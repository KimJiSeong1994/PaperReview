from datetime import datetime, timedelta, timezone
import json
import sqlite3
from unittest.mock import patch

import pytest

from src import recommendation_attribution as attribution
from src.recommendation_candidates import normalize_candidate
from src.recommendation_state import RecommendationState
from src.storage.user_db import UserDB

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
PAPER = {
    "doi": "https://doi.org/10.1234/EXAMPLE",
    "title": "Public paper",
    "canonical_key": "forged",
}


@pytest.fixture
def stores(tmp_path):
    authority = UserDB(tmp_path / "users.db")
    user = authority.create_account("alice", {"role": "user"})
    events = tmp_path / "events.db"
    state = RecommendationState.initialize(events, authority=authority)
    return authority, events, state, user["account_incarnation"]


def call(stores, **overrides):
    authority, events, _, incarnation = stores
    args = dict(
        authority=authority,
        events_db=events,
        username="alice",
        account_incarnation=incarnation,
        paper=PAPER,
        kind="save",
        outcome_id="committed-save-1",
        now=NOW,
    )
    args.update(overrides)
    return attribution.attribute_recommendation_outcome(**args)


def test_canonical_actual_paper_and_captured_identity(stores):
    with patch.object(
        RecommendationState,
        "record_outcome",
        create=True,
        return_value={"status": "attributed", "credited": True},
    ) as record:
        result = call(stores)
    assert result["credited"] is True
    assert record.call_args.args == (stores[3],)
    assert record.call_args.kwargs == dict(
        canonical_key="doi:10.1234/example",
        kind="save",
        outcome_id="committed-save-1",
        now=NOW,
    )


def test_revoked_account_never_records(stores):
    authority, _, _, incarnation = stores
    authority.begin_delete("alice", incarnation)
    with patch.object(RecommendationState, "record_outcome", create=True) as record:
        result = call(stores)
    assert result["status"] == "not_attributed" and not result["credited"]
    record.assert_not_called()


def test_recreated_username_does_not_rebind(stores):
    authority, _, _, incarnation = stores
    authority.begin_delete("alice", incarnation)
    authority.finish_delete("alice", incarnation, cleanup_succeeded=True)
    authority.create_account("alice", {"role": "user"})
    with patch.object(RecommendationState, "record_outcome", create=True) as record:
        assert call(stores)["reason"] == "account_unavailable"
    record.assert_not_called()


def test_store_failure_cannot_fail_committed_primary_or_leak_payload(stores):
    with patch.object(
        attribution, "RecommendationState", side_effect=RuntimeError("private-marker")
    ):
        result = call(stores)
    assert result == {
        "status": "unavailable",
        "reason": "attribution_unavailable",
        "credited": False,
    }
    assert "private-marker" not in json.dumps(result)


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "click"},
        {"paper": {}},
        {"now": NOW.replace(tzinfo=None)},
        {"outcome_id": ""},
    ],
)
def test_invalid_hook_input_is_explicit_not_attributed(stores, overrides):
    with patch.object(RecommendationState, "record_outcome", create=True) as record:
        assert call(stores, **overrides)["status"] == "not_attributed"
    record.assert_not_called()


def test_report_preserves_observed_denominators_and_unknown_completeness(stores):
    bucket = {
        "visible_userdays": 3,
        "positive_userdays": 1,
        "per_kind_counts": {"save": 1, "review_start": 0},
        "rate": 1 / 3,
    }
    metrics = {
        "total": bucket,
        "mature": bucket,
        "right_censored": {
            "visible_userdays": 0,
            "positive_userdays": 0,
            "per_kind_counts": {"save": 0, "review_start": 0},
            "rate": None,
        },
    }
    since, until = NOW.replace(hour=0) - timedelta(days=10), NOW.replace(hour=0)
    with patch.object(
        RecommendationState, "outcome_metrics", create=True, return_value=metrics
    ) as read:
        result = attribution.observed_outcome_report(
            authority=stores[0],
            events_db=stores[1],
            username="alice",
            since=since,
            until=until,
            now=NOW,
        )
    assert result["metrics"] == metrics
    assert read.call_args.args == (stores[3],)
    assert result["capture_completeness"] == "unknown"
    assert result["promotion"] is False and result["causal_effect_estimated"] is False
    assert result["rate_is_population_lower_bound"] is False


def test_cli_requires_explicit_paths_times_and_sanitizes_failure(tmp_path, capsys):
    with pytest.raises(SystemExit):
        attribution.build_parser().parse_args([])
    args = [
        "--users-db",
        str(tmp_path / "missing-users"),
        "--events-db",
        str(tmp_path / "missing-events"),
        "--username",
        "private-name",
        "--since",
        "2026-09-01T00:00:00Z",
        "--until",
        "2026-09-10T00:00:00Z",
        "--now",
        NOW.isoformat(),
    ]
    assert attribution.main(args) == 2
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "status": "unavailable",
        "reason": "outcome_report_unavailable",
        "promotion": False,
    }
    assert not (tmp_path / "missing-users").exists()


def test_cli_local_observed_report(stores, capsys):
    with patch.object(
        RecommendationState,
        "outcome_metrics",
        create=True,
        return_value={"observed": 0},
    ):
        code = attribution.main(
            [
                "--users-db",
                str(stores[1].parent / "users.db"),
                "--events-db",
                str(stores[1]),
                "--username",
                "alice",
                "--since",
                "2026-09-01T00:00:00Z",
                "--until",
                "2026-09-10T00:00:00Z",
                "--now",
                NOW.isoformat(),
            ]
        )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["metrics"] == {"observed": 0}


def test_report_rejects_non_day_boundary_and_future_window(stores):
    for since, until in (
        (NOW - timedelta(days=2), NOW.replace(hour=0)),
        (NOW.replace(hour=0), NOW.replace(hour=0) + timedelta(days=1)),
    ):
        with pytest.raises(ValueError):
            attribution.observed_outcome_report(
                authority=stores[0],
                events_db=stores[1],
                username="alice",
                since=since,
                until=until,
                now=NOW,
            )


def test_actual_store_loss_is_unavailable_without_reinitialization(stores):
    stores[1].unlink()
    result = call(stores)
    assert result["status"] == "unavailable"
    assert not stores[1].exists()


@pytest.mark.parametrize("legacy", [False, True])
def test_cli_never_initializes_existing_empty_or_legacy_authority(
    tmp_path, capsys, legacy
):
    users = tmp_path / "users.db"
    events = tmp_path / "events.db"
    with sqlite3.connect(users) as conn:
        if legacy:
            conn.execute(
                "CREATE TABLE users(username TEXT PRIMARY KEY, password_hash TEXT)"
            )
            conn.execute("INSERT INTO users VALUES('alice', 'preserve-credential')")
    with sqlite3.connect(events):
        pass
    before = users.read_bytes()
    with patch.object(
        attribution,
        "UserDB",
        side_effect=AssertionError("must not construct authority"),
    ) as constructor:
        code = attribution.main(
            [
                "--users-db",
                str(users),
                "--events-db",
                str(events),
                "--username",
                "alice",
                "--since",
                "2026-09-01T00:00:00Z",
                "--until",
                "2026-09-10T00:00:00Z",
                "--now",
                NOW.isoformat(),
            ]
        )
    assert code == 2
    constructor.assert_not_called()
    assert users.read_bytes() == before
    assert json.loads(capsys.readouterr().out)["reason"] == "outcome_report_unavailable"


@pytest.mark.parametrize(
    "markers",
    [
        {"lifecycle_initialized": "1"},
        {"lifecycle_initialized": "0", "policy_store": "{}"},
        {"lifecycle_initialized": "1", "policy_store": "null"},
    ],
)
def test_cli_requires_both_existing_authority_markers(tmp_path, capsys, markers):
    users, events = tmp_path / "users.db", tmp_path / "events.db"
    with sqlite3.connect(users) as conn:
        conn.execute(
            "CREATE TABLE account_store_meta(key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.executemany("INSERT INTO account_store_meta VALUES(?, ?)", markers.items())
    with sqlite3.connect(events):
        pass
    before = users.read_bytes()
    with patch.object(attribution, "UserDB") as constructor:
        assert (
            attribution.main(
                [
                    "--users-db",
                    str(users),
                    "--events-db",
                    str(events),
                    "--username",
                    "alice",
                    "--since",
                    "2026-09-01T00:00:00Z",
                    "--until",
                    "2026-09-10T00:00:00Z",
                    "--now",
                    NOW.isoformat(),
                ]
            )
            == 2
        )
    constructor.assert_not_called()
    assert users.read_bytes() == before


@pytest.mark.parametrize(
    "bibliographic",
    [
        {"title": "Provider paper", "openalex_id": "https://openalex.org/W123456"},
        {
            "title": "Metadata paper",
            "authors": [{"name": "Public Author"}],
            "publication_date": "2025-03-04",
            "url": "https://example.org/paper",
            "pdf_url": "https://example.org/paper.pdf",
        },
        {"title": "DOI paper", "doi": "https://doi.org/10.1234/EXAMPLE"},
    ],
)
@pytest.mark.parametrize("kind", ["save", "review_start"])
def test_common_normalized_identity_matches_actual_qualified_exposure(
    stores, bibliographic, kind
):
    authority, _, state, incarnation = stores
    candidate = normalize_candidate(bibliographic)
    with authority.account_guard("alice", incarnation):
        assert state.record_exposure(
            incarnation,
            run_id="actual-run",
            canonical_key=candidate.canonical_key,
            visible_fraction=0.5,
            visible_ms=1000,
            now=NOW - timedelta(hours=1),
        )
    committed = {
        **bibliographic,
        "source": "legacy-provider",
        "id": "legacy-id",
        "paper_id": "legacy-paper",
        "canonical_key": "forged-key",
        "result_key": "forged-result",
        "run_id": "forged-run",
        "abstract": "private-large-abstract" * 1000,
        "notes": {"private": "never identity"},
        "categories": "not a valid list",
        "venue": {"private": "irrelevant"},
    }
    result = call(stores, paper=committed, kind=kind)
    assert result["status"] == "attributed" and result["credited"] is True
    assert result["canonical_key"] == candidate.canonical_key
    assert result["run_id"] == "actual-run"
    if "openalex_id" in bibliographic:
        assert result["canonical_key"] == "provider:openalex:W123456"
    elif "doi" not in bibliographic:
        assert result["canonical_key"].startswith("metadata:")
