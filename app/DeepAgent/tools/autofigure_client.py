"""
AutoFigure-Edit Client

AutoFigure-Edit 마이크로서비스와 통신하는 비동기 HTTP 클라이언트.
논문 메서드 텍스트를 편집 가능한 SVG 삽도로 변환하기 위해
LLM 이미지 생성 + SAM3 세그멘테이션 파이프라인을 활용한다.

Usage:
    client = get_autofigure_client()
    result = await client.method_to_svg("Transformer encoder-decoder architecture...")
    if result.success:
        svg_content = result.final_svg
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class AutoFigureResult:
    """AutoFigure-Edit 파이프라인 실행 결과."""

    success: bool
    final_svg: str = ""
    figure_png_b64: str = ""
    template_svg: str = ""
    artifacts: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class AutoFigureClient:
    """AutoFigure-Edit 마이크로서비스와의 비동기 통신 클라이언트.

    Args:
        base_url: 서비스 루트 URL.  ``AUTOFIGURE_URL`` 환경변수 또는
            ``http://localhost:8100`` 을 기본값으로 사용한다.
        api_key: 인증 키.  ``AUTOFIGURE_API_KEY``, ``OPENROUTER_API_KEY``,
            ``GOOGLE_API_KEY`` 순서로 환경변수를 탐색한다.
        provider: LLM 프로바이더 이름 (예: ``"gemini"``, ``"openai"``).
        image_model: 이미지 생성에 사용할 모델 식별자.
        svg_model: SVG 변환에 사용할 모델 식별자.
    """

    # 헬스체크 캐시 TTL (초)
    _HEALTH_CACHE_TTL: int = 60

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        provider: Optional[str] = None,
        image_model: str = "gemini-2.5-pro-preview-06-05",
        svg_model: str = "gemini-2.5-pro-preview-06-05",
    ) -> None:
        self.base_url: str = (
            base_url
            or os.getenv("AUTOFIGURE_URL")
            or "http://localhost:8100"
        ).rstrip("/")

        self.api_key: str = (
            api_key
            or os.getenv("AUTOFIGURE_API_KEY")
            or os.getenv("OPENROUTER_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        )

        self.provider: str = (
            provider
            or os.getenv("AUTOFIGURE_PROVIDER")
            or "gemini"
        )

        self.image_model: str = image_model
        self.svg_model: str = svg_model

        # 헬스체크 캐시
        self._health_cache: Optional[bool] = None
        self._health_cache_ts: float = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_headers(self) -> Dict[str, str]:
        """공통 HTTP 헤더를 구성한다."""
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _make_client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        """요청 단위 ``httpx.AsyncClient`` 를 생성한다."""
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._build_headers(),
            timeout=httpx.Timeout(timeout, connect=10.0),
        )

    # ------------------------------------------------------------------
    # Health Check
    # ------------------------------------------------------------------

    @property
    def _is_available(self) -> Optional[bool]:
        """캐시된 헬스체크 결과를 반환한다.

        TTL(60초) 이내의 캐시가 있으면 해당 값을 반환하고,
        만료되었으면 ``None`` 을 반환하여 재확인이 필요함을 나타낸다.
        """
        if self._health_cache is not None:
            elapsed = time.monotonic() - self._health_cache_ts
            if elapsed < self._HEALTH_CACHE_TTL:
                return self._health_cache
        return None

    async def health_check(self) -> bool:
        """``GET /healthz`` 로 서비스 가용성을 확인한다.

        결과는 60초간 캐시되어 반복 호출 비용을 줄인다.

        Returns:
            서비스가 정상 응답하면 ``True``, 그렇지 않으면 ``False``.
        """
        cached = self._is_available
        if cached is not None:
            return cached

        try:
            async with self._make_client(timeout=10.0) as client:
                resp = await client.get("/healthz")
                healthy = resp.status_code == 200
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("AutoFigure health check failed: %s", exc)
            healthy = False

        self._health_cache = healthy
        self._health_cache_ts = time.monotonic()
        return healthy

    # ------------------------------------------------------------------
    # Core API: method_to_svg
    # ------------------------------------------------------------------

    async def method_to_svg(
        self,
        method_text: str,
        reference_image_b64: Optional[str] = None,
        style_hints: Optional[Union[str, Dict[str, Any]]] = None,
        optimize_iterations: int = 1,
        timeout: float = 180.0,
    ) -> AutoFigureResult:
        """메서드 텍스트를 SVG 삽도로 변환한다.

        ``POST /api/run`` 으로 작업을 제출한 뒤
        ``GET /api/events/{job_id}`` SSE 스트림을 폴링하여
        진행 상황을 수신하고, 완료 시 아티팩트를 수집한다.

        Args:
            method_text: 변환할 연구 방법론 텍스트.
            reference_image_b64: 참조 이미지 (base64, 선택).
            style_hints: 스타일 힌트 문자열 (선택).
            optimize_iterations: SVG 최적화 반복 횟수.
            timeout: 전체 작업 타임아웃 (초).

        Returns:
            파이프라인 실행 결과를 담은 ``AutoFigureResult``.
        """
        # 1. 작업 제출
        payload: Dict[str, Any] = {
            "method_text": method_text,
            "provider": self.provider,
            "image_model": self.image_model,
            "svg_model": self.svg_model,
            "optimize_iterations": optimize_iterations,
        }
        if reference_image_b64:
            payload["reference_image_b64"] = reference_image_b64
        if style_hints:
            payload["style_hints"] = (
                json.dumps(style_hints) if isinstance(style_hints, dict) else style_hints
            )

        try:
            async with self._make_client(timeout=timeout) as client:
                resp = await client.post("/api/run", json=payload)
                if resp.status_code != 200:
                    error_detail = resp.text[:500]
                    logger.error(
                        "AutoFigure /api/run failed (HTTP %d): %s",
                        resp.status_code,
                        error_detail,
                    )
                    return AutoFigureResult(
                        success=False,
                        error=f"Run request failed (HTTP {resp.status_code}): {error_detail}",
                    )

                run_data = resp.json()
                job_id: str = run_data.get("job_id", "")
                if not job_id:
                    return AutoFigureResult(
                        success=False,
                        error="No job_id returned from /api/run",
                    )

                logger.info("AutoFigure job submitted: %s", job_id)

                # 2. SSE 폴링
                artifacts = await self._poll_sse(client, job_id, timeout)

                # 3. 아티팩트 수집
                return await self._collect_artifacts(client, job_id, artifacts)

        except httpx.TimeoutException:
            logger.error("AutoFigure method_to_svg timed out after %.0fs", timeout)
            return AutoFigureResult(
                success=False,
                error=f"Request timed out after {timeout}s",
            )
        except (httpx.HTTPError, OSError) as exc:
            logger.error("AutoFigure method_to_svg connection error: %s", exc)
            return AutoFigureResult(
                success=False,
                error=f"Connection error: {exc}",
            )

    # ------------------------------------------------------------------
    # Core API: figure_to_svg
    # ------------------------------------------------------------------

    async def figure_to_svg(
        self,
        image_base64: str,
        mime_type: str = "image/png",
    ) -> AutoFigureResult:
        """래스터 이미지를 업로드한 뒤 SVG로 변환한다.

        ``POST /api/upload`` 로 이미지를 업로드하여 참조 URL을 받은 다음,
        해당 이미지를 참조로 ``method_to_svg`` 를 호출한다.

        Args:
            image_base64: base64 인코딩된 이미지 데이터.
            mime_type: 이미지 MIME 타입 (기본 ``"image/png"``).

        Returns:
            파이프라인 실행 결과를 담은 ``AutoFigureResult``.
        """
        upload_payload = {
            "image_base64": image_base64,
            "mime_type": mime_type,
        }

        try:
            async with self._make_client(timeout=30.0) as client:
                resp = await client.post("/api/upload", json=upload_payload)
                if resp.status_code != 200:
                    error_detail = resp.text[:500]
                    logger.error(
                        "AutoFigure /api/upload failed (HTTP %d): %s",
                        resp.status_code,
                        error_detail,
                    )
                    return AutoFigureResult(
                        success=False,
                        error=f"Upload failed (HTTP {resp.status_code}): {error_detail}",
                    )

                upload_data = resp.json()
                logger.info("Image uploaded to AutoFigure: %s", upload_data.get("id", ""))

        except (httpx.HTTPError, OSError) as exc:
            logger.error("AutoFigure upload connection error: %s", exc)
            return AutoFigureResult(
                success=False,
                error=f"Upload connection error: {exc}",
            )

        # 업로드된 이미지를 참조로 하여 SVG 변환 수행
        return await self.method_to_svg(
            method_text="Convert the uploaded figure into an editable SVG diagram.",
            reference_image_b64=image_base64,
        )

    # ------------------------------------------------------------------
    # SSE Polling
    # ------------------------------------------------------------------

    async def _poll_sse(
        self,
        client: httpx.AsyncClient,
        job_id: str,
        timeout: float,
    ) -> List[Dict[str, Any]]:
        """``GET /api/events/{job_id}`` SSE 스트림을 소비한다.

        수신한 아티팩트 이벤트 목록을 반환한다. ``close`` 이벤트를 받거나
        타임아웃이 발생하면 종료된다.

        Args:
            client: 활성 ``httpx.AsyncClient``.
            job_id: AutoFigure 작업 식별자.
            timeout: 폴링 타임아웃 (초).

        Returns:
            아티팩트 이벤트 데이터 목록.
        """
        artifacts: List[Dict[str, Any]] = []
        url = f"/api/events/{job_id}"

        try:
            async with client.stream("GET", url, timeout=timeout) as stream:
                current_event: Optional[str] = None
                current_data: str = ""

                async for raw_line in stream.aiter_lines():
                    line = raw_line.strip()

                    # 빈 줄 = 이벤트 경계
                    if not line:
                        if current_event and current_data:
                            self._handle_sse_event(
                                current_event, current_data, artifacts,
                            )
                            if current_event == "close":
                                break
                        current_event = None
                        current_data = ""
                        continue

                    if line.startswith("event:"):
                        current_event = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        current_data = line[len("data:"):].strip()

                # 스트림 종료 시 마지막 이벤트 처리
                if current_event and current_data:
                    self._handle_sse_event(current_event, current_data, artifacts)

        except httpx.TimeoutException:
            logger.warning("SSE polling timed out for job %s", job_id)
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("SSE polling error for job %s: %s", job_id, exc)

        return artifacts

    def _handle_sse_event(
        self,
        event_type: str,
        data_str: str,
        artifacts: List[Dict[str, Any]],
    ) -> None:
        """단일 SSE 이벤트를 처리한다.

        Args:
            event_type: 이벤트 종류 (``status``, ``artifact``, ``close``).
            data_str: JSON 인코딩된 이벤트 데이터.
            artifacts: 아티팩트를 누적할 리스트 (in-place 변경).
        """
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            logger.debug("SSE non-JSON data: %s", data_str[:200])
            return

        if event_type == "status":
            message = data.get("message", "")
            logger.info("AutoFigure status: %s", message)

        elif event_type == "artifact":
            artifact_type = data.get("type", "unknown")
            artifact_path = data.get("path", "")
            logger.info(
                "AutoFigure artifact: type=%s, path=%s",
                artifact_type,
                artifact_path,
            )
            artifacts.append(data)

        elif event_type == "close":
            logger.info("AutoFigure job completed: %s", data.get("message", ""))

        else:
            logger.debug("Unknown SSE event '%s': %s", event_type, data_str[:200])

    # ------------------------------------------------------------------
    # Artifact Collection
    # ------------------------------------------------------------------

    async def _collect_artifacts(
        self,
        client: httpx.AsyncClient,
        job_id: str,
        artifact_events: List[Dict[str, Any]],
    ) -> AutoFigureResult:
        """아티팩트 이벤트를 기반으로 실제 파일 내용을 수집한다.

        ``GET /api/artifacts/{job_id}/{path}`` 로 각 아티팩트를 다운로드하여
        ``AutoFigureResult`` 로 조합한다.

        Args:
            client: 활성 ``httpx.AsyncClient``.
            job_id: AutoFigure 작업 식별자.
            artifact_events: SSE에서 수신한 아티팩트 이벤트 목록.

        Returns:
            수집된 아티팩트를 포함하는 ``AutoFigureResult``.
        """
        if not artifact_events:
            return AutoFigureResult(
                success=False,
                error="No artifacts received from pipeline",
            )

        final_svg = ""
        figure_png_b64 = ""
        template_svg = ""
        all_artifacts: Dict[str, Any] = {}

        for event in artifact_events:
            artifact_type = event.get("type", "")
            artifact_path = event.get("path", "")
            if not artifact_path:
                continue

            url = f"/api/artifacts/{job_id}/{artifact_path}"
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(
                        "Failed to fetch artifact %s (HTTP %d)",
                        artifact_path,
                        resp.status_code,
                    )
                    continue

                content_type = resp.headers.get("content-type", "")

                if artifact_type == "final_svg":
                    final_svg = resp.text
                    all_artifacts["final_svg"] = artifact_path
                elif artifact_type == "figure":
                    # figure.png -> base64 인코딩
                    import base64
                    figure_png_b64 = base64.b64encode(resp.content).decode("utf-8")
                    all_artifacts["figure_png"] = artifact_path
                elif artifact_type == "template_svg":
                    template_svg = resp.text
                    all_artifacts["template_svg"] = artifact_path
                else:
                    # 기타 아티팩트는 텍스트/바이너리 구분하여 저장
                    if "text" in content_type or "svg" in content_type:
                        all_artifacts[artifact_type] = resp.text
                    else:
                        import base64
                        all_artifacts[artifact_type] = base64.b64encode(
                            resp.content
                        ).decode("utf-8")

            except (httpx.HTTPError, OSError) as exc:
                logger.warning(
                    "Error fetching artifact %s: %s", artifact_path, exc,
                )
                continue

        if not final_svg:
            return AutoFigureResult(
                success=False,
                error="Pipeline completed but no final SVG artifact found",
                artifacts=all_artifacts,
                figure_png_b64=figure_png_b64,
                template_svg=template_svg,
            )

        logger.info("AutoFigure SVG collected successfully (job %s)", job_id)
        return AutoFigureResult(
            success=True,
            final_svg=final_svg,
            figure_png_b64=figure_png_b64,
            template_svg=template_svg,
            artifacts=all_artifacts,
        )


# ---------------------------------------------------------------------------
# Prompt Builders
# ---------------------------------------------------------------------------

def build_method_prompt(
    content: Any,
    paper_analyses: List[Dict[str, Any]],
) -> str:
    """``ExtractedContent`` 와 논문 분석 결과로부터 AutoFigure용 프롬프트를 생성한다.

    AutoFigure-Edit는 간결한 입력에서 더 나은 결과를 보이므로
    총 출력을 2000자 이내로 제한한다.

    Args:
        content: ``ExtractedContent``-like 객체. ``methodology`` 속성이 있어야 한다.
        paper_analyses: 논문별 분석 딕셔너리 리스트.
            각 딕셔너리는 ``title``, ``methodology``, ``contributions`` 키를 가질 수 있다.

    Returns:
        AutoFigure-Edit에 전달할 메서드 설명 프롬프트 문자열.
    """
    MAX_LENGTH = 2000
    sections: List[str] = []

    # --- Research Method Overview ---
    methodology = getattr(content, "methodology", "") or ""
    if methodology:
        # 핵심 부분만 추출 (앞부분이 보통 개요)
        overview = methodology.strip()[:600]
        sections.append(f"Research Method Overview:\n{overview}")

    # --- Key Architecture Components ---
    components: List[str] = []
    for paper in paper_analyses:
        method_text = (paper.get("methodology") or "").strip()
        if not method_text:
            continue
        title = (paper.get("title") or "Unknown").strip()[:60]
        # 첫 문장 또는 150자까지를 컴포넌트 설명으로 사용
        first_sentence = method_text.split(".")[0].strip()
        desc = first_sentence[:150] if first_sentence else method_text[:150]
        components.append(f"- {title}: {desc}")

    if components:
        components_text = "\n".join(components[:6])
        sections.append(f"Key Architecture Components:\n{components_text}")

    # --- Pipeline Flow ---
    # methodology에서 단계적 흐름 추출 시도
    contributions = getattr(content, "contributions", []) or []
    if contributions:
        flow_items = [c.strip().lstrip("-").strip() for c in contributions[:5]]
        flow_str = " -> ".join(flow_items)
        sections.append(f"Pipeline Flow:\n{flow_str}")

    result = "\n\n".join(sections)

    # 길이 제한 적용
    if len(result) > MAX_LENGTH:
        result = result[:MAX_LENGTH - 3] + "..."

    return result


def build_paper_figure_prompts(
    paper_analyses: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """논문별 아키텍처/방법론 삽도 생성을 위한 프롬프트 목록을 반환한다.

    ``methodology`` 필드가 존재하는 논문만 포함하며,
    각 항목은 해당 논문의 방법론에 집중된 간결한 설명이다.

    Args:
        paper_analyses: 논문별 분석 딕셔너리 리스트.

    Returns:
        ``{"paper_title": str, "method_prompt": str}`` 형태의 딕셔너리 리스트.
    """
    prompts: List[Dict[str, str]] = []

    for paper in paper_analyses:
        methodology = (paper.get("methodology") or "").strip()
        if not methodology:
            continue

        title = (paper.get("title") or "Unknown Paper").strip()
        contributions = (paper.get("contributions") or "").strip()

        parts: List[str] = []
        parts.append(f"Paper: {title}")
        parts.append(f"\nMethod:\n{methodology[:800]}")

        if contributions:
            parts.append(f"\nKey Contributions:\n{contributions[:400]}")

        method_prompt = "\n".join(parts)

        # AutoFigure 최적 입력 길이에 맞추어 제한
        if len(method_prompt) > 1500:
            method_prompt = method_prompt[:1497] + "..."

        prompts.append({
            "paper_title": title,
            "method_prompt": method_prompt,
        })

    return prompts


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_client_instance: Optional[AutoFigureClient] = None


def get_autofigure_client() -> AutoFigureClient:
    """모듈 수준 싱글턴 ``AutoFigureClient`` 인스턴스를 반환한다.

    최초 호출 시 기본 설정으로 인스턴스를 생성하고,
    이후에는 동일 인스턴스를 재사용한다.

    Returns:
        ``AutoFigureClient`` 싱글턴 인스턴스.
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = AutoFigureClient()
    return _client_instance
