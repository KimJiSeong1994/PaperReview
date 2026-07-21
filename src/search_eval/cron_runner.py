"""Run one configured SkillOpt continuous-optimization bookkeeping iteration.

This script is intended for cron. It is deliberately config-gated: when the
required approved/evaluation artifacts are not configured, it exits 0 with a
SKIPPED message so production search behavior is never mutated by accident.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .continuous_optimizer import run_continuous_optimization_iteration

_REQUIRED_ENV = {
    "approved_policy_artifact_path": "SKILLOPT_APPROVED_POLICY_ARTIFACT",
    "baseline_eval_path": "SKILLOPT_BASELINE_EVAL",
    "candidate_eval_path": "SKILLOPT_CANDIDATE_EVAL",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--approved-policy-artifact",
        default=os.getenv("SKILLOPT_APPROVED_POLICY_ARTIFACT"),
    )
    parser.add_argument("--baseline-eval", default=os.getenv("SKILLOPT_BASELINE_EVAL"))
    parser.add_argument(
        "--candidate-eval", default=os.getenv("SKILLOPT_CANDIDATE_EVAL")
    )
    parser.add_argument(
        "--dataset",
        default=os.getenv(
            "SKILLOPT_DATASET", "data/search_eval/skillopt_paper_search_v0.json"
        ),
    )
    parser.add_argument(
        "--control",
        default=os.getenv(
            "SKILLOPT_CONTROL", "data/search_eval/skillopt_execution_control_v0.json"
        ),
    )
    parser.add_argument(
        "--baseline-skill",
        default=os.getenv(
            "SKILLOPT_BASELINE_SKILL", "docs/skillopt_search/baseline_skill.md"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("SKILLOPT_OUTPUT_DIR", "data/search_eval/continuous_runs"),
    )
    parser.add_argument(
        "--reward-memory",
        default=os.getenv(
            "SKILLOPT_REWARD_MEMORY", "data/search_eval/reward_memory.jsonl"
        ),
    )
    parser.add_argument("--run-id", default=os.getenv("SKILLOPT_RUN_ID"))
    parser.add_argument(
        "--next-holdout-generation-id",
        default=os.getenv("SKILLOPT_NEXT_HOLDOUT_GENERATION_ID"),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=os.getenv("SKILLOPT_CRON_STRICT", "").lower() in {"1", "true", "yes"},
        help="Exit non-zero instead of SKIPPED when required artifacts are not configured.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    missing = _missing_required_args(args)
    if missing:
        message = {
            "status": "SKIPPED",
            "reason": "missing_required_skillopt_artifacts",
            "missing_env": missing,
        }
        print(json.dumps(message, ensure_ascii=False, sort_keys=True))
        return 2 if args.strict else 0

    run_id = args.run_id or f"skillopt-cron-{_utc_stamp()}"
    next_holdout = args.next_holdout_generation_id or f"holdout:{run_id}:next"
    output_dir = Path(args.output_dir) / run_id

    result = run_continuous_optimization_iteration(
        run_id=run_id,
        output_dir=output_dir,
        approved_policy_artifact_path=args.approved_policy_artifact,
        baseline_eval=_load_json(args.baseline_eval),
        candidate_eval=_load_json(args.candidate_eval),
        dataset_path=args.dataset,
        control_path=args.control,
        baseline_skill_path=args.baseline_skill,
        reward_memory_path=args.reward_memory,
        next_holdout_generation_id=next_holdout,
    )
    print(
        json.dumps(
            {
                "status": "complete",
                "run_id": run_id,
                "manifest_path": result["manifest_path"],
                "summary_path": result["summary_path"],
                "reward": result["summary"]["reward"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _missing_required_args(args: argparse.Namespace) -> list[str]:
    values = {
        "approved_policy_artifact_path": args.approved_policy_artifact,
        "baseline_eval_path": args.baseline_eval,
        "candidate_eval_path": args.candidate_eval,
    }
    return [env for field, env in _REQUIRED_ENV.items() if not values[field]]


def _load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected object JSON at {path}")
    return value


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    raise SystemExit(main())
