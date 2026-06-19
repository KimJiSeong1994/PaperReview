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
    assert response["raw_count"] == 1
    assert response["latest_run_at"] == "2026-04-25T09:00:00"
    assert response["scoring_mode"] == "listwise"
    assert response["score_stats"]["soul"]["mean"] == 4.5
    item = response["items"][0]
    assert item["title"] == "Ranked Paper"
    assert item["authors"] == ["Kim", "Lee", "Park"]
    assert item["score"] == 4.5
    assert item["display_score"] == "4.5"
    assert item["confidence_label"] == "상위 추천"
    assert item["rank"] == 1
    assert item["url"] == "https://example.test/paper"
    grouped = response["grouped_items"][0]
    assert grouped["paper_id"] == "arxiv:1"
    assert grouped["top_reason"] == "프로필과 잘 맞습니다."
    assert grouped["variants"][0]["variant"] == "soul"


def test_load_notifications_empty_when_artifact_root_missing(tmp_path: Path) -> None:
    response = load_recommendation_artifact(tmp_path / "missing", "alice", limit=10)

    assert response["items"] == []
    assert response["grouped_items"] == []
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
    assert response["grouped_items"] == []
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
    assert response["grouped_items"] == []
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



def test_load_notifications_groups_duplicate_papers_across_variants(tmp_path: Path) -> None:
    day = tmp_path / "2026-04-25"
    day.mkdir()
    paper = {
        "paper_id": "same-paper",
        "title": "Same Paper",
        "authors": ["Kim"],
        "score": 4.9999,
        "rank": 1,
        "reason": "키워드 기준 추천",
    }
    (day / "raw.json").write_text(
        json.dumps(
            {
                "run_at": "2026-04-25T09:00:00",
                "user_id": "alice",
                "variants": {
                    "keywords": [paper],
                    "soul": [{**paper, "score": 4.8, "rank": 2, "reason": "SOUL 기준 추천"}],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = load_recommendation_artifact(tmp_path, "alice", limit=10)

    assert response["raw_count"] == 2
    assert response["unread_count"] == 1
    assert len(response["items"]) == 2
    grouped = response["grouped_items"][0]
    assert grouped["title"] == "Same Paper"
    assert grouped["confidence_label"] == "상위 추천"
    assert grouped["display_score"] == "5.0"
    assert grouped["top_reason"] == "키워드 기준 추천"
    assert [v["variant"] for v in grouped["variants"]] == ["keywords", "soul"]


def test_load_notifications_limits_grouped_items_by_highest_score(tmp_path: Path) -> None:
    day = tmp_path / "2026-04-25"
    day.mkdir()
    papers = [
        {
            "paper_id": f"paper-{idx}",
            "title": f"Paper {idx}",
            "score": float(idx),
            "reason": f"{idx}점 추천",
        }
        for idx in range(1, 8)
    ]
    (day / "raw.json").write_text(
        json.dumps(
            {
                "run_at": "2026-04-25T09:00:00",
                "user_id": "alice",
                "variants": {"keywords": papers},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = load_recommendation_artifact(tmp_path, "alice", limit=5)

    assert response["unread_count"] == 7
    assert [item["title"] for item in response["grouped_items"]] == [
        "Paper 7",
        "Paper 6",
        "Paper 5",
        "Paper 4",
        "Paper 3",
    ]


def test_load_notifications_preserves_v2_explanation_fields(tmp_path: Path) -> None:
    day = tmp_path / "alice" / "2026-04-28"
    day.mkdir(parents=True)
    (day / "raw.json").write_text(
        json.dumps(
            {
                "run_at": "2026-04-28T00:00:00Z",
                "user_id": "alice",
                "scoring_mode": "daily_profile_ranker_v2",
                "variants": {
                    "daily": [
                        {
                            "paper_id": "p1",
                            "title": "Explainable Recommendation",
                            "score": 4.2,
                            "rank": 1,
                            "reason": "관심 신호와 겹칩니다.",
                            "matched_terms": ["graph", "ranking"],
                            "reason_factors": ["최근 탐색 신호"],
                            "score_breakdown": {"recent_intent_match": 0.8},
                            "evidence_count": 3,
                            "explanation_confidence": "근거 충분",
                            "slot_type": "recent_intent",
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = load_recommendation_artifact(tmp_path, "alice", limit=10)

    item = response["items"][0]
    assert item["matched_terms"] == ["graph", "ranking"]
    assert item["reason_factors"] == ["최근 탐색 신호"]
    assert item["score_breakdown"]["recent_intent_match"] == 0.8
    grouped = response["grouped_items"][0]
    assert grouped["slot_type"] == "recent_intent"
    assert grouped["variants"][0]["explanation_confidence"] == "근거 충분"


def test_recommendation_feedback_endpoint_emits_event(monkeypatch) -> None:
    import asyncio
    import routers.recommendations as rec_router
    from src.events.event_types import EventType

    events = []
    monkeypatch.setattr(rec_router, "emit_or_warn", lambda event: events.append(event))

    response = asyncio.run(
        rec_router.record_recommendation_feedback(
            rec_router.RecommendationFeedbackRequest(
                recommendation_id="run:daily:p1",
                paper_id="p1",
                feedback_type="not_interested",
                reason_factor="topic",
                run_at="2026-04-28T00:00:00Z",
            ),
            username="alice",
        )
    )

    assert response == {"tracked": True}
    assert events[0].event_type == EventType.RECOMMENDATION_FEEDBACK
    assert events[0].payload["feedback_type"] == "not_interested"
    assert events[0].paper_id == "p1"


def test_recommendation_read_state_endpoint_validates_action(monkeypatch) -> None:
    import asyncio
    import routers.recommendations as rec_router
    from src.events.event_types import EventType

    events = []
    monkeypatch.setattr(rec_router, "emit_or_warn", lambda event: events.append(event))

    invalid = asyncio.run(
        rec_router.record_recommendation_read_state(
            rec_router.RecommendationReadStateRequest(run_at="2026-04-28T00:00:00Z", action="raw_query"),
            username="alice",
        )
    )
    valid = asyncio.run(
        rec_router.record_recommendation_read_state(
            rec_router.RecommendationReadStateRequest(run_at="2026-04-28T00:00:00Z", recommendation_id="r1", action="seen"),
            username="alice",
        )
    )

    assert invalid == {"tracked": False}
    assert valid == {"tracked": True}
    assert len(events) == 1
    assert events[0].event_type == EventType.RECOMMENDATION_READ
    assert events[0].payload["action"] == "seen"
