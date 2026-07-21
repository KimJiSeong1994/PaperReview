"""CLI for the bounded SkillOpt v0.2.0 RED diagnostic harness."""

from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
from pathlib import Path

from src.search_eval.skillopt_contract import ValidationError
from tools.skillopt_compat import (
    DEFAULT_PROFILE_CATALOG,
    build_red_diagnostic_report,
    canonical_report_bytes,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect exact SkillOpt v0.2.0 inputs without executing train or eval."
    )
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--materialized-root", required=True, type=Path)
    parser.add_argument("--profile-catalog", type=Path, default=DEFAULT_PROFILE_CATALOG)
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = build_red_diagnostic_report(
            source_root=args.source_root,
            materialized_root=args.materialized_root,
            profile_catalog_path=args.profile_catalog,
        )
        payload = canonical_report_bytes(report)
        if args.report is not None:
            _write_report(
                args.report,
                payload,
                forbidden_inputs=(
                    args.source_root,
                    args.materialized_root,
                    args.profile_catalog,
                ),
            )
        sys.stdout.buffer.write(payload)
    except (OSError, ValidationError) as exc:
        print(f"skillopt compatibility diagnostic rejected: {exc}", file=sys.stderr)
        return 2
    return 0


def _write_report(
    path: Path,
    payload: bytes,
    *,
    forbidden_inputs: tuple[Path, ...],
) -> None:
    report_path = Path(os.path.abspath(path))
    _reject_input_overlap(report_path, forbidden_inputs)
    parent_fd = _open_or_create_real_parent(report_path.parent)
    temporary_name = f".{report_path.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    temporary_created = False
    try:
        before = _report_leaf_stat(parent_fd, report_path.name)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temporary_name, flags, 0o600, dir_fd=parent_fd)
        temporary_created = True
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise OSError("report write made no progress")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        after = _report_leaf_stat(parent_fd, report_path.name)
        if not _same_optional_inode(before, after):
            raise ValidationError("report target changed during atomic write")
        os.replace(
            temporary_name,
            report_path.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        temporary_created = False
        os.fsync(parent_fd)
    finally:
        if temporary_created:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except OSError:
                pass
        os.close(parent_fd)


def _open_or_create_real_parent(parent: Path) -> int:
    absolute = Path(os.path.abspath(parent))
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    current_fd = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            try:
                child_stat = os.stat(
                    component, dir_fd=current_fd, follow_symlinks=False
                )
            except FileNotFoundError:
                os.mkdir(component, 0o700, dir_fd=current_fd)
                child_stat = os.stat(
                    component, dir_fd=current_fd, follow_symlinks=False
                )
            if stat.S_ISLNK(child_stat.st_mode) or not stat.S_ISDIR(child_stat.st_mode):
                raise ValidationError(
                    "report parent must contain only real directories"
                )
            next_fd = os.open(component, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _report_leaf_stat(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        leaf_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(leaf_stat.st_mode):
        raise ValidationError("report path must not be a symlink")
    if not stat.S_ISREG(leaf_stat.st_mode):
        raise ValidationError("report path must be a regular file")
    if leaf_stat.st_nlink != 1:
        raise ValidationError("report path must not be a hardlink target")
    return leaf_stat


def _same_optional_inode(
    before: os.stat_result | None, after: os.stat_result | None
) -> bool:
    if before is None or after is None:
        return before is after
    return (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)


def _reject_input_overlap(path: Path, forbidden_inputs: tuple[Path, ...]) -> None:
    output = path.resolve(strict=False)
    for input_path in forbidden_inputs:
        protected = Path(input_path).resolve(strict=False)
        if output == protected or output.is_relative_to(protected):
            raise ValidationError("report output must not overlap a diagnostic input")


if __name__ == "__main__":
    raise SystemExit(main())
