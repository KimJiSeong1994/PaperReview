# From Local to Global: A Graph RAG Approach to Query-Focused Summarization

**Paper:** Darren Edge; Ha Trinh; Newman Cheng; Joshua Bradley; Alex Chao; Apurva Mody; Steven Truitt; Dasha Metropolitansky; Robert Osazuwa Ness; Jonathan Larson (2024). "From Local to Global: A Graph RAG Approach to Query-Focused Summarization". https://arxiv.org/abs/2404.16130 · arXiv:2404.16130

**Abstract:** MS GraphRAG가 겨냥한 문제는 단순한 multi-hop QA가 아니다. 질문과 가까운 몇 개의 문단을 찾는 대신, 문서 집합 전체에서 반복되는 주제와 연결 구조를 요약해야 하는 **global sensemaking**이다. 시스템은 문서에서 엔티티·관계·주장을 추출해 지식 그래프를 만들고, Leiden 알고리즘으로 계층형 커뮤니티를 찾은 뒤, 각 커뮤니티를 미리 보고서 형태로 요약한다. 질문이 들어오면 이 보고서들에서 부분 답변을 병렬 생성하고 다시 하나의 global answer로 합친다. 저자 보고 기준으로 GraphRAG 계열은 두 데이터셋에서 vector RAG보다 comprehensiveness와 diversity가 높았다. 하지만 empowerment는 일관되게 개선되지 않았고, directness는 오히려 vector RAG가 높았다. GraphRAG와 graph-free source-text summarization의 차이도 claim 기반 검증에서는 유의하지 않았다. 이 논문의 기여는 “그래프가 RAG를 항상 이긴다”는 증명이 아니라, **global question을 위한 사전 계산형 계층 요약 인덱스**를 제안한 데 있다.

---

## 핵심 요약

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 문서 전체의 핵심 주제·관계·관점을 묻는 질문을, 제한된 context window 안에서 어떻게 답할 것인가? |
| 핵심 기여 | LLM 기반 지식 그래프 구축, 계층형 Leiden community detection, community report, query-time map-reduce를 하나의 global RAG 파이프라인으로 결합했다. |
| 작동 방식 | 문서를 그래프로 바꾸고 커뮤니티별 요약을 미리 만든다. 질문이 들어오면 요약 묶음마다 부분 답변과 helpfulness score를 생성하고, 점수가 높은 답변을 다시 합성한다. |
| 대표 결과 | GraphRAG 조건은 vector RAG보다 comprehensiveness에서 Podcast 72–79%, News 72–79%, diversity에서 Podcast 75–81%, News 62–71%의 head-to-head score를 기록했다. |
| 핵심 한계 | 두 corpus와 LLM 생성 질문·LLM judge에 의존한다. global text summarization과 비교하면 개선폭이 작거나 유의하지 않았고, hallucination·사실 정확도·총 API 비용은 직접 평가하지 않았다. |

## 목차

1. 이 논문이 정의한 문제
2. 문서를 지식 그래프로 바꾸는 과정
3. 커뮤니티가 검색 단위가 되는 과정
4. 질의 시점의 map-reduce
5. Vector RAG·source-text summarization과 무엇이 다른가
6. 실험 설계
7. 결과와 해석
8. 결과의 해석과 한계
9. 결론

## 1. 이 논문이 정의한 문제

일반적인 RAG는 질문과 의미적으로 가까운 청크를 찾는다. “A 회사는 언제 설립됐는가?”처럼 답이 몇 문단 안에 있을 때는 이 방식이 자연스럽다. 검색기는 관련 청크를 고르고, LLM은 그 청크 안에서 답을 구성하면 된다.

하지만 다음과 같은 질문은 성격이 다르다.

- 이 문서 모음에서 반복되는 핵심 주제는 무엇인가?
- 인터뷰이들은 기술 규제를 어떻게 바라보는가?
- 뉴스 보도에서 공중보건의 우선순위는 어떻게 드러나는가?

이 질문들은 특정 문장을 찾는 retrieval 문제가 아니다. 문서 집합 전체에 흩어진 사건과 관점을 모아 질문에 맞게 요약하는 **query-focused summarization(QFS)** 문제다. 질문과 가장 가까운 청크 몇 개만 읽으면, 일부 사례를 전체 corpus의 경향처럼 말할 위험이 있다.

MS GraphRAG의 출발점은 여기에 있다. 문서를 질문이 들어올 때마다 처음부터 모두 읽는 대신, 문서 전체를 미리 그래프로 구조화하고 그 그래프의 주요 영역을 요약해 둔다. 질문이 들어오면 원문 청크가 아니라 이 사전 계산된 community report를 global evidence unit으로 사용한다.

![MS GraphRAG indexing and query pipeline](/api/blog/figures/graphrag-fig1-pipeline.png)

*그림 1. Source document에서 knowledge graph와 community summary를 만들고, 질의 시 community answer를 global answer로 합치는 파이프라인. 원논문 Figure 1을 주변 본문만 제거해 재사용했다. CC BY 4.0.*

여기서 중요한 구분이 하나 있다. 현재 Microsoft GraphRAG 구현은 local search와 여러 검색 방식을 제공하지만, 이 논문이 주로 평가한 것은 **community summary를 사용하는 global search**다. 논문의 평가 범위는 global QFS 경로다.

---

## 2. 문서를 지식 그래프로 바꾸는 과정

### 2.1 문서 청크 만들기

첫 단계는 익숙하다. 문서를 일정 길이로 나누고, 각 청크를 LLM extraction의 입력으로 사용한다. 실험에서는 600-token 청크와 100-token overlap을 사용했다.

청크 길이는 단순한 구현 파라미터가 아니다.

- 청크가 길면 호출 횟수가 줄어 indexing 비용이 낮아진다.
- 반대로 긴 입력에서는 앞부분 정보가 덜 추출될 수 있다.
- 청크가 짧으면 entity reference를 더 많이 찾지만 호출 수가 늘어난다.

논문은 이 trade-off를 self-reflection, 또는 저자들이 구현에서 부르는 **gleaning**으로 완화한다. 첫 extraction이 끝난 뒤 LLM에게 누락된 엔티티가 있는지 다시 묻고, 있다고 판단하면 추가 extraction을 수행한다.

![Entity extraction by chunk size and self-reflection](/api/blog/figures/graphrag-fig3-self-reflection.png)

*그림 2. 청크 크기와 self-reflection 반복 횟수에 따른 entity reference 수. 원논문 Figure 3을 크롭했다. 이 그래프는 추출된 수를 보여줄 뿐, 각 엔티티의 정확성이나 검색 기여도를 증명하지는 않는다. CC BY 4.0.*

Figure 3에서 600-token 청크는 2,400-token 청크보다 모든 반복 횟수에서 더 많은 entity reference를 추출한다. self-reflection을 늘리면 세 조건 모두 추출 수가 증가한다. 다만 여기서 측정한 것은 **reference count**다. 더 많이 추출했다는 사실만으로 더 정확한 그래프를 만들었다고 결론 내릴 수는 없다.

### 2.2 엔티티·관계·주장 추출

각 청크에서 LLM은 다음 요소를 만든다.

| 요소 | 내용 | 그래프에서의 역할 |
| --- | --- | --- |
| Entity | 이름, 유형, 짧은 설명 | node 후보 |
| Relationship | source, target, 관계 설명 | edge 후보 |
| Claim | 날짜·사건·상호작용 같은 중요 사실 | node·edge에 연결되는 근거 annotation |

이 과정은 전통적인 schema-first KG construction과 다르다. 고정된 relation vocabulary에 문장을 맞추기보다, LLM이 자연어 설명을 생성한다. 유연한 대신 extraction 결과가 prompt와 모델에 크게 의존한다.

### 2.3 인스턴스를 하나의 그래프로 합치기

같은 엔티티와 관계는 여러 문서에서 반복해서 등장한다. GraphRAG는 이 instance를 합쳐 하나의 node와 edge로 만들고, 여러 설명을 다시 요약한다. 같은 관계가 반복된 횟수는 edge weight가 된다.

논문 구현에서 entity matching은 **exact string matching**이다. 즉 `Microsoft`, `Microsoft Corp.`, `MS`처럼 표기가 다르면 자동으로 하나의 node가 된다고 보장할 수 없다. 저자들은 중복 node가 같은 community에 모이면 후속 summarization이 어느 정도 흡수할 수 있다고 설명하지만, entity resolution 방법을 비교하는 실험은 제시하지 않는다.

Indexing 파이프라인을 단순화하면 다음과 같다. 아래 수식은 논문의 원래 표기가 아니라 파이프라인을 설명하기 위한 재구성이다.

$$
\mathcal{C}=\operatorname{Chunk}(\mathcal{D};L,O)
$$

여기서 $\mathcal{D}$는 문서 집합, $L$은 청크 길이, $O$는 overlap이다. 각 청크 $c_i$에서 LLM이 그래프 요소를 추출한다.

$$
X_i=\operatorname{LLMExtract}(c_i)
=\left(V_i,E_i,A_i\right)
$$

$V_i$는 entity instance, $E_i$는 relationship instance, $A_i$는 claim annotation이다. 이후 같은 이름의 entity와 중복 관계를 집계해 최종 그래프를 만든다.

$$
G=(V,E,w)=\operatorname{Aggregate}\left(\{X_i\}_{i=1}^{|\mathcal{C}|}\right)
$$

$w(u,v)$는 같은 관계가 반복해서 추출된 횟수를 반영한다.

---

## 3. 커뮤니티가 검색 단위가 되는 과정

### 3.1 계층형 Leiden community detection

그래프를 만들었다고 global question에 바로 답할 수 있는 것은 아니다. 전체 node와 edge를 prompt에 넣을 수 없기 때문이다. GraphRAG는 Leiden 알고리즘으로 서로 강하게 연결된 node 집합을 찾고, 각 community를 다시 하위 community로 나눈다.

![Hierarchical Leiden communities](/api/blog/figures/graphrag-fig4-communities.png)

*그림 3. MultiHop-RAG 문서 그래프에서 탐지한 root community와 level-1 sub-community. 원논문 Figure 4를 크롭했다. node 크기는 degree, 색은 community를 나타낸다. CC BY 4.0.*

논문은 hierarchy를 C0에서 C3까지 비교한다.

- **C0**: 가장 상위의 root community. 수가 적고 범위가 넓다.
- **C1–C2**: 중간 수준 community. 범위와 세부 정보 사이의 절충점이다.
- **C3**: 가장 낮은 수준. community 수가 많고 구체적이다.

각 level은 전체 node를 겹치지 않게 나눈다. 이 구조 덕분에 동일한 corpus를 넓은 주제 수준에서도, 더 세분된 하위 주제 수준에서도 요약할 수 있다.

### 3.2 Leaf community report

가장 아래 community에서는 모든 정보를 무작정 prompt에 넣지 않는다. community 내부 edge를 source와 target node의 degree 합이 큰 순서로 정렬한다. 그다음 node 설명, edge 설명, 관련 claim을 context budget이 허용하는 만큼 추가한다.

이 설계는 degree가 큰 entity와 relation이 community를 대표한다는 가정에 기대고 있다. 많이 연결된 entity가 주제를 설명하는 데 유용할 수 있지만, 드물고 중요한 사실은 뒤로 밀릴 수 있다.

### 3.3 Higher-level report

상위 community는 하위 영역의 raw element가 context에 모두 들어가면 그대로 요약한다. 너무 크면 긴 element 묶음을 짧은 child-community report로 교체한다. 다시 말해 아래에서 위로 요약을 말아 올리는 **bottom-up roll-up**이다.

파이프라인을 수식으로 나타내면 level $\ell$의 $k$번째 community report를 다음처럼 쓸 수 있다.

$$
s_k^{(\ell)}=\operatorname{LLMReport}\left(
\operatorname{Elements}(C_k^{(\ell)}),
\{s_j^{(\ell+1)}\}
\right)
$$

상위 report는 넓은 범위를 담지만 세부 사항을 잃을 수 있다. 낮은 level report는 자세하지만 처리해야 할 unit이 많다. 논문의 C0–C3 비교는 바로 이 **범위–세부 정보–token 비용** 사이의 절충을 측정한다.

---

## 4. 질의 시점의 map-reduce

community report가 준비되면 질의 시점에는 세 단계를 거친다.

### 4.1 Report를 섞고 batch로 나누기

선택한 hierarchy level의 report를 무작위로 섞은 뒤, 미리 정한 token 크기의 batch로 나눈다. 특정 주제의 report가 한 batch에 몰려 context 밖으로 사라지는 것을 줄이려는 설계다.

### 4.2 Map: 부분 답변과 helpfulness score 만들기

각 batch는 같은 질문을 독립적으로 받는다. LLM은 부분 답변과 함께 0–100의 helpfulness score를 출력한다.

$$
(a_j,h_j)=\operatorname{LLMMap}(q,B_j)
$$

$q$는 질문, $B_j$는 community report batch, $a_j$는 부분 답변, $h_j$는 유용성 점수다. $h_j=0$인 답변은 버린다.

### 4.3 Reduce: 점수가 높은 부분 답변 합치기

남은 부분 답변을 $h_j$가 높은 순서로 정렬하고, final context가 찰 때까지 넣는다. 마지막 LLM 호출이 이를 하나의 global answer로 합친다.

$$
y=\operatorname{LLMReduce}\left(q,
\operatorname{TopBudget}\{(a_j,h_j)\}\right)
$$

이 구조의 장점은 report batch를 병렬로 처리할 수 있다는 점이다. 반면 information loss가 여러 번 누적된다.

1. 원문에서 entity·relationship·claim을 추출하며 한 번 줄어든다.
2. graph community를 report로 만들며 다시 줄어든다.
3. report batch를 partial answer로 만들며 또 줄어든다.
4. partial answer를 final answer로 합치며 마지막으로 줄어든다.

GraphRAG는 원문 검색보다 더 많은 구조를 제공하지만, 그 구조는 LLM이 반복해서 만든 abstraction이라는 점을 잊으면 안 된다.

---

## 5. Vector RAG·source-text summarization과 무엇이 다른가

논문은 여섯 조건을 비교한다.

| 조건 | query context | 역할 |
| --- | --- | --- |
| SS | query와 가까운 source chunk | 일반적인 vector semantic search |
| TS | 전체 source text를 나눠 map-reduce | 그래프 없는 global summarization |
| C0 | root community report | 가장 압축된 GraphRAG global search |
| C1 | high-level community report | 넓은 범위와 일부 세부 정보 |
| C2 | intermediate report | 중간 수준 절충 |
| C3 | low-level community report | 가장 세부적인 GraphRAG global search |

이 비교에서 가장 중요한 baseline은 두 개다.

### 5.1 SS는 local retrieval 기준선이다

SS는 질문과 의미적으로 가까운 청크를 8k context가 찰 때까지 넣는다. 구체적인 답을 간결하게 제시하는 데 유리하지만, corpus 전체의 주제를 대표한다고 보장할 수 없다.

### 5.2 TS는 “그래프가 정말 필요한가”를 묻는 기준선이다

TS는 source text 전체를 map-reduce한다. community report를 쓰지 않을 뿐, local top-k retrieval은 아니다. 따라서 GraphRAG가 SS보다 좋다는 결과만으로는 그래프의 효과와 global summarization의 효과를 분리할 수 없다. C0–C3와 TS의 차이를 함께 봐야 한다.

논문의 결과는 이 구분을 지지한다. GraphRAG는 SS보다 comprehensiveness와 diversity가 크게 높지만, TS와의 차이는 훨씬 작다. claim 기반 검증에서는 global GraphRAG 조건과 TS 사이에 유의한 차이가 관찰되지 않았다.

---

## 6. 실험 설계

### 6.1 두 개의 corpus

| 데이터 | 구성 | 규모 | 생성된 그래프 |
| --- | --- | ---: | ---: |
| Podcast | *Behind the Tech with Kevin Scott* transcript | 1,669 chunks, 약 1M tokens | 8,564 nodes, 20,691 edges |
| News | 2013–2023년 다분야 news article benchmark | 3,197 chunks, 약 1.7M tokens | 15,754 nodes, 19,520 edges |

두 데이터 모두 600-token chunk와 100-token overlap으로 구성됐다. Podcast indexing은 논문에 적힌 VM과 public `gpt-4-turbo` endpoint에서 281분이 걸렸다. API 호출의 금액은 보고하지 않았다.

### 6.2 정답이 없는 global question 만들기

global sensemaking question에는 하나의 gold answer를 만들기 어렵다. 저자들은 corpus의 짧은 설명을 바탕으로 다음 절차를 사용한다.

1. 잠재 사용자 persona 5개를 만든다.
2. persona마다 수행할 task 5개를 만든다.
3. user–task 조합마다 global question 5개를 만든다.

따라서 데이터셋마다 $5\times5\times5=125$개 질문이 생성된다. 질문은 corpus 전체의 이해를 요구하고, 특정 low-level fact 하나를 찾는 방식은 피하도록 prompt한다.

### 6.3 네 가지 평가 기준

| 기준 | 묻는 내용 | 읽을 때의 주의점 |
| --- | --- | --- |
| Comprehensiveness | 질문의 여러 측면을 얼마나 빠짐없이 다루는가 | 긴 답변이 유리할 수 있다. |
| Diversity | 서로 다른 관점과 근거를 얼마나 다양하게 담는가 | 사실 정확성과 동일하지 않다. |
| Empowerment | 독자가 판단할 수 있도록 설명·근거를 제공하는가 | judge의 질적 판단에 의존한다. |
| Directness | 질문에 얼마나 직접적이고 간결하게 답하는가 | breadth와 반대 방향의 control metric이다. |

LLM judge는 두 답변을 보고 각 기준에서 승자 또는 동률을 선택한다. 질문 하나의 비교는 다섯 번 반복된다. 비정규 분포를 확인한 뒤 Wilcoxon signed-rank test와 Holm–Bonferroni correction을 적용했다.

### 6.4 Claim 기반 보조 검증

저자들은 LLM judge만으로 결과를 끝내지 않았다. 생성 답변에서 검증 가능한 factual claim을 추출해 다음을 측정했다.

- **Comprehensiveness proxy:** 답변당 claim 수
- **Diversity proxy:** claim을 군집화한 뒤 cluster 수

전체 답변에서 중복을 제거한 claim 47,075개, 답변당 평균 31개를 얻었다. 다만 claim 수는 사실성 지표가 아니다. 틀린 문장이 많아도 claim count는 높을 수 있다.

---

## 7. 결과와 해석

### 7.1 GraphRAG는 vector RAG보다 더 넓게 답했다

![MS GraphRAG pairwise win-rate matrices](/api/blog/figures/graphrag-fig2-head-to-head.png)

*그림 4. 두 데이터셋에서 여섯 조건을 pairwise 비교한 결과. 행 조건이 열 조건을 이긴 평균 score다. 원논문 Figure 2를 크롭했다. 125개 질문, 질문당 다섯 번의 비교를 평균했다. CC BY 4.0.*

SS를 열로 두고 C0–C3 행을 보면 모든 GraphRAG 조건이 comprehensiveness와 diversity에서 앞선다.

| 비교 | Podcast | News |
| --- | ---: | ---: |
| C0 vs SS, comprehensiveness | 71.92 vs 28.08 | 71.76 vs 28.24 |
| C3 vs SS, comprehensiveness | 78.96 vs 21.04 | 79.44 vs 20.56 |
| C0 vs SS, diversity | 76.56 vs 23.44 | 62.08 vs 37.92 |
| C3 vs SS, diversity | 80.80 vs 19.20 | 69.12 vs 30.88 |

이 결과가 말하는 범위는 명확하다. **global sensemaking question에 대해 community report를 훑는 방식이 local semantic search보다 더 많은 주제와 관점을 담았다.** 이는 factual retrieval recall이나 answer correctness를 직접 측정한 결과가 아니다.

### 7.2 넓어진 만큼 덜 직접적이었다

Directness에서는 결과가 반대다.

| 비교 | Podcast | News |
| --- | ---: | ---: |
| C0 vs SS | 35.12 vs 64.88 | 41.44 vs 58.56 |
| C3 vs SS | 40.48 vs 59.52 | 45.60 vs 54.40 |

GraphRAG의 답변은 더 포괄적이지만 더 간결한 것은 아니다. 이 결과는 실패라기보다 설계 목적의 trade-off에 가깝다. 문제는 질문 유형을 구분하지 않고 global search를 모든 요청에 적용할 때 생긴다. 짧은 사실 답변이 필요한 질의라면 community report를 모두 합성하는 방식이 과하다.

### 7.3 Root community는 query context를 크게 줄였다

Table 2의 context token 수는 C0의 장점을 잘 보여준다.

| 데이터 | C0 | C3 | TS |
| --- | ---: | ---: | ---: |
| Podcast | 26,657 | 746,100 | 1,014,611 |
| News | 39,770 | 1,140,266 | 1,707,694 |

C0는 TS token 총량의 Podcast 2.6%, News 2.3%만 사용한다. 미리 만들어 둔 root report를 반복 질의에 재사용하기 때문이다. C3도 TS보다 26–33% 적은 context token을 사용했다.

그러나 이것을 **전체 시스템 비용이 97% 감소했다**고 읽으면 안 된다. community report를 만들기 위한 graph indexing과 LLM 호출은 사전에 지불한다. 논문은 Podcast indexing에 281분이 걸렸다고 보고하지만, 금액·전체 token·News indexing 시간은 제공하지 않는다. C0의 장점은 많은 global query가 같은 corpus에 반복될 때 offline cost를 amortize할 수 있다는 데 있다.

### 7.4 그래프의 효과와 global summarization의 효과는 분리되지 않았다

C2와 C3는 일부 조건에서 TS보다 높은 comprehensiveness와 diversity를 보였다.

- Podcast C2 vs TS comprehensiveness: 57.28 vs 42.72
- News C3 vs TS comprehensiveness: 63.60 vs 36.40
- Podcast C2 vs TS diversity: 57.12 vs 42.88
- News C3 vs TS diversity: 60.16 vs 39.84

하지만 모든 level과 데이터에서 일관된 것은 아니다. C0는 Podcast에서 TS와 거의 같았고, News diversity에서는 TS보다 낮았다. 더 중요한 것은 claim 기반 검증에서 **global GraphRAG 조건끼리, 그리고 GraphRAG와 TS 사이에 유의한 차이가 관찰되지 않았다**는 점이다.

따라서 가장 안전한 결론은 다음과 같다.

1. local vector RAG보다 global processing이 breadth를 높였다.
2. graph community가 raw source map-reduce보다 context를 줄이는 데는 분명한 장점이 있었다.
3. 품질 향상 중 얼마가 graph structure 자체에서 왔는지는 이 실험만으로 완전히 분리되지 않는다.

### 7.5 LLM judge와 claim metric은 부분적으로만 일치했다

LLM judge의 다섯 반복에서 다수결 승자가 나온 경우만 놓고 보면, claim 기반 label과의 일치율은 comprehensiveness 78%, diversity 69–70%였다. 하지만 다수결 non-tie가 나온 경우는 각각 전체 비교의 33%, 39%였다.

방향은 대체로 맞지만 완전한 검증은 아니다. claim 추출도 LLM을 사용하며, cluster 수는 threshold에 민감하다. 저자들이 judge 결과를 보조 지표로 교차 확인했다는 점은 긍정적이지만, 사람 평가나 gold evidence 기반 factuality 평가를 대체하지는 않는다.

---

## 8. 결과의 해석과 한계

### 8.1 이 논문은 global question을 평가했다

가장 중요한 범위 제한이다. 결과를 “GraphRAG가 모든 RAG보다 낫다”로 일반화할 수 없다. local fact question, multi-hop supporting passage recall, entity linking accuracy, retrieval precision은 주 평가 대상이 아니다.

### 8.2 평가 corpus는 두 개다

Podcast는 약 100만 token, News는 약 170만 token 규모의 영어 corpus다. 법률, 의료, 과학 문헌, 다국어 자료, 수천만 token 규모에서 같은 결과가 나오는지는 확인하지 않았다. 논문도 이를 명시적인 한계로 인정한다.

### 8.3 Question generation과 evaluation이 LLM에 의존한다

질문은 LLM이 만든 persona와 task에서 나오고, 답변도 GPT-4 계열 파이프라인이 만들며, 비교 평가도 LLM judge가 수행한다. 논문은 corpus 본문이 아니라 corpus 설명으로 질문을 만들어 직접적인 answer leakage를 줄였지만, 어떤 질문이 “좋은 global question”인지 자체가 생성 모델의 관점에 묶인다.

### 8.4 Extraction 오류가 여러 요약 단계에 누적될 수 있다

entity·relationship·claim은 gold graph가 아니라 LLM output이다. exact string matching으로 node를 합치고, degree가 높은 element부터 community report에 넣는다. 잘못 합쳐진 entity, 누락된 relation, 부정확한 claim은 이후 report와 final answer의 입력이 된다. 논문은 graph extraction accuracy나 entity resolution quality를 독립적으로 평가하지 않았다.

### 8.5 Claim 수는 사실성이 아니다

GraphRAG 답변은 SS보다 claim을 많이 포함했다. News에서 C0는 평균 34.18개, SS는 25.23개였고, Podcast에서 가장 높은 C2는 32.46개, SS는 26.50개였다. 이 차이는 comprehensiveness를 뒷받침하지만, claim이 원문에 의해 지지되는지까지 확인하지 않는다.

### 8.6 Hallucination 감소는 입증하지 않았다

논문은 fabrication rate 비교를 향후 과제로 남긴다. 그래프와 report가 있다고 해서 답변의 모든 주장이 원문에 근거한다고 볼 수 없다. 오히려 LLM extraction과 summarization이 여러 번 이어지므로 provenance가 약해질 가능성도 있다. 이 마지막 문장은 파이프라인에서 직접 따라오는 위험 해석이지, 논문이 실험으로 확인한 결과는 아니다.

## 9. 결론

MS GraphRAG의 핵심은 “검색 결과에 그래프 이웃을 조금 더 붙인다”는 데 있지 않다. 문서 전체를 entity graph로 변환하고, graph community를 계층적으로 요약해, 반복되는 global question에 재사용할 수 있는 **사전 계산형 QFS index**를 만든 데 있다.

논문이 충분히 보여준 것은 두 가지다.

1. global sensemaking question에서 local vector RAG보다 더 포괄적이고 다양한 답변을 만들 수 있었다.
2. root community report는 raw source 전체를 map-reduce하는 것보다 query-time context token을 크게 줄였다.

반면 아직 보여주지 못한 것도 분명하다.

- factual QA에서도 우수한가?
- graph extraction이 정확한가?
- GraphRAG의 품질 이득이 graph 때문인가, global summarization 때문인가?
- 답변의 claim이 실제 원문에 의해 지지되는가?
- offline indexing까지 포함한 총비용은 어느 정도인가?

따라서 MS GraphRAG를 읽는 가장 좋은 방식은 범용 RAG 대체재로 보는 것이 아니다. **한 corpus에 대해 global question이 반복되고, 비싼 offline indexing을 여러 질의에 나눠 부담할 수 있을 때 유효한 설계**로 읽는 편이 정확하다. 이후 LightRAG·LeanRAG·HippoRAG 계열은 이 원형의 비용, retrieval granularity, local reasoning 한계를 서로 다른 방식으로 수정한다.

## References

Edge, D., Trinh, H., Cheng, N., Bradley, J., Chao, A., Mody, A., Truitt, S., Metropolitansky, D., Ness, R. O., & Larson, J. (2024). *From local to global: A Graph RAG approach to query-focused summarization* (arXiv:2404.16130v2) [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2404.16130

Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., Küttler, H., Lewis, M., Yih, W.-T., Rocktäschel, T., Riedel, S., & Kiela, D. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. *Advances in Neural Information Processing Systems, 33*, 9459–9474. https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html

Traag, V. A., Waltman, L., & van Eck, N. J. (2019). From Louvain to Leiden: Guaranteeing well-connected communities. *Scientific Reports, 9*, Article 5233. https://doi.org/10.1038/s41598-019-41695-z
