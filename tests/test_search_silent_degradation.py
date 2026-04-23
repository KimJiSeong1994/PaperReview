"""Regression tests for the four HIGH-severity "silent degradation" findings
in the 2026-04-23 audit (F-04, F-07, F-08, F-09).

Each of these previously caused the search / review stack to silently:
 * return an error string as if it were a valid answer (F-04)
 * disable hybrid ranking for the entire process lifetime (F-07)
 * convert an OpenAI outage into an empty result set (F-08)
 * fabricate ``[0.5]*n`` scores on an LLM count-mismatch, dropping whole
   batches below the relevance threshold (F-09)

The tests here pin the new contract: loud failure, typed exceptions, and
a ``degraded`` marker on the API surface.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# F-04 — LLMClient.generate_response must raise, not return an error string
# ---------------------------------------------------------------------------


class TestLLMClientGenerateResponse:
    """F-04: ``LLMClient.generate_response`` must never return an error string
    or ``None`` — callers would render that as a valid answer."""

    def _make_client_with_mock(self, completion_content: object) -> object:
        """Build an LLMClient whose underlying OpenAI call returns a mocked
        ChatCompletion with ``completion_content`` in ``.choices[0].message.content``.
        """
        from src.graph_rag.llm_client import LLMClient

        client = LLMClient(api_key="sk-test-unused")
        fake_message = MagicMock()
        fake_message.content = completion_content
        fake_choice = MagicMock()
        fake_choice.message = fake_message
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]
        client.client = MagicMock()
        client.client.chat.completions.create.return_value = fake_response
        return client

    def test_empty_content_raises(self) -> None:
        from src.graph_rag.llm_client import EmptyLLMResponseError

        client = self._make_client_with_mock("")
        with pytest.raises(EmptyLLMResponseError):
            client.generate_response("ctx", "query")

    def test_whitespace_only_content_raises(self) -> None:
        from src.graph_rag.llm_client import EmptyLLMResponseError

        client = self._make_client_with_mock("   \n\t ")
        with pytest.raises(EmptyLLMResponseError):
            client.generate_response("ctx", "query")

    def test_none_content_raises(self) -> None:
        """A ``None`` content is the exact crash class that used to bubble as
        ``.strip()`` / ``json.loads`` ``TypeError``s downstream."""
        from src.graph_rag.llm_client import EmptyLLMResponseError

        client = self._make_client_with_mock(None)
        with pytest.raises(EmptyLLMResponseError):
            client.generate_response("ctx", "query")

    def test_underlying_exception_propagates(self) -> None:
        """Previously this returned ``"Error generating response: ..."`` which
        was rendered to the user as the LLM's answer."""
        from src.graph_rag.llm_client import LLMClient

        client = LLMClient(api_key="sk-test-unused")
        client.client = MagicMock()
        client.client.chat.completions.create.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError, match="boom"):
            client.generate_response("ctx", "query")

    def test_valid_content_returned_unchanged(self) -> None:
        client = self._make_client_with_mock("This is a real answer.")
        assert client.generate_response("ctx", "query") == "This is a real answer."


# ---------------------------------------------------------------------------
# F-07 — HybridRanker: import crashes loud; constructor failure emits marker
# ---------------------------------------------------------------------------


class TestHybridRankerDegradation:
    """F-07: constructor failure must not be silent.

    * The import itself stays loud — if ``HybridRanker`` cannot be imported,
      module load fails (a separate test already asserts the live module
      initialises the ranker; see ``tests/test_hybrid_ranker_import.py``).
    * On constructor failure we still keep ``_hybrid_ranker = None`` so the
      process can serve searches, but the next search response must carry
      a ``degraded=["ranker_unavailable"]`` marker.
    """

    def test_current_degradation_markers_is_none_when_healthy(self) -> None:
        from routers import search as rs

        # Empty list → None (healthy baseline on a freshly-imported module).
        with patch.object(rs, "_RANKER_DEGRADATION_REASONS", []):
            assert rs._current_degradation_markers() is None

    def test_current_degradation_markers_reports_ranker_unavailable(self) -> None:
        from routers import search as rs

        with patch.object(
            rs, "_RANKER_DEGRADATION_REASONS", ["ranker_unavailable"]
        ):
            markers = rs._current_degradation_markers()
        assert markers == ["ranker_unavailable"]

    def test_returned_markers_list_is_a_copy(self) -> None:
        """Callers must not be able to mutate module state by poking the
        returned list."""
        from routers import search as rs

        with patch.object(
            rs, "_RANKER_DEGRADATION_REASONS", ["ranker_unavailable"]
        ):
            markers = rs._current_degradation_markers()
            assert markers is not None
            markers.append("bogus")
            # Re-read — the module-level list should still be untouched.
            assert rs._current_degradation_markers() == ["ranker_unavailable"]

    @pytest.mark.asyncio
    async def test_search_response_exposes_degraded_marker(
        self, client, auth_headers
    ) -> None:
        """An end-to-end smoke test that the marker reaches the HTTP response
        body when the ranker has been flagged degraded."""
        from routers import search as rs

        # Minimal happy-path mocks for the pipeline (avoid real network /
        # real LLMs). We just need to reach the ``return SearchResponse``.
        qa_mock = MagicMock()
        qa_mock.analyze_and_prepare.return_value = {
            "is_academic": True,
            "intent": "paper_search",
            "keywords": ["test"],
            "improved_query": "test",
            "search_filters": {},
            "confidence": 0.9,
            "original_query": "test",
            "source_queries": {
                "arxiv": "test",
                "dblp": "test",
                "google_scholar": "test",
                "default": "test",
            },
        }

        sa_mock = MagicMock()

        async def _async_search(query, filters):  # noqa: ANN001
            return {"arxiv": []}

        sa_mock.async_search_with_filters.side_effect = _async_search
        sa_mock.deduplicator = MagicMock()
        sa_mock.deduplicator.deduplicate.side_effect = lambda papers: papers
        sa_mock.save_papers.return_value = {"new_papers": 0, "duplicates": 0}
        sa_mock.similarity_calculator = MagicMock()

        with (
            patch.object(rs, "_RANKER_DEGRADATION_REASONS", ["ranker_unavailable"]),
            patch.object(rs, "query_analyzer", qa_mock),
            patch.object(rs, "search_agent", sa_mock),
            patch.object(rs, "relevance_filter", None),
            patch.object(rs, "_hybrid_ranker", None),
            patch.object(rs, "_set_cache", return_value=None),
            patch.object(rs, "_get_cached_result", return_value=None),
        ):
            resp = await client.post(
                "/api/search",
                json={"query": "test", "fast_mode": True, "save_papers": False},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("degraded") == ["ranker_unavailable"], (
            "Search response must carry the degradation marker so the "
            "frontend can warn the user instead of silently serving "
            "unranked results."
        )


# ---------------------------------------------------------------------------
# F-08 — LightRetriever._get_embedding must raise EmbeddingUnavailable
# ---------------------------------------------------------------------------


class TestLightRetrieverEmbedding:
    """F-08: embedding failures must surface as ``EmbeddingUnavailable`` —
    never as ``None`` / empty result set."""

    def _make_retriever(self):
        """Build a LightRetriever bypassing __init__ heavy setup."""
        from src.light_rag.light_retriever import LightRetriever

        retriever = LightRetriever.__new__(LightRetriever)
        retriever.embedding_model = "text-embedding-3-small"
        retriever._openai_client = None  # patched per test
        retriever.kg = None
        retriever.paper_graph = None
        retriever.storage = MagicMock()
        return retriever

    def test_missing_openai_client_raises(self) -> None:
        from src.light_rag.light_retriever import EmbeddingUnavailable

        retriever = self._make_retriever()
        retriever._openai_client = None
        with pytest.raises(EmbeddingUnavailable):
            retriever._get_embedding("some query")

    def test_api_failure_raises_with_chained_cause(self) -> None:
        from src.light_rag.light_retriever import EmbeddingUnavailable

        retriever = self._make_retriever()
        retriever._openai_client = MagicMock()
        retriever._openai_client.embeddings.create.side_effect = RuntimeError(
            "429 rate limit"
        )

        with pytest.raises(EmbeddingUnavailable) as excinfo:
            retriever._get_embedding("some query")

        # The original cause must be chained for logs / 5xx translation.
        assert isinstance(excinfo.value.__cause__, RuntimeError)
        assert "429" in str(excinfo.value.__cause__)

    def test_naive_search_propagates_embedding_unavailable(self) -> None:
        """Internal search paths must let the exception bubble up — the prior
        behaviour of silently returning an empty result is gone."""
        from src.light_rag.light_retriever import EmbeddingUnavailable

        retriever = self._make_retriever()
        retriever._openai_client = MagicMock()
        retriever._openai_client.embeddings.create.side_effect = RuntimeError(
            "network down"
        )
        with pytest.raises(EmbeddingUnavailable):
            retriever._naive_search("q")


# ---------------------------------------------------------------------------
# F-09 — RelevanceFilter._evaluate_batch must not fabricate [0.5]*n
# ---------------------------------------------------------------------------


class TestRelevanceBatchCountMismatch:
    """F-09: silent ``[0.5]*n`` fabrication on count mismatch is gone.

    The new contract:
      * on mismatch, retry once with a stricter prompt
      * on persistent mismatch, raise ``RelevanceEvaluationFailed``
      * callers (``filter_papers``/``rank_papers``) may choose to fall back
        to keyword scoring, but ``_evaluate_batch`` itself must raise.
    """

    def _make_filter_with_mock_client(self, contents):
        """Build a RelevanceFilter whose ``.client`` returns, in order, the
        given JSON ``contents`` strings on successive calls."""
        from app.QueryAgent.relevance_filter import RelevanceFilter

        rf = RelevanceFilter.__new__(RelevanceFilter)
        rf.api_key = "sk-test-unused"
        rf.model = "gpt-4o-mini"
        rf.client = MagicMock()

        responses = []
        for body in contents:
            fake_message = MagicMock()
            fake_message.content = body
            fake_choice = MagicMock()
            fake_choice.message = fake_message
            fake_response = MagicMock()
            fake_response.choices = [fake_choice]
            responses.append(fake_response)

        rf.client.chat.completions.create.side_effect = responses
        return rf

    def test_mismatch_then_correct_on_retry_returns_scores(self) -> None:
        rf = self._make_filter_with_mock_client(
            [
                # First call: LLM returns one too-few score → mismatch.
                '{"scores": [0.8]}',
                # Retry: LLM obeys the strict instruction.
                '{"scores": [0.8, 0.4, 0.9]}',
            ]
        )
        papers = [{"title": f"P{i}", "abstract": ""} for i in range(3)]

        scores = rf._evaluate_batch("q", papers)

        assert scores == [0.8, 0.4, 0.9]
        # Two LLM calls: the original + exactly one retry (no infinite loop).
        assert rf.client.chat.completions.create.call_count == 2

    def test_persistent_mismatch_raises(self) -> None:
        from app.QueryAgent.relevance_filter import RelevanceEvaluationFailed

        rf = self._make_filter_with_mock_client(
            [
                '{"scores": [0.8]}',  # mismatch #1
                '{"scores": [0.8, 0.4]}',  # mismatch #2 (still wrong)
            ]
        )
        papers = [{"title": f"P{i}", "abstract": ""} for i in range(3)]

        with pytest.raises(RelevanceEvaluationFailed):
            rf._evaluate_batch("q", papers)

        # Exactly one retry, no silent fabrication.
        assert rf.client.chat.completions.create.call_count == 2

    def test_no_05_fabrication_on_mismatch(self) -> None:
        """The specific regression: batches of three papers used to all
        receive ``0.5`` when the LLM returned only one score. 0.5 < 0.65
        threshold → the batch got silently filtered out. The output must
        now be an exception, NOT a uniform-0.5 list."""
        from app.QueryAgent.relevance_filter import RelevanceEvaluationFailed

        rf = self._make_filter_with_mock_client(
            [
                '{"scores": [0.8]}',
                '{"scores": [0.8]}',
            ]
        )
        papers = [{"title": f"P{i}", "abstract": ""} for i in range(3)]

        with pytest.raises(RelevanceEvaluationFailed):
            # This call used to return ``[0.5, 0.5, 0.5]`` silently.
            rf._evaluate_batch("q", papers)

    def test_empty_llm_content_triggers_retry_then_raises(self) -> None:
        from app.QueryAgent.relevance_filter import RelevanceEvaluationFailed

        rf = self._make_filter_with_mock_client(["", ""])
        papers = [{"title": "P0", "abstract": ""}]

        with pytest.raises(RelevanceEvaluationFailed):
            rf._evaluate_batch("q", papers)

    def test_retry_prompt_is_stricter(self) -> None:
        """The retry call's user message must include the 'exactly N scores'
        instruction so we actually give the LLM a chance to comply."""
        rf = self._make_filter_with_mock_client(
            [
                '{"scores": [0.8]}',  # mismatch → triggers retry
                '{"scores": [0.8, 0.4]}',  # retry succeeds
            ]
        )
        papers = [{"title": "P0", "abstract": ""}, {"title": "P1", "abstract": ""}]

        rf._evaluate_batch("q", papers)

        assert rf.client.chat.completions.create.call_count == 2
        retry_call = rf.client.chat.completions.create.call_args_list[1]
        retry_messages = retry_call.kwargs.get("messages", [])
        user_content = next(
            (m["content"] for m in retry_messages if m["role"] == "user"), ""
        )
        assert "exactly 2 scores" in user_content, (
            "Retry pass must ask the LLM for exactly N scores, one per "
            "paper, in order — otherwise the retry is a pointless re-roll."
        )
