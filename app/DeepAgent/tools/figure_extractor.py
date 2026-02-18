"""
Figure Extractor

논문 PDF에서 삽도(Figure/Table/Diagram)를 추출하고
Vision AI로 분석하여 캡션과 설명을 생성하는 모듈
"""

import io
import os
import base64
import requests
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed


@dataclass
class ExtractedFigure:
    """추출된 삽도 정보"""
    image_base64: str           # base64 인코딩된 이미지 (PNG)
    mime_type: str              # 이미지 MIME 타입
    page_number: int            # PDF 페이지 번호
    caption: str                # AI 생성 캡션
    description: str            # AI 생성 상세 설명
    relevance_score: float      # 핵심도 점수 (0~1)
    width: int                  # 이미지 너비
    height: int                 # 이미지 높이
    paper_title: str = ""       # 출처 논문 제목


class FigureExtractor:
    """
    논문 PDF에서 삽도를 추출하고 분석하는 클래스

    - PyMuPDF(fitz)로 PDF 내 이미지 추출
    - 크기 필터링으로 로고/아이콘 제거
    - Gemini Vision으로 각 Figure 분석
    """

    # 최소 이미지 크기 (로고, 아이콘 등 제외)
    MIN_WIDTH = 200
    MIN_HEIGHT = 150
    MIN_AREA = 50000  # width * height

    # 논문당 최대 추출 Figure 수
    MAX_FIGURES_PER_PAPER = 5

    # 포스터에 포함할 최대 Figure 수
    MAX_FIGURES_FOR_POSTER = 4

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        self._llm = None

    @property
    def llm(self):
        """Gemini Vision 모델 (lazy init)"""
        if self._llm is None and self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self._llm = genai.GenerativeModel("gemini-2.0-flash")
            except Exception as e:
                print(f"[FigureExtractor] Gemini 초기화 실패: {e}")
        return self._llm

    def extract_figures_from_papers(
        self,
        papers_data: List[Dict[str, Any]],
        max_papers: int = 3
    ) -> List[ExtractedFigure]:
        """
        여러 논문에서 핵심 Figure를 추출

        Args:
            papers_data: 논문 데이터 리스트 (pdf_url, arxiv_id 포함)
            max_papers: 최대 처리 논문 수

        Returns:
            핵심 Figure 리스트 (relevance_score 기준 정렬)
        """
        all_figures: List[ExtractedFigure] = []

        # PDF URL이 있는 논문만 필터
        papers_with_pdf = [
            p for p in papers_data
            if p.get('pdf_url') or p.get('arxiv_id')
        ][:max_papers]

        if not papers_with_pdf:
            print("[FigureExtractor] PDF URL이 있는 논문이 없습니다")
            return []

        print(f"[FigureExtractor] {len(papers_with_pdf)}편 논문에서 삽도 추출 시작")

        for paper in papers_with_pdf:
            try:
                figures = self._extract_from_single_paper(paper)
                all_figures.extend(figures)
                print(f"[FigureExtractor] '{paper.get('title', 'Unknown')[:40]}...' → {len(figures)}개 삽도 추출")
            except Exception as e:
                print(f"[FigureExtractor] 삽도 추출 실패: {e}")
                continue

        if not all_figures:
            print("[FigureExtractor] 추출된 삽도가 없습니다")
            return []

        # relevance_score 기준 정렬 후 상위 N개 선택
        all_figures.sort(key=lambda f: f.relevance_score, reverse=True)
        selected = all_figures[:self.MAX_FIGURES_FOR_POSTER]

        print(f"[FigureExtractor] 총 {len(all_figures)}개 중 {len(selected)}개 핵심 삽도 선택")
        return selected

    def _extract_from_single_paper(self, paper: Dict[str, Any]) -> List[ExtractedFigure]:
        """단일 논문 PDF에서 Figure 추출"""
        pdf_bytes = self._download_pdf(paper)
        if not pdf_bytes:
            return []

        raw_images = self._extract_images_from_pdf(pdf_bytes)
        if not raw_images:
            return []

        paper_title = paper.get('title', 'Unknown Paper')

        # Vision AI로 분석
        figures = []
        for img_data in raw_images[:self.MAX_FIGURES_PER_PAPER]:
            figure = self._analyze_figure(img_data, paper_title)
            if figure:
                figures.append(figure)

        return figures

    def _download_pdf(self, paper: Dict[str, Any]) -> Optional[bytes]:
        """논문 PDF 다운로드"""
        pdf_url = paper.get('pdf_url')

        if not pdf_url and paper.get('arxiv_id'):
            arxiv_id = paper['arxiv_id'].split('v')[0]
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        if not pdf_url:
            return None

        try:
            print(f"[FigureExtractor] PDF 다운로드: {pdf_url[:80]}...")
            response = self.session.get(pdf_url, timeout=30)
            if response.status_code == 200 and len(response.content) > 1000:
                return response.content
        except Exception as e:
            print(f"[FigureExtractor] PDF 다운로드 실패: {e}")

        return None

    def _extract_images_from_pdf(self, pdf_bytes: bytes) -> List[Dict[str, Any]]:
        """PyMuPDF로 PDF에서 이미지 추출"""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            print("[FigureExtractor] PyMuPDF가 설치되지 않았습니다: pip install PyMuPDF")
            return []

        images = []

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")

            for page_num in range(len(doc)):
                page = doc[page_num]
                image_list = page.get_images(full=True)

                for img_index, img_info in enumerate(image_list):
                    xref = img_info[0]

                    try:
                        base_image = doc.extract_image(xref)
                        if not base_image:
                            continue

                        image_bytes = base_image["image"]
                        width = base_image.get("width", 0)
                        height = base_image.get("height", 0)
                        ext = base_image.get("ext", "png")

                        # 크기 필터링
                        if width < self.MIN_WIDTH or height < self.MIN_HEIGHT:
                            continue
                        if width * height < self.MIN_AREA:
                            continue

                        # MIME 타입 결정
                        mime_map = {
                            "png": "image/png",
                            "jpeg": "image/jpeg",
                            "jpg": "image/jpeg",
                            "jxr": "image/jpeg",
                        }
                        mime_type = mime_map.get(ext, "image/png")

                        # PNG로 변환 (일관성을 위해)
                        png_bytes = self._convert_to_png(image_bytes, ext)
                        if png_bytes:
                            image_bytes = png_bytes
                            mime_type = "image/png"

                        images.append({
                            "image_bytes": image_bytes,
                            "mime_type": mime_type,
                            "page_number": page_num + 1,
                            "width": width,
                            "height": height,
                            "area": width * height,
                        })

                    except Exception:
                        continue

            doc.close()

        except Exception as e:
            print(f"[FigureExtractor] PDF 이미지 추출 오류: {e}")
            return []

        # 면적 기준 내림차순 정렬 (큰 이미지 = 중요 Figure 가능성 높음)
        images.sort(key=lambda x: x["area"], reverse=True)

        return images

    def _convert_to_png(self, image_bytes: bytes, ext: str) -> Optional[bytes]:
        """이미지를 PNG로 변환"""
        if ext == "png":
            return image_bytes

        try:
            from PIL import Image
            img = Image.open(io.BytesIO(image_bytes))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            # PIL 없으면 원본 반환
            return None

    def _analyze_figure(
        self,
        img_data: Dict[str, Any],
        paper_title: str
    ) -> Optional[ExtractedFigure]:
        """Vision AI로 Figure 분석"""
        image_bytes = img_data["image_bytes"]
        b64_str = base64.b64encode(image_bytes).decode("utf-8")

        # Gemini Vision 분석
        caption, description, relevance = self._analyze_with_vision(
            image_bytes, img_data["mime_type"], paper_title
        )

        return ExtractedFigure(
            image_base64=b64_str,
            mime_type="image/png",
            page_number=img_data["page_number"],
            caption=caption,
            description=description,
            relevance_score=relevance,
            width=img_data["width"],
            height=img_data["height"],
            paper_title=paper_title,
        )

    def _analyze_with_vision(
        self,
        image_bytes: bytes,
        mime_type: str,
        paper_title: str
    ) -> tuple:
        """Gemini Vision으로 이미지 분석"""
        if not self.llm:
            return self._fallback_analysis(paper_title)

        try:
            import google.generativeai as genai

            prompt = f"""이 이미지는 학술 논문 "{paper_title}"에서 추출한 삽도입니다.

다음 형식으로 분석해주세요:

CAPTION: [한 줄 캡션 - 이 Figure가 무엇을 보여주는지]
DESCRIPTION: [2-3문장 설명 - 핵심 내용, 데이터/결과의 의미]
RELEVANCE: [0.0~1.0 사이 점수 - 논문 핵심 내용 전달에 얼마나 중요한지]
  - 0.9~1.0: 핵심 아키텍처/결과 그래프/주요 실험결과
  - 0.6~0.8: 보조 실험결과/부분 다이어그램
  - 0.3~0.5: 예시 이미지/보조 설명
  - 0.0~0.2: 로고/장식/무관한 이미지

주의: 학술 포스터에 사용할 수 있는 고품질의 Figure인지 판단해주세요."""

            # multimodal 요청
            image_part = {
                "mime_type": mime_type,
                "data": base64.b64encode(image_bytes).decode("utf-8")
            }

            response = self.llm.generate_content([prompt, image_part])
            return self._parse_vision_response(response.text, paper_title)

        except Exception as e:
            print(f"[FigureExtractor] Vision 분석 실패: {e}")
            return self._fallback_analysis(paper_title)

    def _parse_vision_response(self, text: str, paper_title: str) -> tuple:
        """Vision 응답 파싱"""
        caption = ""
        description = ""
        relevance = 0.5

        for line in text.strip().split('\n'):
            line = line.strip()
            if line.upper().startswith('CAPTION:'):
                caption = line.split(':', 1)[1].strip()
            elif line.upper().startswith('DESCRIPTION:'):
                description = line.split(':', 1)[1].strip()
            elif line.upper().startswith('RELEVANCE:'):
                try:
                    score_str = line.split(':', 1)[1].strip()
                    # 숫자만 추출
                    import re
                    match = re.search(r'(\d+\.?\d*)', score_str)
                    if match:
                        relevance = float(match.group(1))
                        relevance = min(1.0, max(0.0, relevance))
                except (ValueError, IndexError):
                    pass

        if not caption:
            caption = f"논문 '{paper_title[:30]}...'의 삽도"
        if not description:
            description = text[:200] if text else "논문에서 추출한 주요 삽도입니다."

        return caption, description, relevance

    def _fallback_analysis(self, paper_title: str) -> tuple:
        """Vision AI 없을 때 기본 분석"""
        return (
            f"논문 삽도 - {paper_title[:40]}",
            "논문에서 추출한 주요 삽도입니다. 상세 분석은 Vision AI 연동 시 제공됩니다.",
            0.5
        )


def extract_paper_figures(
    papers_data: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    max_papers: int = 3
) -> List[ExtractedFigure]:
    """
    편의 함수: 논문 리스트에서 핵심 Figure 추출

    Args:
        papers_data: 논문 데이터 리스트
        api_key: Google API 키
        max_papers: 최대 처리 논문 수

    Returns:
        핵심 Figure 리스트
    """
    extractor = FigureExtractor(api_key=api_key)
    return extractor.extract_figures_from_papers(papers_data, max_papers=max_papers)
