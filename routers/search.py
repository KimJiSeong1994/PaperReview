"""
Search-related endpoints:
  POST /api/search
  POST /api/smart-search
  POST /api/analyze-query
  POST /api/llm-search
"""

import json
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .deps import (
    query_analyzer,
    relevance_filter,
    search_agent,
)

router = APIRouter(prefix="/api", tags=["search"])


# ── Pydantic models ───────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    max_results: int = 20
    sources: List[str] = ["arxiv", "connected_papers", "google_scholar"]
    sort_by: str = "relevance"
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    author: Optional[str] = None
    category: Optional[str] = None
    fast_mode: bool = True
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

def _enrich_papers_background(
    query: str,
    results: Dict[str, List[Dict[str, Any]]],
    collect_refs: bool,
    extract_text: bool,
    max_refs: int,
):
    """Background paper enrichment (save, refs, full-text)."""
    try:
        print("[Background] Enrichment started...")

        save_result = search_agent.save_papers(
            results, query, generate_embeddings=False, update_graph=True
        )
        print(f"[Background] Saved: {save_result.get('new_papers', 0)} new papers")

        new_papers_count = save_result.get("new_papers", 0)
        if collect_refs and new_papers_count > 0:
            max_papers_to_collect = min(new_papers_count, 10)
            print(f"[Background] Collecting refs (max {max_papers_to_collect} papers)...")
            ref_result = search_agent.collect_references(max_refs, max_papers_to_collect)
            print(f"[Background] Refs collected: {ref_result.get('references_found', 0)}")

        if extract_text and save_result.get("new_papers", 0) > 0:
            print("[Background] Extracting full texts...")
            text_result = search_agent.extract_full_texts(save_result.get("new_papers"))
            print(f"[Background] Texts extracted: {text_result.get('texts_extracted', 0)}")

        print("[Background] Enrichment done")
    except Exception as e:
        print(f"[Background] Enrichment error: {e}")
        traceback.print_exc()


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/analyze-query", response_model=QueryAnalysisResponse)
async def analyze_query(request: QueryAnalysisRequest):
    """Analyze user query to understand intent and extract keywords."""
    if not query_analyzer:
        raise HTTPException(
            status_code=503,
            detail="Query analysis service unavailable (OpenAI API key not configured)",
        )

    try:
        print(f"[API] Analyzing query: {request.query}")
        analysis = query_analyzer.analyze_query(request.query)
        print(f"[API] Analysis result: intent={analysis.get('intent')}, confidence={analysis.get('confidence')}")
        return QueryAnalysisResponse(**analysis)
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"[API] Error in query analysis: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Query analysis failed: {str(e)}")


@router.post("/llm-search", response_model=LLMSearchResponse)
async def llm_context_search(request: LLMSearchRequest):
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
        print(f"[API] LLM Context Search: {request.query}")

        results = search_agent.llm_context_search(
            query=request.query,
            max_results_per_source=request.max_results,
            context=request.context,
        )

        metadata = results.pop("_metadata", {})
        total = sum(len(papers) for papers in results.values())
        search_time = time.time() - start_time

        print(f"[API] LLM Search completed: {total} papers in {search_time:.2f}s")

        if request.save_papers and total > 0:
            try:
                save_result = search_agent.save_papers(
                    results, request.query, generate_embeddings=False, update_graph=True
                )
                metadata["save_result"] = {
                    "new_papers": save_result.get("new_papers", 0),
                    "duplicates": save_result.get("duplicates", 0),
                }
                print(f"[API] Saved: {save_result.get('new_papers', 0)} new papers")
            except Exception as e:
                print(f"[API] Error saving papers: {e}")

        metadata["search_time"] = round(search_time, 2)

        return LLMSearchResponse(results=results, total=total, metadata=metadata)

    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"[API] LLM Search error: {error_trace}")
        raise HTTPException(status_code=500, detail=f"LLM search failed: {str(e)}")


@router.post("/smart-search")
async def smart_search(request: LLMSearchRequest):
    """
    Smart search -- LLM analysis + multi-source strategy.
    1. LLM analyses query & decides strategy
    2. Optimised query across multiple sources
    3. Merge & deduplicate
    4. Sort by relevance
    """
    try:
        start_time = time.time()
        print(f"[API] Smart Search: {request.query}")

        result = search_agent.smart_search(query=request.query, max_results=request.max_results)

        search_time = time.time() - start_time
        result["metadata"]["search_time"] = round(search_time, 2)

        print(f"[API] Smart Search completed: {len(result['papers'])} papers in {search_time:.2f}s")

        if request.save_papers and result["papers"]:
            try:
                results_by_source = {"arxiv": [], "connected_papers": [], "google_scholar": []}
                for paper in result["papers"]:
                    source = paper.pop("_source", "arxiv")
                    if source in results_by_source:
                        results_by_source[source].append(paper)

                save_result = search_agent.save_papers(
                    results_by_source, request.query, generate_embeddings=False, update_graph=True
                )
                result["metadata"]["save_result"] = {
                    "new_papers": save_result.get("new_papers", 0),
                    "duplicates": save_result.get("duplicates", 0),
                }
            except Exception as e:
                print(f"[API] Error saving papers: {e}")

        return result

    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"[API] Smart Search error: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Smart search failed: {str(e)}")


@router.post("/search", response_model=SearchResponse)
async def search_papers(request: SearchRequest):
    """Search papers across multiple sources with automatic query analysis."""
    try:
        start_time = time.time()

        # Query analysis
        query_analysis = None
        if query_analyzer:
            try:
                analysis_start = time.time()
                print(f"[API] Analyzing query: {request.query}")
                query_analysis = query_analyzer.analyze_query(request.query)
                print(
                    f"[API] Query analysis: intent={query_analysis.get('intent')}, "
                    f"keywords={query_analysis.get('keywords')}, "
                    f"confidence={query_analysis.get('confidence')} "
                    f"(took {time.time()-analysis_start:.2f}s)"
                )
            except Exception as e:
                print(f"[API] Query analysis failed (continuing with original query): {e}")
        else:
            print("[API] Query analysis skipped (OpenAI API key not configured)")

        # Auto-apply filters from analysis
        filters = {
            "sources": request.sources,
            "max_results": request.max_results,
            "sort_by": request.sort_by,
            "year_start": request.year_start
            or (query_analysis.get("search_filters", {}).get("year_start") if query_analysis else None),
            "year_end": request.year_end
            or (query_analysis.get("search_filters", {}).get("year_end") if query_analysis else None),
            "author": request.author
            or (query_analysis.get("search_filters", {}).get("author") if query_analysis else None),
            "category": request.category
            or (query_analysis.get("search_filters", {}).get("category") if query_analysis else None),
        }

        # Use improved query if high-confidence analysis available
        search_query = request.query
        if query_analysis and query_analysis.get("confidence", 0) > 0.7:
            improved_query = query_analysis.get("improved_query")
            if improved_query and improved_query != request.query:
                print(f"[API] Using improved query: {improved_query}")
                search_query = improved_query

        search_start = time.time()
        print(f"[API] Searching for: {search_query}")
        print(f"[API] Filters: {filters}")

        # LLM context search or standard search
        if request.use_llm_search and query_analyzer:
            print("[API] Using LLM Context Search...")
            results = search_agent.llm_context_search(
                search_query,
                max_results_per_source=request.max_results,
                context=request.search_context,
            )
            llm_metadata = results.pop("_metadata", None)
            if llm_metadata:
                print(
                    f"[API] LLM generated queries: "
                    f"arXiv={len(llm_metadata.get('arxiv_queries', []))}, "
                    f"Scholar={len(llm_metadata.get('scholar_queries', []))}"
                )
        else:
            results = search_agent.search_with_filters(search_query, filters)

        search_time = time.time() - search_start
        print(
            f"[API] Raw search results: "
            f"{sum(len(papers) for papers in results.values())} papers found "
            f"(took {search_time:.2f}s)"
        )

        # Relevance filtering (only when not fast_mode)
        if not request.fast_mode and relevance_filter and results:
            try:
                print("[API] Applying relevance filtering (parallel mode)...")
                all_papers = []
                for source, papers in results.items():
                    for paper in papers:
                        paper["source"] = source
                        all_papers.append(paper)

                if all_papers:
                    filtered_papers = relevance_filter.filter_papers(
                        request.query, all_papers, threshold=0.5, max_papers=request.max_results, parallel=True
                    )
                    results = {}
                    for source in request.sources:
                        results[source] = [p for p in filtered_papers if p.get("source") == source]
                    print(f"[API] Filtered results: {len(filtered_papers)} papers (threshold: 0.5)")
                else:
                    print("[API] No papers to filter")
            except Exception as e:
                print(f"[API] Relevance filtering failed (using unfiltered results): {e}")
                traceback.print_exc()
        else:
            if request.fast_mode:
                print("[API] Relevance filtering skipped (fast mode enabled)")
            elif not relevance_filter:
                print("[API] Relevance filtering skipped (OpenAI API key not configured)")

        # Ensure all sources present
        for source in request.sources:
            if source not in results:
                results[source] = []

        total = sum(len(papers) for papers in results.values())

        # Save & enrich
        if request.save_papers and total > 0:
            if request.fast_mode:
                print(f"[API] Fast mode: Starting background enrichment for {total} papers...")
                t = threading.Thread(
                    target=_enrich_papers_background,
                    args=(
                        request.query,
                        results,
                        request.collect_references,
                        request.extract_texts,
                        request.max_references_per_paper,
                    ),
                )
                t.daemon = True
                t.start()
                print("[API] Background enrichment started (thread)")
            else:
                try:
                    print(f"[API] Saving {total} papers...")
                    save_result = search_agent.save_papers(
                        results, request.query, generate_embeddings=False, update_graph=True
                    )
                    print(
                        f"[API] Saved: {save_result.get('new_papers', 0)} new, "
                        f"{save_result.get('duplicates', 0)} duplicates"
                    )
                    new_papers_count = save_result.get("new_papers", 0)
                    if request.collect_references and new_papers_count > 0:
                        max_papers_to_collect = min(new_papers_count, 10)
                        print(f"[API] Collecting references for {max_papers_to_collect} papers...")
                        ref_result = search_agent.collect_references(
                            request.max_references_per_paper, max_papers=max_papers_to_collect
                        )
                        print(f"[API] References collected: {ref_result.get('references_found', 0)}")
                    if request.extract_texts:
                        print("[API] Extracting full texts for saved papers...")
                        text_result = search_agent.extract_full_texts(
                            max_papers=save_result.get("new_papers", 0)
                            if save_result.get("new_papers", 0) > 0
                            else None
                        )
                        print(f"[API] Texts extracted: {text_result.get('texts_extracted', 0)}")
                except Exception as e:
                    print(f"[API] Error in saving/enriching papers: {e}")
                    traceback.print_exc()

        total_time = time.time() - start_time
        print(f"[API] Search completed in {total_time:.2f}s")

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

            for paper in results:
                if "doc_id" not in paper or not paper.get("doc_id"):
                    title = paper.get("title", "")
                    paper["doc_id"] = _generate_doc_id(title)

            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"[API] Search results cached: {len(results)} papers (with doc_ids)")
        except Exception as cache_error:
            print(f"[API] Cache save warning: {cache_error}")

        return SearchResponse(results=results, total=total, query_analysis=query_analysis)
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"[API] Error in search: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
