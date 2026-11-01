"""Conversation endpoints and the SSE turn stream (search/graph/LLM monkeypatched)."""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.assistant import turn_runner
from routers import conversations
from routers.deps.auth import AuthenticatedPrincipal, get_authenticated_principal
from routers.deps.middleware import limiter
from src.storage.conversation_db import ConversationDB

PAPERS = {
    "arxiv": [
        {"result_key": "k1", "doc_id": "d1", "_rank": 2, "source": "arxiv", "title": "B", "year": 2021},
        {"result_key": "k0", "doc_id": "d0", "_rank": 1, "source": "arxiv", "title": "A", "year": 2020},
    ],
    "openalex": [{"result_key": "k1", "doc_id": "d1x", "_rank": 3, "source": "openalex", "title": "B"}],
}


def _search_response(results=PAPERS, is_academic=True):
    return SimpleNamespace(
        results=results,
        query_analysis={"is_academic": is_academic},
        metadata={"executed_query": "exec q", "partial": False},
        degraded=None,
        query_hash="qh1",
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = ConversationDB(tmp_path / "conversations.db")
    monkeypatch.setattr(conversations, "_get_conversation_db", lambda: db)
    limiter.reset()

    calls = {"search": [], "llm": [], "years": [], "route_inputs": []}

    async def fake_search(query, username, year_start=None, year_end=None):
        calls["search"].append((query, username))
        calls["years"].append((year_start, year_end))
        if calls.get("search_error"):
            raise RuntimeError("provider down")
        return calls.get("search_response") or _search_response()

    async def fake_graph(papers):
        return {"nodes": [{"id": p["result_key"]} for p in papers], "edges": [], "meta": {}}

    async def fake_llm(messages, emit):
        calls["llm"].append(messages)
        if calls.get("llm_error"):
            raise RuntimeError("boom")
        for piece in ("요약 ", "[1]"):
            emit({"delta": piece})
        return "요약 [1]"

    monkeypatch.setattr(turn_runner, "run_search", fake_search)
    monkeypatch.setattr(turn_runner, "build_graph", fake_graph)
    monkeypatch.setattr(turn_runner, "stream_llm", fake_llm)

    def fake_route(client, **kwargs):  # the only non-streaming LLM call left unfaked
        calls["route_inputs"].append(kwargs["messages"])
        if calls.get("route") is None:
            raise RuntimeError("router down")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=calls["route"]))], usage=None)

    monkeypatch.setattr(turn_runner, "create_chat_completion", fake_route)
    monkeypatch.setattr(turn_runner, "get_openai_client", lambda: None)

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(conversations.router)
    app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal("alice", "inc-a")
    other = FastAPI()
    other.state.limiter = limiter
    other.include_router(conversations.router)
    other.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal("bob", "inc-b")
    anonymous = FastAPI()
    anonymous.include_router(conversations.router)
    return SimpleNamespace(
        client=TestClient(app), other=TestClient(other), anonymous=TestClient(anonymous), db=db, calls=calls
    )


def _events(client, conv_id, message=None):
    body = {} if message is None else {"message": message}
    with client.stream("POST", f"/api/conversations/{conv_id}/turns", json=body) as resp:
        assert resp.status_code == 200
        return [json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data: ")]


def _kinds(events):
    return [next(iter(e)) if "block" not in e else f"block:{e['block']['type']}" for e in events]


def test_create_list_get_and_ownership(env):
    created = env.client.post("/api/conversations", json={"message": "  그래프 신경망 " + "x" * 80})
    assert created.status_code == 201
    body = created.json()
    assert len(body["title"]) <= 60 and body["title"].startswith("그래프 신경망")
    listed = env.client.get("/api/me/conversations").json()
    assert [c["id"] for c in listed] == [body["id"]] and listed[0]["turn_count"] == 1
    conv = env.client.get(f"/api/conversations/{body['id']}").json()
    assert conv["turns"][0]["id"] == body["turn_id"] and conv["turns"][0]["role"] == "user"
    assert set(conv["turns"][0]) == {"id", "seq", "role", "content", "blocks", "intent", "status", "created_at"}

    assert env.other.get(f"/api/conversations/{body['id']}").status_code == 404
    assert env.other.post(f"/api/conversations/{body['id']}/turns", json={}).status_code == 404
    assert env.other.post(f"/api/conversations/{body['id']}/archive").status_code == 404
    assert env.anonymous.get("/api/me/conversations").status_code == 401
    assert env.anonymous.post("/api/conversations", json={"message": "q"}).status_code == 401
    assert env.client.post("/api/conversations", json={"message": ""}).status_code == 422

    assert env.client.post(f"/api/conversations/{body['id']}/archive").json() == {"ok": True}
    assert env.client.get("/api/me/conversations").json() == []


def test_search_turn_stream_order_and_persistence(env):
    conv_id = env.client.post("/api/conversations", json={"message": "트랜스포머"}).json()["id"]
    events = _events(env.client, conv_id)
    kinds = _kinds(events)
    # Router is down → plain search of the raw message with the deterministic lead.
    lead = "'트랜스포머'(으)로 찾아볼게요.\n\n"
    assert kinds[:2] == ["delta", "status"] and events[0]["delta"] == lead and kinds[-1] == "done"
    assert kinds.index("block:search_results") < kinds.index("block:graph") < kinds.index("delta", 1)
    assert {e["stage"] for e in events if "status" in e} == {"search", "graph", "answer"}

    block = events[kinds.index("block:search_results")]["block"]
    assert [p["result_key"] for p in block["papers"]] == ["k0", "k1"]  # rank-sorted, de-duplicated
    assert block["total"] == 2 and block["executed_query"] == "exec q" and block["query_hash"] == "qh1"
    assert env.calls["search"] == [("트랜스포머", "alice")]

    turn = env.client.get(f"/api/conversations/{conv_id}").json()["turns"][-1]
    assert events[-1]["done"]["turn_id"] == turn["id"] and events[-1]["done"]["intent"] == "search"
    assert turn["content"] == lead + "요약 [1]" and turn["status"] == "done"
    assert events[-1]["done"]["title"] is None
    assert [b["type"] for b in turn["blocks"]] == ["search_results", "graph"]

    # The message is answered: running again without a new message is rejected.
    assert env.client.post(f"/api/conversations/{conv_id}/turns", json={}).status_code == 400


def test_non_academic_and_empty_results_reply_conversationally(env):
    env.calls["search_response"] = _search_response(is_academic=False)
    conv_id = env.client.post("/api/conversations", json={"message": "오늘 날씨"}).json()["id"]
    events = _events(env.client, conv_id)
    assert _kinds(events)[-2:] == ["delta", "done"] and not any("block" in e for e in events)
    note = env.calls["llm"][-1][-1]["content"]
    assert env.calls["llm"][-1][0]["content"].startswith("당신은 학술 논문 검색 도우미 '집현전'")
    assert note.startswith("오늘 날씨") and "검색어 예시 2개" in note

    env.calls["search_response"] = _search_response(results={"arxiv": []})
    env.calls["llm_error"] = True
    events = _events(env.client, conv_id, "없는 주제 zzz")
    assert "찾지 못했어요" in events[-2]["delta"] and "GraphRAG 최신 연구" in events[-2]["delta"]
    assert env.db.get_conversation(conv_id, "alice", "inc-a")["turns"][-1]["blocks"] == []


def test_llm_failure_uses_fallback_sentence(env):
    env.calls["llm_error"] = True
    conv_id = env.client.post("/api/conversations", json={"message": "트랜스포머"}).json()["id"]
    events = _events(env.client, conv_id)
    assert events[-1].get("done") and "2편의 논문을 찾았습니다" in events[-2]["delta"]
    turn = env.client.get(f"/api/conversations/{conv_id}").json()["turns"][-1]
    assert turn["status"] == "done" and turn["content"].endswith("2편의 논문을 찾았습니다. 오른쪽 그래프와 목록에서 논문 사이의 관계를 살펴보세요.")


def test_search_exception_ends_with_error_and_can_be_retried(env):
    env.calls["search_error"] = True
    conv_id = env.client.post("/api/conversations", json={"message": "트랜스포머"}).json()["id"]
    events = _events(env.client, conv_id)
    assert "error" in events[-1] and not any("done" in e for e in events)
    assert env.client.get(f"/api/conversations/{conv_id}").json()["turns"][-1]["status"] == "error"

    env.calls["search_error"] = False
    assert _events(env.client, conv_id)[-1].get("done")
    turns = env.client.get(f"/api/conversations/{conv_id}").json()["turns"]
    assert [t["status"] for t in turns] == ["done", "error", "done"]


def test_follow_up_answer_path_uses_latest_results(env, monkeypatch):
    conv_id = env.client.post("/api/conversations", json={"message": "트랜스포머"}).json()["id"]
    _events(env.client, conv_id)

    env.calls["route"] = '{"action": "answer", "query": null, "lead": ""}'
    events = _events(env.client, conv_id, "첫 번째 논문을 설명해줘")
    assert not any("block" in e for e in events) and events[-1]["done"]["intent"] == "answer"
    assert len(env.calls["search"]) == 1
    system, papers = env.calls["llm"][-1][0], env.calls["llm"][-1][1]
    assert system["role"] == "system" and "[1]" not in system["content"]
    assert papers["role"] == "user" and papers["content"].rstrip().endswith("</papers>")
    assert "[1] A (2020)" in papers["content"] and "[2] B (2021)" in papers["content"]
    assert env.calls["llm"][-1][-1] == {"role": "user", "content": "첫 번째 논문을 설명해줘"}


def test_stream_llm_preserves_chunk_order_and_run_search_wiring(monkeypatch):
    import asyncio

    import routers.search as rs

    chunks = [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=t))]) for t in "abc"]
    monkeypatch.setattr(turn_runner, "create_chat_completion", lambda client, **kw: iter(chunks))
    monkeypatch.setattr(turn_runner, "get_openai_client", lambda: None)
    seen = []

    async def go():
        text = await turn_runner.stream_llm([], seen.append)
        seen.append("end")
        return text

    assert asyncio.run(go()) == "abc" and seen == [{"delta": "a"}, {"delta": "b"}, {"delta": "c"}, "end"]

    async def fake_search_papers(request, username, http_request):
        return (request, username, http_request)

    monkeypatch.setattr(rs, "search_papers", fake_search_papers)
    request, username, http_request = asyncio.run(turn_runner.run_search("gnn", "alice"))
    assert (request.query, request.max_results, len(request.sources), username, http_request) == ("gnn", 50, 6, "alice", None)


def test_flatten_drops_same_title_under_different_keys(env):
    title = "Is GraphRAG Needed? From Basic RAG to Graph-/Agentic Solutions with Context Optimization"
    env.calls["search_response"] = _search_response(results={
        "openalex": [
            {"result_key": "w2", "_rank": 3, "source": "openalex", "title": title.upper() + " "},
            {"result_key": "w1", "_rank": 2, "source": "openalex", "title": title},
            {"result_key": "w0", "_rank": 1, "source": "openalex", "title": "Other"},
        ],
    })
    conv_id = env.client.post("/api/conversations", json={"message": "graphrag"}).json()["id"]
    block = next(e["block"] for e in _events(env.client, conv_id) if "block" in e)
    assert [p["result_key"] for p in block["papers"]] == ["w0", "w1"] and block["total"] == 2


def test_new_message_cancels_running_turn(env, monkeypatch):
    import asyncio
    import threading

    monkeypatch.setattr(conversations, "KEEPALIVE_INTERVAL_SEC", 0.05)
    entered = threading.Event()
    real_llm = turn_runner.stream_llm

    async def blocking_llm(messages, emit):
        if not entered.is_set():
            entered.set()
            emit({"delta": "부분"})
            await asyncio.sleep(3600)
        return await real_llm(messages, emit)

    monkeypatch.setattr(turn_runner, "stream_llm", blocking_llm)
    with TestClient(env.client.app) as client:  # one event loop shared by both requests
        conv_id = client.post("/api/conversations", json={"message": "트랜스포머"}).json()["id"]
        first = {}
        worker = threading.Thread(target=lambda: first.setdefault("events", _events(client, conv_id)))
        worker.start()
        assert entered.wait(5)

        assert client.post(f"/api/conversations/{conv_id}/turns", json={}).status_code == 400
        monkeypatch.setattr(turn_runner, "stream_llm", lambda m, emit: _async(emit({"delta": "새 답"}) or "새 답"))
        second = _events(client, conv_id, "그래프 신경망")
        worker.join(5)

    assert second[-1].get("done") and "error" in first["events"][-1]
    turns = env.client.get(f"/api/conversations/{conv_id}").json()["turns"]
    assert [(t["role"], t["status"], t["content"]) for t in turns] == [
        ("user", "done", "트랜스포머"),
        ("assistant", "error", "중단됨"),
        ("user", "done", "그래프 신경망"),
        ("assistant", "done", "'그래프 신경망'(으)로 찾아볼게요.\n\n새 답"),
    ]


async def _async(value):
    return value


def test_parse_route_actions_and_malformed_fallback():
    parse = turn_runner.parse_route
    chat = parse('{"action": "chat", "lead": "안녕하세요", "title": "인사"}', "안녕", False)
    assert chat["action"] == "chat" and chat["title"] == "인사"
    search = parse(
        '```json\n{"action": "search", "query": "GraphRAG vs RAG", "year_start": 2024, "year_end": null,'
        ' "lead": "비교 연구를\n찾아볼게요.", "title": "' + "가" * 40 + '"}\n```', "GraphRAG랑 RAG 비교 논문 찾아줘", False
    )
    assert (search["query"], search["year_start"], search["year_end"]) == ("GraphRAG vs RAG", 2024, None)
    assert search["lead"] == "비교 연구를 찾아볼게요." and len(search["title"]) == 24
    assert parse('{"action": "answer"}', "2번 자세히", True)["action"] == "answer"
    assert parse('{"action": "answer"}', "2번 자세히", False)["action"] == "search"  # no results to answer from
    clarify = parse('{"action": "clarify", "lead": "어떤 분야인가요?"}', "논문 찾아줘", False)
    assert clarify["action"] == "clarify" and clarify["lead"] == "어떤 분야인가요?"
    assert parse('{"action": "search", "year_start": 2025, "year_end": 2020}', "q", False)["year_start"] is None
    for raw in ("", "not json", '["search"]', '{"action": "dance"}'):
        route = parse(raw, "원문 메시지", False)
        assert (route["action"], route["query"], route["lead"], route["title"]) == ("search", "원문 메시지", "", None)


def test_routed_first_turn_sets_title_years_and_lead(env):
    env.calls["route"] = json.dumps({
        "action": "search", "query": "GraphRAG RAG comparison", "year_start": 2024, "year_end": None,
        "lead": "GraphRAG와 기존 RAG를 비교한 연구를 찾아볼게요.", "title": "GraphRAG와 RAG 비교",
    })
    conv_id = env.client.post("/api/conversations", json={"message": "GraphRAG랑 RAG 비교한 논문 찾아줘"}).json()["id"]
    events = _events(env.client, conv_id)
    assert events[0] == {"delta": "GraphRAG와 기존 RAG를 비교한 연구를 찾아볼게요.\n\n"} and "status" in events[1]
    assert events[-1]["done"]["title"] == "GraphRAG와 RAG 비교"
    assert env.client.get(f"/api/conversations/{conv_id}").json()["title"] == "GraphRAG와 RAG 비교"
    assert env.calls["search"][-1][0] == "GraphRAG RAG comparison" and env.calls["years"][-1] == (2024, None)
    assert "(첫 메시지)" in env.calls["route_inputs"][-1][1]["content"]

    # A refinement is a later turn: no title change, previous query reaches the summary prompt.
    env.calls["route"] = json.dumps({
        "action": "search", "query": "GraphRAG RAG comparison Korean", "year_start": 2024, "year_end": 2025,
        "lead": "한국어 데이터로 좁혀 볼게요.", "title": "무시될 제목",
    })
    events = _events(env.client, conv_id, "그 중 한국어 데이터로 한정해서")
    assert events[-1]["done"]["title"] is None and env.calls["years"][-1] == (2024, 2025)
    assert "현재 검색어: GraphRAG RAG comparison" in env.calls["route_inputs"][-1][1]["content"]
    assert "이전 검색어: GraphRAG RAG comparison\n" in env.calls["llm"][-1][1]["content"]
    assert env.client.get(f"/api/conversations/{conv_id}").json()["title"] == "GraphRAG와 RAG 비교"


def test_chat_and_clarify_turns_have_no_blocks_or_status(env):
    env.calls["route"] = '{"action": "chat", "lead": "", "title": "집현전 소개"}'
    conv_id = env.client.post("/api/conversations", json={"message": "뭘 할 수 있어?"}).json()["id"]
    events = _events(env.client, conv_id)
    assert _kinds(events) == ["delta", "delta", "done"] and events[-1]["done"]["intent"] == "chat"
    assert env.calls["llm"][-1][0]["content"].startswith("당신은 학술 논문 검색 도우미 '집현전'")
    assert env.calls["search"] == []

    env.calls["route"] = '{"action": "clarify", "lead": "어떤 주제인가요? 예: \\"GraphRAG 최신 연구\\", \\"LLM 에이전트 메모리\\""}'
    events = _events(env.client, conv_id, "논문 추천해줘")
    assert _kinds(events) == ["delta", "done"] and events[-1]["done"]["intent"] == "clarify"
    assert events[0]["delta"].startswith("어떤 주제인가요?")
    turns = env.client.get(f"/api/conversations/{conv_id}").json()["turns"]
    assert [t["intent"] for t in turns if t["role"] == "assistant"] == ["chat", "clarify"]
    assert all(t["blocks"] == [] for t in turns) and env.calls["search"] == []


def test_title_follows_chat_turns_until_first_search(env):
    env.calls["route"] = '{"action": "chat", "lead": "", "title": "도움 기능 안내"}'
    conv_id = env.client.post("/api/conversations", json={"message": "뭘 할 수 있어?"}).json()["id"]
    assert _events(env.client, conv_id)[-1]["done"]["title"] == "도움 기능 안내"

    env.calls["route"] = '{"action": "search", "query": "GraphRAG", "lead": "찾아볼게요.", "title": "GraphRAG 연구 동향"}'
    assert _events(env.client, conv_id, "GraphRAG 논문 찾아줘")[-1]["done"]["title"] == "GraphRAG 연구 동향"

    env.calls["route"] = '{"action": "search", "query": "LightRAG", "lead": "찾아볼게요.", "title": "다른 제목"}'
    assert _events(env.client, conv_id, "LightRAG도 찾아줘")[-1]["done"]["title"] is None
    assert env.client.get(f"/api/conversations/{conv_id}").json()["title"] == "GraphRAG 연구 동향"


def test_router_keyword_soup_is_normalised():
    soup = "agent memory long conversation memory long-term memory agent memory paper"
    route = turn_runner.parse_route(json.dumps({"action": "search", "query": soup}), "원문", False)
    assert route["query"] == "agent memory long conversation long-term"
    assert turn_runner.normalize_query('  "장기  대화 기억   에이전트 메모리 논문" ') == "장기 대화 기억 에이전트 메모리"
    assert turn_runner.normalize_query(" ".join(f"w{i}" for i in range(20))) == " ".join(f"w{i}" for i in range(12))
    assert turn_runner.parse_route('{"action": "search", "query": " \\"papers\\" "}', "원문", False)["query"] == "원문"


def test_search_without_router_title_uses_query_as_title(env):
    env.calls["route"] = '{"action": "search", "query": "장기 대화 기억 에이전트 메모리", "lead": "찾아볼게요.", "title": null}'
    conv_id = env.client.post(
        "/api/conversations", json={"message": "장기 대화 기억을 다루는 에이전트 메모리 논문을 보고 싶어"}
    ).json()["id"]
    assert _events(env.client, conv_id)[-1]["done"]["title"] == "장기 대화 기억 에이전트 메모리"
    assert env.client.get(f"/api/conversations/{conv_id}").json()["title"] == "장기 대화 기억 에이전트 메모리"

    env.calls["route"] = '{"action": "search", "query": "LightRAG", "lead": "찾아볼게요.", "title": null}'
    assert _events(env.client, conv_id, "LightRAG도")[-1]["done"]["title"] is None  # already searched
