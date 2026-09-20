# Multi-token Prediction 리뷰 발행 기록

## 대상과 근거

- 논문: *Better & Faster Large Language Models via Multi-token Prediction*.
- 기술 분석 판본: [arXiv:2404.19737v1](https://arxiv.org/abs/2404.19737v1), 2024-04-30, 29쪽.
- 출판 메타데이터: [ICML 2024 / PMLR 235](https://proceedings.mlr.press/v235/gloeckle24a.html). 기술적 수치·표·도판의 기준은 v1을 유지한다.
- 게시 주소: `/blog/multi-token-prediction`.
- 분류: `paper-review`; 대표 그림: `mtp-fig1-overview.png`.

## 편집

사용자가 제공한 PaperWiki 원고의 10개 절과 그림 8개를 유지하며, 기존 집현전 리뷰의 설명 중심 문체로 다듬었다.

- 반복적인 비판과 도판의 세부 모양 나열을 줄이고 방법·결과 해석을 앞에 배치했다.
- 여러 미래 위치의 손실을 수식으로 재구성하고, 헤드별 순전파·역전파를 의사코드로 설명했다.
- 파라미터·데이터가 맞춰진 같은 규모의 비교와, 토큰 수가 달라지는 규모 간 비교를 구분했다.
- 13B 품질 결과와 7B 탐욕적 디코딩의 속도 결과를 분리하고, 3.05배·6.39배의 비교 기준과 배치 조건을 명시했다.
- Table S5의 측정된 학습 오버헤드와 저자들이 설명한 구현 개선 가능성을 구분했다.
- 책:동화 혼합 비율 9:1을 바로잡고, 요약 결과가 데이터셋별 3에폭 미세조정·검증 선택 이후라는 조건을 보강했다.
- 누락된 주 논문 참고문헌을 추가하고 excerpt를 기여·결과·한계를 전달하는 128자의 두 문장으로 작성했다.

도판은 사용자가 제공한 원논문 Figures 1–8의 영역 추출본이다. 원본 그래프·축·수치를 변경하지 않고 출처와 한국어 해설을 보존했다. 새로운 라이선스를 임의로 부여하지 않았다.

## 게시 데이터

기존 87편의 레코드를 바꾸지 않고 새 글 한 편과 PNG 8개를 추가한다. PaperWiki 전용 상대 경로의 쉬운 해설 링크는 원고에 유지하며 공개 블로그 본문에서는 제외한다. 블로그 본문은 검토 후 저장된 PaperWiki 원고를 기준으로 생성했다.

## 검증

- 블로그·검색·태그·참고문헌·시리즈·썸네일·SEO 관련 테스트 113개 통과.
- TypeScript 및 Vite 빌드 통과.
- 1440px·400px 미리보기에서 수식 40개, 그림 8개, 단일 제목, 가로 넘침과 페이지 오류 없음 확인.
- 게시 스키마, 주 논문 저자 5명·제목·arXiv 판본 추출, 기존 87편 보존 확인.
- 제공된 도판 8개의 SHA-256·크기와 원본 manifest 일치 확인.

```sh
pytest -q tests/test_blog_slug.py tests/test_blog_search.py tests/test_blog_tags.py tests/test_blog_references.py tests/test_blog_series_sync.py tests/test_blog_thumbnails.py tests/test_seo.py
npm --prefix web-ui run build
git diff --check
```

원문 및 제공된 검토 기록을 대조한 발행 작업이며, 모델 학습·벤치마크를 독립 재실행한 결과는 아니다.
