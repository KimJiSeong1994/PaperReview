---
title: "RAG vs. GraphRAG: A Systematic Evaluation and Key Insights"
slug: rag-vs-graphrag-systematic-evaluation
excerpt: "RAG와 여러 GraphRAG를 질의응답·요약에서 비교한 연구다. 우열은 질문 유형과 근거 표현에 따라 달라지며, 입력 토큰량을 맞추면 일부 차이가 줄어 구조와 맥락 길이의 효과를 함께 봐야 한다."
category: Agents / RAG
tags:
  - rag
  - graphrag
  - retrieval-evaluation
  - query-based-summarization
  - llm-as-a-judge
  - hybrid-retrieval
status: "published"
published_at: "2026-09-11T12:23:45.767870+00:00"
blog_url: "https://jiphyeonjeon.kr/blog/rag-vs-graphrag-systematic-evaluation"
reviewed_at: "2026-09-15"
date: "2026-09-11"
publication_doi: "10.1145/3770855.3817575"
publication_url: "https://dl.acm.org/doi/10.1145/3770855.3817575"
venue: "KDD 2026 (출판 메타데이터 확인)"
source_paper: "https://arxiv.org/pdf/2502.11371v3"
paper_version: "저자 공개 arXiv:2502.11371v3, 2026-03-04; ACM 최종 PDF 직접 대조 불가"
official_code: "https://github.com/haoyuhan1/RAGvsGraphRAG"
code_snapshot: "d2a0c0c0deb0903d60338d3c416ccd6f9544267c"
thumbnail: "figures/rvg-fig2-complementary-errors.png"
updated_at: "2026-09-15T14:10:12.721107+00:00"
---

# RAG vs. GraphRAG: A Systematic Evaluation and Key Insights

**Paper:** Haoyu Han; Li Ma; Yu Wang; Harry Shomer; Yongjia Lei; Zhisheng Qi; Kai Guo; Zhigang Hua; Bo Long; Hui Liu; Charu C. Aggarwal; Jiliang Tang (2026). "RAG vs. GraphRAG: A Systematic Evaluation and Key Insights". https://arxiv.org/abs/2502.11371v3 · arXiv:2502.11371v3. 2026년 3월 4일 공개된 20쪽의 v3를 분석한다. [공식 코드](https://github.com/haoyuhan1/RAGvsGraphRAG).

**검토 기준:** KDD 2026 V.2 출판 정보(pp. 8966–8977)는 [ACM DOI](https://doi.org/10.1145/3770855.3817575) 메타데이터와 [저자의 논문 목록](https://cse.msu.edu/~hanhaoy1/publications/)으로 확인했다. 기술 분석·수치·도판은 저자가 연결한 **arXiv v3**를 기준으로 한다. ACM 최종 PDF는 직접 대조하지 못했으며, 공개 v3에는 미완성 ACM 서식 문구가 남아 있다. 따라서 두 판의 내용이 같다고 전제하지 않는다. 아래 표·그림 번호는 모두 공개 v3의 번호다.

**Abstract:** 일반적인 RAG는 원문 chunk를 검색하고, GraphRAG는 텍스트에서 얻은 구조를 이용해 근거를 검색하거나 요약한다. 그래프가 관계를 보존하면 복합 질문에 유리할 수 있지만, 구조를 만드는 과정에서 세부 정보가 사라지고 비용과 평가 조건도 달라진다. 이 논문은 단일 새 알고리즘을 제안하기보다, QA와 query-based summarization에서 RAG와 여러 GraphRAG 계열을 비교한다. 공개 v3의 Llama-3.1-8B 결과에서 NQ는 RAG의 F1 64.78이 높고, HotpotQA는 HippoRAG2의 63.01이 RAG 60.04보다 높다. 그러나 Community Local과 입력 토큰량을 맞춘 RAG는 MultiHop-RAG에서 69.33으로 Local 69.01과 비슷하거나 약간 높다. 요약에서는 참조문 기반 지표와 LLM 선호가 다른 속성을 측정하고, 답변 제시 순서에도 선호가 바뀐다. 이 글은 이러한 결과를 ‘그래프의 존재’ 하나의 효과로 묶지 않고, 근거의 단위·정보 보존·토큰량·판정 방식·비용으로 나누어 분석한다. [공개 v3 §§3–5, Tables 1·32](https://arxiv.org/pdf/2502.11371v3#page=20)

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 일반 텍스트에서 그래프를 만들면 어떤 질문과 요약에 도움이 되며, 어떤 비용과 정보 손실을 동반하는가? |
| 논문의 기여 | 공통 전처리·검색·생성 설정으로 여러 RAG 계열을 비교하고, 혼합 전략과 평가 편향을 분석한다. |
| 비교한 GraphRAG 계열 | KG triplets, community Local/Global, HippoRAG2, RAPTOR처럼 서로 다른 근거 표현을 포함한다. |
| QA의 큰 경향 | 세부 사실에서는 RAG가, 일부 관계 결합·시간 비교에서는 구조를 활용한 방법이 강한 경향을 보인다. 모델과 query type에 따라 예외가 있다. |
| 중요한 통제 | Top-10 chunk와 top-10 entity는 같은 토큰 예산이 아니다. Token-matched RAG가 전체 점수 차이를 크게 줄인다. |
| 요약 평가 | 참조문 일치, comprehensiveness, diversity는 같은 목표가 아니다. LLM judge의 순서 편향도 확인한다. |
| 혼합 전략 | Selection은 한 경로를 고르고, Integration은 양쪽 근거를 합친다. Integration도 항상 좋아지지는 않는다. |
| 검토 한계 | 기술 분석은 저자 공개 v3 기준이다. 최종 ACM 판과 코드 snapshot의 완전한 일치, 실제 실험 재실행은 확인하지 않았다. |

## 목차

1. GraphRAG를 하나의 방법으로 비교할 수 있는가
2. 네 가지 구조화 검색과 공통 평가 흐름
3. QA 결과: 평균보다 질문 유형을 본다
4. 그래프의 정보 보존과 검색 개선의 한계
5. 상보성에서 Selection·Integration으로
6. 요약: 정답과 닮은 글, 다양한 글, 선호되는 글
7. 같은 top-k와 같은 비용은 다르다
8. 원문·코드·사례에서 확인할 평가의 경계
9. 적용 기준과 결론

---

## 1. GraphRAG를 하나의 방법으로 비교할 수 있는가

RAG에 그래프를 넣었다는 설명만으로는 시스템을 충분히 알 수 없다. 어떤 방법은 원문을 triple로 바꾸고 triple 자체를 LLM에 보여준다. 다른 방법은 그래프를 검색의 보조 수단으로 쓰면서 원문 chunk를 전달한다. 또 다른 방법은 community summary나 계층적 요약을 전달한다.

따라서 “RAG 대 GraphRAG”는 그래프 유무만 바꾼 하나의 깔끔한 실험이 아니다. 문서의 어떤 정보를 남기는지, 어떤 단위로 검색하는지, 생성 모델이 무엇을 읽는지가 함께 바뀐다. 논문은 이 차이를 네 계열로 나눠 비교한다. [공개 v3 §3.2](https://arxiv.org/pdf/2502.11371v3#page=3)

이 구분은 앞선 [Procedural Graphs 리뷰](https://jiphyeonjeon.kr/blog/procedural-graphs)와도 다르다. 여기서 그래프는 주로 **답변의 사실 근거를 조직하는 구조**다. 에이전트가 다음에 무엇을 해야 하는지 안내하는 실행 절차 그래프를 비교하는 논문은 아니다.

이 연구의 가장 유용한 독해 방식은 특정 이름의 승자를 찾는 것보다, **어떤 근거 표현이 어떤 질문에 맞는지**를 살피는 것이다. 특히 논문 후반에서 단순히 GraphRAG라고 부르는 대상은 대체로 Community-GraphRAG Local이므로, 그 결과를 다른 모든 GraphRAG로 확장하지 않도록 주의해야 한다.

## 2. 네 가지 구조화 검색과 공통 평가 흐름

### 2.1 같은 텍스트에서 서로 다른 근거를 만든다

| 계열 | 논문에서 비교한 방법 | 최종 근거의 주된 형태 | 얻는 것과 잃을 수 있는 것 |
| --- | --- | --- | --- |
| Vector RAG | RAG | 원문 chunk | 문장과 세부 맥락을 보존하지만 흩어진 근거의 연결은 검색·생성 과정이 담당한다. |
| KG 기반 | KG-GraphRAG Triplets | 개체–관계–개체 triple | 관계가 명시적이지만 추출에서 빠진 정보가 전달되지 않을 수 있다. |
| KG 기반 + 원문 | KG-GraphRAG Triplets+Text | Triple과 대응 source text | 구조의 연결과 원문의 세부 정보를 함께 제공한다. |
| Community 기반 | Community Local | 개체 주변 관계와 낮은 수준의 community 정보 | Query와 관련된 상세 관계 및 요약을 결합한다. |
| Community 기반 | Community Global | 높은 수준의 community summary | 넓은 범위의 내용을 묶지만 구체적 질문의 세부가 희석될 수 있다. |
| Text 중심 graph-guided | HippoRAG2 | 그래프로 검색을 돕는 원문 chunk | 그래프를 보조 구조로 활용하면서 원문 근거를 유지한다. |
| 계층적 summary | RAPTOR, 표기상 RaptorRAG | 여러 수준의 요약과 text unit | 명시적인 entity KG 없이도 계층 구조를 사용한다. |

[공개 v3 §§3.1–3.2](https://arxiv.org/pdf/2502.11371v3#page=3)

이 taxonomy는 GraphRAG를 넓게 잡은 논문의 분류다. RAPTOR를 entity–relation KG와 동일한 구조로 설명할 수 없고, HippoRAG2의 graph-guided text retrieval을 triple만 전달하는 방식과도 구분해야 한다.

원 연구에서도 RAPTOR는 embedding·clustering·summarization을 반복한 tree를 사용하고, HippoRAG2는 passage 통합과 Personalized PageRank를 활용한다. 이들을 모두 하나의 ‘그래프 탐색 알고리즘’으로 묶으면 작동 원리의 차이가 사라진다. 이 글의 수치 비교는 각 원 연구의 별도 실험을 합친 것이 아니라 Han et al.의 공통 benchmark 결과를 따른다. [RAPTOR](https://arxiv.org/abs/2401.18059), [HippoRAG2](https://proceedings.mlr.press/v267/gutierrez25a.html)

### 2.2 검색을 저장한 뒤 같은 generator로 비교한다

논문은 각 방법의 retrieved evidence를 먼저 저장하고, 공통 generation script로 답변을 생성하는 평가 흐름을 사용한다. 검색과 생성의 구현 차이가 불필요하게 섞이지 않도록 하려는 설계다.

| 단계 | 공통으로 유지하는 부분 | 방법마다 달라지는 부분 |
| --- | --- | --- |
| 원문 준비 | 같은 과제의 corpus와 chunking | Chunk를 바탕으로 만드는 index·그래프·요약 구조 |
| 근거 검색 | 같은 질문을 입력 | 원문 검색 또는 구조를 활용한 검색, 근거의 단위와 길이 |
| 근거 저장 | 검색 결과를 저장해 생성 단계와 분리 | Chunk·triplet·community summary 등의 표현 |
| 답변 생성·평가 | 같은 generator와 평가 절차 | 저장된 근거에 따라 달라지는 답변 |

*공개 v3 §3의 평가 흐름을 설명하기 위해 재구성했다. 공통 절차를 사용해도 각 방법이 전달하는 정보와 입력량까지 같아지는 것은 아니다.*

이를 개념적으로 쓰면 $\widehat y=M(q,\operatorname{Serialize}(C(q)))$다. Generator $M$을 공통으로 두고, 질문 $q$에 대해 어떤 evidence $C(q)$를 가져오는지가 방법별로 달라진다. 이 식은 평가 흐름의 설명용 재구성이지, 논문이 제안한 새로운 최적화 목적이 아니다.

### 2.3 무엇을 통제하고 무엇은 같지 않은가

| 설정 | 공개 v3의 보고 |
| --- | --- |
| 그래프 구축 모델 | 기본 GPT-4o-mini, 부록에서 GPT-4o 비교 |
| Chunk 크기 | 약 256 tokens |
| Embedding | `text-embedding-ada-002` |
| 기본 검색 개수 | $k=10$ |
| Reranker | `BAAI/bge-reranker-large` |
| 반복 검색 | IRCoT |
| Generator | Llama-3.1-8B-Instruct, Llama-3.1-70B-Instruct |

[공개 v3 §3.4](https://arxiv.org/pdf/2502.11371v3#page=3)

같은 generator를 쓰는 것은 중요한 통제다. 그러나 GraphRAG는 그전에 구축 LLM으로 원문을 추출·요약한다. Generator가 같아도 evidence의 양과 표현, 상위 단계에서 사용한 계산은 다르다. 또한 같은 $k$는 검색 단위의 개수만 맞출 뿐, 같은 토큰이나 같은 정보량을 보장하지 않는다.

### `k=10`이 두 시스템에서 다른 일을 하는 예

MultiHop-RAG의 기본 설정에서 RAG의 상위 10개는 3,631 retrieved tokens였지만 Community Local의 상위 10개는 9,770 tokens였다. 전자는 대체로 독립 chunk 10개를 reader에 전달하고, 후자는 entity 주변 관계·설명·community 문맥을 함께 조립한 10개 단위를 전달한다. 그래서 두 결과가 모두 “top-10”이어도 reader가 읽는 근거 길이와 관계 정보의 밀도가 크게 다르다. [공개 v3 Table 31](https://arxiv.org/pdf/2502.11371v3#page=19)

저자들의 token-matched control은 이 차이를 확인하는 좋은 역방향 실험이다. RAG의 chunk 수를 늘려 Local의 token 양에 맞추자 8B MultiHop overall은 67.02에서 69.33으로 올라 Local 69.01과 비슷해졌다. 하지만 Temporal은 36.71로 Local 50.60보다 낮다. 즉 이 control은 전체 점수 차이의 일부가 context 양과 연결됐음을 보이지만, 시간·관계 결합에 필요한 representation까지 같은 것으로 만들지는 않는다. [공개 v3 Tables 2, 32–33](https://arxiv.org/pdf/2502.11371v3#page=20)

데이터 단위도 확인해야 한다. 이 공개본은 NQ를 single-document QA로 사용하며 문서마다 별도 RAG 시스템을 구성한다고 설명한다. NovelQA도 한 소설을 대상으로 검색하고, multi-document 과제는 여러 문서를 합친 index를 사용한다. 따라서 결과를 아무 corpus나 대상으로 하는 일반적인 open-domain retrieval 성능으로 확대해서는 안 된다. [공개 v3 Appendix A](https://arxiv.org/pdf/2502.11371v3#page=12)

## 3. QA 결과: 평균보다 질문 유형을 본다

### 3.1 Single-hop과 multi-hop의 큰 경향

아래는 기본 Llama-3.1-8B 결과다. NQ와 HotpotQA는 F1, MultiHop-RAG는 accuracy다. 서로 다른 지표를 한 종류의 점수처럼 평균하지 않는다.

| 방법 | NQ F1 | HotpotQA F1 | MultiHop-RAG accuracy |
| --- | ---: | ---: | ---: |
| RAG | 64.78 | 60.04 | 67.02 |
| RaptorRAG | 60.04 | 61.31 | 68.78 |
| KG Triplets | 34.28 | 25.02 | 41.24 |
| KG Triplets+Text | 50.27 | 42.60 | 48.51 |
| Community Local | 63.01 | 61.66 | 69.01 |
| Community Global | 54.48 | 45.16 | 64.40 |
| HippoRAG2 | 61.03 | 63.01 | 70.27 |

[공개 v3 Tables 1–2](https://arxiv.org/pdf/2502.11371v3#page=4)

NQ에서는 RAG가 높고, HotpotQA와 MultiHop-RAG에서는 HippoRAG2가 가장 높다. 그러나 같은 GraphRAG 범주 안에서도 triple-only와 text-guided 방식의 차이가 매우 크다. 이 표를 “multi-hop이면 어떤 GraphRAG든 유리하다”는 규칙으로 읽을 수는 없다.

또한 Community Local의 NQ F1 63.01과 RAG 64.78처럼 일부 차이는 작다. 주요 표에는 반복 실행의 분산이나 유의성 검정이 제시되지 않으므로, 점수의 방향과 차이의 크기를 보고하되 모든 차이를 통계적으로 확정된 우위라고 표현하지 않는다.

### 3.2 Multi-hop 안에서도 Null과 Temporal은 다르다

| 방법 | Inference | Comparison | Null | Temporal | Overall |
| --- | ---: | ---: | ---: | ---: | ---: |
| RAG | 92.16 | 57.59 | 96.01 | 30.70 | 67.02 |
| Community Local | 86.89 | 60.63 | 80.07 | 50.60 | 69.01 |
| Community Global | 89.34 | 64.02 | 19.27 | 53.34 | 64.40 |
| HippoRAG2 | 91.54 | 58.41 | 85.71 | 49.91 | 70.27 |

[공개 v3 Table 2](https://arxiv.org/pdf/2502.11371v3#page=4)

RAG는 이 benchmark의 Inference와 Null에 강하고, community 방식은 Comparison과 Temporal에서 높다. 여기서 Inference는 benchmark가 정의한 특정 query type이며 ‘모든 추론 문제’의 동의어가 아니다. Null은 근거에서 답을 도출할 수 없어 정보 부족을 인식해야 하는 질문이다.

Community Global은 Comparison·Temporal에서 높지만 Null은 19.27로 낮다. 높은 수준의 요약에서 관련된 이야기를 찾아내는 능력과, 현재 근거로는 답하면 안 된다는 판단은 다를 수 있다. 이 셀은 넓은 연결이 항상 더 정확한 답변으로 이어지지는 않는다는 점을 보여준다.

### 3.3 NovelQA: 긴 문서라는 이유만으로 그래프가 우세하지는 않다

| 방법 | Multi-hop | Single-hop | Detail | 전체 avg |
| --- | ---: | ---: | ---: | ---: |
| RAG | 47.34 | 68.73 | 55.28 | 57.12 |
| RaptorRAG | 48.17 | 66.25 | 57.72 | 57.12 |
| Community Local | 47.01 | 63.43 | 46.88 | 53.03 |
| HippoRAG2 | 47.84 | 66.25 | 55.83 | 56.54 |

[공개 v3 Table 3](https://arxiv.org/pdf/2502.11371v3#page=5). 앞의 세 열은 각 질문 유형 행의 마지막 `avg`이며, 마지막 열은 원문 표 맨 아래의 전체 `avg`다. 질문 유형별 평균과 전체 평균을 구분해 발췌했다.

RAG가 Single-hop에서 가장 높고 Community Local보다 세 group 모두 높다. 하지만 Multi-hop과 Detail에서는 RaptorRAG와 HippoRAG2가 RAG보다 조금 높다. 따라서 “RAG는 모든 detail 질문에서 이긴다”는 문장도 표 전체를 정확히 요약하지 못한다. 문서가 길다는 사실보다 **어떤 세부가 어디에 있고 어떤 연결을 요구하는지**를 함께 봐야 한다.

## 4. 그래프의 정보 보존과 검색 개선의 한계

### 4.1 그래프에서 빠진 정보는 어떻게 복구되는가

KG Triplets가 낮은 이유를 저자들은 불완전한 graph construction과 연결한다. 공개본은 정답 개체가 구축된 KG에 등장하는 비율을 HotpotQA 약 65.8%, NQ 약 65.5%로 보고한다. [공개 v3 §4.2, Appendix C](https://arxiv.org/pdf/2502.11371v3#page=14)

구조화는 압축이기도 하다. Triple로 바꿀 때 빠진 시점·수식어·인용 맥락은 그래프 경로만으로 다시 얻기 어렵다. Source text를 함께 제공한 KG Triplets+Text가 triple-only보다 높은 것은 이러한 정보 복구의 가치와 일치한다.

다만 KG 안의 정답 개체 coverage를 generator 정확도의 엄밀한 상한으로 해석하면 안 된다. Generator가 사전학습 지식이나 다른 문맥으로 답을 만들 수 있기 때문이다. 그 비율은 **graph에 evidence가 보존되었는가**에 대한 관측이다.

### 4.2 Retrieval accuracy도 무엇을 세는지 확인해야 한다

Appendix C의 retrieval accuracy는 정답 문자열이 retrieved context에 등장하는 비율이다. 모든 supporting fact가 회수되었는지 또는 올바른 논리 경로가 있는지를 평가한 recall과는 다르다.

| 방법 | HotpotQA 정답 문자열 포함률 | NQ 정답 문자열 포함률 |
| --- | ---: | ---: |
| RAG | 88.60 | 86.70 |
| KG Triplets | 39.20 | 32.18 |
| KG Triplets+Text | 69.80 | 61.50 |
| Community Local | 67.53 | 42.20 |
| Community Global | 88.60 | 83.30 |

[공개 v3 Table 16](https://arxiv.org/pdf/2502.11371v3#page=14)

Community Global의 HotpotQA 포함률은 RAG와 같지만, 최종 F1은 더 낮다. 정답 문자열이 있다고 그것이 올바른 질문 관계에 연결되어 있는 것은 아니다. 반대로 원문 그대로의 문자열이 없어도 동의어나 요약으로 필요한 정보가 표현될 수 있다. 이 지표는 coverage의 한 측면으로 읽어야 한다.

### 4.3 Reranking과 반복 검색은 구조와 별도의 개선 축이다

[![NQ와 MultiHop-RAG에서 Rerank, Vanilla, IRCoT 설정에 따른 RAG 계열 성능 비교](figures/rvg-fig1-retrieval-strategies.png)](figures/rvg-fig1-retrieval-strategies.png)

*공개 v3 Figure 1. 왼쪽은 NQ, 오른쪽은 MultiHop-RAG이며 검색 이후 보강 전략에 따라 각 방법의 결과가 바뀐다. 원그림과 캡션은 두 패널을 F1으로 표기하지만, 본문의 MultiHop-RAG 지표는 accuracy다. 이 글은 dataset별 본문·표의 정의를 따른다. Han et al. (2026), [arXiv v3 PDF p. 4](https://arxiv.org/pdf/2502.11371v3#page=4). 원본 도판 영역 직접 추출, CC BY 4.0.*

그림을 누르면 원본 해상도로 확대할 수 있다.

Reranking은 우선 더 넓게 얻은 후보를 query와 다시 비교하고, IRCoT는 중간 추론과 검색을 번갈아 수행한다. 공개본은 reranking에서 20개 후보를 다시 평가해 최종 10개를 고른다. 이는 graph representation과 다른 개선 축이다. [공개 v3 Appendices E–F](https://arxiv.org/pdf/2502.11371v3#page=15)

그러나 더 많은 검색·추론이 항상 좋은 것은 아니다. Community Local의 MultiHop-RAG Null accuracy는 IRCoT에서 80.07에서 50.50으로 떨어진다고 보고된다. 주변 정보를 더 많이 얻으면서 정보 부족을 인정하는 대신 답을 만들어낼 수 있다는 해석이다. 전체 점수와 abstention이 필요한 질문의 성능을 분리해 봐야 한다.

## 5. 상보성에서 Selection·Integration으로

### 5.1 서로 다른 질문에 성공한다는 것이 출발점이다

[![RAG와 Community GraphRAG Local의 정답·오답 조합을 네 QA dataset에서 비교한 confusion matrices](figures/rvg-fig2-complementary-errors.png)](figures/rvg-fig2-complementary-errors.png)

*공개 v3 Figure 2. 대각선 밖의 셀은 한 방법만 맞힌 질문을 뜻한다. MultiHop-RAG에서는 RAG-only 11.6%, GraphRAG-only 13.6%가 있어 보완 가능성을 보여준다. 여기의 GraphRAG는 Community Local이고, correctness의 이진 분류는 앞선 NQ F1과 같은 통계가 아니다. Han et al. (2026), [arXiv v3 PDF p. 5](https://arxiv.org/pdf/2502.11371v3#page=5). 원본 도판 영역 직접 추출, CC BY 4.0.*

서로 다른 오류를 낸다는 것은 혼합 시스템의 가능성을 보여준다. 그러나 어느 방법이 맞을지 미리 알아내는 classifier가 있어야 선택의 이득을 얻고, 양쪽 evidence를 합쳤을 때 generator가 올바르게 활용해야 통합의 이득을 얻는다. 상보성이 관찰되었다는 사실만으로 실제 hybrid의 우위가 따라오지는 않는다.

### 5.2 Selection은 하나를 고르고 Integration은 둘 다 실행한다

| 전략 | 절차 | 추가로 필요한 판단·비용 |
| --- | --- | --- |
| Selection | Query를 fact-based 또는 reasoning-based로 분류해 각각 RAG 또는 Community Local로 보낸다. | Router의 오분류와 분류 호출 비용 |
| Integration | 두 방식으로 검색한 context를 합쳐 generator에 전달한다. | 양쪽 검색과 더 긴 evidence 처리 비용 |

[공개 v3 §4.5, Appendices G–H](https://arxiv.org/pdf/2502.11371v3#page=15)

Selection은 query당 한 검색 경로를 사용하지만, 서비스를 준비하려면 두 경로의 index를 보유해야 할 수 있다. 따라서 query-time 계산 절약과 offline graph construction 비용을 구분해야 한다. Integration은 그때그때 양쪽 근거를 확보하는 대신 정보 충돌과 context 길이의 문제도 함께 가져온다.

또한 공개본 Appendix G의 classifier에는 fact-based와 reasoning-based 두 label만 있고, `Null`이나 `insufficient evidence`라는 세 번째 선택지는 없다. 답을 도출할 근거가 없는 질문도 어느 한 검색 경로로 배정된다. 이는 검색 뒤 generator가 답변을 유보할 수 없다는 뜻은 아니지만, **Selection 자체가 answerability 또는 abstention을 판정하는 장치는 아니다.** Query 유형 분류와 evidence sufficiency 판정은 별도로 평가해야 한다. [공개 v3 Figure 7의 분류 prompt](https://arxiv.org/pdf/2502.11371v3#page=18)

[![Llama-3.1-8B와 70B에서 RAG, GraphRAG, Selection, Integration의 QA 결과를 비교한 그래프](figures/rvg-fig3-hybrid-comparison.png)](figures/rvg-fig3-hybrid-comparison.png)

*공개 v3 Figure 3. 네 전략의 개괄적 비교다. 일부 막대의 높이는 부록 수치와 정확히 대응하지 않아, 이 글의 정량 해석은 Tables 20–22를 우선한다. 특히 8B MultiHop-RAG에서 Integration이 항상 최고라는 근거로 쓰지 않는다. Han et al. (2026), [arXiv v3 PDF p. 6](https://arxiv.org/pdf/2502.11371v3#page=6). 원본 도판 영역 직접 추출, CC BY 4.0.*

### 5.3 작은 generator에서는 통합이 오히려 불리한 경우도 있다

| Generator·전략 | MultiHop Overall | Null |
| --- | ---: | ---: |
| 8B RAG | 67.02 | 96.01 |
| 8B Community Local | 69.01 | 80.07 |
| 8B Integration | 68.19 | 50.17 |
| 70B RAG | 65.77 | 91.36 |
| 70B Community Local | 71.17 | 88.70 |
| 70B Integration | 77.62 | 59.47 |

[공개 v3 Tables 21–22](https://arxiv.org/pdf/2502.11371v3#page=17)

8B에서는 Integration이 RAG보다 높지만 Community Local보다 낮다. Null 손실이 다른 유형의 이득을 상쇄한다. 70B는 overall이 크게 높아지지만 Null은 여전히 낮아진다. 큰 모델이 많은 evidence를 활용하는 능력과 불충분한 근거에 답하지 않는 능력은 함께 움직이지 않을 수 있다.

한편 NQ와 HotpotQA에서는 Integration의 F1이 두 단독 방식보다 높게 보고된다. 예를 들어 8B의 NQ는 66.28, HotpotQA는 64.76이다. 결론은 통합의 보편적 우위가 아니라 **질문 유형과 generator 용량에 따라 이득과 손실의 구성이 달라진다**는 것이다. [공개 v3 Table 20](https://arxiv.org/pdf/2502.11371v3#page=17)

## 6. 요약: 정답과 닮은 글, 다양한 글, 선호되는 글

### 6.1 참조 요약과 비교하면 세부 정보의 보존이 중요하다

논문은 단일 문서의 SQuALITY·QMSum, 다중 문서의 ODSum-story·ODSum-meeting을 비교한다. ROUGE-2는 어휘 중첩, BERTScore는 embedding 기반 의미 유사도를 평가한다. 이들은 human reference와의 대응을 측정하며, 사실성·완전성·다양성의 전부를 직접 측정하는 것은 아니다.

아래는 Llama-3.1-8B의 ROUGE-2 F1 결과 중 주요 방법이다.

| 방법 | SQuALITY | QMSum | ODSum-story | ODSum-meeting |
| --- | ---: | ---: | ---: | ---: |
| RAG | 10.08 | 6.32 | 9.81 | 8.77 |
| RaptorRAG | 9.81 | 6.68 | 9.62 | 8.44 |
| Community Local | 10.10 | 5.64 | 8.49 | 8.02 |
| Community Global | 6.99 | 3.23 | 5.46 | 5.59 |
| HippoRAG2 | 10.20 | 6.60 | 9.82 | 8.51 |
| Integration | 10.67 | 6.34 | 9.53 | 8.51 |

[공개 v3 Tables 6–7](https://arxiv.org/pdf/2502.11371v3#page=8)

Global summary가 넓은 내용을 담더라도 query-specific reference에 필요한 세부를 보존하지 못할 수 있다. 특히 ODSum-meeting에서는 RAG가 이 ROUGE-2 F1과 BERTScore F1 모두에서 가장 높게 보고된다. 그러나 모든 dataset·metric에서 RAG가 최고라는 뜻은 아니다.

SQuALITY의 BERTScore F1은 KG Triplets+Text가 84.92로 가장 높고 RAG는 77.62다. 이 예외는 중요한데, ‘원문 chunk를 쓰는 방법이 항상 reference metric에서 우세하다’는 서술도 모든 셀을 설명하지 못하기 때문이다. 아주 작은 차이인 ODSum-story의 RAG 9.81과 HippoRAG2 9.82 역시 유의성 정보 없이 실질적인 우위라고 판단하기는 어렵다. [공개 v3 Tables 6–7](https://arxiv.org/pdf/2502.11371v3#page=8)

### 6.2 LLM judge는 무엇을 선호하는가

공개본은 두 후보 요약을 LLM에게 제시해 comprehensiveness와 diversity를 비교한다. 같은 요약이라도 제시 순서를 바꾸어 평가한다. Order 1에서는 RAG가 먼저, Order 2에서는 GraphRAG가 먼저다.

[![요약 후보의 제시 순서를 뒤집었을 때 RAG와 GraphRAG에 대한 LLM judge의 선호 비율이 변하는 비교](figures/rvg-fig4-judge-position-bias.png)](figures/rvg-fig4-judge-position-bias.png)

*공개 v3 Figure 4. 색과 빗금은 시스템뿐 아니라 제시 순서도 구분한다. 특히 Local 비교에서는 순서를 바꾸면 선호가 크게 달라지는 패널이 있다. 막대는 정답률이 아니라 해당 순서에서의 선호 비율이다. Han et al. (2026), [arXiv v3 PDF p. 8](https://arxiv.org/pdf/2502.11371v3#page=8). 원본 도판 영역 직접 추출, CC BY 4.0.*

이 그림은 한 번의 presentation order로 평가한 승률을 그대로 모델 품질로 읽기 어렵다는 근거다. 순서를 균형 있게 바꿔 평가하고, 두 순서에서 판단이 얼마나 일관되는지도 보고하는 편이 타당하다. 단, 순서 평균을 냈다는 것만으로 모든 evaluator bias가 사라졌다고 보장할 수는 없다.

Global 비교에서는 GraphRAG가 diversity에서, RAG가 comprehensiveness에서 선호되는 경향을 보고한다. 이것을 ‘GraphRAG가 더 정확하다’로 바꾸어 말하면 평가 대상을 바꾼 것이다. 넓은 주제와 다양한 관점을 포함하는 것, 질문에 필요한 내용을 충분히 담는 것, 참조 요약과 비슷한 것은 서로 다른 속성이다. [공개 v3 §5.3](https://arxiv.org/pdf/2502.11371v3#page=7)

## 7. 같은 top-k와 같은 비용은 다르다

### 7.1 입력 토큰량을 맞추면 전체 점수 차이가 줄어든다

공개본의 검색 결과에서 MultiHop-RAG는 RAG 3,631 tokens, Community Local 9,770 tokens이고, ODSum-story는 2,279 대 10,244 tokens다. RAG는 chunk를, Local은 entity와 관계·설명·community 정보를 가져오기 때문이다. [공개 v3 Table 31](https://arxiv.org/pdf/2502.11371v3#page=19)

저자들은 RAG의 chunk 수를 늘려 Local과 retrieved-token 양을 맞춘 추가 실험을 수행한다.

| Generator·방법 | MultiHop Overall | Temporal | Null |
| --- | ---: | ---: | ---: |
| 8B RAG | 67.02 | 30.70 | 96.01 |
| 8B RAG, token matched | 69.33 | 36.71 | 89.04 |
| 8B Community Local | 69.01 | 50.60 | 80.07 |
| 70B RAG | 65.77 | 25.73 | 91.36 |
| 70B RAG, token matched | 71.01 | 43.74 | 88.70 |
| 70B Community Local | 71.17 | 49.06 | 88.70 |

[공개 v3 Tables 32–33](https://arxiv.org/pdf/2502.11371v3#page=20)

8B overall은 token-matched RAG가 Local보다 약간 높고, 70B는 두 방법의 차이가 0.16%p로 작다. 그렇다고 그래프의 이득이 모두 사라진 것은 아니다. Temporal에서는 여전히 Local이 높다. **전체 평균 격차 일부는 입력량과 연결되고, 특정 관계를 결합하는 일부 질문의 차이는 그 뒤에도 남는다.**

이 통제 역시 완전한 동등 조건은 아니다. 같은 토큰 수가 같은 정보량, 같은 index 구축 비용, 같은 검색 계산을 뜻하지 않기 때문이다. 그러나 단순한 top-k 일치보다 중요한 추가 검증인 것은 분명하다.

### 7.2 구축 시간·검색 시간·저장량을 분리한다

| 방법 | 구축 시간(초) | 검색 시간(초) | 저장량(MB) |
| --- | ---: | ---: | ---: |
| RAG | 135 | 1724 | 127 |
| KG-GraphRAG | 7702 | 14434 | 117 |
| Community-GraphRAG | 5560 | 1249 | 165 |

[공개 v3 Table 4](https://arxiv.org/pdf/2502.11371v3#page=6). 이는 MultiHop-RAG에서 보고된 측정값이며, 이 표만으로 시간 집계 단위와 hardware·병렬화 조건이 충분히 고정되지 않는다. 따라서 검색 시간을 질문 하나당 지연으로 해석하기는 어렵다.

KG 방식은 구축과 검색 시간이 크지만 저장량은 RAG보다 작다. Community 방식은 구축 비용이 크고 저장량도 늘지만, 보고된 검색 시간은 RAG보다 짧다. 따라서 ‘GraphRAG는 모든 비용이 더 높다’는 문장도 표와 맞지 않는다. 어떤 단계에 비용을 먼저 지불하고, 그 index를 얼마나 반복 사용하느냐가 중요하다.

### 7.3 더 좋은 구축 모델이 항상 더 좋은 결과를 만들지는 않는다

| Generator | GPT-4o-mini로 만든 Local | GPT-4o로 만든 Local |
| --- | ---: | ---: |
| Llama-3.1-8B | 69.01 | 68.74 |
| Llama-3.1-70B | 71.17 | 75.08 |

[공개 v3 Tables 27–28](https://arxiv.org/pdf/2502.11371v3#page=19), MultiHop-RAG overall accuracy.

70B에서는 GPT-4o 구축의 이득이 크지만 8B overall은 약간 낮아진다. 70B도 Null은 88.70에서 81.06으로 떨어진다. 구축 모델을 바꾸면 그래프의 정확성뿐 아니라 내용의 양과 추상화, 검색 결과도 함께 달라질 수 있다. 이 비교는 구축 품질이 중요한 변수임을 보여주지만, 그 변수의 효과가 모든 generator와 query type에서 단조롭다는 법칙을 주지는 않는다.

## 8. 원문·코드·사례에서 확인할 평가의 경계

### 8.1 정성 사례는 작동 원리를 보여주지만 일반 성능의 증명은 아니다

[![RAG와 KG, community 기반 근거가 서로 다른 연도를 답하는 HotpotQA 사례](figures/rvg-fig5-qa-case1.png)](figures/rvg-fig5-qa-case1.png)

*공개 v3 Figure 5. RAG는 retrieved passage의 1923을 답하고, Community 방식은 요약된 관계에서 gold answer인 October 1922를 답하는 사례다. 이 그림은 근거 단위가 답에 영향을 주는 예시이며, 전쟁 종결 시점이나 질문 문구의 독립적 타당성까지 검증한 평가로 간주하지 않는다. Han et al. (2026), [arXiv v3 PDF p. 14](https://arxiv.org/pdf/2502.11371v3#page=14). 원본 도판 영역 직접 추출, CC BY 4.0.*

이런 사례는 여러 문장에 흩어진 관계를 하나의 community 설명으로 모았을 때 답을 얻는 원리를 이해하는 데 도움이 된다. 동시에 근거 추출·요약·gold answer 중 어디에 오류가 있는지도 별도로 봐야 한다. 단일 성공 사례로 모든 관계 결합이 올바르다고 결론내릴 수는 없다.

### 8.2 Gold와 일치해도 독립적인 사실성은 별도다

[![Canberra 폭격기와 제2차 세계대전의 관계를 묻는 질문에 GraphRAG가 gold answer와 일치하는 답을 낸 사례](figures/rvg-fig6-qa-case2.png)](figures/rvg-fig6-qa-case2.png)

*공개 v3 Figure 6. 저자는 GraphRAG가 정답을 얻는 사례로 제시하지만, 질문의 제2차 세계대전 시점과 답변 기체의 연혁이 충돌한다. 따라서 이 글은 성공 증거뿐 아니라 benchmark gold와 사실성의 차이를 보여주는 사례로 분석한다. 원그림의 문구는 수정하지 않았다. Han et al. (2026), [arXiv v3 PDF p. 15](https://arxiv.org/pdf/2502.11371v3#page=15). 원본 도판 영역 직접 추출, CC BY 4.0.*

질문은 제2차 세계대전의 South West Pacific 전장에서 사용된 영국 초기 제트 폭격기를 묻고, gold는 English Electric Canberra다. 그러나 BAE Systems의 공식 기체 연혁은 prototype의 첫 비행을 1949년 5월 13일, RAF의 첫 기체 인도를 1951년 5월 25일로 기록한다. 질문의 전쟁 시점과 맞지 않는다. [BAE Systems의 Canberra 연혁](https://www.baesystems.com/heritage/page/english-electric-canberra)

공개본의 GraphRAG 근거 안에도 1950년대 제작 설명과 제2차 세계대전 참전 표현이 함께 들어 있다. 또한 제시된 두 triple의 squadron 이름도 다르므로, 그 조각만으로 완전한 연결 경로가 성립한다고 보기 어렵다. 이 사례는 관계를 연결할 때 **개체의 활동 시점과 관계 주체를 함께 보존해야 한다**는 점을 보여준다.

이 사례 하나로 전체 benchmark 결과가 무효가 되는 것은 아니다. 이 공개본의 정성 사례에는 확인 가능한 시점 문제가 있으며, gold 일치와 독립적인 사실 검증은 다르다는 범위의 비판이다. ACM 최종판에서 이 사례가 수정되었는지는 직접 대조하지 못했다.

### 8.3 공개 코드의 통일 수준과 재현 한계

저자 저장소의 검토 snapshot은 `d2a0c0c`이며, GitHub API에 기록된 commit 시각은 2026년 2월 27일 02:09:05 UTC로 arXiv v3와 KDD 출판보다 앞선다. 검색 결과를 저장한 뒤 공통 QA 생성 코드가 읽는 구조는 확인되지만, 이 snapshot을 최종 실험의 정확한 실행 버전이라고 단정할 수는 없다. [공식 저장소 snapshot](https://github.com/haoyuhan1/RAGvsGraphRAG/tree/d2a0c0c0deb0903d60338d3c416ccd6f9544267c)

구현을 보면 통제 범위가 더 구체적으로 드러난다. KG retrieval은 LlamaIndex의 vector context와 path depth를 사용하고, Microsoft Global은 community report와 별도 token limit을 사용한다. Local도 entity·relation·source를 조립한다. 공통 generator를 사용해도 evidence serialization과 실질적인 budget은 완전히 같지 않다. [KG retrieval](https://github.com/haoyuhan1/RAGvsGraphRAG/blob/d2a0c0c0deb0903d60338d3c416ccd6f9544267c/graph_retrieval.py), [Global retrieval](https://github.com/haoyuhan1/RAGvsGraphRAG/blob/d2a0c0c0deb0903d60338d3c416ccd6f9544267c/graphrag_global.py)

공개 iterative retrieval 경로는 매 step에서 얻은 evidence를 누적한다. 따라서 ‘최종 top-k 또는 token budget이 항상 엄격하게 동일하다’는 조건은 실제 실행에서 별도 확인이 필요하다. 공개 코드의 존재만으로 모든 hybrid routing·integration 결과와 최종 표가 완전히 재현됐다고 말할 수도 없다. [공식 retrieval 구현](https://github.com/haoyuhan1/RAGvsGraphRAG/blob/d2a0c0c0deb0903d60338d3c416ccd6f9544267c/retrieval.py)

### 8.4 그래프 구조의 순수한 효과를 분리한 실험은 아니다

이 비교에서는 graph construction, retrieval target, context 길이, summary 정보와 generator의 활용 능력이 함께 바뀐다. 동일한 사실을 보존한 채 구조만 제거하는 ablation이나, evidence 길이·구축 계산을 모두 맞춘 비교와는 다르다.

그러므로 강한 결론은 ‘이 구현 묶음들이 이 데이터에서 다르게 작동했다’는 것이다. 이 결과는 실제 시스템 선택에 유용하지만, 구조 자체의 인과 효과를 모든 상황에 적용하는 이론은 아니다. Token matching, 70B 비교, 구축 모델 교체는 이 문제를 더 잘 이해하게 하는 보조 실험이며, 각 통제가 해결한 차이와 남겨 둔 차이를 구분해야 한다.

## 9. 적용 기준과 결론

이 논문을 적용 가능한 판단으로 바꾸려면 먼저 질문과 평가 목표를 분해하는 편이 좋다.

| 판단할 것 | 비교에 필요한 관측 |
| --- | --- |
| 질문에 필요한 근거가 한 chunk에 있는가? | 강한 vector retrieval과 reranking 기준선 |
| 서로 다른 문서·시간·개체의 관계를 연결해야 하는가? | 관계 보존과 supporting evidence 회수, query-type별 성능 |
| 구조화 과정에서 중요한 세부가 사라지는가? | Triple-only와 source-text 결합, answer coverage |
| 근거가 없을 때 답하지 않아야 하는가? | Null·abstention 성능을 전체 평균과 별도로 평가 |
| 요약의 목표가 정확한 세부인가, 넓은 주제인가? | Reference metric, comprehensiveness, diversity, 사실성의 분리 |
| Judge 결과가 믿을 만한가? | 제시 순서 교환, judge 간 일치, human audit |
| 비용을 어디서 지불하는가? | 구축·갱신·검색·생성 비용과 index 재사용 횟수 |

이 표는 공개본의 결과에서 도출한 평가 설계 제안이다. 특정 방법을 무조건 채택하라는 배포 권고가 아니다. 특히 새로운 corpus에서는 데이터 변화와 질문 분포, 실제 generator가 다르므로 같은 비교를 다시 수행해야 한다.

이 연구의 기여는 GraphRAG의 장점만 보여주는 것이 아니라, 원문 텍스트를 보존하는 검색이 여전히 강한 조건과 구조가 유리한 조건을 같은 평가 틀 안에서 드러낸다는 데 있다. 입력량을 맞추면 줄어드는 점수 차이, 정답이 없는 질문에서의 실패, LLM judge의 순서 효과는 모두 평균 순위 하나로는 보이지 않는 결과다.

이 연구에서 가져갈 판단 기준은 **그래프를 썼는지보다 무엇을 보존하고 무엇을 검색해 어떤 기준으로 답을 평가했는지를 먼저 확인해야 한다**는 것이다. RAG와 GraphRAG의 상보성을 활용하는 hybrid는 유망하지만, 합치면 항상 좋아진다는 결론까지는 이 공개본의 표가 뒷받침하지 않는다. 구조·정보량·평가·비용을 분리해 읽을 때 이 논문은 더 유용한 시스템 비교 자료가 된다.

*도판은 저자 공개 arXiv v3의 Figures 1–6을 영역별로 추출하고 한국어 해설을 덧붙였다. 원본 그래프·축·문구는 유지했다. arXiv 등록 라이선스는 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)이다. 기술적 분석과 수치는 이 공개본 기준이며, ACM 최종 PDF와의 일치 및 모델 실험의 독립 재실행을 주장하지 않는다.*

## References

BAE Systems. (n.d.). *English Electric Canberra*. BAE Systems Heritage. [기체 연혁](https://www.baesystems.com/heritage/page/english-electric-canberra)

Gutiérrez, B. J., Shu, Y., Qi, W., Zhou, S., & Su, Y. (2025). From RAG to memory: Non-parametric continual learning for large language models. In *Proceedings of the 42nd International Conference on Machine Learning* (Vol. 267, pp. 21497–21515). PMLR. [PMLR proceedings](https://proceedings.mlr.press/v267/gutierrez25a.html)

Han, H., Ma, L., Wang, Y., Shomer, H., Guo, K., Lei, Y., Qi, Z., Hua, Z., Long, B., Liu, H., Aggarwal, C., & Tang, J. (2026). RAG vs. GraphRAG: A systematic evaluation and key insights. In *Proceedings of the 32nd ACM SIGKDD Conference on Knowledge Discovery and Data Mining V.2* (pp. 8966–8977). Association for Computing Machinery. [https://doi.org/10.1145/3770855.3817575](https://doi.org/10.1145/3770855.3817575)

Han, H., Ma, L., Wang, Y., Shomer, H., Lei, Y., Qi, Z., Guo, K., Hua, Z., Long, B., Liu, H., Aggarwal, C. C., & Tang, J. (2026). *RAG vs. GraphRAG: A systematic evaluation and key insights* (arXiv:2502.11371v3). arXiv. [실제 분석에 사용한 공개본](https://arxiv.org/abs/2502.11371v3)

Sarthi, P., Abdullah, S., Tuli, A., Khanna, S., Goldie, A., & Manning, C. D. (2024). *RAPTOR: Recursive abstractive processing for tree-organized retrieval*. International Conference on Learning Representations. [arXiv:2401.18059](https://arxiv.org/abs/2401.18059)
