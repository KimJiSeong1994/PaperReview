"""Conversation endpoints and the SSE turn stream (search/graph/LLM monkeypatched)."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.assistant import tools, turn_runner
from routers import conversations
from routers.deps.auth import AuthenticatedPrincipal, get_authenticated_principal
from routers.deps.middleware import limiter
from routers.deps import storage
from src.storage.conversation_db import ConversationDB
from src.storage.soul_db import SoulDB
from src.storage.user_db import AccountLifecycleError

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


class _CurrentUsers:
    """Account authority stand-in for the post-turn memory write."""

    def __init__(self, current):
        self.current = current

    @contextmanager
    def account_guard(self, username, incarnation):
        if (username, incarnation) not in self.current:
            raise AccountLifecycleError("account_inactive_or_mismatch")
        yield {}


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = ConversationDB(tmp_path / "conversations.db")
    monkeypatch.setattr(conversations, "_get_conversation_db", lambda: db)
    souls = SoulDB(tmp_path / "souls.db")
    monkeypatch.setattr(storage, "_get_soul_db", lambda: souls)
    monkeypatch.setattr(storage, "_get_user_db", lambda: _CurrentUsers({("alice", "inc-a")}))
    monkeypatch.setattr(turn_runner, "_review_starts", {})
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

    def fake_route(client, **kwargs):  # the non-streaming LLM calls: router and memory extractor
        if kwargs["messages"][0]["content"] == turn_runner._EXTRACT_PROMPT:
            calls.setdefault("extract_inputs", []).append(kwargs["messages"])
            content = calls.get("extract", '{"items": []}')
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=None)
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
        client=TestClient(app), other=TestClient(other), anonymous=TestClient(anonymous), db=db, calls=calls,
        souls=souls,
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
    last = env.calls["llm"][-1][-1]
    assert last["role"] == "user" and last["content"].endswith("질문: 첫 번째 논문을 설명해줘")
    assert last["content"].startswith("직전 답변:\n'트랜스포머'(으)로 찾아볼게요.")


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
    chat = parse('{"action": "chat", "lead": "안녕하세요", "title": "인사"}', "안녕", [])
    assert chat["action"] == "chat" and chat["title"] == "인사"
    search = parse(
        '```json\n{"action": "search", "query": "GraphRAG vs RAG", "year_start": 2024, "year_end": null,'
        ' "lead": "비교 연구를\n찾아볼게요.", "title": "' + "가" * 40 + '"}\n```', "GraphRAG랑 RAG 비교 논문 찾아줘", []
    )
    assert (search["query"], search["year_start"], search["year_end"]) == ("GraphRAG vs RAG", 2024, None)
    assert search["lead"] == "비교 연구를 찾아볼게요." and len(search["title"]) == 24
    assert parse('{"action": "answer"}', "2번 자세히", [{"title": "A"}])["action"] == "answer"
    assert parse('{"action": "answer"}', "2번 자세히", [])["action"] == "search"  # no results to answer from
    clarify = parse('{"action": "clarify", "lead": "어떤 분야인가요?"}', "논문 찾아줘", [])
    assert clarify["action"] == "clarify" and clarify["lead"] == "어떤 분야인가요?"
    assert parse('{"action": "search", "year_start": 2025, "year_end": 2020}', "q", [])["year_start"] is None
    for raw in ("", "not json", '["search"]', '{"action": "dance"}'):
        route = parse(raw, "원문 메시지", [])
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
    route = turn_runner.parse_route(json.dumps({"action": "search", "query": soup}), "원문", [])
    assert route["query"] == "agent memory long conversation long-term"
    assert turn_runner.normalize_query('  "장기  대화 기억   에이전트 메모리 논문" ') == "장기 대화 기억 에이전트 메모리"
    assert turn_runner.normalize_query(" ".join(f"w{i}" for i in range(20))) == " ".join(f"w{i}" for i in range(12))
    assert turn_runner.parse_route('{"action": "search", "query": " \\"papers\\" "}', "원문", [])["query"] == "원문"


def test_search_without_router_title_uses_query_as_title(env):
    env.calls["route"] = '{"action": "search", "query": "장기 대화 기억 에이전트 메모리", "lead": "찾아볼게요.", "title": null}'
    conv_id = env.client.post(
        "/api/conversations", json={"message": "장기 대화 기억을 다루는 에이전트 메모리 논문을 보고 싶어"}
    ).json()["id"]
    assert _events(env.client, conv_id)[-1]["done"]["title"] == "장기 대화 기억 에이전트 메모리"
    assert env.client.get(f"/api/conversations/{conv_id}").json()["title"] == "장기 대화 기억 에이전트 메모리"

    env.calls["route"] = '{"action": "search", "query": "LightRAG", "lead": "찾아볼게요.", "title": null}'
    assert _events(env.client, conv_id, "LightRAG도")[-1]["done"]["title"] is None  # already searched


PAPER_LIST = [{"title": "Attention Is All You Need"}, {"title": "From Local to Global: A GraphRAG Approach"}]


def test_parse_route_review_index_and_title_resolution():
    parse = turn_runner.parse_route
    assert parse('{"action": "review", "paper_index": 2}', "2번 심층 리뷰", PAPER_LIST)["paper_index"] == 2
    assert parse('{"action": "review", "paper_index": "1"}', "1번 리뷰해줘", PAPER_LIST)["paper_index"] == 1
    by_title = parse('{"action": "review", "paper_index": "graphrag approach"}', "GraphRAG 논문 리뷰", PAPER_LIST)
    assert (by_title["action"], by_title["paper_index"]) == ("review", 2)
    for bad in ('{"action": "review", "paper_index": 7}', '{"action": "review", "paper_index": null}',
                '{"action": "review", "paper_index": "없는 제목"}', '{"action": "review", "paper_index": true}'):
        route = parse(bad, "리뷰해줘", PAPER_LIST)
        assert route["action"] == "clarify" and route["lead"].startswith("몇 번 논문을 심층 리뷰할까요?")
    assert parse('{"action": "review", "paper_index": 1}', "리뷰해줘", [])["action"] == "clarify"


def test_pending_offer_is_last_sentence_of_last_answer():
    history = [
        {"role": "user", "content": "q", "status": "done"},
        {"role": "assistant", "content": "리드.\n\n- A [1] — x\n\n요약입니다. 관련 비교 논문과 함께 볼까요?", "status": "done"},
    ]
    assert turn_runner.pending_offer(history) == "관련 비교 논문과 함께 볼까요?"
    assert turn_runner.pending_offer([]) == ""


def test_review_turn_starts_owned_deep_review(env, monkeypatch, tmp_path):
    import threading
    from functools import partial

    from app.DeepAgent import workspace_manager
    from routers import reviews
    from src.storage.user_db import UserDB

    users = UserDB(tmp_path / "users.db")
    principal = AuthenticatedPrincipal("alice", users.create_account("alice", {})["account_incarnation"])
    monkeypatch.setattr(reviews, "_get_user_db", lambda: users)
    monkeypatch.setattr(
        workspace_manager, "WorkspaceManager", partial(workspace_manager.WorkspaceManager, base_path=str(tmp_path / "ws"))
    )
    started, ran = {}, threading.Event()

    def fake_background(**kwargs):
        started.update(kwargs)
        ran.set()

    monkeypatch.setattr(reviews, "run_deep_review_background", fake_background)
    app = env.client.app
    app.dependency_overrides[get_authenticated_principal] = lambda: principal

    with TestClient(app) as client:  # keep the loop alive until the scheduled review runs
        conv_id = client.post("/api/conversations", json={"message": "트랜스포머"}).json()["id"]
        _events(client, conv_id)
        env.calls["route"] = '{"action": "review", "paper_index": 2, "lead": ""}'
        events = _events(client, conv_id, "2번 논문에 대해서 심층 리뷰 해줘")
        assert ran.wait(5)

    assert _kinds(events) == ["delta", "block:review_started", "done"] and events[-1]["done"]["intent"] == "review"
    assert events[0]["delta"] == "2번 논문 「B」 심층 리뷰를 시작할게요. 몇 분 걸립니다.\n\n"
    block = events[1]["block"]
    assert (block["paper_index"], block["paper_title"], block["paper_key"]) == (2, "B", "k1")
    # The real pipeline moves to "analyzing"; any non-terminal status counts as running.
    with reviews.review_sessions_lock:
        reviews.review_sessions[block["session_id"]].update(status="analyzing", progress="논문 분석 중")

    # Same paper again (e.g. a bare "2"): no re-run, report its progress instead.
    env.calls["route"] = '{"action": "review", "paper_index": 2, "lead": ""}'
    repeat = _events(env.client, conv_id, "2")
    assert _kinds(repeat) == ["delta", "done"] and repeat[-1]["done"]["intent"] == "chat"
    assert repeat[0]["delta"].startswith("2번 논문 심층 리뷰는 이미 진행 중이에요(상태: 분석 중).")
    assert "직전 행동: review 2번 논문(B) 심층 리뷰 시작" in env.calls["route_inputs"][-1][1]["content"]

    # Another paper while one is analyzing: the duplicate guard answers.
    env.calls["route"] = '{"action": "review", "paper_index": 1, "lead": ""}'
    again = _events(env.client, conv_id, "1번도 심층 리뷰 해줘")
    assert _kinds(again) == ["delta", "done"] and again[-1]["done"]["intent"] == "chat"
    assert again[0]["delta"] == "이미 진행 중인 심층 리뷰가 있어요(2번 논문, 상태: 분석 중). 끝나면 결과를 보여드릴게요."
    session = reviews.review_sessions.pop(block["session_id"])
    assert (session["username"], session["account_incarnation"]) == ("alice", principal.account_incarnation)
    assert session["paper_ids"] == ["k1"] and session["papers_data"][0]["result_key"] == "k1"
    assert started["owner_principal"] == principal and started["session_id"] == block["session_id"]
    assert started["paper_ids"] == ["k1"] and started["fast_mode"] is True and started["num_researchers"] == 3
    assert "직전 제안: 없음" not in env.calls["route_inputs"][-1][1]["content"]  # previous summary closed with an offer
    turn = client.get(f"/api/conversations/{conv_id}").json()["turns"][-5]
    assert turn["intent"] == "review" and turn["blocks"] == [block]

    # Once the review is no longer processing, a new review may start.
    session["status"] = "completed"
    reviews.review_sessions[block["session_id"]] = session
    assert turn_runner._running_review([{"blocks": [block]}]) is None
    reviews.review_sessions.pop(block["session_id"])


def test_invalid_review_index_clarifies_and_offer_reaches_router(env):
    conv_id = env.client.post("/api/conversations", json={"message": "트랜스포머"}).json()["id"]
    _events(env.client, conv_id)  # summary closes with the fake "요약 [1]"
    env.calls["route"] = '{"action": "review", "paper_index": 9, "lead": ""}'
    events = _events(env.client, conv_id, "9번 리뷰해줘")
    assert _kinds(events) == ["delta", "done"] and events[-1]["done"]["intent"] == "clarify"
    assert events[0]["delta"].startswith("몇 번 논문을 심층 리뷰할까요?")
    router_input = env.calls["route_inputs"][-1][1]["content"]
    assert "직전 제안: 요약 [1]" in router_input and "[1] A" in router_input and "[2] B" in router_input


def test_same_search_as_previous_turn_is_not_rerun(env):
    route = {"action": "search", "query": "GraphRAG", "year_start": 2024, "year_end": None, "lead": "찾아볼게요."}
    env.calls["route"] = json.dumps(route)
    conv_id = env.client.post("/api/conversations", json={"message": "GraphRAG 2024년 이후"}).json()["id"]
    first = _events(env.client, conv_id)
    block = next(e["block"] for e in first if "block" in e)
    assert (block["year_start"], block["year_end"]) == (2024, None)

    repeat = _events(env.client, conv_id, "1")
    assert _kinds(repeat) == ["delta", "done"] and repeat[-1]["done"]["intent"] == "chat"
    assert repeat[0]["delta"] == "같은 조건의 검색 결과를 이미 보여드렸어요. 조건을 바꾸거나 특정 논문을 골라 주세요."
    assert len(env.calls["search"]) == 1
    assert "직전 행동: search_papers 'GraphRAG'" in env.calls["route_inputs"][-1][1]["content"]

    env.calls["route"] = json.dumps({**route, "year_start": 2025})  # changed condition → runs
    assert any("block" in e for e in _events(env.client, conv_id, "2025년 이후만"))
    assert len(env.calls["search"]) == 2


def test_bare_reply_after_review_reports_that_turns_own_session(env, monkeypatch):
    from routers.deps import storage

    sessions = {
        "s-old": {"status": "completed", "progress": "Restored from workspace"},
        "s-new": {"status": "analyzing", "progress": "AI is analysing the papers..."},
    }
    monkeypatch.setattr(storage, "review_sessions", sessions)

    def review_turn(sid, n):
        return {"role": "assistant", "status": "done", "content": "리드", "blocks": [
            {"type": "review_started", "session_id": sid, "paper_index": n, "paper_title": "T", "paper_key": f"k{n}"}]}

    history = [review_turn("s-old", 1), {"role": "user", "status": "done", "content": "2번 리뷰"}, review_turn("s-new", 2)]
    chat_route = {"action": "chat", "query": "", "year_start": None, "year_end": None, "paper_index": None}
    reply = turn_runner.repeat_reply(chat_route, history, [], "2")  # router said chat; code still answers
    assert reply.startswith("2번 논문 심층 리뷰는 이미 진행 중이에요(상태: 분석 중).") and "Restored" not in reply
    assert turn_runner.repeat_reply(chat_route, history, [], "응").startswith("2번 논문 심층 리뷰는 이미 진행 중이에요")
    assert turn_runner.repeat_reply(chat_route, history, [], "1") is None  # another number goes to the router
    assert turn_runner.repeat_reply(chat_route, history, [], "2번 요약해줘") is None

    sessions["s-new"]["status"] = "completed"
    assert "이미 끝났어요(상태: 완료)" in turn_runner.repeat_reply(chat_route, history, [], "2")
    sessions["s-new"]["status"] = "verifying"  # unknown status → no parenthetical, raw progress never shown
    assert turn_runner.repeat_reply(chat_route, history, [], "2").startswith("2번 논문 심층 리뷰는 이미 진행 중이에요. ")
    sessions["s-new"]["status"] = "failed"  # a failed review may be started again
    assert turn_runner.repeat_reply(chat_route, history, [], "2") is None
    del sessions["s-new"]  # expired (24 h TTL) or lost in a restart: not a repeat, may re-run
    assert turn_runner.repeat_reply(chat_route, history, [], "2") is None
    review_route = {**chat_route, "action": "review", "paper_index": 2}
    assert turn_runner.repeat_reply(review_route, history, [{}, {"result_key": "k2"}], "2번 다시 리뷰") is None
    assert turn_runner._running_review(history) is None


def test_user_memory_reaches_prompts_and_turns_are_remembered(env):
    env.souls.set_user_md("alice", "inc-a", "박사과정, 짧은 답 선호")
    env.souls.add_memories("alice", "inc-a", [{"kind": "paper", "text": "심층 리뷰: HiGMem"}], None)
    env.calls["route"] = json.dumps({"action": "search", "query": "장기 기억 에이전트", "lead": "찾아볼게요."})
    env.calls["extract"] = '{"items": [{"kind": "fact", "text": "12월 학회 마감"}]}'
    with TestClient(env.client.app) as client:  # keep the loop alive for the post-`done` memory write
        conv_id = client.post("/api/conversations", json={"message": "장기 기억 에이전트 논문, 12월 마감이야"}).json()["id"]
        _events(client, conv_id)

        router_input = env.calls["route_inputs"][-1][1]["content"]
        assert "사용자 메모리:\n<user_memory>\n# USER.md\n\n박사과정, 짧은 답 선호" in router_input
        summary_system = env.calls["llm"][-1][0]["content"]
        assert "<user_memory>" in summary_system and "- [논문] 심층 리뷰: HiGMem" in summary_system
        assert "메모리에 없는 과거는 절대 지어내지 마세요" in summary_system

        texts = {m["text"] for m in env.souls.get_soul("alice", "inc-a")["memories"]}
        assert {"장기 기억 에이전트", "12월 학회 마감", "심층 리뷰: HiGMem"} <= texts

        env.calls["route"] = '{"action": "answer", "lead": ""}'
        _events(client, conv_id, "1번이 HiGMem 이랑 뭐가 달라?")
        assert "<user_memory>" in env.calls["llm"][-1][0]["content"]

        before = len(env.souls.get_soul("alice", "inc-a")["memories"])
        extract_calls = len(env.calls["extract_inputs"])
        env.calls["route"] = '{"action": "clarify", "lead": "어떤 주제인가요?"}'
        _events(client, conv_id, "추천해줘")
        assert len(env.calls["extract_inputs"]) == extract_calls  # clarify turns teach nothing
        assert len(env.souls.get_soul("alice", "inc-a")["memories"]) == before


def test_review_start_limit_per_user(env):
    import time
    from collections import deque

    for _ in range(5):
        assert turn_runner._reserve_start("review", "carol")
    assert not turn_runner._reserve_start("review", "carol")  # 6th within 10 minutes
    assert turn_runner._reserve_start("review", "dave")  # per user

    conv_id = env.client.post("/api/conversations", json={"message": "트랜스포머"}).json()["id"]
    _events(env.client, conv_id)
    turn_runner._review_starts[("review", "alice")] = deque([time.monotonic()] * 5)
    env.calls["route"] = '{"action": "review", "paper_index": 1, "lead": ""}'
    events = _events(env.client, conv_id, "1번 심층 리뷰 해줘")
    assert _kinds(events) == ["delta", "done"] and events[-1]["done"]["intent"] == "chat"
    assert events[0]["delta"] == "심층 리뷰는 10분에 5편까지 시작할 수 있어요. 잠시 후 다시 시도해 주세요."

    turn_runner._review_starts[("review", "alice")] = deque([time.monotonic() - 601] * 5)  # window passed
    assert turn_runner._reserve_start("review", "alice")


def test_chat_review_runs_in_anyio_threadpool_and_cleans_up(monkeypatch, tmp_path):
    import asyncio
    from functools import partial

    from app.DeepAgent import workspace_manager
    from routers import reviews

    monkeypatch.setattr(
        workspace_manager, "WorkspaceManager", partial(workspace_manager.WorkspaceManager, base_path=str(tmp_path))
    )
    calls = []

    async def fake_pool(fn, **kwargs):
        calls.append((fn, kwargs["session_id"]))

    monkeypatch.setattr(reviews, "run_in_threadpool", fake_pool)
    monkeypatch.setattr(reviews, "_cleanup_expired_sessions", lambda: calls.append("cleanup"))

    async def go():
        sid = await reviews.start_review_session([{"title": "T"}], ["k"], None)
        await asyncio.sleep(0)  # let the scheduled task start
        return sid

    sid = asyncio.run(go())
    assert calls == ["cleanup", (reviews.run_deep_review_background, sid)]
    reviews.review_sessions.pop(sid)


# ── Phase A5: assistant tools ─────────────────────────────────────────


TWO = [{"title": "Attention Is All You Need"}, {"title": "APEX-MEM: Agentic Semi-Structured Memory"},
       {"title": "LightRAG: Simple and Fast RAG"}, {"title": "Fourth"}]


def test_registry_and_router_prompt():
    assert [t.name for t in tools.TOOLS] == [
        "search_papers", "answer_from_results", "deep_review", "open_pdf", "highlight_pdf"]
    assert set(turn_runner.TOOL_ACTIONS) == set(tools.TOOLS_BY_NAME)
    prompt = turn_runner.build_route_prompt()
    review = tools.TOOLS_BY_NAME["deep_review"]
    assert f'- "deep_review": {review.description}' in prompt and '"2번 핵심 기여랑 한계까지 정리해줘"' in prompt
    assert '"tool": "chat|clarify|search_papers|answer_from_results|deep_review|open_pdf|highlight_pdf"' in prompt
    for word in ("딥리뷰", "딥 리뷰", "심층 리뷰", "심층 분석", "정독", "꼼꼼히", "deep review", "in-depth"):
        assert word in review.description


def test_tool_and_legacy_action_are_aliases():
    parse = turn_runner.parse_route
    by_tool = parse('{"tool": "deep_review", "paper_index": 2}', "x", TWO)
    by_action = parse('{"action": "review", "paper_index": 2}', "x", TWO)
    assert by_tool == by_action and (by_tool["action"], by_tool["tool"]) == ("review", "deep_review")
    assert parse('{"tool": "search_papers", "query": "q"}', "x", [])["tool"] == "search_papers"
    assert parse('{"tool": "chat"}', "x", [])["tool"] is None
    pdf = parse('{"tool": "open_pdf", "paper_index": 9}', "x", TWO)
    assert pdf["action"] == "clarify" and pdf["lead"].startswith("몇 번 논문의 PDF를 열까요?")


def test_precheck_routes_paper_tools_deterministically():
    pre = turn_runner.precheck_route
    review = pre("3번 논문 딥리뷰", [], TWO)
    assert (review["action"], review["paper_index"]) == ("review", 3)
    assert pre("apex-mem 심층 분석 부탁해", [], TWO)["paper_index"] == 2  # title head
    single = [{"role": "assistant", "status": "done", "content": "핵심입니다.\n\n- APEX-MEM [2] — 반시간 메모리", "blocks": []}]
    implicit = pre("이 논문 제대로 파고들고 싶어", single, TWO)
    assert (implicit["action"], implicit["paper_index"]) == ("review", 2)
    ambiguous = pre("딥리뷰 해줘", [], TWO)
    assert ambiguous["action"] == "clarify"
    assert ambiguous["lead"] == ("몇 번 논문을 심층 리뷰할까요?\n\n1. Attention Is All You Need\n"
                                 "2. APEX-MEM: Agentic Semi-Structured Memory\n3. LightRAG: Simple and Fast RAG")
    assert pre("꼼꼼히 비교해줘", [], TWO) is None  # weak marker without a paper → LLM router
    assert pre("3번 딥리뷰", [], []) is None  # nothing searched yet
    assert pre("2번 원문 보여줘", [], TWO)["action"] == "open_pdf"
    assert pre("전문가 의견은?", [], TWO) is None
    assert pre("1번 PDF에서 핵심 문장 표시해줘", [], TWO)["action"] == "highlight_pdf"
    assert pre("하이라이트 해줘", [], TWO)["lead"].startswith("몇 번 논문에서 핵심 문장을 표시할까요?")


def _searched(env):
    conv_id = env.client.post("/api/conversations", json={"message": "트랜스포머"}).json()["id"]
    _events(env.client, conv_id)
    return conv_id


def test_open_pdf_turn_and_no_pdf_path(env, monkeypatch):
    async def resolve(paper):
        return None if paper["result_key"] == "k1" else "https://arxiv.org/pdf/1706.03762.pdf"

    monkeypatch.setattr(tools, "resolve_pdf_url", resolve)
    with TestClient(env.client.app) as client:
        conv_id = client.post("/api/conversations", json={"message": "트랜스포머"}).json()["id"]
        _events(client, conv_id)
        events = _events(client, conv_id, "1번 논문 PDF 열어줘")
        assert _kinds(events) == ["delta", "block:paper_pdf", "done"] and events[-1]["done"]["intent"] == "open_pdf"
        assert events[0]["delta"] == "1번 논문 「A」 PDF를 열게요.\n\n"
        block = events[1]["block"]
        assert block == {
            "type": "paper_pdf", "paper_index": 1, "paper_title": "A", "paper_key": "k0",
            "pdf_url": "https://arxiv.org/pdf/1706.03762.pdf",
            "proxy_url": "/api/pdf/proxy?url=https%3A%2F%2Farxiv.org%2Fpdf%2F1706.03762.pdf",
            "viewer_url": "/paper-viewer?title=A&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F1706.03762.pdf&year=2020",
            "authors": [], "year": 2020,
        }
        assert "PDF 열람: A" in {m["text"] for m in env.souls.get_soul("alice", "inc-a")["memories"]}

        missing = _events(client, conv_id, "2번 원문 보여줘")
        assert _kinds(missing) == ["delta", "done"] and missing[-1]["done"]["intent"] == "chat"
        assert missing[0]["delta"] == "이 논문의 PDF를 찾지 못했어요."


def test_highlight_turn_fallback_and_shared_window(env, monkeypatch):
    import time
    from collections import deque

    async def resolve(paper):
        return "https://arxiv.org/pdf/1.pdf"

    texts = {"text": "본문 " * 100}

    async def extract(url):
        if texts["text"] is None:
            raise TimeoutError
        return texts["text"]

    items = [{"id": f"phl_{i}", "text": f"문장 {i}", "color": "#86efac", "memo": "[Key Finding] 이유",
              "category": "finding"} for i in range(2)]

    async def highlights(text, title):
        return items

    monkeypatch.setattr(tools, "resolve_pdf_url", resolve)
    monkeypatch.setattr(tools, "extract_pdf_text", extract)
    monkeypatch.setattr(tools, "generate_highlights", highlights)
    conv_id = _searched(env)

    events = _events(env.client, conv_id, "2번 논문 하이라이트 해줘")
    assert _kinds(events) == ["delta", "block:pdf_highlights", "delta", "delta", "done"]
    assert events[0]["delta"] == "2번 논문 「B」에서 핵심 문장을 표시할게요.\n\n"
    block = events[1]["block"]
    assert block["highlights"] == items and block["paper_key"] == "k1" and block["viewer_url"].startswith("/paper-viewer?")
    assert events[-1]["done"]["intent"] == "highlight_pdf"
    assert "<highlights>\n[finding] 문장 0" in env.calls["llm"][-1][1]["content"]

    texts["text"] = None  # extraction fails → open-able PDF + one line
    events = _events(env.client, conv_id, "1번 핵심 문장 표시해줘")
    assert _kinds(events) == ["delta", "block:paper_pdf", "delta", "done"]
    assert events[2]["delta"] == "본문 추출이 안 돼 뷰어에서 자동 하이라이트를 눌러 주세요."
    assert len(turn_runner._review_starts[("highlight", "alice")]) == 1  # failed run gave its slot back

    turn_runner._review_starts[("highlight", "alice")] = deque([time.monotonic()] * 10)
    events = _events(env.client, conv_id, "2번 하이라이트")
    assert events[0]["delta"] == "하이라이트는 10분에 10편까지 만들 수 있어요. 잠시 후 다시 시도해 주세요."
    assert turn_runner._reserve_start("review", "alice")  # same window, separate budget


def test_pdf_helpers_resolver_extractor_and_highlight_shape(monkeypatch):
    import asyncio

    from routers import paper_reviews, pdf_proxy

    assert asyncio.run(tools.resolve_pdf_url({"pdf_url": "https://x.org/a.pdf"})) == "https://x.org/a.pdf"
    seen = {}

    async def no_cache(title, doi):
        return None

    async def put(title, doi, result):
        seen["cached"] = result.pdf_url

    async def client():
        return None

    async def resolve_single(c, title, doi, arxiv_id=None):
        seen["args"] = (title, doi, arxiv_id)
        return pdf_proxy.PdfResolveResponse(pdf_url="https://arxiv.org/pdf/2.pdf", source="arxiv")

    monkeypatch.setattr(pdf_proxy, "_cache_get", no_cache)
    monkeypatch.setattr(pdf_proxy, "_cache_put", put)
    monkeypatch.setattr(pdf_proxy, "_get_http_client", client)
    monkeypatch.setattr(pdf_proxy, "_resolve_single", resolve_single)
    paper = {"title": "T", "doi": "10.1/x", "arxiv_id": "2"}
    assert asyncio.run(tools.resolve_pdf_url(paper)) == "https://arxiv.org/pdf/2.pdf"
    assert seen == {"args": ("T", "10.1/x", "2"), "cached": "https://arxiv.org/pdf/2.pdf"}

    with pytest.raises(ValueError, match="not allowed"):  # private / non-academic hosts are never fetched
        asyncio.run(tools.extract_pdf_text("http://10.0.0.1/internal.pdf"))

    raw = [{"text": f"Important sentence number {i}.", "category": "finding", "reason": "r"} for i in range(25)]
    monkeypatch.setattr(paper_reviews, "generate_pdf_highlights_llm", lambda text, title, client: raw)
    monkeypatch.setattr(turn_runner, "get_openai_client", lambda: None)
    out = asyncio.run(tools.generate_highlights("Important sentence number 0. " * 10, "T"))
    assert len(out) == 20 and {"id", "text", "color", "memo", "category", "significance"} <= set(out[0])


def test_pdf_text_keeps_word_spaces_and_spaceless_text_is_rejected():
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "We evaluate all methods on two representative text-based tasks.")
    text = tools.pdf_bytes_to_text(doc.tobytes())
    assert "We evaluate all methods on two representative" in text and tools.has_word_spaces(text)

    assert not tools.has_word_spaces("Weevaluateallmethodsontworepresentativetext-basedtasks:Acrossbothdatasets")
    assert tools.has_word_spaces("We evaluate all methods on two representative text-based tasks.")


def test_pdf_download_checks_every_redirect_hop(monkeypatch):
    import requests

    class Resp:
        def __init__(self, location=None, body=b"%PDF-1.4"):
            self.is_redirect, self.headers, self.body = location is not None, {"location": location}, body

        def close(self):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, size):
            yield self.body

    hops = {"https://arxiv.org/pdf/1": Resp("https://arxiv.org/pdf/1v2"), "https://arxiv.org/pdf/1v2": Resp()}
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: hops[url])
    assert tools._download_pdf("https://arxiv.org/pdf/1") == b"%PDF-1.4"

    hops["https://arxiv.org/pdf/1"] = Resp("http://169.254.169.254/latest/meta-data")
    with pytest.raises(ValueError, match="not allowed"):
        tools._download_pdf("https://arxiv.org/pdf/1")


def test_spaceless_extraction_falls_back_to_viewer(env, monkeypatch):
    async def resolve(paper):
        return "https://arxiv.org/pdf/2502.11371"

    async def extract(url):
        return "Weevaluateallmethodsontworepresentativetext-basedtasks:" * 20

    async def highlights(text, title):
        raise AssertionError("spaceless text must not reach the LLM")

    monkeypatch.setattr(tools, "resolve_pdf_url", resolve)
    monkeypatch.setattr(tools, "extract_pdf_text", extract)
    monkeypatch.setattr(tools, "generate_highlights", highlights)
    conv_id = _searched(env)
    events = _events(env.client, conv_id, "1번 논문 하이라이트 해줘")
    assert _kinds(events) == ["delta", "block:paper_pdf", "delta", "done"]
    assert events[2]["delta"] == "본문 추출이 안 돼 뷰어에서 자동 하이라이트를 눌러 주세요."


def test_slow_highlight_generation_falls_back_within_timeout(env, monkeypatch):
    import threading
    import time

    from routers import paper_reviews

    release = threading.Event()

    def stuck_llm(text, title, client):
        stuck_llm.chars = len(text)
        release.wait(5)  # the abandoned worker thread exits once the test is done
        return []

    async def resolve(paper):
        return "https://arxiv.org/pdf/2604.09666"

    async def extract(url):
        return "We evaluate all methods on two tasks. " * 1500  # ~57k chars

    monkeypatch.setattr(tools, "resolve_pdf_url", resolve)
    monkeypatch.setattr(tools, "extract_pdf_text", extract)
    monkeypatch.setattr(paper_reviews, "generate_pdf_highlights_llm", stuck_llm)
    monkeypatch.setattr(turn_runner, "get_openai_client", lambda: None)
    monkeypatch.setattr(tools, "HIGHLIGHT_LLM_TIMEOUT_SEC", 0.2)
    conv_id = _searched(env)
    try:
        started = time.monotonic()
        events = _events(env.client, conv_id, "2번 논문에서 핵심 문장 표시해줘")
        assert time.monotonic() - started < 3
    finally:
        release.set()
    assert _kinds(events) == ["delta", "block:paper_pdf", "delta", "done"]
    assert events[2]["delta"] == "하이라이트 생성이 오래 걸려 PDF만 열었어요. 뷰어에서 자동 하이라이트를 눌러 주세요."
    assert stuck_llm.chars == tools.HIGHLIGHT_LLM_CHARS  # only the first 20k chars reach the model


def test_tool_that_never_returns_ends_the_turn_with_error(env, monkeypatch):
    import asyncio

    async def forever(t):
        t.say("1번 논문 「A」 PDF를 열게요.\n\n")
        await asyncio.sleep(3600)

    monkeypatch.setitem(tools.TOOLS_BY_NAME, "open_pdf", tools.Tool("open_pdf", "d", (), forever))
    monkeypatch.setattr(turn_runner, "TOOL_DEADLINE_SEC", 0.1)
    conv_id = _searched(env)
    events = _events(env.client, conv_id, "1번 논문 PDF 열어줘")
    assert events[-1] == {"error": "시간이 너무 오래 걸려 중단했어요. 다시 시도해 주세요."}
    assert not any("done" in e for e in events)
    turn = env.client.get(f"/api/conversations/{conv_id}").json()["turns"][-1]
    assert (turn["status"], turn["content"]) == ("error", "1번 논문 「A」 PDF를 열게요.\n\n")
