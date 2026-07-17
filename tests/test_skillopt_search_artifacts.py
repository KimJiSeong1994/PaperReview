"""SkillOpt paper-search PR1 artifact contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.search_eval.skillopt_adapter import canonical_file_hash
from src.search_eval.skillopt_contract import (
    ValidationError,
    load_json,
    validate_candidate_artifact,
    validate_dataset_contract,
    validate_execution_control,
    validate_rollback_record,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/search_eval/skillopt_paper_search_v0.json"
CONTROL = ROOT / "data/search_eval/skillopt_execution_control_v0.json"
CANDIDATE = ROOT / "data/search_eval/skillopt_candidate_artifact_example.json"
ROLLBACK = ROOT / "data/search_eval/skillopt_rollback_record_example.json"
BASELINE_SKILL = ROOT / "docs/skillopt_search/baseline_skill.md"


def test_skillopt_dataset_contract_is_valid():
    dataset = load_json(DATASET)

    validate_dataset_contract(dataset)

    assert dataset["dataset_hash"]
    assert dataset["primary_metric"] == "nDCG@10"
    assert dataset["provenance"]["raw_user_logs_included"] is False


def test_dataset_contract_rejects_content_mutation_with_retained_hash():
    dataset = load_json(DATASET)
    dataset["queries"][0]["query_text"] = "tampered but otherwise valid query"

    with pytest.raises(ValidationError, match="canonical dataset content"):
        validate_dataset_contract(dataset)


def test_skillopt_dataset_group_split_has_no_leakage():
    dataset = load_json(DATASET)
    groups_by_split: dict[str, set[str]] = {"train": set(), "selection": set(), "test": set()}
    for query in dataset["queries"]:
        groups_by_split[query["split"]].add(query["group_id"])

    assert groups_by_split["train"].isdisjoint(groups_by_split["selection"])
    assert groups_by_split["train"].isdisjoint(groups_by_split["test"])
    assert groups_by_split["selection"].isdisjoint(groups_by_split["test"])


def test_skillopt_dataset_selection_split_covers_live_gate_intents():
    dataset = load_json(DATASET)

    validate_dataset_contract(dataset)

    selection_intents = {query["intent"] for query in dataset["queries"] if query["split"] == "selection"}
    assert {"author_search", "method_search"} <= selection_intents
    assert sum(1 for query in dataset["queries"] if query["split"] == "selection") >= 2


def test_dataset_contract_rejects_selection_split_without_method_holdout():
    dataset = dict(load_json(DATASET))
    dataset["queries"] = [
        query
        for query in dataset["queries"]
        if query["query_id"] != "q-selection-method-resnet"
    ]

    with pytest.raises(ValidationError, match="selection split.*at least two|selection split missing"):
        validate_dataset_contract(dataset)


def test_execution_control_matrix_locks_v1_scope():
    control = load_json(CONTROL)

    validate_execution_control(control)

    assert control["control_hash"]
    assert control["scope"] == "query_analyzer_standard_search"
    assert control["fast_mode"] is False
    assert control["use_llm_search"] is False
    assert control["hyde_policy"]["promotion_in_scope"] is False
    assert control["relevance_filter_policy"]["promotion_in_scope"] is False


def test_candidate_artifact_has_rollback_and_matching_hashes():
    dataset = load_json(DATASET)
    control = load_json(CONTROL)
    artifact = load_json(CANDIDATE)

    validate_candidate_artifact(artifact, dataset=dataset, execution_control=control)

    assert artifact["baseline_hash"] == canonical_file_hash(BASELINE_SKILL)
    assert artifact["rollback_to"]["skill_hash"] == artifact["baseline_hash"]
    assert artifact["rollout_metadata"]["skill_hash"] == artifact["skill_hash"]
    assert artifact["metric_snapshot"]["primary_metric"] == "nDCG@10"
    assert artifact["metric_snapshot"]["candidate"] >= artifact["metric_snapshot"]["baseline"]


def test_candidate_artifact_rejects_mismatched_dataset_hash():
    artifact = dict(load_json(CANDIDATE))
    dataset = dict(load_json(DATASET))
    dataset["dataset_hash"] = "different_dataset_hash"

    with pytest.raises(ValidationError, match="dataset_hash"):
        validate_candidate_artifact(artifact, dataset=dataset)


def test_candidate_artifact_rejects_missing_rollout_metadata():
    artifact = dict(load_json(CANDIDATE))
    artifact["rollout_metadata"] = {"skill_hash": artifact["skill_hash"]}

    with pytest.raises(ValidationError, match="rollout_metadata missing"):
        validate_candidate_artifact(artifact)


def test_candidate_artifact_rejects_rollout_metadata_hash_drift():
    artifact = dict(load_json(CANDIDATE))
    artifact["rollout_metadata"] = dict(artifact["rollout_metadata"])
    artifact["rollout_metadata"]["execution_control_hash"] = "different_control"

    with pytest.raises(ValidationError, match="execution_control_hash"):
        validate_candidate_artifact(artifact)


def test_candidate_artifact_rejects_hyde_enabled_rollout_metadata():
    artifact = dict(load_json(CANDIDATE))
    artifact["rollout_metadata"] = dict(artifact["rollout_metadata"])
    artifact["rollout_metadata"]["hyde_enabled"] = True

    with pytest.raises(ValidationError, match="hyde_enabled"):
        validate_candidate_artifact(artifact)


def test_candidate_artifact_rejects_cache_status_rollout_drift():
    artifact = dict(load_json(CANDIDATE))
    artifact["rollout_metadata"] = dict(artifact["rollout_metadata"])
    artifact["rollout_metadata"]["cache_status"] = "warm_shared_cache"

    with pytest.raises(ValidationError, match="cache_status"):
        validate_candidate_artifact(artifact)


def test_candidate_artifact_rejects_budget_branch_rollout_drift():
    artifact = dict(load_json(CANDIDATE))
    artifact["rollout_metadata"] = dict(artifact["rollout_metadata"])
    artifact["rollout_metadata"]["budget_branch"] = "candidate_budget"

    with pytest.raises(ValidationError, match="budget_branch"):
        validate_candidate_artifact(artifact)


def test_candidate_artifact_rejects_low_query_analysis_confidence():
    artifact = dict(load_json(CANDIDATE))
    artifact["rollout_metadata"] = dict(artifact["rollout_metadata"])
    artifact["rollout_metadata"]["query_analysis_confidence"] = 0.1

    with pytest.raises(ValidationError, match="below execution-control minimum"):
        validate_candidate_artifact(artifact)


def test_dataset_contract_rejects_raw_user_logs():
    dataset = dict(load_json(DATASET))
    dataset["provenance"] = dict(dataset["provenance"])
    dataset["provenance"]["raw_user_logs_included"] = True

    with pytest.raises(ValidationError, match="raw user logs"):
        validate_dataset_contract(dataset)


def test_dataset_contract_rejects_empty_dataset_hash():
    dataset = dict(load_json(DATASET))
    dataset["dataset_hash"] = ""

    with pytest.raises(ValidationError, match="dataset_hash"):
        validate_dataset_contract(dataset)


def test_dataset_contract_rejects_missing_guardrail_metrics():
    dataset = dict(load_json(DATASET))
    dataset["guardrail_metrics"] = []

    with pytest.raises(ValidationError, match="guardrail_metrics missing"):
        validate_dataset_contract(dataset)


def test_dataset_contract_rejects_duplicate_guardrail_metrics():
    dataset = dict(load_json(DATASET))
    dataset["guardrail_metrics"] = [*dataset["guardrail_metrics"], dataset["guardrail_metrics"][0]]

    with pytest.raises(ValidationError, match="duplicates"):
        validate_dataset_contract(dataset)


def test_execution_control_rejects_empty_control_hash():
    control = dict(load_json(CONTROL))
    control["control_hash"] = ""

    with pytest.raises(ValidationError, match="control_hash"):
        validate_execution_control(control)


def test_execution_control_rejects_content_mutation_with_retained_hash():
    control = load_json(CONTROL)
    control["version"] = "execution-control-v0-tampered"

    with pytest.raises(ValidationError, match="canonical control content"):
        validate_execution_control(control)


def test_execution_control_rejects_confidence_gate_drift():
    control = dict(load_json(CONTROL))
    control["query_analyzer_confidence_gate"] = dict(control["query_analyzer_confidence_gate"])
    control["query_analyzer_confidence_gate"]["minimum_confidence"] = 0.1

    with pytest.raises(ValidationError, match="minimum_confidence"):
        validate_execution_control(control)


def test_execution_control_rejects_confidence_gate_extra_keys():
    control = dict(load_json(CONTROL))
    control["query_analyzer_confidence_gate"] = dict(control["query_analyzer_confidence_gate"])
    control["query_analyzer_confidence_gate"]["candidate_override"] = True

    with pytest.raises(ValidationError, match="candidate_override"):
        validate_execution_control(control)


def test_execution_control_rejects_overlap_gate_drift():
    control = dict(load_json(CONTROL))
    control["improved_query_overlap_gate"] = dict(control["improved_query_overlap_gate"])
    control["improved_query_overlap_gate"]["minimum_overlap"] = 0.1

    with pytest.raises(ValidationError, match="minimum_overlap"):
        validate_execution_control(control)


def test_execution_control_rejects_cache_policy_drift():
    control = dict(load_json(CONTROL))
    control["cache_policy"] = "warm_shared_cache"

    with pytest.raises(ValidationError, match="cache_policy"):
        validate_execution_control(control)


def test_execution_control_rejects_budget_policy_drift():
    control = dict(load_json(CONTROL))
    control["budget_policy"] = dict(control["budget_policy"])
    control["budget_policy"]["mode"] = "candidate_budget"

    with pytest.raises(ValidationError, match="budget_policy"):
        validate_execution_control(control)


def test_execution_control_rejects_budget_policy_extra_keys():
    control = dict(load_json(CONTROL))
    control["budget_policy"] = dict(control["budget_policy"])
    control["budget_policy"]["candidate_budget_override"] = True

    with pytest.raises(ValidationError, match="candidate_budget_override"):
        validate_execution_control(control)


def test_execution_control_rejects_hyde_enabled_for_v1():
    control = dict(load_json(CONTROL))
    control["hyde_policy"] = dict(control["hyde_policy"])
    control["hyde_policy"]["enabled"] = True

    with pytest.raises(ValidationError, match="hyde_policy.enabled"):
        validate_execution_control(control)


def test_execution_control_rejects_hyde_candidate_prompt_drift():
    control = dict(load_json(CONTROL))
    control["hyde_policy"] = dict(control["hyde_policy"])
    control["hyde_policy"]["candidate_prompt_path"] = "hyde_v2.md"

    with pytest.raises(ValidationError, match="hyde_policy"):
        validate_execution_control(control)


def test_execution_control_rejects_hyde_candidate_prompt_alias_drift():
    control = dict(load_json(CONTROL))
    control["hyde_policy"] = dict(control["hyde_policy"])
    control["hyde_policy"]["candidate_prompt_text"] = "new prompt"

    with pytest.raises(ValidationError, match="hyde_policy"):
        validate_execution_control(control)


def test_execution_control_rejects_llm_search_for_v1():
    control = dict(load_json(CONTROL))
    control["use_llm_search"] = True

    with pytest.raises(ValidationError, match="use_llm_search=false"):
        validate_execution_control(control)


def test_execution_control_rejects_relevance_filter_drift():
    control = dict(load_json(CONTROL))
    control["relevance_filter_policy"] = dict(control["relevance_filter_policy"])
    control["relevance_filter_policy"]["llm_fallback"] = "candidate_prompt_v2"

    with pytest.raises(ValidationError, match="llm_fallback"):
        validate_execution_control(control)


def test_execution_control_rejects_relevance_filter_candidate_prompt_alias():
    control = dict(load_json(CONTROL))
    control["relevance_filter_policy"] = dict(control["relevance_filter_policy"])
    control["relevance_filter_policy"]["candidate_prompt_text"] = "new prompt"

    with pytest.raises(ValidationError, match="relevance_filter_policy"):
        validate_execution_control(control)


def test_execution_control_rejects_duplicate_rollout_metadata():
    control = dict(load_json(CONTROL))
    control["required_rollout_metadata"] = [*control["required_rollout_metadata"], "skill_hash"]

    with pytest.raises(ValidationError, match="duplicates"):
        validate_execution_control(control)


def test_candidate_artifact_rejects_metric_regression():
    artifact = dict(load_json(CANDIDATE))
    artifact["metric_snapshot"] = dict(artifact["metric_snapshot"])
    artifact["metric_snapshot"]["baseline"] = 0.7
    artifact["metric_snapshot"]["candidate"] = 0.6

    with pytest.raises(ValidationError, match="must not regress"):
        validate_candidate_artifact(artifact)


def test_candidate_artifact_rejects_missing_or_nonnumeric_guardrails():
    artifact = dict(load_json(CANDIDATE))
    artifact["metric_snapshot"] = dict(artifact["metric_snapshot"])
    artifact["metric_snapshot"]["guardrails"] = {"MRR@10": "not_numeric"}

    with pytest.raises(ValidationError, match="guardrails missing"):
        validate_candidate_artifact(artifact)


def test_candidate_artifact_rejects_missing_dataset_declared_guardrail():
    dataset = load_json(DATASET)
    artifact = dict(load_json(CANDIDATE))
    artifact["metric_snapshot"] = dict(artifact["metric_snapshot"])
    artifact["metric_snapshot"]["guardrails"] = dict(artifact["metric_snapshot"]["guardrails"])
    artifact["metric_snapshot"]["guardrails"].pop("Recall@10")

    with pytest.raises(ValidationError, match="Recall@10"):
        validate_candidate_artifact(artifact, dataset=dataset)


def test_candidate_artifact_rejects_bool_metrics():
    artifact = dict(load_json(CANDIDATE))
    artifact["metric_snapshot"] = dict(artifact["metric_snapshot"])
    artifact["metric_snapshot"]["baseline"] = False

    with pytest.raises(ValidationError, match="baseline"):
        validate_candidate_artifact(artifact)


def test_candidate_artifact_rejects_non_finite_json_metric(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"metric": NaN}', encoding="utf-8")

    with pytest.raises(ValidationError, match="non-finite"):
        load_json(path)


def test_candidate_artifact_rejects_empty_hashes_and_bad_timestamp():
    artifact = dict(load_json(CANDIDATE))
    artifact["skill_hash"] = ""
    artifact["created_at"] = "not-a-date"

    with pytest.raises(ValidationError, match="skill_hash"):
        validate_candidate_artifact(artifact)

    artifact = dict(load_json(CANDIDATE))
    artifact["created_at"] = "not-a-date"
    with pytest.raises(ValidationError, match="created_at"):
        validate_candidate_artifact(artifact)


def test_dataset_contract_rejects_private_query_text():
    dataset = dict(load_json(DATASET))
    dataset["queries"] = [dict(query) for query in dataset["queries"]]
    dataset["queries"][0]["query_text"] = "john.doe@example.com private rejected query from raw user logs"

    with pytest.raises(ValidationError, match="private or raw-log"):
        validate_dataset_contract(dataset)


@pytest.mark.parametrize("field", ["group_id", "intent", "locale", "difficulty", "downstream"])
def test_dataset_contract_rejects_private_query_metadata_fields(field: str):
    dataset = dict(load_json(DATASET))
    dataset["queries"] = [dict(query) for query in dataset["queries"]]
    dataset["queries"][0][field] = "john.doe@example.com private rejected query from raw user logs"

    with pytest.raises(ValidationError, match="private or raw-log"):
        validate_dataset_contract(dataset)


@pytest.mark.parametrize("phrase", ["raw user identifiers", "private query", "private queries"])
def test_dataset_contract_rejects_private_provenance_strings(phrase: str):
    dataset = dict(load_json(DATASET))
    dataset["provenance"] = dict(dataset["provenance"])
    dataset["provenance"]["privacy_review"] = f"john.doe@example.com {phrase}"

    with pytest.raises(ValidationError, match="private or raw-log"):
        validate_dataset_contract(dataset)


def test_candidate_artifact_rejects_guardrail_threshold_breach():
    artifact = dict(load_json(CANDIDATE))
    artifact["metric_snapshot"] = dict(artifact["metric_snapshot"])
    artifact["metric_snapshot"]["guardrails"] = dict(artifact["metric_snapshot"]["guardrails"])
    artifact["metric_snapshot"]["guardrails"]["wrong_paper_handoff_rate"] = 1.0

    with pytest.raises(ValidationError, match="wrong_paper_handoff_rate"):
        validate_candidate_artifact(artifact)


def test_candidate_artifact_rejects_latency_threshold_breach():
    artifact = dict(load_json(CANDIDATE))
    artifact["metric_snapshot"] = dict(artifact["metric_snapshot"])
    artifact["metric_snapshot"]["guardrails"] = dict(artifact["metric_snapshot"]["guardrails"])
    artifact["metric_snapshot"]["guardrails"]["p95_latency_ms"] = 999999

    with pytest.raises(ValidationError, match="p95_latency_ms"):
        validate_candidate_artifact(artifact)


def test_candidate_artifact_rejects_rollback_target_drift():
    artifact = dict(load_json(CANDIDATE))
    artifact["rollback_to"] = dict(artifact["rollback_to"])
    artifact["rollback_to"]["skill_hash"] = "wrong_baseline_hash"

    with pytest.raises(ValidationError, match="baseline_hash"):
        validate_candidate_artifact(artifact)


def test_baseline_skill_documents_non_negotiable_scope():
    text = BASELINE_SKILL.read_text(encoding="utf-8")

    assert "QueryAnalyzer standard search path" in text
    assert "Do not include `use_llm_search`" in text
    assert "HyDE prompt optimization" in text
    assert "RelevanceFilter prompt optimization" in text
    assert "production behavior unchanged" in text


def test_rollback_record_disables_feature_flag_and_quarantines_candidate():
    record = load_json(ROLLBACK)
    artifact = load_json(CANDIDATE)

    validate_rollback_record(record, artifact=artifact)

    assert record["feature_flag_after"] is False
    assert record["quarantined_candidate"] is True
    assert record["rollback_to_skill_hash"] == canonical_file_hash(BASELINE_SKILL)
    assert record["api_contract_unchanged"] is True


def test_rollback_record_rejects_reenabled_feature_flag():
    record = dict(load_json(ROLLBACK))
    record["feature_flag_after"] = True

    with pytest.raises(ValidationError, match="feature_flag_after"):
        validate_rollback_record(record)


def test_rollback_record_rejects_empty_reason():
    record = dict(load_json(ROLLBACK))
    record["reason"] = ""

    with pytest.raises(ValidationError, match="reason"):
        validate_rollback_record(record)


def test_rollback_record_rejects_unknown_trigger():
    record = dict(load_json(ROLLBACK))
    record["triggered_by"] = "unknown"

    with pytest.raises(ValidationError, match="triggered_by"):
        validate_rollback_record(record)


def test_rollback_record_rejects_candidate_hash_drift():
    record = dict(load_json(ROLLBACK))
    artifact = dict(load_json(CANDIDATE))
    record["from_candidate_hash"] = "different_candidate"

    with pytest.raises(ValidationError, match="from_candidate_hash"):
        validate_rollback_record(record, artifact=artifact)


def test_search_eval_is_not_imported_by_production_modules():
    excluded_parts = {".venv", "tests", "docs", "search_eval", "deep_review_eval", "__pycache__"}
    hits = []
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if any(part in excluded_parts for part in relative.parts):
            continue
        text = path.read_text(encoding="utf-8")
        if "search_eval" in text or "deep_review_eval" in text:
            hits.append(str(relative))

    assert hits == []


def test_search_eval_fixtures_are_not_gitignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "!data/search_eval/" in gitignore
    assert "!data/search_eval/*.json" in gitignore
    for path in (DATASET, CONTROL, CANDIDATE, ROLLBACK):
        assert path.exists(), path
        json.loads(path.read_text(encoding="utf-8"))


def test_search_eval_package_is_excluded_from_distribution():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'exclude = ["src.search_eval*", "src.deep_review_eval*"]' in pyproject


def test_candidate_artifact_standalone_requires_full_v1_guardrails():
    artifact = load_json(CANDIDATE)
    artifact["metric_snapshot"] = dict(artifact["metric_snapshot"])
    artifact["metric_snapshot"]["guardrails"] = dict(artifact["metric_snapshot"]["guardrails"])
    for name in ["Recall@10", "token_estimate", "cost_estimate"]:
        artifact["metric_snapshot"]["guardrails"].pop(name)

    with pytest.raises(ValidationError, match="guardrails missing"):
        validate_candidate_artifact(artifact)
