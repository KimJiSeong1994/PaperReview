from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

import pytest

import src.search_eval.accepted_candidate as accepted_candidate_module
import src.search_eval.orchestrator as orchestrator_module
import src.search_eval.skillopt_run_contract as run_contract_module
from src.search_eval.accepted_candidate import (
    load_accepted_skillopt_candidate,
    validate_acceptance_manifest,
)
from src.search_eval.orchestrator import main, run_orchestrator
from src.search_eval.skillopt_contract import ValidationError, canonical_self_hash
from src.search_eval.skillopt_compatibility import seal_identity_artifact
from src.search_eval.skillopt_run_contract import (
    AUTHORITY_CONTEXT_ENV,
    canonical_json_bytes,
    resolve_authority_context,
    seal_run_request,
    seal_run_result,
)
from tests.skillopt_acceptance_fixtures import _entry, _write_json
from tests.test_skillopt_run_contract import _sealed_request, _sealed_result


def _dump(path: Path, value: dict) -> None:
    _write_json(path, value)


def _paths(root: Path) -> tuple[dict, Path, dict, Path]:
    request = _sealed_request(root)
    request_path = root / "incoming-request.json"
    _dump(request_path, request)
    result = _sealed_result(root, request)
    result_path = root / request["output"]["result_manifest_path"]
    _dump(result_path, result)
    return request, request_path, result, result_path


def _paths_for_status(root: Path, status: str) -> tuple[dict, Path, dict, Path]:
    request = _sealed_request(root)
    request_path = root / "incoming-request.json"
    _dump(request_path, request)
    result = _sealed_result(root, request, status=status)
    result_path = root / request["output"]["result_manifest_path"]
    _dump(result_path, result)
    return request, request_path, result, result_path


def _publish_candidate(root: Path) -> tuple[dict, Path]:
    _request, request_path, _result, result_path = _paths(root)
    status = run_orchestrator(
        run_root=root,
        request_path=request_path,
        import_result_path=result_path,
    )
    assert status["state"] == "candidate_ready", status
    return status, Path(status["acceptance_manifest_path"])


def _reseal_result(result: dict) -> dict:
    payload = copy.deepcopy(result)
    payload.pop("result_id", None)
    return seal_run_result(payload)


def _rotate_authority_context(
    root: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> tuple[Path, str]:
    current_path = Path(os.environ[AUTHORITY_CONTEXT_ENV])
    context = json.loads(current_path.read_bytes())
    if kind == "namespace_and_root":
        rotated_root = root.parent / f"{root.name}-rotated-authority"
        _sealed_request(rotated_root)
        rotated = resolve_authority_context()
        return rotated.coordinator_root, rotated.coordinator_namespace
    if kind == "root_only":
        coordinator_root = root / "rotated-coordinator-root"
        coordinator_root.mkdir(parents=True)
        context["coordinator_root"] = str(coordinator_root.resolve())
    elif kind == "policy_only":
        policy_path = Path(context["trusted_policy"]["path"])
        policy = json.loads(policy_path.read_bytes())
        policy["policy_name"] = "rotated exact-byte fixture authority"
        policy = seal_identity_artifact(policy, policy["version"])
        rotated_policy_path = root / "rotated-trusted-authority-policy.json"
        _dump(rotated_policy_path, policy)
        policy_bytes = rotated_policy_path.read_bytes()
        context["trusted_policy"] = {
            "path": str(rotated_policy_path.resolve()),
            "identity": policy["identity"],
            "sha256": "sha256:" + hashlib.sha256(policy_bytes).hexdigest(),
            "size_bytes": len(policy_bytes),
        }
    else:
        raise AssertionError(f"unknown authority rotation kind: {kind}")
    rotated_context_path = root / f"rotated-{kind}-authority-context.json"
    _dump(rotated_context_path, context)
    monkeypatch.setenv(AUTHORITY_CONTEXT_ENV, str(rotated_context_path.resolve()))
    return Path(context["coordinator_root"]), str(context["coordinator_namespace"])


def _consumption_record(root: Path, namespace: str, request_id: str) -> Path:
    return root / "namespaces" / namespace / "consumed" / f"{request_id}.json"


def _lifecycle_bytes(root: Path) -> dict[str, bytes]:
    return {
        "status": (root / "status.json").read_bytes(),
        "journal": (root / "stage_journal.json").read_bytes(),
        "heartbeat": (root / "heartbeat.json").read_bytes(),
    }


TERMINAL_IMPORT_CASES = (
    ("succeeded", "candidate_ready"),
    ("failed", "failed"),
    ("timed_out", "timed_out"),
    ("cancelled", "cancelled"),
)


def test_dry_run_is_credential_free_idempotent_and_journaled(tmp_path: Path):
    request = _sealed_request(tmp_path)
    request_path = tmp_path / "request.json"
    _dump(request_path, request)
    first = run_orchestrator(run_root=tmp_path, request_path=request_path, dry_run=True)
    second = run_orchestrator(
        run_root=tmp_path, request_path=request_path, dry_run=True
    )
    assert first == second
    assert first["state"] == "dry_run_complete"
    journal = json.loads((tmp_path / "stage_journal.json").read_bytes())
    assert [event["state"] for event in journal["events"]] == [
        "requested",
        "running",
        "dry_run_complete",
    ]
    assert not (tmp_path / "artifacts/run_result.json").exists()


def test_stable_run_root_lock_serializes_dry_run_rotation_then_new_authority_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request = _sealed_request(tmp_path)
    request_path = tmp_path / "request.json"
    _dump(request_path, request)
    initial = resolve_authority_context()
    rotation_done = Event()
    retry_calling = Event()
    retry_entered = Event()
    allow_retry = Event()
    rotated_location: tuple[Path, str] | None = None
    lifecycle_before_rotation: dict[str, bytes] | None = None
    original_verify = orchestrator_module.verify_authority_context_current
    original_run_locked = orchestrator_module._run_locked

    def verify_then_rotate(snapshot):
        nonlocal rotated_location, lifecycle_before_rotation
        if snapshot == initial and rotated_location is None:
            lifecycle_before_rotation = _lifecycle_bytes(tmp_path)
            rotated_location = _rotate_authority_context(
                tmp_path, monkeypatch, "root_only"
            )
            rotation_done.set()
            assert retry_calling.wait(5)
            assert not retry_entered.wait(0.2)
        return original_verify(snapshot)

    def observe_new_authority_entry(**kwargs):
        if (
            rotated_location is not None
            and kwargs["authority_context"].coordinator_root == rotated_location[0]
        ):
            retry_entered.set()
            assert allow_retry.wait(5)
        return original_run_locked(**kwargs)

    def retry_under_rotated_authority():
        retry_calling.set()
        return run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            dry_run=True,
        )

    monkeypatch.setattr(
        orchestrator_module, "verify_authority_context_current", verify_then_rotate
    )
    monkeypatch.setattr(orchestrator_module, "_run_locked", observe_new_authority_entry)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rotating = pool.submit(
            run_orchestrator,
            run_root=tmp_path,
            request_path=request_path,
            dry_run=True,
        )
        assert rotation_done.wait(5)
        retrying = pool.submit(retry_under_rotated_authority)
        with pytest.raises(orchestrator_module.AuthorityContextRotationError):
            rotating.result(timeout=5)
        assert retry_entered.wait(5)
        try:
            assert lifecycle_before_rotation is not None
            assert _lifecycle_bytes(tmp_path) == lifecycle_before_rotation
            assert not (tmp_path / "quarantine").exists()
            old_incidents = list(
                (
                    initial.coordinator_root
                    / "namespaces"
                    / initial.coordinator_namespace
                    / "incidents"
                ).glob("*.json")
            )
            assert len(old_incidents) == 1
            assert (
                "authority rotation during dry-run terminal transaction"
                in json.loads(old_incidents[0].read_bytes())["reason"]
            )
            assert rotated_location is not None
            assert not list(
                (
                    rotated_location[0]
                    / "namespaces"
                    / rotated_location[1]
                    / "incidents"
                ).glob("*.json")
            )
        finally:
            allow_retry.set()
        status = retrying.result(timeout=5)

    assert status["state"] == "dry_run_complete"
    assert [
        event["state"]
        for event in json.loads((tmp_path / "stage_journal.json").read_bytes())[
            "events"
        ]
    ] == ["requested", "running", "dry_run_complete"]
    assert not (tmp_path / "quarantine").exists()


def test_exact_import_and_accepted_candidate_load(tmp_path: Path):
    request, request_path, result, result_path = _paths(tmp_path)
    status = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        import_result_path=result_path,
    )
    candidate = load_accepted_skillopt_candidate(
        acceptance_manifest_path=status["acceptance_manifest_path"],
        run_root=tmp_path,
    )
    assert status["state"] == "candidate_ready"
    assert candidate.request_id == request["request_id"]
    assert candidate.result_id == result["result_id"]
    assert candidate.profile_identity == request["upstream"]["profile_identity"]
    assert candidate.overlay_identity == request["upstream"]["overlay_identity"]
    assert candidate.staging_identity == request["upstream"]["staging_identity"]
    assert candidate.runner_identity == request["upstream"]["runner_identity"]
    assert candidate.custody_identity == request["upstream"]["custody_identity"]
    assert candidate.usage_receipt_identity.startswith("sha256:")
    assert candidate.privacy_receipt_identity.startswith("sha256:")


@pytest.mark.parametrize(
    "rotation_kind", ["namespace_and_root", "root_only", "policy_only"]
)
def test_authority_rotation_before_request_capture_fails_without_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rotation_kind: str,
):
    request, request_path, _result, result_path = _paths(tmp_path)
    initial = resolve_authority_context()
    rotated_location: tuple[Path, str] | None = None
    original_capture = orchestrator_module.capture_run_request

    def rotate_then_capture(*args, **kwargs):
        nonlocal rotated_location
        assert kwargs["authority_context"] == initial
        rotated_location = _rotate_authority_context(
            tmp_path, monkeypatch, rotation_kind
        )
        return original_capture(*args, **kwargs)

    monkeypatch.setattr(orchestrator_module, "capture_run_request", rotate_then_capture)
    with pytest.raises(orchestrator_module.AuthorityContextRotationError):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )

    assert rotated_location is not None
    initial_record = _consumption_record(
        initial.coordinator_root,
        initial.coordinator_namespace,
        request["request_id"],
    )
    rotated_record = _consumption_record(
        rotated_location[0], rotated_location[1], request["request_id"]
    )
    assert not initial_record.exists()
    assert not rotated_record.exists()
    assert json.loads((tmp_path / "status.json").read_bytes())["state"] == "running"
    assert not (tmp_path / "quarantine").exists()
    manifest_path = tmp_path / "artifacts" / "acceptance_manifest.json"
    assert manifest_path.is_file()
    monkeypatch.setattr(orchestrator_module, "capture_run_request", original_capture)
    with pytest.raises(ValidationError):
        load_accepted_skillopt_candidate(
            acceptance_manifest_path=manifest_path,
            run_root=tmp_path,
        )


def test_authority_rotation_after_record_write_rolls_back_without_quarantine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request, request_path, _result, result_path = _paths(tmp_path)
    initial = resolve_authority_context()
    record_path = _consumption_record(
        initial.coordinator_root,
        initial.coordinator_namespace,
        request["request_id"],
    )
    original_write = orchestrator_module._write_json_atomic
    rotated_location: tuple[Path, str] | None = None

    def write_then_rotate(path, value):
        nonlocal rotated_location
        original_write(path, value)
        if path == record_path:
            rotated_location = _rotate_authority_context(
                tmp_path, monkeypatch, "root_only"
            )

    monkeypatch.setattr(orchestrator_module, "_write_json_atomic", write_then_rotate)
    with pytest.raises(orchestrator_module.AuthorityContextRotationError):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )

    assert rotated_location is not None
    assert not record_path.exists()
    assert not _consumption_record(
        rotated_location[0], rotated_location[1], request["request_id"]
    ).exists()
    assert json.loads((tmp_path / "status.json").read_bytes())["state"] == "running"
    assert not (tmp_path / "quarantine").exists()
    with pytest.raises(ValidationError):
        load_accepted_skillopt_candidate(
            acceptance_manifest_path=tmp_path
            / "artifacts"
            / "acceptance_manifest.json",
            run_root=tmp_path,
        )


def test_malformed_run_result_quarantine_rotation_restores_lifecycle_and_removes_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request, request_path, _result, result_path = _paths(tmp_path)
    dry_run_status = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        dry_run=True,
    )
    assert dry_run_status["state"] == "dry_run_complete"
    lifecycle_before = _lifecycle_bytes(tmp_path)
    initial = resolve_authority_context()
    quarantine_path = tmp_path / "quarantine" / "run_result.json.metadata.json"
    assert not quarantine_path.parent.exists()

    result_path.write_bytes(b"not-json")
    original_write = orchestrator_module._write_json_atomic
    rotated_location: tuple[Path, str] | None = None

    def write_then_rotate(path, value):
        nonlocal rotated_location
        original_write(path, value)
        if path == quarantine_path and rotated_location is None:
            rotated_location = _rotate_authority_context(
                tmp_path, monkeypatch, "root_only"
            )

    monkeypatch.setattr(orchestrator_module, "_write_json_atomic", write_then_rotate)
    with pytest.raises(orchestrator_module.AuthorityContextRotationError):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )

    assert rotated_location is not None
    assert _lifecycle_bytes(tmp_path) == lifecycle_before
    assert not quarantine_path.exists()
    assert not quarantine_path.parent.exists()
    old_incidents = list(
        (
            initial.coordinator_root
            / "namespaces"
            / initial.coordinator_namespace
            / "incidents"
        ).glob("*.json")
    )
    assert len(old_incidents) == 1
    assert (
        "authority rotation during run_result.json quarantine terminal transaction"
        in json.loads(old_incidents[0].read_bytes())["reason"]
    )
    assert not list(
        (rotated_location[0] / "namespaces" / rotated_location[1] / "incidents").glob(
            "*.json"
        )
    )


def test_authority_rotation_rollback_preserves_same_byte_new_root_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request, request_path, _result, result_path = _paths(tmp_path)
    initial = resolve_authority_context()
    old_record_path = _consumption_record(
        initial.coordinator_root,
        initial.coordinator_namespace,
        request["request_id"],
    )
    original_heartbeat = orchestrator_module._heartbeat
    rotated_record_path: Path | None = None
    winner_bytes: bytes | None = None

    def heartbeat_then_commit_rotated_winner(root, request_id, request_sha256, state):
        nonlocal rotated_record_path, winner_bytes
        original_heartbeat(root, request_id, request_sha256, state)
        if state == "candidate_ready" and rotated_record_path is None:
            rotated_root, rotated_namespace = _rotate_authority_context(
                tmp_path, monkeypatch, "root_only"
            )
            rotated_record_path = _consumption_record(
                rotated_root, rotated_namespace, request["request_id"]
            )
            winner_bytes = old_record_path.read_bytes()
            orchestrator_module._write_bytes_atomic(rotated_record_path, winner_bytes)

    monkeypatch.setattr(
        orchestrator_module, "_heartbeat", heartbeat_then_commit_rotated_winner
    )
    with pytest.raises(orchestrator_module.AuthorityContextRotationError):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )

    assert not old_record_path.exists()
    assert rotated_record_path is not None
    assert winner_bytes is not None
    assert rotated_record_path.read_bytes() == winner_bytes
    assert json.loads((tmp_path / "status.json").read_bytes())["state"] == "running"
    assert not (tmp_path / "quarantine").exists()


def test_authority_rotation_at_terminal_commit_rolls_back_without_quarantine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request, request_path, _result, result_path = _paths(tmp_path)
    initial = resolve_authority_context()
    record_path = _consumption_record(
        initial.coordinator_root,
        initial.coordinator_namespace,
        request["request_id"],
    )
    original_transition = orchestrator_module._transition
    rotated_location: tuple[Path, str] | None = None

    def rotate_before_terminal(**kwargs):
        nonlocal rotated_location
        if kwargs.get("state") == "candidate_ready":
            rotated_location = _rotate_authority_context(
                tmp_path, monkeypatch, "root_only"
            )
        return original_transition(**kwargs)

    monkeypatch.setattr(orchestrator_module, "_transition", rotate_before_terminal)
    with pytest.raises(orchestrator_module.AuthorityContextRotationError):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )

    assert rotated_location is not None
    assert not record_path.exists()
    assert not _consumption_record(
        rotated_location[0], rotated_location[1], request["request_id"]
    ).exists()
    assert json.loads((tmp_path / "status.json").read_bytes())["state"] == "running"
    assert not (tmp_path / "quarantine").exists()


@pytest.mark.parametrize(("result_status", "terminal_state"), TERMINAL_IMPORT_CASES)
def test_authority_rotation_after_final_lifecycle_write_rolls_back_terminal_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result_status: str,
    terminal_state: str,
):
    request, request_path, _result, result_path = _paths_for_status(
        tmp_path, result_status
    )
    initial = resolve_authority_context()
    record_path = _consumption_record(
        initial.coordinator_root,
        initial.coordinator_namespace,
        request["request_id"],
    )
    original_heartbeat = orchestrator_module._heartbeat
    rotated_location: tuple[Path, str] | None = None

    def heartbeat_then_rotate(root, request_id, request_sha256, state):
        nonlocal rotated_location
        original_heartbeat(root, request_id, request_sha256, state)
        if state == terminal_state and rotated_location is None:
            rotated_location = _rotate_authority_context(
                tmp_path, monkeypatch, "root_only"
            )

    monkeypatch.setattr(orchestrator_module, "_heartbeat", heartbeat_then_rotate)
    with pytest.raises(orchestrator_module.AuthorityContextRotationError):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )

    assert rotated_location is not None
    assert not record_path.exists()
    assert not _consumption_record(
        rotated_location[0], rotated_location[1], request["request_id"]
    ).exists()
    assert json.loads((tmp_path / "status.json").read_bytes())["state"] == "running"
    assert json.loads((tmp_path / "heartbeat.json").read_bytes())["state"] == "running"
    assert not (tmp_path / "quarantine").exists()


def test_stable_run_root_lock_serializes_rotation_then_new_authority_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request, request_path, result, result_path = _paths(tmp_path)
    initial = resolve_authority_context()
    old_record_path = _consumption_record(
        initial.coordinator_root,
        initial.coordinator_namespace,
        request["request_id"],
    )
    rotation_done = Event()
    retry_calling = Event()
    retry_entered = Event()
    rotated_location: tuple[Path, str] | None = None
    original_heartbeat = orchestrator_module._heartbeat
    original_run_locked = orchestrator_module._run_locked

    def heartbeat_then_rotate(root, request_id, request_sha256, state):
        nonlocal rotated_location
        original_heartbeat(root, request_id, request_sha256, state)
        if state == "candidate_ready" and rotated_location is None:
            rotated_location = _rotate_authority_context(
                tmp_path, monkeypatch, "root_only"
            )
            rotation_done.set()
            assert retry_calling.wait(5)
            assert not retry_entered.wait(0.2)

    def observe_new_authority_entry(**kwargs):
        if (
            rotated_location is not None
            and kwargs["authority_context"].coordinator_root == rotated_location[0]
        ):
            retry_entered.set()
        return original_run_locked(**kwargs)

    def retry_under_rotated_authority():
        retry_calling.set()
        return run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )

    monkeypatch.setattr(orchestrator_module, "_heartbeat", heartbeat_then_rotate)
    monkeypatch.setattr(orchestrator_module, "_run_locked", observe_new_authority_entry)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rotating = pool.submit(
            run_orchestrator,
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )
        assert rotation_done.wait(5)
        retrying = pool.submit(retry_under_rotated_authority)
        with pytest.raises(orchestrator_module.AuthorityContextRotationError):
            rotating.result(timeout=5)
        status = retrying.result(timeout=5)

    assert rotated_location is not None
    assert retry_entered.is_set()
    assert status["state"] == "candidate_ready"
    assert not old_record_path.exists()
    new_record_path = _consumption_record(
        rotated_location[0], rotated_location[1], request["request_id"]
    )
    assert new_record_path.is_file()
    assert json.loads(new_record_path.read_bytes())["state"] == "candidate_ready"
    assert [
        event["state"]
        for event in json.loads((tmp_path / "stage_journal.json").read_bytes())[
            "events"
        ]
    ] == ["requested", "running", "candidate_ready"]
    assert not (tmp_path / "quarantine").exists()
    incidents = list(
        (
            initial.coordinator_root
            / "namespaces"
            / initial.coordinator_namespace
            / "incidents"
        ).glob("*.json")
    )
    assert len(incidents) == 1
    assert (
        "authority rotation during import terminal transaction"
        in json.loads(incidents[0].read_bytes())["reason"]
    )
    candidate = load_accepted_skillopt_candidate(
        acceptance_manifest_path=status["acceptance_manifest_path"],
        run_root=tmp_path,
    )
    assert candidate.request_id == request["request_id"]
    assert candidate.result_id == result["result_id"]


def test_accepted_load_revalidates_authority_evidence_at_actual_use_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _status, manifest_path = _publish_candidate(tmp_path)
    real_datetime = datetime

    class FutureDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.now(timezone.utc) + timedelta(days=2)

    monkeypatch.setattr(run_contract_module, "datetime", FutureDateTime)
    with pytest.raises(ValidationError, match="custody_evidence is not valid"):
        load_accepted_skillopt_candidate(
            acceptance_manifest_path=manifest_path,
            run_root=tmp_path,
        )


@pytest.mark.parametrize("rotation_kind", ["root_only", "policy_only"])
@pytest.mark.parametrize(
    "phase", ["request_capture", "record_validation", "final_assertion"]
)
def test_accepted_load_fails_closed_on_authority_rotation_without_mixed_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rotation_kind: str,
    phase: str,
):
    _status, manifest_path = _publish_candidate(tmp_path)
    initial = resolve_authority_context()
    rotated_location: tuple[Path, str] | None = None
    original_capture = accepted_candidate_module.capture_run_request
    original_publication = accepted_candidate_module._validate_coordinator_publication
    original_verify = accepted_candidate_module.verify_authority_context_current

    def rotate_once():
        nonlocal rotated_location
        if rotated_location is None:
            rotated_location = _rotate_authority_context(
                tmp_path, monkeypatch, rotation_kind
            )

    def rotate_during_capture(*args, **kwargs):
        assert kwargs["authority_context"] == initial
        rotate_once()
        return original_capture(*args, **kwargs)

    def rotate_during_publication(*args, **kwargs):
        assert kwargs["authority_context"] == initial
        rotate_once()
        return original_publication(*args, **kwargs)

    def rotate_during_final_verify(snapshot):
        assert snapshot == initial
        rotate_once()
        return original_verify(snapshot)

    if phase == "request_capture":
        monkeypatch.setattr(
            accepted_candidate_module, "capture_run_request", rotate_during_capture
        )
    elif phase == "record_validation":
        monkeypatch.setattr(
            accepted_candidate_module,
            "_validate_coordinator_publication",
            rotate_during_publication,
        )
    elif phase == "final_assertion":
        monkeypatch.setattr(
            accepted_candidate_module,
            "verify_authority_context_current",
            rotate_during_final_verify,
        )
    else:
        raise AssertionError(f"unknown phase: {phase}")

    with pytest.raises(orchestrator_module.AuthorityContextRotationError):
        load_accepted_skillopt_candidate(
            acceptance_manifest_path=manifest_path,
            run_root=tmp_path,
        )

    assert rotated_location is not None
    request = json.loads((tmp_path / "incoming-request.json").read_bytes())
    old_record = _consumption_record(
        initial.coordinator_root,
        initial.coordinator_namespace,
        request["request_id"],
    )
    rotated_record = _consumption_record(
        rotated_location[0], rotated_location[1], request["request_id"]
    )
    assert old_record.exists()
    if rotated_record != old_record:
        assert not rotated_record.exists()


def test_identical_replay_has_no_duplicate_journal_or_manifest(tmp_path: Path):
    request, request_path, _result, result_path = _paths(tmp_path)
    first = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        import_result_path=result_path,
    )
    manifest_before = Path(first["acceptance_manifest_path"]).read_bytes()
    journal_before = (tmp_path / "stage_journal.json").read_bytes()
    record = (
        resolve_authority_context().coordinator_root
        / "namespaces"
        / request["authority"]["coordinator_namespace"]
        / "consumed"
        / f"{request['request_id']}.json"
    )
    record_before = record.read_bytes()
    second = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        import_result_path=result_path,
    )
    assert second == first
    assert Path(first["acceptance_manifest_path"]).read_bytes() == manifest_before
    assert (tmp_path / "stage_journal.json").read_bytes() == journal_before
    assert record.read_bytes() == record_before


def test_per_call_coordinator_root_is_forbidden(tmp_path: Path):
    _request, request_path, _result, result_path = _paths(tmp_path)
    with pytest.raises(ValidationError, match="per-call coordinator_root is forbidden"):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
            coordinator_root=tmp_path / "caller-selected-coordinator",
        )


def test_crash_after_consumption_record_recovers_terminal_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request, request_path, _result, result_path = _paths(tmp_path)
    original_transition = orchestrator_module._transition

    def crash_before_terminal(**kwargs):
        if kwargs.get("state") == "candidate_ready":
            raise RuntimeError("fault after durable consumption record")
        return original_transition(**kwargs)

    monkeypatch.setattr(orchestrator_module, "_transition", crash_before_terminal)
    with pytest.raises(RuntimeError, match="fault after durable"):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )
    assert json.loads((tmp_path / "status.json").read_bytes())["state"] == "running"
    record_path = (
        resolve_authority_context().coordinator_root
        / "namespaces"
        / request["authority"]["coordinator_namespace"]
        / "consumed"
        / f"{request['request_id']}.json"
    )
    record_before = record_path.read_bytes()
    manifest_path = tmp_path / "artifacts" / "acceptance_manifest.json"
    manifest_before = manifest_path.read_bytes()

    monkeypatch.setattr(orchestrator_module, "_transition", original_transition)
    recovered = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        import_result_path=result_path,
    )
    replay = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        import_result_path=result_path,
    )
    journal = json.loads((tmp_path / "stage_journal.json").read_bytes())
    assert recovered["state"] == "candidate_ready"
    assert recovered["terminal"] is True
    assert replay == recovered
    assert [event["state"] for event in journal["events"]] == [
        "requested",
        "running",
        "candidate_ready",
    ]
    assert record_path.read_bytes() == record_before
    assert manifest_path.read_bytes() == manifest_before
    assert not (tmp_path / "reward_memory.jsonl").exists()


def test_crash_after_terminal_journal_recovers_status_and_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request, request_path, _result, result_path = _paths(tmp_path)
    original_write = orchestrator_module._write_json_atomic
    journal_path = tmp_path / "stage_journal.json"

    def write_then_crash(path, value):
        original_write(path, value)
        if (
            path == journal_path
            and value.get("events")
            and value["events"][-1].get("state") == "candidate_ready"
        ):
            raise RuntimeError("fault after terminal journal")

    monkeypatch.setattr(orchestrator_module, "_write_json_atomic", write_then_crash)
    with pytest.raises(RuntimeError, match="terminal journal"):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )
    assert (
        json.loads((tmp_path / "stage_journal.json").read_bytes())["events"][-1][
            "state"
        ]
        == "candidate_ready"
    )
    assert json.loads((tmp_path / "status.json").read_bytes())["state"] == "running"
    assert json.loads((tmp_path / "heartbeat.json").read_bytes())["state"] == "running"

    monkeypatch.setattr(orchestrator_module, "_write_json_atomic", original_write)
    recovered = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        import_result_path=result_path,
    )
    replay = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        import_result_path=result_path,
    )

    assert recovered["state"] == "candidate_ready"
    assert replay == recovered
    assert json.loads((tmp_path / "status.json").read_bytes())["state"] == (
        "candidate_ready"
    )
    assert json.loads((tmp_path / "heartbeat.json").read_bytes())["state"] == (
        "candidate_ready"
    )
    assert [
        event["state"] for event in json.loads(journal_path.read_bytes())["events"]
    ] == [
        "requested",
        "running",
        "candidate_ready",
    ]


def test_terminal_journal_partial_rejects_impossible_heartbeat_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request, request_path, _result, result_path = _paths(tmp_path)
    original_write = orchestrator_module._write_json_atomic
    journal_path = tmp_path / "stage_journal.json"

    def write_then_crash(path, value):
        original_write(path, value)
        if (
            path == journal_path
            and value.get("events")
            and value["events"][-1].get("state") == "candidate_ready"
        ):
            raise RuntimeError("fault after terminal journal")

    monkeypatch.setattr(orchestrator_module, "_write_json_atomic", write_then_crash)
    with pytest.raises(RuntimeError, match="terminal journal"):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )
    heartbeat_path = tmp_path / "heartbeat.json"
    heartbeat = json.loads(heartbeat_path.read_bytes())
    heartbeat["state"] = "cancelled"
    _dump(heartbeat_path, heartbeat)
    lifecycle_before = _lifecycle_bytes(tmp_path)

    monkeypatch.setattr(orchestrator_module, "_write_json_atomic", original_write)
    with pytest.raises(ValidationError, match="heartbeat state cannot be repaired"):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )

    assert _lifecycle_bytes(tmp_path) == lifecycle_before


def test_crash_after_terminal_status_recovers_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request, request_path, _result, result_path = _paths(tmp_path)
    original_write = orchestrator_module._write_json_atomic
    status_path = tmp_path / "status.json"

    def write_then_crash(path, value):
        original_write(path, value)
        if path == status_path and value.get("state") == "candidate_ready":
            raise RuntimeError("fault after terminal status")

    monkeypatch.setattr(orchestrator_module, "_write_json_atomic", write_then_crash)
    with pytest.raises(RuntimeError, match="terminal status"):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )
    assert (
        json.loads((tmp_path / "stage_journal.json").read_bytes())["events"][-1][
            "state"
        ]
        == "candidate_ready"
    )
    assert json.loads((tmp_path / "status.json").read_bytes())["state"] == (
        "candidate_ready"
    )
    assert json.loads((tmp_path / "heartbeat.json").read_bytes())["state"] == (
        "running"
    )

    monkeypatch.setattr(orchestrator_module, "_write_json_atomic", original_write)
    recovered = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        import_result_path=result_path,
    )

    assert recovered["state"] == "candidate_ready"
    assert json.loads((tmp_path / "heartbeat.json").read_bytes())["state"] == (
        "candidate_ready"
    )


def test_impossible_terminal_lifecycle_state_is_quarantined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    request, request_path, _result, result_path = _paths(tmp_path)
    original_transition = orchestrator_module._transition

    def crash_before_terminal(**kwargs):
        if kwargs.get("state") == "candidate_ready":
            raise RuntimeError("fault after durable consumption record")
        return original_transition(**kwargs)

    monkeypatch.setattr(orchestrator_module, "_transition", crash_before_terminal)
    with pytest.raises(RuntimeError):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )
    journal_path = tmp_path / "stage_journal.json"
    journal = json.loads(journal_path.read_bytes())
    journal["events"].append(
        {
            "sequence": 3,
            "old_state": "running",
            "state": "cancelled",
            "at": "2026-07-20T00:00:00Z",
            "reason": "impossible partial",
            "request_sha256": journal["events"][-1]["request_sha256"],
            "result_sha256": None,
        }
    )
    _dump(journal_path, journal)
    monkeypatch.setattr(orchestrator_module, "_transition", original_transition)

    status = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        import_result_path=result_path,
    )

    assert status["state"] == "quarantined"
    assert "impossible lifecycle journal" in status["reason"]


def test_inconsistent_crash_partial_is_quarantined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _request, request_path, _result, result_path = _paths(tmp_path)
    original_transition = orchestrator_module._transition

    def crash_before_terminal(**kwargs):
        if kwargs.get("state") == "candidate_ready":
            raise RuntimeError("fault after durable consumption record")
        return original_transition(**kwargs)

    monkeypatch.setattr(orchestrator_module, "_transition", crash_before_terminal)
    with pytest.raises(RuntimeError):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )
    manifest_path = tmp_path / "artifacts" / "acceptance_manifest.json"
    manifest_path.write_bytes(manifest_path.read_bytes() + b"x")
    monkeypatch.setattr(orchestrator_module, "_transition", original_transition)
    status = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        import_result_path=result_path,
    )
    assert status["state"] == "quarantined"
    assert "inconsistent durable consumption record" in status["reason"]


def test_malformed_replay_preserves_prior_candidate_ready_lifecycle(tmp_path: Path):
    status, _manifest = _publish_candidate(tmp_path)
    request = json.loads((tmp_path / "incoming-request.json").read_bytes())
    result_path = tmp_path / request["output"]["result_manifest_path"]
    result_path.write_bytes(b"not-json")
    replay = run_orchestrator(
        run_root=tmp_path,
        request_path=tmp_path / "incoming-request.json",
        import_result_path=result_path,
    )
    namespace_root = (
        resolve_authority_context().coordinator_root
        / "namespaces"
        / request["authority"]["coordinator_namespace"]
    )
    incidents = list((namespace_root / "incidents").glob("*.json"))
    assert replay == status
    assert json.loads((tmp_path / "status.json").read_bytes())["state"] == (
        "candidate_ready"
    )
    assert len(incidents) == 1
    assert (
        "malformed replay import ignored"
        in json.loads(incidents[0].read_bytes())["reason"]
    )


@pytest.mark.parametrize(("result_status", "terminal_state"), TERMINAL_IMPORT_CASES)
def test_consumed_terminal_replay_with_original_evidence_drift_preserves_lifecycle(
    tmp_path: Path, result_status: str, terminal_state: str
):
    request, request_path, _result, result_path = _paths_for_status(
        tmp_path, result_status
    )
    status = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        import_result_path=result_path,
    )
    assert status["state"] == terminal_state
    context = resolve_authority_context()
    record_path = _consumption_record(
        context.coordinator_root,
        context.coordinator_namespace,
        request["request_id"],
    )
    record_before = record_path.read_bytes()
    lifecycle_before = _lifecycle_bytes(tmp_path)
    dataset_path = tmp_path / request["input_artifacts"]["dataset"]["path"]
    dataset_path.write_bytes(dataset_path.read_bytes() + b"x")

    replay = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        import_result_path=result_path,
    )

    namespace_root = (
        context.coordinator_root
        / "namespaces"
        / request["authority"]["coordinator_namespace"]
    )
    incidents = list((namespace_root / "incidents").glob("*.json"))
    assert replay == status
    assert replay["state"] == terminal_state
    assert _lifecycle_bytes(tmp_path) == lifecycle_before
    assert record_path.read_bytes() == record_before
    assert len(incidents) == 1
    assert (
        "original source evidence drift after consumption: dataset"
        in json.loads(incidents[0].read_bytes())["reason"]
    )


def test_malformed_replay_recovery_failure_does_not_mutate_lifecycle(
    tmp_path: Path,
):
    _status, _manifest = _publish_candidate(tmp_path)
    request = json.loads((tmp_path / "incoming-request.json").read_bytes())
    context = resolve_authority_context()
    record_path = _consumption_record(
        context.coordinator_root,
        request["authority"]["coordinator_namespace"],
        request["request_id"],
    )
    record_before = record_path.read_bytes()
    heartbeat_path = tmp_path / "heartbeat.json"
    heartbeat = json.loads(heartbeat_path.read_bytes())
    heartbeat["state"] = "quarantined"
    _dump(heartbeat_path, heartbeat)
    lifecycle_before = _lifecycle_bytes(tmp_path)
    result_path = tmp_path / request["output"]["result_manifest_path"]
    result_path.write_bytes(b"not-json")

    with pytest.raises(ValidationError, match="heartbeat state cannot be repaired"):
        run_orchestrator(
            run_root=tmp_path,
            request_path=tmp_path / "incoming-request.json",
            import_result_path=result_path,
        )

    namespace_root = (
        context.coordinator_root
        / "namespaces"
        / request["authority"]["coordinator_namespace"]
    )
    incidents = list((namespace_root / "incidents").glob("*.json"))
    assert _lifecycle_bytes(tmp_path) == lifecycle_before
    assert record_path.read_bytes() == record_before
    assert len(incidents) == 1
    assert (
        "inconsistent durable consumption record after malformed replay"
        in (json.loads(incidents[0].read_bytes())["reason"])
    )


def test_consumed_replay_authority_rotation_records_incident_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    status, _manifest = _publish_candidate(tmp_path)
    request = json.loads((tmp_path / "incoming-request.json").read_bytes())
    result_path = tmp_path / request["output"]["result_manifest_path"]
    initial = resolve_authority_context()
    record_path = _consumption_record(
        initial.coordinator_root,
        initial.coordinator_namespace,
        request["request_id"],
    )
    record_before = record_path.read_bytes()
    lifecycle_before = _lifecycle_bytes(tmp_path)
    original_repair = orchestrator_module._repair_terminal_heartbeat
    rotated_location: tuple[Path, str] | None = None

    def repair_then_rotate(**kwargs):
        nonlocal rotated_location
        original_repair(**kwargs)
        rotated_location = _rotate_authority_context(tmp_path, monkeypatch, "root_only")

    monkeypatch.setattr(
        orchestrator_module, "_repair_terminal_heartbeat", repair_then_rotate
    )
    with pytest.raises(orchestrator_module.AuthorityContextRotationError):
        run_orchestrator(
            run_root=tmp_path,
            request_path=tmp_path / "incoming-request.json",
            import_result_path=result_path,
        )

    namespace_root = (
        initial.coordinator_root
        / "namespaces"
        / request["authority"]["coordinator_namespace"]
    )
    incidents = list((namespace_root / "incidents").glob("*.json"))
    assert status["state"] == "candidate_ready"
    assert rotated_location is not None
    assert _lifecycle_bytes(tmp_path) == lifecycle_before
    assert record_path.read_bytes() == record_before
    assert not _consumption_record(
        rotated_location[0], rotated_location[1], request["request_id"]
    ).exists()
    assert len(incidents) == 1
    assert (
        "authority rotation during consumed replay"
        in json.loads(incidents[0].read_bytes())["reason"]
    )
    assert record_before


@pytest.mark.parametrize(("result_status", "terminal_state"), TERMINAL_IMPORT_CASES)
def test_authority_rotation_during_terminal_heartbeat_repair_restores_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result_status: str,
    terminal_state: str,
):
    request, request_path, _result, result_path = _paths_for_status(
        tmp_path, result_status
    )
    status = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        import_result_path=result_path,
    )
    assert status["state"] == terminal_state
    initial = resolve_authority_context()
    record_path = _consumption_record(
        initial.coordinator_root,
        initial.coordinator_namespace,
        request["request_id"],
    )
    record_before = record_path.read_bytes()
    heartbeat_path = tmp_path / "heartbeat.json"
    heartbeat = json.loads(heartbeat_path.read_bytes())
    heartbeat["state"] = "running"
    _dump(heartbeat_path, heartbeat)
    lifecycle_before = _lifecycle_bytes(tmp_path)
    original_heartbeat = orchestrator_module._heartbeat
    rotated_location: tuple[Path, str] | None = None

    def heartbeat_then_rotate(root, request_id, request_sha256, state):
        nonlocal rotated_location
        original_heartbeat(root, request_id, request_sha256, state)
        if state == terminal_state and rotated_location is None:
            rotated_location = _rotate_authority_context(
                tmp_path, monkeypatch, "root_only"
            )

    monkeypatch.setattr(orchestrator_module, "_heartbeat", heartbeat_then_rotate)
    with pytest.raises(orchestrator_module.AuthorityContextRotationError):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )

    assert rotated_location is not None
    assert _lifecycle_bytes(tmp_path) == lifecycle_before
    assert record_path.read_bytes() == record_before
    assert not _consumption_record(
        rotated_location[0], rotated_location[1], request["request_id"]
    ).exists()


@pytest.mark.parametrize(("result_status", "terminal_state"), TERMINAL_IMPORT_CASES)
def test_authority_rotation_after_recovery_final_lifecycle_write_restores_partial_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result_status: str,
    terminal_state: str,
):
    request, request_path, _result, result_path = _paths_for_status(
        tmp_path, result_status
    )
    initial = resolve_authority_context()
    record_path = _consumption_record(
        initial.coordinator_root,
        initial.coordinator_namespace,
        request["request_id"],
    )
    original_transition = orchestrator_module._transition

    def crash_before_terminal(**kwargs):
        if kwargs.get("state") == terminal_state:
            raise RuntimeError("fault after durable consumption record")
        return original_transition(**kwargs)

    monkeypatch.setattr(orchestrator_module, "_transition", crash_before_terminal)
    with pytest.raises(RuntimeError, match="fault after durable"):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )
    partial_lifecycle = _lifecycle_bytes(tmp_path)
    record_before = record_path.read_bytes()
    original_heartbeat = orchestrator_module._heartbeat
    rotated_location: tuple[Path, str] | None = None

    def heartbeat_then_rotate(root, request_id, request_sha256, state):
        nonlocal rotated_location
        original_heartbeat(root, request_id, request_sha256, state)
        if state == terminal_state and rotated_location is None:
            rotated_location = _rotate_authority_context(
                tmp_path, monkeypatch, "root_only"
            )

    monkeypatch.setattr(orchestrator_module, "_transition", original_transition)
    monkeypatch.setattr(orchestrator_module, "_heartbeat", heartbeat_then_rotate)
    with pytest.raises(orchestrator_module.AuthorityContextRotationError):
        run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )

    assert rotated_location is not None
    assert _lifecycle_bytes(tmp_path) == partial_lifecycle
    assert record_path.read_bytes() == record_before
    assert not _consumption_record(
        rotated_location[0], rotated_location[1], request["request_id"]
    ).exists()
    assert record_before


def test_same_request_different_result_is_incident_and_quarantined(tmp_path: Path):
    request, request_path, result, result_path = _paths(tmp_path)
    accepted = run_orchestrator(
        run_root=tmp_path, request_path=request_path, import_result_path=result_path
    )
    result["logs"]["stdout_sha256"] = "sha256:" + "9" * 64
    result = _reseal_result(result)
    _dump(result_path, result)
    conflict = run_orchestrator(
        run_root=tmp_path, request_path=request_path, import_result_path=result_path
    )
    assert accepted["state"] == "candidate_ready"
    assert conflict["state"] == "quarantined"
    assert "replay_conflict" in conflict["reason"]
    assert Path(conflict["quarantine_path"]).is_file()


@pytest.mark.parametrize(
    ("conflict_kind", "conflict_reason"),
    (
        ("request_identity", "conflicting request identity"),
        ("action", "consumed import cannot be replaced"),
        ("result_hash", "conflicting result or terminal replacement"),
    ),
)
def test_consumed_conflict_rotation_restores_acceptance_before_new_authority_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conflict_kind: str,
    conflict_reason: str,
):
    request, request_path, result, result_path = _paths(tmp_path)
    accepted = run_orchestrator(
        run_root=tmp_path,
        request_path=request_path,
        import_result_path=result_path,
    )
    assert accepted["state"] == "candidate_ready"
    initial = resolve_authority_context()
    old_record_path = _consumption_record(
        initial.coordinator_root,
        initial.coordinator_namespace,
        request["request_id"],
    )
    record_before = old_record_path.read_bytes()
    lifecycle_before = _lifecycle_bytes(tmp_path)
    valid_request_bytes = request_path.read_bytes()
    valid_result_bytes = result_path.read_bytes()

    if conflict_kind == "request_identity":
        conflicting_record = json.loads(record_before)
        conflicting_record["request_sha256"] = "sha256:" + "0" * 64
        original_load_record = orchestrator_module._load_optional_canonical

        def load_conflicting_record(path):
            if path == old_record_path:
                return conflicting_record
            return original_load_record(path)

        monkeypatch.setattr(
            orchestrator_module, "_load_optional_canonical", load_conflicting_record
        )
        conflict_call = {"import_result_path": result_path}
    elif conflict_kind == "action":
        conflict_call = {"dry_run": True}
    elif conflict_kind == "result_hash":
        conflicting_result = copy.deepcopy(result)
        conflicting_result["logs"]["stdout_sha256"] = "sha256:" + "9" * 64
        _dump(result_path, _reseal_result(conflicting_result))
        conflict_call = {"import_result_path": result_path}
    else:
        raise AssertionError(f"unknown conflict kind: {conflict_kind}")

    rotation_done = Event()
    retry_calling = Event()
    retry_entered = Event()
    allow_retry = Event()
    rotated_location: tuple[Path, str] | None = None
    original_record_incident = orchestrator_module._record_replay_incident
    original_run_locked = orchestrator_module._run_locked

    def rotate_before_conflict_mutation(**kwargs):
        nonlocal rotated_location
        if conflict_reason in kwargs["reason"] and rotated_location is None:
            assert _lifecycle_bytes(tmp_path) == lifecycle_before
            assert old_record_path.read_bytes() == record_before
            rotated_location = _rotate_authority_context(
                tmp_path, monkeypatch, "root_only"
            )
            rotation_done.set()
            assert retry_calling.wait(5)
            assert not retry_entered.wait(0.2)
        return original_record_incident(**kwargs)

    def observe_new_authority_entry(**kwargs):
        if (
            rotated_location is not None
            and kwargs["authority_context"].coordinator_root == rotated_location[0]
        ):
            retry_entered.set()
            assert allow_retry.wait(5)
        return original_run_locked(**kwargs)

    def retry_valid_import_under_rotated_authority():
        request_path.write_bytes(valid_request_bytes)
        result_path.write_bytes(valid_result_bytes)
        retry_calling.set()
        return run_orchestrator(
            run_root=tmp_path,
            request_path=request_path,
            import_result_path=result_path,
        )

    monkeypatch.setattr(
        orchestrator_module,
        "_record_replay_incident",
        rotate_before_conflict_mutation,
    )
    monkeypatch.setattr(orchestrator_module, "_run_locked", observe_new_authority_entry)

    with ThreadPoolExecutor(max_workers=2) as pool:
        rotating = pool.submit(
            run_orchestrator,
            run_root=tmp_path,
            request_path=request_path,
            **conflict_call,
        )
        assert rotation_done.wait(5)
        retrying = pool.submit(retry_valid_import_under_rotated_authority)
        with pytest.raises(orchestrator_module.AuthorityContextRotationError):
            rotating.result(timeout=5)
        assert retry_entered.wait(5)
        try:
            assert _lifecycle_bytes(tmp_path) == lifecycle_before
            assert old_record_path.read_bytes() == record_before
            assert not (tmp_path / "quarantine").exists()
            old_incidents = list(
                (
                    initial.coordinator_root
                    / "namespaces"
                    / initial.coordinator_namespace
                    / "incidents"
                ).glob("*.json")
            )
            assert len(old_incidents) == 1
            assert (
                "authority rotation during replay-conflict terminal transaction"
                in (json.loads(old_incidents[0].read_bytes())["reason"])
            )
            assert conflict_reason not in old_incidents[0].read_text()
            assert rotated_location is not None
            assert not list(
                (
                    rotated_location[0]
                    / "namespaces"
                    / rotated_location[1]
                    / "incidents"
                ).glob("*.json")
            )
        finally:
            allow_retry.set()
        replayed = retrying.result(timeout=5)

    assert replayed["state"] == "candidate_ready"
    assert old_record_path.read_bytes() == record_before
    assert rotated_location is not None
    new_record_path = _consumption_record(
        rotated_location[0], rotated_location[1], request["request_id"]
    )
    assert json.loads(new_record_path.read_bytes())["state"] == "candidate_ready"
    candidate = load_accepted_skillopt_candidate(
        acceptance_manifest_path=replayed["acceptance_manifest_path"],
        run_root=tmp_path,
    )
    assert candidate.request_id == request["request_id"]
    assert candidate.result_id == result["result_id"]
    assert not (tmp_path / "quarantine").exists()


def test_same_request_and_result_in_different_root_is_globally_idempotent(
    tmp_path: Path,
):
    first_root = tmp_path / "first" / "run"
    first_root.mkdir(parents=True)
    request, request_path, _result, result_path = _paths(first_root)
    second_root = tmp_path / "second" / "run"
    shutil.copytree(first_root, second_root)
    first = run_orchestrator(
        run_root=first_root,
        request_path=request_path,
        import_result_path=result_path,
    )
    second = run_orchestrator(
        run_root=second_root,
        request_path=second_root / "incoming-request.json",
        import_result_path=second_root / request["output"]["result_manifest_path"],
    )
    assert first["state"] == "candidate_ready"
    assert second == first
    assert not (second_root / "status.json").exists()


def test_terminal_failure_cannot_be_replaced_by_success(tmp_path: Path):
    request = _sealed_request(tmp_path)
    request_path = tmp_path / "request.json"
    _dump(request_path, request)
    failed = _sealed_result(tmp_path, request, status="failed")
    result_path = tmp_path / request["output"]["result_manifest_path"]
    _dump(result_path, failed)
    first = run_orchestrator(
        run_root=tmp_path, request_path=request_path, import_result_path=result_path
    )
    succeeded = _sealed_result(tmp_path, request)
    _dump(result_path, succeeded)
    replacement = run_orchestrator(
        run_root=tmp_path, request_path=request_path, import_result_path=result_path
    )
    assert first["state"] == "failed"
    assert replacement["state"] == "quarantined"
    assert "terminal replacement" in replacement["reason"]


def test_concurrent_different_root_conflict_has_one_winner(tmp_path: Path):
    first_root = tmp_path / "a" / "run"
    first_root.mkdir(parents=True)
    request, first_request, _result, first_result = _paths(first_root)
    second_root = tmp_path / "b" / "run"
    shutil.copytree(first_root, second_root)
    second_result_path = second_root / request["output"]["result_manifest_path"]
    second_result = json.loads(second_result_path.read_bytes())
    second_result["logs"]["stderr_sha256"] = "sha256:" + "8" * 64
    second_result = _reseal_result(second_result)
    _dump(second_result_path, second_result)
    calls = [
        dict(
            run_root=first_root,
            request_path=first_request,
            import_result_path=first_result,
        ),
        dict(
            run_root=second_root,
            request_path=second_root / "incoming-request.json",
            import_result_path=second_result_path,
        ),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda kwargs: run_orchestrator(**kwargs), calls))
    assert sorted(status["state"] for status in statuses) == [
        "candidate_ready",
        "quarantined",
    ]


def test_concurrent_malformed_and_valid_import_has_one_durable_terminal_state(
    tmp_path: Path,
):
    valid_root = tmp_path / "valid" / "run"
    valid_root.mkdir(parents=True)
    request, valid_request, _result, valid_result = _paths(valid_root)
    malformed_root = tmp_path / "malformed" / "run"
    shutil.copytree(valid_root, malformed_root)
    malformed_result = malformed_root / request["output"]["result_manifest_path"]
    malformed_result.write_bytes(b"not-json")
    calls = [
        dict(
            run_root=valid_root,
            request_path=valid_request,
            import_result_path=valid_result,
        ),
        dict(
            run_root=malformed_root,
            request_path=malformed_root / "incoming-request.json",
            import_result_path=malformed_result,
        ),
    ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda kwargs: run_orchestrator(**kwargs), calls))

    context = resolve_authority_context()
    record_path = _consumption_record(
        context.coordinator_root,
        request["authority"]["coordinator_namespace"],
        request["request_id"],
    )
    record = json.loads(record_path.read_bytes())
    valid_status = json.loads((valid_root / "status.json").read_bytes())
    malformed_status_path = malformed_root / "status.json"

    assert record["state"] == "candidate_ready"
    assert valid_status["state"] == "candidate_ready"
    assert sum(status["state"] == "candidate_ready" for status in statuses) >= 1
    assert {status["state"] for status in statuses} <= {
        "candidate_ready",
        "quarantined",
    }
    if malformed_status_path.exists():
        assert json.loads(malformed_status_path.read_bytes())["state"] == (
            "quarantined"
        )


def test_acceptance_manifest_binds_request_result_sizes_and_every_snapshot(
    tmp_path: Path,
):
    status, manifest_path = _publish_candidate(tmp_path)
    manifest = json.loads(manifest_path.read_bytes())
    validate_acceptance_manifest(manifest, run_root=tmp_path)
    assert manifest["bindings"]["request_sha256"] == status["request_sha256"]
    assert manifest["bindings"]["result_sha256"] == status["result_sha256"]
    assert manifest["bindings"]["request_size_bytes"] > 0
    assert manifest["bindings"]["result_size_bytes"] > 0
    assert len(manifest["evidence_snapshots"]) == 16
    assert set(manifest["accepted_receipts"]) == {"usage", "privacy"}


@pytest.mark.parametrize(
    "target",
    [
        "artifacts/run_request.json",
        "artifacts/run_result.json",
        "artifacts/accepted_best_skill.md",
        "artifacts/accepted_evaluation.json",
        "artifacts/accepted_usage_receipt.json",
        "artifacts/evidence/custody_evidence.json",
    ],
)
def test_accepted_candidate_rejects_any_snapshot_change(tmp_path: Path, target: str):
    _status, manifest_path = _publish_candidate(tmp_path)
    path = tmp_path / target
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(ValidationError, match="binding|canonical|content"):
        load_accepted_skillopt_candidate(
            acceptance_manifest_path=manifest_path,
            run_root=tmp_path,
        )


def test_original_outputs_may_change_after_atomic_acceptance(tmp_path: Path):
    status, manifest_path = _publish_candidate(tmp_path)
    request = json.loads((tmp_path / "incoming-request.json").read_bytes())
    (tmp_path / request["output"]["best_skill_path"]).write_text("changed\n")
    candidate = load_accepted_skillopt_candidate(
        acceptance_manifest_path=manifest_path,
        run_root=tmp_path,
    )
    assert candidate.best_skill_bytes != b"changed\n"
    replay = run_orchestrator(
        run_root=tmp_path,
        request_path=tmp_path / "incoming-request.json",
        import_result_path=tmp_path / request["output"]["result_manifest_path"],
    )
    assert replay == status


@pytest.mark.parametrize(
    "name", ["status.json", "stage_journal.json", "heartbeat.json"]
)
def test_accepted_candidate_requires_lifecycle_files(tmp_path: Path, name: str):
    _status, manifest_path = _publish_candidate(tmp_path)
    (tmp_path / name).unlink()
    with pytest.raises(ValidationError, match="file is missing"):
        load_accepted_skillopt_candidate(
            acceptance_manifest_path=manifest_path,
            run_root=tmp_path,
        )


def test_noncanonical_request_and_result_are_quarantined(tmp_path: Path):
    request = _sealed_request(tmp_path)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request, indent=2))
    request_status = run_orchestrator(
        run_root=tmp_path, request_path=request_path, dry_run=True
    )
    assert request_status["state"] == "quarantined"
    assert "canonically" in request_status["reason"]

    other = tmp_path / "other"
    other.mkdir()
    request, request_path, result, result_path = _paths(other)
    result_path.write_text(json.dumps(result, indent=2))
    result_status = run_orchestrator(
        run_root=other,
        request_path=request_path,
        import_result_path=result_path,
    )
    assert result_status["state"] == "quarantined"
    assert "canonically" in result_status["reason"]


@pytest.mark.parametrize("source_kind", ["symlink", "fifo", "oversize"])
def test_failed_request_read_is_bounded_never_reopened_and_has_null_content_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_kind: str,
):
    _sealed_request(tmp_path)
    request_path = tmp_path / f"rejected-{source_kind}.json"
    if source_kind == "symlink":
        target = tmp_path / "symlink-target.json"
        target.write_bytes(b"not-json")
        request_path.symlink_to(target)
    elif source_kind == "fifo":
        os.mkfifo(request_path)
    else:
        request_path.write_bytes(b"x" * (16 * 1024 * 1024 + 1))

    original_read = orchestrator_module.read_stable_file
    source_reads = 0

    def count_source_reads(path, *args, **kwargs):
        nonlocal source_reads
        if Path(path) == request_path:
            source_reads += 1
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(
        orchestrator_module, "read_stable_file", count_source_reads
    )
    status = run_orchestrator(
        run_root=tmp_path, request_path=request_path, dry_run=True
    )
    metadata = json.loads(Path(status["quarantine_path"]).read_bytes())

    assert status["state"] == "quarantined"
    assert source_reads == 1
    assert metadata["source_sha256"] is None
    assert metadata["source_size_bytes"] is None


def test_invalid_request_uses_held_hash_and_size_without_reopening_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _sealed_request(tmp_path)
    request_path = tmp_path / "malformed-request.json"
    payload = b"not-json"
    request_path.write_bytes(payload)
    original_read = orchestrator_module.read_stable_file
    source_reads = 0

    def fail_on_reopen(path, *args, **kwargs):
        nonlocal source_reads
        if Path(path) == request_path:
            source_reads += 1
            if source_reads > 1:
                raise AssertionError("rejected request source was reopened")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(orchestrator_module, "read_stable_file", fail_on_reopen)
    status = run_orchestrator(
        run_root=tmp_path, request_path=request_path, dry_run=True
    )
    metadata = json.loads(Path(status["quarantine_path"]).read_bytes())

    assert status["state"] == "quarantined"
    assert source_reads == 1
    assert metadata["source_sha256"] == (
        "sha256:" + hashlib.sha256(payload).hexdigest()
    )
    assert metadata["source_size_bytes"] == len(payload)


def test_private_raw_log_dataset_is_quarantined_before_request_publication(
    tmp_path: Path,
):
    request = _sealed_request(tmp_path)
    dataset_path = tmp_path / request["input_artifacts"]["dataset"]["path"]
    dataset = json.loads(dataset_path.read_bytes())
    dataset["queries"][0]["query_text"] = "private raw logs user_id"
    dataset["dataset_hash"] = canonical_self_hash(dataset, "dataset_hash")
    _dump(dataset_path, dataset)
    request["input_artifacts"]["dataset"] = _entry(
        tmp_path, dataset_path.relative_to(tmp_path).as_posix()
    )
    request_payload = copy.deepcopy(request)
    request_payload.pop("request_id")
    request = seal_run_request(request_payload)
    request_path = tmp_path / "private-request.json"
    _dump(request_path, request)

    status = run_orchestrator(
        run_root=tmp_path, request_path=request_path, dry_run=True
    )

    assert status["state"] == "quarantined"
    assert "private or raw-log text" in status["reason"]
    assert not (tmp_path / "artifacts" / "run_request.json").exists()


def test_import_path_must_equal_requested_result_path(tmp_path: Path):
    request, request_path, _result, result_path = _paths(tmp_path)
    other = tmp_path / "other-result.json"
    other.write_bytes(result_path.read_bytes())
    status = run_orchestrator(
        run_root=tmp_path, request_path=request_path, import_result_path=other
    )
    assert status["state"] == "quarantined"
    assert "result_manifest_path" in status["reason"]


def test_cancel_is_default_off_and_durable(tmp_path: Path):
    request = _sealed_request(tmp_path)
    request_path = tmp_path / "request.json"
    _dump(request_path, request)
    first = run_orchestrator(run_root=tmp_path, request_path=request_path, cancel=True)
    second = run_orchestrator(run_root=tmp_path, request_path=request_path, cancel=True)
    assert first == second
    assert first["state"] == "cancelled"
    assert not (tmp_path / "artifacts/run_result.json").exists()


def test_cli_dry_run_outputs_status(tmp_path: Path, capsys):
    request = _sealed_request(tmp_path)
    request_path = tmp_path / "request.json"
    _dump(request_path, request)
    code = main(
        ["--run-root", str(tmp_path), "--request", str(request_path), "--dry-run"]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["state"] == "dry_run_complete"


def test_manifest_and_snapshots_are_canonical_exact_bytes(tmp_path: Path):
    _status, manifest_path = _publish_candidate(tmp_path)
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest_path.read_bytes() == canonical_json_bytes(manifest)
    assert (tmp_path / "artifacts/run_request.json").read_bytes() == (
        tmp_path / "incoming-request.json"
    ).read_bytes()
