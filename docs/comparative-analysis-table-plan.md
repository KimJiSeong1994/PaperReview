# Comparative Analysis Table (방법론 비교표) - 심층 기획안

> 에이전트 팀 FGD 기반 기획 (2026-02-18)
> 참여: Paper Review Expert, Backend Architect, Web Designer, Data Visualization Expert, QA Validator

---

## 1. 개요

### 1.1 기능 요약
복수 논문의 방법론/성능/한계를 **LLM 기반으로 자동 추출**하여 구조화된 비교표를 생성한다.

### 1.2 핵심 가치
- 논문 리뷰 작성 시 **비교표 자동 생성**으로 시간 절약
- Related Work 섹션에 **즉시 활용 가능**한 LaTeX/Markdown 내보내기
- 기존 Deep Review 파이프라인의 **분석 결과를 재활용**

### 1.3 지원 범위
- 최대 **20편** 논문 동시 비교
- 최대 **10개** 비교 차원
- 내보내기: CSV, LaTeX, Markdown, 클립보드 복사

---

## 2. LLM 추출 파이프라인 (Paper Review Expert)

### 2.1 추출 차원

**핵심 차원 (기본 추출):**
| 차원 | 설명 | 타입 |
|------|------|------|
| Method/Model | 핵심 방법론/모델 | text |
| Dataset | 학습/평가 데이터셋 | text |
| Key Results | 주요 성능 수치 | text |
| Evaluation Metrics | 평가 지표명 + 값 | text |
| Limitations | 한계점 | text |
| Year | 발표 연도 | numeric |

**확장 차원 (자동 감지 시 추가):**
- Training Details, Inference Cost, Code Availability, Novelty Claims

### 2.2 추출 전략

```
Step 1: 차원 결정 (자동/수동)
  - 사용자가 차원을 지정하면 그대로 사용
  - 미지정 시 LLM이 논문 목록을 보고 최적 5-8개 차원 자동 결정

Step 2: 논문별 차원 추출 (병렬 불가, 순차 처리)
  - 각 논문의 abstract + full_text(있으면)를 LLM에 전달
  - response_format: {"type": "json_object"} 으로 구조화 출력 강제
  - 추출 결과를 파일 캐시에 저장 (TTL: 7일)

Step 3: 차원 정렬
  - 모든 논문에 동일 차원 키 적용
  - 누락된 셀은 "Not reported" / "N/A"로 채움
```

### 2.3 프롬프트 설계

```python
system_prompt = (
    "You are an expert academic paper analyst. "
    "Extract structured information from the given paper "
    "according to the specified dimensions. "
    "Return ONLY a valid JSON object with dimension names as keys. "
    "If information is not available, use 'Not reported'."
)

user_prompt = f"""Extract the following dimensions from this paper:
{dimensions_list}

Paper:
Title: {title}
Abstract: {abstract[:3000]}
Full text (excerpt): {full_text[:8000]}

Return a JSON object with these exact dimension names as keys.
"""
```

### 2.4 메트릭 정규화
- 동일 메트릭의 다른 표기 ("accuracy" vs "acc" vs "top-1 accuracy") → LLM이 차원 결정 시 통일
- 숫자 단위 ("93.2%" vs "0.932") → 추출 시 원본 텍스트 그대로 유지, 프론트엔드에서 파싱

---

## 3. 백엔드 API 설계 (Backend Architect)

### 3.1 엔드포인트

```
POST /api/comparative-table                    # 비교표 생성 시작
GET  /api/comparative-table/{table_id}         # 비교표 조회 (폴링)
PUT  /api/comparative-table/{table_id}         # 셀 편집
POST /api/comparative-table/{table_id}/add-papers  # 논문 추가 (증분)
GET  /api/comparative-table/export/{table_id}  # 내보내기 (?format=csv|latex|markdown)
GET  /api/comparative-tables                   # 목록 조회
DELETE /api/comparative-table/{table_id}       # 삭제
```

### 3.2 데이터 모델

```python
class ComparativeTableRow(BaseModel):
    paper_id: str
    paper_title: str
    paper_authors: List[str]
    paper_year: str
    paper_url: str
    values: Dict[str, str]  # dimension_name -> extracted_value

class ComparativeTable(BaseModel):
    id: str
    username: str
    title: str
    columns: List[str]        # 차원 이름 목록
    rows: List[ComparativeTableRow]
    status: str               # "generating" | "completed" | "failed"
    version: int
    created_at: str
    updated_at: str
    generation_model: str
    bookmark_ids: List[str]
    source_paper_ids: List[str]
    edit_history: List[dict]
    generation_metadata: dict  # duration, partial_failures 등
```

### 3.3 저장소

```
data/comparative_tables.json          # 비교표 영구 저장
data/cache/dimension_extractions/     # 논문별 추출 캐시 (SHA-256 해시 파일명)
```

- 기존 `bookmarks.json` 패턴과 동일한 `FileLock` 기반 원자적 읽기/쓰기
- 인메모리 `comparative_tables_store` dict로 생성 진행 상태 추적

### 3.4 생성 흐름

```
[POST 요청] → 입력 검증 → 즉시 table_id 반환 (202 Accepted)
                ↓
        [BackgroundTasks]
                ↓
    Step 0: 논문 수집 (paper_ids / bookmark_ids → load_papers)
    Step 1: 캐시 확인 → 캐시 hit면 재사용
    Step 2: LLM 차원 추출 (논문별 순차, 진행률 업데이트)
    Step 3: 차원 정렬 + 누락 셀 보정
    Step 4: 영구 저장 → status: "completed"
                ↓
        [GET 폴링으로 프론트엔드 수신]
```

### 3.5 내보내기 형식

| 형식 | 특징 |
|------|------|
| CSV | UTF-8, 메타데이터 주석행(`#`) 포함 |
| LaTeX | `\resizebox`, `\caption`, `\label` 포함, 특수문자 이스케이프 |
| Markdown | 논문 제목에 URL 링크 자동 삽입 |

### 3.6 파일 구조

| 파일 | 설명 |
|------|------|
| `routers/comparative_table.py` | API 라우터 (신규) |
| `routers/comparative_table_service.py` | 백그라운드 생성 + 내보내기 (신규) |
| `routers/deps/storage.py` | comparative_tables load/save 함수 추가 |
| `routers/__init__.py` | 라우터 등록 |
| `api_server.py` | `app.include_router()` 추가 |

---

## 4. 프론트엔드 UI/UX 설계 (Web Designer)

### 4.1 배치 위치

ReportViewer 패널 내에 **탭 시스템**을 도입:

```
[ Report ]  [ Compare (3) ]
```

- "Report" 탭: 기존 단일 북마크 리포트 뷰
- "Compare" 탭: 다중 북마크 비교 테이블 + 레이더 차트
- 선택된 북마크 2개 미만이면 "Compare" 탭 비활성

### 4.2 진입점

BookmarkSidebar의 `mypage-bulk-bar`에 **"Compare"** 버튼 추가:

```
| 3 selected [All] [None]  [Compare] [Move to...] [Delete] |
```

- `selectedIds.size >= 2` 일 때만 활성
- 클릭 시 `activeTab = 'compare'` + API 호출

### 4.3 비교 테이블 레이아웃

```
+===================================================================+
|  TOOLBAR: [Columns v] [+ Add Column]     [Export v] [Radar ON/OFF]|
+===================================================================+
|  RADAR CHART (접기 가능)                                           |
|  Paper A (blue) ◆  Paper B (purple) ◇  Paper C (green) △         |
+===================================================================+
|  TABLE                                                            |
|  | Paper (고정) | Model ▲ | Dataset | Acc (%) | F1 (%) | Params | |
|  |=============|========|========|========|=======|=======|       |
|  | Paper A      | GPT-4  | GLUE   | ██ 95.2 | ██ 93.1| 175B   | |
|  | Paper B      | BERT   | SQuAD  | █░ 88.7 | █░ 86.4| 340M   | |
|  ← 가로 스크롤 →                                                   |
+===================================================================+
```

**핵심 디자인 요소:**
- 첫번째 열(논문명) `position: sticky; left: 0;`으로 고정
- 숫자형 셀: 인라인 프로그레스 바 + 수치
- 최고값: 연두색 배경 + 볼드 / 최저값: 연분홍 배경
- 컬럼 헤더 클릭 → 정렬 토글 (none → asc → desc)
- 셀 더블클릭 → 인라인 편집

### 4.4 상태별 UI

| 상태 | UI |
|------|-----|
| Empty | "Select 2+ bookmarks to compare" + 아이콘 |
| Loading | 스피너 + "Analyzing Paper A (1/3)" + Progress Bar |
| Error | 경고 아이콘 + [Retry] [Edit Manually] 버튼 |
| Completed | 테이블 + 차트 + Export 툴바 |

### 4.5 컴포넌트 구조

```
MyPage.tsx
  ├── BookmarkSidebar.tsx       (Compare 버튼 추가)
  ├── ReportViewer.tsx          (탭 시스템 래핑)
  │   ├── ReportTab             (기존 리포트)
  │   └── CompareTab            (NEW)
  │       ├── CompareToolbar
  │       ├── CompareRadarOverlay
  │       ├── CompareTable
  │       │   ├── CompareTableHeader
  │       │   ├── CompareTableRow
  │       │   └── CompareTableCell
  │       └── CompareExportModal
  └── ChatPanel.tsx             (기존)
```

### 4.6 커스텀 훅

```typescript
// hooks/useComparison.tsx
export function useComparison(selectedIds: Set<string>, bookmarks: Bookmark[]) {
  // 상태: comparisonData, loading, error, sortKey, sortDir, activeTab
  // 핸들러: fetchComparison, toggleSort, toggleColumnVisibility, editCell
  // Export: exportCSV, exportLaTeX, exportMarkdown, copyToClipboard
  // Computed: sortedRows, visibleColumns
}
```

### 4.7 CSS 네이밍

`mypage-compare-*` 네임스페이스:
- `mypage-compare-container`, `mypage-compare-toolbar`
- `mypage-compare-table`, `mypage-compare-th-sortable`, `mypage-compare-td-best`
- `mypage-compare-radar`, `mypage-compare-export-modal`

### 4.8 반응형

| 화면 | 레이아웃 |
|------|---------|
| Desktop (>1200px) | 3-패널, 테이블 가로스크롤 |
| Tablet (900-1200px) | ChatPanel 숨김, 레이더 축소 |
| Mobile (<600px) | 카드 뷰 전환, 레이더 숨김 |

---

## 5. 시각화 설계 (Data Visualization Expert)

### 5.1 멀티 페이퍼 레이더 차트

Plotly.js `scatterpolar` 타입 사용 (기존 `react-plotly.js` 활용).

```typescript
// 8색 팔레트 (기존 앱 색상과 조화)
const PAPER_COLORS = [
  '#818cf8', '#f472b6', '#34d399', '#fbbf24',
  '#60a5fa', '#a78bfa', '#fb923c', '#2dd4bf',
];

// Trace: 각 논문이 하나의 다각형
{
  type: 'scatterpolar',
  r: [...scores, scores[0]],  // 닫힌 다각형
  theta: [...dimensions, dimensions[0]],
  fill: 'toself',
  fillcolor: `${color}1a`,   // 반투명 배경
  name: paper.shortTitle,
}

// Layout: 다크 테마, 기존 GraphView 스타일 일관성
{
  polar: { bgcolor: 'transparent', radialaxis: { range: [0, 10] } },
  paper_bgcolor: 'transparent',
  plot_bgcolor: 'transparent',
}
```

**인터랙션:**
- 범례 클릭 → 논문 토글 on/off
- 호버 → 정확한 수치 표시
- 클릭 → 테이블 해당 행 하이라이트

### 5.2 성능 메트릭 바 차트

Plotly.js `bar` 타입, `barmode: 'group'`.

- 2편 이상에서 공통 보고된 메트릭만 기본 표시
- 결측값은 바를 그리지 않음 (null → gap)
- 메트릭 필터 체크박스 제공

### 5.3 히트맵 뷰

Plotly.js `heatmap` 타입.

- 행(Y축): 논문, 열(X축): 평가 차원
- 색상: 빨간색(낮음) → 노란색(중간) → 초록색(높음)
- Min-Max 정규화 적용, 원본 값은 셀 텍스트로 표시
- 결측값: 회색 배경 + "N/A" 텍스트

### 5.4 차트-테이블 양방향 동기화

```
[ComparisonTable]  ←→  [ChartPanel]
        ↓                    ↓
   onRowClick(id)      onChartClick(id)
        ↓                    ↓
     [ChartInteractionState (공유)]
       - selectedPaperId
       - hoveredPaperId
       - visiblePaperIds
       - activeChartType: 'radar' | 'bar' | 'heatmap'
```

### 5.5 차트 타입 선택기

```
[ Radar | Bar | Heatmap ]
```

탭 형태 선택기, 기존 AdminPage 탭 스타일 재사용.

### 5.6 이미지 내보내기

Plotly 기본 toImage + 커스텀 다운로드: PNG, SVG (2x 스케일 고해상도).

---

## 6. 테스트 전략 (QA Validator)

### 6.1 백엔드 테스트

| 영역 | 테스트 수 | 핵심 검증 |
|------|----------|----------|
| 프롬프트 구성 | 4 | 모든 논문 포함, JSON 형식 요구 |
| LLM 응답 파싱 | 5 | 정상 JSON, markdown 감싼 응답, malformed |
| 차원 정렬 | 4 | 숫자 정규화, 타입 추론, 누락 보정 |
| Export 포맷터 | 3x3 | CSV/LaTeX/Markdown 각각 정상+특수문자+null |
| API 엔드포인트 | 6 | 성공/에러/인증별 HTTP 상태코드 |

### 6.2 프론트엔드 테스트

| 영역 | 테스트 수 | 핵심 검증 |
|------|----------|----------|
| 테이블 렌더링 | 5 | 헤더, 셀 값, null 표시, 빈 데이터 |
| 정렬/필터 | 4 | 오름차순/내림차순, 숫자/텍스트, null 처리 |
| 셀 편집 | 4 | 더블클릭 진입, Enter 저장, Escape 취소 |
| 내보내기 | 3 | CSV/LaTeX/MD 버튼 동작 |
| 로딩/에러 | 3 | 스피너, 에러 메시지, 재시도 |

### 6.3 엣지 케이스

- 메트릭 없는 서베이 논문
- 대형 테이블 (25편/15차원)
- 한영 혼합 논문
- 중복 논문 중복 제거
- 네트워크 끊김 mid-generation
- 초록 없는 논문

### 6.4 품질 기준

| 메트릭 | 기준 |
|--------|------|
| 백엔드 커버리지 | >= 80% |
| 프론트엔드 커버리지 | >= 75% |
| LLM 추출 정확도 (semantic) | >= 70% |
| API 응답 시간 (mock) | < 200ms |
| API 응답 시간 (실 LLM) | < 30s |

### 6.5 테스트 데이터

- `tests/fixtures/mock_papers.json` — 표준 3편 + 한국어 1편 + 엣지 케이스 4편
- `tests/fixtures/expected_extractions.json` — 골든 추출 결과
- `web-ui/src/test/fixtures/comparativeFixtures.ts` — 프론트엔드 mock

---

## 7. 구현 로드맵

### Phase 1: MVP (핵심 기능)

```
[Week 1-2]
├── 백엔드
│   ├── comparative_table.py 라우터 (POST/GET/DELETE)
│   ├── comparative_table_service.py (LLM 추출 + 저장)
│   └── deps/storage.py 확장
├── 프론트엔드
│   ├── useComparison 훅 기본 구조
│   ├── ReportViewer 탭 시스템
│   ├── CompareTab (빈 상태 + 로딩 + 기본 테이블)
│   ├── BookmarkSidebar Compare 버튼
│   └── api/client.ts API 함수 추가
└── 테스트
    └── API 엔드포인트 기본 테스트
```

### Phase 2: 시각화 + 편집

```
[Week 3]
├── CompareRadarOverlay (Plotly scatterpolar)
├── 차트-테이블 hover 연동
├── 셀 타입별 렌더링 (percentage bar, best/worst)
├── 컬럼 관리 (표시/숨김)
└── 셀 인라인 편집
```

### Phase 3: 내보내기 + 고급 기능

```
[Week 4]
├── Export 기능 (CSV, LaTeX, Markdown, Clipboard)
├── Export 미리보기 모달
├── Performance Bar Chart + Heatmap 뷰
├── 증분 논문 추가 (add-papers)
├── 반응형 디자인 (모바일 카드뷰)
└── 전체 테스트 스위트 완성
```

---

## 8. 비용/성능 분석

### LLM 호출 비용 (gpt-4.1 기준)

| 작업 | 입력 토큰 | 출력 토큰 | 비용 |
|------|----------|----------|------|
| 차원 자동 결정 (1회) | ~1,000 | ~200 | ~$0.01 |
| 논문별 차원 추출 (1편) | ~2,000 | ~500 | ~$0.02 |
| **20편 최대 (캐시 miss)** | | | **~$0.41** |

### 캐시 효과

```
L1: 인메모리 (생성 진행 상태) — 서버 재시작 시 소멸
L2: 파일 캐시 (data/cache/dimension_extractions/) — TTL 7일
    → 반복 사용 논문 60-70% LLM 호출 절감
L3: 영구 저장 (data/comparative_tables.json)
```

### 성능 예상

| 논문 수 | 예상 소요 시간 | 캐시 hit 시 |
|---------|-------------|------------|
| 3편 | ~30초 | ~5초 |
| 10편 | ~100초 | ~30초 |
| 20편 | ~200초 | ~60초 |

---

## 9. 기존 시스템과의 관계

| 기존 시스템 | 활용 방식 |
|-----------|----------|
| Deep Review (reviews.py) | BackgroundTasks 패턴 동일 적용 |
| Bookmark (bookmarks.py) | bookmark_ids로 논문 조회, 비교표 연동 |
| Paper Loader (paper_loader.py) | paper_ids → 논문 데이터 로드 |
| OpenAI Client (deps/openai_client.py) | 싱글톤 클라이언트 재사용 |
| react-plotly.js | 기존 GraphView/AdminPage와 동일한 라이브러리 |
| FileLock (deps/storage.py) | 기존 bookmarks.json 잠금 패턴 동일 |

---

## 10. 미변경 사항

- 기존 Deep Review 파이프라인 — 변경 없음
- 기존 북마크 CRUD — 변경 없음 (read-only 참조만)
- 기존 채팅 시스템 — 변경 없음
- 백엔드 인증 시스템 — 기존 JWT 그대로 사용

---

> **Team Lead 의견**: Comparative Analysis Table은 기존 리뷰 시스템의 가치를 극대화하는 핵심 기능이다.
> 기존 인프라(BackgroundTasks, FileLock, OpenAI 클라이언트, Plotly.js)를 최대한 재사용하여
> 구현 복잡도를 낮추면서도 연구자에게 높은 가치를 제공할 수 있다.
> Phase 1 MVP만으로도 "논문 비교표 자동 생성" 핵심 가치를 전달 가능하다.
