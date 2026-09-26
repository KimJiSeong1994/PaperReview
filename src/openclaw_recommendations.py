"""Local-only OpenClaw receiver. Never publishes recommendation delivery files."""

from __future__ import annotations

import json
import math
import os
import stat
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from src.recommendation_candidates import (
    MAX_BYTES,
    CandidateSnapshot,
    CandidateValidationError,
    TrustedReceiverPolicy,
    make_candidate_snapshot,
    write_candidate_snapshot,
)
from src.utils.secure_directory import open_directory

if TYPE_CHECKING:
    from src.storage.user_db import UserDB


class OpenClawArtifactError(ValueError):
    """Only stable, payload-free error codes cross this boundary."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ImportedOpenClawArtifact:
    destination_path: Path
    snapshot: CandidateSnapshot
    variant_count: int
    observed_bytes: int

    def as_dict(self) -> dict:
        return {
            "code": "candidate_staged",
            "status": self.snapshot.status,
            "variant_count": self.variant_count,
            "item_count": len(self.snapshot.records),
            "rejected_counts": self.snapshot.rejected_counts,
            "observed_bytes": self.observed_bytes,
        }


def _deadline(deadline: float | None, clock: Callable[[], float]) -> None:
    if deadline is not None:
        if not math.isfinite(deadline):
            raise OpenClawArtifactError("invalid_budget")
        if clock() >= deadline:
            raise OpenClawArtifactError("deadline_exceeded")


def load_and_validate_openclaw_raw(
    source_path: Path,
    *,
    policy: TrustedReceiverPolicy,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[list[dict], int, int]:
    """Bound reads before JSON parsing; returns flattened candidates, not raw payload."""
    if policy.source != "openclaw":
        raise OpenClawArtifactError("source_disabled")
    path = Path(source_path).absolute()
    if ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise OpenClawArtifactError("unsafe_path")
    try:
        _deadline(deadline, clock)
        parent = open_directory(path.parent)
        try:
            fd = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=parent,
            )
        finally:
            os.close(parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise OpenClawArtifactError("invalid_source_file")
            if info.st_size > MAX_BYTES:
                raise OpenClawArtifactError("size_limit")
        except BaseException:
            os.close(fd)
            raise
        with os.fdopen(fd, "rb") as handle:
            payload = bytearray()
            while True:
                _deadline(deadline, clock)
                chunk = handle.read(min(65536, MAX_BYTES + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > MAX_BYTES:
                    raise OpenClawArtifactError("size_limit")
            _deadline(deadline, clock)
        raw = json.loads(payload)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, OpenClawArtifactError):
            raise
        raise OpenClawArtifactError("invalid_source") from None
    if not isinstance(raw, dict):
        raise OpenClawArtifactError("invalid_root")
    variants = raw.get("variants")
    if not isinstance(variants, dict) or not 1 <= len(variants) <= 16:
        raise OpenClawArtifactError("variant_limit")
    records = []
    cap = 10000 if policy.scope == "public" else 500
    for name, items in variants.items():
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 128
            or not isinstance(items, list)
        ):
            raise OpenClawArtifactError("invalid_variant")
        if len(records) + len(items) > cap:
            raise OpenClawArtifactError("record_limit")
        if any(not isinstance(item, dict) for item in items):
            raise OpenClawArtifactError("invalid_record")
        records.extend(items)
    _deadline(deadline, clock)
    return records, len(variants), len(payload)


def import_openclaw_artifact(
    source_path: Path,
    *,
    candidate_root: Path,
    final_root: Path,
    policy: TrustedReceiverPolicy,
    source_run_id: str,
    collected_at: datetime | str,
    now: datetime,
    username: str | None = None,
    user_db: UserDB | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ImportedOpenClawArtifact:
    """Stage sanitized candidates under a current private-account commit guard.

    Policy/provenance and collection time come from the trusted receiver, not
    legacy JSON's username, scope, run_at, variant labels or model explanation.
    No UserDB calls are nested inside account_guard.
    """
    if policy.source != "openclaw":
        raise OpenClawArtifactError("source_disabled")
    if policy.scope == "private":
        if user_db is None or not username:
            raise OpenClawArtifactError("principal_required")
        try:
            user_db.validate_principal(username, policy.account_incarnation)
        except Exception:
            raise OpenClawArtifactError("principal_rejected") from None
    try:
        records, variant_count, observed = load_and_validate_openclaw_raw(
            source_path,
            policy=policy,
            deadline=deadline,
            clock=clock,
        )
        snapshot = make_candidate_snapshot(
            records,
            policy=policy,
            source_run_id=source_run_id,
            collected_at=collected_at,
            now=now,
        )
        _deadline(deadline, clock)
        if policy.scope == "private":
            try:
                with user_db.account_guard(username, policy.account_incarnation):
                    _deadline(deadline, clock)
                    destination = write_candidate_snapshot(
                        snapshot, root=candidate_root, final_root=final_root
                    )
            except (CandidateValidationError, OpenClawArtifactError, OSError):
                raise
            except Exception:
                raise OpenClawArtifactError("principal_rejected") from None
        else:
            destination = write_candidate_snapshot(
                snapshot, root=candidate_root, final_root=final_root
            )
    except CandidateValidationError as exc:
        raise OpenClawArtifactError(exc.code) from None
    except OSError:
        raise OpenClawArtifactError("staging_failed") from None
    return ImportedOpenClawArtifact(destination, snapshot, variant_count, observed)
