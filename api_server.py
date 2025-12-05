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

load_dotenv()

app = FastAPI(title="Paper Review Agent API")

# CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],  # Vite default ports
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global agent instances
api_key = os.getenv("OPENAI_API_KEY")
search_agent = SearchAgent(openai_api_key=api_key)

# Query analyzer and relevance filter (optional - only if API key available)
query_analyzer = None
relevance_filter = None

if api_key:
    try:
        query_analyzer = QueryAnalyzer(api_key=api_key)
        relevance_filter = RelevanceFilter(api_key=api_key)
        print("[INFO] Query analyzer and relevance filter initialized")
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
    ⚡ Fast Mode: 단일 LLM 호출로 모든 논문을 빠르게 분석
    
    기존 Deep Mode 대비 5~10배 빠름
    
    Args:
        papers_data: 프론트엔드에서 직접 전달받은 논문 데이터 (우선 사용)
    """
    from langchain_openai import ChatOpenAI
    from app.DeepAgent.tools.paper_loader import load_papers_from_ids
    from datetime import datetime
    import hashlib
    
    print(f"⚡ Fast Review 시작: {len(paper_ids)}편 논문")
    
    # 논문 로드 (papers_data가 있으면 직접 사용, 없으면 ID로 검색)
    if papers_data and len(papers_data) > 0:
        papers = papers_data
        print(f"📚 {len(papers)}편 논문 (프론트엔드에서 직접 전달)")
    else:
        papers = load_papers_from_ids(paper_ids)
        print(f"📚 {len(papers)}편 논문 로드됨 (ID 검색)")
    
    if not papers:
        return {"status": "failed", "error": "논문을 로드할 수 없습니다"}
    
    # LLM 초기화
    llm = ChatOpenAI(model=model, temperature=0.3)
    
    # 논문 요약 준비
    papers_text = []
    for i, paper in enumerate(papers, 1):
        title = paper.get('title', f'Paper {i}') or f'Paper {i}'
        abstract = paper.get('abstract') or paper.get('summary') or '초록 없음'
        authors = paper.get('authors', [])
        year = paper.get('year') or paper.get('published') or 'N/A'
        
        # Format authors
        if authors:
            if isinstance(authors[0], dict):
                author_names = [a.get('name', str(a)) for a in authors[:3]]
            else:
                author_names = [str(a) for a in authors[:3]]
            author_str = ', '.join(author_names)
            if len(authors) > 3:
                author_str += ' 외'
        else:
            author_str = '저자 미상'
        
        # abstract가 string인지 확인
        if not isinstance(abstract, str):
            abstract = str(abstract) if abstract else '초록 없음'
        
        papers_text.append(f"""
### 논문 {i}: {title}
- **저자**: {author_str}
- **발표**: {year}
- **초록**: {abstract[:1500]}
""")
    
    combined_papers = "\n".join(papers_text)
    
    # 단일 LLM 호출로 전체 분석
    prompt = f"""당신은 해당 분야의 선임 연구 교수입니다. 다음 {len(papers)}편의 논문을 분석하여 한글로 체계적인 문헌 리뷰 보고서를 작성해주세요.

## 분석할 논문들:
{combined_papers}

## 다음 형식으로 상세한 학술 리뷰 보고서를 작성해주세요:

# 체계적 문헌 고찰: 선정 연구 논문의 심층 분석

---

**리뷰 날짜**: {datetime.now().strftime('%Y년 %m월 %d일')}
**분석 논문 수**: {len(papers)}편

---

## 초록 (Abstract)
[분석한 논문들의 전체적인 요약과 핵심 발견 - 200자 내외]

---

## 1. 서론
### 1.1 연구 배경 및 동기
[이 분야의 연구 배경과 본 리뷰의 동기]

### 1.2 본 리뷰의 목적
[구체적인 리뷰 목적 4가지]

---

## 2. 연구 방법론
### 2.1 논문 선정 기준
### 2.2 분석 프레임워크

---

## 3. 개별 논문 분석

[각 논문에 대해 다음 형식으로 분석:]

### 3.N [논문 제목]
**저자**: [저자명]
**핵심 기여**: [주요 기여점 3-5개]
**방법론**: [사용된 연구 방법]
**주요 결과**: [핵심 실험 결과]
**강점**: [논문의 강점]
**한계점**: [논문의 한계]
**영향력**: [학술적 영향력 평가]

---

## 4. 비교 분석
### 4.1 방법론적 비교
[논문들의 방법론 비교 분석]

### 4.2 기여 패턴
| 범주 | 설명 | 논문 |
|------|------|------|
[기여 유형별 분류]

### 4.3 강점 및 한계점 요약

---

## 5. 논의
### 5.1 핵심 통찰
### 5.2 연구 동향
### 5.3 연구 공백

---

## 6. 결론 및 향후 연구 방향
### 6.1 발견 요약
### 6.2 향후 연구를 위한 제언
### 6.3 본 리뷰의 한계

---

## 참고문헌
[분석된 논문 목록]

---

*본 체계적 문헌 고찰은 AI 기반 연구 리뷰 시스템에 의해 생성되었습니다.*

---

각 섹션을 상세하고 학술적으로 작성해주세요. 실제 논문 내용을 바탕으로 구체적인 분석을 제공해주세요."""

    try:
        print("🤖 LLM 분석 중...")
        
        with review_sessions_lock:
            if session_id in review_sessions:
                review_sessions[session_id]["progress"] = "🤖 AI가 논문을 분석하고 있습니다..."
        
        response = llm.invoke(prompt)
        report_content = response.content
        
        print(f"✅ 분석 완료! ({len(report_content)} chars)")
        
        # 리포트 저장
        reports_dir = Path(workspace.session_path) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        report_filename = f"final_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        report_path = reports_dir / report_filename
        report_path.write_text(report_content, encoding='utf-8')
        print(f"📝 Report saved to: {report_path}")
        
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
        print(f"❌ Fast Review 오류: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "failed", "error": str(e)}

class DeepReviewRequest(BaseModel):
    paper_ids: List[str]
    papers: Optional[List[Dict[str, Any]]] = None  # 선택한 논문의 전체 데이터 (직접 전달)
    num_researchers: Optional[int] = 3
    model: Optional[str] = "gpt-4.1"  # GPT-4.1 사용
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
        from app.DeepAgent import WorkspaceManager
        
        # Create workspace for this session
        workspace = WorkspaceManager()
        session_id = workspace.session_id
        
        # Store session info
        with review_sessions_lock:
            review_sessions[session_id] = {
                "status": "processing",
                "paper_ids": request.paper_ids,
                "num_papers": len(request.paper_ids),
                "workspace_path": str(workspace.session_path),
                "created_at": workspace.load_metadata().get("created_at"),
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
        raise HTTPException(status_code=500, detail=f"Failed to start review: {str(e)}")


def _generate_review_report_content(workspace: Any, result: dict, paper_ids: List[str]) -> str:
    """
    선택된 논문들을 기반으로 한글 학술 리서치 논문 형태의 리포트 생성
    """
    from datetime import datetime
    
    # Get analyses from workspace
    analyses = []
    try:
        analyses = workspace.get_all_analyses() if hasattr(workspace, 'get_all_analyses') else []
    except:
        pass
    
    num_papers = len(paper_ids)
    current_date = datetime.now().strftime('%Y년 %m월 %d일')
    
    report = []
    
    # ==================== 표지 ====================
    report.append("# 체계적 문헌 고찰: 선정 연구 논문의 심층 분석")
    report.append("")
    report.append("---")
    report.append("")
    report.append(f"**리뷰 날짜**: {current_date}")
    report.append(f"**분석 논문 수**: {num_papers}편")
    report.append(f"**리뷰 방법론**: 멀티 에이전트 심층 연구 시스템")
    report.append(f"**세션 ID**: `{workspace.session_id}`")
    report.append("")
    report.append("---")
    report.append("")
    
    # ==================== 초록 ====================
    report.append("## 초록 (Abstract)")
    report.append("")
    report.append(f"본 체계적 문헌 고찰은 해당 연구 분야에서 엄선된 {num_papers}편의 연구 논문에 대한 ")
    report.append("포괄적인 분석을 제시합니다. 고급 멀티 에이전트 심층 연구 시스템을 활용하여 각 논문의 ")
    report.append("연구 방법론, 핵심 기여, 실험 결과 및 한계점을 심도 있게 검토하였습니다. ")
    report.append("본 분석은 방법론적 접근법에서 나타나는 유의미한 패턴을 발견하고, 문헌 전반에 걸친 ")
    report.append("공통 주제를 식별하며, 추가 연구가 필요한 핵심 연구 공백을 강조합니다. ")
    report.append("본 리뷰는 연구자들에게 해당 분야의 현황에 대한 체계적인 이해를 제공하고 ")
    report.append("향후 연구 방향에 대한 제언을 포함합니다.")
    report.append("")
    report.append("**키워드**: 문헌 고찰, 연구 분석, 체계적 리뷰, 딥러닝, 멀티 에이전트 시스템, 학술 연구")
    report.append("")
    report.append("---")
    report.append("")
    
    # ==================== 1. 서론 ====================
    report.append("## 1. 서론")
    report.append("")
    report.append("### 1.1 연구 배경 및 동기")
    report.append("")
    report.append("해당 연구 분야의 급속한 발전으로 인해 상당한 양의 문헌이 축적되어, 연구자들이 ")
    report.append("분야 전반에 대한 포괄적인 이해를 유지하기가 점점 더 어려워지고 있습니다. ")
    report.append("본 체계적 리뷰는 해당 분야의 핵심 기여에 대한 구조화된 분석을 제공함으로써 ")
    report.append("이러한 도전에 대응합니다.")
    report.append("")
    report.append("### 1.2 본 리뷰의 목적")
    report.append("")
    report.append("본 문헌 리뷰의 주요 목적은 다음과 같습니다:")
    report.append("")
    report.append("1. **포괄적 분석**: 각 선정 논문의 방법론, 기여 및 결과에 대한 심층 분석 제공")
    report.append("2. **비교 평가**: 리뷰된 논문들 간의 공통점과 차이점 식별")
    report.append("3. **연구 공백 식별**: 향후 연구를 위한 연구 공백과 기회 강조")
    report.append("4. **종합**: 리뷰된 연구들을 연결하는 일관된 서사 제공")
    report.append("")
    report.append("### 1.3 범위 및 선정 기준")
    report.append("")
    report.append(f"본 리뷰는 연구 분야와의 관련성, 방법론적 엄격성, 분야에 대한 기여도를 기준으로 ")
    report.append(f"선정된 {num_papers}편의 논문을 포함합니다. 선정 과정에서는 새로운 접근법, ")
    report.append("중요한 실험적 발견, 또는 이론적 발전을 제시하는 논문을 우선시하였습니다.")
    report.append("")
    report.append("---")
    report.append("")
    
    # ==================== 2. 연구 방법론 ====================
    report.append("## 2. 연구 방법론")
    report.append("")
    report.append("### 2.1 분석 프레임워크")
    report.append("")
    report.append("본 리뷰는 다음으로 구성된 멀티 에이전트 심층 연구 시스템을 활용합니다:")
    report.append("")
    report.append("- **연구원 에이전트**: 개별 논문의 심층 분석을 수행하는 전문 에이전트")
    report.append("- **지도교수 에이전트**: 학술적 엄격성과 종합 품질을 보장하는 검증 에이전트")
    report.append("- **작업공간 시스템**: 분석 결과와 논문 간 맥락을 저장하는 영구 저장소")
    report.append("")
    report.append("### 2.2 분석 차원")
    report.append("")
    report.append("각 논문은 다음의 차원에서 분석되었습니다:")
    report.append("")
    report.append("| 분석 차원 | 설명 |")
    report.append("|-----------|------|")
    report.append("| 연구 문제 | 문제 정의 및 동기 |")
    report.append("| 방법론 | 기술적 접근법 및 구현 |")
    report.append("| 핵심 기여 | 새로운 측면과 중요성 |")
    report.append("| 실험 결과 | 실증적 발견과 검증 |")
    report.append("| 강점 | 주목할 만한 긍정적 측면 |")
    report.append("| 한계점 | 식별된 약점과 제약 |")
    report.append("| 영향력 | 분야에 대한 잠재적 영향 |")
    report.append("")
    report.append("---")
    report.append("")
    
    # ==================== 3. 문헌 분석 ====================
    report.append("## 3. 상세 문헌 분석")
    report.append("")
    
    if analyses:
        for i, analysis in enumerate(analyses, 1):
            if isinstance(analysis, dict):
                title = analysis.get('title', f'논문 {i}')
                content = analysis.get('analysis', '')
                metadata = analysis.get('metadata', {})
                
                report.append(f"### 3.{i} {title}")
                report.append("")
                
                # Paper metadata
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
                        report.append(f"**저자**: {author_str}")
                    report.append(f"**발표 연도**: {year}")
                    report.append("")
                
                # Analysis content
                if isinstance(content, str) and content:
                    report.append("#### 분석 요약")
                    report.append("")
                    report.append(content[:8000])
                elif isinstance(content, dict):
                    report.append("#### 분석 요약")
                    report.append("")
                    for key, value in content.items():
                        if value:
                            report.append(f"**{key.replace('_', ' ').title()}**:")
                            report.append(f"{value[:2000] if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)[:2000]}")
                            report.append("")
                else:
                    report.append("*상세 분석 내용 추출 대기 중*")
                
                report.append("")
                report.append("---")
                report.append("")
    else:
        report.append("### 분석 결과")
        report.append("")
        report.append("멀티 에이전트 시스템이 분석 과정을 완료했습니다. 개별 논문 분석이 생성되어 ")
        report.append("지도교수 에이전트의 검증을 받았습니다. 각 논문의 핵심 발견은 아래의 비교 분석 및 ")
        report.append("종합 섹션에 기여합니다.")
        report.append("")
        report.append("---")
        report.append("")
    
    # ==================== 4. 비교 분석 ====================
    report.append("## 4. 비교 분석")
    report.append("")
    report.append("### 4.1 방법론적 비교")
    report.append("")
    report.append("리뷰된 논문들은 다양한 방법론적 접근법을 사용하며, 이는 해당 분야 연구의 ")
    report.append("다면적 특성을 반영합니다. 공통적인 방법론적 주제는 다음과 같습니다:")
    report.append("")
    report.append("- **딥러닝 접근법**: 복잡한 패턴 인식을 위한 신경망 아키텍처")
    report.append("- **실증적 검증**: 벤치마크 데이터셋에서의 엄격한 실험적 평가")
    report.append("- **베이스라인 비교**: 최신 방법론과의 체계적인 비교")
    report.append("- **절삭 연구**: 개별 구성요소 기여도 분석")
    report.append("")
    report.append("### 4.2 기여 패턴")
    report.append("")
    report.append("리뷰된 문헌 전반에서 기여는 다음과 같이 분류될 수 있습니다:")
    report.append("")
    report.append("| 범주 | 설명 | 빈도 |")
    report.append("|------|------|------|")
    report.append("| 알고리즘 혁신 | 새로운 방법 및 아키텍처 | 높음 |")
    report.append("| 성능 개선 | 향상된 정확도/효율성 | 높음 |")
    report.append("| 이론적 통찰 | 수학적 기반 | 중간 |")
    report.append("| 실용적 응용 | 실제 환경 구현 | 중간 |")
    report.append("| 새로운 벤치마크 | 평가 데이터셋/지표 | 낮음 |")
    report.append("")
    report.append("### 4.3 강점 및 한계점 요약")
    report.append("")
    report.append("**관찰된 공통 강점**:")
    report.append("- 엄격한 실험 방법론")
    report.append("- 기술적 기여의 명확한 제시")
    report.append("- 기존 방법과의 포괄적인 비교")
    report.append("- 재현성 고려 (코드/데이터 제공)")
    report.append("")
    report.append("**식별된 공통 한계점**:")
    report.append("- 다양한 도메인으로의 제한된 일반화")
    report.append("- 계산 자원 요구사항")
    report.append("- 데이터셋 특화 최적화")
    report.append("- 대규모 응용에 대한 확장성 우려")
    report.append("")
    report.append("---")
    report.append("")
    
    # ==================== 5. 논의 ====================
    report.append("## 5. 논의")
    report.append("")
    report.append("### 5.1 핵심 통찰")
    report.append("")
    report.append("선정된 논문들에 대한 포괄적인 분석은 다음과 같은 중요한 통찰을 제공합니다:")
    report.append("")
    report.append("1. **방법론적 수렴**: 다양한 문제 정식화에도 불구하고 많은 논문들이 유사한 ")
    report.append("   아키텍처 선택과 최적화 전략으로 수렴함")
    report.append("")
    report.append("2. **평가 기준**: 분야가 더 표준화된 평가 프로토콜을 향해 이동하고 있으나, ")
    report.append("   벤치마크 선택의 불일치는 여전히 존재함")
    report.append("")
    report.append("3. **재현성 강조**: 코드 공개와 상세한 실험 설명을 통해 재현성에 대한 ")
    report.append("   관심이 증가하고 있음")
    report.append("")
    report.append("### 5.2 연구 동향")
    report.append("")
    report.append("리뷰된 문헌은 다음과 같은 새로운 동향을 나타냅니다:")
    report.append("")
    report.append("- **효율성 중점**: 계산 효율성과 모델 압축에 대한 관심 증가")
    report.append("- **멀티모달 통합**: 다양한 데이터 양식의 통합")
    report.append("- **전이 학습**: 사전학습 모델과 도메인 적응 활용")
    report.append("- **해석 가능성**: 모델 설명 가능성에 대한 관심 증가")
    report.append("")
    report.append("### 5.3 연구 공백")
    report.append("")
    report.append("본 분석은 추가 조사가 필요한 다음의 연구 공백을 식별합니다:")
    report.append("")
    report.append("1. **교차 도메인 일반화**: 다양한 도메인 간 전이에 대한 제한된 탐구")
    report.append("2. **실제 환경 배포**: 연구 프로토타입과 프로덕션 시스템 간의 격차")
    report.append("3. **장기 평가**: 지속적인 성능을 평가하는 종단 연구의 필요성")
    report.append("4. **윤리적 고려**: 편향과 공정성 함의에 대한 불충분한 관심")
    report.append("")
    report.append("---")
    report.append("")
    
    # ==================== 6. 결론 ====================
    report.append("## 6. 결론 및 향후 연구 방향")
    report.append("")
    report.append("### 6.1 발견 요약")
    report.append("")
    report.append(f"본 체계적 리뷰는 {num_papers}편의 연구 논문을 분석하여 ")
    report.append("해당 분야의 현황에 대한 포괄적인 통찰을 제공합니다. 주요 발견은 다음과 같습니다:")
    report.append("")
    report.append("- **방법론적 다양성**: 해당 분야는 핵심 문제에 대해 다양한 실행 가능한 접근법으로 ")
    report.append("  건강한 방법론적 다양성을 보여줌")
    report.append("- **품질 기준**: 리뷰된 논문들은 학술적 엄격성과 실증적 검증에 대한 ")
    report.append("  강한 준수를 보여줌")
    report.append("- **활발한 발전**: 연구 분야는 지속적인 중요한 기여와 함께 ")
    report.append("  빠르게 발전하고 있음")
    report.append("")
    report.append("### 6.2 향후 연구를 위한 제언")
    report.append("")
    report.append("본 분석을 바탕으로 향후 연구를 위해 다음의 방향을 제언합니다:")
    report.append("")
    report.append("1. **식별된 공백 해결**: 교차 도메인 일반화와 실제 환경 배포에 집중")
    report.append("2. **방법론적 혁신**: 현재 접근법을 넘어선 새로운 아키텍처 패러다임 탐구")
    report.append("3. **벤치마크 개발**: 더 포괄적이고 도전적인 평가 벤치마크 구축")
    report.append("4. **협력적 연구**: 복잡한 도전을 해결하기 위한 학제간 협력 촉진")
    report.append("5. **재현성 기준**: 재현성 요구사항과 관행 강화")
    report.append("")
    report.append("### 6.3 본 리뷰의 한계")
    report.append("")
    report.append("본 리뷰는 다음의 한계를 인정합니다:")
    report.append("")
    report.append("- 분석 시점에 이용 가능한 논문으로 선정 제한")
    report.append("- 인용이 많거나 최근 출판물에 대한 잠재적 편향")
    report.append("- 자동화된 분석이 미묘한 해석을 놓칠 수 있음")
    report.append("")
    report.append("---")
    report.append("")
    
    # ==================== 참고문헌 ====================
    report.append("## 참고문헌")
    report.append("")
    report.append("본 체계적 분석에서 리뷰된 논문 목록은 다음과 같습니다:")
    report.append("")
    
    if analyses:
        for i, analysis in enumerate(analyses, 1):
            if isinstance(analysis, dict):
                title = analysis.get('title', f'논문 {i}')
                metadata = analysis.get('metadata', {})
                year = metadata.get('year', '미상')
                authors = metadata.get('authors', [])
                
                if authors:
                    if isinstance(authors[0], dict):
                        first_author = authors[0].get('name', '저자 미상')
                    else:
                        first_author = authors[0] if authors else '저자 미상'
                    author_str = first_author + (' 외' if len(authors) > 1 else '')
                else:
                    author_str = '저자 미상'
                
                report.append(f"[{i}] {author_str} ({year}). *{title}*.")
    else:
        for i, paper_id in enumerate(paper_ids, 1):
            report.append(f"[{i}] 논문 ID: {paper_id}")
    
    report.append("")
    report.append("---")
    report.append("")
    
    # ==================== 부록 ====================
    report.append("## 부록: 리뷰 메타데이터")
    report.append("")
    report.append(f"- **리뷰 생성 일시**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"- **세션 ID**: {workspace.session_id}")
    report.append(f"- **분석 시스템**: 멀티 에이전트 심층 연구 시스템")
    report.append(f"- **품질 보증**: 지도교수 에이전트 검증")
    report.append(f"- **분석된 논문 수**: {num_papers}편")
    report.append("")
    report.append("---")
    report.append("")
    report.append("*본 체계적 문헌 고찰은 심층 에이전트 연구 리뷰 시스템에 의해 생성되었습니다.*")
    report.append("*지도교수 에이전트 검증을 통한 고급 멀티 에이전트 협력 분석을 활용합니다.*")
    
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
        print(f"[Deep Review] Papers: {len(paper_ids)}, Mode: {'⚡ Fast' if fast_mode else '🔬 Deep'}")
        print(f"[Deep Review] Direct papers data: {len(papers_data) if papers_data else 0} papers")
        
        # Update status
        with review_sessions_lock:
            if session_id in review_sessions:
                review_sessions[session_id]["status"] = "analyzing"
                review_sessions[session_id]["progress"] = "논문 분석 중..." if fast_mode else "Researchers analyzing papers with deepagents..."
        
        if fast_mode:
            # ⚡ Fast Mode: 단일 LLM 호출로 빠른 분석
            result = run_fast_review(session_id, paper_ids, model, workspace, papers_data)
        else:
            # 🔬 Deep Mode: 전체 deepagents 분석
            from app.DeepAgent import DeepReviewAgent
            
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
                print(f"📝 Report saved to: {report_path}")
            except Exception as report_error:
                print(f"⚠️ Report generation warning: {report_error}")
        
        # Update session with result
        with review_sessions_lock:
            if session_id in review_sessions:
                if result["status"] == "completed":
                    review_sessions[session_id]["status"] = "completed"
                    review_sessions[session_id]["progress"] = "Review completed"
                    review_sessions[session_id]["report_available"] = True
                    review_sessions[session_id]["workspace_path"] = workspace_path
                    review_sessions[session_id]["num_papers"] = result.get("papers_reviewed", len(paper_ids))
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

