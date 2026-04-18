"""
Search-related endpoints:
  POST /api/search
  POST /api/smart-search
  POST /api/analyze-query
  POST /api/llm-search
  POST /api/prefetch-popular  (admin)
"""

import asyncio
import collections
import copy
import hashlib
import json
import logging
import re
import threading
import time
import traceback
import unicodedata
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .deps import (
    get_openai_client,
    get_optional_user,
    query_analyzer,
    relevance_filter,
    search_agent,
)

# HybridRanker (optional) - search_agent의 similarity_calculator 재사용
try:
    from graph_rag.hybrid_ranker import HybridRanker
    _hybrid_ranker = HybridRanker(similarity_calculator=search_agent.similarity_calculator)
except Exception:
    _hybrid_ranker = None

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["search"])


# ── GraphRAG auxiliary recall ─────────────────────────────────────────

_GRAPH_PATH = Path("data/graph/paper_graph.pkl")

# ── Graph 메모리 캐시 (매 요청 pickle.load 방지) ──────────────────
_cached_graph = None
_cached_graph_mtime: float = 0.0
_graph_cache_lock = threading.Lock()


def _load_graph_cached():
    """Graph를 메모리에 캐시하고 파일 변경 시에만 재로드."""
    global _cached_graph, _cached_graph_mtime
    import pickle

    if not _GRAPH_PATH.exists():
        return None

    try:
        current_mtime = _GRAPH_PATH.stat().st_mtime
    except OSError:
        return _cached_graph

    if _cached_graph is not None and current_mtime == _cached_graph_mtime:
        return _cached_graph

    with _graph_cache_lock:
        # Double-check after lock
        if _cached_graph is not None and current_mtime == _cached_graph_mtime:
            return _cached_graph
        try:
            with open(_GRAPH_PATH, "rb") as f:
                _cached_graph = pickle.load(f)
            _cached_graph_mtime = current_mtime
            logger.info("[GraphRAG] Graph loaded/refreshed: %d nodes", _cached_graph.number_of_nodes())
        except Exception as exc:
            logger.warning("[GraphRAG] Graph load failed: %s", exc)
    return _cached_graph


def _graphrag_expand(
    query: str,
    initial_papers: List[Dict[str, Any]],
    max_expand: int = 15,
) -> List[Dict[str, Any]]:
    """검색 결과의 논문들을 기반으로 GraphRAG hybrid_deep 확장.

    1-hop: SIMILAR_TO + CITES 모두, 2-hop: CITES만 (인용 기반 안전 탐색).
    기존 검색 결과의 title을 시드로 사용하여,
    그래프에서 이웃 논문을 추가로 가져온다.
    실패 시 빈 리스트 반환 (graceful degradation).
    """
    graph = _load_graph_cached()
    if graph is None:
        logger.debug("[GraphRAG] Graph file not found: %s", _GRAPH_PATH)
        return []

    from src.graph_rag.search_engine import SearchEngine

    engine = SearchEngine(
        graph,
        embeddings_index_path="data/embeddings/paper_embeddings.index",
        id_mapping_path="data/embeddings/paper_id_mapping.json",
    )

    # 기존 검색 결과의 title → graph node_id 매핑 (lowercase)
    seed_ids: List[str] = []
    existing_titles: set = set()
    for paper in initial_papers:
        title = paper.get("title", "")
        if title:
            node_id = title.strip().lower()
            existing_titles.add(node_id)
            if node_id in graph:
                seed_ids.append(node_id)

    if not seed_ids:
        # 시드가 없으면 키워드 fallback 시도
        fallback_ids = engine._keyword_fallback(query, top_k=max_expand)
        fallback_ids = [pid for pid in fallback_ids if pid not in existing_titles]
        if not fallback_ids:
            return []
        neighbor_ids = fallback_ids[:max_expand]
    else:
        # hybrid_deep 확장: 1-hop (SIMILAR_TO + CITES) + 2-hop (CITES만)
        expanded_ids = engine.expand_graph(
            seed_ids[:10],
            expansion_strategy="hybrid_deep",
            max_expanded=max_expand + len(seed_ids),
        )

        # 기존 검색 결과와 겹치는 논문 제외
        neighbor_ids_set = set(expanded_ids) - existing_titles - set(seed_ids)
        neighbor_ids = list(neighbor_ids_set)[:max_expand]

    if not neighbor_ids:
        return []

    # 그래프 노드 데이터를 검색 결과 형식으로 변환
    expanded: List[Dict[str, Any]] = []
    for nid in neighbor_ids:
        if nid not in graph:
            continue
        node_data = graph.nodes[nid]
        title = node_data.get("title", "")
        if not title:
            continue
        paper: Dict[str, Any] = {
            "title": title,
            "abstract": node_data.get("abstract", ""),
            "authors": node_data.get("authors", []),
            "url": node_data.get("url", ""),
            "pdf_url": node_data.get("pdf_url", ""),
            "source": "graphrag",
            "arxiv_id": node_data.get("arxiv_id", ""),
            "doi": node_data.get("doi", ""),
            "published_date": node_data.get("published_date", ""),
            "categories": node_data.get("categories", []),
            "citations": node_data.get("citations", 0),
            "year": node_data.get("year", ""),
        }
        expanded.append(paper)

    return expanded


# ── Pydantic models ───────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    max_results: int = 20
    sources: List[str] = ["arxiv", "connected_papers", "google_scholar", "openalex", "dblp", "openalex_korean"]
    sort_by: str = "relevance"
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    author: Optional[str] = None
    category: Optional[str] = None
    fast_mode: bool = False
    save_papers: bool = True
    collect_references: bool = False
    extract_texts: bool = False
    max_references_per_paper: int = 10
    use_llm_search: bool = False
    search_context: str = ""


class SearchResponse(BaseModel):
    results: Dict[str, List[Dict[str, Any]]]
    total: int
    query_analysis: Optional[Dict[str, Any]] = None


class QueryAnalysisRequest(BaseModel):
    query: str


class QueryAnalysisResponse(BaseModel):
    intent: str
    keywords: List[str]
    improved_query: str
    search_filters: Dict[str, Any]
    confidence: float
    original_query: str
    analysis_details: Optional[str] = None


class LLMSearchRequest(BaseModel):
    query: str
    max_results: int = 20
    context: str = ""
    save_papers: bool = True


class LLMSearchResponse(BaseModel):
    results: Dict[str, List[Dict[str, Any]]]
    total: int
    metadata: Dict[str, Any]


# ── Helper ─────────────────────────────────────────────────────────────

def _stamp_searched_by(results: Dict[str, List[Dict[str, Any]]], username: Optional[str]):
    """Add searched_by field to all papers in results."""
    stamp = username or "(unknown)"
    for papers in results.values():
        for paper in papers:
            paper["searched_by"] = stamp


def _enrich_papers_background(
    query: str,
    results: Dict[str, List[Dict[str, Any]]],
    collect_refs: bool,
    extract_text: bool,
    max_refs: int,
):
    """Background paper enrichment (save, refs, full-text)."""
    try:
        logger.info("[Background] Enrichment started...")

        save_result = search_agent.save_papers(
            results, query, generate_embeddings=False, update_graph=True
        )
        logger.info("[Background] Saved: %s new papers", save_result.get("new_papers", 0))

        # Pre-compute embeddings for ranking cache (speeds up future HyDE scoring)
        new_count = save_result.get("new_papers", 0)
        if new_count > 0 and hasattr(search_agent, 'similarity_calculator'):
            try:
                texts_to_embed = []
                for source_papers in results.values():
                    if not isinstance(source_papers, list):
                        continue
                    for paper in source_papers:
                        title = paper.get("title", "")
                        abstract = paper.get("abstract", "") or title
                        if title:
                            texts_to_embed.append(title)
                        if abstract and abstract != title:
                            texts_to_embed.append(abstract)
                if texts_to_embed:
                    search_agent.similarity_calculator.get_embeddings_batch(texts_to_embed[:200])
                    logger.info("[Background] Pre-computed %d embeddings for ranking cache", len(texts_to_embed[:200]))
            except Exception as emb_err:
                logger.warning("[Background] Embedding pre-cache failed (non-critical): %s", emb_err)

        new_papers_count = save_result.get("new_papers", 0)
        if collect_refs and new_papers_count > 0:
            max_papers_to_collect = min(new_papers_count, 10)
            logger.info("[Background] Collecting refs (max %s papers)...", max_papers_to_collect)
            ref_result = search_agent.collect_references(max_refs, max_papers_to_collect)
            logger.info("[Background] Refs collected: %s", ref_result.get("references_found", 0))

        if extract_text and save_result.get("new_papers", 0) > 0:
            logger.info("[Background] Extracting full texts...")
            text_result = search_agent.extract_full_texts(save_result.get("new_papers"))
            logger.info("[Background] Texts extracted: %s", text_result.get("texts_extracted", 0))

        logger.info("[Background] Enrichment done")
    except Exception as e:
        logger.exception("[Background] Enrichment error: %s", e)


# ── Search cache ──────────────────────────────────────────────────────
SEARCH_CACHE_DIR = Path("data/cache/search_cache")
SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_search_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()
CACHE_TTL_SECONDS = 3600  # 1시간
CACHE_MAX_SIZE = 200  # 최대 캐시 엔트리 수


_CACHE_STOPWORDS = frozenset({
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "is", "are", "and", "or", "but", "not", "this", "that", "these", "those",
})


def _normalize_query_for_cache(query: str) -> str:
    """캐시 키용 쿼리 정규화 (유니코드 + stopword + 공백)."""
    q = unicodedata.normalize("NFKC", query).strip().lower()
    q = re.sub(r"\s+", " ", q)
    tokens = [t for t in q.split() if t not in _CACHE_STOPWORDS]
    return " ".join(tokens)


def _compute_cache_key(query: str, sources: List[str], filters: Dict[str, Any]) -> str:
    """검색 요청에 대한 캐시 키 생성 (fast_mode 포함)"""
    key_data = {
        "query": _normalize_query_for_cache(query),
        "sources": sorted(sources),
        "year_start": filters.get("year_start"),
        "year_end": filters.get("year_end"),
        "author": filters.get("author"),
        "category": filters.get("category"),
        "sort_by": filters.get("sort_by", "relevance"),
        "fast_mode": filters.get("fast_mode", False),
    }
    key_str = json.dumps(key_data, sort_keys=True)
    return hashlib.sha256(key_str.encode()).hexdigest()[:16]


def _get_cached_result(cache_key: str) -> Optional[Dict[str, Any]]:
    """인메모리 → 파일 순서로 캐시 조회"""
    now = datetime.now()

    # 1. 인메모리 캐시
    with _cache_lock:
        if cache_key in _search_cache:
            entry = _search_cache[cache_key]
            if datetime.fromisoformat(entry["expires_at"]) > now:
                logger.debug("[Cache] HIT (memory): %s", cache_key)
                return entry["results"]
            else:
                del _search_cache[cache_key]

    # 2. 파일 캐시
    cache_file = SEARCH_CACHE_DIR / f"{cache_key}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                entry = json.load(f)
            if datetime.fromisoformat(entry["expires_at"]) > now:
                with _cache_lock:
                    _search_cache[cache_key] = entry
                logger.debug("[Cache] HIT (file): %s", cache_key)
                return entry["results"]
            else:
                cache_file.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("[Cache] File read error: %s", e)

    logger.debug("[Cache] MISS: %s", cache_key)
    return None


def _set_cache(cache_key: str, results: Dict[str, Any], ttl_seconds: int = CACHE_TTL_SECONDS):
    """인메모리 + 파일 캐시 저장 (크기 제한 + TTL 만료 정리)"""
    now = datetime.now()
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
    entry = {"results": results, "expires_at": expires_at, "cached_at": now.isoformat()}

    with _cache_lock:
        # 캐시 크기 초과 시 만료 엔트리 정리 + 가장 오래된 엔트리 제거
        if len(_search_cache) >= CACHE_MAX_SIZE:
            expired_keys = [
                k for k, v in _search_cache.items()
                if datetime.fromisoformat(v["expires_at"]) <= now
            ]
            for k in expired_keys:
                del _search_cache[k]
            # 여전히 초과하면 가장 오래된 엔트리 제거
            if len(_search_cache) >= CACHE_MAX_SIZE:
                oldest_key = min(_search_cache, key=lambda k: _search_cache[k]["cached_at"])
                del _search_cache[oldest_key]
        _search_cache[cache_key] = entry

    try:
        cache_file = SEARCH_CACHE_DIR / f"{cache_key}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False)
        logger.debug("[Cache] STORED: %s", cache_key)
    except Exception as e:
        logger.warning("[Cache] File write error: %s", e)


def _cleanup_expired_cache():
    """만료된 파일 캐시 정리 (서버 시작 시 및 주기적 실행)"""
    now = datetime.now()
    removed = 0
    try:
        for cache_file in SEARCH_CACHE_DIR.glob("*.json"):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    entry = json.load(f)
                expires_at = datetime.fromisoformat(entry.get("expires_at", "2000-01-01"))
                if expires_at <= now:
                    cache_file.unlink(missing_ok=True)
                    removed += 1
            except (json.JSONDecodeError, KeyError, ValueError):
                cache_file.unlink(missing_ok=True)
                removed += 1
            except Exception:
                pass
    except Exception as e:
        logger.warning("[Cache] Cleanup error: %s", e)
    if removed > 0:
        logger.info("[Cache] Cleanup: removed %d expired cache files", removed)


# 서버 시작 시 만료 캐시 정리
_cleanup_expired_cache()


def _periodic_cache_maintenance():
    """30분 주기 백그라운드 캐시 정리 + 빈도 데이터 저장"""
    while True:
        time.sleep(1800)
        try:
            _cleanup_expired_cache()
            _save_query_freq()
        except Exception as e:
            logger.warning("[Cache] Periodic cleanup error: %s", e)


_cache_maintenance_thread = threading.Thread(
    target=_periodic_cache_maintenance,
    daemon=True,
    name="cache-maintenance",
)
_cache_maintenance_thread.start()


# ── Popular query prefetching ──────────────────────────────────────
_POPULAR_QUERIES = [
    "transformer",
    "large language model",
    "reinforcement learning",
    "diffusion model",
    "graph neural network",
    "retrieval augmented generation",
    "computer vision",
    "natural language processing",
    "federated learning",
    "self-supervised learning",
    "multimodal learning",
    "knowledge graph",
    "attention mechanism",
    "generative adversarial network",
    "prompt engineering",
]

# ── 검색 빈도 카운터 ──────────────────────────────────────────────
_query_freq: collections.Counter = collections.Counter()
_query_freq_lock = threading.Lock()
_FREQ_FILE = Path("data/cache/query_freq.json")

_SEED_QUERIES = [
    "transformer", "large language model", "reinforcement learning",
    "diffusion model", "graph neural network", "retrieval augmented generation",
    "vision language model", "mixture of experts", "test-time compute",
    "agent", "reasoning", "alignment",
]


def _record_query(query: str) -> None:
    """검색 쿼리를 빈도 카운터에 기록."""
    normalized = _normalize_query_for_cache(query)
    with _query_freq_lock:
        _query_freq[normalized] += 1


def _get_popular_queries(top_k: int = 15) -> List[str]:
    """빈도 기반 인기 쿼리 목록 반환 (시드 쿼리로 보충)."""
    with _query_freq_lock:
        popular = [q for q, _ in _query_freq.most_common(top_k)]
    for seed in _SEED_QUERIES:
        if len(popular) >= top_k:
            break
        if seed not in popular:
            popular.append(seed)
    return popular[:top_k]


def _save_query_freq() -> None:
    """빈도 데이터를 JSON 파일로 저장."""
    try:
        with _query_freq_lock:
            data = dict(_query_freq.most_common(500))
        _FREQ_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_FREQ_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.warning("[QueryFreq] Save failed: %s", e)


def _load_query_freq() -> None:
    """파일에서 빈도 데이터 로드."""
    try:
        if _FREQ_FILE.exists():
            with open(_FREQ_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            with _query_freq_lock:
                _query_freq.update(data)
    except Exception:
        pass


_load_query_freq()


_prefetch_running = False


def _prefetch_popular_queries():
    """Background thread: periodically pre-fetches popular query results into cache."""
    global _prefetch_running
    import time as _time

    # Prevent overlapping cycles
    if _prefetch_running:
        logger.info("[Prefetch] Already running, skipping")
        return
    _prefetch_running = True

    try:
        # Wait for server startup to complete
        _time.sleep(30)

        while True:
            cycle_start = _time.time()
            popular = _get_popular_queries()
            logger.info("[Prefetch] Starting prefetch cycle (%d queries)...", len(popular))

            # arXiv/google_scholar excluded: global semaphore + rate limits block user searches
            default_sources = ["connected_papers", "openalex", "dblp", "openalex_korean"]

            fetched = 0
            for query in popular:
                try:
                    cache_key = _compute_cache_key(query, default_sources, {"sort_by": "relevance", "year_start": None, "year_end": None, "author": None, "category": None, "fast_mode": False})
                    if _get_cached_result(cache_key) is not None:
                        logger.debug("[Prefetch] Cache hit for '%s', skipping", query)
                        continue

                    filters = {
                        "sources": default_sources,
                        "max_results": 20,
                        "sort_by": "relevance",
                    }
                    results = search_agent.search_with_filters(query, filters)

                    if results:
                        total = sum(len(papers) for papers in results.values())
                        _set_cache(cache_key, results, ttl_seconds=3600)  # 1 hour TTL (matches default)
                        logger.info("[Prefetch] Cached '%s': %d papers", query, total)
                        fetched += 1

                    # Respect rate limits between queries
                    _time.sleep(5)

                except Exception as e:
                    logger.warning("[Prefetch] Failed for '%s': %s", query, e)
                    _time.sleep(5)

            cycle_duration = _time.time() - cycle_start
            logger.info("[Prefetch] Cycle complete: %d/%d queries prefetched (%.0fs)", fetched, len(popular), cycle_duration)

            # Sleep until next cycle (45 minutes), accounting for actual cycle time
            next_sleep = max(0, 2700 - cycle_duration)
            _time.sleep(next_sleep)
    finally:
        _prefetch_running = False


# Start prefetch in background thread on module load
_prefetch_thread = threading.Thread(
    target=_prefetch_popular_queries,
    daemon=True,
    name="query-prefetch",
)
_prefetch_thread.start()


# ── Endpoints ──────────────────────────────────────────────────────────

# Endpoint-level timeout constants (seconds)
_ANALYZE_TIMEOUT = 15
_LLM_SEARCH_TIMEOUT = 60
_SMART_SEARCH_TIMEOUT = 60
_SEARCH_TIMEOUT = 100           # 전체 검색 파이프라인 (분석+검색+랭킹+필터)
_SOURCE_SEARCH_TIMEOUT = 40     # 멀티소스 검색 단계만
_RELEVANCE_FILTER_TIMEOUT = 30  # LLM 관련성 필터 단계만
_GRAPHRAG_TIMEOUT = 5           # GraphRAG 확장
_RANKING_TIMEOUT = 25           # HyDE + hybrid ranking
_MIN_BUDGET_FOR_GRAPHRAG = 18
_MIN_BUDGET_FOR_RANKING = 12
_MIN_BUDGET_FOR_HYDE_HARD = 28
_RELEVANCE_FILTER_TOP_N = 30
_MIN_BUDGET_FOR_RELEVANCE = 10
_MAX_RANKING_CANDIDATES = 80


def _remaining_budget(start_time: float, total_budget: int = _SEARCH_TIMEOUT) -> float:
    """Return remaining wall-clock budget for the current search request."""
    return max(0.0, total_budget - (time.time() - start_time))


def _ranking_candidate_cap(max_results: int) -> int:
    """Bound ranking input size while keeping enough recall for later stages."""
    return min(max(max_results * 2, 40), _MAX_RANKING_CANDIDATES)


def _paper_identity(paper: Dict[str, Any]) -> str:
    """Stable paper identity for dedup/filter recomposition."""
    doi = (paper.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    arxiv_id = (paper.get("arxiv_id") or "").strip().lower()
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    title = (paper.get("title") or "").strip().lower()
    if title:
        return f"title:{title}"
    return f"fallback:{hashlib.sha256(json.dumps(paper, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]}"


def _interleave_source_candidates(
    results: Dict[str, List[Dict[str, Any]]],
    source_keys: List[str],
    limit: int,
) -> List[Dict[str, Any]]:
    """Preserve source diversity when capping ranking candidates."""
    queues = {source: list(results.get(source, [])) for source in source_keys}
    merged: List[Dict[str, Any]] = []

    while len(merged) < limit:
        progressed = False
        for source in source_keys:
            queue = queues.get(source, [])
            if not queue:
                continue
            merged.append(queue.pop(0))
            progressed = True
            if len(merged) >= limit:
                break
        if not progressed:
            break

    return merged


def _rebuild_results_from_ranked(
    ranked_papers: List[Dict[str, Any]],
    source_keys: List[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """Rebuild source buckets from a globally ranked paper list."""
    rebuilt = {source: [] for source in source_keys}
    for paper in ranked_papers:
        source = (
            paper.get("_result_source")
            or paper.get("source")
            or paper.get("_source_tag")
            or "arxiv"
        )
        if source in rebuilt:
            rebuilt[source].append(paper)
    return rebuilt


@router.post("/analyze-query", response_model=QueryAnalysisResponse)
async def analyze_query(request: QueryAnalysisRequest):
    """Analyze user query to understand intent and extract keywords."""
    if not query_analyzer:
        raise HTTPException(
            status_code=503,
            detail="Query analysis service unavailable (OpenAI API key not configured)",
        )

    try:
        logger.info("[API] Analyzing query: %s", request.query)
        loop = asyncio.get_running_loop()
        analysis = await asyncio.wait_for(
            loop.run_in_executor(None, partial(query_analyzer.analyze_query, request.query)),
            timeout=_ANALYZE_TIMEOUT,
        )
        logger.info("[API] Analysis result: intent=%s, confidence=%s", analysis.get("intent"), analysis.get("confidence"))
        return QueryAnalysisResponse(**analysis)
    except asyncio.TimeoutError:
        logger.error("[API] Query analysis timed out after %ds", _ANALYZE_TIMEOUT)
        raise HTTPException(status_code=504, detail=f"Query analysis timed out after {_ANALYZE_TIMEOUT}s")
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("[API] Error in query analysis: %s", error_trace)
        raise HTTPException(status_code=500, detail=f"Query analysis failed: {str(e)}")


@router.post("/llm-search", response_model=LLMSearchResponse)
async def llm_context_search(request: LLMSearchRequest, username: Optional[str] = Depends(get_optional_user)):
    """
    LLM context-based search.
    Analyzes user query, optimises search terms, searches arXiv & Scholar.
    Korean queries are auto-translated to English.
    """
    if not query_analyzer:
        raise HTTPException(
            status_code=503,
            detail="LLM search service unavailable (OpenAI API key not configured)",
        )

    try:
        start_time = time.time()
        logger.info("[API] LLM Context Search: %s", request.query)

        loop = asyncio.get_running_loop()
        results = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                partial(
                    search_agent.llm_context_search,
                    query=request.query,
                    max_results_per_source=request.max_results,
                    context=request.context,
                ),
            ),
            timeout=_LLM_SEARCH_TIMEOUT,
        )

        metadata = results.pop("_metadata", {})
        total = sum(len(papers) for papers in results.values())
        search_time = time.time() - start_time

        logger.info("[API] LLM Search completed: %s papers in %.2fs", total, search_time)

        if request.save_papers and total > 0:
            try:
                _stamp_searched_by(results, username)
                save_result = search_agent.save_papers(
                    results, request.query, generate_embeddings=False, update_graph=True
                )
                metadata["save_result"] = {
                    "new_papers": save_result.get("new_papers", 0),
                    "duplicates": save_result.get("duplicates", 0),
                }
                logger.info("[API] Saved: %s new papers", save_result.get("new_papers", 0))
            except Exception as e:
                logger.error("[API] Error saving papers: %s", e)

        metadata["search_time"] = round(search_time, 2)

        return LLMSearchResponse(results=results, total=total, metadata=metadata)

    except asyncio.TimeoutError:
        logger.error("[API] LLM Search timed out after %ds", _LLM_SEARCH_TIMEOUT)
        raise HTTPException(status_code=504, detail=f"LLM search timed out after {_LLM_SEARCH_TIMEOUT}s")
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("[API] LLM Search error: %s", error_trace)
        raise HTTPException(status_code=500, detail=f"LLM search failed: {str(e)}")


@router.post("/smart-search")
async def smart_search(request: LLMSearchRequest, username: Optional[str] = Depends(get_optional_user)):
    """
    Smart search -- LLM analysis + multi-source strategy.
    1. LLM analyses query & decides strategy
    2. Optimised query across multiple sources
    3. Merge & deduplicate
    4. Sort by relevance
    """
    try:
        start_time = time.time()
        logger.info("[API] Smart Search: %s", request.query)

        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                partial(search_agent.smart_search, query=request.query, max_results=request.max_results),
            ),
            timeout=_SMART_SEARCH_TIMEOUT,
        )

        search_time = time.time() - start_time
        result["metadata"]["search_time"] = round(search_time, 2)

        logger.info("[API] Smart Search completed: %s papers in %.2fs", len(result["papers"]), search_time)

        if request.save_papers and result["papers"]:
            try:
                results_by_source = {"arxiv": [], "connected_papers": [], "google_scholar": [], "openalex": [], "dblp": [], "openalex_korean": []}
                for paper in result["papers"]:
                    source = paper.pop("_source", "arxiv")
                    if source in results_by_source:
                        results_by_source[source].append(paper)

                _stamp_searched_by(results_by_source, username)
                save_result = search_agent.save_papers(
                    results_by_source, request.query, generate_embeddings=False, update_graph=True
                )
                result["metadata"]["save_result"] = {
                    "new_papers": save_result.get("new_papers", 0),
                    "duplicates": save_result.get("duplicates", 0),
                }
            except Exception as e:
                logger.error("[API] Error saving papers: %s", e)

        return result

    except asyncio.TimeoutError:
        logger.error("[API] Smart Search timed out after %ds", _SMART_SEARCH_TIMEOUT)
        raise HTTPException(status_code=504, detail=f"Smart search timed out after {_SMART_SEARCH_TIMEOUT}s")
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("[API] Smart Search error: %s", error_trace)
        raise HTTPException(status_code=500, detail=f"Smart search failed: {str(e)}")


@router.post("/deep-search")
async def deep_search(request: LLMSearchRequest, username: Optional[str] = Depends(get_optional_user)):
    """ArxivQA 스타일 멀티턴 심층 검색.

    ReAct 에이전트가 검색→분석→재쿼리를 반복하고,
    RaR rubric으로 결과 세트를 평가한다.
    """
    _record_query(request.query)
    try:
        start_time = time.time()
        logger.info("[API] Deep Search: %s", request.query)

        # 1. Query analysis
        analysis = {}
        if query_analyzer:
            try:
                loop = asyncio.get_running_loop()
                analysis = await asyncio.wait_for(
                    loop.run_in_executor(None, partial(query_analyzer.analyze_query, request.query)),
                    timeout=10,
                )
            except Exception as e:
                logger.warning("[Deep Search] Query analysis failed: %s", e)

        # 2. ReAct multi-turn search (난이도 기반 max_turns)
        difficulty = query_analyzer.classify_difficulty(analysis) if query_analyzer and analysis else "medium"
        _DIFFICULTY_TURNS = {"easy": 1, "medium": 2, "hard": 3}
        max_turns = _DIFFICULTY_TURNS.get(difficulty, 2)

        from app.SearchAgent.react_search_agent import ReActSearchAgent

        react_agent = ReActSearchAgent(
            search_agent=search_agent,
            openai_client=get_openai_client(),
            max_turns=max_turns,
        )
        result = await react_agent.search(
            query=request.query,
            analysis=analysis,
            max_results=request.max_results or 20,
        )

        # 2.5. GraphRAG auxiliary expansion
        try:
            react_papers = result.get("papers", [])
            if react_papers:
                loop = asyncio.get_running_loop()
                graphrag_papers = await loop.run_in_executor(
                    None, partial(_graphrag_expand, request.query, react_papers, 15)
                )
                if graphrag_papers:
                    # 중복 제거: 기존 결과의 제목 집합
                    existing_titles = {p.get("title", "").strip().lower() for p in react_papers}
                    new_papers = [
                        p for p in graphrag_papers
                        if p.get("title", "").strip().lower() not in existing_titles
                    ]
                    for p in new_papers:
                        p["_source"] = "graphrag"
                    result["papers"].extend(new_papers)
                    logger.info("[Deep Search][GraphRAG] Added %d papers from graph expansion", len(new_papers))
        except Exception as e:
            logger.warning("[Deep Search][GraphRAG] Expansion failed (continuing): %s", e)

        # 3. Rubric evaluation
        from app.QueryAgent.rubric_evaluator import RubricEvaluator

        evaluator = RubricEvaluator()  # OPENAI_API_KEY 환경변수로 자체 AsyncOpenAI 생성
        evaluation = await evaluator.evaluate(
            query=request.query,
            intent=analysis.get("intent", "paper_search"),
            papers=result.get("papers", []),
        )
        result["evaluation"] = evaluation

        search_time = time.time() - start_time
        result.setdefault("metadata", {})["search_time"] = round(search_time, 2)
        result["metadata"]["difficulty"] = difficulty
        result["metadata"]["max_turns"] = max_turns

        logger.info(
            "[API] Deep Search completed: %d papers, %.1fs, score=%.2f",
            len(result.get("papers", [])),
            search_time,
            evaluation.get("overall_score", 0),
        )

        # 4. Save papers
        if request.save_papers and result.get("papers"):
            try:
                results_by_source = {"arxiv": [], "openalex": [], "dblp": [], "graphrag": []}
                for paper in result["papers"]:
                    src = paper.pop("_source", "arxiv")
                    if src in results_by_source:
                        results_by_source[src].append(paper)
                _stamp_searched_by(results_by_source, username)
                search_agent.save_papers(results_by_source, request.query, generate_embeddings=False, update_graph=True)
            except Exception as e:
                logger.error("[Deep Search] Save papers error: %s", e)

        return result

    except asyncio.TimeoutError:
        logger.error("[API] Deep Search timed out")
        raise HTTPException(status_code=504, detail="Deep search timed out")
    except Exception as e:
        logger.error("[API] Deep Search failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Deep search failed: {str(e)}")


@router.post("/search", response_model=SearchResponse)
async def search_papers(request: SearchRequest, username: Optional[str] = Depends(get_optional_user)):
    """Search papers across multiple sources with automatic query analysis."""
    _record_query(request.query)
    # Mutable container for partial results accessible from timeout handler
    _partial: dict = {
        "results": {s: [] for s in request.sources},
        "query_analysis": None,
        "stage_timings": {},
        "stage_modes": {},
    }

    async def _run_search_pipeline() -> SearchResponse:
        start_time = time.time()
        loop = asyncio.get_running_loop()
        stage_timings: Dict[str, float] = {}
        stage_modes: Dict[str, Any] = {
            "use_llm_search": request.use_llm_search,
            "fast_mode": request.fast_mode,
            "query_analyzer_enabled": bool(query_analyzer),
            "relevance_filter_enabled": bool(relevance_filter),
            "hybrid_ranker_enabled": bool(_hybrid_ranker),
        }

        # ── Parallel topic classification + query analysis ──
        is_academic = True
        query_analysis = None

        if query_analyzer:
            analysis_start = time.time()

            if not request.use_llm_search:
                # Unified 3-in-1 call: classify + analyze + source_queries
                logger.info("[API] Unified query analysis: %s", request.query)
                try:
                    unified = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            partial(query_analyzer.analyze_and_prepare, request.query),
                        ),
                        timeout=_ANALYZE_TIMEOUT,
                    )
                    is_academic = unified.get("is_academic", True)
                    query_analysis = unified
                    logger.info(
                        "[API] Unified analysis: intent=%s, keywords=%s, confidence=%s (took %.2fs)",
                        unified.get("intent"),
                        unified.get("keywords"),
                        unified.get("confidence"),
                        time.time() - analysis_start,
                    )
                    stage_timings["query_analysis"] = round(time.time() - analysis_start, 3)
                    stage_modes["query_analysis_mode"] = "unified_llm"
                except asyncio.TimeoutError:
                    logger.warning("[API] Unified analysis timed out after %ds (continuing with original query)", _ANALYZE_TIMEOUT)
                    stage_timings["query_analysis"] = round(time.time() - analysis_start, 3)
                    stage_modes["query_analysis_mode"] = "unified_timeout_fallback"
                except Exception as e:
                    logger.warning("[API] Unified analysis failed (continuing with original query): %s", e)
                    stage_timings["query_analysis"] = round(time.time() - analysis_start, 3)
                    stage_modes["query_analysis_mode"] = "unified_error_fallback"
            else:
                # LLM search mode: only classify, skip analyze
                logger.info("[API] Query analysis skipped (LLM search handles query optimization)")
                try:
                    classify_result = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            partial(query_analyzer.classify_topic, request.query),
                        ),
                        timeout=5,
                    )
                    is_academic = classify_result.get("is_academic", True)
                    stage_timings["query_analysis"] = round(time.time() - analysis_start, 3)
                    stage_modes["query_analysis_mode"] = "classify_only"
                except Exception:
                    stage_timings["query_analysis"] = round(time.time() - analysis_start, 3)
                    stage_modes["query_analysis_mode"] = "classify_only_fallback"
                    pass  # error → assume academic
        else:
            logger.info("[API] Query analysis skipped (OpenAI API key not configured)")
            stage_modes["query_analysis_mode"] = "disabled_no_api_key"

        _partial["query_analysis"] = query_analysis
        _partial["stage_timings"] = stage_timings
        _partial["stage_modes"] = stage_modes

        if not is_academic:
            logger.info("[API] Non-academic query blocked: %s", request.query)
            return SearchResponse(
                results={s: [] for s in request.sources},
                total=0,
                query_analysis={"is_academic": False, "original_query": request.query},
            )

        # Use only user-specified filters (LLM auto-filters removed — they
        # were too aggressive and returned irrelevant results)
        filters = {
            "sources": request.sources,
            "max_results": request.max_results,
            "sort_by": request.sort_by,
            "year_start": request.year_start,
            "year_end": request.year_end,
            "author": request.author,
            "category": request.category,
        }

        # Use improved query only with very high confidence
        search_query = request.query
        source_queries = None
        if query_analysis and query_analysis.get("confidence", 0) >= 0.8:
            improved_query = query_analysis.get("improved_query")
            if improved_query and improved_query != request.query:
                # 단수/복수 차이를 무시하는 간단한 정규화 (trailing 's' 제거)
                _STOP_WORDS = {"in", "of", "for", "the", "a", "an", "and", "or", "on", "to", "with", "by", "from", "is", "are", "at", "as"}

                def _stem(word: str) -> str:
                    w = word.lower().rstrip("s")
                    return w if w else word.lower()

                original_stems = {_stem(w) for w in request.query.split() if w.lower() not in _STOP_WORDS}
                improved_stems = {_stem(w) for w in improved_query.split() if w.lower() not in _STOP_WORDS}
                overlap = len(original_stems & improved_stems) / max(len(original_stems), 1)
                length_ratio = len(improved_stems) / max(len(original_stems), 1)
                max_ratio = 2.0
                if overlap >= 0.5 and length_ratio < max_ratio:
                    logger.info("[API] Using improved query (overlap=%.2f, ratio=%.1f): %s", overlap, length_ratio, improved_query)
                    search_query = improved_query
                else:
                    logger.info("[API] Skipping improved query (overlap=%.2f, ratio=%.1f): %s", overlap, length_ratio, improved_query)

            # Use source-specific queries from unified analysis (already included)
            unified_source_queries = query_analysis.get("source_queries")
            if unified_source_queries:
                source_queries = unified_source_queries
                logger.info("[API] Source-specific queries (from unified): %s", {k: v[:50] for k, v in source_queries.items()})
                filters["source_queries"] = source_queries

        # Cache check (사용자 원본 입력 기준 - LLM 분석 결과 변동 무관)
        user_filters = {
            "sort_by": request.sort_by,
            "year_start": request.year_start,
            "year_end": request.year_end,
            "author": request.author,
            "category": request.category,
            "fast_mode": request.fast_mode,
        }
        cache_key = _compute_cache_key(request.query, request.sources, user_filters)
        cached = _get_cached_result(cache_key)
        if cached is not None:
            total = sum(len(papers) for papers in cached.values() if isinstance(papers, list))
            logger.info("[API] Returning cached results: %s papers", total)
            return SearchResponse(results=cached, total=total, query_analysis=query_analysis)

        search_start = time.time()
        logger.info("[API] Searching for: %s", search_query)
        logger.info("[API] Filters: %s", filters)

        # LLM context search or standard search (with timeout)
        if request.use_llm_search and query_analyzer:
            logger.info("[API] Using LLM Context Search...")
            stage_modes["source_search_mode"] = "llm_context_search"
            results = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    partial(
                        search_agent.llm_context_search,
                        search_query,
                        max_results_per_source=request.max_results,
                        context=request.search_context,
                    ),
                ),
                timeout=_SOURCE_SEARCH_TIMEOUT,
            )
            llm_metadata = results.pop("_metadata", None)
            if llm_metadata:
                logger.info(
                    "[API] LLM generated queries: arXiv=%s, Scholar=%s",
                    len(llm_metadata.get("arxiv_queries", [])),
                    len(llm_metadata.get("scholar_queries", [])),
                )
        else:
            stage_modes["source_search_mode"] = "standard_async_multi_source"
            results = await asyncio.wait_for(
                search_agent.async_search_with_filters(search_query, filters),
                timeout=_SOURCE_SEARCH_TIMEOUT,
            )

        search_time = time.time() - search_start
        stage_timings["source_search"] = round(search_time, 3)
        logger.info(
            "[API] Raw search results: %s papers found (took %.2fs)",
            sum(len(papers) for papers in results.values()),
            search_time,
        )

        # Update partial results after raw search completes
        _partial["results"] = results

        # Step 1.5: GraphRAG auxiliary expansion (skip in fast_mode)
        if not request.fast_mode and results:
            remaining_before_graphrag = _remaining_budget(start_time)
            if remaining_before_graphrag < _MIN_BUDGET_FOR_GRAPHRAG:
                stage_modes["graphrag_mode"] = "skipped_low_budget"
                stage_timings["graphrag"] = 0.0
                logger.info(
                    "[GraphRAG] Skipped due to low remaining budget: %.2fs < %ds",
                    remaining_before_graphrag,
                    _MIN_BUDGET_FOR_GRAPHRAG,
                )
            else:
                graphrag_start = time.time()
                try:
                    all_papers_flat = [p for papers in results.values() for p in papers]
                    graphrag_papers = await asyncio.wait_for(
                        loop.run_in_executor(
                            None, partial(_graphrag_expand, request.query, all_papers_flat, 15)
                        ),
                        timeout=min(_GRAPHRAG_TIMEOUT, max(1.0, remaining_before_graphrag - 8)),
                    )
                    if graphrag_papers:
                        results.setdefault("graphrag", []).extend(graphrag_papers)
                        logger.info("[GraphRAG] Added %d papers from graph expansion", len(graphrag_papers))
                    stage_timings["graphrag"] = round(time.time() - graphrag_start, 3)
                    stage_modes["graphrag_mode"] = "enabled"
                except asyncio.TimeoutError:
                    logger.warning("[GraphRAG] Expansion timed out after %ds (continuing without graph expansion)", _GRAPHRAG_TIMEOUT)
                    stage_timings["graphrag"] = round(time.time() - graphrag_start, 3)
                    stage_modes["graphrag_mode"] = "timeout"
                except Exception as e:
                    logger.warning("[GraphRAG] Expansion failed (continuing): %s", e)
                    stage_timings["graphrag"] = round(time.time() - graphrag_start, 3)
                    stage_modes["graphrag_mode"] = "error"
        else:
            stage_modes["graphrag_mode"] = "skipped"

        # Cross-source deduplication + Hybrid ranking (always) + Relevance filtering (non-fast only)
        if results:
            intent = query_analysis.get("intent", "paper_search") if query_analysis else "paper_search"
            ranked_candidates: List[Dict[str, Any]] = []

            # Collect all active source keys (user-specified + graphrag if present)
            _all_source_keys = list(request.sources) + [s for s in results if s not in request.sources]

            # Step 1: Cross-source deduplication
            try:
                all_papers_for_dedup = []
                for source, papers in results.items():
                    for paper in papers:
                        paper["_source_tag"] = source
                        all_papers_for_dedup.append(paper)

                before_count = len(all_papers_for_dedup)
                if before_count > 0:
                    deduped = search_agent.deduplicator.deduplicate(all_papers_for_dedup)
                    removed = before_count - len(deduped)
                    if removed > 0:
                        logger.info("[API] Cross-source dedup: removed %d duplicates (%d → %d)", removed, before_count, len(deduped))
                    # 소스별로 다시 분리 (graphrag 포함)
                    results = {s: [] for s in _all_source_keys}
                    for paper in deduped:
                        src = paper.pop("_source_tag", paper.get("_source", "arxiv"))
                        paper.pop("_source", None)
                        if src in results:
                            results[src].append(paper)
            except Exception as e:
                logger.warning("[API] Cross-source dedup failed (continuing): %s", e)

            for source, papers in results.items():
                for paper in papers:
                    paper["_result_source"] = source

            # Step 2: Hybrid ranking (always applied)
            if _hybrid_ranker:
                ranking_start = time.time()
                try:
                    for source, papers in results.items():
                        for paper in papers:
                            paper["_source_tag"] = source
                            paper["_result_source"] = source

                    ranking_cap = _ranking_candidate_cap(request.max_results)
                    all_papers_for_ranking = _interleave_source_candidates(
                        results,
                        _all_source_keys,
                        ranking_cap,
                    )

                    if all_papers_for_ranking:
                        remaining_before_ranking = _remaining_budget(start_time)
                        if remaining_before_ranking < _MIN_BUDGET_FOR_RANKING:
                            stage_modes["ranking_mode"] = "skipped_low_budget"
                            stage_timings["ranking"] = 0.0
                            ranked_candidates = list(all_papers_for_ranking)
                            logger.info(
                                "[API] Ranking skipped due to low remaining budget: %.2fs < %ds",
                                remaining_before_ranking,
                                _MIN_BUDGET_FOR_RANKING,
                            )
                        else:
                            # Skip HyDE unless the query is hard and enough budget remains.
                            difficulty = query_analyzer.classify_difficulty(query_analysis) if query_analyzer and query_analysis else "medium"
                            hyde_enabled = difficulty == "hard" and remaining_before_ranking >= _MIN_BUDGET_FOR_HYDE_HARD
                            hyde_client = get_openai_client() if hyde_enabled else None
                            stage_modes["ranking_mode"] = "hybrid_rrf"
                            stage_modes["query_difficulty"] = difficulty
                            if difficulty == "easy":
                                stage_modes["hyde_mode"] = "disabled_easy_query"
                            elif difficulty != "hard":
                                stage_modes["hyde_mode"] = "disabled_non_hard_query"
                            elif not hyde_enabled:
                                stage_modes["hyde_mode"] = "disabled_low_budget"
                            else:
                                stage_modes["hyde_mode"] = "enabled_hard_query"

                            if not hyde_enabled:
                                logger.info(
                                    "[API] HyDE skipped (difficulty=%s, remaining_budget=%.2fs)",
                                    difficulty,
                                    remaining_before_ranking,
                                )

                            ranked = await asyncio.wait_for(
                                loop.run_in_executor(
                                    None,
                                    partial(
                                        _hybrid_ranker.rank_papers,
                                        query=request.query,
                                        papers=all_papers_for_ranking,
                                        intent=intent,
                                        openai_client=hyde_client,
                                        use_rrf=True,
                                    ),
                                ),
                                timeout=min(_RANKING_TIMEOUT, max(3.0, remaining_before_ranking - 5)),
                            )
                            ranked_candidates = list(ranked)
                            # 소스별로 다시 분리 (graphrag 포함)
                            results = _rebuild_results_from_ranked(ranked, _all_source_keys)
                            logger.info(
                                "[API] Hybrid ranking applied (intent=%s, candidates=%d, mode=%s)",
                                intent,
                                len(all_papers_for_ranking),
                                stage_modes.get("hyde_mode", "unknown"),
                            )
                            stage_timings["ranking"] = round(time.time() - ranking_start, 3)
                except asyncio.TimeoutError:
                    logger.warning("[API] Hybrid ranking timed out after %ds (returning results in original order)", _RANKING_TIMEOUT)
                    stage_timings["ranking"] = round(time.time() - ranking_start, 3)
                    stage_modes["ranking_mode"] = "timeout_fallback_original_order"
                    ranked_candidates = [paper for papers in results.values() for paper in papers]
                except Exception as e:
                    logger.warning("[API] Hybrid ranking failed (continuing): %s", e)
                    stage_timings["ranking"] = round(time.time() - ranking_start, 3)
                    stage_modes["ranking_mode"] = "error_fallback_original_order"
                    ranked_candidates = [paper for papers in results.values() for paper in papers]
            else:
                stage_modes["ranking_mode"] = "disabled"
                ranked_candidates = [paper for papers in results.values() for paper in papers]

            # Update partial results after ranking
            _partial["results"] = results

            # Step 3: LLM Relevance filtering (only when not fast_mode)
            if not request.fast_mode:
                if relevance_filter:
                    filter_start = time.time()
                    try:
                        if stage_modes.get("ranking_mode") == "skipped_low_budget":
                            stage_modes["relevance_filter_mode"] = "skipped_after_low_budget_ranking"
                            stage_timings["relevance_filter"] = 0.0
                            logger.info("[API] Relevance filtering skipped because ranking was already skipped for low budget")
                        else:
                            remaining_before_filter = _remaining_budget(start_time)
                            if remaining_before_filter < _MIN_BUDGET_FOR_RELEVANCE:
                                stage_modes["relevance_filter_mode"] = "skipped_low_budget"
                                stage_timings["relevance_filter"] = 0.0
                                logger.info(
                                    "[API] Relevance filtering skipped due to low remaining budget: %.2fs < %ds",
                                    remaining_before_filter,
                                    _MIN_BUDGET_FOR_RELEVANCE,
                                )
                            else:
                                logger.info("[API] Applying relevance filtering (parallel mode)...")
                                all_papers = list(ranked_candidates) if ranked_candidates else []
                                for paper in all_papers:
                                    paper["source"] = paper.get("_result_source", paper.get("source", "arxiv"))

                                filter_candidates = all_papers[:_RELEVANCE_FILTER_TOP_N]
                                if filter_candidates:
                                    filtered_papers = await asyncio.wait_for(
                                        loop.run_in_executor(
                                            None,
                                            partial(
                                                relevance_filter.filter_papers,
                                                request.query,
                                                filter_candidates,
                                                threshold=0.65,
                                                max_papers=min(request.max_results, _RELEVANCE_FILTER_TOP_N),
                                                parallel=True,
                                            ),
                                        ),
                                        timeout=min(_RELEVANCE_FILTER_TIMEOUT, max(2.0, remaining_before_filter - 3)),
                                    )
                                    # Fallback: if filtering eliminated ALL papers, keep originals
                                    if filtered_papers:
                                        selected_keys = {_paper_identity(p) for p in filtered_papers}
                                        filtered_tail = [
                                            paper for paper in all_papers
                                            if _paper_identity(paper) not in selected_keys
                                        ]
                                        combined_ranked = (filtered_papers + filtered_tail)[:request.max_results]
                                        results = _rebuild_results_from_ranked(combined_ranked, _all_source_keys)
                                        ranked_candidates = combined_ranked
                                        logger.info(
                                            "[API] Filtered top-%d candidates and preserved %d fallback papers",
                                            len(filter_candidates),
                                            max(0, len(combined_ranked) - len(filtered_papers)),
                                        )
                                    else:
                                        logger.warning(
                                            "[API] Relevance filter eliminated all %d top candidates — keeping ranked results",
                                            len(filter_candidates),
                                        )
                                else:
                                    logger.info("[API] No papers to filter")
                                stage_timings["relevance_filter"] = round(time.time() - filter_start, 3)
                                stage_modes["relevance_filter_mode"] = "enabled_top_n"
                    except Exception as e:
                        logger.exception("[API] Relevance filtering failed (using unfiltered results): %s", e)
                        stage_timings["relevance_filter"] = round(time.time() - filter_start, 3)
                        stage_modes["relevance_filter_mode"] = "error_fallback_unfiltered"
                else:
                    logger.info("[API] Relevance filtering skipped (OpenAI API key not configured)")
                    stage_modes["relevance_filter_mode"] = "disabled_no_api_key"
            else:
                logger.info("[API] LLM relevance filtering skipped (fast mode)")
                stage_modes["relevance_filter_mode"] = "skipped_fast_mode"
        else:
            logger.info("[API] No results to rank/filter")
            stage_modes["ranking_mode"] = "skipped_no_results"
            stage_modes["relevance_filter_mode"] = "skipped_no_results"

        # Ensure all sources present
        for source in request.sources:
            if source not in results:
                results[source] = []

        for papers in results.values():
            for paper in papers:
                paper.pop("_source_tag", None)
                paper.pop("_result_source", None)

        total = sum(len(papers) for papers in results.values())

        # Stamp username on papers before saving
        _stamp_searched_by(results, username)

        # Save & enrich (always in background to keep response fast)
        if request.save_papers and total > 0:
            logger.info("[API] Starting background enrichment for %s papers...", total)
            t = threading.Thread(
                target=_enrich_papers_background,
                args=(
                    request.query,
                    copy.deepcopy(results),
                    request.collect_references,
                    request.extract_texts,
                    request.max_references_per_paper,
                ),
            )
            t.daemon = True
            t.start()
            logger.info("[API] Background enrichment started (thread)")

        total_time = time.time() - start_time
        stage_timings["total"] = round(total_time, 3)
        _partial["stage_timings"] = stage_timings
        _partial["stage_modes"] = stage_modes
        logger.info("[API] Search completed in %.2fs", total_time)
        logger.info("[API] Search stage timings=%s modes=%s", stage_timings, stage_modes)

        # Store in query cache
        _set_cache(cache_key, results)

        # Cache results for Deep Research
        try:
            cache_dir = Path("data/cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / "last_search_results.json"

            from src.utils.paper_utils import generate_doc_id as _generate_doc_id

            all_cached_papers = []
            for source_papers in results.values():
                if isinstance(source_papers, list):
                    for paper in source_papers:
                        if "doc_id" not in paper or not paper.get("doc_id"):
                            title = paper.get("title", "")
                            paper["doc_id"] = _generate_doc_id(title)
                        all_cached_papers.append(paper)

            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(all_cached_papers, f, ensure_ascii=False, indent=2)
            logger.info("[API] Search results cached: %s papers (with doc_ids)", len(all_cached_papers))
        except Exception as cache_error:
            logger.warning("[API] Cache save warning: %s", cache_error)

        return SearchResponse(results=results, total=total, query_analysis=query_analysis)

    try:
        return await asyncio.wait_for(_run_search_pipeline(), timeout=_SEARCH_TIMEOUT)
    except asyncio.TimeoutError:
        # Return partial results collected so far instead of failing completely
        partial_results = _partial["results"]
        total = sum(len(papers) for papers in partial_results.values() if isinstance(papers, list))
        logger.error(
            "[API] Search pipeline timed out after %ds for query: %s (returning %d partial results)",
            _SEARCH_TIMEOUT, request.query, total,
        )
        logger.error(
            "[API] Partial search timings=%s modes=%s",
            _partial.get("stage_timings", {}),
            _partial.get("stage_modes", {}),
        )
        if total > 0:
            return SearchResponse(
                results=partial_results,
                total=total,
                query_analysis=_partial["query_analysis"],
            )
        raise HTTPException(status_code=504, detail=f"Search timed out after {_SEARCH_TIMEOUT}s")
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("[API] Error in search: %s", error_trace)
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


# ── P2-4: SSE Streaming Deep Search ──────────────────────────────────

class DeepSearchStreamRequest(BaseModel):
    query: str
    max_results: int = 20
    context: str = ""
    save_papers: bool = True


@router.post("/deep-search-stream")
async def deep_search_stream(request: DeepSearchStreamRequest, username: Optional[str] = Depends(get_optional_user)):
    """SSE streaming endpoint for deep search.

    Emits real-time progress events as the multi-turn ReAct agent works:
    - ``turn_start``: A new search turn has begun
    - ``query_analysis``: Query analysis complete
    - ``papers_found``: Papers discovered in this turn
    - ``gap_analysis``: Gap analysis identifying missing coverage
    - ``evaluation``: Rubric evaluation scores
    - ``complete``: Final results with all papers
    - ``error``: An error occurred
    """
    _record_query(request.query)

    async def event_generator():
        """Generate SSE events during deep search execution."""
        try:
            start_time = time.time()

            # ── Turn 0: Query analysis ────────────────────────────
            yield _sse_event("turn_start", {"turn": 0, "phase": "query_analysis"})

            analysis = {}
            if query_analyzer:
                try:
                    loop = asyncio.get_running_loop()
                    analysis = await asyncio.wait_for(
                        loop.run_in_executor(None, partial(query_analyzer.analyze_query, request.query)),
                        timeout=10,
                    )
                    yield _sse_event("query_analysis", {
                        "intent": analysis.get("intent", "paper_search"),
                        "keywords": analysis.get("keywords", []),
                        "confidence": analysis.get("confidence", 0),
                    })
                except Exception as e:
                    logger.warning("[Deep Search Stream] Query analysis failed: %s", e)
                    yield _sse_event("query_analysis", {"intent": "paper_search", "keywords": [], "error": str(e)})

            # ── Multi-turn ReAct search ───────────────────────────
            difficulty = query_analyzer.classify_difficulty(analysis) if query_analyzer and analysis else "medium"
            _DIFFICULTY_TURNS = {"easy": 1, "medium": 2, "hard": 3}
            max_turns = _DIFFICULTY_TURNS.get(difficulty, 2)

            yield _sse_event("turn_start", {"turn": 1, "phase": "search", "max_turns": max_turns, "difficulty": difficulty})

            from app.SearchAgent.react_search_agent import ReActSearchAgent

            loop = asyncio.get_running_loop()
            react_agent = ReActSearchAgent(
                search_agent=search_agent,
                openai_client=get_openai_client(),
                max_turns=max_turns,
            )

            result = await react_agent.search(
                query=request.query,
                analysis=analysis,
                max_results=request.max_results or 20,
            )

            papers = result.get("papers", [])
            yield _sse_event("papers_found", {
                "count": len(papers),
                "turns_used": result.get("metadata", {}).get("turns_used", 1),
            })

            # ── Gap analysis ──────────────────────────────────────
            turns_history = result.get("metadata", {}).get("turns_history", [])
            missing_aspects = []
            for turn_info in turns_history:
                gaps = turn_info.get("gaps", [])
                if gaps:
                    missing_aspects.extend(gaps)
            if missing_aspects:
                yield _sse_event("gap_analysis", {"missing": missing_aspects[:10]})

            # ── Rubric evaluation ─────────────────────────────────
            yield _sse_event("turn_start", {"turn": max_turns + 1, "phase": "evaluation"})

            from app.QueryAgent.rubric_evaluator import RubricEvaluator

            evaluator = RubricEvaluator()
            evaluation = await evaluator.evaluate(
                query=request.query,
                intent=analysis.get("intent", "paper_search"),
                papers=papers,
            )
            result["evaluation"] = evaluation

            yield _sse_event("evaluation", {
                "overall_score": evaluation.get("overall_score", 0),
                "dimensions": {
                    k: v for k, v in evaluation.items()
                    if k != "overall_score" and isinstance(v, (int, float))
                },
            })

            # ── Save papers ───────────────────────────────────────
            search_time = time.time() - start_time
            result.setdefault("metadata", {})["search_time"] = round(search_time, 2)
            result["metadata"]["difficulty"] = difficulty
            result["metadata"]["max_turns"] = max_turns

            if request.save_papers and papers:
                try:
                    results_by_source = {"arxiv": [], "openalex": [], "dblp": []}
                    for paper in papers:
                        src = paper.pop("_source", "arxiv")
                        if src in results_by_source:
                            results_by_source[src].append(paper)
                    _stamp_searched_by(results_by_source, username)
                    search_agent.save_papers(results_by_source, request.query, generate_embeddings=False, update_graph=True)
                except Exception as e:
                    logger.error("[Deep Search Stream] Save papers error: %s", e)

            # ── Complete ──────────────────────────────────────────
            yield _sse_event("complete", {
                "papers": papers,
                "total": len(papers),
                "search_time": round(search_time, 2),
                "evaluation": evaluation,
                "metadata": result.get("metadata", {}),
            })

            logger.info(
                "[API] Deep Search Stream completed: %d papers, %.1fs, score=%.2f",
                len(papers), search_time, evaluation.get("overall_score", 0),
            )

        except Exception as e:
            logger.error("[API] Deep Search Stream failed: %s", e, exc_info=True)
            yield _sse_event("error", {"message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse_event(event: str, data: Any) -> str:
    """Format a Server-Sent Event string."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


# ── Admin: manual prefetch trigger ───────────────────────────────────

@router.post("/prefetch-popular")
async def trigger_prefetch():
    """Manually trigger popular query prefetch (admin use)."""
    t = threading.Thread(
        target=_prefetch_popular_queries,
        daemon=True,
        name="query-prefetch-manual",
    )
    t.start()
    return {"message": "Prefetch started", "queries": len(_get_popular_queries())}
