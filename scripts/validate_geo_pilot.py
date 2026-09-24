#!/usr/bin/env python3
"""Validate the bounded GEO pilot records and produce safe rollback plans."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import ipaddress
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REPO_ROOT = Path(__file__).resolve().parents[1]
POSTS_PATH = REPO_ROOT / "data/blog/posts.json"
MANIFEST_PATH = REPO_ROOT / "data/blog/geo-pilot.json"
OBSERVATION_PATH = REPO_ROOT / "data/blog/geo-pilot-observation.json"

PILOT_HUBS = ("graphrag", "gnn")
EXCLUDED_SLUG = "ic2-interventional-dynamical-causality-under-latent-confounders"
MANIFEST_STATUSES = {
    "draft",
    "active",
    "observing",
    "expansion_candidate",
    "inconclusive",
    "rollback_recommended",
    "rollback_conflict",
    "rolled_back",
}
SELECTION_BASES = {"gsc_query_demand", "bing_query_demand", "editorial_hypothesis"}
EDIT_FIELDS = {"excerpt", "content", "deep_content", "updated_at"}
REVIEW_RESULTS = {"pending", "approved", "rejected"}
SOURCE_STATUSES = {
    "available",
    "insufficient_data",
    "no_property_access",
    "excluded",
    "fetch_error",
}
SOURCE_MEASUREMENTS = {
    "nginx_answer_fetches": {"estimated_answer_fetches"},
    "ai_referrers": {"referrals"},
    "gsc_ai": {"impressions"},
    "bing_ai": {"citations", "cited_pages", "sampled_grounding_query_count"},
}
REQUIRED_SOURCE_IDS = tuple(SOURCE_MEASUREMENTS)
DISPOSITIONS = {"expansion_candidate", "inconclusive", "rollback_recommended"}
READER_METRICS = {"page_views", "sessions", "pages_per_session", "landing_sessions"}
VERIFIED_INDEX_BOTS = {"Googlebot", "Bingbot"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECRET_RE = re.compile(r"(?i)(api[_-]?key|authorization|bearer|cookie|password|secret|token)\s*[:=]")
_RAW_IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")


class GeoPilotError(ValueError):
    """A pilot artifact violates the bounded observation contract."""


def canonical_value_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def value_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_value_bytes(value)).hexdigest()


def _load(value: Any) -> Any:
    if isinstance(value, (str, Path)):
        return json.loads(
            Path(value).read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                GeoPilotError(f"non-finite JSON constant is forbidden: {token}")
            ),
        )
    return copy.deepcopy(value)


def _timestamp(value: Any, path: str, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise GeoPilotError(f"{path} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GeoPilotError(f"{path} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GeoPilotError(f"{path} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _nonempty(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GeoPilotError(f"{path} must be a non-empty string")
    return value


def _sha(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise GeoPilotError(f"{path} must be a lowercase SHA-256 digest")
    return value


def _evidence_ref(value: Any, path: str) -> str:
    text = _nonempty(value, path)
    if len(text) > 500 or _SECRET_RE.search(text) or _RAW_IPV4_RE.search(text):
        raise GeoPilotError(f"{path} is unsafe or too large")
    parsed = urlparse(text)
    if parsed.scheme:
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise GeoPilotError(f"{path} must be HTTPS or a repository-relative artifact")
        if parsed.query or parsed.fragment:
            raise GeoPilotError(f"{path} must not contain a query or fragment component")
        try:
            ipaddress.ip_address(parsed.hostname or "")
        except ValueError:
            pass
        else:
            raise GeoPilotError(f"{path} must not contain a raw IP address")
    else:
        candidate = Path(text)
        if candidate.is_absolute() or ".." in candidate.parts or text.startswith(("~", ".git/")):
            raise GeoPilotError(f"{path} must be a safe repository-relative artifact")
    return text


def _https_url(value: Any, path: str) -> str:
    text = _nonempty(value, path)
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise GeoPilotError(f"{path} must be an HTTPS URL without credentials")
    return text


def _series_members() -> dict[str, set[str]]:
    tree = ast.parse((REPO_ROOT / "routers/seo.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "BLOG_SERIES":
            raw = ast.literal_eval(node.value)
            return {hub: set(raw[hub]["slugs"]) for hub in PILOT_HUBS}
    raise GeoPilotError("routers/seo.py does not define literal BLOG_SERIES")


def _posts_by_slug(posts: Any = POSTS_PATH) -> dict[str, dict[str, Any]]:
    raw = _load(posts)
    values = raw.get("posts", raw) if isinstance(raw, Mapping) else raw
    if not isinstance(values, list):
        raise GeoPilotError("posts data must be an array or an object with posts")
    return {
        post["slug"]: post
        for post in values
        if isinstance(post, Mapping) and isinstance(post.get("slug"), str)
    }


def validate_manifest(manifest: Any, *, posts: Any = POSTS_PATH) -> dict[str, Any]:
    data = _load(manifest)
    if (
        not isinstance(data, Mapping)
        or type(data.get("schema_version")) is not int
        or data.get("schema_version") != 1
    ):
        raise GeoPilotError("manifest schema_version must be 1")
    required = {
        "schema_version", "status", "recorded_at", "hubs", "pages", "excluded_slugs",
        "baseline_window", "deployment_ref", "recrawl_anchor", "observation_deadline",
        "rollback_ref", "edits", "semantic_reviews", "evidence_paths",
    }
    if set(data) != required:
        raise GeoPilotError("manifest has unknown or missing fields")
    if data["status"] not in MANIFEST_STATUSES:
        raise GeoPilotError("manifest status is invalid")
    _timestamp(data["recorded_at"], "recorded_at")
    if tuple(data["hubs"]) != PILOT_HUBS:
        raise GeoPilotError("hubs must contain graphrag then gnn")
    if data["excluded_slugs"] != [EXCLUDED_SLUG]:
        raise GeoPilotError("excluded_slugs must retain the IC2 exclusion")
    pages = data["pages"]
    if not isinstance(pages, list) or len(pages) > 5:
        raise GeoPilotError("pages must be an array with at most five entries")
    posts_by_slug = _posts_by_slug(posts)
    members = _series_members()
    eligible = set().union(*members.values())
    seen_pages: set[str] = set()
    for index, page in enumerate(pages):
        path = f"pages[{index}]"
        if not isinstance(page, Mapping):
            raise GeoPilotError(f"{path} must be an object")
        allowed = {"slug", "selection_basis", "hypothesis", "evidence_path", "report_date"}
        if not {"slug", "selection_basis", "hypothesis"}.issubset(page) or set(page) - allowed:
            raise GeoPilotError(f"{path} has unknown or missing fields")
        slug = _nonempty(page["slug"], f"{path}.slug")
        if slug in seen_pages:
            raise GeoPilotError(f"{path}.slug is duplicated")
        seen_pages.add(slug)
        if slug == EXCLUDED_SLUG or slug not in eligible:
            raise GeoPilotError(f"{path}.slug is outside the pilot clusters")
        if slug not in posts_by_slug or posts_by_slug[slug].get("published") is not True:
            raise GeoPilotError(f"{path}.slug is not published")
        basis = page["selection_basis"]
        if basis not in SELECTION_BASES:
            raise GeoPilotError(f"{path}.selection_basis is invalid")
        _nonempty(page["hypothesis"], f"{path}.hypothesis")
        if basis != "editorial_hypothesis":
            _evidence_ref(page.get("evidence_path"), f"{path}.evidence_path")
            _timestamp(page.get("report_date"), f"{path}.report_date")

    if not isinstance(data["edits"], list):
        raise GeoPilotError("edits must be an array")
    edit_keys: set[tuple[str, str]] = set()
    changed_content_slugs: set[str] = set()
    for index, edit in enumerate(data["edits"]):
        path = f"edits[{index}]"
        required_edit = {
            "slug", "field", "before_value", "before_hash", "applied_value", "applied_hash", "result_hash"
        }
        if not isinstance(edit, Mapping) or set(edit) != required_edit:
            raise GeoPilotError(f"{path} has unknown or missing fields")
        slug = _nonempty(edit["slug"], f"{path}.slug")
        field = edit["field"]
        if slug not in seen_pages or field not in EDIT_FIELDS:
            raise GeoPilotError(f"{path} targets an unapproved slug or field")
        key = (slug, field)
        if key in edit_keys:
            raise GeoPilotError(f"{path} duplicates an edit target")
        edit_keys.add(key)
        before_hash = _sha(edit["before_hash"], f"{path}.before_hash")
        applied_hash = _sha(edit["applied_hash"], f"{path}.applied_hash")
        if before_hash != value_sha256(edit["before_value"]):
            raise GeoPilotError(f"{path}.before_hash does not match before_value")
        if applied_hash != value_sha256(edit["applied_value"]):
            raise GeoPilotError(f"{path}.applied_hash does not match applied_value")
        if before_hash == applied_hash:
            raise GeoPilotError(f"{path} does not change the field value")
        if edit["result_hash"] is not None:
            _sha(edit["result_hash"], f"{path}.result_hash")
        if field in {"excerpt", "content", "deep_content"}:
            changed_content_slugs.add(slug)
    for slug, field in edit_keys:
        if field == "updated_at" and slug not in changed_content_slugs:
            raise GeoPilotError("updated_at requires an actual content change for the same slug")

    if not isinstance(data["semantic_reviews"], list):
        raise GeoPilotError("semantic_reviews must be an array")
    approved_scopes: set[tuple[str, str]] = set()
    for index, review in enumerate(data["semantic_reviews"]):
        path = f"semantic_reviews[{index}]"
        fields = {"scope_type", "scope_id", "reviewer", "reviewed_at", "evidence_ref", "result"}
        if not isinstance(review, Mapping) or set(review) != fields:
            raise GeoPilotError(f"{path} has unknown or missing fields")
        if review["scope_type"] not in {"hub", "page"}:
            raise GeoPilotError(f"{path}.scope_type is invalid")
        scope_id = _nonempty(review["scope_id"], f"{path}.scope_id")
        if review["result"] not in REVIEW_RESULTS:
            raise GeoPilotError(f"{path}.result is invalid")
        reviewer = _nonempty(review["reviewer"], f"{path}.reviewer")
        if reviewer.casefold() in {"writer", "content writer", "author"}:
            raise GeoPilotError(f"{path}.reviewer must identify an independent reviewer")
        if review["result"] == "pending":
            if review["reviewed_at"] is not None:
                _timestamp(review["reviewed_at"], f"{path}.reviewed_at")
        else:
            _timestamp(review["reviewed_at"], f"{path}.reviewed_at")
            if "unassigned" in reviewer.casefold():
                raise GeoPilotError(f"{path}.reviewer must name the completed reviewer")
        _evidence_ref(review["evidence_ref"], f"{path}.evidence_ref")
        if review["scope_type"] == "hub" and scope_id not in PILOT_HUBS:
            raise GeoPilotError(f"{path}.scope_id is not a pilot hub")
        if review["scope_type"] == "page" and scope_id not in seen_pages:
            raise GeoPilotError(f"{path}.scope_id is not a pilot page")
        if review["result"] == "approved":
            approved_scopes.add((review["scope_type"], scope_id))
    if data["status"] in {"active", "observing", "expansion_candidate", "inconclusive"}:
        expected = {("hub", hub) for hub in PILOT_HUBS} | {("page", slug) for slug in seen_pages}
        if not expected.issubset(approved_scopes):
            raise GeoPilotError("non-draft manifests require approved independent semantic reviews")

    for index, ref in enumerate(data["evidence_paths"]):
        _evidence_ref(ref, f"evidence_paths[{index}]")
    baseline = data["baseline_window"]
    baseline_end = None
    if baseline is not None:
        if not isinstance(baseline, Mapping) or set(baseline) != {"start", "end"}:
            raise GeoPilotError("baseline_window must contain start and end")
        baseline_start = _timestamp(baseline["start"], "baseline_window.start")
        baseline_end = _timestamp(baseline["end"], "baseline_window.end")
        if baseline_start >= baseline_end:
            raise GeoPilotError("baseline_window must be increasing")
    deployment_at = _timestamp(data["deployment_ref"], "deployment_ref", nullable=True)
    anchor_at = _timestamp(data["recrawl_anchor"], "recrawl_anchor", nullable=True)
    deadline = _timestamp(data["observation_deadline"], "observation_deadline", nullable=True)
    if baseline_end and deployment_at and baseline_end > deployment_at:
        raise GeoPilotError("baseline must end no later than deployment")
    if anchor_at and (not deployment_at or anchor_at < deployment_at):
        raise GeoPilotError("recrawl_anchor must follow deployment")
    if anchor_at and deployment_at and anchor_at > deployment_at + timedelta(days=14):
        raise GeoPilotError("recrawl_anchor exceeds the deployment + 14 day anchor window")
    if deadline and (not deployment_at or deadline < deployment_at):
        raise GeoPilotError("observation_deadline must follow deployment")
    if deployment_at and deadline and deadline > deployment_at + timedelta(days=70):
        raise GeoPilotError("observation_deadline exceeds deployment + 70 days")
    if anchor_at and deadline and not (
        anchor_at + timedelta(days=28) <= deadline <= anchor_at + timedelta(days=56)
    ):
        raise GeoPilotError("observation_deadline must be 28 to 56 days after recrawl_anchor")
    if data["status"] == "rolled_back":
        if data["rollback_ref"] is None:
            raise GeoPilotError("rolled_back requires rollback_ref")
        _evidence_ref(data["rollback_ref"], "rollback_ref")
        if not data["evidence_paths"]:
            raise GeoPilotError("rolled_back must preserve evidence_paths")
        for index, edit in enumerate(data["edits"]):
            if edit["result_hash"] != edit["before_hash"]:
                raise GeoPilotError(
                    f"edits[{index}].result_hash must equal before_hash when rolled_back"
                )
            current = posts_by_slug[edit["slug"]].get(edit["field"])
            if value_sha256(current) != edit["before_hash"]:
                raise GeoPilotError(
                    f"edits[{index}] current value does not match the rolled-back result_hash"
                )
    elif data["status"] == "rollback_conflict":
        if data["rollback_ref"] is None:
            raise GeoPilotError("rollback_conflict requires rollback_ref evidence")
        _evidence_ref(data["rollback_ref"], "rollback_ref")
        if not data["evidence_paths"]:
            raise GeoPilotError("rollback_conflict must preserve evidence_paths")
        if any(edit["result_hash"] is not None for edit in data["edits"]):
            raise GeoPilotError("rollback_conflict cannot claim restored results")
    else:
        if any(edit["result_hash"] is not None for edit in data["edits"]):
            raise GeoPilotError("result_hash must remain null until rolled_back")
        if data["rollback_ref"] is not None:
            if data["status"] != "rollback_recommended":
                raise GeoPilotError("rollback_ref is only valid for rollback evidence states")
            _evidence_ref(data["rollback_ref"], "rollback_ref")
    return copy.deepcopy(dict(data))


def _window(value: Any, path: str) -> tuple[datetime, datetime]:
    if not isinstance(value, Mapping) or set(value) != {"start", "end"}:
        raise GeoPilotError(f"{path} must contain start and end")
    start = _timestamp(value["start"], f"{path}.start")
    end = _timestamp(value["end"], f"{path}.end")
    if start >= end:
        raise GeoPilotError(f"{path} must be a non-empty [start,end) window")
    return start, end


def _measurement_map(
    value: Any,
    path: str,
    allowed: set[str] | None = None,
    *,
    ratio_metrics: set[str] | None = None,
) -> None:
    if not isinstance(value, Mapping):
        raise GeoPilotError(f"{path} must be an object")
    if allowed is not None and set(value) - allowed:
        raise GeoPilotError(f"{path} contains private or unsupported measurements")
    ratios = ratio_metrics or set()
    for key, measurement in value.items():
        if not isinstance(key, str) or not key:
            raise GeoPilotError(f"{path} measurement keys must be non-empty strings")
        if key in ratios:
            valid_ratio = (type(measurement) is int and measurement >= 0) or (
                type(measurement) is float
                and math.isfinite(measurement)
                and measurement >= 0
            )
            if not valid_ratio:
                raise GeoPilotError(f"{path}.{key} must be a finite non-negative number")
        elif type(measurement) is not int or measurement < 0:
            raise GeoPilotError(f"{path}.{key} must be a non-negative integer")


def _validate_source_period(
    source: Mapping[str, Any],
    *,
    status_key: str,
    window_key: str,
    measurements_key: str,
    path: str,
    metrics: set[str],
) -> tuple[datetime, datetime] | None:
    status = source[status_key]
    if status not in SOURCE_STATUSES:
        raise GeoPilotError(f"{path}.{status_key} is invalid")
    window = source[window_key]
    measurements = source[measurements_key]
    if status != "available":
        if window is not None or measurements is not None:
            raise GeoPilotError(f"{path} unavailable measurements must be null, not zero")
        return None
    checked_window = _window(window, f"{path}.{window_key}")
    _measurement_map(measurements, f"{path}.{measurements_key}", metrics)
    missing = metrics - set(measurements)
    if missing:
        raise GeoPilotError(
            f"{path}.{measurements_key} is missing required measurement fields: {sorted(missing)}"
        )
    return checked_window


def _expected_urls(manifest: Mapping[str, Any]) -> set[str]:
    urls = {f"https://jiphyeonjeon.kr/blog/series/{hub}" for hub in manifest["hubs"]}
    urls |= {f"https://jiphyeonjeon.kr/blog/{page['slug']}" for page in manifest["pages"]}
    return urls


def _validate_report_scope(value: Any, path: str, expected_urls: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"property", "dimensions", "urls"}:
        raise GeoPilotError(f"{path} must contain property, dimensions, and urls")
    if value["property"] != "https://jiphyeonjeon.kr/" or value["dimensions"] != ["page"]:
        raise GeoPilotError(f"{path} must use the canonical page-scoped property")
    urls = value["urls"]
    if not isinstance(urls, list):
        raise GeoPilotError(f"{path}.urls must be a unique array")
    checked_urls: list[str] = []
    for index, url in enumerate(urls):
        checked_url = _https_url(url, f"{path}.urls[{index}]")
        parsed = urlparse(checked_url)
        if parsed.query or parsed.fragment:
            raise GeoPilotError(f"{path}.urls[{index}] cannot contain query or fragment")
        checked_urls.append(checked_url)
    if len(checked_urls) != len(set(checked_urls)):
        raise GeoPilotError(f"{path}.urls must be a unique array")
    if set(checked_urls) != expected_urls:
        raise GeoPilotError(f"{path}.urls must equal the pilot URL cohort")
    return copy.deepcopy(dict(value))


def _validate_observation_structure(
    observation: Any, *, manifest: Any | None = None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    data = _load(observation)
    required = {
        "schema_version", "deployment_at", "ceiling_at", "decision_at", "extension_count",
        "guardrails", "recrawls", "sources", "nginx_weekly", "reader_outcomes",
        "contaminated_units", "disposition",
    }
    if (
        not isinstance(data, Mapping)
        or set(data) != required
        or type(data.get("schema_version")) is not int
        or data.get("schema_version") != 1
    ):
        raise GeoPilotError("observation has unknown/missing fields or schema_version is not 1")
    deployment = _timestamp(data["deployment_at"], "deployment_at", nullable=True)
    ceiling = _timestamp(data["ceiling_at"], "ceiling_at", nullable=True)
    decision = _timestamp(data["decision_at"], "decision_at", nullable=True)
    if type(data["extension_count"]) is not int or data["extension_count"] not in {0, 1}:
        raise GeoPilotError("extension_count must be 0 or 1")
    if (deployment is None) != (ceiling is None):
        raise GeoPilotError("deployment_at and ceiling_at must both be null or populated")
    if deployment and ceiling != deployment + timedelta(days=70):
        raise GeoPilotError("ceiling_at must equal deployment_at + 70 days")
    if decision and (deployment is None or decision < deployment or decision > ceiling):
        raise GeoPilotError("decision_at must fall within the deployment observation period")
    if deployment is None and data["disposition"] is not None:
        raise GeoPilotError("undeployed observations cannot have a disposition")
    if (decision is None) != (data["disposition"] is None):
        raise GeoPilotError("decision_at and disposition must both be null or populated")
    if deployment is None and data["extension_count"] != 0:
        raise GeoPilotError("undeployed observations cannot have an extension")
    guardrails = data["guardrails"]
    if not isinstance(guardrails, Mapping) or set(guardrails) != {"status", "evidence_ref"}:
        raise GeoPilotError("guardrails must contain status and evidence_ref")
    if guardrails["status"] not in {"unknown", "pass", "regression"}:
        raise GeoPilotError("guardrails.status is invalid")
    if deployment is None and guardrails["status"] != "unknown":
        raise GeoPilotError("undeployed guardrails must remain unknown")
    _evidence_ref(guardrails["evidence_ref"], "guardrails.evidence_ref")

    allowed_urls: set[str] | None = None
    checked_manifest = None
    if manifest is not None:
        checked_manifest = validate_manifest(manifest)
        allowed_urls = _expected_urls(checked_manifest)
        manifest_deployment = _timestamp(
            checked_manifest["deployment_ref"], "manifest.deployment_ref", nullable=True
        )
        if deployment is None:
            if checked_manifest["status"] != "draft" or manifest_deployment is not None:
                raise GeoPilotError("undeployed observation requires a draft undeployed manifest")
        else:
            if checked_manifest["status"] == "draft" or manifest_deployment != deployment:
                raise GeoPilotError(
                    "deployed observation requires a reviewed non-draft manifest with matching deployment"
                )
            if data["disposition"] is None and checked_manifest["status"] not in {
                "active", "observing"
            }:
                raise GeoPilotError("active observation and manifest lifecycle states disagree")
            if (
                data["disposition"] is not None
                and checked_manifest["status"] != data["disposition"]
            ):
                raise GeoPilotError("stored disposition and manifest lifecycle states disagree")
    recrawled_urls: set[str] = set()
    for index, recrawl in enumerate(data["recrawls"]):
        path = f"recrawls[{index}]"
        if deployment is None:
            raise GeoPilotError(f"{path} requires deployment_at")
        fields = {"url", "bot", "kind", "observed_at_utc", "evidence_ref"}
        if not isinstance(recrawl, Mapping) or set(recrawl) != fields:
            raise GeoPilotError(f"{path} has unknown or missing fields")
        url = _https_url(recrawl["url"], f"{path}.url")
        if url in recrawled_urls:
            raise GeoPilotError(f"{path}.url has more than one recrawl anchor")
        recrawled_urls.add(url)
        if allowed_urls is not None and url not in allowed_urls:
            raise GeoPilotError(f"{path}.url is outside the pilot")
        if recrawl["bot"] not in VERIFIED_INDEX_BOTS or recrawl["kind"] != "verified_index":
            raise GeoPilotError(f"{path} must be a verified search/index bot recrawl")
        observed = _timestamp(recrawl["observed_at_utc"], f"{path}.observed_at_utc")
        if deployment and (observed < deployment or observed > deployment + timedelta(days=14)):
            raise GeoPilotError(f"{path}.observed_at_utc is outside the 14-day anchor window")
        _evidence_ref(recrawl["evidence_ref"], f"{path}.evidence_ref")
    if checked_manifest is not None and deployment is not None and recrawled_urls:
        latest_anchor = max(
            _timestamp(recrawl["observed_at_utc"], "recrawl.observed_at_utc")
            for recrawl in data["recrawls"]
        )
        manifest_anchor = _timestamp(
            checked_manifest["recrawl_anchor"], "manifest.recrawl_anchor", nullable=True
        )
        if manifest_anchor != latest_anchor:
            raise GeoPilotError("manifest recrawl_anchor must match the latest URL recrawl")
        expected_deadline = min(
            latest_anchor + timedelta(days=28 if data["extension_count"] == 0 else 56),
            ceiling,
        )
        manifest_deadline = _timestamp(
            checked_manifest["observation_deadline"],
            "manifest.observation_deadline",
            nullable=True,
        )
        if manifest_deadline != expected_deadline:
            raise GeoPilotError("manifest observation_deadline does not match the finite schedule")
        if decision is not None and decision > manifest_deadline:
            raise GeoPilotError("decision_at exceeds the finite manifest deadline")
    elif checked_manifest is not None and deployment is not None:
        if (
            checked_manifest["recrawl_anchor"] is not None
            or checked_manifest["observation_deadline"] is not None
        ):
            raise GeoPilotError("manifest cannot record an anchor or deadline before a URL recrawl")

    if tuple(source.get("id") for source in data["sources"] if isinstance(source, Mapping)) != (
        REQUIRED_SOURCE_IDS
    ):
        raise GeoPilotError("sources must contain all four canonical source IDs in order")
    seen_source_ids: set[str] = set()
    for index, source in enumerate(data["sources"]):
        path = f"sources[{index}]"
        fields = {
            "id", "baseline_status", "baseline_window", "baseline_measurements", "status",
            "window", "timezone", "report_lag_days", "measurements", "baseline_scope",
            "followup_scope", "evidence_ref",
        }
        if not isinstance(source, Mapping) or set(source) != fields:
            raise GeoPilotError(f"{path} has unknown or missing fields")
        source_id = _nonempty(source["id"], f"{path}.id")
        if source_id not in SOURCE_MEASUREMENTS:
            raise GeoPilotError(f"{path}.id is unsupported")
        if source_id in seen_source_ids:
            raise GeoPilotError(f"{path}.id is duplicated")
        seen_source_ids.add(source_id)
        timezone_name = _nonempty(source["timezone"], f"{path}.timezone")
        try:
            provider_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise GeoPilotError(f"{path}.timezone is not an IANA timezone") from exc
        lag = source["report_lag_days"]
        if lag is not None and (type(lag) is not int or lag < 0):
            raise GeoPilotError(f"{path}.report_lag_days must be null or a non-negative integer")
        baseline_window = _validate_source_period(
            source,
            status_key="baseline_status",
            window_key="baseline_window",
            measurements_key="baseline_measurements",
            path=path,
            metrics=SOURCE_MEASUREMENTS[source_id],
        )
        followup_window = _validate_source_period(
            source,
            status_key="status",
            window_key="window",
            measurements_key="measurements",
            path=path,
            metrics=SOURCE_MEASUREMENTS[source_id],
        )
        if source["status"] == "available" and lag is None:
            raise GeoPilotError(f"{path}.report_lag_days is required when available")
        if baseline_window and followup_window:
            if baseline_window[1] > followup_window[0]:
                raise GeoPilotError(f"{path} baseline and follow-up windows overlap")
            baseline_duration = baseline_window[1].astimezone(
                provider_timezone
            ) - baseline_window[0].astimezone(provider_timezone)
            followup_duration = followup_window[1].astimezone(
                provider_timezone
            ) - followup_window[0].astimezone(provider_timezone)
            if baseline_duration != followup_duration:
                raise GeoPilotError(f"{path} baseline and follow-up windows must have equal duration")
        if source_id not in {"gsc_ai", "bing_ai"}:
            if source["baseline_scope"] is not None or source["followup_scope"] is not None:
                raise GeoPilotError(f"{path} non-account sources cannot carry report scope")
        else:
            if source["baseline_status"] == "available":
                if allowed_urls is None:
                    raise GeoPilotError(f"{path}.baseline_scope requires the pilot manifest")
                baseline_scope = _validate_report_scope(
                    source["baseline_scope"], f"{path}.baseline_scope", allowed_urls
                )
            elif source["baseline_scope"] is not None:
                raise GeoPilotError(f"{path}.baseline_scope must be null when unavailable")
            else:
                baseline_scope = None
            if source["status"] == "available":
                if allowed_urls is None:
                    raise GeoPilotError(f"{path}.followup_scope requires the pilot manifest")
                followup_scope = _validate_report_scope(
                    source["followup_scope"], f"{path}.followup_scope", allowed_urls
                )
            elif source["followup_scope"] is not None:
                raise GeoPilotError(f"{path}.followup_scope must be null when unavailable")
            else:
                followup_scope = None
            if baseline_scope is not None and followup_scope is not None:
                if (
                    baseline_scope["property"] != followup_scope["property"]
                    or baseline_scope["dimensions"] != followup_scope["dimensions"]
                    or set(baseline_scope["urls"]) != set(followup_scope["urls"])
                ):
                    raise GeoPilotError(f"{path} baseline and follow-up scopes must match")
        _evidence_ref(source["evidence_ref"], f"{path}.evidence_ref")

    weekly_windows: list[tuple[datetime, datetime]] = []
    for index, weekly in enumerate(data["nginx_weekly"]):
        path = f"nginx_weekly[{index}]"
        fields = {"start_utc", "end_utc", "coverage", "measurements", "evidence_ref"}
        if not isinstance(weekly, Mapping) or set(weekly) != fields:
            raise GeoPilotError(f"{path} has unknown or missing fields")
        start = _timestamp(weekly["start_utc"], f"{path}.start_utc")
        end = _timestamp(weekly["end_utc"], f"{path}.end_utc")
        if start >= end:
            raise GeoPilotError(f"{path} must be a non-empty [start,end) window")
        if weekly["coverage"] not in {"complete", "partial_coverage"}:
            raise GeoPilotError(f"{path}.coverage is invalid")
        weekly_metrics = {"estimated_answer_fetches", "ai_referrals"}
        _measurement_map(
            weekly["measurements"],
            f"{path}.measurements",
            weekly_metrics,
        )
        if weekly["coverage"] == "complete" and set(weekly["measurements"]) != weekly_metrics:
            raise GeoPilotError(f"{path} complete coverage requires all count metrics")
        if weekly["coverage"] == "partial_coverage" and not weekly["measurements"]:
            raise GeoPilotError(f"{path} partial coverage requires at least one count metric")
        _evidence_ref(weekly["evidence_ref"], f"{path}.evidence_ref")
        weekly_windows.append((start, end))
    for previous, current in zip(sorted(weekly_windows), sorted(weekly_windows)[1:], strict=False):
        if current[0] < previous[1]:
            raise GeoPilotError("nginx_weekly windows overlap")

    if not isinstance(data["reader_outcomes"], list) or not data["reader_outcomes"]:
        raise GeoPilotError("reader_outcomes requires an explicit available or unknown record")
    for index, outcome in enumerate(data["reader_outcomes"]):
        path = f"reader_outcomes[{index}]"
        fields = {"status", "window", "metrics", "evidence_ref"}
        if not isinstance(outcome, Mapping) or set(outcome) != fields:
            raise GeoPilotError(f"{path} has unknown or missing fields")
        if outcome["status"] not in {"available", "partial_coverage", "insufficient_data", "excluded"}:
            raise GeoPilotError(f"{path}.status is invalid")
        if not isinstance(outcome["metrics"], Mapping) or set(outcome["metrics"]) != READER_METRICS:
            raise GeoPilotError(f"{path}.metrics may contain only existing consented reader aggregates")
        if outcome["status"] in {"insufficient_data", "excluded"}:
            if outcome["window"] is not None or any(
                value is not None for value in outcome["metrics"].values()
            ):
                raise GeoPilotError(f"{path} unknown reader outcomes must remain null")
        else:
            _window(outcome["window"], f"{path}.window")
            present = [value is not None for value in outcome["metrics"].values()]
            if outcome["status"] == "available" and not all(present):
                raise GeoPilotError(f"{path} available reader outcomes require all metrics")
            if outcome["status"] == "partial_coverage" and not any(present):
                raise GeoPilotError(f"{path} partial reader outcomes require at least one metric")
        for metric, value in outcome["metrics"].items():
            if value is None:
                continue
            if metric == "pages_per_session":
                valid_ratio = (type(value) is int and value >= 0) or (
                    type(value) is float and math.isfinite(value) and value >= 0
                )
                if not valid_ratio:
                    raise GeoPilotError(
                        f"{path}.metrics.{metric} must be a finite non-negative number"
                    )
            elif type(value) is not int or value < 0:
                raise GeoPilotError(
                    f"{path}.metrics.{metric} must be a non-negative integer or null"
                )
        _evidence_ref(outcome["evidence_ref"], f"{path}.evidence_ref")
    if not isinstance(data["contaminated_units"], list) or any(
        not isinstance(unit, str) or not unit.strip() for unit in data["contaminated_units"]
    ):
        raise GeoPilotError("contaminated_units must be an array of identifiers")
    if allowed_urls is not None and any(unit not in allowed_urls for unit in data["contaminated_units"]):
        raise GeoPilotError("contaminated_units contains a URL outside the pilot")
    if data["disposition"] is not None and data["disposition"] not in DISPOSITIONS:
        raise GeoPilotError("disposition is invalid")
    if deployment is not None and checked_manifest is None:
        raise GeoPilotError("deployed observation validation requires the pilot manifest")
    return copy.deepcopy(dict(data)), checked_manifest


def _as_utc(value: str | datetime, path: str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise GeoPilotError(f"{path} must include a timezone")
        return value.astimezone(timezone.utc)
    parsed = _timestamp(value, path)
    assert parsed is not None
    return parsed


def evaluate_disposition(
    observation: Any,
    manifest: Any,
    *,
    as_of: str | datetime,
) -> dict[str, Any]:
    """Derive an evidence-eligible direction; it does not prove external causality."""
    data, checked_manifest = _validate_observation_structure(observation, manifest=manifest)
    assert checked_manifest is not None
    when = _as_utc(as_of, "as_of")
    deployment = _timestamp(data["deployment_at"], "deployment_at", nullable=True)
    ceiling = _timestamp(data["ceiling_at"], "ceiling_at", nullable=True)
    result: dict[str, Any] = {
        "disposition": None,
        "reason": "not_deployed",
        "account_directions": {},
        "as_of": when.isoformat().replace("+00:00", "Z"),
    }
    if deployment is None or ceiling is None:
        return result
    if when < deployment:
        raise GeoPilotError("as_of cannot precede deployment_at")
    if data["guardrails"]["status"] == "regression":
        result.update(disposition="rollback_recommended", reason="guardrail_regression")
        return result
    expected = _expected_urls(checked_manifest)
    anchors = {
        recrawl["url"]: _timestamp(recrawl["observed_at_utc"], "recrawl.observed_at_utc")
        for recrawl in data["recrawls"]
    }
    if when < deployment + timedelta(days=14) and set(anchors) != expected:
        result["reason"] = "anchor_window_open"
        return result
    if set(anchors) != expected:
        result.update(disposition="inconclusive", reason="partial_recrawl_coverage")
        return result
    contaminated = set(data["contaminated_units"])
    clean_anchors = [anchor for url, anchor in anchors.items() if url not in contaminated]
    if not clean_anchors:
        result.update(disposition="inconclusive", reason="no_clean_recrawl")
        return result
    if contaminated:
        result.update(disposition="inconclusive", reason="contaminated_scope")
        return result
    latest_anchor = max(clean_anchors)
    primary_at = latest_anchor + timedelta(days=28)
    extension_end = min(latest_anchor + timedelta(days=56), ceiling)
    manifest_deadline = _timestamp(
        checked_manifest["observation_deadline"],
        "manifest.observation_deadline",
    )
    if when < primary_at:
        result["reason"] = "day28_pending"
        return result
    if when > ceiling:
        result.update(disposition="inconclusive", reason="ceiling_reached")
        return result
    if when > manifest_deadline:
        result.update(disposition="inconclusive", reason="deadline_passed")
        return result
    if data["extension_count"] == 1 and when < extension_end:
        result["reason"] = "reporting_extension_open"
        return result

    sources = {source["id"]: source for source in data["sources"]}
    account_ids = {"gsc_ai", "bing_ai"}
    incomplete_accounts = [
        source_id
        for source_id in account_ids
        if sources[source_id]["baseline_status"] != "available"
        or sources[source_id]["status"] != "available"
    ]
    if len(incomplete_accounts) == len(account_ids):
        result.update(disposition="inconclusive", reason="account_sources_unavailable")
        return result
    if any(outcome["status"] != "available" for outcome in data["reader_outcomes"]):
        result.update(disposition="inconclusive", reason="reader_coverage_incomplete")
        return result
    reader_windows = sorted(
        _window(outcome["window"], "reader_outcomes.window")
        for outcome in data["reader_outcomes"]
    )
    if (
        reader_windows[0][0] > latest_anchor
        or reader_windows[-1][1] != when
        or any(window[1] > when for window in reader_windows)
        or any(
            current[0] > previous[1]
            for previous, current in zip(reader_windows, reader_windows[1:], strict=False)
        )
    ):
        result.update(disposition="inconclusive", reason="reader_window_incomplete")
        return result
    weekly = sorted(
        (
            _timestamp(item["start_utc"], "nginx.start_utc"),
            _timestamp(item["end_utc"], "nginx.end_utc"),
            item["coverage"],
        )
        for item in data["nginx_weekly"]
    )
    if (
        not weekly
        or weekly[0][0] > latest_anchor
        or weekly[-1][1] != when
        or any(item[1] > when for item in weekly)
        or any(item[2] != "complete" for item in weekly)
        or any(current[0] > previous[1] for previous, current in zip(weekly, weekly[1:], strict=False))
    ):
        result.update(disposition="inconclusive", reason="nginx_coverage_incomplete")
        return result
    if data["guardrails"]["status"] != "pass":
        result.update(disposition="inconclusive", reason="guardrails_unverified")
        return result

    decision_metrics = {
        "gsc_ai": {"impressions"},
        "bing_ai": {"citations", "cited_pages"},
    }
    directions: dict[str, str] = {}
    for source_id, metrics in decision_metrics.items():
        source = sources[source_id]
        if source["baseline_status"] != "available" or source["status"] != "available":
            continue
        baseline_start, baseline_end = _window(
            source["baseline_window"], f"{source_id}.baseline_window"
        )
        followup_start, followup_end = _window(source["window"], f"{source_id}.window")
        lag = timedelta(days=source["report_lag_days"])
        provider_timezone = ZoneInfo(source["timezone"])
        baseline_duration = baseline_end.astimezone(provider_timezone) - baseline_start.astimezone(
            provider_timezone
        )
        followup_duration = followup_end.astimezone(provider_timezone) - followup_start.astimezone(
            provider_timezone
        )
        if (
            baseline_end > deployment
            or followup_start < latest_anchor
            or followup_end > when
            or when < followup_end + lag
            or baseline_duration != followup_duration
        ):
            continue
        for metric in metrics:
            before = source["baseline_measurements"][metric]
            after = source["measurements"][metric]
            directions[f"{source_id}.{metric}"] = (
                "up" if after > before else "down" if after < before else "flat"
            )
    result["account_directions"] = directions
    if not directions:
        result.update(disposition="inconclusive", reason="no_comparable_account_window")
    elif "down" in directions.values():
        result.update(disposition="inconclusive", reason="mixed_or_down_account_direction")
    elif "up" in directions.values():
        result.update(disposition="expansion_candidate", reason="eligible_account_direction_up")
    else:
        result.update(disposition="inconclusive", reason="flat_account_direction")
    return result


def validate_observation(observation: Any, *, manifest: Any | None = None) -> dict[str, Any]:
    data, _ = _validate_observation_structure(observation, manifest=manifest)
    if data["disposition"] is not None:
        if manifest is None:
            raise GeoPilotError("a stored disposition requires the pilot manifest")
        evaluation = evaluate_disposition(data, manifest, as_of=data["decision_at"])
        if evaluation["disposition"] != data["disposition"]:
            raise GeoPilotError("stored disposition does not match evidence evaluation")
    return data


def plan_rollback(manifest: Any, current_posts: Any) -> dict[str, Any]:
    """Return a field-only rollback plan without mutating either input or disk."""
    checked = validate_manifest(manifest, posts=current_posts)
    posts_by_slug = _posts_by_slug(current_posts)
    conflicts: list[dict[str, str]] = []
    updates: list[dict[str, Any]] = []
    for edit in checked["edits"]:
        current = posts_by_slug[edit["slug"]].get(edit["field"])
        current_hash = value_sha256(current)
        if current_hash != edit["applied_hash"]:
            conflicts.append(
                {"slug": edit["slug"], "field": edit["field"], "current_hash": current_hash}
            )
        else:
            updates.append(
                {
                    "slug": edit["slug"],
                    "field": edit["field"],
                    "value": copy.deepcopy(edit["before_value"]),
                    "result_hash": edit["before_hash"],
                }
            )
    if conflicts:
        return {"status": "rollback_conflict", "updates": [], "conflicts": conflicts}
    return {"status": "ready", "updates": updates, "conflicts": []}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, default=MANIFEST_PATH)
    parser.add_argument("observation", nargs="?", type=Path, default=OBSERVATION_PATH)
    args = parser.parse_args()
    try:
        manifest = validate_manifest(args.manifest)
        validate_observation(args.observation, manifest=manifest)
    except (OSError, json.JSONDecodeError, GeoPilotError) as exc:
        parser.error(str(exc))
    print("GEO pilot manifest and observation are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
