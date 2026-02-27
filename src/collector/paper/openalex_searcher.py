"""
OpenAlex 검색 클라이언트
OpenAlex REST API를 통한 학술 논문 검색 (무료, API 키 불필요)
"""

import logging
import requests
from typing import List, Dict, Any, Optional
import time
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from utils.logger import log_search_operation

logger = logging.getLogger(__name__)


class OpenAlexSearcher:
    """OpenAlex API 검색 클라이언트"""

    def __init__(self):
        self.base_url = "https://api.openalex.org/works"
        self.headers = {
            'User-Agent': 'PaperReviewAgent/1.0 (mailto:paperreviewagent@example.com)',
            'Accept': 'application/json',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

        # Rate limiting
        self.request_delay = 0.5
        self.last_request_time = 0

    def close(self):
        """Close the HTTP session."""
        self.session.close()

    def __del__(self):
        self.session.close()

    def _rate_limit(self):
        """Rate limiting을 위한 요청 간 딜레이"""
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self.last_request_time = time.time()

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
        }

    @log_search_operation("OpenAlex")
    def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        OpenAlex API를 통한 논문 검색

        Args:
            query: 검색 쿼리
            max_results: 최대 결과 수

        Returns:
            논문 정보 리스트
        """
        try:
            self._rate_limit()

            params = {
                'search': query,
                'per_page': min(max_results, 50),
            }

            response = self.session.get(self.base_url, params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            papers = []

            for work in data.get("results", []):
                paper = self._parse_paper(work)
                if paper.get("title"):
                    papers.append(paper)

            return papers[:max_results]

        except Exception as e:
            print(f"[OpenAlex] Search error: {e}")
            return []

    @log_search_operation("OpenAlex Title")
    def search_by_title(self, title: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        논문 제목으로 검색

        Args:
            title: 논문 제목
            max_results: 최대 결과 수

        Returns:
            논문 정보 리스트
        """
        try:
            self._rate_limit()

            params = {
                'filter': f'title.search:{title}',
                'per_page': min(max_results, 50),
            }

            response = self.session.get(self.base_url, params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            papers = []

            for work in data.get("results", []):
                paper = self._parse_paper(work)
                if paper.get("title"):
                    papers.append(paper)

            return papers[:max_results]

        except Exception as e:
            print(f"[OpenAlex] Title search error: {e}")
            # Fallback to general search
            return self.search(title, max_results)

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
            print(f"[OpenAlex] Enhanced search error: {e}")
            return []
