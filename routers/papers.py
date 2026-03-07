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

import hashlib
import json
import logging
import os
import re
import traceback
from typing import Any, Dict, List

import networkx as nx
from fastapi import APIRouter, Depends, HTTPException
from starlette.requests import Request

from .deps import get_optional_user, get_admin_user, search_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["papers"])


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
    """Get all saved papers."""
    try:
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
    return {"success": success}


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
        logger.info("Searching code repos for: %s", title[:60])
        repos = search_agent.github_client.search_repos_by_title(title)
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


@router.post("/graph-data")
async def get_graph_data(request: Dict[str, Any]):
    """Generate graph data for visualisation. Accepts papers JSON string or uses saved papers."""
    try:
        papers_json = request.get("papers_json")
        if papers_json:
            papers_data = json.loads(papers_json)
            for paper in papers_data:
                if "doc_id" not in paper:
                    title = paper.get("title", "")
                    doc_id = (
                        str(int(hashlib.md5(title.encode("utf-8")).hexdigest()[:15], 16))
                        if title
                        else ""
                    )
                    paper["doc_id"] = doc_id
        else:
            papers_file = search_agent.papers_file
            if not os.path.exists(papers_file):
                return {"nodes": [], "edges": []}
            with open(papers_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                papers_data = data.get("papers", [])

        # ── Build similarity graph ─────────────────────────────────────
        def _title_tokens(text: str) -> List[str]:
            words = re.findall(r"\b\w+\b", text.lower())
            return [w for w in words if len(w) > 3]

        def generate_doc_id(title: str) -> str:
            """Generate doc_id matching frontend hashString function (djb2)."""
            hash_value = 0
            for char in title:
                char_code = ord(char)
                hash_value = ((hash_value << 5) - hash_value) + char_code
                hash_value = hash_value & 0x7FFFFFFF
            return str(hash_value)

        graph = nx.Graph()

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

        # Edges based on title similarity
        token_cache = {
            p.get("doc_id", str(abs(hash(p.get("title", ""))))): set(_title_tokens(p.get("title", "")))
            for p in papers_data
        }

        paper_list = list(papers_data)
        for idx, paper in enumerate(paper_list):
            for jdx in range(idx + 1, len(paper_list)):
                other = paper_list[jdx]
                doc_id1 = paper.get("doc_id") or str(abs(hash(paper.get("title", ""))))
                doc_id2 = other.get("doc_id") or str(abs(hash(other.get("title", ""))))

                base_tokens = token_cache.get(doc_id1, set())
                other_tokens = token_cache.get(doc_id2, set())
                if not base_tokens or not other_tokens:
                    continue

                overlap = len(base_tokens & other_tokens)
                union = len(base_tokens | other_tokens)
                score = overlap / union if union else 0

                if score >= 0.12:
                    graph.add_edge(doc_id1, doc_id2, weight=round(score, 3))

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
            centered_layout = {}
            for node_id, (x, y) in layout.items():
                centered_layout[node_id] = (x - centroid_x, y - centroid_y)
            layout = centered_layout

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
