"""
Poster Composition Agent

포스터 HTML 생성 전에 콘텐츠-figure 통합 레이아웃을 설계하는 에이전트.

기존 파이프라인의 post-hoc injection 문제를 해결한다:
- 기존: HTML 생성 → _inject_visuals_into_poster() 로 figure를 </body> 앞에 추가
- 개선: 생성 전에 콘텐츠-figure 매핑을 결정 → Gemini가 figure를 제자리에 배치
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional

from app.DeepAgent.poster.sanitizer import escape_text, sanitize_poster_markup

from .poster_content_agent import ExtractedContent
from .poster_visual_agent import PosterVisualAgent

logger = logging.getLogger(__name__)


# ── 색상 팔레트 ─────────────────────────────────────────────────────────────
_PAPER_COLORS = [
    '#2563eb',  # blue
    '#7c3aed',  # violet
    '#059669',  # emerald
    '#ea580c',  # orange
    '#0891b2',  # cyan
    '#d97706',  # amber
]


# ── 열거형 ─────────────────────────────────────────────────────────────────


class SectionRole(str, Enum):
    """포스터 섹션의 역할"""
    HEADER = "header"
    OVERVIEW = "overview"       # 초록 + 배경 + 전체 파이프라인 다이어그램
    PAPER_CARD = "paper_card"   # 개별 논문 (방법론 텍스트 + 논문별 다이어그램)
    COMPARISON = "comparison"   # 비교 분석 테이블 + 결과 차트
    FINDINGS = "findings"       # 핵심 발견 + 기여
    CONCLUSION = "conclusion"   # 결론


# ── 데이터 구조 ─────────────────────────────────────────────────────────────


@dataclass
class FigurePlacement:
    """섹션에 배치할 figure 정보"""
    figure_index: int       # autofigure_svgs 또는 figures 리스트의 인덱스
    source: str             # "autofigure" | "paper_figure" | "generated_diagram"
    paper_title: str        # 관련 논문 제목
    placement: str          # "inline" | "below_text" | "side_by_side"
    caption: str            # figure 캡션


@dataclass
class CompositionSection:
    """포스터 구성의 한 섹션"""
    role: SectionRole
    title: str
    text_content: str                               # 섹션 텍스트 (마크다운)
    figures: List[FigurePlacement] = field(default_factory=list)
    subsections: List['CompositionSection'] = field(default_factory=list)
    color_code: str = ""                            # 논문별 색상 코드
    grid_span: int = 1                              # CSS grid span


@dataclass
class PosterComposition:
    """전체 포스터 구성 설계"""
    title: str
    subtitle: str
    keywords: List[str]
    sections: List[CompositionSection]
    grid_columns: int       # 전체 그리드 컬럼 수 (2 or 3)
    total_figures: int      # 배치된 총 figure 수
    total_text_sections: int  # 텍스트 섹션 수


# ── 에이전트 ────────────────────────────────────────────────────────────────


class PosterCompositionAgent:
    """심층 리뷰 콘텐츠와 생성된 figure를 통합하여 포스터 구성을 설계한다.

    기존 파이프라인에서는 포스터 HTML 생성 후 figure를 삽입(post-hoc injection)했으나,
    이 에이전트는 생성 전에 콘텐츠-figure 매핑을 결정하여 통합된 레이아웃을 보장한다.

    사용 예::

        agent = PosterCompositionAgent()
        composition = agent.design(content, autofigure_svgs, figures)
        prompt = agent.to_gemini_prompt(composition, content)
        # Gemini 호출 후:
        final_html = agent.inject_figures_by_composition(
            raw_html, composition, autofigure_svgs, figures
        )
    """

    # ── 공개 API ────────────────────────────────────────────────────────────

    def design(
        self,
        content: ExtractedContent,
        autofigure_svgs: List[Dict[str, Any]],
        figures: List[Dict[str, Any]],
    ) -> PosterComposition:
        """콘텐츠와 figure 데이터로부터 포스터 구성을 설계한다.

        Args:
            content: 리포트에서 추출된 구조화 콘텐츠.
            autofigure_svgs: PaperBanana/AutoFigure가 생성한 SVG 리스트.
                각 원소: {"paper_title": str, "svg_content": str, "figure_png_b64": str}
            figures: 논문 원문에서 추출된 figure 리스트.
                각 원소: {"image_base64": str, "caption": str, "paper_title": str, ...}

        Returns:
            PosterComposition: 섹션-figure 매핑이 완성된 포스터 구성.
        """
        autofigure_svgs = autofigure_svgs or []
        figures = figures or []

        paper_analyses = list(content.paper_analyses or [])

        # autofigure 인덱스별 할당 추적 (중복 배치 방지)
        assigned_autofigures: set[int] = set()
        # paper figure 인덱스별 할당 추적
        assigned_paper_figures: set[int] = set()

        sections: List[CompositionSection] = []

        # 1. HEADER
        sections.append(self._build_header(content))

        # 2. OVERVIEW
        overview_autofigure = self._find_overview_autofigure(autofigure_svgs)
        overview_section = self._build_overview(content, autofigure_svgs, overview_autofigure)
        if overview_autofigure is not None:
            assigned_autofigures.add(overview_autofigure)
        sections.append(overview_section)

        # 3. PAPER_CARD (논문별, 최대 6개)
        paper_cards = self._build_paper_cards(
            content,
            paper_analyses,
            autofigure_svgs,
            figures,
            assigned_autofigures,
            assigned_paper_figures,
        )
        sections.extend(paper_cards)

        # 4. COMPARISON
        remaining_autofigures = [
            i for i in range(len(autofigure_svgs))
            if i not in assigned_autofigures
        ]
        comparison_section = self._build_comparison(
            content, autofigure_svgs, remaining_autofigures
        )
        assigned_autofigures.update(remaining_autofigures)
        sections.append(comparison_section)

        # 5. FINDINGS
        sections.append(self._build_findings(content))

        # 6. CONCLUSION
        remaining_paper_figures = [
            i for i in range(len(figures))
            if i not in assigned_paper_figures
        ]
        sections.append(self._build_conclusion(content, figures, remaining_paper_figures))

        # 그리드 컬럼 결정
        num_paper_cards = len(paper_cards)
        grid_columns = 3 if num_paper_cards >= 3 else 2

        # 배치된 figure 총 수 집계
        total_figures = sum(len(s.figures) for s in sections)
        total_text_sections = sum(1 for s in sections if s.role != SectionRole.HEADER)

        logger.info(
            "PosterComposition 설계 완료: 섹션=%d, figure=%d, grid=%d열",
            len(sections),
            total_figures,
            grid_columns,
        )

        return PosterComposition(
            title=content.title,
            subtitle=content.subtitle,
            keywords=content.keywords[:8],
            sections=sections,
            grid_columns=grid_columns,
            total_figures=total_figures,
            total_text_sections=total_text_sections,
        )

    def to_gemini_prompt(
        self,
        composition: PosterComposition,
        content: ExtractedContent,
    ) -> str:
        """PosterComposition을 Gemini용 HTML 생성 프롬프트로 변환한다.

        각 섹션의 텍스트 + figure 배치 지시를 인라인으로 포함하므로,
        Gemini가 figure를 관련 섹션 카드 안에 직접 배치할 수 있다.

        figure 데이터는 <!-- EMBED_SVG_{n} --> / <!-- EMBED_FIGURE_{n} --> 플레이스홀더로
        삽입되며, inject_figures_by_composition()이 실제 내용으로 교체한다.

        Args:
            composition: design()이 반환한 포스터 구성.
            content: 원본 ExtractedContent (comparison_tables 등 추가 데이터용).

        Returns:
            Gemini에 전달할 완성된 프롬프트 문자열.
        """
        section_directives = self._build_section_directives(composition)
        comparison_tables_block = self._build_comparison_tables_block(content)
        keywords_str = ", ".join(composition.keywords)
        paper_count = len(content.paper_analyses or [])
        ref_count = len(getattr(content, 'references', []) or [])
        figure_count = composition.total_figures

        return f"""당신은 NeurIPS/ICML 학회 포스터 디자이너입니다.
아래 지정된 섹션 구조와 figure 배치 지시를 **정확히** 따라 self-contained HTML 학회지 포스터를 생성하세요.

## 핵심 원칙
1. **figure는 반드시 관련 섹션 카드 안에 배치** — 별도 "Additional Visualizations" 섹션 생성 금지
2. **<!-- EMBED_SVG_N --> 플레이스홀더를 그대로 유지** — 실제 SVG 데이터는 후처리에서 교체됨
3. **<!-- EMBED_FIGURE_N --> 플레이스홀더를 그대로 유지** — 실제 이미지는 후처리에서 교체됨
4. 논문별 색상 코드를 카드 border-left, evidence chip, caption accent에 일관되게 적용
5. 각 논문 카드 안의 다이어그램은 해당 논문의 방법/데이터/모델/결과명을 써서 구체화하고 범용 입출력 흐름명, 익명 지표명, 익명 방법명 금지
6. 외부 font/CDN/image/script/style URL은 절대 금지. 시스템 폰트와 인라인 CSS만 사용

## 포스터 메타데이터
- **제목**: {composition.title}
- **부제목**: {composition.subtitle}
- **키워드**: {keywords_str}
- **논문 수**: {paper_count}
- **참고문헌 수**: {ref_count}
- **Figure 수**: {figure_count}
- **디자인 계약**: Editorial Evidence Wall, 4:3/A3 landscape, 12-column responsive grid

## 섹션별 콘텐츠 및 Figure 배치 지시

이 포스터는 {composition.total_text_sections}개 섹션으로 구성됩니다.
각 섹션의 콘텐츠와 figure 배치를 정확히 따르세요.

{section_directives}

{comparison_tables_block}

## 포스터 HTML 구조

```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{composition.title}</title>
  <style>인라인 CSS만 사용</style>
</head>
<body>
<main class="poster poster--a3-landscape">
<header class="poster-header">
  <p class="kicker">Academic Review Poster</p>
  <h1 class="poster-title title-ko title-long">제목</h1>
  <p class="poster-subtitle">부제목</p>
  <div class="evidence-meta">
    <span>papers {paper_count}</span><span>refs {ref_count}</span><span>figures {figure_count}</span>
  </div>
</header>
<aside class="thesis-strip">첫 번째 핵심 발견 기반 thesis 문장</aside>
<section class="overview-section grid-span-12">
  <div class="overview-copy"><h2>Research Frame</h2><p>초록+배경</p></div>
  <figure><!-- EMBED_SVG_N 또는 의미 있는 인라인 SVG --><figcaption>연구 파이프라인 다이어그램</figcaption></figure>
</section>
<section class="papers-section grid-span-12">
  <h2>Evidence Papers</h2>
  <article class="paper-card">논문별 텍스트 + figure/figcaption</article>
</section>
<section class="comparison-section grid-span-8">
  비교 테이블 + 결과 차트
</section>
<section class="findings-section grid-span-4">
  핵심 발견 + 기여 목록
</section>
<section class="conclusion-section grid-span-12">
  결론
</section>
</main>
</body>
</html>
```

## CSS 규칙

```css
:root {{
  --font-main: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", "Apple SD Gothic Neo", Arial, sans-serif;
  --ink: #172033;
  --muted: #596579;
  --paper: #fffdf8;
  --panel: #ffffff;
  --line: #d9dee8;
  --blue: #2457a6;
  --green: #0f766e;
  --amber: #b45309;
  --red: #b91c1c;
  --gap: 10px;
  --radius: 8px;
}}
@page {{
  size: A3 landscape;
  margin: 0;
}}
* {{ box-sizing: border-box; }}
html, body {{
  margin: 0;
  background: #e7e9ee;
  color: var(--ink);
  font-family: var(--font-main);
  word-break: keep-all;
  overflow-wrap: anywhere;
}}
.poster {{
  width: min(100%, 1580px);
  aspect-ratio: 4 / 3;
  min-height: 900px;
  margin: 0 auto;
  padding: 12px;
  background: var(--paper);
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  grid-auto-rows: min-content;
  gap: var(--gap);
}}
.poster-header, .thesis-strip, section {{
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--panel);
  padding: 16px 18px;
  break-inside: avoid;
}}
.poster-header {{
  grid-column: 1 / -1;
  background: #172033;
  color: white;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px 20px;
}}
.poster-title {{
  font-size: clamp(2rem, 3vw, 3.4rem);
  line-height: 1.08;
  margin: 0;
}}
.title-long {{
  font-size: clamp(1.55rem, 2.35vw, 2.75rem);
}}
.title-ko {{
  letter-spacing: 0;
}}
.evidence-meta {{
  display: flex;
  gap: 20px;
  align-items: start;
  font-size: 0.78rem;
  text-transform: uppercase;
}}
.thesis-strip {{
  grid-column: 1 / -1;
  border-left: 6px solid var(--green);
  font-size: 1.05rem;
  font-weight: 700;
}}
.grid-span-4 {{ grid-column: span 4; }}
.grid-span-8 {{ grid-column: span 8; }}
.grid-span-12 {{ grid-column: 1 / -1; }}
.papers-section {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}}
.papers-section > h2 {{
  grid-column: 1 / -1;
}}
.paper-card {{
  border-left: 4px solid currentColor;
  padding-left: 12px;
  break-inside: avoid;
 }}
h2 {{
  margin: 0 0 10px;
  font-size: 1.05rem;
  line-height: 1.2;
  color: var(--blue);
}}
h3 {{
  margin: 0 0 8px;
  font-size: 0.92rem;
  line-height: 1.35;
}}
p, li, td, th {{
  font-size: 0.82rem;
  line-height: 1.45;
}}
figure {{
  margin: 10px 0;
  break-inside: avoid;
}}
figure img, figure svg {{
  width: 100%;
  height: auto;
  max-height: 180px;
  object-fit: contain;
  border: 1px solid var(--line);
  border-radius: 6px;
}}
figcaption {{
  margin-top: 5px;
  color: var(--muted);
  font-size: 0.72rem;
  line-height: 1.35;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}}
th, td {{
  padding: 6px 7px;
  border: 1px solid var(--line);
  vertical-align: top;
}}
th {{ background: #eef2f7; }}
@media (max-width: 1199px) {{
  .poster {{ aspect-ratio: auto; grid-template-columns: repeat(8, minmax(0, 1fr)); }}
  .grid-span-4, .grid-span-8 {{ grid-column: 1 / -1; }}
}}
@media (max-width: 760px) {{
  body {{ background: var(--paper); }}
  .poster {{ width: 100%; min-height: 0; padding: 12px; grid-template-columns: 1fr; }}
  .poster-header, .thesis-strip, section, .grid-span-4, .grid-span-8, .grid-span-12 {{ grid-column: 1 / -1; }}
  .papers-section {{ grid-template-columns: 1fr; }}
}}
@media print {{
  html, body {{ width: 420mm; height: 297mm; overflow: hidden; }}
  body {{ background: white; padding: 0; display: flex; justify-content: center; }}
  .poster {{ width: 396mm; height: 297mm; min-height: 297mm; max-width: none; box-shadow: none; overflow: hidden; }}
  * {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  section, article, figure, table {{ break-inside: avoid; }}
}}
```

## 출력 규칙
- <!DOCTYPE html>로 시작하는 완전한 HTML만 출력 (설명 텍스트, 코드블록 마커 제외)
- <!-- EMBED_SVG_N --> 와 <!-- EMBED_FIGURE_N --> 플레이스홀더는 반드시 원문 그대로 포함
- figure 플레이스홀더는 반드시 `<figure>` 안에 두고 바로 뒤에 의미 있는 `<figcaption>`을 제공
- 별도 "추가 시각화" 또는 "Additional Visualizations" 섹션 생성 금지
- overview 12컬럼 대형 evidence-flow 밴드, papers 12컬럼 3열 evidence wall, 하단 comparison 6컬럼/findings 3컬럼/conclusion 3컬럼 배치 준수
- 논문 원문에 실제 정량 결과가 있으면 실제 metric label과 단위/비교 맥락을 붙여 evidence panel 제목 옆에 강조하되 수치를 새로 만들지 마세요
- 추출된 limitations는 숨기거나 잘라내지 말고 각 evidence panel에 짧고 명시적으로 노출하세요
- thesis strip에는 생성일, 합성 상태, 입력 논문 수를 안전한 provenance metadata로 표시하세요
- 첫 번째 key finding을 thesis strip으로 재서술
- 제목에는 긴 한국어/영문 제목 대응 class (`title-ko`, `title-en`, `title-long`)를 적용

## 절대 금지 사항
- 원격 URL 기반 이미지 절대 사용 금지
- Wikipedia, Google, arXiv 등 외부 서비스의 로고/아이콘/워터마크 삽입 금지
- 이미지는 반드시 data:image/... base64 또는 인라인 SVG만 허용
- 폰트 CDN 포함 어떤 외부 URL도 참조 금지
- 장식용 아이콘, 이모지 이미지, 클립아트 삽입 금지"""

    def inject_figures_by_composition(
        self,
        poster_html: str,
        composition: PosterComposition,
        autofigure_svgs: List[Dict[str, Any]],
        figures: List[Dict[str, Any]],
    ) -> str:
        """HTML 내 플레이스홀더를 실제 figure 콘텐츠로 교체한다.

        post-hoc injection(</body> 앞 추가)과 달리, 이미 섹션 카드 안에 위치한
        <!-- EMBED_SVG_N --> / <!-- EMBED_FIGURE_N --> 를 단순 문자열 교체로 처리한다.

        Args:
            poster_html: Gemini가 생성한 HTML (플레이스홀더 포함).
            composition: design()이 반환한 포스터 구성 (메타 정보용).
            autofigure_svgs: AutoFigure SVG 리스트.
            figures: 논문 원문 figure 리스트.

        Returns:
            플레이스홀더가 실제 콘텐츠로 교체된 HTML.
        """
        autofigure_svgs = autofigure_svgs or []
        figures = figures or []

        # SVG 플레이스홀더 교체
        for idx, af in enumerate(autofigure_svgs):
            placeholder = f"<!-- EMBED_SVG_{idx} -->"
            if placeholder not in poster_html:
                continue
            svg_content = (af.get('svg_content') or '').strip()
            if not svg_content:
                # SVG가 없으면 폴백: figure_png_b64 사용
                b64 = af.get('figure_png_b64', '')
                if b64:
                    img_html = (
                        f'<figure class="embed-autofigure" style="margin:12px 0;">'
                        f'<img src="data:image/png;base64,{self._esc(b64)}" '
                        f'alt="{self._esc(af.get("paper_title", ""))}" '
                        f'style="width:100%;height:auto;border-radius:8px;" />'
                        f'<figcaption style="font-size:0.78rem;color:#64748b;margin-top:6px;">'
                        f'{self._esc(af.get("paper_title", "자동 생성 overview figure"))}'
                        f'</figcaption>'
                        f'</figure>'
                    )
                    poster_html = poster_html.replace(placeholder, img_html)
                else:
                    poster_html = poster_html.replace(placeholder, '')
                continue

            # SVG를 반응형으로 래핑
            if not svg_content.startswith('<svg'):
                svg_content = f'<svg>{svg_content}</svg>'
            svg_content = sanitize_poster_markup(svg_content)
            svg_wrapped = (
                f'<figure class="embed-autofigure" style="width:100%;margin:12px 0;">'
                f'{svg_content}'
                f'<figcaption style="font-size:0.78rem;color:#64748b;margin-top:6px;">'
                f'{self._esc(af.get("paper_title", "자동 생성 연구 다이어그램"))}'
                f'</figcaption>'
                f'</figure>'
            )
            poster_html = poster_html.replace(placeholder, svg_wrapped)

        # paper figure 플레이스홀더 교체
        for idx, fig in enumerate(figures):
            placeholder = f"<!-- EMBED_FIGURE_{idx} -->"
            if placeholder not in poster_html:
                continue
            if isinstance(fig, dict):
                b64 = fig.get('image_base64', '')
                caption = fig.get('caption', '')
                mime = fig.get('mime_type', 'image/png')
            else:
                b64 = getattr(fig, 'image_base64', '')
                caption = getattr(fig, 'caption', '')
                mime = getattr(fig, 'mime_type', 'image/png')

            if not b64:
                poster_html = poster_html.replace(placeholder, '')
                continue

            if mime not in {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}:
                mime = 'image/png'

            img_html = (
                f'<figure class="embed-figure" style="margin:12px 0;">'
                f'<img src="data:{self._esc(mime)};base64,{self._esc(b64)}" '
                f'alt="{self._esc(caption)}" '
                f'style="width:100%;height:auto;border-radius:8px;" />'
                f'<figcaption style="font-size:0.78rem;color:#64748b;margin-top:6px;">'
                f'{self._esc(caption)}'
                f'</figcaption>'
                f'</figure>'
            )
            poster_html = poster_html.replace(placeholder, img_html)

        logger.debug("inject_figures_by_composition 완료")
        return poster_html

    # ── 섹션 빌더 ───────────────────────────────────────────────────────────

    def _build_header(self, content: ExtractedContent) -> CompositionSection:
        """HEADER 섹션 생성"""
        return CompositionSection(
            role=SectionRole.HEADER,
            title=content.title,
            text_content=f"{content.title}\n{content.subtitle}",
            grid_span=2,
        )

    def _build_overview(
        self,
        content: ExtractedContent,
        autofigure_svgs: List[Dict[str, Any]],
        overview_af_idx: Optional[int],
    ) -> CompositionSection:
        """OVERVIEW 섹션 생성 (초록 + 배경 + 전체 파이프라인 figure)"""
        text_parts = []
        if content.abstract:
            text_parts.append(f"**초록**\n{content.abstract}")
        if content.motivation:
            text_parts.append(f"**배경/동기**\n{content.motivation}")

        fig_placements: List[FigurePlacement] = []
        if overview_af_idx is not None:
            af = autofigure_svgs[overview_af_idx]
            fig_placements.append(FigurePlacement(
                figure_index=overview_af_idx,
                source="autofigure",
                paper_title=af.get('paper_title', 'Overall Methodology'),
                placement="below_text",
                caption="전체 연구 파이프라인 다이어그램",
            ))

        return CompositionSection(
            role=SectionRole.OVERVIEW,
            title="연구 개요",
            text_content="\n\n".join(text_parts),
            figures=fig_placements,
            grid_span=2,
        )

    def _build_paper_cards(
        self,
        content: ExtractedContent,
        paper_analyses: List[Dict[str, Any]],
        autofigure_svgs: List[Dict[str, Any]],
        figures: List[Dict[str, Any]],
        assigned_autofigures: set,
        assigned_paper_figures: set,
    ) -> List[CompositionSection]:
        """논문별 PAPER_CARD 섹션 목록 생성 (최대 6개)"""
        cards: List[CompositionSection] = []

        for i, paper in enumerate(paper_analyses[:6]):
            title = (paper.get('title') or '').strip() or 'Untitled evidence source'
            color = _PAPER_COLORS[i % len(_PAPER_COLORS)]

            # 텍스트 콘텐츠 조합
            text_parts = []
            methodology = self._poster_excerpt(paper.get('methodology') or '', 150)
            contributions = self._poster_excerpt(paper.get('contributions') or '', 130)
            results = self._poster_excerpt(paper.get('results') or '', 140)
            limitations = self._poster_excerpt(paper.get('limitations') or '', 120)

            if methodology:
                text_parts.append(f"**핵심 방법론** {methodology}")
            if contributions:
                text_parts.append(f"**주요 기여** {contributions}")
            if results:
                text_parts.append(f"**실험 결과** {results}")
            if limitations:
                text_parts.append(f"**한계** {limitations}")

            fig_placements: List[FigurePlacement] = []

            # autofigure 매칭
            af_idx = self._match_autofigure_to_paper(title, autofigure_svgs, assigned_autofigures)
            if af_idx is not None:
                assigned_autofigures.add(af_idx)
                fig_placements.append(FigurePlacement(
                    figure_index=af_idx,
                    source="autofigure",
                    paper_title=title,
                    placement="inline",
                    caption=f"{title} — 아키텍처 다이어그램",
                ))

            # paper figure 매칭
            pf_idx = self._match_paper_figure_to_paper(title, figures, assigned_paper_figures)
            if pf_idx is not None:
                assigned_paper_figures.add(pf_idx)
                fig = figures[pf_idx]
                caption = (
                    fig.get('caption', '') if isinstance(fig, dict)
                    else getattr(fig, 'caption', '')
                )
                fig_placements.append(FigurePlacement(
                    figure_index=pf_idx,
                    source="paper_figure",
                    paper_title=title,
                    placement="below_text",
                    caption=caption or f"{title} — Figure",
                ))

            cards.append(CompositionSection(
                role=SectionRole.PAPER_CARD,
                title=title,
                text_content="\n\n".join(text_parts),
                figures=fig_placements,
                color_code=color,
                grid_span=1,
            ))

        return cards

    def _build_comparison(
        self,
        content: ExtractedContent,
        autofigure_svgs: List[Dict[str, Any]],
        remaining_af_indices: List[int],
    ) -> CompositionSection:
        """COMPARISON 섹션 생성 (비교 테이블 + 미할당 autofigure)"""
        tables = content.comparison_tables or []
        text_content = "\n\n".join(tables[:3]) if tables else "논문 간 비교 분석"

        fig_placements: List[FigurePlacement] = []
        for af_idx in remaining_af_indices:
            af = autofigure_svgs[af_idx]
            fig_placements.append(FigurePlacement(
                figure_index=af_idx,
                source="autofigure",
                paper_title=af.get('paper_title', ''),
                placement="side_by_side",
                caption=af.get('paper_title', '') + " — 비교 다이어그램",
            ))

        return CompositionSection(
            role=SectionRole.COMPARISON,
            title="비교 분석",
            text_content=text_content,
            figures=fig_placements,
            grid_span=2,
        )

    def _build_findings(self, content: ExtractedContent) -> CompositionSection:
        """FINDINGS 섹션 생성"""
        findings_lines = [f"- {f}" for f in content.key_findings[:8]]
        contributions_lines = [f"- {c}" for c in content.contributions[:5]]

        text_parts = []
        if findings_lines:
            text_parts.append("**핵심 발견**\n" + "\n".join(findings_lines))
        if contributions_lines:
            text_parts.append("**주요 기여**\n" + "\n".join(contributions_lines))

        return CompositionSection(
            role=SectionRole.FINDINGS,
            title="핵심 발견 및 기여",
            text_content="\n\n".join(text_parts) or "핵심 발견 내용",
            grid_span=2,
        )

    def _build_conclusion(
        self,
        content: ExtractedContent,
        figures: List[Dict[str, Any]],
        remaining_pf_indices: List[int],
    ) -> CompositionSection:
        """CONCLUSION 섹션 생성 (결론 + 미할당 paper figures)"""
        fig_placements: List[FigurePlacement] = []
        for pf_idx in remaining_pf_indices[:2]:  # 결론에는 최대 2개만
            fig = figures[pf_idx]
            caption = (
                fig.get('caption', '') if isinstance(fig, dict)
                else getattr(fig, 'caption', '')
            )
            fig_placements.append(FigurePlacement(
                figure_index=pf_idx,
                source="paper_figure",
                paper_title=(
                    fig.get('paper_title', '') if isinstance(fig, dict)
                    else getattr(fig, 'paper_title', '')
                ),
                placement="below_text",
                caption=caption or "Figure",
            ))

        return CompositionSection(
            role=SectionRole.CONCLUSION,
            title="결론",
            text_content=content.conclusion or "본 분석을 통해 해당 분야의 주요 연구 동향을 확인하였습니다.",
            figures=fig_placements,
            grid_span=2,
        )

    # ── 매칭 헬퍼 ───────────────────────────────────────────────────────────

    def _find_overview_autofigure(
        self, autofigure_svgs: List[Dict[str, Any]]
    ) -> Optional[int]:
        """'Overall Methodology' 또는 유사 제목의 autofigure 인덱스를 반환한다."""
        overview_keywords = {'overall', 'pipeline', 'overview', 'methodology', 'framework'}
        for i, af in enumerate(autofigure_svgs):
            pt = (af.get('paper_title') or '').lower()
            if any(kw in pt for kw in overview_keywords):
                return i
        return None

    def _match_autofigure_to_paper(
        self,
        paper_title: str,
        autofigure_svgs: List[Dict[str, Any]],
        already_assigned: set,
    ) -> Optional[int]:
        """autofigure_svgs 중 paper_title에 가장 잘 맞는 인덱스를 반환한다.

        Args:
            paper_title: 논문 제목.
            autofigure_svgs: 전체 autofigure 리스트.
            already_assigned: 이미 할당된 인덱스 집합.

        Returns:
            매칭된 인덱스 또는 None.
        """
        return self._match_figure_to_paper(
            paper_title,
            [af.get('paper_title', '') for af in autofigure_svgs],
            already_assigned,
        )

    def _match_paper_figure_to_paper(
        self,
        paper_title: str,
        figures: List[Dict[str, Any]],
        already_assigned: set,
    ) -> Optional[int]:
        """figures 중 paper_title에 가장 잘 맞는 인덱스를 반환한다."""
        figure_titles = []
        for fig in figures:
            if isinstance(fig, dict):
                figure_titles.append(fig.get('paper_title', ''))
            else:
                figure_titles.append(getattr(fig, 'paper_title', ''))
        return self._match_figure_to_paper(paper_title, figure_titles, already_assigned)

    def _match_figure_to_paper(
        self,
        paper_title: str,
        candidate_titles: List[str],
        already_assigned: set,
    ) -> Optional[int]:
        """후보 제목 리스트에서 paper_title에 매칭되는 인덱스를 퍼지 탐색한다.

        매칭 전략 (우선순위 순):
        1. 정확 일치 (대소문자 무시)
        2. 후보 제목이 paper_title의 부분 문자열
        3. paper_title이 후보 제목의 부분 문자열
        4. 단어 교집합 ≥ 2개

        Args:
            paper_title: 매칭 대상 논문 제목.
            candidate_titles: 후보 제목 리스트 (인덱스 순서 보존).
            already_assigned: 건너뛸 인덱스 집합.

        Returns:
            매칭된 인덱스 또는 None.
        """
        pt_lower = paper_title.lower().strip()
        pt_words = set(pt_lower.split())

        best_idx: Optional[int] = None
        best_score = 0

        for i, candidate in enumerate(candidate_titles):
            if i in already_assigned:
                continue
            ct_lower = (candidate or '').lower().strip()
            if not ct_lower:
                continue

            # 전략 1: 정확 일치
            if pt_lower == ct_lower:
                return i

            # 전략 2: 부분 문자열 포함 (양방향)
            score = 0
            if ct_lower in pt_lower or pt_lower in ct_lower:
                score = 3

            # 전략 3: 단어 교집합
            if score == 0:
                ct_words = set(ct_lower.split())
                common = pt_words & ct_words
                # 불용어 제외 (단어 길이 ≥ 4 기준)
                meaningful = {w for w in common if len(w) >= 4}
                score = len(meaningful)

            if score > best_score:
                best_score = score
                best_idx = i

        # 단어 교집합 1개 이상일 때만 허용
        if best_idx is not None and best_score >= 1:
            return best_idx
        return None

    # ── 프롬프트 빌더 헬퍼 ──────────────────────────────────────────────────

    def _build_section_directives(self, composition: PosterComposition) -> str:
        """각 섹션의 배치 지시문을 문자열로 조합한다."""
        blocks: List[str] = []

        for sec in composition.sections:
            if sec.role == SectionRole.HEADER:
                continue  # 헤더는 별도 처리

            role_label = {
                SectionRole.OVERVIEW: "OVERVIEW (전체 개요)",
                SectionRole.PAPER_CARD: "PAPER CARD (개별 논문)",
                SectionRole.COMPARISON: "COMPARISON (비교 분석)",
                SectionRole.FINDINGS: "FINDINGS (핵심 발견)",
                SectionRole.CONCLUSION: "CONCLUSION (결론)",
            }.get(sec.role, sec.role.value.upper())

            color_hint = f"\n- **색상 코드**: `{sec.color_code}`" if sec.color_code else ""
            text_preview = sec.text_content[:500].replace('\n', ' ')

            figure_lines: List[str] = []
            for fp in sec.figures:
                src_label = {
                    "autofigure": "AutoFigure SVG",
                    "paper_figure": "논문 원문 Figure",
                    "generated_diagram": "생성 다이어그램",
                }.get(fp.source, fp.source)

                if fp.source == "autofigure":
                    placeholder = f"<!-- EMBED_SVG_{fp.figure_index} -->"
                else:
                    placeholder = f"<!-- EMBED_FIGURE_{fp.figure_index} -->"

                figure_lines.append(
                    f"  - [{src_label}] 배치 위치: `{fp.placement}` | "
                    f"캡션: {fp.caption[:80]} | "
                    f"플레이스홀더: `{placeholder}`"
                )

            figure_block = ""
            if figure_lines:
                figure_block = "\n**Figure 배치 (반드시 이 섹션 카드 안에 포함)**:\n" + "\n".join(figure_lines)

            block = (
                f"### [{role_label}] {sec.title}{color_hint}\n"
                f"- **텍스트**: {text_preview}…\n"
                f"{figure_block}"
            )
            blocks.append(block)

        return "\n\n".join(blocks)

    def _build_comparison_tables_block(self, content: ExtractedContent) -> str:
        """비교 테이블 마크다운을 프롬프트 블록으로 변환한다."""
        tables = content.comparison_tables or []
        if not tables:
            return ""
        tables_text = "\n\n".join(tables[:3])
        return (
            "## 비교 분석 테이블 (포스터 COMPARISON 섹션에 포함하세요)\n\n"
            "아래 마크다운 테이블을 학술 포스터 스타일 HTML 테이블로 변환하여 "
            "comparison-section 안에 배치하세요. 원본 데이터를 정확히 반영하세요.\n\n"
            f"{tables_text}"
        )

    # ── Paper2Poster Binary-Tree 레이아웃 ─────────────────────────────────

    def _compute_panel_layout(
        self,
        composition: PosterComposition,
    ) -> List[Dict[str, Any]]:
        """Paper2Poster 논문의 binary-tree 분할 알고리즘으로 패널 레이아웃을 계산한다.

        각 섹션(HEADER 제외)에 대해 text proportion(tp)과 figure proportion(gp)을
        산출하고, 선형 모델로 size proportion(sp)과 aspect ratio(rp)를 추론한 뒤,
        재귀적 이진 분할로 (x, y, w, h) 좌표를 결정한다.

        Args:
            composition: design()이 반환한 포스터 구성.

        Returns:
            패널 레이아웃 리스트. 각 원소:
            ``{"section_index": int, "x": float, "y": float, "w": float, "h": float}``
            좌표는 콘텐츠 영역 내 퍼센트(0-100).
        """
        sections = [
            (i, s) for i, s in enumerate(composition.sections)
            if s.role != SectionRole.HEADER
        ]
        if not sections:
            return []

        # PAPER_CARD 그룹을 단일 가상 패널로 통합 (sp 폭주 방지)
        paper_indices = [i for i, s in sections if s.role == SectionRole.PAPER_CARD]
        non_paper = [(i, s) for i, s in sections if s.role != SectionRole.PAPER_CARD]
        paper_sections_list = [(i, s) for i, s in sections if s.role == SectionRole.PAPER_CARD]

        # tp, gp 계산 (PAPER_CARD는 합산하여 단일 패널로)
        merged = non_paper[:]
        if paper_sections_list:
            # 가상 통합 섹션: 첫 번째 PAPER_CARD의 인덱스를 대표로 사용
            merged.append((paper_indices[0], paper_sections_list[0][1]))

        total_text = sum(len(s.text_content) for _, s in merged) or 1
        total_figs = sum(len(s.figures) for _, s in merged) or 1

        # PAPER_CARD 그룹의 텍스트를 합산하되, 다른 패널과 동일한 스케일로
        paper_total_text = sum(len(s.text_content) for _, s in paper_sections_list)
        paper_total_figs = sum(len(s.figures) for _, s in paper_sections_list)
        total_text_with_papers = total_text - len(paper_sections_list[0][1].text_content) + paper_total_text if paper_sections_list else total_text
        total_figs_with_papers = total_figs - len(paper_sections_list[0][1].figures) + paper_total_figs if paper_sections_list else total_figs

        panels: List[Dict[str, Any]] = []
        for idx, sec in non_paper:
            tp = len(sec.text_content) / total_text_with_papers
            gp = len(sec.figures) / total_figs_with_papers if total_figs_with_papers > 0 else 0
            sp = max(0.6 * tp + 0.3 * gp + 0.05, 0.08)
            rp = max(0.4 * tp + 0.5 * gp + 1.0, 0.5)
            panels.append({"index": idx, "sp": sp, "rp": rp, "section": sec})

        # PAPER_CARD 그룹을 단일 패널로 (첫 번째 인덱스를 대표)
        if paper_sections_list:
            tp = paper_total_text / total_text_with_papers
            gp = paper_total_figs / total_figs_with_papers if total_figs_with_papers > 0 else 0
            # 논문 카드 그룹은 넓고 낮은 비율 (rp > 1)
            sp = max(0.6 * tp + 0.3 * gp + 0.05, 0.15)
            rp = max(1.5, 0.4 * tp + 0.5 * gp + 1.5)
            panels.append({
                "index": paper_indices[0],  # 대표 인덱스
                "sp": sp, "rp": rp,
                "section": paper_sections_list[0][1],
                "_is_paper_group": True,
            })

        # sp 정규화 (합=1)
        total_sp = sum(p["sp"] for p in panels)
        for p in panels:
            p["sp"] = p["sp"] / total_sp

        # binary tree 분할 (콘텐츠 영역 전체 = 0,0,100,100)
        _, layout = self._binary_tree_split(panels, 0.0, 0.0, 100.0, 100.0)

        logger.debug(
            "Binary-tree 레이아웃 계산 완료: %d panels",
            len(layout),
        )
        return layout

    def _binary_tree_split(
        self,
        panels: List[Dict[str, Any]],
        x: float,
        y: float,
        w: float,
        h: float,
    ) -> tuple:
        """패널 리스트를 재귀적으로 이진 분할하여 좌표를 결정한다.

        Paper2Poster의 핵심 알고리즘: N개 패널을 (1..N-1)로 분할하고,
        수평(상/하) 및 수직(좌/우) 분할을 모두 시도하여
        aspect-ratio deviation loss가 최소인 분할을 선택한다.

        Args:
            panels: 분할 대상 패널 리스트.
            x: 현재 영역 좌상단 X (퍼센트).
            y: 현재 영역 좌상단 Y (퍼센트).
            w: 현재 영역 너비 (퍼센트).
            h: 현재 영역 높이 (퍼센트).

        Returns:
            (loss, layout) 튜플. layout은 각 패널의 좌표 딕셔너리 리스트.
        """
        if len(panels) == 1:
            actual_rp = w / h if h > 0 else 1.0
            target_rp = panels[0]["rp"]
            loss = abs(actual_rp - target_rp)
            return loss, [{
                "section_index": panels[0]["index"],
                "x": x, "y": y, "w": w, "h": h,
            }]

        best_loss = float('inf')
        best_layout: List[Dict[str, Any]] = []
        total_sp = sum(p["sp"] for p in panels)

        for i in range(1, len(panels)):
            left, right = panels[:i], panels[i:]
            ratio = sum(p["sp"] for p in left) / total_sp if total_sp > 0 else 0.5

            # 수평 분할 (상/하)
            h_top = ratio * h
            if 0.15 * h < h_top < 0.85 * h:
                l1, a1 = self._binary_tree_split(left, x, y, w, h_top)
                l2, a2 = self._binary_tree_split(right, x, y + h_top, w, h - h_top)
                loss = l1 + l2
                if loss < best_loss:
                    best_loss = loss
                    best_layout = a1 + a2

            # 수직 분할 (좌/우)
            w_left = ratio * w
            if 0.15 * w < w_left < 0.85 * w:
                l1, a1 = self._binary_tree_split(left, x, y, w_left, h)
                l2, a2 = self._binary_tree_split(right, x + w_left, y, w - w_left, h)
                loss = l1 + l2
                if loss < best_loss:
                    best_loss = loss
                    best_layout = a1 + a2

        if not best_layout:
            # Fallback: 균등 수평 분할
            each_h = h / len(panels)
            best_layout = [
                {
                    "section_index": p["index"],
                    "x": x,
                    "y": y + i * each_h,
                    "w": w,
                    "h": each_h,
                }
                for i, p in enumerate(panels)
            ]
            best_loss = 0.0

        return best_loss, best_layout

    # ── Gemini 없이 자체 HTML 렌더링 ──────────────────────────────────────

    def render_html(
        self,
        composition: PosterComposition,
        autofigure_svgs: Optional[List[Dict[str, Any]]] = None,
        figures: Optional[List[Dict[str, Any]]] = None,
        content: Optional[Any] = None,
    ) -> str:
        """Gemini 없이 PosterComposition을 완전한 HTML로 렌더링한다.

        Gemini LLM이 가용하지 않을 때 fallback으로 사용된다.
        composition의 섹션 구조를 그대로 HTML로 변환하며,
        figure placeholder를 실제 콘텐츠로 치환한다.
        """
        autofigure_svgs = autofigure_svgs or []
        figures = figures or []
        esc = self._esc

        sections_by_role: Dict[SectionRole, List[CompositionSection]] = {}
        for sec in composition.sections:
            sections_by_role.setdefault(sec.role, []).append(sec)

        overview = (sections_by_role.get(SectionRole.OVERVIEW) or [None])[0]
        comparison = (sections_by_role.get(SectionRole.COMPARISON) or [None])[0]
        findings = (sections_by_role.get(SectionRole.FINDINGS) or [None])[0]
        conclusion = (sections_by_role.get(SectionRole.CONCLUSION) or [None])[0]
        paper_sections = sections_by_role.get(SectionRole.PAPER_CARD, [])

        title_text = composition.title or "Academic Review Poster"
        title_classes = ["poster-title"]
        if len(title_text) >= 72:
            title_classes.append("title-long")
        if any(ord(ch) > 127 for ch in title_text):
            title_classes.append("title-ko")
        else:
            title_classes.append("title-en")

        keywords_html = ''.join(
            f'<span class="keyword">{esc(k)}</span>'
            for k in composition.keywords[:8]
        )

        paper_count = len(getattr(content, 'paper_analyses', []) or paper_sections)
        refs = getattr(content, 'references', []) if content else []
        ref_count = len(refs or [])
        source_figure_count = len(autofigure_svgs) + len(figures)
        figure_count = source_figure_count or composition.total_figures

        if refs:
            refs_items = ' '.join(
                f'[{i+1}] {esc(r)}' for i, r in enumerate(refs[:8])
            )
            refs_html = refs_items
        else:
            refs_html = 'References were unavailable in the extracted review payload.'

        first_finding = ''
        if content and getattr(content, 'key_findings', None):
            first_finding = content.key_findings[0]
        elif findings:
            first_finding = findings.text_content.split('\n')[0].strip('- *')
        thesis_html = esc(first_finding or "핵심 결론이 입력 리포트에서 추출되지 않았습니다.")
        generated_on = date.today().isoformat()
        synthesis_status = 'synthesized' if content and paper_count else 'partial'

        visual_agent = PosterVisualAgent()

        def section_body(sec: Optional[CompositionSection], default_text: str = "") -> str:
            if not sec:
                return self._text_to_html(default_text)
            if sec.role == SectionRole.COMPARISON:
                return self._markdown_table_to_html(sec.text_content)
            return self._text_to_html(sec.text_content)

        def section_figures(sec: Optional[CompositionSection]) -> str:
            if not sec:
                return ""
            return ''.join(
                self._render_figure_html(fp, autofigure_svgs, figures)
                for fp in sec.figures
            )

        def metric_callout(text: str) -> str:
            """Surface one labelled result only when its source text supports it."""
            result_text = (text or '').split('**실험 결과**', 1)[-1]
            result_text = result_text.split('**한계**', 1)[0].strip()
            metric = (
                r"[+-]?\d+(?:\.\d+)?(?:\s?(?:%|×|x)|\s+"
                r"(?:points?|pts?|ms|seconds?|papers?|tasks?|samples?))"
            )
            patterns = (
                (
                    rf"\b(?:cuts?|reduces?|decreases?)\s+(.{{2,64}}?)\s+from\s+"
                    rf"{metric}\s+to\s+({metric})",
                    lambda match: (match.group(1), match.group(2)),
                ),
                (
                    rf"\b(?:improves?|increases?|raises?)\s+(.{{2,64}}?)\s+by\s+({metric})",
                    lambda match: (match.group(1), match.group(2)),
                ),
                (
                    rf"\b(?:preserves?|retains?)\s+({metric})\s+(?:of\s+)?"
                    r"(.{2,64}?)(?:\s+in\b|\s+on\b|\s+across\b|[.;]|$)",
                    lambda match: (f"{match.group(2)} preserved", match.group(1)),
                ),
            )

            label = value = ''
            for pattern, unpack in patterns:
                match = re.search(pattern, result_text, flags=re.IGNORECASE)
                if match:
                    label, value = unpack(match)
                    break

            if not value:
                match = re.search(metric, result_text, flags=re.IGNORECASE)
                if not match:
                    return ""
                value = match.group(0)
                context = result_text.replace(value, ' ')
                context = re.sub(
                    r"\b(?:reports?|shows?|achieves?|reaches?|records?)\b",
                    ' ',
                    context,
                    flags=re.IGNORECASE,
                )
                label = self._poster_excerpt(context.strip(' .,:;-'), 42)

            label = self._poster_excerpt(label.strip(' .,:;-'), 42)
            if not label:
                return ""
            return (
                f'<div class="metric-callout" title="{esc(result_text)}" '
                f'aria-label="{esc(label)}: {esc(value)}">'
                f'<span class="metric-label">{esc(label)}</span>'
                f'<strong>{esc(value)}</strong>'
                '</div>'
            )

        overview_fig_html = section_figures(overview)
        if overview and not overview_fig_html:
            methodology = getattr(content, 'methodology', '') if content else ''
            steps = visual_agent._parse_methodology_steps(methodology or overview.text_content)
            if steps:
                svg = sanitize_poster_markup(visual_agent.generate_pipeline_diagram(steps))
                overview_fig_html = (
                    '<figure class="evidence-figure overview-figure">'
                    f'{svg}'
                    '<figcaption>연구 파이프라인 다이어그램: 추출된 방법론 단계를 요약한 자동 생성 개요.</figcaption>'
                    '</figure>'
                )

        paper_cards_html = []
        for i, psec in enumerate(paper_sections):
            color = psec.color_code or _PAPER_COLORS[i % len(_PAPER_COLORS)]
            ptitle = psec.title or f"Evidence source {i + 1}"
            paper_title_class = "paper-title title-long" if len(ptitle) >= 58 else "paper-title"
            fig_html = section_figures(psec)
            if not fig_html and psec.text_content:
                method_text = (
                    psec.text_content.split('**주요 기여**')[0]
                    if '**주요 기여**' in psec.text_content
                    else psec.text_content[:600]
                )
                steps = visual_agent._parse_methodology_steps(method_text)
                if steps:
                    svg = sanitize_poster_markup(visual_agent.generate_pipeline_diagram(steps))
                    fig_html = (
                        '<figure class="evidence-figure">'
                        f'{svg}'
                        f'<figcaption>{esc(ptitle)} 방법론 흐름을 요약한 자동 생성 다이어그램.</figcaption>'
                        '</figure>'
                    )

            paper_cards_html.append(
                f'<article class="paper-card" style="--paper-color:{esc(color)};">'
                f'<div class="paper-meta">Evidence {i + 1:02d}</div>'
                f'<div class="paper-heading-row">'
                f'<h3 class="{paper_title_class}">{esc(ptitle)}</h3>'
                f'{metric_callout(psec.text_content)}'
                f'</div>'
                f'<div class="paper-card-body{"" if fig_html else " paper-card-body--text-only"}">'
                f'<div class="paper-copy">{self._text_to_html(psec.text_content)}</div>'
                f'{fig_html}'
                f'</div>'
                f'</article>'
            )

        if not paper_cards_html:
            paper_cards_html.append(
                '<article class="paper-card" style="--paper-color:#2457a6;">'
                '<div class="paper-meta">Evidence</div>'
                '<h3 class="paper-title">No individual paper cards were extracted</h3>'
                '<p>논문별 세부 분석 데이터가 없어 전체 리뷰 단위로 요약합니다.</p>'
                '</article>'
            )

        comparison_fig_html = section_figures(comparison)
        findings_fig_html = section_figures(findings)
        conclusion_fig_html = section_figures(conclusion)

        html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(composition.title)} - Academic Poster</title>
<style>
/* ================================================================
   Editorial Evidence Wall — self-contained academic poster
   Contract: 4:3 / A3 landscape, 12-column responsive grid
   ================================================================ */
:root {{
  --font-main: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR",
               "Apple SD Gothic Neo", Arial, sans-serif;
  --ink: #172033;
  --muted: #596579;
  --quiet: #7a8494;
  --paper: #fffdf8;
  --panel: #ffffff;
  --panel-soft: #f4f7fb;
  --line: #d9dee8;
  --blue: #2457a6;
  --green: #0f766e;
  --amber: #b45309;
  --red: #b91c1c;
  --gap: 12px;
  --radius: 8px;
}}

@page {{
  size: A3 landscape;
  margin: 0;
}}
*,*::before,*::after {{ box-sizing: border-box; }}

html, body {{
  margin: 0;
  min-height: 100%;
}}

body {{
  font-family: var(--font-main);
  background: #e7e9ee;
  margin: 0;
  padding: 16px;
  color: var(--ink);
  font-size: 14px;
  line-height: 1.48;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  word-break: keep-all;
  overflow-wrap: break-word;
}}

.poster {{
  width: min(100%, 1580px);
  aspect-ratio: 4 / 3;
  min-height: 900px;
  margin: 0 auto;
  background: var(--paper);
  border: 1px solid #cfd5df;
  box-shadow: 0 14px 40px rgba(23,32,51,0.18);
  padding: 16px;
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  grid-auto-rows: min-content;
  gap: var(--gap);
}}

.poster-header {{
  grid-column: 1 / -1;
  background: var(--ink);
  color: #fff;
  border-radius: var(--radius);
  padding: 12px 18px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px 18px;
  break-inside: avoid;
}}
.kicker {{
  margin: 0 0 6px;
  color: #a8d5ff;
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
}}
.poster-header h1 {{
  font-size: clamp(1.9rem, 2.8vw, 3rem);
  font-weight: 800;
  margin: 0 0 8px;
  line-height: 1.08;
  letter-spacing: 0;
}}
.poster-header h1.title-long {{
  font-size: clamp(1.45rem, 1.95vw, 2.2rem);
  line-height: 1.05;
}}
.poster-header .subtitle {{
  margin: 0;
  color: rgba(255,255,255,0.82);
  font-size: 0.98rem;
  line-height: 1.45;
}}
.keyword-row {{
  margin-top: 9px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}}
.keyword {{
  border: 1px solid rgba(255,255,255,0.28);
  border-radius: 999px;
  color: #dbeafe;
  padding: 3px 9px;
  font-size: 0.72rem;
  font-weight: 500;
}}
.evidence-meta {{
  display: grid;
  grid-template-columns: repeat(3, minmax(72px, 1fr));
  align-self: start;
  gap: 6px;
  min-width: 246px;
}}
.evidence-meta span {{
  border: 1px solid rgba(255,255,255,0.24);
  border-radius: 6px;
  padding: 6px 8px;
  text-align: center;
  font-size: 0.72rem;
  text-transform: uppercase;
}}
.evidence-meta strong {{
  display: block;
  color: #fff;
  font-size: 1rem;
}}

.thesis-strip,
.section-card {{
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--panel);
  padding: 13px 15px;
  min-width: 0;
  break-inside: avoid;
}}
.thesis-strip {{
  grid-column: 1 / -1;
  border-left: 6px solid var(--green);
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 14px;
  align-items: baseline;
  font-size: 1.03rem;
  font-weight: 700;
}}
.thesis-strip .label {{
  color: var(--green);
  font-size: 0.78rem;
  text-transform: uppercase;
}}
.provenance-meta {{
  display: flex;
  gap: 8px;
  color: var(--muted);
  font-size: 0.66rem;
  font-weight: 600;
  white-space: nowrap;
}}
.provenance-meta span + span::before {{
  content: "·";
  margin-right: 8px;
  color: var(--quiet);
}}
.overview-section {{
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: minmax(280px, 0.9fr) minmax(0, 1.5fr);
  gap: 16px;
  align-items: start;
}}
.papers-section {{ grid-column: 1 / -1; }}
.overview-section,
.papers-section,
.comparison-section,
.findings-section,
.conclusion-section {{
  padding: 10px 12px;
}}
.comparison-section {{
  grid-column: span 6;
  grid-row: 5;
}}
.findings-section {{
  grid-column: span 3;
  grid-row: 5;
}}
.conclusion-section {{
  grid-column: span 3;
  grid-row: 5;
}}
.conclusion-section {{
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}}
.findings-body {{
  columns: 1;
}}
.findings-body h4,
.findings-body ul {{
  break-inside: avoid;
}}

.section-card h2 {{
  margin: 0 0 8px;
  color: var(--blue);
  font-size: 1rem;
  line-height: 1.22;
  font-weight: 700;
  border-bottom: 2px solid #e2e8f0;
  padding-bottom: 8px;
}}
.section-eyebrow {{
  margin: 0 0 5px;
  color: var(--quiet);
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}}
.section-card h4,
.paper-card h4 {{
  margin: 8px 0 3px;
  color: var(--ink);
  font-size: 0.8rem;
  line-height: 1.3;
}}
.paper-card h4 {{
  margin: 5px 0 2px;
}}
.section-card p,
.paper-card p {{
  margin: 0 0 5px;
  color: #2f3a4d;
  font-size: 0.76rem;
  line-height: 1.4;
}}
.paper-card p {{
  overflow-wrap: anywhere;
}}
.section-card ul,
.paper-card ul {{
  margin: 4px 0 0;
  padding-left: 1.05rem;
}}
.section-card li,
.paper-card li {{
  margin: 0 0 3px;
  color: #2f3a4d;
  font-size: 0.76rem;
  line-height: 1.38;
}}

.paper-grid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}}
.paper-card {{
  border: 1px solid var(--line);
  border-left: 5px solid var(--paper-color, var(--blue));
  border-radius: 7px;
  padding: 10px 11px;
  background: #fff;
  min-width: 0;
  break-inside: avoid;
}}
.paper-meta {{
  color: var(--paper-color, var(--blue));
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
  margin-bottom: 5px;
}}
.paper-title {{
  margin: 0 0 8px;
  color: var(--ink);
  font-size: 0.92rem;
  line-height: 1.32;
}}
.paper-title.title-long {{
  font-size: 0.82rem;
  line-height: 1.28;
}}
.paper-heading-row {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: start;
}}
.metric-callout {{
  min-width: 68px;
  padding: 4px 6px;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid var(--line);
  text-align: right;
}}
.metric-callout span {{
  display: block;
  color: var(--muted);
  font-size: 0.56rem;
  font-weight: 700;
  text-transform: uppercase;
}}
.metric-callout strong {{
  display: block;
  color: var(--paper-color, var(--blue));
  font-size: 1.08rem;
  line-height: 1.05;
}}
.paper-card-body {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(86px, 0.42fr);
  gap: 8px;
  align-items: start;
}}
.paper-card-body--text-only {{
  grid-template-columns: 1fr;
}}

table {{
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  margin: 8px 0 10px;
}}
th, td {{
  border: 1px solid var(--line);
  padding: 6px 7px;
  text-align: left;
  vertical-align: top;
  font-size: 0.76rem;
  line-height: 1.38;
  overflow-wrap: anywhere;
}}
th {{
  background: #eef2f7;
  color: var(--ink);
  font-weight: 700;
}}
tbody tr:nth-child(even) td {{ background: #f8fafc; }}

figure {{
  margin: 7px 0 0;
  text-align: center;
  break-inside: avoid;
}}
figure img,
figure svg {{
  max-width: 100%;
  width: 100%;
  height: auto;
  max-height: 120px;
  object-fit: contain;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
}}
.overview-figure svg {{
  height: 150px;
  max-height: 150px;
}}
.paper-card figure svg,
.paper-card figure img {{
  max-height: 100px;
}}
figcaption {{
  color: var(--muted);
  font-size: 0.72rem;
  line-height: 1.35;
  margin-top: 5px;
  text-align: left;
}}

.poster-footer {{
  background: var(--panel-soft);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 12px;
  color: var(--muted);
  font-size: 0.72rem;
  line-height: 1.4;
}}

@media (max-width: 1199px) {{
  body {{ padding: 10px; }}
  .poster {{
    aspect-ratio: auto;
    min-height: 0;
    grid-template-columns: repeat(8, minmax(0, 1fr));
  }}
  .overview-section,
  .papers-section,
  .comparison-section,
  .findings-section,
  .conclusion-section {{
    grid-column: 1 / -1;
    grid-row: auto;
  }}
  .overview-section {{
    grid-template-columns: 1fr;
  }}
  .paper-grid {{
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }}
}}

@media (max-width: 760px) {{
  body {{ padding: 0; background: var(--paper); }}
  .poster {{
    width: 100%;
    border: 0;
    box-shadow: none;
    padding: 12px;
    grid-template-columns: 1fr;
  }}
  .poster-header {{
    grid-template-columns: 1fr;
  }}
  .evidence-meta {{
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    min-width: 0;
  }}
  .thesis-strip,
  .section-card,
  .overview-section,
  .papers-section,
  .comparison-section,
  .findings-section,
  .conclusion-section {{
    grid-column: 1 / -1;
  }}
  .conclusion-section {{
    grid-template-columns: 1fr;
  }}
  .thesis-strip {{
    grid-template-columns: 1fr;
    gap: 6px;
  }}
  .provenance-meta {{
    flex-wrap: wrap;
    white-space: normal;
  }}
  .findings-body {{
    columns: 1;
  }}
  .paper-grid {{
    grid-template-columns: 1fr;
  }}
  .paper-card-body {{
    grid-template-columns: 1fr;
  }}
  .paper-heading-row {{
    grid-template-columns: 1fr;
  }}
  .metric-callout {{
    justify-self: start;
    text-align: left;
  }}
}}

@media print {{
  html, body {{
    width: 420mm;
    height: 297mm;
    overflow: hidden;
  }}
  body {{
    background: white;
    padding: 0;
    display: flex;
    justify-content: center;
  }}
  .poster {{
    width: 396mm;
    height: 297mm;
    min-height: 297mm;
    max-width: none;
    box-shadow: none;
    border: 0;
    overflow: hidden;
  }}
  * {{
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  .section-card,
  .paper-card,
  figure,
  table,
  tr {{
    break-inside: avoid;
    page-break-inside: avoid;
  }}
}}
</style>
</head>
<body>
<main class="poster poster--a3-landscape" aria-label="Academic review poster">
  <header class="poster-header">
    <div>
      <p class="kicker">Academic Review Poster</p>
      <h1 class="{' '.join(title_classes)}">{esc(title_text)}</h1>
      <p class="subtitle">{esc(composition.subtitle)}</p>
      <div class="keyword-row">{keywords_html}</div>
    </div>
    <div class="evidence-meta" aria-label="Evidence metadata">
      <span><strong>{paper_count}</strong> papers</span>
      <span><strong>{ref_count}</strong> refs</span>
      <span><strong>{figure_count}</strong> figures</span>
    </div>
  </header>

  <aside class="thesis-strip">
    <span class="label">Thesis</span>
    <span>{thesis_html}</span>
    <span class="provenance-meta" aria-label="Review provenance">
      <span>Generated {generated_on}</span>
      <span>Status {synthesis_status}</span>
      <span>{paper_count} source papers</span>
    </span>
  </aside>

  <section class="section-card overview-section">
    <div class="overview-copy">
      <p class="section-eyebrow">01 / Research Frame</p>
      <h2>{esc(overview.title if overview else "연구 개요")}</h2>
      {section_body(overview, "추출된 초록과 연구 배경이 없습니다.")}
    </div>
    {overview_fig_html}
  </section>

  <section class="section-card papers-section">
    <p class="section-eyebrow">02 / Evidence Papers</p>
    <h2>논문별 증거 벽</h2>
    <div class="paper-grid">
      {''.join(paper_cards_html)}
    </div>
  </section>

  <section class="section-card comparison-section">
    <p class="section-eyebrow">03 / Cross-paper Comparison</p>
    <h2>{esc(comparison.title if comparison else "비교 분석")}</h2>
    {section_body(comparison, "비교 테이블이 추출되지 않았습니다.")}
    {comparison_fig_html}
  </section>

  <section class="section-card findings-section">
    <p class="section-eyebrow">04 / Findings</p>
    <h2>{esc(findings.title if findings else "핵심 발견 및 기여")}</h2>
    <div class="findings-body">{section_body(findings, "핵심 발견이 추출되지 않았습니다.")}</div>
    {findings_fig_html}
  </section>

  <section class="section-card conclusion-section">
    <div>
      <p class="section-eyebrow">05 / Takeaway</p>
      <h2>{esc(conclusion.title if conclusion else "결론")}</h2>
      {section_body(conclusion, "결론이 추출되지 않았습니다.")}
      {conclusion_fig_html}
    </div>
    <footer class="poster-footer">
      <strong>참고문헌</strong>&ensp;{refs_html}
    </footer>
  </section>
</main>
</body>
</html>'''
        return sanitize_poster_markup(html)

    def _render_figure_html(
        self,
        fp: FigurePlacement,
        autofigure_svgs: List[Dict[str, Any]],
        figures: List[Dict[str, Any]],
    ) -> str:
        """FigurePlacement를 실제 HTML로 렌더링한다."""
        if fp.source == 'autofigure' and fp.figure_index < len(autofigure_svgs):
            af = autofigure_svgs[fp.figure_index]
            svg = af.get('svg_content', '')
            if svg:
                svg = sanitize_poster_markup(svg)
                return f'''<figure class="evidence-figure" style="margin:12px 0;">
                    {svg}
                    <figcaption style="font-size:0.8rem;color:#64748b;margin-top:6px;">{self._esc(fp.caption)}</figcaption>
                </figure>'''
        elif fp.source == 'paper_figure' and fp.figure_index < len(figures):
            fig = figures[fp.figure_index]
            b64 = fig.get('image_base64', '') if isinstance(fig, dict) else getattr(fig, 'image_base64', '')
            if b64:
                mime = fig.get('mime_type', 'image/png') if isinstance(fig, dict) else getattr(fig, 'mime_type', 'image/png')
                if mime not in {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}:
                    mime = 'image/png'
                return f'''<figure class="embed-figure" style="margin:12px 0;">
                    <img src="data:{self._esc(mime)};base64,{self._esc(b64)}" style="width:100%;border-radius:8px;" alt="{self._esc(fp.caption)}" />
                    <figcaption style="font-size:0.78rem;color:#64748b;margin-top:6px;">{self._esc(fp.caption)}</figcaption>
                </figure>'''
        return ''

    def _text_to_html(self, text: str) -> str:
        """마크다운 텍스트를 HTML로 변환한다 (CSS 클래스 기반)."""
        import re

        def inline_markup(value: str) -> str:
            escaped = self._esc(value)
            return re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', escaped)

        lines = text.strip().split('\n')
        parts = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith('- ') or stripped.startswith('* '):
                item = inline_markup(stripped[2:])
                parts.append(f'<li>{item}</li>')
            elif stripped.startswith('**') and stripped.endswith('**'):
                parts.append(f'<h4>{self._esc(stripped.strip("*"))}</h4>')
            elif stripped.startswith('**'):
                clean = inline_markup(stripped)
                parts.append(f'<p>{clean}</p>')
            else:
                parts.append(f'<p>{self._esc(stripped)}</p>')

        # 연속 li를 ul로 묶기
        result = []
        in_list = False
        for p in parts:
            if p.startswith('<li'):
                if not in_list:
                    result.append('<ul>')
                    in_list = True
                result.append(p)
            else:
                if in_list:
                    result.append('</ul>')
                    in_list = False
                result.append(p)
        if in_list:
            result.append('</ul>')

        return '\n'.join(result)

    def _markdown_table_to_html(self, text: str) -> str:
        """마크다운 테이블을 HTML 테이블로 변환한다."""
        import re
        lines = text.strip().split('\n')
        tables_html = []
        current_rows: List[List[str]] = []
        in_table = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith('|') and '|' in stripped[1:]:
                cells = [c.strip() for c in stripped.split('|')[1:-1]]
                if re.match(r'^[\s\-:]+$', ''.join(cells)):
                    continue  # 구분선 스킵
                current_rows.append(cells)
                in_table = True
            else:
                if in_table and current_rows:
                    tables_html.append(self._rows_to_table(current_rows))
                    current_rows = []
                    in_table = False
                if stripped:
                    tables_html.append(f'<p style="margin:4px 0;">{self._esc(stripped)}</p>')

        if current_rows:
            tables_html.append(self._rows_to_table(current_rows))

        return '\n'.join(tables_html)

    @staticmethod
    def _poster_excerpt(text: str, limit: int) -> str:
        """Return a bounded, visible excerpt instead of clipping text in CSS."""
        normalized = re.sub(r'\s+', ' ', str(text or '')).strip()
        if len(normalized) <= limit:
            return normalized

        first_sentence = re.split(r'(?<=[.!?。])\s+', normalized, maxsplit=1)[0]
        if len(first_sentence) <= limit:
            return first_sentence

        shortened = normalized[: limit + 1].rsplit(' ', 1)[0].rstrip(' ,;:')
        return f"{shortened or normalized[:limit].rstrip()}…"

    @staticmethod
    def _rows_to_table(rows: List[List[str]]) -> str:
        """행 리스트를 HTML 테이블로 변환한다."""
        if not rows:
            return ''
        header = rows[0]
        body = rows[1:]
        th = ''.join(f'<th>{escape_text(h)}</th>' for h in header)
        trs = []
        for row in body:
            tds = ''.join(f'<td>{escape_text(c)}</td>' for c in row)
            trs.append(f'<tr>{tds}</tr>')
        return f'''<table>
            <thead><tr>{th}</tr></thead>
            <tbody>{''.join(trs)}</tbody>
        </table>'''

    # ── 유틸리티 ────────────────────────────────────────────────────────────

    @staticmethod
    def _esc(text: str) -> str:
        """HTML 특수문자를 이스케이프한다."""
        return (
            str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
        )
