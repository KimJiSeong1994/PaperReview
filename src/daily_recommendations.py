"""Daily per-user paper recommendation artifact generation.

The notification API intentionally reads immutable ``raw.json`` artifacts.
This module owns the local, dependency-light producer for those artifacts so
production can refresh every user's recommendations on a daily schedule.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.events.feature_flags import PROFILE_RANKER_ENABLED, _db_path, is_enabled
from src.recommendation_profiles import (
    build_recommendation_profile,
    load_user_event_signals,
)
from src.recommendation_ranker import mmr_rerank, rank_paper_v2, reason_v2
from src.recommendations_artifacts import paper_id, safe_str


DEFAULT_LIMIT = 12
DEFAULT_MIN_SCORE = 0.6
SCORING_MODE = "daily_content_v1"
SCORING_MODE_V2 = "daily_profile_ranker_v2"
PROFILE_RANKER_GLOBAL_ENABLED = "PROFILE_RANKER_GLOBAL_ENABLED"
PROFILE_RANKER_ALLOWED_USERS = "PROFILE_RANKER_ALLOWED_USERS"
_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]{2,}")
_SAFE_USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "using",
    "based",
    "towards",
    "through",
    "paper",
    "study",
    "analysis",
    "method",
    "methods",
    "model",
    "models",
    "data",
    "learning",
    "research",
    "this",
    "that",
    "into",
    "between",
    "under",
    "over",
    "via",
    "및",
    "으로",
    "에서",
    "대한",
    "논문",
    "연구",
    "분석",
}


@dataclass(frozen=True)
class UserRecord:
    username: str
    role: str | None = None


@dataclass(frozen=True)
class BookmarkRecord:
    username: str
    topic: str
    title: str
    papers: list[dict[str, Any]]
    report: str = ""
    notes: str = ""




def _run_datetime(run_at: str | None) -> datetime:
    if not run_at:
        return datetime.now(timezone.utc)
    raw = run_at[:-1] + "+00:00" if run_at.endswith("Z") else run_at
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _allowed_profile_ranker_users() -> set[str]:
    raw = os.getenv(PROFILE_RANKER_ALLOWED_USERS, "")
    return {part.strip() for part in raw.split(",") if part.strip()}




def _profile_ranker_per_user_override(username: str) -> bool | None:
    try:
        conn = sqlite3.connect(str(_db_path()))
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT enabled FROM feature_flags WHERE flag = ? AND username = ?",
            (PROFILE_RANKER_ENABLED, username),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return bool(row[0]) if row is not None else None

def _profile_ranker_enabled(username: str) -> bool:
    # Safety guard: v2 rollout requires either explicit per-user enablement or
    # a second global rollout gate. A global DB/env flag alone is insufficient.
    global_gate = os.getenv(PROFILE_RANKER_GLOBAL_ENABLED, "").strip().lower() in {"true", "1", "yes"}
    allowed_users = _allowed_profile_ranker_users()
    per_user_override = _profile_ranker_per_user_override(username)
    if per_user_override is not None:
        return bool(per_user_override)
    if username in allowed_users:
        return is_enabled(PROFILE_RANKER_ENABLED, username=username)
    return global_gate and is_enabled(PROFILE_RANKER_ENABLED, username=username)


def _score_stats(scores: list[float], *, fallback_recent: bool) -> dict[str, dict[str, float]]:
    mean = sum(scores) / len(scores) if scores else 0.0
    return {
        "daily": {
            "n": len(scores),
            "mean": round(mean, 3),
            "min": min(scores) if scores else 0.0,
            "max": max(scores) if scores else 0.0,
            "spread": round((max(scores) - min(scores)), 3) if scores else 0.0,
            "fallback_recent_rate": 1.0 if fallback_recent else 0.0,
        }
    }

def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in _TOKEN_RE.findall(text)
        if token.lower() not in _STOPWORDS and not token.isdigit()
    ]


def _is_safe_username(username: str) -> bool:
    return bool(_SAFE_USERNAME_RE.fullmatch(username))


def _weighted_update(counter: Counter[str], text: str, weight: int) -> None:
    for token in _tokens(text):
        counter[token] += weight


def _safe_json_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def load_users(users_db: Path) -> list[UserRecord]:
    if not users_db.exists():
        return []
    with _connect_readonly(users_db) as conn:
        rows = conn.execute("SELECT username, role FROM users ORDER BY username").fetchall()
    users: list[UserRecord] = []
    for row in rows:
        username = safe_str(row["username"])
        if not username:
            continue
        if not _is_safe_username(username):
            continue
        users.append(UserRecord(username=username, role=safe_str(row["role"]) or None))
    return users


def load_bookmarks(bookmarks_db: Path) -> list[BookmarkRecord]:
    if not bookmarks_db.exists():
        return []
    with _connect_readonly(bookmarks_db) as conn:
        rows = conn.execute(
            """
            SELECT username, topic, title, papers, report, notes
            FROM bookmarks
            WHERE username IS NOT NULL AND username != ''
            ORDER BY created_at DESC
            """
        ).fetchall()
    bookmarks: list[BookmarkRecord] = []
    for row in rows:
        username = safe_str(row["username"])
        if not username:
            continue
        if not _is_safe_username(username):
            continue
        bookmarks.append(
            BookmarkRecord(
                username=username,
                topic=safe_str(row["topic"]),
                title=safe_str(row["title"]),
                papers=_safe_json_list(row["papers"]),
                report=safe_str(row["report"]),
                notes=safe_str(row["notes"]),
            )
        )
    return bookmarks




def load_related_paper_signals(report_json: Path | None) -> dict[str, dict[str, Any]]:
    if report_json is None or not report_json.exists():
        return {}
    try:
        raw = json.loads(report_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    papers = raw.get("top_papers") if isinstance(raw, dict) else None
    if not isinstance(papers, list):
        return {}
    signals: dict[str, dict[str, Any]] = {}
    for item in papers:
        if not isinstance(item, dict):
            continue
        identity = safe_str(item.get("paper_id")).lower()
        if not identity:
            identity = safe_str(item.get("title")).lower()
        if not identity:
            continue
        signals[identity] = {
            "related_review_score": item.get("score"),
            "related_query": safe_str(item.get("query")),
            "related_reasons": item.get("reasons") if isinstance(item.get("reasons"), list) else [],
        }
    return signals


def _with_related_signal(paper: dict[str, Any], related_signals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not related_signals:
        return paper
    for identity in _paper_identity_values(paper):
        signal = related_signals.get(identity.lower())
        if signal:
            enriched = dict(paper)
            enriched.update(signal)
            if not safe_str(enriched.get("source")):
                enriched["source"] = "related-papers"
            return enriched
    return paper

def load_papers(papers_json: Path) -> list[dict[str, Any]]:
    if not papers_json.exists():
        return []
    try:
        raw = json.loads(papers_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    papers = raw.get("papers") if isinstance(raw, dict) else raw
    if not isinstance(papers, list):
        return []
    return [paper for paper in papers if isinstance(paper, dict) and safe_str(paper.get("title"))]


def _paper_identity_values(item: dict[str, Any]) -> set[str]:
    values = {paper_id(item).lower()}
    for key in ("title", "arxiv_id", "doi", "url", "pdf_url"):
        value = safe_str(item.get(key)).lower()
        if value:
            values.add(value)
    return values


def _user_profile(bookmarks: list[BookmarkRecord]) -> tuple[Counter[str], set[str]]:
    profile: Counter[str] = Counter()
    seen_papers: set[str] = set()
    for bookmark in bookmarks:
        _weighted_update(profile, bookmark.topic, 5)
        _weighted_update(profile, bookmark.title, 4)
        _weighted_update(profile, bookmark.notes, 2)
        _weighted_update(profile, bookmark.report[:4000], 1)
        for paper in bookmark.papers:
            _weighted_update(profile, safe_str(paper.get("title")), 7)
            _weighted_update(profile, " ".join(map(str, paper.get("authors") or [])), 1)
            seen_papers.update(_paper_identity_values(paper))
    return profile, seen_papers


def _paper_text(paper: dict[str, Any]) -> str:
    authors = paper.get("authors") if isinstance(paper.get("authors"), list) else []
    categories = paper.get("categories") if isinstance(paper.get("categories"), list) else []
    return " ".join(
        [
            safe_str(paper.get("title")),
            safe_str(paper.get("abstract")),
            safe_str(paper.get("search_query")),
            " ".join(map(str, authors[:8])),
            " ".join(map(str, categories)),
        ]
    )


def _year_value(paper: dict[str, Any]) -> int | None:
    for key in ("year", "published_date", "updated_date", "collected_at"):
        value = safe_str(paper.get(key))
        match = re.search(r"(19|20)\d{2}", value)
        if match:
            return int(match.group(0))
    return None


def _recency_bonus(year: int | None, *, current_year: int) -> float:
    if year is None:
        return 0.15
    age = max(0, current_year - year)
    return max(0.0, 1.0 - min(age, 10) * 0.1)


def _score_paper(
    paper: dict[str, Any],
    profile: Counter[str],
    *,
    current_year: int,
    fallback_recent: bool,
) -> tuple[float, list[str]]:
    terms = _tokens(_paper_text(paper))
    term_counts = Counter(terms)
    overlap = 0.0
    matched: list[str] = []
    for token, count in term_counts.items():
        weight = profile.get(token, 0)
        if weight <= 0:
            continue
        overlap += math.log1p(weight) * min(count, 3)
        matched.append(token)

    year = _year_value(paper)
    recency = _recency_bonus(year, current_year=current_year)
    source_bonus = 0.2 if safe_str(paper.get("pdf_url")) else 0.0
    source_bonus += 0.1 if safe_str(paper.get("doi")) or safe_str(paper.get("arxiv_id")) else 0.0

    if fallback_recent:
        return recency + source_bonus, []
    if overlap <= 0:
        return recency * 0.25 + source_bonus, []
    return overlap + recency + source_bonus, matched


def _reason(paper: dict[str, Any], matched: list[str], *, fallback_recent: bool) -> str:
    if fallback_recent:
        return "아직 개인화 신호가 적어 최근 수집 논문을 우선 추천했습니다."
    if matched:
        keywords = ", ".join(matched[:4])
        return f"사용자의 북마크/주제 신호와 겹치는 키워드가 있습니다: {keywords}."
    return "최근 수집된 논문 중 사용자 관심사와 함께 검토할 후보입니다."


def _notification_row(
    paper: dict[str, Any],
    *,
    score: float,
    rank: int,
    reason: str,
) -> dict[str, Any]:
    year = _year_value(paper)
    authors = paper.get("authors") if isinstance(paper.get("authors"), list) else []
    return {
        "paper_id": paper_id(paper),
        "title": safe_str(paper.get("title")),
        "authors": [safe_str(author) for author in authors if safe_str(author)][:6],
        "year": year,
        "venue": safe_str(paper.get("journal_ref")) or safe_str(paper.get("source")),
        "source": safe_str(paper.get("source")),
        "url": safe_str(paper.get("url")),
        "pdf_url": safe_str(paper.get("pdf_url")),
        "doi": safe_str(paper.get("doi")),
        "arxiv_id": safe_str(paper.get("arxiv_id")),
        "score": round(score, 3),
        "rank": rank,
        "reason": reason,
    }


def _recommend_for_user_v1(
    username: str,
    user_bookmarks: list[BookmarkRecord],
    papers: list[dict[str, Any]],
    *,
    limit: int,
    min_score: float,
    run_at: str,
    now: datetime,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    current_year = now.year
    profile, seen_papers = _user_profile(user_bookmarks)
    fallback_recent = not profile

    scored: list[tuple[float, list[str], dict[str, Any]]] = []
    for paper in papers:
        if _paper_identity_values(paper) & seen_papers:
            continue
        score, matched = _score_paper(
            paper,
            profile,
            current_year=current_year,
            fallback_recent=fallback_recent,
        )
        if score >= min_score or fallback_recent:
            scored.append((score, matched, paper))

    scored.sort(key=lambda item: (item[0], _year_value(item[2]) or 0, safe_str(item[2].get("title"))), reverse=True)
    recommendations = [
        _notification_row(
            paper,
            score=score,
            rank=idx,
            reason=_reason(paper, matched, fallback_recent=fallback_recent),
        )
        for idx, (score, matched, paper) in enumerate(scored[:limit], start=1)
    ]
    scores = [item["score"] for item in recommendations]
    personalization_state = "fallback" if fallback_recent else "ready"
    artifact = {
        "run_at": run_at,
        "user_id": username,
        "scoring_mode": SCORING_MODE,
        "personalization_state": personalization_state,
        "fallback_reason": fallback_reason or ("no_bookmarks" if fallback_recent else None),
        "next_best_action": "관심 논문을 북마크하면 추천 정확도가 올라갑니다." if fallback_recent else None,
        "profile": {
            "bookmark_count": len(user_bookmarks),
            "top_terms": [term for term, _ in profile.most_common(12)],
            "fallback_recent": fallback_recent,
        },
        "score_stats": _score_stats(scores, fallback_recent=fallback_recent),
        "variants": {"daily": recommendations},
    }
    return artifact


def _notification_row_v2(
    ranked: Any,
    *,
    rank: int,
    fallback_recent: bool,
) -> dict[str, Any]:
    row = _notification_row(
        ranked.paper,
        score=ranked.score,
        rank=rank,
        reason=reason_v2(ranked, fallback_recent=fallback_recent),
    )
    row.update(
        {
            "raw_score": ranked.raw_score,
            "normalized_score": ranked.normalized_score,
            "score_breakdown": ranked.score_breakdown,
            "matched_terms": ranked.matched_terms[:5],
            "reason_summary": row["reason"],
            "reason_factors": ranked.reason_factors,
            "evidence_count": len(ranked.reason_factors) + len(ranked.matched_terms),
            "explanation_confidence": ranked.explanation_confidence,
            "slot_type": ranked.slot_type,
            "diversity_adjusted": ranked.diversity_adjusted,
            "similarity_penalty": ranked.similarity_penalty,
        }
    )
    return row


def _recommend_for_user_v2(
    username: str,
    user_bookmarks: list[BookmarkRecord],
    papers: list[dict[str, Any]],
    *,
    event_signals: list[Any],
    related_signals: dict[str, dict[str, Any]] | None = None,
    limit: int,
    min_score: float,
    run_at: str,
    now: datetime,
) -> dict[str, Any]:
    current_year = now.year
    bookmark_profile, seen_papers = _user_profile(user_bookmarks)
    profile = build_recommendation_profile(bookmark_profile, event_signals, now=now)
    fallback_recent = not profile.positive_terms and not profile.query_terms
    seen_papers.update(profile.positive_paper_ids)

    ranked_items = []
    for paper in papers:
        if _paper_identity_values(paper) & seen_papers:
            continue
        enriched_paper = _with_related_signal(paper, related_signals or {})
        ranked = rank_paper_v2(enriched_paper, profile, current_year=current_year)
        if ranked.score >= min_score or fallback_recent:
            ranked_items.append(ranked)

    ranked_items.sort(
        key=lambda item: (item.score, _year_value(item.paper) or 0, safe_str(item.paper.get("title"))),
        reverse=True,
    )
    selected_items = mmr_rerank(ranked_items, limit=limit)
    recommendations = [
        _notification_row_v2(ranked, rank=idx, fallback_recent=fallback_recent)
        for idx, ranked in enumerate(selected_items, start=1)
    ]
    scores = [item["score"] for item in recommendations]
    personalization_state = "fallback" if fallback_recent else ("sparse" if len(event_signals) < 2 else "ready")
    return {
        "run_at": run_at,
        "user_id": username,
        "scoring_mode": SCORING_MODE_V2,
        "personalization_state": personalization_state,
        "fallback_reason": "no_personalization_signals" if fallback_recent else None,
        "next_best_action": "관심 논문을 북마크하거나 검색 결과를 열어 추천 근거를 늘릴 수 있습니다." if fallback_recent else None,
        "profile": profile.public_summary(bookmark_count=len(user_bookmarks), fallback_recent=fallback_recent),
        "score_stats": _score_stats(scores, fallback_recent=fallback_recent),
        "variants": {"daily": recommendations},
    }


def recommend_for_user(
    username: str,
    user_bookmarks: list[BookmarkRecord],
    papers: list[dict[str, Any]],
    *,
    limit: int = DEFAULT_LIMIT,
    min_score: float = DEFAULT_MIN_SCORE,
    run_at: str | None = None,
    event_signals: list[Any] | None = None,
    related_signals: dict[str, dict[str, Any]] | None = None,
    use_profile_ranker: bool = False,
) -> dict[str, Any]:
    now = _run_datetime(run_at)
    resolved_run_at = run_at or now.isoformat()
    if not use_profile_ranker:
        return _recommend_for_user_v1(
            username,
            user_bookmarks,
            papers,
            limit=limit,
            min_score=min_score,
            run_at=resolved_run_at,
            now=now,
        )
    return _recommend_for_user_v2(
        username,
        user_bookmarks,
        papers,
        event_signals=event_signals or [],
        related_signals=related_signals,
        limit=limit,
        min_score=min_score,
        run_at=resolved_run_at,
        now=now,
    )


def _artifact_path(root: Path, username: str, run_at: str) -> Path:
    day = run_at[:10] if run_at else datetime.now(timezone.utc).date().isoformat()
    return root / username / day / "raw.json"


def write_artifact(root: Path, username: str, artifact: dict[str, Any]) -> Path:
    path = _artifact_path(root, username, safe_str(artifact.get("run_at")))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


def generate_daily_recommendations(
    *,
    users_db: Path,
    bookmarks_db: Path,
    papers_json: Path,
    artifacts_dir: Path,
    limit: int = DEFAULT_LIMIT,
    min_score: float = DEFAULT_MIN_SCORE,
    usernames: Iterable[str] | None = None,
    run_at: str | None = None,
    skip_existing: bool = False,
    events_db: Path | None = None,
    related_papers_json: Path | None = None,
) -> dict[str, Any]:
    users = load_users(users_db)
    requested = {safe_str(username) for username in usernames or [] if safe_str(username)}
    if requested:
        users = [user for user in users if user.username in requested]
    bookmarks = load_bookmarks(bookmarks_db)
    bookmarks_by_user: dict[str, list[BookmarkRecord]] = {}
    for bookmark in bookmarks:
        bookmarks_by_user.setdefault(bookmark.username, []).append(bookmark)
    papers = load_papers(papers_json)
    related_signals = load_related_paper_signals(related_papers_json)

    written: list[str] = []
    skipped: list[str] = []
    skipped_existing: list[str] = []
    v2_success = 0
    v2_failed = 0
    v1_fallback = 0
    now = _run_datetime(run_at)
    for user in users:
        if skip_existing and _artifact_path(artifacts_dir, user.username, run_at or "").exists():
            skipped_existing.append(user.username)
            continue
        use_v2 = _profile_ranker_enabled(user.username)
        if use_v2:
            try:
                event_signals = load_user_event_signals(events_db, user.username, now=now)
                artifact = recommend_for_user(
                    user.username,
                    bookmarks_by_user.get(user.username, []),
                    papers,
                    limit=limit,
                    min_score=min_score,
                    run_at=run_at,
                    event_signals=event_signals,
                    related_signals=related_signals,
                    use_profile_ranker=True,
                )
                v2_success += 1
            except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
                # Per-user safety fallback: malformed v2 signals must not stop
                # the whole daily batch or leave the user without recommendations.
                v2_failed += 1
                v1_fallback += 1
                artifact = _recommend_for_user_v1(
                    user.username,
                    bookmarks_by_user.get(user.username, []),
                    papers,
                    limit=limit,
                    min_score=min_score,
                    run_at=run_at or now.isoformat(),
                    now=now,
                    fallback_reason="v2_error",
                )
        else:
            artifact = recommend_for_user(
                user.username,
                bookmarks_by_user.get(user.username, []),
                papers,
                limit=limit,
                min_score=min_score,
                run_at=run_at,
            )
        path = write_artifact(artifacts_dir, user.username, artifact)
        written.append(str(path))

    if requested:
        existing = {user.username for user in users}
        skipped = sorted(requested - existing)

    return {
        "users_seen": len(users),
        "papers_seen": len(papers),
        "artifacts_written": written,
        "skipped_usernames": skipped,
        "skipped_existing_usernames": skipped_existing,
        "v2_success": v2_success,
        "v2_failed": v2_failed,
        "v1_fallback": v1_fallback,
        "related_signals_seen": len(related_signals),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate daily per-user recommendation artifacts.")
    parser.add_argument("--users-db", type=Path, default=Path("data/users.db"))
    parser.add_argument("--bookmarks-db", type=Path, default=Path("data/bookmarks.db"))
    parser.add_argument("--papers-json", type=Path, default=Path("data/raw/papers.json"))
    parser.add_argument("--artifacts-dir", type=Path, default=Path("data/recommendations"))
    parser.add_argument("--events-db", type=Path, default=Path("data/events.db"))
    parser.add_argument("--related-papers-json", type=Path)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--user", action="append", dest="users", help="Restrict generation to a username.")
    parser.add_argument("--run-at", help="Override run_at ISO timestamp, mainly for tests/backfills.")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Do not overwrite users that already have a raw.json for the target run date.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = generate_daily_recommendations(
        users_db=args.users_db,
        bookmarks_db=args.bookmarks_db,
        papers_json=args.papers_json,
        artifacts_dir=args.artifacts_dir,
        limit=max(1, args.limit),
        min_score=args.min_score,
        usernames=args.users,
        run_at=args.run_at,
        skip_existing=args.skip_existing,
        events_db=args.events_db,
        related_papers_json=args.related_papers_json,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
