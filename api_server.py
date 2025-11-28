"""
FastAPI backend server for Paper Review Agent
Provides REST API for React frontend
"""
import os
import sys
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
                    # Generate doc_id using same method as frontend
                    title = paper.get("title", "")
                    doc_id = str(abs(hash(title)))
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
            """Generate doc_id matching frontend hashString function"""
            hash_value = 0
            for char in title:
                char_code = ord(char)
                hash_value = ((hash_value << 5) - hash_value) + char_code
                hash_value = hash_value & hash_value  # Convert to 32bit integer
            return str(abs(hash_value))
        
        for paper in papers_data:
            if 'doc_id' not in paper:
                title = paper.get("title", "")
                doc_id = generate_doc_id(title)
                paper['doc_id'] = doc_id
        
        for paper in papers_data:
            doc_id = paper.get("doc_id")
            if not doc_id:
                # Fallback if doc_id still missing
                title = paper.get("title", "")
                doc_id = str(abs(hash(title)))
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

