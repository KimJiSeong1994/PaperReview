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
- 별도 "추가 시각화" 또는 "Additional Visualizations" 섹션 생성 금지

## 절대 금지 사항
- <img src="https://..."> 등 외부 URL 이미지 절대 사용 금지
- Wikipedia, Google, arXiv 등 외부 서비스의 로고/아이콘/워터마크 삽입 금지
- 이미지는 반드시 data:image/... base64 또는 인라인 SVG만 허용
- 폰트 CDN 외에는 어떤 외부 URL도 참조 금지
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

        keywords_html = ''.join(
            f'<span class="keyword">{esc(k)}</span>'
            for k in composition.keywords[:8]
        )

        # ── Binary-tree 레이아웃 계산 ─────────────────────────────────
        layout = self._compute_panel_layout(composition)

        # 섹션 인덱스 → 레이아웃 좌표 매핑
        layout_map: Dict[int, Dict[str, float]] = {
            item["section_index"]: item for item in layout
        }

        # 섹션 번호 부여 (PAPER_CARD 그룹은 1개 번호)
        section_numbers: Dict[int, int] = {}
        num = 1
        paper_num_assigned = False
        for idx, sec in enumerate(composition.sections):
            if sec.role == SectionRole.HEADER:
                continue
            if sec.role == SectionRole.PAPER_CARD:
                if not paper_num_assigned:
                    section_numbers[idx] = num
                    num += 1
                    paper_num_assigned = True
                # 나머지 PAPER_CARD는 그룹 번호와 동일
            else:
                section_numbers[idx] = num
                num += 1

        # 섹션 역할 → 제목 매핑
        _role_titles = {
            SectionRole.OVERVIEW: "연구 개요",
            SectionRole.PAPER_CARD: None,  # 논문 카드는 개별 제목 사용
            SectionRole.COMPARISON: "비교 분석",
            SectionRole.FINDINGS: "핵심 발견 및 기여",
            SectionRole.CONCLUSION: "결론",
        }

        # ── 패널 HTML 생성 ────────────────────────────────────────────
        visual_agent = PosterVisualAgent()
        gap = 0.8  # 패널 간 갭 (%)

        # 논문 카드 그룹 처리: 여러 PAPER_CARD를 하나의 패널 안에 서브그리드로 배치
        paper_card_indices = [
            idx for idx, sec in enumerate(composition.sections)
            if sec.role == SectionRole.PAPER_CARD
        ]
        # 첫 번째 PAPER_CARD의 레이아웃을 그룹 대표로 사용하되,
        # 모든 PAPER_CARD 레이아웃 좌표를 병합하여 바운딩 박스를 구한다.
        paper_group_bbox: Optional[Dict[str, float]] = None
        if paper_card_indices:
            coords = [layout_map[i] for i in paper_card_indices if i in layout_map]
            if coords:
                min_x = min(c["x"] for c in coords)
                min_y = min(c["y"] for c in coords)
                max_x = max(c["x"] + c["w"] for c in coords)
                max_y = max(c["y"] + c["h"] for c in coords)
                paper_group_bbox = {
                    "x": min_x, "y": min_y,
                    "w": max_x - min_x, "h": max_y - min_y,
                }

        panels_html = ''

        # 이미 그룹 렌더링 한 PAPER_CARD 인덱스 추적
        paper_cards_rendered = False

        for idx, sec in enumerate(composition.sections):
            if sec.role == SectionRole.HEADER:
                continue  # 헤더는 별도 영역

            if idx not in layout_map:
                continue

            # ── PAPER_CARD 그룹 렌더링 ────────────────────────────
            if sec.role == SectionRole.PAPER_CARD:
                if paper_cards_rendered:
                    continue  # 이미 그룹으로 렌더링 완료
                paper_cards_rendered = True

                if paper_group_bbox is None:
                    continue

                bw = paper_group_bbox["w"] - gap

                # 개별 논문 카드 HTML 목록
                paper_sections = [
                    composition.sections[i] for i in paper_card_indices
                ]
                cards = []
                for psec in paper_sections:
                    color = psec.color_code or '#2563eb'

                    fig_html = ''
                    for fp in psec.figures:
                        fig_html += self._render_figure_html(
                            fp, autofigure_svgs, figures,
                        )
                    if not fig_html and psec.text_content:
                        method_text = (
                            psec.text_content.split('**주요 기여**')[0]
                            if '**주요 기여**' in psec.text_content
                            else psec.text_content[:600]
                        )
                        steps = visual_agent._parse_methodology_steps(method_text)
                        if steps:
                            svg = visual_agent.generate_pipeline_diagram(steps)
                            fig_html = f'<div style="margin:12px 0;">{svg}</div>'

                    text_html = self._text_to_html(psec.text_content)
                    cards.append(
                        f'<div class="paper-card" style="border-left-color:{color};">'
                        f'<h3 style="color:{color};">{esc(psec.title)}</h3>'
                        f'{text_html}'
                        f'{fig_html}'
                        f'</div>'
                    )

                sec_num = section_numbers.get(paper_card_indices[0], 2)
                span = ' span-full' if bw > 55 else ''
                panels_html += (
                    f'<div class="panel{span}">'
                    f'<div class="panel-inner section-card">'
                    f'<h2 class="section-heading">'
                    f'<span class="section-num">{sec_num}</span>'
                    f'논문별 분석</h2>'
                    f'<div class="paper-grid">{"".join(cards)}</div>'
                    f'</div></div>'
                )
                continue

            # ── 일반 섹션 (OVERVIEW, COMPARISON, FINDINGS, CONCLUSION) ──
            coords = layout_map[idx]
            pw = coords["w"]

            sec_num = section_numbers.get(idx, 1)
            heading_title = _role_titles.get(sec.role, sec.title) or sec.title

            # figure HTML
            fig_html = ''.join(
                self._render_figure_html(fp, autofigure_svgs, figures)
                for fp in sec.figures
            )

            # 섹션 역할별 특수 처리
            if sec.role == SectionRole.OVERVIEW and not fig_html:
                methodology = getattr(content, 'methodology', '') if content else ''
                if not methodology:
                    methodology = ''
                steps = visual_agent._parse_methodology_steps(methodology)
                if steps:
                    svg = visual_agent.generate_pipeline_diagram(steps)
                    fig_html = (
                        f'<div style="margin:12px 0;">{svg}'
                        f'<p style="font-size:0.8rem;color:#64748b;'
                        f'text-align:center;margin-top:6px;">'
                        f'연구 파이프라인 다이어그램</p></div>'
                    )

            if sec.role == SectionRole.COMPARISON:
                content_html = self._markdown_table_to_html(sec.text_content)
            else:
                content_html = self._text_to_html(sec.text_content)

            span = ' span-full' if pw > 55 else ''
            panels_html += (
                f'<div class="panel{span}">'
                f'<div class="panel-inner section-card">'
                f'<h2 class="section-heading">'
                f'<span class="section-num">{sec_num}</span>'
                f'{esc(heading_title)}</h2>'
                f'{content_html}'
                f'{fig_html}'
                f'</div></div>'
            )

        return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(composition.title)} - Academic Poster</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="stylesheet" as="style" crossorigin
  href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" />
<style>
/* ================================================================
   NeurIPS / ICML / CVPR — Academic Poster Template
   Aspect ratio: 4:3 landscape (48" × 36" equivalent)
   ================================================================ */
:root {{
  --font-main: 'Pretendard Variable', 'Pretendard', -apple-system, BlinkMacSystemFont,
               'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  /* brand colours */
  --c-header-bg:   #1B2A4A;
  --c-header-text: #FFFFFF;
  --c-primary:     #2563EB;
  --c-secondary:   #059669;
  --c-accent-muted:#DBEAFE;
  /* content */
  --c-bg:          #FAFAFA;
  --c-card:        #FFFFFF;
  --c-border:      #E5E7EB;
  --c-text:        #1A1A1A;
  --c-text-sub:    #374151;
  --c-text-muted:  #6B7280;
  --c-caption:     #555555;
  /* geometry */
  --radius-card:   8px;
  --radius-modal:  12px;
  --gap:           1.5rem;
  --pad-card:      1.5rem;
}}

*,*::before,*::after {{ box-sizing: border-box; }}

body {{
  font-family: var(--font-main);
  background: #D1D5DB;
  margin: 0;
  padding: 2rem;
  color: var(--c-text);
  font-size: 0.92rem;
  line-height: 1.65;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  word-break: keep-all;
  overflow-wrap: break-word;
  overflow-x: auto;       /* 좁은 뷰포트에서 가로 스크롤 */
}}

/* ── Poster shell — wide format, height grows with content ── */
.poster {{
  width: 100%;
  min-width: 1200px;
  max-width: 1800px;
  margin: 0 auto;
  background: var(--c-bg);
  border-radius: var(--radius-modal);
  box-shadow: 0 8px 40px rgba(0,0,0,0.18);
  display: flex;
  flex-direction: column;
}}

/* ================================================================
   HEADER — full-width dark bar
   ================================================================ */
.poster-header {{
  background: var(--c-header-bg);
  color: var(--c-header-text);
  padding: 2rem 3rem 1.75rem;
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 2rem;
  flex-shrink: 0;
}}
.poster-header-left {{
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  min-width: 80px;
}}
.conference-badge {{
  background: rgba(255,255,255,0.15);
  border: 1px solid rgba(255,255,255,0.3);
  border-radius: 6px;
  padding: 0.35rem 0.75rem;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #93C5FD;
  white-space: nowrap;
}}
.poster-header-center {{
  text-align: center;
}}
.poster-header h1 {{
  font-size: clamp(1.6rem, 2.8vw, 3.5rem);
  font-weight: 800;
  color: var(--c-header-text);
  margin: 0 0 0.5rem;
  letter-spacing: -0.02em;
  line-height: 1.2;
}}
.poster-header .subtitle {{
  font-size: clamp(0.85rem, 1.1vw, 1.2rem);
  font-weight: 400;
  color: rgba(255,255,255,0.82);
  margin: 0;
  line-height: 1.5;
}}
.poster-header-right {{
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  min-width: 80px;
}}
.credit-badge {{
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.2);
  border-radius: 6px;
  padding: 0.35rem 0.75rem;
  font-size: 0.7rem;
  color: rgba(255,255,255,0.55);
  text-align: center;
  white-space: nowrap;
}}
.keyword-bar {{
  margin-top: 1rem;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.4rem;
}}
.keyword {{
  background: rgba(255,255,255,0.12);
  border: 1px solid rgba(255,255,255,0.25);
  color: #BFDBFE;
  padding: 0.2rem 0.75rem;
  border-radius: 20px;
  font-size: 0.75rem;
  font-weight: 500;
}}

/* ================================================================
   CONTENT AREA — Paper2Poster Binary-Tree Absolute Layout
   ================================================================ */
.poster-content {{
  background: var(--c-bg);
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--gap);
  padding: var(--gap);
  min-height: 60vw;         /* 와이드 비율 유지 (4:3 ≈ 75vw, 여유있게) */
}}

/* ── Panel — flow-based grid item ── */
.panel {{
  min-width: 0;
}}
.panel-inner {{
  width: 100%;
}}
.panel.span-full {{
  grid-column: 1 / -1;
}}

/* ================================================================
   SECTION CARD
   ================================================================ */
.section-card {{
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-card);
  padding: var(--pad-card);
  display: flex;
  flex-direction: column;
}}

/* Section heading — numbered, with underline accent */
.section-heading {{
  font-size: 1.35rem;
  font-weight: 700;
  color: var(--c-text);
  margin: 0 0 1rem;
  padding-bottom: 0.6rem;
  border-bottom: 2px solid var(--c-primary);
  display: flex;
  align-items: center;
  gap: 0.55rem;
  flex-shrink: 0;
}}
.section-num {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.7rem;
  height: 1.7rem;
  background: var(--c-primary);
  color: #fff;
  border-radius: 50%;
  font-size: 0.85rem;
  font-weight: 700;
  flex-shrink: 0;
}}

/* ================================================================
   PAPER CARDS — 2-column sub-grid
   ================================================================ */
.paper-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 1rem;
}}
.paper-card {{
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-left-width: 4px;
  border-radius: var(--radius-card);
  padding: 1.1rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}}
.paper-card h3 {{
  font-size: 0.95rem;
  font-weight: 700;
  margin: 0 0 0.5rem;
  line-height: 1.4;
}}

/* ================================================================
   TYPOGRAPHY — shared between section-card and paper-card
   ================================================================ */
.section-card h4,
.paper-card h4 {{
  font-size: 0.88rem;
  font-weight: 700;
  color: var(--c-text);
  margin: 0.9rem 0 0.3rem;
  padding-left: 0.6rem;
  border-left: 3px solid var(--c-accent-muted);
}}
.section-card p,
.paper-card p {{
  font-size: 0.88rem;
  line-height: 1.65;
  color: var(--c-text-sub);
  margin: 0.25rem 0;
}}
.section-card strong,
.paper-card strong {{
  font-weight: 600;
  color: var(--c-text);
}}
.section-card ul,
.paper-card ul {{
  list-style: none;
  padding-left: 0;
  margin: 0.4rem 0;
}}
.section-card li,
.paper-card li {{
  position: relative;
  padding: 0.2rem 0 0.2rem 1.1rem;
  font-size: 0.88rem;
  line-height: 1.6;
  color: var(--c-text-sub);
}}
.section-card li::before,
.paper-card li::before {{
  content: '';
  position: absolute;
  left: 0;
  top: 0.55rem;
  width: 5px;
  height: 5px;
  background: var(--c-primary);
  border-radius: 50%;
}}

/* ================================================================
   TABLE — comparison section
   ================================================================ */
.section-card table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
  margin: 0.75rem 0;
}}
.section-card th {{
  padding: 0.5rem 0.85rem;
  text-align: left;
  font-weight: 600;
  color: var(--c-text);
  border-bottom: 2px solid var(--c-primary);
  background: #F3F4F6;
}}
.section-card td {{
  padding: 0.45rem 0.85rem;
  border-bottom: 1px solid var(--c-border);
  color: var(--c-text-sub);
}}
.section-card tbody tr:nth-child(even) td {{ background: #F9FAFB; }}
.section-card tbody tr:hover td {{ background: #EFF6FF; }}

/* ================================================================
   FIGURES
   ================================================================ */
.section-card figure,
.paper-card figure {{
  margin: 0.75rem 0;
  text-align: center;
}}
.section-card figcaption,
.paper-card figcaption {{
  font-size: 0.8rem;
  color: var(--c-caption);
  margin-top: 0.4rem;
  font-style: italic;
}}
.section-card img,
.paper-card img {{
  max-width: 100%;
  height: auto;
  border-radius: var(--radius-card);
  border: 1px solid var(--c-border);
}}

/* ================================================================
   FOOTER — full-width references bar
   ================================================================ */
.poster-footer {{
  background: #F3F4F6;
  border-top: 1px solid var(--c-border);
  padding: 0.75rem 2rem;
  display: flex;
  align-items: baseline;
  gap: 2rem;
  flex-shrink: 0;
}}
.footer-refs {{
  flex: 1;
  font-size: 0.75rem;
  color: var(--c-text-muted);
  line-height: 1.55;
}}
.footer-refs strong {{
  color: var(--c-text-sub);
  font-weight: 600;
}}
.footer-credit {{
  font-size: 0.7rem;
  color: #9CA3AF;
  white-space: nowrap;
}}
</style>
</head>
<body>
<div class="poster">

  <!-- ── HEADER ─────────────────────────────────────────────── -->
  <header class="poster-header">
    <div class="poster-header-left">
      <span class="conference-badge">Academic<br>Poster</span>
    </div>
    <div class="poster-header-center">
      <h1>{esc(composition.title)}</h1>
      <p class="subtitle">{esc(composition.subtitle)}</p>
      <div class="keyword-bar">{keywords_html}</div>
    </div>
    <div class="poster-header-right">
      <span class="credit-badge">PaperReview<br>Agent</span>
    </div>
  </header>

  <!-- ── CONTENT — Binary-Tree Layout ──────────────────────────── -->
  <main class="poster-content">
    {panels_html}
  </main>

  <!-- ── FOOTER ──────────────────────────────────────────────── -->
  <footer class="poster-footer">
    <div class="footer-refs">
      <strong>참고문헌</strong>&ensp;논문 검색 및 분석 결과는 arXiv, Google Scholar 등의 공개 데이터를 기반으로 합니다.
    </div>
    <span class="footer-credit">Generated by PaperReviewAgent</span>
  </footer>

</div>
</body>
</html>'''

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
                return f'''<div style="margin:12px 0;text-align:center;">
                    {svg}
                    <p style="font-size:0.8rem;color:#64748b;margin-top:6px;">{self._esc(fp.caption)}</p>
                </div>'''
        elif fp.source == 'paper_figure' and fp.figure_index < len(figures):
            fig = figures[fp.figure_index]
            b64 = fig.get('image_base64', '') if isinstance(fig, dict) else getattr(fig, 'image_base64', '')
            if b64:
                return f'''<figure style="margin:12px 0;">
                    <img src="data:image/png;base64,{b64}" style="width:100%;border-radius:8px;" alt="{self._esc(fp.caption)}" />
                    <figcaption style="font-size:0.78rem;color:#64748b;margin-top:6px;">{self._esc(fp.caption)}</figcaption>
                </figure>'''
        return ''

    def _text_to_html(self, text: str) -> str:
        """마크다운 텍스트를 HTML로 변환한다 (CSS 클래스 기반)."""
        import re
        lines = text.strip().split('\n')
        parts = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith('- ') or stripped.startswith('* '):
                item = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', stripped[2:])
                parts.append(f'<li>{item}</li>')
            elif stripped.startswith('**') and stripped.endswith('**'):
                parts.append(f'<h4>{self._esc(stripped.strip("*"))}</h4>')
            elif stripped.startswith('**'):
                clean = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', stripped)
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
    def _rows_to_table(rows: List[List[str]]) -> str:
        """행 리스트를 HTML 테이블로 변환한다."""
        if not rows:
            return ''
        header = rows[0]
        body = rows[1:]
        th = ''.join(f'<th>{h}</th>' for h in header)
        trs = []
        for row in body:
            tds = ''.join(f'<td>{c}</td>' for c in row)
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
