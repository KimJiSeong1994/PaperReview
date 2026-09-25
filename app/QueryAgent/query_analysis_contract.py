"""Strict SkillOpt query-analysis input and normalization contracts.

The regular QueryAnalyzer path remains product-compatible and permissive. These
helpers define the optimization boundary: model output admitted for SkillOpt
evaluation or an enabled SkillOpt production policy must satisfy the exact raw
contract before it can become a normalized query analysis.
"""

from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Mapping
from typing import Any

RAW_MODEL_OUTPUT_VERSION = "raw_model_output_v1"
NORMALIZED_QUERY_ANALYSIS_VERSION = "normalized_query_analysis_v1"
RAW_INTENTS = frozenset(
    {
        "paper_search",
        "topic_exploration",
        "author_search",
        "method_search",
        "comparison",
        "survey",
        "latest_research",
        "problem_solving",
    }
)
NORMALIZED_INTENTS = RAW_INTENTS | {"unknown"}
RAW_REQUIRED_KEYS = frozenset(
    {
        "is_academic",
        "intent",
        "keywords",
        "improved_query",
        "confidence",
        "source_queries",
    }
)
RAW_OPTIONAL_KEYS = frozenset(
    {"core_concepts", "research_area", "search_strategy", "search_filters"}
)
RAW_ALLOWED_KEYS = RAW_REQUIRED_KEYS | RAW_OPTIONAL_KEYS
SOURCE_REQUIRED_KEYS = frozenset({"arxiv", "dblp", "google_scholar"})
SOURCE_OPTIONAL_KEYS = frozenset({"scholar_queries"})
SEARCH_FILTER_KEYS = frozenset({"year_start", "year_end", "category", "min_citations"})

MAX_JSON_BYTES = 64 * 1024
MAX_QUERY_SCALARS = 512
MAX_LIST_ITEMS = 16
MAX_LIST_ITEM_SCALARS = 128
MAX_FREE_TEXT_SCALARS = 2048
MAX_SCHOLAR_VARIANTS = 3
MIN_YEAR = 0
MAX_YEAR = 9999

# Canonical semantic artifact projected into the SkillOpt overlay. Keep this
# declaration beside the implementation so runner and production cannot drift
# through separately maintained schemas.
QUERY_ANALYSIS_CONTRACT = {
    "raw_model_output_v1": {
        "type": "object",
        "additional_properties": False,
        "required": sorted(RAW_REQUIRED_KEYS),
        "optional": sorted(RAW_OPTIONAL_KEYS),
        "max_json_bytes": MAX_JSON_BYTES,
        "fields": {
            "is_academic": {"type": "boolean"},
            "intent": {"type": "string", "allowed": sorted(RAW_INTENTS)},
            "keywords": {
                "type": "array[string]",
                "min_items": 0,
                "max_items": MAX_LIST_ITEMS,
                "item_min_length": 1,
                "item_max_length": MAX_LIST_ITEM_SCALARS,
                "duplicates": "reject_nfkc_casefold",
            },
            "core_concepts": {
                "type": "array[string]",
                "min_items": 0,
                "max_items": MAX_LIST_ITEMS,
                "item_min_length": 1,
                "item_max_length": MAX_LIST_ITEM_SCALARS,
                "duplicates": "reject_nfkc_casefold",
            },
            "research_area": {"type": "string", "min_length": 0, "max_length": 2048},
            "improved_query": {"type": "string", "min_length": 1, "max_length": 512},
            "search_strategy": {"type": "string", "min_length": 0, "max_length": 2048},
            "search_filters": {
                "type": "object",
                "additional_properties": False,
                "fields": {
                    "year_start": f"integer[{MIN_YEAR},{MAX_YEAR}]|null",
                    "year_end": f"integer[{MIN_YEAR},{MAX_YEAR}]|null",
                    "category": "string|null",
                    "min_citations": "integer>=0|null",
                },
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "source_queries": {
                "type": "object",
                "additional_properties": False,
                "required": sorted(SOURCE_REQUIRED_KEYS),
                "optional": sorted(SOURCE_OPTIONAL_KEYS),
                "fields": {
                    "arxiv": {"type": "string", "min_length": 1, "max_length": 512},
                    "dblp": {"type": "string", "min_length": 1, "max_length": 512},
                    "google_scholar": {
                        "type": "string|array[string]",
                        "string_min_length": 1,
                        "string_max_length": 512,
                        "array_min_items": 1,
                        "array_max_items": 3,
                        "duplicates": "reject_nfkc_casefold",
                    },
                    "scholar_queries": {
                        "type": "array[string]",
                        "min_items": 1,
                        "max_items": 3,
                        "item_min_length": 1,
                        "item_max_length": 512,
                        "duplicates": "reject_nfkc_casefold",
                        "precedence": "when_present_over_google_scholar",
                    },
                },
            },
        },
        "safety": {
            "json_duplicate_keys": "reject",
            "json_nonfinite_numbers": "reject",
            "markdown_fences": "reject",
            "unicode_categories": {"Cc": "reject", "Cf": "reject"},
            "boolean_is_number": False,
        },
    },
    "normalized_query_analysis_v1": {
        "type": "object",
        "additional_properties": False,
        "required": [
            "is_academic",
            "intent",
            "keywords",
            "core_concepts",
            "research_area",
            "improved_query",
            "search_strategy",
            "search_filters",
            "confidence",
            "original_query",
            "source_queries",
        ],
        "intent_allowed": sorted(NORMALIZED_INTENTS),
        "unknown_intent": "fallback_only",
        "defaults": {
            "core_concepts": [],
            "research_area": "",
            "search_strategy": "",
            "search_filters": {},
        },
        "original_query": "derived_from_input_item",
        "source_queries": {
            "required": [
                "arxiv",
                "dblp",
                "google_scholar",
                "scholar_queries",
                "default",
            ],
            "scholar_queries": {
                "type": "array[string]",
                "min_items": 1,
                "max_items": 3,
            },
            "google_scholar": "first_scholar_query",
            "default": "original_query",
            "alias_precedence": "scholar_queries_over_google_scholar",
        },
    },
}


class QueryAnalysisContractError(ValueError):
    """Raised when model output violates the SkillOpt optimization contract."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QueryAnalysisContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise QueryAnalysisContractError(f"non-finite JSON number: {value}")


def _has_unsafe_character(value: str) -> bool:
    return any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)


def _string(
    value: Any,
    field: str,
    *,
    minimum: int = 1,
    maximum: int = MAX_QUERY_SCALARS,
) -> str:
    if not isinstance(value, str):
        raise QueryAnalysisContractError(f"{field} must be a string")
    if _has_unsafe_character(value):
        raise QueryAnalysisContractError(f"{field} contains an unsafe character")
    if len(value) > maximum:
        raise QueryAnalysisContractError(f"{field} length must not exceed {maximum}")
    normalized = value.strip()
    if not minimum <= len(normalized) <= maximum:
        raise QueryAnalysisContractError(
            f"{field} length must be between {minimum} and {maximum}"
        )
    return normalized


def _unique_string_list(
    value: Any,
    field: str,
    *,
    minimum_items: int = 0,
    maximum_items: int = MAX_LIST_ITEMS,
    item_maximum: int = MAX_LIST_ITEM_SCALARS,
) -> list[str]:
    if not isinstance(value, list):
        raise QueryAnalysisContractError(f"{field} must be an array")
    if not minimum_items <= len(value) <= maximum_items:
        raise QueryAnalysisContractError(
            f"{field} must contain between {minimum_items} and {maximum_items} items"
        )
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        normalized = _string(item, f"{field}[{index}]", maximum=item_maximum)
        identity = unicodedata.normalize("NFKC", normalized).casefold()
        if identity in seen:
            raise QueryAnalysisContractError(f"{field} contains duplicate items")
        seen.add(identity)
        result.append(normalized)
    return result


def _strict_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QueryAnalysisContractError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise QueryAnalysisContractError(f"{field} must be between 0 and 1")
    return result


def _nullable_integer(
    value: Any,
    field: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise QueryAnalysisContractError(f"{field} must be an integer or null")
    if minimum is not None and value < minimum:
        raise QueryAnalysisContractError(f"{field} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise QueryAnalysisContractError(f"{field} must be at most {maximum}")
    return value


def _search_filters(value: Any) -> dict[str, int | str | None]:
    if not isinstance(value, Mapping):
        raise QueryAnalysisContractError("search_filters must be an object")
    extras = set(value) - SEARCH_FILTER_KEYS
    if extras:
        raise QueryAnalysisContractError(
            f"search_filters contains unsupported keys: {sorted(extras)}"
        )
    result: dict[str, int | str | None] = {}
    if "year_start" in value:
        result["year_start"] = _nullable_integer(
            value["year_start"],
            "search_filters.year_start",
            minimum=MIN_YEAR,
            maximum=MAX_YEAR,
        )
    if "year_end" in value:
        result["year_end"] = _nullable_integer(
            value["year_end"],
            "search_filters.year_end",
            minimum=MIN_YEAR,
            maximum=MAX_YEAR,
        )
    if "category" in value:
        category = value["category"]
        result["category"] = (
            None
            if category is None
            else _string(category, "search_filters.category", minimum=0, maximum=512)
        )
    if "min_citations" in value:
        result["min_citations"] = _nullable_integer(
            value["min_citations"], "search_filters.min_citations", minimum=0
        )
    return result


def parse_raw_model_output(
    payload: str | bytes | bytearray | Mapping[str, Any],
) -> dict[str, Any]:
    """Decode and validate ``raw_model_output_v1`` without coercion."""

    if isinstance(payload, Mapping):
        decoded: Any = dict(payload)
    else:
        if isinstance(payload, str):
            raw_bytes = payload.encode("utf-8")
            text = payload
        elif isinstance(payload, (bytes, bytearray)):
            raw_bytes = bytes(payload)
            try:
                text = raw_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise QueryAnalysisContractError(
                    "model output must be UTF-8 JSON"
                ) from exc
        else:
            raise QueryAnalysisContractError(
                "model output must be JSON text or an object"
            )
        if len(raw_bytes) > MAX_JSON_BYTES:
            raise QueryAnalysisContractError("model output exceeds the JSON size limit")
        try:
            decoded = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
        except QueryAnalysisContractError:
            raise
        except json.JSONDecodeError as exc:
            raise QueryAnalysisContractError(
                "model output must be strict JSON"
            ) from exc

    if not isinstance(decoded, Mapping):
        raise QueryAnalysisContractError("model output must be an object")
    keys = set(decoded)
    missing = RAW_REQUIRED_KEYS - keys
    extras = keys - RAW_ALLOWED_KEYS
    if missing:
        raise QueryAnalysisContractError(
            f"model output is missing keys: {sorted(missing)}"
        )
    if extras:
        raise QueryAnalysisContractError(
            f"model output contains unsupported keys: {sorted(extras)}"
        )
    if type(decoded["is_academic"]) is not bool:
        raise QueryAnalysisContractError("is_academic must be a boolean")
    intent = decoded["intent"]
    if not isinstance(intent, str) or intent not in RAW_INTENTS:
        raise QueryAnalysisContractError("intent is not an allowed production intent")

    source_queries = decoded["source_queries"]
    if not isinstance(source_queries, Mapping):
        raise QueryAnalysisContractError("source_queries must be an object")
    source_keys = set(source_queries)
    missing_sources = SOURCE_REQUIRED_KEYS - source_keys
    extra_sources = source_keys - (SOURCE_REQUIRED_KEYS | SOURCE_OPTIONAL_KEYS)
    if missing_sources:
        raise QueryAnalysisContractError(
            f"source_queries is missing keys: {sorted(missing_sources)}"
        )
    if extra_sources:
        raise QueryAnalysisContractError(
            f"source_queries contains unsupported keys: {sorted(extra_sources)}"
        )

    google_scholar = source_queries["google_scholar"]
    if isinstance(google_scholar, str):
        validated_google: str | list[str] = _string(
            google_scholar, "source_queries.google_scholar"
        )
    else:
        validated_google = _unique_string_list(
            google_scholar,
            "source_queries.google_scholar",
            minimum_items=1,
            maximum_items=MAX_SCHOLAR_VARIANTS,
            item_maximum=MAX_QUERY_SCALARS,
        )

    validated_sources: dict[str, Any] = {
        "arxiv": _string(source_queries["arxiv"], "source_queries.arxiv"),
        "dblp": _string(source_queries["dblp"], "source_queries.dblp"),
        "google_scholar": validated_google,
    }
    if "scholar_queries" in source_queries:
        validated_sources["scholar_queries"] = _unique_string_list(
            source_queries["scholar_queries"],
            "source_queries.scholar_queries",
            minimum_items=1,
            maximum_items=MAX_SCHOLAR_VARIANTS,
            item_maximum=MAX_QUERY_SCALARS,
        )

    result: dict[str, Any] = {
        "is_academic": decoded["is_academic"],
        "intent": intent,
        "keywords": _unique_string_list(decoded["keywords"], "keywords"),
        "improved_query": _string(decoded["improved_query"], "improved_query"),
        "confidence": _strict_number(decoded["confidence"], "confidence"),
        "source_queries": validated_sources,
    }
    if "core_concepts" in decoded:
        result["core_concepts"] = _unique_string_list(
            decoded["core_concepts"], "core_concepts"
        )
    if "research_area" in decoded:
        result["research_area"] = _string(
            decoded["research_area"],
            "research_area",
            minimum=0,
            maximum=MAX_FREE_TEXT_SCALARS,
        )
    if "search_strategy" in decoded:
        result["search_strategy"] = _string(
            decoded["search_strategy"],
            "search_strategy",
            minimum=0,
            maximum=MAX_FREE_TEXT_SCALARS,
        )
    if "search_filters" in decoded:
        result["search_filters"] = _search_filters(decoded["search_filters"])
    return result


def normalize_query_analysis(
    raw: Mapping[str, Any], *, original_query: str
) -> dict[str, Any]:
    """Build ``normalized_query_analysis_v1`` from a validated raw object."""

    validated = parse_raw_model_output(raw)
    _string(original_query, "original_query")
    sources = validated["source_queries"]
    scholar_source = sources.get("scholar_queries", sources["google_scholar"])
    if isinstance(scholar_source, list):
        scholar_queries = list(scholar_source)
    else:
        scholar_queries = [scholar_source]

    normalized = {
        "is_academic": validated["is_academic"],
        "intent": validated["intent"],
        "keywords": list(validated["keywords"]),
        "core_concepts": list(validated.get("core_concepts", [])),
        "research_area": validated.get("research_area", ""),
        "improved_query": validated["improved_query"],
        "search_strategy": validated.get("search_strategy", ""),
        "search_filters": dict(validated.get("search_filters", {})),
        "confidence": validated["confidence"],
        "original_query": original_query,
        "source_queries": {
            "arxiv": sources["arxiv"],
            "dblp": sources["dblp"],
            "google_scholar": scholar_queries[0],
            "scholar_queries": scholar_queries,
            "default": original_query,
        },
    }
    return validate_normalized_query_analysis(
        normalized, original_query=original_query, provenance="model_output"
    )


def validate_normalized_query_analysis(
    value: Mapping[str, Any],
    *,
    original_query: str,
    provenance: str = "model_output",
) -> dict[str, Any]:
    """Validate the sole normalized QueryAnalyzer optimization contract.

    ``unknown`` is reserved for an explicitly identified safe fallback.  The
    SkillOpt reward path uses the default ``model_output`` provenance, so a
    candidate cannot claim the fallback-only intent label.
    """

    if not isinstance(value, Mapping) or set(value) != set(
        QUERY_ANALYSIS_CONTRACT["normalized_query_analysis_v1"]["required"]
    ):
        raise QueryAnalysisContractError("normalized query analysis keys are invalid")
    if provenance not in {"model_output", "fallback"}:
        raise QueryAnalysisContractError("normalization provenance is invalid")
    checked_original = _string(original_query, "original_query")
    if type(value["is_academic"]) is not bool:
        raise QueryAnalysisContractError("is_academic must be a boolean")
    intent = value["intent"]
    if not isinstance(intent, str) or intent not in NORMALIZED_INTENTS:
        raise QueryAnalysisContractError("intent is invalid")
    if intent == "unknown":
        fallback_semantics = (
            provenance == "fallback"
            and value["is_academic"] is True
            and value["keywords"] == []
            and value["core_concepts"] == []
            and value["research_area"] == ""
            and value["search_strategy"] == ""
            and value["search_filters"] == {}
            and value["improved_query"] == checked_original
        )
        if not fallback_semantics:
            raise QueryAnalysisContractError(
                "unknown intent requires explicit fallback provenance and semantics"
            )
    elif provenance == "fallback":
        raise QueryAnalysisContractError("fallback provenance requires unknown intent")

    if value["original_query"] != checked_original:
        raise QueryAnalysisContractError("original_query must match the input item")
    keywords = _unique_string_list(value["keywords"], "keywords")
    concepts = _unique_string_list(value["core_concepts"], "core_concepts")
    research_area = _string(
        value["research_area"],
        "research_area",
        minimum=0,
        maximum=MAX_FREE_TEXT_SCALARS,
    )
    improved_query = _string(value["improved_query"], "improved_query")
    strategy = _string(
        value["search_strategy"],
        "search_strategy",
        minimum=0,
        maximum=MAX_FREE_TEXT_SCALARS,
    )
    filters = _search_filters(value["search_filters"])
    confidence = _strict_number(value["confidence"], "confidence")
    sources = value["source_queries"]
    required_sources = set(
        QUERY_ANALYSIS_CONTRACT["normalized_query_analysis_v1"]["source_queries"][
            "required"
        ]
    )
    if not isinstance(sources, Mapping) or set(sources) != required_sources:
        raise QueryAnalysisContractError("source_queries keys are invalid")
    scholar_queries = _unique_string_list(
        sources["scholar_queries"],
        "source_queries.scholar_queries",
        minimum_items=1,
        maximum_items=MAX_SCHOLAR_VARIANTS,
        item_maximum=MAX_QUERY_SCALARS,
    )
    google_scholar = _string(sources["google_scholar"], "source_queries.google_scholar")
    default = _string(sources["default"], "source_queries.default")
    if google_scholar != scholar_queries[0]:
        raise QueryAnalysisContractError(
            "source_queries.google_scholar must equal scholar_queries[0]"
        )
    if default != checked_original:
        raise QueryAnalysisContractError(
            "source_queries.default must equal original_query"
        )
    return {
        "is_academic": value["is_academic"],
        "intent": intent,
        "keywords": keywords,
        "core_concepts": concepts,
        "research_area": research_area,
        "improved_query": improved_query,
        "search_strategy": strategy,
        "search_filters": filters,
        "confidence": confidence,
        "original_query": checked_original,
        "source_queries": {
            "arxiv": _string(sources["arxiv"], "source_queries.arxiv"),
            "dblp": _string(sources["dblp"], "source_queries.dblp"),
            "google_scholar": google_scholar,
            "scholar_queries": scholar_queries,
            "default": default,
        },
    }


def parse_and_normalize_query_analysis(
    payload: str | bytes | bytearray | Mapping[str, Any], *, original_query: str
) -> dict[str, Any]:
    """Strictly decode raw output and produce its normalized representation."""

    return normalize_query_analysis(
        parse_raw_model_output(payload), original_query=original_query
    )
