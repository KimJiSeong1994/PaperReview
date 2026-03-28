"""
그래프 빌딩 공통 임계값/상수
"""

# ── Edge thresholds ──────────────────────────────────────────────────
JACCARD_EDGE_THRESHOLD = 0.12
COSINE_EDGE_THRESHOLD_STRICT = 0.5
COSINE_EDGE_THRESHOLD_RELAXED = 0.3

# ── FAISS ANN parameters ────────────────────────────────────────────
FAISS_SWITCH_THRESHOLD = 100
FAISS_TOP_K = 10
