"""Dev-only SkillOpt artifact tests for DeepReview."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.deep_review_eval.contract import (
    DeepReviewSkillOptValidationError,
    load_json,
    validate_dataset_contract,
    build_runtime_env,
    canonical_file_hash,
    canonical_self_hash,
    validate_candidate_artifact,
    validate_execution_control,
    validate_rollback_record,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/deep_review_eval/skillopt_deep_review_v0.json"
CONTROL = ROOT / "data/deep_review_eval/skillopt_execution_control_v0.json"
CANDIDATE = ROOT / "data/deep_review_eval/skillopt_candidate_artifact_example.json"
ROLLBACK = ROOT / "data/deep_review_eval/skillopt_rollback_record_example.json"


def test_deep_review_eval_dataset_contract_is_valid() -> None:
    validate_dataset_contract(load_json(DATASET))


def test_deep_review_eval_control_contract_is_valid() -> None:
    validate_execution_control(load_json(CONTROL))


def test_deep_review_candidate_artifact_contract_is_valid() -> None:
    validate_candidate_artifact(
        load_json(CANDIDATE),
        dataset=load_json(DATASET),
        control=load_json(CONTROL),
    )


def test_deep_review_rollback_record_contract_is_valid() -> None:
    validate_rollback_record(load_json(ROLLBACK), artifact=load_json(CANDIDATE))


def test_deep_review_eval_dataset_rejects_split_mismatch() -> None:
    dataset = load_json(DATASET)
    dataset["items"][0]["split"] = "test"
    dataset["dataset_hash"] = canonical_self_hash(dataset, "dataset_hash")

    with pytest.raises(DeepReviewSkillOptValidationError, match="split membership"):
        validate_dataset_contract(dataset)


def test_deep_review_eval_control_rejects_runtime_default_on() -> None:
    control = load_json(CONTROL)
    control["runtime_default_off"] = False
    control["control_hash"] = canonical_self_hash(control, "control_hash")

    with pytest.raises(DeepReviewSkillOptValidationError, match="runtime_default_off"):
        validate_execution_control(control)


def test_deep_review_eval_fixtures_are_not_gitignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "!data/deep_review_eval/" in gitignore
    assert "!data/deep_review_eval/*.json" in gitignore
    for path in (DATASET, CONTROL, CANDIDATE, ROLLBACK):
        assert path.exists(), path
        json.loads(path.read_text(encoding="utf-8"))


def test_deep_review_runtime_env_requires_absolute_hash_bound_policy(tmp_path: Path) -> None:
    policy = tmp_path / "best_skill.md"
    policy.write_text(Path("docs/skillopt_deep_review/baseline_skill.md").read_text(encoding="utf-8"), encoding="utf-8")
    digest = canonical_file_hash(policy)

    env = build_runtime_env(policy_path=policy, policy_hash=digest)

    assert env["SKILLOPT_DEEP_REVIEW_POLICY_ENABLED"] == "true"
    assert env["SKILLOPT_DEEP_REVIEW_POLICY_HASH"] == digest
    assert env["SKILLOPT_DEEP_REVIEW_POLICY_SCOPE"] == "deep_review_analysis_prompt"


def test_deep_review_runtime_env_rejects_hash_mismatch(tmp_path: Path) -> None:
    policy = tmp_path / "best_skill.md"
    policy.write_text("policy", encoding="utf-8")

    with pytest.raises(DeepReviewSkillOptValidationError, match="hash mismatch"):
        build_runtime_env(policy_path=policy, policy_hash="sha256:" + "0" * 64)


def test_deep_review_eval_dataset_rejects_self_hash_drift() -> None:
    dataset = load_json(DATASET)
    dataset["items"][0]["paper"]["title"] = "Tampered title"

    with pytest.raises(DeepReviewSkillOptValidationError, match="dataset_hash"):
        validate_dataset_contract(dataset)


def test_deep_review_eval_control_rejects_self_hash_drift() -> None:
    control = load_json(CONTROL)
    control["blocked_changes"].append("new_unsafe_change")

    with pytest.raises(DeepReviewSkillOptValidationError, match="control_hash"):
        validate_execution_control(control)


def test_deep_review_eval_dataset_rejects_empty_holdout_split() -> None:
    dataset = load_json(DATASET)
    dataset["splits"]["dev"] = [item["query_id"] for item in dataset["items"]]
    dataset["splits"]["test"] = []
    dataset["dataset_hash"] = canonical_self_hash(dataset, "dataset_hash")

    with pytest.raises(DeepReviewSkillOptValidationError, match="test must be non-empty"):
        validate_dataset_contract(dataset)



def test_deep_review_eval_dataset_rejects_duplicate_split_id() -> None:
    dataset = load_json(DATASET)
    duplicate = dataset["splits"]["dev"][0]
    dataset["splits"]["dev"].append(duplicate)
    dataset["dataset_hash"] = canonical_self_hash(dataset, "dataset_hash")

    with pytest.raises(DeepReviewSkillOptValidationError, match="duplicate query_id"):
        validate_dataset_contract(dataset)

def test_deep_review_eval_dataset_rejects_ghost_split_id() -> None:
    dataset = load_json(DATASET)
    dataset["splits"]["test"].append("ghost-query")
    dataset["dataset_hash"] = canonical_self_hash(dataset, "dataset_hash")

    with pytest.raises(DeepReviewSkillOptValidationError, match="exactly match item query_ids"):
        validate_dataset_contract(dataset)


def test_deep_review_candidate_rejects_self_hash_drift() -> None:
    artifact = load_json(CANDIDATE)
    artifact["rollout"]["rollout_fraction"] = 0.1

    with pytest.raises(DeepReviewSkillOptValidationError, match="candidate_hash"):
        validate_candidate_artifact(artifact)


def test_deep_review_candidate_rejects_holdout_regression() -> None:
    artifact = load_json(CANDIDATE)
    artifact["holdout_gate"]["primary_metric"]["candidate"] = 0.60
    artifact["candidate_hash"] = canonical_self_hash(artifact, "candidate_hash")

    with pytest.raises(DeepReviewSkillOptValidationError, match="holdout_gate candidate"):
        validate_candidate_artifact(artifact)


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda artifact: artifact.__setitem__("policy_hash", artifact["baseline_hash"]), "must differ"),
        (
            lambda artifact: artifact["runtime_env"].__setitem__(
                "SKILLOPT_DEEP_REVIEW_POLICY_ENABLED", "false"
            ),
            "explicitly enable",
        ),
        (
            lambda artifact: artifact["runtime_env"].__setitem__(
                "SKILLOPT_DEEP_REVIEW_POLICY_PATH", "relative/policy.md"
            ),
            "path must be absolute",
        ),
        (
            lambda artifact: artifact["rollout"].__setitem__("manual_approval_required", False),
            "manual approval",
        ),
        (lambda artifact: artifact["holdout_gate"].__setitem__("split", "dev"), "split must be test"),
        (
            lambda artifact: artifact["rollback_to"].__setitem__(
                "feature_flag", "SKILLOPT_DEEP_REVIEW_POLICY_ENABLED=true"
            ),
            "disable the runtime policy",
        ),
    ),
)
def test_deep_review_candidate_rejects_unsafe_rollout_metadata(mutate, message: str) -> None:
    artifact = load_json(CANDIDATE)
    mutate(artifact)
    artifact["candidate_hash"] = canonical_self_hash(artifact, "candidate_hash")

    with pytest.raises(DeepReviewSkillOptValidationError, match=message):
        validate_candidate_artifact(artifact)


def test_deep_review_rollback_rejects_feature_flag_left_on() -> None:
    record = load_json(ROLLBACK)
    record["feature_flag_after"] = True
    record["rollback_hash"] = canonical_self_hash(record, "rollback_hash")

    with pytest.raises(DeepReviewSkillOptValidationError, match="feature_flag_after"):
        validate_rollback_record(record)


def test_deep_review_rollback_rejects_candidate_hash_mismatch() -> None:
    record = load_json(ROLLBACK)
    record["from_candidate_hash"] = "sha256:" + "0" * 64
    record["rollback_hash"] = canonical_self_hash(record, "rollback_hash")

    with pytest.raises(DeepReviewSkillOptValidationError, match="from_candidate_hash"):
        validate_rollback_record(record, artifact=load_json(CANDIDATE))
