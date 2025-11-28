"""
LLM 기반 검색 결과 관련성 필터 에이전트
사용자 질의와 검색된 논문의 관련성을 평가하여 필터링
"""
import os
import sys
import json
import asyncio
import concurrent.futures
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.join(os.path.dirname(__file__), '../../src'))
from utils.logger import log_data_processing

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAI = None


class RelevanceFilter:
    """LLM 기반 검색 결과 관련성 필터"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        """
        RelevanceFilter 초기화
        
        Args:
            api_key: OpenAI API 키 (없으면 환경변수에서 로드)
            model: 사용할 LLM 모델 (기본값: gpt-4o-mini)
        """
        # SSL 검증 비활성화 (macOS 보안 정책 우회)
        import ssl
        try:
            _create_unverified_https_context = ssl._create_unverified_context
        except AttributeError:
            pass
        else:
            ssl._create_default_https_context = _create_unverified_https_context
        
        if not OPENAI_AVAILABLE:
            raise ImportError("OpenAI package is required. Install with: pip install openai")
        
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OpenAI API key is required.")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = model
    
    @log_data_processing("Relevance Filtering")
    def filter_papers(self, query: str, papers: List[Dict[str, Any]], 
                     threshold: float = 0.6, max_papers: int = None, parallel: bool = True) -> List[Dict[str, Any]]:
        """
        검색된 논문들을 질의와의 관련성에 따라 필터링
        
        Args:
            query: 사용자 검색 쿼리
            papers: 검색된 논문 리스트
            threshold: 관련성 점수 임계값 (0.0 ~ 1.0)
            max_papers: 반환할 최대 논문 수
            parallel: 병렬 처리 여부 (기본 True)
            
        Returns:
            관련성 점수가 높은 논문 리스트 (관련성 점수 포함)
        """
        if not papers:
            return []
        
        print(f"[관련성 필터] {len(papers)}개 논문 평가 시작... (병렬: {parallel})")
        
        # 배치로 처리 (한 번에 10개씩)
        batch_size = 10
        batches = [papers[i:i+batch_size] for i in range(0, len(papers), batch_size)]
        
        if parallel and len(batches) > 1:
            # 병렬 처리
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(batches))) as executor:
                futures = [executor.submit(self._evaluate_batch, query, batch) for batch in batches]
                all_results = []
                for future in concurrent.futures.as_completed(futures):
                    all_results.append(future.result())
            
            # 결과 병합
            batch_idx = 0
            filtered_papers = []
            for batch, scores in zip(batches, all_results):
                for paper, score in zip(batch, scores):
                    if score >= threshold:
                        paper['relevance_score'] = score
                        filtered_papers.append(paper)
                        print(f"  ✓ [{score:.2f}] {paper.get('title', 'Untitled')[:60]}")
                    else:
                        print(f"  ✗ [{score:.2f}] {paper.get('title', 'Untitled')[:60]}")
        else:
            # 순차 처리
            filtered_papers = []
            for batch in batches:
                batch_results = self._evaluate_batch(query, batch)
                for paper, score in zip(batch, batch_results):
                    if score >= threshold:
                        paper['relevance_score'] = score
                        filtered_papers.append(paper)
                        print(f"  ✓ [{score:.2f}] {paper.get('title', 'Untitled')[:60]}")
                    else:
                        print(f"  ✗ [{score:.2f}] {paper.get('title', 'Untitled')[:60]}")
        
        # 관련성 점수 순으로 정렬
        filtered_papers.sort(key=lambda p: p['relevance_score'], reverse=True)
        
        # 최대 개수 제한
        if max_papers:
            filtered_papers = filtered_papers[:max_papers]
        
        print(f"[관련성 필터] {len(filtered_papers)}/{len(papers)}개 논문 선택 (임계값: {threshold})")
        return filtered_papers
    
    def _evaluate_batch(self, query: str, papers: List[Dict[str, Any]]) -> List[float]:
        """배치 논문들의 관련성 평가"""
        try:
            # 평가 프롬프트 생성
            evaluation_prompt = self._create_evaluation_prompt(query, papers)
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert academic research evaluator. 
Your task is to evaluate the relevance between a user's research query and academic papers.
Rate each paper's relevance on a scale of 0.0 to 1.0, where:
- 1.0 = Highly relevant, directly addresses the query
- 0.7-0.9 = Very relevant, closely related to the query
- 0.5-0.6 = Moderately relevant, somewhat related
- 0.3-0.4 = Slightly relevant, tangentially related
- 0.0-0.2 = Not relevant, unrelated to the query

Consider:
- Topic match: Does the paper discuss the same research area?
- Problem match: Does it address similar problems or challenges?
- Method match: Does it use similar methods or approaches?
- Goal match: Does it have similar research goals?"""
                    },
                    {
                        "role": "user",
                        "content": evaluation_prompt
                    }
                ],
                temperature=0.2,  # 낮은 temperature로 일관된 평가
                response_format={"type": "json_object"}
            )
            
            result_text = response.choices[0].message.content
            evaluation = json.loads(result_text)
            
            # 점수 추출 및 검증
            scores = evaluation.get("scores", [])
            if len(scores) != len(papers):
                print(f"⚠ 평가 결과 개수 불일치: {len(scores)} vs {len(papers)}")
                return [0.5] * len(papers)  # 기본값 반환
            
            return [float(s) for s in scores]
            
        except Exception as e:
            print(f"⚠ 관련성 평가 중 오류: {e}")
            # 폴백: 간단한 키워드 매칭으로 점수 계산
            return [self._fallback_score(query, paper) for paper in papers]
    
    def _create_evaluation_prompt(self, query: str, papers: List[Dict[str, Any]]) -> str:
        """평가 프롬프트 생성"""
        papers_info = []
        for idx, paper in enumerate(papers):
            title = paper.get('title', 'Untitled')
            abstract = paper.get('abstract', '')[:500]  # 최대 500자
            
            papers_info.append(f"""Paper {idx + 1}:
Title: {title}
Abstract: {abstract if abstract else "No abstract available"}""")
        
        papers_text = "\n\n".join(papers_info)
        
        return f"""User's research query: "{query}"

Evaluate the relevance of each paper to this query.

{papers_text}

Provide your evaluation in JSON format:
{{
    "scores": [0.0 to 1.0 for paper 1, 0.0 to 1.0 for paper 2, ...],
    "reasoning": ["brief reason for paper 1", "brief reason for paper 2", ...]
}}

Return only valid JSON, no additional text."""
    
    def _fallback_score(self, query: str, paper: Dict[str, Any]) -> float:
        """LLM 평가 실패 시 간단한 키워드 매칭으로 점수 계산"""
        query_lower = query.lower()
        title_lower = paper.get('title', '').lower()
        abstract_lower = paper.get('abstract', '').lower()
        
        # 키워드 추출 (단순화)
        import re
        query_words = set(re.findall(r'\b\w{4,}\b', query_lower))
        
        if not query_words:
            return 0.5
        
        # 제목과 초록에서 키워드 매칭
        title_matches = sum(1 for word in query_words if word in title_lower)
        abstract_matches = sum(1 for word in query_words if word in abstract_lower)
        
        # 점수 계산
        title_score = (title_matches / len(query_words)) * 0.7  # 제목 가중치 70%
        abstract_score = (abstract_matches / len(query_words)) * 0.3  # 초록 가중치 30%
        
        total_score = min(title_score + abstract_score, 1.0)
        return round(total_score, 2)
    
    def evaluate_single(self, query: str, paper: Dict[str, Any]) -> float:
        """
        단일 논문의 관련성 평가
        
        Args:
            query: 사용자 검색 쿼리
            paper: 평가할 논문
            
        Returns:
            관련성 점수 (0.0 ~ 1.0)
        """
        scores = self._evaluate_batch(query, [paper])
        return scores[0] if scores else 0.5
    
    def rank_papers(self, query: str, papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        논문들을 관련성 순으로 재정렬 (필터링 없이)
        
        Args:
            query: 사용자 검색 쿼리
            papers: 논문 리스트
            
        Returns:
            관련성 순으로 정렬된 논문 리스트 (관련성 점수 포함)
        """
        if not papers:
            return []
        
        print(f"[관련성 순위] {len(papers)}개 논문 평가 시작...")
        
        # 배치로 처리
        batch_size = 10
        scored_papers = []
        
        for i in range(0, len(papers), batch_size):
            batch = papers[i:i+batch_size]
            batch_scores = self._evaluate_batch(query, batch)
            
            for paper, score in zip(batch, batch_scores):
                paper['relevance_score'] = score
                scored_papers.append(paper)
        
        # 관련성 점수 순으로 정렬
        scored_papers.sort(key=lambda p: p['relevance_score'], reverse=True)
        
        print(f"[관련성 순위] 평가 완료 (평균: {sum(p['relevance_score'] for p in scored_papers)/len(scored_papers):.2f})")
        return scored_papers

