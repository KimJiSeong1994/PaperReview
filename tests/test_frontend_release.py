from __future__ import annotations

import io
import json
import os
import platform
import tarfile
from pathlib import Path

import pytest

from scripts import frontend_release


def _archive(path: Path, files: dict[str, bytes], *, link: tuple[str, str, bytes] | None = None) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, body in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
        if link:
            name, target, kind = link
            info = tarfile.TarInfo(name)
            info.type = kind
            info.linkname = target
            archive.addfile(info)


def _valid_archive(path: Path, marker: str = "new") -> None:
    _archive(
        path,
        {
            "index.html": f'<script type="module" src="/assets/app-new.js"></script>{marker}'.encode(),
            "assets/app-new.js": marker.encode(),
        },
    )


def _active(root: Path, marker: str = "old") -> Path:
    active = root / "dist"
    (active / "assets").mkdir(parents=True)
    (active / "index.html").write_text(
        f'<script type="module" src="/assets/app-old.abc123.js"></script>{marker}'
    )
    (active / "assets" / "app-old.abc123.js").write_text(marker)
    return active


def _portable_exchange(left: Path, right: Path) -> None:
    temporary = left.parent / ".test-exchange"
    os.rename(left, temporary)
    os.rename(right, left)
    os.rename(temporary, right)


def _persisted_promotion_crash(
    root: Path, state: str
) -> tuple[Path, Path, Path]:
    active = _active(root)
    archive = root / "crashed-release.tar.gz"
    _valid_archive(archive, "crashed-new")
    stage, previous, journal = frontend_release._paths(active, "crashed-release")
    frontend_release._extract_archive(archive, stage)
    frontend_release.validate_stage(stage)
    frontend_release._retain_existing_assets(active, stage)
    frontend_release._write_json(
        stage / frontend_release.ACTIVATION_FILE,
        {"release_id": "crashed-release", "source_sha": "c" * 40},
    )
    record: dict[str, object] = {
        "release_id": "crashed-release",
        "source_sha": "c" * 40,
        "active_path": str(active),
        "previous_path": str(previous),
        "activated_identity": frontend_release._tree_identity(stage),
        "previous_identity": frontend_release._tree_identity(active),
        "previous_non_asset_identity": frontend_release._tree_identity(
            active, exclude_assets=True
        ),
        "status": "prepared" if state == "before_exchange_prepared" else "promotion_intent",
    }
    frontend_release._write_json(journal, record)
    if state in {"after_exchange", "after_rename", "activated"}:
        _portable_exchange(active, stage)
    if state in {"after_rename", "activated"}:
        os.replace(stage, previous)
    if state == "activated":
        record["status"] = "activated"
        frontend_release._write_json(journal, record)
    return active, previous, journal


@pytest.mark.parametrize(
    ("name", "link"),
    [
        ("../escaped.txt", None),
        ("assets/link.js", ("assets/link.js", "app.js", tarfile.SYMTYPE)),
        ("assets/hard.js", ("assets/hard.js", "assets/app.js", tarfile.LNKTYPE)),
    ],
)
def test_rejects_unsafe_archive_members_without_touching_active(
    tmp_path: Path, name: str, link: tuple[str, str, bytes] | None
) -> None:
    active = _active(tmp_path)
    archive = tmp_path / "release.tar.gz"
    files = {name: b"bad"} if link is None else {"index.html": b"ok"}
    _archive(archive, files, link=link)

    with pytest.raises(frontend_release.ReleaseError):
        frontend_release.promote_release(archive, active, "bad-release")

    assert (active / "index.html").read_text().endswith("old")
    assert not (tmp_path / "escaped.txt").exists()


def test_missing_referenced_asset_fails_before_promotion(tmp_path: Path) -> None:
    active = _active(tmp_path)
    archive = tmp_path / "release.tar.gz"
    _archive(archive, {"index.html": b'<script src="/assets/missing.js"></script>'})

    with pytest.raises(frontend_release.ReleaseError, match="missing referenced file"):
        frontend_release.promote_release(archive, active, "missing-asset")

    assert (active / "index.html").read_text().endswith("old")


def test_promote_retains_old_hashed_assets_and_records_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = _active(tmp_path)
    archive = tmp_path / "release.tar.gz"
    _valid_archive(archive)
    monkeypatch.setattr(frontend_release, "_rename_exchange", _portable_exchange)

    journal_path = frontend_release.promote_release(archive, active, "release-1", source_sha="a" * 40)

    assert (active / "index.html").read_text().endswith("new")
    assert (active / "assets" / "app-old.abc123.js").read_text() == "old"
    journal = json.loads(journal_path.read_text())
    previous = Path(journal["previous_path"])
    assert (previous / "index.html").read_text().endswith("old")
    assert json.loads((active / frontend_release.ACTIVATION_FILE).read_text())["release_id"] == "release-1"

    frontend_release.rollback_release(active, journal_path)

    assert (active / "index.html").read_text().endswith("old")
    assert (previous / "index.html").read_text().endswith("new")
    assert (active / "assets" / "app-new.js").read_text() == "new"
    assert (active / "assets" / "app-old.abc123.js").read_text() == "old"
    assert json.loads(journal_path.read_text())["status"] == "rolled_back"

    frontend_release.rollback_release(active, journal_path)
    assert (active / "index.html").read_text().endswith("old")
    assert json.loads(journal_path.read_text())["status"] == "rolled_back"


def test_unsupported_atomic_exchange_preserves_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = _active(tmp_path)
    archive = tmp_path / "release.tar.gz"
    _valid_archive(archive)

    def unsupported(left: Path, right: Path) -> None:
        raise frontend_release.ReleaseError("renameat2 unavailable")

    monkeypatch.setattr(frontend_release, "_rename_exchange", unsupported)
    with pytest.raises(frontend_release.ReleaseError, match="unavailable"):
        frontend_release.promote_release(archive, active, "release-2")

    assert active.is_dir()
    assert (active / "index.html").read_text().endswith("old")


def test_first_install_uses_replace_without_exchange(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = tmp_path / "dist"
    archive = tmp_path / "release.tar.gz"
    _valid_archive(archive)
    monkeypatch.setattr(
        frontend_release,
        "_rename_exchange",
        lambda left, right: pytest.fail("first install must not use exchange"),
    )

    journal_path = frontend_release.promote_release(archive, active, "first-release")

    assert (active / "index.html").read_text().endswith("new")
    assert json.loads(journal_path.read_text())["previous_path"] is None


def test_failure_after_exchange_restores_previous_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = _active(tmp_path)
    archive = tmp_path / "release.tar.gz"
    _valid_archive(archive)
    monkeypatch.setattr(frontend_release, "_rename_exchange", _portable_exchange)
    original_write = frontend_release._write_json
    def fail_final_journal(path: Path, payload: dict[str, object]) -> None:
        if payload.get("status") == "activated":
            raise OSError("simulated journal failure")
        original_write(path, payload)

    monkeypatch.setattr(frontend_release, "_write_json", fail_final_journal)
    with pytest.raises(OSError, match="simulated journal failure"):
        frontend_release.promote_release(archive, active, "restore-on-failure")

    assert active.is_dir()
    assert (active / "index.html").read_text().endswith("old")


@pytest.mark.parametrize(
    ("reference", "filename"),
    [
        ('<link rel="icon" href="/favicon.svg">', "favicon.svg"),
        ('<link rel="manifest" href="/manifest.json">', "manifest.json"),
        ('<img src="/hero.png">', "hero.png"),
    ],
)
def test_rejects_missing_root_file_references(
    tmp_path: Path, reference: str, filename: str
) -> None:
    archive = tmp_path / "release.tar.gz"
    _archive(
        archive,
        {
            "index.html": (
                '<script type="module" src="/assets/app.js"></script>' + reference
            ).encode(),
            "assets/app.js": b"ok",
        },
    )

    with pytest.raises(frontend_release.ReleaseError, match=filename):
        frontend_release.preflight_archive(archive, tmp_path / "dist", f"missing-{filename}")


def test_accepts_backend_figure_reference_and_validates_every_html_entrypoint(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "release.tar.gz"
    files = {
        "index.html": (
            '<script type="module" src="/assets/app.js"></script>'
            '<img src="/api/blog/figures/paper.png">'
        ).encode(),
        "introduce/index.html": b'<script type="module" src="/assets/app.js"></script>',
        "assets/app.js": b"ok",
    }
    _archive(archive, files)
    frontend_release.preflight_archive(archive, tmp_path / "dist", "api-figure")

    files["introduce/index.html"] = b'<script type="module" src="/assets/missing.js"></script>'
    _archive(tmp_path / "bad.tar.gz", files)
    with pytest.raises(frontend_release.ReleaseError, match="introduce/index.html"):
        frontend_release.preflight_archive(
            tmp_path / "bad.tar.gz", tmp_path / "dist", "bad-static-entry"
        )


def test_does_not_whitelist_arbitrary_api_shaped_file_reference(tmp_path: Path) -> None:
    archive = tmp_path / "release.tar.gz"
    _archive(
        archive,
        {
            "index.html": (
                '<script type="module" src="/assets/app.js"></script>'
                '<img src="/api/not-a-static-backend-route.png">'
            ).encode(),
            "assets/app.js": b"ok",
        },
    )
    with pytest.raises(frontend_release.ReleaseError, match="not-a-static-backend-route"):
        frontend_release.preflight_archive(archive, tmp_path / "dist", "arbitrary-api")


@pytest.mark.parametrize("body", [b"", b"<html>no JavaScript entry</html>"])
def test_rejects_empty_or_scriptless_index(tmp_path: Path, body: bytes) -> None:
    archive = tmp_path / "release.tar.gz"
    _archive(archive, {"index.html": body})
    with pytest.raises(frontend_release.ReleaseError):
        frontend_release.preflight_archive(archive, tmp_path / "dist", "invalid-index")


def test_rollback_rejects_conflicting_hashed_asset_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = _active(tmp_path)
    archive = tmp_path / "release.tar.gz"
    _archive(
        archive,
        {
            "index.html": b'<script type="module" src="/assets/app-old.abc123.js"></script>',
            "assets/app-old.abc123.js": b"different-new-bytes",
        },
    )
    monkeypatch.setattr(frontend_release, "_rename_exchange", _portable_exchange)

    with pytest.raises(frontend_release.ReleaseError, match="collision"):
        frontend_release.promote_release(archive, active, "collision")
    assert (active / "assets" / "app-old.abc123.js").read_text() == "old"


def test_rollback_recovers_when_completion_journal_write_failed_after_exchange(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = _active(tmp_path)
    archive = tmp_path / "release.tar.gz"
    _valid_archive(archive)
    monkeypatch.setattr(frontend_release, "_rename_exchange", _portable_exchange)
    journal = frontend_release.promote_release(archive, active, "retry-rollback")
    original_write = frontend_release._write_json

    def fail_completion(path: Path, payload: dict[str, object]) -> None:
        if payload.get("status") == "rolled_back":
            raise OSError("post-exchange journal failure")
        original_write(path, payload)

    monkeypatch.setattr(frontend_release, "_write_json", fail_completion)
    with pytest.raises(OSError, match="post-exchange"):
        frontend_release.rollback_release(active, journal)
    assert (active / "index.html").read_text().endswith("old")
    assert json.loads(journal.read_text())["status"] == "rollback_intent"

    monkeypatch.setattr(frontend_release, "_write_json", original_write)
    frontend_release.rollback_release(active, journal)
    assert json.loads(journal.read_text())["status"] == "rolled_back"
    assert (active / "assets" / "app-new.js").read_text() == "new"


@pytest.mark.parametrize(
    "state",
    [
        "before_exchange_prepared",
        "before_exchange_intent",
        "after_exchange",
        "after_rename",
        "activated",
    ],
)
def test_rollback_recovers_every_persisted_promotion_crash_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    monkeypatch.setattr(frontend_release, "_rename_exchange", _portable_exchange)
    active, previous, journal = _persisted_promotion_crash(tmp_path, state)

    frontend_release.rollback_release(active, journal)

    assert (active / "index.html").read_text().endswith("old")
    assert (active / "assets" / "app-new.js").read_text() == "crashed-new"
    assert (previous / "index.html").read_text().endswith("crashed-new")
    assert json.loads(journal.read_text())["status"] == "rolled_back"
    frontend_release.rollback_release(active, journal)


@pytest.mark.parametrize("state", ["before_exchange_intent", "after_rename"])
def test_rollback_resumes_after_crash_during_asset_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    monkeypatch.setattr(frontend_release, "_rename_exchange", _portable_exchange)
    active, previous, journal = _persisted_promotion_crash(tmp_path, state)
    record = json.loads(journal.read_text())
    record["status"] = "rollback_intent"
    frontend_release._write_json(journal, record)
    if state == "before_exchange_intent":
        stage, _, _ = frontend_release._paths(active, "crashed-release")
        source = stage / "assets" / "app-new.js"
        destination = active / "assets" / "app-new.js"
    else:
        source = active / "assets" / "app-new.js"
        destination = previous / "assets" / "app-new.js"
    os.link(source, destination)

    frontend_release.rollback_release(active, journal)

    assert (active / "index.html").read_text().endswith("old")
    assert (active / "assets" / "app-new.js").read_text() == "crashed-new"
    assert json.loads(journal.read_text())["status"] == "rolled_back"


def _path_snapshot(path: Path) -> tuple[tuple[str, bytes | None], ...]:
    if not path.exists():
        return (("<missing>", None),)
    if path.is_file():
        return (("<file>", path.read_bytes()),)
    return tuple(
        (item.relative_to(path).as_posix(), item.read_bytes() if item.is_file() else None)
        for item in sorted(path.rglob("*"))
    )


@pytest.mark.parametrize(
    ("state", "status"),
    [
        ("before_exchange_prepared", "prepared"),
        ("after_rename", "promotion_intent"),
        ("activated", "activated"),
        ("after_rename", "rollback_intent"),
    ],
)
def test_next_preflight_blocks_unfinished_journal_without_mutating_release_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, status: str
) -> None:
    monkeypatch.setattr(frontend_release, "_rename_exchange", _portable_exchange)
    active, previous, crashed_journal = _persisted_promotion_crash(tmp_path, state)
    record = json.loads(crashed_journal.read_text())
    record["status"] = status
    frontend_release._write_json(crashed_journal, record)
    stage, _, _ = frontend_release._paths(active, "crashed-release")
    next_archive = tmp_path / "next-release.tar.gz"
    _archive(
        next_archive,
        {
            "index.html": b'<script type="module" src="/assets/next.js"></script>',
            "assets/next.js": b"next",
        },
    )
    watched = (active, stage, previous, crashed_journal)
    before = tuple(_path_snapshot(path) for path in watched)

    with pytest.raises(frontend_release.ReleaseError, match="blocks preflight"):
        frontend_release.preflight_archive(next_archive, active, "next-release")

    assert tuple(_path_snapshot(path) for path in watched) == before
    next_stage, _, next_journal = frontend_release._paths(active, "next-release")
    assert not next_stage.exists()
    assert not next_journal.exists()


def test_verified_release_is_not_reconciled_by_next_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = _active(tmp_path)
    archive = tmp_path / "release.tar.gz"
    next_archive = tmp_path / "next.tar.gz"
    _valid_archive(archive, "verified-new")
    _valid_archive(next_archive, "next-new")
    monkeypatch.setattr(frontend_release, "_rename_exchange", _portable_exchange)
    journal = frontend_release.promote_release(archive, active, "verified-release")

    frontend_release.finalize_release(active, journal)
    frontend_release.finalize_release(active, journal)
    frontend_release.preflight_archive(next_archive, active, "next-preflight")

    assert (active / "index.html").read_text().endswith("verified-new")
    assert json.loads(journal.read_text())["status"] == "verified"


def test_rolled_back_release_does_not_block_next_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(frontend_release, "_rename_exchange", _portable_exchange)
    active, _, journal = _persisted_promotion_crash(tmp_path, "activated")
    frontend_release.rollback_release(active, journal)
    next_archive = tmp_path / "next.tar.gz"
    _valid_archive(next_archive, "next")

    frontend_release.preflight_archive(next_archive, active, "after-rollback")

    assert json.loads(journal.read_text())["status"] == "rolled_back"


def test_workflow_persists_journal_pointer_before_promotion_and_rolls_back_on_cancel() -> None:
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text()
    promote = workflow[workflow.index("      - name: Atomically promote frontend") :]
    pointer_write = 'printf \'%s\\n\' "$JOURNAL" > "$REMOTE_RELEASE/frontend-journal.path"'
    assert promote.index(pointer_write) < promote.index('frontend_release.py" promote')
    assert "if: (failure() || cancelled())" in promote
    assert 'if test -f "$JOURNAL"' in promote
    assert 'frontend_release.py" finalize' in promote


def test_workflow_owns_durable_recovery_marker_before_backend_checkout() -> None:
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text()
    deploy = workflow[workflow.index("  deploy:") :]
    assert deploy.index("deployment_state.py\" ensure-clear") < deploy.index(
        'frontend_release.py" preflight'
    )
    assert deploy.index("deployment_state.py\" begin") < deploy.index(
        'git checkout --detach --force "$DEPLOY_SHA"'
    )
    assert '--state-root "$APP_ROOT/.deploy-state"' in deploy
    assert '--helper "frontend_release.py=$REMOTE_RELEASE/frontend_release.py"' in deploy
    rollback = deploy[deploy.index("Roll back frontend and backend") :]
    assert 'if ! "$APP_ROOT/venv/bin/python" "$REMOTE_RELEASE/deployment_state.py" owns' in rollback
    assert rollback.index(" owns \\") < rollback.index('checkout --detach --force "$PREVIOUS_SHA"')
    assert 'test "$ROLLBACK_FAILED" -eq 0' in rollback
    assert '"$STATE_HELPER" clear' in rollback


def test_stale_rollback_journal_cannot_replace_a_newer_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = _active(tmp_path)
    first_archive = tmp_path / "first.tar.gz"
    second_archive = tmp_path / "second.tar.gz"
    _valid_archive(first_archive, "first")
    _archive(
        second_archive,
        {
            "index.html": b'<script type="module" src="/assets/app-second.js"></script>second',
            "assets/app-second.js": b"second",
        },
    )
    monkeypatch.setattr(frontend_release, "_rename_exchange", _portable_exchange)
    first_journal = frontend_release.promote_release(first_archive, active, "first")
    frontend_release.promote_release(second_archive, active, "second")

    with pytest.raises(frontend_release.ReleaseError, match="stale rollback"):
        frontend_release.rollback_release(active, first_journal)
    assert (active / "index.html").read_text().endswith("second")


@pytest.mark.skipif(platform.system() != "Linux", reason="renameat2 is Linux-specific")
def test_linux_exchange_keeps_both_complete_directories(tmp_path: Path) -> None:
    active = _active(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "index.html").write_text("new")

    frontend_release._rename_exchange(active, stage)

    assert active.is_dir() and stage.is_dir()
    assert (active / "index.html").read_text() == "new"
    assert (stage / "index.html").read_text() == "old"
