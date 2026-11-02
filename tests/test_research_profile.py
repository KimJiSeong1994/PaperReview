"""Phase A9: derived research profile → assistant, recommendations, newsletter export."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.assistant import profile as profile_mod
from app.assistant import tools, turn_runner
from routers.deps import storage
from routers.deps.auth import AuthenticatedPrincipal
from src.storage.soul_db import SoulDB, read_profile_readonly
from tests.test_daily_recommendations import NOW, delivery, env, generate, snapshot  # noqa: F401  (env is a fixture)

ALICE = AuthenticatedPrincipal("alice", "inc-a")


def _reply(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=None)


@pytest.fixture
def souls(tmp_path, monkeypatch):
    db = SoulDB(tmp_path / "souls.db")
    monkeypatch.setattr(storage, "_get_soul_db", lambda: db)
    monkeypatch.setattr(turn_runner, "get_openai_client", lambda: None)
    return db


def _seed(db, user="alice", inc="inc-a"):
    db.set_user_md(user, inc, "")
    db.add_memories(user, inc, [{"kind": "research", "text": "추천시스템에서 그래프 기반 콜드스타트 완화를 연구 중"}], None)
    db.add_memories(user, inc, [{"kind": "fact", "text": "석사과정"}], None)
    for label, times in (("그래프 기반 추천", 3), ("에이전트 장기 기억", 1)):
        for _ in range(times):
            db.add_memories(user, inc, [{"kind": "interest", "text": label}], None)
    db.add_memories(user, inc, [{"kind": "paper", "text": "심층 리뷰: LightGCN"}], None)
    db.add_memories(user, inc, [{"kind": "preference", "text": "앞으로 답은 짧게"}], None)
    db.add_memories(user, inc, [{"kind": "topic", "text": "graph cold start"}], None)


MODEL_PROFILE = {
    "role": "석사과정", "domain": "추천시스템", "research_topics": ["그래프 기반 콜드스타트 완화"],
    "problems": ["신규 사용자 콜드스타트"], "methods": ["GNN", "LightGCN"],
    "keywords": ["graph cold start recommendation", "LightGCN", "GNN recommender"],
    "summary": "그래프 기반 추천의 콜드스타트를 연구하는 석사과정",
}


def test_builder_with_model_grounds_computed_fields(souls, monkeypatch):
    _seed(souls)
    monkeypatch.setattr(turn_runner, "create_chat_completion", lambda client, **kw: _reply(json.dumps(MODEL_PROFILE)))
    built = asyncio.run(profile_mod.build_research_profile(souls.get_soul("alice", "inc-a")))
    assert {k: built[k] for k in ("role", "domain", "methods", "keywords", "summary")} == {
        k: MODEL_PROFILE[k] for k in ("role", "domain", "methods", "keywords", "summary")}
    assert [i["label"] for i in built["interests"]] == ["그래프 기반 추천", "에이전트 장기 기억"]
    assert built["interests"][0]["weight"] == 1.0 and 0 < built["interests"][1]["weight"] < 1
    assert built["recent_papers"] == ["LightGCN"] and built["preferences"] == {"answer_length": "short"}


def test_builder_never_fills_unsupported_fields(souls, monkeypatch):
    souls.add_memories("alice", "inc-a", [{"kind": "topic", "text": "GraphRAG"}], None)  # only a searched topic
    invented = {**MODEL_PROFILE, "role": "교수", "methods": ["invented"]}
    monkeypatch.setattr(turn_runner, "create_chat_completion", lambda client, **kw: _reply(json.dumps(invented)))
    built = asyncio.run(profile_mod.build_research_profile(souls.get_soul("alice", "inc-a")))
    assert built["role"] is None and built["domain"] is None and built["methods"] == []  # no facts/research
    assert built["keywords"] == MODEL_PROFILE["keywords"]  # a topic supports keywords


def test_builder_fallback_when_model_fails(souls, monkeypatch):
    _seed(souls)

    def broken(client, **kw):
        raise RuntimeError("model down")

    monkeypatch.setattr(turn_runner, "create_chat_completion", broken)
    built = asyncio.run(profile_mod.build_research_profile(souls.get_soul("alice", "inc-a")))
    assert built["role"] == "석사과정" and built["domain"] == "추천시스템"
    assert built["keywords"][:2] == ["그래프 기반 추천", "에이전트 장기 기억"] and "graph cold start" in built["keywords"]
    assert built["research_topics"] == ["추천시스템에서 그래프 기반 콜드스타트 완화를 연구 중"]
    assert built["summary"] == "추천시스템 석사과정, 그래프 기반 추천, 에이전트 장기 기억에 관심"


def test_profile_cache_rebuilds_on_soul_change_and_age(souls, monkeypatch):
    _seed(souls)
    calls = []
    monkeypatch.setattr(turn_runner, "create_chat_completion",
                        lambda client, **kw: calls.append(1) or _reply(json.dumps(MODEL_PROFILE)))
    get = profile_mod.get_research_profile
    first = asyncio.run(get("alice", "inc-a"))
    assert len(calls) == 1 and first["source_hash"] == profile_mod.source_hash(souls.get_soul("alice", "inc-a"))
    asyncio.run(get("alice", "inc-a"))
    assert len(calls) == 1  # cached: same soul, fresh
    souls.add_memories("alice", "inc-a", [{"kind": "interest", "text": "그래프 기반 추천"}], None)  # a hit changes the hash
    asyncio.run(get("alice", "inc-a"))
    assert len(calls) == 2
    stale = souls.get_profile("alice", "inc-a")
    with souls._lock:
        conn = souls._connect()
        conn.execute("UPDATE research_profiles SET updated_at = ?",
                     ((datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),))
        conn.commit()
        conn.close()
    assert stale["profile"]
    asyncio.run(get("alice", "inc-a"))
    assert len(calls) == 3  # older than 24 h
    asyncio.run(get("alice", "inc-a", refresh=True))
    assert len(calls) == 4
    assert asyncio.run(get("nobody", "inc-x")) is None  # no soul yet


def test_memory_block_header_and_prompt_rule(souls):
    _seed(souls)
    souls.save_profile("alice", "inc-a", {**MODEL_PROFILE, "interests": [{"label": "그래프 기반 추천", "weight": 1.0}]},
                       "h")
    block = turn_runner.build_memory_block(ALICE, "질문")
    assert block.startswith("연구 프로필: 그래프 기반 추천의 콜드스타트를 연구하는 석사과정 · 역할 석사과정 · 분야 추천시스템"
                            " · 관심 그래프 기반 추천\n\n# USER.md")
    for prompt in (turn_runner._SEARCH_SUMMARY_PROMPT, turn_runner._EXPLAIN_PROMPT, turn_runner._COMPARE_PROMPT,
                   tools._BOOKMARK_ANSWER_PROMPT):
        assert "'내 연구와의 연결' 한 문장" in prompt and "프로필에 없는 사실은 말하지 마세요" in prompt


def test_profile_keyword_only_for_generic_asks():
    profile = {"keywords": ["graph cold start recommendation", "LightGCN"]}
    pq = turn_runner.profile_query
    assert pq("최근 동향", "최근 동향 알려줘", profile) == "최근 동향 graph cold start recommendation"
    assert pq("논문", "읽을 만한 논문 추천해줘", profile) == "논문 graph cold start recommendation"
    assert pq("graph cold start recommendation 최근", "그거 최근 동향", profile).endswith("LightGCN")  # skip present
    assert pq("GraphRAG 평가", "GraphRAG 평가 방법이 뭐야?", profile) == "GraphRAG 평가"  # specific: unchanged
    assert pq("최근 동향", "최근 동향 알려줘", None) == "최근 동향"


def test_recommendations_use_profile_terms_and_reasons(env, tmp_path):  # noqa: F811
    records = [
        {"title": f"Graph retrieval study {i}", "abstract": "Graph retrieval networks", "doi": f"10.1234/g{i}",
         "publication_date": "2025-01-01", "authors": ["A"]} for i in range(4)
    ] + [
        {"title": f"LightGCN cold start recommendation {i}", "abstract": "cold start recommendation with LightGCN",
         "doi": f"10.1234/l{i}", "publication_date": "2024-01-01", "authors": ["B"]} for i in range(2)
    ]
    snapshot(env, records)
    souls_db = SoulDB(tmp_path / "souls.db")
    souls_db.save_profile("alice", env["alice"], {
        "interests": [{"label": "cold start", "weight": 1.0}], "keywords": ["LightGCN"]}, "h")
    assert read_profile_readonly(tmp_path / "souls.db", "alice", env["alice"])["keywords"] == ["LightGCN"]

    generate(env, souls_db=tmp_path / "souls.db", profile_fetch=lambda keyword, deadline: [])  # no network
    items = delivery(env)["items"]
    assert items[0]["title"].startswith("LightGCN cold start recommendation")
    assert items[0]["reason"].startswith("연구 프로필: cold start · ")
    assert items[0]["score_breakdown"]["research_profile"] == 1.0
    assert not any(i["reason"].startswith("연구 프로필") for i in items if i["title"].startswith("Graph retrieval"))


def test_recommendation_profile_flag_off(env, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("RECOMMEND_USE_PROFILE", "0")
    snapshot(env)
    souls_db = SoulDB(tmp_path / "souls.db")
    souls_db.save_profile("alice", env["alice"], {"interests": [{"label": "graph", "weight": 1.0}]}, "h")
    fetched = []
    generate(env, souls_db=tmp_path / "souls.db",
             profile_fetch=lambda keyword, deadline: fetched.append(keyword) or [])
    assert fetched == []  # flag off: no profile-keyword collection either
    assert delivery(env)["items"] and not any(i["reason"].startswith("연구 프로필") for i in delivery(env)["items"])


def test_readonly_profile_reader_tolerates_missing_files(tmp_path):
    assert read_profile_readonly(tmp_path / "absent.db", "alice", "inc") is None
    SoulDB(tmp_path / "s.db")
    assert read_profile_readonly(tmp_path / "s.db", "alice", "inc") is None


def test_export_script_and_deletion_cascade(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("export_rp", "scripts/export_research_profiles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    db = SoulDB(tmp_path / "souls.db")
    db.save_profile("alice", "inc-a", {"summary": "s", "source_hash": "h"}, "h")
    db.add_memories("bob", "inc-b", [{"kind": "interest", "text": "GraphRAG 평가"}], None)  # soul, no profile
    out = tmp_path / "profiles.jsonl"
    assert module.export_profiles(tmp_path / "souls.db", out) == 1
    assert module.export_profiles(tmp_path / "souls.db", out, build_missing=True) == 2
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [(r["username"], r["account_incarnation"]) for r in lines] == [("alice", "inc-a"), ("bob", "inc-b")]
    assert lines[1]["profile"]["interests"][0]["label"] == "GraphRAG 평가" and lines[1]["profile"]["source_hash"]

    db.clear("alice", "inc-a")
    assert db.get_profile("alice", "inc-a") is None
    db.save_profile("bob", "inc-b", {"summary": "s"}, "h")
    assert db.delete_by_username("bob") >= 2 and db.get_profile("bob", "inc-b") is None


def test_research_profile_route(souls, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import soul as soul_router
    from routers.deps.auth import get_authenticated_principal

    app = FastAPI()
    app.include_router(soul_router.profile_router)
    anonymous = TestClient(app)
    assert anonymous.get("/api/me/research-profile").status_code == 401
    app.dependency_overrides[get_authenticated_principal] = lambda: ALICE
    client = TestClient(app)
    assert client.get("/api/me/research-profile").json() == {"profile": None}
    souls.add_memories("alice", "inc-a", [{"kind": "interest", "text": "GraphRAG 평가"}], None)
    monkeypatch.setattr(turn_runner, "create_chat_completion", lambda client, **kw: _reply("{}"))
    body = client.get("/api/me/research-profile").json()
    assert body["profile"]["interests"] == [{"label": "GraphRAG 평가", "weight": 1.0}]



def test_remember_turn_rebuilds_the_profile(souls, monkeypatch):
    from contextlib import contextmanager

    class Users:
        @contextmanager
        def account_guard(self, username, incarnation):
            yield {}

    monkeypatch.setattr(storage, "_get_user_db", lambda: Users())
    replies = {"extract": '{"items": [], "query_interests": ["그래프 기반 추천"]}', "profile": json.dumps(MODEL_PROFILE)}
    monkeypatch.setattr(turn_runner, "create_chat_completion", lambda client, **kw: _reply(
        replies["profile"] if kw["messages"][0]["content"] == profile_mod._PROFILE_PROMPT else replies["extract"]))
    blocks = [{"type": "search_results", "query": "graph cold start"}]
    asyncio.run(turn_runner.remember_turn(ALICE, "c1", "콜드스타트 논문", blocks))
    saved = souls.get_profile("alice", "inc-a")
    assert saved["profile"]["summary"] == MODEL_PROFILE["summary"]
    assert saved["source_hash"] == profile_mod.source_hash(souls.get_soul("alice", "inc-a"))


# ── profile-keyword candidate collection ───────────────────────────────

def _arxiv(i, keyword, date="2026-09-01"):
    return {"title": f"{keyword} advances {i}", "abstract": f"We study {keyword} for recommendation.",
            "authors": ["A. Author"], "url": f"http://arxiv.org/abs/2609.0{i:04d}v1",
            "pdf_url": f"http://arxiv.org/pdf/2609.0{i:04d}v1", "published_date": date,
            "arxiv_id": f"2609.0{i:04d}v1", "categories": ["cs.IR"], "doi": ""}


def test_profile_keywords_prefer_heavy_english_labels():
    from src import daily_recommendations as daily

    research = {"interests": [{"label": "그래프 기반 추천", "weight": 1.0}, {"label": "GraphRAG evaluation", "weight": 0.4},
                              {"label": "cold start", "weight": 0.9}],
                "keywords": ["LightGCN", "cold start", "graph neural recommendation"]}
    assert daily.profile_keywords(research) == ["cold start", "GraphRAG evaluation", "LightGCN"]
    assert daily.profile_keywords(None) == [] and daily.profile_keywords({}) == []


def test_fetch_profile_candidates_bounds_and_filters():
    from src import daily_recommendations as daily

    calls = []

    def fetch(keyword, deadline):
        calls.append(keyword)
        if keyword == "broken":
            raise TimeoutError
        base = 100 * len(calls)  # distinct ids per keyword
        return [_arxiv(base + i, keyword) for i in range(25)] + [_arxiv(base + 99, keyword, date="2023-01-01")]

    raws, keyword_of = daily.fetch_profile_candidates(
        ["broken", "cold start", "LightGCN"], now=NOW, deadline=float("inf"), monotonic=lambda: 0.0, fetch=fetch)
    assert calls == ["broken", "cold start", "LightGCN"]  # a failing keyword is skipped, not fatal
    assert len(raws) == daily.MAX_PROFILE_CANDIDATES == 30
    assert all(raw["publication_date"] >= "2025" for raw in raws)
    assert set(keyword_of.values()) == {"cold start", "LightGCN"} and len(keyword_of) == 30

    raws, _ = daily.fetch_profile_candidates(["x"], now=NOW, deadline=0.0, monotonic=lambda: 1.0, fetch=fetch)
    assert raws == []  # past the run's network budget: nothing fetched


def test_profile_candidates_enter_the_pool_and_get_tagged(env, tmp_path):  # noqa: F811
    snapshot(env)  # the public pool: generic graph retrieval papers
    souls_db = SoulDB(tmp_path / "souls.db")
    souls_db.save_profile("alice", env["alice"], {"interests": [{"label": "cold start", "weight": 1.0}]}, "h")
    asked = []

    def fetch(keyword, deadline):
        asked.append(keyword)
        return [_arxiv(i, keyword) for i in range(3)]

    generate(env, souls_db=tmp_path / "souls.db", profile_fetch=fetch)
    assert asked == ["cold start"]
    items = delivery(env)["items"]
    fetched = [i for i in items if i["title"].startswith("cold start advances")]
    assert fetched and fetched[0]["final_rank"] == 1
    assert fetched[0]["reason"].startswith("연구 프로필: cold start · 최근 arXiv · ")
    assert fetched[0]["candidate_sources"] == ["owner_local"]
    # Private to alice: bob's run never sees alice's profile candidates.
    generate(env, souls_db=tmp_path / "souls.db", profile_fetch=fetch, usernames=["bob"])
    assert not any(i["title"].startswith("cold start advances") for i in delivery(env, env["bob"])["items"])


def test_language_preference_needs_an_answer_language_request():
    def prefs(*texts):
        soul = {"memories": [{"kind": "preference", "text": t} for t in texts]}
        return profile_mod._preferences(soul)

    assert prefs("논문 제목은 영어 그대로 두고 설명해달라") == {}
    assert prefs("앞으로 영어로 답해줘") == {"language": "en"}
    assert prefs("Always answer in English") == {"language": "en"}
    assert prefs("항상 한국어로 설명해줘", "답은 짧게") == {"answer_length": "short", "language": "ko"}
