"""Captured bibliographic fixtures only: no provider or production database access."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

import src.daily_recommendations as daily
from src.recommendation_candidates import (
    TrustedReceiverPolicy,
    make_candidate_snapshot,
    write_candidate_snapshot,
)
from src.recommendation_profiles import RecommendationProfile
from src.recommendation_ranker import rank_paper_v2
from src.recommendation_state import RecommendationPolicy, RecommendationState
from src.recommendations_artifacts import (
    load_recommendation_artifact,
    read_delivery,
    validate_delivery,
)
from src.storage.user_db import UserDB
from src.utils.paper_utils import generate_result_key

NOW = datetime(2026, 9, 25, 10, tzinfo=timezone.utc)


def papers(count=8):
    return [
        {
            "title": f"Graph retrieval study {index}",
            "abstract": "Graph retrieval recommendation networks",
            "doi": f"10.1234/paper{index}",
            "publication_date": "2025-01-01",
            "pdf_url": f"https://example.org/paper{index}.pdf",
            "authors": ["Public Author"],
        }
        for index in range(count)
    ]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FEATURE_FLAGS_DB_PATH", str(tmp_path / "flags.db"))
    monkeypatch.delenv("PROFILE_RANKER_ENABLED", raising=False)
    monkeypatch.delenv("PROFILE_RANKER_GLOBAL_ENABLED", raising=False)
    monkeypatch.delenv("PROFILE_RANKER_ALLOWED_USERS", raising=False)
    users = UserDB(tmp_path / "users.db")
    alice = users.create_account("alice", {"role": "user"})
    bob = users.create_account("bob", {"role": "user"})
    events = tmp_path / "events.db"
    with sqlite3.connect(events) as conn:
        conn.execute(
            "CREATE TABLE user_events (id INTEGER PRIMARY KEY, user_id TEXT, event_type TEXT, payload TEXT, paper_id TEXT, created_at TEXT, source TEXT)"
        )
    bookmarks = tmp_path / "bookmarks.db"
    with sqlite3.connect(bookmarks) as conn:
        conn.execute(
            "CREATE TABLE bookmarks(id TEXT PRIMARY KEY, username TEXT, topic TEXT, title TEXT, papers TEXT, notes TEXT, report TEXT, created_at TEXT, metadata TEXT)"
        )
    result = {
        "root": tmp_path,
        "users": users,
        "alice": alice["account_incarnation"],
        "bob": bob["account_incarnation"],
        "state": RecommendationState.initialize(events, authority=users),
        "candidate_root": tmp_path / "candidates",
        "artifacts_dir": tmp_path / "deliveries",
        "users_db": tmp_path / "users.db",
        "events_db": events,
        "bookmarks_db": bookmarks,
    }
    return result


def snapshot(env, records=None, *, policy=None, run="captured", collected=NOW):
    policy = policy or daily.DEFAULT_REGISTRATIONS[0].policy
    captured = make_candidate_snapshot(
        papers() if records is None else records,
        policy=policy,
        source_run_id=run,
        collected_at=collected,
        now=collected,
    )
    return write_candidate_snapshot(
        captured, root=env["candidate_root"], final_root=env["artifacts_dir"]
    )


def event(
    env, terms, *, incarnation=None, event_type="query_submit", feedback=None, key=None
):
    payload = {
        "terms": terms,
        "account_incarnation": incarnation or env["alice"],
        "query": "private_query_marker",
    }
    if feedback:
        payload["feedback_type"] = feedback
    if key:
        payload["paper_id"] = key
    with sqlite3.connect(env["events_db"]) as conn:
        conn.execute(
            "INSERT INTO user_events(user_id,event_type,payload,paper_id,created_at,source) VALUES('alice',?,?,?,?, 'app')",
            (event_type, json.dumps(payload), key, NOW.isoformat()),
        )


def bookmark(env, username="alice", title="Graph retrieval private_bookmark_marker"):
    with sqlite3.connect(env["bookmarks_db"]) as conn:
        conn.execute(
            "INSERT INTO bookmarks VALUES(?,?,?,?,?,?,?,?,?)",
            (
                username,
                username,
                "Graph retrieval",
                title,
                "[]",
                "private_note_marker",
                "private_report_marker",
                NOW.isoformat(),
                json.dumps({"account_incarnation": env[username]}),
            ),
        )


def generate(env, **kwargs):
    options = {
        key: env[key]
        for key in (
            "users_db",
            "events_db",
            "bookmarks_db",
            "candidate_root",
            "artifacts_dir",
        )
    }
    options.update(run_at=NOW.isoformat(), wall_clock=lambda: NOW, usernames=["alice"])
    options.update(kwargs)
    return daily.generate_daily_recommendations(**options)


def delivery(env, incarnation=None):
    return read_delivery(env["artifacts_dir"], incarnation or env["alice"], now=NOW)


def action(env, key, action_name, *, request="action", run="prior"):
    env["state"].apply_action(
        env["alice"],
        canonical_key=key,
        action=action_name,
        request_id=request,
        run_id=run,
        now=NOW,
    )


def test_common_delivery_manifest_top5_and_private_marker_absence(env):
    snapshot(env)
    bookmark(env)
    event(env, ["graph", "private_event_marker"])
    summary = generate(env, usernames=["alice", "bob", "missing"])
    assert summary["rank_success"] == summary["publish_success"] == 2
    assert summary["failures"] == []
    assert summary["unknown_requested_count"] == 1
    raw = delivery(env)
    assert raw["producer"] == "common_local"
    assert raw["scoring_mode"] == "v1"
    assert raw["cutoff"] == raw["run_at"] == NOW.isoformat()
    assert (
        len(raw["code_hash"])
        == len(raw["config_hash"])
        == len(raw["input_manifest_hash"])
        == 64
    )
    assert raw["input_manifest"][0]["provenance_id"] == "public-seeds-v1"
    text = json.dumps(raw)
    for marker in (
        "private_query_marker",
        "private_bookmark_marker",
        "private_note_marker",
        "private_report_marker",
        "private_event_marker",
    ):
        assert marker not in text
    result = load_recommendation_artifact(
        env["artifacts_dir"],
        env["alice"],
        5,
        policy=env["state"].policy(env["alice"], now=NOW),
        now=NOW,
    )
    assert len(result["items"]) == 5
    assert result["total_count"] == 8
    assert result["items"][0]["canonical_key"] == raw["items"][0]["canonical_key"]
    assert delivery(env, env["bob"])["scoring_mode"] == "metadata"
    assert summary["provider_calls"] == summary["paid_calls"] == 0
    assert summary["process_peak_rss_bytes"] > 0
    assert not (env["artifacts_dir"] / "alice").exists()


@pytest.mark.parametrize("use_v2", [False, True])
@pytest.mark.parametrize(
    "source",
    ["local", "external", "both", "none", "empty", "invalid", "stale", "wrong_owner"],
)
def test_registered_source_matrix_and_hard_hide(env, monkeypatch, use_v2, source):
    monkeypatch.setattr(daily, "_profile_ranker_enabled", lambda _: use_v2)
    registrations = list(daily.DEFAULT_REGISTRATIONS)
    if source in {"local", "both"}:
        snapshot(env)
    elif source == "empty":
        snapshot(env, [])
    elif source == "invalid":
        path = snapshot(env)
        path.write_text('{"schema":"external_raw","score":999}', encoding="utf-8")
    elif source == "stale":
        snapshot(env, collected=NOW - timedelta(days=3))
    if source in {"external", "both", "wrong_owner"}:
        owner = env["bob"] if source == "wrong_owner" else env["alice"]
        policy = TrustedReceiverPolicy(
            "openclaw", "private", "approved-fixture", account_incarnation=owner
        )
        snapshot(env, policy=policy, run="external")
        registrations.append(daily.SourceRegistration(f"private/{owner}", policy))
    hidden = generate_result_key(papers()[0])
    action(env, hidden, "hide")
    event(
        env,
        [],
        event_type="recommendation_feedback",
        feedback="topic_less",
        key=generate_result_key(papers()[1]),
    )
    summary = generate(env, registrations=registrations)
    assert summary["publish_success"] == 1
    raw = delivery(env)
    assert all(item["canonical_key"] != hidden for item in raw["items"])
    assert raw["personalization_state"] == "metadata_only"
    if source in {"local", "external", "both"}:
        assert raw["items"]
    else:
        assert raw["items"] == []
        assert raw["status"] == "empty"
    if source not in {"external", "both"}:
        assert raw["source_statuses"]["openclaw"] == "disabled"


def test_unregistered_external_json_never_grants_source_authority(env):
    policy = TrustedReceiverPolicy(
        "openclaw", "public", "unregistered", public_source_qualified=True
    )
    snapshot(env, policy=policy)
    generate(env)
    raw = delivery(env)
    assert raw["items"] == []
    assert raw["source_statuses"]["openclaw"] == "disabled"


def test_v2_flag_gate_unchanged(env, monkeypatch):
    import src.events.feature_flags as flags

    monkeypatch.setenv("PROFILE_RANKER_ENABLED", "true")
    assert daily._profile_ranker_enabled("alice") is False
    monkeypatch.setenv("PROFILE_RANKER_ALLOWED_USERS", "alice")
    assert daily._profile_ranker_enabled("alice") is True
    flags.set_override(flags.PROFILE_RANKER_ENABLED, enabled=False, username="alice")
    assert daily._profile_ranker_enabled("alice") is False
    flags.set_override(flags.PROFILE_RANKER_ENABLED, enabled=True, username="bob")
    assert daily._profile_ranker_enabled("bob") is True


def test_positive_id_is_not_seen_and_durable_topic_less_is_soft(env, monkeypatch):
    snapshot(env)
    monkeypatch.setattr(daily, "_profile_ranker_enabled", lambda _: True)
    key = generate_result_key(papers()[0])
    action(env, key, "interested")
    action(env, generate_result_key(papers()[1]), "topic_less", request="topic")
    generate(env)
    raw = delivery(env)
    assert raw["scoring_mode"] == "v2"
    assert key in {item["canonical_key"] for item in raw["items"]}
    assert any(item["score_breakdown"]["negative_match"] > 0 for item in raw["items"])
    assert env["state"].policy(env["alice"], now=NOW).seen == frozenset()


def test_ranker_failure_falls_back_without_resurrecting_hidden_or_erasing_negative(
    env, monkeypatch
):
    snapshot(env)
    bookmark(env)
    event(
        env,
        ["graph"],
        event_type="bookmark_remove",
        key=generate_result_key(papers()[1]),
    )
    action(env, generate_result_key(papers()[0]), "hide")
    monkeypatch.setattr(daily, "_profile_ranker_enabled", lambda _: True)
    monkeypatch.setattr(
        daily,
        "rank_paper_v2",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("private-error-marker")),
    )
    summary = generate(env)
    assert summary["publish_success"] == 1
    raw = delivery(env)
    assert raw["scoring_mode"] == "v1_fallback"
    assert "ranker_error" in raw["degraded_reasons"]
    assert all(
        item["canonical_key"] != generate_result_key(papers()[0])
        for item in raw["items"]
    )
    assert any(item["score_breakdown"]["negative_match"] > 0 for item in raw["items"])
    assert "private-error-marker" not in json.dumps(summary) + json.dumps(raw)


def test_policy_failure_is_fail_closed(env, monkeypatch):
    snapshot(env)
    monkeypatch.setattr(
        daily.RecommendationState,
        "policy",
        lambda *a, **k: (_ for _ in ()).throw(
            sqlite3.OperationalError("private error")
        ),
    )
    summary = generate(env)
    assert summary["publish_success"] == summary["rank_success"] == 0
    assert summary["failures"][0]["reason"] == "policy_unavailable"
    assert delivery(env) is None


def test_hide_during_ranking_rechecked_before_publish(env, monkeypatch):
    snapshot(env)
    original = daily.recommend_for_user
    hidden = []

    def racing_rank(*args, **kwargs):
        result = original(*args, **kwargs)
        hidden.append(result[0][0]["canonical_key"])
        action(env, hidden[0], "hide")
        return result

    monkeypatch.setattr(daily, "recommend_for_user", racing_rank)
    summary = generate(env)
    assert summary["publish_success"] == 1
    raw = delivery(env)
    assert hidden[0] not in {item["canonical_key"] for item in raw["items"]}
    assert raw["items"][0]["final_rank"] == 2
    shown = load_recommendation_artifact(
        env["artifacts_dir"],
        env["alice"],
        5,
        policy=env["state"].policy(env["alice"], now=NOW),
        now=NOW,
    )
    assert len(shown["items"]) == 5
    assert shown["items"][-1]["final_rank"] == 6


def test_account_recreated_during_ranking_cannot_publish_old_generation(
    env, monkeypatch
):
    snapshot(env)
    original = daily.recommend_for_user
    old = env["alice"]

    def recreate(*args, **kwargs):
        ranked = original(*args, **kwargs)
        env["users"].begin_delete("alice", old)
        env["users"].finish_delete("alice", old, cleanup_succeeded=True)
        env["users"].create_account("alice", {"role": "user"})
        return ranked

    monkeypatch.setattr(daily, "recommend_for_user", recreate)
    summary = generate(env)
    assert summary["rank_success"] == 1
    assert summary["publish_success"] == 0
    assert summary["failures"][0]["reason"] == "authority_unavailable"
    assert delivery(env, old) is None
    assert not list(env["artifacts_dir"].rglob("*.tmp"))


def test_exact_idempotent_reuse_and_policy_change_not_existence_skip(env):
    snapshot(env)
    first = generate(env)
    second = generate(env)
    assert first["publish_success"] == 1
    assert second["publish_success"] == 0 and second["reused"] == 1
    key = delivery(env)["items"][0]["canonical_key"]
    action(env, key, "hide")
    third = generate(env)
    assert third["publish_success"] == 1 and third["reused"] == 0
    assert key not in {item["canonical_key"] for item in delivery(env)["items"]}


def test_deadline_during_rank_never_late_publishes(env, monkeypatch):
    snapshot(env)
    clock = [0.0]
    original = daily.recommend_for_user

    def slow(*args, **kwargs):
        ranked = original(*args, **kwargs)
        clock[0] = 901.0
        return ranked

    monkeypatch.setattr(daily, "recommend_for_user", slow)
    summary = generate(env, monotonic=lambda: clock[0])
    assert summary["rank_success"] == 1
    assert summary["publish_success"] == 0
    assert summary["failures"][0]["reason"] == "budget_exhausted"
    assert delivery(env) is None


def test_mmr_order_survives_publication_and_top5_reader(env, monkeypatch):
    records = papers(3)
    records[2]["title"] = "Ocean Climate Forecast"
    records[2]["abstract"] = "Ocean climate forecasts"
    snapshot(env, records)
    event(env, ["graph"])
    monkeypatch.setattr(daily, "_profile_ranker_enabled", lambda _: True)

    def scored(paper, profile, **kwargs):
        ranked = rank_paper_v2(paper, profile, **kwargs)
        score = {
            "10.1234/paper0": 0.95,
            "10.1234/paper1": 0.94,
            "10.1234/paper2": 0.85,
        }[paper["doi"]]
        return replace(ranked, normalized_score=score, score=score * 5, raw_score=score)

    monkeypatch.setattr(daily, "rank_paper_v2", scored)
    generate(env)
    raw = delivery(env)
    assert [row["doi"] for row in raw["items"]] == [
        "10.1234/paper0",
        "10.1234/paper2",
        "10.1234/paper1",
    ]
    assert raw["items"][1]["score"] < raw["items"][2]["score"]
    shown = load_recommendation_artifact(
        env["artifacts_dir"],
        env["alice"],
        5,
        policy=env["state"].policy(env["alice"], now=NOW),
        now=NOW,
    )
    assert [row["doi"] for row in shown["items"]] == [
        row["doi"] for row in raw["items"]
    ]


def test_cached_public_tokens_once_across_users(env, monkeypatch):
    snapshot(env)
    original = daily._paper_terms
    counts = Counter()

    def tracked(paper):
        counts[generate_result_key(paper)] += 1
        return original(paper)

    monkeypatch.setattr(daily, "_paper_terms", tracked)
    generate(env, usernames=["alice", "bob"])
    assert len(counts) == 8
    assert set(counts.values()) == {1}


def test_policy_filter_precedes_candidate_cap_and_seen_is_not_hide():
    records = [
        {**paper, "canonical_key": generate_result_key(paper)} for paper in papers(4)
    ]
    hidden = frozenset(paper["canonical_key"] for paper in records[:3])
    policy = RecommendationPolicy(
        "fixture", hidden=hidden, seen=frozenset({records[-1]["canonical_key"]})
    )
    with patch.object(daily, "MAX_CANDIDATES", 1):
        items, mode, metadata = daily.recommend_for_user(
            records,
            profile=RecommendationProfile(),
            v1_terms=Counter(),
            policy=policy,
            run_id="today",
            now=NOW,
            use_profile_ranker=False,
            feature_cache={},
        )
    assert [item["canonical_key"] for item in items] == [records[-1]["canonical_key"]]
    assert mode == "metadata" and metadata


def test_exposure_cooldown_excludes_next_run_not_current():
    record = {**papers(1)[0], "canonical_key": generate_result_key(papers(1)[0])}
    policy = RecommendationPolicy(
        "fixture", recent_exposures=((record["canonical_key"], "current"),)
    )
    options = dict(
        profile=RecommendationProfile(),
        v1_terms=Counter(),
        policy=policy,
        now=NOW,
        use_profile_ranker=False,
        feature_cache={},
    )
    assert daily.recommend_for_user([record], run_id="current", **options)[0]
    assert daily.recommend_for_user([record], run_id="next", **options)[0] == []


def test_cli_rejects_obsolete_bypass_and_invalid_timestamp():
    parser = daily.build_parser()
    for option in ("--skip-existing", "--papers-json", "--related-papers-json"):
        with pytest.raises(SystemExit):
            parser.parse_args([option])
    with pytest.raises(ValueError):
        daily._run_datetime("garbage")
    with pytest.raises(ValueError):
        daily._run_datetime("2026-09-25T00:00:00")
    assert daily._run_datetime("2026-09-25T19:00:00+09:00") == NOW


def test_current_policy_failure_at_publication_cannot_commit(env, monkeypatch):
    snapshot(env)
    original = daily.RecommendationState.policy
    calls = [0]

    def fail_second(self, *args, **kwargs):
        calls[0] += 1
        if calls[0] == 2:
            raise sqlite3.OperationalError("private detail")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(daily.RecommendationState, "policy", fail_second)
    summary = generate(env)
    assert summary["rank_success"] == 1 and summary["publish_success"] == 0
    assert delivery(env) is None
    assert not list(env["artifacts_dir"].rglob("*.tmp"))


def test_events_unavailable_and_error_are_explicit_degraded(env):
    snapshot(env)
    with sqlite3.connect(env["events_db"]) as conn:
        conn.execute("DROP TABLE user_events")
    generate(env)
    raw = delivery(env)
    assert "events_error" in raw["degraded_reasons"]
    assert raw["items"] and raw["status"] == "degraded"
    failed = generate(env, events_db=env["root"] / "new-events.db")
    assert failed["publish_success"] == 0
    assert failed["failures"][0]["reason"] == "policy_unavailable"


def test_validation_rejects_old_external_artifact_in_same_run(env):
    snapshot(env)
    generate(env)
    raw = delivery(env)
    path = env["artifacts_dir"] / env["alice"] / (raw["run_id"] + ".json")
    path.write_text(json.dumps({**raw, "producer": "openclaw", "items": []}))
    summary = generate(env)
    assert summary["publish_success"] == 1 and summary["reused"] == 0
    assert validate_delivery(delivery(env), incarnation=env["alice"], now=NOW)["items"]


def test_no_network_provider_or_paid_model_path(env, monkeypatch):
    import socket

    snapshot(env)

    def reject_network(*args, **kwargs):
        raise AssertionError("batch must never use network")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(socket, "socket", reject_network)
    assert generate(env)["publish_success"] == 1


def test_owner_bookmarks_are_bounded_and_never_read_other_users(env):
    bookmark(env, "bob", "OtherOwnerPrivateMarker")
    with sqlite3.connect(env["bookmarks_db"]) as conn:
        for index in range(505):
            conn.execute(
                "INSERT INTO bookmarks VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    f"a-{index:04}",
                    "alice",
                    "Graph",
                    "Graph",
                    "[]",
                    "notes",
                    "report",
                    NOW.isoformat(),
                    json.dumps({"account_incarnation": env["alice"]}),
                ),
            )
    loaded, status = daily.load_bookmarks(
        env["bookmarks_db"], "alice", account_incarnation=env["alice"]
    )
    assert status == "ok" and len(loaded) == 500
    assert "OtherOwnerPrivateMarker" not in repr(loaded)
    assert all(
        not hasattr(row, "notes") and not hasattr(row, "report") for row in loaded
    )


def test_event_loader_receives_authoritative_incarnation_and_old_claim_is_ignored(
    env, monkeypatch
):
    snapshot(env)
    event(env, ["graph"], incarnation="old-account-incarnation")
    monkeypatch.setattr(daily, "_profile_ranker_enabled", lambda _: True)
    original = daily.load_user_event_signals
    calls = []

    def capture(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(daily, "load_user_event_signals", capture)
    generate(env)
    assert calls[0]["account_incarnation"] == env["alice"]
    assert calls[0]["legacy_before"] is None
    assert delivery(env)["profile"]["event_count"] == 0
    assert delivery(env)["scoring_mode"] == "metadata"


def test_user_cap_is_explicit_and_publish_count_is_not_rank_count(env, monkeypatch):
    snapshot(env)
    monkeypatch.setattr(daily, "MAX_USERS", 1)
    summary = generate(env, usernames=["alice", "bob"])
    assert summary["users_seen"] == 2
    assert summary["rank_success"] == summary["publish_success"] == 1
    assert summary["failures"] == [
        {"account_incarnation": env["bob"], "reason": "user_cap"}
    ]


def test_pruning_only_valid_owned_expired_files_preserves_current_and_legacy(env):
    snapshot(env)
    generate(env)
    raw = delivery(env)
    owner = env["artifacts_dir"] / env["alice"]
    old = {
        **raw,
        "run_id": "old",
        "run_at": (NOW - timedelta(days=31)).isoformat(),
        "cutoff": (NOW - timedelta(days=31)).isoformat(),
    }
    expired = owner / "old.json"
    expired.write_text(json.dumps(old))
    legacy = owner / "legacy.json"
    legacy.write_text('{"producer":"old","do_not_delete":true}')
    other = env["artifacts_dir"] / env["bob"]
    other.mkdir()
    foreign = other / "old.json"
    foreign.write_text(json.dumps({**old, "account_incarnation": env["bob"]}))
    daily._prune_deliveries(
        env["artifacts_dir"],
        env["alice"],
        current_run=raw["run_id"],
        now=NOW,
        deadline=1,
        monotonic=lambda: 0,
    )
    assert not expired.exists()
    assert legacy.exists() and foreign.exists()
    assert (owner / (raw["run_id"] + ".json")).exists()


def test_symlink_owner_directory_never_publishes_outside_root(env):
    snapshot(env)
    outside = env["root"] / "outside"
    outside.mkdir()
    env["artifacts_dir"].mkdir()
    (env["artifacts_dir"] / env["alice"]).symlink_to(outside, target_is_directory=True)
    summary = generate(env)
    assert summary["rank_success"] == 1 and summary["publish_success"] == 0
    assert list(outside.iterdir()) == []


def test_same_batch_lease_applies_to_programmatic_and_cli_entry(env):
    from filelock import FileLock, Timeout

    lock = env["users_db"].parent / ".recommendations-batch.lock"
    with FileLock(str(lock), timeout=0):
        with pytest.raises(Timeout):
            generate(env)


def test_private_staging_retention_preserves_selected_other_owner_and_legacy(env):
    policy = TrustedReceiverPolicy(
        "owner_local", "private", "owner-fixture", account_incarnation=env["alice"]
    )
    registration = daily.SourceRegistration(f"private/{env['alice']}", policy)
    expired = snapshot(
        env, policy=policy, collected=NOW - timedelta(days=8), run="expired"
    )
    archived = expired.with_name("expired.json")
    expired.rename(archived)
    expired = archived
    retained = snapshot(
        env, policy=policy, collected=NOW - timedelta(days=8), run="selected"
    )
    archived = retained.with_name("selected.json")
    retained.rename(archived)
    retained = archived
    fresh = snapshot(env, policy=policy, run="fresh")
    other_policy = TrustedReceiverPolicy(
        "owner_local", "private", "owner-fixture", account_incarnation=env["bob"]
    )
    foreign = snapshot(
        env, policy=other_policy, collected=NOW - timedelta(days=8), run="foreign"
    )
    legacy = expired.parent / "legacy.json"
    legacy.write_text('{"collected_at":"2020-01-01T00:00:00+00:00","private":"leave"}')
    daily._prune_private_staging(
        env["candidate_root"],
        (registration,),
        incarnation=env["alice"],
        final_root=env["artifacts_dir"],
        keep={retained.absolute()},
        now=NOW,
        deadline=1,
        monotonic=lambda: 0,
    )
    assert not expired.exists()
    assert retained.exists() and fresh.exists() and foreign.exists() and legacy.exists()


def test_shared_policy_store_initialization_failure_is_explicit_per_user(
    env, monkeypatch
):
    def broken_state(*args, **kwargs):
        raise sqlite3.OperationalError("private database details")

    monkeypatch.setattr(daily, "RecommendationState", broken_state)
    summary = generate(env, usernames=["alice", "bob"])
    assert summary["publish_success"] == summary["rank_success"] == 0
    assert len(summary["failures"]) == 2
    assert {failure["reason"] for failure in summary["failures"]} == {
        "policy_unavailable"
    }


def test_bookmark_claim_filter_precedes_cap_and_input_hash(env):
    snapshot(env)
    bookmark(env)
    generate(env)
    baseline = delivery(env)["input_manifest_hash"]
    with sqlite3.connect(env["bookmarks_db"]) as conn:
        for index in range(600):
            conn.execute(
                "INSERT INTO bookmarks VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    f"z-foreign-{index:04}",
                    "alice",
                    "ForeignPrivateTopic",
                    "ForeignPrivateTitle",
                    json.dumps([{"title": "ForeignPrivatePaper"}]),
                    "notes",
                    "report",
                    (NOW + timedelta(seconds=1)).isoformat(),
                    json.dumps({"account_incarnation": env["bob"]}),
                ),
            )
    loaded, status = daily.load_bookmarks(
        env["bookmarks_db"], "alice", account_incarnation=env["alice"]
    )
    assert status == "ok" and len(loaded) == 1
    assert loaded[0].title == "Graph retrieval private_bookmark_marker"
    assert "ForeignPrivate" not in repr(loaded)
    generate(env)
    assert delivery(env)["input_manifest_hash"] == baseline


def test_bookmark_account_recreation_does_not_rebind_captured_principal(env):
    bookmark(env)
    old = env["alice"]
    env["users"].begin_delete("alice", old)
    env["users"].finish_delete("alice", old, cleanup_succeeded=True)
    new = env["users"].create_account("alice", {"role": "user"})["account_incarnation"]
    with sqlite3.connect(env["bookmarks_db"]) as conn:
        conn.execute(
            "INSERT INTO bookmarks VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "new",
                "alice",
                "NewPrivate",
                "NewPrivate",
                "[]",
                "",
                "",
                NOW.isoformat(),
                json.dumps({"account_incarnation": new}),
            ),
        )
        conn.execute(
            "INSERT INTO bookmarks VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "unbound",
                "alice",
                "Unbound",
                "Unbound",
                "[]",
                "",
                "",
                NOW.isoformat(),
                None,
            ),
        )
    old_rows, _ = daily.load_bookmarks(
        env["bookmarks_db"], "alice", account_incarnation=old
    )
    new_rows, _ = daily.load_bookmarks(
        env["bookmarks_db"], "alice", account_incarnation=new
    )
    assert [row.title for row in old_rows] == [
        "Graph retrieval private_bookmark_marker"
    ]
    assert [row.title for row in new_rows] == ["NewPrivate"]


def test_original_account_legacy_bookmarks_preserved_but_null_claim_and_corruption_rejected(
    env,
):
    metadata_cases = {
        "legacy-sql-null": None,
        "legacy-object": "{}",
        "matching": json.dumps({"account_incarnation": env["alice"]}),
        "explicit-null": '{"account_incarnation":null}',
        "foreign": json.dumps({"account_incarnation": env["bob"]}),
        "empty-claim": '{"account_incarnation":""}',
        "number-claim": '{"account_incarnation":7}',
        "corrupt": "{invalid",
        "array": "[]",
        "scalar-null": "null",
        "empty-metadata": "",
    }
    with sqlite3.connect(env["bookmarks_db"]) as conn:
        for name, metadata in metadata_cases.items():
            conn.execute(
                "INSERT INTO bookmarks VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    name,
                    "alice",
                    name,
                    name,
                    "[]",
                    "private notes",
                    "private report",
                    NOW.isoformat(),
                    metadata,
                ),
            )
    original, status = daily.load_bookmarks(
        env["bookmarks_db"],
        "alice",
        account_incarnation=env["alice"],
        legacy_event_cutoff=NOW.isoformat(),
    )
    assert status == "ok"
    assert {row.title for row in original} == {
        "legacy-sql-null",
        "legacy-object",
        "matching",
    }
    recreated, status = daily.load_bookmarks(
        env["bookmarks_db"], "alice", account_incarnation=env["alice"]
    )
    assert status == "ok" and [row.title for row in recreated] == ["matching"]


@pytest.mark.parametrize(
    "use_v2,fallback", [(False, False), (True, False), (True, True)]
)
@pytest.mark.parametrize("control", ["interested", "topic_less"])
def test_durable_control_undo_overrides_analytics_replay_private_id(
    env, monkeypatch, use_v2, fallback, control
):
    private_policy = TrustedReceiverPolicy(
        "owner_local", "private", "owner-fixture", account_incarnation=env["alice"]
    )
    snapshot(env, policy=private_policy)
    registration = daily.SourceRegistration(f"private/{env['alice']}", private_policy)
    monkeypatch.setattr(daily, "_profile_ranker_enabled", lambda _: use_v2)
    if fallback:
        monkeypatch.setattr(
            daily,
            "rank_paper_v2",
            lambda *a, **k: (_ for _ in ()).throw(ValueError("ranker")),
        )
    key = generate_result_key(papers()[0])
    options = {"registrations": [registration], "min_score": 0, "v2_min_score": 0}
    generate(env, **options)
    baseline = delivery(env)["items"]
    action(env, key, control)
    generate(env, **options)  # Durable action works without an analytics emitter.
    active = delivery(env)["items"]
    baseline_score = next(
        item["score"] for item in baseline if item["canonical_key"] == key
    )
    active_score = next(
        (item["score"] for item in active if item["canonical_key"] == key), 0
    )
    assert (
        active_score > baseline_score
        if control == "interested"
        else active_score < baseline_score
    )
    event(
        env, ["graph"], event_type="recommendation_feedback", feedback=control, key=key
    )
    env["state"].apply_action(
        env["alice"],
        canonical_key=key,
        action="undo",
        undo_action=control,
        request_id="undo",
        run_id="prior",
        now=NOW,
    )
    generate(env, **options)
    assert delivery(env)["items"] == baseline
    assert delivery(env)["profile"]["event_count"] == 0


@pytest.mark.parametrize("loss", ["file", "table", "replacement"])
def test_fresh_batch_after_acknowledged_hide_store_loss_fails_closed(env, loss):
    snapshot(env)
    action(env, generate_result_key(papers()[0]), "hide")
    if loss == "table":
        with sqlite3.connect(env["events_db"]) as conn:
            conn.execute("DROP TABLE recommendation_actions")
    else:
        env["events_db"].unlink()
        if loss == "replacement":
            with sqlite3.connect(env["events_db"]) as conn:
                conn.execute("CREATE TABLE replacement(x)")
    result = generate(env)
    assert result["rank_success"] == result["publish_success"] == 0
    assert result["failures"][0]["reason"] == "policy_unavailable"
    assert delivery(env) is None
    with pytest.raises(sqlite3.Error):
        RecommendationState.initialize(env["events_db"], authority=env["users"])


@pytest.mark.parametrize(
    "health,reasons,nonempty",
    [
        ("ready", (), True),
        ("empty", (), False),
        ("error", ("provider_error",), False),
        ("disabled", ("source_disabled",), False),
        ("degraded", ("partial_failure",), True),
    ],
)
def test_serialized_acquisition_health_survives_current_slot_and_generation(
    env, health, reasons, nonempty
):
    policy = daily.DEFAULT_REGISTRATIONS[0].policy
    captured = make_candidate_snapshot(
        papers() if nonempty else [],
        policy=policy,
        source_run_id="captured-health",
        collected_at=NOW,
        now=NOW,
        acquisition_status=health,
        acquisition_reasons=reasons,
    )
    path = write_candidate_snapshot(
        captured, root=env["candidate_root"], final_root=env["artifacts_dir"]
    )
    for index in range(405):
        (path.parent / f"history-{index}.receipt.json").write_text("not a snapshot")
        (path.parent / f"history-{index}.wiki.md").write_text("ignored sidecar")
    generate(env)
    raw = delivery(env)
    assert raw["source_statuses"]["local_public"] == health
    assert raw["input_manifest"][0]["acquisition_status"] == health
    assert raw["input_manifest"][0]["acquisition_reasons"] == list(reasons)
    assert bool(raw["items"]) == nonempty
    if health == "error":
        assert "source_error" in raw["degraded_reasons"]
    if health == "disabled":
        assert "source_disabled" in raw["degraded_reasons"]
    if health == "degraded":
        assert raw["status"] == "degraded"


@pytest.mark.parametrize("control", ["interested", "topic_less"])
def test_expired_durable_control_cannot_be_revived_by_recent_analytics(
    env, monkeypatch, control
):
    snapshot(env)
    monkeypatch.setattr(daily, "_profile_ranker_enabled", lambda _: True)
    generate(env)
    baseline = delivery(env)["items"]
    key = generate_result_key(papers()[0])
    env["state"].apply_action(
        env["alice"],
        canonical_key=key,
        action=control,
        request_id="expired",
        run_id="prior",
        now=NOW - timedelta(days=91),
    )
    event(
        env, ["graph"], event_type="recommendation_feedback", feedback=control, key=key
    )
    generate(env)
    assert delivery(env)["items"] == baseline


@pytest.mark.parametrize("health", ["empty", "disabled", "error", "degraded"])
def test_collector_fixture_health_reloads_into_common_delivery(env, health):
    from src.related_paper_wiki import collect_review_build_wiki

    calls = []

    def provider(seed, deadline):
        calls.append(seed)
        if health == "error" or (health == "degraded" and len(calls) == 1):
            return [], [{"status": "error"}]
        return (
            (papers(1), [{"status": "searched"}])
            if health == "degraded"
            else ([], [{"status": "searched_empty"}])
        )

    result = collect_review_build_wiki(
        candidate_root=env["candidate_root"],
        final_root=env["artifacts_dir"],
        run_at=NOW.isoformat(),
        source_qualified=health != "disabled",
        attempt=provider,
        clock=lambda: 0,
    )
    assert result["acquisition_status"] == health
    generate(env)
    raw = delivery(env)
    assert raw["source_statuses"]["local_public"] == health
    assert raw["input_manifest"][0]["acquisition_status"] == health
    assert bool(raw["items"]) == (health == "degraded")
    if health == "disabled":
        assert calls == []
