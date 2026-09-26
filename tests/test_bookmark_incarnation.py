"""Bookmark ownership fences, using only temporary account/bookmark stores."""

import asyncio
import inspect
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.storage.bookmark_db import BookmarkDB, bookmark_belongs_to_account
from src.storage.user_db import UserDB


@pytest.fixture
def qualified_outcome_store(client, tmp_path, monkeypatch):
    from routers.deps.storage import _get_user_db
    from src.recommendation_state import RecommendationState
    from src.utils.paper_utils import generate_result_key
    from tests.conftest import _make_test_token

    users = _get_user_db()
    incarnation = users.create_account("outcome-owner", {"role": "user"})[
        "account_incarnation"
    ]
    headers = {
        "Authorization": f"Bearer {_make_test_token('outcome-owner', role='user')}"
    }
    path = tmp_path / "qualified-events.db"
    monkeypatch.setenv("EVENTS_DB_PATH", str(path))
    state = RecommendationState.initialize(path, authority=users)
    paper = {
        "title": "Qualified paper",
        "doi": "10.1234/qualified",
        "abstract": "Local fixture abstract",
    }
    key = generate_result_key(paper)

    def expose(*, days=0, fraction=0.5, milliseconds=1000):
        with users.account_guard("outcome-owner", incarnation):
            state.record_exposure(
                incarnation,
                run_id="qualified-run",
                canonical_key=key,
                visible_fraction=fraction,
                visible_ms=milliseconds,
                now=datetime.now(timezone.utc) - timedelta(days=days, seconds=1),
            )

    return users, incarnation, headers, path, state, paper, key, expose


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["review", "paper"])
async def test_actual_bookmark_save_attribution_and_dedup(
    client, qualified_outcome_store, variant
):
    users, incarnation, headers, path, state, paper, key, expose = (
        qualified_outcome_store
    )
    expose()
    if variant == "review":
        url = "/api/bookmarks"
        payload = {
            "session_id": "no-session",
            "title": "Saved review",
            "papers": [paper],
            "report_markdown": "# Report",
        }
    else:
        url = "/api/bookmarks/from-paper"
        payload = paper
    # Untrusted context cannot select the exposure or override canonical identity.
    payload = {
        **payload,
        "run_id": "forged",
        "canonical_key": "doi:foreign",
        "visible_at": "2099-01-01T00:00:00Z",
    }
    first = await client.post(url, headers=headers, json=payload)
    assert first.status_code == 200, first.text
    result = first.json()
    credit = result["recommendation_attribution"][0]
    assert credit["credited"] is True
    assert credit["canonical_key"] == key
    assert credit["run_id"] == "qualified-run"
    second = await client.post(url, headers=headers, json=payload)
    assert second.status_code == 200
    assert second.json()["recommendation_attribution"][0]["credited"] is False
    with users.account_guard("outcome-owner", incarnation):
        replay = state.record_outcome(
            incarnation, canonical_key=key, kind="save", outcome_id=result["id"]
        )
    assert replay == credit
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT outcome_id,canonical_key,credited FROM recommendation_outcomes"
        ).fetchall()
    assert len(rows) == 2
    assert sum(row[2] for row in rows) == 1
    assert (result["id"], key, 1) in rows


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identity",
    [
        {"openalex_id": "https://openalex.org/W123456789"},
        {"url": "https://example.org/papers/local-identity"},
        {"semantic_scholar_id": "a" * 40},
        {"pmid": "12345678"},
        {"pdf_url": "https://example.org/papers/local-identity.pdf"},
    ],
)
async def test_from_paper_preserves_candidate_identity_for_attribution(
    client, qualified_outcome_store, identity
):
    from routers.deps.storage import _get_bookmark_db
    from src.recommendation_candidates import normalize_candidate

    users, incarnation, headers, path, state, _, _, _ = qualified_outcome_store
    paper = {"title": "Provider identity paper", **identity}
    key = normalize_candidate(paper).canonical_key
    with users.account_guard("outcome-owner", incarnation):
        state.record_exposure(
            incarnation,
            run_id="provider-run",
            canonical_key=key,
            visible_fraction=0.5,
            visible_ms=1000,
            now=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    response = await client.post(
        "/api/bookmarks/from-paper",
        headers=headers,
        json={**paper, "canonical_key": "doi:forged", "run_id": "forged"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    saved = _get_bookmark_db().get_by_id(body["id"])["papers"][0]
    for field, value in identity.items():
        assert saved[field] == value
    assert (
        normalize_candidate(
            {field: value for field, value in saved.items() if value not in ("", None)}
        ).canonical_key
        == key
    )
    credit = body["recommendation_attribution"][0]
    assert credit["credited"] is True
    assert credit["canonical_key"] == key
    assert credit["run_id"] == "provider-run"
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT canonical_key,credited FROM recommendation_outcomes WHERE outcome_id=?",
            (body["id"],),
        ).fetchall() == [(key, 1)]


@pytest.mark.asyncio
@pytest.mark.parametrize("exposure", ["unseen", "prefetch", "expired"])
async def test_successful_save_without_qualified_exposure_has_no_credit(
    client, qualified_outcome_store, exposure
):
    from src.recommendation_state import RecommendationStateError

    _, _, headers, _, _, paper, _, expose = qualified_outcome_store
    if exposure == "prefetch":
        with pytest.raises(RecommendationStateError, match="insufficient_visibility"):
            expose(fraction=0, milliseconds=0)
    elif exposure == "expired":
        expose(days=8)
    response = await client.post(
        "/api/bookmarks/from-paper", headers=headers, json=paper
    )
    assert response.status_code == 200
    result = response.json()["recommendation_attribution"][0]
    assert result["status"] == "not_attributed"
    assert result["credited"] is False


@pytest.mark.asyncio
async def test_committed_save_survives_attribution_unavailable(
    client, qualified_outcome_store, monkeypatch
):
    from routers import bookmarks
    from routers.deps.storage import _get_bookmark_db

    _, _, headers, _, _, paper, _, _ = qualified_outcome_store

    def unavailable(**kwargs):
        raise OSError("fixture unavailable")

    monkeypatch.setattr(bookmarks, "attribute_recommendation_outcome", unavailable)
    response = await client.post(
        "/api/bookmarks/from-paper", headers=headers, json=paper
    )
    assert response.status_code == 200
    assert response.json()["recommendation_attribution"][0]["status"] == "unavailable"
    assert (
        _get_bookmark_db().get_by_id(response.json()["id"])["papers"][0]["doi"]
        == paper["doi"]
    )


@pytest.mark.asyncio
async def test_save_recreation_before_attribution_never_credits_replacement(
    client, qualified_outcome_store, monkeypatch
):
    from routers import bookmarks

    users, incarnation, headers, path, _, paper, _, expose = qualified_outcome_store
    expose()
    real_attribute = bookmarks.attribute_recommendation_outcome

    def replace_then_attribute(**kwargs):
        users.begin_delete("outcome-owner", incarnation)
        users.finish_delete("outcome-owner", incarnation, cleanup_succeeded=True)
        users.create_account("outcome-owner", {"role": "user"})
        assert kwargs["account_incarnation"] == incarnation
        return real_attribute(**kwargs)

    monkeypatch.setattr(
        bookmarks, "attribute_recommendation_outcome", replace_then_attribute
    )
    response = await client.post(
        "/api/bookmarks/from-paper", headers=headers, json=paper
    )
    assert response.status_code == 200
    assert response.json()["recommendation_attribution"][0]["status"] != "attributed"
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM recommendation_outcomes").fetchone()[0]
            == 0
        )


@pytest.mark.asyncio
async def test_foreign_session_save_never_records_outcome(
    client, qualified_outcome_store, monkeypatch
):
    from routers import bookmarks

    _, _, headers, path, _, paper, _, expose = qualified_outcome_store
    expose()
    monkeypatch.setattr(
        bookmarks,
        "review_sessions",
        {"foreign": {"username": "someone-else", "account_incarnation": "foreign"}},
    )
    response = await client.post(
        "/api/bookmarks",
        headers=headers,
        json={
            "session_id": "foreign",
            "title": "paper",
            "papers": [paper],
            "report_markdown": "report",
        },
    )
    assert response.status_code == 404
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM recommendation_outcomes").fetchone()[0]
            == 0
        )


@pytest.mark.asyncio
async def test_multi_paper_save_preserves_actual_outcome_id(
    client, qualified_outcome_store
):
    from src.utils.paper_utils import generate_result_key

    users, incarnation, headers, path, state, paper, key, expose = (
        qualified_outcome_store
    )
    expose()
    second_paper = {"title": "Second paper", "arxiv_id": "2401.01234"}
    second_key = generate_result_key(second_paper)
    with users.account_guard("outcome-owner", incarnation):
        state.record_exposure(
            incarnation,
            run_id="qualified-run",
            canonical_key=second_key,
            visible_fraction=0.5,
            visible_ms=1000,
            now=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    response = await client.post(
        "/api/bookmarks",
        headers=headers,
        json={
            "session_id": "multi",
            "title": "Review",
            "papers": [paper, second_paper],
            "report_markdown": "# Review",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert all(result["credited"] for result in body["recommendation_attribution"])
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT outcome_id,canonical_key FROM recommendation_outcomes WHERE credited=1"
        ).fetchall()
    assert set(rows) == {(body["id"], key), (body["id"], second_key)}


def test_pure_ownership_bound_and_original_legacy():
    belongs = lambda record, cutoff=None: bookmark_belongs_to_account(
        record, username="alice", account_incarnation="new", legacy_event_cutoff=cutoff
    )
    assert belongs({"username": "alice", "account_incarnation": "new"})
    assert not belongs({"username": "alice", "account_incarnation": "old"}, "cutoff")
    assert not belongs({"username": "alice"})
    assert belongs({"username": "alice"}, "trusted-cutoff")
    assert not belongs({"username": "bob"}, "trusted-cutoff")
    assert not belongs(
        {"username": "alice", "account_incarnation": None}, "trusted-cutoff"
    )


@pytest.fixture
def stores(tmp_path, monkeypatch):
    from routers import bookmarks
    from routers.deps import storage
    from routers.deps.auth import AuthenticatedPrincipal

    users = UserDB(tmp_path / "users.db")
    db = BookmarkDB(tmp_path / "bookmarks.db")
    inc = users.create_account("alice", {})["account_incarnation"]
    principal = AuthenticatedPrincipal("alice", inc)
    monkeypatch.setattr(bookmarks, "_get_user_db", lambda: users)
    monkeypatch.setattr(bookmarks, "_get_bookmark_db", lambda: db)
    monkeypatch.setattr(storage, "_get_bookmark_db", lambda: db)
    monkeypatch.setattr(bookmarks, "review_sessions", {})
    monkeypatch.setattr(bookmarks, "emit_or_warn", lambda event: False)
    return bookmarks, users, db, principal


def request():
    return Request(
        {
            "type": "http",
            "headers": [],
            "method": "POST",
            "path": "/",
            "client": ("127.0.0.1", 1234),
        }
    )


def test_create_tags_metadata_even_when_analytics_dropped(stores):
    router, users, db, principal = stores
    payload = router.BookmarkCreateRequest(
        session_id="none", title="paper", report_markdown="report"
    )
    result = asyncio.run(
        inspect.unwrap(router.create_bookmark)(request(), payload, principal)
    )
    saved = db.get_by_id(result.id)
    assert saved["account_incarnation"] == principal.account_incarnation
    assert asyncio.run(router.get_bookmark(result.id, principal))["id"] == result.id
    db.upsert({"id": "legacy", "username": "alice", "title": "old"})
    listing = asyncio.run(router.list_bookmarks(principal))
    assert [row["id"] for row in listing["bookmarks"]] == [result.id]
    with pytest.raises(HTTPException) as exc:
        asyncio.run(router.get_bookmark("legacy", principal))
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    "session",
    [
        {"username": "bob", "account_incarnation": "other"},
        {"username": "alice", "account_incarnation": "old"},
        {"username": "alice", "account_incarnation": None},
        {"username": "alice"},
    ],
)
def test_workspace_attachment_rejects_foreign_or_unbound_session(stores, session):
    router, _, db, principal = stores
    router.review_sessions["session"] = {**session, "workspace_path": "/private/other"}
    payload = router.BookmarkCreateRequest(
        session_id="session", title="paper", report_markdown="report"
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            inspect.unwrap(router.create_bookmark)(request(), payload, principal)
        )
    assert exc.value.status_code == 404
    assert db.get_all() == []


def test_highlight_after_await_rejects_old_principal_and_preserves_replacement(
    stores, monkeypatch
):
    router, users, db, principal = stores
    db.upsert(
        {
            "id": "paper",
            "username": "alice",
            "account_incarnation": principal.account_incarnation,
            "report_markdown": "Long enough report for highlight",
            "title": "paper",
        }
    )
    replacement = {}

    async def replace_during_llm(*args):
        users.begin_delete("alice", principal.account_incarnation)
        db.delete_by_username("alice")
        users.finish_delete(
            "alice", principal.account_incarnation, cleanup_succeeded=True
        )
        replacement.update(users.create_account("alice", {}))
        db.upsert(
            {
                "id": "paper",
                "username": "alice",
                "account_incarnation": replacement["account_incarnation"],
                "notes": "new owner",
            }
        )
        return [{"text": "Long enough report", "category": "finding"}]

    monkeypatch.setattr(router, "run_in_threadpool", replace_during_llm)
    monkeypatch.setattr(router, "get_openai_client", lambda: object())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            inspect.unwrap(router.auto_highlight_bookmark)(
                request(), "paper", principal
            )
        )
    assert exc.value.status_code == 401
    assert db.get_by_id("paper")["notes"] == "new owner"
    assert not db.get_by_id("paper").get("highlights")


def test_mutations_cannot_touch_foreign_incarnation(stores):
    router, _, db, principal = stores
    db.upsert(
        {
            "id": "old",
            "username": "alice",
            "account_incarnation": "old",
            "topic": "keep",
        }
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            inspect.unwrap(router.update_bookmark_topic)(
                request(),
                "old",
                router.BookmarkTopicUpdateRequest(topic="changed"),
                principal,
            )
        )
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException):
        asyncio.run(inspect.unwrap(router.delete_bookmark)(request(), "old", principal))
    assert db.get_by_id("old")["topic"] == "keep"
