"""Recover only rejected scores after validation correction; retain first-pass report."""
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import statistics
from src.search_eval.jev_client import JevError, score_candidate
from src.search_eval.judged_replay import digest, score_identities

root=Path(__file__).parent
out=root/"comparison-validation-recovery.json"
assert not out.exists()
original=json.loads((root/"comparison.json").read_text())
report=copy.deepcopy(original)
frozen=json.loads((root/"frozen-en.json").read_text())
queries={q["query_id"]:q for q in frozen["queries"]}
recovery=[]
for row in report["trials"]:
    if not row["jev_errors"]:
        continue
    original_errors=copy.deepcopy(row["jev_errors"])
    remaining=[]
    for error in original_errors:
        assert len(recovery)<3
        candidate=next(p for p in queries[row["query_id"]]["candidates"] if p["paper_key"]==error["paper_key"])
        receipt={"query_id":row["query_id"],"language":row["language"],"paper_key":candidate["paper_key"],"original_error":error["error"]}
        try:
            result=score_candidate(row["query"],candidate,api_key=os.environ["TYPESAFE_API_KEY"],timeout=20)
            row["jev_scores"].append({"paper_key":candidate["paper_key"],"result":result})
            receipt["status"]="ok"
            receipt["result"]=result
        except JevError as exc:
            receipt["status"]="error"
            receipt["error"]=str(exc)
            remaining.append({"paper_key":candidate["paper_key"],"error":str(exc)})
        recovery.append(receipt)
    row["first_pass_errors"]=original_errors
    row["jev_errors"]=remaining
    if not remaining:
        by_key={r["paper_key"]:r for r in row["jev_scores"]}
        assert len(by_key)==10 and set(by_key)==set(row["candidate_ids"])
        # Retain the original input order for tied scores, not append order.
        ordered=sorted(row["candidate_ids"],key=lambda key:-by_key[key]["result"]["score"])
        gold=queries[row["query_id"]]["qrels"]
        values=score_identities(ordered,{k:{"grade":v,"required":v>0,"excluded":False} for k,v in gold.items()})
        row["jev_metrics"]={k:values[k] for k in ("nDCG@10","MRR@10","Recall@5","Recall@10")}
        row["jev_metrics"]["Hit@1"]=float(gold.get(ordered[0],0)>0)
        row["jev_order"]=ordered
        row["jev_status"]="ok"
        row["quality_recovered_after_validation_fix"]=True


def summary(lang):
    rows=[r for r in report["trials"] if r["language"]==lang]
    pairs=[r for r in rows if r["baseline_status"]=="ok" and r["jev_status"]=="ok"]
    average=lambda field:{k:statistics.mean(r[field][k] for r in pairs) for k in pairs[0][field]} if pairs else None
    delta=[r["jev_metrics"]["nDCG@10"]-r["baseline_metrics"]["nDCG@10"] for r in pairs]
    rng=random.Random(20260929)
    boot=sorted(statistics.mean(rng.choices(delta,k=len(delta))) for _ in range(10000)) if delta else []
    return {"queries":len(rows),"paired_complete":len(pairs),"baseline_non_ok":sum(r["baseline_status"]!="ok" for r in rows),"jev_incomplete":sum(r["jev_status"]!="ok" for r in rows),"paired_baseline":average("baseline_metrics"),"paired_jev":average("jev_metrics"),"ndcg_wins_ties_losses":[sum(d>1e-12 for d in delta),sum(abs(d)<=1e-12 for d in delta),sum(d< -1e-12 for d in delta)],"paired_ndcg_mean_delta":statistics.mean(delta) if delta else None,"paired_query_bootstrap_95_interval":[boot[249],boot[9749]] if boot else None}


report["version"]="scifact-jev-quality-validation-recovery-v1"
report["original_report_hash"]=original["report_hash"]
report["first_pass_summary"]=original["summary"]
report["summary"]={lang:summary(lang) for lang in ("en","ko")}
report["recovery_calls"]=recovery
report["recovery_call_count"]=len(recovery)
report["client_sha256"]=hashlib.sha256(Path("src/search_eval/jev_client.py").read_bytes()).hexdigest()
report["limitations"].append("Three rejected first-pass scores were re-requested after correcting hundredth-rounded wire-value validation. Original other scores are unchanged; recovered results are a mixed-time sample, not a fresh all-at-once rerun. First-pass rejection was not a network timeout.")
report["limitations"].append("Do not use retained first-pass timing as recovery-run latency. Separate three-call numeric diagnostics were excluded from all quality metrics.")
report.pop("report_hash",None)
report["report_hash"]=digest(report)
with out.open("x") as f:
    json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)
print(json.dumps(report["summary"],ensure_ascii=False))
