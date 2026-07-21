from __future__ import annotations

import json
import os
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest

from src.search_eval.orchestrator import main, run_orchestrator
from src.search_eval.skillopt_adapter import canonical_file_hash
from src.search_eval.skillopt_contract import ValidationError
from src.search_eval.skillopt_run_contract import (
    canonical_json_bytes,
    seal_run_request,
    validate_run_request,
)
from tests.skillopt_acceptance_fixtures import sealed_request, sealed_result


def _request_fixture(tmp_path: Path) -> tuple[Path, Path, dict]:
    root = tmp_path / "run"
    request = sealed_request(root)
    request_path = root / "request.json"
    request_path.write_bytes(canonical_json_bytes(request))
    validate_run_request(request, run_root=root)
    return root, request_path, request


def _result_fixture(
    root: Path, request: dict, *, status: str = "succeeded"
) -> tuple[Path, dict]:
    result = sealed_result(root, request, status=status)
    result_path = root / request["output"]["result_manifest_path"]
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_bytes(canonical_json_bytes(result))
    return result_path, result


def _reseal_request(request: dict) -> dict:
    value = deepcopy(request)
    value.pop("request_id")
    return seal_run_request(value)


def test_contract_rejects_extra_and_duplicate_json_keys(tmp_path: Path):
    root, request_path, request = _request_fixture(tmp_path)
    extra = deepcopy(request)
    extra["unexpected"] = True
    extra = _reseal_request(extra)
    with pytest.raises(ValidationError, match="keys mismatch"):
        validate_run_request(extra, run_root=root)

    raw = request_path.read_text(encoding="utf-8")
    duplicate = raw.replace('"version":', '"version": "shadowed", "version":', 1)
    request_path.write_text(duplicate, encoding="utf-8")
    status = run_orchestrator(run_root=root, request_path=request_path, dry_run=True)
    assert status["state"] == "quarantined"


@pytest.mark.parametrize("unsafe_path", ["../escape.json", "/tmp/escape.json"])
def test_request_path_escape_is_quarantined(tmp_path: Path, unsafe_path: str):
    root, request_path, request = _request_fixture(tmp_path)
    request["input_artifacts"]["dataset"]["path"] = unsafe_path
    request = _reseal_request(request)
    request_path.write_bytes(canonical_json_bytes(request))
    status = run_orchestrator(run_root=root, request_path=request_path, dry_run=True)
    assert status["state"] == "quarantined"
    assert "invalid_request" in status["reason"]


def test_request_symlink_is_quarantined(tmp_path: Path):
    root, request_path, request = _request_fixture(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    link = root / "inputs/link.json"
    link.symlink_to(outside)
    request["input_artifacts"]["dataset"] = {
        "path": "inputs/link.json",
        "sha256": canonical_file_hash(outside),
    }
    request = _reseal_request(request)
    request_path.write_bytes(canonical_json_bytes(request))
    assert (
        run_orchestrator(run_root=root, request_path=request_path, dry_run=True)[
            "state"
        ]
        == "quarantined"
    )


def test_dry_run_replay_and_concurrency_are_single_flight(tmp_path: Path):
    root, request_path, _request = _request_fixture(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(
            pool.map(
                lambda _: run_orchestrator(
                    run_root=root, request_path=request_path, dry_run=True
                ),
                range(4),
            )
        )
    assert {status["state"] for status in statuses} <= {"running", "dry_run_complete"}
    final = run_orchestrator(run_root=root, request_path=request_path, dry_run=True)
    assert final["state"] == "dry_run_complete"
    journal = json.loads((root / "stage_journal.json").read_text(encoding="utf-8"))
    states = [event["state"] for event in journal["events"]]
    assert states == ["requested", "running", "dry_run_complete"]


def test_valid_import_after_dry_run_is_resumable_and_timeout_is_terminal(
    tmp_path: Path,
):
    root, request_path, request = _request_fixture(tmp_path)
    assert (
        run_orchestrator(run_root=root, request_path=request_path, dry_run=True)[
            "state"
        ]
        == "dry_run_complete"
    )
    result_path, _ = _result_fixture(root, request)
    imported = run_orchestrator(
        run_root=root, request_path=request_path, import_result_path=result_path
    )
    assert imported["state"] == "candidate_ready", imported
    assert Path(imported["result_path"]).is_file()

    timeout_root, timeout_request_path, timeout_request = _request_fixture(
        tmp_path / "timeout-case"
    )
    timeout_result_path, _ = _result_fixture(
        timeout_root, timeout_request, status="timed_out"
    )
    timed_out = run_orchestrator(
        run_root=timeout_root,
        request_path=timeout_request_path,
        import_result_path=timeout_result_path,
    )
    assert timed_out["state"] == "timed_out"
    assert timed_out["terminal"] is True


def test_tampered_import_is_quarantined_and_cancel_is_durable(tmp_path: Path):
    root, request_path, request = _request_fixture(tmp_path)
    result_path, _ = _result_fixture(root, request)
    (root / request["output"]["best_skill_path"]).write_text(
        "tampered\n", encoding="utf-8"
    )
    status = run_orchestrator(
        run_root=root, request_path=request_path, import_result_path=result_path
    )
    assert status["state"] == "quarantined"
    assert status["quarantine_path"]

    cancel_root, cancel_request_path, _ = _request_fixture(tmp_path / "cancel-case")
    cancelled = run_orchestrator(
        run_root=cancel_root, request_path=cancel_request_path, cancel=True
    )
    assert cancelled["state"] == "cancelled"
    assert (
        json.loads((cancel_root / "status.json").read_text(encoding="utf-8"))["state"]
        == "cancelled"
    )


def test_dry_run_has_no_command_network_env_reward_or_runtime_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root, request_path, _ = _request_fixture(tmp_path)
    before = dict(os.environ)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("external side effect attempted")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    status = run_orchestrator(run_root=root, request_path=request_path, dry_run=True)
    assert status["state"] == "dry_run_complete"
    assert dict(os.environ) == before
    assert not (root / "reward_memory.jsonl").exists()
    assert not any(path.name.startswith("skillopt_policy") for path in root.rglob("*"))


def test_cli_import_quarantine_is_structured_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    root, request_path, _ = _request_fixture(tmp_path)
    malformed = root / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    code = main(
        [
            "--run-root",
            str(root),
            "--request",
            str(request_path),
            "--import-result",
            str(malformed),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["state"] == "quarantined"
