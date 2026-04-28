from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.daily_recommendations import generate_daily_recommendations
from src.recommendations_artifacts import load_recommendation_artifact


def _init_users(path: Path, usernames: list[str]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE users (
                username TEXT PRIMARY KEY,
                password_hash TEXT,
                role TEXT,
                created_at TEXT,
                metadata TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO users (username, role) VALUES (?, 'user')",
            [(username,) for username in usernames],
        )
        conn.commit()
    finally:
        conn.close()


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
                report TEXT,
                notes TEXT,
                highlights TEXT,
                share_token TEXT,
                citation_tree TEXT,
                created_at TEXT,
                updated_at TEXT,
                metadata TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO bookmarks (id, username, topic, title, papers, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "bm-alice",
                    "alice",
                    "Graph neural networks",
                    "Graph recommendation reading list",
                    json.dumps(
                        [
                            {
                                "title": "Graph Neural Networks for Recommendation",
                                "arxiv_id": "2401.00001",
                            }
                        ]
                    ),
                    "2026-04-01T00:00:00",
                ),
                (
                    "bm-bob",
                    "bob",
                    "Urban spatial vitality",
                    "City co-location mining",
                    json.dumps([{"title": "Urban Co-Location Pattern Mining"}]),
                    "2026-04-01T00:00:00",
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _write_papers(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "title": "Graph Contrastive Learning for Recommender Systems",
                        "abstract": "Graph neural networks improve personalized recommendation.",
                        "arxiv_id": "2601.11111",
                        "pdf_url": "https://arxiv.org/pdf/2601.11111.pdf",
                        "published_date": "2026-01-02",
                        "source": "arxiv",
                    },
                    {
                        "title": "Urban Function Co-Location Mining in Smart Cities",
                        "abstract": "Spatial vitality and city function patterns are mined from urban data.",
                        "doi": "10.1000/urban",
                        "published_date": "2026-01-03",
                        "source": "openalex",
                    },
                    {
                        "title": "Graph Neural Networks for Recommendation",
                        "abstract": "Already bookmarked and should not be recommended again.",
                        "arxiv_id": "2401.00001",
                        "published_date": "2024-01-01",
                    },
                    {
                        "title": "A Recent General AI Paper",
                        "abstract": "A broad paper used as fallback for inactive users.",
                        "published_date": "2026-02-01",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_daily_generation_writes_user_scoped_artifacts(tmp_path: Path) -> None:
    users_db = tmp_path / "users.db"
    bookmarks_db = tmp_path / "bookmarks.db"
    papers_json = tmp_path / "raw" / "papers.json"
    artifacts_dir = tmp_path / "recommendations"
    _init_users(users_db, ["alice", "bob", "carol"])
    _init_bookmarks(bookmarks_db)
    _write_papers(papers_json)

    summary = generate_daily_recommendations(
        users_db=users_db,
        bookmarks_db=bookmarks_db,
        papers_json=papers_json,
        artifacts_dir=artifacts_dir,
        run_at="2026-04-28T03:10:00+09:00",
        min_score=0.1,
    )

    assert summary["users_seen"] == 3
    assert len(summary["artifacts_written"]) == 3

    alice = load_recommendation_artifact(artifacts_dir, "alice", limit=5)
    bob = load_recommendation_artifact(artifacts_dir, "bob", limit=5)
    carol = load_recommendation_artifact(artifacts_dir, "carol", limit=5)

    assert alice["latest_run_at"] == "2026-04-28T03:10:00+09:00"
    assert alice["grouped_items"][0]["title"] == "Graph Contrastive Learning for Recommender Systems"
    assert all(item["title"] != "Graph Neural Networks for Recommendation" for item in alice["grouped_items"])
    assert bob["grouped_items"][0]["title"] == "Urban Function Co-Location Mining in Smart Cities"
    assert carol["grouped_items"]
    assert carol["score_stats"]["daily"]["n"] > 0


def test_daily_generation_can_target_single_user(tmp_path: Path) -> None:
    users_db = tmp_path / "users.db"
    bookmarks_db = tmp_path / "bookmarks.db"
    papers_json = tmp_path / "raw" / "papers.json"
    artifacts_dir = tmp_path / "recommendations"
    _init_users(users_db, ["alice", "bob"])
    _init_bookmarks(bookmarks_db)
    _write_papers(papers_json)

    summary = generate_daily_recommendations(
        users_db=users_db,
        bookmarks_db=bookmarks_db,
        papers_json=papers_json,
        artifacts_dir=artifacts_dir,
        usernames=["bob", "missing"],
        run_at="2026-04-28T03:10:00+09:00",
        min_score=0.1,
    )

    assert summary["users_seen"] == 1
    assert summary["skipped_usernames"] == ["missing"]
    assert not (artifacts_dir / "alice").exists()
    assert load_recommendation_artifact(artifacts_dir, "bob", limit=5)["grouped_items"]
