"""SQLite authority for account identity, updates, and deletion reservations."""

import json
import hashlib
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from filelock import FileLock

_DEFAULT_DB_PATH = Path("data/users.db")
_RESERVED = {
    "username",
    "password_hash",
    "role",
    "created_at",
    "metadata",
    "account_incarnation",
    "incarnation",
    "state",
    "initialized_at",
    "cleanup_receipt",
    "legacy_event_cutoff",
}
_SELECT = """SELECT u.*, l.incarnation AS account_incarnation, l.legacy_event_cutoff
             FROM users u JOIN account_lifecycles l USING(username)
             WHERE l.state = 'active'"""


class AccountLifecycleError(RuntimeError):
    """Public, payload-free lifecycle failure with a stable reason code."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class _UserTransaction:
    def __init__(self, conn):
        self.conn = conn

    def get_all(self):
        return {
            row["username"]: UserDB._row_to_dict(row)
            for row in self.conn.execute(_SELECT + " ORDER BY username")
        }

    def get(self, username):
        row = self.conn.execute(_SELECT + " AND u.username = ?", (username,)).fetchone()
        return UserDB._row_to_dict(row) if row else None

    def get_lifecycle(self, username):
        row = self.conn.execute(
            "SELECT incarnation AS account_incarnation, state FROM account_lifecycles WHERE username=?",
            (username,),
        ).fetchone()
        return dict(row) if row else None

    def validate_principal(self, username, incarnation):
        if (
            not isinstance(username, str)
            or not username
            or not isinstance(incarnation, str)
            or not incarnation
        ):
            raise AccountLifecycleError("invalid_principal")
        user = self.get(username)
        if user is None or user["account_incarnation"] != incarnation:
            raise AccountLifecycleError("account_inactive_or_mismatch")
        return user

    def create_account(self, username, data, *, only_if_pristine=False):
        if not isinstance(username, str) or not username:
            raise AccountLifecycleError("invalid_username")
        if (
            only_if_pristine
            and self.conn.execute("SELECT 1 FROM account_history LIMIT 1").fetchone()
        ):
            raise AccountLifecycleError("store_not_pristine")
        if self.conn.execute(
            "SELECT 1 FROM account_lifecycles WHERE username = ?", (username,)
        ).fetchone():
            raise AccountLifecycleError("username_reserved")
        incarnation = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO users(username, password_hash, role, created_at, metadata) VALUES (?, ?, ?, ?, ?)",
            (
                username,
                data.get("password_hash"),
                data.get("role") or "user",
                data.get("created_at"),
                self._metadata(data),
            ),
        )
        self.conn.execute(
            "INSERT INTO account_lifecycles (username, incarnation, state, initialized_at, cleanup_receipt) VALUES (?, ?, 'active', ?, NULL)",
            (username, incarnation, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO account_history VALUES (?)", (username,)
        )
        return self.get(username)

    @staticmethod
    def _metadata(data):
        extra = dict(data.get("metadata") or {})
        extra.update(data)
        return json.dumps(
            {k: v for k, v in extra.items() if k not in _RESERVED}, ensure_ascii=False
        )

    def upsert(self, username, data, *, expected_incarnation):
        """Update only: never create an identity from a stale snapshot."""
        current = self.validate_principal(username, expected_incarnation)
        supplied = data.get("account_incarnation", expected_incarnation)
        if supplied != expected_incarnation:
            raise AccountLifecycleError("incarnation_immutable")
        merged = {**current, **data}
        self.conn.execute(
            "UPDATE users SET password_hash=?, role=?, created_at=?, metadata=? WHERE username=?",
            (
                merged["password_hash"],
                merged["role"],
                merged["created_at"],
                self._metadata(merged),
                username,
            ),
        )

    def begin_delete(self, username, incarnation):
        row = self.conn.execute(
            "SELECT * FROM account_lifecycles WHERE username=?", (username,)
        ).fetchone()
        if row is None or row["incarnation"] != incarnation:
            raise AccountLifecycleError("account_inactive_or_mismatch")
        if row["state"] == "active":
            self.conn.execute(
                "UPDATE account_lifecycles SET state='deleting' WHERE username=?",
                (username,),
            )
        return incarnation

    def finish_delete(self, username, incarnation, *, cleanup_succeeded):
        row = self.conn.execute(
            "SELECT * FROM account_lifecycles WHERE username=?", (username,)
        ).fetchone()
        if row is None or row["incarnation"] != incarnation:
            raise AccountLifecycleError("account_inactive_or_mismatch")
        if row["state"] == "active":
            raise AccountLifecycleError("deletion_not_started")
        self.conn.execute("DELETE FROM users WHERE username=?", (username,))
        if cleanup_succeeded:
            self.conn.execute(
                "DELETE FROM account_lifecycles WHERE username=?", (username,)
            )
        else:
            self.conn.execute(
                "UPDATE account_lifecycles SET state='cleanup_pending', cleanup_receipt='incomplete' WHERE username=?",
                (username,),
            )


class UserDB:
    """All mutations serialize across processes in the authoritative SQLite DB."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = Path(db_path or _DEFAULT_DB_PATH)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(str(self._db_path), timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def policy_store_receipt(self, path):
        """Read immutable provisioning authority without acquiring a writer lock.

        Safe inside account_guard: this connection only reads committed metadata.
        It never creates a missing authority DB.
        """
        conn = sqlite3.connect(self._db_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM account_store_meta WHERE key=?",
                ("policy_store",),
            ).fetchone()
            if row is None:
                return None
            try:
                receipt = json.loads(row[0])
            except (TypeError, ValueError):
                raise sqlite3.OperationalError("policy_store_invalid_receipt") from None
            if not isinstance(receipt, dict):
                raise sqlite3.OperationalError("policy_store_invalid_receipt")
            if receipt.get("path") != str(Path(path).resolve()):
                raise sqlite3.OperationalError("policy_store_path_mismatch")
            return receipt
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield _UserTransaction(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        # DDL, identities and completion marker are committed together. No
        # executescript: its implicit commit would break initialization rollback.
        with self.transaction() as tx:
            tx.conn.execute(
                "CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT, role TEXT DEFAULT 'user', created_at TEXT, metadata TEXT)"
            )
            tx.conn.execute(
                "CREATE TABLE IF NOT EXISTS account_lifecycles (username TEXT PRIMARY KEY, incarnation TEXT NOT NULL UNIQUE, state TEXT NOT NULL CHECK(state IN ('active','deleting','cleanup_pending')), initialized_at TEXT NOT NULL, cleanup_receipt TEXT, legacy_event_cutoff TEXT)"
            )
            tx.conn.execute(
                "CREATE TABLE IF NOT EXISTS account_history (username TEXT PRIMARY KEY)"
            )
            tx.conn.execute(
                "CREATE TABLE IF NOT EXISTS account_store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            initialized = tx.conn.execute(
                "SELECT 1 FROM account_store_meta WHERE key='lifecycle_initialized'"
            ).fetchone()
            # One frozen store-owned UTC boundary, atomic with initial identities.
            cutoff = datetime.now(timezone.utc).isoformat()
            tx.conn.execute(
                "INSERT OR IGNORE INTO account_store_meta VALUES ('legacy_event_cutoff', ?)",
                (cutoff,),
            )
            cutoff = tx.conn.execute(
                "SELECT value FROM account_store_meta WHERE key='legacy_event_cutoff'"
            ).fetchone()[0]
            missing = tx.conn.execute(
                "SELECT u.username FROM users u LEFT JOIN account_lifecycles l USING(username) WHERE l.username IS NULL"
            ).fetchall()
            if initialized and missing:
                raise AccountLifecycleError("lifecycle_integrity_error")
            for row in missing:
                tx.conn.execute(
                    "INSERT INTO account_lifecycles (username, incarnation, state, initialized_at, cleanup_receipt, legacy_event_cutoff) VALUES (?, ?, 'active', ?, NULL, ?)",
                    (row["username"], uuid.uuid4().hex, cutoff, cutoff),
                )
            tx.conn.execute(
                "INSERT OR IGNORE INTO account_history SELECT username FROM account_lifecycles"
            )
            tx.conn.execute(
                "INSERT OR IGNORE INTO account_store_meta VALUES ('lifecycle_initialized', '1')"
            )

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except (ValueError, TypeError):
            metadata = {}
        user = (
            {k: v for k, v in metadata.items() if k not in _RESERVED}
            if isinstance(metadata, dict)
            else {}
        )
        user.update(
            {
                k: row[k]
                for k in (
                    "password_hash",
                    "role",
                    "created_at",
                    "account_incarnation",
                    "legacy_event_cutoff",
                )
            }
        )
        return user

    def get_all(self):
        with self.transaction() as tx:
            return tx.get_all()

    def get(self, username):
        with self.transaction() as tx:
            return tx.get(username)

    def get_lifecycle(self, username):
        """Read reservations, including identities whose credentials were removed."""
        with self.transaction() as tx:
            return tx.get_lifecycle(username)

    @contextmanager
    def cleanup_lock(self, username):
        """Nonblocking cross-process cleanup lease; never unlink its lock file."""
        digest = hashlib.sha256(username.encode("utf-8")).hexdigest()
        root = self._db_path.resolve().parent / ".account-cleanup-locks"
        if root.is_symlink():
            raise AccountLifecycleError("unsafe_cleanup_lock")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = root / (digest + ".lock")
        if path.is_symlink():
            raise AccountLifecycleError("unsafe_cleanup_lock")
        with FileLock(str(path), timeout=0):
            yield

    def create_account(self, username, data, *, only_if_pristine=False):
        with self.transaction() as tx:
            return tx.create_account(username, data, only_if_pristine=only_if_pristine)

    def upsert(self, username, data, *, expected_incarnation):
        with self.transaction() as tx:
            tx.upsert(username, data, expected_incarnation=expected_incarnation)

    def validate_principal(self, username, incarnation):
        with self.transaction() as tx:
            return tx.validate_principal(username, incarnation)

    @contextmanager
    def account_guard(self, username, incarnation):
        """Serialize a bounded local final write with deletion/registration.

        No network, ranking, nested UserDB calls or lengthy cleanup in this
        block. Other databases/files are NOT made atomic with this transaction.
        A failed external write must propagate; readers must revalidate identity.
        """
        with self.transaction() as tx:
            yield tx.validate_principal(username, incarnation)

    def begin_delete(self, username, incarnation):
        with self.transaction() as tx:
            return tx.begin_delete(username, incarnation)

    def finish_delete(self, username, incarnation, *, cleanup_succeeded):
        with self.transaction() as tx:
            tx.finish_delete(username, incarnation, cleanup_succeeded=cleanup_succeeded)

    def count(self):
        return len(self.get_all())

    def migrate_from_json(self, json_path):
        """One atomic legacy import. History prevents deleted-user resurrection."""
        path = Path(json_path)
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(data, dict):
            raise AccountLifecycleError("invalid_legacy_users")
        with self.transaction() as tx:
            if tx.conn.execute(
                "SELECT 1 FROM account_store_meta WHERE key='legacy_import_complete'"
            ).fetchone():
                return 0
            count = 0
            for username, record in data.items():
                if not isinstance(record, dict):
                    raise AccountLifecycleError("invalid_legacy_users")
                if tx.conn.execute(
                    "SELECT 1 FROM account_history WHERE username=?", (username,)
                ).fetchone():
                    continue
                tx.create_account(username, record)
                tx.conn.execute(
                    "UPDATE account_lifecycles SET legacy_event_cutoff=(SELECT value FROM account_store_meta WHERE key='legacy_event_cutoff') WHERE username=?",
                    (username,),
                )
                count += 1
            tx.conn.execute(
                "INSERT INTO account_store_meta VALUES ('legacy_import_complete', '1')"
            )
            return count
