"""Daily related-paper collection, review, and LLM-wiki artifact builder.

This module is intentionally dependency-light and deterministic.  The daily
scheduler can run it before per-user recommendations so recommendations have a
fresh paper pool, while the generated markdown gives agents an LLM-readable
research memory page for the same run.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

from src.recommendations_artifacts import paper_id, safe_str

DEFAULT_QUERIES = (
    "graph neural network paper recommendation",
    "research agent literature review",
    "retrieval augmented generation academic search",
)
DEFAULT_MAX_QUERIES = 8
DEFAULT_PER_QUERY = 8
DEFAULT_TOP = 24
_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣_\-]{1,}")
_SLUG_RE = re.compile(r"[^a-z0-9가-힣]+")
_STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "using",
    "based",
    "paper",
    "papers",
    "study",
    "studies",
    "research",
    "method",
    "methods",
    "model",
    "models",
    "analysis",
    "towards",
    "through",
    "대한",
    "논문",
    "연구",
    "분석",
    "방법",
}
_QUERY_NOISE_TOKENS = {
    "test",
    "e2e",
    "backfill",
    "payload",
    "large_payload_test",
    "mcp-e2e-test",
    "secret",
    "delete",
}
_QUERY_NOISE_SUBSTRINGS = ("test", "e2e", "backfill", "payload", "secret")


class PaperSearcher(Protocol):
    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class ReviewedPaper:
    paper: dict[str, Any]
    score: float
    reasons: list[str]


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def day_from_run_at(run_at: str) -> str:
    match = re.match(r"\d{4}-\d{2}-\d{2}", run_at)
    if match:
        return match.group(0)
    return datetime.now(timezone.utc).date().isoformat()


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in _TOKEN_RE.findall(text)
        if token.lower() not in _STOPWORDS and not token.isdigit()
    ]


def _compact_query(text: str, *, max_terms: int = 7) -> str:
    terms: list[str] = []
    for token in _tokens(text):
        if token in terms:
            continue
        terms.append(token)
        if len(terms) >= max_terms:
            break
    return " ".join(terms)


def _is_useful_query(query: str) -> bool:
    query = safe_str(query)
    if not 8 <= len(query) <= 160:
        return False
    tokens = _tokens(query)
    if len(tokens) < 2:
        return False
    lowered = query.lower()
    if any(noise in lowered for noise in _QUERY_NOISE_SUBSTRINGS):
        return False
    token_set = set(tokens)
    if token_set & _QUERY_NOISE_TOKENS:
        return False
    # Guard against synthetic payloads such as "aaaaaa..."
    if any(len(token) > 40 for token in tokens):
        return False
    return True


def load_seed_queries(
    bookmarks_db: Path,
    *,
    explicit_queries: Iterable[str] | None = None,
    max_queries: int = DEFAULT_MAX_QUERIES,
) -> list[str]:
    """Build daily collection queries from user bookmark topics and paper titles."""
    queries: list[str] = []

    for query in explicit_queries or []:
        query = safe_str(query)
        if _is_useful_query(query) and query not in queries:
            queries.append(query)

    if bookmarks_db.exists():
        conn = sqlite3.connect(str(bookmarks_db))
        conn.row_factory = sqlite3.Row
        try:
            columns = {
                safe_str(row["name"])
                for row in conn.execute("PRAGMA table_info(bookmarks)").fetchall()
            }
            order_by = "updated_at DESC, created_at DESC"
            if "updated_at" not in columns:
                order_by = "created_at DESC" if "created_at" in columns else "rowid DESC"
            rows = conn.execute(
                f"""
                SELECT topic, title, papers, notes
                FROM bookmarks
                ORDER BY {order_by}
                LIMIT 200
                """
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            candidates = [safe_str(row["topic"]), safe_str(row["title"]), safe_str(row["notes"])]
            try:
                papers = json.loads(row["papers"] or "[]")
            except json.JSONDecodeError:
                papers = []
            if isinstance(papers, list):
                candidates.extend(safe_str(paper.get("title")) for paper in papers if isinstance(paper, dict))

            for candidate in candidates:
                query = _compact_query(candidate)
                if not _is_useful_query(query) or query in queries:
                    continue
                queries.append(query)
                if len(queries) >= max_queries:
                    return queries

    for query in DEFAULT_QUERIES:
        if _is_useful_query(query) and query not in queries:
            queries.append(query)
        if len(queries) >= max_queries:
            break
    return queries[:max_queries]


def load_paper_pool(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    papers = raw.get("papers") if isinstance(raw, dict) else raw
    if not isinstance(papers, list):
        return []
    return [paper for paper in papers if isinstance(paper, dict) and safe_str(paper.get("title"))]


def _paper_identity(paper: dict[str, Any]) -> str:
    for key in ("doi", "arxiv_id", "openalex_id", "url", "pdf_url", "doc_id", "paper_id"):
        value = safe_str(paper.get(key)).lower()
        if value:
            return value
    return safe_str(paper.get("title")).lower()


def _year_value(paper: dict[str, Any]) -> int | None:
    for key in ("year", "published_date", "updated_date", "collected_at"):
        value = safe_str(paper.get(key))
        match = re.search(r"(19|20)\d{2}", value)
        if match:
            return int(match.group(0))
    return None


def normalize_collected_paper(paper: dict[str, Any], *, query: str, source_rank: int, run_at: str) -> dict[str, Any]:
    normalized = dict(paper)
    normalized["title"] = safe_str(normalized.get("title"))
    normalized["abstract"] = safe_str(normalized.get("abstract"))
    normalized["source"] = safe_str(normalized.get("source")) or "unknown"
    normalized["search_query"] = query
    normalized["source_rank"] = source_rank
    normalized["collected_at"] = run_at
    normalized["doc_id"] = paper_id(normalized)
    return normalized


def review_paper(paper: dict[str, Any], *, current_year: int | None = None) -> ReviewedPaper:
    """Score a collected paper for recommendation/wiki usefulness."""
    current_year = current_year or datetime.now(timezone.utc).year
    year = _year_value(paper)
    citations = int(paper.get("citations") or 0)
    source_rank = int(paper.get("source_rank") or 99)
    query_terms = set(_tokens(safe_str(paper.get("search_query"))))
    paper_terms = set(_tokens(f"{safe_str(paper.get('title'))} {safe_str(paper.get('abstract'))}"))
    overlap_terms = sorted(query_terms & paper_terms)
    overlap_count = len(overlap_terms)

    rank_score = max(0.0, 1.5 - 0.08 * max(0, source_rank - 1))
    citation_score = min(1.2, math.log1p(citations) / 6)
    if overlap_count < 2:
        citation_score *= 0.25
    recency_score = 0.25 if year is None else max(0.0, 1.0 - min(max(current_year - year, 0), 8) * 0.12)
    abstract_score = 0.4 if safe_str(paper.get("abstract")) else 0.0
    identifier_score = 0.2 if safe_str(paper.get("doi")) or safe_str(paper.get("arxiv_id")) else 0.0
    pdf_score = 0.15 if safe_str(paper.get("pdf_url")) else 0.0
    relevance_score = min(1.0, overlap_count * 0.25)
    relevance_penalty = 0.0
    if overlap_count == 0:
        relevance_penalty = 1.5
    elif overlap_count == 1:
        relevance_penalty = 0.8
    score = round(
        rank_score
        + citation_score
        + recency_score
        + abstract_score
        + identifier_score
        + pdf_score
        + relevance_score
        - relevance_penalty,
        3,
    )

    reasons: list[str] = []
    if source_rank <= 3:
        reasons.append("검색 상위권 후보")
    if year and current_year - year <= 2:
        reasons.append("최근 연구")
    if citations >= 50:
        reasons.append("인용 신호 있음")
    if safe_str(paper.get("abstract")):
        reasons.append("초록 기반 검토 가능")
    if safe_str(paper.get("pdf_url")):
        reasons.append("원문/PDF 접근 가능")
    if overlap_count >= 2:
        reasons.append(f"쿼리-내용 키워드 일치: {', '.join(overlap_terms[:4])}")
    if not reasons:
        reasons.append("관련 쿼리에서 수집된 검토 후보")

    return ReviewedPaper(paper=paper, score=score, reasons=reasons)


def collect_papers(searcher: PaperSearcher, queries: list[str], *, per_query: int, run_at: str) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for query in queries:
        results = searcher.search(query, max_results=per_query)
        for rank, paper in enumerate(results, start=1):
            if not safe_str(paper.get("title")):
                continue
            collected.append(normalize_collected_paper(paper, query=query, source_rank=rank, run_at=run_at))
    return collected


def merge_paper_pool(existing: list[dict[str, Any]], reviewed: list[ReviewedPaper]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {_paper_identity(paper): dict(paper) for paper in existing}
    for item in reviewed:
        paper = dict(item.paper)
        paper["related_review_score"] = item.score
        paper["related_review_reasons"] = item.reasons
        identity = _paper_identity(paper)
        previous = merged.get(identity)
        if previous is None or item.score >= float(previous.get("related_review_score") or 0):
            merged[identity] = {**(previous or {}), **paper}
    return sorted(
        merged.values(),
        key=lambda paper: (
            float(paper.get("related_review_score") or 0),
            _year_value(paper) or 0,
            safe_str(paper.get("title")),
        ),
        reverse=True,
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _slug(text: str) -> str:
    slug = _SLUG_RE.sub("-", safe_str(text).lower()).strip("-")
    return slug[:80] or "daily-related-papers"


def _paper_markdown(item: ReviewedPaper, index: int) -> str:
    paper = item.paper
    authors = paper.get("authors") if isinstance(paper.get("authors"), list) else []
    author_text = ", ".join(safe_str(author) for author in authors[:4] if safe_str(author)) or "n/a"
    title = safe_str(paper.get("title")) or "Untitled"
    url = safe_str(paper.get("url")) or safe_str(paper.get("pdf_url"))
    abstract = safe_str(paper.get("abstract"))
    if len(abstract) > 420:
        abstract = abstract[:417].rstrip() + "..."
    lines = [
        f"### {index}. {title}",
        "",
        f"- **Review score:** {item.score}",
        f"- **Why reviewed:** {', '.join(item.reasons)}",
        f"- **Source query:** {safe_str(paper.get('search_query'))}",
        f"- **Authors:** {author_text}",
        f"- **Year:** {_year_value(paper) or 'n/a'}",
        f"- **Source:** {safe_str(paper.get('source')) or 'n/a'}",
    ]
    if url:
        lines.append(f"- **URL:** {url}")
    if abstract:
        lines.extend(["", f"> {abstract}"])
    lines.append("")
    return "\n".join(lines)


def write_llm_wiki(
    wiki_dir: Path,
    *,
    reviewed: list[ReviewedPaper],
    queries: list[str],
    run_at: str,
    top: int,
) -> Path:
    day = day_from_run_at(run_at)
    daily_dir = wiki_dir / "daily"
    daily_path = daily_dir / f"{day}.md"
    top_reviewed = sorted(reviewed, key=lambda item: item.score, reverse=True)[:top]
    title = f"Daily Related Paper Review — {day}"
    body = [
        "---",
        f"title: {title}",
        f"date: {day}",
        "type: daily-related-paper-review",
        "tags: [paper-recommendation, related-papers, llm-wiki]",
        "---",
        "",
        f"# {title}",
        "",
        "## Purpose",
        "",
        "매일 수집된 관련 논문을 검토해 추천 후보 풀과 LLM wiki 연구 메모리로 재사용한다.",
        "",
        "## Collection queries",
        "",
        *(f"- {query}" for query in queries),
        "",
        "## Review criteria",
        "",
        "- 검색 상위권 여부",
        "- 최신성",
        "- 인용 신호",
        "- 초록 기반 검토 가능 여부",
        "- DOI/arXiv/PDF 등 후속 검토 가능 식별자",
        "",
        "## Top reviewed papers",
        "",
    ]
    if top_reviewed:
        for index, item in enumerate(top_reviewed, start=1):
            body.append(_paper_markdown(item, index))
    else:
        body.append("수집된 후보가 없습니다.\n")
    body.extend(
        [
            "## Next agent instructions",
            "",
            "- 상위 후보를 사용자 북마크/관심사와 다시 대조한다.",
            "- 추천 사유는 논문 제목만이 아니라 초록·방법론·데이터셋 단서까지 포함해 작성한다.",
            "- 후속 리서치가 필요한 논문은 별도 주제 wiki page로 승격한다.",
        ]
    )
    daily_path.parent.mkdir(parents=True, exist_ok=True)
    daily_path.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")

    latest_path = wiki_dir / "latest.md"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(
        f"# Latest Daily Related Paper Review\n\n- [{title}](daily/{daily_path.name})\n",
        encoding="utf-8",
    )
    return daily_path


def collect_review_build_wiki(
    *,
    bookmarks_db: Path,
    papers_json: Path,
    wiki_dir: Path,
    report_dir: Path,
    explicit_queries: Iterable[str] | None = None,
    max_queries: int = DEFAULT_MAX_QUERIES,
    per_query: int = DEFAULT_PER_QUERY,
    top: int = DEFAULT_TOP,
    run_at: str | None = None,
    searcher: PaperSearcher | None = None,
) -> dict[str, Any]:
    run_at = run_at or iso_now()
    owns_searcher = searcher is None
    if searcher is None:
        from src.collector.paper.openalex_searcher import OpenAlexSearcher

        searcher = OpenAlexSearcher()

    queries = load_seed_queries(bookmarks_db, explicit_queries=explicit_queries, max_queries=max_queries)
    try:
        collected = collect_papers(searcher, queries, per_query=per_query, run_at=run_at)
    finally:
        if owns_searcher:
            searcher.close()

    reviewed = sorted((review_paper(paper) for paper in collected), key=lambda item: item.score, reverse=True)
    existing = load_paper_pool(papers_json)
    merged = merge_paper_pool(existing, reviewed)
    _write_json_atomic(
        papers_json,
        {
            "updated_at": run_at,
            "source": "daily_related_paper_collection",
            "papers": merged,
        },
    )
    wiki_path = write_llm_wiki(wiki_dir, reviewed=reviewed, queries=queries, run_at=run_at, top=top)

    day = day_from_run_at(run_at)
    report_path = report_dir / f"{day}.json"
    top_reviewed = reviewed[:top]
    _write_json_atomic(
        report_path,
        {
            "run_at": run_at,
            "queries": queries,
            "collected_count": len(collected),
            "reviewed_count": len(reviewed),
            "papers_json": str(papers_json),
            "wiki_path": str(wiki_path),
            "top_papers": [
                {
                    "title": safe_str(item.paper.get("title")),
                    "paper_id": paper_id(item.paper),
                    "score": item.score,
                    "reasons": item.reasons,
                    "query": safe_str(item.paper.get("search_query")),
                    "url": safe_str(item.paper.get("url")) or safe_str(item.paper.get("pdf_url")),
                }
                for item in top_reviewed
            ],
        },
    )
    return {
        "run_at": run_at,
        "queries": queries,
        "collected_count": len(collected),
        "reviewed_count": len(reviewed),
        "merged_papers_count": len(merged),
        "papers_json": str(papers_json),
        "wiki_path": str(wiki_path),
        "report_path": str(report_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect related papers, review them, and build an LLM wiki page.")
    parser.add_argument("--bookmarks-db", type=Path, default=Path("data/bookmarks.db"))
    parser.add_argument("--papers-json", type=Path, default=Path("data/raw/papers.json"))
    parser.add_argument("--wiki-dir", type=Path, default=Path("data/llm-wiki"))
    parser.add_argument("--report-dir", type=Path, default=Path("data/related-papers"))
    parser.add_argument("--query", action="append", dest="queries", help="Seed query; can be repeated.")
    parser.add_argument("--max-queries", type=int, default=DEFAULT_MAX_QUERIES)
    parser.add_argument("--per-query", type=int, default=DEFAULT_PER_QUERY)
    parser.add_argument("--top", type=int, default=DEFAULT_TOP)
    parser.add_argument("--run-at", help="Override run timestamp for deterministic backfills/tests.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = collect_review_build_wiki(
        bookmarks_db=args.bookmarks_db,
        papers_json=args.papers_json,
        wiki_dir=args.wiki_dir,
        report_dir=args.report_dir,
        explicit_queries=args.queries,
        max_queries=max(1, args.max_queries),
        per_query=max(1, args.per_query),
        top=max(1, args.top),
        run_at=args.run_at,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
