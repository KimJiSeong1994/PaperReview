"""Incarnation-scoped recommendation policy, independent of lossy analytics.

The user store owns account identity. Callers must hold its account guard while
committing actions/exposures or reading policy for an authenticated response.
This store neither creates account incarnations nor authorizes principals.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from src.storage.user_db import UserDB

ACTIONS = frozenset({"hide", "already_seen", "topic_less", "interested", "seen"})
ACTION_DAYS = {"already_seen": 90, "topic_less": 90, "interested": 90, "seen": 30}
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class RecommendationStateError(ValueError):
    """Invalid action or an idempotency key reused for another operation."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clock(value: datetime | None) -> datetime:
    value = value or utc_now()
    if value.tzinfo is None or value.utcoffset() is None:
        raise RecommendationStateError("timezone_required")
    return value.astimezone(timezone.utc)


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise RecommendationStateError("invalid_identifier")
    return value


def _key(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or any(ord(c) < 32 for c in value)
    ):
        raise RecommendationStateError("invalid_canonical_key")
    return value


def _payload_hash(
    run_id: str, canonical_key: str, action: str, undo_action: str | None
) -> str:
    payload = [run_id, canonical_key, action, undo_action]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class RecommendationPolicy:
    """An explicit policy snapshot; a failed read must never become an empty one."""

    incarnation: str
    hidden: frozenset[str] = frozenset()
    already_seen: frozenset[str] = frozenset()
    seen: frozenset[str] = frozenset()
    interested: frozenset[str] = frozenset()
    topic_less: dict[str, str] = field(default_factory=dict)
    recent_exposures: tuple[tuple[str, str], ...] = ()

    @property
    def suppressed(self) -> frozenset[str]:
        return self.hidden | self.already_seen

    def excluded_for_run(self, run_id: str) -> frozenset[str]:
        """Exposure affects later runs, never reopening the displayed run."""
        return self.suppressed | frozenset(
            key for key, exposed_run in self.recent_exposures if exposed_run != run_id
        )

    def project(self, papers: list[dict], *, limit: int = 5) -> list[dict]:
        """Preserve final rank, then refill from the eligible ordered reserve."""
        if not 1 <= limit <= 50:
            raise RecommendationStateError("invalid_limit")
        selected = []
        for paper in papers:
            key = _key(paper.get("canonical_key", ""))
            if key in self.suppressed:
                continue
            selected.append(
                {
                    **paper,
                    "seen": key in self.seen,
                    "display_position": len(selected) + 1,
                }
            )
            if len(selected) == limit:
                break
        return selected


class RecommendationState:
    """Small transactional projection in events.db, not an identity authority."""

    def __init__(self, db_path: str | Path, *, authority: UserDB):
        self.db_path = Path(db_path).resolve()
        self.authority = authority
        with self._connection():
            pass

    @classmethod
    def initialize(cls, db_path: str | Path, *, authority: UserDB):
        """Explicit first provisioning only; never repair/adopt a lost store.

        Users→Events order. Events commits before the authority receipt: a
        failed authority commit can leave an orphan, which requires operator
        recovery, not automatic adoption. No cross-database atomicity claim.
        """
        path = Path(db_path).resolve()
        key = "policy_store"
        with authority.transaction() as tx:
            receipt = authority.policy_store_receipt(path)
            if receipt is not None:
                cls._validate_file(path, receipt)
                conn = cls._open_existing(path)
                try:
                    cls._validate(conn, receipt)
                finally:
                    conn.close()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(path, timeout=5)
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    if conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE name LIKE 'recommendation_%' LIMIT 1"
                    ).fetchone():
                        raise sqlite3.OperationalError(
                            "policy_store_untrusted_existing"
                        )
                    store_id = uuid.uuid4().hex
                    cls._create_schema(conn)
                    conn.execute(
                        "CREATE TABLE recommendation_store_identity (store_id TEXT PRIMARY KEY NOT NULL)"
                    )
                    conn.execute(
                        "INSERT INTO recommendation_store_identity VALUES (?)",
                        (store_id,),
                    )
                    stat = path.stat()
                    receipt = {
                        "store_id": store_id,
                        "schema": cls._schema(conn),
                        "path": str(path),
                        "file_identity": [stat.st_dev, stat.st_ino],
                    }
                    conn.commit()
                    tx.conn.execute(
                        "INSERT INTO account_store_meta VALUES (?, ?)",
                        (key, json.dumps(receipt, sort_keys=True)),
                    )
                except BaseException:
                    conn.rollback()
                    raise
                finally:
                    conn.close()
        return cls(path, authority=authority)

    @staticmethod
    def _create_schema(conn):
        schema = """
                CREATE TABLE IF NOT EXISTS recommendation_actions (
                    incarnation TEXT NOT NULL,
                    canonical_key TEXT NOT NULL,
                    action TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    expires_at TEXT,
                    PRIMARY KEY (incarnation, canonical_key, action)
                );
                CREATE TABLE IF NOT EXISTS recommendation_receipts (
                    incarnation TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (incarnation, request_id)
                );
                CREATE TABLE IF NOT EXISTS recommendation_exposures (
                    incarnation TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    canonical_key TEXT NOT NULL,
                    day TEXT NOT NULL,
                    visible_at TEXT NOT NULL,
                    PRIMARY KEY (incarnation, run_id, canonical_key, day)
                );
                CREATE INDEX IF NOT EXISTS recommendation_exposure_time
                    ON recommendation_exposures(incarnation, visible_at);
                CREATE TABLE recommendation_outcomes (
                    incarnation TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    outcome_id TEXT NOT NULL,
                    canonical_key TEXT NOT NULL,
                    outcome_at TEXT NOT NULL,
                    run_id TEXT,
                    exposure_day TEXT,
                    visible_at TEXT,
                    credited INTEGER NOT NULL,
                    response_json TEXT NOT NULL,
                    PRIMARY KEY (incarnation, kind, outcome_id, canonical_key)
                );
                CREATE UNIQUE INDEX recommendation_outcome_credit
                    ON recommendation_outcomes(incarnation, kind, canonical_key, exposure_day)
                    WHERE credited=1;
            """
        for statement in schema.split(";"):
            if statement.strip():
                conn.execute(statement)

    @staticmethod
    def _schema(conn):
        return [
            list(row)
            for row in conn.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE name LIKE 'recommendation_%' OR tbl_name LIKE 'recommendation_%' "
                "ORDER BY type,name"
            )
        ]

    @classmethod
    def _validate(cls, conn, receipt):
        if not isinstance(receipt, dict) or set(receipt) != {
            "store_id",
            "schema",
            "path",
            "file_identity",
        }:
            raise sqlite3.OperationalError("policy_store_unprovisioned")
        schema = cls._schema(conn)
        required_tables = {
            "recommendation_actions",
            "recommendation_receipts",
            "recommendation_exposures",
            "recommendation_outcomes",
            "recommendation_store_identity",
        }
        if not required_tables.issubset(
            {row[1] for row in schema if row[0] == "table"}
        ):
            raise sqlite3.OperationalError("policy_store_schema_mismatch_required")
        outcome_pk = [
            row[1]
            for row in sorted(
                conn.execute("PRAGMA table_info(recommendation_outcomes)").fetchall(),
                key=lambda row: row[5],
            )
            if row[5]
        ]
        if outcome_pk != ["incarnation", "kind", "outcome_id", "canonical_key"]:
            raise sqlite3.OperationalError("policy_store_schema_mismatch_required")
        if schema != receipt["schema"]:
            raise sqlite3.OperationalError("policy_store_schema_mismatch")
        rows = conn.execute(
            "SELECT store_id FROM recommendation_store_identity"
        ).fetchall()
        if [row[0] for row in rows] != [receipt["store_id"]]:
            raise sqlite3.OperationalError("policy_store_identity_mismatch")

    @staticmethod
    def _validate_file(path, receipt):
        try:
            stat = path.stat()
        except OSError:
            raise sqlite3.OperationalError("policy_store_missing") from None
        if receipt.get("file_identity") != [stat.st_dev, stat.st_ino]:
            raise sqlite3.OperationalError("policy_store_file_replaced")

    @staticmethod
    def _open_existing(path):
        return sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # Read Users before opening Events. No nested users.db writer lock,
        # including when the caller already holds its account_guard.
        receipt = self.authority.policy_store_receipt(self.db_path)
        if receipt is None:
            raise sqlite3.OperationalError("policy_store_unprovisioned")
        self._validate_file(self.db_path, receipt)
        conn = self._open_existing(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            self._validate(conn, receipt)
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def apply_action(
        self,
        incarnation: str,
        *,
        run_id: str,
        canonical_key: str,
        action: str,
        request_id: str,
        undo_action: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        """Commit policy and receipt together; membership is checked by caller."""
        incarnation, run_id, request_id = map(
            _identifier, (incarnation, run_id, request_id)
        )
        canonical_key = _key(canonical_key)
        if action == "undo":
            if undo_action not in ACTIONS:
                raise RecommendationStateError("invalid_undo_action")
        elif action not in ACTIONS or undo_action is not None:
            raise RecommendationStateError("invalid_action")
        timestamp = _clock(now)
        digest = _payload_hash(run_id, canonical_key, action, undo_action)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT payload_hash, response_json FROM recommendation_receipts WHERE incarnation=? AND request_id=?",
                (incarnation, request_id),
            ).fetchone()
            if previous:
                if previous["payload_hash"] != digest:
                    raise RecommendationStateError("idempotency_conflict")
                return json.loads(previous["response_json"])
            if action == "undo":
                conn.execute(
                    "DELETE FROM recommendation_actions WHERE incarnation=? AND canonical_key=? AND action=?",
                    (incarnation, canonical_key, undo_action),
                )
            else:
                expires = (
                    timestamp + timedelta(days=ACTION_DAYS[action])
                    if action in ACTION_DAYS
                    else None
                )
                conn.execute(
                    "INSERT INTO recommendation_actions VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(incarnation, canonical_key, action) DO UPDATE SET "
                    "run_id=excluded.run_id, occurred_at=excluded.occurred_at, expires_at=excluded.expires_at",
                    (
                        incarnation,
                        canonical_key,
                        action,
                        run_id,
                        timestamp.isoformat(),
                        expires.isoformat() if expires else None,
                    ),
                )
            response = {
                "tracked": True,
                "request_id": request_id,
                "canonical_key": canonical_key,
                "action": action,
                "undo_action": undo_action,
                "applied_at": timestamp.isoformat(),
            }
            conn.execute(
                "INSERT INTO recommendation_receipts VALUES (?, ?, ?, ?, ?)",
                (
                    incarnation,
                    request_id,
                    digest,
                    json.dumps(response, sort_keys=True),
                    timestamp.isoformat(),
                ),
            )
            return response

    def receipt(
        self,
        incarnation: str,
        *,
        request_id: str,
        run_id: str,
        canonical_key: str,
        action: str,
        undo_action: str | None = None,
    ) -> dict | None:
        """Read an acknowledged request without re-emitting or reapplying it."""
        incarnation, request_id = map(_identifier, (incarnation, request_id))
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload_hash, response_json FROM recommendation_receipts "
                "WHERE incarnation=? AND request_id=?",
                (incarnation, request_id),
            ).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != _payload_hash(
            run_id, canonical_key, action, undo_action
        ):
            raise RecommendationStateError("idempotency_conflict")
        return json.loads(row["response_json"])

    def record_exposure(
        self,
        incarnation: str,
        *,
        run_id: str,
        canonical_key: str,
        visible_fraction: float,
        visible_ms: int,
        now: datetime | None = None,
    ) -> bool:
        """Record a qualifying visible card once per account/run/item/UTC day."""
        incarnation, run_id = map(_identifier, (incarnation, run_id))
        canonical_key = _key(canonical_key)
        if (
            isinstance(visible_fraction, bool)
            or not isinstance(visible_fraction, (int, float))
            or not 0.5 <= visible_fraction <= 1
        ):
            raise RecommendationStateError("insufficient_visibility")
        if (
            isinstance(visible_ms, bool)
            or not isinstance(visible_ms, int)
            or not 1000 <= visible_ms <= 60000
        ):
            raise RecommendationStateError("insufficient_visibility")
        timestamp = _clock(now)
        with self._connection() as conn:
            inserted = conn.execute(
                "INSERT OR IGNORE INTO recommendation_exposures VALUES (?, ?, ?, ?, ?)",
                (
                    incarnation,
                    run_id,
                    canonical_key,
                    timestamp.date().isoformat(),
                    timestamp.isoformat(),
                ),
            ).rowcount
        return bool(inserted)

    def has_action(
        self,
        incarnation: str,
        *,
        run_id: str,
        canonical_key: str,
        action: str,
        now: datetime | None = None,
    ) -> bool:
        """Allow undo of an owned control even after its delivery expires."""
        incarnation, run_id = map(_identifier, (incarnation, run_id))
        canonical_key = _key(canonical_key)
        if action not in ACTIONS:
            raise RecommendationStateError("invalid_action")
        timestamp = _clock(now).isoformat()
        with self._connection() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM recommendation_actions WHERE incarnation=? AND run_id=? "
                    "AND canonical_key=? AND action=? AND occurred_at<=? "
                    "AND (expires_at IS NULL OR expires_at>?)",
                    (incarnation, run_id, canonical_key, action, timestamp, timestamp),
                ).fetchone()
                is not None
            )

    def policy(
        self, incarnation: str, *, now: datetime | None = None
    ) -> RecommendationPolicy:
        incarnation = _identifier(incarnation)
        timestamp = _clock(now)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT canonical_key, action, occurred_at FROM recommendation_actions "
                "WHERE incarnation=? AND occurred_at<=? AND (expires_at IS NULL OR expires_at>?)",
                (incarnation, timestamp.isoformat(), timestamp.isoformat()),
            ).fetchall()
            exposures = conn.execute(
                "SELECT DISTINCT canonical_key, run_id FROM recommendation_exposures "
                "WHERE incarnation=? AND visible_at>? AND visible_at<=? ORDER BY canonical_key, run_id",
                (
                    incarnation,
                    (timestamp - timedelta(days=7)).isoformat(),
                    timestamp.isoformat(),
                ),
            ).fetchall()
        groups: dict[str, set[str]] = {action: set() for action in ACTIONS}
        topics = {}
        for row in rows:
            if row["action"] not in ACTIONS:
                raise RecommendationStateError("corrupt_policy_action")
            groups[row["action"]].add(row["canonical_key"])
            if row["action"] == "topic_less":
                topics[row["canonical_key"]] = row["occurred_at"]
        return RecommendationPolicy(
            incarnation=incarnation,
            hidden=frozenset(groups["hide"]),
            already_seen=frozenset(groups["already_seen"]),
            seen=frozenset(groups["seen"]),
            interested=frozenset(groups["interested"]),
            topic_less=topics,
            recent_exposures=tuple(
                (row["canonical_key"], row["run_id"]) for row in exposures
            ),
        )

    def record_outcome(
        self,
        incarnation: str,
        *,
        canonical_key: str,
        kind: str,
        outcome_id: str,
        now: datetime | None = None,
    ) -> dict:
        """Internal producer only; caller holds account_guard, never trusts a run claim.

        Outcome receipts (including no-match receipts) are immutable per
        incarnation/kind/producer outcome ID/canonical paper for 30 days.
        One multi-paper producer outcome may therefore credit distinct papers.
        Replays return the stored response, not a new credit. Last-touch ties use
        ascending run_id. Primary metrics count positive exposure days, not rows.
        """
        incarnation = _identifier(incarnation)
        outcome_id = _key(outcome_id)
        canonical_key = _key(canonical_key)
        if kind not in {"save", "review_start"}:
            raise RecommendationStateError("invalid_outcome_kind")
        timestamp = _clock(now)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT canonical_key,response_json FROM recommendation_outcomes "
                "WHERE incarnation=? AND kind=? AND outcome_id=? AND canonical_key=?",
                (incarnation, kind, outcome_id, canonical_key),
            ).fetchone()
            if previous:
                return json.loads(previous["response_json"])
            exposure = conn.execute(
                "SELECT run_id,day,visible_at FROM recommendation_exposures "
                "WHERE incarnation=? AND canonical_key=? AND visible_at>=? AND visible_at<=? "
                "ORDER BY visible_at DESC,run_id ASC LIMIT 1",
                (
                    incarnation,
                    canonical_key,
                    (timestamp - timedelta(days=7)).isoformat(),
                    timestamp.isoformat(),
                ),
            ).fetchone()
            credited = False
            reason = "no_qualified_exposure"
            context = {}
            if exposure:
                context = {
                    "run_id": exposure["run_id"],
                    "exposure_day": exposure["day"],
                    "visible_at": exposure["visible_at"],
                }
                duplicate = conn.execute(
                    "SELECT 1 FROM recommendation_outcomes WHERE incarnation=? AND kind=? "
                    "AND canonical_key=? AND exposure_day=? AND credited=1",
                    (incarnation, kind, canonical_key, exposure["day"]),
                ).fetchone()
                credited = duplicate is None
                reason = "last_touch" if credited else "already_credited"
            response = {
                "status": "attributed" if exposure else "not_attributed",
                "reason": reason,
                "credited": credited,
                "kind": kind,
                "canonical_key": canonical_key,
                "outcome_id": outcome_id,
                "outcome_at": timestamp.isoformat(),
                **context,
            }
            conn.execute(
                "INSERT INTO recommendation_outcomes VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    incarnation,
                    kind,
                    outcome_id,
                    canonical_key,
                    timestamp.isoformat(),
                    context.get("run_id"),
                    context.get("exposure_day"),
                    context.get("visible_at"),
                    int(credited),
                    json.dumps(response, sort_keys=True),
                ),
            )
            return response

    def outcome_metrics(
        self,
        incarnation: str,
        *,
        since: datetime,
        until: datetime,
        now: datetime | None = None,
    ) -> dict:
        """Aggregate retained UTC exposure days in [since, until).

        Bounds must be UTC midnights. A day is mature only at day-end + 7 days,
        conservatively allowing every exposure on that day its full window.
        Right-censored days are separate; rate is None for an empty denominator.
        Per-kind counts are binary positive user-days and must not be summed to
        derive the primary numerator. All counts exclude future records.
        """
        incarnation = _identifier(incarnation)
        start, end, timestamp = _clock(since), _clock(until), _clock(now)
        if start >= end or any(
            (d.hour, d.minute, d.second, d.microsecond) != (0, 0, 0, 0)
            for d in (start, end)
        ):
            raise RecommendationStateError("invalid_metric_day_range")
        cutoff = timestamp - timedelta(days=30)
        with self._connection() as conn:
            days = {
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT day FROM recommendation_exposures WHERE incarnation=? "
                    "AND day>=? AND day<? AND visible_at>=? AND visible_at<=?",
                    (
                        incarnation,
                        start.date().isoformat(),
                        end.date().isoformat(),
                        cutoff.isoformat(),
                        timestamp.isoformat(),
                    ),
                )
            }
            positives = list(
                conn.execute(
                    "SELECT DISTINCT exposure_day,kind FROM recommendation_outcomes WHERE incarnation=? "
                    "AND credited=1 AND outcome_at>=? AND outcome_at<=? AND visible_at>=?",
                    (
                        incarnation,
                        cutoff.isoformat(),
                        timestamp.isoformat(),
                        cutoff.isoformat(),
                    ),
                )
            )
        mature = {
            day
            for day in days
            if datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
            + timedelta(days=8)
            <= timestamp
        }

        def aggregate(selected):
            by_kind = {
                kind: {day for day, k in positives if k == kind and day in selected}
                for kind in ("save", "review_start")
            }
            positive = set().union(*by_kind.values())
            return {
                "visible_userdays": len(selected),
                "positive_userdays": len(positive),
                "per_kind_counts": {k: len(v) for k, v in by_kind.items()},
                "rate": len(positive) / len(selected) if selected else None,
            }

        return {
            "total": aggregate(days),
            "mature": aggregate(mature),
            "right_censored": aggregate(days - mature),
        }

    def delete_incarnation(self, incarnation: str) -> None:
        incarnation = _identifier(incarnation)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for table in (
                "recommendation_actions",
                "recommendation_receipts",
                "recommendation_exposures",
                "recommendation_outcomes",
            ):
                conn.execute(f"DELETE FROM {table} WHERE incarnation=?", (incarnation,))

    def prune(self, *, now: datetime | None = None) -> None:
        """Expire bounded training/read/exposure data without expiring hard hides."""
        timestamp = _clock(now)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM recommendation_actions WHERE expires_at IS NOT NULL AND expires_at<=?",
                (timestamp.isoformat(),),
            )
            conn.execute(
                "DELETE FROM recommendation_exposures WHERE visible_at<?",
                ((timestamp - timedelta(days=30)).isoformat(),),
            )
            conn.execute(
                "DELETE FROM recommendation_receipts WHERE created_at<?",
                ((timestamp - timedelta(days=30)).isoformat(),),
            )
            conn.execute(
                "DELETE FROM recommendation_outcomes WHERE outcome_at<?",
                ((timestamp - timedelta(days=30)).isoformat(),),
            )
