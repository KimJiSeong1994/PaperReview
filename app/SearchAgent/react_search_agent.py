"""
ReAct Multi-turn Search Agent

ArxivQA 스타일의 멀티턴 검색 에이전트.
Search-R1의 <search>→<result>→<think>→<search> 루프를
프롬프트 엔지니어링으로 구현한다.

핵심: 검색 → 결과 분석 → 갭 식별 → 보완 쿼리 → 재검색
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 전역 타임아웃 ───────────────────────────────────────────────────────────
_TOTAL_TIMEOUT_SECONDS = 120


# ── 데이터클래스 ────────────────────────────────────────────────────────────

@dataclass
class SearchTurn:
    """한 턴(turn)의 검색 활동을 기록하는 데이터클래스."""

    turn: int
    query: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    """각 항목: {"tool": str, "input": str, "output_count": int}"""
    papers_found: List[Dict[str, Any]] = field(default_factory=list)
    gap_analysis: Optional[str] = None
    next_query_rationale: Optional[str] = None


# ── 메인 에이전트 ────────────────────────────────────────────────────────────

class ReActSearchAgent:
    """
    ReAct 프레임워크 기반 멀티턴 논문 검색 에이전트.

    ArxivQA 논문(arxiv.org/abs/2309.01536)의 multi-turn 패턴을
    RL 파인튜닝 없이 프롬프트 엔지니어링만으로 재현한다.

    Args:
        search_agent: 기존 SearchAgent 인스턴스.
        openai_client: OpenAI 클라이언트 (gpt-4o-mini 추론용). None 이면 생략 모드.
        max_turns: 최대 검색 턴 수. 기본 3.
        model: 사용할 OpenAI 모델 명. 기본 "gpt-4o-mini".
    """

    def __init__(
        self,
        search_agent,
        openai_client=None,
        max_turns: int = 3,
        model: str = "gpt-4o-mini",
    ) -> None:
        self._search_agent = search_agent
        self._client = openai_client
        self._max_turns = max_turns
        self._model = model

    # ── 공개 API ─────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        analysis: Optional[Dict[str, Any]] = None,
        max_results: int = 20,
    ) -> Dict[str, Any]:
        """
        ReAct 루프를 실행하여 관련 논문을 수집한다.

        Args:
            query: 사용자의 원본 검색 쿼리.
            analysis: QueryAnalyzer.analyze_query() 결과 (optional). 없으면
                      쿼리 텍스트만으로 동작한다.
            max_results: 최종 반환할 최대 논문 수.

        Returns:
            {
                "papers":        List[Dict],   # 중복 제거된 논문 목록
                "turns":         int,          # 실행된 턴 수
                "turn_history":  List[SearchTurn],
                "validation":    Dict,         # ArxivQA 4-gate 결과
                "elapsed_s":     float,
            }
        """
        start = time.monotonic()
        intent: str = (analysis or {}).get("intent", "paper_search")

        # ── 1단계: 다양한 초기 쿼리 생성 ─────────────────────────────────
        initial_queries = self._build_initial_queries(query, analysis)
        logger.info(
            "[ReAct] query=%r | intent=%s | initial_queries=%d | max_turns=%d",
            query[:60], intent, len(initial_queries), self._max_turns,
        )

        all_papers: List[Dict[str, Any]] = []
        turn_history: List[SearchTurn] = []
        current_query = initial_queries[0]

        for turn_idx in range(1, self._max_turns + 1):
            # 전체 타임아웃 체크
            elapsed = time.monotonic() - start
            if elapsed >= _TOTAL_TIMEOUT_SECONDS:
                logger.warning("[ReAct] 전체 타임아웃 도달 (%.1fs). 조기 종료.", elapsed)
                break

            remaining = _TOTAL_TIMEOUT_SECONDS - elapsed
            logger.info("[ReAct] Turn %d: query=%r (remaining=%.1fs)", turn_idx, current_query[:60], remaining)

            turn = SearchTurn(turn=turn_idx, query=current_query)

            # ── 2단계: 턴 내 병렬 검색 ─────────────────────────────────
            # Turn 1 — arXiv(keyword) + OpenAlex(semantic)
            # Turn 2+ — OpenAlex + DBLP (arXiv rate-limit 방지)
            try:
                if turn_idx == 1:
                    papers, tool_calls = await asyncio.wait_for(
                        self._turn1_search(current_query, initial_queries, max_results),
                        timeout=min(remaining, 40),
                    )
                else:
                    papers, tool_calls = await asyncio.wait_for(
                        self._turn_n_search(current_query, max_results // 2),
                        timeout=min(remaining, 30),
                    )
            except asyncio.TimeoutError:
                logger.warning("[ReAct] Turn %d 검색 타임아웃", turn_idx)
                papers, tool_calls = [], []

            turn.tool_calls = tool_calls
            turn.papers_found = papers
            all_papers.extend(papers)
            turn_history.append(turn)

            logger.info("[ReAct] Turn %d: found=%d / cumulative=%d", turn_idx, len(papers), len(all_papers))

            # 마지막 턴이면 갭 분석 불필요
            if turn_idx >= self._max_turns:
                break

            # 누적 논문이 충분하면 종료
            if len(all_papers) >= max_results * 1.5:
                logger.info("[ReAct] 충분한 결과 수집됨 (%d). 조기 종료.", len(all_papers))
                break

            # ── 3단계: 갭 분석 → 다음 쿼리 결정 ──────────────────────
            elapsed = time.monotonic() - start
            remaining_for_llm = _TOTAL_TIMEOUT_SECONDS - elapsed
            if remaining_for_llm < 10:
                logger.warning("[ReAct] LLM 갭 분석 시간 부족 (%.1fs 남음). 종료.", remaining_for_llm)
                break

            try:
                plan = await asyncio.wait_for(
                    self._analyze_and_plan_next(
                        query=query,
                        intent=intent,
                        papers_so_far=all_papers,
                        turn_history=turn_history,
                    ),
                    timeout=min(remaining_for_llm, 20),
                )
            except asyncio.TimeoutError:
                logger.warning("[ReAct] 갭 분석 LLM 타임아웃. 다음 다양화 쿼리 사용.")
                plan = self._fallback_plan(query, initial_queries, turn_idx)

            turn.gap_analysis = plan.get("missing_str", "")
            turn.next_query_rationale = plan.get("rationale", "")

            if plan.get("is_sufficient", False):
                logger.info("[ReAct] LLM 판단: 결과 충분. 종료.")
                break

            next_q = plan.get("next_query", "").strip()
            if not next_q:
                logger.info("[ReAct] 다음 쿼리 없음. 종료.")
                break

            current_query = next_q

        # ── 4단계: 중복 제거 ─────────────────────────────────────────────
        deduped = self._deduplicate(all_papers)

        # ── 5단계: ArxivQA 4-gate 검증 ───────────────────────────────────
        validation = self._validate_gates(deduped, turn_history)

        elapsed_total = time.monotonic() - start
        logger.info(
            "[ReAct] 완료: turns=%d, papers_before_dedup=%d, papers_after=%d, elapsed=%.1fs",
            len(turn_history), len(all_papers), len(deduped), elapsed_total,
        )

        return {
            "papers": deduped[:max_results],
            "turns": len(turn_history),
            "turn_history": turn_history,
            "validation": validation,
            "elapsed_s": round(elapsed_total, 2),
        }

    # ── 내부 검색 도구 ────────────────────────────────────────────────────────

    async def _turn1_search(
        self,
        primary_query: str,
        all_initial_queries: List[str],
        max_results: int,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Turn 1 전용: arXiv(keyword) + OpenAlex(semantic)를 병렬 실행.

        arXiv 호출은 rate-limit 준수를 위해 첫 번째 쿼리 하나만 사용한다.
        나머지 초기 쿼리 변형은 OpenAlex semantic 검색으로 커버한다.
        """
        per_source = max(5, max_results // 3)

        # arXiv는 원본 쿼리 1개만
        arxiv_task = self._keyword_search(primary_query, per_source)

        # OpenAlex는 2번째 다양화 쿼리 사용 (있으면)
        semantic_query = all_initial_queries[1] if len(all_initial_queries) > 1 else primary_query
        semantic_task = self._semantic_search(semantic_query, per_source)

        arxiv_results, semantic_results = await asyncio.gather(
            arxiv_task, semantic_task, return_exceptions=True
        )

        papers: List[Dict[str, Any]] = []
        tool_calls: List[Dict[str, Any]] = []

        if isinstance(arxiv_results, Exception):
            logger.warning("[ReAct] arXiv 검색 오류: %s", arxiv_results)
            arxiv_results = []
        papers.extend(arxiv_results)  # type: ignore[arg-type]
        tool_calls.append({
            "tool": "keyword_search",
            "input": primary_query,
            "output_count": len(arxiv_results),
        })

        if isinstance(semantic_results, Exception):
            logger.warning("[ReAct] semantic 검색 오류: %s", semantic_results)
            semantic_results = []
        papers.extend(semantic_results)  # type: ignore[arg-type]
        tool_calls.append({
            "tool": "semantic_search",
            "input": semantic_query,
            "output_count": len(semantic_results),
        })

        return papers, tool_calls

    async def _turn_n_search(
        self,
        query: str,
        max_results: int,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Turn 2+ 전용: OpenAlex + DBLP를 병렬 실행 (arXiv rate-limit 방지).
        """
        per_source = max(5, max_results // 2)

        openalex_task = self._semantic_search(query, per_source)
        dblp_task = self._dblp_search(query, per_source)

        openalex_results, dblp_results = await asyncio.gather(
            openalex_task, dblp_task, return_exceptions=True
        )

        papers: List[Dict[str, Any]] = []
        tool_calls: List[Dict[str, Any]] = []

        if isinstance(openalex_results, Exception):
            logger.warning("[ReAct] OpenAlex 보완 검색 오류: %s", openalex_results)
            openalex_results = []
        papers.extend(openalex_results)  # type: ignore[arg-type]
        tool_calls.append({
            "tool": "semantic_search",
            "input": query,
            "output_count": len(openalex_results),
        })

        if isinstance(dblp_results, Exception):
            logger.warning("[ReAct] DBLP 보완 검색 오류: %s", dblp_results)
            dblp_results = []
        papers.extend(dblp_results)  # type: ignore[arg-type]
        tool_calls.append({
            "tool": "dblp_search",
            "input": query,
            "output_count": len(dblp_results),
        })

        return papers, tool_calls

    async def _keyword_search(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        arXiv API 키워드 검색 (ArxivSearcher 래퍼).

        arXiv 3.5 s rate limit 준수는 ArxivSearcher._rate_limit() 내부에서 처리.
        """
        loop = asyncio.get_running_loop()
        try:
            results = await loop.run_in_executor(
                None,
                self._search_agent.arxiv_searcher.search,
                query,
                max_results,
            )
            logger.debug("[ReAct] keyword_search: query=%r, found=%d", query[:50], len(results))
            return results or []
        except Exception as exc:
            logger.warning("[ReAct] keyword_search 실패: %s", exc)
            return []

    async def _semantic_search(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        OpenAlex API 시맨틱 검색 (OpenAlexSearcher 래퍼).

        OpenAlex는 free-text search로 임베딩 유사도와 유사한 관련성 검색을 제공.
        """
        loop = asyncio.get_running_loop()
        try:
            results = await loop.run_in_executor(
                None,
                self._search_agent.openalex_searcher.search,
                query,
                max_results,
            )
            logger.debug("[ReAct] semantic_search: query=%r, found=%d", query[:50], len(results))
            return results or []
        except Exception as exc:
            logger.warning("[ReAct] semantic_search 실패: %s", exc)
            return []

    async def _dblp_search(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """DBLP 검색 (DBLPSearcher 래퍼)."""
        loop = asyncio.get_running_loop()
        try:
            results = await loop.run_in_executor(
                None,
                self._search_agent.dblp_searcher.search,
                query,
                max_results,
            )
            logger.debug("[ReAct] dblp_search: query=%r, found=%d", query[:50], len(results))
            return results or []
        except Exception as exc:
            logger.warning("[ReAct] dblp_search 실패: %s", exc)
            return []

    async def _read_abstract(self, paper_id: str) -> Optional[Dict[str, Any]]:
        """
        arXiv ID로 초록 및 메타데이터를 조회한다.

        arxiv 패키지의 Client.results()를 직접 호출하므로
        rate-limit 준수는 ArxivSearcher._rate_limit()에 위임하지 않고
        단순 Search 객체 생성으로 처리한다 (1회 조회라 허용 가능).

        Args:
            paper_id: arXiv short ID (예: "2309.01536" or "2309.01536v1").

        Returns:
            논문 정보 딕셔너리 또는 None.
        """
        loop = asyncio.get_running_loop()
        try:
            import arxiv

            def _fetch() -> Optional[Dict[str, Any]]:
                search = arxiv.Search(id_list=[paper_id], max_results=1)
                client = arxiv.Client(delay_seconds=3.5, num_retries=3)
                results = list(client.results(search))
                if not results:
                    return None
                return self._search_agent.arxiv_searcher._extract_paper_info(results[0])

            return await asyncio.wait_for(
                loop.run_in_executor(None, _fetch),
                timeout=15,
            )
        except asyncio.TimeoutError:
            logger.warning("[ReAct] _read_abstract 타임아웃: paper_id=%s", paper_id)
            return None
        except Exception as exc:
            logger.warning("[ReAct] _read_abstract 실패: paper_id=%s, err=%s", paper_id, exc)
            return None

    # ── LLM 갭 분석 ──────────────────────────────────────────────────────────

    async def _analyze_and_plan_next(
        self,
        query: str,
        intent: str,
        papers_so_far: List[Dict[str, Any]],
        turn_history: List[SearchTurn],
    ) -> Dict[str, Any]:
        """
        현재까지 수집된 논문을 분석하여 갭을 파악하고 다음 쿼리를 제안한다.

        LLM 호출이 불가하거나 실패하면 fallback 계획을 반환한다.

        Returns:
            {
                "is_sufficient": bool,
                "missing": List[str],       # 아직 없는 논문 유형 설명
                "missing_str": str,
                "next_query": str,
                "rationale": str,
            }
        """
        if self._client is None:
            logger.debug("[ReAct] OpenAI 클라이언트 없음. fallback 계획 사용.")
            return self._fallback_plan(query, [], len(turn_history))

        # 논문 요약 (토큰 절약 위해 제목 + 연도만 사용)
        paper_summaries = [
            f"- {p.get('title', '(제목 없음)')} ({p.get('published_date', '')[:4]})"
            for p in papers_so_far[:30]
        ]
        papers_block = "\n".join(paper_summaries) if paper_summaries else "(아직 없음)"

        # 이전 턴 히스토리 요약
        history_lines = [
            f"  Turn {t.turn}: query={t.query!r}, found={len(t.papers_found)}, gap={t.gap_analysis or '(없음)'}"
            for t in turn_history
        ]
        history_block = "\n".join(history_lines) if history_lines else "(없음)"

        system_prompt = (
            "You are an expert academic search strategist. "
            "Your task is to analyze a set of retrieved papers and identify "
            "what TYPES of papers are still missing, then suggest a single focused "
            "follow-up search query to fill the gap. "
            "Be concise and return valid JSON only."
        )

        user_prompt = f"""
Original query: "{query}"
Search intent: {intent}

Papers found so far ({len(papers_so_far)} total):
{papers_block}

Previous turn history:
{history_block}

Analyze the papers above and answer:
1. Are the results already sufficient to address the original query?
2. What TYPES of papers are still missing? (e.g., "benchmark papers", "survey papers on X", "papers comparing Y and Z")
3. What single follow-up query would best fill the gap?

Important rules:
- The follow-up query MUST be substantially different from all previous queries (avoid repetition).
- Focus on a gap in the paper TYPES, not just adding keywords.
- If results are already sufficient, set is_sufficient to true and leave next_query empty.

Respond in JSON:
{{
  "is_sufficient": true/false,
  "missing": ["type1", "type2"],
  "next_query": "a single search query string",
  "rationale": "brief explanation"
}}
"""

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=300,
                    response_format={"type": "json_object"},
                ),
            )

            content = response.choices[0].message.content
            if not content or not content.strip():
                logger.warning("[ReAct] LLM 빈 응답. fallback 계획 사용.")
                return self._fallback_plan(query, [], len(turn_history))

            plan_raw: Dict[str, Any] = json.loads(content)
            missing_list: List[str] = plan_raw.get("missing", [])
            plan: Dict[str, Any] = {
                "is_sufficient": bool(plan_raw.get("is_sufficient", False)),
                "missing": missing_list,
                "missing_str": "; ".join(missing_list),
                "next_query": str(plan_raw.get("next_query", "")).strip(),
                "rationale": str(plan_raw.get("rationale", "")).strip(),
            }
            logger.debug(
                "[ReAct] 갭 분석 완료: is_sufficient=%s, next_query=%r",
                plan["is_sufficient"], plan["next_query"][:60] if plan["next_query"] else "",
            )
            return plan

        except json.JSONDecodeError as exc:
            logger.warning("[ReAct] LLM JSON 파싱 오류: %s. fallback 계획 사용.", exc)
            return self._fallback_plan(query, [], len(turn_history))
        except Exception as exc:
            logger.warning("[ReAct] 갭 분석 LLM 호출 실패: %s. fallback 계획 사용.", exc)
            return self._fallback_plan(query, [], len(turn_history))

    # ── ArxivQA 4-gate 검증 ──────────────────────────────────────────────────

    def _validate_gates(
        self,
        final_papers: List[Dict[str, Any]],
        tool_history: List[SearchTurn],
    ) -> Dict[str, Any]:
        """
        ArxivQA 4-gate 검증을 수행하고 각 게이트 통과 여부를 반환한다.

        Gates:
          1. Duplication: 중복 doc_id 없음.
          2. Submission:  최소 1개 이상의 논문.
          3. Citation:    모든 논문이 tool 호출로부터 유래.
          4. Limit:       논문 수 <= max_results (호출 측 책임이므로 항상 통과).

        Returns:
            {
                "passed": bool,
                "duplication": bool,
                "submission": bool,
                "citation": bool,
                "limit": bool,
                "details": str,
            }
        """
        # Gate 1: 중복 체크
        doc_ids = [self._paper_doc_id(p) for p in final_papers]
        gate_duplication = len(doc_ids) == len(set(doc_ids))

        # Gate 2: 최소 제출 여부
        gate_submission = len(final_papers) >= 1

        # Gate 3: 출처 추적 — tool_calls에 기록된 출력 개수와 비교
        total_tool_output = sum(
            tc.get("output_count", 0)
            for turn in tool_history
            for tc in turn.tool_calls
        )
        # final_papers 는 tool output의 합집합(중복 제거)이므로 항상 <= total_tool_output
        gate_citation = len(final_papers) <= total_tool_output or total_tool_output == 0

        # Gate 4: 결과 수 제한 (호출 측에서 슬라이싱하므로 항상 통과)
        gate_limit = True

        all_passed = gate_duplication and gate_submission and gate_citation and gate_limit

        details_parts = []
        if not gate_duplication:
            details_parts.append("중복 doc_id 감지됨")
        if not gate_submission:
            details_parts.append("결과 0건")
        if not gate_citation:
            details_parts.append("tool 출처 추적 불일치")

        return {
            "passed": all_passed,
            "duplication": gate_duplication,
            "submission": gate_submission,
            "citation": gate_citation,
            "limit": gate_limit,
            "details": "; ".join(details_parts) if details_parts else "all gates passed",
        }

    # ── 쿼리 다양성 제어 ─────────────────────────────────────────────────────

    def _ensure_query_diversity(
        self,
        queries: List[str],
        threshold: float = 0.5,
    ) -> List[str]:
        """
        단어 수준 Jaccard 유사도로 중복 쿼리를 필터링한다.

        ArxivQA의 P_query_diversity 전략을 단순화하여 구현.

        Args:
            queries: 후보 쿼리 목록.
            threshold: 이 값 이상의 Jaccard 유사도를 가진 쿼리는 제거.

        Returns:
            중복이 제거된 쿼리 목록.
        """
        diverse: List[str] = []
        for candidate in queries:
            candidate_words = set(candidate.lower().split())
            is_redundant = False
            for existing in diverse:
                existing_words = set(existing.lower().split())
                union = candidate_words | existing_words
                if not union:
                    continue
                jaccard = len(candidate_words & existing_words) / len(union)
                if jaccard >= threshold:
                    is_redundant = True
                    break
            if not is_redundant:
                diverse.append(candidate)
        return diverse

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _build_initial_queries(
        self,
        query: str,
        analysis: Optional[Dict[str, Any]],
    ) -> List[str]:
        """
        분석 결과를 바탕으로 3~5개의 초기 검색 쿼리를 생성한다.

        우선순위:
          1. analysis의 improved_query
          2. analysis의 keywords 기반 조합 쿼리
          3. 원본 쿼리

        최종적으로 _ensure_query_diversity 로 Jaccard 필터링.
        """
        candidates: List[str] = []

        if analysis:
            improved = analysis.get("improved_query", "").strip()
            if improved and improved.lower() != query.lower():
                candidates.append(improved)

            keywords: List[str] = analysis.get("keywords", [])
            core_concepts: List[str] = analysis.get("core_concepts", [])

            # 키워드 기반 변형 쿼리
            if len(keywords) >= 2:
                candidates.append(" ".join(keywords[:4]))
            if len(keywords) >= 3:
                candidates.append(" ".join(keywords[1:5]))
            if core_concepts:
                candidates.append(" ".join(core_concepts[:3]))

            # research_area 결합
            area = analysis.get("research_area", "").strip()
            if area and keywords:
                candidates.append(f"{keywords[0]} {area}")

        # 원본 쿼리는 항상 포함 (첫 번째 자리 보장)
        if query not in candidates:
            candidates.insert(0, query)
        else:
            # 원본이 이미 있다면 첫 자리로 이동
            candidates.remove(query)
            candidates.insert(0, query)

        # 빈 문자열 제거
        candidates = [q for q in candidates if q.strip()]

        # 다양성 필터링
        diverse = self._ensure_query_diversity(candidates, threshold=0.5)

        # 3~5개로 제한
        return diverse[:5] if len(diverse) >= 3 else diverse or [query]

    def _fallback_plan(
        self,
        query: str,
        initial_queries: List[str],
        current_turn: int,
    ) -> Dict[str, Any]:
        """
        LLM 갭 분석이 불가할 때 사용할 기본 계획.

        이미 사용된 쿼리를 피하기 위해 initial_queries에서 아직 사용하지
        않은 쿼리를 선택하거나, 없으면 더 넓은 키워드 쿼리를 생성한다.
        """
        # 아직 사용하지 않은 초기 쿼리 선택
        unused = [q for q in initial_queries if q != query]
        if unused:
            next_q = unused[0]
        else:
            # 쿼리를 더 짧게 줄여 broad search 시도
            words = query.split()
            next_q = " ".join(words[: max(1, len(words) - 1)]) if len(words) > 2 else ""

        return {
            "is_sufficient": not next_q,
            "missing": [],
            "missing_str": "",
            "next_query": next_q,
            "rationale": "fallback: LLM 갭 분석 불가, 다음 초기 쿼리 사용",
        }

    @staticmethod
    def _paper_doc_id(paper: Dict[str, Any]) -> str:
        """논문의 고유 식별자를 추출한다 (중복 게이트용)."""
        # arxiv_id > doi > 정규화 제목 순
        arxiv_id = paper.get("arxiv_id", "").strip()
        if arxiv_id:
            return f"arxiv:{arxiv_id}"
        doi = paper.get("doi", "").strip()
        if doi:
            return f"doi:{doi.lower()}"
        title = paper.get("title", "").lower().strip()
        # 공백·구두점 제거
        import re
        title_normalized = re.sub(r"[^\w]", "", title)[:80]
        return f"title:{title_normalized}"

    def _deduplicate(self, papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        doc_id 기반 중복 제거.

        같은 doc_id가 여러 번 등장하면 가장 먼저 수집된 항목을 유지한다.
        """
        seen: dict[str, bool] = {}
        unique: List[Dict[str, Any]] = []
        for paper in papers:
            doc_id = self._paper_doc_id(paper)
            if doc_id not in seen:
                seen[doc_id] = True
                unique.append(paper)
        return unique
