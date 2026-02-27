"""
Design Pattern Manager for Academic Poster Generation

This module manages design patterns loaded from YAML configuration,
providing pattern selection, SVG template retrieval, and design guidance
based on content analysis.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class ColorScheme:
    """Color scheme for a design pattern"""
    primary: str
    secondary: str
    accent: str
    background: str
    box_bg: str
    border: str
    text: str
    text_light: str
    
    def to_css_variables(self) -> str:
        """Convert to CSS custom properties"""
        return f"""
        --primary: {self.primary};
        --secondary: {self.secondary};
        --accent: {self.accent};
        --bg-color: {self.background};
        --box-bg: {self.box_bg};
        --border-color: {self.border};
        --text-color: {self.text};
        --text-light: {self.text_light};
        """


@dataclass
class LayoutConfig:
    """Layout configuration for a design pattern"""
    type: str  # "three_column", "asymmetric", etc.
    ratio: List[float]
    aspect_ratio: str
    min_width: str
    sections: Dict[str, List[str]]
    
    def get_css_grid(self) -> str:
        """Generate CSS Grid configuration"""
        ratio_fr = " ".join([f"{r}fr" for r in self.ratio])
        return f"grid-template-columns: {ratio_fr};"


@dataclass
class TypographyConfig:
    """Typography configuration"""
    title: Dict[str, str]
    subtitle: Dict[str, str]
    section_title: Dict[str, str]
    body: Dict[str, str]
    fonts: List[str]
    
    def get_font_family(self) -> str:
        """Get font-family CSS"""
        fonts_quoted = [f"'{f}'" for f in self.fonts]
        return ", ".join(fonts_quoted) + ", sans-serif"


class DesignPatternManager:
    """
    Manages design patterns for poster generation.
    
    Loads patterns from YAML, provides pattern selection logic,
    and generates design guidance for the poster generation agent.
    """
    
    def __init__(self, yaml_path: Optional[str] = None):
        """
        Initialize the design pattern manager.
        
        Args:
            yaml_path: Path to the design patterns YAML file.
                      If None, uses default location.
        """
        if yaml_path is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            yaml_path = os.path.join(current_dir, "poster_design_patterns.yaml")
        
        self.yaml_path = yaml_path
        self.patterns = {}
        self.svg_templates = {}
        self.guidelines = {}
        
        self._load_patterns()
    
    def _load_patterns(self):
        """Load design patterns from YAML file"""
        try:
            with open(self.yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            
            self.patterns = data.get('design_patterns', {})
            self.svg_templates = data.get('svg_templates', {})
            self.guidelines = data.get('design_guidelines', {})
            
        except FileNotFoundError:
            print(f"Warning: Design patterns YAML not found at {self.yaml_path}")
            self.patterns = {}
            self.svg_templates = {}
            self.guidelines = {}
        except Exception as e:
            print(f"Error loading design patterns: {e}")
            self.patterns = {}
            self.svg_templates = {}
            self.guidelines = {}
    
    def get_pattern(self, pattern_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific design pattern by name.
        
        Args:
            pattern_name: Name of the pattern (e.g., "multi_crit_style")
        
        Returns:
            Pattern dictionary or None if not found
        """
        return self.patterns.get(pattern_name)
    
    def get_all_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Get all available design patterns"""
        return self.patterns
    
    def get_pattern_names(self) -> List[str]:
        """Get list of all pattern names"""
        return list(self.patterns.keys())
    
    def get_svg_template(self, viz_type: str) -> Optional[str]:
        """
        Get SVG template/guide for a specific visualization type.
        
        Args:
            viz_type: Type of visualization (e.g., "radar_chart", "pipeline_diagram")
        
        Returns:
            SVG template string or None if not found
        """
        return self.svg_templates.get(viz_type)
    
    def get_all_svg_templates(self) -> Dict[str, str]:
        """Get all SVG templates"""
        return self.svg_templates
    
    def suggest_pattern(self, content_analysis: Dict[str, Any]) -> str:
        """
        Suggest the most appropriate design pattern based on content analysis.
        
        Args:
            content_analysis: Dictionary containing content analysis results
                - has_pipeline: bool
                - has_performance_metrics: bool
                - has_timeline: bool
                - content_balance: str ("text_heavy", "visual_heavy", "balanced")
                - num_sections: int
        
        Returns:
            Suggested pattern name
        """
        # Default to multi_crit_style
        suggested = "multi_crit_style"
        
        # If content has a dominant pipeline/flowchart, use llamaduo_style
        if content_analysis.get('has_pipeline', False):
            suggested = "llamaduo_style"
        
        # If content has performance comparison metrics, prefer multi_crit
        elif content_analysis.get('has_performance_metrics', False):
            suggested = "multi_crit_style"
        
        # If content is text-heavy with timeline, llamaduo might work better
        elif (content_analysis.get('content_balance') == 'text_heavy' and 
              content_analysis.get('has_timeline', False)):
            suggested = "llamaduo_style"
        
        return suggested
    
    def get_color_scheme(self, pattern_name: str) -> Optional[ColorScheme]:
        """
        Get color scheme for a pattern.
        
        Args:
            pattern_name: Name of the pattern
        
        Returns:
            ColorScheme object or None
        """
        pattern = self.get_pattern(pattern_name)
        if not pattern or 'color_scheme' not in pattern:
            return None
        
        cs = pattern['color_scheme']
        return ColorScheme(
            primary=cs.get('primary', '#2563eb'),
            secondary=cs.get('secondary', '#1e293b'),
            accent=cs.get('accent', '#f59e0b'),
            background=cs.get('background', '#f8fafc'),
            box_bg=cs.get('box_bg', '#ffffff'),
            border=cs.get('border', '#e2e8f0'),
            text=cs.get('text', '#334155'),
            text_light=cs.get('text_light', '#475569')
        )
    
    def get_layout_config(self, pattern_name: str) -> Optional[LayoutConfig]:
        """
        Get layout configuration for a pattern.
        
        Args:
            pattern_name: Name of the pattern
        
        Returns:
            LayoutConfig object or None
        """
        pattern = self.get_pattern(pattern_name)
        if not pattern or 'layout' not in pattern:
            return None
        
        layout = pattern['layout']
        return LayoutConfig(
            type=layout.get('type', 'three_column'),
            ratio=layout.get('ratio', [1, 1, 1]),
            aspect_ratio=layout.get('aspect_ratio', '20:9'),
            min_width=layout.get('min_width', '1600px'),
            sections=layout.get('sections', {})
        )
    
    def get_typography_config(self, pattern_name: str) -> Optional[TypographyConfig]:
        """
        Get typography configuration for a pattern.
        
        Args:
            pattern_name: Name of the pattern
        
        Returns:
            TypographyConfig object or None
        """
        pattern = self.get_pattern(pattern_name)
        if not pattern or 'typography' not in pattern:
            return None
        
        typo = pattern['typography']
        return TypographyConfig(
            title=typo.get('title', {}),
            subtitle=typo.get('subtitle', {}),
            section_title=typo.get('section_title', {}),
            body=typo.get('body', {}),
            fonts=typo.get('fonts', ['Inter', 'Noto Sans KR'])
        )
    
    def get_visualization_types(self, pattern_name: str) -> List[Dict[str, Any]]:
        """
        Get recommended visualization types for a pattern.
        
        Args:
            pattern_name: Name of the pattern
        
        Returns:
            List of visualization configurations
        """
        pattern = self.get_pattern(pattern_name)
        if not pattern or 'visualizations' not in pattern:
            return []
        
        return pattern['visualizations']
    
    def generate_design_prompt(self, pattern_name: str) -> str:
        """
        Generate detailed design guidance prompt for Gemini.
        
        Args:
            pattern_name: Name of the pattern to use
        
        Returns:
            Formatted design prompt string
        """
        pattern = self.get_pattern(pattern_name)
        if not pattern:
            return "Use a clean, professional academic poster design."
        
        color_scheme = self.get_color_scheme(pattern_name)
        layout_config = self.get_layout_config(pattern_name)
        typo_config = self.get_typography_config(pattern_name)
        viz_types = self.get_visualization_types(pattern_name)
        
        prompt = f"""## Design Pattern: {pattern.get('name', pattern_name)}

{pattern.get('description', '')}

### Layout Configuration
- Type: {layout_config.type if layout_config else 'flexible'}
- Grid Ratio: {':'.join(map(str, layout_config.ratio)) if layout_config else '1:1:1'}
- Aspect Ratio: {layout_config.aspect_ratio if layout_config else '20:9'}
- Min Width: {layout_config.min_width if layout_config else '1600px'}

### Color Palette
"""
        if color_scheme:
            prompt += f"""- Primary: {color_scheme.primary} (main branding, titles)
- Secondary: {color_scheme.secondary} (supporting text, borders)
- Accent: {color_scheme.accent} (highlights, call-outs)
- Background: {color_scheme.background}
- Box Background: {color_scheme.box_bg}
- Border: {color_scheme.border}
- Text: {color_scheme.text}
"""
        
        prompt += "\n### Typography\n"
        if typo_config:
            prompt += f"""- Fonts: {typo_config.get_font_family()}
- Title: {typo_config.title.get('size', '3rem')} / weight {typo_config.title.get('weight', '800')}
- Section Titles: {typo_config.section_title.get('size', '1.5rem')} / weight {typo_config.section_title.get('weight', '700')}
- Body: {typo_config.body.get('size', '1rem')} / line-height {typo_config.body.get('line_height', '1.6')}
"""
        
        prompt += "\n### Recommended Visualizations\n"
        for viz in viz_types:
            prompt += f"- {viz.get('type', 'chart')}: {viz.get('use_case', 'data visualization')}\n"
        
        return prompt
    
    def get_guidelines(self, category: str = 'general') -> List[str]:
        """
        Get design guidelines for a specific category.
        
        Args:
            category: Category of guidelines (e.g., 'general', 'layout_selection')
        
        Returns:
            List of guideline strings
        """
        return self.guidelines.get(category, [])
    
    def format_svg_examples(self) -> str:
        """
        Format all SVG templates as examples for Gemini prompt.

        Returns:
            Formatted string with all SVG examples
        """
        if not self.svg_templates:
            return ""

        output = "## SVG Generation Examples\n\n"
        for viz_type, template in self.svg_templates.items():
            output += f"### {viz_type.replace('_', ' ').title()}\n\n"
            output += f"```svg\n{template}\n```\n\n"

        return output

    def select_reference_poster(self, content_analysis: Dict[str, Any]) -> Optional[str]:
        """
        콘텐츠 분석 결과를 기반으로 최적 참조 포스터 HTML을 반환.

        Args:
            content_analysis: 콘텐츠 분석 결과 딕셔너리
                - has_pipeline: bool
                - has_performance_metrics: bool
                - keywords: list

        Returns:
            참조 포스터 HTML 문자열 또는 None
        """
        ref_dir = Path(os.path.dirname(os.path.abspath(__file__))) / "reference_posters"
        metadata_path = ref_dir / "metadata.yaml"

        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = yaml.safe_load(f)
        except Exception:
            return None

        # 선택 규칙 적용
        rules = metadata.get('selection_rules', {})
        selected_key = rules.get('default', 'multi_crit_reference')

        if content_analysis.get('has_pipeline', False):
            selected_key = rules.get('has_pipeline', selected_key)
        elif content_analysis.get('has_performance_metrics', False):
            selected_key = rules.get('has_performance_metrics', selected_key)

        # 참조 포스터 메타데이터에서 파일명 가져오기
        posters = metadata.get('reference_posters', {})
        poster_meta = posters.get(selected_key, {})
        filename = poster_meta.get('file')

        if not filename:
            return None

        poster_path = ref_dir / filename
        if not poster_path.exists():
            return None

        try:
            return poster_path.read_text(encoding='utf-8')
        except Exception:
            return None


# Singleton instance
_design_pattern_manager = None

def get_design_pattern_manager() -> DesignPatternManager:
    """Get singleton instance of DesignPatternManager"""
    global _design_pattern_manager
    if _design_pattern_manager is None:
        _design_pattern_manager = DesignPatternManager()
    return _design_pattern_manager

