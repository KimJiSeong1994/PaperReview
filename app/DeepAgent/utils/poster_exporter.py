"""
Poster Exporter

HTML 포스터를 다양한 형식(PDF, PPTX)으로 내보내기
Paper2Poster의 출력 형식 다양화 구현
"""

import io
import logging
import re
from pathlib import Path
from typing import Optional

from app.DeepAgent.poster.resource_policy import remaining_budget
from app.DeepAgent.poster.result_contract import (
    CODE_PDF_GEOMETRY_INVALID,
    CODE_PDF_RENDER_FAILED,
    CODE_PDF_UNAVAILABLE,
    CODE_TIMEOUT_UNCLASSIFIED,
    PosterServiceError,
)

logger = logging.getLogger(__name__)

A3_LANDSCAPE_MM = (420.0, 297.0)
GEOMETRY_TOLERANCE_MM = 1.0

_MM_PER_POINT = 25.4 / 72.0
_RENDER_CAP_SECONDS = 30.0
# 문서 자신과 인라인 도판만 통과시킨다. 나머지 스킴은 전부 네트워크다.
_LOCAL_SCHEMES = ("data:", "about:", "blob:")
# Playwright가 Chromium 미설치를 알리는 문구. 렌더 실패와 구분해야
# "서버가 PDF를 만들 수 있는가"에 답할 수 있다.
_UNAVAILABLE_MARKERS = (
    "Executable doesn't exist",
    "playwright install",
    "Looks like Playwright was just installed",
)

# sanitize_css는 CSS에 'url('이 하나라도 있으면 스타일시트 전체를 비운다.
# url(#gradient) 같은 네트워크 능력 없는 로컬 프래그먼트나 주석 속 단어에도
# 걸리므로, 클라이언트가 쥔 포스터는 이미 @page를 잃은 채로 도착할 수 있다.
_A3_PAGE_FALLBACK = (
    "<style>@page{size:A3 landscape;margin:0}html,body{margin:0}"
    "@media print{html,body{width:420mm;height:297mm;overflow:hidden}}</style>"
)
_PAGE_RULE_RE = re.compile(r"@page\b", re.I)
_HEAD_RE = re.compile(r"<head[^>]*>", re.I)


def render_poster_pdf(html: str, *, deadline: Optional[float] = None) -> bytes:
    """Sanitize된 포스터 HTML 문자열을 A3 가로 PDF 바이트로 렌더한다.

    Args:
        html: 완전한 포스터 HTML. 호출자가 미리 sanitize해야 한다.
        deadline: time.monotonic() 기준 마감 시각. 남은 예산까지만 렌더한다.

    Returns:
        단일 페이지 A3 가로 PDF 바이트.

    Raises:
        PosterServiceError: Chromium 부재, 예산 소진, 렌더 실패, 판형 검증 실패.
            조용한 fallback은 없다 — 실패 원인은 error_code로 보존된다.
    """
    budget = remaining_budget(deadline, _RENDER_CAP_SECONDS)
    if budget <= 0:
        raise PosterServiceError(
            504,
            CODE_TIMEOUT_UNCLASSIFIED,
            "Poster PDF export budget was exhausted before rendering started",
            retryable=False,
        )

    try:
        from playwright.sync_api import (
            Error as PlaywrightError,
            TimeoutError as PlaywrightTimeoutError,
            sync_playwright,
        )
    except ImportError as exc:
        raise PosterServiceError(
            503,
            CODE_PDF_UNAVAILABLE,
            "PDF export is unavailable: Playwright is not installed",
            retryable=False,
        ) from exc

    try:
        with sync_playwright() as playwright:
            browser = _launch_chromium(playwright, PlaywrightError)
            try:
                # 정적 포스터에 스크립트는 필요 없다. 미리보기 iframe과 달리
                # 이 페이지에는 sandbox가 없으므로, sanitizer를 빠져나간 mXSS가
                # 곧바로 서버 브라우저의 JS 실행이 된다. 여기서 원천 차단한다.
                context = browser.new_context(java_script_enabled=False)
                context.set_default_timeout(budget * 1000)
                # 보조 방어다. 주 방어는 위의 java_script_enabled=False와
                # _launch_chromium의 host-resolver 규칙 — route는
                # fetch(keepalive), WebSocket, sendBeacon, <link rel=prefetch>를
                # 가로채지 못한다.
                # 문서 로드 이전에 걸어야 첫 서브리소스도 빠져나가지 못한다.
                context.route("**/*", _block_external)
                page = context.new_page()
                # set_content는 about:blank에 주입한다. file:// 로드가 아니므로
                # 로컬 파일 접근 표면 자체가 없다.
                page.set_content(_ensure_page_rule(html), wait_until="load")
                # 폰트가 준비되기 전에 인쇄하면 폴백 폰트로 레이아웃이 어긋난다.
                page.evaluate("document.fonts.ready.then(() => true)")
                pdf_bytes = page.pdf(
                    print_background=True,
                    # CSS @page가 유일한 판형 권위다. format=을 넘기면
                    # Playwright가 @page를 덮어써 권위가 둘로 갈린다.
                    prefer_css_page_size=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                )
            finally:
                browser.close()
    except PosterServiceError:
        raise
    # TimeoutError subclasses Error, so this must come first — otherwise running
    # out of budget mid-render answers with a different contract than running out
    # before it (504/not-retryable above), for the same cause.
    except PlaywrightTimeoutError as exc:
        raise PosterServiceError(
            504,
            CODE_TIMEOUT_UNCLASSIFIED,
            "Poster PDF export budget was exhausted while rendering",
            retryable=False,
        ) from exc
    except PlaywrightError as exc:
        # Playwright messages carry the API name, a call log, and installation
        # paths. That belongs in the log, not in a response to the client —
        # which is already what the router's own fallback does.
        logger.exception("[Poster PDF] Chromium render failed")
        raise PosterServiceError(
            500,
            CODE_PDF_RENDER_FAILED,
            "Poster PDF export failed",
            retryable=True,
        ) from exc

    _assert_a3_landscape(pdf_bytes)
    return pdf_bytes


def _ensure_page_rule(html: str) -> str:
    """sanitizer가 <style>을 통째로 비웠을 때 판형 권위를 복구한다.

    주입 CSS는 사용자 입력에서 파생되지 않은 고정 리터럴이라 sanitize 결과를
    되돌리지 않는다 — url()/@import/expression()이 없어 제거된 어떤 네트워크
    능력도 재도입하지 못하므로 보안 경계 밖이다. "CSS @page가 유일한 판형
    권위"라는 원칙은 그대로고, 권위의 출처만 클라이언트 HTML에서
    "클라이언트 HTML 또는 서버 기본값"으로 넓어진다.
    """
    if _PAGE_RULE_RE.search(html):
        return html
    head = _HEAD_RE.search(html)
    if head:
        return html[: head.end()] + _A3_PAGE_FALLBACK + html[head.end() :]
    return _A3_PAGE_FALLBACK + html


def _launch_chromium(playwright, playwright_error):
    """Chromium을 띄운다. 바이너리 가용성 판정을 겸한다.

    mXSS는 이벤트 핸들러만이 아니라 임의 요소를 밀반입하므로, JS를 꺼도
    <link rel=prefetch> 같은 마크업만으로 된 이그레스 채널은 살아남는다.
    그 채널들은 context.route가 구조적으로 보지 못한다. 이름 해석 단계에서
    끊으면 채널을 하나씩 세지 않아도 전부 닫힌다 — data:/about:/blob:은
    DNS를 타지 않으므로 포스터 렌더에는 영향이 없다.

    chromium_sandbox=True가 없으면 Playwright 드라이버가 --no-sandbox를
    자동으로 붙인다(chromium.js: `if (options.chromiumSandbox !== true)`).
    신뢰할 수 없는 HTML을 파싱하는 브라우저에서 커널 수준 격리를 끄는 셈이라
    명시적으로 되돌린다. 컨테이너가 비-root(Dockerfile의 USER appuser)여야
    setuid 샌드박스가 기동하므로 둘은 한 쌍이다.
    """
    try:
        return playwright.chromium.launch(
            headless=True,
            chromium_sandbox=True,
            args=["--host-resolver-rules=MAP * ~NOTFOUND"],
        )
    except playwright_error as exc:
        if any(marker in str(exc) for marker in _UNAVAILABLE_MARKERS):
            raise PosterServiceError(
                503,
                CODE_PDF_UNAVAILABLE,
                "PDF export is unavailable: the Chromium runtime is not installed",
                retryable=False,
            ) from exc
        raise


def _block_external(route) -> None:
    """인라인 리소스만 허용하고 외부 요청은 전부 중단한다."""
    if route.request.url.startswith(_LOCAL_SCHEMES):
        route.continue_()
    else:
        route.abort()


def _assert_a3_landscape(pdf_bytes: bytes) -> None:
    """생성된 PDF가 실제로 단일 페이지 A3 가로인지 확인한다."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        page_count = len(reader.pages)
        mediabox = reader.pages[0].mediabox if page_count else None
    except Exception as exc:
        raise PosterServiceError(
            500,
            CODE_PDF_GEOMETRY_INVALID,
            "Poster PDF could not be parsed for geometry verification",
            retryable=False,
        ) from exc

    if page_count != 1:
        raise PosterServiceError(
            500,
            CODE_PDF_GEOMETRY_INVALID,
            f"Poster PDF must be a single page, got {page_count}",
            retryable=False,
        )

    width_mm = float(mediabox.width) * _MM_PER_POINT
    height_mm = float(mediabox.height) * _MM_PER_POINT
    expected_width, expected_height = A3_LANDSCAPE_MM
    if (
        abs(width_mm - expected_width) > GEOMETRY_TOLERANCE_MM
        or abs(height_mm - expected_height) > GEOMETRY_TOLERANCE_MM
    ):
        raise PosterServiceError(
            500,
            CODE_PDF_GEOMETRY_INVALID,
            f"Poster PDF page is {width_mm:.1f}x{height_mm:.1f}mm, "
            f"expected {expected_width:.0f}x{expected_height:.0f}mm",
            retryable=False,
        )


class PosterExporter:
    """
    포스터 내보내기 유틸리티

    지원 형식:
    - HTML (기본)
    - PDF (playwright 사용)
    - PPTX (python-pptx 사용, 선택)
    """

    def __init__(self):
        self.has_pptx = self._check_pptx()

    def _check_pptx(self) -> bool:
        """python-pptx 사용 가능 여부 확인"""
        try:
            from pptx import Presentation  # type: ignore  # noqa: F401
            return True
        except ImportError:
            return False

    def export_to_pdf(self, html_path: Path, output_path: Optional[Path] = None) -> Path:
        """
        HTML 파일을 PDF로 변환

        Args:
            html_path: 입력 HTML 파일 경로
            output_path: 출력 PDF 경로 (기본값: html_path와 동일 경로에 .pdf)

        Returns:
            생성된 PDF 파일 경로

        Raises:
            PosterServiceError: render_poster_pdf가 올리는 실패를 그대로 전달한다.
        """
        if output_path is None:
            output_path = html_path.with_suffix('.pdf')

        output_path.write_bytes(
            render_poster_pdf(html_path.read_text(encoding='utf-8'))
        )
        return output_path

    def export_to_pptx(self, html_content: str, output_path: Path, title: str = "Research Poster") -> Optional[Path]:
        """
        HTML 콘텐츠를 PPTX로 변환

        Args:
            html_content: HTML 문자열
            output_path: 출력 PPTX 경로
            title: 슬라이드 제목

        Returns:
            생성된 PPTX 파일 경로
        """
        if not self.has_pptx:
            return None

        try:
            from pptx import Presentation  # type: ignore
            from pptx.util import Inches, Pt  # type: ignore
            from pptx.enum.text import PP_ALIGN  # type: ignore

            # 프레젠테이션 생성 (16:9 비율)
            prs = Presentation()
            prs.slide_width = Inches(13.33)  # Wide format
            prs.slide_height = Inches(7.5)

            # 빈 슬라이드 추가
            blank_layout = prs.slide_layouts[6]  # Blank layout
            slide = prs.slides.add_slide(blank_layout)

            # 제목 추가
            left = Inches(0.5)
            top = Inches(0.3)
            width = Inches(12.33)
            height = Inches(1)

            title_box = slide.shapes.add_textbox(left, top, width, height)
            title_frame = title_box.text_frame
            title_frame.text = title

            # 제목 스타일
            title_para = title_frame.paragraphs[0]
            title_para.font.size = Pt(40)
            title_para.font.bold = True
            title_para.alignment = PP_ALIGN.CENTER

            # 내용 추가 (간단한 텍스트 추출)
            content_text = self._extract_text_from_html(html_content)

            left = Inches(0.5)
            top = Inches(1.5)
            width = Inches(12.33)
            height = Inches(5.5)

            content_box = slide.shapes.add_textbox(left, top, width, height)
            content_frame = content_box.text_frame
            content_frame.text = content_text[:1000]  # 제한된 길이
            content_frame.word_wrap = True

            # 저장
            prs.save(str(output_path))

            return output_path

        except Exception:
            return None

    def _extract_text_from_html(self, html_content: str) -> str:
        """HTML에서 텍스트 추출 (간단한 파싱)"""
        import re

        # 태그 제거
        text = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)

        # 공백 정리
        text = re.sub(r'\s+', ' ', text)

        return text.strip()

    def export_all_formats(self, html_path: Path, base_name: Optional[str] = None) -> dict:
        """
        모든 형식으로 동시 내보내기

        Args:
            html_path: HTML 파일 경로
            base_name: 기본 파일명 (없으면 html_path 사용)

        Returns:
            dict: {'pdf': Path, 'pptx': Path}
        """
        if base_name is None:
            base_name = html_path.stem

        output_dir = html_path.parent

        results = {
            'html': html_path,
            'pdf': None,
            'pptx': None
        }

        # PDF 생성
        pdf_path = output_dir / f"{base_name}.pdf"
        results['pdf'] = self.export_to_pdf(html_path, pdf_path)

        # PPTX 생성 (HTML 읽기 필요)
        if self.has_pptx:
            with open(html_path, 'r', encoding='utf-8') as f:
                html_content = f.read()

            pptx_path = output_dir / f"{base_name}.pptx"
            results['pptx'] = self.export_to_pptx(html_content, pptx_path, base_name)

        return results


# 전역 익스포터 인스턴스
_exporter = None

def get_exporter() -> PosterExporter:
    """싱글톤 익스포터 인스턴스 반환"""
    global _exporter
    if _exporter is None:
        _exporter = PosterExporter()
    return _exporter

