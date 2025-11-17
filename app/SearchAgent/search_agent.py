from typing import Dict, List, Any, Optional, Union
import concurrent.futures
from datetime import datetime
import json
import sys
import os

# 상위 디렉토리에서 src 모듈 import
sys.path.append(os.path.join(os.path.dirname(__file__), '../../src'))
from collector.paper.arxiv_searcher import ArxivSearcher
from collector.paper.connected_papers_searcher import ConnectedPapersSearcher
from collector.paper.google_scholar_searcher import GoogleScholarSearcher
from collector.paper.reference_collector import ReferenceCollector
from collector.paper.text_extractor import TextExtractor
from collector.paper.similarity_calculator import SimilarityCalculator
from utils.logger import log_search_operation

class SearchAgent:
    def __init__(self, data_dir: str = None, openai_api_key: str = None):
        self.arxiv_searcher = ArxivSearcher()
        self.connected_papers_searcher = ConnectedPapersSearcher()
        self.google_scholar_searcher = GoogleScholarSearcher()
        self.reference_collector = ReferenceCollector()
        self.text_extractor = TextExtractor()
        
        # 유사도 계산기 초기화 (API 키가 있으면)
        try:
            self.similarity_calculator = SimilarityCalculator(api_key=openai_api_key) if openai_api_key or os.getenv('OPENAI_API_KEY') else None
        except Exception:
            self.similarity_calculator = None
        
        self.search_history = []
        
        # 데이터 저장 경로 설정
        if data_dir is None:
            project_root = os.path.join(os.path.dirname(__file__), '../..')
            self.data_dir = os.path.join(project_root, 'data/raw')

        else:
            self.data_dir = data_dir
        
        # 디렉토리 생성
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 논문 저장 파일 경로
        self.papers_file = os.path.join(self.data_dir, 'papers.json')
    
    @log_search_operation("Multi-Source")
    def search_all_sources(self, query: str, max_results_per_source: int = 5) -> Dict[str, List[Dict[str, Any]]]:
        results = {
            "arxiv": [],
            "connected_papers": [],
            "google_scholar": []
        }
        
        # 검색 기록 저장
        self._add_to_history(query, "multi_source")
        
        # 각 소스별 직접 검색 (병렬 처리)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            # 각 검색 작업을 병렬로 실행
            arxiv_future = executor.submit(self.arxiv_searcher.search, query, max_results_per_source)
            connected_papers_future = executor.submit(self.connected_papers_searcher.search, query, max_results_per_source)
            google_scholar_future = executor.submit(self.google_scholar_searcher.search, query, max_results_per_source)
            
            # 결과 수집
            results["arxiv"] = arxiv_future.result()
            results["connected_papers"] = connected_papers_future.result()
            results["google_scholar"] = google_scholar_future.result()
        
        return results
    
    def search_arxiv(self, query: str, max_results: int = 10, sort_by: str = "relevance", category: str = None) -> List[Dict[str, Any]]:
        self._add_to_history(query, "arxiv")
        
        if category: return self.arxiv_searcher.search_by_category(category, max_results)
        else: return self.arxiv_searcher.search(query, max_results, sort_by)
    
    def search_connected_papers(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        self._add_to_history(query, "connected_papers")
        return self.connected_papers_searcher.search(query, max_results)
    
    def search_google_scholar(self, query: str, max_results: int = 10, sort_by: str = "relevance", year_start: int = None, year_end: int = None, author: str = None) -> List[Dict[str, Any]]:       
        self._add_to_history(query, "google_scholar")
        
        if year_start or year_end or author: return self.google_scholar_searcher.search_with_filters(query, year_start, year_end, author, max_results)
        else: return self.google_scholar_searcher.search(query, max_results, sort_by)
    
    def search_by_author(self, author: str, max_results: int = 10) -> Dict[str, List[Dict[str, Any]]]:
        results = {
            "arxiv": [],
            "connected_papers": [],
            "google_scholar": []
        }
        
        self._add_to_history(f"author:{author}", "multi_author")
        
        # 각 소스에서 저자 검색
        results["arxiv"] = self.arxiv_searcher.search_by_author(author, max_results)
        results["google_scholar"] = self.google_scholar_searcher.search_by_author(author, max_results)
        
        # Connected Papers는 저자 검색이 제한적이므로 일반 검색으로 대체
        results["connected_papers"] = self.connected_papers_searcher.search(author, max_results)
        return results
    
    def search_recent_papers(self, category: str = None, days: int = 7, max_results: int = 20) -> List[Dict[str, Any]]:
        self._add_to_history(f"recent:{days}days", "recent")
        return self.arxiv_searcher.get_recent_papers(category, days, max_results)
    
    def get_trending_papers(self, category: str = None, max_results: int = 20) -> List[Dict[str, Any]]:
        self._add_to_history("trending", "trending")
        return self.connected_papers_searcher.get_trending_papers(category, max_results)
    
    def get_paper_details(self, paper_url: str, source: str) -> Optional[Dict[str, Any]]:
        try:
            if source.lower() == "connected_papers": return self.connected_papers_searcher.get_paper_details(paper_url)
            else: return None

        except Exception as e:
            logger.error(f"논문 상세 정보 가져오기 오류: {e}")
            return None
    
    def get_related_papers(self, paper_url: str, source: str, max_results: int = 10) -> List[Dict[str, Any]]:
        try:
            if source.lower() == "connected_papers":
                paper_id = paper_url.split('/')[-1] if '/' in paper_url else paper_url
                return self.connected_papers_searcher.get_related_papers(paper_id)

            elif source.lower() == "google_scholar":
                return self.google_scholar_searcher.get_related_articles(paper_url, max_results)

            else:
                return []

        except Exception as e:
            logger.error(f"관련 논문 가져오기 오류: {e}")
            return []
    
    def get_author_profile(self, author_name: str) -> Optional[Dict[str, Any]]:
        return self.google_scholar_searcher.get_author_profile(author_name)
    
    def get_categories(self) -> Dict[str, List[Dict[str, str]]]:
        return {"arxiv": self.arxiv_searcher.get_categories()}
    
    def search_with_filters(self, query: str, filters: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """
        필터를 적용한 고급 검색
        
        Args:
            query: 검색 쿼리
            filters: 필터 조건
                - sources: 검색할 소스 목록
                - max_results: 최대 결과 수
                - year_start, year_end: 연도 범위
                - author: 저자
                - category: 카테고리 (arXiv)
                - sort_by: 정렬 기준
                
        Returns:
            소스별 검색 결과
        """
        sources = filters.get("sources", ["arxiv", "connected_papers", "google_scholar"])
        max_results = filters.get("max_results", 5)
        
        results = {}
        
        for source in sources:
            if source == "arxiv":
                category = filters.get("category")
                sort_by = filters.get("sort_by", "relevance")
                results["arxiv"] = self.search_arxiv(query, max_results, sort_by, category)
                
            elif source == "connected_papers":
                results["connected_papers"] = self.search_connected_papers(query, max_results)
                
            elif source == "google_scholar":
                year_start = filters.get("year_start")
                year_end = filters.get("year_end")
                author = filters.get("author")
                sort_by = filters.get("sort_by", "relevance")
                results["google_scholar"] = self.search_google_scholar(
                    query, max_results, sort_by, year_start, year_end, author
                )
        
        return results
    
    def get_search_history(self) -> List[Dict[str, Any]]:
        return self.search_history.copy()
    
    def clear_search_history(self):
        self.search_history.clear()
    
    def export_results(self, results: Dict[str, List[Dict[str, Any]]], filename: str = None) -> str:
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"search_results_{timestamp}.json"
        
        # 결과에 메타데이터 추가
        export_data = {
            "timestamp": datetime.now().isoformat(),
            "total_results": sum(len(papers) for papers in results.values()),
            "sources": list(results.keys()),
            "results": results
        }
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            return filename
            
        except Exception:
            return ""
    
    def _add_to_history(self, query: str, search_type: str):
        """검색 기록에 추가"""
        self.search_history.append({
            "query": query,
            "type": search_type,
            "timestamp": datetime.now().isoformat()
        })
    
    def _load_existing_papers(self) -> Dict[str, Dict[str, Any]]:
        """기존 저장된 논문 로드 (중복 제거용)"""
        if not os.path.exists(self.papers_file):
            return {}
        
        try:
            with open(self.papers_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {self._generate_paper_id(paper): paper for paper in data.get('papers', [])}
        except Exception:
            return {}
    
    def _generate_paper_id(self, paper: Dict[str, Any]) -> str:
        """논문 고유 ID 생성 (제목 기반)"""
        title = paper.get('title', '').lower().strip()
        return title[:100] if title else str(hash(str(paper)))
    
    def save_papers(self, results: Dict[str, List[Dict[str, Any]]], query: str = "") -> Dict[str, Any]:
        """
        검색된 논문들을 누적형으로 JSON 파일에 저장
        
        Args:
            results: 검색 결과 (소스별 논문 리스트)
            query: 검색 쿼리
            
        Returns:
            저장 결과 정보 (저장된 수, 중복 수 등)
        """
        # 기존 논문 로드
        existing_papers = self._load_existing_papers()
        
        # 새로운 논문 추가
        new_count = 0
        duplicate_count = 0
        
        for source, papers in results.items():
            for paper in papers:
                # 검색 메타데이터 추가
                paper['collected_at'] = datetime.now().isoformat()
                paper['search_query'] = query
                
                # 고유 ID 생성
                paper_id = self._generate_paper_id(paper)
                
                # 중복 체크
                if paper_id in existing_papers:
                    duplicate_count += 1
                else:
                    existing_papers[paper_id] = paper
                    new_count += 1
        
        # 전체 데이터 저장
        save_data = {
            'metadata': {
                'last_updated': datetime.now().isoformat(),
                'total_papers': len(existing_papers),
                'sources': list(set(paper.get('source', 'Unknown') for paper in existing_papers.values()))
            },
            'papers': list(existing_papers.values())
        }
        
        try:
            with open(self.papers_file, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            
            return {
                'success': True,
                'file': self.papers_file,
                'new_papers': new_count,
                'duplicates': duplicate_count,
                'total_papers': len(existing_papers)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'new_papers': 0,
                'duplicates': 0,
                'total_papers': 0
            }
    
    def get_saved_papers_count(self) -> int:
        """저장된 논문 수 조회"""
        existing_papers = self._load_existing_papers()
        return len(existing_papers)
    
    def clear_saved_papers(self) -> bool:
        """저장된 논문 초기화"""
        try:
            if os.path.exists(self.papers_file):
                os.remove(self.papers_file)
            return True
        except Exception:
            return False
    
    def collect_references(self, max_references_per_paper: int = 10, max_papers: int = None) -> Dict[str, Any]:
        existing_papers = self._load_existing_papers()
        papers_list = list(existing_papers.values())
        
        if max_papers:
            papers_list = papers_list[:max_papers]
        
        print(f'\n📚 {len(papers_list)}개 논문의 참고문헌 수집 시작...')
        
        # 참고문헌 수집 및 각 논문에 추가
        total_references_found = 0
        
        for i, (paper_id, paper) in enumerate(existing_papers.items()):
            if max_papers and i >= max_papers:
                break
            
            # 이미 참고문헌이 있으면 스킵
            if paper.get('references'):
                continue
            
            print(f"  [{i+1}/{min(max_papers or len(existing_papers), len(existing_papers))}] {paper.get('title', 'Unknown')[:50]}... 참고문헌 수집 중")
            
            references = self.reference_collector.get_references(paper, max_references_per_paper)
            
            if references:
                # 유사도 계산 (가능한 경우)
                if self.similarity_calculator:
                    try:
                        print(f"    → 유사도 계산 중...")
                        references = self.similarity_calculator.add_similarity_scores(paper, references)
                        # 유사도 순으로 정렬
                        references.sort(key=lambda x: x.get('similarity_score', 0), reverse=True)
                        print(f"    → 유사도 계산 완료 (최고: {references[0].get('similarity_score', 0):.3f})")
                    except Exception as e:
                        print(f"    → 유사도 계산 실패: {e}")
                
                # 논문에 references 필드 추가
                existing_papers[paper_id]['references'] = references
                total_references_found += len(references)
                print(f"    → {len(references)}개 참고문헌 발견")
            else:
                existing_papers[paper_id]['references'] = []
                print(f"    → 참고문헌 없음")
        
        # 업데이트된 데이터 저장
        save_data = {
            'metadata': {
                'last_updated': datetime.now().isoformat(),
                'total_papers': len(existing_papers),
                'sources': list(set(paper.get('source', 'Unknown') for paper in existing_papers.values()))
            },
            'papers': list(existing_papers.values())
        }
        
        try:
            with open(self.papers_file, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            
            return {
                'papers_processed': min(max_papers or len(papers_list), len(papers_list)),
                'references_found': total_references_found,
                'total_papers': len(existing_papers)
            }
            
        except Exception:
            return {
                'papers_processed': 0,
                'references_found': 0,
            'total_papers': self.get_saved_papers_count()
        }
    
    def extract_full_texts(self, max_papers: int = None) -> Dict[str, Any]:
        """
        저장된 논문들의 본문 추출
        
        Args:
            max_papers: 최대 처리할 논문 수
            
        Returns:
            추출 결과 통계
        """
        # 저장된 논문 로드
        existing_papers = self._load_existing_papers()
        papers_list = list(existing_papers.values())
        
        if max_papers:
            papers_list = papers_list[:max_papers]
        
        print(f'\n📝 {len(papers_list)}개 논문의 본문 추출 시작...')
        
        # 본문 추출
        extract_results = self.text_extractor.extract_batch(papers_list, max_papers)
        
        # 업데이트된 논문 저장
        # papers_list가 참조이므로 자동으로 existing_papers에 반영됨
        save_data = {
            'metadata': {
                'last_updated': datetime.now().isoformat(),
                'total_papers': len(existing_papers),
                'sources': list(set(paper.get('source', 'Unknown') for paper in existing_papers.values()))
            },
            'papers': list(existing_papers.values())
        }
        
        try:
            with open(self.papers_file, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            
            return {
                'papers_processed': extract_results['total'] + extract_results['already_exists'],
                'texts_extracted': extract_results['success'],
                'already_exists': extract_results['already_exists'],
                'failed': extract_results['failed'],
                'total_papers': len(existing_papers)
            }
            
        except Exception:
            return {
                'papers_processed': 0,
                'texts_extracted': 0,
                'already_exists': 0,
                'failed': 0,
                'total_papers': self.get_saved_papers_count()
            }
