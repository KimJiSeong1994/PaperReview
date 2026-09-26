"""Authored synthetic correctness cases; not public relevance or user benefit evidence."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

from src import recommendation_evaluation as evaluation
from src.recommendation_state import RecommendationPolicy

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/recommendation_eval/public_fixture_manifest.json"


def paper(number: int, rank: int) -> dict:
    return {
        "canonical_key": f"synthetic:{number}",
        "final_rank": rank,
        "title": f"SYNTHETIC item {number}, not a real paper",
        "source": "synthetic",
        "topic": f"topic-{number % 3}",
        "published_at": "2020-01-01T00:00:00Z",
        "collected_at": "2026-09-20T00:00:00Z",
        "generated_at": "2026-09-24T00:00:00Z",
    }


def case(order=range(1, 13)) -> dict:
    papers = [paper(number, rank) for rank, number in enumerate(order, 1)]
    return {
        "id": "synthetic-case",
        "cluster": "synthetic-cluster",
        "slices": list(evaluation.REQUIRED_SLICES),
        "eligible": True,
        "features_at": "2026-09-24T00:00:00Z",
        "labels_at": "2026-09-26T00:00:00Z",
        "policy": {
            "hidden": [],
            "already_seen": [],
            "seen": [],
            "interested": [],
            "topic_less": {},
        },
        "labels": {p["canonical_key"]: int(i % 2 == 0) for i, p in enumerate(papers)},
        "baseline": papers,
        "candidate": deepcopy(papers),
    }


def rebind(manifest: dict) -> dict:
    manifest["config"] = deepcopy(evaluation.CONFIG)
    manifest["bindings"] = {
        "code": {
            p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
            for p in (
                "src/recommendation_evaluation.py",
                "src/recommendation_state.py",
                "scripts/evaluate_daily_recommendations.py",
            )
        },
        "config_sha256": evaluation.digest(manifest["config"]),
        "input_sha256": evaluation.digest(
            {
                k: manifest[k]
                for k in (
                    "scope",
                    "evidence_kind",
                    "cutoff",
                    "label_cutoff",
                    "comparisons",
                    "safety_violations",
                )
            }
        ),
        "protocol_sha256": evaluation.digest(manifest["provenance"]),
    }
    return manifest


def manifest_for(sample: dict, count: int = 30) -> dict:
    manifest = json.loads(FIXTURE.read_text())
    comparison = manifest["comparisons"][0]
    comparison["cases"] = []
    for i in range(count):
        copied = deepcopy(sample)
        copied.update(id=f"synthetic-case-{i}", cluster=f"synthetic-cluster-{i}")
        comparison["cases"].append(copied)
    return rebind(manifest)


@pytest.fixture
def small_bootstrap(monkeypatch):
    # Bound test runtime only; each test re-freezes its own explicitly synthetic config.
    monkeypatch.setitem(evaluation.CONFIG, "bootstrap_samples", 40)


@pytest.mark.parametrize("size", [0, 1, 4, 5, 8, 12])
@pytest.mark.parametrize("suppression_count", range(7))
@pytest.mark.parametrize("action", ["hidden", "already_seen", "seen"])
def test_126_synthetic_projection_and_recall_scenarios(size, suppression_count, action):
    sample = case(range(1, size + 1))
    blocked = [f"synthetic:{i}" for i in range(1, suppression_count + 1)]
    sample["policy"][action] = blocked
    projected = evaluation.project_case(sample, "candidate")
    eligible = [
        p
        for p in sample["candidate"]
        if action == "seen" or p["canonical_key"] not in blocked
    ]
    assert [p["canonical_key"] for p in projected] == [
        p["canonical_key"] for p in eligible[:5]
    ]
    assert [p["final_rank"] for p in projected] == [
        p["final_rank"] for p in eligible[:5]
    ]
    assert [p["display_position"] for p in projected] == list(
        range(1, len(projected) + 1)
    )
    assert all(
        p["seen"] == (action == "seen" and p["canonical_key"] in blocked)
        for p in projected
    )
    scored = evaluation.score_case(sample, "candidate", cutoff="2026-09-25T00:00:00Z")
    positives = {key for key, label in sample["labels"].items() if label > 0}
    expected_recall = (
        len(positives & {p["canonical_key"] for p in eligible[:5]}) / len(positives)
        if positives
        else None
    )
    assert scored["recall"] == expected_recall
    ideal = sum(1 / math.log2(i + 2) for i in range(min(5, len(positives))))
    dcg = sum(
        sample["labels"][p["canonical_key"]] / math.log2(i + 2)
        for i, p in enumerate(eligible[:5])
    )
    assert scored["ndcg"] == (dcg / ideal if ideal else None)


def test_shared_projection_is_called_not_reimplemented(monkeypatch):
    calls = []
    original = RecommendationPolicy.project

    def observed(self, papers, *, limit=5):
        calls.append(limit)
        return original(self, papers, limit=limit)

    monkeypatch.setattr(RecommendationPolicy, "project", observed)
    sample = case()
    sample["policy"]["hidden"] = ["synthetic:1"]
    evaluation.score_case(sample, "baseline", cutoff="2026-09-25T00:00:00Z", k=5)
    evaluation.score_case(sample, "candidate", cutoff="2026-09-25T00:00:00Z", k=12)
    assert calls == [5, 12]


@pytest.mark.parametrize("action", ["hidden", "already_seen"])
@pytest.mark.parametrize("suppressed_count", [0, 11, 12])
@pytest.mark.parametrize("k", [5, 12])
def test_frozen_reserve_matches_validated_delivery_loader(
    tmp_path, action, suppressed_count, k
):
    from src.recommendation_candidates import normalize_candidate
    from src.recommendations_artifacts import (
        DELIVERY_SCHEMA,
        POLICY_VERSION,
        load_recommendation_artifact,
        read_delivery,
        validate_delivery,
    )

    # Reversed identities catch accidental identity/score sorting. Ranks remain
    # the original ordered final ranks, including the unservable supply tail.
    sample = case(range(17, 0, -1))
    delivery_items = []
    for candidate in sample["candidate"]:
        normalized = normalize_candidate({"title": candidate["title"], "year": 2020})
        candidate["canonical_key"] = normalized.canonical_key
        delivery_items.append(
            {
                **normalized.metadata,
                "canonical_key": normalized.canonical_key,
                "final_rank": candidate["final_rank"],
                "score": float(candidate["final_rank"]),
            }
        )
    sample["baseline"] = deepcopy(sample["candidate"])
    sample["labels"] = {
        p["canonical_key"]: int(p["final_rank"] > 12) for p in sample["candidate"]
    }
    sample["policy"][action] = [
        p["canonical_key"] for p in sample["candidate"][:suppressed_count]
    ]
    cutoff = "2026-09-25T00:00:00Z"
    now = evaluation._time(cutoff)
    policy = RecommendationPolicy(
        incarnation="offline-fixture",
        **{action: frozenset(sample["policy"][action])},
    )
    raw = {
        "schema": DELIVERY_SCHEMA,
        "producer": "common_local",
        "account_incarnation": policy.incarnation,
        "run_id": "synthetic-reserve",
        "run_at": cutoff,
        "cutoff": cutoff,
        "policy_version": POLICY_VERSION,
        "code_hash": "0" * 64,
        "config_hash": "0" * 64,
        "input_manifest_hash": "0" * 64,
        "scoring_mode": "v2",
        "ranker_version": "synthetic-test",
        "status": "ready",
        "source_statuses": {"local_public": "ready"},
        "degraded_reasons": [],
        "items": delivery_items[:12],
    }
    validate_delivery(raw, incarnation=policy.incarnation, now=now)
    owner = tmp_path / policy.incarnation
    owner.mkdir()
    (owner / "synthetic-reserve.json").write_text(json.dumps(raw), encoding="utf-8")
    loaded = read_delivery(tmp_path, policy.incarnation, now=now)
    assert loaded is not None
    served = load_recommendation_artifact(
        tmp_path, policy.incarnation, 5, policy=policy, now=now
    )
    reserve = policy.project(loaded["items"], limit=12)
    expected = served["items"] if k == 5 else reserve
    projected = evaluation.project_case(sample, "candidate", limit=k)
    assert [(p["canonical_key"], p["final_rank"]) for p in projected] == [
        (p["canonical_key"], p["final_rank"]) for p in expected
    ]
    assert served["total_count"] == len(reserve)
    scored = evaluation.score_case(sample, "candidate", cutoff=cutoff, k=k)
    assert scored["candidate_count"] == 17
    assert scored["candidate_positive_count"] == 5
    assert scored["candidate_positive_coverage"] == 1
    assert scored["ndcg"] == 0
    assert scored["recall"] == 0
    assert scored["candidate_conditional_recall"] == 0
    assert scored["mrr"] == 0
    assert all(p["final_rank"] <= 12 for p in projected)
    if suppressed_count == 12:
        assert served["items"] == reserve == projected == []
        assert scored["visible_count"] == 0
        assert scored["coverage"] == 0


def test_top12_improvement_cannot_rescue_visible_top5(small_bootstrap):
    sample = case(list(range(1, 6)) + list(range(11, 18)) + list(range(6, 11)))
    sample["labels"] = {
        f"synthetic:{i}": 1 if i <= 5 else 3 if i <= 10 else 0 for i in range(1, 18)
    }
    order = list(range(11, 16)) + list(range(6, 11)) + list(range(1, 6)) + [16, 17]
    sample["candidate"] = [paper(i, rank) for rank, i in enumerate(order, 1)]
    result = evaluation.evaluate_manifest(manifest_for(sample))
    comparison = result["comparisons"][0]
    secondary = comparison["at_k"]["12"]["metrics"]
    for metric in ("ndcg", "recall", "coverage"):
        assert evaluation._gate(secondary[metric], -0.02, 30) == "pass"
    assert secondary["ndcg"]["delta"] > 0
    assert secondary["recall"]["delta"] > 0
    assert comparison["primary_gates"]["ndcg"] == "fail"
    assert comparison["primary_gates"]["recall"] == "fail"
    assert result["promotion"] is False
    assert result["status"] == "fail"
    assert any(
        reason.startswith("top5_gate:") for reason in result["nonpromotion_reasons"]
    )


def test_unconditional_recall_includes_outside_candidates():
    sample = case([1])
    sample["labels"] = {"synthetic:1": 1, "synthetic:outside": 1}
    scored = evaluation.score_case(sample, "baseline", cutoff="2026-09-25T00:00:00Z")
    assert scored["recall"] == 0.5
    assert scored["candidate_conditional_recall"] == 1
    assert scored["candidate_positive_coverage"] == 0.5


def test_negative_topic_is_not_hard_suppression():
    sample = case([1, 2])
    sample["policy"]["topic_less"] = {"synthetic:1": "topic-1"}
    assert (
        evaluation.project_case(sample, "candidate")[0]["canonical_key"]
        == "synthetic:1"
    )


@pytest.mark.parametrize("kind", ["hidden", "already_seen"])
def test_refill_retains_reserve_order(kind):
    sample = case([6, 5, 4, 3, 2, 1])
    sample["policy"][kind] = ["synthetic:6"]
    assert [
        p["canonical_key"] for p in evaluation.project_case(sample, "candidate")
    ] == [f"synthetic:{i}" for i in [5, 4, 3, 2, 1]]


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (
            lambda s: s["candidate"].append(deepcopy(s["candidate"][0])),
            "duplicate_paper",
        ),
        (lambda s: s["candidate"][0].update(final_rank=0), "invalid_final_rank"),
        (lambda s: s["candidate"][0].update(final_rank=True), "invalid_final_rank"),
        (
            lambda s: s["candidate"][0].update(notes="must not enter eval"),
            "fields_bibliographic_paper",
        ),
        (lambda s: s.update(query="private query"), "fields_case"),
        (lambda s: s["labels"].update({"synthetic:1": -1}), "invalid_finite_number"),
        (lambda s: s["labels"].update({"synthetic:1": 4}), "invalid_finite_number"),
        (lambda s: s["labels"].update({"synthetic:1": True}), "invalid_finite_number"),
        (
            lambda s: s.update(features_at="2026-09-26T00:00:00Z"),
            "future_feature_or_label_leak",
        ),
        (
            lambda s: s.update(labels_at="2026-09-24T00:00:00Z"),
            "future_feature_or_label_leak",
        ),
        (
            lambda s: s.update(labels_at="2026-10-04T00:00:00Z"),
            "future_feature_or_label_leak",
        ),
        (lambda s: s.update(features_at="2026-09-24"), "naive_time"),
        (
            lambda s: s["candidate"][0].update(published_at="2027-01-01T00:00:00Z"),
            "future_metadata_leak",
        ),
        (
            lambda s: s["candidate"][0].update(collected_at="2027-01-01T00:00:00Z"),
            "future_metadata_leak",
        ),
        (
            lambda s: s["candidate"][0].update(generated_at="2027-01-01T00:00:00Z"),
            "future_metadata_leak",
        ),
    ],
)
def test_rejects_unsafe_cases(mutation, reason):
    sample = case()
    mutation(sample)
    manifest = manifest_for(sample, 1)
    with pytest.raises(evaluation.EvaluationError, match=reason):
        evaluation.validate_manifest(manifest)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_labels_and_ranks(value):
    sample = case()
    sample["labels"]["synthetic:1"] = value
    with pytest.raises(evaluation.EvaluationError, match="finite"):
        evaluation._validate_case(
            sample,
            evaluation._time("2026-09-25T00:00:00Z"),
            evaluation._time("2026-10-03T00:00:00Z"),
        )
    sample = case()
    sample["candidate"][0]["final_rank"] = value
    with pytest.raises(evaluation.EvaluationError, match="rank"):
        evaluation._validate_case(
            sample,
            evaluation._time("2026-09-25T00:00:00Z"),
            evaluation._time("2026-10-03T00:00:00Z"),
        )


@pytest.mark.parametrize(
    "path",
    [
        "../users.db",
        "data/recommendation_eval/../../users.db",
        "/etc/passwd",
        "data/raw/papers.json",
    ],
)
def test_paths_cannot_escape_eval_directory(path):
    with pytest.raises(evaluation.EvaluationError):
        evaluation.load_manifest(path)


def test_symlink_manifest_is_rejected(tmp_path):
    folder = tmp_path / "data/recommendation_eval"
    folder.mkdir(parents=True)
    (folder / "fixture.json").symlink_to(FIXTURE)
    with pytest.raises(evaluation.EvaluationError, match="symlink"):
        evaluation.load_manifest("data/recommendation_eval/fixture.json", root=tmp_path)


@pytest.mark.parametrize("raw", ['{"x":NaN}', '{"x":Infinity}', '{"x":1,"x":2}', "[]"])
def test_invalid_json_payload(tmp_path, raw):
    path = tmp_path / "data/recommendation_eval/invalid.json"
    path.parent.mkdir(parents=True)
    path.write_text(raw)
    with pytest.raises(evaluation.EvaluationError):
        evaluation.load_manifest("data/recommendation_eval/invalid.json", root=tmp_path)


@pytest.mark.parametrize(
    "binding", ["config_sha256", "input_sha256", "protocol_sha256"]
)
def test_tampered_receipts_rejected(binding):
    manifest = manifest_for(case(), 1)
    manifest["bindings"][binding] = "0" * 64
    with pytest.raises(evaluation.EvaluationError, match="hash_mismatch"):
        evaluation.validate_manifest(manifest)


def test_code_and_policy_receipts_rejected():
    manifest = manifest_for(case(), 1)
    manifest["bindings"]["code"]["src/recommendation_state.py"] = "0" * 64
    with pytest.raises(evaluation.EvaluationError, match="code_policy_hash_mismatch"):
        evaluation.validate_manifest(manifest)


def test_scorer_and_supply_effects_must_not_be_confounded():
    sample = case()
    sample["candidate"].pop()
    manifest = manifest_for(sample, 1)
    with pytest.raises(evaluation.EvaluationError, match="different_scorer_universe"):
        evaluation.validate_manifest(manifest)
    manifest["comparisons"][0]["effect"] = "candidate_supply"
    with pytest.raises(evaluation.EvaluationError, match="confounded_supply"):
        evaluation.validate_manifest(rebind(manifest))
    comparison = manifest["comparisons"][0]
    comparison["candidate_scorer"] = comparison["baseline_scorer"]
    comparison["candidate_config_sha256"] = comparison["baseline_config_sha256"]
    evaluation.validate_manifest(rebind(manifest))


def test_candidate_supply_has_separate_coverage_gain(small_bootstrap):
    sample = case([1, 2])
    sample["labels"] = {"synthetic:1": 1, "synthetic:2": 1}
    sample["baseline"] = sample["baseline"][:1]
    manifest = manifest_for(sample)
    comparison = manifest["comparisons"][0]
    comparison["effect"] = "candidate_supply"
    comparison["candidate_scorer"] = comparison["baseline_scorer"]
    comparison["candidate_config_sha256"] = comparison["baseline_config_sha256"]
    result = evaluation.evaluate_manifest(rebind(manifest))
    assert result["comparisons"][0]["primary_gates"]["source_utility"] == "pass"
    assert not result["promotion"]


def test_bootstrap_clusters_not_user_days_and_deterministic(small_bootstrap):
    rows = [
        {"cluster": "a", "baseline": {"recall": 0.2}, "candidate": {"recall": 0.6}}
    ] * 50
    rows += [
        {"cluster": "b", "baseline": {"recall": 0.8}, "candidate": {"recall": 0.4}}
    ]
    first = evaluation.paired_interval(rows, "recall")
    assert first == evaluation.paired_interval(rows, "recall")
    assert first["clusters"] == 2
    assert first["paired_cases"] == 51
    assert first["delta"] == pytest.approx(0)
    assert first["ci95"][0] < 0 < first["ci95"][1]
    assert evaluation._gate(first, -0.02, 30) == "inconclusive"


@pytest.mark.parametrize(
    "condition",
    [
        "zero_baseline",
        "empty",
        "unjudged",
        "underpowered",
        "unknown_slice",
        "no_eligible",
    ],
)
def test_unknown_denominators_and_power_never_pass(condition, small_bootstrap):
    sample = case()
    count = 30
    if condition == "zero_baseline":
        sample["labels"] = {key: 0 for key in sample["labels"]}
    elif condition == "empty":
        sample = case([])
    elif condition == "unjudged":
        sample["labels"].pop("synthetic:1")
    elif condition == "underpowered":
        count = 2
    elif condition == "unknown_slice":
        sample["slices"] = ["en"]
    elif condition == "no_eligible":
        sample["eligible"] = False
    result = evaluation.evaluate_manifest(manifest_for(sample, count))
    assert result["offline_quality_status"] == "inconclusive"
    assert result["promotion"] is False


def test_zero_relative_baseline_cannot_be_invented_improvement(small_bootstrap):
    rows = [{"cluster": "a", "baseline": {"ndcg": 0.0}, "candidate": {"ndcg": 1.0}}]
    result = evaluation.paired_interval(rows, "ndcg", relative=True)
    assert result["delta"] is None
    assert result["ci95"] is None
    assert "zero_baseline" in result["reason"]


@pytest.mark.parametrize(
    "violation", ["rank", "privacy", "hide", "incarnation", "budget"]
)
def test_any_safety_violation_hard_fails(violation, small_bootstrap):
    manifest = manifest_for(case())
    manifest["safety_violations"][violation] = 1
    result = evaluation.evaluate_manifest(rebind(manifest))
    assert result["status"] == "fail"
    assert "safety_violations" in result["nonpromotion_reasons"]


@pytest.mark.parametrize(
    "judge", ["unknown", "checksum-only", "self-declared independent blind judge"]
)
def test_public_label_claim_does_not_qualify_itself(judge, small_bootstrap):
    manifest = manifest_for(case())
    manifest["evidence_kind"] = "public_bibliographic_judgments"
    manifest["provenance"]["judge"] = judge
    result = evaluation.evaluate_manifest(rebind(manifest))
    assert not result["promotion"]
    assert (
        "independent_judgment_provenance_unverified" in result["nonpromotion_reasons"]
    )
    assert result["operational_metrics"]["observed"] is None


def test_fixture_has_no_serving_schema_and_is_truthfully_synthetic():
    manifest = evaluation.load_manifest(FIXTURE)
    assert manifest["scope"] == "evaluation_only_non_serving"
    assert manifest["evidence_kind"] == "synthetic_correctness"
    assert "papers" not in manifest and "candidates" not in manifest
    assert all(
        p["canonical_key"].startswith("synthetic:")
        for c in manifest["comparisons"]
        for s in c["cases"]
        for p in s["candidate"]
    )


def test_cli_fixture_nonpromotion_and_validation_exit_codes():
    command = [
        sys.executable,
        str(ROOT / "scripts/evaluate_daily_recommendations.py"),
        "--manifest",
        str(FIXTURE),
        "--offline",
    ]
    validation = subprocess.run(
        command + ["--validate-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert validation.returncode == 0, validation.stdout
    assert json.loads(validation.stdout)["quality_evaluated"] is False
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 3, result.stdout
    report = json.loads(result.stdout)
    assert report["promotion"] is False
    assert "fixture_only_never_promotes" in report["nonpromotion_reasons"]


def test_cli_requires_offline_and_refuses_outside_path():
    command = [
        sys.executable,
        str(ROOT / "scripts/evaluate_daily_recommendations.py"),
        "--manifest",
        "../users.db",
    ]
    missing_flag = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=30
    )
    assert missing_flag.returncode == 2
    unsafe_path = subprocess.run(
        command + ["--offline"], cwd=ROOT, capture_output=True, text=True, timeout=30
    )
    assert unsafe_path.returncode == 2
    assert json.loads(unsafe_path.stdout)["status"] == "invalid"


def test_product_candidate_ingestion_rejects_eval_fixture(tmp_path):
    from src.recommendation_candidates import (
        CandidateValidationError,
        TrustedReceiverPolicy,
        load_candidate_snapshot,
    )

    with pytest.raises(CandidateValidationError, match="invalid_envelope"):
        load_candidate_snapshot(
            FIXTURE,
            root=FIXTURE.parent,
            final_root=tmp_path / "serving",
            policy=TrustedReceiverPolicy(
                "local_public",
                "public",
                "public-seeds-v1",
                public_source_qualified=True,
            ),
            now=evaluation._time("2026-09-25T00:00:00Z"),
        )


@pytest.mark.parametrize("effect", ["scorer", "candidate_supply"])
def test_common_candidates_cannot_change_metadata_during_comparison(effect):
    sample = case()
    sample["candidate"][0]["topic"] = "changed-feature"
    manifest = manifest_for(sample, 1)
    comparison = manifest["comparisons"][0]
    comparison["effect"] = effect
    comparison["candidate_scorer"] = comparison["baseline_scorer"]
    comparison["candidate_config_sha256"] = comparison["baseline_config_sha256"]
    with pytest.raises(
        evaluation.EvaluationError, match="different_comparison_metadata"
    ):
        evaluation.validate_manifest(rebind(manifest))


def test_cli_report_refuses_overwrite_and_escape(tmp_path, monkeypatch, capsys):
    from scripts import evaluate_daily_recommendations as cli

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    manifest = manifest_for(case(), 1)
    monkeypatch.setattr(cli, "load_manifest", lambda *args, **kwargs: manifest)
    report = tmp_path / "data/recommendation_eval/report.json"
    report.parent.mkdir(parents=True)
    args = [
        "--manifest",
        "data/recommendation_eval/fixture.json",
        "--offline",
        "--validate-only",
        "--report-out",
        "data/recommendation_eval/report.json",
    ]
    assert cli.main(args) == 0
    original = report.read_bytes()
    assert cli.main(args) == 2
    assert report.read_bytes() == original
    args[-1] = "data/recommendation_eval/../../outside.json"
    assert cli.main(args) == 2
    assert not (tmp_path / "outside.json").exists()
    capsys.readouterr()
