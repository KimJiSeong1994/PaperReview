# HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models

**Paper:** Gutiérrez, B. J.; Shu, Y.; Gu, Y.; Yasunaga, M.; & Su, Y. (2024). "HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models." *Advances in Neural Information Processing Systems*, 37.

**Abstract:** Passage-level dense ranking을 중심에 둔 RAG는 답의 단서가 여러 문서에 흩어져 있을 때 필요한 근거를 한꺼번에 찾지 못할 수 있다. HippoRAG는 LLM 기반 OpenIE로 corpus 전체의 개념과 관계를 지식 그래프로 만들고, 질의에서 추출한 entity를 시작점으로 Personalized PageRank(PPR)를 실행해 관련 passage를 순위화한다. 저자 보고 기준 2WikiMultiHopQA의 R@5는 ColBERTv2의 68.2에서 89.1로 높아졌지만, HotpotQA에서는 79.3에서 77.7로 낮아졌다. 이 결과는 graph diffusion이 entity 중심 multi-hop retrieval에 유효함을 보여주지만 인간과 같은 장기 기억 전반을 입증하지는 않는다. NER·OpenIE 오류, 높은 offline indexing 비용, entity 중심 표현의 context 손실, 대규모 index에서의 미검증 확장성을 함께 읽어야 한다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 여러 passage에 흩어진 단서를 query-time 반복 생성 없이 하나의 retrieval 단계에서 함께 찾을 수 있는가? |
| 핵심 기여 | OpenIE 지식 그래프, dense entity linking, query-seeded PPR을 결합한 cross-passage association index를 제안했다. |
| 작동 방식 | 질의 entity를 graph node에 연결하고 specificity로 seed를 보정한 뒤, PPR node score를 원문 passage score로 투영한다. |
| 대표 결과 | 2Wiki R@5는 68.2→89.1로 +20.9 percentage points였지만 HotpotQA는 79.3→77.7이었다. Online retrieval은 1,000 query 기준 USD 0.1·3분으로 보고됐다. |
| 핵심 경계 | 각 benchmark의 1,000개 질문과 최대 11,656 passages에서 평가됐다. 오류 100건 중 NER 48%, OpenIE 28%, PPR 24%였고, 더 큰 open-world index의 효과와 효율은 검증되지 않았다. |

**TL;DR**

- HippoRAG는 LLM 기반 OpenIE로 corpus 전체를 지식 그래프로 만들고, 질의 entity를 seed로 Personalized PageRank를 실행해 여러 passage에 흩어진 근거를 한 번의 retrieval로 찾는 그래프 기반 비파라미터 연상 기억 구조다(NeurIPS 2024).
- HippoRAG는 2WikiMultiHopQA R@5를 68.2→89.1(+20.9pp)로 끌어올리고 IRCoT 대비 1,000 query 기준 비용 USD 1–3→0.1·시간 20–40분→3분의 online 절감을 보고하지만, HotpotQA에서는 오히려 ColBERTv2보다 낮다(79.3→77.7).
- HippoRAG의 이득은 entity 중심 benchmark 구조와 방법의 inductive bias가 맞을 때 큰 조건부 효과이며, 오류의 76%가 NER·OpenIE 상류 단계에서 나고 offline indexing 비용이 크며(10k passages에 USD 15·60분) 최대 11,656 passages 규모라 대규모 open-world index로의 일반화는 검증되지 않았다.

## 목차

1. 문제 설정과 연구의 위치
2. 해마 인덱싱 이론에서 가져온 설계 원리
3. HippoRAG의 indexing과 retrieval
4. PPR retrieval의 수식
5. 기존 retrieval 방법과의 차이
6. 실험 결과와 근거 범위
7. 비용·ablation·오류 분석
8. 한계와 해석
9. 결론

---

## 1. 문제 설정과 연구의 위치

표준 RAG는 질의와 각 passage의 유사도를 계산한 뒤 상위 문서를 reader LLM에 전달한다. 답이 한 passage에 직접 적혀 있다면 이 구조는 단순하고 효과적이다. 그러나 서로 다른 문서에 있는 두 조건의 교집합을 찾아야 할 때는 각 passage를 독립적으로 순위화하는 방식이 불리할 수 있다.

논문의 대표 예시는 “스탠퍼드 교수이면서 알츠하이머 신경과학을 연구하는 사람은 누구인가?”라는 질문이다. 한 passage에는 Thomas Südhof가 Stanford 교수라는 사실이, 다른 passage에는 그가 Alzheimer’s neuroscience를 연구한다는 사실이 있을 수 있다. 어느 passage도 질의 전체와 완전히 닮지 않았지만, 두 passage가 가리키는 동일 entity와 관계를 연결하면 답에 필요한 근거 묶음이 드러난다.

Iterative RAG는 첫 검색 결과로 중간 추론이나 다음 질의를 만들고 다시 검색해 이 문제를 푼다. IRCoT처럼 retrieval과 chain-of-thought를 교차시키는 방법은 명시적인 경로를 따라가는 질문에 유용하지만, 매 단계 LLM 호출이 필요하고 첫 단계에서 탐색 방향을 정해야 한다. HippoRAG는 query-time reasoning loop를 늘리는 대신 **검색 전에 corpus 전체의 연관 구조를 만들어 둔다**.

![Current RAG, 인간 기억, HippoRAG의 knowledge integration 비교](/api/blog/figures/hipporag-fig1-knowledge-integration.png)

*그림 1. Current RAG는 passage를 독립적으로 검색하지만 HippoRAG는 corpus 전체의 association graph에서 Stanford와 Alzheimer’s 단서를 연결한다. — 원논문 Figure 1을 블로그 가독성에 맞게 여백만 잘라 부분 인용. 출처: Gutiérrez et al. (2024).*

이 논문의 초점은 생성 모델의 추론 능력보다 **retrieval index의 구조**다. 답을 직접 graph에서 생성하는 것이 아니라, 여러 문서의 관계를 graph에서 계산한 뒤 원문 passage를 reader에게 돌려준다.

---

## 2. 해마 인덱싱 이론에서 가져온 설계 원리

HippoRAG라는 이름은 hippocampal memory indexing theory에서 온다. 논문이 가져온 핵심 직관은 서로 다른 경험을 구분해 저장하는 **pattern separation**과 부분 단서에서 관련 기억을 복원하는 **pattern completion**이다.

| 기억 이론의 구성요소 | HippoRAG의 대응물 | 시스템 역할 |
| --- | --- | --- |
| Neocortex | Instruction-tuned LLM | passage에서 높은 수준의 개념과 관계를 추출한다. |
| Parahippocampal regions | Retrieval encoder | 유사 표현을 연결하고 query entity를 graph node에 매핑한다. |
| Hippocampus | Open KG + PPR | 문서 간 연관성을 저장하고 seed 주변의 관련 subgraph를 활성화한다. |

![Neocortex, parahippocampal regions, hippocampus와 HippoRAG 구성요소의 대응](/api/blog/figures/hipporag-fig2-methodology.png)

*그림 2. LLM–retrieval encoder–KG+PPR이 각각 neocortex–parahippocampal regions–hippocampus의 역할에 대응한다. 위쪽은 offline indexing, 아래쪽은 online retrieval이다. — 원논문 Figure 2를 블로그 가독성에 맞게 여백만 잘라 부분 인용. 출처: Gutiérrez et al. (2024).*

여기서 대응 관계는 신경과학적 동등성을 보인 결과가 아니라 **architecture를 구성하기 위한 analogy**다. HippoRAG가 직접 평가한 것은 multi-hop QA retrieval이며, 인간 기억의 생물학적 fidelity가 아니다.

Open KG에서 noun phrase는 node가 되고 OpenIE relation은 edge가 된다. 같은 entity가 서로 다른 passage에 등장하면 corpus 수준의 연결점이 생긴다. Dense encoder는 이 설계에서 사라지지 않는다. 표현이 다른 유사 node 사이에 synonymy edge를 만들고 query entity를 graph node에 연결할 때 cosine similarity를 사용한다. 정확한 구분은 “vector retrieval을 버렸다”가 아니라 **dense representation을 passage 최종 순위기에서 entity linking과 graph 보강 장치로 옮겼다**는 것이다.

---

## 3. HippoRAG의 indexing과 retrieval

### 3.1 Offline indexing

입력 passage 집합을 $P$, instruction-tuned LLM을 $L$, retrieval encoder를 $M$이라고 하자. Indexing은 다음 순서로 진행된다.

1. 각 passage에서 named entity를 추출한다.
2. 추출한 entity를 prompt에 포함해 subject–relation–object triple을 만든다.
3. Entity와 noun phrase를 node로, OpenIE relation을 edge로 추가한다.
4. 두 node embedding의 cosine similarity가 threshold $\tau$보다 크면 synonymy edge를 추가한다. 논문의 기본값은 $\tau=0.8$이다.
5. Node가 어느 passage에 등장했는지를 node–passage occurrence matrix $P$에 기록한다.

![Alhandra 질문과 관련된 OpenIE 지식 그래프 subgraph](/api/blog/figures/hipporag-fig4-indexing-subgraph.png)

*그림 3. 서로 다른 passage에서 추출된 Alhandra와 Vila Franca de Xira 관련 triple이 하나의 subgraph로 연결된다. `born in`, `is a municipality in`, `equivalent` edge가 passage 경계를 가로지르는 검색 경로를 만든다. — 원논문 Figure 4의 indexing subgraph 패널을 부분 인용. 출처: Gutiérrez et al. (2024).*

이 구조에서 새 passage를 추가할 때 모델 파라미터를 다시 학습할 필요는 없다. 그러나 update가 무비용인 것은 아니다. 새 문서마다 NER, OpenIE, embedding, synonym detection, passage mapping을 다시 수행해야 한다.

### 3.2 Online retrieval

질의 $q$가 들어오면 LLM이 query named entity $C_q=\{c_1,\dots,c_n\}$를 추출한다. 각 entity는 encoder $M$을 통해 가장 가까운 graph node에 연결된다. 연결된 node의 초기 확률을 specificity로 보정한 뒤 PPR을 실행하고, 얻은 node score를 node–passage matrix에 곱해 상위 passage를 선택한다.

![Query NER에서 PPR node probability 확산까지의 retrieval 예시](/api/blog/figures/hipporag-fig5-ppr-retrieval.png)

*그림 4. “Alhandra”를 query node로 연결한 뒤 PPR을 실행하면 초기 확률이 Vila Franca de Xira, Lisbon 등 연관 node로 확산된다. — 원논문 Figure 5의 query NER·node retrieval·PPR 패널을 부분 인용. 출처: Gutiérrez et al. (2024).*

PPR이 answer reasoning 전체를 대신하는 것은 아니다. “Single-step”은 여러 supporting passage를 한 번의 graph retrieval로 찾는다는 뜻이다. 최종 답은 검색된 passage를 받은 reader LLM이 생성한다.

---

## 4. PPR retrieval의 수식

### 4.1 Query entity를 graph seed로 연결하기

Query entity $c_i$는 graph node 가운데 embedding이 가장 가까운 node $r_i$에 연결된다.

$$
r_i
=
\arg\max_{e_j \in N}
\cos\left(M(c_i), M(e_j)\right)
$$

이 단계에서 잘못된 node를 고르면 이후 graph diffusion도 잘못된 subgraph에서 시작한다. 따라서 HippoRAG의 성능은 PPR뿐 아니라 query NER와 entity linking 품질에 의존한다.

### 4.2 Node specificity

Node $i$가 등장한 passage 집합을 $P_i$라고 할 때 논문은 specificity를 다음처럼 정의한다.

$$
s_i=\frac{1}{|P_i|}
$$

많은 문서에 등장하는 일반 node의 seed weight는 낮추고, 소수 문서에 등장하는 구체적인 node는 높인다. IDF와 비슷한 역할을 graph의 passage 연결 수로 구현한 셈이다.

### 4.3 Personalized PageRank

원문의 설명을 표준 PPR 식으로 쓰면 다음과 같다.

$$
\pi
=
\alpha v
+
(1-\alpha)T^\top \pi
$$

$\pi$는 수렴한 node relevance distribution, $v$는 query node에 집중된 restart distribution, $T$는 graph transition matrix다. $\alpha$는 query seed로 돌아갈 확률이며 논문의 기본 damping/restart 설정은 0.5다. 여러 query entity를 동시에 seed로 두면 각각을 따로 검색하는 대신 공동 연결 구조에서 중요한 node에 점수를 모을 수 있다.

### 4.4 Node score를 passage로 되돌리기

PPR이 만든 node score는 node–passage occurrence matrix에 투영된다.

$$
\operatorname{score}_{\text{passage}}
=
\pi^\top P
$$

이 식은 knowledge graph가 최종 evidence를 대체하지 않는다는 점을 보여준다. Graph는 passage를 찾는 index이고, reader에게 전달되는 근거는 원문 passage다.

---

## 5. 기존 retrieval 방법과의 차이

| 방법 | 검색 단위와 연결 방식 | Query-time 반복 | HippoRAG와의 차이 |
| --- | --- | --- | --- |
| BM25 | Sparse term–passage match | 없음 | Lexical match에는 강하지만 문서 간 association을 표현하지 않는다. |
| Contriever·GTR | Dense passage vector | 없음 | 각 passage를 독립적으로 점수화한다. |
| ColBERTv2 | Token–passage late interaction | 없음 | 강한 dense baseline이지만 명시적인 cross-passage graph traversal은 없다. |
| Propositionizer | Passage를 atomic statement로 재작성 | 없음 | 분해는 하지만 corpus-level association graph를 PPR로 검색하지 않는다. |
| RAPTOR | Chunk와 summary의 계층 구조 | 없음 | 문서 통합을 hierarchical summary로 수행한다. |
| IRCoT | 이전 추론이 다음 retrieval query를 만든다. | 있음 | 여러 retrieval–generation round가 필요하다. |
| HippoRAG | Entity/concept KG에서 PPR 후 passage로 투영 | Query NER 1회 | Offline association graph에서 여러 seed의 공동 연관성을 계산한다. |

HippoRAG는 dense retrieval과 symbolic graph를 대체 관계로 두지 않는다. Dense encoder는 synonymy edge와 entity linking을 담당하고, OpenIE graph와 PPR은 cross-passage relevance를 계산한다. 이 역할 분담이 논문의 핵심 architecture다.

---

## 6. 실험 결과와 근거 범위

저자들은 MuSiQue, 2WikiMultiHopQA, HotpotQA validation set에서 각각 1,000개 질문을 선택했다. 각 질문의 supporting passage와 distractor passage를 합쳐 dataset별 retrieval corpus를 구성했으며, 가장 큰 MuSiQue corpus도 11,656 passages다. 아래 수치는 모두 논문 저자 보고 결과이지 독립 재현값이 아니다.

### 6.1 Single-step retrieval

| 모델 | MuSiQue R@5 | 2Wiki R@5 | HotpotQA R@5 | 평균 R@5 |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 41.2 | 61.9 | 72.2 | 58.4 |
| Contriever | 46.6 | 57.5 | 75.5 | 59.9 |
| ColBERTv2 | 49.2 | 68.2 | **79.3** | 65.6 |
| RAPTOR (ColBERTv2) | 46.5 | 64.7 | 75.6 | 62.3 |
| Proposition (ColBERTv2) | 50.1 | 64.9 | 78.1 | 64.4 |
| **HippoRAG (ColBERTv2)** | **51.9** | **89.1** | 77.7 | **72.9** |

가장 큰 격차는 2WikiMultiHopQA에서 나온다. R@5가 68.2에서 89.1로 **+20.9 percentage points** 높아졌다. 이를 “20% 향상”이라고만 요약하면 상대 향상률로 오해할 수 있다. MuSiQue에서는 +2.7 points이고, HotpotQA에서는 오히려 79.3에서 77.7로 1.6 points 낮았다.

저자들도 2Wiki의 entity-centric design이 HippoRAG에 특히 잘 맞는다고 설명한다. 따라서 이 결과는 graph retrieval의 보편적 우월성보다 **방법의 inductive bias와 benchmark 구조가 맞을 때 큰 이득이 난다**는 근거로 읽는 편이 정확하다.

### 6.2 Supporting passage를 세트로 찾는가

| 모델 | MuSiQue AR@5 | 2Wiki AR@5 | HotpotQA AR@5 | 평균 AR@5 |
| --- | ---: | ---: | ---: | ---: |
| ColBERTv2 | 16.1 | 37.1 | **59.0** | 37.4 |
| **HippoRAG** | **22.4** | **75.7** | 57.9 | **52.0** |

모든 supporting passage를 함께 찾은 비율인 AR@5에서도 2Wiki 격차는 +38.6 points다. HippoRAG의 강점이 관련 문서 하나의 순위를 높이는 데 그치지 않고 evidence set을 함께 회수하는 데 있음을 보여준다. 다만 HotpotQA에서는 이 지표 역시 ColBERTv2보다 낮다.

### 6.3 Retrieval gain이 QA gain으로 이어지는가

| Retriever | MuSiQue F1 | 2Wiki F1 | HotpotQA F1 | 평균 F1 |
| --- | ---: | ---: | ---: | ---: |
| None | 24.1 | 39.6 | 42.8 | 35.5 |
| ColBERTv2 | 26.4 | 43.3 | **57.7** | 42.5 |
| **HippoRAG** | **29.8** | **59.5** | 55.0 | **48.1** |
| IRCoT + ColBERTv2 | 30.5 | 45.1 | 58.4 | 44.7 |
| **IRCoT + HippoRAG** | **33.3** | **62.7** | **59.2** | **51.7** |

Single-step HippoRAG의 평균 F1은 42.5에서 48.1로 높아졌고, 2Wiki의 +16.2 points가 대부분의 차이를 만든다. HotpotQA에서는 ColBERTv2보다 2.7 points 낮다. 한편 IRCoT의 retriever를 HippoRAG로 바꾸면 평균 F1이 44.7에서 51.7로 높아진다. Graph association과 iterative reasoning이 서로 대체하기보다 상보적일 수 있다는 결과다.

논문은 명확한 한 경로를 따라가는 path-following과 여러 후보 중 조건의 교집합을 찾는 path-finding을 구분한다. PPR은 여러 query seed의 공동 연관성을 계산하므로 path-finding에 적합한 구조를 갖는다. 그러나 원문의 path-finding 근거는 정량 benchmark가 아니라 Stanford–Alzheimer 사례다. 가능한 작동 방식을 보여주지만 open-world path-finding 전반의 우월성을 입증하지는 않는다.

---

## 7. 비용·ablation·오류 분석

### 7.1 Online 비용과 offline 대가

Appendix G의 1,000 query 측정은 다음과 같다.

| 방법 | API cost | 시간 |
| --- | ---: | ---: |
| ColBERTv2 | USD 0 | 1분 |
| IRCoT | USD 1–3 | 20–40분 |
| HippoRAG | USD 0.1 | 3분 |

HippoRAG는 query entity를 추출한 뒤 graph search를 실행하므로 매 retrieval round에서 LLM을 부르는 IRCoT보다 online token과 지연이 적다. 표의 원자료로 계산하면 비용은 10–30배 낮고 시간은 약 6.7–13.3배 짧다. 다만 NeurIPS 공식 abstract는 “10–20 times cheaper”, arXiv v3 abstract는 “10–30 times cheaper”라고 적는다. 이 글은 headline 대신 Appendix G의 USD 1–3 대 USD 0.1을 기준으로 삼는다.

계산이 사라진 것은 아니라 indexing 단계로 이동했다. 10,000 passages 기준 ColBERTv2/IRCoT indexing은 USD 0·7분, HippoRAG는 GPT-3.5 Turbo API USD 15·60분으로 보고됐다. Llama-3.1-70B를 사용한 indexing 실험에는 4×H100이 쓰였다. Query가 많고 corpus update가 드물수록 online 절감이 높은 indexing 비용을 상쇄하기 쉽다.

### 7.2 무엇이 성능을 만드는가

OpenIE extractor를 바꾼 ablation에서 평균 R@5는 GPT-3.5 Turbo 72.9, REBEL 58.4, Llama-3.1-8B-Instruct 67.8, Llama-3.1-70B-Instruct 72.5였다. 특정 closed model만 가능한 것은 아니지만 충분히 유연하고 정확한 information extraction이 필요하다는 결과다.

Graph scoring에서도 full PPR 72.9에 비해 query nodes only는 56.2, query nodes와 direct neighbors만 사용하면 59.2였다. 단순히 이웃을 늘리는 것이 아니라 seed에서 출발한 확률 분포로 여러 경로의 중요도를 조정하는 과정이 성능에 기여한다. Node specificity를 제거하면 평균 R@5는 70.9, synonymy edge를 제거하면 70.5로 낮아졌다.

100개 MuSiQue 오류를 분류한 결과는 NER 48%, incorrect/missing OpenIE 28%, PPR 24%였다. 가장 큰 병목은 graph algorithm 자체보다 query와 passage에서 필요한 concept을 정확히 뽑는 상류 단계다. “Windows 8”은 추출하지만 “browser”와 “accessible” 같은 context cue를 놓치면 PPR의 seed 정보가 처음부터 불완전해진다.

---

## 8. 한계와 해석

### 8.1 결과를 어디까지 일반화할 수 있는가

첫째, “long-term memory”는 좁혀 읽어야 한다. 논문이 검증한 것은 새 corpus를 parameter update 없이 indexing하고 여러 passage의 연관 evidence를 찾는 능력이다. 망각, 시간에 따라 충돌하는 사실, 기억의 수정·삭제, 개인화된 episodic memory, privacy와 access control은 평가하지 않았다. 더 정확한 기술적 표현은 **graph-based non-parametric associative memory**다.

둘째, 평가 corpus는 각 benchmark의 1,000개 질문에 연결된 supporting/distractor passages로 구성됐다. 최대 11,656 passages는 per-question candidate set보다 현실적이지만 수백만 문서가 지속적으로 갱신되는 환경과는 거리가 있다. 저자들도 훨씬 큰 index에서의 효율과 효과를 입증하지 못했다고 밝힌다.

셋째, entity-centric representation에는 concept–context trade-off가 있다. 구체적인 인명과 지명이 반복되는 corpus에서는 문서 간 연결이 선명해진다. 반대로 서술 맥락, 수식, 담화 관계가 중요한 질문에서는 NER가 핵심 retrieval cue를 버릴 수 있다. Appendix F.4의 작은 intrinsic experiment에서도 GPT-3.5 OpenIE F1은 가장 짧은 10개 passage의 71.8에서 가장 긴 10개 passage의 53.9로 낮아졌다. 표본이 작아 일반적인 degradation curve로 볼 수는 없지만 긴 문서의 extraction과 chunking이 별도 설계 문제임을 보여준다.

넷째, OpenIE relation type은 edge를 만드는 데 쓰이지만 기본 PPR은 `employs`, `located in`, `researches` 같은 relation semantics를 질의 조건에 맞춰 직접 구분하지 않는다. Relation-aware traversal이나 learned edge weighting은 자연스러운 후속 방향이지만 이 논문이 검증한 결과는 아니다.


---

## 9. 결론

HippoRAG의 핵심 기여는 LLM 자체보다 retrieval memory의 형태를 바꾼 데 있다. Passage를 독립적으로 순위화하는 대신 OpenIE concept과 relation을 corpus-level graph로 연결하고, query entity에서 시작한 PPR score를 원문 passage로 되돌린다. 이 구조는 2WikiMultiHopQA에서 retrieval과 QA를 크게 개선했고, iterative LLM retrieval보다 낮은 online 비용과 지연을 보였다.

그 효과는 조건부다. HotpotQA에서는 강한 dense baseline보다 낮았고, 성능은 entity extraction과 linking 품질에 크게 의존했다. 실험 규모도 최대 11,656 passages에 머물며, 높은 offline indexing 비용과 대규모 update·search의 확장성은 남은 문제다.

따라서 HippoRAG는 “인간 기억의 복제”보다 **문서 간 association을 먼저 계산해 multi-hop evidence를 찾는 hybrid retrieval architecture**로 읽는 편이 정확하다. Graph를 도입했다는 사실만으로 충분하지 않다. 무엇을 node로 추출하고, 어떤 edge를 신뢰하며, query를 어느 seed에 연결하고, graph score를 검증 가능한 원문 evidence로 어떻게 돌려주는지가 실제 성능을 결정한다.

## References

Gutiérrez, B. J., Shu, Y., Gu, Y., Yasunaga, M., & Su, Y. (2024). HippoRAG: Neurobiologically inspired long-term memory for large language models. *Advances in Neural Information Processing Systems, 37*. https://proceedings.neurips.cc/paper_files/paper/2024/hash/6ddc001d07ca4f319af96a3024f6dbd1-Abstract-Conference.html

Gutiérrez, B. J., Shu, Y., Gu, Y., Yasunaga, M., & Su, Y. (2025). *HippoRAG: Neurobiologically inspired long-term memory for large language models* (arXiv:2405.14831, Version 3). arXiv. https://arxiv.org/abs/2405.14831

Sarthi, P., Abdullah, S., Tuli, A., Khanna, S., Goldie, A., & Manning, C. D. (2024). RAPTOR: Recursive abstractive processing for tree-organized retrieval. *arXiv*. https://arxiv.org/abs/2401.18059

Santhanam, K., Khattab, O., Saad-Falcon, J., Potts, C., & Zaharia, M. (2022). ColBERTv2: Effective and efficient retrieval via lightweight late interaction. *Proceedings of NAACL-HLT 2022*, 3715–3734. https://aclanthology.org/2022.naacl-main.272/

Teyler, T. J., & DiScenna, P. (1986). The hippocampal memory indexing theory. *Behavioral Neuroscience, 100*(2), 147–154. https://pubmed.ncbi.nlm.nih.gov/3008780/

Teyler, T. J., & Rudy, J. W. (2007). The hippocampal indexing theory and episodic memory: Updating the index. *Hippocampus, 17*. https://pubmed.ncbi.nlm.nih.gov/17696170/

Trivedi, H., Balasubramanian, N., Khot, T., & Sabharwal, A. (2023). Interleaving retrieval with chain-of-thought reasoning for knowledge-intensive multi-step questions. *Proceedings of ACL 2023*, 10014–10037. https://aclanthology.org/2023.acl-long.557/
