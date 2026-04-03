"""
PaperBanana Client

PaperBanana Python API 래퍼.
포스터 생성 에이전트에서 논문 다이어그램/플롯을 프로그래밍 방식으로
생성하기 위한 비동기 클라이언트를 제공한다.

Usage:
    client = get_paperbanana_client()
    if client.is_available():
        result = await client.generate_diagram("Transformer encoder-decoder...")
        if result.success:
            html_img = f'<img src="data:image/png;base64,{result.image_base64}" />'
"""

import base64
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

_available = False
try:
    from paperbanana import (
        DiagramType,
        GenerationInput,
        PaperBananaPipeline,
    )
    from paperbanana.core.config import Settings

    _available = True
except ImportError:
    logger.debug("paperbanana package not installed; PaperBananaClient disabled")


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class PaperBananaResult:
    """PaperBanana 파이프라인 실행 결과."""

    success: bool
    image_path: str = ""
    image_base64: str = ""
    description: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class PaperBananaClient:
    """PaperBanana 파이프라인 비동기 래퍼 클라이언트.

    포스터 용도에 맞게 빠른 기본값(낮은 반복 횟수, 최적화 비활성)을
    사용하며, 생성된 이미지를 base64로 인코딩하여 HTML 임베딩에
    바로 사용할 수 있도록 한다.

    Args:
        iterations: 리파인먼트 반복 횟수. 기본 2 (포스터용 빠른 생성).
        optimize: 입력 최적화 활성화 여부.
        auto_refine: 자동 리파인 활성화 여부.
    """

    def __init__(
        self,
        iterations: int = 1,
        optimize: bool = False,
        auto_refine: bool = False,
    ) -> None:
        self._iterations = iterations
        self._optimize = optimize
        self._auto_refine = auto_refine
        self._pipeline: Optional[Any] = None

    def is_available(self) -> bool:
        """paperbanana 패키지 설치 여부를 확인한다.

        Returns:
            패키지가 설치되어 있으면 ``True``, 그렇지 않으면 ``False``.
        """
        return _available

    def _get_pipeline(self) -> Any:
        """파이프라인 인스턴스를 지연 생성하여 반환한다.

        Returns:
            ``PaperBananaPipeline`` 인스턴스.

        Raises:
            RuntimeError: paperbanana가 설치되어 있지 않을 때.
        """
        if not _available:
            raise RuntimeError("paperbanana package is not installed")

        if self._pipeline is None:
            settings = Settings(
                refinement_iterations=self._iterations,
                optimize_inputs=self._optimize,
                auto_refine=self._auto_refine,
            )
            self._pipeline = PaperBananaPipeline(settings=settings)
            logger.info(
                "PaperBananaPipeline initialized (iterations=%d, optimize=%s)",
                self._iterations,
                self._optimize,
            )

        return self._pipeline

    async def generate_diagram(
        self,
        method_text: str,
        caption: str = "",
        aspect_ratio: str = "16:9",
    ) -> PaperBananaResult:
        """방법론 텍스트로부터 다이어그램 이미지를 생성한다.

        Args:
            method_text: 다이어그램으로 변환할 연구 방법론 텍스트.
            caption: 그림 캡션. 비어 있으면 기본 캡션을 사용한다.
            aspect_ratio: 출력 이미지 비율 (기본 ``"16:9"``).

        Returns:
            생성 결과를 담은 ``PaperBananaResult``.
        """
        if not _available:
            return PaperBananaResult(
                success=False,
                error="paperbanana package is not installed",
            )

        gen_input = GenerationInput(
            source_context=method_text,
            communicative_intent=caption or "Methodology diagram",
            diagram_type=DiagramType.METHODOLOGY,
            aspect_ratio=aspect_ratio,
        )

        return await self._run_pipeline(gen_input)

    async def generate_plot(
        self,
        data_json: str,
        intent: str,
        aspect_ratio: str = "16:9",
    ) -> PaperBananaResult:
        """JSON 데이터로부터 플롯 이미지를 생성한다.

        Args:
            data_json: 플롯에 사용할 JSON 인코딩된 데이터.
            intent: 플롯의 커뮤니케이션 의도 (예: ``"Performance comparison"``).
            aspect_ratio: 출력 이미지 비율 (기본 ``"16:9"``).

        Returns:
            생성 결과를 담은 ``PaperBananaResult``.
        """
        if not _available:
            return PaperBananaResult(
                success=False,
                error="paperbanana package is not installed",
            )

        gen_input = GenerationInput(
            source_context=data_json,
            communicative_intent=intent,
            diagram_type=DiagramType.PLOT,
            aspect_ratio=aspect_ratio,
        )

        return await self._run_pipeline(gen_input)

    async def _run_pipeline(
        self,
        gen_input: Any,
    ) -> PaperBananaResult:
        """파이프라인을 실행하고 결과를 ``PaperBananaResult``로 변환한다.

        생성된 이미지 파일을 읽어 base64로 인코딩한 뒤 결과에 포함한다.

        Args:
            gen_input: ``GenerationInput`` 인스턴스.

        Returns:
            ``PaperBananaResult`` 인스턴스.
        """
        try:
            pipeline = self._get_pipeline()
            result = await pipeline.generate(gen_input)

            image_path = getattr(result, "image_path", "") or ""
            description = getattr(result, "description", "") or ""
            image_base64 = ""

            if image_path:
                image_base64 = self._read_image_as_base64(image_path)

            if not image_path and not description:
                return PaperBananaResult(
                    success=False,
                    error="Pipeline completed but produced no output",
                )

            logger.info("PaperBanana generation succeeded: %s", image_path)
            return PaperBananaResult(
                success=True,
                image_path=image_path,
                image_base64=image_base64,
                description=description,
            )

        except RuntimeError:
            raise
        except Exception as exc:
            logger.error("PaperBanana generation failed: %s", exc)
            return PaperBananaResult(
                success=False,
                error=f"Generation failed: {exc}",
            )

    @staticmethod
    def _read_image_as_base64(image_path: str) -> str:
        """이미지 파일을 읽어 base64 문자열로 반환한다.

        Args:
            image_path: 이미지 파일 경로.

        Returns:
            base64 인코딩된 문자열. 파일 읽기 실패 시 빈 문자열.
        """
        try:
            with open(image_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except (OSError, IOError) as exc:
            logger.warning("Failed to read image at %s: %s", image_path, exc)
            return ""


# ---------------------------------------------------------------------------
# Prompt Builders
# ---------------------------------------------------------------------------

def build_diagram_prompt(
    content: Any,
    paper_analyses: List[Dict[str, Any]],
) -> str:
    """``ExtractedContent``와 논문 분석 결과로부터 PaperBanana용 source_context를 생성한다.

    아키텍처 블록 다이어그램 / 데이터 플로우 다이어그램 생성에 최적화된
    구조화 프롬프트를 구성한다. 총 길이를 2500자 이내로 제한한다.

    Args:
        content: ``ExtractedContent``-like 객체. ``methodology`` 속성이 있어야 한다.
        paper_analyses: 논문별 분석 딕셔너리 리스트.

    Returns:
        PaperBanana source_context로 사용할 문자열.
    """
    MAX_LENGTH = 2500
    sections: List[str] = []

    # --- Diagram instruction ---
    sections.append(
        "Create a clear block diagram / data-flow diagram for an academic poster. "
        "Use labeled rectangles for components and directional arrows for data flow."
    )

    # --- System Architecture Overview ---
    methodology = getattr(content, "methodology", "") or ""
    if methodology:
        overview = methodology.strip()[:600]
        sections.append(f"## System Architecture Overview\n{overview}")

    # --- Core Components (역할 기반 구조화) ---
    components: List[str] = []
    for paper in paper_analyses:
        method_text = (paper.get("methodology") or "").strip()
        if not method_text:
            continue
        title = (paper.get("title") or "Unknown").strip()[:50]
        # 방법론에서 핵심 구조 추출: 첫 2문장
        sentences = [s.strip() for s in method_text.split(".") if s.strip()]
        desc = ". ".join(sentences[:2])[:250]
        contribs = (paper.get("contributions") or "").strip()
        innovation = ""
        if contribs:
            first_contrib = contribs.split("\n")[0].strip().lstrip("-").strip()[:120]
            innovation = f" | Innovation: {first_contrib}"
        components.append(f"- [{title}]: {desc}{innovation}")

    if components:
        components_text = "\n".join(components[:4])
        sections.append(f"## Core Components\n{components_text}")

    # --- Data Flow (단계별 입출력) ---
    contributions = getattr(content, "contributions", []) or []
    if contributions:
        flow_items = [c.strip().lstrip("-").strip()[:80] for c in contributions[:6]]
        flow_lines = []
        for i, item in enumerate(flow_items):
            prefix = "Input" if i == 0 else f"Stage {i}"
            flow_lines.append(f"  {prefix}: {item}")
        flow_str = "\n→ ".join(flow_lines)
        sections.append(f"## Data Flow\n{flow_str}")

    result = "\n\n".join(sections)

    # 스타일 지시
    result += (
        "\n\nSTYLE: Academic publication quality. Clean block diagram with labeled arrows. "
        "Use geometric shapes (rectangles, rounded boxes) and directional arrows. "
        "White background, sans-serif font. "
        "Do NOT include any logos, brand marks, icons, or watermarks. "
        "No clipart or decorative images."
    )

    if len(result) > MAX_LENGTH:
        result = result[:MAX_LENGTH - 3] + "..."

    return result


def build_diagram_caption(content: Any) -> str:
    """``ExtractedContent``에서 다이어그램 캡션을 생성한다.

    논문 수, 핵심 방법론 키워드를 포함한 서술적 캡션을 만든다.

    Args:
        content: ``ExtractedContent``-like 객체.

    Returns:
        다이어그램 캡션 문자열.
    """
    title = getattr(content, "title", "") or ""
    methodology = getattr(content, "methodology", "") or ""
    paper_titles = getattr(content, "paper_titles", []) or []

    parts: List[str] = []

    if title:
        parts.append(f"System architecture of {title}")
    elif paper_titles:
        parts.append(f"Comparative architecture overview of {len(paper_titles)} papers")

    if methodology:
        first_sentence = methodology.strip().split(".")[0].strip()
        if first_sentence and len(first_sentence) > 10:
            parts.append(first_sentence[:150])

    if not parts:
        return "System architecture and data flow diagram"

    return ": ".join(parts)


def build_paper_diagram_inputs(
    paper_analyses: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """논문별 아키텍처 다이어그램 생성 입력 목록을 반환한다.

    각 논문의 핵심 아키텍처를 블록 다이어그램으로 시각화하기 위한
    구조화된 프롬프트를 생성한다.

    Args:
        paper_analyses: 논문별 분석 딕셔너리 리스트.

    Returns:
        ``{"paper_title": str, "source_context": str, "caption": str}``
        형태의 딕셔너리 리스트.
    """
    inputs: List[Dict[str, str]] = []

    for paper in paper_analyses:
        methodology = (paper.get("methodology") or "").strip()
        if not methodology:
            continue

        title = (paper.get("title") or "Unknown Paper").strip()
        contributions = (paper.get("contributions") or "").strip()

        parts: List[str] = []
        parts.append(
            f"Draw a block diagram showing the core architecture of: {title}\n"
            "Use labeled rectangles for components and arrows for data flow."
        )
        parts.append(f"\n## Method\n{methodology[:800]}")

        if contributions:
            contrib_lines = contributions.split("\n")
            key_items = [c.strip().lstrip("-").strip() for c in contrib_lines if c.strip()][:4]
            if key_items:
                items_str = "\n".join(f"- {item[:100]}" for item in key_items)
                parts.append(f"\n## Key Innovations\n{items_str}")

        parts.append(
            "\nSTYLE: Academic block diagram. White background, clean layout. "
            "No logos or decorative elements."
        )

        source_context = "\n".join(parts)
        if len(source_context) > 2000:
            source_context = source_context[:1997] + "..."

        caption = f"Architecture diagram: {title}"

        inputs.append({
            "paper_title": title,
            "source_context": source_context,
            "caption": caption,
        })

    return inputs


def build_plot_inputs(
    paper_analyses: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """논문별 정량적 결과를 플롯으로 시각화하기 위한 입력을 생성한다.

    ``paper_analyses``에서 성능 지표, 비교 데이터를 추출하여
    ``PaperBananaClient.generate_plot()`` 에 전달할 수 있는
    JSON 데이터와 intent를 구성한다.

    Args:
        paper_analyses: 논문별 분석 딕셔너리 리스트.

    Returns:
        ``{"label": str, "data_json": str, "intent": str}`` 형태의 리스트.
    """
    import json as _json

    plots: List[Dict[str, str]] = []

    # --- 논문 간 비교 플롯 ---
    comparison_rows: List[Dict[str, str]] = []
    for paper in paper_analyses:
        title = (paper.get("title") or "").strip()[:40]
        contributions = (paper.get("contributions") or "").strip()
        key_findings = (paper.get("key_findings") or "").strip()
        if not title:
            continue

        # 핵심 기여 1줄 요약
        first_contrib = ""
        if contributions:
            first_contrib = contributions.split("\n")[0].strip().lstrip("-").strip()[:80]

        # 핵심 발견 1줄 요약
        first_finding = ""
        if key_findings:
            first_finding = key_findings.split("\n")[0].strip().lstrip("-").strip()[:80]

        if first_contrib or first_finding:
            comparison_rows.append({
                "paper": title,
                "contribution": first_contrib,
                "finding": first_finding,
            })

    if len(comparison_rows) >= 2:
        plots.append({
            "label": "Paper Comparison",
            "data_json": _json.dumps(
                {"type": "comparison_table", "papers": comparison_rows},
                ensure_ascii=False,
            ),
            "intent": (
                f"Create a comparison chart showing key contributions and findings "
                f"of {len(comparison_rows)} papers side by side. "
                "Use a grouped bar chart or structured table visualization."
            ),
        })

    return plots


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_client_instance: Optional[PaperBananaClient] = None


def get_paperbanana_client() -> PaperBananaClient:
    """모듈 수준 싱글턴 ``PaperBananaClient`` 인스턴스를 반환한다.

    최초 호출 시 기본 설정으로 인스턴스를 생성하고,
    이후에는 동일 인스턴스를 재사용한다.

    Returns:
        ``PaperBananaClient`` 싱글턴 인스턴스.
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = PaperBananaClient()
    return _client_instance
