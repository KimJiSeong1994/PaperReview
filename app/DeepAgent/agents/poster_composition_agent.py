"""
Poster Composition Agent

포스터 HTML 생성 전에 콘텐츠-figure 통합 레이아웃을 설계하는 에이전트.

기존 파이프라인의 post-hoc injection 문제를 해결한다:
- 기존: HTML 생성 → _inject_visuals_into_poster() 로 figure를 </body> 앞에 추가
- 개선: 생성 전에 콘텐츠-figure 매핑을 결정 → Gemini가 figure를 제자리에 배치
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .poster_content_agent import ExtractedContent

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
        grid_col_css = (
            "repeat(3, 1fr)" if composition.grid_columns >= 3
            else "repeat(2, 1fr)"
        )

        return f"""당신은 NeurIPS/ICML 학회 포스터 디자이너입니다.
아래 지정된 섹션 구조와 figure 배치 지시를 **정확히** 따라 HTML 포스터를 생성하세요.

## 핵심 원칙
1. **figure는 반드시 관련 섹션 카드 안에 배치** — 별도 "Additional Visualizations" 섹션 생성 금지
2. **<!-- EMBED_SVG_N --> 플레이스홀더를 그대로 유지** — 실제 SVG 데이터는 후처리에서 교체됨
3. **<!-- EMBED_FIGURE_N --> 플레이스홀더를 그대로 유지** — 실제 이미지는 후처리에서 교체됨
4. 논문별 색상 코드를 카드 border-left 및 SVG 색상에 일관되게 적용
5. 각 논문 카드 안에 해당 논문의 구체적 파이프라인 SVG를 직접 생성 (generic "Input→Process→Output" 금지)

## 포스터 메타데이터
- **제목**: {composition.title}
- **부제목**: {composition.subtitle}
- **키워드**: {keywords_str}
- **그리드**: {composition.grid_columns}열 레이아웃

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
  <title>{composition.title}</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap" rel="stylesheet">
</head>
<body>

<header>
  제목 + 부제목 + 키워드 배지
</header>

<section class="overview-section">
  초록+배경 텍스트 | 파이프라인 다이어그램 SVG 또는 <!-- EMBED_SVG_N -->
</section>

<section class="papers-grid">
  <!-- 논문 카드들: 텍스트 + SVG + <!-- EMBED_SVG_N --> + <!-- EMBED_FIGURE_N --> -->
</section>

<section class="comparison-section">
  비교 테이블 + 결과 차트
</section>

<section class="findings-section">
  핵심 발견 + 기여 목록
</section>

<section class="conclusion-section">
  결론
</section>

</body>
</html>
```

## CSS 규칙

```css
:root {{
  --primary: #2563eb;
  --bg: #f8fafc;
  --card-radius: 12px;
  --shadow: 0 2px 8px rgba(0,0,0,0.06);
}}

body {{
  font-family: 'Inter', 'Noto Sans KR', sans-serif;
  background: var(--bg);
  margin: 0;
  padding: 0;
}}

.poster-container {{
  max-width: 1600px;
  margin: 0 auto;
  padding: 24px;
}}

header {{
  background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
  color: white;
  padding: 32px 40px;
  border-radius: var(--card-radius);
  margin-bottom: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}}

header h1 {{
  font-size: 2rem;
  font-weight: 800;
  margin: 0 0 8px;
  line-height: 1.2;
}}

header h2 {{
  font-size: 1.1rem;
  font-weight: 400;
  opacity: 0.85;
  margin: 0;
}}

.keyword-badge {{
  display: inline-block;
  background: rgba(255,255,255,0.15);
  border: 1px solid rgba(255,255,255,0.3);
  border-radius: 20px;
  padding: 3px 12px;
  font-size: 0.78rem;
  margin: 4px 3px;
}}

.overview-section {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 24px;
}}

.papers-grid {{
  display: grid;
  grid-template-columns: {grid_col_css};
  gap: 20px;
  margin-bottom: 24px;
}}

.paper-card {{
  background: white;
  border-radius: var(--card-radius);
  padding: 24px;
  box-shadow: var(--shadow);
  border-top: 3px solid currentColor;
}}

.paper-card h3 {{
  font-size: 1rem;
  font-weight: 700;
  margin: 0 0 12px;
  line-height: 1.3;
}}

.paper-card svg,
.paper-card .embed-figure {{
  width: 100%;
  height: auto;
  border-radius: 8px;
  margin: 12px 0;
}}

.comparison-section,
.findings-section,
.conclusion-section {{
  background: white;
  border-radius: var(--card-radius);
  padding: 28px;
  box-shadow: var(--shadow);
  margin-bottom: 24px;
}}

.section-heading {{
  font-size: 1.2rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 16px;
  padding-bottom: 10px;
  border-bottom: 2px solid #e2e8f0;
}}

table.comparison-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.88rem;
  margin-top: 12px;
}}

table.comparison-table th {{
  background: #f1f5f9;
  font-weight: 600;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  text-align: left;
}}

table.comparison-table td {{
  padding: 9px 12px;
  border: 1px solid #e2e8f0;
  vertical-align: top;
}}

table.comparison-table tr:nth-child(even) td {{
  background: #f8fafc;
}}

.findings-list {{
  list-style: none;
  padding: 0;
  margin: 0;
}}

.findings-list li {{
  display: flex;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid #f1f5f9;
  font-size: 0.92rem;
  line-height: 1.5;
}}

.findings-list li::before {{
  content: "▶";
  color: var(--primary);
  flex-shrink: 0;
  font-size: 0.7rem;
  margin-top: 4px;
}}

.embed-placeholder {{
  display: block;
  background: #f1f5f9;
  border: 2px dashed #cbd5e1;
  border-radius: 8px;
  padding: 16px;
  text-align: center;
  color: #94a3b8;
  font-size: 0.8rem;
  margin: 12px 0;
}}
```

## 출력 규칙
- <!DOCTYPE html>로 시작하는 완전한 HTML만 출력 (설명 텍스트, 코드블록 마커 제외)
- <!-- EMBED_SVG_N --> 와 <!-- EMBED_FIGURE_N --> 플레이스홀더는 반드시 원문 그대로 포함
- figure 플레이스홀더는 반드시 해당 논문/섹션 카드 내부에 위치해야 함
- 별도 "추가 시각화" 또는 "Additional Visualizations" 섹션 생성 금지"""

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
                        f'<img src="data:image/png;base64,{b64}" '
                        f'alt="{self._esc(af.get("paper_title", ""))}" '
                        f'style="width:100%;height:auto;border-radius:8px;" />'
                    )
                    poster_html = poster_html.replace(placeholder, img_html)
                else:
                    poster_html = poster_html.replace(placeholder, '')
                continue

            # SVG를 반응형으로 래핑
            if not svg_content.startswith('<svg'):
                svg_content = f'<svg xmlns="http://www.w3.org/2000/svg">{svg_content}</svg>'
            svg_wrapped = (
                f'<div class="embed-autofigure" style="width:100%;margin:12px 0;">'
                f'{svg_content}'
                f'</div>'
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
                f'<img src="data:{mime};base64,{b64}" '
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
            title = paper.get('title', f'Paper {i + 1}')
            color = _PAPER_COLORS[i % len(_PAPER_COLORS)]

            # 텍스트 콘텐츠 조합
            text_parts = []
            methodology = (paper.get('methodology') or '')[:600]
            contributions = (paper.get('contributions') or '')[:400]
            results = (paper.get('results') or '')[:400]

            if methodology:
                text_parts.append(f"**핵심 방법론**\n{methodology}")
            if contributions:
                text_parts.append(f"**주요 기여**\n{contributions}")
            if results:
                text_parts.append(f"**실험 결과**\n{results}")

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
