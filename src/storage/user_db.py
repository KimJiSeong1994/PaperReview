"""SQLite authority for account identity, updates, and deletion reservations."""

import json
import hashlib
import math
import sqlite3
import time
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
                "DELETE FROM external_identities WHERE username=? AND account_incarnation=?",
                (username, incarnation),
            )
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
            tx.conn.execute(
                """CREATE TABLE IF NOT EXISTS external_identities (
                    provider TEXT NOT NULL, subject TEXT NOT NULL,
                    username TEXT NOT NULL, account_incarnation TEXT NOT NULL,
                    PRIMARY KEY(provider, subject),
                    UNIQUE(provider, username, account_incarnation)
                )"""
            )
            tx.conn.execute(
                """CREATE TABLE IF NOT EXISTS google_auth_challenges (
                    nonce_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL,
                    target_username TEXT, target_incarnation TEXT,
                    CHECK ((target_username IS NULL AND target_incarnation IS NULL)
                        OR (target_username IS NOT NULL AND target_incarnation IS NOT NULL))
                )"""
            )
            tx.conn.execute(
                "CREATE INDEX IF NOT EXISTS google_auth_challenges_expiry ON google_auth_challenges(expires_at)"
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

    def create_google_challenge(
        self, nonce_hash, *, expires_at, target_username=None, target_incarnation=None
    ):
        """Persist a short-lived nonce after any legacy credential verification.

        Only the SHA-256 digest belongs here; the browser-bound raw nonce and
        Google token verification remain the HTTP layer's responsibility.
        """
        now = time.time()
        if (
            not isinstance(nonce_hash, str)
            or len(nonce_hash) != 64
            or any(char not in "0123456789abcdef" for char in nonce_hash)
            or not isinstance(expires_at, (int, float))
            or not math.isfinite(expires_at)
            or expires_at <= now
        ):
            raise AccountLifecycleError("google_challenge_invalid")
        if (target_username is None) != (target_incarnation is None):
            raise AccountLifecycleError("invalid_principal")
        with self.transaction() as tx:
            if target_username is not None:
                tx.validate_principal(target_username, target_incarnation)
            tx.conn.execute("DELETE FROM google_auth_challenges WHERE expires_at <= ?", (now,))
            tx.conn.execute(
                "INSERT INTO google_auth_challenges VALUES (?, ?, ?, ?)",
                (nonce_hash, expires_at, target_username, target_incarnation),
            )

    @staticmethod
    def _complete_google_identity(tx, challenge, subject, *, now, profile):
        identity = tx.conn.execute(
            "SELECT username, account_incarnation FROM external_identities WHERE provider='google' AND subject=?",
            (subject,),
        ).fetchone()
        target_username = challenge["target_username"]
        is_new_user = False
        if target_username is not None:
            user = tx.validate_principal(target_username, challenge["target_incarnation"])
            if identity and (
                identity["username"] != target_username
                or identity["account_incarnation"] != user["account_incarnation"]
            ):
                raise AccountLifecycleError("google_identity_conflict")
            linked = tx.conn.execute(
                "SELECT subject FROM external_identities WHERE provider='google' AND username=? AND account_incarnation=?",
                (target_username, user["account_incarnation"]),
            ).fetchone()
            if linked and linked["subject"] != subject:
                raise AccountLifecycleError("google_account_already_linked")
            username = target_username
        elif identity:
            username = identity["username"]
            user = tx.validate_principal(username, identity["account_incarnation"])
        else:
            # Handles are unrelated to an email/name and never auto-link an
            # existing account. History also prevents reusing a deleted handle.
            for _ in range(5):
                username = "google_" + uuid.uuid4().hex[:16]
                if not tx.conn.execute(
                    "SELECT 1 FROM account_history WHERE username=?", (username,)
                ).fetchone():
                    break
            else:
                raise AccountLifecycleError("google_username_unavailable")
            data = {
                "role": "user", "password_hash": None,
                "created_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            }
            # Never accept credential/role fields from provider profile data.
            for key, limit in (("display_name", 200), ("email", 320)):
                value = (profile or {}).get(key)
                if isinstance(value, str) and value:
                    data[key] = value[:limit]
            user = tx.create_account(username, data)
            is_new_user = True
        if identity is None:
            tx.conn.execute(
                "INSERT INTO external_identities VALUES ('google', ?, ?, ?)",
                (subject, username, user["account_incarnation"]),
            )
        return {"username": username, "user": user, "is_new_user": is_new_user}

    def complete_google_login(self, nonce_hash, subject, *, now, profile=None):
        """Consume one verified browser challenge and atomically bind/sign in.

        Signature, audience, issuer and raw nonce must already be verified by
        the caller. Expected account/link failures still consume the nonce;
        their savepoint rolls back any identity writes while retaining that
        consumption. Unexpected storage failures roll back the whole operation.
        """
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 255:
            raise AccountLifecycleError("google_identity_invalid")
        if not isinstance(now, (int, float)) or not math.isfinite(now):
            raise AccountLifecycleError("google_challenge_invalid")
        failure = None
        result = None
        with self.transaction() as tx:
            challenge = tx.conn.execute(
                "SELECT * FROM google_auth_challenges WHERE nonce_hash=?", (nonce_hash,)
            ).fetchone()
            tx.conn.execute("DELETE FROM google_auth_challenges WHERE nonce_hash=?", (nonce_hash,))
            if challenge is None or challenge["expires_at"] <= now:
                failure = AccountLifecycleError("google_challenge_invalid")
            else:
                tx.conn.execute("SAVEPOINT google_identity")
                try:
                    result = self._complete_google_identity(
                        tx, challenge, subject, now=now, profile=profile
                    )
                except AccountLifecycleError as exc:
                    tx.conn.execute("ROLLBACK TO google_identity")
                    failure = exc
                finally:
                    tx.conn.execute("RELEASE google_identity")
        if failure is not None:
            raise failure
        return result

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
