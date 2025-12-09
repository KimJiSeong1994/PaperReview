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
        theme: str = "default",
        design_pattern_manager=None
    ):
        """
        Args:
            model: Gemini 모델 이름 (기본값: gemini-3-pro-image-preview - 이미지 생성 지원)
            api_key: Google API 키
            max_workers: 병렬 처리 워커 수
            enable_validation: VLM 품질 검증 활성화
            theme: YAML 테마 이름 (default, academic_blue, dark_theme 등)
            design_pattern_manager: DesignPatternManager 인스턴스 (옵션)
        """
        self.model = model
        self.api_key = api_key or os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')
        self.max_workers = max_workers
        self.enable_validation = enable_validation
        self.theme = theme
        
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
        
        # 스타일 매니저 초기화 (권한 오류 시 기본값 사용)
        try:
            self.style_manager = StyleManager()
        except (OSError, PermissionError, ImportError) as e:
            # StyleManager 초기화 실패 시 None으로 설정 (기본 CSS 사용)
            self.style_manager = None
        
        # 하위 에이전트 초기화 (DesignPatternManager 전달)
        self.content_agent = PosterContentAgent()
        self.layout_agent = PosterLayoutAgent(design_pattern_manager=self.pattern_manager)
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
        
        이제 예시 포스터 분석, SVG 가이드, 디자인 패턴 정보를 포함합니다.
        """
        # DesignPatternManager에서 SVG 템플릿 및 패턴 정보 가져오기
        svg_examples = ""
        pattern_guidance = ""
        
        try:
            from app.DeepAgent.config.design_pattern_manager import get_design_pattern_manager
            pattern_manager = get_design_pattern_manager()
            if pattern_manager:
                svg_examples = pattern_manager.format_svg_examples()
                
                # 레이아웃 패턴 정보 추가
                if hasattr(layout, 'design_pattern') and layout.design_pattern:
                    pattern_guidance = pattern_manager.generate_design_prompt(layout.design_pattern)
        except Exception:
            pass
        
        return f"""# 🎨 저명한 학술 포스터 디자이너로서의 역할

당신은 NeurIPS, ICML, ICLR, CVPR 등 최고급 학회에서 수상작을 디자인한 저명한 학술 포스터 디자이너입니다.
당신의 전문성은 **심층 분석 내용을 가장 효과적으로 전달할 수 있는 최적의 디자인을 창조**하는 것입니다.

**핵심 철학**: 
- 고정된 틀이나 템플릿에 얽매이지 않음
- 콘텐츠의 본질을 가장 잘 드러내는 디자인 창조
- 각 연구의 고유한 특성에 맞는 맞춤형 레이아웃 설계
- 시각적 스토리텔링을 통한 효과적인 정보 전달

---

## 📊 심층 분석 콘텐츠 (정확히 반영하세요)

다음은 멀티 에이전트 심층 분석 시스템이 생성한 연구 리포트입니다.
이 콘텐츠를 가장 효과적으로 전달할 수 있는 포스터를 디자인하세요.

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

## 🏆 예시 포스터 분석 (디자인 참고용)

### Multi-Crit 포스터 특징

**레이아웃**:
- 3단 그리드 (좌: 1fr, 중: 1.2fr, 우: 1fr)
- 좌측: Motivation, Abstract, Methodology
- 중앙: Architecture Diagram, Results Chart
- 우측: Key Findings, Timeline, Conclusion

**색상 팔레트**:
- Primary: #2563eb (Academic Blue) - 제목, 강조
- Secondary: #1e293b (Dark Slate) - 텍스트
- Accent: #f59e0b (Orange) - 하이라이트
- Background: #f8fafc (Light Gray)

**시각화**:
- Radar Chart: 5-6개 차원의 성능 비교
- Timeline: 수직형, 아이콘 포함, 연도별 이벤트
- Bar Chart: 그룹화된 막대 그래프

**타이포그래피**:
- 제목: 3.5rem, weight 900, uppercase
- 섹션 헤더: 1.5rem, weight 800, border-bottom
- 본문: 1.1rem, line-height 1.6

### LlamaDuo 포스터 특징

**레이아웃**:
- 비대칭 레이아웃 (좌: 1fr, 중: 2fr, 우: 1fr)
- 좌측: Abstract, Methodology, Key Components
- 중앙: 대형 Pipeline Diagram, Experimental Results
- 우측: Research History Timeline, Economic Benefits

**색상 팔레트**:
- Primary: #3b82f6 (Blue)
- Secondary: #64748b (Slate Gray)
- Accent: #8b5cf6 (Purple)
- Background: #f1f5f9 (Light Blue Gray)

**시각화**:
- Pipeline Diagram: 수평형 플로우차트, 둥근 박스
- Timeline: 수직형, 텍스트 중심, 아이콘
- Line Chart: 다중 시리즈, 성능 추이
- Table: 성능 비교 테이블

**타이포그래피**:
- 제목: 3rem, weight 800
- 섹션 헤더: 1.3rem, weight 700, background color
- 본문: 1rem, line-height 1.6

---

{pattern_guidance}

---

{svg_examples}

---

## 🎯 디자인 접근법

### 1. 콘텐츠 중심 디자인
- **콘텐츠 분석**: 제공된 심층 분석 내용을 먼저 깊이 이해하세요
- **핵심 메시지 식별**: 가장 중요한 메시지가 무엇인지 파악
- **정보 계층 구조**: 어떤 정보가 가장 중요하고, 어떤 순서로 전달해야 하는지 결정
- **시각적 스토리**: 논리적 흐름에 따라 시각적 스토리를 구성

### 2. 레이아웃 전략
- **예시 포스터 참고**: Multi-Crit과 LlamaDuo의 레이아웃 패턴을 참고하되, 콘텐츠에 맞게 조정
- **3단 그리드**: 내용이 균등하게 분포된 경우 (Multi-Crit 스타일)
  - CSS: `grid-template-columns: 1fr 1.2fr 1fr;`
  - 좌측: Introduction, 중앙: Methods/Results, 우측: Findings/Timeline
- **비대칭 레이아웃**: 하나의 요소(예: Pipeline)가 지배적인 경우 (LlamaDuo 스타일)
  - CSS: `grid-template-columns: 1fr 2fr 1fr;`
  - 중앙에 대형 시각화 배치
- **유연성**: 콘텐츠 특성에 따라 자유롭게 조정

### 3. 시각화 전략
**필요한 시각화 식별** (콘텐츠 기반):
- **Radar Chart**: 성능 비교, 다차원 평가가 있을 때
- **Pipeline Diagram**: 방법론, 프로세스, 아키텍처 설명이 필요할 때
- **Timeline**: 연구 발전, 역사적 흐름이 있을 때
- **Bar Chart**: 결과 데이터, 수치 비교가 있을 때
- **Table**: 상세한 비교 분석이 필요할 때

**SVG 생성 가이드** (위의 예시 참고):
- Radar Chart: 중심점에서 방사형 축, 다각형으로 데이터 표현
- Pipeline: 둥근 박스 + 화살표, 수평 배치
- Timeline: 수직선 + 원형 마커, 좌우 교대 배치
- Bar Chart: 축 + 그리드 + 막대, 값 레이블 표시

### 4. 색상 및 타이포그래피
**색상 선택**:
- 학술적 느낌: Blue 계열 (Multi-Crit 스타일)
- 모던한 느낌: Blue-Purple 계열 (LlamaDuo 스타일)
- 일관성: Primary, Secondary, Accent 3가지 색상 체계 유지

**타이포그래피**:
- 제목: 3-3.5rem, weight 800-900
- 섹션 헤더: 1.3-1.5rem, weight 700-800
- 본문: 1-1.1rem, line-height 1.6
- 폰트: Inter, Noto Sans KR 등 Sans-serif

---

## ✅ 필수 요구사항

1. **완전한 HTML**: DOCTYPE, html, head, body 모두 포함
2. **CSS 자유 생성**: <style> 태그 내부에 모든 CSS를 직접 작성
   - 예시 포스터의 디자인 패턴을 참고하되, 콘텐츠에 맞게 조정
   - CSS Grid 또는 Flexbox 활용
   - CSS Custom Properties (:root 변수) 사용
   - 최소 너비 1600px 이상
3. **SVG 시각화**: 위의 SVG 예시를 참고하여 필요한 시각화 생성
   - Radar Chart, Pipeline Diagram, Timeline, Bar Chart 등
   - 깔끔하고 전문적인 스타일
   - 레이블과 값 명확히 표시
4. **콘텐츠 정확성**: 제공된 콘텐츠를 정확히 반영, 임의로 변경하지 말 것
5. **한글 지원**: 한글과 영어 모두 올바르게 표시
6. **학술적 품질**: NeurIPS, ICML 수준의 전문적인 포스터

---

## 🚀 디자인 프로세스

### Step 1: 콘텐츠 분석
1. 제공된 심층 분석 내용을 깊이 이해
2. 핵심 메시지와 부차적 정보 구분
3. 필요한 시각화 타입 결정 (Radar? Pipeline? Timeline?)

### Step 2: 레이아웃 선택
1. 콘텐츠 특성 파악:
   - 방법론이 복잡하고 Pipeline이 필요? → LlamaDuo 스타일 (비대칭)
   - 성능 비교가 중요? → Multi-Crit 스타일 (3단 그리드)
   - 균형 잡힌 내용? → 혼합 스타일
2. CSS Grid 구조 결정

### Step 3: 포스터 생성
1. **HTML 구조**: 선택한 레이아웃에 맞는 HTML 작성
2. **CSS 스타일**: 예시 포스터의 색상/타이포그래피 참고하여 CSS 작성
3. **SVG 생성**: 위의 SVG 예시를 참고하여 필요한 시각화 생성
4. **통합**: 모든 요소를 조화롭게 배치

### Step 4: 품질 검증
1. 콘텐츠가 정확히 반영되었는가?
2. 시각화가 명확하고 이해하기 쉬운가?
3. 디자인이 전문적이고 일관성 있는가?
4. 예시 포스터 수준의 품질인가?

---

## 🎨 최종 지시

**지금 바로 시작하세요:**

1. 제공된 심층 분석 콘텐츠를 깊이 이해
2. Multi-Crit 또는 LlamaDuo 스타일 중 적합한 것 선택 (또는 혼합)
3. 위의 SVG 예시를 참고하여 필요한 시각화 생성
4. 예시 포스터의 색상/타이포그래피 패턴을 참고하여 CSS 작성
5. 완전한 HTML 포스터 생성

**핵심**: 예시 포스터의 디자인 패턴과 시각화 기법을 활용하되, 콘텐츠에 맞게 최적화하세요.
당신은 저명한 학술 포스터 디자이너입니다. Multi-Crit과 LlamaDuo 수준의 전문적인 포스터를 만들어주세요!
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
