"""AI-crawler statistics parsed from nginx access logs.

nginx (the TLS edge) logs every request in the default ``combined`` format,
which is the only place bot traffic is observable — AI crawlers do not run
the SPA, so they never reach first-party analytics. Reading the logs needs
the app user in the ``adm`` group; when the files are unreadable the report
degrades to ``{"available": False}`` instead of failing the dashboard.

Results are cached for ten minutes: the parse walks up to ~10MB of gzipped
history and the dashboard may be refreshed repeatedly.
"""

from __future__ import annotations

import datetime as dt
import gzip
import os
import re
import time
from pathlib import Path
from typing import Any

# Mirrors middleware._AI_BOT_RE; keep the two lists in sync. Ordered so the
# most specific token wins (Claude-User before ClaudeBot would not matter —
# regex alternation is fine because tokens do not prefix each other).
_BOT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in [
        ("GPTBot", r"GPTBot"),
        ("OAI-SearchBot", r"OAI-SearchBot"),
        ("ChatGPT-User", r"ChatGPT-User"),
        ("Claude-SearchBot", r"Claude-SearchBot"),
        ("Claude-User", r"Claude-User"),
        ("ClaudeBot", r"ClaudeBot|anthropic-ai"),
        ("PerplexityBot", r"PerplexityBot"),
        ("Perplexity-User", r"Perplexity-User"),
        ("Googlebot", r"Googlebot|Google-Extended"),
        ("Bingbot", r"Bingbot"),
        ("Yeti(Naver)", r"Yeti"),
        ("Applebot", r"Applebot"),
        ("Bytespider", r"Bytespider"),
        ("CCBot", r"CCBot"),
        ("Amazonbot", r"Amazonbot"),
    ]
]

# Fetches a human triggered from inside an AI assistant — the closest thing
# to a "citation click" that is directly measurable.
_USER_FETCH_BOTS = {"ChatGPT-User", "Claude-User", "Perplexity-User"}

_AI_REFERRER_RE = re.compile(
    r"chatgpt\.com|perplexity\.ai|claude\.ai|anthropic\.com|gemini\.google|"
    r"copilot\.microsoft|you\.com|deepseek\.com",
    re.IGNORECASE,
)

# 127.0.0.1 - - [11/Jul/2026:13:04:03 +0000] "GET /x HTTP/1.1" 200 123 "ref" "ua"
_LOG_LINE_RE = re.compile(
    r'^\S+ \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+)[^"]*" '
    r'(?P<status>\d{3}) \S+ "(?P<referer>[^"]*)" "(?P<ua>[^"]*)"'
)

_LOG_TIME_FORMAT = "%d/%b/%Y:%H:%M:%S %z"

_CACHE_TTL_SECONDS = 600
_cache: dict[int, tuple[float, dict[str, Any]]] = {}


def _log_dir() -> Path:
    return Path(os.getenv("NGINX_ACCESS_LOG_DIR", "/var/log/nginx"))


def _iter_log_lines(log_dir: Path):
    """Yield lines from access.log, access.log.1 and rotated .gz files."""
    candidates = sorted(
        log_dir.glob("access.log*"),
        key=lambda p: p.name,
    )
    for path in candidates:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
            yield from fh


def build_crawler_report(
    *,
    days: int,
    top_limit: int = 10,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Summarize AI/search crawler traffic from nginx logs for the window."""
    cached = _cache.get(days)
    if cached and now is None and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    cutoff = (now or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(days=days)
    log_dir = _log_dir()

    bot_hits: dict[str, dict[str, Any]] = {}
    citation_clicks = 0
    citation_paths: dict[str, int] = {}
    ai_referral_hits = 0
    ai_referral_sources: dict[str, int] = {}

    try:
        for line in _iter_log_lines(log_dir):
            m = _LOG_LINE_RE.match(line)
            if not m:
                continue
            ua = m.group("ua")
            referer = m.group("referer")

            bot_name = None
            for name, pattern in _BOT_PATTERNS:
                if pattern.search(ua):
                    bot_name = name
                    break
            is_ai_ref = bool(_AI_REFERRER_RE.search(referer))
            if bot_name is None and not is_ai_ref:
                continue

            try:
                ts = dt.datetime.strptime(m.group("time"), _LOG_TIME_FORMAT)
            except ValueError:
                continue
            if ts < cutoff:
                continue

            if bot_name is not None:
                entry = bot_hits.setdefault(
                    bot_name, {"bot": bot_name, "hits": 0, "ok": 0, "errors": 0}
                )
                entry["hits"] += 1
                status = int(m.group("status"))
                if status < 400:
                    entry["ok"] += 1
                else:
                    entry["errors"] += 1
                if bot_name in _USER_FETCH_BOTS:
                    citation_clicks += 1
                    path = m.group("path").split("?", 1)[0]
                    citation_paths[path] = citation_paths.get(path, 0) + 1

            if is_ai_ref and bot_name is None:
                ai_referral_hits += 1
                host = _AI_REFERRER_RE.search(referer).group(0).lower()
                ai_referral_sources[host] = ai_referral_sources.get(host, 0) + 1
    except (OSError, PermissionError) as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    report = {
        "available": True,
        "bots": sorted(bot_hits.values(), key=lambda b: -b["hits"]),
        "citation_clicks": citation_clicks,
        "citation_paths": sorted(
            ({"path": p, "hits": n} for p, n in citation_paths.items()),
            key=lambda r: -r["hits"],
        )[:top_limit],
        "ai_referral_hits": ai_referral_hits,
        "ai_referral_sources": sorted(
            ({"source": s, "hits": n} for s, n in ai_referral_sources.items()),
            key=lambda r: -r["hits"],
        )[:top_limit],
    }
    if now is None:
        _cache[days] = (time.monotonic(), report)
    return report
