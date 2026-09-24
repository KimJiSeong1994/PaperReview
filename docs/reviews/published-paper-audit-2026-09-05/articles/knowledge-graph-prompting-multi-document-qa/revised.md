# Knowledge Graph Prompting for Multi-Document Question Answering

**Paper:** Yu Wang; Nedim Lipka; Ryan A. Rossi; Alexa Siu; Ruiyi Zhang; Tyler Derr (2024). "Knowledge Graph Prompting for Multi-Document Question Answering". https://doi.org/10.1609/aaai.v38i17.29889 · arXiv:2308.11730

**Abstract:** Multi-document question answering에서는 질문과 가장 비슷한 passage 하나를 찾는 것만으로 충분하지 않다. 첫 번째 passage에서 발견한 단서가 다음에 찾아야 할 문서를 결정하기 때문이다. KGP는 이 문제를 passage retrieval이 아니라 **문서 그래프 위의 탐색 문제**로 다시 정의한다. Passage·page·table을 node로 만들고, 공통 keyword·embedding similarity·공통 Wikipedia entity·문서 구조 관계를 edge로 연결한다. 질의 시에는 fine-tuned T5가 현재까지 찾은 근거를 읽고 “다음에 필요한 근거”를 생성하며, graph의 이웃 중 그 근거와 가장 가까운 passage를 방문한다. 저자 보고 기준 KGP-T5는 golden-context oracle을 제외한 평균 순위에서 가장 높았고, 2WikiMQA와 MuSiQue에서 강한 결과를 냈다. 그러나 IIRC에서는 MDR보다 낮았고, 구조 질문의 67% Struct-EM은 비교 baseline 없이 보고됐다. 실험 그래프도 질문마다 구성된 12개 문서 집합에 한정된다. 따라서 KGP의 의의는 대규모 지식 그래프를 완성했다는 데 있지 않다. **LLM이 만든 중간 추론을 자유 검색 질의로 쓰지 않고 graph neighborhood 안에서 검증 가능한 passage 선택으로 제한한 초기 Graph RAG 설계**라는 데 있다.

---

## 핵심 요약

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 여러 문서에 흩어진 근거와 page·table 같은 구조를 LLM prompt에 어떻게 순차적으로 모을 것인가? |
| 핵심 표현 | Passage, page, table을 node로 두고 lexical·semantic·entity·structural relation을 edge로 만든 document graph다. |
| 검색 방식 | TF-IDF seed에서 시작해 LLM이 다음 evidence를 생성하고, 현재 node의 이웃 가운데 가장 가까운 passage를 선택한다. |
| 대표 결과 | KGP-T5 F1은 HotpotQA 66.77, IIRC 41.54, 2WikiMQA 53.50, MuSiQue 41.19다. 평균 순위는 oracle 제외 최고지만 모든 dataset·metric에서 이긴 것은 아니다. |
| 핵심 경계 | 질문마다 12개 문서로 graph를 만들었고, passage graph의 대규모 확장성·TAGME 구축 비용·dataset transfer 문제가 남는다. |

## 목차

1. 왜 multi-document QA를 graph traversal로 보았는가
2. KGP의 graph는 전통적 knowledge graph와 무엇이 다른가
3. 문서 graph를 만드는 네 가지 방식
4. LLM-guided graph traversal의 작동 원리
5. 생성과 검색을 분리한 이유
6. 실험 설정과 결과
7. Graph density, branching factor, 확장성
8. 결과를 제한해서 해석해야 하는 이유
9. Graph RAG 계보에서 KGP의 위치
10. 결론

## 1. 왜 multi-document QA를 graph traversal로 보았는가

일반적인 retrieve-and-read RAG는 질문과 각 passage의 유사도를 계산하고 상위 context를 reader에 전달한다. 답이 한 passage에 직접 적혀 있다면 이 구조가 가장 단순하다. 그러나 multi-hop question은 첫 번째 근거를 찾은 뒤에야 다음 검색 대상이 드러난다.

예를 들어 “현재 *The Simpsons Theme* 편곡자의 출생 연도는?”이라는 질문을 생각해 보자. 첫 passage는 현재 편곡자가 Alf Clausen이라는 사실을 알려 준다. 두 번째 passage에서야 Alf Clausen의 생년을 찾을 수 있다. 두 passage 중 어느 하나도 질문 전체를 단독으로 해결하지 못한다.

논문은 multi-document 질문을 세 유형으로 나눈다.

![KGP가 다루는 bridging, comparing, structural question](/api/blog/figures/kgp-fig2-question-types.png)

*원논문 Figure 2. Bridging question은 근거를 순서대로 연결하고, comparing question은 서로 다른 문서의 근거를 병렬로 모으며, structural question은 page·table node를 직접 찾아간다. 주변 본문만 제거해 직접 인용했다. 출처: Wang et al. (2024), AAAI-24 PDF p. 2.*

| 질문 유형 | 필요한 검색 | 단일 vector retrieval의 약점 |
| --- | --- | --- |
| Bridging | 첫 근거의 entity를 이용해 다음 passage를 찾는다. | 원 질문과 두 번째 passage의 직접 유사도가 낮을 수 있다. |
| Comparing | 두 개 이상의 독립적인 evidence branch를 모은다. | 상위 결과가 한쪽 entity에 편중될 수 있다. |
| Structural | 특정 page나 table의 내용을 가져온다. | Page 번호나 table 위치는 semantic similarity만으로 표현하기 어렵다. |

KGP의 답은 graph다. Passage 사이에 미리 edge를 만들어 두면 첫 번째 근거에서 다음 후보로 이동할 수 있다. Page와 table을 node로 추가하면 “Table 2”처럼 문서 구조를 직접 지칭하는 질문도 같은 retrieval interface에서 처리할 수 있다.

다만 여기서 graph는 답을 직접 생성하는 symbolic knowledge base가 아니다. **다음에 읽을 원문 passage의 후보 공간을 제한하는 retrieval index**다.

## 2. KGP의 graph는 전통적 knowledge graph와 무엇이 다른가

전통적인 knowledge graph는 entity를 node로, relation triple을 edge로 표현한다. KGP는 이보다 text에 가깝다.

$$
G=(\mathcal{V},\mathcal{E}),
\qquad
\mathcal{V}=\{v_i\}_{i=1}^{n}
$$

Node $v_i$는 entity가 아니라 passage, page, table 같은 문서 단위다. Node feature $\mathcal{X}_i$도 passage text, markdown table, page pointer처럼 원문에 가까운 표현이다.

$$
\mathcal{E}
\subseteq
\mathcal{V}\times\mathcal{V}
$$

Edge는 다음 두 범주를 결합한다.

1. **내용 관계**: 공통 keyword, embedding similarity, 공통 Wikipedia entity
2. **구조 관계**: page가 어떤 passage와 table을 포함하는지 나타내는 directed edge

![KGP의 document graph construction](/api/blog/figures/kgp-fig3-kg-construction.png)

*원논문 Figure 3. 문서를 passage로 나눈 뒤 embedding 또는 bag-of-words 표현으로 passage edge를 만들고, page·table node와 구조 edge를 추가한다. 주변 본문만 제거해 직접 인용했다. 출처: Wang et al. (2024), AAAI-24 PDF p. 3.*

이 차이는 “knowledge graph”라는 이름을 읽을 때 중요하다. KGP는 corpus를 정제된 entity–relation triple 집합으로 변환하지 않는다. Relation extraction의 높은 비용과 domain dependency를 피하는 대신, passage-level similarity graph를 사용한다. 따라서 장점은 원문 보존과 범용성이고, 대가는 graph가 질문에 불필요한 연결까지 많이 포함할 수 있다는 점이다.

## 3. 문서 graph를 만드는 네 가지 방식

논문은 하나의 graph constructor를 정답으로 제시하지 않는다. 서로 다른 edge 생성 방식을 비교한다.

| 구성 방식 | Edge 기준 | 장점 | 논문이 확인한 한계 |
| --- | --- | --- | --- |
| TF-IDF | Passage가 추출 keyword를 공유하는가 | Domain-specific extractor가 필요 없다. | 질문과 무관한 공통어도 edge를 만든다. |
| KNN-ST | Sentence Transformer embedding similarity | Lexical overlap이 없어도 semantic neighbor를 만든다. | 일반 embedding similarity가 QA의 논리적 순서를 보장하지 않는다. |
| KNN-MDR | Next-supporting-fact prediction으로 학습한 embedding similarity | Multi-hop 순서를 반영하는 edge를 만들 수 있다. | 순서가 주석된 supporting fact가 필요하고 domain shift에 민감하다. |
| TAGME | Passage가 공통 Wikipedia entity를 언급하는가 | Wikipedia entity 연결에는 강하다. | Wikipedia 밖의 domain에 제한적이며 entity extraction이 느리다. |

TF-IDF는 문서 제목을 keyword 집합에 추가한다. 제목 entity를 묻는 질문에서 passage 사이의 다리를 놓기 위해서다. KNN-ST는 off-the-shelf sentence transformer를 사용한다. KNN-MDR은 이미 찾은 supporting fact에서 다음 supporting fact를 예측하도록 encoder를 학습해, 단순 의미 유사성보다 “다음 근거가 될 가능성”을 embedding에 넣으려 한다.

주 실험 graph에는 TAGME가 사용됐다. 이는 성능표를 일반 domain의 범용 passage graph 결과로 곧바로 읽기 어렵게 만든다. TAGME는 Wikipedia entity에 기대며, 부록은 12개 Wikipedia 문서의 entity를 추출하는 데 8시간 이상, 병렬 처리 후에도 2시간 이상이 걸렸다고 보고한다.

Graph가 조밀할수록 supporting fact가 seed의 이웃에 들어올 가능성은 높아진다. 그러나 관련 없는 이웃도 함께 늘어난다.

![Graph density에 따른 supporting-fact coverage와 precision trade-off](/api/blog/figures/kgp-fig5-kg-quality.png)

*원논문 Figure 5. HotpotQA에서 graph가 조밀해질수록 Supporting Fact Exact Match는 높아지지만 precision은 낮아진다. 실선은 precision, 점선은 평균 이웃 수를 나타낸다. 주변 본문만 제거해 직접 인용했다. 출처: Wang et al. (2024), AAAI-24 PDF p. 4.*

여기서 중요한 점은 graph construction만으로 retrieval 문제가 해결되지 않는다는 사실이다. High recall graph는 필요한 passage를 어딘가에 포함하지만, 어느 이웃을 방문할지는 알려 주지 않는다. KGP의 두 번째 구성요소인 traversal agent가 필요한 이유다.

## 4. LLM-guided graph traversal의 작동 원리

KGP는 질문을 먼저 content-based와 structure-based로 분류한다.

- **Structure-based question**: `Page 1`, `Table 2` 같은 구조 표현을 추출하고 해당 node의 content를 가져온다.
- **Content-based question**: TF-IDF로 seed passage를 찾고 graph traversal을 시작한다.

![KGP의 LLM-guided traversal agent](/api/blog/figures/kgp-fig4-traversal-agent.png)

*원논문 Figure 4. 왼쪽은 page node를 찾는 structural retrieval, 오른쪽은 현재 evidence에서 다음 evidence를 생성하고 graph neighbor와 대조하는 content retrieval이다. 주변 본문만 제거해 직접 인용했다. 출처: Wang et al. (2024), AAAI-24 PDF p. 4.*

Content traversal의 핵심은 두 단계다.

### 4.1 LLM이 다음 evidence를 예측한다

현재까지 방문한 passage를 이어 붙여 fine-tuned LLM $f$에 넣는다. LLM은 최종 답을 바로 쓰는 대신, 질문을 해결하려면 다음에 어떤 passage가 필요할지를 자연어로 생성한다.

### 4.2 생성문과 실제 neighbor를 대조한다

현재 candidate neighborhood를 $\mathcal{N}_j$라 하면 다음 node는 원논문의 Equation 1로 선택된다.

$$
s_{j+1}
=
\underset{v\in\mathcal{N}_j}{\operatorname{arg\,max}}
\;\phi\!\left(
g(\mathcal{X}_v),
f\!\left(\mathop{\Vert}_{k=0}^{j}\mathcal{X}_k\right)
\right)
$$

$f$는 현재 evidence에서 다음 evidence를 생성하고, $g$는 candidate passage를 비교 가능한 표현으로 바꾼다. $\phi$는 embedding inner product 또는 textual similarity다. 본문 수식은 질문 $q$를 명시하지 않지만 Figure 4와 Algorithm 1에서는 질문과 현재 passage를 함께 traversal agent에 전달한다.

이 설계는 LLM hallucination을 없애지 않는다. 논문의 예시에서 LLM은 Alf Clausen의 생일을 잘못 생성한다. KGP는 그 생성문을 답으로 사용하지 않는다. 생성문과 가장 비슷한 **실제 corpus neighbor**를 선택하고, 최종 reader에는 그 원문 passage를 전달한다.

이를 간단히 재구성하면 다음과 같다.

```text
seed_paths ← TF-IDF(question)
candidate_queues ← neighbors(seed_paths)

while retrieved_passages < context_budget:
    path, candidates ← dequeue()
    next_evidence ← traversal_LM(question, path)
    next_nodes ← rank(candidates, next_evidence)

    for node in next_nodes:
        enqueue(path + node, neighbors(node))

return retrieved_paths
```

*위 pseudocode는 원논문 Algorithm 1의 작동 흐름을 설명하기 위한 재구성이다.*

## 5. 생성과 검색을 분리한 이유

KGP는 LLM을 **navigator**로 사용하지만 **source of truth**로 사용하지 않는다. 이 분리가 method의 핵심이다.

| 단계 | LLM이 담당하는 일 | Graph·corpus가 담당하는 일 |
| --- | --- | --- |
| Reasoning | 현재 근거에서 다음에 필요한 evidence를 언어로 예측한다. | 가능한 이동을 현재 node의 neighbor로 제한한다. |
| Retrieval | Candidate를 직접 만들어 내지 않는다. | 실제 passage 가운데 생성 evidence와 가장 가까운 node를 선택한다. |
| Answering | Retrieved context를 읽고 최종 답을 생성한다. | 최종 답의 grounding context를 제공한다. |

IRCoT도 reasoning과 retrieval을 번갈아 수행하지만, 생성된 chain-of-thought를 새로운 검색 질의로 사용한다. KGP는 검색 공간을 graph neighborhood로 제한한다. 반대로 MDR은 다음 passage를 찾는 sequential bias를 dense encoder에 학습하지만, 자연어 evidence generator를 별도로 두지 않는다.

이 구조는 자유로운 LLM search와 고정된 retriever 사이의 절충이다. LLM은 다음 hop의 의미를 만들고, graph는 그 의미가 corpus 밖으로 벗어나지 않도록 후보를 제한한다. 그러나 seed가 잘못됐거나 정답 passage가 현재 neighborhood에 없으면 LLM이 올바른 다음 evidence를 생성해도 회수할 수 없다. Graph recall과 traversal policy가 동시에 맞아야 한다.

## 6. 실험 설정과 결과

### 6.1 평가 corpus는 질문마다 만든 12개 문서 집합이다

실험은 HotpotQA, IIRC, 2WikiMQA, MuSiQue의 development question을 표본으로 사용한다. 각 질문에 대해 supporting fact가 있는 Wikipedia 문서와 무작위 negative 문서를 합쳐 12개 문서 collection을 만들고, 그 collection마다 graph를 구성한다.

| Dataset | 질문 수 | 평균 passage 수 | 평균 edge 수 |
| --- | ---: | ---: | ---: |
| HotpotQA | 500 | 715.22 | 70,420.68 |
| IIRC | 477 | 1,120.55 | 143,136.17 |
| 2WikiMQA | 500 | 294.19 | 19,235.15 |
| MuSiQue | 500 | 748.04 | 97,931.28 |

구조 질문은 내부 PDFTriage dataset으로 평가한다. Wikipedia 계열 graph에는 passage node만 있고, PDFTriage graph에만 page·table node가 추가된다.

모든 retrieval baseline은 최종 context를 30개 passage로 맞췄고, 공통 downstream reader로 ChatGPT를 사용했다. KGP 계열은 첫 hop에서 10개 passage, 두 번째 hop에서 각각 3개를 선택해 30개 reasoning path를 만든다. 이 통제는 reader 차이를 줄이지만, 각 framework의 원래 최적 구성과 동일한 비교라는 뜻은 아니다.

### 6.2 평균 순위는 높지만 모든 dataset에서 이긴 것은 아니다

| Method | HotpotQA F1 | IIRC F1 | 2WikiMQA F1 | MuSiQue F1 | 평균 순위* |
| --- | ---: | ---: | ---: | ---: | ---: |
| TF-IDF | 64.64 | 40.80 | 44.50 | 32.50 | 5.00 |
| DPR | 62.11 | 41.85 | 51.10 | 31.64 | 5.50 |
| MDR | 65.16 | **43.47** | 52.44 | 37.03 | 3.08 |
| IRCoT | 64.12 | 41.65 | 50.17 | 34.21 | 4.08 |
| **KGP-T5** | **66.77** | 41.54 | **53.50** | **41.19** | **2.75** |

*평균 순위는 논문 Table 1의 PDFTriage 제외 열이다. Golden context는 oracle이므로 비교 대상에서 제외했다.*

KGP-T5는 HotpotQA, 2WikiMQA, MuSiQue F1에서 가장 높다. 특히 MuSiQue F1은 MDR 37.03에서 41.19로 4.16 points 높다. 그러나 IIRC에서는 MDR 43.47보다 1.93 points 낮다. HotpotQA accuracy도 TF-IDF 76.64가 KGP-T5 76.53보다 0.11 point 높다. “모든 baseline을 일관되게 능가했다”기보다 **여러 지표를 합친 평균 순위가 가장 높고, sequential multi-hop benchmark 두 곳에서 강했다**고 읽는 편이 정확하다.

PDFTriage Struct-EM은 67.00이다. 그러나 다른 retrieval method는 해당 열에 값이 없고 Golden context만 100.00으로 제시된다. 따라서 이 숫자는 structural node retrieval의 가능성을 보여 주는 절대 성능이지, 기존 방법 대비 우위를 입증하는 비교 결과는 아니다.

### 6.3 Traversal model은 크기보다 task alignment가 중요했다

| Traversal agent | HotpotQA F1 | 2WikiMQA F1 | MuSiQue F1 |
| --- | ---: | ---: | ---: |
| TF-IDF heuristic | 63.1 | 46.0 | 32.9 |
| MDR | 65.8 | 51.3 | 41.1 |
| ChatGPT | 66.6 | 49.4 | 38.7 |
| LLaMA-7B | 66.3 | 52.5 | 40.0 |
| **T5-Large** | **66.8** | **53.5** | **41.2** |

T5-Large는 더 큰 LLaMA-7B와 ChatGPT보다 평균적으로 강했다. 저자들은 traversal task에 맞춘 fine-tuning과 필요한 data 규모 차이를 이유로 추정한다. 이 결과가 일반적인 T5 우위를 뜻하지는 않는다. 평가한 것은 “현재 evidence에서 다음 supporting fact를 예측하는” 좁은 navigation task다.

## 7. Graph density, branching factor, 확장성

KGP는 graph를 조밀하게 만들수록 좋아지는 시스템이 아니다. Density가 높아지면 supporting fact가 이웃에 들어올 확률은 커지지만 candidate matching latency와 noise도 증가한다.

Branching factor도 같은 trade-off를 가진다. 한 node에서 더 많은 이웃을 선택하면 reasoning path의 다양성이 늘어난다. 그러나 context budget을 30으로 고정했기 때문에 branch를 늘릴수록 초기 seed 수가 줄고 전체 graph coverage가 낮아진다. 2WikiMQA와 MuSiQue 모두 branching factor 3 부근에서 가장 높은 성능을 보이고 이후 하락한다.

![KGP branching factor 및 문서 수 민감도](/api/blog/figures/kgp-fig7-sensitivity-scale.png)

*원논문 Figure 7. (a)–(b)는 branching factor가 지나치게 커지면 성능이 다시 낮아짐을, (c)는 문서 수가 늘어날 때 KGP와 baseline의 성능·시간 변화를 보여 준다. (a)–(b)는 각 dataset의 100개 표본 평균이다. 주변 본문만 제거해 직접 인용했다. 출처: Wang et al. (2024), AAAI-24 PDF p. 7.*

저자들은 traversal을 BFS와 neighborhood ranking의 결합으로 보고 다음 시간 복잡도를 제시한다.

$$
\mathcal{O}\!\left((|\mathcal{V}|+|\mathcal{E}|)\,\hat d\,\gamma\right)
$$

$\hat d$는 평균 degree, $\gamma$는 candidate passage와 reasoning path의 similarity 계산 비용이다. 부록은 passage-node graph가 극단적으로 커질 때 잘 확장되지 않는다고 직접 인정한다. 다만 사용자가 관리하는 문서가 보통 10–100개라고 가정해 1,000–10,000 node 범위는 감당할 수 있다고 본다.

이 가정은 KGP를 MS GraphRAG와 같은 corpus-wide global index로 읽지 말아야 하는 이유다. 논문의 실험 단위는 12개 문서이며, Figure 7(c)도 최대 100개 문서다. 수백만 passage, 지속적인 update, 중복 entity 통합을 평가한 결과가 아니다.

## 8. 결과를 제한해서 해석해야 하는 이유

### 8.1 Graph quality는 domain transfer에 민감하다

HotpotQA에서 학습한 KNN-MDR graph는 같은 dataset에서 KNN-ST보다 좋은 coverage–precision trade-off를 보였다. 그러나 MuSiQue에서는 순서가 뒤집혔다. 부록은 이를 HotpotQA에서 MuSiQue로의 distribution shift 때문이라고 설명한다. “Reasoning-aware embedding”도 학습 domain 밖에서 자동으로 논리 관계를 보존하지 않는다.

### 8.2 주 실험의 강한 graph는 Wikipedia-specific하다

TAGME는 공통 Wikipedia entity를 edge로 사용한다. Wikipedia 기반 QA에서는 자연스럽지만 법률 계약서, 사내 보고서, 과학 논문처럼 entity catalog가 다르거나 용어가 새로 생기는 domain에는 그대로 적용하기 어렵다. TF-IDF와 KNN-ST는 domain 제한이 덜하지만, 질문에 필요한 논리 관계를 edge가 표현한다는 보장은 약하다.

### 8.3 Structural QA 근거는 탐색적이다

PDFTriage는 저자 측 내부 dataset이며 본 논문 표에서는 질문 수와 경쟁 baseline이 분리 보고되지 않는다. 67% Struct-EM은 page·table node를 graph에 넣는 아이디어가 작동할 수 있음을 보여 주지만, 일반 document QA에서 우수하다는 결론에는 부족하다. 긴 table은 ChatGPT input limit 때문에 markdown 변환이 적합하지 않다는 한계도 부록에 명시돼 있다.

### 8.4 Retrieval과 reasoning을 완전히 분리하지 않았다

KGP는 retrieval method이면서도 supporting-fact 순서로 fine-tuned한 T5를 사용한다. 성능 향상이 graph topology에서 얼마나 오고, next-evidence supervision에서 얼마나 오는지 완전히 분리되지 않는다. Table 2는 heuristic보다 learned traversal이 강함을 보여 주지만, graph 없는 동일 T5 sequential retriever와의 직접 ablation은 주 표에서 명확하지 않다.

### 8.5 통계적 불확실성이 보고되지 않았다

표본은 dataset마다 약 500개 질문이고 결과표에는 confidence interval이나 significance test가 없다. HotpotQA accuracy의 0.11 point처럼 작은 차이는 안정적인 우위로 해석할 근거가 없다. 반면 MuSiQue F1의 4.16-point 차이는 더 크지만, 동일한 graph와 reader 설정을 다른 corpus에서 재현하기 전까지는 저자 보고 범위로 한정해야 한다.

## 9. Graph RAG 계보에서 KGP의 위치

KGP는 이후의 Graph RAG와 graph 사용 목적이 다르다.

| 방법 | Graph의 node | Query-time 핵심 연산 | 주로 겨냥한 문제 |
| --- | --- | --- | --- |
| KGP | Passage, page, table | LLM이 다음 evidence를 만들고 neighbor를 선택 | Multi-document·structural QA |
| MS GraphRAG | Entity, relation, community, community report | Community summary를 map-reduce | Corpus 전체를 묻는 global query |
| HippoRAG | OpenIE phrase/entity와 passage 연결 | Query-seeded Personalized PageRank | Cross-passage association과 multi-hop retrieval |
| LightRAG | Entity, relation, text chunk | Low-level·high-level dual retrieval | 가벼운 graph index와 증분 검색 |

KGP의 graph는 “무엇이 중요한 community인가”를 요약하지 않는다. 대신 현재 passage에서 어디로 이동할지를 정한다. HippoRAG처럼 전체 graph에 확률을 확산하지도 않는다. Queue에 담긴 reasoning path마다 LLM이 다음 evidence를 예측하고 local neighborhood를 순회한다.

이 차이 때문에 KGP는 Graph RAG의 초기형으로 의미가 있다. Graph를 정답 생성기나 global summarization layer로 사용하기 전에, **LLM의 반복 retrieval을 구조적으로 제한하는 navigation substrate**로 사용했다. 이후 연구는 이 local agent traversal을 PPR diffusion, entity graph, community hierarchy, dense fallback과 다른 방식으로 대체하거나 결합한다.

## 10. 결론

KGP의 출발점은 단순하다. Multi-document QA에서는 다음에 찾아야 할 passage가 현재까지 읽은 evidence에 따라 달라진다. 저자들은 passage·page·table을 graph node로 만들고, LLM이 다음 evidence를 예측하도록 학습한 뒤, 그 예측을 실제 neighbor passage와 대조했다.

이 설계의 가장 중요한 부분은 LLM이 만든 문장을 그대로 사실로 사용하지 않는다는 점이다. LLM은 탐색 방향을 제안하고, graph는 후보 공간을 제한하며, 원문 passage가 최종 context가 된다. 생성 모델의 유연성과 retrieval index의 근거성을 분리하려는 구조다.

저자 실험에서 KGP-T5는 2WikiMQA와 MuSiQue에서 강했고 평균 순위도 가장 높았다. 그러나 IIRC에서는 MDR보다 낮았으며, structural QA에는 직접 비교할 baseline이 없다. Graph는 질문마다 12개 문서로 구성됐고, TAGME의 domain dependency와 구축 비용, passage graph의 대규모 확장성도 남는다.

따라서 KGP를 “knowledge graph가 vector search를 이겼다”는 논문으로 요약하면 핵심을 놓친다. 더 정확한 결론은 다음과 같다.

1. Multi-hop retrieval에는 질문–passage 유사도 외에 passage 사이의 이동 구조가 필요할 수 있다.
2. Graph recall을 높이면 noise도 함께 증가하므로 query-conditioned traversal이 필요하다.
3. LLM generation은 답이 아니라 다음 evidence의 description으로 사용할 수 있다.
4. 생성된 evidence를 corpus neighbor와 대조하면 hallucination을 retrieval signal로 바꿀 수 있다.
5. 이 접근의 효과는 graph construction domain, candidate neighborhood, context budget, traversal supervision에 의존한다.

KGP가 남긴 가장 지속적인 아이디어는 graph 자체보다 **reasoning과 retrieval의 접점**이다. 다음 추론을 자유롭게 생성하되, 실제 이동은 검증 가능한 문서 graph 안에서만 허용한다. 이 원리는 이후 Graph RAG가 local traversal, graph diffusion, hybrid retrieval을 설계할 때 계속 되풀이된다.

## References

Edge, D., Trinh, H., Cheng, N., Bradley, J., Chao, A., Mody, A., Truitt, S., Metropolitansky, D., Ness, R. O., & Larson, J. (2024). *From local to global: A graph RAG approach to query-focused summarization* (arXiv:2404.16130) [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2404.16130

Gutiérrez, B. J., Shu, Y., Gu, Y., Yasunaga, M., & Su, Y. (2024). HippoRAG: Neurobiologically inspired long-term memory for large language models. *Advances in Neural Information Processing Systems, 37*. https://proceedings.neurips.cc/paper_files/paper/2024/hash/6ddc001d07ca4f319af96a3024f6dbd1-Abstract-Conference.html

Karpukhin, V., Oğuz, B., Min, S., Lewis, P., Wu, L., Edunov, S., Chen, D., & Yih, W.-T. (2020). Dense passage retrieval for open-domain question answering. In *Proceedings of the 2020 Conference on Empirical Methods in Natural Language Processing* (pp. 6769–6781). Association for Computational Linguistics. https://doi.org/10.18653/v1/2020.emnlp-main.550

Trivedi, H., Balasubramanian, N., Khot, T., & Sabharwal, A. (2023). Interleaving retrieval with chain-of-thought reasoning for knowledge-intensive multi-step questions. In *Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)* (pp. 10014–10037). Association for Computational Linguistics. https://doi.org/10.18653/v1/2023.acl-long.557

Wang, Y., Lipka, N., Rossi, R. A., Siu, A., Zhang, R., & Derr, T. (2024). Knowledge graph prompting for multi-document question answering. *Proceedings of the AAAI Conference on Artificial Intelligence, 38*(17), 19206–19214. https://doi.org/10.1609/aaai.v38i17.29889
