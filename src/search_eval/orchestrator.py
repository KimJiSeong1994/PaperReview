"""Coordinator-owned, import-only SkillOpt sealed provenance lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from .accepted_candidate import (
    ACCEPTANCE_MANIFEST_VERSION,
    validate_acceptance_manifest,
)
from .skillopt_contract import ValidationError
from .skillopt_run_contract import (
    RUN_REQUEST_VERSION,
    RUN_RESULT_VERSION,
    AuthorityContext,
    AuthorityContextRotationError,
    ValidatedRunRequest,
    ValidatedRunResult,
    StableFile,
    canonical_json_bytes,
    capture_run_request,
    capture_run_result,
    read_stable_file,
    resolve_authority_context,
    verify_stable_file,
    verify_authority_context_current,
)


ORCHESTRATOR_STATUS_VERSION = "skillopt-orchestrator-status-v2"
ORCHESTRATOR_JOURNAL_VERSION = "skillopt-orchestrator-journal-v2"
ORCHESTRATOR_HEARTBEAT_VERSION = "skillopt-orchestrator-heartbeat-v2"
CONSUMPTION_RECORD_VERSION = "skillopt-consumption-record-v1"
INCIDENT_VERSION = "skillopt-replay-incident-v1"
QUARANTINE_VERSION = "skillopt-quarantine-metadata-v2"
_TERMINAL_STATES = {
    "dry_run_complete",
    "candidate_ready",
    "failed",
    "timed_out",
    "cancelled",
    "quarantined",
}
_NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_STATUS_KEYS = {
    "version",
    "request_id",
    "request_sha256",
    "result_id",
    "result_sha256",
    "state",
    "terminal",
    "reason",
    "updated_at",
    "heartbeat_path",
    "journal_path",
    "result_path",
    "quarantine_path",
    "acceptance_manifest_path",
    "acceptance_manifest_hash",
}
_HEARTBEAT_KEYS = {
    "version",
    "request_id",
    "request_sha256",
    "state",
    "updated_at",
}
_JOURNAL_KEYS = {"version", "request_id", "events"}
_JOURNAL_EVENT_BASE_KEYS = {
    "sequence",
    "old_state",
    "state",
    "at",
    "reason",
    "request_sha256",
    "result_sha256",
}
_JOURNAL_EVENT_ACCEPTANCE_KEYS = {
    "acceptance_manifest_path",
    "acceptance_manifest_hash",
}
_CONSUMED_TERMINAL_STATES = {"candidate_ready", "failed", "timed_out", "cancelled"}


@dataclass(frozen=True)
class _LifecycleArtifactSnapshot:
    name: str
    existed: bool
    payload: bytes | None


@dataclass(frozen=True)
class _LifecycleSnapshot:
    artifacts: tuple[_LifecycleArtifactSnapshot, ...]


@dataclass(frozen=True)
class _FileArtifactSnapshot:
    path: Path
    existed: bool
    payload: bytes | None
    parent_existed: bool


@dataclass
class _ConsumptionRecordWriteToken:
    path: Path | None = None
    payload: bytes | None = None


def run_orchestrator(
    *,
    run_root: str | Path,
    request_path: str | Path,
    dry_run: bool = False,
    import_result_path: str | Path | None = None,
    cancel: bool = False,
    coordinator_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate one action under a coordinator-global consumption namespace."""
    if sum((dry_run, import_result_path is not None, cancel)) != 1:
        raise ValidationError(
            "orchestrator requires exactly one of dry_run, import_result_path, or cancel"
        )
    if coordinator_root is not None:
        raise ValidationError(
            "per-call coordinator_root is forbidden; use the external authority context"
        )
    root = _prepare_root(run_root, create=True, label="orchestrator run_root")
    request_file = Path(request_path)
    stable_lock_path = root / ".skillopt-orchestrator.lock"
    if stable_lock_path.is_symlink():
        raise ValidationError("orchestrator stable run_root lock must not be a symlink")
    try:
        with FileLock(str(stable_lock_path), timeout=10):
            return _run_with_stable_root_lock(
                root=root,
                request_file=request_file,
                import_result_path=Path(import_result_path)
                if import_result_path is not None
                else None,
                dry_run=dry_run,
                cancel=cancel,
            )
    except Timeout:
        return _busy_status(
            root,
            _file_identity(request_file),
            reason="stable run_root lifecycle lock is held",
        )


def _run_with_stable_root_lock(
    *,
    root: Path,
    request_file: Path,
    import_result_path: Path | None,
    dry_run: bool,
    cancel: bool,
) -> dict[str, Any]:
    """Acquire the authority-derived request lock after the stable root lock."""
    authority_context = resolve_authority_context()
    request_held = None
    try:
        request_held = read_stable_file(request_file)
        request = _decode_canonical_sealed(
            request_held.payload, RUN_REQUEST_VERSION, "request"
        )
        request_id = _require_sealed_id(request, "request_id", RUN_REQUEST_VERSION)
        namespace = authority_context.coordinator_namespace
    except ValidationError as exc:
        return _quarantine_invalid_request(
            root, request_file, exc, source_held=request_held
        )

    coordinator = authority_context.coordinator_root
    namespace_root = coordinator / "namespaces" / namespace
    lock_path = namespace_root / "locks" / f"{request_id}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(lock_path), timeout=10):
            return _run_locked(
                root=root,
                namespace_root=namespace_root,
                authority_context=authority_context,
                request=request,
                request_held=request_held,
                import_result_path=import_result_path,
                dry_run=dry_run,
                cancel=cancel,
            )
    except Timeout:
        return _busy_status(
            root,
            request_id,
            reason="coordinator-global request lock is held",
        )


def _run_locked(
    *,
    root: Path,
    namespace_root: Path,
    authority_context: AuthorityContext,
    request: Mapping[str, Any],
    request_held: Any,
    import_result_path: Path | None,
    dry_run: bool,
    cancel: bool,
) -> dict[str, Any]:
    request_id = str(request["request_id"])
    record_path = namespace_root / "consumed" / f"{request_id}.json"
    existing_record = _load_optional_canonical(record_path)
    if (
        existing_record is not None
        and existing_record.get("state") in _CONSUMED_TERMINAL_STATES
    ):
        return _handle_terminal_consumed_replay(
            root=root,
            namespace_root=namespace_root,
            authority_context=authority_context,
            request=request,
            request_held=request_held,
            import_result_path=import_result_path,
            record=existing_record,
            dry_run=dry_run,
            cancel=cancel,
        )
    try:
        validated_request = capture_run_request(
            request,
            run_root=root,
            raw_bytes=request_held.payload,
            authority_context=authority_context,
        )
    except AuthorityContextRotationError as exc:
        _record_authority_rotation_incident(
            root=root,
            namespace_root=namespace_root,
            request_id=request_id,
            request_sha256=request_held.sha256,
            result_sha256=None,
            existing_record=existing_record,
            phase="request capture",
            exc=exc,
        )
        raise
    except ValidationError as exc:
        return _quarantine(
            root=root,
            request_id=request_id,
            reason=f"invalid_request: {exc}",
            source_path=request_held.path,
            source_name="run_request.json",
            source_held=request_held,
            authority_context=authority_context,
            namespace_root=namespace_root,
            incident_request_sha256=request_held.sha256,
            existing_record=existing_record,
        )
    result_held = None
    result = None
    if import_result_path is not None:
        try:
            result_held = read_stable_file(import_result_path)
            result = _decode_canonical_sealed(
                result_held.payload, RUN_RESULT_VERSION, "result"
            )
            _require_sealed_id(result, "result_id", RUN_RESULT_VERSION)
        except ValidationError as exc:
            result_sha256 = result_held.sha256 if result_held is not None else None
            if existing_record is not None:
                try:
                    recovered = _recover_or_return_recorded_consumption(
                        invocation_root=root,
                        request=validated_request,
                        request_held=request_held,
                        record=existing_record,
                    )
                except AuthorityContextRotationError as recovery_exc:
                    _record_replay_incident(
                        root=root,
                        namespace_root=namespace_root,
                        request_id=request_id,
                        request_sha256=request_held.sha256,
                        result_sha256=result_sha256,
                        existing_record=existing_record,
                        reason=(
                            "authority rotation during malformed replay recovery: "
                            f"{recovery_exc}"
                        ),
                    )
                    raise
                except ValidationError as recovery_exc:
                    _record_replay_incident(
                        root=root,
                        namespace_root=namespace_root,
                        request_id=request_id,
                        request_sha256=request_held.sha256,
                        result_sha256=result_sha256,
                        existing_record=existing_record,
                        reason=(
                            "inconsistent durable consumption record after malformed "
                            f"replay: {recovery_exc}"
                        ),
                    )
                    raise
                _record_replay_incident(
                    root=root,
                    namespace_root=namespace_root,
                    request_id=request_id,
                    request_sha256=request_held.sha256,
                    result_sha256=result_sha256,
                    existing_record=existing_record,
                    reason=f"malformed replay import ignored after consumption: {exc}",
                )
                return recovered
            return _quarantine(
                root=root,
                request_id=request_id,
                reason=f"invalid_import_result: {exc}",
                source_path=import_result_path,
                source_name="run_result.json",
                source_held=result_held,
                authority_context=authority_context,
                namespace_root=namespace_root,
                incident_request_sha256=request_held.sha256,
                result_sha256=result_sha256,
            )
    if existing_record is not None:
        if result is not None and result_held is not None:
            same = (
                existing_record.get("request_sha256") == request_held.sha256
                and existing_record.get("result_sha256") == result_held.sha256
            )
            if same:
                try:
                    return _recover_or_return_consumption(
                        invocation_root=root,
                        request=validated_request,
                        request_held=request_held,
                        result=result,
                        result_held=result_held,
                        record=existing_record,
                    )
                except AuthorityContextRotationError as exc:
                    _record_replay_incident(
                        root=root,
                        namespace_root=namespace_root,
                        request_id=request_id,
                        request_sha256=request_held.sha256,
                        result_sha256=result_held.sha256,
                        existing_record=existing_record,
                        reason=f"authority rotation during consumed replay: {exc}",
                    )
                    raise
                except ValidationError as exc:
                    if "heartbeat" in str(exc):
                        _record_replay_incident(
                            root=root,
                            namespace_root=namespace_root,
                            request_id=request_id,
                            request_sha256=request_held.sha256,
                            result_sha256=result_held.sha256,
                            existing_record=existing_record,
                            reason=f"unrecoverable lifecycle heartbeat: {exc}",
                        )
                        raise
                    return _replay_incident(
                        root=root,
                        namespace_root=namespace_root,
                        authority_context=authority_context,
                        request_id=request_id,
                        request_sha256=request_held.sha256,
                        result_sha256=result_held.sha256,
                        existing_record=existing_record,
                        reason=f"inconsistent durable consumption record: {exc}",
                    )
            return _replay_incident(
                root=root,
                namespace_root=namespace_root,
                authority_context=authority_context,
                request_id=request_id,
                request_sha256=request_held.sha256,
                result_sha256=result_held.sha256,
                existing_record=existing_record,
                reason="conflicting result or terminal replacement for consumed request",
            )
        return _replay_incident(
            root=root,
            namespace_root=namespace_root,
            authority_context=authority_context,
            request_id=request_id,
            request_sha256=request_held.sha256,
            result_sha256=None,
            existing_record=existing_record,
            reason="consumed import cannot be replaced by a non-import action",
        )

    status_path = root / "status.json"
    existing = _load_optional_json(status_path)
    resumable_state = None
    replaying_candidate_ready = False
    replay_recorded_at = None
    if existing is not None:
        if existing.get("request_id") != request_id:
            return _replay_incident(
                root=root,
                namespace_root=namespace_root,
                authority_context=authority_context,
                request_id=request_id,
                request_sha256=request_held.sha256,
                result_sha256=result_held.sha256 if result_held else None,
                existing_record=None,
                reason="run_root already belongs to a different request",
            )
        state = existing.get("state")
        if state in _TERMINAL_STATES:
            if state == "dry_run_complete" and result is not None:
                pass
            elif state == "dry_run_complete" and dry_run:
                verify_authority_context_current(authority_context)
                return existing
            elif state == "cancelled" and cancel:
                verify_authority_context_current(authority_context)
                return existing
            elif state == "candidate_ready" and result is not None and result_held:
                try:
                    replay_recorded_at = (
                        _validate_candidate_ready_replay_without_namespace_record(
                            root=root,
                            status=existing,
                            authority_context=authority_context,
                            request=request,
                            request_held=request_held,
                            result=result,
                            result_held=result_held,
                        )
                    )
                except ValidationError as exc:
                    return _replay_incident(
                        root=root,
                        namespace_root=namespace_root,
                        authority_context=authority_context,
                        request_id=request_id,
                        request_sha256=request_held.sha256,
                        result_sha256=result_held.sha256,
                        existing_record=None,
                        reason=f"terminal lifecycle replacement is forbidden: {exc}",
                    )
                resumable_state = state
                replaying_candidate_ready = True
            else:
                return _replay_incident(
                    root=root,
                    namespace_root=namespace_root,
                    authority_context=authority_context,
                    request_id=request_id,
                    request_sha256=request_held.sha256,
                    result_sha256=result_held.sha256 if result_held else None,
                    existing_record=None,
                    reason="terminal lifecycle replacement is forbidden",
                )
        else:
            _validate_resumable_request_lifecycle(
                root=root,
                status=existing,
                request_id=request_id,
                request_sha256=request_held.sha256,
            )
            resumable_state = str(state)

    snapshot_path = root / "artifacts" / "run_request.json"
    if snapshot_path.exists():
        snapshot = read_stable_file(snapshot_path)
        if snapshot.payload != request_held.payload:
            return _replay_incident(
                root=root,
                namespace_root=namespace_root,
                authority_context=authority_context,
                request_id=request_id,
                request_sha256=request_held.sha256,
                result_sha256=result_held.sha256 if result_held else None,
                existing_record=None,
                reason="request snapshot differs from exact incoming request bytes",
            )
    else:
        verify_stable_file(request_held)
        _write_bytes_atomic(snapshot_path, request_held.payload)

    if resumable_state is None:
        _transition(
            root=root,
            request_id=request_id,
            request_sha256=request_held.sha256,
            state="requested",
            terminal=False,
            reason="authoritative sealed request validated",
        )
    if cancel:
        try:
            return _run_terminal_lifecycle_transaction(
                root=root,
                authority_context=authority_context,
                operation=lambda: _transition(
                    root=root,
                    request_id=request_id,
                    request_sha256=request_held.sha256,
                    state="cancelled",
                    terminal=True,
                    reason="cancelled before any external execution or import",
                ),
            )
        except AuthorityContextRotationError as exc:
            _record_authority_rotation_incident(
                root=root,
                namespace_root=namespace_root,
                request_id=request_id,
                request_sha256=request_held.sha256,
                result_sha256=None,
                existing_record=None,
                phase="cancel terminal transaction",
                exc=exc,
            )
            raise
    if dry_run:
        if resumable_state != "running":
            _transition(
                root=root,
                request_id=request_id,
                request_sha256=request_held.sha256,
                state="running",
                terminal=False,
                reason="credential-free dry-run validation in progress",
            )
        try:
            return _run_terminal_lifecycle_transaction(
                root=root,
                authority_context=authority_context,
                operation=lambda: _transition(
                    root=root,
                    request_id=request_id,
                    request_sha256=request_held.sha256,
                    state="dry_run_complete",
                    terminal=True,
                    reason="request validated with execution, provider, network, and credentials disabled",
                ),
            )
        except AuthorityContextRotationError as exc:
            _record_authority_rotation_incident(
                root=root,
                namespace_root=namespace_root,
                request_id=request_id,
                request_sha256=request_held.sha256,
                result_sha256=None,
                existing_record=None,
                phase="dry-run terminal transaction",
                exc=exc,
            )
            raise

    assert result is not None and result_held is not None
    expected_result = root / str(request["output"]["result_manifest_path"])
    if result_held.path != expected_result.resolve(strict=True):
        return _quarantine(
            root=root,
            request_id=request_id,
            reason="invalid_import_result: import path does not equal requested result_manifest_path",
            source_path=result_held.path,
            source_name="run_result.json",
            source_held=result_held,
            authority_context=authority_context,
            namespace_root=namespace_root,
            incident_request_sha256=request_held.sha256,
            result_sha256=result_held.sha256,
        )
    if resumable_state not in {"running", "candidate_ready"}:
        _transition(
            root=root,
            request_id=request_id,
            request_sha256=request_held.sha256,
            state="running",
            terminal=False,
            reason="sealed import validation in progress",
        )
    try:
        validated_result = capture_run_result(
            result,
            request=request,
            run_root=root,
            raw_bytes=result_held.payload,
            request_capture=validated_request,
        )
    except AuthorityContextRotationError as exc:
        _record_authority_rotation_incident(
            root=root,
            namespace_root=namespace_root,
            request_id=request_id,
            request_sha256=request_held.sha256,
            result_sha256=result_held.sha256,
            existing_record=None,
            phase="result capture",
            exc=exc,
        )
        raise
    except ValidationError as exc:
        return _quarantine(
            root=root,
            request_id=request_id,
            reason=f"invalid_import_result: {exc}",
            source_path=result_held.path,
            source_name="run_result.json",
            source_held=result_held,
            authority_context=authority_context,
            namespace_root=namespace_root,
            incident_request_sha256=request_held.sha256,
            result_sha256=result_held.sha256,
        )

    try:
        if replaying_candidate_ready:
            assert existing is not None
            publication = {
                "acceptance_manifest_path": existing["acceptance_manifest_path"],
                "acceptance_manifest_hash": existing["acceptance_manifest_hash"],
            }
        else:
            publication = _publish_import(
                root=root,
                authority_context=authority_context,
                request=validated_request,
                request_held=request_held,
                result=validated_result,
                result_held=result_held,
            )
        result_state = {
            "succeeded": "candidate_ready",
            "failed": "failed",
            "timed_out": "timed_out",
            "cancelled": "cancelled",
        }[str(result["status"])]
        acceptance_path = publication.get("acceptance_manifest_path")
        acceptance_hash = publication.get("acceptance_manifest_hash")
        record = {
            "version": CONSUMPTION_RECORD_VERSION,
            "request_id": request_id,
            "request_sha256": request_held.sha256,
            "result_id": result["result_id"],
            "result_sha256": result_held.sha256,
            "run_root": str(root),
            "state": result_state,
            "policy_identity": authority_context.policy_identity,
            "coordinator_id": authority_context.coordinator_id,
            "coordinator_namespace": authority_context.coordinator_namespace,
            "acceptance_manifest_path": acceptance_path,
            "acceptance_manifest_hash": acceptance_hash,
            "recorded_at": replay_recorded_at or _utc_now(),
        }
    except AuthorityContextRotationError as exc:
        _record_authority_rotation_incident(
            root=root,
            namespace_root=namespace_root,
            request_id=request_id,
            request_sha256=request_held.sha256,
            result_sha256=result_held.sha256,
            existing_record=None,
            phase="import publication",
            exc=exc,
        )
        raise
    except (OSError, ValidationError) as exc:
        return _quarantine(
            root=root,
            request_id=request_id,
            reason=f"import_publication_failed: {exc}",
            source_path=result_held.path,
            source_name="run_result.json",
            source_held=result_held,
            authority_context=authority_context,
            namespace_root=namespace_root,
            incident_request_sha256=request_held.sha256,
            result_sha256=result_held.sha256,
        )

    record_write = _ConsumptionRecordWriteToken()
    try:
        return _run_terminal_lifecycle_transaction(
            root=root,
            authority_context=authority_context,
            consumption_record_writes=(record_write,),
            operation=lambda: _write_record_and_transition_terminal_import(
                record_path=record_path,
                record=record,
                record_write=record_write,
                root=root,
                authority_context=authority_context,
                request_id=request_id,
                request_sha256=request_held.sha256,
                result_id=str(result["result_id"]),
                result_sha256=result_held.sha256,
                state=result_state,
                reason=f"sealed import consumed with status={result['status']}",
                result_path=str(root / "artifacts" / "run_result.json"),
                acceptance_manifest_path=acceptance_path,
                acceptance_manifest_hash=acceptance_hash,
            ),
        )
    except AuthorityContextRotationError as exc:
        _record_authority_rotation_incident(
            root=root,
            namespace_root=namespace_root,
            request_id=request_id,
            request_sha256=request_held.sha256,
            result_sha256=result_held.sha256,
            existing_record=record,
            phase="import terminal transaction",
            exc=exc,
        )
        raise


def _handle_terminal_consumed_replay(
    *,
    root: Path,
    namespace_root: Path,
    authority_context: AuthorityContext,
    request: Mapping[str, Any],
    request_held: Any,
    import_result_path: Path | None,
    record: Mapping[str, Any],
    dry_run: bool,
    cancel: bool,
) -> dict[str, Any]:
    request_id = str(request["request_id"])
    if (
        record.get("request_id") != request_id
        or record.get("request_sha256") != request_held.sha256
    ):
        return _replay_incident(
            root=root,
            namespace_root=namespace_root,
            authority_context=authority_context,
            request_id=request_id,
            request_sha256=request_held.sha256,
            result_sha256=None,
            existing_record=record,
            reason="conflicting request identity for consumed request",
        )
    if import_result_path is None:
        action = "dry_run" if dry_run else "cancel" if cancel else "non-import"
        return _replay_incident(
            root=root,
            namespace_root=namespace_root,
            authority_context=authority_context,
            request_id=request_id,
            request_sha256=request_held.sha256,
            result_sha256=None,
            existing_record=record,
            reason=f"consumed import cannot be replaced by a {action} action",
        )

    result_held = None
    try:
        result_held = read_stable_file(import_result_path)
        result = _decode_canonical_sealed(
            result_held.payload, RUN_RESULT_VERSION, "result"
        )
        _require_sealed_id(result, "result_id", RUN_RESULT_VERSION)
    except ValidationError as exc:
        result_sha256 = result_held.sha256 if result_held is not None else None
        try:
            recovered = _recover_or_return_terminal_consumption(
                authority_context=authority_context,
                request=request,
                request_held=request_held,
                incoming_result_held=None,
                record=record,
            )
        except AuthorityContextRotationError as recovery_exc:
            _record_replay_incident(
                root=root,
                namespace_root=namespace_root,
                request_id=request_id,
                request_sha256=request_held.sha256,
                result_sha256=result_sha256,
                existing_record=record,
                reason=(
                    "authority rotation during malformed replay recovery: "
                    f"{recovery_exc}"
                ),
            )
            raise
        except ValidationError as recovery_exc:
            _record_replay_incident(
                root=root,
                namespace_root=namespace_root,
                request_id=request_id,
                request_sha256=request_held.sha256,
                result_sha256=result_sha256,
                existing_record=record,
                reason=(
                    "inconsistent durable consumption record after malformed "
                    f"replay: {recovery_exc}"
                ),
            )
            raise
        _record_original_evidence_drift_incident(
            root=root,
            namespace_root=namespace_root,
            request=request,
            request_sha256=request_held.sha256,
            result_sha256=result_sha256,
            existing_record=record,
        )
        _record_replay_incident(
            root=root,
            namespace_root=namespace_root,
            request_id=request_id,
            request_sha256=request_held.sha256,
            result_sha256=result_sha256,
            existing_record=record,
            reason=f"malformed replay import ignored after consumption: {exc}",
        )
        return recovered

    if record.get("result_sha256") != result_held.sha256:
        return _replay_incident(
            root=root,
            namespace_root=namespace_root,
            authority_context=authority_context,
            request_id=request_id,
            request_sha256=request_held.sha256,
            result_sha256=result_held.sha256,
            existing_record=record,
            reason="conflicting result or terminal replacement for consumed request",
        )
    try:
        recovered = _recover_or_return_terminal_consumption(
            authority_context=authority_context,
            request=request,
            request_held=request_held,
            incoming_result_held=result_held,
            record=record,
        )
    except AuthorityContextRotationError as exc:
        _record_replay_incident(
            root=root,
            namespace_root=namespace_root,
            request_id=request_id,
            request_sha256=request_held.sha256,
            result_sha256=result_held.sha256,
            existing_record=record,
            reason=f"authority rotation during consumed replay: {exc}",
        )
        raise
    except ValidationError as exc:
        if "heartbeat" in str(exc):
            _record_replay_incident(
                root=root,
                namespace_root=namespace_root,
                request_id=request_id,
                request_sha256=request_held.sha256,
                result_sha256=result_held.sha256,
                existing_record=record,
                reason=f"unrecoverable lifecycle heartbeat: {exc}",
            )
            raise
        return _replay_incident(
            root=root,
            namespace_root=namespace_root,
            authority_context=authority_context,
            request_id=request_id,
            request_sha256=request_held.sha256,
            result_sha256=result_held.sha256,
            existing_record=record,
            reason=f"inconsistent durable consumption record: {exc}",
        )
    _record_original_evidence_drift_incident(
        root=root,
        namespace_root=namespace_root,
        request=request,
        request_sha256=request_held.sha256,
        result_sha256=result_held.sha256,
        existing_record=record,
    )
    return recovered


def _validate_candidate_ready_replay_without_namespace_record(
    *,
    root: Path,
    status: Mapping[str, Any],
    authority_context: AuthorityContext,
    request: Mapping[str, Any],
    request_held: Any,
    result: Mapping[str, Any],
    result_held: Any,
) -> str:
    """Allow exact accepted replay after coordinator-root authority rotation only."""
    if result.get("status") != "succeeded":
        raise ValidationError("candidate_ready replay result is not succeeded")
    manifest_path = root / "artifacts" / "acceptance_manifest.json"
    manifest_held = read_stable_file(manifest_path)
    expected = {
        "request_id": request["request_id"],
        "request_sha256": request_held.sha256,
        "result_id": result["result_id"],
        "result_sha256": result_held.sha256,
        "state": "candidate_ready",
        "acceptance_manifest_path": str(manifest_path),
        "acceptance_manifest_hash": manifest_held.sha256,
    }
    _validate_terminal_status(status, expected, root)
    journal = _load_optional_json(root / "stage_journal.json")
    _validate_recoverable_terminal_journal(
        journal=journal,
        expected=expected,
        allow_running_tail=False,
    )
    sealed_request = read_stable_file(root / "artifacts" / "run_request.json")
    sealed_result = read_stable_file(root / "artifacts" / "run_result.json")
    if (
        sealed_request.payload != request_held.payload
        or sealed_result.payload != result_held.payload
    ):
        raise ValidationError(
            "candidate_ready replay differs from accepted sealed bytes"
        )
    manifest = _decode_canonical_sealed(
        manifest_held.payload, ACCEPTANCE_MANIFEST_VERSION, "acceptance manifest"
    )
    bindings = manifest.get("bindings")
    if not isinstance(bindings, Mapping):
        raise ValidationError("candidate_ready replay manifest bindings are invalid")
    expected_bindings = {
        "request_sha256": request_held.sha256,
        "result_sha256": result_held.sha256,
        "policy_identity": authority_context.policy_identity,
        "coordinator_id": authority_context.coordinator_id,
        "coordinator_namespace": authority_context.coordinator_namespace,
    }
    for field, value in expected_bindings.items():
        if bindings.get(field) != value:
            raise ValidationError(f"candidate_ready replay manifest {field} mismatch")
    validate_acceptance_manifest(manifest, run_root=root)
    assert journal is not None
    events = journal["events"]
    recorded_at = events[-1]["at"]
    _require_recorded_at(recorded_at)
    return str(recorded_at)


def _publish_import(
    *,
    root: Path,
    authority_context: AuthorityContext,
    request: ValidatedRunRequest,
    request_held: Any,
    result: Mapping[str, Any],
    result_held: Any,
) -> dict[str, Any]:
    if request.authority_context is not authority_context:
        raise ValidationError("publication authority snapshot identity mismatch")
    for held in request.evidence.values():
        verify_stable_file(held)
    for held in result.outputs.values():
        if held is not None:
            verify_stable_file(held)
    for held in result.receipts.values():
        verify_stable_file(held)
    verify_stable_file(request_held)
    verify_stable_file(result_held)
    sealed_request_path = root / "artifacts" / "run_request.json"
    if not sealed_request_path.exists():
        _write_bytes_atomic(sealed_request_path, request_held.payload)
    sealed_result_path = root / "artifacts" / "run_result.json"
    _write_bytes_atomic(sealed_result_path, result_held.payload)

    evidence_snapshots: dict[str, Any] = {}
    for name, held in request.evidence.items():
        suffix = held.path.suffix or ".bin"
        destination = root / "artifacts" / "evidence" / f"{name}{suffix}"
        _write_bytes_atomic(destination, held.payload)
        evidence_snapshots[name] = _file_entry(root, destination)

    accepted_outputs: dict[str, Any] = {}
    output_destinations = {
        "best_skill": root / "artifacts" / "accepted_best_skill.md",
        "evaluation": root / "artifacts" / "accepted_evaluation.json",
        "sanitized_summary": root / "artifacts" / "accepted_sanitized_summary.json",
    }
    for name, held in result.outputs.items():
        if held is None:
            accepted_outputs[name] = None
        else:
            _write_bytes_atomic(output_destinations[name], held.payload)
            accepted_outputs[name] = _file_entry(root, output_destinations[name])
    accepted_receipts: dict[str, Any] = {}
    for name, held in result.receipts.items():
        destination = root / "artifacts" / f"accepted_{name}_receipt.json"
        _write_bytes_atomic(destination, held.payload)
        accepted_receipts[name] = _file_entry(root, destination)

    if result.result["status"] != "succeeded":
        return {"acceptance_manifest_path": None, "acceptance_manifest_hash": None}
    manifest_path = root / "artifacts" / "acceptance_manifest.json"
    manifest = {
        "version": ACCEPTANCE_MANIFEST_VERSION,
        "request_id": request.request["request_id"],
        "result_id": result.result["result_id"],
        "accepted_at": _utc_now(),
        "sealed_request": _file_entry(root, sealed_request_path),
        "sealed_result": _file_entry(root, sealed_result_path),
        "evidence_snapshots": evidence_snapshots,
        "accepted_outputs": accepted_outputs,
        "accepted_receipts": accepted_receipts,
        "bindings": {
            "profile_identity": request.profile["identity"],
            "overlay_identity": request.profile["overlay_manifest"]["identity"],
            "staging_identity": request.profile["staging_manifest"]["identity"],
            "runner_identity": request.profile["runner_identity"]["identity"],
            "custody_identity": request.profile["custody_evidence"]["identity"],
            "usage_receipt_identity": result.receipt_json["usage"]["identity"],
            "privacy_receipt_identity": result.receipt_json["privacy"]["identity"],
            "request_sha256": request_held.sha256,
            "request_size_bytes": request_held.size_bytes,
            "result_sha256": result_held.sha256,
            "result_size_bytes": result_held.size_bytes,
            "policy_identity": authority_context.policy_identity,
            "coordinator_id": authority_context.coordinator_id,
            "coordinator_namespace": authority_context.coordinator_namespace,
        },
    }
    _write_json_atomic(manifest_path, manifest)
    validate_acceptance_manifest(manifest, run_root=root)
    return {
        "acceptance_manifest_path": str(manifest_path),
        "acceptance_manifest_hash": _file_entry(root, manifest_path)["sha256"],
    }


def _terminal_snapshot_entries(
    *,
    root: Path,
    request: Mapping[str, Any],
    result: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Describe the immutable snapshots published for a non-success terminal run."""
    evidence_snapshots = {}
    for name, entry in request["input_artifacts"].items():
        suffix = Path(str(entry["path"])).suffix or ".bin"
        evidence_snapshots[name] = _file_entry(
            root, root / "artifacts" / "evidence" / f"{name}{suffix}"
        )
    output_paths = {
        "best_skill": root / "artifacts" / "accepted_best_skill.md",
        "evaluation": root / "artifacts" / "accepted_evaluation.json",
        "sanitized_summary": root / "artifacts" / "accepted_sanitized_summary.json",
    }
    output_snapshots = {
        name: None if entry is None else _file_entry(root, output_paths[name])
        for name, entry in result["outputs"].items()
    }
    receipt_snapshots = {
        name: _file_entry(root, root / "artifacts" / f"accepted_{name}_receipt.json")
        for name in result["receipts"]
    }
    return evidence_snapshots, output_snapshots, receipt_snapshots


def _recover_or_return_terminal_consumption(
    *,
    authority_context: AuthorityContext,
    request: Mapping[str, Any],
    request_held: Any,
    incoming_result_held: Any | None,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Recover any consumed terminal replay from immutable durable snapshots."""
    expected_keys = {
        "version",
        "request_id",
        "request_sha256",
        "result_id",
        "result_sha256",
        "run_root",
        "state",
        "policy_identity",
        "coordinator_id",
        "coordinator_namespace",
        "acceptance_manifest_path",
        "acceptance_manifest_hash",
        "recorded_at",
    }
    if (
        set(record) != expected_keys
        or record.get("version") != CONSUMPTION_RECORD_VERSION
    ):
        raise ValidationError("consumption record schema/version mismatch")
    record_state = record.get("state")
    if record_state not in _CONSUMED_TERMINAL_STATES:
        raise ValidationError("consumption record state is invalid")
    expected_record = {
        "request_id": request["request_id"],
        "request_sha256": request_held.sha256,
        "policy_identity": authority_context.policy_identity,
        "coordinator_id": authority_context.coordinator_id,
        "coordinator_namespace": authority_context.coordinator_namespace,
    }
    for field, value in expected_record.items():
        if record.get(field) != value:
            raise ValidationError(f"consumption record {field} mismatch")
    _require_recorded_at(record.get("recorded_at"))
    recorded_root_value = record.get("run_root")
    if (
        not isinstance(recorded_root_value, str)
        or not Path(recorded_root_value).is_absolute()
    ):
        raise ValidationError("consumption record run_root is invalid")
    recorded_root = _prepare_root(
        recorded_root_value, create=False, label="consumption record run_root"
    )
    sealed_request = read_stable_file(recorded_root / "artifacts" / "run_request.json")
    sealed_result = read_stable_file(recorded_root / "artifacts" / "run_result.json")
    if sealed_request.sha256 != request_held.sha256 or (
        sealed_request.payload != request_held.payload
    ):
        raise ValidationError("durable sealed request/result bytes mismatch")
    if incoming_result_held is not None and (
        sealed_result.sha256 != incoming_result_held.sha256
        or sealed_result.payload != incoming_result_held.payload
    ):
        raise ValidationError("durable sealed request/result bytes mismatch")
    if sealed_result.sha256 != record.get("result_sha256"):
        raise ValidationError("consumption record result_sha256 mismatch")
    result = _decode_canonical_sealed(
        sealed_result.payload, RUN_RESULT_VERSION, "result"
    )
    _require_sealed_id(result, "result_id", RUN_RESULT_VERSION)
    expected_state = {
        "succeeded": "candidate_ready",
        "failed": "failed",
        "timed_out": "timed_out",
        "cancelled": "cancelled",
    }.get(str(result.get("status")))
    if expected_state != record_state:
        raise ValidationError("consumption record state does not match sealed result")
    if result.get("result_id") != record.get("result_id"):
        raise ValidationError("consumption record result_id mismatch")
    acceptance_path = record.get("acceptance_manifest_path")
    acceptance_hash = record.get("acceptance_manifest_hash")
    if expected_state == "candidate_ready":
        expected_manifest = recorded_root / "artifacts" / "acceptance_manifest.json"
        if acceptance_path != str(expected_manifest):
            raise ValidationError("consumption acceptance manifest path mismatch")
        manifest_held = read_stable_file(expected_manifest)
        if manifest_held.sha256 != acceptance_hash:
            raise ValidationError("consumption acceptance manifest hash mismatch")
        manifest = _decode_canonical_sealed(
            manifest_held.payload, ACCEPTANCE_MANIFEST_VERSION, "acceptance manifest"
        )
        if (
            manifest.get("request_id") != request["request_id"]
            or manifest.get("result_id") != result["result_id"]
            or manifest.get("bindings", {}).get("request_sha256") != request_held.sha256
            or manifest.get("bindings", {}).get("result_sha256") != sealed_result.sha256
        ):
            raise ValidationError("durable acceptance manifest lineage mismatch")
        validate_acceptance_manifest(manifest, run_root=recorded_root)
        evidence_snapshots = manifest["evidence_snapshots"]
        output_snapshots = manifest["accepted_outputs"]
        receipt_snapshots = manifest["accepted_receipts"]
    else:
        if acceptance_path is not None or acceptance_hash is not None:
            raise ValidationError("non-success consumption record claims acceptance")
        evidence_snapshots, output_snapshots, receipt_snapshots = (
            _terminal_snapshot_entries(
                root=recorded_root,
                request=request,
                result=result,
            )
        )
    durable_request = capture_run_request(
        _decode_canonical_sealed(
            sealed_request.payload, RUN_REQUEST_VERSION, "request"
        ),
        run_root=recorded_root,
        raw_bytes=sealed_request.payload,
        evidence_snapshots=evidence_snapshots,
        authority_context=authority_context,
    )
    capture_run_result(
        result,
        request=durable_request.request,
        run_root=recorded_root,
        raw_bytes=sealed_result.payload,
        request_capture=durable_request,
        accepted_outputs=output_snapshots,
        accepted_receipts=receipt_snapshots,
    )

    terminal_expected = {
        "request_id": request["request_id"],
        "request_sha256": request_held.sha256,
        "result_id": result["result_id"],
        "result_sha256": sealed_result.sha256,
        "state": expected_state,
        "acceptance_manifest_path": acceptance_path,
        "acceptance_manifest_hash": acceptance_hash,
    }
    status = _load_optional_json(recorded_root / "status.json")
    journal = _load_optional_json(recorded_root / "stage_journal.json")
    _validate_recoverable_terminal_journal(
        journal=journal,
        expected=terminal_expected,
        allow_running_tail=status is None or status.get("terminal") is not True,
    )
    if status is not None and status.get("terminal") is True:
        _validate_terminal_status(status, terminal_expected, recorded_root)
        return _run_terminal_lifecycle_transaction(
            root=recorded_root,
            authority_context=authority_context,
            operation=lambda: _repair_terminal_heartbeat_and_return_status(
                status=status,
                root=recorded_root,
                request_id=str(request["request_id"]),
                request_sha256=request_held.sha256,
                state=expected_state,
            ),
        )
    if status is not None:
        _validate_recoverable_nonterminal_status(
            status, terminal_expected, recorded_root
        )
    _validate_recoverable_heartbeat(
        root=recorded_root,
        request_id=str(request["request_id"]),
        request_sha256=request_held.sha256,
        allowed_states={"running"},
    )
    return _run_terminal_lifecycle_transaction(
        root=recorded_root,
        authority_context=authority_context,
        operation=lambda: _transition(
            root=recorded_root,
            request_id=str(request["request_id"]),
            request_sha256=request_held.sha256,
            result_id=str(result["result_id"]),
            result_sha256=sealed_result.sha256,
            state=expected_state,
            terminal=True,
            reason=f"recovered sealed import consumed with status={result['status']}",
            result_path=str(recorded_root / "artifacts" / "run_result.json"),
            acceptance_manifest_path=acceptance_path,
            acceptance_manifest_hash=acceptance_hash,
        ),
    )


def _recover_or_return_consumption(
    *,
    invocation_root: Path,
    request: ValidatedRunRequest,
    request_held: Any,
    result: ValidatedRunResult,
    result_held: Any,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Finish a crash-interrupted terminal transition without republishing."""
    expected_keys = {
        "version",
        "request_id",
        "request_sha256",
        "result_id",
        "result_sha256",
        "run_root",
        "state",
        "policy_identity",
        "coordinator_id",
        "coordinator_namespace",
        "acceptance_manifest_path",
        "acceptance_manifest_hash",
        "recorded_at",
    }
    if (
        set(record) != expected_keys
        or record.get("version") != CONSUMPTION_RECORD_VERSION
    ):
        raise ValidationError("consumption record schema/version mismatch")
    expected_state = {
        "succeeded": "candidate_ready",
        "failed": "failed",
        "timed_out": "timed_out",
        "cancelled": "cancelled",
    }[str(result["status"])]
    expected = {
        "request_id": request.request["request_id"],
        "request_sha256": request_held.sha256,
        "result_id": result["result_id"],
        "result_sha256": result_held.sha256,
        "state": expected_state,
        "policy_identity": request.authority_context.policy_identity,
        "coordinator_id": request.authority_context.coordinator_id,
        "coordinator_namespace": request.authority_context.coordinator_namespace,
    }
    for field, value in expected.items():
        if record.get(field) != value:
            raise ValidationError(f"consumption record {field} mismatch")
    _require_recorded_at(record.get("recorded_at"))
    recorded_root_value = record.get("run_root")
    if (
        not isinstance(recorded_root_value, str)
        or not Path(recorded_root_value).is_absolute()
    ):
        raise ValidationError("consumption record run_root is invalid")
    recorded_root = _prepare_root(
        recorded_root_value, create=False, label="consumption record run_root"
    )
    sealed_request = read_stable_file(recorded_root / "artifacts" / "run_request.json")
    sealed_result = read_stable_file(recorded_root / "artifacts" / "run_result.json")
    if (
        sealed_request.sha256 != request_held.sha256
        or sealed_request.payload != request_held.payload
        or sealed_result.sha256 != result_held.sha256
        or sealed_result.payload != result_held.payload
    ):
        raise ValidationError("durable sealed request/result bytes mismatch")
    acceptance_path = record.get("acceptance_manifest_path")
    acceptance_hash = record.get("acceptance_manifest_hash")
    if expected_state == "candidate_ready":
        expected_manifest = recorded_root / "artifacts" / "acceptance_manifest.json"
        if acceptance_path != str(expected_manifest):
            raise ValidationError("consumption acceptance manifest path mismatch")
        manifest_held = read_stable_file(expected_manifest)
        if manifest_held.sha256 != acceptance_hash:
            raise ValidationError("consumption acceptance manifest hash mismatch")
        manifest = _decode_canonical_sealed(
            manifest_held.payload, ACCEPTANCE_MANIFEST_VERSION, "acceptance manifest"
        )
        if (
            manifest.get("request_id") != request.request["request_id"]
            or manifest.get("result_id") != result["result_id"]
            or manifest.get("bindings", {}).get("request_sha256") != request_held.sha256
            or manifest.get("bindings", {}).get("result_sha256") != result_held.sha256
        ):
            raise ValidationError("durable acceptance manifest lineage mismatch")
        validate_acceptance_manifest(manifest, run_root=recorded_root)
        accepted_request = capture_run_request(
            _decode_canonical_sealed(
                sealed_request.payload, RUN_REQUEST_VERSION, "request"
            ),
            run_root=recorded_root,
            raw_bytes=sealed_request.payload,
            evidence_snapshots=manifest["evidence_snapshots"],
            authority_context=request.authority_context,
        )
        capture_run_result(
            result,
            request=accepted_request.request,
            run_root=recorded_root,
            raw_bytes=sealed_result.payload,
            request_capture=accepted_request,
            accepted_outputs=manifest["accepted_outputs"],
            accepted_receipts=manifest["accepted_receipts"],
        )
    elif acceptance_path is not None or acceptance_hash is not None:
        raise ValidationError("non-success consumption record claims acceptance")
    else:
        capture_run_result(
            result,
            request=request.request,
            run_root=invocation_root,
            raw_bytes=result_held.payload,
            request_capture=request,
        )

    terminal_expected = {
        "request_id": request.request["request_id"],
        "request_sha256": request_held.sha256,
        "result_id": result["result_id"],
        "result_sha256": result_held.sha256,
        "state": expected_state,
        "acceptance_manifest_path": acceptance_path,
        "acceptance_manifest_hash": acceptance_hash,
    }
    status = _load_optional_json(recorded_root / "status.json")
    journal = _load_optional_json(recorded_root / "stage_journal.json")
    _validate_recoverable_terminal_journal(
        journal=journal,
        expected=terminal_expected,
        allow_running_tail=status is None or status.get("terminal") is not True,
    )
    if status is not None and status.get("terminal") is True:
        _validate_terminal_status(status, terminal_expected, recorded_root)
        return _run_terminal_lifecycle_transaction(
            root=recorded_root,
            authority_context=request.authority_context,
            operation=lambda: _repair_terminal_heartbeat_and_return_status(
                status=status,
                root=recorded_root,
                request_id=str(request.request["request_id"]),
                request_sha256=request_held.sha256,
                state=expected_state,
            ),
        )
    if status is not None:
        _validate_recoverable_nonterminal_status(
            status, terminal_expected, recorded_root
        )
    _validate_recoverable_heartbeat(
        root=recorded_root,
        request_id=str(request.request["request_id"]),
        request_sha256=request_held.sha256,
        allowed_states={"running"},
    )
    return _run_terminal_lifecycle_transaction(
        root=recorded_root,
        authority_context=request.authority_context,
        operation=lambda: _transition(
            root=recorded_root,
            request_id=str(request.request["request_id"]),
            request_sha256=request_held.sha256,
            result_id=str(result["result_id"]),
            result_sha256=result_held.sha256,
            state=expected_state,
            terminal=True,
            reason=f"recovered sealed import consumed with status={result['status']}",
            result_path=str(recorded_root / "artifacts" / "run_result.json"),
            acceptance_manifest_path=acceptance_path,
            acceptance_manifest_hash=acceptance_hash,
        ),
    )


def _validate_terminal_status(
    status: Mapping[str, Any], expected: Mapping[str, Any], root: Path
) -> None:
    _validate_status_schema(status, root)
    for field, value in expected.items():
        if status.get(field) != value:
            raise ValidationError(f"terminal status {field} mismatch")
    if status.get("terminal") is not True:
        raise ValidationError("terminal status is not marked terminal")
    if status.get("result_path") != str(root / "artifacts" / "run_result.json"):
        raise ValidationError("terminal status result_path mismatch")
    if status.get("quarantine_path") is not None:
        raise ValidationError("terminal status unexpectedly claims quarantine")
    if not isinstance(status.get("result_id"), str):
        raise ValidationError("terminal status result_id is invalid")
    if not isinstance(status.get("result_sha256"), str):
        raise ValidationError("terminal status result_sha256 is invalid")


def _validate_recoverable_nonterminal_status(
    status: Mapping[str, Any], expected: Mapping[str, Any], root: Path
) -> None:
    _validate_status_schema(status, root)
    if status.get("request_id") != expected["request_id"]:
        raise ValidationError("nonterminal status request_id mismatch")
    if status.get("request_sha256") != expected["request_sha256"]:
        raise ValidationError("nonterminal status request_sha256 mismatch")
    if status.get("terminal") is not False or status.get("state") != "running":
        raise ValidationError("crash recovery found impossible nonterminal status")
    for field in (
        "result_id",
        "result_sha256",
        "acceptance_manifest_path",
        "acceptance_manifest_hash",
    ):
        value = status.get(field)
        if value is not None and value != expected[field]:
            raise ValidationError(f"nonterminal status {field} mismatch")
    if status.get("result_path") is not None:
        raise ValidationError("nonterminal status unexpectedly claims result_path")
    if status.get("quarantine_path") is not None:
        raise ValidationError("nonterminal status unexpectedly claims quarantine")


def _validate_resumable_request_lifecycle(
    *,
    root: Path,
    status: Mapping[str, Any],
    request_id: str,
    request_sha256: str,
) -> None:
    """Validate the exact pre-terminal lifecycle left by a rolled-back owner."""
    _validate_status_schema(status, root)
    state = status.get("state")
    if (
        status.get("request_id") != request_id
        or status.get("request_sha256") != request_sha256
        or status.get("terminal") is not False
        or state not in {"requested", "running"}
    ):
        raise ValidationError("run_root nonterminal lifecycle is not resumable")
    for field in (
        "result_id",
        "result_sha256",
        "result_path",
        "quarantine_path",
        "acceptance_manifest_path",
        "acceptance_manifest_hash",
    ):
        if status.get(field) is not None:
            raise ValidationError("run_root nonterminal lifecycle is not resumable")

    journal = _load_optional_json(root / "stage_journal.json")
    if (
        journal is None
        or set(journal) != _JOURNAL_KEYS
        or journal.get("version") != ORCHESTRATOR_JOURNAL_VERSION
        or journal.get("request_id") != request_id
    ):
        raise ValidationError("run_root nonterminal journal is not resumable")
    events = journal.get("events")
    expected_states = (
        ["requested"] if state == "requested" else ["requested", "running"]
    )
    if not isinstance(events, list) or any(
        not isinstance(event, Mapping) for event in events
    ):
        raise ValidationError("run_root nonterminal journal is not resumable")
    if [event.get("state") for event in events] != expected_states:
        raise ValidationError("run_root nonterminal journal is not resumable")
    previous = None
    for sequence, event in enumerate(events, start=1):
        if (
            not isinstance(event, Mapping)
            or set(event) != _JOURNAL_EVENT_BASE_KEYS
            or event.get("sequence") != sequence
            or event.get("old_state") != previous
            or event.get("request_sha256") != request_sha256
            or event.get("result_sha256") is not None
        ):
            raise ValidationError("run_root nonterminal journal is not resumable")
        if not isinstance(event.get("reason"), str) or not event["reason"]:
            raise ValidationError("run_root nonterminal journal is not resumable")
        _require_timestamp(event.get("at"), "stage journal event at")
        previous = event.get("state")
    _validate_recoverable_heartbeat(
        root=root,
        request_id=request_id,
        request_sha256=request_sha256,
        allowed_states={str(state)},
    )


def _validate_status_schema(status: Mapping[str, Any], root: Path) -> None:
    if set(status) != _STATUS_KEYS:
        raise ValidationError("status schema mismatch")
    if status.get("version") != ORCHESTRATOR_STATUS_VERSION:
        raise ValidationError("status version mismatch")
    if status.get("heartbeat_path") != str(root / "heartbeat.json"):
        raise ValidationError("status heartbeat_path mismatch")
    if status.get("journal_path") != str(root / "stage_journal.json"):
        raise ValidationError("status journal_path mismatch")
    if not isinstance(status.get("reason"), str) or not status["reason"]:
        raise ValidationError("status reason is invalid")
    _require_timestamp(status.get("updated_at"), "status updated_at")


def _validate_recoverable_terminal_journal(
    *,
    journal: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
    allow_running_tail: bool,
) -> None:
    if journal is None:
        raise ValidationError("crash recovery requires the durable running journal")
    if set(journal) != _JOURNAL_KEYS:
        raise ValidationError("stage journal schema mismatch")
    if journal.get("version") != ORCHESTRATOR_JOURNAL_VERSION:
        raise ValidationError("stage journal version mismatch")
    if journal.get("request_id") != expected["request_id"]:
        raise ValidationError("stage journal request_id mismatch")
    events = journal.get("events")
    if not isinstance(events, list) or not events:
        raise ValidationError("stage journal events must be a nonempty list")
    previous_state = None
    for index, event in enumerate(events, start=1):
        if not isinstance(event, Mapping) or event.get("sequence") != index:
            raise ValidationError("stage journal sequence mismatch")
        state = event.get("state")
        has_acceptance = expected["acceptance_manifest_path"] is not None and (
            state == expected["state"]
        )
        expected_keys = set(_JOURNAL_EVENT_BASE_KEYS)
        if has_acceptance:
            expected_keys |= _JOURNAL_EVENT_ACCEPTANCE_KEYS
        if set(event) != expected_keys:
            raise ValidationError("stage journal event schema mismatch")
        if event.get("old_state") != previous_state:
            raise ValidationError("stage journal old_state chain mismatch")
        if not isinstance(state, str):
            raise ValidationError("stage journal state is invalid")
        if not isinstance(event.get("reason"), str) or not event["reason"]:
            raise ValidationError("stage journal reason is invalid")
        _require_timestamp(event.get("at"), "stage journal event at")
        if event.get("request_sha256") != expected["request_sha256"]:
            raise ValidationError("stage journal request_sha256 mismatch")
        if state == expected["state"]:
            if event.get("result_sha256") != expected["result_sha256"]:
                raise ValidationError("terminal journal result_sha256 mismatch")
        elif event.get("result_sha256") is not None:
            raise ValidationError("nonterminal journal result_sha256 mismatch")
        previous_state = state
    states = [event.get("state") for event in events]
    if states == ["requested", "running"] and allow_running_tail:
        return
    if states == ["requested", "running", expected["state"]]:
        terminal_event = events[-1]
        for field in ("request_sha256", "result_sha256"):
            if terminal_event.get(field) != expected[field]:
                raise ValidationError(f"terminal journal {field} mismatch")
        if expected["acceptance_manifest_path"] is not None:
            for field in ("acceptance_manifest_path", "acceptance_manifest_hash"):
                if terminal_event.get(field) != expected[field]:
                    raise ValidationError(f"terminal journal {field} mismatch")
        return
    raise ValidationError("crash recovery found impossible lifecycle journal")


def _repair_terminal_heartbeat(
    *, root: Path, request_id: str, request_sha256: str, state: str
) -> None:
    heartbeat = _validate_recoverable_heartbeat(
        root=root,
        request_id=request_id,
        request_sha256=request_sha256,
        allowed_states={"running", state},
    )
    if heartbeat.get("state") != state:
        _heartbeat(root, request_id, request_sha256, state)


def _validate_recoverable_heartbeat(
    *,
    root: Path,
    request_id: str,
    request_sha256: str,
    allowed_states: set[str],
) -> Mapping[str, Any]:
    heartbeat = _load_optional_json(root / "heartbeat.json")
    if heartbeat is None:
        raise ValidationError("heartbeat is missing")
    _validate_heartbeat_schema(
        heartbeat=heartbeat,
        request_id=request_id,
        request_sha256=request_sha256,
        allowed_states=allowed_states,
    )
    return heartbeat


def _validate_heartbeat_schema(
    *,
    heartbeat: Mapping[str, Any],
    request_id: str,
    request_sha256: str,
    allowed_states: set[str],
) -> None:
    if set(heartbeat) != _HEARTBEAT_KEYS:
        raise ValidationError("heartbeat schema mismatch")
    if heartbeat.get("version") != ORCHESTRATOR_HEARTBEAT_VERSION:
        raise ValidationError("heartbeat version mismatch")
    if heartbeat.get("request_id") != request_id:
        raise ValidationError("heartbeat request_id mismatch")
    if heartbeat.get("request_sha256") != request_sha256:
        raise ValidationError("heartbeat request_sha256 mismatch")
    if heartbeat.get("state") not in allowed_states:
        raise ValidationError("heartbeat state cannot be repaired")
    _require_timestamp(heartbeat.get("updated_at"), "heartbeat updated_at")


def _recover_or_return_recorded_consumption(
    *,
    invocation_root: Path,
    request: ValidatedRunRequest,
    request_held: Any,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    recorded_root_value = record.get("run_root")
    if (
        not isinstance(recorded_root_value, str)
        or not Path(recorded_root_value).is_absolute()
    ):
        raise ValidationError("consumption record run_root is invalid")
    recorded_root = _prepare_root(
        recorded_root_value, create=False, label="consumption record run_root"
    )
    result_held = read_stable_file(recorded_root / "artifacts" / "run_result.json")
    result = _decode_canonical_sealed(result_held.payload, RUN_RESULT_VERSION, "result")
    _require_sealed_id(result, "result_id", RUN_RESULT_VERSION)
    return _recover_or_return_consumption(
        invocation_root=invocation_root,
        request=request,
        request_held=request_held,
        result=result,
        result_held=result_held,
        record=record,
    )


def _require_recorded_at(value: Any) -> None:
    _require_timestamp(value, "consumption record recorded_at")


def _require_timestamp(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValidationError(f"{label} is invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{label} is invalid") from exc


def _record_original_evidence_drift_incident(
    *,
    root: Path,
    namespace_root: Path,
    request: Mapping[str, Any],
    request_sha256: str,
    result_sha256: str | None,
    existing_record: Mapping[str, Any],
) -> None:
    artifacts = request.get("input_artifacts")
    if not isinstance(artifacts, Mapping):
        return
    for name, entry in artifacts.items():
        if not isinstance(name, str) or not isinstance(entry, Mapping):
            continue
        path = entry.get("path")
        declared_sha256 = entry.get("sha256")
        declared_size = entry.get("size_bytes")
        if not isinstance(path, str):
            continue
        reason = None
        try:
            held = read_stable_file(path, root=root)
        except ValidationError as exc:
            reason = f"original source evidence drift after consumption: {name}: {exc}"
        else:
            if held.sha256 != declared_sha256 or held.size_bytes != declared_size:
                reason = (
                    "original source evidence drift after consumption: "
                    f"{name}: exact-byte binding mismatch"
                )
        if reason is not None:
            _record_replay_incident(
                root=root,
                namespace_root=namespace_root,
                request_id=str(request["request_id"]),
                request_sha256=request_sha256,
                result_sha256=result_sha256,
                existing_record=existing_record,
                reason=reason,
            )
            return


def _write_record_and_transition_terminal_import(
    *,
    record_path: Path,
    record: Mapping[str, Any],
    record_write: _ConsumptionRecordWriteToken,
    root: Path,
    authority_context: AuthorityContext,
    request_id: str,
    request_sha256: str,
    result_id: str,
    result_sha256: str,
    state: str,
    reason: str,
    result_path: str,
    acceptance_manifest_path: str | None,
    acceptance_manifest_hash: str | None,
) -> dict[str, Any]:
    if state not in _CONSUMED_TERMINAL_STATES:
        raise ValidationError("consumed terminal state is not lifecycle-transactional")
    record_payload = canonical_json_bytes(record)
    _write_json_atomic(record_path, record)
    record_write.path = record_path
    record_write.payload = record_payload
    verify_authority_context_current(authority_context)
    return _transition(
        root=root,
        request_id=request_id,
        request_sha256=request_sha256,
        result_id=result_id,
        result_sha256=result_sha256,
        state=state,
        terminal=True,
        reason=reason,
        result_path=result_path,
        acceptance_manifest_path=acceptance_manifest_path,
        acceptance_manifest_hash=acceptance_manifest_hash,
    )


def _repair_terminal_heartbeat_and_return_status(
    *,
    status: Mapping[str, Any],
    root: Path,
    request_id: str,
    request_sha256: str,
    state: str,
) -> dict[str, Any]:
    if state not in _CONSUMED_TERMINAL_STATES:
        raise ValidationError("consumed terminal state is not lifecycle-transactional")
    _repair_terminal_heartbeat(
        root=root,
        request_id=request_id,
        request_sha256=request_sha256,
        state=state,
    )
    return dict(status)


def _run_terminal_lifecycle_transaction(
    *,
    root: Path,
    authority_context: AuthorityContext,
    operation: Any,
    consumption_record_writes: Sequence[_ConsumptionRecordWriteToken] = (),
    rollback_paths: Sequence[Path] = (),
) -> dict[str, Any]:
    snapshot = _snapshot_lifecycle(root)
    supplemental_snapshot = _snapshot_files(rollback_paths)
    mutation_started = False
    try:
        verify_authority_context_current(authority_context)
        mutation_started = True
        status = operation()
        verify_authority_context_current(authority_context)
        return status
    except AuthorityContextRotationError:
        if mutation_started:
            _restore_lifecycle(root, snapshot)
            _restore_files(supplemental_snapshot)
            _remove_owned_consumption_records(consumption_record_writes)
        raise


def _snapshot_lifecycle(root: Path) -> _LifecycleSnapshot:
    artifacts = []
    for name in ("status.json", "stage_journal.json", "heartbeat.json"):
        path = root / name
        if path.exists():
            artifacts.append(
                _LifecycleArtifactSnapshot(
                    name=name, existed=True, payload=path.read_bytes()
                )
            )
        else:
            artifacts.append(
                _LifecycleArtifactSnapshot(name=name, existed=False, payload=None)
            )
    return _LifecycleSnapshot(artifacts=tuple(artifacts))


def _restore_lifecycle(root: Path, snapshot: _LifecycleSnapshot) -> None:
    for artifact in snapshot.artifacts:
        path = root / artifact.name
        if not artifact.existed:
            path.unlink(missing_ok=True)
        else:
            assert artifact.payload is not None
            _write_bytes_atomic(path, artifact.payload)


def _snapshot_files(paths: Sequence[Path]) -> tuple[_FileArtifactSnapshot, ...]:
    snapshots = []
    for path in paths:
        parent_existed = path.parent.exists()
        if path.exists():
            snapshots.append(
                _FileArtifactSnapshot(
                    path=path,
                    existed=True,
                    payload=path.read_bytes(),
                    parent_existed=parent_existed,
                )
            )
        else:
            snapshots.append(
                _FileArtifactSnapshot(
                    path=path,
                    existed=False,
                    payload=None,
                    parent_existed=parent_existed,
                )
            )
    return tuple(snapshots)


def _restore_files(snapshots: Sequence[_FileArtifactSnapshot]) -> None:
    for artifact in snapshots:
        if not artifact.existed:
            artifact.path.unlink(missing_ok=True)
            if not artifact.parent_existed:
                try:
                    artifact.path.parent.rmdir()
                except OSError:
                    pass
        else:
            assert artifact.payload is not None
            _write_bytes_atomic(artifact.path, artifact.payload)


def _run_authority_checked_terminal_lifecycle_transaction(
    *,
    root: Path,
    namespace_root: Path,
    authority_context: AuthorityContext,
    request_id: str,
    request_sha256: str,
    result_sha256: str | None,
    existing_record: Mapping[str, Any] | None,
    phase: str,
    operation: Any,
    rollback_paths: Sequence[Path] = (),
) -> dict[str, Any]:
    try:
        return _run_terminal_lifecycle_transaction(
            root=root,
            authority_context=authority_context,
            operation=operation,
            rollback_paths=rollback_paths,
        )
    except AuthorityContextRotationError as exc:
        _record_authority_rotation_incident(
            root=root,
            namespace_root=namespace_root,
            request_id=request_id,
            request_sha256=request_sha256,
            result_sha256=result_sha256,
            existing_record=existing_record,
            phase=phase,
            exc=exc,
        )
        raise


def _remove_owned_consumption_records(
    writes: Sequence[_ConsumptionRecordWriteToken],
) -> None:
    for write in writes:
        if write.path is None or write.payload is None or not write.path.exists():
            continue
        held = read_stable_file(write.path)
        if held.payload != write.payload:
            raise ValidationError(
                "owned consumption record changed before authority-rotation rollback"
            )
        write.path.unlink()
        if write.path.exists():
            raise ValidationError("authority-rotation consumption rollback failed")


def _replay_incident(
    *,
    root: Path,
    namespace_root: Path,
    authority_context: AuthorityContext,
    request_id: str,
    request_sha256: str,
    result_sha256: str | None,
    existing_record: Mapping[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    incident_path = _replay_incident_path(
        root=root,
        namespace_root=namespace_root,
        request_id=request_id,
        request_sha256=request_sha256,
        result_sha256=result_sha256,
        reason=reason,
    )
    return _run_authority_checked_terminal_lifecycle_transaction(
        root=root,
        namespace_root=namespace_root,
        authority_context=authority_context,
        request_id=request_id,
        request_sha256=request_sha256,
        result_sha256=result_sha256,
        existing_record=existing_record,
        phase="replay-conflict terminal transaction",
        rollback_paths=(incident_path,),
        operation=lambda: _record_and_transition_replay_incident(
            root=root,
            namespace_root=namespace_root,
            request_id=request_id,
            request_sha256=request_sha256,
            result_sha256=result_sha256,
            existing_record=existing_record,
            reason=reason,
        ),
    )


def _record_and_transition_replay_incident(
    *,
    root: Path,
    namespace_root: Path,
    request_id: str,
    request_sha256: str,
    result_sha256: str | None,
    existing_record: Mapping[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    incident_path = _record_replay_incident(
        root=root,
        namespace_root=namespace_root,
        request_id=request_id,
        request_sha256=request_sha256,
        result_sha256=result_sha256,
        existing_record=existing_record,
        reason=reason,
    )
    return _transition(
        root=root,
        request_id=request_id,
        request_sha256=request_sha256,
        result_sha256=result_sha256,
        state="quarantined",
        terminal=True,
        reason=f"replay_conflict: {reason}",
        quarantine_path=str(incident_path),
    )


def _replay_incident_path(
    *,
    root: Path,
    namespace_root: Path,
    request_id: str,
    request_sha256: str,
    result_sha256: str | None,
    reason: str,
) -> Path:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "request_id": request_id,
                "request_sha256": request_sha256,
                "result_sha256": result_sha256,
                "run_root": str(root),
                "reason": reason,
            }
        )
    ).hexdigest()
    return (
        namespace_root
        / "incidents"
        / f"{request_id.removeprefix('sha256:')}-{digest[:16]}.json"
    )


def _record_replay_incident(
    *,
    root: Path,
    namespace_root: Path,
    request_id: str,
    request_sha256: str,
    result_sha256: str | None,
    existing_record: Mapping[str, Any] | None,
    reason: str,
) -> Path:
    incident_path = _replay_incident_path(
        root=root,
        namespace_root=namespace_root,
        request_id=request_id,
        request_sha256=request_sha256,
        result_sha256=result_sha256,
        reason=reason,
    )
    incident = {
        "version": INCIDENT_VERSION,
        "request_id": request_id,
        "request_sha256": request_sha256,
        "result_sha256": result_sha256,
        "run_root": str(root),
        "reason": reason,
        "existing_record": dict(existing_record)
        if existing_record is not None
        else None,
        "captured_at": _utc_now(),
    }
    _write_json_atomic(incident_path, incident)
    return incident_path


def _record_authority_rotation_incident(
    *,
    root: Path,
    namespace_root: Path,
    request_id: str,
    request_sha256: str,
    result_sha256: str | None,
    existing_record: Mapping[str, Any] | None,
    phase: str,
    exc: Exception,
) -> Path:
    return _record_replay_incident(
        root=root,
        namespace_root=namespace_root,
        request_id=request_id,
        request_sha256=request_sha256,
        result_sha256=result_sha256,
        existing_record=existing_record,
        reason=f"authority rotation during {phase}: {exc}",
    )


def _quarantine_invalid_request(
    root: Path,
    source_path: Path,
    exc: Exception,
    *,
    source_held: StableFile | None,
) -> dict[str, Any]:
    return _quarantine(
        root=root,
        request_id=(
            source_held.sha256
            if source_held is not None
            else _failed_read_identity(source_path)
        ),
        reason=f"unreadable_request: {exc}",
        source_path=source_path,
        source_name="run_request.json",
        source_held=source_held,
    )


def _quarantine(
    *,
    root: Path,
    request_id: str,
    reason: str,
    source_path: Path,
    source_name: str,
    source_held: StableFile | None = None,
    authority_context: AuthorityContext | None = None,
    namespace_root: Path | None = None,
    incident_request_sha256: str | None = None,
    result_sha256: str | None = None,
    existing_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    quarantine_path = root / "quarantine" / f"{source_name}.metadata.json"

    def quarantine_operation() -> dict[str, Any]:
        metadata = {
            "version": QUARANTINE_VERSION,
            "request_id": request_id,
            "reason": reason,
            "captured_at": _utc_now(),
            "source_sha256": None,
            "source_size_bytes": None,
            "suspect_content_persisted": False,
        }
        if source_held is not None:
            metadata["source_sha256"] = source_held.sha256
            metadata["source_size_bytes"] = source_held.size_bytes
        _write_json_atomic(quarantine_path, metadata)
        return _transition(
            root=root,
            request_id=request_id,
            request_sha256=metadata["source_sha256"],
            state="quarantined",
            terminal=True,
            reason=reason,
            quarantine_path=str(quarantine_path),
        )

    if authority_context is None:
        if namespace_root is not None or incident_request_sha256 is not None:
            raise ValidationError("quarantine authority transaction is incomplete")
        return quarantine_operation()
    if namespace_root is None or incident_request_sha256 is None:
        raise ValidationError("quarantine authority transaction is incomplete")
    return _run_authority_checked_terminal_lifecycle_transaction(
        root=root,
        namespace_root=namespace_root,
        authority_context=authority_context,
        request_id=request_id,
        request_sha256=incident_request_sha256,
        result_sha256=result_sha256,
        existing_record=existing_record,
        phase=f"{source_name} quarantine terminal transaction",
        rollback_paths=(quarantine_path,),
        operation=quarantine_operation,
    )


def _transition(
    *,
    root: Path,
    request_id: str,
    request_sha256: str | None,
    state: str,
    terminal: bool,
    reason: str,
    result_id: str | None = None,
    result_sha256: str | None = None,
    result_path: str | None = None,
    quarantine_path: str | None = None,
    acceptance_manifest_path: str | None = None,
    acceptance_manifest_hash: str | None = None,
    authority_context: AuthorityContext | None = None,
) -> dict[str, Any]:
    if terminal and authority_context is not None:
        verify_authority_context_current(authority_context)
    journal_path = root / "stage_journal.json"
    journal = _load_optional_json(journal_path) or {
        "version": ORCHESTRATOR_JOURNAL_VERSION,
        "request_id": request_id,
        "events": [],
    }
    if journal.get("request_id") != request_id:
        raise ValidationError("stage journal request_id mismatch")
    events = journal.get("events")
    if not isinstance(events, list):
        raise ValidationError("stage journal events must be a list")
    previous = events[-1]["state"] if events else None
    if not events or previous != state:
        event = {
            "sequence": len(events) + 1,
            "old_state": previous,
            "state": state,
            "at": _utc_now(),
            "reason": reason,
            "request_sha256": request_sha256,
            "result_sha256": result_sha256,
        }
        if acceptance_manifest_path is not None:
            event["acceptance_manifest_path"] = acceptance_manifest_path
            event["acceptance_manifest_hash"] = acceptance_manifest_hash
        events.append(event)
        _write_json_atomic(journal_path, journal)
    status = {
        "version": ORCHESTRATOR_STATUS_VERSION,
        "request_id": request_id,
        "request_sha256": request_sha256,
        "result_id": result_id,
        "result_sha256": result_sha256,
        "state": state,
        "terminal": terminal,
        "reason": reason,
        "updated_at": _utc_now(),
        "heartbeat_path": str(root / "heartbeat.json"),
        "journal_path": str(journal_path),
        "result_path": result_path,
        "quarantine_path": quarantine_path,
        "acceptance_manifest_path": acceptance_manifest_path,
        "acceptance_manifest_hash": acceptance_manifest_hash,
    }
    _write_json_atomic(root / "status.json", status)
    _heartbeat(root, request_id, request_sha256, state)
    if terminal and authority_context is not None:
        verify_authority_context_current(authority_context)
    return status


def _heartbeat(
    root: Path, request_id: str, request_sha256: str | None, state: str
) -> None:
    _write_json_atomic(
        root / "heartbeat.json",
        {
            "version": ORCHESTRATOR_HEARTBEAT_VERSION,
            "request_id": request_id,
            "request_sha256": request_sha256,
            "state": state,
            "updated_at": _utc_now(),
        },
    )


def _busy_status(root: Path, request_id: str, *, reason: str) -> dict[str, Any]:
    existing = _load_optional_json(root / "status.json")
    if existing is not None:
        return {**existing, "busy": True}
    return {
        "version": ORCHESTRATOR_STATUS_VERSION,
        "request_id": request_id,
        "request_sha256": None,
        "result_id": None,
        "result_sha256": None,
        "state": "running",
        "terminal": False,
        "reason": reason,
        "updated_at": _utc_now(),
        "heartbeat_path": str(root / "heartbeat.json"),
        "journal_path": str(root / "stage_journal.json"),
        "result_path": None,
        "quarantine_path": None,
        "acceptance_manifest_path": None,
        "acceptance_manifest_hash": None,
        "busy": True,
    }


def _prepare_root(value: str | Path, *, create: bool, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValidationError(f"{label} must be absolute")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValidationError(f"{label} must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValidationError(f"{label} must be a directory")
    return resolved


def _decode_canonical_sealed(
    payload: bytes, version: str, label: str
) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValidationError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValidationError(f"non-finite JSON value {item}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"sealed {label} is not UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"sealed {label} must be an object")
    if value.get("version") != version:
        raise ValidationError(
            f"sealed {label} legacy/unsupported version cannot be upgraded"
        )
    if canonical_json_bytes(value) != payload:
        raise ValidationError(f"sealed {label} JSON is not canonically encoded")
    return value


def _require_sealed_id(value: Mapping[str, Any], field: str, version: str) -> str:
    identity = value.get(field)
    if not isinstance(identity, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", identity
    ):
        raise ValidationError(f"sealed artifact {field} is invalid")
    payload = dict(value)
    payload.pop(field, None)
    from .skillopt_compatibility import domain_separated_hash

    if identity != domain_separated_hash(version, payload):
        raise ValidationError(f"sealed artifact {field} content binding mismatch")
    return identity


def _file_entry(root: Path, path: Path) -> dict[str, Any]:
    held = read_stable_file(path)
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": held.sha256,
        "size_bytes": held.size_bytes,
    }


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    _write_bytes_atomic(path, canonical_json_bytes(value))


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    held = read_stable_file(path)
    value = json.loads(held.payload)
    if not isinstance(value, dict) or canonical_json_bytes(value) != held.payload:
        raise ValidationError("coordinator lifecycle artifact is not canonical")
    return value


def _load_optional_canonical(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    held = read_stable_file(path)
    value = json.loads(held.payload)
    if not isinstance(value, dict) or canonical_json_bytes(value) != held.payload:
        raise ValidationError("coordinator consumption record is not canonical")
    return value


def run_coordinator(
    *,
    run_root: str | Path,
    request_path: str | Path,
    import_result_path: str | Path | None = None,
    dry_run: bool = False,
    cancel: bool = False,
    coordinator_root: str | Path | None = None,
) -> dict[str, Any]:
    return run_orchestrator(
        run_root=run_root,
        request_path=request_path,
        import_result_path=import_result_path,
        dry_run=dry_run,
        cancel=cancel,
        coordinator_root=coordinator_root,
    )


def _failed_read_identity(path: Path) -> str:
    """Return a bounded path/inode identity without opening rejected content."""
    try:
        value = os.lstat(path)
        signature: tuple[int, ...] | None = (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
    except OSError:
        signature = None
    payload = canonical_json_bytes(
        {
            "path": os.fsencode(path)[:4096].hex(),
            "lstat": signature,
        }
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _file_identity(path: Path) -> str:
    return _failed_read_identity(path)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--request", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--import-result")
    action.add_argument("--cancel", action="store_true")
    args = parser.parse_args(argv)
    try:
        status = run_orchestrator(
            run_root=args.run_root,
            request_path=args.request,
            dry_run=args.dry_run,
            import_result_path=args.import_result,
            cancel=args.cancel,
        )
    except ValidationError as exc:
        print(json.dumps({"state": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(status, sort_keys=True))
    return 0 if status.get("state") not in {"quarantined", "failed", "timed_out"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
