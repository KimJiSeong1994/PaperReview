"""Authoritative sealed SkillOpt request/result provenance contracts.

The v2 boundary is intentionally incompatible with the earlier draft v1
schema.  A v1 document is never inferred, relabelled, or upgraded.  Every
evidence-bearing file is read once through a stable descriptor, validated from
those exact bytes, and may then be published from the held bytes.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .policy_validation import validate_runtime_policy_text
from .skillopt_compatibility import (
    APPROVED_ARCHIVE_SHA256,
    APPROVED_PEELED_COMMIT,
    APPROVED_TREE_GIT_SHA1,
    CANDIDATE_PATH,
    EVAL_ARGV,
    EVAL_OUT_ROOT,
    PROFILE_ID,
    SOURCE_IMMUTABLE_OBJECT_VERSION,
    TRAIN_ARGV,
    TRAIN_OUT_ROOT,
    domain_separated_hash,
    validate_compatibility_profile,
    validate_overlay_manifest,
    validate_pristine_source_manifest,
    validate_runner_identity,
    validate_same_domain_custody_evidence,
    validate_staging_manifest,
)
from .skillopt_contract import (
    V1_ALLOWED_SCOPE,
    ValidationError,
    validate_dataset_contract,
    validate_execution_control,
)


RUN_REQUEST_VERSION = "skillopt-run-request-v2"
RUN_RESULT_VERSION = "skillopt-run-result-v2"
COMPATIBILITY_REPORT_VERSION = "skillopt-wave1-2-compatibility-report-v1"
AUTHORITY_POLICY_VERSION = "skillopt-sealed-authority-policy-v1"
ACL_SNAPSHOT_VERSION = "skillopt-acl-snapshot-v1"
STORE_RECEIPT_VERSION = "skillopt-immutable-store-receipt-v1"
USAGE_RECEIPT_VERSION = "skillopt-usage-receipt-v1"
PRIVACY_RECEIPT_VERSION = "skillopt-privacy-receipt-v1"
AUTHORITY_CONTEXT_VERSION = "skillopt-authority-context-v1"
AUTHORITY_CONTEXT_ENV = "SKILLOPT_AUTHORITY_CONTEXT_PATH"

INPUT_ARTIFACT_NAMES = (
    "dataset",
    "execution_control",
    "baseline_skill",
    "generated_environment_archive",
    "dependency_lock",
    "rendered_config",
    "compatibility_profile",
    "compatibility_report",
    "pristine_source_manifest",
    "overlay_manifest",
    "staging_manifest",
    "runner_identity",
    "custody_evidence",
    "acl_snapshot",
    "immutable_store_receipt",
    "trusted_authority_policy",
)

_REQUEST_KEYS = {
    "version",
    "request_id",
    "created_at",
    "scope",
    "input_artifacts",
    "upstream",
    "execution",
    "output",
    "authority",
    "privacy",
}
_ARTIFACT_KEYS = {"path", "sha256", "size_bytes"}
_UPSTREAM_KEYS = {
    "profile_id",
    "profile_identity",
    "compatibility_report_identity",
    "skillopt_revision",
    "tree_git_sha1",
    "archive_sha256",
    "runner_image_digest",
    "runner_identity",
    "python_version",
    "dependency_lock_hash",
    "pristine_source_identity",
    "overlay_identity",
    "staging_identity",
    "custody_identity",
}
_EXECUTION_REQUEST_KEYS = {
    "seeds",
    "model_identifier",
    "train_argv",
    "eval_argv",
    "train_argv_identity",
    "eval_argv_identity",
    "execution_config_identity",
    "rendered_config_hash",
    "budget",
    "timeout_seconds",
    "max_retries",
    "max_concurrency",
}
_BUDGET_KEYS = {"max_cost_usd", "max_tokens"}
_OUTPUT_REQUEST_KEYS = {
    "train_root",
    "eval_root",
    "best_skill_path",
    "evaluation_path",
    "sanitized_summary_path",
    "usage_receipt_path",
    "privacy_receipt_path",
    "result_manifest_path",
    "schema_version",
}
_AUTHORITY_KEYS = {
    "evidence_class",
    "policy_identity",
    "coordinator_id",
    "coordinator_namespace",
    "wave3_crypto_required",
}
_PRIVACY_REQUEST_KEYS = {
    "raw_user_logs_included",
    "pii_included",
    "requires_approved_export",
}

_RESULT_KEYS = {
    "version",
    "result_id",
    "request_id",
    "sealed_request",
    "completed_at",
    "scope",
    "status",
    "upstream",
    "execution",
    "observed",
    "outputs",
    "receipts",
    "logs",
    "budget_usage",
    "attestation",
    "candidate_binding",
    "privacy",
}
_SEALED_REQUEST_KEYS = {"request_id", "sha256", "size_bytes"}
_EXECUTION_RESULT_KEYS = {
    "seeds",
    "model_identifier",
    "train_argv_identity",
    "eval_argv_identity",
    "execution_config_identity",
    "rendered_config_hash",
    "timeout_seconds",
    "max_retries",
    "max_concurrency",
    "exit_code",
    "duration_seconds",
    "timed_out",
    "retry_count",
}
_OBSERVED_KEYS = {
    "profile_identity",
    "compatibility_report_identity",
    "pristine_source_identity",
    "overlay_identity",
    "staging_identity",
    "runner_identity",
    "custody_identity",
    "execution_config_identity",
    "rendered_config_hash",
    "train_argv",
    "eval_argv",
    "imported_modules",
    "train_root",
    "eval_root",
    "candidate_path",
}
_OUTPUT_RESULT_KEYS = {"best_skill", "evaluation", "sanitized_summary"}
_RECEIPT_KEYS = {"usage", "privacy"}
_LOG_KEYS = {"stdout_sha256", "stderr_sha256", "redaction_report_sha256"}
_BUDGET_USAGE_KEYS = {"cost_usd", "tokens"}
_ATTESTATION_KEYS = {
    "evidence_class",
    "custody_identity",
    "store_receipt_identity",
    "policy_identity",
}
_CANDIDATE_BINDING_KEYS = {
    "best_skill_hash",
    "evaluation_hash",
    "dataset_hash",
    "execution_control_hash",
    "profile_identity",
    "overlay_identity",
    "staging_identity",
    "runner_identity",
    "custody_identity",
}
_PRIVACY_RESULT_KEYS = {
    "raw_user_logs_included",
    "pii_included",
    "requires_approved_export",
    "redaction_passed",
    "redaction_report_sha256",
}

_COMPATIBILITY_REPORT_KEYS = {
    "version",
    "profile_id",
    "status",
    "evidence_class",
    "authorization_status",
    "authenticity_status",
    "seal_kind",
    "trusted",
    "pristine_source_identity",
    "overlay_identity",
    "staging_identity",
    "runner_identity",
    "custody_identity",
    "execution_config_identity",
    "train_argv_identity",
    "eval_argv_identity",
    "imported_modules",
    "outputs",
    "provider_count",
    "network_count",
    "subprocess_count",
    "identity",
}
_POLICY_KEYS = {
    "version",
    "policy_name",
    "coordinator_id",
    "coordinator_namespace",
    "allowed_profile_identities",
    "allowed_report_identities",
    "allowed_runner_identities",
    "allowed_custody_identities",
    "allowed_issuers",
    "allowed_verifiers",
    "allowed_stores",
    "wave3_trust_roots",
    "identity",
}
_ACL_KEYS = {
    "version",
    "store_id",
    "issuer_workload",
    "verifier_id",
    "coordinator_id",
    "principals",
    "object_versions",
    "issued_at",
    "expires_at",
    "immutable",
    "identity",
}
_STORE_KEYS = {
    "version",
    "store_id",
    "issuer_workload",
    "verifier_id",
    "subject_runner_identity",
    "source_immutable_object_version",
    "overlay_immutable_object_version",
    "acl_snapshot_sha256",
    "object_versions",
    "retention_mode",
    "issued_at",
    "expires_at",
    "immutable",
    "verified",
    "identity",
}
_USAGE_KEYS = {
    "version",
    "request_id",
    "status",
    "runner_identity",
    "issuer_workload",
    "started_at",
    "completed_at",
    "cost_usd",
    "tokens",
    "identity",
}
_PRIVACY_RECEIPT_KEYS = {
    "version",
    "request_id",
    "status",
    "runner_identity",
    "issuer_workload",
    "completed_at",
    "raw_user_logs_included",
    "pii_included",
    "requires_approved_export",
    "redaction_passed",
    "redaction_report_sha256",
    "identity",
}

_SUCCESS = "succeeded"
_TERMINAL_STATUSES = {_SUCCESS, "failed", "timed_out", "cancelled"}
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_RAW_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_UNSAFE_ARG_RE = re.compile(r"[;&|`$<>\r\n]")
_SECRET_MARKERS = (
    "api_key",
    "apikey",
    "password",
    "bearer ",
    "secret",
    "token=",
    "user_id",
    "session_id",
    "@",
)


@dataclass(frozen=True)
class StableFile:
    path: Path
    payload: bytes
    sha256: str
    size_bytes: int
    stat_signature: tuple[int, ...]


@dataclass(frozen=True)
class AuthorityContext:
    """Deployment-owned trust anchor shared by every authoritative consumer."""

    config_path: Path
    config_hash: str
    coordinator_root: Path
    coordinator_namespace: str
    coordinator_id: str
    policy_path: Path
    policy_identity: str
    policy_sha256: str
    policy_size_bytes: int
    policy_bytes: bytes
    allowed_issuers: tuple[str, ...]
    allowed_verifiers: tuple[str, ...]
    allowed_stores: tuple[str, ...]


class AuthorityContextRotationError(ValidationError):
    """The deployment authority no longer matches an operation snapshot."""


@dataclass(frozen=True)
class ValidatedRunRequest:
    request: Mapping[str, Any]
    canonical_bytes: bytes
    sha256: str
    evidence: Mapping[str, StableFile]
    evidence_json: Mapping[str, Mapping[str, Any]]
    profile: Mapping[str, Any]
    report: Mapping[str, Any]
    policy: Mapping[str, Any]
    acl_snapshot: Mapping[str, Any]
    store_receipt: Mapping[str, Any]
    authority_context: AuthorityContext


@dataclass(frozen=True)
class ValidatedRunResult:
    result: Mapping[str, Any]
    canonical_bytes: bytes
    sha256: str
    outputs: Mapping[str, StableFile | None]
    receipts: Mapping[str, StableFile]
    receipt_json: Mapping[str, Mapping[str, Any]]


def canonical_json_bytes(value: Any) -> bytes:
    """Return the only accepted sealed JSON encoding (no trailing newline)."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError("value is not canonical JSON") from exc


def canonical_value_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sealed_identity(version: str, value: Mapping[str, Any], field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return domain_separated_hash(version, payload)


def seal_run_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    if "request_id" in payload:
        raise ValidationError("run_request payload must not already contain request_id")
    if payload.get("version") != RUN_REQUEST_VERSION:
        raise ValidationError(
            "run_request payload version is not the authoritative v2 schema"
        )
    request = json.loads(canonical_json_bytes(payload))
    request["request_id"] = domain_separated_hash(RUN_REQUEST_VERSION, request)
    return json.loads(canonical_json_bytes(request))


def build_run_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    return seal_run_request(payload)


def seal_run_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    if "result_id" in payload:
        raise ValidationError("run_result payload must not already contain result_id")
    if payload.get("version") != RUN_RESULT_VERSION:
        raise ValidationError(
            "run_result payload version is not the authoritative v2 schema"
        )
    result = json.loads(canonical_json_bytes(payload))
    result["result_id"] = domain_separated_hash(RUN_RESULT_VERSION, result)
    return json.loads(canonical_json_bytes(result))


def build_run_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    return seal_run_result(payload)


def load_json_strict(
    path: str | Path,
    *,
    max_bytes: int = 16 * 1024 * 1024,
    require_canonical: bool = False,
) -> dict[str, Any]:
    held = read_stable_file(path, max_bytes=max_bytes)
    value = _decode_json_strict(held.payload)
    if require_canonical and canonical_json_bytes(value) != held.payload:
        raise ValidationError("sealed JSON artifact is not canonically encoded")
    return value


def load_json_strict_with_hash(
    path: str | Path, *, max_bytes: int = 16 * 1024 * 1024
) -> tuple[dict[str, Any], str]:
    held = read_stable_file(path, max_bytes=max_bytes)
    value = _decode_json_strict(held.payload)
    if canonical_json_bytes(value) != held.payload:
        raise ValidationError("sealed JSON artifact is not canonically encoded")
    return value, held.sha256


def read_stable_file(
    path: str | Path,
    *,
    max_bytes: int = 16 * 1024 * 1024,
    root: str | Path | None = None,
) -> StableFile:
    """Read exact bytes once and bind them to a stable, unique inode."""
    source = Path(path)
    if root is not None:
        resolved_root = _require_run_root(root)
        source = _contained_path(
            resolved_root, str(source), "artifact path", must_exist=True
        )
    else:
        if source.is_symlink():
            raise ValidationError("artifact path must not be a symlink")
        if not source.is_absolute():
            source = source.absolute()
        try:
            source = source.resolve(strict=True)
        except OSError as exc:
            raise ValidationError(
                f"could not resolve stable artifact: {source}"
            ) from exc
    _reject_symlink_components(source)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(source, flags)
    except OSError as exc:
        raise ValidationError(f"could not open stable artifact: {source}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValidationError("artifact must be a regular file")
        if before.st_nlink != 1:
            raise ValidationError("artifact must have exactly one hard link")
        if before.st_size > max_bytes:
            raise ValidationError(f"artifact exceeds {max_bytes} bytes")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise ValidationError("artifact changed during exact-byte read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValidationError("artifact grew during exact-byte read")
        after = os.fstat(descriptor)
        signature = _stat_signature(before)
        if signature != _stat_signature(after):
            raise ValidationError("artifact changed during exact-byte read")
        try:
            path_stat = os.lstat(source)
        except OSError as exc:
            raise ValidationError(
                "artifact path changed during exact-byte read"
            ) from exc
        if signature != _stat_signature(path_stat):
            raise ValidationError("artifact inode was replaced during exact-byte read")
        payload = b"".join(chunks)
        return StableFile(
            path=source.resolve(strict=True),
            payload=payload,
            sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
            stat_signature=signature,
        )
    finally:
        os.close(descriptor)


def verify_stable_file(held: StableFile) -> None:
    """Fail if a held artifact path or inode changed after validation."""
    try:
        current = os.lstat(held.path)
    except OSError as exc:
        raise ValidationError(
            "validated artifact disappeared before publication"
        ) from exc
    if _stat_signature(current) != held.stat_signature:
        raise ValidationError("validated artifact changed before publication")


def resolve_authority_context() -> AuthorityContext:
    """Resolve the sole deployment-owned authority context, or fail closed."""
    configured = os.environ.get(AUTHORITY_CONTEXT_ENV)
    if not configured:
        raise ValidationError(
            f"external authority context is required via {AUTHORITY_CONTEXT_ENV}"
        )
    config_path = Path(configured)
    if not config_path.is_absolute():
        raise ValidationError("external authority context path must be absolute")
    config_file = read_stable_file(config_path, max_bytes=64 * 1024)
    config = _decode_json_strict(config_file.payload)
    if canonical_json_bytes(config) != config_file.payload:
        raise ValidationError("external authority context must be canonical JSON")
    expected_keys = {
        "version",
        "coordinator_root",
        "coordinator_namespace",
        "coordinator_id",
        "trusted_policy",
        "allowed_issuers",
        "allowed_verifiers",
        "allowed_stores",
    }
    _require_exact_keys(config, expected_keys, "external_authority_context")
    if config.get("version") != AUTHORITY_CONTEXT_VERSION:
        raise ValidationError("external authority context version is invalid")
    coordinator_root_value = config.get("coordinator_root")
    if not isinstance(coordinator_root_value, str):
        raise ValidationError("external authority coordinator_root is required")
    coordinator_root = Path(coordinator_root_value)
    if not coordinator_root.is_absolute() or coordinator_root.is_symlink():
        raise ValidationError(
            "external authority coordinator_root must be absolute and real"
        )
    try:
        coordinator_root = coordinator_root.resolve(strict=True)
    except OSError as exc:
        raise ValidationError(
            "external authority coordinator_root is unresolved"
        ) from exc
    if not coordinator_root.is_dir():
        raise ValidationError("external authority coordinator_root must be a directory")
    namespace = config.get("coordinator_namespace")
    if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace):
        raise ValidationError("external authority coordinator_namespace is invalid")
    coordinator_id = _require_text(
        config.get("coordinator_id"), "external_authority_context.coordinator_id"
    )
    trusted = _require_mapping(
        config.get("trusted_policy"), "external_authority_context.trusted_policy"
    )
    _require_exact_keys(
        trusted,
        {"path", "identity", "sha256", "size_bytes"},
        "external_authority_context.trusted_policy",
    )
    policy_path_value = trusted.get("path")
    if (
        not isinstance(policy_path_value, str)
        or not Path(policy_path_value).is_absolute()
    ):
        raise ValidationError("external trusted policy path must be absolute")
    policy_file = read_stable_file(policy_path_value, max_bytes=256 * 1024)
    policy_identity = _require_digest(
        trusted.get("identity"), "external_authority_context.trusted_policy.identity"
    )
    policy_sha256 = _require_digest(
        trusted.get("sha256"), "external_authority_context.trusted_policy.sha256"
    )
    policy_size = _require_int(
        trusted.get("size_bytes"),
        "external_authority_context.trusted_policy.size_bytes",
        minimum=1,
    )
    if (policy_file.sha256, policy_file.size_bytes) != (policy_sha256, policy_size):
        raise ValidationError("external trusted policy exact-byte pin mismatch")
    policy = _decode_json_strict(policy_file.payload)
    if canonical_json_bytes(policy) != policy_file.payload:
        raise ValidationError("external trusted policy must be canonical JSON")
    policy = _validate_authority_policy(policy)
    if (
        policy["identity"] != policy_identity
        or policy["coordinator_id"] != coordinator_id
        or policy["coordinator_namespace"] != namespace
    ):
        raise ValidationError(
            "external trusted policy identity/coordinator pin mismatch"
        )
    allowlists: dict[str, tuple[str, ...]] = {}
    for config_field, policy_field in (
        ("allowed_issuers", "allowed_issuers"),
        ("allowed_verifiers", "allowed_verifiers"),
        ("allowed_stores", "allowed_stores"),
    ):
        values = _require_text_list(
            config.get(config_field), f"external_authority_context.{config_field}"
        )
        if list(values) != list(policy[policy_field]):
            raise ValidationError(f"external authority {config_field} pin mismatch")
        allowlists[config_field] = tuple(values)
    verify_stable_file(config_file)
    verify_stable_file(policy_file)
    return AuthorityContext(
        config_path=config_file.path,
        config_hash=config_file.sha256,
        coordinator_root=coordinator_root,
        coordinator_namespace=namespace,
        coordinator_id=coordinator_id,
        policy_path=policy_file.path,
        policy_identity=policy_identity,
        policy_sha256=policy_sha256,
        policy_size_bytes=policy_size,
        policy_bytes=policy_file.payload,
        allowed_issuers=allowlists["allowed_issuers"],
        allowed_verifiers=allowlists["allowed_verifiers"],
        allowed_stores=allowlists["allowed_stores"],
    )


def verify_authority_context_current(snapshot: AuthorityContext) -> None:
    """Fail closed if the deployment authority changed after ``snapshot``."""
    try:
        current = resolve_authority_context()
    except ValidationError as exc:
        raise AuthorityContextRotationError(
            "external authority context rotated or became invalid during operation"
        ) from exc
    snapshot_identity = (
        snapshot.config_hash,
        snapshot.coordinator_root,
        snapshot.coordinator_namespace,
        snapshot.coordinator_id,
        snapshot.policy_identity,
        snapshot.policy_sha256,
        snapshot.policy_size_bytes,
        snapshot.policy_bytes,
    )
    current_identity = (
        current.config_hash,
        current.coordinator_root,
        current.coordinator_namespace,
        current.coordinator_id,
        current.policy_identity,
        current.policy_sha256,
        current.policy_size_bytes,
        current.policy_bytes,
    )
    if current_identity != snapshot_identity:
        raise AuthorityContextRotationError(
            "external authority context rotated during operation"
        )


def _stat_signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _decode_json_strict(payload: bytes) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("JSON artifact must be UTF-8") from exc

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValidationError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            text,
            object_pairs_hook=no_duplicates,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ValidationError(f"non-finite JSON value {constant}")
            ),
        )
    except json.JSONDecodeError as exc:
        raise ValidationError("artifact is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError("JSON artifact must contain an object")
    return value


def validate_run_request(
    request: Mapping[str, Any],
    *,
    run_root: str | Path,
    seen_request_ids: Collection[str] = (),
) -> None:
    capture_run_request(
        request,
        run_root=run_root,
        seen_request_ids=seen_request_ids,
    )


def capture_run_request(
    request: Mapping[str, Any],
    *,
    run_root: str | Path,
    raw_bytes: bytes | None = None,
    seen_request_ids: Collection[str] = (),
    evidence_snapshots: Mapping[str, Mapping[str, Any]] | None = None,
    authority_context: AuthorityContext | None = None,
) -> ValidatedRunRequest:
    root = _require_run_root(run_root)
    authority_context = authority_context or resolve_authority_context()
    validation_time = datetime.now(timezone.utc)
    _require_exact_keys(request, _REQUEST_KEYS, "run_request")
    if request.get("version") != RUN_REQUEST_VERSION:
        raise ValidationError(
            "run_request.version is not authoritative v2; legacy v1 cannot be upgraded"
        )
    canonical = canonical_json_bytes(request)
    if raw_bytes is not None and raw_bytes != canonical:
        raise ValidationError("sealed run_request JSON is not canonically encoded")
    request_id = _require_digest(request.get("request_id"), "run_request.request_id")
    if request_id != _sealed_identity(RUN_REQUEST_VERSION, request, "request_id"):
        raise ValidationError(
            "run_request.request_id does not match canonical request content"
        )
    if request_id in seen_request_ids:
        raise ValidationError("run_request.request_id has already been consumed")
    if request.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("run_request.scope is invalid")
    created_at = _require_utc_timestamp(
        request.get("created_at"), "run_request.created_at"
    )
    if created_at > validation_time:
        raise ValidationError("run_request.created_at is in the future")

    artifacts = _require_mapping(
        request.get("input_artifacts"), "run_request.input_artifacts"
    )
    _require_exact_keys(
        artifacts, set(INPUT_ARTIFACT_NAMES), "run_request.input_artifacts"
    )
    if evidence_snapshots is not None:
        _require_exact_keys(
            evidence_snapshots,
            set(INPUT_ARTIFACT_NAMES),
            "acceptance_manifest.evidence_snapshots",
        )
    held: dict[str, StableFile] = {}
    for name in INPUT_ARTIFACT_NAMES:
        declared = _artifact_entry(
            artifacts.get(name), f"run_request.input_artifacts.{name}"
        )
        source_entry = (
            _artifact_entry(
                evidence_snapshots[name],
                f"acceptance_manifest.evidence_snapshots.{name}",
            )
            if evidence_snapshots is not None
            else declared
        )
        file = read_stable_file(source_entry["path"], root=root)
        if (
            file.sha256 != declared["sha256"]
            or file.size_bytes != declared["size_bytes"]
        ):
            raise ValidationError(
                f"run_request.input_artifacts.{name} exact-byte binding mismatch"
            )
        if (
            file.sha256 != source_entry["sha256"]
            or file.size_bytes != source_entry["size_bytes"]
        ):
            raise ValidationError(
                f"acceptance evidence snapshot {name} binding mismatch"
            )
        held[name] = file

    json_names = {
        "dataset",
        "execution_control",
        "compatibility_profile",
        "compatibility_report",
        "pristine_source_manifest",
        "overlay_manifest",
        "staging_manifest",
        "runner_identity",
        "custody_evidence",
        "acl_snapshot",
        "immutable_store_receipt",
        "trusted_authority_policy",
    }
    evidence_json: dict[str, Mapping[str, Any]] = {}
    for name in json_names:
        value = _decode_json_strict(held[name].payload)
        if canonical_json_bytes(value) != held[name].payload:
            raise ValidationError(
                f"run_request evidence {name} is not canonically encoded"
            )
        evidence_json[name] = value

    validate_dataset_contract(evidence_json["dataset"])
    validate_execution_control(evidence_json["execution_control"])

    profile = validate_compatibility_profile(
        evidence_json["compatibility_profile"], custody_as_of=created_at
    )
    if profile["evidence_ceiling"]:
        raise ValidationError(
            "compatibility profile remains unresolved and is not acceptance-eligible"
        )
    for field in (
        "overlay_manifest",
        "staging_manifest",
        "runner_identity",
        "custody_evidence",
        "tested_patch",
        "full_dependency_lock",
    ):
        if profile[field] is None:
            raise ValidationError(f"compatibility profile missing required {field}")
    pristine = validate_pristine_source_manifest(
        evidence_json["pristine_source_manifest"]
    )
    overlay = validate_overlay_manifest(evidence_json["overlay_manifest"])
    staging = validate_staging_manifest(evidence_json["staging_manifest"])
    runner = validate_runner_identity(evidence_json["runner_identity"])
    custody = validate_same_domain_custody_evidence(
        evidence_json["custody_evidence"], as_of=validation_time
    )
    component_pairs = {
        "pristine_source_manifest": pristine,
        "overlay_manifest": overlay,
        "staging_manifest": staging,
        "runner_identity": runner,
        "custody_evidence": custody,
    }
    for name, component in component_pairs.items():
        if component != profile[name]:
            raise ValidationError(
                f"compatibility profile {name} differs from exact request evidence"
            )

    report = _validate_compatibility_report(
        evidence_json["compatibility_report"], profile
    )
    policy = _validate_authority_policy(evidence_json["trusted_authority_policy"])
    policy_file = held["trusted_authority_policy"]
    if (
        policy_file.payload != authority_context.policy_bytes
        or policy_file.sha256 != authority_context.policy_sha256
        or policy_file.size_bytes != authority_context.policy_size_bytes
        or policy["identity"] != authority_context.policy_identity
    ):
        raise ValidationError(
            "request trusted policy does not match external exact-byte authority pin"
        )
    acl = _validate_acl_snapshot(evidence_json["acl_snapshot"], as_of=validation_time)
    store = _validate_store_receipt(
        evidence_json["immutable_store_receipt"], as_of=validation_time
    )
    _validate_authority_bindings(
        request=request,
        profile=profile,
        report=report,
        policy=policy,
        acl=acl,
        store=store,
        acl_file=held["acl_snapshot"],
        custody=custody,
    )

    upstream = _require_mapping(request.get("upstream"), "run_request.upstream")
    _require_exact_keys(upstream, _UPSTREAM_KEYS, "run_request.upstream")
    expected_upstream = {
        "profile_id": PROFILE_ID,
        "profile_identity": profile["identity"],
        "compatibility_report_identity": report["identity"],
        "skillopt_revision": APPROVED_PEELED_COMMIT,
        "tree_git_sha1": APPROVED_TREE_GIT_SHA1,
        "archive_sha256": APPROVED_ARCHIVE_SHA256,
        "runner_image_digest": runner["image_digest"],
        "runner_identity": runner["identity"],
        "python_version": runner["python_version"],
        "dependency_lock_hash": held["dependency_lock"].sha256,
        "pristine_source_identity": pristine["identity"],
        "overlay_identity": overlay["identity"],
        "staging_identity": staging["identity"],
        "custody_identity": custody["identity"],
    }
    if dict(upstream) != expected_upstream:
        raise ValidationError(
            "run_request.upstream does not match validated compatibility evidence"
        )
    if (
        _raw_digest(held["dependency_lock"].sha256)
        != profile["full_dependency_lock"]["sha256"]
    ):
        raise ValidationError(
            "full dependency lock bytes do not match compatibility profile"
        )
    if runner["dependency_lock_sha256"] != profile["full_dependency_lock"]["sha256"]:
        raise ValidationError(
            "runner dependency lock does not match compatibility profile"
        )

    execution = _require_mapping(request.get("execution"), "run_request.execution")
    _require_exact_keys(execution, _EXECUTION_REQUEST_KEYS, "run_request.execution")
    _validate_seeds(execution.get("seeds"), "run_request.execution.seeds")
    _validate_model_identifier(
        execution.get("model_identifier"), "run_request.execution.model_identifier"
    )
    train_argv = _validate_argv(
        execution.get("train_argv"), "run_request.execution.train_argv"
    )
    eval_argv = _validate_argv(
        execution.get("eval_argv"), "run_request.execution.eval_argv"
    )
    config = staging["execution_config"]
    expected_execution = {
        "train_argv": TRAIN_ARGV,
        "eval_argv": EVAL_ARGV,
        "train_argv_identity": config["train_argv_identity"],
        "eval_argv_identity": config["eval_argv_identity"],
        "execution_config_identity": staging["execution_config_identity"],
        "rendered_config_hash": held["rendered_config"].sha256,
    }
    for key, expected in expected_execution.items():
        actual = (
            train_argv
            if key == "train_argv"
            else eval_argv
            if key == "eval_argv"
            else execution.get(key)
        )
        if actual != expected:
            raise ValidationError(
                f"run_request.execution.{key} does not match canonical staging evidence"
            )
    if _raw_digest(held["rendered_config"].sha256) != config["rendered_config_sha256"]:
        raise ValidationError("rendered config bytes do not match staging manifest")
    budget = _require_mapping(execution.get("budget"), "run_request.execution.budget")
    _require_exact_keys(budget, _BUDGET_KEYS, "run_request.execution.budget")
    _require_number(
        budget.get("max_cost_usd"),
        "run_request.execution.budget.max_cost_usd",
        minimum=0.0,
        maximum=10_000.0,
    )
    _require_int(
        budget.get("max_tokens"),
        "run_request.execution.budget.max_tokens",
        minimum=1,
        maximum=100_000_000,
    )
    _require_int(
        execution.get("timeout_seconds"),
        "run_request.execution.timeout_seconds",
        minimum=1,
        maximum=86_400,
    )
    _require_int(
        execution.get("max_retries"),
        "run_request.execution.max_retries",
        minimum=0,
        maximum=10,
    )
    _require_int(
        execution.get("max_concurrency"),
        "run_request.execution.max_concurrency",
        minimum=1,
        maximum=16,
    )

    output = _require_mapping(request.get("output"), "run_request.output")
    _require_exact_keys(output, _OUTPUT_REQUEST_KEYS, "run_request.output")
    if (
        output.get("train_root") != TRAIN_OUT_ROOT
        or output.get("eval_root") != EVAL_OUT_ROOT
    ):
        raise ValidationError(
            "run_request output roots do not match the compatibility profile"
        )
    if output.get("best_skill_path") != CANDIDATE_PATH:
        raise ValidationError("run_request candidate path is not canonical")
    if output.get("schema_version") != RUN_RESULT_VERSION:
        raise ValidationError("run_request.output.schema_version is invalid")
    requested_paths = []
    for key in (
        "best_skill_path",
        "evaluation_path",
        "sanitized_summary_path",
        "usage_receipt_path",
        "privacy_receipt_path",
        "result_manifest_path",
    ):
        requested_paths.append(
            _contained_path(
                root, output.get(key), f"run_request.output.{key}", must_exist=False
            )
        )
    if len(set(requested_paths)) != len(requested_paths):
        raise ValidationError("run_request output paths must be distinct")
    if not str(output["best_skill_path"]).startswith(TRAIN_OUT_ROOT + "/"):
        raise ValidationError("candidate path must be inside the train root")
    for key in (
        "evaluation_path",
        "sanitized_summary_path",
        "usage_receipt_path",
        "privacy_receipt_path",
        "result_manifest_path",
    ):
        if not str(output[key]).startswith(EVAL_OUT_ROOT + "/"):
            raise ValidationError(f"{key} must be inside the separate eval root")
    _validate_request_privacy(request.get("privacy"))

    return ValidatedRunRequest(
        request=request,
        canonical_bytes=canonical,
        sha256="sha256:" + hashlib.sha256(canonical).hexdigest(),
        evidence=held,
        evidence_json=evidence_json,
        profile=profile,
        report=report,
        policy=policy,
        acl_snapshot=acl,
        store_receipt=store,
        authority_context=authority_context,
    )


def validate_run_result(
    result: Mapping[str, Any], *, request: Mapping[str, Any], run_root: str | Path
) -> None:
    capture_run_result(result, request=request, run_root=run_root)


def validate_sealed_run_result(
    result: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    run_root: str | Path,
    accepted_outputs: Mapping[str, Any],
    accepted_receipts: Mapping[str, Any] | None = None,
    evidence_snapshots: Mapping[str, Mapping[str, Any]] | None = None,
    request_bytes: bytes | None = None,
    result_bytes: bytes | None = None,
) -> None:
    request_capture = capture_run_request(
        request,
        run_root=run_root,
        raw_bytes=request_bytes,
        evidence_snapshots=evidence_snapshots,
    )
    capture_run_result(
        result,
        request=request,
        run_root=run_root,
        raw_bytes=result_bytes,
        request_capture=request_capture,
        accepted_outputs=accepted_outputs,
        accepted_receipts=accepted_receipts,
    )


def capture_run_result(
    result: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    run_root: str | Path,
    raw_bytes: bytes | None = None,
    request_capture: ValidatedRunRequest | None = None,
    accepted_outputs: Mapping[str, Any] | None = None,
    accepted_receipts: Mapping[str, Any] | None = None,
) -> ValidatedRunResult:
    root = _require_run_root(run_root)
    request_capture = request_capture or capture_run_request(request, run_root=root)
    _require_exact_keys(result, _RESULT_KEYS, "run_result")
    if result.get("version") != RUN_RESULT_VERSION:
        raise ValidationError(
            "run_result.version is not authoritative v2; legacy v1 cannot be upgraded"
        )
    canonical = canonical_json_bytes(result)
    if raw_bytes is not None and raw_bytes != canonical:
        raise ValidationError("sealed run_result JSON is not canonically encoded")
    result_id = _require_digest(result.get("result_id"), "run_result.result_id")
    if result_id != _sealed_identity(RUN_RESULT_VERSION, result, "result_id"):
        raise ValidationError(
            "run_result.result_id does not match canonical result content"
        )
    if result.get("request_id") != request.get("request_id"):
        raise ValidationError("run_result.request_id does not match request")
    if result.get("scope") != request.get("scope"):
        raise ValidationError("run_result.scope does not match request")
    sealed_request = _require_mapping(
        result.get("sealed_request"), "run_result.sealed_request"
    )
    _require_exact_keys(
        sealed_request, _SEALED_REQUEST_KEYS, "run_result.sealed_request"
    )
    expected_request_binding = {
        "request_id": request["request_id"],
        "sha256": request_capture.sha256,
        "size_bytes": len(request_capture.canonical_bytes),
    }
    if dict(sealed_request) != expected_request_binding:
        raise ValidationError("run_result sealed request byte binding mismatch")
    created_at = _require_utc_timestamp(
        request.get("created_at"), "run_request.created_at"
    )
    completed_at = _require_utc_timestamp(
        result.get("completed_at"), "run_result.completed_at"
    )
    if completed_at < created_at:
        raise ValidationError("run_result.completed_at predates the request")
    validation_time = datetime.now(timezone.utc)
    if completed_at > validation_time:
        raise ValidationError("run_result.completed_at is in the future")
    custody = request_capture.profile["custody_evidence"]
    if not (
        _parse_utc(custody["issued_at"])
        <= completed_at
        < _parse_utc(custody["expires_at"])
    ):
        raise ValidationError(
            "run_result completed outside the custody validity window"
        )
    status_value = result.get("status")
    if status_value not in _TERMINAL_STATUSES:
        raise ValidationError("run_result.status is invalid")
    status_text = str(status_value)

    upstream = _require_mapping(result.get("upstream"), "run_result.upstream")
    _require_exact_keys(upstream, _UPSTREAM_KEYS, "run_result.upstream")
    if dict(upstream) != dict(request["upstream"]):
        raise ValidationError("run_result.upstream does not exactly match request")
    execution = _require_mapping(result.get("execution"), "run_result.execution")
    _require_exact_keys(execution, _EXECUTION_RESULT_KEYS, "run_result.execution")
    request_execution = request["execution"]
    for key in (
        "seeds",
        "model_identifier",
        "train_argv_identity",
        "eval_argv_identity",
        "execution_config_identity",
        "rendered_config_hash",
        "timeout_seconds",
        "max_retries",
        "max_concurrency",
    ):
        if execution.get(key) != request_execution.get(key):
            raise ValidationError(f"run_result.execution.{key} does not match request")
    exit_code = _require_int(
        execution.get("exit_code"),
        "run_result.execution.exit_code",
        minimum=-255,
        maximum=255,
    )
    duration = _require_number(
        execution.get("duration_seconds"),
        "run_result.execution.duration_seconds",
        minimum=0.0,
    )
    timed_out = execution.get("timed_out")
    if not isinstance(timed_out, bool):
        raise ValidationError("run_result.execution.timed_out must be boolean")
    retry_count = _require_int(
        execution.get("retry_count"), "run_result.execution.retry_count", minimum=0
    )
    if retry_count > request_execution["max_retries"]:
        raise ValidationError("run_result retry_count exceeds request cap")
    if duration > request_execution["timeout_seconds"] * (retry_count + 1):
        raise ValidationError("run_result duration exceeds timeout and retry envelope")
    if status_text == _SUCCESS and (exit_code != 0 or timed_out):
        raise ValidationError(
            "successful run_result requires exit_code=0 and timed_out=false"
        )
    if status_text == "timed_out" and not timed_out:
        raise ValidationError("timed_out run_result requires timed_out=true")
    if status_text in {_SUCCESS, "failed", "cancelled"} and timed_out:
        raise ValidationError(f"{status_text} run_result cannot set timed_out=true")

    observed = _require_mapping(result.get("observed"), "run_result.observed")
    _require_exact_keys(observed, _OBSERVED_KEYS, "run_result.observed")
    profile = request_capture.profile
    staging = profile["staging_manifest"]
    expected_observed = {
        "profile_identity": profile["identity"],
        "compatibility_report_identity": request_capture.report["identity"],
        "pristine_source_identity": profile["pristine_source_manifest"]["identity"],
        "overlay_identity": profile["overlay_manifest"]["identity"],
        "staging_identity": staging["identity"],
        "runner_identity": profile["runner_identity"]["identity"],
        "custody_identity": profile["custody_evidence"]["identity"],
        "execution_config_identity": staging["execution_config_identity"],
        "rendered_config_hash": request_capture.evidence["rendered_config"].sha256,
        "train_argv": TRAIN_ARGV,
        "eval_argv": EVAL_ARGV,
        "imported_modules": staging["expected_imported_modules"],
        "train_root": TRAIN_OUT_ROOT,
        "eval_root": EVAL_OUT_ROOT,
        "candidate_path": CANDIDATE_PATH,
    }
    if dict(observed) != expected_observed:
        raise ValidationError(
            "run_result observed execution does not match staged compatibility evidence"
        )

    outputs = _require_mapping(result.get("outputs"), "run_result.outputs")
    _require_exact_keys(outputs, _OUTPUT_RESULT_KEYS, "run_result.outputs")
    if accepted_outputs is not None:
        _require_exact_keys(
            accepted_outputs,
            _OUTPUT_RESULT_KEYS,
            "acceptance_manifest.accepted_outputs",
        )
    output_files: dict[str, StableFile | None] = {}
    request_output = request["output"]
    path_fields = {
        "best_skill": "best_skill_path",
        "evaluation": "evaluation_path",
        "sanitized_summary": "sanitized_summary_path",
    }
    for name, path_field in path_fields.items():
        value = outputs.get(name)
        if name == "best_skill" and status_text != _SUCCESS:
            if value is not None:
                raise ValidationError(
                    "non-success run_result must not contain a best_skill output"
                )
            if accepted_outputs is not None and accepted_outputs.get(name) is not None:
                raise ValidationError(
                    "non-success acceptance cannot contain best_skill"
                )
            output_files[name] = None
            continue
        declared = _artifact_entry(value, f"run_result.outputs.{name}")
        if declared["path"] != request_output[path_field]:
            raise ValidationError(
                f"run_result {name} path does not match requested output"
            )
        source = (
            _artifact_entry(
                accepted_outputs[name], f"acceptance_manifest.accepted_outputs.{name}"
            )
            if accepted_outputs is not None
            else declared
        )
        file = read_stable_file(source["path"], root=root)
        if (file.sha256, file.size_bytes) != (
            declared["sha256"],
            declared["size_bytes"],
        ):
            raise ValidationError(
                f"run_result.outputs.{name} exact-byte binding mismatch"
            )
        if (file.sha256, file.size_bytes) != (source["sha256"], source["size_bytes"]):
            raise ValidationError(f"accepted {name} snapshot binding mismatch")
        output_files[name] = file
    best_file = output_files["best_skill"]
    if best_file is not None:
        try:
            policy_text = best_file.payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError("run_result best_skill must be UTF-8") from exc
        _reject_private_text(policy_text, "run_result.outputs.best_skill")
        validate_runtime_policy_text(policy_text)
    for name in ("evaluation", "sanitized_summary"):
        value = _decode_json_strict(output_files[name].payload)  # type: ignore[union-attr]
        _reject_private_value(value, f"run_result.outputs.{name}")

    receipt_values = _require_mapping(result.get("receipts"), "run_result.receipts")
    _require_exact_keys(receipt_values, _RECEIPT_KEYS, "run_result.receipts")
    if accepted_receipts is not None:
        _require_exact_keys(
            accepted_receipts, _RECEIPT_KEYS, "acceptance_manifest.accepted_receipts"
        )
    receipt_files: dict[str, StableFile] = {}
    receipt_json: dict[str, Mapping[str, Any]] = {}
    for name, path_field in (
        ("usage", "usage_receipt_path"),
        ("privacy", "privacy_receipt_path"),
    ):
        declared = _artifact_entry(
            receipt_values.get(name), f"run_result.receipts.{name}"
        )
        if declared["path"] != request_output[path_field]:
            raise ValidationError(
                f"run_result {name} receipt path does not match request"
            )
        source = (
            _artifact_entry(
                accepted_receipts[name], f"acceptance_manifest.accepted_receipts.{name}"
            )
            if accepted_receipts is not None
            else declared
        )
        file = read_stable_file(source["path"], root=root)
        if (file.sha256, file.size_bytes) != (
            declared["sha256"],
            declared["size_bytes"],
        ):
            raise ValidationError(
                f"run_result.receipts.{name} exact-byte binding mismatch"
            )
        if (file.sha256, file.size_bytes) != (source["sha256"], source["size_bytes"]):
            raise ValidationError(f"accepted {name} receipt snapshot binding mismatch")
        parsed = _decode_json_strict(file.payload)
        if canonical_json_bytes(parsed) != file.payload:
            raise ValidationError(f"{name} receipt is not canonically encoded")
        receipt_files[name] = file
        receipt_json[name] = parsed
    usage_receipt = _validate_usage_receipt(
        receipt_json["usage"],
        request_capture,
        status_text,
        result_completed_at=completed_at,
    )
    privacy_receipt = _validate_privacy_receipt(
        receipt_json["privacy"],
        request_capture,
        status_text,
        result_completed_at=completed_at,
    )

    logs = _require_mapping(result.get("logs"), "run_result.logs")
    _require_exact_keys(logs, _LOG_KEYS, "run_result.logs")
    for key in _LOG_KEYS:
        _require_digest(logs.get(key), f"run_result.logs.{key}")
    if logs["redaction_report_sha256"] != privacy_receipt["redaction_report_sha256"]:
        raise ValidationError("redaction report hash does not match privacy receipt")
    usage = _require_mapping(result.get("budget_usage"), "run_result.budget_usage")
    _require_exact_keys(usage, _BUDGET_USAGE_KEYS, "run_result.budget_usage")
    if dict(usage) != {
        "cost_usd": usage_receipt["cost_usd"],
        "tokens": usage_receipt["tokens"],
    }:
        raise ValidationError("claimed budget usage does not match exact usage receipt")
    if (
        usage_receipt["cost_usd"] > request_execution["budget"]["max_cost_usd"]
        or usage_receipt["tokens"] > request_execution["budget"]["max_tokens"]
    ):
        raise ValidationError("run_result exceeds the approved budget")
    privacy = _require_mapping(result.get("privacy"), "run_result.privacy")
    _require_exact_keys(privacy, _PRIVACY_RESULT_KEYS, "run_result.privacy")
    expected_privacy = {key: privacy_receipt[key] for key in _PRIVACY_RESULT_KEYS}
    if dict(privacy) != expected_privacy:
        raise ValidationError(
            "claimed privacy state does not match exact privacy receipt"
        )
    _validate_result_privacy(privacy)

    attestation = _require_mapping(result.get("attestation"), "run_result.attestation")
    _require_exact_keys(attestation, _ATTESTATION_KEYS, "run_result.attestation")
    expected_attestation = {
        "evidence_class": "wave1_2_same_domain",
        "custody_identity": profile["custody_evidence"]["identity"],
        "store_receipt_identity": request_capture.store_receipt["identity"],
        "policy_identity": request_capture.policy["identity"],
    }
    if dict(attestation) != expected_attestation:
        raise ValidationError(
            "run_result attestation does not match trusted same-domain evidence"
        )

    binding = _require_mapping(
        result.get("candidate_binding"), "run_result.candidate_binding"
    )
    _require_exact_keys(
        binding, _CANDIDATE_BINDING_KEYS, "run_result.candidate_binding"
    )
    expected_binding = {
        "best_skill_hash": best_file.sha256 if best_file is not None else None,
        "evaluation_hash": output_files["evaluation"].sha256,  # type: ignore[union-attr]
        "dataset_hash": request_capture.evidence["dataset"].sha256,
        "execution_control_hash": request_capture.evidence["execution_control"].sha256,
        "profile_identity": profile["identity"],
        "overlay_identity": profile["overlay_manifest"]["identity"],
        "staging_identity": profile["staging_manifest"]["identity"],
        "runner_identity": profile["runner_identity"]["identity"],
        "custody_identity": profile["custody_evidence"]["identity"],
    }
    if dict(binding) != expected_binding:
        raise ValidationError("run_result candidate/output binding mismatch")

    return ValidatedRunResult(
        result=result,
        canonical_bytes=canonical,
        sha256="sha256:" + hashlib.sha256(canonical).hexdigest(),
        outputs=output_files,
        receipts=receipt_files,
        receipt_json=receipt_json,
    )


def _validate_compatibility_report(
    value: Mapping[str, Any], profile: Mapping[str, Any]
) -> Mapping[str, Any]:
    _require_exact_keys(value, _COMPATIBILITY_REPORT_KEYS, "compatibility_report")
    if value.get("version") != COMPATIBILITY_REPORT_VERSION:
        raise ValidationError(
            "diagnostic or unsupported compatibility report is not authorized"
        )
    if value.get("identity") != _sealed_identity(
        COMPATIBILITY_REPORT_VERSION, value, "identity"
    ):
        raise ValidationError("compatibility report identity mismatch")
    fixed = {
        "profile_id": PROFILE_ID,
        "status": "passed",
        "evidence_class": "wave1_2_compatibility",
        "authorization_status": "authorized_for_sealed_import",
        "authenticity_status": "same_domain_verified",
        "seal_kind": "acl_immutable_store",
        "trusted": True,
        "provider_count": 0,
        "network_count": 0,
        "subprocess_count": 0,
    }
    for key, expected in fixed.items():
        if value.get(key) != expected:
            raise ValidationError(
                f"compatibility report {key} is not acceptance-eligible"
            )
    staging = profile["staging_manifest"]
    expected = {
        "pristine_source_identity": profile["pristine_source_manifest"]["identity"],
        "overlay_identity": profile["overlay_manifest"]["identity"],
        "staging_identity": staging["identity"],
        "runner_identity": profile["runner_identity"]["identity"],
        "custody_identity": profile["custody_evidence"]["identity"],
        "execution_config_identity": staging["execution_config_identity"],
        "train_argv_identity": staging["execution_config"]["train_argv_identity"],
        "eval_argv_identity": staging["execution_config"]["eval_argv_identity"],
        "imported_modules": staging["expected_imported_modules"],
        "outputs": profile["outputs"],
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise ValidationError(f"compatibility report {key} cross-binding mismatch")
    tested = profile["tested_patch"]
    if tested["report_identity"] != value["identity"]:
        raise ValidationError(
            "compatibility report is not the profile tested_patch report"
        )
    if tested["status"] != "passed" or tested["verified"] is not True:
        raise ValidationError(
            "compatibility tested_patch is not verified passed evidence"
        )
    return value


def _validate_authority_policy(value: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_exact_keys(value, _POLICY_KEYS, "trusted_authority_policy")
    if value.get("version") != AUTHORITY_POLICY_VERSION:
        raise ValidationError("trusted authority policy version is invalid")
    if value.get("identity") != _sealed_identity(
        AUTHORITY_POLICY_VERSION, value, "identity"
    ):
        raise ValidationError("trusted authority policy identity mismatch")
    _require_text(value.get("policy_name"), "trusted_authority_policy.policy_name")
    _require_text(
        value.get("coordinator_id"), "trusted_authority_policy.coordinator_id"
    )
    namespace = value.get("coordinator_namespace")
    if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace):
        raise ValidationError(
            "trusted authority policy coordinator_namespace is invalid"
        )
    for field in (
        "allowed_profile_identities",
        "allowed_report_identities",
        "allowed_runner_identities",
        "allowed_custody_identities",
    ):
        _require_digest_list(value.get(field), f"trusted_authority_policy.{field}")
    for field in ("allowed_issuers", "allowed_verifiers", "allowed_stores"):
        _require_text_list(value.get(field), f"trusted_authority_policy.{field}")
    roots = value.get("wave3_trust_roots")
    if roots != []:
        raise ValidationError(
            "Wave3 cryptographic trust roots are unsupported without signature verification"
        )
    return value


def _validate_acl_snapshot(
    value: Mapping[str, Any], *, as_of: datetime
) -> Mapping[str, Any]:
    _require_exact_keys(value, _ACL_KEYS, "acl_snapshot")
    if value.get("version") != ACL_SNAPSHOT_VERSION:
        raise ValidationError("ACL snapshot version is invalid")
    if value.get("identity") != _sealed_identity(
        ACL_SNAPSHOT_VERSION, value, "identity"
    ):
        raise ValidationError("ACL snapshot identity mismatch")
    _validate_time_window(value, "acl_snapshot", as_of=as_of)
    if value.get("immutable") is not True:
        raise ValidationError("ACL snapshot must be immutable")
    principals = _require_text_list(value.get("principals"), "acl_snapshot.principals")
    if len(principals) < 2:
        raise ValidationError(
            "ACL snapshot requires distinct coordinator and verifier principals"
        )
    object_versions = _require_mapping(
        value.get("object_versions"), "acl_snapshot.object_versions"
    )
    _require_exact_keys(
        object_versions, {"source", "overlay"}, "acl_snapshot.object_versions"
    )
    return value


def _validate_store_receipt(
    value: Mapping[str, Any], *, as_of: datetime
) -> Mapping[str, Any]:
    _require_exact_keys(value, _STORE_KEYS, "immutable_store_receipt")
    if value.get("version") != STORE_RECEIPT_VERSION:
        raise ValidationError("immutable store receipt version is invalid")
    if value.get("identity") != _sealed_identity(
        STORE_RECEIPT_VERSION, value, "identity"
    ):
        raise ValidationError("immutable store receipt identity mismatch")
    _validate_time_window(value, "immutable_store_receipt", as_of=as_of)
    if value.get("immutable") is not True or value.get("verified") is not True:
        raise ValidationError("immutable store receipt must be verified and immutable")
    if value.get("retention_mode") != "governance-compliance":
        raise ValidationError("immutable store receipt retention mode is invalid")
    object_versions = _require_mapping(
        value.get("object_versions"), "immutable_store_receipt.object_versions"
    )
    _require_exact_keys(
        object_versions,
        {"source", "overlay", "staging", "runner", "custody"},
        "immutable_store_receipt.object_versions",
    )
    return value


def _validate_authority_bindings(
    *,
    request: Mapping[str, Any],
    profile: Mapping[str, Any],
    report: Mapping[str, Any],
    policy: Mapping[str, Any],
    acl: Mapping[str, Any],
    store: Mapping[str, Any],
    acl_file: StableFile,
    custody: Mapping[str, Any],
) -> None:
    authority = _require_mapping(request.get("authority"), "run_request.authority")
    _require_exact_keys(authority, _AUTHORITY_KEYS, "run_request.authority")
    expected = {
        "evidence_class": "wave1_2_same_domain",
        "policy_identity": policy["identity"],
        "coordinator_id": policy["coordinator_id"],
        "coordinator_namespace": policy["coordinator_namespace"],
        "wave3_crypto_required": False,
    }
    if dict(authority) != expected:
        raise ValidationError(
            "run_request authority does not match explicit trusted policy"
        )
    allowlist_pairs = (
        (profile["identity"], policy["allowed_profile_identities"], "profile"),
        (report["identity"], policy["allowed_report_identities"], "report"),
        (
            profile["runner_identity"]["identity"],
            policy["allowed_runner_identities"],
            "runner",
        ),
        (custody["identity"], policy["allowed_custody_identities"], "custody"),
    )
    for identity, allowed, label in allowlist_pairs:
        if identity not in allowed:
            raise ValidationError(
                f"{label} identity is not in the external trusted policy"
            )
    issuer = custody["issuer_workload"]
    verifier = custody["verifier_id"]
    store_id = store["store_id"]
    if (
        issuer not in policy["allowed_issuers"]
        or store["issuer_workload"] not in policy["allowed_issuers"]
    ):
        raise ValidationError("custody/store issuer is not trusted")
    if (
        verifier not in policy["allowed_verifiers"]
        or store["verifier_id"] not in policy["allowed_verifiers"]
    ):
        raise ValidationError("custody/store verifier is not trusted")
    if store_id not in policy["allowed_stores"]:
        raise ValidationError("immutable store is not trusted")
    if issuer == verifier or store["issuer_workload"] == store["verifier_id"]:
        raise ValidationError("same-domain evidence cannot be self-issued")
    if (
        acl["store_id"] != store_id
        or acl["issuer_workload"] not in policy["allowed_issuers"]
    ):
        raise ValidationError("ACL snapshot store/issuer mismatch")
    if acl["verifier_id"] not in policy["allowed_verifiers"]:
        raise ValidationError("ACL snapshot verifier is not trusted")
    if acl["coordinator_id"] != policy["coordinator_id"]:
        raise ValidationError("ACL snapshot coordinator mismatch")
    expected_acl_principals = {policy["coordinator_id"], acl["verifier_id"]}
    if set(acl["principals"]) != expected_acl_principals or len(
        acl["principals"]
    ) != len(expected_acl_principals):
        raise ValidationError(
            "ACL snapshot principals must be exactly the policy coordinator and ACL verifier"
        )
    if not (
        acl["verifier_id"] == custody["verifier_id"] == store["verifier_id"]
    ):
        raise ValidationError("ACL/custody/store verifier cross-binding mismatch")
    if _raw_digest(acl_file.sha256) != custody["acl_snapshot_sha256"]:
        raise ValidationError(
            "custody ACL hash does not match actual ACL snapshot bytes"
        )
    if store["acl_snapshot_sha256"] != _raw_digest(acl_file.sha256):
        raise ValidationError("immutable store receipt ACL binding mismatch")
    runner = profile["runner_identity"]
    expected_store = {
        "subject_runner_identity": runner["identity"],
        "source_immutable_object_version": SOURCE_IMMUTABLE_OBJECT_VERSION,
        "overlay_immutable_object_version": profile["overlay_manifest"][
            "immutable_object_version"
        ],
        "object_versions": {
            "source": profile["pristine_source_manifest"]["identity"],
            "overlay": profile["overlay_manifest"]["identity"],
            "staging": profile["staging_manifest"]["identity"],
            "runner": runner["identity"],
            "custody": custody["identity"],
        },
    }
    for key, expected_value in expected_store.items():
        if store.get(key) != expected_value:
            raise ValidationError(
                f"immutable store receipt {key} cross-binding mismatch"
            )
    if acl["object_versions"] != {
        "source": SOURCE_IMMUTABLE_OBJECT_VERSION,
        "overlay": profile["overlay_manifest"]["immutable_object_version"],
    }:
        raise ValidationError("ACL snapshot object versions are stale or mismatched")


def _validate_usage_receipt(
    value: Mapping[str, Any],
    request: ValidatedRunRequest,
    status_value: str,
    *,
    result_completed_at: datetime,
) -> Mapping[str, Any]:
    _require_exact_keys(value, _USAGE_KEYS, "usage_receipt")
    if value.get("version") != USAGE_RECEIPT_VERSION:
        raise ValidationError("usage receipt version is invalid")
    if value.get("identity") != _sealed_identity(
        USAGE_RECEIPT_VERSION, value, "identity"
    ):
        raise ValidationError("usage receipt identity mismatch")
    if (
        value.get("request_id") != request.request["request_id"]
        or value.get("status") != status_value
    ):
        raise ValidationError("usage receipt request/status binding mismatch")
    if value.get("runner_identity") != request.profile["runner_identity"]["identity"]:
        raise ValidationError("usage receipt runner binding mismatch")
    if value.get("issuer_workload") not in request.policy["allowed_issuers"]:
        raise ValidationError("usage receipt issuer is not trusted")
    started = _require_utc_timestamp(
        value.get("started_at"), "usage_receipt.started_at"
    )
    completed = _require_utc_timestamp(
        value.get("completed_at"), "usage_receipt.completed_at"
    )
    request_created_at = _require_utc_timestamp(
        request.request.get("created_at"), "run_request.created_at"
    )
    if not (request_created_at <= started <= completed <= result_completed_at):
        raise ValidationError(
            "usage receipt interval must be within the request/result interval"
        )
    _require_number(value.get("cost_usd"), "usage_receipt.cost_usd", minimum=0.0)
    _require_int(value.get("tokens"), "usage_receipt.tokens", minimum=0)
    return value


def _validate_privacy_receipt(
    value: Mapping[str, Any],
    request: ValidatedRunRequest,
    status_value: str,
    *,
    result_completed_at: datetime,
) -> Mapping[str, Any]:
    _require_exact_keys(value, _PRIVACY_RECEIPT_KEYS, "privacy_receipt")
    if value.get("version") != PRIVACY_RECEIPT_VERSION:
        raise ValidationError("privacy receipt version is invalid")
    if value.get("identity") != _sealed_identity(
        PRIVACY_RECEIPT_VERSION, value, "identity"
    ):
        raise ValidationError("privacy receipt identity mismatch")
    if (
        value.get("request_id") != request.request["request_id"]
        or value.get("status") != status_value
    ):
        raise ValidationError("privacy receipt request/status binding mismatch")
    if value.get("runner_identity") != request.profile["runner_identity"]["identity"]:
        raise ValidationError("privacy receipt runner binding mismatch")
    if value.get("issuer_workload") not in request.policy["allowed_issuers"]:
        raise ValidationError("privacy receipt issuer is not trusted")
    completed = _require_utc_timestamp(
        value.get("completed_at"), "privacy_receipt.completed_at"
    )
    request_created_at = _require_utc_timestamp(
        request.request.get("created_at"), "run_request.created_at"
    )
    if not (request_created_at <= completed <= result_completed_at):
        raise ValidationError(
            "privacy receipt completion must be within the request/result interval"
        )
    _require_digest(
        value.get("redaction_report_sha256"), "privacy_receipt.redaction_report_sha256"
    )
    _validate_result_privacy(value)
    return value


def _validate_time_window(
    value: Mapping[str, Any], field: str, *, as_of: datetime
) -> None:
    issued = _require_utc_timestamp(value.get("issued_at"), f"{field}.issued_at")
    expires = _require_utc_timestamp(value.get("expires_at"), f"{field}.expires_at")
    if issued >= expires:
        raise ValidationError(f"{field}.issued_at must precede expires_at")
    if not (issued <= as_of < expires):
        raise ValidationError(f"{field} is expired or not yet valid")


def _validate_request_privacy(value: Any) -> None:
    privacy = _require_mapping(value, "run_request.privacy")
    _require_exact_keys(privacy, _PRIVACY_REQUEST_KEYS, "run_request.privacy")
    expected = {
        "raw_user_logs_included": False,
        "pii_included": False,
        "requires_approved_export": True,
    }
    if dict(privacy) != expected:
        raise ValidationError("run_request privacy boundary is invalid")


def _validate_result_privacy(value: Any) -> None:
    privacy = _require_mapping(value, "run_result.privacy")
    for key in _PRIVACY_RESULT_KEYS:
        if key not in privacy:
            raise ValidationError("run_result privacy/redaction boundary is incomplete")
    expected = {
        "raw_user_logs_included": False,
        "pii_included": False,
        "requires_approved_export": True,
        "redaction_passed": True,
    }
    for key, expected_value in expected.items():
        if privacy.get(key) != expected_value:
            raise ValidationError("run_result privacy/redaction boundary is invalid")


def _artifact_entry(value: Any, field: str) -> dict[str, Any]:
    entry = _require_mapping(value, field)
    _require_exact_keys(entry, _ARTIFACT_KEYS, field)
    path = _require_relative_path(entry.get("path"), f"{field}.path")
    digest = _require_digest(entry.get("sha256"), f"{field}.sha256")
    size = _require_int(
        entry.get("size_bytes"),
        f"{field}.size_bytes",
        minimum=0,
        maximum=16 * 1024 * 1024,
    )
    return {"path": path, "sha256": digest, "size_bytes": size}


def _validate_seeds(value: Any, field: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{field} must be a non-empty list")
    seeds = tuple(
        _require_int(item, f"{field}[]", minimum=0, maximum=2**31 - 1) for item in value
    )
    if len(set(seeds)) != len(seeds):
        raise ValidationError(f"{field} must not contain duplicates")
    return seeds


def _validate_model_identifier(value: Any, field: str) -> str:
    model = _require_text(value, field)
    if model.lower().endswith(("/latest", ":latest")) or model.lower() == "latest":
        raise ValidationError(f"{field} must be immutable, not latest")
    return model


def _validate_argv(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{field} must be a non-empty argv list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ValidationError(f"{field}[{index}] must be text")
        if _UNSAFE_ARG_RE.search(item):
            raise ValidationError(f"{field}[{index}] contains unsafe shell syntax")
        result.append(item)
    return result


def _require_run_root(value: str | Path) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise ValidationError("run_root must be absolute")
    if root.is_symlink():
        raise ValidationError("run_root must not be a symlink")
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise ValidationError("run_root must exist") from exc
    if not resolved.is_dir():
        raise ValidationError("run_root must be an existing directory")
    return resolved


def _contained_path(root: Path, value: Any, field: str, *, must_exist: bool) -> Path:
    relative = _require_relative_path(value, field)
    candidate = root.joinpath(*relative.split("/"))
    _reject_symlink_components(candidate, stop=root)
    try:
        resolved = candidate.resolve(strict=must_exist)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise ValidationError(f"{field} escapes run_root or is missing") from exc
    if must_exist and not resolved.is_file():
        raise ValidationError(f"{field} must reference a regular file")
    return resolved


def _require_relative_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValidationError(
            f"{field} must be a normalized POSIX relative path inside run_root"
        )
    raw = Path(value)
    if (
        raw.is_absolute()
        or any(part in {"", ".", ".."} for part in raw.parts)
        or raw.as_posix() != value
    ):
        raise ValidationError(
            f"{field} must be a normalized POSIX relative path inside run_root"
        )
    return value


def _reject_symlink_components(path: Path, *, stop: Path | None = None) -> None:
    current = path
    minimum = stop.resolve() if stop is not None else Path(path.anchor)
    while True:
        if current.exists() or current.is_symlink():
            if current.is_symlink():
                raise ValidationError("artifact path must not traverse a symlink")
        if current == minimum or current.parent == current:
            break
        current = current.parent


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], field: str
) -> None:
    actual = set(value)
    if actual != expected:
        raise ValidationError(
            f"{field} keys mismatch: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{field} must be an object")
    return value


def _require_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValidationError(f"{field} must be a lowercase sha256 digest")
    return value


def _raw_digest(value: str) -> str:
    digest = _require_digest(value, "digest")
    return digest.removeprefix("sha256:")


def _require_digest_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{field} must be a non-empty list")
    result = [_require_digest(item, f"{field}[]") for item in value]
    if result != sorted(set(result)):
        raise ValidationError(f"{field} must be sorted and unique")
    return result


def _require_text_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{field} must be a non-empty list")
    result = [_require_text(item, f"{field}[]") for item in value]
    if result != sorted(set(result)):
        raise ValidationError(f"{field} must be sorted and unique")
    return result


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string")
    lowered = value.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        raise ValidationError(f"{field} contains a secret, PII, or raw-log marker")
    return value


def _reject_private_text(value: str, field: str) -> None:
    lowered = value.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        raise ValidationError(f"{field} contains a secret, PII, or raw-log marker")


def _reject_private_value(value: Any, field: str) -> None:
    if isinstance(value, str):
        _reject_private_text(value, field)
    elif isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_private_text(str(key), f"{field}.key")
            _reject_private_value(nested, f"{field}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, nested in enumerate(value):
            _reject_private_value(nested, f"{field}[{index}]")


def _require_int(
    value: Any, field: str, *, minimum: int, maximum: int | None = None
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{field} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValidationError(f"{field} is outside the allowed range")
    return value


def _require_number(
    value: Any, field: str, *, minimum: float, maximum: float | None = None
) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ValidationError(f"{field} must be a finite number")
    number = float(value)
    if number < minimum or (maximum is not None and number > maximum):
        raise ValidationError(f"{field} is outside the allowed range")
    return number


def _require_utc_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValidationError(f"{field} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValidationError(f"{field} must be a UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValidationError(f"{field} must be a UTC timestamp")
    return parsed


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")
