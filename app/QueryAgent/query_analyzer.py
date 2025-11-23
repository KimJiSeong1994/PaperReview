"""
유저 질의 분석 에이전트
사용자의 검색 쿼리를 분석하여 의도, 키워드, 개선 사항을 파악
"""
import os
import sys
import json
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


class QueryAnalyzer:
    """유저 질의 분석 클래스"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        """
        QueryAnalyzer 초기화
        
        Args:
            api_key: OpenAI API 키 (없으면 환경변수에서 로드)
            model: 사용할 LLM 모델 (기본값: gpt-4o-mini)
        """
        if not OPENAI_AVAILABLE:
            raise ImportError("OpenAI package is required. Install with: pip install openai")
        
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY environment variable or pass api_key parameter.")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = model
    
    @log_data_processing("Query Analysis")
    def analyze_query(self, query: str) -> Dict[str, Any]:
        """
        사용자 질의를 분석하여 의도, 키워드, 개선 사항을 파악
        
        Args:
            query: 사용자 검색 쿼리
            
        Returns:
            분석 결과 딕셔너리:
            - intent: 검색 의도 (paper_search, topic_exploration, author_search, etc.)
            - keywords: 주요 키워드 리스트
            - improved_query: 개선된 검색 쿼리
            - search_filters: 추천 검색 필터
            - confidence: 분석 신뢰도 (0.0 ~ 1.0)
        """
        if not query or not query.strip():
            return {
                "intent": "unknown",
                "keywords": [],
                "improved_query": "",
                "search_filters": {},
                "confidence": 0.0,
                "error": "Empty query"
            }
        
        try:
            # LLM을 사용하여 질의 분석
            analysis_prompt = self._create_analysis_prompt(query)
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at analyzing academic research queries. Analyze user queries to understand their intent, extract keywords, and suggest improvements for better search results."
                    },
                    {
                        "role": "user",
                        "content": analysis_prompt
                    }
                ],
                temperature=0.3,  # 낮은 temperature로 일관된 분석
                response_format={"type": "json_object"}  # JSON 형식으로 응답
            )
            
            result_text = response.choices[0].message.content
            analysis_result = json.loads(result_text)
            
            # 결과 검증 및 기본값 설정
            return {
                "intent": analysis_result.get("intent", "paper_search"),
                "keywords": analysis_result.get("keywords", []),
                "improved_query": analysis_result.get("improved_query", query),
                "search_filters": analysis_result.get("search_filters", {}),
                "confidence": float(analysis_result.get("confidence", 0.8)),
                "original_query": query,
                "analysis_details": analysis_result.get("analysis_details", "")
            }
            
        except json.JSONDecodeError as e:
            print(f"⚠ JSON 파싱 오류: {e}")
            return self._fallback_analysis(query)
        except Exception as e:
            print(f"⚠ 질의 분석 중 오류: {e}")
            return self._fallback_analysis(query)
    
    def _create_analysis_prompt(self, query: str) -> str:
        """질의 분석을 위한 프롬프트 생성"""
        return f"""Analyze the following academic research query and provide a structured analysis in JSON format.

Query: "{query}"

Please analyze this query and provide a JSON response with the following structure:
{{
    "intent": "one of: paper_search, topic_exploration, author_search, method_search, comparison, survey, latest_research",
    "keywords": ["list", "of", "main", "keywords"],
    "improved_query": "improved or expanded version of the query for better search results",
    "search_filters": {{
        "year_start": null or year number,
        "year_end": null or year number,
        "category": null or arxiv category (e.g., "cs.LG", "cs.AI"),
        "min_citations": null or number
    }},
    "confidence": 0.0 to 1.0,
    "analysis_details": "brief explanation of the analysis"
}}

Guidelines:
- Intent classification:
  * paper_search: User wants to find specific papers
  * topic_exploration: User wants to explore a research topic
  * author_search: User is looking for papers by specific authors
  * method_search: User is searching for specific methods or techniques
  * comparison: User wants to compare different approaches
  * survey: User wants survey papers or comprehensive reviews
  * latest_research: User wants recent papers (last 1-2 years)

- Keywords: Extract 3-7 most important keywords that should be used for search
- Improved query: Expand or refine the query while maintaining the original intent
- Search filters: Suggest appropriate filters based on the query (e.g., if query mentions "recent" or "2024", set year_end)
- Confidence: Rate how confident you are in the analysis (0.0 to 1.0)

Return only valid JSON, no additional text."""
    
    def _fallback_analysis(self, query: str) -> Dict[str, Any]:
        """LLM 분석 실패 시 기본 분석 수행"""
        # 간단한 키워드 추출
        keywords = [word.strip() for word in query.split() if len(word.strip()) > 2]
        
        # 기본 의도 추정
        query_lower = query.lower()
        if any(word in query_lower for word in ['author', 'by', 'written by']):
            intent = "author_search"
        elif any(word in query_lower for word in ['recent', 'latest', 'new', '2024', '2023']):
            intent = "latest_research"
        elif any(word in query_lower for word in ['survey', 'review', 'overview']):
            intent = "survey"
        elif any(word in query_lower for word in ['compare', 'comparison', 'vs', 'versus']):
            intent = "comparison"
        else:
            intent = "paper_search"
        
        return {
            "intent": intent,
            "keywords": keywords[:7],  # 최대 7개 키워드
            "improved_query": query,
            "search_filters": {},
            "confidence": 0.5,
            "original_query": query,
            "analysis_details": "Fallback analysis using simple keyword extraction"
        }
    
    def extract_keywords(self, query: str) -> List[str]:
        """
        질의에서 키워드만 추출 (간단한 버전)
        
        Args:
            query: 사용자 검색 쿼리
            
        Returns:
            키워드 리스트
        """
        analysis = self.analyze_query(query)
        return analysis.get("keywords", [])
    
    def improve_query(self, query: str) -> str:
        """
        질의를 개선하여 반환
        
        Args:
            query: 원본 검색 쿼리
            
        Returns:
            개선된 검색 쿼리
        """
        analysis = self.analyze_query(query)
        return analysis.get("improved_query", query)
    
    def get_search_filters(self, query: str) -> Dict[str, Any]:
        """
        질의 기반 검색 필터 추천
        
        Args:
            query: 사용자 검색 쿼리
            
        Returns:
            추천 검색 필터 딕셔너리
        """
        analysis = self.analyze_query(query)
        return analysis.get("search_filters", {})
    
    def classify_intent(self, query: str) -> str:
        """
        질의 의도 분류
        
        Args:
            query: 사용자 검색 쿼리
            
        Returns:
            검색 의도 (paper_search, topic_exploration, etc.)
        """
        analysis = self.analyze_query(query)
        return analysis.get("intent", "paper_search")

