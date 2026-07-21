from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

import tools.skillopt_compat as compat_harness
from src.search_eval.skillopt_compatibility import (
    APPROVED_ARCHIVE_SHA256,
    APPROVED_FILE_ENTRIES,
    APPROVED_PEELED_COMMIT,
    APPROVED_SOURCE_INVENTORY_IDENTITY,
    APPROVED_TAG_OBJECT,
    APPROVED_TREE_GIT_SHA1,
    seal_identity_artifact,
)
from src.search_eval.skillopt_contract import ValidationError
from src.search_eval.skillopt_materializer import materialize_skillopt_search_benchmark
from tools.skillopt_compat import (
    APPROVED_PRISTINE_MANIFEST_IDENTITY,
    DenySentinel,
    DIAGNOSTIC_CODES,
    ExecutionDenied,
    MAX_INSPECTED_AGGREGATE_BYTES,
    MAX_INSPECTED_DEPTH,
    MAX_INSPECTED_DIRECTORIES,
    MAX_INSPECTED_FILES,
    MAX_INSPECTED_FILE_BYTES,
    README_RELATIVE_PATH,
    REPORT_VERSION,
    _has_hidden_import_error,
    build_red_diagnostic_report,
    canonical_report_bytes,
    load_diagnostic_report,
    validate_diagnostic_report,
)
from tools.skillopt_compat.run_compat import _write_report, main

UPSTREAM_ROOT_ENV = "SKILLOPT_V020_UPSTREAM_ROOT"
EXACT_SOURCE_REQUIRED_ENV = "SKILLOPT_V020_EXACT_SOURCE_REQUIRED"
DEVELOPER_UPSTREAM_ROOT = Path("/private/tmp/skillopt-v020-review")
DATASET = Path("data/search_eval/skillopt_paper_search_v0.json")
CONTROL = Path("data/search_eval/skillopt_execution_control_v0.json")
BASELINE = Path("docs/skillopt_search/baseline_skill.md")
MATERIALIZER = Path("src/search_eval/skillopt_materializer.py")
MATERIALIZER_V0_SHA256 = (
    "5813cba5581e8ed193ea901171494b8ad5fe2cfae5689e0830d73984ac436950"
)


def _upstream_checkout() -> Path:
    configured = os.environ.get(UPSTREAM_ROOT_ENV)
    root = Path(configured) if configured else DEVELOPER_UPSTREAM_ROOT
    if not root.is_dir():
        message = f"exact SkillOpt v0.2.0 source unavailable: {root}"
        if os.environ.get(EXACT_SOURCE_REQUIRED_ENV) == "1":
            pytest.fail(message)
        pytest.skip(f"{message}; developer exact-source check not requested")
    return root


def _exact_git_free_export(destination: Path) -> Path:
    upstream_checkout = _upstream_checkout()
    for entry in APPROVED_FILE_ENTRIES:
        source = upstream_checkout / entry["path"]
        if not source.is_file():
            pytest.fail(f"exact upstream checkout is missing {entry['path']}")
        target = destination / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o755 if entry["mode"] == "0755" else 0o644)
    assert not (destination / ".git").exists()
    return destination


def _legacy_materialization(destination: Path) -> Path:
    materialize_skillopt_search_benchmark(
        output_dir=destination,
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE,
    )
    return destination


def _report(tmp_path: Path) -> tuple[dict, Path, Path]:
    source = _exact_git_free_export(tmp_path / "source")
    overlay = _legacy_materialization(tmp_path / "overlay")
    report = build_red_diagnostic_report(
        source_root=source,
        materialized_root=overlay,
    )
    return report, source, overlay


def test_exact_v020_legacy_materialization_stays_red_without_execution(
    tmp_path: Path,
) -> None:
    report, _, overlay = _report(tmp_path)

    assert report == validate_diagnostic_report(report)
    assert report["content_inventory_verification"] == {
        "status": "verified",
        "verification_kind": "approved_manifest_fd_lease",
        "tracked_inventory_identity": APPROVED_SOURCE_INVENTORY_IDENTITY,
        "pristine_source_manifest_identity": APPROVED_PRISTINE_MANIFEST_IDENTITY,
    }
    assert report["declared_profile_anchors"] == {
        "archive_sha256": APPROVED_ARCHIVE_SHA256,
        "peeled_commit": APPROVED_PEELED_COMMIT,
        "tag_object": APPROVED_TAG_OBJECT,
        "tree_git_sha1": APPROVED_TREE_GIT_SHA1,
    }
    assert report["authenticity_status"] == "unverified"
    assert report["seal_kind"] == "self_asserted_integrity"
    assert report["status"] == "invalid"
    assert report["evidence_class"] == "diagnostic"
    assert report["authorization_status"] == "not_authorized"
    assert report["tested_patch"] is None
    assert report["execution_counts"] == {
        "provider": 0,
        "network": 0,
        "subprocess": 0,
        "train": 0,
        "eval": 0,
    }
    assert [item["code"] for item in report["diagnostics"]] == list(DIAGNOSTIC_CODES)
    assert report["diagnostics"][1]["observed"] == "FileNotFoundError"
    assert report["diagnostics"][2]["observed"] == ["scripts/train.py"]
    assert report["diagnostics"][1]["proof"]["loader_path"] == "skillopt/config.py"
    assert report["diagnostics"][2]["proof"]["environment_absent"] is True
    assert report["diagnostics"][2]["proof"]["get_adapter_unknown_environment"] == (
        "ValueError"
    )
    assert report["diagnostics"][3]["proof"] == {
        "ast_verified": True,
        "exact_try_shape": True,
    }
    assert report["diagnostics"][4]["observed"] == "ckpt/<run>/best_skill.md"
    assert report["diagnostics"][4]["expected"] == "outputs/train/best_skill.md"
    assert report["diagnostics"][5]["proof"] == {"config_embeds_absolute_paths": True}
    assert report["diagnostics"][6]["proof"] == {"argv_identity_present": False}

    missing_base = overlay / "configs/_base_/default.yaml"
    with pytest.raises(FileNotFoundError):
        missing_base.read_bytes()

    repeated = build_red_diagnostic_report(
        source_root=tmp_path / "source",
        materialized_root=overlay,
    )
    assert repeated == report


def test_exact_source_lease_rejects_wrong_sha_changed_bytes_and_extra_file(
    tmp_path: Path,
) -> None:
    overlay = _legacy_materialization(tmp_path / "overlay")
    changed_source = _exact_git_free_export(tmp_path / "changed-source")
    changed_file = changed_source / "README.md"
    changed_file.write_bytes(changed_file.read_bytes() + b"\ntampered\n")
    with pytest.raises(ValidationError, match="sha256|size|leased"):
        build_red_diagnostic_report(
            source_root=changed_source,
            materialized_root=overlay,
        )

    extra_source = _exact_git_free_export(tmp_path / "extra-source")
    (extra_source / "untracked.txt").write_text("extra\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="manifest paths"):
        build_red_diagnostic_report(
            source_root=extra_source,
            materialized_root=overlay,
        )


def test_report_seal_rejects_tampering_wrong_sha_and_promotion(tmp_path: Path) -> None:
    report, _, _ = _report(tmp_path)

    tampered = copy.deepcopy(report)
    tampered["diagnostics"][0]["observed"] = "overlay_manifest_v1"
    with pytest.raises(ValidationError, match="identity"):
        validate_diagnostic_report(tampered)

    wrong_sha = copy.deepcopy(report)
    wrong_sha["declared_profile_anchors"]["archive_sha256"] = "0" * 64
    wrong_sha = seal_identity_artifact(wrong_sha, REPORT_VERSION)
    with pytest.raises(ValidationError, match="declared profile anchors"):
        validate_diagnostic_report(wrong_sha)

    promoted = copy.deepcopy(report)
    promoted["tested_patch"] = {"status": "passed"}
    promoted = seal_identity_artifact(promoted, REPORT_VERSION)
    with pytest.raises(ValidationError, match="never promote"):
        validate_diagnostic_report(promoted)

    attempted = copy.deepcopy(report)
    attempted["execution_counts"]["network"] = 1
    attempted = seal_identity_artifact(attempted, REPORT_VERSION)
    with pytest.raises(ValidationError, match="forbidden execution attempts"):
        validate_diagnostic_report(attempted)


def test_bounded_cli_writes_the_same_sealed_red_report(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    source = _exact_git_free_export(tmp_path / "source")
    overlay = _legacy_materialization(tmp_path / "overlay")
    report_path = tmp_path / "reports/red.json"

    assert (
        main(
            [
                "--source-root",
                str(source),
                "--materialized-root",
                str(overlay),
                "--report",
                str(report_path),
            ]
        )
        == 0
    )
    stdout = capfd.readouterr().out.encode("utf-8")
    report = load_diagnostic_report(report_path)
    assert stdout == canonical_report_bytes(report)
    assert json.loads(stdout)["execution_counts"] == {
        "provider": 0,
        "network": 0,
        "subprocess": 0,
        "train": 0,
        "eval": 0,
    }


def test_historical_v0_materializer_bytes_are_immutable() -> None:
    assert (
        hashlib.sha256(MATERIALIZER.read_bytes()).hexdigest() == MATERIALIZER_V0_SHA256
    )


def test_exact_source_required_never_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(UPSTREAM_ROOT_ENV, str(tmp_path / "missing-upstream"))
    monkeypatch.setenv(EXACT_SOURCE_REQUIRED_ENV, "1")
    with pytest.raises(
        pytest.fail.Exception, match="exact SkillOpt v0.2.0 source unavailable"
    ):
        _upstream_checkout()


def test_approved_source_lease_precedes_overlay_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _exact_git_free_export(tmp_path / "source")
    overlay = _legacy_materialization(tmp_path / "overlay")
    state = {"source_leased": False}
    real_acquire = compat_harness.acquire_approved_source_tree_lease
    real_snapshot = compat_harness._snapshot_manifest

    @contextmanager
    def tracked_acquire(root: Path, manifest: dict):
        with real_acquire(root, manifest) as lease:
            state["source_leased"] = True
            try:
                yield lease
            finally:
                state["source_leased"] = False

    def checked_snapshot(root: Path) -> dict:
        assert state["source_leased"] is True
        return real_snapshot(root)

    monkeypatch.setattr(
        compat_harness, "acquire_approved_source_tree_lease", tracked_acquire
    )
    monkeypatch.setattr(compat_harness, "_snapshot_manifest", checked_snapshot)
    build_red_diagnostic_report(source_root=source, materialized_root=overlay)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("file_count", "too many files"),
        ("directory_count", "too many directories"),
        ("depth", "maximum depth"),
        ("file_bytes", "oversized file"),
        ("aggregate_bytes", "aggregate byte limit"),
    ],
)
def test_untrusted_overlay_inspection_is_bounded(
    tmp_path: Path, mutation: str, message: str
) -> None:
    source = _exact_git_free_export(tmp_path / "source")
    overlay = _legacy_materialization(tmp_path / "overlay")
    hostile = overlay / "hostile"
    hostile.mkdir()
    if mutation == "file_count":
        for index in range(MAX_INSPECTED_FILES + 1):
            (hostile / f"file-{index:04d}").touch()
    elif mutation == "directory_count":
        for index in range(MAX_INSPECTED_DIRECTORIES + 1):
            (hostile / f"dir-{index:04d}").mkdir()
    elif mutation == "depth":
        deep = hostile.joinpath(*[f"d{index}" for index in range(MAX_INSPECTED_DEPTH)])
        deep.mkdir(parents=True)
    elif mutation == "file_bytes":
        (hostile / "oversized").write_bytes(b"x" * (MAX_INSPECTED_FILE_BYTES + 1))
    elif mutation == "aggregate_bytes":
        chunk = b"x" * MAX_INSPECTED_FILE_BYTES
        for index in range(MAX_INSPECTED_AGGREGATE_BYTES // len(chunk) + 1):
            (hostile / f"chunk-{index}").write_bytes(chunk)
    with pytest.raises(ValidationError, match=message):
        build_red_diagnostic_report(source_root=source, materialized_root=overlay)


@pytest.mark.parametrize("swap_kind", ["symlink", "hardlink", "oversize"])
def test_snapshot_rejects_file_swaps_before_reading_outside_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap_kind: str
) -> None:
    overlay = _legacy_materialization(tmp_path / "overlay")
    target = overlay / README_RELATIVE_PATH
    outside = tmp_path / "outside"
    outside.write_bytes(
        b"outside" if swap_kind != "oversize" else b"x" * (MAX_INSPECTED_FILE_BYTES + 1)
    )
    outside_inode = outside.stat().st_ino
    original_open = os.open
    original_read = os.read
    swapped = False

    def racing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if (
            dir_fd is not None
            and os.fspath(path) == README_RELATIVE_PATH
            and not swapped
        ):
            swapped = True
            target.unlink()
            if swap_kind == "symlink":
                target.symlink_to(outside)
            elif swap_kind == "hardlink":
                os.link(outside, target)
            else:
                os.replace(outside, target)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    def reject_outside_read(fd: int, size: int) -> bytes:
        assert os.fstat(fd).st_ino != outside_inode
        return original_read(fd, size)

    monkeypatch.setattr(compat_harness.os, "open", racing_open)
    monkeypatch.setattr(compat_harness.os, "read", reject_outside_read)
    with pytest.raises(ValidationError, match="changed during inspection"):
        compat_harness._snapshot_manifest(overlay)
    assert swapped is True


def test_snapshot_rejects_aba_name_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overlay = _legacy_materialization(tmp_path / "overlay")
    target = overlay / README_RELATIVE_PATH
    target_inode = target.stat().st_ino
    original_read = os.read
    swapped = False

    def aba_read(fd: int, size: int) -> bytes:
        nonlocal swapped
        if not swapped and os.fstat(fd).st_ino == target_inode:
            swapped = True
            parked = overlay / "README.parked"
            target.rename(parked)
            target.write_bytes(b"hostile replacement")
            target.unlink()
            parked.rename(target)
        return original_read(fd, size)

    monkeypatch.setattr(compat_harness.os, "read", aba_read)
    with pytest.raises(ValidationError, match="changed during inspection"):
        compat_harness._snapshot_manifest(overlay)
    assert swapped is True


def test_snapshot_closes_every_opened_fd_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overlay = _legacy_materialization(tmp_path / "overlay")
    (overlay / "hostile-link").symlink_to(tmp_path / "outside")
    original_open = os.open
    original_close = os.close
    opened: set[int] = set()

    def tracked_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        fd = original_open(path, flags, mode, dir_fd=dir_fd)
        opened.add(fd)
        return fd

    def tracked_close(fd: int) -> None:
        opened.discard(fd)
        original_close(fd)

    monkeypatch.setattr(compat_harness.os, "open", tracked_open)
    monkeypatch.setattr(compat_harness.os, "close", tracked_close)
    with pytest.raises(ValidationError, match="must not contain symlinks"):
        compat_harness._snapshot_manifest(overlay)
    assert opened == set()


@pytest.mark.parametrize("git_kind", ["directory", "file"])
def test_exact_source_rejects_git_metadata(tmp_path: Path, git_kind: str) -> None:
    source = _exact_git_free_export(tmp_path / f"source-{git_kind}")
    overlay = _legacy_materialization(tmp_path / f"overlay-{git_kind}")
    git_path = source / ".git"
    if git_kind == "directory":
        git_path.mkdir()
    else:
        git_path.write_text("gitdir: elsewhere\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="manifest paths|manifest directories"):
        build_red_diagnostic_report(source_root=source, materialized_root=overlay)


def test_hidden_import_error_requires_the_exact_single_try_shape() -> None:
    exact = """try:
    from skillopt.envs.jiphyeonjeon_search.adapter import JiphyeonjeonSearchAdapter
    _ENV_REGISTRY[\"jiphyeonjeon_search\"] = JiphyeonjeonSearchAdapter
except ImportError:
    pass
"""
    assert _has_hidden_import_error(exact) is True
    near_misses = [
        exact + "extra = True\n",
        exact.replace(
            "JiphyeonjeonSearchAdapter\n", "JiphyeonjeonSearchAdapter as Adapter\n", 1
        ),
        exact.replace('["jiphyeonjeon_search"]', '["other"]'),
        exact.replace("except ImportError:", "except Exception:"),
        exact.replace("    pass\n", "    pass\n    raise\n"),
        exact.replace("except ImportError:\n", "except ImportError:\n", 1)
        + "except RuntimeError:\n    pass\n",
        exact.replace(
            "except ImportError:\n    pass",
            "except ImportError:\n    pass\nelse:\n    pass",
        ),
        exact.replace(
            '_ENV_REGISTRY["jiphyeonjeon_search"] = JiphyeonjeonSearchAdapter',
            '_ENV_REGISTRY["jiphyeonjeon_search"] = object',
        ),
    ]
    assert all(_has_hidden_import_error(snippet) is False for snippet in near_misses)


@pytest.mark.parametrize(
    ("kind", "api"),
    [
        ("provider", "provider_import"),
        ("train", "train_import"),
        ("eval", "eval_import"),
        ("network", "socket"),
        ("network", "create_connection"),
        ("subprocess", "run"),
        ("subprocess", "popen"),
        ("subprocess", "system"),
    ],
)
def test_restricted_boundary_blocks_real_hostile_apis_and_restores(
    kind: str, api: str
) -> None:
    sentinel = DenySentinel()
    original_socket = socket.socket
    original_run = subprocess.run
    original_system = os.system
    with pytest.raises(ExecutionDenied, match="denied before execution"):
        with compat_harness._restricted_execution_boundary(sentinel):
            if api == "provider_import":
                sentinel.guarded_import("openai")
            elif api == "train_import":
                sentinel.guarded_import("scripts.train")
            elif api == "eval_import":
                sentinel.guarded_import("scripts.eval_only")
            elif api == "socket":
                socket.socket()
            elif api == "create_connection":
                socket.create_connection(("127.0.0.1", 9))
            elif api == "run":
                subprocess.run(["false"], check=False)
            elif api == "popen":
                subprocess.Popen(["false"])
            else:
                os.system("false")
    assert sentinel.counts() == {
        item: int(item == kind)
        for item in ("provider", "network", "subprocess", "train", "eval")
    }
    assert socket.socket is original_socket
    assert subprocess.run is original_run
    assert os.system is original_system


def _restricted_hook_snapshot() -> dict[tuple[object, str], object]:
    targets = (
        (socket, "socket"),
        (socket, "create_connection"),
        (socket, "create_server"),
        (subprocess, "Popen"),
        (subprocess, "run"),
        (subprocess, "call"),
        (subprocess, "check_call"),
        (subprocess, "check_output"),
        (subprocess, "getoutput"),
        (subprocess, "getstatusoutput"),
        (os, "system"),
    )
    return {(owner, name): getattr(owner, name) for owner, name in targets}


def _assert_restricted_hooks_match(
    expected: dict[tuple[object, str], object],
) -> None:
    assert all(
        getattr(owner, name) is original for (owner, name), original in expected.items()
    )


def test_restricted_boundary_same_thread_nesting_restores_each_layer() -> None:
    originals = _restricted_hook_snapshot()
    outer_sentinel = DenySentinel()
    inner_sentinel = DenySentinel()

    with compat_harness._restricted_execution_boundary(outer_sentinel):
        outer_hooks = _restricted_hook_snapshot()
        assert all(
            outer_hooks[target] is not original
            for target, original in originals.items()
        )
        with compat_harness._restricted_execution_boundary(inner_sentinel):
            inner_hooks = _restricted_hook_snapshot()
            assert all(
                inner_hooks[target] is not outer
                for target, outer in outer_hooks.items()
            )
            with pytest.raises(ExecutionDenied, match="network denied"):
                socket.socket()
        _assert_restricted_hooks_match(outer_hooks)
        with pytest.raises(ExecutionDenied, match="subprocess denied"):
            subprocess.run(["false"], check=False)

    _assert_restricted_hooks_match(originals)
    assert outer_sentinel.counts() == {
        "provider": 0,
        "network": 0,
        "subprocess": 1,
        "train": 0,
        "eval": 0,
    }
    assert inner_sentinel.counts() == {
        "provider": 0,
        "network": 1,
        "subprocess": 0,
        "train": 0,
        "eval": 0,
    }


def test_restricted_boundary_serializes_two_threads_and_restores_all_hooks() -> None:
    originals = _restricted_hook_snapshot()
    first_sentinel = DenySentinel()
    second_sentinel = DenySentinel()
    first_entered = threading.Event()
    second_attempted = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()
    first_exited = threading.Event()
    failures: list[BaseException] = []

    def first_boundary() -> None:
        try:
            with compat_harness._restricted_execution_boundary(first_sentinel):
                with pytest.raises(ExecutionDenied, match="network denied"):
                    socket.socket()
                first_entered.set()
                assert release_first.wait(timeout=5)
            first_exited.set()
        except BaseException as exc:
            failures.append(exc)

    def second_boundary() -> None:
        try:
            assert first_entered.wait(timeout=5)
            second_attempted.set()
            with compat_harness._restricted_execution_boundary(second_sentinel):
                assert first_exited.is_set()
                second_entered.set()
                with pytest.raises(ExecutionDenied, match="subprocess denied"):
                    os.system("false")
        except BaseException as exc:
            failures.append(exc)

    first = threading.Thread(target=first_boundary)
    second = threading.Thread(target=second_boundary)
    first.start()
    assert first_entered.wait(timeout=5)
    second.start()
    try:
        assert second_attempted.wait(timeout=5)
        second.join(timeout=0.1)
        assert second.is_alive()
        assert not second_entered.is_set()
    finally:
        release_first.set()
        first.join(timeout=5)
        second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert failures == []
    assert second_entered.is_set()
    _assert_restricted_hooks_match(originals)
    assert first_sentinel.counts() == {
        "provider": 0,
        "network": 1,
        "subprocess": 0,
        "train": 0,
        "eval": 0,
    }
    assert second_sentinel.counts() == {
        "provider": 0,
        "network": 0,
        "subprocess": 1,
        "train": 0,
        "eval": 0,
    }


def test_restricted_boundary_ownership_drift_restores_every_hook() -> None:
    originals = _restricted_hook_snapshot()
    sentinel = DenySentinel()
    drifted_socket = object()

    with pytest.raises(ValidationError, match="lost hook ownership: socket.socket"):
        with compat_harness._restricted_execution_boundary(sentinel):
            socket.socket = drifted_socket  # type: ignore[assignment]

    _assert_restricted_hooks_match(originals)
    assert sentinel.counts() == {
        "provider": 0,
        "network": 0,
        "subprocess": 0,
        "train": 0,
        "eval": 0,
    }


def _cli_arguments(source: Path, overlay: Path, report_path: Path) -> list[str]:
    return [
        "--source-root",
        str(source),
        "--materialized-root",
        str(overlay),
        "--report",
        str(report_path),
    ]


def test_report_output_rejects_input_overwrite_attempts(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    source = _exact_git_free_export(tmp_path / "source")
    overlay = _legacy_materialization(tmp_path / "overlay")
    protected = [
        source / "README.md",
        overlay / "README.md",
        Path("data/search_eval/skillopt_compatibility_profiles_v1.json"),
    ]
    before = {path: path.read_bytes() for path in protected}
    for report_path in protected:
        assert main(_cli_arguments(source, overlay, report_path)) == 2
        capfd.readouterr()
    assert {path: path.read_bytes() for path in protected} == before


def test_report_output_rejects_symlink_parent_leaf_and_hardlink(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    source = _exact_git_free_export(tmp_path / "source")
    overlay = _legacy_materialization(tmp_path / "overlay")
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    symlink_parent = tmp_path / "symlink-parent"
    symlink_parent.symlink_to(real_parent, target_is_directory=True)
    assert main(_cli_arguments(source, overlay, symlink_parent / "red.json")) == 2
    capfd.readouterr()

    leaf_target = tmp_path / "leaf-target"
    leaf_target.write_text("unchanged", encoding="utf-8")
    symlink_leaf = tmp_path / "symlink-leaf.json"
    symlink_leaf.symlink_to(leaf_target)
    assert main(_cli_arguments(source, overlay, symlink_leaf)) == 2
    capfd.readouterr()
    assert leaf_target.read_text(encoding="utf-8") == "unchanged"

    hardlink_source = tmp_path / "hardlink-source"
    hardlink_source.write_text("unchanged", encoding="utf-8")
    hardlink_leaf = tmp_path / "hardlink-leaf.json"
    os.link(hardlink_source, hardlink_leaf)
    assert main(_cli_arguments(source, overlay, hardlink_leaf)) == 2
    capfd.readouterr()
    assert hardlink_source.read_text(encoding="utf-8") == "unchanged"


def test_report_write_is_atomic_on_failure_and_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "reports/red.json"
    report_path.parent.mkdir()
    report_path.write_bytes(b"previous\n")
    original_write = os.write

    def fail_write(fd: int, payload: bytes) -> int:
        raise OSError("injected write failure")

    monkeypatch.setattr("tools.skillopt_compat.run_compat.os.write", fail_write)
    with pytest.raises(OSError, match="injected write failure"):
        _write_report(report_path, b"replacement\n", forbidden_inputs=())
    assert report_path.read_bytes() == b"previous\n"
    assert list(report_path.parent.glob(".red.json.tmp-*")) == []

    monkeypatch.setattr("tools.skillopt_compat.run_compat.os.write", original_write)
    _write_report(report_path, b"replacement\n", forbidden_inputs=())
    assert report_path.read_bytes() == b"replacement\n"
