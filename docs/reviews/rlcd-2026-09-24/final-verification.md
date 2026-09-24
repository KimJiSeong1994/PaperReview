# RLCD 발행 전 독립 사실 검증

검증일: 2026-09-24
검증 대상: `deep.md`, `easy.md`, `evidence-review.md`, `/tmp/rlcd-v3.pdf`, PaperWiki 원본 Figure 1·2 및 `manifest.json`
검증 성격: 논문 원문과 공개 자료를 대조한 **문헌 검증**이다. 모델 학습, 데이터 재생성, 벤치마크 재실행을 통한 독립 재현은 수행하지 않았다.

## Verdict

- **PASS — 사실 검증 승인.** 핵심 방법, 비교 대상, 평가 척도, 모든 주요 수치와 비판적 해석은 원문 v3와 일치한다. 발행을 막을 내용 오류나 근거 앵커 오류를 발견하지 못했다.
- `deep.md`와 `easy.md` 모두 문헌 검증 기준을 통과했다.

## Evidence

### 핵심 주장과 비교 대상

- `/tmp/rlcd-v3.pdf`, PDF p. 6, §4 — RLCD7B·RLCD30B 및 RLAIF/Context-Dist 첨자는 선호 데이터 시뮬레이션에 사용한 LLaMA-7B·30B를 가리킨다. 정렬되는 downstream base model은 모든 조건에서 LLaMA-7B다. `deep.md`와 `easy.md`가 이를 정확히 구분한다.
- PDF pp. 3–4, §3.1–3.2 — `p+`, `p-`에서 `o+`, `o-`를 생성하고 `o+`를 사후 채점 없이 선호로 라벨하며, 두 프롬프트의 표면형을 최대한 비슷하게 두려는 설명이 초안과 일치한다.
- PDF p. 6, Metrics — 무해성 prompt set에서는 `Harm`와 `Help`를 함께 측정하고, 도움성 prompt set에서는 별도의 `Help`를 측정한다. 초안의 열 구분은 정확하다.

### 평가 척도와 주 결과

- PDF pp. 6–7 및 p. 19, Tables 2–3·Appendix F — 사람 평가는 비교당 200개, 1–8 척도이며 사후 정규화한 두 점수의 합은 9다. GPT-4 평가는 비교당 1,000개이고, 파싱 실패·거부 시 양쪽에 0.5를 준다. 두 초안이 이를 승률·절대 품질 점수와 구분한다.
- PDF pp. 6–7, Tables 2–3 — RLCD7B/RLAIF7B의 사람 점수 `5.62/3.38, 4.64/4.36, 5.88/3.12, 5.97/3.03`과 GPT-4 점수 `84.8/15.2, 71.0/29.0, 85.4/14.6, 78.5/21.5`가 정확하다.
- PDF pp. 6–7, Tables 2–3 — RLCD30B/RLAIF30B의 사람 점수 `4.71/4.29, 4.50/4.50, 4.51/4.49, 4.76/4.24`와 GPT-4 점수 `60.3/39.7, 55.3/44.7, 47.8/52.2, 35.9/64.1`이 정확하다. 초안은 GPT-4가 도움성 과제와 개요에서 RLAIF30B를 선호한 사실을 숨기지 않는다.
- PDF p. 21, Table 23 — RLCD/RLAIF 비교의 사람–GPT-4 일치율 `74.7→62.8`(도움성 prompt set) 및 `77.5→59.0`(개요)이 정확하며, GPT-4가 거부한 예제를 제외한다는 단서도 포함됐다.

### Few-shot 기준선과 `Help` 열

- PDF p. 16, Tables 15–16 — few-shot 실험은 **harmlessness task / harmlessness prompt set에만** 수행됐다. Table 16의 `Help`는 별도 도움성 과제가 아니라 같은 무해성 prompt set에서 측정한 도움성이다.
- `deep.md`는 `42.1/57.9`를 무해성 `Harm`, `56.9/43.1`을 “같은 무해성 과제의 도움성 지표”로 명시한다. `easy.md`도 few-shot 비교를 무해성 결과로 한정한다. 과제 혼동은 없다.
- PDF p. 16 본문 — RLAIF-Few30B의 generic harmless but meaningless 응답과 heavy mode collapse에 대한 초안 설명이 원문과 일치한다.

### 길이, 보조 분석, 이론

- PDF p. 37, Table 34 — 7B 길이 수치 `66.5/118.0/115.9`(RLCD)와 `42.1/35.4/54.8`(RLAIF)가 정확하다.
- PDF p. 38, Table 35 — 30B 길이 수치 `73.3/108.3/138.7`(RLCD)와 `78.1/84.7/88.6`(RLAIF)가 정확하다. Tables 34와 35는 각각 PDF 37쪽과 38쪽에 나뉘어 있다.
- PDF pp. 39–40, Appendix N — `sigma_G=sigma_D=1`, RLAIF 전체 0.75, hard subset 0.528, `mu(p+)-mu(p-)=3`인 RLCD hard subset 0.574가 정확하다. 초안은 이를 실제 측정치나 30B 결과의 원인 입증으로 과장하지 않는다.
- PDF pp. 35–38, Appendices J.1·K.1 — 최종 출력의 held-out reward와 생성 선호쌍의 held-out-model label accuracy를 사람의 직접 라벨 정확도와 구분한 설명이 정확하다.

### Figure, 목차, 출처

- `.venv/bin/python`/PyMuPDF로 `/tmp/rlcd-v3.pdf`를 확인한 결과 40쪽이며 첫 페이지에 `arXiv:2307.12950v3 [cs.CL] 16 Mar 2024`, ICLR 2024, 저자 5인이 표시된다. 본문 metadata와 References가 일치한다.
- Figure 1은 PDF p. 2, Figure 2는 PDF p. 20에서 추출됐다. 캡션의 내용·페이지·척도 설명이 원문과 일치한다.
- PaperWiki `figures/manifest.json`의 PDF SHA-256 `3723ddb...46a`는 `/tmp/rlcd-v3.pdf`와 일치한다. Figure 1·2 PNG SHA-256도 manifest와 각각 일치한다.
- `github-slugger` 2.0.0으로 10개 절 제목을 계산한 결과 `deep.md` 목차 링크가 `rehype-slug`이 생성하는 ID와 모두 일치한다. 가운데점 `·`이 제거되는 8절 앵커 `#8-길이다양성과-통제-실험`도 정확하다.
- `## References`가 존재하고 Yang et al.의 저자, 연도, 제목, ICLR 2024, arXiv:2307.12950v3가 PDF와 일치한다. 나머지 인용도 원문 References의 저자·제목·arXiv ID와 충돌하지 않는다.
- `data/blog/posts.json`은 파싱에 성공하며 90개 레코드 중 RLCD는 slug `rlcd` 한 건이다. 저장된 `content` SHA-256은 `easy.md`와, `deep_content` SHA-256은 `deep.md`와 각각 완전히 일치한다.
- 서버의 `_estimate_reading_time`을 최신 원고에 직접 적용한 결과 easy 8분, deep 24분이며, RLCD 레코드는 `published: true`, `index_deep_view: true`, thumbnail `/api/blog/figures/rlcd-fig1-comparison.png`로 설정됐다.
- `.venv/bin/pytest -q tests/test_blog_reading_views.py tests/test_blog_thumbnails.py` — **32 passed**. easy/deep 읽기 뷰, 읽기 시간, 썸네일 관련 회귀 테스트가 통과했다.

## Resolved before approval

- Table 2/3, Table 6, Tables 34/35, Table 16, Tables 28/29/36, Appendix N의 PDF 링크를 각 근거가 실제로 위치한 pp. 6/7, 8/9, 37/38, 16, 35/36/38, 39/40으로 분리했다.
- Figure 1을 PDF p. 2의 도판 경계로 다시 추출해 상단 페이지 헤더 조각을 제거했다. 새 PNG의 SHA-256 `8318ae2...8d47f`는 `figure-provenance.json`과 일치한다.

## Gaps

- 논문이 보고한 학습·평가 결과를 재실행하지 않았다. 판정 범위는 PDF·공개 README·기존 PaperWiki 산출물 사이의 문헌 및 인용 정합성이다.
- 실제 블로그 API 업로드 후 이미지 URL 해석, 렌더링, 발행 상태는 이 검증 범위에 포함되지 않는다.

## Risks

- 논문이 제공하지 않은 길이 보정 평가, 최신 모델에서의 재현, 독립 벤치마크 결과는 글에서도 미검증 범위로 남겨 두었다. 현재 문구는 이를 저자 보고 결과나 리뷰어의 제한된 해석으로 구분한다.
