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

# Search/answer-engine indexing crawlers (not user-triggered fetches). The set
# of pages these fetch is a live "what is being indexed" GEO coverage list.
_INDEXING_BOTS = {
    "GPTBot",
    "OAI-SearchBot",
    "ClaudeBot",
    "Claude-SearchBot",
    "PerplexityBot",
    "Googlebot",
    "Bingbot",
    "Yeti(Naver)",
    "Applebot",
}

_AI_REFERRER_RE = re.compile(
    r"chatgpt\.com|perplexity\.ai|claude\.ai|anthropic\.com|gemini\.google|"
    r"copilot\.microsoft|you\.com|deepseek\.com",
    re.IGNORECASE,
)

# Real external referrer hosts (search + social). Self-navigation, AI-engine
# referrers, and infra noise are excluded — the AI referrers are counted
# separately as citation traffic. Raw-IP and cloud-host referrers (e.g. the
# server's own EC2 address hitting itself, health checks, scanners) dominate
# the log and are not real acquisition channels, so they are dropped.
_SELF_HOST_RE = re.compile(r"://(www\.)?jiphyeonjeon\.kr", re.IGNORECASE)
_REFERRER_HOST_RE = re.compile(r"^https?://([^/]+)", re.IGNORECASE)
_INFRA_HOST_RE = re.compile(
    r"^(\d{1,3}\.){3}\d{1,3}$"  # bare IPv4
    r"|amazonaws\.com$|compute\.internal$|\.local$|^localhost$",
    re.IGNORECASE,
)
_CHANNEL_HOSTS = {
    "www.google.com": "Google",
    "google.com": "Google",
    "com.google.android.googlequicksearchbox": "Google",
    "duckduckgo.com": "DuckDuckGo",
    "www.bing.com": "Bing",
    "bing.com": "Bing",
    "search.naver.com": "Naver",
    "news.ycombinator.com": "Hacker News",
    "www.reddit.com": "Reddit",
    "out.reddit.com": "Reddit",
    "github.com": "GitHub",
    "www.linkedin.com": "LinkedIn",
    "lnkd.in": "LinkedIn",
    "t.co": "X (Twitter)",
    "www.facebook.com": "Facebook",
    "l.facebook.com": "Facebook",
    "m.facebook.com": "Facebook",
}


def _channel_for(referer: str) -> str | None:
    """Map a referer URL to a named external channel, else None."""
    if not referer or referer == "-" or _SELF_HOST_RE.search(referer):
        return None
    if _AI_REFERRER_RE.search(referer):
        return None
    host_match = _REFERRER_HOST_RE.match(referer)
    if not host_match:
        return None
    host = host_match.group(1).lower().split(":", 1)[0]
    if _INFRA_HOST_RE.search(host):
        return None
    if host in _CHANNEL_HOSTS:
        return _CHANNEL_HOSTS[host]
    # Unknown external host — surface the bare host so nothing is silently lost.
    return host

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
    crawled_pages: dict[str, int] = {}
    channels: dict[str, int] = {}

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
            channel = _channel_for(referer) if bot_name is None else None
            if bot_name is None and not is_ai_ref and channel is None:
                continue

            try:
                ts = dt.datetime.strptime(m.group("time"), _LOG_TIME_FORMAT)
            except ValueError:
                continue
            if ts < cutoff:
                continue

            path = m.group("path").split("?", 1)[0]

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
                    citation_paths[path] = citation_paths.get(path, 0) + 1
                elif bot_name in _INDEXING_BOTS and status < 400 and path.startswith("/blog"):
                    crawled_pages[path] = crawled_pages.get(path, 0) + 1

            if bot_name is None and is_ai_ref:
                ai_referral_hits += 1
                host = _AI_REFERRER_RE.search(referer).group(0).lower()
                ai_referral_sources[host] = ai_referral_sources.get(host, 0) + 1
            elif bot_name is None and channel is not None:
                channels[channel] = channels.get(channel, 0) + 1
    except (OSError, PermissionError) as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    def _rank(counts: dict[str, int], key: str) -> list[dict[str, Any]]:
        return sorted(
            ({key: k, "hits": n} for k, n in counts.items()),
            key=lambda r: -r["hits"],
        )[:top_limit]

    report = {
        "available": True,
        "bots": sorted(bot_hits.values(), key=lambda b: -b["hits"]),
        "citation_clicks": citation_clicks,
        "citation_paths": _rank(citation_paths, "path"),
        "ai_referral_hits": ai_referral_hits,
        "ai_referral_sources": _rank(ai_referral_sources, "source"),
        "crawled_pages": _rank(crawled_pages, "path"),
        "channels": _rank(channels, "channel"),
    }
    if now is None:
        _cache[days] = (time.monotonic(), report)
    return report
