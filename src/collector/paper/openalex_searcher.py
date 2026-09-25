"""
OpenAlex 검색 클라이언트
OpenAlex REST API를 통한 학술 논문 검색 (무료, API 키 불필요)
"""

import logging
import time
import requests
from typing import List, Dict, Any, Optional

from src.collector.paper.rate_limiter import RateLimiter
from src.utils.logger import log_search_operation

logger = logging.getLogger(__name__)


class OpenAlexSearcher:
    """OpenAlex API 검색 클라이언트"""

    # Class-level: the upstream quota is per-IP, so the throttle must cover the
    # whole process. Several call sites build their own searcher (curriculum,
    # related-paper wiki), and per-instance limiters would not see each other.
    _rate_limiter = RateLimiter(0.5)

    def __init__(self):
        self.base_url = "https://api.openalex.org/works"
        self.headers = {
            'User-Agent': 'PaperReviewAgent/1.0 (mailto:paperreviewagent@example.com)',
            'Accept': 'application/json',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)


    def close(self):
        """Close the HTTP session."""
        self.session.close()

    def __del__(self):
        self.session.close()

    def _rate_limit(self):
        """Rate limiting을 위한 요청 간 딜레이"""
        self._rate_limiter.wait()

    def _reconstruct_abstract(self, inverted_index: Optional[Dict]) -> str:
        """OpenAlex abstract_inverted_index에서 원문 재구성"""
        if not inverted_index:
            return ""
        try:
            word_positions = []
            for word, positions in inverted_index.items():
                for pos in positions:
                    word_positions.append((pos, word))
            word_positions.sort(key=lambda x: x[0])
            return " ".join(word for _, word in word_positions)
        except Exception as e:
            logger.debug("Failed to reconstruct abstract from inverted index: %s", e)
            return ""

    def _parse_paper(self, work: Dict) -> Dict[str, Any]:
        """OpenAlex work 객체를 표준 논문 형식으로 변환"""
        # Authors
        authors = []
        for authorship in work.get("authorships", []):
            author = authorship.get("author", {})
            name = author.get("display_name", "")
            if name:
                authors.append(name)

        # DOI
        doi = work.get("doi", "") or ""
        if doi.startswith("https://doi.org/"):
            doi = doi[len("https://doi.org/"):]

        # URL
        primary_location = work.get("primary_location") or {}
        url = primary_location.get("landing_page_url", "")
        if not url and doi:
            url = f"https://doi.org/{doi}"
        if not url:
            url = work.get("id", "")

        # PDF URL
        pdf_url = ""
        best_oa = work.get("best_oa_location") or {}
        if best_oa.get("pdf_url"):
            pdf_url = best_oa["pdf_url"]

        # Abstract
        abstract = self._reconstruct_abstract(work.get("abstract_inverted_index"))

        # Venue (journal/conference name)
        source_obj = primary_location.get("source") or {}
        venue = source_obj.get("display_name", "")

        return {
            "title": work.get("display_name", ""),
            "authors": authors,
            "abstract": abstract,
            "url": url,
            "pdf_url": pdf_url,
            "source": "OpenAlex",
            "year": str(work.get("publication_year", "")),
            "citations": work.get("cited_by_count", 0),
            "doi": doi,
            "openalex_id": work.get("id", ""),
            "relevance_score": work.get("relevance_score"),
            "venue": venue,
        }

    def _search_requests(self, query, max_results, filters, *, deadline=None, stop_event=None, attempts=None):
        from src.utils.paper_utils import generate_result_key
        deadline = deadline if deadline is not None else time.monotonic() + 30
        papers, seen = [], set()
        for source_filter in filters:
            receipt = {"query": query, "filter": source_filter, "status": "dispatched"}
            if attempts is not None:
                attempts.append(receipt)
            try:
                if time.monotonic() >= deadline or (stop_event is not None and stop_event.is_set()):
                    raise TimeoutError("OpenAlex budget exhausted")
                self._rate_limit()
                remaining = deadline - time.monotonic()
                if remaining <= 0 or (stop_event is not None and stop_event.is_set()):
                    raise TimeoutError("OpenAlex budget exhausted")
                params = {"per_page": min(max_results * 2, 50)}
                if not source_filter or not source_filter.startswith("title.search:"):
                    params["search"] = query
                if source_filter:
                    params["filter"] = source_filter
                response = self.session.get(self.base_url, params=params, timeout=min(15, remaining))
                response.raise_for_status()
                works = response.json().get("results", [])
                receipt["status"] = "searched" if works else "searched_empty"
                for work in works:
                    paper = self._parse_paper(work)
                    if source_filter in ("language:ko", "institutions.country_code:KR"):
                        paper["source"] = "OpenAlex Korean"
                    key = generate_result_key(paper)
                    if paper.get("title") and key not in seen:
                        seen.add(key)
                        papers.append(paper)
            except Exception as error:
                receipt["status"] = "timeout" if isinstance(error, (TimeoutError, requests.Timeout)) else "error"
                if attempts is None:
                    raise
                if receipt["status"] == "timeout":
                    break
            if len(papers) >= max_results:
                break
        if filters == [None] and papers and papers[0].get("relevance_score"):
            top_score = papers[0]["relevance_score"]
            if top_score > 0:
                papers = [p for p in papers if not p.get("relevance_score") or p["relevance_score"] >= top_score * 0.3]
        return papers[:max_results]

    @log_search_operation("OpenAlex")
    def search(self, query: str, max_results: int = 10, *, deadline=None, stop_event=None, attempts=None) -> List[Dict[str, Any]]:
        return self._search_requests(query, max_results, [None], deadline=deadline, stop_event=stop_event, attempts=attempts)

    @log_search_operation("OpenAlex Title")
    def search_by_title(self, title: str, max_results: int = 5, *, deadline=None, stop_event=None, attempts=None) -> List[Dict[str, Any]]:
        return self._search_requests(title, max_results, [f'title.search:{title}'], deadline=deadline, stop_event=stop_event, attempts=attempts)

    @log_search_operation("OpenAlex Korean")
    def search_korean(self, query: str, max_results: int = 10, *, deadline=None, stop_event=None, attempts=None) -> List[Dict[str, Any]]:
        return self._search_requests(query, max_results, ['language:ko', 'institutions.country_code:KR'], deadline=deadline, stop_event=stop_event, attempts=attempts)

    @log_search_operation("OpenAlex Enhanced")
    def enhanced_search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        향상된 검색 - 일반 검색 + 제목 필터 검색 병합

        Args:
            query: 검색 쿼리
            max_results: 최대 결과 수

        Returns:
            논문 정보 리스트
        """
        try:
            seen_titles = set()
            all_papers = []

            # 1. 일반 검색
            basic_results = self.search(query, max_results)
            for paper in basic_results:
                title_lower = paper.get("title", "").lower().strip()
                if title_lower and title_lower not in seen_titles:
                    seen_titles.add(title_lower)
                    all_papers.append(paper)

            # 2. 제목 필터 검색 (결과 부족 시)
            if len(all_papers) < max_results:
                remaining = max_results - len(all_papers)
                title_results = self.search_by_title(query, remaining)
                for paper in title_results:
                    title_lower = paper.get("title", "").lower().strip()
                    if title_lower and title_lower not in seen_titles:
                        seen_titles.add(title_lower)
                        all_papers.append(paper)

            return all_papers[:max_results]

        except Exception as e:
            logger.error("OpenAlex enhanced search error: %s", e)
            return []
