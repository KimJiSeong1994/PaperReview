# 집현전 검색 에이전트: 단일 쿼리의 한계를 넘어서

*6개 학술 데이터베이스를 병렬로 검색하고, 결과를 분석해 부족한 부분을 스스로 보완하는 멀티턴 검색 에이전트를 구축한 이야기.*

작성: 집현전 팀 · 13분 읽기
태그: #검색에이전트 #ReAct #HybridRanking #RaR

---

## 논문 검색이 어려운 이유

논문을 쓰거나 리뷰할 때, 관련 문헌을 빠짐없이 찾는 일은 생각보다 어렵다. "transformer attention mechanism"을 검색하면 핵심 논문은 나온다. 하지만 비슷한 문제를 다른 용어로 접근한 논문, 최근 후속 연구, 관련 벤치마크 논문은 첫 검색에 거의 잡히지 않는다.

원인은 세 가지로 압축된다.

- **용어 불일치**: 같은 개념이 `self-attention`과 `scaled dot-product attention`처럼 다르게 표현된다. 한국어 검색에서는 상황이 더 심각하다.
- **데이터베이스 편향**: arXiv는 CS/ML에 강하지만 생의학은 약하고, Google Scholar는 고인용 논문에 강하지만 최신 프리프린트에 느리다. 한 곳만 보면 반드시 빠뜨린다.
- **단일 검색의 커버리지 한계**: 아무리 좋은 쿼리라도 한 번으로 주제 공간 전체를 커버하기 어렵다. 서베이 논문과 방법론 논문은 다른 키워드로 찾아야 한다.

우리는 [집현전(jiphyeonjeon.kr)](https://jiphyeonjeon.kr) 서비스의 검색 인프라를 점진적으로 발전시키며 이 문제를 풀어왔다. 이 글은 그 과정에서 무엇이 실패했고, 무엇이 작동했는지 솔직하게 정리한 기록이다.

---

## 첫 번째 파이프라인: 6소스 병렬 검색



<div style="margin:24px 0;text-align:center;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1040 460" width="1040" height="460" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif">
  <defs>
    <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#6b7280" />
    </marker>
    <!-- Row 1 gradients -->
    <linearGradient id="grad-query" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#1e3a5f;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#1e40af;stop-opacity:1" />
    </linearGradient>
    <linearGradient id="grad-analyzer" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#1e3a5f;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#2563eb;stop-opacity:1" />
    </linearGradient>
    <linearGradient id="grad-search" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#1e3365;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#7c3aed;stop-opacity:1" />
    </linearGradient>
    <linearGradient id="grad-dedup" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#064e3b;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#059669;stop-opacity:1" />
    </linearGradient>
    <linearGradient id="grad-ranker" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#78350f;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#d97706;stop-opacity:1" />
    </linearGradient>
    <linearGradient id="grad-react" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#164e63;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#0891b2;stop-opacity:1" />
    </linearGradient>
    <linearGradient id="grad-rubric" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#4c1d95;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#7c3aed;stop-opacity:1" />
    </linearGradient>
    <linearGradient id="grad-result" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#1e3a5f;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#1d4ed8;stop-opacity:1" />
    </linearGradient>
  </defs>

  <!-- Background -->
  <rect width="1040" height="460" fill="#0f0f0f" rx="16"/>

  <!-- Title -->
  <text x="520" y="34" text-anchor="middle" fill="#f3f4f6" font-size="15" font-weight="700" letter-spacing="0.5">검색 에이전트 파이프라인 아키텍처</text>

  <!-- ===== ROW 1: User Query → QueryAnalyzer → 6소스 병렬 검색 ===== -->

  <!-- Node 1: User Query -->
  <rect x="30" y="58" width="140" height="56" rx="12" fill="url(#grad-query)" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="100" y="81" text-anchor="middle" fill="#93c5fd" font-size="13" font-weight="700">User Query</text>
  <text x="100" y="100" text-anchor="middle" fill="#bfdbfe" font-size="11">자연어 입력</text>

  <!-- Arrow 1→2 -->
  <line x1="170" y1="86" x2="208" y2="86" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arrowhead)"/>

  <!-- Node 2: QueryAnalyzer -->
  <rect x="210" y="58" width="200" height="56" rx="12" fill="url(#grad-analyzer)" stroke="#60a5fa" stroke-width="1.5"/>
  <text x="310" y="78" text-anchor="middle" fill="#bfdbfe" font-size="13" font-weight="700">QueryAnalyzer</text>
  <text x="310" y="96" text-anchor="middle" fill="#93c5fd" font-size="10.5">Intent 분류 (8종) + improved_query</text>

  <!-- Arrow 2→3 -->
  <line x1="410" y1="86" x2="448" y2="86" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arrowhead)"/>

  <!-- Node 3: 6소스 병렬 검색 -->
  <rect x="450" y="58" width="240" height="56" rx="12" fill="url(#grad-search)" stroke="#a78bfa" stroke-width="1.5"/>
  <text x="570" y="78" text-anchor="middle" fill="#ddd6fe" font-size="13" font-weight="700">6소스 병렬 검색</text>
  <text x="570" y="96" text-anchor="middle" fill="#c4b5fd" font-size="10.5">arXiv · Scholar · OpenAlex · DBLP · Connected · Korean</text>

  <!-- Arrow 3→4 -->
  <line x1="690" y1="86" x2="728" y2="86" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arrowhead)"/>

  <!-- Node 4: 4단계 중복 제거 -->
  <rect x="730" y="58" width="280" height="56" rx="12" fill="url(#grad-dedup)" stroke="#34d399" stroke-width="1.5"/>
  <text x="870" y="78" text-anchor="middle" fill="#a7f3d0" font-size="13" font-weight="700">4단계 중복 제거</text>
  <text x="870" y="96" text-anchor="middle" fill="#6ee7b7" font-size="10.5">DOI → 제목 → Jaccard(0.85) → 임베딩(0.90)</text>

  <!-- ===== Vertical arrow from row 1 to row 2 ===== -->
  <!-- Down arrow from right end of row 1 to row 2 right end -->
  <!-- We'll use a bent path: right side of Node4 → bend down → Node5 right end -->
  <path d="M 870 114 L 870 150" stroke="#6b7280" stroke-width="1.5" fill="none" marker-end="url(#arrowhead)"/>

  <!-- ===== ROW 2: HybridRanker → ReAct Agent → RubricEvaluator → Results ===== -->

  <!-- Node 5: HybridRanker -->
  <rect x="730" y="152" width="280" height="68" rx="12" fill="url(#grad-ranker)" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="870" y="173" text-anchor="middle" fill="#fde68a" font-size="13" font-weight="700">HybridRanker</text>
  <text x="870" y="191" text-anchor="middle" fill="#fcd34d" font-size="10.5">BM25 + Semantic (HyDE) + Citations + Recency</text>
  <text x="870" y="208" text-anchor="middle" fill="#fbbf24" font-size="10.5" font-weight="600">→ Reciprocal Rank Fusion (RRF)</text>

  <!-- Arrow 5→6 (right to left) -->
  <line x1="730" y1="186" x2="692" y2="186" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arrowhead)"/>

  <!-- Node 6: ReAct Agent -->
  <rect x="450" y="152" width="240" height="68" rx="12" fill="url(#grad-react)" stroke="#22d3ee" stroke-width="1.5"/>
  <text x="570" y="173" text-anchor="middle" fill="#a5f3fc" font-size="13" font-weight="700">ReAct Agent</text>
  <text x="570" y="191" text-anchor="middle" fill="#67e8f9" font-size="10.5">Turn 1 → Gap Analysis → Turn 2 → Turn 3</text>
  <text x="570" y="208" text-anchor="middle" fill="#22d3ee" font-size="10.5">멀티턴 반복 검색 (예산 기반)</text>

  <!-- Arrow 6→7 -->
  <line x1="450" y1="186" x2="412" y2="186" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arrowhead)"/>

  <!-- Node 7: RubricEvaluator -->
  <rect x="210" y="152" width="200" height="68" rx="12" fill="url(#grad-rubric)" stroke="#a78bfa" stroke-width="1.5"/>
  <text x="310" y="173" text-anchor="middle" fill="#ddd6fe" font-size="13" font-weight="700">RubricEvaluator</text>
  <text x="310" y="191" text-anchor="middle" fill="#c4b5fd" font-size="10.5">Diversity · Thoroughness</text>
  <text x="310" y="208" text-anchor="middle" fill="#c4b5fd" font-size="10.5">Thoughtfulness · Relevance</text>

  <!-- Arrow 7→8 -->
  <line x1="210" y1="186" x2="172" y2="186" stroke="#6b7280" stroke-width="1.5" marker-end="url(#arrowhead)"/>

  <!-- Node 8: Ranked Results -->
  <rect x="30" y="152" width="140" height="68" rx="12" fill="url(#grad-result)" stroke="#60a5fa" stroke-width="1.5"/>
  <text x="100" y="178" text-anchor="middle" fill="#bfdbfe" font-size="13" font-weight="700">Ranked</text>
  <text x="100" y="196" text-anchor="middle" fill="#bfdbfe" font-size="13" font-weight="700">Results</text>
  <text x="100" y="213" text-anchor="middle" fill="#93c5fd" font-size="10.5">최종 순위 논문</text>

  <!-- ===== DETAIL CALLOUTS — Row 3 ===== -->
  <!-- Search sources detail -->
  <rect x="450" y="262" width="240" height="52" rx="8" fill="#1a1a2e" stroke="#4c1d95" stroke-width="1" stroke-dasharray="4,3"/>
  <text x="570" y="280" text-anchor="middle" fill="#a78bfa" font-size="10" font-weight="600">병렬 검색 세부</text>
  <text x="570" y="296" text-anchor="middle" fill="#8b5cf6" font-size="9.5">arXiv API · Google Scholar · OpenAlex</text>
  <text x="570" y="311" text-anchor="middle" fill="#8b5cf6" font-size="9.5">DBLP · Connected Papers · Korean DB</text>
  <line x1="570" y1="230" x2="570" y2="262" stroke="#4c1d95" stroke-width="1" stroke-dasharray="3,3"/>

  <!-- ReAct loop callout -->
  <rect x="730" y="262" width="280" height="52" rx="8" fill="#1a1a2e" stroke="#0e7490" stroke-width="1" stroke-dasharray="4,3"/>
  <text x="870" y="280" text-anchor="middle" fill="#22d3ee" font-size="10" font-weight="600">ReAct 루프 예산</text>
  <text x="870" y="296" text-anchor="middle" fill="#67e8f9" font-size="9.5">Turn 1: 40s · Gap Analysis: 20s</text>
  <text x="870" y="311" text-anchor="middle" fill="#67e8f9" font-size="9.5">Turn 2: 30s · Turn 3: 20s (선택적)</text>
  <line x1="870" y1="230" x2="870" y2="262" stroke="#0e7490" stroke-width="1" stroke-dasharray="3,3"/>

  <!-- RRF callout -->
  <rect x="210" y="262" width="200" height="52" rx="8" fill="#1a1a2e" stroke="#92400e" stroke-width="1" stroke-dasharray="4,3"/>
  <text x="310" y="280" text-anchor="middle" fill="#fbbf24" font-size="10" font-weight="600">RRF 가중치</text>
  <text x="310" y="296" text-anchor="middle" fill="#fcd34d" font-size="9.5">BM25: 0.3 · Semantic: 0.4</text>
  <text x="310" y="311" text-anchor="middle" fill="#fcd34d" font-size="9.5">Citations: 0.2 · Recency: 0.1</text>
  <line x1="310" y1="230" x2="310" y2="262" stroke="#92400e" stroke-width="1" stroke-dasharray="3,3"/>

  <!-- ===== Flow direction labels ===== -->
  <!-- Row 1 direction label -->
  <text x="520" y="46" text-anchor="middle" fill="#4b5563" font-size="10" letter-spacing="2">— — — — — — — — — — FORWARD PASS — — — — — — — — — —</text>

  <!-- Row 2 direction label -->
  <rect x="450" y="345" width="540" height="1" fill="#1f2937"/>
  <text x="170" y="370" text-anchor="middle" fill="#4b5563" font-size="10">EVALUATION</text>
  <text x="570" y="370" text-anchor="middle" fill="#4b5563" font-size="10">SEARCH</text>
  <text x="870" y="370" text-anchor="middle" fill="#4b5563" font-size="10">RANKING</text>

  <!-- Legend -->
  <rect x="30" y="390" width="980" height="54" rx="8" fill="#111827" stroke="#1f2937" stroke-width="1"/>
  <text x="60" y="410" fill="#9ca3af" font-size="10" font-weight="600">범례</text>
  <rect x="100" y="400" width="12" height="12" rx="3" fill="#1d4ed8"/>
  <text x="116" y="410" fill="#9ca3af" font-size="9.5">쿼리/결과</text>
  <rect x="185" y="400" width="12" height="12" rx="3" fill="#2563eb"/>
  <text x="201" y="410" fill="#9ca3af" font-size="9.5">분석</text>
  <rect x="240" y="400" width="12" height="12" rx="3" fill="#7c3aed"/>
  <text x="256" y="410" fill="#9ca3af" font-size="9.5">검색</text>
  <rect x="295" y="400" width="12" height="12" rx="3" fill="#059669"/>
  <text x="311" y="410" fill="#9ca3af" font-size="9.5">중복제거</text>
  <rect x="370" y="400" width="12" height="12" rx="3" fill="#d97706"/>
  <text x="386" y="410" fill="#9ca3af" font-size="9.5">랭킹</text>
  <rect x="425" y="400" width="12" height="12" rx="3" fill="#0891b2"/>
  <text x="441" y="410" fill="#9ca3af" font-size="9.5">ReAct</text>
  <rect x="490" y="400" width="12" height="12" rx="3" fill="#7c3aed"/>
  <text x="506" y="410" fill="#9ca3af" font-size="9.5">평가</text>

  <text x="60" y="434" fill="#6b7280" font-size="9">* 화살표 방향: Row 1은 좌→우, Row 2는 우→좌 (U자형 파이프라인)</text>
  <text x="600" y="434" fill="#a5b4fc" font-size="9" font-weight="600">집현전 (Jiphyeonjeon) Search Agent v2.0</text>
</svg>
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 1. 집현전 검색 에이전트 전체 아키텍처 — QueryAnalyzer부터 RubricEvaluator까지의 파이프라인 흐름</em></p>
</div>
출발 아이디어는 단순했다. "여러 소스를 동시에 검색하면 커버리지가 올라갈 것이다." arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers, OpenAlex Korean -- 6개 데이터베이스를 동시에 호출하고, 결과를 모아 랭킹한다.

### QueryAnalyzer: 쿼리를 이해하는 첫 번째 레이어

검색에 앞서 `QueryAnalyzer`가 사용자의 의도를 파악한다. `paper_search`, `topic_exploration`, `method_search`, `survey` 등 8가지 intent로 분류하며, 분류는 `gpt-4o-mini`에 위임하고 결과를 캐싱해 반복 호출 비용을 줄인다. LLM을 쓸 수 없을 때는 키워드 규칙 기반 fallback이 동작한다.

분석 결과에는 `improved_query`도 포함되는데, 여기서 원칙은 보수적이다. 오타 수정, 약어 확장 정도만 허용한다. LLM이 원래 의도에 없던 컨텍스트를 추가해 검색 품질이 오히려 떨어지는 상황을 여러 번 경험했기 때문이다.

그래서 이중 guardrail을 유지한다. 프롬프트 수준에서 쿼리 길이를 원본의 1.5배 이내로 제한하고, 코드 수준에서는 confidence가 낮거나 원본과 어간 겹침이 50% 미만이면 개선 쿼리를 폐기한다.

### 하이브리드 랭킹: BM25 + Semantic + Citations + Recency

6개 소스에서 수집된 논문은 중복 제거를 거쳐 `HybridRanker`로 넘어간다. 랭킹은 4가지 신호를 조합한다.

- **BM25 (sparse)**: 키워드 매칭. 제목에 가중을 둔다.
- **Semantic (dense)**: 코사인 유사도. **HyDE**가 활성화되면 LLM이 가상 초록을 생성해 쿼리 벡터를 보강한다.
- **Citations**: log 정규화로 고인용 논문의 지배를 억제한다.
- **Recency**: 연도 기반 계단식 점수 (1년 이내 1.0 ~ 10년 초과 0.1).

이 신호를 통합하는 기본 방식은 **RRF (Reciprocal Rank Fusion)** 다. 각 신호로 독립 정렬한 뒤 순위 역수를 합산하므로, 특정 신호에 점수가 몰리지 않고 여러 관점에서 고르게 높은 논문이 우선된다.

Intent별로 가중치를 달리하는 weighted-sum 방식도 지원한다. 예를 들어 `latest_research`는 최신성(0.50)을, `survey`는 인용 수(0.40)를, `method_search`는 의미 유사도(0.50)를 최우선한다.

### 4단계 중복 제거

다중 소스 검색에서 중복은 불가피하다. 같은 논문이 arXiv에도, OpenAlex에도 있다. 이를 4단계로 제거한다: DOI 완전 일치 -> 정규화 제목 완전 일치 -> 퍼지 제목 매칭(Jaccard 0.85) -> 임베딩 코사인 유사도(0.90). 중복으로 판정되면 메타데이터가 풍부한 쪽을 대표로 삼고 나머지 필드를 병합한다.

이 파이프라인으로 커버리지는 확실히 올라갔다. 하지만 프로덕션에 올린 뒤, 예상 못한 한계가 드러나기 시작했다.

---

## 무엇이 부족했는가

### 한 번의 검색으로는 충분하지 않다

"transformer 효율화 방법"을 검색하면 Attention 관련 논문은 잘 나왔다. 하지만 같은 주제를 "computational efficiency neural network"이나 "low-rank approximation attention"으로 검색하면 결과가 상당히 달랐다. 단일 쿼리는 자신의 관점에 갇혀 있었다.

연구자가 실제로 하는 행동을 떠올려 보자. 첫 검색 결과를 훑고 "이 방향은 많이 나왔는데, 저 방향이 빠졌군" 판단한 후 다시 검색한다. 우리 시스템에는 이 **반성적 재검색**이 없었다.

### 타임아웃 구조의 문제

초기 파이프라인은 120초 타임아웃을 전체 파이프라인이 공유했다. 6개 소스 병렬 검색에 40-50초, LLM 관련성 필터에 최대 45초 -- 이 둘이 겹치면 타임아웃이 빈번했다.

해결책은 검색 단계(60초)와 필터 단계(45초)의 타임아웃을 분리하는 것이었다. 필터가 타임아웃되더라도 필터링 없는 원본 결과를 반환하도록 graceful degradation을 적용했고, 타임아웃 발생 빈도가 크게 줄었다.

### Recall 측정 부재

가장 불안한 점은 얼마나 많은 논문을 빠뜨리고 있는지 모른다는 것이었다. 정밀도(precision)는 "찾은 논문이 관련 있는가"를 보여주지만, 재현율(recall)은 "관련 논문 중 얼마나 찾았는가"를 본다. 못 찾은 논문은 존재 자체를 모르기 때문에, recall 문제는 사용자에게 보이지 않는다.

---

## ArxivQA에서 배운 것

이 세 가지 한계를 어떻게 극복할까 고민하던 중, ArxivQA 논문(arxiv.org/abs/2309.01536)이 관점 전환을 제공했다. 핵심 질문은 이것이었다: 검색 에이전트를 강화학습으로 학습시킬 때, 어떤 reward를 주어야 하는가?

**outcome reward는 불안정했다.** "최종 답이 맞으면 +1, 틀리면 0"이라는 단순한 보상은 멀티턴 검색에서 문제가 됐다. 올바른 과정을 거쳤어도 마지막 답이 살짝 다르면 보상을 받지 못하고, 엉뚱한 방법으로 우연히 맞아도 보상을 받았다.

**RaR (Rubric-as-Reward)는 달랐다.** 결과가 아니라 과정을 평가하는 루브릭 기반 reward를 도입하자, 에이전트가 체계적인 검색 전략을 학습하기 시작했다. 검색 결과 세트를 다양성, 포괄성, 사려깊음, 관련성의 4차원으로 평가하는 것이 핵심이다.

교훈은 명확했다: **결과만 보지 말고, 검색 과정을 평가하라.** 그리고 RL fine-tuning 없이도 프롬프트 엔지니어링으로 멀티턴 루프를 구현하고, RaR rubric을 inference-time 평가에 사용할 수 있다는 것을 깨달았다.

---

## 우리의 접근: ReAct 멀티턴 검색 에이전트

그래서 만든 것이 `ReActSearchAgent`다. Search-R1의 `<search>-><result>-><think>-><search>` 루프를 RL fine-tuning 없이 프롬프트 엔지니어링으로 재현했다.

### 도구 설계

에이전트가 사용하는 도구는 `keyword_search`(arXiv), `semantic_search`(OpenAlex), `dblp_search`(DBLP), `read_abstract`(arXiv ID 직접 조회)의 4가지다. 새로운 인프라가 아니라 기존 `SearchAgent`의 검색기를 async executor로 래핑한 것이므로, 기존 자산 위에 에이전트 레이어만 얹은 셈이다.

### 멀티턴 루프



<div style="margin:24px 0;text-align:center;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 620 740" width="620" height="740" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif">
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#6b7280" />
    </marker>
    <marker id="arrow-orange" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#f59e0b" />
    </marker>
    <linearGradient id="turn1-bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#0f1b35;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#1e3a5f;stop-opacity:1" />
    </linearGradient>
    <linearGradient id="gap-bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#1c1008;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#451a03;stop-opacity:1" />
    </linearGradient>
    <linearGradient id="turn2-bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#13102b;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#2e1065;stop-opacity:1" />
    </linearGradient>
    <linearGradient id="result-bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#052e16;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#14532d;stop-opacity:1" />
    </linearGradient>
  </defs>

  <!-- Background -->
  <rect width="620" height="740" fill="#0f0f0f" rx="16"/>

  <!-- Title -->
  <text x="310" y="36" text-anchor="middle" fill="#f3f4f6" font-size="15" font-weight="700">멀티턴 ReAct 검색 루프</text>
  <text x="310" y="56" text-anchor="middle" fill="#6b7280" font-size="11">예산 기반 반복 검색 · LLM Gap 분석 · 누적 결과 관리</text>

  <!-- ================================================================ -->
  <!-- TURN 1 CARD -->
  <!-- ================================================================ -->
  <rect x="30" y="72" width="560" height="168" rx="14" fill="url(#turn1-bg)" stroke="#3b82f6" stroke-width="2"/>

  <!-- Turn 1 header bar -->
  <rect x="30" y="72" width="560" height="36" rx="14" fill="#1d4ed8" opacity="0.7"/>
  <rect x="30" y="92" width="560" height="16" fill="#1d4ed8" opacity="0.7"/>
  <text x="52" y="96" fill="#bfdbfe" font-size="13" font-weight="700">Turn 1</text>
  <rect x="120" y="82" width="1" height="16" fill="#3b82f6" opacity="0.5"/>
  <text x="134" y="96" fill="#93c5fd" font-size="11">예산: 40s</text>
  <!-- clock icon simulation -->
  <circle cx="540" cy="89" r="8" fill="none" stroke="#60a5fa" stroke-width="1.5"/>
  <line x1="540" y1="84" x2="540" y2="89" stroke="#60a5fa" stroke-width="1.5"/>
  <line x1="540" y1="89" x2="545" y2="89" stroke="#60a5fa" stroke-width="1.5"/>
  <text x="526" y="89" text-anchor="end" fill="#60a5fa" font-size="10">40s</text>

  <!-- Query line -->
  <text x="52" y="125" fill="#9ca3af" font-size="11">Query:</text>
  <text x="100" y="125" fill="#e2e8f0" font-size="11" font-weight="600">"transformer attention"</text>

  <!-- Search results - tree structure -->
  <!-- Branch line -->
  <line x1="64" y1="140" x2="64" y2="200" stroke="#374151" stroke-width="1.5"/>

  <!-- keyword_search branch -->
  <line x1="64" y1="150" x2="82" y2="150" stroke="#374151" stroke-width="1.5"/>
  <rect x="84" y="140" width="210" height="22" rx="5" fill="#1e3a5f" stroke="#3b82f6" stroke-width="1"/>
  <text x="94" y="154" fill="#93c5fd" font-size="10.5" font-weight="600">keyword_search</text>
  <text x="208" y="154" fill="#6b7280" font-size="10">(arXiv)</text>
  <rect x="315" y="141" width="60" height="20" rx="4" fill="#1e40af"/>
  <text x="345" y="154" text-anchor="middle" fill="#bfdbfe" font-size="10.5" font-weight="700">8편 수집</text>

  <!-- semantic_search branch -->
  <line x1="64" y1="178" x2="82" y2="178" stroke="#374151" stroke-width="1.5"/>
  <rect x="84" y="168" width="210" height="22" rx="5" fill="#1e3a5f" stroke="#3b82f6" stroke-width="1"/>
  <text x="94" y="182" fill="#93c5fd" font-size="10.5" font-weight="600">semantic_search</text>
  <text x="208" y="182" fill="#6b7280" font-size="10">(OpenAlex)</text>
  <rect x="315" y="169" width="60" height="20" rx="4" fill="#1e40af"/>
  <text x="345" y="182" text-anchor="middle" fill="#bfdbfe" font-size="10.5" font-weight="700">7편 수집</text>

  <!-- Accumulation line -->
  <line x1="64" y1="200" x2="64" y2="215" stroke="#374151" stroke-width="1.5"/>
  <line x1="64" y1="215" x2="82" y2="215" stroke="#374151" stroke-width="1.5"/>

  <!-- Cumulative result -->
  <rect x="84" y="205" width="280" height="24" rx="6" fill="#0f2845" stroke="#2563eb" stroke-width="1.5"/>
  <text x="96" y="220" fill="#7dd3fc" font-size="11" font-weight="600">누적:</text>
  <text x="130" y="220" fill="#e2e8f0" font-size="11" font-weight="700">15편</text>
  <text x="158" y="220" fill="#6b7280" font-size="11">(중복 제거 전)</text>

  <!-- ================================================================ -->
  <!-- ARROW 1 + TIME LABEL -->
  <!-- ================================================================ -->
  <line x1="310" y1="240" x2="310" y2="278" stroke="#6b7280" stroke-width="2" marker-end="url(#arrow)"/>
  <rect x="230" y="246" width="160" height="24" rx="6" fill="#1c1f26" stroke="#374151" stroke-width="1"/>
  <text x="310" y="261" text-anchor="middle" fill="#9ca3af" font-size="10.5">40s 완료 → Gap Analysis 시작</text>

  <!-- ================================================================ -->
  <!-- GAP ANALYSIS CARD -->
  <!-- ================================================================ -->
  <rect x="30" y="280" width="560" height="118" rx="14" fill="url(#gap-bg)" stroke="#f59e0b" stroke-width="2"/>

  <!-- Gap header bar -->
  <rect x="30" y="280" width="560" height="36" rx="14" fill="#92400e" opacity="0.6"/>
  <rect x="30" y="300" width="560" height="16" fill="#92400e" opacity="0.6"/>
  <!-- LLM icon -->
  <rect x="46" y="282" width="22" height="22" rx="5" fill="#fbbf24" opacity="0.2" stroke="#fbbf24" stroke-width="1"/>
  <text x="57" y="297" text-anchor="middle" fill="#fbbf24" font-size="9" font-weight="700">LLM</text>
  <text x="76" y="297" fill="#fde68a" font-size="13" font-weight="700">Gap Analysis</text>
  <text x="200" y="297" fill="#d97706" font-size="11">· 20s budget</text>
  <circle cx="540" cy="290" r="8" fill="none" stroke="#f59e0b" stroke-width="1.5"/>
  <line x1="540" y1="285" x2="540" y2="290" stroke="#f59e0b" stroke-width="1.5"/>
  <line x1="540" y1="290" x2="544" y2="290" stroke="#f59e0b" stroke-width="1.5"/>

  <!-- Gap content -->
  <text x="52" y="328" fill="#9ca3af" font-size="11">분석:</text>
  <text x="90" y="328" fill="#fcd34d" font-size="11" font-weight="600">"linear attention 관련 방법론이 부족합니다"</text>

  <text x="52" y="352" fill="#9ca3af" font-size="11">next_query:</text>
  <rect x="120" y="340" width="305" height="22" rx="5" fill="#1c1008" stroke="#d97706" stroke-width="1"/>
  <text x="130" y="354" fill="#fbbf24" font-size="11" font-weight="600">"linear attention FlashAttn efficient"</text>

  <!-- continuation -->
  <text x="52" y="381" fill="#6b7280" font-size="10.5">coverage_score: 0.43 &lt; 임계값(0.70) → 추가 턴 필요</text>

  <!-- ================================================================ -->
  <!-- ARROW 2 + TIME LABEL -->
  <!-- ================================================================ -->
  <line x1="310" y1="398" x2="310" y2="436" stroke="#6b7280" stroke-width="2" marker-end="url(#arrow)"/>
  <rect x="230" y="404" width="160" height="24" rx="6" fill="#1c1f26" stroke="#374151" stroke-width="1"/>
  <text x="310" y="419" text-anchor="middle" fill="#9ca3af" font-size="10.5">20s 완료 → Turn 2 시작</text>

  <!-- ================================================================ -->
  <!-- TURN 2 CARD -->
  <!-- ================================================================ -->
  <rect x="30" y="438" width="560" height="176" rx="14" fill="url(#turn2-bg)" stroke="#8b5cf6" stroke-width="2"/>

  <!-- Turn 2 header bar -->
  <rect x="30" y="438" width="560" height="36" rx="14" fill="#5b21b6" opacity="0.7"/>
  <rect x="30" y="458" width="560" height="16" fill="#5b21b6" opacity="0.7"/>
  <text x="52" y="462" fill="#ddd6fe" font-size="13" font-weight="700">Turn 2</text>
  <rect x="120" y="448" width="1" height="16" fill="#7c3aed" opacity="0.5"/>
  <text x="134" y="462" fill="#c4b5fd" font-size="11">예산: 30s</text>
  <circle cx="540" cy="455" r="8" fill="none" stroke="#8b5cf6" stroke-width="1.5"/>
  <line x1="540" y1="450" x2="540" y2="455" stroke="#8b5cf6" stroke-width="1.5"/>
  <line x1="540" y1="455" x2="544" y2="455" stroke="#8b5cf6" stroke-width="1.5"/>
  <text x="526" y="455" text-anchor="end" fill="#8b5cf6" font-size="10">30s</text>

  <!-- Query line -->
  <text x="52" y="491" fill="#9ca3af" font-size="11">Query:</text>
  <text x="100" y="491" fill="#e2e8f0" font-size="11" font-weight="600">"linear attention FlashAttn efficient..."</text>

  <!-- Branch line -->
  <line x1="64" y1="505" x2="64" y2="560" stroke="#374151" stroke-width="1.5"/>

  <!-- semantic_search branch -->
  <line x1="64" y1="516" x2="82" y2="516" stroke="#374151" stroke-width="1.5"/>
  <rect x="84" y="506" width="210" height="22" rx="5" fill="#2e1065" stroke="#7c3aed" stroke-width="1"/>
  <text x="94" y="520" fill="#c4b5fd" font-size="10.5" font-weight="600">semantic_search</text>
  <text x="208" y="520" fill="#6b7280" font-size="10">(OpenAlex)</text>
  <rect x="315" y="507" width="60" height="20" rx="4" fill="#4c1d95"/>
  <text x="345" y="520" text-anchor="middle" fill="#ddd6fe" font-size="10.5" font-weight="700">6편 수집</text>

  <!-- dblp_search branch -->
  <line x1="64" y1="545" x2="82" y2="545" stroke="#374151" stroke-width="1.5"/>
  <rect x="84" y="535" width="210" height="22" rx="5" fill="#2e1065" stroke="#7c3aed" stroke-width="1"/>
  <text x="94" y="549" fill="#c4b5fd" font-size="10.5" font-weight="600">dblp_search</text>
  <text x="182" y="549" fill="#6b7280" font-size="10">(DBLP)</text>
  <rect x="315" y="536" width="60" height="20" rx="4" fill="#4c1d95"/>
  <text x="345" y="549" text-anchor="middle" fill="#ddd6fe" font-size="10.5" font-weight="700">4편 수집</text>

  <!-- Dedup result -->
  <line x1="64" y1="560" x2="64" y2="578" stroke="#374151" stroke-width="1.5"/>
  <line x1="64" y1="578" x2="82" y2="578" stroke="#374151" stroke-width="1.5"/>
  <rect x="84" y="568" width="380" height="34" rx="6" fill="#1a0a35" stroke="#6d28d9" stroke-width="1.5"/>
  <text x="96" y="582" fill="#a78bfa" font-size="11" font-weight="600">누적: 25편</text>
  <text x="164" y="582" fill="#6b7280" font-size="11">→ 중복 제거</text>
  <text x="96" y="596" fill="#7c3aed" font-size="10.5">Jaccard(0.85) + 임베딩(0.90) 적용</text>
  <text x="280" y="596" fill="#c4b5fd" font-size="11" font-weight="700">→ 최종 18편</text>

  <!-- ================================================================ -->
  <!-- ARROW 3 -->
  <!-- ================================================================ -->
  <line x1="310" y1="614" x2="310" y2="650" stroke="#10b981" stroke-width="2" marker-end="url(#arrow)"/>

  <!-- ================================================================ -->
  <!-- FINAL RESULT CARD -->
  <!-- ================================================================ -->
  <rect x="30" y="652" width="560" height="68" rx="14" fill="url(#result-bg)" stroke="#10b981" stroke-width="2"/>
  <rect x="30" y="652" width="560" height="34" rx="14" fill="#059669" opacity="0.4"/>
  <rect x="30" y="672" width="560" height="14" fill="#059669" opacity="0.4"/>

  <!-- checkmark icon -->
  <circle cx="56" cy="665" r="10" fill="#059669" opacity="0.3" stroke="#10b981" stroke-width="1.5"/>
  <polyline points="50,665 54,670 63,659" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>

  <text x="76" y="669" fill="#a7f3d0" font-size="13" font-weight="700">검색 완료</text>
  <text x="170" y="669" fill="#6b7280" font-size="11">· coverage_score: 0.78 ≥ 임계값(0.70)</text>

  <text x="52" y="695" fill="#34d399" font-size="12" font-weight="700">결과: 18편</text>
  <text x="118" y="695" fill="#9ca3af" font-size="11">최종 논문</text>

  <!-- time badges -->
  <rect x="350" y="657" width="90" height="22" rx="6" fill="#052e16" stroke="#059669" stroke-width="1"/>
  <text x="395" y="671" text-anchor="middle" fill="#6ee7b7" font-size="11" font-weight="600">총 71.4초</text>
  <rect x="452" y="657" width="120" height="22" rx="6" fill="#052e16" stroke="#059669" stroke-width="1"/>
  <text x="512" y="671" text-anchor="middle" fill="#6ee7b7" font-size="11" font-weight="600">2턴 완료</text>

  <!-- Footer note -->
  <text x="310" y="731" text-anchor="middle" fill="#4b5563" font-size="9.5">* Turn 3은 coverage_score가 여전히 낮을 경우 20s 추가 예산으로 실행됨</text>
</svg>
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 2. ReAct 멀티턴 검색 루프 — Turn 1 초기 탐색 → Gap Analysis → Turn 2 보완 검색</em></p>
</div>
전체 타임아웃은 `_TOTAL_TIMEOUT_SECONDS = 120`초. 최대 3턴이 기본값이다.

**Turn 1 — 다양화 쿼리로 초기 탐색**

먼저 `_build_initial_queries`가 `QueryAnalyzer`의 분석 결과를 조합해 3~5개의 초기 쿼리 후보를 만든다. 그리고 단어 수준 Jaccard 유사도로 중복을 걸러낸다 -- 유사도 0.5 이상이면 제거한다. "transformer attention mechanism"과 "attention mechanism transformer"는 하나만 남고, "transformer attention"과 "self-supervised pre-training"은 둘 다 살아남는 식이다.

Turn 1에서는 원본 쿼리로 arXiv 키워드 검색(rate limit 때문에 1회만)과 두 번째 다양화 쿼리로 OpenAlex 시맨틱 검색을 병렬 실행한다. 타임아웃은 40초.

**갭 분석 — LLM이 무엇이 부족한지 분석한다**

Turn 1이 끝나면, 수집된 논문 목록(제목 + 연도)을 gpt-4o-mini에 제공하고 묻는다: "어떤 유형의 논문이 빠져 있는가? 그 gap을 채울 쿼리를 제안하라." LLM은 부족한 영역(`missing`)과 보완 쿼리(`next_query`)를 JSON으로 반환한다.

타임아웃(20초) 내에 응답이 오지 않으면 fallback이 동작한다 -- 초기 쿼리 중 아직 사용하지 않은 것을 다음 쿼리로 사용한다.

**Turn 2 — 보완 검색, arXiv 제외**

갭 분석이 제안한 쿼리로 OpenAlex + DBLP를 병렬 검색한다. arXiv는 rate limit(3.5초 간격) 때문에 Turn 1에서만 호출하고, Turn 2부터는 제외한다. Turn 2+ 타임아웃은 30초.

**조기 종료 조건**

- 누적 논문 수가 `max_results * 1.5`를 초과하면 "충분하다" 판단
- LLM 갭 분석이 `is_sufficient: true` 반환
- 전체 120초 타임아웃 도달
- LLM 갭 분석 시간이 10초 미만 남은 경우

### 난이도 기반 전략 분기

모든 쿼리에 3턴을 돌리면 불필요하게 느리다. `classify_difficulty`가 confidence, intent, 키워드 수를 보고 난이도를 3단계로 분류한다.

- **Easy** (confidence 높고 단순 intent): 단일 검색으로 충분
- **Medium** (일반적 경우): 다양화 쿼리 3개, 2턴
- **Hard** (탐색형/서베이/비교 intent): 3턴 전체 실행

현재 `/api/deep-search`는 난이도와 무관하게 항상 3턴을 실행하고, 난이도는 메타데이터로 기록만 한다. 난이도별 전략 분기는 향후 과제다.

---

## Rubric 기반 결과 평가 (RaR-Implicit)

검색이 끝나면 `RubricEvaluator`가 결과 세트 전체를 평가한다. 개별 논문이 아니라, **집합으로서의 품질**을 본다.

### 4차원 루브릭



<div style="margin:24px 0;text-align:center;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 620 340" width="620" height="340" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif">
  <defs>
    <!-- Bar gradients: score-based color (low=orange, high=green) -->
    <!-- Diversity 3/5 = 60% — amber/yellow -->
    <linearGradient id="bar-diversity" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" style="stop-color:#d97706;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#fbbf24;stop-opacity:1" />
    </linearGradient>
    <!-- Thoroughness 4/5 = 80% — teal/green -->
    <linearGradient id="bar-thoroughness" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" style="stop-color:#059669;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#34d399;stop-opacity:1" />
    </linearGradient>
    <!-- Thoughtfulness 4/5 = 80% — cyan -->
    <linearGradient id="bar-thoughtfulness" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" style="stop-color:#0891b2;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#22d3ee;stop-opacity:1" />
    </linearGradient>
    <!-- Relevance 5/5 = 100% — indigo/purple -->
    <linearGradient id="bar-relevance" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" style="stop-color:#4f46e5;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#818cf8;stop-opacity:1" />
    </linearGradient>
    <!-- Overall score gradient -->
    <linearGradient id="overall-grad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" style="stop-color:#059669;stop-opacity:1" />
      <stop offset="72.8%" style="stop-color:#34d399;stop-opacity:1" />
      <stop offset="72.8%" style="stop-color:#374151;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#374151;stop-opacity:1" />
    </linearGradient>
  </defs>

  <!-- Background -->
  <rect width="620" height="340" fill="#0f0f0f" rx="16"/>

  <!-- Title -->
  <text x="310" y="36" text-anchor="middle" fill="#f3f4f6" font-size="15" font-weight="700">RaR Rubric 평가 — 4차원 품질 검증</text>
  <text x="310" y="56" text-anchor="middle" fill="#6b7280" font-size="11">Reflection-after-Retrieval · 검색 결과 자가 평가</text>

  <!-- ======================================================= -->
  <!-- BAR CHART AREA -->
  <!-- Left labels start at x=30, bars start at x=190, max width=340 -->
  <!-- ======================================================= -->

  <!-- Grid lines (subtle) -->
  <line x1="190" y1="68" x2="190" y2="258" stroke="#1f2937" stroke-width="1"/>
  <!-- 20% = 68px -->
  <line x1="258" y1="68" x2="258" y2="258" stroke="#1f2937" stroke-width="1" stroke-dasharray="3,3"/>
  <!-- 40% = 136px -->
  <line x1="326" y1="68" x2="326" y2="258" stroke="#1f2937" stroke-width="1" stroke-dasharray="3,3"/>
  <!-- 60% = 204px -->
  <line x1="394" y1="68" x2="394" y2="258" stroke="#1f2937" stroke-width="1" stroke-dasharray="3,3"/>
  <!-- 80% = 272px -->
  <line x1="462" y1="68" x2="462" y2="258" stroke="#1f2937" stroke-width="1" stroke-dasharray="3,3"/>
  <!-- 100% = 340px -->
  <line x1="530" y1="68" x2="530" y2="258" stroke="#374151" stroke-width="1"/>

  <!-- Grid labels -->
  <text x="190" y="264" text-anchor="middle" fill="#4b5563" font-size="9">0</text>
  <text x="258" y="264" text-anchor="middle" fill="#4b5563" font-size="9">1</text>
  <text x="326" y="264" text-anchor="middle" fill="#4b5563" font-size="9">2</text>
  <text x="394" y="264" text-anchor="middle" fill="#4b5563" font-size="9">3</text>
  <text x="462" y="264" text-anchor="middle" fill="#4b5563" font-size="9">4</text>
  <text x="530" y="264" text-anchor="middle" fill="#4b5563" font-size="9">5</text>
  <text x="360" y="276" text-anchor="middle" fill="#374151" font-size="9">점수 (5점 만점)</text>

  <!-- ======= ROW 1: Diversity 3/5 = 60% = 204px ======= -->
  <text x="180" y="96" text-anchor="end" fill="#e5e7eb" font-size="12.5" font-weight="600">Diversity</text>
  <text x="180" y="111" text-anchor="end" fill="#6b7280" font-size="9.5">다양성</text>
  <!-- Bar background -->
  <rect x="190" y="82" width="340" height="32" rx="6" fill="#1f2937"/>
  <!-- Bar fill: 3/5 = 204px -->
  <rect x="190" y="82" width="204" height="32" rx="6" fill="url(#bar-diversity)"/>
  <!-- Score pip markers -->
  <rect x="190" y="82" width="204" height="32" rx="6" fill="url(#bar-diversity)"/>
  <!-- Segment dividers (subtle) -->
  <line x1="258" y1="84" x2="258" y2="112" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <line x1="326" y1="84" x2="326" y2="112" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <line x1="394" y1="84" x2="394" y2="112" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <!-- Score label -->
  <text x="402" y="102" fill="#fde68a" font-size="13" font-weight="700">3 / 5</text>
  <!-- percentage -->
  <text x="480" y="102" fill="#d97706" font-size="11">60%</text>
  <!-- Description tag -->
  <rect x="512" y="87" width="40" height="16" rx="4" fill="#78350f"/>
  <text x="532" y="98" text-anchor="middle" fill="#fcd34d" font-size="9" font-weight="600">보통</text>

  <!-- ======= ROW 2: Thoroughness 4/5 = 80% = 272px ======= -->
  <text x="180" y="142" text-anchor="end" fill="#e5e7eb" font-size="12.5" font-weight="600">Thoroughness</text>
  <text x="180" y="157" text-anchor="end" fill="#6b7280" font-size="9.5">철저함</text>
  <rect x="190" y="128" width="340" height="32" rx="6" fill="#1f2937"/>
  <rect x="190" y="128" width="272" height="32" rx="6" fill="url(#bar-thoroughness)"/>
  <line x1="258" y1="130" x2="258" y2="158" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <line x1="326" y1="130" x2="326" y2="158" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <line x1="394" y1="130" x2="394" y2="158" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <line x1="462" y1="130" x2="462" y2="158" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <text x="470" y="148" fill="#a7f3d0" font-size="13" font-weight="700">4 / 5</text>
  <text x="547" y="148" fill="#059669" font-size="11">80%</text>
  <rect x="560" y="133" width="40" height="16" rx="4" fill="#064e3b"/>
  <text x="580" y="144" text-anchor="middle" fill="#6ee7b7" font-size="9" font-weight="600">양호</text>

  <!-- ======= ROW 3: Thoughtfulness 4/5 = 80% = 272px ======= -->
  <text x="180" y="188" text-anchor="end" fill="#e5e7eb" font-size="12.5" font-weight="600">Thoughtfulness</text>
  <text x="180" y="203" text-anchor="end" fill="#6b7280" font-size="9.5">통찰력</text>
  <rect x="190" y="174" width="340" height="32" rx="6" fill="#1f2937"/>
  <rect x="190" y="174" width="272" height="32" rx="6" fill="url(#bar-thoughtfulness)"/>
  <line x1="258" y1="176" x2="258" y2="204" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <line x1="326" y1="176" x2="326" y2="204" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <line x1="394" y1="176" x2="394" y2="204" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <line x1="462" y1="176" x2="462" y2="204" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <text x="470" y="194" fill="#a5f3fc" font-size="13" font-weight="700">4 / 5</text>
  <text x="547" y="194" fill="#0891b2" font-size="11">80%</text>
  <rect x="560" y="179" width="40" height="16" rx="4" fill="#164e63"/>
  <text x="580" y="190" text-anchor="middle" fill="#67e8f9" font-size="9" font-weight="600">양호</text>

  <!-- ======= ROW 4: Relevance 5/5 = 100% = 340px ======= -->
  <text x="180" y="234" text-anchor="end" fill="#e5e7eb" font-size="12.5" font-weight="600">Relevance</text>
  <text x="180" y="249" text-anchor="end" fill="#6b7280" font-size="9.5">관련성</text>
  <rect x="190" y="220" width="340" height="32" rx="6" fill="#1f2937"/>
  <rect x="190" y="220" width="340" height="32" rx="6" fill="url(#bar-relevance)"/>
  <line x1="258" y1="222" x2="258" y2="250" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <line x1="326" y1="222" x2="326" y2="250" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <line x1="394" y1="222" x2="394" y2="250" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <line x1="462" y1="222" x2="462" y2="250" stroke="#0f0f0f" stroke-width="1" opacity="0.4"/>
  <!-- Full bar, score at right edge -->
  <text x="536" y="240" fill="#c7d2fe" font-size="13" font-weight="700">5 / 5</text>
  <!-- percentage inside bar (bar is full, so just show in a lighter shade) -->
  <text x="480" y="240" fill="#e0e7ff" font-size="11">100%</text>
  <rect x="560" y="225" width="40" height="16" rx="4" fill="#312e81"/>
  <text x="580" y="236" text-anchor="middle" fill="#a5b4fc" font-size="9" font-weight="600">최고</text>

  <!-- ======================================================= -->
  <!-- OVERALL SCORE SECTION -->
  <!-- ======================================================= -->
  <rect x="30" y="284" width="560" height="44" rx="10" fill="#111827" stroke="#1f2937" stroke-width="1.5"/>

  <!-- Overall bar (full width track) -->
  <rect x="220" y="294" width="280" height="14" rx="4" fill="#1f2937"/>
  <!-- 72.8% of 280 = ~204px -->
  <rect x="220" y="294" width="204" height="14" rx="4" fill="url(#overall-grad)"/>
  <!-- Threshold marker at 60% = 168px -->
  <line x1="388" y1="290" x2="388" y2="312" stroke="#f59e0b" stroke-width="2"/>
  <text x="388" y="287" text-anchor="middle" fill="#f59e0b" font-size="8.5">임계값 0.60</text>

  <text x="44" y="306" fill="#9ca3af" font-size="11" font-weight="600">Overall Score:</text>
  <text x="148" y="306" fill="#a5b4fc" font-size="14" font-weight="700">0.728</text>

  <!-- Pass badge -->
  <rect x="512" y="291" width="62" height="22" rx="6" fill="#059669" opacity="0.3" stroke="#10b981" stroke-width="1.5"/>
  <text x="543" y="305" text-anchor="middle" fill="#34d399" font-size="11" font-weight="700">PASS ✓</text>

  <!-- Score formula detail -->
  <text x="44" y="322" fill="#4b5563" font-size="9.5">(3×0.2 + 4×0.3 + 4×0.25 + 5×0.25) / 5 = 0.728</text>
  <text x="350" y="322" fill="#374151" font-size="9">method_search 임계값: 0.60</text>
</svg>
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 3. RaR-Implicit Rubric 4차원 평가 결과 — method_search intent 기준</em></p>
</div>
- **Diversity (다양성)**: 서로 다른 하위 주제와 방법론을 커버하는가
- **Thoroughness (포괄성)**: 기대되는 주요 측면이 빠짐없이 포함되어 있는가
- **Thoughtfulness (사려깊음)**: 기반 논문, 고임팩트 논문, 미래지향적 논문이 있는가
- **Relevance (관련성)**: 실제로 쿼리 주제를 다루는가

LLM에 최대 15편(제목 + 초록 앞 200자)을 제공하고, 4차원 각 점수(0-5)와 전체 홀리스틱 점수(1-10)를 요청한다.

### 최종 점수 계산

ArxivQA RaR-Implicit에서 영감을 받아, 최종 점수는 홀리스틱 점수(LLM의 전체 직관)에 60%, 가중 차원 합산에 40%를 배분해 산출한다. `overall = 0.6 * holistic_norm + 0.4 * weighted_dim_score` 형태다.

### Intent별 차원 가중치

차원 가중치는 intent에 따라 달라진다. `latest_research`는 관련성(0.5)과 사려깊음(0.3)을, `comparison`은 다양성(0.4)을, `survey`는 포괄성(0.4)을 최우선한다. 검색 의도에 맞는 평가가 가능해진다.

### 충분성 판정

Intent별로 충분성 임계값이 다르다. `survey`는 0.70으로 가장 엄격하고(포괄성이 중요하므로), `paper_search`는 0.55로 비교적 관대하다.

기준에 미달하면 가장 약한 차원(`weakest_dimension`)에 맞춰 보완 쿼리를 자동 생성한다. 예를 들어 다양성이 약하면 "alternative methods approaches"를, 포괄성이 약하면 "survey overview"를 쿼리에 덧붙인다.

---

## 타임아웃 아키텍처

`/api/deep-search`의 실행 흐름과 각 단계의 타임아웃 버짓은 다음과 같다.

```
QueryAnalyzer (10s) -> ReActSearchAgent (120s) -> RubricEvaluator (15s)
                         ├─ Turn 1: arXiv+OpenAlex (40s)
                         ├─ Gap Analysis (20s)
                         ├─ Turn 2: OpenAlex+DBLP (30s)
                         └─ Turn 3 (필요 시, 30s)
```

기본 검색(`/api/search`)도 검색 단계(60초)와 관련성 필터 단계(45초)를 독립 버짓으로 운영한다. 필터가 타임아웃되면 필터링 없는 원본 결과를 반환한다 -- 에러 페이지보다 품질이 약간 낮은 결과가 낫다는 판단이다.

---

## 결과

프로덕션에서 실행한 구체적인 사례를 보자.

### 실행 예시: "efficient transformer attention mechanisms for long sequences"

**Turn 1** (39초): arXiv 키워드 검색 8편 + OpenAlex 시맨틱 검색 7편 = 15편 수집.

**Gap Analysis** (8초): LLM이 "linear attention 방법론"과 "하드웨어 최적화 논문"이 빠져 있다고 판단. 보완 쿼리 `"linear attention approximation FlashAttention hardware"` 제안.

**Turn 2** (22초): OpenAlex 6편 + DBLP 4편 추가 수집. 중복 제거 후 최종 **18편**, 총 71초 소요.

Rubric 평가에서 Relevance 5/5, Thoroughness 4/5, Thoughtfulness 4/5, Diversity 3/5를 받았다. 최종 점수 0.728로 `method_search` 충분성 임계값(0.60)을 초과해 검색을 종료했다. 가장 약한 차원은 Diversity -- 필요하다면 "alternative methods" 방향으로 보완 검색할 수 있다.

단일 검색이었다면 Turn 1의 15편에서 멈췄을 것이다. 멀티턴 덕분에 linear attention과 FlashAttention 계열 논문을 추가로 발굴했다.

---

## 아직 남은 과제

### 검색 에이전트 RL Fine-tuning

지금의 `ReActSearchAgent`는 프롬프트 엔지니어링으로 ArxivQA의 패턴을 모방한 것이지, RL로 학습된 것이 아니다. 다음 단계는 강화학습으로 에이전트를 직접 학습시키는 것이다.

구상 중인 스택은 **Qwen3-8B + GRPO + RaR**이다. Rubric 점수를 process reward로, GRPO로 정책을 업데이트한다. 8B급 모델로 전문 검색 에이전트를 만들 수 있다면 gpt-4o-mini 의존성을 낮출 수 있다.

핵심 난제는 **credit assignment**다. 마지막 Turn에만 rubric을 적용하면 Turn 1, 2의 좋은 결정에 reward가 전달되지 않는다.

### 사용자 피드백 기반 학습

사용자가 특정 논문을 클릭하거나 북마크하면 positive signal이 생긴다. 현재는 수집만 하고 랭킹에 반영하지 않지만, 이를 implicit reward로 활용해 가중치를 온라인 업데이트하는 것이 가능한 방향이다.

다만 클릭 데이터는 노이즈가 크다. 제목이 매력적이어서, 상위에 노출되어서 등 관련성과 무관한 이유로 클릭이 발생한다. 신호를 그대로 쓰면 오히려 품질이 하락할 수 있다.

### 초록 기반 정밀 재랭킹

현재 semantic 점수는 임베딩 유사도 기반이다. Top-20 논문의 초록을 LLM이 직접 읽고 관련성을 판단하는 **Cross-Encoder 재랭킹**을 추가하면 정밀도가 크게 높아질 것으로 예상한다.

비용이 걸림돌이다. 매 검색마다 약 8,000 토큰을 LLM에 입력해야 하므로, 캐싱이나 경량 reranker 모델의 활용이 필요하다.

---

## 열린 질문

시스템을 만들면서 계속 마음에 걸리는 질문들이 있다.

**멀티턴 검색은 언제 수렴하는가?** 현재 종료 조건은 "충분한 논문 수 확보"와 "LLM이 sufficient 판단" 두 가지인데, 둘 다 실질적 커버리지를 보장하지 않는다. 새로 찾은 논문이 기존 결과와 임베딩 공간에서 충분히 멀어질 때까지 탐색하는 novelty-driven 종료 조건을 실험 중이다.

**언어 간 검색 불균형은?** 한국어와 영어 논문이 같은 주제를 다뤄도 임베딩 공간에서 거리가 멀다. 다국어 임베딩 모델이나 번역 기반 쿼리 확장이 필요하다.

**LLM이 LLM을 평가하는 구조는 괜찮은가?** RaR rubric은 유용하지만, 결국 자기 평가다. 사람이 직접 평가한 gold standard 없이는 자기충족적 편향에 빠질 수 있다. 사용자 검색 세션을 분석해 gold standard를 만드는 작업을 시작했지만, 아직 갈 길이 멀다.

---

## 참고문헌

- Yao, S. et al. (2023). *ReAct: Synergizing Reasoning and Acting in Language Models*. ICLR 2023.
- Jin, Z. et al. (2025). *Search-R1: Training LLMs to Reason and Leverage Search Engines with Reinforcement Learning*. arxiv.org/abs/2503.09516.
- Peng, B. et al. (2023). *ArxivQA: Long-form Question Answering on arXiv Papers*. arxiv.org/abs/2309.01536.
- Ma, X. et al. (2023). *Fine-Tuning LLaMA for Multi-Stage Text Retrieval*. arxiv.org/abs/2310.08319.
- Gao, L. et al. (2023). *Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE)*. ACL 2023.
- Cormack, G.V. et al. (2009). *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*. SIGIR 2009.
