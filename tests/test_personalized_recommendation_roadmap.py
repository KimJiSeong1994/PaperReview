from __future__ import annotations

import ast
from pathlib import Path


DOC_PATH = Path("docs/personalized-paper-recommendation-roadmap.md")


def test_personalized_recommendation_roadmap_is_code_grounded() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    required_references = [
        "src/daily_recommendations.py::generate_daily_recommendations",
        "src/daily_recommendations.py::recommend_for_user",
        "src/daily_recommendations.py::write_artifact",
        "src/storage/user_db.py::UserDB.account_guard",
        "src/recommendation_candidates.py::load_candidate_snapshot",
        "src/recommendation_candidates.py::merge_candidate_pool",
        "src/related_paper_wiki.py::collect_review_build_wiki",
        "src/recommendation_profiles.py::load_user_event_signals",
        "src/recommendation_profiles.py::build_recommendation_profile",
        "src/recommendation_ranker.py::rank_paper_v2",
        "src/recommendation_ranker.py::mmr_rerank",
        "src/recommendations_artifacts.py::read_delivery",
        "src/recommendations_artifacts.py::load_recommendation_artifact",
        "src/recommendation_state.py::RecommendationPolicy.project",
        "routers/recommendations.py::list_recommendation_notifications",
        "routers/recommendations.py::record_recommendation_feedback",
        "routers/recommendations.py::record_recommendation_read_state",
        "routers/recommendations.py::record_recommendation_exposure",
        "src/recommendation_evaluation.py::evaluate_manifest",
        "src/recommendation_evaluation.py::project_case",
    ]
    for reference in required_references:
        assert reference in text, reference
        path, symbol = reference.split("::")
        node = ast.parse(Path(path).read_text(encoding="utf-8"))
        for name in symbol.split("."):
            matches = [
                child
                for child in node.body
                if isinstance(
                    child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                )
                and child.name == name
            ]
            assert len(matches) == 1, f"Stale documentation anchor: {reference}"
            node = matches[0]

    for path in (
        "web-ui/src/components/RecommendationBell.tsx",
        ".github/workflows/daily-recommendations.yml",
        "scripts/evaluate_daily_recommendations.py",
        "data/recommendation_eval/public_fixture_manifest.json",
    ):
        assert path in text
        assert Path(path).is_file()

    for retired in (
        "src/daily_recommendations.py::_user_profile",
        "src/recommendations_artifacts.py::latest_raw_file",
    ):
        assert retired not in text


def test_personalized_recommendation_roadmap_covers_required_strategy_sections() -> (
    None
):
    text = DOC_PATH.read_text(encoding="utf-8")
    for section in (
        "## 상태와 범위",
        "## 공통 제품 경로",
        "### 현재 함수 기준 추적",
        "## Offline evaluator",
        "### Frozen manifest와 신뢰 경계",
        "### 지표와 gate",
        "## 별도 운영·온라인 gate (미측정)",
        "## 남은 검증과 확장 순서",
    ):
        assert section in text

    for term in (
        "half-life decay",
        "canonical identity",
        "MMR",
        "한국어",
        "OpenClaw",
        "Shadow",
        "Canary",
        "user fixed assignment/activity 층화",
        "Rollback",
        "feature fallback",
        "policy/identity fail-closed",
        "daily-recommendations.md",
    ):
        assert term in text


def test_roadmap_preserves_top5_and_evidence_gates() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    for requirement in (
        "post-policy Top5 NDCG@5",
        "unconditional positive Recall@5",
        "candidate-conditional recall",
        "후보 밖 labeled positives",
        "@12 개선은 @5 regression을 보상할 수 없다",
        "paired user/profile-cluster bootstrap",
        "CI95%",
        "relative delta CI 하한≥−2%",
        "absolute delta CI 하한≥−2%p",
        "absolute point drop≤5%p",
        "missing/underpowered slice는 pass가 아니라 inconclusive",
        "safety violation은 하나라도 hard fail",
        "baseline NDCG=0",
        "features와 수집/생성/발행 metadata는 cutoff 이하",
        "label time은 cutoff 이후 label_cutoff 이하",
        "로컬 구현 정합성, 실제 public/OpenClaw 공급원 운영 적격성, 사용자 추천 유용성은 별도 판정",
        "실제 논문이 아닌 synthetic",
        "independent judge",
        "operational_metrics.observed=null",
        "promotion=false",
        "delivery≥99%",
        "stale≤1%",
        "최소14일",
        "power80%",
        "impression duplicate≤0.1%",
        "known-view linkage 누락≤1%",
        "hide rate 악화 CI 상한≤1%p",
        "전역 flag는 별도 승인",
    ):
        assert requirement in text, requirement


def test_roadmap_preserves_ownership_privacy_and_visible_surface_contracts() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    for requirement in (
        "현재 account incarnation",
        "삭제/재가입",
        "late publication",
        "private 후보는 동일 account incarnation만 사용",
        "public_only=True",
        "private 후보를 제외",
        "사용자 query/notes/report를 외부/shared wiki로 내보내지 않는다",
        "legacy global pool을 public으로 재분류하지 않는다",
        "serving artifact 직접 게시 또는 skip-existing 우회 금지",
        "source absent는 honest empty",
        "fake fallback 없음",
        "GET `/api/recommendations/notifications` 기본/최대5",
        "hide/already_seen는 hard suppression",
        "seen은 read marker",
        "interested/topic_less는 preference",
        "analytics 손실이 accepted action을 취소하지 않는다",
        "실제 visible Top5만 outcome 귀속",
        "current hide/refill",
        "candidate ingestion/기본 fallback으로 사용할 수 없다",
    ):
        assert requirement in text, requirement
