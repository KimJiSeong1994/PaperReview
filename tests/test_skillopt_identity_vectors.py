import copy
import json
from pathlib import Path

from src.search_eval import query_analysis_reward as reward
from src.search_eval.query_analysis_reward import algorithm_identity, seal_reward_corpus

CORPUS = (
    Path(__file__).resolve().parents[1]
    / "data/search_eval/skillopt_reward_corpus_v1.json"
)


def test_reward_identity_is_domain_separated_and_content_sensitive():
    corpus = json.loads(CORPUS.read_text())
    assert algorithm_identity() != corpus["corpus_hash"]
    changed = copy.deepcopy(corpus)
    changed["queries"][0]["expected_intent"] = "survey"
    assert seal_reward_corpus(changed)["corpus_hash"] != corpus["corpus_hash"]


def test_corpus_file_and_mapping_key_order_do_not_change_identity():
    corpus = json.loads(CORPUS.read_text())
    reversed_keys = {key: corpus[key] for key in reversed(corpus)}
    reversed_keys["documents"] = list(reversed(reversed_keys["documents"]))
    reversed_keys["queries"] = list(reversed(reversed_keys["queries"]))
    assert seal_reward_corpus(reversed_keys)["corpus_hash"] == corpus["corpus_hash"]


def test_every_normative_table_family_is_bound_into_algorithm_identity(monkeypatch):
    baseline = algorithm_identity()
    mutations = [
        ("ALGORITHM_VERSION", "deterministic_retriever_mutated"),
        ("REWARD_RESULT_VERSION", "query_analysis_reward_mutated"),
        ("REWARD_CORPUS_VERSION", "skillopt_reward_corpus_mutated"),
        ("SAFETY_TAXONOMY_VERSION", "query_analysis_scope_safety_mutated"),
        ("SEALED_EVIDENCE_VERSION", "query_analysis_reward_evidence_mutated"),
        (
            "REFLECTION_PROJECTION_VERSION",
            "query_analysis_reflection_projection_mutated",
        ),
        ("_VARIANT_ORDER", tuple(reversed(reward._VARIANT_ORDER))),
        ("_SOFT_WEIGHTS", {**reward._SOFT_WEIGHTS, "ndcg_at_10": 0.49}),
        (
            "_COMPACTNESS_BOUNDS",
            {**reward._COMPACTNESS_BOUNDS, "research_area_tokens": [0, 31]},
        ),
        ("RRF_K", reward.RRF_K + 1),
        ("METRIC_CUTOFF", reward.METRIC_CUTOFF - 1),
        ("GATE_MIXED_WEIGHT", 0.7),
        (
            "SAFETY_SCOPE_TAXONOMY",
            {**reward.SAFETY_SCOPE_TAXONOMY, "version": "mutated"},
        ),
        (
            "QUERY_ANALYSIS_CONTRACT",
            {**reward.QUERY_ANALYSIS_CONTRACT, "semantic_identity": "mutated"},
        ),
    ]
    for name, value in mutations:
        with monkeypatch.context() as scoped:
            scoped.setattr(reward, name, value)
            assert algorithm_identity() != baseline, name
