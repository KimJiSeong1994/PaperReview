from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from routers.geo_comparisons import load_geo_comparisons

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_geo_pilot_review", ROOT / "scripts/validate_geo_pilot.py"
)
assert SPEC and SPEC.loader
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


def _report_scope() -> dict:
    manifest = json.loads((ROOT / "data/blog/geo-pilot.json").read_text(encoding="utf-8"))
    urls = [f"https://jiphyeonjeon.kr/blog/series/{hub}" for hub in manifest["hubs"]]
    urls.extend(f"https://jiphyeonjeon.kr/blog/{page['slug']}" for page in manifest["pages"])
    return {
        "property": "https://jiphyeonjeon.kr/",
        "dimensions": ["page"],
        "urls": urls,
    }


def _source(
    source_id: str,
    measurements: dict[str, int] | None,
    *,
    baseline_measurements: dict[str, int] | None = None,
    status: str = "available",
) -> dict:
    baseline = baseline_measurements
    if status == "available" and baseline is None:
        baseline = {key: max(value - 1, 0) for key, value in (measurements or {}).items()}
    account_scope = _report_scope() if source_id in {"gsc_ai", "bing_ai"} else None
    return {
        "id": source_id,
        "baseline_status": status,
        "baseline_window": (
            {"start": "2026-08-27T00:00:00Z", "end": "2026-09-24T00:00:00Z"}
            if status == "available"
            else None
        ),
        "baseline_measurements": baseline if status == "available" else None,
        "status": status,
        "window": (
            {"start": "2026-09-25T00:00:00Z", "end": "2026-10-23T00:00:00Z"}
            if status == "available"
            else None
        ),
        "timezone": "UTC",
        "report_lag_days": 0 if status == "available" else None,
        "measurements": measurements if status == "available" else None,
        "baseline_scope": copy.deepcopy(account_scope) if status == "available" else None,
        "followup_scope": copy.deepcopy(account_scope) if status == "available" else None,
        "evidence_ref": ".omx/reports/geo-implementation/manual-source.json",
    }


def _active_manifest(status: str = "observing", *, extension_count: int = 0) -> dict:
    manifest = json.loads((ROOT / "data/blog/geo-pilot.json").read_text(encoding="utf-8"))
    manifest.update(
        status=status,
        deployment_ref="2026-09-24T00:00:00Z",
        recrawl_anchor="2026-09-25T00:00:00Z",
        observation_deadline=(
            "2026-10-23T00:00:00Z" if extension_count == 0 else "2026-11-20T00:00:00Z"
        ),
    )
    for review in manifest["semantic_reviews"]:
        review.update(
            reviewer="independent-reviewer",
            reviewed_at="2026-09-24T00:00:00Z",
            result="approved",
        )
    return manifest


def _active_observation() -> dict:
    manifest = _active_manifest()
    urls = [f"https://jiphyeonjeon.kr/blog/series/{hub}" for hub in manifest["hubs"]]
    urls.extend(f"https://jiphyeonjeon.kr/blog/{page['slug']}" for page in manifest["pages"])
    return {
        "schema_version": 1,
        "deployment_at": "2026-09-24T00:00:00Z",
        "ceiling_at": "2026-12-03T00:00:00Z",
        "decision_at": None,
        "extension_count": 0,
        "guardrails": {
            "status": "pass",
            "evidence_ref": ".omx/reports/geo-implementation/guardrails.json",
        },
        "recrawls": [
            {
                "url": url,
                "bot": "Googlebot",
                "kind": "verified_index",
                "observed_at_utc": "2026-09-25T00:00:00Z",
                "evidence_ref": ".omx/reports/geo-implementation/recrawl.json",
            }
            for url in urls
        ],
        "sources": [
            _source(
                "nginx_answer_fetches",
                {"estimated_answer_fetches": 5},
            ),
            _source("ai_referrers", {"referrals": 1}),
            _source("gsc_ai", {"impressions": 3}),
            _source(
                "bing_ai",
                {"citations": 1, "cited_pages": 1, "sampled_grounding_query_count": 0},
                baseline_measurements={
                    "citations": 1,
                    "cited_pages": 1,
                    "sampled_grounding_query_count": 0,
                },
            ),
        ],
        "nginx_weekly": [
            {
                "start_utc": start,
                "end_utc": end,
                "coverage": "complete",
                "measurements": {"estimated_answer_fetches": 1, "ai_referrals": 0},
                "evidence_ref": ".omx/reports/geo-implementation/nginx-week.json",
            }
            for start, end in [
                ("2026-09-25T00:00:00Z", "2026-10-02T00:00:00Z"),
                ("2026-10-02T00:00:00Z", "2026-10-09T00:00:00Z"),
                ("2026-10-09T00:00:00Z", "2026-10-16T00:00:00Z"),
                ("2026-10-16T00:00:00Z", "2026-10-23T00:00:00Z"),
            ]
        ],
        "reader_outcomes": [
            {
                "status": "available",
                "window": {"start": "2026-09-25T00:00:00Z", "end": "2026-10-23T00:00:00Z"},
                "metrics": {
                    "page_views": 10,
                    "sessions": 5,
                    "pages_per_session": 2,
                    "landing_sessions": 3,
                },
                "evidence_ref": ".omx/reports/geo-implementation/readers.json",
            }
        ],
        "contaminated_units": [],
        "disposition": None,
    }


def test_nodeploy_rejects_any_disposition() -> None:
    observation = _active_observation()
    observation.update(deployment_at=None, ceiling_at=None, decision_at=None, recrawls=[])
    observation["guardrails"]["status"] = "unknown"
    observation["disposition"] = "inconclusive"
    with pytest.raises(pilot.GeoPilotError, match="undeployed"):
        pilot.validate_observation(observation)


def test_disposition_evaluator_is_time_and_evidence_aware() -> None:
    observation = _active_observation()
    manifest = _active_manifest()
    result = pilot.evaluate_disposition(
        observation, manifest, as_of="2026-10-23T00:00:00Z"
    )
    assert result["disposition"] == "expansion_candidate"
    assert result["account_directions"]["gsc_ai.impressions"] == "up"
    assert (
        pilot.evaluate_disposition(
            observation, manifest, as_of="2026-10-22T23:59:59Z"
        )["disposition"]
        is None
    )

    contaminated = copy.deepcopy(observation)
    contaminated["contaminated_units"] = [contaminated["recrawls"][0]["url"]]
    assert (
        pilot.evaluate_disposition(
            contaminated, manifest, as_of="2026-10-23T00:00:00Z"
        )["disposition"]
        == "inconclusive"
    )

    insufficient = copy.deepcopy(observation)
    insufficient["sources"][2] = _source("gsc_ai", None, status="insufficient_data")
    assert (
        pilot.evaluate_disposition(
            insufficient, manifest, as_of="2026-10-23T00:00:00Z"
        )["disposition"]
        == "inconclusive"
    )

    regression = copy.deepcopy(observation)
    regression["guardrails"]["status"] = "regression"
    assert (
        pilot.evaluate_disposition(
            regression, manifest, as_of="2026-09-25T00:00:00Z"
        )["disposition"]
        == "rollback_recommended"
    )


def test_observation_rejects_extra_extensions_and_fake_positive() -> None:
    observation = _active_observation()
    observation["extension_count"] = 2
    with pytest.raises(pilot.GeoPilotError, match="extension_count"):
        pilot.validate_observation(observation)

    observation = _active_observation()
    observation["sources"][2] = _source("gsc_ai", None, status="no_property_access")
    observation["decision_at"] = "2026-10-23T00:00:00Z"
    observation["disposition"] = "expansion_candidate"
    with pytest.raises(pilot.GeoPilotError, match="does not match evidence"):
        pilot.validate_observation(
            observation,
            manifest=_active_manifest("expansion_candidate"),
        )


def test_extension_is_single_and_finite() -> None:
    observation = _active_observation()
    observation["extension_count"] = 1
    # One account provider can be complete while the other is still inside its report lag.
    observation["sources"][3] = _source("bing_ai", None, status="insufficient_data")
    manifest = _active_manifest(extension_count=1)
    pending = pilot.evaluate_disposition(
        observation, manifest, as_of="2026-10-23T00:00:00Z"
    )
    assert pending["disposition"] is None
    assert pending["reason"] == "reporting_extension_open"
    ended = pilot.evaluate_disposition(
        observation, manifest, as_of="2026-11-20T00:00:00Z"
    )
    assert ended["disposition"] == "inconclusive"


def test_day70_complete_evidence_can_decide_but_incomplete_or_late_cannot_expand() -> None:
    observation = _active_observation()
    observation["extension_count"] = 1
    observation["recrawls"] = [
        {**recrawl, "observed_at_utc": "2026-10-08T00:00:00Z"}
        for recrawl in observation["recrawls"]
    ]
    for source in observation["sources"]:
        if source["baseline_status"] == "available":
            source["baseline_window"] = {
                "start": "2026-07-30T00:00:00Z",
                "end": "2026-09-24T00:00:00Z",
            }
            source["window"] = {
                "start": "2026-10-08T00:00:00Z",
                "end": "2026-12-03T00:00:00Z",
            }
    observation["reader_outcomes"][0]["window"] = {
        "start": "2026-10-08T00:00:00Z",
        "end": "2026-12-03T00:00:00Z",
    }
    observation["nginx_weekly"] = [
        {
            "start_utc": f"2026-{month_day}T00:00:00Z",
            "end_utc": f"2026-{next_month_day}T00:00:00Z",
            "coverage": "complete",
            "measurements": {"estimated_answer_fetches": 1, "ai_referrals": 0},
            "evidence_ref": ".omx/reports/geo-implementation/nginx-week.json",
        }
        for month_day, next_month_day in [
            ("10-08", "10-15"),
            ("10-15", "10-22"),
            ("10-22", "10-29"),
            ("10-29", "11-05"),
            ("11-05", "11-12"),
            ("11-12", "11-19"),
            ("11-19", "11-26"),
            ("11-26", "12-03"),
        ]
    ]
    manifest = _active_manifest(extension_count=1)
    manifest["recrawl_anchor"] = "2026-10-08T00:00:00Z"
    manifest["observation_deadline"] = "2026-12-03T00:00:00Z"

    at_ceiling = pilot.evaluate_disposition(
        observation, manifest, as_of="2026-12-03T00:00:00Z"
    )
    assert at_ceiling["disposition"] == "expansion_candidate"

    incomplete = copy.deepcopy(observation)
    incomplete["sources"][2] = _source("gsc_ai", None, status="insufficient_data")
    incomplete["sources"][3] = _source("bing_ai", None, status="insufficient_data")
    assert (
        pilot.evaluate_disposition(incomplete, manifest, as_of="2026-12-03T00:00:00Z")[
            "disposition"
        ]
        == "inconclusive"
    )
    assert (
        pilot.evaluate_disposition(observation, manifest, as_of="2026-12-03T00:00:01Z")[
            "disposition"
        ]
        != "expansion_candidate"
    )


def test_account_windows_and_sample_volume_cannot_fake_improvement() -> None:
    observation = _active_observation()
    manifest = _active_manifest()
    gsc = observation["sources"][2]
    gsc["baseline_measurements"] = {"impressions": 3}
    bing = observation["sources"][3]
    bing["measurements"]["sampled_grounding_query_count"] = 100
    flat = pilot.evaluate_disposition(observation, manifest, as_of="2026-10-23T00:00:00Z")
    assert flat["disposition"] == "inconclusive"
    assert flat["reason"] == "flat_account_direction"

    gsc["measurements"] = {"impressions": 4}
    gsc["window"]["start"] = "2026-09-26T00:00:00Z"
    gsc["window"]["end"] = "2026-10-24T00:00:00Z"
    not_reported = pilot.evaluate_disposition(
        observation, manifest, as_of="2026-10-23T00:00:00Z"
    )
    assert not_reported["disposition"] == "inconclusive"
    assert not_reported["reason"] == "flat_account_direction"


def test_whole_property_account_totals_cannot_qualify_the_pilot() -> None:
    observation = _active_observation()
    observation["sources"][2]["followup_scope"]["urls"] = []
    with pytest.raises(pilot.GeoPilotError, match="pilot URL cohort"):
        pilot.evaluate_disposition(
            observation, _active_manifest(), as_of="2026-10-23T00:00:00Z"
        )

    malformed = _active_observation()
    malformed["sources"][2]["followup_scope"]["urls"] = [{}]
    with pytest.raises(pilot.GeoPilotError, match="non-empty string"):
        pilot.evaluate_disposition(
            malformed, _active_manifest(), as_of="2026-10-23T00:00:00Z"
        )


def test_deployed_evaluation_rejects_draft_manifest_bypass() -> None:
    observation = _active_observation()
    draft = json.loads((ROOT / "data/blog/geo-pilot.json").read_text(encoding="utf-8"))
    with pytest.raises(pilot.GeoPilotError, match="non-draft manifest"):
        pilot.evaluate_disposition(observation, draft, as_of="2026-10-23T00:00:00Z")


def test_complete_reader_and_weekly_records_cannot_be_empty() -> None:
    observation = _active_observation()
    observation["reader_outcomes"][0]["metrics"] = dict.fromkeys(pilot.READER_METRICS)
    with pytest.raises(pilot.GeoPilotError, match="require all metrics"):
        pilot.validate_observation(observation, manifest=_active_manifest())

    observation = _active_observation()
    observation["nginx_weekly"][0]["measurements"] = {}
    with pytest.raises(pilot.GeoPilotError, match="all count metrics"):
        pilot.validate_observation(observation, manifest=_active_manifest())


def test_provider_local_equal_windows_survive_dst_offset_change() -> None:
    observation = json.loads(
        (ROOT / "data/blog/geo-pilot-observation.json").read_text(encoding="utf-8")
    )
    gsc = next(source for source in observation["sources"] if source["id"] == "gsc_ai")
    gsc.update(
        baseline_status="available",
        baseline_window={
            "start": "2026-09-22T00:00:00-07:00",
            "end": "2026-10-20T00:00:00-07:00",
        },
        baseline_measurements={"impressions": 1},
        status="available",
        window={
            "start": "2026-10-20T00:00:00-07:00",
            "end": "2026-11-17T00:00:00-08:00",
        },
        report_lag_days=0,
        measurements={"impressions": 2},
        baseline_scope=_report_scope(),
        followup_scope=_report_scope(),
    )
    checked = pilot.validate_observation(
        observation,
        manifest=json.loads((ROOT / "data/blog/geo-pilot.json").read_text(encoding="utf-8")),
    )
    checked_gsc = next(source for source in checked["sources"] if source["id"] == "gsc_ai")
    assert checked_gsc["measurements"] == {"impressions": 2}


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf"), 1.5, True])
def test_count_metrics_reject_nonfinite_fractional_and_boolean_values(bad_value) -> None:
    observation = _active_observation()
    observation["sources"][2]["measurements"]["impressions"] = bad_value
    with pytest.raises(pilot.GeoPilotError, match="non-negative integer"):
        pilot.validate_observation(observation, manifest=_active_manifest())


@pytest.mark.parametrize("bad_control", [True, 1.0])
def test_extension_count_requires_an_actual_integer(bad_control) -> None:
    observation = _active_observation()
    observation["extension_count"] = bad_control
    with pytest.raises(pilot.GeoPilotError, match="extension_count"):
        pilot.validate_observation(observation, manifest=_active_manifest())


def test_zero_counts_and_finite_pages_per_session_are_valid() -> None:
    observation = _active_observation()
    observation["sources"][2]["baseline_measurements"]["impressions"] = 0
    observation["sources"][2]["measurements"]["impressions"] = 0
    observation["sources"][3]["baseline_measurements"]["cited_pages"] = 0
    observation["sources"][3]["measurements"]["cited_pages"] = 0
    observation["sources"][2]["measurements"]["impressions"] = 10**100
    observation["reader_outcomes"][0]["metrics"]["pages_per_session"] = 1.25
    checked = pilot.validate_observation(observation, manifest=_active_manifest())
    assert checked["sources"][2]["measurements"]["impressions"] == 10**100
    assert checked["reader_outcomes"][0]["metrics"]["pages_per_session"] == 1.25
    observation["reader_outcomes"][0]["metrics"]["pages_per_session"] = 10**1000
    checked = pilot.validate_observation(observation, manifest=_active_manifest())
    assert checked["reader_outcomes"][0]["metrics"]["pages_per_session"] == 10**1000


def test_reader_counts_and_bing_distinct_cited_pages_are_integers() -> None:
    observation = _active_observation()
    observation["reader_outcomes"][0]["metrics"]["sessions"] = float("nan")
    with pytest.raises(pilot.GeoPilotError, match="non-negative integer"):
        pilot.validate_observation(observation, manifest=_active_manifest())

    observation = _active_observation()
    observation["reader_outcomes"][0]["metrics"]["pages_per_session"] = float("inf")
    with pytest.raises(pilot.GeoPilotError, match="finite non-negative number"):
        pilot.validate_observation(observation, manifest=_active_manifest())

    observation = _active_observation()
    observation["sources"][3]["measurements"]["cited_pages"] = 1.5
    with pytest.raises(pilot.GeoPilotError, match="non-negative integer"):
        pilot.validate_observation(observation, manifest=_active_manifest())


def test_strict_json_loader_rejects_nonfinite_constants_but_not_text(tmp_path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"value": NaN}', encoding="utf-8")
    with pytest.raises(pilot.GeoPilotError, match="non-finite JSON constant"):
        pilot._load(invalid)

    valid = tmp_path / "valid.json"
    valid.write_text('{"value": "NaN is article text"}', encoding="utf-8")
    assert pilot._load(valid) == {"value": "NaN is article text"}


def test_schema_versions_reject_boolean_alias_for_one() -> None:
    manifest = json.loads((ROOT / "data/blog/geo-pilot.json").read_text(encoding="utf-8"))
    manifest["schema_version"] = True
    with pytest.raises(pilot.GeoPilotError, match="schema_version"):
        pilot.validate_manifest(manifest)

    observation = json.loads(
        (ROOT / "data/blog/geo-pilot-observation.json").read_text(encoding="utf-8")
    )
    observation["schema_version"] = True
    with pytest.raises(pilot.GeoPilotError, match="schema_version"):
        pilot.validate_observation(observation)


def test_rolled_back_and_conflict_states_require_consistent_results() -> None:
    manifest = json.loads((ROOT / "data/blog/geo-pilot.json").read_text(encoding="utf-8"))
    manifest["status"] = "rolled_back"
    manifest["rollback_ref"] = ".omx/reports/geo-implementation/rollback.json"
    with pytest.raises(pilot.GeoPilotError, match="result_hash"):
        pilot.validate_manifest(manifest)

    manifest["status"] = "rollback_conflict"
    manifest["edits"][0]["result_hash"] = manifest["edits"][0]["before_hash"]
    with pytest.raises(pilot.GeoPilotError, match="restored results"):
        pilot.validate_manifest(manifest)


def test_evidence_url_rejects_query_components() -> None:
    observation = _active_observation()
    observation["guardrails"]["evidence_ref"] = (
        "https://example.com/report?query=alice@example.com"
    )
    with pytest.raises(pilot.GeoPilotError, match="query"):
        pilot.validate_observation(observation)


def test_runtime_loader_rejects_projection_digest_mismatch_and_missing_source(tmp_path) -> None:
    source = ROOT / "data/blog/geo-comparisons.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    generated = tmp_path / "geo_generated.py"
    generated.write_text(
        "GEO_COMPARISONS_SOURCE_SHA256 = " + repr("0" * 64) + "\n"
        "GEO_COMPARISONS = " + repr(document["comparisons"]) + "\n",
        encoding="utf-8",
    )
    assert load_geo_comparisons(generated_path=generated, source_path=source) == {}
    assert load_geo_comparisons(generated_path=generated, source_path=tmp_path / "missing.json") == {}
