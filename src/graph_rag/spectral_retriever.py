"""Bounded paper-metadata adaptation of SpectRAG (MIT, c9599c455b52).

Reference: https://github.com/SightAndCite/SpectRAG/tree/c9599c455b52a53a8c58743dc2fc91332a25c857
Uses normalized-Laplacian proximity, PPR and protected-core diverse selection.
Unlike upstream, nodes are papers and edges are lexical/citation relationships;
there is no claim of dense semantic retrieval or full-text chunk equivalence.
No model/network calls or full-corpus matrix is built on the request path.
"""

from __future__ import annotations

import copy
import heapq
import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components

from src.utils.paper_utils import generate_result_key

VERSION = "spectrag-metadata-v1"
MAX_CANDIDATES = 128
MODES = {"baseline", "spectral", "ppr"}


def configured_mode() -> str:
    value = os.getenv("KCI_RETRIEVAL_MODE", "baseline").strip().lower()
    # An invalid operator value must not silently launch a different algorithm.
    return value if value in MODES else "baseline"


def _expired(deadline, stop_event) -> bool:
    return bool(stop_event is not None and stop_event.is_set()) or (
        deadline is not None and time.monotonic() >= deadline
    )


def expand_graph_candidates(graph, seeds, *, max_candidates=MAX_CANDIDATES, hops=2,
                            deadline=None, stop_event=None):
    """Bounded weighted BFS for existing paper graphs; no corpus-wide scan.

    Include incoming citation links as well as outgoing neighbors. Inspect at
    most 512 neighbors per node and keep the strongest eight per expansion.
    """
    from itertools import chain, islice

    cap = max(1, min(MAX_CANDIDATES, max_candidates))
    selected = list(dict.fromkeys(node for node in seeds if node in graph))[:cap]
    seen = set(selected)
    frontier = list(selected)
    for _ in range(min(2, max(0, hops))):
        next_frontier = []
        for node in frontier:
            if _expired(deadline, stop_event) or len(selected) >= cap:
                return selected
            neighbors = graph.neighbors(node)
            if graph.is_directed():
                neighbors = chain(neighbors, graph.predecessors(node))
            candidates = {}
            for neighbor in islice(neighbors, 512):
                if neighbor in seen:
                    continue
                weight = 0.0
                for a, b in ((node, neighbor), (neighbor, node)):
                    attributes = graph.get_edge_data(a, b) or {}
                    entries = attributes.values() if graph.is_multigraph() else [attributes]
                    for entry in entries:
                        value = entry.get("weight", 1.0 if entry.get("edge_type") == "CITES" else 0.0)
                        if isinstance(value, (int, float)) and math.isfinite(value):
                            weight = max(weight, value)
                if weight > 0:
                    candidates[neighbor] = weight
            for neighbor, _weight in heapq.nsmallest(8, candidates.items(), key=lambda item: (-item[1], str(item[0]))):
                if len(selected) >= cap:
                    return selected
                seen.add(neighbor)
                selected.append(neighbor)
                next_frontier.append(neighbor)
        frontier = next_frontier
    return selected


def _features(text: str) -> Counter:
    words = re.findall(r"[^\W_]+", text[:6000].casefold(), re.UNICODE)
    counts = Counter(w for w in words if len(w) > 1)
    # Korean compound/spacing variation; prefixes avoid collisions with words.
    for word in words:
        if re.fullmatch(r"[가-힣]{3,}", word):
            counts.update("ko:" + word[i:i + 2] for i in range(len(word) - 1))
    return counts


def _text(paper):
    return " ".join(str(paper.get(key) or "") for key in
                    ("title", "title", "title_en", "abstract", "abstract_en"))


def _similarities(query, papers):
    docs = [_features(_text(p)) for p in papers]
    df = Counter(term for doc in docs for term in doc)
    # Bound memory even for adversarially long/diverse metadata.
    vocab = {term: i for i, (term, _) in enumerate(df.most_common(8192))}
    rows, cols, values = [], [], []
    for i, doc in enumerate([*docs, _features(query)]):
        for term, count in doc.items():
            if term in vocab:
                rows.append(i)
                cols.append(vocab[term])
                values.append((1 + math.log(count)) * (1 + math.log((1 + len(docs)) / (1 + df[term]))))
    matrix = csr_matrix((values, (rows, cols)), shape=(len(docs) + 1, len(vocab)), dtype=float)
    norms = np.sqrt(matrix.multiply(matrix).sum(axis=1)).A1
    matrix = matrix.multiply((1 / np.maximum(norms, 1e-12))[:, None]).tocsr()
    similarity = (matrix[:-1] @ matrix[:-1].T).toarray()
    relevance = (matrix[:-1] @ matrix[-1].T).toarray().ravel()
    return similarity, relevance


def _adjacency(similarity, papers, edges):
    n = len(papers)
    adjacency = np.zeros((n, n), dtype=float)
    for i in range(n):
        neighbors = sorted(range(n), key=lambda j: (-similarity[i, j], j))
        for j in [j for j in neighbors if j != i and similarity[i, j] >= 0.15][:8]:
            adjacency[i, j] = similarity[i, j]
    adjacency = np.maximum(adjacency, adjacency.T)
    index = {generate_result_key(p): i for i, p in enumerate(papers)}
    for left, right, weight in edges:
        if left not in index or right not in index or left == right:
            continue
        if not isinstance(weight, (float, int)) or not math.isfinite(weight) or weight <= 0:
            continue
        i, j = index[left], index[right]
        adjacency[i, j] = adjacency[j, i] = max(adjacency[i, j], min(1.0, weight))
    np.fill_diagonal(adjacency, 0)
    return adjacency


def _proximity(adjacency, seeds, mode, deadline, stop_event):
    n = len(adjacency)
    seed_mass = np.zeros(n)
    seed_mass[seeds] = 1 / len(seeds)
    degree = adjacency.sum(axis=1)
    transition = adjacency / np.maximum(degree[:, None], 1e-12)
    ppr = seed_mass.copy()
    for _ in range(100):
        if _expired(deadline, stop_event):
            raise TimeoutError("retrieval deadline")
        updated = 0.15 * seed_mass + 0.85 * (transition.T @ ppr + ppr[degree == 0].sum() * seed_mass)
        if np.abs(updated - ppr).sum() < 1e-9:
            ppr = updated
            break
        ppr = updated
    ppr /= max(float(ppr.max()), 1e-12)
    if mode == "ppr":
        return ppr

    # Component-local spectra prevent disconnected nodes acquiring proximity
    # from arbitrary zero-eigenvalue eigenvectors or position interpolation.
    _, labels = connected_components(csr_matrix(adjacency), directed=False)
    spectral = np.zeros(n)
    for label in sorted(set(labels)):
        members = np.flatnonzero(labels == label)
        local_seeds = np.flatnonzero(np.isin(members, seeds))
        if len(members) < 3 or not len(local_seeds):
            spectral[members] = ppr[members]
            continue
        if _expired(deadline, stop_event):
            raise TimeoutError("retrieval deadline")
        a = adjacency[np.ix_(members, members)]
        inv = 1 / np.sqrt(np.maximum(a.sum(axis=1), 1e-12))
        laplacian = np.eye(len(members)) - inv[:, None] * a * inv[None, :]
        values, vectors = np.linalg.eigh(laplacian)
        usable = np.flatnonzero(values > 1e-8)
        if not len(usable):
            spectral[members] = ppr[members]
            continue
        # Keep a complete repeated-eigenvalue block, so basis rotations do not
        # change cosine proximity when the spectrum has tied eigenvalues.
        cutoff = values[usable[min(7, len(usable) - 1)]]
        coords = vectors[:, (values > 1e-8) & (values <= cutoff + 1e-8)]
        coords /= np.maximum(np.linalg.norm(coords, axis=1, keepdims=True), 1e-12)
        spectral[members] = np.maximum(0, (coords @ coords[local_seeds].T).max(axis=1))
    return (spectral + ppr) / 2


@dataclass(frozen=True)
class RetrievalResult:
    papers: list[dict]
    metadata: dict


def retrieve(query, papers, top_k=10, *, mode="spectral", edges=(), deadline=None, stop_event=None):
    """Select papers from a bounded candidate pool; preserve input on failure.

    Input order is the lexical/dense baseline. Protect its first two candidates;
    all-term matches outrank relaxed matches even after graph scoring. This is
    candidate-set retrieval, not a full-corpus semantic index.
    """
    if mode not in MODES:
        raise ValueError(f"Unsupported retrieval mode: {mode}")
    if not isinstance(top_k, int) or not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    candidates = list(papers[:MAX_CANDIDATES])
    fallback = copy.deepcopy(candidates[:top_k])
    metadata = {"version": VERSION, "mode": mode, "candidate_count": len(candidates),
                "input_truncated": len(papers) > MAX_CANDIDATES, "graph_edges": 0}
    if mode == "baseline" or len(candidates) < 3:
        return RetrievalResult(fallback, {**metadata, "status": "baseline"})
    if _expired(deadline, stop_event):
        return RetrievalResult(fallback, {**metadata, "status": "deadline_fallback"})
    try:
        similarity, relevance = _similarities(query, candidates)
        adjacency = _adjacency(similarity, candidates, edges)
        metadata["graph_edges"] = int(np.count_nonzero(adjacency) // 2)
        if not np.any(adjacency) or not np.any(relevance):
            return RetrievalResult(fallback, {**metadata, "status": "no_signal_fallback"})
        rank_prior = 1 / (1 + np.arange(len(candidates)) / 10)
        raw = 0.7 * relevance / max(float(relevance.max()), 1e-12) + 0.3 * rank_prior
        seeds = list(range(min(5, len(candidates))))
        proximity = _proximity(adjacency, seeds, mode, deadline, stop_event)
        scores = 0.8 * raw + 0.2 * proximity
        selected = list(range(min(2, top_k, len(candidates))))
        remaining = set(range(len(candidates))) - set(selected)
        while remaining and len(selected) < top_k:
            if _expired(deadline, stop_event):
                raise TimeoutError("retrieval deadline")
            # Keep exact conjunction matches before relaxing to partial ones.
            tier = min(candidates[i].get("_kci_match_tier", 0) for i in remaining)
            eligible = [i for i in remaining if candidates[i].get("_kci_match_tier", 0) == tier]
            def utility(i):
                redundancy = max(similarity[i, j] for j in selected) if selected else 0
                return scores[i] - 0.12 * redundancy
            chosen = max(eligible, key=lambda i: (utility(i), -i))
            selected.append(chosen)
            remaining.remove(chosen)
        output = []
        for i in selected:
            paper = copy.deepcopy(candidates[i])
            paper["_retrieval_score"] = round(float(scores[i]), 8)
            output.append(paper)
        return RetrievalResult(output, {**metadata, "status": "completed"})
    except (TimeoutError, np.linalg.LinAlgError):
        return RetrievalResult(fallback, {**metadata, "status": "compute_fallback"})


def select_context(papers, token_budget, count_tokens, *, render):
    """Pack complete serialized records under a strict budget, skipping oversize.

    The caller supplies its actual tokenizer and rendering (including metadata
    and separators). No character-count heuristic is reported as model tokens.
    Returns selected records and the exact cost of their combined rendering.
    """
    if not isinstance(token_budget, int) or token_budget < 0:
        raise ValueError("token_budget must be a nonnegative integer")
    if count_tokens(render([])) > token_budget:
        raise ValueError("The empty context wrapper exceeds token_budget")
    selected = []
    for paper in papers:
        if count_tokens(render([*selected, paper])) <= token_budget:
            selected.append(paper)
    return selected, count_tokens(render(selected))
