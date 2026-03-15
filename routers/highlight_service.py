"""
Highlight extraction service.

Contains the LLM-based auto-highlight logic:
- CATEGORY_CONFIG, prompt template, and helper functions
- generate_highlights() – calls LLM to extract highlights from a report

PDF-specific highlight pipeline:
- PDF_CATEGORY_CONFIG – extended 11-category config for academic papers
- PDF_HIGHLIGHT_SYSTEM_PROMPT – optimised for raw paper text
- preprocess_pdf_text() – clean raw PDF extraction artefacts
- truncate_paper_text() – structure-aware truncation for long papers
- generate_pdf_highlights() – end-to-end PDF highlight generation
"""

import json
import logging
import re
from collections import Counter

from .llm_cache import get_cached, set_cache

logger = logging.getLogger(__name__)


# ── Category configuration ────────────────────────────────────────────

CATEGORY_CONFIG = {
    # Green -- empirical findings
    "finding":         {"label": "[핵심 발견]",   "color": "#a5b4fc"},
    "evidence":        {"label": "[근거/수치]",   "color": "#a5b4fc"},
    "contribution":    {"label": "[핵심 기여]",   "color": "#a5b4fc"},
    # Blue -- analytical / structural
    "methodology":     {"label": "[방법론]",      "color": "#a5b4fc"},
    "insight":         {"label": "[인사이트]",    "color": "#a5b4fc"},
    "reproducibility": {"label": "[재현성]",      "color": "#a5b4fc"},
    # Rose -- critical evaluation
    "limitation":      {"label": "[연구 한계]",   "color": "#fda4af"},
    "gap":             {"label": "[연구 공백]",   "color": "#fda4af"},
    "assumption":      {"label": "[숨겨진 가정]", "color": "#fda4af"},
}

AUTO_HIGHLIGHT_SYSTEM_PROMPT = """\
당신은 Nature, Science, Cell 등 최상위 저널의 시니어 리뷰어이자 해당 연구 도메인의 전문가입니다.
주어진 연구 리포트에서 학술적 가치가 높은 구절을 정확히 추출하고, 각 구절에 대해 전문가 수준의 심층 비평을 제공하는 것이 임무입니다.

당신의 코멘트는 단순 요약이 아니라, 동료 연구자에게 제공하는 **비판적 피어 리뷰**여야 합니다.

## 추출 원칙
1. **원문 정확 복사**: text 필드에는 리포트 본문에서 해당 구절을 한 글자도 바꾸지 않고 그대로 복사해야 합니다.
   - 공백, 구두점, 특수문자까지 모두 원문 그대로여야 합니다.
   - 마크다운 기호(#, *, -, |)는 제외하고 순수 텍스트만 복사하세요.
2. **구절 길이**: 한 문장 또는 의미 있는 반 문장(20~120자) 단위로 추출하세요. 너무 짧거나(10자 미만) 너무 길면(200자 초과) 안 됩니다.
3. **깊이 우선**: 표면적이거나 일반적인 서술이 아니라, 구체적 수치·방법·비교·한계·새로운 해석이 담긴 문장을 선택하세요.

## 카테고리 가이드 (9개 카테고리, 3가지 색상 톤)

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
- **limitation**: 연구의 명시적 한계, 향후 과제.
  예: 데이터 제약, 일반화 한계, 미해결 문제
- **gap**: 연구 공백, 후속 연구 필요성, 미탐색 영역.
  예: 다루지 못한 변수, 누락된 비교군, 확장 필요성
- **assumption**: 연구가 암묵적으로 전제하지만 명시적으로 검증하지 않은 가정.
  예: 데이터 분포 가정, 인과관계 가정, 일반화 가능성 가정, 측정 도구의 타당성 가정

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

## Expert Reviewer Commentary

각 하이라이트에 해당 연구 도메인의 시니어 리뷰어 관점에서 심층 비평을 제공하세요.

### reviewer_comment — 3단계 구조화된 비평

**반드시 아래 3단계를 순서대로 포함**하는 3~4문장을 작성하세요:

**1단계: 평가 판단** — 이 구절이 학술적으로 강점(strength)인지 약점(weakness)인지 명확히 판단하세요.
**2단계: 근거/반론** — 판단의 근거를 리포트 내 다른 부분과 교차 검증하거나, 해당 주장에 대한 잠재적 반론(devil's advocate)을 제시하세요.
**3단계: 건설적 제안** — 강점이면 확장·응용 방향을, 약점이면 구체적 개선 방안을 제시하세요.

카테고리 톤에 따라 비평의 렌즈를 달리하세요:

**Green 톤** (finding/evidence/contribution):
→ 내적 타당도(internal validity), 효과 크기(effect size)의 실질적 의미, 외적 타당도 한계, 교란 변수 가능성을 분석하세요.

**Blue 톤** (methodology/insight/reproducibility):
→ 방법론적 엄밀성(methodological rigor), 기존 접근법 대비 이론적·실용적 차별점, 재현 시 필요한 조건을 분석하세요.

**Rose 톤** (limitation/gap/assumption):
→ 한계의 근본 원인(root cause), 가정이 위반될 경우의 결과 민감도, 해소를 위한 구체적 실험/데이터/분석 설계를 분석하세요.

### strength_or_weakness — 강점/약점 판별
이 구절이 연구의 "strength"인지 "weakness"인지 단일 값으로 기록하세요.
Green 톤이라도 약점일 수 있고, Rose 톤이라도 강점(예: 한계를 솔직히 인정)일 수 있습니다.

### question_for_authors — 저자에게 묻고 싶은 질문
이 구절을 읽은 리뷰어가 저자에게 물을 법한 핵심 질문 1개를 작성하세요.
예: "표본 크기 42개 도시가 클러스터링 패턴의 통계적 안정성을 보장하기에 충분한 근거는 무엇인가?"

### confidence_level — 리뷰어 확신도
이 코멘트에 대한 리뷰어로서의 확신 수준을 1~5로 기록하세요:
- 5: 해당 분야 핵심 전문성 — 확신을 가지고 판단
- 4: 관련 분야 경험 — 높은 확신
- 3: 일반적 학술 판단 — 보통 확신
- 2: 인접 분야 지식 기반 — 낮은 확신
- 1: 추론적 판단 — 전문성 부족

### implication — 다차원 영향 분석
2~3문장으로 다음 3가지 차원 중 **2가지 이상**을 포함하여 기술하세요:
- **이론적 함의**: 기존 이론/모델에 대한 지지, 수정, 또는 도전
- **실용적 함의**: 산업·정책·응용 관점에서의 의미와 적용 가능성
- **후속 연구 방향**: 이 발견이 열어주는 구체적인 새로운 연구 질문

### 금지 사항 (Zero Tolerance)
다음과 같은 보일러플레이트 코멘트는 **절대 금지**합니다:
- "이 결과는 의미 있다" / "중요한 기여이다" → 무엇이, 왜, 기존 대비 어떻게 의미 있는지 구체적으로 기술
- "향후 연구가 필요하다" → 어떤 변수를, 어떤 방법으로, 어떤 가설 하에 연구해야 하는지 기술
- "흥미로운 접근이다" → 기존 방법 대비 어떤 이론적·기술적 차별점이 있는지 기술
- "추가 검증이 필요하다" → 어떤 실험 설계로, 어떤 데이터셋에서, 어떤 baseline과 비교해야 하는지 기술

### 근거 기반 원칙
reviewer_comment, implication, question_for_authors에는 리포트에 직접 언급되지 않은 수치, 저자명, 논문 제목을 포함하지 마세요.
리포트 본문에 근거가 있는 분석만 기술하세요.

## 출력 형식
반드시 아래 JSON 형식으로만 응답하세요:
{"highlights": [{"text": "리포트 원문 그대로", "category": "finding|evidence|contribution|methodology|insight|reproducibility|limitation|gap|assumption", "reviewer_comment": "3단계 구조화된 비평 3~4문장", "strength_or_weakness": "strength|weakness", "question_for_authors": "저자에게 묻고 싶은 핵심 질문 1개", "confidence_level": 4, "implication": "다차원 영향 분석 2~3문장", "significance": 4, "section": "섹션 제목"}]}

## 선정 기준
- 총 12~18개 하이라이트를 추출하세요.
- Green 톤(finding, evidence, contribution)에서 최소 3개.
- Blue 톤(methodology, insight, reproducibility)에서 최소 3개.
- Rose 톤(limitation, gap, assumption)에서 최소 3개 (assumption 최소 1개 필수).
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


# ══════════════════════════════════════════════════════════════════════
# PDF-specific highlight pipeline
# ══════════════════════════════════════════════════════════════════════

PDF_CATEGORY_CONFIG: dict[str, dict[str, str]] = {
    # Green tone — empirical / positive findings
    "finding":            {"label": "[Key Finding]",          "color": "#86efac"},
    "evidence":           {"label": "[Evidence/Data]",        "color": "#86efac"},
    "contribution":       {"label": "[Contribution]",         "color": "#4ade80"},
    "claim":              {"label": "[Author Claim]",         "color": "#86efac"},
    # Blue tone — analytical / structural
    "methodology":        {"label": "[Methodology]",          "color": "#93c5fd"},
    "insight":            {"label": "[Insight]",              "color": "#93c5fd"},
    "reproducibility":    {"label": "[Reproducibility]",      "color": "#7dd3fc"},
    "experimental_setup": {"label": "[Experimental Setup]",   "color": "#93c5fd"},
    # Rose tone — critical evaluation
    "limitation":         {"label": "[Limitation]",           "color": "#fda4af"},
    "gap":                {"label": "[Research Gap]",         "color": "#fda4af"},
    "assumption":         {"label": "[Hidden Assumption]",    "color": "#fb923c"},
}

PDF_HIGHLIGHT_SYSTEM_PROMPT = """\
You are a senior peer reviewer for top-tier venues (Nature, Science, NeurIPS, ACL, \
CVPR) and a domain expert in the field of the paper under review.

Your task is to analyse the **original academic paper text** provided below, extract \
passages of high scholarly value, and write expert-level critical commentary for each.

Your comments must be **critical peer review**, not summaries.

## Step 1: Paper Type Detection
Before extracting highlights, identify the paper type from the text:
- EMPIRICAL: proposes method + experiments (most CS/ML papers)
- THEORETICAL: proves theorems or derives formal results
- CLINICAL: RCT, cohort study, or clinical research
- SURVEY: systematic review, meta-analysis, or literature survey

State the detected type in a `paper_type` field in your JSON output.

## Step 2: Apply Type-Specific Critical Lens
Adapt your critical analysis based on the detected paper type:
- EMPIRICAL: ablation completeness, baseline fairness, dataset leakage, \
hyperparameter sensitivity
- THEORETICAL: proof validity, assumption necessity, bound tightness, constructiveness
- CLINICAL: CONSORT/PRISMA compliance, confounders, p-hacking risk, \
intention-to-treat
- SURVEY: search protocol, inclusion/exclusion criteria, coverage, synthesis quality

## Extraction Rules
1. **Verbatim copy**: The `text` field must be copied character-for-character from the \
paper text. Preserve whitespace, punctuation, and special characters exactly.
2. **Passage length**: English 30-200 characters; Korean/CJK 20-120 characters. \
Do not extract passages shorter than 15 characters or longer than 250 characters.
3. **Depth first**: Prefer sentences with specific numbers, methods, comparisons, \
limitations, or novel interpretations over generic statements.

## Paper Structure Awareness
The paper text may contain `[SECTION: ...]` markers denoting standard academic sections \
(Abstract, Introduction, Related Work, Methods/Methodology, \
Results/Experiments, Discussion, Conclusion).
Record the section each highlight belongs to in the `section` field.

## EXCLUSION: Do NOT highlight any text from the References / Bibliography section.

## Category Guide (11 categories, 3 colour tones)

### Green tone (empirical / positive findings)
- **finding**: A measured or observed result — quantitative outcomes, statistical \
test results, or empirical observations directly obtained from experiments or data. \
A finding is something that was *measured*, not *interpreted*.
- **evidence**: Specific data points, statistics, or metrics that support or \
contradict a claim. Includes p-values, confidence intervals, effect sizes, \
accuracy/F1/BLEU scores, and ablation deltas.
- **contribution**: The paper's core scholarly or practical contribution — a novel \
framework, algorithm, dataset, or tool that did not exist before this work. \
Use only when the text explicitly states what is new.
- **claim**: An author's interpretive assertion, thesis statement, or causal \
argument that goes beyond what the data strictly show. A claim is something \
the authors *argue*, not something they *measured*. Finding vs claim boundary: \
"accuracy improved by 3.2%" is a finding; "this demonstrates the superiority of \
our approach" is a claim.

### Blue tone (analytical / structural)
- **methodology**: Core algorithm, technical innovation, research design, or \
theoretical framework that underpins the work.
- **insight**: Cross-paper interpretation, meta-level implications, novel \
perspective, or synthesis that connects multiple findings.
- **reproducibility**: Reproducibility concerns, data/code availability, \
experimental transparency, or missing details that would hinder replication.
- **experimental_setup**: Experimental design details — datasets, baselines, \
hyperparameters, evaluation protocol, train/test splits, hardware specifications.

### Rose tone (critical evaluation)
- **limitation**: A shortcoming *of this specific paper* — methodological \
weaknesses, data constraints, scope restrictions, or acknowledged caveats. \
Limitation = this-paper shortfall.
- **gap**: A void in the *broader research field* that this paper does not address \
and that represents an opportunity for future work. Gap = field-level void. \
Gap vs limitation boundary: "our model was only tested on English" is a \
limitation; "no prior work has explored this phenomenon in low-resource \
languages" is a gap.
- **assumption**: An implicit premise that the authors rely on but do not \
explicitly validate — distributional assumptions, causal structure, \
generalisability claims, or measurement validity.

## Significance Score (1-5)
- 5: The single most important claim or result of the entire paper (max 2 per paper)
- 4: Top-3 methodological innovation or primary experimental result
- 3: Secondary result, ablation finding, or supporting evidence
- 2: Implementation detail, dataset description, or background context
- 1: Bibliographic or framing context

## Distribution Requirements
Ensure highlights are distributed across the paper's structure:
- Abstract: 1-2 highlights (primary claim)
- Introduction: 1-2 highlights (problem statement, contribution positioning)
- Methods/Methodology: at least 2 highlights
- Results/Experiments: at least 4 highlights (evidence lives here)
- Discussion: at least 2 highlights
- Conclusion: 1 highlight
- Remaining slots: distribute by importance

## Expert Reviewer Commentary

For each highlight, provide commentary from a senior reviewer perspective.

### reviewer_comment — 3-step structured critique (3-4 sentences)
1. **Assessment**: Is this a strength or weakness? State clearly.
2. **Evidence / Counter-argument**: Cross-reference with other parts of the paper, \
or present a devil's advocate challenge.
3. **Constructive suggestion**: For strengths, suggest extensions; for weaknesses, \
propose concrete improvements.

Adapt the critical lens to the colour tone:

**Green tone** (finding/evidence/contribution/claim):
Analyse internal validity, effect size significance, potential confounders. \
Also assess novelty: is this genuinely new relative to prior work cited, \
or does it replicate known findings with marginal variation?

**Blue tone** (methodology/insight/reproducibility/experimental_setup):
Evaluate methodological rigour, differentiation from prior work, \
conditions for reproducibility.

**Rose tone** (limitation/gap/assumption):
Root cause of the limitation, sensitivity if assumption is violated, \
concrete experimental designs to address the gap.

### strength_or_weakness — "strength" or "weakness"
### question_for_authors — One key question a reviewer would ask.

### confidence_level — Evidence grounding (1-5)
Rate how well the paper text supports your commentary:
- 5: Paper provides explicit data/proof directly supporting this highlight
- 4: Strong indirect evidence exists in the paper
- 3: Reasonable inference from available text
- 2: Speculative — paper text is ambiguous on this point
- 1: Commentary relies on background knowledge not present in the paper

### implication — 2-3 sentences covering at least 2 of: theoretical, practical, \
future research implications.

## Language
Write all commentary fields (reviewer_comment, question_for_authors, implication) \
in the **same language as the paper**. If the paper is in English, comment in English. \
If in Korean, comment in Korean.

## Zero-Tolerance Boilerplate
- Do NOT write "This is an interesting approach" — state precisely what differs \
from prior methods and why it matters.
- Do NOT write "Further research is needed" — specify which variables, methods, \
hypotheses, and datasets.
- Do NOT write "This result is meaningful" or "Important contribution" — explain \
what, why, and how it differs from existing work.
- Do NOT write "Additional validation is needed" — specify which experimental \
design, which datasets, and which baselines to compare against.
- Do NOT fabricate author names, paper titles, or numbers not present in the text.

## Output Format
Respond ONLY with the following JSON:
{"paper_type": "EMPIRICAL|THEORETICAL|CLINICAL|SURVEY", \
"highlights": [{"text": "exact paper text", \
"category": "finding|evidence|contribution|claim|methodology|insight|\
reproducibility|experimental_setup|limitation|gap|assumption", \
"reviewer_comment": "3-step critique", \
"strength_or_weakness": "strength|weakness", \
"question_for_authors": "one key question", \
"confidence_level": 4, \
"implication": "multi-dimensional impact", \
"significance": 4, \
"section": "section title"}]}

## Selection Criteria
- Extract the number of highlights as specified in the user prompt.
- Green tone: at least 4 (including at least 1 claim).
- Blue tone: at least 4 (including at least 1 experimental_setup).
- Rose tone: at least 3 (including at least 1 assumption).
- significance 4-5 should be 30-40% of total.
- Distribute evenly from Abstract through Conclusion following the \
Distribution Requirements above.
- No duplicate content.\
"""


# ── PDF text preprocessing ───────────────────────────────────────────

_SECTION_WHITELIST: set[str] = {
    "abstract", "introduction", "background", "related work",
    "methodology", "methods", "approach", "model",
    "experiments", "experiment", "results", "result", "evaluation",
    "discussion", "conclusion", "conclusions", "acknowledgments",
    "acknowledgements", "appendix", "supplementary",
}

# Math unicode block characters (e.g. 𝒜-𝟿, ∀∃∅∇∈∉ etc.)
_MATH_UNICODE_RE = re.compile(
    r'[\u2200-\u22FF\u2A00-\u2AFF\U0001D400-\U0001D7FF]{3,}'
)

# Sequences of 4+ decimal numbers (typical of table data rows)
_TABLE_DATA_RE = re.compile(
    r'(?:\d+\.\d+[\s,;|/&]+){3,}\d+\.\d+'
)


def preprocess_pdf_text(text: str) -> str:
    """Clean raw PDF-extracted text for LLM consumption.

    Performs:
    - References/Bibliography section removal
    - Repeated header/footer pattern removal (preserving section headings)
    - Math unicode artefact replacement
    - Table data normalisation
    - Hyphenated line-break merging
    - Whitespace normalisation
    - Page-number-only line removal
    """
    # 1. Remove References / Bibliography section (and everything after)
    ref_pattern = re.compile(
        r'^\s*(References|Bibliography|REFERENCES|BIBLIOGRAPHY'
        r'|참고\s*문헌|참\s*고\s*문\s*헌)\s*$',
        re.MULTILINE,
    )
    match = ref_pattern.search(text)
    if match:
        text = text[:match.start()]

    # 2. Remove page-number-only lines (e.g. "  12  " or "- 5 -")
    text = re.sub(r'^\s*[-–—]?\s*\d{1,4}\s*[-–—]?\s*$', '', text, flags=re.MULTILINE)

    # 3. Remove repeated header/footer patterns (short lines appearing 3+ times)
    #    but preserve lines whose text matches a known section heading.
    lines = text.split('\n')
    short_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if 3 <= len(stripped) <= 80:
            short_lines.append(stripped)

    counts = Counter(short_lines)
    repeated = {
        line for line, count in counts.items()
        if count >= 3 and line.lower() not in _SECTION_WHITELIST
    }

    if repeated:
        lines = [
            line for line in lines
            if line.strip() not in repeated
        ]
        text = '\n'.join(lines)

    # 4. Replace math unicode artefacts (3+ consecutive math symbols -> [MATH])
    text = _MATH_UNICODE_RE.sub('[MATH]', text)

    # 5. Replace dense table data (4+ consecutive decimal numbers -> [TABLE_DATA])
    text = _TABLE_DATA_RE.sub('[TABLE_DATA]', text)

    # 6. Merge hyphenated line breaks ("meth-\nod" -> "method")
    text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)

    # 7. Normalise consecutive blank lines (max 2)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 8. Normalise consecutive spaces within lines
    text = re.sub(r'[^\S\n]{2,}', ' ', text)

    return text.strip()


# ── Structure-aware truncation ───────────────────────────────────────

_HEADING_RE = re.compile(
    r'^'
    r'(?:'
    r'(?:\d+\.[\d.]*)\s+'            # "1.", "2.1.", "3.2.1."
    r'|(?:[IVX]+\.)\s+'              # "I.", "II.", "IV."
    r'|(?:[A-Z][A-Z\s]{2,})\s*$'    # ALL-CAPS line (e.g. "ABSTRACT")
    r')',
    re.MULTILINE,
)

_KNOWN_SECTIONS_RE = re.compile(
    r'^\s*(Abstract|Introduction|Background|Related\s+Work|'
    r'Methodology|Methods|Approach|Model|Framework|'
    r'Experiments?|Results?|Evaluation|Analysis|'
    r'Discussion|Conclusion|Conclusions|Limitations?|'
    r'Future\s+Work|Acknowledgm|Ethical)\s*$',
    re.IGNORECASE | re.MULTILINE,
)

# Priority map: section keyword -> priority (lower = keep more)
_SECTION_PRIORITY: dict[str, int] = {
    "abstract": 1,
    "introduction": 1,
    "result": 1,
    "experiment": 1,
    "evaluation": 1,
    "discussion": 1,
    "conclusion": 1,
    "method": 2,
    "approach": 2,
    "model": 2,
    "framework": 2,
    "related": 3,
    "background": 3,
    "literature": 3,
    "prior": 3,
}


def _classify_section(heading: str) -> int:
    """Return priority level for a section heading (1=high, 3=low)."""
    lower = heading.lower()
    for keyword, priority in _SECTION_PRIORITY.items():
        if keyword in lower:
            return priority
    return 2  # default: medium priority


def _detect_paper_type_hint(text: str) -> str:
    """Detect paper type from title and first 2000 chars for keep_ratio tuning.

    Returns one of: 'survey', 'theoretical', 'empirical'.
    """
    probe = text[:2000].lower()
    survey_kw = ["survey", "review", "meta-analysis", "systematic review",
                 "literature review"]
    theory_kw = ["theorem", "proof", "lemma", "corollary", "proposition"]

    if any(kw in probe for kw in survey_kw):
        return "survey"
    if any(kw in probe for kw in theory_kw):
        return "theoretical"
    return "empirical"


def truncate_paper_text(text: str, max_chars: int = 40000) -> str:
    """Truncate paper text with structure-aware prioritisation.

    Detects section headings via heuristics (numbered/all-caps headings and
    known section names) and inserts [SECTION: title] markers. When text
    exceeds *max_chars*, truncates low-priority sections with ratios that
    adapt to the detected paper type (survey, theoretical, empirical).

    Args:
        text: Preprocessed paper text.
        max_chars: Maximum character budget for the output.

    Returns:
        Truncated text with [SECTION: ...] markers inserted.
    """
    # Detect section headings
    lines = text.split('\n')
    sections: list[tuple[str, int, int]] = []  # (heading, start_line, priority)
    section_start_indices: list[int] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Heuristic: numbered heading, ALL-CAPS line, or known section name
        is_heading = False
        if _HEADING_RE.match(stripped):
            is_heading = True
        elif stripped.isupper() and 3 <= len(stripped) <= 60:
            is_heading = True
        elif _KNOWN_SECTIONS_RE.match(stripped):
            is_heading = True

        if is_heading:
            priority = _classify_section(stripped)
            sections.append((stripped, i, priority))
            section_start_indices.append(i)

    # If no sections detected, just truncate plainly
    if not sections:
        if len(text) <= max_chars:
            return text
        cutoff = text.rfind('\n', 0, max_chars)
        if cutoff < max_chars * 0.6:
            cutoff = max_chars
        return text[:cutoff]

    # Build section content blocks
    section_blocks: list[dict] = []
    for idx, (heading, start_line, priority) in enumerate(sections):
        end_line = sections[idx + 1][1] if idx + 1 < len(sections) else len(lines)
        content_lines = lines[start_line + 1:end_line]
        content = '\n'.join(content_lines).strip()
        section_blocks.append({
            "heading": heading,
            "content": content,
            "priority": priority,
            "original_length": len(content),
        })

    # Preamble (content before first section)
    preamble = '\n'.join(lines[:sections[0][1]]).strip()

    # Check total length
    total = len(preamble) + sum(
        len(f"\n[SECTION: {b['heading']}]\n") + b["original_length"]
        for b in section_blocks
    )

    if total <= max_chars:
        # No truncation needed, just add markers
        parts: list[str] = []
        if preamble:
            parts.append(preamble)
        for block in section_blocks:
            parts.append(f"\n[SECTION: {block['heading']}]")
            if block["content"]:
                parts.append(block["content"])
        return '\n'.join(parts)

    # Truncation needed — choose keep_ratios based on paper type
    paper_hint = _detect_paper_type_hint(text)
    if paper_hint == "survey":
        # Surveys: keep Methods heavily (coverage analysis lives there)
        keep_ratios: dict[int, float] = {1: 1.0, 2: 0.6, 3: 0.3}
    elif paper_hint == "theoretical":
        # Theoretical: keep Methods fully (proofs are critical)
        keep_ratios = {1: 1.0, 2: 1.0, 3: 0.3}
    else:
        # Empirical (default): moderate Methods truncation
        keep_ratios = {1: 1.0, 2: 0.4, 3: 0.3}

    for block in section_blocks:
        ratio = keep_ratios.get(block["priority"], 0.5)
        if ratio < 1.0:
            keep_chars = int(block["original_length"] * ratio)
            if keep_chars < block["original_length"]:
                # Cut at a sentence or line boundary
                cutoff = block["content"].rfind('. ', 0, keep_chars)
                if cutoff < keep_chars * 0.5:
                    cutoff = block["content"].rfind('\n', 0, keep_chars)
                if cutoff < keep_chars * 0.3:
                    cutoff = keep_chars
                block["content"] = (
                    block["content"][:cutoff + 1].rstrip() + "\n[...]"
                )

    # Assemble
    parts = []
    if preamble:
        parts.append(preamble)
    for block in section_blocks:
        parts.append(f"\n[SECTION: {block['heading']}]")
        if block["content"]:
            parts.append(block["content"])

    result = '\n'.join(parts)

    # Final hard truncation if still over budget
    if len(result) > max_chars:
        cutoff = result.rfind('\n', 0, max_chars)
        if cutoff < max_chars * 0.6:
            cutoff = max_chars
        result = result[:cutoff]

    return result


# ── PDF highlight generation ─────────────────────────────────────────

def generate_pdf_highlights(
    text: str,
    title: str,
    client: object,
) -> list[dict]:
    """Generate highlights from raw PDF paper text.

    Pipeline: preprocess -> truncate -> determine dynamic highlight count
    -> LLM call with PDF-specific prompt.

    Args:
        text: Raw text extracted from PDF (e.g. via pdfjs).
        title: Paper title for context.
        client: An OpenAI-compatible client instance.

    Returns:
        A list of highlight dicts as returned by the LLM (unprocessed).

    Raises:
        openai.APITimeoutError: If the LLM call times out.
        openai.RateLimitError: If the API rate limit is hit.
        openai.APIError: On other API errors.
        ValueError: If the LLM returns invalid JSON.
    """
    # Step 1: Preprocess
    cleaned = preprocess_pdf_text(text)

    # Step 2: Structure-aware truncation
    max_chars = 40000
    truncated = truncate_paper_text(cleaned, max_chars=max_chars)

    # Step 3: Dynamic highlight range based on text length
    char_count = len(truncated)
    if char_count < 10000:
        highlight_range = "10-15"
    elif char_count < 25000:
        highlight_range = "15-20"
    else:
        highlight_range = "20-25"

    # Step 4: Build prompt
    topic_context = f"[Paper Title: {title}]\n\n" if title else ""
    model = "gpt-4.1"
    temperature = 0.2
    user_prompt = (
        f"{topic_context}"
        f"Analyse the following academic paper and extract "
        f"**{highlight_range} highlights**.\n\n"
        f"---\n{truncated}\n---"
    )

    # Step 5: Check LLM cache
    cached = get_cached(PDF_HIGHLIGHT_SYSTEM_PROMPT, user_prompt, model, temperature)
    if cached is not None:
        logger.info("Using cached LLM response for PDF highlight")
        raw = cached
    else:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            timeout=180,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": PDF_HIGHLIGHT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        logger.info("PDF highlight token usage: %s", response.usage)
        raw = response.choices[0].message.content or "{}"

        # Store in cache
        set_cache(PDF_HIGHLIGHT_SYSTEM_PROMPT, user_prompt, model, temperature, raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("LLM returned invalid JSON for PDF highlights")

    # Extract paper_type for logging
    paper_type: str = parsed.get("paper_type", "UNKNOWN")
    highlights: list[dict] = parsed.get("highlights", [])
    logger.info(
        "Detected paper type: %s, highlights: %d",
        paper_type,
        len(highlights),
    )

    return highlights
