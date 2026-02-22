"""
DBLP 검색 클라이언트
DBLP REST API를 통한 컴퓨터 과학 논문 검색 (무료, API 키 불필요)
"""

import requests
from typing import List, Dict, Any, Optional
import time
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from utils.logger import log_search_operation


class DBLPSearcher:
    """DBLP API 검색 클라이언트"""

    def __init__(self):
        self.base_url = "https://dblp.org/search/publ/api"
        self.headers = {
            'User-Agent': 'PaperReviewAgent/1.0',
            'Accept': 'application/json',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

        # Rate limiting
        self.request_delay = 1.0
        self.last_request_time = 0

    def _rate_limit(self):
        """Rate limiting을 위한 요청 간 딜레이"""
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self.last_request_time = time.time()

    def _extract_authors(self, info: Dict) -> List[str]:
        """DBLP authors 필드에서 저자 목록 추출 (다형성 처리)"""
        raw_authors = info.get("authors", {}).get("author", [])

        if isinstance(raw_authors, str):
            return [raw_authors]
        elif isinstance(raw_authors, dict):
            return [raw_authors.get("text", raw_authors.get("@text", str(raw_authors)))]
        elif isinstance(raw_authors, list):
            authors = []
            for a in raw_authors:
                if isinstance(a, str):
                    authors.append(a)
                elif isinstance(a, dict):
                    authors.append(a.get("text", a.get("@text", str(a))))
            return authors
        return []

    def _extract_paper_info(self, hit: Dict) -> Optional[Dict[str, Any]]:
        """DBLP hit에서 논문 정보 추출"""
        info = hit.get("info", {})
        if not info:
            return None

        title = info.get("title", "").rstrip(".")
        if not title:
            return None

        authors = self._extract_authors(info)

        # DOI
        doi = info.get("doi", "") or ""

        # URL: ee (electronic edition) 우선, fallback to DOI URL
        url = info.get("ee", "")
        if isinstance(url, list):
            url = url[0] if url else ""
        if not url and doi:
            url = f"https://doi.org/{doi}"
        if not url:
            url = info.get("url", "")

        return {
            "title": title,
            "authors": authors,
            "abstract": "",  # DBLP는 초록을 제공하지 않음
            "url": url,
            "pdf_url": "",
            "source": "DBLP",
            "year": str(info.get("year", "")),
            "citations": 0,  # DBLP는 인용수를 제공하지 않음
            "doi": doi,
            "venue": info.get("venue", ""),
            "dblp_key": info.get("key", ""),
        }

    @log_search_operation("DBLP")
    def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        DBLP API를 통한 논문 검색

        Args:
            query: 검색 쿼리
            max_results: 최대 결과 수

        Returns:
            논문 정보 리스트
        """
        try:
            self._rate_limit()

            # DBLP는 긴 쿼리에서 500 에러 발생 → stopword 제거 후 핵심 키워드 추출
            _stopwords = {
                'the', 'a', 'an', 'in', 'on', 'for', 'of', 'with', 'by', 'from',
                'and', 'or', 'to', 'is', 'are', 'using', 'based', 'via', 'through',
                'its', 'their', 'our', 'this', 'that', 'these', 'those', 'how',
                'what', 'which', 'where', 'when', 'can', 'will', 'into', 'over',
                'under', 'about', 'between', 'towards', 'toward',
            }
            words = query.split()
            keywords = [w for w in words if w.lower() not in _stopwords and len(w) > 1]
            if len(keywords) > 8:
                keywords = keywords[:8]
            if keywords:
                query = " ".join(keywords)

            params = {
                'q': query,
                'h': min(max_results, 100),
                'format': 'json',
            }

            response = self.session.get(self.base_url, params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            hits = data.get("result", {}).get("hits", {}).get("hit", [])

            papers = []
            for hit in hits:
                paper = self._extract_paper_info(hit)
                if paper:
                    papers.append(paper)

            return papers[:max_results]

        except Exception as e:
            print(f"[DBLP] Search error: {e}")
            return []

    @log_search_operation("DBLP Title")
    def search_by_title(self, title: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        논문 제목으로 검색

        Args:
            title: 논문 제목
            max_results: 최대 결과 수

        Returns:
            논문 정보 리스트
        """
        # DBLP에서 정확한 제목 검색은 $ 구분자 사용
        exact_query = f"${title}$"
        return self.search(exact_query, max_results)

    @log_search_operation("DBLP Author")
    def search_by_author(self, author: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        저자별 논문 검색

        Args:
            author: 저자 이름
            max_results: 최대 결과 수

        Returns:
            논문 정보 리스트
        """
        try:
            self._rate_limit()

            # DBLP author search API
            author_url = "https://dblp.org/search/author/api"
            params = {
                'q': author,
                'h': 5,
                'format': 'json',
            }

            response = self.session.get(author_url, params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            hits = data.get("result", {}).get("hits", {}).get("hit", [])

            if not hits:
                # Fallback: 일반 검색에 저자 이름 사용
                return self.search(author, max_results)

            # 첫 번째 저자의 URL에서 논문 목록 검색
            author_info = hits[0].get("info", {})
            author_url_page = author_info.get("url", "")

            if author_url_page:
                # 저자 이름으로 논문 검색
                return self.search(author, max_results)

            return []

        except Exception as e:
            print(f"[DBLP] Author search error: {e}")
            return self.search(author, max_results)
