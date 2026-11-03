"""Admin stats for the conversational product (routers/admin_assistant.py) and /api/admin/users enrichment.

Stores live under the per-test DATA_DIR from conftest; turn timestamps are
written directly so windows and KST bucketing are deterministic.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

ENDPOINTS = ("/api/admin/conversations/stats", "/api/admin/souls/stats", "/api/admin/llm-usage")
NOW = datetime.now(timezone.utc)
SECRET = "SECRET-7f3a"


def _ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


@pytest.fixture
def client(auth_headers):  # noqa: ARG001 — seeds test-admin
    from api_server import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def conv_db():
    from routers.deps.storage import _get_conversation_db

    return _get_conversation_db()


@pytest.fixture
def soul_db():
    from routers.deps.storage import _get_soul_db

    return _get_soul_db()


def _user(username: str, role: str = "user", created_at: str = "") -> str:
    """Create an account and return its incarnation."""
    from routers.deps.storage import _get_user_db

    return _get_user_db().create_account(
        username, {"password_hash": "x", "role": role, "created_at": created_at}
    )["account_incarnation"]


def _bearer(username: str, role: str = "user") -> dict:
    from tests.conftest import _make_test_token

    return {"Authorization": f"Bearer {_make_test_token(username, role)}"}


def _conv(db, username: str, incarnation: str, created_at: str | None = None, title: str = "t") -> str:
    conv = db.create_conversation(username, incarnation, title)
    if created_at:
        _sql(db, "UPDATE conversations SET created_at = ?, updated_at = ? WHERE id = ?",
             (created_at, created_at, conv["id"]))
    return conv["id"]


def _turn(db, conv_id: str, role: str, created_at: str, *, content: str = "", blocks=None,
          intent=None, status: str = "done", latency_ms=None) -> None:
    _sql(
        db,
        "INSERT INTO turns (id, conversation_id, seq, role, content, blocks_json, intent, status, model,"
        " latency_ms, created_at) VALUES (?, ?, (SELECT COALESCE(MAX(seq), 0) + 1 FROM turns"
        " WHERE conversation_id = ?), ?, ?, ?, ?, ?, NULL, ?, ?)",
        (uuid4().hex, conv_id, conv_id, role, content, json.dumps(blocks or []), intent, status,
         latency_ms, created_at),
    )


def _sql(db, sql: str, params: tuple) -> None:
    with sqlite3.connect(db._db_path) as conn:
        conn.execute(sql, params)


def _stats(client, auth_headers, path="/api/admin/conversations/stats", days=7) -> dict:
    resp = client.get(path, params={"days": days}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Auth / params ────────────────────────────────────────────────────


def test_assistant_admin_endpoints_require_admin(client):
    _user("plain")
    for path in ENDPOINTS:
        assert client.get(path).status_code == 401
        assert client.get(path, headers=_bearer("plain")).status_code == 403


def test_assistant_admin_endpoints_reject_bad_window(client, auth_headers):
    for path in ENDPOINTS:
        assert client.get(path, params={"days": 30}, headers=auth_headers).status_code == 400


# ── Conversation stats ───────────────────────────────────────────────


def test_conversation_stats_empty_db_is_zero_not_error(client, auth_headers):
    body = _stats(client, auth_headers, days=28)
    assert body["totals"] == {"conversations": 0, "user_turns": 0, "assistant_turns": 0, "active_users": 0, "running": 0}
    assert body["error_rate"] is None
    assert len(body["daily"]) == 28 and all(d["user_turns"] == 0 for d in body["daily"])
    assert body["reviews"]["verification"]["verified_ratio"] is None
    assert body["latency"] == [] and body["intents"] == []
    assert "metric_definitions" in body


def test_conversation_stats_outcome_taxonomy(client, auth_headers, conv_db):
    cid = _conv(conv_db, "a", "inc-a")
    t = _ago(hours=1)
    _turn(conv_db, cid, "user", t, content="q")
    _turn(conv_db, cid, "assistant", t, intent="search", status="done", latency_ms=100)
    _turn(conv_db, cid, "assistant", t, intent="search", status="error", latency_ms=50)  # failed
    _turn(conv_db, cid, "assistant", t, content="중단됨", status="error")  # cancelled
    _turn(conv_db, cid, "assistant", t, content="", status="error")  # interrupted
    _turn(conv_db, cid, "assistant", t, status="running")
    body = _stats(client, auth_headers)
    assert body["outcomes"] == {"done": 1, "failed": 1, "cancelled": 1, "interrupted": 1}
    assert body["totals"]["running"] == 1 and body["totals"]["assistant_turns"] == 5
    assert body["error_rate"] == round(2 / 3, 3)
    assert body["intents"] == [{"intent": "search", "turns": 2, "failed": 1, "interrupted": 0}]


def test_conversation_stats_latency_is_per_intent(client, auth_headers, conv_db):
    cid = _conv(conv_db, "a", "inc-a")
    t = _ago(hours=1)
    for ms in (1000, 2000, 3000, 4000, 5000, 6000):
        _turn(conv_db, cid, "assistant", t, intent="search", latency_ms=ms)
    for ms in (900, 1100):
        _turn(conv_db, cid, "assistant", t, intent="review", latency_ms=ms)
    body = _stats(client, auth_headers)
    assert body["latency"] == [
        {"intent": "search", "samples": 6, "p50_ms": 3000, "p95_ms": 6000},
        {"intent": "review", "samples": 2, "p50_ms": 900, "p95_ms": None},
    ]


def test_conversation_stats_window_excludes_old_turns(client, auth_headers, conv_db):
    old = _conv(conv_db, "a", "inc-a", created_at=_ago(days=40))
    _turn(conv_db, old, "user", _ago(days=40))
    _turn(conv_db, old, "assistant", _ago(days=40), intent="chat")
    body = _stats(client, auth_headers)
    assert body["totals"]["conversations"] == 0 and body["totals"]["user_turns"] == 0
    assert _stats(client, auth_headers, days=90)["totals"]["user_turns"] == 1


def test_conversation_stats_daily_uses_kst(conv_db, monkeypatch):
    from routers import admin_assistant

    cid = _conv(conv_db, "a", "inc-a")
    _turn(conv_db, cid, "user", "2026-11-02T16:00:00+00:00")
    monkeypatch.setattr(admin_assistant, "_window", lambda days: (
        {"days": 7, "start": "2026-10-28T15:00:00+00:00", "end": "x", "timezone": "Asia/Seoul"},
        ["2026-11-02", "2026-11-03"],
    ))
    daily = {d["date"]: d for d in admin_assistant._conversation_stats(7)["daily"]}
    assert daily["2026-11-03"]["user_turns"] == 1 and daily["2026-11-02"]["user_turns"] == 0


def _review_block(session_id: str, mode: str | None) -> dict:
    block = {"type": "review_started", "session_id": session_id, "paper_title": SECRET}
    if mode:
        block["mode"] = mode
    return block


def test_conversation_stats_review_modes_and_verification(client, auth_headers, conv_db):
    from routers.deps import storage

    full_sid, fast_sid, old_sid = (f"review_20261101_120000_{h * 8}" for h in "abc")
    ws = Path(storage.WORKSPACE_DIR)
    (ws / full_sid / "verifications").mkdir(parents=True)
    (ws / full_sid / "metadata.json").write_text(json.dumps({"status": "completed"}))
    statuses = ["verified"] * 3 + ["partially_verified", "contradicted"]
    (ws / full_sid / "verifications" / "claims_20261101_120500.json").write_text(
        json.dumps({"claims": [{"verification_status": s, "text": SECRET} for s in statuses]})
    )
    cid = _conv(conv_db, "a", "inc-a")
    t = _ago(hours=2)
    _turn(conv_db, cid, "assistant", t, intent="review", blocks=[_review_block(full_sid, "full")])
    _turn(conv_db, cid, "assistant", t, intent="review", blocks=[_review_block(fast_sid, "fast")])
    _turn(conv_db, cid, "assistant", t, intent="review", blocks=[_review_block(old_sid, None)])
    reviews = _stats(client, auth_headers)["reviews"]
    assert reviews["started"] == 3
    assert reviews["by_mode"] == {"fast": 2, "full": 1} and reviews["mode_missing"] == 1
    assert reviews["outcomes"] == {"completed": 1, "failed": 0, "running": 0, "unknown": 2}
    assert reviews["verification"] == {
        "sessions_with_claims": 1, "claims": 5, "verified": 3, "partially_verified": 1,
        "unverified": 0, "contradicted": 1, "verified_ratio": 0.6,
    }


def test_conversation_stats_ignores_unsafe_session_id(client, auth_headers, conv_db, monkeypatch):
    from routers import admin_assistant

    touched = []
    monkeypatch.setattr(admin_assistant, "Path", lambda *a: touched.append(a) or Path(*a))
    cid = _conv(conv_db, "a", "inc-a")
    _turn(conv_db, cid, "assistant", _ago(hours=1), intent="review",
          blocks=[_review_block("../../etc", "full")])
    reviews = _stats(client, auth_headers)["reviews"]
    assert reviews["outcomes"]["unknown"] == 1 and touched == []


def test_conversation_stats_activation(client, auth_headers, conv_db):
    fast = _user("fast_user", created_at=_ago(hours=5))
    _user("slow_user", created_at=_ago(days=3))
    _user("old_user", created_at=_ago(days=60))
    _conv(conv_db, "fast_user", fast, created_at=_ago(hours=4))
    assert _stats(client, auth_headers)["activation"] == {"signups": 2, "first_conversation_within_24h": 1}


# ── Soul stats ───────────────────────────────────────────────────────


def test_souls_stats_counts_by_kind_and_profile_fill(client, auth_headers, soul_db):
    soul_db.add_memories("a", "i1", [{"kind": "interest", "text": "graphs"}, {"kind": "topic", "text": "rag"}], None)
    soul_db.add_memories("a", "i1", [{"kind": "interest", "text": "graphs"}], None)  # hit → 2
    soul_db.add_memories("b", "i2", [{"kind": "topic", "text": "llm"}], None)
    soul_db.set_user_md("c", "i3", "about me")
    soul_db.save_profile("a", "i1", {"role": "student", "keywords": ["x"]}, "h")
    soul_db.save_profile("b", "i2", {"domain": "nlp", "keywords": []}, "h")
    _sql(soul_db, "UPDATE research_profiles SET updated_at = ? WHERE username = 'b'", (_ago(days=2),))
    body = _stats(client, auth_headers, "/api/admin/souls/stats")
    assert body["accounts"] == {"with_soul": 3, "with_memories": 2, "with_user_md": 1}
    assert [k["kind"] for k in body["memories"]["by_kind"]] == [
        "preference", "topic", "paper", "fact", "research", "interest"]
    kinds = {k["kind"]: k for k in body["memories"]["by_kind"]}
    assert kinds["topic"] == {"kind": "topic", "count": 2, "accounts": 2} and kinds["paper"]["count"] == 0
    assert body["memories"]["total"] == 3 and body["memories"]["new_in_window"] == 3
    assert body["memories"]["interest_avg_hits"] == 2
    assert body["profiles"] == {"total": 2, "stale_over_24h": 1, "with_role": 1, "with_domain": 1, "with_keywords": 1}


def test_souls_stats_empty_db(client, auth_headers):
    body = _stats(client, auth_headers, "/api/admin/souls/stats")
    assert body["memories"]["total"] == 0 and body["memories"]["interest_avg_hits"] is None
    assert body["profiles"]["total"] == 0 and len(body["memories"]["by_kind"]) == 6


# ── Privacy ──────────────────────────────────────────────────────────


def test_assistant_admin_responses_leak_no_user_text(client, auth_headers, conv_db, soul_db, tmp_path, monkeypatch):
    from src.utils import llm_usage

    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"ts": NOW.timestamp(), "stage": "assistant_stream", "model": "m",
                                  "prompt_tokens": 1, "completion_tokens": 1}) + "\n")
    monkeypatch.setattr(llm_usage, "LEDGER_PATH", ledger)
    inc = _user("leaky")
    cid = _conv(conv_db, "leaky", inc, title=f"{SECRET} title")
    _turn(conv_db, cid, "user", _ago(hours=1), content=f"{SECRET} question")
    _turn(conv_db, cid, "assistant", _ago(hours=1), content=f"{SECRET} answer", intent="review",
          blocks=[_review_block("review_20261101_120000_dddddddd", "full")], latency_ms=5)
    soul_db.add_memories("leaky", inc, [{"kind": "fact", "text": f"{SECRET} memory"}], cid)
    soul_db.set_user_md("leaky", inc, f"{SECRET} user md")
    soul_db.save_profile("leaky", inc, {"summary": SECRET, "keywords": [SECRET], "role": SECRET}, "h")
    dumps = [json.dumps(_stats(client, auth_headers, p)) for p in ENDPOINTS]
    users = client.get("/api/admin/users", headers=auth_headers)
    assert users.status_code == 200
    dumps.append(users.text)
    for text in dumps:
        assert SECRET not in text and cid not in text and "review_20261101" not in text


# ── /api/admin/users enrichment ──────────────────────────────────────


def _users_by_name(client, auth_headers) -> dict:
    resp = client.get("/api/admin/users", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return {u["username"]: u for u in resp.json()["users"]}


def test_admin_users_enriched_with_current_incarnation_only(client, auth_headers, conv_db, soul_db):
    inc = _user("bob")
    _conv(conv_db, "bob", "previous-incarnation")
    _conv(conv_db, "bob", inc, created_at=_ago(days=1))
    last = _conv(conv_db, "bob", inc)
    soul_db.add_memories("bob", inc, [{"kind": "topic", "text": "a"}, {"kind": "fact", "text": "b"}], None)
    soul_db.add_memories("bob", "previous-incarnation", [{"kind": "topic", "text": "old"}], None)
    soul_db.save_profile("bob", inc, {"role": "x"}, "h")
    bob = _users_by_name(client, auth_headers)["bob"]
    assert bob["conversation_count"] == 2 and bob["memory_count"] == 2
    assert bob["last_conversation_at"] == conv_db.get_conversation(last, "bob", inc)["updated_at"]
    assert bob["profile_updated_at"] is not None
    admin = _users_by_name(client, auth_headers)["test-admin"]
    assert (admin["conversation_count"], admin["last_conversation_at"], admin["memory_count"],
            admin["profile_updated_at"]) == (0, None, 0, None)


def test_admin_users_counts_drop_to_zero_after_user_delete(client, auth_headers, conv_db, soul_db, tmp_path, monkeypatch):
    from filelock import FileLock

    from routers.deps import user_deletion
    from routers.deps.storage import _get_user_db
    from src.recommendation_state import RecommendationState

    # Isolate every cascade path (module globals are captured at import), as test_admin_delete_user does.
    events_db = Path(os.environ["EVENTS_DB_PATH"])
    for name, value in {
        "EVENTS_DB_PATH": events_db,
        "PROFILE_DB_PATH": tmp_path / "profile.db",
        "EMBEDDINGS_USERS_DIR": tmp_path / "embeddings" / "users",
        "GDPR_AUDIT_LOG": tmp_path / "audit.jsonl",
        "BLOG_POSTS_FILE": tmp_path / "blog.json",
        "BLOG_POSTS_LOCK": FileLock(str(tmp_path / "blog.lock")),
        "CURRICULA_DIR": tmp_path / "curricula",
        "PAPERS_FILE": tmp_path / "papers.json",
        "RECOMMENDATIONS_DIR": tmp_path / "recommendations",
        "RECOMMENDATION_CANDIDATES_DIR": tmp_path / "candidates",
    }.items():
        monkeypatch.setattr(user_deletion, name, value)
    RecommendationState.initialize(events_db, authority=_get_user_db())
    inc = _user("gone")
    cid = _conv(conv_db, "gone", inc)
    _turn(conv_db, cid, "user", _ago(hours=1))
    soul_db.add_memories("gone", inc, [{"kind": "topic", "text": "a"}], None)
    assert _stats(client, auth_headers)["totals"]["user_turns"] == 1
    resp = client.delete("/api/admin/users/gone", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert "gone" not in _users_by_name(client, auth_headers)
    assert _stats(client, auth_headers)["totals"]["user_turns"] == 0
    assert _stats(client, auth_headers, "/api/admin/souls/stats")["memories"]["total"] == 0


# ── LLM usage ────────────────────────────────────────────────────────


def test_llm_usage_missing_ledger_is_unavailable(client, auth_headers, tmp_path, monkeypatch):
    from src.utils import llm_usage

    monkeypatch.setattr(llm_usage, "LEDGER_PATH", tmp_path / "none.jsonl")
    body = _stats(client, auth_headers, "/api/admin/llm-usage")
    assert body["available"] is False and body["reason"] == "ledger not found"
    assert body["totals"]["calls"] == 0 and len(body["daily"]) == 7


def test_llm_usage_aggregates_window_and_skips_malformed(client, auth_headers, tmp_path, monkeypatch):
    from src.utils import llm_usage

    ledger = tmp_path / "u.jsonl"
    now = NOW.timestamp()
    rows = [
        {"ts": now, "stage": "fast_review", "model": "m1", "prompt_tokens": 100, "completion_tokens": 10, "cached_tokens": 40},
        {"ts": now, "stage": "fast_review", "model": "m1", "prompt_tokens": 50, "completion_tokens": 5},
        {"ts": now, "stage": "assistant_stream", "model": "m2", "prompt_tokens": 7, "completion_tokens": 3},
        {"ts": now - 40 * 86400, "stage": "old", "model": "m1", "prompt_tokens": 999, "completion_tokens": 999},
        {"ts": "yesterday", "stage": "bad_ts", "model": "m1", "prompt_tokens": 1},
    ]
    ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\n{not json\n")
    monkeypatch.setattr(llm_usage, "LEDGER_PATH", ledger)
    body = _stats(client, auth_headers, "/api/admin/llm-usage")
    assert body["available"] is True and body["ledger"]["malformed_lines"] == 1
    assert body["totals"] == {"calls": 3, "prompt_tokens": 157, "completion_tokens": 18, "cached_tokens": 40}
    assert body["by_stage"] == [
        {"stage": "fast_review", "model": "m1", "calls": 2, "prompt_tokens": 150, "completion_tokens": 15},
        {"stage": "assistant_stream", "model": "m2", "calls": 1, "prompt_tokens": 7, "completion_tokens": 3},
    ]
    assert sum(d["prompt_tokens"] for d in body["daily"]) == 157
    assert body["coverage"]["unrecorded_stages"] == ["claim_verification"]


# ── Schema ───────────────────────────────────────────────────────────


def test_conversation_db_has_turns_created_index(conv_db):
    with sqlite3.connect(conv_db._db_path) as conn:
        names = [r[1] for r in conn.execute("PRAGMA index_list(turns)")]
    assert "idx_turns_created" in names
