"""Compare frozen published qrels, never JEV-authored labels; no production edits."""
import copy
import json
import logging
import os
from pathlib import Path
import random
import statistics
import tempfile
import time
from dotenv import load_dotenv
from openai import OpenAI
from src.graph_rag.hybrid_ranker import HybridRanker
from src.collector.paper.similarity_calculator import SimilarityCalculator
from src.search_eval.jev_client import MODEL, RUBRIC_HASH, JevError, score_candidate
from src.search_eval.judged_replay import digest, score_identities

ROOT = Path(__file__).parent
OUT = ROOT / "comparison.json"
assert not OUT.exists(), "Refusing to overwrite experiment"
frozen = json.loads((ROOT / "frozen-en.json").read_text())
assert frozen["input_hash"] == digest({k:v for k,v in frozen.items() if k!="input_hash"})
translations = json.loads((ROOT / "korean-translations.json").read_text())
assert set(translations["translations"]) == {q["query_id"] for q in frozen["queries"]}
load_dotenv()
key = os.environ["TYPESAFE_API_KEY"]
ai_key = os.environ["OPENAI_API_KEY"]
warnings = []


class Capture(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.WARNING:
            message = record.getMessage().replace(key,"[REDACTED]").replace(ai_key,"[REDACTED]")
            warnings.append(message)


logging.getLogger().addHandler(Capture())
METRICS = ("nDCG@10", "MRR@10", "Recall@5", "Recall@10", "Hit@1")


def metrics(order, gold):
    judgments = {k:{"grade":v,"required":v>0,"excluded":False} for k,v in gold.items()}
    result = score_identities(order, judgments)
    return {**{k:result[k] for k in METRICS if k!="Hit@1"}, "Hit@1":float(bool(order) and gold.get(order[0],0)>0)}


rows=[]
run_deadline=time.monotonic()+900
calls=0
with tempfile.TemporaryDirectory(prefix="jev-quality-") as tmp:
    calculator=SimilarityCalculator(cache_db_path=Path(tmp)/"embeddings.db")
    calculator.client.close()
    calculator.client=OpenAI(api_key=ai_key,timeout=10,max_retries=0)
    chat=OpenAI(api_key=ai_key,timeout=10,max_retries=0)
    baseline=HybridRanker(similarity_calculator=calculator)
    try:
        for q in frozen["queries"]:
            for language in ("en","ko"):
                query=q["query"] if language=="en" else translations["translations"][q["query_id"]]
                row={"query_id":q["query_id"],"language":language,"query":query,"gold_in_pool":q["gold_in_pool"],"candidate_ids":[p["paper_key"] for p in q["candidates"]],"baseline_status":"not_run","jev_status":"not_run","jev_scores":[],"jev_errors":[]}
                row["bm25_metrics"]=metrics(row["candidate_ids"],q["qrels"])
                start=time.perf_counter()
                warn_start=len(warnings)
                try:
                    assert time.monotonic()<run_deadline
                    ranked=baseline.rank_papers(query=query,papers=copy.deepcopy(q["candidates"]),intent="paper_search",use_rrf=True,openai_client=chat,deadline=time.monotonic()+25)
                    order=[p["paper_key"] for p in ranked]
                    assert len(order)==10 and set(order)==set(row["candidate_ids"])
                    row["baseline_order"]=order
                    row["baseline_metrics"]=metrics(order,q["qrels"])
                    row["baseline_excluded_signals"]=ranked[0].get("_score_breakdown",{}).get("excluded_signals",{})
                    row["baseline_status"]="degraded" if "semantic" in row["baseline_excluded_signals"] or warnings[warn_start:] else "ok"
                except Exception as exc:
                    row["baseline_status"]="error"
                    row["baseline_error_type"]=type(exc).__name__
                row["baseline_elapsed_ms"]=(time.perf_counter()-start)*1000
                row["baseline_warnings"]=warnings[warn_start:]
                start=time.perf_counter()
                for candidate in q["candidates"]:
                    if time.monotonic()>=run_deadline or calls>=160:
                        row["jev_errors"].append({"paper_key":candidate["paper_key"],"error":"run_budget_exhausted"})
                        continue
                    calls+=1
                    try:
                        score=score_candidate(query,candidate,api_key=key,timeout=min(20.0,run_deadline-time.monotonic()))
                        row["jev_scores"].append({"paper_key":candidate["paper_key"],"result":score})
                    except JevError as exc:
                        row["jev_errors"].append({"paper_key":candidate["paper_key"],"error":str(exc)})
                row["jev_elapsed_ms"]=(time.perf_counter()-start)*1000
                if not row["jev_errors"]:
                    order=[s["paper_key"] for s in sorted(row["jev_scores"],key=lambda s:-s["result"]["score"])]
                    assert len(order)==10 and set(order)==set(row["candidate_ids"])
                    row["jev_order"]=order
                    row["jev_metrics"]=metrics(order,q["qrels"])
                    row["jev_status"]="ok"
                else:
                    row["jev_status"]="incomplete"
                rows.append(row)
                with (ROOT/"trial-receipts.jsonl").open("a") as log:
                    log.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+"\n")
                print(json.dumps({k:row[k] for k in ("query_id","language","baseline_status","jev_status")}),flush=True)
    finally:
        calculator.client.close()
        chat.close()
        if calculator._db_conn is not None:
            calculator._db_conn.close()


def average(items,field):
    return {m:statistics.mean(r[field][m] for r in items) for m in METRICS} if items else None


def summary(language):
    selected=[r for r in rows if r["language"]==language]
    paired=[r for r in selected if r["baseline_status"]=="ok" and r["jev_status"]=="ok"]
    delta=[r["jev_metrics"]["nDCG@10"]-r["baseline_metrics"]["nDCG@10"] for r in paired]
    interval=None
    if delta:
        rng=random.Random(20260929)
        boot=sorted(statistics.mean(rng.choices(delta,k=len(delta))) for _ in range(10000))
        interval=[boot[249],boot[9749]]
    return {"queries":len(selected),"paired_complete":len(paired),"baseline_non_ok":sum(r["baseline_status"]!="ok" for r in selected),"jev_incomplete":sum(r["jev_status"]!="ok" for r in selected),"paired_baseline":average(paired,"baseline_metrics"),"paired_jev":average(paired,"jev_metrics"),"bm25_all":average(selected,"bm25_metrics"),"ndcg_wins_ties_losses":[sum(d>1e-12 for d in delta),sum(abs(d)<=1e-12 for d in delta),sum(d< -1e-12 for d in delta)],"paired_ndcg_mean_delta":statistics.mean(delta) if delta else None,"paired_query_bootstrap_95_interval":interval}


report={"version":"scifact-jev-quality-pilot-v1","input_hash":frozen["input_hash"],"translation_hash":digest(translations),"model":MODEL,"rubric_hash":RUBRIC_HASH,"attempted_jev_calls":calls,"summary":{lang:summary(lang) for lang in ("en","ko")},"trials":rows,"label_source":frozen["label_provenance"],"limitations":["English results use published BEIR SciFact qrels; this is scientific-claim evidence retrieval, not general search relevance.","Korean is an unreviewed AI translation probe sharing English gold; not independent human Korean judgment.","Unlisted candidate identities get zero benchmark gain but are not certified nonrelevant; qrels may be incomplete.","Candidate pool is frozen English BM25 top10 from5183 abstracts, without gold injection. Missing gold cannot be recovered by reranking.","Only8 independent query pairs; paired bootstrap intervals are exploratory, not deployment qualification. Languages are not independent samples.","Incomplete JEV rows are excluded only from paired quality means and counted separately; failure selection can bias complete-case estimates.","Unchanged current Score rubric, no model/rubric tuning after observing outcomes; no ranking labels sent to either model.","HyDE and embedding baseline uses isolated cache and max_retries0, not a deployed-server measurement."],"promotion_eligible":False}
report["report_hash"]=digest(report)
with OUT.open("x") as f:
    json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)
print(json.dumps(report["summary"],ensure_ascii=False),flush=True)
