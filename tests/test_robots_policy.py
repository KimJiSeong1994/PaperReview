from pathlib import Path
import re

ROBOTS_PATH = Path("web-ui/public/robots.txt")
DIST_ROBOTS_PATH = Path("web-ui/dist/robots.txt")

NO_BLANKET_BLOCK_AGENTS = [
    "GPTBot",
    "ClaudeBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "Claude-SearchBot",
    "Claude-User",
    "PerplexityBot",
]

AI_SEARCH_AND_DISCOVERY_AGENTS = [
    "OAI-SearchBot",
    "ChatGPT-User",
    "GPTBot",
    "ClaudeBot",
    "Claude-User",
    "Claude-SearchBot",
    "PerplexityBot",
    "Googlebot",
    "Bingbot",
    "Yeti",
    "DAUM",
    "DuckDuckBot",
    "Slurp",
    "YandexBot",
    "Baiduspider",
]

PRIVATE_PATHS = [
    "/api/",
    "/admin",
    "/admin/",
    "/mypage",
    "/mypage/",
    "/share/*",
    "/share/curriculum/*",
    "/api/admin*",
    "/api/me*",
    "/api/bookmarks*",
    "/api/shared/*",
    "/api/shared/curriculum/*",
    "/api/auth*",
    "/api/recommendations*",
    "/api/analytics*",
    "/api/private*",
    "/api/user*",
]

ROBOTS_PATHS = [
    ROBOTS_PATH,
    *([DIST_ROBOTS_PATH] if DIST_ROBOTS_PATH.exists() else []),
]

REPRESENTATIVE_USER_AGENTS = [
    "*",
    "OAI-SearchBot",
    "ChatGPT-User",
    "GPTBot",
    "ClaudeBot",
    "Claude-SearchBot",
    "Claude-User",
    "PerplexityBot",
    "Googlebot",
    "Bingbot",
    "Yeti",
    "DAUM",
    "DuckDuckBot",
    "Slurp",
    "YandexBot",
    "Baiduspider",
]

PUBLIC_ALLOWED_SAMPLES = [
    "/",
    "/blog",
    "/blog/some-post",
    "/api/blog/thumbnail/x",
    "/api/blog/figures/x",
]

PRIVATE_DISALLOWED_SAMPLES = [
    "/admin",
    "/mypage",
    "/share/token",
    "/share/curriculum/x",
    "/api/auth/login",
    "/api/recommendations/list",
    "/api/analytics/event",
    "/api/private/data",
    "/api/user/settings",
    "/api/shared/x",
    "/api/shared/curriculum/x",
    "/api/admin/dashboard",
    "/api/me/all",
    "/api/bookmarks",
    "/api/curricula/course/progress",
    "/api/deep-review/status/session",
    "/api/deep-review/report/session",
    "/api/deep-review/verification/session",
    "/api/light-rag/status",
]


def _parse_groups(text: str) -> list[tuple[list[str], list[tuple[str, str]]]]:
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []

    def flush() -> None:
        nonlocal agents, rules
        if agents:
            groups.append((agents, rules))
            agents = []
            rules = []

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if rules:
                flush()
            agents.append(value)
        elif key in {"allow", "disallow"}:
            rules.append((key, value))
    flush()
    return groups


def _rules_for(agent: str, text: str) -> list[tuple[str, str]]:
    for agents, rules in _parse_groups(text):
        if agent in agents:
            return rules
    for agents, rules in _parse_groups(text):
        if "*" in agents:
            return rules
    return []


def _pattern_matches(pattern: str, path: str) -> bool:
    if not pattern:
        return False

    regex = re.escape(pattern).replace(r"\*", ".*")
    if regex.endswith(r"\$"):
        regex = regex[:-2] + "$"
    else:
        regex += ".*"

    return re.match(regex, path) is not None


def _match_length(pattern: str) -> int:
    return len(pattern.replace("*", "").removesuffix("$"))


def _is_allowed(agent: str, path: str, text: str) -> bool:
    matching_rules = [
        (directive, pattern)
        for directive, pattern in _rules_for(agent, text)
        if _pattern_matches(pattern, path)
    ]
    if not matching_rules:
        return True

    best_length = max(_match_length(pattern) for _, pattern in matching_rules)
    best_rules = [
        directive
        for directive, pattern in matching_rules
        if _match_length(pattern) == best_length
    ]
    return "allow" in best_rules


def test_dist_robots_matches_public_when_present() -> None:
    if DIST_ROBOTS_PATH.exists():
        assert DIST_ROBOTS_PATH.read_text(encoding="utf-8") == ROBOTS_PATH.read_text(encoding="utf-8")


def test_representative_ai_agents_are_not_blanket_blocked() -> None:
    for robots_path in ROBOTS_PATHS:
        text = robots_path.read_text(encoding="utf-8")
        for agent in NO_BLANKET_BLOCK_AGENTS:
            rules = _rules_for(agent, text)
            assert rules, f"{agent} should be declared explicitly in {robots_path}"
            assert ("disallow", "/") not in rules, f"{agent} must not be blanket-blocked in {robots_path}"


def test_ai_search_answer_and_model_agents_are_present_and_publicly_allowed() -> None:
    for robots_path in ROBOTS_PATHS:
        text = robots_path.read_text(encoding="utf-8")
        for agent in AI_SEARCH_AND_DISCOVERY_AGENTS:
            rules = _rules_for(agent, text)
            assert rules, f"{agent} should be declared explicitly in {robots_path}"
            assert ("allow", "/") in rules, f"{agent} should be allowed on public pages in {robots_path}"


def test_private_paths_remain_disallowed_for_all_relevant_groups() -> None:
    for robots_path in ROBOTS_PATHS:
        text = robots_path.read_text(encoding="utf-8")
        for agents, rules in _parse_groups(text):
            if "*" in agents or any(agent in AI_SEARCH_AND_DISCOVERY_AGENTS for agent in agents):
                for path in PRIVATE_PATHS:
                    assert ("disallow", path) in rules, f"{agents} must keep {path} private in {robots_path}"


def test_effective_policy_allows_public_paths_for_representative_agents() -> None:
    for robots_path in ROBOTS_PATHS:
        text = robots_path.read_text(encoding="utf-8")
        for agent in REPRESENTATIVE_USER_AGENTS:
            for path in PUBLIC_ALLOWED_SAMPLES:
                assert _is_allowed(agent, path, text), f"{agent} should allow {path} in {robots_path}"


def test_blog_media_allow_rules_beat_api_disallow_by_longest_match() -> None:
    for robots_path in ROBOTS_PATHS:
        text = robots_path.read_text(encoding="utf-8")
        for agent in REPRESENTATIVE_USER_AGENTS:
            rules = _rules_for(agent, text)
            assert ("disallow", "/api/") in rules, f"{agent} should broadly block API paths in {robots_path}"
            for path in ["/api/blog/thumbnail/x", "/api/blog/figures/x"]:
                matching_rules = [
                    (directive, pattern)
                    for directive, pattern in rules
                    if _pattern_matches(pattern, path)
                ]
                best_length = max(_match_length(pattern) for _, pattern in matching_rules)
                assert best_length > _match_length("/api/")
                assert _is_allowed(agent, path, text), f"{agent} should allow {path} in {robots_path}"


def test_effective_policy_disallows_private_paths_for_representative_agents() -> None:
    for robots_path in ROBOTS_PATHS:
        text = robots_path.read_text(encoding="utf-8")
        for agent in REPRESENTATIVE_USER_AGENTS:
            for path in PRIVATE_DISALLOWED_SAMPLES:
                assert not _is_allowed(agent, path, text), f"{agent} should disallow {path} in {robots_path}"


def test_sitemap_directive_exists() -> None:
    for robots_path in ROBOTS_PATHS:
        assert "Sitemap: https://jiphyeonjeon.kr/sitemap.xml" in robots_path.read_text(encoding="utf-8")
