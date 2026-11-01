"""Public sample conversations: routes, sanitiser and export script."""

import importlib.util
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import samples
from routers.deps.middleware import limiter
from src.storage.conversation_db import ConversationDB

_spec = importlib.util.spec_from_file_location("export_sample", "scripts/export_sample_conversation.py")
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)


def _client():
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(samples.router)
    limiter.reset()
    return TestClient(app)


def _papers(n):
    return [{"result_key": f"k{i}", "doc_id": f"d{i}", "_rank": i, "title": f"P{i}", "searched_by": "home_demo"}
            for i in range(n)]


def _graph(n):
    return {"nodes": [{"id": f"k{i}", "title": f"P{i}"} for i in range(n)],
            "edges": [{"source": f"k{i}", "target": f"k{i + 1}", "weight": 1} for i in range(n - 1)], "meta": {}}


def test_sanitiser_rules():
    turns = [
        {"seq": 1, "role": "user", "content": "추천해줘", "blocks_json": "[]", "intent": None, "status": "done"},
        {"seq": 2, "role": "assistant", "status": "done", "intent": "search",
         "content": "연구 프로필 기준으로 '그래프 기반 추천' 최신 논문을 찾아볼게요. 다른 주제를 원하시면 말씀해 주세요.\n\n"
                    "결론입니다[1].\n\n내 연구와의 연결: 추천시스템 콜드스타트에 쓸 수 있습니다[2].\n\n다음 단계?",
         "blocks_json": json.dumps([
             {"type": "search_results", "query": "q", "total": 25, "papers": _papers(25)},
             {"type": "graph", "query_hash": "h", "graph": _graph(25)},
             {"type": "review_started", "session_id": "s", "paper_index": 1, "username": "home_demo"},
             {"type": "bookmark_refs", "bookmarks": []}, {"type": "paper_pdf", "pdf_url": "x"},
             {"type": "pdf_highlights", "highlights": []},
         ])},
        {"seq": 3, "role": "user", "content": "2번", "blocks_json": "[]", "intent": None, "status": "done"},
        {"seq": 4, "role": "assistant", "content": "", "blocks_json": "[]", "intent": "search", "status": "error"},
    ]
    sample = export.build_sample(turns, slug="s", title="T", asof="2026-11-02")
    assert sample["question"] == "추천해줘" and [t["seq"] for t in sample["turns"]] == [1, 2, 3]  # error turn dropped
    answer = sample["turns"][1]
    assert answer["content"] == "관련 논문을 찾아 근거와 함께 답해 볼게요.\n\n결론입니다[1].\n\n다음 단계?"
    assert [b["type"] for b in answer["blocks"]] == ["search_results", "graph"]
    results, graph = answer["blocks"]
    assert len(results["papers"]) == 20 and results["total"] == 20
    assert "searched_by" not in json.dumps(sample) and "home_demo" not in json.dumps(sample)
    assert len(graph["graph"]["nodes"]) == 20 and len(graph["graph"]["edges"]) == 19  # trimmed to kept papers


def test_export_script_end_to_end_and_routes(tmp_path, monkeypatch):
    db = ConversationDB(tmp_path / "conversations.db")
    conv = db.create_conversation("alice", "inc-a", "t")
    db.append_turn(conv["id"], "user", "GraphRAG가 언제 좋아?")
    db.append_turn(conv["id"], "assistant", "관련 논문을 찾아볼게요.\n\n답[1].", blocks=[
        {"type": "search_results", "query": "q", "total": 3, "papers": _papers(3)},
        {"type": "graph", "query_hash": "h", "graph": _graph(3)}], intent="search")
    db.append_turn(conv["id"], "assistant", "", status="error")
    out_dir = tmp_path / "samples"
    path = export.export_sample(tmp_path / "conversations.db", conv["id"], slug="graphrag-when", title="언제 좋아",
                                asof="2026-11-02", out_dir=out_dir)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["id"] == "sample-graphrag-when" and len(written["turns"]) == 2
    assert "alice" not in path.read_text(encoding="utf-8") and "inc-a" not in path.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        export.export_sample(tmp_path / "conversations.db", conv["id"], slug="Bad Slug", title="x", asof="x",
                             out_dir=out_dir)
    with pytest.raises(LookupError):
        export.export_sample(tmp_path / "conversations.db", "missing", slug="x", title="x", asof="x", out_dir=out_dir)

    monkeypatch.setattr(samples, "SAMPLES_DIR", out_dir)
    client = _client()
    assert client.get("/api/samples/conversations").json() == [
        {"id": "sample-graphrag-when", "slug": "graphrag-when", "title": "언제 좋아",
         "question": "GraphRAG가 언제 좋아?", "asof": "2026-11-02", "turn_count": 2}]
    detail = client.get("/api/samples/conversations/graphrag-when").json()
    assert set(detail) == {"id", "slug", "title", "question", "asof", "turns"}
    assert set(detail["turns"][1]) == {"seq", "role", "content", "blocks", "intent"}
    assert [b["type"] for b in detail["turns"][1]["blocks"]] == ["search_results", "graph"]
    assert client.get("/api/samples/conversations/unknown").status_code == 404
    assert client.get("/api/samples/conversations/..%2Fsecrets").status_code == 404

    # An edited file is served without a restart (mtime-keyed cache).
    import os
    edited = {**written, "title": "바뀐 제목"}
    path.write_text(json.dumps(edited, ensure_ascii=False), encoding="utf-8")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    assert client.get("/api/samples/conversations/graphrag-when").json()["title"] == "바뀐 제목"


def test_committed_samples_load_through_the_route(monkeypatch):
    monkeypatch.setattr(samples, "SAMPLES_DIR", export.SAMPLES_DIR)
    client = _client()
    listed = {s["slug"]: s for s in client.get("/api/samples/conversations").json()}
    assert set(listed) == {"graphrag-vs-rag", "graphrag-core-explained", "long-term-agent-memory"}
    assert listed["graphrag-vs-rag"]["question"] == "GraphRAG가 기존 RAG보다 나은 경우는 언제야?"
    assert all(s["asof"] == "2026-11-02" for s in listed.values())
    for slug in listed:
        detail = client.get(f"/api/samples/conversations/{slug}").json()
        raw = json.dumps(detail, ensure_ascii=False)
        assert "home_demo" not in raw and "내 연구와의 연결" not in raw and "연구 프로필" not in raw
        results = [b for t in detail["turns"] for b in t["blocks"] if b["type"] == "search_results"]
        assert results and all(len(b["papers"]) <= 20 for b in results)
