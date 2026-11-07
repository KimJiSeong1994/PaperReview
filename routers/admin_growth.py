"""Account growth from retained user messages; no browser/account identity joins."""

from __future__ import annotations

import asyncio
import datetime as dt
from collections import defaultdict

from fastapi import APIRouter, Depends, Query

from routers.admin_assistant import KST, _window
from routers.deps.auth import get_admin_user
from routers.deps.storage import _get_conversation_db, load_users

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _timestamp(value: str | None) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value or "")
        return parsed.astimezone(dt.timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _growth_stats(days: int) -> dict:
    window, dates = _window(days)
    start, end = (_timestamp(window[key]) for key in ("start", "end"))
    assert start is not None and end is not None
    today = end.astimezone(KST).date()
    accounts = {
        (name, data.get("account_incarnation")): data
        for name, data in load_users().items() if data.get("role") != "admin"
    }
    activity: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for row in _get_conversation_db().user_activity_days(window["end"]):
        owner = (row["username"], row["account_incarnation"])
        if owner in accounts and row["date"]:
            activity[owner][row["date"]] = row

    daily = {day: {"date": day, "active_users": 0, "new_users": 0, "returning_users": 0,
                   "user_messages": 0} for day in dates}
    totals = dict(active_users=0, new_users=0, returning_users=0, repeat_users=0, user_messages=0)
    first_days = {}
    first_times = {}
    for owner, history in activity.items():
        first_day = min(history)
        first_days[owner] = dt.date.fromisoformat(first_day)
        # SQLite julianday preserves offsets; the 1970 epoch is JD 2440587.5.
        first_times[owner] = dt.datetime.fromtimestamp(
            (min(row["first_jd"] for row in history.values()) - 2440587.5) * 86400,
            dt.timezone.utc,
        )
        observed = sorted(set(history) & daily.keys())
        if not observed:
            continue
        totals["active_users"] += 1
        totals["new_users" if first_day >= dates[0] else "returning_users"] += 1
        totals["repeat_users"] += len(observed) >= 2
        for day in observed:
            daily[day]["active_users"] += 1
            daily[day]["new_users" if day == first_day else "returning_users"] += 1
            daily[day]["user_messages"] += history[day]["messages"]
            totals["user_messages"] += history[day]["messages"]

    activation = dict(signups=0, eligible=0, activated=0, pending=0, pending_activated=0)
    unknown_signup_dates = 0
    for owner, account in accounts.items():
        created = _timestamp(account.get("created_at"))
        if created is None:
            unknown_signup_dates += 1
            continue
        if not start <= created <= end:
            continue
        activation["signups"] += 1
        first = first_times.get(owner)
        # Match SQLite's timestamp precision when comparing the 24h boundary.
        elapsed = round((first - created).total_seconds(), 3) if first else None
        activated = elapsed is not None and 0 <= elapsed <= 86400
        if created + dt.timedelta(hours=24) <= end:
            activation["eligible"] += 1
            activation["activated"] += activated
        else:
            activation["pending"] += 1
            activation["pending_activated"] += activated
    activation["rate"] = _ratio(activation["activated"], activation["eligible"])

    retention = []
    for lag in (1, 7):
        eligible = returned = pending = 0
        for owner, first_day in first_days.items():
            if not dates[0] <= first_day.isoformat() <= dates[-1]:
                continue
            target = first_day + dt.timedelta(days=lag)
            if target >= today:
                pending += 1
                continue
            eligible += 1
            returned += target.isoformat() in activity[owner]
        retention.append({"day": lag, "eligible": eligible, "returned": returned,
                          "pending": pending, "rate": _ratio(returned, eligible)})

    return {
        "window": window, "totals": totals, "activation": activation,
        "retention": retention, "daily": list(daily.values()),
        "measurement": {
            "population": "current_non_admin_accounts",
            "activity": "persisted_user_message",
            "history": "retained_messages_only",
            "first_activity_date": min((d.isoformat() for d in first_days.values()), default=None),
            "unknown_signup_dates": unknown_signup_dates,
        },
        "metric_definitions": {
            "active_users": "distinct current non-admin account incarnations with a user message in window",
            "new_users": "first retained user message falls in window",
            "returning_users": "active in window and first retained user message predates window",
            "repeat_users": "user messages on at least two distinct KST days in window",
            "activation": "signups in window aged at least 24h; first user message within [0,24h]",
            "retention": "first retained message in window; message on exact KST D1/D7; target day must have ended",
            "coverage": "deleted accounts/messages excluded; retained history cannot establish lifetime first use",
        },
    }


@router.get("/growth/stats")
async def admin_growth_stats(
    days: int = Query(7, description="Window size in KST days: 7, 28, or 90"),
    admin: str = Depends(get_admin_user),
) -> dict:
    return await asyncio.to_thread(_growth_stats, days)
