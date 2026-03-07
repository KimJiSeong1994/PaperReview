"""
Search-related endpoints:
  POST /api/search
  POST /api/smart-search
  POST /api/analyze-query
  POST /api/llm-search
"""

import asyncio
import copy
import hashlib
import json
import logging
import threading
import time
import traceback
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .deps import (
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
    if not username:
        return
    for papers in results.values():
        for paper in papers:
            paper["searched_by"] = username


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


def _compute_cache_key(query: str, sources: List[str], filters: Dict[str, Any]) -> str:
    """검색 요청에 대한 캐시 키 생성 (fast_mode 포함)"""
    key_data = {
        "query": query.strip().lower(),
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
    """30분 주기 백그라운드 캐시 정리"""
    while True:
        time.sleep(1800)
        try:
            _cleanup_expired_cache()
        except Exception as e:
            logger.warning("[Cache] Periodic cleanup error: %s", e)


_cache_maintenance_thread = threading.Thread(
    target=_periodic_cache_maintenance,
    daemon=True,
    name="cache-maintenance",
)
_cache_maintenance_thread.start()


# ── Endpoints ──────────────────────────────────────────────────────────

# Endpoint-level timeout constants (seconds)
_ANALYZE_TIMEOUT = 30
_LLM_SEARCH_TIMEOUT = 90
_SMART_SEARCH_TIMEOUT = 90
_SEARCH_TIMEOUT = 90


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
                if username:
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

                if username:
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


@router.post("/search", response_model=SearchResponse)
async def search_papers(request: SearchRequest, username: Optional[str] = Depends(get_optional_user)):
    """Search papers across multiple sources with automatic query analysis."""
    try:
        start_time = time.time()
        loop = asyncio.get_running_loop()

        # Query analysis (skip when LLM search — llm_context_search does its own)
        query_analysis = None
        if query_analyzer and not request.use_llm_search:
            try:
                analysis_start = time.time()
                logger.info("[API] Analyzing query: %s", request.query)
                query_analysis = await asyncio.wait_for(
                    loop.run_in_executor(None, partial(query_analyzer.analyze_query, request.query)),
                    timeout=_ANALYZE_TIMEOUT,
                )
                logger.info(
                    "[API] Query analysis: intent=%s, keywords=%s, confidence=%s (took %.2fs)",
                    query_analysis.get("intent"),
                    query_analysis.get("keywords"),
                    query_analysis.get("confidence"),
                    time.time() - analysis_start,
                )
            except asyncio.TimeoutError:
                logger.warning("[API] Query analysis timed out after %ds (continuing with original query)", _ANALYZE_TIMEOUT)
            except Exception as e:
                logger.warning("[API] Query analysis failed (continuing with original query): %s", e)
        elif request.use_llm_search:
            logger.info("[API] Query analysis skipped (LLM search handles query optimization)")
        else:
            logger.info("[API] Query analysis skipped (OpenAI API key not configured)")

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

            # Generate source-specific optimized queries
            if query_analyzer:
                try:
                    source_queries = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            partial(
                                query_analyzer.generate_source_specific_queries,
                                search_query,
                                keywords=query_analysis.get("keywords"),
                            ),
                        ),
                        timeout=_ANALYZE_TIMEOUT,
                    )
                    logger.info("[API] Source-specific queries generated: %s", {k: v[:50] for k, v in source_queries.items()})
                    filters["source_queries"] = source_queries
                except Exception as e:
                    logger.warning("[API] Source-specific query generation failed: %s", e)

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
                timeout=_SEARCH_TIMEOUT,
            )
            llm_metadata = results.pop("_metadata", None)
            if llm_metadata:
                logger.info(
                    "[API] LLM generated queries: arXiv=%s, Scholar=%s",
                    len(llm_metadata.get("arxiv_queries", [])),
                    len(llm_metadata.get("scholar_queries", [])),
                )
        else:
            results = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    partial(search_agent.search_with_filters, search_query, filters),
                ),
                timeout=_SEARCH_TIMEOUT,
            )

        search_time = time.time() - search_start
        logger.info(
            "[API] Raw search results: %s papers found (took %.2fs)",
            sum(len(papers) for papers in results.values()),
            search_time,
        )

        # Cross-source deduplication + Hybrid ranking (always) + Relevance filtering (non-fast only)
        if results:
            intent = query_analysis.get("intent", "paper_search") if query_analysis else "paper_search"

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
                    # 소스별로 다시 분리
                    results = {s: [] for s in request.sources}
                    for paper in deduped:
                        src = paper.pop("_source_tag", paper.get("_source", "arxiv"))
                        paper.pop("_source", None)
                        if src in results:
                            results[src].append(paper)
            except Exception as e:
                logger.warning("[API] Cross-source dedup failed (continuing): %s", e)

            # Step 2: Hybrid ranking (always applied)
            if _hybrid_ranker:
                try:
                    all_papers_for_ranking = []
                    for source, papers in results.items():
                        for paper in papers:
                            paper["_source_tag"] = source
                            all_papers_for_ranking.append(paper)

                    if all_papers_for_ranking:
                        ranked = _hybrid_ranker.rank_papers(
                            query=request.query,
                            papers=all_papers_for_ranking,
                            intent=intent,
                        )
                        # 소스별로 다시 분리
                        results = {s: [] for s in request.sources}
                        for paper in ranked:
                            src = paper.pop("_source_tag", "arxiv")
                            if src in results:
                                results[src].append(paper)
                        logger.info("[API] Hybrid ranking applied (intent=%s)", intent)
                except Exception as e:
                    logger.warning("[API] Hybrid ranking failed (continuing): %s", e)

            # Step 3: LLM Relevance filtering (only when not fast_mode)
            if not request.fast_mode:
                if relevance_filter:
                    try:
                        logger.info("[API] Applying relevance filtering (parallel mode)...")
                        all_papers = []
                        for source, papers in results.items():
                            for paper in papers:
                                paper["source"] = source
                                all_papers.append(paper)

                        if all_papers:
                            filtered_papers = await asyncio.wait_for(
                                loop.run_in_executor(
                                    None,
                                    partial(
                                        relevance_filter.filter_papers,
                                        request.query,
                                        all_papers,
                                        threshold=0.65,
                                        max_papers=request.max_results,
                                        parallel=True,
                                    ),
                                ),
                                timeout=_SEARCH_TIMEOUT,
                            )
                            results = {}
                            for source in request.sources:
                                results[source] = [p for p in filtered_papers if p.get("source") == source]
                            logger.info("[API] Filtered results: %s papers (threshold: 0.65)", len(filtered_papers))
                        else:
                            logger.info("[API] No papers to filter")
                    except Exception as e:
                        logger.exception("[API] Relevance filtering failed (using unfiltered results): %s", e)
                else:
                    logger.info("[API] Relevance filtering skipped (OpenAI API key not configured)")
            else:
                logger.info("[API] LLM relevance filtering skipped (fast mode)")
        else:
            logger.info("[API] No results to rank/filter")

        # Ensure all sources present
        for source in request.sources:
            if source not in results:
                results[source] = []

        total = sum(len(papers) for papers in results.values())

        # Stamp username on papers before saving
        if username:
            _stamp_searched_by(results, username)

        # Save & enrich
        if request.save_papers and total > 0:
            if request.fast_mode:
                logger.info("[API] Fast mode: Starting background enrichment for %s papers...", total)
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
            else:
                try:
                    logger.info("[API] Saving %s papers...", total)
                    save_result = search_agent.save_papers(
                        results, request.query, generate_embeddings=False, update_graph=True
                    )
                    logger.info(
                        "[API] Saved: %s new, %s duplicates",
                        save_result.get("new_papers", 0),
                        save_result.get("duplicates", 0),
                    )
                    new_papers_count = save_result.get("new_papers", 0)
                    if request.collect_references and new_papers_count > 0:
                        max_papers_to_collect = min(new_papers_count, 10)
                        logger.info("[API] Collecting references for %s papers...", max_papers_to_collect)
                        ref_result = search_agent.collect_references(
                            request.max_references_per_paper, max_papers=max_papers_to_collect
                        )
                        logger.info("[API] References collected: %s", ref_result.get("references_found", 0))
                    if request.extract_texts:
                        logger.info("[API] Extracting full texts for saved papers...")
                        text_result = search_agent.extract_full_texts(
                            max_papers=save_result.get("new_papers", 0)
                            if save_result.get("new_papers", 0) > 0
                            else None
                        )
                        logger.info("[API] Texts extracted: %s", text_result.get("texts_extracted", 0))
                except Exception as e:
                    logger.exception("[API] Error in saving/enriching papers: %s", e)

        total_time = time.time() - start_time
        logger.info("[API] Search completed in %.2fs", total_time)

        # Store in query cache
        _set_cache(cache_key, results)

        # Cache results for Deep Research
        try:
            cache_dir = Path("data/cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / "last_search_results.json"

            def _generate_doc_id(title: str) -> str:
                hash_value = 0
                for char in title:
                    hash_value = ((hash_value << 5) - hash_value) + ord(char)
                    hash_value = hash_value & 0x7FFFFFFF
                return str(hash_value)

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
    except asyncio.TimeoutError:
        logger.error("[API] Search timed out after %ds for query: %s", _SEARCH_TIMEOUT, request.query)
        raise HTTPException(status_code=504, detail=f"Search timed out after {_SEARCH_TIMEOUT}s")
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("[API] Error in search: %s", error_trace)
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
