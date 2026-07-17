"""Validation helpers for dev-only DeepReview SkillOpt artifacts."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCOPE = "deep_review_analysis_prompt"
DATASET_VERSION = "skillopt-deep-review-dataset-v0"
CONTROL_VERSION = "skillopt-deep-review-execution-control-v0"
CANDIDATE_VERSION = "skillopt-deep-review-candidate-artifact-v0"
ROLLBACK_VERSION = "skillopt-deep-review-rollback-record-v0"


class DeepReviewSkillOptValidationError(ValueError):
    """Raised when a DeepReview SkillOpt artifact violates the v0 contract."""


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise DeepReviewSkillOptValidationError(f"expected JSON object: {path}")
    return value


def canonical_mapping_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def canonical_file_hash(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_self_hash(value: Mapping[str, Any], hash_field: str) -> str:
    """Hash an artifact while excluding its self-referential hash field."""
    payload = dict(value)
    payload.pop(hash_field, None)
    return canonical_mapping_hash(payload)


def validate_dataset_contract(dataset: Mapping[str, Any]) -> None:
    if dataset.get("version") != DATASET_VERSION:
        raise DeepReviewSkillOptValidationError("dataset version is invalid")
    if dataset.get("scope") != SCOPE:
        raise DeepReviewSkillOptValidationError("dataset scope is invalid")
    expected_hash = _require_digest(dataset.get("dataset_hash"), "dataset_hash")
    if expected_hash != canonical_self_hash(dataset, "dataset_hash"):
        raise DeepReviewSkillOptValidationError("dataset_hash does not match dataset content")
    splits = dataset.get("splits")
    if not isinstance(splits, Mapping) or set(splits) != {"dev", "test"}:
        raise DeepReviewSkillOptValidationError("dataset splits must include dev and test")
    split_ids = _validate_split_ids(splits)
    items = dataset.get("items")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)) or len(items) < 2:
        raise DeepReviewSkillOptValidationError("dataset items must contain at least two records")
    seen_ids: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            raise DeepReviewSkillOptValidationError("dataset item must be an object")
        query_id = _require_non_empty_str(item.get("query_id"), "item.query_id")
        if query_id in seen_ids:
            raise DeepReviewSkillOptValidationError("dataset query_id must be unique")
        seen_ids.add(query_id)
        split = _require_non_empty_str(item.get("split"), "item.split")
        if split not in split_ids or query_id not in split_ids[split]:
            raise DeepReviewSkillOptValidationError("dataset split membership mismatch")
        paper = item.get("paper")
        if not isinstance(paper, Mapping):
            raise DeepReviewSkillOptValidationError("dataset paper must be an object")
        _require_non_empty_str(paper.get("title"), "paper.title")
        if not (paper.get("abstract") or paper.get("full_text")):
            raise DeepReviewSkillOptValidationError("paper requires abstract or full_text")
        rubric = item.get("rubric")
        if not isinstance(rubric, Mapping):
            raise DeepReviewSkillOptValidationError("rubric must be an object")
        _require_non_empty_list(rubric.get("must_cover"), "rubric.must_cover")
        _require_non_empty_list(rubric.get("must_not_include"), "rubric.must_not_include")
    split_union = set().union(*split_ids.values())
    if split_union != seen_ids:
        raise DeepReviewSkillOptValidationError("dataset split ids must exactly match item query_ids")


def validate_execution_control(control: Mapping[str, Any]) -> None:
    if control.get("version") != CONTROL_VERSION:
        raise DeepReviewSkillOptValidationError("control version is invalid")
    if control.get("scope") != SCOPE:
        raise DeepReviewSkillOptValidationError("control scope is invalid")
    expected_hash = _require_digest(control.get("control_hash"), "control_hash")
    if expected_hash != canonical_self_hash(control, "control_hash"):
        raise DeepReviewSkillOptValidationError("control_hash does not match control content")
    if control.get("runtime_default_off") is not True:
        raise DeepReviewSkillOptValidationError("runtime_default_off must be true")
    allowed_env = control.get("allowed_runtime_env")
    required_env = {
        "SKILLOPT_DEEP_REVIEW_POLICY_ENABLED",
        "SKILLOPT_DEEP_REVIEW_POLICY_PATH",
        "SKILLOPT_DEEP_REVIEW_POLICY_HASH",
        "SKILLOPT_DEEP_REVIEW_POLICY_SCOPE",
    }
    if not isinstance(allowed_env, Sequence) or set(allowed_env) != required_env:
        raise DeepReviewSkillOptValidationError("allowed_runtime_env mismatch")
    blocked = set(control.get("blocked_changes", []))
    for required in {
        "paper_loader_behavior",
        "workspace_session_ownership",
        "fact_verification_bypass",
        "advisor_validation_bypass",
        "report_failure_suppression",
    }:
        if required not in blocked:
            raise DeepReviewSkillOptValidationError(f"blocked_changes missing {required}")
    approval = control.get("approval_requirements")
    if not isinstance(approval, Mapping) or not all(approval.get(key) is True for key in (
        "hash_bound_policy", "holdout_gate", "rollback_record", "manual_rollout"
    )):
        raise DeepReviewSkillOptValidationError("approval_requirements must all be true")


def validate_candidate_artifact(
    artifact: Mapping[str, Any],
    *,
    dataset: Mapping[str, Any] | None = None,
    control: Mapping[str, Any] | None = None,
) -> None:
    """Validate a hash-bound approved DeepReview candidate artifact."""
    if artifact.get("version") != CANDIDATE_VERSION:
        raise DeepReviewSkillOptValidationError("candidate version is invalid")
    if artifact.get("scope") != SCOPE:
        raise DeepReviewSkillOptValidationError("candidate scope is invalid")
    expected_hash = _require_digest(artifact.get("candidate_hash"), "candidate_hash")
    if expected_hash != canonical_self_hash(artifact, "candidate_hash"):
        raise DeepReviewSkillOptValidationError("candidate_hash does not match candidate content")
    policy_hash = _require_digest(artifact.get("policy_hash"), "policy_hash")
    baseline_hash = _require_digest(artifact.get("baseline_hash"), "baseline_hash")
    if policy_hash == baseline_hash:
        raise DeepReviewSkillOptValidationError("candidate policy_hash must differ from baseline_hash")
    dataset_hash = _require_digest(artifact.get("dataset_hash"), "dataset_hash")
    control_hash = _require_digest(artifact.get("control_hash"), "control_hash")
    if dataset is not None:
        validate_dataset_contract(dataset)
        if dataset.get("dataset_hash") != dataset_hash:
            raise DeepReviewSkillOptValidationError("candidate dataset_hash mismatch")
    if control is not None:
        validate_execution_control(control)
        if control.get("control_hash") != control_hash:
            raise DeepReviewSkillOptValidationError("candidate control_hash mismatch")
    selection_gate = artifact.get("selection_gate")
    holdout_gate = artifact.get("holdout_gate")
    _validate_gate(selection_gate, "selection_gate")
    _validate_gate(holdout_gate, "holdout_gate")
    if holdout_gate.get("split") != "test":
        raise DeepReviewSkillOptValidationError("holdout_gate split must be test")
    rollout = artifact.get("rollout")
    if not isinstance(rollout, Mapping):
        raise DeepReviewSkillOptValidationError("candidate rollout must be an object")
    if rollout.get("runtime_default_off") is not True or rollout.get("rollout_fraction") != 0.0:
        raise DeepReviewSkillOptValidationError("candidate rollout must stay default-off with fraction 0.0")
    if rollout.get("manual_approval_required") is not True:
        raise DeepReviewSkillOptValidationError("candidate rollout must require manual approval")
    runtime_env = artifact.get("runtime_env")
    required_env = {
        "SKILLOPT_DEEP_REVIEW_POLICY_ENABLED",
        "SKILLOPT_DEEP_REVIEW_POLICY_PATH",
        "SKILLOPT_DEEP_REVIEW_POLICY_HASH",
        "SKILLOPT_DEEP_REVIEW_POLICY_SCOPE",
    }
    if not isinstance(runtime_env, Mapping) or set(runtime_env) != required_env:
        raise DeepReviewSkillOptValidationError("candidate runtime_env mismatch")
    if runtime_env.get("SKILLOPT_DEEP_REVIEW_POLICY_ENABLED") != "true":
        raise DeepReviewSkillOptValidationError("candidate runtime_env must explicitly enable the approved policy")
    runtime_path = runtime_env.get("SKILLOPT_DEEP_REVIEW_POLICY_PATH")
    if not isinstance(runtime_path, str) or not Path(runtime_path).is_absolute():
        raise DeepReviewSkillOptValidationError("candidate runtime_env policy path must be absolute")
    if runtime_env.get("SKILLOPT_DEEP_REVIEW_POLICY_HASH") != artifact.get("policy_hash"):
        raise DeepReviewSkillOptValidationError("candidate runtime_env policy hash mismatch")
    if runtime_env.get("SKILLOPT_DEEP_REVIEW_POLICY_SCOPE") != SCOPE:
        raise DeepReviewSkillOptValidationError("candidate runtime_env scope mismatch")
    rollback_to = artifact.get("rollback_to")
    if not isinstance(rollback_to, Mapping) or rollback_to.get("policy_hash") != artifact.get("baseline_hash"):
        raise DeepReviewSkillOptValidationError("candidate rollback_to must point to baseline_hash")
    if rollback_to.get("feature_flag") != "SKILLOPT_DEEP_REVIEW_POLICY_ENABLED=false":
        raise DeepReviewSkillOptValidationError("candidate rollback_to must disable the runtime policy")


def validate_rollback_record(
    record: Mapping[str, Any],
    *,
    artifact: Mapping[str, Any] | None = None,
) -> None:
    """Validate a DeepReview rollback record that forces runtime policy off."""
    if record.get("version") != ROLLBACK_VERSION:
        raise DeepReviewSkillOptValidationError("rollback version is invalid")
    if record.get("scope") != SCOPE:
        raise DeepReviewSkillOptValidationError("rollback scope is invalid")
    expected_hash = _require_digest(record.get("rollback_hash"), "rollback_hash")
    if expected_hash != canonical_self_hash(record, "rollback_hash"):
        raise DeepReviewSkillOptValidationError("rollback_hash does not match rollback content")
    from_candidate = _require_digest(record.get("from_candidate_hash"), "from_candidate_hash")
    to_baseline = _require_digest(record.get("to_baseline_hash"), "to_baseline_hash")
    if artifact is not None:
        validate_candidate_artifact(artifact)
        if artifact.get("candidate_hash") != from_candidate:
            raise DeepReviewSkillOptValidationError("rollback from_candidate_hash mismatch")
        if artifact.get("baseline_hash") != to_baseline:
            raise DeepReviewSkillOptValidationError("rollback to_baseline_hash mismatch")
    if record.get("feature_flag_after") is not False:
        raise DeepReviewSkillOptValidationError("rollback feature_flag_after must be false")
    if _require_non_empty_str(record.get("reason"), "rollback.reason") == "":
        raise DeepReviewSkillOptValidationError("rollback reason is required")
    if record.get("triggered_by") not in {"manual", "canary_sla", "quality_regression", "hash_mismatch"}:
        raise DeepReviewSkillOptValidationError("rollback triggered_by is invalid")


def _validate_gate(gate: Any, field: str) -> None:
    if not isinstance(gate, Mapping):
        raise DeepReviewSkillOptValidationError(f"{field} must be an object")
    if gate.get("status") != "passed":
        raise DeepReviewSkillOptValidationError(f"{field} must pass")
    metric = gate.get("primary_metric")
    if not isinstance(metric, Mapping):
        raise DeepReviewSkillOptValidationError(f"{field}.primary_metric must be an object")
    baseline = _finite_float(metric.get("baseline"), f"{field}.baseline")
    candidate = _finite_float(metric.get("candidate"), f"{field}.candidate")
    if candidate <= baseline:
        raise DeepReviewSkillOptValidationError(f"{field} candidate must beat baseline")
    _require_non_empty_list(gate.get("required_criteria"), f"{field}.required_criteria")


def build_runtime_env(*, policy_path: str | Path, policy_hash: str) -> dict[str, str]:
    """Build the explicit runtime env block for an approved DeepReview policy."""
    _require_digest(policy_hash, "policy_hash")
    path = Path(policy_path)
    if not path.is_absolute():
        raise DeepReviewSkillOptValidationError("policy_path must be absolute")
    if canonical_file_hash(path) != policy_hash:
        raise DeepReviewSkillOptValidationError("policy_path hash mismatch")
    return {
        "SKILLOPT_DEEP_REVIEW_POLICY_ENABLED": "true",
        "SKILLOPT_DEEP_REVIEW_POLICY_PATH": str(path),
        "SKILLOPT_DEEP_REVIEW_POLICY_HASH": policy_hash,
        "SKILLOPT_DEEP_REVIEW_POLICY_SCOPE": SCOPE,
    }


def _finite_float(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise DeepReviewSkillOptValidationError(f"{field} must be a finite number")
    result = float(value)
    if result != result or result in {float("inf"), float("-inf")}:
        raise DeepReviewSkillOptValidationError(f"{field} must be a finite number")
    return result


def _validate_split_ids(splits: Mapping[str, Any]) -> dict[str, set[str]]:
    split_ids: dict[str, set[str]] = {}
    all_ids: set[str] = set()
    for split_name in ("dev", "test"):
        raw_ids = splits.get(split_name)
        if not isinstance(raw_ids, Sequence) or isinstance(raw_ids, (str, bytes)) or not raw_ids:
            raise DeepReviewSkillOptValidationError(f"dataset split {split_name} must be non-empty")
        ids: set[str] = set()
        for value in raw_ids:
            query_id = _require_non_empty_str(value, f"splits.{split_name}")
            if query_id in ids:
                raise DeepReviewSkillOptValidationError(f"dataset split {split_name} contains duplicate query_id")
            if query_id in all_ids:
                raise DeepReviewSkillOptValidationError("dataset split query_id appears in multiple splits")
            ids.add(query_id)
            all_ids.add(query_id)
        split_ids[split_name] = ids
    return split_ids


def _require_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise DeepReviewSkillOptValidationError(f"{field} must be a sha256 digest")
    digest = value[len("sha256:"):]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise DeepReviewSkillOptValidationError(f"{field} must be a sha256 digest")
    return value


def _require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeepReviewSkillOptValidationError(f"{field} is required")
    return value


def _require_non_empty_list(value: Any, field: str) -> None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise DeepReviewSkillOptValidationError(f"{field} must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise DeepReviewSkillOptValidationError(f"{field} entries must be non-empty strings")
