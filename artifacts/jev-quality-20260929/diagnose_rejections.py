"""At most three diagnostic calls, excluded from the frozen evaluation metrics."""
import json
import os
from pathlib import Path
import httpx
from src.search_eval.jev_client import JevError, score_candidate
root=Path(__file__).parent
report=json.loads((root/"comparison.json").read_text())
frozen=json.loads((root/"frozen-en.json").read_text())
by_id={q["query_id"]:q for q in frozen["queries"]}
rows=[]
for trial in report["trials"]:
    for error in trial["jev_errors"]:
        assert len(rows)<3
        candidate=next(p for p in by_id[trial["query_id"]]["candidates"] if p["paper_key"]==error["paper_key"])
        row={"query_id":trial["query_id"],"paper_key":candidate["paper_key"],"original_error":error["error"]}
        def capture(response):
            response.read()
            row["http_status"]=response.status_code
            if response.status_code==200:
                data=response.json()
                answer=data.get("answers",{}).get("relevance",{})
                row["numeric_answer"]={k:answer.get(k) for k in ("score","confidence","probabilities")}
        with httpx.Client(event_hooks={"response":[capture]},follow_redirects=False) as client:
            try:
                score_candidate(trial["query"],candidate,api_key=os.environ["TYPESAFE_API_KEY"],client=client,timeout=20)
                row["diagnostic_status"]="accepted"
            except JevError as exc:
                row["diagnostic_status"]=str(exc)
        rows.append(row)
with (root/"rejection-diagnostics.json").open("x") as f:
    json.dump({"excluded_from_quality_metrics":True,"calls":len(rows),"rows":rows},f,indent=2,ensure_ascii=False,allow_nan=False)
print(json.dumps(rows,ensure_ascii=False))
