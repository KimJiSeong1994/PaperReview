"""
FastAPI backend server for Paper Review Agent
Provides REST API for React frontend
"""
import os
import sys
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import BackgroundTasks
import threading

# SSL 검증 완전 비활성화 (macOS 보안 정책 우회)
import ssl
import warnings
import os
warnings.filterwarnings('ignore')

# 환경 변수 설정
os.environ['PYTHONHTTPSVERIFY'] = '0'
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['REQUESTS_CA_BUNDLE'] = ''
os.environ['SSL_CERT_FILE'] = ''

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# urllib3 SSL 경고 비활성화
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# urllib3 monkey patch - SSL 검증 완전 우회
from urllib3.util import ssl_ as urllib3_ssl

# 원본 함수 저장
_original_ssl_wrap_socket = urllib3_ssl.ssl_wrap_socket

def patched_ssl_wrap_socket(sock, keyfile=None, certfile=None, cert_reqs=None,
                             ca_certs=None, server_hostname=None,
                             ssl_version=None, ciphers=None, ssl_context=None,
                             ca_cert_dir=None, key_password=None, ca_cert_data=None,
                             tls_in_tls=False):
    """SSL 검증을 완전히 우회하는 패치된 함수"""
    try:
        # SSL 컨텍스트 생성 (검증 없음)
        if ssl_context is None:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            # load_verify_locations 호출 방지
        return ssl_context.wrap_socket(sock, server_hostname=server_hostname)
    except Exception as e:
        print(f"[SSL PATCH] Error in patched_ssl_wrap_socket: {e}")
        # 실패 시 원본 함수 시도 (하지만 검증 비활성화)
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context.wrap_socket(sock, server_hostname=server_hostname)

# 패치 적용
urllib3_ssl.ssl_wrap_socket = patched_ssl_wrap_socket

# requests 라이브러리 패치
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.poolmanager import PoolManager
    
    class SSLAdapter(HTTPAdapter):
        """SSL 검증을 비활성화하는 커스텀 어댑터"""
        def init_poolmanager(self, *args, **kwargs):
            kwargs['ssl_context'] = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            kwargs['ssl_context'].check_hostname = False
            kwargs['ssl_context'].verify_mode = ssl.CERT_NONE
            return super().init_poolmanager(*args, **kwargs)
    
    # 기본 세션 패치
    _original_session_init = requests.Session.__init__
    
    def patched_session_init(self, *args, **kwargs):
        _original_session_init(self, *args, **kwargs)
        self.verify = False
        self.mount('https://', SSLAdapter())
        self.mount('http://', HTTPAdapter())
    
    requests.Session.__init__ = patched_session_init
    print("[SSL PATCH] Successfully patched requests.Session")
except Exception as e:
    print(f"[SSL PATCH] Warning: Could not patch requests: {e}")

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Ensure project modules are importable
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_ROOT / "src"))
sys.path.append(str(PROJECT_ROOT / "app" / "SearchAgent"))
sys.path.append(str(PROJECT_ROOT / "app" / "QueryAgent"))

from search_agent import SearchAgent
from query_analyzer import QueryAnalyzer
from relevance_filter import RelevanceFilter

# .env 파일 로드 (프로젝트 루트에서)
env_path = PROJECT_ROOT / '.env'

# .env 파일이 존재하는지 확인
if env_path.exists():
    print(f"[ENV] Loading .env file from: {env_path}")
    
    # override=True로 기존 환경변수도 덮어쓰기
    load_dotenv(dotenv_path=env_path, override=True)
    
    # .env 파일을 수동으로 파싱하여 OPENAI_API_KEY 찾기
    try:
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        
                        # OPENAI 관련 키만 처리
                        if 'OPENAI' in key.upper() and value:
                            os.environ[key] = value
                            print(f"[ENV] Set {key} = {value[:8]}...{value[-4:] if len(value) > 12 else ''}")
    except Exception as e:
        print(f"[ENV] Warning: Could not parse .env file: {e}")
else:
    print(f"[ENV] Warning: .env file not found at: {env_path}")
    load_dotenv()  # 기본 경로에서 시도

app = FastAPI(title="Paper Review Agent API")

# CORS middleware for React frontend
# 내부 네트워크 접근 허용: 모든 origin 허용 (개발 환경)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 origin 허용 (내부 네트워크 접근 가능)
    allow_credentials=False,  # allow_origins=["*"]일 때는 False여야 함
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global agent instances
# OpenAI API 키 로드 (여러 가능한 환경 변수 이름 확인)
api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY") or os.getenv("OPENAI_API")

if api_key:
    print(f"[API KEY] Loaded OpenAI API key: {api_key[:8]}...{api_key[-4:]}")
else:
    print("[API KEY] Warning: No OpenAI API key found in environment")

search_agent = SearchAgent(openai_api_key=api_key)

# Query analyzer and relevance filter (optional - only if API key available)
query_analyzer = None
relevance_filter = None

if api_key:
    try:
        # QueryAnalyzer 초기화 시도
        try:
            query_analyzer = QueryAnalyzer(api_key=api_key)
            print("[INFO] Query analyzer initialized")
        except Exception as e:
            print(f"[WARNING] Could not initialize query analyzer: {e}")
            query_analyzer = None
        
        # RelevanceFilter 초기화 시도
        try:
            relevance_filter = RelevanceFilter(api_key=api_key)
            print("[INFO] Relevance filter initialized")
        except Exception as e:
            print(f"[WARNING] Could not initialize relevance filter: {e}")
            relevance_filter = None
            
    except Exception as e:
        print(f"[WARNING] Could not initialize query analyzer/filter: {e}")
else:
    print("[WARNING] No OpenAI API key - query analysis and relevance filtering disabled")


class SearchRequest(BaseModel):
    query: str
    max_results: int = 20
    sources: List[str] = ["arxiv", "connected_papers", "google_scholar"]
    sort_by: str = "relevance"
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    author: Optional[str] = None
    category: Optional[str] = None
    fast_mode: bool = True  # 빠른 모드 (관련성 필터링 스킵, 백그라운드 처리)
    save_papers: bool = True  # 검색 결과 자동 저장
    collect_references: bool = False  # 참고문헌 자동 수집 (성능 개선: 기본 비활성화)
    extract_texts: bool = False  # 본문 자동 추출 (성능 개선: 기본 비활성화)
    max_references_per_paper: int = 10  # 논문당 최대 참고문헌 수 (성능 개선: 20->10)
    use_llm_search: bool = False  # LLM 컨텍스트 기반 검색 사용 여부
    search_context: str = ""  # 추가 검색 컨텍스트


class SearchResponse(BaseModel):
    results: Dict[str, List[Dict[str, Any]]]
    total: int
    query_analysis: Optional[Dict[str, Any]] = None


class QueryAnalysisRequest(BaseModel):
    query: str


class QueryAnalysisResponse(BaseModel):
    intent: str
    keywords: List[str]
    improved_query: str
    search_filters: Dict[str, Any]
    confidence: float
    original_query: str
    analysis_details: Optional[str] = None


@app.get("/")
async def root():
    return {"message": "Paper Review Agent API", "version": "1.0.0"}


@app.post("/api/analyze-query", response_model=QueryAnalysisResponse)
async def analyze_query(request: QueryAnalysisRequest):
    """Analyze user query to understand intent and extract keywords"""
    if not query_analyzer:
        raise HTTPException(status_code=503, detail="Query analysis service unavailable (OpenAI API key not configured)")
    
    try:
        print(f"[API] Analyzing query: {request.query}")
        analysis = query_analyzer.analyze_query(request.query)
        print(f"[API] Analysis result: intent={analysis.get('intent')}, confidence={analysis.get('confidence')}")
        return QueryAnalysisResponse(**analysis)
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[API] Error in query analysis: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Query analysis failed: {str(e)}")


class LLMSearchRequest(BaseModel):
    query: str
    max_results: int = 20
    context: str = ""  # 추가 컨텍스트 (이전 검색 등)
    save_papers: bool = True


class LLMSearchResponse(BaseModel):
    results: Dict[str, List[Dict[str, Any]]]
    total: int
    metadata: Dict[str, Any]


@app.post("/api/llm-search", response_model=LLMSearchResponse)
async def llm_context_search(request: LLMSearchRequest):
    """
    LLM 컨텍스트 기반 검색
    
    LLM이 사용자 쿼리를 분석하고 최적화된 검색 쿼리를 생성하여
    arXiv와 Google Scholar에서 검색합니다.
    
    한글 쿼리도 자동으로 영어로 번역하여 검색합니다.
    """
    if not query_analyzer:
        raise HTTPException(
            status_code=503, 
            detail="LLM search service unavailable (OpenAI API key not configured)"
        )
    
    try:
        import time
        start_time = time.time()
        
        print(f"[API] LLM Context Search: {request.query}")
        
        # LLM 컨텍스트 기반 검색 수행
        results = search_agent.llm_context_search(
            query=request.query,
            max_results_per_source=request.max_results,
            context=request.context
        )
        
        # 메타데이터 분리
        metadata = results.pop('_metadata', {})
        
        total = sum(len(papers) for papers in results.values())
        search_time = time.time() - start_time
        
        print(f"[API] LLM Search completed: {total} papers in {search_time:.2f}s")
        
        # 결과 저장 (옵션)
        if request.save_papers and total > 0:
            try:
                save_result = search_agent.save_papers(
                    results, 
                    request.query,
                    generate_embeddings=False,
                    update_graph=True
                )
                metadata['save_result'] = {
                    'new_papers': save_result.get('new_papers', 0),
                    'duplicates': save_result.get('duplicates', 0)
                }
                print(f"[API] Saved: {save_result.get('new_papers', 0)} new papers")
            except Exception as e:
                print(f"[API] Error saving papers: {e}")
        
        # 검색 시간 추가
        metadata['search_time'] = round(search_time, 2)
        
        return LLMSearchResponse(
            results=results,
            total=total,
            metadata=metadata
        )
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[API] LLM Search error: {error_trace}")
        raise HTTPException(status_code=500, detail=f"LLM search failed: {str(e)}")


@app.post("/api/smart-search")
async def smart_search(request: LLMSearchRequest):
    """
    스마트 검색 - LLM 분석 + 다중 검색 전략 조합
    
    1. LLM이 쿼리를 분석하고 검색 전략 결정
    2. 최적화된 쿼리로 다중 소스 검색
    3. 결과 병합 및 중복 제거
    4. 관련성 순 정렬
    """
    try:
        import time
        start_time = time.time()
        
        print(f"[API] Smart Search: {request.query}")
        
        # 스마트 검색 수행
        result = search_agent.smart_search(
            query=request.query,
            max_results=request.max_results
        )
        
        search_time = time.time() - start_time
        result['metadata']['search_time'] = round(search_time, 2)
        
        print(f"[API] Smart Search completed: {len(result['papers'])} papers in {search_time:.2f}s")
        
        # 결과 저장 (옵션)
        if request.save_papers and result['papers']:
            try:
                # papers 리스트를 소스별로 분류
                results_by_source = {"arxiv": [], "connected_papers": [], "google_scholar": []}
                for paper in result['papers']:
                    source = paper.pop('_source', 'arxiv')
                    if source in results_by_source:
                        results_by_source[source].append(paper)
                
                save_result = search_agent.save_papers(
                    results_by_source, 
                    request.query,
                    generate_embeddings=False,
                    update_graph=True
                )
                result['metadata']['save_result'] = {
                    'new_papers': save_result.get('new_papers', 0),
                    'duplicates': save_result.get('duplicates', 0)
                }
            except Exception as e:
                print(f"[API] Error saving papers: {e}")
        
        return result
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[API] Smart Search error: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Smart search failed: {str(e)}")


def _enrich_papers_background(query: str, results: Dict[str, List[Dict[str, Any]]], 
                              collect_refs: bool, extract_text: bool, max_refs: int):
    """백그라운드에서 논문 enrichment 수행"""
    try:
        print(f"[백그라운드] Enrichment 작업 시작...")
        
        # 논문 저장
        save_result = search_agent.save_papers(
            results, 
            query,
            generate_embeddings=False,  # OpenAI quota 초과로 비활성화
            update_graph=True
        )
        print(f"[백그라운드] 저장 완료: {save_result.get('new_papers', 0)} 새 논문")
        
        # 참고문헌 수집 (새로 저장된 논문에 대해서만)
        new_papers_count = save_result.get('new_papers', 0)
        if collect_refs and new_papers_count > 0:
            # 최대 10개 논문에 대해서만 참고문헌 수집 (성능 개선)
            max_papers_to_collect = min(new_papers_count, 10)
            print(f"[백그라운드] 참고문헌 수집 중 (최대 {max_papers_to_collect}개 논문)...")
            ref_result = search_agent.collect_references(max_refs, max_papers_to_collect)
            print(f"[백그라운드] 참고문헌 수집 완료: {ref_result.get('references_found', 0)}")
        
        # 본문 추출
        if extract_text and save_result.get('new_papers', 0) > 0:
            print(f"[백그라운드] 본문 추출 중...")
            text_result = search_agent.extract_full_texts(save_result.get('new_papers'))
            print(f"[백그라운드] 본문 추출 완료: {text_result.get('texts_extracted', 0)}")
        
        print(f"[백그라운드] Enrichment 완료")
    except Exception as e:
        print(f"[백그라운드] Enrichment 오류: {e}")
        import traceback
        traceback.print_exc()


@app.post("/api/search", response_model=SearchResponse)
async def search_papers(request: SearchRequest):
    """Search papers across multiple sources with automatic query analysis"""
    try:
        import traceback
        import time
        
        start_time = time.time()
        
        # 질의 분석 수행 (query_analyzer가 초기화된 경우에만)
        query_analysis = None
        if query_analyzer:
            try:
                analysis_start = time.time()
                print(f"[API] Analyzing query: {request.query}")
                query_analysis = query_analyzer.analyze_query(request.query)
                print(f"[API] Query analysis: intent={query_analysis.get('intent')}, keywords={query_analysis.get('keywords')}, confidence={query_analysis.get('confidence')} (took {time.time()-analysis_start:.2f}s)")
            except Exception as e:
                print(f"[API] Query analysis failed (continuing with original query): {e}")
        else:
            print(f"[API] Query analysis skipped (OpenAI API key not configured)")
        
        # 분석 결과를 기반으로 필터 자동 적용 (사용자가 명시적으로 지정하지 않은 경우)
        filters = {
            "sources": request.sources,
            "max_results": request.max_results,
            "sort_by": request.sort_by,
            "year_start": request.year_start or (query_analysis.get("search_filters", {}).get("year_start") if query_analysis else None),
            "year_end": request.year_end or (query_analysis.get("search_filters", {}).get("year_end") if query_analysis else None),
            "author": request.author or (query_analysis.get("search_filters", {}).get("author") if query_analysis else None),
            "category": request.category or (query_analysis.get("search_filters", {}).get("category") if query_analysis else None),
        }
        
        # 개선된 쿼리 사용 (분석 결과가 있고 신뢰도가 높은 경우)
        search_query = request.query
        if query_analysis and query_analysis.get("confidence", 0) > 0.7:
            improved_query = query_analysis.get("improved_query")
            if improved_query and improved_query != request.query:
                print(f"[API] Using improved query: {improved_query}")
                search_query = improved_query
        
        search_start = time.time()
        print(f"[API] Searching for: {search_query}")
        print(f"[API] Filters: {filters}")
        
        # LLM 컨텍스트 기반 검색 사용 여부 확인
        if request.use_llm_search and query_analyzer:
            print(f"[API] Using LLM Context Search...")
            results = search_agent.llm_context_search(
                search_query, 
                max_results_per_source=request.max_results,
                context=request.search_context
            )
            # 메타데이터 분리
            llm_metadata = results.pop('_metadata', None)
            if llm_metadata:
                print(f"[API] LLM generated queries: arXiv={len(llm_metadata.get('arxiv_queries', []))}, Scholar={len(llm_metadata.get('scholar_queries', []))}")
        else:
            results = search_agent.search_with_filters(search_query, filters)
        
        search_time = time.time() - search_start
        print(f"[API] Raw search results: {sum(len(papers) for papers in results.values())} papers found (took {search_time:.2f}s)")
        
        # 관련성 필터링 적용 (fast_mode가 아니고 relevance_filter가 초기화된 경우에만)
        if not request.fast_mode and relevance_filter and results:
            try:
                print(f"[API] Applying relevance filtering (parallel mode)...")
                
                # 모든 소스의 논문을 합침
                all_papers = []
                for source, papers in results.items():
                    for paper in papers:
                        paper['source'] = source  # 소스 정보 보존
                        all_papers.append(paper)
                
                if all_papers:
                    # 관련성 필터링 (임계값 0.5, 병렬 처리)
                    filtered_papers = relevance_filter.filter_papers(
                        request.query,  # 원본 쿼리 사용 (사용자가 입력한 그대로)
                        all_papers,
                        threshold=0.5,
                        max_papers=request.max_results,
                        parallel=True  # 병렬 처리 활성화
                    )
                    
                    # 소스별로 다시 분류
                    results = {}
                    for source in request.sources:
                        results[source] = [p for p in filtered_papers if p.get('source') == source]
                    
                    print(f"[API] Filtered results: {len(filtered_papers)} papers (threshold: 0.5)")
                else:
                    print(f"[API] No papers to filter")
                    
            except Exception as e:
                print(f"[API] Relevance filtering failed (using unfiltered results): {e}")
                import traceback
                traceback.print_exc()
        else:
            if request.fast_mode:
                print(f"[API] Relevance filtering skipped (fast mode enabled)")
            elif not relevance_filter:
                print(f"[API] Relevance filtering skipped (OpenAI API key not configured)")
        
        # Ensure all sources are in results
        for source in request.sources:
            if source not in results:
                results[source] = []
        
        total = sum(len(papers) for papers in results.values())
        
        # 논문 저장 및 enrichment (옵션에 따라)
        if request.save_papers and total > 0:
            if request.fast_mode:
                # Fast mode: 백그라운드에서 처리 (즉시 결과 반환)
                print(f"[API] Fast mode: Starting background enrichment for {total} papers...")
                thread = threading.Thread(
                    target=_enrich_papers_background,
                    args=(request.query, results, request.collect_references, 
                          request.extract_texts, request.max_references_per_paper)
                )
                thread.daemon = True
                thread.start()
                print(f"[API] Background enrichment started (thread)")
            else:
                # Normal mode: 동기적 처리 (모든 작업 완료 후 결과 반환)
                try:
                    print(f"[API] Saving {total} papers...")
                    save_result = search_agent.save_papers(
                        results, 
                        request.query,
                        generate_embeddings=False,  # OpenAI quota 초과로 비활성화
                        update_graph=True
                    )
                    print(f"[API] Saved: {save_result.get('new_papers', 0)} new, {save_result.get('duplicates', 0)} duplicates")
                    
                    # 참고문헌 수집 (옵션, 최대 10개 논문으로 제한)
                    new_papers_count = save_result.get('new_papers', 0)
                    if request.collect_references and new_papers_count > 0:
                        max_papers_to_collect = min(new_papers_count, 10)
                        print(f"[API] Collecting references for {max_papers_to_collect} papers...")
                        ref_result = search_agent.collect_references(
                            request.max_references_per_paper,
                            max_papers=max_papers_to_collect
                        )
                        print(f"[API] References collected: {ref_result.get('references_found', 0)}")
                    
                    # 본문 추출 (옵션)
                    if request.extract_texts:
                        print(f"[API] Extracting full texts for saved papers...")
                        text_result = search_agent.extract_full_texts(
                            max_papers=save_result.get('new_papers', 0) if save_result.get('new_papers', 0) > 0 else None
                        )
                        print(f"[API] Texts extracted: {text_result.get('texts_extracted', 0)}")
                        
                except Exception as e:
                    print(f"[API] Error in saving/enriching papers: {e}")
                    import traceback
                    traceback.print_exc()
        
        total_time = time.time() - start_time
        print(f"[API] Search completed in {total_time:.2f}s")
        
        # 검색 결과를 캐시에 저장 (Deep Research에서 사용)
        try:
            cache_dir = Path("data/cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / "last_search_results.json"
            
            # doc_id 생성 함수 (djb2 해시)
            def _generate_doc_id(title: str) -> str:
                hash_value = 0
                for char in title:
                    hash_value = ((hash_value << 5) - hash_value) + ord(char)
                    hash_value = hash_value & 0x7FFFFFFF
                return str(hash_value)
            
            # 각 논문에 doc_id 추가
            for paper in results:
                if 'doc_id' not in paper or not paper.get('doc_id'):
                    title = paper.get('title', '')
                    paper['doc_id'] = _generate_doc_id(title)
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"[API] Search results cached: {len(results)} papers (with doc_ids)")
        except Exception as cache_error:
            print(f"[API] Cache save warning: {cache_error}")
        
        return SearchResponse(
            results=results,
            total=total,
            query_analysis=query_analysis
        )
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[API] Error in search: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@app.post("/api/save")
async def save_papers(
    results: Dict[str, List[Dict[str, Any]]], 
    query: str = "",
    generate_embeddings: bool = False,  # OpenAI quota 초과로 기본값 비활성화
    update_graph: bool = True
):
    """
    Save search results to database with automatic embedding generation and graph update
    
    Args:
        results: Search results (papers by source)
        query: Search query
        generate_embeddings: Whether to generate embeddings for new papers
        update_graph: Whether to update the graph with new papers
    """
    try:
        print(f"[API] Saving {sum(len(papers) for papers in results.values())} papers...")
        print(f"[API] Generate embeddings: {generate_embeddings}, Update graph: {update_graph}")
        
        save_info = search_agent.save_papers(
            results, 
            query, 
            generate_embeddings=generate_embeddings,
            update_graph=update_graph
        )
        
        print(f"[API] Save completed: {save_info.get('new_papers', 0)} new papers, "
              f"{save_info.get('embeddings_generated', 0)} embeddings generated, "
              f"graph updated: {save_info.get('graph_updated', False)}")
        
        return save_info
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[API] Error in save: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Save failed: {str(e)}")


@app.get("/api/papers/count")
async def get_papers_count():
    """Get count of saved papers"""
    return {"count": search_agent.get_saved_papers_count()}


@app.get("/api/papers")
async def get_saved_papers():
    """Get all saved papers"""
    try:
        papers_file = search_agent.papers_file
        if not os.path.exists(papers_file):
            return {"papers": []}
        
        import json
        with open(papers_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {"papers": data.get("papers", [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/papers")
async def clear_papers():
    """Clear all saved papers"""
    success = search_agent.clear_saved_papers()
    return {"success": success}


@app.post("/api/collect-references")
async def collect_references(max_references_per_paper: int = 10, max_papers: int = None):
    """
    저장된 논문들의 참고문헌 수집
    
    Args:
        max_references_per_paper: 논문당 최대 수집할 참고문헌 수
        max_papers: 처리할 최대 논문 수
    """
    try:
        print(f"[API] Collecting references: max_references_per_paper={max_references_per_paper}, max_papers={max_papers}")
        result = search_agent.collect_references(max_references_per_paper, max_papers)
        print(f"[API] References collected: {result.get('references_found', 0)} references for {result.get('papers_processed', 0)} papers")
        return result
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[API] Error in collect references: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Reference collection failed: {str(e)}")


@app.post("/api/extract-texts")
async def extract_texts(max_papers: int = None):
    """
    저장된 논문들의 본문 추출
    
    Args:
        max_papers: 처리할 최대 논문 수
    """
    try:
        print(f"[API] Extracting full texts: max_papers={max_papers}")
        result = search_agent.extract_full_texts(max_papers)
        print(f"[API] Texts extracted: {result.get('texts_extracted', 0)}/{result.get('papers_processed', 0)} papers")
        return result
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[API] Error in extract texts: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Text extraction failed: {str(e)}")


@app.post("/api/enrich-papers")
async def enrich_papers(
    collect_references: bool = True,
    extract_texts: bool = True,
    max_references_per_paper: int = 10,
    max_papers: int = None
):
    """
    저장된 논문들을 enrichment (참고문헌 + 본문 추출 + 그래프 업데이트)
    
    Args:
        collect_references: 참고문헌 수집 여부
        extract_texts: 본문 추출 여부
        max_references_per_paper: 논문당 최대 참고문헌 수
        max_papers: 처리할 최대 논문 수
    """
    try:
        results = {
            "references": None,
            "texts": None,
            "success": True
        }
        
        # 참고문헌 수집
        if collect_references:
            print(f"[API] Step 1: Collecting references...")
            ref_result = search_agent.collect_references(max_references_per_paper, max_papers)
            results["references"] = ref_result
            print(f"[API] References collected: {ref_result.get('references_found', 0)}")
        
        # 본문 추출
        if extract_texts:
            print(f"[API] Step 2: Extracting full texts...")
            text_result = search_agent.extract_full_texts(max_papers)
            results["texts"] = text_result
            print(f"[API] Texts extracted: {text_result.get('texts_extracted', 0)}")
        
        print(f"[API] Paper enrichment completed")
        return results
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[API] Error in enrich papers: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Paper enrichment failed: {str(e)}")


@app.post("/api/graph-data")
async def get_graph_data(request: Dict[str, Any]):
    """
    Generate graph data for visualization
    Accepts papers JSON string in request body or uses saved papers
    """
    try:
        import json
        import networkx as nx
        
        papers_json = request.get("papers_json")
        if papers_json:
            papers_data = json.loads(papers_json)
            # Ensure all papers have doc_id for consistent matching with frontend
            for paper in papers_data:
                if 'doc_id' not in paper:
                    # Generate doc_id using stable hashlib (consistent across sessions)
                    title = paper.get("title", "")
                    import hashlib
                    doc_id = str(int(hashlib.md5(title.encode('utf-8')).hexdigest()[:15], 16)) if title else ""
                    paper['doc_id'] = doc_id
        else:
            papers_file = search_agent.papers_file
            if not os.path.exists(papers_file):
                return {"nodes": [], "edges": []}
            with open(papers_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                papers_data = data.get("papers", [])
        
        # Build similarity graph (similar to web_app.py logic)
        def _title_tokens(text: str) -> List[str]:
            import re
            words = re.findall(r"\b\w+\b", text.lower())
            return [w for w in words if len(w) > 3]
        
        graph = nx.Graph()
        # Ensure all papers have doc_id for consistent matching with frontend
        # Frontend uses hashString function which implements djb2-like hash
        def generate_doc_id(title: str) -> str:
            """Generate doc_id matching frontend hashString function (djb2)"""
            hash_value = 0
            for char in title:
                char_code = ord(char)
                hash_value = ((hash_value << 5) - hash_value) + char_code
                hash_value = hash_value & 0x7FFFFFFF  # Keep positive 32bit
            return str(hash_value)
        
        for paper in papers_data:
            if 'doc_id' not in paper:
                title = paper.get("title", "")
                doc_id = generate_doc_id(title)
                paper['doc_id'] = doc_id
        
        for paper in papers_data:
            doc_id = paper.get("doc_id")
            if not doc_id:
                # Fallback if doc_id still missing - use stable hashlib
                title = paper.get("title", "")
                import hashlib
                doc_id = str(int(hashlib.md5(title.encode('utf-8')).hexdigest()[:15], 16)) if title else ""
                paper['doc_id'] = doc_id
            
            # Create node attributes dict, avoiding duplicates
            node_attrs = {
                "weight": max(paper.get("citations", 1), 1),
                "year": paper.get("year"),
                "title": paper.get("title", ""),
            }
            # Add other paper attributes, but don't override existing ones
            for key, value in paper.items():
                if key not in node_attrs and key != 'doc_id':
                    node_attrs[key] = value
            graph.add_node(doc_id, **node_attrs)
        
        # Add edges based on title similarity
        token_cache = {p.get("doc_id", str(abs(hash(p.get("title", ""))))): set(_title_tokens(p.get("title", ""))) 
                      for p in papers_data}
        
        paper_list = list(papers_data)
        for idx, paper in enumerate(paper_list):
            for jdx in range(idx + 1, len(paper_list)):
                other = paper_list[jdx]
                doc_id1 = paper.get("doc_id") or str(abs(hash(paper.get("title", ""))))
                doc_id2 = other.get("doc_id") or str(abs(hash(other.get("title", ""))))
                
                base_tokens = token_cache.get(doc_id1, set())
                other_tokens = token_cache.get(doc_id2, set())
                if not base_tokens or not other_tokens:
                    continue
                
                overlap = len(base_tokens & other_tokens)
                union = len(base_tokens | other_tokens)
                score = overlap / union if union else 0
                
                if score >= 0.12:
                    graph.add_edge(doc_id1, doc_id2, weight=round(score, 3))
        
        # Generate layout centered around graph centroid
        # 먼저 기본 spring layout 생성 (k 값을 조정하여 노드 간 거리 설정)
        layout = nx.spring_layout(graph, seed=42, k=0.75, iterations=50)
        
        # 그래프의 centroid 계산
        if len(layout) > 0:
            # 모든 노드 위치의 평균 (centroid)
            centroid_x = sum(pos[0] for pos in layout.values()) / len(layout)
            centroid_y = sum(pos[1] for pos in layout.values()) / len(layout)
            
            # 모든 노드를 centroid를 중심으로 재배치
            centered_layout = {}
            for node_id, (x, y) in layout.items():
                centered_layout[node_id] = (x - centroid_x, y - centroid_y)
            
            layout = centered_layout
        
        # Extract nodes and edges for frontend
        nodes = []
        if len(graph.nodes()) > 0:
            for node_id in graph.nodes():
                node_data = graph.nodes[node_id]
                x, y = layout.get(node_id, (0, 0))
                nodes.append({
                    "id": str(node_id),
                    "x": float(x),
                    "y": float(y),
                    "title": node_data.get("title", ""),
                    "year": node_data.get("year"),
                    "citations": node_data.get("citations", 0),
                    "authors": node_data.get("authors", []),
                    "abstract": node_data.get("abstract", ""),
                    "url": node_data.get("url", ""),
                    "pdf_url": node_data.get("pdf_url", ""),
                    "doi": node_data.get("doi", ""),
                    "source": node_data.get("source", ""),
                    "journal": node_data.get("journal", ""),
                    "doc_id": str(node_id),  # Ensure doc_id is included for matching
                    "weight": node_data.get("weight", 1),
                })
            
            edges = []
            for start, end in graph.edges():
                edges.append({
                    "source": str(start),
                    "target": str(end),
                    "weight": graph.edges[start, end].get("weight", 0.1),
                })
        else:
            edges = []
        
        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Deep Agent Review Endpoints ====================

# Review session storage
review_sessions: Dict[str, Dict[str, Any]] = {}
review_sessions_lock = threading.Lock()


def run_fast_review(session_id: str, paper_ids: List[str], model: str, workspace: Any, papers_data: Optional[List[Dict[str, Any]]] = None) -> dict:
    """
    Fast Mode: 단일 LLM 호출로 모든 논문을 빠르게 분석
    
    기존 Deep Mode 대비 5~10배 빠름
    
    Args:
        papers_data: 프론트엔드에서 직접 전달받은 논문 데이터 (우선 사용)
    """
    from openai import OpenAI
    from app.DeepAgent.tools.paper_loader import load_papers_from_ids
    from datetime import datetime
    import hashlib
    
    print(f"[Fast Review] 시작: {len(paper_ids)}편 논문")
    
    # 논문 로드 (papers_data가 있으면 직접 사용, 없으면 ID로 검색)
    if papers_data and len(papers_data) > 0:
        papers = papers_data
        print(f"[Fast Review] {len(papers)}편 논문 (프론트엔드에서 직접 전달)")
    else:
        papers = load_papers_from_ids(paper_ids)
        print(f"[Fast Review] {len(papers)}편 논문 로드됨 (ID 검색)")
    
    if not papers:
        return {"status": "failed", "error": "논문을 로드할 수 없습니다"}
    
    # OpenAI 클라이언트 초기화 (langchain 대신 직접 사용)
    deep_research_model = "gpt-4.1"
    print(f"[Fast Review] Deep Research 모델: {deep_research_model}")
    client = OpenAI()
    
    # 논문 데이터 확장 준비 (가용 메타데이터 최대 활용)
    papers_text = []
    for i, paper in enumerate(papers, 1):
        title = paper.get('title', f'Paper {i}') or f'Paper {i}'
        abstract = paper.get('abstract') or paper.get('summary') or '초록 없음'
        authors = paper.get('authors', [])
        year = paper.get('year') or paper.get('published') or 'N/A'

        # Format authors
        if authors:
            if isinstance(authors[0], dict):
                author_names = [a.get('name', str(a)) for a in authors[:5]]
            else:
                author_names = [str(a) for a in authors[:5]]
            author_str = ', '.join(author_names)
            if len(authors) > 5:
                author_str += f' 외 {len(authors) - 5}명'
        else:
            author_str = '저자 미상'

        # abstract가 string인지 확인
        if not isinstance(abstract, str):
            abstract = str(abstract) if abstract else '초록 없음'

        # 추가 메타데이터 수집
        categories = paper.get('categories', [])
        keywords = paper.get('keywords', [])
        citations = paper.get('citations')
        doi = paper.get('doi', '')
        url = paper.get('url', '') or paper.get('pdf_url', '')
        venue = paper.get('venue') or paper.get('journal') or paper.get('journal_ref', '')
        full_text = paper.get('full_text', '')

        # 카테고리 포맷
        cat_str = ', '.join(categories[:5]) if categories else ''
        kw_str = ', '.join(keywords[:8]) if keywords else ''

        paper_entry = f"""
### 논문 {i}: {title}
- **저자**: {author_str}
- **발표**: {year}"""

        if venue:
            paper_entry += f"\n- **학회/저널**: {venue}"
        if cat_str:
            paper_entry += f"\n- **분야**: {cat_str}"
        if kw_str:
            paper_entry += f"\n- **키워드**: {kw_str}"
        if citations is not None and citations > 0:
            paper_entry += f"\n- **피인용 횟수**: {citations}회"
        if doi:
            paper_entry += f"\n- **DOI**: {doi}"
        if url:
            paper_entry += f"\n- **URL**: {url}"

        paper_entry += f"\n- **초록**: {abstract[:3000]}"

        # 전문(full_text) 가용 시 방법론/결과 부분 추가 제공
        if full_text and len(full_text) > 500:
            paper_entry += f"\n- **본문 발췌 (방법론/결과 중심)**: {full_text[:5000]}"

        papers_text.append(paper_entry)
    
    combined_papers = "\n".join(papers_text)
    
    # 심층 분석 프롬프트 - 비판적 사고와 통찰력 기반
    prompt = f"""당신은 Nature, Science 등 최상위 저널의 리뷰어이자, 해당 분야에서 20년 이상 핵심 연구를 수행해온 석학 교수입니다.
다음 {len(papers)}편의 논문을 단순히 요약하는 것이 아니라, **비판적으로 분석하고 학술적 통찰을 도출**하여
박사과정 학생 및 연구자들이 연구 방향 설정에 직접 활용할 수 있는 수준의 심층 문헌 고찰 보고서를 작성해주세요.

**분석 철학**:
- 표면적 요약이 아닌, 각 논문의 **핵심 아이디어의 본질**을 꿰뚫는 분석
- "무엇을 했는가"보다 "왜 이 접근이 효과적인가/비효과적인가"에 초점
- 논문들을 종합했을 때 비로소 보이는 **메타 수준의 패턴과 통찰** 도출
- 모호한 표현("~할 수 있다", "중요하다") 대신 **구체적 근거와 논리적 추론** 사용

## 분석 대상 논문들:
{combined_papers}

---

## 분석 품질 기준 (반드시 준수)

1. 모든 주장에는 **논문의 구체적 내용을 근거**로 제시할 것
2. "일반적으로", "보통" 같은 일반론 사용 금지 - **해당 논문만의 고유한 분석**만 작성
3. 방법론 설명 시 **알고리즘의 핵심 작동 원리**를 기술적으로 서술할 것
4. 실험 결과는 반드시 **수치 데이터**와 함께 제시할 것
5. 한계점 분석 시 저자가 명시하지 않은 **숨겨진 가정과 잠재적 문제**도 도출할 것
6. 각 논문 분석은 **최소 800자 이상** 깊이 있게 작성할 것

---

# 체계적 문헌 고찰: 선정 연구 논문의 심층 분석

---

**리뷰 날짜**: {datetime.now().strftime('%Y년 %m월 %d일')}
**분석 논문 수**: {len(papers)}편
**리뷰 방법론**: AI 기반 심층 연구 분석 시스템 (비판적 분석 프레임워크)

---

## 초록 (Abstract)

[400-600자로 작성. 단순 요약이 아닌 분석적 초록:]
- 분석 대상 논문들이 다루는 **공통 연구 질문**과 그 학술적 중요성
- 각 논문이 이 질문에 대해 제시하는 **서로 다른 접근법**과 그 차이의 본질
- 논문들을 종합했을 때 드러나는 **핵심 연구 트렌드와 패러다임 전환**
- 본 리뷰가 해당 분야 연구자에게 제공하는 **고유한 학술적 가치**

**키워드**: [논문들의 핵심 개념을 관통하는 키워드 7-10개]

---

## 1. 서론

### 1.1 연구 배경 및 학술적 맥락
[500자 이상. 깊이 있는 맥락 분석:]
- 이 연구 분야가 현재 직면한 **근본적인 도전과 미해결 문제**
- 최근 5년간 이 분야에서 일어난 **패러다임 변화**와 그 동인
- 분석 대상 논문들이 이 큰 그림 속에서 차지하는 **위치와 의미**
- 기존 연구의 한계 중 이 논문들이 구체적으로 **어떤 간극을 메우고 있는지**

### 1.2 본 리뷰의 목적과 차별점
[단순 요약을 넘어서는 본 리뷰의 고유 가치를 4-5가지로 서술]

### 1.3 분석 프레임워크
| 분석 차원 | 핵심 질문 | 평가 관점 |
|-----------|----------|----------|
| 문제 정의 | 이 문제가 왜 중요하며, 어떤 실질적 영향을 미치는가? | 참신성, 실용성, 학술적 의의 |
| 방법론적 혁신 | 기존 방법 대비 무엇이 근본적으로 다른가? | 기술적 차별성, 이론적 근거 |
| 실험적 엄밀성 | 실험 설계가 주장을 충분히 뒷받침하는가? | 데이터셋 적절성, 베이스라인 공정성, 재현성 |
| 이론적 깊이 | 왜 이 방법이 작동하는지 설명할 수 있는가? | 이론적 분석, 수렴성, 일반화 가능성 |
| 실질적 영향 | 이 연구가 실제 문제 해결에 얼마나 기여하는가? | 응용 가능성, 확장성, 실무 적용 |

---

## 2. 개별 논문 심층 분석

[**각 논문에 대해 아래 형식으로 최소 800자 이상, 비판적 시각으로 분석:**]

### 2.N [논문 제목]

**기본 정보**
- **저자**: [저자명]
- **발표**: [연도/학회/저널]

**연구 문제의 본질 분석**
[단순한 문제 기술이 아닌, 이 문제가 중요한 이유를 학술적 맥락에서 깊이 있게 분석.
이 문제를 해결하면 어떤 파급 효과가 있는지, 기존에 왜 해결되지 못했는지를 3-5문장으로 서술]

**핵심 방법론 및 기술적 혁신**
[알고리즘의 핵심 작동 원리를 기술적으로 설명. 단순히 "X 기법을 사용했다"가 아닌:
- 이 방법이 **왜** 이 문제에 적합한지 (이론적 근거)
- 기존 방법과 **구체적으로 어떤 점**이 다른지 (기술적 차별점)
- 핵심 알고리즘의 **작동 메커니즘** (입력->처리->출력 흐름)
- 계산 복잡도나 확장성 측면의 특성]

**주요 기여 (이론적 vs 실용적 구분)**
- 이론적 기여: [새로운 프레임워크, 수학적 증명, 분석적 통찰 등]
- 실용적 기여: [도구 개발, 성능 향상, 새로운 응용 등]

**실험 결과의 비판적 검토**
[주요 결과를 수치와 함께 서술하되, 다음도 포함:
- 실험 설계의 **강점과 약점** (데이터셋 선택의 적절성, 베이스라인 비교의 공정성)
- 보고된 성능 향상이 **통계적으로 유의미한지** 여부
- 실험에서 **빠져 있는 비교/분석** (있었다면 더 설득력 있었을 실험)]

**숨겨진 가정과 한계**
[저자가 명시적으로 언급하지 않은 부분 포함:
- 방법론의 **암묵적 가정** (데이터 분포, 계산 자원 등)
- **일반화 가능성**의 한계 (특정 도메인/규모에만 적용 가능한가?)
- **재현성** 관련 우려 (구현 세부사항 충분히 공개되었는가?)
- 향후 해결해야 할 **핵심 과제**]

---

## 3. 교차 분석 및 비교

### 3.1 연구 패러다임 분류
| 논문 | 연구 유형 | 핵심 접근법 | 데이터 | 평가 지표 | 성숙도 |
|------|----------|-----------|--------|----------|--------|
[각 논문의 연구 패러다임(실증적/이론적/설계과학적)과 접근법 성숙도(초기 탐색/발전/성숙) 분류]

### 3.2 방법론적 상보성과 모순점
[논문들의 방법론이 서로 어떻게 보완할 수 있는지, 상충되는 주장이나 결과가 있는지 분석:
- **상보적 관계**: A의 강점이 B의 약점을 보완하는 구체적 사례
- **모순되는 결과/주장**: 같은 문제에 대해 다른 결론을 내리는 경우와 그 원인 분석
- **방법론적 수렴**: 서로 다른 접근이 공통적으로 가리키는 방향]

### 3.3 기여도 비교 매트릭스
| 기여 유형 | 해당 논문 | 구체적 기여 내용 | 영향력 평가 |
|----------|----------|----------------|-----------|
| 이론적 프레임워크 제시 | | | |
| 알고리즘/모델 혁신 | | | |
| 대규모 실험적 검증 | | | |
| 실용적 도구/시스템 | | | |
| 새로운 연구 방향 개척 | | | |

---

## 4. 핵심 통찰 및 연구 시사점

### 4.1 메타 수준의 핵심 통찰 (Cross-Paper Insights)
[개별 논문 분석만으로는 보이지 않는, 논문들을 종합했을 때 비로소 발견되는 패턴과 통찰 5-7개.
각 통찰에 대해 근거가 되는 논문을 명시하고, 왜 이것이 중요한 발견인지 설명]

1. [통찰 1: 구체적 설명 + 근거 논문]
2. [통찰 2: 구체적 설명 + 근거 논문]
...

### 4.2 연구 공백 분석 (Research Gaps)
[이 논문들이 다루지 못하고 있는 중요한 연구 질문을 식별하고,
왜 이 질문들이 중요한지, 해결하기 위해 어떤 접근이 필요한지 구체적으로 서술]

### 4.3 기술 융합 가능성 (Cross-Pollination Opportunities)
[서로 다른 논문의 기법을 결합했을 때 기대되는 시너지 효과를 구체적으로 제시:
- 논문 A의 X 기법 + 논문 B의 Y 기법 = 예상되는 개선점
- 이 융합이 해결할 수 있는 현재의 한계점]

### 4.4 실무 적용 시나리오
[각 연구 결과의 산업/실무 적용 가능성을 구체적으로 평가:
- 어떤 산업/분야에서 활용 가능한가?
- 실용화까지 해결해야 할 기술적 과제는?
- 예상되는 비즈니스 임팩트]

---

## 5. 연구 동향 및 미래 전망

### 5.1 현재 연구 트렌드 분석
[논문들에서 발견되는 연구 동향을 다차원적으로 분석:]
- **기술적 트렌드**: 어떤 기술이 부상하고, 어떤 기술이 쇠퇴하고 있는가?
- **방법론적 트렌드**: 연구 방법론은 어떻게 진화하고 있는가?
- **데이터/벤치마크 트렌드**: 평가 기준과 데이터셋은 어떻게 변화하고 있는가?

### 5.2 향후 5년 연구 전망
[현재 트렌드를 바탕으로 한 미래 연구 방향 예측 5-7개.
각 방향에 대해 왜 그 방향이 유망한지, 어떤 선행 조건이 필요한지 구체적으로 서술]

### 5.3 연구자를 위한 실행 가능한 제언
[이 분야에 진입하려는 연구자에게 제공하는 구체적이고 실행 가능한 연구 제언:
- 가장 유망한 연구 주제 3가지와 그 이유
- 피해야 할 함정과 주의사항
- 필수적으로 읽어야 할 핵심 참고문헌]

---

## 6. 결론

### 6.1 주요 발견 요약
[본 리뷰의 핵심 발견을 5-7개 bullet point로 압축 정리]

### 6.2 본 리뷰의 한계
[본 리뷰의 한계점과 향후 보완 방향을 솔직하게 서술]

---

## 참고문헌

[분석된 모든 논문을 학술 인용 형식(APA)으로 정리]

---

*본 체계적 문헌 고찰은 AI 기반 심층 연구 분석 시스템에 의해 생성되었습니다.*

---

**최종 점검 (반드시 확인):**
- 모든 분석에 **구체적 근거**가 제시되었는가? (일반론 사용 금지)
- 각 논문의 **고유한 특성**이 드러나는가? (복사-붙여넣기식 분석 금지)
- **방법론의 작동 원리**가 기술적으로 설명되었는가?
- **숨겨진 가정과 한계**가 비판적으로 분석되었는가?
- **교차 논문 통찰**이 개별 분석을 넘어서는 새로운 가치를 제공하는가?
- **수치 데이터**가 충분히 인용되었는가?"""

    try:
        print("[Fast Review] LLM 분석 중...")
        
        with review_sessions_lock:
            if session_id in review_sessions:
                review_sessions[session_id]["progress"] = "AI가 논문을 분석하고 있습니다..."
        
        # OpenAI API 직접 호출 (langchain 호환성 문제 우회)
        response = client.chat.completions.create(
            model=deep_research_model,
            messages=[
                {"role": "system", "content": (
                    "당신은 Nature, Science 등 최상위 저널의 리뷰어이자, "
                    "해당 분야에서 20년 이상 핵심 연구를 수행해온 석학 교수입니다. "
                    "단순한 논문 요약이 아닌, 비판적 사고와 학제간 통찰을 바탕으로 "
                    "논문의 본질적 기여와 한계를 꿰뚫는 심층 분석을 수행합니다. "
                    "모든 주장에는 구체적 근거를 제시하고, 숨겨진 가정과 잠재적 한계까지 도출합니다. "
                    "체계적이고 상세한 한글 문헌 리뷰 보고서를 작성합니다."
                )},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=32000
        )
        report_content = response.choices[0].message.content
        
        print(f"[Fast Review] 분석 완료! ({len(report_content)} chars)")
        
        # 리포트 저장
        reports_dir = Path(workspace.session_path) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        report_filename = f"final_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        report_path = reports_dir / report_filename
        report_path.write_text(report_content, encoding='utf-8')
        print(f"[Review] Report saved to: {report_path}")
        
        # 분석 데이터도 저장
        analyses = []
        for paper in papers:
            analyses.append({
                "title": paper.get('title', 'Unknown'),
                "analysis": "Fast mode analysis included in report",
                "metadata": {
                    "authors": paper.get('authors', []),
                    "year": paper.get('year', 'N/A')
                }
            })
        
        # workspace에 분석 저장
        try:
            workspace.save_researcher_analysis(
                researcher_id="fast_mode",
                paper_id="all",
                analysis={"papers": len(papers), "mode": "fast"}
            )
        except:
            pass
        
        return {
            "status": "completed",
            "papers_reviewed": len(papers),
            "workspace_path": str(workspace.session_path),
            "summary": {
                "mode": "fast",
                "papers": len(papers),
                "analyses": analyses
            }
        }
        
    except Exception as e:
        print(f"ERROR: Fast Review 오류: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "failed", "error": str(e)}

class DeepReviewRequest(BaseModel):
    paper_ids: List[str]
    papers: Optional[List[Dict[str, Any]]] = None  # 선택한 논문의 전체 데이터 (직접 전달)
    num_researchers: Optional[int] = 3
    model: Optional[str] = "gpt-4.1"  # 기본 모델 (Deep Research는 o3 사용)
    fast_mode: Optional[bool] = True  # 기본값: Fast Mode (빠른 분석)

class ReviewStatusResponse(BaseModel):
    session_id: str
    status: str
    progress: Optional[str] = None
    report_available: bool = False
    error: Optional[str] = None

@app.post("/api/deep-review")
async def start_deep_review(request: DeepReviewRequest, background_tasks: BackgroundTasks):
    """
    Start deep paper review with N researcher agents
    Runs in background and returns session_id immediately
    """
    try:
        from app.DeepAgent.workspace_manager import WorkspaceManager
        from datetime import datetime
        
        print(f"[Deep Review] Starting request with {len(request.paper_ids)} papers")
        print(f"[Deep Review] Papers data provided: {len(request.papers) if request.papers else 0}")
        
        # Create workspace for this session
        workspace = WorkspaceManager()
        session_id = workspace.session_id
        
        print(f"[Deep Review] Session ID: {session_id}")
        
        # Store session info
        with review_sessions_lock:
            review_sessions[session_id] = {
                "status": "processing",
                "paper_ids": request.paper_ids,
                "num_papers": len(request.paper_ids),
                "workspace_path": str(workspace.session_path),
                "created_at": datetime.now().isoformat(),
            }
        
        # Start background task
        background_tasks.add_task(
            run_deep_review_background,
            session_id=session_id,
            paper_ids=request.paper_ids,
            papers_data=request.papers,  # 프론트엔드에서 전달받은 논문 데이터
            num_researchers=request.num_researchers,
            model=request.model,
            workspace=workspace,
            fast_mode=request.fast_mode
        )
        
        return {
            "success": True,
            "session_id": session_id,
            "status": "processing",
            "message": f"Deep review started for {len(request.paper_ids)} papers",
            "status_url": f"/api/deep-review/status/{session_id}"
        }
    
    except Exception as e:
        import traceback
        print(f"[Deep Review] ERROR: Error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to start review: {str(e)}")


def _generate_review_report_content(workspace: Any, result: dict, paper_ids: List[str]) -> str:
    """
    LLM을 사용하여 선택된 논문들을 기반으로 한글 학술 리서치 논문 형태의 심층 리포트 생성
    """
    from datetime import datetime
    from openai import OpenAI
    
    # Get analyses from workspace
    analyses = []
    try:
        analyses = workspace.get_all_analyses() if hasattr(workspace, 'get_all_analyses') else []
    except:
        pass
    
    num_papers = len(paper_ids)
    current_date = datetime.now().strftime('%Y년 %m월 %d일')
    
    # 분석 데이터 요약 준비
    analyses_summary = []
    for i, analysis in enumerate(analyses, 1):
        if isinstance(analysis, dict):
            title = analysis.get('title', f'논문 {i}')
            content = analysis.get('analysis', '')
            metadata = analysis.get('metadata', {})
            
            summary = f"### 논문 {i}: {title}\n"
            if metadata:
                authors = metadata.get('authors', [])
                year = metadata.get('year', '미상')
                if authors:
                    if isinstance(authors[0], dict):
                        author_names = [a.get('name', str(a)) for a in authors[:3]]
                    else:
                        author_names = authors[:3]
                    author_str = ', '.join(author_names)
                    if len(authors) > 3:
                        author_str += ' 외'
                    summary += f"- 저자: {author_str}\n"
                summary += f"- 발표 연도: {year}\n"
            
            if isinstance(content, str) and content:
                summary += f"- 분석 내용: {content[:3000]}\n"
            elif isinstance(content, dict):
                summary += f"- 분석 내용: {json.dumps(content, ensure_ascii=False)[:3000]}\n"
            
            analyses_summary.append(summary)
    
    combined_analyses = "\n\n".join(analyses_summary) if analyses_summary else "분석 데이터 없음"
    
    # LLM 프롬프트
    prompt = f"""당신은 해당 분야의 선임 연구 교수입니다. 다음 {num_papers}편의 논문 분석 데이터를 바탕으로 
한글로 체계적이고 심층적인 문헌 리뷰 보고서를 작성해주세요.

## 논문 분석 데이터:
{combined_analyses}

## 다음 형식으로 상세한 학술 리뷰 보고서를 작성해주세요:

# 체계적 문헌 고찰: 선정 연구 논문의 심층 분석

---

**리뷰 날짜**: {current_date}
**분석 논문 수**: {num_papers}편
**세션 ID**: `{workspace.session_id}`

---

## 초록 (Abstract)
[분석한 논문들의 전체적인 요약과 핵심 발견을 200-300자로 작성. 실제 논문 내용을 반영해야 함]

**키워드**: [논문들에서 추출한 실제 키워드 5-7개]

---

## 1. 서론
### 1.1 연구 배경 및 동기
[분석된 논문들의 연구 분야에 대한 배경 설명. 구체적인 연구 주제와 왜 중요한지 설명]

### 1.2 본 리뷰의 목적
[이 논문들을 리뷰하는 구체적인 목적 4가지]

### 1.3 범위 및 선정 기준
[선정된 논문들의 공통 주제와 선정 이유]

---

## 2. 연구 방법론
### 2.1 분석 프레임워크
[사용된 분석 방법론 설명]

### 2.2 분석 차원
[각 논문을 어떤 관점에서 분석했는지 표로 정리]

---

## 3. 상세 문헌 분석

[각 논문에 대해 다음 형식으로 상세 분석 작성:]

### 3.N [논문 제목]
**저자**: [저자명]
**발표 연도**: [연도]

#### 연구 배경 및 문제 정의
[논문이 해결하고자 하는 문제와 동기]

#### 핵심 기여
[논문의 주요 기여점 3-5개 - 구체적으로]

#### 연구 방법론
[사용된 기술적 방법과 접근법]

#### 주요 실험 결과
[핵심 실험 결과와 성능 수치]

#### 강점
[논문의 주요 강점 3-4개]

#### 한계점 및 개선 방향
[논문의 한계와 향후 개선 방향]

#### 학술적 영향력
[이 논문이 분야에 미친/미칠 영향]

---

## 4. 비교 분석
### 4.1 방법론적 비교
[논문들의 방법론을 비교 분석 - 실제 내용 기반]

### 4.2 기여 패턴
[논문들의 기여 유형을 표로 정리]

| 논문 | 주요 기여 유형 | 구체적 기여 |
|------|---------------|------------|
[각 논문별 기여 정리]

### 4.3 강점 및 한계점 종합
[모든 논문의 공통 강점과 한계점 분석]

---

## 5. 논의
### 5.1 핵심 통찰
[분석을 통해 얻은 중요한 통찰 3-5개 - 구체적으로]

### 5.2 연구 동향
[논문들에서 발견된 연구 트렌드]

### 5.3 연구 공백
[발견된 연구 공백과 미래 연구 기회]

---

## 6. 결론 및 향후 연구 방향
### 6.1 발견 요약
[주요 발견 사항 종합]

### 6.2 향후 연구를 위한 제언
[구체적인 향후 연구 방향 5개]

### 6.3 본 리뷰의 한계
[이 리뷰의 한계점]

---

## 참고문헌
[분석된 논문 목록을 학술 형식으로 정리]

---

## 부록: 리뷰 메타데이터
- **리뷰 생성 일시**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **세션 ID**: {workspace.session_id}
- **분석 시스템**: 멀티 에이전트 심층 연구 시스템
- **분석된 논문 수**: {num_papers}편

---

*본 체계적 문헌 고찰은 심층 에이전트 연구 리뷰 시스템에 의해 생성되었습니다.*

---

**중요**: 
- 각 섹션을 실제 논문 내용을 바탕으로 구체적이고 상세하게 작성해주세요.
- 일반적인 문구가 아닌, 분석된 논문의 실제 내용을 반영해야 합니다.
- 각 논문의 고유한 특성과 기여를 명확히 구분해서 작성해주세요.
- 학술 논문 수준의 깊이와 전문성을 유지해주세요."""

    try:
        # Deep Research는 GPT-4.1 모델로 심층 분석
        deep_research_model = "gpt-4.1"
        print(f"[Deep Review] LLM으로 심층 리포트 생성 중... (모델: {deep_research_model})")
        
        # OpenAI API 직접 호출 (langchain 호환성 문제 우회)
        client = OpenAI()
        response = client.chat.completions.create(
            model=deep_research_model,
            messages=[
                {"role": "system", "content": "당신은 해당 분야의 선임 연구 교수입니다. 체계적이고 심층적인 한글 문헌 리뷰 보고서를 작성합니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=16000
        )
        report_content = response.choices[0].message.content
        print(f"[Deep Review] 심층 리포트 생성 완료! ({len(report_content)} chars)")
        return report_content
        
    except Exception as e:
        print(f"[Deep Review] LLM 리포트 생성 실패: {e}, 기본 템플릿 사용")
        # LLM 실패 시 기본 템플릿 반환
        return _generate_fallback_report(workspace, result, paper_ids, analyses, num_papers, current_date)


def _generate_fallback_report(workspace: Any, result: dict, paper_ids: List[str], 
                               analyses: list, num_papers: int, current_date: str) -> str:
    """LLM 실패 시 사용하는 기본 템플릿 리포트"""
    report = []
    
    report.append("# 체계적 문헌 고찰: 선정 연구 논문의 심층 분석")
    report.append("")
    report.append("---")
    report.append("")
    report.append(f"**리뷰 날짜**: {current_date}")
    report.append(f"**분석 논문 수**: {num_papers}편")
    report.append(f"**세션 ID**: `{workspace.session_id}`")
    report.append("")
    report.append("---")
    report.append("")
    
    report.append("## 분석된 논문 목록")
    report.append("")
    
    if analyses:
        for i, analysis in enumerate(analyses, 1):
            if isinstance(analysis, dict):
                title = analysis.get('title', f'논문 {i}')
                content = analysis.get('analysis', '')
                
                report.append(f"### {i}. {title}")
                report.append("")
                
                if isinstance(content, str) and content:
                    report.append(content[:5000])
                elif isinstance(content, dict):
                    report.append(json.dumps(content, indent=2, ensure_ascii=False)[:5000])
                
                report.append("")
                report.append("---")
                report.append("")
    else:
        for i, paper_id in enumerate(paper_ids, 1):
            report.append(f"[{i}] 논문 ID: {paper_id}")
    
    report.append("")
    report.append("*리포트 생성 중 오류가 발생하여 기본 템플릿이 사용되었습니다.*")
    
    return "\n".join(report)


def run_deep_review_background(
    session_id: str,
    paper_ids: List[str],
    papers_data: Optional[List[Dict[str, Any]]],
    num_researchers: int,
    model: str,
    workspace: Any,
    fast_mode: bool = True
):
    """
    Background task to run deep review
    
    Args:
        papers_data: 프론트엔드에서 직접 전달받은 논문 데이터 (ID 매칭 불필요)
        fast_mode: True면 빠른 단일 LLM 호출 분석, False면 전체 deepagents 분석
    """
    try:
        print(f"[Deep Review] Starting session {session_id}")
        print(f"[Deep Review] Papers: {len(paper_ids)}, Mode: {'Fast' if fast_mode else 'Deep'}")
        print(f"[Deep Review] Direct papers data: {len(papers_data) if papers_data else 0} papers")
        
        # Update status
        with review_sessions_lock:
            if session_id in review_sessions:
                review_sessions[session_id]["status"] = "analyzing"
                review_sessions[session_id]["progress"] = "논문 분석 중..." if fast_mode else "Researchers analyzing papers with deepagents..."
        
        if fast_mode:
            # Fast Mode: 단일 LLM 호출로 빠른 분석
            result = run_fast_review(session_id, paper_ids, model, workspace, papers_data)
        else:
            # Deep Mode: 전체 deepagents 분석
            from app.DeepAgent.deep_review_agent import DeepReviewAgent
            
            agent = DeepReviewAgent(
                model=model,
                num_researchers=num_researchers,
                workspace=workspace
            )
            result = agent.review_papers(paper_ids=paper_ids, verbose=True)
        
        # Get workspace path
        workspace_path = result.get("workspace_path", str(workspace.session_path))
        
        # Fast Mode에서는 이미 LLM이 생성한 리포트가 저장되어 있으므로 템플릿 생성 건너뜀
        # Deep Mode에서만 템플릿 리포트 생성
        if not fast_mode:
            try:
                from datetime import datetime
                reports_dir = Path(workspace_path) / "reports"
                reports_dir.mkdir(parents=True, exist_ok=True)
                
                # Generate report content (Deep Mode only)
                report_content = _generate_review_report_content(workspace, result, paper_ids)
                
                report_filename = f"final_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                report_path = reports_dir / report_filename
                report_path.write_text(report_content, encoding='utf-8')
                print(f"[Review] Report saved to: {report_path}")
            except Exception as report_error:
                print(f"[Deep Review] Report generation warning: {report_error}")
        
        # Update session with result
        with review_sessions_lock:
            if session_id in review_sessions:
                if result["status"] == "completed":
                    review_sessions[session_id]["status"] = "completed"
                    review_sessions[session_id]["progress"] = "Review completed"
                    review_sessions[session_id]["report_available"] = True
                    review_sessions[session_id]["workspace_path"] = workspace_path
                    review_sessions[session_id]["num_papers"] = result.get("papers_reviewed", len(paper_ids))
                    # 포스터 생성 시 삽도 추출을 위해 논문 데이터 보존
                    if papers_data:
                        review_sessions[session_id]["papers_data"] = papers_data
                else:
                    review_sessions[session_id]["status"] = "failed"
                    review_sessions[session_id]["error"] = result.get("error", "Unknown error")
        
        print(f"[Deep Review] Session {session_id} completed: {result['status']}")
        
    except Exception as e:
        print(f"[Deep Review] Session {session_id} failed: {e}")
        import traceback
        traceback.print_exc()
        with review_sessions_lock:
            if session_id in review_sessions:
                review_sessions[session_id]["status"] = "failed"
                review_sessions[session_id]["error"] = str(e)


@app.get("/api/deep-review/status/{session_id}")
async def get_review_status(session_id: str) -> ReviewStatusResponse:
    """
    Get status of a deep review session
    """
    with review_sessions_lock:
        if session_id not in review_sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = review_sessions[session_id]
        
        return ReviewStatusResponse(
            session_id=session_id,
            status=session["status"],
            progress=session.get("progress"),
            report_available=session.get("report_available", False),
            error=session.get("error")
        )


@app.get("/api/deep-review/report/{session_id}")
async def get_review_report(session_id: str):
    """
    Get the generated review report
    """
    with review_sessions_lock:
        if session_id not in review_sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = review_sessions[session_id]
        
        if session["status"] != "completed":
            raise HTTPException(status_code=400, detail=f"Review not completed yet (status: {session['status']})")
        
        workspace_path = Path(session["workspace_path"])
        reports_dir = workspace_path / "reports"
        
        if not reports_dir.exists():
            raise HTTPException(status_code=404, detail="Reports directory not found")
        
        # Find latest markdown report
        md_files = sorted(reports_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        
        if not md_files:
            raise HTTPException(status_code=404, detail="Report not found")
        
        # Read report
        with open(md_files[0], 'r', encoding='utf-8') as f:
            report_content = f.read()
        
        # Also try to get JSON results
        json_files = sorted(reports_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        json_result = None
        if json_files:
            try:
                import json
                with open(json_files[0], 'r', encoding='utf-8') as f:
                    json_result = json.load(f)
            except:
                pass
        
        return {
            "session_id": session_id,
            "report_markdown": report_content,
            "report_json": json_result,
            "num_papers": session.get("num_papers", 0),
            "created_at": session.get("created_at")
        }


# ==================== Report Visualization (학회 포스터) ====================

@app.post("/api/deep-review/visualize/{session_id}")
async def generate_poster_visualization(session_id: str):
    """
    Deep Research 리포트를 학회 포스터 형태로 시각화
    PosterGenerationAgent를 사용하여 HTML/SVG 포스터 생성
    """
    try:
        print(f"[Poster API] Starting poster generation for session: {session_id}")
        
        # Step 1: Import PosterGenerationAgent
        try:
            from app.DeepAgent.agents import PosterGenerationAgent
            print("[Poster API] PosterGenerationAgent imported successfully")
        except Exception as e:
            print(f"[Poster API] ERROR: Failed to import PosterGenerationAgent: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Failed to import PosterGenerationAgent: {str(e)}")
        
        # Step 2: 세션 확인
        with review_sessions_lock:
            if session_id not in review_sessions:
                print(f"[Poster API] ERROR: Session not found: {session_id}")
                raise HTTPException(status_code=404, detail="Session not found")
            
            session = review_sessions[session_id]
            print(f"[Poster API] Session found: status={session.get('status')}")
            
            if session["status"] != "completed":
                print(f"[Poster API] ERROR: Review not completed: status={session.get('status')}")
                raise HTTPException(status_code=400, detail="Review not completed yet")
            
            workspace_path = Path(session["workspace_path"])
            print(f"[Poster API] Workspace path: {workspace_path}")
        
        # Step 3: 리포트 읽기
        reports_dir = workspace_path / "reports"
        md_files = sorted(reports_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        
        if not md_files:
            print(f"[Poster API] ERROR: No report files found in: {reports_dir}")
            raise HTTPException(status_code=404, detail="Report not found")
        
        print(f"[Poster API] Found {len(md_files)} report file(s)")
        with open(md_files[0], 'r', encoding='utf-8') as f:
            report_content = f.read()
        print(f"[Poster API] Report content loaded: {len(report_content)} chars")
        
        # Step 4: DesignPatternManager 초기화
        try:
            from app.DeepAgent.config.design_pattern_manager import get_design_pattern_manager
            pattern_manager = get_design_pattern_manager()
            print("[Poster API] DesignPatternManager initialized")
        except Exception as e:
            print(f"[Poster API] WARNING: Failed to initialize DesignPatternManager: {e}")
            pattern_manager = None
        
        # Step 5: PosterGenerationAgent 초기화 (DesignPatternManager 포함)
        try:
            poster_agent = PosterGenerationAgent(
                model="gemini-3-pro-image-preview",
                design_pattern_manager=pattern_manager
            )
            print("[Poster API] PosterGenerationAgent initialized with gemini-3-pro-image-preview and DesignPatternManager")
        except Exception as e:
            print(f"[Poster API] ERROR: Failed to initialize PosterGenerationAgent: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Failed to initialize PosterGenerationAgent: {str(e)}")
        
        # Step 5: 포스터 생성 (논문 삽도 추출 포함)
        poster_dir = workspace_path / "posters"
        num_papers = session.get("num_papers", 0)

        # 세션에 저장된 논문 데이터 가져오기 (삽도 추출용)
        # papers.json에서 pdf_url, arxiv_id 등 전체 데이터를 가져옴
        papers_data = None
        try:
            from app.DeepAgent.tools.paper_loader import load_papers_from_ids
            paper_ids = session.get("paper_ids", [])
            if paper_ids:
                papers_data = load_papers_from_ids(paper_ids)
                print(f"[Poster API] 논문 데이터 로드 (papers.json): {len(papers_data) if papers_data else 0}편")

            # papers.json에서 못 찾으면 세션 데이터 사용
            if not papers_data:
                papers_data = session.get("papers_data")
                if papers_data:
                    print(f"[Poster API] 세션 논문 데이터 사용: {len(papers_data)}편")
        except Exception as e:
            print(f"[Poster API] WARNING: 논문 데이터 로드 실패: {e}")
            papers_data = session.get("papers_data")

        print(f"[Poster API] Generating poster: num_papers={num_papers}, output_dir={poster_dir}, papers_data={len(papers_data) if papers_data else 0}")

        try:
            result = poster_agent.generate_poster(
                report_content=report_content,
                num_papers=num_papers,
                output_dir=poster_dir,
                papers_data=papers_data
            )
            print(f"[Poster API] Poster generated: success={result.get('success')}, path={result.get('poster_path', 'N/A')}")
        except Exception as e:
            print(f"[Poster API] ERROR: Failed to generate poster: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Failed to generate poster: {str(e)}")
        
        return {
            "success": result["success"],
            "session_id": session_id,
            "poster_html": result["poster_html"],
            "poster_path": result.get("poster_path", "")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Poster API] ERROR: Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Poster generation failed: {str(e)}")


# ─── LightRAG API Endpoints ───

class LightRAGBuildRequest(BaseModel):
    max_concurrent: int = 4
    extraction_model: str = "gpt-4o-mini"

class LightRAGQueryRequest(BaseModel):
    query: str
    mode: str = "hybrid"  # naive, local, global, hybrid, mix
    top_k: int = 10
    temperature: float = 0.7

# LightRAG 에이전트 (싱글톤)
_light_rag_agent = None

def _get_light_rag_agent():
    global _light_rag_agent
    if _light_rag_agent is None:
        from app.GraphRAG.rag_agent import GraphRAGAgent
        _light_rag_agent = GraphRAGAgent(
            papers_json_path="data/raw/papers.json",
            graph_path="data/graph/paper_graph.pkl",
            light_rag_dir="data/light_rag",
        )
    return _light_rag_agent


@app.post("/api/light-rag/build")
async def light_rag_build(request: LightRAGBuildRequest, background_tasks: BackgroundTasks):
    """LightRAG 지식 그래프 구축 (백그라운드)"""
    def _build():
        try:
            agent = _get_light_rag_agent()
            agent.build_knowledge_graph(
                max_concurrent=request.max_concurrent,
                extraction_model=request.extraction_model,
            )
            print("[LightRAG] Knowledge graph build complete")
        except Exception as e:
            print(f"[LightRAG] Build error: {e}")

    background_tasks.add_task(_build)
    return {
        "status": "building",
        "message": "Knowledge graph build started in background",
        "config": {
            "max_concurrent": request.max_concurrent,
            "extraction_model": request.extraction_model,
        },
    }


@app.post("/api/light-rag/query")
async def light_rag_query(request: LightRAGQueryRequest):
    """LightRAG 쿼리 실행"""
    try:
        agent = _get_light_rag_agent()
        result = agent.light_query(
            query=request.query,
            mode=request.mode,
            top_k=request.top_k,
            temperature=request.temperature,
        )
        return result
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Knowledge graph not found. Run /api/light-rag/build first.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LightRAG query failed: {str(e)}")


@app.get("/api/light-rag/status")
async def light_rag_status():
    """LightRAG 지식 그래프 상태 확인"""
    try:
        agent = _get_light_rag_agent()
        stats = agent.get_kg_stats()
        return {"status": "ready", "stats": stats}
    except Exception as e:
        return {"status": "not_built", "error": str(e)}


# ==================== Bookmarks Endpoints ====================

BOOKMARKS_FILE = Path("data/bookmarks.json")


def _load_bookmarks() -> dict:
    """Load bookmarks from JSON file"""
    if BOOKMARKS_FILE.exists():
        with open(BOOKMARKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"bookmarks": []}


def _save_bookmarks(data: dict):
    """Save bookmarks to JSON file"""
    BOOKMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BOOKMARKS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class BookmarkCreateRequest(BaseModel):
    session_id: str
    title: str
    query: str = ""
    papers: List[dict] = []
    report_markdown: str
    tags: List[str] = []
    topic: str = "General"


class BookmarkTopicUpdateRequest(BaseModel):
    topic: str


class BookmarkResponse(BaseModel):
    id: str
    title: str
    session_id: str
    query: str
    num_papers: int
    created_at: str
    tags: List[str]
    topic: str = "General"


@app.post("/api/bookmarks")
async def create_bookmark(request: BookmarkCreateRequest):
    """Save a deep research result as a bookmark"""
    from datetime import datetime
    import uuid

    bookmark_id = f"bm_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    # Try to get workspace_path from active sessions
    workspace_path = ""
    with review_sessions_lock:
        if request.session_id in review_sessions:
            workspace_path = review_sessions[request.session_id].get("workspace_path", "")

    bookmark = {
        "id": bookmark_id,
        "title": request.title,
        "session_id": request.session_id,
        "workspace_path": workspace_path,
        "query": request.query,
        "papers": request.papers,
        "num_papers": len(request.papers),
        "report_markdown": request.report_markdown,
        "created_at": datetime.now().isoformat(),
        "tags": request.tags,
        "topic": request.topic,
    }

    data = _load_bookmarks()
    data["bookmarks"].append(bookmark)
    _save_bookmarks(data)

    return BookmarkResponse(
        id=bookmark_id,
        title=request.title,
        session_id=request.session_id,
        query=request.query,
        num_papers=len(request.papers),
        created_at=bookmark["created_at"],
        tags=request.tags,
        topic=request.topic,
    )


@app.get("/api/bookmarks")
async def list_bookmarks():
    """List all bookmarks (summary only, without report content)"""
    data = _load_bookmarks()
    return {
        "bookmarks": [
            {
                "id": bm["id"],
                "title": bm["title"],
                "session_id": bm["session_id"],
                "query": bm.get("query", ""),
                "num_papers": bm.get("num_papers", 0),
                "created_at": bm["created_at"],
                "tags": bm.get("tags", []),
                "topic": bm.get("topic", "General"),
            }
            for bm in data["bookmarks"]
        ]
    }


@app.get("/api/bookmarks/{bookmark_id}")
async def get_bookmark(bookmark_id: str):
    """Get full bookmark detail including report"""
    data = _load_bookmarks()
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id:
            return bm
    raise HTTPException(status_code=404, detail="Bookmark not found")


@app.delete("/api/bookmarks/{bookmark_id}")
async def delete_bookmark(bookmark_id: str):
    """Delete a bookmark"""
    data = _load_bookmarks()
    original_len = len(data["bookmarks"])
    data["bookmarks"] = [bm for bm in data["bookmarks"] if bm["id"] != bookmark_id]

    if len(data["bookmarks"]) == original_len:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    _save_bookmarks(data)
    return {"success": True, "message": "Bookmark deleted"}


@app.patch("/api/bookmarks/{bookmark_id}/topic")
async def update_bookmark_topic(bookmark_id: str, request: BookmarkTopicUpdateRequest):
    """Update a bookmark's topic"""
    data = _load_bookmarks()
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id:
            bm["topic"] = request.topic
            _save_bookmarks(data)
            return {"success": True, "topic": request.topic}
    raise HTTPException(status_code=404, detail="Bookmark not found")


# Bulk bookmark operations
class BulkDeleteBookmarksRequest(BaseModel):
    bookmark_ids: List[str]

class BulkMoveBookmarksRequest(BaseModel):
    bookmark_ids: List[str]
    topic: str

@app.post("/api/bookmarks/bulk-delete")
async def bulk_delete_bookmarks(request: BulkDeleteBookmarksRequest):
    """Delete multiple bookmarks at once"""
    data = _load_bookmarks()
    ids_set = set(request.bookmark_ids)
    original = len(data["bookmarks"])
    data["bookmarks"] = [bm for bm in data["bookmarks"] if bm["id"] not in ids_set]
    deleted = original - len(data["bookmarks"])
    if deleted == 0:
        raise HTTPException(status_code=404, detail="No bookmarks found to delete")
    _save_bookmarks(data)
    return {"success": True, "deleted_count": deleted}

@app.post("/api/bookmarks/bulk-move")
async def bulk_move_bookmarks(request: BulkMoveBookmarksRequest):
    """Move multiple bookmarks to a new topic"""
    data = _load_bookmarks()
    ids_set = set(request.bookmark_ids)
    updated = 0
    for bm in data["bookmarks"]:
        if bm["id"] in ids_set:
            bm["topic"] = request.topic
            updated += 1
    if updated == 0:
        raise HTTPException(status_code=404, detail="No bookmarks found to update")
    _save_bookmarks(data)
    return {"success": True, "updated_count": updated, "topic": request.topic}


# ==================== Chat Endpoints ====================

class ChatRequest(BaseModel):
    messages: List[dict]  # [{"role": "user"|"assistant", "content": "..."}]
    bookmark_ids: List[str] = []  # empty = use all bookmarks


@app.post("/api/chat")
async def chat_with_bookmarks(request: ChatRequest):
    """Chat about bookmarked papers using their report content as context. Returns SSE stream."""
    from openai import OpenAI

    # Load bookmark context
    data = _load_bookmarks()
    bookmarks = data.get("bookmarks", [])

    if request.bookmark_ids:
        bookmarks = [bm for bm in bookmarks if bm["id"] in request.bookmark_ids]

    # Build context from bookmark reports with numbered references
    sources_metadata = []
    if not bookmarks:
        context_text = "(No bookmarked papers available.)"
    else:
        context_parts = []
        max_chars = 4000
        for idx, bm in enumerate(bookmarks[:10], start=1):
            report = bm.get("report_markdown", "")[:max_chars]
            papers_summary = ", ".join(
                p.get("title", "Untitled") for p in bm.get("papers", [])[:5]
            )
            context_parts.append(
                f"[{idx}] Bookmark: {bm.get('title', 'Untitled')}\n"
                f"Query: {bm.get('query', 'N/A')}\n"
                f"Papers: {papers_summary}\n"
                f"Report:\n{report}\n"
            )
            sources_metadata.append({
                "ref": idx,
                "id": bm["id"],
                "title": bm.get("title", "Untitled"),
                "num_papers": bm.get("num_papers", 0),
            })
        context_text = "\n---\n".join(context_parts)

    system_message = {
        "role": "system",
        "content": (
            "You are a research assistant helping users understand their bookmarked academic papers. "
            "You have access to the following bookmarked research reports and paper information. "
            "Each bookmark is numbered [1], [2], etc. When referencing information from the bookmarks, "
            "cite them using numbered references like [1], [2], etc. "
            "Answer questions based on this context. If the user asks about something not covered "
            "in the bookmarks, say so clearly. Respond in the same language the user uses.\n\n"
            f"=== BOOKMARKED PAPERS CONTEXT ===\n{context_text}\n=== END CONTEXT ==="
        ),
    }

    openai_messages = [system_message] + [
        {"role": m["role"], "content": m["content"]} for m in request.messages
    ]

    client = OpenAI()

    def generate():
        try:
            stream = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=openai_messages,
                temperature=0.7,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield f"data: {json.dumps({'content': delta.content})}\n\n"
            # Send sources metadata before done
            if sources_metadata:
                yield f"data: {json.dumps({'sources': sources_metadata})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

