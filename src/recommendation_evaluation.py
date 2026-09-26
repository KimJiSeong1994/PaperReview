"""Frozen, offline recommendation comparisons; no product inputs or provider access.

Manifest cases contain public/synthetic bibliographic lists, never profiles or raw
user events. SHA256 receipts bind bytes, not authenticity or independent judgment.
The only serving projection is RecommendationPolicy.project.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from src.recommendation_state import RecommendationPolicy

SCHEMA = "recommendation-offline-v1"
REQUIRED_SLICES = (
    "ko",
    "en",
    "cold",
    "sparse",
    "active",
    "local",
    "merged",
    "old",
    "new",
)
CONFIG = {
    "primary_k": 5,
    "secondary_k": 12,
    "bootstrap_samples": 2000,
    "seed": 20260925,
    "min_clusters": 30,
    "min_slice_clusters": 10,
    "ndcg_relative_floor": -0.02,
    "recall_coverage_floor": -0.02,
    "slice_drop_floor": -0.05,
    "zero_baseline": "inconclusive",
    "gain": "2**label-1",
    "positive_label": ">0",
    "missing_label": "inconclusive",
    "empty_positive_denominator": "inconclusive",
}
OPERATIONAL_REQUIREMENTS = {
    "shadow": {
        "daily_runs_min": 7,
        "delivery_min": 0.99,
        "stale_over_36h_max": 0.01,
        "safety_violations_max": 0,
        "budget_violations_max": 0,
    },
    "canary": {"max_users": 10, "max_eligible_fraction": 0.05, "safety_days_min": 7},
    "online": {
        "observation_days_min": 14,
        "alpha": 0.05,
        "power": 0.80,
        "relative_mde": 0.10,
        "primary_ci_lower_strictly_above": 0,
        "delivery_min": 0.99,
        "stale_max": 0.01,
        "impression_duplicate_max": 0.001,
        "missing_known_view_linkage_max": 0.01,
        "hide_rate_delta_ci_upper_max": 0.01,
        "safety_violations_max": 0,
        "primary": "7-day attributed save/review-start per visible Top5 user-day",
        "assignment": "fixed user assignment stratified by activity",
        "denominators": "active, eligible, unavailable, visible user-days; repeated cards are not users",
    },
    "rollout": {
        "eligible_percent_steps": [5, 25, 100],
        "days_each_min": 7,
        "global_flag_change": "separate approval required",
    },
    "performance": {
        "users": 100,
        "public_candidates": 10000,
        "private_candidates_per_user": 500,
        "events_per_user": 500,
        "k": 12,
        "mmr_pool": 200,
        "user_p95_seconds_max": 2,
        "batch_seconds_max": 600,
        "rss_bytes_max": 1073741824,
        "required_context": "hardware and worker count",
    },
}


class EvaluationError(ValueError):
    """Invalid or unsafe offline evidence. Error messages contain no input payload."""


def digest(value: Any) -> str:
    """Canonical JSON digest for inline frozen structures."""
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    except (ValueError, TypeError) as exc:
        raise EvaluationError("invalid_frozen_json") from exc
    return hashlib.sha256(encoded).hexdigest()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise EvaluationError(reason)


def _object(value: Any, allowed: set[str], required: set[str], name: str) -> None:
    _require(isinstance(value, dict), f"invalid_{name}")
    _require(required <= value.keys() and value.keys() <= allowed, f"fields_{name}")


def _time(value: Any) -> datetime:
    _require(isinstance(value, str), "invalid_time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvaluationError("invalid_time") from exc
    _require(parsed.tzinfo is not None, "naive_time")
    return parsed.astimezone(timezone.utc)


def _token(value: Any) -> None:
    _require(
        isinstance(value, str)
        and 0 < len(value) <= 256
        and all(c.isalnum() or c in "-_:./" for c in value),
        "invalid_identifier",
    )


def _number(value: Any, low: float, high: float) -> None:
    _require(
        type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
        "invalid_finite_number",
    )


def _safe_file(root: Path, relative: str) -> Path:
    _require(isinstance(relative, str), "invalid_path")
    path = Path(relative)
    _require(
        not path.is_absolute() and path.parts and ".." not in path.parts, "unsafe_path"
    )
    current = root
    for part in path.parts:
        current = current / part
        _require(not current.is_symlink(), "symlink_path")
    _require(
        current.is_file() and current.resolve().is_relative_to(root.resolve()),
        "missing_or_unsafe_path",
    )
    return current


def load_manifest(path: str | Path, *, root: str | Path | None = None) -> dict:
    """Load a bounded manifest only from data/recommendation_eval inside repository root."""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    path = Path(path)
    if path.is_absolute():
        try:
            path = path.relative_to(root.absolute())
        except ValueError as exc:
            raise EvaluationError("unsafe_manifest_path") from exc
    _require(
        path.parts[:2] == ("data", "recommendation_eval"),
        "manifest_outside_eval_directory",
    )
    safe = _safe_file(root, str(path))
    _require(safe.stat().st_size <= 8 * 1024 * 1024, "manifest_too_large")

    def pairs(items: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    try:
        manifest = json.loads(
            safe.read_text(encoding="utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                EvaluationError("nonfinite_json")
            ),
        )
    except (ValueError, UnicodeError) as exc:
        raise EvaluationError("invalid_manifest_json") from exc
    validate_manifest(manifest, root=root)
    return manifest


def validate_manifest(manifest: dict, *, root: str | Path | None = None) -> None:
    """Fail closed on schema, temporal, privacy, comparability and frozen receipt errors."""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    fields = {
        "schema",
        "scope",
        "evidence_kind",
        "cutoff",
        "label_cutoff",
        "config",
        "bindings",
        "provenance",
        "comparisons",
        "safety_violations",
    }
    _object(manifest, fields, fields, "manifest")
    _require(
        manifest["schema"] == SCHEMA
        and manifest["scope"] == "evaluation_only_non_serving",
        "invalid_scope",
    )
    _require(
        manifest["evidence_kind"]
        in {"synthetic_correctness", "public_bibliographic_judgments"},
        "invalid_evidence_kind",
    )
    _require(manifest["config"] == CONFIG, "unregistered_config")
    cutoff, label_cutoff = _time(manifest["cutoff"]), _time(manifest["label_cutoff"])
    _require(cutoff < label_cutoff, "invalid_temporal_split")
    bindings = manifest["bindings"]
    _object(
        bindings,
        {"code", "config_sha256", "input_sha256", "protocol_sha256"},
        {"code", "config_sha256", "input_sha256", "protocol_sha256"},
        "bindings",
    )
    _require(
        isinstance(bindings["code"], dict)
        and set(bindings["code"])
        == {
            "src/recommendation_evaluation.py",
            "src/recommendation_state.py",
            "scripts/evaluate_daily_recommendations.py",
        },
        "missing_code_policy_binding",
    )
    for path, expected in bindings["code"].items():
        actual = hashlib.sha256(_safe_file(root, path).read_bytes()).hexdigest()
        _require(actual == expected, "code_policy_hash_mismatch")
    _require(
        bindings["config_sha256"] == digest(manifest["config"]), "config_hash_mismatch"
    )
    frozen_input = {
        key: manifest[key]
        for key in (
            "scope",
            "evidence_kind",
            "cutoff",
            "label_cutoff",
            "comparisons",
            "safety_violations",
        )
    }
    _require(bindings["input_sha256"] == digest(frozen_input), "input_hash_mismatch")
    provenance = manifest["provenance"]
    provenance_fields = {
        "source",
        "capture",
        "baseline",
        "judge",
        "protocol",
        "temporal",
        "exposure_denominators",
    }
    _object(provenance, provenance_fields, provenance_fields, "provenance")
    _require(
        all(isinstance(v, str) and len(v) <= 2000 for v in provenance.values()),
        "invalid_provenance",
    )
    _require(
        bindings["protocol_sha256"] == digest(provenance), "protocol_hash_mismatch"
    )
    _require(
        isinstance(manifest["safety_violations"], dict)
        and set(manifest["safety_violations"])
        == {"rank", "privacy", "hide", "incarnation", "budget"},
        "invalid_safety_counts",
    )
    for value in manifest["safety_violations"].values():
        _require(type(value) is int and value >= 0, "invalid_safety_count")
    comparisons = manifest["comparisons"]
    _require(
        isinstance(comparisons, list) and 1 <= len(comparisons) <= 20,
        "invalid_comparisons",
    )
    names = set()
    for comparison in comparisons:
        fields = {
            "id",
            "effect",
            "baseline_scorer",
            "candidate_scorer",
            "baseline_config_sha256",
            "candidate_config_sha256",
            "cases",
        }
        _object(comparison, fields, fields, "comparison")
        _token(comparison["id"])
        _require(comparison["id"] not in names, "duplicate_comparison")
        names.add(comparison["id"])
        _require(
            comparison["effect"] in {"scorer", "candidate_supply"}, "confounded_effect"
        )
        for key in ("baseline_scorer", "candidate_scorer"):
            _token(comparison[key])
        for key in ("baseline_config_sha256", "candidate_config_sha256"):
            value = comparison[key]
            _require(
                isinstance(value, str)
                and len(value) == 64
                and all(c in "0123456789abcdef" for c in value),
                "invalid_scorer_config_hash",
            )
        if comparison["effect"] == "candidate_supply":
            _require(
                comparison["baseline_scorer"] == comparison["candidate_scorer"]
                and comparison["baseline_config_sha256"]
                == comparison["candidate_config_sha256"],
                "confounded_supply",
            )
        _require(
            isinstance(comparison["cases"], list)
            and 1 <= len(comparison["cases"]) <= 2000,
            "invalid_cases",
        )
        case_ids = set()
        for case in comparison["cases"]:
            _validate_case(case, cutoff, label_cutoff)
            _require(case["id"] not in case_ids, "duplicate_case")
            case_ids.add(case["id"])
            baseline = {p["canonical_key"]: p for p in case["baseline"]}
            candidate = {p["canonical_key"]: p for p in case["candidate"]}
            if comparison["effect"] == "scorer":
                _require(
                    baseline.keys() == candidate.keys(), "different_scorer_universe"
                )
            _require(
                all(
                    {k: v for k, v in baseline[key].items() if k != "final_rank"}
                    == {k: v for k, v in candidate[key].items() if k != "final_rank"}
                    for key in baseline.keys() & candidate.keys()
                ),
                "different_comparison_metadata",
            )


def _validate_case(case: dict, cutoff: datetime, label_cutoff: datetime) -> None:
    fields = {
        "id",
        "cluster",
        "slices",
        "eligible",
        "features_at",
        "labels_at",
        "policy",
        "labels",
        "baseline",
        "candidate",
    }
    _object(case, fields, fields, "case")
    _token(case["id"])
    _token(case["cluster"])
    _require(type(case["eligible"]) is bool, "invalid_eligibility")
    _require(
        isinstance(case["slices"], list)
        and all(s in REQUIRED_SLICES for s in case["slices"]),
        "invalid_slices",
    )
    _require(
        _time(case["features_at"]) <= cutoff < _time(case["labels_at"]) <= label_cutoff,
        "future_feature_or_label_leak",
    )
    policy = case["policy"]
    fields = {"hidden", "already_seen", "seen", "interested", "topic_less"}
    _object(policy, fields, fields, "policy")
    for name in fields - {"topic_less"}:
        _require(
            isinstance(policy[name], list) and len(policy[name]) <= 2000,
            "invalid_policy_keys",
        )
        for key in policy[name]:
            _token(key)
    _require(
        isinstance(policy["topic_less"], dict) and len(policy["topic_less"]) <= 2000,
        "invalid_topic_less",
    )
    for key, value in policy["topic_less"].items():
        _token(key)
        _token(value)
    _require(
        isinstance(case["labels"], dict) and len(case["labels"]) <= 5000,
        "invalid_labels",
    )
    for key, label in case["labels"].items():
        _token(key)
        _number(label, 0, 3)
    for variant in ("baseline", "candidate"):
        papers = case[variant]
        _require(
            isinstance(papers, list) and len(papers) <= 2000, "invalid_ranked_list"
        )
        keys = set()
        for rank, paper in enumerate(papers, 1):
            fields = {
                "canonical_key",
                "final_rank",
                "title",
                "source",
                "topic",
                "published_at",
                "collected_at",
                "generated_at",
            }
            _object(paper, fields, fields, "bibliographic_paper")
            _token(paper["canonical_key"])
            _require(paper["canonical_key"] not in keys, "duplicate_paper")
            keys.add(paper["canonical_key"])
            _require(
                type(paper["final_rank"]) is int and paper["final_rank"] == rank,
                "invalid_final_rank",
            )
            for name in ("title", "source", "topic"):
                _require(
                    isinstance(paper[name], str) and 0 < len(paper[name]) <= 500,
                    "invalid_bibliographic_text",
                )
            _require(
                _time(paper["published_at"])
                <= _time(paper["collected_at"])
                <= _time(paper["generated_at"])
                <= cutoff,
                "future_metadata_leak",
            )


def project_case(case: dict, variant: str, *, limit: int = 5) -> list[dict]:
    """Freeze the production K12 reserve before current serve-time suppression.

    Validated input is in final-rank order. Candidates beyond rank12 remain in
    the supply universe, but cannot refill a delivery after a current hide.
    """
    state = case["policy"]
    policy = RecommendationPolicy(
        incarnation="offline-fixture",
        hidden=frozenset(state["hidden"]),
        already_seen=frozenset(state["already_seen"]),
        seen=frozenset(state["seen"]),
        interested=frozenset(state["interested"]),
        topic_less=state["topic_less"],
    )
    return policy.project(case[variant][:12], limit=limit)


def score_case(case: dict, variant: str, *, cutoff: str, k: int = 5) -> dict:
    """Unconditional recall includes labeled positives absent from supplied candidates.

    Undefined denominators are None, never manufactured zeros or improvements.
    Unjudged candidates also make relevance metrics unknown, not irrelevant.
    Supply diagnostics retain the full candidate universe, not just the frozen
    delivery reserve; only projected reserve items receive visible credit.
    """
    visible = project_case(case, variant, limit=k)
    labels = case["labels"]
    positives = {key for key, label in labels.items() if label > 0}
    supplied = {p["canonical_key"] for p in case[variant]}
    keys = [p["canonical_key"] for p in visible]
    hits = len(set(keys) & positives)
    fully_judged = supplied <= labels.keys()
    gains = [
        (2 ** labels.get(key, 0) - 1) / math.log2(rank + 2)
        for rank, key in enumerate(keys)
    ]
    ideal = sum(
        (2**label - 1) / math.log2(rank + 2)
        for rank, label in enumerate(sorted(labels.values(), reverse=True)[:k])
    )
    conditional = positives & supplied
    result = {
        "ndcg": sum(gains) / ideal if ideal and fully_judged else None,
        "recall": hits / len(positives) if positives and fully_judged else None,
        "candidate_conditional_recall": hits / len(conditional)
        if conditional and fully_judged
        else None,
        "candidate_positive_coverage": len(conditional) / len(positives)
        if positives
        else None,
        "coverage": float(bool(visible)) if case["eligible"] else None,
        "mrr": next(
            (1 / (i + 1) for i, key in enumerate(keys) if labels.get(key, 0) > 0), 0.0
        )
        if fully_judged
        else None,
        "source_diversity": len({p["source"] for p in visible}) / len(visible)
        if visible
        else None,
        "topic_diversity": len({p["topic"] for p in visible}) / len(visible)
        if visible
        else None,
        "visible_count": len(visible),
        "positive_count": len(positives),
        "candidate_positive_count": len(conditional),
        "judged_candidate_count": len(supplied & labels.keys()),
        "candidate_count": len(supplied),
        "visible_keys": keys,
    }
    for field in ("published_at", "collected_at", "generated_at"):
        result[field + "_age_days"] = (
            mean(
                (_time(cutoff) - _time(p[field])).total_seconds() / 86400
                for p in visible
            )
            if visible
            else None
        )
    return result


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def paired_interval(rows: list[dict], metric: str, *, relative: bool = False) -> dict:
    """Equal-weight cluster paired percentile bootstrap (95%), deterministic PRNG.

    Multiple user-days in a cluster are averaged before resampling clusters.
    Missing paired observations are reported and cannot produce a passing gate.
    """
    clusters: dict[str, list[tuple[float, float]]] = defaultdict(list)
    missing = 0
    for row in rows:
        baseline, candidate = row["baseline"][metric], row["candidate"][metric]
        if baseline is None or candidate is None:
            missing += 1
        else:
            clusters[row["cluster"]].append((baseline, candidate))
    pairs = [
        (mean(p[0] for p in values), mean(p[1] for p in values))
        for _, values in sorted(clusters.items())
    ]
    result = {
        "clusters": len(pairs),
        "paired_cases": len(rows) - missing,
        "unknown_cases": missing,
        "baseline": None,
        "candidate": None,
        "delta": None,
        "ci95": None,
        "scale": "relative" if relative else "absolute",
    }
    if not pairs:
        return result
    baseline, candidate = mean(p[0] for p in pairs), mean(p[1] for p in pairs)
    result.update(baseline=baseline, candidate=candidate)
    if relative and baseline == 0:
        result["reason"] = "zero_baseline_preregistered_inconclusive"
        return result
    result["delta"] = (
        (candidate - baseline) / baseline if relative else candidate - baseline
    )
    rng = random.Random(CONFIG["seed"])
    deltas = []
    for _ in range(CONFIG["bootstrap_samples"]):
        sample = rng.choices(pairs, k=len(pairs))
        b, c = mean(p[0] for p in sample), mean(p[1] for p in sample)
        if relative and b == 0:
            result["reason"] = "zero_baseline_bootstrap_inconclusive"
            return result
        deltas.append((c - b) / b if relative else c - b)
    result["ci95"] = [_percentile(deltas, 0.025), _percentile(deltas, 0.975)]
    return result


def _gate(interval: dict, floor: float, minimum: int) -> str:
    if (
        interval["ci95"] is None
        or interval["unknown_cases"]
        or interval["clusters"] < minimum
    ):
        return "inconclusive"
    return "pass" if interval["ci95"][0] >= floor else "fail"


def evaluate_manifest(manifest: dict, *, root: str | Path | None = None) -> dict:
    """Validate receipts and evaluate lists. This offline API never authorizes rollout."""
    validate_manifest(manifest, root=root)
    results = []
    hard_failures = []
    if any(manifest["safety_violations"].values()):
        hard_failures.append("safety_violations")
    for comparison in manifest["comparisons"]:
        by_k = {}
        for k in (5, 12):
            rows = [
                {
                    "cluster": case["cluster"],
                    "slices": case["slices"],
                    "case_id": case["id"],
                    **{
                        variant: score_case(
                            case, variant, cutoff=manifest["cutoff"], k=k
                        )
                        for variant in ("baseline", "candidate")
                    },
                }
                for case in comparison["cases"]
            ]
            metrics = {
                metric: paired_interval(rows, metric, relative=(metric == "ndcg"))
                for metric in (
                    "ndcg",
                    "recall",
                    "coverage",
                    "candidate_conditional_recall",
                    "candidate_positive_coverage",
                    "mrr",
                    "source_diversity",
                    "topic_diversity",
                    "published_at_age_days",
                    "collected_at_age_days",
                    "generated_at_age_days",
                )
            }
            by_k[str(k)] = {"metrics": metrics, "cases": rows}
        primary = by_k["5"]["metrics"]
        gates = {
            name: _gate(
                primary[name],
                CONFIG["ndcg_relative_floor"]
                if name == "ndcg"
                else CONFIG["recall_coverage_floor"],
                CONFIG["min_clusters"],
            )
            for name in ("ndcg", "recall", "coverage")
        }
        slices = {}
        for slice_name in REQUIRED_SLICES:
            rows = [row for row in by_k["5"]["cases"] if slice_name in row["slices"]]
            slice_metrics = {
                metric: paired_interval(rows, metric)
                for metric in ("ndcg", "recall", "coverage")
            }
            statuses = []
            for interval in slice_metrics.values():
                if (
                    interval["clusters"] < CONFIG["min_slice_clusters"]
                    or interval["unknown_cases"]
                    or interval["delta"] is None
                ):
                    statuses.append("inconclusive")
                else:
                    statuses.append(
                        "pass"
                        if interval["delta"] >= CONFIG["slice_drop_floor"]
                        else "fail"
                    )
            status = (
                "fail"
                if "fail" in statuses
                else "inconclusive"
                if "inconclusive" in statuses
                else "pass"
            )
            slices[slice_name] = {"status": status, "metrics": slice_metrics}
        statuses = list(gates.values()) + [s["status"] for s in slices.values()]
        if comparison["effect"] == "candidate_supply":
            relevance = primary["ndcg"]
            supply = by_k["5"]["metrics"]["candidate_positive_coverage"]
            gain = any(
                m["ci95"] is not None
                and not m["unknown_cases"]
                and m["clusters"] >= CONFIG["min_clusters"]
                and m["ci95"][0] > 0
                for m in (relevance, supply)
            )
            gates["source_utility"] = "pass" if gain else "inconclusive"
            statuses.append(gates["source_utility"])
        status = (
            "fail"
            if "fail" in statuses
            else "inconclusive"
            if "inconclusive" in statuses
            else "pass"
        )
        if status == "fail":
            hard_failures.append("top5_gate:" + comparison["id"])
        results.append(
            {
                "id": comparison["id"],
                "effect": comparison["effect"],
                "status": status,
                "denominators": {
                    "profile_cases": len(comparison["cases"]),
                    "profile_clusters": len(
                        {case["cluster"] for case in comparison["cases"]}
                    ),
                    "eligible_cases": sum(
                        case["eligible"] for case in comparison["cases"]
                    ),
                    "visible_eligible_cases": {
                        variant: sum(
                            row[variant]["coverage"] == 1 for row in by_k["5"]["cases"]
                        )
                        for variant in ("baseline", "candidate")
                    },
                    "actual_active_users": None,
                    "actual_visible_user_days": None,
                },
                "primary_gates": gates,
                "slices": slices,
                "at_k": by_k,
            }
        )
    reasons = [
        "offline_only_no_operational_qualification",
        "independent_judgment_provenance_unverified",
        "source_owner_transport_cost_qualification_required",
        "baseline_capture_authenticity_unverified",
        "sample_power_and_exposure_denominators_unverified",
    ]
    if manifest["evidence_kind"] == "synthetic_correctness":
        reasons.insert(0, "fixture_only_never_promotes")
    reasons.extend(hard_failures)
    status = "fail" if hard_failures else "inconclusive"
    return {
        "schema": SCHEMA,
        "status": status,
        "promotion": False,
        "consistency": "passed",
        "local_implementation_qualification": "requires_separate_test_evidence",
        "offline_quality_status": "fail"
        if hard_failures
        else "inconclusive"
        if any(c["status"] == "inconclusive" for c in results)
        else "pass",
        "evidence_kind": manifest["evidence_kind"],
        "scope": manifest["scope"],
        "bindings": manifest["bindings"],
        "cutoff": manifest["cutoff"],
        "label_cutoff": manifest["label_cutoff"],
        "provenance_claims_unverified": manifest["provenance"],
        "nonpromotion_reasons": reasons,
        "safety_violations": manifest["safety_violations"],
        "comparisons": results,
        "operational_metrics": {"observed": None, "required": OPERATIONAL_REQUIREMENTS},
        "limitations": [
            "No historical current-v2 baseline capture is inferred from these lists.",
            "Hashes prove integrity, not independent labels, temporal provenance or real-user outcomes.",
            "Minimum cluster counts are screening rules, not a statistical power calculation.",
            "Public profile-paper pairs do not establish real-user personalization benefit.",
            "At12 is secondary and cannot compensate for a Top5 regression.",
            "Safety counts are supplied evidence, not an operational audit.",
        ],
    }
