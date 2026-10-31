"""Phase 0 readability metrics for the paper-relationship graph (no browser).

Builds three synthetic result sets, runs the real graph builder, and prints
M1 (edges per node), M2 (edges returned vs. edges before sparsification) and
M5 (community labels free of common terms and pairwise distinct).

Run: ``uv run python scripts/graph_readability_report.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers.papers import _build_graph_sync  # noqa: E402

_TAILS = [
    "federated",
    "poisoning",
    "survey",
    "medical",
    "legal",
    "agents",
    "multimodal",
    "temporal",
    "hyperbolic",
    "benchmark",
    "privacy",
    "code",
]
_HETERO = [
    "Attention Is All You Need",
    "Deep Residual Learning for Image Recognition",
    "Language Models are Few-Shot Learners",
    "Denoising Diffusion Probabilistic Models",
    "Playing Atari with Deep Reinforcement Learning",
    "BERT Pretraining of Deep Bidirectional Transformers",
    "Generative Adversarial Networks",
    "Adam: A Method for Stochastic Optimization",
    "Segment Anything",
    "Neural Machine Translation by Jointly Learning to Align",
]


def _homogeneous(count: int) -> list[dict]:
    return [
        {
            "doc_id": f"h{i}",
            "title": (
                "Graph Retrieval-Augmented Generation for "
                f"{_TAILS[i % len(_TAILS)]} {_TAILS[(i * 7 + 3) % len(_TAILS)]}"
            ),
            "keywords": [_TAILS[i % len(_TAILS)]],
            "citations": i,
        }
        for i in range(count)
    ]


def _heterogeneous(count: int) -> list[dict]:
    return [
        {
            "doc_id": f"x{i}",
            "title": f"{_HETERO[i % len(_HETERO)]} {_TAILS[i % len(_TAILS)]}",
            "keywords": [_TAILS[(i * 3) % len(_TAILS)]],
            "citations": i,
        }
        for i in range(count)
    ]


def _metrics(name: str, papers: list[dict]) -> dict:
    graph = _build_graph_sync(papers)
    meta = graph["meta"]
    nodes, edges = len(graph["nodes"]), len(graph["edges"])
    common = set(meta.get("common_terms", []))
    labels = [c["label"] for c in meta["communities"]]
    label_terms = {t for label in labels for t in label.replace(" · ", " ").split()}
    return {
        "fixture": name,
        "nodes": nodes,
        "M1 edges/node": round(edges / nodes, 2) if nodes else 0,
        "M2 edges drawn/total": f"{edges}/{meta.get('edge_total', edges)}",
        "M5 common term in label": bool(common & label_terms),
        "M5 labels distinct": len(labels) == len(set(labels)),
        "communities": len(labels),
        "isolated nodes": sum(n["community_id"] is None for n in graph["nodes"]),
        "sizes": [c["size"] for c in meta["communities"]],
        "labels": labels,
    }


def main() -> None:
    rows = [
        _metrics("80 homogeneous (query echo)", _homogeneous(80)),
        _metrics("40 heterogeneous", _heterogeneous(40)),
        _metrics("20 mixed", _homogeneous(10) + _heterogeneous(10)),
    ]
    keys = [k for k in rows[0] if k not in ("labels", "sizes")]
    print(" | ".join(keys))
    for row in rows:
        print(" | ".join(str(row[k]) for k in keys))
        print("   sizes:", row["sizes"], "labels:", row["labels"])
    # Self-check: fails loudly if the readability targets regress.
    assert all(row["M1 edges/node"] <= 5 for row in rows), (
        "M1 target: <= 5 edges per node"
    )
    assert not any(row["M5 common term in label"] for row in rows), (
        "M5: common term leaked into label"
    )
    assert all(row["M5 labels distinct"] for row in rows), (
        "M5: duplicate community labels"
    )


if __name__ == "__main__":
    main()
