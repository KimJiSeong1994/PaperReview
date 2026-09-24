# WikiProfile 근거·수정 기록

근거: [arXiv:2602.14080v2](https://arxiv.org/abs/2602.14080v2), 2026-06-19 개정본. 새로 내려받은 65쪽 PDF의 텍스트·해시를 저장했다. 방법의 존재/전칭 조건과 profile 집계가 독자에게 실제로 어떻게 적용되는지 보강한다.

## Evidence ledger

| claim | source anchor | evidence type | confidence | notes |
| --- | --- | --- | --- | --- |
| Encoding은 두 과제 중 하나, knowledge는 QA 모두의 성공 | §2.1, pp.3–4 | paper-reported | high | 가상 예시에 적용 |
| 성공 문턱은 g(q) > .5 | §2.1 | paper-reported | high | 4/8은 실패, 5/8은 성공 |
| g(q)는 correct/(correct+incorrect) | §2.1 | paper-reported | high | PARTIALLY/OTHER 제외 |
| 분모 0은 NaN이며 선택 규칙에 따라 처리 | Appendix D.1; Table 2 Selected | paper-reported | high | 0점으로 임의 대체하지 않음 |
| Direct Recall은 thinking 없는 knowledge 성공으로 판정 | §2.2 | paper-reported | high | thinking 성공을 조건으로 요구하지 않음 |
| thinking knowledge 집계와 성공 profile 합은 자동으로 같지 않다 | §2.2; Table 2 | direct inference from setup | high | 같은 사실의 thinking 퇴행 가능성·집계 구분 |
| 정방향은 원문 개체 등장 순서에 의존한다 | §2.1 | paper-reported | high | 사전학습 방향 직접 관찰 아님 |
| Encoding은 행동적 검사이며 내부 저장 직접 측정 아님 | §2; §7 | paper-reported | high | 기존 한정 유지 |

## Method map

| component/step | role | input/output | assumption | source anchor |
| --- | --- | --- | --- | --- |
| 사실 구성 | 양방향 질문 가능한 사실 선택 | Wikipedia→2,150 facts | 생성·필터링 조건 | §3; App.A |
| Encoding | 문맥 복원 측정 | left context→두 과제 | thinking off | §2.1 |
| Knowledge | 질의 변화에 대한 안정성 | 4 QA→K0, KT | 채점기·문턱 | §2.1 |
| Recognition | 후보가 주어질 때 구별 | 4 MCQ→정방향/역방향 비교 | 보기 순서 균형 | §3–4 |
| Profile | 사실별 실패 구성 | E,K0,KT→5 profile | 제외 규칙 | §2.2; App.D.1 |

## Result table

| result claim | metric/dataset/setup | exact value | comparator | source anchor | caveat |
| --- | --- | --- | --- | --- | --- |
| 높은 encoding | Table 2 Selected | Gemini-3-Pro 98.1; GPT-5 95.3 | Direct Recall 72.2/61.6 | Table 2 | 세계 지식의 비율 아님 |
| recall failure | 같은 집계 | 10.9/12.2 | 위 두 모델 | Table 2 | conditional recall rate와 분모 다름 |
| popularity | GPT-5 high/low 20% | encoding 98.4/90.7; recall 77.8/52.9 | 인기 구간 | Figure 5 | 페이지 조회수는 학습 빈도 아님 |
| generation vs recognition | GPT-5 no thinking | 83.0/74.0 vs 86.0/90.7 | 정방향/역방향 | Figure 6 | 내부 대칭 표현의 증명 아님 |
| thinking recovery | encoded-but-not-known | 약 40–65% | native thinking 모델군 | §5.3; Figure 8 | 전체 정확도 %p가 아님 |
| 채점기 일치 | 4,160응답 | 98.2% | Gemini/GPT 채점기 | App.D.3 | 인간 정답률 아님 |
| 표현 검정 | FDR 보정 | 104 tests에서 유의차 미발견 | 원문/재표현 | App.C.3 | 동등성 증명 아님 |

## Critique log

| critique | label | action | reason | final prose location |
| --- | --- | --- | --- | --- |
| 수식만으로 엄격한 문턱 의미가 불명확 | direct inference from setup | accepted | 6/8,3/8과 7/8,6/8,5/8,4/8을 가상 예시로 명시 | §3.2 |
| 전부 비채점이면 0점이라고 읽을 수 있음 | paper-evidenced | accepted | NaN/Selected 규칙 설명 | §3.2 |
| thinking을 켜면 기존 성공이 항상 유지된다고 가정 | direct inference from setup | accepted | Direct Recall 정의는 KT를 조건으로 쓰지 않음 | §6.2 |
| 재인 성공으로 내부 대칭 기억을 입증 | speculative | rejected | 행동적 평가만 수행 | 기존 한정 유지 |

## Final verification note

새 숫자는 실험 결과가 아닌 정의 설명용 가상 예시임을 명시했다. 실제 결과 표의 수치는 원문 Selected/Figures와 대조했다. 기존 도판과 CC BY-SA 표기를 보존한다. 반복 응답을 새로 생성한 검증은 아니다.
