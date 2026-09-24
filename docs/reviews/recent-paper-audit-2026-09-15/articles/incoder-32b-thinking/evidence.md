# InCoder-32B-Thinking 근거·수정 기록

근거: [arXiv:2604.03144v1](https://arxiv.org/abs/2604.03144v1), 2026-04-03, 25쪽. 새 PDF의 `source.txt`와 해시를 보존했다. 이전 비판 기록은 참고하되, 실제 원문에서 확정되는 범위로 비판을 재판정했다.

## Evidence ledger

| claim | source anchor | evidence type | confidence | notes |
| --- | --- | --- | --- | --- |
| DeepSeek-V3.2가 실제 오류 피드백으로 수정 궤적 생성 | §2.2, pp.4–5 | paper-reported | high | K=4 correction rounds |
| 전체 궤적은 코드 모델, 개별 턴은 ICWM 학습에 사용 | §2.2 마지막 문단, p.5 | paper-reported | high | 새 학습 신호 표 |
| ICWM 입력 환경/코드, 출력 라벨/진단/수치 | Eq.2, p.5 | paper-reported | high | 별도 명시 인과 구조 주장 안 함 |
| every real turn과 hold out 2,000 서술 공존 | §§2.3,4.1, pp.5,9 | paper-reported | high | 실제 오염 증거로 단정하지 않음 |
| 조건부 G-exe가 G-call 15.2와 G-exe100에 일관됨 | Table 5; App.A.2.2, p.24 | direct inference from setup | medium | 분모 정의는 미명시, 확정 철회 |
| 360M→540M은 1.5배 | §4.3; Figure 7 | direct inference from setup | high | 두 번째 배증 오기 교정 |
| 자기 벤치마크 1위 부재는 편향 부재의 증거가 아님 | Tables 4–5; 평가 설계 | direct inference from setup | high | 기존 리뷰의 논리 오류 철회 |
| 모델 크기만으로 낮은 baseline 점수를 오류라 할 수 없음 | Tables 1–3 | direct inference from setup | high | 기존 추측 삭제 |
| 두 체크포인트는 데이터량도 다름 | §4.3, p.11 | paper-reported | high | thinking 순효과라는 명명 완화 |

## Method map

| component/step | role | input/output | assumption | source anchor |
| --- | --- | --- | --- | --- |
| Seed/environment | 실행 가능한 과제 구성 | 이전 자산→과제+툴체인 환경 | 테스트벤치·설정 필요 | §2.1 |
| ECoT | 오류-수정 경험 생성 | reasoning/code→실행→진단→수정 | generator 및 실제 백엔드 | §2.2 |
| ICWM 학습 | 실행 피드백의 대리 모델 | 개별 코드·환경→실행 결과 | 라벨/진단 품질 | Eq.2 |
| ICWM 합성 | 실행 호출을 예측으로 대체 | 예측 피드백→추가 궤적 | 오류 누적·감사 | Eq.3 |
| 최종 코드 모델 | 수정 추론 학습 | Dreal∪Dicwm | 기여별 절제 없음 | §§2.2–2.3 |

## Result table

| result claim | metric/dataset/setup | exact value | comparator | source anchor | caveat |
| --- | --- | --- | --- | --- | --- |
| 코드 추론 | LiveCodeBench V5 | 81.3 | instruct53.3 | Table 2 | +28.0pp, 약52.5% 상대 상승 |
| SWE | SWE-bench Verified | 70.4 | instruct74.8 | Table 3 | −4.4pp |
| GPU | KernelBench L1/L2/L3 | 20.2/38.0/12.0 | 22.2/36.0/14.0 | Table 5 | fast1, 혼합된 방향 |
| CAD | Compile/IoU | 84.0/48.6 | 82.0/53.5 | Table 5 | 실행/기하 지표 분리 |
| ICWM | outcome/trajectory agreement | 평균96.7/94.4 | real execution | §4.1; Figure 5 | 성능 향상의 절제 아님 |
| 데이터 규모 | 사고 학습 | 180M/360M/540M | instruct250M | §4.3 | 마지막 구간 배증 아님 |
| 모순 유지 | EmbedCGen | Table5 47.9 vs Figure2 51.0 | Figure7 추정최종51.0 | 원문 표/그림 | 어느 값을 정답이라 확정하지 않음 |

## Critique log

| critique | label | action | reason | final prose location |
| --- | --- | --- | --- | --- |
| every/holdout은 둘 다 성립 불가, 평가 오염 암시 | speculative | softened | 일반 서술 생략일 수 있음; split evidence 없음 | §3.1 |
| ICWM은 순전파 한 번이므로 일정 저비용 | direct inference from setup | softened | 텍스트 예측 비용·측정 가속 분리 | §3.2 |
| 두 학습 대상과 supervision 경로 혼동 | paper-evidenced | accepted | 전체 궤적/개별 턴 구분 | §3.3 |
| 1위가 아니므로 자체 평가 편향 없음 | speculative | rejected | 순위로 판정 불가 | §4.2 |
| 큰 모델의 낮은 점수는 평가 이상 | speculative | rejected | 크기만으로 판단 불가 | §§5,9.2 |
| G-exe 분모가 확정됨 | direct inference from setup | softened | 일관된 해석이나 문서 미명시 | §§8.2,9.4 |
| 360M→540M 두 번째 배증 | paper-evidenced | accepted | 1.5배 | §8.2 |

## Final verification note

주요 표의 체크포인트 차이와 새 학습 경로를 원문과 대조했다. 기존 결과의 상충 수치를 남기되 추정 원인을 확정하지 않는다. 그림 URL을 보존한다. 모델·툴체인 실행 재현은 하지 않았다.
