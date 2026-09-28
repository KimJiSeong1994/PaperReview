"""Offline-first fixed-pool evaluation for Jev paper relevance scoring.

Run with ``python -m src.search_eval.jev_eval --help``. This evaluator never
changes production search behavior and its reports are not promotion authority.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import sys
import time

from . import judged_replay
from .jev_client import (
    MODEL,
    RUBRIC_HASH,
    RUBRIC_VERSION,
    JevError,
    score_candidate,
    validate_score_result,
)


INPUT_VERSION = "jev-evaluation-input-v1"
REPORT_VERSION = "jev-evaluation-report-v1"
CAPTURE_VERSION = "jev-evaluation-scoring-v1"
MAX_CALLS = 80
MAX_CANDIDATES_PER_QUERY = 80
DEFAULT_TIMEOUT = 10.0
DEFAULT_TOTAL_DEADLINE = 60.0
INPUT_PRICE_PER_MILLION_USD = 0.042
MAX_QUERY_CHARS = 2_000
MAX_TITLE_CHARS = 1_000
MAX_ABSTRACT_CHARS = 12_000

METRIC_NAMES = (
    "nDCG@10",
    "MRR@10",
    "Recall@5",
    "Recall@10",
    "wrong_paper_handoff_rate",
)
_CAPTURE_KEYS = {
    "version",
    "input_hash",
    "model",
    "rubric_version",
    "rubric_hash",
    "results",
    "scoring_hash",
}
_REPORT_KEYS = {
    "version",
    "input_hash",
    "evidence_kind",
    "model",
    "rubric_version",
    "rubric_hash",
    "execution_mode",
    "comparison_scope",
    "baseline_definition",
    "timing_scope",
    "per_query",
    "aggregate",
    "slices",
    "usage",
    "scoring_elapsed_ms",
    "grade_provenance",
    "promotion_eligible",
    "rollout_authority",
    "limitations",
    "scoring_capture",
    "report_hash",
}


class JevEvaluationError(ValueError):
    """A safe, user-facing input, replay, or evaluation error."""


def _require(condition, message):
    if not condition:
        raise JevEvaluationError(message)


def _exact_keys(value, expected, name):
    _require(
        type(value) is dict and set(value) == set(expected), f"invalid {name} fields"
    )


def _nonempty_text(value):
    return type(value) is str and bool(value.strip())


def validate_input(value):
    """Validate the complete fixed-pool artifact before I/O or output writes."""
    _exact_keys(value, {"version", "evidence_kind", "queries"}, "input")
    _require(value["version"] == INPUT_VERSION, "invalid input version")
    evidence_kind = value["evidence_kind"]
    _require(type(evidence_kind) is str, "invalid evidence kind")
    _require(evidence_kind in {"synthetic", "human_reviewed"}, "invalid evidence kind")
    queries = value["queries"]
    _require(
        type(queries) is list and 1 <= len(queries) <= 24,
        "input requires 1..24 queries",
    )

    query_ids = set()
    for query in queries:
        _exact_keys(
            query,
            {"query_id", "query", "language", "split", "candidates", "judgments"},
            "query",
        )
        _require(_nonempty_text(query["query_id"]), "query_id must be nonempty")
        _require(query["query_id"] not in query_ids, "duplicate query_id")
        query_ids.add(query["query_id"])
        _require(
            _nonempty_text(query["query"]) and len(query["query"]) <= MAX_QUERY_CHARS,
            "query must be nonempty and at most 2000 characters",
        )
        _require(
            type(query["language"]) is str and query["language"] in {"en", "ko"},
            "invalid query language",
        )
        _require(
            type(query["split"]) is str
            and query["split"] in {"development", "holdout"},
            "invalid query split",
        )

        candidates = query["candidates"]
        _require(
            type(candidates) is list and len(candidates) <= MAX_CANDIDATES_PER_QUERY,
            "each query allows at most 80 candidates",
        )
        candidate_ids = set()
        for candidate in candidates:
            _exact_keys(candidate, {"paper_key", "title", "abstract"}, "candidate")
            _require(
                _nonempty_text(candidate["paper_key"]), "paper_key must be nonempty"
            )
            _require(
                candidate["paper_key"] not in candidate_ids,
                "duplicate candidate paper_key",
            )
            candidate_ids.add(candidate["paper_key"])
            _require(
                _nonempty_text(candidate["title"])
                and _nonempty_text(candidate["abstract"])
                and len(candidate["title"]) <= MAX_TITLE_CHARS
                and len(candidate["abstract"]) <= MAX_ABSTRACT_CHARS,
                "insufficient metadata: every candidate needs a nonempty title and abstract",
            )

        judgments = query["judgments"]
        _require(
            type(judgments) is list and len(judgments) == len(candidates),
            "complete judgments required",
        )
        judgment_ids = set()
        for judgment in judgments:
            _exact_keys(
                judgment,
                {
                    "paper_key",
                    "grade",
                    "required",
                    "excluded",
                    "evidence_refs",
                    "author_id",
                    "reviewer_id",
                    "review_status",
                },
                "judgment",
            )
            paper_key = judgment["paper_key"]
            _require(_nonempty_text(paper_key), "judgment paper_key must be nonempty")
            _require(
                paper_key in candidate_ids, "judgment references an unknown candidate"
            )
            _require(paper_key not in judgment_ids, "duplicate judgment paper_key")
            judgment_ids.add(paper_key)
            grade = judgment["grade"]
            _require(
                type(grade) is int and 0 <= grade <= 3, "grade must be integer 0..3"
            )
            _require(
                type(judgment["required"]) is bool
                and type(judgment["excluded"]) is bool,
                "judgment flags must be booleans",
            )
            _require(
                not (judgment["required"] and judgment["excluded"]),
                "excluded identity cannot be required",
            )
            _require(
                not judgment["required"] or grade > 0,
                "required identity must have positive grade",
            )
            refs = judgment["evidence_refs"]
            _require(
                type(refs) is list and all(_nonempty_text(ref) for ref in refs),
                "invalid evidence_refs",
            )
            _require(
                type(judgment["review_status"]) is str
                and judgment["review_status"] in {"synthetic", "reviewed"},
                "invalid review_status",
            )
            for field in ("author_id", "reviewer_id"):
                _require(
                    judgment[field] is None or type(judgment[field]) is str,
                    f"invalid {field}",
                )
            if evidence_kind == "synthetic":
                _require(
                    judgment["review_status"] == "synthetic",
                    "synthetic input requires synthetic judgments",
                )
            else:
                _require(
                    judgment["review_status"] == "reviewed",
                    "human_reviewed input requires reviewed judgments",
                )
                _require(
                    _nonempty_text(judgment["author_id"])
                    and _nonempty_text(judgment["reviewer_id"])
                    and judgment["author_id"] != judgment["reviewer_id"]
                    and refs,
                    "human_reviewed judgments require distinct author/reviewer IDs and evidence refs",
                )
        _require(
            judgment_ids == candidate_ids,
            "complete judgments required for every candidate",
        )
    return value


def _validate_score_result_shape(result):
    try:
        validate_score_result(result)
    except JevError:
        raise JevEvaluationError("invalid score result") from None


def _candidate_pairs(value):
    return [
        (query["query_id"], candidate["paper_key"])
        for query in value["queries"]
        for candidate in query["candidates"]
    ]


def _check_result_rows(input_value, rows):
    _require(type(rows) is list, "invalid captured score results")
    expected = _candidate_pairs(input_value)
    _require(
        len(rows) == len(expected), "captured scores do not cover the input candidates"
    )
    seen = set()
    for row, pair in zip(rows, expected):
        _exact_keys(row, {"query_id", "paper_key", "result"}, "captured score")
        _require(
            (row["query_id"], row["paper_key"]) == pair,
            "captured scores do not match input candidate order",
        )
        key = (row["query_id"], row["paper_key"])
        _require(key not in seen, "duplicate captured score identity")
        seen.add(key)
        _validate_score_result_shape(row["result"])


def make_scoring_capture(input_value, input_hash, results):
    capture = {
        "version": CAPTURE_VERSION,
        "input_hash": input_hash,
        "model": MODEL,
        "rubric_version": RUBRIC_VERSION,
        "rubric_hash": RUBRIC_HASH,
        "results": copy.deepcopy(results),
    }
    capture["scoring_hash"] = judged_replay.digest(capture)
    return capture


def validate_replay_report(report, input_value, input_hash):
    _exact_keys(report, _REPORT_KEYS, "replay report")
    _require(report["version"] == REPORT_VERSION, "invalid replay report version")
    report_hash = report["report_hash"]
    report_without_hash = dict(report)
    del report_without_hash["report_hash"]
    _require(
        report_hash == judged_replay.digest(report_without_hash),
        "replay report hash mismatch",
    )
    _require(report["input_hash"] == input_hash, "replay input binding mismatch")
    _require(
        report["evidence_kind"] == input_value["evidence_kind"],
        "replay evidence binding mismatch",
    )
    _require(
        report["model"] == MODEL
        and report["rubric_version"] == RUBRIC_VERSION
        and report["rubric_hash"] == RUBRIC_HASH,
        "replay model or rubric binding mismatch",
    )
    _require(
        report["execution_mode"] in ("network", "replay"),
        "invalid replay execution mode",
    )
    _require(
        report["comparison_scope"] == "fixed_pool"
        and report["baseline_definition"] == "input_order_not_production_ranker"
        and report["timing_scope"] == "jev_scoring_only"
        and report["promotion_eligible"] is False
        and report["rollout_authority"] is False,
        "invalid replay report contract",
    )
    capture = report["scoring_capture"]
    _exact_keys(capture, _CAPTURE_KEYS, "scoring capture")
    _require(capture["version"] == CAPTURE_VERSION, "invalid scoring capture version")
    _require(capture["input_hash"] == input_hash, "replay input binding mismatch")
    _require(
        capture["model"] == MODEL
        and capture["rubric_version"] == RUBRIC_VERSION
        and capture["rubric_hash"] == RUBRIC_HASH,
        "replay model or rubric binding mismatch",
    )
    capture_without_hash = dict(capture)
    del capture_without_hash["scoring_hash"]
    _require(
        capture["scoring_hash"] == judged_replay.digest(capture_without_hash),
        "scoring capture hash mismatch",
    )
    _check_result_rows(input_value, capture["results"])
    return copy.deepcopy(capture["results"])


def _run_network(input_value, api_key, max_calls, timeout, total_deadline):
    candidate_count = sum(len(query["candidates"]) for query in input_value["queries"])
    _require(candidate_count <= max_calls, "candidate count exceeds --max-calls")
    deadline = time.monotonic() + total_deadline
    results = []
    for query in input_value["queries"]:
        for candidate in query["candidates"]:
            remaining = deadline - time.monotonic()
            _require(remaining > 0, "total scoring deadline exceeded")
            call_timeout = min(timeout, remaining)
            try:
                result = score_candidate(
                    query["query"],
                    candidate,
                    api_key=api_key,
                    client=None,
                    timeout=call_timeout,
                )
                _validate_score_result_shape(result)
            except JevEvaluationError:
                raise
            except JevError as exc:
                safe_messages = {
                    "TypeSafe authentication failed",
                    "TypeSafe rate limit exceeded",
                    "TypeSafe service overloaded",
                    "TypeSafe request timed out",
                }
                message = str(exc)
                if message not in safe_messages:
                    message = "scoring request failed"
                raise JevEvaluationError(message) from None
            except Exception:
                raise JevEvaluationError("scoring request failed") from None
            _require(time.monotonic() <= deadline, "total scoring deadline exceeded")
            results.append(
                {
                    "query_id": query["query_id"],
                    "paper_key": candidate["paper_key"],
                    "result": copy.deepcopy(result),
                }
            )
    return results


def _metrics_for_order(order, judgments):
    return judged_replay.score_identities(order, judgments)


def _mean_metrics(items):
    count = len(items)
    _require(count > 0, "cannot aggregate an empty slice")
    return {
        name: math.fsum(row[name] for row in items) / count for name in METRIC_NAMES
    }


def _aggregate(items):
    return {
        "query_count": len(items),
        "baseline": _mean_metrics([item["baseline_metrics"] for item in items]),
        "candidate": _mean_metrics([item["candidate_metrics"] for item in items]),
    }


def build_report(input_value, execution_mode, results):
    input_hash = judged_replay.digest(input_value)
    _check_result_rows(input_value, results)
    result_by_identity = {
        (row["query_id"], row["paper_key"]): row["result"] for row in results
    }
    per_query = []
    for query in input_value["queries"]:
        input_order = [candidate["paper_key"] for candidate in query["candidates"]]
        score_by_key = {
            paper_key: result_by_identity[(query["query_id"], paper_key)]
            for paper_key in input_order
        }
        candidate_order = sorted(
            input_order, key=lambda key: score_by_key[key]["score"], reverse=True
        )
        _require(
            len(candidate_order) == len(input_order)
            and set(candidate_order) == set(input_order),
            "reranking changed the candidate identity set",
        )
        judgments = {
            row["paper_key"]: {
                "grade": row["grade"],
                "required": row["required"],
                "excluded": row["excluded"],
            }
            for row in query["judgments"]
        }
        baseline_metrics = _metrics_for_order(input_order, judgments)
        candidate_metrics = _metrics_for_order(candidate_order, judgments)
        per_query.append(
            {
                "query_id": query["query_id"],
                "query": query["query"],
                "language": query["language"],
                "split": query["split"],
                "candidate_ids": input_order,
                "baseline_order": input_order,
                "candidate_order": candidate_order,
                "scores": [
                    {"paper_key": key, **copy.deepcopy(score_by_key[key])}
                    for key in input_order
                ],
                "baseline_metrics": baseline_metrics,
                "candidate_metrics": candidate_metrics,
                "scoring_elapsed_ms": math.fsum(
                    score_by_key[key]["elapsed_ms"] for key in input_order
                ),
            }
        )

    slices = {}
    for language in ("en", "ko"):
        selected = [row for row in per_query if row["language"] == language]
        if selected:
            slices[f"language/{language}"] = _aggregate(selected)
    for split in ("development", "holdout"):
        selected = [row for row in per_query if row["split"] == split]
        if selected:
            slices[f"split/{split}"] = _aggregate(selected)

    input_tokens = sum(row["result"]["usage"]["input_tokens"] for row in results)
    output_tokens = sum(row["result"]["usage"]["output_tokens"] for row in results)
    scoring_elapsed_ms = math.fsum(row["result"]["elapsed_ms"] for row in results)
    report = {
        "version": REPORT_VERSION,
        "input_hash": input_hash,
        "evidence_kind": input_value["evidence_kind"],
        "model": MODEL,
        "rubric_version": RUBRIC_VERSION,
        "rubric_hash": RUBRIC_HASH,
        "execution_mode": execution_mode,
        "comparison_scope": "fixed_pool",
        "baseline_definition": "input_order_not_production_ranker",
        "timing_scope": "jev_scoring_only",
        "per_query": per_query,
        "aggregate": _aggregate(per_query),
        "slices": slices,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_input_cost_usd": input_tokens
            * INPUT_PRICE_PER_MILLION_USD
            / 1_000_000,
        },
        "scoring_elapsed_ms": scoring_elapsed_ms,
        "grade_provenance": {
            "evidence_kind": input_value["evidence_kind"],
            "judgment_sources": [
                {
                    "query_id": query["query_id"],
                    "paper_key": judgment["paper_key"],
                    "review_status": judgment["review_status"],
                    "evidence_refs": judgment["evidence_refs"],
                    "author_id": judgment["author_id"],
                    "reviewer_id": judgment["reviewer_id"],
                }
                for query in input_value["queries"]
                for judgment in query["judgments"]
            ],
            "human_authentication_claimed": False,
            "production_claimed": False,
        },
        "promotion_eligible": False,
        "rollout_authority": False,
        "limitations": [
            "Baseline is input order, not a production ranker.",
            "Fixed-pool results do not measure retrieval or live-corpus coverage.",
            "Evidence provenance is not authentication of human participation.",
            "This evaluation report grants no implementation, promotion, or rollout authority.",
            "Timing covers Jev scoring responses only, not end-to-end application latency.",
        ],
        "scoring_capture": make_scoring_capture(input_value, input_hash, results),
    }
    report["report_hash"] = judged_replay.digest(report)
    return report


def _resolve_path(path):
    return Path(path).expanduser().resolve(strict=False)


def _preflight_output(output_path, input_path, replay_path=None):
    output_resolved = _resolve_path(output_path)
    protected = [_resolve_path(input_path)]
    if replay_path is not None:
        protected.append(_resolve_path(replay_path))
    _require(output_resolved not in protected, "output path aliases an input artifact")
    _require(
        not os.path.lexists(Path(output_path).expanduser()), "output already exists"
    )
    return Path(output_path).expanduser()


def _write_exclusive(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise JevEvaluationError("output already exists") from None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise JevEvaluationError("could not write evaluation report") from None


def _positive_bounded_float(value, maximum, name):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"{name} must be a number") from None
    if not math.isfinite(parsed) or parsed <= 0 or parsed > maximum:
        raise argparse.ArgumentTypeError(
            f"{name} must be greater than 0 and at most {maximum:g}"
        )
    return parsed


def _call_count(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            "max-calls must be an integer from 1 to 80"
        ) from None
    if str(parsed) != str(value) or not 1 <= parsed <= MAX_CALLS:
        raise argparse.ArgumentTypeError("max-calls must be an integer from 1 to 80")
    return parsed


def _parser():
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate one fixed candidate pool per query. Network access requires "
            "--allow-network --max-calls N; otherwise use --replay PATH."
        )
    )
    parser.add_argument(
        "--input", required=True, metavar="PATH", help="jev-evaluation-input-v1 JSON"
    )
    parser.add_argument(
        "--out", required=True, metavar="PATH", help="new report path (must not exist)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--allow-network",
        action="store_true",
        help="explicitly permit TypeSafe API calls",
    )
    mode.add_argument(
        "--replay",
        metavar="PATH",
        help="reuse scoring results in a prior report; no network",
    )
    parser.add_argument(
        "--max-calls",
        type=_call_count,
        help="required hard call cap (1..80) with --allow-network",
    )
    parser.add_argument(
        "--timeout",
        "--per-call-timeout",
        dest="timeout",
        type=lambda value: _positive_bounded_float(value, 30, "timeout"),
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help="per-call timeout, at most 30 seconds (default: 10)",
    )
    parser.add_argument(
        "--total-deadline",
        type=lambda value: _positive_bounded_float(value, 300, "total-deadline"),
        default=DEFAULT_TOTAL_DEADLINE,
        metavar="SECONDS",
        help="total network-scoring deadline, at most 300 seconds (default: 60)",
    )
    return parser


def _read_json_safe(path, name):
    try:
        value = judged_replay.read_json(Path(path).expanduser())
    except Exception:
        raise JevEvaluationError(f"could not read {name} JSON") from None
    return value


def _print_metrics(report):
    names = {
        "nDCG@10": "ndcg_at_10",
        "MRR@10": "mrr_at_10",
        "Recall@5": "recall_at_5",
        "Recall@10": "recall_at_10",
        "wrong_paper_handoff_rate": "wrong_paper_handoff_rate",
    }
    for prefix in ("candidate", "baseline"):
        for metric in METRIC_NAMES:
            print(
                f"METRIC {prefix}_{names[metric]}={report['aggregate'][prefix][metric]:.10f}"
            )
    print(
        f"METRIC estimated_input_cost_usd={report['usage']['estimated_input_cost_usd']:.10f}"
    )


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if args.allow_network and args.max_calls is None:
        parser.error("--allow-network requires --max-calls N")
    if not args.allow_network and args.max_calls is not None:
        parser.error("--max-calls is only valid with --allow-network")
    if not args.allow_network and args.replay is None:
        parser.error(
            "choose --allow-network --max-calls N or --replay PATH; network is not enabled by default"
        )

    try:
        output_path = _preflight_output(args.out, args.input, args.replay)
        input_value = _read_json_safe(args.input, "input")
        validate_input(input_value)
        input_hash = judged_replay.digest(input_value)

        if args.allow_network:
            candidate_count = sum(
                len(query["candidates"]) for query in input_value["queries"]
            )
            _require(
                candidate_count <= args.max_calls, "candidate count exceeds --max-calls"
            )
            api_key = os.environ.get("TYPESAFE_API_KEY")
            _require(
                _nonempty_text(api_key),
                "TYPESAFE_API_KEY is required for network scoring",
            )
            results = _run_network(
                input_value,
                api_key,
                args.max_calls,
                args.timeout,
                args.total_deadline,
            )
            execution_mode = "network"
        else:
            replay_value = _read_json_safe(args.replay, "replay")
            results = validate_replay_report(replay_value, input_value, input_hash)
            execution_mode = "replay"

        report = build_report(input_value, execution_mode, results)
        _write_exclusive(output_path, report)
        _print_metrics(report)
        return 0
    except JevEvaluationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception:
        print("ERROR: evaluation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
