"""MCP request isolation and real business lifecycle boundaries, without LLMs."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import threading
from uuid import uuid4

import jwt
import pytest
from fastapi import BackgroundTasks, Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from routers.deps import auth
from src.analytics import mcp_usage
from src.analytics.mcp_context import (
    McpUsageMiddleware,
    capture_context,
    drain_measurements,
    record_job_started,
)


@pytest.fixture
def events(monkeypatch):
    rows = []

    def record(**fields):
        rows.append(dict(fields))
        return True

    async def record_async(**fields):
        return record(**fields)

    monkeypatch.setattr(mcp_usage, "record_event", record)
    monkeypatch.setattr(mcp_usage, "record_event_async", record_async)
    return rows


@pytest.fixture
def headers(monkeypatch):
    from routers.deps import storage
    monkeypatch.setattr(auth, "_JWT_SECRET", "mcp-isolation-test-secret-that-is-long")
    monkeypatch.setattr(storage, "_get_user_db", lambda: SimpleNamespace(get=lambda name: {"role": "user"}))

    def make(name="alice", mcp=True):
        token = jwt.encode({"sub": name, "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                           auth._JWT_SECRET, algorithm="HS256")
        value = {"Authorization": f"Bearer {token}"}
        if mcp:
            value.update({"User-Agent": "jiphyeonjeon-mcp/0.1.6",
                          "X-Jiphyeonjeon-Invocation-Id": str(uuid4())})
        return value

    return make


@pytest.mark.asyncio
async def test_concurrent_actors_are_isolated_and_paths_are_normalized(events, headers):
    app = FastAPI()
    app.add_middleware(McpUsageMiddleware)
    both = asyncio.Event()
    arrivals = []

    @app.get("/api/action/{private_id}")
    async def action(private_id: str, actor=Depends(auth.get_current_user)):
        arrivals.append(actor)
        if len(arrivals) == 2:
            both.set()
        await both.wait()
        assert capture_context()["actor_id"] == actor
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(
            client.get("/api/action/private-alice?token=never-store", headers=headers("alice")),
            client.get("/api/action/private-bob?query=never-store", headers=headers("bob")),
        )
    assert [response.status_code for response in responses] == [200, 200]
    await drain_measurements()
    assert {row["actor_id"] for row in events} == {"alice", "bob"}
    assert {row["name"] for row in events} == {"GET /api/action/{private_id}"}
    assert len({row["invocation_id"] for row in events}) == 2
    assert "never-store" not in str(events)
    assert capture_context() is None


@pytest.mark.asyncio
async def test_request_boundary_captured_before_background_work_and_probes_excluded(events, headers, monkeypatch):
    from src.analytics import mcp_context
    clock = [0.0]
    monkeypatch.setattr(mcp_context.time, "perf_counter", lambda: clock[0])
    app = FastAPI()
    app.add_middleware(McpUsageMiddleware)

    async def background():
        clock[0] = 100.0

    @app.get("/api/action")
    async def action(tasks: BackgroundTasks, actor=Depends(auth.get_current_user)):
        tasks.add_task(background)
        return {"ok": True}

    @app.get("/api/version")
    async def version():
        return {"version": "1"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/action", headers=headers())).status_code == 200
        assert (await client.get("/api/version", headers=headers())).status_code == 200
        assert (await client.get("/api/version", headers=headers(mcp=False))).status_code == 200
    await drain_measurements()
    assert len(events) == 1
    assert events[0]["duration_ms"] == 0


@pytest.mark.asyncio
async def test_invalid_mcp_token_cannot_silently_start_anonymous_work(events):
    app = FastAPI()
    app.add_middleware(McpUsageMiddleware)
    started = []

    @app.post("/api/deep-review")
    async def start(actor=Depends(auth.get_optional_user)):
        started.append(actor)
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/deep-review", headers={
            "User-Agent": "jiphyeonjeon-mcp/0.1.6", "Authorization": "Bearer invalid",
        })
        assert response.status_code == 401
        assert not started
        # Existing browser optional-auth semantics remain intact.
        assert (await client.post("/api/deep-review")).status_code == 200
    await drain_measurements()
    assert started == [None]
    assert len(events) == 1 and events[0]["http_status"] == 401
    assert events[0].get("actor_id") is None


@pytest.mark.asyncio
async def test_poster_terminal_survives_http_timeout(events, headers, monkeypatch):
    from app.DeepAgent.poster import service as poster_service
    from app.DeepAgent.poster.result_contract import PosterServiceError

    monkeypatch.setattr(poster_service, "_poster_semaphore", asyncio.Semaphore(1))
    monkeypatch.setattr(poster_service, "_active_jobs", {})
    finished = threading.Event()
    app = FastAPI()
    app.add_middleware(McpUsageMiddleware)

    class Agent:
        def generate_poster(self, **kwargs):
            assert finished.wait(3)
            return {"success": True, "poster_html": "<p>Generated result</p>"}

    @app.post("/api/deep-review/visualize-direct")
    async def generate(actor=Depends(auth.get_current_user)):
        try:
            await poster_service.PosterApplicationService().generate(
                report_content="test", num_papers=1, agent_factory=Agent,
                timeout_seconds=0.01,
            )
        except PosterServiceError as error:
            assert error.status_code == 504
            return {"timed_out": True}

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/deep-review/visualize-direct", headers=headers())
        assert response.json() == {"timed_out": True}
        assert [r["status"] for r in events if r["kind"] == "job"] == ["started"]
    finally:
        finished.set()
    for _ in range(100):
        if any(r["kind"] == "job" and r["status"] == "succeeded" for r in events):
            break
        await asyncio.sleep(0.01)
    jobs = [r for r in events if r["kind"] == "job"]
    assert [r["status"] for r in jobs] == ["started", "succeeded"]
    assert jobs[0]["job_id"] == jobs[1]["job_id"]
    assert all(r["actor_id"] == "alice" and r["source"] == "server_observed" for r in jobs)


@pytest.mark.asyncio
async def test_review_failure_is_recorded_by_worker(events, headers, monkeypatch, tmp_path):
    from routers import reviews
    monkeypatch.setattr(reviews, "run_fast_review", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("private failure")))
    app = FastAPI()
    app.add_middleware(McpUsageMiddleware)

    @app.post("/api/review-test")
    async def start(tasks: BackgroundTasks, actor=Depends(auth.get_current_user)):
        sid = "review_mcp_lifecycle_test"
        reviews.review_sessions[sid] = {"status": "processing", "username": actor}
        measurement = await record_job_started("deep_review", sid)
        tasks.add_task(reviews.run_deep_review_background, sid, [], None, 1, "test",
                       SimpleNamespace(session_path=tmp_path), True, measurement)
        return {"accepted": True}

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.post("/api/review-test", headers=headers())).status_code == 200
        jobs = [r for r in events if r["kind"] == "job"]
        assert [r["status"] for r in jobs] == ["started", "failed"]
        assert jobs[1]["actor_id"] == "alice"
        assert "private failure" not in str(events)
    finally:
        await drain_measurements()
        reviews.review_sessions.pop("review_mcp_lifecycle_test", None)


@pytest.mark.asyncio
@pytest.mark.parametrize("result_kind,expected", [("success", "succeeded"), ("failure", "failed"), ("disconnect", "unknown")])
@pytest.mark.parametrize("collector_outage", [False, True])
async def test_actual_mcp_figure_endpoint_records_outcomes(events, headers, monkeypatch, result_kind, expected, collector_outage):
    from routers import autofigure

    async def generate(*args, **kwargs):
        if result_kind == "disconnect":
            raise TimeoutError("private remote timeout")
        return SimpleNamespace(success=result_kind == "success", final_svg="<svg></svg>",
                               figure_png_b64="", error="private failure")

    monkeypatch.setattr(autofigure, "_autofigure_available", True)
    monkeypatch.setattr(autofigure, "get_autofigure_client", lambda: SimpleNamespace(method_to_svg=generate))
    if collector_outage:
        async def broken_writer(**fields):
            raise RuntimeError("executor unavailable")
        monkeypatch.setattr(mcp_usage, "record_event_async", broken_writer)
    app = FastAPI()
    app.add_middleware(McpUsageMiddleware)
    app.include_router(autofigure.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/autofigure/method-to-svg", headers=headers(),
                                     json={"method_text": "private method body"})
    assert response.status_code == (503 if result_kind == "disconnect" else 200)
    await drain_measurements()
    jobs = [r for r in events if r["kind"] == "job"]
    if collector_outage:
        assert jobs == []
        return
    assert [r["status"] for r in jobs] == ["started", expected]
    assert all(r["name"] == "figure" and r["actor_id"] == "alice" for r in jobs)
    assert "private" not in str(events)


@pytest.mark.asyncio
@pytest.mark.parametrize("writer_error", [RuntimeError, asyncio.CancelledError])
async def test_broken_collector_never_prevents_background_or_poster_work(headers, monkeypatch, writer_error):
    from app.DeepAgent.poster import service as poster_service

    async def broken_writer(**fields):
        raise writer_error()

    def broken_sync_writer(**fields):
        raise writer_error()

    monkeypatch.setattr(mcp_usage, "record_event_async", broken_writer)
    monkeypatch.setattr(mcp_usage, "record_event", broken_sync_writer)
    monkeypatch.setattr(poster_service, "_poster_semaphore", asyncio.Semaphore(1))
    monkeypatch.setattr(poster_service, "_active_jobs", {})
    app = FastAPI()
    app.add_middleware(McpUsageMiddleware)
    executed = []

    class Agent:
        def generate_poster(self, **kwargs):
            executed.append("poster")
            return {"success": True, "poster_html": "<p>Result</p>"}

    async def background():
        executed.append("background")

    @app.post("/api/test")
    async def run(tasks: BackgroundTasks, actor=Depends(auth.get_current_user)):
        await record_job_started("deep_review", "test_job")
        result = await poster_service.PosterApplicationService().generate(
            report_content="test", num_papers=1, agent_factory=Agent,
        )
        tasks.add_task(background)
        return {"success": result["success"]}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/test", headers=headers())
    await drain_measurements()
    assert response.status_code == 200 and response.json()["success"] is True
    assert executed == ["poster", "background"]
