from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_geo_pilot", ROOT / "scripts/validate_geo_pilot.py"
)
assert SPEC and SPEC.loader
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


def _real_target() -> tuple[str, dict]:
    posts = json.loads((ROOT / "data/blog/posts.json").read_text(encoding="utf-8"))
    posts = posts.get("posts", posts) if isinstance(posts, dict) else posts
    target = next(post for post in posts if post["slug"] == "ms-graphrag-global-query-focused-summarization")
    return target["slug"], target


def _manifest() -> tuple[dict, dict]:
    slug, post = _real_target()
    before = post.get("excerpt")
    applied = f"{before} bounded update"
    manifest = {
        "schema_version": 1,
        "status": "draft",
        "recorded_at": "2026-09-24T00:00:00Z",
        "hubs": ["graphrag", "gnn"],
        "pages": [
            {
                "slug": slug,
                "selection_basis": "editorial_hypothesis",
                "hypothesis": "Clarify the method's applicability conditions.",
            }
        ],
        "excluded_slugs": [pilot.EXCLUDED_SLUG],
        "baseline_window": None,
        "deployment_ref": None,
        "recrawl_anchor": None,
        "observation_deadline": None,
        "rollback_ref": None,
        "edits": [
            {
                "slug": slug,
                "field": "excerpt",
                "before_value": before,
                "before_hash": pilot.value_sha256(before),
                "applied_value": applied,
                "applied_hash": pilot.value_sha256(applied),
                "result_hash": None,
            }
        ],
        "semantic_reviews": [],
        "evidence_paths": [],
    }
    applied_post = copy.deepcopy(post)
    applied_post["excerpt"] = applied
    return manifest, {"posts": [applied_post]}


def _observation() -> dict:
    observation = json.loads(
        (ROOT / "data/blog/geo-pilot-observation.json").read_text(encoding="utf-8")
    )
    observation["deployment_at"] = "2026-09-24T00:00:00Z"
    observation["ceiling_at"] = "2026-12-03T00:00:00Z"
    return observation


def _deployed_manifest(manifest: dict) -> dict:
    manifest = copy.deepcopy(manifest)
    manifest.update(
        status="active",
        deployment_ref="2026-09-24T00:00:00Z",
        recrawl_anchor="2026-09-25T00:00:00Z",
        observation_deadline="2026-10-23T00:00:00Z",
    )
    manifest["semantic_reviews"] = [
        {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "reviewer": "independent-reviewer",
            "reviewed_at": "2026-09-24T00:00:00Z",
            "evidence_ref": ".omx/reports/geo/semantic-review.json",
            "result": "approved",
        }
        for scope_type, scope_id in [
            ("hub", "graphrag"),
            ("hub", "gnn"),
            ("page", manifest["pages"][0]["slug"]),
        ]
    ]
    return manifest


def test_manifest_and_field_scoped_rollback_plan() -> None:
    manifest, posts = _manifest()
    checked = pilot.validate_manifest(manifest, posts=posts)
    plan = pilot.plan_rollback(checked, posts)
    assert plan["status"] == "ready"
    assert plan["updates"] == [
        {
            "slug": checked["edits"][0]["slug"],
            "field": "excerpt",
            "value": checked["edits"][0]["before_value"],
            "result_hash": checked["edits"][0]["before_hash"],
        }
    ]


def test_rollback_conflict_produces_no_updates() -> None:
    manifest, posts = _manifest()
    posts["posts"][0]["excerpt"] += " concurrent editor change"
    plan = pilot.plan_rollback(manifest, posts)
    assert plan["status"] == "rollback_conflict"
    assert plan["updates"] == []
    assert plan["conflicts"][0]["field"] == "excerpt"


@pytest.mark.parametrize("field", ["title", "slug", "index_deep_view"])
def test_manifest_rejects_fields_outside_allowlist(field: str) -> None:
    manifest, posts = _manifest()
    manifest["edits"][0]["field"] = field
    with pytest.raises(pilot.GeoPilotError):
        pilot.validate_manifest(manifest, posts=posts)


def test_updated_at_without_content_change_is_rejected() -> None:
    manifest, posts = _manifest()
    edit = manifest["edits"][0]
    edit.update(
        field="updated_at",
        before_value="2026-01-01T00:00:00Z",
        applied_value="2026-09-24T00:00:00Z",
    )
    edit["before_hash"] = pilot.value_sha256(edit["before_value"])
    edit["applied_hash"] = pilot.value_sha256(edit["applied_value"])
    with pytest.raises(pilot.GeoPilotError, match="actual content change"):
        pilot.validate_manifest(manifest, posts=posts)


def test_observation_rejects_answer_fetch_bot_as_recrawl() -> None:
    observation = _observation()
    observation["recrawls"] = [
        {
            "url": "https://jiphyeonjeon.ai/blog/series/graphrag",
            "bot": "ChatGPT-User",
            "kind": "verified_index",
            "observed_at_utc": "2026-09-25T00:00:00Z",
            "evidence_ref": ".omx/reports/geo/recrawl.md",
        }
    ]
    with pytest.raises(pilot.GeoPilotError, match="verified search/index"):
        pilot.validate_observation(observation)


def test_observation_allows_only_canonical_kr_pilot_recrawl_urls() -> None:
    manifest, _ = _manifest()
    manifest = _deployed_manifest(manifest)
    observation = _observation()
    recrawl = {
        "url": "https://jiphyeonjeon.kr/blog/series/graphrag",
        "bot": "Googlebot",
        "kind": "verified_index",
        "observed_at_utc": "2026-09-25T00:00:00Z",
        "evidence_ref": ".omx/reports/geo/recrawl.md",
    }
    observation["recrawls"] = [recrawl]
    checked = pilot.validate_observation(observation, manifest=manifest)
    assert checked["recrawls"][0]["url"] == recrawl["url"]

    observation["recrawls"][0]["url"] = "https://jiphyeonjeon.ai/blog/series/graphrag"
    with pytest.raises(pilot.GeoPilotError, match="outside the pilot"):
        pilot.validate_observation(observation, manifest=manifest)


def test_observation_rejects_overlapping_weekly_windows() -> None:
    observation = _observation()
    base = {
        "coverage": "complete",
        "measurements": {"estimated_answer_fetches": 1, "ai_referrals": 0},
        "evidence_ref": ".omx/reports/geo/nginx-week.md",
    }
    observation["nginx_weekly"] = [
        {**base, "start_utc": "2026-09-24T00:00:00Z", "end_utc": "2026-10-01T00:00:00Z"},
        {**base, "start_utc": "2026-09-30T00:00:00Z", "end_utc": "2026-10-07T00:00:00Z"},
    ]
    with pytest.raises(pilot.GeoPilotError, match="overlap"):
        pilot.validate_observation(observation)


def test_observation_preserves_unavailable_as_null_and_enforces_ceiling() -> None:
    observation = _observation()
    gsc = next(source for source in observation["sources"] if source["id"] == "gsc_ai")
    gsc["measurements"] = {"impressions": 0}
    with pytest.raises(pilot.GeoPilotError, match="null, not zero"):
        pilot.validate_observation(observation)
    observation = _observation()
    observation["ceiling_at"] = "2026-12-04T00:00:00Z"
    with pytest.raises(pilot.GeoPilotError, match="70 days"):
        pilot.validate_observation(observation)


def test_observation_rejects_private_metrics_and_unsafe_evidence() -> None:
    observation = _observation()
    observation["reader_outcomes"] = [
        {
            "window": {"start": "2026-09-24T00:00:00Z", "end": "2026-10-01T00:00:00Z"},
            "metrics": {
                "page_views": 1,
                "sessions": 1,
                "pages_per_session": 1.0,
                "landing_sessions": 1,
                "raw_ip": 1,
            },
            "evidence_ref": "https://192.0.2.1/raw.log",
        }
    ]
    with pytest.raises(pilot.GeoPilotError):
        pilot.validate_observation(observation)
