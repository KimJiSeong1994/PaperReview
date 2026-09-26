from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from routers.geo_comparisons import AXES, GeoComparisonError, validate_comparisons


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pilot = _load_module("geo_pilot_adversarial", "scripts/validate_geo_pilot.py")
sync = _load_module("geo_sync_adversarial", "scripts/sync_geo_comparisons.py")


def _known_cell() -> dict:
    return {
        "state": "known",
        "value": "paper-supported value",
        "reason": None,
        "sources": ["https://arxiv.org/abs/2404.16130"],
    }


def _comparison_document(shared_slug: str) -> dict:
    def hub() -> dict:
        return {
            "question": "Which conditions fit this method?",
            "reading_guide": [{"title": "Start here", "description": "Compare the stated assumptions.", "slugs": [shared_slug]}],
            "axes": list(AXES),
            "entries": [
                {
                    "slug": shared_slug,
                    "label": "Shared method",
                    "summary": {"role": "Method role", "fit": "Documented use", "caution": "Scope matters"},
                    "values": {axis: _known_cell() for axis in AXES},
                }
            ],
            "limits": "Do not rank unlike benchmarks.",
            "source_note": "Claims are scoped to primary papers.",
        }

    return {"schema_version": 1, "comparisons": {"graphrag": hub(), "gnn": hub()}}


def test_comparison_rejects_one_slug_assigned_to_multiple_series() -> None:
    document = _comparison_document("shared-paper")

    with pytest.raises(GeoComparisonError, match="more than one series"):
        validate_comparisons(
            document,
            series_members={"graphrag": ["shared-paper"], "gnn": ["shared-paper"]},
            published_slugs={"shared-paper"},
        )


def test_available_provider_requires_its_canonical_measurement_fields() -> None:
    observation = json.loads(
        (ROOT / "data/blog/geo-pilot-observation.json").read_text(encoding="utf-8")
    )
    gsc = next(source for source in observation["sources"] if source["id"] == "gsc_ai")
    gsc.update(
        status="available",
        window={"start": "2026-09-01T00:00:00-07:00", "end": "2026-09-08T00:00:00-07:00"},
        report_lag_days=3,
        measurements={},
    )

    with pytest.raises(pilot.GeoPilotError, match="required measurement"):
        pilot.validate_observation(observation)


def test_available_provider_accepts_observed_zero_without_mixing_metrics() -> None:
    observation = json.loads(
        (ROOT / "data/blog/geo-pilot-observation.json").read_text(encoding="utf-8")
    )
    gsc = next(source for source in observation["sources"] if source["id"] == "gsc_ai")
    gsc.update(
        status="available",
        window={"start": "2026-09-01T00:00:00-07:00", "end": "2026-09-08T00:00:00-07:00"},
        report_lag_days=3,
        measurements={"impressions": 0},
        followup_scope={
            "property": "https://jiphyeonjeon.kr/",
            "dimensions": ["page"],
            "urls": [
                "https://jiphyeonjeon.kr/blog/series/graphrag",
                "https://jiphyeonjeon.kr/blog/series/gnn",
                *[
                    f"https://jiphyeonjeon.kr/blog/{page['slug']}"
                    for page in json.loads(
                        (ROOT / "data/blog/geo-pilot.json").read_text(encoding="utf-8")
                    )["pages"]
                ],
            ],
        },
    )

    checked = pilot.validate_observation(
        observation,
        manifest=json.loads((ROOT / "data/blog/geo-pilot.json").read_text(encoding="utf-8")),
    )

    checked_gsc = next(source for source in checked["sources"] if source["id"] == "gsc_ai")
    assert checked_gsc["measurements"] == {"impressions": 0}


def test_available_provider_rejects_metric_from_another_provider() -> None:
    observation = json.loads(
        (ROOT / "data/blog/geo-pilot-observation.json").read_text(encoding="utf-8")
    )
    gsc = next(source for source in observation["sources"] if source["id"] == "gsc_ai")
    gsc.update(
        status="available",
        window={"start": "2026-09-01T00:00:00-07:00", "end": "2026-09-08T00:00:00-07:00"},
        report_lag_days=3,
        measurements={"impressions": 1, "citations": 2},
    )

    with pytest.raises(pilot.GeoPilotError, match="unsupported measurements"):
        pilot.validate_observation(observation)


def test_recrawl_evidence_requires_a_deployment_anchor() -> None:
    observation = json.loads(
        (ROOT / "data/blog/geo-pilot-observation.json").read_text(encoding="utf-8")
    )
    observation["recrawls"] = [
        {
            "url": "https://jiphyeonjeon.ai/blog/series/graphrag",
            "bot": "Googlebot",
            "kind": "verified_index",
            "observed_at_utc": "2026-09-25T00:00:00Z",
            "evidence_ref": ".omx/reports/geo-implementation/recrawl.md",
        }
    ]

    with pytest.raises(pilot.GeoPilotError, match="requires deployment_at"):
        pilot.validate_observation(observation)


def test_rollback_conflict_is_pure_and_preserves_unrelated_fields() -> None:
    manifest = json.loads((ROOT / "data/blog/geo-pilot.json").read_text(encoding="utf-8"))
    posts_document = json.loads((ROOT / "data/blog/posts.json").read_text(encoding="utf-8"))
    posts = posts_document.get("posts", posts_document)
    edit = manifest["edits"][0]
    target = next(post for post in posts if post["slug"] == edit["slug"])
    target[edit["field"]] = f"{target[edit['field']]} concurrent edit"
    target["audit_sentinel"] = {"preserve": True}
    before_manifest = copy.deepcopy(manifest)
    before_posts = copy.deepcopy(posts_document)

    plan = pilot.plan_rollback(manifest, posts_document)

    assert plan["status"] == "rollback_conflict"
    assert plan["updates"] == []
    assert manifest == before_manifest
    assert posts_document == before_posts
    assert target["audit_sentinel"] == {"preserve": True}


def test_generator_check_reports_drift_without_mutating_outputs(tmp_path, monkeypatch) -> None:
    python_output = tmp_path / "geo.py"
    typescript_output = tmp_path / "geo.ts"
    monkeypatch.setattr(sync, "PYTHON_OUTPUT", python_output)
    monkeypatch.setattr(sync, "TYPESCRIPT_OUTPUT", typescript_output)
    assert sync.sync(source=ROOT / "data/blog/geo-comparisons.json")
    python_output.write_text("# reviewer drift\n", encoding="utf-8")
    typescript_output.unlink()
    drift_before = python_output.read_bytes()

    assert sync.sync(check=True, source=ROOT / "data/blog/geo-comparisons.json") is False
    assert python_output.read_bytes() == drift_before
    assert not typescript_output.exists()
