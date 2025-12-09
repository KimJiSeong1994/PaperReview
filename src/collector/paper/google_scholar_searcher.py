"""
Google Scholar 검색 클라이언트 (Enhanced)
웹 스크래핑을 통한 Google Scholar 검색

강화된 기능:
- 다중 쿼리 전략
- 제목 정확 매칭
- 쿼리 최적화
- 결과 병합 및 중복 제거
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional, Set
import time
import re
import urllib.parse
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from utils.logger import log_search_operation, logger

class GoogleScholarSearcher:
    """Google Scholar 검색 클라이언트 (Enhanced)"""
    
    def __init__(self):
        import ssl
        import urllib3
        
        # SSL 검증 완전 비활성화 (macOS 보안 정책 우회)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        try:
            _create_unverified_https_context = ssl._create_unverified_context
        except AttributeError:
            pass
        else:
            ssl._create_default_https_context = _create_unverified_https_context
        
        self.base_url = "https://scholar.google.com"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        # SSL 검증 비활성화
        self.session.verify = False
        
        # 요청 간 딜레이 (Rate limiting 방지)
        self.request_delay = 1.0
        self.last_request_time = 0
    
    def _rate_limit(self):
        """Rate limiting을 위한 요청 간 딜레이"""
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self.last_request_time = time.time()
    
    def _extract_keywords(self, query: str) -> List[str]:
        """쿼리에서 핵심 키워드 추출"""
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                     'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
                     'as', 'it', 'its', 'this', 'that', 'these', 'those', 'can', 'will',
                     'using', 'based', 'via', 'through', 'into', 'over', 'under'}
        
        # 소문자로 변환하고 특수문자 제거
        query_clean = re.sub(r'[^\w\s\-]', ' ', query.lower())
        words = query_clean.split()
        keywords = [w for w in words if w not in stopwords and len(w) > 2]
        return keywords
    
    def _build_optimized_query(self, query: str, search_type: str = "default") -> str:
        """최적화된 검색 쿼리 생성"""
        if search_type == "exact":
            # 정확한 구문 검색
            return f'"{query}"'
        
        elif search_type == "title":
            # 제목에서 검색
            return f'allintitle: {query}'
        
        elif search_type == "keywords":
            # 키워드 기반 검색
            keywords = self._extract_keywords(query)
            if keywords:
                return " ".join(keywords[:5])  # 상위 5개 키워드
            return query
        
        else:  # default
            return query
    
    @log_search_operation("Google Scholar")
    def search(self, query: str, max_results: int = 10, sort_by: str = "relevance") -> List[Dict[str, Any]]:
        """
        Google Scholar에서 논문 검색 (Enhanced)
        
        Args:
            query: 검색 쿼리
            max_results: 최대 결과 수
            sort_by: 정렬 기준 (relevance, date)
            
        Returns:
            논문 정보 리스트
        """
        try:
            self._rate_limit()
            
            # 검색 URL 구성
            search_url = f"{self.base_url}/scholar"
            params = {
                'q': query,
                'hl': 'en',
                'as_sdt': '0,5'
            }
            
            # 정렬 기준 추가
            if sort_by == "date":
                params['scisbd'] = '1'  # 날짜순 정렬
            
            response = self.session.get(search_url, params=params, timeout=15)
            response.raise_for_status()
            
            # 검색 결과 파싱
            papers = self._parse_search_results(response.text, max_results)
            
            # 결과가 부족하면 추가 검색 시도
            if len(papers) < max_results // 2:
                additional = self.enhanced_search(query, max_results=max_results - len(papers))
                # 중복 제거 후 병합
                seen_titles = {p['title'].lower() for p in papers}
                for paper in additional:
                    if paper['title'].lower() not in seen_titles:
                        papers.append(paper)
                        seen_titles.add(paper['title'].lower())
            
            return papers[:max_results]
            
        except Exception as e:
            logger.error(f"Google Scholar 검색 중 오류 발생: {e}")
            return []
    
    @log_search_operation("Google Scholar Enhanced")
    def enhanced_search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        향상된 다중 전략 검색
        
        여러 검색 전략을 조합하여 더 포괄적인 결과 제공
        """
        all_results: List[Dict[str, Any]] = []
        seen_titles: Set[str] = set()
        
        try:
            # 다양한 검색 전략
            strategies = [
                ("keywords", max_results // 2),  # 키워드 기반
                ("title", max_results // 2),     # 제목 검색
            ]
            
            for strategy, limit in strategies:
                try:
                    self._rate_limit()
                    
                    optimized_query = self._build_optimized_query(query, strategy)
                    search_url = f"{self.base_url}/scholar"
                    params = {
                        'q': optimized_query,
                        'hl': 'en',
                        'as_sdt': '0,5'
                    }
                    
                    response = self.session.get(search_url, params=params, timeout=15)
                    response.raise_for_status()
                    
                    papers = self._parse_search_results(response.text, limit)
                    
                    for paper in papers:
                        title_lower = paper['title'].lower()
                        if title_lower not in seen_titles:
                            seen_titles.add(title_lower)
                            all_results.append(paper)
                    
                except Exception as e:
                    logger.warning(f"Strategy '{strategy}' failed: {e}")
                    continue
                
                # 충분한 결과가 있으면 조기 종료
                if len(all_results) >= max_results:
                    break
            
            return all_results[:max_results]
            
        except Exception as e:
            logger.error(f"Enhanced search error: {e}")
            return []
    
    @log_search_operation("Google Scholar Title")
    def search_by_title(self, title: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        논문 제목으로 정확한 검색
        
        Args:
            title: 논문 제목
            max_results: 최대 결과 수
            
        Returns:
            논문 정보 리스트
        """
        try:
            results = []
            
            # 1. 정확한 제목 검색
            self._rate_limit()
            exact_query = f'allintitle: "{title}"'
            search_url = f"{self.base_url}/scholar"
            params = {'q': exact_query, 'hl': 'en', 'as_sdt': '0,5'}
            
            response = self.session.get(search_url, params=params, timeout=15)
            response.raise_for_status()
            results.extend(self._parse_search_results(response.text, max_results))
            
            # 2. 결과가 없으면 키워드 기반 검색
            if not results:
                self._rate_limit()
                keywords = self._extract_keywords(title)
                if keywords:
                    keyword_query = " ".join(keywords[:4])
                    params = {'q': keyword_query, 'hl': 'en', 'as_sdt': '0,5'}
                    
                    response = self.session.get(search_url, params=params, timeout=15)
                    response.raise_for_status()
                    results.extend(self._parse_search_results(response.text, max_results))
            
            return results[:max_results]
            
        except Exception as e:
            logger.error(f"Title search error: {e}")
            return []
    
    def search_by_author(self, author: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        저자별 논문 검색
        
        Args:
            author: 저자 이름
            max_results: 최대 결과 수
            
        Returns:
            논문 정보 리스트
        """
        query = f'author:"{author}"'
        return self.search(query, max_results)
    
    def search_by_year(self, query: str, year: int, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        특정 연도 논문 검색
        
        Args:
            query: 검색 쿼리
            year: 연도
            max_results: 최대 결과 수
            
        Returns:
            논문 정보 리스트
        """
        query_with_year = f'{query} after:{year} before:{year+1}'
        return self.search(query_with_year, max_results)
    
    def get_cited_by(self, paper_url: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        특정 논문을 인용한 논문들 가져오기
        
        Args:
            paper_url: 논문 URL
            max_results: 최대 결과 수
            
        Returns:
            인용 논문 리스트
        """
        try:
            # Cited by 링크 찾기
            response = self.session.get(paper_url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Cited by 링크 찾기
            cited_by_link = soup.find('a', string=re.compile(r'Cited by'))
            if not cited_by_link:
                return []
            
            cited_by_url = urllib.parse.urljoin(self.base_url, cited_by_link.get('href', ''))
            
            # Cited by 페이지 접근
            cited_response = self.session.get(cited_by_url, timeout=10)
            cited_response.raise_for_status()
            
            return self._parse_search_results(cited_response.text, max_results)
            
        except Exception as e:
            logger.error(f"인용 논문 가져오기 오류: {e}")
            return []
    
    def get_related_articles(self, paper_url: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        관련 논문 가져오기
        
        Args:
            paper_url: 논문 URL
            max_results: 최대 결과 수
            
        Returns:
            관련 논문 리스트
        """
        try:
            # Related articles 링크 찾기
            response = self.session.get(paper_url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Related articles 링크 찾기
            related_link = soup.find('a', string=re.compile(r'Related articles'))
            if not related_link:
                return []
            
            related_url = urllib.parse.urljoin(self.base_url, related_link.get('href', ''))
            
            # Related articles 페이지 접근
            related_response = self.session.get(related_url, timeout=10)
            related_response.raise_for_status()
            
            return self._parse_search_results(related_response.text, max_results)
            
        except Exception as e:
            logger.error(f"관련 논문 가져오기 오류: {e}")
            return []
    
    def _parse_search_results(self, html_content: str, max_results: int) -> List[Dict[str, Any]]:
        """검색 결과 HTML 파싱"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            papers = []
            
            # 검색 결과 요소 찾기
            result_elements = soup.find_all('div', class_='gs_ri')
            
            for element in result_elements[:max_results]:
                paper_info = self._extract_paper_from_element(element)
                if paper_info:
                    papers.append(paper_info)
            
            return papers
            
        except Exception as e:
            logger.error(f"검색 결과 파싱 오류: {e}")
            return []
    
    def _extract_paper_from_element(self, element) -> Optional[Dict[str, Any]]:
        """HTML 요소에서 논문 정보 추출"""
        try:
            # 제목 추출
            title_elem = element.find('h3', class_='gs_rt')
            title = ""
            url = ""
            if title_elem:
                title_link = title_elem.find('a')
                if title_link:
                    title = title_link.get_text(separator=' ', strip=True)
                    url = title_link.get('href', '')
                else:
                    title = title_elem.get_text(separator=' ', strip=True)
            
            # 저자 및 출판 정보 추출
            authors_elem = element.find('div', class_='gs_a')
            authors = []
            journal = ""
            year = ""
            if authors_elem:
                authors_text = authors_elem.get_text(separator=' ')
                # 저자 파싱 (일반적으로 첫 번째 부분이 저자)
                parts = authors_text.split(' - ')
                if parts:
                    authors_part = parts[0]
                    authors = [author.strip() for author in authors_part.split(',')]
                    
                    # 출판 정보에서 저널과 연도 추출
                    if len(parts) > 1:
                        journal_part = parts[1]
                        # 연도 추출
                        year_match = re.search(r'\b(19|20)\d{2}\b', journal_part)
                        if year_match:
                            year = year_match.group()
                        journal = journal_part
            
            # 초록 추출
            abstract_elem = element.find('div', class_='gs_rs')
            abstract = abstract_elem.get_text(separator=' ', strip=True) if abstract_elem else ""
            
            # 인용 수 추출
            citations_elem = element.find('a', string=re.compile(r'Cited by'))
            citations = 0
            if citations_elem:
                citations_text = citations_elem.get_text()
                citations_match = re.search(r'(\d+)', citations_text)
                if citations_match:
                    citations = int(citations_match.group(1))
            
            # PDF 링크 추출
            pdf_link = element.find('a', string='[PDF]')
            pdf_url = pdf_link.get('href', '') if pdf_link else ""
            
            # DOI 추출 (초록에서)
            doi = ""
            doi_match = re.search(r'doi\.org/([^\s]+)', abstract)
            if doi_match:
                doi = doi_match.group(1)
            
            return {
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "url": url,
                "pdf_url": pdf_url,
                "journal": journal,
                "year": year,
                "citations": citations,
                "doi": doi,
                "source": "Google Scholar"
            }
            
        except Exception as e:
            logger.error(f"논문 정보 추출 오류: {e}")
            return None
    
    def search_with_filters(self, query: str, year_start: int = None, year_end: int = None, 
                          author: str = None, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        필터를 적용한 검색
        
        Args:
            query: 검색 쿼리
            year_start: 시작 연도
            year_end: 종료 연도
            author: 저자
            max_results: 최대 결과 수
            
        Returns:
            논문 정보 리스트
        """
        try:
            # 검색 쿼리 구성
            search_query = query
            
            if author:
                search_query += f' author:"{author}"'
            
            if year_start and year_end:
                search_query += f' after:{year_start-1} before:{year_end+1}'
            elif year_start:
                search_query += f' after:{year_start-1}'
            elif year_end:
                search_query += f' before:{year_end+1}'
            
            return self.search(search_query, max_results)
            
        except Exception as e:
            logger.error(f"필터 검색 중 오류 발생: {e}")
            return []
    
    def get_author_profile(self, author_name: str) -> Optional[Dict[str, Any]]:
        """
        저자 프로필 정보 가져오기
        
        Args:
            author_name: 저자 이름
            
        Returns:
            저자 프로필 정보
        """
        try:
            # 저자 검색
            search_url = f"{self.base_url}/citations"
            params = {
                'mauthors': author_name,
                'hl': 'en'
            }
            
            response = self.session.get(search_url, params=params, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 저자 프로필 정보 추출
            profile_elem = soup.find('div', class_='gsc_vcd')
            if not profile_elem:
                return None
            
            # 저자 이름
            name_elem = profile_elem.find('h3', class_='gsc_oai_name')
            name = name_elem.get_text(strip=True) if name_elem else author_name
            
            # 소속
            affiliation_elem = profile_elem.find('div', class_='gsc_oai_aff')
            affiliation = affiliation_elem.get_text(strip=True) if affiliation_elem else ""
            
            # 연구 분야
            interests_elem = profile_elem.find('div', class_='gsc_oai_int')
            interests = []
            if interests_elem:
                interests = [interest.strip() for interest in interests_elem.get_text().split(',')]
            
            # 인용 통계
            stats_elem = profile_elem.find('table', class_='gsc_rsb_st')
            citations = 0
            h_index = 0
            i10_index = 0
            
            if stats_elem:
                rows = stats_elem.find_all('tr')
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 2:
                        label = cells[0].get_text(strip=True)
                        value = cells[1].get_text(strip=True)
                        
                        if 'Citations' in label:
                            citations = int(re.sub(r'[^\d]', '', value)) if re.search(r'\d', value) else 0
                        elif 'h-index' in label:
                            h_index = int(re.sub(r'[^\d]', '', value)) if re.search(r'\d', value) else 0
                        elif 'i10-index' in label:
                            i10_index = int(re.sub(r'[^\d]', '', value)) if re.search(r'\d', value) else 0
            
            return {
                "name": name,
                "affiliation": affiliation,
                "interests": interests,
                "total_citations": citations,
                "h_index": h_index,
                "i10_index": i10_index,
                "source": "Google Scholar"
            }
            
        except Exception as e:
            logger.error(f"저자 프로필 가져오기 오류: {e}")
            return None
