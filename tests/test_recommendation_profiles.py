import json
import sqlite3
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.events.event_types import EventType
from src.recommendation_profiles import (
    RecommendationEventSignal,
    _decay,
    build_recommendation_profile,
    load_user_event_signals,
    normalize_event_row,
)
from src.utils.paper_utils import generate_result_key

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)


class RecommendationProfileTests(unittest.TestCase):
    def signal(self, **kwargs):
        values = dict(
            event_type=EventType.QUERY_SUBMIT.value,
            created_at=NOW,
            terms=("private_marker",),
            event_id="1",
        )
        values.update(kwargs)
        return RecommendationEventSignal(**values)

    def test_distinct_event_counts_and_per_paper_day_cap(self):
        first = self.signal(paper_id="doi:10.1/a")
        second = replace(first, event_id="2")
        profile = build_recommendation_profile(
            Counter({"bookmarkword": 3}), [first, first, second], now=NOW
        )
        self.assertEqual(profile.event_count, 2)
        self.assertEqual(sum(profile.signal_counts.values()), 2)
        self.assertEqual(profile.positive_terms["private_marker"], 1.5)
        summary = profile.public_summary(bookmark_count=7, fallback_recent=False)
        self.assertEqual(summary["bookmark_count"], 7)
        self.assertNotIn("private_marker", json.dumps(summary))
        self.assertNotIn("bookmarkword", json.dumps(summary))
        self.assertNotIn("top_terms", summary)

    def test_true_half_life(self):
        for age, expected in ((0, 1), (14, 0.5), (28, 0.25)):
            self.assertAlmostEqual(
                _decay(self.signal(created_at=NOW - timedelta(days=age)), now=NOW),
                expected,
            )

    def test_invalid_future_synthetic_and_bounded_terms(self):
        row = {
            "event_type": EventType.QUERY_SUBMIT.value,
            "payload": {"terms": ["private_marker"]},
            "created_at": NOW.isoformat(),
        }
        for bad in (
            "bad",
            "2026-09-25T12:00:00",
            (NOW + timedelta(seconds=1)).isoformat(),
        ):
            self.assertIsNone(normalize_event_row({**row, "created_at": bad}, now=NOW))
        self.assertIsNone(normalize_event_row({**row, "source": "synthetic"}, now=NOW))
        row["payload"] = {
            "terms": [f"word{x}" for x in range(30)],
            "query": "secret_raw_query",
        }
        signal = normalize_event_row(row, now=NOW)
        self.assertEqual(len(signal.terms), 8)
        self.assertNotIn("secret_raw_query", signal.terms)
        invalid = [
            self.signal(created_at=NOW + timedelta(seconds=1)),
            self.signal(source="e2e"),
            self.signal(created_at=NOW.replace(tzinfo=None)),
            self.signal(event_type="unsupported"),
        ]
        self.assertEqual(
            build_recommendation_profile(Counter(), invalid, now=NOW).event_count, 0
        )

    def test_id_only_preferences_and_durable_public_affinity(self):
        paper = {
            "doi": "10.1234/a",
            "title": "Graph Learning",
            "notes": "private_marker",
        }
        key = generate_result_key(paper)
        positive = self.signal(
            event_type=EventType.RECOMMENDATION_FEEDBACK.value,
            terms=(),
            paper_id=key,
            feedback_type="interested",
        )
        profile = build_recommendation_profile(Counter(), [positive], now=NOW)
        self.assertFalse(profile.positive_paper_ids)
        self.assertFalse(profile.negative_paper_ids)
        read = replace(
            positive, event_type=EventType.RECOMMENDATION_READ.value, feedback_type=None
        )
        read_profile = build_recommendation_profile(Counter(), [read], now=NOW)
        self.assertFalse(read_profile.positive_paper_ids)
        self.assertFalse(read_profile.negative_paper_ids)
        self.assertEqual(read_profile.event_count, 0)
        negative = replace(positive, feedback_type="topic_less")
        profile = build_recommendation_profile(Counter(), [negative], now=NOW)
        self.assertFalse(profile.negative_paper_ids)
        self.assertFalse(profile.positive_terms)
        durable = build_recommendation_profile(
            Counter(),
            [],
            now=NOW,
            interested_papers=[paper],
            topic_less_papers=[(paper, NOW - timedelta(days=30))],
        )
        self.assertEqual(durable.positive_terms["graph"], 5)
        self.assertAlmostEqual(durable.negative_terms["graph"], 2.5)
        self.assertNotIn("private_marker", durable.positive_terms)
        self.assertEqual(durable.event_count, 0)
        combined = build_recommendation_profile(
            Counter(), [positive], now=NOW, interested_papers=[paper, paper]
        )
        self.assertEqual(combined.positive_terms["graph"], 5)
        unavailable = build_recommendation_profile(
            Counter(), [], now=NOW, event_status="error"
        )
        self.assertEqual(
            unavailable.public_summary(bookmark_count=0, fallback_recent=True)[
                "event_status"
            ],
            "error",
        )

    def test_recommendation_control_replay_is_not_independent_preference(self):
        controls = [
            self.signal(
                event_type=EventType.RECOMMENDATION_FEEDBACK.value,
                feedback_type=action,
                event_id=str(index),
                paper_id="doi:10.1234/a",
            )
            for index, action in enumerate(
                ("interested", "helpful", "topic_less", "less_like_this", "hide")
            )
        ]
        genuine = self.signal(event_type=EventType.PAPER_OPEN.value, event_id="genuine")
        expected = build_recommendation_profile(Counter(), [genuine], now=NOW)
        actual = build_recommendation_profile(Counter(), [*controls, genuine], now=NOW)
        self.assertEqual(actual, expected)
        for control in controls:
            self.assertIsNone(
                normalize_event_row(
                    {
                        "event_type": control.event_type,
                        "created_at": NOW.isoformat(),
                        "payload": {
                            "feedback_type": control.feedback_type,
                            "terms": ["private_marker"],
                        },
                    },
                    now=NOW,
                )
            )

    def test_loader_status_supported_flood_cutoff_and_stable_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite"
            self.assertEqual(
                load_user_event_signals(
                    path, "user", now=NOW, account_incarnation="current"
                ).status,
                "unavailable",
            )
            conn = sqlite3.connect(path)
            self.assertEqual(
                load_user_event_signals(
                    path, "user", now=NOW, account_incarnation="current"
                ).status,
                "error",
            )
            conn.execute(
                "CREATE TABLE user_events (id INTEGER PRIMARY KEY, user_id TEXT, event_type TEXT, payload TEXT, paper_id TEXT, created_at TEXT, source TEXT)"
            )
            conn.commit()
            empty = load_user_event_signals(
                path, "user", now=NOW, account_incarnation="current"
            )
            self.assertEqual((empty.status, empty.signals), ("ok", ()))
            supported = EventType.QUERY_SUBMIT.value

            def insert(event_id, event_type, created_at):
                conn.execute(
                    "INSERT INTO user_events VALUES (?, 'user', ?, ?, NULL, ?, 'app')",
                    (
                        event_id,
                        event_type,
                        '{"terms":["graph"],"account_incarnation":"current"}',
                        created_at,
                    ),
                )

            insert(1, supported, NOW.isoformat())
            insert(
                2, supported, NOW.astimezone(timezone(timedelta(hours=9))).isoformat()
            )
            insert(3, supported, (NOW - timedelta(days=90, seconds=1)).isoformat())
            insert(4, supported, "invalid")
            insert(5, supported, (NOW + timedelta(seconds=1)).isoformat())
            for number in range(6, 606):
                insert(number, "unsupported", NOW.isoformat())
            conn.commit()
            loaded = load_user_event_signals(
                path, "user", now=NOW, account_incarnation="current"
            )
            self.assertEqual(loaded.status, "ok")
            self.assertEqual([signal.event_id for signal in loaded.signals], ["2", "1"])
            self.assertTrue(all(signal.created_at == NOW for signal in loaded.signals))
            conn.close()

    def test_incarnation_filter_before_cap_and_authoritative_legacy_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite"
            cutoff = NOW - timedelta(days=1)
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "CREATE TABLE user_events (id INTEGER PRIMARY KEY, user_id TEXT, event_type TEXT, payload TEXT, paper_id TEXT, created_at TEXT, source TEXT)"
                )

                def insert(event_id, payload, occurred_at=NOW):
                    conn.execute(
                        "INSERT INTO user_events VALUES (?, 'user', ?, ?, NULL, ?, 'app')",
                        (
                            event_id,
                            EventType.QUERY_SUBMIT.value,
                            payload,
                            occurred_at.isoformat(),
                        ),
                    )

                current = json.dumps(
                    {"terms": ["current_private"], "account_incarnation": "B"}
                )
                old = json.dumps({"terms": ["old_private"], "account_incarnation": "A"})
                legacy = json.dumps({"terms": ["legacy_private"]})
                insert(1, current, cutoff)
                insert(2, old)  # A's delayed request completes after B exists.
                insert(3, legacy, cutoff)
                insert(4, legacy, cutoff + timedelta(seconds=1))
                insert(5, old, cutoff - timedelta(seconds=1))
                insert(6, legacy, NOW - timedelta(days=91))
                insert(7, '{"terms":["empty_claim"],"account_incarnation":""}', cutoff)
                insert(8, '{"terms":["wrong_type"],"account_incarnation":7}', cutoff)
                insert(9, '{"terms":["null_claim"],"account_incarnation":null}', cutoff)
                for number in range(10, 1210):
                    insert(number, (old, legacy, "{broken json", "[]")[number % 4])
            new_account = load_user_event_signals(
                path, "user", now=NOW, account_incarnation="B"
            )
            self.assertEqual(new_account.status, "ok")
            self.assertEqual([signal.event_id for signal in new_account.signals], ["1"])
            original = load_user_event_signals(
                path, "user", now=NOW, account_incarnation="B", legacy_before=cutoff
            )
            self.assertEqual(original.status, "ok")
            self.assertEqual(
                [signal.event_id for signal in original.signals], ["9", "3", "1"]
            )
            self.assertNotIn("old_private", repr(original.signals))
            self.assertEqual(
                load_user_event_signals(
                    path, "user", now=NOW, account_incarnation="C"
                ).signals,
                (),
            )

    def test_loader_requires_nonempty_principal_and_aware_legacy_cutoff(self):
        with self.assertRaises(TypeError):
            load_user_event_signals(None, "user", now=NOW)
        for invalid in ("", " ", None, 1):
            with self.assertRaises(ValueError):
                load_user_event_signals(
                    None, "user", now=NOW, account_incarnation=invalid
                )
        with self.assertRaises(ValueError):
            load_user_event_signals(
                None,
                "user",
                now=NOW,
                account_incarnation="B",
                legacy_before=NOW.replace(tzinfo=None),
            )

    def test_duplicate_permutation_is_deterministic(self):
        first = self.signal(
            paper_id="doi:10.1/a", terms=("older",), created_at=NOW - timedelta(hours=1)
        )
        second = replace(first, event_id="2", terms=("newer",), created_at=NOW)
        a = build_recommendation_profile(Counter(), [first, second, first], now=NOW)
        b = build_recommendation_profile(Counter(), [second, first, first], now=NOW)
        self.assertEqual(a, b)
        self.assertEqual(a.positive_terms["older"], 0)
        self.assertGreater(a.positive_terms["newer"], 0)


if __name__ == "__main__":
    unittest.main()
