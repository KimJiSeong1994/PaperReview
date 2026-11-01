"""Personal soul: SoulDB, /api/me/soul routes, memory extraction and the prompt memory block."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.assistant import turn_runner
from routers import soul as soul_router
from routers.deps import storage
from routers.deps.auth import AuthenticatedPrincipal, get_authenticated_principal
from src.storage.soul_db import MAX_MEMORIES, SoulDB, render_markdown

ALICE = AuthenticatedPrincipal("alice", "inc-a")


def test_crud_dedupe_ownership_and_markdown(tmp_path):
    db = SoulDB(tmp_path / "s.db")
    assert db.get_soul("alice", "inc-a") == {"user_md": "", "memories": []}
    assert db.set_user_md("alice", "inc-a", "x" * 3000) == "x" * 2000
    db.set_user_md("alice", "inc-a", "대학원생, GraphRAG 연구")

    items = [{"kind": "topic", "text": "GraphRAG  메모리"}, {"kind": "topic", "text": "graphrag 메모리"},
             {"kind": "bogus", "text": "x"}, {"kind": "fact", "text": "  "}, {"kind": "preference", "text": "짧게 답해 주세요"}]
    assert db.add_memories("alice", "inc-a", items, "c1") == 2  # duplicate, bad kind and empty dropped
    soul = db.get_soul("alice", "inc-a")
    assert soul["user_md"] == "대학원생, GraphRAG 연구" and len(soul["memories"]) == 2
    assert soul["memories"][0]["text"] == "짧게 답해 주세요"  # most recently used first
    assert soul["memories"][1]["source_conversation_id"] == "c1"

    assert db.get_soul("alice", "inc-b") == {"user_md": "", "memories": []}  # re-registered account
    mem_id = soul["memories"][0]["id"]
    assert db.delete_memory(mem_id, "alice", "inc-b") is False
    assert db.delete_memory(mem_id, "alice", "inc-a") is True

    md = render_markdown(db.get_soul("alice", "inc-a"))
    assert md == "# USER.md\n\n대학원생, GraphRAG 연구\n\n# MEMORY.md\n\n- [관심 주제] GraphRAG 메모리"
    assert render_markdown({"user_md": "", "memories": []}) == "# USER.md\n\n(비어 있음)\n\n# MEMORY.md\n\n(비어 있음)"

    db.add_memories("alice", "inc-b", [{"kind": "fact", "text": "다른 계정"}], None)
    assert db.clear("alice", "inc-a") == 1 and db.get_soul("alice", "inc-a")["user_md"] == ""
    assert db.delete_by_username("alice") == 1


def test_cap_evicts_least_recently_used(tmp_path):
    db = SoulDB(tmp_path / "s.db")
    db.add_memories("alice", "inc-a", [{"kind": "topic", "text": f"t{i}"} for i in range(MAX_MEMORIES)], None)
    oldest = next(m for m in db.get_soul("alice", "inc-a")["memories"] if m["text"] == "t0")
    db.touch_memories([oldest["id"]])  # t0 is used again, so t1 becomes the oldest
    db.add_memories("alice", "inc-a", [{"kind": "topic", "text": "new"}], None)
    texts = {m["text"] for m in db.get_soul("alice", "inc-a")["memories"]}
    assert len(texts) == MAX_MEMORIES and "new" in texts and "t0" in texts and "t1" not in texts


@pytest.fixture
def souls(tmp_path, monkeypatch):
    db = SoulDB(tmp_path / "souls.db")
    monkeypatch.setattr(storage, "_get_soul_db", lambda: db)
    monkeypatch.setattr(soul_router, "_get_soul_db", lambda: db)
    return db


def test_routes_auth_ownership_and_clear(souls):
    app = FastAPI()
    app.include_router(soul_router.router)
    app.dependency_overrides[get_authenticated_principal] = lambda: ALICE
    client, anonymous = TestClient(app), TestClient(FastAPI())
    anonymous.app.include_router(soul_router.router)

    for method in ("get", "put", "delete"):
        assert getattr(anonymous, method)("/api/me/soul", **({"json": {"user_md": ""}} if method == "put" else {})).status_code == 401
    assert client.put("/api/me/soul", json={"user_md": "x" * 2001}).status_code == 422
    assert client.put("/api/me/soul", json={"user_md": "박사과정"}).json() == {"user_md": "박사과정"}

    souls.add_memories("alice", "inc-a", [{"kind": "topic", "text": "GraphRAG"}], "c1")
    souls.add_memories("bob", "inc-b", [{"kind": "topic", "text": "남의 메모리"}], None)
    body = client.get("/api/me/soul").json()
    assert body["user_md"] == "박사과정" and [m["text"] for m in body["memories"]] == ["GraphRAG"]
    assert set(body["memories"][0]) == {"id", "kind", "text", "created_at"}
    assert body["markdown"].startswith("# USER.md\n\n박사과정")

    bob_id = souls.get_soul("bob", "inc-b")["memories"][0]["id"]
    assert client.delete(f"/api/me/soul/memories/{bob_id}").status_code == 404
    assert client.delete(f"/api/me/soul/memories/{body['memories'][0]['id']}").json() == {"ok": True}
    souls.add_memories("alice", "inc-a", [{"kind": "fact", "text": "마감 12월"}], None)
    assert client.delete("/api/me/soul").json() == {"deleted": 1}
    assert client.get("/api/me/soul").json()["memories"] == [] and souls.get_soul("bob", "inc-b")["memories"]


def _llm_reply(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=None)


def test_remember_turn_deterministic_and_llm_items(souls, monkeypatch):
    monkeypatch.setattr(turn_runner, "get_openai_client", lambda: None)
    replies = []
    monkeypatch.setattr(turn_runner, "create_chat_completion", lambda client, **kw: replies.pop(0))

    replies.append(_llm_reply(json.dumps({"items": [
        {"kind": "preference", "text": "답변은 짧게"}, {"kind": "fact", "text": "12월 학회 마감"},
        {"kind": "topic", "text": "LLM 이 고른 주제는 무시"}, {"kind": "fact", "text": "넷째"}, {"kind": "fact", "text": "다섯째"},
    ]})))
    search_blocks = [{"type": "search_results", "query": "장기 대화 기억 에이전트 메모리"}, {"type": "graph"}]
    added = asyncio.run(turn_runner.remember_turn(ALICE, "c1", "짧게 답해줘, 12월 마감이야", "…", search_blocks))
    assert added == 4  # topic + preference + 2 facts (3 LLM items max, wrong kind dropped)
    texts = {m["text"] for m in souls.get_soul("alice", "inc-a")["memories"]}
    assert {"장기 대화 기억 에이전트 메모리", "답변은 짧게", "12월 학회 마감", "넷째"} == texts

    replies.append(_llm_reply("not json"))
    review = [{"type": "review_started", "paper_title": "APEX-MEM", "session_id": "s", "paper_index": 2}]
    assert asyncio.run(turn_runner.remember_turn(ALICE, "c1", "2번 논문 심층 리뷰 해줘", "…", review)) == 1
    assert "심층 리뷰: APEX-MEM" in {m["text"] for m in souls.get_soul("alice", "inc-a")["memories"]}

    # A bare reply makes no extraction call at all (replies is empty, pop would raise).
    assert asyncio.run(turn_runner.remember_turn(ALICE, "c1", "응", "…", [])) == 0


def test_parse_extracted_rejects_malformed():
    assert turn_runner.parse_extracted("") == []
    assert turn_runner.parse_extracted('{"items": "x"}') == []
    assert turn_runner.parse_extracted('[{"kind": "fact"}]') == []
    assert turn_runner.parse_extracted('{"items": [{"kind": "fact", "text": 3}]}') == []


def test_memory_block_picks_related_and_recent_and_touches(souls):
    assert turn_runner.build_memory_block(ALICE, "아무거나") == ""
    souls.set_user_md("alice", "inc-a", "박사과정")
    souls.add_memories("alice", "inc-a", [{"kind": "paper", "text": "심층 리뷰: HiGMem"}], None)
    souls.add_memories("alice", "inc-a", [{"kind": "topic", "text": f"주제{i}"} for i in range(20)], None)
    block = turn_runner.build_memory_block(ALICE, "higmem 이랑 비교해줘")
    lines = [ln for ln in block.splitlines() if ln.startswith("- [")]
    assert block.startswith("# USER.md\n\n박사과정") and len(lines) == 12
    assert "- [논문] 심층 리뷰: HiGMem" in lines  # old but related to the message
    assert souls.get_soul("alice", "inc-a")["memories"][0]["text"] in {ln.split("] ", 1)[1] for ln in lines}


def test_extraction_drops_restated_requests_and_topic_preferences(souls, monkeypatch):
    raw = json.dumps({"items": [
        {"kind": "preference", "text": "그래프 기반 추천 논문을 보고 싶어 한다."},
        {"kind": "preference", "text": "앞으로 답은 아주 짧게"},
        {"kind": "fact", "text": "추천시스템을 연구하는 석사생"},
    ]})
    assert turn_runner.parse_extracted(raw, "그래프 기반 추천") == [
        {"kind": "preference", "text": "앞으로 답은 아주 짧게"},
        {"kind": "fact", "text": "추천시스템을 연구하는 석사생"},
    ]
    # Topic containment alone also drops a preference, even without a request verb.
    assert turn_runner.parse_extracted('{"items": [{"kind": "preference", "text": "그래프 기반 추천 위주로"}]}',
                                       "그래프 기반 추천") == []

    monkeypatch.setattr(turn_runner, "get_openai_client", lambda: None)
    monkeypatch.setattr(turn_runner, "create_chat_completion", lambda client, **kw: _llm_reply(raw))
    blocks = [{"type": "search_results", "query": "그래프 기반 추천"}]
    asyncio.run(turn_runner.remember_turn(ALICE, "c1", "그래프 기반 추천 논문 보고 싶어", "…", blocks))
    texts = [m["text"] for m in souls.get_soul("alice", "inc-a")["memories"]]
    assert sorted(texts) == sorted(["그래프 기반 추천", "앞으로 답은 아주 짧게", "추천시스템을 연구하는 석사생"])
