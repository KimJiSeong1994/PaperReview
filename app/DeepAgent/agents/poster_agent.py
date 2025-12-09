"""
Enhanced Poster Agent (Orchestrator)

Paper2Poster 방법론 기반의 멀티 에이전트 포스터 생성 시스템
각 에이전트의 작업을 조율하고 통합하는 오케스트레이터
"""

import os
from pathlib import Path
from datetime import datetime
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# 하위 에이전트 임포트
from .poster_content_agent import PosterContentAgent
from .poster_layout_agent import PosterLayoutAgent, LayoutType
from .poster_visual_agent import PosterVisualAgent
from .poster_validator_agent import PosterValidatorAgent

# 스타일 매니저 (동적 임포트)
import sys
from pathlib import Path
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
        model: str = "gemini-3-pro-image-preview", 
        api_key: Optional[str] = None,
        max_workers: int = 4,
        enable_validation: bool = False,
        theme: str = "default"
    ):
        """
        Args:
            model: Gemini 모델 이름 (기본값: gemini-3-pro-image-preview - 이미지 생성 지원)
            api_key: Google API 키
            max_workers: 병렬 처리 워커 수
            enable_validation: VLM 품질 검증 활성화
            theme: YAML 테마 이름 (default, academic_blue, dark_theme 등)
        """
        self.model = model
        self.api_key = api_key or os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')
        self.max_workers = max_workers
        self.enable_validation = enable_validation
        self.theme = theme
        
        # Gemini LLM 초기화
        self.llm = None
        if self.api_key:
            self._initialize_gemini()
        
        # 스타일 매니저 초기화 (권한 오류 시 기본값 사용)
        try:
            self.style_manager = StyleManager()
        except (OSError, PermissionError, ImportError) as e:
            # StyleManager 초기화 실패 시 None으로 설정 (기본 CSS 사용)
            self.style_manager = None
        
        # 하위 에이전트 초기화
        self.content_agent = PosterContentAgent()
        self.layout_agent = PosterLayoutAgent()
        self.visual_agent = PosterVisualAgent()
        self.validator_agent = PosterValidatorAgent() if enable_validation else None
    
    def _initialize_gemini(self):
        """Gemini LLM 초기화"""
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.llm = genai.GenerativeModel(self.model)
        except Exception as e:
            self.llm = None
    
    def generate_poster(self, report_content: str, num_papers: int = 0, output_dir: Optional[Path] = None) -> dict:
        """
        멀티 에이전트 파이프라인으로 포스터 생성
        
        Pipeline:
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
            
        Returns:
            dict: {
                "success": bool,
                "poster_html": str,
                "poster_path": str,
                "validation_score": float
            }
        """
        try:
            # Phase 1: Content Extraction (멀티 에이전트)
            content = self.content_agent.extract(report_content, num_papers)
            
            # Phase 2: Layout Planning (멀티 에이전트)
            layout = self.layout_agent.plan(content)
            
            # Phase 3: Gemini를 사용한 포스터 생성
            if self.llm:
                poster_html = self._generate_with_gemini(content, layout, report_content, num_papers)
            else:
                # Gemini 사용 불가 시 멀티 에이전트 방식 사용
                section_htmls = self._generate_sections_parallel(layout.sections)
                poster_html = self._assemble_poster(content, layout, section_htmls)
            
            # Phase 4: Validation (옵션)
            validation_score = 0.8
            if self.enable_validation and self.validator_agent:
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
            import traceback
            traceback.print_exc()
            
            # Fallback
            return {
                "success": False,
                "poster_html": self._generate_simple_fallback(report_content, num_papers),
                "poster_path": None,
                "validation_score": 0.5,
                "error": str(e)
            }
    
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
                except Exception as e:
                    section_htmls[section.id] = {
                        'html': '<p class="text-red-500">생성 실패</p>',
                        'section': section
                    }
        
        return section_htmls
    
    def _generate_with_gemini(self, content, layout, report_content: str, num_papers: int) -> str:
        """
        Gemini를 사용하여 포스터 생성
        
        멀티 에이전트로 추출한 구조화된 콘텐츠를 Gemini에 전달하여
        고품질 학술 포스터를 생성합니다.
        """
        # 리포트 요약 (토큰 제한)
        report_summary = report_content[:8000]
        
        # Gemini 프롬프트 구성
        prompt = self._build_gemini_prompt(content, layout, report_summary, num_papers)
        
        try:
            response = self.llm.generate_content(prompt)
            poster_html = response.text
            
            # HTML 코드만 추출 (마크다운 코드 블록 제거)
            if "```html" in poster_html:
                poster_html = poster_html.split("```html")[1].split("```")[0]
            elif "```" in poster_html:
                parts = poster_html.split("```")
                if len(parts) > 1:
                    poster_html = parts[1]
            
            poster_html = poster_html.strip()
            
            # HTML 형식 검증 및 보완
            if not poster_html.startswith("<!DOCTYPE") and not poster_html.startswith("<html"):
                poster_html = f"<!DOCTYPE html>\n<html lang='ko'>\n{poster_html}\n</html>"
            
            return poster_html
            
        except Exception as e:
            # Gemini 생성 실패 시 멀티 에이전트 방식으로 fallback
            section_htmls = self._generate_sections_parallel(layout.sections)
            return self._assemble_poster(content, layout, section_htmls)
    
    def _build_gemini_prompt(self, content, layout, report_summary: str, num_papers: int) -> str:
        """
        Gemini용 포스터 생성 프롬프트 구성
        
        멀티 에이전트로 추출한 구조화된 정보를 활용하여
        상세하고 정확한 프롬프트를 생성합니다.
        """
        return f"""# 🎓 학술 포스터 생성 태스크 (Gemini 3 Pro)

당신은 NeurIPS, ICML, ICLR 수준의 최고급 학술 포스터를 생성하는 전문 디자이너이자 프론트엔드 개발자입니다.
"Multi-Crit: Benchmarking Multimodal Judges" 포스터와 유사한 디자인 패턴과 톤앤매너를 참고하여,
멀티 에이전트 시스템으로 추출한 구조화된 콘텐츠를 바탕으로 고품질 포스터를 생성하세요.

---

## 📊 입력 데이터 (정확히 사용하세요)

**제목**: {content.title}
**부제목**: {content.subtitle}
**분석 논문 수**: {num_papers}편

**초록 (Abstract)**:
{content.abstract[:600]}

**연구 배경 (Motivation)**:
{content.motivation[:600]}

**핵심 기여 (Contributions)**:
{chr(10).join(f"• {c}" for c in content.contributions[:5])}

**방법론 (Methodology)**:
{content.methodology[:800]}

**주요 발견 (Key Findings)**:
{chr(10).join(f"✓ {f}" for f in content.key_findings[:6])}

**결론 (Conclusion)**:
{content.conclusion[:500]}

**키워드**: {", ".join(content.keywords[:7])}

---

## 🎨 디자인 참고: Multi-Crit 포스터 스타일

### 디자인 패턴
- **레이아웃**: 유연한 비대칭 그리드 (좌측에 주요 내용, 중앙/우측에 시각화)
- **톤앤매너**: 깔끔하고 모던한 학술 스타일, 전문적이면서도 접근하기 쉬운 디자인
- **색상**: 부드럽고 조화로운 색상 팔레트, 과도한 강조 없이 명확한 계층 구조
- **타이포그래피**: 가독성 높은 Sans-serif 폰트, 명확한 위계 구조
- **시각화**: 다양한 다이어그램, 차트, 타임라인을 적절히 배치

### 레이아웃 가이드라인 (유연하게 적용)
- **전체 구조**: 가로형 와이드 포스터 (20:9 또는 유사한 비율)
- **섹션 배치**: 콘텐츠의 중요도와 흐름에 따라 자유롭게 배치
  - 좌측: 주요 텍스트 콘텐츠 (Motivation, Abstract, Contributions 등)
  - 중앙: 핵심 시각화 요소 (아키텍처 다이어그램, 알고리즘 순서도)
  - 우측: 보조 정보 및 추가 시각화 (Findings, Charts, Timeline 등)
- **그리드**: CSS Grid 또는 Flexbox를 사용하여 유연한 레이아웃 구성
- **반응형**: 최소 너비 1600px 이상, 브라우저에서 잘 보이도록

### 색상 팔레트 (참고용, 자유롭게 조정 가능)
- **Primary**: #2563eb (Academic Blue) 또는 유사한 파란색 계열
- **Secondary**: #1e293b (Dark Slate) 또는 유사한 어두운 회색
- **Accent**: #f59e0b (Orange) 또는 유사한 강조 색상
- **Background**: #f8fafc (Light Gray) 또는 흰색
- **Text**: #334155 (Dark Gray) 또는 #1e293b
- **Borders**: #e2e8f0 (Light Gray)

### 타이포그래피 (참고용)
- **제목**: 큰 크기, 굵은 weight, 명확한 계층
- **섹션 타이틀**: 중간 크기, 굵은 weight, 하단 경계선
- **본문**: 가독성 높은 크기, 적절한 line-height
- **폰트**: 'Inter', 'Noto Sans KR', 또는 유사한 Sans-serif

---

## 🖼️ 시각화 요소 (이미지 생성 활용)

**중요**: Gemini 3 Pro Image Preview 모델의 이미지 생성 기능을 활용하여 고품질 시각화를 생성하세요.

### Figure 1: 모델 아키텍처 다이어그램
**생성 방법**:
1. **이미지 생성 사용**: Gemini의 이미지 생성 기능을 활용하여 아키텍처 다이어그램 생성
2. **요구사항**:
   - 방법론에 맞는 아키텍처 구조를 시각화
   - 데이터 흐름과 주요 컴포넌트 명확히 표시
   - 색상으로 단계 구분
   - 레이블과 설명 포함
   - 학술 포스터에 적합한 깔끔한 스타일
3. **대안**: 이미지 생성이 어려운 경우 SVG로 직접 작성

### Figure 2: 알고리즘/프로세스 순서도
**생성 방법**:
1. **이미지 생성 사용**: Gemini의 이미지 생성 기능을 활용하여 순서도 생성
2. **요구사항**:
   - 방법론의 주요 단계를 Flowchart 형태로 표현
   - 화살표로 흐름 표시
   - 각 단계별 설명 포함
   - 전문적인 다이어그램 스타일
3. **대안**: 이미지 생성이 어려운 경우 SVG로 직접 작성

### Chart: 결과/데이터 시각화
**생성 방법**:
1. **이미지 생성 사용**: Gemini의 이미지 생성 기능을 활용하여 차트 생성
2. **요구사항**:
   - 주요 발견이나 결과를 시각적으로 표현
   - 막대 그래프, 라인 차트, 레이더 차트 등 적절한 형태 선택
   - 데이터가 없으면 논문 수나 분석 통계를 시각화
   - 학술 포스터에 적합한 깔끔한 차트 스타일
3. **대안**: CSS/HTML 또는 SVG로 작성

### 추가 시각화 (선택적)
- 타임라인: 연구 발전 과정 (이미지 생성 또는 SVG)
- 비교 테이블: 방법론 비교 (HTML 테이블 또는 이미지)
- 개념 다이어그램: 핵심 개념 관계 (이미지 생성 권장)

### 이미지 생성 가이드
- **스타일**: 학술 포스터에 적합한 깔끔하고 전문적인 스타일
- **색상**: Multi-Crit 포스터와 유사한 부드러운 색상 팔레트
- **해상도**: 고해상도로 생성하여 포스터에서 선명하게 보이도록
- **포맷**: Base64 인코딩된 이미지를 HTML에 직접 포함

---

## 📐 섹션 구성 가이드 (유연하게 적용)

콘텐츠의 특성에 맞게 다음 섹션들을 적절히 배치하세요:

**필수 섹션**:
1. **제목 영역**: 상단에 큰 제목, 부제목, 저자 정보
2. **초록 (Abstract)**: 연구 요약
3. **연구 배경 (Motivation)**: 문제 정의 및 동기
4. **방법론 (Methodology)**: 핵심 방법론 설명
5. **주요 발견 (Key Findings)**: 핵심 결과
6. **결론 (Conclusion)**: 결론 및 시사점

**선택적 섹션**:
- 핵심 기여 (Contributions)
- 비교 분석
- 향후 연구 방향
- 참고문헌 (간략)

**시각화 배치**:
- 아키텍처 다이어그램은 방법론 섹션 근처에 배치
- 알고리즘 순서도는 프로세스 설명과 함께 배치
- 차트는 결과/발견 섹션에 배치

---

## ✅ 절대 규칙

1. **완전한 HTML**: DOCTYPE, html, head, body 모두 포함
2. **CSS 자유 생성**: <style> 태그 내부에 모든 CSS를 직접 작성하세요
   - Multi-Crit 포스터 스타일을 참고하여 깔끔하고 전문적인 CSS 생성
   - 레이아웃, 색상, 타이포그래피를 자유롭게 결정
   - CSS Grid, Flexbox 등 최신 레이아웃 기법 활용
   - 반응형 디자인 고려 (min-width: 1600px)
3. **이미지 생성 활용**: Gemini 3 Pro Image Preview의 이미지 생성 기능을 적극 활용
   - 아키텍처 다이어그램, 순서도, 차트 등을 이미지로 생성
   - 생성된 이미지는 Base64 인코딩하여 HTML에 직접 포함
   - 이미지 생성이 어려운 경우 SVG로 대체
4. **SVG 직접 작성**: 이미지 생성이 불가능한 경우 SVG 코드로 직접 작성
5. **콘텐츠 정확성**: 추출된 콘텐츠를 정확히 반영, 임의로 변경하지 말 것
6. **한글 지원**: 한글과 영어 모두 올바르게 표시
7. **가독성**: 충분한 여백, 명확한 계층 구조
8. **디자인 일관성**: Multi-Crit 포스터와 유사한 깔끔하고 전문적인 스타일

---

## 🚀 생성 지시사항

위의 가이드라인을 참고하여, **콘텐츠의 특성에 맞게 최적의 레이아웃과 디자인을 자유롭게 생성**하세요:

1. **레이아웃 결정**: 콘텐츠의 양과 중요도에 따라 그리드 구조를 유연하게 결정
   - 2단, 3단, 또는 혼합 레이아웃 모두 가능
   - CSS Grid 또는 Flexbox를 활용하여 반응형 구조 생성
   - Multi-Crit 포스터처럼 비대칭 레이아웃도 가능

2. **CSS 스타일 생성**: Multi-Crit 포스터 스타일을 참고하여 완전히 새로운 CSS 작성
   - 고정된 템플릿 사용 금지, 콘텐츠에 맞는 최적의 스타일 생성
   - 색상, 폰트, 간격, 레이아웃을 자유롭게 결정
   - 깔끔하고 전문적인 학술 포스터 스타일 유지

3. **섹션 배치**: 논리적 흐름에 따라 섹션을 배치
   - 좌측에서 우측으로, 위에서 아래로 자연스러운 읽기 흐름
   - 중요한 내용은 눈에 띄는 위치에 배치
   - 시각화 요소는 적절한 위치에 통합

4. **시각화 생성**: Gemini의 이미지 생성 기능을 활용하여 고품질 시각화 생성
   - **아키텍처 다이어그램**: 이미지 생성 기능으로 생성 (우선), 불가능 시 SVG
   - **알고리즘 순서도**: 이미지 생성 기능으로 생성 (우선), 불가능 시 SVG
   - **결과 차트**: 이미지 생성 기능으로 생성 (우선), 불가능 시 CSS/HTML 또는 SVG
   - **타임라인/비교 테이블**: 필요시 이미지 생성 또는 HTML로 생성
   - 생성된 이미지는 Base64 인코딩하여 `<img src="data:image/png;base64,...">` 형태로 포함

5. **스타일링**: Multi-Crit 포스터와 유사한 깔끔하고 전문적인 스타일 적용
   - 부드럽고 조화로운 색상 팔레트
   - 명확한 타이포그래피 위계
   - 적절한 여백과 간격
   - 일관된 디자인 언어

6. **최종 검토**: 생성된 포스터가 학회 발표 수준의 품질인지 확인
   - 모든 콘텐츠가 정확히 반영되었는지
   - 시각화가 명확하고 이해하기 쉬운지
   - 디자인이 전문적이고 일관성 있는지

**중요**: CSS 구조를 강제하지 말고, 콘텐츠와 디자인 요구사항에 맞게 자유롭게 생성하세요.
Multi-Crit 포스터의 디자인 패턴과 톤앤매너를 참고하되, 고유한 레이아웃과 스타일을 만들어주세요.

---

## 🎨 이미지 생성 활용 방법

**Gemini 3 Pro Image Preview 모델의 이미지 생성 기능을 활용하세요:**

1. **이미지 생성 요청**: 프롬프트에서 이미지 생성을 요청하면, Gemini가 이미지를 생성합니다
2. **이미지 포함 방법**: 생성된 이미지는 Base64 인코딩하여 HTML에 포함
   ```html
   <img src="data:image/png;base64,iVBORw0KGgoAAAANS..." alt="Architecture Diagram">
   ```
3. **이미지 생성 프롬프트 예시**:
   - "Create a clean academic poster diagram showing [methodology description]"
   - "Generate a flowchart image illustrating [algorithm steps]"
   - "Create a bar chart image showing [results data]"

**이미지 생성이 가능한 경우**:
- 아키텍처 다이어그램을 이미지로 생성하여 포스터에 포함
- 알고리즘 순서도를 이미지로 생성하여 포스터에 포함
- 결과 차트를 이미지로 생성하여 포스터에 포함

**이미지 생성이 어려운 경우**:
- SVG 코드로 직접 작성하여 대체

**지금 바로 완전한 HTML 포스터를 생성하세요!**
이미지 생성 기능을 적극 활용하여 고품질 시각화를 포함한 포스터를 만들어주세요.
"""
    
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
        """간단한 fallback 포스터"""
        return f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>Fallback Poster</title>
    <style>
        body {{ font-family: sans-serif; padding: 40px; background: #f0f0f0; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 40px; }}
        h1 {{ color: #2563eb; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Research Analysis Poster</h1>
        <p><strong>Papers Analyzed:</strong> {num_papers}</p>
        <div style="white-space: pre-wrap; margin-top: 20px;">
            {report_content[:2000]}
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
