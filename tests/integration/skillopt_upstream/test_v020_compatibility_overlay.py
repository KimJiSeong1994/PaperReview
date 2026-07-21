from __future__ import annotations

import hashlib
import os
import shutil
import stat
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from src.search_eval.skillopt_compatibility import (
    APPROVED_FILE_ENTRIES,
    CANDIDATE_PATH,
    EVAL_OUT_ROOT,
    REGISTRY_PATCH_PATHS,
    REQUIRED_IMPORTED_MODULES,
    REQUIRED_PROJECTED_INPUT_PATHS,
    TRAIN_OUT_ROOT,
)
from src.search_eval.skillopt_compatibility_overlay import (
    ADAPTER_MARKER,
    _ExecutionProjectionLease,
    _run_projection,
    execute_staged_skillopt_mock_diagnostic,
    materialize_skillopt_compatibility_overlay,
    stage_skillopt_compatibility_overlay,
)
from src.search_eval.skillopt_contract import ValidationError


UPSTREAM_ROOT_ENV = "SKILLOPT_V020_UPSTREAM_ROOT"
EXACT_SOURCE_REQUIRED_ENV = "SKILLOPT_V020_EXACT_SOURCE_REQUIRED"
DEVELOPER_UPSTREAM_ROOT = Path("/private/tmp/skillopt-v020-review")
V0_MATERIALIZER = Path("src/search_eval/skillopt_materializer.py")
V0_MATERIALIZER_SHA256 = (
    "5813cba5581e8ed193ea901171494b8ad5fe2cfae5689e0830d73984ac436950"
)
EXPECTED_EVAL_IDS = [
    "train-1",
    "train-2",
    "train-3",
    "val-1",
    "val-2",
    "test-1",
    "test-2",
]
REQUIRED_UPSTREAM_CALLS = {
    "scripts.train.main": 1,
    "ReflACTTrainer.train": 1,
    "merge_patches": 1,
    "rank_and_select": 1,
    "apply_patch_with_report": 1,
    "evaluate_gate": 1,
    "select_gate_score": 2,
    "scripts.eval_only.main": 1,
}


def _upstream_root() -> Path:
    configured = os.environ.get(UPSTREAM_ROOT_ENV)
    root = Path(configured) if configured else DEVELOPER_UPSTREAM_ROOT
    if root.is_dir():
        return root
    message = f"exact SkillOpt v0.2.0 source unavailable: {root}"
    if os.environ.get(EXACT_SOURCE_REQUIRED_ENV) == "1":
        pytest.fail(message)
    pytest.skip(f"{message}; exact-source integration was not requested")


def _file_paths(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }


def _export_exact_source(destination: Path) -> Path:
    upstream = _upstream_root()
    for entry in APPROVED_FILE_ENTRIES:
        source = upstream / entry["path"]
        if not source.is_file():
            pytest.fail(f"exact upstream source is missing {entry['path']}")
        target = destination / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(int(entry["mode"], 8))
    assert len(APPROVED_FILE_ENTRIES) == 311
    assert _file_paths(destination) == {
        entry["path"] for entry in APPROVED_FILE_ENTRIES
    }
    assert not (destination / ".git").exists()
    return destination


def _source_snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        entry["path"]: (
            (root / entry["path"]).read_bytes(),
            stat.S_IMODE((root / entry["path"]).lstat().st_mode),
        )
        for entry in APPROVED_FILE_ENTRIES
    }


@pytest.fixture(scope="module")
def exact_execution(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("skillopt-v020-exact-overlay")
    source = _export_exact_source(root / "source")
    source_before = _source_snapshot(source)
    overlay = root / "overlay"
    profile = materialize_skillopt_compatibility_overlay(output_dir=overlay)
    staged = root / "staged"
    profile = stage_skillopt_compatibility_overlay(
        source_root=source,
        overlay_root=overlay,
        staged_root=staged,
        profile=profile,
    )
    execution = root / "execution"
    report = execute_staged_skillopt_mock_diagnostic(
        staged_root=staged,
        execution_root=execution,
        profile=profile,
    )
    return {
        "source": source,
        "source_before": source_before,
        "overlay": overlay,
        "staged": staged,
        "execution": execution,
        "profile": profile,
        "report": report,
    }


def test_exact_source_overlay_stages_and_executes_real_mock_train_eval(
    exact_execution: dict[str, Any],
) -> None:
    source = exact_execution["source"]
    overlay = exact_execution["overlay"]
    staged = exact_execution["staged"]
    execution = exact_execution["execution"]
    profile = exact_execution["profile"]
    report = exact_execution["report"]

    overlay_entries = profile["overlay_manifest"]["logical_files"]
    staging = profile["staging_manifest"]
    assert len(overlay_entries) == 10
    assert _file_paths(overlay) == {entry["path"] for entry in overlay_entries}
    assert len(staging["staged_tree"]) == 318
    assert _file_paths(staged) == {entry["path"] for entry in staging["staged_tree"]}
    assert {
        row["path"] for row in staging["allowlisted_diff"] if row["change"] == "add"
    } == set(REQUIRED_PROJECTED_INPUT_PATHS)
    assert {
        row["path"] for row in staging["allowlisted_diff"] if row["change"] == "modify"
    } == set(REGISTRY_PATCH_PATHS)

    assert report["status"] == "passed"
    assert report["evidence_class"] == "diagnostic"
    assert report["authorization_status"] == "not_authorized"
    assert report["authenticity_status"] == "unverified"
    assert report["seal_kind"] == "self_asserted_integrity"
    assert report["trusted"] is False
    assert report["tested_patch"] is None
    assert report["execution_counts"] == {
        "provider": 0,
        "network": 0,
        "subprocess": 0,
        "train": 1,
        "eval": 1,
    }

    for call, minimum in REQUIRED_UPSTREAM_CALLS.items():
        assert report["calls"][call] >= minimum
    for call in (
        "adapter.setup",
        "adapter.build_env_from_batch",
        "adapter.build_eval_env",
        "adapter.rollout",
        "adapter.reflect",
    ):
        assert report["calls"][call] >= 1
    for module, relative in REQUIRED_IMPORTED_MODULES.items():
        assert report["imports"][module]["path"] == relative

    candidate = report["candidate"]
    assert candidate == {
        "path": CANDIDATE_PATH,
        "sha256": report["bindings"]["candidate_sha256"],
        "size_bytes": (execution / CANDIDATE_PATH).stat().st_size,
        "marker": ADAPTER_MARKER,
        "marker_count": 1,
        "writer": "skillopt.engine.trainer.ReflACTTrainer.train",
        "writer_observed": True,
        "writer_open_count": 2,
        "writer_open_path": CANDIDATE_PATH,
        "writer_open_mode": "w",
    }
    assert report["eval"]["candidate_sha256_read"] == candidate["sha256"]
    assert report["eval"]["candidate_read_count"] == 1
    assert report["eval"]["input_ids"] == EXPECTED_EVAL_IDS
    assert report["eval"]["ids"] == EXPECTED_EVAL_IDS
    assert report["eval"]["n_items"] == 7
    assert report["eval"]["hard"] == report["eval"]["soft"] == 1.0
    assert report["containment"] == {
        "scope": "diagnostic_in_process",
        "single_threaded": True,
        "os_sandbox": False,
        "authorization": False,
    }

    projection = report["projection"]
    assert projection["immutable_files"] == staging["staged_tree"]
    assert projection["staging_identity"] == staging["identity"]
    assert projection["staged_tree_identity"] == staging["staged_tree_identity"]
    assert projection["mutable_roots"] == [TRAIN_OUT_ROOT, EVAL_OUT_ROOT]
    immutable_paths = {entry["path"] for entry in projection["immutable_files"]}
    execution_paths = _file_paths(execution)
    assert immutable_paths <= execution_paths
    assert all(
        path in immutable_paths
        or path.startswith(f"{TRAIN_OUT_ROOT}/")
        or path.startswith(f"{EVAL_OUT_ROOT}/")
        for path in execution_paths
    )
    for entry in projection["immutable_files"]:
        execution_path = execution / entry["path"]
        staged_path = staged / entry["path"]
        assert execution_path.read_bytes() == staged_path.read_bytes()
        assert stat.S_IMODE(execution_path.lstat().st_mode) == int(entry["mode"], 8)

    assert _source_snapshot(source) == exact_execution["source_before"]
    assert hashlib.sha256(V0_MATERIALIZER.read_bytes()).hexdigest() == (
        V0_MATERIALIZER_SHA256
    )


def test_exact_source_required_failure_cannot_be_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(UPSTREAM_ROOT_ENV, str(tmp_path / "missing-source"))
    monkeypatch.setenv(EXACT_SOURCE_REQUIRED_ENV, "1")
    with pytest.raises(
        pytest.fail.Exception, match="exact SkillOpt v0.2.0 source unavailable"
    ):
        _upstream_root()


def test_preloaded_protected_module_rejects_before_execution_and_is_preserved(
    exact_execution: dict[str, Any], tmp_path: Path
) -> None:
    assert "skillopt" not in sys.modules
    sentinel = types.ModuleType("skillopt")
    sys.modules["skillopt"] = sentinel
    execution = tmp_path / "preloaded-execution"
    try:
        with pytest.raises(
            ValidationError, match="protected namespace is already loaded"
        ):
            execute_staged_skillopt_mock_diagnostic(
                staged_root=exact_execution["staged"],
                execution_root=execution,
                profile=exact_execution["profile"],
            )
        assert sys.modules["skillopt"] is sentinel
        assert not execution.exists()
    finally:
        assert sys.modules.pop("skillopt") is sentinel


def test_staged_byte_tamper_rejects_before_execution(
    exact_execution: dict[str, Any], tmp_path: Path
) -> None:
    tampered = tmp_path / "tampered-staged"
    shutil.copytree(exact_execution["staged"], tampered)
    readme = tampered / "README.md"
    readme.write_bytes(readme.read_bytes() + b"\ntampered\n")
    execution = tmp_path / "tampered-execution"

    with pytest.raises(
        ValidationError, match="size README.md|manifest file changed|leased manifest"
    ):
        execute_staged_skillopt_mock_diagnostic(
            staged_root=tampered,
            execution_root=execution,
            profile=exact_execution["profile"],
        )
    assert not execution.exists()


def test_preexisting_candidate_is_rejected_before_a_second_upstream_run(
    exact_execution: dict[str, Any],
) -> None:
    report = exact_execution["report"]
    execution = exact_execution["execution"]
    with _ExecutionProjectionLease(execution, report["projection"]) as lease:
        with pytest.raises(ValidationError, match="candidate must be absent"):
            _run_projection(
                execution=execution,
                projection=report["projection"],
                profile=exact_execution["profile"],
                lease=lease,
            )
