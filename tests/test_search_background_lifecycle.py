"""Event-driven ownership tests: await expiry never releases running work."""
import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from routers import search as rs


def wait_until(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return True
        threading.Event().wait(.002)
    return predicate()


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setattr(rs, "_router_operation_owner", rs.SearchAgent.__new__(rs.SearchAgent))
    monkeypatch.setattr(rs, "_router_shutdown", threading.Event())
    monkeypatch.setattr(rs, "_background_generation", None)
    monkeypatch.setattr(rs, "_cleanup_expired_cache", lambda: None)
    monkeypatch.setattr(rs, "_log_cache_file_count", lambda: None)
    yield rs._router_operation_owner
    rs.stop_search_background_workers(.1)


def active(owner, name):
    lock, operations = owner._operation_generation_state()
    with lock:
        return len(operations.get(name, ()))


def test_returned_save_failure_skips_optional_work(owner, monkeypatch, caplog):
    agent = SimpleNamespace(
        save_papers=MagicMock(return_value={"success": False, "new_papers": 1, "error": "disk failed"}),
        collect_references=MagicMock(), extract_full_texts=MagicMock(),
    )
    monkeypatch.setattr(rs, "search_agent", agent)
    rs._enrich_papers_background("q", {"arxiv": [{"title": "P"}]}, True, True, 10)
    agent.collect_references.assert_not_called()
    agent.extract_full_texts.assert_not_called()
    assert "Persistence failed" in caplog.text


def test_shutdown_accounts_for_source_owner(owner, monkeypatch):
    source_owner = rs.SearchAgent.__new__(rs.SearchAgent)
    monkeypatch.setattr(rs, "search_agent", source_owner)
    release, entered = threading.Event(), threading.Event()
    generation = source_owner._begin_operation_generation("search_with_filters")
    def block():
        entered.set()
        release.wait(2)
    generation.submit(block)
    try:
        assert entered.wait(1)
        assert not rs.stop_search_background_workers(0)
        assert not rs.start_search_background_workers()
        assert active(source_owner, "search_with_filters") == 1
    finally:
        release.set()
        generation.close()
    assert wait_until(lambda: active(source_owner, "search_with_filters") == 0)
    assert rs.start_search_background_workers()


def test_admitted_save_persists_but_disconnect_skips_optional(owner, monkeypatch):
    disconnected = threading.Event()
    def save(*args, **kwargs):
        disconnected.set()
        return {"success": True, "new_papers": 1}
    refs, texts = MagicMock(), MagicMock()
    monkeypatch.setattr(rs, "search_agent", SimpleNamespace(save_papers=save, collect_references=refs, extract_full_texts=texts))
    rs._enrich_papers_background("q", {"arxiv": [{"title": "P"}]}, True, True, 10, disconnect_event=disconnected)
    refs.assert_not_called()
    texts.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("lane", ["search_analysis", "search_rank", "search_graph"])
async def test_expired_await_keeps_two_underlying_slots(owner, lane):
    release = threading.Event()
    entered = [threading.Event(), threading.Event()]
    def block(index):
        entered[index].set()
        release.wait(2)
    try:
        for index in range(2):
            with pytest.raises(asyncio.TimeoutError):
                await rs._run_owned(lane, lambda i=index: block(i), .02)
            assert entered[index].is_set()
        assert active(owner, lane) == 2
        with pytest.raises(rs.SearchCapacityExceeded):
            await rs._run_owned(lane, lambda: None, 1)
    finally:
        release.set()
    assert wait_until(lambda: active(owner, lane) == 0)
    assert await rs._run_owned(lane, lambda: "recovered", 1) == "recovered"


def test_save_lane_saturation_private_snapshot_and_recovery(owner, monkeypatch):
    release = threading.Event()
    entered = threading.Barrier(3)
    records = []
    def save(results, query, **kwargs):
        records.append(results)
        entered.wait(timeout=2)
        release.wait(2)
        return {"new_papers": 1}
    agent = SimpleNamespace(save_papers=save, collect_references=MagicMock(), extract_full_texts=MagicMock())
    monkeypatch.setattr(rs, "search_agent", agent)
    results = {"arxiv": [{"title": "Original"}]}
    try:
        assert rs._admit_save("q", results, fast_mode=True) == "accepted"
        assert rs._admit_save("q", results, fast_mode=True) == "accepted"
        entered.wait(timeout=2)
        results["arxiv"][0]["title"] = "Changed"
        assert all(record["arxiv"][0]["title"] == "Original" for record in records)
        assert rs._admit_save("q", results) == "not_admitted_capacity"
        assert active(owner, "search_save_enrichment") == 2
    finally:
        release.set()
    assert wait_until(lambda: active(owner, "search_save_enrichment") == 0)


@pytest.mark.parametrize("fast,expired,shutdown,failed", [(True, False, False, False), (False, True, False, False), (False, False, True, False), (False, False, False, True)])
def test_optional_stages_forbidden_after_capability_or_stop(owner, monkeypatch, fast, expired, shutdown, failed):
    def save(*args, **kwargs):
        assert kwargs == {"generate_embeddings": False, "update_graph": False}
        if shutdown:
            rs._router_shutdown.set()
        if expired:
            clock[0] = 31
        if failed:
            raise RuntimeError("save failed")
        return {"new_papers": 1}
    clock = [0]
    monkeypatch.setattr(rs.time, "monotonic", lambda: clock[0])
    agent = SimpleNamespace(save_papers=save, collect_references=MagicMock(), extract_full_texts=MagicMock(), similarity_calculator=MagicMock())
    monkeypatch.setattr(rs, "search_agent", agent)
    rs._enrich_papers_background("q", {"arxiv": [{"title": "Paper"}]}, True, True, 10, fast_mode=fast, deadline=30)
    agent.collect_references.assert_not_called()
    agent.extract_full_texts.assert_not_called()
    agent.similarity_calculator.get_embeddings_batch.assert_not_called()


def test_shutdown_retains_save_ownership_and_prevents_restart(owner, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    refs = MagicMock()
    def save(*args, **kwargs):
        entered.set()
        release.wait(2)
        return {"new_papers": 1}
    monkeypatch.setattr(rs, "search_agent", SimpleNamespace(save_papers=save, collect_references=refs))
    try:
        assert rs._admit_save("q", {"arxiv": [{"title": "P"}]}, True) == "accepted"
        assert entered.wait(1)
        assert rs.stop_search_background_workers(0) is False
        assert rs.start_search_background_workers() is False
        assert rs._admit_save("q", {"arxiv": [{}]}) == "not_admitted_shutdown"
        assert active(owner, "search_save_enrichment") == 1
    finally:
        release.set()
    assert wait_until(lambda: active(owner, "search_save_enrichment") == 0)
    refs.assert_not_called()
    assert rs.start_search_background_workers()
    assert rs.stop_search_background_workers(1)


def test_maintenance_only_lifecycle(owner):
    assert rs.start_search_background_workers()
    generation = rs._background_generation
    assert len(generation.threads) == 1
    assert generation.threads[0].name == "cache-maintenance"
    assert not rs.start_search_background_workers()
    assert rs.stop_search_background_workers(1)
    assert rs.start_search_background_workers()
    assert rs._background_generation.stop_event is not generation.stop_event
    assert rs.stop_search_background_workers(1)
    assert all(route.path != "/api/prefetch-popular" for route in rs.router.routes)
