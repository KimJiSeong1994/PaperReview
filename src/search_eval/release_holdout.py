"""One-shot, sealed release-holdout evaluation for the approval plane.

The optimizer never receives a holdout path, labels, per-query results, or this
module's validated aggregate capability.  A generation is the consumption key:
the exact pair is durably precommitted before the evaluator is invoked and any
attempt permanently spends or quarantines that generation.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Callable, Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .skillopt_contract import ValidationError
from .skillopt_run_contract import (
    StableFile,
    canonical_json_bytes,
    canonical_value_hash,
    read_stable_file,
)

RELEASE_HOLDOUT_MANIFEST_VERSION = "release_holdout_manifest_v1"
RELEASE_HOLDOUT_EVALUATION_VERSION = "release_holdout_evaluation_v1"
RELEASE_HOLDOUT_PRECOMMIT_VERSION = "release_holdout_precommit_v1"
RELEASE_HOLDOUT_STATUS_VERSION = "release_holdout_status_v1"
RELEASE_HOLDOUT_JOURNAL_VERSION = "release_holdout_journal_v1"
RELEASE_HOLDOUT_INCIDENT_VERSION = "release_holdout_incident_v1"
RELEASE_HOLDOUT_CONSUMPTION_VERSION = "release_holdout_consumption_v1"
RELEASE_HOLDOUT_AUTHORITY_CONTEXT_VERSION = "release_holdout_authority_context_v1"
RELEASE_HOLDOUT_AUTHORITY_CONTEXT_ENV = (
    "SKILLOPT_RELEASE_HOLDOUT_AUTHORITY_CONTEXT_PATH"
)

RELEASE_HOLDOUT_AUTHORITY = "external-release-evaluator-only"
APPROVAL_AGGREGATE_AUTHORITY = "approval-plane-aggregate-only"

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_GENERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_MANIFEST_KEYS = {
    "version",
    "generation_id",
    "object_version",
    "holdout_sha256",
    "holdout_size_bytes",
    "authority_classification",
    "issuer_identity",
    "verifier_identity",
    "authority_context_hash",
    "immutable_store_receipt",
    "manifest_hash",
}
_AUTHORITY_CONTEXT_KEYS = {
    "version", "allowed_manifest_issuers", "allowed_evaluator_identities",
    "allowed_verifier_identities", "immutable_store", "acl_receipt",
    "valid_from", "expires_at", "context_hash",
}
_IMMUTABLE_STORE_CONTEXT_KEYS = {
    "root", "store_id", "namespace", "object_prefix", "retention_mode",
    "receipt_issuer_identity",
}
_ACL_CONTEXT_KEYS = {"issuer_identity", "receipt_hash"}
_STORE_RECEIPT_KEYS = {
    "store_id", "namespace", "object_key", "object_version", "holdout_sha256",
    "holdout_size_bytes", "retention_mode", "acl_receipt_hash",
    "receipt_issuer_identity", "receipt_hash",
}
_PRECOMMIT_KEYS = {
    "version",
    "generation_id",
    "manifest_hash",
    "manifest_path",
    "authority_context_hash",
    "baseline_sha256",
    "candidate_sha256",
    "thresholds",
    "evaluator_identity",
    "contract_identity",
    "nonce",
    "selection_evidence",
    "request_hash",
    "precommit_hash",
}
_STATUS_KEYS = {
    "version",
    "generation_id",
    "request_hash",
    "state",
    "reason",
    "precommit_hash",
    "evaluation_hash",
    "incident_hash",
}
_JOURNAL_KEYS = {"version", "generation_id", "request_hash", "events", "journal_hash"}
_CONSUMPTION_KEYS = {
    "version", "generation_id", "request_hash", "precommit_hash", "manifest_hash",
    "authority_context_hash", "evaluation_hash", "outcome", "consumption_hash",
}
_EVENT_KEYS = {"sequence", "state", "reason"}
_EVALUATION_KEYS = {
    "version",
    "evaluation_id",
    "generation_id",
    "manifest_hash",
    "authority_context_hash",
    "request_hash",
    "precommit_hash",
    "authority_classification",
    "baseline_sha256",
    "candidate_sha256",
    "evaluator_identity",
    "contract_identity",
    "outcome",
    "sample_count",
    "metrics",
    "threshold_results",
    "evaluation_hash",
}


@dataclass(frozen=True)
class ReleaseHoldoutAuthorityContext:
    config_path: Path
    context_hash: str
    allowed_manifest_issuers: tuple[str, ...]
    allowed_evaluator_identities: tuple[str, ...]
    allowed_verifier_identities: tuple[str, ...]
    store_root: Path
    store_id: str
    namespace: str
    object_prefix: str
    retention_mode: str
    receipt_issuer_identity: str
    acl_issuer_identity: str
    acl_receipt_hash: str
    valid_from: datetime
    expires_at: datetime


class ReleaseHoldoutAttemptError(ValidationError):
    """The generation was spent or quarantined without approval evidence."""


class PartialHoldoutExposureError(RuntimeError):
    """Evaluator reports that holdout detail may have been partially exposed."""


@dataclass(frozen=True)
class ValidatedReleaseHoldoutManifest(Mapping[str, Any]):
    """Immutable authority capability; unlike a path, this is safe to consume."""

    _manifest: Mapping[str, Any]
    manifest_path: Path
    manifest_hash: str
    authority_context: ReleaseHoldoutAuthorityContext
    _holdout_bytes: bytes

    def __getitem__(self, key: str) -> Any:
        return deepcopy(self._manifest[key])

    def __iter__(self) -> Iterator[str]:
        return iter(self._manifest)

    def __len__(self) -> int:
        return len(self._manifest)

    def persisted_manifest(self) -> dict[str, Any]:
        return deepcopy(dict(self._manifest))

    def read_holdout_bytes(self, *, max_bytes: int = 64 * 1024 * 1024) -> bytes:
        """Return the exact immutable bytes validated with this capability.

        Evaluators never receive an authoritative path and therefore cannot
        accidentally reopen a substituted object during the one-shot callback.
        """
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValidationError("release holdout read bound must be positive")
        if len(self._holdout_bytes) > max_bytes:
            raise ValidationError("release holdout exceeds evaluator read bound")
        return self._holdout_bytes


@dataclass(frozen=True)
class ReleaseHoldoutAggregate:
    """The only value an evaluator may return across the private boundary."""

    sample_count: int
    metrics: Mapping[str, float]
    threshold_results: Mapping[str, bool]


@dataclass(frozen=True)
class ValidatedReleaseHoldoutEvaluation(Mapping[str, Any]):
    """Aggregate-only capability accepted by the approval plane."""

    _record: Mapping[str, Any]
    record_path: Path
    evaluation_hash: str
    replayed: bool = False
    state_root: Path | None = None
    manifest_path: Path | None = None
    authority_context_hash: str | None = None
    authority_context: ReleaseHoldoutAuthorityContext | None = None

    def __getitem__(self, key: str) -> Any:
        return deepcopy(self._record[key])

    def __iter__(self) -> Iterator[str]:
        return iter(self._record)

    def __len__(self) -> int:
        return len(self._record)

    def persisted_record(self) -> dict[str, Any]:
        return deepcopy(dict(self._record))

    def capability_reference(self) -> dict[str, Any]:
        if self.state_root is None or self.manifest_path is None:
            raise ValidationError("release holdout capability is missing revalidation roots")
        return {
            "version": "release_holdout_capability_reference_v1",
            "state_root": str(self.state_root),
            "record_path": str(self.record_path),
            "manifest_path": str(self.manifest_path),
            "generation_id": self._record["generation_id"],
            "evaluation_hash": self.evaluation_hash,
            "authority_context_hash": self.authority_context_hash,
        }


def resolve_release_holdout_authority_context() -> ReleaseHoldoutAuthorityContext:
    configured = os.environ.get(RELEASE_HOLDOUT_AUTHORITY_CONTEXT_ENV)
    if not configured:
        raise ValidationError(
            f"release holdout authority context is required via {RELEASE_HOLDOUT_AUTHORITY_CONTEXT_ENV}"
        )
    path = Path(configured)
    if not path.is_absolute():
        raise ValidationError("release holdout authority context path must be absolute")
    held = read_stable_file(path, max_bytes=64 * 1024)
    try:
        value = json.loads(held.payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("release holdout authority context is unreadable") from exc
    if not isinstance(value, dict) or set(value) != _AUTHORITY_CONTEXT_KEYS:
        raise ValidationError("release holdout authority context schema mismatch")
    if canonical_json_bytes(value) != held.payload:
        raise ValidationError("release holdout authority context must be canonical JSON")
    if value.get("version") != RELEASE_HOLDOUT_AUTHORITY_CONTEXT_VERSION:
        raise ValidationError("release holdout authority context version mismatch")
    unsigned = dict(value)
    context_hash = unsigned.pop("context_hash", None)
    _require_sha256(context_hash, "authority context hash")
    if context_hash != canonical_value_hash(unsigned):
        raise ValidationError("release holdout authority context hash mismatch")
    store = value.get("immutable_store")
    acl = value.get("acl_receipt")
    if not isinstance(store, Mapping) or set(store) != _IMMUTABLE_STORE_CONTEXT_KEYS:
        raise ValidationError("release holdout immutable store context schema mismatch")
    if not isinstance(acl, Mapping) or set(acl) != _ACL_CONTEXT_KEYS:
        raise ValidationError("release holdout ACL context schema mismatch")
    root_value = store.get("root")
    if not isinstance(root_value, str) or not Path(root_value).is_absolute():
        raise ValidationError("release holdout immutable store root must be absolute")
    root = Path(root_value)
    if root.is_symlink():
        raise ValidationError("release holdout immutable store root must not be a symlink")
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise ValidationError("release holdout immutable store root is unresolved") from exc
    if not root.is_dir():
        raise ValidationError("release holdout immutable store root must be a directory")
    for field in ("store_id", "namespace", "object_prefix", "retention_mode", "receipt_issuer_identity"):
        _require_identity(store.get(field), f"immutable_store.{field}")
    if store.get("retention_mode") != "governance-compliance":
        raise ValidationError("release holdout retention mode must be governance-compliance")
    _require_identity(acl.get("issuer_identity"), "acl_receipt.issuer_identity")
    _require_sha256(acl.get("receipt_hash"), "acl_receipt.receipt_hash")
    allowlists: dict[str, tuple[str, ...]] = {}
    for field in ("allowed_manifest_issuers", "allowed_evaluator_identities", "allowed_verifier_identities"):
        raw = value.get(field)
        if not isinstance(raw, list) or not raw or any(not isinstance(item, str) or not _IDENTITY_RE.fullmatch(item) for item in raw):
            raise ValidationError(f"release holdout authority {field} is invalid")
        if len(set(raw)) != len(raw):
            raise ValidationError(f"release holdout authority {field} contains duplicates")
        allowlists[field] = tuple(raw)
    valid_from = _parse_utc(value.get("valid_from"), "valid_from")
    expires_at = _parse_utc(value.get("expires_at"), "expires_at")
    now = datetime.now(timezone.utc)
    if valid_from > now or expires_at <= now or expires_at <= valid_from:
        raise ValidationError("release holdout authority context is not currently valid")
    return ReleaseHoldoutAuthorityContext(
        config_path=held.path, context_hash=context_hash,
        allowed_manifest_issuers=allowlists["allowed_manifest_issuers"],
        allowed_evaluator_identities=allowlists["allowed_evaluator_identities"],
        allowed_verifier_identities=allowlists["allowed_verifier_identities"],
        store_root=root, store_id=str(store["store_id"]), namespace=str(store["namespace"]),
        object_prefix=str(store["object_prefix"]), retention_mode=str(store["retention_mode"]),
        receipt_issuer_identity=str(store["receipt_issuer_identity"]),
        acl_issuer_identity=str(acl["issuer_identity"]), acl_receipt_hash=str(acl["receipt_hash"]),
        valid_from=valid_from, expires_at=expires_at,
    )


def verify_release_holdout_authority_context_current(
    snapshot: ReleaseHoldoutAuthorityContext,
) -> None:
    current = resolve_release_holdout_authority_context()
    if current != snapshot:
        raise ValidationError("release holdout authority context rotated during operation")


def seal_release_holdout_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Seal the external authority's manifest with an exact v1 schema."""
    context = resolve_release_holdout_authority_context()
    if "manifest_hash" in payload:
        raise ValidationError("release holdout manifest payload is already sealed")
    manifest = dict(payload)
    manifest.setdefault("authority_context_hash", context.context_hash)
    manifest["manifest_hash"] = canonical_value_hash(manifest)
    _validate_manifest_mapping(manifest, context=context)
    return manifest


def write_release_holdout_manifest(
    path: str | Path, payload: Mapping[str, Any]
) -> ValidatedReleaseHoldoutManifest:
    """Write a newly sealed manifest atomically and return its capability."""
    destination = Path(path).absolute()
    manifest = seal_release_holdout_manifest(payload)
    _write_path_exclusive_atomic(destination, canonical_json_bytes(manifest))
    return load_release_holdout_manifest(destination)


def load_release_holdout_manifest(path: str | Path) -> ValidatedReleaseHoldoutManifest:
    context = resolve_release_holdout_authority_context()
    held = read_stable_file(path, max_bytes=64 * 1024)
    try:
        value = json.loads(held.payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("release holdout manifest is not canonical JSON") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != held.payload:
        raise ValidationError("release holdout manifest is not canonical JSON")
    holdout_object = _validate_manifest_mapping(value, context=context)
    return ValidatedReleaseHoldoutManifest(
        _manifest=deepcopy(value),
        manifest_path=held.path,
        manifest_hash=value["manifest_hash"],
        authority_context=context,
        _holdout_bytes=holdout_object.payload,
    )


def evaluate_release_holdout(
    *,
    manifest: ValidatedReleaseHoldoutManifest,
    state_root: str | Path,
    baseline_sha256: str,
    candidate_sha256: str,
    thresholds: Mapping[str, float],
    evaluator_identity: str,
    contract_identity: str,
    nonce: str,
    selection_evidence: Mapping[str, Any],
    evaluator: Callable[[ValidatedReleaseHoldoutManifest], ReleaseHoldoutAggregate],
) -> ValidatedReleaseHoldoutEvaluation:
    """Consume one generation once, returning only validated aggregate evidence."""
    if not isinstance(manifest, ValidatedReleaseHoldoutManifest):
        raise ValidationError("release evaluation requires a validated manifest capability")
    current = load_release_holdout_manifest(manifest.manifest_path)
    if current.manifest_hash != manifest.manifest_hash:
        raise ValidationError("release holdout manifest authority changed")
    if current.authority_context != manifest.authority_context:
        raise ValidationError("release holdout authority context rotated")
    _require_sha256(baseline_sha256, "baseline_sha256")
    _require_sha256(candidate_sha256, "candidate_sha256")
    normalized_thresholds = _validate_thresholds(thresholds)
    _require_identity(evaluator_identity, "evaluator_identity")
    if evaluator_identity not in current.authority_context.allowed_evaluator_identities:
        raise ValidationError("release holdout evaluator is not deployment-authorized")
    _require_identity(contract_identity, "contract_identity")
    _require_identity(nonce, "nonce")
    normalized_selection = _validate_selection_evidence(
        selection_evidence,
        baseline_sha256=baseline_sha256,
        candidate_sha256=candidate_sha256,
    )
    request = {
        "version": RELEASE_HOLDOUT_PRECOMMIT_VERSION,
        "generation_id": manifest["generation_id"],
        "manifest_hash": manifest.manifest_hash,
        "manifest_path": str(manifest.manifest_path),
        "authority_context_hash": current.authority_context.context_hash,
        "baseline_sha256": baseline_sha256,
        "candidate_sha256": candidate_sha256,
        "thresholds": normalized_thresholds,
        "evaluator_identity": evaluator_identity,
        "contract_identity": contract_identity,
        "nonce": nonce,
        "selection_evidence": normalized_selection,
    }
    request_hash = canonical_value_hash(request)
    precommit = {**request, "request_hash": request_hash}
    precommit["precommit_hash"] = canonical_value_hash(precommit)
    root = Path(state_root).absolute()
    generation_key = hashlib.sha256(str(manifest["generation_id"]).encode()).hexdigest()
    generation_root = root / "generations" / generation_key

    with _StateLease(root, generation_key) as lease:
        return _evaluate_locked(
            manifest=current,
            lease=lease,
            generation_root=generation_root,
            precommit=precommit,
            evaluator=evaluator,
            state_root=root,
        )


def load_validated_release_holdout_evaluation(
    reference: Mapping[str, Any],
) -> ValidatedReleaseHoldoutEvaluation:
    """Rebuild a release capability from a narrow persisted reference.

    A path or decoded record is deliberately insufficient: every authoritative
    file and the deployment-owned authority/store context is replayed here.
    """
    keys = {
        "version", "state_root", "record_path", "manifest_path", "generation_id",
        "evaluation_hash", "authority_context_hash",
    }
    if not isinstance(reference, Mapping) or set(reference) != keys:
        raise ValidationError("release holdout capability reference schema mismatch")
    if reference.get("version") != "release_holdout_capability_reference_v1":
        raise ValidationError("release holdout capability reference version mismatch")
    for field in ("state_root", "record_path", "manifest_path"):
        raw = reference.get(field)
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise ValidationError(f"release holdout capability {field} must be absolute")
    _require_sha256(reference.get("evaluation_hash"), "capability evaluation_hash")
    _require_sha256(reference.get("authority_context_hash"), "capability authority_context_hash")
    generation_id = reference.get("generation_id")
    if not isinstance(generation_id, str) or not _GENERATION_RE.fullmatch(generation_id):
        raise ValidationError("release holdout capability generation_id is invalid")
    context = resolve_release_holdout_authority_context()
    if reference["authority_context_hash"] != context.context_hash:
        raise ValidationError("release holdout capability authority context rotated")
    manifest = load_release_holdout_manifest(reference["manifest_path"])
    generation_key = hashlib.sha256(generation_id.encode()).hexdigest()
    state_root = Path(str(reference["state_root"])).absolute()
    expected_record = state_root / "generations" / generation_key / "evaluation.json"
    if Path(str(reference["record_path"])).absolute() != expected_record:
        raise ValidationError("release holdout capability record path is not canonical")
    with _StateLease(state_root, generation_key) as lease:
        lease.assert_stable()
        precommit = _load_exact_at(lease.generation_fd, "precommit.json", _PRECOMMIT_KEYS, "precommit")
        status = _load_exact_at(lease.generation_fd, "status.json", _STATUS_KEYS, "status")
        journal = _load_exact_at(lease.generation_fd, "journal.json", _JOURNAL_KEYS, "journal")
        record = _load_exact_at(lease.generation_fd, "evaluation.json", _EVALUATION_KEYS, "evaluation")
        consumption = _load_exact_at(
            lease.generation_fd, "consumption.json", _CONSUMPTION_KEYS, "consumption"
        )
        _validate_precommit(precommit)
        _validate_status_journal(status, journal, precommit)
        _validate_evaluation(record, precommit)
        _validate_consumption(consumption, precommit, record)
        if precommit["generation_id"] != generation_id:
            raise ValidationError("release holdout capability generation binding mismatch")
        if precommit["manifest_path"] != str(manifest.manifest_path):
            raise ValidationError("release holdout capability manifest path binding mismatch")
        if precommit["manifest_hash"] != manifest.manifest_hash:
            raise ValidationError("release holdout capability manifest hash binding mismatch")
        if precommit["authority_context_hash"] != context.context_hash:
            raise ValidationError("release holdout capability authority binding mismatch")
        if status["state"] != "spent" or status["reason"] not in {"accepted", "rejected"}:
            raise ValidationError("release holdout capability is not terminal spent evidence")
        if status["evaluation_hash"] != record["evaluation_hash"]:
            raise ValidationError("release holdout capability terminal hash mismatch")
        if record["evaluation_hash"] != reference["evaluation_hash"]:
            raise ValidationError("release holdout capability evaluation reference mismatch")
        if _exists_at(lease.generation_fd, "incidents"):
            incidents_fd = _open_existing_directory_at(lease.generation_fd, "incidents")
            try:
                if os.listdir(incidents_fd):
                    raise ValidationError("release holdout spent capability has incidents")
            finally:
                os.close(incidents_fd)
        lease.assert_stable()
    verify_release_holdout_authority_context_current(context)
    return ValidatedReleaseHoldoutEvaluation(
        _record=deepcopy(record), record_path=expected_record,
        evaluation_hash=str(record["evaluation_hash"]), state_root=state_root,
        manifest_path=manifest.manifest_path, authority_context_hash=context.context_hash,
        authority_context=context,
    )


def verify_release_holdout_evaluation_authority_current(
    capability: ValidatedReleaseHoldoutEvaluation,
) -> None:
    """Re-verify the release authority, manifest, store identity, and exact object."""
    if not isinstance(capability, ValidatedReleaseHoldoutEvaluation):
        raise ValidationError("release holdout authority check requires a validated capability")
    if capability.manifest_path is None or capability.authority_context is None:
        raise ValidationError("release holdout capability is missing authority snapshot")
    verify_release_holdout_authority_context_current(capability.authority_context)
    manifest = load_release_holdout_manifest(capability.manifest_path)
    if manifest.authority_context != capability.authority_context:
        raise ValidationError("release holdout authority context rotated")
    if manifest.manifest_hash != capability["manifest_hash"]:
        raise ValidationError("release holdout manifest authority changed")
    if manifest["authority_context_hash"] != capability.authority_context_hash:
        raise ValidationError("release holdout manifest authority binding changed")


def _evaluate_locked(
    *,
    manifest: ValidatedReleaseHoldoutManifest,
    lease: _StateLease,
    generation_root: Path,
    precommit: Mapping[str, Any],
    evaluator: Callable[[ValidatedReleaseHoldoutManifest], ReleaseHoldoutAggregate],
    state_root: Path,
) -> ValidatedReleaseHoldoutEvaluation:
    evaluation_path = generation_root / "evaluation.json"
    request_hash = str(precommit["request_hash"])

    lease.assert_stable()
    existing_names = [
        name
        for name in ("precommit.json", "status.json", "journal.json", "evaluation.json")
        if _exists_at(lease.generation_fd, name)
    ]
    if existing_names:
        try:
            existing_precommit = _load_exact_at(lease.generation_fd, "precommit.json", _PRECOMMIT_KEYS, "precommit")
            _validate_precommit(existing_precommit)
            status = _load_exact_at(lease.generation_fd, "status.json", _STATUS_KEYS, "status")
            journal = _load_exact_at(lease.generation_fd, "journal.json", _JOURNAL_KEYS, "journal")
            _validate_status_journal(status, journal, existing_precommit)
        except ValidationError as exc:
            _quarantine_locked(
                lease,
                request_hash=request_hash,
                precommit_hash=str(precommit["precommit_hash"]),
                reason="corrupt_or_torn_generation_state",
                detail=str(exc),
            )
            raise ReleaseHoldoutAttemptError(
                "release holdout generation state is corrupt; rotate generation"
            ) from exc
        if existing_precommit["request_hash"] != request_hash or existing_precommit != dict(precommit):
            _quarantine_locked(
                lease,
                request_hash=str(existing_precommit["request_hash"]),
                precommit_hash=str(existing_precommit["precommit_hash"]),
                reason="generation_reuse_mismatch",
                detail="different pair, nonce, request, threshold, or identity attempted reuse",
            )
            raise ReleaseHoldoutAttemptError(
                "release holdout generation cannot be reused with a different request"
            )
        if status["state"] == "spent":
            try:
                record = _load_exact_at(lease.generation_fd, "evaluation.json", _EVALUATION_KEYS, "evaluation")
                consumption = _load_exact_at(
                    lease.generation_fd, "consumption.json", _CONSUMPTION_KEYS, "consumption"
                )
                _validate_evaluation(record, existing_precommit)
                _validate_consumption(consumption, existing_precommit, record)
                if status["evaluation_hash"] != record["evaluation_hash"]:
                    raise ValidationError("release holdout status evaluation_hash mismatch")
                if status["reason"] != record["outcome"]:
                    raise ValidationError("release holdout status outcome mismatch")
            except ValidationError as exc:
                _quarantine_locked(
                    lease,
                    request_hash=request_hash,
                    precommit_hash=str(precommit["precommit_hash"]),
                    reason="corrupt_or_torn_generation_state",
                    detail=str(exc),
                )
                raise ReleaseHoldoutAttemptError(
                    "release holdout generation state is corrupt; rotate generation"
                ) from exc
            try:
                verify_release_holdout_authority_context_current(
                    manifest.authority_context
                )
            except ValidationError as exc:
                _quarantine_locked(
                    lease,
                    request_hash=request_hash,
                    precommit_hash=str(precommit["precommit_hash"]),
                    reason="authority_context_rotated",
                    detail=str(exc),
                )
                raise ReleaseHoldoutAttemptError(
                    "release holdout authority rotated during replay; generation quarantined"
                ) from exc
            return ValidatedReleaseHoldoutEvaluation(
                _record=deepcopy(record),
                record_path=evaluation_path,
                evaluation_hash=str(record["evaluation_hash"]),
                replayed=True,
                state_root=state_root,
                manifest_path=manifest.manifest_path,
                authority_context_hash=manifest.authority_context.context_hash,
                authority_context=manifest.authority_context,
            )
        if status["state"] == "quarantined":
            raise ReleaseHoldoutAttemptError(
                "release holdout generation is quarantined; rotate generation"
            )
        _quarantine_locked(
            lease,
            request_hash=request_hash,
            precommit_hash=str(precommit["precommit_hash"]),
            reason="partial_or_interrupted_attempt",
            detail="precommit exists without a valid terminal state",
        )
        raise ReleaseHoldoutAttemptError(
            "release holdout attempt was interrupted; generation quarantined"
        )

    verify_release_holdout_authority_context_current(manifest.authority_context)
    _write_exclusive_at(lease.generation_fd, "precommit.json", canonical_json_bytes(precommit))
    journal = _journal(
        generation_id=str(precommit["generation_id"]),
        request_hash=request_hash,
        events=[{"sequence": 1, "state": "precommitted", "reason": "fixed_pair_committed"}],
    )
    _write_exclusive_at(lease.generation_fd, "journal.json", canonical_json_bytes(journal))
    status = _status(precommit, state="precommitted", reason="fixed_pair_committed")
    _write_exclusive_at(lease.generation_fd, "status.json", canonical_json_bytes(status))
    lease.assert_stable()
    try:
        verify_release_holdout_authority_context_current(manifest.authority_context)
    except ValidationError as exc:
        _quarantine_locked(
            lease, request_hash=request_hash,
            precommit_hash=str(precommit["precommit_hash"]),
            reason="authority_context_rotated", detail=str(exc),
        )
        raise ReleaseHoldoutAttemptError(
            "release holdout authority rotated after precommit; generation quarantined"
        ) from exc

    try:
        aggregate = evaluator(manifest)
        normalized = _validate_aggregate(aggregate, precommit["thresholds"])
    except TimeoutError as exc:
        _quarantine_locked(lease, request_hash=request_hash, precommit_hash=str(precommit["precommit_hash"]), reason="timeout", detail=type(exc).__name__)
        raise ReleaseHoldoutAttemptError("release holdout timed out; generation quarantined") from exc
    except asyncio.CancelledError as exc:
        _quarantine_locked(lease, request_hash=request_hash, precommit_hash=str(precommit["precommit_hash"]), reason="cancelled", detail=type(exc).__name__)
        raise ReleaseHoldoutAttemptError("release holdout cancelled; generation quarantined") from exc
    except PartialHoldoutExposureError as exc:
        _quarantine_locked(lease, request_hash=request_hash, precommit_hash=str(precommit["precommit_hash"]), reason="partial_exposure", detail=type(exc).__name__)
        raise ReleaseHoldoutAttemptError("release holdout partially exposed; generation quarantined") from exc
    except Exception as exc:
        _quarantine_locked(lease, request_hash=request_hash, precommit_hash=str(precommit["precommit_hash"]), reason="evaluation_error", detail=type(exc).__name__)
        raise ReleaseHoldoutAttemptError("release holdout evaluation failed; generation quarantined") from exc
    except (KeyboardInterrupt, SystemExit) as exc:
        _quarantine_locked(
            lease,
            request_hash=request_hash,
            precommit_hash=str(precommit["precommit_hash"]),
            reason="process_termination",
            detail=type(exc).__name__,
        )
        raise

    lease.assert_stable()
    try:
        verify_release_holdout_authority_context_current(manifest.authority_context)
        current_manifest = load_release_holdout_manifest(manifest.manifest_path)
        if current_manifest.manifest_hash != manifest.manifest_hash:
            raise ValidationError("release holdout manifest rotated during evaluation")
    except ValidationError as exc:
        _quarantine_locked(
            lease, request_hash=request_hash,
            precommit_hash=str(precommit["precommit_hash"]),
            reason="authority_context_rotated", detail=str(exc),
        )
        raise ReleaseHoldoutAttemptError(
            "release holdout authority rotated during evaluation; generation quarantined"
        ) from exc
    outcome = "accepted" if all(normalized.threshold_results.values()) else "rejected"
    record: dict[str, Any] = {
        "version": RELEASE_HOLDOUT_EVALUATION_VERSION,
        "evaluation_id": f"release:{request_hash.removeprefix('sha256:')}",
        "generation_id": precommit["generation_id"],
        "manifest_hash": precommit["manifest_hash"],
        "authority_context_hash": precommit["authority_context_hash"],
        "request_hash": request_hash,
        "precommit_hash": precommit["precommit_hash"],
        "authority_classification": APPROVAL_AGGREGATE_AUTHORITY,
        "baseline_sha256": precommit["baseline_sha256"],
        "candidate_sha256": precommit["candidate_sha256"],
        "evaluator_identity": precommit["evaluator_identity"],
        "contract_identity": precommit["contract_identity"],
        "outcome": outcome,
        "sample_count": normalized.sample_count,
        "metrics": dict(normalized.metrics),
        "threshold_results": dict(normalized.threshold_results),
    }
    record["evaluation_hash"] = canonical_value_hash(record)
    try:
        _write_exclusive_at(lease.generation_fd, "evaluation.json", canonical_json_bytes(record))
        consumption = {
            "version": RELEASE_HOLDOUT_CONSUMPTION_VERSION,
            "generation_id": precommit["generation_id"],
            "request_hash": request_hash,
            "precommit_hash": precommit["precommit_hash"],
            "manifest_hash": precommit["manifest_hash"],
            "authority_context_hash": precommit["authority_context_hash"],
            "evaluation_hash": record["evaluation_hash"],
            "outcome": outcome,
        }
        consumption["consumption_hash"] = canonical_value_hash(consumption)
        _write_exclusive_at(
            lease.generation_fd, "consumption.json", canonical_json_bytes(consumption)
        )
        terminal_journal = _journal(
            generation_id=str(precommit["generation_id"]),
            request_hash=request_hash,
            events=[
                {"sequence": 1, "state": "precommitted", "reason": "fixed_pair_committed"},
                {"sequence": 2, "state": "spent", "reason": outcome},
            ],
        )
        _write_atomic_at(lease.generation_fd, "journal.json", canonical_json_bytes(terminal_journal))
        terminal_status = _status(
            precommit,
            state="spent",
            reason=outcome,
            evaluation_hash=str(record["evaluation_hash"]),
        )
        _write_atomic_at(lease.generation_fd, "status.json", canonical_json_bytes(terminal_status))
        lease.assert_stable()
        verify_release_holdout_authority_context_current(manifest.authority_context)
    except (KeyboardInterrupt, SystemExit) as exc:
        _quarantine_locked(
            lease,
            request_hash=request_hash,
            precommit_hash=str(precommit["precommit_hash"]),
            reason="terminal_persistence_interrupted",
            detail=type(exc).__name__,
        )
        raise
    except Exception as exc:
        _quarantine_locked(
            lease,
            request_hash=request_hash,
            precommit_hash=str(precommit["precommit_hash"]),
            reason="terminal_persistence_error",
            detail=type(exc).__name__,
        )
        raise ReleaseHoldoutAttemptError(
            "release holdout terminal persistence failed; generation quarantined"
        ) from exc
    return ValidatedReleaseHoldoutEvaluation(
        _record=deepcopy(record),
        record_path=evaluation_path,
        evaluation_hash=str(record["evaluation_hash"]),
        state_root=state_root,
        manifest_path=manifest.manifest_path,
        authority_context_hash=manifest.authority_context.context_hash,
        authority_context=manifest.authority_context,
    )


def _validate_manifest_mapping(
    value: Mapping[str, Any], *, context: ReleaseHoldoutAuthorityContext
) -> StableFile:
    if set(value) != _MANIFEST_KEYS:
        raise ValidationError("release holdout manifest schema mismatch")
    if value.get("version") != RELEASE_HOLDOUT_MANIFEST_VERSION:
        raise ValidationError("release holdout manifest version mismatch")
    expected_manifest = dict(value)
    manifest_identity = expected_manifest.pop("manifest_hash", None)
    _require_sha256(manifest_identity, "manifest_hash")
    if manifest_identity != canonical_value_hash(expected_manifest):
        raise ValidationError("release holdout manifest hash mismatch")
    generation = value.get("generation_id")
    if not isinstance(generation, str) or not _GENERATION_RE.fullmatch(generation):
        raise ValidationError("release holdout generation_id is invalid")
    _require_identity(value.get("object_version"), "object_version")
    _require_sha256(value.get("holdout_sha256"), "holdout_sha256")
    size = value.get("holdout_size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ValidationError("release holdout size must be a positive integer")
    if value.get("authority_classification") != RELEASE_HOLDOUT_AUTHORITY:
        raise ValidationError("release holdout authority classification mismatch")
    _require_identity(value.get("issuer_identity"), "issuer_identity")
    if value.get("issuer_identity") not in context.allowed_manifest_issuers:
        raise ValidationError("release holdout manifest issuer is not authorized")
    _require_identity(value.get("verifier_identity"), "verifier_identity")
    if value.get("verifier_identity") not in context.allowed_verifier_identities:
        raise ValidationError("release holdout verifier is not authorized")
    if value.get("authority_context_hash") != context.context_hash:
        raise ValidationError("release holdout manifest authority context mismatch")
    receipt = value.get("immutable_store_receipt")
    if not isinstance(receipt, Mapping) or set(receipt) != _STORE_RECEIPT_KEYS:
        raise ValidationError("release holdout immutable store receipt schema mismatch")
    unsigned_receipt = dict(receipt)
    receipt_hash = unsigned_receipt.pop("receipt_hash", None)
    _require_sha256(receipt_hash, "immutable store receipt hash")
    if receipt_hash != canonical_value_hash(unsigned_receipt):
        raise ValidationError("release holdout immutable store receipt hash mismatch")
    exact_receipt = {
        "store_id": context.store_id,
        "namespace": context.namespace,
        "object_version": value.get("object_version"),
        "holdout_sha256": value.get("holdout_sha256"),
        "holdout_size_bytes": value.get("holdout_size_bytes"),
        "retention_mode": context.retention_mode,
        "acl_receipt_hash": context.acl_receipt_hash,
        "receipt_issuer_identity": context.receipt_issuer_identity,
    }
    for field, expected_value in exact_receipt.items():
        if receipt.get(field) != expected_value:
            raise ValidationError(f"release holdout immutable store receipt {field} mismatch")
    object_key = receipt.get("object_key")
    if not isinstance(object_key, str) or not object_key.startswith(context.object_prefix):
        raise ValidationError("release holdout immutable object key is outside authority prefix")
    relative = Path(object_key)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValidationError("release holdout immutable object key is unsafe")
    object_path = context.store_root / context.namespace / relative
    held = read_stable_file(object_path, max_bytes=64 * 1024 * 1024)
    if held.sha256 != value.get("holdout_sha256") or held.size_bytes != value.get("holdout_size_bytes"):
        raise ValidationError("release holdout immutable object exact bytes mismatch")
    verify_release_holdout_authority_context_current(context)
    return held


def _validate_selection_evidence(
    value: Mapping[str, Any], *, baseline_sha256: str, candidate_sha256: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError("selection evidence must be a mapping")
    evidence = deepcopy(dict(value))
    if evidence.get("status") != "passed":
        raise ValidationError("selection evidence must prove passed selection")
    # Existing selection records bind evaluation-record hashes, which are not
    # the skill hashes precommitted above.  When an integration record also
    # declares skill hashes, require them to agree without conflating the two.
    if "baseline_skill_hash" in evidence and evidence["baseline_skill_hash"] != baseline_sha256:
        raise ValidationError("selection evidence baseline skill hash mismatch")
    if "candidate_skill_hash" in evidence and evidence["candidate_skill_hash"] != candidate_sha256:
        raise ValidationError("selection evidence candidate skill hash mismatch")
    evidence_hash = evidence.get("evidence_hash")
    _require_sha256(evidence_hash, "selection evidence_hash")
    try:
        canonical_json_bytes(evidence)
    except (TypeError, ValueError) as exc:
        raise ValidationError("selection evidence is not canonical JSON") from exc
    return evidence


def _validate_thresholds(value: Mapping[str, float]) -> dict[str, float]:
    if not isinstance(value, Mapping) or not value:
        raise ValidationError("release holdout thresholds must be nonempty")
    normalized: dict[str, float] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or not _IDENTITY_RE.fullmatch(key):
            raise ValidationError("release holdout threshold name is invalid")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
            raise ValidationError("release holdout threshold must be finite")
        normalized[key] = float(raw)
    return dict(sorted(normalized.items()))


def _validate_aggregate(value: Any, thresholds: Mapping[str, Any]) -> ReleaseHoldoutAggregate:
    if not isinstance(value, ReleaseHoldoutAggregate):
        raise ValidationError("evaluator must return ReleaseHoldoutAggregate, never raw detail")
    if isinstance(value.sample_count, bool) or not isinstance(value.sample_count, int) or value.sample_count <= 0:
        raise ValidationError("release aggregate sample_count must be positive")
    if not isinstance(value.metrics, Mapping) or set(value.metrics) != set(thresholds):
        raise ValidationError("release aggregate metrics must exactly match thresholds")
    metrics: dict[str, float] = {}
    for key, raw in value.metrics.items():
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
            raise ValidationError("release aggregate metrics must be finite")
        metrics[str(key)] = float(raw)
    if not isinstance(value.threshold_results, Mapping) or set(value.threshold_results) != set(thresholds):
        raise ValidationError("release aggregate threshold results must exactly match thresholds")
    results = dict(value.threshold_results)
    if any(type(result) is not bool for result in results.values()):
        raise ValidationError("release aggregate threshold results must be booleans")
    return ReleaseHoldoutAggregate(value.sample_count, dict(sorted(metrics.items())), dict(sorted(results.items())))


def _validate_precommit(value: Mapping[str, Any]) -> None:
    if set(value) != _PRECOMMIT_KEYS or value.get("version") != RELEASE_HOLDOUT_PRECOMMIT_VERSION:
        raise ValidationError("release holdout precommit schema mismatch")
    expected = dict(value)
    precommit_hash = expected.pop("precommit_hash", None)
    _require_sha256(precommit_hash, "precommit_hash")
    if precommit_hash != canonical_value_hash(expected):
        raise ValidationError("release holdout precommit hash mismatch")
    request = dict(expected)
    request_hash = request.pop("request_hash", None)
    if request_hash != canonical_value_hash(request):
        raise ValidationError("release holdout request hash mismatch")


def _validate_status_journal(status: Mapping[str, Any], journal: Mapping[str, Any], precommit: Mapping[str, Any]) -> None:
    if status.get("version") != RELEASE_HOLDOUT_STATUS_VERSION:
        raise ValidationError("release holdout status version mismatch")
    if status.get("generation_id") != precommit["generation_id"] or status.get("request_hash") != precommit["request_hash"]:
        raise ValidationError("release holdout status binding mismatch")
    if status.get("precommit_hash") != precommit["precommit_hash"]:
        raise ValidationError("release holdout status precommit mismatch")
    state = status.get("state")
    if state not in {"precommitted", "spent", "quarantined"}:
        raise ValidationError("release holdout status state invalid")
    if journal.get("version") != RELEASE_HOLDOUT_JOURNAL_VERSION:
        raise ValidationError("release holdout journal version mismatch")
    if journal.get("generation_id") != precommit["generation_id"] or journal.get("request_hash") != precommit["request_hash"]:
        raise ValidationError("release holdout journal binding mismatch")
    expected_journal = dict(journal)
    journal_hash = expected_journal.pop("journal_hash", None)
    if journal_hash != canonical_value_hash(expected_journal):
        raise ValidationError("release holdout journal hash mismatch")
    events = journal.get("events")
    if not isinstance(events, list) or not events:
        raise ValidationError("release holdout journal events invalid")
    for index, event in enumerate(events, 1):
        if not isinstance(event, Mapping) or set(event) != _EVENT_KEYS or event.get("sequence") != index:
            raise ValidationError("release holdout journal sequence invalid")
    if events[0] != {
        "sequence": 1,
        "state": "precommitted",
        "reason": "fixed_pair_committed",
    }:
        raise ValidationError("release holdout journal precommit event mismatch")
    if events[-1].get("state") != state:
        raise ValidationError("release holdout journal/status state mismatch")
    if events[-1].get("reason") != status.get("reason"):
        raise ValidationError("release holdout journal/status reason mismatch")
    evaluation_hash = status.get("evaluation_hash")
    incident_hash = status.get("incident_hash")
    if state == "precommitted":
        if status.get("reason") != "fixed_pair_committed" or evaluation_hash is not None or incident_hash is not None:
            raise ValidationError("release holdout precommitted status semantics mismatch")
        if len(events) != 1:
            raise ValidationError("release holdout precommitted journal length mismatch")
    elif state == "spent":
        if status.get("reason") not in {"accepted", "rejected"}:
            raise ValidationError("release holdout spent reason mismatch")
        _require_sha256(evaluation_hash, "status evaluation_hash")
        if incident_hash is not None or len(events) != 2:
            raise ValidationError("release holdout spent terminal semantics mismatch")
        if events[1] != {
            "sequence": 2,
            "state": "spent",
            "reason": status.get("reason"),
        }:
            raise ValidationError("release holdout spent journal sequence mismatch")
    else:
        if not isinstance(status.get("reason"), str) or not status["reason"]:
            raise ValidationError("release holdout quarantine reason mismatch")
        _require_sha256(incident_hash, "status incident_hash")
        if evaluation_hash is not None or len(events) != 2:
            raise ValidationError("release holdout quarantine terminal semantics mismatch")
        if events[1] != {
            "sequence": 2,
            "state": "quarantined",
            "reason": status.get("reason"),
        }:
            raise ValidationError("release holdout quarantine journal sequence mismatch")


def _validate_evaluation(record: Mapping[str, Any], precommit: Mapping[str, Any]) -> None:
    if record.get("version") != RELEASE_HOLDOUT_EVALUATION_VERSION:
        raise ValidationError("release holdout evaluation version mismatch")
    for key in ("generation_id", "manifest_hash", "authority_context_hash", "request_hash", "precommit_hash", "baseline_sha256", "candidate_sha256", "evaluator_identity", "contract_identity"):
        if record.get(key) != precommit.get(key):
            raise ValidationError(f"release holdout evaluation {key} mismatch")
    if record.get("authority_classification") != APPROVAL_AGGREGATE_AUTHORITY:
        raise ValidationError("release holdout evaluation authority mismatch")
    expected = dict(record)
    identity = expected.pop("evaluation_hash", None)
    if identity != canonical_value_hash(expected):
        raise ValidationError("release holdout evaluation hash mismatch")
    aggregate = ReleaseHoldoutAggregate(record.get("sample_count"), record.get("metrics"), record.get("threshold_results"))
    _validate_aggregate(aggregate, precommit["thresholds"])
    expected_outcome = "accepted" if all(record["threshold_results"].values()) else "rejected"
    if record.get("outcome") != expected_outcome:
        raise ValidationError("release holdout evaluation outcome mismatch")


def _validate_consumption(
    value: Mapping[str, Any], precommit: Mapping[str, Any], record: Mapping[str, Any]
) -> None:
    if set(value) != _CONSUMPTION_KEYS or value.get("version") != RELEASE_HOLDOUT_CONSUMPTION_VERSION:
        raise ValidationError("release holdout consumption schema mismatch")
    expected = dict(value)
    identity = expected.pop("consumption_hash", None)
    if identity != canonical_value_hash(expected):
        raise ValidationError("release holdout consumption hash mismatch")
    bindings = {
        "generation_id": precommit["generation_id"],
        "request_hash": precommit["request_hash"],
        "precommit_hash": precommit["precommit_hash"],
        "manifest_hash": precommit["manifest_hash"],
        "authority_context_hash": precommit["authority_context_hash"],
        "evaluation_hash": record["evaluation_hash"],
        "outcome": record["outcome"],
    }
    for field, expected_value in bindings.items():
        if value.get(field) != expected_value:
            raise ValidationError(f"release holdout consumption {field} mismatch")


def _status(precommit: Mapping[str, Any], *, state: str, reason: str, evaluation_hash: str | None = None, incident_hash: str | None = None) -> dict[str, Any]:
    return {
        "version": RELEASE_HOLDOUT_STATUS_VERSION,
        "generation_id": precommit["generation_id"],
        "request_hash": precommit["request_hash"],
        "state": state,
        "reason": reason,
        "precommit_hash": precommit["precommit_hash"],
        "evaluation_hash": evaluation_hash,
        "incident_hash": incident_hash,
    }


def _journal(*, generation_id: str, request_hash: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "version": RELEASE_HOLDOUT_JOURNAL_VERSION,
        "generation_id": generation_id,
        "request_hash": request_hash,
        "events": events,
    }
    value["journal_hash"] = canonical_value_hash(value)
    return value


def _quarantine_locked(lease: _StateLease, *, request_hash: str, precommit_hash: str, reason: str, detail: str) -> None:
    lease.assert_stable()
    generation_id = _generation_id_best_effort(lease.generation_fd) or "unknown-generation"
    incident: dict[str, Any] = {
        "version": RELEASE_HOLDOUT_INCIDENT_VERSION,
        "generation_id": generation_id,
        "request_hash": request_hash,
        "reason": reason,
        "detail_classification": detail[:256],
        "evidence_valid": False,
        "rotation_required": True,
    }
    incident["incident_hash"] = canonical_value_hash(incident)
    incident_name = f"{incident['incident_hash'].removeprefix('sha256:')}.json"
    incidents_fd = _open_or_create_directory_at(lease.generation_fd, "incidents")
    try:
        if not _exists_at(incidents_fd, incident_name):
            _write_exclusive_at(incidents_fd, incident_name, canonical_json_bytes(incident))
    finally:
        os.close(incidents_fd)
    terminal_journal = _journal(
        generation_id=generation_id,
        request_hash=request_hash,
        events=[
            {"sequence": 1, "state": "precommitted", "reason": "fixed_pair_committed"},
            {"sequence": 2, "state": "quarantined", "reason": reason},
        ],
    )
    _write_atomic_at(lease.generation_fd, "journal.json", canonical_json_bytes(terminal_journal))
    status = {
        "version": RELEASE_HOLDOUT_STATUS_VERSION,
        "generation_id": generation_id,
        "request_hash": request_hash,
        "state": "quarantined",
        "reason": reason,
        "precommit_hash": precommit_hash,
        "evaluation_hash": None,
        "incident_hash": incident["incident_hash"],
    }
    _write_atomic_at(lease.generation_fd, "status.json", canonical_json_bytes(status))
    lease.assert_stable()


def _generation_id_best_effort(generation_fd: int) -> str | None:
    try:
        value = _load_exact_at(generation_fd, "precommit.json", _PRECOMMIT_KEYS, "precommit")
    except ValidationError:
        return None
    generation = value.get("generation_id")
    return generation if isinstance(generation, str) else None


class _StateLease:
    """Pinned descriptor graph for the complete generation transaction."""

    def __init__(self, root: Path, generation_key: str) -> None:
        self.root_path = root
        self.generation_key = generation_key
        self.root_parent_fd = -1
        self.root_fd = -1
        self.root_name = ""
        self.path_fds: list[int] = []
        self.path_names: list[str] = []
        self.generations_fd = -1
        self.locks_fd = -1
        self.generation_fd = -1
        self.lock_fd = -1
        self.lock_name = f"{generation_key}.lock"

    def __enter__(self) -> _StateLease:
        try:
            self.path_fds, self.path_names = _open_absolute_directory_lease(self.root_path)
            self.root_parent_fd = self.path_fds[-2]
            self.root_fd = self.path_fds[-1]
            self.root_name = self.path_names[-1]
            self.generations_fd = _open_or_create_directory_at(self.root_fd, "generations")
            self.locks_fd = _open_or_create_directory_at(self.root_fd, "locks")
            self.generation_fd = _open_or_create_directory_at(
                self.generations_fd, self.generation_key
            )
            flags = (
                os.O_RDWR
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                self.lock_fd = os.open(
                    self.lock_name,
                    flags | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=self.locks_fd,
                )
                os.fsync(self.locks_fd)
            except FileExistsError:
                self.lock_fd = os.open(self.lock_name, flags, dir_fd=self.locks_fd)
            info = os.fstat(self.lock_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValidationError("release holdout generation lock is unsafe")
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX)
            self.assert_stable()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def assert_stable(self) -> None:
        for parent_fd, name, child_fd in zip(
            self.path_fds[:-1], self.path_names, self.path_fds[1:], strict=True
        ):
            _assert_named_inode(parent_fd, name, child_fd, directory=True)
        _assert_named_inode(self.root_fd, "generations", self.generations_fd, directory=True)
        _assert_named_inode(self.root_fd, "locks", self.locks_fd, directory=True)
        _assert_named_inode(
            self.generations_fd, self.generation_key, self.generation_fd, directory=True
        )
        _assert_named_inode(self.locks_fd, self.lock_name, self.lock_fd, directory=False)

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.lock_fd >= 0:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
        for attribute in (
            "lock_fd",
            "generation_fd",
            "locks_fd",
            "generations_fd",
        ):
            descriptor = getattr(self, attribute)
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                setattr(self, attribute, -1)
        for descriptor in reversed(self.path_fds):
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.path_fds = []
        self.path_names = []
        self.root_fd = -1
        self.root_parent_fd = -1


def _open_absolute_directory_lease(path: Path) -> tuple[list[int], list[str]]:
    absolute = path.absolute()
    if not absolute.is_absolute() or absolute == Path(absolute.anchor):
        raise ValidationError("release holdout state_root must be a non-root absolute directory")
    parts = absolute.parts
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors = [os.open(absolute.anchor, flags)]
    names: list[str] = []
    try:
        for component in parts[1:]:
            current_fd = descriptors[-1]
            try:
                next_fd = os.open(component, flags, dir_fd=current_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise ValidationError(
                        "release holdout state_root could not create an intermediate component"
                    ) from exc
                try:
                    next_fd = os.open(component, flags, dir_fd=current_fd)
                except OSError as exc:
                    raise ValidationError(
                        "release holdout state_root component became unsafe during creation"
                    ) from exc
            except OSError as exc:
                message = (
                    "release holdout state_root must not be a symlink"
                    if component == parts[-1]
                    else "release holdout state_root has an unsafe intermediate component"
                )
                raise ValidationError(message) from exc
            _assert_named_inode(current_fd, component, next_fd, directory=True)
            descriptors.append(next_fd)
            names.append(component)
        return descriptors, names
    except BaseException:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise


def _open_or_create_directory_at(parent_fd: int, name: str) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise ValidationError(f"release holdout state directory is unsafe: {name}") from exc
    try:
        _assert_named_inode(parent_fd, name, descriptor, directory=True)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _open_existing_directory_at(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise ValidationError(f"release holdout state directory is unsafe: {name}") from exc
    try:
        _assert_named_inode(parent_fd, name, descriptor, directory=True)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _assert_named_inode(parent_fd: int, name: str, descriptor: int, *, directory: bool) -> None:
    held = os.fstat(descriptor)
    try:
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise ValidationError("release holdout state name drifted during transaction") from exc
    expected_mode = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_mode(held.st_mode) or not expected_mode(named.st_mode):
        raise ValidationError("release holdout state entry type drifted during transaction")
    if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
        raise ValidationError("release holdout state entry was replaced during transaction")
    if not directory and (held.st_nlink != 1 or named.st_nlink != 1):
        raise ValidationError("release holdout lock link count is unsafe")


def _exists_at(parent_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ValidationError("release holdout state entry could not be inspected") from exc
    return True


def _load_exact_at(parent_fd: int, name: str, keys: set[str], label: str) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        raise ValidationError(f"release holdout {label} is missing")
    except OSError as exc:
        raise ValidationError(f"release holdout {label} is unsafe") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 1024 * 1024:
            raise ValidationError(f"release holdout {label} is unsafe")
        payload = b""
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                raise ValidationError(f"release holdout {label} changed during read")
            payload += chunk
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValidationError(f"release holdout {label} grew during read")
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValidationError(f"release holdout {label} changed during read")
        if (after.st_dev, after.st_ino) != (named.st_dev, named.st_ino):
            raise ValidationError(f"release holdout {label} was replaced during read")
    finally:
        os.close(descriptor)
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"release holdout {label} is corrupt") from exc
    if not isinstance(value, dict) or set(value) != keys:
        raise ValidationError(f"release holdout {label} schema mismatch")
    if canonical_json_bytes(value) != payload:
        raise ValidationError(f"release holdout {label} is not canonical JSON")
    return value


def _write_exclusive_at(parent_fd: int, name: str, payload: bytes) -> None:
    temporary = f".{name}.{os.getpid()}.{hashlib.sha256(os.urandom(16)).hexdigest()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
        os.unlink(temporary, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except FileExistsError as exc:
        raise ValidationError(f"sealed artifact already exists: {name}") from exc
    finally:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def _write_atomic_at(parent_fd: int, name: str, payload: bytes) -> None:
    temporary = f".{name}.{os.getpid()}.{hashlib.sha256(os.urandom(16)).hexdigest()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def _write_path_exclusive_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{hashlib.sha256(os.urandom(16)).hexdigest()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path, follow_symlinks=False)
        _fsync_path_dir(path.parent)
    except FileExistsError as exc:
        raise ValidationError(f"sealed artifact already exists: {path.name}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_path_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _require_sha256(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValidationError(f"{field} must be a sha256 digest")


def _require_identity(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
        raise ValidationError(f"{field} is invalid")


def _parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValidationError(f"release holdout authority {field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"release holdout authority {field} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"release holdout authority {field} must include timezone")
    return parsed.astimezone(timezone.utc)


__all__ = [
    "APPROVAL_AGGREGATE_AUTHORITY",
    "PartialHoldoutExposureError",
    "RELEASE_HOLDOUT_AUTHORITY",
    "RELEASE_HOLDOUT_AUTHORITY_CONTEXT_ENV",
    "RELEASE_HOLDOUT_AUTHORITY_CONTEXT_VERSION",
    "RELEASE_HOLDOUT_EVALUATION_VERSION",
    "RELEASE_HOLDOUT_MANIFEST_VERSION",
    "ReleaseHoldoutAggregate",
    "ReleaseHoldoutAttemptError",
    "ValidatedReleaseHoldoutEvaluation",
    "ValidatedReleaseHoldoutManifest",
    "evaluate_release_holdout",
    "load_release_holdout_manifest",
    "load_validated_release_holdout_evaluation",
    "resolve_release_holdout_authority_context",
    "seal_release_holdout_manifest",
    "write_release_holdout_manifest",
]
