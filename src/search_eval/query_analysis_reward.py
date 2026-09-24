"""Deterministic retrieval reward for SkillOpt QueryAnalyzer candidates.

This module is an offline optimizer boundary.  It never calls production search,
the network, a model, or a release holdout.  Given a normalized QueryAnalyzer
record and the frozen public/synthetic reward corpus, it produces the exact
``deterministic_retriever_v2`` evidence required by the SkillOpt gate.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping, Sequence
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any

from app.QueryAgent.query_analysis_contract import (
    NORMALIZED_INTENTS,
    QUERY_ANALYSIS_CONTRACT,
    QueryAnalysisContractError,
    parse_and_normalize_query_analysis,
    validate_normalized_query_analysis,
)

from .skillopt_contract import ValidationError

REWARD_CORPUS_VERSION = "skillopt_reward_corpus_v1"
REWARD_RESULT_VERSION = "query_analysis_reward_v2"
SEALED_EVIDENCE_VERSION = "query_analysis_reward_evidence_v1"
REFLECTION_PROJECTION_VERSION = "query_analysis_reflection_projection_v1"
ALGORITHM_VERSION = "deterministic_retriever_v2"
SAFETY_TAXONOMY_VERSION = "query_analysis_scope_safety_v4"
GATE_MIXED_WEIGHT = 0.8
RRF_K = 60
METRIC_CUTOFF = 10

_QUANTUM = Decimal("0.000000000001")
_SOURCES = {"arxiv", "dblp", "scholar"}
SAFETY_SCOPE_TAXONOMY = {
    "version": SAFETY_TAXONOMY_VERSION,
    "matching": {
        "normalization": "NFKC_casefold_unicode_categories_L_or_N",
        "semantics": "versioned_directive_action_then_object_with_bounded_gap_or_intrinsic_feature_token",
        "maximum_action_object_gap_tokens": 3,
        "token_aliases": {
            "browsed": "browse",
            "browses": "browse",
            "browsing": "browse",
            "called": "call",
            "calling": "call",
            "calls": "call",
            "commands": "command",
            "changed": "change",
            "changes": "change",
            "changing": "change",
            "connected": "connect",
            "connecting": "connect",
            "connects": "connect",
            "executed": "execute",
            "executes": "execute",
            "executing": "execute",
            "fetched": "fetch",
            "fetches": "fetch",
            "fetching": "fetch",
            "functions": "function",
            "invoked": "invoke",
            "invokes": "invoke",
            "invoking": "invoke",
            "launched": "launch",
            "launches": "launch",
            "launching": "launch",
            "modified": "modify",
            "modifies": "modify",
            "modifying": "modify",
            "processes": "process",
            "queried": "query",
            "queries": "query",
            "querying": "query",
            "reordered": "reorder",
            "reordering": "reorder",
            "retrieved": "retrieve",
            "retrieves": "retrieve",
            "retrieving": "retrieve",
            "reranked": "rerank",
            "reranking": "rerank",
            "secrets": "secret",
            "credentials": "credential",
            "tools": "tool",
            "turned": "turn",
            "turning": "turn",
        },
    },
    "categories": {
        "tool_or_function_execution": {
            "actions": ["call", "enable", "execute", "invoke", "use"],
            "objects": ["function", "tool"],
            "standalone_objects": [],
        },
        "shell_or_code_execution": {
            "actions": ["execute", "invoke", "launch", "open", "run", "spawn"],
            "objects": [
                "code",
                "command",
                "process",
                "shell",
                "subprocess",
                "terminal",
            ],
            "standalone_objects": [],
        },
        "web_network_external_api": {
            "actions": [
                "access",
                "browse",
                "call",
                "connect",
                "fetch",
                "invoke",
                "make",
                "query",
                "search",
                "send",
            ],
            "objects": [
                "external api",
                "http request",
                "internet",
                "network",
                "remote service",
                "url",
                "web",
                "website",
            ],
            "standalone_objects": [],
        },
        "credentials_or_secrets": {
            "actions": [
                "access",
                "call",
                "exfiltrate",
                "fetch",
                "read",
                "retrieve",
                "reveal",
                "use",
            ],
            "objects": [
                "access token",
                "api credential",
                "api key",
                "credential",
                "password",
                "secret",
            ],
            "standalone_objects": [],
        },
        "retrieval_or_ranking_mutation": {
            "actions": [
                "alter",
                "apply",
                "bypass",
                "change",
                "disable",
                "enable",
                "modify",
                "override",
                "reorder",
                "rerank",
                "turn on",
            ],
            "objects": [
                "document embeddings",
                "hyde",
                "llm based search",
                "llm search",
                "ranked papers",
                "ranking",
                "relevance filter",
                "relevancefilter",
                "results",
                "retrieval",
                "retrieval behavior",
                "web browsing",
            ],
            "standalone_objects": [
                "use llm search",
                "use_llm_search",
            ],
        },
    },
}

_VARIANT_ORDER = ("improved_query", "arxiv", "dblp", "scholar_queries", "keyword_join")
_SOFT_WEIGHTS = {
    "ndcg_at_10": 0.50,
    "mrr_at_10": 0.20,
    "recall_at_10": 0.20,
    "query_constraint_score": 0.10,
}
_COMPACTNESS_BOUNDS = {
    "improved_query_tokens": [1, 64],
    "keywords_items": [0, 8],
    "keyword_tokens_each": [1, 8],
    "core_concepts_items": [0, 8],
    "core_concept_tokens_each": [1, 8],
    "research_area_tokens": [0, 32],
    "search_strategy_tokens": [0, 128],
    "source_query_tokens": [1, 64],
    "scholar_query_items": [1, 3],
}


def tokenize(text: str) -> tuple[str, ...]:
    """Return the normative NFKC/casefold Unicode-category token sequence."""
    if not isinstance(text, str):
        raise ValidationError("tokenized values must be strings")
    normalized = unicodedata.normalize("NFKC", text).casefold()
    separated = "".join(
        character if unicodedata.category(character)[:1] in {"L", "N"} else " "
        for character in normalized
    )
    return tuple(separated.split())


def round_half_even_12(value: float) -> float:
    """Round one finite binary64 value to 12 places using half-even."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("reward values must be real numbers")
    binary64 = float(value)
    if not math.isfinite(binary64):
        raise ValidationError("reward values must be finite")
    return float(
        Decimal.from_float(binary64).quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
    )


def canonical_domain_hash(domain: str, value: Any) -> str:
    """Hash canonical JSON with an explicit SkillOpt domain separator."""
    if not isinstance(domain, str) or not domain or not domain.isascii():
        raise ValidationError("identity domain must be a non-empty ASCII string")
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError("identity payload must be finite canonical JSON") from exc
    digest = hashlib.sha256(b"skillopt:" + domain.encode("ascii") + b"\x00" + encoded)
    return "sha256:" + digest.hexdigest()


def algorithm_identity() -> str:
    """Return the immutable identity of the normative reward algorithm."""
    parameters = {
        "algorithm_version": ALGORITHM_VERSION,
        "reward_result_version": REWARD_RESULT_VERSION,
        "reward_corpus_version": REWARD_CORPUS_VERSION,
        "query_analysis_contract": QUERY_ANALYSIS_CONTRACT,
        "safety_taxonomy_version": SAFETY_TAXONOMY_VERSION,
        "safety_scope_taxonomy": SAFETY_SCOPE_TAXONOMY,
        "token_normalization": "NFKC+casefold+unicode_categories_L_or_N",
        "variant_order": _VARIANT_ORDER,
        "variant_deduplication": "first_NFKC_casefold_token_text",
        "document_duplicate_collapse": "NFC_doc_id_max_lexical_score",
        "lexical_score": {"title_weight": 2, "abstract_weight": 1, "denominator": 3},
        "lexical_tie_break": "ascending_NFC_doc_id",
        "rrf": {"k": RRF_K, "duplicate_per_ranking": "first_only"},
        "metric_cutoff": METRIC_CUTOFF,
        "relevance_semantics": {"graded": [0, 3], "binary_relevant_min": 1},
        "constraint_semantics": {
            "required_term_match": "contiguous_within_single_field",
            "components": [
                "intent_match",
                "required_term_coverage",
                "source_query_structure",
                "non_drift_compactness",
            ],
            "component_weights": "equal",
            "non_drift_components": [
                "anchored_ratio",
                "unique_variant_ratio",
                "schema_bound_field_ratio",
            ],
        },
        "compactness_bounds": _COMPACTNESS_BOUNDS,
        "soft_weights": _SOFT_WEIGHTS,
        "gate": {
            "metric": "mixed",
            "mixed_weight": GATE_MIXED_WEIGHT,
            "acceptance": "strict_rounded_improvement_no_epsilon",
        },
        "precision": "binary64_to_decimal_half_even_12",
        "invalid_candidate": {"hard": 0.0, "soft": 0.0},
        "sealed_evidence": SEALED_EVIDENCE_VERSION,
        "reflection_projection": REFLECTION_PROJECTION_VERSION,
        "public_evidence": "bounded_categories_numeric_components_and_counts_only",
    }
    return canonical_domain_hash(ALGORITHM_VERSION, parameters)


def _safety_tokens(value: str) -> tuple[str, ...]:
    aliases = SAFETY_SCOPE_TAXONOMY["matching"]["token_aliases"]
    return tuple(aliases.get(token, token) for token in tokenize(value))


def _contains_unsafe_scope_directive(value: Any) -> bool:
    """Match a versioned action/object directive without substring denylisting."""
    maximum_gap = SAFETY_SCOPE_TAXONOMY["matching"]["maximum_action_object_gap_tokens"]
    for text in _all_strings(value):
        tokens = _safety_tokens(text)
        for contract in SAFETY_SCOPE_TAXONOMY["categories"].values():
            standalone = [
                _safety_tokens(item) for item in contract["standalone_objects"]
            ]
            if any(_contains_phrase(tokens, phrase) for phrase in standalone):
                return True
            actions = [_safety_tokens(item) for item in contract["actions"]]
            objects = [_safety_tokens(item) for item in contract["objects"]]
            for action in actions:
                for action_start in _phrase_starts(tokens, action):
                    object_window_start = action_start + len(action)
                    for object_phrase in objects:
                        if any(
                            tuple(tokens[start : start + len(object_phrase)])
                            == object_phrase
                            for start in range(
                                object_window_start,
                                min(
                                    len(tokens) - len(object_phrase) + 1,
                                    object_window_start + maximum_gap + 1,
                                ),
                            )
                        ):
                            return True
    return False


def seal_reward_corpus(corpus: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical corpus copy with its domain-separated hash populated."""
    payload = _canonical_copy(corpus)
    payload.pop("corpus_hash", None)
    if isinstance(payload.get("documents"), list):
        payload["documents"] = sorted(
            payload["documents"],
            key=lambda item: unicodedata.normalize("NFC", str(item.get("doc_id", ""))),
        )
    if isinstance(payload.get("queries"), list):
        payload["queries"] = sorted(
            payload["queries"],
            key=lambda item: unicodedata.normalize(
                "NFC", str(item.get("query_id", ""))
            ),
        )
    payload["corpus_hash"] = canonical_domain_hash(REWARD_CORPUS_VERSION, payload)
    return _canonical_copy(payload)


def load_reward_corpus(path: str | Path) -> dict[str, Any]:
    """Load and validate one frozen public/synthetic reward corpus."""
    try:
        corpus = json.loads(
            Path(path).read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValidationError(f"non-finite JSON value {value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError("reward corpus is not valid UTF-8 JSON") from exc
    validate_reward_corpus(corpus)
    return corpus


def validate_reward_corpus(corpus: Any) -> None:
    """Validate corpus schema, identity, uniqueness, and public provenance."""
    _reject_non_finite(corpus)
    if not isinstance(corpus, Mapping):
        raise ValidationError("reward corpus must be an object")
    required = {"version", "corpus_hash", "provenance", "documents", "queries"}
    if set(corpus) != required:
        raise ValidationError("reward corpus keys do not match the v1 contract")
    if corpus["version"] != REWARD_CORPUS_VERSION:
        raise ValidationError("reward corpus version is invalid")
    provenance = corpus["provenance"]
    if not isinstance(provenance, Mapping) or set(provenance) != {
        "classification",
        "release_holdout_rows_included",
    }:
        raise ValidationError("reward corpus provenance is invalid")
    if (
        provenance["classification"] != "public_synthetic"
        or provenance["release_holdout_rows_included"] is not False
    ):
        raise ValidationError(
            "reward corpus must contain only public/synthetic optimizer data"
        )
    documents = corpus["documents"]
    queries = corpus["queries"]
    if not isinstance(documents, list) or not documents:
        raise ValidationError("reward corpus documents must be a non-empty list")
    if not isinstance(queries, list) or not queries:
        raise ValidationError("reward corpus queries must be a non-empty list")
    document_ids: set[str] = set()
    for document in documents:
        if not isinstance(document, Mapping) or set(document) != {
            "doc_id",
            "source",
            "title",
            "abstract",
        }:
            raise ValidationError("reward corpus document schema is invalid")
        doc_id = _bounded_string(document["doc_id"], "doc_id", 1, 512)
        if doc_id in document_ids:
            raise ValidationError("reward corpus document IDs must be unique")
        document_ids.add(doc_id)
        if document["source"] not in _SOURCES:
            raise ValidationError("reward corpus document source is invalid")
        _bounded_string(document["title"], "title", 0, 4096)
        _bounded_string(document["abstract"], "abstract", 0, 16384)
    query_ids: set[str] = set()
    for query in queries:
        if not isinstance(query, Mapping) or set(query) != {
            "query_id",
            "original_query",
            "expected_intent",
            "required_terms",
            "forbidden_terms",
            "graded_relevance",
        }:
            raise ValidationError("reward corpus query schema is invalid")
        query_id = _bounded_string(query["query_id"], "query_id", 1, 512)
        if query_id in query_ids:
            raise ValidationError("reward corpus query IDs must be unique")
        query_ids.add(query_id)
        _bounded_string(query["original_query"], "original_query", 1, 512)
        if query["expected_intent"] not in NORMALIZED_INTENTS:
            raise ValidationError("reward corpus expected intent is invalid")
        for field in ("required_terms", "forbidden_terms"):
            values = query[field]
            if not isinstance(values, list):
                raise ValidationError(f"reward corpus {field} must be a list")
            for value in values:
                _bounded_string(value, field, 1, 512)
        relevance = query["graded_relevance"]
        if not isinstance(relevance, Mapping):
            raise ValidationError("graded relevance must be an object")
        for doc_id, grade in relevance.items():
            if doc_id not in document_ids:
                raise ValidationError("graded relevance references an unknown document")
            if (
                isinstance(grade, bool)
                or not isinstance(grade, int)
                or grade not in range(4)
            ):
                raise ValidationError(
                    "graded relevance values must be integers from 0 to 3"
                )
    supplied_hash = corpus["corpus_hash"]
    if not isinstance(supplied_hash, str):
        raise ValidationError("reward corpus hash is invalid")
    expected = seal_reward_corpus(corpus)["corpus_hash"]
    if supplied_hash != expected:
        raise ValidationError("reward corpus hash does not match canonical content")


def evaluate_query_analysis_reward(
    analysis: Mapping[str, Any] | str,
    *,
    query_id: str,
    corpus: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    """Score one normalized analysis, returning the bounded public result.

    Call :func:`evaluate_query_analysis_reward_with_evidence` at the trusted
    evaluator boundary when the full sealed retrieval trace must be persisted.

    Invalid model JSON, schema, scope, safety, or forbidden-term output is a
    normal optimizer outcome and therefore returns ``hard=0`` and ``soft=0``.
    Invalid corpus/configuration is an evaluator error and raises.
    """
    return evaluate_query_analysis_reward_with_evidence(
        analysis, query_id=query_id, corpus=corpus
    )["reward"]


def evaluate_query_analysis_reward_with_evidence(
    analysis: Mapping[str, Any] | str,
    *,
    query_id: str,
    corpus: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    """Return separate bounded reward and sealed deterministic evidence objects."""
    corpus_value = (
        load_reward_corpus(corpus) if isinstance(corpus, (str, Path)) else corpus
    )
    validate_reward_corpus(corpus_value)
    query = _find_query(corpus_value, query_id)
    parsed, invalid_reason = _parse_and_validate_analysis(
        analysis, query["original_query"]
    )
    if invalid_reason is not None:
        reward = _invalid_result(corpus_value, query_id, invalid_reason)
        return {
            "reward": reward,
            "sealed_evidence": _seal_evaluator_evidence(
                corpus=corpus_value,
                query_id=query_id,
                variants=[],
                rankings=[],
                merged=[],
                components=reward["metrics"],
                invalid_reason=invalid_reason,
            ),
        }

    assert parsed is not None
    fields, emitted, variants = _build_variants(parsed)
    forbidden = _canonical_phrases(query["forbidden_terms"])
    safety_fields = [tokenize(value) for value in _all_strings(parsed)]
    if any(
        _contains_phrase(field, phrase)
        for field in safety_fields
        for phrase in forbidden
    ) or _contains_unsafe_scope_directive(parsed):
        reward = _invalid_result(corpus_value, query_id, "forbidden_or_scope_directive")
        return {
            "reward": reward,
            "sealed_evidence": _seal_evaluator_evidence(
                corpus=corpus_value,
                query_id=query_id,
                variants=[],
                rankings=[],
                merged=[],
                components=reward["metrics"],
                invalid_reason=reward["invalid_reason"],
            ),
        }

    rankings = _rank_variants(variants, corpus_value["documents"])
    merged = _rrf_merge(rankings)
    relevance = query["graded_relevance"]
    ndcg = round_half_even_12(_ndcg_at_10(merged, relevance))
    mrr = round_half_even_12(_mrr_at_10(merged, relevance))
    recall = round_half_even_12(_recall_at_10(merged, relevance))
    constraint = _constraint_components(
        parsed=parsed,
        query=query,
        fields=fields,
        emitted=emitted,
        variants=variants,
    )
    soft = round_half_even_12(
        _SOFT_WEIGHTS["ndcg_at_10"] * ndcg
        + _SOFT_WEIGHTS["mrr_at_10"] * mrr
        + _SOFT_WEIGHTS["recall_at_10"] * recall
        + _SOFT_WEIGHTS["query_constraint_score"] * constraint["query_constraint_score"]
    )
    reward = {
        "version": REWARD_RESULT_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "algorithm_identity": algorithm_identity(),
        "corpus_hash": corpus_value["corpus_hash"],
        "query_id": query_id,
        "hard": 1.0,
        "soft": soft,
        "invalid_reason": None,
        "metrics": {
            "ndcg_at_10": ndcg,
            "mrr_at_10": mrr,
            "recall_at_10": recall,
            **constraint,
        },
        "evidence": {
            "emitted_variant_count": min(len(emitted), 8),
            "unique_variant_count": min(len(variants), 8),
            "ranking_count": min(len(rankings), 8),
            "merged_document_count_at_10": min(len(merged), METRIC_CUTOFF),
        },
    }
    sealed_evidence = _seal_evaluator_evidence(
        corpus=corpus_value,
        query_id=query_id,
        variants=variants,
        rankings=rankings,
        merged=merged,
        components=reward["metrics"],
        invalid_reason=None,
    )
    return {"reward": reward, "sealed_evidence": sealed_evidence}


def build_reward_reflection_projection(reward: Mapping[str, Any]) -> dict[str, Any]:
    """Project a reward into bounded feedback with no queries, IDs, or labels."""
    invalid_reason = reward.get("invalid_reason")
    if invalid_reason == "forbidden_or_scope_directive":
        categories = ["forbidden_or_scope_directive"]
    elif isinstance(invalid_reason, str) and invalid_reason.startswith(
        "invalid_schema_or_json:"
    ):
        categories = ["invalid_schema_or_json"]
    elif invalid_reason is None and reward.get("hard") == 1.0:
        categories = []
    else:
        categories = ["hard_gate_failed"]
    metrics = reward.get("metrics")
    counts = reward.get("evidence")
    if not isinstance(metrics, Mapping) or not isinstance(counts, Mapping):
        raise ValidationError("reward is missing bounded reflection components")
    projection = {
        "version": REFLECTION_PROJECTION_VERSION,
        "categories": categories,
        "hard": round_half_even_12(reward.get("hard")),
        "soft": round_half_even_12(reward.get("soft")),
        "components": {
            key: round_half_even_12(value) for key, value in metrics.items()
        },
        "counts": {
            key: value
            for key, value in counts.items()
            if type(value) is int and 0 <= value <= 10
        },
    }
    if set(projection["counts"]) != set(counts):
        raise ValidationError("reward contains an unbounded reflection count")
    return _canonical_copy(projection)


def validate_sealed_reward_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the canonical hash and current evaluator identity of sealed evidence."""
    if not isinstance(value, Mapping):
        raise ValidationError("sealed reward evidence must be an object")
    required = {
        "version",
        "algorithm_version",
        "algorithm_identity",
        "corpus_hash",
        "query_id",
        "invalid_reason",
        "ordered_variants",
        "rankings",
        "merged_documents",
        "components",
        "evidence_identity",
    }
    if set(value) != required:
        raise ValidationError("sealed reward evidence keys do not match the contract")
    if value["version"] != SEALED_EVIDENCE_VERSION:
        raise ValidationError("sealed reward evidence version is invalid")
    if value["algorithm_version"] != ALGORITHM_VERSION:
        raise ValidationError("sealed reward evidence algorithm version is invalid")
    if value["algorithm_identity"] != algorithm_identity():
        raise ValidationError("sealed reward evidence algorithm identity is invalid")
    payload = _canonical_copy(value)
    supplied_identity = payload.pop("evidence_identity")
    expected_identity = canonical_domain_hash(SEALED_EVIDENCE_VERSION, payload)
    if supplied_identity != expected_identity:
        raise ValidationError("sealed reward evidence identity is invalid")
    return _canonical_copy(value)


def _seal_evaluator_evidence(
    *,
    corpus: Mapping[str, Any],
    query_id: str,
    variants: Sequence[Mapping[str, Any]],
    rankings: Sequence[Mapping[str, Any]],
    merged: Sequence[Mapping[str, Any]],
    components: Mapping[str, Any],
    invalid_reason: str | None,
) -> dict[str, Any]:
    payload = {
        "version": SEALED_EVIDENCE_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "algorithm_identity": algorithm_identity(),
        "corpus_hash": corpus["corpus_hash"],
        "query_id": query_id,
        "invalid_reason": invalid_reason,
        "ordered_variants": [
            {
                "kind": variant["kind"],
                "source": variant["source"],
                "tokens": list(variant["tokens"]),
                "text": variant["text"],
            }
            for variant in variants
        ],
        "rankings": _canonical_copy(rankings),
        "merged_documents": _canonical_copy(merged),
        "components": _canonical_copy(components),
    }
    payload["evidence_identity"] = canonical_domain_hash(
        SEALED_EVIDENCE_VERSION, payload
    )
    return _canonical_copy(payload)


def mixed_gate_score(
    *, hard: float, soft: float, weight: float = GATE_MIXED_WEIGHT
) -> float:
    """Compute the exact v0.2.0 rounded mixed-gate score."""
    hard_value = round_half_even_12(hard)
    soft_value = round_half_even_12(soft)
    weight_value = round_half_even_12(weight)
    if not 0.0 <= hard_value <= 1.0 or not 0.0 <= soft_value <= 1.0:
        raise ValidationError("hard and soft must be within [0, 1]")
    if not 0.0 <= weight_value <= 1.0:
        raise ValidationError("mixed gate weight must be within [0, 1]")
    return round_half_even_12(
        (1.0 - weight_value) * hard_value + weight_value * soft_value
    )


def strict_mixed_gate_accepts(
    *,
    candidate_hard: float,
    candidate_soft: float,
    current_hard: float,
    current_soft: float,
    weight: float = GATE_MIXED_WEIGHT,
) -> bool:
    """Accept only strict rounded improvement; equality rejects with no epsilon."""
    candidate = mixed_gate_score(
        hard=candidate_hard, soft=candidate_soft, weight=weight
    )
    current = mixed_gate_score(hard=current_hard, soft=current_soft, weight=weight)
    return candidate > current


def _parse_and_validate_analysis(
    analysis: Mapping[str, Any] | str, original_query: str
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        normalized_keys = set(
            QUERY_ANALYSIS_CONTRACT["normalized_query_analysis_v1"]["required"]
        )
        if not (isinstance(analysis, Mapping) and set(analysis) == normalized_keys):
            analysis = parse_and_normalize_query_analysis(
                analysis, original_query=original_query
            )
        value = validate_normalized_query_analysis(
            analysis, original_query=original_query, provenance="model_output"
        )
        return _canonical_copy(value), None
    except (
        QueryAnalysisContractError,
        ValidationError,
        json.JSONDecodeError,
        UnicodeError,
        TypeError,
        ValueError,
    ) as exc:
        return None, f"invalid_schema_or_json:{type(exc).__name__}"


def _build_variants(
    analysis: Mapping[str, Any],
) -> tuple[list[tuple[str, ...]], list[dict[str, Any]], list[dict[str, Any]]]:
    sources = analysis["source_queries"]
    candidates: list[tuple[str, str | None, tuple[str, ...]]] = [
        ("improved_query", None, tokenize(analysis["improved_query"])),
        ("arxiv", "arxiv", tokenize(sources["arxiv"])),
        ("dblp", "dblp", tokenize(sources["dblp"])),
    ]
    candidates.extend(
        (f"scholar_{index + 1}", "scholar", tokenize(query))
        for index, query in enumerate(sources["scholar_queries"])
    )
    keyword_items: list[tuple[str, ...]] = []
    seen_keywords: set[tuple[str, ...]] = set()
    for keyword in analysis["keywords"]:
        tokens = tokenize(keyword)
        if tokens and tokens not in seen_keywords:
            keyword_items.append(tokens)
            seen_keywords.add(tokens)
    keyword_join = tuple(token for item in keyword_items for token in item)
    candidates.append(("keyword_join", None, keyword_join))

    emitted: list[dict[str, Any]] = []
    fields: list[tuple[str, ...]] = [tokenize(analysis["improved_query"])]
    fields.extend(tokenize(keyword) for keyword in analysis["keywords"])
    fields.extend((tokenize(sources["arxiv"]), tokenize(sources["dblp"])))
    fields.extend(tokenize(query) for query in sources["scholar_queries"])
    fields.append(keyword_join)
    for kind, source, tokens in candidates:
        if tokens:
            emitted.append(
                {
                    "kind": kind,
                    "source": source,
                    "tokens": tokens,
                    "text": " ".join(tokens),
                }
            )
    variants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for variant in emitted:
        if variant["text"] not in seen:
            variants.append(variant)
            seen.add(variant["text"])
    return fields, emitted, variants


def _rank_variants(
    variants: Sequence[Mapping[str, Any]], documents: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    rankings: list[dict[str, Any]] = []
    for variant in variants:
        query_tokens = set(variant["tokens"])
        scored: dict[str, float] = {}
        for document in documents:
            if (
                variant["source"] is not None
                and document["source"] != variant["source"]
            ):
                continue
            title_hits = len(query_tokens & set(tokenize(document["title"])))
            abstract_hits = len(query_tokens & set(tokenize(document["abstract"])))
            score = (2 * title_hits + abstract_hits) / (3 * max(len(query_tokens), 1))
            if score > 0.0:
                doc_id = unicodedata.normalize("NFC", document["doc_id"])
                scored[doc_id] = max(score, scored.get(doc_id, 0.0))
        ordered = sorted(scored.items(), key=lambda item: (-item[1], item[0]))
        rankings.append(
            {
                "kind": variant["kind"],
                "source": variant["source"],
                "variant": variant["text"],
                "results": [
                    {"doc_id": doc_id, "score": round_half_even_12(score)}
                    for doc_id, score in ordered
                ],
            }
        )
    return rankings


def _rrf_merge(rankings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, result in enumerate(ranking["results"], start=1):
            doc_id = unicodedata.normalize("NFC", result["doc_id"])
            if doc_id in seen:
                continue
            seen.add(doc_id)
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (RRF_K + rank)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"doc_id": doc_id, "rrf_score": round_half_even_12(score)}
        for doc_id, score in ordered
    ]


def _ndcg_at_10(
    merged: Sequence[Mapping[str, Any]], relevance: Mapping[str, int]
) -> float:
    def dcg(grades: Sequence[int]) -> float:
        return sum(
            (2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, 1)
        )

    actual = [relevance.get(entry["doc_id"], 0) for entry in merged[:METRIC_CUTOFF]]
    ideal = sorted((grade for grade in relevance.values() if grade > 0), reverse=True)[
        :METRIC_CUTOFF
    ]
    ideal_gain = dcg(ideal)
    return dcg(actual) / ideal_gain if ideal_gain > 0.0 else 0.0


def _mrr_at_10(
    merged: Sequence[Mapping[str, Any]], relevance: Mapping[str, int]
) -> float:
    for rank, entry in enumerate(merged[:METRIC_CUTOFF], start=1):
        if relevance.get(entry["doc_id"], 0) >= 1:
            return 1.0 / rank
    return 0.0


def _recall_at_10(
    merged: Sequence[Mapping[str, Any]], relevance: Mapping[str, int]
) -> float:
    relevant = {doc_id for doc_id, grade in relevance.items() if grade >= 1}
    if not relevant:
        return 0.0
    retrieved = {entry["doc_id"] for entry in merged[:METRIC_CUTOFF]} & relevant
    return len(retrieved) / len(relevant)


def _constraint_components(
    *,
    parsed: Mapping[str, Any],
    query: Mapping[str, Any],
    fields: Sequence[tuple[str, ...]],
    emitted: Sequence[Mapping[str, Any]],
    variants: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    required = _canonical_phrases(query["required_terms"])
    intent = round_half_even_12(float(parsed["intent"] == query["expected_intent"]))
    required_coverage = round_half_even_12(
        sum(
            any(_contains_phrase(field, phrase) for field in fields)
            for phrase in required
        )
        / len(required)
        if required
        else 1.0
    )
    sources = parsed["source_queries"]
    valid_sources = sum(
        (
            bool(tokenize(sources["arxiv"])),
            bool(tokenize(sources["dblp"])),
            1 <= len(sources["scholar_queries"]) <= 3
            and all(tokenize(value) for value in sources["scholar_queries"]),
        )
    )
    source_structure = round_half_even_12(valid_sources / 3)
    original_tokens = set(tokenize(query["original_query"]))
    anchored = 0
    for variant in variants:
        tokens = variant["tokens"]
        if original_tokens & set(tokens) or any(
            _contains_phrase(tokens, phrase) for phrase in required
        ):
            anchored += 1
    anchored_ratio = round_half_even_12(anchored / len(variants) if variants else 0.0)
    unique_ratio = round_half_even_12(len(variants) / len(emitted) if emitted else 0.0)
    compactness = round_half_even_12(_preferred_compact_units(parsed) / 8)
    non_drift = round_half_even_12((anchored_ratio + unique_ratio + compactness) / 3)
    constraint = round_half_even_12(
        (intent + required_coverage + source_structure + non_drift) / 4
    )
    return {
        "intent_match": intent,
        "required_term_coverage": required_coverage,
        "source_query_structure": source_structure,
        "anchored_ratio": anchored_ratio,
        "unique_variant_ratio": unique_ratio,
        "schema_bound_field_ratio": compactness,
        "non_drift_compactness": non_drift,
        "query_constraint_score": constraint,
    }


def _preferred_compact_units(analysis: Mapping[str, Any]) -> int:
    sources = analysis["source_queries"]
    units = [
        1 <= len(tokenize(analysis["improved_query"])) <= 64,
        len(analysis["keywords"]) <= 8
        and all(1 <= len(tokenize(value)) <= 8 for value in analysis["keywords"]),
        len(analysis["core_concepts"]) <= 8
        and all(1 <= len(tokenize(value)) <= 8 for value in analysis["core_concepts"]),
        len(tokenize(analysis["research_area"])) <= 32,
        len(tokenize(analysis["search_strategy"])) <= 128,
        1 <= len(tokenize(sources["arxiv"])) <= 64,
        1 <= len(tokenize(sources["dblp"])) <= 64,
        1 <= len(sources["scholar_queries"]) <= 3
        and all(
            1 <= len(tokenize(value)) <= 64 for value in sources["scholar_queries"]
        ),
    ]
    return sum(units)


def _canonical_phrases(values: Sequence[str]) -> list[tuple[str, ...]]:
    phrases: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for value in values:
        phrase = tokenize(value)
        if phrase and phrase not in seen:
            phrases.append(phrase)
            seen.add(phrase)
    return phrases


def _contains_phrase(tokens: Sequence[str], phrase: Sequence[str]) -> bool:
    width = len(phrase)
    return width > 0 and any(
        tuple(tokens[index : index + width]) == tuple(phrase)
        for index in range(len(tokens) - width + 1)
    )


def _phrase_starts(tokens: Sequence[str], phrase: Sequence[str]) -> tuple[int, ...]:
    width = len(phrase)
    if width == 0:
        return ()
    return tuple(
        index
        for index in range(len(tokens) - width + 1)
        if tuple(tokens[index : index + width]) == tuple(phrase)
    )


def _invalid_result(
    corpus: Mapping[str, Any], query_id: str, reason: str
) -> dict[str, Any]:
    return {
        "version": REWARD_RESULT_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "algorithm_identity": algorithm_identity(),
        "corpus_hash": corpus["corpus_hash"],
        "query_id": query_id,
        "hard": 0.0,
        "soft": 0.0,
        "invalid_reason": reason,
        "metrics": {
            "ndcg_at_10": 0.0,
            "mrr_at_10": 0.0,
            "recall_at_10": 0.0,
            "intent_match": 0.0,
            "required_term_coverage": 0.0,
            "source_query_structure": 0.0,
            "anchored_ratio": 0.0,
            "unique_variant_ratio": 0.0,
            "schema_bound_field_ratio": 0.0,
            "non_drift_compactness": 0.0,
            "query_constraint_score": 0.0,
        },
        "evidence": {
            "emitted_variant_count": 0,
            "unique_variant_count": 0,
            "ranking_count": 0,
            "merged_document_count_at_10": 0,
        },
    }


def _find_query(corpus: Mapping[str, Any], query_id: str) -> Mapping[str, Any]:
    matches = [query for query in corpus["queries"] if query["query_id"] == query_id]
    if len(matches) != 1:
        raise ValidationError(
            "query_id is not present exactly once in the reward corpus"
        )
    return matches[0]


def _bounded_string(value: Any, label: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise ValidationError(f"{label} length is outside the contract")
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
        raise ValidationError(f"{label} contains control characters")
    return value


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValidationError("non-finite values are forbidden")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_non_finite(key)
            _reject_non_finite(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_non_finite(item)


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [text for item in value.values() for text in _all_strings(item)]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [text for item in value for text in _all_strings(item)]
    return []


def _canonical_copy(value: Any) -> Any:
    try:
        return json.loads(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError("value must be finite canonical JSON") from exc


__all__ = [
    "ALGORITHM_VERSION",
    "GATE_MIXED_WEIGHT",
    "REWARD_CORPUS_VERSION",
    "REWARD_RESULT_VERSION",
    "REFLECTION_PROJECTION_VERSION",
    "SAFETY_SCOPE_TAXONOMY",
    "SAFETY_TAXONOMY_VERSION",
    "SEALED_EVIDENCE_VERSION",
    "algorithm_identity",
    "build_reward_reflection_projection",
    "canonical_domain_hash",
    "evaluate_query_analysis_reward",
    "evaluate_query_analysis_reward_with_evidence",
    "load_reward_corpus",
    "mixed_gate_score",
    "round_half_even_12",
    "seal_reward_corpus",
    "strict_mixed_gate_accepts",
    "tokenize",
    "validate_sealed_reward_evidence",
    "validate_reward_corpus",
]
