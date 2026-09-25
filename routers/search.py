"""
Search-related endpoints:
  POST /api/search
  POST /api/smart-search
  POST /api/analyze-query
  POST /api/llm-search
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
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from starlette.requests import Request

from .deps import (
    get_openai_client,
    get_optional_user,
    limiter,
    query_analyzer,
    search_agent,
)
from src.events.emit import emit_or_warn
from src.events.event_types import EventType, UserEvent
from app.QueryAgent.skillopt_policy import (
    SkillOptPolicyError,
    load_skillopt_policy_from_env,
)
from app.SearchAgent.search_agent import (
    SearchAgent, SearchCapacityExceeded, apply_search_filters, classify_search_route,
)
from src.utils.paper_utils import generate_doc_id, generate_result_key

logger = logging.getLogger(__name__)

# HybridRanker (optional) - search_agent의 similarity_calculator 재사용.
#
# F-07 fix: the import MUST crash loudly — a missing `HybridRanker` symbol
# is a dev-time configuration error (wrong module path, missing dependency),
# not a runtime condition to hide. A prior hotfix (12b424f era) was
# reintroduced where both ImportError and constructor failure were caught
# by a broad ``except Exception`` — every search silently lost ranking.
from src.graph_rag.hybrid_ranker import CROSS_ENCODER_RRF_WEIGHT, HybridRanker  # noqa: E402

# Track ranker-degradation reasons so operators + API consumers see the
# degradation instead of it being silent-ranking-skipped. Exposed on
# ``SearchResponse.degraded``.
_RANKER_DEGRADATION_REASONS: List[str] = []

try:
    _hybrid_ranker: Optional[HybridRanker] = HybridRanker(
        similarity_calculator=search_agent.similarity_calculator
    )
except Exception as _hr_exc:
    # Constructor-time failure: keep the process alive (ranking is optional
    # for search to return *something*), but shout about it at startup AND
    # surface the degradation on every search response so it is not silent.
    logger.warning(
        "[Search] HybridRanker constructor failed, ranking disabled: %s: %s",
        type(_hr_exc).__name__,
        _hr_exc,
    )
    _hybrid_ranker = None
    _RANKER_DEGRADATION_REASONS.append("ranker_unavailable")


def _current_degradation_markers() -> Optional[List[str]]:
    """Return the list of active degradation markers, or ``None`` if healthy.

    Kept as a function so tests can monkeypatch the underlying list and
    observe the marker propagating into ``SearchResponse.degraded``.
    """
    if not _RANKER_DEGRADATION_REASONS:
        return None
    # Return a copy so callers cannot mutate our module state.
    return list(_RANKER_DEGRADATION_REASONS)

router = APIRouter(prefix="/api", tags=["search"])

# This owner has no providers: mocking a provider singleton cannot disable admission.
_router_operation_owner = SearchAgent.__new__(SearchAgent)
_router_shutdown = threading.Event()
_router_admission_lock = threading.Lock()
_router_request_stops: set[threading.Event] = set()


async def _run_owned(operation, function, timeout, stop_event=None):
    if timeout <= 0 or (stop_event is not None and stop_event.is_set()):
        raise asyncio.TimeoutError
    with _router_admission_lock:
        if _router_shutdown.is_set():
            raise SearchCapacityExceeded(operation)
        generation = _router_operation_owner._begin_operation_generation(operation)
        try:
            future = generation.submit(function)
        except BaseException:
            generation.close()
            raise
    try:
        return await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)
    finally:
        generation.close()


async def _run_snapshot_search(operation, function, deadline, stop, snapshots, metadata):
    """Marshal collector snapshots; close publication before returning or cancelling."""
    loop = asyncio.get_running_loop()
    closed = False
    known_sources = set()

    def deliver(snapshot):
        if closed or stop.is_set():
            return
        snapshot_metadata = snapshot.get("_metadata", {})
        completed = snapshot_metadata.get("timings", {})
        known_sources.update(source for source in snapshot if not source.startswith("_"))
        snapshots.clear()
        snapshots.update({source: papers for source, papers in snapshot.items()
                          if not source.startswith("_") and (papers or source in completed)})
        metadata.clear()
        metadata.update(snapshot_metadata)

    def receive(snapshot):
        private = copy.deepcopy(snapshot)
        try:
            loop.call_soon_threadsafe(deliver, private)
        except RuntimeError:
            # A closed request loop cannot accept late collector output.
            return

    try:
        return await _run_owned(
            operation,
            partial(function, deadline=deadline, stop_event=stop, snapshot_callback=receive),
            max(0.0, deadline - time.monotonic()),
            stop,
        )
    except asyncio.TimeoutError:
        stop.set()
        metadata["partial"] = True
        for source in known_sources - snapshots.keys():
            metadata.setdefault("timeouts", {})[source] = True
            metadata.setdefault("modes", {})[source] = "timeout"
        raise
    finally:
        closed = True


async def _run_legacy_search(function, timeout, *, smart=False):
    stop = threading.Event()
    deadline = time.monotonic() + timeout
    snapshots, metadata = {}, {}
    with _router_admission_lock:
        _router_request_stops.add(stop)
    try:
        try:
            return await _run_snapshot_search("search_legacy", function, deadline, stop, snapshots, metadata)
        except asyncio.TimeoutError:
            stop.set()
            if not snapshots:
                raise
            metadata = copy.deepcopy(metadata)
            metadata["partial"] = True
            if smart:
                return {"papers": [paper for papers in snapshots.values() for paper in papers], "metadata": metadata}
            return {**copy.deepcopy(snapshots), "_metadata": metadata}
    finally:
        stop.set()
        with _router_admission_lock:
            _router_request_stops.discard(stop)


def _finalize_results(results, filters, sources):
    """One publication boundary for fresh, graph-added, cached and partial hits."""
    keys = list(dict.fromkeys([*sources, *[key for key in results if not key.startswith("_")]]))
    papers = []
    for source in keys:
        for paper in results.get(source, []):
            record = copy.deepcopy(paper)
            record["_result_source"] = source
            papers.append(record)
    papers.sort(key=lambda paper: paper.get("_rank", float("inf")))
    order = {generate_result_key(paper): index for index, paper in reversed(list(enumerate(papers)))}
    papers = search_agent.deduplicator.deduplicate(papers)
    papers.sort(key=lambda paper: order.get(generate_result_key(paper), paper.get("_rank", float("inf"))))
    papers, drops = apply_search_filters(papers, filters)
    rebuilt = {source: [] for source in keys}
    published = []
    for paper in papers:
        source = paper.get("_result_source") or sources[0]
        if source not in rebuilt:
            source = sources[0]
        if len(rebuilt[source]) >= filters.get("max_results", 100):
            continue
        paper.setdefault("source", source)
        paper.pop("_source_tag", None)
        paper["result_key"] = generate_result_key(paper)
        if not paper.get("doc_id"):
            paper["doc_id"] = generate_doc_id(paper.get("title", ""))
        rebuilt[source].append(paper)
        published.append(paper)
    _stamp_global_rank(published)
    return rebuilt, drops


def _admit_save(query, results, collect_refs=False, extract_text=False, max_refs=10, *, fast_mode=False, disconnect_event=None, completion_event=None):
    if not any(results.values()):
        return "no_results"
    with _router_admission_lock:
        if disconnect_event is not None and disconnect_event.is_set():
            return "not_admitted_disconnect"
        if _router_shutdown.is_set():
            return "not_admitted_shutdown"
        try:
            generation = _router_operation_owner._begin_operation_generation("search_save_enrichment")
        except SearchCapacityExceeded:
            return "not_admitted_capacity"
        try:
            snapshot = copy.deepcopy(results)
            deadline = time.monotonic() + 30
            submitted = threading.Event()

            def save_job():
                submitted.wait()
                try:
                    _enrich_papers_background(
                        query, snapshot, collect_refs, extract_text, max_refs,
                        fast_mode=fast_mode, deadline=deadline, disconnect_event=disconnect_event,
                    )
                finally:
                    if completion_event is not None:
                        completion_event.set()
                    generation.close()

            generation.submit(save_job)
            submitted.set()
        except BaseException:
            generation.close()
            raise
    return "accepted"


def _search_capacity_unavailable(error: SearchCapacityExceeded) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=str(error),
        headers={"Retry-After": "1"},
    )


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
    max_results: int = Field(default=20, ge=1, le=100)
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

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, sources):
        allowed = {"arxiv", "connected_papers", "google_scholar", "openalex", "dblp", "openalex_korean"}
        if not sources or any(source not in allowed for source in sources):
            raise ValueError("Unsupported or empty sources")
        return sorted(set(sources))

    @field_validator("sort_by")
    @classmethod
    def validate_sort(cls, value):
        if value not in {"relevance", "submittedDate", "lastUpdatedDate"}:
            raise ValueError("Unsupported sort")
        return value

    @model_validator(mode="after")
    def validate_years(self):
        if any(year is not None and not 1 <= year <= 9999 for year in (self.year_start, self.year_end)):
            raise ValueError("Invalid year")
        if self.year_start is not None and self.year_end is not None and self.year_start > self.year_end:
            raise ValueError("Reversed year range")
        return self


class SearchResponse(BaseModel):
    results: Dict[str, List[Dict[str, Any]]]
    total: int
    query_analysis: Optional[Dict[str, Any]] = None
    # P0/P1 latency observability metadata. Optional fields preserve response
    # compatibility for existing clients while making fast-path/source timing
    # behavior explicit for newer callers and operators.
    stage_timings: Optional[Dict[str, float]] = None
    stage_modes: Optional[Dict[str, Any]] = None
    source_timings: Optional[Dict[str, float]] = None
    source_timeouts: Optional[Dict[str, bool]] = None
    cache_hit: bool = False
    quality_mode: str = "standard"
    metadata: Optional[Dict[str, Any]] = None
    # F-07: non-None when some search subsystem is degraded (e.g. ranker
    # unavailable). Contains short machine-readable markers such as
    # ``"ranker_unavailable"`` — the frontend and operators key off these.
    degraded: Optional[List[str]] = None
    # Identifier the client echoes back on POST /api/search/click so a click
    # can be joined to the search that produced it.
    query_hash: Optional[str] = None


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
    max_results: int = Field(default=20, ge=1, le=100)
    context: str = ""
    save_papers: bool = True


class LLMSearchResponse(BaseModel):
    results: Dict[str, List[Dict[str, Any]]]
    total: int
    metadata: Dict[str, Any]


# ── Helper ─────────────────────────────────────────────────────────────

def _stamp_searched_by(results: Dict[str, List[Dict[str, Any]]], username: Optional[str]):
    """Add/overwrite searched_by field on all papers.

    This is idempotent per caller: the value is overwritten, not appended.
    That invariant is relied on by the cache path — a cache body written by
    user A can be safely re-stamped for user B on read (see F-03 fix).
    """
    stamp = username or "(unknown)"
    for papers in results.values():
        for paper in papers:
            paper["searched_by"] = stamp


def _strip_searched_by(results: Dict[str, List[Dict[str, Any]]]) -> None:
    """Remove searched_by from every paper entry in-place.

    Used defensively on cache READ to scrub any stamp that a previous
    (pre-F-03) write may have persisted on disk, AND used on cache WRITE
    input so we never persist a per-user stamp in the shared cache body.
    """
    for papers in results.values():
        if not isinstance(papers, list):
            continue
        for paper in papers:
            if isinstance(paper, dict):
                paper.pop("searched_by", None)


def _enrich_papers_background(query, results, collect_refs, extract_text, max_refs, *, fast_mode=False, deadline=None, disconnect_event=None):
    """Best effort callback; a running call keeps its admission until completion."""
    deadline = deadline if deadline is not None else time.monotonic() + 30
    def allowed():
        return not _router_shutdown.is_set() and time.monotonic() < deadline
    if not allowed():
        logger.info("[Search save] Skipped expired_or_shutdown")
        return
    try:
        saved = search_agent.save_papers(results, query, generate_embeddings=False, update_graph=False)
        if saved.get("success") is False:
            logger.error("[Search save] Persistence failed: %s", saved.get("error", "unspecified"))
            return
        logger.info("[Search save] Persistence completed new_papers=%s within_budget=%s", saved.get("new_papers", 0), allowed())
        if fast_mode or not allowed() or (disconnect_event is not None and disconnect_event.is_set()) or not saved.get("new_papers", 0):
            return
        if collect_refs and allowed():
            search_agent.collect_references(max_refs, min(saved["new_papers"], 10))
        if extract_text and allowed() and not (disconnect_event is not None and disconnect_event.is_set()):
            search_agent.extract_full_texts(saved.get("new_papers"))
        logger.info("[Search save] Completed within_budget=%s", allowed())
    except Exception:
        logger.exception("[Search save] Callback failed")


# ── Search cache ──────────────────────────────────────────────────────
SEARCH_CACHE_DIR = Path("data/cache/search_cache")
SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# BUMP THIS STRING when ranking algorithm, result schema, or source list changes.
# Old cache entries become unreachable (keys differ) and self-resolve within TTL (1h).
_CACHE_SCHEMA_VERSION = "v4-meaning-identity-finalization"

_search_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()
CACHE_TTL_SECONDS = 3600  # 1시간
CACHE_MAX_SIZE = 200  # 최대 캐시 엔트리 수


_RECOMMENDATION_STOPWORDS = frozenset({
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "is", "are", "and", "or", "but", "not", "this", "that", "these", "those",
})


def _normalize_query_for_cache(query: str) -> str:
    """Normalize explicit Unicode, case and whitespace equivalence only."""
    q = unicodedata.normalize("NFKC", query).strip().lower()
    q = re.sub(r"\s+", " ", q)
    return q.casefold()




def _recommendation_normalized_terms(query: str, *, max_terms: int = 8) -> list[str]:
    """Return bounded privacy-safe query terms for recommendation signals.

    This deliberately stores only normalized tokens, not the raw query text.
    """
    normalized = unicodedata.normalize("NFKC", query).lower()
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣_\-]{1,48}", normalized):
        clean = token.strip("_-")
        if len(clean) < 2 or clean.isdigit() or clean in _RECOMMENDATION_STOPWORDS:
            continue
        if clean not in terms:
            terms.append(clean)
        if len(terms) >= max_terms:
            break
    return terms


def _query_hash(query: str) -> str:
    """Stable identifier tying a SEARCH_CLICK back to its QUERY_SUBMIT.

    Returned to the client so the browser does not have to reimplement this
    and drift from the server's definition.
    """
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]


def _skillopt_result_cache_namespace(
    *, apply_skillopt_policy: bool
) -> Tuple[str, str]:
    """Return the validated SkillOpt namespace and why that namespace was chosen.

    The reason is reported separately because every fallback path collapses to
    the ``"baseline"`` namespace: without it, an intentionally disabled policy
    and a misconfigured one are indistinguishable from the response alone.
    """
    if not apply_skillopt_policy:
        return "baseline", "not_requested"
    try:
        policy = load_skillopt_policy_from_env()
    except SkillOptPolicyError as e:
        logger.warning(
            "[API] SkillOpt search policy excluded from result cache namespace by invalid configuration: %s",
            e,
        )
        return "baseline", "invalid_config"
    if not policy.enabled:
        return "baseline", policy.reason
    return policy.content_hash, policy.reason


def _compute_cache_key(query: str, sources: List[str], filters: Dict[str, Any]) -> str:
    """검색 요청에 대한 캐시 키 생성 (schema version + fast_mode 포함).

    ``_CACHE_SCHEMA_VERSION`` 을 key_data에 포함시켜, 랭킹 알고리즘/결과
    스키마가 변경될 때 상수를 bump하면 기존 캐시 항목이 자동으로 무효화된다.
    """
    key_data = {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "query": _normalize_query_for_cache(query),
        "sources": sorted(set(sources)),
        "search_context": _normalize_query_for_cache(filters.get("search_context", "")),
        "year_start": filters.get("year_start"),
        "year_end": filters.get("year_end"),
        "author": filters.get("author"),
        "category": filters.get("category"),
        "sort_by": filters.get("sort_by", "relevance"),
        "fast_mode": filters.get("fast_mode", False),
        # max_results bounds how many papers each source returns, so a body
        # cached for a small request is a *truncated* answer for a larger one.
        # Leaving it out let a max_results=10 search serve max_results=50
        # callers for the full hour of TTL.
        "max_results": filters.get("max_results"),
        # use_llm_search selects an entirely different retrieval pipeline
        # (llm_context_search). Both pipelines collapse to the "baseline"
        # SkillOpt namespace while the policy is off, so without this field
        # their result bodies shared one cache key.
        "use_llm_search": filters.get("use_llm_search", False),
        "skillopt_policy": filters.get("skillopt_policy", "baseline"),
    }
    key_str = json.dumps(key_data, sort_keys=True)
    return hashlib.sha256(key_str.encode()).hexdigest()[:16]


def _cache_entry_passes_guard(entry: Dict[str, Any], *, require_academic_guard: bool) -> bool:
    if not require_academic_guard:
        return True
    metadata = entry.get("metadata") if isinstance(entry, dict) else None
    return bool(isinstance(metadata, dict) and metadata.get("academic_guard_passed") is True)


def _get_cached_result(cache_key: str, *, require_academic_guard: bool = False) -> Optional[Dict[str, Any]]:
    """인메모리 → 파일 순서로 캐시 조회.

    F-03 defensive behaviour: any ``searched_by`` stamp found in the cached
    payload (e.g. legacy on-disk entries written before the F-03 fix) is
    stripped before returning. The caller is responsible for re-stamping
    with the current request's username via ``_stamp_searched_by``.

    ``require_academic_guard=True`` is used only by the pre-analysis fast
    path. It prevents legacy/prefetch entries from bypassing the current
    non-academic guard; those entries can still be reused after classification.
    """
    now = datetime.now()

    # 1. 인메모리 캐시
    with _cache_lock:
        if cache_key in _search_cache:
            entry = _search_cache[cache_key]
            if datetime.fromisoformat(entry["expires_at"]) > now:
                if not _cache_entry_passes_guard(entry, require_academic_guard=require_academic_guard):
                    logger.debug("[Cache] HIT blocked by academic guard: %s", cache_key)
                    return None
                logger.debug("[Cache] HIT (memory): %s", cache_key)
                results = copy.deepcopy(entry["results"])
                _strip_searched_by(results)
                return results
            else:
                del _search_cache[cache_key]

    # 2. 파일 캐시
    cache_file = SEARCH_CACHE_DIR / f"{cache_key}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                entry = json.load(f)
            if datetime.fromisoformat(entry["expires_at"]) > now:
                if not _cache_entry_passes_guard(entry, require_academic_guard=require_academic_guard):
                    logger.debug("[Cache] FILE HIT blocked by academic guard: %s", cache_key)
                    return None
                # Strip before memoizing so future memory hits are also clean.
                _strip_searched_by(entry["results"])
                with _cache_lock:
                    _search_cache[cache_key] = entry
                logger.debug("[Cache] HIT (file): %s", cache_key)
                return copy.deepcopy(entry["results"])
            else:
                cache_file.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("[Cache] File read error: %s", e)

    logger.debug("[Cache] MISS: %s", cache_key)
    return None


def _set_cache(cache_key: str, results: Dict[str, Any], ttl_seconds: int = CACHE_TTL_SECONDS, *, academic_guard_passed: bool = False, stop_event: Optional[threading.Event] = None, deadline: Optional[float] = None):
    """Prepare privately, then publish only while the foreground still owns it."""
    import tempfile
    now = datetime.now()
    sanitized = copy.deepcopy(results)
    _strip_searched_by(sanitized)
    entry = {"results": sanitized, "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(), "cached_at": now.isoformat(), "metadata": {"cache_schema_version": _CACHE_SCHEMA_VERSION, "academic_guard_passed": academic_guard_passed}}
    def expired():
        return ((stop_event is not None and stop_event.is_set()) or (deadline is not None and time.monotonic() >= deadline))
    if expired():
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=SEARCH_CACHE_DIR, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(entry, handle, ensure_ascii=False)
        with _cache_lock:
            if expired():
                return
            if len(_search_cache) >= CACHE_MAX_SIZE:
                for key in [key for key, value in _search_cache.items() if datetime.fromisoformat(value["expires_at"]) <= now]:
                    del _search_cache[key]
                if len(_search_cache) >= CACHE_MAX_SIZE:
                    del _search_cache[min(_search_cache, key=lambda key: _search_cache[key]["cached_at"])]
            temporary.replace(SEARCH_CACHE_DIR / f"{cache_key}.json")
            _search_cache[cache_key] = entry
    except Exception:
        logger.exception("[Cache] Write failed")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _persist_last_search(results, stop_event, deadline):
    """Keep the existing DeepAgent handoff outside the event loop."""
    import tempfile
    temporary = None
    directory = Path("data/cache")
    try:
        if stop_event.is_set() or time.monotonic() >= deadline:
            return
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump([paper for papers in results.values() for paper in papers], handle, ensure_ascii=False)
        if not stop_event.is_set() and time.monotonic() < deadline:
            temporary.replace(directory / "last_search_results.json")
    except Exception:
        logger.exception("[Search] DeepAgent handoff write failed")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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


def _log_cache_file_count() -> None:
    """서버 시작 시 캐시 디렉터리의 전체 파일 수를 기록한다.

    파일은 삭제하지 않는다. 운영자가 직접 정리할 수 있도록 카운트만 남긴다.
    """
    try:
        all_files = list(SEARCH_CACHE_DIR.glob("*.json"))
        logger.info(
            "[Cache] schema=%s, total cache files=%d (orphaned files from old schemas remain on disk)",
            _CACHE_SCHEMA_VERSION,
            len(all_files),
        )
    except Exception as e:
        logger.warning("[Cache] Schema mismatch count error: %s", e)


_CACHE_MAINTENANCE_INTERVAL_SECONDS = 1800.0
_BACKGROUND_JOIN_TIMEOUT_SECONDS = 5.0


def _periodic_cache_maintenance(stop_event: threading.Event) -> None:
    """Clean expired cache entries every thirty minutes until shutdown."""
    while not stop_event.wait(_CACHE_MAINTENANCE_INTERVAL_SECONDS):
        try:
            _cleanup_expired_cache()
        except Exception as e:
            logger.warning("[Cache] Periodic cleanup error: %s", e)



























class _BackgroundWorkerGeneration:
    """One maintenance worker with an immutable stop signal."""

    def __init__(
        self,
        stop_event: threading.Event,
        cache_thread: threading.Thread,
    ) -> None:
        self.stop_event = stop_event
        self.threads = (cache_thread,)


_background_workers_lock = threading.Lock()
_background_generation: Optional[_BackgroundWorkerGeneration] = None
_cache_maintenance_thread: Optional[threading.Thread] = None


def _active_search_operations():
    active = []
    for owner in (_router_operation_owner, search_agent):
        if not isinstance(owner, SearchAgent):
            continue
        lock, operations = owner._operation_generation_state()
        with lock:
            active.extend(operation for generations in operations.values() for operation in generations)
    return active


def start_search_background_workers() -> bool:
    """Start maintenance without overlapping a draining generation."""
    global _background_generation, _cache_maintenance_thread
    with _background_workers_lock, _router_admission_lock:
        if _background_generation and any(thread.is_alive() for thread in _background_generation.threads):
            return False
        if _router_shutdown.is_set() and _active_search_operations():
            return False
        _router_shutdown.clear()
        stop = threading.Event()
        thread = threading.Thread(target=_periodic_cache_maintenance, args=(stop,), daemon=True, name="cache-maintenance")
        _background_generation = _BackgroundWorkerGeneration(stop, thread)
        _cache_maintenance_thread = thread
        _cleanup_expired_cache()
        _log_cache_file_count()
        thread.start()
        return True


def stop_search_background_workers(join_timeout: float = _BACKGROUND_JOIN_TIMEOUT_SECONDS) -> bool:
    """Stop new stages; running operations remain charged until drained."""
    global _background_generation, _cache_maintenance_thread
    with _router_admission_lock:
        _router_shutdown.set()
        for stop_event in _router_request_stops:
            stop_event.set()
        active = _active_search_operations()
        for operation in active:
            operation.close()
    with _background_workers_lock:
        generation = _background_generation
        if generation:
            generation.stop_event.set()
    deadline = time.monotonic() + max(0.0, join_timeout)
    if generation:
        for thread in generation.threads:
            if thread is not threading.current_thread():
                thread.join(max(0.0, deadline - time.monotonic()))
        with _background_workers_lock:
            if any(thread.is_alive() for thread in generation.threads):
                return False
            if _background_generation is generation:
                _background_generation = None
                _cache_maintenance_thread = None
    return not _active_search_operations()


# ── Endpoints ──────────────────────────────────────────────────────────

# Endpoint-level timeout constants (seconds)
_ANALYZE_TIMEOUT = 15
_LLM_SEARCH_TIMEOUT = 60
_SMART_SEARCH_TIMEOUT = 60
_SEARCH_TIMEOUT = 100           # 전체 검색 파이프라인 (분석+검색+랭킹)
_SOURCE_SEARCH_TIMEOUT = 40     # 멀티소스 검색 단계만
_GRAPHRAG_TIMEOUT = 5           # GraphRAG 확장
_RANKING_TIMEOUT = 25           # HyDE + hybrid ranking
_MIN_BUDGET_FOR_GRAPHRAG = 18

_MIN_BUDGET_FOR_HYDE_HARD = 28
_MAX_RANKING_CANDIDATES = 80


def _remaining_budget(start_time: float, total_budget: int = _SEARCH_TIMEOUT) -> float:
    """Return remaining monotonic budget for the current search request."""
    return max(0.0, total_budget - (time.monotonic() - start_time))


def _ranking_candidate_cap(max_results: int) -> int:
    """Bound ranking input size while keeping enough recall for later stages."""
    return min(max(max_results * 2, 40), _MAX_RANKING_CANDIDATES)


def _interleave_source_candidates(
    results: Dict[str, List[Dict[str, Any]]],
    source_keys: List[str],
    limit: int,
) -> List[Dict[str, Any]]:
    """Preserve source diversity when capping ranking candidates."""
    queues = {source: collections.deque(results.get(source, [])) for source in source_keys}
    merged: List[Dict[str, Any]] = []

    while len(merged) < limit:
        progressed = False
        for source in source_keys:
            queue = queues.get(source)
            if not queue:
                continue
            merged.append(queue.popleft())
            progressed = True
            if len(merged) >= limit:
                break
        if not progressed:
            break

    return merged


def _stamp_global_rank(
    ranked_papers: List[Dict[str, Any]],
    results: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> None:
    """Write each paper's global position onto the paper itself as ``_rank``.

    The response groups papers by source (``Dict[source, papers]``), which
    throws away the cross-source order the ranker just computed: a client
    that iterates the buckets sees every arXiv paper, then every Scholar
    paper, and never the fused ranking. Carrying the rank *on the paper*
    means the order survives both the bucketing and the result cache — a
    cached body already contains ``_rank`` on every paper, so warm requests
    keep the same order without re-ranking.

    Papers the ranker never saw (beyond ``_MAX_RANKING_CANDIDATES``, or when
    ranking was skipped) are stamped after the ranked ones, preserving their
    source order. They stay in the response; they just sort last.
    """
    rank = 0
    for paper in ranked_papers:
        paper["_rank"] = rank
        rank += 1
    for papers in (results or {}).values():
        for paper in papers:
            if "_rank" not in paper:
                paper["_rank"] = rank
                rank += 1


async def _dedup_and_rank_deep_search(
    query: str,
    papers: List[Dict[str, Any]],
    intent: str,
    *, deadline=None, stop_event=None,
) -> List[Dict[str, Any]]:
    """Give the deep-search paths the same dedup and fusion as ``/api/search``.

    Both deep-search endpoints returned whatever order the ReAct turns happened
    to append in — turn 1's hits, then turn 2's, then graph expansion — with no
    cross-source deduplication. A paper found by three turns appeared three
    times, and the ranking signals never ran at all, so the two search entry
    points disagreed about what "best" means.

    Degrades to the input order on any failure: deep search is already slow and
    an unranked answer beats no answer.
    """
    if not papers:
        return papers
    deadline = deadline if deadline is not None else time.monotonic() + _RANKING_TIMEOUT

    try:
        papers = search_agent.deduplicator.deduplicate(papers)
    except Exception as exc:  # noqa: BLE001 - ranking still worth attempting
        logger.warning("[Deep Search] Dedup failed (continuing): %s", exc)

    if _hybrid_ranker is None:
        _stamp_global_rank(papers)
        for paper in papers:
            paper["result_key"] = generate_result_key(paper)
        return papers

    try:
        ranked = await asyncio.wait_for(
            _run_owned("search_rank", partial(_hybrid_ranker.rank_papers, query=query,
            papers=copy.deepcopy(papers),
            intent=intent,
            use_rrf=True, deadline=deadline, stop_event=stop_event), max(0, deadline - time.monotonic()), stop_event),
            timeout=max(0, deadline - time.monotonic()),
        )
        papers = list(ranked)
    except asyncio.TimeoutError:
        logger.warning(
            "[Deep Search] Ranking timed out after %ds (returning dedup order)",
            _RANKING_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Deep Search] Ranking failed (returning dedup order): %s", exc)

    _stamp_global_rank(papers)
    for paper in papers:
        paper["result_key"] = generate_result_key(paper)
    return papers


async def _evaluate_deep_results(query, intent, papers, result, deadline, stop):
    """Rubric expiry degrades enrichment, never discards retrieved papers."""
    metadata = result.setdefault("metadata", {})
    if stop.is_set() or time.monotonic() >= deadline:
        metadata.update(partial=True, evaluation_mode="skipped_budget")
        return {}
    from app.QueryAgent.rubric_evaluator import RubricEvaluator
    try:
        evaluation = await asyncio.wait_for(
            RubricEvaluator().evaluate(query=query, intent=intent, papers=papers),
            timeout=max(0, deadline - time.monotonic()),
        )
        metadata["evaluation_mode"] = "completed"
        return evaluation
    except asyncio.TimeoutError:
        metadata.update(partial=True, evaluation_mode="timeout")
        return {}


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
        analysis = await asyncio.wait_for(
            _run_owned("search_analysis", partial(query_analyzer.analyze_query, request.query), _ANALYZE_TIMEOUT),
            timeout=_ANALYZE_TIMEOUT,
        )
        logger.info("[API] Analysis result: intent=%s, confidence=%s", analysis.get("intent"), analysis.get("confidence"))
        return QueryAnalysisResponse(**analysis)
    except SearchCapacityExceeded as e:
        raise _search_capacity_unavailable(e)
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


        results = await _run_legacy_search(
            partial(
                search_agent.llm_context_search,
                query=request.query,
                max_results_per_source=request.max_results,
                context=request.context,
            ), _LLM_SEARCH_TIMEOUT,
        )

        metadata = results.pop("_metadata", {})
        results, metadata["filter_drops"] = _finalize_results(
            results, {"max_results": request.max_results}, list(results) or ["arxiv"],
        )
        total = sum(len(papers) for papers in results.values())
        search_time = time.time() - start_time

        logger.info("[API] LLM Search completed: %s papers in %.2fs", total, search_time)

        _stamp_searched_by(results, username)
        metadata["save_status"] = _admit_save(request.query, results) if request.save_papers else "not_requested"

        metadata["search_time"] = round(search_time, 2)

        return LLMSearchResponse(results=results, total=total, metadata=metadata)

    except SearchCapacityExceeded as e:
        raise _search_capacity_unavailable(e)
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


        result = await _run_legacy_search(
            partial(search_agent.smart_search, query=request.query, max_results=request.max_results),
            _SMART_SEARCH_TIMEOUT, smart=True,
        )

        search_time = time.time() - start_time
        result["metadata"]["search_time"] = round(search_time, 2)

        logger.info("[API] Smart Search completed: %s papers in %.2fs", len(result["papers"]), search_time)

        results_by_source, drops = _finalize_results(
            {"smart": result["papers"]}, {"max_results": request.max_results}, ["smart"],
        )
        result["papers"] = results_by_source["smart"]
        _stamp_searched_by(results_by_source, username)
        result["metadata"]["filter_drops"] = drops
        result["metadata"]["save_status"] = _admit_save(request.query, results_by_source) if request.save_papers else "not_requested"

        return result

    except SearchCapacityExceeded as e:
        raise _search_capacity_unavailable(e)
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

    deadline, stop = time.monotonic() + _SEARCH_TIMEOUT, threading.Event()
    with _router_admission_lock:
        _router_request_stops.add(stop)
    try:
        start_time = time.time()
        logger.info("[API] Deep Search: %s", request.query)

        # 1. Query analysis
        analysis = {}
        if query_analyzer:
            try:

                analysis = await asyncio.wait_for(
                    _run_owned("search_analysis", partial(query_analyzer.analyze_query, request.query), min(10, max(0, deadline-time.monotonic())), stop),
                    timeout=max(0, deadline-time.monotonic()),
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
        result = await react_agent.search(query=request.query, analysis=analysis, max_results=request.max_results or 20, deadline=deadline, stop_event=stop)

        # 2.5. GraphRAG auxiliary expansion
        try:
            react_papers = result.get("papers", [])
            if react_papers:

                graphrag_papers = await _run_owned("search_graph", partial(_graphrag_expand, request.query, copy.deepcopy(react_papers), 15), min(_GRAPHRAG_TIMEOUT, max(0, deadline-time.monotonic())), stop)
                if graphrag_papers:
                    for p in graphrag_papers:
                        p["_source"] = "graphrag"
                    result["papers"].extend(graphrag_papers)
                    logger.info("[Deep Search][GraphRAG] Added %d papers from graph expansion", len(graphrag_papers))
        except Exception as e:
            logger.warning("[Deep Search][GraphRAG] Expansion failed (continuing): %s", e)

        # 2.6. Dedup + hybrid ranking, before the rubric so the evaluation
        # scores the set the caller actually receives.
        result["papers"] = await _dedup_and_rank_deep_search(request.query, result.get("papers", []), analysis.get("intent", "paper_search"), deadline=deadline, stop_event=stop)

        evaluation = await _evaluate_deep_results(
            request.query, analysis.get("intent", "paper_search"),
            result.get("papers", []), result, deadline, stop,
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
                    src = paper.get("_source", paper.get("source", "arxiv"))
                    results_by_source.setdefault(src, []).append(paper)
                _stamp_searched_by(results_by_source, username)
                result.setdefault("metadata", {}).update(save_status=_admit_save(request.query, results_by_source))
            except Exception as e:
                logger.error("[Deep Search] Save papers error: %s", e)

        return result

    except SearchCapacityExceeded as e:
        raise _search_capacity_unavailable(e)
    except asyncio.TimeoutError:
        logger.error("[API] Deep Search timed out")
        raise HTTPException(status_code=504, detail="Deep search timed out")
    except Exception as e:
        logger.error("[API] Deep Search failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Deep search failed: {str(e)}")
    finally:
        stop.set()
        with _router_admission_lock:
            _router_request_stops.discard(stop)


@router.post("/search", response_model=SearchResponse)
async def search_papers(request: SearchRequest, username: Optional[str] = Depends(get_optional_user), http_request: Request = None):
    """Publish finalized snapshots; ownership outlives an expired await."""
    started = time.monotonic()
    deadline = started + _SEARCH_TIMEOUT
    stop = threading.Event()
    disconnected = threading.Event()
    save_completed = threading.Event()
    save_accepted = False
    observer_closed = threading.Event()
    observer_deadline = deadline
    async def observe_disconnect():
        while (not observer_closed.is_set() and not save_completed.is_set()
               and not _router_shutdown.is_set() and time.monotonic() < observer_deadline):
            if await http_request.is_disconnected():
                disconnected.set()
                stop.set()
                return
            if observer_closed.is_set():
                return
            await asyncio.sleep(.01)
    with _router_admission_lock:
        if _router_shutdown.is_set():
            raise _search_capacity_unavailable(SearchCapacityExceeded("search_sources"))
        _router_request_stops.add(stop)
    observer = asyncio.create_task(observe_disconnect()) if http_request is not None else None
    sources = request.sources
    policy_requested = not request.fast_mode and not request.use_llm_search
    namespace, policy_reason = _skillopt_result_cache_namespace(apply_skillopt_policy=policy_requested)
    filters = {key: getattr(request, key) for key in ("max_results", "sort_by", "year_start", "year_end", "author", "category", "fast_mode", "use_llm_search", "search_context")}
    filters.update(sources=sources, original_query=request.query, skillopt_policy=namespace)
    cache_key = _compute_cache_key(request.query, sources, filters)
    timings = {}
    modes = {"fast_mode": request.fast_mode, "use_llm_search": request.use_llm_search, "skillopt_policy_cache_namespace": namespace, "skillopt_policy_requested": policy_requested, "skillopt_policy_reason": policy_reason}
    source_metadata = {"timings": {}, "timeouts": {}, "modes": {}}
    snapshots = {}
    analysis = None
    guard = False
    healthy = True
    cache_hit = False
    results = {source: [] for source in sources}
    search_query = request.query
    route = classify_search_route(request.query)
    cached_metadata = {}
    finalization_drops = collections.Counter()

    def finalize(value):
        finalized, dropped = _finalize_results(value, filters, sources)
        finalization_drops.update(dropped)
        return finalized

    async def stage(name, function, timeout):
        before = time.monotonic()
        try:
            return await _run_owned(name, function, min(timeout, max(0.0, deadline - before)), stop)
        finally:
            timings[name] = round(timings.get(name, 0.0) + time.monotonic() - before, 3)

    try:
        cached = await stage("search_cache_io", partial(_get_cached_result, cache_key, require_academic_guard=True), 2)
        if cached is not None:
            cached_metadata = cached.pop("_metadata", {})
            results = cached
            cache_hit = True
            modes.update(cache_fast_path=True, query_analysis_mode="skipped_cache_hit", ranking_mode="skipped_cache_hit", source_search_mode="skipped_cache_hit")
            search_query = cached_metadata.get("executed_query", request.query)
        else:
            modes["cache_fast_path"] = False
            if route["kind"] != "topic":
                guard = True
                modes["query_analysis_mode"] = "skipped_exact_route"
            elif query_analyzer:
                try:
                    analysis = await stage("search_analysis", partial(query_analyzer.analyze_and_prepare, request.query, apply_skillopt_policy=policy_requested), _ANALYZE_TIMEOUT)
                    if analysis.get("analysis_status"):
                        guard = False
                        healthy = False
                        modes["query_analysis_mode"] = "original_query_fallback_returned"
                    else:
                        guard = analysis.get("is_academic") is True
                        modes["query_analysis_mode"] = "unified_llm"
                except (asyncio.TimeoutError, SearchCapacityExceeded) as exc:
                    healthy = False
                    modes["query_analysis_mode"] = "original_query_fallback_" + type(exc).__name__
                except Exception:
                    healthy = False
                    modes["query_analysis_mode"] = "original_query_fallback_error"
            else:
                modes["query_analysis_mode"] = "disabled_no_api_key"
            modes["academic_guard_passed"] = guard
            blocked = analysis is not None and not analysis.get("analysis_status") and analysis.get("is_academic") is False
            if not blocked:
                if route["kind"] == "topic" and analysis and not analysis.get("analysis_status") and analysis.get("confidence", 0) >= 0.8:
                    improved = analysis.get("improved_query")
                    if isinstance(improved, str) and improved.strip():
                        search_query = improved.strip()
                    if isinstance(analysis.get("source_queries"), dict):
                        filters["source_queries"] = copy.deepcopy(analysis["source_queries"])
                filters.update(_deadline=deadline, _stop_event=stop, _partial_results=snapshots, _metadata=source_metadata)
                if _router_shutdown.is_set():
                    stop.set()
                    raise SearchCapacityExceeded("search_sources")
                before = time.monotonic()
                try:
                    if request.use_llm_search and query_analyzer and route["kind"] == "topic" and not request.fast_mode:
                        modes["source_search_mode"] = "llm_context_search"
                        results = await _run_snapshot_search(
                            "search_llm",
                            partial(search_agent.llm_context_search, search_query, max_results_per_source=request.max_results, context=request.search_context),
                            min(deadline, time.monotonic() + _SOURCE_SEARCH_TIMEOUT),
                            stop, snapshots, source_metadata,
                        )
                        source_metadata.update(results.pop("_metadata", {}))
                    else:
                        modes["source_search_mode"] = "standard_async_multi_source"
                        results = await asyncio.wait_for(search_agent.async_search_with_filters(search_query, filters), timeout=min(_SOURCE_SEARCH_TIMEOUT, max(0.0, deadline - time.monotonic())))
                except asyncio.TimeoutError:
                    healthy = False
                    stop.set()
                    results = copy.deepcopy(snapshots)
                    modes["source_search_mode"] = "timeout_partial"
                    for source in sources:
                        if source not in snapshots:
                            source_metadata.setdefault("timeouts", {})[source] = True
                            source_metadata.setdefault("modes", {})[source] = "timeout"
                timings["source_search"] = round(time.monotonic() - before, 3)
                results = finalize(results)
                if not request.fast_mode and route["kind"] == "topic" and not stop.is_set() and _remaining_budget(started) >= _MIN_BUDGET_FOR_GRAPHRAG:
                    try:
                        graph = await stage("search_graph", partial(_graphrag_expand, request.query, copy.deepcopy([paper for papers in results.values() for paper in papers]), 15), _GRAPHRAG_TIMEOUT)
                        if graph:
                            results["graphrag"] = graph
                        modes["graphrag_mode"] = "enabled"
                    except Exception as exc:
                        healthy = False
                        modes["graphrag_mode"] = type(exc).__name__
                else:
                    modes["graphrag_mode"] = "fast_capability" if request.fast_mode else "skipped"
                results = finalize(results)
                if _hybrid_ranker and any(results.values()) and not stop.is_set():
                    papers = _interleave_source_candidates(results, list(results), _ranking_candidate_cap(request.max_results))
                    try:
                        hyde = not request.fast_mode and route["kind"] == "topic" and _remaining_budget(started) >= _MIN_BUDGET_FOR_HYDE_HARD
                        ranked = await stage("search_rank", partial(_hybrid_ranker.rank_papers, query=request.query, papers=copy.deepcopy(papers), intent=(analysis or {}).get("intent", "paper_search"), openai_client=get_openai_client() if hyde else None, use_rrf=True, fast_mode=request.fast_mode, deadline=min(deadline, time.monotonic() + _RANKING_TIMEOUT), stop_event=stop), _RANKING_TIMEOUT)
                        _stamp_global_rank(ranked)
                        results = _rebuild_results_from_ranked(ranked, list(results))
                        modes["ranking_mode"] = "cheap_rrf" if request.fast_mode else "hybrid_rrf"
                        modes["hyde_mode"] = "enabled" if hyde else "disabled"
                    except Exception as exc:
                        healthy = False
                        modes["ranking_mode"] = "fallback_" + type(exc).__name__
                else:
                    modes["ranking_mode"] = "skipped"
            else:
                modes["source_search_mode"] = "non_academic"
        results = finalize(results)
        drops = {"sources": copy.deepcopy(source_metadata.get("filter_drops", {})), "finalization": dict(finalization_drops)}
        _stamp_searched_by(results, username)
        total = sum(map(len, results.values()))
        source_modes = source_metadata.get("modes", {})
        unhealthy = any(source_metadata.get("timeouts", {}).values()) or any(any(word in str(mode).lower() for word in ("error", "timeout", "circuit", "reject", "capacity")) for mode in source_modes.values())
        healthy = healthy and not unhealthy and not stop.is_set() and not _current_degradation_markers()
        executed_queries = cached_metadata.get("executed_queries", source_metadata.get("executed_queries", {}))
        actual_queries = [query for queries in executed_queries.values() if isinstance(queries, list) for query in queries if isinstance(query, str)]
        if actual_queries and search_query not in actual_queries:
            search_query = actual_queries[0]
        if analysis and not analysis.get("analysis_status") and analysis.get("is_academic") is False:
            search_query = None
        metadata = {"executed_query": search_query, "executed_queries": executed_queries, "routing": source_metadata.get("routing", route), "filter_drops": drops, "save_status": "not_requested", "stage_modes": modes, "cache_hit": cache_hit, "quality_mode": "fast" if request.fast_mode else "standard", "source_timings": dict(source_metadata.get("timings", {})), "source_timeouts": dict(source_metadata.get("timeouts", {}))}
        degradation = list(_current_degradation_markers() or [])
        for stage_name, mode in modes.items():
            if isinstance(mode, str) and any(word in mode.lower() for word in ("fallback", "error", "timeout", "capacity")):
                degradation.append(f"{stage_name}:{mode}")
        if unhealthy:
            degradation.append("source_incomplete")
        metadata["partial"] = bool(source_metadata.get("partial") or unhealthy or stop.is_set() or modes.get("source_search_mode") == "timeout_partial")
        metadata["degraded"] = degradation or None
        if request.save_papers and cache_hit:
            metadata["save_status"] = "skipped_cache"
        if request.fast_mode:
            metadata["optional_enrichment"] = "fast_capability"
        else:
            metadata["graph_save_enrichment"] = "not_requested"
        if not cache_hit and healthy and guard:
            cache_body = copy.deepcopy(results)
            cache_body["_metadata"] = {"executed_query": search_query, "executed_queries": executed_queries}
            try:
                await stage("search_cache_io", partial(_set_cache, cache_key, cache_body, academic_guard_passed=True, stop_event=stop, deadline=min(deadline, time.monotonic() + 2)), 2)
            except (asyncio.TimeoutError, SearchCapacityExceeded):
                modes["cache_write"] = "not_completed"
        await asyncio.sleep(0)
        if total and not cache_hit and not stop.is_set():
            try:
                await stage("search_cache_io", partial(_persist_last_search, copy.deepcopy(results), stop, min(deadline, time.monotonic() + 2)), 2)
            except (asyncio.TimeoutError, SearchCapacityExceeded):
                modes["last_search_write"] = "not_completed"
        await asyncio.sleep(0)
        if request.save_papers and not cache_hit:
            if http_request is not None and await http_request.is_disconnected():
                disconnected.set()
                stop.set()
            metadata["save_status"] = _admit_save(request.query, results, request.collect_references, request.extract_texts, request.max_references_per_paper, fast_mode=request.fast_mode, disconnect_event=disconnected, completion_event=save_completed) if total else "no_results"
            save_accepted = metadata["save_status"] == "accepted"
            if save_accepted:
                observer_deadline = time.monotonic() + 30
        timings["total"] = round(time.monotonic() - started, 3)
        metadata["stage_timings"] = timings
        modes["source_modes"] = source_modes
        if username:
            try:
                emit_or_warn(UserEvent(user_id=username, event_type=EventType.QUERY_SUBMIT, payload={"query_hash": _query_hash(request.query), "normalized_terms": _recommendation_normalized_terms(request.query), "results_count": total, "ranking_applied": modes.get("ranking_mode") in {"cheap_rrf", "hybrid_rrf"}, "ranking_variant": f"ce_w={CROSS_ENCODER_RRF_WEIGHT}", "source_counts": {source: len(papers) for source, papers in results.items()}, "elapsed_ms": int(timings["total"] * 1000), "cache_hit": cache_hit}))
            except Exception as exc:
                logger.warning("[Search analytics] Query event failed: %s", type(exc).__name__)
        return SearchResponse(results=results, total=total, query_hash=_query_hash(request.query), query_analysis=analysis, stage_timings=timings, stage_modes=modes, source_timings=metadata["source_timings"], source_timeouts=metadata["source_timeouts"], cache_hit=cache_hit, quality_mode=metadata["quality_mode"], metadata=metadata, degraded=degradation or None)
    except SearchCapacityExceeded as exc:
        raise _search_capacity_unavailable(exc)
    finally:
        stop.set()
        if observer is not None and not save_accepted:
            observer_closed.set()
            observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)
        with _router_admission_lock:
            _router_request_stops.discard(stop)


# ── Search-click tracking ─────────────────────────────────────────────


class SearchClickRequest(BaseModel):
    """Body for POST /api/search/click."""

    query_hash: str
    paper_id: str
    # 1-based position of the clicked paper in the ranked list the user saw.
    # Optional so older clients keep working; without it a click records that
    # *something* was opened but not where it ranked, which is what MRR and
    # CTR@k need. Bounded to keep a hostile client from writing junk ranks.
    rank: Optional[int] = Field(default=None, ge=1, le=1000)


@router.post("/search/click")
@limiter.limit("60/minute")
async def track_search_click(
    request: Request,
    body: SearchClickRequest,
    username: Optional[str] = Depends(get_optional_user),
) -> dict:
    """Record which paper the user clicked from a search result set.

    Fire-and-forget — failures are logged but never surface to the caller.
    """
    if not (body.query_hash and body.paper_id):
        return {"tracked": False}
    if username:
        try:
            payload: Dict[str, Any] = {
                "query_hash": body.query_hash,
                "paper_id": body.paper_id,
            }
            if body.rank is not None:
                payload["rank"] = body.rank
            emit_or_warn(UserEvent(
                user_id=username,
                event_type=EventType.SEARCH_CLICK,
                payload=payload,
                paper_id=body.paper_id,
            ))
        except Exception:
            logger.debug("failed to emit SEARCH_CLICK event", exc_info=True)
    return {"tracked": username is not None}


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


    async def event_generator():
        """Generate SSE events during deep search execution."""
        deadline, stop = time.monotonic() + _SEARCH_TIMEOUT, threading.Event()
        with _router_admission_lock:
            _router_request_stops.add(stop)
        try:
            start_time = time.time()

            # ── Turn 0: Query analysis ────────────────────────────
            yield _sse_event("turn_start", {"turn": 0, "phase": "query_analysis"})

            analysis = {}
            if query_analyzer:
                try:

                    analysis = await asyncio.wait_for(
                        _run_owned("search_analysis", partial(query_analyzer.analyze_query, request.query), min(10, max(0, deadline-time.monotonic())), stop),
                        timeout=max(0, deadline-time.monotonic()),
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


            react_agent = ReActSearchAgent(
                search_agent=search_agent,
                openai_client=get_openai_client(),
                max_turns=max_turns,
            )

            result = await react_agent.search(query=request.query, analysis=analysis, max_results=request.max_results or 20, deadline=deadline, stop_event=stop)

            papers = await _dedup_and_rank_deep_search(request.query, result.get("papers", []), analysis.get("intent", "paper_search"), deadline=deadline, stop_event=stop)
            result["papers"] = papers
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

            evaluation = await _evaluate_deep_results(
                request.query, analysis.get("intent", "paper_search"),
                papers, result, deadline, stop,
            )
            result["evaluation"] = evaluation

            yield _sse_event("evaluation", {
                "overall_score": evaluation.get("overall_score"),
                "mode": result["metadata"]["evaluation_mode"],
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
                        src = paper.get("_source", paper.get("source", "arxiv"))
                        results_by_source.setdefault(src, []).append(paper)
                    _stamp_searched_by(results_by_source, username)
                    result.setdefault("metadata", {}).update(save_status=_admit_save(request.query, results_by_source))
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

        except SearchCapacityExceeded as e:
            yield _sse_event("error", {
                "message": str(e), "status_code": 503,
                "code": "search_capacity_exceeded", "retry_after": 1,
            })
        except Exception as e:
            logger.error("[API] Deep Search Stream failed: %s", e, exc_info=True)
            yield _sse_event("error", {"message": str(e)})
        finally:
            stop.set()
            with _router_admission_lock:
                _router_request_stops.discard(stop)

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
