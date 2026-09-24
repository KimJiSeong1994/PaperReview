# CLAUSE 근거·수정 기록

근거: [ICLR 2026 컨퍼런스 PDF](https://proceedings.iclr.cc/paper_files/paper/2026/file/8598c5d05e1d045919962e430b0bdf0d-Paper-Conference.pdf), 27쪽. 이번에 다운로드한 PDF에서 `source.txt`를 추출했다. 해시는 `source-provenance.json`에 보존했다. 기존 본문의 정확도·비용·이론 구분을 유지하고 Curator의 실제 선택 흐름과 학습 신호를 보강한다.

## Evidence ledger

| claim | source anchor | evidence type | confidence | notes |
| --- | --- | --- | --- | --- |
| 세 정책은 edit→traverse→curate로 맥락을 구성한다 | §§3–4, Algorithms 1–2, PDF pp.4–6,19 | paper-reported | high | 실행 데이터 흐름과 공동 학습을 구분 |
| task reward는 reader 답변 후 계산하고 비용은 행동별 누적한다 | Algorithm 1 lines 5–13, p.19 | paper-reported | high | §4.6 설명 추가 |
| 실행에는 gold answer가 필요하지 않다 | Algorithm 2 inputs/return, p.19 | direct inference from setup | high | 학습의 q/y와 실행의 q/정책 입력 차이 |
| Curator 최고점 후보가 예산을 초과하면 종료한다 | Algorithm 4 lines 3–5, p.20 | paper-reported | high | 더 짧은 후보로 건너뛰는 분기 없음 |
| 해당 의사코드는 최적 knapsack 탐색을 구현하지 않는다 | Algorithm 4, p.20 | direct inference from setup | high | 실제 구현 결함으로 단정하지 않음 |
| 기대 비용 제약과 개별 질의 cap은 다르다 | Eq.1; Algorithms 2,4 | direct inference from setup | high | 기존 구분 유지 |
| Algorithm 1/3의 advantage 표기가 다르다 | p.19 | paper-reported | high | 코드에서 잘못됐다는 주장 아님 |
| dual의 부호·convexity 서술은 정합성 확인이 필요하다 | Appendix H; max of affine의 성질 | direct inference from setup | high | 실험 진위를 부정하는 근거로 사용하지 않음 |

## Method map

| component/step | role | input/output | assumption | source anchor |
| --- | --- | --- | --- | --- |
| Architect | 작업용 그래프 편집 | 질문·frontier→간선 추가/삭제 | KG 관계 및 anchor | §4.3 |
| Navigator | 경로 선택·되돌리기 | 부분 그래프→탐색 기록 | hop/잔여 예산 | §4.3 |
| Curator | 근거 목록 구성 | 후보·기선택 목록→reader 맥락 | tokenizer·후보 길이 | Algorithm 4 |
| Reader | 답변 생성 | 질문·선택 텍스트→답변 | 근거 충실성 별도 평가 | Algorithm 2 |
| LC-MAPPO | 정책·critic·자원 가격 갱신 | 정답 보상·단계별 비용→정책 | 정답이 있는 학습 집합 | Algorithms 1,3 |

## Result table

| result claim | metric/dataset/setup | exact value | comparator | source anchor | caveat |
| --- | --- | --- | --- | --- | --- |
| 정확도 | MetaQA 2-hop, EM@1 | 87.3 | GraphRAG 48.0; KG-Agent 78.0 | Table 2 | +39.3/+9.3은 percentage points |
| 지연 | MetaQA 2-hop, Vanilla=1 | 1.14 | GraphRAG 1.40 | Table 3 | 상대 감소 18.6%, 절대 ms 아님 |
| 간선 | 같은 과제·정규화 | 0.78 | GraphRAG 1.32 | Table 4 | 상대 감소 40.9% |
| 제약 준수 | MetaQA edge .5 / latency .7 | .340 | MAPPO .117 | §5.1, Figure 3 | 완전 준수 아님 |
| 지연 위반 | 같은 설정 | .577 | .880 | §5.1, Figure 3 | hard cap 시행 여부 불명 |
| 제거 실험 | Architect 대체 | 74.8 vs full 87.3 | StaticRAG/no-KG | Table 5 | 순수 정책 제거 효과 아님 |

## Critique log

| critique | label | action | reason | final prose location |
| --- | --- | --- | --- | --- |
| Curator가 남은 예산의 최적 조합을 찾는다는 오독 | direct inference from setup | accepted | 최고점 후보 초과 시 break | §3.3 |
| 실행 의존성과 학습 보상 연결 설명 부족 | paper-evidenced | accepted | Algorithm 1/2를 따라 재구성 | §4.6 |
| 의사코드 종료를 실제 코드 버그로 단정 | speculative | rejected | supplemental 코드 미확보 | omitted |
| 이론 서술 문제로 실험 수치를 무효화 | speculative | rejected | 별개 증거 | omitted |

## Final verification note

주요 표·제약 수치 및 새 방법 설명을 PDF와 대조했다. 원문 도판 URL 4개를 보존한다. 기존 원문의 불확실성 표시는 유지하며 모델을 독립 실행하지 않았다. 독립 후속 검토 결과는 상위 폴더의 critical/verification pass에 기록한다.
