"""GitHub Search API client for finding paper code repositories.

Multi-source strategy:
  1. Papers With Code API — curated paper-to-repo mappings (most reliable)
  2. Semantic Scholar API — official code URLs from paper metadata
  3. GitHub Search API — fallback with author + title for precision
"""

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class GitHubClient:
    """Search GitHub repositories related to academic papers."""

    BASE_URL = "https://api.github.com"
    PWC_API = "https://paperswithcode.com/api/v1"
    S2_API = "https://api.semanticscholar.org/graph/v1"

    def __init__(self):
        self.token = os.environ.get("GITHUB_TOKEN")
        self.s2_key = os.environ.get("S2_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    def search_repos(
        self,
        title: str,
        arxiv_id: Optional[str] = None,
        doi: Optional[str] = None,
        authors: Optional[List[str]] = None,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search code repositories for a paper using multiple sources.

        Priority:
          1. Papers With Code (curated mapping)
          2. Semantic Scholar (paper metadata)
          3. GitHub Search (fallback with relevance filtering)

        Args:
            title: Paper title.
            arxiv_id: arXiv identifier (e.g. "1706.03762").
            doi: DOI string.
            authors: List of author names.
            max_results: Maximum repos to return.

        Returns:
            List of repo dicts: url, stars, description, language, is_official, source.
        """
        seen_urls: set[str] = set()
        repos: List[Dict[str, Any]] = []

        # ── Source 1: Papers With Code ──
        pwc_repos = self._search_papers_with_code(title, arxiv_id)
        for r in pwc_repos:
            url_lower = r["url"].lower().rstrip("/")
            if url_lower not in seen_urls:
                seen_urls.add(url_lower)
                repos.append(r)

        # ── Source 2: Semantic Scholar ──
        if len(repos) < max_results:
            s2_repos = self._search_semantic_scholar(title, arxiv_id, doi)
            for r in s2_repos:
                url_lower = r["url"].lower().rstrip("/")
                if url_lower not in seen_urls:
                    seen_urls.add(url_lower)
                    repos.append(r)

        # ── Source 3: GitHub Search (fallback) ──
        if len(repos) < max_results:
            gh_repos = self._search_github(title, authors, max_results)
            for r in gh_repos:
                url_lower = r["url"].lower().rstrip("/")
                if url_lower not in seen_urls:
                    seen_urls.add(url_lower)
                    repos.append(r)

        # Sort: official/PWC first, then by stars
        repos.sort(key=lambda r: (
            not r.get("is_official", False),
            r.get("source") != "PapersWithCode",
            -r.get("stars", 0),
        ))
        return repos[:max_results]

    # ── Keep backward compatibility ──
    def search_repos_by_title(self, title: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Legacy method — delegates to search_repos."""
        return self.search_repos(title, max_results=max_results)

    # ── Source 1: Papers With Code ──────────────────────────────────

    def _search_papers_with_code(
        self, title: str, arxiv_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search Papers With Code API for curated paper-repo mappings."""
        repos = []

        # Try by arXiv ID first (most precise)
        if arxiv_id:
            clean_id = arxiv_id.strip().replace("arXiv:", "")
            try:
                resp = self.session.get(
                    f"{self.PWC_API}/papers",
                    params={"arxiv_id": clean_id},
                    timeout=10,
                )
                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    if results:
                        paper_id = results[0].get("id", "")
                        if paper_id:
                            repos.extend(self._get_pwc_repos(paper_id))
            except requests.RequestException as e:
                logger.warning("PWC arXiv lookup failed: %s", e)

        # Fallback: search by title
        if not repos:
            try:
                resp = self.session.get(
                    f"{self.PWC_API}/papers",
                    params={"q": title[:200]},
                    timeout=10,
                )
                if resp.status_code == 200:
                    for paper in resp.json().get("results", [])[:3]:
                        paper_title = (paper.get("title") or "").lower().strip()
                        if self._title_similarity(title, paper_title) > 0.6:
                            paper_id = paper.get("id", "")
                            if paper_id:
                                repos.extend(self._get_pwc_repos(paper_id))
                                break
            except requests.RequestException as e:
                logger.warning("PWC title search failed: %s", e)

        return repos

    def _get_pwc_repos(self, paper_id: str) -> List[Dict[str, Any]]:
        """Fetch repositories for a Papers With Code paper ID."""
        repos = []
        try:
            resp = self.session.get(
                f"{self.PWC_API}/papers/{paper_id}/repositories/",
                timeout=10,
            )
            if resp.status_code != 200:
                return []
            for item in resp.json().get("results", [])[:5]:
                url = item.get("url", "")
                if not url:
                    continue
                repos.append({
                    "url": url,
                    "stars": item.get("stars", 0),
                    "description": item.get("description") or "",
                    "language": "",
                    "is_official": item.get("is_official", False),
                    "source": "PapersWithCode",
                })
        except requests.RequestException as e:
            logger.warning("PWC repos fetch failed for %s: %s", paper_id, e)
        return repos

    # ── Source 2: Semantic Scholar ──────────────────────────────────

    def _search_semantic_scholar(
        self,
        title: str,
        arxiv_id: Optional[str] = None,
        doi: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find code URLs from Semantic Scholar paper metadata."""
        headers = {}
        if self.s2_key:
            headers["x-api-key"] = self.s2_key

        paper_id = None
        if arxiv_id:
            paper_id = f"ArXiv:{arxiv_id.strip().replace('arXiv:', '')}"
        elif doi:
            paper_id = f"DOI:{doi.strip()}"

        if not paper_id:
            # Search by title
            try:
                resp = requests.get(
                    f"{self.S2_API}/paper/search",
                    params={"query": title[:200], "limit": 3, "fields": "title,externalIds,openAccessPdf"},
                    headers=headers,
                    timeout=10,
                )
                if resp.status_code == 200:
                    for p in resp.json().get("data", []):
                        if self._title_similarity(title, p.get("title", "")) > 0.6:
                            ext_ids = p.get("externalIds") or {}
                            paper_id = ext_ids.get("CorpusId")
                            if paper_id:
                                paper_id = f"CorpusID:{paper_id}"
                            break
            except requests.RequestException as e:
                logger.warning("S2 title search failed: %s", e)
            time.sleep(0.3)

        if not paper_id:
            return []

        # Fetch paper details with links
        try:
            resp = requests.get(
                f"{self.S2_API}/paper/{paper_id}",
                params={"fields": "title,externalIds,openAccessPdf,url"},
                headers=headers,
                timeout=10,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
        except requests.RequestException as e:
            logger.warning("S2 paper fetch failed: %s", e)
            return []

        repos = []
        # Check if S2 links to a GitHub URL
        ext_ids = data.get("externalIds") or {}
        # Some papers have GitHub listed in external URLs
        for field in [data.get("url", ""), data.get("openAccessPdf", {}).get("url", "") if data.get("openAccessPdf") else ""]:
            if field and "github.com" in field:
                repos.append({
                    "url": field,
                    "stars": 0,
                    "description": "Found via Semantic Scholar",
                    "language": "",
                    "is_official": True,
                    "source": "SemanticScholar",
                })
        return repos

    # ── Source 3: GitHub Search (fallback) ──────────────────────────

    def _search_github(
        self, title: str, authors: Optional[List[str]] = None, max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search GitHub with title + author for better precision."""
        query = self._build_query(title)
        if not query:
            return []

        # Add first author's last name for precision
        if authors and authors[0]:
            last_name = authors[0].split()[-1].strip()
            if len(last_name) >= 2:
                query = f"{query} {last_name}"

        try:
            resp = self.session.get(
                f"{self.BASE_URL}/search/repositories",
                params={
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": min(max_results * 2, 20),
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
        for item in data.get("items", []):
            relevance = self._compute_relevance(item, title, authors)
            if relevance < 0.3:
                continue  # Skip clearly irrelevant repos
            repos.append({
                "url": item.get("html_url", ""),
                "stars": item.get("stargazers_count", 0),
                "description": item.get("description") or "",
                "language": item.get("language") or "",
                "is_official": self._is_official(item, title),
                "source": "GitHub",
                "_relevance": relevance,
            })

        repos.sort(key=lambda r: (-r.get("_relevance", 0), -r.get("stars", 0)))
        # Remove internal score before returning
        for r in repos:
            r.pop("_relevance", None)
        return repos[:max_results]

    # ── Helpers ─────────────────────────────────────────────────────

    def _build_query(self, title: str) -> str:
        """Build a GitHub search query from a paper title."""
        stop_words = {
            "a", "an", "the", "of", "for", "in", "on", "to", "and", "or",
            "with", "by", "from", "is", "are", "was", "were", "be", "been",
            "its", "it", "this", "that", "as", "at", "via", "using",
        }
        words = re.findall(r"\b\w+\b", title.lower())
        keywords = [w for w in words if w not in stop_words and len(w) > 1]
        if not keywords:
            return ""
        return " ".join(keywords[:8])

    def _is_official(self, item: Dict[str, Any], title: str) -> bool:
        """Heuristic to determine if a repo is the official implementation."""
        desc = (item.get("description") or "").lower()
        name = (item.get("name") or "").lower()
        combined = f"{desc} {name}"

        official_markers = ["official", "implementation of", "code for"]
        has_marker = any(m in combined for m in official_markers)
        if not has_marker:
            return False

        title_words = set(re.findall(r"\b\w{4,}\b", title.lower()))
        combined_words = set(re.findall(r"\b\w{4,}\b", combined))
        title_overlap = len(title_words & combined_words)
        return title_overlap >= max(len(title_words) * 0.3, 2)

    def _compute_relevance(
        self, item: Dict[str, Any], title: str, authors: Optional[List[str]] = None,
    ) -> float:
        """Compute relevance score (0-1) of a GitHub repo to a paper."""
        desc = (item.get("description") or "").lower()
        name = (item.get("name") or "").lower()
        readme_topics = " ".join(item.get("topics", []))
        combined = f"{desc} {name} {readme_topics}"

        # Title keyword overlap
        title_words = set(re.findall(r"\b\w{4,}\b", title.lower()))
        combined_words = set(re.findall(r"\b\w{4,}\b", combined))
        if not title_words:
            return 0.0
        word_overlap = len(title_words & combined_words) / len(title_words)

        # Paper-related signals
        paper_signals = ["paper", "official", "implementation", "arxiv", "conference", "neurips", "icml", "iclr", "cvpr", "acl", "emnlp"]
        signal_bonus = 0.15 if any(s in combined for s in paper_signals) else 0.0

        # Author match bonus
        author_bonus = 0.0
        if authors:
            owner = (item.get("owner") or {}).get("login", "").lower()
            for author in authors[:3]:
                last = author.split()[-1].lower().strip()
                if len(last) >= 2 and last in owner:
                    author_bonus = 0.2
                    break

        return min(word_overlap + signal_bonus + author_bonus, 1.0)

    def _title_similarity(self, title_a: str, title_b: str) -> float:
        """Simple word-overlap similarity between two titles."""
        words_a = set(re.findall(r"\b\w{3,}\b", title_a.lower()))
        words_b = set(re.findall(r"\b\w{3,}\b", title_b.lower()))
        if not words_a or not words_b:
            return 0.0
        intersection = len(words_a & words_b)
        return intersection / max(len(words_a), len(words_b))
