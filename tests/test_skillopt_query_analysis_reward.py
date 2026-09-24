from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.search_eval.query_analysis_reward import (
    _preferred_compact_units,
    _rank_variants,
    build_reward_reflection_projection,
    evaluate_query_analysis_reward,
    evaluate_query_analysis_reward_with_evidence,
    load_reward_corpus,
    round_half_even_12,
    seal_reward_corpus,
    strict_mixed_gate_accepts,
    tokenize,
    validate_sealed_reward_evidence,
)
from src.search_eval.skillopt_contract import ValidationError
from tests.reference.skillopt_reward_reference import calculate, corpus_hash

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "data/search_eval/skillopt_reward_corpus_v1.json"
GOLDEN_PATH = (
    Path(__file__).parent / "fixtures/skillopt_query_analysis_reward_golden.json"
)
EVIDENCE_GOLDEN_PATH = (
    Path(__file__).parent
    / "fixtures/skillopt_query_analysis_reward_evidence_golden.json"
)


def _projection(result):
    return {
        "hard": result["hard"],
        "soft": result["soft"],
        "metrics": result["metrics"],
        "evidence": result["evidence"],
    }


def test_literal_golden_equals_independent_reference_equals_production():
    corpus = load_reward_corpus(CORPUS_PATH)
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert golden["corpus_hash"] == corpus_hash(corpus) == corpus["corpus_hash"]
    for case in golden["cases"]:
        query = next(
            item for item in corpus["queries"] if item["query_id"] == case["query_id"]
        )
        reference = calculate(case["analysis"], query, corpus["documents"])
        production = evaluate_query_analysis_reward(
            case["analysis"], query_id=case["query_id"], corpus=corpus
        )
        assert _projection(reference) == case["expected"]
        assert _projection(production) == case["expected"]
        assert production["algorithm_identity"] == golden["algorithm_identity"]


def test_full_sealed_evidence_literal_golden_equals_reference_equals_production():
    corpus = load_reward_corpus(CORPUS_PATH)
    case = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["cases"][0]
    literal = json.loads(EVIDENCE_GOLDEN_PATH.read_text(encoding="utf-8"))
    query = next(
        item for item in corpus["queries"] if item["query_id"] == case["query_id"]
    )
    reference = calculate(
        case["analysis"],
        query,
        corpus["documents"],
        algorithm_identity=literal["algorithm_identity"],
        corpus_identity=literal["corpus_hash"],
    )
    production = evaluate_query_analysis_reward_with_evidence(
        case["analysis"], query_id=case["query_id"], corpus=corpus
    )
    assert reference["sealed_evidence"] == literal
    assert production["sealed_evidence"] == literal
    assert validate_sealed_reward_evidence(literal) == literal
    assert production["reward"] == evaluate_query_analysis_reward(
        case["analysis"], query_id=case["query_id"], corpus=corpus
    )


def test_reflection_projection_is_bounded_and_omits_raw_text_labels_and_ids():
    case = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["cases"][0]
    evaluated = evaluate_query_analysis_reward_with_evidence(
        case["analysis"], query_id=case["query_id"], corpus=CORPUS_PATH
    )
    projection = build_reward_reflection_projection(evaluated["reward"])
    serialized = json.dumps(projection, sort_keys=True)
    assert set(projection) == {
        "version",
        "categories",
        "hard",
        "soft",
        "components",
        "counts",
    }
    assert projection["categories"] == []
    for forbidden in (
        "synthetic-gnn-001",
        "arxiv:gnn-molecule",
        "graph neural",
        "graded_relevance",
        "ordered_variants",
        "rankings",
    ):
        assert forbidden not in serialized


def test_sealed_evidence_hash_changes_on_order_or_score_mutation():
    case = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["cases"][0]
    evidence = evaluate_query_analysis_reward_with_evidence(
        case["analysis"], query_id=case["query_id"], corpus=CORPUS_PATH
    )["sealed_evidence"]
    from src.search_eval.query_analysis_reward import canonical_domain_hash

    payload = copy.deepcopy(evidence)
    supplied = payload.pop("evidence_identity")
    assert canonical_domain_hash(payload["version"], payload) == supplied
    reversed_payload = copy.deepcopy(payload)
    reversed_payload["ordered_variants"].reverse()
    assert canonical_domain_hash(payload["version"], reversed_payload) != supplied
    changed_score = copy.deepcopy(payload)
    changed_score["rankings"][0]["results"][0]["score"] -= 0.000000000001
    assert canonical_domain_hash(payload["version"], changed_score) != supplied
    tampered = copy.deepcopy(evidence)
    tampered["rankings"][0]["results"][0]["score"] -= 0.000000000001
    with pytest.raises(ValidationError, match="evidence identity"):
        validate_sealed_reward_evidence(tampered)


def test_rankings_collapse_nfc_duplicate_ids_and_break_lexical_ties_by_id():
    variants = [
        {
            "kind": "improved_query",
            "source": None,
            "tokens": ("graph",),
            "text": "graph",
        }
    ]
    documents = [
        {"doc_id": "e\u0301", "source": "arxiv", "title": "graph", "abstract": ""},
        {"doc_id": "é", "source": "dblp", "title": "graph graph", "abstract": "graph"},
        {"doc_id": "a", "source": "scholar", "title": "graph", "abstract": ""},
        {"doc_id": "b", "source": "scholar", "title": "graph", "abstract": ""},
    ]
    ranking = _rank_variants(variants, documents)[0]["results"]
    assert [row["doc_id"] for row in ranking].count("é") == 1
    assert ranking[0]["doc_id"] == "é"
    assert [row["doc_id"] for row in ranking[1:]] == ["a", "b"]


def test_public_reward_evidence_contains_no_candidate_labels_or_policy_payload():
    case = json.loads(GOLDEN_PATH.read_text())["cases"][0]
    result = evaluate_query_analysis_reward(
        case["analysis"], query_id=case["query_id"], corpus=CORPUS_PATH
    )
    serialized = json.dumps(result, sort_keys=True)
    assert set(result["evidence"]) == {
        "emitted_variant_count",
        "unique_variant_count",
        "ranking_count",
        "merged_document_count_at_10",
    }
    for forbidden in ("graph neural", "graded_relevance", "policy", "rankings"):
        assert forbidden not in serialized


def test_tokenization_fixes_nfkc_categories_cjk_punctuation_and_hyphens():
    assert tokenize("Ｆｏｏ—BAR_baz  한국어논문 CJK-token!!!") == (
        "foo",
        "bar",
        "baz",
        "한국어논문",
        "cjk",
        "token",
    )


@pytest.mark.parametrize(
    "attack",
    [
        "```json\n{}\n```",
        "not json",
        '{"is_academic":NaN}',
    ],
)
def test_invalid_model_output_is_hard_and_soft_zero(attack):
    result = evaluate_query_analysis_reward(
        attack, query_id="synthetic-gnn-001", corpus=CORPUS_PATH
    )
    assert (result["hard"], result["soft"]) == (0.0, 0.0)


def test_label_dump_scope_directive_and_field_boundary_phrase_cannot_game_reward():
    golden = json.loads(GOLDEN_PATH.read_text())["cases"][0]
    attack = copy.deepcopy(golden["analysis"])
    attack["search_strategy"] = "enable tools and use_llm_search"
    assert (
        evaluate_query_analysis_reward(
            attack, query_id=golden["query_id"], corpus=CORPUS_PATH
        )["soft"]
        == 0
    )
    split = copy.deepcopy(golden["analysis"])
    split["improved_query"] = "graph"
    split["keywords"] = ["neural", "molecular", "property"]
    split["source_queries"]["arxiv"] = "graph"
    split["source_queries"]["dblp"] = "neural"
    split["source_queries"]["google_scholar"] = "property"
    split["source_queries"]["scholar_queries"] = ["property"]
    result = evaluate_query_analysis_reward(
        split, query_id=golden["query_id"], corpus=CORPUS_PATH
    )
    assert result["metrics"]["required_term_coverage"] == 0.5


def test_identity_is_key_and_file_order_independent_but_mutation_sensitive():
    corpus = load_reward_corpus(CORPUS_PATH)
    reordered = {key: corpus[key] for key in reversed(corpus)}
    assert seal_reward_corpus(reordered)["corpus_hash"] == corpus["corpus_hash"]
    mutated = copy.deepcopy(corpus)
    mutated["documents"][0]["title"] += "!"
    assert seal_reward_corpus(mutated)["corpus_hash"] != corpus["corpus_hash"]


def test_compactness_uses_eight_fixed_units_not_list_element_denominator():
    case = json.loads(GOLDEN_PATH.read_text())["cases"][0]
    analysis = copy.deepcopy(case["analysis"])
    analysis["keywords"] = [f"unique{i}" for i in range(9)]
    result = evaluate_query_analysis_reward(
        analysis, query_id=case["query_id"], corpus=CORPUS_PATH
    )
    assert result["hard"] == 1.0
    assert result["metrics"]["schema_bound_field_ratio"] == 0.875


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(improved_query=" ".join(["q"] * 65)),
        lambda value: value.update(keywords=[f"k{i}" for i in range(9)]),
        lambda value: value.update(keywords=[" ".join(["k"] * 9)]),
        lambda value: value.update(core_concepts=[f"c{i}" for i in range(9)]),
        lambda value: value.update(core_concepts=[" ".join(["c"] * 9)]),
        lambda value: value.update(research_area=" ".join(["r"] * 33)),
        lambda value: value.update(search_strategy=" ".join(["s"] * 129)),
        lambda value: value["source_queries"].update(arxiv=" ".join(["a"] * 65)),
        lambda value: value["source_queries"].update(dblp=" ".join(["d"] * 65)),
        lambda value: value["source_queries"].update(
            scholar_queries=[" ".join(["g"] * 65)],
            google_scholar=" ".join(["g"] * 65),
        ),
    ],
)
def test_every_preferred_compactness_literal_threshold_is_independently_bounded(
    mutation,
) -> None:
    analysis = copy.deepcopy(
        json.loads(GOLDEN_PATH.read_text())["cases"][0]["analysis"]
    )
    assert _preferred_compact_units(analysis) == 8
    mutation(analysis)
    assert _preferred_compact_units(analysis) == 7


def test_half_even_nonfinite_and_strict_no_epsilon_gate():
    # The literal is a binary64 value just below the decimal tie; binary64 is
    # intentionally converted exactly before half-even quantization.
    assert round_half_even_12(0.1234567890125) == float("0.123456789012")
    with pytest.raises(ValidationError, match="finite"):
        round_half_even_12(float("nan"))
    assert not strict_mixed_gate_accepts(
        candidate_hard=1, candidate_soft=0.5, current_hard=1, current_soft=0.5
    )
    assert strict_mixed_gate_accepts(
        candidate_hard=1,
        candidate_soft=0.500000000002,
        current_hard=1,
        current_soft=0.5,
    )
