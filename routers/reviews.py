"""
Deep review endpoints:
  POST /api/deep-review
  GET  /api/deep-review/status/{session_id}
  GET  /api/deep-review/report/{session_id}
  POST /api/deep-review/visualize/{session_id}
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from starlette.requests import Request

from .deps import limiter, review_sessions, review_sessions_lock, get_optional_user, get_openai_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["reviews"])

# ── Cache-stable system prompts ────────────────────────────────────────
# Kept as module-level immutable strings so OpenAI automatic prompt caching
# (and the local split-key cache) can reuse them across calls. Do not
# interpolate runtime values (paper count, dates, titles) into these
# constants — those belong in the user message.

FAST_REVIEW_SYSTEM_PROMPT = (
    "당신은 Nature, Science 등 최상위 저널의 리뷰어이자, "
    "해당 분야에서 20년 이상 핵심 연구를 수행해온 석학 교수입니다. "
    "단순한 논문 요약이 아닌, 비판적 사고와 학제간 통찰을 바탕으로 "
    "논문의 본질적 기여와 한계를 꿰뚫는 심층 분석을 수행합니다. "
    "모든 주장에는 구체적 근거를 제시하고, 숨겨진 가정과 잠재적 한계까지 도출합니다. "
    "체계적이고 상세한 한글 문헌 리뷰 보고서를 작성합니다."
)

DEEP_REVIEW_SYSTEM_PROMPT = (
    "당신은 해당 분야의 선임 연구 교수입니다. "
    "체계적이고 심층적인 한글 문헌 리뷰 보고서를 작성합니다."
)

_SESSION_TTL_SECONDS = 86400  # 24 hours
_last_cleanup = 0.0

def _cleanup_expired_sessions():
    """Remove review sessions older than 24 hours."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < 600:  # Only run every 10 minutes
        return
    _last_cleanup = now
    expired = []
    with review_sessions_lock:
        for sid, session in review_sessions.items():
            created = session.get("created_at", "")
            if created:
                try:
                    created_dt = datetime.fromisoformat(created)
                    age = (datetime.now() - created_dt).total_seconds()
                    if age > _SESSION_TTL_SECONDS:
                        expired.append(sid)
                except (ValueError, TypeError):
                    pass
        for sid in expired:
            del review_sessions[sid]
    if expired:
        logger.info("Cleaned up %d expired review sessions", len(expired))


# ── Pydantic models ───────────────────────────────────────────────────

class DeepReviewRequest(BaseModel):
    paper_ids: List[str]
    papers: Optional[List[Dict[str, Any]]] = None
    num_researchers: Optional[int] = 3
    model: Optional[str] = "gpt-4.1"
    fast_mode: Optional[bool] = True


class VerificationStats(BaseModel):
    total_claims: int = 0
    verifiable_claims: int = 0
    verified: int = 0
    partially_verified: int = 0
    unverified: int = 0
    contradicted: int = 0
    verification_rate: float = 0.0


class ReviewStatusResponse(BaseModel):
    session_id: str
    status: str
    progress: Optional[str] = None
    report_available: bool = False
    error: Optional[str] = None
    verification_stats: Optional[VerificationStats] = None


# ── Helper functions ───────────────────────────────────────────────────

def _enrich_papers_with_abstracts(papers_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fetch abstracts from arXiv for papers that lack them (batch mode)."""
    try:
        import arxiv
    except ImportError:
        logger.warning("arxiv package not available for abstract enrichment")
        return papers_data

    # Collect papers needing enrichment
    needs_abstract: Dict[str, int] = {}  # clean_arxiv_id -> index in enriched
    enriched = [dict(p) for p in papers_data]  # shallow copy all

    for i, paper in enumerate(enriched):
        if not (paper.get("abstract") or paper.get("summary")):
            aid = paper.get("arxiv_id")
            if aid:
                clean_id = aid.split("/")[-1] if "/" in aid else aid
                clean_id = clean_id.split("v")[0]  # Remove version suffix
                needs_abstract[clean_id] = i

    if not needs_abstract:
        return enriched

    logger.info("Fetching %d arXiv abstracts in batch...", len(needs_abstract))

    try:
        client = arxiv.Client(page_size=100, delay_seconds=3.5, num_retries=3)
        search = arxiv.Search(id_list=list(needs_abstract.keys()))

        for result in client.results(search):
            # Match result back to paper
            result_id = result.entry_id.split("/abs/")[-1].split("v")[0] if result.entry_id else ""
            if not result_id:
                result_id = result.get_short_id().split("v")[0] if hasattr(result, "get_short_id") else ""

            idx = needs_abstract.get(result_id)
            if idx is not None:
                enriched[idx]["abstract"] = result.summary
                if not enriched[idx].get("categories") and result.categories:
                    enriched[idx]["categories"] = list(result.categories)
                if result.pdf_url:
                    enriched[idx]["pdf_url"] = result.pdf_url
                logger.info("Enriched: %s", enriched[idx].get("title", "?")[:60])
    except Exception as e:
        logger.warning("Batch arXiv abstract fetch failed: %s", e)

    return enriched


def run_fast_review(
    session_id: str,
    paper_ids: List[str],
    model: str,
    workspace: Any,
    papers_data: Optional[List[Dict[str, Any]]] = None,
) -> dict:
    """
    Fast Mode: single LLM call to quickly analyse all papers.
    5-10x faster than Deep Mode.
    """
    from app.DeepAgent.tools.paper_loader import load_papers_from_ids

    logger.info("[Fast Review] Starting: %s papers", len(paper_ids))

    if papers_data and len(papers_data) > 0:
        papers = papers_data
        logger.info("[Fast Review] %s papers (from frontend)", len(papers))
    else:
        papers = load_papers_from_ids(paper_ids)
        logger.info("[Fast Review] %s papers loaded (ID search)", len(papers))

    if not papers:
        return {"status": "failed", "error": "Cannot load papers"}

    deep_research_model = "gpt-4.1"
    logger.info("[Fast Review] Deep Research model: %s", deep_research_model)
    client = get_openai_client()

    papers_text = []
    for i, paper in enumerate(papers, 1):
        title = paper.get("title", f"Paper {i}") or f"Paper {i}"
        abstract = paper.get("abstract") or paper.get("summary") or "No abstract"
        authors = paper.get("authors", [])
        year = paper.get("year") or paper.get("published") or "N/A"

        if authors:
            if isinstance(authors[0], dict):
                author_names = [a.get("name", str(a)) for a in authors[:5]]
            else:
                author_names = [str(a) for a in authors[:5]]
            author_str = ", ".join(author_names)
            if len(authors) > 5:
                author_str += f" et al. ({len(authors) - 5} more)"
        else:
            author_str = "Unknown"

        if not isinstance(abstract, str):
            abstract = str(abstract) if abstract else "No abstract"

        categories = paper.get("categories", [])
        keywords = paper.get("keywords", [])
        citations = paper.get("citations")
        doi = paper.get("doi", "")
        url = paper.get("url", "") or paper.get("pdf_url", "")
        venue = paper.get("venue") or paper.get("journal") or paper.get("journal_ref", "")
        full_text = paper.get("full_text", "")

        cat_str = ", ".join(categories[:5]) if categories else ""
        kw_str = ", ".join(keywords[:8]) if keywords else ""

        paper_entry = f"""
### Paper {i}: {title}
- **Authors**: {author_str}
- **Published**: {year}"""

        if venue:
            paper_entry += f"\n- **Venue**: {venue}"
        if cat_str:
            paper_entry += f"\n- **Categories**: {cat_str}"
        if kw_str:
            paper_entry += f"\n- **Keywords**: {kw_str}"
        if citations is not None and citations > 0:
            paper_entry += f"\n- **Citations**: {citations}"
        if doi:
            paper_entry += f"\n- **DOI**: {doi}"
        if url:
            paper_entry += f"\n- **URL**: {url}"

        paper_entry += f"\n- **Abstract**: {abstract[:3000]}"

        if full_text and len(full_text) > 500:
            paper_entry += f"\n- **Full text excerpt**: {full_text[:5000]}"

        papers_text.append(paper_entry)

    combined_papers = "\n".join(papers_text)

    prompt = f"""당신은 Nature, Science 등 최상위 저널의 리뷰어이자, 해당 분야에서 20년 이상 핵심 연구를 수행해온 석학 교수입니다.
다음 {len(papers)}편의 논문을 단순히 요약하는 것이 아니라, **비판적으로 분석하고 학술적 통찰을 도출**하여
박사과정 학생 및 연구자들이 연구 방향 설정에 직접 활용할 수 있는 수준의 심층 문헌 고찰 보고서를 작성해주세요.

**분석 철학**:
- 표면적 요약이 아닌, 각 논문의 **핵심 아이디어의 본질**을 꿰뚫는 분석
- "무엇을 했는가"보다 "왜 이 접근이 효과적인가/비효과적인가"에 초점
- 논문들을 종합했을 때 비로소 보이는 **메타 수준의 패턴과 통찰** 도출
- 모호한 표현("~할 수 있다", "중요하다") 대신 **구체적 근거와 논리적 추론** 사용

## 분석 대상 논문들:
{combined_papers}

---

## 분석 품질 기준 (반드시 준수)

1. 모든 주장에는 **논문의 구체적 내용을 근거**로 제시할 것
2. "일반적으로", "보통" 같은 일반론 사용 금지 - **해당 논문만의 고유한 분석**만 작성
3. 방법론 설명 시 **알고리즘의 핵심 작동 원리**를 기술적으로 서술할 것
4. 실험 결과는 반드시 **수치 데이터**와 함께 제시할 것
5. 한계점 분석 시 저자가 명시하지 않은 **숨겨진 가정과 잠재적 문제**도 도출할 것
6. 각 논문 분석은 **최소 800자 이상** 깊이 있게 작성할 것

---

# 체계적 문헌 고찰: 선정 연구 논문의 심층 분석

---

**리뷰 날짜**: {datetime.now().strftime('%Y년 %m월 %d일')}
**분석 논문 수**: {len(papers)}편
**리뷰 방법론**: AI 기반 심층 연구 분석 시스템 (비판적 분석 프레임워크)

---

## 초록 (Abstract)

[400-600자로 작성. 단순 요약이 아닌 분석적 초록:]
- 분석 대상 논문들이 다루는 **공통 연구 질문**과 그 학술적 중요성
- 각 논문이 이 질문에 대해 제시하는 **서로 다른 접근법**과 그 차이의 본질
- 논문들을 종합했을 때 드러나는 **핵심 연구 트렌드와 패러다임 전환**
- 본 리뷰가 해당 분야 연구자에게 제공하는 **고유한 학술적 가치**

**키워드**: [논문들의 핵심 개념을 관통하는 키워드 7-10개]

---

## 1. 서론

### 1.1 연구 배경 및 학술적 맥락
[500자 이상. 깊이 있는 맥락 분석:]
- 이 연구 분야가 현재 직면한 **근본적인 도전과 미해결 문제**
- 최근 5년간 이 분야에서 일어난 **패러다임 변화**와 그 동인
- 분석 대상 논문들이 이 큰 그림 속에서 차지하는 **위치와 의미**
- 기존 연구의 한계 중 이 논문들이 구체적으로 **어떤 간극을 메우고 있는지**

### 1.2 본 리뷰의 목적과 차별점
[단순 요약을 넘어서는 본 리뷰의 고유 가치를 4-5가지로 서술]

### 1.3 분석 프레임워크
| 분석 차원 | 핵심 질문 | 평가 관점 |
|-----------|----------|----------|
| 문제 정의 | 이 문제가 왜 중요하며, 어떤 실질적 영향을 미치는가? | 참신성, 실용성, 학술적 의의 |
| 방법론적 혁신 | 기존 방법 대비 무엇이 근본적으로 다른가? | 기술적 차별성, 이론적 근거 |
| 실험적 엄밀성 | 실험 설계가 주장을 충분히 뒷받침하는가? | 데이터셋 적절성, 베이스라인 공정성, 재현성 |
| 이론적 깊이 | 왜 이 방법이 작동하는지 설명할 수 있는가? | 이론적 분석, 수렴성, 일반화 가능성 |
| 실질적 영향 | 이 연구가 실제 문제 해결에 얼마나 기여하는가? | 응용 가능성, 확장성, 실무 적용 |

---

## 2. 개별 논문 심층 분석

[**각 논문에 대해 아래 형식으로 최소 800자 이상, 비판적 시각으로 분석:**]

### 2.N [논문 제목]

**기본 정보**
- **저자**: [저자명]
- **발표**: [연도/학회/저널]

**연구 문제의 본질 분석**
[단순한 문제 기술이 아닌, 이 문제가 중요한 이유를 학술적 맥락에서 깊이 있게 분석.
이 문제를 해결하면 어떤 파급 효과가 있는지, 기존에 왜 해결되지 못했는지를 3-5문장으로 서술]

**핵심 방법론 및 기술적 혁신**
[알고리즘의 핵심 작동 원리를 기술적으로 설명. 단순히 "X 기법을 사용했다"가 아닌:
- 이 방법이 **왜** 이 문제에 적합한지 (이론적 근거)
- 기존 방법과 **구체적으로 어떤 점**이 다른지 (기술적 차별점)
- 핵심 알고리즘의 **작동 메커니즘** (입력->처리->출력 흐름)
- 계산 복잡도나 확장성 측면의 특성]

**주요 기여 (이론적 vs 실용적 구분)**
- 이론적 기여: [새로운 프레임워크, 수학적 증명, 분석적 통찰 등]
- 실용적 기여: [도구 개발, 성능 향상, 새로운 응용 등]

**실험 결과의 비판적 검토**
[주요 결과를 수치와 함께 서술하되, 다음도 포함:
- 실험 설계의 **강점과 약점** (데이터셋 선택의 적절성, 베이스라인 비교의 공정성)
- 보고된 성능 향상이 **통계적으로 유의미한지** 여부
- 실험에서 **빠져 있는 비교/분석** (있었다면 더 설득력 있었을 실험)]

**숨겨진 가정과 한계**
[저자가 명시적으로 언급하지 않은 부분 포함:
- 방법론의 **암묵적 가정** (데이터 분포, 계산 자원 등)
- **일반화 가능성**의 한계 (특정 도메인/규모에만 적용 가능한가?)
- **재현성** 관련 우려 (구현 세부사항 충분히 공개되었는가?)
- 향후 해결해야 할 **핵심 과제**]

---

## 3. 교차 분석 및 비교

### 3.1 연구 패러다임 분류
| 논문 | 연구 유형 | 핵심 접근법 | 데이터 | 평가 지표 | 성숙도 |
|------|----------|-----------|--------|----------|--------|
[각 논문의 연구 패러다임(실증적/이론적/설계과학적)과 접근법 성숙도(초기 탐색/발전/성숙) 분류]

### 3.2 방법론적 상보성과 모순점
[논문들의 방법론이 서로 어떻게 보완할 수 있는지, 상충되는 주장이나 결과가 있는지 분석:
- **상보적 관계**: A의 강점이 B의 약점을 보완하는 구체적 사례
- **모순되는 결과/주장**: 같은 문제에 대해 다른 결론을 내리는 경우와 그 원인 분석
- **방법론적 수렴**: 서로 다른 접근이 공통적으로 가리키는 방향]

### 3.3 기여도 비교 매트릭스
| 기여 유형 | 해당 논문 | 구체적 기여 내용 | 영향력 평가 |
|----------|----------|----------------|-----------|
| 이론적 프레임워크 제시 | | | |
| 알고리즘/모델 혁신 | | | |
| 대규모 실험적 검증 | | | |
| 실용적 도구/시스템 | | | |
| 새로운 연구 방향 개척 | | | |

---

## 4. 핵심 통찰 및 연구 시사점

### 4.1 메타 수준의 핵심 통찰 (Cross-Paper Insights)
[개별 논문 분석만으로는 보이지 않는, 논문들을 종합했을 때 비로소 발견되는 패턴과 통찰 5-7개.
각 통찰에 대해 근거가 되는 논문을 명시하고, 왜 이것이 중요한 발견인지 설명]

1. [통찰 1: 구체적 설명 + 근거 논문]
2. [통찰 2: 구체적 설명 + 근거 논문]
...

### 4.2 연구 공백 분석 (Research Gaps)
[이 논문들이 다루지 못하고 있는 중요한 연구 질문을 식별하고,
왜 이 질문들이 중요한지, 해결하기 위해 어떤 접근이 필요한지 구체적으로 서술]

### 4.3 기술 융합 가능성 (Cross-Pollination Opportunities)
[서로 다른 논문의 기법을 결합했을 때 기대되는 시너지 효과를 구체적으로 제시:
- 논문 A의 X 기법 + 논문 B의 Y 기법 = 예상되는 개선점
- 이 융합이 해결할 수 있는 현재의 한계점]

### 4.4 실무 적용 시나리오
[각 연구 결과의 산업/실무 적용 가능성을 구체적으로 평가:
- 어떤 산업/분야에서 활용 가능한가?
- 실용화까지 해결해야 할 기술적 과제는?
- 예상되는 비즈니스 임팩트]

---

## 5. 연구 동향 및 미래 전망

### 5.1 현재 연구 트렌드 분석
[논문들에서 발견되는 연구 동향을 다차원적으로 분석:]
- **기술적 트렌드**: 어떤 기술이 부상하고, 어떤 기술이 쇠퇴하고 있는가?
- **방법론적 트렌드**: 연구 방법론은 어떻게 진화하고 있는가?
- **데이터/벤치마크 트렌드**: 평가 기준과 데이터셋은 어떻게 변화하고 있는가?

### 5.2 향후 5년 연구 전망
[현재 트렌드를 바탕으로 한 미래 연구 방향 예측 5-7개.
각 방향에 대해 왜 그 방향이 유망한지, 어떤 선행 조건이 필요한지 구체적으로 서술]

### 5.3 연구자를 위한 실행 가능한 제언
[이 분야에 진입하려는 연구자에게 제공하는 구체적이고 실행 가능한 연구 제언:
- 가장 유망한 연구 주제 3가지와 그 이유
- 피해야 할 함정과 주의사항
- 필수적으로 읽어야 할 핵심 참고문헌]

---

## 6. 결론

### 6.1 주요 발견 요약
[본 리뷰의 핵심 발견을 5-7개 bullet point로 압축 정리]

### 6.2 본 리뷰의 한계
[본 리뷰의 한계점과 향후 보완 방향을 솔직하게 서술]

---

## 참고문헌

[분석된 모든 논문을 학술 인용 형식(APA)으로 정리]

---

*본 체계적 문헌 고찰은 AI 기반 심층 연구 분석 시스템에 의해 생성되었습니다.*

---

**최종 점검 (반드시 확인):**
- 모든 분석에 **구체적 근거**가 제시되었는가? (일반론 사용 금지)
- 각 논문의 **고유한 특성**이 드러나는가? (복사-붙여넣기식 분석 금지)
- **방법론의 작동 원리**가 기술적으로 설명되었는가?
- **숨겨진 가정과 한계**가 비판적으로 분석되었는가?
- **교차 논문 통찰**이 개별 분석을 넘어서는 새로운 가치를 제공하는가?
- **수치 데이터**가 충분히 인용되었는가?"""

    try:
        logger.info("[Fast Review] LLM analysing...")

        with review_sessions_lock:
            if session_id in review_sessions:
                review_sessions[session_id]["progress"] = "AI is analysing the papers..."

        # Scale timeout with number of papers (min 180s, +60s per paper, max 600s)
        api_timeout = min(600, max(180, 60 * len(papers)))
        logger.info("[Fast Review] API timeout: %ds for %d papers", api_timeout, len(papers))

        messages = [
            {"role": "system", "content": FAST_REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        max_retries = 2
        response = None
        for attempt in range(1, max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=deep_research_model,
                    messages=messages,
                    temperature=0.4,
                    max_tokens=32000,
                    timeout=api_timeout,
                )
                break
            except Exception as retry_err:
                if "timeout" in str(retry_err).lower() and attempt < max_retries:
                    logger.warning("[Fast Review] Attempt %d timed out, retrying...", attempt)
                    with review_sessions_lock:
                        if session_id in review_sessions:
                            review_sessions[session_id]["progress"] = f"Retrying analysis (attempt {attempt + 1})..."
                else:
                    raise

        report_content = response.choices[0].message.content
        logger.info("[Fast Review] Usage: %s", response.usage)

        logger.info("[Fast Review] Analysis done! (%s chars)", len(report_content))

        reports_dir = Path(workspace.session_path) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        report_filename = f"final_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        report_path = reports_dir / report_filename
        report_path.write_text(report_content, encoding="utf-8")
        logger.info("[Review] Report saved to: %s", report_path)

        analyses = []
        for paper in papers:
            analyses.append(
                {
                    "title": paper.get("title", "Unknown"),
                    "analysis": "Fast mode analysis included in report",
                    "metadata": {
                        "authors": paper.get("authors", []),
                        "year": paper.get("year", "N/A"),
                    },
                }
            )

        try:
            workspace.save_researcher_analysis(
                researcher_id="fast_mode",
                paper_id="all",
                analysis={"papers": len(papers), "mode": "fast"},
            )
        except Exception:
            pass

        return {
            "status": "completed",
            "papers_reviewed": len(papers),
            "workspace_path": str(workspace.session_path),
            "summary": {"mode": "fast", "papers": len(papers), "analyses": analyses},
        }

    except Exception as e:
        logger.exception("Fast Review error: %s", e)
        return {"status": "failed", "error": str(e)}


def _generate_review_report_content(workspace: Any, result: dict, paper_ids: List[str]) -> str:
    """
    Generate a Korean academic research-style deep report using LLM.
    """

    analyses = []
    try:
        analyses = workspace.get_all_analyses() if hasattr(workspace, "get_all_analyses") else []
    except Exception:
        pass

    num_papers = len(paper_ids)
    current_date = datetime.now().strftime("%Y년 %m월 %d일")

    analyses_summary = []
    for i, analysis in enumerate(analyses, 1):
        if isinstance(analysis, dict):
            title = analysis.get("title", f"Paper {i}")
            content = analysis.get("analysis", "")
            metadata = analysis.get("metadata", {})

            summary = f"### Paper {i}: {title}\n"
            if metadata:
                authors = metadata.get("authors", [])
                year = metadata.get("year", "Unknown")
                if authors:
                    if isinstance(authors[0], dict):
                        author_names = [a.get("name", str(a)) for a in authors[:3]]
                    else:
                        author_names = authors[:3]
                    author_str = ", ".join(author_names)
                    if len(authors) > 3:
                        author_str += " et al."
                    summary += f"- Authors: {author_str}\n"
                summary += f"- Year: {year}\n"

            if isinstance(content, str) and content:
                summary += f"- Analysis: {content[:3000]}\n"
            elif isinstance(content, dict):
                summary += f"- Analysis: {json.dumps(content, ensure_ascii=False)[:3000]}\n"

            analyses_summary.append(summary)

    combined_analyses = "\n\n".join(analyses_summary) if analyses_summary else "No analysis data"

    prompt = f"""당신은 해당 분야의 선임 연구 교수입니다. 다음 {num_papers}편의 논문 분석 데이터를 바탕으로
한글로 체계적이고 심층적인 문헌 리뷰 보고서를 작성해주세요.

## 논문 분석 데이터:
{combined_analyses}

## 다음 형식으로 상세한 학술 리뷰 보고서를 작성해주세요:

# 체계적 문헌 고찰: 선정 연구 논문의 심층 분석

---

**리뷰 날짜**: {current_date}
**분석 논문 수**: {num_papers}편
**세션 ID**: `{workspace.session_id}`

---

## 초록 (Abstract)
[분석한 논문들의 전체적인 요약과 핵심 발견을 200-300자로 작성. 실제 논문 내용을 반영해야 함]

**키워드**: [논문들에서 추출한 실제 키워드 5-7개]

---

## 1. 서론
### 1.1 연구 배경 및 동기
[분석된 논문들의 연구 분야에 대한 배경 설명. 구체적인 연구 주제와 왜 중요한지 설명]

### 1.2 본 리뷰의 목적
[이 논문들을 리뷰하는 구체적인 목적 4가지]

### 1.3 범위 및 선정 기준
[선정된 논문들의 공통 주제와 선정 이유]

---

## 2. 연구 방법론
### 2.1 분석 프레임워크
[사용된 분석 방법론 설명]

### 2.2 분석 차원
[각 논문을 어떤 관점에서 분석했는지 표로 정리]

---

## 3. 상세 문헌 분석

[각 논문에 대해 다음 형식으로 상세 분석 작성:]

### 3.N [논문 제목]
**저자**: [저자명]
**발표 연도**: [연도]

#### 연구 배경 및 문제 정의
[논문이 해결하고자 하는 문제와 동기]

#### 핵심 기여
[논문의 주요 기여점 3-5개 - 구체적으로]

#### 연구 방법론
[사용된 기술적 방법과 접근법]

#### 주요 실험 결과
[핵심 실험 결과와 성능 수치]

#### 강점
[논문의 주요 강점 3-4개]

#### 한계점 및 개선 방향
[논문의 한계와 향후 개선 방향]

#### 학술적 영향력
[이 논문이 분야에 미친/미칠 영향]

---

## 4. 비교 분석
### 4.1 방법론적 비교
[논문들의 방법론을 비교 분석 - 실제 내용 기반]

### 4.2 기여 패턴
[논문들의 기여 유형을 표로 정리]

| 논문 | 주요 기여 유형 | 구체적 기여 |
|------|---------------|------------|
[각 논문별 기여 정리]

### 4.3 강점 및 한계점 종합
[모든 논문의 공통 강점과 한계점 분석]

---

## 5. 논의
### 5.1 핵심 통찰
[분석을 통해 얻은 중요한 통찰 3-5개 - 구체적으로]

### 5.2 연구 동향
[논문들에서 발견된 연구 트렌드]

### 5.3 연구 공백
[발견된 연구 공백과 미래 연구 기회]

---

## 6. 결론 및 향후 연구 방향
### 6.1 발견 요약
[주요 발견 사항 종합]

### 6.2 향후 연구를 위한 제언
[구체적인 향후 연구 방향 5개]

### 6.3 본 리뷰의 한계
[이 리뷰의 한계점]

---

## 참고문헌
[분석된 논문 목록을 학술 형식으로 정리]

---

## 부록: 리뷰 메타데이터
- **리뷰 생성 일시**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **세션 ID**: {workspace.session_id}
- **분석 시스템**: 멀티 에이전트 심층 연구 시스템
- **분석된 논문 수**: {num_papers}편

---

*본 체계적 문헌 고찰은 심층 에이전트 연구 리뷰 시스템에 의해 생성되었습니다.*

---

**중요**:
- 각 섹션을 실제 논문 내용을 바탕으로 구체적이고 상세하게 작성해주세요.
- 일반적인 문구가 아닌, 분석된 논문의 실제 내용을 반영해야 합니다.
- 각 논문의 고유한 특성과 기여를 명확히 구분해서 작성해주세요.
- 학술 논문 수준의 깊이와 전문성을 유지해주세요."""

    try:
        deep_research_model = "gpt-4.1"
        logger.info("[Deep Review] Generating report with LLM... (model: %s)", deep_research_model)

        client = get_openai_client()
        response = client.chat.completions.create(
            model=deep_research_model,
            messages=[
                {"role": "system", "content": DEEP_REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=16000,
            timeout=120,
        )
        report_content = response.choices[0].message.content
        logger.info("[Deep Review] Usage: %s", response.usage)
        logger.info("[Deep Review] Report generated! (%s chars)", len(report_content))
        return report_content

    except Exception as e:
        logger.error("[Deep Review] LLM report generation failed: %s, using fallback template", e)
        return _generate_fallback_report(workspace, result, paper_ids, analyses, num_papers, current_date)


def _generate_fallback_report(
    workspace: Any,
    result: dict,
    paper_ids: List[str],
    analyses: list,
    num_papers: int,
    current_date: str,
) -> str:
    """Fallback template report when LLM fails."""
    report = []

    report.append("# Systematic Literature Review: In-Depth Analysis")
    report.append("")
    report.append("---")
    report.append("")
    report.append(f"**Review Date**: {current_date}")
    report.append(f"**Papers Analysed**: {num_papers}")
    report.append(f"**Session ID**: `{workspace.session_id}`")
    report.append("")
    report.append("---")
    report.append("")

    report.append("## Analysed Papers")
    report.append("")

    if analyses:
        for i, analysis in enumerate(analyses, 1):
            if isinstance(analysis, dict):
                title = analysis.get("title", f"Paper {i}")
                content = analysis.get("analysis", "")

                report.append(f"### {i}. {title}")
                report.append("")

                if isinstance(content, str) and content:
                    report.append(content[:5000])
                elif isinstance(content, dict):
                    report.append(json.dumps(content, indent=2, ensure_ascii=False)[:5000])

                report.append("")
                report.append("---")
                report.append("")
    else:
        for i, paper_id in enumerate(paper_ids, 1):
            report.append(f"[{i}] Paper ID: {paper_id}")

    report.append("")
    report.append("*A fallback template was used due to an error during report generation.*")

    return "\n".join(report)


def run_deep_review_background(
    session_id: str,
    paper_ids: List[str],
    papers_data: Optional[List[Dict[str, Any]]],
    num_researchers: int,
    model: str,
    workspace: Any,
    fast_mode: bool = True,
):
    """Background task to run deep review."""
    try:
        logger.info("[Deep Review] Starting session %s", session_id)
        logger.info("[Deep Review] Papers: %s, Mode: %s", len(paper_ids), "Fast" if fast_mode else "Deep")
        logger.info("[Deep Review] Direct papers data: %s papers", len(papers_data) if papers_data else 0)

        with review_sessions_lock:
            if session_id in review_sessions:
                review_sessions[session_id]["status"] = "analyzing"
                review_sessions[session_id]["progress"] = (
                    "Analysing papers..." if fast_mode else "Researchers analyzing papers with deepagents..."
                )

        # Enrich papers lacking abstracts (e.g. curriculum papers with arxiv_id)
        if papers_data:
            with review_sessions_lock:
                if session_id in review_sessions:
                    review_sessions[session_id]["progress"] = "Fetching paper abstracts..."
            papers_data = _enrich_papers_with_abstracts(papers_data)

        if fast_mode:
            result = run_fast_review(session_id, paper_ids, model, workspace, papers_data)
        else:
            from app.DeepAgent.deep_review_agent import DeepReviewAgent

            agent = DeepReviewAgent(model=model, num_researchers=num_researchers, workspace=workspace)
            result = agent.review_papers(paper_ids=paper_ids, verbose=True)

        workspace_path = result.get("workspace_path", str(workspace.session_path))

        if not fast_mode:
            try:
                reports_dir = Path(workspace_path) / "reports"
                reports_dir.mkdir(parents=True, exist_ok=True)

                report_content = _generate_review_report_content(workspace, result, paper_ids)

                report_filename = f"final_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                report_path = reports_dir / report_filename
                report_path.write_text(report_content, encoding="utf-8")
                logger.info("[Review] Report saved to: %s", report_path)
            except Exception as report_error:
                logger.warning("[Deep Review] Report generation warning: %s", report_error)

        with review_sessions_lock:
            if session_id in review_sessions:
                if result["status"] == "completed":
                    review_sessions[session_id]["status"] = "completed"
                    review_sessions[session_id]["progress"] = "Review completed"
                    review_sessions[session_id]["report_available"] = True
                    review_sessions[session_id]["workspace_path"] = workspace_path
                    review_sessions[session_id]["num_papers"] = result.get("papers_reviewed", len(paper_ids))
                    if papers_data:
                        review_sessions[session_id]["papers_data"] = papers_data

                    # metadata.json 갱신 (서버 재시작 시 세션 복원용)
                    try:
                        meta_path = Path(workspace_path) / "metadata.json"
                        meta = {"session_id": session_id, "status": "completed",
                                "num_papers": review_sessions[session_id]["num_papers"],
                                "paper_ids": paper_ids}
                        if papers_data:
                            meta["papers_data"] = papers_data
                        with open(meta_path, "w", encoding="utf-8") as mf:
                            json.dump(meta, mf, ensure_ascii=False, indent=2)
                    except Exception as me:
                        logger.warning("[Deep Review] Failed to update metadata.json: %s", me)

                    # 검증 통계 저장
                    v_result = result.get("verification", {})
                    v_stats = v_result.get("statistics", {})
                    if v_stats.get("total_claims", 0) > 0:
                        review_sessions[session_id]["verification_stats"] = {
                            "total_claims": v_stats.get("total_claims", 0),
                            "verifiable_claims": v_stats.get("verifiable_claims", 0),
                            "verified": v_stats.get("verified", 0),
                            "partially_verified": v_stats.get("partially_verified", 0),
                            "unverified": v_stats.get("unverified", 0),
                            "contradicted": v_stats.get("contradicted", 0),
                            "verification_rate": v_stats.get("verification_rate", 0.0),
                        }
                else:
                    review_sessions[session_id]["status"] = "failed"
                    review_sessions[session_id]["error"] = result.get("error", "Unknown error")

        logger.info("[Deep Review] Session %s completed: %s", session_id, result["status"])

    except Exception as e:
        logger.exception("[Deep Review] Session %s failed: %s", session_id, e)
        with review_sessions_lock:
            if session_id in review_sessions:
                review_sessions[session_id]["status"] = "failed"
                review_sessions[session_id]["error"] = str(e)


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/deep-review")
@limiter.limit("5/minute")
async def start_deep_review(
    request: Request,
    review_request: DeepReviewRequest,
    background_tasks: BackgroundTasks,
    username: str | None = Depends(get_optional_user),
):
    """Start deep paper review. Runs in background and returns session_id immediately."""
    _cleanup_expired_sessions()

    try:
        from app.DeepAgent.workspace_manager import WorkspaceManager

        logger.info("[Deep Review] Starting with %s papers", len(review_request.paper_ids))

        workspace = WorkspaceManager()
        session_id = workspace.session_id

        with review_sessions_lock:
            review_sessions[session_id] = {
                "status": "processing",
                "paper_ids": review_request.paper_ids,
                "num_papers": len(review_request.paper_ids),
                "workspace_path": str(workspace.session_path),
                "created_at": datetime.now().isoformat(),
                "username": username,
            }

        background_tasks.add_task(
            run_deep_review_background,
            session_id=session_id,
            paper_ids=review_request.paper_ids,
            papers_data=review_request.papers,
            num_researchers=review_request.num_researchers,
            model=review_request.model,
            workspace=workspace,
            fast_mode=review_request.fast_mode,
        )

        return {
            "success": True,
            "session_id": session_id,
            "status": "processing",
            "message": f"Deep review started for {len(review_request.paper_ids)} papers",
            "status_url": f"/api/deep-review/status/{session_id}",
        }

    except Exception as e:
        logger.exception("[Deep Review] ERROR: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to start review: {str(e)}")


@router.get("/deep-review/status/{session_id}")
async def get_review_status(session_id: str, username: str | None = Depends(get_optional_user)) -> ReviewStatusResponse:
    """Get status of a deep review session."""
    with review_sessions_lock:
        if session_id not in review_sessions:
            raise HTTPException(status_code=404, detail="Session not found")

        session = review_sessions[session_id]

        # Allow access if no auth required or if user owns the session
        session_owner = session.get("username")
        if session_owner and username and session_owner != username:
            raise HTTPException(status_code=404, detail="Session not found")

        v_raw = session.get("verification_stats")
        v_stats = VerificationStats(**v_raw) if v_raw else None

        return ReviewStatusResponse(
            session_id=session_id,
            status=session["status"],
            progress=session.get("progress"),
            report_available=session.get("report_available", False),
            error=session.get("error"),
            verification_stats=v_stats,
        )


@router.get("/deep-review/report/{session_id}")
async def get_review_report(session_id: str, username: str | None = Depends(get_optional_user)):
    """Get the generated review report."""
    with review_sessions_lock:
        if session_id not in review_sessions:
            raise HTTPException(status_code=404, detail="Session not found")

        session = review_sessions[session_id]

        # Allow access if no auth required or if user owns the session
        session_owner = session.get("username")
        if session_owner and username and session_owner != username:
            raise HTTPException(status_code=404, detail="Session not found")

        if session["status"] != "completed":
            raise HTTPException(
                status_code=400, detail=f"Review not completed yet (status: {session['status']})"
            )

        workspace_path = Path(session["workspace_path"])
        reports_dir = workspace_path / "reports"

        if not reports_dir.exists():
            raise HTTPException(status_code=404, detail="Reports directory not found")

        md_files = sorted(reports_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

        if not md_files:
            raise HTTPException(status_code=404, detail="Report not found")

        with open(md_files[0], "r", encoding="utf-8") as f:
            report_content = f.read()

        json_files = sorted(reports_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        json_result = None
        if json_files:
            try:
                with open(json_files[0], "r", encoding="utf-8") as f:
                    json_result = json.load(f)
            except Exception:
                pass

        return {
            "session_id": session_id,
            "report_markdown": report_content,
            "report_json": json_result,
            "num_papers": session.get("num_papers", 0),
            "created_at": session.get("created_at"),
            "verification_stats": session.get("verification_stats"),
        }


@router.get("/deep-review/verification/{session_id}")
async def get_verification_detail(session_id: str, username: str | None = Depends(get_optional_user)):
    """Get detailed verification results (claims, evidence, cross-references)."""
    with review_sessions_lock:
        if session_id not in review_sessions:
            raise HTTPException(status_code=404, detail="Session not found")

        session = review_sessions[session_id]

        # Allow access if no auth required or if user owns the session
        session_owner = session.get("username")
        if session_owner and username and session_owner != username:
            raise HTTPException(status_code=404, detail="Session not found")

        if session["status"] != "completed":
            raise HTTPException(
                status_code=400, detail=f"Review not completed yet (status: {session['status']})"
            )

        workspace_path = Path(session["workspace_path"])

    verifications_dir = workspace_path / "verifications"
    if not verifications_dir.exists():
        return {
            "session_id": session_id,
            "claims": [],
            "cross_references": [],
            "consensus": [],
            "verification_stats": session.get("verification_stats"),
        }

    # Load claims
    claims_data = []
    claim_files = sorted(
        verifications_dir.glob("claims_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if claim_files:
        try:
            with open(claim_files[0], "r", encoding="utf-8") as f:
                data = json.load(f)
                claims_data = data.get("claims", [])
        except Exception as e:
            logger.warning("Failed to load claims: %s", e)

    # Load cross-references and consensus
    crossrefs_data = []
    consensus_data = []
    xref_files = sorted(
        verifications_dir.glob("crossrefs_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if xref_files:
        try:
            with open(xref_files[0], "r", encoding="utf-8") as f:
                data = json.load(f)
                crossrefs_data = data.get("cross_references", [])
                consensus_data = data.get("consensus", [])
        except Exception as e:
            logger.warning("Failed to load cross-references: %s", e)

    return {
        "session_id": session_id,
        "claims": claims_data,
        "cross_references": crossrefs_data,
        "consensus": consensus_data,
        "verification_stats": session.get("verification_stats"),
    }


@router.post("/deep-review/visualize/{session_id}")
async def generate_poster_visualization(session_id: str, username: str | None = Depends(get_optional_user)):
    """Generate a conference poster from the deep research report."""
    try:
        logger.info("[Poster API] Starting poster generation for session: %s", session_id)

        try:
            from app.DeepAgent.agents import PosterGenerationAgent

            logger.info("[Poster API] PosterGenerationAgent imported successfully")
        except Exception as e:
            logger.exception("[Poster API] Failed to import PosterGenerationAgent: %s", e)
            raise HTTPException(status_code=500, detail=f"Failed to import PosterGenerationAgent: {str(e)}")

        with review_sessions_lock:
            if session_id not in review_sessions:
                logger.error("[Poster API] Session not found: %s", session_id)
                raise HTTPException(status_code=404, detail="Session not found")

            session = review_sessions[session_id]

            # Allow access if no auth required or if user owns the session
            session_owner = session.get("username")
            if session_owner and username and session_owner != username:
                raise HTTPException(status_code=404, detail="Session not found")

            logger.info("[Poster API] Session found: status=%s", session.get("status"))

            if session["status"] != "completed":
                logger.error("[Poster API] Review not completed: status=%s", session.get("status"))
                raise HTTPException(status_code=400, detail="Review not completed yet")

            workspace_path = Path(session["workspace_path"])
            logger.info("[Poster API] Workspace path: %s", workspace_path)

        reports_dir = workspace_path / "reports"
        md_files = sorted(reports_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

        if not md_files:
            logger.error("[Poster API] No report files found in: %s", reports_dir)
            raise HTTPException(status_code=404, detail="Report not found")

        logger.info("[Poster API] Found %s report file(s)", len(md_files))
        with open(md_files[0], "r", encoding="utf-8") as f:
            report_content = f.read()
        logger.info("[Poster API] Report content loaded: %s chars", len(report_content))

        try:
            from app.DeepAgent.config.design_pattern_manager import get_design_pattern_manager

            pattern_manager = get_design_pattern_manager()
            logger.info("[Poster API] DesignPatternManager initialized")
        except Exception as e:
            logger.warning("[Poster API] Failed to initialize DesignPatternManager: %s", e)
            pattern_manager = None

        try:
            poster_agent = PosterGenerationAgent(
                model="gemini-2.5-flash-preview-05-20",
                design_pattern_manager=pattern_manager,
                enable_critic=True,
                max_critic_rounds=2,
            )
            logger.info(
                "[Poster API] PosterGenerationAgent initialized: llm=%s, critic=%s, api_key=%s",
                poster_agent.llm is not None,
                poster_agent.critic_agent is not None,
                bool(poster_agent.api_key),
            )
        except Exception as e:
            logger.exception("[Poster API] Failed to initialize PosterGenerationAgent: %s", e)
            raise HTTPException(
                status_code=500, detail=f"Failed to initialize PosterGenerationAgent: {str(e)}"
            )

        poster_dir = workspace_path / "posters"
        num_papers = session.get("num_papers", 0)

        papers_data = None
        try:
            from app.DeepAgent.tools.paper_loader import load_papers_from_ids

            paper_ids = session.get("paper_ids", [])
            if paper_ids:
                papers_data = load_papers_from_ids(paper_ids)
                logger.info(
                    "[Poster API] Papers loaded (papers.json): %s",
                    len(papers_data) if papers_data else 0,
                )

            if not papers_data:
                papers_data = session.get("papers_data")
                if papers_data:
                    logger.info("[Poster API] Using session papers data: %s", len(papers_data))
        except Exception as e:
            logger.warning("[Poster API] Failed to load papers data: %s", e)
            papers_data = session.get("papers_data")

        logger.info(
            "[Poster API] Generating poster: num_papers=%s, output_dir=%s, papers_data=%s",
            num_papers,
            poster_dir,
            len(papers_data) if papers_data else 0,
        )

        try:
            result = await asyncio.to_thread(
                poster_agent.generate_poster,
                report_content=report_content,
                num_papers=num_papers,
                output_dir=poster_dir,
                papers_data=papers_data,
            )
            logger.info(
                "[Poster API] Poster generated: success=%s, path=%s",
                result.get("success"),
                result.get("poster_path", "N/A"),
            )
        except Exception as e:
            logger.exception("[Poster API] Failed to generate poster: %s", e)
            raise HTTPException(status_code=500, detail=f"Failed to generate poster: {str(e)}")

        if not result.get("poster_html"):
            error_msg = result.get("error", "Poster HTML generation returned empty")
            logger.error("[Poster API] Empty poster HTML: %s", error_msg)
            raise HTTPException(status_code=500, detail=error_msg)

        return {
            "success": result["success"],
            "session_id": session_id,
            "poster_html": result["poster_html"],
            "poster_path": result.get("poster_path", ""),
            "error": result.get("error", ""),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Poster API] Unexpected error: %s", e)
        raise HTTPException(status_code=500, detail=f"Poster generation failed: {str(e)}")


class DirectPosterRequest(BaseModel):
    """세션 없이 리포트 콘텐츠로 직접 포스터를 생성하는 요청."""
    report_content: str
    num_papers: int = 0


@router.post("/deep-review/visualize-direct")
async def generate_poster_direct(
    request: DirectPosterRequest,
    username: str | None = Depends(get_optional_user),
):
    """세션 없이 리포트 마크다운으로 직접 포스터를 생성한다.

    세션이 유실된 경우 프론트엔드가 reviewReport를 직접 전달하여 포스터를 생성할 수 있다.
    """
    try:
        logger.info("[Poster Direct] Starting: %d chars, %d papers", len(request.report_content), request.num_papers)

        from app.DeepAgent.agents import PosterGenerationAgent
        try:
            from app.DeepAgent.config.design_pattern_manager import get_design_pattern_manager
            pattern_manager = get_design_pattern_manager()
        except Exception:
            pattern_manager = None

        poster_agent = PosterGenerationAgent(
            model="gemini-2.5-flash-preview-05-20",
            design_pattern_manager=pattern_manager,
            enable_critic=True,
            max_critic_rounds=1,  # 직접 생성은 1라운드로 빠르게
        )
        logger.info("[Poster Direct] Agent: llm=%s, api_key=%s", poster_agent.llm is not None, bool(poster_agent.api_key))

        result = await asyncio.to_thread(
            poster_agent.generate_poster,
            report_content=request.report_content,
            num_papers=request.num_papers,
        )

        if not result.get("poster_html"):
            raise HTTPException(status_code=500, detail=result.get("error", "Empty poster"))

        return {
            "success": result["success"],
            "session_id": "",
            "poster_html": result["poster_html"],
            "poster_path": "",
            "error": result.get("error", ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Poster Direct] Failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
