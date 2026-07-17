"""Continuous SkillOpt/RL optimization gates for paper search.

The functions here keep the continuous-optimization loop dev/eval-only. They do
not call the production search path and they never mutate runtime policy state;
instead they validate lineage, evaluator gates, reward-memory eligibility, and
manual live-canary handoff artifacts.
"""
from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from .approved_policy import split_retrieval_evaluation_record, validate_approved_policy_artifact
from .skillopt_materializer import validate_skillopt_materialization_manifest
from .retrieval_eval import assert_candidate_beats_baseline, validate_retrieval_evaluation_record
from .skillopt_adapter import canonical_file_hash
from .skillopt_contract import V1_ALLOWED_SCOPE, ValidationError, load_json, validate_dataset_contract, validate_execution_control

OPTIMIZER_RECORD_VERSION = "skillopt-continuous-optimizer-record-v0"
REWARD_MEMORY_VERSION = "skillopt-reward-memory-entry-v0"
LIVE_CANARY_HANDOFF_VERSION = "skillopt-live-canary-handoff-v0"
MINIMUM_NDCG_DELTA = 0.01
MAX_LIVE_P95_LATENCY_MS = 3000.0
_ACCEPTED_STATUS = "accepted"
_REWARD_BLOCKED_STATUSES = {"rejected", "rolled_back", "quarantined", "hash_mismatch", "holdout_leakage"}


def validate_evaluator_contract_v1(
    *,
    baseline_eval: Mapping[str, Any],
    candidate_eval: Mapping[str, Any],
    minimum_ndcg_delta: float = MINIMUM_NDCG_DELTA,
) -> None:
    """Validate the continuous-optimization evaluator contract.

    This is intentionally stricter than the generic retrieval comparator: the
    deterministic replay approval threshold is +0.01 nDCG@10 and any live-measured
    latency must stay under 3000ms as well as non-regress against baseline.
    """
    validate_retrieval_evaluation_record(baseline_eval)
    validate_retrieval_evaluation_record(candidate_eval)
    assert_candidate_beats_baseline(
        baseline_record=baseline_eval,
        candidate_record=candidate_eval,
        minimum_delta=minimum_ndcg_delta,
    )
    if float(candidate_eval["p95_latency_ms"]) > MAX_LIVE_P95_LATENCY_MS:
        raise ValidationError("candidate p95_latency_ms exceeds live canary limit")


def load_approved_policy_artifact_from_path(path: str | Path) -> dict[str, Any]:
    """Load a persisted approved policy artifact and annotate its file path.

    ``export_approved_skillopt_policy`` returns transient helper paths, while the
    persisted JSON intentionally contains only the stable artifact schema. This
    loader bridges the two shapes without changing the artifact hash contract.
    """
    artifact_path = Path(path)
    artifact = load_json(artifact_path)
    validate_approved_policy_artifact(artifact)
    return {**artifact, "artifact_path": str(artifact_path)}


def build_optimizer_decision_record(
    *,
    run_id: str,
    approved_policy_artifact: Mapping[str, Any],
    baseline_eval: Mapping[str, Any],
    candidate_eval: Mapping[str, Any],
    dataset_path: str | Path,
    control_path: str | Path,
    baseline_skill_path: str | Path,
    materialization_manifest_path: str | Path,
    status: str = _ACCEPTED_STATUS,
    rolled_back: bool = False,
    quarantined: bool = False,
    holdout_leakage_detected: bool = False,
) -> dict[str, Any]:
    """Build a hash-bound optimizer decision record for reward-memory gating."""
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValidationError("optimizer run_id is required")
    validate_approved_policy_artifact(approved_policy_artifact)
    validate_evaluator_contract_v1(
        baseline_eval=baseline_eval,
        candidate_eval=candidate_eval,
    )
    dataset = load_json(dataset_path)
    control = load_json(control_path)
    validate_dataset_contract(dataset)
    validate_execution_control(control)
    manifest = load_json(materialization_manifest_path)
    validate_skillopt_materialization_manifest(manifest)

    skill_hash = str(approved_policy_artifact["skill_hash"])
    baseline_hash = str(approved_policy_artifact["baseline_hash"])
    baseline_file_hash = canonical_file_hash(baseline_skill_path)
    materialization_file_hash = canonical_file_hash(materialization_manifest_path)
    metrics = approved_policy_artifact["metric_snapshot"]
    if candidate_eval.get("evaluated_skill_hash") != skill_hash:
        raise ValidationError("optimizer candidate_eval evaluated_skill_hash must match approved skill_hash")
    selection_ids = [str(query["query_id"]) for query in dataset["queries"] if query["split"] == "selection"]
    selection_baseline_eval = split_retrieval_evaluation_record(baseline_eval, selection_ids)
    selection_candidate_eval = split_retrieval_evaluation_record(candidate_eval, selection_ids)
    if _mapping_hash(selection_baseline_eval) != metrics.get("baseline_eval_hash"):
        raise ValidationError("optimizer baseline_eval hash must match approved artifact")
    if _mapping_hash(selection_candidate_eval) != metrics.get("candidate_eval_hash"):
        raise ValidationError("optimizer candidate_eval hash must match approved artifact")
    if baseline_eval.get("dataset_hash") != dataset.get("dataset_hash"):
        raise ValidationError("optimizer baseline_eval dataset_hash mismatch")
    if candidate_eval.get("dataset_hash") != dataset.get("dataset_hash"):
        raise ValidationError("optimizer candidate_eval dataset_hash mismatch")
    if approved_policy_artifact.get("dataset_hash") != dataset.get("dataset_hash"):
        raise ValidationError("optimizer approved policy dataset_hash mismatch")
    if approved_policy_artifact.get("execution_control_hash") != control.get("control_hash"):
        raise ValidationError("optimizer approved policy execution_control_hash mismatch")
    if baseline_file_hash != baseline_hash:
        raise ValidationError("optimizer baseline_skill_path hash must match approved baseline_hash")
    if materialization_file_hash != approved_policy_artifact.get("materialization_manifest_hash"):
        raise ValidationError("optimizer materialization manifest hash must match approved artifact")
    if manifest.get("dataset_hash") != dataset.get("dataset_hash"):
        raise ValidationError("optimizer materialization dataset_hash mismatch")
    if manifest.get("execution_control_hash") != control.get("control_hash"):
        raise ValidationError("optimizer materialization execution_control_hash mismatch")
    expected_source_hashes = {
        "dataset_file": canonical_file_hash(dataset_path),
        "control_file": canonical_file_hash(control_path),
        "baseline_skill_file": baseline_file_hash,
    }
    if dict(manifest.get("source_hashes", {})) != expected_source_hashes:
        raise ValidationError("optimizer materialization source_hashes mismatch")

    reward = round(
        float(selection_candidate_eval["nDCG@10"])
        - float(selection_baseline_eval["nDCG@10"]),
        6,
    )
    record = {
        "version": OPTIMIZER_RECORD_VERSION,
        "run_id": run_id.strip(),
        "created_at": _utc_now_iso(),
        "status": status,
        "scope": V1_ALLOWED_SCOPE,
        "reward": reward,
        "reward_source": "approved_policy_export",
        "candidate_skill_hash": skill_hash,
        "evaluated_skill_hash": candidate_eval.get("evaluated_skill_hash"),
        "baseline_hash": baseline_hash,
        "dataset_hash": dataset["dataset_hash"],
        "execution_control_hash": control["control_hash"],
        "approved_policy_artifact_hash": _artifact_hash(approved_policy_artifact),
        "approved_policy_artifact_file_hash": canonical_file_hash(approved_policy_artifact["artifact_path"]),
        "selection_gate": approved_policy_artifact["selection_gate"],
        "holdout_gate": approved_policy_artifact["holdout_gate"],
        "metric_snapshot": approved_policy_artifact["metric_snapshot"],
        "lineage": {
            "dataset_file": canonical_file_hash(dataset_path),
            "control_file": canonical_file_hash(control_path),
            "baseline_skill_file": baseline_file_hash,
            "materialization_manifest_file": materialization_file_hash,
        },
        "provenance": {
            "raw_user_logs_included": False,
            "pii_included": False,
            "holdout_leakage_detected": bool(holdout_leakage_detected),
        },
        "safety": {
            "rolled_back": bool(rolled_back),
            "quarantined": bool(quarantined),
            "runtime_default_off": True,
            "hash_pinned": True,
        },
        "rollback_to": approved_policy_artifact["rollback_to"],
        "holdout_lineage": {
            "generation_id": f"holdout:{dataset['dataset_hash']}:test",
            "split": "test",
            "reuse_as_training": False,
            "rotation_required_for_next_iteration": True,
        },
    }
    validate_optimizer_decision_record(record)
    return record


def validate_optimizer_decision_record(record: Mapping[str, Any]) -> None:
    """Validate that an optimizer decision is eligible for downstream use."""
    required = {
        "version",
        "run_id",
        "created_at",
        "status",
        "scope",
        "reward",
        "reward_source",
        "candidate_skill_hash",
        "evaluated_skill_hash",
        "baseline_hash",
        "dataset_hash",
        "execution_control_hash",
        "approved_policy_artifact_hash",
        "approved_policy_artifact_file_hash",
        "selection_gate",
        "holdout_gate",
        "metric_snapshot",
        "lineage",
        "provenance",
        "safety",
        "rollback_to",
        "holdout_lineage",
    }
    missing = required - set(record)
    if missing:
        raise ValidationError(f"optimizer decision missing required keys: {sorted(missing)}")
    if record.get("version") != OPTIMIZER_RECORD_VERSION:
        raise ValidationError("optimizer decision version is invalid")
    if record.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("optimizer decision scope is invalid")
    _require_iso_datetime(record.get("created_at"), "optimizer.created_at")
    _require_digest(record.get("candidate_skill_hash"), "optimizer.candidate_skill_hash")
    _require_digest(record.get("evaluated_skill_hash"), "optimizer.evaluated_skill_hash")
    _require_digest(record.get("baseline_hash"), "optimizer.baseline_hash")
    _require_digest(record.get("approved_policy_artifact_hash"), "optimizer.approved_policy_artifact_hash")
    _require_digest(record.get("approved_policy_artifact_file_hash"), "optimizer.approved_policy_artifact_file_hash")
    if record.get("candidate_skill_hash") != record.get("evaluated_skill_hash"):
        raise ValidationError("optimizer evaluated_skill_hash must equal candidate_skill_hash")
    if record.get("candidate_skill_hash") == record.get("baseline_hash"):
        raise ValidationError("optimizer candidate must differ from baseline")
    reward = _finite_float(record.get("reward"), "optimizer.reward")
    if record.get("reward_source") != "approved_policy_export":
        raise ValidationError("optimizer reward_source must be approved_policy_export")
    status = record.get("status")
    if status != _ACCEPTED_STATUS and status not in _REWARD_BLOCKED_STATUSES:
        raise ValidationError("optimizer status is invalid")
    _validate_gate(record.get("selection_gate"), "selection_gate")
    _validate_gate(record.get("holdout_gate"), "holdout_gate")
    provenance = record.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValidationError("optimizer provenance must be an object")
    if provenance.get("raw_user_logs_included") is not False or provenance.get("pii_included") is not False:
        raise ValidationError("optimizer provenance must exclude raw logs and PII")
    if provenance.get("holdout_leakage_detected") is True:
        raise ValidationError("optimizer holdout leakage blocks release")
    safety = record.get("safety")
    if not isinstance(safety, Mapping):
        raise ValidationError("optimizer safety must be an object")
    if safety.get("runtime_default_off") is not True or safety.get("hash_pinned") is not True:
        raise ValidationError("optimizer safety must keep runtime default-off and hash-pinned")
    if status == _ACCEPTED_STATUS:
        if reward < MINIMUM_NDCG_DELTA:
            raise ValidationError("accepted optimizer reward must meet minimum nDCG delta")
        if safety.get("rolled_back") is True or safety.get("quarantined") is True:
            raise ValidationError("accepted optimizer record cannot be rolled back or quarantined")
    lineage = record.get("lineage")
    if not isinstance(lineage, Mapping):
        raise ValidationError("optimizer lineage must be an object")
    required_lineage = {"dataset_file", "control_file", "baseline_skill_file", "materialization_manifest_file"}
    if set(lineage) != required_lineage:
        raise ValidationError("optimizer lineage must bind dataset/control/baseline/materialization")
    for key, value in lineage.items():
        _require_digest(value, f"optimizer.lineage.{key}")
    rollback = record.get("rollback_to")
    if not isinstance(rollback, Mapping) or rollback.get("skill_hash") != record.get("baseline_hash"):
        raise ValidationError("optimizer rollback_to must point to baseline hash")
    _validate_holdout_lineage(record.get("holdout_lineage"))


def build_next_iteration_seed(decision_record: Mapping[str, Any], *, next_holdout_generation_id: str) -> dict[str, Any]:
    """Build the next optimizer seed only from an accepted approved policy.

    Continuous optimization may carry forward only a previously approved skill
    hash as the next baseline, and it must rotate holdout generation so repeated
    optimization cannot train against the same holdout feedback.
    """
    validate_optimizer_decision_record(decision_record)
    if decision_record.get("status") != _ACCEPTED_STATUS:
        raise ValidationError("next iteration seed requires an accepted optimizer decision")
    safety = decision_record["safety"]
    if safety.get("rolled_back") or safety.get("quarantined"):
        raise ValidationError("next iteration seed rejects rolled-back or quarantined decisions")
    holdout_lineage = decision_record["holdout_lineage"]
    if not isinstance(next_holdout_generation_id, str) or not next_holdout_generation_id.strip():
        raise ValidationError("next iteration seed requires next_holdout_generation_id")
    if next_holdout_generation_id == holdout_lineage["generation_id"]:
        raise ValidationError("next iteration seed requires rotated holdout generation")
    seed = {
        "version": "skillopt-next-iteration-seed-v0",
        "created_at": _utc_now_iso(),
        "scope": V1_ALLOWED_SCOPE,
        "previous_run_id": decision_record["run_id"],
        "baseline_hash": decision_record["candidate_skill_hash"],
        "baseline_source": "approved_policy_export",
        "dataset_hash": decision_record["dataset_hash"],
        "execution_control_hash": decision_record["execution_control_hash"],
        "reward_memory_anchor": decision_record["approved_policy_artifact_hash"],
        "reward_memory_file_anchor": decision_record["approved_policy_artifact_file_hash"],
        "previous_holdout_generation_id": holdout_lineage["generation_id"],
        "next_holdout_generation_id": next_holdout_generation_id.strip(),
        "holdout_reuse_policy": "rotate_holdout_generation_keep_test_split_read_only_no_training",
    }
    validate_next_iteration_seed(seed)
    return seed


def validate_next_iteration_seed(seed: Mapping[str, Any]) -> None:
    required = {
        "version",
        "created_at",
        "scope",
        "previous_run_id",
        "baseline_hash",
        "baseline_source",
        "dataset_hash",
        "execution_control_hash",
        "reward_memory_anchor",
        "reward_memory_file_anchor",
        "previous_holdout_generation_id",
        "next_holdout_generation_id",
        "holdout_reuse_policy",
    }
    missing = required - set(seed)
    if missing:
        raise ValidationError(f"next iteration seed missing required keys: {sorted(missing)}")
    if seed.get("version") != "skillopt-next-iteration-seed-v0":
        raise ValidationError("next iteration seed version is invalid")
    if seed.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("next iteration seed scope is invalid")
    _require_iso_datetime(seed.get("created_at"), "next_iteration.created_at")
    _require_digest(seed.get("baseline_hash"), "next_iteration.baseline_hash")
    _require_digest(seed.get("reward_memory_anchor"), "next_iteration.reward_memory_anchor")
    _require_digest(seed.get("reward_memory_file_anchor"), "next_iteration.reward_memory_file_anchor")
    if seed.get("baseline_source") != "approved_policy_export":
        raise ValidationError("next iteration seed baseline_source must be approved_policy_export")
    previous_generation = seed.get("previous_holdout_generation_id")
    next_generation = seed.get("next_holdout_generation_id")
    if not isinstance(previous_generation, str) or not previous_generation:
        raise ValidationError("next iteration seed previous_holdout_generation_id is required")
    if not isinstance(next_generation, str) or not next_generation or next_generation == previous_generation:
        raise ValidationError("next iteration seed requires rotated holdout generation")
    if seed.get("holdout_reuse_policy") != "rotate_holdout_generation_keep_test_split_read_only_no_training":
        raise ValidationError("next iteration seed must rotate holdout and keep test split out of training reward")


def _build_reward_memory_entry(
    decision_record: Mapping[str, Any],
    *,
    approved_policy_artifact_path: str | Path,
) -> dict[str, Any]:
    """Append one reward-memory entry from an accepted optimizer decision only.

    The approved policy must be loaded from a persisted export artifact path so a
    forged in-memory mapping cannot seed positive reward memory.
    """
    validate_optimizer_decision_record(decision_record)
    artifact_path = Path(approved_policy_artifact_path)
    approved_policy_artifact = load_json(artifact_path)
    validate_approved_policy_artifact(approved_policy_artifact)
    if canonical_file_hash(artifact_path) != decision_record.get("approved_policy_artifact_file_hash"):
        raise ValidationError("reward memory approved artifact file hash mismatch")
    if _artifact_hash(approved_policy_artifact) != decision_record.get("approved_policy_artifact_hash"):
        raise ValidationError("reward memory approved artifact schema hash mismatch")
    if approved_policy_artifact.get("skill_hash") != decision_record.get("candidate_skill_hash"):
        raise ValidationError("reward memory approved artifact skill hash mismatch")
    if approved_policy_artifact.get("dataset_hash") != decision_record.get("dataset_hash"):
        raise ValidationError("reward memory approved artifact dataset hash mismatch")
    if approved_policy_artifact.get("execution_control_hash") != decision_record.get("execution_control_hash"):
        raise ValidationError("reward memory approved artifact control hash mismatch")
    expected_reward = round(
        float(approved_policy_artifact["metric_snapshot"]["candidate"])
        - float(approved_policy_artifact["metric_snapshot"]["baseline"]),
        6,
    )
    if round(float(decision_record.get("reward", -1.0)), 6) != expected_reward:
        raise ValidationError("reward memory decision reward must match approved metric snapshot")
    for field in ("metric_snapshot", "selection_gate", "holdout_gate", "rollback_to"):
        if decision_record.get(field) != approved_policy_artifact.get(field):
            raise ValidationError(f"reward memory decision {field} must match approved artifact")
    if decision_record.get("status") != _ACCEPTED_STATUS:
        raise ValidationError("reward memory accepts only accepted optimizer decisions")
    safety = decision_record["safety"]
    if safety.get("rolled_back") or safety.get("quarantined"):
        raise ValidationError("reward memory rejects rolled-back or quarantined decisions")
    entry = {
        "version": REWARD_MEMORY_VERSION,
        "run_id": decision_record["run_id"],
        "created_at": _utc_now_iso(),
        "scope": V1_ALLOWED_SCOPE,
        "skill_hash": decision_record["candidate_skill_hash"],
        "reward": decision_record["reward"],
        "reward_source": decision_record["reward_source"],
        "dataset_hash": decision_record["dataset_hash"],
        "execution_control_hash": decision_record["execution_control_hash"],
        "approved_policy_artifact_hash": decision_record["approved_policy_artifact_hash"],
        "approved_policy_artifact_file_hash": decision_record["approved_policy_artifact_file_hash"],
    }
    validate_reward_memory_entry(entry)
    return entry


def append_reward_memory_entry(
    memory_path: str | Path,
    decision_record: Mapping[str, Any],
    *,
    approved_policy_artifact_path: str | Path,
) -> dict[str, Any]:
    entry = _build_reward_memory_entry(
        decision_record,
        approved_policy_artifact_path=approved_policy_artifact_path,
    )
    _append_reward_memory_entry_value(Path(memory_path), entry)
    return entry


def _append_reward_memory_entry_value(path: Path, entry: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock"):
        with path.open("a+", encoding="utf-8") as f:
            f.seek(0)
            _reject_duplicate_reward_memory_entry(
                f.read(),
                run_id=str(entry["run_id"]),
                artifact_file_hash=str(entry["approved_policy_artifact_file_hash"]),
            )
            f.seek(0, os.SEEK_END)
            f.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())


def validate_reward_memory_entry(entry: Mapping[str, Any]) -> None:
    required = {
        "version",
        "run_id",
        "created_at",
        "scope",
        "skill_hash",
        "reward",
        "reward_source",
        "dataset_hash",
        "execution_control_hash",
        "approved_policy_artifact_hash",
        "approved_policy_artifact_file_hash",
    }
    missing = required - set(entry)
    if missing:
        raise ValidationError(f"reward memory entry missing required keys: {sorted(missing)}")
    if entry.get("version") != REWARD_MEMORY_VERSION:
        raise ValidationError("reward memory entry version is invalid")
    if entry.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("reward memory entry scope is invalid")
    _require_iso_datetime(entry.get("created_at"), "reward_memory.created_at")
    _require_digest(entry.get("skill_hash"), "reward_memory.skill_hash")
    _require_digest(entry.get("approved_policy_artifact_hash"), "reward_memory.approved_policy_artifact_hash")
    _require_digest(entry.get("approved_policy_artifact_file_hash"), "reward_memory.approved_policy_artifact_file_hash")
    if _finite_float(entry.get("reward"), "reward_memory.reward") < MINIMUM_NDCG_DELTA:
        raise ValidationError("reward memory reward must meet minimum delta")
    if entry.get("reward_source") != "approved_policy_export":
        raise ValidationError("reward memory source must be approved_policy_export")


def build_live_canary_handoff(
    *,
    approved_policy_artifact_path: str | Path,
    manual_approval: Mapping[str, Any],
    rollback_sla_minutes: int,
) -> dict[str, Any]:
    """Build a manual live-canary handoff; never enables production by itself."""
    artifact_path = Path(approved_policy_artifact_path)
    artifact = load_json(artifact_path)
    validate_approved_policy_artifact(artifact)
    if not isinstance(manual_approval, Mapping):
        raise ValidationError("live canary manual_approval must be an object")
    approver = manual_approval.get("approved_by")
    if not isinstance(approver, str) or not approver.strip():
        raise ValidationError("live canary requires approved_by")
    approved_at = _parse_iso_datetime(manual_approval.get("approved_at"), "live_canary.approved_at")
    artifact_created_at = _parse_iso_datetime(artifact.get("created_at"), "live_canary.artifact.created_at")
    if approved_at < artifact_created_at:
        raise ValidationError("live canary manual approval is stale for this artifact")
    expires_at = _parse_iso_datetime(manual_approval.get("expires_at"), "live_canary.expires_at")
    if expires_at <= approved_at:
        raise ValidationError("live canary approval expires_at must be after approved_at")
    if manual_approval.get("artifact_hash") != canonical_file_hash(artifact_path):
        raise ValidationError("live canary manual approval artifact_hash is stale")
    if not isinstance(rollback_sla_minutes, int) or rollback_sla_minutes <= 0 or rollback_sla_minutes > 60:
        raise ValidationError("live canary rollback_sla_minutes must be 1..60")
    handoff = {
        "version": LIVE_CANARY_HANDOFF_VERSION,
        "created_at": _utc_now_iso(),
        "state": "manual_approval_required_before_enablement",
        "rollout_fraction": 0.0,
        "scope": V1_ALLOWED_SCOPE,
        "approved_policy_artifact_hash": canonical_file_hash(artifact_path),
        "artifact_created_at": artifact["created_at"],
        "runtime_policy_path": artifact["runtime_policy_path"],
        "approved_skill_hash": artifact["skill_hash"],
        "runtime_env": artifact["runtime_env"],
        "selection_gate": artifact["selection_gate"],
        "holdout_gate": artifact["holdout_gate"],
        "manual_approval": dict(manual_approval),
        "rollback_sla_minutes": rollback_sla_minutes,
        "rollback_to": artifact["rollback_to"],
    }
    validate_live_canary_handoff(handoff)
    return handoff


def validate_live_canary_handoff(handoff: Mapping[str, Any]) -> None:
    required = {
        "version",
        "created_at",
        "state",
        "rollout_fraction",
        "scope",
        "approved_policy_artifact_hash",
        "artifact_created_at",
        "runtime_policy_path",
        "approved_skill_hash",
        "runtime_env",
        "selection_gate",
        "holdout_gate",
        "manual_approval",
        "rollback_sla_minutes",
        "rollback_to",
    }
    missing = required - set(handoff)
    if missing:
        raise ValidationError(f"live canary handoff missing required keys: {sorted(missing)}")
    if handoff.get("version") != LIVE_CANARY_HANDOFF_VERSION:
        raise ValidationError("live canary handoff version is invalid")
    if handoff.get("state") != "manual_approval_required_before_enablement":
        raise ValidationError("live canary handoff must not enable rollout automatically")
    if float(handoff.get("rollout_fraction")) != 0.0:
        raise ValidationError("live canary handoff rollout_fraction must remain 0.0")
    if handoff.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("live canary handoff scope is invalid")
    _require_iso_datetime(handoff.get("created_at"), "live_canary.created_at")
    _require_digest(handoff.get("approved_policy_artifact_hash"), "live_canary.approved_policy_artifact_hash")
    artifact_created_at = _parse_iso_datetime(handoff.get("artifact_created_at"), "live_canary.artifact_created_at")
    _validate_gate(handoff.get("selection_gate"), "selection_gate")
    _validate_gate(handoff.get("holdout_gate"), "holdout_gate")
    manual = handoff.get("manual_approval")
    if not isinstance(manual, Mapping) or not manual.get("approved_by"):
        raise ValidationError("live canary handoff requires manual approval evidence")
    approved_at = _parse_iso_datetime(manual.get("approved_at"), "live_canary.manual_approval.approved_at")
    expires_at = _parse_iso_datetime(manual.get("expires_at"), "live_canary.manual_approval.expires_at")
    handoff_created_at = _parse_iso_datetime(handoff.get("created_at"), "live_canary.created_at")
    if approved_at < artifact_created_at:
        raise ValidationError("live canary handoff approval is stale for artifact")
    if expires_at <= approved_at or expires_at <= handoff_created_at:
        raise ValidationError("live canary handoff approval expiry must be after approval and handoff creation")
    if manual.get("artifact_hash") != handoff.get("approved_policy_artifact_hash"):
        raise ValidationError("live canary handoff manual approval hash mismatch")
    sla = handoff.get("rollback_sla_minutes")
    if not isinstance(sla, int) or sla <= 0 or sla > 60:
        raise ValidationError("live canary handoff rollback_sla_minutes must be 1..60")
    rollback = handoff.get("rollback_to")
    env = handoff.get("runtime_env")
    if not isinstance(rollback, Mapping) or not isinstance(env, Mapping):
        raise ValidationError("live canary handoff requires rollback and runtime env")
    required_env = {
        "SKILLOPT_SEARCH_POLICY_ENABLED",
        "SKILLOPT_SEARCH_POLICY_PATH",
        "SKILLOPT_SEARCH_POLICY_HASH",
        "SKILLOPT_SEARCH_POLICY_SCOPE",
    }
    if set(env) != required_env:
        raise ValidationError("live canary runtime_env must contain exactly the four rollout keys")
    if env.get("SKILLOPT_SEARCH_POLICY_ENABLED") != "true":
        raise ValidationError("live canary runtime_env enabled must be true")
    policy_path = env.get("SKILLOPT_SEARCH_POLICY_PATH")
    if not isinstance(policy_path, str) or not Path(policy_path).is_absolute():
        raise ValidationError("live canary runtime_env path must be absolute")
    _require_digest(env.get("SKILLOPT_SEARCH_POLICY_HASH"), "live_canary.runtime_env.policy_hash")
    if policy_path != handoff.get("runtime_policy_path"):
        raise ValidationError("live canary runtime_env path must match approved runtime_policy_path")
    _require_digest(handoff.get("approved_skill_hash"), "live_canary.approved_skill_hash")
    if env.get("SKILLOPT_SEARCH_POLICY_HASH") != handoff.get("approved_skill_hash"):
        raise ValidationError("live canary runtime_env hash must match approved skill hash")
    if env.get("SKILLOPT_SEARCH_POLICY_SCOPE") != V1_ALLOWED_SCOPE:
        raise ValidationError("live canary runtime_env scope is invalid")
    if rollback.get("skill_hash") == env.get("SKILLOPT_SEARCH_POLICY_HASH"):
        raise ValidationError("live canary rollback target must differ from candidate policy")


def run_continuous_optimization_iteration(
    *,
    run_id: str,
    output_dir: str | Path,
    approved_policy_artifact_path: str | Path,
    baseline_eval: Mapping[str, Any],
    candidate_eval: Mapping[str, Any],
    dataset_path: str | Path,
    control_path: str | Path,
    baseline_skill_path: str | Path,
    materialization_manifest_path: str | Path,
    reward_memory_path: str | Path,
    next_holdout_generation_id: str,
    manual_approval: Mapping[str, Any] | None = None,
    rollback_sla_minutes: int | None = None,
) -> dict[str, Any]:
    """Run one safe continuous-optimization bookkeeping iteration.

    This function does not invoke SkillOpt training or change runtime policy. It
    materializes the post-approval operating artifacts for one already-approved
    candidate: decision record, reward-memory entry, next-iteration seed, and
    optional live-canary handoff. All outputs are written under ``output_dir``.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    artifact_path = Path(approved_policy_artifact_path)
    approved_artifact = load_approved_policy_artifact_from_path(artifact_path)
    decision = build_optimizer_decision_record(
        run_id=run_id,
        approved_policy_artifact=approved_artifact,
        baseline_eval=baseline_eval,
        candidate_eval=candidate_eval,
        dataset_path=dataset_path,
        control_path=control_path,
        baseline_skill_path=baseline_skill_path,
        materialization_manifest_path=materialization_manifest_path,
    )
    decision_path = output / "optimizer_decision.json"
    decision_path.write_text(json.dumps(decision, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    next_seed = build_next_iteration_seed(
        decision,
        next_holdout_generation_id=next_holdout_generation_id,
    )
    next_seed_path = output / "next_iteration_seed.json"
    next_seed_path.write_text(json.dumps(next_seed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    live_canary_handoff = None
    live_canary_handoff_path = None
    if manual_approval is not None or rollback_sla_minutes is not None:
        if manual_approval is None or rollback_sla_minutes is None:
            raise ValidationError("live canary handoff requires both manual_approval and rollback_sla_minutes")
        live_canary_handoff = build_live_canary_handoff(
            approved_policy_artifact_path=artifact_path,
            manual_approval=manual_approval,
            rollback_sla_minutes=rollback_sla_minutes,
        )
        live_canary_handoff_path = output / "live_canary_handoff.json"
        live_canary_handoff_path.write_text(
            json.dumps(live_canary_handoff, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    reward_entry = _build_reward_memory_entry(
        decision,
        approved_policy_artifact_path=artifact_path,
    )
    reward_entry_path = output / "reward_memory_entry.json"
    reward_entry_path.write_text(json.dumps(reward_entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest = {
        "version": "skillopt-continuous-iteration-manifest-v0",
        "run_id": decision["run_id"],
        "created_at": _utc_now_iso(),
        "scope": V1_ALLOWED_SCOPE,
        "approved_policy_artifact_file_hash": decision["approved_policy_artifact_file_hash"],
        "decision_record_path": str(decision_path),
        "decision_record_hash": canonical_file_hash(decision_path),
        "reward_memory_path": str(Path(reward_memory_path)),
        "reward_memory_entry_path": str(reward_entry_path),
        "reward_memory_entry_hash": canonical_file_hash(reward_entry_path),
        "next_iteration_seed_path": str(next_seed_path),
        "next_iteration_seed_hash": canonical_file_hash(next_seed_path),
        "live_canary_handoff_path": str(live_canary_handoff_path) if live_canary_handoff_path else None,
        "live_canary_handoff_hash": canonical_file_hash(live_canary_handoff_path) if live_canary_handoff_path else None,
        "summary_path": None,
        "summary_hash": None,
        "status": "complete",
    }
    validate_continuous_iteration_manifest(manifest)
    summary = build_continuous_iteration_summary(
        manifest=manifest,
        decision=decision,
        reward_entry=reward_entry,
        next_iteration_seed=next_seed,
        live_canary_handoff=live_canary_handoff,
    )
    summary_path = output / "continuous_iteration_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest["summary_path"] = str(summary_path)
    manifest["summary_hash"] = canonical_file_hash(summary_path)
    validate_continuous_iteration_manifest(manifest)
    manifest_path = output / "continuous_iteration_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _append_reward_memory_entry_value(Path(reward_memory_path), reward_entry)
    return {
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "summary": summary,
        "summary_path": str(summary_path),
        "decision": decision,
        "reward_entry": reward_entry,
        "next_iteration_seed": next_seed,
        "live_canary_handoff": live_canary_handoff,
    }


def build_continuous_iteration_summary(
    *,
    manifest: Mapping[str, Any],
    decision: Mapping[str, Any],
    reward_entry: Mapping[str, Any],
    next_iteration_seed: Mapping[str, Any],
    live_canary_handoff: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a human-friendly but hash-bound summary for operators."""
    validate_continuous_iteration_manifest(manifest)
    validate_optimizer_decision_record(decision)
    validate_reward_memory_entry(reward_entry)
    validate_next_iteration_seed(next_iteration_seed)
    if live_canary_handoff is not None:
        validate_live_canary_handoff(live_canary_handoff)
    summary = {
        "version": "skillopt-continuous-iteration-summary-v0",
        "created_at": _utc_now_iso(),
        "run_id": decision["run_id"],
        "status": "complete",
        "scope": V1_ALLOWED_SCOPE,
        "reward": decision["reward"],
        "candidate_skill_hash": decision["candidate_skill_hash"],
        "baseline_hash": decision["baseline_hash"],
        "approved_policy_artifact_file_hash": decision["approved_policy_artifact_file_hash"],
        "manifest_hashes": {
            "decision_record_hash": manifest["decision_record_hash"],
            "reward_memory_entry_hash": manifest["reward_memory_entry_hash"],
            "next_iteration_seed_hash": manifest["next_iteration_seed_hash"],
            "live_canary_handoff_hash": manifest["live_canary_handoff_hash"],
        },
        "reward_memory": {
            "appended": True,
            "path": manifest["reward_memory_path"],
            "entry_hash": manifest["reward_memory_entry_hash"],
        },
        "next_iteration": {
            "baseline_hash": next_iteration_seed["baseline_hash"],
            "previous_holdout_generation_id": next_iteration_seed["previous_holdout_generation_id"],
            "next_holdout_generation_id": next_iteration_seed["next_holdout_generation_id"],
        },
        "live_canary": _summary_live_canary(live_canary_handoff),
    }
    validate_continuous_iteration_summary(summary)
    return summary


def validate_continuous_iteration_summary(summary: Mapping[str, Any]) -> None:
    required = {
        "version",
        "created_at",
        "run_id",
        "status",
        "scope",
        "reward",
        "candidate_skill_hash",
        "baseline_hash",
        "approved_policy_artifact_file_hash",
        "manifest_hashes",
        "reward_memory",
        "next_iteration",
        "live_canary",
    }
    missing = required - set(summary)
    if missing:
        raise ValidationError(f"continuous iteration summary missing required keys: {sorted(missing)}")
    if summary.get("version") != "skillopt-continuous-iteration-summary-v0":
        raise ValidationError("continuous iteration summary version is invalid")
    if summary.get("status") != "complete" or summary.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("continuous iteration summary status/scope is invalid")
    _require_iso_datetime(summary.get("created_at"), "continuous_iteration_summary.created_at")
    _require_digest(summary.get("candidate_skill_hash"), "continuous_iteration_summary.candidate_skill_hash")
    _require_digest(summary.get("baseline_hash"), "continuous_iteration_summary.baseline_hash")
    _require_digest(summary.get("approved_policy_artifact_file_hash"), "continuous_iteration_summary.approved_policy_artifact_file_hash")
    hashes = summary.get("manifest_hashes")
    if not isinstance(hashes, Mapping):
        raise ValidationError("continuous iteration summary manifest_hashes must be an object")
    for field in ("decision_record_hash", "reward_memory_entry_hash", "next_iteration_seed_hash"):
        _require_digest(hashes.get(field), f"continuous_iteration_summary.{field}")
    handoff_hash = hashes.get("live_canary_handoff_hash")
    if handoff_hash is not None:
        _require_digest(handoff_hash, "continuous_iteration_summary.live_canary_handoff_hash")
    reward_memory = summary.get("reward_memory")
    if not isinstance(reward_memory, Mapping) or reward_memory.get("appended") is not True:
        raise ValidationError("continuous iteration summary reward_memory must show appended=true")
    next_iteration = summary.get("next_iteration")
    if not isinstance(next_iteration, Mapping):
        raise ValidationError("continuous iteration summary next_iteration must be an object")
    _require_digest(next_iteration.get("baseline_hash"), "continuous_iteration_summary.next_iteration.baseline_hash")
    if next_iteration.get("previous_holdout_generation_id") == next_iteration.get("next_holdout_generation_id"):
        raise ValidationError("continuous iteration summary holdout generation must rotate")
    live_canary = summary.get("live_canary")
    if not isinstance(live_canary, Mapping):
        raise ValidationError("continuous iteration summary live_canary must be an object")
    if live_canary.get("present") is True and live_canary.get("rollout_fraction") != 0.0:
        raise ValidationError("continuous iteration summary live canary rollout must remain 0.0")


def validate_continuous_iteration_manifest(manifest: Mapping[str, Any]) -> None:
    required = {
        "version",
        "run_id",
        "created_at",
        "scope",
        "approved_policy_artifact_file_hash",
        "decision_record_path",
        "decision_record_hash",
        "reward_memory_path",
        "reward_memory_entry_path",
        "reward_memory_entry_hash",
        "next_iteration_seed_path",
        "next_iteration_seed_hash",
        "live_canary_handoff_path",
        "live_canary_handoff_hash",
        "summary_path",
        "summary_hash",
        "status",
    }
    missing = required - set(manifest)
    if missing:
        raise ValidationError(f"continuous iteration manifest missing required keys: {sorted(missing)}")
    if manifest.get("version") != "skillopt-continuous-iteration-manifest-v0":
        raise ValidationError("continuous iteration manifest version is invalid")
    if manifest.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("continuous iteration manifest scope is invalid")
    if manifest.get("status") != "complete":
        raise ValidationError("continuous iteration manifest status must be complete")
    _require_iso_datetime(manifest.get("created_at"), "continuous_iteration.created_at")
    for field in (
        "approved_policy_artifact_file_hash",
        "decision_record_hash",
        "reward_memory_entry_hash",
        "next_iteration_seed_hash",
    ):
        _require_digest(manifest.get(field), f"continuous_iteration.{field}")
    _require_existing_file_hash(manifest.get("decision_record_path"), manifest.get("decision_record_hash"), "decision_record")
    _require_existing_file_hash(manifest.get("reward_memory_entry_path"), manifest.get("reward_memory_entry_hash"), "reward_memory_entry")
    _require_existing_file_hash(manifest.get("next_iteration_seed_path"), manifest.get("next_iteration_seed_hash"), "next_iteration_seed")
    summary_path = manifest.get("summary_path")
    summary_hash = manifest.get("summary_hash")
    if summary_path is not None:
        _require_existing_file_hash(summary_path, summary_hash, "summary")
    elif summary_hash is not None:
        raise ValidationError("continuous iteration summary hash must be null when summary path is null")
    handoff_path = manifest.get("live_canary_handoff_path")
    handoff_hash = manifest.get("live_canary_handoff_hash")
    if handoff_path is None:
        if handoff_hash is not None:
            raise ValidationError("continuous iteration handoff hash must be null when handoff path is null")
    else:
        if not isinstance(handoff_path, str) or not handoff_path:
            raise ValidationError("continuous iteration handoff path is invalid")
        _require_digest(handoff_hash, "continuous_iteration.live_canary_handoff_hash")
        _require_existing_file_hash(handoff_path, handoff_hash, "live_canary_handoff")


def _summary_live_canary(handoff: Mapping[str, Any] | None) -> dict[str, Any]:
    if handoff is None:
        return {"present": False}
    manual = handoff["manual_approval"]
    return {
        "present": True,
        "state": handoff["state"],
        "rollout_fraction": handoff["rollout_fraction"],
        "approved_by": manual["approved_by"],
        "approved_at": manual["approved_at"],
        "expires_at": manual["expires_at"],
        "rollback_sla_minutes": handoff["rollback_sla_minutes"],
        "approved_policy_artifact_hash": handoff["approved_policy_artifact_hash"],
    }


def _reject_duplicate_reward_memory_entry(memory_text: str, *, run_id: str, artifact_file_hash: str) -> None:
    for line_number, line in enumerate(memory_text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"reward memory contains invalid JSON at line {line_number}") from exc
        if row.get("run_id") == run_id:
            raise ValidationError("reward memory duplicate run_id")
        if row.get("approved_policy_artifact_file_hash") == artifact_file_hash:
            raise ValidationError("reward memory duplicate approved artifact")


def _require_existing_file_hash(path_value: Any, expected_hash: Any, field: str) -> None:
    if not isinstance(path_value, str) or not path_value:
        raise ValidationError(f"continuous iteration {field} path is required")
    _require_digest(expected_hash, f"continuous_iteration.{field}_hash")
    path = Path(path_value)
    if not path.is_file():
        raise ValidationError(f"continuous iteration {field} file is missing")
    if canonical_file_hash(path) != expected_hash:
        raise ValidationError(f"continuous iteration {field} hash mismatch")


def _validate_holdout_lineage(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise ValidationError("optimizer holdout_lineage must be an object")
    generation = value.get("generation_id")
    if not isinstance(generation, str) or not generation.strip():
        raise ValidationError("optimizer holdout_lineage.generation_id is required")
    if value.get("split") != "test":
        raise ValidationError("optimizer holdout_lineage.split must be test")
    if value.get("reuse_as_training") is not False:
        raise ValidationError("optimizer holdout must never be reused as training reward")
    if value.get("rotation_required_for_next_iteration") is not True:
        raise ValidationError("optimizer holdout rotation proof is required")


def _mapping_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    import hashlib

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _artifact_hash(artifact: Mapping[str, Any]) -> str:
    schema_artifact = {
        key: value
        for key, value in artifact.items()
        if key not in {"artifact_path", "runtime_env_path"}
    }
    payload = json.dumps(schema_artifact, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    import hashlib

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_gate(gate: Any, field: str) -> None:
    if not isinstance(gate, Mapping) or gate.get("status") != "passed":
        raise ValidationError(f"optimizer {field} must be passed")
    rows = gate.get("per_query")
    if not isinstance(rows, list) or not rows:
        raise ValidationError(f"optimizer {field}.per_query is required")
    for row in rows:
        if not isinstance(row, Mapping) or row.get("passed") is not True:
            raise ValidationError(f"optimizer {field}.per_query must all pass")
        if _finite_float(row.get("ndcg_at_10"), f"{field}.ndcg_at_10") <= 0.0:
            raise ValidationError(f"optimizer {field} ndcg_at_10 must be positive")
        if _finite_float(row.get("recall_at_10"), f"{field}.recall_at_10") <= 0.0:
            raise ValidationError(f"optimizer {field} recall_at_10 must be positive")


def _finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValidationError(f"{field} must be finite")
    return number


def _require_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise ValidationError(f"{field} must be a sha256 digest")
    suffix = value[len("sha256:"):]
    if any(ch not in "0123456789abcdef" for ch in suffix):
        raise ValidationError(f"{field} must be a sha256 digest")
    return value


def _require_iso_datetime(value: Any, field: str) -> None:
    _parse_iso_datetime(value, field)


def _parse_iso_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
