"""
학회 포스터 생성 Agent

Google Gemini를 사용하여 심층 연구 리포트를 학회 포스터로 시각화
HTML/SVG 기반의 전문적인 학술 포스터 생성
"""

import os
from pathlib import Path
from datetime import datetime
from typing import Optional


class PosterGenerationAgent:
    """
    학회 포스터 생성을 담당하는 Agent
    
    특징:
    - Google Gemini 3 Pro (Preview) 모델 사용
    - HTML/SVG 기반 시각화
    - 3단 그리드 레이아웃
    - 반응형 디자인
    
    참고: https://ai.google.dev/gemini-api/docs/gemini-3
    """
    
    def __init__(self, model: str = "gemini-3-pro-preview", api_key: Optional[str] = None):
        """
        Args:
            model: Gemini 모델 이름
            api_key: Google API 키 (없으면 환경변수에서 로드)
        """
        self.model = model
        self.api_key = api_key or os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')
        self.llm = None
        
        if self.api_key:
            self._initialize_llm()
    
    def _initialize_llm(self):
        """Gemini LLM 초기화 (google-generativeai 직접 사용)"""
        try:
            import google.generativeai as genai
            
            genai.configure(api_key=self.api_key)
            self.llm = genai.GenerativeModel(self.model)
            print(f"🎨 Poster Agent initialized with {self.model}")
        except Exception as e:
            print(f"⚠️ Failed to initialize Gemini: {e}")
            self.llm = None
    
    def generate_poster(self, report_content: str, num_papers: int = 0, output_dir: Optional[Path] = None) -> dict:
        """
        심층 연구 리포트를 학회 포스터로 변환
        
        Args:
            report_content: 마크다운 형식의 리포트 내용
            num_papers: 분석된 논문 수
            output_dir: 포스터 저장 디렉토리 (선택)
            
        Returns:
            dict: {
                "success": bool,
                "poster_html": str,
                "poster_path": str (저장된 경우)
            }
        """
        print("🎨 Poster Agent: 학회 포스터 생성 시작...")
        
        if not self.llm:
            print("⚠️ Gemini LLM not available, using fallback template")
            poster_html = self._generate_fallback_poster(report_content, num_papers)
        else:
            poster_html = self._generate_with_gemini(report_content, num_papers)
        
        result = {
            "success": True,
            "poster_html": poster_html,
            "poster_path": None
        }
        
        # 저장 디렉토리가 지정된 경우 파일 저장
        if output_dir:
            result["poster_path"] = self._save_poster(poster_html, output_dir)
        
        print(f"✅ Poster Agent: 포스터 생성 완료 ({len(poster_html)} chars)")
        return result
    
    def _generate_with_gemini(self, report_content: str, num_papers: int) -> str:
        """Gemini를 사용한 포스터 생성 (google-generativeai 직접 사용)"""
        
        # 리포트 요약 (토큰 제한)
        report_summary = report_content[:8000]
        
        prompt = self._build_prompt(report_summary, num_papers)
        
        try:
            print("🤖 Gemini로 포스터 생성 중...")
            response = self.llm.generate_content(prompt)
            poster_html = response.text
            
            # HTML 코드만 추출 (마크다운 코드 블록 제거)
            if "```html" in poster_html:
                poster_html = poster_html.split("```html")[1].split("```")[0]
            elif "```" in poster_html:
                parts = poster_html.split("```")
                if len(parts) > 1:
                    poster_html = parts[1]
            
            poster_html = poster_html.strip()
            
            # HTML 형식 검증 및 보완
            if not poster_html.startswith("<!DOCTYPE") and not poster_html.startswith("<html"):
                poster_html = f"<!DOCTYPE html>\n<html lang='ko'>\n{poster_html}\n</html>"
            
            return poster_html
            
        except Exception as e:
            print(f"⚠️ Gemini 포스터 생성 실패: {e}")
            return self._generate_fallback_poster(report_content, num_papers)
    
    def _build_prompt(self, report_summary: str, num_papers: int) -> str:
        """
        포스터 생성 프롬프트 구성 (Paper2Poster 스타일 고도화)
        
        참조: https://github.com/Paper2Poster/Paper2Poster
        - Top-down, visual-in-the-loop 멀티 에이전트 시스템 접근법 적용
        - 구조화된 섹션 추출 → 레이아웃 결정 → 시각화 생성 → 최종 조합
        """
        
        return f"""# 🎓 학술 포스터 생성 태스크 (Paper2Poster Inspired)

당신은 NeurIPS 수준의 학술 포스터를 생성하는 전문 AI 시스템입니다.
Paper2Poster 프레임워크의 접근 방식을 따라, 체계적인 단계별 프로세스로 포스터를 생성합니다.

---

## 🔄 생성 파이프라인 (Multi-Agent Approach)

### Phase 1: Content Extraction (콘텐츠 추출)
리포트에서 다음 요소를 정확히 추출하세요:
- **Title**: 메인 제목 (첫 번째 # 헤더)
- **Abstract**: 연구 요약 (300-500자)
- **Motivation**: 연구 배경 및 문제 정의
- **Contributions**: 핵심 기여점 (3-5개)
- **Methodology**: 분석 방법론/프레임워크
- **Key Findings**: 주요 발견 (4-6개)
- **Conclusion**: 결론 및 시사점

### Phase 2: Layout Planning (레이아웃 설계)
- 3단 그리드 레이아웃 (1:2:1 비율)
- 정보 위계: 제목 → 핵심 내용 → 세부 사항
- 시각적 균형: SVG 다이어그램 중앙 배치

### Phase 3: Visual Generation (시각화 생성)
- Figure 1: 모델 아키텍처 SVG (상세)
- Figure 2: 알고리즘 흐름도 SVG
- 비교 테이블/차트

### Phase 4: Final Assembly (최종 조합)
- HTML/CSS 통합
- 스타일 일관성 검증
- 가독성 최적화

---

## 📊 입력 데이터

**분석 논문 수**: {num_papers}편

### 연구 리포트 내용:
{report_summary}

---

## 🎯 태스크 수행 단계

### STEP 1: 리포트에서 다음 정보 추출
- 제목 (첫 번째 # 헤더에서)
- 초록/요약 섹션
- 연구 배경/동기
- 핵심 기여점 (bullet points)
- 분석한 논문 제목들
- 주요 발견사항
- 결론

### STEP 2: 아래 HTML 구조에 추출한 내용 삽입
### STEP 3: SVG 다이어그램 2개 직접 작성 (중요!)

---

## 🏗️ 정확히 따라야 할 HTML 구조

```html
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>학술 포스터</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        :root {{ --primary: #2563eb; --secondary: #1e293b; --accent: #f59e0b; }}
        body {{ font-family: 'Inter', 'Noto Sans KR', sans-serif; background: #e2e8f0; margin: 0; padding: 20px; min-width: 1600px; }}
        .poster {{ max-width: 2200px; margin: 0 auto; background: #f8fafc; padding: 40px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); aspect-ratio: 20/9; display: flex; flex-direction: column; }}
        header {{ display: flex; justify-content: space-between; border-bottom: 4px solid var(--primary); padding-bottom: 20px; margin-bottom: 25px; }}
        h1 {{ font-size: 2.5rem; font-weight: 900; color: var(--primary); margin: 0; }}
        h2 {{ font-size: 1.3rem; color: var(--secondary); margin: 8px 0 0; }}
        .grid {{ display: grid; grid-template-columns: 1fr 2fr 1fr; gap: 20px; flex: 1; }}
        .col {{ display: flex; flex-direction: column; gap: 15px; }}
        .box {{ background: white; border-radius: 12px; padding: 16px; border: 1px solid #e2e8f0; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        .box-title {{ font-size: 1.1rem; font-weight: 800; color: var(--primary); border-bottom: 2px solid #cbd5e1; padding-bottom: 6px; margin-bottom: 10px; }}
        .box-content {{ font-size: 0.9rem; line-height: 1.5; color: #334155; }}
        .highlight {{ background: #eff6ff; border-left: 3px solid var(--primary); padding: 10px; margin: 8px 0; font-style: italic; }}
        footer {{ margin-top: 15px; padding-top: 10px; border-top: 2px solid #e2e8f0; text-align: center; color: #64748b; font-size: 0.8rem; }}
    </style>
</head>
<body>
<div class="poster">
    <header>
        <div>
            <h1>[리포트 제목을 여기에]</h1>
            <h2>[한글 부제목]</h2>
            <div style="color:#475569; margin-top:8px;">Systematic Literature Review | {num_papers} Papers</div>
        </div>
        <div style="text-align:right;">
            <div style="font-weight:700; color:var(--primary); font-size:1.2rem;">AI Research Analysis</div>
            <div>[오늘 날짜]</div>
        </div>
    </header>
    
    <div class="grid">
        <!-- 왼쪽 컬럼: 초록, 배경, 기여 -->
        <div class="col">
            <div class="box">
                <div class="box-title">📋 1. 초록 (Abstract)</div>
                <div class="box-content">[리포트 초록 내용 - 실제 내용으로]</div>
            </div>
            <div class="box">
                <div class="box-title">🎯 2. 연구 배경 (Motivation)</div>
                <div class="box-content">
                    <ul style="padding-left:18px; margin:0;">
                        <li>[배경 포인트 1]</li>
                        <li>[배경 포인트 2]</li>
                    </ul>
                    <div class="highlight">"[핵심 인용구]"</div>
                </div>
            </div>
            <div class="box">
                <div class="box-title">⭐ 3. 핵심 기여 (Contributions)</div>
                <div class="box-content">
                    <ol style="padding-left:18px; margin:0;">
                        <li>[기여 1]</li>
                        <li>[기여 2]</li>
                        <li>[기여 3]</li>
                    </ol>
                </div>
            </div>
        </div>
        
        <!-- 중앙 컬럼: 아키텍처 SVG + 알고리즘 SVG -->
        <div class="col">
            <div class="box" style="flex:2;">
                <div class="box-title">🔬 4. 모델 아키텍처 (Architecture)</div>
                <div class="box-content">
                    <p style="margin-bottom:10px;">[아키텍처 설명 한 줄]</p>
                    <!-- 아키텍처 SVG: 아래 예시 참고하여 작성 -->
                    <svg viewBox="0 0 800 350" style="width:100%; background:#f8fafc; border-radius:8px; border:1px solid #e2e8f0;">
                        <!-- SVG 내용은 아래 예시 참고 -->
                    </svg>
                </div>
            </div>
            <div class="box" style="flex:1;">
                <div class="box-title">📊 5. 알고리즘 흐름 (Algorithm)</div>
                <div class="box-content">
                    <!-- 알고리즘 순서도 SVG -->
                    <svg viewBox="0 0 700 140" style="width:100%; background:#f8fafc; border-radius:8px;">
                        <!-- SVG 내용 -->
                    </svg>
                </div>
            </div>
        </div>
        
        <!-- 오른쪽 컬럼: 발견, 비교, 결론 -->
        <div class="col">
            <div class="box">
                <div class="box-title">💡 6. 핵심 발견 (Key Findings)</div>
                <div class="box-content">
                    <ul style="padding-left:18px; margin:0;">
                        <li>✅ [발견 1]</li>
                        <li>✅ [발견 2]</li>
                        <li>✅ [발견 3]</li>
                    </ul>
                </div>
            </div>
            <div class="box">
                <div class="box-title">📈 7. 비교 분석</div>
                <div class="box-content">
                    <table style="width:100%; font-size:0.85rem; border-collapse:collapse;">
                        <tr style="border-bottom:2px solid #cbd5e1;"><th style="text-align:left; padding:5px;">항목</th><th style="text-align:center; padding:5px;">결과</th></tr>
                        <tr style="border-bottom:1px solid #e2e8f0;"><td style="padding:5px;">분석 논문</td><td style="text-align:center; color:#2563eb; font-weight:bold;">{num_papers}편</td></tr>
                        <tr style="border-bottom:1px solid #e2e8f0;"><td style="padding:5px;">주요 발견</td><td style="text-align:center; color:#16a34a; font-weight:bold;">[N]건</td></tr>
                    </table>
                </div>
            </div>
            <div class="box">
                <div class="box-title">🎯 8. 결론 (Conclusion)</div>
                <div class="box-content">[리포트 결론 내용]</div>
            </div>
        </div>
    </div>
    
    <footer>🤖 AI 기반 심층 연구 분석 시스템 | Generated: [날짜]</footer>
</div>
</body>
</html>
```

---

## 🎨 SVG 다이어그램 필수 요소 (직접 작성!)

### Figure 1: 모델 아키텍처 SVG (viewBox="0 0 800 350")

**필수 요소:**
```svg
<defs>
    <marker id="arrow" markerWidth="8" markerHeight="6" refX="0" refY="3" orient="auto">
        <polygon points="0 0, 8 3, 0 6" fill="#475569"/>
    </marker>
</defs>

<!-- STEP 1: ENCODING 영역 (파란색 #eff6ff) -->
<rect x="20" y="20" width="200" height="300" rx="10" fill="#eff6ff" stroke="#dbeafe" stroke-width="2" stroke-dasharray="5,5"/>
<text x="120" y="310" text-anchor="middle" font-weight="bold" fill="#2563eb" font-size="11">STEP 1: ENCODING</text>

<!-- Query Graph 아이콘 -->
<circle cx="120" cy="60" r="25" fill="white" stroke="#2563eb" stroke-width="2"/>
<circle cx="110" cy="55" r="4" fill="#2563eb"/>
<circle cx="130" cy="55" r="4" fill="#2563eb"/>
<circle cx="120" cy="70" r="4" fill="#2563eb"/>
<text x="120" y="100" text-anchor="middle" font-size="10" font-weight="bold">Query Graph (Gq)</text>

<!-- GNN Layer Stack -->
<rect x="50" y="120" width="140" height="25" rx="4" fill="#dbeafe" stroke="#2563eb"/>
<text x="120" y="137" text-anchor="middle" font-size="9">GNN Layer 1</text>
<rect x="50" y="150" width="140" height="25" rx="4" fill="#dbeafe" stroke="#2563eb"/>
<text x="120" y="167" text-anchor="middle" font-size="9">GNN Layer 2</text>
<rect x="50" y="180" width="140" height="25" rx="4" fill="#bfdbfe" stroke="#2563eb"/>
<text x="120" y="197" text-anchor="middle" font-size="9">Pooling/Readout</text>

<!-- Query Embedding 벡터 -->
<rect x="80" y="220" width="80" height="60" fill="#1e40af" rx="4"/>
<text x="120" y="295" text-anchor="middle" font-size="10" font-weight="bold">Query Emb (Zq)</text>

<!-- STEP 2: RETRIEVAL 영역 (주황색 #fff7ed) -->
<rect x="240" y="20" width="200" height="140" rx="10" fill="#fff7ed" stroke="#ffedd5" stroke-width="2" stroke-dasharray="5,5"/>
<text x="340" y="150" text-anchor="middle" font-weight="bold" fill="#ea580c" font-size="11">STEP 2: RETRIEVAL</text>

<!-- External DB -->
<ellipse cx="340" cy="80" rx="70" ry="40" fill="white" stroke="#ea580c" stroke-width="2"/>
<text x="340" y="85" text-anchor="middle" font-size="10">External Graph DB</text>

<!-- STEP 3: AGGREGATION 영역 (초록색 #f0fdf4) -->
<rect x="240" y="180" width="540" height="140" rx="10" fill="#f0fdf4" stroke="#dcfce7" stroke-width="2" stroke-dasharray="5,5"/>
<text x="510" y="310" text-anchor="middle" font-weight="bold" fill="#16a34a" font-size="11">STEP 3: AGGREGATION & PREDICTION</text>

<!-- Fusion Module -->
<rect x="280" y="210" width="180" height="80" rx="8" fill="white" stroke="#16a34a" stroke-width="2"/>
<rect x="295" y="225" width="150" height="22" rx="4" fill="#dcfce7" stroke="#16a34a"/>
<text x="370" y="240" text-anchor="middle" font-size="9">Cross-Attention / Concat</text>
<rect x="295" y="252" width="150" height="22" rx="4" fill="#dcfce7" stroke="#16a34a"/>
<text x="370" y="267" text-anchor="middle" font-size="9">Non-linear Transform (MLP)</text>

<!-- Softmax & Prediction -->
<polygon points="520,230 570,250 570,270 520,290" fill="#e2e8f0" stroke="#475569" stroke-width="2"/>
<text x="545" y="265" text-anchor="middle" font-size="8">Softmax</text>
<circle cx="620" cy="260" r="25" fill="#1e293b"/>
<text x="620" y="265" text-anchor="middle" fill="white" font-weight="bold" font-size="14">Y</text>

<!-- 화살표 연결 (marker-end="url(#arrow)") -->
<line x1="160" y1="250" x2="280" y2="250" stroke="#2563eb" stroke-width="2" marker-end="url(#arrow)"/>
<line x1="460" y1="250" x2="520" y2="250" stroke="#475569" stroke-width="2" marker-end="url(#arrow)"/>
<line x1="570" y1="260" x2="595" y2="260" stroke="#475569" stroke-width="2" marker-end="url(#arrow)"/>
```

### Figure 2: 알고리즘 순서도 SVG (viewBox="0 0 700 140")

```svg
<!-- Step 박스들 -->
<rect x="20" y="40" width="130" height="50" rx="8" fill="white" stroke="#2563eb" stroke-width="2"/>
<text x="85" y="60" text-anchor="middle" font-weight="bold" fill="#2563eb" font-size="10">1. Encoding</text>
<text x="85" y="78" text-anchor="middle" font-size="9">z_q = f_θ(G_q)</text>

<rect x="180" y="40" width="140" height="50" rx="8" fill="white" stroke="#ea580c" stroke-width="2"/>
<text x="250" y="60" text-anchor="middle" font-weight="bold" fill="#ea580c" font-size="10">2. Index Search</text>
<text x="250" y="78" text-anchor="middle" font-size="9">S = TopK(z_q, M)</text>

<rect x="350" y="40" width="130" height="50" rx="8" fill="white" stroke="#16a34a" stroke-width="2"/>
<text x="415" y="60" text-anchor="middle" font-weight="bold" fill="#16a34a" font-size="10">3. Fusion</text>
<text x="415" y="78" text-anchor="middle" font-size="9">h = Concat(z_q, S)</text>

<rect x="510" y="40" width="130" height="50" rx="8" fill="#1e293b"/>
<text x="575" y="60" text-anchor="middle" font-weight="bold" fill="white" font-size="10">4. Update</text>
<text x="575" y="78" text-anchor="middle" fill="#cbd5e1" font-size="9">Loss = L(ŷ, y)</text>

<!-- 화살표 -->
<line x1="150" y1="65" x2="180" y2="65" stroke="#475569" stroke-width="2" marker-end="url(#arrow)"/>
<line x1="320" y1="65" x2="350" y2="65" stroke="#475569" stroke-width="2" marker-end="url(#arrow)"/>
<line x1="480" y1="65" x2="510" y2="65" stroke="#475569" stroke-width="2" marker-end="url(#arrow)"/>

<!-- Backprop 루프 -->
<path d="M575,90 L575,110 L85,110 L85,90" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="5,5" marker-end="url(#arrow)"/>
<text x="330" y="125" text-anchor="middle" fill="#64748b" font-size="9">Backpropagation (End-to-End)</text>
```

---

## ✅ 품질 체크리스트 (Paper2Poster Quality Criteria)

### 1. 콘텐츠 품질 (Content Quality)
- [ ] 리포트의 **실제 내용**이 정확히 반영됨
- [ ] 모든 섹션에 **구체적인 정보** 포함 (플레이스홀더 금지)
- [ ] 학술적 톤과 전문 용어 사용
- [ ] 논리적 흐름과 연결성 유지

### 2. 시각적 품질 (Visual Quality)
- [ ] SVG 다이어그램이 **상세하고 전문적**임
- [ ] 색상 테마 일관성 (파란색/주황색/초록색)
- [ ] 정보 위계가 시각적으로 명확함
- [ ] 여백과 간격이 적절함

### 3. 기술적 품질 (Technical Quality)
- [ ] 완전한 HTML 문서 (<!DOCTYPE html>)
- [ ] 모든 CSS가 <style> 태그 내에 포함
- [ ] SVG가 직접 인라인으로 작성됨
- [ ] 외부 의존성 최소화 (Tailwind CDN만 사용)

### 4. 학술 포스터 표준 (Academic Poster Standards)
- [ ] 제목이 명확하고 눈에 띔
- [ ] 저자/소속 정보 포함
- [ ] 섹션 번호와 라벨 일관성
- [ ] 결론이 명확한 takeaway 제공

---

## 🎨 디자인 원칙 (Design Principles)

### 색상 팔레트
```
Primary (Academic Blue): #2563eb, #dbeafe, #eff6ff
Secondary (Dark Slate): #1e293b, #334155, #475569
Accent Orange: #ea580c, #fff7ed, #ffedd5
Accent Green: #16a34a, #dcfce7, #f0fdf4
Background: #f8fafc, #e2e8f0
```

### 타이포그래피
```
제목: font-weight: 900, font-size: 2.5-3rem
섹션 제목: font-weight: 800, font-size: 1.1-1.3rem
본문: font-weight: 400, font-size: 0.9-0.95rem
캡션: font-weight: 400, font-size: 0.8rem
```

### 레이아웃
```
포스터 비율: 20:9 (가로형)
그리드: 3단 (1fr 2fr 1fr)
간격: 20-25px
패딩: 16-20px (섹션 박스)
```

---

## ⚠️ 절대 규칙

1. **HTML 코드만 출력** - 설명, 마크다운, 코드 블록 없이 순수 HTML만
2. **모든 텍스트는 한글로** - 영어 제목/학술 용어는 그대로 유지
3. **리포트의 실제 내용 반영** - 일반적인 플레이스홀더 절대 금지
4. **SVG 직접 작성** - 외부 이미지 URL 사용 금지
5. **즉시 실행 가능** - 복사해서 브라우저에서 바로 열릴 것
6. **<!DOCTYPE html>로 시작** - 완전한 HTML 문서

---

## 🚀 생성 지침

1. 먼저 리포트에서 각 섹션의 내용을 추출하세요
2. 추출한 내용으로 HTML 템플릿의 각 부분을 채우세요
3. SVG 다이어그램 2개를 상세하게 작성하세요
4. 최종 HTML이 완전하고 실행 가능한지 확인하세요

**지금 바로 완전한 HTML 포스터 코드를 출력하세요. 오직 HTML만!**"""
    
    def _generate_fallback_poster(self, report_content: str, num_papers: int) -> str:
        """Gemini 실패 시 사용하는 기본 포스터 템플릿 - Ragraph 스타일 적용"""
        import re
        
        # 리포트에서 주요 섹션 추출
        lines = report_content.split('\n')
        
        # 제목 추출
        title = "Systematic Literature Review"
        subtitle = "체계적 문헌 고찰 및 심층 분석"
        for line in lines[:15]:
            if line.startswith('# '):
                title = line.replace('# ', '').strip()
                break
        
        # 초록/요약 추출
        abstract = ""
        in_abstract = False
        for i, line in enumerate(lines):
            if '초록' in line or 'Abstract' in line or '요약' in line:
                in_abstract = True
                continue
            if in_abstract:
                if line.startswith('#') or line.startswith('---'):
                    break
                if line.strip() and not line.startswith('**'):
                    abstract += line.strip() + " "
        abstract = abstract[:600] if abstract else "본 연구는 선정된 논문들을 체계적으로 분석하여 해당 분야의 연구 동향과 핵심 기여를 파악합니다. 각 논문의 방법론, 실험 결과, 기여점을 종합적으로 검토하였습니다."
        
        # 연구 배경 추출
        motivation = ""
        in_motivation = False
        for line in lines:
            if '배경' in line or '동기' in line or 'Motivation' in line:
                in_motivation = True
                continue
            if in_motivation:
                if line.startswith('#') or line.startswith('---'):
                    break
                if line.strip() and not line.startswith('**'):
                    motivation += line.strip() + " "
        motivation = motivation[:400] if motivation else "기존 연구의 한계를 분석하고, 새로운 접근법의 필요성을 파악하기 위해 체계적인 문헌 고찰을 수행하였습니다."
        
        # 논문 제목들 추출
        paper_titles = []
        for line in lines:
            if line.startswith('### ') and ('논문' in line or 'Paper' in line or '3.' in line):
                title_part = line.replace('### ', '').strip()
                if ':' in title_part:
                    title_part = title_part.split(':', 1)[1].strip()
                if title_part and len(title_part) > 5:
                    paper_titles.append(title_part[:50])
        paper_titles = paper_titles[:4]
        
        # 핵심 기여 추출
        contributions = []
        in_contrib = False
        for line in lines:
            if '기여' in line or 'Contribution' in line:
                in_contrib = True
                continue
            if in_contrib:
                if line.startswith('#') or line.startswith('---'):
                    break
                if line.strip().startswith(('•', '-', '*', '1.', '2.', '3.')):
                    contrib = line.strip().lstrip('•-*123456789.').strip()
                    if contrib and len(contrib) > 5:
                        contributions.append(contrib[:100])
        contributions = contributions[:3] if contributions else [
            "선정 논문들의 방법론적 특징 분석",
            "연구 동향 및 패턴 식별",
            "향후 연구 방향 도출"
        ]
        
        # 핵심 발견 추출
        findings = []
        in_findings = False
        for line in lines:
            if '핵심 발견' in line or '주요 발견' in line or 'Key' in line or '통찰' in line:
                in_findings = True
                continue
            if in_findings:
                if line.startswith('#') or line.startswith('---'):
                    break
                if line.strip().startswith(('•', '-', '*', '✅', '1.', '2.', '3.')):
                    finding = line.strip().lstrip('•-*✅123456789.').strip()
                    if finding and len(finding) > 5:
                        findings.append(finding[:100])
        findings = findings[:4] if findings else ["방법론적 다양성 확인", "공통 연구 트렌드 발견", "성능 개선 패턴 식별", "연구 공백 파악"]
        
        # 결론 추출
        conclusion = ""
        in_conclusion = False
        for line in lines:
            if '결론' in line or 'Conclusion' in line:
                in_conclusion = True
                continue
            if in_conclusion:
                if line.startswith('#') or line.startswith('---'):
                    break
                if line.strip() and not line.startswith('**'):
                    conclusion += line.strip() + " "
        conclusion = conclusion[:400] if conclusion else "본 분석을 통해 해당 분야의 연구 동향을 파악하고, 향후 연구 방향에 대한 통찰을 얻었습니다."
        
        # 기여 HTML
        contrib_html = "".join([f'''
                            <li class="flex items-start">
                                <span class="bg-blue-600 text-white rounded-full w-5 h-5 flex items-center justify-center mr-2 mt-1 text-xs flex-shrink-0">{i+1}</span>
                                <div>{c}</div>
                            </li>''' for i, c in enumerate(contributions)])
        
        # 발견 HTML
        findings_html = "".join([f'<li class="py-1 border-b border-slate-100">✅ {f}</li>' for f in findings])
        
        # 논문 목록 HTML
        papers_html = "".join([f'<li class="border-l-4 border-blue-500 pl-3 py-1">{t}</li>' for t in paper_titles]) if paper_titles else '<li>논문 정보 없음</li>'
        
        return f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        :root {{
            --primary: #2563eb;
            --secondary: #1e293b;
            --accent: #f59e0b;
            --bg-color: #f8fafc;
            --box-bg: #ffffff;
        }}
        
        body {{
            font-family: 'Inter', 'Noto Sans KR', sans-serif;
            background-color: #e2e8f0;
            color: #1e293b;
            margin: 0;
            padding: 20px;
            min-width: 1600px; 
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
            padding: 40px;
            box-sizing: border-box;
            aspect-ratio: 20 / 9;
        }}

        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 4px solid var(--primary);
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}

        .title-area h1 {{
            font-size: 2.8rem;
            font-weight: 900;
            color: var(--primary);
            margin: 0;
            line-height: 1.1;
            letter-spacing: -0.02em;
        }}

        .title-area h2 {{
            font-size: 1.4rem;
            font-weight: 500;
            color: var(--secondary);
            margin: 10px 0 0 0;
        }}

        .authors {{
            font-size: 1rem;
            color: #475569;
            margin-top: 10px;
        }}

        .grid-container {{
            display: grid;
            grid-template-columns: 1fr 2fr 1fr;
            gap: 25px;
            flex-grow: 1;
        }}

        .col {{
            display: flex;
            flex-direction: column;
            gap: 20px;
        }}

        .section-box {{
            background: var(--box-bg);
            border-radius: 12px;
            padding: 18px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            border: 1px solid #e2e8f0;
        }}

        .section-title {{
            font-size: 1.3rem;
            font-weight: 800;
            color: var(--primary);
            border-bottom: 2px solid #cbd5e1;
            padding-bottom: 8px;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .section-content {{
            font-size: 0.95rem;
            line-height: 1.6;
            color: #334155;
        }}

        .highlight-box {{
            background-color: #eff6ff;
            border-left: 4px solid var(--primary);
            padding: 12px;
            margin: 10px 0;
            font-style: italic;
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>
    <div class="poster-container">
        <!-- Header -->
        <header>
            <div class="title-area">
                <h1>{title[:80]}</h1>
                <h2>{subtitle}</h2>
                <div class="authors">Systematic Literature Review | {num_papers} Papers Analyzed</div>
            </div>
            <div style="text-align: right;">
                <div style="font-weight: 700; color: var(--primary); font-size: 1.3rem;">AI Research Analysis</div>
                <div>{datetime.now().strftime('%B %d, %Y')}</div>
            </div>
        </header>

        <!-- Main Grid -->
        <div class="grid-container">
            
            <!-- Column 1: Intro & Motivation -->
            <div class="col">
                <div class="section-box">
                    <div class="section-title">📋 1. 초록 (Abstract)</div>
                    <div class="section-content">
                        {abstract}
                    </div>
                </div>

                <div class="section-box">
                    <div class="section-title">🎯 2. 연구 배경 (Motivation)</div>
                    <div class="section-content">
                        {motivation}
                        <div class="highlight-box">
                            "체계적 문헌 고찰을 통해 연구 동향을 파악하고 미래 방향을 제시합니다."
                        </div>
                    </div>
                </div>

                <div class="section-box">
                    <div class="section-title">⭐ 3. 핵심 기여 (Contributions)</div>
                    <div class="section-content">
                        <ul class="space-y-2">
                            {contrib_html}
                        </ul>
                    </div>
                </div>
            </div>

            <!-- Column 2: Main Architecture & Algorithm -->
            <div class="col">
                <div class="section-box" style="flex: 2;">
                    <div class="section-title">🔬 4. 모델 상세 구조 (Architecture Overview)</div>
                    <div class="section-content">
                        <p class="mb-3">본 분석 시스템은 <strong>인코더(Encoder)</strong>, <strong>검색기(Retriever)</strong>, <strong>통합기(Aggregator)</strong>의 3단계 파이프라인으로 구성됩니다.</p>
                        
                        <!-- Detailed Architecture SVG -->
                        <svg viewBox="0 0 800 420" style="background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; width: 100%;">
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
                                <!-- Query Graph -->
                                <circle cx="60" cy="30" r="25" fill="white" stroke="#2563eb" stroke-width="2"/>
                                <circle cx="50" cy="25" r="4" fill="#2563eb"/>
                                <circle cx="70" cy="20" r="4" fill="#2563eb"/>
                                <circle cx="55" cy="40" r="4" fill="#2563eb"/>
                                <line x1="50" y1="25" x2="70" y2="20" stroke="#2563eb" stroke-width="1"/>
                                <line x1="50" y1="25" x2="55" y2="40" stroke="#2563eb" stroke-width="1"/>
                                <text x="60" y="70" text-anchor="middle" font-size="11" font-weight="bold">Query Graph (Gq)</text>
                            </g>

                            <!-- Arrow Down -->
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
                            <!-- Path from Emb to Retrieval -->
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
                                <circle cx="80" y1="55" r="18" fill="none" stroke="#ea580c" stroke-width="1" stroke-dasharray="2,2"/>
                                
                                <text x="80" y="120" text-anchor="middle" font-size="10" font-weight="bold" fill="#9a3412">External Graph DB</text>
                            </g>

                            <!-- Arrow to Retrieved Graphs -->
                            <line x1="420" y1="100" x2="490" y2="100" stroke="#ea580c" stroke-width="2" marker-end="url(#arrowhead-orange)"/>

                            <!-- Retrieved Graphs Stack -->
                            <g transform="translate(500, 45)">
                                <rect x="0" y="0" width="95" height="75" fill="white" stroke="#ea580c" stroke-width="1" rx="5"/>
                                <rect x="5" y="5" width="95" height="75" fill="white" stroke="#ea580c" stroke-width="1" rx="5"/>
                                <rect x="10" y="10" width="95" height="75" fill="white" stroke="#ea580c" stroke-width="2" rx="5"/>
                                
                                <circle cx="40" cy="40" r="4" fill="#ea580c"/>
                                <circle cx="75" cy="40" r="4" fill="#ea580c"/>
                                <line x1="40" y1="40" x2="75" y2="40" stroke="#ea580c" stroke-width="1"/>
                                
                                <text x="55" y="105" text-anchor="middle" font-size="10" font-weight="bold" fill="#ea580c">Retrieved {{Gn}}</text>
                            </g>

                            <!-- STEP 3: AGGREGATION -->
                            <!-- Inputs to Aggregation -->
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

                            <!-- Output Flow -->
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
                            <text x="285" y="268" font-family="serif" font-style="italic" font-size="11" fill="#475569">Aggr(z_q, {{z_n}})</text>

                        </svg>
                    </div>
                </div>

                <div class="section-box" style="flex: 1;">
                    <div class="section-title">📊 5. 알고리즘 상세 (Detailed Algorithm)</div>
                    <div class="section-content">
                        <!-- Algorithm Flowchart SVG -->
                        <svg viewBox="0 0 750 180" style="background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; width: 100%; margin-bottom: 10px;">
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
                        </svg>
                        
                        <!-- Paper List -->
                        <div class="mt-3">
                            <strong class="text-sm">분석 논문:</strong>
                            <ul class="space-y-1 text-sm mt-2">
                                {papers_html}
                            </ul>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Column 3: Results & Conclusion -->
            <div class="col">
                <div class="section-box">
                    <div class="section-title">💡 6. 핵심 발견 (Key Findings)</div>
                    <div class="section-content">
                        <ul class="space-y-1">
                            {findings_html}
                        </ul>
                    </div>
                </div>

                <div class="section-box">
                    <div class="section-title">📈 7. 비교 분석</div>
                    <div class="section-content">
                        <table style="width: 100%; font-size: 0.85rem; border-collapse: collapse;">
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
                                    <td style="padding: 6px; text-align: center; color: #16a34a; font-weight: bold;">{len(findings)}건</td>
                                </tr>
                                <tr>
                                    <td style="padding: 6px;">분석 완료율</td>
                                    <td style="padding: 6px; text-align: center; color: #ea580c; font-weight: bold;">100%</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <div class="section-box">
                    <div class="section-title">🎯 8. 결론 (Conclusion)</div>
                    <div class="section-content">
                        {conclusion}
                    </div>
                </div>
            </div>

        </div>
        
        <!-- Footer -->
        <footer style="margin-top: 20px; padding-top: 15px; border-top: 2px solid #e2e8f0; text-align: center; color: #64748b; font-size: 0.85rem;">
            <p>🤖 AI 기반 심층 연구 분석 시스템 (Deep Research Agent) | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        </footer>
    </div>
</body>
</html>'''
    
    def _save_poster(self, poster_html: str, output_dir: Path) -> str:
        """포스터 파일 저장"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"poster_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        filepath = output_dir / filename
        
        filepath.write_text(poster_html, encoding='utf-8')
        print(f"📊 Poster saved to: {filepath}")
        
        return str(filepath)

