"""Revalidation boundary for coordinator-published SkillOpt candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .skillopt_contract import ValidationError
from .skillopt_run_contract import (
    INPUT_ARTIFACT_NAMES,
    AuthorityContext,
    canonical_json_bytes,
    capture_run_request,
    capture_run_result,
    read_stable_file,
    resolve_authority_context,
    verify_authority_context_current,
)


ACCEPTANCE_MANIFEST_VERSION = "skillopt-acceptance-manifest-v2"
_MANIFEST_KEYS = {
    "version",
    "request_id",
    "result_id",
    "accepted_at",
    "sealed_request",
    "sealed_result",
    "evidence_snapshots",
    "accepted_outputs",
    "accepted_receipts",
    "bindings",
}
_BINDING_KEYS = {
    "profile_identity",
    "overlay_identity",
    "staging_identity",
    "runner_identity",
    "custody_identity",
    "usage_receipt_identity",
    "privacy_receipt_identity",
    "request_sha256",
    "request_size_bytes",
    "result_sha256",
    "result_size_bytes",
    "policy_identity",
    "coordinator_id",
    "coordinator_namespace",
}


@dataclass(frozen=True)
class AcceptedSkillOptCandidate:
    run_root: Path
    manifest_path: Path
    manifest_hash: str
    manifest_size_bytes: int
    request_id: str
    result_id: str
    best_skill_path: Path
    best_skill_hash: str
    best_skill_bytes: bytes
    sealed_request_hash: str
    sealed_request_size_bytes: int
    sealed_result_hash: str
    sealed_result_size_bytes: int
    input_artifact_hashes: Mapping[str, str]
    profile_identity: str
    overlay_identity: str
    staging_identity: str
    runner_identity: str
    custody_identity: str
    usage_receipt_identity: str
    privacy_receipt_identity: str
    policy_identity: str
    coordinator_id: str
    coordinator_namespace: str


def load_accepted_skillopt_candidate(
    *,
    acceptance_manifest_path: str | Path,
    run_root: str | Path,
    authority_context: AuthorityContext | None = None,
) -> AcceptedSkillOptCandidate:
    authority_context = authority_context or resolve_authority_context()
    verify_authority_context_current(authority_context)
    root = _resolved_root(run_root, "accepted candidate run_root")
    manifest_path = Path(acceptance_manifest_path)
    if manifest_path.is_symlink():
        raise ValidationError("acceptance manifest must not be a symlink")
    try:
        manifest_path = manifest_path.resolve(strict=True)
    except OSError as exc:
        raise ValidationError("acceptance manifest is missing") from exc
    expected = root / "artifacts" / "acceptance_manifest.json"
    if manifest_path != expected:
        raise ValidationError(
            "acceptance manifest must be the coordinator-published artifacts/acceptance_manifest.json"
        )
    manifest_held, manifest = _load_canonical(manifest_path)
    _validate_acceptance_manifest(manifest, run_root=root, verify_files=False)

    request_held, request = _load_canonical(
        root / str(manifest["sealed_request"]["path"])
    )
    result_held, result = _load_canonical(root / str(manifest["sealed_result"]["path"]))
    request_capture = capture_run_request(
        request,
        run_root=root,
        raw_bytes=request_held.payload,
        evidence_snapshots=manifest["evidence_snapshots"],
        authority_context=authority_context,
    )
    result_capture = capture_run_result(
        result,
        request=request,
        run_root=root,
        raw_bytes=result_held.payload,
        request_capture=request_capture,
        accepted_outputs=manifest["accepted_outputs"],
        accepted_receipts=manifest["accepted_receipts"],
    )
    if result.get("status") != "succeeded":
        raise ValidationError("approval requires a succeeded sealed SkillOpt result")
    if manifest.get("request_id") != request.get("request_id"):
        raise ValidationError(
            "acceptance manifest request_id does not match sealed request"
        )
    if manifest.get("result_id") != result.get("result_id"):
        raise ValidationError(
            "acceptance manifest result_id does not match sealed result"
        )

    bindings = manifest["bindings"]
    expected_bindings = {
        "profile_identity": request_capture.profile["identity"],
        "overlay_identity": request_capture.profile["overlay_manifest"]["identity"],
        "staging_identity": request_capture.profile["staging_manifest"]["identity"],
        "runner_identity": request_capture.profile["runner_identity"]["identity"],
        "custody_identity": request_capture.profile["custody_evidence"]["identity"],
        "usage_receipt_identity": result_capture.receipt_json["usage"]["identity"],
        "privacy_receipt_identity": result_capture.receipt_json["privacy"]["identity"],
        "request_sha256": request_held.sha256,
        "request_size_bytes": request_held.size_bytes,
        "result_sha256": result_held.sha256,
        "result_size_bytes": result_held.size_bytes,
        "policy_identity": request_capture.policy["identity"],
        "coordinator_id": request_capture.policy["coordinator_id"],
        "coordinator_namespace": request_capture.policy["coordinator_namespace"],
    }
    if dict(bindings) != expected_bindings:
        raise ValidationError(
            "acceptance manifest identity/byte bindings do not match sealed artifacts"
        )
    if (
        manifest["sealed_request"]["sha256"],
        manifest["sealed_request"]["size_bytes"],
    ) != (
        request_held.sha256,
        request_held.size_bytes,
    ):
        raise ValidationError(
            "acceptance manifest sealed request snapshot binding mismatch"
        )
    if (
        manifest["sealed_result"]["sha256"],
        manifest["sealed_result"]["size_bytes"],
    ) != (
        result_held.sha256,
        result_held.size_bytes,
    ):
        raise ValidationError(
            "acceptance manifest sealed result snapshot binding mismatch"
        )

    _validate_coordinator_publication(
        root=root,
        manifest=manifest,
        manifest_path=manifest_path,
        manifest_held=manifest_held,
        request_id=str(request["request_id"]),
        result_id=str(result["result_id"]),
        result_completed_at=result["completed_at"],
        authority_context=authority_context,
    )
    best = result_capture.outputs["best_skill"]
    if best is None:
        raise ValidationError("succeeded acceptance is missing best_skill bytes")
    verify_authority_context_current(authority_context)
    return AcceptedSkillOptCandidate(
        run_root=root,
        manifest_path=manifest_path,
        manifest_hash=manifest_held.sha256,
        manifest_size_bytes=manifest_held.size_bytes,
        request_id=str(request["request_id"]),
        result_id=str(result["result_id"]),
        best_skill_path=best.path,
        best_skill_hash=best.sha256,
        best_skill_bytes=best.payload,
        sealed_request_hash=request_held.sha256,
        sealed_request_size_bytes=request_held.size_bytes,
        sealed_result_hash=result_held.sha256,
        sealed_result_size_bytes=result_held.size_bytes,
        input_artifact_hashes={
            name: request_capture.evidence[name].sha256 for name in INPUT_ARTIFACT_NAMES
        },
        profile_identity=str(bindings["profile_identity"]),
        overlay_identity=str(bindings["overlay_identity"]),
        staging_identity=str(bindings["staging_identity"]),
        runner_identity=str(bindings["runner_identity"]),
        custody_identity=str(bindings["custody_identity"]),
        usage_receipt_identity=str(bindings["usage_receipt_identity"]),
        privacy_receipt_identity=str(bindings["privacy_receipt_identity"]),
        policy_identity=str(bindings["policy_identity"]),
        coordinator_id=str(bindings["coordinator_id"]),
        coordinator_namespace=str(bindings["coordinator_namespace"]),
    )


def validate_acceptance_manifest(
    manifest: Mapping[str, Any], *, run_root: str | Path
) -> None:
    _validate_acceptance_manifest(manifest, run_root=run_root, verify_files=True)


def _validate_acceptance_manifest(
    manifest: Mapping[str, Any], *, run_root: str | Path, verify_files: bool
) -> None:
    if set(manifest) != _MANIFEST_KEYS:
        raise ValidationError("acceptance manifest keys mismatch")
    if manifest.get("version") != ACCEPTANCE_MANIFEST_VERSION:
        raise ValidationError("acceptance manifest version is invalid")
    for field in ("request_id", "result_id"):
        if not _is_digest(manifest.get(field)):
            raise ValidationError(f"acceptance manifest {field} is invalid")
    _require_utc(manifest.get("accepted_at"), "acceptance manifest accepted_at")
    root = _resolved_root(run_root, "acceptance manifest run_root")
    sealed_request = _validate_file_entry(
        root, manifest.get("sealed_request"), "sealed_request", verify=verify_files
    )
    sealed_result = _validate_file_entry(
        root, manifest.get("sealed_result"), "sealed_result", verify=verify_files
    )
    if sealed_request["path"] != "artifacts/run_request.json":
        raise ValidationError(
            "acceptance manifest sealed request path is not canonical"
        )
    if sealed_result["path"] != "artifacts/run_result.json":
        raise ValidationError("acceptance manifest sealed result path is not canonical")
    evidence = manifest.get("evidence_snapshots")
    if not isinstance(evidence, Mapping) or set(evidence) != set(INPUT_ARTIFACT_NAMES):
        raise ValidationError("acceptance manifest evidence snapshot keys mismatch")
    for name, entry in evidence.items():
        validated = _validate_file_entry(
            root, entry, f"evidence_snapshots.{name}", verify=verify_files
        )
        if not validated["path"].startswith(f"artifacts/evidence/{name}"):
            raise ValidationError(
                f"acceptance evidence snapshot {name} path is not canonical"
            )
    outputs = manifest.get("accepted_outputs")
    if not isinstance(outputs, Mapping) or set(outputs) != {
        "best_skill",
        "evaluation",
        "sanitized_summary",
    }:
        raise ValidationError("acceptance manifest accepted output keys mismatch")
    expected_output_paths = {
        "best_skill": "artifacts/accepted_best_skill.md",
        "evaluation": "artifacts/accepted_evaluation.json",
        "sanitized_summary": "artifacts/accepted_sanitized_summary.json",
    }
    for name, expected_path in expected_output_paths.items():
        entry = _validate_file_entry(
            root,
            outputs.get(name),
            f"accepted_outputs.{name}",
            verify=verify_files,
        )
        if entry["path"] != expected_path:
            raise ValidationError(f"acceptance manifest {name} path is not canonical")
    receipts = manifest.get("accepted_receipts")
    if not isinstance(receipts, Mapping) or set(receipts) != {"usage", "privacy"}:
        raise ValidationError("acceptance manifest accepted receipt keys mismatch")
    for name in ("usage", "privacy"):
        entry = _validate_file_entry(
            root,
            receipts.get(name),
            f"accepted_receipts.{name}",
            verify=verify_files,
        )
        if entry["path"] != f"artifacts/accepted_{name}_receipt.json":
            raise ValidationError(
                f"acceptance manifest {name} receipt path is not canonical"
            )
    bindings = manifest.get("bindings")
    if not isinstance(bindings, Mapping) or set(bindings) != _BINDING_KEYS:
        raise ValidationError("acceptance manifest binding keys mismatch")
    for field in _BINDING_KEYS - {
        "request_size_bytes",
        "result_size_bytes",
        "coordinator_id",
        "coordinator_namespace",
    }:
        if not _is_digest(bindings.get(field)):
            raise ValidationError(f"acceptance manifest binding {field} is invalid")
    for field in ("request_size_bytes", "result_size_bytes"):
        if type(bindings.get(field)) is not int or bindings[field] < 0:
            raise ValidationError(f"acceptance manifest binding {field} is invalid")
    for field in ("coordinator_id", "coordinator_namespace"):
        if not isinstance(bindings.get(field), str) or not bindings[field]:
            raise ValidationError(f"acceptance manifest binding {field} is invalid")


def _validate_coordinator_publication(
    *,
    root: Path,
    manifest: Mapping[str, Any],
    manifest_path: Path,
    manifest_held: Any,
    request_id: str,
    result_id: str,
    result_completed_at: Any,
    authority_context: AuthorityContext,
) -> None:
    bindings = manifest["bindings"]
    coordinator = authority_context.coordinator_root
    if (
        bindings["policy_identity"] != authority_context.policy_identity
        or bindings["coordinator_id"] != authority_context.coordinator_id
        or bindings["coordinator_namespace"] != authority_context.coordinator_namespace
    ):
        raise ValidationError("acceptance authority does not match external pin")
    record_path = (
        coordinator
        / "namespaces"
        / str(bindings["coordinator_namespace"])
        / "consumed"
        / f"{request_id}.json"
    )
    _record_held, record = _load_canonical(record_path)
    expected_record = {
        "version": "skillopt-consumption-record-v1",
        "request_id": request_id,
        "request_sha256": bindings["request_sha256"],
        "result_id": result_id,
        "result_sha256": bindings["result_sha256"],
        "run_root": str(root),
        "state": "candidate_ready",
        "policy_identity": bindings["policy_identity"],
        "coordinator_id": bindings["coordinator_id"],
        "coordinator_namespace": bindings["coordinator_namespace"],
        "acceptance_manifest_path": str(manifest_path),
        "acceptance_manifest_hash": manifest_held.sha256,
    }
    for key, expected in expected_record.items():
        if record.get(key) != expected:
            raise ValidationError(f"coordinator consumption record {key} mismatch")
    record_at = _require_utc(
        record.get("recorded_at"), "consumption record recorded_at"
    )

    status = _load_lifecycle(root / "status.json", "status")
    journal = _load_lifecycle(root / "stage_journal.json", "stage journal")
    heartbeat = _load_lifecycle(root / "heartbeat.json", "heartbeat")
    expected_status = {
        "version": "skillopt-orchestrator-status-v2",
        "request_id": request_id,
        "request_sha256": bindings["request_sha256"],
        "result_id": result_id,
        "result_sha256": bindings["result_sha256"],
        "state": "candidate_ready",
        "terminal": True,
        "result_path": str(root / "artifacts" / "run_result.json"),
        "quarantine_path": None,
        "acceptance_manifest_path": str(manifest_path),
        "acceptance_manifest_hash": manifest_held.sha256,
    }
    for key, expected in expected_status.items():
        if status.get(key) != expected:
            raise ValidationError(f"coordinator status {key} mismatch")
    if not isinstance(status.get("reason"), str) or not status["reason"]:
        raise ValidationError("coordinator status reason is invalid")
    status_at = _require_utc(status.get("updated_at"), "coordinator status updated_at")

    if set(journal) != {"version", "request_id", "events"}:
        raise ValidationError("coordinator stage journal keys mismatch")
    if (
        journal.get("version") != "skillopt-orchestrator-journal-v2"
        or journal.get("request_id") != request_id
    ):
        raise ValidationError("coordinator stage journal identity mismatch")
    events = journal.get("events")
    if not isinstance(events, list) or not events:
        raise ValidationError("coordinator stage journal events are missing")
    states = [
        event.get("state") if isinstance(event, Mapping) else None for event in events
    ]
    if states not in (
        ["requested", "running", "candidate_ready"],
        [
            "requested",
            "running",
            "dry_run_complete",
            "requested",
            "running",
            "candidate_ready",
        ],
    ):
        raise ValidationError("coordinator stage journal transition chain is invalid")
    previous = None
    timestamps: list[datetime] = []
    for index, event in enumerate(events, 1):
        if not isinstance(event, Mapping) or event.get("sequence") != index:
            raise ValidationError("coordinator stage journal sequence mismatch")
        if event.get("old_state") != previous:
            raise ValidationError("coordinator stage journal old_state mismatch")
        if event.get("request_sha256") != bindings["request_sha256"]:
            raise ValidationError("coordinator stage journal request hash mismatch")
        if index == len(events):
            if event.get("result_sha256") != bindings["result_sha256"]:
                raise ValidationError("coordinator stage journal result hash mismatch")
            if event.get("acceptance_manifest_hash") != manifest_held.sha256:
                raise ValidationError(
                    "coordinator stage journal acceptance hash mismatch"
                )
        event_at = _require_utc(event.get("at"), "coordinator stage journal event at")
        if timestamps and event_at < timestamps[-1]:
            raise ValidationError(
                "coordinator stage journal timestamps must be nondecreasing"
            )
        timestamps.append(event_at)
        previous = event.get("state")

    expected_heartbeat = {
        "version": "skillopt-orchestrator-heartbeat-v2",
        "request_id": request_id,
        "request_sha256": bindings["request_sha256"],
        "state": "candidate_ready",
    }
    for key, expected in expected_heartbeat.items():
        if heartbeat.get(key) != expected:
            raise ValidationError(f"coordinator heartbeat {key} mismatch")
    heartbeat_at = _require_utc(
        heartbeat.get("updated_at"), "coordinator heartbeat updated_at"
    )
    completed = _require_utc(result_completed_at, "sealed result completed_at")
    accepted = _require_utc(
        manifest.get("accepted_at"), "acceptance manifest accepted_at"
    )
    if not (
        completed
        <= accepted
        <= record_at
        <= timestamps[-1]
        <= status_at
        <= heartbeat_at
    ):
        raise ValidationError("coordinator publication timestamps violate write order")


def _validate_file_entry(
    root: Path, value: Any, field: str, *, verify: bool
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"path", "sha256", "size_bytes"}:
        raise ValidationError(f"acceptance manifest {field} keys mismatch")
    relative = value.get("path")
    if (
        not isinstance(relative, str)
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
    ):
        raise ValidationError(f"acceptance manifest {field} path is invalid")
    if not _is_digest(value.get("sha256")):
        raise ValidationError(f"acceptance manifest {field} sha256 is invalid")
    if type(value.get("size_bytes")) is not int or value["size_bytes"] < 0:
        raise ValidationError(f"acceptance manifest {field} size is invalid")
    if verify:
        held = read_stable_file(relative, root=root)
        if held.sha256 != value.get("sha256") or held.size_bytes != value.get(
            "size_bytes"
        ):
            raise ValidationError(
                f"acceptance manifest {field} snapshot binding mismatch"
            )
    return dict(value)


def _load_canonical(path: Path) -> tuple[Any, dict[str, Any]]:
    held = read_stable_file(path)
    try:
        value = json.loads(held.payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("canonical accepted JSON is unreadable") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != held.payload:
        raise ValidationError("canonical accepted JSON encoding mismatch")
    return held, value


def _load_lifecycle(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValidationError(f"coordinator {label} file is missing or non-canonical")
    _held, value = _load_canonical(path)
    return value


def _resolved_root(value: str | Path, label: str) -> Path:
    root = Path(value)
    if not root.is_absolute() or root.is_symlink():
        raise ValidationError(f"{label} must be an absolute non-symlink directory")
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise ValidationError(f"{label} does not exist") from exc
    if not resolved.is_dir():
        raise ValidationError(f"{label} must be a directory")
    return resolved


def _require_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValidationError(f"{field} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValidationError(f"{field} must be a UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValidationError(f"{field} must be a UTC timestamp")
    return parsed


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )
