from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from src.related_paper_wiki import collect_review_build_wiki, load_seed_queries, review_paper


class DummySearcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        self.calls.append((query, max_results))
        return [
            {
                "title": f"Graph Co-Location Study for {query}",
                "authors": ["Ada Lovelace", "Grace Hopper"],
                "abstract": "Graph neural networks identify related paper co-location patterns.",
                "year": "2026",
                "citations": 75,
                "doi": "10.1000/graph-colocation",
                "url": "https://example.org/paper",
                "source": "OpenAlex",
            }
        ]

    def close(self) -> None:
        pass


def _init_bookmarks(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE bookmarks (
                id TEXT PRIMARY KEY,
                username TEXT,
                topic TEXT,
                title TEXT,
                papers TEXT,
                notes TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO bookmarks (id, username, topic, title, papers, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "bm-1",
                "alice",
                "Graph neural network paper recommendation",
                "Co-location and recommendation reading list",
                json.dumps([{"title": "Urban Co-Location Mining with GNN"}]),
                "Need related papers for LLM wiki construction.",
                "2026-05-01T00:00:00",
                "2026-05-02T00:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_load_seed_queries_from_bookmarks(tmp_path: Path) -> None:
    bookmarks_db = tmp_path / "bookmarks.db"
    _init_bookmarks(bookmarks_db)

    queries = load_seed_queries(bookmarks_db, max_queries=3)

    assert queries
    assert "graph" in queries[0]
    assert len(queries) <= 3


def test_review_paper_scores_recent_accessible_candidate() -> None:
    reviewed = review_paper(
        {
            "title": "A Related Paper",
            "abstract": "useful abstract",
            "year": "2026",
            "citations": 100,
            "doi": "10.1000/example",
            "pdf_url": "https://example.org/paper.pdf",
            "source_rank": 1,
            "search_query": "related useful paper",
        },
        current_year=2026,
    )

    assert reviewed.score > 3
    assert "검색 상위권 후보" in reviewed.reasons
    assert "원문/PDF 접근 가능" in reviewed.reasons


def test_collect_review_build_wiki_writes_paper_pool_and_markdown(tmp_path: Path) -> None:
    bookmarks_db = tmp_path / "bookmarks.db"
    papers_json = tmp_path / "raw" / "papers.json"
    wiki_dir = tmp_path / "llm-wiki"
    report_dir = tmp_path / "related-papers"
    _init_bookmarks(bookmarks_db)

    summary = collect_review_build_wiki(
        bookmarks_db=bookmarks_db,
        papers_json=papers_json,
        wiki_dir=wiki_dir,
        report_dir=report_dir,
        max_queries=1,
        per_query=2,
        top=5,
        run_at="2026-05-03T00:00:00Z",
        searcher=DummySearcher(),
    )

    assert summary["collected_count"] == 1
    assert summary["reviewed_count"] == 1
    assert papers_json.exists()
    papers = json.loads(papers_json.read_text(encoding="utf-8"))["papers"]
    assert papers[0]["related_review_score"] > 0
    assert papers[0]["search_query"]

    wiki_path = Path(summary["wiki_path"])
    assert wiki_path == wiki_dir / "daily" / "2026-05-03.md"
    wiki_text = wiki_path.read_text(encoding="utf-8")
    assert "Daily Related Paper Review" in wiki_text
    assert "Graph Co-Location Study" in wiki_text
    assert "Next agent instructions" in wiki_text
    assert (wiki_dir / "latest.md").exists()
    assert (report_dir / "2026-05-03.json").exists()
