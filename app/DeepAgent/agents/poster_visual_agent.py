"""
Poster Visual Agent

SVG 다이어그램 및 시각화를 생성하는 에이전트
Paper2Poster의 Visual Generation 단계 구현
"""

from typing import Dict, List, Any, Optional
import re


class PosterVisualAgent:
    """
    SVG 다이어그램 및 시각화를 생성하는 에이전트

    역할:
    - 모델 아키텍처 SVG 생성
    - 알고리즘 순서도 SVG 생성
    - 비교 차트/테이블 HTML 생성
    """

    @staticmethod
    def _escape_xml(text: str) -> str:
        """SVG/XML 특수문자를 이스케이프한다."""
        if not text:
            return ''
        return (str(text)
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#39;'))

    def __init__(self, autofigure_svgs: Optional[List[Dict[str, Any]]] = None):
        """
        Args:
            autofigure_svgs: AutoFigure-Edit로 생성된 SVG 리스트 (옵션).
                [{"paper_title": str, "svg_content": str}, ...]
                제공되면 아키텍처/파이프라인 다이어그램에 우선 사용된다.
        """
        self._autofigure_svgs = autofigure_svgs or []
        self._autofigure_used = 0  # 사용된 AutoFigure SVG 카운터
        self.color_palette = {
            'blue': '#2563eb',
            'blue_light': '#dbeafe',
            'blue_bg': '#eff6ff',
            'orange': '#ea580c',
            'orange_light': '#ffedd5',
            'orange_bg': '#fff7ed',
            'green': '#16a34a',
            'green_light': '#dcfce7',
            'green_bg': '#f0fdf4',
            'gray': '#1e293b',
            'gray_light': '#94a3b8',
            'purple': '#8b5cf6',
            'red': '#ef4444'
        }

    def _try_autofigure_svg(self) -> Optional[str]:
        """AutoFigure SVG가 남아있으면 하나를 소비하여 반환한다."""
        if self._autofigure_used < len(self._autofigure_svgs):
            fig = self._autofigure_svgs[self._autofigure_used]
            svg = fig.get("svg_content", "")
            title = fig.get("paper_title", "")
            self._autofigure_used += 1
            if svg:
                return f'''<div style="text-align: center;">
                    {svg}
                    <p style="font-size: 0.85rem; color: #64748b; margin-top: 6px; font-style: italic;">{self._escape_xml(title)}</p>
                </div>'''
        return None

    def generate_section(self, section) -> str:
        """
        섹션별 HTML 생성 (병렬 처리 가능)

        Args:
            section: Section 객체

        Returns:
            생성된 HTML 문자열
        """
        if section.content is None:
            return self.generate_text_html('')
        if isinstance(section.content, dict) and section.content.get('type') == 'svg_diagram':
            # 하이브리드: AutoFigure SVG가 있으면 우선 사용
            af_svg = self._try_autofigure_svg()
            if af_svg:
                return af_svg
            return self.generate_architecture_svg(
                section.content.get('content', ''),
                visualization_data=section.content.get('visualization_data'),
            )
        elif isinstance(section.content, dict) and section.content.get('type') == 'svg_flowchart':
            # 하이브리드: AutoFigure SVG가 있으면 우선 사용
            af_svg = self._try_autofigure_svg()
            if af_svg:
                return af_svg
            return self.generate_algorithm_svg(
                section.content.get('papers', []),
                visualization_data=section.content.get('visualization_data'),
            )
        elif isinstance(section.content, dict) and section.content.get('type') == 'svg_bar_chart':
            return self._generate_quantitative_chart(
                section.content.get('visualization_data'),
            )
        elif isinstance(section.content, dict):
            return self.generate_comparison_table(section.content)
        elif isinstance(section.content, list):
            return self.generate_list_html(section.content)
        else:
            return self.generate_text_html(section.content)

    def generate_architecture_svg(self, methodology: str = "",
                                   visualization_data: Optional[Dict[str, Any]] = None) -> str:
        """
        데이터 기반 아키텍처/파이프라인 SVG 생성.

        방법론 텍스트에서 파이프라인 단계를 추출하거나
        visualization_data의 pipeline_steps를 활용하여 동적 다이어그램을 생성한다.
        """
        steps = []

        # 1순위: 구조화 데이터
        if visualization_data and visualization_data.get('pipeline_steps'):
            steps = visualization_data['pipeline_steps']

        # 2순위: 방법론 텍스트 파싱
        if not steps and methodology:
            steps = self._parse_methodology_steps(methodology)

        # 3순위: 기본 fallback
        if not steps:
            steps = [
                {'title': 'Input', 'desc': 'Data Collection'},
                {'title': 'Processing', 'desc': 'Analysis & Modeling'},
                {'title': 'Output', 'desc': 'Results & Evaluation'},
            ]

        return self.generate_pipeline_diagram(steps)

    def generate_algorithm_svg(self, papers: List[str] = None,
                                visualization_data: Optional[Dict[str, Any]] = None) -> str:
        """
        데이터 기반 비교/분석 SVG 생성.

        논문별 수치 결과가 있으면 바 차트, 없으면 논문 카드 레이아웃 SVG를 생성한다.
        """
        # 1순위: 정량 데이터 → 바 차트
        if visualization_data and visualization_data.get('paper_results'):
            return self._generate_results_chart(visualization_data['paper_results'])

        # 2순위: 논문 제목 → 비교 카드 SVG
        if papers:
            return self._generate_paper_comparison_svg(papers)

        # 3순위: 기본 바 차트
        return self.generate_bar_chart({
            'labels': ['Paper 1', 'Paper 2', 'Paper 3'],
            'values': [0.85, 0.78, 0.92],
        })

    # ── 데이터 기반 SVG 헬퍼 ────────────────────────────────────────

    def _parse_methodology_steps(self, methodology: str) -> List[Dict[str, str]]:
        """방법론 텍스트에서 파이프라인 단계를 추출한다."""
        steps: List[Dict[str, str]] = []

        # 전략 1: 화살표 분리
        text = methodology.replace('->', '→')
        if '→' in text:
            parts = [p.strip() for p in text.split('→') if p.strip()]
            for part in parts[:8]:
                clean = re.sub(r'\*\*|\*|`', '', part).split('\n')[0].strip()
                if clean and len(clean) > 2:
                    steps.append({'title': clean[:30], 'desc': ''})

        # 전략 2: 번호 매기기 (숫자+구분자로 분할)
        if not steps:
            parts = re.split(r'\d+[.)]\s*\*?\*?', methodology)
            for part in parts[1:8]:
                clean = re.sub(r'\*\*|\*|`', '', part).split('\n')[0].strip()
                if clean and len(clean) > 1:
                    steps.append({'title': clean[:30], 'desc': ''})

        # 전략 3: 볼드 키워드
        if not steps:
            skip_kw = {'결과', 'result', '한계', 'limit', '배경', 'background',
                       '결론', 'conclusion', '요약', 'summary'}
            bold = re.findall(r'\*\*([^*]{3,50})\*\*', methodology)
            for b in bold[:8]:
                if not any(sk in b.lower() for sk in skip_kw):
                    steps.append({'title': b.strip()[:30], 'desc': ''})

        return steps

    def _generate_quantitative_chart(self, visualization_data: Optional[Dict[str, Any]] = None) -> str:
        """정량적 메트릭 데이터를 바 차트 SVG로 시각화한다."""
        if visualization_data:
            quant = visualization_data.get('quantitative', {})
            if isinstance(quant, dict):
                metrics = quant.get('metrics', [])
                if isinstance(metrics, list) and metrics:
                    labels = []
                    values = []
                    for m in metrics[:6]:
                        if isinstance(m, dict) and m.get('name') and m.get('value') is not None:
                            try:
                                val = float(m['value'])
                                labels.append(self._escape_xml(str(m['name'])[:15]))
                                values.append(val)
                            except (ValueError, TypeError):
                                continue
                    if labels:
                        max_val = max(values) if values else 1
                        if max_val > 1:
                            normalized = [v / max_val for v in values]
                        else:
                            normalized = values
                        return self.generate_bar_chart({'labels': labels, 'values': normalized})
        return self.generate_bar_chart({})

    def _generate_results_chart(self, paper_results: List[Dict[str, Any]]) -> str:
        """논문별 수치 결과를 바 차트 SVG로 변환한다."""
        labels = []
        values = []
        for result in paper_results[:6]:
            title = result.get('paper_title', '')[:20]
            metrics = result.get('metrics', [])
            if metrics and isinstance(metrics[0], dict):
                try:
                    val = float(metrics[0].get('value', 0))
                    labels.append(self._escape_xml(title))
                    values.append(val)
                except (ValueError, TypeError):
                    continue

        if not labels:
            return self.generate_bar_chart({})

        # 0~1 범위로 정규화
        max_val = max(values) if values else 1
        if max_val > 1:
            normalized = [v / max_val for v in values]
        else:
            normalized = values

        return self.generate_bar_chart({'labels': labels, 'values': normalized})

    def _generate_paper_comparison_svg(self, papers: List[str]) -> str:
        """논문 제목을 카드 레이아웃 SVG로 시각화한다."""
        n = min(len(papers), 6)
        card_w, card_h, gap = 140, 70, 25
        total_w = n * (card_w + gap) + 60
        colors = [self.color_palette['blue'], self.color_palette['orange'],
                  self.color_palette['green'], self.color_palette['purple'],
                  self.color_palette['red'], self.color_palette['gray']]

        svg = (f'<svg viewBox="0 0 {total_w} 160" '
               f'style="background: #f8fafc; border-radius: 8px; width: 100%;">')
        svg += ('\n  <text x="30" y="25" font-size="13" font-weight="bold" '
                'fill="#1e293b">Analyzed Papers</text>')

        for i, title in enumerate(papers[:n]):
            x = 30 + i * (card_w + gap)
            color = colors[i % len(colors)]
            # 2줄로 분할 (약 20자씩) + XML 이스케이프
            line1 = self._escape_xml(title[:22])
            line2 = self._escape_xml(title[22:44] + ('...' if len(title) > 44 else ''))

            svg += f'''
  <rect x="{x}" y="40" width="{card_w}" height="{card_h}" rx="10"
        fill="white" stroke="{color}" stroke-width="2"/>
  <circle cx="{x + 15}" cy="55" r="8" fill="{color}" opacity="0.2"/>
  <text x="{x + 15}" y="59" text-anchor="middle" font-size="10"
        font-weight="bold" fill="{color}">{i + 1}</text>
  <text x="{x + 30}" y="68" font-size="9" fill="#334155">{line1}</text>
  <text x="{x + 30}" y="82" font-size="9" fill="#64748b">{line2}</text>'''

        svg += '\n</svg>'
        return svg

    def generate_comparison_table(self, data: Dict[str, Any]) -> str:
        """비교 분석 테이블 HTML 생성"""
        num_papers = data.get('num_papers', 0)
        num_findings = data.get('num_findings', 0)
        completion = data.get('completion_rate', 100)

        return f'''<table style="width: 100%; font-size: 0.85rem; border-collapse: collapse;">
            <thead>
                <tr style="border-bottom: 2px solid #cbd5e1;">
                    <th style="padding: 6px; text-align: left;">항목</th>
                    <th style="padding: 6px; text-align: center;">분석 결과</th>
                </tr>
            </thead>
            <tbody>
                <tr style="border-bottom: 1px solid #e2e8f0;">
                    <td style="padding: 6px;">분석 논문 수</td>
                    <td style="padding: 6px; text-align: center; color: #2563eb; font-weight: bold;">{num_papers}편</td>
                </tr>
                <tr style="border-bottom: 1px solid #e2e8f0;">
                    <td style="padding: 6px;">주요 발견</td>
                    <td style="padding: 6px; text-align: center; color: #16a34a; font-weight: bold;">{num_findings}건</td>
                </tr>
                <tr>
                    <td style="padding: 6px;">분석 완료율</td>
                    <td style="padding: 6px; text-align: center; color: #ea580c; font-weight: bold;">{completion}%</td>
                </tr>
            </tbody>
        </table>'''

    def generate_list_html(self, items: List[str]) -> str:
        """리스트 항목 HTML 생성"""
        if not items:
            return '<p class="text-gray-500">내용 없음</p>'

        list_items = "".join([f'<li class="py-1 border-b border-slate-100">{self._escape_xml(item)}</li>'
                              for item in items])
        return f'<ul class="space-y-1">{list_items}</ul>'

    def generate_text_html(self, text: str) -> str:
        """텍스트 콘텐츠 HTML 생성"""
        if not text or not str(text).strip():
            return '<p class="text-gray-500">내용이 비어있습니다.</p>'
        return f'<p>{self._escape_xml(text)}</p>'

    def generate_paper_list_html(self, papers: List[str]) -> str:
        """논문 목록 HTML 생성"""
        if not papers:
            return '<li class="text-gray-500">논문 정보 없음</li>'

        return "".join([f'<li class="border-l-4 border-blue-500 pl-3 py-1 mb-2">{self._escape_xml(title)}</li>'
                        for title in papers])

    def generate_contributions_html(self, contributions: List[str]) -> str:
        """기여 항목 HTML 생성 (번호 아이콘 포함)"""
        if not contributions:
            return '<p>기여 내용 없음</p>'

        items = []
        for i, contrib in enumerate(contributions):
            items.append(f'''<li class="flex items-start">
                <span class="bg-blue-600 text-white rounded-full w-5 h-5 flex items-center justify-center mr-2 mt-1 text-xs flex-shrink-0">{i+1}</span>
                <div>{self._escape_xml(contrib)}</div>
            </li>''')

        return f'<ul class="space-y-2">{"".join(items)}</ul>'

    def generate_highlight_box(self, quote: str) -> str:
        """강조 박스 HTML 생성"""
        if not quote:
            return ''

        return f'''<div class="highlight-box">
            "{self._escape_xml(quote)}"
        </div>'''

    def generate_keywords_html(self, keywords: List[str]) -> str:
        """키워드 배지 HTML 생성"""
        if not keywords:
            return '<p class="text-gray-500">키워드 없음</p>'

        badges = " ".join([f'<span class="bg-blue-100 text-blue-800 px-3 py-1 rounded-full text-sm mr-2 mb-2 inline-block">{self._escape_xml(kw)}</span>'
                          for kw in keywords[:8]])
        return f'<div class="flex flex-wrap">{badges}</div>'

    def generate_radar_chart(self, data: Dict[str, Any]) -> str:
        """
        Radar Chart (Multi-Crit 스타일) SVG 생성

        Args:
            data: 차트 데이터 (dimensions, values 등)

        Returns:
            SVG 문자열
        """
        dimensions = data.get('dimensions', ['Completeness', 'Efficiency', 'Grounding', 'Logic', 'Expressiveness', 'Hallucination'])
        values = data.get('values', [0.85, 0.75, 0.90, 0.80, 0.70, 0.88])

        # 중심점과 반지름
        cx, cy, radius = 200, 200, 150
        n = len(dimensions)

        # dimensions/values 길이 맞춤
        if len(values) > n:
            values = values[:n]
        elif len(values) < n:
            values = values + [0.5] * (n - len(values))

        # 각도 계산 (시작점: 위쪽)
        import math
        angles = [(-90 + i * 360 / n) * math.pi / 180 for i in range(n)]

        # 데이터 포인트 계산
        points = []
        for i, value in enumerate(values):
            x = cx + radius * value * math.cos(angles[i])
            y = cy + radius * value * math.sin(angles[i])
            points.append(f"{x},{y}")

        # 축 끝점 계산
        axis_points = []
        for angle in angles:
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            axis_points.append((x, y))

        svg = f'''<svg viewBox="0 0 400 400" style="background: white; border-radius: 8px;">
            <defs>
                <linearGradient id="radarGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" style="stop-color:{self.color_palette['blue']};stop-opacity:0.6" />
                    <stop offset="100%" style="stop-color:{self.color_palette['blue_light']};stop-opacity:0.8" />
                </linearGradient>
            </defs>

            <!-- Background circles (grid) -->
            <circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="#e2e8f0" stroke-width="1"/>
            <circle cx="{cx}" cy="{cy}" r="{radius * 0.67}" fill="none" stroke="#e2e8f0" stroke-width="1"/>
            <circle cx="{cx}" cy="{cy}" r="{radius * 0.33}" fill="none" stroke="#e2e8f0" stroke-width="1"/>

            <!-- Axes -->'''

        for i, (x, y) in enumerate(axis_points):
            svg += f'\n            <line x1="{cx}" y1="{cy}" x2="{x}" y2="{y}" stroke="#cbd5e1" stroke-width="1"/>'

        # Data polygon
        svg += f'''

            <!-- Data polygon -->
            <polygon points="{' '.join(points)}"
                     fill="url(#radarGrad)"
                     stroke="{self.color_palette['blue']}"
                     stroke-width="2"
                     opacity="0.7"/>'''

        # Labels
        for i, (x, y) in enumerate(axis_points):
            # 레이블 위치 조정 (축 끝점에서 약간 밖으로)
            label_x = cx + (radius + 30) * math.cos(angles[i])
            label_y = cy + (radius + 30) * math.sin(angles[i])

            svg += f'''
            <text x="{label_x}" y="{label_y}" text-anchor="middle" font-size="12" fill="#334155">{self._escape_xml(dimensions[i])}</text>'''

        svg += '\n        </svg>'
        return svg

    def generate_pipeline_diagram(self, steps: List[Dict[str, str]]) -> str:
        """
        Pipeline/Flowchart Diagram (학회 포스터 수준) SVG 생성

        그라데이션, 그림자, 단계 번호 아이콘을 포함한 고품질 SVG.

        Args:
            steps: 파이프라인 단계 리스트 [{'title': '...', 'desc': '...'}, ...]

        Returns:
            SVG 문자열
        """
        if not steps:
            steps = [
                {'title': 'Step 1', 'desc': 'Data Input'},
                {'title': 'Step 2', 'desc': 'Processing'},
                {'title': 'Step 3', 'desc': 'Output'}
            ]

        n_steps = min(len(steps), 8)
        box_width = 150
        box_height = 90
        gap = 50
        total_width = n_steps * box_width + (n_steps - 1) * gap + 80
        start_x = 40
        y = 60

        colors = [
            ('#2563eb', '#dbeafe'), ('#7c3aed', '#ede9fe'), ('#059669', '#d1fae5'),
            ('#ea580c', '#ffedd5'), ('#0891b2', '#cffafe'), ('#d97706', '#fef3c7'),
            ('#e11d48', '#ffe4e6'), ('#4f46e5', '#e0e7ff'),
        ]

        svg = f'''<svg viewBox="0 0 {total_width} {box_height + 100}" style="background:white; border-radius:12px; width:100%;">
            <defs>
                <marker id="pipeArrow" markerWidth="12" markerHeight="8" refX="11" refY="4" orient="auto">
                    <path d="M0,0 L12,4 L0,8 L3,4 Z" fill="#94a3b8"/>
                </marker>
                <filter id="pipeShadow" x="-5%" y="-5%" width="110%" height="120%">
                    <feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity="0.1"/>
                </filter>
            </defs>'''

        for i, step in enumerate(steps[:n_steps]):
            x = start_x + i * (box_width + gap)
            color, bg_color = colors[i % len(colors)]
            title = self._escape_xml(step.get('title', f'Step {i+1}')[:22])
            desc = self._escape_xml(step.get('desc', '')[:28])

            # Box with shadow
            svg += f'''
            <rect x="{x}" y="{y}" width="{box_width}" height="{box_height}" rx="12"
                  fill="{bg_color}" stroke="{color}" stroke-width="2" filter="url(#pipeShadow)"/>
            <circle cx="{x + 20}" cy="{y + 20}" r="12" fill="{color}"/>
            <text x="{x + 20}" y="{y + 24}" text-anchor="middle" font-size="11" font-weight="bold" fill="white">{i + 1}</text>
            <text x="{x + 40}" y="{y + 24}" font-size="13" font-weight="bold" fill="{color}">{title}</text>
            <text x="{x + box_width / 2}" y="{y + 55}" text-anchor="middle" font-size="11" fill="#64748b">{desc}</text>'''

            # Arrow
            if i < n_steps - 1:
                ax1 = x + box_width + 4
                ax2 = x + box_width + gap - 4
                ay = y + box_height / 2
                svg += f'''
            <line x1="{ax1}" y1="{ay}" x2="{ax2}" y2="{ay}"
                  stroke="#94a3b8" stroke-width="2" stroke-dasharray="6,3" marker-end="url(#pipeArrow)"/>'''

        svg += '\n        </svg>'
        return svg

    def generate_timeline(self, events: List[Dict[str, str]], style: str = 'vertical') -> str:
        """
        Timeline (수직형, Multi-Crit/LlamaDuo 스타일) SVG 생성

        Args:
            events: 이벤트 리스트 [{'year': '2020', 'title': '...', 'desc': '...'}, ...]
            style: 'vertical' or 'horizontal'

        Returns:
            SVG 문자열
        """
        if not events:
            events = [
                {'year': '2020', 'title': 'Event 1', 'desc': 'Description'},
                {'year': '2021', 'title': 'Event 2', 'desc': 'Description'},
                {'year': '2022', 'title': 'Event 3', 'desc': 'Description'}
            ]

        n_events = len(events)
        event_gap = 100
        total_height = n_events * event_gap + 100

        svg = f'''<svg viewBox="0 0 300 {total_height}" style="background: white; border-radius: 8px;">
            <!-- Central line -->
            <line x1="150" y1="50" x2="150" y2="{total_height - 50}"
                  stroke="#cbd5e1" stroke-width="3" stroke-dasharray="5,5"/>'''

        colors = [self.color_palette['blue'], self.color_palette['green'], self.color_palette['orange'], self.color_palette['purple']]

        for i, event in enumerate(events):
            y = 100 + i * event_gap
            color = colors[i % len(colors)]

            # Alternating left/right
            is_left = i % 2 == 0
            text_x = 130 if is_left else 170
            text_anchor = 'end' if is_left else 'start'

            svg += f'''

            <!-- Event {i+1} -->
            <circle cx="150" cy="{y}" r="20" fill="{color}" stroke="white" stroke-width="3"/>
            <circle cx="150" cy="{y}" r="12" fill="white"/>
            <text x="{text_x}" y="{y - 10}" text-anchor="{text_anchor}" font-size="14" font-weight="bold" fill="{color}">{self._escape_xml(event.get('year', ''))}</text>
            <text x="{text_x}" y="{y + 5}" text-anchor="{text_anchor}" font-size="12" fill="#334155">{self._escape_xml(event.get('title', ''))}</text>
            <text x="{text_x}" y="{y + 20}" text-anchor="{text_anchor}" font-size="11" fill="#64748b">{self._escape_xml(event.get('desc', '')[:30])}</text>'''

        svg += '\n        </svg>'
        return svg

    def generate_bar_chart(self, data: Dict[str, Any]) -> str:
        """
        Bar Chart (Multi-Crit 스타일) SVG 생성

        Args:
            data: 차트 데이터 (labels, values 등)

        Returns:
            SVG 문자열
        """
        labels = data.get('labels', ['Model A', 'Model B', 'Model C'])
        values = data.get('values', [0.85, 0.75, 0.90])

        n_bars = len(labels)
        bar_width = 40
        gap = 30
        chart_width = n_bars * (bar_width + gap) + 100
        chart_height = 300

        # Scale values to chart height
        max_value = max(values) if values else 1.0
        scale = 200 / max_value if max_value > 0 else 1.0

        svg = f'''<svg viewBox="0 0 {chart_width} {chart_height}" style="background: white; border-radius: 8px;">
            <!-- Axes -->
            <line x1="50" y1="250" x2="{chart_width - 50}" y2="250" stroke="#cbd5e1" stroke-width="2"/>
            <line x1="50" y1="50" x2="50" y2="250" stroke="#cbd5e1" stroke-width="2"/>

            <!-- Grid lines -->
            <line x1="50" y1="200" x2="{chart_width - 50}" y2="200" stroke="#e2e8f0" stroke-width="1"/>
            <line x1="50" y1="150" x2="{chart_width - 50}" y2="150" stroke="#e2e8f0" stroke-width="1"/>
            <line x1="50" y1="100" x2="{chart_width - 50}" y2="100" stroke="#e2e8f0" stroke-width="1"/>'''

        colors = [self.color_palette['blue'], self.color_palette['orange'], self.color_palette['green']]

        for i, (label, value) in enumerate(zip(labels, values)):
            x = 70 + i * (bar_width + gap)
            bar_height = value * scale
            y = 250 - bar_height
            color = colors[i % len(colors)]

            svg += f'''

            <!-- Bar {i+1} -->
            <rect x="{x}" y="{y}" width="{bar_width}" height="{bar_height}" fill="{color}" opacity="0.8"/>
            <text x="{x + bar_width/2}" y="265" text-anchor="middle" font-size="12" fill="#334155">{self._escape_xml(label)}</text>
            <text x="{x + bar_width/2}" y="{y - 5}" text-anchor="middle" font-size="11" fill="{color}">{value:.2f}</text>'''

        # Y-axis labels
        for i, val in enumerate([0, 0.25, 0.5, 0.75, 1.0]):
            y = 250 - val * 200
            svg += f'''
            <text x="45" y="{y + 5}" text-anchor="end" font-size="11" fill="#64748b">{val:.2f}</text>'''

        svg += '\n        </svg>'
        return svg

