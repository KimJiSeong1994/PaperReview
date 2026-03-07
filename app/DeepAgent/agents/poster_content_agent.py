"""
Poster Content Agent

리포트에서 구조화된 콘텐츠를 추출하는 에이전트
Paper2Poster의 Content Extraction 단계 구현
"""

import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class ExtractedContent:
    """추출된 콘텐츠 구조"""
    title: str
    subtitle: str
    abstract: str
    motivation: str
    contributions: List[str]
    methodology: str
    paper_titles: List[str]
    key_findings: List[str]
    comparison_data: Dict[str, Any]
    conclusion: str
    keywords: List[str]
    statistics: Dict[str, Any]
    # 시각화 요구사항
    required_visualizations: List[str]
    content_analysis: Dict[str, Any]
    # 논문 삽도 (Figure) 데이터
    figures: Optional[List[Dict[str, Any]]] = None
    # 논문별 핵심 구조 분석 데이터
    paper_analyses: Optional[List[Dict[str, Any]]] = None
    # 비교 분석 테이블 (마크다운 원문)
    comparison_tables: Optional[List[str]] = None
    # 시각화용 구조화 데이터 (파이프라인 단계, 정량 데이터, 논문별 결과)
    visualization_data: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.figures is None:
            self.figures = []
        if self.paper_analyses is None:
            self.paper_analyses = []
        if self.comparison_tables is None:
            self.comparison_tables = []
        if self.visualization_data is None:
            self.visualization_data = {}


class PosterContentAgent:
    """
    리포트에서 포스터용 콘텐츠를 추출하는 에이전트

    역할:
    - 섹션별 핵심 내용 추출
    - 키워드 및 핵심 용어 식별
    - 수치/통계 데이터 추출
    - 논문 제목 및 메타데이터 정리
    """

    def __init__(self):
        self.stopwords = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been'
        }

        # 시각화 식별을 위한 키워드 패턴
        self.viz_patterns = {
            'pipeline_diagram': ['pipeline', 'workflow', 'architecture', 'process', 'framework', '파이프라인', '워크플로우', '아키텍처', '프로세스'],
            'radar_chart': ['performance', 'comparison', 'metrics', 'evaluation', 'benchmark', '성능', '비교', '평가'],
            'timeline': ['history', 'evolution', 'development', 'progress', 'timeline', '연혁', '발전', '타임라인'],
            'bar_chart': ['results', 'scores', 'accuracy', 'rate', '결과', '점수', '정확도'],
            'table': ['comparison table', 'summary', '비교표', '요약'],
            'flowchart': ['algorithm', 'method', 'steps', 'procedure', '알고리즘', '방법', '절차']
        }

    def extract(self, report_content: str, num_papers: int = 0, figures: List[Dict] = None) -> ExtractedContent:
        """
        리포트에서 구조화된 콘텐츠 추출

        Args:
            report_content: 마크다운 형식의 리포트
            num_papers: 분석된 논문 수
            figures: 논문에서 추출한 삽도 데이터 리스트 (옵션)

        Returns:
            ExtractedContent: 구조화된 콘텐츠
        """
        lines = report_content.split('\n')

        # 각 섹션 추출 (방법론은 더 긴 한도 적용)
        title = self._extract_title(lines)
        subtitle = self._generate_subtitle(title, num_papers)
        abstract = self._extract_section(lines, ['초록', 'Abstract', '요약', 'Summary'])
        motivation = self._extract_section(lines, ['배경', '동기', 'Motivation', 'Background'])
        contributions = self._extract_list_items(lines, ['기여', 'Contribution'])
        methodology = self._extract_section(lines, ['방법론', 'Methodology', 'Method', 'Analysis'], max_length=1500)
        paper_titles = self._extract_paper_titles(lines)
        key_findings = self._extract_list_items(lines, ['핵심 발견', '주요 발견', 'Key Finding', 'Finding'])
        conclusion = self._extract_section(lines, ['결론', 'Conclusion'])
        keywords = self._extract_keywords(report_content)
        statistics = self._extract_statistics(report_content, num_papers)

        # 논문별 핵심 구조 추출
        paper_analyses = self._extract_paper_analyses(report_content)
        # 비교 분석 테이블 추출
        comparison_tables = self._extract_comparison_tables(report_content)
        # 비교 데이터 (테이블 파싱 포함)
        comparison_data = self._extract_comparison_data(lines, num_papers, comparison_tables)

        # 시각화용 구조화 데이터 추출
        quantitative_data = self._extract_quantitative_data(report_content)
        pipeline_steps = self._extract_pipeline_steps(methodology)
        paper_results = self._extract_paper_results(paper_analyses)
        parsed_tables = [self._parse_markdown_table(t) for t in comparison_tables[:3] if t]
        parsed_tables = [t for t in parsed_tables if t]  # 빈 결과 제거

        visualization_data = {
            'quantitative': quantitative_data,
            'pipeline_steps': pipeline_steps,
            'parsed_tables': parsed_tables,
            'paper_results': paper_results,
        }

        # 시각화 요구사항 식별
        required_visualizations = self.identify_visualization_needs(report_content, methodology, key_findings)
        content_analysis = self.analyze_content_characteristics(report_content, methodology, required_visualizations)

        return ExtractedContent(
            title=title,
            subtitle=subtitle,
            abstract=abstract,
            motivation=motivation,
            contributions=contributions,
            methodology=methodology,
            paper_titles=paper_titles,
            key_findings=key_findings,
            comparison_data=comparison_data,
            conclusion=conclusion,
            keywords=keywords,
            statistics=statistics,
            required_visualizations=required_visualizations,
            content_analysis=content_analysis,
            figures=figures or [],
            paper_analyses=paper_analyses,
            comparison_tables=comparison_tables,
            visualization_data=visualization_data,
        )

    def _extract_title(self, lines: List[str]) -> str:
        """제목 추출 (첫 번째 # 헤더)"""
        for line in lines[:20]:
            if line.startswith('# '):
                return line.replace('# ', '').strip()
        return "Systematic Literature Review"

    def _generate_subtitle(self, title: str, num_papers: int) -> str:
        """부제목 생성"""
        return f"체계적 문헌 고찰 및 심층 분석 ({num_papers}편 논문)"

    def _extract_section(self, lines: List[str], keywords: List[str], max_length: int = 1000) -> str:
        """특정 섹션 추출"""
        content = ""
        in_section = False

        for i, line in enumerate(lines):
            # 섹션 시작 감지
            if any(kw in line for kw in keywords) and (line.startswith('#') or line.startswith('**')):
                in_section = True
                continue

            # 섹션 종료 감지
            if in_section and (line.startswith('#') or line.startswith('---')):
                break

            # 내용 수집
            if in_section and line.strip() and not line.startswith('**'):
                content += line.strip() + " "

        # 기본값 제공
        if not content:
            if '초록' in keywords or 'Abstract' in keywords:
                content = "본 연구는 선정된 논문들을 체계적으로 분석하여 해당 분야의 연구 동향과 핵심 기여를 파악합니다."
            elif '배경' in keywords or 'Motivation' in keywords:
                content = "기존 연구의 한계를 분석하고, 새로운 접근법의 필요성을 파악하기 위해 체계적인 문헌 고찰을 수행하였습니다."
            elif '결론' in keywords or 'Conclusion' in keywords:
                content = "본 분석을 통해 해당 분야의 연구 동향을 파악하고, 향후 연구 방향에 대한 통찰을 얻었습니다."

        return content[:max_length].strip()

    def _extract_list_items(self, lines: List[str], keywords: List[str]) -> List[str]:
        """리스트 항목 추출"""
        items = []
        in_section = False

        for line in lines:
            # 섹션 시작
            if any(kw in line for kw in keywords):
                in_section = True
                continue

            # 섹션 종료
            if in_section and (line.startswith('#') or line.startswith('---')):
                break

            # 리스트 항목 수집 (•/-/* 또는 숫자+구분자로 시작)
            if in_section and re.match(r'^\s*[•\-*]\s|^\s*\d+[.)]\s', line):
                item = re.sub(r'^\s*[•\-*]+\s*|\s*\d+[.)]\s*', '', line).strip()
                if item and len(item) > 5:
                    items.append(item[:250])

        # 기본값
        if not items:
            if '기여' in keywords or 'Contribution' in keywords:
                items = [
                    "선정 논문들의 방법론적 특징 분석",
                    "연구 동향 및 패턴 식별",
                    "향후 연구 방향 도출"
                ]
            elif '발견' in keywords or 'Finding' in keywords:
                items = [
                    "방법론적 다양성 확인",
                    "공통 연구 트렌드 발견",
                    "성능 개선 패턴 식별",
                    "연구 공백 파악"
                ]

        return items[:8]

    def _extract_paper_titles(self, lines: List[str]) -> List[str]:
        """논문 제목 추출"""
        titles = []

        for line in lines:
            if line.startswith('### ') and ('논문' in line or 'Paper' in line or re.match(r'###\s+\d+\.', line)):
                title_part = line.replace('### ', '').strip()
                if ':' in title_part:
                    title_part = title_part.split(':', 1)[1].strip()
                if title_part and len(title_part) > 5 and not title_part.startswith(('논문', 'Paper')):
                    titles.append(title_part[:120])

        return titles[:8]

    def _extract_comparison_data(self, lines: List[str], num_papers: int,
                                 comparison_tables: List[str] = None) -> Dict[str, Any]:
        """비교 분석 데이터 추출 (테이블 파싱 포함)"""
        base = {
            'num_papers': num_papers,
            'num_findings': len(self._extract_list_items(lines, ['발견', 'Finding'])),
            'completion_rate': 100,
        }
        if comparison_tables:
            parsed = [self._parse_markdown_table(t) for t in comparison_tables[:3]]
            base['parsed_tables'] = [t for t in parsed if t]
        return base

    def _extract_keywords(self, content: str) -> List[str]:
        """키워드 추출 (TF 기반)"""
        # 단어 토큰화
        words = re.findall(r'\b[가-힣a-zA-Z]{3,}\b', content.lower())

        # 불용어 제거
        words = [w for w in words if w not in self.stopwords]

        # 빈도 계산
        from collections import Counter
        word_freq = Counter(words)

        # 상위 키워드 선택
        top_keywords = [word for word, _ in word_freq.most_common(10)]

        return top_keywords[:10]

    def _extract_statistics(self, content: str, num_papers: int) -> Dict[str, Any]:
        """통계 데이터 추출"""
        # 숫자 패턴 찾기
        numbers = re.findall(r'\b\d+(?:\.\d+)?%?\b', content)

        return {
            'total_papers': num_papers,
            'content_length': len(content),
            'sections_found': content.count('##'),
            'numeric_data': numbers[:5] if numbers else []
        }

    def _extract_paper_analyses(self, report_content: str) -> List[Dict[str, Any]]:
        """
        리포트에서 논문별 핵심 구조 분석 데이터 추출

        '개별 논문 심층 분석' 섹션 (보통 ## 3.)의 ### 3.N 하위 섹션에서
        각 논문의 제목, 핵심 방법론, 주요 기여, 실험 결과를 파싱
        """
        analyses = []
        lines = report_content.split('\n')

        # 먼저 '개별 논문 심층 분석' 또는 '## 3.' 섹션의 범위를 찾음
        analysis_start = -1
        analysis_end = len(lines)

        for i, line in enumerate(lines):
            if line.startswith('## ') and ('개별 논문' in line or '심층 분석' in line or '논문 분석' in line):
                analysis_start = i
                continue
            # 개별 논문 분석 섹션 이후의 다음 ## 섹션 (비교 분석 등)
            if analysis_start >= 0 and i > analysis_start and line.startswith('## '):
                analysis_end = i
                break

        # '개별 논문 심층 분석' 섹션을 못 찾으면, ### 3.1, ### 3.2 패턴으로 직접 탐색
        if analysis_start < 0:
            paper_section_pattern = re.compile(r'^###\s+3\.\d+\s+')
            for i, line in enumerate(lines):
                if paper_section_pattern.match(line):
                    analysis_start = i - 1
                    break
            if analysis_start < 0:
                return []

        current_paper = None
        current_field = None
        current_text = []

        for line in lines[analysis_start:analysis_end]:
            # 논문 섹션 헤더 감지: ### 3.1 ..., ### 3.2 ..., ### 논문 1: ...
            if line.startswith('### ') and (re.match(r'###\s+3\.\d+', line) or re.match(r'###\s+논문\s*\d+', line)):
                # 이전 논문 저장
                if current_paper and self._has_paper_data(current_paper):
                    if current_field and current_text:
                        current_paper[current_field] = ' '.join(current_text).strip()
                    analyses.append(current_paper)

                title = line.replace('###', '').strip()
                # 숫자 접두사 제거: "3.1 Title..." → "Title..."
                title = re.sub(r'^\d+\.\d+\s+', '', title)
                current_paper = {
                    'title': title[:120],
                    'methodology': '',
                    'contributions': '',
                    'results': '',
                    'strengths': '',
                    'limitations': '',
                }
                current_field = None
                current_text = []
                continue

            if current_paper is None:
                continue

            # 필드 감지 (이모지 또는 한글/영문 키워드)
            stripped = line.strip()
            new_field = self._detect_paper_field(stripped)
            if new_field:
                if current_field and current_text:
                    current_paper[current_field] = ' '.join(current_text).strip()
                current_field = new_field
                current_text = []
                continue

            # 내용 수집
            if current_field and stripped:
                current_text.append(stripped)

        # 마지막 논문 저장
        if current_paper and self._has_paper_data(current_paper):
            if current_field and current_text:
                current_paper[current_field] = ' '.join(current_text).strip()
            analyses.append(current_paper)

        return analyses

    def _detect_paper_field(self, line: str) -> Optional[str]:
        """논문 분석의 필드 타입 감지"""
        field_patterns = {
            'methodology': ['핵심 방법론', '방법론', 'Core Method', 'Methodology'],
            'contributions': ['주요 기여', 'Contribution', '핵심 기여'],
            'results': ['실험 결과', '성능', 'Result', 'Performance', 'Experiment'],
            'strengths': ['강점', 'Strength'],
            'limitations': ['한계', 'Limitation', '개선'],
        }
        for field, keywords in field_patterns.items():
            if any(kw in line for kw in keywords):
                return field
        return None

    def _has_paper_data(self, paper: Dict[str, Any]) -> bool:
        """논문 분석 데이터에 실제 내용이 있는지 확인"""
        return bool(
            paper.get('methodology') or
            paper.get('contributions') or
            paper.get('results')
        )

    def _extract_comparison_tables(self, report_content: str) -> List[str]:
        """
        리포트에서 마크다운 비교 테이블 추출

        '|' 문자로 시작하는 테이블 행을 감지하여 테이블 단위로 수집.
        연속 테이블을 구분선(| --- |) 중복 감지로 분리한다.
        """
        tables = []
        lines = report_content.split('\n')
        current_table: List[str] = []
        has_separator = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith('|') and '|' in stripped[1:]:
                # 구분선 여부 판별: 파이프와 대시/콜론/공백으로만 구성
                is_sep = bool(re.match(r'^[\s|:\-]+$', stripped))

                if is_sep and has_separator and len(current_table) >= 2:
                    # 두 번째 구분선 → 새 테이블 시작. 직전 행은 새 테이블 헤더
                    new_header = current_table.pop()
                    if len(current_table) >= 2:
                        tables.append('\n'.join(current_table))
                    current_table = [new_header, stripped]
                    has_separator = True
                else:
                    current_table.append(stripped)
                    if is_sep:
                        has_separator = True
            else:
                if current_table and len(current_table) >= 2:
                    tables.append('\n'.join(current_table))
                current_table = []
                has_separator = False

        # 마지막 테이블
        if current_table and len(current_table) >= 2:
            tables.append('\n'.join(current_table))

        return tables

    # ── 시각화 데이터 추출 메서드 ──────────────────────────────────

    def _parse_markdown_table(self, table_text: str) -> List[Dict[str, str]]:
        """마크다운 테이블을 딕셔너리 리스트로 파싱"""
        lines = [line.strip() for line in table_text.strip().split('\n') if line.strip()]
        if len(lines) < 3:  # 헤더 + 구분선 + 데이터 최소 1행
            return []
        headers = [h.strip() for h in lines[0].split('|') if h.strip()]
        if not headers:
            return []
        rows = []
        for line in lines[2:]:  # 구분선(lines[1]) 건너뜀
            values = [v.strip() for v in line.split('|') if v.strip()]
            if len(values) == len(headers):
                rows.append(dict(zip(headers, values)))
        return rows

    def _extract_pipeline_steps(self, methodology: str) -> List[Dict[str, str]]:
        """
        방법론 텍스트에서 파이프라인/알고리즘 단계 추출.

        전략 1: 화살표(→, ->) 분리
        전략 2: 번호 매기기 (1. ..., 2. ...)
        전략 3: 볼드 키워드 (**단계명**)
        """
        if not methodology:
            return []

        steps = []

        # 전략 1: 화살표 분리
        text = methodology.replace('->', '→')
        if '→' in text:
            parts = [p.strip() for p in text.split('→') if p.strip()]
            for part in parts[:8]:
                clean = re.sub(r'\*\*|\*|`', '', part).split('\n')[0].strip()
                if clean and len(clean) > 2:
                    steps.append({'title': clean[:40], 'desc': ''})

        # 전략 2: 번호 매기기 (숫자+구분자로 분할)
        if not steps:
            parts = re.split(r'\d+[.)]\s*\*?\*?', methodology)
            for part in parts[1:8]:  # 첫 빈 문자열 건너뜀
                clean = re.sub(r'\*\*|\*|`', '', part).split('\n')[0].strip()
                if clean and len(clean) > 1:
                    steps.append({'title': clean[:40], 'desc': ''})

        # 전략 3: 볼드 키워드
        if not steps:
            skip_keywords = {'결과', 'result', '한계', 'limit', '배경', 'background',
                             '결론', 'conclusion', '요약', 'summary'}
            bold = re.findall(r'\*\*([^*]{3,50})\*\*', methodology)
            for b in bold[:8]:
                if not any(skip in b.lower() for skip in skip_keywords):
                    steps.append({'title': b.strip()[:40], 'desc': ''})

        return steps

    def _extract_quantitative_data(self, report_content: str) -> Dict[str, Any]:
        """
        리포트에서 정량적 데이터 추출 (차트 생성용).

        Returns:
            Dict with 'metrics' (메트릭-값 쌍)와 'improvements' (개선 수치)
        """
        metric_keywords = {
            'accuracy', 'precision', 'recall', 'f1', 'bleu', 'rouge', 'score',
            'rate', 'loss', 'auc', 'map', 'ndcg', 'perplexity', 'throughput',
            '정확도', '정밀도', '재현율', '성능', '점수', '속도',
        }

        # 메트릭-값 쌍 추출 (구분자 필수): "accuracy: 95.3%", "F1= 0.87" 등
        metrics = []
        for match in re.finditer(
            r'([\w가-힣\-@]+(?:[ \t]+[\w가-힣\-@]+)?)\s*[:=]\s*(\d+(?:\.\d+)?)\s*(%)?',
            report_content
        ):
            name, value, unit = match.group(1), match.group(2), match.group(3) or ''
            if any(kw in name.lower() for kw in metric_keywords):
                metrics.append({
                    'name': name.strip()[:30],
                    'value': float(value),
                    'unit': unit,
                })
        # 중복 제거 (이름 기준)
        seen_names = set()
        unique_metrics = []
        for m in metrics:
            key = m['name'].lower()
            if key not in seen_names:
                seen_names.add(key)
                unique_metrics.append(m)

        # 개선 수치 추출: "72% 시간 단축", "30% 감소", "1.5배 향상" 등
        improvements = []
        imp_patterns = [
            r'(\d+(?:\.\d+)?)\s*(%|배)\s*([\w가-힣]+(?:\s+[\w가-힣]+)?)',
            r'([\w가-힣]+)\s+대비\s+(\d+(?:\.\d+)?)\s*(%|배)',
        ]
        for pattern in imp_patterns:
            for match in re.finditer(pattern, report_content):
                groups = match.groups()
                raw_val = groups[0] if groups[0].replace('.', '').isdigit() else groups[1]
                try:
                    float_val = float(raw_val)
                except (ValueError, TypeError):
                    continue
                improvements.append({
                    'description': match.group(0)[:60],
                    'value': float_val,
                })

        return {
            'metrics': unique_metrics[:15],
            'improvements': improvements[:10],
        }

    def _extract_paper_results(self, paper_analyses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """논문별 수치 결과를 구조화하여 차트 생성용 데이터로 변환"""
        results = []
        for paper in paper_analyses:
            result_text = paper.get('results', '')
            if not result_text:
                continue

            metrics = []
            seen_values = set()

            # 패턴 A: 메트릭명 + 구분자 + 값: "accuracy: 0.95", "HR@10: 0.68"
            for match in re.finditer(
                r'([\w가-힣\-@]+)\s*[:=]\s*(\d+(?:\.\d+)?)\s*(%)?',
                result_text
            ):
                name, value_str, unit = match.group(1), match.group(2), match.group(3) or ''
                val_key = f"{name}:{value_str}"
                if val_key not in seen_values:
                    seen_values.add(val_key)
                    metrics.append({
                        'name': name.strip()[:30],
                        'value': float(value_str),
                        'unit': unit,
                    })

            # 패턴 B: 숫자 + 단위(% 또는 배) + 컨텍스트: "72% 시간 단축", "1.5배 향상"
            for match in re.finditer(
                r'(\d+(?:\.\d+)?)\s*(%|배)\s+([\w가-힣]{2,})',
                result_text
            ):
                value_str, unit, context = match.group(1), match.group(2), match.group(3)
                val_key = f"{context}:{value_str}"
                if val_key not in seen_values:
                    seen_values.add(val_key)
                    metrics.append({
                        'name': context.strip()[:30],
                        'value': float(value_str),
                        'unit': unit,
                    })

            if metrics:
                results.append({
                    'paper_title': paper.get('title', '')[:60],
                    'metrics': metrics[:5],
                })

        return results

    def identify_visualization_needs(self, content: str, methodology: str, findings: List[str]) -> List[str]:
        """
        콘텐츠 분석 기반 필요한 시각화 타입 식별

        Args:
            content: 전체 리포트 내용
            methodology: 방법론 섹션
            findings: 주요 발견 리스트

        Returns:
            List of visualization types needed
        """
        visualizations = []
        content_lower = content.lower()

        # Pipeline/Architecture Diagram 필요 여부
        if any(keyword in content_lower or keyword in methodology.lower()
               for keyword in self.viz_patterns['pipeline_diagram']):
            visualizations.append('pipeline_diagram')

        # Radar Chart 필요 여부 (성능 비교가 있을 때)
        if any(keyword in content_lower
               for keyword in self.viz_patterns['radar_chart']):
            # 숫자 데이터가 있으면 radar chart 추천
            if re.search(r'\d+\.\d+|\d+%', content):
                visualizations.append('radar_chart')

        # Timeline 필요 여부 (역사/발전 과정이 있을 때)
        if any(keyword in content_lower
               for keyword in self.viz_patterns['timeline']):
            visualizations.append('timeline')

        # Bar Chart 필요 여부 (결과 데이터가 있을 때)
        findings_text = ' '.join(findings).lower()
        if any(keyword in findings_text or keyword in content_lower
               for keyword in self.viz_patterns['bar_chart']):
            if 'radar_chart' not in visualizations:  # Radar chart가 없으면 bar chart
                visualizations.append('bar_chart')

        # Flowchart 필요 여부 (알고리즘 설명이 있을 때)
        if any(keyword in methodology.lower()
               for keyword in self.viz_patterns['flowchart']):
            if 'pipeline_diagram' not in visualizations:
                visualizations.append('flowchart')

        # Table 필요 여부 (비교 분석이 있을 때)
        if 'comparison' in content_lower or '비교' in content:
            visualizations.append('table')

        # 기본값: 최소한 하나의 시각화는 필요
        if not visualizations:
            visualizations.append('bar_chart')

        return visualizations

    def analyze_content_characteristics(self, content: str, methodology: str, visualizations: List[str]) -> Dict[str, Any]:
        """
        콘텐츠 특성 분석 (레이아웃 패턴 선택에 사용)

        Args:
            content: 전체 리포트 내용
            methodology: 방법론 섹션
            visualizations: 필요한 시각화 리스트

        Returns:
            Content analysis dictionary
        """
        # 텍스트 vs 시각화 비율 추정
        word_count = len(content.split())
        viz_count = len(visualizations)

        # 콘텐츠 밸런스 결정
        if viz_count >= 3:
            content_balance = 'visual_heavy'
        elif viz_count <= 1 and word_count > 3000:
            content_balance = 'text_heavy'
        else:
            content_balance = 'balanced'

        # 섹션 수 계산
        num_sections = content.count('##')

        return {
            'has_pipeline': 'pipeline_diagram' in visualizations or 'flowchart' in visualizations,
            'has_performance_metrics': 'radar_chart' in visualizations or 'bar_chart' in visualizations,
            'has_timeline': 'timeline' in visualizations,
            'content_balance': content_balance,
            'num_sections': num_sections,
            'word_count': word_count,
            'viz_count': viz_count,
            'has_methodology_detail': len(methodology) > 300
        }

