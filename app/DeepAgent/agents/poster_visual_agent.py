"""
Poster Visual Agent

SVG 다이어그램 및 시각화를 생성하는 에이전트
Paper2Poster의 Visual Generation 단계 구현
"""

from typing import Dict, List, Any, Optional
import random


class PosterVisualAgent:
    """
    SVG 다이어그램 및 시각화를 생성하는 에이전트
    
    역할:
    - 모델 아키텍처 SVG 생성
    - 알고리즘 순서도 SVG 생성
    - 비교 차트/테이블 HTML 생성
    """
    
    def __init__(self):
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
    
    def generate_section(self, section) -> str:
        """
        섹션별 HTML 생성 (병렬 처리 가능)
        
        Args:
            section: Section 객체
            
        Returns:
            생성된 HTML 문자열
        """
        if isinstance(section.content, dict) and section.content.get('type') == 'svg_diagram':
            return self.generate_architecture_svg(section.content.get('content', ''))
        elif isinstance(section.content, dict) and section.content.get('type') == 'svg_flowchart':
            return self.generate_algorithm_svg(section.content.get('papers', []))
        elif isinstance(section.content, dict):
            return self.generate_comparison_table(section.content)
        elif isinstance(section.content, list):
            return self.generate_list_html(section.content)
        else:
            return self.generate_text_html(section.content)
    
    def generate_architecture_svg(self, methodology: str = "") -> str:
        """
        모델 아키텍처 SVG 생성
        
        3단계 파이프라인: ENCODING → RETRIEVAL → AGGREGATION
        """
        return '''<svg viewBox="0 0 800 420" style="background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; width: 100%;">
            <defs>
                <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="0" refY="3" orient="auto">
                    <polygon points="0 0, 8 3, 0 6" fill="#475569" />
                </marker>
                <marker id="arrowhead-blue" markerWidth="8" markerHeight="6" refX="0" refY="3" orient="auto">
                    <polygon points="0 0, 8 3, 0 6" fill="#2563eb" />
                </marker>
                <marker id="arrowhead-orange" markerWidth="8" markerHeight="6" refX="0" refY="3" orient="auto">
                    <polygon points="0 0, 8 3, 0 6" fill="#ea580c" />
                </marker>
                <pattern id="grid" width="10" height="10" patternUnits="userSpaceOnUse">
                    <path d="M 10 0 L 0 0 0 10" fill="none" stroke="#e2e8f0" stroke-width="0.5"/>
                </pattern>
            </defs>

            <!-- Background Zones -->
            <rect x="20" y="20" width="200" height="380" rx="10" fill="#eff6ff" stroke="#dbeafe" stroke-width="2" stroke-dasharray="5,5"/>
            <text x="120" y="390" text-anchor="middle" font-weight="bold" fill="#2563eb" font-size="12">STEP 1: ENCODING</text>
            
            <rect x="240" y="20" width="200" height="170" rx="10" fill="#fff7ed" stroke="#ffedd5" stroke-width="2" stroke-dasharray="5,5"/>
            <text x="340" y="180" text-anchor="middle" font-weight="bold" fill="#ea580c" font-size="12">STEP 2: RETRIEVAL</text>

            <rect x="240" y="210" width="540" height="190" rx="10" fill="#f0fdf4" stroke="#dcfce7" stroke-width="2" stroke-dasharray="5,5"/>
            <text x="510" y="390" text-anchor="middle" font-weight="bold" fill="#16a34a" font-size="12">STEP 3: AGGREGATION & PREDICTION</text>

            <!-- STEP 1: ENCODER -->
            <g transform="translate(60, 50)">
                <circle cx="60" cy="30" r="25" fill="white" stroke="#2563eb" stroke-width="2"/>
                <circle cx="50" cy="25" r="4" fill="#2563eb"/>
                <circle cx="70" cy="20" r="4" fill="#2563eb"/>
                <circle cx="55" cy="40" r="4" fill="#2563eb"/>
                <line x1="50" y1="25" x2="70" y2="20" stroke="#2563eb" stroke-width="1"/>
                <line x1="50" y1="25" x2="55" y2="40" stroke="#2563eb" stroke-width="1"/>
                <text x="60" y="70" text-anchor="middle" font-size="11" font-weight="bold">Query Graph (Gq)</text>
            </g>

            <line x1="120" y1="130" x2="120" y2="150" stroke="#2563eb" stroke-width="2" marker-end="url(#arrowhead-blue)"/>

            <!-- GNN Stack -->
            <g transform="translate(50, 155)">
                <rect x="0" y="0" width="140" height="28" rx="4" fill="#dbeafe" stroke="#2563eb"/>
                <text x="70" y="18" text-anchor="middle" font-size="10" fill="#1e40af">GNN Layer 1</text>
                
                <rect x="0" y="33" width="140" height="28" rx="4" fill="#dbeafe" stroke="#2563eb"/>
                <text x="70" y="51" text-anchor="middle" font-size="10" fill="#1e40af">GNN Layer 2</text>
                
                <rect x="0" y="66" width="140" height="28" rx="4" fill="#bfdbfe" stroke="#2563eb"/>
                <text x="70" y="84" text-anchor="middle" font-size="10" fill="#1e40af">Pooling / Readout</text>
            </g>

            <!-- Query Embedding Vector -->
            <g transform="translate(80, 270)">
                <rect x="0" y="0" width="80" height="80" fill="#1e40af" rx="4"/>
                <line x1="0" y1="16" x2="80" y2="16" stroke="white" stroke-width="0.5"/>
                <line x1="0" y1="32" x2="80" y2="32" stroke="white" stroke-width="0.5"/>
                <line x1="0" y1="48" x2="80" y2="48" stroke="white" stroke-width="0.5"/>
                <line x1="0" y1="64" x2="80" y2="64" stroke="white" stroke-width="0.5"/>
                <text x="40" y="100" text-anchor="middle" font-weight="bold" font-size="11">Query Emb (Zq)</text>
            </g>

            <!-- STEP 2: RETRIEVAL -->
            <path d="M160,310 L200,310 L200,100 L250,100" fill="none" stroke="#ea580c" stroke-width="2" stroke-dasharray="4,2" marker-end="url(#arrowhead-orange)"/>
            <text x="205" y="90" font-size="9" fill="#ea580c">Query (k-NN)</text>

            <!-- Database Cloud -->
            <g transform="translate(260, 45)">
                <ellipse cx="80" cy="55" rx="75" ry="45" fill="white" stroke="#ea580c" stroke-width="2"/>
                <rect x="15" y="20" width="130" height="70" fill="url(#grid)" opacity="0.5"/>
                
                <circle cx="45" cy="45" r="3" fill="#cbd5e1"/>
                <circle cx="110" cy="35" r="3" fill="#cbd5e1"/>
                <circle cx="90" cy="80" r="3" fill="#cbd5e1"/>
                
                <circle cx="75" cy="55" r="4" fill="#ea580c"/>
                <circle cx="80" cy="50" r="4" fill="#ea580c"/>
                <circle cx="85" cy="60" r="4" fill="#ea580c"/>
                <circle cx="80" cy="55" r="18" fill="none" stroke="#ea580c" stroke-width="1" stroke-dasharray="2,2"/>
                
                <text x="80" y="120" text-anchor="middle" font-size="10" font-weight="bold" fill="#9a3412">External Graph DB</text>
            </g>

            <line x1="420" y1="100" x2="490" y2="100" stroke="#ea580c" stroke-width="2" marker-end="url(#arrowhead-orange)"/>

            <!-- Retrieved Graphs Stack -->
            <g transform="translate(500, 45)">
                <rect x="0" y="0" width="95" height="75" fill="white" stroke="#ea580c" stroke-width="1" rx="5"/>
                <rect x="5" y="5" width="95" height="75" fill="white" stroke="#ea580c" stroke-width="1" rx="5"/>
                <rect x="10" y="10" width="95" height="75" fill="white" stroke="#ea580c" stroke-width="2" rx="5"/>
                
                <circle cx="40" cy="40" r="4" fill="#ea580c"/>
                <circle cx="75" cy="40" r="4" fill="#ea580c"/>
                <line x1="40" y1="40" x2="75" y2="40" stroke="#ea580c" stroke-width="1"/>
                
                <text x="55" y="105" text-anchor="middle" font-size="10" font-weight="bold" fill="#ea580c">Retrieved {Gn}</text>
            </g>

            <!-- STEP 3: AGGREGATION -->
            <path d="M160,340 L260,340" fill="none" stroke="#2563eb" stroke-width="2" marker-end="url(#arrowhead-blue)"/>
            <text x="210" y="335" font-size="9" fill="#2563eb">Query Info</text>
            
            <path d="M555,135 L555,250 L450,250" fill="none" stroke="#ea580c" stroke-width="2" marker-end="url(#arrowhead-orange)"/>
            <text x="545" y="240" text-anchor="end" font-size="9" fill="#ea580c">Knowledge Info</text>

            <!-- Fusion Module -->
            <g transform="translate(270, 280)">
                <rect x="0" y="0" width="180" height="95" rx="8" fill="white" stroke="#16a34a" stroke-width="2"/>
                
                <rect x="15" y="15" width="150" height="28" rx="4" fill="#dcfce7" stroke="#16a34a"/>
                <text x="90" y="33" text-anchor="middle" font-size="10" fill="#15803d">Cross-Attention / Concat</text>
                
                <rect x="15" y="50" width="150" height="28" rx="4" fill="#dcfce7" stroke="#16a34a"/>
                <text x="90" y="68" text-anchor="middle" font-size="10" fill="#15803d">Non-linear Transform (MLP)</text>
                
                <text x="90" y="112" text-anchor="middle" font-weight="bold" font-size="11" fill="#15803d">Fusion Module</text>
            </g>

            <line x1="450" y1="328" x2="520" y2="328" stroke="#475569" stroke-width="2" marker-end="url(#arrowhead)"/>

            <!-- Softmax -->
            <g transform="translate(525, 305)">
                <polygon points="0,5 55,25 55,45 0,25" fill="#e2e8f0" stroke="#475569" stroke-width="2"/>
                <text x="20" y="28" font-size="9" fill="#1e293b">Softmax</text>
            </g>

            <line x1="580" y1="328" x2="620" y2="328" stroke="#475569" stroke-width="2" marker-end="url(#arrowhead)"/>

            <!-- Final Prediction -->
            <g transform="translate(625, 303)">
                <circle cx="25" cy="25" r="22" fill="#1e293b"/>
                <text x="25" y="30" text-anchor="middle" fill="white" font-weight="bold" font-size="14">Y</text>
                <text x="25" y="60" text-anchor="middle" font-size="10" font-weight="bold">Prediction</text>
            </g>

            <!-- Math Annotation -->
            <text x="285" y="268" font-family="serif" font-style="italic" font-size="11" fill="#475569">Aggr(z_q, {z_n})</text>
        </svg>'''
    
    def generate_algorithm_svg(self, papers: List[str] = None) -> str:
        """
        알고리즘 순서도 SVG 생성
        
        4단계 흐름: Encoding → Index Search → Fusion → Update
        """
        return '''<svg viewBox="0 0 750 180" style="background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; width: 100%;">
            <defs>
                <marker id="flow-arrow" markerWidth="10" markerHeight="7" refX="0" refY="3.5" orient="auto">
                    <polygon points="0 0, 10 3.5, 0 7" fill="#64748b" />
                </marker>
            </defs>
            
            <!-- Step 1: Encoding -->
            <g transform="translate(25, 45)">
                <rect x="0" y="0" width="140" height="55" rx="8" fill="white" stroke="#2563eb" stroke-width="2"/>
                <text x="70" y="22" text-anchor="middle" font-weight="bold" font-size="11" fill="#2563eb">1. Encoding</text>
                <text x="70" y="40" text-anchor="middle" font-family="serif" font-size="10" fill="#334155">z_q = f_θ(G_q)</text>
            </g>

            <line x1="165" y1="73" x2="195" y2="73" stroke="#64748b" stroke-width="2" marker-end="url(#flow-arrow)"/>

            <!-- Step 2: Index Search -->
            <g transform="translate(195, 45)">
                <rect x="0" y="0" width="155" height="55" rx="8" fill="white" stroke="#ea580c" stroke-width="2"/>
                <text x="78" y="22" text-anchor="middle" font-weight="bold" font-size="11" fill="#ea580c">2. Index Search</text>
                <text x="78" y="40" text-anchor="middle" font-family="serif" font-size="10" fill="#334155">S = TopK(z_q, M)</text>
            </g>

            <line x1="350" y1="73" x2="380" y2="73" stroke="#64748b" stroke-width="2" marker-end="url(#flow-arrow)"/>

            <!-- Step 3: Fusion -->
            <g transform="translate(380, 45)">
                <rect x="0" y="0" width="155" height="55" rx="8" fill="white" stroke="#16a34a" stroke-width="2"/>
                <text x="78" y="22" text-anchor="middle" font-weight="bold" font-size="11" fill="#16a34a">3. Fusion</text>
                <text x="78" y="40" text-anchor="middle" font-family="serif" font-size="10" fill="#334155">h = Concat(z_q, S)</text>
            </g>
            
            <line x1="535" y1="73" x2="565" y2="73" stroke="#64748b" stroke-width="2" marker-end="url(#flow-arrow)"/>

            <!-- Step 4: Update -->
            <g transform="translate(565, 45)">
                <rect x="0" y="0" width="140" height="55" rx="8" fill="#1e293b" stroke="#1e293b" stroke-width="2"/>
                <text x="70" y="22" text-anchor="middle" font-weight="bold" font-size="11" fill="white">4. Update</text>
                <text x="70" y="40" text-anchor="middle" font-family="serif" font-size="10" fill="#cbd5e1">Loss = L(ŷ, y)</text>
            </g>

            <!-- Backprop Loop -->
            <path d="M635,100 L635,130 L95,130 L95,100" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="5,5" marker-end="url(#flow-arrow)"/>
            <text x="365" y="148" text-anchor="middle" font-size="10" fill="#64748b">Backpropagation (End-to-End Training)</text>
        </svg>'''
    
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
        
        list_items = "".join([f'<li class="py-1 border-b border-slate-100">✅ {item}</li>' 
                              for item in items])
        return f'<ul class="space-y-1">{list_items}</ul>'
    
    def generate_text_html(self, text: str) -> str:
        """텍스트 콘텐츠 HTML 생성"""
        if not text or not text.strip():
            return '<p class="text-gray-500">내용이 비어있습니다.</p>'
        return f'<p>{text}</p>'
    
    def generate_paper_list_html(self, papers: List[str]) -> str:
        """논문 목록 HTML 생성"""
        if not papers:
            return '<li class="text-gray-500">논문 정보 없음</li>'
        
        return "".join([f'<li class="border-l-4 border-blue-500 pl-3 py-1 mb-2">{title}</li>' 
                        for title in papers])
    
    def generate_contributions_html(self, contributions: List[str]) -> str:
        """기여 항목 HTML 생성 (번호 아이콘 포함)"""
        if not contributions:
            return '<p>기여 내용 없음</p>'
        
        items = []
        for i, contrib in enumerate(contributions):
            items.append(f'''<li class="flex items-start">
                <span class="bg-blue-600 text-white rounded-full w-5 h-5 flex items-center justify-center mr-2 mt-1 text-xs flex-shrink-0">{i+1}</span>
                <div>{contrib}</div>
            </li>''')
        
        return f'<ul class="space-y-2">{"".join(items)}</ul>'
    
    def generate_highlight_box(self, quote: str) -> str:
        """강조 박스 HTML 생성"""
        if not quote:
            return ''
        
        return f'''<div class="highlight-box">
            "{quote}"
        </div>'''
    
    def generate_keywords_html(self, keywords: List[str]) -> str:
        """키워드 배지 HTML 생성"""
        if not keywords:
            return '<p class="text-gray-500">키워드 없음</p>'
        
        badges = " ".join([f'<span class="bg-blue-100 text-blue-800 px-3 py-1 rounded-full text-sm mr-2 mb-2 inline-block">{kw}</span>' 
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
            <text x="{label_x}" y="{label_y}" text-anchor="middle" font-size="12" fill="#334155">{dimensions[i]}</text>'''
        
        svg += '\n        </svg>'
        return svg
    
    def generate_pipeline_diagram(self, steps: List[Dict[str, str]]) -> str:
        """
        Pipeline/Flowchart Diagram (LlamaDuo 스타일) SVG 생성
        
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
        
        n_steps = len(steps)
        box_width = 120
        box_height = 80
        gap = 60
        total_width = n_steps * box_width + (n_steps - 1) * gap
        start_x = 50
        y = 100
        
        svg = f'''<svg viewBox="0 0 {total_width + 100} 300" style="background: white; border-radius: 8px;">
            <defs>
                <marker id="pipelineArrow" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
                    <polygon points="0 0, 10 3.5, 0 7" fill="#64748b" />
                </marker>
            </defs>'''
        
        for i, step in enumerate(steps):
            x = start_x + i * (box_width + gap)
            
            # Box
            svg += f'''
            
            <!-- Step {i+1} -->
            <rect x="{x}" y="{y}" width="{box_width}" height="{box_height}" rx="15" 
                  fill="{self.color_palette['blue_bg']}" stroke="{self.color_palette['blue']}" stroke-width="2"/>
            <text x="{x + box_width/2}" y="{y + 35}" text-anchor="middle" font-size="14" font-weight="bold" fill="{self.color_palette['blue']}">{step.get('title', f'Step {i+1}')}</text>
            <text x="{x + box_width/2}" y="{y + 55}" text-anchor="middle" font-size="12" fill="#64748b">{step.get('desc', '')}</text>'''
            
            # Arrow to next step
            if i < n_steps - 1:
                arrow_start_x = x + box_width
                arrow_end_x = x + box_width + gap
                svg += f'''
            <line x1="{arrow_start_x}" y1="{y + box_height/2}" x2="{arrow_end_x}" y2="{y + box_height/2}" 
                  stroke="#64748b" stroke-width="2" marker-end="url(#pipelineArrow)"/>'''
        
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
            <text x="{text_x}" y="{y - 10}" text-anchor="{text_anchor}" font-size="14" font-weight="bold" fill="{color}">{event.get('year', '')}</text>
            <text x="{text_x}" y="{y + 5}" text-anchor="{text_anchor}" font-size="12" fill="#334155">{event.get('title', '')}</text>
            <text x="{text_x}" y="{y + 20}" text-anchor="{text_anchor}" font-size="11" fill="#64748b">{event.get('desc', '')[:30]}</text>'''
        
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
        scale = 200 / max_value
        
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
            <text x="{x + bar_width/2}" y="265" text-anchor="middle" font-size="12" fill="#334155">{label}</text>
            <text x="{x + bar_width/2}" y="{y - 5}" text-anchor="middle" font-size="11" fill="{color}">{value:.2f}</text>'''
        
        # Y-axis labels
        for i, val in enumerate([0, 0.25, 0.5, 0.75, 1.0]):
            y = 250 - val * 200
            svg += f'''
            <text x="45" y="{y + 5}" text-anchor="end" font-size="11" fill="#64748b">{val:.2f}</text>'''
        
        svg += '\n        </svg>'
        return svg

