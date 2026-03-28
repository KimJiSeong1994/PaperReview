"""
그래프 빌딩 공통 임계값/상수
"""

# ── Edge thresholds ──────────────────────────────────────────────────
JACCARD_EDGE_THRESHOLD = 0.12
COSINE_EDGE_THRESHOLD_STRICT = 0.5
COSINE_EDGE_THRESHOLD_RELAXED = 0.3

# ── Edge type constants ─────────────────────────────────────────────
EDGE_TYPE_CITES = "CITES"
EDGE_TYPE_SIMILAR_TO = "SIMILAR_TO"

# ── Hop depth limits by edge type ──────────────────────────────────
MAX_HOP_SIMILARITY = 1
MAX_HOP_CITATION = 2

# ── Citation collection limits ─────────────────────────────────────
CITATION_MAX_PER_PAPER = 20
CITATION_COLLECTION_DELAY = 0.5

# ── FAISS ANN parameters ────────────────────────────────────────────
FAISS_SWITCH_THRESHOLD = 100
FAISS_TOP_K = 10
