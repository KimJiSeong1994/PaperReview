"""Exact temporary fixtures for the authoritative sealed SkillOpt boundary."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.search_eval.orchestrator import run_orchestrator
from src.search_eval.skillopt_compatibility import (
    APPROVED_ARCHIVE_SHA256,
    APPROVED_PEELED_COMMIT,
    APPROVED_TREE_GIT_SHA1,
    CANONICAL_RENDERED_CONFIG_BYTES,
    CANDIDATE_PATH,
    EVAL_ARGV,
    EVAL_OUT_ROOT,
    PROFILE_ID,
    SOURCE_IMMUTABLE_OBJECT_VERSION,
    TRAIN_ARGV,
    TRAIN_OUT_ROOT,
    domain_separated_hash,
    seal_identity_artifact,
)
from src.search_eval.skillopt_contract import V1_ALLOWED_SCOPE
from src.search_eval.skillopt_run_contract import (
    ACL_SNAPSHOT_VERSION,
    AUTHORITY_CONTEXT_ENV,
    AUTHORITY_CONTEXT_VERSION,
    AUTHORITY_POLICY_VERSION,
    COMPATIBILITY_REPORT_VERSION,
    PRIVACY_RECEIPT_VERSION,
    RUN_REQUEST_VERSION,
    RUN_RESULT_VERSION,
    STORE_RECEIPT_VERSION,
    USAGE_RECEIPT_VERSION,
    canonical_json_bytes,
    seal_run_request,
    seal_run_result,
)
from tests.test_skillopt_compatibility import (
    _reseal_profile,
    _structurally_resolved_profile,
)


_FIXTURE_NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _timestamp(delta: timedelta) -> str:
    return (_FIXTURE_NOW + delta).isoformat().replace("+00:00", "Z")


CREATED_AT = _timestamp(timedelta(minutes=-5))
COMPLETED_AT = _timestamp(timedelta(minutes=-1))
ISSUED_AT = _timestamp(timedelta(hours=-1))
EXPIRES_AT = _timestamp(timedelta(hours=23))
ISSUER = "skillopt-build-workload"
VERIFIER = "paper-review-agent"
STORE = "fixture-immutable-store"
COORDINATOR = "paper-review-agent-coordinator"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATASET_PATH = _REPO_ROOT / "data/search_eval/skillopt_paper_search_v0.json"
_CONTROL_PATH = _REPO_ROOT / "data/search_eval/skillopt_execution_control_v0.json"


def _seal(value: dict[str, Any], version: str) -> dict[str, Any]:
    return seal_identity_artifact(value, version)


def _write(path: Path, payload: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload.encode("utf-8") if isinstance(payload, str) else payload)


def _write_json(path: Path, value: Any) -> None:
    _write(path, canonical_json_bytes(value))


def _canonical_json_file(path: Path) -> bytes:
    return canonical_json_bytes(json.loads(path.read_bytes()))


def _entry(root: Path, relative: str) -> dict[str, Any]:
    payload = (root / relative).read_bytes()
    return {
        "path": relative,
        "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def _authority_evidence(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = copy.deepcopy(_structurally_resolved_profile())
    acl = _seal(
        {
            "version": ACL_SNAPSHOT_VERSION,
            "store_id": STORE,
            "issuer_workload": ISSUER,
            "verifier_id": VERIFIER,
            "coordinator_id": COORDINATOR,
            "principals": sorted([COORDINATOR, VERIFIER]),
            "object_versions": {
                "source": SOURCE_IMMUTABLE_OBJECT_VERSION,
                "overlay": profile["overlay_manifest"]["immutable_object_version"],
            },
            "issued_at": ISSUED_AT,
            "expires_at": EXPIRES_AT,
            "immutable": True,
        },
        ACL_SNAPSHOT_VERSION,
    )
    acl_bytes = canonical_json_bytes(acl)
    custody = copy.deepcopy(profile["custody_evidence"])
    custody["acl_snapshot_sha256"] = hashlib.sha256(acl_bytes).hexdigest()
    custody["issued_at"] = ISSUED_AT
    custody["expires_at"] = EXPIRES_AT
    custody = _seal(custody, custody["version"])
    profile["custody_evidence"] = custody
    profile = _reseal_profile(profile)

    staging = profile["staging_manifest"]
    report = _seal(
        {
            "version": COMPATIBILITY_REPORT_VERSION,
            "profile_id": PROFILE_ID,
            "status": "passed",
            "evidence_class": "wave1_2_compatibility",
            "authorization_status": "authorized_for_sealed_import",
            "authenticity_status": "same_domain_verified",
            "seal_kind": "acl_immutable_store",
            "trusted": True,
            "pristine_source_identity": profile["pristine_source_manifest"]["identity"],
            "overlay_identity": profile["overlay_manifest"]["identity"],
            "staging_identity": staging["identity"],
            "runner_identity": profile["runner_identity"]["identity"],
            "custody_identity": custody["identity"],
            "execution_config_identity": staging["execution_config_identity"],
            "train_argv_identity": staging["execution_config"]["train_argv_identity"],
            "eval_argv_identity": staging["execution_config"]["eval_argv_identity"],
            "imported_modules": staging["expected_imported_modules"],
            "outputs": profile["outputs"],
            "provider_count": 0,
            "network_count": 0,
            "subprocess_count": 0,
        },
        COMPATIBILITY_REPORT_VERSION,
    )
    profile["tested_patch"]["report_identity"] = report["identity"]
    profile = _reseal_profile(profile)
    store = _seal(
        {
            "version": STORE_RECEIPT_VERSION,
            "store_id": STORE,
            "issuer_workload": ISSUER,
            "verifier_id": VERIFIER,
            "subject_runner_identity": profile["runner_identity"]["identity"],
            "source_immutable_object_version": SOURCE_IMMUTABLE_OBJECT_VERSION,
            "overlay_immutable_object_version": profile["overlay_manifest"][
                "immutable_object_version"
            ],
            "acl_snapshot_sha256": hashlib.sha256(acl_bytes).hexdigest(),
            "object_versions": {
                "source": profile["pristine_source_manifest"]["identity"],
                "overlay": profile["overlay_manifest"]["identity"],
                "staging": profile["staging_manifest"]["identity"],
                "runner": profile["runner_identity"]["identity"],
                "custody": profile["custody_evidence"]["identity"],
            },
            "retention_mode": "governance-compliance",
            "issued_at": ISSUED_AT,
            "expires_at": EXPIRES_AT,
            "immutable": True,
            "verified": True,
        },
        STORE_RECEIPT_VERSION,
    )
    namespace = root.name.lower().replace("_", "-")[:48]
    if not namespace or not namespace[0].isalnum():
        namespace = "fixture"
    policy = _seal(
        {
            "version": AUTHORITY_POLICY_VERSION,
            "policy_name": "temporary sealed fixture authority",
            "coordinator_id": COORDINATOR,
            "coordinator_namespace": namespace,
            "allowed_profile_identities": [profile["identity"]],
            "allowed_report_identities": [report["identity"]],
            "allowed_runner_identities": [profile["runner_identity"]["identity"]],
            "allowed_custody_identities": [profile["custody_evidence"]["identity"]],
            "allowed_issuers": [ISSUER],
            "allowed_verifiers": [VERIFIER],
            "allowed_stores": [STORE],
            "wave3_trust_roots": [],
        },
        AUTHORITY_POLICY_VERSION,
    )
    values = {
        "compatibility_profile": profile,
        "compatibility_report": report,
        "pristine_source_manifest": profile["pristine_source_manifest"],
        "overlay_manifest": profile["overlay_manifest"],
        "staging_manifest": profile["staging_manifest"],
        "runner_identity": profile["runner_identity"],
        "custody_evidence": profile["custody_evidence"],
        "acl_snapshot": acl,
        "immutable_store_receipt": store,
        "trusted_authority_policy": policy,
    }
    _install_external_authority(root, policy)
    return values, policy


def _install_external_authority(root: Path, policy: dict[str, Any]) -> Path:
    authority_root = (
        root.parent / ".skillopt-test-authority" / str(policy["coordinator_namespace"])
    )
    authority_root.mkdir(parents=True, exist_ok=True)
    coordinator_root = authority_root / "coordinator"
    coordinator_root.mkdir(parents=True, exist_ok=True)
    policy_path = authority_root / "trusted_authority_policy.json"
    _write_json(policy_path, policy)
    policy_bytes = policy_path.read_bytes()
    context = {
        "version": AUTHORITY_CONTEXT_VERSION,
        "coordinator_root": str(coordinator_root.resolve()),
        "coordinator_namespace": policy["coordinator_namespace"],
        "coordinator_id": policy["coordinator_id"],
        "trusted_policy": {
            "path": str(policy_path.resolve()),
            "identity": policy["identity"],
            "sha256": "sha256:" + hashlib.sha256(policy_bytes).hexdigest(),
            "size_bytes": len(policy_bytes),
        },
        "allowed_issuers": policy["allowed_issuers"],
        "allowed_verifiers": policy["allowed_verifiers"],
        "allowed_stores": policy["allowed_stores"],
    }
    context_path = authority_root / "authority_context.json"
    _write_json(context_path, context)
    os.environ[AUTHORITY_CONTEXT_ENV] = str(context_path.resolve())
    return context_path


def sealed_request(
    root: Path,
    *,
    source_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "dataset": "inputs/dataset.json",
        "execution_control": "inputs/execution_control.json",
        "baseline_skill": "inputs/baseline_skill.md",
        "generated_environment_archive": "inputs/generated_environment.tar",
        "dependency_lock": "inputs/requirements.lock",
        "rendered_config": "inputs/rendered_config.yaml",
        "compatibility_profile": "evidence/compatibility_profile.json",
        "compatibility_report": "evidence/compatibility_report.json",
        "pristine_source_manifest": "evidence/pristine_source_manifest.json",
        "overlay_manifest": "evidence/overlay_manifest.json",
        "staging_manifest": "evidence/staging_manifest.json",
        "runner_identity": "evidence/runner_identity.json",
        "custody_evidence": "evidence/custody_evidence.json",
        "acl_snapshot": "evidence/acl_snapshot.json",
        "immutable_store_receipt": "evidence/immutable_store_receipt.json",
        "trusted_authority_policy": "evidence/trusted_authority_policy.json",
    }
    defaults: dict[str, bytes | str] = {
        "dataset": _canonical_json_file(_DATASET_PATH),
        "execution_control": _canonical_json_file(_CONTROL_PATH),
        "baseline_skill": b"baseline policy\n",
        "generated_environment_archive": b"hermetic fixture archive\n",
        "dependency_lock": b"pip-compile lock for skillopt compatibility fixture\n",
        "rendered_config": CANONICAL_RENDERED_CONFIG_BYTES,
    }
    for name, payload in defaults.items():
        destination = root / paths[name]
        if source_paths and name in source_paths:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if name in {"dataset", "execution_control"}:
                _write(destination, _canonical_json_file(source_paths[name]))
            else:
                shutil.copyfile(source_paths[name], destination)
        else:
            _write(destination, payload)
    evidence, policy = _authority_evidence(root)
    for name, value in evidence.items():
        _write_json(root / paths[name], value)
    artifacts = {name: _entry(root, relative) for name, relative in paths.items()}
    profile = evidence["compatibility_profile"]
    staging = profile["staging_manifest"]
    runner = profile["runner_identity"]
    request = seal_run_request(
        {
            "version": RUN_REQUEST_VERSION,
            "created_at": CREATED_AT,
            "scope": V1_ALLOWED_SCOPE,
            "input_artifacts": artifacts,
            "upstream": {
                "profile_id": PROFILE_ID,
                "profile_identity": profile["identity"],
                "compatibility_report_identity": evidence["compatibility_report"][
                    "identity"
                ],
                "skillopt_revision": APPROVED_PEELED_COMMIT,
                "tree_git_sha1": APPROVED_TREE_GIT_SHA1,
                "archive_sha256": APPROVED_ARCHIVE_SHA256,
                "runner_image_digest": runner["image_digest"],
                "runner_identity": runner["identity"],
                "python_version": runner["python_version"],
                "dependency_lock_hash": artifacts["dependency_lock"]["sha256"],
                "pristine_source_identity": profile["pristine_source_manifest"][
                    "identity"
                ],
                "overlay_identity": profile["overlay_manifest"]["identity"],
                "staging_identity": staging["identity"],
                "custody_identity": profile["custody_evidence"]["identity"],
            },
            "execution": {
                "seeds": [7],
                "model_identifier": "fixture/model-2026-07-17",
                "train_argv": TRAIN_ARGV,
                "eval_argv": EVAL_ARGV,
                "train_argv_identity": staging["execution_config"][
                    "train_argv_identity"
                ],
                "eval_argv_identity": staging["execution_config"]["eval_argv_identity"],
                "execution_config_identity": staging["execution_config_identity"],
                "rendered_config_hash": artifacts["rendered_config"]["sha256"],
                "budget": {"max_cost_usd": 10.0, "max_tokens": 100_000},
                "timeout_seconds": 300,
                "max_retries": 2,
                "max_concurrency": 1,
            },
            "output": {
                "train_root": TRAIN_OUT_ROOT,
                "eval_root": EVAL_OUT_ROOT,
                "best_skill_path": CANDIDATE_PATH,
                "evaluation_path": EVAL_OUT_ROOT + "/evaluation.json",
                "sanitized_summary_path": EVAL_OUT_ROOT + "/sanitized_summary.json",
                "usage_receipt_path": EVAL_OUT_ROOT + "/usage_receipt.json",
                "privacy_receipt_path": EVAL_OUT_ROOT + "/privacy_receipt.json",
                "result_manifest_path": EVAL_OUT_ROOT + "/run_result.json",
                "schema_version": RUN_RESULT_VERSION,
            },
            "authority": {
                "evidence_class": "wave1_2_same_domain",
                "policy_identity": policy["identity"],
                "coordinator_id": policy["coordinator_id"],
                "coordinator_namespace": policy["coordinator_namespace"],
                "wave3_crypto_required": False,
            },
            "privacy": {
                "raw_user_logs_included": False,
                "pii_included": False,
                "requires_approved_export": True,
            },
        }
    )
    return request


def sealed_result(
    root: Path, request: dict[str, Any], *, status: str = "succeeded"
) -> dict[str, Any]:
    output = request["output"]
    best_path = root / output["best_skill_path"]
    best_entry = None
    if status == "succeeded":
        _write(
            best_path,
            "# QueryAnalyzer standard search path\n"
            "Do not enable `use_llm_search`.\n"
            "Do not enable HyDE.\n"
            "Do not promote RelevanceFilter.\n",
        )
        best_entry = _entry(root, output["best_skill_path"])
    _write_json(
        root / output["evaluation_path"], {"status": status, "split": "optimizer_test"}
    )
    _write_json(root / output["sanitized_summary_path"], {"status": "sanitized"})
    runner_identity = request["upstream"]["runner_identity"]
    usage = _seal(
        {
            "version": USAGE_RECEIPT_VERSION,
            "request_id": request["request_id"],
            "status": status,
            "runner_identity": runner_identity,
            "issuer_workload": ISSUER,
            "started_at": CREATED_AT,
            "completed_at": COMPLETED_AT,
            "cost_usd": 1.25 if status == "succeeded" else 0.0,
            "tokens": 5_000 if status == "succeeded" else 0,
        },
        USAGE_RECEIPT_VERSION,
    )
    redaction_hash = "sha256:" + "e" * 64
    privacy = _seal(
        {
            "version": PRIVACY_RECEIPT_VERSION,
            "request_id": request["request_id"],
            "status": status,
            "runner_identity": runner_identity,
            "issuer_workload": ISSUER,
            "completed_at": COMPLETED_AT,
            "raw_user_logs_included": False,
            "pii_included": False,
            "requires_approved_export": True,
            "redaction_passed": True,
            "redaction_report_sha256": redaction_hash,
        },
        PRIVACY_RECEIPT_VERSION,
    )
    _write_json(root / output["usage_receipt_path"], usage)
    _write_json(root / output["privacy_receipt_path"], privacy)
    timed_out = status == "timed_out"
    profile = json.loads(
        (
            root / request["input_artifacts"]["compatibility_profile"]["path"]
        ).read_bytes()
    )
    report = json.loads(
        (root / request["input_artifacts"]["compatibility_report"]["path"]).read_bytes()
    )
    store = json.loads(
        (
            root / request["input_artifacts"]["immutable_store_receipt"]["path"]
        ).read_bytes()
    )
    request_bytes = canonical_json_bytes(request)
    result = seal_run_result(
        {
            "version": RUN_RESULT_VERSION,
            "request_id": request["request_id"],
            "sealed_request": {
                "request_id": request["request_id"],
                "sha256": "sha256:" + hashlib.sha256(request_bytes).hexdigest(),
                "size_bytes": len(request_bytes),
            },
            "completed_at": COMPLETED_AT,
            "scope": request["scope"],
            "status": status,
            "upstream": copy.deepcopy(request["upstream"]),
            "execution": {
                "seeds": request["execution"]["seeds"],
                "model_identifier": request["execution"]["model_identifier"],
                "train_argv_identity": request["execution"]["train_argv_identity"],
                "eval_argv_identity": request["execution"]["eval_argv_identity"],
                "execution_config_identity": request["execution"][
                    "execution_config_identity"
                ],
                "rendered_config_hash": request["execution"]["rendered_config_hash"],
                "timeout_seconds": request["execution"]["timeout_seconds"],
                "max_retries": request["execution"]["max_retries"],
                "max_concurrency": request["execution"]["max_concurrency"],
                "exit_code": 0 if status == "succeeded" else 124 if timed_out else 1,
                "duration_seconds": 12.5,
                "timed_out": timed_out,
                "retry_count": 0,
            },
            "observed": {
                "profile_identity": profile["identity"],
                "compatibility_report_identity": report["identity"],
                "pristine_source_identity": profile["pristine_source_manifest"][
                    "identity"
                ],
                "overlay_identity": profile["overlay_manifest"]["identity"],
                "staging_identity": profile["staging_manifest"]["identity"],
                "runner_identity": profile["runner_identity"]["identity"],
                "custody_identity": profile["custody_evidence"]["identity"],
                "execution_config_identity": profile["staging_manifest"][
                    "execution_config_identity"
                ],
                "rendered_config_hash": request["execution"]["rendered_config_hash"],
                "train_argv": TRAIN_ARGV,
                "eval_argv": EVAL_ARGV,
                "imported_modules": profile["staging_manifest"][
                    "expected_imported_modules"
                ],
                "train_root": TRAIN_OUT_ROOT,
                "eval_root": EVAL_OUT_ROOT,
                "candidate_path": CANDIDATE_PATH,
            },
            "outputs": {
                "best_skill": best_entry,
                "evaluation": _entry(root, output["evaluation_path"]),
                "sanitized_summary": _entry(root, output["sanitized_summary_path"]),
            },
            "receipts": {
                "usage": _entry(root, output["usage_receipt_path"]),
                "privacy": _entry(root, output["privacy_receipt_path"]),
            },
            "logs": {
                "stdout_sha256": "sha256:" + "c" * 64,
                "stderr_sha256": "sha256:" + "d" * 64,
                "redaction_report_sha256": redaction_hash,
            },
            "budget_usage": {"cost_usd": usage["cost_usd"], "tokens": usage["tokens"]},
            "attestation": {
                "evidence_class": "wave1_2_same_domain",
                "custody_identity": profile["custody_evidence"]["identity"],
                "store_receipt_identity": store["identity"],
                "policy_identity": request["authority"]["policy_identity"],
            },
            "candidate_binding": {
                "best_skill_hash": best_entry["sha256"] if best_entry else None,
                "evaluation_hash": _entry(root, output["evaluation_path"])["sha256"],
                "dataset_hash": request["input_artifacts"]["dataset"]["sha256"],
                "execution_control_hash": request["input_artifacts"][
                    "execution_control"
                ]["sha256"],
                "profile_identity": profile["identity"],
                "overlay_identity": profile["overlay_manifest"]["identity"],
                "staging_identity": profile["staging_manifest"]["identity"],
                "runner_identity": profile["runner_identity"]["identity"],
                "custody_identity": profile["custody_evidence"]["identity"],
            },
            "privacy": {
                "raw_user_logs_included": False,
                "pii_included": False,
                "requires_approved_export": True,
                "redaction_passed": True,
                "redaction_report_sha256": redaction_hash,
            },
        }
    )
    return result


def publish_accepted_candidate(
    *,
    parent: Path,
    best_skill_path: Path,
    dataset_path: str | Path,
    control_path: str | Path,
    baseline_skill_path: str | Path,
) -> dict[str, str]:
    candidate_hash = (
        "sha256:" + hashlib.sha256(best_skill_path.read_bytes()).hexdigest()
    )
    root = parent / "accepted-run" / candidate_hash.removeprefix("sha256:")[:16]
    sources = {
        "dataset": Path(dataset_path),
        "execution_control": Path(control_path),
        "baseline_skill": Path(baseline_skill_path),
    }
    request = sealed_request(root, source_paths=sources)
    request_path = root / "incoming_request.json"
    _write_json(request_path, request)
    result = sealed_result(root, request)
    runner_best = root / request["output"]["best_skill_path"]
    shutil.copyfile(best_skill_path, runner_best)
    result["outputs"]["best_skill"] = _entry(root, request["output"]["best_skill_path"])
    result["candidate_binding"]["best_skill_hash"] = result["outputs"]["best_skill"][
        "sha256"
    ]
    result_payload = dict(result)
    result_payload.pop("result_id")
    result = seal_run_result(result_payload)
    result_path = root / request["output"]["result_manifest_path"]
    _write_json(result_path, result)
    status = run_orchestrator(
        run_root=root,
        request_path=request_path,
        import_result_path=result_path,
    )
    if status.get("state") != "candidate_ready":
        raise AssertionError(f"fixture candidate was not accepted: {status}")
    return {
        "acceptance_manifest_path": str(status["acceptance_manifest_path"]),
        "run_root": str(root),
    }
