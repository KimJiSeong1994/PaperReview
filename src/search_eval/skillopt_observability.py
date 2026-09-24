"""Read-only, default-off observability for validated SkillOpt evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .orchestrator import (
    ORCHESTRATOR_HEARTBEAT_VERSION,
    ORCHESTRATOR_JOURNAL_VERSION,
    ORCHESTRATOR_STATUS_VERSION,
)
from .skillopt_contract import ValidationError
from .skillopt_run_contract import (
    AUTHORITY_CONTEXT_ENV,
    ValidatedRunRequest,
    ValidatedRunResult,
    canonical_json_bytes,
    canonical_value_hash,
    capture_run_request,
    capture_run_result,
    read_stable_file,
)

OBSERVATION_VERSION = "skillopt-compatibility-observation-v1"
ATTEMPT_SUMMARY_VERSION = "skillopt-attempt-observability-v1"
ALERT_VERSION = "skillopt-observability-alert-v1"
OPERATOR_ENVELOPE_VERSION = "skillopt-operator-envelope-v1"
DEFAULT_FRESHNESS_SECONDS = 900
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}$")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_QUARANTINE_REFERENCE = re.compile(r"quarantine:sha256:[0-9a-f]{64}$")
_SENSITIVE_FIELDS = {
    "authorization",
    "cookie",
    "credential",
    "email",
    "password",
    "pii",
    "policy",
    "prompt",
    "query",
    "raw",
    "secret",
    "session",
    "sessionid",
    "token",
    "user",
}
_SENSITIVE_VALUE = re.compile(
    r"(?i)(?:password\s*[=:]\s*\S+|authorization\s*[=:]\s*(?:basic|bearer)\s+\S+|(?:^|[;\s])(?:cookie|sessionid)\s*[=:]\s*\S+|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|aws[_-]?secret[_-]?access[_-]?key\s*[=:]\s*\S+|(?:gh[opusr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})|(?:api[_-]?key|secret|credential|token)\s*[=:]\s*\S+|https?://[^\s?#]+(?:\?[^\s#]*(?:password|api[_-]?key|secret|token|sessionid)=)|\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b)"
)
_CAPABILITY_TOKEN = object()
_FUTURE_SKEW = timedelta(seconds=5)
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
_EVENT_KEYS = {
    "sequence",
    "old_state",
    "state",
    "at",
    "reason",
    "request_sha256",
    "result_sha256",
}
_ACCEPTANCE_KEYS = {"acceptance_manifest_path", "acceptance_manifest_hash"}
_TERMINAL = {
    "dry_run_complete",
    "candidate_ready",
    "failed",
    "timed_out",
    "cancelled",
    "quarantined",
}
_ALERT_POLICY = {
    "stale_heartbeat": ("warning", 30, 7),
    "repeated_compatibility_failure": ("warning", 30, 7),
    "revision_drift": ("critical", 90, 30),
    "budget_breach": ("critical", 90, 30),
    "privacy_finding": ("critical", 30, 7),
    "release_holdout_leak": ("critical", 90, 30),
    "authorization_misuse": ("critical", 90, 30),
}


class EvidenceClass(str, Enum):
    FIXTURE = "fixture"
    COMPATIBILITY = "compatibility"
    MEASURED_RESEARCH = "measured_research"
    SHADOW = "shadow"
    PRODUCTION = "production"


class AlertCode(str, Enum):
    AUTHORIZATION_MISUSE = "authorization_misuse"
    BUDGET_BREACH = "budget_breach"
    PRIVACY_FINDING = "privacy_finding"
    RELEASE_HOLDOUT_LEAK = "release_holdout_leak"
    REPEATED_COMPATIBILITY_FAILURE = "repeated_compatibility_failure"
    REVISION_DRIFT = "revision_drift"
    STALE_HEARTBEAT = "stale_heartbeat"


@dataclass(frozen=True)
class _SourceContext:
    request_path: Path
    result_path: Path
    run_root: Path
    authority_path: Path
    source_hashes: tuple[tuple[str, str], ...]


@dataclass(frozen=True, init=False)
class _ValidatedMapping(Mapping[str, Any]):
    _payload: bytes
    _source: _SourceContext | None = field(repr=False, compare=False)

    def __init__(
        self,
        value: Mapping[str, Any],
        source: _SourceContext | None,
        token: object,
    ) -> None:
        if token is not _CAPABILITY_TOKEN:
            raise TypeError("validated observability capabilities are privately minted")
        object.__setattr__(self, "_payload", canonical_json_bytes(value))
        object.__setattr__(self, "_source", source)

    def __getitem__(self, key: str) -> Any:
        return self.persisted_record()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.persisted_record())

    def __len__(self) -> int:
        return len(self.persisted_record())

    def persisted_record(self) -> dict[str, Any]:
        value = json.loads(self._payload)
        if not isinstance(value, dict):  # pragma: no cover - private invariant
            raise AssertionError("validated capability payload is not a mapping")
        return value


@dataclass(frozen=True, init=False)
class ValidatedCompatibilityObservation(_ValidatedMapping):
    pass


@dataclass(frozen=True, init=False)
class ValidatedAttemptSummary(_ValidatedMapping):
    pass


@dataclass(frozen=True, init=False)
class ValidatedAlert(_ValidatedMapping):
    pass


@dataclass(frozen=True, init=False)
class ValidatedOperatorEnvelope(_ValidatedMapping):
    pass


def _mint(
    capability: type[_ValidatedMapping],
    value: Mapping[str, Any],
    source: _SourceContext | None,
) -> Any:
    return capability(value, source, _CAPABILITY_TOKEN)


def reject_sensitive_observability_value(value: Any, *, _path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            segments = re.split(r"[_-]+", key.lower()) if isinstance(key, str) else []
            safe_aggregate = isinstance(key, str) and key.lower().endswith(
                ("_hash", "_count")
            )
            if not isinstance(key, str) or (
                not safe_aggregate
                and any(part in _SENSITIVE_FIELDS for part in segments)
            ):
                raise ValidationError(
                    f"sensitive observability field rejected at {_path}"
                )
            reject_sensitive_observability_value(item, _path=f"{_path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            reject_sensitive_observability_value(item, _path=f"{_path}[{index}]")
    elif isinstance(value, str) and _SENSITIVE_VALUE.search(value):
        raise ValidationError(f"secret-bearing observability value rejected at {_path}")


def validate_evidence_gate(
    *,
    requested: EvidenceClass | str,
    available: EvidenceClass | str = EvidenceClass.COMPATIBILITY,
    compatibility_passed: bool = True,
    privacy_passed: bool = False,
) -> EvidenceClass:
    del privacy_passed
    try:
        requested_class, available_class = (
            EvidenceClass(requested),
            EvidenceClass(available),
        )
    except ValueError as exc:
        raise ValidationError("unknown evidence class") from exc
    if requested_class is EvidenceClass.PRODUCTION:
        raise ValidationError("production evidence is unsupported")
    if requested_class is not EvidenceClass.COMPATIBILITY:
        raise ValidationError(
            "measured, shadow, and production gate requests are unsupported"
        )
    if available_class is not EvidenceClass.COMPATIBILITY:
        raise ValidationError(
            "caller evidence labels cannot confer compatibility capability"
        )
    if compatibility_passed is not True:
        raise ValidationError("passing compatibility evidence is required")
    return EvidenceClass.COMPATIBILITY


def build_attempt_summary(
    *,
    attempt_id: str,
    request_path: str | Path,
    result_path: str | Path,
    run_root: str | Path,
    freshness_threshold_seconds: int = DEFAULT_FRESHNESS_SECONDS,
) -> ValidatedAttemptSummary:
    return _build_attempt_summary_from_sources(
        attempt_id=attempt_id,
        request_path=request_path,
        result_path=result_path,
        run_root=run_root,
        freshness_threshold_seconds=freshness_threshold_seconds,
        now_fn=_utc_now,
    )


def _build_attempt_summary_from_sources(
    *,
    attempt_id: str,
    request_path: str | Path,
    result_path: str | Path,
    run_root: str | Path,
    freshness_threshold_seconds: int,
    now_fn: Callable[[], datetime],
    observed_at: str | None = None,
    expected_source: _SourceContext | None = None,
) -> ValidatedAttemptSummary:
    trusted_now = _trusted_now(now_fn)
    source, request, result, status, journal, heartbeat = _capture_sources(
        request_path=request_path,
        result_path=result_path,
        run_root=run_root,
        expected=expected_source,
    )
    observation_time = (
        _format_utc(trusted_now)
        if observed_at is None
        else _validated_persisted_observation_time(observed_at, trusted_now)
    )
    observation = _build_observation(
        attempt_id,
        request,
        result,
        status,
        journal,
        heartbeat,
        observation_time,
        trusted_now,
        freshness_threshold_seconds,
    )
    value = {"version": ATTEMPT_SUMMARY_VERSION, **observation.persisted_record()}
    value.pop("version")
    value["version"] = ATTEMPT_SUMMARY_VERSION
    value["counts"] = {
        "provider": 0,
        "network": 0,
        "subprocess": 0,
        "runtime_traffic": 0,
    }
    value["safety"] = {
        "sensitive_content_absent": True,
        "personal_data_absent": True,
        "redaction_passed": True,
        "enablement_status": "not_authorized",
        "runtime_default_off": True,
        "promotion_authority": False,
    }
    value["summary_hash"] = canonical_value_hash(value)
    validated = _validate_attempt_summary(value, trusted_now)
    return _mint(ValidatedAttemptSummary, validated, source)


def _capture_sources(
    *,
    request_path: str | Path,
    result_path: str | Path,
    run_root: str | Path,
    expected: _SourceContext | None = None,
) -> tuple[
    _SourceContext,
    ValidatedRunRequest,
    ValidatedRunResult,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    root = Path(run_root).resolve(strict=True)
    if not root.is_dir():
        raise ValidationError("run_root must be a directory")
    configured = os.environ.get(AUTHORITY_CONTEXT_ENV)
    if not configured or not Path(configured).is_absolute():
        raise ValidationError("fixed external authority context is required")
    authority = read_stable_file(configured, max_bytes=64 * 1024)
    request_file = read_stable_file(_source_path(root, request_path))
    result_file = read_stable_file(_source_path(root, result_path))
    request_value = _decode_canonical_source(request_file.payload, "run request")
    result_value = _decode_canonical_source(result_file.payload, "run result")
    request = capture_run_request(
        request_value, run_root=root, raw_bytes=request_file.payload
    )
    result = capture_run_result(
        result_value,
        request=request_value,
        run_root=root,
        raw_bytes=result_file.payload,
        request_capture=request,
    )
    authority_after = read_stable_file(configured, max_bytes=64 * 1024)
    if (
        os.environ.get(AUTHORITY_CONTEXT_ENV) != configured
        or authority_after.path != authority.path
        or authority_after.sha256 != authority.sha256
    ):
        raise ValidationError("external authority context changed during capture")
    lifecycle: dict[str, dict[str, Any]] = {}
    hashes = {
        "authority": authority.sha256,
        "request": request_file.sha256,
        "result": result_file.sha256,
    }
    for label, name in (
        ("status", "status.json"),
        ("journal", "stage_journal.json"),
        ("heartbeat", "heartbeat.json"),
    ):
        held = read_stable_file(root / name)
        lifecycle[label] = _decode_canonical_source(held.payload, label)
        hashes[label] = held.sha256
    source = _SourceContext(
        request_path=request_file.path,
        result_path=result_file.path,
        run_root=root,
        authority_path=authority.path,
        source_hashes=tuple(sorted(hashes.items())),
    )
    if expected is not None and source != expected:
        raise ValidationError("authoritative observability sources changed")
    return (
        source,
        request,
        result,
        lifecycle["status"],
        lifecycle["journal"],
        lifecycle["heartbeat"],
    )


def _source_path(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    candidate = candidate if candidate.is_absolute() else root / candidate
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValidationError("observability source must be inside run_root") from exc
    return resolved


def _build_observation(
    attempt_id: str,
    request: ValidatedRunRequest,
    result: ValidatedRunResult,
    status: Mapping[str, Any],
    journal: Mapping[str, Any],
    heartbeat: Mapping[str, Any],
    observed_at: str,
    trusted_now: datetime,
    threshold: int,
) -> ValidatedCompatibilityObservation:
    _id(attempt_id, "attempt_id")
    observed = _utc(observed_at, "observed_at")
    if type(threshold) is not int or not 1 <= threshold <= 86400:
        raise ValidationError("freshness threshold must be 1..86400 seconds")
    if result.result.get("request_id") != request.request.get("request_id"):
        raise ValidationError("validated request/result identity mismatch")
    report = request.report
    if report.get("status") != "passed" or any(
        report.get(k) != 0
        for k in ("provider_count", "network_count", "subprocess_count")
    ):
        raise ValidationError(
            "only passing credential-free compatibility evidence is observable"
        )
    lifecycle, fresh = _lifecycle(
        status, journal, heartbeat, request, result, observed, trusted_now, threshold
    )
    revision = request.request.get("upstream", {}).get("skillopt_revision")
    _id(revision, "revision")
    return _mint(
        ValidatedCompatibilityObservation,
        {
            "version": OBSERVATION_VERSION,
            "attempt_id": attempt_id,
            "evidence_class": "compatibility",
            "measurement_mode": "diagnostic_exact_source",
            "observed_at": observed_at,
            "request_ref": {
                "id": request.request["request_id"],
                "sha256": request.sha256,
            },
            "result_ref": {"id": result.result["result_id"], "sha256": result.sha256},
            "revision": revision,
            "lifecycle": lifecycle,
            "heartbeat": fresh,
        },
        None,
    )


def _lifecycle(
    status: Mapping[str, Any],
    journal: Mapping[str, Any],
    heartbeat: Mapping[str, Any],
    request: ValidatedRunRequest,
    result: ValidatedRunResult,
    observed: datetime,
    trusted_now: datetime,
    threshold: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request_id, result_id = request.request["request_id"], result.result["result_id"]
    if (
        set(status) != _STATUS_KEYS
        or status.get("version") != ORCHESTRATOR_STATUS_VERSION
    ):
        raise ValidationError("coordinator status schema/version mismatch")
    for key, expected in {
        "request_id": request_id,
        "request_sha256": request.sha256,
        "result_id": result_id,
        "result_sha256": result.sha256,
    }.items():
        if status.get(key) != expected:
            raise ValidationError(f"coordinator status {key} mismatch")
    state = status.get("state")
    if state not in _TERMINAL or status.get("terminal") is not True:
        raise ValidationError("coordinator status is not terminal")
    status_at = _utc(status.get("updated_at"), "status updated_at")
    if (
        set(journal) != {"version", "request_id", "events"}
        or journal.get("version") != ORCHESTRATOR_JOURNAL_VERSION
        or journal.get("request_id") != request_id
    ):
        raise ValidationError("coordinator journal schema/version mismatch")
    events = journal.get("events")
    if not isinstance(events, list) or not events:
        raise ValidationError("coordinator journal events are missing")
    previous = None
    event_at = None
    for index, event in enumerate(events, 1):
        if not isinstance(event, Mapping):
            raise ValidationError("coordinator journal event must be a mapping")
        keys = _EVENT_KEYS | (
            _ACCEPTANCE_KEYS if _ACCEPTANCE_KEYS & set(event) else set()
        )
        if (
            set(event) != keys
            or event.get("sequence") != index
            or event.get("old_state") != previous
        ):
            raise ValidationError("coordinator journal event schema/chain mismatch")
        if event.get("request_sha256") != request.sha256:
            raise ValidationError("coordinator journal request hash mismatch")
        current = _utc(event.get("at"), "journal event at")
        if event_at is not None and current < event_at:
            raise ValidationError("coordinator journal timestamps are not monotonic")
        if (
            not isinstance(event.get("state"), str)
            or not isinstance(event.get("reason"), str)
            or not event["reason"]
        ):
            raise ValidationError("coordinator journal event state/reason is invalid")
        previous, event_at = event["state"], current
    if previous != state or events[-1].get("result_sha256") != result.sha256:
        raise ValidationError("coordinator journal terminal state/hash mismatch")
    if (
        set(heartbeat)
        != {"version", "request_id", "request_sha256", "state", "updated_at"}
        or heartbeat.get("version") != ORCHESTRATOR_HEARTBEAT_VERSION
    ):
        raise ValidationError("coordinator heartbeat schema/version mismatch")
    for key, expected in (
        ("request_id", request_id),
        ("request_sha256", request.sha256),
        ("state", state),
    ):
        if heartbeat.get(key) != expected:
            raise ValidationError(f"coordinator heartbeat {key} mismatch")
    heartbeat_at = _utc(heartbeat.get("updated_at"), "heartbeat updated_at")
    if event_at is None or not event_at <= status_at <= heartbeat_at:
        raise ValidationError(
            "coordinator lifecycle timestamps violate observation order"
        )
    if any(
        moment > trusted_now + _FUTURE_SKEW
        for moment in (event_at, status_at, heartbeat_at)
    ):
        raise ValidationError("coordinator lifecycle timestamp exceeds trusted clock")
    stale = max(0, int((observed - heartbeat_at).total_seconds()))
    return (
        {
            "state": state,
            "terminal": True,
            "event_count": len(events),
            "updated_at": status["updated_at"],
        },
        {
            "updated_at": heartbeat["updated_at"],
            "freshness_threshold_seconds": threshold,
            "stale_seconds": stale,
            "fresh": stale <= threshold,
        },
    )


def validate_attempt_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_attempt_summary(value, _utc_now())


def _validate_attempt_summary(
    value: Mapping[str, Any], trusted_now: datetime
) -> dict[str, Any]:
    if isinstance(value, ValidatedAttemptSummary):
        value = value.persisted_record()
    keys = {
        "version",
        "attempt_id",
        "evidence_class",
        "measurement_mode",
        "observed_at",
        "request_ref",
        "result_ref",
        "revision",
        "lifecycle",
        "heartbeat",
        "counts",
        "safety",
        "summary_hash",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValidationError("attempt summary schema mismatch")
    if (
        value.get("version"),
        value.get("evidence_class"),
        value.get("measurement_mode"),
    ) != (ATTEMPT_SUMMARY_VERSION, "compatibility", "diagnostic_exact_source"):
        raise ValidationError("attempt summary compatibility identity mismatch")
    _id(value.get("attempt_id"), "attempt_id")
    _id(value.get("revision"), "revision")
    observed = _utc(value.get("observed_at"), "observed_at")
    if observed > trusted_now + _FUTURE_SKEW:
        raise ValidationError("observed_at exceeds trusted clock")
    for name in ("request_ref", "result_ref"):
        ref = value.get(name)
        if not isinstance(ref, Mapping) or set(ref) != {"id", "sha256"}:
            raise ValidationError(f"{name} schema mismatch")
        _id(ref.get("id"), f"{name} id")
        _digest(ref.get("sha256"), f"{name} hash")
    lifecycle = value.get("lifecycle")
    if (
        not isinstance(lifecycle, Mapping)
        or set(lifecycle) != {"state", "terminal", "event_count", "updated_at"}
        or lifecycle.get("state") not in _TERMINAL
        or lifecycle.get("terminal") is not True
    ):
        raise ValidationError("attempt summary lifecycle mismatch")
    _count(lifecycle.get("event_count"), "event count", 64, 1)
    lifecycle_at = _utc(lifecycle.get("updated_at"), "lifecycle updated_at")
    if lifecycle_at > trusted_now + _FUTURE_SKEW:
        raise ValidationError("lifecycle timestamp exceeds trusted clock")
    heartbeat = value.get("heartbeat")
    if not isinstance(heartbeat, Mapping) or set(heartbeat) != {
        "updated_at",
        "freshness_threshold_seconds",
        "stale_seconds",
        "fresh",
    }:
        raise ValidationError("attempt summary heartbeat schema mismatch")
    heartbeat_at = _utc(heartbeat.get("updated_at"), "heartbeat updated_at")
    threshold = _count(
        heartbeat.get("freshness_threshold_seconds"), "freshness threshold", 86400, 1
    )
    stale = _count(heartbeat.get("stale_seconds"), "stale seconds", 31536000)
    if heartbeat_at > trusted_now + _FUTURE_SKEW:
        raise ValidationError("heartbeat timestamp exceeds trusted clock")
    recomputed = max(0, int((observed - heartbeat_at).total_seconds()))
    if stale != recomputed or heartbeat.get("fresh") is not (recomputed <= threshold):
        raise ValidationError("heartbeat freshness is not derived from observed_at")
    if value.get("counts") != {
        "provider": 0,
        "network": 0,
        "subprocess": 0,
        "runtime_traffic": 0,
    }:
        raise ValidationError(
            "provider/network/subprocess/runtime traffic counts must remain zero"
        )
    if value.get("safety") != {
        "sensitive_content_absent": True,
        "personal_data_absent": True,
        "redaction_passed": True,
        "enablement_status": "not_authorized",
        "runtime_default_off": True,
        "promotion_authority": False,
    }:
        raise ValidationError("attempt summary is not default-off/not-authorized")
    _self_hash(value, "summary_hash")
    reject_sensitive_observability_value(value)
    return deepcopy(dict(value))


def derive_alerts(
    summary: ValidatedAttemptSummary,
    *,
    compatibility_failure_count: int = 0,
    expected_revision: str | None = None,
    budget_breach_detected: bool = False,
    privacy_finding_count: int = 0,
    release_holdout_reference_count: int = 0,
    authorization_enablement_requested: bool = False,
    exception: BaseException | None = None,
    quarantine_reference: str | None = None,
) -> tuple[ValidatedAlert, ...]:
    if not isinstance(summary, ValidatedAttemptSummary):
        raise ValidationError("alerts require a validated attempt summary capability")
    summary = revalidate_attempt_summary(summary)
    record = summary.persisted_record()
    for label, count in (
        ("compatibility failure count", compatibility_failure_count),
        ("privacy finding count", privacy_finding_count),
        ("release holdout reference count", release_holdout_reference_count),
    ):
        _count(count, label, 1_000_000)
    if expected_revision is not None:
        _id(expected_revision, "expected revision")
    if quarantine_reference is not None and not _QUARANTINE_REFERENCE.fullmatch(
        quarantine_reference
    ):
        raise ValidationError("quarantine reference must be an exact quarantine digest")
    exception_digest = (
        None
        if exception is None
        else "sha256:"
        + hashlib.sha256(type(exception).__qualname__.encode()).hexdigest()
    )
    active = {
        AlertCode.STALE_HEARTBEAT: record["heartbeat"]["fresh"] is False,
        AlertCode.REPEATED_COMPATIBILITY_FAILURE: compatibility_failure_count >= 3,
        AlertCode.REVISION_DRIFT: expected_revision is not None
        and expected_revision != record["revision"],
        AlertCode.BUDGET_BREACH: budget_breach_detected is True,
        AlertCode.PRIVACY_FINDING: privacy_finding_count > 0 or exception is not None,
        AlertCode.RELEASE_HOLDOUT_LEAK: release_holdout_reference_count > 0,
        AlertCode.AUTHORIZATION_MISUSE: authorization_enablement_requested is True,
    }
    alerts = []
    for code in sorted(
        (code for code, enabled in active.items() if enabled),
        key=lambda item: item.value,
    ):
        severity, retention, grace = _ALERT_POLICY[code.value]
        item = {
            "version": ALERT_VERSION,
            "code": code.value,
            "reason": code.value,
            "owner": "skillopt-operations",
            "severity": severity,
            "retention_days": retention,
            "deletion_grace_days": grace,
            "attempt_id": record["attempt_id"],
            "summary_hash": record["summary_hash"],
            "exception_digest": exception_digest,
            "quarantine_reference": quarantine_reference,
        }
        reject_sensitive_observability_value(item)
        item["alert_hash"] = canonical_value_hash(item)
        alerts.append(_mint(ValidatedAlert, _validate_alert(item), summary._source))
    return tuple(alerts)


def _validate_alert(value: Mapping[str, Any]) -> dict[str, Any]:
    keys = {
        "version",
        "code",
        "reason",
        "owner",
        "severity",
        "retention_days",
        "deletion_grace_days",
        "attempt_id",
        "summary_hash",
        "exception_digest",
        "quarantine_reference",
        "alert_hash",
    }
    if set(value) != keys:
        raise ValidationError("alert schema mismatch")
    code = value.get("code")
    if code not in _ALERT_POLICY or (
        value.get("version"),
        value.get("reason"),
        value.get("owner"),
    ) != (ALERT_VERSION, code, "skillopt-operations"):
        raise ValidationError("alert fixed policy mismatch")
    if (
        value.get("severity"),
        value.get("retention_days"),
        value.get("deletion_grace_days"),
    ) != _ALERT_POLICY[str(code)]:
        raise ValidationError("alert retention/severity/deletion policy mismatch")
    _id(value.get("attempt_id"), "alert attempt_id")
    _digest(value.get("summary_hash"), "summary hash")
    if value.get("exception_digest") is not None:
        _digest(value["exception_digest"], "exception digest")
    if value.get(
        "quarantine_reference"
    ) is not None and not _QUARANTINE_REFERENCE.fullmatch(
        value["quarantine_reference"]
    ):
        raise ValidationError("alert quarantine reference is invalid")
    _self_hash(value, "alert_hash")
    reject_sensitive_observability_value(value)
    return deepcopy(dict(value))


def build_operator_envelope(
    summary: ValidatedAttemptSummary, alerts: Sequence[ValidatedAlert]
) -> ValidatedOperatorEnvelope:
    if not isinstance(summary, ValidatedAttemptSummary) or any(
        not isinstance(item, ValidatedAlert) for item in alerts
    ):
        raise ValidationError("operator envelope requires typed summary and alerts")
    summary = revalidate_attempt_summary(summary)
    if any(item._source != summary._source for item in alerts):
        raise ValidationError("operator alert source context mismatch")
    records = [_validate_alert(item.persisted_record()) for item in alerts]
    codes = [item["code"] for item in records]
    if len(records) > 7 or codes != sorted(codes) or len(codes) != len(set(codes)):
        raise ValidationError("operator alerts must be bounded, unique, and ordered")
    value = {
        "version": OPERATOR_ENVELOPE_VERSION,
        "mode": "observe_only",
        "summary": summary.persisted_record(),
        "alerts": records,
        "network_action": False,
        "provider_action": False,
        "subprocess_action": False,
        "production_action": False,
        "runtime_action": False,
        "promotion_action": False,
    }
    reject_sensitive_observability_value(value)
    value["envelope_hash"] = canonical_value_hash(value)
    validated = validate_operator_envelope(value)
    return _mint(ValidatedOperatorEnvelope, validated, summary._source)


def validate_operator_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, ValidatedOperatorEnvelope):
        value = value.persisted_record()
    keys = {
        "version",
        "mode",
        "summary",
        "alerts",
        "network_action",
        "provider_action",
        "subprocess_action",
        "production_action",
        "runtime_action",
        "promotion_action",
        "envelope_hash",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != keys
        or (value.get("version"), value.get("mode"))
        != (OPERATOR_ENVELOPE_VERSION, "observe_only")
    ):
        raise ValidationError("operator envelope schema/mode mismatch")
    actions = (
        "network_action",
        "provider_action",
        "subprocess_action",
        "production_action",
        "runtime_action",
        "promotion_action",
    )
    if any(value.get(name) is not False for name in actions):
        raise ValidationError("observe-only operator envelope cannot perform actions")
    summary = validate_attempt_summary(value.get("summary"))
    raw = value.get("alerts")
    if (
        not isinstance(raw, list)
        or len(raw) > 7
        or any(not isinstance(item, Mapping) for item in raw)
    ):
        raise ValidationError("operator envelope alerts are invalid")
    alerts = tuple(_validate_alert(item) for item in raw)
    if any(
        item["summary_hash"] != summary["summary_hash"]
        or item["attempt_id"] != summary["attempt_id"]
        for item in alerts
    ):
        raise ValidationError("operator alert does not bind summary")
    codes = [item["code"] for item in alerts]
    if codes != sorted(codes) or len(codes) != len(set(codes)):
        raise ValidationError("operator alerts are not deterministic")
    _self_hash(value, "envelope_hash")
    reject_sensitive_observability_value(value)
    return deepcopy(dict(value))


def load_attempt_summary(
    path: str | Path,
    *,
    request_path: str | Path,
    result_path: str | Path,
    run_root: str | Path,
) -> ValidatedAttemptSummary:
    raw = _load(path, "attempt summary")
    validated = validate_attempt_summary(raw)
    rebuilt = _build_attempt_summary_from_sources(
        attempt_id=validated["attempt_id"],
        request_path=request_path,
        result_path=result_path,
        run_root=run_root,
        freshness_threshold_seconds=validated["heartbeat"][
            "freshness_threshold_seconds"
        ],
        now_fn=_utc_now,
        observed_at=validated["observed_at"],
    )
    if canonical_json_bytes(rebuilt.persisted_record()) != canonical_json_bytes(raw):
        raise ValidationError("attempt summary does not match authoritative sources")
    return rebuilt


def load_operator_envelope(
    path: str | Path,
    *,
    request_path: str | Path,
    result_path: str | Path,
    run_root: str | Path,
) -> ValidatedOperatorEnvelope:
    raw = _load(path, "operator envelope")
    validated = validate_operator_envelope(raw)
    summary_raw = validated["summary"]
    summary = _build_attempt_summary_from_sources(
        attempt_id=summary_raw["attempt_id"],
        request_path=request_path,
        result_path=result_path,
        run_root=run_root,
        freshness_threshold_seconds=summary_raw["heartbeat"][
            "freshness_threshold_seconds"
        ],
        now_fn=_utc_now,
        observed_at=summary_raw["observed_at"],
    )
    if summary.persisted_record() != summary_raw:
        raise ValidationError("operator envelope summary source mismatch")
    alerts = tuple(
        _mint(ValidatedAlert, _validate_alert(item), summary._source)
        for item in validated["alerts"]
    )
    rebuilt = _mint(ValidatedOperatorEnvelope, validated, summary._source)
    if any(alert["summary_hash"] != summary["summary_hash"] for alert in alerts):
        raise ValidationError("operator envelope alert source mismatch")
    if canonical_json_bytes(rebuilt.persisted_record()) != canonical_json_bytes(raw):
        raise ValidationError("operator envelope does not match authoritative artifact")
    return rebuilt


def revalidate_attempt_summary(
    value: ValidatedAttemptSummary,
) -> ValidatedAttemptSummary:
    if not isinstance(value, ValidatedAttemptSummary):
        raise ValidationError("revalidation requires a typed summary")
    if value._source is None:
        raise ValidationError("summary has no authoritative source context")
    record = validate_attempt_summary(value.persisted_record())
    rebuilt = _build_attempt_summary_from_sources(
        attempt_id=record["attempt_id"],
        request_path=value._source.request_path,
        result_path=value._source.result_path,
        run_root=value._source.run_root,
        freshness_threshold_seconds=record["heartbeat"]["freshness_threshold_seconds"],
        now_fn=_utc_now,
        observed_at=record["observed_at"],
        expected_source=value._source,
    )
    if rebuilt.persisted_record() != record:
        raise ValidationError("summary no longer matches authoritative sources")
    return rebuilt


def revalidate_operator_envelope(
    value: ValidatedOperatorEnvelope,
) -> ValidatedOperatorEnvelope:
    if not isinstance(value, ValidatedOperatorEnvelope):
        raise ValidationError("revalidation requires a typed envelope")
    if value._source is None:
        raise ValidationError("envelope has no authoritative source context")
    record = validate_operator_envelope(value.persisted_record())
    summary = _mint(ValidatedAttemptSummary, record["summary"], value._source)
    revalidate_attempt_summary(summary)
    return _mint(ValidatedOperatorEnvelope, record, value._source)


def _load(path: str | Path, label: str) -> dict[str, Any]:
    held = read_stable_file(path)
    try:
        value = json.loads(held.payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{label} JSON is unreadable") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != held.payload:
        raise ValidationError(f"{label} is not canonical JSON")
    return value


def _decode_canonical_source(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{label} JSON is unreadable") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
        raise ValidationError(f"{label} is not canonical JSON")
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _trusted_now(now_fn: Callable[[], datetime]) -> datetime:
    value = now_fn()
    if not isinstance(value, datetime) or value.tzinfo != timezone.utc:
        raise ValidationError("trusted clock must return a UTC datetime")
    return value


def _format_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _validated_persisted_observation_time(value: str, trusted_now: datetime) -> str:
    observed = _utc(value, "observed_at")
    if observed > trusted_now + _FUTURE_SKEW:
        raise ValidationError("observed_at exceeds trusted clock")
    return value


def _utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValidationError(f"{label} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValidationError(f"{label} must be a UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValidationError(f"{label} must be a UTC timestamp")
    return parsed


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValidationError(f"{label} is not a bounded identifier")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ValidationError(f"{label} is not a sha256 digest")
    return value


def _count(value: Any, label: str, maximum: int, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(f"{label} is outside its bounded range")
    return value


def _self_hash(value: Mapping[str, Any], field: str) -> None:
    claimed = value.get(field)
    _digest(claimed, field)
    payload = dict(value)
    payload.pop(field)
    if claimed != canonical_value_hash(payload):
        raise ValidationError(f"{field} mismatch")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    summary = build_attempt_summary(
        attempt_id="attempt:compatibility",
        request_path=args.request,
        result_path=args.result,
        run_root=args.run_root,
    )
    alerts = derive_alerts(summary)
    envelope = revalidate_operator_envelope(build_operator_envelope(summary, alerts))
    payload = canonical_json_bytes(envelope.persisted_record())
    if args.output is not None:
        args.output.write_bytes(payload)
    print(payload.decode("utf-8"))
    return 2 if alerts else 0


__all__ = [
    "ALERT_VERSION",
    "ATTEMPT_SUMMARY_VERSION",
    "DEFAULT_FRESHNESS_SECONDS",
    "OBSERVATION_VERSION",
    "OPERATOR_ENVELOPE_VERSION",
    "AlertCode",
    "EvidenceClass",
    "ValidatedAlert",
    "ValidatedAttemptSummary",
    "ValidatedCompatibilityObservation",
    "ValidatedOperatorEnvelope",
    "build_attempt_summary",
    "build_operator_envelope",
    "derive_alerts",
    "load_attempt_summary",
    "load_operator_envelope",
    "main",
    "reject_sensitive_observability_value",
    "revalidate_attempt_summary",
    "revalidate_operator_envelope",
    "validate_attempt_summary",
    "validate_evidence_gate",
    "validate_operator_envelope",
]

if __name__ == "__main__":
    raise SystemExit(main())
