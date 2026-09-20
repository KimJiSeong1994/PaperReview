# 블로그의 쉬운 읽기와 상세 읽기

## 독자 흐름

- `/blog/:slug`는 기본 본문을 보여 준다. MTP 글은 수식 없는 7분 분량의 쉬운 버전을 기본으로 사용한다.
- 상세 본문이 있는 글은 상단의 `PDF 보기` 옆에 `상세 읽기` 링크를 둔다.
- `/blog/:slug?view=deep`는 상세 본문을 보여 주고 같은 위치에 `쉬운 읽기` 링크를 둔다. MTP의 기존 29분 상세 리뷰를 그대로 보존했다.
- 브라우저 뒤로 가기·앞으로 가기·새로고침·복사한 링크의 직접 열기를 지원한다. 읽기 시간과 목차는 선택한 본문에 맞게 바뀐다.
- 상세 본문이 없거나 비어 있거나 알 수 없는 view 값이면 기본 글을 보여 준다.

## 데이터 및 API

### 쉬운 읽기의 핵심 도판

논문의 방법 구조와 주요 결과를 이해하는 데 필요한 원그림을 본문의 해당 설명 옆에 둔다. 보통 2–3개를 고르고, 캡션에는 무엇을 볼지와 결과가 성립하는 조건을 한국어로 설명한다. 논문 판본·그림 번호·페이지를 밝히며, 큰 도판은 원본 이미지로 연결한다. 작성·비판 검토·발행 검증에서 도판 누락, 다른 판본의 그림 혼입, 축·범례 잘림, 모바일 표시, 대체텍스트를 함께 확인한다.

RLT는 2026년 9월 17일 개정판의 Figures 1·4를 쉬운 글에, Figures 1·4·17을 상세 글에 사용한다. RSI·TTPO·InCoder·CodeNib 쉬운 글에는 각각 핵심 도판 3개를 배치했다. RLT의 원본 PDF 해시와 추출 영역은 `docs/reviews/rlt-v20260917-figure-provenance.json`에 기록했다.

`content`는 항상 기본 본문이다. 선택적인 `deep_content`에 상세 Markdown을 저장한다. 상세 API는 두 본문과 계산된 `deep_reading_time_min`을 반환하므로 읽기 전환에 추가 요청이 필요하지 않다. 목록에는 두 본문을 싣지 않는다.

POST/PUT에서 `deep_content`를 생략하면 기존 값을 유지한다. 명시적인 null·빈 문자열·공백 문자열은 상세 본문을 지운다. 관리자 편집은 두 본문을 별도 입력란으로 제공하며, 목록에서 편집할 때 전체 레코드를 가져온다. 늦게 끝난 이전 요청이 새 편집 대상을 바꾸지 않도록 요청 순서를 확인한다. 기존 글 편집은 slug를 보존한다.

검색은 두 본문을 모두 대상으로 한다. 목록·excerpt·RSS·사이트맵·기본 전체 텍스트는 기존 기본 글 기준이다. 서버 렌더링도 view를 반영하므로 JavaScript 없이 두 버전을 오갈 수 있다. 양쪽의 canonical은 기존 `/blog/:slug`다.

논문 제목·arXiv·DOI·PDF 링크는 기본 글에서 추출한다. 상세 글에 Paper 메타데이터가 없어도 같은 논문을 가리킨다. 구조화 데이터의 articleBody·wordCount는 현재 읽는 본문을 반영하고, articleBody는 상세 본문을 지원하는 글에만 추가한다.

## 디자인과 호환성

`DESIGN.md`의 reading-level 계약을 따른다. 기존 PDF 링크 스타일과 색상 변수를 재사용하고 44px 터치 영역·키보드 포커스를 제공한다. 별도 상세 본문이 없는 기존 글의 읽기 흐름은 유지된다.

MTP의 ID·URL·제목·최초 발행일·태그·그림과 다른 87편을 보존했다. 변경 중인 외부 PaperWiki 상세 원고는 덮어쓰지 않으며, 이 기능은 이미 발행·검증된 상세 본문을 연결한다.

## 검증

- 프런트엔드 전체: 429 passed, 1 skipped.
- 관련 백엔드·SEO: 118 passed.
- TypeScript/Vite build 통과.
- 1440px/400px × light/dark × easy/deep의 8개 화면 확인.
- 키보드 전환, 새로고침, 뒤로/앞으로, PDF 링크 유지, JavaScript 없는 탐색 확인.
- 독립 코드 리뷰 승인 및 시각 검토 96/100.
- 기존 BlogPage의 ESLint 진단 3건은 그대로이며 이번 변경에서 새 진단을 추가하지 않았다. 클릭 핸들러 안의 ref 갱신을 렌더 단계로 오인하는 한 진단은 해당 줄에만 근거를 명시해 제외했다.

```sh
pytest -q tests/test_blog_reading_views.py tests/test_blog_slug.py tests/test_blog_search.py tests/test_blog_tags.py tests/test_blog_references.py tests/test_blog_series_sync.py tests/test_blog_thumbnails.py tests/test_seo.py
npm --prefix web-ui test
npm --prefix web-ui run build
git diff --check
```
