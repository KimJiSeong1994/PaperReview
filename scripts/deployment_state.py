#!/usr/bin/env python3
"""Persist and guard durable, release-owned deployment recovery state."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


_RELEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HELPER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class DeploymentStateError(RuntimeError):
    """Deployment recovery state is invalid or owned by another release."""


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json(path: Path, payload: dict[str, object], *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(payload, output, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        _fsync_directory(path.parent)
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeploymentStateError(f"invalid deployment state {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DeploymentStateError(f"invalid deployment state {path}: expected object")
    return payload


def _write_text_exclusive(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(value)
        output.flush()
        os.fsync(output.fileno())
    _fsync_directory(path.parent)


def _copy_file_durable(source: Path, destination: Path) -> None:
    with source.open("rb") as input_handle, destination.open("xb") as output_handle:
        shutil.copyfileobj(input_handle, output_handle)
        os.fchmod(output_handle.fileno(), 0o700)
        output_handle.flush()
        os.fsync(output_handle.fileno())


def _validate_release_id(release_id: str) -> None:
    if not _RELEASE_ID.fullmatch(release_id):
        raise DeploymentStateError("invalid release id")


def _paths(state_root: Path, release_id: str) -> tuple[Path, Path, Path]:
    _validate_release_id(release_id)
    root = Path(os.path.abspath(os.fspath(state_root)))
    return root / "in-progress.json", root / "releases" / release_id, root / ".lock"


def _lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def ensure_clear(state_root: Path) -> None:
    marker = Path(os.path.abspath(os.fspath(state_root))) / "in-progress.json"
    if marker.exists():
        record = _load_json(marker)
        raise DeploymentStateError(
            f"deployment recovery is still owned by release {record.get('release_id')!r}"
        )


def _parse_helper(specification: str) -> tuple[str, Path]:
    name, separator, raw_path = specification.partition("=")
    if not separator or not _HELPER_NAME.fullmatch(name):
        raise DeploymentStateError(f"invalid helper specification: {specification!r}")
    source = Path(raw_path)
    if not source.is_file() or source.is_symlink():
        raise DeploymentStateError(f"recovery helper is not a regular file: {source}")
    return name, source


def begin(
    state_root: Path,
    release_id: str,
    target_sha: str,
    previous_sha_file: Path,
    previous_health_file: Path,
    frontend_active: Path,
    helper_specs: list[str],
) -> Path:
    marker, release_dir, lock_path = _paths(state_root, release_id)
    if not _SHA.fullmatch(target_sha):
        raise DeploymentStateError("target SHA must be a full lowercase Git SHA")
    try:
        previous_sha = previous_sha_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise DeploymentStateError(f"could not read previous SHA: {exc}") from exc
    if not _SHA.fullmatch(previous_sha):
        raise DeploymentStateError("previous SHA must be a full lowercase Git SHA")
    previous_health = _load_json(previous_health_file)
    helpers = [_parse_helper(specification) for specification in helper_specs]
    if not helpers:
        raise DeploymentStateError("at least one recovery helper is required")
    if len({name for name, _ in helpers}) != len(helpers):
        raise DeploymentStateError("recovery helper names must be unique")

    with _lock(lock_path):
        if marker.exists():
            owner = _load_json(marker).get("release_id")
            raise DeploymentStateError(f"deployment state is already owned by {owner!r}")
        if release_dir.exists():
            raise DeploymentStateError(f"release recovery directory already exists: {release_dir}")
        release_dir.mkdir(parents=True, mode=0o700)
        helper_names: list[str] = []
        for name, source in helpers:
            destination = release_dir / name
            _copy_file_durable(source, destination)
            helper_names.append(name)
        _write_text_exclusive(release_dir / "previous.sha", previous_sha + "\n")
        _write_json(release_dir / "backend.previous.health.json", previous_health)
        record: dict[str, object] = {
            "release_id": release_id,
            "target_sha": target_sha,
            "previous_sha": previous_sha,
            "previous_health": "backend.previous.health.json",
            "frontend_active": str(Path(os.path.abspath(os.fspath(frontend_active)))),
            "frontend_journal": str(
                Path(os.path.abspath(os.fspath(frontend_active))).parent
                / ".frontend-releases"
                / f"{release_id}.json"
            ),
            "helpers": helper_names,
            "frontend_promotion_intent": False,
        }
        recovery_path = release_dir / "recovery.json"
        _write_json(recovery_path, record)
        _fsync_directory(release_dir)
        _fsync_directory(release_dir.parent)
        _write_json(
            marker,
            {"release_id": release_id, "recovery_record": str(recovery_path)},
            exclusive=True,
        )
    return recovery_path


def _require_owner(state_root: Path, release_id: str) -> tuple[Path, Path, Path]:
    marker, release_dir, lock_path = _paths(state_root, release_id)
    if not marker.is_file():
        raise DeploymentStateError("no deployment is in progress")
    payload = _load_json(marker)
    if payload.get("release_id") != release_id:
        raise DeploymentStateError(
            f"deployment state belongs to {payload.get('release_id')!r}, not {release_id!r}"
        )
    expected_record = release_dir / "recovery.json"
    if payload.get("recovery_record") != str(expected_record) or not expected_record.is_file():
        raise DeploymentStateError("deployment marker does not match its recovery record")
    return marker, release_dir, lock_path


def assert_owner(state_root: Path, release_id: str) -> None:
    _require_owner(state_root, release_id)


def mark_frontend(state_root: Path, release_id: str) -> None:
    marker, release_dir, lock_path = _paths(state_root, release_id)
    with _lock(lock_path):
        _require_owner(state_root, release_id)
        record_path = release_dir / "recovery.json"
        record = _load_json(record_path)
        record["frontend_promotion_intent"] = True
        _write_json(record_path, record)
        intent = release_dir / "frontend-promotion.intent"
        if not intent.exists():
            descriptor = os.open(intent, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.fsync(descriptor)
            os.close(descriptor)
            _fsync_directory(intent.parent)
        if not marker.is_file():
            raise DeploymentStateError("deployment marker disappeared while marking frontend")


def clear(state_root: Path, release_id: str) -> None:
    marker, _, lock_path = _paths(state_root, release_id)
    with _lock(lock_path):
        _require_owner(state_root, release_id)
        marker.unlink()
        _fsync_directory(marker.parent)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    ensure = subparsers.add_parser("ensure-clear")
    ensure.add_argument("--state-root", type=Path, required=True)
    begin_parser = subparsers.add_parser("begin")
    begin_parser.add_argument("--state-root", type=Path, required=True)
    begin_parser.add_argument("--release-id", required=True)
    begin_parser.add_argument("--target-sha", required=True)
    begin_parser.add_argument("--previous-sha-file", type=Path, required=True)
    begin_parser.add_argument("--previous-health-file", type=Path, required=True)
    begin_parser.add_argument("--frontend-active", type=Path, required=True)
    begin_parser.add_argument("--helper", action="append", default=[])
    for command in ("owns", "mark-frontend", "clear"):
        child = subparsers.add_parser(command)
        child.add_argument("--state-root", type=Path, required=True)
        child.add_argument("--release-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "ensure-clear":
            ensure_clear(args.state_root)
        elif args.command == "begin":
            path = begin(
                args.state_root,
                args.release_id,
                args.target_sha,
                args.previous_sha_file,
                args.previous_health_file,
                args.frontend_active,
                args.helper,
            )
            print(path)
        elif args.command == "owns":
            assert_owner(args.state_root, args.release_id)
        elif args.command == "mark-frontend":
            mark_frontend(args.state_root, args.release_id)
        else:
            clear(args.state_root, args.release_id)
    except DeploymentStateError as exc:
        raise SystemExit(f"deployment state failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
