"""
논문 로더 도구
"""
import json
from typing import List, Dict, Any, Optional
from pathlib import Path


def load_papers_from_ids(paper_ids: List[str], papers_file: str = "data/raw/papers.json") -> List[Dict[str, Any]]:
    """
    논문 ID 리스트로부터 논문 데이터 로드
    
    여러 데이터 소스를 검색:
    1. papers.json (기존 저장된 논문)
    2. 최신 검색 결과 캐시 (새로 검색된 논문)
    
    Args:
        paper_ids: 논문 ID 리스트
        papers_file: 논문 데이터 파일 경로
        
    Returns:
        논문 데이터 리스트
    """
    all_papers = []
    
    # 1. papers.json에서 로드
    papers_path = Path(papers_file)
    if papers_path.exists():
        try:
            with open(papers_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if isinstance(data, dict) and 'papers' in data:
                all_papers.extend(data['papers'])
                print(f"📚 Loaded papers database: {len(data['papers'])} papers")
            elif isinstance(data, list):
                all_papers.extend(data)
                print(f"📚 Loaded papers database: {len(data)} papers")
        except Exception as e:
            print(f"⚠️ Error loading papers.json: {e}")
    
    # 2. 최신 검색 결과 캐시에서도 로드 (새로 검색된 논문)
    cache_paths = [
        Path("data/cache/last_search_results.json"),
        Path("data/search_results_cache.json"),
    ]
    
    for cache_path in cache_paths:
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                
                if isinstance(cache_data, list):
                    all_papers.extend(cache_data)
                    print(f"📦 Loaded search cache: {len(cache_data)} papers from {cache_path.name}")
                elif isinstance(cache_data, dict) and 'papers' in cache_data:
                    all_papers.extend(cache_data['papers'])
                    print(f"📦 Loaded search cache: {len(cache_data['papers'])} papers from {cache_path.name}")
            except Exception as e:
                print(f"⚠️ Error loading cache {cache_path}: {e}")
    
    if not all_papers:
        print(f"⚠️ No papers found in any data source")
        return []
    
    print(f"📊 Total papers in pool: {len(all_papers)}")
    
    # Helper functions to generate doc_id (must match api_server.py)
    import hashlib
    
    def generate_djb2_doc_id(title: str) -> str:
        """Generate doc_id using djb2 hash (matches frontend hashString function)"""
        if not title:
            return ""
        hash_value = 0
        for char in title:
            hash_value = ((hash_value << 5) - hash_value) + ord(char)
            hash_value = hash_value & 0x7FFFFFFF  # Keep positive
        return str(hash_value)
    
    def generate_md5_doc_id(title: str) -> str:
        """Generate stable doc_id using hashlib.md5"""
        if not title:
            return ""
        return str(int(hashlib.md5(title.encode('utf-8')).hexdigest()[:15], 16))
    
    # ID로 필터링
    print(f"🔍 Requested paper_ids: {paper_ids[:5]}...")  # 첫 5개만 출력
    
    # 디버그: 첫 번째 논문의 ID 정보 출력
    if all_papers and len(all_papers) > 0:
        sample_paper = all_papers[0]
        if isinstance(sample_paper, dict):
            sample_title = sample_paper.get('title', '')
            sample_djb2 = generate_djb2_doc_id(sample_title) if sample_title else 'N/A'
            sample_md5 = generate_md5_doc_id(sample_title) if sample_title else 'N/A'
            print(f"📋 Sample paper ID info:")
            print(f"   Title: {sample_title[:50]}...")
            print(f"   djb2 ID: {sample_djb2}")
            print(f"   md5 ID: {sample_md5}")
            print(f"   paper.id: {sample_paper.get('id')}")
            print(f"   paper.doc_id: {sample_paper.get('doc_id')}")
    
    selected_papers = []
    for paper in all_papers:
        # paper가 string이면 skip (데이터 형식 오류)
        if isinstance(paper, str):
            print(f"⚠️ Skipping invalid paper entry (string): {paper[:50]}...")
            continue
        
        # paper가 dict가 아니면 skip
        if not isinstance(paper, dict):
            print(f"⚠️ Skipping invalid paper entry (not dict): {type(paper)}")
            continue
        
        title = paper.get('title', '')
        
        # Generate multiple possible doc_ids (must match ALL methods in api_server.py)
        # Method 1: djb2 hash (primary - used by frontend)
        djb2_doc_id = generate_djb2_doc_id(title) if title else None
        
        # Method 2: MD5 hash (fallback)
        md5_doc_id = generate_md5_doc_id(title) if title else None
        
        # Method 3: Python hash (legacy - varies by session)
        python_hash_id = str(abs(hash(title))) if title else None
        
        # Try multiple ID fields from paper data (doc_id first - most reliable from cache)
        paper_doc_id = paper.get('doc_id')  # From cache - most reliable
        paper_id = paper.get('id') or paper.get('arxiv_id') or paper.get('title_hash')
        
        # Check if any ID matches - doc_id has highest priority
        ids_to_check = [paper_doc_id, djb2_doc_id, paper_id, md5_doc_id, python_hash_id]
        ids_to_check = [str(i) for i in ids_to_check if i]  # Ensure all are strings
        
        # 직접 비교
        matched = any(pid in paper_ids for pid in ids_to_check)
        
        if matched:
            # Add djb2 doc_id to paper for consistency (matches frontend)
            if djb2_doc_id and 'doc_id' not in paper:
                paper['doc_id'] = djb2_doc_id
            selected_papers.append(paper)
    
    print(f"✅ Loaded {len(selected_papers)} papers out of {len(paper_ids)} requested IDs")
    
    return selected_papers


def get_paper_content(paper: Dict[str, Any]) -> Dict[str, Any]:
    """
    논문에서 필요한 컨텐츠 추출
    
    Args:
        paper: 논문 데이터
        
    Returns:
        정리된 논문 컨텐츠
    """
    return {
        "id": paper.get('id') or paper.get('arxiv_id') or paper.get('title_hash', 'unknown'),
        "title": paper.get('title', 'Untitled'),
        "authors": paper.get('authors', []),
        "year": paper.get('year') or paper.get('published_date', '').split('-')[0] if paper.get('published_date') else None,
        "venue": paper.get('venue') or paper.get('journal', ''),
        "abstract": paper.get('abstract', ''),
        "full_text": paper.get('full_text', ''),
        "arxiv_id": paper.get('arxiv_id'),
        "url": paper.get('url') or paper.get('pdf_url'),
        "citations": paper.get('citations'),
        "keywords": paper.get('keywords', []),
    }


def load_and_prepare_papers(paper_ids: List[str]) -> List[Dict[str, Any]]:
    """
    논문 로드 및 준비 (원스톱 함수)
    
    Args:
        paper_ids: 논문 ID 리스트
        
    Returns:
        준비된 논문 데이터 리스트
    """
    papers = load_papers_from_ids(paper_ids)
    prepared_papers = [get_paper_content(paper) for paper in papers]
    
    print(f"📚 Prepared {len(prepared_papers)} papers for analysis")
    for i, paper in enumerate(prepared_papers, 1):
        print(f"  {i}. {paper['title'][:80]}...")
    
    return prepared_papers

