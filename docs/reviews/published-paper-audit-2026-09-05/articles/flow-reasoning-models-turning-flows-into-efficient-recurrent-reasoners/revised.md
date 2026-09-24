# Flow Reasoning Models: Turning Flows Into Efficient Recurrent Reasoners

**Paper:** Alec Helbling; Andrey Bryutkin; Mauro Martino; Duen Horng Chau; Nima Dehmamy; Hendrik Strobelt (2026). "Flow Reasoning Models: Turning Flows Into Efficient Recurrent Reasoners". https://arxiv.org/abs/2606.29150v3 · https://doi.org/10.48550/arXiv.2606.29150 · arXiv:2606.29150v3

**Abstract:** Helbling et al.은 연속 flow 모델을 이산 구조 추론에 적용하고, denoiser의 노이즈 제거 예측(clean prediction)을 다시 조건으로 넣어 답을 반복 수정하는 Flow Reasoning Model(FRM)을 제안한다. 핵심 문제는 단순 self-conditioning을 깊게 반복할수록 모델이 학습에서 보지 못한 자기 생성 상태를 만나 틀린 고정점으로 수렴할 수 있다는 것이다. Fixed-Point Forcing(FPF)은 표준 flow 경로와 cross-entropy supervision은 유지한 채, carry의 출처만 한 번 통과한 예측에서 모델 자신의 다단계 rollout으로 바꾼다. 저자 보고에서 FPF는 3시드 평균 해결률을 Sudoku-Extreme 32.6%에서 99.2%, Zebra 36.9%에서 99.9%, Maze-Unique 96.2%에서 98.0%로 높인다. Sudoku에서는 EqR의 98.7%를 약 44배 적은 추론 FLOPs로 맞춘다고 보고한다. 다만 이 배수는 곡선 보간값과 EqR의 최고비용점을 비교한 FLOPs 기준 추정치이며, 고정점·끌개 설명은 형식적 수렴 보증이 아니다. 평가 범위도 세 가지 정답형 격자 퍼즐에 한정된다.

---

## Executive Summary

| 항목            | 설명                                                                                                                                                  |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 연구 질문         | 이산 구조 출력 위의 연속 flow 모델을, 결정을 만들고 되돌리는 반복 추론기로 바꿀 수 있는가.                                                                                             |
| 핵심 기여         | (1) denoiser의 깨끗한 예측을 되먹여 flow 시간 $t$와 분리된 추론 깊이 $k$를 만드는 Flow Reasoning Model, (2) 그 되먹임을 모델 자신의 추론 궤적에서 얻은 상태로 학습시키는 Fixed-Point Forcing.         |
| 방법적 결과        | denoiser의 clean prediction을 후보 해이자 flow update로 함께 사용하고, flow 시간 $t$와 recurrent depth $k$를 분리한다. FPF는 canonical flow path의 loss-bearing state를 유지하면서 rollout-derived carry만 조건으로 넣는다. |
| 실험 결과 (저자 보고) | Sudoku-Extreme 99.5%, Zebra 100.0%, Maze-Unique 99.9%(최고점 기준). 3시드 평균은 99.2±0.3 / 99.9±0.2 / 98.0±1.8. Sudoku에서 EqR의 98.7%를 44배 적은 추론 FLOPs로 따라잡는다. |
| 핵심 한계         | 주 평가가 세 격자형 퍼즐에 한정되고 Maze의 최고점은 FRM이 아니다. 44배는 보간과 FLOP 하한에 의존하며, validation-selected sampler·NFE와 미공개 구현 때문에 정확한 재현 범위도 제한된다. 고정점·끌개 언어에 대응하는 정리는 없다. |

---

## 목차

1. 결정을 되돌릴 수 있는 추론기가 필요한 이유
2. 이산 구조 위의 조건부 flow
3. Flow Reasoning Model: flow 시간과 추론 깊이
4. Fixed-Point Forcing
5. 기존 reasoning 방법과 설계 근거
6. 평가 설계와 비교 조건
7. 결과와 절제
8. 결과가 뒷받침하는 범위
9. 결론

## 1. 결정을 되돌릴 수 있는 추론기가 필요한 이유

### 1.1 논문이 겨냥한 문제

구조적 추론은 서로를 제약하는 결정을 하나의 일관된 해로 모으는 일이다. 논문은 기존 두 생성 계열이 각각 다른 이유로 여기서 막힌다고 본다.

**자기회귀 모델은 되돌리지 못한다.** 토큰을 고정된 순서로 확정하기 때문에, 어떤 선택의 전역적 결과가 뒤늦게 드러나도 앞의 선택을 고칠 방법이 없다.

**마스크 확산 모델은 같은 스텝 안에서 서로를 보지 못한다.** 생성 순서는 자유롭고 여러 토큰을 병렬로 예측하지만, 한 스텝에서 갱신되는 토큰들은 현재 상태가 주어지면 조건부 독립이라 서로가 실제로 무엇이 되었는지 반영하지 못한다. 그래서 공격적으로 병렬 갱신하면 불일치가 생기고, 제약이 빡빡한 문제일수록 조금씩 보수적으로 갱신해야 한다. 이미 저지른 오류를 고치려면 remasking 같은 장치를 따로 붙여야 한다.

### 1.2 출발 관측치

논문의 대안은 연속 flow다. 이산 데이터 위의 연속 flow는 모든 토큰과 그 상호의존을 동시에 모델링한다. 그러나 naive flow의 Sudoku-Extreme 해결률은 약 13%에 불과했고, Table 2의 Base Flow 13.1±0.7%가 이 출발점을 보여 준다. 즉 논문의 질문은 flow 자체의 우월성이 아니라, 낮은 기본 성능을 반복 추론으로 어떻게 바꿀 것인가에 있다.

### 1.3 연구 질문

| 질문 | 논문의 답 |
| --- | --- |
| 모든 토큰을 다시 수정할 수 있는 추론 상태를 어떻게 만들까. | denoiser의 clean prediction을 self-conditioning carry로 반복 사용한다. |
| flow의 생성 시간과 “더 생각하는 깊이”를 어떻게 분리할까. | 같은 $(x_t,t)$에서 carry만 반복 갱신해 별도 깊이 $k$를 만든다. |
| 깊은 되먹임의 train–test mismatch를 어떻게 줄일까. | 모델 자신의 rollout에서 만든 carry를 supervision pass에 노출한다. |

## 2. 이산 구조 위의 조건부 flow

### 2.1 무엇을 노이즈하고 무엇을 고정하는가

추론을 조건부 생성으로 환원한다. 데이터 쌍 $(c, y)$에서 $c$는 문제 명세이고(스도쿠의 주어진 단서, 미로의 배치) $y = (y_1, \dots, y_L)$은 어휘 $V$ 위의 이산 해다.

설계에서 먼저 눈에 띄는 것은 **$c$를 노이즈하지 않는다**는 결정이다. 문제 명세는 학습과 추론 내내 고정된 조건 입력이며, flow가 생성하는 대상은 해 $y$뿐이다.

이산 해는 원-핫 끝점 $x_1 \in \{0,1\}^{L \times |V|}$로 올려놓고, 디코딩은 위치별 argmax로 내린다. 노이즈에서 이 끝점까지는 선형 보간으로 잇는다.

$$x_t = (1-t)\varepsilon + t\,x_1, \qquad t \in [0,1]$$

### 2.2 예측 대상이 속도장이 아니라는 것

이 논문에서 중요한 선택이 여기 있다. 네트워크가 직접 예측하는 것은 속도장이 아니라 **깨끗한 토큰의 범주 분포**다. denoiser $D_\theta^t(x_t \mid c)$가 각 위치에서 깨끗한 토큰에 대한 분포를 내놓고, 속도는 거기서 유도된다.

$$v_\theta^t(x_t \mid c) = \frac{D_\theta^t(x_t \mid c) - x_t}{1-t}$$

같은 출력이 그대로 해독 가능한 후보 해이면서 flow를 전진시키는 양이라는 이중 역할이 다음 절의 되먹임을 가능하게 한다.

손실은 토큰별 크로스엔트로피 하나뿐이다.

$$\mathcal{L}_{\text{CE}}(\theta) = \mathbb{E}_{t,c,y,\varepsilon}\left[-\sum_{i=1}^{L} \log D_\theta^t(x_t \mid c)_{i,y_i}\right]$$

여기까지의 standard discrete flow가 FLM 기준선이고, FRM의 기여는 다음 절의 recurrent carry에서 시작한다.

## 3. Flow Reasoning Model: flow 시간과 추론 깊이

### 3.1 carry

self-conditioning은 denoiser에 자기 이전 출력을 추가 입력으로 준다. 모델은 $D_\theta^t(x_t \mid c, s)$가 되고, $s$는 이전의 깨끗한 해 예측을 나른다. $s = \varnothing$은 0으로 채운 널 carry다.

관행적 학습은 순전파를 두 번 한다. 널 carry로 한 번 통과시켜 떼어낸 예측 $\tilde{s} = \text{stopgrad}[D_\theta^t(x_t \mid c, \varnothing)]$을 얻고, 손실을 담당하는 두 번째 통과가 $\tilde{s}$ 또는 널 carry 중 하나를 받는다. 확률 경로와 끝점 손실은 그대로이고 기울기는 $\tilde{s}$를 통과하지 않는다.

### 3.2 flow 시간과 분리된 추론 깊이

되먹이는 것은 **깨끗한 예측**이지 노이즈 상태가 아니다. $(x_t, t)$를 고정한 채 반복하면 이렇게 된다.

$$s_t^{(0)} = \varnothing, \qquad s_t^{(k+1)} = D_\theta^t\!\left(x_t \mid c, s_t^{(k)}\right)$$

여기서 $k$가 **flow 시간 $t$와 분리된 이산 추론 깊이**다. 두 축이 갈라진다는 것이 FRM의 구조적 주장이다. 샘플러는 flow 상태를 전진시키는 것과 현재 flow 시간에서 재귀를 더 도는 것 사이를 오갈 수 있다.

모든 carry가 같은 노이즈 제거 해를 추정하므로 각 갱신이 직접 지도 신호를 받고, 시간축 역전파 없이 학습된다. 이것이 이 설계의 실용적 장점이다.

### 3.3 되먹임만으로는 부족하다

논문은 여기서 멈추지 않는다. self-conditioning은 Sudoku-Extreme을 약 13%에서 33%로 올리지만 깊이에 따라 이득이 포화되어 대부분의 문제를 풀지 못한다.

다만 이 한계는 난이도에 따라 달라진다. 더 쉬운 Sudoku-Shah에서는 self-conditioning만으로 해결률이 약 30%에서 99%까지 오른다. FPF의 필요성은 모든 재귀 문제보다 강한 제약과 긴 수정 과정이 필요한 설정에서 두드러진다.

## 4. Fixed-Point Forcing

### 4.1 학습이 보여주지 않은 상태

식 (4)의 재귀는 후보 해 위의 동역학계를 정의한다. $(x_t, c, t)$를 고정하면 $D_\theta^t$의 반복 적용이 self-conditioning 상태 위의 고정점 반복이 된다. 논문이 바라는 것은 이것이다.

$$s_t^{(k)} \longrightarrow s_t^\star, \qquad D_\theta^t(x_t \mid c, s_t^\star) = s_t^\star, \qquad \text{decode}(s_t^\star) = y^\star$$

문제는 학습이 이 상태를 보여주지 않는다는 데 있다. 관행적 self-conditioning은 정답에서 유도한 보간 $x_t$ 위에서 한 번 통과시켜 carry를 만든다. 그런데 추론은 예측을 반복해서 되먹이므로, 깊이 $k$의 carry는 모델 자신의 닫힌 루프 동역학이 만든 것이다. 두 분포가 다르고 그 차이는 깊이에 따라 커진다.

$$p_{\text{train}}(s \mid x_t, c, t) \neq p^{(k)}_{\text{infer}}(s \mid \hat{x}_t, c, t)$$

논문은 이 불일치의 결과를 둘로 나눈다. 첫째, denoiser가 자기 재귀 상태에 대해 보정되어 있지 않아 **틀렸지만 확신에 찬 예측이 믿을 만한 증거로 되먹여져 오류를 증폭하고 가짜 고정점에 안착**한다. 둘째, 한 번 통과 학습은 몇 번 정제한 뒤에 남는 미세하고 잔차가 작은 오류를 거의 보여주지 않아, 수렴 근처에서 만나는 상태를 고치도록 훈련되지 않는다.

### 4.2 rollout carry를 사용하는 추가 학습

Fixed-Point Forcing은 한 번 통과로 만든 carry를 **모델 자신의 다단계 추론 동역학이 만든 carry**로 갈아 끼운다. 논문은 이 차이를 두 번 보여준다. Figure 3이 도식으로 가르고, Figure 4가 같은 차이를 학습 코드의 차분으로 보여주는데 바뀌는 줄이 몇 되지 않는다.

관행적 절차는 널 carry로 한 번 통과시켜(`carry=None`) 나온 예측을 떼어내 carry로 쓴다. FPF는 대신 supervision 시각 $t$보다 앞선 시각 $t_{\text{start}} \sim \text{uniform}(0, t)$를 뽑고, 거기서 시작한 self-conditioned 롤아웃을 $t$까지 돌려 그 결과를 carry로 쓴다. 그다음은 같다. 표준 보간 $x_t$ 위에서 denoiser를 한 번 더 돌리고 크로스엔트로피로 갱신한다.

![Fixed-Point Forcing](/api/blog/figures/frm-fig3-fpf.png)

*그림 1. Conventional self-conditioning의 one-pass carry를 rollout-derived carry로 대체한다. 출처: Helbling et al. (2026), Figure 3, [arXiv:2606.29150v3](https://arxiv.org/abs/2606.29150v3), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). 원문 도판을 블로그용으로 캡처·축소.*

여기서 표준 flow-matching 목적함수를 보존한다는 의미가 드러난다. **손실을 지는 상태는 여전히 정답에서 유도한 표준 경로 위에 있고**, 모델이 만든 상태는 조건 채널로만 들어온다.

### 4.3 FPF 학습 절차를 다시 쓰면

아래는 §3.2와 Figure 4를 실행 순서대로 재구성한 것이다.

```text
1. 문제 조건 c와 정답 y에서 supervision time t ~ Uniform(0, 1)을 뽑는다.
2. t_start ~ Uniform(0, t)를 뽑고 x_start = (1 - t_start) noise + t_start target을 만든다.
3. x_start에서 시작해 t_start부터 t까지 self-conditioned inference rollout을 실행한다.
4. 마지막 clean prediction을 detach해 carry로 사용한다.
5. 정답에서 만든 canonical x_t와 rollout carry를 denoiser에 넣는다.
6. token cross-entropy로 denoiser를 갱신한다.
```

추론에서는 현재 flow 상태에서 carry를 반복 정제하고, sampler가 flow 시간을 전진시킨다. 논문은 Euler·SDE·held-time sampler를 사용했다고 적지만 각각의 의사코드와 과제별 최종 선택은 제공하지 않는다. 따라서 위 절차는 학습의 핵심 흐름을 재구성한 것이며, 전체 sampler 구현을 복원한 것은 아니다.

### 4.4 고정점 언어의 지위

논문은 올바른 해를 안정적인 끌개로 만든다는 동역학 언어를 사용한다. 이 설명에 대응하는 형식 정리가 있는지는 별도로 구분해야 한다.

논문은 contraction 조건이나 수렴·정확성 정리를 제시하지 않는다. 식 (5)는 증명된 성질이 아니라 **기대하는 거동**의 서술이다.

논문도 이 경계를 명시한다. 실제 FPF rollout에서는 flow 상태와 시간과 carry가 함께 움직이므로, 식 (5)는 현재 상태를 고정해 바라본 해석이지 carry 생성 과정의 문자 그대로인 설명이 아니다. 고정점·끌개는 경험적 동역학을 설명하는 관점이며 contraction이나 정확성 보증을 제공하는 정리가 아니다.

## 5. 기존 reasoning 방법과 설계 근거

### 5.1 비교 축

| 접근 | 수정 가능한 상태 | FRM과의 차이 |
| --- | --- | --- |
| Autoregressive model | 이미 확정한 앞 token은 수정 불가 | FRM은 전체 clean prediction을 반복 갱신 |
| MDLM·Adaptive MDLM | mask 상태를 병렬 갱신 | FRM은 연속 flow와 self-conditioning carry 사용 |
| FMLM·FLM | 연속 flow로 이산 해 생성 | FRM은 clean prediction을 recurrent state로 되먹임 |
| HRM·TRM | 전용 recurrent architecture | FRM은 일반 denoiser의 조건 채널을 재사용 |
| FPRM·EqR | fixed-point·equilibrium reasoning | FRM은 canonical flow loss와 rollout carry를 결합 |

자기회귀, 확산·flow, 전용 recurrent reasoner는 architecture와 compute 단위가 다르다. 이 분류가 곧 같은 parameter budget이나 학습량을 뜻하지는 않으며, 논문도 Table 1의 model size와 Figure 5의 FLOP frontier를 따로 보고한다.

### 5.2 Conventional self-conditioning과 FPF

| 항목 | Conventional self-conditioning | Fixed-Point Forcing |
| --- | --- | --- |
| Carry 출처 | 같은 $x_t$에서 한 번 통과한 예측 | 앞선 시각에서 시작한 다단계 rollout의 예측 |
| 학습이 보는 상태 | one-pass state | inference-induced recurrent state |
| Loss-bearing state | target-derived canonical path | target-derived canonical path |
| Rollout 역전파 | 없음 | 없음 |
| 겨냥하는 문제 | 기본 예측 보조 | recurrent-depth exposure mismatch |

FPF의 실험적 장점은 구조와 loss를 함께 바꾼 복합 개입이 아니라, carry distribution을 바꾼 좁은 개입이라는 데 있다. 반면 FPF probability 0.5와 rollout depth 16을 묶어서 사용하므로 어느 설정이 얼마나 기여했는지는 분리되지 않는다.

### 5.3 설계 장치와 실패 양상

| 장치 | 막으려는 실패 | 작동 논리 |
| --- | --- | --- |
| Clean-prediction parameterization | 중간 상태를 해로 읽기 어려움 | 모든 carry를 직접 decode 가능한 후보 해로 만듦 |
| 별도 recurrent depth $k$ | flow step을 늘려야만 더 계산 가능 | 같은 flow time에서 후보 해를 반복 수정 |
| Rollout-derived carry | 깊은 추론에서 exposure bias 누적 | 학습 시 inference-induced state를 조건으로 제공 |
| Canonical loss path 유지 | 자기 생성 상태가 supervision을 오염 | 정답 기반 $x_t$에서만 CE loss 계산 |
| Stop-gradient carry | 긴 rollout 역전파 비용 | rollout을 supervision용 조건으로만 사용 |

## 6. 평가 설계와 비교 조건

### 6.1 세 과제와 데이터 규모

| 과제 | 구조 | 학습·평가 규모 | FRM 크기 |
| --- | --- | --- | ---: |
| Sudoku-Extreme | 9×9 제약 만족 | 시드당 train 1,000, fixed test 1,000 | 7M |
| Zebra | 3×3–6×6 관계 추론 | 약 train 1.5M, test 0.1M | 25M |
| Maze-Unique | 30×30 유일 경로 | train 1,000, test 1,000 | 8M |

Sudoku는 official split에서 난이도 균형 1,000개를 시드마다 뽑고 symmetry augmentation을 적용한다. Maze-Unique는 정답 경로가 유일해 exact-grid accuracy가 path validity와 optimality를 함께 나타낸다. 세 과제 모두 정답이 하나로 판정되는 구조형 퍼즐이라는 공통점이 있다.

### 6.2 학습 설정과 선택 절차

공통 backbone은 non-causal DiT이고 AdamW, gradient clip 1.0, EMA 0.9999, dropout 0.1을 사용한다. Stage A는 self-conditioning을 처음부터 학습하고, Stage B는 선택된 Stage-A weight에서 optimizer와 EMA를 새로 시작해 FPF를 적용한다.

| 설정 | Sudoku | Zebra | Maze |
| --- | ---: | ---: | ---: |
| Stage A / B iterations | 100K / 100K | 200K / 200K | 300K / 100K |
| Batch size | 128 | 128 | 64 |
| Learning rate | $3\times10^{-4}$ | $3\times10^{-4}$ | $1\times10^{-4}$ |

세 과제 모두 self-conditioning probability 0.5, FPF rollout probability 0.5, rollout depth 16, supervised states 4, noise scale 0을 사용한다. Table 2는 고정된 단일 inference setting의 단순 평균이 아니다. 각 seed에서 validation solve rate가 가장 높은 checkpoint와 sampler·NFE를 선택한 뒤 3시드 평균과 표본표준편차를 낸다.

### 6.3 네 종류의 결과를 구분하기

| 결과 | 의미 |
| --- | --- |
| Table 1 peak | 평가된 checkpoint·추론 구성에서 얻은 과제별 최고 정확도 |
| Table 2 mean±std | validation-selected 운영점의 3시드 평균·표준편차 |
| Figure 5 frontier | profile 가능한 checkpoint의 정확도–FLOPs 운영점 집합 |
| Figure 6 dynamics | Sudoku에서 recurrent depth에 따른 loss·해결률·residual AUROC |

Table 1의 published accuracy와 Figure 5의 profiled frontier는 출처가 다를 수 있다. compatible checkpoint가 없으면 공개 정확도가 표에는 있어도 frontier에서는 빠진다. 대시는 0점이 아니라 비교 가능한 값이 없다는 뜻이다.

### 6.4 FLOPs와 NFE가 세는 것

NFE는 learned-model update와 최종 readout을 센다. 부록이 설명하는 solved-puzzle mean NFE는 각 퍼즐이 처음 풀린 시점을 정답으로 확인해 평균하므로, ground truth가 필요한 oracle diagnostic이다. 일반적인 배포 시점 early stopping 비용으로 읽을 수 없다.

FLOPs는 batch-one forward pass를 operator-level counter로 측정한 뒤 실제 NFE를 곱한다. 메모리 이동, kernel·framework overhead, control flow, communication은 제외되므로 실제 경과시간이 아니라 산술 연산량의 하한이다.

## 7. 결과와 절제

### 7.1 과제별 최고 해결률

![세 과제 최고점](/api/blog/figures/frm-fig1-overview.png)

*그림 2. 왼쪽은 recurrent solution landscape의 개념도, 오른쪽은 Sudoku-Extreme의 정확도–FLOPs frontier. 출처: Helbling et al. (2026), Figure 1, [arXiv:2606.29150v3](https://arxiv.org/abs/2606.29150v3), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). 원문 도판을 블로그용으로 캡처·축소.*

Table 1의 peak exact-solve accuracy를 과제별로 비교한다. Size는 해당 과제에서 평가된 parameter 수다.

**Sudoku-Extreme**

| 방법 | 정확도(%) | Size |
| --- | ---: | ---: |
| FMLM | 1.0 | 7M |
| MDLM | 3.9 | 30M |
| ReMDM | 5.5 | 30M |
| FLM | 13.9 | 7M |
| Adaptive MDLM | 19.1 | 30M |
| HRM | 64.1 | 27.3M |
| TRM | 84.1 | 17.6M |
| FPRM | 94.2 | 7M |
| EqR | 98.7 | 5.03M |
| FRM | **99.5** | 7M |

Sudoku는 FRM의 핵심 주장이 가장 직접적으로 성립하는 과제다. 99.5%로 Table 1의 최고값이며 EqR의 98.7%를 넘어선다.

**Zebra**

| 방법 | 정확도(%) | Size |
| --- | ---: | ---: |
| FMLM | 74.2 | 25M |
| MDLM | 76.9† | 19M |
| FLM | 67.9 | 25M |
| Adaptive MDLM | 98.3† | 19M |
| FRM | **100.0** | 25M |

†는 기존 논문의 보고값이며 저자들이 자기 pipeline에서 재현하지 못한 값이다. FRM은 100.0%지만 높은 specialized reasoner 비교가 대부분 비어 있다. 저자들의 공개 가중치 기반 MDLM 재현은 49.2%에 머물렀고, 비교할 수 없는 조합은 0점이 아니라 대시로 처리했다.

**Maze-Unique**

| 방법 | 정확도(%) | Size |
| --- | ---: | ---: |
| FMLM | 87.5 | 8.1M |
| MDLM | 89.0 | 8M |
| ReMDM | 93.5 | 8M |
| FLM | 93.3 | 8M |
| Adaptive MDLM | **100.0** | 8M |
| HRM | 0.3 | 27.3M |
| TRM | 77.9 | 0.264M |
| FPRM | **100.0** | 7M |
| EqR | 93.0 | 2.6M |
| FRM | 99.9 | 8M |

Maze의 최고점은 FRM이 아니다. Adaptive MDLM과 FPRM이 100.0%, FRM이 99.9%다. 논문 본문도 이 차이를 명시한다. 따라서 “세 과제 모두 state of the art”라는 기여 문구는 Maze의 동률 최고 미달과 함께 읽어야 한다.

### 7.2 정확도–연산 frontier와 44배

![정확도–연산 프런티어](/api/blog/figures/frm-fig5-frontier.png)

*그림 3. Sudoku-Extreme·Zebra·Maze-Unique의 exact solve rate와 문제당 추론 FLOPs. 출처: Helbling et al. (2026), Figure 5, [arXiv:2606.29150v3](https://arxiv.org/abs/2606.29150v3), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). 원문 도판을 블로그용으로 캡처·축소.*

44배의 비교 상대는 Sudoku의 EqR이다. Figure 5에서 EqR의 최고 98.7%는 약 105 TFLOPs에 있고, FRM curve가 같은 정확도에 도달하는 지점은 두 측정점 사이를 로그축에서 보간하면 약 2.4 TFLOPs다. $105/2.4\approx43.7$이므로 반올림한 44배와 일치한다.

다만 분모는 FRM의 직접 측정 운영점이 아니라 곡선 보간값이고, 분자는 EqR의 가장 비싼 운영점이다. 정확도 기준을 낮추거나 다른 운영점을 택하면 비율도 바뀐다. 더구나 FLOPs는 메모리와 kernel overhead를 제외한 하한이므로 실제 경과시간 기준으로 44배 빠르다는 뜻이 아니다.

Maze에서는 FRM이 0.1 TFLOPs 아래 저연산 구간에서 강하지만, 연산량이 커지면 Adaptive MDLM이 같거나 조금 높은 운영점도 있다. 따라서 논문의 “measured frontier를 지배한다”는 표현은 저연산 영역에 한정하는 편이 정확하다.

### 7.3 FPF가 직접 바꾼 것

Table 2는 각 seed에서 validation solve rate가 가장 높은 checkpoint와 추론 구성을 고른 뒤 낸 3시드 평균과 표본표준편차다.

| 학습 방식 | Sudoku-Extreme | Zebra | Maze-Unique |
| --- | ---: | ---: | ---: |
| Base Flow | 13.1 ± 0.7 | 62.3 ± 29.1 | 77.6 ± 16.7 |
| + Self-conditioning | 32.6 ± 3.7 | 36.9 ± 18.0 | 96.2 ± 3.0 |
| + Fixed-Point Forcing | **99.2 ± 0.3** | **99.9 ± 0.2** | **98.0 ± 1.8** |

Table 2에서 Sudoku는 32.6→99.2, Maze는 96.2→98.0의 향상을 보인다. 구조·canonical 경로·목적함수는 유지하지만, Appendix A.2와 Table 3에 따르면 FPF는 선택한 Stage A 가중치에서 optimizer와 EMA를 새로 두고 추가 Stage B 학습을 수행한다. 동일한 추가 반복 수를 conventional self-conditioning으로 학습한 비교군이 없어, 이 차이를 carry 분포만의 효과로 분리할 수는 없다.

Zebra에서는 conventional self-conditioning이 Base Flow 62.3에서 36.9로 내려간다. 두 행 모두 seed variance가 커 원인을 분리하기 어렵다. 반면 FPF의 표준편차는 세 과제 모두 줄어든다. 특히 Zebra는 ±29.1에서 ±0.2, Maze는 ±16.7에서 ±1.8이다. 평균 향상뿐 아니라 학습 안정성의 변화가 Table 2에서 일관되게 보인다.

더 쉬운 Sudoku-Shah에서는 self-conditioning만으로 약 30%에서 99%까지 오른다고 논문이 서술한다. 표나 seed 정보는 없지만, 모든 문제에 FPF가 필수라는 주장 대신 난도가 높은 constraint problem에서 exposure mismatch가 중요하다는 범위를 제시한다.

### 7.4 깊이가 늘 때 손실과 수렴 신호는 어떻게 변하는가

![수렴과 정확성](/api/blog/figures/frm-fig6-convergence.png)

*그림 4. Sudoku-Extreme에서 recurrent depth에 따른 ground-truth loss, solve rate, adjacent-state residual의 정확성 AUROC. 출처: Helbling et al. (2026), Figure 6, [arXiv:2606.29150v3](https://arxiv.org/abs/2606.29150v3), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). 원문 도판을 블로그용으로 캡처·축소.*

Figure 6a에서 conventional self-conditioning의 정답 대비 cross-entropy는 깊이가 늘수록 약 1.8에서 5.4로 오른다. 예측이 안정돼 보이더라도 정답에서는 멀어지는 spurious fixed point 진단과 맞는다. FPF의 loss는 0에 가까워지고 solve rate는 계속 상승한다.

수렴 residual은 인접한 예측 분포 $p_k,p_{k-1}$ 사이의 token-averaged symmetric KL이다.

$$r_k=D_{\mathrm{SKL}}(p_k,p_{k-1})$$

이 residual로 정답 여부를 분류한 AUROC는 Base Flow 0.74, self-conditioning 0.50, FPF 1.00이다. FPF가 “수렴하면 맞을 가능성이 높다”는 관찰을 만든다는 근거다. 그러나 이 값은 Sudoku-Extreme diagnostic 하나이며 Zebra·Maze의 adaptive halting 성능이나 형식적인 correctness certificate를 뜻하지 않는다.

## 8. 결과가 뒷받침하는 범위

### 8.1 carry 분포와 추가 학습의 결합 효과

Table 2의 FPF 결과와 Figure 6의 깊이별 진단은 rollout 상태에 대한 학습의 유용성을 뒷받침한다. 다만 Stage B가 Sudoku·Zebra·Maze에서 각각 100K·200K·100K의 추가 학습 반복을 수행하므로, 이 절제는 carry 분포와 학습 예산을 동시에 바꾼다(Appendix A.2, Table 3). 모델 구조와 canonical 경로·endpoint CE를 유지했다는 사실만으로 계산량까지 통제한 인과적 분리는 성립하지 않는다.

### 8.2 핵심 주장을 할인해서 읽을 조건

| 핵심 주장 | 해석 경계 |
| --- | --- |
| Table 1의 99.5·100.0·99.9% | Maze의 최고점은 두 기준선의 100.0%다. |
| Figure 5의 Sudoku 44× | 측정점 사이 보간과 산술 연산량 하한에 의존한다. |
| Figure 6c의 residual AUROC 1.00 | Sudoku diagnostic이며 형식적인 정확성 보증이 아니다. |
| Table 2의 세 과제 향상 | seed마다 checkpoint·sampler·NFE를 validation으로 선택한다. |
| Figure 6의 반복 깊이 scaling | flow time과 depth의 분리는 held-state 해석이다. |

논문의 첫 동기는 자기회귀 모델이 앞 결정을 수정하지 못한다는 것이다. Appendix A.3은 plain causal decoder 기준선까지 정의하지만 Table 1과 Figure 5에는 자기회귀 결과가 없다. 따라서 FRM이 실제로 직접 비교한 상대는 diffusion·flow와 specialized recurrent reasoner다.

## 9. 결론

Flow Reasoning Model의 핵심은 새로운 전용 추론 아키텍처보다 **되먹임 가능한 노이즈 제거 예측 상태**에 있다. denoiser의 출력을 후보 해와 flow 갱신에 함께 사용해 flow 시간과 별도의 반복 깊이를 만들고, Fixed-Point Forcing으로 학습 때의 carry를 실제 rollout 상태에 맞춘다.

가장 직접적인 근거는 FPF 절제와 Figure 6의 깊이별 loss·AUROC 변화다. 추가 Stage B 학습과 carry 분포 변경이 함께 적용돼 평균 향상과 seed variance 감소에서 각각의 기여를 분리할 수는 없다. 반면 계산 효율 주장은 운영점 선택과 FLOP 하한에 의존하고, 수렴은 정확성의 형식 보증이 아니다.

따라서 이 논문은 고정점 추론을 증명했다기보다, **자기 생성 반복 상태를 학습에 노출하면 깊은 self-conditioning을 생산적인 계산으로 바꿀 수 있다**는 경험적 결과로 읽는 편이 정확하다. 더 크고 덜 구조화된 문제에서 같은 거동이 유지되는지는 후속 검증에 달려 있다.

---


## References

- Helbling, A., Bryutkin, A., Martino, M., Chau, D. H., Dehmamy, N., & Strobelt, H. (2026). *Flow reasoning models: Turning flows into efficient recurrent reasoners* (arXiv:2606.29150v3). arXiv. https://arxiv.org/abs/2606.29150
- Chen, T., Zhang, R., & Hinton, G. (2023). *Analog bits: Generating discrete data using diffusion models with self-conditioning* (arXiv:2208.04202). arXiv. https://arxiv.org/abs/2208.04202
- Huang, B., Geng, Z., & Kolter, Z. (2026). *Equilibrium reasoners: Learning attractors enables scalable reasoning* (arXiv:2605.21488). arXiv. https://arxiv.org/abs/2605.21488
- Huang, X., Li, Z., He, G., Zhou, M., & Shechtman, E. (2025). *Self forcing: Bridging the train-test gap in autoregressive video diffusion* (arXiv:2506.08009). arXiv. https://arxiv.org/abs/2506.08009
- Jolicoeur-Martineau, A. (2025). *Less is more: Recursive reasoning with tiny networks* (arXiv:2510.04871). arXiv. https://arxiv.org/abs/2510.04871
- Kim, J., Shah, K., Kontonis, V., Kakade, S., & Chen, S. (2025). *Train for the worst, plan for the best: Understanding token ordering in masked diffusions* (arXiv:2502.06768). arXiv. https://arxiv.org/abs/2502.06768
- Lee, C., Yoo, J., Agarwal, M., Shah, S., Huang, J., Raghunathan, A., Hong, S., Boffi, N. M., & Kim, J. (2026). *Flow map language models: One-step language modeling via continuous denoising* (arXiv:2602.16813). arXiv. https://arxiv.org/abs/2602.16813
- Lipman, Y., Chen, R. T. Q., Ben-Hamu, H., Nickel, M., & Le, M. (2023). Flow matching for generative modeling. *International Conference on Learning Representations*. https://openreview.net/forum?id=PqvMRDCJT9t
- Movahedi, S., Milovanović, V., Feigin, S. L., Theus, A., Hofmann, T., Boeva, V., Rusch, T. K., & Orvieto, A. (2026). *Fixed-point reasoners: Stable and adaptive deep looped transformers* (arXiv:2606.18206). arXiv. https://arxiv.org/abs/2606.18206
- Sahoo, S. S., Arriola, M., Schiff, Y., Gokaslan, A., Marroquin, E., Chiu, J. T., Rush, A., & Kuleshov, V. (2024). *Simple and effective masked diffusion language models* (arXiv:2406.07524). arXiv. https://arxiv.org/abs/2406.07524
- Shah, K., Dikkala, N., Wang, X., & Panigrahy, R. (2024). *Causal language modeling can elicit search and reasoning capabilities on logic puzzles* (arXiv:2409.10502). arXiv. https://arxiv.org/abs/2409.10502
- Wang, G., Li, J., Sun, Y., Chen, X., Liu, C., Wu, Y., Lu, M., Song, S., & Abbasi Yadkori, Y. (2025). *Hierarchical reasoning model* (arXiv:2506.21734). arXiv. https://arxiv.org/abs/2506.21734
- Wang, G., Schiff, Y., Sahoo, S. S., & Kuleshov, V. (2025). Remasking discrete diffusion models with inference-time scaling. *Advances in Neural Information Processing Systems, 38*, 147282–147339.
- Yoo, J., Kim, W., Eijkelboom, F., Lee, C., Boffi, N. M., Hong, S., & Kim, J. (2026). *Self-conditioned flow map language models via fixed-point flows* (arXiv:2607.00714). arXiv. https://arxiv.org/abs/2607.00714
