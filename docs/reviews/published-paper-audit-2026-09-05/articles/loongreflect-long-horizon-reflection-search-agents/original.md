**Paper:** Zhang, Z., Jiang, X., Yang, Z., Xu, W., Qiu, G., Chu, X., Zhao, J., & Wang, Y. (2026). *LoongReflect: Boosting long-horizon reflection in search agents via global perspective distillation* (arXiv:2608.11967v1). arXiv. https://arxiv.org/abs/2608.11967

**Abstract:** 이 문서는 장기지평 검색 에이전트의 반성(reflection)을 학습 문제로 정식화한 LoongReflect를 절별로 따라간다. 논문의 출발점은 반성이 국소 분기에서 수행되는데 그 가치는 최종 궤적 결과로만 드러난다는 불일치이고, 해법은 반성을 메모리 제어 정책으로 바꾼 뒤 특권 교사의 조밀한 국소 지도와 결과 기반 전역 보정을 두 채널로 결합하는 것이다. 방법의 구성과 실험 수치를 확인하고, 표제 격차 +12.6점이 어느 층에서 발생했는지를 학습 데이터 구성까지 거슬러 검토한다.

---

## Executive Summary

| 항목 | 설명 |
|------|------|
| 연구 질문 | 장기지평 에이전트에서 "지금 분기를 계속할까, 고칠까, 버릴까"라는 반성 결정을 어떻게 학습시킬 것인가 |
| 핵심 기여 | (1) 반성을 되돌릴 수 있는 궤적 트리 위의 **메모리 제어 정책**으로 정식화하고 `<reflect>`·`<backtrack>`을 명시적 행동으로 도입, (2) 답 마스킹 교사 증류(fast) + 결과 기반 GRPO(slow)의 2채널 학습, (3) 두 방향을 합치기 전에 조정하는 look-ahead 결합 |
| 방법적 결과 | 형식 정리는 없다. 설계 결과는 비활성 분기를 활성 컨텍스트에서 빼되 트리에는 남겨 진단에 쓴다는 분리, 그리고 fast 방향에서 slow와 충돌하는 성분만 제거하는 기울기 투영 |
| 실험 결과 (저자 보고) | QA 7종 평균 F1이 3B에서 46.15, 7B에서 49.21로 최강 베이스라인 AgenticRAG-R1 대비 +12.60·+12.61. MATH 56.0·GSM8K 82.4로 +1.2·+1.8. 절제에서 `<reflect>` 제거 −15.31 |
| 재현 가능성 | 코드·체크포인트 공개 여부에 대한 언급 없음. 학습은 A800-80GB 8장 1노드, RL 100 outer step, SFT 궤적 600편. **단일 시드**(논문이 부록에서 명시) |

---

## 목차

1. 문제 설정 — 국소에서 결정하고 전역에서 평가된다
2. 반성을 메모리 제어로 바꾸기
3. 궤적 트리와 두 개의 제어 행동
4. Fast 채널 — 답을 가린 교사에게서 배우기
5. Slow 채널 — 결과로 보정하기
6. Look-ahead 결합, 그리고 그것이 실은 무엇인가
7. 실험 설정과 SFT 데이터가 만들어진 방식
8. 주 결과
9. 절제 실험을 열별로 다시 읽기
10. 격차 +12.6점의 출처를 분해하기
11. 논문이 밝힌 한계와 검토자 관점
12. 결론

---

## 1. 문제 설정 — 국소에서 결정하고 전역에서 평가된다

![반성의 국소–전역 불일치](/api/blog/figures/loongreflect-fig1-motivation.png)

*Zhang et al. (2026), Figure 1. CC BY 4.0 원문을 연구·비평 목적으로 인용. [원문](https://arxiv.org/abs/2608.11967) · [라이선스](https://creativecommons.org/licenses/by/4.0/).*

LLM 에이전트가 계획·도구 사용·메모리를 오가며 여러 단계를 밟을 때, 다음 행동을 생성하는 것만으로는 부족하다. 지금 궤적이 진전하고 있는지, 증거가 충분한지, 앞선 분기를 고치거나 버려야 하는지를 계속 판정해야 한다. 논문은 이 판정을 반성이라 부르고, 추가 사고 텍스트가 아니라 **궤적 자체에 대한 제어 과정**으로 규정한다.

긴 지평에서 이게 특히 중요한 이유는 오염이 누적되기 때문이다. 관련 없는 검색 결과, 잘못 연결된 개체, 낡은 메모리 갱신 같은 국소 오류가 활성 컨텍스트에 들어오면 이후의 많은 결정에 영향을 준다. 격리하고 정정할 장치가 없으면 궤적이 길어질수록 상태 오염이 불어난다.

그런데 반성을 학습시키기가 어렵다. 논문이 두 가지 난점으로 정리한다.

**C1 학습 신호 딜레마.** 반성 결정의 가치는 이후 많은 행동을 거쳐 최종 결과에서야 드러난다. 결과 기반 강화학습은 희소하고 지연되며 귀속이 약한 지도만 준다. 그렇다고 반성에 중간 보상을 직접 매기면 보상 해킹이 생긴다. 과제 성공과 무관하게 과하거나 피상적인 반성을 부추긴다.

**C2 국소–전역 관점 격차.** 반성은 현재 분기의 컨텍스트에서 수행되는데, 그 가치는 그 분기가 전체 궤적에 어떻게 기여하는지로 결정된다. 국소 반성자는 계속·수정·포기 중 무엇이 최종 결과를 개선할지 직접 관측할 수 없다.

두 난점을 합치면 요구조건이 서로 당긴다. 효과적인 반성은 조밀한 국소 지도로 배워야 하는데, 평가와 보정은 전역 궤적 관점에서 해야 한다.

## 2. 반성을 메모리 제어로 바꾸기

![LoongReflect 전체 구조](/api/blog/figures/loongreflect-fig2-framework.png)

*Zhang et al. (2026), Figure 2. CC BY 4.0 원문을 연구·비평 목적으로 인용. [원문](https://arxiv.org/abs/2608.11967) · [라이선스](https://creativecommons.org/licenses/by/4.0/).*

논문의 첫 수는 반성을 자유 형식 언어 피드백에서 떼어내는 것이다. 에이전트가 추론 메모리에서 무엇을 유지·수정·폐기할지에 대한 구조화된 결정으로 바꾼다.

단계 $t$에서 에이전트 상태는 다음과 같다.

$$z_t = (x,\ \mathcal{T}_t,\ P_t,\ m_t)$$

$\mathcal{T}_t$는 누적 궤적 트리, $P_t$는 활성 실행 경로, $m_t$는 그 경로에서 압축한 작업 메모리다. 에이전트는 $P_t$를 따라 순차적으로 행동하지만 전체 상호작용 이력이 선형일 필요는 없다. 앞선 상태로 되돌아가 실행을 재개하면 새로 생성된 접미부가 대안 분기가 되고 버려진 접미부는 비활성 분기로 트리에 남는다. 회복이 반복되면 자연히 트리가 되고, 루트에서 노드까지의 각 경로가 하나의 실행 분기가 된다.

LLM 컨텍스트는 $c_t = \text{Serialize}(x, P_t, m_t)$로 직렬화된다. 모델이 보는 것은 과제와 활성 경로와 압축 메모리뿐이다. 트리 $\mathcal{T}_t$와 보관 분기 $\mathcal{B}_t$는 내부 상태로 남아 이후 진단과 회복에만 쓰인다.

이 분리가 설계의 핵심이다. **비활성 분기는 활성 컨텍스트에서 빠져 이후 결정을 오염시키지 않지만, 트리에는 남아 오류 진단과 반성 지도에 쓰인다.** 오염된 분기에서 빠져나오되 그것으로부터 배울 정보는 버리지 않는다.

## 3. 궤적 트리와 두 개의 제어 행동

행동 공간이 실행과 제어로 나뉜다. $a_t \sim \pi_\theta(\cdot \mid z_t)$, $a_t \in \mathcal{A}_{\text{exec}} \cup \mathcal{A}_{\text{ctrl}}$. 실행 행동은 추론·도구 사용·답변이고, 제어 행동은 둘이다.

$$a_t^{\text{ctrl}} \in \mathcal{A}_{\text{ctrl}} = \{\texttt{<reflect>},\ \texttt{<backtrack>}\}$$

`<reflect>`는 활성 상태를 진단한다. 증거를 요약하고, 빠진 정보나 잘못된 가정을 짚고, 다음 제어 결정을 제안한다. 출력은 구조화된 4항 요약이다.

$$r_t = (e_t^{\text{ver}},\ q_t^{\text{risk}},\ j_t^{\text{ret}},\ d_t^{\text{ctrl}}), \qquad d_t^{\text{ctrl}} \in \{\text{continue},\ \text{backtrack}\}$$

각각 검증된 증거, 위험, 복귀 지점, 제어 의도다. 마지막 항이 있어서 반성이 일반적 비평이 아니라 상태 제어 진단이 된다.

`<backtrack>`은 회복을 실행한다. 신뢰할 만한 접두부로 되돌리고 오염된 접미부를 활성 컨텍스트에서 제거한다.

$$P_{t+1} = P_j \oplus u_{j:t}, \qquad \mathcal{B}_{t+1} = \mathcal{B}_t \cup \{P_{j+1:t}\}$$

$u_{j:t}$는 현재 반성에서 뽑아낸 압축 정정 갱신이다. 결정적 모순, 반증된 가정, 다음 시도가 만족해야 할 제약 같은 것이다. 부록에 따르면 컨트롤러는 체크포인트를 역순으로 평가해 제안된 정정을 뒷받침하는 가장 최근 체크포인트에서 재개하고, 루트가 완전 초기화 지점이 된다.

## 4. Fast 채널 — 답을 가린 교사에게서 배우기

두 채널 중 첫째는 반성 토큰에만 걸리는 조밀한 지도다.

교사는 실행 이력에서 답 마스킹 구조 제어 라벨을 만든다.

$$h_t = H_\phi(x,\ \mathcal{T}_{\le t},\ P_t,\ m_t)$$

$\mathcal{T}_{\le t}$에는 현재 활성 경로와 보관된 과거 분기가 모두 들어간다. $H_\phi$는 특권 힌트 구성자이고, 논문은 "보조 LLM 또는 규칙 기반 피드백 모듈"로 구현된다고 적는다. 출력 스키마는 `<reflect>` 요약과 같다. 요컨대 교사는 전역 실행 기록에 접근하되 최종 답은 가린 채 힌트를 만든다. 그래서 fast 채널이 지도하는 것은 답 생성이 아니라 국소 진단과 회복이다.

학생과 교사는 같은 접두부와 연속을 평가한다. 교사에게만 추가로 주어지는 것이 구조화 힌트 $h_t$다. 교사 $q_{\bar\theta}$는 정책의 EMA다.

$$\ell_{t,k} = \log \pi_\theta(y_{t,k} \mid c_t, y_{t,<k}), \qquad \bar\ell_{t,k} = \log q_{\bar\theta}(y_{t,k} \mid c_t, h_t, y_{t,<k})$$

반성 구간에만 손실을 걸기 위해 토큰 마스크를 둔다.

$$m^{\text{ref}}_{t,k} = \mathbb{I}\big[y_{t,k} \in \text{Span}(\texttt{<reflect>}, \texttt{<backtrack>})\big]$$

교사–학생 로그확률 차 $\delta_{t,k} = \ell_{t,k} - \bar\ell_{t,k}$에 대해 마스킹된 역 KL을 최적화한다.

$$\mathcal{L}_{\text{fast}} = \frac{1}{Z}\sum_{t,k} m^{\text{ref}}_{t,k}\,\min\big(\exp(-\delta_{t,k}) - 1 + \delta_{t,k},\ c\big)$$

$k3$ 형태의 불편 추정량에 극단적 토큰비를 누르는 클리핑 상수 $c$를 붙였다(부록 표 8에서 $c=10$).

## 5. Slow 채널 — 결과로 보정하기

둘째 채널은 반성 결정의 전역 효용을 최종 결과로 판정한다. 과제 $x$마다 완전한 궤적 $\tau_1,\dots,\tau_G$를 표집하고 종단 보상 $R_1,\dots,R_G$를 받아 그룹 상대 이점을 만든다.

$$\hat{A}_i = \frac{R_i - \text{mean}_g(R_g)}{\text{std}_g(R_g)}$$

손실은 표준 GRPO 클리핑 목적에 KL 정규화를 더한 형태이고, 토큰비는 $\rho_{i,k}(\theta) = \pi_\theta(y_{i,k}\mid c_{i,k}) / \pi_{\text{old}}(y_{i,k}\mid c_{i,k})$다. 귀속을 분명히 하려고 slow 목적은 최종 활성 실행의 정책 생성 토큰에만 적용한다. 도구 출력, 외부 관측, 컨트롤러 갱신은 제외한다.

$\hat{A}_i$가 종단 결과에서 나오므로, slow 채널은 반성이 전체 성능을 개선할 때만 그것을 보상한다.

## 6. Look-ahead 결합, 그리고 그것이 실은 무엇인가

두 채널의 갱신 방향이 충돌할 수 있다. 논문은 slow가 fast를 최적화 전에 보정하는 방식을 쓴다.

먼저 fast 내부 갱신을 $K$번 적용해 잠정 정책 $\tilde\theta = U^K_{\text{fast}}(\theta)$를 얻고, 누적 내부 스텝 크기 $\alpha$로 fast 방향을 정의한다. $g_f = (\theta - \tilde\theta)/\alpha$로, 기울기 부호 규약을 따르므로 뒤의 융합 갱신에서 부호가 맞는다. 그다음 $\tilde\theta$에서 궤적을 평가해 slow 보정 방향 $g_s = \nabla_{\tilde\theta}\mathcal{L}_{\text{slow}}(\tilde\theta)$를 얻는다. 둘이 충돌하면 $g_f$에서 $g_s$에 반하는 성분을 뺀다.

$$g_f^{\text{LA}} = \begin{cases} g_f - \dfrac{\langle g_f, g_s\rangle}{\|g_s\|_2^2}\,g_s, & \langle g_s, g_f\rangle < 0 \\[4pt] g_f, & \text{그 외}\end{cases}$$

그리고 원래 파라미터로 돌아와 $\theta_+ = \theta - \eta_s g_s - \eta_f g_f^{\text{LA}}$로 융합 갱신한다.

여기서 짚어둘 것이 있다. **투영식 자체는 PCGrad류 기울기 수술과 식 수준에서 매우 유사하다.** 두 기울기의 내적이 음일 때 한쪽을 다른 쪽의 법선 평면에 투영하는 연산으로, 다중과제 학습에서 널리 쓰이는 형태다. 논문은 이를 "extragradient-style"이라 부르지만, 이 투영 연산과 관련 선행 연구의 관계를 구분해 설명하거나 인용했으면 더 명확했을 것이다. 방법의 차별점은 투영식 자체보다 $g_s$를 $\theta$가 아니라 $K$번 앞서 나간 $\tilde\theta$에서 계산한다는 look-ahead 평가 위치에 더 가깝다.

## 7. 실험 설정과 SFT 데이터가 만들어진 방식

**모델과 벤치마크.** Qwen2.5-3B·7B instruct를 쓰고 절제는 3B로 한다. HotpotQA와 2WikiMultiHopQA로 학습하고, 이 둘을 in-domain으로, Bamboogle·FRAMES·MuSiQue·NQ·TriviaQA를 out-of-domain으로 평가한다. 수학 전이는 MATH·GSM8K다. 검색은 2023년 11월 1일자 영어 위키백과 스냅숏으로 통일하고, 리트리버·top-k·컨텍스트 예산·도구호출 예산·디코딩 설정·답 정규화기를 모든 방법에 같게 맞췄다. 지표는 답 수준 F1이다.

**여기가 이 논문에서 가장 중요한 대목이다 — SFT 데이터 구성.** RL 전에 Qwen3-32B를 로컬에 띄워 SFT 궤적을 증류한다. 절차가 이렇다.

1. 교사가 16턴·턴당 1,024토큰·궤적 16,384토큰 예산 안에서 궤적을 생성한다.
2. 상호작용 예산이 남은 상태에서 교사가 **틀린 답을 내놓으면**, 정답과의 exact-match 검증이 개입해 답변 행동을 `<reflect>`–`<backtrack>` 턴으로 바꾸고 정답에 도달할 때까지 롤아웃을 이어간다.
3. 1차 거부 표집: 정답에 도달했고 `<reflect>`가 최소 1회 있고 상호작용이 최소 5턴인 궤적만 남긴다.
4. 2차 거부 표집: 같은 질문을 **Search-R1로 다시 풀려 보고, 반성 궤적이 성공하면서 Search-R1이 실패하는 경우만 남긴다.**
5. 최종 SFT 집합은 궤적 600편.

두 가지가 걸린다. 첫째, 반성 시점이 **정답을 아는 상태에서 결정된다.** 교사는 자기가 틀렸을 때 반성하는데, 틀렸다는 판정은 정답 대조로 이뤄진다. 그러니 SFT 시연이 가르치는 것은 "틀렸을 때 반성하라"이고, 그 타이밍 신호는 시험 시점에 존재하지 않는다. 특권 교사 증류에서 흔한 구도이긴 하나, 학습된 반성 트리거가 오라클 타이밍에 맞춰 보정됐다는 뜻이기도 하다.

둘째, 4단계가 더 무겁다. **표 1의 주요 RL 베이스라인 중 하나인 Search-R1이 실패한 문제를 SFT 선별 조건에 포함했다.** 따라서 최종 SFT 집합은 일반적인 문제 표본이라기보다 Search-R1의 실패 영역을 의도적으로 강조한 표본이다.

## 8. 주 결과

**표 1 — QA 7종 F1 (저자 보고, 발췌)**

| 모델 | 방법 | 2Wiki | HotpotQA | Bamboogle | FRAMES | MuSiQue | NQ | TriviaQA | 평균 |
|---|---|---|---|---|---|---|---|---|---|
| 3B | Search-R1 | 29.90 | 37.24 | 29.90 | 10.76 | 13.53 | 34.73 | 55.08 | 30.16 |
| 3B | AgenticRAG-R1 | 32.92 | 44.00 | 31.48 | 16.23 | 16.48 | 37.15 | 56.62 | 33.55 |
| 3B | **LoongReflect** | 48.01 | 56.17 | 35.25 | 23.51 | 31.02 | 55.37 | 73.72 | **46.15** |
| 7B | AgenticRAG-R1 | 38.34 | 45.15 | 49.21 | 19.44 | 22.01 | 23.60 | 58.45 | 36.60 |
| 7B | **LoongReflect** | 54.44 | 53.27 | 53.89 | 23.17 | 25.81 | 58.98 | 74.91 | **49.21** |

모든 벤치마크·두 모델 크기에서 최고 F1이다. 이 주장은 표를 열별로 확인해도 성립한다. 평균 격차는 3B에서 +12.60, 7B에서 +12.61이고, in-domain 38.46 → 52.09, out-of-domain 31.59 → 43.77(3B)이다. 본문에 적힌 소계도 전부 표와 맞는다.

**표 4 — 학습 단계별 기여 (평균 F1)**

| 단계 | 3B | 7B |
|---|---|---|
| RAW | 30.33 | 37.73 |
| SFT | 34.76 (+4.43) | 41.27 (+3.54) |
| SFT+RL | 46.15 (+11.39) | 49.21 (+7.94) |

**표 3 — 수학 전이 (3B)**

| 방법 | MATH | GSM8K |
|---|---|---|
| AgenticRAG-R1 | 54.8 | 80.6 |
| RLSD | 53.6 | 80.7 |
| LoongReflect | 56.0 | 82.4 |

여기서 크기 대비가 눈에 띈다. QA에서 +12.6점이던 격차가 수학에서는 +1.2·+1.8점이다. 논문의 서술은 "검색 없는 다단계 추론에도 도움이 된다" 정도로 절제돼 있어 과장은 아니다. 다만 초록의 "일관된 개선"이라는 말이 두 자릿수와 한 자릿수 소수점을 같은 단어로 묶는다.

## 9. 절제 실험을 열별로 다시 읽기

**표 2 — 구성요소 절제 (3B, F1 %)**

| 설정 | 2Wiki | HotpotQA | Bamboogle | FRAMES | MuSiQue | NQ | TriviaQA | 평균 |
|---|---|---|---|---|---|---|---|---|
| LoongReflect | **48.01** | **56.17** | **35.25** | 23.51 | **31.02** | 55.37 | **73.72** | **46.15** |
| w/o `<reflect>` | 26.41 | 37.74 | 18.35 | 11.46 | 18.18 | 45.28 | 58.45 | 30.84 |
| w/o `<backtrack>` | 33.67 | 45.89 | 19.22 | 15.18 | 14.78 | 49.22 | 53.67 | 33.09 |
| w/o Fast 증류 | 37.50 | 47.13 | 32.58 | **25.00** | 13.64 | **63.33** | 64.37 | 40.51 |
| w/o Slow 최적화 | 30.12 | 55.29 | 25.29 | 21.43 | 20.73 | 54.65 | 66.28 | 39.11 |
| w/o Look-ahead | 36.26 | 49.84 | 31.93 | 19.08 | 27.43 | 55.94 | 68.01 | 41.21 |

(볼드는 원논문 표기 그대로인 열 최댓값. 절제판이 최댓값을 가진 두 칸이 곧 완전 모형을 앞선 칸이다)

두 메모리 제어 행동의 기여는 확실하다. 반성을 빼면 평균이 15.31점, 백트래킹을 빼면 13.06점 떨어지고, 두 경우 모두 일곱 벤치마크 전부에서 완전 모형에 못 미친다. 최적화 3요소의 평균 손실은 각각 7.04(slow), 5.64(fast), 4.94(look-ahead)로 순서도 그럴듯하다.

그런데 열별로 보면 본문 서술과 어긋나는 곳이 있다. 논문은 "최적화 절제 역시 완전 모형보다 일관되게 나쁘다"고 적는데, **fast 증류를 뺀 모형이 NQ에서 63.33으로 완전 모형 55.37을 7.96점 앞선다.** FRAMES에서도 25.00 대 23.51로 앞선다. look-ahead를 뺀 모형도 NQ에서 근소하게(55.94 대 55.37) 앞선다. 평균으로는 맞는 서술이지만 "일관되게"는 성립하지 않는다.

논문 자신도 이 두 칸을 열 최댓값으로 볼드 처리했으니 조판으로는 인정한 셈인데, 본문은 다루지 않는다. NQ에서의 7.96점 역전은 그냥 잡음으로 보기에 크다. NQ는 단일 홉 개방형 QA라 다중 홉 반성이 오히려 방해가 될 수 있다는 해석이 가능한데, 논문은 이 칸을 언급하지 않는다. 같은 표에서 MuSiQue는 반대다. fast를 빼면 13.64로 떨어져 반성 자체를 뺀 경우(18.18)보다도 나쁘다. 한 구성요소를 제거했을 때 벤치마크마다 부호가 갈리는 상황인데 평균 한 줄로 정리된다.

**하이퍼파라미터 민감도.** $w=1$에서 내부 fast 갱신 수를 $K=1$(41.26) → $K=3$(46.15) → $K=4$(44.71)로 바꾸면 3에서 꺾인다. $K=3$에서 $w=1$이 $w=0.5$·$w=2.0$보다 낫다. 본 실험은 $K=3$, $w=1$을 쓴다. 최적점이 격자의 안쪽에 있다는 점은 좋은 신호이지만, 최고값 46.15와 차선 44.71의 차이가 1.44점인데 시드가 하나뿐이라 이 선택이 잡음보다 큰지는 알 수 없다.

## 10. 격차 +12.6점의 출처를 분해하기

표제 수치를 다시 조립해 보면 층이 갈린다.

3B 기준으로 원 instruct 모델이 30.33이고, SFT만 마친 모형이 34.76이다. 여기서 걸리는 점 하나. 표 4의 RAW 30.33과 표 1의 Base 18.33은 같은 Qwen2.5-3B인데 12점 차이가 나고, 논문은 RAW를 정의하지도 두 수를 화해시키지도 않는다(표 1 Base는 검색 없는 조건, 표 4 RAW는 검색 하네스 위의 미학습 모델로 보이나 명시가 없다). 아래 논증은 RAW의 이 해석에 기대고 있다. **표 4와 표 1의 평균을 동일한 평가 축으로 나란히 읽으면, 최강 베이스라인 AgenticRAG-R1이 33.55이므로 이 논문의 RL 기법을 하나도 쓰지 않은 SFT 단계가 이미 1.21점 앞선다.** 7B에서는 그 차이가 4.67점으로 더 크다. 다만 두 표의 조건이 완전히 같은지는 논문이 명시하지 않는다.

그 SFT는 무엇이었나. Qwen3-32B라는 한 세대 뒤·10배 큰 교사에게서 증류한 600편이고, 그 600편에는 (a) 정답 대조로 반성 시점을 정하는 개입이 들어갔고(교사가 틀렸을 때만 발동하므로 전량은 아니다), (b) Search-R1이 실패하는 문제만 남았다. 베이스라인들에게 같은 SFT가 주어졌다는 언급은 없다.

그러면 +12.60에는 최소 세 요인이 함께 들어간 결과로 읽어야 한다. 첫째 32B 교사 증류, 둘째 Search-R1 실패 사례를 포함한 데이터 선별, 셋째 논문이 제안한 2채널 RL이다. 표 4가 셋째 요인의 추가 개선을 11.39점으로 분리해 주는데, 이건 이 논문에서 가장 값어치 있는 숫자다. **하지만 그 11.39점도 앞의 두 요인으로 만들어진 SFT 정책 위에서 측정된 값**이라 완전히 독립적인 기여로 분해되지는 않는다.

여기에 계산 비용이 빠져 있다. 외부 스텝마다 fast 후보 갱신 3회에 slow 후보 갱신 1회, 그리고 $\tilde\theta$에서 궤적을 다시 평가하는 look-ahead가 붙는다. 단일 채널 GRPO 베이스라인보다 스텝당 비용이 더 클 가능성이 있지만, 벽시계 시간이나 GPU 시간이나 토큰 수가 보고되지 않는다. 논문이 부록에서 "되돌릴 수 있는 다중턴 검색과 3-fast/1-slow look-ahead 갱신이 추론·최적화 비용을 늘린다"고 인정하되 수치를 제시하지 않으므로, 계산량을 맞춘 비교인지 판단하기 어렵다.

베이스라인 표 자체에도 이상한 칸이 있다. 3B에서 Mem1의 평균이 15.02로 검색을 전혀 쓰지 않는 Base(18.33)와 CoT(19.61)보다 낮다. 7B에서 AEPO는 12.50으로 Base(23.34)의 절반이고, 같은 AEPO가 3B에서는 24.62였다. ARPO도 3B 29.60에서 7B 24.53으로 내려간다. 모델을 키웠는데 성능이 크게 떨어지는 방법이 여럿이라면 베이스라인 조정과 규모별 안정성을 더 확인할 필요가 있고, 표제 격차를 방법 고유 효과로만 해석하기는 어렵다.

한 가지 더. LoongReflect 자신도 3B에서 7B로 갈 때 일곱 중 셋에서 내려간다. HotpotQA 56.17 → 53.27, MuSiQue 31.02 → 25.81, FRAMES 23.51 → 23.17이다. 평균은 46.15 → 49.21로 3.06점 오르지만 파라미터는 2.33배다. 논문의 "모델 규모를 가로지르는 일관된 이득"은 각 크기에서 베이스라인 대비 이득이 유지된다는 뜻이지 스케일업 이득을 말한 것이 아니므로 이 관찰이 그 문장을 반박하지는 않는다. 다만 방법 자체의 규모 확장성은 표가 보증하지 않는다.

## 11. 논문이 밝힌 한계와 검토자 관점

**논문이 밝힌 한계.** 부록 K에 별도 절이 있고 내용이 성실하다. 검색 품질과 컨트롤러의 체크포인트·회복 판단에 의존한다는 점, 검색 잡음이 검증 상태 구성과 체크포인트 선택에 영향을 줄 수 있고 초기 진단 오류가 이후로 전파된다는 점, 정규화 exact-match 보상이 유효한 의미 별칭을 과소 인정할 수 있다는 점, EMA 교사의 이진 종단 결과가 국소 진단의 문체를 형성할 수 있다는 점을 든다. 비용 증가도 인정한다. 그리고 **현재 실험이 "기록된 단일 시드 구성"이며 여러 독립 시드 비교가 향후 과제라고 명시한다.** 체크포인트 선택 정확도 측정과 압축 갱신을 통한 오류 전파 분석도 미래 작업으로 남긴다.

**검토자 관점의 한계.**

*데이터 선별과 베이스라인 비교의 순환.* SFT 집합을 "Search-R1이 실패하는 문제"로 고른 뒤 Search-R1을 표 1의 베이스라인으로 함께 싣는다. 4단계 필터를 뺐을 때 결과가 어떻게 되는지에 대한 검토가 없다. 일반화 주장의 상당 부분이 out-of-domain 다섯 벤치마크에 걸려 있는데, 학습 분포가 한 베이스라인의 실패 영역으로 좁혀진 상태에서 그 다섯을 얼마나 자유롭게 읽을 수 있는지가 불분명하다.

*SFT를 통제한 대조군 부재.* 베이스라인들이 같은 600편으로 SFT를 받았다는 언급이 없다. 그렇다면 표 1은 "SFT+2채널 RL" 대 "RL만"의 비교다. 표 4가 부분적으로 분해해 주지만, 베이스라인에 같은 SFT를 얹은 조건이 있어야 방법 고유의 기여가 분리된다.

*단일 시드에 얹힌 결정.* 하이퍼파라미터 선택($K=3$, $w=1$)과 절제 순위가 모두 점추정 하나에 기대고 있다. 논문이 이를 부록에서 밝히지만, 1~2점 차이로 결론이 갈리는 표들이 본문에 있다.

*특권 힌트 구성자가 명세되지 않음.* $H_\phi$가 "보조 LLM 또는 규칙 기반 피드백 모듈"이라고만 적혀 있고 실험에서 어느 쪽을 썼는지, 보조 LLM이라면 어느 모델인지가 없다. fast 채널 전체가 이 구성자의 출력에 걸려 있으므로 재현에 필수인 정보다.

*"answer-masked"가 가리는 것과 가리지 않는 것.* 교사는 최종 답 문자열을 보지 않지만 서론에 따르면 궤적 트리와 종단 결과는 본다. 즉 "이 분기가 실패로 끝난다"는 사실이 힌트에 실릴 수 있다. 시험 시점에는 그런 교사가 없으므로, 학습된 반성이 교사가 틀렸을 상황에서도 작동하는지에 대한 검증이 있어야 하는데 없다.

*본문 서술과 표의 어긋남.* "최적화 절제가 일관되게 나쁘다"는 서술이 NQ 두 칸과 FRAMES 한 칸에서 성립하지 않는다. 특히 fast 증류를 뺀 쪽이 NQ에서 7.96점 앞서는 것은 언급할 만한 크기다.

*선행 연구 귀속.* look-ahead 결합의 투영식이 PCGrad류 기울기 수술과 동일한데 인용이 없다.

*재현 경로 부재.* 코드·체크포인트·SFT 데이터의 공개 여부가 논문에 언급되지 않는다. 학습 환경(A800-80GB 8장, RL 100 outer step, 시드 1234/42)은 부록에 상세히 적혀 있어 이 부분은 성실하다.

## 12. 결론

이 논문의 좋은 점은 문제를 정확히 좁힌 데 있다. "반성을 어떻게 잘하게 만들까"라는 막연한 물음을 "국소에서 내리는 결정을 전역 결과로 어떻게 평가·보정할까"로 바꾸고, 그 답을 두 개의 학습 채널과 하나의 결합 규칙으로 구현했다. 반성을 자유 텍스트가 아니라 4항 구조 출력과 두 개의 명시적 행동으로 고정한 것, 그리고 비활성 분기를 컨텍스트에서는 빼되 진단용으로는 남긴 분리는 깔끔한 설계다. 절제에서 두 제어 행동을 뺐을 때 일곱 벤치마크 전부에서 무너지는 것도 그 설계가 실제로 일하고 있음을 보여준다.

근거의 단단함 순으로 정리하면 순서가 논문의 강조와 조금 다르다. 가장 단단한 것은 **메모리 제어 행동의 기여**다(−15.31, −13.06, 전 벤치마크에서 일관). 그다음이 **표 4의 학습 단계 분해**로, 2채널 RL이 SFT 위에 11.39점을 더한다는 숫자는 이 논문에서 가장 정보량이 크다. 반면 표 1의 +12.60은 방법의 기여로 그대로 읽기 어렵다. 32B 교사 증류와 Search-R1 실패 사례를 포함한 데이터 선별이 같은 결과 안에 함께 들어 있고, 계산량 통제 여부도 확인할 수 없다.

수학 전이는 +1.2·+1.8점으로 검색 과제의 10분의 1 수준이다. 이걸 약점으로 볼 필요는 없다. 오히려 이 방법이 무엇을 고치는지를 알려주는 신호에 가깝다. 다중 홉 검색처럼 오염된 분기를 버리고 되돌아갈 여지가 큰 과제에서 크게 작동하고, 그런 구조가 약한 과제에서는 작게 작동한다. 논문이 그 비대칭을 결과로 삼았다면 지금보다 정확한 주장이 됐을 것이다.

---

## References

Cobbe, K., Kosaraju, V., Bavarian, M., Chen, M., Jun, H., Kaiser, L., Plappert, M., Tworek, J., Hilton, J., Nakano, R., Hesse, C., & Schulman, J. (2021). *Training verifiers to solve math word problems* (arXiv:2110.14168). arXiv. https://arxiv.org/abs/2110.14168

Hendrycks, D., Burns, C., Kadavath, S., Arora, A., Basart, S., Tang, E., Song, D., & Steinhardt, J. (2021). *Measuring mathematical problem solving with the MATH dataset* (arXiv:2103.03874). arXiv. https://arxiv.org/abs/2103.03874

Ho, X., Nguyen, A.-K. D., Sugawara, S., & Aizawa, A. (2020). Constructing a multi-hop QA dataset for comprehensive evaluation of reasoning steps. In *Proceedings of the 28th International Conference on Computational Linguistics* (pp. 6609–6625).

Jin, B., Zeng, H., Yue, Z., Yoon, J., Arik, S., Wang, D., Zamani, H., & Han, J. (2025). *Search-R1: Training LLMs to reason and leverage search engines with reinforcement learning* (arXiv:2503.09516). arXiv. https://arxiv.org/abs/2503.09516

Kamoi, R., Zhang, Y., Zhang, N., Han, J., & Zhang, R. (2024). When can LLMs actually correct their own mistakes? A critical survey of self-correction of LLMs. *Transactions of the Association for Computational Linguistics*, *12*, 1417–1440.

Lightman, H., Kosaraju, V., Burda, Y., Edwards, H., Baker, B., Lee, T., Leike, J., Schulman, J., Sutskever, I., & Cobbe, K. (2024). Let's verify step by step. In *International Conference on Learning Representations*.

Madaan, A., Tandon, N., Gupta, P., Hallinan, S., Gao, L., Wiegreffe, S., Alon, U., Dziri, N., Prabhumoye, S., Yang, Y., Gupta, S., Majumder, B. P., Hermann, K., Welleck, S., Yazdanbakhsh, A., & Clark, P. (2023). Self-Refine: Iterative refinement with self-feedback. *Advances in Neural Information Processing Systems*, *36*.

Shinn, N., Cassano, F., Berman, E., Gopinath, A., Narasimhan, K., & Yao, S. (2023). Reflexion: Language agents with verbal reinforcement learning. *Advances in Neural Information Processing Systems*, *36*.

Yang, A., Yang, B., Zhang, B., Hui, B., Zheng, B., Yu, B., Li, C., Liu, D., Huang, F., Wei, H., Lin, H., Yang, J., Tu, J., Zhang, J., Yang, J., Zhou, J., Lin, J., Dang, K., … Qiu, Z. (2024). *Qwen2.5 technical report* (arXiv:2412.15115). arXiv. https://arxiv.org/abs/2412.15115

Yang, Z., Qi, P., Zhang, S., Bengio, Y., Cohen, W. W., Salakhutdinov, R., & Manning, C. D. (2018). HotpotQA: A dataset for diverse, explainable multi-hop question answering. In *Proceedings of the 2018 Conference on Empirical Methods in Natural Language Processing* (pp. 2369–2380).

Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2022). *ReAct: Synergizing reasoning and acting in language models* (arXiv:2210.03629). arXiv. https://arxiv.org/abs/2210.03629

Yu, T., Kumar, S., Gupta, A., Levine, S., Hausman, K., & Finn, C. (2020). Gradient surgery for multi-task learning. *Advances in Neural Information Processing Systems*, *33*, 5824–5836.

Zhang, Z., Jiang, X., Yang, Z., Xu, W., Qiu, G., Chu, X., Zhao, J., & Wang, Y. (2026). *LoongReflect: Boosting long-horizon reflection in search agents via global perspective distillation* (arXiv:2608.11967). arXiv. https://arxiv.org/abs/2608.11967