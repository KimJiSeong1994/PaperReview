"""
Connected Papers 검색 클라이언트
Connected Papers는 JavaScript 기반 SPA이므로 대안적 접근 방식 사용
"""

import requests
from typing import List, Dict, Any, Optional
import time
import json
import re
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from utils.logger import log_search_operation

class ConnectedPapersSearcher:
    """Connected Papers 검색 클라이언트 (대안적 접근)"""
    
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
        
        self.base_url = "https://www.connectedpapers.com"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        # SSL 검증 비활성화
        self.session.verify = False
    
    @log_search_operation("Connected Papers")
    def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Connected Papers 대안 검색 (Semantic Scholar API 사용)
        Connected Papers는 SPA 구조로 직접 스크래핑이 어려움
        
        Args:
            query: 검색 쿼리
            max_results: 최대 결과 수
            
        Returns:
            논문 정보 리스트
        """
        try:
            # Semantic Scholar API 사용
            papers = self._search_semantic_scholar(query, max_results)
            return papers
            
        except Exception:
            return []
    
    def get_paper_details(self, paper_id: str) -> Optional[Dict[str, Any]]:
        """
        특정 논문의 상세 정보 가져오기 (Semantic Scholar API 사용)
        
        Args:
            paper_id: 논문 ID
            
        Returns:
            논문 상세 정보
        """
        try:
            if paper_id.startswith('ss_'):
                actual_id = paper_id[3:]  # ss_ 제거
                
                api_url = f"https://api.semanticscholar.org/graph/v1/paper/{actual_id}"
                params = {
                    'fields': 'title,authors,year,citationCount,abstract,url,fieldsOfStudy'
                }
                
                response = self.session.get(api_url, params=params, timeout=10)
                response.raise_for_status()
                
                paper_data = response.json()
                
                return {
                    "title": paper_data.get('title', ''),
                    "authors": [author.get('name', '') for author in paper_data.get('authors', [])],
                    "abstract": paper_data.get('abstract', ''),
                    "doi": paper_data.get('doi', ''),
                    "citations": paper_data.get('citationCount', 0),
                    "year": str(paper_data.get('year', '')),
                    "fields": paper_data.get('fieldsOfStudy', []),
                    "source": "Connected Papers (via Semantic Scholar)"
                }
            
            return None
            
        except Exception:
            return None
    
    def get_related_papers(self, paper_id: str) -> List[Dict[str, Any]]:
        """
        관련 논문 가져오기 (Semantic Scholar API 사용)
        
        Args:
            paper_id: 논문 ID
            
        Returns:
            관련 논문 리스트
        """
        try:
            # Semantic Scholar API를 통한 관련 논문 검색
            if paper_id.startswith('ss_'):
                actual_id = paper_id[3:]  # ss_ 제거
                
                api_url = f"https://api.semanticscholar.org/graph/v1/paper/{actual_id}/citations"
                params = {
                    'limit': 10,
                    'fields': 'title,authors,year,citationCount,abstract,url'
                }
                
                response = self.session.get(api_url, params=params, timeout=10)
                response.raise_for_status()
                
                data = response.json()
                related_papers = []
                
                for citation in data.get('data', []):
                    if citation.get('citingPaper'):
                        paper = citation['citingPaper']
                        related_papers.append({
                            "title": paper.get('title', ''),
                            "authors": [author.get('name', '') for author in paper.get('authors', [])],
                            "year": str(paper.get('year', '')),
                            "citations": paper.get('citationCount', 0),
                            "abstract": paper.get('abstract', ''),
                            "doi": paper.get('doi', ''),
                            "url": paper.get('url', ''),
                            "connected_papers_id": f"ss_{paper.get('paperId', '')}",
                            "source": "Connected Papers (via Semantic Scholar)"
                        })
                
                return related_papers
            
            return []
            
        except Exception:
            return []
    
    def _search_semantic_scholar(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Semantic Scholar API를 통한 논문 검색"""
        try:
            # Semantic Scholar API 사용
            api_url = "https://api.semanticscholar.org/graph/v1/paper/search"
            params = {
                'query': query,
                'limit': max_results,
                'fields': 'title,authors,year,citationCount,abstract,url'
            }
            
            response = self.session.get(api_url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            papers = []
            
            for paper_data in data.get('data', []):
                paper_info = {
                    "title": paper_data.get('title', ''),
                    "authors": [author.get('name', '') for author in paper_data.get('authors', [])],
                    "year": str(paper_data.get('year', '')),
                    "citations": paper_data.get('citationCount', 0),
                    "abstract": paper_data.get('abstract', ''),
                    "doi": paper_data.get('doi', ''),
                    "url": paper_data.get('url', ''),
                    "source": "Connected Papers (via Semantic Scholar)",
                    "connected_papers_id": f"ss_{paper_data.get('paperId', '')}"
                }
                papers.append(paper_info)
            
            return papers
            
        except Exception:
            return []
    
    def search_by_topic(self, topic: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        주제별 논문 검색
        
        Args:
            topic: 주제
            max_results: 최대 결과 수
            
        Returns:
            논문 정보 리스트
        """
        return self.search(topic, max_results)
    
    def get_trending_papers(self, category: str = None, max_results: int = 20) -> List[Dict[str, Any]]:
        """
        인기 논문 가져오기 (Semantic Scholar API 사용)
        
        Args:
            category: 카테고리 (선택사항)
            max_results: 최대 결과 수
            
        Returns:
            인기 논문 리스트
        """
        try:
            # Semantic Scholar API를 통한 인기 논문 검색
            api_url = "https://api.semanticscholar.org/graph/v1/paper/search"
            params = {
                'query': 'machine learning' if not category else category,
                'limit': max_results,
                'sort': 'citationCount:desc',
                'fields': 'title,authors,year,citationCount,abstract,url'
            }
            
            response = self.session.get(api_url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            papers = []
            
            for paper_data in data.get('data', []):
                paper_info = {
                    "title": paper_data.get('title', ''),
                    "authors": [author.get('name', '') for author in paper_data.get('authors', [])],
                    "year": str(paper_data.get('year', '')),
                    "citations": paper_data.get('citationCount', 0),
                    "abstract": paper_data.get('abstract', ''),
                    "doi": paper_data.get('doi', ''),
                    "url": paper_data.get('url', ''),
                    "source": "Connected Papers (via Semantic Scholar)",
                    "connected_papers_id": f"ss_{paper_data.get('paperId', '')}"
                }
                papers.append(paper_info)
            
            return papers
            
        except Exception:
            return []