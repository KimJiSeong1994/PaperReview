"""
Poster Layout Agent

콘텐츠 기반으로 최적의 레이아웃을 결정하는 에이전트
Paper2Poster의 Layout Planning 단계 구현
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

# Add parent directory to path for imports

try:
    from app.DeepAgent.config.design_pattern_manager import DesignPatternManager, get_design_pattern_manager
except ImportError:
    DesignPatternManager = None
    get_design_pattern_manager = None


class LayoutType(Enum):
    """레이아웃 타입"""
    THREE_COLUMN = "3-column"
    TWO_COLUMN = "2-column"
    ONE_COLUMN = "1-column"


class SectionSize(Enum):
    """섹션 크기"""
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


@dataclass
class Section:
    """포스터 섹션"""
    id: str
    title: str
    content: Any
    size: SectionSize
    column: int
    order: int


@dataclass
class LayoutPlan:
    """레이아웃 계획"""
    layout_type: LayoutType
    aspect_ratio: str
    columns: int
    sections: List[Section]
    grid_template: str
    # 새로 추가: 디자인 패턴 정보
    design_pattern: Optional[str] = None
    pattern_config: Optional[Dict[str, Any]] = None


class PosterLayoutAgent:
    """
    콘텐츠 기반으로 포스터 레이아웃을 결정하는 에이전트

    역할:
    - 콘텐츠 분량에 따라 레이아웃 타입 결정 (1단/2단/3단)
    - 섹션 배치 최적화
    - 시각적 균형 계산
    - 디자인 패턴 기반 레이아웃 선택 (Multi-Crit, LlamaDuo 등)
    """

    def __init__(self, design_pattern_manager: Optional[Any] = None):
        self.aspect_ratio = "20:9"  # 가로형 와이드
        self.pattern_manager = design_pattern_manager or (get_design_pattern_manager() if get_design_pattern_manager else None)

    def plan(self, content) -> LayoutPlan:
        """
        콘텐츠 기반 레이아웃 계획 수립

        Args:
            content: ExtractedContent 객체

        Returns:
            LayoutPlan: 레이아웃 계획
        """
        # 1. 디자인 패턴 선택 (DesignPatternManager 사용)
        design_pattern, pattern_config = self.select_layout_pattern(content)

        # 2. 레이아웃 타입 결정 (패턴 기반 또는 기존 로직)
        if pattern_config and 'layout' in pattern_config:
            layout_type = self._pattern_to_layout_type(pattern_config['layout'])
        else:
            layout_type = self._decide_layout_type(content)

        columns = self._get_columns(layout_type)

        # 3. 섹션 생성 및 배치 (패턴 기반 또는 기존 로직)
        if pattern_config and 'layout' in pattern_config:
            sections = self._create_sections_from_pattern(content, pattern_config['layout'])
        else:
            sections = self._create_sections(content, layout_type)

        # 4. 그리드 템플릿 생성 (패턴 기반 또는 기존 로직)
        if pattern_config and 'layout' in pattern_config:
            grid_template = self._generate_grid_template_from_pattern(pattern_config['layout'])
        else:
            grid_template = self._generate_grid_template(layout_type)

        return LayoutPlan(
            layout_type=layout_type,
            aspect_ratio=self.aspect_ratio,
            columns=columns,
            sections=sections,
            grid_template=grid_template,
            design_pattern=design_pattern,
            pattern_config=pattern_config
        )

    def _decide_layout_type(self, content) -> LayoutType:
        """
        콘텐츠 분량 기반 레이아웃 타입 결정

        기준:
        - 논문 수 >= 3 and 발견 >= 4: 3단 레이아웃
        - 논문 수 >= 2 or 발견 >= 3: 2단 레이아웃
        - 기타: 1단 레이아웃
        """
        num_papers = len(content.paper_titles)
        num_findings = len(content.key_findings)
        num_contributions = len(content.contributions)

        # 콘텐츠 복잡도 계산
        complexity_score = (
            num_papers * 2 +
            num_findings * 1.5 +
            num_contributions * 1
        )

        if complexity_score >= 12:
            return LayoutType.THREE_COLUMN
        elif complexity_score >= 6:
            return LayoutType.TWO_COLUMN
        else:
            return LayoutType.ONE_COLUMN

    def _get_columns(self, layout_type: LayoutType) -> int:
        """레이아웃 타입에서 컬럼 수 반환"""
        mapping = {
            LayoutType.THREE_COLUMN: 3,
            LayoutType.TWO_COLUMN: 2,
            LayoutType.ONE_COLUMN: 1
        }
        return mapping[layout_type]

    def _create_sections(self, content, layout_type: LayoutType) -> List[Section]:
        """섹션 생성 및 배치"""
        sections = []

        if layout_type == LayoutType.THREE_COLUMN:
            sections = self._create_three_column_sections(content)
        elif layout_type == LayoutType.TWO_COLUMN:
            sections = self._create_two_column_sections(content)
        else:
            sections = self._create_one_column_sections(content)

        return sections

    def _create_three_column_sections(self, content) -> List[Section]:
        """3단 레이아웃 섹션 생성"""
        sections = []

        # Column 1: 초록, 배경, 기여
        sections.append(Section(
            id="abstract",
            title="1. 초록 (Abstract)",
            content=content.abstract,
            size=SectionSize.MEDIUM,
            column=1,
            order=1
        ))

        sections.append(Section(
            id="motivation",
            title="2. 연구 배경 (Motivation)",
            content=content.motivation,
            size=SectionSize.MEDIUM,
            column=1,
            order=2
        ))

        sections.append(Section(
            id="contributions",
            title="3. 핵심 기여 (Contributions)",
            content=content.contributions,
            size=SectionSize.SMALL,
            column=1,
            order=3
        ))

        # Column 2: 아키텍처, 알고리즘 (각 섹션에 관련 viz_data 서브셋만 전달)
        viz_data = getattr(content, 'visualization_data', None)
        if not isinstance(viz_data, dict):
            viz_data = None
        arch_viz = {'pipeline_steps': viz_data.get('pipeline_steps', [])} if viz_data else None
        algo_viz = {
            'paper_results': viz_data.get('paper_results', []),
            'quantitative': viz_data.get('quantitative', {}),
        } if viz_data else None

        sections.append(Section(
            id="architecture",
            title="4. 모델 아키텍처 (Architecture)",
            content={"type": "svg_diagram", "content": content.methodology,
                     "visualization_data": arch_viz},
            size=SectionSize.LARGE,
            column=2,
            order=4
        ))

        sections.append(Section(
            id="algorithm",
            title="5. 알고리즘 흐름 (Algorithm)",
            content={"type": "svg_flowchart", "papers": content.paper_titles,
                     "visualization_data": algo_viz},
            size=SectionSize.MEDIUM,
            column=2,
            order=5
        ))

        # Column 3: 발견, 비교, 결론
        sections.append(Section(
            id="findings",
            title="6. 핵심 발견 (Key Findings)",
            content=content.key_findings,
            size=SectionSize.MEDIUM,
            column=3,
            order=6
        ))

        sections.append(Section(
            id="comparison",
            title="7. 비교 분석",
            content=content.comparison_data,
            size=SectionSize.SMALL,
            column=3,
            order=7
        ))

        sections.append(Section(
            id="conclusion",
            title="8. 결론 (Conclusion)",
            content=content.conclusion,
            size=SectionSize.SMALL,
            column=3,
            order=8
        ))

        return sections

    def _create_two_column_sections(self, content) -> List[Section]:
        """2단 레이아웃 섹션 생성"""
        sections = []

        # Column 1
        sections.append(Section(
            id="abstract",
            title="1. 초록 (Abstract)",
            content=content.abstract,
            size=SectionSize.MEDIUM,
            column=1,
            order=1
        ))

        sections.append(Section(
            id="motivation",
            title="2. 연구 배경",
            content=content.motivation,
            size=SectionSize.MEDIUM,
            column=1,
            order=2
        ))

        sections.append(Section(
            id="findings",
            title="3. 핵심 발견",
            content=content.key_findings,
            size=SectionSize.MEDIUM,
            column=1,
            order=3
        ))

        # Column 2 (파이프라인 관련 viz_data만 전달)
        viz_data = getattr(content, 'visualization_data', None)
        if not isinstance(viz_data, dict):
            viz_data = None
        arch_viz = {'pipeline_steps': viz_data.get('pipeline_steps', [])} if viz_data else None
        sections.append(Section(
            id="architecture",
            title="4. 분석 프레임워크",
            content={"type": "svg_diagram", "content": content.methodology,
                     "visualization_data": arch_viz},
            size=SectionSize.LARGE,
            column=2,
            order=4
        ))

        sections.append(Section(
            id="conclusion",
            title="5. 결론",
            content=content.conclusion,
            size=SectionSize.SMALL,
            column=2,
            order=5
        ))

        return sections

    def _create_one_column_sections(self, content) -> List[Section]:
        """1단 레이아웃 섹션 생성"""
        sections = []

        sections.append(Section(
            id="abstract",
            title="초록",
            content=content.abstract,
            size=SectionSize.LARGE,
            column=1,
            order=1
        ))

        sections.append(Section(
            id="content",
            title="분석 내용",
            content=content.methodology,
            size=SectionSize.LARGE,
            column=1,
            order=2
        ))

        sections.append(Section(
            id="conclusion",
            title="결론",
            content=content.conclusion,
            size=SectionSize.MEDIUM,
            column=1,
            order=3
        ))

        return sections

    def _generate_grid_template(self, layout_type: LayoutType) -> str:
        """CSS Grid 템플릿 생성"""
        templates = {
            LayoutType.THREE_COLUMN: "1fr 2fr 1fr",
            LayoutType.TWO_COLUMN: "1fr 1fr",
            LayoutType.ONE_COLUMN: "1fr"
        }
        return templates[layout_type]

    def calculate_visual_balance(self, sections: List[Section]) -> float:
        """
        시각적 균형 점수 계산

        Returns:
            0.0 ~ 1.0 사이의 균형 점수
        """
        if not sections:
            return 0.0

        # 각 컬럼별 섹션 수 계산
        column_counts = {}
        for section in sections:
            column_counts[section.column] = column_counts.get(section.column, 0) + 1

        # 균등 분포 점수 계산
        if not column_counts:
            return 0.0

        avg_count = sum(column_counts.values()) / len(column_counts)
        variance = sum((count - avg_count) ** 2 for count in column_counts.values()) / len(column_counts)

        # 분산이 작을수록 균형이 좋음
        balance_score = max(0.0, 1.0 - (variance / (avg_count + 1)))

        return balance_score

    def select_layout_pattern(self, content) -> tuple:
        """
        콘텐츠 분석 기반으로 최적의 디자인 패턴 선택

        Args:
            content: ExtractedContent 객체 (content_analysis 포함)

        Returns:
            Tuple of (pattern_name, pattern_config)
        """
        if not self.pattern_manager:
            return None, None

        # content_analysis 속성 확인
        if not hasattr(content, 'content_analysis'):
            return None, None

        content_analysis = content.content_analysis

        # DesignPatternManager의 suggest_pattern 사용
        suggested_pattern = self.pattern_manager.suggest_pattern(content_analysis)
        pattern_config = self.pattern_manager.get_pattern(suggested_pattern)

        return suggested_pattern, pattern_config

    def _pattern_to_layout_type(self, pattern_layout: Dict[str, Any]) -> LayoutType:
        """
        패턴의 레이아웃 타입을 LayoutType enum으로 변환

        Args:
            pattern_layout: 패턴의 layout 설정

        Returns:
            LayoutType
        """
        layout_type_str = pattern_layout.get('type', 'three_column')

        if 'three' in layout_type_str or '3' in layout_type_str:
            return LayoutType.THREE_COLUMN
        elif 'two' in layout_type_str or '2' in layout_type_str:
            return LayoutType.TWO_COLUMN
        else:
            return LayoutType.ONE_COLUMN

    def _generate_grid_template_from_pattern(self, pattern_layout: Dict[str, Any]) -> str:
        """
        패턴의 레이아웃 설정에서 CSS Grid 템플릿 생성

        Args:
            pattern_layout: 패턴의 layout 설정

        Returns:
            CSS Grid template string
        """
        ratio = pattern_layout.get('ratio', [1, 1, 1])
        ratio_fr = ' '.join([f"{r}fr" for r in ratio])
        return f"grid-template-columns: {ratio_fr};"

    def _create_sections_from_pattern(self, content, pattern_layout: Dict[str, Any]) -> List[Section]:
        """
        패턴의 섹션 배치에 따라 섹션 생성

        Args:
            content: ExtractedContent 객체
            pattern_layout: 패턴의 layout 설정

        Returns:
            List of Section objects
        """
        sections = []
        section_map = pattern_layout.get('sections', {})

        # 패턴에 정의된 섹션 배치 사용
        for column_name, section_list in section_map.items():
            # column_name을 숫자로 변환 (left=0, center=1, right=2)
            column_mapping = {'left': 1, 'center': 2, 'right': 3}
            column_idx = column_mapping.get(column_name, 1)

            for order, section_id in enumerate(section_list):
                # section_id에 따라 적절한 콘텐츠 매핑
                section = self._create_section_for_id(section_id, content, column_idx, order)
                if section:
                    sections.append(section)

        return sections

    def _create_section_for_id(self, section_id: str, content, column: int, order: int) -> Optional[Section]:
        """
        섹션 ID에 따라 Section 객체 생성

        Args:
            section_id: 섹션 식별자 (예: "motivation", "abstract", "key_findings")
            content: ExtractedContent 객체
            column: 컬럼 번호
            order: 섹션 순서

        Returns:
            Section object or None
        """
        viz_data = getattr(content, 'visualization_data', None)
        if not isinstance(viz_data, dict):
            viz_data = None
        arch_viz = {'pipeline_steps': viz_data.get('pipeline_steps', [])} if viz_data else None
        algo_viz = {
            'paper_results': viz_data.get('paper_results', []),
            'quantitative': viz_data.get('quantitative', {}),
        } if viz_data else None
        section_mapping = {
            'motivation': ('연구 배경', content.motivation, SectionSize.MEDIUM),
            'abstract': ('초록', content.abstract, SectionSize.MEDIUM),
            'methodology': ('방법론', content.methodology, SectionSize.LARGE),
            'contributions': ('핵심 기여', content.contributions, SectionSize.MEDIUM),
            'key_findings': ('주요 발견', content.key_findings, SectionSize.LARGE),
            'conclusion': ('결론', content.conclusion, SectionSize.MEDIUM),
            'timeline': ('연구 타임라인', content.paper_titles, SectionSize.MEDIUM),
            'architecture_diagram': ('모델 아키텍처',
                                     {"type": "svg_diagram", "content": content.methodology,
                                      "visualization_data": arch_viz},
                                     SectionSize.LARGE),
            'algorithm_flowchart': ('알고리즘 순서도',
                                    {"type": "svg_flowchart", "papers": content.paper_titles,
                                     "visualization_data": algo_viz},
                                    SectionSize.LARGE),
            'results_chart': ('실험 결과',
                              {"type": "svg_bar_chart",
                               "visualization_data": algo_viz},
                              SectionSize.MEDIUM),
            'pipeline_diagram': ('파이프라인',
                                 {"type": "svg_diagram", "content": content.methodology,
                                  "visualization_data": arch_viz},
                                 SectionSize.LARGE),
            'experimental_results': ('실험 결과', content.key_findings, SectionSize.LARGE),
            'research_history': ('연구 연혁', content.paper_titles, SectionSize.MEDIUM),
            'future_work': ('향후 연구', content.conclusion, SectionSize.SMALL),
            'key_components': ('핵심 구성요소', content.contributions, SectionSize.MEDIUM),
            'economic_benefits': ('경제적 효과', content.key_findings, SectionSize.SMALL),
        }

        if section_id in section_mapping:
            title, section_content, size = section_mapping[section_id]
            return Section(
                id=section_id,
                title=title,
                content=section_content,
                size=size,
                column=column,
                order=order
            )

        return None

