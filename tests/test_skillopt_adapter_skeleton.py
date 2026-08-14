"""Dev-only SkillOpt adapter skeleton tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.search_eval.skillopt_adapter import (
    build_skillopt_benchmark_cases,
    canonical_file_hash,
    create_skillopt_rollout_skeleton,
    validate_skillopt_rollout_skeleton,
)
from src.search_eval.skillopt_contract import ValidationError, load_json

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/search_eval/skillopt_paper_search_v0.json"
CONTROL = ROOT / "data/search_eval/skillopt_execution_control_v0.json"
BASELINE_SKILL = ROOT / "docs/skillopt_search/baseline_skill.md"
CANDIDATE = ROOT / "data/search_eval/skillopt_candidate_artifact_example.json"


def test_build_skillopt_benchmark_cases_from_dataset():
    cases = build_skillopt_benchmark_cases(DATASET)

    # Track the dataset rather than a literal: the benchmark is meant to grow,
    # and a hardcoded count turns every added query into a failing test.
    expected = len(load_json(DATASET)["queries"])
    assert len(cases) == expected
    assert {case.split for case in cases} == {"train", "selection", "test"}
    assert all(case.expected_must_include for case in cases)


def test_create_skillopt_rollout_skeleton_is_dev_only_and_content_bound():
    skeleton = create_skillopt_rollout_skeleton(
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
        candidate_artifact_path=CANDIDATE,
    )

    assert skeleton["adapter_kind"] == "dev_only_skillopt_env_adapter_skeleton"
    assert skeleton["scope"] == "query_analyzer_standard_search"
    assert skeleton["source_hashes"]["baseline_skill_file"] == canonical_file_hash(BASELINE_SKILL)
    # Derived from the dataset for the same reason as the case count above:
    # the split tallies must follow the benchmark as it grows, while still
    # proving the skeleton counts each split rather than guessing.
    expected_splits: dict[str, int] = {}
    for query in load_json(DATASET)["queries"]:
        expected_splits[query["split"]] = expected_splits.get(query["split"], 0) + 1
    assert skeleton["splits"] == expected_splits
    assert skeleton["pilot_rollout_metadata"]["hyde_enabled"] is False
    assert skeleton["candidate_skill_hash"].startswith("sha256:")


def test_rollout_skeleton_validator_rejects_hash_drift():
    dataset = load_json(DATASET)
    control = load_json(CONTROL)
    skeleton = create_skillopt_rollout_skeleton(
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
    )
    skeleton["dataset_hash"] = "different_dataset"

    with pytest.raises(ValidationError, match="dataset_hash"):
        validate_skillopt_rollout_skeleton(skeleton, dataset=dataset, execution_control=control)


def test_rollout_skeleton_rejects_candidate_missing_declared_guardrail(tmp_path):
    candidate = load_json(CANDIDATE)
    candidate["metric_snapshot"]["guardrails"].pop("Recall@10")
    bad_candidate = tmp_path / "candidate.json"
    import json

    bad_candidate.write_text(json.dumps(candidate), encoding="utf-8")

    with pytest.raises(ValidationError, match="Recall@10"):
        create_skillopt_rollout_skeleton(
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            candidate_artifact_path=bad_candidate,
        )


def test_rollout_skeleton_rejects_forged_baseline_hash(tmp_path):
    candidate = load_json(CANDIDATE)
    forged = "sha256:" + "d" * 64
    candidate["baseline_hash"] = forged
    candidate["rollback_to"]["skill_hash"] = forged
    bad_candidate = tmp_path / "candidate.json"
    import json

    bad_candidate.write_text(json.dumps(candidate), encoding="utf-8")

    with pytest.raises(ValidationError, match="baseline skill content"):
        create_skillopt_rollout_skeleton(
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
            candidate_artifact_path=bad_candidate,
        )
