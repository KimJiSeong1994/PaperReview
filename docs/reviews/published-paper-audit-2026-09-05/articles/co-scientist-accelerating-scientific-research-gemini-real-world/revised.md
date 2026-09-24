# Accelerating Scientific Research with Gemini in the Real-World

**Paper:** Samuel Schmidgall; Xiaokai Zhu; Marian Shaw; Lin Yang; Valentin Liévin; Jingyun Yang; Yuchen Zhuang; Tim Strother; Alex Bijamov; Min Woo Sun; Anil Palepu; Justin Chen; David Steiner; Jacqueline Shreibati; Wei-Hung Weng; Yilin Zhao; Xingjian Hu; Nicholas Zahn; Sadhya Garg; Julia Kirby; Yuxiang Gan; Jiaoli Li; Divy Thakkar; Shekoofeh Azizi; David Racz; Juraj Gottweis; Vivek Natarajan; Chenglin Wu; Tal Danino; Keran Rong; Haozhe Wang; Benoit Schillings; Yong Cheng; Quoc V. Le; Tao Tu (2026). "Accelerating Scientific Research with Gemini in the Real-World". https://arxiv.org/abs/2608.26701 · arXiv:2608.26701

**Abstract:** Schmidgall et al.은 가설 생성에 집중했던 Co-Scientist를 실험 장비 연동, 코드 실행, 원고 작성까지 수행하는 실행 기반 연구 에이전트로 확장한다. 논문은 재료합성, 생물학, 의료 소프트웨어, 논문 자동생성의 네 영역에서 시스템을 평가한다. 신뢰성 모듈을 켠 논문생성 조건에서는 결과 환각이 46%에서 4%로 줄었고, Agent_H는 HealthBench 길이보정 네 조건에서 모두 1위를 기록했다. 다만 MXene 유사 물질의 정체는 확정되지 않았고, Agent_H와 기준선의 호출 예산은 맞춰지지 않았으며, 사람 연구자와 시간·비용을 통제한 비교도 없다.

---

## Executive Summary

| 항목 | 설명 |
| --- | --- |
| 연구 질문 | 가설 생성형 Co-Scientist를 실제 실험·코드 실행·원고 작성으로 확장하고, 실행 과정에서 생기는 보상 해킹과 환각을 줄일 수 있는가. |
| 핵심 기여 | Co-Scientist를 실행 기반 연구 파트너로 확장하고, 재료합성·생물학·의료 소프트웨어·논문 자동생성 네 영역에서 평가했다. |
| 방법적 결과 | 원고의 수치 주장을 실행 로그와 직접 대조하는 장치는 명시적이다. 반면 아이디어 단계의 결합 최적화는 §2와 §2.1의 설명이 달라 본문만으로 완전히 재구성하기 어렵다. |
| 실험 결과 | 논문생성 연구의 결과 환각은 신뢰성 모듈 사용 시 4%, 모듈을 끈 절제판에서 46%, Agent Laboratory에서 90%였다. Agent_H는 길이보정 네 조건에서 모두 1위였지만 원점수 네 조건에서는 한 번만 1위였다. |
| 핵심 한계 | MXene 유사 물질의 정체가 확정되지 않았고, Agent_H는 질의당 40~80회 호출을 쓰는 반면 기준선은 1회다. 길이보정과 맹검 절차를 완전히 재현하기 어렵고, 연구 전체의 가속은 직접 측정하지 않았다. |

---

## 목차

1. 가설 생성에서 실행 기반 연구로
2. Co-Scientist의 실행·검증 루프
3. 실험실 연동 평가
4. Agent_H와 HealthBench
5. 논문 자동생성 평가
6. 결과가 뒷받침하는 범위
7. 결론

## 1. 가설 생성에서 실행 기반 연구로

### 1.1 이전 Co-Scientist와 이번 논문의 범위

이전 Co-Scientist는 *Nature*에 실린 Gottweis et al. (2026)으로, 가설 생성이 중심이었다. 이번 논문은 목표를 "execution-grounded research partner"로 넓힌다. 계산 안에서 아이디어를 내는 데서 멈추지 않고, 화학기상증착 장비와 연동하고 코드를 실행하며 논문을 완성하는 시스템을 지향한다.

### 1.2 네 평가 영역을 한눈에 보기

| 영역 | 시스템이 수행한 일 | 평가의 중심 |
| --- | --- | --- |
| 재료합성 | CVD 합성 프로토콜 탐색과 TMD 성장 레시피 제안 | 재현 성공률, 분광·현미경 특성, 물질 정체 |
| 생물학 | IPTG 조건에 따른 E. coli 군집 형태 예측 | 공개 wet-lab 이미지와의 일치, 전문가 개입 범위 |
| 의료 소프트웨어 | 추론 시점 스케일링 구조 Agent_H 설계 | HealthBench 점수와 임상의 위해 평가 |
| 논문 자동생성 | 코드 실행부터 원고 작성까지의 자동화 | 환각·표절·안전성, 신뢰성 모듈 절제 |

## 2. Co-Scientist의 실행·검증 루프

### 2.1 보상 해킹이 핵심 문제가 되는 이유

§1은 자동 리뷰어 점수 같은 대리 목표만 최적화하면, 사실 검증 없이도 그럴듯한 결과·방법·인용을 만들어 보상 해킹에 빠질 수 있다고 지적한다. §2는 이 실패를 줄이기 위해 원고 점수에 페널티를 결합하고, 원고의 수치와 실행 로그를 대조하는 장치를 둔다.

### 2.2 환각·표절 페널티

첫 장치는 결합 최적화 페널티다. 원고 생성 시 리뷰어 점수에 환각·표절 페널티를 붙이며, 계수는 $\lambda_{hall} = 1.0$, $\lambda_{plag} = 0.5$다. 다만 환각 페널티의 근거로 제시한 $\Delta S_{reviewer} \le 0.3$은 측정값이나 인용 없이 등장한다. 논문은 페널티가 최대 1까지 부과될 수 있으므로 리뷰어 점수의 한계 이득을 항상 상쇄한다고 설명하지만, 최대치와 항상 성립한다는 보장은 같은 말이 아니다. 실제 페널티가 0.2라면 0.3의 점수 이득을 상쇄하지 못하며, 논문은 이런 범위를 설명하지 않는다.

### 2.3 실행 로그와 원고 수치 대조

더 직접적인 장치는 실행 로그 대조다. 원고의 수치 주장을 에이전트가 실행한 코드 로그와 맞춰 보고, 로그에서 확인되지 않는 수치가 있으면 문장을 다시 쓰게 한다. 확률적 자기평가보다 검증 기준이 명시적이며, §3.4에서 보고한 환각 감소 결과도 이 장치의 의도와 부합한다.

### 2.4 본문만으로 재구성하기 어려운 구현 경계

다만 §2와 §2.1의 설명은 맞물리지 않는다. §2는 가설 적합도에 리뷰어 점수와 표절 페널티가 함께 들어간다고 쓰지만, §2.1은 수치 페널티 대신 LLM 동료평가·Bayesian inference·프롬프트 수준 제약을 쓴다고 설명한다. 이어지는 알고리즘에도 TrueSkill 평점과 UCB 선택만 나타난다. 프롬프트 제약을 적합도 함수의 항으로 볼 수는 없으므로, 아이디어 단계의 결합 최적화가 정확히 어떻게 구현되는지는 본문만으로 재구성하기 어렵다.

## 3. 실험실 연동 평가

재료과학 절은 성격이 다른 두 실험을 다룬다. 한쪽의 성공률을 다른 쪽에 적용하면 결과를 잘못 읽게 된다.

### 3.1 MXene 유사 물질: 성공률과 정체 유보

목표는 Ti₃C₂Tₓ MXene을 습식 식각이 아니라 바닥부터 CVD로 키우는 것이다. 시스템이 육염화에탄(C₂Cl₆)을 전구체로 제안했고, XRD에서 2θ = 7.8° 피크가 나왔다.

논문은 재현성 한계를 구체적으로 공개한다. 첫 관찰 뒤 반복 실험의 성공률은 26회 중 3회, 11.5%였고 XRD에서는 TiO₂ 부산물이 다량 검출됐다. 저자들은 원인을 밀봉 불량에 따른 산소 누출로 보고, 석영관과 오링을 닦고 오링을 주기적으로 교체하며 배출관을 열 번마다 세척하는 정비 절차를 도입했다.

그 뒤 성공률은 25회 중 17회, 68.0%로 올랐다. 저자 보고에서 성공률 개선 직전에 명시된 직접 개입은 새 레시피가 아니라 유지보수 절차 변경이다. 이후에도 25회 중 8회는 실패했다.

프로토콜도 온전히 자동화된 것은 아니다. 25회의 실험 주기 동안 인간 전문가가 272개 후보 가운데 선택된 C₂Cl₆+Ti 프로토콜을 다듬었다.

저자들은 물질의 정체도 확정하지 않는다. §3.1.4는 습식 식각 Ti₃C₂Tₓ와 맞지 않는 측정값을 함께 제시한다. TEM-EDS에서는 산소와 질소가 검출되고, Raman에서는 TiO₂ 특유의 진동 모드가 나타나며, XPS에서는 Ti–O 결합만 관찰된다. 최종 확인에는 단면 원자분해능 STEM이 필요하다는 것이 논문의 결론이다. 후보도 Ti₃C₂Tₓ, Ti₂CCl₂, 그 밖의 상으로 열어 둔다. 반증 가능성이 있는 측정값을 결과 절에 함께 보고한 점은 평가할 만하다.

표현의 강도는 위치에 따라 다르다. 초록·서론 불릿·Table 1·§5·Figure 2 캡션은 "consistent with", "analogous to", "further experiments needed"처럼 유보적으로 쓴다. 반면 §3.1.2에서는 Ti₃C₂Tₓ MXene의 특성과 "matching"한다고 표현하고, Figure 2c 범례는 물질을 곧바로 "MXene"으로 표시한다. 같은 결과를 두고 본문 안에서도 확정의 정도가 달라진다.

### 3.2 TMD: 별도의 1회 성공 실험

TMD 실험은 앞선 MXene 유사 물질 실험과 별개다. MoS₂·MoSe₂·WS₂ 세 물질은 Gemini 3 Deep Think로 레시피를 맞춰 성장시켰고, Figure 3d는 첫 시도에 합성됐다고 보고한다. 그중 MoS₂는 Raman의 E¹₂g/A₁g 간격 약 21 cm⁻¹로 단일층을 확인했다. 따라서 앞의 11.5%→68.0% 성공률은 이 실험에 적용되지 않는다.

### 3.3 E. coli 군집 예측과 전문가 개입

조작된 대장균이 IPTG 농도에 따라 만드는 군집 형태를, 희소한 이미징 데이터에서 예측하는 시스템을 Co-Scientist가 만들었다. 초록은 결과를 "largely matching unpublished wet-lab morphological measurements"라 적는다.

여기서 "unpublished"는 데이터가 비공개라는 뜻이 아니라 선행 논문으로 출판되지 않았다는 뜻이다. 대조에 사용한 세균 군집 이미지는 Data Availability에 적힌 Zenodo 저장소(https://doi.org/10.5281/zenodo.19612563)에서 확인할 수 있다.

더 중요한 한계는 전문가 개입과 시스템 기여가 분리되지 않는다는 점이다. 논문은 도메인 전문가가 과제 구성을 반복해서 다듬었다고 적지만, 어느 단계까지가 시스템의 산출이고 어느 단계부터가 전문가의 재구성인지는 구분하지 않는다.

## 4. Agent_H와 HealthBench

### 4.1 원점수와 길이보정 점수

Co-Scientist가 자율적으로 추론 시점 스케일링 구조를 설계했고, 그것을 Agent_H라 부른다. HealthBench Hard(1,000문항)와 HealthBench Professional(525문항)에서 여섯 프런티어 모델과 비교한다. 심판은 LLM 둘(Gemini 3.5 Flash, GPT-5.4 Low Reasoning)이며, 점수는 심판별 8회의 grading run으로 집계한다.

Table 2의 여덟 조건을 모두 비교하면, 심판과 지표에 따라 순위가 달라진다.

| 심판 | 지표 | Agent_H | 1위 | Agent_H 순위 |
| --- | --- | ---: | --- | --- |
| Gemini 3.5 Flash | Hard 원점수 | 0.420 | Agent_H | 1위 (2위 GPT-5 0.414) |
| Gemini 3.5 Flash | Hard 길이보정 | 0.377 | Agent_H | 1위 |
| Gemini 3.5 Flash | Professional 원점수 | 0.645 | Claude Opus 5 0.697 | 3위 |
| Gemini 3.5 Flash | Professional 길이보정 | 0.643 | Agent_H | 1위 |
| GPT-5.4 | Hard 원점수 | 0.335 | GPT-5 0.372 | 3위 |
| GPT-5.4 | Hard 길이보정 | 0.292 | Agent_H | 1위 (2위 GPT-5 0.291) |
| GPT-5.4 | Professional 원점수 | 0.621 | Claude Opus 5 0.677 | 3위 |
| GPT-5.4 | Professional 길이보정 | 0.619 | Agent_H | 1위 |

길이보정 점수에서는 네 조건 모두 Agent_H가 1위다. 원점수에서는 네 조건 중 하나만 1위이며, 그 차이도 0.420 대 0.414로 0.006이다. 신뢰구간은 Agent_H [0.397, 0.443], GPT-5 [0.395, 0.434]로 크게 겹친다. GPT-5.4 심판의 Hard 길이보정도 0.292 대 0.291로 차이가 작다.

길이보정은 2,000자를 기준으로 긴 답변에 벌점을 주는 변환이다. 계수는 Hard 7.84×10⁻⁵, Professional 2.94×10⁻⁵다. 장문 응답의 장황함을 통제한다는 목적은 분명하다. 다만 초록은 1위라는 결과가 길이보정 점수에서 나온다는 조건을 밝히지 않는다.

### 4.2 길이보정 값의 재현성

논문은 §3.3에 평균 응답 길이도 보고한다. Agent_H는 Hard에서 2,549자(SD 299), Professional에서 1,850자(SD 329)이고, Gemini 3.1 Pro는 각각 5,020자(SD 1,758)와 7,618자(SD 1,438)다. Claude Opus 5의 Professional 평균은 6,201자다. 이 평균값과 Table 2의 원점수−길이보정 차이를 나란히 놓으면 설명이 더 필요한 지점이 보인다.

| 모델 | 평균 길이 | 벌점(Gemini 심판) | 벌점(GPT-5.4 심판) |
| --- | ---: | ---: | ---: |
| Agent_H | 1,850자 | 0.002 | 0.002 |
| Claude Opus 5 | 6,201자 | 0.125 | 0.124 |
| Gemini 3.1 Pro | 7,618자 | 0.061 | 0.062 |

Professional에서 Gemini 3.1 Pro의 평균 응답은 Claude Opus 5보다 1,417자 길지만, 표에 나타난 점수 차감 폭은 절반 이하다. 평균 길이에 단순 선형 계수를 적용하는 식만으로는 이 값을 설명할 수 없다.

캡션 설명을 `벌점 = 계수 × max(평균 길이 − 2,000, 0)`의 단순식으로 해석해 다시 계산하면 차이는 더 분명해진다.

| 모델 | 벤치마크 | 예측 벌점 | 실제 벌점 |
| --- | --- | ---: | ---: |
| Agent_H | Hard | 0.0430 | 0.043 |
| Agent_H | Professional | 0.0000 | 0.002 |
| Claude Opus 5 | Professional | 0.1235 | 0.125 |
| Gemini 3.1 Pro | Hard | 0.2368 | 0.088 |
| Gemini 3.1 Pro | Professional | 0.1652 | 0.061 |

이 단순식은 Agent_H의 Hard 값과 Claude Opus 5의 Professional 값을 소수 셋째 자리 수준에서 재현하지만, Gemini 3.1 Pro에서는 두 벤치마크 모두 맞지 않는다. 다만 논문이 정확한 함수식이나 문항별 길이 분포를 공개하지 않았으므로, 이 차이를 계산 오류라고 단정할 수는 없다. 표의 값이 문항별 비선형 보정에서 나온 것인지, 캡션에 빠진 절차가 있는지, 단순 오기인지는 확인되지 않는다.

불일치가 Agent_H를 유리하게 만드는 방향도 아니다. 단순식대로라면 Gemini 3.1 Pro의 Hard 길이보정 점수는 보고된 0.148보다 낮아진다. 남는 문제는 길이보정이 핵심 결과를 바꾸는 변환인데도 독자가 표를 재현할 만큼의 식과 집계 절차가 공개되지 않았다는 점이다.

### 4.3 호출 예산과 임상 위해 평가

계산량은 Agent_H가 질의당 약 40~80회의 LLM 호출, 여섯 기준선이 각 1회다. 이 차이는 캡션에 공개돼 있지만, 호출 예산을 맞춘 비교는 없다.

임상 위해 평가는 전문의 세 명이 106개 문항에서 Agent_H와 Gemini 3.1 Pro를 맹검 비교한 결과다. 문항마다 한 명의 임상의가 아홉 차원을 평가했고, 잠재적 임상 위해에서만 FDR 보정 후 p=0.0486이 나왔다. 나머지 여덟 차이는 유의하지 않았고 문항 수준 평가자 간 신뢰도도 측정하지 않았다. 다중비교 보정은 했지만, 효과의 범위는 한 차원과 한 기준선에 한정된다.

본문은 이 조건들을 밝히며 결과를 "significant, though modest"라고 부른다. 반면 초록은 유의한 위해 감소만 언급하고, 비교 대상이 Gemini 3.1 Pro 하나라는 점과 p=0.0486이라는 경계선상의 결과는 생략한다.

## 5. 논문 자동생성 평가

### 5.1 비교 설계와 신뢰성 모듈

이 절은 같은 주제를 세 조건에 적용해 신뢰성 모듈의 효과를 비교한다. 주제 50개로 조건마다 50편씩, 모두 150편을 만들고 전문가 30명이 450건을 리뷰했다. 조건은 ①모든 신뢰성 모듈을 켠 Co-Scientist, ②같은 구조에서 모듈만 끈 절제판, ③Agent Laboratory다. 주제를 맞춰 둔 설계라 과제 난이도보다 아키텍처 차이를 비교하기 쉽다.

Agent Laboratory는 제1저자의 전작이다. 기준선 구현에 대한 정보 비대칭은 비교적 작지만, 그것만으로 비교의 공정성이 보장되는 것은 아니다.

### 5.2 환각·표절·안전성 결과

결과 환각(심각도 ≥5)은 4% 대 46% 대 90%, 방법론 환각(≥5)은 24% 대 52% 대 100%, 심각한 표절은 16% 대 50% 대 60%다. 특히 ①과 ②의 차이가 커서, 저자의 설계 안에서는 신뢰성 모듈의 효과를 지지한다. 안전성 평가에서 위해 프롬프트 거부율은 98.7%(691/700, 95% CI [98.1%, 99.3%])였다.

### 5.3 맹검·통계·척도 보고의 불확실성

해석하기 전에 해석의 한계도 있다. 다음 항목은 논문이 직접 인정한 한계가 아니라, 공개된 연구설계와 보고 방식에서 도출되는 해석이다.

- 주제 50개는 사람이 아니라 Gemini가 하나의 프롬프트로 생성했고, 전체 목록은 부록에 없다. 평가 대상 시스템 둘과 주제 생성기가 같은 모델 계열이다.
- 논문은 연구를 "double-blind"라고 부르지만, 무엇을 누구에게 가렸는지 운영 절차를 설명하지 않는다. 리뷰어가 조건을 몰랐는지, 원고에서 LaTeX 템플릿·도판·서지 형식 같은 식별 흔적을 제거했는지, 원고를 어떻게 배정했는지는 문서만으로 확인되지 않는다.
- 주제 대응 설계를 사용했지만 χ²·Fisher·Mann–Whitney 같은 비대응 3군 검정을 보고한다. 리뷰어나 주제를 임의효과로 넣은 모형도 없다. 따라서 대응 구조가 분석에 반영됐는지는 불분명하다.
- novelty 결과의 표기도 맞지 않는다. 본문은 Co-Scientist의 평균을 0.80이라고 보고하면서 109/150건을 "Novel (score 1)"로 분류한다. 부록의 1~5 루브릭만 적용하면 1보다 작은 평균은 나올 수 없다. 선행 이진 게이트의 0점이 평균에 포함됐을 가능성이 있지만, 원시 평점이 없어 실제 척도를 확정할 수는 없다.
- 단위도 섞여 있다. Figure 8 패널은 조건마다 "50 ratings each"라고 쓰지만, 표절 설명은 같은 조건을 "150 reviews"라고 부른다.
- §3.4.1은 코드 품질과 원고의 전반적 과학적 가치를 평가 항목으로 열거하고, 부록 D.3.6에는 코드 가독성·모듈성 루브릭도 제시한다. 그러나 150편을 세 조건으로 비교한 두 지표의 결과는 보고되지 않는다. 실제 수집 여부와 누락 이유는 확인할 수 없다.

## 6. 결과가 뒷받침하는 범위

네 평가는 같은 강도로 결론을 지지하지 않는다. 논문생성 절제는 모듈의 효과를 직접 비교하지만, 나머지 평가는 물질 정체·전문가 개입·점수 보정·호출 예산 같은 조건에 더 크게 의존한다.

| 평가 | 가장 직접적인 근거 | 해석의 경계 |
| --- | --- | --- |
| 논문 자동생성 | 같은 주제와 시스템 구조에서 신뢰성 모듈만 끈 절제 비교 | 맹검·배정 절차와 대응 분석이 충분히 설명되지 않음 |
| 재료합성 | 반복 실험의 성공률과 분광·현미경 측정 | 물질 정체 미확정, 인간의 프로토콜 보정과 유지보수 개입 |
| E. coli 예측 | 공개된 wet-lab 이미지와 형태 비교 | 전문가가 과제 구성을 반복해서 다듬은 범위가 분리되지 않음 |
| Agent_H | 두 심판·두 벤치마크의 원점수와 길이보정 점수 | 길이보정 절차 일부 미공개, 40~80회 대 1회의 호출 예산 차이 |

### 6.1 가장 강한 근거: 신뢰성 모듈 절제

논문생성 연구의 4% 대 46%는 서로 다른 시스템끼리의 비교가 아니라 같은 구조에서 신뢰성 모듈만 켜고 끈 비교다. 모든 조건에 같은 50개 주제를 적용했기 때문에, 이 논문 안에서 모듈의 효과를 가장 직접적으로 보여 주는 결과다. 실행 로그와 원고 수치를 대조하는 장치도 확률적 자기검토보다 검증 기준이 분명하다.

### 6.2 논문이 밝힌 한계

논문은 MXene 유사 물질의 원자 구조를 확정하지 못했고 타 연구실 재현도 이루어지지 않았다고 적는다. 임상 평가에서는 문항당 평가자가 한 명이고 아홉 차원 중 여덟이 유의하지 않았으며, Agent_H와 기준선의 호출 예산도 맞추지 않았다. Co-Scientist 전체 소스코드는 공개하지 않고, §3.3의 의료 산출물은 연구용이며 FDA 승인을 받지 않았다고 명시한다.

### 6.3 보고와 재현성의 경계

실험 결과의 해석은 공개된 설정과 보고 방식의 범위에 한정된다. 83쪽 분량에 본문 표는 두 개뿐이라 주요 결과의 상당 부분이 도판과 부록에 흩어져 있다. 임상 위해의 "though modest"와 HealthBench의 길이보정 조건은 초록에서 빠지고, MXene 유사 물질은 §3.1.2 일부가 초록과 결론보다 더 강하게 표현한다.

개요 도판도 길이보정 결과만 전면에 둔다. Figure 1의 CS 패널은 "HealthBench Pro Length Adj."를 제목으로 쓰며, 값은 Table 2의 Gemini 3.5 Flash 심판 길이보정 열과 일치한다(0.643 / 0.614 / 0.581 / 0.572 / 0.485 / 0.467). 같은 벤치마크 원점수에서는 Claude Opus 5가 0.697로 Agent_H의 0.645를 앞서지만, 이 열은 개요 도판에 없다.

안전성 거부율 98.7%는 무엇을 거부했는지는 보여 주지만 어떤 규정을 적용했는지는 재구성하기 어렵다. 본문은 "restricted category", "established safety policies", "safety criteria"를 언급하지만 구체 목록을 제시하지 않는다. 부록의 "명백한 악성", "이중용도", "안전·표준 연구"는 인간 평가자용 채점 범주이며, 시스템의 거부 규정과 어떻게 연결되는지 설명되지 않는다. §2.2가 두 층의 윤리 감독을 설명하며 가리키는 Figure A4도 실제로는 실행 전 코드 위해성 검사 파이프라인을 그린다.

### 6.4 직접 측정하지 않은 "가속"

사람 연구자와 시간·비용·성공률을 맞춰 비교한 대조군이 없으므로, 제목의 "Accelerating"은 이 논문에서 직접 측정된 결과가 아니다. "in minutes"는 레시피 생성 단계에 대한 설명일 뿐, 25회의 설계 반복과 수십 회의 물리 실험을 포함한 전체 연구 주기를 재지는 않는다.

## 7. 결론

Co-Scientist는 가설을 제안하는 시스템에서 한 걸음 더 나아가 장비·코드·원고를 실행·검증 루프로 연결한다. 네 영역을 한 시스템으로 묶고, 실패율·호출량·반증 가능성이 있는 측정값까지 본문에 공개했다는 점이 이 논문의 기여다.

증거의 강도는 영역마다 다르다. 신뢰성 모듈을 켜고 끈 논문생성 절제의 4% 대 46%는 가장 직접적이다. 재료합성 결과에는 물질 정체와 인간 개입, Agent_H 결과에는 길이보정과 호출 예산, 임상 결과에는 한 기준선·한 차원이라는 조건이 붙는다.

따라서 이 논문은 과학 연구의 가속을 입증한 결과라기보다, 가설 생성형 Co-Scientist를 실행 기반 연구 파트너로 확장했을 때 무엇을 검증할 수 있고 어떤 조건이 남는지를 네 영역에서 보여 준 연구로 읽는 편이 정확하다.

---

## References

Arora, R. K., Wei, J., Hicks, R. S., Bowman, P., Quiñonero-Candela, J., Tsimpourlas, F., Sharman, M., Shah, M., Vallone, A., Beutel, A., et al. (2025). *HealthBench: Evaluating large language models towards improved human health* (arXiv:2505.08775). arXiv. https://arxiv.org/abs/2505.08775

Gottweis, J., Weng, W.-H., Daryin, A., Tu, T., Sirkovic, P., Myaskovsky, A., Glowaty, G., Weissenberger, F., Orlandi, A., Popovici, D., et al. (2026). Accelerating scientific discovery with co-scientist. *Nature, 655*, 487–496. https://doi.org/10.1038/s41586-026-10644-y

Hicks, R. S., Trofimov, M., Lim, D., Arora, R. K., Tsimpourlas, F., Bowman, P., Sharman, M., Tong, C., Karthik, K., Dugar, A., et al. (2026). *HealthBench Professional: Evaluating large language models on real clinician chats* (arXiv:2604.27470). arXiv. https://arxiv.org/abs/2604.27470

Schmidgall, S., Su, Y., Wang, Z., Sun, X., Wu, J., Yu, X., Liu, J., Moor, M., Liu, Z., & Barsoum, E. (2025). Agent laboratory: Using LLM agents as research assistants. In C. Christodoulopoulos, T. Chakraborty, C. Rose, & V. Peng (Eds.), *Findings of the Association for Computational Linguistics: EMNLP 2025* (pp. 5977–6043). Association for Computational Linguistics. https://doi.org/10.18653/v1/2025.findings-emnlp.320

Schmidgall, S., Zhu, X., Shaw, M., Yang, L., Liévin, V., Yang, J., Zhuang, Y., Strother, T., Bijamov, A., Sun, M. W., Palepu, A., Chen, J., Steiner, D., Shreibati, J., Weng, W.-H., Zhao, Y., Hu, X., Zahn, N., Garg, S., … Tu, T. (2026). *Accelerating scientific research with Gemini in the real-world* (arXiv:2608.26701v1). arXiv. https://arxiv.org/abs/2608.26701v1
