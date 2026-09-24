#!/usr/bin/env python3
"""Validate, atomically promote, and roll back frontend release archives."""

from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
from typing import BinaryIO
from urllib.parse import unquote, urlsplit


ACTIVATION_FILE = ".frontend-release.json"
_RELEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_RENAME_EXCHANGE = 2
_AT_FDCWD = -100


class ReleaseError(RuntimeError):
    """A release failed validation or could not be safely activated."""


class _AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[tuple[str, str]] = []
        self.script_references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("src"):
            reference = values["src"] or ""
            self.references.append((tag, reference))
            if tag == "script":
                self.script_references.append(reference)
        rel = set((values.get("rel") or "").split())
        if values.get("href") and rel.intersection(
            {"stylesheet", "icon", "modulepreload", "preload", "manifest"}
        ):
            self.references.append((tag, values["href"] or ""))


def _safe_member_name(raw_name: str) -> Path | None:
    normalized = raw_name.removeprefix("./")
    if normalized in {"", "."}:
        return None
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise ReleaseError(f"unsafe archive path: {raw_name!r}")
    return Path(*candidate.parts)


def _copy_file(source: BinaryIO, destination: Path, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        shutil.copyfileobj(source, output)
    destination.chmod(mode & 0o777 or 0o644)


def _extract_archive(archive_path: Path, stage: Path) -> None:
    seen: set[Path] = set()
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            relative = _safe_member_name(member.name)
            if relative is None:
                continue
            if relative in seen:
                raise ReleaseError(f"duplicate archive path: {member.name!r}")
            seen.add(relative)
            if not (member.isdir() or member.isfile()):
                raise ReleaseError(f"archive links and special files are forbidden: {member.name!r}")

        stage.mkdir(mode=0o755)
        for member in members:
            relative = _safe_member_name(member.name)
            if relative is None:
                continue
            destination = stage / relative
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            source = archive.extractfile(member)
            if source is None:
                raise ReleaseError(f"could not read archive member: {member.name!r}")
            with source:
                _copy_file(source, destination, member.mode)


def _local_file_path(reference: str, *, entrypoint: Path) -> Path | None:
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc or reference.startswith(("data:", "#")):
        return None
    decoded = unquote(parsed.path)
    if decoded.startswith("/api/blog/figures/"):
        filename = decoded.removeprefix("/api/blog/figures/")
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            raise ReleaseError(f"invalid backend figure reference: {reference!r}")
        return None
    if not decoded:
        raise ReleaseError(f"empty local file reference in {entrypoint.as_posix()}")
    if decoded.startswith("/"):
        path = PurePosixPath(decoded.lstrip("/"))
    else:
        path = PurePosixPath(entrypoint.parent.as_posix()) / decoded
    if ".." in path.parts:
        raise ReleaseError(f"unsafe local file reference: {reference!r}")
    return Path(*path.parts)


def validate_stage(stage: Path) -> None:
    index = stage / "index.html"
    if not index.is_file():
        raise ReleaseError("release is missing index.html")
    entrypoints = sorted(stage.rglob("*.html"))
    for entrypoint_path in entrypoints:
        relative_entrypoint = entrypoint_path.relative_to(stage)
        parser = _AssetParser()
        try:
            document = entrypoint_path.read_text(encoding="utf-8")
            if not document.strip():
                raise ReleaseError(f"HTML entrypoint is empty: {relative_entrypoint}")
            parser.feed(document)
        except (OSError, UnicodeError) as exc:
            raise ReleaseError(f"HTML entrypoint is unreadable: {relative_entrypoint}: {exc}") from exc
        local_scripts = [
            path
            for reference in parser.script_references
            if (path := _local_file_path(reference, entrypoint=relative_entrypoint)) is not None
        ]
        if not any(path.suffix == ".js" for path in local_scripts):
            raise ReleaseError(f"HTML entrypoint has no local JavaScript entry: {relative_entrypoint}")
        for _tag, reference in parser.references:
            relative = _local_file_path(reference, entrypoint=relative_entrypoint)
            if relative is not None and not (stage / relative).is_file():
                raise ReleaseError(
                    f"missing referenced file in {relative_entrypoint}: {reference}"
                )


def _same_file(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as left_handle, right.open("rb") as right_handle:
        while True:
            left_chunk = left_handle.read(1024 * 1024)
            right_chunk = right_handle.read(1024 * 1024)
            if left_chunk != right_chunk:
                return False
            if not left_chunk:
                return True


def _retain_existing_assets(active: Path, stage: Path) -> None:
    old_assets = active / "assets"
    new_assets = stage / "assets"
    if not old_assets.is_dir():
        return
    for source in old_assets.rglob("*"):
        if not source.is_file() or source.is_symlink():
            continue
        relative = source.relative_to(old_assets)
        destination = new_assets / relative
        if destination.exists():
            if not destination.is_file() or destination.is_symlink() or not _same_file(source, destination):
                raise ReleaseError(f"asset filename collision with different bytes: assets/{relative}")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)


def _tree_identity(root: Path, *, exclude_assets: bool = False) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative_path = path.relative_to(root)
        if exclude_assets and relative_path.parts[0] == "assets":
            continue
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ReleaseError(f"frontend tree contains unsupported entry: {path}")
        relative = relative_path.as_posix().encode()
        digest.update(b"d\0" if path.is_dir() else b"f\0")
        digest.update(relative)
        digest.update(b"\0")
        if path.is_file():
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _activation(path: Path) -> dict[str, object] | None:
    marker = path / ACTIVATION_FILE
    if not marker.is_file():
        return None
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseError(f"invalid activation marker in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseError(f"invalid activation marker in {path}")
    return value


def _is_expected_activation(path: Path, record: dict[str, object]) -> bool:
    marker = _activation(path)
    return bool(
        marker
        and marker.get("release_id") == record.get("release_id")
        and marker.get("source_sha") == record.get("source_sha")
    )


def _matches_identity(path: Path, identity: object) -> bool:
    return isinstance(identity, str) and path.is_dir() and _tree_identity(path) == identity


def _load_journal(journal_path: Path) -> dict[str, object]:
    try:
        record = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseError(f"invalid rollback journal: {exc}") from exc
    if not isinstance(record, dict):
        raise ReleaseError("invalid rollback journal: expected a JSON object")
    return record


def _is_resumable_retention_target(
    failed_release: Path, rollback_target: Path, record: dict[str, object]
) -> bool:
    expected_non_assets = record.get("previous_non_asset_identity")
    if not _matches_identity_without_assets(rollback_target, expected_non_assets):
        return False
    target_assets = rollback_target / "assets"
    failed_assets = failed_release / "assets"
    if not target_assets.exists():
        return True
    if not target_assets.is_dir() or target_assets.is_symlink() or not failed_assets.is_dir():
        return False
    for target in target_assets.rglob("*"):
        if target.is_symlink() or not (target.is_dir() or target.is_file()):
            return False
        if not target.is_file():
            continue
        source = failed_assets / target.relative_to(target_assets)
        if not source.is_file() or source.is_symlink() or not _same_file(source, target):
            return False
    return True


def _matches_identity_without_assets(path: Path, identity: object) -> bool:
    return (
        isinstance(identity, str)
        and path.is_dir()
        and _tree_identity(path, exclude_assets=True) == identity
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _rename_exchange(left: Path, right: Path) -> None:
    """Atomically exchange two paths, failing closed outside supported Linux."""
    if not hasattr(ctypes, "CDLL") or os.name != "posix":
        raise ReleaseError("atomic directory exchange is unavailable on this platform")
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise ReleaseError("renameat2(RENAME_EXCHANGE) is unavailable")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        _AT_FDCWD,
        os.fsencode(left),
        _AT_FDCWD,
        os.fsencode(right),
        _RENAME_EXCHANGE,
    )
    if result != 0:
        error = ctypes.get_errno()
        detail = os.strerror(error)
        if error in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EPERM}:
            raise ReleaseError(f"renameat2(RENAME_EXCHANGE) unsupported: {detail}")
        raise ReleaseError(f"atomic directory exchange failed: {detail}")


def _lock(active: Path):
    lock_path = active.parent / ".frontend-release.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _paths(active: Path, release_id: str) -> tuple[Path, Path, Path]:
    if not _RELEASE_ID.fullmatch(release_id):
        raise ReleaseError("release id must contain only letters, digits, dot, underscore, or hyphen")
    root = active.parent
    stage = root / f".{active.name}.stage.{release_id}"
    previous = root / f".{active.name}.previous.{release_id}"
    journal = root / ".frontend-releases" / f"{release_id}.json"
    return stage, previous, journal


def _absolute_without_following(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _probe_exchange(parent: Path, release_id: str) -> None:
    left = parent / f".frontend-exchange-probe.{release_id}.a"
    right = parent / f".frontend-exchange-probe.{release_id}.b"
    if left.exists() or right.exists():
        raise ReleaseError("atomic exchange probe paths already exist")
    left.mkdir()
    right.mkdir()
    try:
        _rename_exchange(left, right)
    finally:
        if left.exists():
            left.rmdir()
        if right.exists():
            right.rmdir()


def _rollback_locked(active: Path, journal_path: Path, record: dict[str, object]) -> None:
    if _absolute_without_following(Path(str(record.get("active_path")))) != active:
        raise ReleaseError("rollback journal active path does not match")
    release_id = record.get("release_id")
    if not isinstance(release_id, str):
        raise ReleaseError("rollback journal release id is invalid")
    stage, expected_previous, expected_journal = _paths(active, release_id)
    if journal_path != expected_journal.resolve():
        raise ReleaseError("rollback journal path does not match release id")
    previous_value = record.get("previous_path")
    if not previous_value:
        raise ReleaseError("first-install release has no previous frontend to restore")
    previous = _absolute_without_following(Path(str(previous_value)))
    if previous != expected_previous:
        raise ReleaseError("rollback journal previous path does not match release id")

    activated_identity = record.get("activated_identity")
    previous_identity = record.get("previous_identity")
    previous_non_asset_identity = record.get("previous_non_asset_identity")
    if (
        not isinstance(activated_identity, str)
        or not isinstance(previous_identity, str)
        or not isinstance(previous_non_asset_identity, str)
    ):
        raise ReleaseError("rollback journal is missing release tree identities")
    status = record.get("status")
    if status == "rolled_back":
        restored_identity = record.get("restored_identity")
        if (
            not _matches_identity(active, restored_identity)
            or not _is_expected_activation(previous, record)
            or not _matches_identity(previous, activated_identity)
        ):
            raise ReleaseError("completed rollback state no longer matches the journal")
        return
    if status not in {
        "prepared",
        "promotion_intent",
        "activated",
        "verified",
        "rollback_intent",
    }:
        raise ReleaseError(f"release is not rollback eligible from status {status!r}")

    active_is_new = _is_expected_activation(active, record) and _matches_identity(
        active, activated_identity
    )
    stage_is_new = _is_expected_activation(stage, record) and _matches_identity(
        stage, activated_identity
    )
    previous_is_new = _is_expected_activation(previous, record) and _matches_identity(
        previous, activated_identity
    )
    active_is_old = _matches_identity(active, previous_identity)
    stage_is_old = _matches_identity(stage, previous_identity)
    previous_is_old = _matches_identity(previous, previous_identity)

    # Crash before exchange: the old tree is still active and the complete new
    # tree remains staged. Preserve the new hashes in the old tree, then retain
    # the failed release under the deterministic previous path.
    resumable_pre_exchange = stage_is_new and _is_resumable_retention_target(
        stage, active, record
    )
    if (active_is_old or resumable_pre_exchange) and stage_is_new and not previous.exists():
        record["status"] = "rollback_intent"
        _write_json(journal_path, record)
        _retain_existing_assets(stage, active)
        record["restored_identity"] = _tree_identity(active)
        _write_json(journal_path, record)
        os.replace(stage, previous)
    else:
        # Crash after exchange but before stage was renamed to previous.
        if active_is_new and stage_is_old and not previous.exists():
            record["status"] = "rollback_intent"
            _write_json(journal_path, record)
            os.replace(stage, previous)
            previous_is_old = True

        resumable_target = previous.is_dir() and _is_resumable_retention_target(
            active, previous, record
        )
        if active_is_new and (previous_is_old or resumable_target):
            record["status"] = "rollback_intent"
            _write_json(journal_path, record)
            _retain_existing_assets(active, previous)
            restored_identity = _tree_identity(previous)
            record["restored_identity"] = restored_identity
            _write_json(journal_path, record)
            _rename_exchange(active, previous)
        elif previous_is_new:
            restored_identity = record.get("restored_identity")
            if not _matches_identity(active, restored_identity):
                raise ReleaseError("interrupted rollback state does not match the journal")
        else:
            raise ReleaseError(
                "frontend trees do not match any recoverable journal state; refusing stale rollback"
            )

    restored_identity = record.get("restored_identity")
    if (
        not _matches_identity(active, restored_identity)
        or not _is_expected_activation(previous, record)
        or not _matches_identity(previous, activated_identity)
    ):
        raise ReleaseError("rollback recovery did not produce the recorded frontend identities")
    record["status"] = "rolled_back"
    _write_json(journal_path, record)


def _reject_unfinished_releases(active: Path) -> None:
    journal_root = active.parent / ".frontend-releases"
    if not journal_root.is_dir():
        return
    for journal_path in sorted(journal_root.glob("*.json")):
        record = _load_journal(journal_path)
        if record.get("status") not in {
            "prepared",
            "promotion_intent",
            "activated",
            "rollback_intent",
        }:
            continue
        if _absolute_without_following(Path(str(record.get("active_path")))) != active:
            continue
        raise ReleaseError(
            f"unfinished frontend release journal blocks preflight: {journal_path} "
            f"(status={record.get('status')!r})"
        )


def preflight_archive(archive_path: Path, active: Path, release_id: str) -> None:
    active = _absolute_without_following(active)
    stage, previous, journal = _paths(active, release_id)
    with _lock(active):
        _reject_unfinished_releases(active)
        if stage.exists() or previous.exists() or journal.exists():
            raise ReleaseError(f"release id already has deployment state: {release_id}")
        if active.exists() and (not active.is_dir() or active.is_symlink()):
            raise ReleaseError("active frontend must be a real directory")
        try:
            _extract_archive(archive_path, stage)
            validate_stage(stage)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        if active.exists():
            _probe_exchange(active.parent, release_id)


def promote_release(
    archive_path: Path, active: Path, release_id: str, *, source_sha: str = ""
) -> Path:
    archive_path = archive_path.resolve()
    active = _absolute_without_following(active)
    stage, previous, journal = _paths(active, release_id)
    with _lock(active):
        promoted_previous: Path | None = None
        if stage.exists() or previous.exists() or journal.exists():
            raise ReleaseError(f"release id already has deployment state: {release_id}")
        try:
            _extract_archive(archive_path, stage)
            validate_stage(stage)
            if active.exists():
                if not active.is_dir() or active.is_symlink():
                    raise ReleaseError("active frontend must be a real directory")
                _retain_existing_assets(active, stage)
                validate_stage(stage)

            activation = {"release_id": release_id, "source_sha": source_sha}
            _write_json(stage / ACTIVATION_FILE, activation)
            activated_identity = _tree_identity(stage)
            previous_identity = _tree_identity(active) if active.exists() else None
            previous_non_asset_identity = (
                _tree_identity(active, exclude_assets=True) if active.exists() else None
            )
            record: dict[str, object] = {
                "release_id": release_id,
                "source_sha": source_sha,
                "active_path": str(active),
                "previous_path": str(previous) if active.exists() else None,
                "activated_identity": activated_identity,
                "previous_identity": previous_identity,
                "previous_non_asset_identity": previous_non_asset_identity,
                "status": "prepared",
            }
            _write_json(journal, record)

            if active.exists():
                record["status"] = "promotion_intent"
                _write_json(journal, record)
                _rename_exchange(active, stage)
                try:
                    os.replace(stage, previous)
                except BaseException:
                    _rename_exchange(active, stage)
                    raise
                promoted_previous = previous
            else:
                os.replace(stage, active)

            record["status"] = "activated"
            _write_json(journal, record)
            return journal
        except BaseException as exc:
            if promoted_previous is not None:
                try:
                    _rename_exchange(active, promoted_previous)
                except BaseException as rollback_exc:
                    raise ReleaseError(
                        f"promotion failed and automatic frontend restoration failed: {rollback_exc}"
                    ) from exc
            if stage.exists():
                shutil.rmtree(stage)
            if journal.exists():
                journal.unlink()
            raise


def rollback_release(active: Path, journal_path: Path) -> None:
    active = _absolute_without_following(active)
    journal_path = journal_path.resolve()
    with _lock(active):
        _rollback_locked(active, journal_path, _load_journal(journal_path))


def finalize_release(active: Path, journal_path: Path) -> None:
    active = _absolute_without_following(active)
    journal_path = journal_path.resolve()
    with _lock(active):
        record = _load_journal(journal_path)
        release_id = record.get("release_id")
        if not isinstance(release_id, str):
            raise ReleaseError("release journal release id is invalid")
        _, _, expected_journal = _paths(active, release_id)
        if journal_path != expected_journal.resolve():
            raise ReleaseError("release journal path does not match release id")
        if _absolute_without_following(Path(str(record.get("active_path")))) != active:
            raise ReleaseError("release journal active path does not match")
        if record.get("status") == "verified":
            if not _is_expected_activation(active, record) or not _matches_identity(
                active, record.get("activated_identity")
            ):
                raise ReleaseError("verified release state no longer matches the journal")
            return
        if record.get("status") != "activated":
            raise ReleaseError(f"release cannot be finalized from status {record.get('status')!r}")
        if not _is_expected_activation(active, record) or not _matches_identity(
            active, record.get("activated_identity")
        ):
            raise ReleaseError("active frontend does not match the release being finalized")
        record["status"] = "verified"
        _write_json(journal_path, record)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "promote"):
        child = subparsers.add_parser(command)
        child.add_argument("--archive", type=Path, required=True)
        child.add_argument("--active", type=Path, required=True)
        child.add_argument("--release-id", required=True)
        if command == "promote":
            child.add_argument("--source-sha", default="")
    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--active", type=Path, required=True)
    rollback.add_argument("--journal", type=Path, required=True)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--active", type=Path, required=True)
    finalize.add_argument("--journal", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "preflight":
            preflight_archive(args.archive, args.active, args.release_id)
        elif args.command == "promote":
            journal = promote_release(
                args.archive, args.active, args.release_id, source_sha=args.source_sha
            )
            print(journal)
        elif args.command == "rollback":
            rollback_release(args.active, args.journal)
        else:
            finalize_release(args.active, args.journal)
    except ReleaseError as exc:
        raise SystemExit(f"frontend release failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
