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
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

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
        "--status-path",
        default=os.getenv("SKILLOPT_DEEP_REVIEW_STATUS_PATH"),
        help="Optional path for the latest DeepReview SkillOpt status JSON snapshot.",
    )
    parser.add_argument(
        "--reward-memory",
        default=os.getenv("SKILLOPT_DEEP_REVIEW_REWARD_MEMORY"),
        help="Optional JSONL path for append-only DeepReview SkillOpt reward memory.",
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
        persist_guard_outputs(
            summary,
            status_path=args.status_path,
            reward_memory_path=args.reward_memory,
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
        if args.status_path:
            try:
                _write_json_atomic(Path(args.status_path), message)
            except OSError as persist_exc:
                message["status_persist_error"] = str(persist_exc)
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
        "selection_primary_metric": candidate.get("selection_gate", {}).get("primary_metric", {}),
        "holdout_primary_metric": candidate.get("holdout_gate", {}).get("primary_metric", {}),
    }


def persist_guard_outputs(
    summary: Mapping[str, Any],
    *,
    status_path: str | Path | None,
    reward_memory_path: str | Path | None,
) -> None:
    """Persist latest status and append-only reward memory when configured."""
    if status_path:
        _write_json_atomic(Path(status_path), dict(summary))
    if reward_memory_path:
        _append_jsonl(Path(reward_memory_path), build_reward_memory_entry(summary))


def build_reward_memory_entry(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Create a compact RL-ready memory entry from the approved candidate gates."""
    metric = summary.get("holdout_primary_metric")
    if not isinstance(metric, Mapping):
        raise DeepReviewSkillOptCronError("holdout_primary_metric is required for reward memory")
    baseline = _finite_float(metric.get("baseline"), "holdout_primary_metric.baseline")
    candidate = _finite_float(metric.get("candidate"), "holdout_primary_metric.candidate")
    return {
        "version": "skillopt-deep-review-reward-memory-entry-v0",
        "entry_id": f"deep-review-{uuid4()}",
        "created_at": _utc_stamp(),
        "status": summary.get("status"),
        "scope": summary.get("scope"),
        "reward": round(candidate - baseline, 6),
        "reward_metric": metric.get("name"),
        "candidate_hash": summary.get("candidate_hash"),
        "runtime_policy_hash": summary.get("runtime_policy_hash"),
        "dataset_hash": summary.get("dataset_hash"),
        "control_hash": summary.get("control_hash"),
        "runtime_policy_enabled": summary.get("runtime_policy_enabled"),
        "safety": {
            "hash_pinned": bool(summary.get("runtime_policy_hash")),
            "rollback_record_present": bool(summary.get("rollback_hash")),
            "artifact_validation_passed": summary.get("status") == "complete",
        },
    }


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def _finite_float(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise DeepReviewSkillOptCronError(f"{field} must be a finite number")
    result = float(value)
    if result != result or result in {float("inf"), float("-inf")}:
        raise DeepReviewSkillOptCronError(f"{field} must be finite")
    return result


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    raise SystemExit(main())
