from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.search_eval.skillopt_compatibility import (
    PROFILE_ID,
    SAME_DOMAIN_CUSTODY_EVIDENCE_VERSION,
    seal_identity_artifact,
)
from src.search_eval.skillopt_contract import ValidationError, canonical_self_hash
from src.search_eval.skillopt_run_contract import (
    AUTHORITY_CONTEXT_ENV,
    RUN_REQUEST_VERSION,
    RUN_RESULT_VERSION,
    canonical_json_bytes,
    load_json_strict,
    seal_run_request,
    seal_run_result,
    validate_run_request,
    validate_run_result,
)
from tests.skillopt_acceptance_fixtures import (
    _install_external_authority,
    _entry,
    _write_json,
    sealed_request,
    sealed_result,
)


def _sealed_request(root: Path) -> dict:
    return sealed_request(root)


def _sealed_result(root: Path, request: dict, *, status: str = "succeeded") -> dict:
    return sealed_result(root, request, status=status)


def _reseal_request(request: dict) -> dict:
    payload = copy.deepcopy(request)
    payload.pop("request_id", None)
    return seal_run_request(payload)


def _reseal_result(result: dict) -> dict:
    payload = copy.deepcopy(result)
    payload.pop("result_id", None)
    return seal_run_result(payload)


def _replace_evidence(root: Path, request: dict, name: str, value: dict) -> dict:
    path = root / request["input_artifacts"][name]["path"]
    _write_json(path, value)
    request["input_artifacts"][name] = _entry(root, path.relative_to(root).as_posix())
    return _reseal_request(request)


def _replace_receipt(
    root: Path, request: dict, result: dict, name: str, updates: dict
) -> dict:
    path = root / result["receipts"][name]["path"]
    value = json.loads(path.read_bytes())
    value.update(updates)
    value = seal_identity_artifact(value, value["version"])
    _write_json(path, value)
    result["receipts"][name] = _entry(root, path.relative_to(root).as_posix())
    return _reseal_result(result)


def test_exact_valid_sealed_request_and_result(tmp_path: Path):
    request = _sealed_request(tmp_path)
    result = _sealed_result(tmp_path, request)
    validate_run_request(request, run_root=tmp_path)
    validate_run_result(result, request=request, run_root=tmp_path)
    assert request["version"] == RUN_REQUEST_VERSION
    assert result["version"] == RUN_RESULT_VERSION


def test_request_created_trust_bundle_fails_without_external_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request = _sealed_request(tmp_path)
    monkeypatch.delenv(AUTHORITY_CONTEXT_ENV)
    with pytest.raises(ValidationError, match="external authority context is required"):
        validate_run_request(request, run_root=tmp_path)


def test_request_policy_bytes_must_match_external_pin(tmp_path: Path):
    request = _sealed_request(tmp_path)
    path = tmp_path / request["input_artifacts"]["trusted_authority_policy"]["path"]
    policy = json.loads(path.read_bytes())
    policy["policy_name"] = "request-selected replacement authority"
    policy = seal_identity_artifact(policy, policy["version"])
    request = _replace_evidence(tmp_path, request, "trusted_authority_policy", policy)
    with pytest.raises(ValidationError, match="external exact-byte authority pin"):
        validate_run_request(request, run_root=tmp_path)


def test_external_allowlist_pin_mismatch_fails_closed(tmp_path: Path):
    request = _sealed_request(tmp_path)
    context_path = Path(os.environ[AUTHORITY_CONTEXT_ENV])
    context = json.loads(context_path.read_bytes())
    context["allowed_issuers"] = ["different-external-issuer"]
    _write_json(context_path, context)
    with pytest.raises(ValidationError, match="allowed_issuers pin mismatch"):
        validate_run_request(request, run_root=tmp_path)


@pytest.mark.parametrize("name", ["acl_snapshot", "immutable_store_receipt"])
def test_acl_and_store_are_revalidated_at_actual_load_time(tmp_path: Path, name: str):
    request = _sealed_request(tmp_path)
    target = tmp_path / request["input_artifacts"][name]["path"]
    value = json.loads(target.read_bytes())
    now = datetime.now(timezone.utc).replace(microsecond=0)
    value["issued_at"] = (
        (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    )
    value["expires_at"] = (
        (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    )
    value = seal_identity_artifact(value, value["version"])
    request = _replace_evidence(tmp_path, request, name, value)
    with pytest.raises(ValidationError, match="expired or not yet valid"):
        validate_run_request(request, run_root=tmp_path)


@pytest.mark.parametrize(
    ("receipt", "updates"),
    [
        ("usage", {"started_at": "2000-01-01T00:00:00Z"}),
        ("usage", {"completed_at": "2999-01-01T00:00:00Z"}),
        (
            "usage",
            {
                "started_at": "2026-01-02T00:00:00Z",
                "completed_at": "2026-01-01T00:00:00Z",
            },
        ),
        ("privacy", {"completed_at": "2999-01-01T00:00:00Z"}),
    ],
)
def test_receipt_times_must_stay_inside_request_result_interval(
    tmp_path: Path, receipt: str, updates: dict
):
    request = _sealed_request(tmp_path)
    result = _sealed_result(tmp_path, request)
    result = _replace_receipt(tmp_path, request, result, receipt, updates)
    with pytest.raises(ValidationError, match="request/result interval"):
        validate_run_result(result, request=request, run_root=tmp_path)


@pytest.mark.parametrize(
    "offered",
    [{}, {"version": "skillopt-search-benchmark-materialization-v0"}],
)
def test_materialization_v0_cannot_be_offered_as_v2_authority(
    tmp_path: Path, offered: dict
):
    request = _sealed_request(tmp_path)
    path = tmp_path / "inputs" / "offered-materialization.json"
    _write_json(path, offered)
    request["input_artifacts"]["materialization_manifest"] = _entry(
        tmp_path, path.relative_to(tmp_path).as_posix()
    )
    request = _reseal_request(request)
    with pytest.raises(ValidationError, match="input_artifacts keys mismatch"):
        validate_run_request(request, run_root=tmp_path)


@pytest.mark.parametrize(
    "artifact_name",
    [
        "dataset",
        "execution_control",
        "baseline_skill",
        "generated_environment_archive",
        "dependency_lock",
        "rendered_config",
        "compatibility_profile",
        "compatibility_report",
        "pristine_source_manifest",
        "overlay_manifest",
        "staging_manifest",
        "runner_identity",
        "custody_evidence",
        "acl_snapshot",
        "immutable_store_receipt",
        "trusted_authority_policy",
    ],
)
def test_one_byte_mutation_of_every_request_evidence_class_fails(
    tmp_path: Path, artifact_name: str
):
    request = _sealed_request(tmp_path)
    target = tmp_path / request["input_artifacts"][artifact_name]["path"]
    target.write_bytes(target.read_bytes() + b"x")
    with pytest.raises(ValidationError, match="exact-byte binding mismatch"):
        validate_run_request(request, run_root=tmp_path)


def test_request_rejects_legacy_version_without_upgrade(tmp_path: Path):
    request = _sealed_request(tmp_path)
    request["version"] = "skillopt-run-request-v1"
    with pytest.raises(ValidationError, match="legacy v1 cannot be upgraded"):
        validate_run_request(request, run_root=tmp_path)


def test_unresolved_production_catalog_profile_fails_closed(tmp_path: Path):
    request = _sealed_request(tmp_path)
    catalog = json.loads(
        Path("data/search_eval/skillopt_compatibility_profiles_v1.json").read_text()
    )
    request = _replace_evidence(
        tmp_path, request, "compatibility_profile", catalog["profiles"][PROFILE_ID]
    )
    with pytest.raises(ValidationError, match="unresolved|missing required"):
        validate_run_request(request, run_root=tmp_path)


def test_diagnostic_not_authorized_report_is_never_promoted(tmp_path: Path):
    request = _sealed_request(tmp_path)
    report_path = tmp_path / request["input_artifacts"]["compatibility_report"]["path"]
    report = json.loads(report_path.read_bytes())
    report["version"] = "skillopt_mock_execution_diagnostic_v1"
    request = _replace_evidence(tmp_path, request, "compatibility_report", report)
    with pytest.raises(ValidationError, match="diagnostic or unsupported"):
        validate_run_request(request, run_root=tmp_path)


@pytest.mark.parametrize(
    ("issued_at", "expires_at"),
    [
        ("2026-07-15T00:00:00Z", "2026-07-16T00:00:00Z"),
        ("2026-07-18T00:00:00Z", "2026-07-19T00:00:00Z"),
    ],
)
def test_expired_or_future_custody_fails(
    tmp_path: Path, issued_at: str, expires_at: str
):
    request = _sealed_request(tmp_path)
    path = tmp_path / request["input_artifacts"]["custody_evidence"]["path"]
    custody = json.loads(path.read_bytes())
    custody["issued_at"] = issued_at
    custody["expires_at"] = expires_at
    custody = seal_identity_artifact(custody, SAME_DOMAIN_CUSTODY_EVIDENCE_VERSION)
    request = _replace_evidence(tmp_path, request, "custody_evidence", custody)
    with pytest.raises(ValidationError, match="not valid"):
        validate_run_request(request, run_root=tmp_path)


def test_self_issued_custody_fails(tmp_path: Path):
    request = _sealed_request(tmp_path)
    path = tmp_path / request["input_artifacts"]["custody_evidence"]["path"]
    custody = json.loads(path.read_bytes())
    custody["issuer_workload"] = custody["verifier_id"]
    custody = seal_identity_artifact(custody, SAME_DOMAIN_CUSTODY_EVIDENCE_VERSION)
    request = _replace_evidence(tmp_path, request, "custody_evidence", custody)
    with pytest.raises(ValidationError, match="issuer must differ"):
        validate_run_request(request, run_root=tmp_path)


@pytest.mark.parametrize("name", ["acl_snapshot", "immutable_store_receipt"])
def test_changed_acl_or_store_receipt_fails(tmp_path: Path, name: str):
    request = _sealed_request(tmp_path)
    target = tmp_path / request["input_artifacts"][name]["path"]
    value = json.loads(target.read_bytes())
    version = value["version"]
    value["store_id"] = "untrusted-store"
    value = seal_identity_artifact(value, version)
    request = _replace_evidence(tmp_path, request, name, value)
    with pytest.raises(ValidationError, match="mismatch|trusted"):
        validate_run_request(request, run_root=tmp_path)


def test_acl_principals_are_exactly_coordinator_and_acl_verifier(tmp_path: Path):
    request = _sealed_request(tmp_path)
    path = tmp_path / request["input_artifacts"]["acl_snapshot"]["path"]
    acl = json.loads(path.read_bytes())
    acl["principals"] = sorted([*acl["principals"], "hostile-extra-principal"])
    acl = seal_identity_artifact(acl, acl["version"])
    request = _replace_evidence(tmp_path, request, "acl_snapshot", acl)

    with pytest.raises(ValidationError, match="principals must be exactly"):
        validate_run_request(request, run_root=tmp_path)


def test_acl_custody_store_verifiers_cannot_cross_bind_hostile_allowlisted_values(
    tmp_path: Path,
):
    request = _sealed_request(tmp_path)
    hostile_verifier = "hostile-but-allowlisted-verifier"
    store_path = (
        tmp_path / request["input_artifacts"]["immutable_store_receipt"]["path"]
    )
    store = json.loads(store_path.read_bytes())
    store["verifier_id"] = hostile_verifier
    store = seal_identity_artifact(store, store["version"])
    request = _replace_evidence(tmp_path, request, "immutable_store_receipt", store)

    policy_path = (
        tmp_path / request["input_artifacts"]["trusted_authority_policy"]["path"]
    )
    policy = json.loads(policy_path.read_bytes())
    policy["allowed_verifiers"] = sorted(
        [*policy["allowed_verifiers"], hostile_verifier]
    )
    policy = seal_identity_artifact(policy, policy["version"])
    request = _replace_evidence(tmp_path, request, "trusted_authority_policy", policy)
    request["authority"]["policy_identity"] = policy["identity"]
    request = _reseal_request(request)
    _install_external_authority(tmp_path, policy)

    with pytest.raises(ValidationError, match="verifier cross-binding"):
        validate_run_request(request, run_root=tmp_path)


def test_request_rejects_noncanonical_dataset_before_publication(tmp_path: Path):
    request = _sealed_request(tmp_path)
    path = tmp_path / request["input_artifacts"]["dataset"]["path"]
    path.write_bytes(path.read_bytes() + b"\n")
    request["input_artifacts"]["dataset"] = _entry(
        tmp_path, path.relative_to(tmp_path).as_posix()
    )
    request = _reseal_request(request)

    with pytest.raises(ValidationError, match="dataset.*not canonically encoded"):
        validate_run_request(request, run_root=tmp_path)


@pytest.mark.parametrize("artifact_name", ["dataset", "execution_control"])
def test_request_rejects_input_artifacts_missing_required_keys(
    tmp_path: Path, artifact_name: str
):
    request = _sealed_request(tmp_path)
    path = tmp_path / request["input_artifacts"][artifact_name]["path"]
    _write_json(path, {})
    request["input_artifacts"][artifact_name] = _entry(
        tmp_path, path.relative_to(tmp_path).as_posix()
    )
    request = _reseal_request(request)

    with pytest.raises(ValidationError, match="missing required keys"):
        validate_run_request(request, run_root=tmp_path)


def test_request_rejects_private_raw_log_dataset_before_publication(tmp_path: Path):
    request = _sealed_request(tmp_path)
    path = tmp_path / request["input_artifacts"]["dataset"]["path"]
    dataset = json.loads(path.read_bytes())
    dataset["queries"][0]["query_text"] = "private raw user logs session_id"
    dataset["dataset_hash"] = canonical_self_hash(dataset, "dataset_hash")
    request = _replace_evidence(tmp_path, request, "dataset", dataset)

    with pytest.raises(ValidationError, match="private or raw-log text"):
        validate_run_request(request, run_root=tmp_path)


def test_request_rejects_semantically_invalid_execution_control_before_publication(
    tmp_path: Path,
):
    request = _sealed_request(tmp_path)
    path = tmp_path / request["input_artifacts"]["execution_control"]["path"]
    control = json.loads(path.read_bytes())
    control["scope"] = "hostile-private-raw-log-scope"
    control["control_hash"] = canonical_self_hash(control, "control_hash")
    request = _replace_evidence(tmp_path, request, "execution_control", control)

    with pytest.raises(ValidationError, match="execution_control.scope"):
        validate_run_request(request, run_root=tmp_path)


@pytest.mark.parametrize(
    ("artifact_name", "hash_field", "nested_path", "match"),
    [
        ("dataset", "dataset_hash", ("raw_logs",), "forbidden keys.*raw_logs"),
        (
            "dataset",
            "dataset_hash",
            ("queries", 0, "labels", "acceptable", 0),
            "private or raw-log text",
        ),
        (
            "dataset",
            "dataset_hash",
            ("provenance", "privacy_review"),
            "private or raw-log text",
        ),
        (
            "execution_control",
            "control_hash",
            ("raw_logs",),
            "forbidden keys.*raw_logs",
        ),
        (
            "execution_control",
            "control_hash",
            ("hyde_policy", "reason"),
            "private or raw-log text",
        ),
        (
            "execution_control",
            "control_hash",
            ("required_rollout_metadata", 0),
            "private or raw-log text",
        ),
    ],
)
def test_request_rejects_hostile_rehashed_artifacts_before_publication(
    tmp_path: Path,
    artifact_name: str,
    hash_field: str,
    nested_path: tuple[str | int, ...],
    match: str,
):
    request = _sealed_request(tmp_path)
    path = tmp_path / request["input_artifacts"][artifact_name]["path"]
    artifact = json.loads(path.read_bytes())
    target = artifact
    for key in nested_path[:-1]:
        target = target[key]
    target[nested_path[-1]] = "john.doe@example.com private raw user logs session_id"
    artifact[hash_field] = canonical_self_hash(artifact, hash_field)
    request = _replace_evidence(tmp_path, request, artifact_name, artifact)

    with pytest.raises(ValidationError, match=match):
        validate_run_request(request, run_root=tmp_path)
    assert not (tmp_path / "artifacts" / "acceptance_manifest.json").exists()


def test_canonical_json_whitespace_and_key_reordering_rejected(tmp_path: Path):
    request = _sealed_request(tmp_path)
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request, indent=2), encoding="utf-8")
    with pytest.raises(ValidationError, match="not canonically encoded"):
        load_json_strict(path, require_canonical=True)
    path.write_text(json.dumps(request), encoding="utf-8")
    with pytest.raises(ValidationError, match="not canonically encoded"):
        load_json_strict(path, require_canonical=True)


def test_result_cross_binds_request_observed_execution_and_paths(tmp_path: Path):
    request = _sealed_request(tmp_path)
    result = _sealed_result(tmp_path, request)
    result["observed"]["runner_identity"] = "sha256:" + "0" * 64
    result = _reseal_result(result)
    with pytest.raises(ValidationError, match="observed execution"):
        validate_run_result(result, request=request, run_root=tmp_path)


@pytest.mark.parametrize(
    ("section", "field", "match"),
    [
        ("budget_usage", "tokens", "usage receipt"),
        ("privacy", "redaction_passed", "privacy receipt|privacy/redaction"),
    ],
)
def test_claimed_usage_and_privacy_must_equal_receipts(
    tmp_path: Path, section: str, field: str, match: str
):
    request = _sealed_request(tmp_path)
    result = _sealed_result(tmp_path, request)
    value = result[section][field]
    result[section][field] = value + 1 if isinstance(value, int) else not value
    result = _reseal_result(result)
    with pytest.raises(ValidationError, match=match):
        validate_run_result(result, request=request, run_root=tmp_path)


def test_result_binds_exact_request_bytes(tmp_path: Path):
    request = _sealed_request(tmp_path)
    result = _sealed_result(tmp_path, request)
    result["sealed_request"]["sha256"] = "sha256:" + "0" * 64
    result = _reseal_result(result)
    with pytest.raises(ValidationError, match="sealed request byte binding"):
        validate_run_result(result, request=request, run_root=tmp_path)


def test_train_eval_roots_and_result_path_are_exact(tmp_path: Path):
    request = _sealed_request(tmp_path)
    request["output"]["eval_root"] = request["output"]["train_root"]
    request = _reseal_request(request)
    with pytest.raises(ValidationError, match="output roots"):
        validate_run_request(request, run_root=tmp_path)


def test_symlink_and_hardlink_inputs_fail(tmp_path: Path):
    request = _sealed_request(tmp_path)
    dataset = tmp_path / request["input_artifacts"]["dataset"]["path"]
    original = dataset.read_bytes()
    dataset.unlink()
    outside = tmp_path / "outside.json"
    outside.write_bytes(original)
    dataset.symlink_to(outside)
    with pytest.raises(ValidationError, match="symlink"):
        validate_run_request(request, run_root=tmp_path)

    dataset.unlink()
    dataset.write_bytes(original)
    hardlink = tmp_path / "dataset-hardlink.json"
    try:
        os.link(dataset, hardlink)
    except OSError:
        pytest.skip("hard links unavailable")
    with pytest.raises(ValidationError, match="hard link"):
        validate_run_request(request, run_root=tmp_path)


@pytest.mark.parametrize("status", ["failed", "timed_out", "cancelled"])
def test_non_success_results_are_terminal_but_not_candidates(
    tmp_path: Path, status: str
):
    request = _sealed_request(tmp_path)
    result = _sealed_result(tmp_path, request, status=status)
    validate_run_result(result, request=request, run_root=tmp_path)
