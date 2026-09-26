"""Best-effort local outcome association, not causal or complete-capture evidence."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.recommendation_candidates import normalize_candidate
from src.recommendation_state import RecommendationState, RecommendationStateError
from src.storage.user_db import AccountLifecycleError, UserDB

_IDENTITY_FIELDS = (
    "title",
    "authors",
    "year",
    "publication_date",
    "doi",
    "arxiv_id",
    "openalex_id",
    "semantic_scholar_id",
    "pmid",
    "url",
    "pdf_url",
)


def _utc(value: datetime | None) -> datetime:
    value = datetime.now(timezone.utc) if value is None else value
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("timezone_required")
    return value.astimezone(timezone.utc)


def attribute_recommendation_outcome(
    *,
    authority: UserDB,
    events_db: Path,
    username: str,
    account_incarnation: str,
    paper: dict,
    kind: str,
    outcome_id: str,
    now: datetime | None = None,
) -> dict:
    """Call after primary commit, outside any existing account guard.

    Pass captured identity and actual committed bibliographic metadata, not a
    caller's recommendation run/exposure context. Failure never rolls back or
    misreports the already committed primary operation. No payload is logged.
    """
    try:
        timestamp = _utc(now)
        if (
            kind not in {"save", "review_start"}
            or not isinstance(paper, dict)
            or not paper
        ):
            raise ValueError("invalid_outcome")
        if not isinstance(outcome_id, str) or not outcome_id:
            raise ValueError("invalid_outcome")
        # Match the candidate boundary exactly, including provider-ID and
        # metadata fingerprint normalization. Private/nonidentity fields cannot
        # invalidate attribution or introduce a different source/id namespace.
        canonical_key = normalize_candidate(
            {field: paper[field] for field in _IDENTITY_FIELDS if field in paper}
        ).canonical_key
        state = RecommendationState(events_db, authority=authority)
        with authority.account_guard(username, account_incarnation):
            return state.record_outcome(
                account_incarnation,
                canonical_key=canonical_key,
                kind=kind,
                outcome_id=outcome_id,
                now=timestamp,
            )
    except AccountLifecycleError:
        return {
            "status": "not_attributed",
            "reason": "account_unavailable",
            "credited": False,
        }
    except (RecommendationStateError, ValueError, TypeError):
        return {
            "status": "not_attributed",
            "reason": "invalid_outcome",
            "credited": False,
        }
    except Exception:
        # This hook runs after a successful primary commit. In particular, a
        # storage failure must not turn that successful save into a false error.
        return {
            "status": "unavailable",
            "reason": "attribution_unavailable",
            "credited": False,
        }


def observed_outcome_report(
    *,
    authority: UserDB,
    events_db: Path,
    username: str,
    since: datetime,
    until: datetime,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp, start, end = _utc(now), _utc(since), _utc(until)
    if (
        start >= end
        or end > timestamp
        or any(
            value.hour or value.minute or value.second or value.microsecond
            for value in (start, end)
        )
    ):
        raise ValueError("invalid_day_window")
    user = authority.get(username)
    if user is None:
        raise AccountLifecycleError("account_unavailable")
    incarnation = user["account_incarnation"]
    state = RecommendationState(events_db, authority=authority)
    with authority.account_guard(username, incarnation):
        metrics = state.outcome_metrics(
            incarnation, since=start, until=end, now=timestamp
        )
    return {
        "status": "observed",
        "since": start.isoformat(),
        "until": end.isoformat(),
        "as_of": timestamp.isoformat(),
        "metrics": metrics,
        "capture_completeness": "unknown",
        "association": "observed_last_touch_7_days",
        "observed_positive_counts_are_lower_bounds": True,
        "rate_is_population_lower_bound": False,
        "causal_effect_estimated": False,
        "promotion": False,
    }


def _iso(value: str) -> datetime:
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError(
            "An explicit timezone-aware ISO timestamp is required."
        ) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local observed recommendation outcome counts; not a promotion gate."
    )
    parser.add_argument("--users-db", type=Path, required=True)
    parser.add_argument("--events-db", type=Path, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--since", type=_iso, required=True)
    parser.add_argument("--until", type=_iso, required=True)
    parser.add_argument("--now", type=_iso, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        # Never create an empty authority database because of a mistyped path.
        if not args.users_db.is_file() or not args.events_db.is_file():
            raise OSError("store_unavailable")
        for path in (args.users_db, args.events_db):
            if any(
                part.is_symlink()
                for part in (path.absolute(), *path.absolute().parents)
            ):
                raise OSError("unsafe_path")
        # UserDB construction initializes legacy stores. Reporting must never
        # trigger that migration or issue fresh account identities.
        conn = sqlite3.connect(args.users_db.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            markers = dict(
                conn.execute(
                    "SELECT key, value FROM account_store_meta "
                    "WHERE key IN ('lifecycle_initialized', 'policy_store')"
                ).fetchall()
            )
            if markers.get("lifecycle_initialized") != "1" or not markers.get(
                "policy_store"
            ):
                raise ValueError("authority_unprovisioned")
            receipt = json.loads(markers["policy_store"])
            if not isinstance(receipt, dict) or not receipt:
                raise ValueError("authority_unprovisioned")
        finally:
            conn.close()
        report = observed_outcome_report(
            authority=UserDB(args.users_db),
            events_db=args.events_db,
            username=args.username,
            since=args.since,
            until=args.until,
            now=args.now,
        )
    except Exception:
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "reason": "outcome_report_unavailable",
                    "promotion": False,
                }
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
