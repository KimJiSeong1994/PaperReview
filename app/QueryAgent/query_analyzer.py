"""
유저 질의 분석 에이전트
사용자의 검색 쿼리를 분석하여 의도, 키워드, 개선 사항을 파악
"""
import hashlib
import logging
import os
import json
import threading
import time as _time

logger = logging.getLogger(__name__)
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

# Module-level query analysis cache (TTL-based, thread-safe)
_analysis_cache: Dict[str, Dict[str, Any]] = {}
_analysis_cache_lock = threading.Lock()
_CACHE_TTL = 86400  # 24 hours
_CACHE_MAX_SIZE = 500


def _cache_key(prefix: str, query: str) -> str:
    """Cache key from prefix and normalized query."""
    return hashlib.sha256(f"{prefix}:{query.strip().lower()}".encode()).hexdigest()[:16]


def _get_from_cache(key: str) -> Optional[Dict]:
    """Return cached data if present and not expired, otherwise None."""
    with _analysis_cache_lock:
        entry = _analysis_cache.get(key)
        if entry and (_time.time() - entry["ts"]) < _CACHE_TTL:
            return entry["data"]
        if entry:
            _analysis_cache.pop(key, None)
        return None


def _set_in_cache(key: str, data: Any) -> None:
    """Store data in cache, evicting the 50 oldest entries when full."""
    with _analysis_cache_lock:
        if len(_analysis_cache) >= _CACHE_MAX_SIZE:
            oldest = sorted(_analysis_cache.items(), key=lambda x: x[1]["ts"])[:50]
            for k, _ in oldest:
                _analysis_cache.pop(k, None)
        _analysis_cache[key] = {"data": data, "ts": _time.time()}

load_dotenv()


# 로거는 lazy import로 처리 (권한 오류 방지)
def log_data_processing(operation: str = None):
    """로거 데코레이터 (lazy import)"""
    try:
        from src.utils.logger import log_data_processing as _log_data_processing
        return _log_data_processing(operation)
    except (ImportError, OSError, PermissionError):
        # 로거 사용 불가 시 no-op 데코레이터 반환
        def noop_decorator(func):
            return func
        return noop_decorator

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
        # SSL 검증은 api_server.py에서 전역으로 처리됨

        if not OPENAI_AVAILABLE:
            self.client = None
            self.api_key = None
            self.model = model
            return

        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            self.client = None
            self.model = model
            return

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

        key = _cache_key("analyze", query)
        cached = _get_from_cache(key)
        if cached is not None:
            return cached

        # Client가 없으면 fallback 분석 사용
        if not self.client:
            return self._fallback_analysis(query)

        try:
            # LLM을 사용하여 질의 분석
            analysis_prompt = self._create_analysis_prompt(query)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert academic research query analyzer with deep knowledge in:
- Computer Science (ML, AI, NLP, CV, HCI, Systems, etc.)
- Understanding research paper structures and terminology
- Multilingual query understanding (especially Korean ↔ English)
- Identifying research problems and solutions

Your goal is to:
1. Deeply understand the user's research intent
2. Extract precise technical keywords
3. Generate improved search queries that will find highly relevant papers
4. Recommend effective search strategies

Be particularly careful with:
- Problem-focused queries (e.g., "limitations of X", "improving X")
- Method-specific queries (e.g., "Graph RAG", "multi-agent tool chain")
- Comparative queries (e.g., "X vs Y", "better than X")
- Non-English queries (translate and enhance with English technical terms)"""
                    },
                    {
                        "role": "user",
                        "content": analysis_prompt
                    }
                ],
                temperature=0.3,
                response_format={"type": "json_object"}  # JSON 형식으로 응답
            )

            result_text = response.choices[0].message.content
            analysis_result = json.loads(result_text)

            # 결과 검증 및 기본값 설정
            result = {
                "intent": analysis_result.get("intent", "paper_search"),
                "keywords": analysis_result.get("keywords", []),
                "core_concepts": analysis_result.get("core_concepts", []),
                "research_area": analysis_result.get("research_area", ""),
                "improved_query": analysis_result.get("improved_query", query),
                "search_strategy": analysis_result.get("search_strategy", ""),
                "search_filters": analysis_result.get("search_filters", {}),
                "confidence": float(analysis_result.get("confidence", 0.8)),
                "original_query": query,
                "analysis_details": analysis_result.get("analysis_details", "")
            }
            _set_in_cache(key, result)
            return result

        except json.JSONDecodeError as e:
            logger.error(f"[WARNING] JSON 파싱 오류: {e}")
            return self._fallback_analysis(query)
        except Exception as e:
            logger.error(f"[WARNING] 질의 분석 중 오류: {e}")
            return self._fallback_analysis(query)

    def _create_analysis_prompt(self, query: str) -> str:
        """질의 분석을 위한 프롬프트 생성"""
        return f"""Analyze the following academic research query and provide a structured analysis in JSON format.

Query: "{query}"

Please analyze this query and provide a JSON response with the following structure:
{{
    "intent": "one of: paper_search, topic_exploration, author_search, method_search, comparison, survey, latest_research, problem_solving",
    "keywords": ["list", "of", "main", "keywords"],
    "core_concepts": ["main", "research", "concepts"],
    "research_area": "specific research field (e.g., Machine Learning, NLP, Computer Vision)",
    "improved_query": "improved or expanded version of the query for better search results",
    "search_strategy": "brief search strategy recommendation",
    "search_filters": {{
        "year_start": null or year number,
        "year_end": null or year number,
        "category": null or arxiv category (e.g., "cs.LG", "cs.AI"),
        "min_citations": null or number
    }},
    "confidence": 0.0 to 1.0,
    "analysis_details": "detailed explanation of the analysis"
}}

Guidelines:
- Intent classification:
  * paper_search: User wants to find specific papers on a topic
  * topic_exploration: User wants to explore and understand a research area
  * author_search: User is looking for papers by specific authors
  * method_search: User is searching for specific methods, techniques, or algorithms
  * comparison: User wants to compare different approaches or methods
  * survey: User wants comprehensive survey/review papers
  * latest_research: User wants very recent papers (last 1-2 years)
  * problem_solving: User is looking for papers that solve specific problems or limitations

- Keywords: Extract 3-7 most important technical keywords that should be used for search
- Core Concepts: Identify 2-5 main research concepts or topics
- Research Area: Determine the specific field (ML, NLP, CV, etc.)
- Improved Query: Create a MINIMALLY improved search query
  * STRICT RULE: The improved query must be VERY CLOSE to the original. Only apply these changes:
    1. Fix typos (e.g., "embeddng" → "embedding")
    2. Fix singular/plural (e.g., "words embedding" → "word embeddings")
    3. Expand abbreviations (e.g., "NLP" → "natural language processing")
    4. For Korean queries, translate to English
  * NEVER add domain descriptors like "in natural language processing", "for machine learning", etc.
  * NEVER add broad field names that weren't in the original query
  * Max length: 1.5x the original query length
  * For vague queries, add at most 1 specific synonym (e.g., "word vectors" for "word embeddings")
  * For problem-focused queries, include both problem and solution keywords
- Search Strategy: Suggest how to search effectively
- Search Filters: Recommend filters based on query context
  * For "recent", "latest", "new": set year_start to current_year - 2
  * For "improvement", "limitation": might want recent papers (last 3-5 years)
  * For specific years mentioned: set appropriate year range
- Confidence: Rate analysis confidence (0.0 to 1.0)

Special handling for non-English queries:
- If query is in Korean or other languages, identify the language
- Translate core concepts to English for better search
- Keep both original and English terms in keywords

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

    def classify_topic(self, query: str) -> Dict[str, Any]:
        """
        쿼리가 학술/논문 검색 주제인지 경량 분류.

        gpt-4o-mini + max_tokens=20으로 빠르게 판정한다.
        실패 시 항상 is_academic=True를 반환하여 정상 검색이 차단되지 않도록 한다.

        Args:
            query: 사용자 검색 쿼리

        Returns:
            {"is_academic": True/False}
        """
        if not self.client or not query.strip():
            return {"is_academic": True}

        key = _cache_key("classify", query)
        cached = _get_from_cache(key)
        if cached is not None:
            return cached

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You classify whether a search query is related to academic research, "
                            "scientific papers, or scholarly topics. Return JSON: {\"is_academic\": true/false}\n\n"
                            "Return false ONLY for clearly non-academic queries like:\n"
                            "- Weather, food, shopping, travel, entertainment, sports\n"
                            "- Personal questions, greetings, chitchat\n"
                            "- Software installation guides, product reviews, news\n\n"
                            "Return true for anything that could relate to research, even if vague.\n"
                            "When in doubt, return true."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                temperature=0,
                max_tokens=20,
                response_format={"type": "json_object"},
            )
            result = {"is_academic": bool(json.loads(response.choices[0].message.content).get("is_academic", True))}
            _set_in_cache(key, result)
            return result
        except Exception:
            return {"is_academic": True}

    @log_data_processing("LLM Search Query Generation")
    def generate_search_queries(self, query: str) -> Dict[str, Any]:
        """
        LLM을 사용하여 arXiv와 Google Scholar에 최적화된 검색 쿼리 생성

        Args:
            query: 사용자 검색 쿼리

        Returns:
            검색 쿼리 딕셔너리:
            - arxiv_queries: arXiv 검색에 최적화된 쿼리 리스트
            - scholar_queries: Google Scholar 검색에 최적화된 쿼리 리스트
            - keywords: 핵심 키워드 리스트
            - search_context: 검색 맥락 설명
        """
        if not query or not query.strip():
            return {
                "arxiv_queries": [query],
                "scholar_queries": [query],
                "keywords": [],
                "search_context": ""
            }

        try:
            prompt = self._create_search_query_prompt(query)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert academic search query optimizer.
Your task is to generate highly effective search queries for academic paper databases.

You have deep knowledge of:
- arXiv search syntax (ti:, au:, abs:, cat:, AND, OR)
- Google Scholar search operators (intitle:, author:, "exact phrase")
- Academic terminology across CS, ML, AI, NLP, CV fields
- Research paper naming conventions and common phrasings

Generate queries that will find the most relevant papers for the user's research needs.
For non-English queries, translate to English and use technical terms."""
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.4,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)

            return {
                "arxiv_queries": result.get("arxiv_queries", [query])[:5],
                "scholar_queries": result.get("scholar_queries", [query])[:5],
                "keywords": result.get("keywords", []),
                "search_context": result.get("search_context", ""),
                "original_query": query,
                "translated_query": result.get("translated_query", query),
                "related_terms": result.get("related_terms", [])
            }

        except Exception as e:
            logger.error(f"[WARNING] Search query generation failed: {e}")
            return self._fallback_search_queries(query)

    def _create_search_query_prompt(self, query: str) -> str:
        """LLM 검색 쿼리 생성 프롬프트"""
        return f"""Generate optimized search queries for finding academic papers.

User Query: "{query}"

Generate a JSON response with the following structure:
{{
    "arxiv_queries": [
        "optimized query 1 for arXiv (can use ti:, abs:, cat: syntax)",
        "optimized query 2 for arXiv",
        "optimized query 3 for arXiv"
    ],
    "scholar_queries": [
        "optimized query 1 for Google Scholar",
        "optimized query 2 for Google Scholar",
        "optimized query 3 for Google Scholar"
    ],
    "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
    "search_context": "Brief explanation of what the user is searching for",
    "translated_query": "English translation if original is non-English",
    "related_terms": ["related term 1", "related term 2", "related term 3"]
}}

Guidelines for arXiv queries:
- Use arXiv search syntax: ti: (title), abs: (abstract), au: (author), cat: (category)
- Example: "ti:transformer AND abs:attention mechanism"
- Use AND/OR operators for complex queries
- Include relevant arXiv categories when appropriate (cs.LG, cs.CL, cs.CV, cs.AI)
- First query should be the most specific, subsequent queries broader

Guidelines for Google Scholar queries:
- Use natural language with key technical terms
- Use "exact phrases" for specific concepts
- Include intitle: for title-specific searches
- First query should be the most specific

Guidelines for Keywords:
- Extract 5-7 most important technical terms
- Include both specific and general terms
- Include English versions for non-English queries

Special handling:
- If query is in Korean/other language: translate and provide both versions
- If query mentions specific paper/method name: include exact name
- If query is about a problem/limitation: include problem terms AND solution approaches
- If query is comparative: include all compared methods/approaches

Return only valid JSON."""

    def _fallback_search_queries(self, query: str) -> Dict[str, Any]:
        """검색 쿼리 생성 실패 시 기본 처리"""
        import re

        # 기본 키워드 추출
        words = re.findall(r'\b[a-zA-Z가-힣]{2,}\b', query)
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                     'of', 'with', 'by', 'from', 'is', 'are', '에서', '으로', '와', '과'}
        keywords = [w for w in words if w.lower() not in stopwords][:7]

        # 기본 쿼리 생성
        arxiv_queries = [
            query,
            f"ti:{' AND ti:'.join(keywords[:3])}" if len(keywords) >= 3 else query,
            f"abs:{' AND abs:'.join(keywords[:4])}" if len(keywords) >= 4 else query
        ]

        scholar_queries = [
            query,
            " ".join(keywords[:5]),
            f'intitle:"{keywords[0]}" {" ".join(keywords[1:4])}' if keywords else query
        ]

        return {
            "arxiv_queries": arxiv_queries,
            "scholar_queries": scholar_queries,
            "keywords": keywords,
            "search_context": "Fallback query generation",
            "original_query": query,
            "translated_query": query,
            "related_terms": []
        }

    def classify_difficulty(self, analysis: Dict[str, Any]) -> str:
        """쿼리 난이도를 분류한다 (LLM 호출 없음, 규칙 기반).

        ArxivQA의 easy/medium/hard 전략 분기에 사용.

        Returns:
            ``"easy"`` | ``"medium"`` | ``"hard"``
        """
        confidence = analysis.get("confidence", 0.5)
        intent = analysis.get("intent", "paper_search")
        keywords = analysis.get("keywords", [])

        if confidence >= 0.9 and intent in ("paper_search", "author_search") and len(keywords) <= 3:
            return "easy"
        if confidence < 0.7 or intent in ("topic_exploration", "survey", "comparison") or len(keywords) >= 7:
            return "hard"
        return "medium"

    def diversify_queries(
        self,
        query: str,
        analysis: Dict[str, Any],
        num_variants: int = 3,
    ) -> List[str]:
        """의미적으로 다양한 쿼리 변형을 생성한다.

        ArxivQA의 query diversity 개념 적용 — 원본 쿼리와 용어/관점이
        다른 변형을 생성하여 recall을 높인다.

        Args:
            query: 원본 검색 쿼리.
            analysis: ``analyze_query()`` 결과.
            num_variants: 생성할 변형 수.

        Returns:
            원본 포함 총 ``num_variants + 1`` 개의 쿼리 리스트.
        """
        cache_key = _cache_key("diversify", f"{query}|{analysis.get('intent', '')}")
        cached = _get_from_cache(cache_key)
        if cached:
            return cached

        intent = analysis.get("intent", "paper_search")
        keywords = ", ".join(analysis.get("keywords", [])[:5])

        prompt = f"""Generate {num_variants} diverse search query variants for academic paper search.

Original query: "{query}"
Intent: {intent}
Keywords: {keywords}

Rules:
- Each variant must use DIFFERENT terminology/perspective than the original
- Variants must still address the same core research topic
- Use synonyms, sub-topics, related methods, or broader/narrower framings
- Do NOT just rephrase — explore different ASPECTS of the topic

Return JSON: {{"queries": ["variant1", "variant2", ...]}}"""

        try:
            if not self.client:
                return [query]
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=300,
                temperature=0.7,
                timeout=8,
            )
            data = json.loads(response.choices[0].message.content or "{}")
            variants = data.get("queries", [])[:num_variants]
            result = [query] + [v for v in variants if v and v != query]
            _set_in_cache(cache_key, result)
            return result
        except Exception as e:
            logger.warning("쿼리 다양화 실패: %s", e)
            return [query]

    @log_data_processing("Source-Specific Query Generation")
    def generate_source_specific_queries(
        self, query: str, keywords: List[str] = None
    ) -> Dict[str, str]:
        """
        소스별 최적화 쿼리 생성.

        Args:
            query: 사용자 검색 쿼리
            keywords: QueryAnalysis에서 추출한 키워드 (fallback용)

        Returns:
            {"arxiv": "...", "dblp": "...", "google_scholar": "...", "default": "..."}
        """

        if not self.client:
            return self._fallback_source_queries(query, keywords)

        kw_suffix = ",".join(sorted(keywords)) if keywords else ""
        key = _cache_key("source_queries", f"{query}|{kw_suffix}")
        cached = _get_from_cache(key)
        if cached is not None:
            return cached

        try:
            prompt = f"""Generate optimized search queries for each academic database.

User Query: "{query}"

Return a JSON object with exactly these keys:
{{
    "arxiv": "arXiv-optimized query",
    "dblp": "DBLP-optimized query",
    "google_scholar": "Google Scholar-optimized query"
}}

CRITICAL RULES:
- STAY CLOSE to the original query. Do NOT add unrelated concepts or expand beyond the user's intent.
- arxiv: Use (ti:keyword1 OR ti:keyword2) OR (abs:keyword1 AND abs:keyword2). Use OR between fields, not AND. Keep keyword count small (2-4 core terms).
- dblp: Use 2-4 core technical keywords only. No operators.
- google_scholar: Natural language with "quoted key phrases". Keep it short and focused.
- Translate non-English queries to English.
- Do NOT add tangential topics (e.g., if the query is about "word embeddings", do NOT add "semantic similarity" or "contextual representation" as separate search terms).
- Return ONLY valid JSON."""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You generate source-specific academic search queries. Return only JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
            source_result = {
                "arxiv": result.get("arxiv", query),
                "dblp": result.get("dblp", query),
                "google_scholar": result.get("google_scholar", query),
                "default": query,
            }
            _set_in_cache(key, source_result)
            return source_result

        except Exception as e:
            logger.error(f"[WARNING] Source-specific query generation failed: {e}")
            return self._fallback_source_queries(query, keywords)

    def _fallback_source_queries(
        self, query: str, keywords: List[str] = None
    ) -> Dict[str, str]:
        """LLM 실패 시 keywords 기반 간단 분배"""
        kw = keywords or [w for w in query.split() if len(w) > 2]
        kw = kw[:6]
        arxiv_q = " AND ".join([f"ti:{k}" for k in kw[:3]]) if kw else query
        dblp_q = " ".join(kw[:6]) if kw else query
        return {
            "arxiv": arxiv_q,
            "dblp": dblp_q,
            "google_scholar": query,
            "default": query,
        }

    @log_data_processing("LLM Context Search")
    def search_with_context(self, query: str, context: str = "") -> Dict[str, Any]:
        """
        사용자 컨텍스트를 고려한 검색 쿼리 생성

        Args:
            query: 사용자 검색 쿼리
            context: 추가 컨텍스트 (이전 검색, 관심 분야 등)

        Returns:
            컨텍스트 기반 검색 쿼리
        """
        if not query or not query.strip():
            return self._fallback_search_queries(query)

        try:
            prompt = f"""Based on the user's search query and context, generate optimized academic search queries.

User Query: "{query}"
Context: "{context if context else 'No additional context provided'}"

Generate a JSON response with:
{{
    "arxiv_queries": ["query1", "query2", "query3"],
    "scholar_queries": ["query1", "query2", "query3"],
    "keywords": ["kw1", "kw2", "kw3", "kw4", "kw5"],
    "search_context": "explanation",
    "search_strategy": "recommended approach",
    "confidence": 0.0-1.0
}}

Consider the context to:
- Refine search focus
- Add relevant domain-specific terms
- Suggest related research directions
- Improve query precision

Return only valid JSON."""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert academic search assistant that generates precise search queries based on user context."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            result["original_query"] = query
            result["context_used"] = context
            return result

        except Exception as e:
            logger.error(f"[WARNING] Context search failed: {e}")
            return self._fallback_search_queries(query)

