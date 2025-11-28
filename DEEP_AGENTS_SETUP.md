# Deep Agents 설치 및 구조 분석 완료 ✅

## 📦 설치된 패키지

### 핵심 패키지
```
✅ langchain (v1.1.0)          - LLM 애플리케이션 프레임워크
✅ langchain-openai (v1.1.0)   - OpenAI 통합
✅ langchain-core (v1.1.0)     - LangChain 핵심 컴포넌트
✅ langgraph (v1.0.4)          - 복잡한 에이전트 워크플로우
✅ langgraph-sdk (v0.2.10)     - LangGraph SDK
✅ langsmith (v0.4.49)         - LLM 앱 모니터링 및 디버깅
✅ deepagents (v0.2.8)         - Deep Agents 패키지
✅ langchain-anthropic (v1.2.0) - Claude 통합 (deepagents 의존성)
```

### 지원 패키지
```
✅ tiktoken (v0.12.0)         - OpenAI 토크나이저
✅ anthropic (v0.75.0)        - Anthropic API 클라이언트
✅ wcmatch (v10.1)            - 파일 패턴 매칭
```

---

## 🎯 Deep Agents 핵심 개념 (LangChain Blog 기반)

### Deep Agents란?
**"Shallow" Agent의 한계를 극복하는 장기 실행 복잡 작업 처리 Agent**

| 특성 | Shallow Agent | Deep Agent |
|------|---------------|------------|
| 실행 시간 | 단기 | 장기 (수십 분~수 시간) |
| 계획 수립 | 없음/단순 | 복잡한 다단계 계획 |
| 컨텍스트 관리 | LLM 윈도우만 | File System + Workspace |
| 작업 분해 | 불가 | Sub Agents로 분할 |
| 깊이 | 얕음 | 깊은 탐색 |

### 4가지 핵심 특성

#### 1️⃣ Detailed System Prompt (상세한 시스템 프롬프트)
```python
# Claude Code 스타일의 매우 상세한 프롬프트
- 도구 사용법에 대한 구체적인 지시사항
- Few-shot 예제 (특정 상황에서의 행동 샘플)
- 작업 흐름 가이드라인
```

**중요성**: "프롬프팅이 여전히 가장 중요하다!"

#### 2️⃣ Planning Tool (계획 도구)
```python
# 실제로는 No-Op (아무것도 안함)
# 하지만 LLM이 작업을 구조화하도록 유도

class PlanningTool:
    def create_todo(self, tasks: List[str]) -> str:
        logger.info(f"Plan: {tasks}")
        return "Plan saved"  # Context Engineering!
```

**목적**: LLM의 Chain-of-Thought 강화, 장기 목표 유지

#### 3️⃣ Sub Agents (하위 에이전트)
```python
# 작업을 특화된 하위 에이전트에게 위임
SearchAgent  → 논문 검색 전담
AnalysisAgent → 논문 분석 전담  
SynthesisAgent → 종합 분석 전담
ComparisonAgent → 비교 분석 전담
```

**효과**: 
- 각 에이전트가 특정 작업에 집중
- 깊이 있는 탐색 가능
- 컨텍스트 관리 및 프롬프트 단축

#### 4️⃣ File System (파일 시스템)
```python
# 장기 메모리 및 협업 공간
data/workspace/
  ├── session_123/
  │   ├── search_agent_result.json
  │   ├── analysis_notes.md
  │   ├── intermediate_findings.json
  │   └── final_summary.md
```

**용도**:
- 중간 결과 저장
- 에이전트 간 컨텍스트 공유
- 작업 메모 및 로그

---

## 🔧 deepagents 패키지 API

### 주요 컴포넌트

#### 1. `create_deep_agent()`
```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model="gpt-4o-mini",  # 또는 "claude-sonnet-4"
    system_prompt="Your custom instructions...",
    tools=[],  # 커스텀 도구
    subagents=[],  # 하위 에이전트
    # 기본으로 포함되는 도구들:
    # - write_todos (Planning Tool)
    # - ls, read_file, write_file, edit_file, glob, grep (File System)
    # - execute (Shell 명령 실행, sandbox 지원 시)
)
```

**반환값**: `CompiledStateGraph` (LangGraph)

#### 2. `SubAgent`
```python
from deepagents import SubAgent

research_agent = SubAgent(
    name="research_agent",
    instructions="Specialized instructions for this sub-agent",
    tools=[],  # 이 서브 에이전트만의 도구
)

# 반환값: dict
# {
#     'name': 'research_agent',
#     'instructions': '...',
#     'tools': [...]
# }
```

#### 3. `FilesystemMiddleware`
```python
from deepagents import FilesystemMiddleware

# 파일 시스템 도구 제공:
# - ls: 디렉토리 내용 나열
# - read_file: 파일 읽기
# - write_file: 파일 쓰기
# - edit_file: 파일 편집
# - glob: 파일 패턴 검색
# - grep: 파일 내용 검색
```

#### 4. `SubAgentMiddleware`
```python
from deepagents import SubAgentMiddleware

# Sub Agent 관리 미들웨어
# task 도구를 통해 하위 에이전트 호출
```

---

## 🏗️ PaperReviewAgent에 Deep Agents 적용 계획

### Phase 1: Master Agent (Orchestrator) 🎯
```python
# app/MasterAgent/deep_research_agent.py
from deepagents import create_deep_agent, SubAgent

class DeepResearchAgent:
    """
    논문 심층 분석을 위한 Master Deep Agent
    """
    def __init__(self):
        self.agent = create_deep_agent(
            model="gpt-4o",
            system_prompt=RESEARCH_SYSTEM_PROMPT,
            subagents=[
                self._create_search_subagent(),
                self._create_analysis_subagent(),
                self._create_synthesis_subagent(),
            ]
        )
```

### Phase 2: Planning Tool (Todo List) 📋
```python
# 기본으로 포함된 write_todos 도구 활용
# LLM이 자동으로 작업을 분해하도록 프롬프트 설계

"""
예시 플랜:
질의: "Graph RAG의 한계점과 개선 방법 심층 분석"

→ LLM이 생성한 Todo:
[ ] 1. Graph RAG 기본 개념 논문 검색 (2020-2024)
[ ] 2. 한계점 관련 논문 수집 및 분석
[ ] 3. 개선 방법 제안 논문 탐색
[ ] 4. 대안 기술 비교 (Vector RAG, Hybrid RAG)
[ ] 5. 종합 분석 리포트 생성
"""
```

### Phase 3: Sub Agents 정의 🤖

#### SearchSubAgent
```python
SubAgent(
    name="paper_search",
    instructions="""
You are specialized in academic paper search.
- Use arXiv, Google Scholar, Connected Papers APIs
- Focus on finding highly relevant papers
- Prioritize recent publications (last 2-3 years)
- Save search results to workspace
    """,
    tools=[arxiv_search_tool, scholar_search_tool]
)
```

#### AnalysisSubAgent
```python
SubAgent(
    name="paper_analysis",
    instructions="""
You specialize in deep paper analysis.
- Extract key contributions
- Identify limitations
- Find proposed improvements
- Analyze methodology
- Save analysis to workspace
    """,
    tools=[text_extraction_tool, llm_analysis_tool]
)
```

#### SynthesisSubAgent
```python
SubAgent(
    name="synthesis",
    instructions="""
You synthesize findings from multiple papers.
- Cross-paper insight generation
- Trend identification
- Gap analysis
- Generate comprehensive reports
    """,
    tools=[graph_rag_tool, report_generation_tool]
)
```

### Phase 4: Workspace Manager 💾
```python
# 기본 파일 시스템 도구 활용 + 커스텀 확장

class WorkspaceManager:
    """
    Deep Agent 작업 공간 관리
    """
    def __init__(self):
        self.base_path = "data/workspace/"
        self.session_id = generate_session_id()
    
    def save_intermediate_result(self, agent_name, data):
        """중간 결과 저장"""
        path = f"{self.base_path}/{self.session_id}/{agent_name}_result.json"
        # write_file 도구 사용
    
    def load_context(self, context_key):
        """이전 컨텍스트 로드"""
        # read_file 도구 사용
    
    def create_note(self, title, content):
        """메모 생성 (Claude Code 스타일)"""
        # write_file 도구 사용
```

---

## 📝 다음 단계 TODO

### 즉시 시작 가능 (오늘~내일)
- [ ] Master Agent 기본 구조 생성 (`app/MasterAgent/`)
- [ ] Enhanced System Prompt 작성 (Claude Code 스타일)
- [ ] Planning Tool 통합 (기본 제공되는 write_todos 활용)

### 단기 목표 (이번 주)
- [ ] 기존 Agent들을 Sub Agent로 리팩토링
  - [ ] `SearchAgent` → SubAgent
  - [ ] `QueryAnalyzer` → SubAgent
  - [ ] `GraphRAG` → SubAgent
- [ ] Workspace Manager 구현
- [ ] 통합 테스트

### 중기 목표 (다음 주)
- [ ] 고급 Sub Agent 추가
  - [ ] `ComparisonSubAgent`
  - [ ] `SynthesisSubAgent`
  - [ ] `SurveySubAgent`
- [ ] Web UI에 진행 상황 표시 (Todo List 시각화)
- [ ] LangSmith 통합 (모니터링 및 디버깅)

---

## 🧪 테스트 스크립트

`test_deepagents.py` 파일이 생성되었습니다.

실행 방법:
```bash
source .venv/bin/activate
python test_deepagents.py
```

---

## 📚 참고 자료

### 공식 문서
- **LangChain Blog**: https://blog.langchain.com/deep-agents/
- **deepagents GitHub**: https://github.com/langchain-ai/deepagents (추정)
- **LangGraph 문서**: https://langchain-ai.github.io/langgraph/

### 핵심 인사이트

> "The core algorithm is actually the same - it's an LLM running in a loop calling tools. The difference is:
> 1. A detailed system prompt
> 2. Planning tool (no-op, but context engineering)
> 3. Sub agents
> 4. File system"
> 
> — LangChain Blog

---

## ✅ 설치 확인

```bash
✅ Python 3.12 가상환경 (.venv)
✅ langchain, langgraph, deepagents 설치 완료
✅ OpenAI, Anthropic 통합 준비 완료
✅ 테스트 스크립트 작동 확인
```

---

## 🚀 시작하기

다음 파일을 생성하여 시작하세요:

1. **`app/MasterAgent/__init__.py`**
2. **`app/MasterAgent/deep_research_agent.py`** - Master Agent
3. **`app/MasterAgent/system_prompt.py`** - 상세한 프롬프트
4. **`app/MasterAgent/workspace_manager.py`** - Workspace 관리
5. **`app/MasterAgent/subagents.py`** - Sub Agent 정의

---

**준비 완료! 이제 Deep Agents 구축을 시작할 수 있습니다! 🎉**

