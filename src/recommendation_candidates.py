"""Bounded bibliographic staging. Receiver policy, never JSON, grants authority."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping
from urllib.parse import urlsplit

from src.utils.paper_utils import generate_result_key, normalize_doi, normalize_title
from src.utils.secure_directory import open_directory

SCHEMA = "recommendation_candidates_v1"
MAX_BYTES = 20 * 1024 * 1024
SOURCES = {"local_public", "owner_local", "openclaw"}
Source = Literal["local_public", "owner_local", "openclaw"]
Scope = Literal["public", "private"]
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


class CandidateValidationError(ValueError):
    """Payload-free rejection suitable for structured counting."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _reject(code: str) -> None:
    raise CandidateValidationError(code)


@dataclass(frozen=True)
class TrustedReceiverPolicy:
    source: Source
    scope: Scope
    provenance_id: str
    account_incarnation: str | None = None
    public_source_qualified: bool = False
    allow_stale_public_corpus: bool = False

    def __post_init__(self) -> None:
        if self.source not in SOURCES or self.scope not in {"public", "private"}:
            _reject("unqualified_source")
        _safe(self.provenance_id)
        if self.scope == "public":
            if (
                not self.public_source_qualified
                or self.account_incarnation is not None
                or self.source == "owner_local"
            ):
                _reject("unqualified_public")
        elif not self.account_incarnation:
            _reject("missing_owner")
        else:
            _safe(self.account_incarnation)
        if self.allow_stale_public_corpus and (
            self.source != "local_public" or self.scope != "public"
        ):
            _reject("invalid_stale_policy")


@dataclass(frozen=True)
class CandidateRecord:
    canonical_key: str
    metadata: dict[str, Any]
    sources: tuple[str, ...] = ()

    def to_paper(self) -> dict[str, Any]:
        return {
            **self.metadata,
            "canonical_key": self.canonical_key,
            "candidate_sources": list(self.sources),
        }


@dataclass(frozen=True)
class CandidateSnapshot:
    source: Source
    source_run_id: str
    collected_at: str
    scope: Scope
    provenance_id: str
    account_incarnation: str | None
    records: tuple[CandidateRecord, ...]
    checksum: str
    degraded: bool = False
    rejected_counts: dict[str, int] = field(default_factory=dict)
    acquisition_status: str = "empty"
    acquisition_reasons: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        return "empty" if not self.records else "degraded" if self.degraded else "ready"


@dataclass(frozen=True)
class CandidatePool:
    records: tuple[CandidateRecord, ...]
    checksum: str
    rejected_counts: dict[str, int]

    @property
    def status(self) -> str:
        return "ready" if self.records else "empty"


def _safe(value: Any) -> str:
    if not isinstance(value, str) or not _SAFE.fullmatch(value):
        _reject("invalid_identifier")
    return value


def _json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value)).hexdigest()


def _utc(value: Any) -> datetime:
    try:
        result = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
        if result.tzinfo is None or result.utcoffset() != timedelta(0):
            _reject("invalid_time")
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError):
        _reject("invalid_time")


def _text(value: Any, bound: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > bound
        or any(ord(c) < 32 and c not in "\n\t\r" for c in value)
    ):
        _reject("invalid_field")
    return value.strip()


def normalize_candidate(raw: Mapping[str, Any]) -> CandidateRecord:
    """Strict allowlist; ignored scores (even NaN) never enter identity/checksum."""
    if not isinstance(raw, Mapping):
        _reject("invalid_record")
    data: dict[str, Any] = {}
    for key, bound in (("title", 512), ("abstract", 8000), ("venue", 512)):
        if raw.get(key) is not None:
            data[key] = _text(raw[key], bound)
    if not normalize_title(data.get("title", "")):
        _reject("missing_title")
    for key, cap, bound in (("authors", 20, 128), ("categories", 16, 128)):
        if key in raw:
            if not isinstance(raw[key], list) or len(raw[key]) > cap:
                _reject("invalid_field")
            values = [
                _text(
                    v.get("name") if isinstance(v, dict) and key == "authors" else v,
                    bound,
                )
                for v in raw[key]
            ]
            data[key] = sorted(set(v for v in values if v))
    if raw.get("year") is not None:
        year = raw["year"]
        if (
            isinstance(year, bool)
            or not isinstance(year, (str, int))
            or not re.fullmatch(r"[1-9]\d{3}", str(year))
        ):
            _reject("invalid_date")
        data["year"] = int(year)
    if raw.get("publication_date") is not None:
        try:
            value = raw["publication_date"]
            if not isinstance(value, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", value
            ):
                _reject("invalid_date")
            parsed = date.fromisoformat(value)
            if data.get("year", parsed.year) != parsed.year:
                _reject("invalid_date")
            data["publication_date"] = value
            data["year"] = parsed.year
        except ValueError:
            _reject("invalid_date")
    if raw.get("doi"):
        doi = normalize_doi(_text(raw["doi"], 256))
        if not re.fullmatch(r"10\.\d{4,9}/[^\s]+", doi):
            _reject("invalid_id")
        data["doi"] = doi
    if raw.get("arxiv_id"):
        arxiv = _text(raw["arxiv_id"], 256)
        key = generate_result_key({"arxiv_id": arxiv})
        if not key.startswith("arxiv:"):
            _reject("invalid_id")
        data["arxiv_id"] = key.removeprefix("arxiv:")
    for key, pattern in (
        ("openalex_id", r"(?:https://openalex.org/)?W\d+"),
        ("semantic_scholar_id", r"[a-fA-F0-9]{40}"),
        ("pmid", r"\d{1,12}"),
    ):
        if raw.get(key):
            value = _text(raw[key], 256)
            if not re.fullmatch(pattern, value):
                _reject("invalid_id")
            data[key] = value.rsplit("/", 1)[-1]
    for key in ("url", "pdf_url"):
        if raw.get(key):
            value = _text(raw[key], 2048)
            try:
                url = urlsplit(value)
                if (
                    url.scheme not in {"http", "https"}
                    or not url.hostname
                    or url.username
                    or url.password
                    or url.query
                    or url.fragment
                ):
                    _reject("invalid_url")
                _ = url.port
            except ValueError:
                _reject("invalid_url")
            data[key] = value
    return CandidateRecord(generate_result_key(data), data)


def _body(snapshot: CandidateSnapshot) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "source": snapshot.source,
        "source_run_id": snapshot.source_run_id,
        "collected_at": snapshot.collected_at,
        "scope": snapshot.scope,
        "provenance": {"registration_id": snapshot.provenance_id},
        "account_incarnation": snapshot.account_incarnation,
        "records": [r.metadata for r in snapshot.records],
        "acquisition_status": snapshot.acquisition_status,
        "acquisition_reasons": list(snapshot.acquisition_reasons),
    }


def make_candidate_snapshot(
    records: Iterable[Mapping[str, Any]],
    *,
    policy: TrustedReceiverPolicy,
    source_run_id: str,
    collected_at: datetime | str,
    now: datetime,
    acquisition_status: str | None = None,
    acquisition_reasons: Iterable[str] = (),
) -> CandidateSnapshot:
    _safe(source_run_id)
    collected = _utc(collected_at)
    age = _utc(now) - collected
    if age < timedelta(0):
        _reject("future_snapshot")
    degraded = age > timedelta(hours=36)
    if degraded and not policy.allow_stale_public_corpus:
        _reject("stale_snapshot")
    cap = 10000 if policy.scope == "public" else 500
    normalized = []
    rejected: Counter[str] = Counter()
    for index, raw in enumerate(records):
        if index >= cap:
            _reject("record_limit")
        try:
            record = normalize_candidate(raw)
            cutoff = _utc(now).date()
            if record.metadata.get("year", cutoff.year) > cutoff.year or (
                record.metadata.get("publication_date", cutoff.isoformat())
                > cutoff.isoformat()
            ):
                _reject("future_publication")
            normalized.append(record)
        except CandidateValidationError as exc:
            rejected[exc.code] += 1
    normalized.sort(key=lambda r: (r.canonical_key, _json(r.metadata)))
    health = acquisition_status or ("ready" if normalized else "empty")
    if (
        not isinstance(acquisition_reasons, (tuple, list))
        or len(acquisition_reasons) > 8
        or any(not isinstance(reason, str) for reason in acquisition_reasons)
    ):
        _reject("invalid_acquisition")
    reasons = tuple(sorted(set(acquisition_reasons)))
    if (
        health not in {"ready", "empty", "disabled", "degraded", "error"}
        or len(reasons) > 8
        or any(
            reason
            not in {
                "source_disabled",
                "provider_error",
                "provider_timeout",
                "partial_failure",
                "records_rejected",
                "deadline_exceeded",
            }
            for reason in reasons
        )
    ):
        _reject("invalid_acquisition")
    if (health in {"empty", "disabled", "error"} and normalized) or (
        health == "ready" and not normalized
    ):
        _reject("invalid_acquisition")
    snapshot = CandidateSnapshot(
        policy.source,
        source_run_id,
        collected.isoformat(),
        policy.scope,
        policy.provenance_id,
        policy.account_incarnation,
        tuple(normalized),
        "",
        degraded,
        dict(sorted(rejected.items())),
        health,
        reasons,
    )
    body = _body(snapshot)
    if len(_json(body)) > MAX_BYTES:
        _reject("size_limit")
    return CandidateSnapshot(**{**snapshot.__dict__, "checksum": _digest(body)})


def _root(root: Path | str, final_root: Path | str) -> Path:
    if ".." in Path(root).parts or ".." in Path(final_root).parts:
        _reject("unsafe_path")
    base, final = Path(root).absolute(), Path(final_root).resolve()
    for part in (base, *base.parents):
        if part.is_symlink():
            _reject("unsafe_path")
    if base == final or base.is_relative_to(final) or final.is_relative_to(base):
        _reject("final_root_overlap")
    return base


def _contained(path: Path | str, root: Path) -> Path:
    path = Path(path)
    if ".." in path.parts:
        _reject("unsafe_path")
    path = path if path.is_absolute() else root / path
    if not path.is_relative_to(root):
        _reject("unsafe_path")
    for part in (path, *path.parents):
        if part.is_symlink():
            _reject("unsafe_path")
        if part == root:
            break
    if not path.resolve().is_relative_to(root):
        _reject("unsafe_path")
    return path


def write_candidate_snapshot(
    snapshot: CandidateSnapshot, *, root: Path | str, final_root: Path | str
) -> Path:
    base = _root(root, final_root)
    _safe(snapshot.source_run_id)
    if snapshot.source not in SOURCES or snapshot.scope not in {"public", "private"}:
        _reject("unqualified_source")
    body = _body(snapshot)
    if snapshot.checksum != _digest(body):
        _reject("checksum_mismatch")
    relative = (
        Path("public") / snapshot.source
        if snapshot.scope == "public"
        else Path("private") / _safe(snapshot.account_incarnation)
    ) / f"current-{snapshot.source}-{_safe(snapshot.provenance_id)}.json"
    destination = _contained(relative, base)
    parent = open_directory(destination.parent, create=True)
    temporary = None
    try:
        name = ".candidate-" + secrets.token_hex(16) + ".tmp"
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent,
        )
        temporary = name
        with os.fdopen(fd, "wb") as handle:
            size = 0
            for chunk in json.JSONEncoder(
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).iterencode({**body, "checksum": snapshot.checksum}):
                encoded = chunk.encode("utf-8")
                size += len(encoded)
                if size > MAX_BYTES:
                    _reject("size_limit")
                handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination.name, src_dir_fd=parent, dst_dir_fd=parent)
        temporary = None
        os.fsync(parent)
    finally:
        try:
            if temporary is not None:
                os.unlink(temporary, dir_fd=parent)
        finally:
            os.close(parent)
    return destination


def load_candidate_snapshot(
    path: Path | str,
    *,
    root: Path | str,
    policy: TrustedReceiverPolicy,
    now: datetime,
    final_root: Path | str,
) -> CandidateSnapshot:
    target = _contained(path, _root(root, final_root))
    try:
        parent = open_directory(target.parent)
        try:
            fd = os.open(
                target.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=parent,
            )
        finally:
            os.close(parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                _reject("invalid_source_file")
            if info.st_size > MAX_BYTES:
                _reject("size_limit")
        except BaseException:
            os.close(fd)
            raise
        with os.fdopen(fd, "rb") as handle:
            chunks = bytearray()
            while True:
                chunk = handle.read(min(65536, MAX_BYTES + 1 - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
                if len(chunks) > MAX_BYTES:
                    _reject("size_limit")
        raw = json.loads(chunks)
    except FileNotFoundError:
        _reject("snapshot_missing")
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, CandidateValidationError):
            raise
        _reject("invalid_snapshot")
    if (
        not isinstance(raw, dict)
        or raw.get("schema") != SCHEMA
        or not isinstance(raw.get("records"), list)
    ):
        _reject("invalid_envelope")
    if (
        raw.get("source"),
        raw.get("scope"),
        raw.get("account_incarnation"),
        raw.get("provenance"),
    ) != (
        policy.source,
        policy.scope,
        policy.account_incarnation,
        {"registration_id": policy.provenance_id},
    ):
        _reject("policy_mismatch")
    snapshot = make_candidate_snapshot(
        raw["records"],
        policy=policy,
        source_run_id=raw.get("source_run_id"),
        collected_at=raw.get("collected_at"),
        now=now,
        acquisition_status=raw.get("acquisition_status"),
        acquisition_reasons=raw.get("acquisition_reasons", ()),
    )
    if raw.get("checksum") != snapshot.checksum:
        _reject("checksum_mismatch")
    return snapshot


def load_current_candidate_snapshot(
    root: Path | str,
    *,
    final_root: Path | str,
    policy: TrustedReceiverPolicy,
    now: datetime,
) -> CandidateSnapshot | None:
    """Read one registered atomic current slot; never enumerate historical entries."""
    directory = (
        Path("public") / policy.source
        if policy.scope == "public"
        else Path("private") / policy.account_incarnation
    )
    path = directory / f"current-{policy.source}-{policy.provenance_id}.json"
    try:
        return load_candidate_snapshot(
            path, root=root, final_root=final_root, policy=policy, now=now
        )
    except CandidateValidationError as exc:
        if exc.code == "snapshot_missing":
            return None
        raise


def merge_candidate_pool(
    snapshots: Iterable[CandidateSnapshot],
    *,
    account_incarnation: str | None = None,
    public_only: bool = False,
) -> CandidatePool:
    """Filter owners before alias discovery; no private data can enter public output."""
    entries = []
    rejected: Counter[str] = Counter()
    for snapshot in snapshots:
        if snapshot.scope != "public" and (
            public_only
            or not account_incarnation
            or snapshot.account_incarnation != account_incarnation
        ):
            rejected["owner_filtered"] += len(snapshot.records)
            continue
        if (
            snapshot.source not in SOURCES
            or snapshot.scope not in {"public", "private"}
            or snapshot.checksum != _digest(_body(snapshot))
        ):
            rejected["invalid_snapshot"] += 1
            continue
        priority = (
            0
            if snapshot.scope == "public"
            else 1
            if snapshot.source == "owner_local"
            else 2
        )
        for record in snapshot.records:
            entries.append(
                (
                    priority,
                    -_utc(snapshot.collected_at).timestamp(),
                    snapshot.source,
                    record.canonical_key,
                    _json(record.metadata),
                    record,
                )
            )
    entries.sort(key=lambda entry: entry[:-1])
    aliases: dict[str, set[str]] = defaultdict(set)
    for *_, record in entries:
        data = record.metadata
        arxiv_key = generate_result_key({k: v for k, v in data.items() if k != "doi"})
        if data.get("doi") and arxiv_key.startswith("arxiv:"):
            aliases[arxiv_key].add(record.canonical_key)
    merged: dict[str, CandidateRecord] = {}
    for _, _, source, _, _, record in entries:
        key = record.canonical_key
        if key.startswith("arxiv:") and len(aliases[key]) == 1:
            key = next(iter(aliases[key]))
        if key not in merged:
            merged[key] = CandidateRecord(key, dict(record.metadata), (source,))
        else:
            previous = merged[key]
            metadata = dict(previous.metadata)
            for field_name, value in record.metadata.items():
                if (
                    field_name in {"year", "publication_date"}
                    and metadata.get("year")
                    and record.metadata.get("year") != metadata["year"]
                ):
                    continue
                if not metadata.get(field_name):
                    metadata[field_name] = value
            merged[key] = CandidateRecord(
                key, metadata, tuple(sorted(set(previous.sources + (source,))))
            )
    records = tuple(merged[key] for key in sorted(merged))
    return CandidatePool(
        records,
        _digest([r.to_paper() for r in records]),
        dict(sorted(rejected.items())),
    )
