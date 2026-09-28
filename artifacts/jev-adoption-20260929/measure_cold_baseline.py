"""Cache-cold control for the same public fixed-pool latency pilot."""
import copy
import json
import logging
import math
import os
from pathlib import Path
import statistics
import tempfile
import time
from dotenv import load_dotenv
from openai import OpenAI
from src.graph_rag import hybrid_ranker as hr
from src.collector.paper.similarity_calculator import SimilarityCalculator
from src.search_eval.judged_replay import digest

root = Path("artifacts/jev-adoption-20260929")
out = root / "latency-cold-baseline.json"
assert not out.exists()
load_dotenv()
key = os.environ["OPENAI_API_KEY"]
fixture = json.loads(Path("data/search_eval/jev_public_smoke_v1.json").read_text())
warnings = []


class Capture(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.WARNING:
            warnings.append(record.getMessage().replace(key, "[REDACTED]"))


logging.getLogger().addHandler(Capture())
rows = []
for repeat in range(5):
    for q in fixture["queries"]:
        with tempfile.TemporaryDirectory(prefix="jev-cold-control-") as tmp:
            with hr._HYDE_CACHE_LOCK:
                hr._HYDE_CACHE.clear()
            calc = SimilarityCalculator(cache_db_path=Path(tmp) / "embeddings.db")
            calc.client.close()
            calc.client = OpenAI(api_key=key, timeout=10.0, max_retries=0)
            ranker = hr.HybridRanker(similarity_calculator=calc)
            chat = OpenAI(api_key=key, timeout=10.0, max_retries=0)
            row = {"repeat": repeat, "query_id": q["query_id"], "language": q["language"], "status": "ok"}
            start_warnings = len(warnings)
            started = time.perf_counter()
            deadline = time.monotonic() + 25
            try:
                result = ranker.rank_papers(query=q["query"], papers=copy.deepcopy(q["candidates"]), intent="paper_search", use_rrf=True, openai_client=chat, deadline=deadline)
                row["order"] = [p["paper_key"] for p in result]
                assert set(row["order"]) == {p["paper_key"] for p in q["candidates"]}
                row["excluded_signals"] = result[0].get("_score_breakdown", {}).get("excluded_signals", {})
                if "semantic" in row["excluded_signals"]:
                    row["status"] = "degraded"
                if time.monotonic() > deadline:
                    row["status"] = "deadline_exceeded"
            except Exception as exc:
                row["status"] = "error"
                row["error_type"] = type(exc).__name__
            row["elapsed_ms"] = (time.perf_counter()-started)*1000
            row["warnings"] = warnings[start_warnings:]
            if row["warnings"] and row["status"] == "ok":
                row["status"] = "degraded"
            rows.append(row)
            chat.close()
            calc.client.close()
            if calc._db_conn is not None:
                calc._db_conn.close()
            print(json.dumps(row), flush=True)
values = sorted(r["elapsed_ms"] for r in rows)
ok = [r["elapsed_ms"] for r in rows if r["status"] == "ok"]
report = {"version": "jev-cold-baseline-control-v1", "fixture_hash": digest(fixture), "arm": "standard_hybrid_cold", "cache": "HyDE and embedding caches empty before EACH trial, in this isolated benchmark process only", "configuration": {"per_call_timeout_seconds": 10, "query_deadline_seconds": 25, "retries": 0, "candidate_count": 3}, "summary": {"n": len(rows), "ok": len(ok), "non_ok": len(rows)-len(ok), "mean_ms_all_attempts": statistics.mean(values), "p50_ms_all_attempts": statistics.median(values), "p95_ms_nearest_rank_all_attempts": values[math.ceil(.95*len(values))-1], "mean_ms_success_only": statistics.mean(ok) if ok else None}, "trials": rows, "limitations": ["Measured after the interleaved JEV/standard/fast pilot, not simultaneously.", "Ten repeated trials over two simple queries cannot establish production percentiles or quality parity.", "Imports/client creation and candidate retrieval are outside the timer; actual ranking and network calls are inside."], "promotion_eligible": False}
with out.open("x") as f:
    json.dump(report, f, indent=2, ensure_ascii=False, allow_nan=False)
print(json.dumps(report["summary"]), flush=True)
