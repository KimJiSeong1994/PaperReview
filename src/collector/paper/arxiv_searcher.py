"""
arXiv 전용 검색 클라이언트
arxiv 패키지를 활용한 직접 검색
"""

import arxiv
from typing import List, Dict, Any, Optional
from datetime import datetime
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from utils.logger import log_arxiv_search, log_performance

class ArxivSearcher:
    """arXiv 직접 검색 클라이언트"""
    
    def __init__(self):
        import ssl
        import urllib3
        
        # SSL 검증 완전 비활성화 (macOS 보안 정책 우회)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # SSL 컨텍스트 수정
        try:
            _create_unverified_https_context = ssl._create_unverified_context
        except AttributeError:
            pass
        else:
            ssl._create_default_https_context = _create_unverified_https_context
        
        self.client = arxiv.Client()
    
    @log_arxiv_search
    def search(self, query: str, max_results: int = 10, sort_by: str = "relevance") -> List[Dict[str, Any]]:
        """
        arXiv에서 논문 검색
        
        Args:
            query: 검색 쿼리
            max_results: 최대 결과 수
            sort_by: 정렬 기준 (relevance, lastUpdatedDate, submittedDate)
            
        Returns:
            논문 정보 리스트
        """
        try:
            # 정렬 기준 설정
            sort_criterion = arxiv.SortCriterion.SubmittedDate
            if sort_by == "relevance":
                sort_criterion = arxiv.SortCriterion.Relevance
            elif sort_by == "lastUpdatedDate":
                sort_criterion = arxiv.SortCriterion.LastUpdatedDate
            
            # 검색 실행
            search = arxiv.Search(query=query, max_results=max_results, sort_by=sort_criterion)
            return [self._extract_paper_info(result) for result in self.client.results(search)]
            
        except Exception as e:
            print(f"[arXiv] Error searching: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    @log_arxiv_search
    def search_by_category(self, category: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        카테고리별 논문 검색
        
        Args:
            category: arXiv 카테고리 (예: cs.AI, cs.LG, stat.ML)
            max_results: 최대 결과 수
            
        Returns:
            논문 정보 리스트
        """
        try:
            query = f"cat:{category}"
            return self.search(query, max_results)
            
        except Exception:
            return []
    
    @log_arxiv_search
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
            query = f"au:{author}"
            return self.search(query, max_results)
            
        except Exception:
            return []
    
    @log_arxiv_search
    def get_recent_papers(self, category: str = None, days: int = 7, max_results: int = 20) -> List[Dict[str, Any]]:
        """
        최근 논문 검색
        
        Args:
            category: 카테고리 (선택사항)
            days: 최근 며칠간의 논문
            max_results: 최대 결과 수
            
        Returns:
            논문 정보 리스트
        """
        try:
            from datetime import timedelta
            
            # 날짜 범위 설정
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # 쿼리 구성
            date_query = f"submittedDate:[{start_date.strftime('%Y%m%d')}0000 TO {end_date.strftime('%Y%m%d')}2359]"
            
            if category:
                query = f"cat:{category} AND {date_query}"
            else:
                query = date_query
            
            return self.search(query, max_results, sort_by="submittedDate")
            
        except Exception:
            return []
    
    def _extract_paper_info(self, result: arxiv.Result) -> Dict[str, Any]:
        """arXiv 결과에서 논문 정보 추출"""
        try:
            return {
                "title": result.title,
                "authors": [author.name for author in result.authors],
                "abstract": result.summary,
                "url": result.entry_id,
                "pdf_url": result.pdf_url,
                "published_date": result.published.strftime('%Y-%m-%d') if result.published else "",
                "updated_date": result.updated.strftime('%Y-%m-%d') if result.updated else "",
                "source": "arXiv",
                "arxiv_id": result.get_short_id(),
                "categories": result.categories,
                "doi": result.doi if hasattr(result, 'doi') else "",
                "comment": result.comment if hasattr(result, 'comment') else "",
                "journal_ref": result.journal_ref if hasattr(result, 'journal_ref') else ""
            }
        except Exception:
            return {
                "title": str(result.title) if result.title else "",
                "authors": [],
                "abstract": str(result.summary) if result.summary else "",
                "url": str(result.entry_id) if result.entry_id else "",
                "pdf_url": str(result.pdf_url) if result.pdf_url else "",
                "published_date": "",
                "updated_date": "",
                "source": "arXiv",
                "arxiv_id": "",
                "categories": [],
                "doi": "",
                "comment": "",
                "journal_ref": ""
            }
    
    def get_categories(self) -> List[Dict[str, str]]:
        """사용 가능한 카테고리 목록 반환"""
        return [
            {"code": "cs.AI", "name": "Artificial Intelligence"},
            {"code": "cs.LG", "name": "Machine Learning"},
            {"code": "cs.CV", "name": "Computer Vision"},
            {"code": "cs.NLP", "name": "Natural Language Processing"},
            {"code": "cs.CL", "name": "Computation and Language"},
            {"code": "cs.IR", "name": "Information Retrieval"},
            {"code": "cs.DL", "name": "Digital Libraries"},
            {"code": "cs.HC", "name": "Human-Computer Interaction"},
            {"code": "cs.CY", "name": "Computers and Society"},
            {"code": "cs.CR", "name": "Cryptography and Security"},
            {"code": "cs.DS", "name": "Data Structures and Algorithms"},
            {"code": "cs.DB", "name": "Databases"},
            {"code": "cs.DC", "name": "Distributed, Parallel, and Cluster Computing"},
            {"code": "cs.GL", "name": "General Literature"},
            {"code": "cs.GR", "name": "Graphics"},
            {"code": "cs.AR", "name": "Hardware Architecture"},
            {"code": "cs.LO", "name": "Logic in Computer Science"},
            {"code": "cs.MS", "name": "Mathematical Software"},
            {"code": "cs.MA", "name": "Multiagent Systems"},
            {"code": "cs.MM", "name": "Multimedia"},
            {"code": "cs.NI", "name": "Networking and Internet Architecture"},
            {"code": "cs.NE", "name": "Neural and Evolutionary Computing"},
            {"code": "cs.NA", "name": "Numerical Analysis"},
            {"code": "cs.OS", "name": "Operating Systems"},
            {"code": "cs.OH", "name": "Other Computer Science"},
            {"code": "cs.PF", "name": "Performance"},
            {"code": "cs.PL", "name": "Programming Languages"},
            {"code": "cs.RO", "name": "Robotics"},
            {"code": "cs.SE", "name": "Software Engineering"},
            {"code": "cs.SD", "name": "Sound"},
            {"code": "cs.SC", "name": "Symbolic Computation"},
            {"code": "cs.SY", "name": "Systems and Control"},
            {"code": "stat.ML", "name": "Machine Learning (Statistics)"},
            {"code": "stat.AP", "name": "Applications"},
            {"code": "stat.CO", "name": "Computation"},
            {"code": "stat.ME", "name": "Methodology"},
            {"code": "stat.OT", "name": "Other Statistics"},
            {"code": "stat.TH", "name": "Statistics Theory"}
        ]
