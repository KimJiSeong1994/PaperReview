from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import src.search_eval.approved_policy as approved_policy_module
from src.search_eval.accepted_candidate import load_accepted_skillopt_candidate
from src.search_eval.approved_policy import (
    _validate_accepted_candidate_matches_inputs,
    export_approved_skillopt_policy,
    load_validated_approved_skillopt_policy,
    split_retrieval_evaluation_record,
    validate_approved_policy_artifact,
)
from src.search_eval.retrieval_eval import (
    assert_candidate_beats_baseline,
    build_fixture_retrieval_results,
    score_retrieval_results,
    validate_retrieval_evaluation_record,
)
from src.search_eval.skillopt_adapter import canonical_file_hash
from src.search_eval.skillopt_contract import ValidationError, load_json
from src.search_eval.skillopt_materializer import (
    ENV_NAME,
    materialize_skillopt_search_benchmark,
    validate_skillopt_materialization_manifest,
)
from src.search_eval.skillopt_run_contract import (
    AUTHORITY_CONTEXT_ENV,
    AuthorityContextRotationError,
    canonical_json_bytes,
)
from tests.skillopt_acceptance_fixtures import publish_accepted_candidate

DATASET = "data/search_eval/skillopt_paper_search_v0.json"
CONTROL = "data/search_eval/skillopt_execution_control_v0.json"
BASELINE_SKILL = "docs/skillopt_search/baseline_skill.md"


def _materialization_manifest_path(tmp_path: Path) -> Path:
    manifest = materialize_skillopt_search_benchmark(
        output_dir=tmp_path / "materialized",
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
    )
    return Path(manifest["output_dir"]) / "skillopt_materialization_manifest.json"


def _candidate_best_skill(tmp_path: Path) -> Path:
    baseline = Path(BASELINE_SKILL).read_text(encoding="utf-8")
    text = (
        baseline
        + """

## SkillOpt accepted edit — retrieval precision
- QueryAnalyzer standard search path should preserve exact paper-title and author intent first.
- Do not enable `use_llm_search` for this policy.
- Do not enable HyDE prompt optimization for this policy.
- Do not promote RelevanceFilter prompt optimization for this policy.
- Prefer source_queries that place must-include title phrases before broad acceptable synonyms.
"""
    )
    path = tmp_path / "best_skill.md"
    path.write_text(text, encoding="utf-8")
    return path


def _approval_candidate_args(tmp_path: Path, best_skill: Path) -> dict[str, str]:
    return publish_accepted_candidate(
        parent=tmp_path,
        best_skill_path=best_skill,
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
    )


def _bind_eval_to_skill(candidate_eval: dict, best_skill: Path) -> dict:
    return {**candidate_eval, "evaluated_skill_hash": canonical_file_hash(best_skill)}


def _two_stage_eval_inputs(baseline_eval: dict, candidate_eval: dict) -> dict:
    baseline_eval = _bind_eval_to_skill(baseline_eval, Path(BASELINE_SKILL))
    dataset = load_json(DATASET)
    selection_ids = [
        query["query_id"]
        for query in dataset["queries"]
        if query["split"] == "selection"
    ]
    test_ids = [
        query["query_id"] for query in dataset["queries"] if query["split"] == "test"
    ]
    selection_baseline = split_retrieval_evaluation_record(baseline_eval, selection_ids)
    selection_candidate = split_retrieval_evaluation_record(
        candidate_eval, selection_ids
    )

    def load_holdout():
        return (
            split_retrieval_evaluation_record(baseline_eval, test_ids),
            split_retrieval_evaluation_record(candidate_eval, test_ids),
        )

    return {
        "selection_baseline_eval": selection_baseline,
        "selection_candidate_eval": selection_candidate,
        "holdout_eval_loader": load_holdout,
    }


def _approved_policy(tmp_path: Path) -> dict:
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)
    return export_approved_skillopt_policy(
        **_approval_candidate_args(tmp_path, best_skill),
        output_dir=tmp_path / "approved",
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        **_two_stage_eval_inputs(baseline_eval, candidate_eval),
    )


def test_materialize_skillopt_search_benchmark_writes_official_shape(tmp_path: Path):
    manifest = materialize_skillopt_search_benchmark(
        output_dir=tmp_path,
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
    )

    validate_skillopt_materialization_manifest(manifest)
    assert manifest["env_name"] == ENV_NAME
    assert "scripts/train.py" in manifest["train_command"]
    assert "JiphyeonjeonSearchAdapter" in manifest["registration_snippet"]

    config_path = Path(manifest["config_path"])
    env_dir = Path(manifest["env_package_dir"])
    split_dir = Path(manifest["split_dir"])
    assert config_path.exists()
    assert (env_dir / "dataloader.py").exists()
    assert (env_dir / "rollout.py").exists()
    rollout_text = (env_dir / "rollout.py").read_text(encoding="utf-8")
    assert "run_target_exec" in rollout_text
    assert "conversation.json" in rollout_text
    assert "fail_reason" in rollout_text
    assert (env_dir / "adapter.py").exists()
    assert (env_dir / "skills" / "initial.md").exists()
    assert (split_dir / "train" / "items.json").exists()
    assert (split_dir / "selection" / "items.json").exists()
    assert (split_dir / "val" / "items.json").exists()
    assert (split_dir / "test" / "items.json").exists()
    assert (split_dir / "selection" / "items.json").read_text(encoding="utf-8") == (
        split_dir / "val" / "items.json"
    ).read_text(encoding="utf-8")

    train_items = json.loads(
        (split_dir / "train" / "items.json").read_text(encoding="utf-8")
    )
    selection_items = json.loads(
        (split_dir / "selection" / "items.json").read_text(encoding="utf-8")
    )
    assert train_items[0]["id"].startswith("q-train-")
    assert "labels" in train_items[0]
    assert {item["task_type"] for item in selection_items} >= {
        "author_search",
        "method_search",
    }
    assert all("split" in item for item in selection_items)
    assert all("group_id" in item for item in selection_items)


def test_retrieval_eval_scores_candidate_above_baseline():
    baseline_results = build_fixture_retrieval_results(
        dataset_path=DATASET, quality="baseline"
    )
    candidate_results = build_fixture_retrieval_results(
        dataset_path=DATASET, quality="candidate"
    )

    baseline = score_retrieval_results(
        dataset_path=DATASET, results_by_query=baseline_results
    )
    candidate = score_retrieval_results(
        dataset_path=DATASET, results_by_query=candidate_results
    )

    validate_retrieval_evaluation_record(baseline)
    validate_retrieval_evaluation_record(candidate)
    assert candidate["nDCG@10"] > baseline["nDCG@10"]
    assert candidate["wrong_paper_handoff_rate"] <= baseline["wrong_paper_handoff_rate"]
    assert_candidate_beats_baseline(
        baseline_record=baseline, candidate_record=candidate
    )


def test_retrieval_eval_labels_fixture_and_requires_measured_capture_lineage():
    results = build_fixture_retrieval_results(dataset_path=DATASET, quality="candidate")

    fixture = score_retrieval_results(dataset_path=DATASET, results_by_query=results)
    assert fixture["evidence"] == {
        "mode": "fixture",
        "capture_id": None,
        "capture_hash": None,
    }
    validate_retrieval_evaluation_record(fixture)

    with pytest.raises(ValidationError, match="requires capture_id"):
        score_retrieval_results(
            dataset_path=DATASET,
            results_by_query=results,
            evidence_mode="measured",
            p95_latency_ms=1.0,
        )
    with pytest.raises(ValidationError, match="positive p95_latency_ms"):
        score_retrieval_results(
            dataset_path=DATASET,
            results_by_query=results,
            evidence_mode="measured",
            capture_id="prod-shadow-capture-1",
            capture_hash="sha256:" + "a" * 64,
        )

    measured = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=results,
        evidence_mode="measured",
        capture_id="prod-shadow-capture-1",
        capture_hash="sha256:" + "a" * 64,
        p95_latency_ms=12.5,
    )
    validate_retrieval_evaluation_record(measured)


def test_retrieval_eval_zero_must_recall_is_not_perfect_ndcg():
    from src.search_eval.skillopt_contract import load_json

    dataset = load_json(DATASET)
    acceptable_only = {}
    for query in dataset["queries"]:
        acceptable = query["labels"].get("acceptable", [])
        acceptable_only[query["query_id"]] = (
            [
                {
                    "title": str(acceptable[0]),
                    "abstract": "acceptable only",
                    "source": "test",
                }
            ]
            if acceptable
            else []
        )

    record = score_retrieval_results(
        dataset_path=DATASET, results_by_query=acceptable_only
    )

    assert record["Recall@10"] == 0.0
    assert record["nDCG@10"] < 1.0


def test_retrieval_eval_rejects_candidate_regression():
    baseline_results = build_fixture_retrieval_results(
        dataset_path=DATASET, quality="candidate"
    )
    candidate_results = build_fixture_retrieval_results(
        dataset_path=DATASET, quality="baseline"
    )
    baseline = score_retrieval_results(
        dataset_path=DATASET, results_by_query=baseline_results
    )
    candidate = score_retrieval_results(
        dataset_path=DATASET, results_by_query=candidate_results
    )

    with pytest.raises(ValidationError, match="candidate nDCG@10"):
        assert_candidate_beats_baseline(
            baseline_record=baseline, candidate_record=candidate
        )


def test_export_approved_skillopt_policy_writes_runtime_artifacts(tmp_path: Path):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)

    artifact = export_approved_skillopt_policy(
        **_approval_candidate_args(tmp_path, best_skill),
        output_dir=tmp_path / "approved",
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        **_two_stage_eval_inputs(baseline_eval, candidate_eval),
    )

    validate_approved_policy_artifact(artifact)
    assert Path(artifact["runtime_policy_path"]).exists()
    assert Path(artifact["artifact_path"]).exists()
    assert Path(artifact["runtime_env_path"]).exists()
    assert artifact["runtime_env"]["SKILLOPT_SEARCH_POLICY_ENABLED"] == "false"
    assert (
        artifact["runtime_env"]["SKILLOPT_SEARCH_POLICY_HASH"] == artifact["skill_hash"]
    )
    assert (
        artifact["metric_snapshot"]["candidate"]
        > artifact["metric_snapshot"]["baseline"]
    )
    assert artifact["selection_gate"]["status"] == "passed"
    assert set(artifact["selection_gate"]["required_intents"]) == {
        "author_search",
        "method_search",
    }
    assert {row["intent"] for row in artifact["selection_gate"]["per_query"]} >= {
        "author_search",
        "method_search",
    }
    assert artifact["holdout_gate"]["status"] == "passed"
    assert artifact["holdout_gate"]["split"] == "test"
    assert {row["query_id"] for row in artifact["holdout_gate"]["per_query"]} >= {
        "q-test-ambiguous-agent",
        "q-test-method-bert",
    }
    assert artifact["version"] == "approved-skillopt-policy-v2"
    assert artifact["evaluation_status"] == "qualified"
    assert artifact["authorization_status"] == "not_authorized"
    assert artifact["evaluation_evidence"]["mode"] == "fixture"
    assert artifact["accepted_candidate"]["request_id"].startswith("sha256:")
    assert artifact["accepted_candidate"]["result_id"].startswith("sha256:")


def test_approval_api_has_no_arbitrary_best_skill_path_escape_hatch() -> None:
    parameters = inspect.signature(export_approved_skillopt_policy).parameters

    assert "best_skill_path" not in parameters
    assert {"acceptance_manifest_path", "run_root"} <= set(parameters)


def test_legacy_v0_approval_artifact_fails_closed_and_requires_regeneration(
    tmp_path: Path,
) -> None:
    artifact = _approved_policy(tmp_path)
    legacy = {**artifact, "version": "approved-skillopt-policy-v0"}

    with pytest.raises(ValidationError, match="version is invalid"):
        validate_approved_policy_artifact(legacy)


def test_relabelled_v0_shape_cannot_masquerade_as_v2(tmp_path: Path) -> None:
    artifact = _approved_policy(tmp_path)
    relabelled = dict(artifact)
    for field in (
        "accepted_candidate",
        "evaluation_status",
        "authorization_status",
        "evaluation_evidence",
    ):
        relabelled.pop(field)
    relabelled["version"] = "approved-skillopt-policy-v2"

    with pytest.raises(ValidationError, match="keys mismatch"):
        validate_approved_policy_artifact(relabelled)


def test_approval_threshold_cannot_be_weakened_below_one_percent(tmp_path: Path):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)

    with pytest.raises(ValidationError, match="at least 0.01"):
        export_approved_skillopt_policy(
            **_approval_candidate_args(tmp_path, best_skill),
            output_dir=tmp_path / "approved",
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            **_two_stage_eval_inputs(baseline_eval, candidate_eval),
            minimum_ndcg_delta=0.009,
        )


def test_approval_rejects_import_inputs_that_differ_from_evaluation_inputs(
    tmp_path: Path,
):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)
    artifact = export_approved_skillopt_policy(
        **_approval_candidate_args(tmp_path, best_skill),
        output_dir=tmp_path / "approved",
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        **_two_stage_eval_inputs(baseline_eval, candidate_eval),
    )
    offered_v0 = artifact.persisted_artifact()
    offered_v0["materialization_manifest_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="keys mismatch"):
        validate_approved_policy_artifact(offered_v0)


def test_approval_rejects_accepted_snapshot_change_after_loader_validation(
    tmp_path: Path,
):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)
    approval_args = _approval_candidate_args(tmp_path, best_skill)
    accepted = load_accepted_skillopt_candidate(
        acceptance_manifest_path=approval_args["acceptance_manifest_path"],
        run_root=approval_args["run_root"],
    )

    def mutate_after_load(**_kwargs):
        accepted.best_skill_path.write_text(
            "changed after validation\n", encoding="utf-8"
        )
        return accepted

    with (
        patch(
            "src.search_eval.approved_policy.load_accepted_skillopt_candidate",
            side_effect=mutate_after_load,
        ),
        pytest.raises(ValidationError, match="changed after acceptance validation"),
    ):
        export_approved_skillopt_policy(
            **approval_args,
            output_dir=tmp_path / "approved",
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            **_two_stage_eval_inputs(baseline_eval, candidate_eval),
        )


def test_exact_one_percent_metric_delta_is_accepted_without_float_drift(
    tmp_path: Path,
):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    boundary_baseline = {
        **baseline_eval,
        "nDCG@10": 0.58,
        "per_query": [
            {**row, "ndcg_at_10": 0.58} for row in baseline_eval["per_query"]
        ],
    }
    boundary_candidate = {
        **candidate_eval,
        "nDCG@10": 0.59,
        "per_query": [
            {**row, "ndcg_at_10": 0.59} for row in candidate_eval["per_query"]
        ],
    }
    assert_candidate_beats_baseline(
        baseline_record=boundary_baseline,
        candidate_record=boundary_candidate,
        minimum_delta=0.01,
    )

    artifact = _approved_policy(tmp_path)
    boundary_artifact = dict(artifact)
    boundary_artifact["metric_snapshot"] = {
        **artifact["metric_snapshot"],
        "baseline": 0.58,
        "candidate": 0.59,
    }
    validate_approved_policy_artifact(boundary_artifact)

    below_candidate = {
        **boundary_candidate,
        "nDCG@10": 0.589999,
        "per_query": [
            {**row, "ndcg_at_10": 0.589999} for row in boundary_candidate["per_query"]
        ],
    }
    with pytest.raises(ValidationError, match="candidate nDCG@10"):
        assert_candidate_beats_baseline(
            baseline_record=boundary_baseline,
            candidate_record=below_candidate,
            minimum_delta=0.01,
        )
    below_artifact = dict(boundary_artifact)
    below_artifact["metric_snapshot"] = {
        **boundary_artifact["metric_snapshot"],
        "candidate": 0.589999,
    }
    with pytest.raises(ValidationError, match="improve by at least 0.01"):
        validate_approved_policy_artifact(below_artifact)


@pytest.mark.parametrize(
    ("input_name", "argument_name"),
    (
        ("dataset", "dataset_path"),
        ("execution_control", "control_path"),
        ("baseline_skill", "baseline_skill_path"),
    ),
)
def test_each_accepted_input_hash_is_bound_to_approval_inputs(
    tmp_path: Path, input_name: str, argument_name: str
):
    best_skill = _candidate_best_skill(tmp_path)
    approval_args = _approval_candidate_args(tmp_path, best_skill)
    accepted = load_accepted_skillopt_candidate(
        acceptance_manifest_path=approval_args["acceptance_manifest_path"],
        run_root=approval_args["run_root"],
    )
    paths = {
        "dataset_path": Path(DATASET),
        "control_path": Path(CONTROL),
        "baseline_skill_path": Path(BASELINE_SKILL),
    }
    original = paths[argument_name]
    changed = tmp_path / f"changed-{original.name}"
    if input_name in {"dataset", "execution_control"}:
        changed_value = load_json(original)
        hash_field = (
            "dataset_hash" if input_name == "dataset" else "control_hash"
        )
        changed_value[hash_field] = "sha256:" + "0" * 64
        changed.write_bytes(canonical_json_bytes(changed_value))
    else:
        changed.write_bytes(original.read_bytes() + b"\n")
    paths[argument_name] = changed

    with pytest.raises(ValidationError, match=input_name):
        _validate_accepted_candidate_matches_inputs(
            accepted_input_hashes=accepted.input_artifact_hashes,
            **paths,
        )


def test_import_boundary_rejects_missing_runtime_safety_phrase(tmp_path: Path):
    bad_skill = tmp_path / "best_skill.md"
    bad_skill.write_text("# unsafe skill", encoding="utf-8")

    with pytest.raises(AssertionError, match="runtime safety phrases"):
        _approval_candidate_args(tmp_path, bad_skill)


def test_export_approved_policy_rejects_eval_skill_hash_mismatch(tmp_path: Path):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = {**candidate_eval, "evaluated_skill_hash": "sha256:" + "0" * 64}

    with pytest.raises(ValidationError, match="evaluated_skill_hash"):
        export_approved_skillopt_policy(
            **_approval_candidate_args(tmp_path, best_skill),
            output_dir=tmp_path / "approved",
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            **_two_stage_eval_inputs(baseline_eval, candidate_eval),
        )


def test_export_approved_policy_rejects_selection_baseline_skill_hash_drift(
    tmp_path: Path,
):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)
    inputs = _two_stage_eval_inputs(baseline_eval, candidate_eval)
    inputs["selection_baseline_eval"] = {
        **inputs["selection_baseline_eval"],
        "evaluated_skill_hash": "sha256:" + "0" * 64,
    }

    with pytest.raises(
        ValidationError, match="baseline evaluation evaluated_skill_hash"
    ):
        export_approved_skillopt_policy(
            **_approval_candidate_args(tmp_path, best_skill),
            output_dir=tmp_path / "approved",
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            **inputs,
        )


def test_export_approved_policy_rejects_test_baseline_skill_hash_drift(
    tmp_path: Path,
):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)
    inputs = _two_stage_eval_inputs(baseline_eval, candidate_eval)
    original_holdout_loader = inputs["holdout_eval_loader"]

    def load_tampered_holdout():
        holdout_baseline, holdout_candidate = original_holdout_loader()
        return (
            {
                **holdout_baseline,
                "evaluated_skill_hash": "sha256:" + "0" * 64,
            },
            holdout_candidate,
        )

    inputs["holdout_eval_loader"] = load_tampered_holdout
    with pytest.raises(
        ValidationError, match="baseline evaluation evaluated_skill_hash"
    ):
        export_approved_skillopt_policy(
            **_approval_candidate_args(tmp_path, best_skill),
            output_dir=tmp_path / "approved",
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            **inputs,
        )


def test_export_approved_policy_rejects_wrong_eval_query_binding(tmp_path: Path):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    candidate_eval = dict(candidate_eval)
    candidate_eval["per_query"] = list(candidate_eval["per_query"])
    selection_id = next(
        query["query_id"]
        for query in load_json(DATASET)["queries"]
        if query["split"] == "selection"
    )
    selection_index = next(
        index
        for index, row in enumerate(candidate_eval["per_query"])
        if row["query_id"] == selection_id
    )
    candidate_eval["per_query"][selection_index] = dict(
        candidate_eval["per_query"][selection_index]
    )
    candidate_eval["per_query"][selection_index]["query_id"] = "wrong-query-id"
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)

    with pytest.raises(
        ValidationError, match="missing required split rows|per_query ids"
    ):
        export_approved_skillopt_policy(
            **_approval_candidate_args(tmp_path, best_skill),
            output_dir=tmp_path / "approved",
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            **_two_stage_eval_inputs(baseline_eval, candidate_eval),
        )


def test_export_rejected_candidate_writes_no_runtime_artifacts_for_selection_gate_failure(
    tmp_path: Path,
):
    baseline_results = build_fixture_retrieval_results(
        dataset_path=DATASET, quality="baseline"
    )
    baseline_results["q-selection-method-resnet"] = []
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=baseline_results,
    )
    candidate_results = build_fixture_retrieval_results(
        dataset_path=DATASET, quality="candidate"
    )
    candidate_results["q-selection-method-resnet"] = [
        {
            "title": "ResNet",
            "abstract": "acceptable-only selection hit",
            "source": "test",
        }
    ]
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET, results_by_query=candidate_results
    )
    output_dir = tmp_path / "approved"
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)

    with pytest.raises(
        ValidationError, match="selection gate.*q-selection-method-resnet"
    ):
        export_approved_skillopt_policy(
            **_approval_candidate_args(tmp_path, best_skill),
            output_dir=output_dir,
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            **_two_stage_eval_inputs(baseline_eval, candidate_eval),
        )

    assert not (output_dir / "best_skill.md").exists()
    assert not (output_dir / "approved_policy_artifact.json").exists()
    assert not (output_dir / "runtime_env.sh").exists()


def test_export_rejected_candidate_writes_no_runtime_artifacts_for_holdout_gate_failure(
    tmp_path: Path,
):
    baseline_results = build_fixture_retrieval_results(
        dataset_path=DATASET, quality="baseline"
    )
    baseline_results["q-test-method-bert"] = []
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=baseline_results,
    )
    candidate_results = build_fixture_retrieval_results(
        dataset_path=DATASET, quality="candidate"
    )
    candidate_results["q-test-method-bert"] = [
        {
            "title": "contextual embeddings",
            "abstract": "acceptable-only holdout hit",
            "source": "test",
        }
    ]
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET, results_by_query=candidate_results
    )
    output_dir = tmp_path / "approved"
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)

    with pytest.raises(ValidationError, match="holdout gate.*q-test-method-bert"):
        export_approved_skillopt_policy(
            **_approval_candidate_args(tmp_path, best_skill),
            output_dir=output_dir,
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            **_two_stage_eval_inputs(baseline_eval, candidate_eval),
        )

    assert not (output_dir / "best_skill.md").exists()
    assert not (output_dir / "approved_policy_artifact.json").exists()
    assert not (output_dir / "runtime_env.sh").exists()


def test_retrieval_eval_rejects_forged_aggregate_metrics():
    record = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    forged = dict(record)
    forged["nDCG@10"] = 1.0

    with pytest.raises(ValidationError, match="nDCG@10.*per_query aggregate"):
        validate_retrieval_evaluation_record(forged)


def test_retrieval_eval_rejects_non_finite_guardrails():
    record = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    forged = dict(record)
    forged["p95_latency_ms"] = float("nan")

    with pytest.raises(ValidationError, match="p95_latency_ms"):
        validate_retrieval_evaluation_record(forged)


def test_approved_policy_artifact_rejects_tampered_guardrail_regression(tmp_path: Path):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)
    artifact = export_approved_skillopt_policy(
        **_approval_candidate_args(tmp_path, best_skill),
        output_dir=tmp_path / "approved",
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        **_two_stage_eval_inputs(baseline_eval, candidate_eval),
    )
    tampered = dict(artifact)
    tampered["metric_snapshot"] = dict(artifact["metric_snapshot"])
    tampered["metric_snapshot"]["guardrails"] = dict(
        artifact["metric_snapshot"]["guardrails"]
    )
    tampered["metric_snapshot"]["guardrails"]["candidate"] = dict(
        artifact["metric_snapshot"]["guardrails"]["candidate"]
    )
    tampered["metric_snapshot"]["guardrails"]["candidate"]["Recall@10"] = 0.0

    with pytest.raises(ValidationError, match="Recall@10"):
        validate_approved_policy_artifact(tampered)


def test_approved_policy_artifact_rejects_tampered_selection_gate(tmp_path: Path):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)
    artifact = export_approved_skillopt_policy(
        **_approval_candidate_args(tmp_path, best_skill),
        output_dir=tmp_path / "approved",
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        **_two_stage_eval_inputs(baseline_eval, candidate_eval),
    )
    tampered = dict(artifact)
    tampered["selection_gate"] = dict(artifact["selection_gate"])
    tampered["selection_gate"]["per_query"] = list(
        artifact["selection_gate"]["per_query"]
    )
    tampered["selection_gate"]["per_query"][0] = dict(
        tampered["selection_gate"]["per_query"][0]
    )
    tampered["selection_gate"]["per_query"][0]["passed"] = False

    with pytest.raises(ValidationError, match="selection_gate"):
        validate_approved_policy_artifact(tampered)


def test_approved_policy_artifact_rejects_zero_ndcg_selection_gate(tmp_path: Path):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)
    artifact = export_approved_skillopt_policy(
        **_approval_candidate_args(tmp_path, best_skill),
        output_dir=tmp_path / "approved",
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        **_two_stage_eval_inputs(baseline_eval, candidate_eval),
    )
    tampered = dict(artifact)
    tampered["selection_gate"] = dict(artifact["selection_gate"])
    tampered["selection_gate"]["per_query"] = list(
        artifact["selection_gate"]["per_query"]
    )
    tampered["selection_gate"]["per_query"][0] = dict(
        tampered["selection_gate"]["per_query"][0]
    )
    tampered["selection_gate"]["per_query"][0]["ndcg_at_10"] = 0.0

    with pytest.raises(ValidationError, match="evidence_hash"):
        validate_approved_policy_artifact(tampered)


def test_approved_policy_artifact_rejects_tampered_holdout_gate(tmp_path: Path):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)
    artifact = export_approved_skillopt_policy(
        **_approval_candidate_args(tmp_path, best_skill),
        output_dir=tmp_path / "approved",
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        **_two_stage_eval_inputs(baseline_eval, candidate_eval),
    )
    tampered = dict(artifact)
    tampered["holdout_gate"] = dict(artifact["holdout_gate"])
    tampered["holdout_gate"]["per_query"] = list(artifact["holdout_gate"]["per_query"])
    tampered["holdout_gate"]["per_query"][0] = dict(
        tampered["holdout_gate"]["per_query"][0]
    )
    tampered["holdout_gate"]["per_query"][0]["recall_at_10"] = 0.0

    with pytest.raises(ValidationError, match="holdout_gate"):
        validate_approved_policy_artifact(tampered)


def test_export_rejects_test_split_regression_hidden_by_global_improvement(
    tmp_path: Path,
):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    test_ids = {
        query["query_id"]
        for query in load_json(DATASET)["queries"]
        if query["split"] == "test"
    }
    candidate_eval["per_query"] = [dict(row) for row in candidate_eval["per_query"]]
    for row in candidate_eval["per_query"]:
        if row["query_id"] in test_ids:
            row["ndcg_at_10"] = 0.001
            row["recall_at_10"] = 0.001
    count = len(candidate_eval["per_query"])
    candidate_eval["nDCG@10"] = round(
        sum(row["ndcg_at_10"] for row in candidate_eval["per_query"]) / count,
        6,
    )
    candidate_eval["Recall@10"] = round(
        sum(row["recall_at_10"] for row in candidate_eval["per_query"]) / count,
        6,
    )
    assert candidate_eval["nDCG@10"] > baseline_eval["nDCG@10"]
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)

    with pytest.raises(ValidationError, match="candidate nDCG@10|holdout gate"):
        export_approved_skillopt_policy(
            **_approval_candidate_args(tmp_path, best_skill),
            output_dir=tmp_path / "approved",
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            **_two_stage_eval_inputs(baseline_eval, candidate_eval),
        )


def test_selection_failure_never_opens_holdout_evaluation(tmp_path: Path):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    best_skill = _candidate_best_skill(tmp_path)
    selection_ids = [
        query["query_id"]
        for query in load_json(DATASET)["queries"]
        if query["split"] == "selection"
    ]
    selection_baseline = split_retrieval_evaluation_record(baseline_eval, selection_ids)
    selection_baseline = _bind_eval_to_skill(selection_baseline, Path(BASELINE_SKILL))
    selection_candidate = {
        **selection_baseline,
        "evaluated_skill_hash": canonical_file_hash(best_skill),
    }
    holdout_opened = False

    def forbidden_holdout_loader():
        nonlocal holdout_opened
        holdout_opened = True
        raise AssertionError("holdout must remain sealed when selection fails")

    with pytest.raises(ValidationError, match="candidate nDCG@10"):
        export_approved_skillopt_policy(
            **_approval_candidate_args(tmp_path, best_skill),
            output_dir=tmp_path / "approved",
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            selection_baseline_eval=selection_baseline,
            selection_candidate_eval=selection_candidate,
            holdout_eval_loader=forbidden_holdout_loader,
            minimum_ndcg_delta=0.01,
        )

    assert holdout_opened is False


def test_selection_and_holdout_evidence_bind_distinct_records(tmp_path: Path):
    artifact = _approved_policy(tmp_path)

    assert artifact["metric_snapshot"]["split"] == "selection"
    assert (
        artifact["selection_gate"]["candidate_eval_hash"]
        == artifact["metric_snapshot"]["candidate_eval_hash"]
    )
    assert (
        artifact["selection_gate"]["candidate_eval_hash"]
        != artifact["holdout_gate"]["candidate_eval_hash"]
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("SKILLOPT_SEARCH_POLICY_ENABLED", "true", "must remain disabled"),
        ("SKILLOPT_SEARCH_POLICY_PATH", "relative/policy.md", "path must be absolute"),
        ("SKILLOPT_SEARCH_POLICY_SCOPE", "other_scope", "scope is invalid"),
    ),
)
def test_approved_policy_artifact_rejects_unsafe_runtime_env(
    tmp_path: Path, field, value, message
):
    artifact = _approved_policy(tmp_path)
    tampered = dict(artifact)
    tampered["runtime_env"] = dict(artifact["runtime_env"])
    tampered["runtime_env"][field] = value

    with pytest.raises(ValidationError, match=message):
        validate_approved_policy_artifact(tampered)


def test_approved_policy_artifact_rejects_extra_runtime_env_key(tmp_path: Path):
    artifact = _approved_policy(tmp_path)
    tampered = dict(artifact)
    tampered["runtime_env"] = {**artifact["runtime_env"], "SKILLOPT_UNSAFE_EXTRA": "1"}

    with pytest.raises(ValidationError, match="exactly the four"):
        validate_approved_policy_artifact(tampered)


def test_approved_policy_artifact_cannot_claim_runtime_authorization(tmp_path: Path):
    artifact = _approved_policy(tmp_path)
    tampered = {**artifact, "authorization_status": "authorized"}

    with pytest.raises(ValidationError, match="must remain not_authorized"):
        validate_approved_policy_artifact(tampered)


def test_approved_policy_artifact_rejects_mixed_evidence_lineage(tmp_path: Path):
    artifact = _approved_policy(tmp_path)
    tampered = dict(artifact)
    tampered["evaluation_evidence"] = {
        "mode": "fixture",
        "records": {
            **artifact["evaluation_evidence"]["records"],
            "test_candidate": {
                "mode": "measured",
                "capture_id": "capture-1",
                "capture_hash": "sha256:" + "b" * 64,
            },
        },
    }

    with pytest.raises(ValidationError, match="evidence modes must match"):
        validate_approved_policy_artifact(tampered)


def test_approved_policy_artifact_rejects_non_finite_primary_metric(tmp_path: Path):
    baseline_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="baseline"
        ),
    )
    candidate_eval = score_retrieval_results(
        dataset_path=DATASET,
        results_by_query=build_fixture_retrieval_results(
            dataset_path=DATASET, quality="candidate"
        ),
    )
    best_skill = _candidate_best_skill(tmp_path)
    candidate_eval = _bind_eval_to_skill(candidate_eval, best_skill)
    artifact = export_approved_skillopt_policy(
        **_approval_candidate_args(tmp_path, best_skill),
        output_dir=tmp_path / "approved",
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        **_two_stage_eval_inputs(baseline_eval, candidate_eval),
    )
    tampered = dict(artifact)
    tampered["metric_snapshot"] = dict(artifact["metric_snapshot"])
    tampered["metric_snapshot"]["baseline"] = float("nan")
    tampered["metric_snapshot"]["candidate"] = float("nan")

    with pytest.raises(ValidationError, match="metric_snapshot.baseline"):
        validate_approved_policy_artifact(tampered)


@pytest.mark.parametrize(
    ("target", "delete"),
    (
        ("acceptance_manifest", True),
        ("sealed_request", False),
        ("sealed_result", False),
        ("accepted_evaluation", False),
        ("dataset_evidence", False),
        ("custody_evidence", False),
    ),
)
def test_v2_approval_loader_rejects_missing_or_modified_accepted_chain(
    tmp_path: Path, target: str, delete: bool
) -> None:
    artifact = _approved_policy(tmp_path)
    provenance = artifact["accepted_candidate"]
    root = Path(provenance["run_root"])
    manifest = load_json(provenance["acceptance_manifest_path"])
    paths = {
        "acceptance_manifest": Path(provenance["acceptance_manifest_path"]),
        "sealed_request": root / manifest["sealed_request"]["path"],
        "sealed_result": root / manifest["sealed_result"]["path"],
        "accepted_evaluation": root
        / manifest["accepted_outputs"]["evaluation"]["path"],
        "dataset_evidence": root / manifest["evidence_snapshots"]["dataset"]["path"],
        "custody_evidence": root
        / manifest["evidence_snapshots"]["custody_evidence"]["path"],
    }
    path = paths[target]
    if delete:
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValidationError):
        load_validated_approved_skillopt_policy(artifact.artifact_path)


def test_v2_approval_loader_rejects_self_consistent_forged_approval(
    tmp_path: Path,
) -> None:
    artifact = _approved_policy(tmp_path)
    payload = artifact.persisted_artifact()
    payload["dataset_hash"] = "sha256:" + "f" * 64
    artifact.artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="dataset_hash"):
        load_validated_approved_skillopt_policy(artifact.artifact_path)


def test_identical_v2_acceptance_yields_deterministic_approved_policy(
    tmp_path: Path,
) -> None:
    first = _approved_policy(tmp_path)
    first_payload = first.persisted_artifact()
    second = load_validated_approved_skillopt_policy(first.artifact_path)

    assert second.persisted_artifact() == first_payload
    assert second.artifact_hash == first.artifact_hash


def test_approved_reload_automatically_reuses_external_authority_context(
    tmp_path: Path,
) -> None:
    artifact = _approved_policy(tmp_path)
    context_path = Path(os.environ[AUTHORITY_CONTEXT_ENV])
    context = json.loads(context_path.read_bytes())
    context["allowed_stores"] = ["different-external-store"]
    context_path.write_bytes(canonical_json_bytes(context))

    with pytest.raises(ValidationError, match="allowed_stores pin mismatch"):
        load_validated_approved_skillopt_policy(artifact.artifact_path)


def test_approved_reload_rejects_authority_rotation_after_runtime_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _approved_policy(tmp_path)
    context_path = Path(os.environ[AUTHORITY_CONTEXT_ENV])
    context = json.loads(context_path.read_bytes())
    original_read = approved_policy_module.read_stable_file
    rotated = False

    def read_then_rotate(path, *args, **kwargs):
        nonlocal rotated
        held = original_read(path, *args, **kwargs)
        if Path(path).name == "runtime_env.sh" and not rotated:
            context["allowed_stores"] = ["rotated-store"]
            context_path.write_bytes(canonical_json_bytes(context))
            rotated = True
        return held

    monkeypatch.setattr(
        approved_policy_module, "read_stable_file", read_then_rotate
    )
    with pytest.raises(AuthorityContextRotationError, match="rotated|invalid"):
        load_validated_approved_skillopt_policy(artifact.artifact_path)
    assert rotated is True
