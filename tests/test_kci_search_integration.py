"""KCI integration audit: real SQLite, collector, ranker and HTTP publication.

External transports/LLM are controlled; production data is never opened.
Originally failing assertions are retained after the retrieval-boundary fixes.
The pre-change failures are recorded in artifacts/spectrag-retrieval-review.
"""

import asyncio
import os
import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from app.SearchAgent.search_agent import SearchAgent
from routers import search as rs
from src.collector.paper import kci_searcher as kci
from src.collector.paper.deduplicator import PaperDeduplicator
from src.collector.paper.openalex_searcher import OpenAlexSearcher
from src.graph_rag.hybrid_ranker import HybridRanker

_READ_CACHE = rs._get_cached_result
_WRITE_CACHE = rs._set_cache


@pytest.fixture
def corpus(isolate_private_app_storage):
    path = Path(os.environ["KCI_DB_PATH"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(kci._SCHEMA)

    def insert(identifier=1, *, title="그래프 신경망 연구", year="2025",
               abstract="그래프 신경망을 활용한 추천 시스템", authors="홍길동",
               doi="10.1234/kci.graph"):
        with sqlite3.connect(path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kci(rowid,title,title_en,abstract,abstract_en,"
                "authors,venue,year,doi,url,citations) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (identifier, title, "GraphRAG neural network", abstract, "Graph retrieval",
                 authors, "정보과학회논문지", year, doi,
                 f"https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART{identifier:09d}", 3),
            )
    insert()
    return path, insert


@pytest.fixture
def runtime(corpus, monkeypatch, tmp_path):
    monkeypatch.setenv("KCI_RETRIEVAL_MODE", "baseline")
    agent = SearchAgent.__new__(SearchAgent)
    agent.search_history = []
    agent.deduplicator = PaperDeduplicator()
    agent.similarity_calculator = None
    provider = agent.openalex_searcher = OpenAlexSearcher()
    provider.session.close()
    provider.session = MagicMock()
    provider.session.get.return_value.json.return_value = {"results": []}
    monkeypatch.setattr(provider, "_rate_limit", lambda: None)
    analyzer = MagicMock()
    analyzer.analyze_and_prepare.return_value = {
        "is_academic": True, "confidence": 0.5, "intent": "paper_search",
    }
    monkeypatch.setattr(rs, "search_agent", agent)
    monkeypatch.setattr(rs, "query_analyzer", analyzer)
    monkeypatch.setattr(rs, "_hybrid_ranker", HybridRanker())
    monkeypatch.setattr(rs, "_RANKER_DEGRADATION_REASONS", [])
    monkeypatch.setattr(rs, "_router_shutdown", threading.Event())
    monkeypatch.setattr(rs, "_router_operation_owner", SearchAgent.__new__(SearchAgent))
    monkeypatch.setattr(rs, "_get_cached_result", lambda *a, **kw: None)
    monkeypatch.setattr(rs, "_set_cache", MagicMock())
    monkeypatch.setattr(rs, "_persist_last_search", MagicMock())
    monkeypatch.setattr(rs, "_graphrag_expand", lambda *a, **kw: [])
    monkeypatch.setattr(rs, "get_openai_client", lambda: None)
    monkeypatch.setattr(rs, "SEARCH_CACHE_DIR", tmp_path / "search-cache")
    rs.SEARCH_CACHE_DIR.mkdir()
    monkeypatch.setattr(rs, "_search_cache", {})
    return agent


@pytest.fixture
def cached_runtime(runtime, monkeypatch):
    monkeypatch.setattr(rs, "_get_cached_result", _READ_CACHE)
    monkeypatch.setattr(rs, "_set_cache", _WRITE_CACHE)
    return runtime


async def search(client, headers, **overrides):
    request = dict(query="그래프 신경망", sources=["openalex_korean"],
                   max_results=10, fast_mode=True, save_papers=False)
    request.update(overrides)
    response = await client.post("/api/search", json=request, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("fast_mode", [True, False])
async def test_kci_reaches_authenticated_http_response_with_real_ranking(runtime, client, auth_headers, monkeypatch, fast_mode):
    from app.QueryAgent.relevance_filter import LocalRelevanceScorer

    monkeypatch.setattr(LocalRelevanceScorer, "score_papers", lambda query, papers: [0.8] * len(papers))

    async def no_external_rerank(query, papers, **kwargs):
        return papers, {"mode": "disabled_no_api_key"}

    monkeypatch.setattr(rs, "rerank_papers", no_external_rerank)
    body = await search(client, auth_headers, fast_mode=fast_mode)
    assert body["total"] == 1
    paper = body["results"]["openalex_korean"][0]
    assert paper["source"] == "KCI"
    assert paper["result_key"] == "doi:10.1234/kci.graph"
    assert paper["venue"] == "정보과학회논문지"
    assert paper["authors"] == ["홍길동"]
    assert paper["_rank"] == 0
    assert "_hybrid_score" in paper
    assert body["stage_modes"]["ranking_mode"] == ("cheap_rrf" if fast_mode else "hybrid_rrf")


@pytest.mark.asyncio
async def test_full_kci_bucket_avoids_external_transport(runtime, client, auth_headers):
    body = await search(client, auth_headers, max_results=1)
    assert body["total"] == 1
    runtime.openalex_searcher.session.get.assert_not_called()


@pytest.mark.asyncio
async def test_spectral_mode_runs_inside_real_kci_http_pipeline(runtime, corpus, client, auth_headers, monkeypatch):
    monkeypatch.setenv("KCI_RETRIEVAL_MODE", "spectral")
    for i in range(2, 10):
        corpus[1](i, title=f"그래프 신경망 활용 개념{i}", doi=f"10.1234/spectral-{i}")
    body = await search(client, auth_headers, max_results=3)
    papers = body["results"]["openalex_korean"]
    assert len(papers) == 3
    assert all("_retrieval_score" in p for p in papers)
    assert all(p["source"] == "KCI" for p in papers)
    assert sorted(p["_rank"] for p in papers) == [0, 1, 2]
    runtime.openalex_searcher.session.get.assert_not_called()


@pytest.mark.asyncio
async def test_translation_keeps_korean_query_for_kci(runtime, client, auth_headers):
    rs.query_analyzer.analyze_and_prepare.return_value.update(
        confidence=0.95, improved_query="graph neural network",
        source_queries={"default": "graph neural network"},
    )
    body = await search(client, auth_headers)
    assert body["total"] == 1
    assert body["results"]["openalex_korean"][0]["source"] == "KCI"


@pytest.mark.asyncio
async def test_english_expansion_keeps_original_query_for_local_kci(runtime, client, auth_headers):
    rs.query_analyzer.analyze_and_prepare.return_value.update(
        confidence=0.95, improved_query="unrelated broad terminology",
        source_queries={"default": "unrelated broad terminology"},
    )
    body = await search(client, auth_headers, query="GraphRAG")
    assert body["total"] == 1
    assert body["results"]["openalex_korean"][0]["source"] == "KCI"
    assert body["metadata"]["executed_queries"]["openalex_korean"] == ["GraphRAG"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [requests.HTTPError("503"), requests.Timeout("expired")])
async def test_prompt_transport_failure_keeps_kci_results(runtime, client, auth_headers, failure):
    runtime.openalex_searcher.session.get.side_effect = failure
    body = await search(client, auth_headers)
    assert body["total"] == 1
    assert body["results"]["openalex_korean"][0]["source"] == "KCI"
    assert body["metadata"]["partial"] is True


@pytest.mark.asyncio
async def test_same_doi_from_openalex_and_kci_is_merged(runtime, client, auth_headers):
    runtime.openalex_searcher.session.get.return_value.json.return_value = {
        "results": [{"id": "https://openalex.org/W1", "display_name": "Graph neural networks",
                     "doi": "https://doi.org/10.1234/kci.graph", "publication_year": 2025}],
    }
    body = await search(client, auth_headers, sources=["openalex", "openalex_korean"])
    papers = [p for values in body["results"].values() for p in values]
    assert len(papers) == 1
    assert papers[0]["result_key"] == "doi:10.1234/kci.graph"
    assert "KCI" in papers[0]["_found_in_sources"]
    assert "OpenAlex" in papers[0]["_found_in_sources"]


@pytest.mark.asyncio
async def test_warm_cache_preserves_kci_identity_and_rank(cached_runtime, client, auth_headers):
    first = await search(client, auth_headers)
    assert first["cache_hit"] is False
    cached_runtime.openalex_searcher.session.get.reset_mock()
    second = await search(client, auth_headers)
    assert second["cache_hit"] is True
    for field in ("source", "result_key", "_rank", "venue"):
        assert second["results"]["openalex_korean"][0][field] == first["results"]["openalex_korean"][0][field]
    cached_runtime.openalex_searcher.session.get.assert_not_called()


@pytest.mark.asyncio
async def test_new_kci_record_invalidates_cached_search(cached_runtime, corpus, client, auth_headers):
    first = await search(client, auth_headers)
    assert first["total"] == 1
    corpus[1](2, title="그래프 신경망의 새로운 응용", doi="10.1234/new-record")
    assert len(kci.search_kci("그래프 신경망", 10)) == 2
    second = await search(client, auth_headers)
    assert second["total"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["GraphRAG", "10.1234/kci.graph", '"그래프 신경망 연구"'])
async def test_kci_available_for_all_supported_query_routes(runtime, corpus, client, auth_headers, query):
    assert kci.search_kci("그래프 신경망", 10, corpus[0])
    body = await search(client, auth_headers, query=query)
    assert body["total"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("filters", [{"year_start": 2025}, {"author": "김철수"}])
async def test_filters_select_matching_candidates_before_cap(runtime, corpus, client, auth_headers, filters):
    _, insert = corpus
    insert(1, title="그래프 그래프 그래프", year="2000", authors="홍길동")
    insert(2, title="다른 제목", abstract="그래프 " + "설명 " * 100,
           authors="김철수", year="2026", doi="10.1234/recent")
    assert len(kci.search_kci("그래프", 10)) == 2
    assert kci.search_kci("그래프", 1)[0]["year"] == "2000"
    body = await search(client, auth_headers, query="그래프", max_results=1, **filters)
    assert body["total"] == 1
    assert body["results"]["openalex_korean"][0]["doi"] == "10.1234/recent"


@pytest.mark.asyncio
async def test_latest_sort_uses_kci_year(runtime, corpus, client, auth_headers):
    corpus[1](1, year="2000", doi="10.1234/a-old")
    corpus[1](2, title="그래프 최신 동향", year="2026", doi="10.1234/z-new")
    body = await search(client, auth_headers, sort_by="submittedDate")
    assert body["total"] == 2
    assert [p["year"] for p in body["results"]["openalex_korean"]] == ["2026", "2000"]


@pytest.mark.asyncio
async def test_all_term_match_survives_candidate_expansion(runtime, corpus, client, auth_headers):
    insert = corpus[1]
    insert(1, title="전체 일치", abstract="희귀단어 특수단어 " + "설명 " * 1000)
    insert(2, title="희귀단어 희귀단어 희귀단어", abstract="", doi="10.1234/partial-a")
    insert(3, title="특수단어 특수단어 특수단어", abstract="", doi="10.1234/partial-b")
    body = await search(client, auth_headers, query="희귀단어 특수단어", max_results=2)
    assert body["total"] == 2
    assert any(p["title"] == "전체 일치" for p in body["results"]["openalex_korean"])


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["collector", "http"])
async def test_deadline_preserves_already_retrieved_kci(runtime, client, auth_headers, monkeypatch, boundary):
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()

    def slow_transport(*args, **kwargs):
        entered.set()
        try:
            assert release.wait(3), "test failed to release controlled transport"
            raise requests.Timeout("controlled deadline")
        finally:
            exited.set()

    runtime.openalex_searcher.session.get.side_effect = slow_transport
    metadata = {}
    if boundary == "collector":
        task = asyncio.create_task(runtime.async_search_with_filters("그래프 신경망", {
            "sources": ["openalex_korean"], "max_results": 10,
            "_deadline": time.monotonic() + 0.5, "_metadata": metadata,
        }))
    else:
        monkeypatch.setattr(rs, "_SOURCE_SEARCH_TIMEOUT", 0.5)
        task = asyncio.create_task(search(client, auth_headers))
    try:
        assert await asyncio.to_thread(entered.wait, 2), "external fallback did not start"
        result = await asyncio.wait_for(task, 2)
        if boundary == "collector":
            assert metadata["modes"]["openalex_korean"] == "partial_timeout"
            assert len(result["openalex_korean"]) == 1
        else:
            assert result["metadata"]["partial"] is True
            assert result["total"] == 1
    finally:
        release.set()
        await asyncio.to_thread(exited.wait, 2)
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "broken"])
async def test_index_unavailability_is_visible_in_api(runtime, corpus, client, auth_headers, state):
    path = corpus[0]
    path.unlink()
    if state == "broken":
        path.write_bytes(b"invalid sqlite database")
    body = await search(client, auth_headers)
    assert body["total"] == 0
    assert body["metadata"]["partial"] or body.get("degraded")


@pytest.mark.asyncio
async def test_doi_less_kci_exposes_stable_provider_identity(runtime, corpus, client, auth_headers):
    corpus[1](doi="")
    body = await search(client, auth_headers)
    paper = body["results"]["openalex_korean"][0]
    assert paper.get("kci_id") or paper.get("id") or paper.get("paper_id")


@pytest.mark.asyncio
async def test_react_search_includes_local_kci_without_remote_results(runtime, monkeypatch):
    from unittest.mock import AsyncMock
    from app.SearchAgent.react_search_agent import ReActSearchAgent

    agent = ReActSearchAgent(runtime, max_turns=1)
    monkeypatch.setattr(agent, "_keyword_search", AsyncMock(return_value=[]))
    monkeypatch.setattr(agent, "_semantic_search", AsyncMock(return_value=[]))
    result = await agent.search("GraphRAG", max_results=10)
    assert len(result["papers"]) == 1
    assert result["papers"][0]["source"] == "KCI"
    assert result["turn_history"][0].tool_calls[0]["tool"] == "kci_search"
