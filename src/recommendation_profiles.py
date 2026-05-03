"""Privacy-safe profile signals for daily paper recommendations.

This module is intentionally deterministic and dependency-light. It consumes
only bounded recommendation event signals (for example normalized terms and
paper identifiers) and never requires raw queries, abstracts, or LLM Wiki
markdown as ranker input.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.events.event_types import EventType
from src.recommendations_artifacts import safe_str

EVENT_SCHEMA_VERSION = "recommendation_event_contract_v1"
MAX_EVENT_TERMS = 8
DEFAULT_SINCE_DAYS = 90
_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣_\-]{1,48}")
_SYNTHETIC_SOURCES = {"test", "e2e", "synthetic"}

_POSITIVE_EVENT_WEIGHTS: dict[str, float] = {
    EventType.REVIEW_CREATE.value: 10.0,
    EventType.REVIEW_UPDATE.value: 6.0,
    EventType.BOOKMARK_ADD.value: 8.0,
    EventType.HIGHLIGHT_CREATE.value: 7.0,
    EventType.HIGHLIGHT_UPDATE.value: 4.0,
    EventType.PAPER_OPEN.value: 3.0,
    EventType.SEARCH_CLICK.value: 2.0,
    EventType.QUERY_SUBMIT.value: 1.5,
    EventType.RECOMMENDATION_FEEDBACK.value: 4.0,
}
_NEGATIVE_EVENT_WEIGHTS: dict[str, float] = {
    EventType.BOOKMARK_REMOVE.value: 6.0,
    EventType.HIGHLIGHT_DELETE.value: 2.0,
    EventType.RECOMMENDATION_READ.value: 1.0,
}
_EVENT_HALF_LIFE_DAYS: dict[str, float] = {
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
    EventType.RECOMMENDATION_FEEDBACK.value: 90.0,
    EventType.RECOMMENDATION_READ.value: 30.0,
}


@dataclass(frozen=True)
class RecommendationEventSignal:
    """Normalized ranker-safe event signal.

    ``terms`` must already be bounded/sanitized. Raw query or abstract text is
    intentionally not part of this contract.
    """

    event_type: str
    created_at: datetime
    source: str = "app"
    terms: tuple[str, ...] = ()
    paper_id: str | None = None
    bookmark_id: str | None = None
    score: float | None = None
    feedback_type: str | None = None


@dataclass
class RecommendationProfile:
    """Ephemeral per-user profile used only inside the daily batch."""

    positive_terms: Counter[str] = field(default_factory=Counter)
    negative_terms: Counter[str] = field(default_factory=Counter)
    query_terms: Counter[str] = field(default_factory=Counter)
    positive_paper_ids: set[str] = field(default_factory=set)
    negative_paper_ids: set[str] = field(default_factory=set)
    signal_counts: Counter[str] = field(default_factory=Counter)

    def public_summary(self, *, bookmark_count: int, fallback_recent: bool) -> dict[str, Any]:
        return {
            "bookmark_count": bookmark_count,
            "event_count": int(sum(self.signal_counts.values())),
            "top_terms": [term for term, _ in self.positive_terms.most_common(12)],
            "fallback_recent": fallback_recent,
            "signal_counts": dict(self.signal_counts),
            "profile_contract": EVENT_SCHEMA_VERSION,
        }


def _parse_datetime(value: str, *, default: datetime) -> datetime:
    raw = safe_str(value)
    if not raw:
        return default
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return default
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _tokenize_terms(values: Iterable[Any]) -> tuple[str, ...]:
    terms: list[str] = []
    for value in values:
        text = safe_str(value).lower()
        if not text:
            continue
        for token in _TOKEN_RE.findall(text):
            clean = token.strip("_-").lower()
            if len(clean) < 2 or clean.isdigit():
                continue
            if clean not in terms:
                terms.append(clean)
            if len(terms) >= MAX_EVENT_TERMS:
                return tuple(terms)
    return tuple(terms)


def _payload_terms(payload: dict[str, Any]) -> tuple[str, ...]:
    # Privacy gate: consume only explicit bounded terms. Do not parse raw
    # query/title/abstract fields into the ranker profile.
    for key in ("normalized_terms", "query_terms", "terms", "topics", "categories"):
        value = payload.get(key)
        if isinstance(value, list):
            terms = _tokenize_terms(value[:MAX_EVENT_TERMS])
            if terms:
                return terms
        elif isinstance(value, str):
            terms = _tokenize_terms(value.split()[:MAX_EVENT_TERMS])
            if terms:
                return terms
    return ()


def _payload_score(payload: dict[str, Any]) -> float | None:
    try:
        score = float(payload.get("score"))
    except (TypeError, ValueError):
        return None
    if not 0.0 <= score <= 5.0:
        return None
    return score


def normalize_event_row(row: sqlite3.Row | dict[str, Any], *, now: datetime) -> RecommendationEventSignal | None:
    event_type = safe_str(row["event_type"] if isinstance(row, sqlite3.Row) else row.get("event_type"))
    if event_type not in _POSITIVE_EVENT_WEIGHTS and event_type not in _NEGATIVE_EVENT_WEIGHTS and event_type != EventType.SCORE_OVERRIDE.value:
        return None

    source = safe_str(row["source"] if isinstance(row, sqlite3.Row) else row.get("source")) or "app"
    if source.lower() in _SYNTHETIC_SOURCES:
        return None

    payload_raw = row["payload"] if isinstance(row, sqlite3.Row) else row.get("payload")
    try:
        payload = json.loads(payload_raw) if isinstance(payload_raw, str) else dict(payload_raw or {})
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    created_at = _parse_datetime(row["created_at"] if isinstance(row, sqlite3.Row) else row.get("created_at"), default=now)
    if created_at > now:
        return None

    top_level_paper_id = row["paper_id"] if isinstance(row, sqlite3.Row) else row.get("paper_id")
    payload_paper_id = payload.get("paper_id")
    bookmark_id = safe_str(payload.get("bookmark_id")) or None
    paper_id = safe_str(payload_paper_id) or safe_str(top_level_paper_id) or None
    if event_type in {EventType.BOOKMARK_ADD.value, EventType.BOOKMARK_REMOVE.value}:
        bookmark_id = bookmark_id or safe_str(top_level_paper_id) or None
        # Existing bookmark routes historically put bookmark_id into the
        # top-level paper_id column. Trust payload.paper_id only for paper identity.
        paper_id = safe_str(payload_paper_id) or None

    terms = _payload_terms(payload)
    score = _payload_score(payload) if event_type == EventType.SCORE_OVERRIDE.value else None
    feedback_type = safe_str(payload.get("feedback_type") or payload.get("action")) or None
    if not terms and not paper_id and score is None and feedback_type is None:
        return None

    return RecommendationEventSignal(
        event_type=event_type,
        created_at=created_at,
        source=source,
        terms=terms,
        paper_id=paper_id,
        bookmark_id=bookmark_id,
        score=score,
        feedback_type=feedback_type,
    )


def load_user_event_signals(
    events_db: Path | None,
    username: str,
    *,
    now: datetime,
    since_days: int = DEFAULT_SINCE_DAYS,
    max_events: int = 500,
) -> list[RecommendationEventSignal]:
    if events_db is None or not events_db.exists():
        return []
    cutoff = now.timestamp() - max(1, since_days) * 86400
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    uri = f"file:{events_db.resolve()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return []
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT user_id, event_type, payload, paper_id, created_at, source
            FROM user_events
            WHERE user_id = ? AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (username, cutoff_iso, max_events),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    signals: list[RecommendationEventSignal] = []
    for row in rows:
        signal = normalize_event_row(row, now=now)
        if signal is not None:
            signals.append(signal)
    return signals


def _decay(signal: RecommendationEventSignal, *, now: datetime) -> float:
    age_days = max(0.0, (now - signal.created_at).total_seconds() / 86400.0)
    half_life = _EVENT_HALF_LIFE_DAYS.get(signal.event_type, 30.0)
    return math.exp(-age_days / half_life)


def build_recommendation_profile(
    bookmark_profile: Counter[str],
    signals: Iterable[RecommendationEventSignal],
    *,
    now: datetime,
) -> RecommendationProfile:
    profile = RecommendationProfile(positive_terms=Counter(bookmark_profile))
    if bookmark_profile:
        profile.signal_counts["bookmark"] += 1

    for signal in signals:
        decay = _decay(signal, now=now)
        if signal.event_type == EventType.SCORE_OVERRIDE.value and signal.score is not None:
            base = abs(signal.score - 2.5) * 2.0
            target = profile.positive_terms if signal.score >= 2.5 else profile.negative_terms
            bucket = "score_positive" if signal.score >= 2.5 else "score_negative"
        elif signal.event_type == EventType.RECOMMENDATION_FEEDBACK.value:
            negative_feedback = {"not_interested", "already_seen", "less_like_this", "topic_less", "dismissed"}
            positive_feedback = {"interested", "more_like_this", "helpful"}
            if signal.feedback_type in negative_feedback:
                base = 5.0
                target = profile.negative_terms
                bucket = "negative_feedback"
            elif signal.feedback_type in positive_feedback:
                base = 5.0
                target = profile.positive_terms
                bucket = "positive_feedback"
            else:
                base = 0.0
                target = profile.positive_terms
                bucket = "ignored_feedback"
        elif signal.event_type == EventType.RECOMMENDATION_READ.value:
            if signal.feedback_type == "dismissed":
                base = _NEGATIVE_EVENT_WEIGHTS[signal.event_type]
                target = profile.negative_terms
                bucket = "negative_event"
            else:
                base = 0.0
                target = profile.positive_terms
                bucket = "read_event"
        elif signal.event_type in _NEGATIVE_EVENT_WEIGHTS:
            base = _NEGATIVE_EVENT_WEIGHTS[signal.event_type]
            target = profile.negative_terms
            bucket = "negative_event"
        else:
            base = _POSITIVE_EVENT_WEIGHTS.get(signal.event_type, 0.0)
            target = profile.positive_terms
            bucket = "positive_event"

        if base <= 0:
            continue
        weight = base * decay
        for term in signal.terms:
            target[term] += weight
            if signal.event_type == EventType.QUERY_SUBMIT.value:
                profile.query_terms[term] += weight
        if signal.paper_id:
            if target is profile.negative_terms:
                profile.negative_paper_ids.add(signal.paper_id.lower())
            else:
                profile.positive_paper_ids.add(signal.paper_id.lower())
        profile.signal_counts[bucket] += 1
        profile.signal_counts[signal.event_type] += 1
    return profile
