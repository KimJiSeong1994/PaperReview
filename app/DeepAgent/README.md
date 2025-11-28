```markdown
# Deep Agent System for Paper Review

논문 심층 리뷰를 위한 Deep Agents 시스템

## 🎯 개요

이 시스템은 LangChain의 Deep Agents 아키텍처를 활용하여:
- **N명의 연구원 에이전트**가 병렬로 논문을 분석하고
- **1명의 지도교수 에이전트**가 결과를 검증하고 맥락을 유지합니다

## 🏗️ 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    Review Orchestrator                       │
│                   (Master Coordinator)                       │
└───────────────────┬─────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌───────────────┐      ┌───────────────┐
│  Researcher 1 │      │   Advisor     │
│  (Paper 1)    │      │  (Validator)  │
├───────────────┤      ├───────────────┤
│  Researcher 2 │      │ • Validate    │
│  (Paper 2)    │      │ • Synthesize  │
├───────────────┤      │ • Maintain    │
│  Researcher 3 │  ──▶ │   Context     │
│  (Paper 3)    │      │ • Generate    │
├───────────────┤      │   Feedback    │
│     ...       │      │               │
├───────────────┤      └───────────────┘
│  Researcher N │
│  (Paper N)    │
└───────────────┘
   (Parallel)            (Sequential)
```

## 📦 구조

```
app/DeepAgent/
├── __init__.py                    # 패키지 초기화
├── README.md                      # 이 문서
├── system_prompts.py              # 상세한 시스템 프롬프트
├── workspace_manager.py           # 파일 시스템 기반 메모리
├── review_orchestrator.py         # 병렬 실행 오케스트레이션
├── example_usage.py               # 사용 예제
├── subagents/
│   ├── __init__.py
│   ├── researcher_agent.py        # PhD 연구원 에이전트
│   └── advisor_agent.py           # 지도교수 에이전트
└── tools/
    ├── __init__.py
    ├── paper_loader.py            # 논문 로더
    └── report_generator.py        # 리포트 생성기
```

## 🚀 빠른 시작

### 1. 기본 사용법

```python
from app.DeepAgent import review_selected_papers

# 논문 ID 리스트
paper_ids = ["arxiv_id_1", "arxiv_id_2", "arxiv_id_3"]

# 리뷰 실행
result = review_selected_papers(
    paper_ids=paper_ids,
    max_workers=3,  # 3명의 연구원이 병렬 분석
    verbose=True
)

print(f"Status: {result['status']}")
print(f"Report: {result['workspace_path']}")
```

### 2. 커스텀 Orchestrator

```python
from app.DeepAgent import ReviewOrchestrator, WorkspaceManager

# Workspace 생성
workspace = WorkspaceManager()

# Orchestrator 생성
orchestrator = ReviewOrchestrator(
    max_workers=5,
    workspace=workspace
)

# 리뷰 실행
result = orchestrator.review_papers(paper_ids, verbose=True)

# 세션 정보
summary = workspace.get_session_summary()
```

### 3. Web App 통합

```python
from app.DeepAgent import review_selected_papers

def review_endpoint(selected_paper_ids: list):
    """Web App에서 호출하는 엔드포인트"""
    result = review_selected_papers(
        paper_ids=selected_paper_ids,
        max_workers=None,  # 자동 최적화
        verbose=True
    )
    
    return {
        "session_id": result["session_id"],
        "report_path": result["workspace_path"],
        "status": result["status"]
    }
```

## 📋 Deep Agents 4가지 특성

### 1. 📝 Detailed System Prompt
- Researcher: PhD 수준의 논문 분석 프롬프트
- Advisor: 지도교수 수준의 검증 프롬프트
- 각 에이전트의 역할, 도구 사용법, 예제 포함

### 2. 📋 Planning Tool (Todo List)
- Review Orchestrator가 작업 계획 수립
- 단계별 실행 (로드 → 분석 → 검증 → 리포트)

### 3. 🤖 Sub Agents
- **Researcher SubAgents**: 병렬 논문 분석
  - 구조 분석
  - 기여 추출
  - 방법론 식별
  - 재현성 평가
- **Advisor SubAgent**: 검증 및 종합
  - 완전성 검증
  - 과학적 정확성 확인
  - 공통 테마 식별
  - 피드백 제공

### 4. 💾 File System (Workspace)
```
data/workspace/review_YYYYMMDD_HHMMSS_XXXX/
├── metadata.json              # 세션 정보
├── selected_papers.json       # 선택된 논문
├── analyses/                  # 연구원 분석 결과
│   ├── researcher_1_paper_X.json
│   ├── researcher_2_paper_Y.json
│   └── ...
├── validations/               # 지도교수 검증
│   └── validation_TIMESTAMP.json
├── plans/                     # 작업 계획
├── reports/                   # 최종 리포트
│   ├── final_review_TIMESTAMP.md
│   ├── final_review_TIMESTAMP.html
│   └── final_review_TIMESTAMP.json
└── logs/                      # 로그
    └── session.log
```

## 🔬 Researcher Agent

각 Researcher는 다음을 수행:

1. **구조 분석** - 논문 메타데이터 및 섹션
2. **기여 추출** - 주요 기여사항 식별
3. **방법론 분석** - 사용된 기법 및 알고리즘
4. **재현성 평가** - 코드, 데이터, 하이퍼파라미터

**도구:**
- `analyze_paper_structure`
- `extract_key_contributions`
- `identify_methodology`
- `assess_reproducibility`

## 👨‍🏫 Advisor Agent

Advisor는 다음을 수행:

1. **검증** - 분석의 완전성 및 정확성
2. **종합** - 여러 논문 간 공통 테마 및 패턴
3. **피드백** - 연구원에게 구체적 피드백
4. **맥락 유지** - 전체적인 일관성 유지

**도구:**
- `validate_analysis_completeness`
- `check_scientific_accuracy`
- `identify_cross_paper_themes`
- `synthesize_findings`
- `provide_feedback`

## 🔄 실행 흐름

```
1. Load Papers (논문 로드)
   └─▶ Load selected papers from data/raw/papers.json
   
2. Parallel Analysis (병렬 분석)
   ├─▶ Researcher 1 → Paper 1
   ├─▶ Researcher 2 → Paper 2
   ├─▶ Researcher 3 → Paper 3
   └─▶ ...
   (ThreadPoolExecutor로 병렬 실행)
   
3. Validation & Synthesis (검증 및 종합)
   └─▶ Advisor validates all analyses
   └─▶ Identifies cross-paper themes
   └─▶ Generates feedback
   
4. Report Generation (리포트 생성)
   ├─▶ Markdown report
   ├─▶ HTML report
   └─▶ JSON results
   
5. Save Results (결과 저장)
   └─▶ Save to workspace/session_id/
```

## 📊 출력 예시

### Markdown Report
```markdown
# Paper Review Report

**Generated**: 2024-11-28 15:30:00
**Total Papers**: 5

## Executive Summary
- Papers Reviewed: 5
- Approved Analyses: 4
- Needs Revision: 1
- Approval Rate: 80.0%

## Cross-Paper Synthesis
### Common Themes
- Deep Learning: 4 papers
- NLP: 3 papers
- Graph Neural Networks: 2 papers

## Individual Paper Analyses
### Paper 1: Graph RAG: Enhancing...
...
```

## 🧪 테스트

```bash
# 예제 1 실행
python app/DeepAgent/example_usage.py --example 1

# 예제 2 실행
python app/DeepAgent/example_usage.py --example 2
```

## 🔧 설정

### 병렬 실행 워커 수

```python
# 자동 (논문 수 또는 CPU 코어 수)
result = review_selected_papers(paper_ids, max_workers=None)

# 수동 설정
result = review_selected_papers(paper_ids, max_workers=5)
```

### Workspace 경로

```python
# 기본 경로
workspace = WorkspaceManager()  # data/workspace/

# 커스텀 경로
workspace = WorkspaceManager(base_path="custom/path")
```

## 📈 성능

- **병렬 실행**: N개 논문을 N명의 연구원이 동시 분석
- **평균 분석 시간**: ~2-3분/논문 (전체 텍스트 포함)
- **검증 시간**: ~1-2분 (N개 논문)

예시: 5개 논문 리뷰
- 순차 실행: ~15-20분
- 병렬 실행: ~4-5분 (3-4배 빠름)

## 🔗 통합 가이드

### FastAPI 통합

```python
from fastapi import FastAPI
from app.DeepAgent import review_selected_papers

app = FastAPI()

@app.post("/review")
async def review_papers(paper_ids: list[str]):
    result = review_selected_papers(paper_ids, verbose=False)
    return result
```

### Streamlit 통합

```python
import streamlit as st
from app.DeepAgent import review_selected_papers

st.title("Paper Review System")

paper_ids = st.multiselect("Select Papers", all_paper_ids)

if st.button("Review"):
    with st.spinner("Reviewing papers..."):
        result = review_selected_papers(paper_ids)
    st.success(f"Review completed! Session: {result['session_id']}")
```

## 🐛 디버깅

### 로그 확인
```python
workspace = WorkspaceManager()
log_file = workspace.session_path / "logs" / "session.log"
print(log_file.read_text())
```

### 중간 결과 확인
```python
# 분석 결과
analyses = workspace.load_all_analyses()

# 검증 결과
validation = workspace.load_latest_validation()

# 계획
plan = workspace.load_latest_plan()
```

## 📚 참고

- [Deep Agents Blog Post](https://blog.langchain.com/deep-agents/)
- [LangChain Documentation](https://python.langchain.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)

## 🤝 기여

이슈 및 PR 환영합니다!

## 📄 라이센스

MIT License
```

