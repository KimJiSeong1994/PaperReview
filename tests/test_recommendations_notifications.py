from __future__ import annotations

import json
from pathlib import Path

from src.recommendations_artifacts import load_recommendation_artifact


def test_load_notifications_parses_latest_autoresearchclaw_artifact(tmp_path: Path) -> None:
    day = tmp_path / "2026-04-25"
    day.mkdir()
    (day / "raw.json").write_text(
        json.dumps(
            {
                "run_at": "2026-04-25T09:00:00",
                "user_id": "alice",
                "scoring_mode": "listwise",
                "score_stats": {"soul": {"n": 1, "mean": 4.5, "std": 0.0, "min": 4.5, "max": 4.5, "spread": 0.0}},
                "variants": {
                    "soul": [
                        {
                            "paper_id": "arxiv:1",
                            "title": "Ranked Paper",
                            "authors": ["Kim", "Lee", "Park"],
                            "year": 2026,
                            "venue": "arxiv",
                            "source": "arxiv",
                            "url": "https://example.test/paper",
                            "score": 4.5,
                            "rank": 1,
                            "reason": "프로필과 잘 맞습니다.",
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = load_recommendation_artifact(tmp_path, "alice", limit=10)

    assert response["unread_count"] == 1
    assert response["latest_run_at"] == "2026-04-25T09:00:00"
    assert response["scoring_mode"] == "listwise"
    assert response["score_stats"]["soul"]["mean"] == 4.5
    item = response["items"][0]
    assert item["title"] == "Ranked Paper"
    assert item["authors"] == ["Kim", "Lee", "Park"]
    assert item["score"] == 4.5
    assert item["rank"] == 1
    assert item["url"] == "https://example.test/paper"


def test_load_notifications_empty_when_artifact_root_missing(tmp_path: Path) -> None:
    response = load_recommendation_artifact(tmp_path / "missing", "alice", limit=10)

    assert response["items"] == []
    assert response["unread_count"] == 0


def test_load_notifications_does_not_fall_back_to_other_user_artifact(tmp_path: Path) -> None:
    day = tmp_path / "2026-04-25"
    day.mkdir()
    (day / "raw.json").write_text(
        json.dumps({"run_at": "2026-04-25T09:00:00", "user_id": "bob", "variants": {"soul": [{"title": "Private"}]}}),
        encoding="utf-8",
    )

    response = load_recommendation_artifact(tmp_path, "alice", limit=10)

    assert response["items"] == []
    assert response["unread_count"] == 0


def test_load_notifications_does_not_use_unscoped_artifact_without_user_id(tmp_path: Path) -> None:
    day = tmp_path / "2026-04-25"
    day.mkdir()
    (day / "raw.json").write_text(
        json.dumps({"run_at": "2026-04-25T09:00:00", "variants": {"soul": [{"title": "Unscoped"}]}}),
        encoding="utf-8",
    )

    response = load_recommendation_artifact(tmp_path, "alice", limit=10)

    assert response["items"] == []
    assert response["unread_count"] == 0


def test_load_notifications_allows_legacy_user_scoped_directory(tmp_path: Path) -> None:
    day = tmp_path / "alice" / "2026-04-25"
    day.mkdir(parents=True)
    (day / "raw.json").write_text(
        json.dumps({"run_at": "2026-04-25T09:00:00", "variants": {"soul": [{"title": "Scoped"}]}}),
        encoding="utf-8",
    )

    response = load_recommendation_artifact(tmp_path, "alice", limit=10)

    assert response["unread_count"] == 1
    assert response["items"][0]["title"] == "Scoped"
