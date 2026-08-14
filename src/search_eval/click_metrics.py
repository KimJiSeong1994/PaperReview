"""Ranking quality measured from real search clicks in ``data/events.db``.

Every other evaluation path in this package scores *fixtures*: deterministic
stand-ins that prove the approval pipeline works but say nothing about whether
search actually got better. This module is the missing behavioural signal —
it reads the QUERY_SUBMIT / SEARCH_CLICK ledger the API already writes and
computes MRR and CTR from where users clicked.

It is read-only and offline: no network, no LLM, no writes to the ledger.

Attribution
-----------
A SEARCH_CLICK is attributed to the most recent QUERY_SUBMIT by the same user
with the same ``query_hash``. ``query_hash`` is a 12-hex-char prefix of
sha256(query); collisions are possible in principle, but attribution is also
scoped per user, so a collision would additionally require one person to have
run both colliding queries inside the window.

Clicks emitted before ``rank`` was recorded (or by an older client) carry no
position. They are counted in ``clicks_without_rank`` rather than silently
treated as rank 1 or dropped from the denominators.

Usage
-----
    python -m src.search_eval.click_metrics --days 30
    python -m src.search_eval.click_metrics --days 30 --by-variant
"""

from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_EVENTS_DB = Path("data/events.db")
DEFAULT_ANALYTICS_DB = Path("data/analytics.db")

_QUERY_SUBMIT = "query_submit"
_SEARCH_CLICK = "search_click"

# First-party analytics event names carrying the same signal for everyone,
# signed-in or not. ``search`` is the impression, ``paper_select`` the click.
_ANALYTICS_IMPRESSION = "search"
_ANALYTICS_CLICK = "paper_select"


@dataclass
class Impression:
    """One search result set a user was shown, with the clicks it earned."""

    user_id: str
    query_hash: str
    at: datetime
    results_count: int
    cache_hit: bool
    ranking_variant: str
    ranked_clicks: list[int] = field(default_factory=list)
    unranked_clicks: int = 0

    @property
    def best_rank(self) -> int | None:
        """Highest-placed click (lowest rank number), or None if never clicked."""
        return min(self.ranked_clicks) if self.ranked_clicks else None


@dataclass(frozen=True)
class ClickMetrics:
    """Aggregate ranking quality over a set of impressions."""

    impressions: int
    impressions_with_click: int
    clicks_without_rank: int
    orphan_clicks: int
    mrr_at_k: float
    mrr_at_k_over_clicked: float
    ctr_at_1: float
    ctr_at_5: float
    ctr_at_k: float
    mean_best_rank: float
    rank_histogram: dict[int, int]
    k: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "click-metrics-v1",
            "k": self.k,
            "impressions": self.impressions,
            "impressions_with_click": self.impressions_with_click,
            "clicks_without_rank": self.clicks_without_rank,
            "orphan_clicks": self.orphan_clicks,
            "mrr_at_k": round(self.mrr_at_k, 4),
            "mrr_at_k_over_clicked": round(self.mrr_at_k_over_clicked, 4),
            "ctr_at_1": round(self.ctr_at_1, 4),
            "ctr_at_5": round(self.ctr_at_5, 4),
            "ctr_at_k": round(self.ctr_at_k, 4),
            "mean_best_rank": round(self.mean_best_rank, 3),
            "rank_histogram": {str(r): c for r, c in sorted(self.rank_histogram.items())},
        }


def _parse_ts(raw: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _read_events(db_path: Path, since: datetime) -> list[tuple[str, str, dict[str, Any], datetime]]:
    """Return (event_type, user_id, payload, created_at) rows in the window."""
    if not db_path.exists():
        raise FileNotFoundError(f"events db not found: {db_path}")

    # Read-only URI so a running server's ledger can never be mutated from here.
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT event_type, user_id, payload, created_at
              FROM user_events
             WHERE event_type IN (?, ?)
               AND created_at >= ?
             ORDER BY created_at ASC
            """,
            (_QUERY_SUBMIT, _SEARCH_CLICK, since.isoformat()),
        ).fetchall()
    finally:
        conn.close()

    parsed: list[tuple[str, str, dict[str, Any], datetime]] = []
    for event_type, user_id, payload_raw, created_at in rows:
        at = _parse_ts(created_at)
        if at is None:
            continue
        try:
            payload = json.loads(payload_raw) if payload_raw else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        parsed.append((event_type, user_id, payload, at))
    return parsed


def build_impressions(
    db_path: Path = DEFAULT_EVENTS_DB,
    *,
    days: int = 30,
    include_cache_hits: bool = True,
) -> tuple[list[Impression], int]:
    """Join submits and clicks into impressions. Returns (impressions, orphan_clicks).

    ``orphan_clicks`` are clicks with no preceding submit in the window — the
    normal cause is a click that lands just after the window's left edge. They
    are reported rather than dropped so a large count is visible as "widen the
    window", not mistaken for a low CTR.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    events = _read_events(db_path, since)

    by_key: dict[tuple[str, str], list[Impression]] = defaultdict(list)
    clicks: list[tuple[str, str, datetime, int | None]] = []

    for event_type, user_id, payload, at in events:
        query_hash = payload.get("query_hash")
        if not isinstance(query_hash, str) or not query_hash:
            continue
        if event_type == _QUERY_SUBMIT:
            by_key[(user_id, query_hash)].append(
                Impression(
                    user_id=user_id,
                    query_hash=query_hash,
                    at=at,
                    results_count=int(payload.get("results_count") or 0),
                    cache_hit=bool(payload.get("cache_hit")),
                    ranking_variant=str(payload.get("ranking_variant") or "unknown"),
                )
            )
        else:
            rank = payload.get("rank")
            clicks.append(
                (user_id, query_hash, at, int(rank) if isinstance(rank, int) and rank >= 1 else None)
            )

    orphan_clicks = 0
    for user_id, query_hash, at, rank in clicks:
        candidates = by_key.get((user_id, query_hash))
        if not candidates:
            orphan_clicks += 1
            continue
        # Latest submit at or before the click. Submits arrive in ascending
        # order from the query above, so their timestamps are already sorted.
        idx = bisect.bisect_right([imp.at for imp in candidates], at) - 1
        if idx < 0:
            orphan_clicks += 1
            continue
        impression = candidates[idx]
        if rank is None:
            impression.unranked_clicks += 1
        else:
            impression.ranked_clicks.append(rank)

    impressions = [imp for group in by_key.values() for imp in group]
    if not include_cache_hits:
        impressions = [imp for imp in impressions if not imp.cache_hit]
    impressions.sort(key=lambda imp: imp.at)
    return impressions, orphan_clicks


def build_impressions_from_analytics(
    db_path: Path = DEFAULT_ANALYTICS_DB,
    *,
    days: int = 30,
) -> tuple[list[Impression], int]:
    """Build impressions from the first-party analytics ledger.

    That ledger is where the volume is: ``user_events`` only records signed-in
    users, so it held zero clicks. Analytics covers everyone who consented,
    anonymous included, and carries no query text — impressions and clicks are
    joined by a random per-search ``search_id`` rather than by anything derived
    from what was typed.

    A row without a ``search_id`` predates that field and is skipped rather
    than guessed at; the count comes back as ``orphan_clicks`` for clicks.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"analytics db not found: {db_path}")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT event_name, client_id, payload, created_at
              FROM app_analytics_events
             WHERE event_name IN (?, ?)
               AND created_at >= ?
             ORDER BY created_at ASC
            """,
            (_ANALYTICS_IMPRESSION, _ANALYTICS_CLICK, since.isoformat()),
        ).fetchall()
    finally:
        conn.close()

    by_search: dict[str, Impression] = {}
    clicks: list[tuple[str, int | None]] = []
    orphan_clicks = 0

    for event_name, client_id, payload_raw, created_at in rows:
        at = _parse_ts(created_at)
        if at is None:
            continue
        try:
            payload = json.loads(payload_raw) if payload_raw else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        search_id = payload.get("search_id")
        if not isinstance(search_id, str) or not search_id:
            continue

        if event_name == _ANALYTICS_IMPRESSION:
            # A repeated search_id would mean a client reused an id; keep the
            # first so clicks are not double-counted against two impressions.
            by_search.setdefault(search_id, Impression(
                user_id=client_id or "anonymous",
                query_hash=search_id,
                at=at,
                results_count=0,
                cache_hit=False,
                ranking_variant=str(payload.get("ranking_variant") or "unknown"),
            ))
        else:
            rank = payload.get("rank")
            clicks.append(
                (search_id, int(rank) if isinstance(rank, int) and rank >= 1 else None)
            )

    for search_id, rank in clicks:
        impression = by_search.get(search_id)
        if impression is None:
            orphan_clicks += 1
            continue
        if rank is None:
            impression.unranked_clicks += 1
        else:
            impression.ranked_clicks.append(rank)

    impressions = sorted(by_search.values(), key=lambda imp: imp.at)
    return impressions, orphan_clicks


def score_impressions(
    impressions: list[Impression],
    *,
    k: int = 10,
    orphan_clicks: int = 0,
) -> ClickMetrics:
    """Compute MRR@k and CTR@k over *impressions*.

    ``mrr_at_k`` counts an impression with no click within k as 0, which is the
    standard definition and the one to watch over time. ``mrr_at_k_over_clicked``
    conditions on there being a click, separating "the ranking put the right
    paper high" from "users clicked at all" — the two move independently and a
    single number hides which one changed.
    """
    if k < 1:
        raise ValueError("k must be >= 1")

    total = len(impressions)
    reciprocal_sum = 0.0
    clicked_within_k = 0
    hits_at_1 = 0
    hits_at_5 = 0
    best_rank_sum = 0
    best_rank_n = 0
    histogram: Counter[int] = Counter()
    unranked = 0
    with_click = 0

    for imp in impressions:
        unranked += imp.unranked_clicks
        if imp.ranked_clicks or imp.unranked_clicks:
            with_click += 1
        for rank in imp.ranked_clicks:
            histogram[rank] += 1
        best = imp.best_rank
        if best is None:
            continue
        best_rank_sum += best
        best_rank_n += 1
        if best <= k:
            reciprocal_sum += 1.0 / best
            clicked_within_k += 1
        if best <= 1:
            hits_at_1 += 1
        if best <= 5:
            hits_at_5 += 1

    def _ratio(numerator: float, denominator: int) -> float:
        return numerator / denominator if denominator else 0.0

    return ClickMetrics(
        impressions=total,
        impressions_with_click=with_click,
        clicks_without_rank=unranked,
        orphan_clicks=orphan_clicks,
        mrr_at_k=_ratio(reciprocal_sum, total),
        mrr_at_k_over_clicked=_ratio(reciprocal_sum, clicked_within_k),
        ctr_at_1=_ratio(hits_at_1, total),
        ctr_at_5=_ratio(hits_at_5, total),
        ctr_at_k=_ratio(clicked_within_k, total),
        mean_best_rank=_ratio(best_rank_sum, best_rank_n),
        rank_histogram=dict(histogram),
        k=k,
    )


def score_by_variant(
    impressions: list[Impression], *, k: int = 10
) -> dict[str, ClickMetrics]:
    """Split metrics by ``ranking_variant`` so two rankers can be compared.

    Cache hits are excluded: their order was produced by whichever variant was
    live when the entry was written, not the one recorded on the impression.
    """
    grouped: dict[str, list[Impression]] = defaultdict(list)
    for imp in impressions:
        if imp.cache_hit:
            continue
        grouped[imp.ranking_variant].append(imp)
    return {
        variant: score_impressions(group, k=k)
        for variant, group in sorted(grouped.items())
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--source",
        choices=("analytics", "events"),
        default="analytics",
        help=(
            "analytics (default) reads the consented first-party ledger, which "
            "covers anonymous visitors; events reads user_events, which only "
            "records signed-in users"
        ),
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--exclude-cache-hits",
        action="store_true",
        help="score only freshly ranked impressions",
    )
    parser.add_argument(
        "--by-variant",
        action="store_true",
        help="break results down by ranking_variant (always excludes cache hits)",
    )
    args = parser.parse_args(argv)

    if args.source == "analytics":
        impressions, orphans = build_impressions_from_analytics(
            args.db or DEFAULT_ANALYTICS_DB, days=args.days
        )
    else:
        impressions, orphans = build_impressions(
            args.db or DEFAULT_EVENTS_DB,
            days=args.days,
            include_cache_hits=not args.exclude_cache_hits,
        )
    if args.by_variant:
        report = {
            variant: metrics.to_dict()
            for variant, metrics in score_by_variant(impressions, k=args.k).items()
        }
    else:
        report = score_impressions(impressions, k=args.k, orphan_clicks=orphans).to_dict()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
