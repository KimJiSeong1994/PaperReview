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
    
    def extract(self, report_content: str, num_papers: int = 0) -> ExtractedContent:
        """
        리포트에서 구조화된 콘텐츠 추출
        
        Args:
            report_content: 마크다운 형식의 리포트
            num_papers: 분석된 논문 수
            
        Returns:
            ExtractedContent: 구조화된 콘텐츠
        """
        lines = report_content.split('\n')
        
        # 각 섹션 추출
        title = self._extract_title(lines)
        subtitle = self._generate_subtitle(title, num_papers)
        abstract = self._extract_section(lines, ['초록', 'Abstract', '요약', 'Summary'])
        motivation = self._extract_section(lines, ['배경', '동기', 'Motivation', 'Background'])
        contributions = self._extract_list_items(lines, ['기여', 'Contribution'])
        methodology = self._extract_section(lines, ['방법론', 'Method', '분석', 'Analysis'])
        paper_titles = self._extract_paper_titles(lines)
        key_findings = self._extract_list_items(lines, ['핵심 발견', '주요 발견', 'Key Finding', 'Finding'])
        comparison_data = self._extract_comparison_data(lines, num_papers)
        conclusion = self._extract_section(lines, ['결론', 'Conclusion'])
        keywords = self._extract_keywords(report_content)
        statistics = self._extract_statistics(report_content, num_papers)
        
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
            statistics=statistics
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
    
    def _extract_section(self, lines: List[str], keywords: List[str]) -> str:
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
        
        return content[:600].strip()
    
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
            
            # 리스트 항목 수집
            if in_section and line.strip().startswith(('•', '-', '*', '✅', '1.', '2.', '3.')):
                item = line.strip().lstrip('•-*✅123456789.').strip()
                if item and len(item) > 5:
                    items.append(item[:150])
        
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
        
        return items[:6]
    
    def _extract_paper_titles(self, lines: List[str]) -> List[str]:
        """논문 제목 추출"""
        titles = []
        
        for line in lines:
            if line.startswith('### ') and ('논문' in line or 'Paper' in line or re.match(r'###\s+\d+\.', line)):
                title_part = line.replace('### ', '').strip()
                if ':' in title_part:
                    title_part = title_part.split(':', 1)[1].strip()
                if title_part and len(title_part) > 5 and not title_part.startswith(('논문', 'Paper')):
                    titles.append(title_part[:60])
        
        return titles[:6]
    
    def _extract_comparison_data(self, lines: List[str], num_papers: int) -> Dict[str, Any]:
        """비교 분석 데이터 추출"""
        return {
            'num_papers': num_papers,
            'num_findings': len(self._extract_list_items(lines, ['발견', 'Finding'])),
            'completion_rate': 100
        }
    
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
        
        return top_keywords[:7]
    
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

