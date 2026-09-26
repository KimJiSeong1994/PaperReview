"""Run real local CLIs against disposable synthetic data; never qualify a source."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent
PYTHON = str(ROOT / ".venv/bin/python")


def main():
    from src.events.event_bus import EventBus
    from src.recommendation_candidates import (
        TrustedReceiverPolicy,
        make_candidate_snapshot,
        write_candidate_snapshot,
    )
    from src.recommendation_state import RecommendationState
    from src.recommendations_artifacts import load_recommendation_artifact
    from src.storage.user_db import UserDB

    entries = []
    with tempfile.TemporaryDirectory(prefix="recommendation-cli-qa-") as temporary:
        data = Path(temporary).resolve()
        env = {
            **os.environ,
            "DATA_DIR": str(data),
            "EVENTS_DB_PATH": str(data / "events.db"),
            "PROFILE_DB_PATH": str(data / "profile.db"),
            "FEATURE_FLAGS_DB_PATH": str(data / "feature_flags.db"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "OPENAI_API_KEY": "sk-fixture-not-used",
        }

        def invoke(label, arguments, expected):
            command = [PYTHON, *arguments]
            started_at = datetime.now(timezone.utc).isoformat()
            completed = subprocess.run(
                command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60
            )
            completed_at = datetime.now(timezone.utc).isoformat()
            (OUT / f"cli-{label}.stdout").write_text(completed.stdout)
            (OUT / f"cli-{label}.stderr").write_text(completed.stderr)
            entries.append(
                {
                    "label": label,
                    "startedAt": started_at,
                    "completedAt": completed_at,
                    "command": command,
                    "cwd": str(ROOT),
                    "exitCode": completed.returncode,
                    "expectedExitCode": expected,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            )
            assert completed.returncode == expected, (
                label,
                completed.returncode,
                completed.stderr,
            )
            return json.loads(completed.stdout)

        evaluation = [
            "scripts/evaluate_daily_recommendations.py",
            "--manifest",
            "data/recommendation_eval/public_fixture_manifest.json",
            "--offline",
        ]
        invoke("validate", [*evaluation, "--validate-only"], 0)
        evaluated = invoke("evaluate", evaluation, 3)
        (OUT / "synthetic-evaluation.json").write_text(
            json.dumps(evaluated, ensure_ascii=False, indent=2)
        )
        now = datetime.now(timezone.utc).replace(microsecond=0)
        run_at = now.isoformat()
        invoke(
            "disabled-collector",
            [
                "scripts/collect_related_papers_for_wiki.py",
                "--candidate-root",
                str(data / "disabled-candidates"),
                "--final-root",
                str(data / "deliveries"),
                "--run-at",
                run_at,
            ],
            0,
        )
        users = UserDB(data / "users.db")
        account = users.create_account(
            "fixture-user", {"role": "user", "password_hash": "not-a-login-password"}
        )
        EventBus(data / "events.db", account_authority=users).close()
        RecommendationState.initialize(data / "events.db", authority=users)
        papers = [
            {
                "title": f"Synthetic bibliographic fixture {number:02d}",
                "authors": ["Fixture Author"],
                "doi": f"10.9999/qa.{number:02d}",
                "year": now.year,
                "publication_date": f"{now.year}-01-01",
                "url": f"https://example.org/fixture/{number}",
            }
            for number in range(1, 15)
        ]
        snapshot = make_candidate_snapshot(
            papers,
            policy=TrustedReceiverPolicy(
                "local_public",
                "public",
                "public-seeds-v1",
                public_source_qualified=True,
            ),
            source_run_id="synthetic-cli-fixture",
            collected_at=now,
            now=now,
        )
        write_candidate_snapshot(
            snapshot, root=data / "candidates", final_root=data / "deliveries"
        )
        arguments = [
            "scripts/generate_daily_recommendations.py",
            "--candidate-root",
            str(data / "candidates"),
            "--users-db",
            str(data / "users.db"),
            "--events-db",
            str(data / "events.db"),
            "--bookmarks-db",
            str(data / "bookmarks.db"),
            "--artifacts-dir",
            str(data / "deliveries"),
            "--run-at",
            run_at,
            "--limit",
            "12",
            "--min-score",
            "0",
        ]
        generated = invoke("generate", arguments, 0)
        assert (
            generated["publish_success"] == 1
            and generated["provider_calls"] == 0
            and generated["paid_calls"] == 0
        )
        reused = invoke("reuse", arguments, 0)
        assert reused["reused"] == 1
        state = RecommendationState(data / "events.db", authority=users)
        incarnation = account["account_incarnation"]
        before = load_recommendation_artifact(
            data / "deliveries",
            incarnation,
            5,
            policy=state.policy(incarnation, now=now),
            now=now,
        )
        assert len(before["items"]) == 5
        hidden = before["items"][0]["canonical_key"]
        with users.account_guard("fixture-user", incarnation):
            state.record_exposure(
                incarnation,
                run_id=before["run_id"],
                canonical_key=hidden,
                visible_fraction=1,
                visible_ms=1500,
                now=now,
            )
            # Explicit synthetic state seed for the metrics CLI; actual producer
            # attribution is separately exercised through real browser/API calls.
            seeded = state.record_outcome(
                incarnation,
                canonical_key=hidden,
                kind="save",
                outcome_id="synthetic-cli-save",
                now=now,
            )
        assert seeded["credited"]
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        measured = invoke(
            "observed-outcomes",
            [
                "-m",
                "src.recommendation_attribution",
                "--users-db",
                str(data / "users.db"),
                "--events-db",
                str(data / "events.db"),
                "--username",
                "fixture-user",
                "--since",
                day_start.isoformat(),
                "--until",
                (day_start + timedelta(days=1)).isoformat(),
                "--now",
                (day_start + timedelta(days=9)).isoformat(),
            ],
            0,
        )
        assert measured["metrics"]["mature"]["visible_userdays"] == 1
        assert measured["metrics"]["mature"]["positive_userdays"] == 1
        state.apply_action(
            incarnation,
            run_id=before["run_id"],
            canonical_key=hidden,
            action="hide",
            request_id="cli-hide",
            now=now,
        )
        after = load_recommendation_artifact(
            data / "deliveries",
            incarnation,
            5,
            policy=state.policy(incarnation, now=now),
            now=now,
        )
        assert len(after["items"]) == 5 and hidden not in [
            item["canonical_key"] for item in after["items"]
        ]
        assert after["items"][0]["final_rank"] == before["items"][1]["final_rank"]
        projection = {"before": before, "afterHide": after}
    transcript = {
        "schemaVersion": 1,
        "kind": "app-automation-transcript",
        "tool": "python-subprocess",
        "actions": [
            {
                "type": "subprocess-invocation",
                "timestamp": entry["completedAt"],
                "selector": entry["command"][0],
                "selectorMeaning": "Actual executable path passed to subprocess.run, not a DOM selector",
                "argv": entry["command"],
                "verdict": "passed",
                **entry,
            }
            for entry in entries
        ],
        "fixtureOnly": True,
        "qualification": "Synthetic isolated software execution; no provider, production data, or quality-gain evidence",
        "commands": entries,
        "projection": projection,
    }
    (OUT / "cli-transcript.json").write_text(
        json.dumps(transcript, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {
                "actual_cli_exits": [entry["exitCode"] for entry in entries],
                "top5_refill": True,
                "fixture_only": True,
            }
        )
    )


if __name__ == "__main__":
    main()
