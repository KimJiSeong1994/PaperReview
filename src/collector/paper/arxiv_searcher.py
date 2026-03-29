"""
arXiv 전용 검색 클라이언트
arxiv 패키지를 활용한 직접 검색 (Enhanced Version)

강화된 검색 기능:
- 복합 검색 전략 (제목, 초록, 전체)
- 쿼리 확장 및 정규화
- 논문 제목 정확 매칭
- 다중 검색 결과 병합
"""

import logging
import random
import threading
import time
import arxiv
from typing import List, Dict, Any, Set
from datetime import datetime
import re
from src.utils.logger import log_arxiv_search

logger = logging.getLogger(__name__)

class ArxivSearcher:
    """arXiv 직접 검색 클라이언트 (Enhanced)"""

    # 클래스 레벨 rate limiter (모든 인스턴스 · 스레드 공유)
    _global_semaphore = threading.Semaphore(1)
    _last_request_time = 0.0
    _min_delay = 3.5  # arXiv 권장 3초 + 여유

    def __init__(self):
        self.client = arxiv.Client(
            page_size=50,
            delay_seconds=3.5,
            num_retries=5,
        )

        # 검색어 확장을 위한 동의어 사전
        self.synonyms = {
            "llm": ["large language model", "language model", "gpt", "transformer"],
            "nlp": ["natural language processing", "text processing", "language understanding"],
            "cv": ["computer vision", "image recognition", "visual recognition"],
            "ml": ["machine learning", "deep learning", "neural network"],
            "rag": ["retrieval augmented generation", "retrieval-augmented", "knowledge retrieval"],
            "gnn": ["graph neural network", "graph network", "graph learning"],
            "bert": ["bidirectional encoder", "transformer encoder"],
            "attention": ["self-attention", "attention mechanism", "transformer attention"],
            "agent": ["ai agent", "autonomous agent", "intelligent agent"],
            "multimodal": ["multi-modal", "vision-language", "cross-modal"],
            "diffusion": ["diffusion model", "denoising diffusion", "score-based generative"],
            "rlhf": ["reinforcement learning from human feedback", "human feedback", "preference learning"],
            "cot": ["chain of thought", "chain-of-thought", "reasoning chain"],
            "moe": ["mixture of experts", "mixture-of-experts", "sparse expert"],
            "vit": ["vision transformer", "visual transformer", "image transformer"],
            "lora": ["low-rank adaptation", "low rank adaptation", "parameter-efficient fine-tuning"],
            "dpo": ["direct preference optimization", "preference optimization"],
            "quantization": ["model quantization", "weight quantization", "post-training quantization"],
            "distillation": ["knowledge distillation", "model distillation", "teacher-student"],
            "federated": ["federated learning", "distributed learning", "privacy-preserving learning"],
            "ssl": ["self-supervised learning", "contrastive learning", "pretext task"],
            "agentic": ["agentic ai", "tool-use agent", "autonomous ai agent"],
            "mamba": ["state space model", "selective state space", "ssm"],
            "peft": ["parameter-efficient fine-tuning", "adapter tuning", "prompt tuning"],
            "nerf": ["neural radiance field", "neural radiance fields", "3d reconstruction"],
        }
        # 역방향 매핑: 풀네임 → 약어
        self._reverse_synonyms = {}
        for abbr, fullnames in self.synonyms.items():
            for fullname in fullnames:
                self._reverse_synonyms[fullname] = abbr

    def _rate_limit(self):
        """글로벌 rate limiting — Semaphore 기반 공정한 스케줄링"""
        ArxivSearcher._global_semaphore.acquire()
        try:
            now = time.time()
            elapsed = now - ArxivSearcher._last_request_time
            if elapsed < ArxivSearcher._min_delay:
                time.sleep(ArxivSearcher._min_delay - elapsed)
            ArxivSearcher._last_request_time = time.time()
        finally:
            ArxivSearcher._global_semaphore.release()

    def _safe_results(self, search: arxiv.Search) -> list:
        """arXiv 검색 실행 — rate limiting + HTTP 429 exponential backoff"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._rate_limit()
                return list(self.client.results(search))
            except Exception as e:
                error_str = str(e)
                if '429' in error_str:
                    wait = (2 ** attempt) * 5 + random.uniform(0, 2)
                    logger.warning(
                        "arXiv rate limited (attempt %d/%d), waiting %.1fs",
                        attempt + 1, max_retries, wait,
                    )
                    time.sleep(wait)
                    continue
                raise
        logger.error("arXiv rate limit retries exhausted")
        return []

    def _normalize_query(self, query: str) -> str:
        """쿼리 정규화"""
        # 소문자 변환
        query = query.lower()
        # 특수문자 정리
        query = re.sub(r'[^\w\s\-\:]', ' ', query)
        # 다중 공백 정리
        query = re.sub(r'\s+', ' ', query).strip()
        return query

    def _expand_query(self, query: str) -> List[str]:
        """쿼리 확장 - 동의어 및 관련 용어 추가 (정방향 + 역방향)"""
        expanded = [query]
        query_lower = query.lower()

        # 정방향: 약어 → 풀네임
        for key, synonyms in self.synonyms.items():
            if key in query_lower:
                for syn in synonyms[:2]:
                    expanded_query = query_lower.replace(key, syn)
                    if expanded_query != query_lower and expanded_query not in expanded:
                        expanded.append(expanded_query)

        # 역방향: 풀네임 → 약어
        for fullname, abbr in self._reverse_synonyms.items():
            if fullname in query_lower:
                expanded_query = query_lower.replace(fullname, abbr)
                if expanded_query != query_lower and expanded_query not in expanded:
                    expanded.append(expanded_query)

        return expanded[:4]  # 최대 4개 쿼리

    def _extract_keywords(self, query: str) -> List[str]:
        """쿼리에서 핵심 키워드 추출"""
        # 불용어 제거
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                     'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
                     'has', 'have', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                     'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare',
                     'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they'}

        words = self._normalize_query(query).split()
        keywords = [w for w in words if w not in stopwords and len(w) > 2]
        return keywords

    def _build_advanced_query(self, query: str, search_type: str = "all") -> str:
        """고급 arXiv 쿼리 생성"""
        keywords = self._extract_keywords(query)

        if search_type == "title":
            # 제목 검색: AND 조합
            if len(keywords) > 1:
                return "ti:" + " AND ti:".join(keywords)
            return f"ti:{query}"

        elif search_type == "abstract":
            # 초록 검색
            if len(keywords) > 1:
                return "abs:" + " AND abs:".join(keywords[:5])  # 상위 5개 키워드
            return f"abs:{query}"

        elif search_type == "exact_title":
            # 정확한 제목 매칭
            return f'ti:"{query}"'

        else:  # "all"
            # 복합 검색: 제목 OR 초록
            title_query = "ti:" + " AND ti:".join(keywords[:3]) if keywords else f"ti:{query}"
            abstract_query = "abs:" + " AND abs:".join(keywords[:3]) if keywords else f"abs:{query}"
            return f"({title_query}) OR ({abstract_query})"

    @log_arxiv_search
    def search(self, query: str, max_results: int = 10, sort_by: str = "relevance") -> List[Dict[str, Any]]:
        """
        arXiv에서 논문 검색 (Enhanced)

        Args:
            query: 검색 쿼리
            max_results: 최대 결과 수
            sort_by: 정렬 기준 (relevance, lastUpdatedDate, submittedDate)

        Returns:
            논문 정보 리스트
        """
        try:
            # 정렬 기준 설정
            sort_criterion = arxiv.SortCriterion.SubmittedDate
            if sort_by == "relevance":
                sort_criterion = arxiv.SortCriterion.Relevance
            elif sort_by == "lastUpdatedDate":
                sort_criterion = arxiv.SortCriterion.LastUpdatedDate

            # 1차: 고급 쿼리 검색 (제목+초록 필드 지정)
            # 이미 arXiv 구문(ti:, abs:, AND, OR)이 포함된 쿼리면 그대로 사용
            if any(prefix in query for prefix in ("ti:", "abs:", "au:", "cat:")):
                advanced_query = query
            else:
                advanced_query = self._build_advanced_query(query, search_type="all")
            search = arxiv.Search(query=advanced_query, max_results=max_results, sort_by=sort_criterion)
            results = [self._extract_paper_info(result) for result in self._safe_results(search)]

            # 결과가 부족하면 추가 검색 시도
            if len(results) < max_results // 2:
                additional = self.enhanced_search(query, max_results=max_results - len(results))
                # 중복 제거 후 병합
                seen_titles = {r['title'].lower() for r in results}
                for paper in additional:
                    if paper['title'].lower() not in seen_titles:
                        results.append(paper)
                        seen_titles.add(paper['title'].lower())

            return results[:max_results]

        except Exception as e:
            logger.error(f"[arXiv] Error searching: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return []

    @log_arxiv_search
    def enhanced_search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        향상된 다중 전략 검색

        여러 검색 전략을 조합하여 더 포괄적인 결과 제공
        """
        all_results: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()

        try:
            # 쿼리 확장
            expanded_queries = self._expand_query(query)

            # 검색 전략: "all" (복합) 1개만 사용 — rate limit 방지
            strategies = [
                ("all", max_results),
            ]

            for strategy, limit in strategies:
                for q in expanded_queries[:1]:  # 원본 쿼리만
                    try:
                        advanced_query = self._build_advanced_query(q, strategy)
                        search = arxiv.Search(
                            query=advanced_query,
                            max_results=limit,
                            sort_by=arxiv.SortCriterion.Relevance
                        )

                        for result in self._safe_results(search):
                            arxiv_id = result.get_short_id()
                            if arxiv_id not in seen_ids:
                                seen_ids.add(arxiv_id)
                                all_results.append(self._extract_paper_info(result))

                    except Exception as e:
                        logger.error(f"[arXiv] Strategy '{strategy}' failed for query '{q[:30]}...': {e}")
                        continue

                if len(all_results) >= max_results:
                    break

            return all_results[:max_results]

        except Exception as e:
            logger.error(f"[arXiv] Enhanced search error: {e}")
            return []

    @log_arxiv_search
    def search_by_title(self, title: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        논문 제목으로 정확한 검색

        Args:
            title: 논문 제목
            max_results: 최대 결과 수

        Returns:
            논문 정보 리스트
        """
        try:
            results = []

            # 1. 정확한 제목 검색
            exact_query = f'ti:"{title}"'
            search = arxiv.Search(query=exact_query, max_results=max_results)
            results.extend([self._extract_paper_info(r) for r in self._safe_results(search)])

            # 2. 결과가 없으면 키워드 기반 검색
            if not results:
                keywords = self._extract_keywords(title)
                if keywords:
                    keyword_query = " AND ".join([f"ti:{kw}" for kw in keywords[:5]])
                    search = arxiv.Search(query=keyword_query, max_results=max_results)
                    results.extend([self._extract_paper_info(r) for r in self._safe_results(search)])

            return results[:max_results]

        except Exception as e:
            logger.error(f"[arXiv] Title search error: {e}")
            return []

    @log_arxiv_search
    def search_similar_papers(self, paper_title: str, paper_abstract: str = "", max_results: int = 10) -> List[Dict[str, Any]]:
        """
        유사 논문 검색

        주어진 논문과 유사한 논문들을 검색
        """
        try:
            # 제목과 초록에서 핵심 키워드 추출
            text = f"{paper_title} {paper_abstract}"
            keywords = self._extract_keywords(text)[:7]  # 상위 7개 키워드

            if not keywords:
                return []

            # 키워드 기반 검색
            query = " OR ".join([f"(ti:{kw} OR abs:{kw})" for kw in keywords])
            search = arxiv.Search(
                query=query,
                max_results=max_results + 5,  # 여유분 확보
                sort_by=arxiv.SortCriterion.Relevance
            )

            results = []
            original_title_lower = paper_title.lower()

            for result in self._safe_results(search):
                # 원본 논문 제외
                if result.title.lower() != original_title_lower:
                    results.append(self._extract_paper_info(result))

            return results[:max_results]

        except Exception as e:
            logger.error(f"[arXiv] Similar paper search error: {e}")
            return []

    @log_arxiv_search
    def search_by_category(self, category: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        카테고리별 논문 검색

        Args:
            category: arXiv 카테고리 (예: cs.AI, cs.LG, stat.ML)
            max_results: 최대 결과 수

        Returns:
            논문 정보 리스트
        """
        try:
            query = f"cat:{category}"
            return self.search(query, max_results)

        except Exception as e:
            logger.warning("arXiv category search failed for %s: %s", category, e)
            return []

    @log_arxiv_search
    def search_by_author(self, author: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        저자별 논문 검색

        Args:
            author: 저자 이름
            max_results: 최대 결과 수

        Returns:
            논문 정보 리스트
        """
        try:
            query = f"au:{author}"
            return self.search(query, max_results)

        except Exception as e:
            logger.warning("arXiv author search failed for %s: %s", author, e)
            return []

    @log_arxiv_search
    def get_recent_papers(self, category: str = None, days: int = 7, max_results: int = 20) -> List[Dict[str, Any]]:
        """
        최근 논문 검색

        Args:
            category: 카테고리 (선택사항)
            days: 최근 며칠간의 논문
            max_results: 최대 결과 수

        Returns:
            논문 정보 리스트
        """
        try:
            from datetime import timedelta

            # 날짜 범위 설정
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            # 쿼리 구성
            date_query = f"submittedDate:[{start_date.strftime('%Y%m%d')}0000 TO {end_date.strftime('%Y%m%d')}2359]"

            if category:
                query = f"cat:{category} AND {date_query}"
            else:
                query = date_query

            return self.search(query, max_results, sort_by="submittedDate")

        except Exception as e:
            logger.warning("arXiv recent papers search failed: %s", e)
            return []

    def _extract_paper_info(self, result: arxiv.Result) -> Dict[str, Any]:
        """arXiv 결과에서 논문 정보 추출"""
        try:
            return {
                "title": result.title,
                "authors": [author.name for author in result.authors],
                "abstract": result.summary,
                "url": result.entry_id,
                "pdf_url": result.pdf_url,
                "published_date": result.published.strftime('%Y-%m-%d') if result.published else "",
                "updated_date": result.updated.strftime('%Y-%m-%d') if result.updated else "",
                "source": "arXiv",
                "arxiv_id": result.get_short_id(),
                "categories": result.categories,
                "doi": result.doi if hasattr(result, 'doi') else "",
                "comment": result.comment if hasattr(result, 'comment') else "",
                "journal_ref": result.journal_ref if hasattr(result, 'journal_ref') else ""
            }
        except Exception as e:
            logger.debug("Error extracting arXiv paper info, using fallback: %s", e)
            return {
                "title": str(result.title) if result.title else "",
                "authors": [],
                "abstract": str(result.summary) if result.summary else "",
                "url": str(result.entry_id) if result.entry_id else "",
                "pdf_url": str(result.pdf_url) if result.pdf_url else "",
                "published_date": "",
                "updated_date": "",
                "source": "arXiv",
                "arxiv_id": "",
                "categories": [],
                "doi": "",
                "comment": "",
                "journal_ref": ""
            }

    def get_categories(self) -> List[Dict[str, str]]:
        """사용 가능한 카테고리 목록 반환"""
        return [
            {"code": "cs.AI", "name": "Artificial Intelligence"},
            {"code": "cs.LG", "name": "Machine Learning"},
            {"code": "cs.CV", "name": "Computer Vision"},
            {"code": "cs.NLP", "name": "Natural Language Processing"},
            {"code": "cs.CL", "name": "Computation and Language"},
            {"code": "cs.IR", "name": "Information Retrieval"},
            {"code": "cs.DL", "name": "Digital Libraries"},
            {"code": "cs.HC", "name": "Human-Computer Interaction"},
            {"code": "cs.CY", "name": "Computers and Society"},
            {"code": "cs.CR", "name": "Cryptography and Security"},
            {"code": "cs.DS", "name": "Data Structures and Algorithms"},
            {"code": "cs.DB", "name": "Databases"},
            {"code": "cs.DC", "name": "Distributed, Parallel, and Cluster Computing"},
            {"code": "cs.GL", "name": "General Literature"},
            {"code": "cs.GR", "name": "Graphics"},
            {"code": "cs.AR", "name": "Hardware Architecture"},
            {"code": "cs.LO", "name": "Logic in Computer Science"},
            {"code": "cs.MS", "name": "Mathematical Software"},
            {"code": "cs.MA", "name": "Multiagent Systems"},
            {"code": "cs.MM", "name": "Multimedia"},
            {"code": "cs.NI", "name": "Networking and Internet Architecture"},
            {"code": "cs.NE", "name": "Neural and Evolutionary Computing"},
            {"code": "cs.NA", "name": "Numerical Analysis"},
            {"code": "cs.OS", "name": "Operating Systems"},
            {"code": "cs.OH", "name": "Other Computer Science"},
            {"code": "cs.PF", "name": "Performance"},
            {"code": "cs.PL", "name": "Programming Languages"},
            {"code": "cs.RO", "name": "Robotics"},
            {"code": "cs.SE", "name": "Software Engineering"},
            {"code": "cs.SD", "name": "Sound"},
            {"code": "cs.SC", "name": "Symbolic Computation"},
            {"code": "cs.SY", "name": "Systems and Control"},
            {"code": "stat.ML", "name": "Machine Learning (Statistics)"},
            {"code": "stat.AP", "name": "Applications"},
            {"code": "stat.CO", "name": "Computation"},
            {"code": "stat.ME", "name": "Methodology"},
            {"code": "stat.OT", "name": "Other Statistics"},
            {"code": "stat.TH", "name": "Statistics Theory"}
        ]
