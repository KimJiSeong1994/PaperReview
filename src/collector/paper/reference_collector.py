import logging
import requests
from typing import List, Dict, Any, Optional
import time
import sys
import os
from src.utils.logger import log_search_operation

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ReferenceCollector:
    """논문 참고문헌 수집 클라이언트"""

    def __init__(self):
        self.base_url = "https://api.semanticscholar.org/graph/v1"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def close(self):
        """Close the HTTP session."""
        self.session.close()

    def __del__(self):
        self.session.close()

    @log_search_operation("Reference Collection")
    def get_references(self, paper: Dict[str, Any], max_references: int = 10) -> List[Dict[str, Any]]:
        paper_id = self._extract_paper_id(paper)

        if not paper_id:
            return []
        references = self._fetch_references_from_semantic_scholar(paper_id, max_references)
        return [self._enrich_reference(ref, paper) for ref in references]

    def _extract_paper_id(self, paper: Dict[str, Any]) -> Optional[str]:
        """논문에서 ID 추출"""
        # DOI가 있으면 DOI 사용
        if paper.get('doi') and paper['doi']:
            return f"DOI:{paper['doi']}"

        # arXiv ID 사용 (버전 번호 제거)
        if paper.get('arxiv_id'):
            arxiv_id = paper['arxiv_id'].split('v')[0]  # 버전 번호 제거
            return f"ARXIV:{arxiv_id}"

        # Connected Papers ID 사용
        if paper.get('connected_papers_id') and paper['connected_papers_id'].startswith('ss_'):
            return paper['connected_papers_id'][3:]  # ss_ 제거

        # 제목으로 검색 시도
        if paper.get('title'):
            return self._search_paper_id_by_title(paper['title'])

        return None

    def _request_with_retry(
        self, url: str, params: dict, timeout: int = 20, max_retries: int = 3,
    ) -> Optional[requests.Response]:
        """HTTP GET with exponential backoff retry for transient errors."""
        last_exc = None
        for attempt in range(max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=timeout)
                if resp.status_code in _RETRYABLE_STATUS:
                    wait = min(2 ** attempt * 2, 10)
                    logger.warning(
                        "S2 %d for %s, retry in %ds (%d/%d)",
                        resp.status_code, url, wait, attempt + 1, max_retries,
                    )
                    time.sleep(wait)
                    last_exc = requests.exceptions.HTTPError(
                        f"status {resp.status_code}", response=resp,
                    )
                    continue
                resp.raise_for_status()
                return resp
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                wait = min(2 ** attempt * 2, 10)
                logger.warning(
                    "S2 network error for %s, retry in %ds (%d/%d): %s",
                    url, wait, attempt + 1, max_retries, e,
                )
                time.sleep(wait)
                last_exc = e
                continue
            except Exception as e:
                last_exc = e
                break
        if last_exc:
            raise last_exc
        return None

    def _search_paper_id_by_title(self, title: str) -> Optional[str]:
        """제목으로 논문 ID 검색"""
        try:
            api_url = f"{self.base_url}/paper/search"
            params = {
                'query': title,
                'limit': 1,
                'fields': 'paperId'
            }

            response = self._request_with_retry(api_url, params=params)
            if response is None:
                return None

            data = response.json()
            if data.get('data') and len(data['data']) > 0:
                return data['data'][0]['paperId']

            return None

        except Exception as e:
            logger.warning("Paper ID search by title failed: %s", e)
            return None

    def _fetch_references_from_semantic_scholar(self, paper_id: str, max_references: int) -> List[Dict[str, Any]]:
        """Semantic Scholar API에서 참고문헌 가져오기"""
        try:
            api_url = f"{self.base_url}/paper/{paper_id}/references"

            # -1이면 제약 없이 모든 참고문헌 수집 (최대 1000개)
            limit = 1000 if max_references == -1 else max_references

            params = {
                'limit': limit,
                'fields': 'title,authors,year,citationCount,abstract,url'
            }

            response = self._request_with_retry(api_url, params=params)
            if response is None:
                return []

            data = response.json()
            references = []

            for ref_data in data.get('data', []):
                if ref_data.get('citedPaper'):
                    cited_paper = ref_data['citedPaper']
                    references.append({
                        "title": cited_paper.get('title', ''),
                        "authors": [author.get('name', '') for author in cited_paper.get('authors', [])],
                        "year": str(cited_paper.get('year', '')),
                        "citations": cited_paper.get('citationCount', 0),
                        "abstract": cited_paper.get('abstract', ''),
                        "url": cited_paper.get('url', ''),
                        "source": "Reference (via Semantic Scholar)",
                        "paper_id": cited_paper.get('paperId', '')
                    })

            return references

        except Exception as e:
            logger.warning("Semantic Scholar reference fetch failed for %s: %s", paper_id, e)
            return []

    def _enrich_reference(self, reference: Dict[str, Any], parent_paper: Dict[str, Any]) -> Dict[str, Any]:
        """참고문헌 정보 보강"""
        reference['reference_type'] = 'citation'
        reference['parent_paper_title'] = parent_paper.get('title', '')
        reference['parent_paper_source'] = parent_paper.get('source', '')
        return reference

    @log_search_operation("Citation Collection")
    def get_citations(self, paper: Dict[str, Any], max_citations: int = 20) -> List[Dict[str, Any]]:
        """논문을 인용한 논문(citations) 수집 — Semantic Scholar /paper/{id}/citations 엔드포인트 사용.

        Args:
            paper: 대상 논문 dict (doi, arxiv_id, title 등 포함)
            max_citations: 최대 인용 수

        Returns:
            인용 논문 리스트 (title, authors, year, citationCount, abstract, url, externalIds, isInfluential 포함)
        """
        paper_id = self._extract_paper_id(paper)
        if not paper_id:
            return []

        citations = self._fetch_citations_from_semantic_scholar(paper_id, max_citations)
        return [self._enrich_reference(cit, paper) for cit in citations]

    def _fetch_citations_from_semantic_scholar(self, paper_id: str, max_citations: int) -> List[Dict[str, Any]]:
        """Semantic Scholar API에서 인용(citation) 논문 가져오기."""
        try:
            api_url = f"{self.base_url}/paper/{paper_id}/citations"

            limit = 1000 if max_citations == -1 else max_citations

            params = {
                'limit': limit,
                'fields': 'title,authors,year,citationCount,abstract,url,externalIds,isInfluential'
            }

            response = self._request_with_retry(api_url, params=params)
            if response is None:
                return []

            data = response.json()
            citations: List[Dict[str, Any]] = []

            for cit_data in data.get('data', []):
                citing_paper = cit_data.get('citingPaper')
                if not citing_paper:
                    continue

                external_ids = citing_paper.get('externalIds') or {}
                citations.append({
                    "title": citing_paper.get('title', ''),
                    "authors": [author.get('name', '') for author in citing_paper.get('authors', [])],
                    "year": str(citing_paper.get('year', '')),
                    "citations": citing_paper.get('citationCount', 0),
                    "abstract": citing_paper.get('abstract', ''),
                    "url": citing_paper.get('url', ''),
                    "externalIds": external_ids,
                    "isInfluential": cit_data.get('isInfluential', False),
                    "source": "Citation (via Semantic Scholar)",
                    "paper_id": citing_paper.get('paperId', ''),
                    "doi": external_ids.get('DOI', ''),
                    "arxiv_id": external_ids.get('ArXiv', ''),
                })

            return citations

        except Exception as e:
            logger.warning("Semantic Scholar citation fetch failed for %s: %s", paper_id, e)
            return []

    @log_search_operation("Batch Reference Collection")
    def collect_references_batch(self, papers: List[Dict[str, Any]], max_references_per_paper: int = 10, delay: float = 1.0) -> Dict[str, List[Dict[str, Any]]]:
        """
        여러 논문의 참고문헌을 일괄 수집

        Args:
            papers: 논문 리스트
            max_references_per_paper: 논문당 최대 참고문헌 수
            delay: 요청 간 대기 시간 (초)

        Returns:
            논문별 참고문헌 딕셔너리
        """
        all_references = {}

        for i, paper in enumerate(papers):
            print(f"  [{i+1}/{len(papers)}] {paper.get('title', 'Unknown')[:50]}... 참고문헌 수집 중")

            references = self.get_references(paper, max_references_per_paper)

            if references:
                paper_key = paper.get('title', f'paper_{i}')
                all_references[paper_key] = references
                print(f"    → {len(references)}개 참고문헌 발견")
            else:
                print("    → 참고문헌 없음")

            # API 제한 방지를 위한 대기
            if i < len(papers) - 1:
                time.sleep(delay)

        return all_references

    def get_citation_network(self, paper: Dict[str, Any], depth: int = 1, max_per_level: int = 5) -> Dict[str, Any]:
        """
        논문의 인용 네트워크 구축 (재귀적으로 참고문헌의 참고문헌도 수집)

        Args:
            paper: 시작 논문
            depth: 탐색 깊이
            max_per_level: 레벨당 최대 논문 수

        Returns:
            인용 네트워크 정보
        """
        if depth <= 0:
            return {"paper": paper, "references": []}

        references = self.get_references(paper, max_per_level)

        network = {
            "paper": paper,
            "references": references,
            "reference_networks": []
        }

        # 재귀적으로 참고문헌의 참고문헌 수집
        if depth > 1:
            for ref in references[:max_per_level]:
                time.sleep(0.5)  # API 제한 방지
                sub_network = self.get_citation_network(ref, depth - 1, max_per_level)
                network["reference_networks"].append(sub_network)

        return network
