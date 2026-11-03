"""Admin stats for the conversational product: conversations, souls, LLM usage.

  GET /api/admin/conversations/stats?days=7|28|90
  GET /api/admin/souls/stats?days=7|28|90
  GET /api/admin/llm-usage?days=7|28|90

Privacy invariant: responses carry counts, ratios, timestamps and fixed enum
values (intent, kind, mode, stage, model) only — never conversation titles or
text, blocks, memory text, USER.md, profile values or session ids.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from app.assistant.profile import PROFILE_MAX_AGE
from routers.deps import storage
from routers.deps.auth import get_admin_user
from routers.deps.storage import _get_conversation_db, _get_soul_db, load_users
from src.utils import llm_usage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

_ALLOWED_WINDOWS = (7, 28, 90)  # same as routers/admin_analytics.py
KST = dt.timezone(dt.timedelta(hours=9))
_INTENT_ORDER = ("chat", "clarify", "search", "answer", "review", "open_pdf", "highlight_pdf", "answer_from_bookmarks")
_SESSION_ID = re.compile(r"review_\d{8}_\d{6}_[0-9a-f]{8}")
_CLAIM_STATUSES = ("verified", "partially_verified", "unverified", "contradicted")
_UNRECORDED_STAGES = ["claim_verification"]


def _window(days: int) -> Tuple[Dict[str, Any], List[str]]:
    """Window covering *days* KST calendar days including today, plus those dates (oldest first)."""
    if days not in _ALLOWED_WINDOWS:
        raise HTTPException(status_code=400, detail="days must be one of 7, 28, 90")
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(KST).date()
    start = dt.datetime.combine(today - dt.timedelta(days=days - 1), dt.time(), KST).astimezone(dt.timezone.utc)
    dates = [(today - dt.timedelta(days=days - 1 - i)).isoformat() for i in range(days)]
    return {"days": days, "start": start.isoformat(), "end": now.isoformat(), "timezone": "Asia/Seoul"}, dates


def _nearest_rank(sorted_values: List[int], pct: float) -> int:
    return sorted_values[max(math.ceil(pct * len(sorted_values)), 1) - 1]


def _intent_key(intent: str) -> Tuple[int, str]:
    return (_INTENT_ORDER.index(intent), "") if intent in _INTENT_ORDER else (len(_INTENT_ORDER), intent)


def _review_outcome(session_id: Optional[str], mode: Optional[str]) -> Tuple[str, Optional[Counter]]:
    """('completed'|'failed'|'running'|'unknown', claim status Counter or None).

    *session_id* comes from stored blocks (data), so it must fullmatch the
    generated id format before it is joined into a workspace path.
    """
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        return "unknown", None
    session_dir = Path(storage.WORKSPACE_DIR) / session_id
    outcome = "unknown"
    try:
        meta = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
        if isinstance(meta, dict) and meta.get("status") == "completed":
            outcome = "completed"
    except (OSError, ValueError):
        pass
    if outcome == "unknown":
        with storage.review_sessions_lock:
            status = (storage.review_sessions.get(session_id) or {}).get("status")
        if status == "completed":
            outcome = "completed"
        elif status in ("failed", "error", "cancelled"):
            outcome = "failed"
        elif status is not None:
            outcome = "running"
    if mode != "full":
        return outcome, None
    claim_files = sorted((session_dir / "verifications").glob("claims_*.json"), key=lambda p: p.stat().st_mtime)
    if not claim_files:
        return outcome, None
    try:
        claims = json.loads(claim_files[-1].read_text(encoding="utf-8")).get("claims") or []
        return outcome, Counter(c.get("verification_status") for c in claims if isinstance(c, dict))
    except (OSError, ValueError, AttributeError):
        logger.warning("admin stats: unreadable claims file for session %s", session_id[:15])
        return outcome, None


def _activation(since: str) -> Dict[str, int]:
    """Accounts created in the window, and how many started a conversation within 24h."""
    firsts = _get_conversation_db().first_conversation_by_owner()
    signups = activated = 0
    for username, data in load_users().items():
        created = data.get("created_at") or ""
        if created < since:
            continue
        signups += 1
        first = firsts.get((username, data.get("account_incarnation")))
        try:
            if first and dt.datetime.fromisoformat(first) - dt.datetime.fromisoformat(created) <= dt.timedelta(hours=24):
                activated += 1
        except (ValueError, TypeError):  # TypeError: legacy naive created_at vs aware first-conversation time
            continue
    return {"signups": signups, "first_conversation_within_24h": activated}


def _conversation_stats(days: int) -> Dict[str, Any]:
    window, dates = _window(days)
    since = window["start"]
    db = _get_conversation_db()
    raw = db.admin_turn_stats(since)

    outcomes = Counter({"done": 0, "failed": 0, "cancelled": 0, "interrupted": 0, "running": 0})
    per_intent: Dict[str, Counter] = defaultdict(Counter)
    for intent, outcome, n in raw["outcomes"]:
        outcomes[outcome] += n
        if intent:
            per_intent[intent][outcome] += n
    denominator = outcomes["done"] + outcomes["failed"] + outcomes["interrupted"]
    error_rate = round((outcomes["failed"] + outcomes["interrupted"]) / denominator, 3) if denominator else None

    latencies: Dict[str, List[int]] = defaultdict(list)
    for intent, ms in raw["latencies"]:
        latencies[intent].append(ms)
    latency = []
    for intent in sorted(latencies, key=_intent_key):
        values = sorted(latencies[intent])
        latency.append({
            "intent": intent,
            "samples": len(values),
            "p50_ms": _nearest_rank(values, 0.5),
            "p95_ms": _nearest_rank(values, 0.95) if len(values) >= 5 else None,
        })
    intents = [
        {"intent": intent, "turns": sum(c.values()), "failed": c["failed"], "interrupted": c["interrupted"]}
        for intent, c in sorted(per_intent.items(), key=lambda kv: _intent_key(kv[0]))
    ]

    by_mode = Counter({"fast": 0, "full": 0})
    review_outcomes = Counter({"completed": 0, "failed": 0, "running": 0, "unknown": 0})
    claims = Counter()
    sessions_with_claims = mode_missing = 0
    starts = db.review_starts_since(since)
    for start in starts:
        mode = start.get("mode")
        if mode not in ("fast", "full"):
            mode_missing += 1
            mode = "fast"  # blocks written before review_mode existed
        by_mode[mode] += 1
        outcome, claim_counts = _review_outcome(start.get("session_id"), mode)
        review_outcomes[outcome] += 1
        if claim_counts:
            sessions_with_claims += 1
            claims.update(claim_counts)
    total_claims = sum(claims.values())

    by_date = {row["date"]: row for row in raw["daily"]}
    daily = [
        {k: (by_date.get(d) or {}).get(k) or 0 for k in ("conversations", "user_turns", "active_users", "failed")}
        | {"date": d}
        for d in dates
    ]
    return {
        "window": window,
        "totals": {
            "conversations": raw["conversations"],
            "user_turns": raw["user_turns"],
            "assistant_turns": sum(outcomes.values()),
            "active_users": raw["active_users"],
            "running": outcomes["running"],
        },
        "outcomes": {k: outcomes[k] for k in ("done", "failed", "cancelled", "interrupted")},
        "error_rate": error_rate,
        "latency": latency,
        "intents": intents,
        "reviews": {
            "started": len(starts),
            "by_mode": dict(by_mode),
            "mode_missing": mode_missing,
            "outcomes": dict(review_outcomes),
            "verification": {
                "sessions_with_claims": sessions_with_claims,
                "claims": total_claims,
                **{s: claims[s] for s in _CLAIM_STATUSES},
                "verified_ratio": round(claims["verified"] / total_claims, 3) if total_claims else None,
            },
        },
        "activation": _activation(since),
        "daily": daily,
        "metric_definitions": {
            "outcomes": {
                "failed": "error with latency",
                "cancelled": "superseded by a new user message",
                "interrupted": "running at server restart",
            },
            "error_rate": {"numerator": "failed+interrupted", "denominator": "done+failed+interrupted"},
            "latency": {
                "population": "assistant turns status=done",
                "percentile": "nearest-rank; p95 null below 5 samples",
                "note": "review = time to start the background review, not review duration",
            },
            "intents": {"population": "assistant turns with an intent (cancelled/interrupted turns have none)"},
            "reviews": {
                "population": "reviews started from conversations only",
                "mode_missing": "blocks written before review_mode existed, counted as fast",
                "unknown": "no completed metadata and not in memory (failures are not persisted)",
            },
            "verification": {"population": "full-mode reviews with a claims file (latest file per review)"},
            "activation": {"population": "accounts created in window", "rule": "first conversation within 24h of created_at"},
            "daily": {"conversations": "conversations with a user message that KST day", "failed": "failed+interrupted"},
        },
    }


def _soul_stats(days: int) -> Dict[str, Any]:
    window, _ = _window(days)
    stale_before = (dt.datetime.now(dt.timezone.utc) - PROFILE_MAX_AGE).isoformat()
    stats = _get_soul_db().admin_stats(window["start"], stale_before)
    return {
        "window": window,
        **stats,
        "metric_definitions": {
            "with_soul": "accounts with USER.md or any memory",
            "new_in_window": "memories created in the window",
            "stale_over_24h": "updated_at older than PROFILE_MAX_AGE; rebuilt lazily on next use",
            "privacy": "counts only; no memory text, USER.md or profile fields are returned",
        },
    }


def _llm_usage(days: int) -> Dict[str, Any]:
    window, dates = _window(days)
    since_ts = dt.datetime.fromisoformat(window["start"]).timestamp()
    path = Path(llm_usage.LEDGER_PATH)
    result: Dict[str, Any] = {
        "available": path.is_file(),
        "window": window,
        "ledger": {"first_at": None, "last_at": None, "malformed_lines": 0},
        "totals": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0},
        "by_stage": [],
        "daily": [{"date": d, "prompt_tokens": 0, "completion_tokens": 0} for d in dates],
        "coverage": {"unrecorded_stages": _UNRECORDED_STAGES},
        "metric_definitions": {
            "unit": "tokens",
            "cost": "not converted to currency",
            "attribution": "none (not per user or conversation)",
            "ledger_path": str(path),
        },
    }
    if not result["available"]:
        result["reason"] = "ledger not found"
        return result

    def _int(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    first = last = None
    totals = result["totals"]
    stages: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
    daily = {row["date"]: row for row in result["daily"]}
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                ts = row["ts"]
            except (ValueError, KeyError, TypeError):
                result["ledger"]["malformed_lines"] += 1
                continue
            if not isinstance(ts, (int, float)) or isinstance(ts, bool):
                continue
            first = ts if first is None else min(first, ts)
            last = ts if last is None else max(last, ts)
            if ts < since_ts:
                continue
            prompt, completion = _int(row.get("prompt_tokens")), _int(row.get("completion_tokens"))
            totals["calls"] += 1
            totals["prompt_tokens"] += prompt
            totals["completion_tokens"] += completion
            totals["cached_tokens"] += _int(row.get("cached_tokens"))
            stage = stages[(str(row.get("stage") or "unknown"), str(row.get("model") or "unknown"))]
            stage.update(calls=1, prompt_tokens=prompt, completion_tokens=completion)
            date = dt.datetime.fromtimestamp(ts, KST).date().isoformat()
            if date in daily:
                daily[date]["prompt_tokens"] += prompt
                daily[date]["completion_tokens"] += completion

    def _iso(ts: Optional[float]) -> Optional[str]:
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat() if ts is not None else None

    result["ledger"].update(first_at=_iso(first), last_at=_iso(last))
    result["by_stage"] = sorted(
        (
            {"stage": stage, "model": model, "calls": c["calls"], "prompt_tokens": c["prompt_tokens"],
             "completion_tokens": c["completion_tokens"]}
            for (stage, model), c in stages.items()
        ),
        key=lambda r: (-(r["prompt_tokens"] + r["completion_tokens"]), r["stage"], r["model"]),
    )
    return result


@router.get("/conversations/stats")
async def admin_conversation_stats(
    days: int = Query(7, description="Window size in KST days: 7, 28, or 90"),
    admin: str = Depends(get_admin_user),
) -> dict:
    """Conversation volume, outcomes, per-intent latency, review modes and verification."""
    return await asyncio.to_thread(_conversation_stats, days)


@router.get("/souls/stats")
async def admin_soul_stats(
    days: int = Query(7, description="Window size in KST days: 7, 28, or 90"),
    admin: str = Depends(get_admin_user),
) -> dict:
    """Memory and research-profile accumulation (counts only)."""
    return await asyncio.to_thread(_soul_stats, days)


@router.get("/llm-usage")
async def admin_llm_usage(
    days: int = Query(7, description="Window size in KST days: 7, 28, or 90"),
    admin: str = Depends(get_admin_user),
) -> dict:
    """Token totals from the append-only LLM usage ledger, by stage×model and KST day."""
    return await asyncio.to_thread(_llm_usage, days)
