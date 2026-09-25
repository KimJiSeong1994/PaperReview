"""Sealed, identity-judged evaluation. Replay never falls back to the network.

JSON hashes are sha256 of sorted compact UTF-8 JSON excluding only the artifact's
own hash field. A checked-in synthetic bundle can supply both --capture and
--judgments. Captures in an existing --out-dir are merged, never overwritten on
conflicting effective requests. Run this harness separately in each source tree.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import copy
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from urllib.parse import parse_qsl, urlsplit
from unittest.mock import patch

BASELINE_REVISION = "99c77237d8a8d2adb6e6e73419cc79213aa1357d"
SOURCES = ["arxiv", "google_scholar", "openalex", "dblp", "connected_papers", "openalex_korean"]
REQUEST_FIELDS = {"provider", "operation", "effective_query", "filters", "sort", "limit", "cursor", "api_version"}
METRICS = ("nDCG@10", "MRR@10", "Recall@5", "Recall@10", "wrong_paper_handoff_rate")


class InvalidArtifact(ValueError):
    pass


class ReplayMiss(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def seal(value, field):
    result = copy.deepcopy(value)
    result.pop(field, None)
    result[field] = digest(result)
    return result


def require(condition, message):
    if not condition:
        raise InvalidArtifact(message)


def keys(value, expected, name):
    require(isinstance(value, dict) and set(value) == set(expected), f"{name}: keys must be {sorted(expected)}")


def hashed(value, kind, field):
    require(isinstance(value, dict), f"{kind}: object required")
    require(value.get("version") == f"search-review-{kind}-v1", f"invalid {kind} version")
    require(value.get(field) == seal(value, field)[field], f"{field} mismatch")


def text(value, name):
    require(isinstance(value, str) and bool(value.strip()), f"{name}: nonempty string required")


def read_json(path, member=None):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result
    value = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs,
                       parse_constant=lambda token: (_ for _ in ()).throw(InvalidArtifact(f"nonfinite JSON: {token}")))
    if member and value.get("version") == "search-review-synthetic-v1":
        hashed(value, "synthetic", "fixture_hash")
        return value[member]
    return value


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def validate_matrix(matrix):
    hashed(matrix, "matrix", "matrix_hash")
    keys(matrix, {"version", "matrix_hash", "queries"}, "matrix")
    require(isinstance(matrix["queries"], list) and len(matrix["queries"]) == 24, "matrix requires exactly 24 queries")
    expected = {f"c{i:02}-{lang}" for i in range(1, 13) for lang in ("en", "ko")}
    require({q.get("query_id") for q in matrix["queries"]} == expected, "invalid matrix query IDs")
    intents = ["exact", "exact", "title", "topic", "survey", "comparison", "author", "topic", "topic", "author", "topic", "negative"]
    filters = ["none"] * 6 + ["author", "year", "category", "combined", "none", "none"]
    for q in matrix["queries"]:
        keys(q, {"query_id", "pair_id", "split", "query", "request", "slices", "required_candidates"}, "query")
        pair, lang = q["query_id"].split("-")
        index = int(pair[1:]) - 1
        require(q["pair_id"] == pair, "pair ID mismatch")
        require(q["split"] == ("development" if pair in {"c01", "c04", "c07", "c11"} else "holdout"), "split is frozen")
        require(q["slices"] == {"language": lang, "intent": intents[index], "filter": filters[index]}, "slice membership is frozen")
        text(q["query"], "query")
        r = q["request"]
        keys(r, {"sources", "max_results", "sort_by", "filters", "use_llm_search", "fast_mode"}, "request")
        require(sorted(r["sources"]) == sorted(SOURCES) and r["max_results"] == 50 and type(r["max_results"]) is int, "normal request must use six sources and max_results=50")
        require(r["use_llm_search"] is False and r["fast_mode"] is False, "matrix pins standard normal request")
        require(r["sort_by"] in {"relevance", "submittedDate", "lastUpdatedDate"}, "invalid sort")
        require(isinstance(r["filters"], dict) and set(r["filters"]) <= {"year_start", "year_end", "author", "category"}, "invalid filters")
        required_filter_keys = {"none": set(), "author": {"author"}, "year": {"year_start", "year_end"}, "category": {"category"}, "combined": {"year_start", "year_end", "author"}}
        require(set(r["filters"]) == required_filter_keys[filters[index]], "filters do not match frozen slice")
        for field, value in r["filters"].items():
            if field.startswith("year_"):
                require(type(value) is int and 1000 <= value <= 9999, "invalid year filter")
            else:
                text(value, field)
        if "year_start" in r["filters"]:
            require(r["filters"]["year_start"] <= r["filters"]["year_end"], "reversed year range")
        require(isinstance(q["required_candidates"], list), "required_candidates must be list")
        identities = set()
        for proposed in q["required_candidates"]:
            keys(proposed, {"paper_key", "evidence_refs"}, "required candidate")
            text(proposed["paper_key"], "paper_key")
            require(proposed["paper_key"] not in identities, "duplicate required candidate")
            identities.add(proposed["paper_key"])
            require(isinstance(proposed["evidence_refs"], list) and proposed["evidence_refs"], "candidate evidence required")
    for i in range(1, 13):
        pair = [q for q in matrix["queries"] if q["pair_id"] == f"c{i:02}"]
        require(pair[0]["request"] == pair[1]["request"] and pair[0]["required_candidates"] == pair[1]["required_candidates"], "paired entities/filters must agree")


def validate_manifest(value):
    keys(value, {"revision", "tree", "config", "configuration"}, "manifest")
    require(isinstance(value["revision"], str) and len(value["revision"]) == 40 and all(c in "0123456789abcdef" for c in value["revision"]), "invalid revision")
    require(isinstance(value["tree"], str) and value["tree"].startswith("sha256:") and len(value["tree"]) == 71, "invalid tree digest")
    require(value["config"] == digest(value["configuration"]), "configuration digest mismatch")
    config = value["configuration"]
    keys(config, {"dependencies", "python", "clean_source", "policy_and_model_defaults_tree", "harness_digest", "identity_helper_digest", "model_environment", "scoring_year"}, "configuration")
    require(isinstance(config["dependencies"], list) and bool(config["dependencies"]), "dependency manifest required")
    require(all(isinstance(d, (list, tuple)) and len(d) == 2 and all(isinstance(v, str) and v for v in d) for d in config["dependencies"]), "invalid dependency manifest")
    text(config["python"], "python version")
    require(type(config["clean_source"]) is bool and type(config["scoring_year"]) is int, "invalid environment configuration")
    require(config["policy_and_model_defaults_tree"] == value["tree"], "policy/model source binding mismatch")
    require(isinstance(config["model_environment"], dict), "model environment must be an object")
    for field in ("harness_digest", "identity_helper_digest"):
        require(isinstance(config[field], str) and config[field].startswith("sha256:") and len(config[field]) == 71, f"invalid {field}")


def validate_capture(matrix, capture):
    hashed(capture, "capture", "capture_hash")
    keys(capture, {"version", "capture_hash", "matrix_hash", "baseline", "candidate", "evidence_kind", "entries", "boundaries", "pools", "browser_evidence"}, "capture")
    require(capture["matrix_hash"] == matrix["matrix_hash"], "capture matrix binding mismatch")
    require(capture["evidence_kind"] in {"synthetic", "recorded_provider"}, "invalid capture evidence")
    for mode in ("baseline", "candidate"):
        if capture[mode] is not None:
            validate_manifest(capture[mode])
    require(isinstance(capture["browser_evidence"], list), "browser evidence must be a list")
    for trace in capture["browser_evidence"]:
        keys(trace, {"trace_ref", "reviewer_id", "cards_before_optional_enrichment"}, "browser evidence")
        text(trace["trace_ref"], "browser trace reference")
        text(trace["reviewer_id"], "browser reviewer")
        require(type(trace["cards_before_optional_enrichment"]) is bool, "browser observation must be boolean")
    for collection in ("entries", "boundaries"):
        require(isinstance(capture[collection], list), "capture entries must be lists")
        seen = set()
        for e in capture[collection]:
            keys(e, {"request_key", "request", "response", "status", "origin"}, "capture entry")
            if collection == "entries":
                keys(e["request"], REQUEST_FIELDS, "effective request")
                text(e["request"]["provider"], "provider")
                text(e["request"]["operation"], "operation")
                text(e["request"]["api_version"], "api_version")
                require(isinstance(e["request"]["filters"], dict), "effective filters must be an object")
                require(e["request"]["effective_query"] is None or isinstance(e["request"]["effective_query"], str), "invalid effective query")
            else:
                keys(e["request"], {"boundary", "input", "config"}, "model boundary")
                text(e["request"]["boundary"], "model boundary")
                require(isinstance(e["request"]["input"], dict), "model input must be an object")
                require(e["request"]["config"] in {m["config"] for m in (capture["baseline"], capture["candidate"]) if m is not None}, "model config is not bound to a captured implementation")
            require(e["request_key"] == digest(e["request"]), "request key mismatch")
            require(e["request_key"] not in seen, "duplicate/conflicting frozen request")
            seen.add(e["request_key"])
            require(e["status"] in {"ok", "error", "timeout"}, "invalid response status")
            require(isinstance(e["origin"], dict) and bool(e["origin"]), "origin required")
            if capture["evidence_kind"] == "synthetic":
                require(e["origin"].get("kind") == "synthetic", "synthetic receipt mislabeled")
            else:
                require(e["origin"].get("kind") == "provider_receipt" and e["origin"].get("captured_at"), "provider receipt required")
    require(isinstance(capture["pools"], dict) and set(capture["pools"]) <= {q["query_id"] for q in matrix["queries"]}, "invalid capture pools")
    for pool in capture["pools"].values():
        require(isinstance(pool, list) and len(pool) == len(set(pool)) and all(isinstance(k, str) and k for k in pool), "invalid pool identities")


def validate_judgments(matrix, capture, judgments):
    hashed(judgments, "judgments", "judgment_hash")
    keys(judgments, {"version", "judgment_hash", "matrix_hash", "capture_hash", "evidence_kind", "frozen_at", "rows"}, "judgments")
    require(judgments["matrix_hash"] == matrix["matrix_hash"] and judgments["capture_hash"] == capture["capture_hash"], "judgment binding mismatch")
    require(judgments["evidence_kind"] in {"synthetic", "human_reviewed"}, "invalid judgment evidence")
    timestamp(judgments["frozen_at"])
    require(isinstance(judgments["rows"], list), "judgments rows must be list")
    seen = set()
    qids = {q["query_id"] for q in matrix["queries"]}
    for row in judgments["rows"]:
        keys(row, {"query_id", "paper_key", "grade", "required", "excluded", "evidence_refs", "author_id", "reviewer_id", "review_status"}, "judgment")
        require(row["query_id"] in qids, "unknown judgment query")
        text(row["paper_key"], "paper_key")
        key = (row["query_id"], row["paper_key"])
        require(key not in seen, "duplicate/conflicting query-identity judgment")
        seen.add(key)
        require(type(row["grade"]) is int and 0 <= row["grade"] <= 3, "grade must be integer 0..3")
        require(type(row["required"]) is bool and type(row["excluded"]) is bool, "judgment flags must be booleans")
        require(not (row["required"] and row["excluded"]), "excluded identity cannot be required")
        require(not row["required"] or row["grade"] > 0, "required identity must be positive")
        require(isinstance(row["evidence_refs"], list) and all(isinstance(ref, str) and ref for ref in row["evidence_refs"]), "invalid evidence refs")
        require(row["review_status"] in {"synthetic", "unreviewed", "reviewed"}, "invalid review status")
        for name in ("author_id", "reviewer_id"):
            require(row[name] is None or isinstance(row[name], str), "invalid reviewer ID")
    for qid in qids:
        require(sum(q == qid for q, _ in seen) <= 80, "more than 80 judged identities per query")


def timestamp(value):
    text(value, "timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "timestamp requires timezone")
        return parsed
    except ValueError as exc:
        raise InvalidArtifact("invalid timestamp") from exc


def score_identities(ranked, judgments):
    """Duplicate positions consume rank but never earn another unit of credit."""
    seen, gains = set(), []
    for key in ranked[:10]:
        row = judgments.get(key)
        gains.append(0 if key in seen or row is None or row["excluded"] else row["grade"])
        seen.add(key)
    ideal = sorted((0 if r["excluded"] else r["grade"] for r in judgments.values()), reverse=True)[:10]
    dcg = lambda values: sum((2 ** grade - 1) / math.log2(i + 2) for i, grade in enumerate(values))
    required = {key for key, row in judgments.items() if row["required"]}
    first = next((i + 1 for i, grade in enumerate(gains) if grade), None)
    return {"nDCG@10": dcg(gains) / dcg(ideal) if dcg(ideal) else 0.0,
            "MRR@10": 1 / first if first else 0.0,
            "Recall@5": len(required & set(ranked[:5])) / len(required) if required else 1.0,
            "Recall@10": len(required & set(ranked[:10])) / len(required) if required else 1.0,
            "wrong_paper_handoff_rate": float(any(judgments.get(k, {}).get("excluded", False) for k in ranked[:10]))}


def validate_run(matrix, capture, run, mode):
    hashed(run, "run", "run_hash")
    keys(run, {"version", "run_hash", "matrix_hash", "capture_hash", "manifest", "mode", "evidence_kind", "per_query", "timing_scope", "started_at"}, "run")
    require(run["matrix_hash"] == matrix["matrix_hash"] and run["capture_hash"] == capture["capture_hash"], "run binding mismatch")
    require(run["mode"] == mode, "baseline must be standard; candidate must be fast")
    require(run["evidence_kind"] == capture["evidence_kind"], "run evidence mismatch")
    validate_manifest(run["manifest"])
    pinned = capture["baseline" if mode == "standard" else "candidate"]
    require(pinned is None or pinned == run["manifest"], "run does not match pinned revision/tree/config")
    require(run["timing_scope"] in {"replay", "ranker_only"}, "invalid timing scope")
    timestamp(run["started_at"])
    require(isinstance(run["per_query"], list) and len(run["per_query"]) == 24 and {q["query_id"] for q in run["per_query"]} == {q["query_id"] for q in matrix["queries"]}, "run must explicitly cover every query")
    known = {e["request_key"] for e in capture["entries"] + capture["boundaries"]}
    for q in run["per_query"]:
        keys(q, {"query_id", "ranked", "records", "request_keys", "replay_misses", "source_outcomes", "call_counts", "elapsed_ms"}, "run query")
        require(isinstance(q["ranked"], list) and all(isinstance(k, str) and k for k in q["ranked"]), "ranked identities invalid")
        require(isinstance(q["records"], list) and len(q["records"]) == len(q["ranked"]), "ranked records mismatch")
        require(all(isinstance(r, dict) and r.get("result_key") == k for k, r in zip(q["ranked"], q["records"])), "record identity mismatch")
        require(isinstance(q["request_keys"], list) and isinstance(q["replay_misses"], list), "invalid request ledger")
        require(all(isinstance(k, str) and k for k in q["request_keys"] + q["replay_misses"]), "invalid request identity")
        require(set(q["request_keys"]) <= known | set(q["replay_misses"]), "unsupported request not declared as miss")
        require(isinstance(q["call_counts"], dict) and all(type(v) is int and v > 0 for v in q["call_counts"].values()) and q["call_counts"] == dict(Counter(q["request_keys"])), "call counts mismatch")
        require(isinstance(q["source_outcomes"], dict), "source outcomes must be an object")
        require(type(q["elapsed_ms"]) in {int, float} and math.isfinite(q["elapsed_ms"]) and q["elapsed_ms"] >= 0, "invalid timing")


def compare(matrix, capture, judgments, baseline, candidate, scope):
    validate_matrix(matrix)
    validate_capture(matrix, capture)
    validate_judgments(matrix, capture, judgments)
    validate_run(matrix, capture, baseline, "standard")
    validate_run(matrix, capture, candidate, "fast")
    require(scope in {"routed_replay", "fixed_pool"}, "invalid scope")
    reasons, regressions, rows = [], [], []
    if scope == "fixed_pool":
        reasons.append("fixed_pool_is_not_retrieval_evidence")
    if capture["evidence_kind"] != "recorded_provider":
        reasons.append("synthetic_capture")
    if judgments["evidence_kind"] != "human_reviewed":
        reasons.append("no_independent_human_review")
    reviewed = all(r["review_status"] == "reviewed" and r["author_id"] and r["reviewer_id"] and r["author_id"] != r["reviewer_id"] and r["evidence_refs"] for r in judgments["rows"])
    if not reviewed or not judgments["rows"]:
        reasons.append("missing_independent_review_provenance")
    for name, run in (("baseline", baseline), ("candidate", candidate)):
        if capture[name] is None:
            reasons.append(f"missing_{name}_manifest")
        if run["timing_scope"] != "replay":
            reasons.append(f"{name}_not_routed_replay")
        if timestamp(judgments["frozen_at"]) > timestamp(run["started_at"]):
            reasons.append("judgments_not_frozen_before_scoring")
    if baseline["manifest"]["revision"] != BASELINE_REVISION:
        reasons.append("baseline_revision_not_pinned_preimplementation_head")
    if not baseline["manifest"]["configuration"].get("clean_source"):
        reasons.append("baseline_source_not_clean")
    if not capture["browser_evidence"] or not all(t["cards_before_optional_enrichment"] for t in capture["browser_evidence"]):
        reasons.append("missing_browser_optional_enrichment_evidence")
    for field in ("harness_digest", "identity_helper_digest"):
        bconfig, cconfig = baseline["manifest"]["configuration"], candidate["manifest"]["configuration"]
        if not bconfig.get(field) or bconfig.get(field) != cconfig.get(field):
            reasons.append(f"mismatched_or_missing_{field}")
    bmap = {q["query_id"]: q for q in baseline["per_query"]}
    cmap = {q["query_id"]: q for q in candidate["per_query"]}
    for q in matrix["queries"]:
        qid = q["query_id"]
        judged = {r["paper_key"]: r for r in judgments["rows"] if r["query_id"] == qid}
        b, c = bmap[qid], cmap[qid]
        top = set(b["ranked"][:10]) | set(c["ranked"][:10])
        required = {k for k, r in judged.items() if r["required"]}
        proposed = {r["paper_key"] for r in q["required_candidates"]}
        missing = sorted(top - set(judged))
        missing_required = sorted(proposed - required)
        pool = set(capture["pools"].get(qid, [])) | proposed | required | set(b["ranked"]) | set(c["ranked"])
        if missing:
            reasons.append(f"{qid}:unjudged_top10")
        if missing_required or (q["slices"]["intent"] != "negative" and not required):
            reasons.append(f"{qid}:missing_declared_positives")
        if len(pool) > 80:
            reasons.append(f"{qid}:candidate_bound_exceeded")
        if qid not in capture["pools"]:
            reasons.append(f"{qid}:missing_candidate_pool")
        if not (set(b["ranked"]) | set(c["ranked"])) <= set(capture["pools"].get(qid, [])):
            reasons.append(f"{qid}:ranked_identity_outside_frozen_pool")
        provider_keys = {e["request_key"] for e in capture["entries"]}
        for name, output in (("baseline", b), ("candidate", c)):
            if output["ranked"] and not provider_keys.intersection(output["request_keys"]):
                reasons.append(f"{qid}:{name}_missing_provider_attempts")
        unsupported = b["replay_misses"] + c["replay_misses"]
        if unsupported:
            reasons.append(f"{qid}:unsupported_requests")
        losses = sorted((required & set(b["ranked"][:10])) - set(c["ranked"][:10]))
        bm, cm = score_identities(b["ranked"], judged), score_identities(c["ranked"], judged)
        if losses or cm["wrong_paper_handoff_rate"] > bm["wrong_paper_handoff_rate"]:
            regressions.append(f"{qid}:required_loss_or_exclusion")
        rows.append({"query_id": qid, "baseline": bm, "candidate": cm, "coverage": {"unjudged_top10": missing, "missing_required": missing_required, "pool_size": len(pool)}, "required_hit_losses": losses, "exclusions": {"baseline": sorted(k for k in set(b["ranked"][:10]) if judged.get(k, {}).get("excluded")), "candidate": sorted(k for k in set(c["ranked"][:10]) if judged.get(k, {}).get("excluded"))}, "unsupported_requests": unsupported})
    groups = {"all": {q["query_id"] for q in matrix["queries"]}, "holdout": {q["query_id"] for q in matrix["queries"] if q["split"] == "holdout"}}
    for split in ("all", "holdout"):
        for dimension in ("language", "intent", "filter"):
            for label in sorted({q["slices"][dimension] for q in matrix["queries"]}):
                members = {q["query_id"] for q in matrix["queries"] if q["slices"][dimension] == label} & groups[split]
                if members:
                    groups[f"{split}/{dimension}={label}"] = members
    aggregates = {}
    for group, members in groups.items():
        selected = [r for r in rows if r["query_id"] in members]
        metrics = {side: {metric: sum(r[side][metric] for r in selected) / len(selected) for metric in METRICS} for side in ("baseline", "candidate")}
        aggregates[group] = metrics
        for metric in METRICS:
            b, c = metrics["baseline"][metric], metrics["candidate"][metric]
            if (c > b if metric == "wrong_paper_handoff_rate" else c < b):
                regressions.append(f"{group}:{metric}")
    decision = "inconclusive" if reasons else "fail" if regressions else "pass"
    return seal({"version": "search-review-comparison-v1", "input_hashes": {"matrix": matrix["matrix_hash"], "capture": capture["capture_hash"], "judgments": judgments["judgment_hash"], "baseline": baseline["run_hash"], "candidate": candidate["run_hash"]}, "comparison_scope": scope, "per_query": rows, "aggregate": {k: aggregates[k] for k in ("all", "holdout")}, "slices": {k: v for k, v in aggregates.items() if "/" in k}, "qualification_reasons": sorted(set(reasons)), "regressions": regressions, "promotion_decision": decision, "evidence_suppliers": sorted({r["author_id"] for r in judgments["rows"] if r["author_id"]}), "evidence_reviewers": sorted({r["reviewer_id"] for r in judgments["rows"] if r["reviewer_id"]}), "limitations": ["Provenance format is not authentication of human participation.", "Recall concerns declared positives, not live-corpus completeness.", "Replay timing is not live latency or browser paint."]}, "report_hash")


def current_manifest():
    def git(*args):
        return subprocess.check_output(["git", *args]).decode().strip()
    files = sorted(set(git("ls-files", "--cached", "--others", "--exclude-standard", "app", "routers", "src", "requirements.txt", "api_server.py").splitlines()))
    # Evaluation-only instrumentation is shared, not part of either production revision.
    files = [p for p in files if not p.startswith("src/search_eval/")]
    tree = digest({p: hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None for p in files})
    helper = Path(os.environ.get("SEARCH_EVAL_IDENTITY_HELPER", "src/utils/paper_utils.py")).resolve()
    configuration = {"dependencies": sorted([d.metadata["Name"], d.version] for d in importlib.metadata.distributions() if d.metadata["Name"]), "python": sys.version, "clean_source": not bool(git("status", "--porcelain", "--", *files)), "policy_and_model_defaults_tree": tree,
                     "harness_digest": "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                     "identity_helper_digest": "sha256:" + hashlib.sha256(helper.read_bytes()).hexdigest(),
                     "model_environment": {k: v for k, v in os.environ.items() if k in {"OPENAI_MODEL", "OPENAI_EMBEDDING_MODEL", "EMBEDDING_MODEL", "TOOL_MODEL"}},
                     "scoring_year": datetime.now().year}
    return {"revision": git("rev-parse", "HEAD"), "tree": tree, "config": digest(configuration), "configuration": configuration}


def evaluation_identity():
    """External candidate helper is evaluation-only, never installed in baseline."""
    helper = Path(os.environ.get("SEARCH_EVAL_IDENTITY_HELPER", "src/utils/paper_utils.py")).resolve()
    spec = importlib.util.spec_from_file_location("_search_eval_identity", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(callable(getattr(module, "generate_result_key", None)), "baseline requires SEARCH_EVAL_IDENTITY_HELPER pointing at candidate paper_utils.py")
    return module.generate_result_key


def json_value(value):
    if hasattr(value, "tolist"):
        return json_value(value.tolist())
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    return value


class FrozenTransport:
    """Thread-safe exact-key ledger shared by HTTP and analysis/model boundaries."""
    def __init__(self, capture, recording=False):
        self.capture = capture
        self.recording = recording
        self.lock = threading.RLock()
        self.ledger = []
        self.misses = []
        self.conflicts = []
        self.candidates = set()
        self.index = {e["request_key"]: e for e in capture["entries"] + capture["boundaries"]}

    def call(self, request, invoke=None, boundary=False):
        key = digest(request)
        with self.lock:
            self.ledger.append(key)
            entry = self.index.get(key)
            if not self.recording:
                if entry is None:
                    self.misses.append(key)
                    raise ReplayMiss(f"replay_miss:{key}")
                if entry["status"] != "ok":
                    raise ReplayMiss(f"recorded_{entry['status']}:{key}")
                return copy.deepcopy(entry["response"])
        try:
            response = invoke()
            canonical(response)
            status = "ok"
        except Exception as exc:
            response = {"error_type": type(exc).__name__, "message": "Recorded boundary failure"}
            status = "timeout" if isinstance(exc, TimeoutError) else "error"
        origin_kind = "synthetic" if self.capture["evidence_kind"] == "synthetic" else "provider_receipt"
        result = {"request_key": key, "request": request, "response": response, "status": status, "origin": {"kind": origin_kind, "captured_at": datetime.now(timezone.utc).isoformat(), "boundary": "model" if boundary else "http"}}
        with self.lock:
            entry = self.index.get(key)
            if entry is not None and (entry["response"] != response or entry["status"] != status):
                self.conflicts.append(key)
                raise InvalidArtifact(f"conflicting response for {key}; choose and document one frozen snapshot")
            if entry is None:
                self.index[key] = result
                self.capture["boundaries" if boundary else "entries"].append(result)
        if status != "ok":
            raise ReplayMiss(f"recorded_{status}:{key}")
        return copy.deepcopy(response)


def effective_http(method, url, body=b""):
    parsed = urlsplit(str(url))
    params = parse_qsl(parsed.query, keep_blank_values=True)
    secret = {"api_key", "apikey", "key", "token", "access_token", "email", "mailto"}
    params = [(k, v) for k, v in params if k.lower() not in secret]
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    # Body is retained exactly: OpenAI input/config must not alias different calls.
    if body:
        try:
            obj = json.loads(body)
            require(not any(k.lower() in secret for k in obj) if isinstance(obj, dict) else True, "secret-bearing HTTP body cannot be captured")
        except json.JSONDecodeError:
            require(not any(k.lower() in secret for k, _ in parse_qsl(body)), "secret-bearing HTTP form cannot be captured")
    get = lambda names: next((v for k, v in params if k in names), None)
    return {"provider": parsed.hostname, "operation": f"{method.upper()} {parsed.path}", "effective_query": get({"q", "query", "search_query", "search", "query.bibliographic"}), "filters": {"parameters": sorted(params), "body": body}, "sort": get({"sort", "sortBy"}), "limit": get({"limit", "max_results", "per-page", "rows", "num"}), "cursor": get({"cursor", "start", "page"}), "api_version": parsed.path.split("/")[1] if parsed.path.startswith("/v") else "unversioned"}


def install_transports(stack, transport):
    import requests
    import httpx
    requests_send, httpx_send = requests.Session.send, httpx.Client.send

    def send_requests(session, request, **kwargs):
        spec = effective_http(request.method, request.url, request.body or b"")
        def invoke():
            response = requests_send(session, request, **kwargs)
            return {"status_code": response.status_code, "body": base64.b64encode(response.content).decode(), "content_type": response.headers.get("content-type", "")}
        value = transport.call(spec, invoke)
        response = requests.Response()
        response.status_code = value["status_code"]
        response._content = base64.b64decode(value["body"])
        response.headers["content-type"] = value["content_type"]
        response.url, response.request = request.url, request
        return response

    def send_httpx(client, request, **kwargs):
        spec = effective_http(request.method, request.url, request.content)
        def invoke():
            response = httpx_send(client, request, **kwargs)
            response.read()
            return {"status_code": response.status_code, "body": base64.b64encode(response.content).decode(), "content_type": response.headers.get("content-type", "")}
        value = transport.call(spec, invoke)
        return httpx.Response(value["status_code"], content=base64.b64decode(value["body"]), headers={"content-type": value["content_type"]}, request=request)

    stack.enter_context(patch.object(requests.Session, "send", send_requests))
    stack.enter_context(patch.object(httpx.Client, "send", send_httpx))
    if not transport.recording:
        def denied(*args, **kwargs):
            with transport.lock:
                transport.misses.append("unintercepted_network")
            raise ReplayMiss("network access forbidden during replay")
        stack.enter_context(patch.object(socket.socket, "connect", denied))
        stack.enter_context(patch.object(socket.socket, "connect_ex", denied))
        stack.enter_context(patch.object(socket, "getaddrinfo", denied))


def install_model_boundaries(stack, transport, search, config):
    targets = []
    if search.query_analyzer is not None:
        targets.append((search.query_analyzer, "analyze_and_prepare", "analysis"))
    calculator = getattr(search.search_agent, "similarity_calculator", None)
    if calculator is not None:
        for name in ("get_embedding", "_get_embedding", "get_embeddings_batch"):
            if hasattr(calculator, name):
                targets.append((calculator, name, "embedding"))
    ranker = search._hybrid_ranker
    if ranker is not None and hasattr(ranker, "_compute_cross_encoder_scores"):
        targets.append((ranker, "_compute_cross_encoder_scores", "cross_encoder"))
        for name in ("_generate_hyde_unified", "_generate_hypothetical_abstract", "_generate_alt_queries"):
            if hasattr(ranker, name):
                targets.append((ranker, name, "hyde"))
    if hasattr(search, "_graphrag_expand"):
        targets.append((search, "_graphrag_expand", "graph"))
    for target, name, category in targets:
        original = getattr(target, name)
        def wrapper(*args, _original=original, _name=name, _category=category, **kwargs):
            bound = inspect.signature(_original).bind(*args, **kwargs)
            bound.apply_defaults()
            inputs = dict(bound.arguments)
            # Ranker lifecycle controls belong to this invocation, not to model
            # identity. Delegate cutoffs to the real helper for its exact return
            # contract; never substitute a previously successful frozen value.
            deadline = inputs.pop("deadline", None)
            stop_event = inputs.pop("stop_event", None)
            def cutoff():
                if _category not in {"hyde", "cross_encoder"}:
                    return False
                from src.graph_rag.hybrid_ranker import _cutoff_reason
                return bool(_cutoff_reason(deadline, stop_event))
            if cutoff():
                return _original(*args, **kwargs)
            client = inputs.pop("openai_client", None)
            if client is not None:
                inputs["model_client"] = {"type": type(client).__name__, "base_url": str(getattr(client, "base_url", ""))}
            spec = {"boundary": f"{_category}.{_name}", "input": json_value(inputs), "config": config}
            def invoke():
                value = _original(*args, **kwargs)
                return json_value(value)
            value = transport.call(spec, invoke, boundary=True)
            if not transport.recording and cutoff():
                return _original(*args, **kwargs)
            return value
        stack.enter_context(patch.object(target, name, wrapper))


def drain_operations(search):
    for owner in (search.search_agent, getattr(search, "_router_operation_owner", None)):
        generation_state = getattr(owner, "_operation_generation_runtime", None)
        if generation_state:
            lock, generations = generation_state
            with lock:
                pending = [g for group in generations.values() for g in group]
            for generation in pending:
                generation._executor.shutdown(wait=True, cancel_futures=True)


async def execute_queries(matrix, capture, mode, manifest, recording=False):
    """Use the real ASGI route; only I/O and model boundaries are substituted."""
    import time
    transport = FrozenTransport(capture, recording)
    rows = []
    with ExitStack() as stack:
        install_transports(stack, transport)
        try:
            from fastapi import FastAPI
            import httpx
            from routers import search
            from src.graph_rag import hybrid_ranker
            generate_result_key = evaluation_identity()
            app = FastAPI()
            app.include_router(search.router)
            app.dependency_overrides[search.get_optional_user] = lambda: None
            # Neither warm reads nor writes may contaminate another query/environment.
            stack.enter_context(patch.object(search, "_get_cached_result", return_value=None))
            stack.enter_context(patch.object(search, "_set_cache", return_value=None))
            for cache_name in ("_HYDE_CACHE", "_CE_CACHE"):
                if hasattr(hybrid_ranker, cache_name):
                    stack.enter_context(patch.object(hybrid_ranker, cache_name, {}))
            install_model_boundaries(stack, transport, search, manifest["config"])
            original_dedup = search.search_agent.deduplicator.deduplicate
            def observe_candidates(papers, *args, **kwargs):
                with transport.lock:
                    transport.candidates.update(generate_result_key(p) for p in papers)
                return original_dedup(papers, *args, **kwargs)
            stack.enter_context(patch.object(search.search_agent.deduplicator, "deduplicate", observe_candidates))
        except Exception as exc:
            for q in matrix["queries"]:
                rows.append({"query_id": q["query_id"], "ranked": [], "records": [], "request_keys": [], "replay_misses": [f"runtime_unavailable:{type(exc).__name__}:{exc}"], "source_outcomes": {}, "call_counts": {}, "elapsed_ms": 0.0})
            return rows, transport
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://evaluation.invalid") as client:
            for q in matrix["queries"]:
                # Draining must succeed before transferring collector ownership.
                # In particular, never relabel a late previous-query observation.
                drain_operations(search)
                with transport.lock:
                    transport.candidates.clear()
                start, ledger_start, miss_start = time.perf_counter(), len(transport.ledger), len(transport.misses)
                request = {**q["request"], **q["request"]["filters"], "query": q["query"], "fast_mode": mode == "fast", "save_papers": False}
                request.pop("filters")
                records, metadata, errors = [], {}, []
                if search.query_analyzer is None:
                    errors.append("analysis_dependency_unavailable")
                if search._hybrid_ranker is None:
                    errors.append("ranking_dependency_unavailable")
                try:
                    response = await client.post("/api/search", json=request)
                    if response.status_code != 200:
                        errors.append(f"route_status:{response.status_code}")
                    else:
                        body = response.json()
                        metadata = copy.deepcopy(body.get("metadata") or {})
                        records = [dict(p) for bucket in body.get("results", {}).values() if isinstance(bucket, list) for p in bucket]
                        records.sort(key=lambda p: p.get("_rank", 10 ** 9))
                        for p in records:
                            p["result_key"] = generate_result_key(p)
                        if body.get("degraded"):
                            errors.extend(f"degraded:{reason}" for reason in body["degraded"])
                        if any((body.get("source_timeouts") or metadata.get("source_timeouts") or {}).values()):
                            errors.append("partial_source_timeout")
                        stage_modes = body.get("stage_modes") or metadata.get("stage_modes") or {}
                        for stage, outcome in stage_modes.items():
                            if any(word in str(outcome).lower() for word in ("timeout", "error", "unavailable", "partial")):
                                errors.append(f"incomplete_stage:{stage}:{outcome}")
                except Exception as exc:
                    errors.append(f"route_error:{type(exc).__name__}:{exc}")
                drain_operations(search)
                ledger = transport.ledger[ledger_start:]
                counts = {key: ledger.count(key) for key in set(ledger)}
                rows.append({"query_id": q["query_id"], "ranked": [p["result_key"] for p in records], "records": records, "request_keys": ledger, "replay_misses": transport.misses[miss_start:] + errors, "source_outcomes": metadata, "call_counts": counts, "elapsed_ms": (time.perf_counter() - start) * 1000})
                if recording:
                    with transport.lock:
                        candidates = set(transport.candidates)
                    capture["pools"][q["query_id"]] = sorted(set(capture["pools"].get(q["query_id"], [])) | candidates | {p["result_key"] for p in records})
        # CLI owns this process: do not unpatch while production workers remain.
        drain_operations(search)
        hyde_executor = getattr(hybrid_ranker, "_HYDE_EXECUTOR", None)
        if hyde_executor is not None:
            hyde_executor.shutdown(wait=True, cancel_futures=True)
    return rows, transport


def run_artifact(matrix, capture, mode, manifest, rows, started_at):
    return seal({"version": "search-review-run-v1", "matrix_hash": matrix["matrix_hash"], "capture_hash": capture["capture_hash"], "manifest": manifest, "mode": mode, "evidence_kind": capture["evidence_kind"], "per_query": rows, "timing_scope": "replay", "started_at": started_at}, "run_hash")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "replay", "compare", "capture"):
        p = sub.add_parser(name)
        p.add_argument("--matrix", required=True)
        if name != "capture":
            p.add_argument("--capture", required=True)
        if name in {"validate", "compare"}:
            p.add_argument("--judgments", required=True)
        if name in {"replay", "capture"}:
            p.add_argument("--mode", required=True, choices=("standard", "fast"))
        if name in {"replay", "compare"}:
            p.add_argument("--out", required=True)
        if name == "compare":
            p.add_argument("--baseline", required=True)
            p.add_argument("--candidate", required=True)
            p.add_argument("--scope", required=True, choices=("routed_replay", "fixed_pool"))
        if name == "capture":
            p.add_argument("--out-dir", required=True)
            p.add_argument("--max-candidates-per-query", type=int, choices=(80,), required=True)
    args = parser.parse_args(argv)
    try:
        matrix = read_json(args.matrix)
        validate_matrix(matrix)
        if args.command == "capture":
            manifest = current_manifest()
            if args.mode == "standard":
                require(manifest["revision"] == BASELINE_REVISION and manifest["configuration"]["clean_source"], "baseline capture requires isolated clean pinned baseline checkout; do not repin after outcomes")
            path = Path(args.out_dir) / "capture.json"
            capture = read_json(path) if path.exists() else {"version": "search-review-capture-v1", "matrix_hash": matrix["matrix_hash"], "baseline": None, "candidate": None, "evidence_kind": "recorded_provider", "entries": [], "boundaries": [], "pools": {}, "browser_evidence": []}
            if path.exists():
                validate_capture(matrix, capture)
                require(capture["evidence_kind"] == "recorded_provider", "cannot merge synthetic and live receipts")
            role = "baseline" if args.mode == "standard" else "candidate"
            require(capture[role] is None or capture[role] == manifest, "capture manifest already frozen; use a new output directory")
            capture[role] = manifest
            rows, transport = asyncio.run(execute_queries(matrix, capture, args.mode, manifest, recording=True))
            if transport.conflicts:
                write_json(Path(args.out_dir) / "conflicts.json", {"request_keys": transport.conflicts, "resolution_required": "Choose and document one frozen snapshot before replaying either mode."})
                raise InvalidArtifact("conflicting capture responses; sealed capture was not changed")
            capture = seal(capture, "capture_hash")
            validate_capture(matrix, capture)
            write_json(path, capture)
            write_json(Path(args.out_dir) / f"{args.mode}-collection.json", {"per_query": rows, "promotion_decision": "inconclusive", "reason": "Collection is not reviewed evaluation; replay both modes after final capture sealing."})
            return 3
        capture = read_json(args.capture, "capture")
        validate_capture(matrix, capture)
        if args.command == "replay":
            manifest = current_manifest()
            pinned = capture["baseline" if args.mode == "standard" else "candidate"]
            require(pinned is None or pinned == manifest, "checked-out implementation differs from pinned capture; explicitly repin before scoring")
            started = datetime.now(timezone.utc).isoformat()
            rows, _ = asyncio.run(execute_queries(matrix, capture, args.mode, manifest))
            run = run_artifact(matrix, capture, args.mode, manifest, rows, started)
            write_json(args.out, run)
            return 3 if pinned is None or capture["evidence_kind"] == "synthetic" or any(q["replay_misses"] for q in rows) else 0
        judgments = read_json(args.judgments, "judgments")
        validate_judgments(matrix, capture, judgments)
        if args.command == "validate":
            print(json.dumps({"valid": True, "promotion_qualified": False, "reason": "Validation is structural, not human authentication or promotion."}))
            return 0
        report = compare(matrix, capture, judgments, read_json(args.baseline), read_json(args.candidate), args.scope)
        write_json(args.out, report)
        return {"pass": 0, "inconclusive": 3, "fail": 4}[report["promotion_decision"]]
    except (InvalidArtifact, ValueError, TypeError, KeyError, OSError) as exc:
        print(f"invalid evaluation artifact: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
