"""Run one DeepReview SkillOpt continuous-optimization guard iteration.

This module is intended for cron. It validates the approved DeepReview SkillOpt
artifact set and, when a runtime policy is enabled, verifies that the live policy
gate is still hash-pinned and loadable. It never mutates production policy; new
candidate generation and rollout remain explicit upstream approval steps.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.DeepAgent.skillopt_policy import (
    SkillOptDeepReviewPolicyError,
    is_skillopt_deep_review_policy_enabled,
    load_skillopt_deep_review_policy_from_env,
)

from .contract import (
    DeepReviewSkillOptValidationError,
    load_json,
    validate_candidate_artifact,
    validate_dataset_contract,
    validate_execution_control,
    validate_rollback_record,
)

_DEFAULT_DATASET = "data/deep_review_eval/skillopt_deep_review_v0.json"
_DEFAULT_CONTROL = "data/deep_review_eval/skillopt_execution_control_v0.json"
_DEFAULT_CANDIDATE = "data/deep_review_eval/skillopt_candidate_artifact_example.json"
_DEFAULT_ROLLBACK = "data/deep_review_eval/skillopt_rollback_record_example.json"
_TRUE_VALUES = {"1", "true", "yes", "on"}


class DeepReviewSkillOptCronError(RuntimeError):
    """Raised when the scheduled DeepReview SkillOpt guard cannot validate."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default=os.getenv("SKILLOPT_DEEP_REVIEW_DATASET", _DEFAULT_DATASET),
        help="DeepReview SkillOpt dataset contract path.",
    )
    parser.add_argument(
        "--control",
        default=os.getenv("SKILLOPT_DEEP_REVIEW_CONTROL", _DEFAULT_CONTROL),
        help="DeepReview SkillOpt execution control contract path.",
    )
    parser.add_argument(
        "--candidate-artifact",
        default=os.getenv("SKILLOPT_DEEP_REVIEW_CANDIDATE_ARTIFACT", _DEFAULT_CANDIDATE),
        help="Approved DeepReview SkillOpt candidate artifact path.",
    )
    parser.add_argument(
        "--rollback-record",
        default=os.getenv("SKILLOPT_DEEP_REVIEW_ROLLBACK_RECORD", _DEFAULT_ROLLBACK),
        help="DeepReview SkillOpt rollback record path.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=os.getenv("SKILLOPT_DEEP_REVIEW_OPTIMIZER_STRICT", "").lower() in _TRUE_VALUES,
        help="Exit non-zero when validation fails.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = run_guard_iteration(
            dataset_path=args.dataset,
            control_path=args.control,
            candidate_artifact_path=args.candidate_artifact,
            rollback_record_path=args.rollback_record,
        )
    except (
        OSError,
        DeepReviewSkillOptCronError,
        DeepReviewSkillOptValidationError,
        SkillOptDeepReviewPolicyError,
    ) as exc:
        message = {
            "status": "failed" if args.strict else "warning",
            "checked_at": _utc_stamp(),
            "reason": str(exc),
        }
        print(json.dumps(message, ensure_ascii=False, sort_keys=True))
        return 2 if args.strict else 0

    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def run_guard_iteration(
    *,
    dataset_path: str | Path,
    control_path: str | Path,
    candidate_artifact_path: str | Path,
    rollback_record_path: str | Path,
) -> dict[str, Any]:
    """Validate DeepReview SkillOpt artifacts and active runtime policy state."""
    dataset = load_json(dataset_path)
    control = load_json(control_path)
    candidate = load_json(candidate_artifact_path)
    rollback = load_json(rollback_record_path)

    validate_dataset_contract(dataset)
    validate_execution_control(control)
    validate_candidate_artifact(candidate, dataset=dataset, control=control)
    validate_rollback_record(rollback, artifact=candidate)

    runtime_policy_enabled = is_skillopt_deep_review_policy_enabled()
    runtime_policy_hash = ""
    if runtime_policy_enabled:
        policy = load_skillopt_deep_review_policy_from_env()
        if not policy.enabled:
            raise DeepReviewSkillOptCronError("runtime policy flag was enabled but no policy loaded")
        runtime_policy_hash = policy.content_hash
        expected_hash = candidate.get("policy_hash")
        if runtime_policy_hash != expected_hash:
            raise DeepReviewSkillOptCronError(
                "runtime policy hash does not match approved candidate: "
                f"expected {expected_hash}, got {runtime_policy_hash}"
            )

    return {
        "status": "complete",
        "checked_at": _utc_stamp(),
        "scope": dataset.get("scope"),
        "dataset_hash": dataset.get("dataset_hash"),
        "control_hash": control.get("control_hash"),
        "candidate_hash": candidate.get("candidate_hash"),
        "rollback_hash": rollback.get("rollback_hash"),
        "runtime_policy_enabled": runtime_policy_enabled,
        "runtime_policy_hash": runtime_policy_hash,
    }


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    raise SystemExit(main())
