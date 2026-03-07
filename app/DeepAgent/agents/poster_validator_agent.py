"""
Poster Validator Agent

VLM 기반 포스터 품질 검증 에이전트
Paper2Poster의 Visual-in-the-loop 검증 구현
"""

import os
import base64
from typing import Dict, Optional, List
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """검증 결과"""
    score: float  # 0.0 ~ 1.0
    feedback: str
    suggestions: List[str]
    metrics: Dict[str, float]


class PosterValidatorAgent:
    """
    VLM 기반 포스터 품질 검증 에이전트

    역할:
    - 생성된 포스터의 시각적 품질 평가
    - 가독성, 정보 밀도, 시각적 균형 점수화
    - 개선 피드백 생성
    """

    def __init__(self, model: str = "gpt-4o", api_key: Optional[str] = None):
        """
        Args:
            model: VLM 모델 (gpt-4o, gpt-4-vision-preview)
            api_key: OpenAI API 키
        """
        self.model = model
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        self.client = None

        # API 키가 있을 때만 클라이언트 초기화 시도
        self._initialize_client()

    def _initialize_client(self):
        """OpenAI 클라이언트 초기화"""
        if not self.api_key:
            self.client = None
            return

        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key)
        except Exception:
            self.client = None

    def validate(self, poster_html: str) -> ValidationResult:
        """
        포스터 품질 검증

        Args:
            poster_html: 생성된 HTML 포스터

        Returns:
            ValidationResult: 검증 결과
        """
        if not self.client:
            return self._rule_based_validation(poster_html)

        try:
            # 1. HTML → 이미지 변환
            image_data = self._render_to_image(poster_html)

            if not image_data:
                return self._rule_based_validation(poster_html)

            # 2. VLM 평가
            result = self._evaluate_with_vlm(image_data)

            return result

        except Exception:
            return self._rule_based_validation(poster_html)

    def _render_to_image(self, html_content: str) -> Optional[str]:
        """
        HTML을 이미지로 렌더링 (Playwright 사용)

        Returns:
            Base64 인코딩된 이미지 데이터
        """
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1920, 'height': 1080})

                # HTML 로드
                page.set_content(html_content)

                # 스크린샷 생성
                screenshot_bytes = page.screenshot(full_page=True)

                browser.close()

                # Base64 인코딩
                image_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                return f"data:image/png;base64,{image_b64}"

        except ImportError:
            return None
        except Exception:
            return None

    def _evaluate_with_vlm(self, image_data: str) -> ValidationResult:
        """VLM을 사용한 포스터 평가"""
        prompt = """You are an expert academic poster evaluator.
Evaluate this poster based on the following criteria:

1. **Readability** (0-10): Text clarity, font sizes, contrast
2. **Information Density** (0-10): Content amount, balance between text and visuals
3. **Visual Balance** (0-10): Layout symmetry, spacing, alignment
4. **Design Quality** (0-10): Color scheme, typography, overall aesthetics
5. **Academic Standards** (0-10): Professional appearance, clear structure, appropriate for conferences

Provide your evaluation in JSON format:
{
    "readability": 8.5,
    "information_density": 7.0,
    "visual_balance": 9.0,
    "design_quality": 8.0,
    "academic_standards": 8.5,
    "overall_score": 8.2,
    "feedback": "Brief overall feedback",
    "suggestions": ["suggestion 1", "suggestion 2", "suggestion 3"]
}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_data}},
                        {"type": "text", "text": prompt}
                    ]
                }],
                temperature=0.3,
                max_tokens=500
            )

            import json
            result_text = response.choices[0].message.content

            # JSON 추출
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0]
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0]

            evaluation = json.loads(result_text.strip())

            return ValidationResult(
                score=evaluation.get('overall_score', 8.0) / 10.0,
                feedback=evaluation.get('feedback', ''),
                suggestions=evaluation.get('suggestions', []),
                metrics={
                    'readability': evaluation.get('readability', 8.0),
                    'information_density': evaluation.get('information_density', 8.0),
                    'visual_balance': evaluation.get('visual_balance', 8.0),
                    'design_quality': evaluation.get('design_quality', 8.0),
                    'academic_standards': evaluation.get('academic_standards', 8.0)
                }
            )

        except Exception:
            return self._rule_based_validation(None)

    def _rule_based_validation(self, poster_html: Optional[str]) -> ValidationResult:
        """
        규칙 기반 검증 (VLM 사용 불가 시)

        HTML 구조 분석으로 간단한 품질 점수 계산
        """
        if not poster_html:
            return ValidationResult(
                score=0.7,
                feedback="VLM validation not available, using rule-based validation",
                suggestions=["Consider adding VLM validation for better quality assurance"],
                metrics={
                    'readability': 7.0,
                    'information_density': 7.0,
                    'visual_balance': 7.0,
                    'design_quality': 7.0,
                    'academic_standards': 7.0
                }
            )

        # 간단한 규칙 기반 점수 계산
        score = 0.0
        metrics = {}

        # 1. 가독성 체크 (섹션 수)
        section_count = poster_html.count('section-box')
        metrics['readability'] = min(10.0, section_count * 1.2)

        # 2. 정보 밀도 (텍스트 길이)
        text_length = len(poster_html)
        metrics['information_density'] = min(10.0, text_length / 1000)

        # 3. 시각적 균형 (SVG 존재 여부)
        has_svg = '<svg' in poster_html
        metrics['visual_balance'] = 9.0 if has_svg else 6.0

        # 4. 디자인 품질 (CSS 스타일 사용)
        has_styles = '<style>' in poster_html
        metrics['design_quality'] = 9.0 if has_styles else 5.0

        # 5. 학술 표준 (구조 완성도)
        has_header = '<header>' in poster_html
        has_footer = '<footer>' in poster_html
        metrics['academic_standards'] = 8.0 if (has_header and has_footer) else 6.0

        # 전체 점수
        score = sum(metrics.values()) / (len(metrics) * 10.0)

        return ValidationResult(
            score=score,
            feedback=f"Rule-based validation: {score*100:.1f}% quality",
            suggestions=[
                "Add more visual elements for better engagement",
                "Ensure consistent spacing and alignment",
                "Consider adding more SVG diagrams"
            ],
            metrics=metrics
        )

    def quick_validate(self, poster_html: str) -> bool:
        """
        빠른 검증 (필수 요소만 체크)

        Returns:
            True if poster meets minimum requirements
        """
        required_elements = [
            '<!DOCTYPE html>',
            '<html',
            '<head>',
            '<style>',
            '<body>',
            'poster-container'
        ]

        for element in required_elements:
            if element not in poster_html:
                return False

        return True

