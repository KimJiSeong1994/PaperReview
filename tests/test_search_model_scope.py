"""Search-specific model defaults and explicit override forwarding."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest

from app.QueryAgent import query_analyzer as query_analyzer_module
from app.QueryAgent.query_analyzer import QueryAnalyzer
from app.SearchAgent import react_search_agent as react_search_agent_module
from app.SearchAgent.react_search_agent import ReActSearchAgent
from src.graph_rag import hybrid_ranker as hybrid_ranker_module
from src.graph_rag.hybrid_ranker import HybridRanker
from src.light_rag import keyword_extractor as keyword_extractor_module
from src.light_rag.keyword_extractor import KeywordExtractor
from src.utils.model_defaults import DEFAULT_SEARCH_MODEL


def _response(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.mark.parametrize(
    ("override", "expected_model"),
    [(None, DEFAULT_SEARCH_MODEL), ("query-analyzer-override", "query-analyzer-override")],
)
def test_query_analyzer_forwards_search_model_to_guard_and_planner(
    monkeypatch: pytest.MonkeyPatch, override: str | None, expected_model: str
) -> None:
    monkeypatch.setattr(query_analyzer_module, "OPENAI_AVAILABLE", False)
    monkeypatch.setattr(query_analyzer_module, "_get_from_cache", lambda _key: None)
    monkeypatch.setattr(query_analyzer_module, "_set_in_cache", lambda *_args: None)
    analyzer = QueryAnalyzer() if override is None else QueryAnalyzer(model=override)
    analyzer.client = object()

    planning_response = {
        "is_academic": True,
        "intent": "paper_search",
        "keywords": ["graph", "retrieval"],
        "core_concepts": ["graph retrieval"],
        "research_area": "Information Retrieval",
        "improved_query": "graph retrieval",
        "search_strategy": "search core terms",
        "search_filters": {},
        "confidence": 0.9,
        "source_queries": {
            "arxiv": "graph retrieval",
            "dblp": "graph retrieval",
            "google_scholar": ["graph retrieval"],
        },
    }
    responses = iter([_response('{"is_academic": true}'), _response(json.dumps(planning_response))])
    sent_models: list[str] = []

    def complete(_client, *, model: str, **_kwargs):
        sent_models.append(model)
        return next(responses)

    monkeypatch.setattr(query_analyzer_module, "create_chat_completion", complete)

    analyzer.classify_topic("query analyzer academic guard model")
    result = analyzer.analyze_and_prepare("query analyzer planning model")

    assert result["is_academic"] is True
    assert sent_models == [expected_model, expected_model]


@pytest.mark.parametrize(
    ("override", "expected_model"),
    [(None, DEFAULT_SEARCH_MODEL), ("react-search-override", "react-search-override")],
)
def test_react_search_forwards_default_or_override_to_gap_planning(
    monkeypatch: pytest.MonkeyPatch, override: str | None, expected_model: str
) -> None:
    class FakeClient:
        def with_options(self, **_options):
            return self

    sent_models: list[str] = []

    def complete(_client, *, model: str, **_kwargs):
        sent_models.append(model)
        return _response('{"is_sufficient": true, "missing": [], "next_query": "", "rationale": "enough"}')

    monkeypatch.setattr(react_search_agent_module, "create_chat_completion", complete)
    kwargs = {} if override is None else {"model": override}
    agent = ReActSearchAgent(object(), openai_client=FakeClient(), **kwargs)

    async def run_owned(function, *args, **_kwargs):
        return function(*args)

    monkeypatch.setattr(agent, "_run_owned", run_owned)
    token = react_search_agent_module._operation.set(
        (object(), time.monotonic() + 30, threading.Event())
    )
    try:
        plan = asyncio.run(
            agent._analyze_and_plan_next("graph retrieval", "paper_search", [], [])
        )
    finally:
        react_search_agent_module._operation.reset(token)

    assert plan["is_sufficient"] is True
    assert sent_models == [expected_model]


@pytest.mark.parametrize(
    ("override", "expected_model"),
    [(None, DEFAULT_SEARCH_MODEL), ("keyword-extractor-override", "keyword-extractor-override")],
)
def test_keyword_extractor_forwards_default_or_override(
    monkeypatch: pytest.MonkeyPatch, override: str | None, expected_model: str
) -> None:
    monkeypatch.setattr(keyword_extractor_module, "OPENAI_AVAILABLE", True)
    monkeypatch.setattr(keyword_extractor_module, "OpenAI", lambda **_kwargs: object())
    sent_models: list[str] = []

    def complete(_client, *, model: str, **_kwargs):
        sent_models.append(model)
        return _response('{"low_level": ["Graph"], "high_level": ["Learning"]}')

    monkeypatch.setattr(keyword_extractor_module, "create_chat_completion", complete)
    kwargs = {} if override is None else {"model": override}
    extractor = KeywordExtractor(api_key="test-key", **kwargs)

    assert extractor.extract_keywords("graph learning models") == {
        "low_level": ["graph"],
        "high_level": ["learning"],
    }
    assert sent_models == [expected_model]


def test_hybrid_ranker_hyde_and_alternative_query_paths_use_search_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            _response("Hypothetical research abstract."),
            _response("alternative query one\nalternative query two\nignored query"),
            _response(
                '{"abstract": "Unified research abstract.", '
                '"alt_queries": ["unified alternative one", "unified alternative two"]}'
            ),
        ]
    )
    sent_models: list[str] = []

    def complete(_client, *, model: str, **_kwargs):
        sent_models.append(model)
        return next(responses)

    monkeypatch.setattr(hybrid_ranker_module, "create_chat_completion", complete)
    ranker = HybridRanker.__new__(HybridRanker)
    fake_client = object()

    assert ranker._generate_hypothetical_abstract("graph retrieval", fake_client) == (
        "Hypothetical research abstract."
    )
    assert ranker._generate_alt_queries("graph retrieval", fake_client) == [
        "alternative query one",
        "alternative query two",
    ]
    assert ranker._generate_hyde_unified("graph retrieval", fake_client) == (
        "Unified research abstract.",
        ["unified alternative one", "unified alternative two"],
    )
    assert sent_models == [DEFAULT_SEARCH_MODEL] * 3
