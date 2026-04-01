"""
Centralized FAISS index factory with automatic strategy selection.

- n < 2000: IndexFlatIP (exact search, no build cost)
- n >= 2000: IndexHNSWFlat (sub-linear queries)
- Graceful fallback if FAISS not available
"""

import logging
from typing import Tuple

import numpy as np

from src.graph.constants import (
    HNSW_EF_CONSTRUCTION,
    HNSW_EF_SEARCH,
    HNSW_M,
    HNSW_SWITCH_THRESHOLD,
)

logger = logging.getLogger(__name__)

try:
    import faiss

    _FAISS_AVAILABLE = True
except ImportError:
    _FAISS_AVAILABLE = False
    logger.warning("faiss not installed; falling back to numpy brute-force similarity")


def build_similarity_index(embeddings: np.ndarray) -> "faiss.Index":
    """Build a FAISS index with automatic strategy selection.

    Args:
        embeddings: L2-normalised float32 matrix of shape (n, dim).

    Returns:
        A FAISS index with all vectors added.

    Raises:
        RuntimeError: If FAISS is not available.
    """
    if not _FAISS_AVAILABLE:
        raise RuntimeError("faiss is not installed")

    n, dim = embeddings.shape

    if n < HNSW_SWITCH_THRESHOLD:
        index = faiss.IndexFlatIP(dim)
        logger.info(
            "[FAISS] Using IndexFlatIP (exact) for %d vectors, dim=%d", n, dim
        )
    else:
        index = faiss.IndexHNSWFlat(dim, HNSW_M, faiss.METRIC_INNER_PRODUCT)
        index.hnsw.efConstruction = HNSW_EF_CONSTRUCTION
        index.hnsw.efSearch = HNSW_EF_SEARCH
        logger.info(
            "[FAISS] Using IndexHNSWFlat (M=%d, efC=%d, efS=%d) for %d vectors, dim=%d",
            HNSW_M,
            HNSW_EF_CONSTRUCTION,
            HNSW_EF_SEARCH,
            n,
            dim,
        )

    index.add(embeddings)
    return index


def search_neighbors(
    index: "faiss.Index",
    embeddings: np.ndarray,
    top_k: int = 10,
    min_similarity: float = 0.3,
) -> Tuple[np.ndarray, np.ndarray]:
    """Search the index for top-k neighbours per vector.

    Searches for ``top_k + 1`` neighbours and strips the self-match
    (position 0).  Entries below *min_similarity* are masked to -1
    (indices) and 0.0 (scores).

    Args:
        index: A FAISS index returned by :func:`build_similarity_index`.
        embeddings: The same L2-normalised matrix used to build the index.
        top_k: Number of neighbours to return (excluding self).
        min_similarity: Minimum inner-product score to keep.

    Returns:
        ``(scores, indices)`` each of shape ``(n, top_k)``.
        Invalid entries have index == -1 and score == 0.0.
    """
    k = min(top_k + 1, embeddings.shape[0])
    raw_scores, raw_indices = index.search(embeddings, k)

    # Strip self-match (position 0 for FlatIP; may vary for HNSW)
    scores = raw_scores[:, 1:]
    indices = raw_indices[:, 1:]

    # Mask entries below threshold
    mask = (scores < min_similarity) | (indices < 0)
    scores[mask] = 0.0
    indices[mask] = -1

    return scores, indices
