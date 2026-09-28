"""Fixed-pool Jev evaluator contracts; all scoring responses are synthetic."""

from __future__ import annotations

import copy
import json

import pytest

from src.search_eval import judged_replay
from src.search_eval import jev_eval


def make_input():
    return {
        "version": jev_eval.INPUT_VERSION,
        "evidence_kind": "synthetic",
        "queries": [
            {
                "query_id": "q1",
                "query": "Find papers about reliable query routing",
                "language": "en",
                "split": "development",
                "candidates": [
                    {
                        "paper_key": "wrong",
                        "title": "Unrelated paper",
                        "abstract": "A different topic.",
                    },
                    {
                        "paper_key": "right",
                        "title": "Reliable query routing",
                        "abstract": "A study of query routing reliability.",
                    },
                ],
                "judgments": [
                    {
                        "paper_key": "wrong",
                        "grade": 0,
                        "required": False,
                        "excluded": True,
                        "evidence_refs": ["synthetic:wrong"],
                        "author_id": None,
                        "reviewer_id": None,
                        "review_status": "synthetic",
                    },
                    {
                        "paper_key": "right",
                        "grade": 3,
                        "required": True,
                        "excluded": False,
                        "evidence_refs": ["synthetic:right"],
                        "author_id": None,
                        "reviewer_id": None,
                        "review_status": "synthetic",
                    },
                ],
            }
        ],
    }


def score_result(score, elapsed_ms=4, input_tokens=100):
    probabilities = {str(level): float(level == score) for level in range(4)}
    return {
        "model": jev_eval.MODEL,
        "rubric_version": jev_eval.RUBRIC_VERSION,
        "score": score,
        "confidence": 0.9,
        "probabilities": probabilities,
        "usage": {"input_tokens": input_tokens, "output_tokens": 12},
        "elapsed_ms": elapsed_ms,
    }


def write_input(tmp_path, value):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def mock_network(monkeypatch, by_key=None):
    calls = []
    by_key = by_key or {"wrong": 0, "right": 3}

    def score(query, candidate, *, api_key, client=None, timeout=10):
        calls.append((query, candidate["paper_key"], api_key, client, timeout))
        return score_result(by_key[candidate["paper_key"]])

    monkeypatch.setattr(jev_eval, "score_candidate", score)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-not-for-output")
    return calls


def run_network(tmp_path, monkeypatch, *, score_map=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = write_input(tmp_path, make_input())
    output = tmp_path / "network-report.json"
    calls = mock_network(monkeypatch, score_map)
    code = jev_eval.main(
        [
            "--input",
            str(source),
            "--out",
            str(output),
            "--allow-network",
            "--max-calls",
            "2",
        ]
    )
    assert code == 0
    return source, output, judged_replay.read_json(output), calls


def reseal_report(report):
    report.pop("report_hash", None)
    report["report_hash"] = judged_replay.digest(report)
    return report


def reseal_capture_and_report(report):
    capture = report["scoring_capture"]
    capture.pop("scoring_hash", None)
    capture["scoring_hash"] = judged_replay.digest(capture)
    return reseal_report(report)


def test_network_cli_fixed_pool_metrics_identity_and_replay_are_deterministic(
    tmp_path, monkeypatch, capsys
):
    source, network_path, network, calls = run_network(tmp_path, monkeypatch)
    assert len(calls) == 2
    assert all(
        call[2] == "test-key-not-for-output" and call[3] is None for call in calls
    )
    assert all(call[4] == 10.0 for call in calls)
    assert "test-key-not-for-output" not in network_path.read_text(encoding="utf-8")
    printed = capsys.readouterr().out
    assert "METRIC candidate_ndcg_at_10=" in printed
    assert "METRIC candidate_mrr_at_10=" in printed
    assert "METRIC candidate_recall_at_5=" in printed
    assert "METRIC candidate_recall_at_10=" in printed
    assert "METRIC candidate_wrong_paper_handoff_rate=" in printed

    query = network["per_query"][0]
    assert query["baseline_order"] == ["wrong", "right"]
    assert query["candidate_order"] == ["right", "wrong"]
    assert query["candidate_ids"] == ["wrong", "right"]
    assert {score["paper_key"] for score in query["scores"]} == {"wrong", "right"}
    assert query["candidate_metrics"] == judged_replay.score_identities(
        ["right", "wrong"],
        {
            "wrong": {"grade": 0, "required": False, "excluded": True},
            "right": {"grade": 3, "required": True, "excluded": False},
        },
    )
    assert query["candidate_metrics"]["nDCG@10"] == 1.0
    assert query["baseline_metrics"]["wrong_paper_handoff_rate"] == 1.0
    assert network["comparison_scope"] == "fixed_pool"
    assert network["baseline_definition"] == "input_order_not_production_ranker"
    assert network["timing_scope"] == "jev_scoring_only"
    assert network["model"] == "jev-1.13.0"
    assert (
        network["slices"]["language/en"]["candidate"]
        == network["aggregate"]["candidate"]
    )
    assert network["rubric_hash"] == jev_eval.RUBRIC_HASH
    assert network["promotion_eligible"] is False
    assert network["rollout_authority"] is False
    assert network["usage"]["input_tokens"] == 200
    assert network["usage"]["estimated_input_cost_usd"] == pytest.approx(0.0000084)
    assert network["scoring_capture"]["input_hash"] == judged_replay.digest(
        make_input()
    )

    replay_output = tmp_path / "replay-report.json"
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    monkeypatch.setattr(
        jev_eval,
        "score_candidate",
        lambda *args, **kwargs: pytest.fail("replay called scorer"),
    )
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(replay_output),
                "--replay",
                str(network_path),
            ]
        )
        == 0
    )
    replay = judged_replay.read_json(replay_output)
    capsys.readouterr()
    assert replay["execution_mode"] == "replay"
    assert replay["scoring_capture"] == network["scoring_capture"]
    assert replay["aggregate"] == network["aggregate"]
    assert replay["slices"] == network["slices"]
    assert replay["usage"] == network["usage"]
    assert replay["scoring_elapsed_ms"] == network["scoring_elapsed_ms"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["queries"].append(copy.deepcopy(value["queries"][0])),
        lambda value: value["queries"][0]["candidates"][1].update(paper_key="wrong"),
        lambda value: value["queries"][0]["judgments"].pop(),
        lambda value: value["queries"][0]["judgments"][1].update(paper_key="unknown"),
        lambda value: value["queries"][0]["judgments"][0].update(grade=True),
        lambda value: value["queries"][0]["judgments"][0].update(
            required=True, excluded=True
        ),
        lambda value: value["queries"][0]["candidates"][1].update(abstract=" "),
    ],
)
def test_invalid_input_is_rejected_before_calls_or_output(
    tmp_path, monkeypatch, mutation, capsys
):
    value = make_input()
    mutation(value)
    source = write_input(tmp_path, value)
    output = tmp_path / "invalid-report.json"
    calls = mock_network(monkeypatch)
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(output),
                "--allow-network",
                "--max-calls",
                "80",
            ]
        )
        == 2
    )
    assert calls == []
    assert not output.exists()
    capsys.readouterr()


def test_duplicate_json_keys_and_nonfinite_json_are_rejected_before_calls(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "invalid.json"
    source.write_text(
        '{"version":"jev-evaluation-input-v1","version":"jev-evaluation-input-v1"}',
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    calls = mock_network(monkeypatch)
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(output),
                "--allow-network",
                "--max-calls",
                "80",
            ]
        )
        == 2
    )
    assert calls == [] and not output.exists()

    source.write_text('{"not_finite":NaN}', encoding="utf-8")
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(output),
                "--allow-network",
                "--max-calls",
                "80",
            ]
        )
        == 2
    )
    assert calls == [] and not output.exists()
    capsys.readouterr()


def test_human_reviewed_requires_independent_provenance(tmp_path, monkeypatch, capsys):
    value = make_input()
    value["evidence_kind"] = "human_reviewed"
    for row in value["queries"][0]["judgments"]:
        row.update(review_status="reviewed", author_id="author", reviewer_id="reviewer")
    jev_eval.validate_input(value)
    value["queries"][0]["judgments"][1]["reviewer_id"] = "author"
    source = write_input(tmp_path, value)
    output = tmp_path / "report.json"
    calls = mock_network(monkeypatch)
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(output),
                "--allow-network",
                "--max-calls",
                "80",
            ]
        )
        == 2
    )
    assert calls == [] and not output.exists()
    capsys.readouterr()


def test_tied_scores_keep_input_order_and_synthetic_is_never_promotable(
    tmp_path, monkeypatch, capsys
):
    _, _, report, _ = run_network(
        tmp_path, monkeypatch, score_map={"wrong": 2, "right": 2}
    )
    assert report["per_query"][0]["candidate_order"] == ["wrong", "right"]
    assert report["promotion_eligible"] is False
    assert report["evidence_kind"] == "synthetic"
    assert report["grade_provenance"]["human_authentication_claimed"] is False
    assert (
        report["grade_provenance"]["judgment_sources"][0]["review_status"]
        == "synthetic"
    )
    capsys.readouterr()


def test_max_calls_is_preflight_and_network_is_never_implicit(
    tmp_path, monkeypatch, capsys
):
    source = write_input(tmp_path, make_input())
    output = tmp_path / "report.json"
    calls = mock_network(monkeypatch)
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(output),
                "--allow-network",
                "--max-calls",
                "1",
            ]
        )
        == 2
    )
    assert calls == [] and not output.exists()
    with pytest.raises(SystemExit):
        jev_eval.main(["--input", str(source), "--out", str(output)])
    assert calls == [] and not output.exists()
    capsys.readouterr()


def test_total_deadline_bounds_call_and_failure_writes_no_report(
    tmp_path, monkeypatch, capsys
):
    source = write_input(tmp_path, make_input())
    output = tmp_path / "expired.json"
    clock = [0.0]
    monkeypatch.setattr(jev_eval.time, "monotonic", lambda: clock[0])
    calls = []

    def late_score(query, candidate, **kwargs):
        calls.append(kwargs["timeout"])
        clock[0] = 11.0
        return score_result(0)

    monkeypatch.setattr(jev_eval, "score_candidate", late_score)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(output),
                "--allow-network",
                "--max-calls",
                "2",
                "--timeout",
                "30",
                "--total-deadline",
                "10",
            ]
        )
        == 2
    )
    assert calls == [10.0]
    assert not output.exists()
    capsys.readouterr()


def test_malformed_response_fails_without_success_report(tmp_path, monkeypatch, capsys):
    source = write_input(tmp_path, make_input())
    output = tmp_path / "malformed.json"
    mock_network(monkeypatch)
    monkeypatch.setattr(
        jev_eval, "score_candidate", lambda *args, **kwargs: {"model": jev_eval.MODEL}
    )
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(output),
                "--allow-network",
                "--max-calls",
                "2",
            ]
        )
        == 2
    )
    assert not output.exists()
    capsys.readouterr()


def test_provider_error_is_sanitized_and_writes_no_success_report(
    tmp_path, monkeypatch, capsys
):
    source = write_input(tmp_path, make_input())
    output = tmp_path / "provider-error.json"
    mock_network(monkeypatch)

    def fail_with_sensitive_error(*args, **kwargs):
        raise RuntimeError("provider detail test-key-not-for-output")

    monkeypatch.setattr(jev_eval, "score_candidate", fail_with_sensitive_error)
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(output),
                "--allow-network",
                "--max-calls",
                "2",
            ]
        )
        == 2
    )
    error = capsys.readouterr().err
    assert "scoring request failed" in error
    assert "provider detail" not in error
    assert "test-key-not-for-output" not in error
    assert not output.exists()


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("TypeSafe authentication failed", "TypeSafe authentication failed"),
        ("TypeSafe rate limit exceeded", "TypeSafe rate limit exceeded"),
        ("test-key-not-for-output", "scoring request failed"),
    ],
)
def test_client_errors_keep_only_safe_diagnostics(
    tmp_path, monkeypatch, capsys, message, expected
):
    source = write_input(tmp_path, make_input())
    output = tmp_path / "failed.json"
    mock_network(monkeypatch)

    def fail(*args, **kwargs):
        raise jev_eval.JevError(message)

    monkeypatch.setattr(jev_eval, "score_candidate", fail)
    result = jev_eval.main(
        [
            "--input",
            str(source),
            "--out",
            str(output),
            "--allow-network",
            "--max-calls",
            "2",
        ]
    )
    assert result == 2
    error = capsys.readouterr().err
    assert expected in error
    assert "test-key-not-for-output" not in error
    assert not output.exists()


def test_replay_rejects_malformed_and_rebound_captures(tmp_path, monkeypatch, capsys):
    source, original_path, original, _ = run_network(tmp_path, monkeypatch)
    malformed = copy.deepcopy(original)
    malformed["scoring_capture"]["results"][0]["result"]["unexpected"] = 1
    malformed_path = tmp_path / "malformed-replay.json"
    malformed_path.write_text(
        json.dumps(reseal_capture_and_report(malformed)), encoding="utf-8"
    )
    malformed_output = tmp_path / "malformed-out.json"
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(malformed_output),
                "--replay",
                str(malformed_path),
            ]
        )
        == 2
    )
    assert not malformed_output.exists()

    rebound = copy.deepcopy(original)
    capture = rebound["scoring_capture"]
    capture["input_hash"] = judged_replay.digest("different input")
    capture.pop("scoring_hash")
    capture["scoring_hash"] = judged_replay.digest(capture)
    rebound_path = tmp_path / "rebound-replay.json"
    rebound_path.write_text(json.dumps(reseal_report(rebound)), encoding="utf-8")
    rebound_output = tmp_path / "rebound-out.json"
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(rebound_output),
                "--replay",
                str(rebound_path),
            ]
        )
        == 2
    )
    assert not rebound_output.exists()

    wrong_rubric = copy.deepcopy(original)
    wrong_rubric["scoring_capture"]["rubric_hash"] = judged_replay.digest(
        "different rubric"
    )
    wrong_rubric_path = tmp_path / "wrong-rubric-replay.json"
    wrong_rubric_path.write_text(
        json.dumps(reseal_capture_and_report(wrong_rubric)), encoding="utf-8"
    )
    wrong_rubric_output = tmp_path / "wrong-rubric-out.json"
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(wrong_rubric_output),
                "--replay",
                str(wrong_rubric_path),
            ]
        )
        == 2
    )
    assert not wrong_rubric_output.exists()
    assert original_path.exists()
    capsys.readouterr()


def test_output_overwrite_and_input_or_replay_alias_are_rejected_preflight(
    tmp_path, monkeypatch, capsys
):
    source = write_input(tmp_path, make_input())
    calls = mock_network(monkeypatch)
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(source),
                "--allow-network",
                "--max-calls",
                "2",
            ]
        )
        == 2
    )
    existing = tmp_path / "existing.json"
    existing.write_text("existing", encoding="utf-8")
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(existing),
                "--allow-network",
                "--max-calls",
                "2",
            ]
        )
        == 2
    )
    assert calls == []

    _, replay_path, _, generated_calls = run_network(
        tmp_path / "generated", monkeypatch
    )
    generated_call_count = len(generated_calls)
    assert (
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(replay_path),
                "--replay",
                str(replay_path),
            ]
        )
        == 2
    )
    assert calls == []
    assert len(generated_calls) == generated_call_count == 2
    capsys.readouterr()


def test_cli_limits_and_report_hash_contract(tmp_path, monkeypatch, capsys):
    source, output, report, _ = run_network(tmp_path, monkeypatch)
    assert report["report_hash"] == judged_replay.digest(
        {key: value for key, value in report.items() if key != "report_hash"}
    )
    assert report["scoring_capture"]["scoring_hash"] == judged_replay.digest(
        {
            key: value
            for key, value in report["scoring_capture"].items()
            if key != "scoring_hash"
        }
    )
    assert source.exists() and output.exists()
    with pytest.raises(SystemExit):
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(tmp_path / "x"),
                "--allow-network",
                "--max-calls",
                "81",
            ]
        )
    with pytest.raises(SystemExit):
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(tmp_path / "x"),
                "--allow-network",
                "--max-calls",
                "2",
                "--timeout",
                "31",
            ]
        )
    with pytest.raises(SystemExit):
        jev_eval.main(
            [
                "--input",
                str(source),
                "--out",
                str(tmp_path / "x"),
                "--allow-network",
                "--max-calls",
                "2",
                "--total-deadline",
                "301",
            ]
        )
    capsys.readouterr()
