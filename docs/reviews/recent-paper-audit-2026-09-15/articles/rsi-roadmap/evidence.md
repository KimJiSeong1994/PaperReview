# RSI Roadmap 근거·수정 기록

근거: [arXiv:2609.11873v1](https://arxiv.org/abs/2609.11873v1), 2026-09-10, 75쪽, 33명 저자. PDF 다운로드·해시·텍스트 추출을 새로 수행했다. DGM 서지는 [arXiv v3](https://arxiv.org/abs/2505.22954v3)로 대조했다. 프로젝트 페이지 접근은 가능했지만 읽을 수 있는 본문이 추출되지 않아 데이터 공개 여부를 판정하지 않는다.

## Evidence ledger

| claim | source anchor | evidence type | confidence | notes |
| --- | --- | --- | --- | --- |
| first-party values에 .75 가중 | §2.1, p.8 | paper-reported | high | primary source와 다른 말; 자기 보고값으로 교정 |
| HCI = 100(s−F0)/(100−F0) | Eq.2, p.8 | paper-reported | high | 원점수/능력의 직접 비교 아님 |
| F0=60,s=80이면 H=50; F0=20이면 H=75 | Eq.2 대입 | direct inference from setup | high | 가상 예시로 표시, 논문 데이터 아님 |
| √n으로 benchmark family의 frontier를 집계 | Eq.3, p.8 | paper-reported | high | 원래 설명 유지 |
| B0는 지속적 시스템 변경 없이 현재 출력만 개선 | §3.1, p.12 | paper-reported | high | 코딩 예시 추가 |
| L1–L5는 이전되는 개선 책임으로 분류 | §§2.2,3.7 | paper-reported | high | 특정 제품 등급으로 주장하지 않음 |
| 구조적 재귀와 실효적 재귀를 구분 | §3.6, pp.31–35 | paper-reported | high | 성능/자율성 독립성 유지 |
| 2026 이후 확장은 측정이 아닌 illustrative | Figure 3; Eq.4 | paper-reported | high | 인용 자체 금지 문장을 의미 제한으로 수정 |
| 작은 산술 차이는 반올림으로 설명 가능하나 원인은 미확인 | §2.1; Table 9 | direct inference from setup | high | 반올림 원인 확정 철회 |
| 리뷰 References에 주 논문이 누락됨 | original.md References; v1 저자 메타데이터 | official artifact | high | 확인한 저자 순서로 APA 추가 |

## Method map

| component/step | role | input/output | assumption | source anchor |
| --- | --- | --- | --- | --- |
| 프로토콜 묶기 | 비교 가능 관측 선택 | 모델–벤치마크 관측→family | 평가 판본·하네스 호환 | §2.1 |
| HCI | 남은 점수 여지 정규화 | consensus score,F0→H | 기준점·만점 정의 | Eq.2 |
| 개선 루프 해부 | 경험·대상·개선자·검증자·후계자 구분 | 시스템 사례→상속 상태/책임 | 실제 후속 회차 사용 증거 | §2.2 |
| 자율성 분류 | 무엇을 AI가 결정하는지 비교 | 해당 루프→B0–L5 | 성능과 별도 축 | §3.7 |
| 실효성 검증 | 개선 기구의 가치 확인 | 원래/수정 기구→후계자 평가 | 비슷한 예산·독립 평가 | §3.6.5 |

## Result table

| result claim | metric/dataset/setup | exact value | comparator | source anchor | caveat |
| --- | --- | --- | --- | --- | --- |
| 관측 규모 | 적격 모델–벤치마크 | 393 | 감사에서 제외한 자료와 구분 | §2.1 | 393개 모델 아님 |
| HCI | 2026 domain frontier | 수학 86.4; 과학 85.8; SWE 52.6; 도구 39.9 | 각 entry-year frontier | §2.1 | 정확도 아님 |
| 예시 미래 종점 | 100−.22(100−T) | T=52.6→89.6(반올림) | observed T | Eq.4 | 미래 예측 아님 |
| 문헌 집계 | L1/L2/L3/L4/L5 | 215/155/64/28/29, 합491 | 43.8/31.6/13.0/5.7/5.9% | Figure 16 | 코퍼스 구성 미확보 |
| 산업 실험 | Theseus workspace | 30 tasks; 1,280 및547 rubrics | clean/noisy; original/reconstructed | Table 9 | 독립 RSI 종단 검증 아님 |

## Critique log

| critique | label | action | reason | final prose location |
| --- | --- | --- | --- | --- |
| first-party를 1차 출처로 번역 | paper-evidenced | accepted | 자기 보고 할인과 primary evidence는 다름 | §§3.1,9.1 |
| HCI를 실제 능력의 동일 척도로 이해 | direct inference from setup | accepted | 기준점 대입 예시 | §3.1 |
| 늦은 벤치마크는 반드시 더 강한 모델이 기준 | speculative | softened | 원자료 없이 집합·점수 순서 확정 불가 | §9.2 |
| B0–L5가 제품 기능 체크리스트로 보임 | direct inference from setup | accepted | 지속성/결정권/다음 회차의 구체 예시 | §4.3 |
| 미세 차이는 확실한 반올림 결과 | speculative | softened | 가능한 설명과 원인 확정 구분 | §§3.2,9.2 |
| 주 논문 참고문헌 누락·DGM의 불확인 권/페이지 | official artifact | accepted | arXiv 메타데이터로 대체 | References |

## Final verification note

새 설명용 계산을 재계산했고 참고문헌 주저자 순서/판본을 arXiv와 대조했다. 기존 도판 URL을 보존했다. 491편 목록·393개 원시 관측·기업 실험은 독립 재현하지 않았으며 원문의 보고와 구분한다.
