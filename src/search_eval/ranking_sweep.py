"""Score the real ranker against the labelled benchmark, at several fusion weights.

``retrieval_eval.score_retrieval_results`` has existed for a while but has only
ever been fed ``build_fixture_retrieval_results`` — deterministic stand-ins that
prove the scorer and approval chain work and explicitly do not claim anything
about live search. This module supplies the missing half: it ranks a real
candidate pool with the production :class:`HybridRanker` and hands the output to
that same scorer, so ``CROSS_ENCODER_RRF_WEIGHT`` can be chosen from a number
instead of a guess.

Two steps, deliberately separate:

``capture``
    Hit the real sources once per benchmark query and write the union of hits to
    a candidate-pool file. Needs network. Non-deterministic, so it is done once
    and the result is pinned by sha256.

``sweep``
    Rank that fixed pool at each weight and score it. No network beyond the local
    cross-encoder, so every weight sees exactly the same candidates and the only
    thing varying is the fusion — which is what makes the comparison fair.

Semantic scoring is off by default: it needs OpenAI embeddings, which would add
cost and run-to-run variance to a comparison that is about the fusion weight.
Pass a ``similarity_calculator`` to include it.

Usage
-----
    python -m src.search_eval.ranking_sweep capture
    python -m src.search_eval.ranking_sweep sweep --weights 0 1 2 4 8
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Sequence

from src.graph_rag.hybrid_ranker import CROSS_ENCODER_RRF_WEIGHT, HybridRanker

from .retrieval_eval import score_retrieval_results
from .skillopt_contract import ValidationError, load_json, validate_dataset_contract

DEFAULT_DATASET = Path("data/search_eval/skillopt_paper_search_v0.json")
DEFAULT_POOL = Path("data/search_eval/candidate_pool_v1.json")

POOL_VERSION = "search-candidate-pool-v1"


def _pool_hash(pool: dict[str, Any]) -> str:
    """sha256 over the canonical pool body, excluding the hash field itself."""
    body = {key: value for key, value in pool.items() if key != "pool_hash"}
    payload = json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


# ── capture ───────────────────────────────────────────────────────────


def capture_candidate_pool(
    *,
    dataset_path: Path = DEFAULT_DATASET,
    out_path: Path = DEFAULT_POOL,
    per_source: int = 15,
) -> dict[str, Any]:
    """Search the real sources for every benchmark query and pin the results.

    arXiv, OpenAlex and DBLP only: they need no API key, so the capture is
    reproducible by anyone with network access. Failures on one source are
    recorded per query rather than aborting — a partial pool that says which
    source was missing is more useful than none.
    """
    # Imported here so `sweep` never pulls in the network searchers.
    from src.collector.paper.arxiv_searcher import ArxivSearcher
    from src.collector.paper.dblp_searcher import DBLPSearcher
    from src.collector.paper.openalex_searcher import OpenAlexSearcher

    dataset = load_json(str(dataset_path))
    validate_dataset_contract(dataset)

    searchers = {
        "arxiv": lambda q: ArxivSearcher().search(q, max_results=per_source),
        "openalex": lambda q: OpenAlexSearcher().search(q, max_results=per_source),
        "dblp": lambda q: DBLPSearcher().search(q, max_results=per_source),
    }

    candidates: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, list[str]] = {}
    for query in dataset["queries"]:
        query_id = str(query["query_id"])
        seen: set[str] = set()
        pool: list[dict[str, Any]] = []
        for source, run in searchers.items():
            try:
                hits = run(query["query_text"]) or []
            except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                errors.setdefault(query_id, []).append(f"{source}: {type(exc).__name__}: {exc}")
                continue
            for hit in hits:
                title = (hit.get("title") or "").strip()
                key = title.lower()
                if not title or key in seen:
                    continue
                seen.add(key)
                pool.append(
                    {
                        "title": title,
                        "abstract": (hit.get("abstract") or "")[:2000],
                        "year": hit.get("year"),
                        "citations": hit.get("citations") or 0,
                        "source": source,
                    }
                )
        candidates[query_id] = pool

    pool_body: dict[str, Any] = {
        "version": POOL_VERSION,
        "dataset_hash": dataset["dataset_hash"],
        "per_source": per_source,
        "sources": sorted(searchers),
        "candidates": candidates,
        "capture_errors": errors,
    }
    pool_body["pool_hash"] = _pool_hash(pool_body)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(pool_body, ensure_ascii=False, indent=2), encoding="utf-8")
    return pool_body


def load_candidate_pool(pool_path: Path = DEFAULT_POOL) -> dict[str, Any]:
    """Load a pool and verify it has not been edited since capture."""
    pool = load_json(str(pool_path))
    if pool.get("version") != POOL_VERSION:
        raise ValidationError(f"candidate pool version must be {POOL_VERSION}")
    recorded = pool.get("pool_hash")
    actual = _pool_hash(pool)
    if recorded != actual:
        raise ValidationError(
            f"candidate pool hash mismatch: recorded {recorded}, computed {actual}"
        )
    return pool


# ── sweep ─────────────────────────────────────────────────────────────


def score_pool_at_weight(
    *,
    pool: dict[str, Any],
    dataset_path: Path = DEFAULT_DATASET,
    cross_encoder_weight: float,
    similarity_calculator: Any = None,
) -> dict[str, Any]:
    """Rank every query's pool at *cross_encoder_weight* and score the result."""
    ranker = HybridRanker(similarity_calculator=similarity_calculator)
    ranked_by_query: dict[str, list[dict[str, Any]]] = {}
    latencies_ms: list[float] = []

    for query in load_json(str(dataset_path))["queries"]:
        query_id = str(query["query_id"])
        # Fresh dicts per weight: rank_papers annotates and sorts in place, so a
        # shared list would leak one weight's scores into the next run.
        papers = [dict(candidate) for candidate in pool["candidates"].get(query_id, [])]
        started = time.perf_counter()
        ranked = ranker.rank_papers(
            query=query["query_text"],
            papers=papers,
            intent=query.get("intent", "paper_search"),
            use_rrf=True,
            cross_encoder_weight=cross_encoder_weight,
        )
        latencies_ms.append((time.perf_counter() - started) * 1000.0)
        ranked_by_query[query_id] = ranked[:10]

    latencies_ms.sort()
    p95 = latencies_ms[max(0, int(len(latencies_ms) * 0.95) - 1)] if latencies_ms else 0.0

    return score_retrieval_results(
        dataset_path=str(dataset_path),
        results_by_query=ranked_by_query,
        p95_latency_ms=max(p95, 1e-6),
        evidence_mode="measured",
        capture_id=f"{pool['version']}@ce_w={cross_encoder_weight}",
        capture_hash=pool["pool_hash"],
    )


def sweep(
    *,
    weights: Sequence[float],
    pool_path: Path = DEFAULT_POOL,
    dataset_path: Path = DEFAULT_DATASET,
    similarity_calculator: Any = None,
) -> list[dict[str, Any]]:
    """Score the same pool at each weight. Returns one summary row per weight."""
    pool = load_candidate_pool(pool_path)
    rows = []
    for weight in weights:
        record = score_pool_at_weight(
            pool=pool,
            dataset_path=dataset_path,
            cross_encoder_weight=weight,
            similarity_calculator=similarity_calculator,
        )
        rows.append(
            {
                "cross_encoder_weight": weight,
                "nDCG@10": record["nDCG@10"],
                "MRR@10": record["MRR@10"],
                "Recall@5": record["Recall@5"],
                "Recall@10": record["Recall@10"],
                "wrong_paper_handoff_rate": record["wrong_paper_handoff_rate"],
            }
        )
    return rows


def build_similarity_calculator() -> Any:
    """Build the production dense-signal calculator from the ambient environment.

    Imported lazily and constructed here rather than in ``sweep`` so the default
    (semantic off) run stays free of OpenAI credentials entirely. Embeddings go
    through the calculator's own SQLite cache, so only the first weight in a
    sweep pays for API calls and every later weight sees byte-identical vectors.
    """
    from dotenv import load_dotenv

    from src.collector.paper.similarity_calculator import SimilarityCalculator

    load_dotenv()
    return SimilarityCalculator()


def format_sweep(rows: Sequence[dict[str, Any]]) -> str:
    header = f"{'ce_weight':>10} {'nDCG@10':>9} {'MRR@10':>8} {'R@5':>7} {'R@10':>7} {'wrong':>7}"
    lines = [header, "-" * len(header)]
    for row in rows:
        marker = "  <- current" if row["cross_encoder_weight"] == CROSS_ENCODER_RRF_WEIGHT else ""
        lines.append(
            f"{row['cross_encoder_weight']:>10} {row['nDCG@10']:>9.4f} {row['MRR@10']:>8.4f} "
            f"{row['Recall@5']:>7.4f} {row['Recall@10']:>7.4f} "
            f"{row['wrong_paper_handoff_rate']:>7.4f}{marker}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="hit real sources once and pin the candidate pool")
    cap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    cap.add_argument("--out", type=Path, default=DEFAULT_POOL)
    cap.add_argument("--per-source", type=int, default=15)

    swp = sub.add_parser("sweep", help="score the pinned pool at several fusion weights")
    swp.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    swp.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    swp.add_argument("--weights", type=float, nargs="+", default=[0.0, 1.0, 2.0, 4.0, 8.0])
    swp.add_argument(
        "--semantic",
        action="store_true",
        help=(
            "include the dense signal, matching production. Needs OPENAI_API_KEY; "
            "embeddings are cached in data/cache/embeddings.db so repeated weights "
            "re-use them and only the first pass costs API calls."
        ),
    )

    args = parser.parse_args(argv)

    if args.command == "capture":
        pool = capture_candidate_pool(
            dataset_path=args.dataset, out_path=args.out, per_source=args.per_source
        )
        sizes = {qid: len(docs) for qid, docs in pool["candidates"].items()}
        print(json.dumps({"pool_hash": pool["pool_hash"], "candidates_per_query": sizes,
                          "capture_errors": pool["capture_errors"]}, indent=2, ensure_ascii=False))
        return 0

    similarity_calculator = build_similarity_calculator() if args.semantic else None
    print(f"semantic signal: {'on' if similarity_calculator else 'off'}")
    print(
        format_sweep(
            sweep(
                weights=args.weights,
                pool_path=args.pool,
                dataset_path=args.dataset,
                similarity_calculator=similarity_calculator,
            )
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
