"""US-003: SearchAgent의 통합 쿼리 분석 경로 검증.

smart_search / llm_context_search가 QueryAnalyzer.analyze_and_prepare를
단일 진입점으로 사용하고, 실패 시 기존 개별 호출(analyze_query +
generate_search_queries)로 graceful fallback되는지 검증한다.

Phase 1 목표: search LLM 호출 3회 → 1회(happy path) / 2회+(fallback).
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from app.SearchAgent.search_agent import SearchAgent


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_UNIFIED_RESULT: Dict[str, Any] = {
    "is_academic": True,
    "intent": "paper_search",
    "keywords": ["graph", "neural", "network"],
    "core_concepts": ["graph neural networks"],
    "research_area": "Machine Learning",
    "improved_query": "graph neural networks",
    "search_strategy": "title + abstract keyword search",
    "search_filters": {},
    "confidence": 0.92,
    "original_query": "graph neural networks",
    "source_queries": {
        "arxiv": "(ti:graph OR ti:neural) OR (abs:graph AND abs:network)",
        "dblp": "graph neural network",
        "google_scholar": "graph neural networks survey",
        "scholar_queries": [
            "graph neural networks survey",
            "\"graph neural network\" representation",
            "message passing graph neural network",
        ],
        "default": "graph neural networks",
    },
}


@pytest.fixture
def search_agent_with_mock_analyzer() -> SearchAgent:
    """SearchAgent 인스턴스에 mock QueryAnalyzer를 주입한다.

    외부 검색 API는 호출되지 않도록 주요 searcher/deduplicator도 mock 처리한다.
    """
    agent = SearchAgent.__new__(SearchAgent)  # __init__ 우회 — 네트워크 의존 차단

    # 검색 소스 전부 mock (빈 결과 반환)
    agent.arxiv_searcher = MagicMock()
    agent.arxiv_searcher.search.return_value = []
    agent.connected_papers_searcher = MagicMock()
    agent.connected_papers_searcher.search.return_value = []
    agent.google_scholar_searcher = MagicMock()
    agent.google_scholar_searcher.search.return_value = []
    agent.openalex_searcher = MagicMock()
    agent.openalex_searcher.search.return_value = []
    agent.openalex_searcher.search_korean.return_value = []
    agent.openalex_searcher.enhanced_search.return_value = []
    agent.dblp_searcher = MagicMock()
    agent.dblp_searcher.search.return_value = []

    # QueryAnalyzer mock
    analyzer = MagicMock()
    analyzer.analyze_and_prepare.return_value = dict(_UNIFIED_RESULT)
    analyzer.analyze_query.return_value = {
        "intent": "paper_search",
        "keywords": ["graph", "neural"],
        "improved_query": "graph neural networks",
        "confidence": 0.9,
        "original_query": "graph neural networks",
    }
    analyzer.generate_search_queries.return_value = {
        "arxiv_queries": ["graph neural networks"],
        "scholar_queries": ["graph neural networks"],
        "keywords": ["graph", "neural"],
        "search_context": "fallback",
        "translated_query": "graph neural networks",
        "related_terms": [],
    }
    analyzer.search_with_context.return_value = {
        "arxiv_queries": ["context query"],
        "scholar_queries": ["context query"],
        "keywords": ["context"],
        "search_context": "context-aware",
        "translated_query": "context query",
    }
    agent.query_analyzer = analyzer

    # 보조 객체
    agent.search_history = []
    agent.deduplicator = MagicMock()
    agent.deduplicator.deduplicate_cross_source.return_value = []
    agent.hybrid_ranker = None
    agent.similarity_calculator = None

    return agent


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestSmartSearchUsesUnifiedPath:
    """smart_search가 analyze_and_prepare 단일 진입점을 사용하는지 검증."""

    def test_smart_search_calls_analyze_and_prepare_once(
        self, search_agent_with_mock_analyzer: SearchAgent
    ) -> None:
        """happy path — 통합 호출이 정확히 1회 이루어지고,
        개별 LLM 호출(analyze_query/classify_topic)은 사용되지 않는다."""
        agent = search_agent_with_mock_analyzer

        agent.smart_search("graph neural networks", max_results=10)

        analyzer = agent.query_analyzer
        # 통합 호출은 반드시 1회 이상 수행
        assert analyzer.analyze_and_prepare.call_count >= 1
        # 개별 LLM 호출은 happy path에서 발생하면 안 됨
        analyzer.analyze_query.assert_not_called()
        # classify_topic/generate_source_specific_queries도 SearchAgent 경로에서는 미사용
        assert not analyzer.classify_topic.called
        assert not analyzer.generate_source_specific_queries.called


class TestSmartSearchFallbackOnFailure:
    """analyze_and_prepare 실패 시 기존 개별 호출 경로로 graceful fallback."""

    def test_smart_search_falls_back_when_unified_raises(
        self, search_agent_with_mock_analyzer: SearchAgent
    ) -> None:
        agent = search_agent_with_mock_analyzer
        agent.query_analyzer.analyze_and_prepare.side_effect = RuntimeError(
            "unified LLM call exploded"
        )

        result = agent.smart_search("graph neural networks", max_results=10)

        analyzer = agent.query_analyzer
        analyzer.analyze_and_prepare.assert_called()
        # Fallback: 개별 analyze_query 호출이 발생해야 검색 quality가 유지된다
        analyzer.analyze_query.assert_called_once_with("graph neural networks")
        # 결과 구조는 여전히 유효해야 한다 (empty papers지만 metadata 존재)
        assert isinstance(result, dict)
        assert "papers" in result
        assert "metadata" in result


class TestLLMContextSearchUsesUnifiedPath:
    """llm_context_search(no context)가 analyze_and_prepare를 사용한다."""

    def test_llm_context_search_no_context_uses_unified(
        self, search_agent_with_mock_analyzer: SearchAgent
    ) -> None:
        agent = search_agent_with_mock_analyzer

        results = agent.llm_context_search("graph neural networks", max_results_per_source=5)

        analyzer = agent.query_analyzer
        analyzer.analyze_and_prepare.assert_called_once_with("graph neural networks")
        # 개별 generate_search_queries는 호출되면 안 됨
        analyzer.generate_search_queries.assert_not_called()
        # search_with_context는 context 없을 때 호출 금지
        analyzer.search_with_context.assert_not_called()
        # _metadata가 채워져 있는지 확인 (통합 결과에서 추출)
        assert "_metadata" in results
        md = results["_metadata"]
        assert md["original_query"] == "graph neural networks"
        assert md["keywords"] == ["graph", "neural", "network"]
        # scholar_queries 리스트가 source_queries로부터 정상 추출되었는지
        assert len(md["scholar_queries"]) == 3

    def test_llm_context_search_fallback_to_generate_search_queries(
        self, search_agent_with_mock_analyzer: SearchAgent
    ) -> None:
        agent = search_agent_with_mock_analyzer
        agent.query_analyzer.analyze_and_prepare.side_effect = RuntimeError(
            "unified LLM call exploded"
        )

        agent.llm_context_search("graph neural networks", max_results_per_source=5)

        analyzer = agent.query_analyzer
        analyzer.analyze_and_prepare.assert_called_once()
        # Fallback으로 개별 generate_search_queries가 호출되어야 한다
        analyzer.generate_search_queries.assert_called_once_with("graph neural networks")

    def test_llm_context_search_with_context_uses_search_with_context(
        self, search_agent_with_mock_analyzer: SearchAgent
    ) -> None:
        """context 인자가 주어지면 search_with_context 경로를 유지한다 (기존 동작 보존)."""
        agent = search_agent_with_mock_analyzer

        agent.llm_context_search(
            "graph neural networks",
            max_results_per_source=5,
            context="previous search: transformers",
        )

        analyzer = agent.query_analyzer
        analyzer.search_with_context.assert_called_once()
        # context 경로에서는 unified 호출을 쓰지 않는다
        analyzer.analyze_and_prepare.assert_not_called()
        analyzer.generate_search_queries.assert_not_called()


class TestAnalyzeAndPrepareReturnShape:
    """analyze_and_prepare의 실제 반환 구조가 SearchAgent가 기대하는 키를 포함하는지 검증."""

    def test_unified_result_contains_expected_fields(self) -> None:
        """통합 결과에는 keywords, intent, confidence, source_queries(arxiv/scholar_queries/dblp)가 있어야 한다."""
        from app.QueryAgent.query_analyzer import QueryAnalyzer

        analyzer = QueryAnalyzer(api_key=None)  # client=None → fallback 경로
        result = analyzer.analyze_and_prepare("graph neural networks")

        # fallback 경로에서도 SearchAgent가 참조하는 키가 전부 존재해야 한다
        assert "is_academic" in result
        assert "intent" in result
        assert "keywords" in result
        assert "improved_query" in result
        assert "confidence" in result
        assert "source_queries" in result

        source_queries = result["source_queries"]
        assert "arxiv" in source_queries
        assert "dblp" in source_queries
        assert "google_scholar" in source_queries
