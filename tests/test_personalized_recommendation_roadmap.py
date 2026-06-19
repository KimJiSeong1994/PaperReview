from __future__ import annotations

from pathlib import Path


DOC_PATH = Path("docs/personalized-paper-recommendation-roadmap.md")


def test_personalized_recommendation_roadmap_is_code_grounded() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    required_references = [
        "src/daily_recommendations.py::generate_daily_recommendations",
        "src/daily_recommendations.py::recommend_for_user",
        "src/daily_recommendations.py::_user_profile",
        "src/daily_recommendations.py::_score_paper",
        "src/recommendations_artifacts.py::latest_raw_file",
        "routers/recommendations.py::list_recommendation_notifications",
        "src/events/event_types.py::EventType",
        "routers/search.py",
        "routers/bookmarks.py",
        "src/graph_rag/hybrid_ranker.py::HybridRanker",
        ".github/workflows/daily-recommendations.yml",
    ]
    for reference in required_references:
        assert reference in text


def test_personalized_recommendation_roadmap_covers_required_strategy_sections() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    required_sections = [
        "## 현재 파이프라인 요약",
        "## 핵심 품질 격차",
        "## 개선 제안",
        "### A. 데이터 신호 계층 확장",
        "### B. 후보 생성 개선",
        "### C. 랭킹/모델링 개선",
        "### D. 평가 전략",
        "## 배포 전략",
        "## 우선순위 로드맵",
        "## 즉시 실행 가능한 다음 작업",
    ]
    for section in required_sections:
        assert section in text

    required_terms = [
        "Recall@K",
        "NDCG@K",
        "Shadow mode",
        "A/B 테스트",
        "한국어",
        "OpenClaw",
        "fallback",
        "time-decayed",
        "stable ID",
    ]
    for term in required_terms:
        assert term in text
