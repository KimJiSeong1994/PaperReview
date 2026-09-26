from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.recommendation_state import RecommendationPolicy, RecommendationState
from src.recommendations_artifacts import (
    DELIVERY_SCHEMA,
    POLICY_VERSION,
    DeliveryValidationError,
    load_recommendation_artifact,
    read_delivery,
    validate_delivery,
)

NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)


def delivery(incarnation="account-A", *, run_id="run-1", when=NOW, count=8):
    return {
        "schema": DELIVERY_SCHEMA,
        "producer": "common_local",
        "account_incarnation": incarnation,
        "run_id": run_id,
        "run_at": when.isoformat(),
        "cutoff": when.isoformat(),
        "code_hash": "a" * 64,
        "config_hash": "b" * 64,
        "input_manifest_hash": "c" * 64,
        "policy_version": POLICY_VERSION,
        "ranker_version": "heuristic_v2",
        "scoring_mode": "v2",
        "status": "ready" if count else "empty",
        "source_statuses": {"local_public": "ready", "openclaw": "disabled"},
        "degraded_reasons": [],
        "items": [
            {
                "canonical_key": f"doi:10.1234/paper-{n}",
                "doi": f"10.1234/paper-{n}",
                "title": f"Paper {n}",
                "authors": ["Kim", "Lee"],
                "year": 2025,
                "publication_date": "2025-01-01",
                "url": f"https://example.test/paper-{n}",
                "score": float(n),
                "final_rank": n,
                "reason": "서지정보 기반 탐색 추천",
                "candidate_sources": ["local_public"],
                "score_breakdown": {"metadata_completeness": 0.8},
            }
            for n in range(1, count + 1)
        ],
    }


def save(root, raw, *, owner=None, name=None):
    directory = root / (owner or raw["account_incarnation"])
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ((name or raw["run_id"]) + ".json")
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def load(root, *, incarnation="account-A", now=NOW, policy=None):
    return load_recommendation_artifact(
        root,
        incarnation,
        5,
        policy=policy or RecommendationPolicy(incarnation),
        now=now,
    )


def test_common_order_is_preserved_not_score_sorted_and_metadata_survives(tmp_path):
    save(tmp_path, delivery())
    response = load(tmp_path)
    assert response["total_count"] == response["unread_count"] == 8
    assert [row["final_rank"] for row in response["items"]] == [1, 2, 3, 4, 5]
    assert [row["score"] for row in response["items"]] == [1, 2, 3, 4, 5]
    assert response["items"][0]["authors"] == ["Kim", "Lee"]
    assert response["items"][0]["publication_date"] == "2025-01-01"
    assert response["latest_run_at"] == NOW.isoformat()
    assert response["source_statuses"]["openclaw"] == "disabled"


def test_missing_root_and_other_account_never_leak(tmp_path):
    assert load(tmp_path / "absent")["items"] == []
    save(tmp_path, delivery("account-B"))
    assert load(tmp_path)["items"] == []
    assert load(tmp_path)["total_count"] == 0


@pytest.mark.parametrize(
    "raw",
    [
        {"user_id": "account-A", "variants": {"soul": [{"title": "Private"}]}},
        {"variants": {"soul": [{"title": "Unscoped"}]}},
        [],
        7,
        None,
    ],
)
def test_legacy_external_and_scalar_payloads_never_serve(tmp_path, raw):
    save(tmp_path, raw, owner="account-A", name="run-1")
    with pytest.raises(DeliveryValidationError, match="invalid_artifact"):
        load(tmp_path)


def test_legacy_username_directory_is_not_an_identity_fallback(tmp_path):
    legacy = tmp_path / "alice" / "2026-09-25"
    legacy.mkdir(parents=True)
    (legacy / "raw.json").write_text(
        json.dumps({"variants": {"daily": [{"title": "Private"}]}})
    )
    assert load(tmp_path, incarnation="current-incarnation")["items"] == []


def test_latest_uses_validated_run_time_never_mtime(tmp_path):
    older = save(tmp_path, delivery(run_id="old", when=NOW - timedelta(hours=1)))
    save(tmp_path, delivery(run_id="new"))
    os.utime(older, (NOW.timestamp() + 5000, NOW.timestamp() + 5000))
    assert load(tmp_path)["run_id"] == "new"


@pytest.mark.parametrize(
    "hours,state,count",
    [(35.99, "ready", 5), (36, "stale", 5), (71.99, "stale", 5), (72, "expired", 0)],
)
def test_delivery_freshness_boundary_is_not_publication_age(
    tmp_path, hours, state, count
):
    save(tmp_path, delivery())
    response = load(tmp_path, now=NOW + timedelta(hours=hours))
    assert response["state"] == state
    assert len(response["items"]) == count
    if count:
        assert response["items"][0]["year"] == 2025


def test_current_policy_refills_and_separates_unread_from_total(tmp_path):
    save(tmp_path, delivery())
    policy = RecommendationPolicy(
        "account-A",
        hidden=frozenset({"doi:10.1234/paper-2", "doi:10.1234/paper-6"}),
        seen=frozenset({"doi:10.1234/paper-1"}),
    )
    response = load(tmp_path, policy=policy)
    assert [row["final_rank"] for row in response["items"]] == [1, 3, 4, 5, 7]
    assert response["total_count"] == 6
    assert response["unread_count"] == 5
    assert response["items"][0]["seen"]


def test_wrong_policy_identity_fails_closed(tmp_path):
    save(tmp_path, delivery())
    with pytest.raises(DeliveryValidationError, match="wrong_policy_owner"):
        load(tmp_path, policy=RecommendationPolicy("account-B"))


@pytest.mark.parametrize(
    "change",
    [
        lambda raw: raw.update(account_incarnation="account-B"),
        lambda raw: raw.update(producer="openclaw"),
        lambda raw: raw.update(run_at="invalid"),
        lambda raw: raw.update(run_at=NOW.replace(tzinfo=None).isoformat()),
        lambda raw: raw.update(run_at=(NOW + timedelta(seconds=1)).isoformat()),
        lambda raw: raw.update(code_hash="unknown"),
        lambda raw: raw["items"][0].update(score=float("nan")),
        lambda raw: raw["items"][0].update(score=float("inf")),
        lambda raw: raw["items"][0].update(final_rank=True),
        lambda raw: raw["items"][1].update(final_rank=1),
        lambda raw: raw["items"][1].update(
            canonical_key=raw["items"][0]["canonical_key"]
        ),
        lambda raw: raw["items"][0].update(year=2027, publication_date="2027-01-01"),
    ],
)
def test_malformed_identity_manifest_rank_score_and_time_rejected(tmp_path, change):
    raw = delivery()
    change(raw)
    save(tmp_path, raw, owner="account-A", name="run-1")
    with pytest.raises(DeliveryValidationError):
        load(tmp_path)


def test_duplicate_canonical_records_rejected_instead_of_reader_regrouping(tmp_path):
    raw = delivery()
    raw["items"][1] = {**raw["items"][0], "final_rank": 2}
    save(tmp_path, raw)
    with pytest.raises(DeliveryValidationError):
        load(tmp_path)


def test_private_profile_fields_are_not_forwarded_from_delivery(tmp_path):
    raw = delivery()
    raw["profile_summary"] = {"top_terms": ["private-marker"]}
    raw["items"][0].update(
        matched_terms=["private-marker"], notes="private-marker", query="private-marker"
    )
    save(tmp_path, raw)
    response = load(tmp_path)
    assert "private-marker" not in json.dumps(response)
    assert response["items"][0]["score_breakdown"] == {"metadata_completeness": 0.8}


def test_reader_has_no_all_user_glob_and_rejects_owner_symlinks(tmp_path, monkeypatch):
    root = tmp_path / "root"
    save(root, delivery("account-B"))
    monkeypatch.setattr(
        Path, "glob", lambda *args, **kwargs: pytest.fail("must not glob all users")
    )
    assert load(root)["items"] == []
    (root / "account-A").symlink_to(root / "account-B", target_is_directory=True)
    with pytest.raises(OSError):
        load(root)


def test_candidate_symlink_and_oversized_delivery_are_rejected(tmp_path, monkeypatch):
    import src.recommendations_artifacts as module

    path = save(tmp_path, delivery())
    outside = tmp_path / "outside.json"
    path.rename(outside)
    path.symlink_to(outside)
    with pytest.raises(DeliveryValidationError):
        load(tmp_path)
    path.unlink()
    save(tmp_path, delivery())
    monkeypatch.setattr(module, "MAX_DELIVERY_BYTES", 20)
    with pytest.raises(DeliveryValidationError):
        load(tmp_path)


def test_invalid_new_file_uses_safe_previous_delivery_with_disclosure(tmp_path):
    save(tmp_path, delivery(run_id="previous", when=NOW - timedelta(hours=1)))
    save(tmp_path, {"run_id": "broken"}, owner="account-A")
    response = load(tmp_path)
    assert response["run_id"] == "previous"
    assert response["state"] == "degraded"
    assert "invalid_artifact" in response["degraded_reasons"]


@pytest.fixture
def api_delivery(client, auth_headers, tmp_path, monkeypatch):
    import routers.recommendations as module
    from routers.deps.storage import _get_user_db

    authority = _get_user_db()
    incarnation = authority.get("test-admin")["account_incarnation"]
    RecommendationState.initialize(
        Path(os.environ["EVENTS_DB_PATH"]), authority=authority
    )
    root = tmp_path / "delivery"
    save(root, delivery(incarnation))
    monkeypatch.setenv("RECOMMENDATIONS_ARTIFACTS_DIR", str(root))
    monkeypatch.setattr(module, "utc_now", lambda: NOW)
    return incarnation, root, module


def test_optional_provider_caches_are_fixture_owned(monkeypatch):
    from src.collector.paper import google_scholar_searcher, similarity_calculator

    repository_cache = Path(google_scholar_searcher.__file__).with_name(
        ".google_scholar_cookies.pkl"
    )
    original_exists = Path.exists

    def isolated_exists(path):
        assert path != repository_cache, "Must not inspect repository credentials"
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", isolated_exists)
    provider = google_scholar_searcher.GoogleScholarSearcher()
    try:
        assert (
            provider.cookies_file
            == Path(os.environ["DATA_DIR"]) / "scholar-cookies.pkl"
        )
        assert not provider.cookies_file.exists()
    finally:
        provider.session.close()
    calculator = similarity_calculator.SimilarityCalculator()
    try:
        assert (
            calculator._cache_db_path
            == Path(os.environ["DATA_DIR"]) / "embedding-cache.db"
        )
        assert calculator._cache_db_path.is_file()
    finally:
        calculator._db_conn.close()
        calculator.client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("health", ["ready", "empty", "disabled", "error", "degraded"])
async def test_fixture_collector_through_common_publisher_to_authenticated_get(
    client, auth_headers, tmp_path, monkeypatch, health
):
    import routers.recommendations as module
    from routers.deps.storage import _get_user_db
    from src.daily_recommendations import generate_daily_recommendations
    from src.events.event_bus import EventBus
    from src.related_paper_wiki import PUBLIC_SEEDS, collect_review_build_wiki

    authority = _get_user_db()
    events = Path(os.environ["EVENTS_DB_PATH"])
    EventBus(events, account_authority=authority).close()
    RecommendationState.initialize(events, authority=authority)
    root = tmp_path / "fresh-delivery"
    candidates = tmp_path / "fresh-candidates"
    monkeypatch.setenv("RECOMMENDATIONS_ARTIFACTS_DIR", str(root))
    monkeypatch.setattr(module, "utc_now", lambda: NOW)
    calls = []

    def provider(seed, deadline):
        calls.append(seed)
        if health == "error" or (health == "degraded" and seed == PUBLIC_SEEDS[0]):
            return [], [{"status": "error"}]
        if health == "empty":
            return [], [{"status": "searched_empty"}]
        seed_index = PUBLIC_SEEDS.index(seed)
        return [
            {
                "title": f"Synthetic health fixture {seed_index}-{index}",
                "abstract": f"This paper studies retrieval method {seed_index}-{index}.",
                "doi": f"10.1234/health-{seed_index}-{index}",
                "authors": ["Fixture Author"],
                "year": NOW.year,
            }
            for index in range(2)
        ], [{"status": "searched"}]

    acquired = collect_review_build_wiki(
        candidate_root=candidates,
        final_root=root,
        run_at=NOW.isoformat(),
        source_qualified=health != "disabled",
        attempt=provider,
        clock=lambda: 0,
    )
    assert acquired["acquisition_status"] == health
    assert (
        len(calls)
        == {"ready": 3, "empty": 3, "disabled": 0, "error": 6, "degraded": 4}[health]
    )
    published = generate_daily_recommendations(
        users_db=authority._db_path,
        candidate_root=candidates,
        events_db=events,
        artifacts_dir=root,
        usernames=["test-admin"],
        run_at=NOW.isoformat(),
        min_score=0,
    )
    assert published["publish_success"] == 1
    assert published["provider_calls"] == published["paid_calls"] == 0
    response = await client.get(
        "/api/recommendations/notifications", headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source_statuses"]["local_public"] == health
    for item in body["items"]:
        paper_id = item["doi"].removeprefix("10.1234/health-")
        assert item["abstract"] == f"This paper studies retrieval method {paper_id}."
    assert body["run_id"]
    assert body["freshness"] == "fresh"
    assert len(body["items"]) == {"ready": 5, "degraded": 4}.get(health, 0)
    assert body["total_count"] == {"ready": 6, "degraded": 4}.get(health, 0)
    if health == "error":
        assert "source_error" in body["degraded_reasons"]
        # Empty describes card availability, not healthy acquisition:
        # source_statuses and source_error must still disclose the failure.
        assert body["state"] == "empty"
    elif health == "degraded":
        assert "limited_coverage" in body["degraded_reasons"]
        assert body["state"] == "degraded"
    elif health == "disabled":
        assert "source_disabled" in body["degraded_reasons"]
    else:
        assert "source_error" not in body["degraded_reasons"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_field,provider_id",
    [
        ("openalex_id", "W123456789"),
        ("semantic_scholar_id", "a" * 40),
        ("pmid", "12345678"),
    ],
)
async def test_provider_only_card_through_publish_get_exposure_save_and_review(
    client, auth_headers, tmp_path, monkeypatch, provider_field, provider_id
):
    import sqlite3
    from functools import partial

    from app.DeepAgent import workspace_manager
    from routers import reviews
    from routers.deps.storage import _get_bookmark_db, _get_user_db
    from src.daily_recommendations import generate_daily_recommendations
    from src.events.event_bus import EventBus
    from src.recommendation_candidates import normalize_candidate
    from src.related_paper_wiki import collect_review_build_wiki

    now = datetime.now(timezone.utc)
    authority = _get_user_db()
    incarnation = authority.get("test-admin")["account_incarnation"]
    events = Path(os.environ["EVENTS_DB_PATH"])
    EventBus(events, account_authority=authority).close()
    RecommendationState.initialize(events, authority=authority)
    root = tmp_path / "provider-delivery"
    candidates = tmp_path / "provider-candidates"
    monkeypatch.setenv("RECOMMENDATIONS_ARTIFACTS_DIR", str(root))
    source_paper = {
        "title": "Provider-only boundary fixture",
        "authors": ["Fixture Author"],
        "year": now.year,
        provider_field: provider_id,
    }

    def provider(seed, deadline):
        return [dict(source_paper)], [{"status": "searched"}]

    acquired = collect_review_build_wiki(
        candidate_root=candidates,
        final_root=root,
        run_at=now.isoformat(),
        source_qualified=True,
        attempt=provider,
        clock=lambda: 0,
    )
    assert acquired["acquisition_status"] == "ready"
    published = generate_daily_recommendations(
        users_db=authority._db_path,
        candidate_root=candidates,
        events_db=events,
        artifacts_dir=root,
        usernames=["test-admin"],
        run_at=now.isoformat(),
        min_score=0,
    )
    assert published["publish_success"] == 1
    assert published["provider_calls"] == published["paid_calls"] == 0
    response = await client.get(
        "/api/recommendations/notifications",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    notification = response.json()
    assert len(notification["items"]) == 1
    card = notification["items"][0]
    assert card[provider_field] == provider_id
    assert card["canonical_key"] == normalize_candidate(source_paper).canonical_key
    exposure = await client.post(
        "/api/recommendations/exposure",
        headers=auth_headers,
        json={
            "run_id": notification["run_id"],
            "canonical_key": card["canonical_key"],
            "visible_fraction": 0.5,
            "visible_ms": 1000,
        },
    )
    assert exposure.status_code == 200, exposure.text

    # Both producers receive bibliographic metadata exclusively from the
    # authenticated response, never the source fixture or caller identity claims.
    fields = {
        "title",
        "authors",
        "year",
        "venue",
        "doi",
        "arxiv_id",
        "openalex_id",
        "semantic_scholar_id",
        "pmid",
        "url",
        "pdf_url",
    }
    paper = {
        key: value for key, value in card.items() if key in fields and value is not None
    }
    saved = await client.post(
        "/api/bookmarks/from-paper",
        headers=auth_headers,
        json=paper,
    )
    assert saved.status_code == 200, saved.text
    bookmark = saved.json()
    assert (
        _get_bookmark_db().get_by_id(bookmark["id"])["papers"][0][provider_field]
        == provider_id
    )

    reviews.limiter._storage.reset()
    workspace_root = tmp_path / "review-workspace"
    monkeypatch.setattr(
        workspace_manager,
        "WorkspaceManager",
        partial(workspace_manager.WorkspaceManager, base_path=str(workspace_root)),
    )

    def bounded_review(session_id, paper_ids, model, workspace, papers_data):
        assert papers_data == [paper]
        (workspace.session_path / "reports" / "report.md").write_text(
            "# Local review", encoding="utf-8"
        )
        return {
            "status": "completed",
            "papers_reviewed": 1,
            "workspace_path": str(workspace.session_path),
        }

    monkeypatch.setattr(reviews, "run_fast_review", bounded_review)
    started = await client.post(
        "/api/deep-review",
        headers=auth_headers,
        json={
            "paper_ids": [card["canonical_key"]],
            "papers": [paper],
            "fast_mode": True,
        },
    )
    assert started.status_code == 200, started.text
    review = started.json()
    try:
        assert reviews.review_sessions[review["session_id"]]["status"] == "completed"
        for body, outcome_id in (
            (bookmark, bookmark["id"]),
            (review, review["session_id"]),
        ):
            credit = body["recommendation_attribution"][0]
            assert credit["credited"] is True
            assert credit["canonical_key"] == card["canonical_key"]
            assert credit["run_id"] == notification["run_id"]
            assert credit["outcome_id"] == outcome_id
        with sqlite3.connect(events) as conn:
            rows = conn.execute(
                "SELECT kind,outcome_id,canonical_key,credited FROM recommendation_outcomes "
                "WHERE incarnation=?",
                (incarnation,),
            ).fetchall()
        assert set(rows) == {
            ("save", bookmark["id"], card["canonical_key"], 1),
            ("review_start", review["session_id"], card["canonical_key"], 1),
        }
    finally:
        with reviews.review_sessions_lock:
            reviews.review_sessions.pop(review["session_id"], None)


@pytest.mark.asyncio
async def test_api_feedback_is_durable_even_when_analytics_fails_and_refills(
    client, auth_headers, api_delivery, monkeypatch
):
    _, _, module = api_delivery

    def failed_emission(event):
        raise RuntimeError("injected analytics outage")

    monkeypatch.setattr(module, "emit_or_warn", failed_emission)
    body = {
        "run_id": "run-1",
        "canonical_key": "doi:10.1234/paper-2",
        "action": "hide",
        "request_id": "hide-2",
    }
    response = await client.post(
        "/api/recommendations/feedback", json=body, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["tracked"] is True
    notification = await client.get(
        "/api/recommendations/notifications", headers=auth_headers
    )
    assert notification.status_code == 200, notification.text
    assert [row["final_rank"] for row in notification.json()["items"]] == [
        1,
        3,
        4,
        5,
        6,
    ]
    assert notification.json()["total_count"] == 7


@pytest.mark.asyncio
async def test_action_receipts_prevent_reapply_and_duplicate_analytics(
    client, auth_headers, api_delivery, monkeypatch
):
    _, _, module = api_delivery
    emitted = []
    monkeypatch.setattr(module, "emit_or_warn", emitted.append)
    hidden = {
        "run_id": "run-1",
        "canonical_key": "doi:10.1234/paper-2",
        "action": "hide",
        "request_id": "hide-2",
    }
    first = await client.post(
        "/api/recommendations/feedback", json=hidden, headers=auth_headers
    )
    undo = {**hidden, "action": "undo", "undo_action": "hide", "request_id": "undo-2"}
    assert (
        await client.post(
            "/api/recommendations/feedback", json=undo, headers=auth_headers
        )
    ).status_code == 200
    replay = await client.post(
        "/api/recommendations/feedback", json=hidden, headers=auth_headers
    )
    assert replay.json() == first.json()
    assert len(emitted) == 2
    conflict = await client.post(
        "/api/recommendations/feedback",
        json={**hidden, "action": "interested"},
        headers=auth_headers,
    )
    assert conflict.status_code == 409
    response = await client.get(
        "/api/recommendations/notifications", headers=auth_headers
    )
    assert [row["final_rank"] for row in response.json()["items"]] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_owned_hide_can_be_undone_after_delivery_expiry(
    client, auth_headers, api_delivery, monkeypatch
):
    _, _, module = api_delivery
    monkeypatch.setattr(module, "emit_or_warn", lambda event: None)
    body = {
        "run_id": "run-1",
        "canonical_key": "doi:10.1234/paper-2",
        "action": "hide",
        "request_id": "hide-2",
    }
    assert (
        await client.post(
            "/api/recommendations/feedback", json=body, headers=auth_headers
        )
    ).status_code == 200
    monkeypatch.setattr(module, "utc_now", lambda: NOW + timedelta(days=4))
    undo = {**body, "action": "undo", "undo_action": "hide", "request_id": "undo-2"}
    response = await client.post(
        "/api/recommendations/feedback", json=undo, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert (
        await client.post(
            "/api/recommendations/feedback", json=undo, headers=auth_headers
        )
    ).json() == response.json()


@pytest.mark.asyncio
async def test_read_state_and_visibility_have_distinct_effects(
    client, auth_headers, api_delivery, monkeypatch
):
    _, _, module = api_delivery
    monkeypatch.setattr(module, "emit_or_warn", lambda event: None)
    identity = {"run_id": "run-1", "canonical_key": "doi:10.1234/paper-1"}
    exposure = {**identity, "visible_fraction": 0.5, "visible_ms": 1000}
    first = await client.post(
        "/api/recommendations/exposure", json=exposure, headers=auth_headers
    )
    second = await client.post(
        "/api/recommendations/exposure", json=exposure, headers=auth_headers
    )
    assert first.json() == {"tracked": True, "recorded": True}
    assert second.json() == {"tracked": True, "recorded": False}
    before = (
        await client.get("/api/recommendations/notifications", headers=auth_headers)
    ).json()
    assert before["unread_count"] == 8 and len(before["items"]) == 5
    marked = await client.post(
        "/api/recommendations/read-state",
        json={**identity, "action": "seen", "request_id": "seen-1"},
        headers=auth_headers,
    )
    assert marked.status_code == 200, marked.text
    after = (
        await client.get("/api/recommendations/notifications", headers=auth_headers)
    ).json()
    assert after["unread_count"] == 7 and after["total_count"] == 8
    assert after["items"][0]["seen"] is True


@pytest.mark.asyncio
async def test_forged_actions_and_nonvisible_exposure_are_rejected(
    client, auth_headers, api_delivery
):
    body = {
        "run_id": "run-1",
        "canonical_key": "doi:10.1234/unknown",
        "action": "hide",
        "request_id": "forged",
    }
    assert (
        await client.post(
            "/api/recommendations/feedback", json=body, headers=auth_headers
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/recommendations/feedback",
            json={**body, "action": "raw_query"},
            headers=auth_headers,
        )
    ).status_code == 422
    exposure = {
        "run_id": "run-1",
        "canonical_key": "doi:10.1234/paper-6",
        "visible_fraction": 1,
        "visible_ms": 1000,
    }
    assert (
        await client.post(
            "/api/recommendations/exposure", json=exposure, headers=auth_headers
        )
    ).status_code == 409
    exposure.update(canonical_key="doi:10.1234/paper-1", visible_ms=999)
    assert (
        await client.post(
            "/api/recommendations/exposure", json=exposure, headers=auth_headers
        )
    ).status_code == 422


@pytest.mark.asyncio
async def test_policy_failure_never_serves_cached_or_raw_recommendations(
    client, auth_headers, api_delivery, monkeypatch
):
    import sqlite3

    _, _, module = api_delivery
    monkeypatch.setattr(
        module,
        "_state",
        lambda: (_ for _ in ()).throw(sqlite3.OperationalError("injected")),
    )
    response = await client.get(
        "/api/recommendations/notifications", headers=auth_headers
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "policy_unavailable"
    assert "Paper" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "damage",
    [
        "missing_file",
        "missing_actions",
        "foreign_store",
        "bad_receipt",
        "nonobject_receipt",
    ],
)
async def test_fresh_http_requests_fail_closed_after_acknowledged_policy_loss(
    client, auth_headers, api_delivery, tmp_path, monkeypatch, damage
):
    import sqlite3
    from src.storage.user_db import UserDB

    _, _, module = api_delivery
    monkeypatch.setattr(module, "emit_or_warn", lambda event: None)
    body = {
        "run_id": "run-1",
        "canonical_key": "doi:10.1234/paper-1",
        "action": "hide",
        "request_id": "acknowledged-hide",
    }
    acknowledged = await client.post(
        "/api/recommendations/feedback", json=body, headers=auth_headers
    )
    assert acknowledged.status_code == 200
    before = await client.get(
        "/api/recommendations/notifications", headers=auth_headers
    )
    assert body["canonical_key"] not in [
        row["canonical_key"] for row in before.json()["items"]
    ]
    path = Path(os.environ["EVENTS_DB_PATH"])
    if damage == "missing_file":
        path.unlink()
    elif damage == "missing_actions":
        with sqlite3.connect(path) as conn:
            conn.execute("DROP TABLE recommendation_actions")
    elif damage == "foreign_store":
        foreign_path = tmp_path / "foreign-events.db"
        foreign_authority = UserDB(tmp_path / "foreign-users.db")
        RecommendationState.initialize(foreign_path, authority=foreign_authority)
        path.write_bytes(foreign_path.read_bytes())
    else:
        from routers.deps.storage import _get_user_db

        value = "{" if damage == "bad_receipt" else "null"
        with sqlite3.connect(_get_user_db()._db_path) as conn:
            conn.execute(
                "UPDATE account_store_meta SET value=? WHERE key='policy_store'",
                (value,),
            )

    for method, endpoint, kwargs in [
        ("get", "/api/recommendations/notifications", {}),
        ("post", "/api/recommendations/feedback", {"json": body}),
    ]:
        response = await getattr(client, method)(
            endpoint, headers=auth_headers, **kwargs
        )
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "policy_unavailable"
        assert "Paper" not in response.text
    if damage == "missing_file":
        assert not path.exists()
    elif damage == "missing_actions":
        with sqlite3.connect(path) as conn:
            assert (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='recommendation_actions'"
                ).fetchone()
                is None
            )


@pytest.mark.asyncio
async def test_recreated_account_never_reads_old_delivery_or_uses_old_token(
    client, auth_headers, api_delivery
):
    from tests.conftest import _make_test_token
    from routers.deps.storage import _get_user_db

    old, _, _ = api_delivery
    db = _get_user_db()
    db.begin_delete("test-admin", old)
    db.finish_delete("test-admin", old, cleanup_succeeded=True)
    replacement = db.create_account("test-admin", {"role": "admin"})
    assert replacement["account_incarnation"] != old
    assert (
        await client.get("/api/recommendations/notifications", headers=auth_headers)
    ).status_code == 401
    headers = {"Authorization": f"Bearer {_make_test_token()}"}
    response = await client.get("/api/recommendations/notifications", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
