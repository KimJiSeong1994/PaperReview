# LinearRAG: Linear Graph Retrieval Augmented Generation on Large-scale Corpora

**Paper:** Luyao Zhuang; Shengyuan Chen; Yilin Xiao; Huachi Zhou; Yujing Zhang; Hao Chen; Qinggang Zhang; Xiao Huang (2025). "LinearRAG: Linear Graph Retrieval Augmented Generation on Large-scale Corpora". https://arxiv.org/abs/2510.10114 · arXiv:2510.10114v4

**Abstract:** 논문의 출발점은 GraphRAG가 종종 순진한(naive) RAG보다도 못하다는 관찰이고, 그 원인을 자동 구축된 지식 그래프의 품질 결함, 구체적으로는 관계 추출의 국소 부정확성과 전역 비일관성에 돌린다. 처방은 단순하다. 삼중항(triple)을 뽑지 말고 엔티티만 뽑아, 엔티티-문장·엔티티-문단이라는 두 개의 이분 인접행렬만으로 Tri-Graph를 만든다. 그래프 구성에 LLM이 개입하지 않으므로 토큰 소비가 0이고, 시간·메모리가 코퍼스 크기에 선형이라는 것이 이름의 근거다. 검색은 두 단계로, 질의-문장 유사도로 가중된 전파로 중간 엔티티를 활성화한 뒤(1단계), 활성화된 엔티티를 씨앗으로 엔티티-문단 이분 그래프에서 personalized PageRank를 돌려 문단을 뽑는다(2단계). 네 데이터셋(HotpotQA, 2Wiki, MuSiQue, Medical)에서 저자들은 모든 열에서 최고 정확도를 보고하며, 2WikiMultiHopQA 색인 시간 249.78초·토큰 0, ATLAS-Wiki 10M 토큰 코퍼스에서 RAPTOR 대비 15.1배 색인 가속을 함께 보고한다. 정확도 이득의 폭(데이터셋에 따라 0.90–3.80%p)과 비용 절감의 폭(수 배에서 수십 배)은 크기가 다른 주장이므로 나누어 읽어야 한다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | GraphRAG의 색인 단계에서 관계 추출을 제거해도 다중홉 검색 성능을 유지할 수 있는가? 그렇다면 색인 비용은 얼마나 줄어드는가? |
| 핵심 기여 | (1) 관계 없는(relation-free) 계층 그래프 Tri-Graph를 spaCy NER과 의미 연결만으로 구성해 LLM 토큰 소비를 0으로 만든다. (2) 의미 브리징 기반 엔티티 활성화와 전역 중요도 집계라는 2단계 검색을 얹어 단일 패스 다중홉 검색을 수행한다. |
| 방법적 결과 | 그래프는 엔티티-문장 mention 행렬 $M$과 엔티티-문단 contain 행렬 $C$ 두 개로 환원된다. 1단계는 $M$ 위에서 질의-문장 유사도로 가중한 최대값 전파를, 2단계는 $C$ 위에서 개인화 초기값을 준 PageRank를 돌린다. 구축 $O(\lvert P\rvert \cdot T)$, 질의당 검색 $O(\lvert P\rvert)$. |
| 실험 결과 | 저자 보고 기준 Table 1의 7개 정확도 열 전부에서 1위. 2Wiki GPT-Acc 63.70%(2위 대비 +3.80%p), HotpotQA GPT-Acc 66.50%(+0.90%p). 2Wiki 색인 249.78초·토큰 0으로 가장 빠르며, ATLAS-Wiki 10M에서 RAPTOR 대비 15.1배 가속. |
| 핵심 한계 | 정확도 이득은 데이터셋별로 0.90–3.80%p이고 분산·유의성 보고가 없다. 검색 지연은 E2GraphRAG(0.053초)·RAPTOR(0.062초)보다 느린 0.093초다. 식 7의 $L_{e_i}$와 $W_p$는 정의·값이 제시되지 않고, 임계 $\delta$ 값은 본문(4)과 그림 축(0.2–0.8)이 어긋난다. 검색 품질 표(Table 4)에서 recall 1위는 네 과제 중 하나뿐이며, 관련연구에서 세 번째 계열로 소개한 추론 강화 RAG와는 비교하지 않는다. |

## 목차

1. 배경과 문제의식
2. 예비 연구: 그래프 품질의 두 결함
3. Tri-Graph: 토큰을 쓰지 않는 그래프 구성
4. 1단계 검색: 의미 브리징을 통한 엔티티 활성화
5. 2단계 검색: 전역 중요도 집계
6. "선형"의 정확한 의미와 복잡도 논증
7. 실험 설계
8. 결과 1: 생성 정확도
9. 결과 2: 시간과 토큰
10. 검색 품질, 절제 연구, 민감도
11. 한계와 해석 범위
12. 결론

## 1. 배경과 문제의식

논문이 겨냥하는 문제는 GraphRAG 계열의 색인 단계다. 표준 RAG는 문서를 청크로 자르고 임베딩해 색인하는데, 이 절단이 맥락을 잃게 만들어 여러 문서에 걸친 추론에서 불리하다는 것이 GraphRAG의 출발점이었다. RAPTOR는 재귀적 군집화와 요약으로 트리를 세우고, Microsoft GraphRAG는 커뮤니티 탐지와 LLM 요약으로 계층을 만든다. G-Retriever는 부분그래프 검색을 Prize-Collecting Steiner Tree 최적화로 정식화하고, LightRAG는 이중 수준 색인을, GFM-RAG는 질의 의존 GNN 검색기를 얹는다. HippoRAG와 HippoRAG2는 삼중항 그래프 위에서 personalized PageRank로 다중홉 검색을 수행한다. 논문은 이 계보를 서두에 정리한 뒤, 이들 모두가 공유하는 전제를 문제 삼는다. 코퍼스를 (주어, 관계, 목적어) 형태의 구조로 요약해야 한다는 전제다.

![RAG의 세 패러다임](/api/blog/figures/linearrag-fig1-three-paradigms.png)
*그림 1. 세 가지 RAG 패러다임. (a) Naive RAG는 청킹-인코딩-검색으로 문단을 뽑는다. (b) GraphRAG는 NER 후 관계 추출로 지식 그래프를 만들고 부분그래프를 검색한다. (c) LinearRAG는 관계 추출 자리에 의미 연결(semantic linking)을 놓아 Tri-Graph를 만들고, 부분그래프가 아니라 원 문단을 검색한다. 원 논문 Figure 1에서 crop. 출처: Zhuang et al. (2025), arXiv:2510.10114.*

그림 1의 대비가 논문의 주장 전부를 압축한다. (b)와 (c)의 차이는 두 곳이다. 관계 추출이 의미 연결로 바뀌고, 검색 결과가 부분그래프가 아니라 원 문단이다. 첫 번째 변경은 색인 비용을, 두 번째 변경은 생성 단계에 들어가는 맥락의 성격을 바꾼다. 부분그래프를 넘기면 LLM은 삼중항을 읽어야 하지만, 원 문단을 넘기면 관계는 자연어 그대로 남아 LLM이 추론 시점에 해석한다.

논문은 이 설계를 두 개의 명제로 정리한다. 첫째, 문단 사이에 흩어진 정보를 잇는 일차 앵커는 관계가 아니라 정렬된 엔티티다. 둘째, 맥락적 관계는 원 문단 안에 가장 잘 보존되어 있으므로 명시적 관계 추출은 불필요하다. 두 명제를 받아들이면 색인 단계에서 LLM을 호출할 이유가 사라지고, 남는 것은 개체명 인식과 인접행렬 구성뿐이다.

---

## 2. 예비 연구: 그래프 품질의 두 결함

논문은 본론에 앞서 예비 연구를 배치해 "GraphRAG가 왜 자주 지는가"를 진단한다. GraphRAG-Bench의 Medical 데이터셋에서 vanilla RAG와 세 GraphRAG 방법을 세 지표로 비교한 결과가 근거다.

![GraphRAG의 성능 저하와 관계 추출 오류의 두 유형](/api/blog/figures/linearrag-fig2-graphrag-degradation.png)
*그림 2. (a) Medical 데이터셋에서 vanilla RAG(Top-5)와 GraphRAG 베이스라인의 evidence recall·context relevance·accuracy 비교. (b) 관계 추출이 만드는 두 유형의 오류. 원 논문 Figure 2에서 crop. 출처: Zhuang et al. (2025), arXiv:2510.10114.*

수치는 이렇다. Evidence recall에서 RAPTOR 75.01%, HippoRAG 74.57%는 vanilla RAG(Top-5) 71.85%를 넘지만 LightRAG는 71.41%로 오히려 조금 낮다. Context relevance에서는 세 GraphRAG 방법이 모두 vanilla RAG의 62.87%에 못 미치며, LightRAG 36.86%, HippoRAG 42.64%, RAPTOR 54.61%로 벌어진다. 최종 정확도도 vanilla RAG 61.68%가 RAPTOR 55.75%, HippoRAG 55.04%, LightRAG 54.36%를 모두 앞선다. 저자들의 해석은 그래프 검색이 회수(recall)를 넓히는 대신 소음을 함께 끌어온다는 것이다. "기후변화 영향"을 묻는데 그래프 링크가 느슨하게 이어진 "경제 정책" 문단이 딸려 오는 식이다.

그래프 품질의 결함을 논문은 두 층위로 나눈다. 국소 부정확성(local inaccuracy)은 관계 추출 모델이 사실과 어긋나는 삼중항을 만드는 경우다. 그림 2(b)의 예시처럼 "Einstein did not win the Nobel Prize for his theory of relativity"라는 문장이 (Einstein, won Nobel Prize for, theory of relativity)로 뒤집힌다. 부정을 잃으면 의미가 반대가 된다. 전역 비일관성(global inconsistency)은 관계 추출이 문단 단위로 독립 수행되어 코퍼스 전체에서 조율되지 않는 데서 온다. "AI"에 대해 (AI, subcategory, UL), (AI, subcategory, NLP), (AI, subcategory, CV)가 나란히 생기면, NLP와 CV는 AI의 하위 분야이고 비지도학습은 그 안에서 쓰이는 기법이라는 위계가 뭉개진다.

논문은 여기서 한 걸음 더 나아가 관계 추출 자체의 타당성을 문제 삼는다(§2.3). 첫째, 정확하고 간결한 관계 삼중항을 뽑는 일은 계산적으로 비싸고 언어학적으로 어렵다. "Rachel reluctantly agreed to go running with Phoebe" 같은 문장은 의미 손실 없이 원자적 삼중항 하나로 환원되지 않는다. 마지못해(reluctantly)라는 태도가 어느 슬롯에도 들어가지 않는다. 둘째, 그럴 필요도 없다. 원문이 관계 의미를 온전한 맥락과 함께 이미 보존하고 있고, LLM은 추론 시점에 그것을 읽어낼 수 있다. 커뮤니티 요약이나 토픽 모델링으로 그래프 품질을 사후 보정하려는 시도들 역시 비지도 방식이라 오류 전파에 취약하며, 잘못된 엔티티 관계가 상위 추상 수준에서 증폭된다는 것이 논문의 진단이다.

이 예비 연구의 근거 범위는 좁다는 점을 미리 적어 둔다. 그림 2(a)는 Medical 한 데이터셋, 세 GraphRAG 방법에서 얻은 것이고, 그림 2(b)는 정량화되지 않은 예시 두 개다. §2.2는 "fine-grained error analysis"를 수행했다고 적지만 오류율 수치는 제시되지 않는다. 뒤에서 보겠지만, "GraphRAG가 vanilla RAG보다 못하다"는 진단은 논문 자신의 Table 1에서도 Medical에서만 성립한다.

---

## 3. Tri-Graph: 토큰을 쓰지 않는 그래프 구성

구성 절차는 짧다. 코퍼스의 문단 집합 $P$가 주어지면, 각 문단을 구두점(마침표, 느낌표 등)으로 잘라 문장 집합 $S$를 얻는다. 그다음 spaCy 같은 경량 모델로 개체명 인식을 수행해 엔티티 집합 $E$를 얻는다. 문단·문장·엔티티가 각각 그래프의 노드 유형 $V_p$, $V_s$, $V_e$가 된다. 여기까지가 전부이고, 관계 추출은 없다.

간선은 포함 관계로만 정의한다. 문단 $p_i$가 엔티티 $e_j$를 포함하면 간선 $(V_{p_i}, V_{e_j})$를, 문장 $s_i$가 $e_j$를 언급하면 $(V_{s_i}, V_{e_j})$를 넣는다. 이것을 두 개의 이분 인접행렬로 적는다. contain 행렬 $C$는 $\lvert V_p\rvert \times \lvert V_e\rvert$ 크기로

$$C = [C_{ij}]_{\lvert V_p\rvert \times \lvert V_e\rvert}, \qquad C_{ij} = \mathbb{1}\{p_i \text{ contains } e_j\}$$

이고, mention 행렬 $M$은 $\lvert V_s\rvert \times \lvert V_e\rvert$ 크기로

$$M = [M_{ij}]_{\lvert V_s\rvert \times \lvert V_e\rvert}, \qquad M_{ij} = \mathbb{1}\{s_i \text{ mentions } e_j\}$$

이다. 두 행렬 모두 0/1 지시 행렬이고, 관계 유형이라는 축이 없다. 논문이 자기 그래프를 "relation-free"라고 부르는 근거가 이것이다. 그래프라기보다 두 개의 발생 행렬(incidence matrix)에 가깝다.

이 설계에서 따라오는 성질이 세 가지다. 첫째, 증분 갱신이 자연스럽다. 새 문단이 들어오면 그 문단만 문장 분할·NER·간선 구성을 거치면 되고, 기존 구조를 다시 계산할 필요가 없다. 커뮤니티 탐지를 다시 돌려야 하는 계층형 방법과 대비되는 지점이다. 둘째, LLM 토큰이 들지 않는다. NER은 spaCy의 BERT 계열 경량 모델로 수행되며, OpenIE보다 정확하고 빠르다는 것이 논문의 주장이다. 셋째, $C$와 $M$은 본질적으로 희소해서 희소 형식으로 저장하면 메모리도 선형에 머문다. 논문이 부록 D에서 드는 희소성 근거는 문장당 엔티티가 대략 4개 이하, 문단당 10개 이하라는 관찰이다.

마지막으로 논문은 원 문단을 지식 운반체로 그대로 남기므로 구성이 "정보 무손실(information-lossless)"이라고 적는다. 이 표현의 사정거리는 정확히 짚어 둘 필요가 있다. 무손실인 것은 검색 결과로 반환되는 문단이지 색인이 아니다. 색인 쪽, 즉 검색 신호로 쓰이는 구조는 공기(co-occurrence)만 남긴 것이므로 관계 정보를 잃는다. 논문의 논지는 그 손실이 무해하다는 것이지 손실이 없다는 것이 아니다.

---

## 4. 1단계 검색: 의미 브리징을 통한 엔티티 활성화

관계를 지운 그래프에서 다중홉 질의를 어떻게 처리하는가가 이 논문의 진짜 설계 문제다. 질의에 직접 등장하는 엔티티만으로는 홉을 건널 수 없다. "Beatrice I의 남편은 어느 나라 사람인가"라는 질의에서 답으로 가는 다리는 질의에 없는 "Frederick Barbarossa"다. 논문은 이 중간 엔티티를 찾는 절차를 의미 브리징(semantic bridging)이라 부르고 세 단계로 나눈다.

![LinearRAG 파이프라인](/api/blog/figures/linearrag-fig3-pipeline.png)
*그림 3. LinearRAG의 전체 파이프라인. I. 오프라인 구성 단계에서 엔티티·문장·문단 노드로 Tri-Graph를 만들고, II. 온라인 검색 단계에서 엔티티-문장 부분그래프의 의미 브리징으로 엔티티를 활성화한 뒤 엔티티-문단 부분그래프에서 personalized PageRank로 문단을 검색한다. 원 논문 Figure 3에서 crop. 출처: Zhuang et al. (2025), arXiv:2510.10114.*

**초기 엔티티 활성화.** 질의 $q$에서 spaCy로 엔티티 $E_q$를 뽑고, 각각에 대해 그래프 안에서 가장 유사한 엔티티를 찾아 그 유사도를 활성화 점수로 준다.

$$a_q = [a_{q,i}]_{\lvert V_e\rvert \times 1}, \qquad a_{q,i} = \mathbb{1}_{\,i = \arg\max_{e_j \in V_e} \mathrm{sim}(e_q, e_j)} \cdot \mathrm{sim}(e_q, e_i)$$

질의 엔티티 하나당 그래프 엔티티 하나가 켜지고, 나머지는 0인 희소 벡터가 된다.

**질의-문장 관련도 분포.** 질의와 코퍼스의 모든 문장 사이 유사도를 벡터로 만든다.

$$\sigma_q = [\sigma_{q,i}]_{\lvert S\rvert \times 1}, \qquad \sigma_{q,i} = \mathrm{sim}(q, s_i)$$

이 벡터가 전파의 게이트 역할을 한다. 질의와 무관한 문장을 지나는 경로는 여기서 감쇠된다.

**의미 전파.** 활성화 벡터를 문장-엔티티 이분 그래프 위에서 갱신한다.

$$a^t_q = \mathrm{MAX}\big(M^{\top}(\sigma_q \odot (M a^{t-1}_q)),\; a^{t-1}_q\big)$$

식을 오른쪽부터 읽으면 동작이 분명하다. $M a^{t-1}_q$는 각 문장이 담고 있는 활성 엔티티 점수의 합, 즉 문장 수준 점수다. 여기에 $\sigma_q$를 원소별로 곱해 질의와 관련된 문장만 살린다. $M^{\top}$로 되돌리면 그 문장들에 등장하는 모든 엔티티가 점수를 받는다. 마지막 $\mathrm{MAX}$는 이전 반복의 점수와 비교해 큰 값을 유지한다. 결과적으로 이 갱신은 "질의와 관련된 문장을 매개로 한 두 걸음 이동"이며, 엔티티 → 문장 → 엔티티라는 경로가 한 번의 반복에 해당한다. 관계 유형 대신 문장 공기(co-occurrence)와 질의 관련도가 홉을 잇는다. 논문은 이를 GraphRAG 계열의 관계 매칭에 대응하는 "암묵적 관계 매칭"이라고 부른다.

비용 면에서 이 벡터화가 요점이다. $n$홉 활성화가 $n$번의 반복으로 끝나고, $n$은 대체로 4 이하다. 논문은 반복당 세 번의 행렬곱과 한 번의 MAX가 든다고 적는데, 식 5에 실제로 나타나는 행렬곱은 $M a^{t-1}_q$와 $M^{\top}(\cdot)$ 두 번이고 나머지 하나는 원소별 곱이다. 어느 쪽으로 세든 반복당 상수 개의 희소 연산이라는 결론은 같고, $M$과 $a^t_q$의 희소성 덕에 SpMM으로 대체할 수 있다는 지적도 유효하다.

**동적 가지치기.** 전파를 그대로 두면 탐색 공간이 지수적으로 커진다. 무관한 엔티티가 다음 반복의 씨앗이 되어 질의 의도에서 멀어지는 방향으로 표류한다. 논문은 각 전파 단계마다 임계 $\delta$를 두고, 관련도 점수가 $\delta$를 넘는 새 엔티티만 다음 반복으로 넘긴다. 임계를 넘는 새 엔티티가 하나도 없으면 전파가 자동 종료된다. 반복 횟수를 고정하지 않고 질의 복잡도에 맞춰 조절하는 장치이기도 하다. 부록 E.2의 민감도 분석에서 $\delta$의 그림 축은 0.2에서 0.8까지인데 본문은 "$\delta = 4$로 설정했다"고 적는다. 축의 범위를 보면 0.4를 뜻하는 것으로 읽는 편이 자연스럽다.

---

## 5. 2단계 검색: 전역 중요도 집계

1단계가 끝나면 질의와 의미적으로 연결된 엔티티 집합 $E_a$와 그 점수가 남는다. 2단계는 이 점수를 씨앗 삼아 엔티티-문단 이분 그래프에서 문단의 전역 중요도를 매긴다. 사용하는 알고리즘은 personalized PageRank이고, 논문이 적은 갱신식은 다음과 같다.

$$I(v_i) = (1-d) + d \cdot \sum_{v_j \in B(v_i)} \frac{I(v_j)}{\deg(v_j)}$$

$d$는 감쇠 계수(통상 0.85), $B(v_i)$는 $v_i$로 들어오는 노드 집합, $\deg(v_j)$는 $v_j$의 링크 수다. 개인화는 초기값으로 들어간다. 엔티티 노드의 초기 중요도는 1단계의 활성화 점수 $I(v_i \mid v_i \in V_e) = a_q^{(i)}$로 두고, 문단 노드의 초기 중요도는 다음 혼합식으로 준다.

$$I(v \mid v \in V_p) = \left(\lambda \cdot \mathrm{sim}(q, v) + \ln\left(1 + \sum_{e_i \in E_a} \frac{a_q^{(i)} \cdot \ln(1 + N_{e_i})}{L_{e_i}}\right)\right) \cdot W_p$$

두 항의 역할이 다르다. 왼쪽 $\mathrm{sim}(q, v)$는 질의와 문단 사이의 밀집 검색 점수, 즉 vanilla RAG가 쓰는 신호 그대로다. 오른쪽 항은 그 문단이 활성 엔티티를 얼마나, 어떤 엔티티를 담고 있는지를 집계한다. $N_{e_i}$는 문단 안에서 엔티티 $e_i$가 등장한 횟수이고 로그로 눌러 빈도의 지배를 막는다. $L_{e_i}$는 엔티티의 계층 수준으로 분모에 들어가며, $W_p$는 문단 노드 가중 계수다. $\lambda$는 두 신호의 저울이다. 부록 E.2의 민감도 분석에서 $\lambda$는 0.05처럼 작은 값에서 최적이었고, 저자들은 이를 엔티티 정보가 주 신호이고 DPR 유사도는 보조라는 뜻으로 읽는다. 최종적으로 문단은 PPR 점수 $I(v \mid v \in V_p)$로 정렬되어 상위 $k$개가 반환된다.

식 7에서 걸리는 대목이 둘 있다. $L_{e_i}$는 "엔티티의 계층 수준"이라고만 소개될 뿐 논문 어디에도 정의나 산출 방법이 없다. Tri-Graph는 엔티티·문장·문단이라는 노드 유형의 구분만 갖고 엔티티들 사이의 계층은 구성하지 않으므로, 엔티티마다 서로 다른 $L$ 값이 어디서 오는지 본문만으로는 알 수 없다. $W_p$ 역시 이름만 있고 값이 없다. 재현 관점에서 식 7은 완전히 명세되지 않은 채 남아 있다.

알고리즘 쪽에도 한 가지 간극이 있다. 위에 적힌 식 6은 텔레포트 항이 모든 노드에 대해 동일한 상수 $(1-d)$인 표준 PageRank 갱신식이다. Personalized PageRank는 이 항을 개인화 벡터 $(1-d)\,p_{v_i}$로 바꾸는 데서 개인화가 생긴다. 식 6처럼 균일 텔레포트를 쓰면, 수렴까지 반복할 경우 고정점은 초기값과 무관해지므로 1단계에서 계산한 씨앗 점수가 최종 순위에 남지 않는다. 개인화가 실제로 작동하려면 씨앗 점수가 텔레포트 벡터로 들어가거나 반복을 몇 회에서 끊어야 하는데, 논문은 어느 쪽도 명시하지 않는다. 구현에서는 개인화 벡터를 쓰고 있을 가능성이 높지만, 인쇄된 식과 서술 사이의 이 간극은 독자가 메워야 한다.

---

## 6. "선형"의 정확한 의미와 복잡도 논증

이름이 주장하는 바를 정확히 분리해 두는 편이 이 논문을 읽는 데 도움이 된다. 논문에서 "linear"는 두 가지 뜻으로 쓰인다.

첫째는 그래프 뷰의 형태다. 서론은 LinearRAG의 핵심 착상을 "복잡한 관계 그래프를 색인하기 쉬운 선형적 뷰로 단순화하는 것"이라고 적는다. 관계 유형이라는 축을 제거하면 그래프는 두 개의 이분 발생 행렬로 납작해지고, 그래프 알고리즘 대신 희소 선형대수로 다룰 수 있게 된다. 4절과 5절의 연산이 전부 행렬곱과 PageRank인 것이 이 뜻의 귀결이다.

둘째는 확장성이다. 부록 D가 "all-stage linear scalability"라는 제목으로 이 부분을 다룬다. 구성 단계는 문장 분할과 NER뿐이므로 시간 복잡도가 $O(\lvert P\rvert \cdot T)$이고($T$는 문단 평균 길이), LLM 토큰 소비가 없다. 메모리는 두 갈래다. 문단·엔티티·문장 임베딩은 코퍼스 크기에 선형이라 $O(\lvert P\rvert \cdot T)$이고, 두 인접행렬은 희소 저장으로 $O(\lvert P\rvert + \lvert S\rvert)$이며 문장 수가 문단 수에 비례하므로 $O(\lvert P\rvert)$로 정리된다. 합치면 $O(\lvert P\rvert \cdot T + \lvert P\rvert) = O(\lvert P\rvert \cdot T)$다. 검색 단계는 유사도 계산, SpMM 전파, PPR 반복으로 이루어지는데, 전파 스텝은 희소 행렬의 비영 원소 수 $O(\lvert S\rvert)$에, 이분 그래프 위 PPR은 간선 수 $O(\lvert P\rvert)$에 선형이므로 전체가 $O(\lvert P\rvert)$다.

여기서 두 가지를 구분해 읽어야 한다.

하나. 이 점근 차수는 vanilla RAG의 청킹·임베딩 색인과 같은 급이다. 그리고 관계 추출 기반 파이프라인도 문단마다 LLM을 한 번씩 부르는 구조라면 문단 수에 선형이다. 즉 LinearRAG가 초선형인 경쟁자를 선형으로 끌어내린 것이 아니다. 논문이 관련연구에서 확장성 문제를 직접 지목하는 대상은 관계 추출 계열이 아니라 클러스터링 기반 계층 구성이다. 대규모 그래프에 Louvain이나 Leiden을 적용하는 일이 실시간 응용에서 비현실적이라는 것이다. 관계 추출 계열에 대한 비판은 차수가 아니라 비용과 불안정성이다. 그러므로 LinearRAG의 실질적 차별점은 점근 차수가 아니라 상수 항이다. 문단당 LLM 호출이 문단당 spaCy 호출로 바뀌는 데서 오는 상수 절감이고, 9절에서 보듯 논문이 실제로 측정해 보이는 것도 정확히 이 상수다.

둘. 질의당 $O(\lvert P\rvert)$는 무조건 좋은 성질이 아니다. 식 4의 $\sigma_q$는 코퍼스의 모든 문장에 대한 질의 유사도를 요구하므로, 매 질의마다 전체 문장 임베딩을 훑는다. 문장 수는 문단 수보다 몇 배 많다. 근사 최근접 이웃 색인을 쓰는 밀집 검색이 질의당 준선형에 가까운 것과 비교하면, 이 단계는 코퍼스가 커질수록 상대적으로 불리해진다. 부록 E.4가 대규모 실험을 다루면서 색인 시간만 재고 검색 시간을 재지 않는 것은 이 지점에서 아쉬운 선택이다.

---

## 7. 실험 설계

데이터셋은 넷이다. 다중홉 QA 벤치마크 셋과 도메인 특화 하나로, HotpotQA(97k 문항, 문항당 최대 2개의 정답 근거 문단), 2WikiMultiHopQA(192k 문항, 2개 또는 4개 문서에서 근거 종합), MuSiQue(25k 문항, 2–4단계 순차 추론), 그리고 GraphRAG-Bench에서 가져온 Medical이다. Medical은 NCCN 임상 지침에서 구축되었고 사실 검색·복합 추론·맥락 요약·창의적 생성 네 과제에 걸쳐 총 4,076문항으로 구성된다. 다중홉 세 데이터셋은 HippoRAG의 방식을 따라 각 검증셋에서 1,000문항을 골라 평가하며, 같은 코퍼스를 검색 대상으로 공유한다. Medical에서 실제로 몇 문항을 썼는지는 명시되지 않는다.

베이스라인은 세 묶음이다. 검색 없는 제로샷 추론(LLaMA3 8B, LLaMA3 13B, GPT-3.5-turbo, GPT-4o-mini), vanilla RAG(상위 1·3·5 문단), 그리고 GraphRAG 계열 여덟 종(KGP, G-Retriever, RAPTOR, E2GraphRAG, LightRAG, HippoRAG, GFM-RAG, HippoRAG2)이다. 이 중 RAPTOR는 계층 트리를, G-Retriever·LightRAG·HippoRAG·GFM-RAG·HippoRAG2는 삼중항 그래프를 쓰며, E2GraphRAG는 둘을 결합한다.

지표는 네 개다. 종단 QA 성능은 생성된 답에 정답 문자열이 포함되는지 보는 Contain-Match Accuracy와 LLM이 정답 일치를 판정하는 GPT-Evaluation Accuracy로 잰다. Medical은 정답이 긴 서술문이라 GPT-Acc만 쓴다. 검색 품질은 GraphRAG-Bench의 두 지표, 질문과 검색 문단의 의미 정합을 보는 Context Relevance와 정답에 필요한 정보를 모두 담았는지 보는 Evidence Recall로 잰다.

구현 조건은 비교의 공정성 면에서 중요하다. 모든 알고리즘이 같은 임베딩 모델(all-mpnet-base-v2)을 쓰고, 모든 방법이 상위 $k = 5$로 검색하며, 생성과 평가 모두 GPT-4o-mini를 쓴다. 하드웨어는 RTX 4090 D(24GB) 한 장과 Xeon Gold 6426Y다. 단일 소비자급 GPU에서 전 실험을 돌렸다는 사실은 효율 주장의 맥락으로 읽을 만하다.

---

## 8. 결과 1: 생성 정확도

Table 1의 전체 결과는 다음과 같다(단위 %, 저자 보고).

| Method | HotpotQA Contain | HotpotQA GPT | 2Wiki Contain | 2Wiki GPT | MuSiQue Contain | MuSiQue GPT | Medical GPT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| llama-8B | 31.10 | 27.30 | 33.60 | 16.20 | 7.40 | 8.10 | 27.31 |
| llama-13B | 24.20 | 16.80 | 21.90 | 10.50 | 3.30 | 4.40 | 28.86 |
| GPT-3.5-turbo | 33.40 | 43.20 | 28.70 | 31.00 | 10.30 | 21.90 | 45.60 |
| GPT-4o-mini | 38.90 | 40.20 | 36.30 | 31.40 | 13.60 | 15.80 | 42.10 |
| Retrieval (Top-1) | 46.30 | 49.10 | 36.60 | 31.70 | 17.80 | 21.10 | 48.01 |
| Retrieval (Top-3) | 53.00 | 56.00 | 44.90 | 39.70 | 25.10 | 27.50 | 59.07 |
| Retrieval (Top-5) | 55.70 | 58.60 | 48.60 | 43.00 | 26.10 | 29.60 | 61.68 |
| KGP | 61.50 | 60.90 | 31.60 | 30.00 | 25.60 | 30.10 | 54.22 |
| G-retriever | 42.20 | 40.60 | 46.60 | 27.10 | 14.40 | 15.50 | 50.36 |
| RAPTOR | 55.90 | 58.30 | 50.10 | 42.10 | 23.30 | 27.40 | 55.75 |
| E2GraphRAG | 61.00 | 63.90 | 54.30 | 38.10 | 23.80 | 26.20 | 58.00 |
| LightRAG | 60.30 | 59.50 | 55.20 | 39.00 | 27.40 | 28.60 | 54.36 |
| HippoRAG | 57.00 | 59.30 | 66.10 | 59.90 | 29.30 | 24.10 | 55.04 |
| GFM-RAG | 62.70 | 65.60 | 66.80 | 59.60 | 29.90 | 34.60 | 56.07 |
| HippoRAG2 | 62.90 | 64.30 | 62.70 | 55.00 | 31.00 | 35.00 | 60.77 |
| **LinearRAG** | **64.30** | **66.50** | **70.20** | **63.70** | **33.90** | **37.00** | **63.72** |

LinearRAG가 일곱 개 열 전부에서 1위다. 다만 2위와의 격차는 열마다 크게 다르다. HotpotQA에서는 Contain +1.40%p(HippoRAG2 62.90 대비), GPT +0.90%p(GFM-RAG 65.60 대비)로 작다. 2Wiki에서는 Contain +3.40%p(GFM-RAG 66.80 대비), GPT +3.80%p(HippoRAG 59.90 대비)로 가장 크며, 논문이 요약에서 인용하는 수치도 이 열이다. MuSiQue는 Contain +2.90%p, GPT +2.00%p(둘 다 HippoRAG2 대비), Medical은 vanilla RAG(Top-5) 61.68 대비 +2.04%p, GraphRAG 계열 최고인 HippoRAG2 60.77 대비 +2.95%p다.

표에서 눈여겨볼 대목이 몇 가지 더 있다.

Medical 열은 논문의 예비 연구가 옳았음을 보여 준다. vanilla RAG(Top-5) 61.68이 여덟 개 GraphRAG 베이스라인 전부를 앞선다(최고 HippoRAG2 60.77). 그러나 나머지 세 다중홉 데이터셋에서는 정반대다. HotpotQA에서 vanilla Top-5는 55.70/58.60인데 GFM-RAG는 62.70/65.60이고, 2Wiki에서는 48.60/43.00 대 66.80/59.60으로 격차가 훨씬 크다. MuSiQue도 26.10/29.60 대 31.00/35.00으로 GraphRAG 쪽이 앞선다. 즉 "GraphRAG가 naive RAG보다 못하다"는 서두의 진단은 논문 자신의 주 표에서 도메인 특화 데이터셋 하나에서만 성립한다. 이 사실이 LinearRAG의 결과를 깎지는 않지만, 문제의식의 일반성 주장은 제한적으로 읽어야 한다.

베이스라인들의 순위가 데이터셋마다 흔들린다는 점도 기록해 둘 만하다. KGP는 HotpotQA에서 61.50/60.90으로 준수하지만 2Wiki에서 31.60/30.00으로 vanilla Top-1보다도 낮게 무너진다. HippoRAG는 2Wiki GPT에서 59.90으로 GraphRAG 중 최고인데 MuSiQue GPT에서는 24.10으로 vanilla Top-3보다 낮다. 본문 Obs. 2는 GraphRAG 방법들 중에서("Among them") HippoRAG2가 대부분의 데이터셋에서 최고라고 적는데, 그 내부 비교 범위에서라면 7열 중 4열(HotpotQA Contain, MuSiQue 두 열, Medical)에서 성립하는 서술이다. 다만 vanilla RAG까지 포함해 베이스라인 전체로 넓히면 Medical은 vanilla RAG가 최고여서 HippoRAG2의 1위는 세 열로 줄고, 2Wiki 두 열은 GFM-RAG와 HippoRAG가, HotpotQA GPT 열은 GFM-RAG가 각각 앞선다.

---

## 9. 결과 2: 시간과 토큰

효율 분석은 2WikiMultiHopQA에서 색인·검색 단계의 시간과 토큰 소비를 재는 방식이다(Table 2, 저자 보고). Accuracy 열은 해당 데이터셋의 Contain-Acc와 GPT-Acc의 평균이다.

| Method | 색인 시간(s) | 검색 시간(평균, s) | Prompt 토큰(×10⁶) | Completion 토큰(×10⁶) | Accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| G-retriever | 2745.94 | 11.487 | 6.05 | 2.26 | 36.85 |
| RAPTOR | 1323.57 | 0.062 | 0.81 | 0.03 | 46.10 |
| E2GraphRAG | 534.60 | 0.053 | 0.78 | 0.08 | 46.20 |
| LightRAG | 4933.22 | 10.963 | 35.52 | 51.16 | 47.10 |
| HippoRAG | 936.00 | 1.461 | 3.05 | 0.98 | 63.00 |
| GFM-RAG | 1202.77 | 1.211 | 3.05 | 0.98 | 63.20 |
| HippoRAG2 | 1147.01 | 1.694 | 4.98 | 1.22 | 58.85 |
| **LinearRAG** | **249.78** | 0.093 | **0** | **0** | **66.95** |

색인 시간에서 LinearRAG가 249.78초로 가장 빠르다. 감소율은 비교 대상에 따라 크게 다르다. 가장 빠른 베이스라인인 E2GraphRAG(534.60초) 대비 53.3%, HippoRAG(936.00초) 대비 73.3%, HippoRAG2 대비 78.2%, GFM-RAG 대비 79.2%, RAPTOR 대비 81.1%, G-Retriever 대비 90.9%, LightRAG 대비 94.9%다. 논문이 기여 목록에서 내세우는 "색인 시간 77% 이상 감소"는 이 표의 일곱 베이스라인 중 다섯에 대해 성립하고, E2GraphRAG와 HippoRAG에 대해서는 성립하지 않는다. 기준이 되는 대상이 명시되지 않은 채로 제시된 수치다.

토큰 소비는 0이다. 이것이 논문이 가장 강하게 미는 숫자이고, 설계상 자명한 결과이기도 하다. 색인과 검색 어느 단계에서도 LLM을 부르지 않으니 0이다. 단 최종 답 생성은 모든 방법이 GPT-4o-mini로 하므로, 이 0은 파이프라인 전체가 아니라 색인·검색 단계의 비용이다. 상위 $k = 5$로 조건이 같으니 생성 비용은 방법 간에 대체로 비슷하다고 볼 수 있다.

검색 시간에서는 LinearRAG가 1등이 아니다. E2GraphRAG 0.053초, RAPTOR 0.062초가 LinearRAG 0.093초보다 빠르다. 논문도 이를 인정하면서, 두 방법은 질의와 직접 관련된 문서만 뽑고 추론 사슬의 구조적 의존을 고려하지 않기 때문에 속도의 대가로 성능을 잃는다고 설명한다(Accuracy 46.20, 46.10 대 66.95). 반대편 끝에서 LinearRAG는 LightRAG(10.963초)나 G-Retriever(11.487초)보다 100배 이상 빠르다.

Obs. 5의 서술에는 표와 어긋나는 대목이 있다. "HippoRAG2가 프롬프트 구성에 3.05M, 완성에 0.98M 토큰만 쓰는 반면 HippoRAG2는 4.98M과 1.22M을 쓴다"고 적혀 있는데, 표에서 3.05M/0.98M은 HippoRAG(그리고 GFM-RAG)의 값이고 4.98M/1.22M이 HippoRAG2의 값이다. 앞의 것은 HippoRAG를 가리키려던 문장으로 보인다. 덧붙여 HippoRAG와 GFM-RAG의 토큰 수가 소수점까지 완전히 동일한 것은 두 방법이 같은 색인 절차를 공유하기 때문일 가능성이 높지만, 논문은 이를 설명하지 않는다.

대규모 실험은 부록 E.4에 있다. ATLAS-Wiki 코퍼스에서 5M·10M 토큰 부분집합을 만들어 색인 단계만 측정했다(Table 6, 저자 보고).

| 규모 | Method | 색인 시간(s) | Prompt 토큰(×10⁶) | Completion 토큰(×10⁶) |
| --- | --- | ---: | ---: | ---: |
| 5M | RAPTOR | 18033.75 | 7.43 | 0.96 |
| 5M | HippoRAG | 6032.46 | 13.94 | 3.68 |
| 5M | **LinearRAG** | **1409.95** | **0** | **0** |
| 10M | RAPTOR | 46430.96 | 16.62 | 2.82 |
| 10M | HippoRAG | 13815 | 28.04 | 7.53 |
| 10M | **LinearRAG** | **3084.38** | **0** | **0** |

논문이 인용하는 RAPTOR 대비 12.8배·15.1배 가속은 이 표에서 그대로 나온다(18033.75/1409.95 = 12.79, 46430.96/3084.38 = 15.05). HippoRAG 대비로는 4.28배와 4.48배다. 코퍼스가 두 배가 될 때 각 방법의 색인 시간이 몇 배가 되는지도 읽어 볼 수 있다. LinearRAG 2.19배, HippoRAG 2.29배, RAPTOR 2.58배다. 측정점이 둘뿐이라 확장 곡선을 판정할 수는 없지만, 셋 중 LinearRAG가 배율 2에 가장 가깝다는 관찰은 논문의 선형성 주장과 방향이 맞는다. 다만 이 표에는 검색 시간도 정확도도 없다. 대규모에서 검증된 것은 색인 비용뿐이다.

---

## 10. 검색 품질, 절제 연구, 민감도

**검색 품질(Medical, Table 4).** GraphRAG-Bench의 네 과제별로 recall과 relevance를 나눠 잰 결과다(저자 보고).

| Method | 사실검색 R | 사실검색 Rel | 복합추론 R | 복합추론 Rel | 맥락 R | 맥락 Rel | 창의생성 R | 창의생성 Rel |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Vanilla RAG (Top-5) | 86.24 | 63.71 | 84.97 | **84.11** | 84.14 | **89.94** | 44.88 | 58.73 |
| RAPTOR | 85.40 | 69.38 | **89.70** | 53.20 | 88.86 | 58.73 | 72.70 | 52.71 |
| E2GraphRAG | 87.84 | 69.74 | 87.08 | 62.67 | **89.17** | 71.63 | 60.26 | 35.84 |
| LightRAG | 80.32 | 41.27 | 82.91 | 42.79 | 85.71 | 43.11 | 81.34 | 45.17 |
| HippoRAG | 87.25 | 52.44 | 83.80 | 42.19 | 83.46 | 49.13 | 81.66 | 45.03 |
| GFM-RAG | **90.08** | 57.90 | 85.03 | 33.06 | 78.62 | 40.14 | 83.51 | 22.87 |
| LinearRAG | 88.86 | **86.09** | 87.03 | 81.58 | 89.13 | 87.89 | **89.08** | **72.74** |

이 표에서 LinearRAG의 실제 강점은 relevance 쪽이다. 사실검색 86.09와 창의생성 72.74는 전 방법 중 최고이고, 나머지 두 과제에서도 vanilla RAG 바로 다음이다. GraphRAG 계열이 relevance에서 크게 무너지는 것과 대조된다. GFM-RAG는 창의생성 recall을 44.88에서 83.51로 끌어올리는 대신 relevance가 58.73에서 22.87로 떨어진다. 논문이 강조하는 "회수와 정합의 동시 달성"은 이 대비에서 설득력을 갖는다.

다만 본문 Obs. 9의 요약은 표보다 강하다. "네 과제 모두에서 recall 최고"라고 적혀 있으나, recall 1위는 창의생성 하나뿐이다. 사실검색은 GFM-RAG 90.08이, 복합추론은 RAPTOR 89.70이, 맥락은 E2GraphRAG 89.17이 각각 앞선다(LinearRAG는 각각 88.86, 87.03, 89.13). "대부분의 경우 RAG보다 나은 relevance"라는 서술도 절반, 즉 네 과제 중 둘에 해당한다. 복합추론(81.58 대 84.11)과 맥락(87.89 대 89.94)에서는 vanilla RAG가 앞선다. 표 자체가 보여 주는 그림, 곧 "GraphRAG 계열 대비 relevance에서 큰 우위, vanilla RAG 대비로는 recall에서 우위이고 relevance는 비등"이 실제 결과에 더 가깝다. 또한 이 표에는 같은 Medical 데이터셋에서 GraphRAG 계열 최고 정확도(60.77)를 냈던 HippoRAG2가 빠져 있다.

**절제 연구.** 두 검색 모듈을 각각 제거한 변형을 네 데이터셋에서 비교한다. w/o Entity Activation은 의미 브리징을 건너뛰고 질의에서 추출한 초기 엔티티를 그대로 활성 엔티티로 쓰며, w/o Global Importance Aggregation은 PPR을 생략하고 1단계 활성화 점수만으로 문단을 뽑는다.

![절제 연구](/api/blog/figures/linearrag-fig4-ablation.png)
*그림 4. 네 데이터셋에서의 절제 연구. y축은 GPT-Acc와 Contain-Acc의 평균이다. 원 논문 Figure 4에서 crop. 출처: Zhuang et al. (2025), arXiv:2510.10114.*

수치는 HotpotQA 65.40 → 63.15(엔티티 활성화 제거) / 63.35(전역 집계 제거), 2Wiki 66.95 → 64.40 / 64.20, MuSiQue 35.45 → 31.65 / 32.05, Medical 63.72 → 61.69 / 61.73이다. 두 모듈의 기여가 거의 대칭이고, 하락폭은 1.99–3.80%p 범위다. MuSiQue에서 가장 크게 떨어지는데(−3.80 / −3.40), 2–4단계 추론을 요구하는 데이터셋에서 브리징과 전역 집계가 더 필요하다는 해석과 맞는다.

이 그림을 8절의 표와 겹쳐 놓으면 더 읽을 것이 있다. Medical에서 두 변형의 점수 61.69와 61.73은 vanilla RAG(Top-5)의 61.68과 사실상 같다. 즉 Medical에서 LinearRAG가 vanilla RAG를 앞서는 폭 전체가 두 모듈이 함께 있을 때만 나온다. 반대로 2Wiki에서는 변형들(64.40, 64.20)이 여전히 GFM-RAG(63.20)와 HippoRAG(63.00)를 앞선다. 데이터셋에 따라 이득의 출처가 다르다는 뜻이다. 두 모듈을 동시에 제거한 조건, 즉 단순 밀집 검색으로 완전히 환원한 하한은 측정되지 않았다.

**하이퍼파라미터.** 2Wiki에서 두 값의 민감도를 본다. 가지치기 임계 $\delta$는 너무 작으면 소음이 늘고 검색 효율이 떨어지며, 너무 크면 관련 엔티티를 놓쳐 맥락이 좁아진다는 통상적인 형태를 보인다(그림의 y축 범위 64–67%). 균형 계수 $\lambda$는 0.05 부근에서 최적이었고(y축 62–68%), 저자들은 엔티티 정보가 주 신호라는 뜻으로 읽는다. 두 분석 모두 2Wiki 한 데이터셋에서만 수행되었다.

**임베딩 백본.** all-mpnet-base-v2 외에 all-MiniLM-L6-v2, bge-large-en-v1.5, e5-large-v2를 갈아 끼운 비교가 부록 E.3에 있다(저자 보고).

| Model | HotpotQA Contain | HotpotQA GPT | 2Wiki Contain | 2Wiki GPT | MuSiQue Contain | MuSiQue GPT | Medical GPT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all-mpnet-base-v2 | 64.30 | 66.50 | **70.20** | 63.70 | **33.90** | **37.00** | 63.72 |
| all-MiniLM-L6-v2 | 64.20 | 64.90 | 69.50 | 62.60 | 32.80 | 36.90 | 62.32 |
| bge-large-en-v1.5 | 66.20 | 67.60 | 69.80 | **63.90** | 31.80 | 35.20 | 64.45 |
| e5-large-v2 | **66.80** | **68.30** | 69.90 | 63.10 | 31.70 | 36.50 | **65.42** |

방법이 임베딩 선택에 크게 흔들리지 않는다는 논문의 결론은 타당하다. 네 모델의 편차가 대체로 1–3%p 안에 있다. 다만 "all-mpnet-base-v2가 대부분의 데이터셋에서 우월하다"는 서술은 표와 잘 맞지 않는다. 일곱 열 가운데 mpnet이 1위인 것은 세 열(2Wiki Contain, MuSiQue 두 열)이고, e5-large-v2도 세 열(HotpotQA 두 열, Medical), bge-large가 한 열(2Wiki GPT)에서 1위다. HotpotQA에서는 e5를 썼다면 66.80/68.30으로 보고된 수치보다 높았을 것이다. 논문은 계산 효율을 근거로 mpnet을 기본값으로 택했다고 밝히며, 모든 베이스라인이 같은 임베딩을 쓰도록 통제한 것을 감안하면 이 선택 자체는 비교의 공정성에 부합한다.

**사례 연구.** 부록 E.5는 2Wiki의 다중홉 질문 하나를 놓고 HippoRAG2와 비교한다. "Beatrice I, Countess of Burgundy의 남편은 어느 나라 사람인가"라는 질문에서, LinearRAG는 Beatrice I → (Frederick Barbarossa와의 혼인을 언급한 문장) → Frederick Barbarossa → (독일 왕 선출을 언급한 문장) → Germany로 활성화가 이어져 정답 Germany를 맞히고, HippoRAG2는 French로 틀린다. 논문의 해석은 HippoRAG2가 사전 추출된 관계(husband)에 의존하는데 그 관계가 그래프에 없어 실패했다는 것이다. 표를 자세히 보면 두 방법 모두 1순위로 같은 문단을 검색했고, 승패를 가른 것은 LinearRAG가 2순위로 Beatrice I 문단을 추가로 가져온 반면 HippoRAG2의 2–5순위는 모두 무관한 문단이었다는 점이다. 사례 하나의 예시적 가치는 인정하되, 이것이 관계 없는 색인의 일반적 우위를 보이는 증거는 아니다.

---

## 11. 한계와 해석 범위

**정확도 이득의 크기와 불확실성.** 이 논문에는 분산도, 신뢰구간도, 유의성 검정도 없다. 다중홉 데이터셋의 표본은 각 1,000문항이다. 정확도가 0.65 근처일 때 1,000문항 표본의 단순 표준오차는 약 1.5%p다. 같은 문항 집합에 대한 짝지어진 비교라 두 방법 차이의 표준오차는 이보다 작지만, 논문이 아무 분산 정보도 제공하지 않으므로 독자가 이를 확인할 방법이 없다. HotpotQA의 이득(+0.90%p, +1.40%p)이 특히 이 지점에서 취약하다. 반대로 2Wiki의 +3.40/+3.80%p와 MuSiQue의 +2.00/+2.90%p는 상대적으로 견고해 보인다. 시드나 반복 실행에 대한 언급도 없어 단일 실행 결과로 읽어야 한다.

**비용 절감의 준거.** 효율 주장은 정확도 주장보다 크고 튼튼하다. 토큰 0은 설계상 보장되고, 색인 시간 절감은 두 규모(2Wiki, ATLAS-Wiki 5M·10M)에서 반복 확인된다. 다만 몇 가지 단서가 붙는다. 기여 목록의 "77% 이상 감소"는 준거를 명시하지 않으며 일곱 중 두 베이스라인에는 해당하지 않는다. 대규모 비교는 RAPTOR와 HippoRAG 둘만 대상으로 하고, 2Wiki에서 가장 빨랐던 E2GraphRAG는 포함되지 않는다. 그리고 색인 시간의 절대적 비교는 각 베이스라인이 어떤 LLM을 어떤 병렬도로 호출했는지에 크게 좌우되는데, 그 조건이 보고되지 않았다. LLM 호출이 API 지연에 묶여 있다면 시간 비교의 상당 부분은 알고리즘이 아니라 네트워크를 재는 것일 수 있다. 토큰 수 비교는 이 교란에서 자유로우므로 더 신뢰할 만한 축이다.

**정확도와 비용을 나눠 읽기.** 이 논문의 두 주장은 성격이 다르다. 비용 쪽은 배수 단위(4–15배, 토큰 0)이고 설계에서 연역되며 두 규모에서 재현된다. 정확도 쪽은 퍼센트포인트 단위(0.90–3.80%p)이고 통계적 뒷받침이 없다. 논문이 실제로 강하게 입증한 명제는 "관계 추출을 빼면 훨씬 싸다"이고, "그러면서 더 정확하다"는 명제는 같은 강도로 입증되지 않았다. 더 방어 가능한 형태는 "관계 추출을 제거해도 정확도를 잃지 않으며, 데이터셋에 따라 소폭 앞선다"일 것이다. 실용적 함의는 그래도 충분히 크다. 색인 비용이 결정적인 대규모 배치에서 정확도를 희생하지 않고 LLM 호출을 없앨 수 있다는 뜻이기 때문이다.

**명세되지 않은 요소들.** 5절에서 짚은 대로 식 7의 $L_{e_i}$는 정의가 없고 $W_p$는 값이 없다. 가지치기 임계 $\delta$는 본문 값(4)과 그림 축 범위(0.2–0.8)가 어긋난다. 의미 전파의 반복 횟수는 "일반적으로 4 이하"로만 서술되고 데이터셋별 실제 값이 보고되지 않는다. 식 6은 표준 PageRank 갱신식으로 적혀 있어 개인화가 어디서 들어가는지 식만으로는 확정되지 않는다. 구축된 그래프의 규모(엔티티·문장 노드 수, 간선 수, 희소도)도 보고되지 않아, 부록 D의 희소성 가정(문장당 4개, 문단당 10개)이 실제 데이터에서 얼마나 지켜지는지 확인할 수 없다. 재현성 선언문은 메모리 사용량을 포함해 자원 정보를 제공한다고 적지만, 부록 C에는 GPU·CPU 사양만 있고 메모리 측정치는 없다. 코드와 데이터가 공개되어 있어 이 공백들은 저장소에서 메울 수 있겠으나, 논문 본문만으로는 식 7을 그대로 구현할 수 없다.

**엔티티 정렬 문제.** 논문의 첫 번째 중심 주장은 "정렬된(aligned) 엔티티가 문단들을 잇는 일차 앵커"라는 것이다. 그런데 §3.1의 구성 절차에는 정렬 단계가 없다. spaCy로 개체명을 뽑고 포함 관계로 간선을 잇는 것이 전부이므로, 표면형이 같으면 같은 노드가 되고 다르면 다른 노드가 된다. "US"와 "United States", 대명사로 이어지는 상호참조는 서로 다른 노드로 남는다. 질의 쪽에서는 식 3이 유사도 최댓값으로 매칭하니 어느 정도 완충이 되지만, 코퍼스 쪽 엔티티 병합은 다루어지지 않는다. 관련연구에서 엔티티 정렬 문헌을 인용하면서도 파이프라인에 반영하지 않은 셈이고, 주장 (i)의 "aligned"는 실제로 구현된 것보다 강한 단어다. 반대로 보면, 정렬 없이도 성능이 나온다는 것은 문장 매개 전파가 표면형 불일치를 어느 정도 우회한다는 방증일 수 있는데, 이를 확인하는 실험은 없다.

**평가 범위.** 데이터셋은 다중홉 QA 셋과 의료 하나다. 셋 다 위키백과 기반이고 spaCy NER이 잘 작동하는 영역이다. 개체명이 희박하거나 도메인 특수적인 코퍼스(법률 조문, 코드, 대화 로그)에서 엔티티만으로 색인을 세우는 전략이 어떻게 되는지는 열려 있다. 실제로 관계 추출을 지우는 설계는 "정보를 잇는 다리가 개체명"이라는 가정 위에 서 있는데, 이 가정이 약한 도메인에서는 Tri-Graph의 간선 자체가 성기게 된다. Medical 데이터셋이 도메인 특화 사례이긴 하나 NCCN 지침이라는 개체명이 풍부한 텍스트다.

평가 프로토콜에도 한계가 있다. GPT-Acc의 판정자와 생성자가 모두 GPT-4o-mini이고, 판정의 신뢰도를 사람 주석과 대조한 연구는 없다. Contain-Match는 문자열 포함 여부라 관대하거나(우연 포함) 가혹하다(표현 차이). 두 지표가 대체로 같은 방향을 가리키는 것은 다행이지만, 2Wiki에서 두 지표의 격차가 6.5%p(70.20 대 63.70)로 벌어지는 등 절대값의 해석에는 주의가 필요하다.

**빠진 비교군.** 부록 F의 관련연구는 GraphRAG를 세 계열로 나눈다. 클러스터링 기반 계층, 관계 추출 기반 지식 그래프, 그리고 추론 강화 RAG다. 실험은 앞의 두 계열만 다루고 세 번째 계열(LogicRAG, LAG, Chain-of-Note, Self-RAG)과는 한 번도 비교하지 않는다. 이 계열은 그래프를 만들지 않고 질의를 분해해 다중홉을 처리하므로 색인 비용이 애초에 0에 가깝고, "색인을 싸게 하면서 다중홉을 푼다"는 LinearRAG의 목표와 정면으로 겹친다. 논문이 스스로 지목한 세 번째 길과의 대조가 없다는 점은 기여의 위치를 재는 데 실질적인 공백이다. 재랭커를 붙인 강한 밀집 검색 베이스라인이 없다는 점도 같은 맥락이다. 식 7의 $\lambda$ 항이 사실상 밀집 검색 점수인 만큼, 밀집 검색을 어디까지 밀어붙일 수 있는지가 자연스러운 대조군인데 vanilla RAG Top-$k$만 놓여 있다.

**설계의 성격.** LinearRAG의 부품은 대체로 기성품이다. spaCy NER, 문장 임베딩 유사도, 희소 행렬 전파, personalized PageRank 모두 새롭지 않고, PPR로 문단을 뽑는 얼개는 HippoRAG와 같다. 새로운 것은 씨앗을 만드는 방식이다. HippoRAG가 삼중항 그래프 위에서 씨앗을 정하는 자리에 LinearRAG는 문장을 경유하는 질의 가중 전파를 놓았다. 논문의 실질적 명제는 "이 자리에 관계 그래프는 필요 없고 문장 공기로 충분하다"는 것이며, Table 1과 Table 4가 그 명제의 실증이다. 뒤집어 말하면 이 논문은 새로운 알고리즘보다 제거의 논증에 가깝다. 무엇을 빼도 되는지를 보이는 작업은 그 자체로 가치가 있지만, 제거의 논증이 성립하려면 제거된 것이 정말 기여하지 않았음을 보여야 한다. 관계 추출을 켠 조건과 끈 조건을 다른 요소를 고정한 채 비교한 실험은 이 논문에 없다. 대신 서로 다른 시스템 전체를 비교하고 있으므로, 관계 추출의 무용함은 직접 측정된 것이 아니라 시스템 간 성능 차로부터 추론된 것이다.

---

## 12. 결론

LinearRAG의 제안은 간명하다. GraphRAG의 색인에서 관계 추출을 빼고 엔티티만 남기면, 그래프는 두 개의 희소 이분 행렬로 납작해지고 LLM 토큰이 필요 없어지며 구축과 검색이 코퍼스 크기에 선형이 된다. 잃어버린 관계 정보는 두 곳에서 보충된다. 검색 단계에서는 질의-문장 유사도로 가중된 전파가 중간 엔티티를 찾아 홉을 잇고, 생성 단계에서는 원 문단이 그대로 전달되어 LLM이 관계를 문맥에서 읽는다.

읽을 때의 균형은 이렇다. "선형"은 경쟁자가 초선형이라는 뜻이 아니라 LinearRAG 자신의 확장 성질이고, 실제 차별점은 점근 차수가 아니라 문단당 LLM 호출을 spaCy 호출로 바꾼 상수 절감이다. 그 절감은 크고 반복 측정되었다. 2Wiki 색인 249.78초와 토큰 0, ATLAS-Wiki 10M에서 RAPTOR 대비 15.1배가 저자 보고 수치다. 정확도 이득은 일곱 열 모두에서 1위이되 폭은 0.90–3.80%p이며 분산 정보가 없다. 검색 품질 표에서 강점은 recall보다 relevance 쪽이고, 절제 결과는 두 검색 모듈이 각각 2–4%p씩 대칭적으로 기여함을 보인다. 문제의식의 출발점이었던 "GraphRAG < naive RAG"는 논문 자신의 주 표에서 Medical 한 데이터셋에만 해당한다.

| 항목 | 정리 |
| --- | --- |
| 기여 | 관계 추출 없이 엔티티-문장·엔티티-문단 이분 행렬만으로 색인하는 Tri-Graph, 그 위에서 문장을 경유해 중간 엔티티를 찾는 의미 브리징 전파, 활성 엔티티를 씨앗으로 한 PPR 문단 검색. 색인 단계 LLM 토큰 소비 0. |
| 근거가 강한 주장 | 색인 비용 절감(시간 4–15배, 토큰 0). 설계에서 연역되고 두 규모에서 측정됨. GraphRAG 계열 대비 context relevance 우위(Table 4). |
| 근거가 제한적인 주장 | 정확도 우위(0.90–3.80%p, 분산·유의성 미보고, 단일 실행). "네 과제 recall 최고"(실제 1/4), "색인 시간 77% 이상 감소"(준거 미명시, 효율 표의 7개 베이스라인 중 5개에 해당), 예비 연구의 일반성(Medical 한정). |
| 해석 범위 | 이 논문은 새 알고리즘의 제안이라기보다 관계 추출이라는 부품을 빼도 되는지에 대한 시스템 수준 논증이다. 색인 비용이 지배적인 대규모 배치를 염두에 두고 읽으면 값이 분명해지고, 관계 추출 자체의 기여를 통제 비교로 측정한 실험은 없다는 점을 함께 두면 주장의 사정거리가 잡힌다. |

## References

Bai, J., Fan, W., Hu, Q., Zong, Q., Li, C., Tsang, H. T., Luo, H., Yim, Y., Huang, H., Zhou, X., et al. (2025). *AutoSchemaKG: Autonomous knowledge graph construction through dynamic schema induction from web-scale corpora*. arXiv. https://arxiv.org/abs/2505.23628

Edge, D., Trinh, H., Cheng, N., Bradley, J., Chao, A., Mody, A., Truitt, S., & Larson, J. (2024). *From local to global: A graph RAG approach to query-focused summarization*. arXiv. https://arxiv.org/abs/2404.16130

Guo, Z., Xia, L., Yu, Y., Ao, T., & Huang, C. (2024). *LightRAG: Simple and fast retrieval-augmented generation*. arXiv. https://arxiv.org/abs/2410.05779

Gutiérrez, B. J., Shu, Y., Gu, Y., Yasunaga, M., & Su, Y. (2024). HippoRAG: Neurobiologically inspired long-term memory for large language models. *Advances in Neural Information Processing Systems*, *37*. https://arxiv.org/abs/2405.14831

Gutiérrez, B. J., Shu, Y., Qi, W., Zhou, S., & Su, Y. (2025). *From RAG to memory: Non-parametric continual learning for large language models*. arXiv. https://arxiv.org/abs/2502.14802

Han, H., Shomer, H., Wang, Y., Lei, Y., Guo, K., Hua, Z., Long, B., Liu, H., & Tang, J. (2025). *RAG vs. GraphRAG: A systematic evaluation and key insights*. arXiv. https://arxiv.org/abs/2502.11371

He, X., Tian, Y., Sun, Y., Chawla, N. V., Laurent, T., LeCun, Y., Bresson, X., & Hooi, B. (2024). *G-Retriever: Retrieval-augmented generation for textual graph understanding and question answering*. arXiv. https://arxiv.org/abs/2402.07630

Ho, X., Nguyen, A.-K. D., Sugawara, S., & Aizawa, A. (2020). *Constructing a multi-hop QA dataset for comprehensive evaluation of reasoning steps*. arXiv. https://arxiv.org/abs/2011.01060

Luo, L., Zhao, Z., Haffari, G., Phung, D., Gong, C., & Pan, S. (2025). *GFM-RAG: Graph foundation model for retrieval augmented generation*. arXiv. https://arxiv.org/abs/2502.01113

Sarthi, P., Abdullah, S., Tuli, A., Khanna, S., Goldie, A., & Manning, C. D. (2024). RAPTOR: Recursive abstractive processing for tree-organized retrieval. *International Conference on Learning Representations (ICLR)*. https://arxiv.org/abs/2401.18059

Song, K., Tan, X., Qin, T., Lu, J., & Liu, T.-Y. (2020). MPNet: Masked and permuted pre-training for language understanding. *Advances in Neural Information Processing Systems*, *33*, 16857–16867. https://arxiv.org/abs/2004.09297

Trivedi, H., Balasubramanian, N., Khot, T., & Sabharwal, A. (2022). MuSiQue: Multihop questions via single-hop question composition. *Transactions of the Association for Computational Linguistics*, *10*, 539–554. https://doi.org/10.1162/tacl_a_00475

Wang, Y., Lipka, N., Rossi, R. A., Siu, A., Zhang, R., & Derr, T. (2024). Knowledge graph prompting for multi-document question answering. *Proceedings of the AAAI Conference on Artificial Intelligence*. https://arxiv.org/abs/2308.11730

Xiang, Z., Wu, C., Zhang, Q., Chen, S., Hong, Z., Huang, X., & Su, J. (2025). *When to use graphs in RAG: A comprehensive analysis for graph retrieval-augmented generation*. arXiv. https://arxiv.org/abs/2506.05690

Yang, Z., Qi, P., Zhang, S., Bengio, Y., Cohen, W. W., Salakhutdinov, R., & Manning, C. D. (2018). HotpotQA: A dataset for diverse, explainable multi-hop question answering. *Proceedings of the 2018 Conference on Empirical Methods in Natural Language Processing*, 2369–2380. https://doi.org/10.18653/v1/D18-1259

Zhao, Y., Zhu, J., Guo, Y., He, K., & Li, X. (2025). *E²GraphRAG: Streamlining graph-based RAG for high efficiency and effectiveness*. arXiv. https://arxiv.org/abs/2505.24226

Zhuang, L., Chen, S., Xiao, Y., Zhou, H., Zhang, Y., Chen, H., Zhang, Q., & Huang, X. (2025). *LinearRAG: Linear graph retrieval augmented generation on large-scale corpora*. arXiv. https://arxiv.org/abs/2510.10114
