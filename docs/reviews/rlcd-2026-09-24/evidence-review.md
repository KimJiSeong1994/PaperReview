# RLCD 원문 근거 검토 장부

검토일: 2026-09-24
대상 초안: `/Users/jiseong/Library/Mobile Documents/com~apple~CloudDocs/PaperWiki/PaperWiki/blog/alignment/rlcd/rlcd-deep-review.md`
원문 기준: Kevin Yang et al., *RLCD: Reinforcement Learning from Contrastive Distillation for Language Model Alignment*, [arXiv:2307.12950v3](https://arxiv.org/abs/2307.12950v3), 2024-03-16, arXiv 표기상 ICLR 2024. 본 검토는 원문 v3의 표·부록을 대조한 문헌 검증이며 재학습이나 독립 재현은 하지 않았다.

## Retrieval sufficiency / source provenance

- **1차 근거:** [arXiv v3 HTML](https://arxiv.org/html/2307.12950v3)과 [v3 PDF](https://arxiv.org/pdf/2307.12950v3). 방법(§3), 실험·주표(§4), 분석(§5), 부록 A–N을 확인했다.
- **기준선 원전:** Bai et al., [*Constitutional AI: Harmlessness from AI Feedback*](https://arxiv.org/abs/2212.08073) (arXiv:2212.08073v1, 2022-12-15). RLCD 부록 C가 이 원전의 few-shot 프롬프트를 직접 사용했다고 명시하므로, 주 비교와 few-shot 추가 비교의 차이를 확인하는 데 충분하다.
- **버전 주의:** 아래 수치와 문구는 2024-03-16 v3에만 귀속한다. 2026-09-24 현재 arXiv의 최신판도 v3로 표시되지만, 후속 구현·재현 결과를 이 장부에 섞지 않았다.

### Official repository scope (supplemental source-reference evidence)

- 원문이 가리키는 `facebookresearch/RLCD`는 **2023-08-18 이후 push가 없는 archived MIT repository**다. 확인한 마지막 main commit은 `fac0b8fe2284637bdb5ffa11a3e3df136952d288`이다. 따라서 “2026년에도 유지되는 구현”이라고 쓰면 안 된다.
- repository는 재현 코드·AlpacaFarm 패치·시뮬레이션/보상모델/PPO/출력 생성 절차를 제공한다. `facebookresearch/RLCD@fac0b8fe2284637bdb5ffa11a3e3df136952d288:README.md:L7-L24`
- 공개 `simulated_data.zip`은 **harmlessness와 helpfulness 실험 데이터만** 담고, outline prompt는 법적 사유로 생략됐다. 따라서 기존 초안의 “코드와 시뮬레이션 선호 데이터가 공개”는 “코드와 무해성·도움성의 시뮬레이션 데이터가 공개되었고, 개요 프롬프트는 미공개”로 좁혀야 한다. `facebookresearch/RLCD@fac0b8fe2284637bdb5ffa11a3e3df136952d288:README.md:L24-L30`

## Method map

| 요소 | 원문이 실제로 한 일 | 초안에 쓸 때의 경계 |
| --- | --- | --- |
| RLCD | 각 원 프롬프트 `p`에서 속성을 부추기거나 거스르는 `p+`, `p-`를 만들고 `o+`, `o-`를 생성한다. `o+`를 추가 채점 없이 선호로 자동 라벨한 뒤, 같은 무정렬 LLM 기반 preference/reward model과 PPO를 사용한다. [§3.1](https://arxiv.org/pdf/2307.12950v3#page=3) | ‘정답을 보장’하는 라벨이 아니라 프롬프트 출처로 정한 구성 라벨이다. 긍정/부정 프롬프트가 목표 속성에서 실제로 얼마나 분리되는지가 전제다. |
| 프롬프트 설계 | `p+`가 목표 속성을 더 낼 가능성과, 두 프롬프트 표면형이 최대한 비슷할 것을 요구한다. 원문은 후자를 더 중시할 수 있다고 쓴다. [§3.2](https://arxiv.org/pdf/2307.12950v3#page=4) | “직교 축의 편향을 없앤다”가 아니라 **줄이려는 설계 기준**이다. |
| RLAIF 주 기준선 | 같은 `p`에서 i.i.d. 출력 두 개를 만들고 LLM의 사후 채점으로 선호를 얻는 재구현이다. RLCD 주 실험은 공정성 맞춤을 위해 **zero-shot** 채점을 썼다. [§4](https://arxiv.org/pdf/2307.12950v3#page=6) | 원래 Constitutional AI의 RL 단계는 두 응답을 원칙에 따라 비교시키며, few-shot 예를 사용하는 체계를 포함한다. [원전 §1.2](https://arxiv.org/html/2212.08073#S1.SS2) 주 기준선은 그 원전을 그대로 복제한 것이 아니다. |
| 7B/30B의 뜻 | 모든 downstream 정렬 정책은 base **LLaMA-7B**다. 첨자 `7B/30B`는 선호 데이터를 시뮬레이션한 base LLaMA 크기이며, 30B→7B는 저자도 model distillation으로 볼 수 있다고 명시한다. [§4](https://arxiv.org/pdf/2307.12950v3#page=5) | “30B 정책과 7B 정책의 대결”이라고 쓰면 틀린다. |
| Context-Dist | RLCD의 동일한 `p+`에서 얻은 `o+`만으로 supervised fine-tuning을 한다. [§4](https://arxiv.org/pdf/2307.12950v3#page=6) | preference model/PPO가 없으므로 RLCD와의 차이는 ‘대비 프롬프트’ 하나만이 아니다. |

## Result ledger

### 주 평가 설계

- 사람: 각 쌍 비교마다 200 예제, 1(A가 훨씬 좋음)–8(B가 훨씬 좋음) 척도. 순서를 무작위화하고, 표의 두 점수는 사후 정규화되어 합이 9가 된다. [§4 및 Table 2](https://arxiv.org/pdf/2307.12950v3#page=6)
- GPT-4: 각 쌍 비교 1,000 예제의 이진 판정. 파싱 실패·거부는 양쪽 0.5점으로 처리한다. [§4](https://arxiv.org/pdf/2307.12950v3#page=6), [Appendix F.2](https://arxiv.org/pdf/2307.12950v3#page=19)
- 무해성 프롬프트에서는 Harm와 Help를 모두 잰다. 도움성 프롬프트는 Help, 개요 프롬프트는 Qual 하나를 잰다. [§4](https://arxiv.org/pdf/2307.12950v3#page=5)

### RLCD 대 RLAIF: 반드시 숫자 그대로 남길 결과

값은 `RLCD / RLAIF`다. H-Harm=무해성 프롬프트의 무해성, H-Help=같은 프롬프트의 도움성, Help=도움성 과제, Qual=개요 품질이다.

| 선호 데이터 시뮬레이터 | 평가 | H-Harm | H-Help | Help | Qual | 원문 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 7B | 사람 | 5.62 / 3.38 | 4.64 / 4.36 | 5.88 / 3.12 | 5.97 / 3.03 | [Table 2](https://arxiv.org/pdf/2307.12950v3#page=6) |
| 7B | GPT-4 | 84.8 / 15.2 | 71.0 / 29.0 | 85.4 / 14.6 | 78.5 / 21.5 | [Table 3](https://arxiv.org/pdf/2307.12950v3#page=6) |
| 30B | 사람 | 4.71 / 4.29 | 4.50 / 4.50 | 4.51 / 4.49 | 4.76 / 4.24 | [Table 2](https://arxiv.org/pdf/2307.12950v3#page=6) |
| 30B | GPT-4 | 60.3 / 39.7 | 55.3 / 44.7 | **47.8 / 52.2** | **35.9 / 64.1** | [Table 3](https://arxiv.org/pdf/2307.12950v3#page=6) |

### 분석·보조 표의 검증 포인트

| 주장/수치 | 판정 | 근거와 정확한 해석 |
| --- | --- | --- |
| RLAIF7B의 preference model 무해성 정확도 35.6%, RLCD7B 52.4%; 30B는 45.7%, 55.9% | 확인 | 2,000개 gold human-labeled preference 예제에 대한 **average binary prediction accuracy**다. RLCD도 무해성 절대 정확도는 50% 조금 위에 머문다. [Table 5](https://arxiv.org/pdf/2307.12950v3#page=8) |
| RLCD-Rescore는 7B에서 크게 뒤지고, 30B에서는 viable alternative | 확인 | 30B RLCD/RLCD-Rescore는 54.6/45.4, 53.2/46.8, 47.3/52.7, 36.4/63.6이다. ‘사후 채점이 따라잡는다’는 과제별 결과이며, 전면적 우위 전환은 아니다. [Table 6](https://arxiv.org/pdf/2307.12950v3#page=8) |
| Few-shot RLAIF30B는 무해성에서 RLCD30B를 이긴다 | 확인 | GPT-4에서 Harm 42.1/57.9, Help 56.9/43.1. 원문도 RLCD가 zero-shot이므로 이 비교가 RLCD에 다소 불리하다고 쓴다. [Appendix C, Table 16](https://arxiv.org/pdf/2307.12950v3#page=16) |
| RLCD7B 출력이 RLAIF7B보다 길다 | 확인 | Harm 66.5 vs 42.1, Help 118.0 vs 35.4, Qual 115.9 vs 54.8 tokens. 30B에서는 73.3 vs 78.1, 108.3 vs 84.7, 138.7 vs 88.6이다. 최대 300 tokens 외 길이 제한은 없었다. [Appendix J.4, Tables 34–35](https://arxiv.org/pdf/2307.12950v3#page=37) |
| 인간–GPT-4 불일치는 30B RLAIF 비교의 Help/Qual에서 크다 | 확인 | 일치율은 62.8%, 59.0%; 단, GPT-4가 명확히 선호하지 않은 예제는 제외했다. [Appendix G, Table 23](https://arxiv.org/pdf/2307.12950v3#page=21) |

## Critique log

### Paper-evidenced (원문이 직접 말하거나 표가 직접 보이는 것)

1. **결과 첫 문장과 Table 3의 범위가 맞지 않는다.** 본문은 사람과 GPT-4 모두에서 모든 baseline을 이겼다고 쓴다. 바로 그 Table 3에는 RLCD30B가 RLAIF30B에 Help 47.8/52.2, Qual 35.9/64.1로 진 행이 있다. 다음 문장은 GPT-4가 일부 경우 RLAIF30B를 선호했다고 한정한다. 따라서 초안은 이를 “후속 문장이 한정을 제공하지만, 첫 문장은 표의 GPT-4 두 패배와 문자 그대로 양립하지 않는다”로 써야 한다. [§4, Table 3](https://arxiv.org/pdf/2307.12950v3#page=7)

2. **`relatively equal`은 저자의 캡션 표현이지 수치 판단이 아니다.** Table 3 캡션이 RLCD30B–RLAIF30B를 예외적 ‘relatively equal’로 부른다. 35.9/64.1도 같은 묶음에 있다. “28.2점 차를 덮는다”는 평가는 해설자의 편집 판단으로 표시해야 한다. [Table 3](https://arxiv.org/pdf/2307.12950v3#page=6)

3. **주 RLAIF는 zero-shot이고 few-shot 결과는 별도 부록이다.** 이것은 중요한 범위 조건이다. 다만 few-shot RLAIF30B가 보인 무해성 우위는 동시에 ‘generic harmless but meaningless’ 출력의 heavy mode collapse라는 저자의 정성적 진단과 묶여 있다. 무해성 값 하나만으로 방법의 총체적 우열을 선언하면 안 된다. [Appendix C](https://arxiv.org/pdf/2307.12950v3#page=15)

4. **길이 차이는 관측됐지만 길이-매칭 평가는 보고되지 않았다.** 원문은 길이를 공개하고 긴 응답이 Help/Qual 기준을 더 충족할 수 있다는 해석을 제시한다. 대조 길이로 재생성하거나 길이 보정한 선호 평가는 원문에 없다. [Appendix J.4](https://arxiv.org/pdf/2307.12950v3#page=37)

5. **모드 붕괴를 가리는 지표가 완전히 대칭적이지 않다.** RLCD7B harmlessness의 Dist-1/2/3은 11.0/42.5/66.4이고 저자는 반복적 거절 탓이라고 한다. RLAIF-Few30B의 heavy mode collapse는 예시 출력으로 진단했으며 같은 diversity 표를 제시하지 않았다. 동일 척도 비교는 아니다. [Appendix J.3](https://arxiv.org/pdf/2307.12950v3#page=36), [Appendix C](https://arxiv.org/pdf/2307.12950v3#page=16)

6. **이론은 제한된 생성·판별 모형의 정당화다.** Appendix N은 단일 실수 속성, 대략 단봉의 정규 분포, 독립 정규 잡음, 그리고 예시에서 `sigma_G=sigma_D=1`을 둔다. 이 가정 아래 RLAIF 라벨 정확도 0.75, hard subset에서 약 0.528, `mu(p+)-mu(p-)=3`인 RLCD hard subset에서 0.574를 계산한다. 이는 실제 표의 30B 원인을 입증하는 분석이 아니다. [Appendix N](https://arxiv.org/pdf/2307.12950v3#page=39)

### Direct inference (원문 수치에서 가능한, 그러나 저자가 인과로 입증하지 않은 해석)

1. **길이는 잠재적 교란이지만 결과 전체를 설명하지 못한다.** 7B에서 Help의 길이비는 약 3.33, Qual 약 2.12, Harm 약 1.58이고 GPT-4 승률 순서는 Help > Harm > Qual이다. 30B에서는 RLCD가 Help·Qual에서 더 길어도 GPT-4에 진다. 따라서 “길이가 이득 전부를 만들었다”는 결론은 지지되지 않으며, “길이 보정이 없어서 기여도를 분리할 수 없다”가 적절하다.

2. **30B 결과는 방법의 일반적 우위보다 모델·과제 조건부 결과로 읽어야 한다.** 사람 평가는 동률 이상이지만 GPT-4는 두 과제에서 RLAIF를 선호한다. 두 평가자의 불일치도 같은 두 칸에서 가장 크다. 어느 평가자가 정답인지는 이 논문만으로 판정할 수 없다.

3. **원전과 맞춘 few-shot baseline은 주 표의 격차 크기를 재평가하게 한다.** 그러나 few-shot configuration은 RLCD와 생성 프롬프트 형식이 다르며 mode collapse도 관찰됐으므로, 이것은 “RLCD가 패배했다” 이상의 단순한 공정성 판결은 아니다.

### Speculative / 삭제 또는 명시적 가설화가 필요한 표현

1. “30B 표의 하락은 동일 `p+`/`p-` 강도를 쓴 탓이다”는 **가설**이다. 저자는 큰 모델에서 `mu` 차를 줄이는 편이 나을 *수 있다*고 전향적으로 제안할 뿐, 30B 표의 원인을 진단하지 않았다. [Appendix N](https://arxiv.org/pdf/2307.12950v3#page=40)

2. “사람 평가가 길이를 선호했기 때문에 RLCD가 이겼다”는 **미검증 인과 주장**이다. 길이 차이와 평가 설계만으로는 성립하지 않는다.

3. “35.6% preference-model accuracy가 PPO hyperparameter 선택을 망쳐 RLAIF7B 결과를 만들었다”는 **가설**이다. 원문은 방법별 reward model로 hyperparameter를 고른 사실을 보고하지만, 이 매개 경로를 실험하지 않았다.

4. Appendix K.1의 0.44–0.74를 “사람과의 직접 라벨 일치”라고 쓰면 부정확하다. 이는 **human preference data로 학습한 held-out reward model**에 따른 label accuracy다. [Appendix K.1](https://arxiv.org/pdf/2307.12950v3#page=38)

## 수정 필수 사항 (발행 전)

1. 7B/30B를 **선호 데이터 시뮬레이터의 크기**로 일관되게 쓰고, 최종 정렬 정책은 전 조건 LLaMA-7B라고 명시한다.
2. 인간 평가는 ‘승률’이 아니라 1–8 비교 판단을 9점 합으로 정규화한 점수라고 명시한다. 4/5는 동점 옵션이 아니므로 “완전 동률”은 **집계 정규화 수치가 4.50/4.50**이라는 뜻으로만 쓴다.
3. “RLCD가 30B에서도 GPT-4로 모든 baseline을 이김” 계열 문구를 삭제한다. Help·Qual의 두 패배와 사람–GPT-4 불일치를 같은 단락에 둔다.
4. RLAIF 주 비교에는 `zero-shot reimplementation`; Appendix C에는 `few-shot RLAIF, only harmlessness task`를 붙인다. 원전의 full Constitutional AI pipeline과 동치라고 부르지 않는다.
5. 길이 비판은 “잠재적 교란·미분리”로 제한하고, 길이가 모든 효과를 설명한다는 인과 문장은 제거한다. 300-token cap과 표의 실제 길이도 함께 제시한다.
6. 이론 숫자(0.75/0.528/0.574)는 실제 측정치가 아닌 **정규-잡음 단순 모형의 계산**이라고 표시한다. 30B 실패 원인으로 단정하지 않는다.
7. reference metadata는 Yang, Klein, Celikyilmaz, Peng, Tian; ICLR 2024; arXiv:2307.12950v3; last revised 2024-03-16으로 통일한다. “40쪽”은 PDF 레이아웃 정보라 인용에 필수 정보는 아니며, 필요하면 v3 PDF의 페이지 수로만 표기한다.

## Reusable takeaway

RLCD의 검증된 핵심은 **같은 프롬프트에서 i.i.d. 두 출력을 채점하는 대신, 대비 프롬프트 두 분포에서 출력을 얻어 구성 라벨을 만드는 설계**다. 이 설계는 LLaMA-7B 시뮬레이션에서 강한 결과를 보였고, 30B에서는 인간 집계 평가는 동률 이상이나 GPT-4는 두 과제에서 RLAIF를 선호했다. 그러므로 논문의 실증 주장은 “7B에서 뚜렷하고 30B에서는 평가자·과제 의존적”으로 제한하는 것이 원문에 가장 충실하다.
