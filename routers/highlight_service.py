"""
Highlight extraction service.

Contains the LLM-based auto-highlight logic:
- CATEGORY_CONFIG, prompt template, and helper functions
- generate_highlights() – calls LLM to extract highlights from a report
"""

import json
import logging
import re

from .llm_cache import get_cached, set_cache

logger = logging.getLogger(__name__)


# ── Category configuration ────────────────────────────────────────────

CATEGORY_CONFIG = {
    # Green -- empirical findings
    "finding":         {"label": "[핵심 발견]", "color": "#6ee7b7"},
    "evidence":        {"label": "[근거/수치]", "color": "#6ee7b7"},
    "contribution":    {"label": "[핵심 기여]", "color": "#6ee7b7"},
    # Blue -- analytical / structural
    "methodology":     {"label": "[방법론]",    "color": "#93c5fd"},
    "insight":         {"label": "[인사이트]",  "color": "#93c5fd"},
    "reproducibility": {"label": "[재현성]",    "color": "#93c5fd"},
    # Rose -- critical evaluation
    "limitation":      {"label": "[연구 한계]", "color": "#fca5a5"},
    "gap":             {"label": "[연구 공백]", "color": "#fca5a5"},
}

AUTO_HIGHLIGHT_SYSTEM_PROMPT = """\
당신은 Nature, Science 등 최상위 저널의 리뷰어이자 학술 논문 분석 전문가입니다.
주어진 연구 리포트에서 가장 핵심적이고 학술적 가치가 높은 구절을 정확히 추출하는 것이 임무입니다.

## 추출 원칙
1. **원문 정확 복사**: text 필드에는 리포트 본문에서 해당 구절을 한 글자도 바꾸지 않고 그대로 복사해야 합니다.
   - 공백, 구두점, 특수문자까지 모두 원문 그대로여야 합니다.
   - 마크다운 기호(#, *, -, |)는 제외하고 순수 텍스트만 복사하세요.
2. **구절 길이**: 한 문장 또는 의미 있는 반 문장(20~120자) 단위로 추출하세요. 너무 짧거나(10자 미만) 너무 길면(200자 초과) 안 됩니다.
3. **깊이 우선**: 표면적이거나 일반적인 서술이 아니라, 구체적 수치·방법·비교·한계·새로운 해석이 담긴 문장을 선택하세요.

## 카테고리 가이드 (8개 카테고리, 3가지 색상 톤)

### Green 톤 (실증적/긍정적 발견)
- **finding**: 실증적 연구 결과, 정량적 수치, 핵심 결론.
  예: 특정 수치 결과, 비교 실험 결과, 핵심 발견 요약
- **evidence**: 주장을 뒷받침하는 구체적 데이터, 통계, 실험 수치.
  예: p-value, 성능 지표, 정확도 비교, 표본 크기
- **contribution**: 학술적·실용적 핵심 기여, 새로운 프레임워크·도구 제시.
  예: 새로운 분석 도구 제안, 기존 방법 대비 차별점

### Blue 톤 (분석적/구조적)
- **methodology**: 핵심 알고리즘, 기술적 혁신, 연구 설계.
  예: 모델 아키텍처 설명, 데이터 처리 방식, 새로운 접근법
- **insight**: 논문 간 교차 해석, 메타 수준의 시사점, 독창적 통찰.
  예: 연구 트렌드 해석, 방법론 간 시너지, 학문적 의미
- **reproducibility**: 재현 가능성, 데이터/코드 공개 여부, 실험 조건의 투명성.
  예: 데이터셋 공개 수준, 파라미터 설정 기준, 재현성 우려

### Rose 톤 (비판적 평가)
- **limitation**: 연구의 명시적 한계, 숨겨진 가정, 향후 과제.
  예: 데이터 제약, 일반화 한계, 미해결 문제
- **gap**: 연구 공백, 후속 연구 필요성, 미탐색 영역.
  예: 다루지 못한 변수, 누락된 비교군, 확장 필요성

## 중요도 (significance) 점수
각 하이라이트에 1~5점의 중요도를 부여하세요:
- 5: 논문 전체의 핵심 결론 또는 가장 중요한 발견
- 4: 주요 방법론적 혁신 또는 핵심 실험 결과
- 3: 의미 있는 기여이나 보조적 수준
- 2: 참고할 만한 세부 사항
- 1: 맥락적 배경 정보

## 섹션 인식
리포트는 [SECTION: 제목] 마커로 섹션이 구분되어 있습니다.
각 하이라이트가 추출된 섹션의 제목을 section 필드에 기록하세요.
마커가 없는 경우 가장 가까운 문맥의 섹션 제목을 추정하여 기록합니다.

## Reviewer Commentary (P2)
각 하이라이트에 전문 리뷰어 수준의 비평을 제공하세요.

### reviewer_comment — 톤별 리뷰 관점
2~3문장의 비판적 코멘트를 작성하되, 카테고리 톤에 따라 다른 관점(lens)을 적용하세요:

**Green 톤** (finding/evidence/contribution):
→ 결과의 내적 타당도(internal validity), 효과 크기(effect size)의 실질적 의미, 외적 타당도 한계를 분석하세요.
  예: "42개 도시 대상 비교 분석에서 클러스터링 패턴의 일관성은 내적 타당도가 높다. 그러나 표본이 중국 도시에 편중되어 있어 글로벌 일반화에는 한계가 있다."

**Blue 톤** (methodology/insight/reproducibility):
→ 방법론적 엄밀성, 기존 접근법 대비 차별적 장점, 재현 가능성 우려를 분석하세요.
  예: "GAN 기반 데이터 증강은 소규모 데이터셋 문제를 창의적으로 해결하지만, 생성 데이터의 분포가 원본과 괴리될 경우 모델 편향을 오히려 증폭시킬 수 있다."

**Rose 톤** (limitation/gap):
→ 한계의 근본 원인, 해소를 위한 구체적 접근법, 후속 연구에서 우선적으로 다뤄야 할 사항을 분석하세요.
  예: "단일 시점 분석은 도시 발전의 시계열 역학을 포착하지 못한다. 5~10년 종단 데이터 확보 시 정책 효과의 인과관계 추론이 가능해질 것이다."

### implication — 3차원 영향 분석
1~2문장으로 다음 3가지 차원 중 가장 적합한 것을 선택하여 기술하세요:
- **이론적 함의**: 기존 이론/모델에 대한 지지 또는 도전
- **실용적 함의**: 산업·정책·응용 관점에서의 의미
- **후속 연구 방향**: 이 발견이 열어주는 새로운 연구 질문
  예: "도시 형태와 에너지 효율 간 비선형 관계의 발견은 기존 선형 모델 가정에 도전하며, 복잡계 시뮬레이션 기반 후속 연구를 촉발할 것이다."

### 금지 사항
다음과 같은 보일러플레이트 코멘트는 절대 금지합니다:
- "이 결과는 의미 있다" / "중요한 기여이다" → 무엇이, 왜 의미 있는지 구체적으로 기술
- "향후 연구가 필요하다" → 어떤 방향의, 어떤 문제에 대한 연구인지 기술
- "흥미로운 접근이다" → 기존 방법 대비 어떤 점에서 차별적인지 기술

### 근거 기반 원칙
reviewer_comment와 implication에는 리포트에 직접 언급되지 않은 수치, 저자명, 논문 제목을 포함하지 마세요.
리포트 본문에 근거가 있는 분석만 기술하세요.

## 출력 형식
반드시 아래 JSON 형식으로만 응답하세요:
{"highlights": [{"text": "리포트 원문 그대로", "category": "finding|evidence|contribution|methodology|insight|reproducibility|limitation|gap", "reviewer_comment": "비판적 코멘트 2~3문장", "implication": "연구 분야 영향 1~2문장", "significance": 1, "section": "섹션 제목"}]}

## 선정 기준
- 총 10~18개 하이라이트를 추출하세요.
- Green 톤(finding, evidence, contribution)에서 최소 3개.
- Blue 톤(methodology, insight, reproducibility)에서 최소 3개.
- Rose 톤(limitation, gap)에서 최소 2개.
- significance 4~5는 전체의 30~40%를 권장합니다.
- 리포트 전체에 걸쳐 고르게 분포시키세요 (서론~결론까지).
- 중복되는 내용의 구절은 제외하세요.\
"""


# ── Helper functions ──────────────────────────────────────────────────

def _parse_report_sections(report: str) -> str:
    """Parse report markdown and reformat with [SECTION: ...] markers for LLM."""
    heading_pattern = re.compile(r'^(#{2,3})\s+(.+)$', re.MULTILINE)
    matches = list(heading_pattern.finditer(report))

    if not matches:
        return report

    parts: list[str] = []
    # Content before first heading
    if matches[0].start() > 0:
        preamble = report[:matches[0].start()].strip()
        if preamble:
            parts.append(preamble)

    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(report)
        content = report[start:end].strip()
        if content:
            parts.append(f"\n[SECTION: {heading}]\n{content}")

    return "\n".join(parts)


def _strip_markdown(text: str) -> str:
    """Strip common markdown formatting characters for comparison."""
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)  # bold/italic
    text = re.sub(r'`([^`]+)`', r'\1', text)  # inline code
    return text.strip()


def _find_verbatim_or_fuzzy(text: str, report: str) -> str | None:
    """Return the original report substring matching `text`, or None."""
    # 1. Exact verbatim match
    if text in report:
        return text

    # 2. Whitespace-normalized match within individual lines
    normalized = " ".join(text.split())
    for line in report.split("\n"):
        norm_line = " ".join(line.split())
        idx = norm_line.find(normalized)
        if idx == -1:
            continue
        # Map normalized offset back to original line
        orig_start = 0
        ni = 0
        for ci, ch in enumerate(line):
            if ni == idx:
                orig_start = ci
                break
            if ch.strip() or (ci > 0 and line[ci - 1].strip()):
                ni += 1
        # Extract original substring of the same semantic length
        orig_end = orig_start
        ni = 0
        for ci in range(orig_start, len(line)):
            if ni >= len(normalized):
                break
            ch = line[ci]
            if ch.strip() or (ci > orig_start and line[ci - 1].strip()):
                ni += 1
            orig_end = ci + 1
        candidate = line[orig_start:orig_end].strip()
        if candidate and candidate in report:
            return candidate

    # 3. Markdown-stripped match: try stripping bold/italic/code from LLM output
    stripped = _strip_markdown(text)
    if stripped != text and stripped in report:
        return stripped

    return None


# ── Main highlight generation ─────────────────────────────────────────

def generate_highlights(report: str, query: str, title: str, client) -> list[dict]:
    """Call LLM to extract highlights from a report. Returns list of raw highlight dicts.

    Args:
        report: Full report markdown text.
        query: The research query associated with the bookmark.
        title: The bookmark title.
        client: An OpenAI-compatible client instance.

    Returns:
        A list of highlight dicts as returned by the LLM (unprocessed).

    Raises:
        openai.APITimeoutError: If the LLM call times out.
        openai.RateLimitError: If the API rate limit is hit.
        openai.APIError: On other API errors.
        ValueError: If the LLM returns invalid JSON.
    """
    from openai import APITimeoutError, RateLimitError, APIError

    # Section-aware truncation: keep structure intact up to limit
    max_chars = 24000
    if len(report) > max_chars:
        cutoff = report.rfind("\n## ", 0, max_chars)
        if cutoff > max_chars * 0.6:
            report_text = report[:cutoff]
        else:
            cutoff = report.rfind("\n\n", 0, max_chars)
            report_text = report[:cutoff] if cutoff > 0 else report[:max_chars]
    else:
        report_text = report

    topic_context = f"[연구 주제: {title or query}]\n\n" if (query or title) else ""

    # Section-aware formatting for LLM
    formatted_report = _parse_report_sections(report_text)

    model = "gpt-4.1"
    temperature = 0.2
    user_prompt = (
        f"{topic_context}"
        f"다음 연구 리포트에서 핵심 하이라이트를 추출해 주세요.\n\n"
        f"---\n{formatted_report}\n---"
    )

    # Check LLM cache first
    cached = get_cached(AUTO_HIGHLIGHT_SYSTEM_PROMPT, user_prompt, model, temperature)
    if cached is not None:
        logger.info("Using cached LLM response for auto-highlight")
        raw = cached
    else:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            timeout=120,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": AUTO_HIGHLIGHT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        logger.info("Auto-highlight token usage: %s", response.usage)
        raw = response.choices[0].message.content or "{}"

        # Store response in cache
        set_cache(AUTO_HIGHLIGHT_SYSTEM_PROMPT, user_prompt, model, temperature, raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("LLM returned invalid JSON")

    return parsed.get("highlights", [])
