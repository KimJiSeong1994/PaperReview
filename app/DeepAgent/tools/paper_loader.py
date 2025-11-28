"""
논문 로더 도구
"""
import json
from typing import List, Dict, Any, Optional
from pathlib import Path


def load_papers_from_ids(paper_ids: List[str], papers_file: str = "data/raw/papers.json") -> List[Dict[str, Any]]:
    """
    논문 ID 리스트로부터 논문 데이터 로드
    
    Args:
        paper_ids: 논문 ID 리스트
        papers_file: 논문 데이터 파일 경로
        
    Returns:
        논문 데이터 리스트
    """
    papers_path = Path(papers_file)
    
    if not papers_path.exists():
        print(f"⚠️ Papers file not found: {papers_file}")
        return []
    
    with open(papers_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Handle different JSON structures
    if isinstance(data, dict) and 'papers' in data:
        # Structure: {"metadata": {...}, "papers": [...]}
        all_papers = data['papers']
        print(f"📚 Loaded papers database: {data.get('metadata', {}).get('total_papers', len(all_papers))} papers")
    elif isinstance(data, list):
        # Structure: [...]
        all_papers = data
    else:
        print(f"⚠️ Unexpected papers.json structure: {type(data)}")
        all_papers = []
    
    # ID로 필터링
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
        
        # Generate doc_id from title hash (same as API server)
        title = paper.get('title', '')
        doc_id = str(abs(hash(title))) if title else None
        
        # Try multiple ID fields
        paper_id = paper.get('id') or paper.get('arxiv_id') or paper.get('title_hash') or doc_id
        
        # Also check if the doc_id matches
        if paper_id in paper_ids or doc_id in paper_ids:
            # Add doc_id to paper for consistency
            if doc_id and 'doc_id' not in paper:
                paper['doc_id'] = doc_id
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

