# Position: LLM-Based Social Simulations Require a Boundary

**Paper:** Wu, Zengqing; Peng, Run; Ito, Takayuki; Onizuka, Makoto; Xiao, Chuan. (2025). "Position: LLM-Based Social Simulations Require a Boundary." arXiv:2506.19806v3. University of Osaka·University of Michigan·Kyoto University·Nagoya University (ICML 포지션 트랙 형식의 프리프린트 — 게재 확정 문구 없음)

**Abstract:** 본 문서는 "LLM 사회시뮬레이션이 사회과학에 기여하려면 명확한 경계가 필요하다"는 포지션 페이퍼를 해설한다. 논문의 진단은 하나의 개념으로 압축된다. LLM 에이전트는 "average persona"로 수렴한다 — 모집단의 전형적 행동은 재현하지만 실제 인간 모집단의 변이는 억압한다. 이 진단을 분산(행동의 산포)과 평균(중심경향의 정렬)의 2축으로 분해하고, 시뮬레이션 연구 21편의 검증 관행을 코딩한 표(Table 1)로 뒷받침한다. 분산을 점검한 연구는 절반이 안 되고, 점검한 연구의 다수가 인간보다 낮은 분산을 보고했으며, 분산 수준에서 인간 기준선과의 일치를 주장한 연구는 한 편도 없다. 처방은 세 항이다: 검증 깊이를 연구 질문의 이질성 요구에 맞추고, 평균 정렬과 함께 분산을 명시적으로 보고하고, 분산이 모자라면 주장을 집합 수준의 정성 패턴으로 제한하라. 판별 도구로는 "모든 에이전트를 모집단 평균으로 대체해도 내 연구 질문에 답할 수 있는가"라는 휴리스틱을 준다. 읽을 때 주의할 점은 판본이다. 초판(v1, 4저자)의 3대 경계 문제 구조가 v3(5저자)에서 alignment 단일 축으로 재편되면서 체계적 리뷰·반대 입장 절·부록 전부가 새로 들어왔다. 위키 관점에서 이 논문은 정렬 역설 트랙의 판정론(무엇이 얼마나 어긋났는지 재는 좌표계)이고, PAPG류 입력 교정 처방의 성패를 심사하는 평가 프로토콜로 읽힌다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 논문 유형·질문 | 포지션 페이퍼. 실험 논문이 아니다. 질문: 현재 LLM 능력에서 사회시뮬레이션이 신뢰할 수 있게 뒷받침하는 연구 주장의 한계(경계)는 어디인가? |
| 핵심 주장 | LLM 에이전트는 average persona로 수렴해 행동 이질성이 부족하고, 이는 설계 교정으로 해소되지 않는 boundary problem이다(논문의 usage/boundary 구분). 따라서 검증 요구수준과 주장 수준의 경계를 세워야 한다(§1, §4). |
| 증거 | (a) 21편 체계적 리뷰(Table 1): ground truth(GT, 인간 기준선) 비교 14/21, 분산 점검 9/21, 점검한 9편 중 7편이 인간보다 낮은 분산, 분산 일치 주장 0편. (b) 설계요인 교차 분석(Appendix C): 페르소나·모델·온도(0.0–1.2)·규모(2~약 100만) 어느 요인도 저분산을 일관되게 설명하지 못함. (c) 자기 선행 연구의 2/3 추측 게임에서 각색 수록한 그림 1장(Figure 2). 신규 실험은 없다. |
| 처방 | 권고 3항(검증 깊이 매칭 / 분산 명시 보고 / 집합-정성 수준으로 주장 제한) + 판별 휴리스틱(Appendix E) + 향후 권고 5항(Appendix F, 모순 감사 포함). |
| 핵심 한계 | "systematic review"라 부르지만 선정 프로토콜이 없는 편의 표본(자기 논문 포함), 경험 근거가 GPT-3.5/4 세대에 묶임(논문 스스로 시효를 인정), "충분한 이질성"의 정량 역치 부재, 내재적 한계 주장과 Appendix G의 개선 방향 목록 사이의 충돌. |

## 목차

1. 서론
2. 주장의 구조: average persona와 두 개의 사례
3. 증거: 21편 리뷰, 모순 사례, 각색 수록 그림
4. 논문의 권고와 판별 휴리스틱
5. 반대 입장의 처리 (§6 Alternative Views)
6. 주의해서 읽을 점
7. 방법적 한계와 확장
8. 결론

---

## 1. 서론

### 1.1 연구 배경

사회시뮬레이션의 정통 도구는 ABM(Agent-Based Modeling, 행위자 기반 모형)이다. 단순한 미시 규칙에서 거시 패턴이 창발하는 과정을 보여주고(Epstein, 1999; Schelling, 1971), 에이전트 간 이질성을 지원하며, 미시-거시를 잇는 해석 가능한 메커니즘을 준다. 대신 규칙을 손으로 단순화해야 하고 주관적·인간다운 행동의 표현이 어렵다(§1, Appendix A.2). LLM 에이전트는 바로 그 빈자리를 채우겠다고 약속했다. 자연어 이해, 유연한 행동, 인간다운 추론이 그것이다(§1). 이 교환에서 무엇을 잃는지가 이 논문의 주제다.

논문이 먼저 정리하는 것은 시뮬레이션의 목적이다. 사회시뮬레이션의 1차 목적은 현실의 정밀 복제나 예측이 아니라 "사회 패턴 설명, 이론 구성, 가설 생성"이다(§2.1). 복제 지향은 알려진 패턴의 반복일 뿐 새 메커니즘을 드러내지 못하고 파라미터가 늘수록 과적합과 검증성 저하를 부른다는 이유로, 예측 지향은 회고 검증의 시나리오가 훈련 코퍼스에 들어 있다는 데이터 누출을 이유로 각각 기각된다(§2.1). Schelling 분리 모형이 반복 소환되는 이유가 여기 있다. 특정 도시를 복제하지 않고도 분리의 보편 메커니즘을 드러내는 것, 그것이 시뮬레이션의 모범이라는 입장이다(§2.1).

그 위에서 도전과제를 둘로 가른다(§2.2). **usage problems**는 프롬프트 설계 결함처럼 더 나은 관행으로 교정 가능한 문제, **boundary problems**는 LLM 본성에서 오는 내재적 한계다. 이 논문은 후자만 다루고, v3 본문은 그중에서도 정렬(alignment) 문제 하나에 집중한다. "boundary"라는 말 자체도 정의되어 있다. 결정 경계나 안전 가드레일이 아니라 "현재 LLM 능력, 특히 행동적으로 다양한 에이전트 집단을 생성하는 능력을 전제로, 신뢰할 수 있게 뒷받침되는 연구 주장의 한계"라는 **방법론적 적용범위 조건**(methodological scope conditions)이다(§1).

### 1.2 판본: v1의 3대 경계에서 v3의 단일 축으로

이 논문은 판본 간 변화가 커서 인용 시 주의가 필요하다. v1(2025-06, 저자 4인: Wu·Peng·Ito·Xiao)은 alignment / consistency(장기 역할 일관성) / robustness(섭동 하 재현성)의 3대 경계 문제를 본문 대칭 구조로 다뤘다. v3(2026-07-12, Onizuka 추가로 5인, ICML 포지션 트랙 양식)에서 consistency와 robustness는 Appendix B로 이동하고(상호작용 구조·환경 설계 2항이 추가돼 B는 네 개의 보조 경계를 다룬다), v1 §7.2의 과제 4항은 Appendix H로 옮겨졌으며, 본문은 alignment·이질성 단일 축으로 재편됐다. 21편 체계적 리뷰(§5의 Table 1과 Appendix C의 Table 2), 반대 입장 절(§6), 판별 휴리스틱과 권고(Appendix E–F)는 전부 v3 신설이다. 기여 주장도 3개에서 4개로 늘었다(§1). 이 글의 절 번호는 모두 v3 기준이다. 통용 인용 표기는 v1 시점의 "Wu et al. 2025"다.

### 1.3 용어

이 논문의 "alignment"는 시뮬레이션된 행동·집합 동학이 실제 사회 패턴과 일치하는가를 뜻한다(§2.2). RLHF(인간 피드백 강화학습) 정렬이 아니다. 오히려 §4.2는 인간 피드백으로 훈련된 모델일수록 여론 시뮬에서 평균이 이탈한다는 연구들을 인용하므로, 두 용법은 서로 엇갈린다(PAPG 리뷰에서 짚은 것과 같은 용어 주의가 여기도 적용된다). 정렬은 두 수준으로 나뉜다: 개인 수준(각 에이전트가 인간다운가)과 집합 수준(상호작용이 현실적 사회동학을 재현하는가)(§3). 구분이 하나 더 있다. 개인 정렬은 **이질성**(에이전트들이 서로 다른가)과 다르며, 논문이 문제 삼는 것은 input heterogeneity(부여된 페르소나의 다양성)가 아니라 **output heterogeneity**(실제 산출된 행동의 다양성)다. "다양한 페르소나를 설정해도 다양한 행동 산출이 보장되지 않기 때문"이다(§3.1). "충분한" 이질성의 기준은 실제 인간 모집단에서 관찰되는 행동 분포와의 비교 가능성이다(§3.3).

## 2. 주장의 구조: average persona와 두 개의 사례

### 논증의 뼈대

전체 논증은 네 단계로 이어진다(논문 외 재구성). (i) 시뮬레이션의 목적은 패턴 설명·가설 생성이다(§2.1). (ii) 복잡한 사회 패턴의 창발은 에이전트 이질성에 의존한다. 동질 에이전트의 집합 행동은 voter model(전원이 같은 모방 규칙을 따르는 여론 모형)처럼 해석적으로 풀 수 있는 균형으로 수렴하므로, 그런 경우 시뮬레이션의 부가가치가 의문시된다(§3.2; 단 이질성 요구가 낮은 질문은 예외다 — 4장의 휴리스틱). (iii) LLM은 average persona로 수렴해 산출 이질성이 부족하고, 이는 설계 선택으로 해소되지 않는 boundary problem이다(§4, Appendix C). (iv) 따라서 신뢰 가능한 주장은 "평균 정렬 + 저분산" 조건에서의 집합-정성 패턴으로 제한되어야 한다(§4.2, Figure 1).

![Boundary Figure 1: overview of claims](/api/blog/figures/boundary-fig1-claims.png)

*그림 1 — 원논문 Figure 1: 주장 전체의 개요도. 복제 지향("Expected" Results)은 기각(빨간 X). 시뮬레이션이 실제로 낳는 두 경우 중 평균 정렬+저분산(Case #1)만 조건부 사용 가능하고, 평균 이탈+저분산(Case #2)은 기각. 허용되는 분석은 ① 집합 패턴의 정성 분석뿐이며(초록 체크), ② 집합 패턴의 정량 주장("80% 정확도 달성")과 ③ 개별 행동 해석("이 에이전트는 망설이고 있다")은 경계 밖(빨간 X).*

### average persona: 정의와 기원

정의: LLM 에이전트는 "모집단-전형적 행동을 반영하는 응답을 생성하면서 실제 인간 모집단에서 관찰되는 변이는 억압한다"(§4.1). 기원 주장: 우도 기반 훈련이 고빈도·주류 표현을 보상하고 주변부 표현을 억압하기 때문이다(§4.1). 그 결과 하위집단 이질성이 소거되고, 대안적 관점을 유도하는 지시가 있어도 행동이 사회적 편향과 인구학적 고정관념을 반영하곤 하는 지배적 패턴에 집중되며, 롱테일 패턴을 놓친다(§4.1).

이 현상의 영향은 **분산**(행동의 다양성과 산포)과 **평균**(중심경향과 인간 행동의 정렬)의 2축으로 분해된다(§4.1). 고/저 판정 기준은 해당 현상에 대해 경험적으로 관측된 인간 행동 분포, 즉 ground truth와의 비교다(§4.1). 이 분해가 논문 전체의 좌표계다.

### 두 개의 사례

- **Case 1: 분산 낮음, 평균 정렬**(§4.2): 경제 시장 시뮬은 거시 패턴을 재현하지만 개별 에이전트의 행동 분산이 인간 참가자보다 유의하게 낮고, 대피 시뮬에서는 페르소나별 집단 차이에도 불구하고 개별 궤적이 서로 매우 유사하다(§4.2가 인용하는 연구들). 이 경우 집합-정성 통찰은 가치가 있지만, 정량 집합 주장과 개별 행동 해석은 신뢰할 수 없다. 후자를 논문은 "interpretive overfitting"이라 부른다(§4.2).
- **Case 2: 분산 낮음, 평균 이탈**(§4.2): 인간 피드백으로 훈련된 모델은 여론조사 시뮬에서 진보 성향과 더 양극화된 태도로 기울고 역할극으로 탈편향이 어렵다(Santurkar et al., 2023 등). 다국어 시뮬레이션에서는 해당 언어 공동체의 문화 가치와 불일치하는 도덕 판단을 내린다(§4.2; 인용된 연구는 다국어 트롤리 문제다). 이 경우 시뮬레이션의 발견은 실제 인간 사회에 적용할 수 없다. 정렬을 이루려면 광범위한 사회인구학적 조건화가 필요하다는 근거로 Argyle et al. (2023)과 나란히 PAPG(Hu et al., 2025)가 인용된다(§4.2). 7장에서 다시 본다.

주장하지 않는 것도 명확하다. LLM 시뮬 기각론이 아니고("문제는 근본적 무효성이 아니라 조건부 타당성", §6), how-to 가이드가 아니며(§1), "LLM 사용이 좋은 연구 프로토콜인가"는 중심 질문이 아닐 수 있다면서 질문을 "LLM이 의미 있게 기여할 수 있는 문제 유형의 경계 긋기"로 바꾼다(§1; "ABM 대체 가능성" 질문의 재구성이라는 표현 자체는 v1 §1의 기여문이다).

## 3. 증거: 21편 리뷰, 모순 사례, 각색 수록 그림

이 논문에 신규 실험은 없다. 증거는 세 종류다: 21편 체계적 리뷰(Table 1–2), 문헌에서 추린 모순 사례 분석(§5.2), 그리고 자기 선행 연구에서 각색해 실은 그림 1장(Figure 2).

### 21편 검증 관행 리뷰 (Table 1, §5)

대상은 2023–2025년 "톱 AI/NLP 학회 게재 또는 고인용" 논문 21편이다(§5). 이질성 요구(연구 질문 유형 기준 High 9 / Med 7 / Low 5), ground truth 유형과 규모, 평균·분산 점검 여부, 주장 수준, 민감도 분석의 5차원으로 코딩했다(기준은 Appendix D).

![Boundary Table 1: systematic review of validation practices](/api/blog/figures/boundary-tab1-review.png)

*표 1 — 원논문 Table 1: 21편의 검증 관행 코딩. Mean/Var.의 ✓ 뒤 표기는 점검 결과(Align/Dev/Mix, Low=인간보다 낮은 분산).*

본문이 뽑아내는 패턴(§5.1; 수치는 검증 단계에서 전부 표 재집계로 확인했다):

- ground truth 비교는 14/21(67%). 게임이론·경제는 인간 실험 데이터가 축적되어 유리하고, 사회연결망·문화는 기준선이 없어 문헌 정성 비교에 의존한다.
- ground truth가 있는 14편 전부가 평균 정렬을 점검했지만 분산 점검은 9편뿐이고, 그 9편 중 7편이 인간보다 낮은 분산을 보고했다. 분산 수준에서 인간 기준선과의 일치를 명시적으로 주장한 연구는 0편이다(§5.1). 규모와 분산의 관계를 대규모 관찰 데이터 기준으로 보고한 것도 표의 Tang 행 1편뿐이며, 낮은 분산을 본문에 정직하게 시인한 사례들(정치 이슈에서 빠르게 확고한 의견 형성, 인간보다 강한 동조)과 분포 차이를 그림으로 보인 모범 사례를 논문은 따로 짚는다(§5.1).
- 이질성 요구가 High인 9편 중 평균·분산을 모두 ground truth 대비 점검한 것은 4편뿐이다. 시장 동학·여론 양극화처럼 이론적으로 행동 다양성에 의존하는 현상을 ground truth 비교 없이 다룬 논문도 있다(§5.1).
- 주장 수준은 대체로 절제되어 있다: 18/21이 집합-정성 수준으로 제한했고, 집합-정량 주장 3편은 모두 ground truth 비교를 동반한다(§5.1). 다만 과대주장 사례 2건도 실명으로 지적된다: ground truth 비교 없이 "현실적인 모의 주식시장"을 주장한 연구와, 인간 기준선 없이 특정 집단행동 시뮬레이션을 주장한 연구다(§5.1, 표의 Lopez-Lira·Chen 행).
- 민감도 분석은 20/21이 최소 부분 수행(단일 차원만 9/21)(§5.1).

리뷰의 두 번째 층이 Appendix C(Table 2)다. 분산을 점검한 9편에서 낮은 분산이 페르소나 구성(인구학·성격·데이터 기반의 온갖 조합), 모델(GPT-3에서 GPT-4o·Llama까지), 온도(0.0–1.2를 명시적으로 훑은 연구 포함), 상호작용 구조와 규모(2에서 약 100만 에이전트까지)에 걸쳐 나타나고, 어느 설계 요인도 분산 결과를 일관되게 설명하지 못한다는 교차 관찰이다. 그래서 "불충분한 행동 이질성은 특정 설계 결정 탓이 아니라 현재 LLM의 근본 특성"이라는 결론에 이른다. usage/boundary 이분법(§2.2)을 지지하는 이 논문의 핵심 경험 논거다(Appendix C).

### 모순 사례 분석 (§5.2)

같은 현상을 다룬 연구들이 서로 반대 결론을 내는 두 사례를 병치한다. **협력 역설**: 반복 죄수의 딜레마에서 과잉 협력(배신을 30%까지 용서)을 보고한 연구와, 배신 경험 후 영구 배신을 보고한 연구와, 공유자원 게임에서 지속가능한 협력에 실패한다는 연구가 공존한다(표의 Fontana·Akata·Piatti 행). 발산 원인 후보는 게임 구조, 자원 프레이밍, 모델 버전, 프롬프팅이고, 한 연구는 스스로 Llama 3가 "현저히 다르고 더 착취적"이라고 관찰했다. 모델 진화가 기존 행동 특성화를 무효화한다는 것이다(§5.2). **충실도 역설**: Argyle et al. (2023)의 algorithmic fidelity(사회인구 프로파일 조건화로 하위집단별 태도-투표 연관 재현)와, ChatGPT 응답이 집계 평균은 근사하나 ANES(미국 선거 연구 설문)보다 변산이 낮고 회귀 추론이 뒤집히기도 한다는 Bisbee et al. (2024)의 반증이 공존한다. 결론: "한 차원의 검증 성공(평균 정렬)이 다른 차원의 실패(분포 붕괴)를 가릴 수 있다"(§5.2).

### 각색 수록 그림 (Figure 2)

Figure 2는 저자들의 선행 연구(2/3 추측 게임, Keynesian beauty contest)에서 가져와 각색한(adapted) 것이다. GPT-4는 인간의 피크 추측값(33·50·66)을 재현하지만, 비피크 값의 빈도는 인간보다 현저히 낮다(§4.2). 평균은 맞고 분산이 붕괴한 Case 1의 그림 증거다.

![Boundary Figure 2: guessing game distribution](/api/blog/figures/boundary-fig2-guessing.png)

*그림 2 — 원논문 Figure 2(Wu et al., 2024에서 각색 수록): 2/3 추측 게임에서 GPT-4 시뮬레이션(파랑)과 NYT 독자 공모(빨강)의 선택 분포. 시뮬레이션은 33 부근에 빈도 약 0.25의 스파이크, 인간 분포는 최고점이 약 0.05로 낮고 넓다.*

## 4. 논문의 권고와 판별 휴리스틱

처방은 세 층이다.

**권고 3항**(Abstract, §1): (1) 검증 깊이를 연구 질문의 이질성 요구에 맞출 것, (2) 평균 정렬과 함께 분산을 명시적으로 보고할 것, (3) 분산이 불충분할 때는 주장을 집합 수준의 정성 패턴으로 제한할 것.

**판별 휴리스틱**(Appendix E): "모든 에이전트를 모집단 평균으로 대체해도 내 연구 질문에 답할 수 있는가?" 답할 수 있으면 이질성 요구가 낮은 질문이다. 균형 존재, 중심경향, 구조 효과, 강건성 시연(동질 에이전트가 보수적 검정 역할)이 여기 속한다. 답할 수 없으면, 즉 분포 속성(불평등·양극화), 티핑 포인트, 경로의존, 소수자 영향, 하위집단 특이 동학(특히 훈련 데이터에 과소대표된 주변화 집단)에 관한 질문이라면 현재의 LLM 시뮬레이션은 적절하지 않을 수 있다. 이 휴리스틱이 Table 1의 이질성 요구 코딩 기준이기도 하다(Appendix D.1).

**향후 권고 5항**(Appendix F): ① 검증 깊이-질문 매칭, ② 분산 명시 보고와 "허용 가능한" 이탈 역치의 공동체 확립(역치는 아직 없다는 뜻이다), ③ Many Labs·Reproducibility Project 같은 사전등록 다기관 인간 데이터의 벤치마크 활용, ④ ground truth가 어려운 도메인의 공유 벤치마크 개발, ⑤ **모순 감사**(contradiction audit): 자기 결론과 상충 가능한 기존 연구를 능동적으로 찾고, 모순이 확인되면 모델 버전·과제 프레이밍·시간적 불안정성 등 원인을 명시적으로 논하라.

v1의 휴리스틱 경계 3항(집합 vs 개별 / 정렬·이질성 / 시간 일관성)은 이 재편에서 초록 권고 3항과 Appendix E로 흡수됐고, 시간 일관성 축은 Appendix B.1로 물러났다.

## 5. 반대 입장의 처리 (§6 Alternative Views)

v3 신설 절로, 논쟁을 세 진영으로 정리하고 자기 위치를 명시한다.

- **낙관론**: LLM 사회시뮬은 유망한 연구 방법이라는 입장(사실상 이 논문의 맞논문인 Anthis et al., 2025; Grossmann et al., 2023 등). LLM 집단이 자율적으로 사회적 관습을 발전시킨다는 실증도 여기 속한다. 반박은 두 개의 되물음이다. 그 창발한 관습이 실제 사회동학의 반영인가, 훈련 분포에서 물려받은 규칙성인가. 그리고 확장성은 충실도가 유지될 때만 가치가 있는데, 행동 다양성이 제한된 에이전트를 대규모로 돌리는 것이 본질적으로 다양한 모집단의 이해를 진전시키는가(§6).
- **회의론**: LLM이 경제 게임에서 인간 행동 분포 복제에 일관되게 실패한다는 증거, 페르소나 기반 시뮬의 체계적 편향 등을 근거로 한 전면 기각(§6). 반박: 전면 기각은 적절한 조건에서 집합 수준 패턴이 재현된다는 증거(Case 1)를 놓친다. 문제는 근본적 무효성이 아니라 **조건부 타당성**이며, 그 조건이 바로 이 논문이 세우려는 경계다(§6).
- **조건부 관점**: "아직 준비 안 됨", 설계 원칙 위반이 시뮬 실패로 이어진다는 계열(원문은 PIMMUR 원칙으로 인용), 진정한 사회적 행동의 발현에는 사적 소통 채널 같은 특정 시뮬 메커니즘이 필요하다는 관찰(Appendix B.3과 연결), "validation then simulation". 저자들은 스스로를 이 세 번째 진영에 위치시킨다(§6).

논문은 맞논문인 Anthis et al. (2025)를 §4.2에서는 '다양성 부족'의 근거로, Appendix A.3에서는 '인간 근접 성능'의 근거로도 인용한다(논문 외 관찰). 상대 진영 논문을 자기 논거의 부분 증거로 흡수하는 방식이다.

## 6. 주의해서 읽을 점

### 6.1 "systematic review"는 체계적이지 않다

Table 1은 이 논문의 경험적 무게중심이지만, 선정 절차가 "2023–2025년, 톱 AI/NLP 학회 게재 또는 고인용"이 전부다. 검색 데이터베이스·검색어·포함/배제 흐름(PRISMA류, 체계적 문헌고찰의 검색·선별 보고 지침)이 없어 재현 불가능한 편의 표본에 가깝고(논문 외 비판), 고인용 조건은 초기 GPT-3.5/4 화제작을 과대 표집한다. 표본에는 저자 자신의 선행 연구(Wu et al., 2024)도 포함된다. 코딩은 저자들이 직접 했고 복수 코더·신뢰도 검증이 없다. 논문도 "판단이 개입함을 인정한다"(Appendix D.1). 다만 "분산 점검이 드물다"는 기술적 발견 자체는 코딩 프레임과 독립적으로 성립한다(논문 외 해석).

### 6.2 경험 근거는 모델 세대에 묶여 있다

"LLM은 인간보다 분산이 낮다"의 실체는 2023–2025년 GPT-3.5/4 세대의 관찰이다(Table 2의 모델 열). 논문 스스로 이 시효를 §5.2에 적어 두었다. Llama 3가 이전 세대와 현저히 다른 행동을 보이며, "빠르게 진화하는 모델 아키텍처가 기존 행동 특성화를 무효화할 수 있다"는 것이다. 모델이 바뀌면 무너질 주장(Figure 2의 저분산, RLHF 모델의 진보 편향, 협력 역설의 개별 결과들)과 살아남을 주장(분산-평균 분해 틀, 검증 깊이 매칭 방법론, 회고 검증의 데이터 누출 문제)을 구분해서 읽어야 한다(논문 외 해석). Appendix F의 모순 감사 권고는 사실상 "우리의 경험적 전제도 세대마다 재검증하라"는 자인이다.

### 6.3 논문 내부의 어긋남: 코딩과 서술이 안 맞는 곳

수치·코딩을 인용할 때 주의할 불일치가 둘 있다(전문 대조로 확인). 첫째, §5.1 본문은 한 연구(Table 1의 Wang et al. 2025b 행)의 분산 지표가 "실데이터와 직접 비교되지 않았다"고 서술하면서, Table 2와 Appendix C는 같은 연구를 "Comparable"(인간과 유사한 분산)로 코딩한다. 자체 코딩 기준(Appendix D.3의 "(None)" 범주)과 충돌한다. 분산이 인간과 비교 가능했던 사례는 표면상 2편인데, 그중 1편이 이 모순에 걸려 있으므로 "내재적 한계의 반례"는 사실상 1편(Tang et al. 2025a 행 — 3장에서 본, 규모-분산 관계를 유일하게 보고한 연구)으로 읽는 편이 안전하다. 둘째, Appendix C는 comparable 2편의 모델이 "저분산 맥락에도 재등장한다"고 하지만, GPT-4o-mini는 표의 다른 어느 행에도 없다. GPT-4o 계열로 뭉뚱그려야만 성립하는 진술이다.

### 6.4 과잉 주장을 경고하는 논문의 전칭 주장

논문은 연구자들에게 주장의 조건·범위를 엄밀히 한정하라고 요구하면서, 자신은 분산 점검 9편의 관찰적 교차표를 근거로 "근본적으로 제한한다"(fundamentally limits), "LLM 본성의 근본 문제" 같은 전칭 주장을 편다(논문 외 비판). 원인 분해도 없다. 분산 붕괴가 사전학습 목적함수 탓인지, RLHF 탓인지, 디코딩 탓인지 이 논문 안에서는 구분되지 않는다. usage/boundary 이분법 자체도 같은 문제를 안는다. 내재적 한계라면서 Appendix G는 개선 방향을 열거하는데, 훈련·아키텍처 개입으로 완화될 수 있다면 그것은 "현 세대의 성질"이지 내재적 한계가 아니다. 논문은 "어느 것도 입증되지 않았다"로 봉합할 뿐 이 구분의 지위를 해소하지 않는다(논문 외 비판). 같은 잣대를 자기 논증에 적용하면 이 논문의 주장 수준은 스스로 허용한 "집합-정성"을 넘는다. 안전지대로 승인한 Case 1에도 미검증 전제가 있다: 낮은 분산이 정성적 집합 패턴까지 왜곡하지 않는다는 보장은 없고, 훈련 데이터에 널리 존재하는 고전 패턴(Schelling 분리, 추측 게임 균형)의 재현이 사회동학의 재현인지 교과서 지식의 회수인지도 구분되지 않는다. 낙관론을 반박할 때 쓴 바로 그 논리("훈련 분포의 규칙성인가")가 자신의 안전지대로는 향하지 않는다(논문 외 비판).

## 7. 방법적 한계와 확장

### 7.1 논문이 남긴 것

포지션 페이퍼답게 자기 한정은 곳곳에 있다. 분류에 판단이 개입함을 인정하고(Appendix D.1), 핵심 판별 기준인 "허용 가능한 분산 이탈"의 정량 역치가 아직 없음을 밝히며(Appendix F), 이질성 개선 방향(데이터 큐레이션, 다양성 보상, 제약 디코딩, 페르소나 라우팅, 인간-LLM 하이브리드 집계, 멀티모델 앙상블 — 단 멀티 LLM도 소수 전략에 집중한다는 단서가 붙는다)을 열거하되 "어느 것도 완전한 해결이 입증되지 않았다"고 못 박는다(Appendix G.2). v1의 과제 절을 옮긴 Appendix H도 남긴 것 목록이다: 검증 방법 부재(LLM 자기보고 의존), 주장 조건의 명시, 소외집단 편향·윤리, 시뮬 발견의 실증 환류 4항. 남는 실질적 공백은 체크리스트의 판별력이다. Table 1에서 이미 18/21이 집합-정성 수준으로 주장을 제한하고 있으므로 "주장 제한" 축은 현장에서 거의 판별력이 없고, 실질 구속력은 분산 보고 축 하나에 몰려 있다(논문 외 해석). 그리고 §5.2의 충실도 역설이 주는 교훈(집계 평균 정렬이 하위집단별 상쇄 이탈의 합일 수 있다)을 정작 자기 체크리스트는 반영하지 않는다. Appendix D.3은 전체 평균·분산 점검만 요구하고 하위집단 조건부 점검을 명시하지 않는다(논문 외 비판).

### 7.2 위키 관점: 정렬 역설의 판정론 (논문 외 해석)

위키의 정렬 역설 트랙(RLHF 정렬이 강할수록 인구 대표성이 낮아진다)이 원인론이라면, 이 논문은 판정론이다. average persona의 분산-평균 분해는 정렬 역설을 두 성분으로 나눈다: 분산 붕괴(우도 훈련이 롱테일을 소거)와 평균 이동(인간 피드백 훈련이 특정 방향의 편향을 주입, §4.2 Case 2). 어떤 모델·처방이든 이 2×2 좌표(분산 높/낮 × 평균 정렬/이탈)에 놓고 판정할 수 있다는 것이 이 논문이 트랙에 주는 도구다. 경계 처방 자체는 모델을 고치지 않는다는 점에서, Modular Pluralism류 모델 측 개입과도 PAPG류 입력 측 개입과도 다른 제3의 위치, 곧 주장 측 규율이다.

### 7.3 PAPG와의 역할 분담 (논문 외 해석)

이 논문은 PAPG를 §4.2에서 한 번 인용한다. "정렬에는 광범위한 사회인구학적 조건화가 필요하다"의 증거로, Argyle과 같은 괄호 안에서다. 그러나 두 논문의 관계는 그 한 줄보다 깊다. PAPG는 경계를 넓히려는 공학적 처방(입력 페르소나 분포를 실측에 정렬)이고, 이 논문은 그런 처방이 성공했는지 판정하는 프로토콜이다. 1.3절에서 본 input/output heterogeneity 구분이 PAPG의 약한 고리를 짚는다. 실제로 Appendix C의 관찰로는 페르소나 구성 방식이 분산 결과를 예측하지 못한다. PAPG 리뷰에서 확인한 사실과 포개면: PAPG는 입력 분포 정렬(Big Five 응답 기준)을 입증했지만 그 검증도 결국 설문 응답이라는 한 도메인이었고, 이 논문 기준의 출력 수준 검증(평균+분산의 ground truth 비교, 하위집단 조건부 점검)은 다음 단계로 남아 있다. 위키 파이프라인에서는 PAPG류를 처치로, 이 논문의 체크리스트를 처치 효과의 평가 프로토콜이자 주장 게이트로 배치하는 구도가 자연스럽다.

### 7.4 한국·비서구 함의 (논문 외 해석)

Case 2(평균 이탈)의 증거는 대부분 문화 축이다. 다국어 시뮬레이션의 문화 가치 불일치, 문화·언어 관습 미준수(§4.2). 한국어 사회시뮬은 기본값이 Case 2일 가능성이 높고, 이 논문의 프레임으로 번역하면 한국 대상 시뮬은 KGSS류 실측 분포로 평균 정렬을 먼저 입증하기 전까지는 Case 1의 안전지대(집합-정성 주장)조차 주장할 수 없다. 판별 휴리스틱을 적용하면 위키의 관심 질문들(하위집단 차이, 소수자 영향, 양극화)은 High 이질성 요구로 코딩되어 "현 세대 LLM 시뮬에 부적합" 판정이 나온다. 이 판정은 prereg가 시뮬 주장 이전에 대표성 열화 측정 단계를 두는 설계와 정합적이다. Appendix F의 분산 이탈 역치 수립(F.2)과 모순 감사(F.5)는 모델 판올림마다 재측정해야 하는 prereg 설계에 그대로 이식 가능한 실행 항목이다. 단 하나 보강할 것: 이 논문의 체크리스트에는 하위집단 조건부 점검이 없으므로(7.1절), 한국 프로그램에서 쓰려면 충실도 역설의 교훈대로 하위집단별 평균·분산 점검을 추가해야 한다.

## 8. 결론

이 논문의 기여는 좌표계다. 새 실험 데이터는 없다. average persona라는 진단을 분산-평균 2축으로 조작화하고, 그 축으로 기존 연구 21편의 검증 관행을 재고, 연구 질문의 이질성 요구와 검증 깊이를 맞추라는 규범을 체크리스트로 만들었다. 포지션 페이퍼로서의 자기 방어도 갖췄다. 반대 입장 절, 모순 사례 분석, 판단 개입과 역치 부재의 명시가 그것이다. 약점도 그 좌표계 안에서 보인다: 경험 근거는 편의 표본과 특정 모델 세대에 묶여 있고, "내재적 한계"라는 전칭 주장은 증거 깊이를 넘어서며, 체크리스트의 실질 구속력은 분산 보고 요건뿐이다. 그래도 경계의 위치는 바뀌어도 경계를 긋는 방법은 남는 구조라, 모델 세대가 바뀐 뒤에도 재사용할 수 있는 틀이다.

읽는 법을 정리하면:

| 목적 | 어디를 읽나 |
|---|---|
| 주장 전체의 한 장 요약 | Figure 1, 이 글 2장 |
| average persona의 정의·기원 | §4.1, 이 글 2장 |
| 검증 관행의 실태 | Table 1과 §5.1, 이 글 3장 |
| 실무 판별 도구 | Appendix E–F, 이 글 4장 |
| 판본 차이와 코딩 불일치 | 이 글 1.2절·6.3절 |
| PAPG·정렬 역설과의 연결 | 이 글 7.2–7.4절 |

시리즈 안에서는 PAPG 리뷰(blog/papg)의 짝 편이다. 같은 문제(LLM의 인구 대표성)를 PAPG는 입력을 고쳐서, 이 논문은 주장을 제한해서 다룬다. 다음 연결로는 silicon sampling(LLM으로 인간 설문 표본을 대체하는 접근)의 원점(Argyle et al., 2023)과 그 반증(Bisbee et al., 2024), 그리고 맞논문(Anthis et al., 2025)이 자연스럽다.

## References

Anthis, J. R., Liu, R., Richardson, S. M., Kozlowski, A. C., Koch, B., Brynjolfsson, E., Evans, J., & Bernstein, M. S. (2025). Position: LLM social simulations are a promising research method. *Proceedings of the 42nd International Conference on Machine Learning, Position Paper Track*. https://arxiv.org/abs/2504.02234 ([PDF 보기](/paper-viewer?title=Position%3A+LLM+social+simulations+are+a+promising+research+method&source=blog-reference&authors=Jacy+R.+Anthis%3BRyan+Liu%3BShaylyn+M.+Richardson%3BAustin+C.+Kozlowski%3BBernard+Koch%3BErik+Brynjolfsson%3BJames+Evans%3BMichael+S.+Bernstein&year=2025&arxiv_id=2504.02234&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2504.02234.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F2504.02234))

Argyle, L. P., Busby, E. C., Fulda, N., Gubler, J. R., Rytting, C., & Wingate, D. (2023). Out of one, many: Using language models to simulate human samples. *Political Analysis*, *31*(3), 337–351. https://doi.org/10.1017/pan.2023.2 ([PDF 보기](/paper-viewer?title=Out+of+one%2C+many%3A+Using+language+models+to+simulate+human+samples&source=blog-reference&authors=Lisa+P.+Argyle%3BEthan+C.+Busby%3BNancy+Fulda%3BJoshua+R.+Gubler%3BChristopher+Rytting%3BDavid+Wingate&year=2023&doi=10.1017%2Fpan.2023.2&url=https%3A%2F%2Fdoi.org%2F10.1017%2Fpan.2023.2))

Bisbee, J., Clinton, J. D., Dorff, C., Kenkel, B., & Larson, J. M. (2024). Synthetic replacements for human survey data? The perils of large language models. *Political Analysis*, *32*(4), 401–416. https://doi.org/10.1017/pan.2024.5 ([PDF 보기](/paper-viewer?title=Synthetic+replacements+for+human+survey+data%3F+The+perils+of+large+language+models&source=blog-reference&authors=James+Bisbee%3BJoshua+D.+Clinton%3BCassidy+Dorff%3BBrenton+Kenkel%3BJennifer+M.+Larson&year=2024&doi=10.1017%2Fpan.2024.5&url=https%3A%2F%2Fdoi.org%2F10.1017%2Fpan.2024.5))

Epstein, J. M. (1999). Agent-based computational models and generative social science. *Complexity*, *4*(5), 41–60. https://doi.org/10.1002/(SICI)1099-0526(199905/06)4:5<41::AID-CPLX9>3.0.CO;2-F ([PDF 보기](/paper-viewer?title=Agent-based+computational+models+and+generative+social+science&source=blog-reference&authors=Joshua+M.+Epstein&year=1999&doi=10.1002%2F%28SICI%291099-0526%28199905%2F06%294%3A5%3C41%3A%3AAID-CPLX9%3E3.0.CO%3B2-F&url=https%3A%2F%2Fdoi.org%2F10.1002%2F%28SICI%291099-0526%28199905%2F06%294%3A5%3C41%3A%3AAID-CPLX9%3E3.0.CO%3B2-F))

Grossmann, I., Feinberg, M., Parker, D. C., Christakis, N. A., Tetlock, P. E., & Cunningham, W. A. (2023). AI and the transformation of social science research. *Science*, *380*(6650), 1108–1109. https://doi.org/10.1126/science.adi1778 ([PDF 보기](/paper-viewer?title=AI+and+the+transformation+of+social+science+research&source=blog-reference&authors=Igor+Grossmann%3BMatthew+Feinberg%3BDaniel+C.+Parker%3BNicholas+A.+Christakis%3BPhilip+E.+Tetlock%3BWilliam+A.+Cunningham&year=2023&doi=10.1126%2Fscience.adi1778&url=https%3A%2F%2Fdoi.org%2F10.1126%2Fscience.adi1778))

Hu, Z., Lian, J., Xiao, Z., Xiong, M., Lei, Y., Wang, T., Ding, K., Xiao, Z., Yuan, N. J., & Xie, X. (2025). *Population-aligned persona generation for LLM-based social simulation* (arXiv:2509.10127). arXiv. https://arxiv.org/abs/2509.10127 ([PDF 보기](/paper-viewer?title=Population-aligned+persona+generation+for+LLM-based+social+simulation&source=blog-reference&authors=Zhengyu+Hu%3BJianxun+Lian%3BZheyuan+Xiao%3BMax+Xiong%3BYuxuan+Lei%3BTianfu+Wang%3BKaize+Ding%3BZiang+Xiao%3BNicholas+Jing+Yuan%3BXing+Xie&year=2025&arxiv_id=2509.10127&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2509.10127.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F2509.10127))

Santurkar, S., Durmus, E., Ladhak, F., Lee, C., Liang, P., & Hashimoto, T. (2023). Whose opinions do language models reflect? *Proceedings of the 40th International Conference on Machine Learning*, 29971–30004. https://arxiv.org/abs/2303.17548 ([PDF 보기](/paper-viewer?title=Whose+opinions+do+language+models+reflect%3F&source=blog-reference&authors=Shibani+Santurkar%3BEsin+Durmus%3BFaisal+Ladhak%3BCinoo+Lee%3BPercy+Liang%3BTatsunori+Hashimoto&year=2023&arxiv_id=2303.17548&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2303.17548.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F2303.17548))

Schelling, T. C. (1971). Dynamic models of segregation. *The Journal of Mathematical Sociology*, *1*(2), 143–186. https://doi.org/10.1080/0022250X.1971.9989794 ([PDF 보기](/paper-viewer?title=Dynamic+models+of+segregation&source=blog-reference&authors=Thomas+C.+Schelling&year=1971&doi=10.1080%2F0022250X.1971.9989794&url=https%3A%2F%2Fdoi.org%2F10.1080%2F0022250X.1971.9989794))

Wu, Z., Peng, R., Ito, T., Onizuka, M., & Xiao, C. (2025). *Position: LLM-based social simulations require a boundary* (arXiv:2506.19806). arXiv. https://arxiv.org/abs/2506.19806 ([PDF 보기](/paper-viewer?title=Position%3A+LLM-based+social+simulations+require+a+boundary&source=blog-reference&authors=Zengqing+Wu%3BRun+Peng%3BTakayuki+Ito%3BMakoto+Onizuka%3BChuan+Xiao&year=2025&arxiv_id=2506.19806&pdf_url=https%3A%2F%2Farxiv.org%2Fpdf%2F2506.19806.pdf&url=https%3A%2F%2Farxiv.org%2Fabs%2F2506.19806))

Wu, Z., Peng, R., Zheng, S., Liu, Q., Han, X., Kwon, B. I., Onizuka, M., Tang, S., & Xiao, C. (2024). Shall we team up: Exploring spontaneous cooperation of competing LLM agents. *Findings of the Association for Computational Linguistics: EMNLP 2024*, 5163–5186. https://doi.org/10.18653/v1/2024.findings-emnlp.297 ([PDF 보기](/paper-viewer?title=Shall+we+team+up%3A+Exploring+spontaneous+cooperation+of+competing+LLM+agents&source=blog-reference&authors=Zengqing+Wu%3BRun+Peng%3BShuai+Zheng%3BQian+Liu%3BXu+Han%3BBonggun+I.+Kwon%3BMakoto+Onizuka%3BShaojie+Tang%3BChuan+Xiao&year=2024&doi=10.18653%2Fv1%2F2024.findings-emnlp.297&url=https%3A%2F%2Fdoi.org%2F10.18653%2Fv1%2F2024.findings-emnlp.297))
