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
import json
import logging
import math
import os
import re
import traceback
from collections import Counter
from typing import Any, Dict, List, Optional

import networkx as nx
import numpy as np
from fastapi import APIRouter, Body, Depends, HTTPException
from starlette.requests import Request

from .deps import (
    get_current_user,
    get_optional_user,
    get_admin_user,
    limiter,
    search_agent,
)

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
from src.utils.paper_utils import generate_doc_id  # P2-3: doc_id for /save SQLite sync

_paper_data_dir = os.getenv("DATA_DIR", "data")
_paper_db = PaperDB(db_path=os.path.join(_paper_data_dir, "papers.db"))

# Auto-migrate from papers.json on first import
_JSON_PATH = os.path.join(_paper_data_dir, "papers.json")
if os.path.exists(_JSON_PATH):
    _migrated = _paper_db.migrate_from_json(_JSON_PATH)
    if _migrated > 0:
        logger.info("[P2-2] Auto-migrated %d papers from JSON to SQLite", _migrated)


# ── FAISS ANN helper (P2-1) ──────────────────────────────────────────

_FAISS_THRESHOLD = FAISS_SWITCH_THRESHOLD
_FAISS_K = FAISS_TOP_K
_FAISS_MIN_SIM = COSINE_EDGE_THRESHOLD_RELAXED
# Edges kept per node before layout; matches the five "next to read" neighbours.
_SPARSE_TOP_K = 5


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
        p.get("doc_id") or str(abs(hash(p.get("title", "")))) for p in papers_data
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
        logger.warning(
            "[P2-1] Too few valid embeddings (%d), skipping FAISS edges",
            len(valid_vectors),
        )
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
        len(papers_data),
        len(valid_vectors),
        len(seen_edges),
    )


def _build_edges_jaccard(
    papers_data: List[Dict[str, Any]],
    graph: nx.Graph,
) -> None:
    """Original O(n^2) Jaccard + keyword edge builder (fallback for <100 papers).

    Each channel uses IDF-weighted Jaccard, ``w(t) = ln((N + 1) / df(t))``, so a
    token every title shares (typically the search query) contributes almost
    nothing while a rare shared token carries the edge.
    """

    def _title_tokens(text: str) -> List[str]:
        words = re.findall(r"\b\w+\b", text.lower())
        return [w for w in words if len(w) > 3]

    token_cache = {
        p.get("doc_id", str(abs(hash(p.get("title", ""))))): set(
            _title_tokens(p.get("title", ""))
        )
        for p in papers_data
    }

    keyword_cache: dict = {}
    for p in papers_data:
        did = p.get("doc_id") or str(abs(hash(p.get("title", ""))))
        kw_tokens: set = set()
        cats = p.get("categories") or ""
        cat_list = (
            cats.split()
            if isinstance(cats, str)
            else (cats if isinstance(cats, list) else [])
        )
        for cat in cat_list:
            kw_tokens.add(cat.lower().strip())
        for kw in p.get("keywords") or []:
            if isinstance(kw, str) and len(kw) > 2:
                kw_tokens.add(kw.lower().strip())
        keyword_cache[did] = kw_tokens

    n_papers = max(len(papers_data), 1)
    title_df: Counter[str] = Counter(
        token for tokens in token_cache.values() for token in tokens
    )
    keyword_df: Counter[str] = Counter(
        token for tokens in keyword_cache.values() for token in tokens
    )

    def _weighted_jaccard(left: set, right: set, df: Counter[str]) -> float:
        if not left or not right:
            return 0.0
        union = sum(math.log((n_papers + 1) / df[token]) for token in left | right)
        if not union:
            return 0.0
        shared = sum(math.log((n_papers + 1) / df[token]) for token in left & right)
        return shared / union

    paper_list = list(papers_data)
    for idx, paper in enumerate(paper_list):
        for jdx in range(idx + 1, len(paper_list)):
            other = paper_list[jdx]
            doc_id1 = paper.get("doc_id") or str(abs(hash(paper.get("title", ""))))
            doc_id2 = other.get("doc_id") or str(abs(hash(other.get("title", ""))))

            title_score = _weighted_jaccard(
                token_cache.get(doc_id1, set()),
                token_cache.get(doc_id2, set()),
                title_df,
            )
            kw_score = _weighted_jaccard(
                keyword_cache.get(doc_id1, set()),
                keyword_cache.get(doc_id2, set()),
                keyword_df,
            )

            score = 0.7 * title_score + 0.3 * kw_score

            if score >= JACCARD_EDGE_THRESHOLD:
                graph.add_edge(doc_id1, doc_id2, weight=round(score, 3))


_GRAPH_LABEL_STOPWORDS = {
    "about",
    "across",
    "after",
    "also",
    "analysis",
    "approach",
    "based",
    "been",
    "being",
    "between",
    "both",
    "could",
    "does",
    "each",
    "every",
    "from",
    "have",
    "into",
    "less",
    "make",
    "makes",
    "making",
    "many",
    "model",
    "models",
    "more",
    "most",
    "much",
    "only",
    "over",
    "paper",
    "research",
    "should",
    "some",
    "study",
    "such",
    "system",
    "systems",
    "than",
    "that",
    "their",
    "then",
    "there",
    "these",
    "this",
    "those",
    "through",
    "toward",
    "towards",
    "under",
    "using",
    "very",
    "what",
    "when",
    "where",
    "which",
    "while",
    "will",
    "with",
    "within",
    "without",
    "would",
    "your",
}


_COMMON_TERM_RATIO = 0.4


def _common_terms(papers_data: List[Dict[str, Any]]) -> frozenset[str]:
    """Title tokens present in at least 40% of titles (min 2 papers).

    These are almost always the search query echoed back by every result, so
    they carry no information about what two papers share.
    """
    document_frequency: Counter[str] = Counter()
    for paper in papers_data:
        tokens: set[str] = set()
        for token in re.findall(r"[A-Za-z0-9가-힣-]+", paper.get("title", "")):
            lowered = token.lower().strip("-")
            # Count hyphenated tokens and their parts so both tokenizers
            # (explanations keep hyphens, Jaccard splits on them) are covered.
            tokens.update(
                part for part in [lowered, *lowered.split("-")] if len(part) > 3
            )
        document_frequency.update(tokens)
    minimum = max(2, math.ceil(len(papers_data) * _COMMON_TERM_RATIO))
    return frozenset(
        term for term, count in document_frequency.items() if count >= minimum
    )


def _paper_graph_terms(
    paper: Dict[str, Any],
    common_terms: frozenset[str] = frozenset(),
) -> tuple[set[str], set[str]]:
    """Return normalized keyword phrases and useful title tokens for graph explanations."""
    keyword_terms: set[str] = set()
    for keyword in paper.get("keywords") or []:
        if isinstance(keyword, str):
            normalized = " ".join(keyword.lower().split()).strip()
            if len(normalized) > 2 and normalized not in common_terms:
                keyword_terms.add(normalized)

    title_terms: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9가-힣-]+", paper.get("title", "")):
        # "(knowledge)-intensive" tokenizes as "-intensive"; drop the stray hyphen.
        lowered = token.lower().strip("-")
        if (
            len(lowered) > 3
            and lowered not in _GRAPH_LABEL_STOPWORDS
            and lowered not in common_terms
        ):
            title_terms.add(lowered)
    return keyword_terms, title_terms


_MIN_COMMUNITY_SIZE = 3
# Palette has six colours (community_id % 6); more hulls than that read as noise.
_MAX_COMMUNITIES = 6


def _merge_tiny_communities(graph: nx.Graph, communities: List[set]) -> None:
    """Fold <3-node communities into their strongest neighbour, then cap at six.

    Mutates ``communities`` in place. Order is deterministic (size, then min
    node id). A tiny community with no edges to any other community cannot be
    merged and is not counted against the cap; the caller leaves it unlabelled.
    The cap is only reachable through merges, so more than six mutually
    disconnected communities of three or more papers are all kept.
    """

    def _reportable(community: set) -> bool:
        return len(community) >= _MIN_COMMUNITY_SIZE or any(
            v not in community for u in community for v in graph.neighbors(u)
        )

    def _ordered() -> List[set]:
        return sorted(communities, key=lambda c: (len(c), min(str(n) for n in c)))

    def _strongest_neighbour(small: set) -> Optional[set]:
        best, best_weight = None, 0.0
        for other in _ordered():
            if other is small:
                continue
            weight = sum(
                graph.edges[u, v].get("weight", 0.1)
                for u in small
                for v in graph.neighbors(u)
                if v in other
            )
            if weight > best_weight:
                best, best_weight = other, weight
        return best

    def _merge_first(candidates: List[set]) -> bool:
        for small in candidates:
            best = _strongest_neighbour(small)
            if best is not None:
                best.update(small)
                communities.remove(small)
                return True
        return False

    while _merge_first([c for c in _ordered() if len(c) < _MIN_COMMUNITY_SIZE]):
        pass
    while sum(
        1 for c in communities if _reportable(c)
    ) > _MAX_COMMUNITIES and _merge_first([c for c in _ordered() if _reportable(c)]):
        pass


def _annotate_graph_explanations(
    graph: nx.Graph,
    papers_data: List[Dict[str, Any]],
    common_terms: frozenset[str] = frozenset(),
) -> List[Dict[str, Any]]:
    """Attach deterministic community labels and inspectable shared edge terms."""
    paper_by_id = {str(paper.get("doc_id", "")): paper for paper in papers_data}
    terms_by_id = {
        paper_id: _paper_graph_terms(paper, common_terms)
        for paper_id, paper in paper_by_id.items()
    }

    for source, target in graph.edges():
        source_keywords, source_title = terms_by_id.get(str(source), (set(), set()))
        target_keywords, target_title = terms_by_id.get(str(target), (set(), set()))
        shared_keywords = sorted(
            source_keywords & target_keywords, key=lambda term: (-len(term), term)
        )
        shared_title = sorted(source_title & target_title)
        shared_terms = list(dict.fromkeys([*shared_keywords, *shared_title]))[:4]
        graph.edges[source, target]["shared_terms"] = shared_terms

    if graph.number_of_nodes() == 0:
        return []

    detected = [
        set(node_set)
        for node_set in nx.community.louvain_communities(
            graph, weight="weight", seed=42
        )
    ]
    _merge_tiny_communities(graph, detected)
    # Tiny communities that survived the merge have no edge to any other
    # community; reporting them would claim topics the canvas cannot show.
    reported = [
        node_set
        for node_set in detected
        if len(node_set) >= _MIN_COMMUNITY_SIZE
        or any(v not in node_set for u in node_set for v in graph.neighbors(u))
    ]
    if not reported and graph.number_of_edges() > 0:
        # Nothing qualifies but papers are connected (e.g. a two-paper graph):
        # keep what Louvain found. An edgeless graph has no topics to report.
        reported = detected
    for node_set in detected:
        if node_set not in reported:
            for node_id in node_set:
                graph.nodes[node_id]["community_id"] = None
                graph.nodes[node_id]["community_label"] = ""
    ordered = sorted(
        reported,
        key=lambda node_set: (
            -len(node_set),
            min(str(node_id) for node_id in node_set),
        ),
    )
    communities: List[Dict[str, Any]] = []

    total_keyword_counts: Counter[str] = Counter()
    total_title_counts: Counter[str] = Counter()
    for keyword_terms, title_terms in terms_by_id.values():
        total_keyword_counts.update(keyword_terms)
        total_title_counts.update(title_terms)

    # Prefer terms that are frequent here and rare elsewhere, so sibling
    # communities do not all get labelled with the same shared vocabulary.
    def _distinctive(
        counts: Counter[str], totals: Counter[str]
    ) -> List[tuple[str, float]]:
        return sorted(
            (
                (term, count / (totals[term] - count + 1))
                for term, count in counts.items()
            ),
            key=lambda item: (-item[1], item[0]),
        )

    for community_id, node_set in enumerate(ordered):
        keyword_counts: Counter[str] = Counter()
        title_counts: Counter[str] = Counter()
        for node_id in node_set:
            keyword_terms, title_terms = terms_by_id.get(str(node_id), (set(), set()))
            keyword_counts.update(keyword_terms)
            title_counts.update(title_terms)

        # One pool ranked by distinctiveness; keyword phrases win ties.
        ranked = sorted(
            [
                *(
                    (term, score, 0)
                    for term, score in _distinctive(
                        keyword_counts, total_keyword_counts
                    )
                ),
                *(
                    (term, score, 1)
                    for term, score in _distinctive(title_counts, total_title_counts)
                ),
            ],
            key=lambda item: (-item[1], item[2], item[0]),
        )
        label_terms: List[str] = []
        for term, _, _ in ranked:
            if term not in label_terms:
                label_terms.append(term)
            if len(label_terms) >= 2:
                break
        label = " · ".join(label_terms) if label_terms else f"주제 {community_id + 1}"

        node_ids = sorted(str(node_id) for node_id in node_set)
        for node_id in node_set:
            graph.nodes[node_id]["community_id"] = community_id
            graph.nodes[node_id]["community_label"] = label

        communities.append(
            {
                "community_id": community_id,
                "label": label,
                "nodes": node_ids,
                "size": len(node_ids),
            }
        )

    return communities


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
        logger.info(
            "Saving %s papers...", sum(len(papers) for papers in results.values())
        )
        logger.info(
            "Generate embeddings: %s, Update graph: %s",
            generate_embeddings,
            update_graph,
        )

        # Stamp username on papers
        if username:
            for paper_list in results.values():
                for paper in paper_list:
                    paper["searched_by"] = username

        save_info = search_agent.save_papers(
            results,
            query,
            generate_embeddings=generate_embeddings,
            update_graph=update_graph,
        )

        # P2-3: also upsert into SQLite (_paper_db) so get_paper / DB-backed search can
        # find /save-ingested papers (search_agent.save_papers only writes papers.json).
        try:
            flat = []
            for paper_list in results.values():
                for p in paper_list:
                    if not p.get("doc_id"):
                        p["doc_id"] = generate_doc_id(p.get("title", ""))
                    flat.append(p)
            if flat:
                synced = _paper_db.save_papers(flat)
                logger.info(
                    "[P2-3] /save synced %d papers to SQLite (%d upserted)",
                    len(flat),
                    synced,
                )
        except Exception as db_err:
            logger.warning("[P2-3] SQLite sync on /save failed: %s", db_err)

        logger.info(
            "Save completed: %s new papers, %s embeddings generated, graph updated: %s",
            save_info.get("new_papers", 0),
            save_info.get("embeddings_generated", 0),
            save_info.get("graph_updated", False),
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
            logger.warning(
                "[P2-2] SQLite read failed, falling back to JSON: %s", db_err
            )

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
async def get_paper_by_id(
    paper_id: str, username: str | None = Depends(get_optional_user)
):
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
@limiter.limit("10/minute")
async def collect_references(
    request: Request,
    max_references_per_paper: int = 10,
    max_papers: int = None,
    username: str = Depends(get_current_user),
):
    """Collect references for saved papers.

    F-33: requires authentication and is IP-rate-limited.  Each call fans
    out to Semantic Scholar / arXiv / OpenAlex over up to ``max_papers``
    saved papers; an unauthenticated visitor could exhaust shared API
    quotas with a single POST.
    """
    try:
        logger.info(
            "Collecting references: max_references_per_paper=%s, max_papers=%s",
            max_references_per_paper,
            max_papers,
        )
        result = search_agent.collect_references(max_references_per_paper, max_papers)
        logger.info(
            "References collected: %s references for %s papers",
            result.get("references_found", 0),
            result.get("papers_processed", 0),
        )
        return result
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("Error in collect references: %s", error_trace)
        raise HTTPException(
            status_code=500, detail=f"Reference collection failed: {str(e)}"
        )


@router.post("/paper-references")
@limiter.limit("20/minute")
async def get_paper_references(
    request: Request,
    body: Dict[str, Any],
    username: str = Depends(get_current_user),
):
    """Get references for a single paper (on-demand).

    F-33: authenticated + rate-limited.  One request triggers an external
    lookup against Semantic Scholar (and fallbacks), so we cap to 20/min
    per IP and require a valid session.
    """
    try:
        paper = {
            "title": body.get("title", ""),
            "doi": body.get("doi"),
            "arxiv_id": body.get("arxiv_id"),
        }
        max_refs = min(body.get("max_references", 10), 20)
        logger.info(
            "Fetching references for: %s (max=%s)", paper["title"][:60], max_refs
        )
        refs = search_agent.reference_collector.get_references(paper, max_refs)
        logger.info("Found %s references for: %s", len(refs), paper["title"][:60])
        return {"references": refs}
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("Error fetching paper references: %s", error_trace)
        raise HTTPException(status_code=500, detail=f"Reference fetch failed: {str(e)}")


@router.post("/paper-code-repos")
@limiter.limit("20/minute")
async def get_paper_code_repos(
    request: Request,
    body: Dict[str, Any],
    username: str = Depends(get_current_user),
):
    """Search GitHub repositories for a paper's code implementation.

    F-33: authenticated + rate-limited.  Hits the GitHub search API,
    which is sharply rate-limited for our PAT.
    """
    try:
        title = body.get("title", "")
        if not title:
            return {"repos": []}
        arxiv_id = body.get("arxiv_id") or None
        doi = body.get("doi") or None
        authors = body.get("authors") or None
        logger.info(
            "Searching code repos for: %s (arxiv=%s, doi=%s)", title[:60], arxiv_id, doi
        )
        repos = search_agent.github_client.search_repos(
            title=title,
            arxiv_id=arxiv_id,
            doi=doi,
            authors=authors,
        )
        logger.info("Found %s code repos for: %s", len(repos), title[:60])
        return {"repos": repos}
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("Error fetching code repos: %s", error_trace)
        raise HTTPException(
            status_code=500, detail=f"Code repo search failed: {str(e)}"
        )


@router.post("/batch-references")
@limiter.limit("10/minute")
async def get_batch_references(
    request: Request,
    body: Dict[str, Any],
    username: str = Depends(get_current_user),
):
    """Fetch references for multiple papers at once (max 5 papers).

    F-33: authenticated + rate-limited.  Each call fans out to up to 5
    external reference lookups in a loop; stricter cap (10/min) than the
    single-paper endpoint.
    """
    import time as _time

    try:
        papers_list = body.get("papers", [])[:5]
        max_refs = min(body.get("max_references", 5), 10)
        logger.info(
            "Batch references: %s papers, max_refs=%s", len(papers_list), max_refs
        )

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

        logger.info(
            "Batch references done: %s unique refs from %s papers",
            len(all_refs),
            len(papers_list),
        )
        return {"references": all_refs}
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("Error in batch references: %s", error_trace)
        raise HTTPException(
            status_code=500, detail=f"Batch reference fetch failed: {str(e)}"
        )


@router.post("/extract-texts")
@limiter.limit("10/minute")
async def extract_texts(
    request: Request,
    max_papers: int = None,
    arxiv_ids: Optional[List[str]] = Body(default=None, embed=True),
    username: str = Depends(get_current_user),
):
    """Extract full texts from saved papers.

    F-33: authenticated + rate-limited.  Downloads PDFs from publisher
    sites in bulk; visitor-initiated traffic could get our IP blocked.

    When ``arxiv_ids`` is supplied (JSON body ``{"arxiv_ids": [...]}``), only
    matching papers are processed (arXiv version suffixes ignored). This lets
    callers target a few freshly-saved papers instead of scanning the whole
    corpus from the start (the default ``max_papers`` slice begins at index 0).
    """
    try:
        logger.info(
            "Extracting full texts: max_papers=%s arxiv_ids=%s",
            max_papers,
            len(arxiv_ids) if arxiv_ids else 0,
        )
        result = search_agent.extract_full_texts(max_papers, arxiv_ids=arxiv_ids)
        logger.info(
            "Texts extracted: %s/%s papers",
            result.get("texts_extracted", 0),
            result.get("papers_processed", 0),
        )
        return result
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("Error in extract texts: %s", error_trace)
        raise HTTPException(status_code=500, detail=f"Text extraction failed: {str(e)}")


@router.post("/enrich-papers")
@limiter.limit("5/minute")
async def enrich_papers(
    request: Request,
    collect_references: bool = True,
    extract_texts: bool = True,
    max_references_per_paper: int = 10,
    max_papers: int = None,
    username: str = Depends(get_current_user),
):
    """Enrich saved papers (references + full-text + graph update).

    F-33: authenticated + rate-limited (5/min — strictest cap since this
    endpoint runs BOTH reference collection AND text extraction for every
    saved paper).
    """
    try:
        results = {"references": None, "texts": None, "success": True}

        if collect_references:
            logger.info("Step 1: Collecting references...")
            ref_result = search_agent.collect_references(
                max_references_per_paper, max_papers
            )
            results["references"] = ref_result
            logger.info(
                "References collected: %s", ref_result.get("references_found", 0)
            )

        if extract_texts:
            logger.info("Step 2: Extracting full texts...")
            text_result = search_agent.extract_full_texts(max_papers)
            results["texts"] = text_result
            logger.info("Texts extracted: %s", text_result.get("texts_extracted", 0))

        logger.info("Paper enrichment completed")
        return results

    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("Error in enrich papers: %s", error_trace)
        raise HTTPException(
            status_code=500, detail=f"Paper enrichment failed: {str(e)}"
        )


def _build_graph_sync(papers_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Synchronous graph building — runs in a thread to avoid blocking the event loop."""
    from src.utils.paper_utils import generate_result_key

    # Existing edge/layout helpers operate on doc_id. Give them private graph
    # records whose IDs are selection identities, never mutate stored records.
    papers_data = [
        {
            **paper,
            "doc_id": str(
                paper.get("result_key")
                or paper.get("doc_id")
                or generate_result_key(paper)
            ),
        }
        for paper in papers_data
    ]

    graph = nx.Graph()

    for paper in papers_data:
        doc_id = paper.get("doc_id")

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
    common_terms = _common_terms(papers_data)
    edge_method = "title_keyword_jaccard"
    edge_label = "제목·키워드 유사도"
    edge_threshold: Optional[float] = JACCARD_EDGE_THRESHOLD

    if n_papers >= _FAISS_THRESHOLD:
        try:
            logger.info("[Graph] Using FAISS ANN for %d papers", n_papers)
            _build_edges_faiss(papers_data, graph)
            edge_method = "semantic_cosine"
            edge_label = "제목 의미 유사도"
            edge_threshold = _FAISS_MIN_SIM
        except Exception as faiss_err:
            logger.warning("[Graph] FAISS failed: %s", faiss_err)
            if n_papers <= _MAX_JACCARD_PAPERS:
                logger.info("[Graph] Jaccard fallback for %d papers", n_papers)
                _build_edges_jaccard(papers_data, graph)
            else:
                logger.warning(
                    "[Graph] %d papers too large for Jaccard fallback, skipping edges",
                    n_papers,
                )
                edge_method = "unavailable"
                edge_label = "연결 계산 불가"
                edge_threshold = None
    else:
        _build_edges_jaccard(papers_data, graph)

    # Sparsify before community detection and layout so node positions are
    # explained by the edges the user actually sees: each node keeps its five
    # strongest edges, and a maximum spanning tree keeps every component
    # connected (so a path to the origin paper always exists).
    edge_total = graph.number_of_edges()
    if edge_total:
        kept = {
            frozenset(edge)
            for edge in nx.maximum_spanning_tree(graph, weight="weight").edges()
        }
        for node in graph.nodes():
            strongest = sorted(
                graph.edges(node, data="weight"),
                key=lambda edge: -(edge[2] or 0.0),
            )[:_SPARSE_TOP_K]
            kept.update(frozenset((u, v)) for u, v, _ in strongest)
        graph.remove_edges_from(
            [edge for edge in graph.edges() if frozenset(edge) not in kept]
        )

    communities = _annotate_graph_explanations(graph, papers_data, common_terms)

    # Layout
    try:
        layout = nx.spring_layout(graph, seed=42, iterations=100)
    except ImportError:
        logger.warning("scipy not available, using random layout fallback")
        import random as _rand

        _rand.seed(42)
        layout = {
            node: (_rand.uniform(-1, 1), _rand.uniform(-1, 1)) for node in graph.nodes()
        }

    if len(layout) > 0:
        centroid_x = sum(pos[0] for pos in layout.values()) / len(layout)
        centroid_y = sum(pos[1] for pos in layout.values()) / len(layout)
        centered = {
            nid: (x - centroid_x, y - centroid_y) for nid, (x, y) in layout.items()
        }

        max_abs = (
            max(
                max(abs(x) for x, _ in centered.values()),
                max(abs(y) for _, y in centered.values()),
            )
            or 1.0
        )
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
                    "community_id": node_data.get("community_id"),
                    "community_label": node_data.get("community_label", ""),
                }
            )

        edges = []
        for start, end in graph.edges():
            edges.append(
                {
                    "source": str(start),
                    "target": str(end),
                    "weight": graph.edges[start, end].get("weight", 0.1),
                    "shared_terms": graph.edges[start, end].get("shared_terms", []),
                }
            )
    else:
        edges = []

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "edge_method": edge_method,
            "edge_label": edge_label,
            "edge_threshold": edge_threshold,
            "directed": False,
            "communities": communities,
            "common_terms": sorted(common_terms),
            "edge_total": edge_total,
        },
    }


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
