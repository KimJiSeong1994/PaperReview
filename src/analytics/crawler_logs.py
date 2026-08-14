"""Crawler statistics parsed from nginx access logs.

User-agent strings are claims, not identities.  This module therefore keeps
raw UA-labelled traffic for operational visibility while separately reporting
requests whose source IP belongs to a provider's published crawler ranges.
Unknown-path vulnerability probes and sources that rotate through several bot
identities are kept out of indexing-health and answer-fetch metrics.

Results are cached for ten minutes because parsing rotated logs is relatively
expensive.  Published IP ranges are fetched concurrently and cached for a day;
an unavailable verifier degrades to ``unavailable`` rather than treating every
request as genuine or breaking the admin dashboard.
"""

from __future__ import annotations

import datetime as dt
import gzip
import ipaddress
import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping, Sequence

IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

# Mirrors middleware._AI_BOT_RE.  Matching is intentionally still permissive:
# the report must show spoofed claims, but only verified requests contribute to
# trusted indexing metrics below.
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
_BOT_TOKENS = [
    (name, tuple(token.lower() for token in pattern.pattern.split("|")))
    for name, pattern in _BOT_PATTERNS
]

_USER_FETCH_BOTS = {"ChatGPT-User", "Claude-User", "Perplexity-User"}
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
    "Amazonbot",
}

_JSON_VERIFIERS = {
    "GPTBot": "https://openai.com/gptbot.json",
    "OAI-SearchBot": "https://openai.com/searchbot.json",
    "Googlebot": "https://developers.google.com/static/crawling/ipranges/common-crawlers.json",
    "Bingbot": "https://www.bing.com/toolbox/bingbot.json",
    "PerplexityBot": "https://www.perplexity.com/perplexitybot.json",
    "Perplexity-User": "https://www.perplexity.com/perplexity-user.json",
}
_AMAZON_VERIFIER_URL = (
    "https://developer.amazon.com/en/amazonbot/searchbot-ip-addresses"
)

_AI_REFERRER_RE = re.compile(
    r"chatgpt\.com|perplexity\.ai|claude\.ai|anthropic\.com|gemini\.google|"
    r"copilot\.microsoft|you\.com|deepseek\.com",
    re.IGNORECASE,
)
_SELF_HOST_RE = re.compile(r"://(www\.)?jiphyeonjeon\.kr", re.IGNORECASE)
_REFERRER_HOST_RE = re.compile(r"^https?://([^/]+)", re.IGNORECASE)
_INFRA_HOST_RE = re.compile(
    r"^(\d{1,3}\.){3}\d{1,3}$|amazonaws\.com$|compute\.internal$|\.local$|^localhost$",
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

_SCAN_PATH_RE = re.compile(
    r"(?:^|/)(?:@fs|\.env(?:\.|$)|\.aws(?:/|$)|\.ssh(?:/|$)|\.git(?:/|$)|"
    r"\.docker(?:/|$)|\.azure(?:/|$)|\.gcloud(?:/|$)|\.npmrc$|wp-config\.php$|"
    r"terraform\.(?:tfstate|tfvars)$|(?:private[-_]?|root)?key(?:\.|$)|"
    r"credentials?(?:\.|/|$)|secrets?(?:\.|/|$)|serviceaccountkey\.json$)",
    re.IGNORECASE,
)
_SCAN_ENDPOINTS = {
    "/fetch",
    "/proxy",
    "/graphql",
    "/v1/graphql",
    "/webhook",
    "/debug",
    "/request",
    "/api/fetch",
    "/api/proxy",
    "/api/request",
    "/cgi-bin/fetch",
}
_SCAN_QUERY_RE = re.compile(
    r"(?:file://|169\.254\.169\.254|/etc/passwd|/proc/self/environ)", re.IGNORECASE
)

# 127.0.0.1 - - [11/Jul/2026:13:04:03 +0000] "GET /x HTTP/1.1" 200 123 "ref" "ua"
_LOG_LINE_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<path>\S+)[^"]*" '
    r'(?P<status>\d{3}) \S+ "(?P<referer>[^"]*)" "(?P<ua>[^"]*)"'
)
_LOG_TIME_FORMAT = "%d/%b/%Y:%H:%M:%S %z"

_CACHE_TTL_SECONDS = 600
_VERIFIER_CACHE_TTL_SECONDS = 86_400
_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_verifier_cache: tuple[float, dict[str, list[IpNetwork]], list[str]] | None = None


def _channel_for(referer: str) -> str | None:
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
    return _CHANNEL_HOSTS.get(host, host)


def _bot_name_for(ua: str) -> str | None:
    normalized = ua.lower()
    return next(
        (
            name
            for name, tokens in _BOT_TOKENS
            if any(token in normalized for token in tokens)
        ),
        None,
    )


def _log_dir() -> Path:
    return Path(os.getenv("NGINX_ACCESS_LOG_DIR", "/var/log/nginx"))


def _iter_log_lines(log_dir: Path):
    candidates = sorted(log_dir.glob("access.log*"), key=lambda p: p.name)
    for path in candidates:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
            yield from fh


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url, headers={"User-Agent": "jiphyeonjeon-crawler-verifier/1.0"}
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_json_networks(payload: str) -> list[IpNetwork]:
    data = json.loads(payload)
    networks: list[IpNetwork] = []
    for prefix in data.get("prefixes", []):
        value = (
            prefix.get("ipv4Prefix")
            or prefix.get("ipv6Prefix")
            or prefix.get("ip_prefix")
        )
        if value:
            networks.append(ipaddress.ip_network(value))
    return networks


def _fetch_amazon_networks() -> list[IpNetwork]:
    payload = _fetch_text(_AMAZON_VERIFIER_URL)
    values = set(
        re.findall(r'\\?"ip_prefix\\?"\s*:\s*\\?"([^"\\]+)', payload)
    )
    return [ipaddress.ip_network(value) for value in sorted(values)]


def _load_verified_networks() -> tuple[dict[str, list[IpNetwork]], list[str]]:
    """Load provider-published crawler networks without blocking serially."""
    global _verifier_cache
    if (
        _verifier_cache
        and time.monotonic() - _verifier_cache[0] < _VERIFIER_CACHE_TTL_SECONDS
    ):
        return _verifier_cache[1], _verifier_cache[2]

    networks: dict[str, list[IpNetwork]] = {}
    failures: list[str] = []

    def fetch_json(item: tuple[str, str]) -> tuple[str, list[IpNetwork]]:
        bot, url = item
        return bot, _parse_json_networks(_fetch_text(url))

    with ThreadPoolExecutor(max_workers=len(_JSON_VERIFIERS) + 1) as executor:
        futures = {
            executor.submit(fetch_json, item): item[0]
            for item in _JSON_VERIFIERS.items()
        }
        futures[executor.submit(_fetch_amazon_networks)] = "Amazonbot"
        for future in as_completed(futures):
            bot = futures[future]
            try:
                result = future.result()
                values = result[1] if isinstance(result, tuple) else result
                if not values:
                    raise ValueError("empty prefix list")
                networks[bot] = values
            except Exception:
                failures.append(bot)

    failures = sorted(failures)
    _verifier_cache = (time.monotonic(), networks, failures)
    return networks, failures


class _IpVerifier:
    """Fast membership checks for provider prefix lists.

    Provider feeds contain hundreds of prefixes.  Grouping their network
    addresses by prefix length turns each request into a handful of integer
    mask lookups instead of a linear scan over every published network.
    """

    def __init__(self, networks: Sequence[IpNetwork]) -> None:
        grouped: dict[int, dict[int, set[int]]] = {4: {}, 6: {}}
        for network in networks:
            grouped[network.version].setdefault(network.prefixlen, set()).add(
                int(network.network_address)
            )
        self._tables: dict[int, list[tuple[int, set[int]]]] = {4: [], 6: []}
        for version, prefixes in grouped.items():
            bits = 32 if version == 4 else 128
            for prefixlen, addresses in prefixes.items():
                host_bits = bits - prefixlen
                mask = (
                    ((1 << bits) - 1) ^ ((1 << host_bits) - 1)
                    if host_bits
                    else (1 << bits) - 1
                )
                self._tables[version].append((mask, addresses))

    def contains(self, ip_value: str) -> bool:
        try:
            address = ipaddress.ip_address(ip_value)
        except ValueError:
            return False
        value = int(address)
        return any(
            (value & mask) in addresses
            for mask, addresses in self._tables[address.version]
        )


def _is_indexable_path(path: str) -> bool:
    return (
        path == "/"
        or path == "/blog"
        or path.startswith("/blog/")
        or path in {
            "/introduce",
            "/introduce/",
            "/robots.txt",
            "/sitemap.xml",
            "/feed.xml",
            "/llms.txt",
            "/llms-full.txt",
        }
    )


def _is_answer_content_path(path: str) -> bool:
    return (
        path == "/"
        or path == "/blog"
        or path.startswith("/blog/")
        or path in {"/introduce", "/introduce/", "/llms.txt", "/llms-full.txt"}
    )


def _is_suspicious_probe(path: str, raw_path: str) -> bool:
    if path.startswith("/blog/"):
        return False
    decoded = urllib.parse.unquote(raw_path)
    return (
        path in _SCAN_ENDPOINTS
        or bool(_SCAN_PATH_RE.search(path))
        or bool(_SCAN_QUERY_RE.search(decoded))
    )


def _empty_bot_entry(bot_name: str, verification_available: bool) -> dict[str, Any]:
    return {
        "bot": bot_name,
        "hits": 0,
        "ok": 0,
        "errors": 0,
        "verification_available": verification_available,
        "verified_hits": 0,
        "unverified_hits": 0,
        "content_ok": 0,
        "content_errors": 0,
        "discovery_errors": 0,
        "suspected_scan_hits": 0,
        "suspected_scan_errors": 0,
        "redirects": 0,
    }


def build_crawler_report(
    *,
    days: int,
    top_limit: int = 10,
    now: dt.datetime | None = None,
    verified_networks: Mapping[str, Sequence[IpNetwork]] | None = None,
) -> dict[str, Any]:
    """Summarize claimed and verified crawler traffic for the window."""
    cached = _cache.get(days)
    if cached and now is None and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    cutoff = (now or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(days=days)
    verifier_failures: list[str] = []
    if verified_networks is None:
        loaded_networks, verifier_failures = _load_verified_networks()
        verified_networks = loaded_networks
    ip_verifiers = {
        bot_name: _IpVerifier(networks)
        for bot_name, networks in verified_networks.items()
        if networks
    }

    records: list[dict[str, Any]] = []
    source_labels: dict[str, set[str]] = {}
    ai_referral_hits = 0
    ai_referral_sources: dict[str, int] = {}
    channels: dict[str, int] = {}
    first_at: dt.datetime | None = None
    last_at: dt.datetime | None = None

    try:
        for line in _iter_log_lines(_log_dir()):
            match = _LOG_LINE_RE.match(line)
            if not match:
                continue
            ua = match.group("ua")
            referer = match.group("referer")
            bot_name = _bot_name_for(ua)
            is_ai_ref = bool(_AI_REFERRER_RE.search(referer))
            channel = _channel_for(referer) if bot_name is None else None
            if bot_name is None and not is_ai_ref and channel is None:
                continue

            try:
                timestamp = dt.datetime.strptime(match.group("time"), _LOG_TIME_FORMAT)
            except ValueError:
                continue
            if timestamp < cutoff:
                continue

            # The dashboard discloses the observed crawler/acquisition window.
            # This avoids parsing timestamps for unrelated traffic while still
            # exposing when the selected period exceeds retained evidence.
            first_at = timestamp if first_at is None else min(first_at, timestamp)
            last_at = timestamp if last_at is None else max(last_at, timestamp)

            if bot_name is not None:
                raw_path = match.group("path")
                path = raw_path.split("?", 1)[0]
                ip_value = match.group("ip")
                records.append(
                    {
                        "bot": bot_name,
                        "ip": ip_value,
                        "path": path,
                        "raw_path": raw_path,
                        "status": int(match.group("status")),
                        "method": match.group("method"),
                    }
                )
                source_labels.setdefault(ip_value, set()).add(bot_name)
            elif is_ai_ref:
                ai_referral_hits += 1
                source_match = _AI_REFERRER_RE.search(referer)
                if source_match:
                    source = source_match.group(0).lower()
                    ai_referral_sources[source] = ai_referral_sources.get(source, 0) + 1
            elif channel is not None:
                channels[channel] = channels.get(channel, 0) + 1
    except (OSError, PermissionError) as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    rotating_sources = {ip for ip, labels in source_labels.items() if len(labels) >= 3}
    bot_hits: dict[str, dict[str, Any]] = {}
    citation_clicks = 0
    citation_paths: dict[str, int] = {}
    crawled_pages: dict[str, int] = {}
    verified_indexing_hits = 0
    verified_content_errors = 0
    discovery_errors = 0
    suspected_scan_hits = 0
    suspected_scan_errors = 0
    unverified_hits = 0

    for record in records:
        bot_name = record["bot"]
        networks = verified_networks.get(bot_name, ())
        verification_available = bool(networks)
        verified = verification_available and ip_verifiers[bot_name].contains(record["ip"])
        status = record["status"]
        path = record["path"]
        is_error = status >= 400
        is_scan = (
            record["method"] not in {"GET", "HEAD"}
            or record["ip"] in rotating_sources
            or _is_suspicious_probe(path, record["raw_path"])
        )

        entry = bot_hits.setdefault(
            bot_name, _empty_bot_entry(bot_name, verification_available)
        )
        entry["hits"] += 1
        entry["ok" if status < 400 else "errors"] += 1
        if verified:
            entry["verified_hits"] += 1
        else:
            entry["unverified_hits"] += 1
            unverified_hits += 1
        if 300 <= status < 400:
            entry["redirects"] += 1

        if is_scan:
            entry["suspected_scan_hits"] += 1
            suspected_scan_hits += 1
            if is_error:
                entry["suspected_scan_errors"] += 1
                suspected_scan_errors += 1
        elif verified and _is_indexable_path(path):
            if 200 <= status < 300:
                entry["content_ok"] += 1
                if bot_name in _INDEXING_BOTS:
                    verified_indexing_hits += 1
                    if path == "/blog" or path.startswith("/blog/"):
                        crawled_pages[path] = crawled_pages.get(path, 0) + 1
            elif is_error:
                entry["content_errors"] += 1
                verified_content_errors += 1
        elif verified and is_error:
            entry["discovery_errors"] += 1
            discovery_errors += 1

        # User-triggered fetch providers do not all publish stable ranges.  A
        # successful, public document fetch is still useful as an estimate, but
        # failed, private, and scanner-shaped requests never count as citations.
        fetch_identity_ok = not verification_available or verified
        if (
            bot_name in _USER_FETCH_BOTS
            and fetch_identity_ok
            and not is_scan
            and 200 <= status < 300
            and _is_answer_content_path(path)
        ):
            citation_clicks += 1
            citation_paths[path] = citation_paths.get(path, 0) + 1

    def rank(counts: dict[str, int], key: str) -> list[dict[str, Any]]:
        return sorted(
            ({key: name, "hits": count} for name, count in counts.items()),
            key=lambda item: -item["hits"],
        )[:top_limit]

    observed_days = (
        (last_at.date() - first_at.date()).days + 1 if first_at and last_at else 0
    )
    report = {
        "available": True,
        "bots": sorted(bot_hits.values(), key=lambda bot: -bot["hits"]),
        "verified_indexing_hits": verified_indexing_hits,
        "verified_content_errors": verified_content_errors,
        "discovery_errors": discovery_errors,
        "suspected_scan_hits": suspected_scan_hits,
        "suspected_scan_errors": suspected_scan_errors,
        "unverified_hits": unverified_hits,
        "citation_clicks": citation_clicks,
        "citation_paths": rank(citation_paths, "path"),
        "ai_referral_hits": ai_referral_hits,
        "ai_referral_sources": rank(ai_referral_sources, "source"),
        "crawled_pages": rank(crawled_pages, "path"),
        "channels": rank(channels, "channel"),
        "log_window": {
            "requested_days": days,
            "observed_days": observed_days,
            "first_at": first_at.isoformat() if first_at else None,
            "last_at": last_at.isoformat() if last_at else None,
        },
        "verification_failures": verifier_failures,
    }
    if now is None:
        _cache[days] = (time.monotonic(), report)
    return report
