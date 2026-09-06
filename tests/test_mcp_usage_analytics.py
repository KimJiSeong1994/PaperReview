from __future__ import annotations

import asyncio
import datetime as dt
import sqlite3
import threading
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from routers.deps.auth import get_admin_user, get_current_user
from routers.deps.middleware import limiter
from src.analytics.mcp_usage import (
    build_mcp_usage_report,
    delete_actor_events,
    initialize_mcp_usage,
    record_event,
)


@pytest.fixture
def ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "mcp.db"
    monkeypatch.setenv("MCP_ANALYTICS_DB_PATH", str(path))
    assert initialize_mcp_usage()
    return path


def _event(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "kind": "tool",
        "name": "search_papers",
        "status": "started",
        "actor_id": "alice",
        "actor_role": "user",
        "invocation_id": str(uuid.uuid4()),
        "source": "adapter_report",
    }
    fields.update(overrides)
    return fields


def test_initialized_empty_is_measured_zero_and_missing_is_not_instrumented(ledger: Path, tmp_path: Path) -> None:
    empty = build_mcp_usage_report(ledger, days=7)
    assert empty["available"] is True
    assert empty["reason"] is None
    assert empty["measurement"]["started_at"]
    assert empty["measurement"]["last_event_at"] is None
    assert empty["totals"]["requests"] == 0
    assert empty["totals"]["request_error_rate"] is None
    assert len(empty["daily"]) == 7

    missing = build_mcp_usage_report(tmp_path / "missing.db", days=7)
    assert missing["available"] is False
    assert missing["reason"] == "not_instrumented"
    assert missing["totals"]["tool_calls"] == 0
    assert missing["daily"] == []

    conn = sqlite3.connect(ledger)
    try:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(mcp_usage_events)")
        }
    finally:
        conn.close()
    assert not {"payload", "arguments", "query", "exception", "error_message"} & columns


def test_actor_scoped_invocations_deduplicate_and_terminal_outcomes_are_stable(ledger: Path) -> None:
    invocation = str(uuid.uuid4())
    assert record_event(**_event(invocation_id=invocation))
    assert record_event(**_event(invocation_id=invocation, name="get_paper"))
    assert record_event(**_event(invocation_id=invocation, status="unknown"))
    assert record_event(**_event(invocation_id=invocation, status="succeeded", duration_ms=12))
    assert record_event(**_event(invocation_id=invocation, status="failed", duration_ms=99))
    assert record_event(**_event(invocation_id=invocation, status="started"))
    assert record_event(**_event(invocation_id=invocation, actor_id="bob", status="failed"))

    conn = sqlite3.connect(ledger)
    try:
        rows = conn.execute(
            "SELECT actor_id, name, status, duration_ms FROM mcp_usage_events ORDER BY actor_id"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [
        ("alice", "search_papers", "succeeded", 12.0),
        ("bob", "search_papers", "failed", None),
    ]

    report = build_mcp_usage_report(ledger, days=7)
    assert report["totals"]["tool_calls"] == 2
    assert report["totals"]["tool_successes"] == 1
    assert report["totals"]["tool_failures"] == 1
    assert report["tools"][0]["calls"] == 2


def test_job_start_cohorts_pending_expiry_orphans_and_kst_daily_sums(ledger: Path) -> None:
    now = dt.datetime(2026, 9, 6, 3, 0, tzinfo=dt.timezone.utc)
    assert record_event(**_event(kind="job", name="deep_review", status="started", invocation_id=None, job_id="fresh"))
    assert record_event(**_event(kind="job", name="deep_review", status="started", invocation_id=None, job_id="done"))
    assert record_event(**_event(kind="job", name="deep_review", status="succeeded", invocation_id=None, job_id="done", duration_ms=45))
    assert record_event(**_event(kind="job", name="poster", status="started", invocation_id=None, job_id="stale"))
    assert record_event(**_event(kind="job", name="poster", status="failed", invocation_id=None, job_id="orphan"))

    fresh_start = "2026-09-06T02:30:00.000Z"  # 2026-09-06 KST
    stale_start = "2026-09-04T01:00:00.000Z"
    conn = sqlite3.connect(ledger)
    try:
        conn.execute("UPDATE mcp_usage_events SET started_at=?, created_at=? WHERE job_id IN ('fresh','done')", (fresh_start, fresh_start))
        conn.execute("UPDATE mcp_usage_events SET started_at=?, created_at=? WHERE job_id='stale'", (stale_start, stale_start))
        conn.execute("UPDATE mcp_usage_events SET started_at=NULL, created_at=? WHERE job_id='orphan'", (fresh_start,))
        conn.commit()
    finally:
        conn.close()

    report = build_mcp_usage_report(ledger, days=7, now=now)
    assert report["totals"]["jobs_started"] == 3
    assert report["totals"]["jobs_completed"] == 1
    assert report["totals"]["jobs_failed"] == 0
    assert report["totals"]["jobs_pending"] == 1
    assert report["totals"]["job_p95_ms"] == 45.0
    assert sum(day["jobs_completed"] for day in report["daily"]) == 1
    deep_review = next(row for row in report["jobs"] if row["name"] == "deep_review")
    poster = next(row for row in report["jobs"] if row["name"] == "poster")
    assert deep_review == {"name": "deep_review", "started": 2, "completed": 1, "failed": 0, "pending": 1, "unknown": 0}
    assert poster["started"] == 1
    assert poster["pending"] == 0
    assert poster["unknown"] == 2  # one expired start plus one orphan terminal


def test_report_filters_internal_accounts_and_reports_invocation_coverage(ledger: Path) -> None:
    for actor, role, invocation in (
        ("alice", "user", str(uuid.uuid4())),
        ("admin", "admin", None),
    ):
        assert record_event(
            kind="request", name="POST /api/search", status="succeeded",
            actor_id=actor, actor_role=role, invocation_id=invocation,
            duration_ms=10, http_status=200, client_name="Claude Desktop",
            client_version="1.2.3", adapter_version="0.4.0", source="ua_claim",
        )
    external = build_mcp_usage_report(ledger, days=7)
    assert external["totals"]["requests"] == 1
    assert external["measurement"]["invocation_coverage"] == 1.0
    assert external["clients"] == [{"name": "Claude Desktop", "version": "1.2.3", "requests": 1, "tool_calls": 0}]

    all_actors = build_mcp_usage_report(ledger, days=7, include_internal=True)
    assert all_actors["totals"]["requests"] == 2
    assert all_actors["measurement"]["legacy_or_unattributed_requests"] == 1
    assert all_actors["measurement"]["invocation_coverage"] == 0.5

    assert record_event(
        kind="request", name="GET (unmatched)", status="failed",
        http_status=404, source="ua_claim",
    )


def test_adapter_client_categories_are_bounded_and_unknown_is_not_mislabeled(ledger: Path) -> None:
    labels = {
        "claude-code": "Claude Code",
        "claude-desktop": "Claude Desktop",
        "cursor": "Cursor",
        "codex": "Codex",
        "vscode": "VS Code",
        "other": "Other",
        "unknown": "Unknown",
    }
    for client_name in labels:
        assert record_event(
            kind="request", name="GET /api/papers/{paper_id}", status="succeeded",
            actor_id="alice", actor_role="user", client_name=client_name,
            source="ua_claim",
        )
    report = build_mcp_usage_report(ledger, days=7)
    observed = {row["name"] for row in report["clients"]}
    assert observed == set(labels.values())


def test_only_completed_meaningful_actions_activate_accounts(ledger: Path) -> None:
    non_activating_requests = (
        ("reader", "GET /api/papers/{paper_id}", "succeeded", 200),
        ("poller", "GET /api/deep-review/status/{session_id}", "succeeded", 200),
        ("failed", "POST /api/search", "failed", 422),
        ("unknown-route", "POST /api/anything", "succeeded", 200),
    )
    for actor, name, status, http_status in non_activating_requests:
        assert record_event(
            kind="request", name=name, status=status, http_status=http_status,
            actor_id=actor, actor_role="user", source="ua_claim",
        )
    assert record_event(**_event(actor_id="failed-tool", status="failed"))
    assert record_event(
        **_event(
            actor_id="read-tool", name="get_review_report", status="succeeded"
        )
    )
    assert record_event(
        **_event(
            kind="job", name="poster", status="failed", actor_id="orphan-job",
            invocation_id=None, job_id="orphan",
        )
    )
    report = build_mcp_usage_report(ledger, days=7)
    assert report["totals"]["active_accounts"] == 0

    assert record_event(
        **_event(actor_id="tool-user", name="search_papers", status="succeeded")
    )
    assert record_event(
        **_event(
            kind="job", name="figure", status="started", actor_id="job-user",
            invocation_id=None, job_id="figure-job",
        )
    )
    activated = build_mcp_usage_report(ledger, days=7)
    assert activated["totals"]["active_accounts"] == 2


def test_delete_actor_tombstone_blocks_in_flight_recreation(ledger: Path) -> None:
    assert record_event(**_event())
    assert delete_actor_events("alice") == 1
    assert record_event(**_event(status="failed"))
    conn = sqlite3.connect(ledger)
    try:
        assert conn.execute("SELECT COUNT(*) FROM mcp_usage_events WHERE actor_id='alice'").fetchone()[0] == 0
        tombstone = conn.execute("SELECT actor_hash FROM mcp_usage_actor_tombstones").fetchone()[0]
    finally:
        conn.close()
    assert "alice" not in tombstone


def test_deletion_before_ledger_exists_blocks_late_job_result(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "recovered.db"
    monkeypatch.setenv("MCP_ANALYTICS_DB_PATH", str(path))
    assert not path.exists()
    assert delete_actor_events("alice") == 0
    assert record_event(**_event(kind="job", name="deep_review", status="succeeded",
                                 job_id="late_result", source="server_observed"))
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mcp_usage_events").fetchone()[0] == 0


def test_deletion_path_override_and_storage_failure(tmp_path: Path, monkeypatch) -> None:
    from routers.deps.user_deletion import _resolve_paths
    from src.analytics import mcp_usage
    selected = tmp_path / "selected.db"
    assert _resolve_paths({"mcp_analytics_db": selected})["mcp_analytics_db"] == selected
    monkeypatch.setattr(mcp_usage, "initialize_mcp_usage", lambda _path: False)
    with pytest.raises(RuntimeError, match="deletion storage unavailable"):
        delete_actor_events("alice", selected)


@pytest.mark.asyncio
async def test_telemetry_endpoint_auth_validation_and_actor_derivation(
    ledger: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import routers.mcp_telemetry as telemetry

    app = FastAPI()
    app.state.limiter = limiter
    limiter.enabled = False
    app.include_router(telemetry.router)
    app.dependency_overrides[get_current_user] = lambda: "derived-user"
    monkeypatch.setattr(telemetry, "_get_user_db", lambda: type("DB", (), {"get": lambda self, key: {"role": "user"}})())
    transport = ASGITransport(app=app)
    payload = {
        "invocation_id": str(uuid.uuid4()), "tool_name": "search_papers",
        "status": "failed", "duration_ms": 3, "client_name": "Codex",
        "client_version": "1.2.0", "adapter_version": "0.4.0",
    }
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/mcp/telemetry", json=payload)
            assert response.status_code == 202
            assert response.json() == {"accepted": True}
            assert (await client.post("/api/mcp/telemetry", json={**payload, "actor_id": "spoof"})).status_code == 422
            assert (await client.post("/api/mcp/telemetry", json={**payload, "tool_name": "not_a_tool"})).status_code == 422
            assert (await client.post("/api/mcp/telemetry", json={**payload, "duration_ms": "NaN"})).status_code == 422
    finally:
        limiter.enabled = True

    conn = sqlite3.connect(ledger)
    try:
        actor = conn.execute("SELECT actor_id FROM mcp_usage_events").fetchone()[0]
    finally:
        conn.close()
    assert actor == "derived-user"


@pytest.mark.asyncio
async def test_admin_endpoint_keeps_unavailable_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import routers.admin_analytics as admin_analytics

    missing = tmp_path / "absent.db"
    monkeypatch.setattr(admin_analytics, "mcp_analytics_db_path", lambda: missing)
    app = FastAPI()
    app.include_router(admin_analytics.router)
    app.dependency_overrides[get_admin_user] = lambda: "admin"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/admin/analytics/mcp?days=7")
        assert response.status_code == 200
        body = response.json()
        assert body["available"] is False
        assert body["reason"] == "not_instrumented"
        assert set(body) == {"available", "reason", "window", "measurement", "totals", "daily", "tools", "routes", "clients", "versions", "jobs", "errors"}
        assert (await client.get("/api/admin/analytics/mcp?days=8")).status_code == 400


@pytest.mark.asyncio
async def test_admin_mcp_report_does_not_block_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import routers.admin_analytics as admin_analytics

    entered = threading.Event()
    release = threading.Event()

    def slow_report(*args: object, **kwargs: object) -> dict:
        entered.set()
        assert release.wait(2)
        return {"available": True}

    monkeypatch.setattr(admin_analytics, "build_mcp_usage_report", slow_report)
    monkeypatch.setattr(admin_analytics, "mcp_analytics_db_path", lambda: tmp_path / "db")
    app = FastAPI()
    app.include_router(admin_analytics.router)
    app.dependency_overrides[get_admin_user] = lambda: "admin"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        request_task = asyncio.create_task(
            client.get("/api/admin/analytics/mcp?days=7")
        )
        assert await asyncio.to_thread(entered.wait, 1)
        await asyncio.sleep(0)
        assert not request_task.done()
        release.set()
        response = await request_task
    assert response.status_code == 200
    assert response.json() == {"available": True}
