"""Tests for click-based ranking metrics (src/search_eval/click_metrics.py).

This is the only evaluation path in the repo scored from real behaviour rather
than fixtures, so the arithmetic and — more importantly — the click-to-search
attribution have to be pinned.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.events.migrations import ensure_events_db
from src.search_eval.click_metrics import (
    build_impressions,
    build_impressions_from_analytics,
    score_by_variant,
    score_impressions,
)

_NOW = datetime.now(timezone.utc)


@pytest.fixture
def events_db(tmp_path):
    """An events.db with a tiny insert helper, using the production schema."""
    db_path = tmp_path / "events.db"
    ensure_events_db(db_path)

    def _insert(event_type: str, user_id: str, payload: dict, *, minutes_ago: float):
        at = (_NOW - timedelta(minutes=minutes_ago)).isoformat()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO user_events (user_id, event_type, payload, paper_id, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, event_type, json.dumps(payload), payload.get("paper_id"), at),
            )

    def submit(user="u1", qh="q1", *, minutes_ago: float, count=20, cache_hit=False, variant="ce_w=4.0"):
        _insert(
            "query_submit",
            user,
            {
                "query_hash": qh,
                "results_count": count,
                "cache_hit": cache_hit,
                "ranking_variant": variant,
            },
            minutes_ago=minutes_ago,
        )

    def click(user="u1", qh="q1", *, minutes_ago: float, rank=None, paper="p1"):
        payload = {"query_hash": qh, "paper_id": paper}
        if rank is not None:
            payload["rank"] = rank
        _insert("search_click", user, payload, minutes_ago=minutes_ago)

    return db_path, submit, click


# ── attribution ───────────────────────────────────────────────────────


def test_click_attaches_to_the_preceding_search(events_db):
    """A click belongs to the most recent submit by that user for that query."""
    db, submit, click = events_db
    submit(minutes_ago=30)
    submit(minutes_ago=10)
    click(minutes_ago=5, rank=3)

    impressions, orphans = build_impressions(db, days=7)

    assert orphans == 0
    assert len(impressions) == 2
    assert impressions[0].ranked_clicks == []          # the older search
    assert impressions[1].ranked_clicks == [3]         # the one just before the click


def test_click_is_not_attributed_across_users(events_db):
    """Two users running the same query must not share clicks."""
    db, submit, click = events_db
    submit(user="alice", minutes_ago=10)
    click(user="bob", minutes_ago=5, rank=1)

    impressions, orphans = build_impressions(db, days=7)

    assert orphans == 1, "bob's click has no search of his own to attach to"
    assert impressions[0].ranked_clicks == []


def test_click_before_any_search_is_counted_not_dropped(events_db):
    """A click landing before the window's first submit is reported.

    Silently dropping it would show up as a lower CTR rather than as
    "widen the window".
    """
    db, submit, click = events_db
    click(minutes_ago=30, rank=2)
    submit(minutes_ago=10)

    _impressions, orphans = build_impressions(db, days=7)
    assert orphans == 1


def test_events_outside_the_window_are_excluded(events_db):
    db, submit, click = events_db
    submit(minutes_ago=60 * 24 * 40)  # 40 days ago
    submit(minutes_ago=10)
    click(minutes_ago=5, rank=1)

    impressions, _ = build_impressions(db, days=30)
    assert len(impressions) == 1


# ── metrics ───────────────────────────────────────────────────────────


def test_mrr_uses_the_best_click_and_counts_no_click_as_zero(events_db):
    """Two searches, one clicked at rank 2 → MRR@10 = (1/2 + 0) / 2."""
    db, submit, click = events_db
    submit(qh="q1", minutes_ago=20)
    click(qh="q1", minutes_ago=19, rank=4)
    click(qh="q1", minutes_ago=18, rank=2)  # better click on the same impression
    submit(qh="q2", minutes_ago=10)

    impressions, orphans = build_impressions(db, days=7)
    metrics = score_impressions(impressions, k=10, orphan_clicks=orphans)

    assert metrics.impressions == 2
    assert metrics.impressions_with_click == 1
    assert metrics.mrr_at_k == pytest.approx(0.25)          # (0.5 + 0) / 2
    assert metrics.mrr_at_k_over_clicked == pytest.approx(0.5)
    assert metrics.mean_best_rank == pytest.approx(2.0)


def test_clicks_beyond_k_do_not_count_toward_mrr_or_ctr(events_db):
    db, submit, click = events_db
    submit(minutes_ago=10)
    click(minutes_ago=5, rank=25)

    impressions, orphans = build_impressions(db, days=7)
    metrics = score_impressions(impressions, k=10, orphan_clicks=orphans)

    assert metrics.impressions_with_click == 1, "the click still happened"
    assert metrics.mrr_at_k == 0.0
    assert metrics.ctr_at_k == 0.0
    assert metrics.rank_histogram == {25: 1}


def test_ctr_buckets_are_nested(events_db):
    db, submit, click = events_db
    submit(qh="a", minutes_ago=40)
    click(qh="a", minutes_ago=39, rank=1)
    submit(qh="b", minutes_ago=30)
    click(qh="b", minutes_ago=29, rank=4)
    submit(qh="c", minutes_ago=20)
    click(qh="c", minutes_ago=19, rank=9)
    submit(qh="d", minutes_ago=10)

    impressions, orphans = build_impressions(db, days=7)
    metrics = score_impressions(impressions, k=10, orphan_clicks=orphans)

    assert metrics.ctr_at_1 == pytest.approx(0.25)
    assert metrics.ctr_at_5 == pytest.approx(0.5)
    assert metrics.ctr_at_k == pytest.approx(0.75)


def test_rankless_clicks_are_reported_not_guessed(events_db):
    """Older clients send no rank; they must not be scored as rank 1."""
    db, submit, click = events_db
    submit(minutes_ago=10)
    click(minutes_ago=5, rank=None)

    impressions, orphans = build_impressions(db, days=7)
    metrics = score_impressions(impressions, k=10, orphan_clicks=orphans)

    assert metrics.clicks_without_rank == 1
    assert metrics.impressions_with_click == 1
    assert metrics.mrr_at_k == 0.0, "an unpositioned click cannot contribute to MRR"


def test_empty_ledger_scores_zero_without_dividing_by_zero(events_db):
    db, _submit, _click = events_db
    impressions, orphans = build_impressions(db, days=7)
    metrics = score_impressions(impressions, k=10, orphan_clicks=orphans)

    assert metrics.impressions == 0
    assert metrics.mrr_at_k == 0.0
    assert metrics.mrr_at_k_over_clicked == 0.0
    assert metrics.to_dict()["version"] == "click-metrics-v1"


# ── variant comparison ────────────────────────────────────────────────


def test_variants_are_scored_separately(events_db):
    """This split is the point of the harness: it lets one ranking weight be
    compared against another on real clicks."""
    db, submit, click = events_db
    submit(qh="a", minutes_ago=40, variant="ce_w=4.0")
    click(qh="a", minutes_ago=39, rank=1)
    submit(qh="b", minutes_ago=30, variant="ce_w=1.0")
    click(qh="b", minutes_ago=29, rank=8)

    impressions, _ = build_impressions(db, days=7)
    by_variant = score_by_variant(impressions, k=10)

    assert set(by_variant) == {"ce_w=1.0", "ce_w=4.0"}
    assert by_variant["ce_w=4.0"].mrr_at_k > by_variant["ce_w=1.0"].mrr_at_k


def test_cache_hits_are_excluded_from_variant_comparison(events_db):
    """A cached body was ordered by whichever weight was live when it was
    written, so attributing it to the current one would corrupt the readout."""
    db, submit, click = events_db
    submit(qh="a", minutes_ago=20, cache_hit=True, variant="ce_w=4.0")
    click(qh="a", minutes_ago=19, rank=1)
    submit(qh="b", minutes_ago=10, cache_hit=False, variant="ce_w=4.0")

    impressions, _ = build_impressions(db, days=7)

    assert score_by_variant(impressions, k=10)["ce_w=4.0"].impressions == 1
    # ...while the headline metric still counts every impression the user saw.
    assert score_impressions(impressions, k=10).impressions == 2


def test_missing_db_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_impressions(tmp_path / "nope.db", days=7)


# ── first-party analytics source (covers anonymous visitors) ──────────


@pytest.fixture
def analytics_db(tmp_path):
    """An analytics.db with an insert helper, using the production schema."""
    from src.analytics.first_party import AppAnalyticsEvent, record_app_analytics_event

    db_path = tmp_path / "analytics.db"

    def _insert(event_name: str, payload: dict, *, client="client_abcdefgh"):
        record_app_analytics_event(
            db_path,
            AppAnalyticsEvent(
                user_id=None,
                client_id=client,
                session_id="session_abcdefgh",
                event_name=event_name,
                page_path="/",
                payload=payload,
            ),
        )

    return db_path, _insert


def test_analytics_source_joins_clicks_to_their_search(analytics_db):
    """The join key is a random per-search id, not anything about the query."""
    db, insert = analytics_db
    insert("search", {"search_id": "s1", "ranking_variant": "ce_w=0.0"})
    insert("paper_select", {"search_id": "s1", "rank": 2})
    insert("search", {"search_id": "s2", "ranking_variant": "ce_w=0.0"})

    impressions, orphans = build_impressions_from_analytics(db, days=7)
    metrics = score_impressions(impressions, k=10, orphan_clicks=orphans)

    assert metrics.impressions == 2
    assert metrics.impressions_with_click == 1
    assert metrics.mrr_at_k == pytest.approx(0.25)  # (1/2 + 0) / 2


def test_analytics_source_carries_no_query_text(analytics_db):
    """Anything resembling query content must be stripped before storage.

    The consent banner promises search text is not sent; the payload sanitizer
    is what enforces it, so this pins that it still does.
    """
    db, insert = analytics_db
    insert("search", {"search_id": "s1", "query": "대규모 언어 모델", "query_hash": "abc123"})

    conn = sqlite3.connect(db)
    try:
        stored = conn.execute(
            "SELECT payload FROM app_analytics_events WHERE event_name='search'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert "대규모" not in stored
    assert "query_hash" not in stored
    assert "s1" in stored, "the join key itself must survive"


def test_analytics_click_without_a_rank_is_counted_separately(analytics_db):
    db, insert = analytics_db
    insert("search", {"search_id": "s1"})
    insert("paper_select", {"search_id": "s1"})

    impressions, orphans = build_impressions_from_analytics(db, days=7)
    metrics = score_impressions(impressions, k=10, orphan_clicks=orphans)

    assert metrics.clicks_without_rank == 1
    assert metrics.mrr_at_k == 0.0


def test_analytics_click_without_a_matching_search_is_orphaned(analytics_db):
    db, insert = analytics_db
    insert("paper_select", {"search_id": "unknown", "rank": 1})

    _impressions, orphans = build_impressions_from_analytics(db, days=7)
    assert orphans == 1


def test_analytics_variants_are_comparable(analytics_db):
    db, insert = analytics_db
    insert("search", {"search_id": "a", "ranking_variant": "ce_w=0.0"})
    insert("paper_select", {"search_id": "a", "rank": 1})
    insert("search", {"search_id": "b", "ranking_variant": "ce_w=2.0"})
    insert("paper_select", {"search_id": "b", "rank": 9})

    impressions, _ = build_impressions_from_analytics(db, days=7)
    by_variant = score_by_variant(impressions, k=10)

    assert by_variant["ce_w=0.0"].mrr_at_k > by_variant["ce_w=2.0"].mrr_at_k


def test_analytics_missing_db_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_impressions_from_analytics(tmp_path / "nope.db", days=7)
