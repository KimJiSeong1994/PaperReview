"""Poster content extraction honesty contracts (B1, B3, B6)."""

from __future__ import annotations

from app.DeepAgent.agents.poster_composition_agent import PosterCompositionAgent
from app.DeepAgent.agents.poster_content_agent import PosterContentAgent


_PROSE_ONLY_REPORT = """# 도시 기능 공간 구조 리뷰

## 1. 초록

본 리뷰는 한 편의 논문을 대상으로 한다.

## 2. 기여

리스트 마커 없이 문단으로만 서술된 기여 설명이다.

## 3. 핵심 발견

리스트 마커 없이 문단으로만 서술된 발견 설명이다.
"""


_NO_SECTION_KEYWORD_REPORT = """# 공간 구조 리뷰

## 1. 개요

마커 없는 산문 한 문단.

## 2. 분석

또 다른 산문 한 문단.
"""


_APA_REFERENCE_REPORT = """# 도시 기능 공간 구조 리뷰

## 참고문헌

Chen, Y., Chen, X., Liu, Z., & Li, X. (2020). Understanding the spatial organization of urban functions based on co-location patterns mining: A comparative analysis for 25 Chinese cities. *Cities*, 97, 102531. https://doi.org/10.1016/j.cities.2019.102531

---

*본 체계적 문헌 고찰은 AI 기반 심층 연구 분석 시스템에 의해 생성되었습니다.*
"""


_NUMBERED_REFERENCE_REPORT = """# 리뷰

## 참고문헌

1. Chen, Y. (2020). Understanding urban functions. *Cities*, 97, 102531.
"""


# 표·산문·불릿·줄바꿈이 섞인 실제 리포트 모양. 실제 참고문헌은 2편뿐이다.
_MIXED_REFERENCE_REPORT = """# 리뷰

## 참고문헌

아래 표는 본 고찰에서 인용한 논문의 서지 정보를 정리한 것이다.

| 번호 | 저자 | 연도 |
|---|---|---|
| 1 | Chen | 2020 |
| 2 | Kim | 2021 |

- Chen, Y., & Li, X. (2020). Understanding the spatial organization of urban
functions based on co-location patterns mining. *Cities*, 97, 102531.
* Kim, J. (2021). Functional region delineation. *Applied Geography*, 128, 102406.

*본 체계적 문헌 고찰은 AI 기반 심층 연구 분석 시스템에 의해 생성되었습니다.*
"""


_REPEATED_FIELD_REPORT = """# 리뷰

## 2. 개별 논문 심층 분석

### 2.1 Co-location Patterns Mining

**핵심 방법론**

POI 공간 동시출현 패턴을 마이닝한다.

**약점 및 한계**

표본이 단일 도시로 제한된다.

**숨겨진 가정과 한계**

POI 품질 검증이 부재하다.
"""


_METHOD_LIMITATION_REPORT = """# 리뷰

## 2. 개별 논문 심층 분석

### 2.1 Co-location Patterns Mining

**핵심 방법론**

POI 공간 동시출현 패턴을 마이닝한다.

**방법론적 한계**

거리 임계값 선택이 임의적이다.
"""


# ── B1: 추출 실패 시 하드코딩 문구를 인쇄하지 않는다 ────────────────────────


def test_missing_lists_are_left_empty_instead_of_boilerplate() -> None:
    content = PosterContentAgent().extract(_PROSE_ONLY_REPORT, num_papers=1)

    assert content.contributions == []
    assert content.key_findings == []


def test_thesis_states_extraction_failure_instead_of_inventing_a_finding() -> None:
    content = PosterContentAgent().extract(_PROSE_ONLY_REPORT, num_papers=1)
    agent = PosterCompositionAgent()
    composition = agent.design(content, autofigure_svgs=[], figures=[])

    html = agent.render_html(composition, [], [], content=content)

    assert "핵심 결론이 입력 리포트에서 추출되지 않았습니다." in html
    for invented in (
        "방법론적 다양성 확인",
        "공통 연구 트렌드 발견",
        "성능 개선 패턴 식별",
        "연구 공백 파악",
        "선정 논문들의 방법론적 특징 분석",
    ):
        assert invented not in html


def test_failed_section_extraction_prints_the_honest_text_not_a_written_default() -> None:
    """F1: 추출 실패 시 초록/배경/결론에 문구를 지어내지 않는다."""
    content = PosterContentAgent().extract(_NO_SECTION_KEYWORD_REPORT, num_papers=1)
    agent = PosterCompositionAgent()

    html = agent.render_html(
        agent.design(content, autofigure_svgs=[], figures=[]), [], [], content=content
    )

    for fabricated in (
        "본 연구는 선정된 논문들을 체계적으로 분석하여 해당 분야의 연구 동향과 핵심 기여를 파악합니다.",
        "기존 연구의 한계를 분석하고, 새로운 접근법의 필요성을 파악하기 위해 체계적인 문헌 고찰을 수행하였습니다.",
        "본 분석을 통해 해당 분야의 연구 동향을 파악하고, 향후 연구 방향에 대한 통찰을 얻었습니다.",
        "본 분석을 통해 해당 분야의 주요 연구 동향을 확인하였습니다.",
    ):
        assert fabricated not in html
    assert "추출된 초록과 연구 배경이 없습니다." in html
    assert "결론이 추출되지 않았습니다." in html


# ── B3: 번호 없는 참고문헌도 "0 refs"로 지워지지 않는다 ─────────────────────


def test_apa_style_references_are_extracted() -> None:
    refs = PosterContentAgent().extract(_APA_REFERENCE_REPORT, num_papers=1).references

    assert len(refs) == 1
    assert refs[0].startswith("Chen, Y., Chen, X., Liu, Z., & Li, X. (2020).")


def test_numbered_references_still_drop_their_numbering() -> None:
    refs = PosterContentAgent().extract(_NUMBERED_REFERENCE_REPORT, num_papers=1).references

    assert refs == ["Chen, Y. (2020). Understanding urban functions. *Cities*, 97, 102531."]


def test_reference_section_noise_is_not_counted_as_references() -> None:
    """F5: 표 행, 안내 산문, AI 고지가 참고문헌 수를 부풀리면 안 된다."""
    refs = PosterContentAgent().extract(_MIXED_REFERENCE_REPORT, num_papers=2).references

    assert refs == [
        "Chen, Y., & Li, X. (2020). Understanding the spatial organization of urban "
        "functions based on co-location patterns mining. *Cities*, 97, 102531.",
        "Kim, J. (2021). Functional region delineation. *Applied Geography*, 128, 102406.",
    ]


# ── B6: 같은 필드 재감지 시 유실 금지 + "방법론적 한계" 분류 ────────────────


def test_repeated_limitation_headings_accumulate_instead_of_overwriting() -> None:
    analyses = PosterContentAgent().extract(_REPEATED_FIELD_REPORT, num_papers=1).paper_analyses

    assert len(analyses) == 1
    limitations = analyses[0]["limitations"]
    assert "표본이 단일 도시로 제한된다." in limitations
    assert "POI 품질 검증이 부재하다." in limitations


def test_limitation_keyword_classifies_by_tail_position_not_containment() -> None:
    """F13: '한계'가 수식어인 헤딩까지 limitations로 흡수하면 안 된다."""
    agent = PosterContentAgent()

    assert agent._detect_paper_field('**방법론적 한계**') == 'limitations'
    assert agent._detect_paper_field('**핵심 방법론의 한계를 극복한 접근**') == 'methodology'
    assert agent._detect_paper_field('**한계 극복을 위한 실험 결과**') == 'results'
    assert agent._detect_paper_field('**성능 개선**') == 'results'
    assert agent._detect_paper_field('**Limitations of the Evaluation**') == 'limitations'
    assert agent._detect_paper_field('**약점 및 한계**') == 'limitations'
    assert agent._detect_paper_field('**핵심 방법론**') == 'methodology'


def test_limitation_fallback_keywords_stay_reachable() -> None:
    """F13: 꼬리 판별을 통과하지 못한 한계 표기는 field_patterns가 받는다."""
    agent = PosterContentAgent()

    # 꼬리가 '점'/'method'/'방향'이라 endswith가 받지 못한다. 세 항목이 각각 받는다.
    assert agent._detect_paper_field('**한계점**') == 'limitations'
    assert agent._detect_paper_field('**Limitations of the Evaluation**') == 'limitations'
    assert agent._detect_paper_field('**개선 방향**') == 'limitations'


def test_methodological_limitation_is_classified_as_a_limitation() -> None:
    analyses = PosterContentAgent().extract(_METHOD_LIMITATION_REPORT, num_papers=1).paper_analyses

    assert len(analyses) == 1
    assert "거리 임계값 선택이 임의적이다." in analyses[0]["limitations"]
    assert "거리 임계값 선택이 임의적이다." not in analyses[0]["methodology"]
