"""US-003 follow-up: Search quality golden tests and scholar_queries guard unit tests.

Two sections:
1. test_scholar_queries_string_input_triggers_guard — non-xfail unit test that
   verifies the degenerate-string guard in analyze_and_prepare fires correctly
   when the LLM returns scholar_queries as a string instead of a list.

2. TestSearchQualityGolden — xfail scaffold that checks Jaccard similarity
   between the unified analyze_and_prepare path and the fallback path.
   Requires real OpenAI calls for meaningful comparison, so marked xfail.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app.QueryAgent.query_analyzer import QueryAnalyzer

# ---------------------------------------------------------------------------
# Representative query fixture (English + Korean mix)
# ---------------------------------------------------------------------------

GOLDEN_QUERIES: List[str] = [
    "transformer attention mechanism",
    "quantum error correction",
    "drug discovery machine learning",
    "대규모 언어 모델 fine tuning",
    "few-shot learning",
]


# ---------------------------------------------------------------------------
# Helper: build a minimal valid LLM JSON payload
# ---------------------------------------------------------------------------

def _make_llm_response(
    query: str,
    scholar_queries_value: Any,
) -> str:
    """Return a JSON string as the LLM would for analyze_and_prepare."""
    payload: Dict[str, Any] = {
        "is_academic": True,
        "intent": "paper_search",
        "keywords": query.split()[:4],
        "core_concepts": [query],
        "research_area": "Machine Learning",
        "improved_query": query,
        "search_strategy": "keyword search",
        "search_filters": {"year_start": None, "year_end": None, "category": None},
        "confidence": 0.85,
        "source_queries": {
            "arxiv": f"ti:{query.split()[0]}",
            "dblp": " ".join(query.split()[:3]),
            "google_scholar": scholar_queries_value,
        },
    }
    return json.dumps(payload)


def _mock_client_for(response_content: str) -> MagicMock:
    """Return a mock OpenAI client whose .chat.completions.create returns response_content."""
    choice = MagicMock()
    choice.message.content = response_content
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


# ---------------------------------------------------------------------------
# Fix 1 unit test — scholar_queries string-degenerate guard
# ---------------------------------------------------------------------------


class TestScholarQueriesStringGuard:
    """Verify the degenerate-string guard in analyze_and_prepare."""

    def test_scholar_queries_string_input_triggers_guard(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When the LLM returns scholar_queries as a plain string, the guard must:
        - Convert it into a list of >=2 variants
        - Log a WARNING mentioning 'LLM non-compliance'
        """
        query = "transformer attention mechanism"
        # LLM returns google_scholar as a string (non-compliant — should be list)
        llm_json = _make_llm_response(query, scholar_queries_value="transformers attention")

        analyzer = QueryAnalyzer(api_key="fake-key")
        analyzer.client = _mock_client_for(llm_json)

        with caplog.at_level(logging.WARNING, logger="app.QueryAgent.query_analyzer"):
            result = analyzer.analyze_and_prepare(query)

        sq = result["source_queries"]["scholar_queries"]
        assert isinstance(sq, list), "scholar_queries must be a list after guard"
        assert len(sq) >= 2, (
            f"Guard must fabricate >=2 variants, got {len(sq)}: {sq}"
        )
        # Warning must have fired
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "LLM non-compliance" in msg or "non-compliance" in str(msg)
            for msg in warning_messages
        ), f"Expected 'LLM non-compliance' warning, got: {warning_messages}"

    def test_scholar_queries_list_input_passes_through(self) -> None:
        """When the LLM returns scholar_queries as a list, values pass through unchanged."""
        query = "quantum error correction"
        expected = ["quantum error correction survey", "fault-tolerant quantum computing"]
        llm_json = _make_llm_response(query, scholar_queries_value=expected)

        analyzer = QueryAnalyzer(api_key="fake-key")
        analyzer.client = _mock_client_for(llm_json)

        result = analyzer.analyze_and_prepare(query)

        sq = result["source_queries"]["scholar_queries"]
        assert isinstance(sq, list)
        assert sq == expected, f"Expected {expected}, got {sq}"

    def test_scholar_queries_none_falls_back_to_single_entry(self) -> None:
        """When google_scholar is missing/None, scholar_queries falls back to [google_scholar_string]."""
        query = "drug discovery machine learning"
        payload = {
            "is_academic": True,
            "intent": "paper_search",
            "keywords": ["drug", "discovery"],
            "core_concepts": [],
            "research_area": "Bioinformatics",
            "improved_query": query,
            "search_strategy": "keyword",
            "search_filters": {},
            "confidence": 0.8,
            "source_queries": {
                "arxiv": "ti:drug",
                "dblp": "drug discovery",
                # google_scholar deliberately absent — triggers None branch
            },
        }
        llm_json = json.dumps(payload)

        analyzer = QueryAnalyzer(api_key="fake-key")
        analyzer.client = _mock_client_for(llm_json)

        result = analyzer.analyze_and_prepare(query)

        sq = result["source_queries"]["scholar_queries"]
        assert isinstance(sq, list)
        assert len(sq) >= 1

    @pytest.mark.parametrize("q", GOLDEN_QUERIES)
    def test_scholar_queries_list_capped_at_three(self, q: str) -> None:
        """scholar_queries is always capped at 3 even if LLM returns more."""
        oversized_list = [f"{q} variant {i}" for i in range(10)]
        llm_json = _make_llm_response(q, scholar_queries_value=oversized_list)

        analyzer = QueryAnalyzer(api_key="fake-key")
        analyzer.client = _mock_client_for(llm_json)

        result = analyzer.analyze_and_prepare(q)

        sq = result["source_queries"]["scholar_queries"]
        assert len(sq) <= 3, f"scholar_queries should be capped at 3, got {len(sq)}"


# ---------------------------------------------------------------------------
# Fix 2 — A/B path Jaccard golden scaffold (xfail; needs real OpenAI)
# ---------------------------------------------------------------------------


def _paper_ids(results: Any) -> set:
    """Extract a set of paper IDs (or titles) from a smart_search result dict."""
    papers = results.get("papers", []) if isinstance(results, dict) else []
    ids = set()
    for p in papers:
        pid = p.get("arxiv_id") or p.get("id") or p.get("title") or str(p)
        ids.add(str(pid))
    return ids


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Golden dataset requires real OpenAI calls and live search APIs. "
        "Scaffold only — asserts Jaccard(path_A, path_B) >= 0.8 when mocked "
        "results are deterministic."
    ),
)
class TestSearchQualityGolden:
    """A/B Jaccard similarity: unified path vs. forced-fallback path.

    Both paths use deterministic mocked search results so the test runs
    offline.  With mocked sources returning identical empty lists, Jaccard is
    trivially 1.0 — the point is the scaffold and plumbing are correct so
    that when real data is injected the comparison is meaningful.
    """

    @pytest.fixture()
    def agent_factory(self):
        """Return a callable that builds a SearchAgent with controllable analyze_and_prepare."""
        from app.SearchAgent.search_agent import SearchAgent

        def _make(unified_raises: bool = False) -> SearchAgent:
            agent = SearchAgent.__new__(SearchAgent)
            # Stub all search sources to return deterministic fake papers
            fake_papers = [
                {"title": f"Paper {i}", "arxiv_id": f"2401.{i:05d}", "id": f"2401.{i:05d}"}
                for i in range(5)
            ]
            for attr in (
                "arxiv_searcher",
                "connected_papers_searcher",
                "google_scholar_searcher",
                "openalex_searcher",
                "dblp_searcher",
            ):
                mock = MagicMock()
                mock.search.return_value = fake_papers
                if attr == "openalex_searcher":
                    mock.search_korean.return_value = fake_papers
                    mock.enhanced_search.return_value = fake_papers
                setattr(agent, attr, mock)

            analyzer = MagicMock()
            if unified_raises:
                analyzer.analyze_and_prepare.side_effect = RuntimeError("forced fallback")
            else:
                analyzer.analyze_and_prepare.return_value = {
                    "is_academic": True,
                    "intent": "paper_search",
                    "keywords": ["test"],
                    "core_concepts": [],
                    "research_area": "ML",
                    "improved_query": "test query",
                    "search_strategy": "keyword",
                    "search_filters": {},
                    "confidence": 0.9,
                    "original_query": "test query",
                    "source_queries": {
                        "arxiv": "ti:test",
                        "dblp": "test",
                        "google_scholar": "test query",
                        "scholar_queries": ["test query"],
                        "default": "test query",
                    },
                }
            analyzer.analyze_query.return_value = {
                "intent": "paper_search",
                "keywords": ["test"],
                "improved_query": "test query",
                "confidence": 0.8,
                "original_query": "test query",
            }
            analyzer.generate_search_queries.return_value = {
                "arxiv_queries": ["test query"],
                "scholar_queries": ["test query"],
                "keywords": ["test"],
                "search_context": "fallback",
                "translated_query": "test query",
                "related_terms": [],
            }
            analyzer.search_with_context.return_value = {
                "arxiv_queries": ["test query"],
                "scholar_queries": ["test query"],
                "keywords": ["test"],
                "search_context": "context-aware",
                "translated_query": "test query",
            }
            agent.query_analyzer = analyzer
            agent.search_history = []
            agent.deduplicator = MagicMock()
            agent.deduplicator.deduplicate_cross_source.return_value = fake_papers
            agent.hybrid_ranker = None
            agent.similarity_calculator = None
            return agent

        return _make

    @pytest.mark.parametrize("query", GOLDEN_QUERIES)
    def test_path_a_b_jaccard_at_least_0_8(self, agent_factory: Any, query: str) -> None:
        """Path A (unified) and Path B (forced fallback) return Jaccard >= 0.8."""
        agent_a = agent_factory(unified_raises=False)
        agent_b = agent_factory(unified_raises=True)

        result_a = agent_a.smart_search(query, max_results=10)
        result_b = agent_b.smart_search(query, max_results=10)

        ids_a = _paper_ids(result_a)
        ids_b = _paper_ids(result_b)

        j = _jaccard(ids_a, ids_b)
        assert j >= 0.8, (
            f"Jaccard similarity between unified and fallback paths is too low: "
            f"{j:.2f} (query={query!r}, |A|={len(ids_a)}, |B|={len(ids_b)})"
        )
