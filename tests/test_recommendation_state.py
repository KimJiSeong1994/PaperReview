"""Behavioral tests for durable, incarnation-scoped recommendation policy."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from src.recommendation_state import RecommendationState, RecommendationStateError
from src.storage.user_db import UserDB

NOW = datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc)


def expose(state, *, incarnation="account-A", key="paper", run="run-a", at=NOW):
    return state.record_exposure(
        incarnation,
        run_id=run,
        canonical_key=key,
        visible_fraction=0.5,
        visible_ms=1000,
        now=at,
    )


def outcome(
    state, *, incarnation="account-A", key="paper", kind="save", oid="save-1", at=NOW
):
    return state.record_outcome(
        incarnation,
        canonical_key=key,
        kind=kind,
        outcome_id=oid,
        now=at,
    )


def test_outcome_last_touch_and_deterministic_tie(state):
    expose(state, run="older", at=NOW - timedelta(hours=1))
    expose(state, run="z")
    expose(state, run="a")
    result = outcome(state)
    assert result["status"] == "attributed" and result["credited"]
    assert result["run_id"] == "a" and result["visible_at"] == NOW.isoformat()
    assert outcome(state, at=NOW + timedelta(days=2)) == result
    duplicate = outcome(state, oid="another-save")
    assert duplicate["reason"] == "already_credited" and not duplicate["credited"]
    assert outcome(state, key="another-paper")["status"] == "not_attributed"


@pytest.mark.parametrize("kind", ["save", "review_start"])
def test_multi_paper_producer_outcome_replays_never_move_attribution(state, kind):
    expose(state, key="paper-a", run="first-a")
    expose(state, key="paper-b", run="first-b")
    first = {
        key: outcome(state, key=key, kind=kind, oid="shared-producer-id")
        for key in ("paper-a", "paper-b")
    }
    assert all(row["credited"] for row in first.values())
    tomorrow = NOW + timedelta(days=1)
    for key in first:
        expose(state, key=key, run="later-run", at=tomorrow)
        assert (
            outcome(state, key=key, kind=kind, oid="shared-producer-id", at=tomorrow)
            == first[key]
        )
    with sqlite3.connect(state.db_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM recommendation_outcomes").fetchone()[0]
            == 2
        )
    metrics = state.outcome_metrics(
        "account-A",
        since=NOW,
        until=NOW + timedelta(days=2),
        now=tomorrow,
    )
    assert metrics["total"]["positive_userdays"] == 1
    assert metrics["total"]["per_kind_counts"][kind] == 1


def test_old_trusted_receipt_without_outcomes_refused_by_open_and_initialize(state):
    import json

    with sqlite3.connect(state.db_path) as conn:
        conn.execute("DROP TABLE recommendation_outcomes")
        old_schema = RecommendationState._schema(conn)
    # Simulate a legitimately stored earlier-release schema receipt: actual
    # and trusted schemas agree, but neither meets the running code contract.
    receipt = state.authority.policy_store_receipt(state.db_path)
    receipt["schema"] = old_schema
    with state.authority.transaction() as tx:
        tx.conn.execute(
            "UPDATE account_store_meta SET value=? WHERE key='policy_store'",
            (json.dumps(receipt),),
        )
    for operation in (
        lambda: RecommendationState(state.db_path, authority=state.authority),
        lambda: RecommendationState.initialize(
            state.db_path, authority=state.authority
        ),
    ):
        with pytest.raises(sqlite3.Error, match="schema_mismatch_required"):
            operation()
    with sqlite3.connect(state.db_path) as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='recommendation_outcomes'"
            ).fetchone()
            is None
        )


@pytest.mark.parametrize(
    "offset,attributed",
    [
        (timedelta(days=-7), True),
        (timedelta(days=-7, microseconds=-1), False),
        (timedelta(microseconds=1), False),
    ],
)
def test_outcome_inclusive_window_and_future_rejection(state, offset, attributed):
    expose(state, at=NOW + offset)
    assert (outcome(state)["status"] == "attributed") is attributed


def test_unseen_foreign_and_nonqualifying_never_receive_attribution(state):
    expose(state, incarnation="foreign")
    expose(state, key="reserve-other")
    with pytest.raises(RecommendationStateError):
        state.record_exposure(
            "account-A",
            run_id="prefetch",
            canonical_key="paper",
            visible_fraction=0,
            visible_ms=0,
            now=NOW,
        )
    result = outcome(state)
    assert result["status"] == "not_attributed" and not result["credited"]
    expose(state)
    # A late exposure cannot retroactively change an already received outcome.
    assert outcome(state) == result
    assert outcome(state, oid="new-outcome")["status"] == "attributed"


def test_metrics_binary_visible_days_and_maturity_boundary(state):
    expose(state)
    expose(state, key="second")
    outcome(state)
    outcome(state, kind="review_start", oid="review-1")
    outcome(state, key="second", oid="save-second")
    expose(state, at=NOW + timedelta(days=1))
    metrics = state.outcome_metrics(
        "account-A",
        since=NOW,
        until=NOW + timedelta(days=2),
        now=NOW + timedelta(days=8),
    )
    assert metrics["total"] == {
        "visible_userdays": 2,
        "positive_userdays": 1,
        "per_kind_counts": {"save": 1, "review_start": 1},
        "rate": 0.5,
    }
    assert metrics["mature"]["visible_userdays"] == 1
    assert metrics["mature"]["positive_userdays"] == 1
    assert metrics["right_censored"]["visible_userdays"] == 1
    earlier = state.outcome_metrics(
        "account-A",
        since=NOW,
        until=NOW + timedelta(days=2),
        now=NOW + timedelta(days=8, microseconds=-1),
    )
    assert earlier["mature"]["rate"] is None
    assert "paper" not in str(metrics) and "account-A" not in str(metrics)


def test_outcome_metrics_exclude_future_and_foreign_and_validate_bounds(state):
    expose(state)
    outcome(state, at=NOW + timedelta(days=1))
    expose(state, at=NOW + timedelta(days=2))
    expose(state, incarnation="foreign")
    metrics = state.outcome_metrics(
        "account-A", since=NOW, until=NOW + timedelta(days=3), now=NOW
    )
    assert metrics["total"]["visible_userdays"] == 1
    assert metrics["total"]["positive_userdays"] == 0
    with pytest.raises(RecommendationStateError, match="invalid_metric_day_range"):
        state.outcome_metrics(
            "account-A", since=NOW + timedelta(hours=1), until=NOW + timedelta(days=1)
        )
    with pytest.raises(RecommendationStateError, match="invalid_outcome_kind"):
        outcome(state, kind="click")


def test_outcome_retention_and_incarnation_cleanup(state):
    expose(state)
    outcome(state)
    expose(state, incarnation="replacement")
    outcome(state, incarnation="replacement")
    state.delete_incarnation("account-A")
    with sqlite3.connect(state.db_path) as conn:
        assert conn.execute(
            "SELECT incarnation FROM recommendation_outcomes"
        ).fetchall() == [("replacement",)]
    state.prune(now=NOW + timedelta(days=30))
    with sqlite3.connect(state.db_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM recommendation_outcomes").fetchone()[0]
            == 1
        )
    state.prune(now=NOW + timedelta(days=30, microseconds=1))
    with sqlite3.connect(state.db_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM recommendation_outcomes").fetchone()[0]
            == 0
        )


def test_concurrent_outcomes_credit_same_day_once(state):
    expose(state)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda n: outcome(state, oid=f"save-{n}"), range(8)))
    assert sum(row["credited"] for row in rows) == 1
    assert (
        state.outcome_metrics(
            "account-A", since=NOW, until=NOW + timedelta(days=1), now=NOW
        )["total"]["positive_userdays"]
        == 1
    )


def test_new_exposure_day_can_gain_credit_but_replayed_actual_outcome_cannot(state):
    expose(state)
    first = outcome(state)
    next_day = NOW + timedelta(days=1)
    expose(state, run="next-run", at=next_day)
    assert outcome(state, at=next_day) == first
    later = outcome(state, oid="second-save", at=next_day)
    assert later["credited"] and later["run_id"] == "next-run"
    metrics = state.outcome_metrics(
        "account-A", since=NOW, until=NOW + timedelta(days=2), now=next_day
    )
    assert metrics["total"]["positive_userdays"] == 2


def test_outcome_receipts_are_strictly_part_of_policy_store_schema(state):
    with sqlite3.connect(state.db_path) as conn:
        conn.execute("DROP TABLE recommendation_outcomes")
    with pytest.raises(sqlite3.Error, match="schema_mismatch"):
        outcome(state)
    with pytest.raises(sqlite3.Error, match="schema_mismatch"):
        state.outcome_metrics("account-A", since=NOW, until=NOW + timedelta(days=1))


@pytest.fixture
def state(tmp_path):
    authority = UserDB(tmp_path / "users.db")
    return RecommendationState.initialize(tmp_path / "events.db", authority=authority)


def act(
    state,
    action,
    *,
    request_id="request-1",
    key="doi:10.1234/a",
    incarnation="account-A",
    **kwargs,
):
    return state.apply_action(
        incarnation,
        run_id="run-1",
        canonical_key=key,
        action=action,
        request_id=request_id,
        now=NOW,
        **kwargs,
    )


def test_hard_hide_survives_retention_and_isolated_account_recreation(state):
    act(state, "hide")
    state.prune(now=NOW + timedelta(days=150))
    assert state.policy("account-A", now=NOW + timedelta(days=150)).suppressed == {
        "doi:10.1234/a"
    }
    assert state.policy("account-B", now=NOW).suppressed == set()


def test_idempotency_replay_does_not_reapply_an_undone_action(state):
    original = act(state, "hide")
    act(state, "undo", request_id="undo-1", undo_action="hide")
    assert act(state, "hide") == original
    assert state.policy("account-A", now=NOW).hidden == set()


def test_idempotency_payload_conflict_leaves_original_policy_untouched(state):
    act(state, "hide")
    with pytest.raises(RecommendationStateError, match="idempotency_conflict"):
        act(state, "already_seen")
    assert state.policy("account-A", now=NOW).hidden == {"doi:10.1234/a"}
    assert state.policy("account-A", now=NOW).already_seen == set()


def test_concurrent_identical_actions_have_one_durable_receipt(state):
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: act(state, "hide"), range(12)))
    assert all(response == responses[0] for response in responses)
    with sqlite3.connect(state.db_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM recommendation_actions").fetchone()[0]
            == 1
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM recommendation_receipts").fetchone()[0]
            == 1
        )


def test_undo_only_removes_target_action(state):
    act(state, "hide")
    act(state, "already_seen", request_id="read-1")
    act(state, "undo", request_id="undo-1", undo_action="hide")
    policy = state.policy("account-A", now=NOW)
    assert not policy.hidden
    assert policy.already_seen == {"doi:10.1234/a"}
    assert policy.suppressed == {"doi:10.1234/a"}


def test_interest_and_read_do_not_become_hard_suppression(state):
    act(state, "interested")
    act(state, "seen", request_id="seen-1")
    act(state, "topic_less", request_id="topic-1", key="doi:10.1234/b")
    policy = state.policy("account-A", now=NOW)
    assert policy.interested == policy.seen == {"doi:10.1234/a"}
    assert policy.topic_less == {"doi:10.1234/b": NOW.isoformat()}
    assert not policy.suppressed


def test_read_and_already_seen_have_different_expiry(state):
    act(state, "seen")
    act(state, "already_seen", request_id="already-1")
    at_30 = state.policy("account-A", now=NOW + timedelta(days=30))
    assert not at_30.seen
    assert at_30.already_seen == {"doi:10.1234/a"}
    assert not state.policy("account-A", now=NOW + timedelta(days=90)).suppressed


def test_exposure_is_deduplicated_and_only_blocks_later_runs(state):
    kwargs = dict(
        run_id="run-1",
        canonical_key="doi:10.1234/a",
        visible_fraction=0.5,
        visible_ms=1000,
        now=NOW,
    )
    assert state.record_exposure("account-A", **kwargs)
    assert not state.record_exposure("account-A", **kwargs)
    policy = state.policy("account-A", now=NOW)
    assert not policy.excluded_for_run("run-1")
    assert policy.excluded_for_run("run-2") == {"doi:10.1234/a"}
    assert not policy.suppressed and not policy.interested and not policy.topic_less
    assert not state.policy("account-A", now=NOW + timedelta(days=7)).excluded_for_run(
        "run-2"
    )


@pytest.mark.parametrize(
    "fraction,ms",
    [
        (0.49, 1000),
        (1, 999),
        (float("nan"), 1000),
        (float("inf"), 1000),
        (True, 1000),
        (1, True),
        (1, 60001),
    ],
)
def test_nonqualifying_exposure_is_not_recorded(state, fraction, ms):
    with pytest.raises(RecommendationStateError, match="insufficient_visibility"):
        state.record_exposure(
            "account-A",
            run_id="run-1",
            canonical_key="doi:10.1234/a",
            visible_fraction=fraction,
            visible_ms=ms,
            now=NOW,
        )
    assert not state.policy("account-A", now=NOW).recent_exposures


def test_top5_projection_refills_without_score_sorting_or_mutation(state):
    papers = [
        {"canonical_key": f"doi:10.1234/{n}", "final_rank": n, "score": 100 - n}
        for n in range(1, 9)
    ]
    papers[0]["score"] = 0
    act(state, "hide", key="doi:10.1234/2")
    act(state, "hide", request_id="hide-6", key="doi:10.1234/6")
    act(state, "seen", request_id="seen-1", key="doi:10.1234/1")
    projected = state.policy("account-A", now=NOW).project(papers)
    assert [p["final_rank"] for p in projected] == [1, 3, 4, 5, 7]
    assert [p["display_position"] for p in projected] == [1, 2, 3, 4, 5]
    assert projected[0]["seen"] is True
    assert all("display_position" not in p for p in papers)


def test_short_reserve_never_relaxes_hard_policy_to_fill(state):
    act(state, "hide")
    projected = state.policy("account-A", now=NOW).project(
        [
            {"canonical_key": "doi:10.1234/a", "final_rank": 1},
            {"canonical_key": "doi:10.1234/b", "final_rank": 2},
        ]
    )
    assert [paper["canonical_key"] for paper in projected] == ["doi:10.1234/b"]


def test_generation_cleanup_does_not_delete_replacement_account_data(state):
    act(state, "hide")
    act(state, "interested", incarnation="account-B")
    state.record_exposure(
        "account-A",
        run_id="run-1",
        canonical_key="doi:10.1234/a",
        visible_fraction=1,
        visible_ms=1000,
        now=NOW,
    )
    state.delete_incarnation("account-A")
    state.delete_incarnation("account-A")
    assert not state.policy("account-A", now=NOW).suppressed
    assert not state.policy("account-A", now=NOW).recent_exposures
    assert state.policy("account-B", now=NOW).interested == {"doi:10.1234/a"}
    with sqlite3.connect(state.db_path) as conn:
        assert conn.execute(
            "SELECT incarnation FROM recommendation_receipts"
        ).fetchall() == [("account-B",)]


def test_failed_state_read_is_not_a_healthy_empty_profile(state):
    with sqlite3.connect(state.db_path) as conn:
        conn.execute("DROP TABLE recommendation_actions")
    with pytest.raises(sqlite3.OperationalError):
        state.policy("account-A", now=NOW)


@pytest.mark.parametrize(
    "action,extra", [("made-up", {}), ("undo", {}), ("seen", {"undo_action": "hide"})]
)
def test_invalid_actions_do_not_write_receipts(state, action, extra):
    with pytest.raises(RecommendationStateError):
        act(state, action, **extra)
    with sqlite3.connect(state.db_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM recommendation_receipts").fetchone()[0]
            == 0
        )


def test_naive_clock_and_control_character_keys_fail_closed(state):
    with pytest.raises(RecommendationStateError, match="timezone_required"):
        state.policy("account-A", now=NOW.replace(tzinfo=None))
    with pytest.raises(RecommendationStateError, match="invalid_canonical_key"):
        act(state, "hide", key="doi:10.1234/a\n")


@pytest.mark.parametrize("damage", ["file", "table", "marker", "empty", "foreign"])
def test_lost_or_replaced_policy_never_becomes_healthy_empty(state, tmp_path, damage):
    act(state, "hide")
    if damage in {"file", "empty", "foreign"}:
        state.db_path.unlink()
    if damage == "empty":
        sqlite3.connect(state.db_path).close()
    elif damage == "foreign":
        other = UserDB(tmp_path / "foreign-users.db")
        RecommendationState.initialize(state.db_path, authority=other)
    elif damage in {"table", "marker"}:
        with sqlite3.connect(state.db_path) as conn:
            conn.execute(
                "DROP TABLE "
                + (
                    "recommendation_actions"
                    if damage == "table"
                    else "recommendation_store_identity"
                )
            )
    for operation in (
        lambda: state.policy("account-A", now=NOW),
        lambda: RecommendationState(state.db_path, authority=state.authority),
        lambda: RecommendationState.initialize(
            state.db_path, authority=state.authority
        ),
    ):
        with pytest.raises(sqlite3.Error):
            operation()
    if damage == "file":
        assert not state.db_path.exists()


def test_explicit_provisioning_repeat_and_normal_open_retain_acknowledged_hide(state):
    act(state, "hide")
    receipt = state.authority.policy_store_receipt(state.db_path)
    for opened in (
        RecommendationState.initialize(state.db_path, authority=state.authority),
        RecommendationState(state.db_path, authority=state.authority),
    ):
        assert opened.policy("account-A", now=NOW).hidden == {"doi:10.1234/a"}
        assert opened.authority.policy_store_receipt(opened.db_path) == receipt


def test_normal_open_never_provisions(tmp_path):
    authority = UserDB(tmp_path / "users.db")
    path = tmp_path / "absent.db"
    with pytest.raises(sqlite3.Error, match="unprovisioned"):
        RecommendationState(path, authority=authority)
    assert not path.exists()


def test_concurrent_first_provisioning_uses_one_receipt(tmp_path):
    authority = UserDB(tmp_path / "users.db")
    path = tmp_path / "events.db"
    with ThreadPoolExecutor(max_workers=4) as pool:
        stores = list(
            pool.map(
                lambda _: RecommendationState.initialize(path, authority=authority),
                range(8),
            )
        )
    receipts = [store.authority.policy_store_receipt(path) for store in stores]
    assert all(receipt == receipts[0] for receipt in receipts)
    act(stores[0], "hide")
    assert stores[-1].policy("account-A", now=NOW).hidden == {"doi:10.1234/a"}


def test_schema_failure_rolls_back_and_does_not_claim_initialized(
    tmp_path, monkeypatch
):
    authority = UserDB(tmp_path / "users.db")
    path = tmp_path / "events.db"
    original = RecommendationState._create_schema

    def fail(conn):
        original(conn)
        raise RuntimeError("injected")

    with monkeypatch.context() as patch:
        patch.setattr(RecommendationState, "_create_schema", staticmethod(fail))
        with pytest.raises(RuntimeError):
            RecommendationState.initialize(path, authority=authority)
    assert authority.policy_store_receipt(path) is None
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'recommendation_%'"
            ).fetchall()
            == []
        )
    assert (
        RecommendationState.initialize(path, authority=authority)
        .policy("account-A")
        .hidden
        == set()
    )


def test_authority_commit_failure_leaves_orphan_not_automatically_adopted(tmp_path):
    authority = UserDB(tmp_path / "users.db")
    path = tmp_path / "events.db"
    with authority.transaction() as tx:
        tx.conn.execute("""CREATE TRIGGER refuse_policy BEFORE INSERT ON account_store_meta
                           WHEN NEW.key='policy_store'
                           BEGIN SELECT RAISE(ABORT, 'injected'); END""")
    with pytest.raises(sqlite3.Error):
        RecommendationState.initialize(path, authority=authority)
    assert authority.policy_store_receipt(path) is None
    with authority.transaction() as tx:
        tx.conn.execute("DROP TRIGGER refuse_policy")
    with pytest.raises(sqlite3.Error, match="untrusted_existing"):
        RecommendationState.initialize(path, authority=authority)
    with pytest.raises(sqlite3.Error, match="unprovisioned"):
        RecommendationState(path, authority=authority)


def test_schema_loss_in_nonqueried_table_is_detected_on_every_connection(state):
    with sqlite3.connect(state.db_path) as conn:
        conn.execute("DROP TABLE recommendation_receipts")
    with pytest.raises(sqlite3.Error, match="schema_mismatch"):
        state.policy("account-A", now=NOW)


def test_policy_access_inside_account_guard_has_no_nested_writer(state):
    account = state.authority.create_account("alice", {})
    with state.authority.account_guard("alice", account["account_incarnation"]):
        act(state, "hide", incarnation=account["account_incarnation"])
        assert state.policy(account["account_incarnation"], now=NOW).hidden


def test_replaced_empty_clone_with_copied_identity_is_not_adopted(state, tmp_path):
    act(state, "hide")
    clone = tmp_path / "clone.db"
    with sqlite3.connect(state.db_path) as source, sqlite3.connect(clone) as target:
        source.backup(target)
        target.execute("DELETE FROM recommendation_actions")
        target.execute("DELETE FROM recommendation_receipts")
    clone.replace(state.db_path)
    with pytest.raises(sqlite3.Error, match="file_replaced"):
        RecommendationState(state.db_path, authority=state.authority)
    with pytest.raises(sqlite3.Error, match="file_replaced"):
        RecommendationState.initialize(state.db_path, authority=state.authority)
