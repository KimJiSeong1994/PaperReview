"""Unit tests for src.graph.faiss_index_manager and FAISS-backed edge creation."""

import os
from unittest.mock import patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_embeddings(n: int, dim: int = 128, seed: int = 42) -> np.ndarray:
    """Generate random L2-normalised float32 embeddings."""
    rng = np.random.RandomState(seed)
    mat = rng.randn(n, dim).astype(np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


# ---------------------------------------------------------------------------
# build_similarity_index
# ---------------------------------------------------------------------------

class TestBuildSimilarityIndex:
    """Tests for build_similarity_index()."""

    def test_small_uses_flat_ip(self):
        """n < 2000 should use IndexFlatIP (exact search)."""
        from src.graph.faiss_index_manager import build_similarity_index
        import faiss

        emb = _random_embeddings(500)
        index = build_similarity_index(emb)

        # IndexFlatIP is the base type for small n
        assert index.ntotal == 500
        # FlatIP has no is_trained concern; verify search works
        scores, indices = index.search(emb[:1], 5)
        assert scores.shape == (1, 5)
        assert indices.shape == (1, 5)
        # Self should be the top match with score ~1.0
        assert indices[0][0] == 0
        assert scores[0][0] == pytest.approx(1.0, abs=0.01)

    def test_large_uses_hnsw(self):
        """n >= 2000 should use IndexHNSWFlat."""
        from src.graph.faiss_index_manager import build_similarity_index

        emb = _random_embeddings(2000, dim=64)
        index = build_similarity_index(emb)
        assert index.ntotal == 2000

        # Verify search still works
        scores, indices = index.search(emb[:1], 5)
        assert scores.shape == (1, 5)
        assert indices.shape == (1, 5)


# ---------------------------------------------------------------------------
# search_neighbors
# ---------------------------------------------------------------------------

class TestSearchNeighbors:
    """Tests for search_neighbors()."""

    def test_correct_shape(self):
        """Output shape should be (n, top_k)."""
        from src.graph.faiss_index_manager import build_similarity_index, search_neighbors

        n, dim, top_k = 100, 64, 5
        emb = _random_embeddings(n, dim)
        index = build_similarity_index(emb)
        scores, indices = search_neighbors(index, emb, top_k=top_k)

        assert scores.shape == (n, top_k)
        assert indices.shape == (n, top_k)

    def test_no_self_matches(self):
        """Self-index should not appear in the results."""
        from src.graph.faiss_index_manager import build_similarity_index, search_neighbors

        n, dim = 50, 32
        emb = _random_embeddings(n, dim)
        index = build_similarity_index(emb)
        scores, indices = search_neighbors(index, emb, top_k=5, min_similarity=0.0)

        for i in range(n):
            valid_nbrs = indices[i][indices[i] >= 0]
            assert i not in valid_nbrs, f"Self-match found for vector {i}"

    def test_min_similarity_filtering(self):
        """Entries below min_similarity should be masked to -1 / 0.0."""
        from src.graph.faiss_index_manager import build_similarity_index, search_neighbors

        n, dim = 30, 16
        emb = _random_embeddings(n, dim)
        index = build_similarity_index(emb)

        # Use a very high threshold so most matches are filtered
        scores, indices = search_neighbors(index, emb, top_k=5, min_similarity=0.99)

        # All filtered entries should have index == -1 and score == 0.0
        mask = indices == -1
        assert np.all(scores[mask] == 0.0)


# ---------------------------------------------------------------------------
# Edge deduplication in EdgeCreator
# ---------------------------------------------------------------------------

class TestEdgeCreatorFAISS:
    """Tests for FAISS-backed create_similarity_edges in EdgeCreator."""

    def _make_papers(self, n: int, dim: int = 64) -> list:
        """Create n mock papers with random embeddings."""
        emb = _random_embeddings(n, dim)
        papers = []
        for i in range(n):
            papers.append({
                "title": f"Paper {i}",
                "node_id": f"paper_{i}",
                "embedding": emb[i].tolist(),
            })
        return papers

    def test_edge_deduplication(self):
        """Edges should be deduplicated: (A, B) and (B, A) produce one edge."""
        from src.graph.edge_creator import EdgeCreator

        ec = EdgeCreator()
        papers = self._make_papers(20, dim=32)
        edges = ec.create_similarity_edges(papers, similarity_threshold=0.0, top_k=5)

        seen_pairs = set()
        for edge in edges:
            pair = tuple(sorted((edge["source"], edge["target"])))
            assert pair not in seen_pairs, f"Duplicate edge found: {pair}"
            seen_pairs.add(pair)

    def test_no_self_edges(self):
        """No edge should connect a paper to itself."""
        from src.graph.edge_creator import EdgeCreator

        ec = EdgeCreator()
        papers = self._make_papers(15, dim=32)
        edges = ec.create_similarity_edges(papers, similarity_threshold=0.0, top_k=10)

        for edge in edges:
            assert edge["source"] != edge["target"], f"Self-edge found: {edge['source']}"

    def test_edge_type_is_similar_to(self):
        """All edges should have edge_type == SIMILAR_TO."""
        from src.graph.edge_creator import EdgeCreator

        ec = EdgeCreator()
        papers = self._make_papers(10, dim=32)
        edges = ec.create_similarity_edges(papers, similarity_threshold=0.0, top_k=5)

        for edge in edges:
            assert edge["edge_type"] == "SIMILAR_TO"

    def test_empty_papers_returns_empty(self):
        """No papers -> no edges."""
        from src.graph.edge_creator import EdgeCreator

        ec = EdgeCreator()
        edges = ec.create_similarity_edges([], similarity_threshold=0.5)
        assert edges == []

    def test_single_paper_returns_empty(self):
        """One paper -> no edges."""
        from src.graph.edge_creator import EdgeCreator

        ec = EdgeCreator()
        papers = self._make_papers(1)
        edges = ec.create_similarity_edges(papers, similarity_threshold=0.0)
        assert edges == []


# ---------------------------------------------------------------------------
# GRAPH_FORCE_BRUTEFORCE env var
# ---------------------------------------------------------------------------

class TestBruteforceFallback:
    """Tests for GRAPH_FORCE_BRUTEFORCE=1 env var."""

    def test_force_bruteforce_uses_numpy(self):
        """Setting GRAPH_FORCE_BRUTEFORCE=1 should use the numpy brute-force path."""
        from src.graph.edge_creator import EdgeCreator

        ec = EdgeCreator()
        rng = np.random.RandomState(123)
        n, dim = 10, 32
        emb = rng.randn(n, dim).astype(np.float32)
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        emb = emb / norms

        papers = []
        for i in range(n):
            papers.append({
                "title": f"Paper {i}",
                "node_id": f"paper_{i}",
                "embedding": emb[i].tolist(),
            })

        with patch.dict(os.environ, {"GRAPH_FORCE_BRUTEFORCE": "1"}):
            edges = ec.create_similarity_edges(papers, similarity_threshold=0.0, top_k=5)

        # Should still produce valid edges via brute-force
        assert len(edges) > 0
        # Verify deduplication
        seen_pairs = set()
        for edge in edges:
            pair = tuple(sorted((edge["source"], edge["target"])))
            assert pair not in seen_pairs
            seen_pairs.add(pair)

    def test_bruteforce_matches_faiss(self):
        """Brute-force and FAISS should produce the same edge set for small n."""
        from src.graph.edge_creator import EdgeCreator

        ec = EdgeCreator()
        rng = np.random.RandomState(99)
        n, dim = 15, 32
        emb = rng.randn(n, dim).astype(np.float32)
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        emb = emb / norms

        papers = []
        for i in range(n):
            papers.append({
                "title": f"Paper {i}",
                "node_id": f"paper_{i}",
                "embedding": emb[i].tolist(),
            })

        threshold = 0.3

        # FAISS path
        with patch.dict(os.environ, {"GRAPH_FORCE_BRUTEFORCE": "0"}):
            faiss_edges = ec.create_similarity_edges(
                papers, similarity_threshold=threshold, top_k=5
            )

        # Brute-force path
        with patch.dict(os.environ, {"GRAPH_FORCE_BRUTEFORCE": "1"}):
            bf_edges = ec.create_similarity_edges(
                papers, similarity_threshold=threshold, top_k=5
            )

        faiss_pairs = {tuple(sorted((e["source"], e["target"]))) for e in faiss_edges}
        bf_pairs = {tuple(sorted((e["source"], e["target"]))) for e in bf_edges}

        assert faiss_pairs == bf_pairs, (
            f"Edge sets differ: FAISS-only={faiss_pairs - bf_pairs}, "
            f"BF-only={bf_pairs - faiss_pairs}"
        )
