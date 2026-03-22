"""
Enhanced Poster Agent (Orchestrator)

Paper2Poster 방법론 기반의 멀티 에이전트 포스터 생성 시스템
각 에이전트의 작업을 조율하고 통합하는 오케스트레이터
"""

import json
import logging
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# 하위 에이전트 임포트
from .poster_content_agent import PosterContentAgent
from .poster_composition_agent import PosterCompositionAgent
from .poster_layout_agent import PosterLayoutAgent
from .poster_visual_agent import PosterVisualAgent
from .poster_validator_agent import PosterValidatorAgent
from .poster_critic_agent import PosterCriticAgent, CritiqueResult

# 스타일 매니저 (동적 임포트)
import sys
config_path = Path(__file__).parent.parent / "config"
if str(config_path) not in sys.path:
    sys.path.insert(0, str(config_path))

try:
    from style_manager import StyleManager  # type: ignore
except ImportError:
    # Fallback: 직접 임포트 시도
    import importlib.util
    spec = importlib.util.spec_from_file_location("style_manager", config_path / "style_manager.py")
    if spec and spec.loader:
        style_manager_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(style_manager_module)
        StyleManager = style_manager_module.StyleManager  # type: ignore
    else:
        raise ImportError("Cannot load StyleManager")


class PosterGenerationAgent:
    """
    멀티 에이전트 포스터 생성 오케스트레이터

    아키텍처:
    1. ContentAgent: 리포트에서 구조화된 콘텐츠 추출
    2. LayoutAgent: 콘텐츠 기반 레이아웃 계획 수립
    3. VisualAgent: 섹션별 SVG/HTML 생성 (병렬 처리)
    4. ValidatorAgent: VLM 기반 품질 검증 (옵션)

    참조: https://github.com/Paper2Poster/Paper2Poster
    """

    def __init__(
        self,
        model: str = "gemini-2.5-flash-preview-05-20",
        api_key: Optional[str] = None,
        max_workers: int = 4,
        enable_validation: bool = False,
        theme: str = "default",
        design_pattern_manager=None,
        enable_critic: bool = True,
        max_critic_rounds: int = 2
    ):
        """
        Args:
            model: Gemini 모델 이름 (기본값: gemini-2.5-flash-preview-05-20)
            api_key: Google API 키
            max_workers: 병렬 처리 워커 수
            enable_validation: VLM 품질 검증 활성화
            theme: YAML 테마 이름 (default, academic_blue, dark_theme 등)
            design_pattern_manager: DesignPatternManager 인스턴스 (옵션)
            enable_critic: Critic 반복 루프 활성화
            max_critic_rounds: 최대 비평 라운드 수
        """
        self.model = model
        self.api_key = api_key or os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')
        self.max_workers = max_workers
        self.enable_validation = enable_validation
        self.theme = theme
        self.enable_critic = enable_critic
        self.max_critic_rounds = max_critic_rounds

        # DesignPatternManager 설정
        if design_pattern_manager is None:
            try:
                from app.DeepAgent.config.design_pattern_manager import get_design_pattern_manager
                self.pattern_manager = get_design_pattern_manager()
            except Exception:
                self.pattern_manager = None
        else:
            self.pattern_manager = design_pattern_manager

        # Gemini LLM 초기화
        self.llm = None
        if self.api_key:
            self._initialize_gemini()

        # Critic 에이전트 초기화
        self.critic_agent = PosterCriticAgent(gemini_llm=self.llm) if enable_critic else None

        # StyleGuideManager 초기화
        self.style_guide_manager = None
        try:
            from app.DeepAgent.config.style_guide_manager import StyleGuideManager
            self.style_guide_manager = StyleGuideManager()
        except Exception:
            pass

        # 스타일 매니저 초기화 (권한 오류 시 기본값 사용)
        try:
            self.style_manager = StyleManager()
        except (OSError, PermissionError, ImportError):
            # StyleManager 초기화 실패 시 None으로 설정 (기본 CSS 사용)
            self.style_manager = None

        # 하위 에이전트 초기화 (DesignPatternManager 전달)
        self.content_agent = PosterContentAgent()
        self.composition_agent = PosterCompositionAgent()
        self.layout_agent = PosterLayoutAgent(design_pattern_manager=self.pattern_manager)
        self.visual_agent = PosterVisualAgent()
        self.validator_agent = PosterValidatorAgent() if enable_validation else None

        # PaperBanana 클라이언트 (우선)
        self._paperbanana_client = None
        try:
            from app.DeepAgent.tools.paperbanana_client import get_paperbanana_client
            client = get_paperbanana_client()
            if client.is_available():
                self._paperbanana_client = client
        except ImportError:
            pass

        # AutoFigure-Edit 클라이언트 (PaperBanana 미가용 시 fallback)
        self._autofigure_client = None
        try:
            from app.DeepAgent.tools.autofigure_client import get_autofigure_client
            self._autofigure_client = get_autofigure_client()
        except ImportError:
            pass

    def _initialize_gemini(self):
        """Gemini LLM 초기화"""
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.llm = genai.GenerativeModel(self.model)
            logger.info("Gemini LLM 초기화 성공: %s", self.model)
        except ImportError:
            logger.warning("google-generativeai 패키지 미설치 — pip install google-generativeai 필요")
            self.llm = None
        except Exception as e:
            logger.warning("Gemini LLM 초기화 실패: %s", e)
            self.llm = None

    def _get_style_guide(self, content=None) -> str:
        """스타일 가이드 텍스트 반환"""
        if not self.style_guide_manager:
            return ""
        try:
            domain = "general"
            if content and hasattr(content, 'keywords'):
                domain = self.style_guide_manager.detect_domain(content.keywords)
            return self.style_guide_manager.get_guide(domain)
        except Exception:
            return ""

    def _critic_loop(self, poster_html: str, style_guide: str, max_rounds: int = 2) -> tuple:
        """
        Critic 반복 루프: 비평 → 수정 사이클.

        Args:
            poster_html: 초기 포스터 HTML
            style_guide: 스타일 가이드 텍스트
            max_rounds: 최대 라운드 수

        Returns:
            (최종 HTML, 최종 점수) 튜플
        """
        current_best = poster_html
        score = 0.0

        for round_idx in range(max_rounds):
            logger.info("Critic loop round %d/%d", round_idx + 1, max_rounds)
            critique = self.critic_agent.critique(poster_html, style_guide, round_idx)
            score = critique.score
            logger.info("Critic score: %.2f", score)

            if critique.suggestions.strip() == "No changes needed.":
                logger.info("Critic: No changes needed. Exiting loop.")
                break
            if score >= 0.85:
                logger.info("Score %.2f >= 0.85. Exiting loop.", score)
                break

            try:
                refined = self._refine_with_gemini(poster_html, critique, style_guide)
                poster_html = refined
                current_best = refined
                logger.info("Refinement applied (round %d)", round_idx + 1)
            except Exception as e:
                logger.warning("Refinement failed: %s. Rolling back to previous best.", e)
                poster_html = current_best
                break

        return current_best, score

    def _refine_with_gemini(self, poster_html: str, critique: 'CritiqueResult', style_guide: str) -> str:
        """
        Gemini에 원본 HTML + 비평 피드백 전송 → 수정된 HTML 반환.

        Args:
            poster_html: 현재 포스터 HTML
            critique: CritiqueResult 비평 결과
            style_guide: 스타일 가이드 텍스트

        Returns:
            수정된 HTML
        """
        if not self.llm:
            raise RuntimeError("Gemini LLM not available for refinement")

        style_section = f"\n## Style Guide\n{style_guide}" if style_guide else ""

        prompt = f"""You are an expert academic poster designer. Refine the following HTML poster based on critic feedback.

## Critic Feedback
- **Score**: {critique.score:.2f}/1.0
- **Suggestions**: {critique.suggestions}
- **Focus areas**: {critique.revised_description}
- **Metrics**: {json.dumps(critique.metrics) if hasattr(critique, 'metrics') else '{}'}
{style_section}

## Current Poster HTML
```html
{poster_html[:25000]}
```

## Instructions
1. Apply the critic's suggestions to improve the poster
2. Keep the overall structure and content intact
3. Focus on the specific issues mentioned in the feedback
4. Output ONLY the complete, refined HTML (no explanations, no markdown fences)
5. Ensure the output starts with <!DOCTYPE html>

Output the refined HTML now:"""


        response = self.llm.generate_content(prompt)
        refined_html = response.text

        # HTML 코드만 추출
        if "```html" in refined_html:
            refined_html = refined_html.split("```html")[1].split("```")[0]
        elif "```" in refined_html:
            parts = refined_html.split("```")
            if len(parts) > 1:
                refined_html = parts[1]

        refined_html = refined_html.strip()

        if not refined_html.startswith("<!DOCTYPE") and not refined_html.startswith("<html"):
            refined_html = f"<!DOCTYPE html>\n<html lang='ko'>\n{refined_html}\n</html>"

        return refined_html

    def _get_style_guide_prompt(self, content=None) -> str:
        """스타일 가이드를 Gemini 프롬프트 형식으로 반환"""
        guide = self._get_style_guide(content)
        if not guide:
            return ""
        return f"""---

## Style Guide (follow these rules strictly)

{guide}
"""

    def _get_reference_poster_prompt(self, content=None) -> str:
        """참조 포스터를 Gemini 프롬프트 형식으로 반환"""
        if not self.pattern_manager:
            return ""
        try:
            if not hasattr(self.pattern_manager, 'select_reference_poster'):
                return ""
            content_analysis = {}
            if content:
                content_analysis = {
                    'keywords': getattr(content, 'keywords', []),
                    'has_pipeline': 'pipeline' in getattr(content, 'methodology', '').lower(),
                    'has_performance_metrics': bool(getattr(content, 'visualization_data', None)),
                }
            ref_html = self.pattern_manager.select_reference_poster(content_analysis)
            if not ref_html:
                return ""
            # 참조 HTML 스니펫 (너무 길면 축소)
            snippet = ref_html[:8000]
            return f"""---

## Reference Poster Example
Below is a high-quality poster HTML structure. Adapt the structure, NOT the content:
```html
{snippet}
```
"""
        except Exception:
            return ""

    def generate_poster(
        self,
        report_content: str,
        num_papers: int = 0,
        output_dir: Optional[Path] = None,
        papers_data: Optional[List[Dict[str, Any]]] = None
    ) -> dict:
        """
        멀티 에이전트 파이프라인으로 포스터 생성

        Pipeline:
        0.5. Figure Extraction (논문 삽도 추출)
        1. Content Extraction (순차)
        2. Layout Planning (순차)
        3. Visual Generation (병렬)
        4. Assembly (순차)
        5. Validation (순차, 옵션)
        6. Refinement (순차, 조건부)

        Args:
            report_content: 마크다운 형식의 리포트
            num_papers: 분석된 논문 수
            output_dir: 저장 디렉토리 (옵션)
            papers_data: 논문 데이터 리스트 (pdf_url, arxiv_id 포함, 삽도 추출용)

        Returns:
            dict: {
                "success": bool,
                "poster_html": str,
                "poster_path": str,
                "validation_score": float
            }
        """
        try:
            # Phase 0.5: Figure Extraction (논문 삽도 추출)
            figures = []
            figure_data = []
            if papers_data:
                figures = self._extract_paper_figures(papers_data)
                if figures:
                    figure_data = [
                        {
                            "image_base64": f.image_base64,
                            "mime_type": f.mime_type,
                            "caption": f.caption,
                            "description": f.description,
                            "relevance_score": f.relevance_score,
                            "paper_title": f.paper_title,
                            "width": f.width,
                            "height": f.height,
                        }
                        for f in figures
                    ]
                    logger.info("%d개 핵심 삽도 추출 완료", len(figure_data))

            # Phase 1: Content Extraction (멀티 에이전트)
            content = self.content_agent.extract(report_content, num_papers, figures=figure_data)

            # Phase 1.5: 다이어그램 생성 (PaperBanana → AutoFigure fallback)
            autofigure_svgs = self._generate_autofigure_svgs(content)
            if autofigure_svgs:
                logger.info("다이어그램: %d개 생성 완료", len(autofigure_svgs))

            # Phase 2: Composition Design (콘텐츠-figure 통합 구성 설계)
            composition = self.composition_agent.design(content, autofigure_svgs, figure_data)
            logger.info(
                "Composition: %d sections, %d figures 배치",
                composition.total_text_sections,
                composition.total_figures,
            )

            # Phase 3: Gemini를 사용한 포스터 생성
            layout = self.layout_agent.plan(content)
            if self.llm:
                poster_html = self._generate_with_composition(
                    composition, content, layout, report_content, num_papers,
                    autofigure_svgs=autofigure_svgs, figures=figure_data,
                )
            else:
                # Gemini 사용 불가 시 멀티 에이전트 방식 사용
                if autofigure_svgs:
                    self.visual_agent = PosterVisualAgent(autofigure_svgs=autofigure_svgs)
                section_htmls = self._generate_sections_parallel(layout.sections)
                poster_html = self._assemble_poster(content, layout, section_htmls)
                poster_html = self._inject_visuals_into_poster(poster_html, content, figure_data, autofigure_svgs)

            # Phase 4: Critic Loop (반복 비평 → 수정)
            validation_score = 0.8
            if self.enable_critic and self.critic_agent:
                style_guide = self._get_style_guide(content)
                poster_html, validation_score = self._critic_loop(
                    poster_html,
                    style_guide=style_guide,
                    max_rounds=self.max_critic_rounds,
                )
            elif self.enable_validation and self.validator_agent:
                validation = self.validator_agent.validate(poster_html)
                validation_score = validation.score

                # Phase 5: Refinement (조건부)
                if validation_score < 0.75:
                    poster_html = self._refine_poster(poster_html, validation.suggestions)

            # 결과 반환
            result = {
                "success": True,
                "poster_html": poster_html,
                "poster_path": None,
                "validation_score": validation_score
            }

            # 저장
            if output_dir:
                result["poster_path"] = self._save_poster(poster_html, output_dir)

            return result

        except Exception as e:
            logger.error("포스터 생성 실패, fallback 사용: %s", e, exc_info=True)

            # Fallback
            return {
                "success": False,
                "poster_html": self._generate_simple_fallback(report_content, num_papers),
                "poster_path": None,
                "validation_score": 0.5,
                "error": str(e)
            }

    def _generate_autofigure_svgs(self, content) -> List[Dict[str, Any]]:
        """PaperBanana 또는 AutoFigure-Edit로 방법론 다이어그램을 생성한다.

        PaperBanana가 가용하면 우선 사용하고, 그렇지 않으면 AutoFigure-Edit로
        fallback한다. 생성된 다이어그램은 PNG(base64)와 선택적 SVG로 반환된다.

        Args:
            content: ExtractedContent 객체

        Returns:
            [{"paper_title": str, "svg_content": str, "figure_png_b64": str}, ...]
        """
        # PaperBanana 우선 시도
        if self._paperbanana_client:
            results = self._generate_with_paperbanana(content)
            if results:
                return results
            logger.info("PaperBanana 생성 실패 — AutoFigure fallback 시도")

        if not self._autofigure_client:
            return []

        try:
            import asyncio
            from app.DeepAgent.tools.autofigure_client import (
                build_method_prompt,
                build_paper_figure_prompts,
            )

            paper_analyses = getattr(content, 'paper_analyses', []) or []

            # 전체 방법론 프롬프트 구성
            method_prompt = build_method_prompt(content, paper_analyses)
            # 논문별 프롬프트 구성
            paper_prompts = build_paper_figure_prompts(paper_analyses)[:2]  # 최대 2개

            async def _run() -> List[Dict[str, Any]]:
                # Health check: AutoFigure-Edit 서비스 가용성 확인
                if not await self._autofigure_client.health_check():
                    logger.warning("AutoFigure-Edit 서비스 미가용 — SVG 생성 건너뜀")
                    return []

                tasks = []
                task_labels: List[str] = []

                # 전체 방법론 SVG 생성 태스크
                if method_prompt.strip():
                    tasks.append(self._autofigure_client.method_to_svg(method_prompt))
                    task_labels.append("Overall Methodology")

                # 논문별 SVG 생성 태스크
                for prompt_info in paper_prompts:
                    tasks.append(
                        self._autofigure_client.method_to_svg(prompt_info["method_prompt"])
                    )
                    task_labels.append(prompt_info["paper_title"])

                if not tasks:
                    return []

                # 모든 태스크를 동시에 실행, 개별 실패를 허용
                raw_results = await asyncio.gather(*tasks, return_exceptions=True)

                results: List[Dict[str, Any]] = []
                for label, result in zip(task_labels, raw_results):
                    if isinstance(result, Exception):
                        logger.warning("AutoFigure SVG 생성 실패 (%s): %s", label, result)
                        continue
                    if result.success:
                        results.append({
                            "paper_title": label,
                            "svg_content": result.final_svg,
                            "figure_png_b64": result.figure_png_b64,
                        })

                return results

            # 이벤트 루프에서 비동기 실행
            try:
                asyncio.get_running_loop()
                # 이미 이벤트 루프 안이면 새 스레드에서 실행
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _run())
                    return future.result(timeout=300)
            except RuntimeError:
                return asyncio.run(_run())

        except Exception as e:
            logger.warning("AutoFigure SVG 생성 실패 (기존 방식으로 진행): %s", e)
            return []

    def _generate_with_paperbanana(self, content) -> List[Dict[str, Any]]:
        """PaperBanana로 방법론 다이어그램을 생성한다.

        PaperBanana의 멀티에이전트 파이프라인(Retriever → Planner → Stylist →
        Visualizer ↔ Critic)을 사용하여 학술 수준 다이어그램을 생성한다.

        Args:
            content: ExtractedContent 객체

        Returns:
            [{"paper_title": str, "svg_content": str, "figure_png_b64": str}, ...]
        """
        try:
            import asyncio
            from app.DeepAgent.tools.paperbanana_client import (
                build_diagram_caption,
                build_diagram_prompt,
                build_paper_diagram_inputs,
            )

            paper_analyses = getattr(content, 'paper_analyses', []) or []

            # 프롬프트 구성
            source_context = build_diagram_prompt(content, paper_analyses)
            caption = build_diagram_caption(content)
            paper_inputs = build_paper_diagram_inputs(paper_analyses)[:2]

            async def _run() -> List[Dict[str, Any]]:
                tasks = []
                task_labels: List[str] = []

                # 전체 방법론 다이어그램
                if source_context.strip():
                    tasks.append(
                        self._paperbanana_client.generate_diagram(source_context, caption)
                    )
                    task_labels.append("Overall Methodology")

                # 논문별 다이어그램
                for inp in paper_inputs:
                    tasks.append(
                        self._paperbanana_client.generate_diagram(
                            inp["source_context"], inp["caption"]
                        )
                    )
                    task_labels.append(inp["paper_title"])

                if not tasks:
                    return []

                raw_results = await asyncio.gather(*tasks, return_exceptions=True)

                results: List[Dict[str, Any]] = []
                for label, result in zip(task_labels, raw_results):
                    if isinstance(result, Exception):
                        logger.warning("PaperBanana 다이어그램 생성 실패 (%s): %s", label, result)
                        continue
                    if result.success and result.image_base64:
                        # PaperBanana는 PNG 이미지를 반환 → img 태그로 변환
                        img_html = (
                            f'<img src="data:image/png;base64,{result.image_base64}" '
                            f'style="max-width:100%; height:auto; border-radius:8px;" '
                            f'alt="{label}" />'
                        )
                        results.append({
                            "paper_title": label,
                            "svg_content": img_html,
                            "figure_png_b64": result.image_base64,
                        })

                return results

            # 이벤트 루프에서 비동기 실행
            try:
                asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _run())
                    return future.result(timeout=600)
            except RuntimeError:
                return asyncio.run(_run())

        except Exception as e:
            logger.warning("PaperBanana 다이어그램 생성 실패: %s", e)
            return []

    def _extract_paper_figures(self, papers_data: List[Dict[str, Any]]) -> list:
        """논문 PDF에서 핵심 삽도 추출"""
        try:
            from app.DeepAgent.tools.figure_extractor import extract_paper_figures
            figures = extract_paper_figures(
                papers_data=papers_data,
                api_key=self.api_key,
                max_papers=3
            )
            return figures
        except Exception as e:
            logger.warning("삽도 추출 실패 (기존 방식으로 진행): %s", e)
            return []

    def _generate_sections_parallel(self, sections: list) -> dict:
        """
        섹션별 HTML을 병렬로 생성

        Paper2Poster의 --max_workers 병렬 처리 구현
        """
        section_htmls = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 병렬 실행
            future_to_section = {
                executor.submit(self.visual_agent.generate_section, section): section
                for section in sections
            }

            # 결과 수집
            for future in as_completed(future_to_section):
                section = future_to_section[future]
                try:
                    html = future.result()
                    section_htmls[section.id] = {
                        'html': html,
                        'section': section
                    }
                except Exception:
                    section_htmls[section.id] = {
                        'html': '<p class="text-red-500">생성 실패</p>',
                        'section': section
                    }

        return section_htmls

    @staticmethod
    def _has_substantial_svg(html: str) -> bool:
        """포스터에 실질적인 SVG 다이어그램이 포함되어 있는지 확인한다.

        아이콘이나 작은 장식 SVG가 아닌, viewBox가 있고 일정 크기 이상인
        SVG 요소가 하나 이상 있으면 True를 반환한다.
        """
        for m in re.finditer(r'<svg[^>]*>', html, re.IGNORECASE):
            tag = m.group(0)
            # viewBox 기반 판정
            vb = re.search(r'viewBox\s*=\s*"([^"]*)"', tag, re.IGNORECASE)
            if vb:
                parts = vb.group(1).split()
                if len(parts) == 4:
                    try:
                        if float(parts[2]) >= 100 and float(parts[3]) >= 60:
                            return True
                    except (ValueError, IndexError):
                        pass
            # width/height 속성 기반 판정
            w_m = re.search(r'width\s*=\s*"(\d+)', tag, re.IGNORECASE)
            h_m = re.search(r'height\s*=\s*"(\d+)', tag, re.IGNORECASE)
            if w_m and h_m:
                try:
                    if int(w_m.group(1)) >= 100 and int(h_m.group(1)) >= 60:
                        return True
                except ValueError:
                    pass
        return False

    def _inject_visuals_into_poster(self, poster_html: str, content, figures, autofigure_svgs) -> str:
        """포스터 HTML에 보조 시각화 + Figure를 삽입한다.

        Gemini가 이미 인라인 SVG를 포함했으면 보조 시각화는 최소한으로 추가.
        Figure(논문 삽도)는 항상 삽입.
        """
        # Gemini가 실질적인 SVG 다이어그램을 이미 생성했는지 확인
        has_gemini_svg = self._has_substantial_svg(poster_html)

        # 보조 시각화: Gemini SVG가 없거나 AutoFigure SVG가 있을 때만
        if not has_gemini_svg or autofigure_svgs:
            viz_html = self._build_visualizations_html(content, autofigure_svgs)
            if viz_html:
                if "<!-- VISUALIZATIONS_PLACEHOLDER -->" in poster_html:
                    poster_html = poster_html.replace("<!-- VISUALIZATIONS_PLACEHOLDER -->", viz_html)
                elif viz_html not in poster_html:
                    poster_html = poster_html.replace("</body>", f"\n{viz_html}\n</body>")

        # Figure(논문 삽도)는 항상 삽입
        fig_html = self._build_figures_html(figures)
        if fig_html:
            if "<!-- FIGURES_PLACEHOLDER -->" in poster_html:
                poster_html = poster_html.replace("<!-- FIGURES_PLACEHOLDER -->", fig_html)
            elif fig_html not in poster_html:
                poster_html = poster_html.replace("</body>", f"\n{fig_html}\n</body>")

        return poster_html

    def _generate_with_composition(self, composition, content, layout,
                                    report_content: str, num_papers: int,
                                    autofigure_svgs: list = None, figures: list = None) -> str:
        """Composition 기반 Gemini 포스터 생성 — figure가 제자리에 배치된다."""
        prompt = self.composition_agent.to_gemini_prompt(composition, content)

        try:
            response = self.llm.generate_content([prompt])
            poster_html = response.text

            # HTML 코드 추출
            if "```html" in poster_html:
                poster_html = poster_html.split("```html")[1].split("```")[0]
            elif "```" in poster_html:
                parts = poster_html.split("```")
                if len(parts) > 1:
                    poster_html = parts[1]
            poster_html = poster_html.strip()

            if not poster_html.startswith("<!DOCTYPE") and not poster_html.startswith("<html"):
                poster_html = f"<!DOCTYPE html>\n<html lang='ko'>\n{poster_html}\n</html>"

            # Composition 기반 figure 삽입 (placeholder → 실제 콘텐츠)
            poster_html = self.composition_agent.inject_figures_by_composition(
                poster_html, composition, autofigure_svgs or [], figures or [],
            )

            return poster_html

        except Exception as e:
            logger.error("Composition 기반 Gemini 생성 실패, legacy fallback: %s", e, exc_info=True)
            return self._generate_with_gemini(
                content, layout, report_content, num_papers, figures, autofigure_svgs,
            )

    def _generate_with_gemini(self, content, layout, report_content: str, num_papers: int,
                              figures: list = None, autofigure_svgs: list = None) -> str:
        """Legacy: Gemini로 레이아웃 HTML 생성 후 SVG/Figure를 확정적으로 삽입한다."""
        report_summary = report_content[:12000]
        prompt = self._build_gemini_prompt(content, layout, report_summary, num_papers, figures)

        try:
            response = self.llm.generate_content([prompt])
            poster_html = response.text

            # HTML 코드 추출
            if "```html" in poster_html:
                poster_html = poster_html.split("```html")[1].split("```")[0]
            elif "```" in poster_html:
                parts = poster_html.split("```")
                if len(parts) > 1:
                    poster_html = parts[1]
            poster_html = poster_html.strip()

            if not poster_html.startswith("<!DOCTYPE") and not poster_html.startswith("<html"):
                poster_html = f"<!DOCTYPE html>\n<html lang='ko'>\n{poster_html}\n</html>"

            # 시각화 + Figure 확정 삽입 (플레이스홀더 유무와 무관)
            poster_html = self._inject_visuals_into_poster(poster_html, content, figures, autofigure_svgs)

            return poster_html

        except Exception as e:
            # Gemini 생성 실패 → 멀티에이전트 fallback
            logger.error("Gemini 포스터 생성 실패, 멀티에이전트 fallback: %s", e, exc_info=True)

            # AutoFigure SVG를 visual_agent에 전달하여 하이브리드 시각화 활용
            if autofigure_svgs:
                self.visual_agent = PosterVisualAgent(autofigure_svgs=autofigure_svgs)

            section_htmls = self._generate_sections_parallel(layout.sections)
            poster_html = self._assemble_poster(content, layout, section_htmls)

            # fallback에서도 시각화 확정 삽입
            poster_html = self._inject_visuals_into_poster(poster_html, content, figures, autofigure_svgs)

            return poster_html

    def _format_paper_analyses_prompt(self, content) -> str:
        """논문별 핵심 구조 분석 데이터를 프롬프트 형식으로 변환"""
        if not hasattr(content, 'paper_analyses') or not content.paper_analyses:
            return ""

        sections = []
        for i, paper in enumerate(content.paper_analyses[:6]):
            title = paper.get('title', f'논문 {i+1}')
            methodology = (paper.get('methodology', '') or '')[:800]
            contributions = (paper.get('contributions', '') or '')[:600]
            results = (paper.get('results', '') or '')[:600]

            if not (methodology or contributions or results):
                continue

            section = f"""
### {title}
"""
            if methodology:
                section += f"**핵심 방법론/아키텍처**: {methodology}\n"
            if contributions:
                section += f"**주요 기여**: {contributions}\n"
            if results:
                section += f"**실험 결과**: {results}\n"

            sections.append(section)

        if not sections:
            return ""

        return f"""
---

## 논문별 핵심 구조 (반드시 포스터에 반영하세요!)

**[최우선 과제]**: 아래 각 논문의 핵심 방법론, 아키텍처, 실험 결과를 포스터에 **구조도(Architecture Diagram)**로 반드시 표현하세요.

**각 논문에 대해 반드시 다음 SVG 구조도를 생성하세요:**

1. **알고리즘/아키텍처 구조도 (Architecture Diagram)**: 각 논문의 핵심 알고리즘 파이프라인을 SVG로 시각화
   - 입력(Input) -> 처리 단계(Processing Steps) -> 출력(Output) 흐름을 보여주는 플로우차트
   - 각 단계를 둥근 사각형(rounded rect) 박스로 표현
   - 단계 간 연결을 화살표(arrow)로 표시
   - 각 박스에 단계 이름과 핵심 설명 포함
   - 색상 구분으로 서로 다른 모듈/컴포넌트를 구분

2. **방법론 비교 다이어그램**: 논문들 간의 방법론 차이를 한눈에 비교할 수 있는 SVG 테이블 또는 비교 플로우차트

3. **실험 결과 차트**: 실험 결과의 수치 데이터를 SVG Bar Chart 또는 Radar Chart로 표현

**SVG 구조도 생성 규칙:**
- 각 논문마다 최소 1개의 알고리즘 파이프라인 SVG 다이어그램을 반드시 포함
- SVG viewBox를 적절히 설정하여 충분한 크기로 표현 (최소 600x300)
- 박스, 화살표, 텍스트를 사용한 명확한 플로우차트 형태
- 각 SVG에 논문 제목을 타이틀로 표시

{''.join(sections)}
"""

    def _format_comparison_tables_prompt(self, content) -> str:
        """비교 분석 테이블을 프롬프트 형식으로 변환"""
        if not hasattr(content, 'comparison_tables') or not content.comparison_tables:
            return ""

        tables_text = '\n\n'.join(content.comparison_tables[:3])

        return f"""
---

## 비교 분석 테이블 (포스터에 포함하세요)

아래 비교 테이블을 포스터의 핵심 섹션에 깔끔하게 스타일링하여 포함하세요.
테이블은 학술 포스터 스타일로 디자인하되, 원본 데이터를 정확히 반영하세요.

{tables_text}
"""

    @staticmethod
    def _safe_metric_str(m) -> str:
        """메트릭 딕셔너리를 안전한 문자열로 변환"""
        if not isinstance(m, dict):
            return str(m)
        name = str(m.get('name', ''))
        value = m.get('value', '')
        unit = str(m.get('unit', ''))
        try:
            value_str = f"{float(value):.4g}" if isinstance(value, (int, float)) else str(value)
        except (ValueError, TypeError):
            value_str = str(value)
        return f"{name}={value_str}{unit}"

    def _format_visualization_data_prompt(self, content) -> str:
        """구조화된 시각화 데이터를 Gemini 프롬프트 형식으로 변환"""
        viz_data = getattr(content, 'visualization_data', None)
        if not viz_data or not isinstance(viz_data, dict):
            return ""

        sections = []

        # 파이프라인 단계
        pipeline_steps = viz_data.get('pipeline_steps', [])
        if isinstance(pipeline_steps, list) and pipeline_steps:
            steps_text = ' → '.join(
                str(s.get('title', '')) if isinstance(s, dict) else str(s)
                for s in pipeline_steps
            )
            sections.append(f"**Research Pipeline**: {steps_text}")

        # 정량 데이터
        quant = viz_data.get('quantitative', {})
        if isinstance(quant, dict) and quant:
            metrics = quant.get('metrics', [])
            if isinstance(metrics, list) and metrics:
                metrics_lines = []
                for m in metrics[:10]:
                    if not isinstance(m, dict):
                        continue
                    metrics_lines.append(f"  - {self._safe_metric_str(m)}")
                if metrics_lines:
                    sections.append("**Key Metrics (차트에 사용하세요)**:\n" + '\n'.join(metrics_lines))

            improvements = quant.get('improvements', [])
            if isinstance(improvements, list) and improvements:
                imp_lines = []
                for imp in improvements[:6]:
                    if isinstance(imp, dict):
                        imp_lines.append(f"  - {imp.get('description', '')}")
                if imp_lines:
                    sections.append("**Performance Improvements**:\n" + '\n'.join(imp_lines))

        # 논문별 결과
        paper_results = viz_data.get('paper_results', [])
        if isinstance(paper_results, list) and paper_results:
            results_lines = []
            for r in paper_results[:5]:
                if not isinstance(r, dict):
                    continue
                title = str(r.get('paper_title', ''))
                r_metrics = r.get('metrics', [])
                if not isinstance(r_metrics, list):
                    continue
                metrics_str = ', '.join(
                    self._safe_metric_str(m) for m in r_metrics[:3] if isinstance(m, dict)
                )
                if metrics_str:
                    results_lines.append(f"  - {title}: {metrics_str}")
            if results_lines:
                sections.append("**Paper Results Data (Bar/Radar Chart에 활용)**:\n" + '\n'.join(results_lines))

        if not sections:
            return ""

        return f"""
---

## 구조화된 시각화 데이터 (반드시 차트/SVG 생성에 활용하세요)

아래 데이터는 리포트에서 자동 추출된 정량적 데이터입니다.
SVG 차트(Bar Chart, Radar Chart 등)를 생성할 때 이 데이터를 정확히 사용하세요.

{chr(10).join(sections)}
"""

    def _replace_figure_placeholders(self, poster_html: str, figures: list) -> str:
        """Gemini가 생성한 플레이스홀더를 실제 base64 데이터로 치환"""
        for i, fig in enumerate(figures[:4]):
            placeholder = f"FIGURE_{i+1}_BASE64"
            if placeholder in poster_html:
                poster_html = poster_html.replace(placeholder, fig.image_base64)
        return poster_html

    @staticmethod
    def _escape_html(text: str) -> str:
        """HTML 특수문자를 이스케이프한다."""
        if not text:
            return ''
        return (str(text)
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#39;'))

    def _build_visualizations_html(self, content, autofigure_svgs: list = None) -> str:
        """동적으로 생성된 다이어그램(PaperBanana/AutoFigure)만 삽입한다.

        정적 fallback(파이프라인 다이어그램, 바 차트)은 생성하지 않는다.
        동적 다이어그램이 없으면 빈 문자열을 반환한다.
        """
        if not autofigure_svgs:
            return ""

        parts = []
        for fig in autofigure_svgs[:3]:
            title = self._escape_html(fig.get("paper_title", ""))
            svg = fig.get("svg_content", "")
            if svg:
                parts.append(f'''<div style="background:#f8fafc; border-radius:10px; padding:16px; border:1px solid #e2e8f0; margin-bottom:16px;">
                    {svg}
                    <p style="font-size:0.85rem; color:#64748b; text-align:center; margin:8px 0 0;">{title}</p>
                </div>''')

        if not parts:
            return ""

        return f'''<div class="section-box" style="margin-bottom:20px;">
        <div class="section-title" style="font-size:1.3rem; font-weight:700; color:#2563eb; margin-bottom:16px; border-bottom:2px solid #dbeafe; padding-bottom:10px;">
            Visualizations
        </div>
        {"".join(parts)}
    </div>'''

    def _build_figures_html(self, figures: list = None) -> str:
        """논문 삽도를 HTML 블록으로 생성한다 (base64 직접 삽입)."""
        if not figures:
            return ""

        allowed_mimes = ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml')
        items = []

        for fig in figures[:4]:
            # ExtractedFigure 객체 또는 dict 모두 지원
            if isinstance(fig, dict):
                mime = fig.get('mime_type', 'image/png')
                b64 = fig.get('image_base64', '')
                caption = fig.get('caption', '')
                paper_title = fig.get('paper_title', '')
            else:
                mime = getattr(fig, 'mime_type', 'image/png')
                b64 = getattr(fig, 'image_base64', '')
                caption = getattr(fig, 'caption', '')
                paper_title = getattr(fig, 'paper_title', '')

            if not b64:
                continue
            if mime not in allowed_mimes:
                mime = 'image/png'
            caption = self._escape_html(str(caption or ''))
            paper_title = self._escape_html(str(paper_title or '')[:50])

            items.append(f'''<div style="background:#f8fafc; border-radius:8px; padding:12px; border:1px solid #e2e8f0;">
            <img src="data:{mime};base64,{b64}"
                 alt="{caption}" style="width:100%; height:auto; border-radius:6px; margin-bottom:8px;" />
            <p style="font-size:0.85rem; font-weight:600; color:#1e293b; margin:4px 0 2px;">{caption}</p>
            <p style="font-size:0.7rem; color:#94a3b8; margin:0; font-style:italic;">Source: {paper_title}</p>
        </div>''')

        if not items:
            return ""

        return f'''<div class="section-box" style="margin-bottom:16px;">
        <div class="section-title" style="font-size:1.2rem; font-weight:700; color:#2563eb; margin-bottom:12px; border-bottom:2px solid #e2e8f0; padding-bottom:8px;">
            Key Figures from Papers
        </div>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:16px;">
            {"".join(items)}
        </div>
    </div>'''

    def _build_asset_cards(self, content) -> str:
        """논문별 Asset Card 데이터를 프롬프트 텍스트로 변환한다."""
        paper_analyses = getattr(content, 'paper_analyses', []) or []
        if not paper_analyses:
            return ""

        colors = ['#2563eb', '#7c3aed', '#059669', '#ea580c', '#0891b2', '#d97706']
        cards = []
        for i, paper in enumerate(paper_analyses[:6]):
            title = paper.get('title', f'Paper {i + 1}')
            methodology = (paper.get('methodology', '') or '')[:600]
            contributions = (paper.get('contributions', '') or '')[:400]
            results = (paper.get('results', '') or '')[:400]
            color = colors[i % len(colors)]

            if not (methodology or contributions or results):
                continue

            card = f"""
### Card {i + 1}: {title}
- **색상 코드**: {color}
- **방법론**: {methodology}
- **기여**: {contributions}
- **결과**: {results}
- **SVG 요구**: 이 논문의 핵심 파이프라인을 SVG 플로우차트로 표현 (색상: {color})
"""
            cards.append(card)

        if not cards:
            return ""

        return f"""
## 논문별 분석 카드 (각 카드 = 텍스트 + SVG를 한 세트로)

아래 각 논문에 대해 **설명 텍스트와 해당 논문의 아키텍처 SVG를 하나의 카드 안에 함께** 배치하세요.
SVG는 해당 논문의 방법론을 구체적으로 시각화해야 합니다 (generic한 "Input→Process→Output" 금지).

{''.join(cards)}"""

    def _build_gemini_prompt(self, content, layout, report_summary: str, num_papers: int, figures: list = None) -> str:
        """Gemini용 동적 포스터 프롬프트 — Asset Card 기반 콘텐츠-시각화 통합"""

        return f"""당신은 NeurIPS/ICML 학회 포스터 디자이너입니다. 논문 분석 내용을 **콘텐츠 기반 동적 레이아웃**으로 구성한 HTML 포스터를 생성하세요.

## 핵심 원칙
1. **텍스트와 시각화를 한 카드 안에 묶기** — figure/SVG가 관련 설명과 분리되지 않도록
2. **논문별 독립 카드** — 각 논문의 방법론+아키텍처SVG가 하나의 카드 단위
3. **동적 그리드** — 논문 수에 따라 자동 배치 (고정 3단 아님)

## 콘텐츠

**제목**: {content.title}
**부제목**: {content.subtitle} ({num_papers}편 논문)
**초록**: {content.abstract[:600]}
**배경**: {content.motivation[:400]}
**기여**: {chr(10).join(f"• {c}" for c in content.contributions[:5])}
**주요 발견**: {chr(10).join(f"- {f}" for f in content.key_findings[:5])}
**결론**: {content.conclusion[:400]}
**키워드**: {", ".join(content.keywords[:7])}

{self._build_asset_cards(content)}
{self._format_visualization_data_prompt(content)}
{self._format_comparison_tables_prompt(content)}

## 포스터 HTML 구조 (이 구조를 따르세요)

```html
<header> 제목 + 부제목 + 키워드 배지 </header>

<section class="overview-section">
  <div class="overview-text"> 초록 + 배경 </div>
  <div class="overview-svg">
    <svg viewBox="0 0 800 180" style="width:100%">
      <!-- 전체 연구 파이프라인: 둥근 박스 + 화살표 -->
    </svg>
  </div>
</section>

<section class="papers-grid">
  <!-- 논문 수에 따라 자동 배치: repeat(auto-fit, minmax(450px, 1fr)) -->
  <div class="paper-card" style="border-left: 4px solid [논문색상]">
    <h3>논문 제목</h3>
    <p>방법론 설명...</p>
    <svg viewBox="0 0 400 160" style="width:100%">
      <!-- 이 논문 고유의 아키텍처 다이어그램 -->
    </svg>
    <p class="results">주요 결과...</p>
  </div>
  <!-- 다음 논문 카드... -->
</section>

<section class="comparison-section">
  비교 분석 테이블 + 결과 차트 SVG
</section>

<section class="conclusion-section">
  결론 + Key Findings
</section>
```

## SVG 생성 규칙

각 논문 카드 안에 **해당 논문의 구체적인 파이프라인을 SVG로** 표현하세요:
- `<svg viewBox="0 0 W H" style="width:100%">` 로 반응형
- 둥근 사각형(`rx="10"`) + 화살표(`<marker>`) + 텍스트 레이블
- 논문별 색상 코드 사용 (카드 border-left와 동일)
- 3-5개 핵심 단계를 박스+화살표로 연결
- **generic "Input→Process→Output" 금지** — 실제 방법론 단계명을 사용

## CSS

```css
:root {{ --primary: #2563eb; --bg: #f8fafc; }}
body {{ font-family: 'Inter', 'Noto Sans KR', sans-serif; }}
.papers-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(450px, 1fr)); gap: 20px; }}
.paper-card {{ background: white; border-radius: 12px; padding: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
```

## 출력
<!DOCTYPE html>로 시작하는 완전한 HTML. 설명/코드블록 없이 HTML만."""

    def _assemble_poster(self, content, layout, section_htmls: dict) -> str:
        """
        모든 섹션을 조합하여 최종 HTML 생성 (YAML 스타일 적용)
        """
        # StyleManager로부터 CSS 생성 (없으면 기본 CSS 사용)
        if self.style_manager:
            try:
                custom_css = self.style_manager.generate_css(self.theme)
            except Exception:
                custom_css = self._get_default_css()
        else:
            custom_css = self._get_default_css()

        # 헤더 생성
        header_html = f'''<header>
            <div class="title-area">
                <h1>{content.title}</h1>
                <h2>{content.subtitle}</h2>
                <div class="authors">Systematic Literature Review | {datetime.now().strftime("%Y-%m-%d")}</div>
            </div>
            <div class="affiliation">
                <div class="conf-name">AI & Graph Learning Conference</div>
                <div>{datetime.now().strftime("%B %d, %Y")}</div>
            </div>
        </header>'''

        # 컬럼별 섹션 그룹화
        columns = {}
        for section_id, data in section_htmls.items():
            section = data['section']
            col = section.column
            if col not in columns:
                columns[col] = []
            columns[col].append((section.order, section, data['html']))

        # 각 컬럼 정렬 및 HTML 생성
        columns_html = []
        for col_num in sorted(columns.keys()):
            sections_in_col = sorted(columns[col_num], key=lambda x: x[0])

            col_sections_html = []
            for _, section, html in sections_in_col:
                section_box = f'''<div class="section-box">
                    <div class="section-title">{section.title}</div>
                    <div class="section-content">{html}</div>
                </div>'''
                col_sections_html.append(section_box)

            col_html = f'<div class="col">{"".join(col_sections_html)}</div>'
            columns_html.append(col_html)

        # 전체 HTML 조립 (YAML 스타일 적용)
        poster_html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{content.title} - Academic Poster</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        {custom_css}
    </style>
</head>
<body>
    <div class="poster-container">
        {header_html}
        <div class="grid-container">
            {"".join(columns_html)}
        </div>
    </div>
</body>
</html>'''

        return poster_html

    def _refine_poster(self, poster_html: str, suggestions: list) -> str:
        """
        검증 피드백 기반 포스터 개선

        현재는 간단한 CSS 조정만 수행
        향후 LLM 기반 재생성 구현 가능
        """
        # 간단한 CSS 조정 (예시)
        refinements = {
            'spacing': 'gap: 35px',
            'readability': 'font-size: 1.1rem',
            'contrast': 'color: #1e293b'
        }

        for key, value in refinements.items():
            if any(key in s.lower() for s in suggestions):
                # CSS에 반영 (간단한 예시)
                poster_html = poster_html.replace('gap: 30px', value)

        return poster_html

    def _get_default_css(self) -> str:
        """기본 CSS (StyleManager 사용 불가 시)"""
        return '''
        :root {
            --primary: #2563eb;
            --secondary: #1e293b;
            --accent: #f59e0b;
            --bg-color: #f8fafc;
            --box-bg: #ffffff;
            --border-color: #e2e8f0;
            --text-color: #334155;
        }

        body {
            font-family: 'Inter', 'Noto Sans KR', sans-serif;
            background-color: #e2e8f0;
            color: var(--text-color);
            margin: 0;
            padding: 20px;
            min-width: 1600px;
            overflow-x: auto;
        }

        .poster-container {
            width: 100%;
            max-width: 2200px;
            margin: 0 auto;
            background-color: var(--bg-color);
            box-shadow: 0 10px 25px rgba(0,0,0,0.1);
            display: flex;
            flex-direction: column;
            padding: 40px;
            box-sizing: border-box;
            aspect-ratio: 20 / 9;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 4px solid var(--primary);
            padding-bottom: 20px;
            margin-bottom: 30px;
        }

        .title-area h1 {
            font-size: 3rem;
            font-weight: 900;
            color: var(--primary);
            margin: 0;
            line-height: 1.1;
            text-transform: uppercase;
            letter-spacing: -0.02em;
        }

        .title-area h2 {
            font-size: 1.5rem;
            font-weight: 500;
            color: var(--secondary);
            margin: 10px 0 0 0;
        }

        .authors {
            font-size: 1rem;
            color: #475569;
            margin-top: 8px;
        }

        .affiliation {
            text-align: right;
        }

        .conf-name {
            font-weight: 700;
            color: var(--primary);
            font-size: 1.3rem;
        }

        .grid-container {
            display: grid;
            grid-template-columns: 1fr 2fr 1fr;
            gap: 30px;
            flex-grow: 1;
        }

        .col {
            display: flex;
            flex-direction: column;
            gap: 25px;
        }

        .section-box {
            background: var(--box-bg);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            border: 1px solid var(--border-color);
        }

        .section-title {
            font-size: 1.3rem;
            font-weight: 800;
            color: var(--primary);
            border-bottom: 2px solid #cbd5e1;
            padding-bottom: 10px;
            margin-bottom: 15px;
        }

        .section-content {
            font-size: 1rem;
            line-height: 1.6;
            color: var(--text-color);
        }

        .highlight-box {
            background-color: #eff6ff;
            border-left: 5px solid var(--primary);
            padding: 15px;
            margin: 10px 0;
            font-style: italic;
        }

        ul {
            list-style: none;
            padding-left: 0;
        }

        li {
            padding: 4px 0;
        }
        '''

    def _generate_simple_fallback(self, report_content: str, num_papers: int) -> str:
        """Fallback 포스터 — Gemini/멀티에이전트 모두 실패 시 사용"""
        # 리포트에서 기본 섹션 추출
        lines = report_content.split('\n')
        title = "Systematic Literature Review"
        for line in lines[:20]:
            if line.startswith('# '):
                title = line.replace('# ', '').strip()
                break

        # 섹션 분리 (간이)
        sections = report_content.split('\n## ')
        body_parts = []
        for sec in sections[1:6]:  # 최대 5개 섹션
            sec_lines = sec.split('\n')
            sec_title = self._escape_html(sec_lines[0].strip())
            sec_body = self._escape_html('\n'.join(sec_lines[1:])[:600])
            body_parts.append(f'''<div class="section-box">
                <div class="section-title">{sec_title}</div>
                <p style="white-space:pre-wrap; line-height:1.6;">{sec_body}</p>
            </div>''')

        sections_html = '\n'.join(body_parts) if body_parts else f'<pre style="white-space:pre-wrap;">{self._escape_html(report_content[:3000])}</pre>'

        return f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>{self._escape_html(title)} - Academic Poster</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=Noto+Sans+KR:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {{ --primary: #2563eb; --secondary: #1e293b; --accent: #f59e0b; --bg: #f8fafc; }}
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ font-family:'Inter','Noto Sans KR',sans-serif; background:var(--bg); padding:24px; }}
        .poster {{ max-width:1600px; margin:0 auto; background:white; border-radius:12px; box-shadow:0 4px 24px rgba(0,0,0,0.08); overflow:hidden; }}
        header {{ background:linear-gradient(135deg, var(--primary), #1d4ed8); color:white; padding:32px 40px; }}
        header h1 {{ font-size:2.5rem; font-weight:800; margin-bottom:8px; }}
        header p {{ font-size:1.1rem; opacity:0.9; }}
        .content {{ padding:32px 40px; display:grid; grid-template-columns:1fr 1fr; gap:24px; }}
        .section-box {{ background:var(--bg); border-radius:8px; padding:20px; border-left:4px solid var(--primary); }}
        .section-title {{ font-size:1.2rem; font-weight:700; color:var(--primary); margin-bottom:12px; }}
        p {{ font-size:0.95rem; color:var(--secondary); line-height:1.7; }}
    </style>
</head>
<body>
    <div class="poster">
        <header>
            <h1>{self._escape_html(title)}</h1>
            <p>Systematic Literature Review &middot; {num_papers} papers analyzed</p>
        </header>
        <div class="content">
            {sections_html}
        </div>
    </div>
</body>
</html>'''

    def _save_poster(self, poster_html: str, output_dir: Path) -> str:
        """포스터 HTML 파일 저장"""
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        poster_path = output_dir / f"poster_{timestamp}.html"

        with open(poster_path, 'w', encoding='utf-8') as f:
            f.write(poster_html)

        return str(poster_path)
