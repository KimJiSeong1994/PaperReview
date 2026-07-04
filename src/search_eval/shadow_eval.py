"""Non-interfering shadow evaluation scaffold for SkillOpt search candidates.

This module compares already-built offline baseline/candidate envelopes. It never
calls production search, never changes a query, and stays disabled unless the
explicit dev-only shadow flag is true.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .skillopt_adapter import create_skillopt_rollout_skeleton
from .skillopt_contract import ValidationError, load_json, validate_execution_control

SHADOW_EVAL_FEATURE_FLAG = "SKILLOPT_SEARCH_SHADOW_EVAL"


def run_shadow_evaluation(
    *,
    enabled: bool,
    dataset_path: str,
    control_path: str,
    baseline_skill_path: str,
    candidate_artifact_path: str,
) -> dict[str, Any]:
    """Run a non-interfering offline shadow comparison behind an explicit flag."""
    control = load_json(control_path)
    validate_execution_control(control)
    rollout_gate = control["controlled_rollout_gate"]

    if not enabled:
        return {
            "version": "skillopt-shadow-eval-v0",
            "feature_flag": SHADOW_EVAL_FEATURE_FLAG,
            "enabled": False,
            "status": "disabled_noop",
            "production_interference": False,
            "candidate_compared": False,
            "rollout_gate": rollout_gate,
        }

    if rollout_gate["state"] != "shadow_only" or rollout_gate["max_rollout_fraction"] != 0.0:
        raise ValidationError("shadow evaluation requires closed shadow_only rollout gate")

    skeleton = create_skillopt_rollout_skeleton(
        dataset_path=dataset_path,
        control_path=control_path,
        baseline_skill_path=baseline_skill_path,
        candidate_artifact_path=candidate_artifact_path,
    )
    guardrails = _extract_guardrails_from_candidate(skeleton)
    verdict = _shadow_verdict(guardrails)
    return {
        "version": "skillopt-shadow-eval-v0",
        "feature_flag": SHADOW_EVAL_FEATURE_FLAG,
        "enabled": True,
        "status": verdict,
        "production_interference": False,
        "candidate_compared": True,
        "scope": skeleton["scope"],
        "source_hashes": skeleton["source_hashes"],
        "dataset_hash": skeleton["dataset_hash"],
        "execution_control_hash": skeleton["execution_control_hash"],
        "case_count": skeleton["case_count"],
        "candidate_skill_hash": skeleton["candidate_skill_hash"],
        "candidate_artifact_hash": skeleton["candidate_artifact_hash"],
        "rollout_gate": rollout_gate,
    }


def validate_shadow_evaluation_record(
    record: Mapping[str, Any],
    *,
    expected_candidate_artifact_hash: str | None = None,
    expected_source_hashes: Mapping[str, str] | None = None,
) -> None:
    """Validate that a shadow record is explicitly non-interfering and provenance-bound."""
    required = {"version", "feature_flag", "enabled", "status", "production_interference", "candidate_compared", "rollout_gate"}
    missing = required - set(record)
    if missing:
        raise ValidationError(f"shadow_evaluation missing required keys: {sorted(missing)}")
    if record.get("feature_flag") != SHADOW_EVAL_FEATURE_FLAG:
        raise ValidationError("shadow_evaluation.feature_flag must be SkillOpt search shadow flag")
    if record.get("production_interference") is not False:
        raise ValidationError("shadow_evaluation must not interfere with production")
    rollout_gate = record.get("rollout_gate")
    if not isinstance(rollout_gate, Mapping):
        raise ValidationError("shadow_evaluation.rollout_gate must be an object")
    if rollout_gate.get("state") != "shadow_only" or rollout_gate.get("max_rollout_fraction") != 0.0:
        raise ValidationError("shadow_evaluation rollout gate must remain shadow_only closed")
    if rollout_gate.get("requires_manual_approval") is not True:
        raise ValidationError("shadow_evaluation rollout gate must require manual approval")
    if record.get("enabled") is False and record.get("candidate_compared") is not False:
        raise ValidationError("disabled shadow evaluation must not compare candidates")
    if record.get("enabled") is True and record.get("candidate_compared") is not True:
        raise ValidationError("enabled shadow evaluation must compare candidate offline")
    if record.get("enabled") is True:
        artifact_hash = record.get("candidate_artifact_hash")
        if not isinstance(artifact_hash, str) or not artifact_hash.startswith("sha256:"):
            raise ValidationError("enabled shadow evaluation must include candidate_artifact_hash")
        if expected_candidate_artifact_hash is None:
            raise ValidationError("enabled shadow evaluation requires expected_candidate_artifact_hash")
        if artifact_hash != expected_candidate_artifact_hash:
            raise ValidationError("shadow_evaluation.candidate_artifact_hash does not match expected artifact")
        source_hashes = record.get("source_hashes")
        if not isinstance(source_hashes, Mapping):
            raise ValidationError("enabled shadow evaluation must include source_hashes")
        if expected_source_hashes is None:
            raise ValidationError("enabled shadow evaluation requires expected_source_hashes")
        if dict(source_hashes) != dict(expected_source_hashes):
            raise ValidationError("shadow_evaluation.source_hashes do not match expected sources")


def _extract_guardrails_from_candidate(skeleton: Mapping[str, Any]) -> Mapping[str, float]:
    # Candidate artifact validation happens inside create_skillopt_rollout_skeleton.
    # The current skeleton intentionally exposes only the high-level comparison
    # record; future PR5 rollout may persist richer internal metrics.
    if not skeleton.get("candidate_skill_hash"):
        raise ValidationError("shadow evaluation requires a candidate artifact")
    return {"validated_by_contract": 1.0}


def _shadow_verdict(guardrails: Mapping[str, float]) -> str:
    if guardrails.get("validated_by_contract") != 1.0:
        return "shadow_rejected"
    return "shadow_passed_contract_only"
