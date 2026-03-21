"""
Poster Critic Agent

Rule-based + Gemini 기반 포스터 비평 에이전트.
포스터 HTML을 분석하여 품질 점수, 개선 제안, 구조 이슈를 반환한다.
"""

import re
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass
class CritiqueResult:
    """비평 결과 데이터클래스"""
    score: float  # 0.0-1.0
    suggestions: str  # "No changes needed." 또는 상세 피드백
    revised_description: str  # 수정 방향
    metrics: Dict[str, float] = field(default_factory=dict)  # readability, density, balance, design, academic
    structural_issues: List[str] = field(default_factory=list)  # HTML/CSS 구조 문제


class PosterCriticAgent:
    """
    학술 포스터 비평 에이전트

    round_idx == 0 또는 LLM 없음 → rule-based 비평 (API 비용 0)
    round_idx >= 1 + LLM 있음 → Gemini 텍스트 비평
    """

    def __init__(self, gemini_llm=None):
        """
        Args:
            gemini_llm: google.generativeai.GenerativeModel 인스턴스 (옵션)
        """
        self.llm = gemini_llm

    def critique(self, poster_html: str, style_guide: str = "", round_idx: int = 0) -> CritiqueResult:
        """
        포스터 비평 수행.

        Args:
            poster_html: 포스터 HTML 전문
            style_guide: 스타일 가이드 텍스트
            round_idx: 현재 비평 라운드 (0-based)

        Returns:
            CritiqueResult
        """
        if round_idx == 0 or self.llm is None:
            return self._rule_based_critique(poster_html)
        return self._gemini_critique(poster_html, style_guide)

    def _rule_based_critique(self, html: str) -> CritiqueResult:
        """
        Rule-based 구조 분석. API 비용 0.

        검사 항목:
        - DOCTYPE 존재
        - <style> 태그 존재 및 CSS 규칙 수
        - SVG 요소 수
        - 섹션 수 (section-box, section 등)
        - Grid 레이아웃 사용 여부
        - figure/img 태그 존재
        - 콘텐츠 길이
        - 폰트 import 여부
        """
        issues: List[str] = []
        metrics: Dict[str, float] = {}

        # 1. DOCTYPE 체크
        has_doctype = html.strip().upper().startswith("<!DOCTYPE")
        if not has_doctype:
            issues.append("Missing <!DOCTYPE html> declaration")

        # 2. <style> 태그 체크
        style_blocks = re.findall(r'<style[^>]*>(.*?)</style>', html, re.DOTALL | re.IGNORECASE)
        css_content = " ".join(style_blocks)
        css_rule_count = len(re.findall(r'\{[^}]+\}', css_content))
        if css_rule_count < 10:
            issues.append(f"Insufficient CSS rules ({css_rule_count}). Expected at least 10 for a polished poster.")
        metrics["design"] = min(css_rule_count / 30.0, 1.0)

        # 3. SVG 수
        svg_count = len(re.findall(r'<svg[\s>]', html, re.IGNORECASE))
        if svg_count < 1:
            issues.append("No SVG visualizations found. Academic posters should include charts or diagrams.")
        metrics["balance"] = min(svg_count / 3.0, 1.0)

        # 4. 섹션 수
        section_patterns = [
            r'class=["\'][^"\']*section[-_]?box[^"\']*["\']',
            r'class=["\'][^"\']*section[-_]?title[^"\']*["\']',
            r'<section[\s>]',
        ]
        section_count = sum(len(re.findall(p, html, re.IGNORECASE)) for p in section_patterns)
        # 최소 div 기반 구조도 카운트
        if section_count < 3:
            div_count = html.count('<div')
            section_count = max(section_count, div_count // 5)  # rough estimate
        if section_count < 4:
            issues.append(f"Too few content sections ({section_count}). Expected at least 4.")
        metrics["density"] = min(section_count / 8.0, 1.0)

        # 5. Grid 레이아웃
        has_grid = bool(re.search(r'grid-template-columns|display:\s*grid', html, re.IGNORECASE))
        if not has_grid:
            issues.append("No CSS Grid layout detected. Multi-column layout is recommended.")

        # 6. Figure/이미지 — base64 직삽입 여부 체크
        img_count = len(re.findall(r'<img[\s>]', html, re.IGNORECASE))
        has_base64_images = 'data:image' in html
        if img_count > 0 and not has_base64_images:
            issues.append("Images use external URLs instead of base64 data URIs — they may not render.")

        # 6.5. 플레이스홀더 잔류 체크
        if '<!-- VISUALIZATIONS_PLACEHOLDER -->' in html:
            issues.append("Visualization placeholder was not replaced — SVGs missing.")
        if '<!-- FIGURES_PLACEHOLDER -->' in html:
            issues.append("Figures placeholder was not replaced — paper figures missing.")
        if 'FIGURE_' in html and 'BASE64' in html:
            issues.append("Figure base64 placeholders (FIGURE_N_BASE64) were not replaced.")

        # 7. 콘텐츠 길이
        # 태그 제거 후 텍스트 길이 추정
        text_only = re.sub(r'<[^>]+>', '', html)
        text_only = re.sub(r'\s+', ' ', text_only).strip()
        text_length = len(text_only)
        if text_length < 500:
            issues.append(f"Content too short ({text_length} chars). Academic posters need substantial text.")
        elif text_length > 15000:
            issues.append(f"Content may be too dense ({text_length} chars). Consider summarizing.")
        metrics["readability"] = min(max(text_length - 300, 0) / 5000.0, 1.0)

        # 8. 폰트 import
        has_font_import = bool(re.search(r'fonts\.googleapis\.com|@font-face|@import.*font', html, re.IGNORECASE))
        if not has_font_import:
            issues.append("No web font import found. Consider using Google Fonts for better typography.")

        # 9. 학술 요소
        academic_keywords = ['abstract', 'methodology', 'conclusion', 'results', 'findings', 'contribution']
        found_academic = sum(1 for kw in academic_keywords if kw.lower() in html.lower())
        metrics["academic"] = min(found_academic / 4.0, 1.0)
        if found_academic < 2:
            issues.append("Missing standard academic sections (Abstract, Methodology, Results, etc.).")

        # 종합 점수 계산
        score = sum(metrics.values()) / max(len(metrics), 1)

        # 패널티 적용
        penalty = len(issues) * 0.05
        score = max(score - penalty, 0.0)

        if not issues:
            return CritiqueResult(
                score=min(score + 0.1, 1.0),
                suggestions="No changes needed.",
                revised_description="The poster meets structural quality standards.",
                metrics=metrics,
                structural_issues=[],
            )

        suggestions = "Structural improvements needed:\n" + "\n".join(f"- {issue}" for issue in issues)
        revised_description = (
            "Fix the following: " + "; ".join(issues[:3])
        )

        return CritiqueResult(
            score=score,
            suggestions=suggestions,
            revised_description=revised_description,
            metrics=metrics,
            structural_issues=issues,
        )

    def _gemini_critique(self, html: str, style_guide: str) -> CritiqueResult:
        """
        Gemini 텍스트 기반 비평. 스크린샷 없이 HTML 분석.

        Args:
            html: 포스터 HTML 전문
            style_guide: 스타일 가이드 텍스트

        Returns:
            CritiqueResult
        """
        style_section = f"\n## Style Guide (evaluate against these rules)\n{style_guide}" if style_guide else ""

        prompt = f"""You are an expert academic conference poster critic specializing in NeurIPS, ICML, and ICLR poster design.

Evaluate the following HTML poster and provide structured feedback.

## Evaluation Dimensions
1. **Faithfulness** (0.0-1.0): Does the poster accurately represent the research content?
2. **Readability** (0.0-1.0): Is the text legible, well-organized, and easy to scan?
3. **Aesthetics** (0.0-1.0): Is the design visually appealing with good color choices and layout?
4. **Academic Standards** (0.0-1.0): Does it follow academic poster conventions?
5. **Visual Balance** (0.0-1.0): Is there a good balance of text, charts, and white space?
{style_section}

## Poster HTML
```html
{html[:20000]}
```

## Response Format
Respond ONLY with valid JSON (no markdown, no extra text):
{{
  "score": <float 0.0-1.0, overall quality>,
  "suggestions": "<specific improvements or 'No changes needed.' if score >= 0.85>",
  "revised_description": "<brief description of what to fix>",
  "metrics": {{
    "faithfulness": <float>,
    "readability": <float>,
    "aesthetics": <float>,
    "academic": <float>,
    "balance": <float>
  }}
}}"""

        try:
            response = self.llm.generate_content(prompt)
            text = response.text.strip()

            # JSON 추출 (마크다운 코드 블록 제거)
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError) as e:
                print(f"[WARNING] Gemini returned malformed JSON, falling back to rule-based: {e}")
                logger.warning("[PosterCritic] Failed to parse Gemini response as JSON: %s", e)
                return self._rule_based_critique(html)

            score = float(data.get("score", 0.5))
            suggestions = data.get("suggestions", "Unable to parse critique.")

            return CritiqueResult(
                score=score,
                suggestions=str(suggestions),
                revised_description=str(data.get("revised_description", "")),
                metrics={k: float(v) for k, v in data.get("metrics", {}).items()},
                structural_issues=[],
            )

        except Exception as e:
            logger.warning("[PosterCritic] Gemini critique failed: %s", e)
            return self._rule_based_critique(html)
