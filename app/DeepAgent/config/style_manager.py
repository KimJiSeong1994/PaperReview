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
        except Exception:
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
            --poster-width: {layout.get('width', 'clamp(1200px, 92vw, 1600px)')};
            --poster-min-width: {layout.get('min_width', '1200px')};
            --poster-max-width: {layout.get('max_width', '1600px')};
            --poster-padding: {layout.get('padding', '48px')};
            --poster-gap: {layout.get('gap', '24px')};
            --poster-radius: {effects.get('border_radius', '8px')};
        }}

        * {{
            box-sizing: border-box;
        }}

        body {{
            font-family: {fonts.get('family_primary', "-apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif")};
            background-color: #d9dee8;
            color: var(--text-color);
            margin: 0;
            padding: 20px;
            overflow-x: auto;
            -webkit-font-smoothing: antialiased;
            text-rendering: optimizeLegibility;
        }}

        .poster-container {{
            width: var(--poster-width);
            min-width: var(--poster-min-width);
            max-width: var(--poster-max-width);
            margin: 0 auto;
            background-color: var(--bg-color);
            box-shadow: 0 10px 25px rgba(0,0,0,0.1);
            display: flex;
            flex-direction: column;
            padding: var(--poster-padding);
            box-sizing: border-box;
            aspect-ratio: {layout.get('aspect_ratio', '4 / 3').replace(':', ' / ')};
            print-color-adjust: exact;
            -webkit-print-color-adjust: exact;
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
            line-height: 1.16;
            text-transform: none;
            letter-spacing: 0;
            overflow-wrap: anywhere;
            word-break: keep-all;
        }}

        .title-area h2 {{
            font-size: {fonts.get('size_subtitle', '1.5rem')};
            font-weight: 650;
            color: var(--secondary);
            margin: 10px 0 0 0;
            line-height: 1.35;
            overflow-wrap: anywhere;
            word-break: keep-all;
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
            grid-template-columns: {layout.get('grid_template', 'repeat(12, minmax(0, 1fr))')};
            gap: var(--poster-gap);
            flex-grow: 1;
            align-items: start;
        }}

        .col {{
            display: flex;
            flex-direction: column;
            gap: var(--poster-gap);
            grid-column: span 4;
            min-width: 0;
        }}

        .col:nth-child(1):last-child {{
            grid-column: span 12;
        }}

        .col:nth-child(1):nth-last-child(2),
        .col:nth-child(2):last-child {{
            grid-column: span 6;
        }}

        .col[data-span="3"], .span-3 {{ grid-column: span 3; }}
        .col[data-span="4"], .span-4 {{ grid-column: span 4; }}
        .col[data-span="5"], .span-5 {{ grid-column: span 5; }}
        .col[data-span="6"], .span-6 {{ grid-column: span 6; }}
        .col[data-span="7"], .span-7 {{ grid-column: span 7; }}
        .col[data-span="8"], .span-8 {{ grid-column: span 8; }}
        .col[data-span="9"], .span-9 {{ grid-column: span 9; }}
        .col[data-span="12"], .span-12 {{ grid-column: span 12; }}

        .evidence-wall,
        .poster-grid {{
            display: grid;
            grid-template-columns: repeat(12, minmax(0, 1fr));
            gap: var(--poster-gap);
        }}

        .thesis-block,
        .poster-thesis {{
            grid-column: span 6;
        }}

        .metric-block,
        .evidence-card,
        .poster-evidence {{
            grid-column: span 4;
        }}

        .metadata-block,
        .limitations-block,
        .poster-metadata,
        .poster-limitations {{
            grid-column: span 6;
        }}

        .section-box {{
            background: var(--box-bg);
            border-radius: var(--poster-radius);
            padding: {spacing.get('section_padding', '20px')};
            box-shadow: {effects.get('box_shadow', '0 4px 6px rgba(0,0,0,0.05)')};
            border: 1px solid var(--border-color);
            min-width: 0;
            overflow-wrap: anywhere;
        }}

        .section-title {{
            font-size: {fonts.get('size_section_title', '1.3rem')};
            font-weight: {fonts.get('weight_section', '800')};
            color: var(--primary);
            border-bottom: 2px solid #cbd5e1;
            padding-bottom: 10px;
            margin-bottom: 15px;
            line-height: 1.25;
            overflow-wrap: anywhere;
            word-break: keep-all;
        }}

        .section-content {{
            font-size: {fonts.get('size_body', '1rem')};
            line-height: 1.6;
            color: var(--text-color);
            overflow-wrap: anywhere;
            word-break: keep-all;
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
            vertical-align: top;
            overflow-wrap: anywhere;
        }}

        .metric-label,
        .evidence-label,
        .metadata-label,
        figcaption {{
            color: #526071;
            font-size: {fonts.get('size_small', '0.85rem')};
            font-weight: 650;
            line-height: 1.35;
        }}

        .metric-value {{
            color: var(--secondary);
            font-size: clamp(1.55rem, 2.4vw, 2.4rem);
            font-weight: 900;
            line-height: 1.05;
            overflow-wrap: anywhere;
        }}

        svg {{
            max-width: 100%;
            height: auto;
        }}

        @media (max-width: 1199px) {{
            body {{
                padding: 12px;
            }}

            .poster-container {{
                width: 100%;
                min-width: 0;
                padding: 32px;
            }}

            .grid-container,
            .evidence-wall,
            .poster-grid {{
                grid-template-columns: repeat(6, minmax(0, 1fr));
                gap: 18px;
            }}

            .col,
            .col:nth-child(1):last-child,
            .col:nth-child(1):nth-last-child(2),
            .col:nth-child(2):last-child,
            .thesis-block,
            .poster-thesis,
            .metadata-block,
            .limitations-block,
            .poster-metadata,
            .poster-limitations {{
                grid-column: span 6;
            }}

            .metric-block,
            .evidence-card,
            .poster-evidence {{
                grid-column: span 3;
            }}
        }}

        @media (max-width: 760px) {{
            body {{
                padding: 0;
                overflow-x: hidden;
            }}

            .poster-container {{
                width: 100%;
                min-width: 0;
                max-width: none;
                aspect-ratio: auto;
                padding: 22px;
                box-shadow: none;
            }}

            header {{
                display: block;
            }}

            .affiliation {{
                text-align: left;
                margin-top: 14px;
            }}

            .grid-container,
            .evidence-wall,
            .poster-grid {{
                display: block;
            }}

            .col,
            .section-box,
            .thesis-block,
            .poster-thesis,
            .metric-block,
            .evidence-card,
            .poster-evidence,
            .metadata-block,
            .limitations-block,
            .poster-metadata,
            .poster-limitations {{
                margin-bottom: 14px;
            }}
        }}

        @page {{
            size: A3 landscape;
            margin: 0;
        }}

        @media print {{
            html, body {{
                width: 420mm;
                height: 297mm;
                overflow: hidden;
            }}

            body {{
                background: var(--bg-color);
                padding: 0;
                display: flex;
                justify-content: center;
            }}

            .poster-container {{
                width: 396mm;
                height: 297mm;
                min-width: 0;
                max-width: none;
                min-height: 297mm;
                box-shadow: none;
                overflow: hidden;
            }}

            .section-box,
            .metric-block,
            .evidence-card,
            figure,
            table {{
                break-inside: avoid;
                page-break-inside: avoid;
            }}
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
                    "type": "editorial-evidence-wall",
                    "aspect_ratio": "4:3",
                    "width": "clamp(1200px, 92vw, 1600px)",
                    "min_width": "1200px",
                    "max_width": "1600px",
                    "padding": "48px",
                    "gap": "24px",
                    "grid_template": "repeat(12, minmax(0, 1fr))"
                },
                "colors": {
                    "primary": "#1d4ed8",
                    "secondary": "#172033",
                    "accent": "#d97706",
                    "accent_green": "#0f766e",
                    "accent_orange": "#b45309",
                    "background": "#f7f8fb",
                    "box_bg": "#ffffff",
                    "border": "#d8dee9",
                    "text": "#243044"
                },
                "fonts": {
                    "family_primary": "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', Arial, sans-serif",
                    "size_title": "clamp(2.4rem, 3.3vw, 3.1rem)",
                    "size_subtitle": "clamp(1.25rem, 1.7vw, 1.65rem)",
                    "size_section_title": "1.15rem",
                    "size_body": "0.98rem",
                    "weight_title": "900",
                    "weight_section": "800",
                    "weight_body": "400"
                },
                "spacing": {
                    "section_padding": "18px",
                    "header_padding": "18px",
                    "margin_bottom": "24px"
                },
                "effects": {
                    "box_shadow": "0 8px 18px rgba(15,23,42,0.08)",
                    "border_radius": "8px",
                    "header_border": "3px solid"
                }
            }
        }
