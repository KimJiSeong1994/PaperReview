"""
Poster Layout Agent

콘텐츠 기반으로 최적의 레이아웃을 결정하는 에이전트
Paper2Poster의 Layout Planning 단계 구현
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum


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


class PosterLayoutAgent:
    """
    콘텐츠 기반으로 포스터 레이아웃을 결정하는 에이전트
    
    역할:
    - 콘텐츠 분량에 따라 레이아웃 타입 결정 (1단/2단/3단)
    - 섹션 배치 최적화
    - 시각적 균형 계산
    """
    
    def __init__(self):
        self.aspect_ratio = "20:9"  # 가로형 와이드
    
    def plan(self, content) -> LayoutPlan:
        """
        콘텐츠 기반 레이아웃 계획 수립
        
        Args:
            content: ExtractedContent 객체
            
        Returns:
            LayoutPlan: 레이아웃 계획
        """
        # 1. 레이아웃 타입 결정
        layout_type = self._decide_layout_type(content)
        columns = self._get_columns(layout_type)
        
        # 2. 섹션 생성 및 배치
        sections = self._create_sections(content, layout_type)
        
        # 3. 그리드 템플릿 생성
        grid_template = self._generate_grid_template(layout_type)
        
        return LayoutPlan(
            layout_type=layout_type,
            aspect_ratio=self.aspect_ratio,
            columns=columns,
            sections=sections,
            grid_template=grid_template
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
        
        # Column 2: 아키텍처, 알고리즘
        sections.append(Section(
            id="architecture",
            title="4. 모델 아키텍처 (Architecture)",
            content={"type": "svg_diagram", "content": content.methodology},
            size=SectionSize.LARGE,
            column=2,
            order=4
        ))
        
        sections.append(Section(
            id="algorithm",
            title="5. 알고리즘 흐름 (Algorithm)",
            content={"type": "svg_flowchart", "papers": content.paper_titles},
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
        
        # Column 2
        sections.append(Section(
            id="architecture",
            title="4. 분석 프레임워크",
            content={"type": "svg_diagram", "content": content.methodology},
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

