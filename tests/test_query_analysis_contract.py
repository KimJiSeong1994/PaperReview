"""Strict raw/normalized QueryAnalyzer contract and production-boundary parity."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.QueryAgent import query_analyzer as query_analyzer_module
from app.QueryAgent.query_analysis_contract import (
    NORMALIZED_INTENTS,
    RAW_INTENTS,
    QueryAnalysisContractError,
    normalize_query_analysis,
    parse_and_normalize_query_analysis,
    parse_raw_model_output,
    validate_normalized_query_analysis,
)
from app.QueryAgent.query_analyzer import QueryAnalyzer
from app.QueryAgent.skillopt_policy import SkillOptPolicy


def _raw(**overrides: object) -> dict:
    value = {
        "is_academic": True,
        "intent": "paper_search",
        "keywords": ["graph", "retrieval"],
        "core_concepts": ["retrieval augmented generation"],
        "research_area": "Information Retrieval",
        "improved_query": "graph retrieval augmented generation",
        "search_strategy": "search exact concepts",
        "search_filters": {
            "year_start": 2020,
            "year_end": None,
            "category": "cs.IR",
            "min_citations": 0,
        },
        "confidence": 0.9,
        "source_queries": {
            "arxiv": "ti:graph AND abs:retrieval",
            "dblp": "graph retrieval",
            "google_scholar": ["graph retrieval", "graph RAG"],
        },
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize("intent", sorted(RAW_INTENTS))
def test_raw_contract_accepts_all_eight_production_intents(intent: str) -> None:
    result = parse_raw_model_output(_raw(intent=intent))
    assert result["intent"] == intent
    assert type(result["is_academic"]) is bool
    assert type(result["confidence"]) is float


def test_normalized_contract_adds_original_defaults_and_unknown_is_fallback_only() -> (
    None
):
    raw = _raw()
    for key in ("core_concepts", "research_area", "search_strategy", "search_filters"):
        raw.pop(key)

    normalized = normalize_query_analysis(raw, original_query="original graph query")

    assert normalized == {
        "is_academic": True,
        "intent": "paper_search",
        "keywords": ["graph", "retrieval"],
        "core_concepts": [],
        "research_area": "",
        "improved_query": "graph retrieval augmented generation",
        "search_strategy": "",
        "search_filters": {},
        "confidence": 0.9,
        "original_query": "original graph query",
        "source_queries": {
            "arxiv": "ti:graph AND abs:retrieval",
            "dblp": "graph retrieval",
            "google_scholar": "graph retrieval",
            "scholar_queries": ["graph retrieval", "graph RAG"],
            "default": "original graph query",
        },
    }
    assert "unknown" not in RAW_INTENTS
    assert "unknown" in NORMALIZED_INTENTS
    with pytest.raises(QueryAnalysisContractError, match="intent"):
        parse_raw_model_output(_raw(intent="unknown"))


def test_scholar_alias_has_precedence_and_string_preserves_genuine_variant() -> None:
    aliased = _raw()
    aliased["source_queries"] = {
        "arxiv": "arxiv query",
        "dblp": "dblp query",
        "google_scholar": ["ignored google one", "ignored google two"],
        "scholar_queries": ["alias one", "alias two"],
    }
    assert normalize_query_analysis(aliased, original_query="query")[
        "source_queries"
    ] == {
        "arxiv": "arxiv query",
        "dblp": "dblp query",
        "google_scholar": "alias one",
        "scholar_queries": ["alias one", "alias two"],
        "default": "query",
    }

    string_value = _raw(
        keywords=["graph", "retrieval"],
        improved_query="improved graph query",
        source_queries={
            "arxiv": "arxiv query",
            "dblp": "dblp query",
            "google_scholar": "scholar query",
        },
    )
    variants = normalize_query_analysis(string_value, original_query="query")[
        "source_queries"
    ]["scholar_queries"]
    assert variants == ["scholar query"]

    long_keywords = _raw(
        keywords=[str(index) + "x" * 126 for index in range(16)],
        source_queries={
            "arxiv": "arxiv query",
            "dblp": "dblp query",
            "google_scholar": "scholar query",
        },
    )
    bounded = normalize_query_analysis(long_keywords, original_query="query")[
        "source_queries"
    ]["scholar_queries"]
    assert bounded == ["scholar query"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(is_academic=1), "is_academic"),
        (lambda value: value.update(confidence=True), "confidence"),
        (lambda value: value.update(confidence=1.01), "confidence"),
        (lambda value: value.update(intent="tool_call"), "intent"),
        (lambda value: value.update(keywords=["same", "ＳＡＭＥ"]), "duplicate"),
        (lambda value: value.update(keywords=["x"] * 17), "between 0 and 16"),
        (lambda value: value.update(improved_query="x" * 513), "length"),
        (lambda value: value.update(improved_query="unsafe\nquery"), "unsafe"),
        (lambda value: value.update(tool="search_web"), "unsupported keys"),
        (lambda value: value["search_filters"].update(limit=10), "unsupported keys"),
        (lambda value: value["search_filters"].update(year_start=True), "integer"),
        (lambda value: value["source_queries"].update(arxiv=["not", "text"]), "string"),
        (
            lambda value: value["source_queries"].update(extra_tool="shell"),
            "unsupported keys",
        ),
        (
            lambda value: value["source_queries"].update(
                google_scholar=["1", "2", "3", "4"]
            ),
            "between 1 and 3",
        ),
        (
            lambda value: value["source_queries"].update(google_scholar=["valid", 7]),
            "string",
        ),
    ],
)
def test_raw_contract_rejects_types_scope_flooding_and_unsafe_values(
    mutation, message: str
) -> None:
    value = _raw()
    mutation(value)
    with pytest.raises(QueryAnalysisContractError, match=message):
        parse_raw_model_output(value)


@pytest.mark.parametrize(
    "payload",
    [
        "```json\n{}\n```",
        '{"is_academic":true,"is_academic":false}',
        '{"confidence":NaN}',
        "[]",
    ],
)
def test_strict_decoder_rejects_fences_duplicates_nonfinite_and_nonobject(
    payload: str,
) -> None:
    with pytest.raises(QueryAnalysisContractError):
        parse_raw_model_output(payload)


def _completion(payload: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
    )


def _enabled_policy() -> SkillOptPolicy:
    return SkillOptPolicy(
        enabled=True,
        content="strict policy",
        content_hash="a" * 64,
        reason="enabled",
    )


def test_enabled_policy_uses_strict_contract_and_returns_normalized_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query_analyzer_module._analysis_cache.clear()
    analyzer = object.__new__(QueryAnalyzer)
    analyzer.client = object()
    analyzer.model = "fixture-model"
    monkeypatch.setattr(analyzer, "_load_skillopt_policy", _enabled_policy)
    monkeypatch.setattr(
        query_analyzer_module,
        "create_chat_completion",
        lambda *args, **kwargs: _completion(json.dumps(_raw())),
    )

    result = analyzer.analyze_and_prepare("original graph", apply_skillopt_policy=True)

    assert result["original_query"] == "original graph"
    assert result["source_queries"]["scholar_queries"] == [
        "graph retrieval",
        "graph RAG",
    ]
    assert result["source_queries"]["default"] == "original graph"


def test_malformed_enabled_policy_output_enters_existing_safe_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    query_analyzer_module._analysis_cache.clear()
    analyzer = object.__new__(QueryAnalyzer)
    analyzer.client = object()
    analyzer.model = "fixture-model"
    monkeypatch.setattr(analyzer, "_load_skillopt_policy", _enabled_policy)
    completion = MagicMock(return_value=_completion('{"is_academic":1,"tool":"shell"}'))
    monkeypatch.setattr(query_analyzer_module, "create_chat_completion", completion)
    retry_calls = {}
    for name in ("analyze_query", "classify_topic", "generate_source_specific_queries"):
        retry_calls[name] = MagicMock(side_effect=AssertionError("Unexpected extra LLM stage"))
        monkeypatch.setattr(analyzer, name, retry_calls[name])

    result = analyzer.analyze_and_prepare("safe query", apply_skillopt_policy=True)

    assert result["analysis_status"] == "unavailable_original_query"
    assert result["improved_query"] == "safe query"
    assert result["search_filters"] == {}
    assert result["source_queries"] == query_analyzer_module.normalize_source_queries("safe query")
    completion.assert_called_once()
    for retry in retry_calls.values():
        retry.assert_not_called()
    assert "analyze_and_prepare failed" in caplog.text
    assert "tool" not in result


def test_default_path_remains_permissive_and_empty_no_client_fallbacks_are_faithful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query_analyzer_module._analysis_cache.clear()
    analyzer = object.__new__(QueryAnalyzer)
    analyzer.client = object()
    analyzer.model = "fixture-model"
    permissive = _raw(is_academic=1, confidence="0.75", extra_product_field="ignored")
    monkeypatch.setattr(
        query_analyzer_module,
        "create_chat_completion",
        lambda *args, **kwargs: _completion(json.dumps(permissive)),
    )
    result = analyzer.analyze_and_prepare("query")
    assert result["is_academic"] is True
    assert result["confidence"] == 0.75

    empty = analyzer.analyze_and_prepare("  ")
    assert empty["intent"] == "unknown"
    assert empty["original_query"] == "  "
    assert empty["source_queries"] == {
        "arxiv": "  ",
        "dblp": "  ",
        "google_scholar": "  ",
        "default": "  ",
    }

    analyzer.client = None
    no_client = analyzer.analyze_and_prepare("graph retrieval")
    assert (
        no_client["analysis_details"]
        == "Fallback analysis using simple keyword extraction"
    )
    assert no_client["source_queries"] == {
        "arxiv": "graph retrieval",
        "dblp": "graph retrieval",
        "google_scholar": "graph retrieval",
        "default": "graph retrieval",
        "openalex": "graph retrieval",
        "openalex_korean": "graph retrieval",
        "scholar_queries": ["graph retrieval"],
    }
    assert no_client["analysis_status"] == "unavailable_original_query"


def test_parse_and_normalize_api_matches_two_step_api() -> None:
    payload = json.dumps(_raw())
    assert parse_and_normalize_query_analysis(
        payload, original_query="original"
    ) == normalize_query_analysis(
        parse_raw_model_output(payload), original_query="original"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["source_queries"].update(default="other"),
        lambda value: value["source_queries"].update(google_scholar="other"),
        lambda value: value.update(original_query="other"),
        lambda value: value.update(intent="unknown"),
        lambda value: value["search_filters"].update(min_citations=-1),
        lambda value: value["search_filters"].update(year_start=-1),
        lambda value: value["search_filters"].update(year_end=10000),
        lambda value: value["search_filters"].update(category="x" * 513),
        lambda value: value.update(keywords=["same", "ＳＡＭＥ"]),
        lambda value: value.update(search_strategy="unsafe\u0000text"),
    ],
)
def test_authoritative_normalized_validator_closes_pre_normalized_bypasses(
    mutation,
) -> None:
    normalized = normalize_query_analysis(_raw(), original_query="original")
    mutation(normalized)
    with pytest.raises(QueryAnalysisContractError):
        validate_normalized_query_analysis(normalized, original_query="original")


def test_unknown_requires_explicit_fallback_provenance_and_exact_semantics() -> None:
    fallback = normalize_query_analysis(_raw(), original_query="original")
    fallback.update(
        intent="unknown",
        keywords=[],
        core_concepts=[],
        research_area="",
        improved_query="original",
        search_strategy="",
        search_filters={},
    )
    assert (
        validate_normalized_query_analysis(
            fallback, original_query="original", provenance="fallback"
        )["intent"]
        == "unknown"
    )
    with pytest.raises(QueryAnalysisContractError, match="fallback provenance"):
        validate_normalized_query_analysis(fallback, original_query="original")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("year_start", 0),
        ("year_end", 9999),
        ("min_citations", 0),
        ("category", ""),
        ("category", "x" * 512),
    ],
)
def test_raw_filter_literal_boundaries_match_normalized_contract(field, value) -> None:
    raw = _raw()
    raw["search_filters"] = {field: value}
    normalized = normalize_query_analysis(raw, original_query="original")
    assert normalized["search_filters"][field] == value
