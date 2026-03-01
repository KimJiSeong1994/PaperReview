from typing import Dict, List, Any, Optional, Union, Set
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
from collector.paper.openalex_searcher import OpenAlexSearcher
from collector.paper.dblp_searcher import DBLPSearcher
from collector.paper.reference_collector import ReferenceCollector
from collector.paper.text_extractor import TextExtractor
from collector.paper.similarity_calculator import SimilarityCalculator
from collector.paper.deduplicator import PaperDeduplicator
from graph.embedding_generator import EmbeddingGenerator

# HybridRanker import
try:
    from graph_rag.hybrid_ranker import HybridRanker
    HYBRID_RANKER_AVAILABLE = True
except ImportError:
    HYBRID_RANKER_AVAILABLE = False
    HybridRanker = None
from graph.graph_builder import GraphBuilder
from graph.node_creator import NodeCreator
from graph.edge_creator import EdgeCreator
from utils.logger import log_search_operation

# QueryAnalyzer import
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
try:
    from QueryAgent.query_analyzer import QueryAnalyzer
    QUERY_ANALYZER_AVAILABLE = True
except ImportError:
    QUERY_ANALYZER_AVAILABLE = False
    QueryAnalyzer = None

class SearchAgent:
    def __init__(self, data_dir: str = None, openai_api_key: str = None):
        self.arxiv_searcher = ArxivSearcher()
        self.connected_papers_searcher = ConnectedPapersSearcher()
        self.google_scholar_searcher = GoogleScholarSearcher()
        self.openalex_searcher = OpenAlexSearcher()
        self.dblp_searcher = DBLPSearcher()
        self.reference_collector = ReferenceCollector()
        self.text_extractor = TextExtractor()
        
        # 유사도 계산기 초기화 (API 키가 있으면)
        try:
            self.similarity_calculator = SimilarityCalculator(api_key=openai_api_key) if openai_api_key or os.getenv('OPENAI_API_KEY') else None
        except Exception:
            self.similarity_calculator = None
        
        # LLM 기반 쿼리 분석기 초기화
        self.query_analyzer = None
        if QUERY_ANALYZER_AVAILABLE and (openai_api_key or os.getenv('OPENAI_API_KEY')):
            try:
                self.query_analyzer = QueryAnalyzer(api_key=openai_api_key)
                print("[SearchAgent] LLM Query Analyzer initialized")
            except Exception as e:
                print(f"[SearchAgent] Query Analyzer initialization failed: {e}")
        
        # 중복 제거기
        self.deduplicator = PaperDeduplicator()

        # 하이브리드 랭커
        self.hybrid_ranker = None
        if HYBRID_RANKER_AVAILABLE:
            try:
                self.hybrid_ranker = HybridRanker(similarity_calculator=self.similarity_calculator)
                print("[SearchAgent] HybridRanker initialized")
            except Exception as e:
                print(f"[SearchAgent] HybridRanker init failed: {e}")

        self.search_history = []
        
        # 데이터 저장 경로 설정
        if data_dir is None:
            project_root = os.path.join(os.path.dirname(__file__), '../..')
            self.data_dir = os.path.join(project_root, 'data/raw')

        else:
            self.data_dir = data_dir
        
        # 디렉토리 생성 (권한 오류 시 무시)
        try:
            os.makedirs(self.data_dir, exist_ok=True)
        except (OSError, PermissionError):
            pass
        
        # 논문 저장 파일 경로
        self.papers_file = os.path.join(self.data_dir, 'papers.json')
        
        # 그래프 및 embedding 경로 설정
        project_root = os.path.join(os.path.dirname(__file__), '../..')
        self.graph_path = os.path.join(project_root, 'data/graph/paper_graph.pkl')
        self.embeddings_dir = os.path.join(project_root, 'data/embeddings')
        
        try:
            os.makedirs(os.path.dirname(self.graph_path), exist_ok=True)
            os.makedirs(self.embeddings_dir, exist_ok=True)
        except (OSError, PermissionError):
            pass
        
        # OpenAI API 키 저장 (embedding 생성용)
        self.openai_api_key = openai_api_key or os.getenv('OPENAI_API_KEY')
    
    @log_search_operation("Multi-Source")
    def search_all_sources(self, query: str, max_results_per_source: int = 5) -> Dict[str, List[Dict[str, Any]]]:
        results = {
            "arxiv": [],
            "connected_papers": [],
            "google_scholar": [],
            "openalex": [],
            "dblp": [],
            "openalex_korean": []
        }

        # 검색 기록 저장
        self._add_to_history(query, "multi_source")

        # 각 소스별 직접 검색 (병렬 처리)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            # 각 검색 작업을 병렬로 실행
            arxiv_future = executor.submit(self.arxiv_searcher.search, query, max_results_per_source)
            connected_papers_future = executor.submit(self.connected_papers_searcher.search, query, max_results_per_source)
            google_scholar_future = executor.submit(self.google_scholar_searcher.search, query, max_results_per_source)
            openalex_future = executor.submit(self.openalex_searcher.search, query, max_results_per_source)
            dblp_future = executor.submit(self.dblp_searcher.search, query, max_results_per_source)
            openalex_korean_future = executor.submit(self.openalex_searcher.search_korean, query, max_results_per_source)

            # 결과 수집
            try:
                results["arxiv"] = arxiv_future.result(timeout=30)
            except (concurrent.futures.TimeoutError, Exception) as e:
                print(f"[WARNING] arXiv search timed out or failed: {e}")
                results["arxiv"] = []

            try:
                results["connected_papers"] = connected_papers_future.result(timeout=30)
            except (concurrent.futures.TimeoutError, Exception) as e:
                print(f"[WARNING] Connected Papers search timed out or failed: {e}")
                results["connected_papers"] = []

            try:
                results["google_scholar"] = google_scholar_future.result(timeout=30)
            except (concurrent.futures.TimeoutError, Exception) as e:
                print(f"[WARNING] Google Scholar search timed out or failed: {e}")
                results["google_scholar"] = []

            try:
                results["openalex"] = openalex_future.result(timeout=30)
            except (concurrent.futures.TimeoutError, Exception) as e:
                print(f"[WARNING] OpenAlex search timed out or failed: {e}")
                results["openalex"] = []

            try:
                results["dblp"] = dblp_future.result(timeout=30)
            except (concurrent.futures.TimeoutError, Exception) as e:
                print(f"[WARNING] DBLP search timed out or failed: {e}")
                results["dblp"] = []

            try:
                results["openalex_korean"] = openalex_korean_future.result(timeout=30)
            except (concurrent.futures.TimeoutError, Exception) as e:
                print(f"[WARNING] OpenAlex Korean search timed out or failed: {e}")
                results["openalex_korean"] = []

        return results
    
    @log_search_operation("Enhanced Multi-Source")
    def enhanced_search_all_sources(self, query: str, max_results_per_source: int = 10) -> Dict[str, List[Dict[str, Any]]]:
        """
        향상된 다중 소스 검색
        
        기본 검색 + Enhanced 검색 + 제목 검색을 병렬로 수행하여 
        더 포괄적인 결과 제공
        """
        results = {
            "arxiv": [],
            "connected_papers": [],
            "google_scholar": [],
            "openalex": [],
            "dblp": [],
            "openalex_korean": []
        }

        self._add_to_history(query, "enhanced_multi_source")

        seen_titles = {"arxiv": set(), "connected_papers": set(), "google_scholar": set(), "openalex": set(), "dblp": set(), "openalex_korean": set()}

        # 병렬 검색 작업 정의
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                # 기본 검색
                executor.submit(self.arxiv_searcher.search, query, max_results_per_source): ("arxiv", "basic"),
                executor.submit(self.google_scholar_searcher.search, query, max_results_per_source): ("google_scholar", "basic"),
                executor.submit(self.connected_papers_searcher.search, query, max_results_per_source): ("connected_papers", "basic"),
                executor.submit(self.openalex_searcher.search, query, max_results_per_source): ("openalex", "basic"),
                executor.submit(self.dblp_searcher.search, query, max_results_per_source): ("dblp", "basic"),
                executor.submit(self.openalex_searcher.search_korean, query, max_results_per_source): ("openalex_korean", "basic"),
                # Enhanced 검색 (arXiv 제외 — rate limit 방지)
                executor.submit(self.google_scholar_searcher.enhanced_search, query, max_results_per_source // 2): ("google_scholar", "enhanced"),
                executor.submit(self.openalex_searcher.enhanced_search, query, max_results_per_source // 2): ("openalex", "enhanced"),
            }
            
            for future in concurrent.futures.as_completed(futures):
                source, search_type = futures[future]
                try:
                    papers = future.result(timeout=30)
                    for paper in papers:
                        title_lower = paper.get('title', '').lower()
                        if title_lower and title_lower not in seen_titles[source]:
                            seen_titles[source].add(title_lower)
                            results[source].append(paper)
                except concurrent.futures.TimeoutError:
                    print(f"[WARNING] {source} {search_type} search timed out")
                except Exception as e:
                    print(f"[SearchAgent] {source} {search_type} search failed: {e}")
        
        # 결과 수 제한
        for source in results:
            results[source] = results[source][:max_results_per_source]
        
        return results
    
    @log_search_operation("Title Search")
    def search_by_paper_title(self, title: str, max_results: int = 5) -> Dict[str, List[Dict[str, Any]]]:
        """
        논문 제목으로 정확한 검색

        특정 논문을 찾을 때 사용
        """
        results = {
            "arxiv": [],
            "connected_papers": [],
            "google_scholar": [],
            "openalex": [],
            "dblp": []
        }

        self._add_to_history(f"title:{title}", "title_search")

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(self.arxiv_searcher.search_by_title, title, max_results): "arxiv",
                executor.submit(self.google_scholar_searcher.search_by_title, title, max_results): "google_scholar",
                executor.submit(self.connected_papers_searcher.search, title, max_results): "connected_papers",
                executor.submit(self.openalex_searcher.search_by_title, title, max_results): "openalex",
                executor.submit(self.dblp_searcher.search_by_title, title, max_results): "dblp",
            }
            
            for future in concurrent.futures.as_completed(futures):
                source = futures[future]
                try:
                    results[source] = future.result(timeout=30)
                except concurrent.futures.TimeoutError:
                    print(f"[WARNING] {source} title search timed out")
                    results[source] = []
                except Exception as e:
                    print(f"[SearchAgent] {source} title search failed: {e}")
                    results[source] = []
        
        return results
    
    @log_search_operation("Similar Papers")
    def find_similar_papers(self, paper_title: str, paper_abstract: str = "", max_results: int = 10) -> Dict[str, List[Dict[str, Any]]]:
        """
        주어진 논문과 유사한 논문 검색
        """
        results = {
            "arxiv": [],
            "connected_papers": [],
            "google_scholar": [],
            "openalex": [],
            "dblp": []
        }

        self._add_to_history(f"similar:{paper_title[:50]}", "similar_search")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            # arXiv와 Google Scholar에서 유사 논문 검색
            arxiv_future = executor.submit(
                self.arxiv_searcher.search_similar_papers,
                paper_title, paper_abstract, max_results
            )

            # 키워드 기반 검색으로 대체
            keywords = self._extract_search_keywords(paper_title, paper_abstract)
            scholar_future = executor.submit(
                self.google_scholar_searcher.search,
                keywords, max_results
            )

            # OpenAlex 키워드 검색
            openalex_future = executor.submit(
                self.openalex_searcher.search,
                keywords, max_results
            )

            # DBLP 키워드 검색
            dblp_future = executor.submit(
                self.dblp_searcher.search,
                keywords, max_results
            )

            try:
                results["arxiv"] = arxiv_future.result(timeout=30)
            except (concurrent.futures.TimeoutError, Exception) as e:
                print(f"[WARNING] arXiv similar search timed out or failed: {e}")
                results["arxiv"] = []

            try:
                results["google_scholar"] = scholar_future.result(timeout=30)
            except (concurrent.futures.TimeoutError, Exception) as e:
                print(f"[WARNING] Google Scholar search timed out or failed: {e}")
                results["google_scholar"] = []

            try:
                results["openalex"] = openalex_future.result(timeout=30)
            except (concurrent.futures.TimeoutError, Exception) as e:
                print(f"[WARNING] OpenAlex search timed out or failed: {e}")
                results["openalex"] = []

            try:
                results["dblp"] = dblp_future.result(timeout=30)
            except (concurrent.futures.TimeoutError, Exception) as e:
                print(f"[WARNING] DBLP search timed out or failed: {e}")
                results["dblp"] = []

        return results
    
    def _extract_search_keywords(self, title: str, abstract: str = "") -> str:
        """제목과 초록에서 검색 키워드 추출"""
        import re
        
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                     'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
                     'as', 'it', 'its', 'this', 'that', 'these', 'those', 'can', 'will',
                     'using', 'based', 'via', 'through', 'into', 'over', 'under', 'we', 'our'}
        
        text = f"{title} {abstract[:200] if abstract else ''}"
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        keywords = [w for w in words if w not in stopwords]
        
        # 빈도 기반 상위 키워드 선택
        from collections import Counter
        word_counts = Counter(keywords)
        top_keywords = [word for word, _ in word_counts.most_common(5)]
        
        return " ".join(top_keywords)
    
    @log_search_operation("LLM Context Search")
    def llm_context_search(self, query: str, max_results_per_source: int = 10, context: str = "") -> Dict[str, List[Dict[str, Any]]]:
        """
        LLM 컨텍스트 기반 검색
        
        LLM이 사용자 쿼리를 분석하고 최적화된 검색 쿼리를 생성하여
        arXiv와 Google Scholar에서 검색합니다.
        
        Args:
            query: 사용자 검색 쿼리 (한글/영어)
            max_results_per_source: 소스당 최대 결과 수
            context: 추가 컨텍스트 (선택)
            
        Returns:
            소스별 검색 결과
        """
        results = {
            "arxiv": [],
            "connected_papers": [],
            "google_scholar": [],
            "openalex": [],
            "dblp": [],
            "openalex_korean": []
        }

        self._add_to_history(query, "llm_context_search")

        # LLM 쿼리 분석기가 없으면 기본 검색으로 대체
        if not self.query_analyzer:
            print("[SearchAgent] LLM Query Analyzer not available, using enhanced search")
            return self.enhanced_search_all_sources(query, max_results_per_source)

        try:
            # 1. LLM으로 최적화된 검색 쿼리 생성
            print(f"[SearchAgent] Generating LLM search queries for: {query[:50]}...")

            if context:
                search_queries = self.query_analyzer.search_with_context(query, context)
            else:
                search_queries = self.query_analyzer.generate_search_queries(query)

            arxiv_queries = search_queries.get("arxiv_queries", [query])
            scholar_queries = search_queries.get("scholar_queries", [query])
            keywords = search_queries.get("keywords", [])

            print(f"[SearchAgent] Generated {len(arxiv_queries)} arXiv queries, {len(scholar_queries)} Scholar queries")
            print(f"[SearchAgent] Keywords: {keywords[:5]}")

            # 2. 병렬 검색 수행
            seen_titles: Dict[str, Set[str]] = {
                "arxiv": set(),
                "google_scholar": set(),
                "connected_papers": set(),
                "openalex": set(),
                "dblp": set(),
                "openalex_korean": set()
            }

            with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
                futures = []

                # arXiv 검색 (rate limit 방지: 쿼리 1개만)
                for arxiv_query in arxiv_queries[:1]:
                    futures.append(
                        (executor.submit(self.arxiv_searcher.search, arxiv_query, max_results_per_source),
                         "arxiv", arxiv_query)
                    )

                # Google Scholar 검색 (여러 쿼리)
                for scholar_query in scholar_queries[:3]:
                    futures.append(
                        (executor.submit(self.google_scholar_searcher.search, scholar_query, max_results_per_source // 2),
                         "google_scholar", scholar_query)
                    )

                # Connected Papers 검색 (키워드 기반)
                keyword_query = " ".join(keywords[:4]) if keywords else query
                futures.append(
                    (executor.submit(self.connected_papers_searcher.search, keyword_query, max_results_per_source),
                     "connected_papers", keyword_query)
                )

                # OpenAlex 검색
                futures.append(
                    (executor.submit(self.openalex_searcher.search, keyword_query, max_results_per_source),
                     "openalex", keyword_query)
                )

                # DBLP 검색
                futures.append(
                    (executor.submit(self.dblp_searcher.search, keyword_query, max_results_per_source),
                     "dblp", keyword_query)
                )

                # OpenAlex Korean 검색
                futures.append(
                    (executor.submit(self.openalex_searcher.search_korean, keyword_query, max_results_per_source),
                     "openalex_korean", keyword_query)
                )

                # 결과 수집
                for future_tuple in futures:
                    future, source, q = future_tuple
                    try:
                        papers = future.result(timeout=30)
                        for paper in papers:
                            title_lower = paper.get('title', '').lower().strip()
                            if title_lower and title_lower not in seen_titles[source]:
                                seen_titles[source].add(title_lower)
                                # 검색 쿼리 정보 추가
                                paper['_search_query'] = q
                                results[source].append(paper)
                    except concurrent.futures.TimeoutError:
                        print(f"[SearchAgent] Timeout for {source}: {q[:30]}...")
                    except Exception as e:
                        print(f"[SearchAgent] Error in {source} search: {e}")
            
            # 결과 수 제한
            for source in results:
                results[source] = results[source][:max_results_per_source]
            
            total = sum(len(papers) for papers in results.values())
            print(f"[SearchAgent] LLM Context Search completed: {total} papers found")
            
            # 검색 메타데이터 추가
            results['_metadata'] = {
                'original_query': query,
                'arxiv_queries': arxiv_queries,
                'scholar_queries': scholar_queries,
                'keywords': keywords,
                'search_context': search_queries.get('search_context', ''),
                'translated_query': search_queries.get('translated_query', query)
            }
            
            return results
            
        except Exception as e:
            print(f"[SearchAgent] LLM Context Search failed: {e}")
            import traceback
            traceback.print_exc()
            # 실패 시 기본 검색으로 대체
            return self.enhanced_search_all_sources(query, max_results_per_source)
    
    @log_search_operation("Smart Search")
    def smart_search(self, query: str, max_results: int = 20) -> Dict[str, Any]:
        """
        스마트 검색 - LLM 분석 + 다중 검색 전략 조합
        
        1. LLM이 쿼리를 분석하고 검색 전략 결정
        2. 최적화된 쿼리로 다중 소스 검색
        3. 결과 병합 및 중복 제거
        4. 관련성 순 정렬
        """
        self._add_to_history(query, "smart_search")
        
        result = {
            "papers": [],
            "metadata": {
                "query": query,
                "total_found": 0,
                "sources_searched": []
            }
        }
        
        try:
            # 1. LLM 쿼리 분석
            analysis = None
            if self.query_analyzer:
                try:
                    analysis = self.query_analyzer.analyze_query(query)
                    print(f"[SmartSearch] Intent: {analysis.get('intent')}, Confidence: {analysis.get('confidence')}")
                except Exception as e:
                    print(f"[SmartSearch] Query analysis failed: {e}")
            
            # 2. 검색 전략 결정
            if analysis and analysis.get('confidence', 0) >= 0.7:
                # LLM 분석 결과 기반 검색
                search_results = self.llm_context_search(query, max_results // 2)
            else:
                # 기본 enhanced 검색
                search_results = self.enhanced_search_all_sources(query, max_results // 2)
            
            # 3. 결과 병합 및 중복 제거 (PaperDeduplicator)
            all_papers = self.deduplicator.deduplicate_cross_source(search_results)

            # 4. 하이브리드 랭킹
            intent = analysis.get('intent', 'paper_search') if analysis else 'paper_search'
            if self.hybrid_ranker:
                all_papers = self.hybrid_ranker.rank_papers(
                    query=query,
                    papers=all_papers,
                    intent=intent,
                )
            elif analysis and analysis.get('keywords'):
                # fallback: 키워드 매칭
                keywords = set(kw.lower() for kw in analysis['keywords'])

                def relevance_score(paper):
                    title = paper.get('title', '').lower()
                    abstract = paper.get('abstract', '').lower()
                    score = 0
                    for kw in keywords:
                        if kw in title:
                            score += 3
                        if kw in abstract:
                            score += 1
                    return score

                all_papers.sort(key=relevance_score, reverse=True)
            
            result["papers"] = all_papers[:max_results]
            result["metadata"]["total_found"] = len(all_papers)
            result["metadata"]["sources_searched"] = list(search_results.keys())
            
            if analysis:
                result["metadata"]["analysis"] = {
                    "intent": analysis.get('intent'),
                    "keywords": analysis.get('keywords', []),
                    "improved_query": analysis.get('improved_query'),
                    "confidence": analysis.get('confidence'),
                    "ranking_intent": intent,
                }
            
            if '_metadata' in search_results:
                result["metadata"]["llm_queries"] = search_results['_metadata']
            
            return result
            
        except Exception as e:
            print(f"[SmartSearch] Error: {e}")
            # 실패 시 기본 검색
            basic_results = self.search_all_sources(query, max_results // 3)
            for source, papers in basic_results.items():
                for paper in papers:
                    paper['_source'] = source
                    result["papers"].append(paper)
            result["metadata"]["total_found"] = len(result["papers"])
            return result
    
    def search_arxiv(self, query: str, max_results: int = 10, sort_by: str = "relevance", category: str = None) -> List[Dict[str, Any]]:
        self._add_to_history(query, "arxiv")

        if category:
            # 카테고리와 쿼리를 결합하여 검색 (카테고리만으로 검색하면 관련 없는 결과 반환)
            combined_query = f"cat:{category} AND ({query})"
            return self.arxiv_searcher.search(combined_query, max_results, sort_by)
        else:
            return self.arxiv_searcher.search(query, max_results, sort_by)
    
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
            "google_scholar": [],
            "openalex": [],
            "dblp": []
        }

        self._add_to_history(f"author:{author}", "multi_author")

        # 각 소스에서 저자 검색
        results["arxiv"] = self.arxiv_searcher.search_by_author(author, max_results)
        results["google_scholar"] = self.google_scholar_searcher.search_by_author(author, max_results)

        # Connected Papers는 저자 검색이 제한적이므로 일반 검색으로 대체
        results["connected_papers"] = self.connected_papers_searcher.search(author, max_results)
        results["openalex"] = self.openalex_searcher.search(author, max_results)
        results["dblp"] = self.dblp_searcher.search_by_author(author, max_results)
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
            print(f"[SearchAgent] 논문 상세 정보 가져오기 오류: {e}")
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
            print(f"[SearchAgent] 관련 논문 가져오기 오류: {e}")
            return []
    
    def get_author_profile(self, author_name: str) -> Optional[Dict[str, Any]]:
        return self.google_scholar_searcher.get_author_profile(author_name)
    
    def get_categories(self) -> Dict[str, List[Dict[str, str]]]:
        return {"arxiv": self.arxiv_searcher.get_categories()}
    
    def search_with_filters(self, query: str, filters: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """
        필터를 적용한 고급 검색 (병렬 실행)

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
        sources = filters.get("sources", ["arxiv", "connected_papers", "google_scholar", "openalex", "dblp"])
        max_results = filters.get("max_results", 5)
        source_queries = filters.get("source_queries", {})

        results = {}
        futures = {}

        def _search_source(source_name):
            # 소스별 최적화 쿼리 사용 (없으면 원본 쿼리)
            sq = source_queries.get(source_name, query)
            if source_name == "arxiv":
                category = filters.get("category")
                sort_by = filters.get("sort_by", "relevance")
                arxiv_q = source_queries.get("arxiv", query)
                # 원본 쿼리와 최적화 쿼리를 모두 검색 후 병합 (중복 제거)
                results_optimized = self.search_arxiv(arxiv_q, max_results, sort_by, category)
                if arxiv_q != query:
                    results_original = self.search_arxiv(query, max_results // 2, sort_by, category)
                    seen_titles = {p.get("title", "").lower() for p in results_optimized}
                    for p in results_original:
                        if p.get("title", "").lower() not in seen_titles:
                            results_optimized.append(p)
                            seen_titles.add(p.get("title", "").lower())
                return results_optimized[:max_results]
            elif source_name == "connected_papers":
                return self.search_connected_papers(query, max_results)
            elif source_name == "google_scholar":
                year_start = filters.get("year_start")
                year_end = filters.get("year_end")
                author = filters.get("author")
                sort_by = filters.get("sort_by", "relevance")
                scholar_q = source_queries.get("google_scholar", query)
                return self.search_google_scholar(
                    scholar_q, max_results, sort_by, year_start, year_end, author
                )
            elif source_name == "openalex":
                # enhanced_search: 일반 검색 + 제목 필터 병합으로 노이즈 감소
                openalex_q = source_queries.get("openalex", query)
                results_optimized = self.openalex_searcher.enhanced_search(openalex_q, max_results)
                # 최적화 쿼리와 원본 쿼리가 다르면 원본도 검색 후 병합
                if openalex_q != query:
                    results_original = self.openalex_searcher.search_by_title(query, max_results // 2)
                    seen_titles = {p.get("title", "").lower() for p in results_optimized}
                    for p in results_original:
                        if p.get("title", "").lower() not in seen_titles:
                            results_optimized.append(p)
                            seen_titles.add(p.get("title", "").lower())
                return results_optimized[:max_results]
            elif source_name == "dblp":
                dblp_q = source_queries.get("dblp", query)
                return self.dblp_searcher.search(dblp_q, max_results)
            elif source_name == "openalex_korean":
                return self.openalex_searcher.search_korean(query, max_results)
            return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(sources)) as executor:
            for source in sources:
                futures[executor.submit(_search_source, source)] = source

            for future in concurrent.futures.as_completed(futures, timeout=60):
                source = futures[future]
                try:
                    results[source] = future.result(timeout=60)
                except Exception as e:
                    print(f"[SearchAgent] {source} search failed: {e}")
                    results[source] = []

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
        """논문 고유 ID 생성 (DOI 우선, 없으면 정규화 제목)"""
        doi = PaperDeduplicator.normalize_doi(paper.get('doi', ''))
        if doi:
            return f"doi:{doi}"
        title = PaperDeduplicator.normalize_title(paper.get('title', ''))
        return title[:100] if title else str(hash(str(paper)))

    @staticmethod
    def _legacy_paper_id(paper: Dict[str, Any]) -> str:
        """레거시 ID 생성 (기존 그래프 호환용: title.lower().strip())"""
        title = paper.get('title', '').lower().strip()
        return title[:100] if title else ""

    def _find_node_in_graph(self, paper: Dict[str, Any], graph) -> Optional[str]:
        """그래프에서 논문 노드 찾기 (신규 ID → 레거시 ID 순)"""
        new_id = self._generate_paper_id(paper)
        if new_id in graph:
            return new_id
        legacy_id = self._legacy_paper_id(paper)
        if legacy_id and legacy_id in graph:
            return legacy_id
        return None
    
    def save_papers(self, results: Dict[str, List[Dict[str, Any]]], query: str = "", 
                  generate_embeddings: bool = True, update_graph: bool = True) -> Dict[str, Any]:
        """
        검색된 논문들을 누적형으로 JSON 파일에 저장하고, embedding 생성 및 그래프 업데이트 수행
        
        Args:
            results: 검색 결과 (소스별 논문 리스트)
            query: 검색 쿼리
            generate_embeddings: embedding 자동 생성 여부
            update_graph: 그래프 업데이트 여부
            
        Returns:
            저장 결과 정보 (저장된 수, 중복 수, embedding 생성 수, 그래프 업데이트 정보 등)
        """
        # 기존 논문 로드
        existing_papers = self._load_existing_papers()
        
        # 새로운 논문 추가
        new_papers_list = []
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
                    new_papers_list.append(paper)
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
            
            result = {
                'success': True,
                'file': self.papers_file,
                'new_papers': new_count,
                'duplicates': duplicate_count,
                'total_papers': len(existing_papers),
                'embeddings_generated': 0,
                'graph_updated': False
            }
            
            # Embedding 생성
            if generate_embeddings and new_papers_list and self.openai_api_key:
                try:
                    print(f"\n[Embedding] {len(new_papers_list)}개 새 논문에 대한 embedding 생성 중...")
                    embedding_generator = EmbeddingGenerator(api_key=self.openai_api_key)
                    new_embeddings = embedding_generator.generate_batch_embeddings(new_papers_list)
                    
                    if new_embeddings:
                        # 기존 embedding 로드 및 병합
                        existing_embeddings = self._load_existing_embeddings()
                        existing_embeddings.update(new_embeddings)
                        
                        # 저장
                        embedding_generator.save_embeddings(existing_embeddings, self.embeddings_dir)
                        result['embeddings_generated'] = len(new_embeddings)
                        print(f"[v] {len(new_embeddings)}개 embedding 생성 및 저장 완료")
                except Exception as e:
                    print(f"[WARNING] Embedding 생성 중 오류: {e}")
                    result['embedding_error'] = str(e)
            
            # 그래프 업데이트
            if update_graph and new_papers_list:
                try:
                    print(f"\n[Graph] {len(new_papers_list)}개 새 논문을 그래프에 추가 중...")
                    graph_info = self._update_graph(new_papers_list)
                    result['graph_updated'] = True
                    result['graph_info'] = graph_info
                    print(f"[v] 그래프 업데이트 완료")
                except Exception as e:
                    print(f"[WARNING] 그래프 업데이트 중 오류: {e}")
                    result['graph_error'] = str(e)
            
            return result
            
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
    
    def _load_existing_embeddings(self) -> Dict[str, Any]:
        """기존 embedding 로드 (JSON 형식)"""
        embeddings_file = os.path.join(self.embeddings_dir, 'embeddings.json')
        if not os.path.exists(embeddings_file):
            return {}
        
        try:
            import json
            with open(embeddings_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # embeddings.json은 {paper_id: [embedding_array]} 형식
                return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[WARNING] Embedding 로드 중 오류: {e}")
            return {}
    
    def _update_graph(self, new_papers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        기존 그래프에 새 논문 추가 및 병합
        
        Args:
            new_papers: 추가할 새 논문 리스트
            
        Returns:
            그래프 업데이트 정보
        """
        import networkx as nx
        import pickle
        
        # 1. 기존 그래프 로드 (없으면 새로 생성)
        existing_graph = None
        if os.path.exists(self.graph_path):
            try:
                with open(self.graph_path, 'rb') as f:
                    existing_graph = pickle.load(f)
                print(f"  기존 그래프 로드: {existing_graph.number_of_nodes()}개 노드, {existing_graph.number_of_edges()}개 엣지")
            except Exception as e:
                print(f"  [WARNING] 기존 그래프 로드 실패: {e}, 새 그래프 생성")
        
        if existing_graph is None:
            existing_graph = nx.MultiDiGraph()
        
        # 2. 기존 논문 로드 (전체 논문 목록)
        all_papers = self._load_existing_papers()
        all_papers_list = list(all_papers.values())
        
        # 3. 새 논문에 대한 embedding 로드 (신규 ID + 레거시 ID 모두 탐색)
        existing_embeddings = self._load_existing_embeddings()
        embeddings_dict = {}
        for paper in new_papers:
            paper_id = self._generate_paper_id(paper)
            legacy_id = self._legacy_paper_id(paper)
            emb_data = existing_embeddings.get(paper_id) or existing_embeddings.get(legacy_id)
            if emb_data is not None:
                import numpy as np
                if isinstance(emb_data, list):
                    embeddings_dict[paper_id] = np.array(emb_data)
                else:
                    embeddings_dict[paper_id] = emb_data
        
        # 4. 새 논문을 노드로 추가
        node_creator = NodeCreator()
        new_nodes = node_creator.create_nodes_batch(new_papers, embeddings_dict)
        
        nodes_added = 0
        for node in new_nodes:
            node_id = node['node_id']
            if node_id not in existing_graph:
                # 노드 속성에서 node_id 제거 (NetworkX는 node_id를 키로 사용)
                node_attrs = {k: v for k, v in node.items() if k != 'node_id'}
                existing_graph.add_node(node_id, **node_attrs)
                nodes_added += 1
        
        print(f"  {nodes_added}개 새 노드 추가")
        
        # 5. 새 논문과 기존 논문 간 엣지 생성
        edge_creator = EdgeCreator()
        
        # Citation 엣지 생성 (새 논문의 참고문헌이 기존 논문에 있는 경우)
        citation_edges = edge_creator.create_citation_edges(new_papers)
        citation_count = 0
        for edge in citation_edges:
            source_id = edge['source']
            target_id = edge['target']
            # 기존 그래프에 노드가 있는 경우에만 엣지 추가
            if source_id in existing_graph and target_id in existing_graph:
                if not existing_graph.has_edge(source_id, target_id):
                    existing_graph.add_edge(
                        source_id, target_id,
                        edge_type=edge['edge_type'],
                        weight=edge['weight'],
                        **edge.get('metadata', {})
                    )
                    citation_count += 1
        
        print(f"  {citation_count}개 Citation 엣지 추가")
        
        # 6. Similarity 엣지 생성 (제목 유사도 기반)
        # 새 논문과 기존 논문 간 유사도 계산
        similarity_count = 0
        for new_paper in new_papers:
            new_paper_id = self._find_node_in_graph(new_paper, existing_graph)
            if new_paper_id is None:
                continue

            # 기존 논문과의 유사도 계산
            similarities = []
            for existing_paper in all_papers_list:
                existing_paper_id = self._find_node_in_graph(existing_paper, existing_graph)
                if existing_paper_id is None or existing_paper_id == new_paper_id:
                    continue
                
                # 제목 토큰 기반 유사도 계산
                similarity = self._calculate_title_similarity(
                    new_paper.get('title', ''),
                    existing_paper.get('title', '')
                )
                
                if similarity >= 0.12:  # 임계값
                    similarities.append((existing_paper_id, similarity))
            
            # 상위 유사도 엣지 추가
            similarities.sort(key=lambda x: x[1], reverse=True)
            for target_id, sim_score in similarities[:10]:  # 상위 10개만
                if not existing_graph.has_edge(new_paper_id, target_id):
                    existing_graph.add_edge(
                        new_paper_id, target_id,
                        edge_type='SIMILAR_TO',
                        weight=round(sim_score, 3)
                    )
                    similarity_count += 1
        
        print(f"  {similarity_count}개 Similarity 엣지 추가")
        
        # 7. 그래프 저장
        try:
            with open(self.graph_path, 'wb') as f:
                pickle.dump(existing_graph, f)
            
            # 메타데이터 저장
            metadata = {
                "nodes": existing_graph.number_of_nodes(),
                "edges": existing_graph.number_of_edges(),
                "updated_at": datetime.now().isoformat()
            }
            metadata_path = self.graph_path.replace('.pkl', '_metadata.json')
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            return {
                "nodes_added": nodes_added,
                "citation_edges_added": citation_count,
                "similarity_edges_added": similarity_count,
                "total_nodes": existing_graph.number_of_nodes(),
                "total_edges": existing_graph.number_of_edges()
            }
        except Exception as e:
            print(f"  [WARNING] 그래프 저장 실패: {e}")
            raise
    
    def _calculate_title_similarity(self, title1: str, title2: str) -> float:
        """제목 간 유사도 계산 (Jaccard similarity)"""
        if not title1 or not title2:
            return 0.0
        
        import re
        def _title_tokens(text: str) -> set:
            words = re.findall(r"\b\w+\b", text.lower())
            return {w for w in words if len(w) > 3}
        
        tokens1 = _title_tokens(title1)
        tokens2 = _title_tokens(title2)
        
        if not tokens1 or not tokens2:
            return 0.0
        
        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)
        
        return intersection / union if union > 0 else 0.0
    
    def collect_references(self, max_references_per_paper: int = 10, max_papers: int = None) -> Dict[str, Any]:
        existing_papers = self._load_existing_papers()
        papers_list = list(existing_papers.values())
        
        if max_papers:
            papers_list = papers_list[:max_papers]
        
        print(f'\n[INFO] {len(papers_list)}개 논문의 참고문헌 수집 시작...')
        
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
        
        print(f'\n[INFO] {len(papers_list)}개 논문의 본문 추출 시작...')
        
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
