"""Bounded private recommendation features. Tokenization is not anonymization."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

from src.events.event_types import EventType
from src.recommendations_artifacts import safe_str
from src.utils.paper_utils import generate_result_key

EVENT_SCHEMA_VERSION = "recommendation_event_contract_v1"
MAX_EVENT_TERMS = 8
DEFAULT_SINCE_DAYS = 90
_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣_\-]{1,48}")
_SYNTHETIC_SOURCES = {"test", "e2e", "synthetic"}
_POSITIVE_EVENT_WEIGHTS = {
    EventType.REVIEW_CREATE.value: 10.0,
    EventType.REVIEW_UPDATE.value: 6.0,
    EventType.BOOKMARK_ADD.value: 8.0,
    EventType.HIGHLIGHT_CREATE.value: 7.0,
    EventType.HIGHLIGHT_UPDATE.value: 4.0,
    EventType.PAPER_OPEN.value: 3.0,
    EventType.SEARCH_CLICK.value: 2.0,
    EventType.QUERY_SUBMIT.value: 1.5,
}
_NEGATIVE_EVENT_WEIGHTS = {
    EventType.BOOKMARK_REMOVE.value: 6.0,
    EventType.HIGHLIGHT_DELETE.value: 2.0,
}
_EVENT_HALF_LIFE_DAYS = {
    EventType.QUERY_SUBMIT.value: 14.0,
    EventType.SEARCH_CLICK.value: 14.0,
    EventType.PAPER_OPEN.value: 21.0,
    EventType.BOOKMARK_ADD.value: 90.0,
    EventType.BOOKMARK_REMOVE.value: 60.0,
    EventType.REVIEW_CREATE.value: 120.0,
    EventType.REVIEW_UPDATE.value: 90.0,
    EventType.HIGHLIGHT_CREATE.value: 90.0,
    EventType.HIGHLIGHT_UPDATE.value: 60.0,
    EventType.HIGHLIGHT_DELETE.value: 60.0,
}
# Recommendation controls are supplementary analytics, not preference authority:
# replaying them would resurrect state that has expired or been undone.
_SUPPORTED = (
    set(_POSITIVE_EVENT_WEIGHTS)
    | set(_NEGATIVE_EVENT_WEIGHTS)
    | {EventType.SCORE_OVERRIDE.value}
)


@dataclass(frozen=True)
class RecommendationEventSignal:
    event_type: str
    created_at: datetime
    source: str = "app"
    terms: tuple[str, ...] = ()
    paper_id: str | None = None
    bookmark_id: str | None = None
    score: float | None = None
    feedback_type: str | None = None
    event_id: str | None = None


@dataclass(frozen=True)
class EventSignalLoadResult:
    signals: tuple[RecommendationEventSignal, ...] = ()
    status: Literal["ok", "unavailable", "error"] = "ok"


@dataclass
class RecommendationProfile:
    positive_terms: Counter[str] = field(default_factory=Counter)
    negative_terms: Counter[str] = field(default_factory=Counter)
    query_terms: Counter[str] = field(default_factory=Counter)
    positive_paper_ids: set[str] = field(default_factory=set)
    negative_paper_ids: set[str] = field(default_factory=set)
    signal_counts: Counter[str] = field(default_factory=Counter)
    event_count: int = 0
    event_status: str = "ok"

    def public_summary(
        self, *, bookmark_count: int, fallback_recent: bool
    ) -> dict[str, Any]:
        return {
            "bookmark_count": bookmark_count,
            "event_count": self.event_count,
            "event_status": self.event_status,
            "fallback_recent": fallback_recent,
            "signal_counts": dict(self.signal_counts),
            "profile_contract": EVENT_SCHEMA_VERSION,
        }


def _parse_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(safe_str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _tokenize_terms(values: Iterable[Any]) -> tuple[str, ...]:
    terms: list[str] = []
    for value in values:
        for token in _TOKEN_RE.findall(safe_str(value)[:512].lower()):
            clean = token.strip("_-")
            if len(clean) >= 2 and not clean.isdigit() and clean not in terms:
                terms.append(clean)
            if len(terms) >= MAX_EVENT_TERMS:
                return tuple(terms)
    return tuple(terms)


def _payload_terms(payload: dict[str, Any]) -> tuple[str, ...]:
    for key in ("normalized_terms", "query_terms", "terms", "topics", "categories"):
        value = payload.get(key)
        if isinstance(value, list):
            return _tokenize_terms(value[:MAX_EVENT_TERMS])
        if isinstance(value, str):
            return _tokenize_terms((value[:512],))
    return ()


def normalize_event_row(
    row: sqlite3.Row | dict[str, Any], *, now: datetime
) -> RecommendationEventSignal | None:
    row = dict(row)
    event_type = safe_str(row.get("event_type"))
    source = safe_str(row.get("source")) or "app"
    created_at = _parse_datetime(row.get("created_at"))
    if event_type not in _SUPPORTED or source.lower() in _SYNTHETIC_SOURCES:
        return None
    if created_at is None or created_at > now:
        return None
    raw = row.get("payload")
    if isinstance(raw, str) and len(raw) > 65536:
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    paper_id = safe_str(payload.get("paper_id") or row.get("paper_id")) or None
    bookmark_id = safe_str(payload.get("bookmark_id")) or None
    if event_type in {EventType.BOOKMARK_ADD.value, EventType.BOOKMARK_REMOVE.value}:
        bookmark_id = bookmark_id or safe_str(row.get("paper_id")) or None
        paper_id = safe_str(payload.get("paper_id")) or None
    score = None
    if event_type == EventType.SCORE_OVERRIDE.value:
        try:
            score = float(payload.get("score"))
        except (ValueError, TypeError, OverflowError):
            return None
        if not math.isfinite(score) or not 0 <= score <= 5:
            return None
    terms = _payload_terms(payload)
    feedback_type = (
        safe_str(payload.get("feedback_type") or payload.get("action")) or None
    )
    if not terms and not paper_id and score is None and feedback_type is None:
        return None
    return RecommendationEventSignal(
        event_type,
        created_at,
        source,
        terms,
        paper_id,
        bookmark_id,
        score,
        feedback_type,
        safe_str(row.get("id")) or None,
    )


def load_user_event_signals(
    events_db: Path | None,
    username: str,
    *,
    now: datetime,
    account_incarnation: str,
    legacy_before: datetime | None = None,
    since_days: int = DEFAULT_SINCE_DAYS,
    max_events: int = 500,
) -> EventSignalLoadResult:
    """Read only the authenticated account incarnation's private features.

    Only an authoritative original-account cutoff may admit unclaimed legacy
    events. Explicit foreign claims never qualify for that exception.
    """
    if not isinstance(account_incarnation, str) or not account_incarnation.strip():
        raise ValueError("account_incarnation must be a nonempty string")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if legacy_before is not None and legacy_before.tzinfo is None:
        raise ValueError("legacy_before must be timezone-aware")
    if events_db is None or not events_db.exists():
        return EventSignalLoadResult(status="unavailable")
    cutoff = now - timedelta(days=max(1, since_days))
    supported = sorted(_SUPPORTED)
    try:
        conn = sqlite3.connect(f"file:{events_db.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                f"""SELECT id, event_type, payload, paper_id, created_at, source FROM user_events
                WHERE user_id = ? AND event_type IN ({",".join("?" for _ in supported)})
                AND julianday(created_at) >= julianday(?) AND julianday(created_at) <= julianday(?)
                AND lower(coalesce(source, 'app')) NOT IN ('test', 'synthetic', 'e2e')
                AND CASE WHEN json_valid(payload) THEN
                    CASE WHEN json_type(payload) = 'object' THEN
                        (json_type(payload, '$.account_incarnation') = 'text'
                         AND json_extract(payload, '$.account_incarnation') = ?)
                        OR ((json_type(payload, '$.account_incarnation') IS NULL
                             OR json_type(payload, '$.account_incarnation') = 'null')
                            AND julianday(created_at) <= julianday(?))
                    ELSE 0 END
                ELSE 0 END
                ORDER BY julianday(created_at) DESC, id DESC LIMIT ?""",
                (
                    username,
                    *supported,
                    cutoff.isoformat(),
                    now.isoformat(),
                    account_incarnation,
                    legacy_before.isoformat() if legacy_before is not None else None,
                    max(0, min(500, max_events)),
                ),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return EventSignalLoadResult(status="error")
    signals: list[RecommendationEventSignal] = []
    for row in rows:
        signal = normalize_event_row(row, now=now)
        if signal is None or signal.created_at < cutoff:
            continue
        # Recheck exact datetime precision after SQLite's date arithmetic.
        claim = json.loads(row["payload"]).get("account_incarnation")
        if claim != account_incarnation and not (
            claim is None
            and legacy_before is not None
            and signal.created_at <= legacy_before
        ):
            continue
        signals.append(signal)
    return EventSignalLoadResult(tuple(signals))


def _decay(signal: RecommendationEventSignal, *, now: datetime) -> float:
    age = max(0.0, (now - signal.created_at).total_seconds() / 86400)
    half_life = _EVENT_HALF_LIFE_DAYS.get(signal.event_type, 30.0)
    return math.exp(-math.log(2.0) * age / half_life)


def build_recommendation_profile(
    bookmark_profile: Counter[str],
    signals: Iterable[RecommendationEventSignal],
    *,
    now: datetime,
    event_status: str = "ok",
    interested_papers: Iterable[dict[str, Any]] = (),
    topic_less_papers: Iterable[tuple[dict[str, Any], datetime]] = (),
) -> RecommendationProfile:
    """Hard policy is external. Positive IDs are preferences, never seen/read.

    Optional durable inputs must be resolved public bibliographic papers; topic_less
    timestamps are aware event times. No raw user text or network lookup is used.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    profile = RecommendationProfile(event_status=event_status)
    for term, weight in bookmark_profile.most_common(500):
        if isinstance(weight, (int, float)) and math.isfinite(weight) and weight > 0:
            for token in _tokenize_terms((term,)):
                profile.positive_terms[token] += min(weight, 100.0)
    accepted: set[str] = set()
    weighted_days: set[tuple] = set()
    valid_times = (s for s in signals if s.created_at.tzinfo is not None)
    ordered = sorted(
        valid_times,
        key=lambda s: (
            s.created_at.astimezone(timezone.utc),
            s.event_id or "",
            repr(s),
        ),
        reverse=True,
    )
    for signal in ordered:
        if (
            signal.created_at.tzinfo is None
            or not now - timedelta(days=90) <= signal.created_at <= now
        ):
            continue
        if (
            signal.event_type not in _SUPPORTED
            or signal.source.lower() in _SYNTHETIC_SOURCES
        ):
            continue
        identity = signal.event_id or repr(signal)
        if identity in accepted:
            continue
        accepted.add(identity)
        target = profile.positive_terms
        base = _POSITIVE_EVENT_WEIGHTS.get(signal.event_type, 0.0)
        if signal.event_type == EventType.SCORE_OVERRIDE.value:
            if (
                signal.score is None
                or not math.isfinite(signal.score)
                or not 0 <= signal.score <= 5
            ):
                continue
            base = abs(signal.score - 2.5) * 2
            target = (
                profile.positive_terms
                if signal.score >= 2.5
                else profile.negative_terms
            )
        elif signal.event_type in _NEGATIVE_EVENT_WEIGHTS:
            target, base = (
                profile.negative_terms,
                _NEGATIVE_EVENT_WEIGHTS[signal.event_type],
            )
        profile.event_count += 1
        profile.signal_counts[signal.event_type] += 1
        day = (
            signal.paper_id,
            signal.event_type,
            signal.created_at.astimezone(timezone.utc).date(),
        )
        if base <= 0 or (signal.paper_id and day in weighted_days):
            continue
        if signal.paper_id:
            weighted_days.add(day)
        weight = base * _decay(signal, now=now)
        for term in _tokenize_terms(signal.terms[:MAX_EVENT_TERMS]):
            target[term] += weight
            if signal.event_type == EventType.QUERY_SUBMIT.value:
                profile.query_terms[term] += weight
        if signal.paper_id:
            ids = (
                profile.negative_paper_ids
                if target is profile.negative_terms
                else profile.positive_paper_ids
            )
            ids.add(signal.paper_id)
    from src.recommendation_ranker import _paper_terms

    interested_applied: set[str] = set()
    for paper in interested_papers:
        key = generate_result_key(paper)
        if key not in interested_applied:
            interested_applied.add(key)
            profile.positive_paper_ids.add(key)
            profile.positive_terms.update({term: 5.0 for term in _paper_terms(paper)})
    applied: set[str] = set()
    for paper, occurred_at in topic_less_papers:
        if (
            occurred_at.tzinfo is None
            or not now - timedelta(days=90) <= occurred_at <= now
        ):
            continue
        key = generate_result_key(paper)
        if key in applied:
            continue
        applied.add(key)
        age = (now - occurred_at).total_seconds() / 86400
        weight = 5.0 * math.exp(-math.log(2.0) * age / 30)
        profile.negative_terms.update({term: weight for term in _paper_terms(paper)})
    return profile
