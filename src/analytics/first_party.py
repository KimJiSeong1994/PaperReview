"""First-party analytics events stored in analytics.db."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote

from src.analytics.ga4_bigquery_sync import ensure_analytics_db, utc_now_iso

ALLOWED_FIRST_PARTY_EVENTS = frozenset(
    {
        "page_view",
        "search",
        "paper_select",
        "login",
        "sign_up",
        "deep_review_start",
        "deep_review_complete",
        "deep_review_fail",
        "bookmark_save",
        "report_download",
        "poster_generate_start",
        "poster_generate_complete",
        "poster_generate_fail",
    }
)

_SENSITIVE_KEY_RE = re.compile(r"(query|q|token|jwt|auth|password|email|title|user|paper|doi|arxiv|bookmark|curriculum)", re.I)
_ALLOWED_PAYLOAD_KEYS = frozenset(
    {
        "query_length_bucket",
        "query_class",
        "result_status",
        "result_count_bucket",
        "selected_count_bucket",
        "source",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_id",
        "utm_term",
        "utm_content",
        "page_type",
    }
)
_ATTRIBUTION_PAYLOAD_KEYS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_id",
        "utm_term",
        "utm_content",
        "page_type",
    }
)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,96}$")
_ATTRIBUTION_VALUE_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._~%+-]+")
_PRIVATE_PREFIXES = ("/admin", "/mypage", "/share")


@dataclass(frozen=True)
class AppAnalyticsEvent:
    user_id: str | None
    client_id: str
    session_id: str
    event_name: str
    page_path: str
    payload: dict[str, str | int | float | bool]
    source: str = "first_party"


def sanitize_identifier(value: str, *, field_name: str) -> str:
    value = value.strip()
    if not _SAFE_ID_RE.match(value):
        raise ValueError(f"invalid {field_name}")
    return value[:96]


def sanitize_page_path(path: str) -> str:
    value = (path or "/").strip()[:512].replace("\\", "/")
    for _ in range(3):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    value = re.sub(r"[?#].*$", "", value)
    value = re.sub(r"/{2,}", "/", value)
    if not value.startswith("/"):
        value = "/"
    lowered = value.lower()
    if any(lowered == prefix or lowered.startswith(prefix + "/") for prefix in _PRIVATE_PREFIXES):
        return "/private"
    return value[:256] or "/"


def _sanitize_attribution_value(value: str) -> str | None:
    value = value.strip().replace("\x00", "")
    if not value or "@" in value:
        return None
    safe_value = _ATTRIBUTION_VALUE_UNSAFE_RE.sub("_", value[:128])
    safe_value = re.sub(r"_+", "_", safe_value).strip("_")[:80]
    return safe_value or None


def sanitize_payload(payload: Mapping[str, Any] | None) -> dict[str, str | int | float | bool]:
    if not payload:
        return {}
    sanitized: dict[str, str | int | float | bool] = {}
    for key, value in payload.items():
        if len(sanitized) >= 20:
            break
        safe_key = str(key).strip()
        if not safe_key or len(safe_key) > 64:
            continue
        if safe_key not in _ALLOWED_PAYLOAD_KEYS and _SENSITIVE_KEY_RE.search(safe_key):
            continue
        if isinstance(value, str) and safe_key in _ATTRIBUTION_PAYLOAD_KEYS:
            safe_value = _sanitize_attribution_value(value)
            if safe_value:
                sanitized[safe_key] = safe_value
        elif isinstance(value, bool):
            sanitized[safe_key] = value
        elif isinstance(value, int):
            sanitized[safe_key] = value
        elif isinstance(value, float):
            sanitized[safe_key] = value
        elif isinstance(value, str):
            sanitized[safe_key] = value[:128]
    return sanitized


def record_app_analytics_event(db_path: Path, event: AppAnalyticsEvent) -> int:
    ensure_analytics_db(db_path)
    now = utc_now_iso()
    payload_json = json.dumps(sanitize_payload(event.payload), ensure_ascii=False, separators=(",", ":"))
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        cur = conn.execute(
            """
            INSERT INTO app_analytics_events (
                user_id, client_id, session_id, event_name, page_path,
                payload, source, created_at, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.user_id,
                sanitize_identifier(event.client_id, field_name="client_id"),
                sanitize_identifier(event.session_id, field_name="session_id"),
                event.event_name,
                sanitize_page_path(event.page_path),
                payload_json,
                event.source,
                now,
                now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


__all__ = [
    "ALLOWED_FIRST_PARTY_EVENTS",
    "AppAnalyticsEvent",
    "record_app_analytics_event",
    "sanitize_identifier",
    "sanitize_page_path",
    "sanitize_payload",
]
