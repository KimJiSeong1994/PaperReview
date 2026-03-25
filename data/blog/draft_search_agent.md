# 집현전 검색 에이전트: 단일 쿼리의 한계를 넘어서

*6개 학술 데이터베이스 병렬 검색에서 출발해, 결과를 분석하고 부족한 부분을 스스로 보완하는 멀티턴 검색 에이전트까지 구축한 이야기.*

작성: 집현전 팀 · 17분 읽기
태그: #검색에이전트 #ReAct #HybridRanking #RaR

---

## 논문 검색이 어려운 이유

논문을 쓰거나 리뷰할 때, 관련 문헌을 제대로 찾는 일이 생각보다 어렵다는 것을 실감한 적이 있을 것이다. "transformer attention mechanism"을 검색하면 핵심 논문들은 나오지만, 그것이 전부가 아니다. 비슷한 문제를 다른 용어로 접근한 논문, 최근 2년 사이에 등장한 후속 연구, 관련 벤치마크를 제안한 논문들은 첫 번째 검색으로는 거의 보이지 않는다.

문제는 몇 가지로 압축된다.

첫째, **용어 불일치**다. 같은 개념도 논문마다 다르게 표현된다. `self-attention`이라 쓰는 논문이 있고, `scaled dot-product attention`이라 쓰는 논문이 있다. 한국어로 검색한다면 상황은 더 심각해진다.

둘째, **데이터베이스 편향**이다. arXiv는 CS/ML 논문이 풍부하지만 생의학 분야는 약하다. Google Scholar는 인용 수 기반 인기 논문을 잘 찾지만 최신 프리프린트는 느리다. 어느 한 곳만 보면 반드시 빠뜨리는 논문이 생긴다.

셋째, **단일 검색의 커버리지 한계**다. 아무리 좋은 쿼리를 작성해도, 검색 한 번으로 주제 공간 전체를 커버하기는 어렵다. 서베이 논문과 방법론 논문은 다른 키워드로 찾아야 하고, 초기 제안 논문과 확장 연구는 또 다르다.

우리는 이 문제를 해결하기 위해 [집현전(jiphyeonjeon.kr)](https://jiphyeonjeon.kr) 서비스의 검색 인프라를 점진적으로 발전시켜 왔다. 이 글은 그 과정에서 무엇이 실패했고, 무엇이 작동했는지를 솔직하게 정리한 기록이다.

---

## 첫 번째 파이프라인: 6소스 병렬 검색

처음 구축한 파이프라인의 아이디어는 단순했다. "여러 소스를 동시에 검색하면 커버리지가 올라간다." arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers, OpenAlex Korean — 6개의 데이터베이스를 동시에 호출하고, 결과를 모아 랭킹한다.

### QueryAnalyzer: 쿼리를 이해하는 첫 번째 레이어

검색 전에 `QueryAnalyzer`가 먼저 사용자의 의도를 파악한다. 8가지 intent로 분류한다.

- `paper_search`: 특정 주제의 논문을 찾는다
- `topic_exploration`: 연구 영역을 탐색한다
- `author_search`: 특정 저자의 논문을 찾는다
- `method_search`: 특정 방법론이나 알고리즘을 찾는다
- `comparison`: 여러 접근법을 비교하려 한다
- `survey`: 서베이/리뷰 논문을 원한다
- `latest_research`: 최신 연구 동향을 파악하려 한다
- `problem_solving`: 특정 문제나 한계를 다루는 논문을 찾는다

분류는 `gpt-4o-mini`에 위임하고 결과를 24시간 TTL의 인메모리 캐시(최대 500개 엔트리)에 저장해 반복 호출 비용을 줄인다. LLM을 쓸 수 없는 상황에서는 규칙 기반 `_fallback_analysis`가 동작한다 — `"recent"`, `"survey"` 같은 키워드를 직접 매칭한다.

분석 결과는 `improved_query`도 포함한다. 원칙은 보수적이다. 오타 수정, 단복수 교정, 약어 확장 정도만 허용한다. 우리는 "임베딩에 관한 NLP 연구"처럼 원래 의도에 없던 컨텍스트를 LLM이 멋대로 추가하다가 검색 품질이 오히려 떨어지는 상황을 여러 번 경험했다. 그래서 이중 guardrail을 유지한다. LLM 프롬프트 수준에서는 쿼리 길이를 원본의 1.5배 이내로 제한하고, 코드 수준에서는 confidence 0.8 미만이면 원본 쿼리를 그대로 사용하며, improved query와 원본의 어간 겹침(stem overlap)이 50% 미만이거나 길이 비율이 2배를 초과해도 폐기한다.

### 하이브리드 랭킹: BM25 + Semantic + Citations + Recency

6개 소스에서 수집된 논문들은 중복 제거를 거쳐 `HybridRanker`로 넘어간다. 랭킹의 핵심은 4가지 신호의 조합이다.

**BM25 (sparse retrieval)**: 제목을 2회 반복 연결해 제목 매칭에 더 높은 가중을 준다. `rank_bm25` 패키지를 사용하며, 불가 시 단순 키워드 오버랩으로 대체한다.

**Semantic (dense retrieval)**: Field-weighted 코사인 유사도 — 제목 0.6, 초록 0.4 비율로 결합한다. OpenAI 클라이언트가 주입되면 **HyDE (Hypothetical Document Embedding)** 가 활성화된다. gpt-4o-mini로 가상 초록(hypothetical abstract)을 생성하고, 동시에 대안 쿼리 2개를 생성한 후, 이 4개 텍스트(원본 쿼리 + 가상 초록 + 대안 2개)의 임베딩을 `text-embedding-3-small`로 한 번에 배치 처리해 L2-정규화 평균을 쿼리 벡터로 사용한다.

**Citations**: log 정규화. `log(1 + c) / log(1 + max_c)` 공식으로 인용 수가 폭발적으로 많은 고인용 논문의 지배를 억제한다.

**Recency**: 연도 기반 계단식 점수 — 1년 이내 1.0, 3년 이내 0.7, 5년 이내 0.5, 10년 이내 0.3, 그 이상 0.1.

이 4가지 신호를 통합하는 방식은 두 가지다. 기본은 **RRF (Reciprocal Rank Fusion)**. 각 신호로 독립 정렬한 뒤 `score(d) = Σ 1/(k + rank_i(d))` 공식(k=60)으로 합산한다. 특정 신호에 점수가 몰리는 것을 막고 각 관점에서 일관되게 높은 논문을 우선한다는 직관이다. arXiv 출처 논문에는 `source_boost = 0.15`를 추가로 가산한다.

Intent별로 weighted-sum 방식도 지원한다. `latest_research`는 `recency: 0.50`으로 최신성을 최우선한다. `survey`는 `citations: 0.40`으로 인용 수를 중시한다. `method_search`는 `semantic: 0.50`으로 의미 유사도에 집중한다.

| Intent | BM25 | Semantic | Citations | Recency |
|--------|------|----------|-----------|---------|
| `paper_search` | 0.35 | 0.35 | 0.15 | 0.15 |
| `latest_research` | 0.20 | 0.20 | 0.10 | 0.50 |
| `survey` | 0.15 | 0.15 | 0.40 | 0.30 |
| `method_search` | 0.30 | 0.50 | 0.10 | 0.10 |
| `comparison` | 0.30 | 0.40 | 0.20 | 0.10 |

### 4단계 중복 제거

다중 소스 검색에서 중복은 피할 수 없다. 같은 논문이 arXiv에도 있고 OpenAlex에도 있다. 우리는 4단계로 중복을 제거한다. 각 단계에서 중복으로 판정된 논문은 메타데이터가 풍부한 쪽을 대표로 삼고 나머지 필드를 병합한다.

1. **DOI 매칭**: 정규화된 DOI 완전 일치
2. **정규화 제목 매칭**: 소문자 + ASCII 변환 + 구두점 제거 후 완전 일치
3. **퍼지 제목 매칭**: 정규화 제목의 단어 수준 Jaccard 유사도 임계값 0.85 (길이 비율 0.80 이상인 경우만 비교)
4. **임베딩 코사인 유사도** (선택): 제목 임베딩 코사인 유사도 임계값 0.90

---

## 무엇이 부족했는가

처음 파이프라인을 배포하고 실제 사용 데이터를 보면서, 몇 가지 구조적인 문제가 눈에 들어오기 시작했다.

### 한 번의 검색으로는 충분하지 않다

"transformer 효율화 방법"을 검색했을 때, 우리는 주로 Attention 관련 논문을 잘 찾았다. 하지만 같은 주제를 "computational efficiency neural network", "low-rank approximation attention"으로 찾았을 때 나오는 논문들이 적지 않게 달랐다. 단일 쿼리는 자신의 관점에 갇혀 있다.

연구자가 논문을 검색할 때 실제로 하는 행동을 생각해 보자. 처음 검색을 하고 결과를 보면서 "아, 이 방향은 이미 많이 나왔고, 이 방향이 빠진 것 같은데"라고 판단한 후 다시 검색한다. 이것이 자연스러운 탐색 과정이다. 우리 시스템에는 이 **반성적 재검색**이 없었다.

### 타임아웃 구조의 문제

초기 파이프라인은 `_SEARCH_TIMEOUT = 120`초를 전체 파이프라인이 공유했다. 6개 소스 병렬 검색에 외부 API 지연이 겹치면 40-50초가 지나가고, 거기에 LLM 관련성 필터(`relevance_filter.filter_papers`)가 최대 45초를 추가로 사용하면 타임아웃이 빈번했다.

해결책은 타임아웃을 두 개의 독립된 버짓으로 분리하는 것이었다.

```python
_SOURCE_SEARCH_TIMEOUT = 60    # 멀티소스 검색 단계만
_RELEVANCE_FILTER_TIMEOUT = 45 # LLM 관련성 필터 단계만
```

관련성 필터가 타임아웃되어도 검색 자체는 graceful degradation으로 결과를 반환한다. 이 변경 이후 타임아웃 발생 빈도가 크게 줄었다.

### Recall 측정 부재

우리는 얼마나 많은 논문을 빠뜨리고 있는지 몰랐다. 정밀도(precision)는 반환된 논문이 관련 있는지를 보여주지만, 재현율(recall)은 관련 있는 논문 중 얼마나 찾았는지를 본다. 검색 시스템에서 recall이 떨어지는 것은 사용자가 인식하기 어렵다 — 찾지 못한 논문은 존재 자체를 모르기 때문이다.

---

## ArxivQA에서 배운 것

2023년 arXiv에 게재된 ArxivQA 논문(arxiv.org/abs/2309.01536)은 우리에게 중요한 관점 전환을 제공했다.

이 논문이 다루는 핵심 질문은 이것이다: 검색 에이전트를 강화학습으로 학습시킬 때, 어떤 reward를 주어야 하는가?

**RLVR의 실패**: outcome reward만 보는 방식 — "최종 답이 맞으면 +1, 틀리면 0" — 은 생각보다 불안정했다. 특히 긴 멀티턴 검색에서, 모델이 올바른 과정을 거쳤어도 마지막 답이 살짝 다르면 reward를 받지 못하고, 엉뚱한 방법으로 우연히 맞아도 reward를 받는 상황이 발생했다.

**RaR (Rubric-as-Reward)의 성공**: 결과가 아니라 과정을 평가하는 루브릭 기반 reward가 핵심이었다. 검색 결과 세트 전체를 다양성(Diversity), 포괄성(Thoroughness), 사려깊음(Thoughtfulness), 관련성(Relevance)의 4차원으로 평가하는 rubric을 reward로 삼자, 에이전트가 더 체계적인 검색 전략을 학습했다.

우리에게 주는 교훈은 명확했다: **결과만 보지 말고, 검색 과정을 평가하라.**

그리고 RL fine-tuning 없이도 이 아이디어를 적용할 수 있다는 것을 깨달았다. 프롬프트 엔지니어링으로 멀티턴 루프를 구현하고, RaR rubric을 inference-time 평가에 사용하면 된다.

---

## 우리의 접근: ReAct 멀티턴 검색 에이전트

`ReActSearchAgent`는 Search-R1의 `<search>→<result>→<think>→<search>` 루프를 RL fine-tuning 없이 프롬프트 엔지니어링으로 재현한 것이다. 핵심 코드 진입점은 `react_agent.search(query, analysis, max_results)`.

### 도구 설계

에이전트가 사용하는 도구는 4가지다.

- `keyword_search`: arXiv API 키워드 검색 (Turn 1 전용)
- `semantic_search`: OpenAlex API 자유 텍스트 검색
- `dblp_search`: DBLP 검색 (Turn 2+ 전용)
- `read_abstract`: arXiv ID로 초록 직접 조회 (필요 시)

중요한 점은 이 도구들이 새로운 인프라가 아니라는 것이다. 기존 `SearchAgent`의 `arxiv_searcher`, `openalex_searcher`, `dblp_searcher`를 async executor로 래핑했을 뿐이다. 기존 자산을 재활용하면서 에이전트 레이어를 추가한 것이다.

### 멀티턴 루프

전체 타임아웃은 `_TOTAL_TIMEOUT_SECONDS = 120`초. 최대 3턴이 기본값이다.

**Turn 1 — 다양화 쿼리로 초기 탐색**

먼저 `_build_initial_queries`가 `QueryAnalyzer`의 분석 결과(개선 쿼리, 키워드, 핵심 개념, research_area)를 조합해 3~5개의 초기 쿼리 후보를 만든다. 그리고 단어 수준 Jaccard 유사도 필터링을 적용한다.

```python
def _ensure_query_diversity(self, queries, threshold=0.5):
    diverse = []
    for candidate in queries:
        candidate_words = set(candidate.lower().split())
        is_redundant = False
        for existing in diverse:
            existing_words = set(existing.lower().split())
            union = candidate_words | existing_words
            jaccard = len(candidate_words & existing_words) / len(union)
            if jaccard >= threshold:
                is_redundant = True
                break
        if not is_redundant:
            diverse.append(candidate)
    return diverse
```

Jaccard 유사도가 0.5 이상인 쿼리는 중복으로 판정해 제거한다. 예를 들어 "transformer attention mechanism"과 "attention mechanism transformer"는 유사도가 높아 하나만 남는다. 반면 "transformer attention"과 "self-supervised pre-training"은 살아남는다.

Turn 1에서는 원본 쿼리로 arXiv 키워드 검색(rate limit 때문에 1회만)과 두 번째 다양화 쿼리로 OpenAlex 시맨틱 검색을 병렬 실행한다. 타임아웃은 40초.

**갭 분석 — LLM이 무엇이 부족한지 분석한다**

Turn 1이 끝나면, 지금까지 수집된 논문 목록(제목 + 연도, 토큰 절약을 위해 초록 제외)과 이전 턴 히스토리를 gpt-4o-mini에 제공하고 묻는다.

> "지금까지 찾은 논문들을 보면, 어떤 *유형*의 논문이 빠져 있나요? 그 gap을 채울 단일 쿼리를 제안해 주세요."

응답은 JSON 형식이다.

```json
{
  "is_sufficient": false,
  "missing": ["benchmark papers comparing methods", "survey on efficiency"],
  "next_query": "attention mechanism efficiency benchmark comparison",
  "rationale": "Found mostly theoretical papers, missing empirical benchmarks"
}
```

LLM 갭 분석 타임아웃은 20초. 타임아웃되거나 API 호출이 실패하면 `_fallback_plan`이 동작한다 — 초기 쿼리 목록 중 아직 사용하지 않은 것을 다음 쿼리로 사용한다.

**Turn 2 — 보완 검색, arXiv 제외**

갭 분석이 제안한 쿼리로 OpenAlex + DBLP를 병렬 검색한다. **arXiv를 제외하는 이유는 rate limit** 때문이다. arXiv API는 3.5초 간격 제한이 있어 Turn 1에서 이미 호출했다면 Turn 2에서 재호출하면 지연이 누적된다. OpenAlex와 DBLP는 이 제약이 없다. Turn 2+ 타임아웃은 30초.

**조기 종료 조건**

- 누적 논문 수가 `max_results * 1.5`를 초과하면 "충분하다" 판단
- LLM 갭 분석이 `is_sufficient: true` 반환
- 전체 120초 타임아웃 도달
- LLM 갭 분석 시간이 10초 미만 남은 경우

### 난이도 기반 전략 분기

모든 쿼리에 3턴 멀티턴을 실행하면 불필요하게 느리다. `classify_difficulty`가 분석 결과를 보고 3단계로 분류한다.

```python
def classify_difficulty(self, analysis):
    confidence = analysis.get("confidence", 0.5)
    intent = analysis.get("intent", "paper_search")
    keywords = analysis.get("keywords", [])

    if confidence >= 0.9 and intent in ("paper_search", "author_search") and len(keywords) <= 3:
        return "easy"
    if confidence < 0.7 or intent in ("topic_exploration", "survey", "comparison") or len(keywords) >= 7:
        return "hard"
    return "medium"
```

- **Easy**: confidence 0.9+, 단순 intent, 키워드 3개 이하 → `fast_mode` + 단일 검색이 적절
- **Medium**: 그 외 일반적인 경우 → 다양화 쿼리 3개, 2턴이 적절
- **Hard**: confidence 0.7 미만, 탐색형/서베이/비교 intent, 키워드 7개 이상 → 3턴 전체가 적절

현재 `/api/deep-search` 엔드포인트는 난이도와 무관하게 항상 `max_turns=3`으로 실행하고, 난이도는 메타데이터로 기록만 한다. 난이도별 전략 분기는 향후 최적화 과제다.

---

## Rubric 기반 결과 평가 (RaR-Implicit)

검색이 끝나면 `RubricEvaluator`가 결과 세트 전체를 평가한다. 개별 논문의 관련성이 아니라, 집합으로서의 품질을 본다.

### 4차원 루브릭

- **Diversity (다양성, 0-5)**: 결과가 서로 다른 하위 주제, 방법론, 관점을 커버하는가
- **Thoroughness (포괄성, 0-5)**: 해당 쿼리에서 기대되는 주요 측면들이 빠짐없이 포함되어 있는가
- **Thoughtfulness (사려깊음, 0-5)**: 기반 논문, 높은 임팩트 논문, 미래지향적 논문이 포함되어 있는가
- **Relevance (관련성, 0-5)**: 논문들이 실제로 쿼리 주제를 다루는가

LLM에 최대 15편의 논문(제목 + 초록 앞 200자)을 제공하고, 4차원 각각의 점수와 feedback, 그리고 전체 홀리스틱 점수(1-10)를 요청한다.

### 최종 점수 계산

ArxivQA RaR-Implicit 접근에서 영감을 받아 다음과 같이 설계했다.

```
holistic_normalized = (holistic_score - 1) / 9.0
weighted_score = Σ (dim_score / 5.0) × w_dim
overall_score = 0.6 × holistic_normalized + 0.4 × weighted_score
```

홀리스틱 점수(LLM의 직관적 전체 판단)에 60%, 가중 차원 합산에 40%를 배분한다. 이 비율은 ArxivQA의 rubric 기반 평가 프레임워크를 참고하되, 우리 시스템의 inference-time 평가에 맞게 조정한 것이다 (ArxivQA 원 논문의 length-penalty 항 lambda(L)은 훈련 시에만 사용되므로 제외했다).

### Intent별 차원 가중치

| Intent | Diversity | Thoroughness | Thoughtfulness | Relevance |
|--------|-----------|--------------|----------------|-----------|
| `paper_search` | 0.2 | 0.2 | 0.2 | **0.4** |
| `topic_exploration` | **0.3** | **0.3** | 0.2 | 0.2 |
| `survey` | 0.2 | **0.4** | 0.2 | 0.2 |
| `latest_research` | 0.1 | 0.1 | **0.3** | **0.5** |
| `method_search` | **0.3** | 0.2 | 0.1 | **0.4** |
| `comparison` | **0.4** | 0.2 | 0.2 | 0.2 |

`latest_research`는 관련성과 사려깊음(새로운 논문의 임팩트)을 중시하고, `comparison`은 다양성(비교할 대상이 다양하게 있는가)을 최우선한다.

### 충분성 판정 임계값

```python
SUFFICIENCY_THRESHOLDS = {
    "paper_search":     0.55,
    "topic_exploration": 0.65,
    "survey":            0.70,
    "latest_research":  0.55,
    "method_search":    0.60,
    "comparison":       0.65,
    "default":          0.60,
}
```

`survey` intent는 0.70으로 가장 엄격하다. 서베이 논문을 찾는 사용자에게는 포괄성이 중요하기 때문이다.

충분성 기준에 미달하면 `weakest_dimension`을 기반으로 보완 쿼리를 자동 생성한다.

```python
strategies = {
    "diversity":     f"{query} alternative methods approaches",
    "thoroughness":  f"{query} survey overview",
    "thoughtfulness":f"{query} analysis implications limitations",
    "relevance":     f'"{query}"',  # 따옴표로 정확도 높이기
}
```

---

## 타임아웃 아키텍처: 실제 구현

`/api/deep-search` 엔드포인트는 다음 순서로 실행된다.

```
QueryAnalyzer.analyze_query()       — 10초 버짓
  ↓
ReActSearchAgent.search()           — 120초 버짓
  ├── Turn 1: arXiv + OpenAlex      — 최대 40초
  ├── LLM Gap Analysis              — 최대 20초
  ├── Turn 2: OpenAlex + DBLP       — 최대 30초
  └── (Turn 3 필요 시)               — 최대 30초
  ↓
RubricEvaluator.evaluate()          — 15초 버짓
```

`/api/search` 엔드포인트(기본 검색)의 타임아웃 구조는 이렇다.

```python
_SEARCH_TIMEOUT = 120           # 전체 파이프라인
_SOURCE_SEARCH_TIMEOUT = 60     # 멀티소스 검색 단계
_RELEVANCE_FILTER_TIMEOUT = 45  # LLM 관련성 필터 단계
```

소스 검색이 60초 내에 끝나도 관련성 필터 45초는 독립적으로 집계된다. 필터가 타임아웃되면 필터링되지 않은 원본 결과를 반환한다 — 사용자가 에러 페이지를 보는 것보다 품질이 약간 낮더라도 결과를 받는 편이 낫다.

---

## 결과

`/api/deep-search` 엔드포인트를 프로덕션 환경에서 테스트한 결과다.

### 실제 실행 예시

쿼리: `"efficient transformer attention mechanisms for long sequences"`

```
Turn 1 (39.2s):
  keyword_search("efficient transformer attention long sequences"):  8편
  semantic_search("attention mechanism computational efficiency"):    7편
  cumulative: 15편

Gap Analysis (7.8s):
  missing: ["linear attention methods", "hardware-aware optimization papers"]
  next_query: "linear attention approximation FlashAttention hardware"

Turn 2 (22.1s):
  semantic_search("linear attention approximation FlashAttention hardware"): 6편
  dblp_search("linear attention approximation FlashAttention hardware"):     4편
  cumulative: 25편

Deduplication: 25 → 18편
Total elapsed: 71.4s
```

Rubric 평가 결과:

| Dimension | Score | Feedback |
|-----------|-------|---------|
| Diversity | 3/5 | Methods covered but missing hardware-level optimization angle |
| Thoroughness | 4/5 | Key sub-topics well-represented |
| Thoughtfulness | 4/5 | Foundational and recent papers both present |
| Relevance | 5/5 | All papers directly address long-sequence attention |
| Holistic | 7/10 | — |

```
# method_search 가중치: diversity=0.3, thoroughness=0.2, thoughtfulness=0.1, relevance=0.4
overall_score = 0.6 × (7-1)/9 + 0.4 × (0.3×3/5 + 0.2×4/5 + 0.1×4/5 + 0.4×5/5)
             = 0.6 × 0.667 + 0.4 × 0.820
             = 0.400 + 0.328
             = 0.728
```

`method_search` intent의 충분성 임계값 0.60을 초과하므로 `is_sufficient = True`. `weakest_dimension = "diversity"` (4차원 중 원점수 3/5로 가장 낮음) — 필요하다면 `"efficient transformer attention mechanisms for long sequences alternative methods approaches"` 쿼리로 보완 검색 가능.

단일 검색이었다면 Turn 1의 15편에서 멈췄을 것이다. 멀티턴 덕분에 linear attention과 FlashAttention 계열 논문을 추가로 발굴했고, 중복 제거 후 18편이 최종 결과로 남았다.

---

## 아직 남은 과제

### 검색 에이전트 RL Fine-tuning

지금의 `ReActSearchAgent`는 RL로 학습된 것이 아니다. 프롬프트 엔지니어링으로 ArxivQA의 패턴을 모방했을 뿐이다. 진짜 다음 단계는 ArxivQA의 원래 제안처럼 강화학습으로 에이전트를 학습시키는 것이다.

우리가 구상하는 스택: **Qwen3-8B + SkyRL-Agent + GRPO + RaR**. Rubric 점수를 process reward로 사용하고, GRPO (Group Relative Policy Optimization)로 정책을 업데이트한다. 작은 모델(8B)로 전문화된 검색 에이전트를 만들 수 있다면, gpt-4o-mini 의존성을 낮출 수 있다.

이 방향에서 핵심 난제는 **RaR reward 신호의 희소성**이다. 멀티턴 검색의 각 중간 단계를 어떻게 평가할 것인가? 마지막 Turn 3 결과에만 rubric을 적용하면 Turn 1, 2의 좋은 결정에 reward가 전달되지 않는다. 이 credit assignment 문제는 해결 중이다.

### 사용자 피드백 기반 학습

사용자가 검색 결과에서 특정 논문을 클릭하거나 북마크하면 positive signal이 생긴다. 현재는 이 신호를 수집만 하고 랭킹에 반영하지 않는다. 클릭 데이터를 implicit reward로 활용해 `HybridRanker`의 intent별 가중치를 온라인으로 업데이트하는 것이 가능한 방향이다.

문제는 **노이즈**다. 클릭은 제목이 매력적이어서 일어나기도 하고, 실제로 관련이 있어서 일어나기도 한다. position bias(상위에 있어서 클릭)도 있다. 이 신호를 그대로 쓰면 오히려 품질이 하락할 수 있다.

### 초록 기반 정밀 재랭킹

현재 `HybridRanker`의 semantic 점수는 초록의 앞 8000자(characters)를 임베딩으로 변환해 유사도를 계산한다. 하지만 LLM이 초록을 직접 읽고 관련성을 판단하는 것과는 다르다. Top-20 논문의 초록 전문을 LLM에 제공하고 "이 논문이 쿼리에 얼마나 깊이 관련 있는지" 평가하는 **Cross-Encoder 재랭킹** 단계를 추가하면 정밀도가 크게 높아질 것으로 예상한다.

비용 문제가 있다. 20편 × 초록당 400 토큰 = 8000 토큰 입력을 매 검색마다 LLM에 넣으면 요금이 누적된다. 캐싱과 배치 처리, 또는 더 작은 reranker 모델 활용이 필요하다.

---

## 열린 질문

시스템을 만들면서 계속 마음에 걸리는 질문이 있다.

**멀티턴 검색의 수렴을 어떻게 알 수 있는가?** 우리는 지금 "충분한 논문 수 확보"와 "LLM이 sufficient라 판단"이라는 두 가지 종료 조건을 사용한다. 하지만 이 두 조건 모두 실질적인 커버리지를 보장하지 않는다. 정말로 주제 공간을 충분히 탐색했다는 것을 어떻게 정량적으로 확인할 수 있을까? 새로 찾은 논문이 이미 아는 논문과 임베딩 공간에서 충분히 멀어질 때까지 계속 검색하는 novelty-driven 종료 조건을 실험 중이다.

**언어 간 검색의 불균형을 어떻게 해결할 것인가?** 한국어 논문과 영어 논문이 동일한 주제를 다루더라도 임베딩 공간에서 거리가 멀다. 현재는 OpenAlex Korean 소스를 별도로 운영하지만, 진정한 의미의 cross-lingual recall을 달성하려면 다국어 임베딩 모델이나 번역 기반 쿼리 확장이 필요하다.

그리고 가장 근본적인 질문: **검색 에이전트가 만든 결과물을 어떻게 평가해야 하는가?** RaR rubric은 유용한 프레임이지만, 결국 LLM이 LLM 결과를 평가하는 구조다. 사람이 직접 평가한 gold standard 없이는 자기충족적 편향에 빠질 수 있다. 집현전 사용자들의 검색 세션을 분석해 gold standard를 만드는 작업을 시작했다. 아직 갈 길이 멀다.

---

## 참고문헌

- Yao, S. et al. (2023). *ReAct: Synergizing Reasoning and Acting in Language Models*. ICLR 2023.
- Jin, Z. et al. (2025). *Search-R1: Training LLMs to Reason and Leverage Search Engines with Reinforcement Learning*. arxiv.org/abs/2503.09516.
- Peng, B. et al. (2023). *ArxivQA: Long-form Question Answering on arXiv Papers*. arxiv.org/abs/2309.01536.
- Ma, X. et al. (2023). *Fine-Tuning LLaMA for Multi-Stage Text Retrieval*. arxiv.org/abs/2310.08319.
- Gao, L. et al. (2023). *Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE)*. ACL 2023.
- Cormack, G.V. et al. (2009). *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*. SIGIR 2009.
