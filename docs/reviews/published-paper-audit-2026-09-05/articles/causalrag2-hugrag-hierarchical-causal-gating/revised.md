# CausalRAG2: Hierarchical Causal Knowledge Graph Design for RAG

**Paper:** Nengbo Wang; Tuo Liang; Vikash Singh; Chaoda Song; Van Yang; Yu Yin; Jing Ma; Jagdip Singh; Vipin Chaudhary (2026). "CausalRAG2: Hierarchical Causal Knowledge Graph Design for RAG". https://arxiv.org/abs/2602.05143 · arXiv:2602.05143v2

초기 arXiv 판본의 HugRAG는 v2에서 CausalRAG2로 개명됐다. 계층적 인과 그래프와 질의별 게이팅을 결합하는 검색 방법이다.

**Abstract:** 기존 Graph RAG는 지식을 그래프로 묶어도 검색이 한 커뮤니티 안에 머무르거나, 질문과 주제만 비슷한 노드를 과도하게 가져올 수 있다. CausalRAG2는 이 두 문제를 각각 **정보 고립**과 **국소적 허위 노이즈**로 정의한다. 오프라인에는 Leiden 알고리즘으로 계층형 모듈을 만들고, 서로 떨어진 모듈 사이에 LLM이 판정한 인과 게이트를 추가한다. 질의 시점에는 엔티티와 모듈을 함께 검색하고, 구조·계층·게이트 간선을 따라 후보 하위 그래프를 확장한 뒤, 다시 LLM으로 인과적 근거와 우연한 연관을 구분한다. 저자 보고 기준 CausalRAG2는 HolisQA의 15개 평가 셀에서 모두 가장 높은 점수를 기록했고, 표준 QA에서는 15개 중 11개 셀에서 가장 높았다. 다만 여기서 “인과”는 개입과 식별을 다루는 통계적 인과추론이 아니다. 게이트는 방향과 효과 크기가 없는 이진 연결이며, LLM이 텍스트의 인과·논리 의존성을 판정해 검색을 허용하는 장치다. 따라서 이 논문의 핵심은 **인과모형의 발견**보다 **계층형 그래프에서 어떤 경로를 열고 어떤 근거를 버릴지 설계한 검색 구조**에 있다.

---

## 핵심 요약

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 그래프 모듈 사이의 정보 고립을 깨면서도, 확장 과정에서 들어온 비인과적 노이즈를 제거할 수 있는가? |
| 핵심 기여 | Leiden 계층, 모듈 간 인과 게이트, 다층 seed 검색, 우선순위 그래프 확장, 질의별 인과 필터를 하나의 Graph RAG 파이프라인으로 묶었다. |
| 평가 기여 | 단일 엔티티 검색보다 여러 문장의 통합을 요구하도록 2025년 학술 논문에서 HolisQA를 만들었다. |
| 대표 결과 | HolisQA 다섯 분야의 F1·Context Recall·Answer Relevancy 15개 셀에서 모두 가장 높았다. 표준 QA에서는 15개 셀 중 11개에서 가장 높았다. |
| 핵심 해석 | “인과 게이트”는 검증된 방향성 인과 간선이 아니라, LLM이 인과 또는 논리적 의존성이 있다고 판정한 모듈 사이의 이진·무방향 탐색 지름길이다. |
| 핵심 한계 | LLM 기반 그래프와 필터, 합성 benchmark, 자동평가, 공통 root graph를 사용한 baseline 재현, 주효과의 통계적 불확실성 부재가 결론의 범위를 제한한다. |

## 목차

1. HugRAG에서 CausalRAG2로
2. 정보 고립과 국소적 허위 노이즈
3. 계층형 그래프와 인과 게이트
4. 질의 시점 검색과 인과 경로 필터
5. 이 논문에서 “인과”가 뜻하는 것
6. HolisQA와 실험 설계
7. 주요 결과와 구성요소 제거 실험
8. 확장성·비용과 결과의 범위
9. 결론

## 1. HugRAG에서 CausalRAG2로

![Standard RAG, Graph-based RAG, and CausalRAG2](/api/blog/figures/hugrag-fig1-comparison.png)

*그림 1. 정전 뒤 교통 정체가 커진 이유를 묻는 질문에서 Standard RAG, 일반 Graph RAG, CausalRAG2의 검색 차이를 비교한 도식. — 원논문 Figure 1을 주변 본문과 분리해 인용했으며 그림 내용은 수정하지 않았다. 출처: Wang et al. (2026), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).*

HugRAG라는 이름은 “계층이 서로를 감싸는 그래프”라는 인상을 주지만, v2의 새 이름 CausalRAG2는 연구 계보를 더 정확하게 드러낸다. 전작 CausalRAG는 질문과 가까운 엔티티에서 그래프를 넓힌 뒤 LLM으로 인과 경로를 골랐다. 문제는 그래프가 커질수록 지역 확장만으로는 다른 커뮤니티의 근거까지 도달하기 어렵다는 점이었다.

CausalRAG2는 전작의 질의별 인과 필터 앞에 두 장치를 추가한다.

1. 지식 그래프를 여러 수준의 모듈로 조직한다.
2. 서로 떨어진 모듈 사이에 인과 게이트를 미리 만든다.

이 변화는 단순히 그래프에 간선을 더 넣는 것과 다르다. 모든 모듈을 완전 연결하면 정보 고립은 사라지지만 검색 노이즈가 폭증한다. CausalRAG2는 오프라인에는 선택적인 지름길을 만들고, 온라인에는 질문별로 지름길을 통과한 결과를 다시 거른다. **recall을 넓히는 장치와 precision을 회복하는 장치를 분리해 배치한 구조**다.

v2는 이 설계를 뒷받침하는 증거도 보강했다. 무작위·의미 유사도 게이트와의 비교, 전문가의 게이트 판정, 전체 비용표, LLM별 필터 안정성, 논문이 인정한 한계가 새로 포함됐다. 따라서 HugRAG v1만 읽으면 방법의 큰 그림은 알 수 있지만, 결과가 어디까지 성립하는지 판단하기에는 현재 v2가 더 적합하다.

---

## 2. 정보 고립과 국소적 허위 노이즈

CausalRAG2가 겨냥한 실패는 recall과 precision의 문제로 나뉜다.

### 2.1 정보 고립: 필요한 근거가 다른 모듈에 있을 때

큰 지식 그래프에는 서로 촘촘히 연결된 커뮤니티가 자연스럽게 생긴다. 시작 노드가 모듈 $m_i$에 있고 필요한 근거 $v^star$가 멀리 떨어진 모듈 $m_j$에 있다면, 고정된 $h$-hop 지역 검색은 $m_j$에 도달하지 못할 수 있다.

$$
v^\star \notin S
\quad\text{when}\quad
\operatorname{dist}_{G}(U,v^\star)>h
$$

GraphRAG의 커뮤니티 요약이나 LeanRAG의 의미 계층은 넓은 문맥을 압축하는 데 도움을 준다. 하지만 의미가 다른 두 모듈 사이에 논리적으로 중요한 연결이 있어도, 커뮤니티 경계나 tree 경로가 그 관계를 직접 표현하지 못할 수 있다. 논문은 이를 **Global Information Isolation**, 즉 전역 recall의 공백으로 본다.

### 2.2 국소적 허위 노이즈: 도달한 노드가 모두 근거는 아닐 때

반대로 검색 반경을 넓히면 질문과 단어·주제는 비슷하지만 답의 원인–결과 설명에는 필요하지 않은 노드가 들어온다. 고차수 hub, 우연한 동시 출현, 같은 분야의 주변 개념이 대표적이다.

논문은 질문과 인과적으로 필요한 집합을 $V_{\mathrm{causal}}$, 주제만 비슷한 집합을 $V_{\mathrm{sp}}$라고 놓고 다음 상황을 문제로 본다.

$$
\left|S\cap V_{\mathrm{sp}}\right|
\gg
\left|S\cap V_{\mathrm{causal}}\right|
$$

두 실패는 서로 반대 방향으로 움직인다. 멀리 탐색하면 recall은 좋아질 수 있지만 noise가 늘고, 지역 검색을 엄격히 하면 precision은 지키기 쉽지만 다른 모듈의 근거를 놓친다. CausalRAG2의 전체 설계는 이 긴장을 **계층형 게이트 확장과 인과 필터의 연쇄**로 풀려는 시도다.

---

## 3. 계층형 그래프와 인과 게이트

![CausalRAG2 pipeline](/api/blog/figures/hugrag-fig2-pipeline.png)

*그림 2. 원문에서 기본 그래프와 계층을 만들고 인과 게이트를 추가하는 오프라인 단계, 그리고 다층 검색·게이트 확장·인과 필터를 수행하는 온라인 단계. — 원논문 Figure 2를 주변 본문과 분리해 인용했으며 그림 내용은 수정하지 않았다. 출처: Wang et al. (2026), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).*

### 3.1 기본 그래프와 계층 만들기

먼저 LLM이 corpus $D$에서 엔티티와 관계를 추출해 기본 그래프 $G_0=(V_0,E_0)$를 만든다. 서로 다른 청크에서 추출된 `J. Biden`과 `Joe Biden` 같은 중복은 문자열 fuzzy matching과 임베딩 유사도로 합친다.

그다음 Leiden community detection을 반복해 계층을 만든다.

$$
\mathcal H
=
\left\{H_0,H_1,\ldots,H_L\right\}
$$

$H_0$는 세부 엔티티 그래프이고, 위층으로 갈수록 여러 노드를 묶은 모듈과 자연어 요약이 놓인다. 분할은 모듈 요약이 하나의 context window에 들어갈 때까지 반복된다. 계층 깊이는 downstream 성능으로 학습하지 않고 Leiden 분할의 수렴으로 정한다.

### 3.2 모듈 사이에 게이트를 추가하기

계층화만 하면 모듈 경계가 더 강해질 수 있다. 이를 막기 위해 LLM이 두 모듈의 요약을 읽고 인과 또는 논리 의존성이 있는지 이진 판정을 내린다. 논문의 gate set은 다음과 같다.

$$
G_c
=
\left\{
\{m_i,m_j\}
\;\middle|\;
\mathbb I_{\mathrm{causal}}(m_i,m_j)=1,
i\ne j
\right\}
$$

중괄호로 표현된 $\{m_i,m_j\}$는 순서가 없는 쌍이다. 실제 구현의 게이트도 **undirected, binary edge**다. 게이트는 “$m_i$가 $m_j$를 일으킨다”는 방향성 명제가 아니라, 두 모듈 사이를 탐색해도 된다는 허가에 가깝다.

### 3.3 모든 모듈 쌍을 비교하지 않는 방법

모듈이 $N$개일 때 모든 쌍을 LLM으로 확인하면 비교 횟수는 $O(N^2)$이다. 저자들은 최상위 계층에서 아래로 내려가는 Top-Down Hierarchical Pruning을 사용한다.

- 같은 층의 모듈 사이에서는 게이트 가능성을 확인한다.
- 현재 모듈의 자식은 이미 계층 간선으로 연결되므로 제외한다.
- 이미 게이트로 연결된 상대 모듈의 자식도 제외한다. 부모 게이트와 계층 간선을 조합하면 도달할 수 있기 때문이다.

논문은 이 전략이 실제 비교량을 near-linear 수준으로 줄인다고 설명한다. 다만 모듈 수에 따른 검증 호출 횟수나 시간의 성장 곡선은 제시하지 않는다. Algorithm 2의 같은 층 검사는 여전히 각 층의 모듈 쌍을 순회한다. 따라서 여기서 확인된 것은 **완전한 쌍 비교를 줄이는 pruning 규칙과 비용 결과**이지, 일반적인 선형 복잡도 보장은 아니다.

---

## 4. 질의 시점 검색과 인과 경로 필터

### 4.1 엔티티와 모듈을 함께 seed로 사용한다

질문 $q$가 들어오면 기본 엔티티 $H_0$만 찾지 않고 상위 모듈 $H_{\ell>0}$도 함께 검색한다. 점수는 임베딩 cosine similarity와 lexical overlap을 섞는다.

$$
s_\alpha(q,x)
=
\alpha\cos\!\left(\operatorname{Enc}(q),\operatorname{Enc}(x)\right)
+(1-\alpha)\operatorname{Lex}(q,x)
$$

기본값은 $\alpha=0.7$이다. 이후 Maximal Marginal Relevance(MMR)를 적용해 서로 비슷한 seed만 뽑히는 현상을 줄인다. 실험의 기본 seed budget은 엔티티 $K_0=3$, 모듈 $K_L=3$이다.

### 4.2 세 종류의 간선을 하나의 검색 공간으로 합친다

검색은 다음 세 간선을 통합한 그래프에서 이루어진다.

$$
E_{\mathrm{uni}}
=
E_{\mathrm{struc}}
\cup
E_{\mathrm{hier}}
\cup
G_c
$$

- $E_{\mathrm{struc}}$: 기본 그래프의 국소 관계
- $E_{\mathrm{hier}}$: 엔티티와 상위 모듈을 잇는 계층 관계
- $G_c$: 모듈 경계를 건너는 인과 게이트

frontier node $v$의 우선순위는 질문 점수, hop decay, 간선 종류 가중치의 곱으로 정한다.

$$
\operatorname{Gain}(v)
=
s(q,v)\cdot\gamma^t
\cdot
w\!\left(\operatorname{type}(u,v)\right)
$$

기본값은 $\gamma=0.7$이며, causal gate에는 1.2, hierarchical link에는 1.0, 일반 structural edge에는 0.8의 가중치를 준다. 의미상 가까운 지역을 무작정 걷기보다 계층과 게이트를 더 우선하도록 만든 수작업 inductive bias다. gain이 임계값 아래로 내려가거나 token budget을 다 쓰면 확장을 멈춘다.

### 4.3 넓힌 뒤 다시 줄인다

게이트 확장이 만든 $S_{\mathrm{raw}}$는 recall을 위한 후보 집합이다. 저자들은 노드와 간선을 짧은 ID가 붙은 표로 선형화하고, LLM에게 질문의 답을 뒷받침하는 인과 경로와 우연한 연관을 나누게 한다.

$$
S^\star
=
\operatorname{CausalFilter}
\left(q,S_{\mathrm{raw}}\right)
$$

일반 relevance reranker가 후보에 순위를 매기는 것과 달리, 이 단계는 후보를 `causal support`와 `spurious association`으로 분할한다. 최종 답변은 남겨진 $S^\star$의 텍스트만 사용해 생성한다.

여기서 CausalRAG2의 구조가 선명해진다. 게이트는 검색 범위를 넓혀 **도달 가능성**을 높이고, causal filter는 넓어진 범위에서 **질문별 근거 집합**을 다시 줄인다. 어느 한쪽만으로는 논문이 목표로 한 recall–precision 균형이 나오기 어렵다.

---

## 5. 이 논문에서 “인과”가 뜻하는 것

논문은 “causal”을 관측 데이터에서 발견하는 통계적 인과관계가 아니라, **텍스트에 명시된 논리적 의존성과 사건 순서**라고 정의한다. 이 구분을 놓치면 방법의 성격을 지나치게 강하게 해석하게 된다.

| 정식 인과추론에서 기대하는 것 | CausalRAG2가 실제로 구현한 것 |
| --- | --- |
| 원인과 결과의 방향 | 게이트는 무방향 연결이다. |
| 개입 $do(X=x)$와 반사실 | 개입이나 반사실 질의를 모델링하지 않는다. |
| 교란·매개·선택 편향의 가정 | 별도의 구조적 가정이나 조정 집합이 없다. |
| 인과효과의 크기와 불확실성 | 게이트는 0/1이며 효과 크기나 확률을 저장하지 않는다. |
| 정답 causal graph와의 구조 비교 | LLM 판정과 전문가 표본 감사로 유효성을 확인한다. |

게이트 검증 프롬프트도 “plausible causal **or logical dependency**”를 찾는다. 따라서 더 정확한 표현은 **LLM이 판정한 논리·사건 의존성에 기반한 cross-module retrieval gate**다.

그렇다고 게이트가 단순한 장식이라는 뜻은 아니다. 저자들은 HolisQA-CompSci의 500개 QA pair에서 gate 수를 같게 맞춰 다섯 전략을 비교했다.

| Gate 유형 | F1 | Context Recall | Answer Relevancy |
| --- | ---: | ---: | ---: |
| Random | 23.86 | 59.26 | 46.65 |
| Semantic | 24.87 | 59.37 | 47.14 |
| **Causal** | **31.62** | **60.98** | **58.31** |
| Causal + 25% random false positive | 27.87 | 60.36 | 52.65 |
| Causal - 25% false negative | 28.60 | 57.26 | 54.23 |

같은 수의 무작위·의미 게이트보다 causal gate의 F1과 Answer Relevancy가 높고, false positive나 false negative를 넣으면 점수가 낮아진다. “아무 cross-module edge나 추가해도 된다”는 설명보다는 논문의 인과 판정이 더 잘 맞는다.

두 명의 박사급 전문가가 무작위로 뽑은 게이트 200개를 독립 평가한 결과도 191개, 즉 95.5%를 유효한 인과관계로 확인했고 annotator agreement는 92%였다. 다만 분야별 표본 구성, 판정 rubric, chance-corrected agreement는 보고되지 않았다. 이 결과는 게이트 품질에 관한 유용한 표본 감사이지만, 전체 그래프의 모든 연결이 인과적으로 옳다는 보증은 아니다.

---

## 6. HolisQA와 실험 설계

### 6.1 단일 엔티티가 아니라 여러 문장을 묻게 하기

저자들은 기존 QA benchmark가 이름·연도·장소 같은 짧은 답을 많이 포함해, 올바른 엔티티 하나만 찾아도 높은 점수를 얻을 수 있다고 본다. 이를 보완하기 위해 2025년에 공개된 학술 논문으로 HolisQA를 만들었다.

HolisQA question–answer–context triple에는 두 제약이 적용된다.

1. 질문은 최소 세 개의 서로 다른 문장을 통합해야 한다.
2. 생성 모델은 모든 supporting sentence ID를 출력해야 하며, 그중 하나라도 제거했을 때 답을 만들 수 있으면 탈락시킨다.

| 분야 | Nodes | Edges | Modules | 원문 문자 수 |
| --- | ---: | ---: | ---: | ---: |
| Biology | 1,714 | 1,722 | 165 | 1,707,489 |
| Business | 2,169 | 2,392 | 292 | 1,671,718 |
| Computer Science | 1,670 | 1,667 | 158 | 1,657,390 |
| Medicine | 1,930 | 2,124 | 226 | 1,706,211 |
| Psychology | 2,019 | 1,990 | 211 | 1,751,389 |

두 명의 domain expert는 HolisQA-CompSci에서 200개 triple을 뽑아 질문의 합리성, 문맥의 충분성, 다문장 통합과 답의 정확성을 평가했다. 논문은 평균 96.8%를 fully valid로 판정했고, 두 평가자가 191/200에서 일치했다고 보고한다.

이 검증은 합성 benchmark의 품질을 점검했다는 점에서 중요하다. 동시에 범위도 분명하다. 전문가 평가는 Computer Science의 200개 표본에 한정되고, PDF에는 전체 논문 수와 QA pair 수가 적혀 있지 않다. Biology·Business·Medicine·Psychology에 같은 품질이 유지되는지는 분야별 감사 결과로 확인할 수 없다.

### 6.2 표준 QA와 평가 조건

표준 benchmark는 MS MARCO, Natural Questions, 2WikiMultiHopQA, QASC, HotpotQA다. 작은 QASC 그래프는 77개 node와 4개 module인 반면, HotpotQA는 20,354개 node와 2,359개 module이다. 이 차이는 계층 구조의 효과가 graph heterogeneity에 따라 달라지는지 보는 조건을 제공한다.

| 축 | 설정 |
| --- | --- |
| 비교 방법 | BM25, Standard RAG, GraphRAG Global/Local, LightRAG, HippoRAG2, LeanRAG, CausalRAG |
| 생성·그래프 LLM | `gpt-5-nano`, temperature 0.0 |
| 임베딩 | `all-MiniLM-L6-v2`, 384 dimensions |
| 자동평가 | Ragas, `Gemini-2.5-Flash-Lite` evaluator |
| 지표 | token-level F1, Context Recall, Answer Relevancy |
| 공통 조건 | unified root knowledge graph, initial $k=3$, retrieval context와 evaluator item 수의 공통 상한 |
| 계산 자원 | task당 2 CPU cores, 16 GB RAM, 10-way job array |

F1은 gold answer와의 표면적 token overlap이다. Context Recall과 Answer Relevancy는 Ragas를 통해 Gemini-2.5-Flash-Lite가 판정한다. 생성 모델과 평가 모델이 분리돼 있다는 점은 같은 모델이 자기 답을 채점하는 설정보다 낫다. 그러나 두 grounding metric은 여전히 사람 평가가 아닌 LLM-as-a-judge 결과다.

또 하나의 중요한 조건은 모든 graph-based method가 **공통 root knowledge graph**에서 시작한다는 점이다. 이는 그래프 추출 품질을 통제해 retrieval 차이에 집중하는 비교다. 반대로 각 방법의 공식 package가 자체 index construction과 함께 내는 end-to-end 성능을 그대로 비교한 결과는 아니다.

---

## 7. 주요 결과와 구성요소 제거 실험

### 7.1 HolisQA에서는 15개 셀 모두 가장 높다

![HolisQA main results](/api/blog/figures/hugrag-table3-holisqa.png)

*그림 3. HolisQA 다섯 분야에서 F1, Context Recall, Answer Relevancy를 비교한 원논문 Table 3. — arXiv v2 PDF에서 표 영역만 잘라 인용했으며 수치와 강조는 수정하지 않았다. 출처: Wang et al. (2026), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).*

CausalRAG2는 Medicine, Computer Science, Business, Biology, Psychology의 세 지표, 총 15개 평가 셀에서 모두 가장 높다.

| 분야 | F1 | Context Recall | Answer Relevancy |
| --- | ---: | ---: | ---: |
| Medicine | 36.45 | 69.91 | 60.65 |
| Computer Science | 31.60 | 60.94 | 58.34 |
| Business | 51.51 | 67.34 | 68.76 |
| Biology | 34.80 | 61.97 | 59.99 |
| Psychology | 44.42 | 60.87 | 63.53 |

Table 3의 다섯 분야를 단순 평균하면 CausalRAG2는 F1 39.76, Context Recall 64.21, Answer Relevancy 62.25다. 비교 방법 가운데 LeanRAG의 단순 평균은 37.95, 58.64, 57.43이고, CausalRAG는 36.72, 52.87, 60.64다. 이 계산은 별도의 통계 추정량이 아니라 표를 요약한 산술 평균이다.

### 7.2 표준 QA에서는 15개 중 11개가 최고다

논문 본문은 표준 QA에서도 일관된 우위를 강조하지만, Table 4를 셀 단위로 보면 예외가 있다.

| 데이터셋·지표 | CausalRAG2 | 더 높은 방법 |
| --- | ---: | ---: |
| 2Wiki Context Recall | 41.95 | HippoRAG2 55.53 |
| QASC F1 | 13.35 | HippoRAG2 14.73 |
| QASC Answer Relevancy | 49.40 | HippoRAG2 49.94 |
| HotpotQA Context Recall | 40.30 | LightRAG 48.17 |

나머지 11개 셀에서는 CausalRAG2가 가장 높다. 특히 CausalRAG와 비교한 표준 QA 평균 F1 차이는 논문 보고대로 약 +15.5 point이며, module이 2,359개인 HotpotQA에서는 +24.83 point, module이 158개인 HolisQA-CompSci에서는 +0.62 point다. 계층 구조가 graph heterogeneity가 큰 조건에서 더 유용하다는 저자들의 해석과 맞닿는다.

다만 main table에는 반복 실험의 분산, confidence interval, 유의성 검정이 없다. 49.40과 49.94처럼 작은 차이나, dataset별 점수 차이가 sample variation을 넘는지는 표만으로 판단할 수 없다.

### 7.3 hierarchy와 gate는 recall을 넓히고, causal filter가 precision을 회복한다

![CausalRAG2 ablation](/api/blog/figures/hugrag-fig3-ablation.png)

*그림 4. Hierarchical Structure(H), Causal Gates(CG), 일반 causal selection, spurious-aware causal selection을 조합한 구성요소 제거 실험. — 원논문 Figure 3을 주변 본문과 분리해 인용했으며 차트 내용은 수정하지 않았다. 출처: Wang et al. (2026), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).*

아무 구성요소도 넣지 않은 설정은 F1 26.8, Context Recall 54.7, Answer Relevancy 55.7이다. hierarchy만 넣으면 recall은 58.0으로 오르지만 F1은 24.0, Answer Relevancy는 53.6으로 낮아진다. causal gate까지 넣고 filter를 쓰지 않으면 recall은 60.2까지 오르지만 F1 23.3, Answer Relevancy 52.6이 된다.

이 패턴은 논문의 문제 설정과 정확히 맞는다. 구조와 게이트가 다른 모듈의 근거를 가져오지만, 함께 들어온 주변 정보가 precision을 해친다. 일반 causal filter를 넣은 전체 구조는 36.8/60.0/64.1, spurious-aware filter까지 사용한 최종 설정은 38.6/60.4/67.4다.

따라서 이 ablation이 지지하는 결론은 “계층이 항상 좋다”거나 “인과 게이트만으로 충분하다”가 아니다. **계층과 게이트가 recall을 넓히고, 질의별 causal filter가 그 대가로 생긴 노이즈를 제거할 때 세 지표가 함께 오른다**는 결합 효과다.

---

## 8. 확장성·비용과 결과의 범위

### 8.1 1.5M 문자까지 유지된 것은 복합 점수다

![CausalRAG2 scalability](/api/blog/figures/hugrag-fig4-scalability.png)

*그림 5. HolisQA에서 원문 길이를 5K부터 1.5M 문자까지 늘렸을 때의 성능 비교. 세로축은 F1, Context Recall, Answer Relevancy의 평균이다. — 원논문 Figure 4를 주변 본문과 분리해 인용했으며 차트 내용은 수정하지 않았다. 출처: Wang et al. (2026), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).*

CausalRAG2의 선은 5K에서 1.5M 문자까지 비교 방법보다 높고, 대체로 48–56 사이에서 유지된다. 정보량이 늘어나도 점수가 급락하지 않았다는 저자들의 주장은 이 범위에서 성립한다.

그러나 이 그림은 F1, Context Recall, Answer Relevancy를 평균한 복합 점수다. 서로 다른 의미의 세 지표가 개별적으로 어떻게 움직였는지는 알 수 없다. 또한 x축은 원문 문자 수이고 y축은 답변 품질이므로, 그래프 구축 시간·메모리·LLM gate 검증 횟수의 asymptotic scalability를 보여주는 곡선은 아니다.

### 8.2 비용은 GraphRAG보다 낮지만 가장 싼 방법은 아니다

| 방법 | 구축 비용 / 1K tokens | 구축 시간 | 질의 비용 | 질의 시간 |
| --- | ---: | ---: | ---: | ---: |
| GraphRAG Global/Local | $0.0034 | 19.694 s | $0.00068 / $0.00051 | 1.850 / 1.306 s |
| LightRAG | $0.0015 | 7.317 s | $0.00018 | 0.487 s |
| HippoRAG2 | $0.00092 | 4.647 s | $0.00032 | 0.641 s |
| LeanRAG | $0.0012 | 5.589 s | $0.00046 | 0.731 s |
| CausalRAG | $0.0014 | 9.022 s | $0.00052 | 0.849 s |
| **CausalRAG2** | **$0.0015** | **9.622 s** | **$0.00049** | **0.801 s** |

CausalRAG2의 구축 비용은 corpus 1K token당 $0.0015로 GraphRAG의 절반보다 작지만 HippoRAG2·LeanRAG·CausalRAG보다 높다. 질의 비용과 지연시간도 LeanRAG보다 약간 높고, GraphRAG보다 낮다. 저자들의 “기존 graph-based RAG와 comparable한 budget”이라는 표현은 타당하지만, 비용 최저라는 뜻은 아니다.

이 수치는 `gpt-5-nano`, 당시 가격, 논문의 corpus와 prompt, cluster 구성에 종속된다. 저장공간, graph update, 실패한 API 호출, 동시성에 따른 tail latency까지 포함한 일반적인 운영비로 확장할 수는 없다.

### 8.3 결과를 해석할 때 남는 다섯 경계

1. **인과 게이트는 이진·무방향 heuristic이다.** 방향, 개입, 교란, 효과 크기를 모델링하지 않는다.
2. **HolisQA는 합성 benchmark다.** 최근 논문과 다문장 제약으로 단순 암기를 줄였지만, expert audit는 CompSci의 제한된 표본에 집중됐다.
3. **두 주요 grounding metric은 자동평가다.** Gemini evaluator를 생성 모델과 분리했지만, main result의 사람 평가나 uncertainty interval은 없다.
4. **baseline 비교는 공통 root graph 위의 retrieval 비교다.** 각 공식 시스템의 고유 index construction까지 포함한 end-to-end package benchmark로 읽어서는 안 된다.
5. **학습되지 않은 구조적 선택이 남아 있다.** hierarchy depth는 downstream objective가 아니라 Leiden 수렴으로 정해지고, gate·edge weight·hop decay도 사전에 정한 값이다.

논문이 직접 인정한 한계도 이 범위와 겹친다. 저자들은 task-adaptive hierarchy가 필요하고, HolisQA의 다섯 학술 분야를 넘어 법률·금융 corpus에서 일반화를 확인해야 한다고 적는다. 여기에 full benchmark의 사람 평가, 방향성 causal relation, graph update 비용, main table의 통계적 불확실성을 더하면 후속 검증의 핵심 축이 된다.

---

## 9. 결론

CausalRAG2의 가장 중요한 아이디어는 “인과 그래프를 만들었다”는 표현보다 **검색 그래프에서 모듈 경계를 어떻게 넘고, 넘은 뒤 어떤 근거를 버릴지 분리했다**는 데 있다.

오프라인에는 Leiden 계층과 인과 게이트를 만들어 먼 모듈 사이의 도달 가능성을 높인다. 온라인에는 엔티티와 모듈을 함께 seed로 선택하고, 구조·계층·게이트 간선을 우선순위에 따라 탐색한다. 마지막에는 LLM이 질문별 인과 경로를 골라 확장 과정의 노이즈를 제거한다. 구성요소 제거 실험은 hierarchy와 gate만 넣었을 때 recall은 오르지만 F1과 Answer Relevancy가 낮아지고, causal filter까지 결합해야 세 지표가 함께 오른다는 점을 보여준다.

실험의 폭도 전작 CausalRAG보다 넓다. 표준 QA 다섯 개와 HolisQA 다섯 분야, gate 유형 비교, 전문가 표본 감사, 1.5M 문자 scale, 비용과 LLM stability를 함께 보고했다. HolisQA 15개 셀에서 모두 가장 높고 표준 QA 15개 중 11개에서 가장 높았다는 결과는 이 설계가 단순 entity hit보다 다문장 통합이 필요한 조건에서 특히 강하다는 해석을 지지한다.

다만 이 결과를 정식 인과추론의 성과로 옮겨 말해서는 안 된다. 게이트는 무방향 binary edge이고, LLM은 인과뿐 아니라 논리적 의존성도 허용한다. HolisQA와 두 grounding metric에는 생성·평가 모델의 판단이 개입하며, baseline은 공통 root graph에서 비교됐다.

따라서 HugRAG에서 CausalRAG2로 이어지는 기여는 **검증된 causal model**이 아니라, **계층형 Graph RAG의 recall–precision 갈등을 cross-module gate와 query-conditioned filter로 구조화한 검색 설계**로 이해하는 편이 정확하다. 다음 단계의 핵심은 더 큰 점수표보다 게이트의 방향성과 불확실성, 사람 기준의 근거 정확도, task-adaptive hierarchy, graph 갱신 비용을 각각 분리해 검증하는 일이다.

## References

Edge, D., Trinh, H., Cheng, N., Bradley, J., Chao, A., Mody, A., Truitt, S., Metropolitansky, D., Ness, R. O., & Larson, J. (2024). *From local to global: A graph RAG approach to query-focused summarization* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2404.16130

Es, S., James, J., Espinosa Anke, L., & Schockaert, S. (2024). RAGAs: Automated evaluation of retrieval augmented generation. In N. Aletras & O. De Clercq (Eds.), *Proceedings of the 18th Conference of the European Chapter of the Association for Computational Linguistics: System Demonstrations* (pp. 150–158). Association for Computational Linguistics. https://doi.org/10.18653/v1/2024.eacl-demo.16

Guo, Z., Xia, L., Yu, Y., Ao, T., & Huang, C. (2025). LightRAG: Simple and fast retrieval-augmented generation. In C. Christodoulopoulos, T. Chakraborty, C. Rose, & V. Peng (Eds.), *Findings of the Association for Computational Linguistics: EMNLP 2025* (pp. 10746–10761). Association for Computational Linguistics. https://doi.org/10.18653/v1/2025.findings-emnlp.568

Gutiérrez, B. J., Shu, Y., Qi, W., Zhou, S., & Su, Y. (2025). From RAG to memory: Non-parametric continual learning for large language models. In *Proceedings of the 42nd International Conference on Machine Learning* (Vol. 267, pp. 21497–21515). PMLR. https://proceedings.mlr.press/v267/gutierrez25a.html

Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., Küttler, H., Lewis, M., Yih, W.-T., Rocktäschel, T., Riedel, S., & Kiela, D. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. *Advances in Neural Information Processing Systems, 33*, 9459–9474. https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html

Traag, V. A., Waltman, L., & van Eck, N. J. (2019). From Louvain to Leiden: Guaranteeing well-connected communities. *Scientific Reports, 9*, Article 5233. https://doi.org/10.1038/s41598-019-41695-z

Wang, N., Han, X., Singh, J., Ma, J., & Chaudhary, V. (2025). CausalRAG: Integrating causal graphs into retrieval-augmented generation. In W. Che, J. Nabende, E. Shutova, & M. T. Pilehvar (Eds.), *Findings of the Association for Computational Linguistics: ACL 2025* (pp. 22680–22693). Association for Computational Linguistics. https://doi.org/10.18653/v1/2025.findings-acl.1165

Wang, N., Liang, T., Singh, V., Song, C., Yang, V., Yin, Y., Ma, J., Singh, J., & Chaudhary, V. (2026). *CausalRAG2: Hierarchical causal knowledge graph design for RAG* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2602.05143

Zhang, Y., Wu, R., Cai, P., Wang, X., Yan, G., Mao, S., Wang, D., & Shi, B. (2026). LeanRAG: Knowledge-graph-based generation with semantic aggregation and hierarchical retrieval. *Proceedings of the AAAI Conference on Artificial Intelligence, 40*(41), 34862–34869. https://doi.org/10.1609/aaai.v40i41.40789
