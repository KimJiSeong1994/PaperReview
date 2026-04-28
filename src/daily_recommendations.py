"""Daily per-user paper recommendation artifact generation.

The notification API intentionally reads immutable ``raw.json`` artifacts.
This module owns the local, dependency-light producer for those artifacts so
production can refresh every user's recommendations on a daily schedule.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.recommendations_artifacts import paper_id, safe_str


DEFAULT_LIMIT = 12
DEFAULT_MIN_SCORE = 0.6
SCORING_MODE = "daily_content_v1"
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


def recommend_for_user(
    username: str,
    user_bookmarks: list[BookmarkRecord],
    papers: list[dict[str, Any]],
    *,
    limit: int = DEFAULT_LIMIT,
    min_score: float = DEFAULT_MIN_SCORE,
    run_at: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    run_at = run_at or now.isoformat()
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
    mean = sum(scores) / len(scores) if scores else 0.0
    return {
        "run_at": run_at,
        "user_id": username,
        "scoring_mode": SCORING_MODE,
        "profile": {
            "bookmark_count": len(user_bookmarks),
            "top_terms": [term for term, _ in profile.most_common(12)],
            "fallback_recent": fallback_recent,
        },
        "score_stats": {
            "daily": {
                "n": len(scores),
                "mean": round(mean, 3),
                "min": min(scores) if scores else 0.0,
                "max": max(scores) if scores else 0.0,
                "spread": round((max(scores) - min(scores)), 3) if scores else 0.0,
            }
        },
        "variants": {"daily": recommendations},
    }


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

    written: list[str] = []
    skipped: list[str] = []
    for user in users:
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
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate daily per-user recommendation artifacts.")
    parser.add_argument("--users-db", type=Path, default=Path("data/users.db"))
    parser.add_argument("--bookmarks-db", type=Path, default=Path("data/bookmarks.db"))
    parser.add_argument("--papers-json", type=Path, default=Path("data/raw/papers.json"))
    parser.add_argument("--artifacts-dir", type=Path, default=Path("data/recommendations"))
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--user", action="append", dest="users", help="Restrict generation to a username.")
    parser.add_argument("--run-at", help="Override run_at ISO timestamp, mainly for tests/backfills.")
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
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
