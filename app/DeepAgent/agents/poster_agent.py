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
        model: str = "gemini-3-pro-preview", 
        api_key: Optional[str] = None,
        max_workers: int = 4,
        enable_validation: bool = False,
        theme: str = "default"
    ):
        """
        Args:
            model: Gemini 모델 이름 (fallback용)
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
        
        # 스타일 매니저 초기화
        self.style_manager = StyleManager()
        
        # 하위 에이전트 초기화
        self.content_agent = PosterContentAgent()
        self.layout_agent = PosterLayoutAgent()
        self.visual_agent = PosterVisualAgent()
        self.validator_agent = PosterValidatorAgent() if enable_validation else None
    
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
            # Phase 1: Content Extraction
            content = self.content_agent.extract(report_content, num_papers)
            
            # Phase 2: Layout Planning
            layout = self.layout_agent.plan(content)
            balance_score = self.layout_agent.calculate_visual_balance(layout.sections)
            
            # Phase 3: Visual Generation (병렬)
            section_htmls = self._generate_sections_parallel(layout.sections)
            
            # Phase 4: Assembly
            poster_html = self._assemble_poster(content, layout, section_htmls)
            
            # Phase 5: Validation (옵션)
            validation_score = 0.8
            if self.enable_validation and self.validator_agent:
                validation = self.validator_agent.validate(poster_html)
                validation_score = validation.score
                
                # Phase 6: Refinement (조건부)
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
    
    def _assemble_poster(self, content, layout, section_htmls: dict) -> str:
        """
        모든 섹션을 조합하여 최종 HTML 생성 (YAML 스타일 적용)
        """
        # StyleManager로부터 CSS 생성
        custom_css = self.style_manager.generate_css(self.theme)
        
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
