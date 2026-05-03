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


def test_daily_generation_skip_existing_preserves_imported_artifact(tmp_path: Path) -> None:
    users_db = tmp_path / "users.db"
    bookmarks_db = tmp_path / "bookmarks.db"
    papers_json = tmp_path / "raw" / "papers.json"
    artifacts_dir = tmp_path / "recommendations"
    _init_users(users_db, ["alice", "bob"])
    _init_bookmarks(bookmarks_db)
    _write_papers(papers_json)

    existing_path = artifacts_dir / "alice" / "2026-04-28" / "raw.json"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_text(
        json.dumps(
            {
                "run_at": "2026-04-28T00:00:00Z",
                "user_id": "alice",
                "scoring_mode": "openclaw",
                "variants": {"keywords": [{"title": "OpenClaw Preserved", "score": 5, "rank": 1}]},
            }
        ),
        encoding="utf-8",
    )

    summary = generate_daily_recommendations(
        users_db=users_db,
        bookmarks_db=bookmarks_db,
        papers_json=papers_json,
        artifacts_dir=artifacts_dir,
        run_at="2026-04-28T03:10:00+09:00",
        min_score=0.1,
        skip_existing=True,
    )

    assert summary["skipped_existing_usernames"] == ["alice"]
    assert len(summary["artifacts_written"]) == 1
    assert load_recommendation_artifact(artifacts_dir, "alice", limit=5)["grouped_items"][0]["title"] == "OpenClaw Preserved"
    assert load_recommendation_artifact(artifacts_dir, "bob", limit=5)["grouped_items"]


def _init_events(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE user_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                paper_id TEXT,
                created_at TEXT NOT NULL,
                source TEXT DEFAULT 'app'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _insert_event(
    path: Path,
    username: str,
    event_type: str,
    payload: dict,
    *,
    paper_id: str | None = None,
    created_at: str = "2026-04-27T00:00:00+00:00",
    source: str = "app",
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO user_events (user_id, event_type, payload, paper_id, created_at, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, event_type, json.dumps(payload), paper_id, created_at, source),
        )
        conn.commit()
    finally:
        conn.close()


def test_profile_ranker_env_flag_requires_user_allowlist(monkeypatch, tmp_path: Path) -> None:
    users_db = tmp_path / "users.db"
    bookmarks_db = tmp_path / "bookmarks.db"
    papers_json = tmp_path / "raw" / "papers.json"
    artifacts_dir = tmp_path / "recommendations"
    events_db = tmp_path / "events.db"
    _init_users(users_db, ["carol"])
    _init_bookmarks(bookmarks_db)
    _write_papers(papers_json)
    _init_events(events_db)
    monkeypatch.setenv("PROFILE_RANKER_ENABLED", "true")
    monkeypatch.delenv("PROFILE_RANKER_GLOBAL_ENABLED", raising=False)
    monkeypatch.delenv("PROFILE_RANKER_ALLOWED_USERS", raising=False)

    generate_daily_recommendations(
        users_db=users_db,
        bookmarks_db=bookmarks_db,
        papers_json=papers_json,
        artifacts_dir=artifacts_dir,
        events_db=events_db,
        usernames=["carol"],
        run_at="2026-04-28T00:00:00+00:00",
        min_score=0.1,
    )

    artifact = json.loads((artifacts_dir / "carol" / "2026-04-28" / "raw.json").read_text())
    assert artifact["scoring_mode"] == "daily_content_v1"


def test_profile_ranker_v2_uses_bounded_event_terms_without_raw_query(monkeypatch, tmp_path: Path) -> None:
    users_db = tmp_path / "users.db"
    bookmarks_db = tmp_path / "bookmarks.db"
    papers_json = tmp_path / "raw" / "papers.json"
    artifacts_dir = tmp_path / "recommendations"
    events_db = tmp_path / "events.db"
    _init_users(users_db, ["carol"])
    _init_bookmarks(bookmarks_db)
    _write_papers(papers_json)
    _init_events(events_db)
    _insert_event(
        events_db,
        "carol",
        "query_submit",
        {
            "event_schema_version": "recommendation_event_contract_v1",
            "query_hash": "abc123",
            "normalized_terms": ["graph", "recommender"],
            "query": "this raw query must not be consumed or serialized",
        },
    )
    monkeypatch.setenv("PROFILE_RANKER_ENABLED", "true")
    monkeypatch.setenv("PROFILE_RANKER_ALLOWED_USERS", "carol")

    summary = generate_daily_recommendations(
        users_db=users_db,
        bookmarks_db=bookmarks_db,
        papers_json=papers_json,
        artifacts_dir=artifacts_dir,
        events_db=events_db,
        usernames=["carol"],
        run_at="2026-04-28T00:00:00+00:00",
        min_score=0.1,
    )

    assert summary["v2_success"] == 1
    artifact_text = (artifacts_dir / "carol" / "2026-04-28" / "raw.json").read_text()
    assert "this raw query" not in artifact_text
    artifact = json.loads(artifact_text)
    assert artifact["scoring_mode"] == "daily_profile_ranker_v2"
    item = artifact["variants"]["daily"][0]
    assert item["title"] == "Graph Contrastive Learning for Recommender Systems"
    assert 0 <= item["normalized_score"] <= 1
    assert 0 <= item["score"] <= 5
    assert item["score_breakdown"]["recent_intent_match"] > 0
    assert item["matched_terms"]


def test_profile_ranker_v2_negative_event_downranks_candidate(monkeypatch, tmp_path: Path) -> None:
    users_db = tmp_path / "users.db"
    bookmarks_db = tmp_path / "bookmarks.db"
    papers_json = tmp_path / "raw" / "papers.json"
    artifacts_dir = tmp_path / "recommendations"
    events_db = tmp_path / "events.db"
    _init_users(users_db, ["carol"])
    _init_bookmarks(bookmarks_db)
    _write_papers(papers_json)
    _init_events(events_db)
    _insert_event(events_db, "carol", "query_submit", {"normalized_terms": ["graph", "recommender"]})
    _insert_event(events_db, "carol", "bookmark_remove", {"paper_id": "2601.11111", "normalized_terms": ["graph"]}, paper_id="bookmark-id")
    monkeypatch.setenv("PROFILE_RANKER_ENABLED", "true")
    monkeypatch.setenv("PROFILE_RANKER_ALLOWED_USERS", "carol")

    generate_daily_recommendations(
        users_db=users_db,
        bookmarks_db=bookmarks_db,
        papers_json=papers_json,
        artifacts_dir=artifacts_dir,
        events_db=events_db,
        usernames=["carol"],
        run_at="2026-04-28T00:00:00+00:00",
        min_score=0.0,
    )

    artifact = json.loads((artifacts_dir / "carol" / "2026-04-28" / "raw.json").read_text())
    graph = next(item for item in artifact["variants"]["daily"] if item["title"].startswith("Graph Contrastive"))
    assert graph["score_breakdown"]["negative_match"] > 0


def test_profile_ranker_v2_ignores_synthetic_events(monkeypatch, tmp_path: Path) -> None:
    users_db = tmp_path / "users.db"
    bookmarks_db = tmp_path / "bookmarks.db"
    papers_json = tmp_path / "raw" / "papers.json"
    artifacts_dir = tmp_path / "recommendations"
    events_db = tmp_path / "events.db"
    _init_users(users_db, ["carol"])
    _init_bookmarks(bookmarks_db)
    _write_papers(papers_json)
    _init_events(events_db)
    _insert_event(events_db, "carol", "query_submit", {"normalized_terms": ["graph"]}, source="test")
    monkeypatch.setenv("PROFILE_RANKER_ENABLED", "true")
    monkeypatch.setenv("PROFILE_RANKER_ALLOWED_USERS", "carol")

    generate_daily_recommendations(
        users_db=users_db,
        bookmarks_db=bookmarks_db,
        papers_json=papers_json,
        artifacts_dir=artifacts_dir,
        events_db=events_db,
        usernames=["carol"],
        run_at="2026-04-28T00:00:00+00:00",
        min_score=0.1,
    )

    artifact = json.loads((artifacts_dir / "carol" / "2026-04-28" / "raw.json").read_text())
    assert artifact["profile"]["event_count"] == 0
    assert artifact["personalization_state"] == "fallback"


def test_profile_ranker_global_db_override_requires_second_gate(monkeypatch, tmp_path: Path) -> None:
    import src.events.feature_flags as ff

    users_db = tmp_path / "users.db"
    bookmarks_db = tmp_path / "bookmarks.db"
    papers_json = tmp_path / "raw" / "papers.json"
    artifacts_dir = tmp_path / "recommendations"
    flags_db = tmp_path / "flags.db"
    _init_users(users_db, ["carol"])
    _init_bookmarks(bookmarks_db)
    _write_papers(papers_json)
    monkeypatch.setenv("FEATURE_FLAGS_DB_PATH", str(flags_db))
    monkeypatch.delenv("PROFILE_RANKER_GLOBAL_ENABLED", raising=False)
    monkeypatch.delenv("PROFILE_RANKER_ALLOWED_USERS", raising=False)
    monkeypatch.delenv("PROFILE_RANKER_ENABLED", raising=False)
    ff.set_override(ff.PROFILE_RANKER_ENABLED, enabled=True)

    generate_daily_recommendations(
        users_db=users_db,
        bookmarks_db=bookmarks_db,
        papers_json=papers_json,
        artifacts_dir=artifacts_dir,
        usernames=["carol"],
        run_at="2026-04-28T00:00:00+00:00",
        min_score=0.1,
    )

    artifact = json.loads((artifacts_dir / "carol" / "2026-04-28" / "raw.json").read_text())
    assert artifact["scoring_mode"] == "daily_content_v1"


def test_profile_ranker_per_user_db_override_enables_v2(monkeypatch, tmp_path: Path) -> None:
    import src.events.feature_flags as ff

    users_db = tmp_path / "users.db"
    bookmarks_db = tmp_path / "bookmarks.db"
    papers_json = tmp_path / "raw" / "papers.json"
    artifacts_dir = tmp_path / "recommendations"
    events_db = tmp_path / "events.db"
    flags_db = tmp_path / "flags.db"
    _init_users(users_db, ["carol"])
    _init_bookmarks(bookmarks_db)
    _write_papers(papers_json)
    _init_events(events_db)
    _insert_event(events_db, "carol", "query_submit", {"normalized_terms": ["graph"]})
    monkeypatch.setenv("FEATURE_FLAGS_DB_PATH", str(flags_db))
    monkeypatch.delenv("PROFILE_RANKER_GLOBAL_ENABLED", raising=False)
    monkeypatch.delenv("PROFILE_RANKER_ALLOWED_USERS", raising=False)
    monkeypatch.delenv("PROFILE_RANKER_ENABLED", raising=False)
    ff.set_override(ff.PROFILE_RANKER_ENABLED, enabled=True, username="carol")

    generate_daily_recommendations(
        users_db=users_db,
        bookmarks_db=bookmarks_db,
        papers_json=papers_json,
        artifacts_dir=artifacts_dir,
        events_db=events_db,
        usernames=["carol"],
        run_at="2026-04-28T00:00:00+00:00",
        min_score=0.1,
    )

    artifact = json.loads((artifacts_dir / "carol" / "2026-04-28" / "raw.json").read_text())
    assert artifact["scoring_mode"] == "daily_profile_ranker_v2"


def test_search_query_event_terms_are_privacy_safe() -> None:
    from routers.search import _recommendation_normalized_terms

    terms = _recommendation_normalized_terms("Graph neural network for private user@example.com co-location research")

    assert "graph" in terms
    assert "network" in terms
    assert len(terms) <= 8
    assert "for" not in terms
    assert "private user@example.com" not in " ".join(terms)


def test_profile_ranker_applies_mmr_diversity(monkeypatch, tmp_path: Path) -> None:
    users_db = tmp_path / "users.db"
    bookmarks_db = tmp_path / "bookmarks.db"
    papers_json = tmp_path / "raw" / "papers.json"
    artifacts_dir = tmp_path / "recommendations"
    events_db = tmp_path / "events.db"
    _init_users(users_db, ["carol"])
    _init_bookmarks(bookmarks_db)
    _init_events(events_db)
    _insert_event(events_db, "carol", "query_submit", {"normalized_terms": ["graph", "ranking", "urban"]})
    papers_json.parent.mkdir(parents=True)
    papers_json.write_text(
        json.dumps(
            {
                "papers": [
                    {"title": "Graph Ranking Model A", "abstract": "graph ranking recommendation", "published_date": "2026-01-01", "source": "arxiv", "arxiv_id": "a"},
                    {"title": "Graph Ranking Model B", "abstract": "graph ranking recommendation", "published_date": "2026-01-02", "source": "arxiv", "arxiv_id": "b"},
                    {"title": "Urban Graph Mobility", "abstract": "urban graph mobility pattern", "published_date": "2026-01-03", "source": "openalex", "doi": "c"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROFILE_RANKER_ENABLED", "true")
    monkeypatch.setenv("PROFILE_RANKER_ALLOWED_USERS", "carol")

    generate_daily_recommendations(
        users_db=users_db,
        bookmarks_db=bookmarks_db,
        papers_json=papers_json,
        artifacts_dir=artifacts_dir,
        events_db=events_db,
        usernames=["carol"],
        run_at="2026-04-28T00:00:00+00:00",
        min_score=0.0,
        limit=3,
    )

    artifact = json.loads((artifacts_dir / "carol" / "2026-04-28" / "raw.json").read_text())
    items = artifact["variants"]["daily"]
    assert len(items) == 3
    assert any(item.get("diversity_adjusted") for item in items[1:])
    assert all("similarity_penalty" in item for item in items)


def test_related_paper_report_boosts_source_signal(monkeypatch, tmp_path: Path) -> None:
    users_db = tmp_path / "users.db"
    bookmarks_db = tmp_path / "bookmarks.db"
    papers_json = tmp_path / "raw" / "papers.json"
    related_json = tmp_path / "related-papers" / "2026-04-28.json"
    artifacts_dir = tmp_path / "recommendations"
    events_db = tmp_path / "events.db"
    _init_users(users_db, ["carol"])
    _init_bookmarks(bookmarks_db)
    _init_events(events_db)
    _insert_event(events_db, "carol", "query_submit", {"normalized_terms": ["urban", "vitality"]})
    papers_json.parent.mkdir(parents=True)
    papers_json.write_text(
        json.dumps({"papers": [{"title": "Urban Vitality Candidate", "abstract": "urban vitality", "doi": "10.related", "published_date": "2026-01-01"}]}),
        encoding="utf-8",
    )
    related_json.parent.mkdir(parents=True)
    related_json.write_text(
        json.dumps({"top_papers": [{"paper_id": "10.related", "score": 4.5, "query": "urban vitality", "reasons": ["reviewed"]}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROFILE_RANKER_ENABLED", "true")
    monkeypatch.setenv("PROFILE_RANKER_ALLOWED_USERS", "carol")

    summary = generate_daily_recommendations(
        users_db=users_db,
        bookmarks_db=bookmarks_db,
        papers_json=papers_json,
        artifacts_dir=artifacts_dir,
        events_db=events_db,
        related_papers_json=related_json,
        usernames=["carol"],
        run_at="2026-04-28T00:00:00+00:00",
        min_score=0.0,
    )

    artifact = json.loads((artifacts_dir / "carol" / "2026-04-28" / "raw.json").read_text())
    item = artifact["variants"]["daily"][0]
    assert summary["related_signals_seen"] == 1
    assert item["score_breakdown"]["related_review"] == 0.9
    assert item["score_breakdown"]["source_confidence"] >= 0.85


def test_recommendation_feedback_event_downranks_seen_paper(monkeypatch, tmp_path: Path) -> None:
    users_db = tmp_path / "users.db"
    bookmarks_db = tmp_path / "bookmarks.db"
    papers_json = tmp_path / "raw" / "papers.json"
    artifacts_dir = tmp_path / "recommendations"
    events_db = tmp_path / "events.db"
    _init_users(users_db, ["carol"])
    _init_bookmarks(bookmarks_db)
    _init_events(events_db)
    papers_json.parent.mkdir(parents=True)
    papers_json.write_text(
        json.dumps({"papers": [{"paper_id": "p1", "title": "Graph Feedback Paper", "abstract": "graph", "published_date": "2026-01-01"}]}),
        encoding="utf-8",
    )
    _insert_event(events_db, "carol", "query_submit", {"normalized_terms": ["graph"]})
    _insert_event(events_db, "carol", "recommendation_feedback", {"paper_id": "p1", "feedback_type": "not_interested"}, paper_id="p1")
    monkeypatch.setenv("PROFILE_RANKER_ENABLED", "true")
    monkeypatch.setenv("PROFILE_RANKER_ALLOWED_USERS", "carol")

    generate_daily_recommendations(
        users_db=users_db,
        bookmarks_db=bookmarks_db,
        papers_json=papers_json,
        artifacts_dir=artifacts_dir,
        events_db=events_db,
        usernames=["carol"],
        run_at="2026-04-28T00:00:00+00:00",
        min_score=0.0,
    )

    item = json.loads((artifacts_dir / "carol" / "2026-04-28" / "raw.json").read_text())["variants"]["daily"][0]
    assert item["score_breakdown"]["negative_match"] == 1.0
