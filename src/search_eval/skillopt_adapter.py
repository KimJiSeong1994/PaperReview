"""Dev-only SkillOpt adapter skeleton for paper-search evaluation.

The real Microsoft SkillOpt runner is intentionally not imported here. This file
adapts the local offline QueryAnalyzer pilot artifacts into a stable benchmark
shape that a future SkillOpt EnvAdapter can consume in development/CI only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .query_analyzer_pilot import run_offline_query_analyzer_pilot
from .skillopt_contract import (
    V1_ALLOWED_SCOPE,
    ValidationError,
    load_json,
    validate_candidate_artifact,
    validate_dataset_contract,
    validate_execution_control,
)


@dataclass(frozen=True)
class SkillOptBenchmarkCase:
    """One SkillOpt-compatible benchmark case for QueryAnalyzer policy search."""

    case_id: str
    split: str
    input_query: str
    expected_must_include: tuple[str, ...]
    expected_must_exclude: tuple[str, ...]


def canonical_file_hash(path: str | Path) -> str:
    """Return a deterministic content hash for a benchmark source file."""
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_skillopt_benchmark_cases(dataset_path: str | Path) -> list[SkillOptBenchmarkCase]:
    """Build deterministic benchmark cases from the validated dataset fixture."""
    dataset = load_json(dataset_path)
    validate_dataset_contract(dataset)
    cases: list[SkillOptBenchmarkCase] = []
    for query in dataset["queries"]:
        labels = query["labels"]
        cases.append(
            SkillOptBenchmarkCase(
                case_id=query["query_id"],
                split=query["split"],
                input_query=query["query_text"],
                expected_must_include=tuple(labels.get("must_include", [])),
                expected_must_exclude=tuple(labels.get("must_exclude", [])),
            )
        )
    return cases


def create_skillopt_rollout_skeleton(
    *,
    dataset_path: str | Path,
    control_path: str | Path,
    baseline_skill_path: str | Path,
    candidate_artifact_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create a dev-only SkillOpt rollout skeleton without running SkillOpt.

    The envelope intentionally binds source-file content hashes so stale or
    mixed-version fixtures are visible before any real adapter can run.
    """
    dataset = load_json(dataset_path)
    control = load_json(control_path)
    validate_dataset_contract(dataset)
    validate_execution_control(control)
    pilot = run_offline_query_analyzer_pilot(
        dataset_path=dataset_path,
        control_path=control_path,
        baseline_skill_path=baseline_skill_path,
    )
    cases = build_skillopt_benchmark_cases(dataset_path)

    baseline_skill_hash = canonical_file_hash(baseline_skill_path)
    candidate_artifact: Mapping[str, Any] | None = None
    if candidate_artifact_path is not None:
        candidate_artifact = load_json(candidate_artifact_path)
        validate_candidate_artifact(candidate_artifact, dataset=dataset, execution_control=control)
        if candidate_artifact.get("baseline_hash") != baseline_skill_hash:
            raise ValidationError("candidate_artifact.baseline_hash does not match baseline skill content")

    skeleton = {
        "version": "skillopt-rollout-skeleton-v0",
        "adapter_kind": "dev_only_skillopt_env_adapter_skeleton",
        "scope": V1_ALLOWED_SCOPE,
        "source_hashes": {
            "dataset_file": canonical_file_hash(dataset_path),
            "control_file": canonical_file_hash(control_path),
            "baseline_skill_file": baseline_skill_hash,
        },
        "dataset_hash": dataset["dataset_hash"],
        "execution_control_hash": control["control_hash"],
        "case_count": len(cases),
        "splits": _count_splits(cases),
        "pilot_rollout_metadata": pilot["rollout_metadata"],
        "candidate_artifact_hash": canonical_file_hash(candidate_artifact_path) if candidate_artifact_path else None,
        "candidate_skill_hash": candidate_artifact.get("skill_hash") if candidate_artifact else None,
        "cases": [case.__dict__ for case in cases],
    }
    validate_skillopt_rollout_skeleton(skeleton, dataset=dataset, execution_control=control)
    return skeleton


def validate_skillopt_rollout_skeleton(
    skeleton: Mapping[str, Any],
    *,
    dataset: Mapping[str, Any],
    execution_control: Mapping[str, Any],
) -> None:
    """Validate the dev-only SkillOpt rollout skeleton envelope."""
    required = {
        "version",
        "adapter_kind",
        "scope",
        "source_hashes",
        "dataset_hash",
        "execution_control_hash",
        "case_count",
        "splits",
        "pilot_rollout_metadata",
        "cases",
    }
    missing = required - set(skeleton)
    if missing:
        raise ValidationError(f"skillopt_rollout_skeleton missing required keys: {sorted(missing)}")
    if skeleton.get("adapter_kind") != "dev_only_skillopt_env_adapter_skeleton":
        raise ValidationError("skillopt_rollout_skeleton.adapter_kind must be dev-only")
    if skeleton.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError(f"skillopt_rollout_skeleton.scope must be {V1_ALLOWED_SCOPE}")
    if skeleton.get("dataset_hash") != dataset.get("dataset_hash"):
        raise ValidationError("skillopt_rollout_skeleton.dataset_hash does not match dataset")
    if skeleton.get("execution_control_hash") != execution_control.get("control_hash"):
        raise ValidationError("skillopt_rollout_skeleton.execution_control_hash does not match control")
    source_hashes = skeleton.get("source_hashes")
    if not isinstance(source_hashes, Mapping) or set(source_hashes) != {"dataset_file", "control_file", "baseline_skill_file"}:
        raise ValidationError("skillopt_rollout_skeleton.source_hashes must bind dataset/control/baseline files")
    if any(not isinstance(value, str) or not value.startswith("sha256:") for value in source_hashes.values()):
        raise ValidationError("skillopt_rollout_skeleton.source_hashes must be sha256 digests")
    cases = skeleton.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)) or not cases:
        raise ValidationError("skillopt_rollout_skeleton.cases must be a non-empty list")
    if skeleton.get("case_count") != len(cases):
        raise ValidationError("skillopt_rollout_skeleton.case_count does not match cases")
    if skeleton.get("splits") != _count_splits_from_dicts(cases):
        raise ValidationError("skillopt_rollout_skeleton.splits do not match cases")


def _count_splits(cases: Sequence[SkillOptBenchmarkCase]) -> dict[str, int]:
    counts = {"train": 0, "selection": 0, "test": 0}
    for case in cases:
        counts[case.split] += 1
    return counts


def _count_splits_from_dicts(cases: Sequence[Any]) -> dict[str, int]:
    counts = {"train": 0, "selection": 0, "test": 0}
    for case in cases:
        if not isinstance(case, Mapping):
            raise ValidationError("skillopt_rollout_skeleton.cases entries must be objects")
        split = case.get("split")
        if split not in counts:
            raise ValidationError("skillopt_rollout_skeleton.cases split must be train/selection/test")
        counts[split] += 1
    return counts
