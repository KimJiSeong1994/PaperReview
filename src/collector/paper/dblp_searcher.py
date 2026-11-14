import logging
logger = logging.getLogger(__name__)

"""
DBLP 검색 클라이언트
DBLP REST API를 통한 컴퓨터 과학 논문 검색 (무료, API 키 불필요)
"""

import requests
import time
import json
import os
import re
from typing import List, Dict, Any, Optional

from src.collector.paper.rate_limiter import RateLimiter
from src.utils.logger import log_search_operation
from src.collector.paper.provider_access import ProviderAccessError, access_details


class DBLPSearcher:
    """DBLP API 검색 클라이언트"""

    # Class-level: throttling is per-upstream, not per-instance. See
    # OpenAlexSearcher for the rationale.
    _rate_limiter = RateLimiter(1.0)

    def __init__(self):
        self.base_url = "https://dblp.org/search/publ/api"
        self.sparql_url = "https://sparql.dblp.org/sparql"
        self.backend = os.getenv("DBLP_SEARCH_BACKEND", "auto")
        if self.backend not in {"auto", "rest", "sparql"}:
            raise ValueError("DBLP_SEARCH_BACKEND must be auto, rest or sparql")
        self._rest_challenged = False
        self._access_issue = None
        self._access_until = 0.0
        self.headers = {
            'User-Agent': 'PaperReviewAgent/1.0',
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

    def _check_access(self):
        if self._access_issue and time.monotonic() < self._access_until:
            raise ProviderAccessError('dblp', self._access_issue['reason'],
                                      http_status=self._access_issue.get('http_status'), retry_after=self._access_until-time.monotonic())

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
    def search(self, query: str, max_results: int = 10, *, deadline=None, stop_event=None) -> List[Dict[str, Any]]:
        """
        DBLP API를 통한 논문 검색

        Args:
            query: 검색 쿼리
            max_results: 최대 결과 수

        Returns:
            논문 정보 리스트
        """
        try:
            original_query = query
            if (stop_event is not None and stop_event.is_set()) or (deadline is not None and time.monotonic() >= deadline):
                raise TimeoutError("DBLP search budget expired")
            self._check_access()
            if self.backend == "sparql" or (self.backend == "auto" and self._rest_challenged):
                return self._search_sparql(original_query, max_results, deadline=deadline, stop_event=stop_event)
            self._rate_limit()
            if (stop_event is not None and stop_event.is_set()) or (deadline is not None and time.monotonic() >= deadline):
                raise TimeoutError("DBLP search budget expired during rate limiting")

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

            timeout = min(15.0, deadline - time.monotonic()) if deadline is not None else 15.0
            if timeout <= 0:
                raise TimeoutError("DBLP search budget expired before transport")
            response = self.session.get(self.base_url, params=params, timeout=timeout)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if response.status_code == 202 or (isinstance(content_type, str) and "text/html" in content_type.lower()):
                # The website's challenge is not JSON and must not be solved by
                # this client. Use DBLP's separately documented public data API.
                self._rest_challenged = True
                response.close()
                if self.backend == "rest":
                    self._access_issue = {'reason': 'access_denied', 'http_status': 202}
                    self._access_until = time.monotonic() + 300
                    raise ProviderAccessError("dblp", "access_denied", http_status=202, retry_after=300)
                return self._search_sparql(original_query, max_results, deadline=deadline, stop_event=stop_event)

            data = response.json()
            hits = data.get("result", {}).get("hits", {}).get("hit", [])

            papers = []
            for hit in hits:
                paper = self._extract_paper_info(hit)
                if paper:
                    papers.append(paper)

            return papers[:max_results]

        except ProviderAccessError:
            raise
        except Exception as e:
            details = access_details(e)
            if details:
                self._access_issue = details
                self._access_until = time.monotonic() + details['retry_after_seconds']
            logger.error(f"[DBLP] Search error: {e}")
            raise

    def _search_sparql(self, query, max_results, *, deadline=None, stop_event=None, author=None):
        """Query DBLP's official public KG API, with a bounded result body.

        https://blog.dblp.org/2024/09/09/introducing-our-public-sparql-query-service/
        User input is encoded as SPARQL string literals, never executable syntax.
        """
        def check():
            if (stop_event is not None and stop_event.is_set()) or (deadline is not None and time.monotonic() >= deadline):
                raise TimeoutError("DBLP search budget expired")
            return min(15.0, deadline - time.monotonic()) if deadline is not None else 15.0

        limit = max(1, min(int(max_results), 100))
        value = query.strip()
        exact_title = len(value) >= 2 and value[0] == value[-1] == "$"
        doi = re.fullmatch(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/\S+)", value, re.I)
        if author:
            condition = f'?paper dblp:authoredBy ?person . ?person rdfs:label ?personName . FILTER(CONTAINS(LCASE(STR(?personName)), {json.dumps(author.casefold())}))'
        elif doi:
            target = json.dumps("https://doi.org/" + doi[1].casefold())
            condition = f"?paper dblp:doi ?matchDoi . FILTER(LCASE(STR(?matchDoi)) = {target})"
        elif exact_title:
            target = value[1:-1].strip().casefold().rstrip('.')
            condition = f"FILTER(LCASE(STR(?title)) IN ({json.dumps(target)}, {json.dumps(target + '.')}))"
        else:
            stopwords = {'the', 'a', 'an', 'in', 'on', 'for', 'of', 'with', 'by', 'from', 'and', 'or', 'to', 'is', 'are', 'using', 'based', 'via'}
            terms = list(dict.fromkeys(word for word in re.findall(r"[^\W_]+", value.casefold()) if (len(word) > 1 or word.isdigit()) and word not in stopwords))[:8]
            if not terms:
                return []
            # DBLP has titles, not abstracts. Requiring every synonym introduced
            # by the query planner can force a corpus scan with no matches.
            # Seed on a named model (GraphRAG/BERT) or three topic terms; the
            # complete query still scores the returned candidates below.
            seeds = terms[:3]
            if len(terms) > 3:
                named = [word.casefold() for word in re.findall(r"[^\W_]+", value)
                         if len(word) >= 3 and sum(c.isupper() for c in word) >= 2
                         and word.casefold() in terms]
                if named:
                    seeds = named[:1]
            condition = "FILTER(" + " && ".join(f"CONTAINS(LCASE(STR(?title)), {json.dumps(term, ensure_ascii=False)})" for term in seeds) + ")"
        candidate_limit = limit if doi or exact_title else min(limit * 3, 100)
        sparql = f'''PREFIX dblp: <https://dblp.org/rdf/schema#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?paper ?title ?year ?doi ?venue ?url ?authorName ?ordinal WHERE {{
  {{ SELECT DISTINCT ?paper ?title WHERE {{
      ?paper dblp:title ?title . {condition}
    }} LIMIT {candidate_limit} }}
  OPTIONAL {{ ?paper dblp:yearOfPublication ?year }}
  OPTIONAL {{ ?paper dblp:doi ?doi }}
  OPTIONAL {{ ?paper dblp:publishedInStream/dblp:streamTitle ?venue }}
  OPTIONAL {{ ?paper dblp:primaryDocumentPage ?url }}
  OPTIONAL {{ ?paper dblp:hasSignature ?signature .
    ?signature a dblp:AuthorSignature; dblp:signatureDblpName ?authorName; dblp:signatureOrdinal ?ordinal . }}
}} ORDER BY ?paper ?ordinal'''
        check()
        self._check_access()
        self._rate_limit()
        self._check_access()
        response = self.session.post(self.sparql_url, data=sparql.encode('utf-8'),
                                     headers={'Content-Type': 'application/sparql-query', 'Accept': 'application/sparql-results+json'},
                                     timeout=check(), stream=True)
        try:
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '')
            if response.status_code == 202 or (isinstance(content_type, str) and 'text/html' in content_type.lower()):
                raise ProviderAccessError('dblp', 'access_denied', http_status=response.status_code, retry_after=300)
            payload = bytearray()
            for part in response.iter_content(65536):
                check()
                payload.extend(part)
                if len(payload) > 2 * 1024 * 1024:
                    raise ProviderAccessError('dblp', 'response_size_limit')
            check()
            data = json.loads(payload)
        except requests.HTTPError as error:
            details = access_details(error)
            if details.get('reason') in ('rate_limited', 'access_denied'):
                self._access_issue = details
                self._access_until = time.monotonic() + details.get('retry_after_seconds', 300)
            raise
        finally:
            response.close()
        bindings = data.get('results', {}).get('bindings')
        if not isinstance(bindings, list):
            raise ProviderAccessError('dblp', 'invalid_response')
        papers = {}
        for binding in bindings:
            check()
            if not isinstance(binding, dict):
                raise ProviderAccessError('dblp', 'invalid_response')
            def field(name):
                entry = binding.get(name, {})
                return entry.get('value', '') if isinstance(entry, dict) else ''
            uri = field('paper')
            if not uri.startswith('https://dblp.org/rec/') or not field('title'):
                continue
            if uri not in papers:
                from src.utils.paper_utils import normalize_doi
                doi_value = normalize_doi(field('doi'))
                papers[uri] = {'title': field('title').rstrip('.'), 'authors': [], 'abstract': '',
                               'url': field('url') or (f'https://doi.org/{doi_value}' if doi_value else uri),
                               'pdf_url': '', 'source': 'DBLP', 'year': field('year'), 'citations': 0,
                               'doi': doi_value, 'venue': field('venue'), 'dblp_key': uri.split('/rec/', 1)[1]}
            author = field('authorName')
            if author and author not in papers[uri]['authors']:
                papers[uri]['authors'].append(author)
        if bindings and not papers:
            raise ProviderAccessError('dblp', 'invalid_response')
        query_terms = set(re.findall(r"[^\W_]+", value.casefold()))
        def relevance(paper):
            title_terms = set(re.findall(r"[^\W_]+", paper['title'].casefold()))
            overlap = len(query_terms & title_terms) / max(1, len(title_terms))
            year = str(paper['year'])[:4]
            return (-overlap, -int(year) if year.isdigit() else 0, paper['dblp_key'])
        return sorted(papers.values(), key=relevance)[:limit]

    @log_search_operation("DBLP Title")
    def search_by_title(self, title: str, max_results: int = 5, *, deadline=None, stop_event=None) -> List[Dict[str, Any]]:
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
        return self.search(exact_query, max_results, deadline=deadline, stop_event=stop_event)

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
            if self.backend == 'sparql' or (self.backend == 'auto' and self._rest_challenged):
                return self._search_sparql('', max_results, author=author)
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
            content_type = response.headers.get('Content-Type', '')
            if response.status_code == 202 or (isinstance(content_type, str) and 'text/html' in content_type.lower()):
                self._rest_challenged = True
                response.close()
                if self.backend == 'rest':
                    raise ProviderAccessError('dblp', 'access_denied', http_status=202)
                return self._search_sparql('', max_results, author=author)

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

        except ProviderAccessError:
            raise
        except Exception as e:
            logger.error(f"[DBLP] Author search error: {e}")
            raise
