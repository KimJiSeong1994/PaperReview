"""
Service layer for Citation Tree Explorer.

Uses Semantic Scholar API for citation data.
"""

import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import networkx as nx
import requests

logger = logging.getLogger(__name__)


def _normalize_title(title: str) -> str:
    """Normalize a paper title for deduplication.

    Strips whitespace, lowercases, removes punctuation so that
    'Attention Is All You Need' and 'Attention is All You Need.'
    are treated as the same paper.
    """
    t = title.strip().lower()
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'\s+', ' ', t)
    return t

# ── Citation Tree ─────────────────────────────────────────────────────


_S2_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _s2_request(session: Any, url: str, params: dict, timeout: int = 20, max_retries: int = 3) -> Any:
    """HTTP GET wrapper with exponential backoff retry for transient errors.

    Retries on 429 (rate limit) and 5xx server errors.
    Returns the response object on success.
    Raises the last exception after exhausting retries.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            if resp.status_code in _S2_RETRYABLE_STATUS:
                wait = min(2 ** attempt * 2, 10)
                logger.warning(
                    "Semantic Scholar %d, retrying in %ds (attempt %d/%d)",
                    resp.status_code, wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
                last_exc = Exception(f"Semantic Scholar returned {resp.status_code}")
                continue
            resp.raise_for_status()
            return resp
        except requests.exceptions.Timeout as e:
            wait = min(2 ** attempt * 2, 10)
            logger.warning(
                "Semantic Scholar timeout, retrying in %ds (attempt %d/%d)",
                wait, attempt + 1, max_retries,
            )
            time.sleep(wait)
            last_exc = e
            continue
        except requests.exceptions.ConnectionError as e:
            wait = min(2 ** attempt * 2, 10)
            logger.warning(
                "Semantic Scholar connection error, retrying in %ds (attempt %d/%d)",
                wait, attempt + 1, max_retries,
            )
            time.sleep(wait)
            last_exc = e
            continue
        except Exception as e:
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            if status in _S2_RETRYABLE_STATUS:
                wait = min(2 ** attempt * 2, 10)
                logger.warning(
                    "Semantic Scholar %s, retrying in %ds (attempt %d/%d)",
                    status, wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
                last_exc = e
                continue
            raise
    raise last_exc or Exception("Max retries exceeded for Semantic Scholar API")


def _resolve_paper(paper: Dict[str, Any], session: Any) -> Optional[Dict[str, str]]:
    """Resolve a paper to its canonical Semantic Scholar paperId and URL.

    Returns dict with 'paperId' and 'url', or None if not found.
    Always returns the canonical hex paperId to prevent duplicate entries
    caused by mixing DOI:/ARXIV: prefixed IDs with hex IDs.
    """
    base_url = "https://api.semanticscholar.org/graph/v1"

    # Try DOI or ARXIV lookup — resolve to canonical paperId
    lookup_id = None
    if paper.get("doi"):
        lookup_id = f"DOI:{paper['doi']}"
    elif paper.get("arxiv_id"):
        arxiv_id = paper["arxiv_id"].split("v")[0]
        lookup_id = f"ARXIV:{arxiv_id}"

    if lookup_id:
        try:
            resp = _s2_request(
                session,
                f"{base_url}/paper/{lookup_id}",
                params={"fields": "paperId,url"},
                timeout=20,
            )
            data = resp.json()
            pid = data.get("paperId")
            if pid:
                url = data.get("url") or f"https://www.semanticscholar.org/paper/{pid}"
                return {"paperId": pid, "url": url}
        except Exception as e:
            logger.debug("Semantic Scholar lookup by ID failed for %s: %s", lookup_id, e)

    # Fallback to title search
    title = paper.get("title", "")
    if not title:
        return None

    try:
        resp = _s2_request(
            session,
            f"{base_url}/paper/search",
            params={"query": title, "limit": 1, "fields": "paperId,url"},
            timeout=20,
        )
        data = resp.json()
        if data.get("data"):
            result = data["data"][0]
            pid = result.get("paperId")
            if pid:
                url = result.get("url") or f"https://www.semanticscholar.org/paper/{pid}"
                return {"paperId": pid, "url": url}
    except Exception as e:
        logger.debug("Semantic Scholar title search failed for '%s': %s", title[:50], e)
    return None


def _fetch_citations(paper_id: str, direction: str, session: Any, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch forward or backward citations from Semantic Scholar.

    Args:
        direction: 'references' (backward) or 'citations' (forward)
    """
    base_url = "https://api.semanticscholar.org/graph/v1"
    endpoint = f"{base_url}/paper/{paper_id}/{direction}"
    fields = "title,authors,year,citationCount,abstract,url,externalIds,contexts,intents,isInfluential"

    try:
        resp = _s2_request(session, endpoint, params={"limit": limit, "fields": fields}, timeout=20)
        data = resp.json()

        results = []
        key = "citedPaper" if direction == "references" else "citingPaper"
        for item in data.get("data", []):
            p = item.get(key)
            if not p or not p.get("paperId") or not p.get("title"):
                continue
            # contexts/intents/isInfluential are on the wrapper item, not nested paper
            results.append({
                "paper_id": p["paperId"],
                "title": p.get("title", ""),
                "authors": [a.get("name", "") for a in p.get("authors", [])[:5]],
                "year": p.get("year"),
                "citations": p.get("citationCount", 0),
                "abstract": (p.get("abstract") or "")[:300],
                "url": p.get("url") or f"https://www.semanticscholar.org/paper/{p['paperId']}",
                "contexts": item.get("contexts") or [],
                "intents": item.get("intents") or [],
                "is_influential": item.get("isInfluential", False),
            })
        return results
    except Exception as e:
        logger.warning("Failed to fetch %s for %s: %s", direction, paper_id, e)
        return []


def generate_citation_tree(
    papers: List[Dict[str, Any]],
    depth: int = 1,
    max_per_direction: int = 10,
) -> Dict[str, Any]:
    """Generate a citation tree for the given papers.

    Collects backward (references) and forward (citing) papers,
    builds a NetworkX DiGraph, computes hierarchical layout,
    and returns positioned nodes + edges.
    """
    import requests

    session = requests.Session()
    headers = {"User-Agent": "PaperReviewAgent/1.0"}
    s2_key = os.getenv("S2_API_KEY")
    if s2_key:
        headers["x-api-key"] = s2_key
    session.headers.update(headers)

    try:
        return _build_citation_tree(papers, depth, max_per_direction, session)
    finally:
        session.close()


def _build_citation_tree(
    papers: List[Dict[str, Any]],
    depth: int,
    max_per_direction: int,
    session: Any,
) -> Dict[str, Any]:
    """Internal helper that builds the citation tree with a given session."""
    graph = nx.DiGraph()
    node_data: Dict[str, Dict[str, Any]] = {}
    # Title-based dedup: normalized_title → paperId
    seen_titles: Dict[str, str] = {}

    def _is_duplicate(paper_id: str, title: str) -> Optional[str]:
        """Check if a paper is a duplicate by ID or normalized title.

        Returns the existing node ID if duplicate, None otherwise.
        """
        if paper_id in node_data:
            return paper_id
        norm = _normalize_title(title)
        if norm in seen_titles:
            return seen_titles[norm]
        return None

    def _register(paper_id: str, title: str) -> None:
        """Register a paper ID and its normalized title."""
        seen_titles[_normalize_title(title)] = paper_id

    # Add root papers (depth=0) — skip papers not found on Semantic Scholar
    root_ids = []
    skipped_papers = []
    for paper in papers:
        resolved = _resolve_paper(paper, session)
        if not resolved:
            title = paper.get("title", "Unknown")
            logger.info("Skipping paper not found on Semantic Scholar: %s", title)
            skipped_papers.append(title)
            continue

        pid = resolved["paperId"]

        # Skip duplicate root papers
        existing = _is_duplicate(pid, paper.get("title", ""))
        if existing:
            if existing not in root_ids:
                root_ids.append(existing)
            continue

        root_ids.append(pid)

        node_data[pid] = {
            "id": pid,
            "title": paper.get("title", "Unknown"),
            "authors": paper.get("authors", [])[:5],
            "year": paper.get("year"),
            "citations": paper.get("citations", 0),
            "depth": 0,
            "direction": "root",
            "url": resolved["url"],
        }
        _register(pid, paper.get("title", ""))
        graph.add_node(pid, subset=0)

        time.sleep(0.3)

        # Backward citations (references)
        refs = _fetch_citations(pid, "references", session, limit=max_per_direction)
        for ref in refs:
            rid = ref["paper_id"]
            edge_data = {
                "weight": 1.0,
                "contexts": ref.get("contexts", []),
                "intents": ref.get("intents", []),
                "is_influential": ref.get("is_influential", False),
            }
            existing = _is_duplicate(rid, ref["title"])
            if existing:
                graph.add_edge(pid, existing, **edge_data)
            else:
                node_data[rid] = {**ref, "id": rid, "depth": -1, "direction": "backward"}
                _register(rid, ref["title"])
                graph.add_node(rid, subset=-1)
                graph.add_edge(pid, rid, **edge_data)

        time.sleep(0.5)

        # Forward citations (citing papers)
        cites = _fetch_citations(pid, "citations", session, limit=max_per_direction)
        for cite in cites:
            cid = cite["paper_id"]
            edge_data = {
                "weight": 1.0,
                "contexts": cite.get("contexts", []),
                "intents": cite.get("intents", []),
                "is_influential": cite.get("is_influential", False),
            }
            existing = _is_duplicate(cid, cite["title"])
            if existing:
                graph.add_edge(existing, pid, **edge_data)
            else:
                node_data[cid] = {**cite, "id": cid, "depth": 1, "direction": "forward"}
                _register(cid, cite["title"])
                graph.add_node(cid, subset=1)
                graph.add_edge(cid, pid, **edge_data)

        time.sleep(0.3)

    # Compute layout
    if len(graph.nodes) == 0:
        return {"nodes": [], "edges": [], "root_paper_ids": root_ids, "skipped_papers": skipped_papers, "generated_at": datetime.now().isoformat()}

    try:
        pos = nx.multipartite_layout(graph, subset_key="subset", scale=1.0)
    except Exception as e:
        logger.debug("Multipartite layout failed, using spring layout: %s", e)
        try:
            pos = nx.spring_layout(graph, seed=42, k=1.0, iterations=50)
        except ImportError:
            logger.warning("scipy not available, using random layout fallback")
            import random as _rand
            _rand.seed(42)
            pos = {node: (_rand.uniform(-1, 1), _rand.uniform(-1, 1)) for node in graph.nodes()}

    # Build output
    nodes = []
    for nid, data in node_data.items():
        x, y = pos.get(nid, (0, 0))
        nodes.append({**data, "x": float(x), "y": float(y)})

    edges = [
        {
            "source": u,
            "target": v,
            "weight": d.get("weight", 1.0),
            "contexts": d.get("contexts", []),
            "intents": d.get("intents", []),
            "is_influential": d.get("is_influential", False),
        }
        for u, v, d in graph.edges(data=True)
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "root_paper_ids": root_ids,
        "skipped_papers": skipped_papers,
        "generated_at": datetime.now().isoformat(),
    }
