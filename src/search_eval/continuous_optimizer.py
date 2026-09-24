"""Continuous SkillOpt/RL optimization gates for paper search.

The functions here keep the continuous-optimization loop dev/eval-only. They do
not call the production search path and they never mutate runtime policy state;
instead they validate lineage, evaluator gates, reward-memory eligibility, and
manual live-canary handoff artifacts.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import unicodedata
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from filelock import FileLock

from .approved_policy import (
    ValidatedApprovedSkillOptPolicy,
    load_validated_approved_skillopt_policy,
    split_retrieval_evaluation_record,
    validate_approved_policy_artifact,
)
from .retrieval_eval import (
    assert_candidate_beats_baseline,
    validate_retrieval_evaluation_record,
)
from .skillopt_adapter import canonical_file_hash
from .skillopt_contract import (
    V1_ALLOWED_SCOPE,
    ValidationError,
    load_json,
    validate_dataset_contract,
    validate_execution_control,
)

OPTIMIZER_RECORD_VERSION = "skillopt-continuous-optimizer-record-v1"
NEXT_ITERATION_SEED_VERSION = "skillopt-next-iteration-seed-v1"
REWARD_MEMORY_VERSION = "skillopt-reward-memory-entry-v1"
LIVE_CANARY_HANDOFF_VERSION = "skillopt-live-canary-handoff-v1"
CONTINUOUS_MANIFEST_VERSION = "skillopt-continuous-iteration-manifest-v1"
CONTINUOUS_SUMMARY_VERSION = "skillopt-continuous-iteration-summary-v1"
CONTINUOUS_TRANSACTION_VERSION = "skillopt-continuous-transaction-v1"
CONTINUOUS_REWARD_COMMIT_VERSION = "skillopt-continuous-reward-commit-v1"
MINIMUM_NDCG_DELTA = 0.01
MAX_LIVE_P95_LATENCY_MS = 3000.0
_ACCEPTED_STATUS = "accepted"
_REWARD_BLOCKED_STATUSES = {
    "rejected",
    "rolled_back",
    "quarantined",
    "hash_mismatch",
}
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_-]{0,126}[A-Za-z0-9])?\Z")
MAX_RUN_ID_LENGTH = 128


@dataclass(frozen=True)
class ValidatedApprovalReceipt:
    """Opaque optimizer anchor for one fully revalidated approval.

    The receipt deliberately retains only hashes and default-off/rollback facts
    needed by optimizer consumers.  Release evaluation, generation, evaluator,
    threshold, metric, and approval-capability details never cross this boundary.
    """

    artifact_path: Path
    artifact_schema_hash: str
    artifact_file_hash: str
    skill_hash: str
    baseline_hash: str
    dataset_hash: str
    execution_control_hash: str
    rollback_version: str
    rollback_skill_hash: str
    runtime_default_off: bool


@dataclass(frozen=True)
class ValidatedOptimizerDecisionRecord(Mapping[str, Any]):
    _record: Mapping[str, Any]
    approval_receipt: ValidatedApprovalReceipt

    def __getitem__(self, key: str) -> Any:
        return deepcopy(self._record[key])

    def __iter__(self) -> Iterator[str]:
        return iter(self._record)

    def __len__(self) -> int:
        return len(self._record)

    def persisted_record(self) -> dict[str, Any]:
        return deepcopy(dict(self._record))


@dataclass
class _OutputLease:
    root_path: Path
    root_fd: int
    run_id: str
    run_fd: int
    chain: tuple[tuple[str, os.stat_result], ...]
    run_stat: os.stat_result
    artifacts: dict[str, os.stat_result]
    created: bool


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


def load_approved_policy_artifact_from_path(
    path: str | Path,
) -> ValidatedApprovedSkillOptPolicy:
    """Load a persisted approved policy artifact and annotate its file path.

    ``export_approved_skillopt_policy`` returns transient helper paths, while the
    persisted JSON intentionally contains only the stable artifact schema. This
    loader bridges the two shapes without changing the artifact hash contract.
    """
    return load_validated_approved_skillopt_policy(path)


def build_optimizer_decision_record(
    *,
    run_id: str,
    approved_policy_artifact: ValidatedApprovedSkillOptPolicy,
    baseline_eval: Mapping[str, Any],
    candidate_eval: Mapping[str, Any],
    dataset_path: str | Path,
    control_path: str | Path,
    baseline_skill_path: str | Path,
    status: str = _ACCEPTED_STATUS,
    rolled_back: bool = False,
    quarantined: bool = False,
) -> ValidatedOptimizerDecisionRecord:
    """Build a hash-bound optimizer decision record for reward-memory gating."""
    run_id = validate_optimizer_run_id(run_id)
    approved_policy_artifact = _fresh_approved_policy(approved_policy_artifact)
    validate_approved_policy_artifact(approved_policy_artifact)
    validate_evaluator_contract_v1(
        baseline_eval=baseline_eval,
        candidate_eval=candidate_eval,
    )
    dataset = load_json(dataset_path)
    control = load_json(control_path)
    validate_dataset_contract(dataset)
    validate_execution_control(control)

    skill_hash = str(approved_policy_artifact["skill_hash"])
    baseline_hash = str(approved_policy_artifact["baseline_hash"])
    baseline_file_hash = canonical_file_hash(baseline_skill_path)
    metrics = approved_policy_artifact["metric_snapshot"]
    if candidate_eval.get("evaluated_skill_hash") != skill_hash:
        raise ValidationError(
            "optimizer candidate_eval evaluated_skill_hash must match approved skill_hash"
        )
    selection_ids = [
        str(query["query_id"])
        for query in dataset["queries"]
        if query["split"] == "selection"
    ]
    selection_baseline_eval = split_retrieval_evaluation_record(
        baseline_eval, selection_ids
    )
    selection_candidate_eval = split_retrieval_evaluation_record(
        candidate_eval, selection_ids
    )
    if _mapping_hash(selection_baseline_eval) != metrics.get("baseline_eval_hash"):
        raise ValidationError(
            "optimizer baseline_eval hash must match approved artifact"
        )
    if _mapping_hash(selection_candidate_eval) != metrics.get("candidate_eval_hash"):
        raise ValidationError(
            "optimizer candidate_eval hash must match approved artifact"
        )
    if baseline_eval.get("dataset_hash") != dataset.get("dataset_hash"):
        raise ValidationError("optimizer baseline_eval dataset_hash mismatch")
    if candidate_eval.get("dataset_hash") != dataset.get("dataset_hash"):
        raise ValidationError("optimizer candidate_eval dataset_hash mismatch")
    if approved_policy_artifact.get("dataset_hash") != dataset.get("dataset_hash"):
        raise ValidationError("optimizer approved policy dataset_hash mismatch")
    if approved_policy_artifact.get("execution_control_hash") != control.get(
        "control_hash"
    ):
        raise ValidationError(
            "optimizer approved policy execution_control_hash mismatch"
        )
    if baseline_file_hash != baseline_hash:
        raise ValidationError(
            "optimizer baseline_skill_path hash must match approved baseline_hash"
        )
    reward = round(
        float(selection_candidate_eval["nDCG@10"])
        - float(selection_baseline_eval["nDCG@10"]),
        6,
    )
    record = {
        "version": OPTIMIZER_RECORD_VERSION,
        "run_id": run_id,
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
        "approved_policy_artifact_file_hash": approved_policy_artifact.artifact_hash,
        "lineage": {
            "dataset_file": canonical_file_hash(dataset_path),
            "control_file": canonical_file_hash(control_path),
            "baseline_skill_file": baseline_file_hash,
        },
        "provenance": {
            "raw_user_logs_included": False,
            "pii_included": False,
            "release_holdout_feedback_included": False,
            "release_evaluation_managed_externally": True,
        },
        "safety": {
            "rolled_back": bool(rolled_back),
            "quarantined": bool(quarantined),
            "runtime_default_off": True,
            "hash_pinned": True,
        },
        "rollback_to": approved_policy_artifact["rollback_to"],
    }
    validate_optimizer_decision_record(record)
    return ValidatedOptimizerDecisionRecord(
        _record=record,
        approval_receipt=_approval_receipt(approved_policy_artifact),
    )


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
        "lineage",
        "provenance",
        "safety",
        "rollback_to",
    }
    missing = required - set(record)
    if missing:
        raise ValidationError(
            f"optimizer decision missing required keys: {sorted(missing)}"
        )
    if set(record) != required:
        raise ValidationError("optimizer decision schema contains unsupported fields")
    if record.get("version") != OPTIMIZER_RECORD_VERSION:
        raise ValidationError("optimizer decision version is invalid")
    validate_optimizer_run_id(record.get("run_id"))
    if record.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("optimizer decision scope is invalid")
    _require_iso_datetime(record.get("created_at"), "optimizer.created_at")
    _require_digest(
        record.get("candidate_skill_hash"), "optimizer.candidate_skill_hash"
    )
    _require_digest(
        record.get("evaluated_skill_hash"), "optimizer.evaluated_skill_hash"
    )
    _require_digest(record.get("baseline_hash"), "optimizer.baseline_hash")
    _require_digest(
        record.get("approved_policy_artifact_hash"),
        "optimizer.approved_policy_artifact_hash",
    )
    _require_digest(
        record.get("approved_policy_artifact_file_hash"),
        "optimizer.approved_policy_artifact_file_hash",
    )
    if record.get("candidate_skill_hash") != record.get("evaluated_skill_hash"):
        raise ValidationError(
            "optimizer evaluated_skill_hash must equal candidate_skill_hash"
        )
    if record.get("candidate_skill_hash") == record.get("baseline_hash"):
        raise ValidationError("optimizer candidate must differ from baseline")
    reward = _finite_float(record.get("reward"), "optimizer.reward")
    if record.get("reward_source") != "approved_policy_export":
        raise ValidationError("optimizer reward_source must be approved_policy_export")
    status = record.get("status")
    if status != _ACCEPTED_STATUS and status not in _REWARD_BLOCKED_STATUSES:
        raise ValidationError("optimizer status is invalid")
    provenance = record.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValidationError("optimizer provenance must be an object")
    if (
        provenance.get("raw_user_logs_included") is not False
        or provenance.get("pii_included") is not False
    ):
        raise ValidationError("optimizer provenance must exclude raw logs and PII")
    if set(provenance) != {
        "raw_user_logs_included",
        "pii_included",
        "release_holdout_feedback_included",
        "release_evaluation_managed_externally",
    }:
        raise ValidationError("optimizer provenance schema is invalid")
    if (
        provenance.get("release_holdout_feedback_included") is not False
        or provenance.get("release_evaluation_managed_externally") is not True
    ):
        raise ValidationError(
            "optimizer must exclude externally managed release feedback"
        )
    safety = record.get("safety")
    if not isinstance(safety, Mapping):
        raise ValidationError("optimizer safety must be an object")
    _require_exact_mapping(
        safety,
        {"rolled_back", "quarantined", "runtime_default_off", "hash_pinned"},
        "optimizer safety",
    )
    if (
        safety.get("runtime_default_off") is not True
        or safety.get("hash_pinned") is not True
    ):
        raise ValidationError(
            "optimizer safety must keep runtime default-off and hash-pinned"
        )
    if status == _ACCEPTED_STATUS:
        if reward < MINIMUM_NDCG_DELTA:
            raise ValidationError(
                "accepted optimizer reward must meet minimum nDCG delta"
            )
        if safety.get("rolled_back") is True or safety.get("quarantined") is True:
            raise ValidationError(
                "accepted optimizer record cannot be rolled back or quarantined"
            )
    lineage = record.get("lineage")
    if not isinstance(lineage, Mapping):
        raise ValidationError("optimizer lineage must be an object")
    required_lineage = {
        "dataset_file",
        "control_file",
        "baseline_skill_file",
    }
    if set(lineage) != required_lineage:
        raise ValidationError("optimizer lineage must bind dataset/control/baseline")
    for key, value in lineage.items():
        _require_digest(value, f"optimizer.lineage.{key}")
    rollback = record.get("rollback_to")
    if not isinstance(rollback, Mapping) or rollback.get("skill_hash") != record.get(
        "baseline_hash"
    ):
        raise ValidationError("optimizer rollback_to must point to baseline hash")
    _require_exact_mapping(rollback, {"version", "skill_hash"}, "optimizer rollback_to")
    _reject_release_feedback(record, "optimizer")


def build_next_iteration_seed(decision_record: Mapping[str, Any]) -> dict[str, Any]:
    """Build the next optimizer seed only from an accepted approved policy.

    Continuous optimization may carry forward only a previously approved skill
    hash as the next baseline. Release-set rotation is proven by a separate
    release-authority capability and is never represented in optimizer state.
    """
    validate_optimizer_decision_record(decision_record)
    if decision_record.get("status") != _ACCEPTED_STATUS:
        raise ValidationError(
            "next iteration seed requires an accepted optimizer decision"
        )
    safety = decision_record["safety"]
    if safety.get("rolled_back") or safety.get("quarantined"):
        raise ValidationError(
            "next iteration seed rejects rolled-back or quarantined decisions"
        )
    if not isinstance(decision_record, ValidatedOptimizerDecisionRecord):
        raise ValidationError(
            "next iteration seed requires a fully validated accepted optimizer decision"
        )
    approved_policy = _fresh_approved_policy_from_receipt(
        decision_record.approval_receipt
    )
    _validate_decision_matches_approved_policy(decision_record, approved_policy)
    seed = {
        "version": NEXT_ITERATION_SEED_VERSION,
        "created_at": _utc_now_iso(),
        "scope": V1_ALLOWED_SCOPE,
        "previous_run_id": decision_record["run_id"],
        "baseline_hash": decision_record["candidate_skill_hash"],
        "baseline_source": "approved_policy_export",
        "dataset_hash": decision_record["dataset_hash"],
        "execution_control_hash": decision_record["execution_control_hash"],
        "reward_memory_anchor": decision_record["approved_policy_artifact_hash"],
        "reward_memory_file_anchor": decision_record[
            "approved_policy_artifact_file_hash"
        ],
        "release_holdout_feedback_included": False,
        "release_evaluation_managed_externally": True,
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
        "release_holdout_feedback_included",
        "release_evaluation_managed_externally",
    }
    missing = required - set(seed)
    if missing:
        raise ValidationError(
            f"next iteration seed missing required keys: {sorted(missing)}"
        )
    if set(seed) != required:
        raise ValidationError("next iteration seed schema contains unsupported fields")
    if seed.get("version") != NEXT_ITERATION_SEED_VERSION:
        raise ValidationError("next iteration seed version is invalid")
    validate_optimizer_run_id(seed.get("previous_run_id"))
    if seed.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("next iteration seed scope is invalid")
    _require_iso_datetime(seed.get("created_at"), "next_iteration.created_at")
    _require_digest(seed.get("baseline_hash"), "next_iteration.baseline_hash")
    _require_digest(
        seed.get("reward_memory_anchor"), "next_iteration.reward_memory_anchor"
    )
    _require_digest(
        seed.get("reward_memory_file_anchor"),
        "next_iteration.reward_memory_file_anchor",
    )
    if seed.get("baseline_source") != "approved_policy_export":
        raise ValidationError(
            "next iteration seed baseline_source must be approved_policy_export"
        )
    if (
        seed.get("release_holdout_feedback_included") is not False
        or seed.get("release_evaluation_managed_externally") is not True
    ):
        raise ValidationError(
            "next iteration seed must exclude external release feedback"
        )
    _reject_release_feedback(seed, "next_iteration")


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
    approved_policy_artifact = load_approved_policy_artifact_from_path(
        approved_policy_artifact_path
    )
    if approved_policy_artifact.artifact_hash != decision_record.get(
        "approved_policy_artifact_file_hash"
    ):
        raise ValidationError("reward memory approved artifact file hash mismatch")
    if _artifact_hash(approved_policy_artifact) != decision_record.get(
        "approved_policy_artifact_hash"
    ):
        raise ValidationError("reward memory approved artifact schema hash mismatch")
    if approved_policy_artifact.get("skill_hash") != decision_record.get(
        "candidate_skill_hash"
    ):
        raise ValidationError("reward memory approved artifact skill hash mismatch")
    if approved_policy_artifact.get("dataset_hash") != decision_record.get(
        "dataset_hash"
    ):
        raise ValidationError("reward memory approved artifact dataset hash mismatch")
    if approved_policy_artifact.get("execution_control_hash") != decision_record.get(
        "execution_control_hash"
    ):
        raise ValidationError("reward memory approved artifact control hash mismatch")
    expected_reward = round(
        float(approved_policy_artifact["metric_snapshot"]["candidate"])
        - float(approved_policy_artifact["metric_snapshot"]["baseline"]),
        6,
    )
    if round(float(decision_record.get("reward", -1.0)), 6) != expected_reward:
        raise ValidationError(
            "reward memory decision reward must match approved metric snapshot"
        )
    for field in ("rollback_to",):
        if decision_record.get(field) != approved_policy_artifact.get(field):
            raise ValidationError(
                f"reward memory decision {field} must match approved artifact"
            )
    if not isinstance(decision_record, ValidatedOptimizerDecisionRecord):
        raise ValidationError(
            "reward memory requires a fully validated optimizer decision object"
        )
    if (
        decision_record.approval_receipt.artifact_file_hash
        != approved_policy_artifact.artifact_hash
    ):
        raise ValidationError("reward memory optimizer approval capability mismatch")
    if decision_record.get("status") != _ACCEPTED_STATUS:
        raise ValidationError("reward memory accepts only accepted optimizer decisions")
    safety = decision_record["safety"]
    if safety.get("rolled_back") or safety.get("quarantined"):
        raise ValidationError(
            "reward memory rejects rolled-back or quarantined decisions"
        )
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
        "approved_policy_artifact_hash": decision_record[
            "approved_policy_artifact_hash"
        ],
        "approved_policy_artifact_file_hash": decision_record[
            "approved_policy_artifact_file_hash"
        ],
        "release_holdout_feedback_included": False,
        "release_evaluation_managed_externally": True,
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
    return _append_reward_memory_entry_value(Path(memory_path), entry)


def _append_reward_memory_entry_value(
    path: Path, entry: Mapping[str, Any]
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock"):
        memory_text = path.read_text(encoding="utf-8") if path.exists() else ""
        committed = _matching_reward_memory_entry(memory_text, entry=entry)
        if committed is not None:
            return committed
        payload = memory_text
        if payload and not payload.endswith("\n"):
            payload += "\n"
        payload += json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n"
        _atomic_write_text(path, payload)
        return deepcopy(dict(entry))


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
        "release_holdout_feedback_included",
        "release_evaluation_managed_externally",
    }
    missing = required - set(entry)
    if missing:
        raise ValidationError(
            f"reward memory entry missing required keys: {sorted(missing)}"
        )
    if set(entry) != required:
        raise ValidationError("reward memory entry schema contains unsupported fields")
    if entry.get("version") != REWARD_MEMORY_VERSION:
        raise ValidationError("reward memory entry version is invalid")
    validate_optimizer_run_id(entry.get("run_id"))
    if entry.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("reward memory entry scope is invalid")
    _require_iso_datetime(entry.get("created_at"), "reward_memory.created_at")
    _require_digest(entry.get("skill_hash"), "reward_memory.skill_hash")
    _require_digest(
        entry.get("approved_policy_artifact_hash"),
        "reward_memory.approved_policy_artifact_hash",
    )
    _require_digest(
        entry.get("approved_policy_artifact_file_hash"),
        "reward_memory.approved_policy_artifact_file_hash",
    )
    if _finite_float(entry.get("reward"), "reward_memory.reward") < MINIMUM_NDCG_DELTA:
        raise ValidationError("reward memory reward must meet minimum delta")
    if entry.get("reward_source") != "approved_policy_export":
        raise ValidationError("reward memory source must be approved_policy_export")
    if (
        entry.get("release_holdout_feedback_included") is not False
        or entry.get("release_evaluation_managed_externally") is not True
    ):
        raise ValidationError("reward memory must exclude external release feedback")
    _reject_release_feedback(entry, "reward_memory")


def build_live_canary_handoff(
    *,
    approved_policy_artifact_path: str | Path,
    manual_approval: Mapping[str, Any],
    rollback_sla_minutes: int,
) -> dict[str, Any]:
    """Build a manual live-canary handoff; never enables production by itself."""
    artifact = load_approved_policy_artifact_from_path(approved_policy_artifact_path)
    if not isinstance(manual_approval, Mapping):
        raise ValidationError("live canary manual_approval must be an object")
    approver = manual_approval.get("approved_by")
    if not isinstance(approver, str) or not approver.strip():
        raise ValidationError("live canary requires approved_by")
    approved_at = _parse_iso_datetime(
        manual_approval.get("approved_at"), "live_canary.approved_at"
    )
    artifact_created_at = _parse_iso_datetime(
        artifact.get("created_at"), "live_canary.artifact.created_at"
    )
    if approved_at < artifact_created_at:
        raise ValidationError("live canary manual approval is stale for this artifact")
    expires_at = _parse_iso_datetime(
        manual_approval.get("expires_at"), "live_canary.expires_at"
    )
    if expires_at <= approved_at:
        raise ValidationError(
            "live canary approval expires_at must be after approved_at"
        )
    if manual_approval.get("artifact_hash") != artifact.artifact_hash:
        raise ValidationError("live canary manual approval artifact_hash is stale")
    if (
        not isinstance(rollback_sla_minutes, int)
        or rollback_sla_minutes <= 0
        or rollback_sla_minutes > 60
    ):
        raise ValidationError("live canary rollback_sla_minutes must be 1..60")
    handoff = {
        "version": LIVE_CANARY_HANDOFF_VERSION,
        "created_at": _utc_now_iso(),
        "state": "manual_approval_required_before_enablement",
        "rollout_fraction": 0.0,
        "scope": V1_ALLOWED_SCOPE,
        "approved_policy_artifact_hash": artifact.artifact_hash,
        "artifact_created_at": artifact["created_at"],
        "runtime_policy_path": artifact["runtime_policy_path"],
        "approved_skill_hash": artifact["skill_hash"],
        "runtime_env": artifact["runtime_env"],
        "release_holdout_feedback_included": False,
        "release_evaluation_managed_externally": True,
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
        "release_holdout_feedback_included",
        "release_evaluation_managed_externally",
        "manual_approval",
        "rollback_sla_minutes",
        "rollback_to",
    }
    missing = required - set(handoff)
    if missing:
        raise ValidationError(
            f"live canary handoff missing required keys: {sorted(missing)}"
        )
    if set(handoff) != required:
        raise ValidationError("live canary handoff schema contains unsupported fields")
    if handoff.get("version") != LIVE_CANARY_HANDOFF_VERSION:
        raise ValidationError("live canary handoff version is invalid")
    if handoff.get("state") != "manual_approval_required_before_enablement":
        raise ValidationError(
            "live canary handoff must not enable rollout automatically"
        )
    if float(handoff.get("rollout_fraction")) != 0.0:
        raise ValidationError("live canary handoff rollout_fraction must remain 0.0")
    if handoff.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("live canary handoff scope is invalid")
    _require_iso_datetime(handoff.get("created_at"), "live_canary.created_at")
    _require_digest(
        handoff.get("approved_policy_artifact_hash"),
        "live_canary.approved_policy_artifact_hash",
    )
    artifact_created_at = _parse_iso_datetime(
        handoff.get("artifact_created_at"), "live_canary.artifact_created_at"
    )
    if (
        handoff.get("release_holdout_feedback_included") is not False
        or handoff.get("release_evaluation_managed_externally") is not True
    ):
        raise ValidationError("live canary must exclude external release feedback")
    manual = handoff.get("manual_approval")
    if not isinstance(manual, Mapping) or not manual.get("approved_by"):
        raise ValidationError("live canary handoff requires manual approval evidence")
    _require_exact_mapping(
        manual,
        {"approved_by", "approved_at", "expires_at", "artifact_hash"},
        "live canary manual_approval",
    )
    approved_at = _parse_iso_datetime(
        manual.get("approved_at"), "live_canary.manual_approval.approved_at"
    )
    expires_at = _parse_iso_datetime(
        manual.get("expires_at"), "live_canary.manual_approval.expires_at"
    )
    handoff_created_at = _parse_iso_datetime(
        handoff.get("created_at"), "live_canary.created_at"
    )
    if approved_at < artifact_created_at:
        raise ValidationError("live canary handoff approval is stale for artifact")
    if expires_at <= approved_at or expires_at <= handoff_created_at:
        raise ValidationError(
            "live canary handoff approval expiry must be after approval and handoff creation"
        )
    if manual.get("artifact_hash") != handoff.get("approved_policy_artifact_hash"):
        raise ValidationError("live canary handoff manual approval hash mismatch")
    sla = handoff.get("rollback_sla_minutes")
    if not isinstance(sla, int) or sla <= 0 or sla > 60:
        raise ValidationError("live canary handoff rollback_sla_minutes must be 1..60")
    rollback = handoff.get("rollback_to")
    env = handoff.get("runtime_env")
    if not isinstance(rollback, Mapping) or not isinstance(env, Mapping):
        raise ValidationError("live canary handoff requires rollback and runtime env")
    _require_exact_mapping(
        rollback, {"version", "skill_hash"}, "live canary rollback_to"
    )
    required_env = {
        "SKILLOPT_SEARCH_POLICY_ENABLED",
        "SKILLOPT_SEARCH_POLICY_PATH",
        "SKILLOPT_SEARCH_POLICY_HASH",
        "SKILLOPT_SEARCH_POLICY_SCOPE",
    }
    if set(env) != required_env:
        raise ValidationError(
            "live canary runtime_env must contain exactly the four rollout keys"
        )
    if env.get("SKILLOPT_SEARCH_POLICY_ENABLED") != "false":
        raise ValidationError(
            "live canary runtime_env must remain disabled at rollout fraction 0"
        )
    policy_path = env.get("SKILLOPT_SEARCH_POLICY_PATH")
    if not isinstance(policy_path, str) or not Path(policy_path).is_absolute():
        raise ValidationError("live canary runtime_env path must be absolute")
    _require_digest(
        env.get("SKILLOPT_SEARCH_POLICY_HASH"), "live_canary.runtime_env.policy_hash"
    )
    if policy_path != handoff.get("runtime_policy_path"):
        raise ValidationError(
            "live canary runtime_env path must match approved runtime_policy_path"
        )
    _require_digest(
        handoff.get("approved_skill_hash"), "live_canary.approved_skill_hash"
    )
    if env.get("SKILLOPT_SEARCH_POLICY_HASH") != handoff.get("approved_skill_hash"):
        raise ValidationError(
            "live canary runtime_env hash must match approved skill hash"
        )
    if env.get("SKILLOPT_SEARCH_POLICY_SCOPE") != V1_ALLOWED_SCOPE:
        raise ValidationError("live canary runtime_env scope is invalid")
    if rollback.get("skill_hash") == env.get("SKILLOPT_SEARCH_POLICY_HASH"):
        raise ValidationError(
            "live canary rollback target must differ from candidate policy"
        )
    _reject_release_feedback(handoff, "live_canary")


def run_continuous_optimization_iteration(
    *,
    run_id: str,
    output_root: str | Path,
    approved_policy_artifact_path: str | Path,
    baseline_eval: Mapping[str, Any],
    candidate_eval: Mapping[str, Any],
    dataset_path: str | Path,
    control_path: str | Path,
    baseline_skill_path: str | Path,
    reward_memory_path: str | Path,
    manual_approval: Mapping[str, Any] | None = None,
    rollback_sla_minutes: int | None = None,
) -> dict[str, Any]:
    """Run one safe continuous-optimization bookkeeping iteration.

    This function does not invoke SkillOpt training or change runtime policy. It
    materializes the post-approval operating artifacts for one already-approved
    candidate: decision record, reward-memory entry, next-iteration seed, and
    optional live-canary handoff. All outputs are written below the descriptor-
    leased ``output_root/run_id`` directory.
    """
    run_id = validate_optimizer_run_id(run_id)
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
    )
    next_seed = build_next_iteration_seed(decision)

    live_canary_handoff = None
    if manual_approval is not None or rollback_sla_minutes is not None:
        if manual_approval is None or rollback_sla_minutes is None:
            raise ValidationError(
                "live canary handoff requires both manual_approval and rollback_sla_minutes"
            )
        live_canary_handoff = build_live_canary_handoff(
            approved_policy_artifact_path=artifact_path,
            manual_approval=manual_approval,
            rollback_sla_minutes=rollback_sla_minutes,
        )
    reward_entry = _build_reward_memory_entry(
        decision,
        approved_policy_artifact_path=artifact_path,
    )
    memory_path = Path(reward_memory_path)
    existing = _locked_matching_reward_memory_entry(memory_path, reward_entry)
    if existing is not None:
        reward_entry["created_at"] = existing["created_at"]
    with _leased_output_run(output_root, run_id) as lease:
        output = lease.root_path / run_id
        decision_path = output / "optimizer_decision.json"
        next_seed_path = output / "next_iteration_seed.json"
        reward_entry_path = output / "reward_memory_entry.json"
        live_canary_handoff_path = (
            output / "live_canary_handoff.json"
            if live_canary_handoff is not None
            else None
        )
        summary_path = output / "continuous_iteration_summary.json"
        manifest_path = output / "continuous_iteration_manifest.json"
        transaction_path = output / "continuous_iteration_transaction.json"
        commit_path = output / "reward_memory_commit.json"

        request_hash = _mapping_hash(
            {
                "run_id": run_id,
                "approved_policy_artifact_file_hash": decision[
                    "approved_policy_artifact_file_hash"
                ],
                "baseline_eval_hash": _mapping_hash(baseline_eval),
                "candidate_eval_hash": _mapping_hash(candidate_eval),
                "dataset_file_hash": canonical_file_hash(dataset_path),
                "control_file_hash": canonical_file_hash(control_path),
                "baseline_skill_file_hash": canonical_file_hash(baseline_skill_path),
                "reward_memory_path": str(memory_path.absolute()),
                "manual_approval_hash": _mapping_hash(manual_approval)
                if manual_approval is not None
                else None,
                "rollback_sla_minutes": rollback_sla_minutes,
            }
        )
        transaction = None
        if lease.created:
            timestamps = {
                "decision": decision["created_at"],
                "next_seed": next_seed["created_at"],
                "reward_entry": reward_entry["created_at"],
                "live_canary_handoff": live_canary_handoff["created_at"]
                if live_canary_handoff is not None
                else None,
                "manifest": _utc_now_iso(),
                "summary": _utc_now_iso(),
                "commit": _utc_now_iso(),
            }
        else:
            transaction = _read_output_json(lease, transaction_path.name)
            _validate_optimizer_transaction(
                transaction,
                run_id=run_id,
                request_hash=request_hash,
                live_canary_present=live_canary_handoff is not None,
            )
            timestamps = dict(transaction["timestamps"])

        decision_record = decision.persisted_record()
        decision_record["created_at"] = timestamps["decision"]
        decision = ValidatedOptimizerDecisionRecord(
            _record=decision_record,
            approval_receipt=decision.approval_receipt,
        )
        next_seed["created_at"] = timestamps["next_seed"]
        reward_entry["created_at"] = timestamps["reward_entry"]
        if live_canary_handoff is not None:
            live_canary_handoff["created_at"] = timestamps["live_canary_handoff"]

        staged_values = {
            decision_path.name: decision_record,
            next_seed_path.name: next_seed,
            **(
                {live_canary_handoff_path.name: live_canary_handoff}
                if live_canary_handoff_path is not None
                else {}
            ),
            reward_entry_path.name: reward_entry,
        }
        staged_hashes = {
            name: _json_value_hash(value) for name, value in staged_values.items()
        }
        manifest = {
            "version": CONTINUOUS_MANIFEST_VERSION,
            "run_id": decision["run_id"],
            "created_at": timestamps["manifest"],
            "scope": V1_ALLOWED_SCOPE,
            "approved_policy_artifact_file_hash": decision[
                "approved_policy_artifact_file_hash"
            ],
            "decision_record_path": str(decision_path),
            "decision_record_hash": staged_hashes[decision_path.name],
            "reward_memory_path": str(memory_path),
            "reward_memory_entry_path": str(reward_entry_path),
            "reward_memory_entry_hash": staged_hashes[reward_entry_path.name],
            "next_iteration_seed_path": str(next_seed_path),
            "next_iteration_seed_hash": staged_hashes[next_seed_path.name],
            "live_canary_handoff_path": str(live_canary_handoff_path)
            if live_canary_handoff_path
            else None,
            "live_canary_handoff_hash": staged_hashes.get("live_canary_handoff.json"),
            "summary_path": None,
            "summary_hash": None,
            "status": "complete",
        }
        summary = _continuous_iteration_summary_value(
            manifest=manifest,
            decision=decision,
            reward_entry=reward_entry,
            next_iteration_seed=next_seed,
            live_canary_handoff=live_canary_handoff,
            created_at=timestamps["summary"],
        )
        summary_hash = _json_value_hash(summary)
        manifest["summary_path"] = str(summary_path)
        manifest["summary_hash"] = summary_hash
        terminal_hashes = {
            summary_path.name: summary_hash,
            manifest_path.name: _json_value_hash(manifest),
        }
        artifact_order = list(staged_values) + [summary_path.name, manifest_path.name]
        if transaction is None:
            transaction = {
                "version": CONTINUOUS_TRANSACTION_VERSION,
                "run_id": run_id,
                "state": "prepared",
                "created_at": _utc_now_iso(),
                "request_hash": request_hash,
                "reward_memory_path": str(memory_path.absolute()),
                "live_canary_present": live_canary_handoff is not None,
                "timestamps": timestamps,
                "artifact_order": artifact_order,
                "artifact_hashes": {**staged_hashes, **terminal_hashes},
            }
            _write_output_json(lease, transaction_path.name, transaction)
        elif transaction["artifact_hashes"] != {**staged_hashes, **terminal_hashes}:
            mismatched = sorted(
                name
                for name, digest in {**staged_hashes, **terminal_hashes}.items()
                if transaction["artifact_hashes"].get(name) != digest
            )
            raise ValidationError(
                f"optimizer recovery artifact bytes mismatch: {mismatched}"
            )

        _inspect_optimizer_recovery_directory(lease, transaction)
        for name, value in staged_values.items():
            _write_or_verify_output_json(lease, name, value)

        committed_reward_entry = _append_reward_memory_entry_value(
            memory_path, reward_entry
        )
        if committed_reward_entry != reward_entry:
            raise ValidationError("reward memory committed entry changed staged value")
        if _locked_matching_reward_memory_entry(memory_path, reward_entry) != reward_entry:
            raise ValidationError("optimizer reward commit could not be verified")
        commit = {
            "version": CONTINUOUS_REWARD_COMMIT_VERSION,
            "run_id": run_id,
            "created_at": timestamps["commit"],
            "transaction_hash": _json_value_hash(transaction),
            "reward_memory_entry_hash": staged_hashes[reward_entry_path.name],
            "reward_memory_path": str(memory_path.absolute()),
        }
        _write_or_verify_output_json(lease, commit_path.name, commit)
        _write_or_verify_output_json(lease, summary_path.name, summary)
        validate_continuous_iteration_manifest(manifest)
        _write_or_verify_output_json(lease, manifest_path.name, manifest)
        _verify_output_lease(lease)
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
    summary = _continuous_iteration_summary_value(
        manifest=manifest,
        decision=decision,
        reward_entry=reward_entry,
        next_iteration_seed=next_iteration_seed,
        live_canary_handoff=live_canary_handoff,
        created_at=_utc_now_iso(),
    )
    validate_continuous_iteration_summary(summary)
    return summary


def _continuous_iteration_summary_value(
    *,
    manifest: Mapping[str, Any],
    decision: Mapping[str, Any],
    reward_entry: Mapping[str, Any],
    next_iteration_seed: Mapping[str, Any],
    live_canary_handoff: Mapping[str, Any] | None,
    created_at: str,
) -> dict[str, Any]:
    return {
        "version": CONTINUOUS_SUMMARY_VERSION,
        "created_at": created_at,
        "run_id": decision["run_id"],
        "status": "complete",
        "scope": V1_ALLOWED_SCOPE,
        "reward": decision["reward"],
        "candidate_skill_hash": decision["candidate_skill_hash"],
        "baseline_hash": decision["baseline_hash"],
        "approved_policy_artifact_file_hash": decision[
            "approved_policy_artifact_file_hash"
        ],
        "release_holdout_feedback_included": False,
        "release_evaluation_managed_externally": True,
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
        },
        "live_canary": _summary_live_canary(live_canary_handoff),
    }


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
        "release_holdout_feedback_included",
        "release_evaluation_managed_externally",
        "manifest_hashes",
        "reward_memory",
        "next_iteration",
        "live_canary",
    }
    missing = required - set(summary)
    if missing:
        raise ValidationError(
            f"continuous iteration summary missing required keys: {sorted(missing)}"
        )
    if set(summary) != required:
        raise ValidationError(
            "continuous iteration summary contains unsupported fields"
        )
    if summary.get("version") != CONTINUOUS_SUMMARY_VERSION:
        raise ValidationError("continuous iteration summary version is invalid")
    if summary.get("status") != "complete" or summary.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("continuous iteration summary status/scope is invalid")
    _require_iso_datetime(
        summary.get("created_at"), "continuous_iteration_summary.created_at"
    )
    _require_digest(
        summary.get("candidate_skill_hash"),
        "continuous_iteration_summary.candidate_skill_hash",
    )
    _require_digest(
        summary.get("baseline_hash"), "continuous_iteration_summary.baseline_hash"
    )
    _require_digest(
        summary.get("approved_policy_artifact_file_hash"),
        "continuous_iteration_summary.approved_policy_artifact_file_hash",
    )
    hashes = summary.get("manifest_hashes")
    if not isinstance(hashes, Mapping):
        raise ValidationError(
            "continuous iteration summary manifest_hashes must be an object"
        )
    _require_exact_mapping(
        hashes,
        {
            "decision_record_hash",
            "reward_memory_entry_hash",
            "next_iteration_seed_hash",
            "live_canary_handoff_hash",
        },
        "continuous iteration summary manifest_hashes",
    )
    for field in (
        "decision_record_hash",
        "reward_memory_entry_hash",
        "next_iteration_seed_hash",
    ):
        _require_digest(hashes.get(field), f"continuous_iteration_summary.{field}")
    handoff_hash = hashes.get("live_canary_handoff_hash")
    if handoff_hash is not None:
        _require_digest(
            handoff_hash, "continuous_iteration_summary.live_canary_handoff_hash"
        )
    reward_memory = summary.get("reward_memory")
    if (
        not isinstance(reward_memory, Mapping)
        or reward_memory.get("appended") is not True
    ):
        raise ValidationError(
            "continuous iteration summary reward_memory must show appended=true"
        )
    _require_exact_mapping(
        reward_memory,
        {"appended", "path", "entry_hash"},
        "continuous iteration summary reward_memory",
    )
    _require_digest(
        reward_memory.get("entry_hash"),
        "continuous_iteration_summary.reward_memory.entry_hash",
    )
    next_iteration = summary.get("next_iteration")
    if not isinstance(next_iteration, Mapping):
        raise ValidationError(
            "continuous iteration summary next_iteration must be an object"
        )
    _require_digest(
        next_iteration.get("baseline_hash"),
        "continuous_iteration_summary.next_iteration.baseline_hash",
    )
    if set(next_iteration) != {"baseline_hash"}:
        raise ValidationError(
            "continuous iteration summary next_iteration schema is invalid"
        )
    live_canary = summary.get("live_canary")
    if not isinstance(live_canary, Mapping):
        raise ValidationError(
            "continuous iteration summary live_canary must be an object"
        )
    if live_canary.get("present") is False:
        _require_exact_mapping(
            live_canary, {"present"}, "continuous iteration summary live_canary"
        )
    elif live_canary.get("present") is True:
        _require_exact_mapping(
            live_canary,
            {
                "present",
                "state",
                "rollout_fraction",
                "approved_by",
                "approved_at",
                "expires_at",
                "rollback_sla_minutes",
                "approved_policy_artifact_hash",
            },
            "continuous iteration summary live_canary",
        )
        _require_digest(
            live_canary.get("approved_policy_artifact_hash"),
            "continuous_iteration_summary.live_canary.approved_policy_artifact_hash",
        )
    else:
        raise ValidationError(
            "continuous iteration summary live_canary present flag is invalid"
        )
    if (
        live_canary.get("present") is True
        and live_canary.get("rollout_fraction") != 0.0
    ):
        raise ValidationError(
            "continuous iteration summary live canary rollout must remain 0.0"
        )
    if (
        summary.get("release_holdout_feedback_included") is not False
        or summary.get("release_evaluation_managed_externally") is not True
    ):
        raise ValidationError(
            "continuous iteration summary must exclude release feedback"
        )
    _reject_release_feedback(summary, "continuous_iteration_summary")


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
        raise ValidationError(
            f"continuous iteration manifest missing required keys: {sorted(missing)}"
        )
    if set(manifest) != required:
        raise ValidationError(
            "continuous iteration manifest contains unsupported fields"
        )
    if manifest.get("version") != CONTINUOUS_MANIFEST_VERSION:
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
    _require_existing_file_hash(
        manifest.get("decision_record_path"),
        manifest.get("decision_record_hash"),
        "decision_record",
    )
    _require_existing_file_hash(
        manifest.get("reward_memory_entry_path"),
        manifest.get("reward_memory_entry_hash"),
        "reward_memory_entry",
    )
    _require_existing_file_hash(
        manifest.get("next_iteration_seed_path"),
        manifest.get("next_iteration_seed_hash"),
        "next_iteration_seed",
    )
    summary_path = manifest.get("summary_path")
    summary_hash = manifest.get("summary_hash")
    if summary_path is not None:
        _require_existing_file_hash(summary_path, summary_hash, "summary")
    elif summary_hash is not None:
        raise ValidationError(
            "continuous iteration summary hash must be null when summary path is null"
        )
    handoff_path = manifest.get("live_canary_handoff_path")
    handoff_hash = manifest.get("live_canary_handoff_hash")
    if handoff_path is None:
        if handoff_hash is not None:
            raise ValidationError(
                "continuous iteration handoff hash must be null when handoff path is null"
            )
    else:
        if not isinstance(handoff_path, str) or not handoff_path:
            raise ValidationError("continuous iteration handoff path is invalid")
        _require_digest(handoff_hash, "continuous_iteration.live_canary_handoff_hash")
        _require_existing_file_hash(handoff_path, handoff_hash, "live_canary_handoff")
    _reject_release_feedback(manifest, "continuous_iteration_manifest")


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


def _matching_reward_memory_entry(
    memory_text: str, *, entry: Mapping[str, Any]
) -> dict[str, Any] | None:
    expected = dict(entry)
    matched: dict[str, Any] | None = None
    for line_number, line in enumerate(memory_text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                f"reward memory contains invalid JSON at line {line_number}"
            ) from exc
        same_run = row.get("run_id") == entry.get("run_id")
        same_artifact = row.get("approved_policy_artifact_file_hash") == entry.get(
            "approved_policy_artifact_file_hash"
        )
        if same_run or same_artifact:
            validate_reward_memory_entry(row)
            stable_row = {
                key: value for key, value in row.items() if key != "created_at"
            }
            stable_expected = {
                key: value for key, value in expected.items() if key != "created_at"
            }
            if stable_row == stable_expected:
                if matched is not None:
                    raise ValidationError(
                        "reward memory contains duplicate matching run entries"
                    )
                matched = deepcopy(row)
                continue
            if same_run:
                raise ValidationError("reward memory duplicate run_id conflict")
            raise ValidationError("reward memory duplicate approved artifact conflict")
    return matched


def _locked_matching_reward_memory_entry(
    path: Path, entry: Mapping[str, Any]
) -> dict[str, Any] | None:
    with FileLock(str(path) + ".lock"):
        memory_text = path.read_text(encoding="utf-8") if path.exists() else ""
        return _matching_reward_memory_entry(memory_text, entry=entry)


def _json_payload(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _json_value_hash(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_json_payload(value)).hexdigest()


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(value)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def validate_optimizer_run_id(run_id: Any) -> str:
    """Return a path-opaque ASCII run identifier or fail closed."""
    if not isinstance(run_id, str):
        raise ValidationError("optimizer run_id must be a string")
    if not run_id or len(run_id) > MAX_RUN_ID_LENGTH:
        raise ValidationError("optimizer run_id length is invalid")
    if unicodedata.normalize("NFKC", run_id) != run_id:
        raise ValidationError("optimizer run_id normalization is invalid")
    if run_id in {".", ".."} or _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValidationError("optimizer run_id must be an opaque ASCII identifier")
    return run_id


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _absolute_output_root(value: str | Path) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValidationError("optimizer output_root is invalid")
    if any(part in {".", ".."} for part in raw.split("/")):
        raise ValidationError("optimizer output_root must not contain dot traversal")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if candidate == Path(candidate.anchor):
        raise ValidationError("optimizer output_root must not be a filesystem root")
    return candidate


@contextmanager
def _leased_output_run(output_root: str | Path, run_id: str):
    root_path = _absolute_output_root(output_root)
    current_fd = os.open("/", _directory_flags())
    held_fds = [current_fd]
    chain: list[tuple[str, os.stat_result]] = []
    try:
        for component in root_path.parts[1:]:
            try:
                os.mkdir(component, 0o700, dir_fd=current_fd)
            except FileExistsError:
                pass
            try:
                next_fd = os.open(component, _directory_flags(), dir_fd=current_fd)
            except OSError as exc:
                raise ValidationError(
                    "optimizer output_root must be a real no-symlink directory"
                ) from exc
            held_fds.append(next_fd)
            chain.append((component, os.fstat(next_fd)))
            current_fd = next_fd
        created = False
        try:
            os.mkdir(run_id, 0o700, dir_fd=current_fd)
            created = True
        except FileExistsError:
            pass
        try:
            run_fd = os.open(run_id, _directory_flags(), dir_fd=current_fd)
        except OSError as exc:
            raise ValidationError("optimizer run directory is unsafe") from exc
        held_fds.append(run_fd)
        fcntl.flock(run_fd, fcntl.LOCK_EX)
        run_stat = os.fstat(run_fd)
        named_run = os.stat(run_id, dir_fd=current_fd, follow_symlinks=False)
        if not stat.S_ISDIR(named_run.st_mode) or not _same_inode(run_stat, named_run):
            raise ValidationError("optimizer run directory lease mismatch")
        lease = _OutputLease(
            root_path, current_fd, run_id, run_fd, tuple(chain), run_stat, {}, created
        )
        _verify_output_lease(lease)
        try:
            yield lease
        except BaseException:
            if created:
                try:
                    if not os.listdir(run_fd):
                        os.rmdir(run_id, dir_fd=current_fd)
                except OSError:
                    pass
            raise
    finally:
        for descriptor in reversed(held_fds):
            os.close(descriptor)


def _verify_output_lease(lease: _OutputLease) -> None:
    current = os.open("/", _directory_flags())
    try:
        for component, expected in lease.chain:
            following = os.open(component, _directory_flags(), dir_fd=current)
            os.close(current)
            current = following
            if not _same_inode(os.fstat(current), expected):
                raise ValidationError("optimizer output_root changed during iteration")
        if not _same_inode(os.fstat(current), os.fstat(lease.root_fd)):
            raise ValidationError("optimizer output_root lease changed")
        named_run = os.stat(lease.run_id, dir_fd=current, follow_symlinks=False)
        if not stat.S_ISDIR(named_run.st_mode) or not _same_inode(
            named_run, lease.run_stat
        ):
            raise ValidationError("optimizer run directory changed during iteration")
        for name, expected in lease.artifacts.items():
            named = os.stat(name, dir_fd=lease.run_fd, follow_symlinks=False)
            if not stat.S_ISREG(named.st_mode) or not _same_inode(named, expected):
                raise ValidationError(
                    "optimizer output artifact changed during iteration"
                )
    except OSError as exc:
        raise ValidationError("optimizer output lease is no longer contained") from exc
    finally:
        os.close(current)


def _write_output_json(lease: _OutputLease, name: str, value: Mapping[str, Any]) -> str:
    payload = _json_payload(value)
    _exclusive_atomic_write_at(lease, name, payload)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _write_or_verify_output_json(
    lease: _OutputLease, name: str, value: Mapping[str, Any]
) -> str:
    expected_hash = _json_value_hash(value)
    try:
        existing = os.stat(name, dir_fd=lease.run_fd, follow_symlinks=False)
    except FileNotFoundError:
        return _write_output_json(lease, name, value)
    if not stat.S_ISREG(existing.st_mode):
        raise ValidationError("optimizer recovery artifact is not a regular file")
    payload = _read_output_bytes(lease, name)
    if "sha256:" + hashlib.sha256(payload).hexdigest() != expected_hash:
        raise ValidationError("optimizer recovery artifact bytes mismatch")
    lease.artifacts[name] = existing
    _verify_output_lease(lease)
    return expected_hash


def _read_output_bytes(lease: _OutputLease, name: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=lease.run_fd)
    except OSError as exc:
        raise ValidationError("optimizer recovery artifact is unsafe or missing") from exc
    try:
        opened = os.fstat(fd)
        named = os.stat(name, dir_fd=lease.run_fd, follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode) or not _same_inode(opened, named):
            raise ValidationError("optimizer recovery artifact lease mismatch")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        if not _same_inode(opened, os.fstat(fd)):
            raise ValidationError("optimizer recovery artifact changed while reading")
        lease.artifacts[name] = opened
        _verify_output_lease(lease)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _read_output_json(lease: _OutputLease, name: str) -> dict[str, Any]:
    try:
        value = json.loads(_read_output_bytes(lease, name).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("optimizer recovery artifact is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError("optimizer recovery artifact must be an object")
    return value


def _validate_optimizer_transaction(
    transaction: Mapping[str, Any],
    *,
    run_id: str,
    request_hash: str,
    live_canary_present: bool,
) -> None:
    required = {
        "version",
        "run_id",
        "state",
        "created_at",
        "request_hash",
        "reward_memory_path",
        "live_canary_present",
        "timestamps",
        "artifact_order",
        "artifact_hashes",
    }
    if set(transaction) != required:
        raise ValidationError("optimizer recovery transaction schema is invalid")
    if (
        transaction.get("version") != CONTINUOUS_TRANSACTION_VERSION
        or transaction.get("state") != "prepared"
        or transaction.get("run_id") != run_id
        or transaction.get("request_hash") != request_hash
        or transaction.get("live_canary_present") is not live_canary_present
    ):
        raise ValidationError("optimizer recovery transaction does not match retry")
    _require_iso_datetime(transaction.get("created_at"), "optimizer_transaction.created_at")
    timestamps = transaction.get("timestamps")
    if not isinstance(timestamps, Mapping) or set(timestamps) != {
        "decision",
        "next_seed",
        "reward_entry",
        "live_canary_handoff",
        "manifest",
        "summary",
        "commit",
    }:
        raise ValidationError("optimizer recovery timestamps schema is invalid")
    for key, value in timestamps.items():
        if key == "live_canary_handoff" and not live_canary_present:
            if value is not None:
                raise ValidationError("optimizer recovery canary timestamp is invalid")
        else:
            _require_iso_datetime(value, f"optimizer_transaction.timestamps.{key}")
    artifact_order = transaction.get("artifact_order")
    artifact_hashes = transaction.get("artifact_hashes")
    if not isinstance(artifact_order, list) or not isinstance(artifact_hashes, Mapping):
        raise ValidationError("optimizer recovery artifact journal is invalid")
    if set(artifact_order) != set(artifact_hashes) or len(artifact_order) != len(
        set(artifact_order)
    ):
        raise ValidationError("optimizer recovery artifact journal is inconsistent")
    for name, digest in artifact_hashes.items():
        if not isinstance(name, str) or "/" in name or "\\" in name:
            raise ValidationError("optimizer recovery artifact name is invalid")
        _require_digest(digest, f"optimizer_transaction.artifact_hashes.{name}")


def _inspect_optimizer_recovery_directory(
    lease: _OutputLease, transaction: Mapping[str, Any]
) -> None:
    transaction_name = "continuous_iteration_transaction.json"
    commit_name = "reward_memory_commit.json"
    expected_order = list(transaction["artifact_order"])
    allowed = {transaction_name, commit_name, *expected_order}
    present = set(os.listdir(lease.run_fd))
    unexpected = present - allowed
    if unexpected:
        raise ValidationError(
            f"optimizer recovery directory contains unexpected artifacts: {sorted(unexpected)}"
        )
    if transaction_name not in present:
        raise ValidationError("optimizer recovery transaction journal is missing")
    for name in present:
        named = os.stat(name, dir_fd=lease.run_fd, follow_symlinks=False)
        if not stat.S_ISREG(named.st_mode):
            raise ValidationError("optimizer recovery directory contains unsafe artifact")
    staged_order = expected_order[:-2]
    staged_present = [name for name in staged_order if name in present]
    if staged_present != staged_order[: len(staged_present)]:
        raise ValidationError("optimizer recovery staged artifact prefix is inconsistent")
    summary_name, manifest_name = expected_order[-2:]
    if commit_name in present and len(staged_present) != len(staged_order):
        raise ValidationError("optimizer recovery commit precedes staged artifacts")
    if summary_name in present and commit_name not in present:
        raise ValidationError("optimizer recovery summary precedes reward commit")
    if manifest_name in present and summary_name not in present:
        raise ValidationError("optimizer recovery manifest precedes summary")
    for name in present & set(expected_order):
        payload_hash = "sha256:" + hashlib.sha256(
            _read_output_bytes(lease, name)
        ).hexdigest()
        if payload_hash != transaction["artifact_hashes"][name]:
            raise ValidationError("optimizer recovery artifact bytes mismatch")


def _exclusive_atomic_write_at(lease: _OutputLease, name: str, payload: bytes) -> None:
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise ValidationError("optimizer artifact name is invalid")
    _verify_output_lease(lease)
    temporary = f".{name}.{os.getpid()}.{len(lease.artifacts)}.tmp"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    fd = -1
    try:
        fd = os.open(temporary, flags, 0o600, dir_fd=lease.run_fd)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(
            temporary,
            name,
            src_dir_fd=lease.run_fd,
            dst_dir_fd=lease.run_fd,
            follow_symlinks=False,
        )
        os.unlink(temporary, dir_fd=lease.run_fd)
        published = os.stat(name, dir_fd=lease.run_fd, follow_symlinks=False)
        if not stat.S_ISREG(published.st_mode):
            raise ValidationError("optimizer output artifact is not a regular file")
        lease.artifacts[name] = published
        os.fsync(lease.run_fd)
        _verify_output_lease(lease)
    except FileExistsError as exc:
        raise ValidationError("optimizer output artifact already exists") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=lease.run_fd)
        except FileNotFoundError:
            pass


def _require_existing_file_hash(
    path_value: Any, expected_hash: Any, field: str
) -> None:
    if not isinstance(path_value, str) or not path_value:
        raise ValidationError(f"continuous iteration {field} path is required")
    _require_digest(expected_hash, f"continuous_iteration.{field}_hash")
    path = Path(path_value)
    if not path.is_file():
        raise ValidationError(f"continuous iteration {field} file is missing")
    if canonical_file_hash(path) != expected_hash:
        raise ValidationError(f"continuous iteration {field} hash mismatch")


_FORBIDDEN_OPTIMIZER_KEY_FRAGMENTS = {
    "capability",
    "contract",
    "detail",
    "document",
    "docs",
    "evaluator",
    "generation",
    "holdout",
    "label",
    "metric",
    "perquery",
    "policy",
    "prompt",
    "query",
    "ranking",
    "reflection",
    "release",
    "secret",
    "threshold",
}

# These keys are deliberately narrow, non-feedback anchors or negative safety
# assertions.  They contain otherwise forbidden words but do not reveal release
# evaluation or policy contents.
_SAFE_OPTIMIZER_KEYS = {
    "approvedpolicyartifacthash",
    "approvedpolicyartifactfilehash",
    "runtimepolicypath",
    "releaseholdoutfeedbackincluded",
    "releaseevaluationmanagedexternally",
    "skilloptsearchpolicyenabled",
    "skilloptsearchpolicyhash",
    "skilloptsearchpolicypath",
    "skilloptsearchpolicyscope",
}


def _reject_release_feedback(value: Any, field: str) -> None:
    """Reject release-authority feedback accidentally copied into optimizer state."""
    if isinstance(value, Mapping):
        forbidden: list[str] = []
        for key in value:
            if not isinstance(key, str):
                forbidden.append(repr(key))
                continue
            canonical = _canonical_key(key)
            if canonical in _SAFE_OPTIMIZER_KEYS:
                continue
            if any(
                fragment in canonical for fragment in _FORBIDDEN_OPTIMIZER_KEY_FRAGMENTS
            ):
                forbidden.append(key)
        if forbidden:
            raise ValidationError(
                f"{field} contains forbidden release feedback keys: {sorted(forbidden)}"
            )
        for key, nested in value.items():
            _reject_release_feedback(nested, f"{field}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_release_feedback(nested, f"{field}[{index}]")


def _canonical_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _require_exact_mapping(
    value: Mapping[str, Any], required: set[str], field: str
) -> None:
    if set(value) != required:
        raise ValidationError(f"{field} schema is invalid")


def _mapping_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _artifact_hash(artifact: Mapping[str, Any]) -> str:
    schema_artifact = {
        key: value
        for key, value in artifact.items()
        if key not in {"artifact_path", "runtime_env_path"}
    }
    payload = json.dumps(
        schema_artifact, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _approval_receipt(
    approved: ValidatedApprovedSkillOptPolicy,
) -> ValidatedApprovalReceipt:
    rollback = approved["rollback_to"]
    runtime_env = approved["runtime_env"]
    return ValidatedApprovalReceipt(
        artifact_path=approved.artifact_path,
        artifact_schema_hash=_artifact_hash(approved),
        artifact_file_hash=approved.artifact_hash,
        skill_hash=str(approved["skill_hash"]),
        baseline_hash=str(approved["baseline_hash"]),
        dataset_hash=str(approved["dataset_hash"]),
        execution_control_hash=str(approved["execution_control_hash"]),
        rollback_version=str(rollback["version"]),
        rollback_skill_hash=str(rollback["skill_hash"]),
        runtime_default_off=(
            runtime_env.get("SKILLOPT_SEARCH_POLICY_ENABLED") == "false"
            and approved.get("authorization_status") == "not_authorized"
        ),
    )


def _fresh_approved_policy(
    value: ValidatedApprovedSkillOptPolicy | Mapping[str, Any],
) -> ValidatedApprovedSkillOptPolicy:
    if not isinstance(value, ValidatedApprovedSkillOptPolicy):
        raise ValidationError(
            "consumer requires a fully revalidated approved SkillOpt policy object; raw mappings are rejected"
        )
    fresh = load_approved_policy_artifact_from_path(value.artifact_path)
    if fresh.artifact_hash != value.artifact_hash:
        raise ValidationError("validated approved policy changed before consumer use")
    return fresh


def _fresh_approved_policy_from_receipt(
    receipt: ValidatedApprovalReceipt,
) -> ValidatedApprovedSkillOptPolicy:
    if not isinstance(receipt, ValidatedApprovalReceipt):
        raise ValidationError("optimizer approval receipt type is invalid")
    fresh = load_approved_policy_artifact_from_path(receipt.artifact_path)
    expected = _approval_receipt(fresh)
    if expected != receipt:
        raise ValidationError("optimizer approval receipt changed before consumer use")
    if receipt.runtime_default_off is not True:
        raise ValidationError("optimizer approval receipt must remain default-off")
    return fresh


def _validate_decision_matches_approved_policy(
    decision: Mapping[str, Any],
    approved: ValidatedApprovedSkillOptPolicy,
) -> None:
    expected = {
        "candidate_skill_hash": approved["skill_hash"],
        "baseline_hash": approved["baseline_hash"],
        "dataset_hash": approved["dataset_hash"],
        "execution_control_hash": approved["execution_control_hash"],
        "approved_policy_artifact_hash": _artifact_hash(approved),
        "approved_policy_artifact_file_hash": approved.artifact_hash,
        "rollback_to": approved["rollback_to"],
    }
    for field, expected_value in expected.items():
        if decision.get(field) != expected_value:
            raise ValidationError(
                f"optimizer decision {field} does not match fully revalidated approval"
            )


def _finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValidationError(f"{field} must be finite")
    return number


def _require_digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
    ):
        raise ValidationError(f"{field} must be a sha256 digest")
    suffix = value[len("sha256:") :]
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
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
