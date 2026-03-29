"""
Singleton OpenAI client and LightRAG agent.
"""

import logging

logger = logging.getLogger(__name__)

# ── OpenAI client singleton ──────────────────────────────────────────
_openai_client = None


def get_openai_client():
    """Return (and lazily create) the singleton OpenAI client."""
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(timeout=120.0)
        logger.info("OpenAI client initialized (timeout=120s)")
    return _openai_client


# ── LightRAG singleton ────────────────────────────────────────────────
_light_rag_agent = None


def get_light_rag_agent():
    """Return (and lazily create) the singleton LightRAG agent."""
    global _light_rag_agent
    if _light_rag_agent is None:
        from app.GraphRAG.rag_agent import GraphRAGAgent

        _light_rag_agent = GraphRAGAgent(
            papers_json_path="data/raw/papers.json",
            graph_path="data/graph/paper_graph.pkl",
            embeddings_index_path="data/embeddings/paper_embeddings.index",
            id_mapping_path="data/embeddings/paper_id_mapping.json",
            light_rag_dir="data/light_rag",
        )
    return _light_rag_agent
