"""
Poster Style Manager

YAML 기반 스타일 설정 로드 및 관리
Paper2Poster의 테마 시스템 구현
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from copy import deepcopy


class StyleManager:
    """
    YAML 기반 포스터 스타일 관리자
    
    기능:
    - YAML 설정 파일 로드
    - 테마 상속 (extends) 처리
    - 스타일 병합 및 오버라이드
    - CSS 생성
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Args:
            config_path: YAML 설정 파일 경로 (기본값: poster_styles.yaml)
        """
        if config_path is None:
            config_path = Path(__file__).parent / "poster_styles.yaml"
        
        self.config_path = config_path
        self.styles = {}
        self.load_styles()
    
    def load_styles(self):
        """YAML 파일에서 스타일 로드"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.styles = yaml.safe_load(f)
        except Exception as e:
            self.styles = self._get_default_styles()
    
    def get_style(self, theme: str = "default") -> Dict[str, Any]:
        """
        특정 테마의 스타일 가져오기 (상속 처리 포함)
        
        Args:
            theme: 테마 이름
            
        Returns:
            완전히 확장된 스타일 딕셔너리
        """
        if theme not in self.styles:
            theme = "default"
        
        style = self.styles[theme]
        
        # 상속 처리
        if "extends" in style:
            parent_theme = style["extends"]
            parent_style = self.get_style(parent_theme)
            style = self._merge_styles(parent_style, style)
        
        return deepcopy(style)
    
    def _merge_styles(self, base: Dict, override: Dict) -> Dict:
        """
        스타일 딕셔너리 병합 (재귀적)
        
        override가 base를 덮어씀
        """
        result = deepcopy(base)
        
        for key, value in override.items():
            if key == "extends":
                continue
            
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_styles(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def generate_css(self, theme: str = "default") -> str:
        """
        테마 기반 CSS 생성
        
        Args:
            theme: 테마 이름
            
        Returns:
            생성된 CSS 문자열
        """
        style = self.get_style(theme)
        
        colors = style.get('colors', {})
        fonts = style.get('fonts', {})
        spacing = style.get('spacing', {})
        effects = style.get('effects', {})
        layout = style.get('layout', {})
        
        css = f'''
        :root {{
            --primary: {colors.get('primary', '#2563eb')};
            --secondary: {colors.get('secondary', '#1e293b')};
            --accent: {colors.get('accent', '#f59e0b')};
            --accent-green: {colors.get('accent_green', '#16a34a')};
            --accent-orange: {colors.get('accent_orange', '#ea580c')};
            --bg-color: {colors.get('background', '#f8fafc')};
            --box-bg: {colors.get('box_bg', '#ffffff')};
            --border-color: {colors.get('border', '#e2e8f0')};
            --text-color: {colors.get('text', '#334155')};
        }}
        
        body {{
            font-family: {fonts.get('family_primary', "'Inter', sans-serif")};
            background-color: #e2e8f0;
            color: var(--text-color);
            margin: 0;
            padding: 20px;
            min-width: {layout.get('min_width', '1600px')};
            overflow-x: auto;
        }}

        .poster-container {{
            width: 100%;
            max-width: 2200px;
            margin: 0 auto;
            background-color: var(--bg-color);
            box-shadow: 0 10px 25px rgba(0,0,0,0.1);
            display: flex;
            flex-direction: column;
            padding: {layout.get('padding', '40px')};
            box-sizing: border-box;
            aspect-ratio: {layout.get('aspect_ratio', '20 / 9').replace(':', ' / ')};
        }}

        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: {effects.get('header_border', '4px solid')} var(--primary);
            padding-bottom: {spacing.get('header_padding', '20px')};
            margin-bottom: {spacing.get('margin_bottom', '30px')};
        }}

        .title-area h1 {{
            font-size: {fonts.get('size_title', '3rem')};
            font-weight: {fonts.get('weight_title', '900')};
            color: var(--primary);
            margin: 0;
            line-height: 1.1;
            text-transform: uppercase;
            letter-spacing: -0.02em;
        }}

        .title-area h2 {{
            font-size: {fonts.get('size_subtitle', '1.5rem')};
            font-weight: 500;
            color: var(--secondary);
            margin: 10px 0 0 0;
        }}

        .authors {{
            font-size: {fonts.get('size_body', '1rem')};
            color: #475569;
            margin-top: 8px;
        }}

        .affiliation {{
            text-align: right;
        }}

        .conf-name {{
            font-weight: 700;
            color: var(--primary);
            font-size: 1.3rem;
        }}

        .grid-container {{
            display: grid;
            grid-template-columns: {layout.get('grid_template', '1fr 2fr 1fr')};
            gap: {layout.get('gap', '30px')};
            flex-grow: 1;
        }}

        .col {{
            display: flex;
            flex-direction: column;
            gap: {layout.get('gap', '30px')};
        }}

        .section-box {{
            background: var(--box-bg);
            border-radius: {effects.get('border_radius', '12px')};
            padding: {spacing.get('section_padding', '20px')};
            box-shadow: {effects.get('box_shadow', '0 4px 6px rgba(0,0,0,0.05)')};
            border: 1px solid var(--border-color);
        }}

        .section-title {{
            font-size: {fonts.get('size_section_title', '1.3rem')};
            font-weight: {fonts.get('weight_section', '800')};
            color: var(--primary);
            border-bottom: 2px solid #cbd5e1;
            padding-bottom: 10px;
            margin-bottom: 15px;
        }}

        .section-content {{
            font-size: {fonts.get('size_body', '1rem')};
            line-height: 1.6;
            color: var(--text-color);
        }}

        .highlight-box {{
            background-color: #eff6ff;
            border-left: 5px solid var(--primary);
            padding: 15px;
            margin: 10px 0;
            font-style: italic;
        }}
        
        ul {{
            list-style: none;
            padding-left: 0;
        }}
        
        li {{
            padding: 4px 0;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
        th, td {{
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
        }}
        '''
        
        return css.strip()
    
    def list_themes(self) -> list:
        """사용 가능한 테마 목록 반환"""
        return list(self.styles.keys())
    
    def _get_default_styles(self) -> Dict[str, Any]:
        """기본 스타일 (YAML 로드 실패 시)"""
        return {
            "default": {
                "layout": {
                    "type": "3-column",
                    "aspect_ratio": "20:9",
                    "min_width": "1600px",
                    "padding": "40px",
                    "gap": "30px",
                    "grid_template": "1fr 2fr 1fr"
                },
                "colors": {
                    "primary": "#2563eb",
                    "secondary": "#1e293b",
                    "accent": "#f59e0b",
                    "accent_green": "#16a34a",
                    "accent_orange": "#ea580c",
                    "background": "#f8fafc",
                    "box_bg": "#ffffff",
                    "border": "#e2e8f0",
                    "text": "#334155"
                },
                "fonts": {
                    "family_primary": "'Inter', 'Noto Sans KR', sans-serif",
                    "size_title": "3rem",
                    "size_subtitle": "1.5rem",
                    "size_section_title": "1.3rem",
                    "size_body": "1rem",
                    "weight_title": "900",
                    "weight_section": "800",
                    "weight_body": "400"
                },
                "spacing": {
                    "section_padding": "20px",
                    "header_padding": "20px",
                    "margin_bottom": "30px"
                },
                "effects": {
                    "box_shadow": "0 4px 6px rgba(0,0,0,0.05)",
                    "border_radius": "12px",
                    "header_border": "4px solid"
                }
            }
        }

