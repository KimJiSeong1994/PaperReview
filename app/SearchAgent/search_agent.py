from typing import Callable, Dict, List, Any, Optional, TypeVar
import asyncio
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import logging
import os
import threading
import time
import copy
import re
import unicodedata
import requests

from src.collector.paper.arxiv_searcher import ArxivSearcher
from src.collector.paper.connected_papers_searcher import ConnectedPapersSearcher
from src.collector.paper.google_scholar_searcher import GoogleScholarSearcher
from src.collector.paper.openalex_searcher import OpenAlexSearcher
from src.collector.paper.dblp_searcher import DBLPSearcher
from src.collector.paper.reference_collector import ReferenceCollector
from src.collector.paper.text_extractor import TextExtractor
from src.collector.paper.similarity_calculator import SimilarityCalculator
from src.collector.paper.deduplicator import PaperDeduplicator
from src.collector.paper.github_client import GitHubClient


def _contains_korean(text: str) -> bool:
    """텍스트에 한글 음절(U+AC00-U+D7A3)이 포함되어 있는지 확인."""
    return any('\uAC00' <= c <= '\uD7A3' for c in text)
from src.graph.embedding_generator import EmbeddingGenerator
from src.graph.constants import JACCARD_EDGE_THRESHOLD, CITATION_MAX_PER_PAPER, CITATION_COLLECTION_DELAY

# HybridRanker import
try:
    from src.graph_rag.hybrid_ranker import HybridRanker
    HYBRID_RANKER_AVAILABLE = True
except ImportError:
    HYBRID_RANKER_AVAILABLE = False
    HybridRanker = None
from src.graph.node_creator import NodeCreator
from src.graph.edge_creator import EdgeCreator
from src.utils.logger import log_search_operation

# QueryAnalyzer import
try:
    from app.QueryAgent.query_analyzer import QueryAnalyzer
    QUERY_ANALYZER_AVAILABLE = True
except ImportError:
    QUERY_ANALYZER_AVAILABLE = False
    QueryAnalyzer = None

logger = logging.getLogger(__name__)

_LLM_CONTEXT_SEARCH_TIMEOUT_SECONDS = 60.0
_SEARCH_OPERATION_TIMEOUT_SECONDS = 60.0
_SEARCH_SHORT_OPERATION_TIMEOUT_SECONDS = 30.0
MAX_ACTIVE_GENERATIONS_PER_OPERATION = 2
_OPERATION_STATE_INIT_LOCK = threading.Lock()
_T = TypeVar("_T")

def classify_search_route(query: str) -> Dict[str, str]:
    value = query.strip()
    doi = re.fullmatch(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/\S+)", value, re.I)
    if doi:
        return {"kind": "doi", "value": doi.group(1).casefold()}
    aid = re.fullmatch(r"(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:\s*)?((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7}))(?:v\d+)?(?:\.pdf)?", value, re.I)
    if aid:
        return {"kind": "arxiv", "value": aid.group(1).casefold()}
    if len(value) > 2 and value[0] == value[-1] == '"':
        return {"kind": "title", "value": value[1:-1]}
    return {"kind": "topic", "value": value}


def apply_search_filters(papers: List[Dict[str, Any]], filters: Dict[str, Any]):
    """Hard filters shared by retrieval and post-expansion publication."""
    from src.utils.paper_utils import generate_result_key
    def tokens(value):
        return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", str(value)).casefold())
    drops: Dict[str, int] = {}
    kept = []
    for paper in papers:
        reason = None
        if filters.get("year_start") is not None or filters.get("year_end") is not None:
            year = str(paper.get("year") or paper.get("published_date") or paper.get("published") or paper.get("publication_date") or "")[:4]
            if not year.isdigit():
                reason = "unknown_year"
            elif not (filters.get("year_start") or 0) <= int(year) <= (filters.get("year_end") or 9999):
                reason = "year"
        if not reason and filters.get("author"):
            authors = paper.get("authors") or []
            if isinstance(authors, str):
                authors = [authors]
            wanted = tokens(filters["author"])
            names = [tokens(a.get("name", "") if isinstance(a, dict) else a) for a in authors]
            if not any(any(name[i:i + len(wanted)] == wanted for i in range(len(name))) for name in names):
                reason = "author" if names else "unknown_author"
        if not reason and filters.get("category"):
            categories = paper.get("categories") or paper.get("primary_category") or []
            if isinstance(categories, str):
                categories = [categories]
            categories = [c for c in categories if isinstance(c, str) and re.fullmatch(r"[a-z-]+(?:\.[A-Z]{2}|\.[a-z-]+)?", c)]
            if filters["category"] not in categories:
                reason = "category" if categories else "unknown_category"
        if reason:
            drops[reason] = drops.get(reason, 0) + 1
        else:
            kept.append(copy.deepcopy(paper))
    sort = filters.get("sort_by", "relevance")
    if sort in ("submittedDate", "lastUpdatedDate"):
        def date_value(paper):
            value = (paper.get("updated_date") or paper.get("updated") or paper.get("last_updated")) if sort == "lastUpdatedDate" else (paper.get("published_date") or paper.get("published") or paper.get("publication_date"))
            try:
                date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                return (date if date.tzinfo else date.replace(tzinfo=timezone.utc)).timestamp()
            except (ValueError, TypeError, OverflowError):
                return float("-inf")
        kept.sort(key=lambda p: (-date_value(p), generate_result_key(p)))
    return kept, drops


def _new_search_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=8, thread_name_prefix="search")


class SearchCapacityExceeded(RuntimeError):
    """Raised when an operation has reached its active-generation limit."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(
            f"Search capacity exceeded for {operation}; retry after current searches finish"
        )


class _OperationGeneration:
    """Own one operation-local executor until all submitted work finishes."""

    def __init__(self, owner: "SearchAgent", operation: str) -> None:
        self._owner = owner
        self.operation = operation
        self._executor = _new_search_executor()
        self._futures: List[concurrent.futures.Future[Any]] = []
        self._release_lock = threading.Lock()
        self._close_started = False
        self._released = False

    def submit(
        self, function: Callable[..., _T], *args: Any, **kwargs: Any
    ) -> concurrent.futures.Future[_T]:
        future = self._executor.submit(function, *args, **kwargs)
        self._futures.append(future)
        return future

    def close(self) -> None:
        """Cancel queued work and reclaim workers without waiting on running calls."""
        with self._release_lock:
            if self._close_started:
                return
            self._close_started = True

        for future in self._futures:
            if not future.done():
                future.cancel()

        if any(future.running() for future in self._futures):
            self._executor.shutdown(wait=False, cancel_futures=True)
            threading.Thread(
                target=self._shutdown_and_release,
                name=f"operation_cleanup_{self.operation}",
                daemon=True,
            ).start()
            return

        self._executor.shutdown(wait=True, cancel_futures=True)
        self._release()

    def _shutdown_and_release(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._release()

    def _release(self) -> None:
        with self._release_lock:
            if self._released:
                return
            self._released = True
        self._owner._release_operation_generation(self.operation, self)


class SearchAgent:
    # Source name → searcher attribute, for sources whose searcher can report
    # circuit-breaker state. Sources absent here simply never report one.
    _SOURCE_SEARCHER_ATTRS = {
        "arxiv": "arxiv_searcher",
        "connected_papers": "connected_papers_searcher",
        "google_scholar": "google_scholar_searcher",
        "openalex": "openalex_searcher",
        "openalex_korean": "openalex_searcher",
        "dblp": "dblp_searcher",
    }

    def __init__(self, data_dir: str = None, openai_api_key: str = None):
        self.arxiv_searcher = ArxivSearcher()
        self.connected_papers_searcher = ConnectedPapersSearcher()
        self.google_scholar_searcher = GoogleScholarSearcher()
        self.openalex_searcher = OpenAlexSearcher()
        self.dblp_searcher = DBLPSearcher()
        self.reference_collector = ReferenceCollector()
        self.text_extractor = TextExtractor()
        self.github_client = GitHubClient()

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
                logger.info("[SearchAgent] LLM Query Analyzer initialized")
            except Exception as e:
                logger.warning("[SearchAgent] Query Analyzer initialization failed: %s", e)

        # 중복 제거기
        self.deduplicator = PaperDeduplicator()

        # 하이브리드 랭커
        self.hybrid_ranker = None
        if HYBRID_RANKER_AVAILABLE:
            try:
                self.hybrid_ranker = HybridRanker(similarity_calculator=self.similarity_calculator)
                logger.info("[SearchAgent] HybridRanker initialized")
            except Exception as e:
                logger.warning("[SearchAgent] HybridRanker init failed: %s", e)

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

    def _operation_generation_state(
        self,
    ) -> tuple[threading.Lock, dict[str, set[_OperationGeneration]]]:
        if not hasattr(self, "_operation_generation_runtime"):
            with _OPERATION_STATE_INIT_LOCK:
                if not hasattr(self, "_operation_generation_runtime"):
                    self._operation_generation_runtime = (threading.Lock(), {})
        return self._operation_generation_runtime

    def _begin_operation_generation(
        self, operation: str
    ) -> _OperationGeneration:
        lock, generations = self._operation_generation_state()
        with lock:
            active_generations = generations.get(operation)
            if (
                active_generations is not None
                and len(active_generations) >= MAX_ACTIVE_GENERATIONS_PER_OPERATION
            ):
                logger.warning(
                    "[SearchAgent] %s reached the active generation limit (%d)",
                    operation,
                    MAX_ACTIVE_GENERATIONS_PER_OPERATION,
                )
                raise SearchCapacityExceeded(operation)
            generation = _OperationGeneration(self, operation)
            if active_generations is None:
                generations[operation] = {generation}
            else:
                active_generations.add(generation)
            return generation

    def _release_operation_generation(
        self, operation: str, generation: _OperationGeneration
    ) -> None:
        lock, generations = self._operation_generation_state()
        with lock:
            active_generations = generations.get(operation)
            if active_generations is None:
                return
            active_generations.discard(generation)
            if not active_generations:
                del generations[operation]

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

        generation = self._begin_operation_generation("search_all_sources")

        # 각 소스별 직접 검색 (병렬 처리)
        try:
            # 각 검색 작업을 병렬로 실행
            source_futures = [
                ("arxiv", "arXiv", generation.submit(self.arxiv_searcher.search, query, max_results_per_source)),
                ("connected_papers", "Connected Papers", generation.submit(self.connected_papers_searcher.search, query, max_results_per_source)),
                ("google_scholar", "Google Scholar", generation.submit(self.google_scholar_searcher.search, query, max_results_per_source)),
                ("openalex", "OpenAlex", generation.submit(self.openalex_searcher.search, query, max_results_per_source)),
                ("dblp", "DBLP", generation.submit(self.dblp_searcher.search, query, max_results_per_source)),
            ]
            if _contains_korean(query):
                source_futures.append(
                    ("openalex_korean", "OpenAlex Korean", generation.submit(self.openalex_searcher.search_korean, query, max_results_per_source))
                )

            # 결과 수집
            deadline = time.monotonic() + _SEARCH_SHORT_OPERATION_TIMEOUT_SECONDS
            for source, label, future in source_futures:
                try:
                    results[source] = future.result(
                        timeout=max(0.0, deadline - time.monotonic())
                    )
                except Exception as e:
                    logger.warning("[WARNING] %s search timed out or failed: %s", label, e)
                    results[source] = []
        finally:
            generation.close()

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

        generation = self._begin_operation_generation("enhanced_search_all_sources")

        # 병렬 검색 작업 정의
        try:
            futures = {
                # 기본 검색
                generation.submit(self.arxiv_searcher.search, query, max_results_per_source): ("arxiv", "basic"),
                generation.submit(self.google_scholar_searcher.search, query, max_results_per_source): ("google_scholar", "basic"),
                generation.submit(self.connected_papers_searcher.search, query, max_results_per_source): ("connected_papers", "basic"),
                generation.submit(self.openalex_searcher.search, query, max_results_per_source): ("openalex", "basic"),
                generation.submit(self.dblp_searcher.search, query, max_results_per_source): ("dblp", "basic"),
                # Enhanced 검색 (arXiv 제외 — rate limit 방지)
                generation.submit(self.google_scholar_searcher.enhanced_search, query, max_results_per_source // 2): ("google_scholar", "enhanced"),
                generation.submit(self.openalex_searcher.enhanced_search, query, max_results_per_source // 2): ("openalex", "enhanced"),
            }
            # 한국어 쿼리일 때만 OpenAlex Korean 검색 추가
            if _contains_korean(query):
                futures[generation.submit(self.openalex_searcher.search_korean, query, max_results_per_source)] = ("openalex_korean", "basic")

            deadline = time.monotonic() + _SEARCH_OPERATION_TIMEOUT_SECONDS
            try:
                for future in concurrent.futures.as_completed(
                    futures, timeout=max(0.0, deadline - time.monotonic())
                ):
                    source, search_type = futures[future]
                    try:
                        papers = future.result(timeout=5)
                        for paper in papers:
                            title_lower = paper.get('title', '').lower()
                            if title_lower and title_lower not in seen_titles[source]:
                                seen_titles[source].add(title_lower)
                                results[source].append(paper)
                    except concurrent.futures.TimeoutError:
                        logger.warning("[WARNING] %s %s search timed out", source, search_type)
                    except Exception as e:
                        logger.warning("[SearchAgent] %s %s search failed: %s", source, search_type, e)
            except concurrent.futures.TimeoutError:
                logger.warning("[WARNING] Enhanced search overall timeout (60s) — returning partial results")
        finally:
            generation.close()

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

        generation = self._begin_operation_generation("search_by_paper_title")

        try:
            futures = {
                generation.submit(self.arxiv_searcher.search_by_title, title, max_results): "arxiv",
                generation.submit(self.google_scholar_searcher.search_by_title, title, max_results): "google_scholar",
                generation.submit(self.connected_papers_searcher.search, title, max_results): "connected_papers",
                generation.submit(self.openalex_searcher.search_by_title, title, max_results): "openalex",
                generation.submit(self.dblp_searcher.search_by_title, title, max_results): "dblp",
            }

            deadline = time.monotonic() + _SEARCH_SHORT_OPERATION_TIMEOUT_SECONDS
            try:
                for future in concurrent.futures.as_completed(
                    futures, timeout=max(0.0, deadline - time.monotonic())
                ):
                    source = futures[future]
                    try:
                        results[source] = future.result()
                    except Exception as e:
                        logger.warning("[SearchAgent] %s title search failed: %s", source, e)
                        results[source] = []
            except concurrent.futures.TimeoutError:
                logger.warning("[WARNING] Title search overall timeout — returning partial results")
        finally:
            generation.close()

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

        generation = self._begin_operation_generation("find_similar_papers")

        try:
            # arXiv와 Google Scholar에서 유사 논문 검색
            arxiv_future = generation.submit(
                self.arxiv_searcher.search_similar_papers,
                paper_title, paper_abstract, max_results
            )

            # 키워드 기반 검색으로 대체
            keywords = self._extract_search_keywords(paper_title, paper_abstract)
            scholar_future = generation.submit(
                self.google_scholar_searcher.search,
                keywords, max_results
            )

            # OpenAlex 키워드 검색
            openalex_future = generation.submit(
                self.openalex_searcher.search,
                keywords, max_results
            )

            # DBLP 키워드 검색
            dblp_future = generation.submit(
                self.dblp_searcher.search,
                keywords, max_results
            )

            deadline = time.monotonic() + _SEARCH_SHORT_OPERATION_TIMEOUT_SECONDS
            for source, label, future in (
                ("arxiv", "arXiv similar", arxiv_future),
                ("google_scholar", "Google Scholar", scholar_future),
                ("openalex", "OpenAlex", openalex_future),
                ("dblp", "DBLP", dblp_future),
            ):
                try:
                    results[source] = future.result(
                        timeout=max(0.0, deadline - time.monotonic())
                    )
                except Exception as e:
                    logger.warning("[WARNING] %s search timed out or failed: %s", label, e)
                    results[source] = []
        finally:
            generation.close()

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
    def llm_context_search(self, query: str, max_results_per_source: int = 10, context: str = "", *, sources=None, deadline=None, stop_event=None, snapshot_callback=None) -> Dict[str, Any]:
        """Bound analysis and retrieval by one deadline; publish private completed buckets.

        snapshot_callback runs on the collecting thread, never a provider worker.
        Async callers must marshal snapshots to their event loop before publishing.
        """
        from app.QueryAgent.query_analyzer import normalize_source_queries
        from src.utils.paper_utils import generate_result_key

        deadline = deadline if deadline is not None else time.monotonic() + _LLM_CONTEXT_SEARCH_TIMEOUT_SECONDS
        stop_event = stop_event if stop_event is not None else threading.Event()
        if sources is None:
            sources = ["arxiv", "google_scholar", "connected_papers", "openalex", "dblp"]
            if _contains_korean(query):
                sources.append("openalex_korean")
        sources = list(dict.fromkeys(sources))
        results = {source: [] for source in sources}
        metadata = {"original_query": query, "timings": {}, "timeouts": {}, "modes": {}, "executed_queries": {}, "routing": classify_search_route(query)}
        results["_metadata"] = metadata
        source_queries = normalize_source_queries(query)
        self._add_to_history(query, "llm_context_search")
        generation = self._begin_operation_generation("llm_context_search")

        def active():
            return not stop_event.is_set() and time.monotonic() < deadline

        def publish():
            if snapshot_callback is not None:
                try:
                    snapshot_callback(copy.deepcopy(results))
                except Exception as error:
                    logger.warning("[SearchAgent] Snapshot delivery failed: %s", error)

        def analyze():
            if context:
                raw = self.query_analyzer.search_with_context(query, context)
                arxiv_queries = raw.get("arxiv_queries", [])
                return {"source_queries": normalize_source_queries(query, {
                    "arxiv": arxiv_queries[0] if isinstance(arxiv_queries, list) and arxiv_queries else query,
                    "scholar_queries": raw.get("scholar_queries"),
                    "default": raw.get("translated_query", query),
                }), "keywords": raw.get("keywords", []), "search_strategy": raw.get("search_context", "")}
            return self.query_analyzer.analyze_and_prepare(query)

        futures = {}
        try:
            if active() and self.query_analyzer and metadata["routing"]["kind"] == "topic":
                future = generation.submit(analyze)
                try:
                    # Poll stop as well as deadline without detaching admission ownership.
                    while active() and not future.done():
                        concurrent.futures.wait([future], timeout=min(0.05, max(0.0, deadline - time.monotonic())))
                    if future.done():
                        analysis = future.result()
                        source_queries = normalize_source_queries(query, analysis.get("source_queries"))
                        metadata["keywords"] = analysis.get("keywords", [])
                        metadata["search_context"] = analysis.get("search_strategy", "")
                        metadata["analysis_status"] = analysis.get("analysis_status", "completed")
                        metadata["analysis"] = copy.deepcopy({key: analysis.get(key) for key in ("intent", "keywords", "improved_query", "confidence")})
                    else:
                        metadata["analysis_status"] = "timeout"
                except SearchCapacityExceeded:
                    raise
                except Exception as error:
                    logger.warning("[SearchAgent] Analysis failed: %s", error)
                    metadata["analysis_status"] = "unavailable_original_query"
            else:
                metadata["analysis_status"] = "unavailable_original_query" if metadata["routing"]["kind"] == "topic" else "skipped_exact_route"
            metadata.update(arxiv_queries=[source_queries["arxiv"]], scholar_queries=source_queries["scholar_queries"], translated_query=source_queries["default"])
            for source in sources:
                route = metadata["routing"]
                if (route["kind"] == "arxiv" and source != "arxiv") or (route["kind"] != "topic" and source == "openalex_korean") or (route["kind"] == "title" and source == "connected_papers"):
                    metadata["modes"][source] = "skipped_unsupported_route"
                    continue
                if not active():
                    metadata["modes"][source] = "timeout"
                    metadata["timeouts"][source] = True
                    continue
                worker_filters = {"_deadline": deadline, "_stop_event": stop_event, "original_query": query, "_attempts": []}
                started = time.monotonic()
                future = generation.submit(self._search_single_source, source, query, worker_filters, copy.deepcopy(source_queries), max_results_per_source)
                futures[future] = (source, started, worker_filters)
                metadata["modes"][source] = "dispatched"
                metadata["executed_queries"][source] = source_queries["scholar_queries"] if source == "google_scholar" else [source_queries.get(source, source_queries["default"])]
                if route["kind"] != "topic":
                    metadata["executed_queries"][source] = [route["value"]]

            def collect(future):
                source, started, worker_filters = futures[future]
                metadata["timings"][source] = time.monotonic() - started
                metadata["timeouts"][source] = False
                try:
                    papers = future.result()
                    seen = set()
                    for paper in papers:
                        key = generate_result_key(paper)
                        if key not in seen:
                            seen.add(key)
                            private = copy.deepcopy(paper)
                            private["_search_query"] = metadata["executed_queries"][source][0]
                            results[source].append(private)
                    results[source] = results[source][:max_results_per_source]
                    metadata["modes"][source] = self._source_outcome_mode(source, results[source], worker_filters["_attempts"])
                    metadata["timeouts"][source] = metadata["modes"][source] in ("timeout", "partial_timeout")
                    if worker_filters["_attempts"]:
                        metadata.setdefault("provider_attempts", {})[source] = copy.deepcopy(worker_filters["_attempts"])
                        metadata["executed_queries"][source] = list(dict.fromkeys(attempt["query"] for attempt in worker_filters["_attempts"]))
                except SearchCapacityExceeded:
                    raise
                except (TimeoutError, requests.Timeout) as error:
                    metadata["modes"][source] = "timeout"
                    metadata["timeouts"][source] = True
                    logger.warning("[SearchAgent] %s search timed out: %s", source, error)
                except Exception as error:
                    metadata["modes"][source] = "error"
                    logger.warning("[SearchAgent] %s search failed: %s", source, error)
                publish()

            pending = set(futures)
            while pending and active():
                done, pending = concurrent.futures.wait(pending, timeout=min(0.05, max(0.0, deadline - time.monotonic())), return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    collect(future)
            # Preserve every completion already available at the cutoff, even if
            # another provider consumed the budget or the caller stopped waiting.
            for future in list(pending):
                if future.done() and not future.cancelled():
                    collect(future)
                    pending.remove(future)
            for future in pending:
                source = futures[future][0]
                metadata["modes"][source] = "timeout"
                metadata["timeouts"][source] = True
            publish()
            return results
        finally:
            generation.close()

    @log_search_operation("Smart Search")
    def smart_search(self, query: str, max_results: int = 20, *, deadline=None, stop_event=None, snapshot_callback=None) -> Dict[str, Any]:
        """Use the same request budget for analysis, retrieval and optional ranking."""
        deadline = deadline if deadline is not None else time.monotonic() + _SEARCH_OPERATION_TIMEOUT_SECONDS
        stop_event = stop_event if stop_event is not None else threading.Event()
        search_results = self.llm_context_search(query, max(1, max_results // 2), deadline=deadline, stop_event=stop_event, snapshot_callback=snapshot_callback)
        metadata = search_results.get("_metadata", {})
        all_papers = self.deduplicator.deduplicate_cross_source({source: papers for source, papers in search_results.items() if not source.startswith("_")})
        if self.hybrid_ranker and metadata["routing"]["kind"] == "topic" and not stop_event.is_set() and time.monotonic() < deadline:
            generation = self._begin_operation_generation("smart_search")
            try:
                future = generation.submit(self.hybrid_ranker.rank_papers, query=query, papers=copy.deepcopy(all_papers), intent=metadata.get("analysis", {}).get("intent") or "paper_search", deadline=deadline, stop_event=stop_event)
                while not future.done() and not stop_event.is_set() and time.monotonic() < deadline:
                    concurrent.futures.wait([future], timeout=min(0.05, max(0.0, deadline - time.monotonic())))
                if future.done():
                    all_papers = future.result()
                else:
                    metadata["ranking_mode"] = "timeout_retrieval_order"
            except SearchCapacityExceeded:
                raise
            except Exception as error:
                logger.warning("[SmartSearch] Ranking failed: %s", error)
                metadata["ranking_mode"] = "error_retrieval_order"
            finally:
                generation.close()
        return {"papers": all_papers[:max_results], "metadata": {"query": query, "total_found": len(all_papers), "sources_searched": [source for source in search_results if not source.startswith("_")], "analysis": metadata.get("analysis", {}), "llm_queries": metadata}}

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

    def search_google_scholar(self, query: str, max_results: int = 10, sort_by: str = "relevance", year_start: int = None, year_end: int = None, author: str = None, *, deadline=None, stop_event=None, attempts=None) -> List[Dict[str, Any]]:
        self._add_to_history(query, "google_scholar")

        if year_start or year_end or author:
            return self.google_scholar_searcher.search_with_filters(query, year_start, year_end, author, max_results, deadline=deadline, stop_event=stop_event, attempts=attempts)
        else:
            return self.google_scholar_searcher.search(query, max_results, sort_by, deadline=deadline, stop_event=stop_event, attempts=attempts)

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
            if source.lower() == "connected_papers":
                return self.connected_papers_searcher.get_paper_details(paper_url)
            else:
                return None

        except Exception as e:
            logger.error("[SearchAgent] 논문 상세 정보 가져오기 오류: %s", e)
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
            logger.error("[SearchAgent] 관련 논문 가져오기 오류: %s", e)
            return []

    def get_author_profile(self, author_name: str) -> Optional[Dict[str, Any]]:
        return self.google_scholar_searcher.get_author_profile(author_name)

    def get_categories(self) -> Dict[str, List[Dict[str, str]]]:
        return {"arxiv": self.arxiv_searcher.get_categories()}

    def _source_outcome_mode(self, source_name: str, papers: List[Dict[str, Any]], attempts=None) -> str:
        """Describe what a completed source search actually did.

        Reporting a bare "searched" for a source that returned nothing makes a
        degraded source indistinguishable from a healthy one that simply had no
        matches — and hides a circuit breaker that never issued a request.
        """
        statuses = {a.get("status") for a in (attempts or [])}
        if "timeout" in statuses:
            return "partial_timeout" if papers else "timeout"
        if statuses & {"error", "circuit_open"}:
            return "partial_error" if papers else ("circuit_open" if statuses == {"circuit_open"} else "error")
        if papers:
            return "searched"
        searcher = self._SOURCE_SEARCHER_ATTRS.get(source_name)
        is_circuit_open = getattr(getattr(self, searcher or "", None), "is_circuit_open", None)
        if callable(is_circuit_open) and is_circuit_open():
            return "circuit_open"
        return "searched_empty"

    def _search_single_source(
        self,
        source_name: str,
        query: str,
        filters: Dict[str, Any],
        source_queries: Dict[str, str],
        max_results: int,
    ) -> List[Dict[str, Any]]:
        """Search a single source. Extracted for reuse by sync and async orchestration.

        Args:
            source_name: Name of the source to search (e.g. "arxiv", "openalex").
            query: Original user search query.
            filters: Full filter dict (category, sort_by, year_start, etc.).
            source_queries: Per-source optimized query overrides.
            max_results: Maximum papers to return from this source.

        Returns:
            List of paper dicts from the given source.
        """
        try:
            attempts = filters.setdefault("_attempts", [])
            budget = {"deadline": filters.get("_deadline"), "stop_event": filters.get("_stop_event"), "attempts": attempts}
            if filters.get("_stop_event", threading.Event()).is_set() or time.monotonic() >= filters.get("_deadline", float("inf")):
                attempts.append({"query": query, "status": "timeout"})
                return []
            route = classify_search_route(filters.get("original_query", query))
            if route["kind"] in ("doi", "arxiv", "title"):
                searcher = getattr(self, self._SOURCE_SEARCHER_ATTRS.get(source_name, ""), None)
                if source_name == "openalex_korean" or searcher is None:
                    return []
                if route["kind"] == "arxiv":
                    papers = self.arxiv_searcher.search_by_id(route["value"], **budget) if source_name == "arxiv" else []
                elif route["kind"] == "title":
                    method = getattr(searcher, "search_by_title", None)
                    if source_name in ("arxiv", "google_scholar", "openalex"):
                        papers = method(route["value"], max_results, **budget)
                    elif source_name == "dblp":
                        papers = method(route["value"], max_results, deadline=budget["deadline"], stop_event=budget["stop_event"])
                    else:
                        papers = method(route["value"], max_results) if method else []
                else:
                    if source_name == "arxiv":
                        papers = searcher.search(f'doi:"{route["value"]}"', max_results, deadline=filters.get("_deadline"), stop_event=filters.get("_stop_event"), attempts=filters.get("_attempts"))
                    elif source_name in ("google_scholar", "openalex"):
                        papers = searcher.search(route["value"], max_results, **budget)
                    elif source_name == "dblp":
                        papers = searcher.search(route["value"], max_results, deadline=budget["deadline"], stop_event=budget["stop_event"])
                    else:
                        papers = searcher.search(route["value"], max_results)
                if route["kind"] in ("doi", "arxiv"):
                    def matches(p):
                        values = [p.get("doi", "")] if route["kind"] == "doi" else [p.get("arxiv_id", ""), p.get("url", ""), p.get("id", "")]
                        return any(classify_search_route(str(v)) == route for v in values)
                    verified = [p for p in papers if matches(p)]
                    filters["_identity_rejections"] = len(papers) - len(verified)
                    papers = verified
                return papers
            if source_name == "arxiv":
                category = filters.get("category")
                sort_by = filters.get("sort_by", "relevance")
                arxiv_q = source_queries.get("arxiv", query)
                effective_query = f"cat:{category} AND ({arxiv_q})" if category else arxiv_q
                results_optimized = self.arxiv_searcher.search(effective_query, max_results, sort_by, deadline=filters.get("_deadline"), stop_event=filters.get("_stop_event"), attempts=filters.get("_attempts"))
                return results_optimized[:max_results]

            elif source_name == "connected_papers":
                return self.search_connected_papers(source_queries.get("default", query), max_results)

            elif source_name == "google_scholar":
                year_start = filters.get("year_start")
                year_end = filters.get("year_end")
                author = filters.get("author")
                sort_by = filters.get("sort_by", "relevance")

                # Multi-query: use scholar_queries list if available
                scholar_queries = source_queries.get("scholar_queries", [])
                if not scholar_queries:
                    scholar_queries = [source_queries.get("google_scholar", query)]

                if isinstance(scholar_queries, str):
                    scholar_queries = [scholar_queries]
                if not isinstance(scholar_queries, list):
                    scholar_queries = []
                scholar_queries = list(dict.fromkeys(q.strip() for q in scholar_queries if isinstance(q, str) and q.strip()))[:3]
                if not scholar_queries:
                    scholar_queries = [query]

                generation = self._begin_operation_generation(
                    "google_scholar_extra_queries"
                )

                try:
                    extra_futures = []
                    for sq in scholar_queries:
                        if time.monotonic() >= filters.get("_deadline", float("inf")) or filters.get("_stop_event", threading.Event()).is_set():
                            break
                        bucket_attempts = []
                        fut = generation.submit(
                            self.search_google_scholar,
                            sq, max_results, sort_by, year_start, year_end, author,
                            deadline=filters.get("_deadline"), stop_event=filters.get("_stop_event"), attempts=bucket_attempts,
                        )
                        extra_futures.append((fut, sq, bucket_attempts))

                    # Merge and deduplicate by title
                    buckets = []
                    deadline = min(filters.get("_deadline", float("inf")), time.monotonic() + _SEARCH_SHORT_OPERATION_TIMEOUT_SECONDS)
                    for fut, sq, bucket_attempts in extra_futures:
                        try:
                            extra_papers = fut.result(
                                timeout=max(0.0, deadline - time.monotonic())
                            )
                            buckets.append(extra_papers)
                            attempts.extend(copy.deepcopy(bucket_attempts))
                        except Exception as e:
                            attempts.append({"query": sq, "status": "timeout" if isinstance(e, (TimeoutError, requests.Timeout)) else "error"})
                            logger.warning("[SearchAgent] Extra scholar query failed: %s", e)
                finally:
                    generation.close()

                from src.utils.paper_utils import generate_result_key
                all_results, seen = [], set()
                for index in range(max((len(b) for b in buckets), default=0)):
                    for bucket in buckets:
                        if index < len(bucket):
                            paper = bucket[index]
                            key = generate_result_key(paper)
                            if key not in seen:
                                seen.add(key)
                                all_results.append(paper)
                                if len(all_results) == max_results:
                                    return all_results
                return all_results

            elif source_name == "openalex":
                openalex_q = source_queries.get("openalex", query)
                results_optimized = self.openalex_searcher.search(openalex_q, max_results, **budget)
                return results_optimized[:max_results]

            elif source_name == "dblp":
                dblp_q = source_queries.get("dblp", query)
                return self.dblp_searcher.search(dblp_q, max_results, deadline=budget["deadline"], stop_event=budget["stop_event"])

            elif source_name == "openalex_korean":
                original_query = filters.get("original_query")
                korean_q = source_queries.get("openalex_korean")
                # Gate here rather than in the async orchestrator alone: every
                # caller routes through this function, and the sync path (used
                # by prefetch) previously ran the Korean search for English
                # queries. search_korean costs up to two OpenAlex requests, and
                # the daily credit budget is the binding constraint.
                if not any(
                    _contains_korean(t)
                    for t in (query, original_query, korean_q)
                    if t
                ):
                    return []
                if original_query and _contains_korean(original_query):
                    korean_q = original_query
                elif not korean_q:
                    korean_q = query
                return self.openalex_searcher.search_korean(korean_q, max_results, **budget)

            else:
                logger.warning("Unknown search source: %s", source_name)
                return []

        except SearchCapacityExceeded:
            raise
        except Exception as e:
            logger.warning("Source %s search failed: %s", source_name, e)
            raise

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
        from app.QueryAgent.query_analyzer import normalize_source_queries
        source_queries = normalize_source_queries(query, filters.get("source_queries"))
        metadata = filters.setdefault("_metadata", {})
        filters = dict(filters)
        filters.setdefault("_deadline", time.monotonic() + _SEARCH_OPERATION_TIMEOUT_SECONDS)
        filters.setdefault("_stop_event", threading.Event())

        results: Dict[str, List[Dict[str, Any]]] = {}
        futures: Dict[concurrent.futures.Future, str] = {}
        worker_receipts = {}
        started_at = {}

        generation = self._begin_operation_generation("search_with_filters")

        try:
            for source in sources:
                worker_filters = dict(filters)
                worker_filters["_attempts"] = []
                worker_receipts[source] = worker_filters["_attempts"]
                started_at[source] = time.monotonic()
                fut = generation.submit(
                    self._search_single_source,
                    source, query, worker_filters, source_queries, max_results,
                )
                futures[fut] = source

            deadline = filters["_deadline"]
            try:
                for future in concurrent.futures.as_completed(
                    futures, timeout=max(0.0, deadline - time.monotonic())
                ):
                    source = futures[future]
                    metadata.setdefault("timings", {})[source] = time.monotonic() - started_at[source]
                    try:
                        results[source], _ = apply_search_filters(future.result(timeout=5), filters)
                        metadata.setdefault("provider_attempts", {})[source] = copy.deepcopy(worker_receipts[source])
                        mode = self._source_outcome_mode(source, results[source], worker_receipts[source])
                        metadata.setdefault("modes", {})[source] = mode
                        metadata.setdefault("timeouts", {})[source] = mode in ("timeout", "partial_timeout")
                    except SearchCapacityExceeded:
                        raise
                    except Exception as e:
                        logger.warning("[SearchAgent] %s search failed: %s", source, e)
                        results[source] = []
                        timed_out = isinstance(e, (TimeoutError, requests.Timeout))
                        metadata.setdefault("modes", {})[source] = "timeout" if timed_out else "error"
                        metadata.setdefault("timeouts", {})[source] = timed_out
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "[SearchAgent] search_with_filters overall timeout (60s) — returning partial results"
                )
                for future, source in futures.items():
                    if source not in results:
                        if not future.done():
                            future.cancel()  # best-effort; ThreadPool 작업 중단은 보장 안 됨
                        results[source] = []
                        metadata.setdefault("timings", {})[source] = time.monotonic() - started_at[source]
                        metadata.setdefault("modes", {})[source] = "timeout"
                        metadata.setdefault("timeouts", {})[source] = True
        finally:
            generation.close()

        return results

    async def async_search_with_filters(
        self, query: str, filters: Dict[str, Any],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Async version of search_with_filters using asyncio.gather for parallelism.

        Each source search is dispatched to the default executor via
        ``run_in_executor`` so that blocking I/O (requests, scholarly, etc.)
        does not block the event loop.  Results are gathered concurrently with
        ``asyncio.gather``.

        Args:
            query: 검색 쿼리
            filters: 필터 조건 (same schema as search_with_filters)

        Returns:
            소스별 검색 결과
        """
        sources = filters.get(
            "sources",
            ["arxiv", "connected_papers", "google_scholar", "openalex", "dblp"],
        )
        max_results = filters.get("max_results", 5)
        from app.QueryAgent.query_analyzer import normalize_source_queries
        source_queries = normalize_source_queries(query, filters.get("source_queries"))
        original_query = filters.get("original_query", query)
        metadata: Dict[str, Any] = filters.setdefault("_metadata", {})
        source_timings: Dict[str, float] = metadata.setdefault("timings", {})
        source_timeouts: Dict[str, bool] = metadata.setdefault("timeouts", {})
        source_modes: Dict[str, str] = metadata.setdefault("modes", {})

        generation = self._begin_operation_generation("search_with_filters")
        deadline = filters.setdefault("_deadline", time.monotonic() + _SEARCH_OPERATION_TIMEOUT_SECONDS)
        stop = filters.setdefault("_stop_event", threading.Event())
        partial = filters.setdefault("_partial_results", {})
        metadata["routing"] = classify_search_route(original_query)
        executed = metadata.setdefault("executed_queries", {})
        filter_drops = metadata.setdefault("filter_drops", {})

        # Per-source timeout: arXiv/Scholar get shorter budget due to rate limits
        _SOURCE_TIMEOUTS = {
            "arxiv": 15,
            "google_scholar": 20,
        }
        _DEFAULT_SOURCE_TIMEOUT = 30

        async def _run_source(source_name: str) -> tuple:
            """Run a single source search in the thread-pool executor with per-source timeout."""
            timeout = _SOURCE_TIMEOUTS.get(source_name, _DEFAULT_SOURCE_TIMEOUT)
            started_at = time.monotonic()
            source_timeouts[source_name] = False
            source_query = source_queries.get(source_name, query)
            if (
                source_name == "openalex_korean"
                and not _contains_korean(query)
                and not _contains_korean(original_query)
                and not _contains_korean(source_query)
            ):
                source_timings[source_name] = 0.0
                source_modes[source_name] = "skipped_non_korean_query"
                return source_name, []

            if stop.is_set() or time.monotonic() >= deadline:
                source_modes[source_name] = "timeout"
                source_timeouts[source_name] = True
                return source_name, []
            route = metadata["routing"]
            if (
                (route["kind"] == "arxiv" and source_name != "arxiv")
                or (route["kind"] != "topic" and source_name == "openalex_korean")
                or (route["kind"] == "title" and source_name == "connected_papers")
            ):
                source_modes[source_name] = "skipped_unsupported_route"
                source_timings[source_name] = 0.0
                return source_name, []
            effective = route["value"] if route["kind"] != "topic" else source_query
            if source_name == "openalex_korean":
                effective = original_query
            if source_name == "connected_papers" and route["kind"] == "topic":
                effective = source_queries.get("default", query)
            executed[source_name] = [effective]
            if source_name == "google_scholar" and route["kind"] == "topic":
                variants = source_queries.get("scholar_queries", [effective])
                executed[source_name] = list(dict.fromkeys(q.strip() for q in variants if isinstance(q, str) and q.strip()))[:3]
            source_modes[source_name] = "dispatched"
            worker_filters = {k: copy.deepcopy(v) for k, v in filters.items() if not k.startswith("_")}
            worker_filters.update(_deadline=min(deadline, started_at + timeout), _stop_event=stop, _attempts=[])
            underlying = generation.submit(
                self._search_single_source,
                source_name, query, worker_filters, copy.deepcopy(source_queries), max_results,
            )
            fut = asyncio.wrap_future(underlying)
            try:
                papers = await asyncio.wait_for(asyncio.shield(fut), timeout=min(timeout, max(0.0, deadline - time.monotonic())))
                papers, drops = apply_search_filters(papers, filters)
                if worker_filters["_attempts"]:
                    metadata.setdefault("provider_attempts", {})[source_name] = copy.deepcopy(worker_filters["_attempts"])
                    executed[source_name] = list(dict.fromkeys(a["query"] for a in worker_filters["_attempts"]))
                filter_drops[source_name] = drops
                rejected = worker_filters.get("_identity_rejections", 0)
                if rejected:
                    filter_drops[source_name]["identity_mismatch"] = rejected
                partial[source_name] = copy.deepcopy(papers)
                source_timings[source_name] = time.monotonic() - started_at
                source_modes[source_name] = self._source_outcome_mode(source_name, papers, worker_filters["_attempts"])
                source_timeouts[source_name] = source_modes[source_name] in ("timeout", "partial_timeout")
                if papers and route["kind"] in ("doi", "arxiv") and source_modes[source_name] == "searched":
                    source_modes[source_name] = "identity_verified"
                elif rejected and not papers and source_modes[source_name] == "searched_empty":
                    source_modes[source_name] = "identity_rejected"
                return source_name, papers
            except (TimeoutError, requests.Timeout):
                source_timings[source_name] = time.monotonic() - started_at
                source_timeouts[source_name] = True
                source_modes[source_name] = "timeout"
                if not fut.done():
                    fut.cancel()  # best-effort; ThreadPool 스레드는 중단 불가이나 Future 상태 정리
                logger.warning("[SearchAgent] source %s timed out after %.3fs", source_name, source_timings[source_name])
                return source_name, []
            except SearchCapacityExceeded:
                raise
            except Exception as error:
                source_timings[source_name] = time.monotonic() - started_at
                source_modes[source_name] = "error"
                logger.warning("[SearchAgent] source %s failed: %s", source_name, error)
                return source_name, []

        tasks = [asyncio.create_task(_run_source(s)) for s in dict.fromkeys(sources)]
        sources = list(dict.fromkeys(sources))
        try:
            completed = await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            stop.set()
            raise
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            generation.close()

        results: Dict[str, List[Dict[str, Any]]] = {}
        for source, outcome in zip(sources, completed):
            if isinstance(outcome, SearchCapacityExceeded):
                raise outcome
            if isinstance(outcome, Exception):
                logger.warning(
                    "[SearchAgent] async source %s failed: %s", source, outcome,
                )
                source_timings.setdefault(source, 0.0)
                source_timeouts.setdefault(source, False)
                source_modes[source] = "error"
                results[source] = []
            else:
                _source_name, papers = outcome
                results[_source_name] = papers

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
        from src.utils.paper_utils import generate_paper_id
        return generate_paper_id(paper)

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

    def _find_node_by_title(self, title: str, graph) -> Optional[str]:
        """제목(정규화)으로 그래프 노드 ID 찾기."""
        if not title:
            return None
        title_norm = title.strip().lower()
        for node_id in graph.nodes():
            node_data = graph.nodes[node_id]
            node_title = node_data.get('title', '')
            if node_title and node_title.strip().lower() == title_norm:
                return node_id
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
                    logger.info("[Embedding] %d개 새 논문에 대한 embedding 생성 중...", len(new_papers_list))
                    embedding_generator = EmbeddingGenerator(api_key=self.openai_api_key)
                    new_embeddings = embedding_generator.generate_batch_embeddings(new_papers_list)

                    if new_embeddings:
                        # 기존 embedding 로드 및 병합
                        existing_embeddings = self._load_existing_embeddings()
                        existing_embeddings.update(new_embeddings)

                        # 저장
                        embedding_generator.save_embeddings(existing_embeddings, self.embeddings_dir)
                        result['embeddings_generated'] = len(new_embeddings)
                        logger.info("[Embedding] %d개 embedding 생성 및 저장 완료", len(new_embeddings))
                except Exception as e:
                    logger.warning("[WARNING] Embedding 생성 중 오류: %s", e)
                    result['embedding_error'] = str(e)

            # 그래프 업데이트
            if update_graph and new_papers_list:
                try:
                    logger.info("[Graph] %d개 새 논문을 그래프에 추가 중...", len(new_papers_list))
                    graph_info = self._update_graph(new_papers_list)
                    result['graph_updated'] = True
                    result['graph_info'] = graph_info
                    logger.info("[Graph] 그래프 업데이트 완료")
                except Exception as e:
                    logger.warning("[WARNING] 그래프 업데이트 중 오류: %s", e)
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
            logger.warning("[WARNING] Embedding 로드 중 오류: %s", e)
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
                logger.info("기존 그래프 로드: %d개 노드, %d개 엣지", existing_graph.number_of_nodes(), existing_graph.number_of_edges())
            except Exception as e:
                logger.warning("[WARNING] 기존 그래프 로드 실패: %s, 새 그래프 생성", e)

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

        logger.info("%d개 새 노드 추가", nodes_added)

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

        logger.info("%d개 Citation 엣지 추가", citation_count)

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

                if similarity >= JACCARD_EDGE_THRESHOLD:
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

        logger.info("%d개 Similarity 엣지 추가", similarity_count)

        # 7. Semantic Scholar 외부 인용 엣지 수집
        ext_citation_count = 0
        citation_batch_size = min(10, len(new_papers))
        for paper in new_papers[:citation_batch_size]:
            node_id = self._find_node_in_graph(paper, existing_graph)
            if not node_id:
                continue
            try:
                citations = self.reference_collector.get_citations(
                    paper, max_citations=CITATION_MAX_PER_PAPER
                )
                for cit in citations:
                    cit_title = cit.get('title', '')
                    if not cit_title:
                        continue
                    cit_node_id = self._find_node_by_title(cit_title, existing_graph)
                    if cit_node_id and cit_node_id != node_id and not existing_graph.has_edge(cit_node_id, node_id):
                        existing_graph.add_edge(
                            cit_node_id, node_id,
                            edge_type="CITES",
                            weight=1.0,
                            is_influential=cit.get('isInfluential', False),
                            source_api="semantic_scholar",
                        )
                        ext_citation_count += 1
                time.sleep(CITATION_COLLECTION_DELAY)
            except Exception:
                continue

        if ext_citation_count > 0:
            logger.info("%d개 외부 인용(Citation) 엣지 추가", ext_citation_count)

        # 8. 그래프 저장
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
                "ext_citation_edges_added": ext_citation_count,
                "total_nodes": existing_graph.number_of_nodes(),
                "total_edges": existing_graph.number_of_edges()
            }
        except Exception as e:
            logger.warning("[WARNING] 그래프 저장 실패: %s", e)
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

        logger.info("[INFO] %d개 논문의 참고문헌 수집 시작...", len(papers_list))

        # 참고문헌 수집 및 각 논문에 추가
        total_references_found = 0

        for i, (paper_id, paper) in enumerate(existing_papers.items()):
            if max_papers and i >= max_papers:
                break

            # 이미 참고문헌이 있으면 스킵
            if paper.get('references'):
                continue

            logger.info("[%d/%d] %s... 참고문헌 수집 중", i + 1, min(max_papers or len(existing_papers), len(existing_papers)), paper.get('title', 'Unknown')[:50])

            references = self.reference_collector.get_references(paper, max_references_per_paper)

            if references:
                # 유사도 계산 (가능한 경우)
                if self.similarity_calculator:
                    try:
                        logger.info("유사도 계산 중...")
                        references = self.similarity_calculator.add_similarity_scores(paper, references)
                        # 유사도 순으로 정렬
                        references.sort(key=lambda x: x.get('similarity_score', 0), reverse=True)
                        logger.info("유사도 계산 완료 (최고: %.3f)", references[0].get('similarity_score', 0))
                    except Exception as e:
                        logger.warning("유사도 계산 실패: %s", e)

                # 논문에 references 필드 추가
                existing_papers[paper_id]['references'] = references
                total_references_found += len(references)
                logger.info("%d개 참고문헌 발견", len(references))
            else:
                existing_papers[paper_id]['references'] = []
                logger.info("참고문헌 없음")

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

    def extract_full_texts(
        self, max_papers: int = None, arxiv_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        저장된 논문들의 본문 추출

        Args:
            max_papers: 최대 처리할 논문 수
            arxiv_ids: 지정 시 해당 arXiv id의 논문만 추출(버전 접미사 무시).
                코퍼스를 앞에서부터 스캔하지 않고 특정 논문만 타깃할 때 사용.

        Returns:
            추출 결과 통계
        """
        # 저장된 논문 로드
        existing_papers = self._load_existing_papers()
        papers_list = list(existing_papers.values())

        if arxiv_ids:
            def _norm_arxiv(value):
                value = (value or "").strip().lower().replace("arxiv:", "")
                base, sep, ver = value.rpartition("v")
                if sep and base and ver.isdigit():
                    value = base
                return value

            wanted = {_norm_arxiv(a) for a in arxiv_ids if a}
            papers_list = [
                paper for paper in papers_list
                if _norm_arxiv(paper.get("arxiv_id") or paper.get("id") or "") in wanted
            ]
            logger.info(
                "[INFO] arxiv_ids 타깃 필터: %d개 매칭 (요청 %d)",
                len(papers_list), len(wanted),
            )

        if max_papers:
            papers_list = papers_list[:max_papers]

        logger.info("[INFO] %d개 논문의 본문 추출 시작...", len(papers_list))

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
