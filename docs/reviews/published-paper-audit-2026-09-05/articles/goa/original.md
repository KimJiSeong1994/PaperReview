**Paper:** Yun, S., Peng, J., Li, P., Fan, W., Chen, J., Zou, J., Li, G., & Chen, T. (2026). *Graph-of-Agents: A graph-based framework for multi-agent LLM collaboration*. **ICLR 2026** (arXiv:2604.17148). UNITES-Lab(UNC, Tianlong Chen)·Stanford(James Zou)·CAMEL-AI(Guohao Li). 코드 [github.com/UNITES-Lab/GoA](https://github.com/UNITES-Lab/GoA).

**Abstract:** LLM이 폭증하면서 여러 모델을 조합해 성능을 올리려는 요구가 커졌다. Mixture-of-Agents(MoA)는 여러 LLM을 조율하지만 (1) 관련 에이전트 선택, (2) 에이전트 간 통신, (3) 응답 통합에서 부족하다. GoA(Graph-of-Agents)는 다중 에이전트 LLM 통신을 그래프로 모델링한다. 에이전트를 노드로, 관련도 관계를 엣지로 보고, 노드 샘플링(모델 카드로 관련 에이전트만 선택) → 엣지 샘플링(서로 평가해 관련도 순위) → 방향 있는 메시지 전달(관련도 높은 노드→낮은 노드, 그다음 역방향) → 그래프 풀링(max/mean)으로 하나의 답을 만든다. 6개 LLM 풀에서 GoA는 놀랍게도 **3개 에이전트만으로** 6개를 모두 쓰는 최신 다중 에이전트 베이스라인을 능가한다고 보고한다. 이 글은 이 test-time 오케스트레이션 프레임워크가 무엇을 만들었고 다섯 표(Table 1–5)가 실제로 무엇을 보였는지, 그리고 표제 서사—"3개가 6개를 이긴다"·"그래프가 이유다"·"MoA를 일반화한다"—가 어디까지 뒷받침되는지를 나눠 읽는다. 잘 만든 논문이고, 비판할 지점은 대개 프레이밍과 통계에 있지 엔지니어링에 있지 않다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | LLM "동물원"이 커지는 시대에, 어떻게 여러 에이전트가 강점을 살리고 약점을 보완하며 test-time에 효율적으로 협업하게 설계할 것인가?(§1) MoA의 세 한계: 관련 에이전트 선택 부재·미세 통신 부재·전체 토큰 연결의 $O(LNd)$ 비용. |
| 핵심 기여 | 다중 에이전트 협업을 **그래프**로 정식화한 GoA. 노드 샘플링(메타-LLM이 모델 카드로 top-k 선택)·엣지 샘플링(에이전트 상호 평가→가중 방향 인접행렬, τ=0.05 가지치기)·양방향 메시지 전달(source→target→source)·그래프 풀링(GoA_Max/GoA_Mean). Test-time·프롬프트 전용(학습 없음, 블랙박스 API). MoA를 특수 사례로 일반화(Prop 1). |
| 실험 결과 | 6벤치마크(MMLU·MMLU-Pro·GPQA·MATH·HumanEval·MedMCQA), 6-LLM 풀(7–8B). GoA(3개)가 6개 중 5개서 최고(MMLU 79.18·MMLU-Pro 54.78·GPQA 40.54·MATH 73.12·MedMCQA 60.04). **효율**(Table 2): MoA 대비 호출 약 2배·토큰 약 3배·시간 약 2배 절감 + 더 정확. |
| 핵심 한계 | "그래프"는 프롬프트 오케스트레이션 위의 조직 어휘(메시지 전달=이웃 텍스트로 재프롬프트, 학습 없음). "3이 6/8을 이긴다"는 좁다: GoA_Max(6)>GoA_Max(3)·DyLAN(8)이 GPQA서 GoA 이김·HumanEval은 Code 단일(85.37)이 GoA(84.98) 이김. 승부 초박빙(MMLU-Pro +0.07)·분산/유의성 없음·부분표본. |

**TL;DR**

- Graph-of-Agents(GoA)는 여러 LLM 에이전트의 협업을 그래프로 보아, 모델 카드로 관련 에이전트만 뽑고(노드 샘플링) 서로 평가해 방향 인접행렬을 만든 뒤(엣지 샘플링) 관련도 높은 노드→낮은 노드로 양방향 재프롬프트하고 max/mean으로 합치는(그래프 풀링) test-time·프롬프트 전용 오케스트레이션 프레임워크다.
- Graph-of-Agents는 6개 7–8B LLM 풀에서 단 3개 에이전트만으로 6개 벤치마크 중 5개에서 최고를 기록하고, MoA 대비 LLM 호출을 약 2배·토큰을 약 3배·시간을 약 2배 줄이면서 더 정확한 파레토 개선을 측정으로 보인다.
- Graph-of-Agents의 '그래프'는 그러나 학습된 연산이 아니라 프롬프트 오케스트레이션 위의 조직 어휘이며(인접 가중치는 high/moderate/low 세 등급으로 붕괴), '3이 6/8을 이긴다'는 GoA_Max(6)>GoA_Max(3)·GPQA에서 DyLAN(8) 우세·HumanEval 단일 Code 모델 우세에서 깨지고 승부가 초박빙(MMLU-Pro +0.07)이며 분산·유의성 보고가 없다.

## 목차

1. 서론
2. 방법: GoA 파이프라인
3. 실험
4. 주의해서 읽을 점
5. 결론

---

## 1. 서론

### 1.1 문제와 세 도전

문제 설정은 "LLM도 벤치마크도 너무 많다"이다(§1). 모델 생태계가 커지면서 test-time에 여러 모델을 효과적으로 조합하는 것이 중심 과제가 된다. 이른 시도가 Mixture-of-Agents(MoA)로, Mixture-of-Experts 방식으로 여러 LLM 에이전트의 응답을 모아 원 질의에 덧붙여 다음 층에 넘긴다(Fig 1c). GoA는 MoA를 주된 비교 대상(foil)으로 삼고 세 도전으로 기여를 구조화한다.

**❶ 어떤 에이전트?** MoA는 에이전트 선택 장치가 없어 질의를 가용 에이전트 **전부**에 보낸다. 과도한 비용, "다중 에이전트 폭발", 무관한 에이전트의 잡음을 낳는다. → GoA의 답은 **노드 샘플링**. **❷ 어떻게 통신?** MoA는 다대일 집계로 모든 응답을 한 덩어리로 취급해 개별 쌍의 1대1 미세 상호작용을 못 잡고, 균등 가중이 합의를 방해한다. → **엣지 샘플링 + 방향 메시지 전달**. **❸ 어떻게 통합?** MoA는 모든 에이전트의 토큰을 연결해 복잡도 $O(LNd)$($L$ 층·$N$ 에이전트·$d$ 토큰 길이)로 비싸고, 모든 에이전트를 균등 취급한다. → **그래프 풀링**. 여기서 ❶의 "무관 에이전트 잡음"이 표제 결과의 하중 지점이다(뒤 4장에서 재론).

![Figure 1: MoA와 GoA](/api/blog/figures/goa-fig1-moa-vs-goa.png)

*그림 1 — 원논문 Figure 1: 현재 다중 에이전트 LLM 파이프라인과 제안. (a) 여러 도메인(생의학+수학+코드)에 걸친 질의, (b) 큰 LLM 풀에서 효과적인 다중 에이전트 시스템을 구성하는 도전, (c) MoA는 가용 에이전트 전부를 통합·집계해 다음 층에 넘김(큰 풀에 일반화 안 되고 층내 통신 부담 큼), (d) GoA는 관련 에이전트 부분집합만 노드로 뽑아 관련도 높은 노드→낮은 노드 방향 메시지 전달로 통신.*

### 1.2 그래프 재프레임과 학술적 위치

GoA는 "에이전트를 노드로, 관련도 관계를 엣지로" 모델링해 구조화된 메시지 전달을 가능케 한다(§1). 형식적으로 방향 그래프 $\mathcal{G}=(\mathcal{V},\mathcal{E})$이고, $S$개 관련 에이전트를 뽑으면 인접행렬 $\mathbf{A}\in\mathbb{R}^{S\times S}$를 만든다. 곧 MoA의 완전 그래프 대신 **질의별 부분그래프**만 활성화한다. 한 가지 성격을 미리 짚어 두면, 이는 학습이 아니다. 논문이 명시하듯 "MoA처럼 순수 프롬프트 인터페이스로 작동해 블랙박스 LLM API와 호환되고 test-time 추론에서 적응적"이다(§1). 학습되는 그래프도, 미분 가능한 전파도 없다. 뒤에서 보듯 "메시지 전달"은 이웃의 텍스트 응답을 새 프롬프트에 넣는 것이다.

관련 연구(§2)는 넷을 겨냥한다. 단일 LLM 추론(CoT·ToT·GoT — GoT는 한 모델의 추론 단계를 그래프로 보는데, GoA는 그 발상을 에이전트로 옮긴다), 다중 에이전트 test-time(Debate·ChatEval — "대칭 토론이나 순차 정제 같은 단순 프로토콜"이라 비판), 앙상블·라우터(Tabi·Tryage·MasRouter — "LLM을 관계 없는 교환 가능 단위로 취급"), 그리고 가장 가까운 선행인 그래프 기반 다중 에이전트다. MacNet·GPTSwarm은 정적 DAG로 에이전트를 노드화하고, DyLAN은 forward-backward 동료 평가로 계산한 Agent Importance Score로 동적 활성화를 한다. GoA는 과제 관련도로 동적 그래프를 짓고 이종 특화 LLM 간 1대1 통신을 한다고 자리매김한다. 성격은 **그래프 추상을 입은 test-time 다중 에이전트 오케스트레이션 프레임워크**(ICLR 2026)다.

## 2. 방법: GoA 파이프라인

원논문 §3에 해당한다.

![Figure 2: GoA 파이프라인](/api/blog/figures/goa-fig2-pipeline.png)

*그림 2 — 원논문 Figure 2: GoA 전체 파이프라인. (a) 여러 도메인 질의 $\mathcal{Q}$를 그래프 관점으로 다뤄 답 $\mathcal{A}$ 생성. (b) 노드 샘플링: 각 에이전트를 도메인·과제 정보의 모델 카드에 매핑, 메타-LLM이 $\mathcal{Q}$와 카드로 관련 에이전트 선택. (c) 엣지 샘플링: 초기 응답을 모아 서로 평가해 정규화 점수 행렬 생성, source→target·target→source 방향으로 엣지, 저관련 노드는 τ=0.05로 가지치기. (d) 메시지 전달: source→target 후 역방향. (e) 그래프 풀링: max 또는 mean.*

**노드 샘플링(§3.2.1).** 질의 $\mathcal{Q}$에 대해 메타-LLM(범용 LLM, 여기선 Qwen2.5-7B-Instruct)이 모델 카드로 top-k 관련 에이전트를 뽑는다(식 1). 모델 카드는 HuggingFace README를 도메인·특화 과제·크기 세 항목으로 요약한 것이다. 생의학 질의에 법률 모델 같은 무관 에이전트를 걸러 "에이전트 폭발"을 막는다.

**엣지 샘플링(§3.2.2).** 뽑힌 에이전트가 각자 초기 응답을 낸 뒤, 서로의 응답을 평가한다(자기 것은 제외, 점수 합 1.0). 에이전트 $j$의 관련도 점수는 받은 점수의 합 $\mathcal{S}_j=\sum_{i\neq j}\text{Score}_{i\to j}$(식 2)다. $\mathcal{S}_j<\tau$($\tau{=}0.05$)면 가지치기한다. 가중 방향 인접행렬은 $\mathbf{A}_{ji}=\mathcal{S}_i/\sum_{k\in\mathcal{N}_j}\mathcal{S}_k$(식 3)로, 관련도 높은 에이전트가 비례해 더 큰 영향력을 갖게 한다.

**메시지 전달(§3.2.3).** 두 단계다. **source→target**(식 4): 상위 노드가 하위 노드로 정보를 전파해 하위가 응답을 정제한다. **target→source**(식 5): 정제된 하위 응답을 상위로 되보내 상위가 이웃의 개선을 반영해 다시 정제한다. 여기서 유의할 점은 이 "메시지 전달"이 학습된 GNN 연산이 아니라 **이웃의 텍스트 응답을 새 프롬프트에 넣어 LLM을 다시 부르는 것**이라는 점이다(부록 B의 프롬프트가 "다른 모델들의 응답을 고려해 답을 정제하라"는 자연어 요청이다). 인접행렬 가중치도 최종적으로는 high($w{>}0.7$)/moderate/low($w{\le}0.4$) 세 등급의 언어 라벨로 프롬프트에 박힌다.

**그래프 풀링(§3.2.4).** 정제된 응답을 하나로 모은다(식 6). **GoA_Max**는 들어오는 엣지가 가장 많은(가장 관련도 높은) source 노드의 응답을 그대로 쓰고, **GoA_Mean**은 메타-LLM이 모든 선택 에이전트의 응답을 관련도로 가중 평균한다(추가 메타-LLM 호출 필요). 두 변형을 실험에서 비교한다.

**GoA는 MoA를 일반화한다(§3.3).** MoA의 갱신은 $\mathcal{R}'_i=v_i(\|_{j=1}^{N}\mathcal{R}_j+\mathcal{Q})$(식 7)다. **Proposition 1**: GoA는 노드 샘플링 $k$가 전체 에이전트 수 $N$과 같고, 인접행렬이 완전 연결에 모든 가중치가 1이며, 각 층에 질의 $\mathcal{Q}$의 자기 루프가 있고, mean 풀링으로 집계할 때 MoA로 환원된다. 다만 이는 GoA의 구별 요소를 하나씩 끄면(모든 에이전트 유지·인접행렬 평탄화·자기 루프 복원·mean 강제) 식 4가 식 7이 되는 정의적 관찰이지, 표현력·최적성·성능 한계에 대한 정리는 아니다(논문 외 해석).

## 3. 실험

원논문 §4에 해당한다.

**설정(§4.1).** 다중 도메인(MMLU·MMLU-Pro·GPQA) + 도메인 특화(MATH·HumanEval·MedMCQA) 6벤치마크. 에이전트 풀은 7–8B LLM 6개: General(Qwen2.5-7B)·Code(Qwen2.5-Coder-7B)·Math(Mathstral-7B)·Biomedical(Bio-Medical-Llama-3-8B)·Finance(finance-Llama3-8B)·Legal(Saul-7B). 메타-LLM은 Qwen2.5-7B. 층화 표집(MMLU 범주당 50×57, MMLU-Pro 150×14). 모두 zero-shot CoT, GoA top-k=3.

**주요 결과(§4.2, Table 1).** 과제 난도에 따른 교차가 이야기의 핵심이다. GoA(3개)가 6벤치마크 중 **다섯에서 최고**다. GoA_Max가 MMLU 79.18·MMLU-Pro 54.78·MedMCQA 60.04, GoA_Mean이 GPQA 40.54·MATH 73.12에서 앞선다. 단일 에이전트 중엔 General이 가장 낫고, 6개짜리 다중 에이전트 중엔 Refine·Self-MoA가 강한데, GoA가 이들을 대체로 넘는다. 다만 두 단서가 붙는다. MMLU-Pro 승리는 GoA_Max 54.78 대 Refine 54.71로 **+0.07의 초박빙**이다. 그리고 **HumanEval에서는 Code 단일 에이전트(85.37)가 GoA(GoA_Mean 84.98·GoA_Max 84.67)를 이긴다**. 곧 GoA가 6벤치마크 전부를 이기는 게 아니라 다섯을 이기고, 강한 도메인 특화 모델이 있는 코드 과제에서는 그 전문가 하나가 다중 에이전트를 앞선다(논문 외 비판; 논문의 "HumanEval 최고 84.98"은 다중 에이전트 비교 안에서만 참이다).

**효율(§4.2, Table 2).** MMLU-Pro에서 MoA는 정확도 53.33·LLM 호출 19회·토큰 56.05k·시간 240.26초인데, GoA_Max는 54.78·11회·19.18k·100.43초다. 곧 GoA가 **더 정확하면서 호출 약 2배·토큰 약 3배·시간 약 2배 적다**. 논문의 가장 견고한 결과이고, 주장이 아니라 측정이다.

**규모 확장(§4.3, Table 3).** gpt-4o로 GPQA·MedMCQA(100표본)·HumanEval을 시험한다. 여기서 두 가지가 표제와 어긋난다(논문 외 비판). 첫째, **GoA_Max(6개)가 GoA_Max(3개)를 세 벤치마크 모두에서 앞선다**(GPQA 56.57 vs 55.05, MedMCQA 83.00 vs 82.00, HumanEval 93.90 vs 93.29). 곧 GoA도 에이전트가 많으면 더 좋아진다. "3개면 충분"은 효율적 작동점이지 작은 풀이 본질적으로 낫다는 증거가 아니다. 둘째, **DyLAN(8개)이 GPQA에서 58.89로 GoA_Max(3개) 55.05와 GoA_Max(6개) 56.57을 모두 이긴다.** "3개가 DyLAN의 8개를 이긴다"는 MedMCQA·HumanEval에서만 성립하고 가장 어려운 추론 벤치마크 GPQA에서는 성립하지 않는다.

**왜 그래프인가(§4.3).** Fig 3의 해부학(MMLU) 사례가 그래프의 이점을 예시한다. MoA는 수학·코드 같은 무관 도메인 에이전트까지 써서 잡음(예: 'Answer: 1')을 끼워 최종 예측을 해치는 반면, GoA는 노드 샘플링으로 무관 에이전트를 피해 관련 에이전트 간 표적 메시지 전달로 더 정확한 답('Answer: 0')에 이른다. 관련도 인식 메시지 전달(§4.3, Table 4)은 코드 3모델 고정 세팅(HumanEval)에서 GoA_Max 85.98로 최고인데, 최고 단일(Qwen2.5-Coder 85.37) 대비 +0.61, MoA(85.37)는 이득이 없고 Debate(71.95)는 오히려 해친다.

**절제(§4.4, Table 5).** MMLU-Pro/GPQA에서 메시지 전달 방향을 뒤집으면 가장 크게 떨어진다(−2.60/−5.05). source→target 제거(−2.57/−3.86), target→source 제거(−1.12/−1.95), 엣지 점수 비활성화($A_{ij}{=}1$, −1.87/−2.64). 양방향 흐름과 관련도 가중이 다 기여함을 확인한다. top-k는 2면 다양성이 부족, 5는 3과 거의 같고(54.65 vs 54.78) 약간 낮으며, τ=0.05가 균형이다(0.1·0.2는 너무 성겨 해로움).

## 4. 주의해서 읽을 점

잘 설계된 오케스트레이션 논문이다. 지속 가치의 대부분은 학습 없이 채택 가능한 실용성과, 측정된 효율 이득에 있다. 아래 비판은 대개 프레이밍과 통계에 관한 것이며 엔지니어링에 관한 것이 아니다.

### 4.1 은유와 메커니즘: "그래프"는 학습된 연산이 아니다

논문은 이득을 "그래프 구조와 새 메시지 전달"에 반복해 귀속한다(초록·§4.3). 그러나 모든 그래프 용어 밑의 메커니즘은 블랙박스 API 호출 위의 프롬프트 오케스트레이션이다(논문 외 비판). "메시지 전달"(식 4·5)은 각 LLM을 이웃의 **텍스트** 응답과 함께 다시 부르는 것이고, "가중 인접행렬"(식 3)은 특징 벡터를 곱하는 데 쓰이지 않는다. 그 유일한 실현(부록 B)은 이웃을 high/moderate/low 세 언어 등급으로 나눠 프롬프트에 붙이는 것뿐이라, 연속 가중치가 모델에 닿기 전에 세 형용사로 붕괴한다. 학습되는 것이 없다. 그래프는 질의마다 LLM 호출로 새로 짓고 버려진다. 그래프 프레임은 **조직 어휘**로는 진짜 유용하다(노드/엣지/방향/풀링이 실제 단계에 깔끔히 대응하고, MoA를 완전 그래프로 보는 관점도 정당하다). 하지만 "이 이득은 그래프 기반 추론에서 온다"(§4.2)는 인과 언어는 표기 선택을 과대 평가한다. 실제로 결과를 이끄는 것은 (a) 더 적고 관련된 에이전트 선택과 (b) LLM이 판정한 관련도 순서로 재프롬프트를 배열하는 것이고, 둘 다 그래프 없이 서술할 수 있다.

### 4.2 "3이 6/8을 이긴다"는 좁다

표제는 실재하나 광고보다 좁다(논문 외 비판). 첫째, **승리의 상당 부분은 잡음 여과이지 메시지 전달이 아니다.** Fig 3의 해부학 사례가 명시하듯 MoA의 손해는 무관 에이전트의 나쁜 표('Answer: 1')이고, GoA의 노드 샘플링이 그것을 제거한다—이는 **선택** 단계의 효과로 방향 메시지 전달과 별개다. 절제(Table 5)가 메시지 전달도 중요함을 보이지만, 절제는 모두 그래프 기계 **안에서** 이뤄져 "top-3 에이전트 + 단순 연결(방향 전달 없음)" 대 완전한 GoA를 주요 벤치마크에서 직접 비교하지 않는다. 곧 순수 선택+집계 위에 그래프가 더하는 한계 가치가 깨끗이 측정되지 않는다. 둘째, **"적을수록 낫다"는 절대적이지 않다.** Table 3에서 GoA_Max(6)가 GoA_Max(3)을 세 벤치마크 모두 앞선다. 셋째, **"3이 DyLAN의 8을 이긴다"는 GPQA에서 실패한다**(DyLAN 58.89 vs GoA 55.05). 넷째, **단일 전문가가 GoA를 이길 수 있다**(HumanEval Code 85.37 vs GoA 84.98). 강한 특화 모델이 있는 곳에서 다중 에이전트 협업이 사는 값은 작다.

### 4.3 통계적 엄밀성: 얇은 마진·분산 없음·부분표본

정확도 우위 주장은 무른 근거에 기댄다(논문 외 비판). 승부가 초박빙인 곳이 있다(MMLU-Pro GoA_Max 54.78 vs Refine 54.71 = +0.07, 2,100문항 층화 부분집합에서 사실상 동전던지기). 그리고 어느 표에도 분산·표준편차·신뢰구간·유의성 검정이 없다—전부 점추정이고 단일 실행으로 보인다. 그래서 τ=0.05 최적점이나 "k=3이 확장적·성능적"이라는 결론(§4.4)이 실행 간 잡음일 가능성을 배제하지 못한다. 게다가 전체가 아닌 부분표본이고(MMLU 50/범주, MMLU-Pro 150/범주), gpt-4o 규모 시험은 MedMCQA를 100표본으로 줄였다. 작은 $n$ 탓에 ±0.07–1.0의 마진이 취약하다. 효율 결과(Table 2, 2–3배 격차)는 오차막대가 필요 없을 만큼 견고하지만, **정확도 우위**는 이 논문의 가장 약한 방법론 고리다.

### 4.4 Proposition 1과 의존성

Proposition 1(GoA가 MoA를 일반화)은 옳지만 정의적이다(논문 외 해석). GoA의 구별 요소를 모두 꺼서 식 4가 식 7이 되게 한 매개변수 치환 관찰이지, 표현력·최적성·성능 한계에 대한 정리가 아니다. "일반화한다"는 표현을 정직하게 벌지만 이론적 기여로 읽어선 안 된다. 의존성도 짚어 둘 만하다. 노드 샘플링(식 1)과 mean 풀링(식 6)이 모두 하나의 7B 메타-LLM(Qwen2.5-7B)을 거치고, 그것이 HuggingFace README 요약(모델 카드)을 읽어 질의에 맞춘다. 메타데이터 품질은 모델마다 다르고, 잘못된 선택엔 τ 말고 하류 복구가 없다—측정되지 않은 단일 실패 지점이다. τ 자체가 "모델 카드에 상세 정보가 없을 수 있는 경우"를 위한 보정 하이퍼파라미터라고 저자가 밝히고(저자 자인), Table 5는 τ에 민감함을 보인다(0.1→−1.66/−1.55, 0.2→−2.00/−2.86). 그리고 부록 B의 신뢰도 필터는 유효 JSON을 못 내는 에이전트를 "범용 도메인 모델로 대체"하는데, 그 범용 모델이 이미 가장 강한 단일 에이전트이자 메타-LLM 기반이라 풀 구성이 조용히 일반 모델 쪽으로 쏠릴 수 있다.

### 4.5 제값을 하는 부분

공정하게 무게를 달면 강점이 분명하다. 세 질문 분해(어떤 에이전트/어떻게 통신/어떻게 통합)가 노드 샘플링/엣지+메시지 전달/풀링에 깔끔히 대응해 읽기 좋다. **노드 샘플링**(관련도 기반 선택으로 에이전트 폭발 방지)은 독립적 가치가 가장 뚜렷한 부품이고, Fig 3의 잡음 여과 직관이 구체적이고 설득력 있다. **효율은 진짜이고 측정됐다**(Table 2, 2–3배 적은 호출·토큰·시간에 더 높은 정확도—드문 파레토 개선). **절제가 성실**해서 양방향 흐름(역방향=최악)과 엣지 점수의 값을 검증한다. **Test-time·프롬프트 전용**이라 학습이 필요한 방법(MacNet/GPTSwarm류) 대비 배포 이점이 있고, MoA 일반화 프레이밍도 정직하다.

## 5. 결론

GoA는 견고하고 잘 설계된 오케스트레이션 논문이다. 핵심 동작—관련 에이전트 몇을 뽑아 동료 판정 관련도로 순서 짓고 양방향으로 재프롬프트한 뒤 풀링—은 합리적이고, 2–3배 낮은 비용에 대등하거나 더 나은 정확도라는 **측정된 진짜 효율 이득**(Table 2)을 낸다. 그 효율 결과만으로도 논문은 값을 한다.

약점은 엔지니어링이 아니라 프레이밍과 통계에 있다. 첫째, "그래프"는 프롬프트 오케스트레이션 위의 우아한 **어휘**다. 학습되는 그래프가 없고, "메시지 전달"은 텍스트로 재프롬프트하는 것이며, 인접 가중치는 모델에 닿기 전 세 언어 등급으로 붕괴한다—"그래프 구조"에 인과를 돌리는 것은 표기 선택을 과대 평가한다. 둘째, "3이 6/8을 이긴다"는 실재하나 좁다. GoA_Max(6)가 GoA_Max(3)을 세 벤치마크 모두 앞서고, DyLAN(8)이 GPQA에서 GoA를 이기며, Code 단일이 HumanEval에서 GoA를 이긴다—그리고 이득의 상당 부분은 절제가 깨끗이 분리하지 못한 **잡음 여과**다. 셋째, 정확도 우위는 초박빙 마진(MMLU-Pro +0.07)·부분표본·분산 부재에 기댄다. 넷째, Proposition 1은 옳지만 동어반복적 위치 선정 장치다. 다섯째, 전체 관련도가 README를 읽는 하나의 7B 메타-LLM에 걸린 미측정 단일 실패 지점이다. 가장 방어 가능한 재진술은 이렇다. **GoA는 관련도 기반 선택으로 더 싼 다중 에이전트 추론을 보인다.** "그래프 패러다임"과 "3이 6/8을 이긴다"는 서사는 우월성의 증명이 아니라 유리한 작동점을 가진 효과적 휴리스틱으로 읽는 편이 정확하다.

읽는 법을 정리하면:

| 목적 | 어디를 읽나 |
|---|---|
| 문제 설정과 세 도전 | §1과 Figure 1, 이 글 1장 |
| 파이프라인 4단계 | §3.2와 Figure 2, 이 글 2장 |
| 성능 주장의 실제 구조(교차·5/6) | Table 1, 이 글 3·4.2절 |
| 진짜 이득이 어디인가(효율) | Table 2, 이 글 3장 |
| "그래프"가 실제로 무엇인가 | 부록 B 프롬프트, 이 글 4.1절 |

## References

Besta, M., Blach, N., Kubicek, A., Gerstenberger, R., Podstawski, M., Gianinazzi, L., … Hoefler, T. (2024). Graph of thoughts: Solving elaborate problems with large language models. *Proceedings of the AAAI Conference on Artificial Intelligence, 38*(16), 17682–17690. https://arxiv.org/abs/2308.09687

Chen, M., Tworek, J., Jun, H., Yuan, Q., Pinto, H. P. de O., Kaplan, J., … Zaremba, W. (2021). *Evaluating large language models trained on code* (arXiv:2107.03374). arXiv. https://arxiv.org/abs/2107.03374

Du, Y., Li, S., Torralba, A., Tenenbaum, J. B., & Mordatch, I. (2023). *Improving factuality and reasoning in language models through multiagent debate* (arXiv:2305.14325). arXiv. https://arxiv.org/abs/2305.14325

Hendrycks, D., Burns, C., Basart, S., Zou, A., Mazeika, M., Song, D., & Steinhardt, J. (2021). Measuring massive multitask language understanding. *International Conference on Learning Representations*. https://arxiv.org/abs/2009.03300

Li, W., & others. (2025). *Rethinking Mixture-of-Agents: Is mixing different large language models beneficial?* (arXiv:2502.00674). arXiv. https://arxiv.org/abs/2502.00674

Liu, Z., Zhang, Y., Li, P., Liu, Y., & Yang, D. (2024). A dynamic LLM-powered agent network for task-oriented agent collaboration. *Conference on Language Modeling (COLM 2024)*. https://arxiv.org/abs/2310.02170

Madaan, A., Tandon, N., Gupta, P., Hallinan, S., Gao, L., Wiegreffe, S., … Clark, P. (2023). Self-Refine: Iterative refinement with self-feedback. *Advances in Neural Information Processing Systems, 36*. https://arxiv.org/abs/2303.17651

Qian, C., Xie, Z., Wang, Y., Liu, W., Dang, Y., Du, Z., … Sun, M. (2024). *Scaling large language model-based multi-agent collaboration* (arXiv:2406.07155). arXiv. https://arxiv.org/abs/2406.07155

Rein, D., Hou, B. L., Stickland, A. C., Petty, J., Pang, R. Y., Dirani, J., … Bowman, S. R. (2024). GPQA: A graduate-level Google-proof Q&A benchmark. *Conference on Language Modeling (COLM 2024)*. https://arxiv.org/abs/2311.12022

Shazeer, N., Mirhoseini, A., Maziarz, K., Davis, A., Le, Q., Hinton, G., & Dean, J. (2017). Outrageously large neural networks: The sparsely-gated mixture-of-experts layer. *International Conference on Learning Representations*. https://arxiv.org/abs/1701.06538

Wang, J., Wang, J., Athiwaratkun, B., Zhang, C., & Zou, J. (2024). *Mixture-of-Agents enhances large language model capabilities* (arXiv:2406.04692). arXiv. https://arxiv.org/abs/2406.04692

Wang, X., Wei, J., Schuurmans, D., Le, Q., Chi, E., Narang, S., … Zhou, D. (2023). Self-consistency improves chain of thought reasoning in language models. *International Conference on Learning Representations*. https://arxiv.org/abs/2203.11171

Wang, Y., Ma, X., Zhang, G., Ni, Y., Chandra, A., Guo, S., … Chen, W. (2024). MMLU-Pro: A more robust and challenging multi-task language understanding benchmark. *Advances in Neural Information Processing Systems, 37*. https://arxiv.org/abs/2406.01574

Wei, J., Wang, X., Schuurmans, D., Bosma, M., Ichter, B., Xia, F., … Zhou, D. (2022). Chain-of-thought prompting elicits reasoning in large language models. *Advances in Neural Information Processing Systems, 35*, 24824–24837. https://arxiv.org/abs/2201.11903

Yao, S., Yu, D., Zhao, J., Shafran, I., Griffiths, T. L., Cao, Y., & Narasimhan, K. (2023). Tree of Thoughts: Deliberate problem solving with large language models. *Advances in Neural Information Processing Systems, 36*. https://arxiv.org/abs/2305.10601

Yun, S., Peng, J., Li, P., Fan, W., Chen, J., Zou, J., Li, G., & Chen, T. (2026). *Graph-of-Agents: A graph-based framework for multi-agent LLM collaboration*. International Conference on Learning Representations. https://arxiv.org/abs/2604.17148

Zhuge, M., Wang, W., Kirsch, L., Faccio, F., Khizbullin, D., & Schmidhuber, J. (2024). *GPTSwarm: Language agents as optimizable graphs* (arXiv:2402.16823). arXiv. https://arxiv.org/abs/2402.16823
