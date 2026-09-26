"""Real JWT/authority coverage of review production, persistence and access."""

import json
from functools import partial
from pathlib import Path

import pytest
from tests.test_bookmark_incarnation import (
    qualified_outcome_store as qualified_outcome_store,
)


def _auth(username):
    from routers.deps.storage import _get_user_db
    from tests.conftest import _make_test_token

    db = _get_user_db()
    if db.get(username) is None:
        db.create_account(username, {"password_hash": "x", "role": "user"})
    return {"Authorization": f"Bearer {_make_test_token(username, role='user')}"}


@pytest.fixture
def local_review(client, tmp_path, monkeypatch):
    from app.DeepAgent import workspace_manager
    from routers import reviews
    from routers.deps import storage

    # Independent API scenarios must not share the in-memory rate-limit bucket.
    reviews.limiter._storage.reset()
    root = tmp_path / "workspace"
    monkeypatch.setattr(
        workspace_manager,
        "WorkspaceManager",
        partial(workspace_manager.WorkspaceManager, base_path=str(root)),
    )
    monkeypatch.setattr(storage, "WORKSPACE_DIR", root)

    # Keep the actual endpoint and background orchestration; replace only the
    # expensive review implementation with a bounded local report producer.
    def fake_review(session_id, paper_ids, model, workspace, papers_data):
        (workspace.session_path / "reports" / "report.md").write_text(
            "# Test Report\nBody content.", encoding="utf-8"
        )
        return {
            "status": "completed",
            "papers_reviewed": len(paper_ids),
            "workspace_path": str(workspace.session_path),
        }

    monkeypatch.setattr(reviews, "run_fast_review", fake_review)
    yield reviews, storage, fake_review
    with reviews.review_sessions_lock:
        for sid, session in list(reviews.review_sessions.items()):
            if str(root) in session.get("workspace_path", ""):
                reviews.review_sessions.pop(sid)


async def _start(client, headers):
    response = await client.post(
        "/api/deep-review",
        headers=headers,
        json={"paper_ids": ["p1"], "fast_mode": True},
    )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


async def _bookmark(client, sid, headers):
    return await client.post(
        "/api/bookmarks",
        headers=headers,
        json={"session_id": sid, "title": "paper", "report_markdown": "report"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("recreated", [False, True])
async def test_review_start_qualified_attribution(
    client, local_review, qualified_outcome_store, monkeypatch, recreated
):
    import sqlite3

    reviews, _, _ = local_review
    users, incarnation, headers, path, _, paper, key, expose = qualified_outcome_store
    expose()
    if recreated:
        record_started = reviews.record_job_started

        async def replace_after_acceptance(*args):
            result = await record_started(*args)
            users.begin_delete("outcome-owner", incarnation)
            users.finish_delete("outcome-owner", incarnation, cleanup_succeeded=True)
            users.create_account("outcome-owner", {"role": "user"})
            return result

        monkeypatch.setattr(reviews, "record_job_started", replace_after_acceptance)
    response = await client.post(
        "/api/deep-review",
        headers=headers,
        json={
            "paper_ids": ["p1"],
            "papers": [paper],
            "fast_mode": True,
            "run_id": "forged",
            "canonical_key": "doi:foreign",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (
        reviews.review_sessions[body["session_id"]]["account_incarnation"]
        == incarnation
    )
    attribution = body["recommendation_attribution"][0]
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT incarnation,outcome_id,canonical_key,credited FROM recommendation_outcomes"
        ).fetchall()
    if recreated:
        assert attribution["status"] != "attributed"
        assert rows == []
    else:
        assert attribution["credited"] is True
        assert attribution["run_id"] == "qualified-run"
        assert rows == [(incarnation, body["session_id"], key, 1)]


@pytest.mark.asyncio
async def test_rejected_review_start_has_no_outcome(
    client, local_review, qualified_outcome_store
):
    import sqlite3

    _, _, headers, path, _, paper, _, expose = qualified_outcome_store
    expose()
    response = await client.post(
        "/api/deep-review", headers=headers, json={"papers": [paper]}
    )
    assert response.status_code == 422
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM recommendation_outcomes").fetchone()[0]
            == 0
        )


@pytest.mark.asyncio
async def test_actual_producer_bookmark_and_metadata_restore(client, local_review):
    reviews, storage, _ = local_review
    headers = _auth("alice")
    incarnation = storage._get_user_db().get("alice")["account_incarnation"]
    sid = await _start(client, headers)
    session = reviews.review_sessions[sid]
    assert session["account_incarnation"] == incarnation
    metadata = json.loads(
        (Path(session["workspace_path"]) / "metadata.json").read_text()
    )
    assert metadata["username"] == "alice"
    assert metadata["account_incarnation"] == incarnation
    assert (await _bookmark(client, sid, headers)).status_code == 200
    with reviews.review_sessions_lock:
        reviews.review_sessions.pop(sid)
    assert storage._restore_sessions_from_workspace() == 1
    assert reviews.review_sessions[sid]["account_incarnation"] == incarnation
    assert (await _bookmark(client, sid, headers)).status_code == 200
    for endpoint in ("status", "report", "verification"):
        assert (
            await client.get(f"/api/deep-review/{endpoint}/{sid}", headers=headers)
        ).status_code == 200
        assert (
            await client.get(f"/api/deep-review/{endpoint}/{sid}")
        ).status_code == 401
        assert (
            await client.get(f"/api/deep-review/{endpoint}/{sid}", headers=_auth("bob"))
        ).status_code == 404
    assert (await _bookmark(client, sid, _auth("bob"))).status_code == 404


@pytest.mark.asyncio
async def test_anonymous_production_never_invents_owner(client, local_review):
    reviews, _, _ = local_review
    sid = await _start(client, {})
    assert reviews.review_sessions[sid]["username"] is None
    assert reviews.review_sessions[sid]["account_incarnation"] is None
    headers = _auth("alice")
    assert (
        await client.get(f"/api/deep-review/status/{sid}", headers=headers)
    ).status_code == 404
    assert (await _bookmark(client, sid, headers)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("recreate_at", ["work", "dispatch"])
async def test_late_completion_cannot_relabel_recreated_account(
    client, local_review, monkeypatch, recreate_at
):
    reviews, storage, fake_review = local_review
    old_headers = _auth("alice")
    users = storage._get_user_db()
    old_incarnation = users.get("alice")["account_incarnation"]

    def recreate():
        users.begin_delete("alice", old_incarnation)
        users.finish_delete("alice", old_incarnation, cleanup_succeeded=True)
        users.create_account("alice", {"role": "user"})

    def recreate_during_work(*args):
        recreate()
        return fake_review(*args)

    if recreate_at == "work":
        monkeypatch.setattr(reviews, "run_fast_review", recreate_during_work)
    else:
        record_started = reviews.record_job_started

        async def recreate_during_dispatch(*args):
            measurement = await record_started(*args)
            recreate()
            return measurement

        monkeypatch.setattr(reviews, "record_job_started", recreate_during_dispatch)
    sid = await _start(client, old_headers)
    session = reviews.review_sessions[sid]
    metadata = json.loads(
        (Path(session["workspace_path"]) / "metadata.json").read_text()
    )
    assert metadata["account_incarnation"] == old_incarnation
    with reviews.review_sessions_lock:
        reviews.review_sessions.pop(sid)
    storage._restore_sessions_from_workspace()
    headers = _auth("alice")
    for endpoint in ("status", "report", "verification"):
        assert (
            await client.get(f"/api/deep-review/{endpoint}/{sid}", headers=headers)
        ).status_code == 404
        assert (
            await client.get(f"/api/deep-review/{endpoint}/{sid}", headers=old_headers)
        ).status_code == 401
    assert (await _bookmark(client, sid, headers)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim", [{}, {"account_incarnation": None}, {"account_incarnation": "foreign"}]
)
async def test_restore_rejects_unbound_null_and_foreign_for_new_account(
    client, local_review, claim
):
    _, storage, _ = local_review
    headers = _auth("alice")
    sid = "review_legacy_claim"
    directory = storage.WORKSPACE_DIR / sid
    (directory / "reports").mkdir(parents=True)
    (directory / "reports" / "report.md").write_text("# Legacy")
    (directory / "metadata.json").write_text(json.dumps({"username": "alice", **claim}))
    storage._restore_sessions_from_workspace()
    session = storage.review_sessions[sid]
    assert ("account_incarnation" in session) == ("account_incarnation" in claim)
    assert (
        await client.get(f"/api/deep-review/status/{sid}", headers=headers)
    ).status_code == 404
    assert (await _bookmark(client, sid, headers)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim,allowed",
    [
        ({}, True),
        ({"account_incarnation": None}, False),
        ({"account_incarnation": "foreign"}, False),
    ],
)
async def test_only_authoritative_original_account_can_read_legacy(
    client, local_review, tmp_path, monkeypatch, claim, allowed
):
    _, storage, _ = local_review
    legacy_users = tmp_path / "legacy-users.json"
    legacy_users.write_text(
        json.dumps({"original": {"role": "user", "password_hash": "x"}})
    )
    monkeypatch.setattr(storage, "USERS_FILE", legacy_users)
    users = storage._get_user_db()
    assert users.get("original")["legacy_event_cutoff"]
    headers = _auth("original")
    sid = "review_original_legacy"
    directory = storage.WORKSPACE_DIR / sid
    (directory / "reports").mkdir(parents=True)
    (directory / "reports" / "report.md").write_text("# Legacy")
    (directory / "metadata.json").write_text(
        json.dumps({"username": "original", **claim})
    )
    storage._restore_sessions_from_workspace()
    expected = 200 if allowed else 404
    for endpoint in ("status", "report", "verification"):
        assert (
            await client.get(f"/api/deep-review/{endpoint}/{sid}", headers=headers)
        ).status_code == expected
    assert (await _bookmark(client, sid, headers)).status_code == expected
    incarnation = users.get("original")["account_incarnation"]
    users.begin_delete("original", incarnation)
    users.finish_delete("original", incarnation, cleanup_succeeded=True)
    replacement_headers = _auth("original")
    assert users.get("original")["legacy_event_cutoff"] is None
    assert (
        await client.get(f"/api/deep-review/status/{sid}", headers=replacement_headers)
    ).status_code == 404
    assert (await _bookmark(client, sid, replacement_headers)).status_code == 404
