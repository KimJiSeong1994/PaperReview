"""Bounded real-call ranker latency pilot; does not change production settings."""
import copy
import json
import logging
import math
import os
from pathlib import Path
import re
import statistics
import tempfile
import time

from dotenv import load_dotenv
from openai import OpenAI

from src.graph_rag.hybrid_ranker import HybridRanker, CROSS_ENCODER_RRF_WEIGHT
from src.collector.paper.similarity_calculator import SimilarityCalculator
from src.search_eval.jev_client import MODEL, RUBRIC_HASH, JevError, score_candidate
from src.search_eval.judged_replay import digest, score_identities
from src.utils.model_defaults import DEFAULT_TOOL_MODEL, DEFAULT_EMBEDDING_MODEL

ROOT = Path("artifacts/jev-adoption-20260929")
OUT = ROOT / "latency-comparison.json"
assert not OUT.exists(), "Refusing to overwrite measurement"
load_dotenv()
key = os.environ["TYPESAFE_API_KEY"]
openai_key = os.environ.get("OPENAI_API_KEY")
assert openai_key, "Standard baseline needs an OpenAI credential"
fixture = json.loads(Path("data/search_eval/jev_public_smoke_v1.json").read_text())
warnings = []


class CaptureWarnings(logging.Handler):
    def emit(self, record):
        if record.levelno < logging.WARNING:
            return
        message = record.getMessage()
        for secret in (key, openai_key):
            message = message.replace(secret, "[REDACTED]")
        message = re.sub(r"apikey_[a-f0-9]+_[a-f0-9]+", "[REDACTED]", message)
        warnings.append({"level": record.levelname, "logger": record.name, "message": message})


logging.getLogger().addHandler(CaptureWarnings())
rows = []
# Deliberately preserve the current JEV per-candidate sequential calls, without
# pooled connections, retries, batching, or score caching: measure before tuning.
with tempfile.TemporaryDirectory(prefix="jev-latency-") as scratch:
    calculator = SimilarityCalculator(cache_db_path=Path(scratch) / "embeddings.db")
    original_client = calculator.client
    calculator.client = OpenAI(api_key=openai_key, timeout=10.0, max_retries=0)
    original_client.close()
    standard = HybridRanker(similarity_calculator=calculator)
    fast = HybridRanker()
    chat = OpenAI(api_key=openai_key, timeout=10.0, max_retries=0)
    try:
        for repeat in range(5):
            for query in fixture["queries"]:
                arms = ["standard_hybrid", "fast_rrf", "jev_sequential"]
                if repeat % 2:
                    arms.reverse()
                for arm in arms:
                    started = time.perf_counter()
                    deadline = time.monotonic() + 25.0
                    warning_start = len(warnings)
                    row = {"repeat": repeat, "query_id": query["query_id"], "language": query["language"], "arm": arm, "candidate_count": len(query["candidates"]), "status": "ok"}
                    try:
                        if arm == "jev_sequential":
                            scored = []
                            for candidate in query["candidates"]:
                                remaining = deadline - time.monotonic()
                                if remaining <= 0:
                                    raise TimeoutError()
                                result = score_candidate(query["query"], candidate, api_key=key, timeout=min(10.0, remaining))
                                scored.append({"paper_key": candidate["paper_key"], "result": result})
                            row["scores"] = scored
                            order = [x["paper_key"] for x in sorted(scored, key=lambda x: -x["result"]["score"])]
                        else:
                            ranker = standard if arm == "standard_hybrid" else fast
                            result = ranker.rank_papers(query=query["query"], papers=copy.deepcopy(query["candidates"]), intent="paper_search", use_rrf=True, fast_mode=arm == "fast_rrf", openai_client=chat if arm == "standard_hybrid" else None, deadline=deadline)
                            order = [p["paper_key"] for p in result]
                            row["excluded_signals"] = result[0].get("_score_breakdown", {}).get("excluded_signals", {})
                            if arm == "standard_hybrid" and "semantic" in row["excluded_signals"]:
                                row["status"] = "degraded"
                        assert len(order) == len(query["candidates"]) and set(order) == {p["paper_key"] for p in query["candidates"]}
                        row["order"] = order
                        row["fixture_metrics"] = score_identities(order, {j["paper_key"]: j for j in query["judgments"]})
                        if time.monotonic() > deadline:
                            row["status"] = "deadline_exceeded"
                    except Exception as exc:
                        row["status"] = "error"
                        row["error_type"] = type(exc).__name__
                        # Only this client exception has known sanitized text.
                        if isinstance(exc, JevError):
                            row["error"] = str(exc)
                    row["elapsed_ms"] = (time.perf_counter() - started) * 1000
                    row["warnings"] = warnings[warning_start:]
                    if row["warnings"] and row["status"] == "ok":
                        row["status"] = "degraded"
                    rows.append(row)
                    print(json.dumps({k: row[k] for k in ("repeat", "query_id", "arm", "status", "elapsed_ms")}), flush=True)
    finally:
        chat.close()
        calculator.client.close()
        if calculator._db_conn is not None:
            calculator._db_conn.close()


def summarize(selected):
    values = sorted(r["elapsed_ms"] for r in selected)
    successful = [r["elapsed_ms"] for r in selected if r["status"] == "ok"]
    return {"n": len(values), "ok": len(successful), "non_ok": len(values)-len(successful), "mean_ms_all_attempts": statistics.mean(values), "p50_ms_all_attempts": statistics.median(values), "p95_ms_nearest_rank_all_attempts": values[math.ceil(.95*len(values))-1], "mean_ms_success_only": statistics.mean(successful) if successful else None}


report = {
    "version": "jev-latency-pilot-v1", "fixture_hash": digest(fixture),
    "models": {"jev": MODEL, "rubric_hash": RUBRIC_HASH, "standard_chat": DEFAULT_TOOL_MODEL, "standard_embedding": DEFAULT_EMBEDDING_MODEL},
    "configuration": {"repeats_per_language": 5, "candidate_count": 3, "cross_encoder_weight": CROSS_ENCODER_RRF_WEIGHT, "per_call_timeout_seconds": 10, "query_deadline_seconds": 25, "retries": 0, "standard_hyde": True, "standard_embedding_cache": "isolated empty cache at process start, then reused", "jev_cache": "none", "jev_parallelism": 1},
    "scope": "Local ranker-only timing including network/model calls; excludes provider retrieval, query analysis, app startup and browser rendering",
    "limitations": ["Only two simple synthetic-labeled queries and ten trials per arm; nearest-rank p95 is the maximum of ten and is not a reliable production percentile.", "Standard baseline uses real current HybridRanker with HyDE and embeddings but isolated cache and bounded HTTP retries/timeouts, not a measurement of the deployed server.", "Repeats after the first may use warm embeddings; do not interpret these as independent cold-cache runs.", "Timeouts and degraded fallback paths are recorded separately, not counted as successful standard ranking.", "Fixture relevance scores do not establish quality parity or justify production rollout."],
    "summary": {arm: summarize([r for r in rows if r["arm"]==arm]) for arm in ("standard_hybrid", "fast_rrf", "jev_sequential")},
    "by_language": {arm: {lang: summarize([r for r in rows if r["arm"]==arm and r["language"]==lang]) for lang in ("en", "ko")} for arm in ("standard_hybrid", "fast_rrf", "jev_sequential")},
    "trials": rows,
    "jev_successful_response_input_tokens": sum(x["result"]["usage"]["input_tokens"] for r in rows for x in r.get("scores", [])),
    "promotion_eligible": False,
}
with OUT.open("x") as f:
    json.dump(report, f, indent=2, ensure_ascii=False, allow_nan=False)
print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
