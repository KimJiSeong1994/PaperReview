from __future__ import annotations

import ast
import builtins
import copy
import hashlib
import importlib
import importlib.abc
import importlib.util
import os
import shutil
import socket
import stat
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

from src.search_eval.skillopt_compatibility import (
    ADAPTER_PATH,
    APPROVED_FILE_ENTRIES,
    CANDIDATE_PATH,
    PROFILE_CONFIG_PATH,
    PROFILE_ID,
    REGISTRY_PATCH_PATHS,
    REQUIRED_PROJECTED_INPUT_PATHS,
    TRAIN_OUT_ROOT,
    acquire_diagnostic_overlay_tree_lease,
    acquire_diagnostic_staging_tree_lease,
    seal_identity_artifact,
)
from src.search_eval.skillopt_compatibility_overlay import (
    ADAPTER_BYTES,
    DEFAULT_PROFILE_CATALOG_PATH,
    _ExecutionProjectionLease,
    _ExecutionSentinel,
    _read_output_file,
    _validate_execution_report,
    _verify_repo_local_scripts_source,
    execute_staged_skillopt_mock_diagnostic,
    materialize_skillopt_compatibility_overlay,
    stage_skillopt_compatibility_overlay,
)
from src.search_eval.skillopt_contract import ValidationError


UPSTREAM = Path("/private/tmp/skillopt-v020-review")
V0_MATERIALIZER = Path("src/search_eval/skillopt_materializer.py")
V0_SHA256 = "5813cba5581e8ed193ea901171494b8ad5fe2cfae5689e0830d73984ac436950"


def _exact_source(destination: Path) -> Path:
    if not UPSTREAM.is_dir():
        pytest.skip(f"pinned upstream checkout is unavailable: {UPSTREAM}")
    for entry in APPROVED_FILE_ENTRIES:
        source = UPSTREAM / entry["path"]
        target = destination / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(int(entry["mode"], 8))
    return destination


def _materialized(tmp_path: Path) -> tuple[dict, Path]:
    overlay = tmp_path / "overlay"
    profile = materialize_skillopt_compatibility_overlay(output_dir=overlay)
    return profile, overlay


def _staged(tmp_path: Path) -> tuple[dict, Path]:
    profile, overlay = _materialized(tmp_path)
    source = _exact_source(tmp_path / "source")
    staged = tmp_path / "staged"
    profile = stage_skillopt_compatibility_overlay(
        source_root=source,
        overlay_root=overlay,
        staged_root=staged,
        profile=profile,
    )
    return profile, staged


def test_overlay_is_deterministic_exact_and_diagnostic(tmp_path: Path) -> None:
    first, first_root = _materialized(tmp_path / "first")
    second, second_root = _materialized(tmp_path / "second")

    assert first == second
    assert first["profile_id"] == PROFILE_ID
    assert first["tested_patch"] is None
    assert {item["code"] for item in first["evidence_ceiling"]} == {
        "custody",
        "full_dependency_lock",
        "image_digest",
        "staging_manifest",
        "tested_patch",
    }
    assert (
        first["overlay_manifest"]["identity"] == second["overlay_manifest"]["identity"]
    )
    paths = {
        path.relative_to(first_root).as_posix()
        for path in first_root.rglob("*")
        if path.is_file()
    }
    assert len(paths) == 10
    assert paths == {
        entry["path"] for entry in first["overlay_manifest"]["logical_files"]
    }
    assert not any(path.name.endswith("manifest.json") for path in (first_root,))
    for relative in paths:
        file_stat = (first_root / relative).lstat()
        assert stat.S_ISREG(file_stat.st_mode)
        assert stat.S_IMODE(file_stat.st_mode) == 0o644
        assert file_stat.st_nlink == 1
        assert (first_root / relative).read_bytes() == (
            second_root / relative
        ).read_bytes()
    assert ast.parse(ADAPTER_BYTES)
    with acquire_diagnostic_overlay_tree_lease(first_root, first):
        pass


def test_overlay_rejects_existing_destination_and_catalog_tamper(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValidationError, match="absent"):
        materialize_skillopt_compatibility_overlay(output_dir=existing)

    catalog = DEFAULT_PROFILE_CATALOG_PATH.read_bytes()
    hostile = tmp_path / "catalog.json"
    hostile.write_bytes(
        catalog.replace(b'"tested_patch": null', b'"tested_patch": {}', 1)
    )
    with pytest.raises(ValidationError):
        materialize_skillopt_compatibility_overlay(
            output_dir=tmp_path / "hostile-overlay",
            profile_catalog_path=hostile,
        )


def test_staging_is_exact_and_preserves_pristine_source(tmp_path: Path) -> None:
    profile, overlay = _materialized(tmp_path)
    source = _exact_source(tmp_path / "source")
    source_before = {
        entry["path"]: (
            (source / entry["path"]).read_bytes(),
            stat.S_IMODE((source / entry["path"]).stat().st_mode),
        )
        for entry in APPROVED_FILE_ENTRIES
    }
    staged = tmp_path / "staged"

    result = stage_skillopt_compatibility_overlay(
        source_root=source,
        overlay_root=overlay,
        staged_root=staged,
        profile=profile,
    )

    staging = result["staging_manifest"]
    assert len(staging["staged_tree"]) == 318
    assert len(staging["allowlisted_diff"]) == 9
    assert {
        row["path"] for row in staging["allowlisted_diff"] if row["change"] == "add"
    } == set(REQUIRED_PROJECTED_INPUT_PATHS)
    assert {
        row["path"] for row in staging["allowlisted_diff"] if row["change"] == "modify"
    } == set(REGISTRY_PATCH_PATHS)
    assert {item["code"] for item in result["evidence_ceiling"]} == {
        "custody",
        "full_dependency_lock",
        "image_digest",
        "tested_patch",
    }
    assert not (staged / "overlay").exists()
    assert {
        path.relative_to(staged).as_posix()
        for path in staged.rglob("*")
        if path.is_file()
    } == {entry["path"] for entry in staging["staged_tree"]}
    for path, (payload, mode) in source_before.items():
        assert (source / path).read_bytes() == payload
        assert stat.S_IMODE((source / path).stat().st_mode) == mode
    with acquire_diagnostic_staging_tree_lease(staged, result):
        pass


@pytest.mark.parametrize(
    "tampered_path", [ADAPTER_PATH, "configs/jiphyeonjeon_search/default.yaml"]
)
def test_staging_rejects_overlay_byte_tamper(
    tmp_path: Path, tampered_path: str
) -> None:
    profile, overlay = _materialized(tmp_path)
    source = _exact_source(tmp_path / "source")
    target = overlay / tampered_path
    target.write_bytes(target.read_bytes() + b"x")

    with pytest.raises(ValidationError):
        stage_skillopt_compatibility_overlay(
            source_root=source,
            overlay_root=overlay,
            staged_root=tmp_path / "staged",
            profile=profile,
        )
    assert not (tmp_path / "staged").exists()


def test_staging_rejects_profile_tamper_hardlink_and_existing_destination(
    tmp_path: Path,
) -> None:
    profile, overlay = _materialized(tmp_path)
    source = _exact_source(tmp_path / "source")

    tampered = copy.deepcopy(profile)
    tampered["outputs"]["candidate_path"] = "outputs/train/other.md"
    tampered = seal_identity_artifact(tampered, tampered["version"])
    with pytest.raises(ValidationError):
        stage_skillopt_compatibility_overlay(
            source_root=source,
            overlay_root=overlay,
            staged_root=tmp_path / "tampered-profile",
            profile=tampered,
        )

    linked = tmp_path / "linked-source"
    _exact_source(linked)
    readme = linked / "README.md"
    os.link(readme, tmp_path / "readme-hardlink")
    with pytest.raises(ValidationError, match="hard link"):
        stage_skillopt_compatibility_overlay(
            source_root=linked,
            overlay_root=overlay,
            staged_root=tmp_path / "hardlink-stage",
            profile=profile,
        )

    existing = tmp_path / "existing-stage"
    existing.mkdir()
    with pytest.raises(ValidationError, match="absent"):
        stage_skillopt_compatibility_overlay(
            source_root=source,
            overlay_root=overlay,
            staged_root=existing,
            profile=profile,
        )


def test_v0_materializer_bytes_remain_frozen() -> None:
    assert hashlib.sha256(V0_MATERIALIZER.read_bytes()).hexdigest() == V0_SHA256


def test_mock_execution_projection_runs_pinned_upstream_and_restores_state(
    tmp_path: Path,
) -> None:
    profile, staged = _staged(tmp_path)
    execution = tmp_path / "execution"
    argv_object = sys.argv
    path_object = sys.path
    argv_before = list(sys.argv)
    path_before = list(sys.path)
    cwd_before = Path.cwd()
    bytecode_before = sys.dont_write_bytecode
    sys_profile_before = sys.getprofile()
    thread_profile_before = threading.getprofile()
    trace_present = "REFLACT_CODEX_TRACE_TO_OPTIMIZER" in os.environ
    trace_before = os.environ.get("REFLACT_CODEX_TRACE_TO_OPTIMIZER")
    modules_before = dict(sys.modules)

    report = execute_staged_skillopt_mock_diagnostic(
        staged_root=staged,
        execution_root=execution,
        profile=profile,
    )

    assert report["status"] == "passed"
    assert report["trusted"] is False
    assert report["authorization_status"] == "not_authorized"
    assert report["tested_patch"] is None
    assert report["execution_counts"] == {
        "provider": 0,
        "network": 0,
        "subprocess": 0,
        "train": 1,
        "eval": 1,
    }
    assert report["projection"]["version"] == "execution_projection_v1"
    assert len(report["projection"]["immutable_files"]) == 318
    assert report["projection"]["mutable_roots"] == [
        "outputs/train",
        "outputs/eval",
    ]
    assert report["candidate"]["marker_count"] == 1
    assert report["train"]["update_operation"] == "append"
    assert report["train"]["gate_metric"] == "mixed"
    assert report["train"]["gate_action"] == "accept_new_best"
    assert report["eval"]["ids"] == [
        "train-1",
        "train-2",
        "train-3",
        "val-1",
        "val-2",
        "test-1",
        "test-2",
    ]
    assert report["eval"]["hard"] == report["eval"]["soft"] == 1.0
    assert not any(path.name == "__pycache__" for path in execution.rglob("*"))
    assert sys.argv is argv_object and sys.argv == argv_before
    assert sys.path is path_object and sys.path == path_before
    assert Path.cwd() == cwd_before
    assert sys.dont_write_bytecode is bytecode_before
    assert sys.getprofile() is sys_profile_before
    assert threading.getprofile() is thread_profile_before
    assert ("REFLACT_CODEX_TRACE_TO_OPTIMIZER" in os.environ) is trace_present
    assert os.environ.get("REFLACT_CODEX_TRACE_TO_OPTIMIZER") == trace_before
    assert set(sys.modules) == set(modules_before)
    assert all(sys.modules[name] is module for name, module in modules_before.items())


def test_execution_report_rejects_independently_resealed_hostile_relations(
    tmp_path: Path,
) -> None:
    profile, staged = _staged(tmp_path)
    report = execute_staged_skillopt_mock_diagnostic(
        staged_root=staged,
        execution_root=tmp_path / "execution",
        profile=profile,
    )

    hostile_reports = []

    candidate = copy.deepcopy(report)
    candidate["candidate"]["marker_count"] = 2
    hostile_reports.append(candidate)

    imported = copy.deepcopy(report)
    imported["imports"]["scripts.train"]["sha256"] = "0" * 64
    hostile_reports.append(imported)

    called = copy.deepcopy(report)
    called["calls"]["scripts.train.main"] = 2
    hostile_reports.append(called)

    gated = copy.deepcopy(report)
    gated["train"]["gate_action"] = "reject"
    hostile_reports.append(gated)

    scored = copy.deepcopy(report)
    scored["eval"]["hard"] = 0.5
    hostile_reports.append(scored)

    hashed = copy.deepcopy(report)
    hashed["eval"]["summary_sha256"] = "1" * 64
    hostile_reports.append(hashed)

    bound = copy.deepcopy(report)
    bound["bindings"]["candidate_sha256"] = "2" * 64
    hostile_reports.append(bound)

    projected = copy.deepcopy(report)
    projected["projection"]["mutable_roots"].reverse()
    projected["projection"] = seal_identity_artifact(
        projected["projection"], projected["projection"]["version"]
    )
    hostile_reports.append(projected)

    for hostile in hostile_reports:
        resealed = seal_identity_artifact(hostile, hostile["version"])
        with pytest.raises(ValidationError):
            _validate_execution_report(resealed, profile)


def test_output_evidence_reader_rejects_aba_symlink_and_hardlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile, staged = _staged(tmp_path)
    execution = tmp_path / "execution"
    report = execute_staged_skillopt_mock_diagnostic(
        staged_root=staged,
        execution_root=execution,
        profile=profile,
    )
    candidate = execution / CANDIDATE_PATH
    relative = CANDIDATE_PATH.removeprefix(f"{TRAIN_OUT_ROOT}/")

    lease = _ExecutionProjectionLease(execution, report["projection"])
    try:
        from src.search_eval import skillopt_compatibility_overlay as overlay_module

        original_read = overlay_module._read_all_fd
        raced = False

        def replace_and_restore(fd: int) -> bytes:
            nonlocal raced
            if not raced:
                raced = True
                saved = candidate.with_name("candidate.saved")
                candidate.rename(saved)
                candidate.write_bytes(b"hostile replacement")
                candidate.unlink()
                saved.rename(candidate)
            return original_read(fd)

        monkeypatch.setattr(overlay_module, "_read_all_fd", replace_and_restore)
        with pytest.raises(ValidationError, match="changed during"):
            _read_output_file(lease, TRAIN_OUT_ROOT, relative)
        monkeypatch.setattr(overlay_module, "_read_all_fd", original_read)

        saved = candidate.with_name("candidate.saved")
        candidate.rename(saved)
        candidate.symlink_to(saved.name)
        with pytest.raises(ValidationError):
            _read_output_file(lease, TRAIN_OUT_ROOT, relative)
        candidate.unlink()
        saved.rename(candidate)

        linked = candidate.with_name("candidate-hardlink.md")
        os.link(candidate, linked)
        with pytest.raises(ValidationError, match="single-link regular"):
            _read_output_file(lease, TRAIN_OUT_ROOT, relative)
        linked.unlink()
    finally:
        lease._close()


def test_execution_projection_lease_rejects_immutable_output_and_candidate_tamper(
    tmp_path: Path,
) -> None:
    profile, staged = _staged(tmp_path)
    execution = tmp_path / "execution"
    report = execute_staged_skillopt_mock_diagnostic(
        staged_root=staged,
        execution_root=execution,
        profile=profile,
    )

    lease = _ExecutionProjectionLease(execution, report["projection"])
    try:
        immutable = execution / "README.md"
        immutable.write_bytes(immutable.read_bytes() + b"tamper")
        with pytest.raises(ValidationError, match="immutable projection file changed"):
            lease.verify_live()
    finally:
        lease._close()

    immutable.write_bytes(staged.joinpath("README.md").read_bytes())
    lease = _ExecutionProjectionLease(execution, report["projection"])
    try:
        train_root = execution / "outputs/train"
        replaced = execution / "outputs/train-replaced"
        train_root.rename(replaced)
        train_root.mkdir()
        with pytest.raises(
            ValidationError, match="topology changed|output root was replaced"
        ):
            lease.verify_live()
    finally:
        lease._close()

    shutil.rmtree(execution)
    report = execute_staged_skillopt_mock_diagnostic(
        staged_root=staged,
        execution_root=execution,
        profile=profile,
    )
    lease = _ExecutionProjectionLease(execution, report["projection"])
    try:
        candidate = execution / "outputs/train/best_skill.md"
        os.link(candidate, execution / "outputs/train/candidate-hardlink.md")
        with pytest.raises(ValidationError, match="single-link regular"):
            lease.verify_live()
    finally:
        lease._close()


def test_execution_projection_lease_rejects_immutable_overwrite_restore_aba(
    tmp_path: Path,
) -> None:
    profile, staged = _staged(tmp_path)
    execution = tmp_path / "execution"
    report = execute_staged_skillopt_mock_diagnostic(
        staged_root=staged,
        execution_root=execution,
        profile=profile,
    )
    immutable = execution / "README.md"
    approved = immutable.read_bytes()
    hostile = bytes(byte ^ 0x01 for byte in approved)
    assert len(hostile) == len(approved) and hostile != approved

    lease = _ExecutionProjectionLease(execution, report["projection"])
    try:
        immutable.write_bytes(hostile)
        immutable.write_bytes(approved)
        assert immutable.read_bytes() == approved
        with pytest.raises(ValidationError, match="immutable projection file changed"):
            lease.verify_live()
    finally:
        lease._close()


def test_mock_execution_rejects_preloaded_protected_namespace(tmp_path: Path) -> None:
    profile, staged = _staged(tmp_path)
    sentinel = types.ModuleType("skillopt")
    sys.modules["skillopt"] = sentinel
    try:
        with pytest.raises(ValidationError, match="already loaded"):
            execute_staged_skillopt_mock_diagnostic(
                staged_root=staged,
                execution_root=tmp_path / "execution",
                profile=profile,
            )
    finally:
        assert sys.modules.pop("skillopt") is sentinel


def test_mock_execution_isolates_repo_local_scripts_import_and_restores_identity(
    tmp_path: Path,
) -> None:
    profile, staged = _staged(tmp_path)
    scripts_module = importlib.import_module("scripts")
    backfill_module = importlib.import_module("scripts.backfill_events")

    report = execute_staged_skillopt_mock_diagnostic(
        staged_root=staged,
        execution_root=tmp_path / "execution",
        profile=profile,
    )

    assert report["status"] == "passed"
    assert sys.modules["scripts"] is scripts_module
    assert sys.modules["scripts.backfill_events"] is backfill_module
    assert "scripts.train" not in sys.modules
    assert "scripts.eval_only" not in sys.modules


@pytest.mark.parametrize("module_name", ["scripts", "scripts.train"])
def test_mock_execution_rejects_and_preserves_preloaded_scripts_sentinels(
    tmp_path: Path,
    module_name: str,
) -> None:
    profile, staged = _staged(tmp_path)
    absent = object()
    previous = sys.modules.get(module_name, absent)
    sentinel = types.ModuleType(module_name)
    sentinel.__spec__ = None
    sys.modules[module_name] = sentinel
    try:
        with pytest.raises(ValidationError, match="protected namespace|not canonical"):
            execute_staged_skillopt_mock_diagnostic(
                staged_root=staged,
                execution_root=tmp_path / "execution",
                profile=profile,
            )
        assert sys.modules[module_name] is sentinel
    finally:
        if previous is absent:
            assert sys.modules.pop(module_name) is sentinel
        else:
            sys.modules[module_name] = previous


def test_mock_execution_rejects_hostile_module_without_reading_attributes(
    tmp_path: Path,
) -> None:
    profile, staged = _staged(tmp_path)

    class HostileModule(types.ModuleType):
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"ambient attribute read: {name}")

    sentinel = HostileModule("scripts")
    absent = object()
    previous = sys.modules.get("scripts", absent)
    sys.modules["scripts"] = sentinel
    try:
        with pytest.raises(ValidationError, match="already loaded"):
            execute_staged_skillopt_mock_diagnostic(
                staged_root=staged,
                execution_root=tmp_path / "execution",
                profile=profile,
            )
        assert sys.modules["scripts"] is sentinel
    finally:
        if previous is absent:
            assert sys.modules.pop("scripts") is sentinel
        else:
            sys.modules["scripts"] = previous


def test_mock_execution_rejects_hostile_loader_without_reading_attributes(
    tmp_path: Path,
) -> None:
    profile, staged = _staged(tmp_path)

    class HostileLoader:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"ambient loader attribute read: {name}")

    sentinel = types.ModuleType("scripts.backfill_events")
    sentinel.__loader__ = HostileLoader()
    sentinel.__spec__ = importlib.machinery.ModuleSpec(
        "scripts.backfill_events",
        sentinel.__loader__,
        is_package=False,
    )
    absent = object()
    previous = sys.modules.get("scripts.backfill_events", absent)
    sys.modules["scripts.backfill_events"] = sentinel
    try:
        with pytest.raises(ValidationError, match="not canonical"):
            execute_staged_skillopt_mock_diagnostic(
                staged_root=staged,
                execution_root=tmp_path / "execution",
                profile=profile,
            )
        assert sys.modules["scripts.backfill_events"] is sentinel
    finally:
        if previous is absent:
            assert sys.modules.pop("scripts.backfill_events") is sentinel
        else:
            sys.modules["scripts.backfill_events"] = previous


def test_repo_local_scripts_source_rejects_symlink_before_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.search_eval import skillopt_compatibility_overlay as overlay_module

    scripts_root = tmp_path / "scripts"
    scripts_root.mkdir()
    target = tmp_path / "backfill_events.py"
    target.write_text("# source fixture\n", encoding="utf-8")
    source = scripts_root / "backfill_events.py"
    source.symlink_to(target)
    loader = importlib.machinery.SourceFileLoader(
        "scripts.backfill_events",
        str(source),
    )
    sentinel = types.ModuleType("scripts.backfill_events")
    sentinel.__file__ = str(source)
    sentinel.__loader__ = loader
    sentinel.__spec__ = importlib.machinery.ModuleSpec(
        "scripts.backfill_events",
        loader,
        origin=str(source),
        is_package=False,
    )
    monkeypatch.setattr(overlay_module, "_repo_scripts_root", lambda: scripts_root)

    with pytest.raises(ValidationError, match="not a regular source file"):
        _verify_repo_local_scripts_source("scripts.backfill_events", sentinel)


def test_exact_trace_rejects_forged_same_filename_and_name(tmp_path: Path) -> None:
    root = tmp_path / "execution"
    (root / "scripts").mkdir(parents=True)
    filename = str(root / "scripts/train.py")
    Path(filename).write_text("# trace fixture\n", encoding="utf-8")

    canonical_namespace: dict[str, object] = {}
    exec(
        compile("def main():\n    return None\n", filename, "exec"), canonical_namespace
    )
    forged_namespace: dict[str, object] = {}
    exec(compile("def main():\n    return 1\n", filename, "exec"), forged_namespace)
    canonical = canonical_namespace["main"]
    forged = forged_namespace["main"]
    assert callable(canonical) and callable(forged)

    sentinel = _ExecutionSentinel(root)
    sentinel.bind_exact_codes({"scripts.train.main": canonical})
    previous = sys.getprofile()
    try:
        sys.setprofile(sentinel.profile)
        with pytest.raises(ValidationError, match="forged upstream frame"):
            forged()
    finally:
        sys.setprofile(previous)


def test_execution_isolates_custom_protected_source_loader(
    tmp_path: Path,
) -> None:
    profile, staged = _staged(tmp_path)
    execution = tmp_path / "execution"
    executed = False

    class HostileLoader(importlib.abc.Loader):
        def create_module(self, spec: object) -> None:
            return None

        def exec_module(self, module: types.ModuleType) -> None:
            nonlocal executed
            executed = True
            module.main = lambda: None

    class HostileFinder(importlib.abc.MetaPathFinder):
        def find_spec(
            self,
            fullname: str,
            path: object = None,
            target: object = None,
        ) -> object:
            del path, target
            if fullname != "scripts.train":
                return None
            return importlib.util.spec_from_file_location(
                fullname,
                execution / "scripts/train.py",
                loader=HostileLoader(),
            )

    finder = HostileFinder()
    sys.meta_path.insert(0, finder)
    try:
        report = execute_staged_skillopt_mock_diagnostic(
            staged_root=staged,
            execution_root=execution,
            profile=profile,
        )
        assert report["status"] == "passed"
        assert executed is False
    finally:
        assert sys.meta_path.pop(0) is finder


def test_execution_never_runs_ambient_exact_source_loader_override(
    tmp_path: Path,
) -> None:
    profile, staged = _staged(tmp_path)
    execution = tmp_path / "execution"
    marker = "_g003_hostile_exact_loader_executed"

    class HostileFinder(importlib.abc.MetaPathFinder):
        def find_spec(
            self,
            fullname: str,
            path: object = None,
            target: object = None,
        ) -> object:
            del path, target
            if fullname != "scripts.train":
                return None
            loader = importlib.machinery.SourceFileLoader(
                fullname, str(execution / "scripts/train.py")
            )

            def forged_get_code(self: object, requested: str) -> types.CodeType:
                del self, requested
                return compile(
                    f"import builtins\nbuiltins.{marker} = True\n",
                    str(execution / "scripts/train.py"),
                    "exec",
                )

            loader.get_code = types.MethodType(forged_get_code, loader)
            return importlib.util.spec_from_file_location(
                fullname,
                execution / "scripts/train.py",
                loader=loader,
            )

    finder = HostileFinder()
    sys.meta_path.insert(0, finder)
    try:
        report = execute_staged_skillopt_mock_diagnostic(
            staged_root=staged,
            execution_root=execution,
            profile=profile,
        )
        assert report["status"] == "passed"
        assert not hasattr(__import__("builtins"), marker)
    finally:
        assert sys.meta_path.pop(0) is finder
        __import__("builtins").__dict__.pop(marker, None)


@pytest.mark.parametrize("builtin_name", ["compile", "exec"])
def test_held_source_ignores_replaced_compile_and_exec_and_restores_ambient_state(
    tmp_path: Path,
    builtin_name: str,
) -> None:
    profile, staged = _staged(tmp_path)
    execution = tmp_path / "execution"
    target = str(execution / "scripts/train.py")
    marker = f"_g003_hostile_{builtin_name}_executed"
    original_compile = builtins.compile
    original_exec = builtins.exec
    target_calls = 0

    def hostile_compile(
        source: object,
        filename: object,
        mode: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal target_calls
        if filename == target:
            target_calls += 1
            source = (
                f"import builtins\nbuiltins.{marker} = True\n"
                "def main():\n    raise AssertionError('hostile compile ran')\n"
            )
        return original_compile(source, filename, mode, *args, **kwargs)

    def hostile_exec(
        source: object,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        *,
        closure: object = None,
    ) -> object:
        nonlocal target_calls
        if isinstance(source, types.CodeType) and source.co_filename == target:
            target_calls += 1
            source = original_compile(
                f"import builtins\nbuiltins.{marker} = True\n",
                target,
                "exec",
            )
        if closure is None:
            return original_exec(source, globals, locals)
        return original_exec(source, globals, locals, closure=closure)

    replacement = hostile_compile if builtin_name == "compile" else hostile_exec
    setattr(builtins, builtin_name, replacement)
    try:
        report = execute_staged_skillopt_mock_diagnostic(
            staged_root=staged,
            execution_root=execution,
            profile=profile,
        )
        assert report["status"] == "passed"
        assert report["execution_counts"] == {
            "provider": 0,
            "network": 0,
            "subprocess": 0,
            "train": 1,
            "eval": 1,
        }
        assert target_calls == 0
        assert not hasattr(builtins, marker)
        assert getattr(builtins, builtin_name) is replacement
    finally:
        setattr(
            builtins,
            builtin_name,
            original_compile if builtin_name == "compile" else original_exec,
        )
        builtins.__dict__.pop(marker, None)


@pytest.mark.parametrize("method_name", ["get_code", "exec_module"])
def test_execution_rejects_replaced_source_loader_class_method_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    profile, staged = _staged(tmp_path)
    marker = "_g003_hostile_loader_class_method_executed"
    original = getattr(importlib.machinery.SourceFileLoader, method_name)

    def hostile(self: object, *args: object, **kwargs: object) -> object:
        __import__("builtins").__dict__[marker] = True
        return original(self, *args, **kwargs)

    monkeypatch.setattr(importlib.machinery.SourceFileLoader, method_name, hostile)
    with pytest.raises(ValidationError, match="canonical import machinery"):
        execute_staged_skillopt_mock_diagnostic(
            staged_root=staged,
            execution_root=tmp_path / "execution",
            profile=profile,
        )
    assert not hasattr(__import__("builtins"), marker)


def test_execution_contains_preinstalled_global_import_hooks(
    tmp_path: Path,
) -> None:
    profile, staged = _staged(tmp_path)
    calls = {"open": 0, "finder": 0, "path_hook": 0}
    original_open = __import__("builtins").open

    def hostile_open(*args: object, **kwargs: object) -> object:
        calls["open"] += 1
        return original_open(*args, **kwargs)

    class HostileFinder(importlib.abc.MetaPathFinder):
        def find_spec(
            self,
            fullname: str,
            path: object = None,
            target: object = None,
        ) -> None:
            del fullname, path, target
            calls["finder"] += 1
            return None

    def hostile_path_hook(path: str) -> None:
        del path
        calls["path_hook"] += 1
        raise ImportError

    builtins_module = __import__("builtins")
    finder = HostileFinder()
    meta_path_object = sys.meta_path
    path_hooks_object = sys.path_hooks
    meta_path_before = list(sys.meta_path)
    path_hooks_before = list(sys.path_hooks)
    builtins_module.open = hostile_open
    sys.meta_path.insert(0, finder)
    sys.path_hooks.insert(0, hostile_path_hook)
    try:
        report = execute_staged_skillopt_mock_diagnostic(
            staged_root=staged,
            execution_root=tmp_path / "execution",
            profile=profile,
        )
        assert report["status"] == "passed"
        assert calls == {"open": 0, "finder": 0, "path_hook": 0}
        assert builtins_module.open is hostile_open
        assert sys.meta_path is meta_path_object
        assert sys.path_hooks is path_hooks_object
    finally:
        builtins_module.open = original_open
        sys.meta_path[:] = meta_path_before
        sys.path_hooks[:] = path_hooks_before


def test_scoped_audit_observer_rejects_prebound_process_and_socket_aliases(
    tmp_path: Path,
) -> None:
    from src.search_eval import skillopt_compatibility_overlay as overlay_module

    root = tmp_path / "execution"
    root.mkdir()
    sentinel = _ExecutionSentinel(root)
    prebound_popen = subprocess.Popen
    prebound_socket = socket.socket

    def hostile_open() -> None:
        process = prebound_popen(["/usr/bin/true"])
        process.wait()

    class HostileFinder:
        def find_spec(self) -> None:
            connection = prebound_socket()
            connection.close()

    for action in (hostile_open, HostileFinder().find_spec):
        with pytest.raises(ValidationError, match="forbidden action"):
            try:
                with overlay_module._restricted_execution_boundary(sentinel):
                    action()
            except overlay_module._ExecutionDenied as exc:
                raise ValidationError("forbidden action attempted") from exc
        assert sentinel.counts() == {
            "provider": 0,
            "network": 0,
            "subprocess": 0,
        }

    with overlay_module._restricted_execution_boundary(sentinel):
        pass
    with overlay_module._restricted_execution_boundary(sentinel):
        pass
    assert sentinel.counts() == {"provider": 0, "network": 0, "subprocess": 0}


def test_execution_rejects_callable_alias_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile, staged = _staged(tmp_path)
    from src.search_eval import skillopt_compatibility_overlay as overlay_module

    original = overlay_module._preload_exact_source_closure

    def replace_alias(root: Path) -> dict[str, object]:
        values = original(root)
        sys.modules["skillopt.engine.trainer"].merge_patches = lambda *args: None
        return values

    monkeypatch.setattr(overlay_module, "_preload_exact_source_closure", replace_alias)
    with pytest.raises(ValidationError, match="callable alias|upstream callable"):
        execute_staged_skillopt_mock_diagnostic(
            staged_root=staged,
            execution_root=tmp_path / "execution",
            profile=profile,
        )


def test_execution_requires_sole_main_thread_ownership(tmp_path: Path) -> None:
    profile, staged = _staged(tmp_path)
    ready = threading.Event()
    finish = threading.Event()

    def foreign_thread() -> None:
        ready.set()
        finish.wait()

    thread = threading.Thread(target=foreign_thread)
    thread.start()
    ready.wait()
    try:
        with pytest.raises(ValidationError, match="sole ownership"):
            execute_staged_skillopt_mock_diagnostic(
                staged_root=staged,
                execution_root=tmp_path / "execution",
                profile=profile,
            )
    finally:
        finish.set()
        thread.join()


def test_candidate_swap_restore_aba_consumes_held_fd_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile, staged = _staged(tmp_path)
    execution = tmp_path / "execution"
    from src.search_eval import skillopt_compatibility_overlay as overlay_module

    original = overlay_module._validate_candidate_lineage

    def swap_restore(lease: object, sentinel: object) -> dict[str, object]:
        result = original(lease, sentinel)
        candidate = execution / CANDIDATE_PATH
        saved = candidate.with_name("candidate.saved")
        candidate.rename(saved)
        candidate.write_bytes(b"hostile replacement")
        candidate.unlink()
        saved.rename(candidate)
        return result

    monkeypatch.setattr(overlay_module, "_validate_candidate_lineage", swap_restore)
    report = execute_staged_skillopt_mock_diagnostic(
        staged_root=staged,
        execution_root=execution,
        profile=profile,
    )
    assert report["eval"]["candidate_read_count"] == 1
    assert report["eval"]["candidate_sha256_read"] == report["candidate"]["sha256"]


@pytest.mark.parametrize(
    ("original", "hostile", "message"),
    [
        (b'"id": str(item["id"]),', b'"id": "dummy",', "seven ordered item IDs"),
        (
            b'"valid_seen": "val",',
            b'"valid_seen": "test",',
            "seven ordered item IDs|split mapping",
        ),
    ],
)
def test_actual_adapter_result_and_split_evidence_rejects_synthesis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    original: bytes,
    hostile: bytes,
    message: str,
) -> None:
    from src.search_eval import skillopt_compatibility_overlay as overlay_module

    payload = ADAPTER_BYTES.replace(original, hostile, 1)
    assert payload != ADAPTER_BYTES
    monkeypatch.setitem(overlay_module._OVERLAY_PAYLOADS, ADAPTER_PATH, payload)
    profile, staged = _staged(tmp_path)
    with pytest.raises(ValidationError, match=message):
        execute_staged_skillopt_mock_diagnostic(
            staged_root=staged,
            execution_root=tmp_path / "execution",
            profile=profile,
        )


def test_live_writer_evidence_rejects_self_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile, staged = _staged(tmp_path)
    from src.search_eval import skillopt_compatibility_overlay as overlay_module

    original = overlay_module._validate_candidate_lineage

    def self_claim(lease: object, sentinel: object) -> dict[str, object]:
        result = original(lease, sentinel)
        result["writer_open_count"] = int(result["writer_open_count"]) + 1
        return result

    monkeypatch.setattr(overlay_module, "_validate_candidate_lineage", self_claim)
    with pytest.raises(ValidationError, match="live candidate writer evidence"):
        execute_staged_skillopt_mock_diagnostic(
            staged_root=staged,
            execution_root=tmp_path / "execution",
            profile=profile,
        )


def test_canonical_config_evidence_rejects_fixed_knob_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.search_eval import skillopt_compatibility_overlay as overlay_module

    config = overlay_module._OVERLAY_PAYLOADS[PROFILE_CONFIG_PATH]
    hostile = config.replace(b"  seed: 42\n", b"  seed: 43\n", 1)
    assert hostile != config
    monkeypatch.setitem(overlay_module._OVERLAY_PAYLOADS, PROFILE_CONFIG_PATH, hostile)
    with pytest.raises(ValidationError, match="canonical rendered config hash"):
        _staged(tmp_path)
