"""Strict reader for common-local recommendation deliveries, never raw candidates."""

from __future__ import annotations

import json
import math
import os
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.recommendation_candidates import CandidateValidationError, normalize_candidate
from src.recommendation_state import RecommendationPolicy
from src.utils.secure_directory import open_directory

DELIVERY_SCHEMA = "recommendation_delivery_v1"
POLICY_VERSION = "recommendation_policy_v1"
MAX_DELIVERY_BYTES = 2 * 1024 * 1024
MAX_DELIVERY_FILES = 400
_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_SOURCES = {"local_public", "owner_local", "openclaw"}
_SOURCE_STATES = {
    "ready",
    "empty",
    "missing",
    "invalid",
    "disabled",
    "stale",
    "error",
    "degraded",
}
_REASONS = {
    "events_unavailable",
    "events_error",
    "ranker_error",
    "source_missing",
    "source_invalid",
    "source_error",
    "source_stale",
    "budget_exhausted",
    "delivery_stale",
    "delivery_expired",
    "policy_unavailable",
    "authority_unavailable",
    "invalid_artifact",
    "no_candidates",
    "no_eligible_candidates",
    "source_disabled",
    "limited_coverage",
    "artifact_scan_limit",
}


class DeliveryValidationError(ValueError):
    """A payload-free, fail-closed delivery boundary error."""


def safe_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def delivery_identifier(value: Any) -> str:
    if not isinstance(value, str) or not _IDENT.fullmatch(value):
        raise DeliveryValidationError("invalid_identifier")
    return value


def parse_delivery_time(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        raise DeliveryValidationError("invalid_time") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise DeliveryValidationError("invalid_time")
    return parsed.astimezone(timezone.utc)


def _finite(value: Any) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise DeliveryValidationError("invalid_score")
    return float(value)


def validate_delivery(
    raw: Any, *, incarnation: str, now: datetime, run_id: str | None = None
) -> dict:
    """Validate provenance, identity and order before exposing any row."""
    delivery_identifier(incarnation)
    if (
        not isinstance(raw, dict)
        or raw.get("schema") != DELIVERY_SCHEMA
        or raw.get("producer") != "common_local"
    ):
        raise DeliveryValidationError("invalid_producer")
    if raw.get("account_incarnation") != incarnation:
        raise DeliveryValidationError("wrong_incarnation")
    actual_run = delivery_identifier(raw.get("run_id"))
    if run_id is not None and actual_run != run_id:
        raise DeliveryValidationError("wrong_run")
    generated = parse_delivery_time(raw.get("run_at"))
    cutoff = parse_delivery_time(raw.get("cutoff"))
    if now.tzinfo is None or generated > now or cutoff > generated:
        raise DeliveryValidationError("invalid_time")
    if raw.get("policy_version") != POLICY_VERSION:
        raise DeliveryValidationError("invalid_policy")
    for key in ("code_hash", "config_hash", "input_manifest_hash"):
        if not isinstance(raw.get(key), str) or not re.fullmatch(
            r"[a-f0-9]{64}", raw[key]
        ):
            raise DeliveryValidationError("missing_manifest")
    if raw.get("scoring_mode") not in {
        "v1",
        "v2",
        "v1_fallback",
        "metadata",
    } or not isinstance(raw.get("ranker_version"), str):
        raise DeliveryValidationError("invalid_scoring_mode")
    if raw.get("status") not in {"ready", "empty", "degraded"}:
        raise DeliveryValidationError("invalid_status")
    reasons = raw.get("degraded_reasons", [])
    sources = raw.get("source_statuses", {})
    if not isinstance(reasons, list) or any(
        reason not in _REASONS for reason in reasons
    ):
        raise DeliveryValidationError("invalid_status")
    if not isinstance(sources, dict) or any(
        key not in _SOURCES or value not in _SOURCE_STATES
        for key, value in sources.items()
    ):
        raise DeliveryValidationError("invalid_source_status")
    items = raw.get("items")
    if not isinstance(items, list) or len(items) > 12:
        raise DeliveryValidationError("invalid_reserve")
    cleaned, identities = [], set()
    previous_rank = 0
    for row in items:
        if not isinstance(row, dict):
            raise DeliveryValidationError("invalid_item")
        try:
            normalized = normalize_candidate(row)
        except CandidateValidationError:
            raise DeliveryValidationError("invalid_metadata") from None
        key = row.get("canonical_key")
        if key != normalized.canonical_key or key in identities:
            raise DeliveryValidationError("invalid_identity")
        identities.add(key)
        rank = row.get("final_rank")
        if (
            isinstance(rank, bool)
            or not isinstance(rank, int)
            or not previous_rank < rank <= 12
        ):
            raise DeliveryValidationError("invalid_rank")
        previous_rank = rank
        if (
            normalized.metadata.get("year", cutoff.year) > cutoff.year
            or normalized.metadata.get("publication_date", cutoff.date().isoformat())
            > cutoff.date().isoformat()
        ):
            raise DeliveryValidationError("future_publication")
        reason = row.get("reason", "")
        if not isinstance(reason, str) or len(reason) > 512:
            raise DeliveryValidationError("invalid_reason")
        candidate_sources = row.get("candidate_sources", [])
        if not isinstance(candidate_sources, list) or any(
            source not in _SOURCES for source in candidate_sources
        ):
            raise DeliveryValidationError("invalid_source_status")
        breakdown = row.get("score_breakdown", {})
        if not isinstance(breakdown, dict) or len(breakdown) > 16:
            raise DeliveryValidationError("invalid_score")
        for factor, value in breakdown.items():
            if not isinstance(factor, str) or not re.fullmatch(r"[a-z_]{1,48}", factor):
                raise DeliveryValidationError("invalid_score")
            _finite(value)
        cleaned.append(
            {
                **normalized.metadata,
                "canonical_key": key,
                "final_rank": rank,
                "score": _finite(row.get("score")),
                "reason": reason,
                "candidate_sources": list(candidate_sources),
                "score_breakdown": dict(breakdown),
            }
        )
    if bool(items) == (raw["status"] == "empty"):
        raise DeliveryValidationError("inconsistent_status")
    return {**raw, "items": cleaned}


def empty_response(
    *, state: str = "empty", reason: str | None = None
) -> dict[str, Any]:
    return {
        "items": [],
        "unread_count": 0,
        "total_count": 0,
        "latest_run_at": None,
        "run_id": None,
        "scoring_mode": None,
        "state": state,
        "freshness": "missing",
        "source_statuses": {},
        "degraded_reasons": [reason] if reason else [],
    }


def open_delivery_owner(root: Path, incarnation: str, *, create: bool = False) -> int:
    """Open a stable no-symlink directory descriptor for a single incarnation."""
    delivery_identifier(incarnation)
    return open_directory(Path(root) / incarnation, create=create)


def _read_file(owner_fd: int, name: str, *, incarnation: str, now: datetime) -> dict:
    run_id = delivery_identifier(name.removesuffix(".json"))
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=owner_fd)
    with os.fdopen(fd, "rb") as handle:
        file_stat = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_size > MAX_DELIVERY_BYTES
        ):
            raise DeliveryValidationError("invalid_file")
        content = handle.read(MAX_DELIVERY_BYTES + 1)
    if len(content) > MAX_DELIVERY_BYTES:
        raise DeliveryValidationError("size_limit")
    try:
        raw = json.loads(content)
    except (ValueError, UnicodeError):
        raise DeliveryValidationError("invalid_json") from None
    return validate_delivery(raw, incarnation=incarnation, now=now, run_id=run_id)


def read_delivery(
    root: Path, incarnation: str, *, now: datetime, run_id: str | None = None
) -> dict | None:
    """Only scan the exact owner's flat directory; mtime is never ordering data."""
    try:
        owner_fd = open_delivery_owner(root, incarnation)
    except FileNotFoundError:
        return None
    try:
        if run_id is not None:
            name = delivery_identifier(run_id) + ".json"
            try:
                return _read_file(owner_fd, name, incarnation=incarnation, now=now)
            except FileNotFoundError:
                return None
        candidates, count, invalid = [], 0, 0
        with os.scandir(owner_fd) as entries:
            for entry in entries:
                count += 1
                if count > MAX_DELIVERY_FILES:
                    raise DeliveryValidationError("artifact_scan_limit")
                if not entry.name.endswith(".json"):
                    continue
                try:
                    raw = _read_file(
                        owner_fd, entry.name, incarnation=incarnation, now=now
                    )
                except (OSError, DeliveryValidationError):
                    invalid += 1
                    continue
                candidates.append(raw)
        if not candidates:
            if invalid:
                raise DeliveryValidationError("invalid_artifact")
            return None
        selected = max(
            candidates,
            key=lambda raw: (parse_delivery_time(raw["run_at"]), raw["run_id"]),
        )
        if invalid:
            selected = {
                **selected,
                "status": "degraded" if selected["items"] else "empty",
                "degraded_reasons": [
                    *selected.get("degraded_reasons", []),
                    "invalid_artifact",
                ],
            }
        return selected
    finally:
        os.close(owner_fd)


def load_recommendation_artifact(
    root: Path,
    incarnation: str,
    limit: int,
    *,
    policy: RecommendationPolicy,
    now: datetime,
) -> dict[str, Any]:
    """Project the common ordered reserve through the current durable policy."""
    if not 1 <= limit <= 5:
        raise DeliveryValidationError("invalid_limit")
    if policy.incarnation != incarnation:
        raise DeliveryValidationError("wrong_policy_owner")
    raw = read_delivery(root, incarnation, now=now)
    if raw is None:
        return empty_response()
    age = now - parse_delivery_time(raw["run_at"])
    result = {
        "latest_run_at": raw["run_at"],
        "run_id": raw["run_id"],
        "scoring_mode": raw["scoring_mode"],
        "state": raw["status"],
        "freshness": "fresh",
        "source_statuses": dict(raw["source_statuses"]),
        "degraded_reasons": list(raw.get("degraded_reasons", [])),
    }
    if age >= timedelta(hours=72):
        return {
            **result,
            "items": [],
            "total_count": 0,
            "unread_count": 0,
            "state": "expired",
            "freshness": "expired",
            "degraded_reasons": [*result["degraded_reasons"], "delivery_expired"],
        }
    eligible = policy.project(raw["items"], limit=12)
    result.update(
        items=eligible[:limit],
        total_count=len(eligible),
        unread_count=sum(not paper["seen"] for paper in eligible),
    )
    if age >= timedelta(hours=36):
        result.update(
            state="stale",
            freshness="stale",
            degraded_reasons=[*result["degraded_reasons"], "delivery_stale"],
        )
    elif not eligible:
        result["state"] = "empty"
    return result
