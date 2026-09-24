from __future__ import annotations

import copy
import hashlib
import json
import os
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.search_eval.orchestrator import run_orchestrator
from src.search_eval import skillopt_observability as observability
from src.search_eval.skillopt_contract import ValidationError
from src.search_eval.skillopt_observability import (
    EvidenceClass,
    ValidatedAttemptSummary,
    ValidatedOperatorEnvelope,
    build_attempt_summary,
    build_operator_envelope,
    derive_alerts,
    load_attempt_summary,
    load_operator_envelope,
    main,
    reject_sensitive_observability_value,
    revalidate_attempt_summary,
    revalidate_operator_envelope,
    validate_attempt_summary,
    validate_evidence_gate,
    validate_operator_envelope,
)
from src.search_eval.skillopt_run_contract import (
    canonical_value_hash,
    capture_run_request,
    capture_run_result,
)
from tests.skillopt_acceptance_fixtures import (
    _write_json,
    sealed_request,
    sealed_result,
)


@pytest.fixture
def source(tmp_path: Path) -> dict[str, object]:
    request_value = sealed_request(tmp_path)
    request_path = tmp_path / "incoming-request.json"
    _write_json(request_path, request_value)
    result_value = sealed_result(tmp_path, request_value)
    result_path = tmp_path / request_value["output"]["result_manifest_path"]
    _write_json(result_path, result_value)
    request = capture_run_request(request_value, run_root=tmp_path)
    result = capture_run_result(
        result_value, request=request_value, run_root=tmp_path, request_capture=request
    )
    run_orchestrator(
        run_root=tmp_path, request_path=request_path, import_result_path=result_path
    )
    heartbeat = json.loads((tmp_path / "heartbeat.json").read_bytes())
    return {
        "root": tmp_path,
        "request_path": request_path,
        "result_path": result_path,
        "request": request,
        "result": result,
        "status": json.loads((tmp_path / "status.json").read_bytes()),
        "journal": json.loads((tmp_path / "stage_journal.json").read_bytes()),
        "heartbeat": heartbeat,
        "heartbeat_at": datetime.fromisoformat(
            heartbeat["updated_at"].replace("Z", "+00:00")
        ),
    }


def _summary(
    source: dict[str, object], stale_seconds: int = 1
) -> ValidatedAttemptSummary:
    observed = datetime.now(timezone.utc)
    if stale_seconds > 5:
        heartbeat_at = source["heartbeat_at"]
        shift = observed - heartbeat_at - timedelta(seconds=stale_seconds)
        for event in source["journal"]["events"]:
            event_at = datetime.fromisoformat(event["at"].replace("Z", "+00:00"))
            event["at"] = (event_at + shift).isoformat().replace("+00:00", "Z")
        for record in (source["status"], source["heartbeat"]):
            record_at = datetime.fromisoformat(
                record["updated_at"].replace("Z", "+00:00")
            )
            record["updated_at"] = (
                (record_at + shift).isoformat().replace("+00:00", "Z")
            )
        _write_json(source["root"] / "stage_journal.json", source["journal"])
        _write_json(source["root"] / "status.json", source["status"])
        _write_json(source["root"] / "heartbeat.json", source["heartbeat"])
    return observability._build_attempt_summary_from_sources(
        attempt_id="attempt:g007-fixture",
        request_path=source["request_path"],
        result_path=source["result_path"],
        run_root=source["root"],
        freshness_threshold_seconds=900,
        now_fn=lambda: observed,
    )


def _rehash(record: dict, field: str) -> None:
    record.pop(field, None)
    record[field] = canonical_value_hash(record)


def test_summary_derives_compatibility_class_and_mode_from_sealed_sources(source):
    summary = _summary(source)
    assert (summary["evidence_class"], summary["measurement_mode"]) == (
        "compatibility",
        "diagnostic_exact_source",
    )
    assert summary["request_ref"]["sha256"] == source["request"].sha256
    assert summary["result_ref"]["sha256"] == source["result"].sha256


@pytest.mark.parametrize(
    "requested",
    [
        EvidenceClass.FIXTURE,
        EvidenceClass.MEASURED_RESEARCH,
        EvidenceClass.SHADOW,
        EvidenceClass.PRODUCTION,
    ],
)
def test_gate_cannot_construct_fixture_measured_shadow_or_production(requested):
    with pytest.raises(ValidationError, match="unsupported"):
        validate_evidence_gate(requested=requested)


def test_gate_rejects_caller_supplied_higher_available_label():
    with pytest.raises(ValidationError, match="caller evidence labels"):
        validate_evidence_gate(
            requested=EvidenceClass.COMPATIBILITY, available=EvidenceClass.SHADOW
        )


def test_envelope_rejects_raw_mapping_even_with_valid_self_hash(source):
    with pytest.raises(ValidationError, match="typed summary"):
        build_operator_envelope(_summary(source).persisted_record(), ())


def test_public_wrappers_and_raw_validators_cannot_forge_capabilities(source):
    record = _summary(source).persisted_record()
    assert type(validate_attempt_summary(record)) is dict
    with pytest.raises(TypeError, match="privately minted"):
        ValidatedAttemptSummary(record, None, object())


def test_loaders_require_sources_return_typed_wrappers_and_revalidate(source):
    root = source["root"]
    summary = _summary(source)
    envelope = build_operator_envelope(summary, derive_alerts(summary))
    _write_json(root / "summary.json", summary.persisted_record())
    _write_json(root / "envelope.json", envelope.persisted_record())
    with pytest.raises(TypeError):
        load_attempt_summary(root / "summary.json")
    loaded_summary = load_attempt_summary(
        root / "summary.json",
        request_path=source["request_path"],
        result_path=source["result_path"],
        run_root=root,
    )
    loaded_envelope = load_operator_envelope(
        root / "envelope.json",
        request_path=source["request_path"],
        result_path=source["result_path"],
        run_root=root,
    )
    assert isinstance(loaded_summary, ValidatedAttemptSummary)
    assert isinstance(loaded_envelope, ValidatedOperatorEnvelope)
    assert revalidate_attempt_summary(loaded_summary) == summary
    assert revalidate_operator_envelope(loaded_envelope) == envelope


def test_future_heartbeat_is_rejected(source):
    future = datetime.now(timezone.utc) + timedelta(minutes=2)
    for event in source["journal"]["events"]:
        event["at"] = future.isoformat().replace("+00:00", "Z")
    source["status"]["updated_at"] = future.isoformat().replace("+00:00", "Z")
    source["heartbeat"]["updated_at"] = future.isoformat().replace("+00:00", "Z")
    _write_json(source["root"] / "stage_journal.json", source["journal"])
    _write_json(source["root"] / "status.json", source["status"])
    _write_json(source["root"] / "heartbeat.json", source["heartbeat"])
    with pytest.raises(ValidationError, match="trusted clock"):
        build_attempt_summary(
            attempt_id="attempt:g007-future",
            request_path=source["request_path"],
            result_path=source["result_path"],
            run_root=source["root"],
        )


def test_nonmonotonic_journal_timestamp_is_rejected(source):
    source["journal"]["events"][1]["at"] = "2000-01-01T00:00:00Z"
    _write_json(source["root"] / "stage_journal.json", source["journal"])
    with pytest.raises(ValidationError, match="not monotonic"):
        _summary(source)


def test_validator_recomputes_heartbeat_freshness(source):
    record = _summary(source).persisted_record()
    record["heartbeat"]["stale_seconds"] += 1
    _rehash(record, "summary_hash")
    with pytest.raises(ValidationError, match="freshness is not derived"):
        validate_attempt_summary(record)


def test_all_seven_alerts_have_exact_order_cardinality_owner_and_policy(source):
    alerts = derive_alerts(
        _summary(source, 901),
        compatibility_failure_count=3,
        expected_revision="different-revision",
        budget_breach_detected=True,
        privacy_finding_count=1,
        release_holdout_reference_count=1,
        authorization_enablement_requested=True,
    )
    expected = {
        "authorization_misuse": ("critical", 90, 30),
        "budget_breach": ("critical", 90, 30),
        "privacy_finding": ("critical", 30, 7),
        "release_holdout_leak": ("critical", 90, 30),
        "repeated_compatibility_failure": ("warning", 30, 7),
        "revision_drift": ("critical", 90, 30),
        "stale_heartbeat": ("warning", 30, 7),
    }
    assert len(alerts) == 7
    assert [alert["code"] for alert in alerts] == sorted(expected)
    assert all(alert["owner"] == "skillopt-operations" for alert in alerts)
    assert {
        alert["code"]: (
            alert["severity"],
            alert["retention_days"],
            alert["deletion_grace_days"],
        )
        for alert in alerts
    } == expected


def test_exception_digest_is_sha256_of_type_only(source):
    alert = derive_alerts(
        _summary(source), exception=RuntimeError("API_KEY=must-not-persist")
    )[0]
    assert (
        alert["exception_digest"]
        == "sha256:" + hashlib.sha256(b"RuntimeError").hexdigest()
    )
    assert "must-not-persist" not in json.dumps(alert.persisted_record())


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": "raw user prompt"},
        {"safe": "person@example.com"},
        {"safe": "AKIAIOSFODNN7EXAMPLE"},
        {"safe": "ghp_abcdefghijklmnopqrstuvwxyz"},
        {"safe": "api_key=plaintext"},
        {"safe": "password=plaintext"},
        {"safe": "Authorization: Bearer plaintext"},
        {"safe": "Cookie: sessionid=plaintext"},
        {"safe": "eyJabcdefgh.abcdefgh.abcdefgh"},
        {"safe": "-----BEGIN PRIVATE KEY-----"},
        {"safe": "aws_secret_access_key=plaintext"},
        {"safe": "https://example.test/path?token=plaintext"},
        {"safe": "https://name:password@example.test/path"},
    ],
)
def test_plaintext_sensitive_alert_values_are_rejected(payload):
    with pytest.raises(ValidationError, match="sensitive|secret-bearing"):
        reject_sensitive_observability_value(payload)


def test_plaintext_optional_alert_reference_is_rejected(source):
    with pytest.raises(ValidationError, match="exact quarantine digest"):
        derive_alerts(_summary(source), quarantine_reference="person@example.com")


def test_quarantine_reference_requires_exact_lowercase_digest(source):
    valid = "quarantine:sha256:" + "a" * 64
    assert (
        derive_alerts(
            _summary(source), privacy_finding_count=1, quarantine_reference=valid
        )[0]["quarantine_reference"]
        == valid
    )
    with pytest.raises(ValidationError, match="exact quarantine digest"):
        derive_alerts(
            _summary(source),
            privacy_finding_count=1,
            quarantine_reference="quarantine:sha256:" + "A" * 64,
        )


def test_sensitive_schema_allows_only_safe_aggregate_suffixes():
    reject_sensitive_observability_value(
        {"policy_hash": "sha256:" + "0" * 64, "user_count": 2, "query_count": 3}
    )
    for key in ("policy", "raw_policy", "user", "query"):
        with pytest.raises(ValidationError, match="sensitive"):
            reject_sensitive_observability_value({key: "content"})


def test_operator_envelope_is_observe_only_and_all_actions_are_false(source):
    envelope = build_operator_envelope(_summary(source), ())
    assert envelope["mode"] == "observe_only"
    assert all(
        envelope[key] is False
        for key in (
            "network_action",
            "provider_action",
            "subprocess_action",
            "production_action",
            "runtime_action",
            "promotion_action",
        )
    )


def test_source_hash_tamper_is_rejected(source):
    source["status"]["request_sha256"] = "sha256:" + "0" * 64
    _write_json(source["root"] / "status.json", source["status"])
    with pytest.raises(ValidationError, match="request_sha256 mismatch"):
        _summary(source)


def test_lifecycle_chain_tamper_is_rejected(source):
    source["journal"]["events"][-1]["old_state"] = "tampered"
    _write_json(source["root"] / "stage_journal.json", source["journal"])
    with pytest.raises(ValidationError, match="schema/chain mismatch"):
        _summary(source)


def test_summary_self_hash_tamper_is_rejected(source):
    record = _summary(source).persisted_record()
    record["revision"] = "tampered-revision"
    with pytest.raises(ValidationError, match="summary_hash mismatch"):
        validate_attempt_summary(record)


def test_envelope_self_hash_tamper_is_rejected(source):
    record = build_operator_envelope(_summary(source), ()).persisted_record()
    record["envelope_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="envelope_hash mismatch"):
        validate_operator_envelope(record)


def test_cli_prints_json_without_network_subprocess_or_runtime_mutation(
    source, monkeypatch, capsys
):
    root = source["root"]
    before_files = {
        path: path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    before_environment = dict(os.environ)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("CLI attempted forbidden external action")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    assert (
        main(
            [
                "--request",
                str(source["request_path"]),
                "--result",
                str(source["result_path"]),
                "--run-root",
                str(root),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "observe_only"
    assert output["alerts"] == []
    assert dict(os.environ) == before_environment
    assert {
        path: path.read_bytes() for path in root.rglob("*") if path.is_file()
    } == before_files


def test_cli_returns_nonzero_no_go_when_any_alert_is_present(source, capsys):
    _summary(source, stale_seconds=901)
    result = main(
        [
            "--request",
            str(source["request_path"]),
            "--result",
            str(source["result_path"]),
            "--run-root",
            str(source["root"]),
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert result != 0
    assert [alert["code"] for alert in output["alerts"]] == ["stale_heartbeat"]
    reject_sensitive_observability_value(output)


def test_revalidation_and_cli_fail_after_authoritative_source_mutation(source):
    summary = _summary(source)
    source["status"]["reason"] = "mutated"
    _write_json(source["root"] / "status.json", source["status"])
    with pytest.raises(ValidationError, match="sources changed"):
        revalidate_attempt_summary(summary)
    source["status"]["request_sha256"] = "sha256:" + "0" * 64
    _write_json(source["root"] / "status.json", source["status"])
    with pytest.raises(ValidationError, match="request_sha256 mismatch"):
        main(
            [
                "--request",
                str(source["request_path"]),
                "--result",
                str(source["result_path"]),
                "--run-root",
                str(source["root"]),
            ]
        )


def test_docs_match_active_phase6_boundaries():
    root = Path(__file__).resolve().parents[1]
    docs = "\n".join(
        (root / path).read_text()
        for path in (
            "docs/skillopt_search/README.md",
            "docs/skillopt_search/operations.md",
        )
    )
    for identity in (
        "skillopt-orchestrator-status-v2",
        "skillopt-orchestrator-journal-v2",
        "skillopt-orchestrator-heartbeat-v2",
        "approved-skillopt-policy-v3",
        "Wave 3 cannot begin without explicit external authority",
        "production remains unsupported",
    ):
        assert identity in docs
    assert "python -m pytest -q tests/test_skillopt_observability.py" in docs
