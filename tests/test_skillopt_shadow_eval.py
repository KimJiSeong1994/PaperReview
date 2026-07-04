"""Non-interfering shadow evaluation tests for SkillOpt search."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.search_eval.shadow_eval import SHADOW_EVAL_FEATURE_FLAG, run_shadow_evaluation, validate_shadow_evaluation_record
from src.search_eval.skillopt_adapter import canonical_file_hash
from src.search_eval.skillopt_contract import ValidationError

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/search_eval/skillopt_paper_search_v0.json"
CONTROL = ROOT / "data/search_eval/skillopt_execution_control_v0.json"
BASELINE_SKILL = ROOT / "docs/skillopt_search/baseline_skill.md"
CANDIDATE = ROOT / "data/search_eval/skillopt_candidate_artifact_example.json"


def test_shadow_evaluation_disabled_is_noop():
    record = run_shadow_evaluation(
        enabled=False,
        dataset_path=str(DATASET),
        control_path=str(CONTROL),
        baseline_skill_path=str(BASELINE_SKILL),
        candidate_artifact_path=str(CANDIDATE),
    )

    validate_shadow_evaluation_record(record)
    assert record["feature_flag"] == SHADOW_EVAL_FEATURE_FLAG
    assert record["status"] == "disabled_noop"
    assert record["production_interference"] is False
    assert record["candidate_compared"] is False
    assert record["rollout_gate"] == {
        "state": "shadow_only",
        "max_rollout_fraction": 0.0,
        "requires_manual_approval": True,
    }


def test_shadow_evaluation_enabled_compares_candidate_offline():
    record = run_shadow_evaluation(
        enabled=True,
        dataset_path=str(DATASET),
        control_path=str(CONTROL),
        baseline_skill_path=str(BASELINE_SKILL),
        candidate_artifact_path=str(CANDIDATE),
    )

    validate_shadow_evaluation_record(
        record,
        expected_candidate_artifact_hash=canonical_file_hash(CANDIDATE),
        expected_source_hashes={
            "dataset_file": canonical_file_hash(DATASET),
            "control_file": canonical_file_hash(CONTROL),
            "baseline_skill_file": canonical_file_hash(BASELINE_SKILL),
        },
    )
    assert record["status"] == "shadow_passed_contract_only"
    assert record["production_interference"] is False
    assert record["candidate_compared"] is True
    assert record["candidate_artifact_hash"].startswith("sha256:")
    assert record["scope"] == "query_analyzer_standard_search"
    assert record["rollout_gate"]["max_rollout_fraction"] == 0.0


def test_shadow_evaluation_rejects_open_rollout_gate(tmp_path):
    control_text = CONTROL.read_text(encoding="utf-8").replace('"max_rollout_fraction": 0.0', '"max_rollout_fraction": 0.1')
    control_path = tmp_path / "control.json"
    control_path.write_text(control_text, encoding="utf-8")

    with pytest.raises(ValidationError, match="max_rollout_fraction"):
        run_shadow_evaluation(
            enabled=True,
            dataset_path=str(DATASET),
            control_path=str(control_path),
            baseline_skill_path=str(BASELINE_SKILL),
            candidate_artifact_path=str(CANDIDATE),
        )


def test_shadow_evaluation_record_rejects_missing_candidate_artifact_hash():
    record = run_shadow_evaluation(
        enabled=True,
        dataset_path=str(DATASET),
        control_path=str(CONTROL),
        baseline_skill_path=str(BASELINE_SKILL),
        candidate_artifact_path=str(CANDIDATE),
    )
    record.pop("candidate_artifact_hash")

    with pytest.raises(ValidationError, match="candidate_artifact_hash"):
        validate_shadow_evaluation_record(record)


def test_shadow_evaluation_record_requires_expected_hashes_when_enabled():
    record = run_shadow_evaluation(
        enabled=True,
        dataset_path=str(DATASET),
        control_path=str(CONTROL),
        baseline_skill_path=str(BASELINE_SKILL),
        candidate_artifact_path=str(CANDIDATE),
    )

    with pytest.raises(ValidationError, match="expected_candidate_artifact_hash"):
        validate_shadow_evaluation_record(record)


def test_shadow_evaluation_record_rejects_forged_candidate_artifact_hash():
    record = run_shadow_evaluation(
        enabled=True,
        dataset_path=str(DATASET),
        control_path=str(CONTROL),
        baseline_skill_path=str(BASELINE_SKILL),
        candidate_artifact_path=str(CANDIDATE),
    )

    with pytest.raises(ValidationError, match="candidate_artifact_hash"):
        validate_shadow_evaluation_record(
            record,
            expected_candidate_artifact_hash="sha256:forged",
            expected_source_hashes={
                "dataset_file": canonical_file_hash(DATASET),
                "control_file": canonical_file_hash(CONTROL),
                "baseline_skill_file": canonical_file_hash(BASELINE_SKILL),
            },
        )


def test_shadow_evaluation_record_rejects_forged_source_hashes():
    record = run_shadow_evaluation(
        enabled=True,
        dataset_path=str(DATASET),
        control_path=str(CONTROL),
        baseline_skill_path=str(BASELINE_SKILL),
        candidate_artifact_path=str(CANDIDATE),
    )

    with pytest.raises(ValidationError, match="source_hashes"):
        validate_shadow_evaluation_record(
            record,
            expected_candidate_artifact_hash=canonical_file_hash(CANDIDATE),
            expected_source_hashes={
                "dataset_file": "sha256:forged",
                "control_file": canonical_file_hash(CONTROL),
                "baseline_skill_file": canonical_file_hash(BASELINE_SKILL),
            },
        )


def test_shadow_eval_package_is_excluded_from_docker_context():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "src/search_eval/" in dockerignore


def test_shadow_evaluation_record_rejects_interference():
    record = {
        "version": "skillopt-shadow-eval-v0",
        "feature_flag": SHADOW_EVAL_FEATURE_FLAG,
        "enabled": True,
        "status": "shadow_passed_contract_only",
        "production_interference": True,
        "candidate_compared": True,
        "rollout_gate": {"state": "shadow_only", "max_rollout_fraction": 0.0, "requires_manual_approval": True},
    }

    with pytest.raises(ValidationError, match="must not interfere"):
        validate_shadow_evaluation_record(record)
