"""GitHub Search API client for finding paper code repositories."""

import logging
import os
import re
from typing import Any, Dict, List

import requests

logger = logging.getLogger(__name__)


class GitHubClient:
    """Search GitHub repositories related to academic papers."""

    BASE_URL = "https://api.github.com"

    def __init__(self):
        self.token = os.environ.get("GITHUB_TOKEN")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    def search_repos_by_title(self, title: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Search GitHub repositories by paper title.

        Args:
            title: Paper title to search for.
            max_results: Maximum number of repositories to return.

        Returns:
            List of repo dicts with keys: url, stars, description, language, is_official.
        """
        query = self._build_query(title)
        if not query:
            return []

        try:
            resp = self.session.get(
                f"{self.BASE_URL}/search/repositories",
                params={
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": min(max_results, 10),
                },
                timeout=10,
            )
            if resp.status_code == 403:
                logger.warning("GitHub API rate limit exceeded")
                return []
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("GitHub API error: %s", e)
            return []

        repos: List[Dict[str, Any]] = []
        for item in data.get("items", [])[:max_results]:
            repos.append({
                "url": item.get("html_url", ""),
                "stars": item.get("stargazers_count", 0),
                "description": item.get("description") or "",
                "language": item.get("language") or "",
                "is_official": self._is_official(item, title),
            })

        # Sort: official first, then by stars
        repos.sort(key=lambda r: (not r["is_official"], -r["stars"]))
        return repos

    def _build_query(self, title: str) -> str:
        """Build a GitHub search query from a paper title."""
        # Remove common filler words and punctuation for better search
        stop_words = {
            "a", "an", "the", "of", "for", "in", "on", "to", "and", "or",
            "with", "by", "from", "is", "are", "was", "were", "be", "been",
            "its", "it", "this", "that", "as", "at", "via", "using",
        }
        words = re.findall(r"\b\w+\b", title.lower())
        keywords = [w for w in words if w not in stop_words and len(w) > 1]
        if not keywords:
            return ""
        # Use the most significant keywords (up to 8) to avoid query being too long
        query = " ".join(keywords[:8])
        return query

    def _is_official(self, item: Dict[str, Any], title: str) -> bool:
        """Heuristic to determine if a repo is the official implementation."""
        desc = (item.get("description") or "").lower()
        name = (item.get("name") or "").lower()
        combined = f"{desc} {name}"

        # Must explicitly say "official" in description or name
        if "official" not in combined:
            return False

        # Check title keyword overlap with description/name
        title_words = set(re.findall(r"\b\w{4,}\b", title.lower()))
        combined_words = set(re.findall(r"\b\w{4,}\b", combined))
        title_overlap = len(title_words & combined_words)

        return title_overlap >= max(len(title_words) * 0.4, 3)
