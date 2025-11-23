"""
FastAPI backend server for Paper Review Agent
Provides REST API for React frontend
"""
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Ensure project modules are importable
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_ROOT / "src"))
sys.path.append(str(PROJECT_ROOT / "app" / "SearchAgent"))

from search_agent import SearchAgent

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

# Global agent instance
search_agent = SearchAgent(openai_api_key=os.getenv("OPENAI_API_KEY"))


class SearchRequest(BaseModel):
    query: str
    max_results: int = 20
    sources: List[str] = ["arxiv", "connected_papers", "google_scholar"]
    sort_by: str = "relevance"
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    author: Optional[str] = None
    category: Optional[str] = None


class SearchResponse(BaseModel):
    results: Dict[str, List[Dict[str, Any]]]
    total: int


@app.get("/")
async def root():
    return {"message": "Paper Review Agent API", "version": "1.0.0"}


@app.post("/api/search", response_model=SearchResponse)
async def search_papers(request: SearchRequest):
    """Search papers across multiple sources"""
    try:
        import traceback
        filters = {
            "sources": request.sources,
            "max_results": request.max_results,
            "sort_by": request.sort_by,
            "year_start": request.year_start,
            "year_end": request.year_end,
            "author": request.author,
            "category": request.category,
        }
        print(f"[API] Searching for: {request.query}")
        print(f"[API] Filters: {filters}")
        results = search_agent.search_with_filters(request.query, filters)
        print(f"[API] Results: {sum(len(papers) for papers in results.values())} papers found")
        
        # Ensure all sources are in results
        for source in request.sources:
            if source not in results:
                results[source] = []
        
        total = sum(len(papers) for papers in results.values())
        return SearchResponse(results=results, total=total)
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[API] Error in search: {error_trace}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@app.post("/api/save")
async def save_papers(
    results: Dict[str, List[Dict[str, Any]]], 
    query: str = "",
    generate_embeddings: bool = True,
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
        # 먼저 기본 spring layout 생성
        layout = nx.spring_layout(graph, seed=42, k=0.55, iterations=50)
        
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

