# 집현전 검색 에이전트: 멀티턴 ReAct 기반 학술 논문 검색 시스템

논문을 쓰거나 리뷰할 때, 관련 문헌을 빠짐없이 찾는 일은 생각보다 어렵다. "transformer attention mechanism"을 검색하면 핵심 논문은 나온다. 하지만 비슷한 문제를 다른 용어로 접근한 논문, 최근 후속 연구, 관련 벤치마크 논문은 첫 검색에 거의 잡히지 않는다.

원인은 세 가지로 압축된다.

- **용어 불일치**: 같은 개념이 `self-attention`과 `scaled dot-product attention`처럼 다르게 표현된다. 한국어 검색에서는 상황이 더 심각하다.
- **데이터베이스 편향**: arXiv는 CS/ML에 강하지만 생의학은 약하고, Google Scholar는 고인용 논문에 강하지만 최신 프리프린트에 느리다. 한 곳만 보면 반드시 빠뜨린다.
- **단일 검색의 커버리지 한계**: 아무리 좋은 쿼리라도 한 번으로 주제 공간 전체를 커버하기 어렵다. 서베이 논문과 방법론 논문은 다른 키워드로 찾아야 한다.

우리는 [집현전(jiphyeonjeon.kr)](https://jiphyeonjeon.kr) 서비스의 검색 인프라를 점진적으로 발전시키며 이 문제들을 해결했다. 6개 학술 데이터베이스를 병렬로 검색하고, LLM 기반 갭 분석을 통해 부족한 영역을 자율적으로 보완하는 멀티턴 검색 에이전트를 만들었다.

---

## 한 번의 검색으로는 부족했다

초기 시스템은 6개 소스 병렬 검색과 하이브리드 랭킹으로 커버리지를 확보했으나, 프로덕션 운영 과정에서 세 가지 한계가 드러났다.

**한 번의 검색으로는 충분하지 않다.** "transformer 효율화 방법"을 검색하면 Attention 관련 논문은 잘 나왔다. 하지만 같은 주제를 "computational efficiency neural network"이나 "low-rank approximation attention"으로 검색하면 결과가 상당히 달랐다. 단일 쿼리는 자신의 관점에 갇혀 있었다. 연구자가 실제로 하는 행동은 첫 검색 결과를 훑고 "이 방향은 많이 나왔는데, 저 방향이 빠졌군" 판단한 후 다시 검색하는 것이다. 우리 시스템에는 이 **반성적 재검색**이 없었다.

**타임아웃 구조의 문제.** 초기 파이프라인은 120초 타임아웃을 전체 파이프라인이 공유했다. 6개 소스 병렬 검색에 40-50초, LLM 관련성 필터에 최대 45초가 소요되어 타임아웃이 빈번했다.

**Recall 측정 부재.** 가장 불안한 점은 얼마나 많은 논문을 빠뜨리고 있는지 모른다는 것이었다. 정밀도(precision)는 "찾은 논문이 관련 있는가"를 보여주지만, 재현율(recall)은 "관련 논문 중 얼마나 찾았는가"를 본다. 못 찾은 논문은 존재 자체를 모르기 때문에, recall 문제는 사용자에게 보이지 않는다.

---

## 무엇이 부족했는가

이 문제들을 해결하기 위해 기존 연구에서 영감을 받았다.

ReAct 프레임워크(Yao et al., 2023)는 추론(Reasoning)과 행동(Acting)을 교차하여 LLM의 과제 수행 능력을 향상시키는 패러다임이다. 우리는 이 패러다임을 검색 도메인에 특화하여, 검색 도구 호출과 갭 분석을 교차 실행하는 멀티턴 에이전트를 구현했다.

Search-R1(Jin et al., 2025)은 `search -> result -> think -> search` 루프를 통해 LLM이 검색 엔진과 상호작용하며 추론하는 프레임워크를 제안했다. 우리의 ReAct 멀티턴 루프는 이 패러다임을 RL fine-tuning 없이 프롬프트 엔지니어링으로 재현한 것이다.

ArxivQA 논문(Peng et al., 2023)에서는 검색 에이전트 학습에서 reward 설계의 중요성이 드러났다. Outcome reward("최종 답이 맞으면 +1, 틀리면 0")는 멀티턴 검색에서 불안정했다. 올바른 과정을 거쳤어도 마지막 답이 살짝 다르면 보상을 받지 못하고, 엉뚱한 방법으로 우연히 맞아도 보상을 받았다. 이에 대한 대안으로 **RaR(Rubric-as-Reward)** 방식이 제안되었다. 결과가 아니라 과정을 평가하는 루브릭 기반 reward를 도입하자, 에이전트가 체계적인 검색 전략을 학습하기 시작했다. 우리는 이 RaR 루브릭을 RL fine-tuning 없이 inference-time 평가에 적용했다.

하이브리드 검색 쪽에서는 HyDE(Gao et al., 2023)가 LLM이 생성한 가상 문서를 쿼리 벡터로 활용하여 zero-shot dense retrieval 성능을 향상시켰고, RRF(Cormack et al., 2009)가 여러 독립 랭킹의 순위 역수를 합산하여 특정 신호에 편향되지 않는 통합 랭킹을 만들었다. 우리 시스템은 이 두 가지를 모두 활용한다.

---

## 쿼리를 이해하는 것부터 시작한다

<div style="margin:24px 0;text-align:center;">
<img src="/api/blog/figures/fig_query_analyzer.png" alt="QueryAnalyzer 쿼리 분석" style="width:100%;max-width:960px;height:auto;border-radius:8px;" />
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 1. QueryAnalyzer -- 쿼리 의도 분류 및 confidence 기반 개선 과정. 사용자 쿼리를 8가지 intent로 분류하고, 이중 guardrail을 통해 쿼리 개선의 안전성을 보장한다.</em></p>
</div>

검색에 앞서 `QueryAnalyzer`가 사용자의 의도를 파악한다. `paper_search`, `topic_exploration`, `method_search`, `survey` 등 8가지 intent로 분류하며, 분류는 `gpt-4o-mini`에 위임하고 결과를 캐싱해 반복 호출 비용을 줄인다. LLM을 쓸 수 없을 때는 키워드 규칙 기반 fallback이 동작한다.

분석 결과에는 `improved_query`도 포함되는데, 여기서 원칙은 보수적이다. 오타 수정, 약어 확장 정도만 허용한다. LLM이 원래 의도에 없던 컨텍스트를 추가해 검색 품질이 오히려 떨어지는 상황을 여러 번 경험했기 때문이다.

그래서 이중 guardrail을 유지한다. 프롬프트 수준에서 쿼리 길이를 원본의 1.5배 이내로 제한하고, 코드 수준에서는 confidence가 낮거나 원본과 어간 겹침이 50% 미만이면 개선 쿼리를 폐기한다.

## 4개 신호를 결합하는 하이브리드 랭킹

<div style="margin:24px 0;text-align:center;">
<img src="/api/blog/figures/fig_hybrid_ranker.png" alt="HybridRanker 4신호 결합" style="width:100%;max-width:960px;height:auto;border-radius:8px;" />
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 2. HybridRanker -- BM25, Semantic, Citations, Recency 4가지 독립 신호를 RRF로 결합하여 최종 순위를 산출한다. Intent에 따라 weighted-sum 모드로 전환 가능하다.</em></p>
</div>

6개 소스에서 수집된 논문은 중복 제거를 거쳐 `HybridRanker`로 넘어간다. 랭킹은 4가지 신호를 조합한다.

- **BM25 (sparse)**: 키워드 매칭. 제목에 가중을 둔다.
- **Semantic (dense)**: 코사인 유사도. HyDE(Gao et al., 2023)가 활성화되면 LLM이 가상 초록을 생성해 쿼리 벡터를 보강한다.
- **Citations**: log 정규화로 고인용 논문의 지배를 억제한다.
- **Recency**: 연도 기반 계단식 점수 (1년 이내 1.0 ~ 10년 초과 0.1).

이 신호를 통합하는 기본 방식은 RRF(Cormack et al., 2009)다. 각 신호로 독립 정렬한 뒤 순위 역수를 합산하므로, 특정 신호에 점수가 몰리지 않고 여러 관점에서 고르게 높은 논문이 우선된다.

Intent별로 가중치를 달리하는 weighted-sum 방식도 지원한다. 예를 들어 `latest_research`는 최신성(0.50)을, `survey`는 인용 수(0.40)를, `method_search`는 의미 유사도(0.50)를 최우선한다.

## 같은 논문이 3번 나오는 문제

다중 소스 검색에서 중복은 불가피하다. 같은 논문이 arXiv에도, OpenAlex에도 있다. 이를 4단계로 제거한다.

| 단계 | 방법 | 기준 |
|------|------|------|
| 1 | DOI 완전 일치 | 정규화된 DOI 동일 |
| 2 | 정규화 제목 완전 일치 | NFKD + 구두점 제거 + 소문자 |
| 3 | 퍼지 제목 매칭 | Jaccard >= 0.85 AND 단어 수 비율 >= 0.80 |
| 4 | 임베딩 코사인 유사도 | cosine >= 0.90 |

상위 단계에서 매칭되면 하위 단계는 건너뛴다. 중복으로 판정되면 메타데이터가 풍부한 쪽을 대표로 삼고 나머지 필드를 병합한다.

## 검색하고, 반성하고, 다시 검색한다

<div style="margin:24px 0;text-align:center;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 520" style="width:100%;max-width:960px;height:auto" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif">
  <defs>
    <marker id="react_arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#6b7280"/>
    </marker>
  </defs>

  <!-- Background -->
  <rect width="600" height="520" fill="#0f0f0f" rx="12"/>

  <!-- Title -->
  <text x="300" y="30" text-anchor="middle" fill="#f3f4f6" font-size="14" font-weight="700">멀티턴 ReAct 검색 루프</text>
  <text x="300" y="50" text-anchor="middle" fill="#9ca3af" font-size="11">예산 기반 반복 검색 · LLM Gap 분석 · 누적 결과 관리</text>

  <!-- ===== CARD 1: Turn 1 ===== -->
  <rect x="24" y="64" width="552" height="118" rx="10" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>

  <!-- Turn label + time badge -->
  <text x="44" y="90" fill="#a5b4fc" font-size="13" font-weight="700">Turn 1</text>
  <rect x="108" y="76" width="58" height="22" rx="6" fill="#181818" stroke="#6b7280" stroke-width="1"/>
  <text x="137" y="91" text-anchor="middle" fill="#6b7280" font-size="11">40s</text>
  <!-- time badge right side -->
  <rect x="490" y="76" width="66" height="22" rx="6" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="523" y="91" text-anchor="middle" fill="#6b7280" font-size="10">예산 40s</text>

  <!-- Search results -->
  <text x="44" y="116" fill="#9ca3af" font-size="11">arXiv:</text>
  <text x="90" y="116" fill="#f3f4f6" font-size="11" font-weight="600">8편</text>
  <text x="130" y="116" fill="#6b7280" font-size="11">+</text>
  <text x="146" y="116" fill="#9ca3af" font-size="11">OpenAlex:</text>
  <text x="216" y="116" fill="#f3f4f6" font-size="11" font-weight="600">7편</text>
  <text x="254" y="116" fill="#6b7280" font-size="11">=</text>

  <!-- Result badge -->
  <rect x="270" y="104" width="68" height="22" rx="6" fill="#181818" stroke="#a5b4fc" stroke-width="1.5"/>
  <text x="304" y="119" text-anchor="middle" fill="#a5b4fc" font-size="11" font-weight="700">15편 수집</text>

  <!-- Sub-description -->
  <text x="44" y="154" fill="#6b7280" font-size="10.5">keyword_search (arXiv) · semantic_search (OpenAlex) 병렬 실행</text>

  <!-- ===== Arrow 1 ===== -->
  <line x1="300" y1="182" x2="300" y2="208" stroke="#6b7280" stroke-width="1.5" marker-end="url(#react_arrow)"/>

  <!-- ===== CARD 2: Gap Analysis ===== -->
  <rect x="24" y="212" width="552" height="100" rx="10" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>

  <!-- Gap label + time badge -->
  <text x="44" y="238" fill="#f3f4f6" font-size="13" font-weight="700">Gap Analysis</text>
  <rect x="158" y="224" width="58" height="22" rx="6" fill="#181818" stroke="#6b7280" stroke-width="1"/>
  <text x="187" y="239" text-anchor="middle" fill="#6b7280" font-size="11">20s</text>
  <!-- LLM tag -->
  <rect x="490" y="224" width="42" height="22" rx="6" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="511" y="239" text-anchor="middle" fill="#9ca3af" font-size="10">LLM</text>

  <!-- Gap content -->
  <text x="44" y="264" fill="#9ca3af" font-size="11">발견:</text>
  <text x="82" y="264" fill="#f3f4f6" font-size="11">"linear attention 관련 방법론이 부족합니다"</text>

  <!-- next_query -->
  <text x="44" y="286" fill="#9ca3af" font-size="11">next_query:</text>
  <rect x="120" y="274" width="300" height="22" rx="5" fill="#181818" stroke="#a5b4fc" stroke-width="1"/>
  <text x="130" y="289" fill="#a5b4fc" font-size="11">"linear attention FlashAttn efficient"</text>

  <!-- ===== Arrow 2 ===== -->
  <line x1="300" y1="312" x2="300" y2="338" stroke="#6b7280" stroke-width="1.5" marker-end="url(#react_arrow)"/>

  <!-- ===== CARD 3: Turn 2 ===== -->
  <rect x="24" y="342" width="552" height="128" rx="10" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>

  <!-- Turn label + time badge -->
  <text x="44" y="368" fill="#a5b4fc" font-size="13" font-weight="700">Turn 2</text>
  <rect x="108" y="354" width="58" height="22" rx="6" fill="#181818" stroke="#6b7280" stroke-width="1"/>
  <text x="137" y="369" text-anchor="middle" fill="#6b7280" font-size="11">30s</text>
  <!-- time badge right side -->
  <rect x="490" y="354" width="66" height="22" rx="6" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
  <text x="523" y="369" text-anchor="middle" fill="#6b7280" font-size="10">예산 30s</text>

  <!-- Search results -->
  <text x="44" y="394" fill="#9ca3af" font-size="11">OpenAlex:</text>
  <text x="114" y="394" fill="#f3f4f6" font-size="11" font-weight="600">6편</text>
  <text x="148" y="394" fill="#6b7280" font-size="11">+</text>
  <text x="164" y="394" fill="#9ca3af" font-size="11">DBLP:</text>
  <text x="204" y="394" fill="#f3f4f6" font-size="11" font-weight="600">4편</text>

  <!-- Dedup arrow -->
  <text x="244" y="394" fill="#6b7280" font-size="11">→ 중복 제거 →</text>

  <!-- Result badge -->
  <rect x="344" y="382" width="68" height="22" rx="6" fill="#181818" stroke="#a5b4fc" stroke-width="1.5"/>
  <text x="378" y="397" text-anchor="middle" fill="#a5b4fc" font-size="11" font-weight="700">18편 확정</text>

  <!-- Accumulation line -->
  <line x1="44" y1="410" x2="556" y2="410" stroke="#1f2937" stroke-width="1"/>

  <!-- Final result row -->
  <text x="44" y="432" fill="#9ca3af" font-size="11">누적 총계:</text>
  <text x="114" y="432" fill="#f3f4f6" font-size="11" font-weight="700">18편</text>
  <text x="156" y="432" fill="#6b7280" font-size="11">(Turn 1: 15편 → 중복 포함 25편 → Jaccard + 임베딩 제거)</text>

  <!-- Time badges row -->
  <rect x="44" y="444" width="80" height="20" rx="5" fill="#181818" stroke="#1f2937" stroke-width="1"/>
  <text x="84" y="458" text-anchor="middle" fill="#9ca3af" font-size="10">총 71초</text>
  <rect x="134" y="444" width="80" height="20" rx="5" fill="#181818" stroke="#1f2937" stroke-width="1"/>
  <text x="174" y="458" text-anchor="middle" fill="#9ca3af" font-size="10">2턴 완료</text>
  <!-- Pass badge -->
  <rect x="460" y="444" width="96" height="20" rx="5" fill="#181818" stroke="#22c55e" stroke-width="1"/>
  <text x="508" y="458" text-anchor="middle" fill="#22c55e" font-size="10" font-weight="700">PASS (0.78 &gt;= 0.70)</text>

  <!-- Footer note -->
  <text x="300" y="508" text-anchor="middle" fill="#6b7280" font-size="9.5">* coverage_score &lt; 0.70 이면 Turn 3 (20s) 추가 실행</text>
</svg>
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 3. ReAct 멀티턴 검색 루프 -- Turn 1 초기 탐색, Gap Analysis, Turn 2 보완 검색의 흐름. coverage_score가 임계값 미만이면 Turn 3이 추가 실행된다.</em></p>
</div>

Search-R1(Jin et al., 2025)의 `search -> result -> think -> search` 루프를 프롬프트 엔지니어링으로 재현한 `ReActSearchAgent`를 구현했다. 전체 타임아웃은 120초이며, 최대 3턴이 기본값이다.

**Turn 1 -- 다양화 쿼리를 통한 초기 탐색.** 먼저 `_build_initial_queries`가 `QueryAnalyzer`의 분석 결과를 조합해 3~5개의 초기 쿼리 후보를 만든다. 단어 수준 Jaccard 유사도로 중복을 걸러내어(유사도 0.5 이상이면 제거), "transformer attention mechanism"과 "attention mechanism transformer"는 하나만 남고, "transformer attention"과 "self-supervised pre-training"은 둘 다 살아남는다. Turn 1에서는 원본 쿼리로 arXiv 키워드 검색(rate limit 때문에 1회만)과 두 번째 다양화 쿼리로 OpenAlex 시맨틱 검색을 병렬 실행한다. 타임아웃은 40초이다.

**Gap Analysis -- LLM 기반 커버리지 부족 영역 식별.** Turn 1이 끝나면, 수집된 논문 목록(제목 + 연도)을 gpt-4o-mini에 제공하고 묻는다: "어떤 유형의 논문이 빠져 있는가? 그 gap을 채울 쿼리를 제안하라." LLM은 부족한 영역(`missing`)과 보완 쿼리(`next_query`)를 JSON으로 반환한다. 타임아웃(20초) 내에 응답이 오지 않으면 fallback이 동작하여 초기 쿼리 중 아직 사용하지 않은 것을 다음 쿼리로 사용한다.

**Turn 2 -- 보완 검색.** 갭 분석이 제안한 쿼리로 OpenAlex + DBLP를 병렬 검색한다. arXiv는 rate limit(3.5초 간격) 때문에 Turn 1에서만 호출하고, Turn 2부터는 제외한다. Turn 2+ 타임아웃은 30초이다.

**조기 종료 조건.** 다음 중 하나를 만족하면 루프를 종료한다: (1) 누적 논문 수가 `max_results * 1.5`를 초과, (2) LLM 갭 분석이 `is_sufficient: true` 반환, (3) 전체 120초 타임아웃 도달, (4) LLM 갭 분석 시간이 10초 미만 잔여.

## 쉬운 쿼리에 3턴은 낭비다

모든 쿼리에 3턴을 돌리면 불필요하게 느리다. `classify_difficulty`가 confidence, intent, 키워드 수를 보고 난이도를 3단계로 분류한다.

| 난이도 | 조건 | 전략 |
|--------|------|------|
| Easy | confidence 높고 단순 intent | 단일 검색 |
| Medium | 일반적 경우 | 다양화 쿼리 3개, 2턴 |
| Hard | 탐색형/서베이/비교 intent | 3턴 전체 실행 |

현재 `/api/deep-search`는 난이도와 무관하게 항상 3턴을 실행하며, 난이도별 전략 분기는 향후 과제이다.

## 검색 결과를 스스로 평가한다

<div style="margin:24px 0;text-align:center;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 260" style="width:100%;max-width:960px;height:auto" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif">

  <!-- Background -->
  <rect width="600" height="260" fill="#0f0f0f" rx="12"/>

  <!-- Title -->
  <text x="300" y="28" text-anchor="middle" fill="#f3f4f6" font-size="14" font-weight="700">RaR Rubric 평가 -- 4차원 품질 검증</text>
  <text x="300" y="46" text-anchor="middle" fill="#9ca3af" font-size="11">Reflection-after-Retrieval · 검색 결과 자가 평가</text>

  <!-- ===== Bar chart area ===== -->

  <!-- Row 1: Diversity 3/5 = 60% = 198px -->
  <text x="170" y="78" text-anchor="end" fill="#f3f4f6" font-size="12.5" font-weight="600">Diversity</text>
  <text x="170" y="93" text-anchor="end" fill="#9ca3af" font-size="10">다양성</text>
  <!-- bar track -->
  <rect x="178" y="66" width="330" height="26" rx="5" fill="#1f2937"/>
  <!-- bar fill: 3/5 = 60% = 198px -->
  <rect x="178" y="66" width="198" height="26" rx="5" fill="#a5b4fc"/>
  <!-- score label -->
  <text x="384" y="84" fill="#f3f4f6" font-size="12" font-weight="700">3 / 5</text>

  <!-- Row 2: Thoroughness 4/5 = 80% = 264px -->
  <text x="170" y="120" text-anchor="end" fill="#f3f4f6" font-size="12.5" font-weight="600">Thoroughness</text>
  <text x="170" y="135" text-anchor="end" fill="#9ca3af" font-size="10">철저함</text>
  <rect x="178" y="108" width="330" height="26" rx="5" fill="#1f2937"/>
  <rect x="178" y="108" width="264" height="26" rx="5" fill="#a5b4fc"/>
  <text x="450" y="126" fill="#f3f4f6" font-size="12" font-weight="700">4 / 5</text>

  <!-- Row 3: Thoughtfulness 4/5 = 80% = 264px -->
  <text x="170" y="162" text-anchor="end" fill="#f3f4f6" font-size="12.5" font-weight="600">Thoughtfulness</text>
  <text x="170" y="177" text-anchor="end" fill="#9ca3af" font-size="10">사려깊음</text>
  <rect x="178" y="150" width="330" height="26" rx="5" fill="#1f2937"/>
  <rect x="178" y="150" width="264" height="26" rx="5" fill="#a5b4fc"/>
  <text x="450" y="168" fill="#f3f4f6" font-size="12" font-weight="700">4 / 5</text>

  <!-- Row 4: Relevance 5/5 = 100% = 330px -->
  <text x="170" y="204" text-anchor="end" fill="#f3f4f6" font-size="12.5" font-weight="600">Relevance</text>
  <text x="170" y="219" text-anchor="end" fill="#9ca3af" font-size="10">관련성</text>
  <rect x="178" y="192" width="330" height="26" rx="5" fill="#1f2937"/>
  <rect x="178" y="192" width="330" height="26" rx="5" fill="#a5b4fc"/>
  <text x="516" y="210" fill="#f3f4f6" font-size="12" font-weight="700">5 / 5</text>

  <!-- ===== Overall score section ===== -->
  <rect x="24" y="230" width="552" height="20" rx="5" fill="#181818" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>

  <!-- Overall score track -->
  <rect x="178" y="234" width="330" height="12" rx="4" fill="#1f2937"/>
  <!-- 72.8% of 330 = 240px -->
  <rect x="178" y="234" width="240" height="12" rx="4" fill="#6366f1"/>
  <!-- Threshold marker: 60% of 330 = 198px, x = 178+198 = 376 -->
  <line x1="376" y1="230" x2="376" y2="250" stroke="#9ca3af" stroke-width="1.5"/>
  <text x="376" y="228" text-anchor="middle" fill="#9ca3af" font-size="8">0.60</text>

  <!-- Score label -->
  <text x="44" y="244" fill="#9ca3af" font-size="11">Overall:</text>
  <text x="94" y="244" fill="#a5b4fc" font-size="13" font-weight="700">0.728</text>

  <!-- Pass badge -->
  <rect x="516" y="232" width="48" height="16" rx="4" fill="#181818" stroke="#22c55e" stroke-width="1.5"/>
  <text x="540" y="244" text-anchor="middle" fill="#22c55e" font-size="10" font-weight="700">PASS</text>
</svg>
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 4. RaR-Implicit Rubric 4차원 평가 결과 예시 -- method_search intent 기준. 전체 점수 0.728은 충분성 임계값 0.60을 초과하여 PASS 판정.</em></p>
</div>

검색이 끝나면 `RubricEvaluator`가 결과 세트 전체를 평가한다. 개별 논문이 아니라 **집합으로서의 품질**을 본다. ArxivQA 논문(Peng et al., 2023)의 RaR-Implicit에서 영감을 받은 이 평가 체계는 4개 차원으로 구성된다.

- **Diversity (다양성)**: 서로 다른 하위 주제와 방법론을 커버하는가
- **Thoroughness (포괄성)**: 기대되는 주요 측면이 빠짐없이 포함되어 있는가
- **Thoughtfulness (사려깊음)**: 기반 논문, 고임팩트 논문, 미래지향적 논문이 있는가
- **Relevance (관련성)**: 실제로 쿼리 주제를 다루는가

LLM에 최대 15편(제목 + 초록 앞 200자)을 제공하고, 4차원 각 점수(0-5)와 전체 홀리스틱 점수(1-10)를 요청한다.

**최종 점수 계산.** 최종 점수는 홀리스틱 점수(LLM의 전체 직관)에 60%, 가중 차원 합산에 40%를 배분해 산출한다.

```
Input: holistic_score (1-10), dim_scores[4] (0-5), intent_weights[4]
Output: overall_score (0-1)

holistic_norm = holistic_score / 10
weighted_dim_score = sum(w_i * d_i / 5 for w_i, d_i in zip(intent_weights, dim_scores))
overall = 0.6 * holistic_norm + 0.4 * weighted_dim_score
```

**Intent별 차원 가중치.** 차원 가중치는 intent에 따라 달라진다. `latest_research`는 관련성(0.5)과 사려깊음(0.3)을, `comparison`은 다양성(0.4)을, `survey`는 포괄성(0.4)을 최우선한다.

**충분성 판정.** Intent별로 충분성 임계값이 다르다. `survey`는 0.70으로 가장 엄격하고(포괄성이 중요하므로), `paper_search`는 0.55로 비교적 관대하다. 기준에 미달하면 가장 약한 차원(`weakest_dimension`)에 맞춰 보완 쿼리를 자동 생성한다. 예를 들어 다양성이 약하면 "alternative methods approaches"를, 포괄성이 약하면 "survey overview"를 쿼리에 덧붙인다.

## 타임아웃은 단계별로 나눠야 한다

<div style="margin:24px 0;text-align:center;">
<img src="/api/blog/thumbnail/65bcbe5c30fd" alt="검색 에이전트 파이프라인 아키텍처" style="width:100%;max-width:960px;height:auto;border-radius:8px;" />
<p style="font-size:13px;color:#6b7280;margin-top:8px;"><em>Figure 5. 집현전 검색 에이전트 전체 아키텍처 -- QueryAnalyzer부터 RubricEvaluator까지의 파이프라인 흐름 및 각 단계의 타임아웃 버짓 배분.</em></p>
</div>

`/api/deep-search`의 실행 흐름과 각 단계의 타임아웃 버짓은 다음과 같다.

```
QueryAnalyzer (10s) -> ReActSearchAgent (120s) -> RubricEvaluator (15s)
                         |-- Turn 1: arXiv+OpenAlex (40s)
                         |-- Gap Analysis (20s)
                         |-- Turn 2: OpenAlex+DBLP (30s)
                         +-- Turn 3 (필요 시, 20s)
```

기본 검색(`/api/search`)도 검색 단계(60초)와 관련성 필터 단계(45초)를 독립 버짓으로 운영한다. 필터가 타임아웃되면 필터링 없는 원본 결과를 반환한다. 에러 페이지보다 품질이 약간 낮은 결과가 낫다는 설계 원칙에 기반한다.

에이전트가 사용하는 도구는 `keyword_search`(arXiv), `semantic_search`(OpenAlex), `dblp_search`(DBLP), `read_abstract`(arXiv ID 직접 조회)의 4가지다. 새로운 인프라가 아니라 기존 `SearchAgent`의 검색기를 async executor로 래핑한 것이므로, 기존 자산 위에 에이전트 레이어만 얹은 구조이다.

---

## 지금까지의 결과와 앞으로의 방향

운영 경험에서 관찰된 결과는 다음과 같다. 멀티턴 검색은 단일 턴 대비 평균적으로 더 넓은 하위 주제를 커버한다 (Turn 2에서 Turn 1과 겹치지 않는 논문이 추가됨). Rubric 평가의 `weakest_dimension` 피드백을 기반으로 한 보완 검색은 해당 차원의 점수를 개선하는 경향을 보인다. 타임아웃 분리 후 사용자 대면 에러율이 감소했다.

물론 trade-off도 있다. 갭 분석과 Rubric 평가 모두 LLM에 의존하므로, LLM의 응답 품질과 지연 시간이 전체 시스템 성능에 직접적 영향을 미친다. Fallback 경로를 통해 LLM 장애 시에도 기본적인 검색 기능은 유지되지만, 멀티턴의 핵심 가치인 "반성적 재검색"은 상실된다. 정답 세트가 없는 open-domain 검색에서 recall을 정량화하는 것은 본질적으로 어렵고, Rubric 평가는 이에 대한 근사치를 제공하지만 체계적 벤치마크 구축이 필요하다.

향후에는 (1) 난이도 기반 전략 분기의 실제 적용, (2) 체계적 recall 벤치마크 구축, (3) 사용자 피드백 기반 Rubric 가중치 자동 조정을 계획하고 있다.

---

## 참고문헌

- Yao, S. et al. (2023). *ReAct: Synergizing Reasoning and Acting in Language Models*. ICLR 2023.
- Jin, Z. et al. (2025). *Search-R1: Training LLMs to Reason and Leverage Search Engines with Reinforcement Learning*. arXiv:2503.09516.
- Peng, B. et al. (2023). *ArxivQA: Long-form Question Answering on arXiv Papers*. arXiv:2309.01536.
- Gao, L. et al. (2023). *Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE)*. ACL 2023.
- Cormack, G.V. et al. (2009). *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*. SIGIR 2009.
