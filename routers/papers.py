"""
Paper management endpoints:
  POST /api/save
  GET  /api/papers
  GET  /api/papers/count
  DELETE /api/papers
  POST /api/collect-references
  POST /api/paper-references
  POST /api/paper-code-repos
  POST /api/extract-texts
  POST /api/enrich-papers
  POST /api/graph-data
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import traceback
from typing import Any, Dict, List

import networkx as nx
import numpy as np
from fastapi import APIRouter, Depends, HTTPException

from .deps import get_optional_user, get_admin_user, search_agent

from src.graph.constants import (
    COSINE_EDGE_THRESHOLD_RELAXED,
    FAISS_SWITCH_THRESHOLD,
    FAISS_TOP_K,
    JACCARD_EDGE_THRESHOLD,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["papers"])

# ── PaperDB singleton (P2-2: SQLite migration) ───────────────────────
from src.storage.paper_db import PaperDB

_paper_db = PaperDB()

# Auto-migrate from papers.json on first import
_JSON_PATH = "data/papers.json"
if os.path.exists(_JSON_PATH):
    _migrated = _paper_db.migrate_from_json(_JSON_PATH)
    if _migrated > 0:
        logger.info("[P2-2] Auto-migrated %d papers from JSON to SQLite", _migrated)


# ── FAISS ANN helper (P2-1) ──────────────────────────────────────────

_FAISS_THRESHOLD = FAISS_SWITCH_THRESHOLD
_FAISS_K = FAISS_TOP_K
_FAISS_MIN_SIM = COSINE_EDGE_THRESHOLD_RELAXED


def _build_edges_faiss(
    papers_data: List[Dict[str, Any]],
    graph: nx.Graph,
) -> None:
    """Build graph edges using FAISS approximate nearest neighbours.

    Uses SimilarityCalculator.get_embeddings_batch() to embed all titles
    in one batch, then builds a FAISS index via faiss_index_manager for
    fast inner-product (cosine similarity on L2-normalised vectors) search.
    """
    import faiss
    from src.graph.faiss_index_manager import build_similarity_index, search_neighbors

    titles = [p.get("title", "") for p in papers_data]
    doc_ids = [
        p.get("doc_id") or str(abs(hash(p.get("title", ""))))
        for p in papers_data
    ]

    # Batch-embed all titles via the search_agent's calculator
    sim_calc = search_agent.similarity_calculator
    embeddings = sim_calc.get_embeddings_batch(titles)

    # Filter out papers with failed embeddings
    valid_indices: List[int] = []
    valid_vectors: List[np.ndarray] = []
    for i, emb in enumerate(embeddings):
        if emb is not None:
            valid_indices.append(i)
            valid_vectors.append(emb.astype(np.float32))

    if len(valid_vectors) < 2:
        logger.warning("[P2-1] Too few valid embeddings (%d), skipping FAISS edges", len(valid_vectors))
        return

    # Stack into matrix and L2-normalise for cosine similarity via inner product
    matrix = np.vstack(valid_vectors)
    faiss.normalize_L2(matrix)

    index = build_similarity_index(matrix)
    scores, indices = search_neighbors(
        index, matrix, top_k=_FAISS_K, min_similarity=_FAISS_MIN_SIM
    )

    # Build edges from search results
    seen_edges: set = set()
    for local_i in range(len(valid_vectors)):
        src_idx = valid_indices[local_i]
        src_id = doc_ids[src_idx]
        for j_pos in range(scores.shape[1]):
            local_j = int(indices[local_i][j_pos])
            if local_j < 0:
                continue
            sim = float(scores[local_i][j_pos])
            if sim <= 0.0:
                continue
            dst_idx = valid_indices[local_j]
            dst_id = doc_ids[dst_idx]
            edge_key = tuple(sorted((src_id, dst_id)))
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                graph.add_edge(src_id, dst_id, weight=round(sim, 3))

    logger.info(
        "[P2-1] FAISS ANN: %d papers, %d valid embeddings, %d edges created",
        len(papers_data), len(valid_vectors), len(seen_edges),
    )


def _build_edges_jaccard(
    papers_data: List[Dict[str, Any]],
    graph: nx.Graph,
) -> None:
    """Original O(n^2) Jaccard + keyword edge builder (fallback for <100 papers)."""

    def _title_tokens(text: str) -> List[str]:
        words = re.findall(r"\b\w+\b", text.lower())
        return [w for w in words if len(w) > 3]

    token_cache = {
        p.get("doc_id", str(abs(hash(p.get("title", ""))))): set(_title_tokens(p.get("title", "")))
        for p in papers_data
    }

    keyword_cache: dict = {}
    for p in papers_data:
        did = p.get("doc_id") or str(abs(hash(p.get("title", ""))))
        kw_tokens: set = set()
        cats = p.get("categories") or ""
        cat_list = cats.split() if isinstance(cats, str) else (cats if isinstance(cats, list) else [])
        for cat in cat_list:
            kw_tokens.add(cat.lower().strip())
        for kw in (p.get("keywords") or []):
            if isinstance(kw, str) and len(kw) > 2:
                kw_tokens.add(kw.lower().strip())
        keyword_cache[did] = kw_tokens

    paper_list = list(papers_data)
    for idx, paper in enumerate(paper_list):
        for jdx in range(idx + 1, len(paper_list)):
            other = paper_list[jdx]
            doc_id1 = paper.get("doc_id") or str(abs(hash(paper.get("title", ""))))
            doc_id2 = other.get("doc_id") or str(abs(hash(other.get("title", ""))))

            base_tokens = token_cache.get(doc_id1, set())
            other_tokens = token_cache.get(doc_id2, set())
            title_score = 0.0
            if base_tokens and other_tokens:
                union = len(base_tokens | other_tokens)
                title_score = len(base_tokens & other_tokens) / union if union else 0

            kw1 = keyword_cache.get(doc_id1, set())
            kw2 = keyword_cache.get(doc_id2, set())
            kw_score = 0.0
            if kw1 and kw2:
                kw_union = len(kw1 | kw2)
                kw_score = len(kw1 & kw2) / kw_union if kw_union else 0

            score = 0.7 * title_score + 0.3 * kw_score

            if score >= JACCARD_EDGE_THRESHOLD:
                graph.add_edge(doc_id1, doc_id2, weight=round(score, 3))


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/save")
async def save_papers(
    results: Dict[str, List[Dict[str, Any]]],
    query: str = "",
    generate_embeddings: bool = False,
    update_graph: bool = True,
    username: str = Depends(get_optional_user),
):
    """
    Save search results to database with automatic embedding generation and graph update.
    """
    try:
        logger.info("Saving %s papers...", sum(len(papers) for papers in results.values()))
        logger.info("Generate embeddings: %s, Update graph: %s", generate_embeddings, update_graph)

        # Stamp username on papers
        if username:
            for paper_list in results.values():
                for paper in paper_list:
                    paper["searched_by"] = username

        save_info = search_agent.save_papers(
            results, query, generate_embeddings=generate_embeddings, update_graph=update_graph
        )

        logger.info(
            "Save completed: %s new papers, %s embeddings generated, graph updated: %s",
            save_info.get('new_papers', 0),
            save_info.get('embeddings_generated', 0),
            save_info.get('graph_updated', False),
        )

        return save_info
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("Error in save: %s", error_trace)
        raise HTTPException(status_code=500, detail=f"Save failed: {str(e)}")


@router.get("/papers/count")
async def get_papers_count():
    """Get count of saved papers."""
    return {"count": search_agent.get_saved_papers_count()}


@router.get("/papers")
async def get_saved_papers():
    """Get all saved papers (SQLite-backed with JSON fallback)."""
    try:
        # P2-2: Try SQLite first
        try:
            papers = _paper_db.get_all_papers()
            if papers:
                return {"papers": papers}
        except Exception as db_err:
            logger.warning("[P2-2] SQLite read failed, falling back to JSON: %s", db_err)

        # Fallback to JSON file
        papers_file = search_agent.papers_file
        if not os.path.exists(papers_file):
            return {"papers": []}

        with open(papers_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {"papers": data.get("papers", [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/papers")
async def clear_papers(username: str = Depends(get_admin_user)):
    """Clear all saved papers (admin only)."""
    success = search_agent.clear_saved_papers()
    # Also clear SQLite
    try:
        _paper_db.clear()
    except Exception as e:
        logger.warning("[P2-2] SQLite clear failed: %s", e)
    return {"success": success}


@router.get("/papers/{paper_id}")
async def get_paper_by_id(paper_id: str):
    """Retrieve a single paper by its doc_id (arxiv_id, DOI, or internal id).

    Used by the MCP server to resolve paper metadata without listing all papers.
    Returns 404 if the paper is not present in the local SQLite index.
    """
    try:
        paper = _paper_db.get_paper(paper_id)
    except Exception as e:
        logger.error("[papers] get_paper_by_id failed for %s: %s", paper_id, e)
        raise HTTPException(status_code=500, detail="paper lookup failed")
    if paper is None:
        raise HTTPException(status_code=404, detail=f"paper not found: {paper_id}")
    return paper


@router.post("/collect-references")
async def collect_references(max_references_per_paper: int = 10, max_papers: int = None):
    """Collect references for saved papers."""
    try:
        logger.info(
            "Collecting references: max_references_per_paper=%s, max_papers=%s",
            max_references_per_paper, max_papers,
        )
        result = search_agent.collect_references(max_references_per_paper, max_papers)
        logger.info(
            "References collected: %s references for %s papers",
            result.get('references_found', 0), result.get('papers_processed', 0),
        )
        return result
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("Error in collect references: %s", error_trace)
        raise HTTPException(status_code=500, detail=f"Reference collection failed: {str(e)}")


@router.post("/paper-references")
async def get_paper_references(request: Dict[str, Any]):
    """Get references for a single paper (on-demand)."""
    try:
        paper = {
            "title": request.get("title", ""),
            "doi": request.get("doi"),
            "arxiv_id": request.get("arxiv_id"),
        }
        max_refs = min(request.get("max_references", 10), 20)
        logger.info("Fetching references for: %s (max=%s)", paper["title"][:60], max_refs)
        refs = search_agent.reference_collector.get_references(paper, max_refs)
        logger.info("Found %s references for: %s", len(refs), paper["title"][:60])
        return {"references": refs}
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("Error fetching paper references: %s", error_trace)
        raise HTTPException(status_code=500, detail=f"Reference fetch failed: {str(e)}")


@router.post("/paper-code-repos")
async def get_paper_code_repos(request: Dict[str, Any]):
    """Search GitHub repositories for a paper's code implementation."""
    try:
        title = request.get("title", "")
        if not title:
            return {"repos": []}
        arxiv_id = request.get("arxiv_id") or None
        doi = request.get("doi") or None
        authors = request.get("authors") or None
        logger.info("Searching code repos for: %s (arxiv=%s, doi=%s)", title[:60], arxiv_id, doi)
        repos = search_agent.github_client.search_repos(
            title=title, arxiv_id=arxiv_id, doi=doi, authors=authors,
        )
        logger.info("Found %s code repos for: %s", len(repos), title[:60])
        return {"repos": repos}
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("Error fetching code repos: %s", error_trace)
        raise HTTPException(status_code=500, detail=f"Code repo search failed: {str(e)}")


@router.post("/batch-references")
async def get_batch_references(request: Dict[str, Any]):
    """Fetch references for multiple papers at once (max 5 papers)."""
    import time as _time
    try:
        papers_list = request.get("papers", [])[:5]
        max_refs = min(request.get("max_references", 5), 10)
        logger.info("Batch references: %s papers, max_refs=%s", len(papers_list), max_refs)

        all_refs: List[Dict[str, Any]] = []
        seen_titles: set = set()

        for i, p in enumerate(papers_list):
            paper = {
                "title": p.get("title", ""),
                "doi": p.get("doi"),
                "arxiv_id": p.get("arxiv_id"),
            }
            if not paper["title"]:
                continue
            refs = search_agent.reference_collector.get_references(paper, max_refs)
            for ref in refs:
                norm_title = ref.get("title", "").strip().lower()
                if norm_title and norm_title not in seen_titles:
                    seen_titles.add(norm_title)
                    all_refs.append(ref)
            if i < len(papers_list) - 1:
                _time.sleep(0.3)

        logger.info("Batch references done: %s unique refs from %s papers", len(all_refs), len(papers_list))
        return {"references": all_refs}
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("Error in batch references: %s", error_trace)
        raise HTTPException(status_code=500, detail=f"Batch reference fetch failed: {str(e)}")


@router.post("/extract-texts")
async def extract_texts(max_papers: int = None):
    """Extract full texts from saved papers."""
    try:
        logger.info("Extracting full texts: max_papers=%s", max_papers)
        result = search_agent.extract_full_texts(max_papers)
        logger.info(
            "Texts extracted: %s/%s papers",
            result.get('texts_extracted', 0), result.get('papers_processed', 0),
        )
        return result
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("Error in extract texts: %s", error_trace)
        raise HTTPException(status_code=500, detail=f"Text extraction failed: {str(e)}")


@router.post("/enrich-papers")
async def enrich_papers(
    collect_references: bool = True,
    extract_texts: bool = True,
    max_references_per_paper: int = 10,
    max_papers: int = None,
):
    """Enrich saved papers (references + full-text + graph update)."""
    try:
        results = {"references": None, "texts": None, "success": True}

        if collect_references:
            logger.info("Step 1: Collecting references...")
            ref_result = search_agent.collect_references(max_references_per_paper, max_papers)
            results["references"] = ref_result
            logger.info("References collected: %s", ref_result.get('references_found', 0))

        if extract_texts:
            logger.info("Step 2: Extracting full texts...")
            text_result = search_agent.extract_full_texts(max_papers)
            results["texts"] = text_result
            logger.info("Texts extracted: %s", text_result.get('texts_extracted', 0))

        logger.info("Paper enrichment completed")
        return results

    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("Error in enrich papers: %s", error_trace)
        raise HTTPException(status_code=500, detail=f"Paper enrichment failed: {str(e)}")


def _build_graph_sync(papers_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Synchronous graph building — runs in a thread to avoid blocking the event loop."""
    from src.utils.paper_utils import generate_doc_id

    for paper in papers_data:
        if "doc_id" not in paper:
            title = paper.get("title", "")
            doc_id = (
                str(int(hashlib.md5(title.encode("utf-8")).hexdigest()[:15], 16))
                if title
                else ""
            )
            paper["doc_id"] = doc_id

    graph = nx.Graph()

    # Ensure all papers have doc_id
    for paper in papers_data:
        if "doc_id" not in paper:
            paper["doc_id"] = generate_doc_id(paper.get("title", ""))

    for paper in papers_data:
        doc_id = paper.get("doc_id")
        if not doc_id:
            title = paper.get("title", "")
            doc_id = (
                str(int(hashlib.md5(title.encode("utf-8")).hexdigest()[:15], 16))
                if title
                else ""
            )
            paper["doc_id"] = doc_id

        node_attrs = {
            "weight": max(paper.get("citations", 1), 1),
            "year": paper.get("year"),
            "title": paper.get("title", ""),
        }
        for key, value in paper.items():
            if key not in node_attrs and key != "doc_id":
                node_attrs[key] = value
        graph.add_node(doc_id, **node_attrs)

    # ── Edge building strategy ──────────────────────────────────
    n_papers = len(papers_data)
    _MAX_JACCARD_PAPERS = 500  # Jaccard O(n^2) 상한

    if n_papers >= _FAISS_THRESHOLD:
        try:
            logger.info("[Graph] Using FAISS ANN for %d papers", n_papers)
            _build_edges_faiss(papers_data, graph)
        except Exception as faiss_err:
            logger.warning("[Graph] FAISS failed: %s", faiss_err)
            if n_papers <= _MAX_JACCARD_PAPERS:
                logger.info("[Graph] Jaccard fallback for %d papers", n_papers)
                _build_edges_jaccard(papers_data, graph)
            else:
                logger.warning("[Graph] %d papers too large for Jaccard fallback, skipping edges", n_papers)
    else:
        _build_edges_jaccard(papers_data, graph)

    # Layout
    try:
        layout = nx.spring_layout(graph, seed=42, k=0.75, iterations=50)
    except ImportError:
        logger.warning("scipy not available, using random layout fallback")
        import random as _rand
        _rand.seed(42)
        layout = {node: (_rand.uniform(-1, 1), _rand.uniform(-1, 1)) for node in graph.nodes()}

    if len(layout) > 0:
        centroid_x = sum(pos[0] for pos in layout.values()) / len(layout)
        centroid_y = sum(pos[1] for pos in layout.values()) / len(layout)
        centered = {nid: (x - centroid_x, y - centroid_y) for nid, (x, y) in layout.items()}

        max_abs = max(
            max(abs(x) for x, _ in centered.values()),
            max(abs(y) for _, y in centered.values()),
        ) or 1.0
        layout = {nid: (x / max_abs, y / max_abs) for nid, (x, y) in centered.items()}

    # Extract nodes and edges for frontend
    nodes = []
    if len(graph.nodes()) > 0:
        for node_id in graph.nodes():
            node_data = graph.nodes[node_id]
            x, y = layout.get(node_id, (0, 0))
            nodes.append(
                {
                    "id": str(node_id),
                    "x": float(x),
                    "y": float(y),
                    "title": node_data.get("title", ""),
                    "year": node_data.get("year"),
                    "citations": node_data.get("citations", 0),
                    "authors": node_data.get("authors", []),
                    "abstract": node_data.get("abstract", ""),
                    "url": node_data.get("url", ""),
                    "pdf_url": node_data.get("pdf_url", ""),
                    "doi": node_data.get("doi", ""),
                    "source": node_data.get("source", ""),
                    "journal": node_data.get("journal", ""),
                    "doc_id": str(node_id),
                    "weight": node_data.get("weight", 1),
                }
            )

        edges = []
        for start, end in graph.edges():
            edges.append(
                {
                    "source": str(start),
                    "target": str(end),
                    "weight": graph.edges[start, end].get("weight", 0.1),
                }
            )
    else:
        edges = []

    return {"nodes": nodes, "edges": edges}


@router.post("/graph-data")
async def get_graph_data(request: Dict[str, Any]):
    """Generate graph data for visualisation.

    P2-1: Uses FAISS ANN for >= 100 papers, Jaccard fallback for < 100.
    P2-2: Reads from SQLite when no papers_json is provided.
    CPU-bound graph operations run in a thread to avoid blocking the event loop.
    """
    try:
        papers_json = request.get("papers_json")
        if not papers_json:
            # papers_json이 없으면 빈 그래프 반환 (전체 DB 로드 방지)
            return {"nodes": [], "edges": []}

        papers_data = json.loads(papers_json)
        if not papers_data:
            return {"nodes": [], "edges": []}

        # Offload CPU-bound graph building to a thread
        result = await asyncio.to_thread(_build_graph_sync, papers_data)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
