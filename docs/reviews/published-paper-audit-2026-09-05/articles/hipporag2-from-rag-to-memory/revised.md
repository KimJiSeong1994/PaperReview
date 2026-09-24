# From RAG to Memory: Non-Parametric Continual Learning for Large Language Models

**Paper:** Bernal Jiménez Gutiérrez; Yiheng Shu; Weijian Qi; Sizhe Zhou; Yu Su (2025). "From RAG to Memory: Non-Parametric Continual Learning for Large Language Models". https://proceedings.mlr.press/v267/gutierrez25a.html · arXiv:2502.14802

**Abstract:** HippoRAG 2는 Graph RAG의 목표를 “복잡한 질문에 강한 검색기”에서 **새 지식을 지속적으로 추가하면서 사실 검색, 긴 문맥 이해, 다중 문서 연상을 함께 유지하는 비모수적 기억 시스템**으로 넓힌다. 이전 HippoRAG의 OpenIE knowledge graph와 Personalized PageRank(PPR)를 유지하되, phrase node만 있던 graph에 원문 passage node를 넣고, 질의를 entity가 아니라 triple과 연결하며, LLM이 관련 triple을 거르는 recognition memory를 추가한다. Llama-3.3-70B-Instruct reader를 사용한 저자 실험에서 평균 QA F1은 NV-Embed-v2의 57.0에서 59.8로 높아졌고, retrieval recall@5 평균은 73.4에서 78.2로 상승했다. 그러나 이 논문의 continual learning은 model parameter의 망각이나 시간에 따른 지식 충돌을 평가한 것이 아니라, 고정된 질문 집합의 retrieval corpus를 네 구간으로 늘린 실험이다. MuSiQue 비용 측정에서 graph construction에는 70B LLM과 9.2M input token이 들고, query마다 triple filtering LLM을 호출한다. 따라서 HippoRAG 2의 가장 설득력 있는 기여는 인간과 같은 기억을 완성했다는 데 있지 않다. **Dense passage retrieval과 graph association을 하나의 PPR personalization vector 안에서 결합해, 단순 사실 검색의 손실을 줄이면서 multi-hop retrieval을 개선한 설계**에 있다.

---

## 핵심 요약

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 구조화 RAG가 multi-hop과 장문 이해를 개선하면서도 vector RAG의 단순 사실 검색 능력을 유지할 수 있는가? |
| 핵심 변화 | Phrase–passage graph, query-to-triple linking, LLM triple filtering, phrase·passage seed를 결합한 PPR을 제안한다. |
| 평가 범위 | Simple QA 2개, multi-hop QA 4개, discourse understanding 1개 등 7개 benchmark를 평가한다. |
| 대표 결과 | Llama reader 기준 평균 QA F1 59.8, NV-Embed-v2 57.0. Retrieval recall@5는 78.2 대 73.4다. |
| 핵심 한계 | Corpus expansion은 평가하지만 temporal conflict, deletion, forgetting, memory consolidation은 다루지 않는다. 4×H100 환경과 70B LLM에 의존한다. |

## 목차

1. RAG를 왜 기억 시스템으로 다시 정의하는가
2. 세 가지 기억 능력으로 평가 문제를 나누다
3. HippoRAG 1에서 무엇이 달라졌는가
4. HippoRAG 2의 indexing과 retrieval
5. PPR personalization을 어떻게 구성하는가
6. 실험 결과와 해석 범위
7. Ablation, corpus expansion, 비용
8. 결과를 제한해서 해석해야 하는 이유
9. 결론

## 1. RAG를 왜 기억 시스템으로 다시 정의하는가

LLM에 새로운 사실을 반영하는 가장 직접적인 방법은 parameter를 다시 학습시키는 것이다. 그러나 continual pretraining이나 fine-tuning은 계산 비용이 크고, 새로운 지식을 넣는 과정에서 기존 능력이 손상되는 catastrophic forgetting 문제를 일으킬 수 있다. Model editing은 특정 사실을 국소적으로 바꿀 수 있지만, 그 사실과 연결된 파급 관계까지 안정적으로 갱신하기 어렵다.

RAG는 model parameter를 바꾸지 않고 외부 corpus에서 근거를 검색한다. 새 문서를 index에 추가하면 모델을 다시 학습하지 않아도 최신 정보를 사용할 수 있으므로, 논문은 이를 **non-parametric continual learning**으로 본다. 다만 일반적인 dense RAG는 각 passage를 독립적인 vector로 저장한다. 한 passage 안의 사실을 찾는 데는 강하지만, 서로 다른 passage에 있는 개념을 연결하거나 긴 서사의 구조를 통합하는 능력은 index 자체에 들어 있지 않다.

GraphRAG, RAPTOR, HippoRAG 같은 structure-augmented RAG는 이 약점을 graph, hierarchy, summary로 보완한다. 그런데 저자들의 문제 제기는 반대 방향에서도 시작한다. 구조를 추가한 방법이 복잡한 질문에서는 좋아져도, 표준 vector RAG가 이미 잘 푸는 단순 사실 질문에서는 성능이 크게 떨어질 수 있다는 것이다. 기억 시스템을 표방하려면 어려운 연상만 잘해서는 충분하지 않다. 새 지식을 정확히 떠올리고, 긴 맥락을 이해하며, 떨어진 사실을 연결하는 능력을 동시에 유지해야 한다.

![Three memory dimensions evaluated in the original paper](/api/blog/figures/paper-fig1-memory-dimensions.png)

*원논문 Figure 1. 저자들은 RAG의 기억 능력을 factual memory, sense-making, associativity로 나누고 각 계열의 평균 성능을 비교한다. 이 집계 figure는 경향을 보여주는 요약이며, 본문의 상세 해석은 dataset별 Table 2 수치를 기준으로 한다. 출처: Gutiérrez et al. (2025), ICML/PMLR PDF p. 2. 주변 여백만 제거해 직접 인용했다(CC BY 4.0).*

## 2. 세 가지 기억 능력으로 평가 문제를 나누다

논문은 장기 기억을 세 가지 QA 능력으로 operationalize한다.

| 기억 능력 | 논문에서의 의미 | Benchmark |
| --- | --- | --- |
| Factual memory | 하나의 사실을 정확하게 검색하고 답한다. | NaturalQuestions, PopQA |
| Associativity | 여러 passage의 단서를 연결해 답을 구성한다. | MuSiQue, 2WikiMultiHopQA, HotpotQA, LV-Eval |
| Sense-making | 긴 문서의 사건과 맥락을 통합한다. | NarrativeQA |

이 taxonomy의 장점은 서로 다른 구조화 RAG가 자기에게 유리한 task 하나만 평가하는 문제를 줄인다는 데 있다. HippoRAG는 multi-hop QA에 강했지만 긴 discourse에서는 query context를 충분히 활용하지 못했다. RAPTOR와 GraphRAG는 summary 구조로 긴 문맥을 통합하지만, 요약 node가 retrieval corpus에 섞이면서 단순 QA에 noise를 추가할 수 있다.

그러나 이 세 범주를 인간 장기 기억의 완전한 측정으로 보면 안 된다. Factual memory는 QA accuracy, associativity는 multi-hop QA, sense-making은 NarrativeQA로 측정한 **실험적 대리 지표**다. 시간 순서에 따른 기억 갱신, 오래된 정보의 억제, 상충하는 사실의 해소, 삭제 요청, episodic memory의 시간·맥락 구분은 포함되지 않는다.

## 3. HippoRAG 1에서 무엇이 달라졌는가

HippoRAG 1은 passage에서 OpenIE triple을 추출해 phrase 중심 knowledge graph를 만들고, query entity를 graph node에 연결한 뒤 PPR로 관련 passage를 찾는다. Multi-hop 단서가 passage 경계를 넘어 연결된다는 장점이 있지만, 정보가 짧은 phrase와 entity로 압축되면서 원문 문맥이 사라지는 문제가 있었다.

HippoRAG 2는 이 손실을 세 가지 방식으로 보완한다.

| 변화 | HippoRAG 1 | HippoRAG 2 | 해결하려는 실패 |
| --- | --- | --- | --- |
| Graph node | Phrase/entity 중심 | Phrase node + passage node | 개념만 남고 원문 context가 사라지는 문제 |
| Query linking | NER 결과를 node에 연결 | Query 전체를 triple과 passage에 연결 | Entity만 추출해 관계와 의도를 놓치는 문제 |
| Seed filtering | 연결된 entity를 직접 사용 | LLM recognition memory가 triple을 필터링 | Embedding 상위 triple 중 질문과 무관한 항목이 PPR을 오염시키는 문제 |
| Passage ranking | Phrase graph score를 passage로 집계 | Passage node의 PPR score로 직접 ranking | Dense retrieval과 graph traversal을 별도로 ensemble하는 불연속성 |

여기서 “dense–sparse integration”은 일반적인 sparse retrieval과 dense retrieval의 결합을 뜻하지 않는다. 논문은 phrase node를 간결한 concept code, passage node를 풍부한 contextual code로 비유한다. 두 node type을 `contains` context edge로 묶어 같은 graph에서 확산시키는 설계다.

## 4. HippoRAG 2의 indexing과 retrieval

![HippoRAG 2 methodology from the original paper](/api/blog/figures/paper-fig2-methodology.png)

*원논문 Figure 2. 위쪽은 OpenIE와 synonym detection, passage node 통합으로 graph를 만드는 offline indexing이고, 아래쪽은 passage·triple ranking, recognition memory, PPR, QA reader로 이어지는 online retrieval이다. 출처: Gutiérrez et al. (2025), ICML/PMLR PDF p. 4. 주변 여백만 제거해 직접 인용했다(CC BY 4.0).*

### 4.1 Offline indexing: phrase와 passage를 하나의 graph에 넣는다

각 passage에서 LLM이 schema 없는 OpenIE triple $(s,r,o)$를 추출한다. Subject와 object는 phrase node가 되고 relation은 edge가 된다. Phrase embedding의 cosine similarity가 threshold 0.8을 넘으면 synonym edge를 추가한다.

HippoRAG 2의 변화는 모든 원문 passage를 별도의 passage node로 추가하는 것이다. Passage에서 추출된 phrase와 해당 passage node를 `contains` context edge로 연결한다. 결과 graph의 node 집합은 다음처럼 볼 수 있다.

$$
V = V_{\text{phrase}} \cup V_{\text{passage}}
$$

Edge는 OpenIE relation, embedding 기반 synonym, phrase–passage context의 세 종류다.

$$
E = E_{\text{relation}} \cup E_{\text{synonym}} \cup E_{\text{context}}
$$

MuSiQue corpus에서 Llama-3.3-70B-Instruct로 만든 graph는 phrase node 85,288개, passage node 11,656개, 전체 edge 약 140만 개다. 그중 synonym edge가 약 113만 개로 가장 많다. Graph topology가 OpenIE relation만으로 결정되는 것이 아니라 embedding threshold에 크게 좌우된다는 뜻이다.

### 4.2 Query-to-triple: 질문의 관계 구조를 보존한다

HippoRAG 1의 NER-to-node는 질문에서 entity를 추출한 뒤 가장 가까운 phrase node를 seed로 삼는다. “Erik Hort의 출생지가 속한 county는 어디인가?”에서 `Erik Hort`만 남기면 `born in`과 `part of`라는 관계 의도가 약해진다.

HippoRAG 2는 query 전체 embedding으로 graph triple을 ranking한다. Triple은 subject와 object 사이의 관계를 포함하므로 entity 단독 node보다 query 의도를 더 많이 보존한다. 동시에 query와 모든 passage embedding도 비교해 passage node seed score를 만든다.

### 4.3 Recognition memory: LLM이 triple을 다시 거른다

Embedding 상위 triple이 질문에 실제로 필요한지는 보장되지 않는다. Recognition memory는 상위 5개 triple을 LLM에 전달하고, 그중 질문과 관련된 최대 4개를 선택한다. 이 이름은 외부 단서를 보고 관련 기억을 알아보는 recognition 과정에서 가져왔다.

중요한 변화는 HippoRAG 2가 online 단계에서도 LLM을 사용한다는 점이다. HippoRAG 1이 query NER 뒤 graph search를 수행했다면, HippoRAG 2는 매 query마다 triple filtering을 추가한다. 더 정확한 seed를 얻는 대신 latency와 model dependency가 늘어난다.

### 4.4 Graph search가 실패하면 dense retrieval로 돌아간다

필터를 통과한 triple이 없으면 HippoRAG 2는 graph search를 생략하고 embedding model이 ranking한 passage를 직접 반환한다. 이는 단순한 예외 처리가 아니라 factual memory를 지키는 중요한 안전장치다. Graph 연결이 불확실할 때도 항상 PPR을 강제하지 않고, 강한 dense retriever를 fallback으로 유지한다.

## 5. PPR personalization을 어떻게 구성하는가

HippoRAG 2의 PPR은 phrase seed와 passage seed를 함께 사용한다.

1. Filtered triple에 등장한 phrase 가운데 평균 triple score가 높은 node를 최대 5개 선택한다.
2. 모든 passage node를 query–passage embedding similarity로 점수화한다.
3. Passage score에는 weight factor $\lambda$를 곱한다. 기본값은 0.05다.
4. 두 종류의 score를 restart distribution $v$로 정규화한다.
5. PPR을 실행하고 passage node의 최종 확률로 evidence를 순위화한다.

논문의 구현 설명을 표준 PPR 표기로 재구성하면 다음과 같다.

$$
\pi = (1-d)v + dT^{\top}\pi
$$

$T$는 graph transition matrix, $v$는 query-specific personalization vector, $d$는 transition을 계속할 확률이다. 논문의 damping factor는 0.5다. Passage seed의 원점수 $s_i$는 다음처럼 축소된다.

$$
v_i \propto
\begin{cases}
r_i, & i \in V_{\text{phrase seed}} \\
\lambda\,\cos(e_q,e_i), & i \in V_{\text{passage}}
\end{cases}
$$

이 수식은 논문의 알고리즘을 설명하기 위한 재구성이다. 핵심은 dense similarity와 graph relevance를 마지막에 두 점수로 합치는 것이 아니라, **PPR이 출발할 확률 분포 안에서 결합한다**는 점이다.

![HippoRAG 2 online pipeline example from the original paper](/api/blog/figures/paper-fig5-pipeline-example.png)

*원논문 Figure 5. Query-to-triple이 `Erik Hort–born in–Montebello`를 찾고, phrase·passage seed를 함께 초기화한 뒤 PPR이 `Montebello, New York` passage를 회수하는 예시다. 하나의 성공 사례이지 전체 benchmark의 작동을 대표하는 정량 증거는 아니다. 출처: Gutiérrez et al. (2025), ICML/PMLR PDF p. 15. 주변 여백만 제거해 직접 인용했다(CC BY 4.0).*

## 6. 실험 결과와 해석 범위

### 6.1 실험 설정

| 축 | 설정 |
| --- | --- |
| Simple QA | NaturalQuestions 1,000문항, PopQA 1,000문항 |
| Multi-hop QA | MuSiQue·2Wiki·HotpotQA 각 1,000문항, LV-Eval 124문항 |
| Discourse understanding | NarrativeQA 10개 장문, 293문항 |
| Reader / structure LLM | Llama-3.3-70B-Instruct가 주 실험의 OpenIE, filtering, QA를 담당 |
| Dense retriever | NV-Embed-v2 7B |
| Retrieval metric | Passage recall@5 |
| QA metric | Token-level F1 |

Structure-augmented baseline도 같은 Llama와 NV-Embed-v2를 사용해 저자들이 재현했다. 이는 backbone 차이를 줄이는 장점이 있다. 반면 각 방법의 원래 최적 설정과 저자 재현 설정이 같다는 보장은 없다. 특히 GraphRAG와 LightRAG는 passage retrieval을 직접 반환하지 않으므로 retrieval Table 3에서 제외되고, QA Table 2에서만 비교된다.

### 6.2 QA 결과: 평균 개선보다 dataset별 차이가 중요하다

| Dataset | NV-Embed-v2 F1 | HippoRAG 2 F1 | 차이 |
| --- | ---: | ---: | ---: |
| NQ | 61.9 | 63.3 | +1.4 |
| PopQA | 55.7 | 56.2 | +0.5 |
| MuSiQue | 45.7 | 48.6 | +2.9 |
| 2Wiki | 61.5 | 71.0 | +9.5 |
| HotpotQA | 75.3 | 75.5 | +0.2 |
| LV-Eval | 9.8 | 12.9 | +3.1 |
| NarrativeQA | 25.7 | 25.9 | +0.2 |
| **평균** | **57.0** | **59.8** | **+2.8** |

가장 큰 QA 개선은 2Wiki의 +9.5 points다. NQ와 MuSiQue, 2Wiki, LV-Eval에는 bootstrap test 기준 유의한 개선 표시가 붙지만, PopQA·HotpotQA·NarrativeQA의 차이는 0.2–0.5 point에 불과하다. “모든 기억 능력에서 큰 폭으로 개선했다”기보다 **단순 QA의 손실을 막고, 일부 multi-hop dataset에서 의미 있는 추가 이득을 얻었다**고 표현하는 편이 정확하다.

또한 HippoRAG 1은 2Wiki에서 71.8로 HippoRAG 2의 71.0보다 조금 높다. HippoRAG 2의 기여는 모든 cell에서 이전 방법을 이기는 것이 아니라, HippoRAG 1의 강한 association을 대체로 유지하면서 NQ 55.3→63.3, MuSiQue 35.1→48.6, NarrativeQA 16.3→25.9처럼 취약한 영역을 보완한 데 있다.

### 6.3 Retrieval 결과: graph의 이득은 multi-hop에서 더 크다

| Dataset | NV-Embed-v2 R@5 | HippoRAG 2 R@5 | 차이 |
| --- | ---: | ---: | ---: |
| NQ | 75.4 | 78.0 | +2.6 |
| PopQA | 51.0 | 51.7 | +0.7 |
| MuSiQue | 69.7 | 74.7 | +5.0 |
| 2Wiki | 76.5 | 90.4 | +13.9 |
| HotpotQA | 94.5 | 96.3 | +1.8 |
| **평균** | **73.4** | **78.2** | **+4.8** |

Retrieval에서는 2Wiki의 +13.9 points가 가장 크고 MuSiQue가 +5.0 points다. PopQA와 HotpotQA는 ceiling 또는 entity-centric 특성 때문에 추가 이득이 작다. 이 패턴은 “graph가 필요할수록 좋아진다”는 직관과 맞지만, 2Wiki에 결과가 집중되어 있다는 점도 함께 봐야 한다.

QA improvement가 retrieval improvement와 일대일로 대응하지도 않는다. HotpotQA recall은 94.5에서 96.3으로 높아졌지만 F1은 75.3에서 75.5로 거의 변하지 않았다. 필요한 passage를 더 회수하더라도 reader가 이미 충분한 evidence를 갖고 있거나, 추가 context를 답변에 활용하지 못할 수 있다.

## 7. Ablation, corpus expansion, 비용

### 7.1 무엇이 성능을 만드는가

Multi-hop 세 dataset 평균 recall@5는 HippoRAG 2가 87.1이다. Query-to-triple을 HippoRAG 1의 NER-to-node로 바꾸면 74.6, query 전체를 node에 직접 연결하면 59.6으로 낮아진다. Passage node를 제거하면 81.0, triple filter를 제거하면 86.4다.

| 설정 | 평균 R@5 | Full 대비 |
| --- | ---: | ---: |
| HippoRAG 2 | 87.1 | — |
| NER-to-node | 74.6 | -12.5 |
| Query-to-node | 59.6 | -27.5 |
| Passage node 제거 | 81.0 | -6.1 |
| Triple filter 제거 | 86.4 | -0.7 |

가장 큰 기여는 LLM filter가 아니라 query-to-triple과 passage node 통합이다. Filter의 평균 기여는 0.7 point로 작고 2Wiki에서는 filter를 제거한 값이 90.7로 full 90.4보다 높다. Recognition memory가 직관적으로 중요한 구성요소인 것은 맞지만, 이 ablation만으로 항상 필요한 단계라고 단정하기는 어렵다.

### 7.2 Corpus가 커질 때 association은 여전히 약해진다

![Continual corpus expansion experiment from the original paper](/api/blog/figures/paper-fig3-corpus-expansion.png)

*원논문 Figure 3. NQ와 MuSiQue corpus를 네 구간으로 나누고 문서를 점진적으로 추가한 실험이다. NQ 성능은 두 방법 모두 안정적이지만 MuSiQue는 corpus가 커질수록 함께 하락한다. 출처: Gutiérrez et al. (2025), ICML/PMLR PDF p. 8. 주변 여백만 제거해 직접 인용했다(CC BY 4.0).*

HippoRAG 2는 corpus 확장 전 구간에서 NV-Embed-v2보다 높다. 그러나 MuSiQue에서는 두 방법 모두 문서 비율이 25%에서 100%로 늘수록 F1이 감소한다. Graph가 corpus growth의 noise를 제거한 것이 아니라, 더 높은 출발점과 비슷한 하락 경향을 보인 것이다.

이 실험을 continual learning이라고 부를 수는 있지만 범위는 좁다. 하나의 고정 segment를 평가하면서 distractor와 다른 질문의 gold document를 추가한다. 새 사실이 기존 사실을 수정하거나, 동일 entity에 충돌하는 값을 넣거나, 시간에 따라 정답이 바뀌는 상황은 없다.

### 7.3 비용은 GraphRAG보다 작지만 dense RAG보다 크다

MuSiQue 11,656 passage와 4×H100 환경에서 보고된 자원은 다음과 같다.

| Method | Index input/output token | Indexing | QA/query | 추가 QA GPU memory |
| --- | ---: | ---: | ---: | ---: |
| NV-Embed-v2 | — | 12.1분 | 0.3초 | 1.7GB |
| RAPTOR | 1.7M / 0.2M | 100.5분 | 0.6초 | 1.4GB |
| GraphRAG | 115.5M / 36.1M | 277.0분 | 10.7초 | 3.7GB |
| LightRAG | 68.5M / 18.3M | 235.0분 | 13.3초 | 4.5GB |
| HippoRAG | 9.2M / 3.0M | 57.5분 | 0.9초 | 6.0GB |
| HippoRAG 2 | 9.2M / 3.0M | 99.5분 | 1.2초 | 9.9GB |

HippoRAG 2는 GraphRAG와 LightRAG보다 indexing token과 query latency가 작다. 하지만 NV-Embed-v2와 비교하면 indexing은 약 8.2배, query latency는 4배다. HippoRAG 1과 token 사용량은 같지만 passage·triple embedding과 online filtering 때문에 시간과 memory가 늘어난다. “효율적 GraphRAG”와 “vector RAG만큼 가벼운 시스템”은 다른 주장이다.

## 8. 결과를 제한해서 해석해야 하는 이유

### 8.1 Continual learning의 핵심 문제 일부는 평가하지 않는다

논문은 parameter를 바꾸지 않는다는 의미에서 non-parametric continual learning을 다룬다. 그러나 catastrophic forgetting을 직접 측정하지 않는다. Model parameter가 고정되어 있으므로 parameter forgetting이 발생하지 않는 것은 설계상 당연하다. 실제 memory system에서 어려운 temporal conflict, source authority, stale fact suppression, deletion, privacy, consolidation도 benchmark에 없다.

따라서 이 논문의 강한 근거는 **incrementally growing retrieval corpus에서 retrieval·QA 성능을 유지하는가**에 한정된다. 인간 장기 기억의 일반 모델이나 지속 학습 전체에 대한 해결책으로 확대하면 평가 범위를 넘어선다.

### 8.2 Recognition memory 자체가 새로운 오류 지점이다

Recall@5가 1.0보다 낮은 MuSiQue 100개 사례에서 저자들은 filtering과 graph search를 주요 오류 원인으로 분석한다. Query-to-triple 단계에서는 supporting passage phrase와 연결되지 않은 사례가 7%였지만, filtering 뒤에는 26%로 늘었다. 18%는 filter 이후 triple이 하나도 남지 않았다.

Graph construction 자체는 one-hop neighborhood에 supporting phrase가 전혀 없는 사례가 2%로 적었다. 반대로 final graph search에서는 절반의 사례에서 연결된 phrase 중 적어도 절반이 supporting document에 있었는데도 top-5 passage가 완전하지 않았다. 상류 graph에 정보가 존재한다고 downstream PPR ranking이 자동으로 성공하는 것은 아니다.

### 8.3 Baseline 비교는 저자 재현 설정에 의존한다

QA Table 2의 LightRAG 평균 F1은 6.6으로 매우 낮다. 이 수치를 LightRAG의 일반 성능으로 인용하면 안 된다. 저자들은 동일 Llama와 NV-Embed-v2, local mode, short-phrase response, 공통 QA rephrasing을 적용했다. Backbone을 통제한 비교이지만 각 framework가 원래 목표로 삼은 query mode와 최적 prompt를 보존한 비교와는 다르다.

GraphRAG와 LightRAG는 passage retrieval 결과를 직접 반환하지 않아 retrieval recall 표에서도 제외된다. 결국 QA 표는 서로 다른 retrieval contract를 최종 answer F1로 맞춘 비교다. 공정성을 높이려는 재현 설계와 framework-native 최적화 사이의 trade-off가 남는다.

### 8.4 Graph 규모와 synonym edge 의존성이 크다

MuSiQue graph에서 전체 edge 약 140만 개 중 약 113만 개가 embedding similarity로 만든 synonym edge다. LV-Eval은 약 336만 edge를 갖는다. Synonym threshold 0.8과 encoder 표현이 graph topology를 크게 결정한다.

논문은 6천–2만여 passage 범위의 corpus를 평가한다. 수백만 passage의 지속적 update, graph compaction, duplicate entity, conflicting triple, incremental edge maintenance는 실험하지 않는다. Cost 표에서 model weight memory를 제외했는데도 HippoRAG 2의 추가 QA GPU memory가 9.9GB라는 점도 large-scale deployment에서 고려해야 할 경계다.

### 8.5 신경과학 개념은 설계 analogy다

Dense–sparse coding과 recognition memory는 architecture를 설명하는 유용한 언어다. 그러나 phrase node가 실제 sparse neural code와 동등하거나, LLM filter가 인간의 recognition process를 재현한다는 실험은 없다. 논문이 검증한 것은 QA benchmark의 retrieval·generation 성능이다.

이 구분은 논문의 가치를 낮추지 않는다. 오히려 생물학적 은유를 제거해도 passage–phrase graph와 query-conditioned PPR이라는 engineering contribution은 남는다. HippoRAG 2는 기억 이론의 실증 모델보다, **memory에서 가져온 기능적 요구를 RAG architecture로 번역한 시스템**으로 읽는 편이 정확하다.

## 9. 결론

HippoRAG 2가 해결한 핵심 문제는 GraphRAG의 정확도와 vector RAG의 robustness 사이의 간극이다. 이전 HippoRAG가 phrase graph와 PPR로 multi-hop association을 만들었다면, HippoRAG 2는 passage node를 graph 안에 넣고 query 전체를 triple과 연결한다. LLM triple filter와 dense fallback까지 더해 graph가 불필요하거나 불확실한 질문에서의 손실을 줄였다.

저자 실험에서 이 설계는 평균 QA F1 59.8로 NV-Embed-v2의 57.0을 앞섰고, retrieval recall@5는 78.2 대 73.4였다. 다만 개선은 2Wiki와 MuSiQue에 집중되며, HotpotQA와 NarrativeQA의 QA 차이는 0.2 point다. Corpus expansion에서도 associative task의 성능 저하는 계속된다.

따라서 HippoRAG 2의 결론은 “Graph가 vector search를 대체했다”가 아니다. 더 정확한 표현은 다음과 같다.

1. Phrase graph만으로는 context가 부족하므로 passage를 graph node로 직접 넣는다.
2. Query entity보다 query–triple matching이 관계 의도를 더 잘 보존한다.
3. Dense retrieval은 버리는 것이 아니라 passage seed와 fallback으로 유지한다.
4. Graph search의 품질은 graph 존재 여부보다 personalization vector와 seed selection에 크게 좌우된다.
5. 이 구조는 일부 multi-hop retrieval을 개선하지만, 장기 기억과 continual learning의 전체 문제를 해결하지는 않는다.

HippoRAG 2는 GraphRAG를 거대한 knowledge graph 하나로 이해하는 관점에서 벗어나게 한다. 중요한 것은 graph를 만들었다는 사실이 아니라, **질문에 따라 phrase와 passage를 어떤 확률로 활성화하고, 언제 graph search를 포기하며, 회수한 evidence를 어떻게 원문으로 되돌리는가**다. 이 점에서 이 논문은 GraphRAG 계열의 성능 경쟁보다 retrieval architecture의 설계 원리를 더 분명하게 보여준다.

## References

Edge, D., Trinh, H., Cheng, N., Bradley, J., Chao, A., Mody, A., Truitt, S., Metropolitansky, D., Ness, R. O., & Larson, J. (2024). *From local to global: A Graph RAG approach to query-focused summarization* (arXiv:2404.16130) [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2404.16130

Guo, Z., Xia, L., Yu, Y., Ao, T., & Huang, C. (2025). LightRAG: Simple and fast retrieval-augmented generation. In *Findings of the Association for Computational Linguistics: EMNLP 2025* (pp. 10746–10761). Association for Computational Linguistics. https://doi.org/10.18653/v1/2025.findings-emnlp.568

Gutiérrez, B. J., Shu, Y., Gu, Y., Yasunaga, M., & Su, Y. (2024). HippoRAG: Neurobiologically inspired long-term memory for large language models. *Advances in Neural Information Processing Systems, 37*. https://proceedings.neurips.cc/paper_files/paper/2024/hash/6ddc001d07ca4f319af96a3024f6dbd1-Abstract-Conference.html

Gutiérrez, B. J., Shu, Y., Qi, W., Zhou, S., & Su, Y. (2025). From RAG to memory: Non-parametric continual learning for large language models. *Proceedings of the 42nd International Conference on Machine Learning, 267*, 21497–21515. https://proceedings.mlr.press/v267/gutierrez25a.html

Lee, C., Roy, R., Xu, M., Raiman, J., Shoeybi, M., Catanzaro, B., & Ping, W. (2025). NV-Embed: Improved techniques for training LLMs as generalist embedding models. *International Conference on Learning Representations*. https://openreview.net/forum?id=lgsyLSsDRe

Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., Küttler, H., Lewis, M., Yih, W.-T., Rocktäschel, T., Riedel, S., & Kiela, D. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. *Advances in Neural Information Processing Systems, 33*, 9459–9474. https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html

Sarthi, P., Abdullah, S., Tuli, A., Khanna, S., Goldie, A., & Manning, C. D. (2024). RAPTOR: Recursive abstractive processing for tree-organized retrieval. *International Conference on Learning Representations*. https://openreview.net/forum?id=GN921JHCRw
