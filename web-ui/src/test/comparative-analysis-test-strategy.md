# Comparative Analysis Table - 테스트 전략 및 품질 보증 기획안

**작성일**: 2026-02-18
**작성자**: QA Validator Agent
**기능**: 다중 논문 비교 분석 테이블 생성 (LLM 기반 메트릭 추출)
**범위**: 백엔드 단위 테스트, 프론트엔드 단위 테스트, 통합 테스트, 엣지 케이스, 품질 메트릭

---

## 목차

1. [테스트 환경 및 도구](#1-테스트-환경-및-도구)
2. [백엔드 단위 테스트](#2-백엔드-단위-테스트)
3. [프론트엔드 단위 테스트](#3-프론트엔드-단위-테스트)
4. [통합 테스트](#4-통합-테스트)
5. [엣지 케이스](#5-엣지-케이스)
6. [품질 메트릭 및 LLM 출력 검증](#6-품질-메트릭-및-llm-출력-검증)
7. [테스트 데이터 (Fixtures)](#7-테스트-데이터-fixtures)
8. [실행 계획 및 CI 통합](#8-실행-계획-및-ci-통합)

---

## 1. 테스트 환경 및 도구

### 백엔드
- **프레임워크**: pytest + pytest-asyncio
- **HTTP 테스트**: httpx (FastAPI TestClient)
- **Mock**: unittest.mock, pytest-mock
- **LLM Mock**: 커스텀 OpenAI 응답 fixture
- **커버리지**: pytest-cov (목표: 80% 이상)

### 프론트엔드
- **프레임워크**: Vitest 4.x (이미 설정됨: `vite.config.ts` > test)
- **DOM 환경**: jsdom (이미 설정됨)
- **컴포넌트 렌더링**: @testing-library/react 16.x
- **사용자 상호작용**: @testing-library/user-event 14.x
- **단언**: @testing-library/jest-dom (이미 `src/test/setup.ts`에서 import)

### 통합 테스트
- **API 통합**: msw (Mock Service Worker) 추가 필요
- **E2E (향후)**: Playwright 검토

---

## 2. 백엔드 단위 테스트

### 2.1 LLM 추출 프롬프트 검증

**파일**: `tests/test_comparative_extraction.py`

```python
"""
LLM 기반 비교 분석 메트릭 추출 로직 테스트.
OpenAI 클라이언트를 mock하여 프롬프트 구성과 응답 파싱을 검증한다.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


# ── Mock LLM 응답 Fixture ──────────────────────────────────────────

MOCK_LLM_EXTRACTION_RESPONSE = {
    "papers": [
        {
            "paper_id": "2401.00001",
            "title": "Attention Is All You Need",
            "dimensions": {
                "method": "Transformer (Self-Attention)",
                "dataset": "WMT 2014 EN-DE, EN-FR",
                "metric_bleu": 28.4,
                "metric_params": "65M",
                "year": 2017,
                "venue": "NeurIPS",
                "task": "Machine Translation",
                "novelty": "Self-attention 기반 seq2seq 아키텍처 제안",
                "limitation": "긴 시퀀스에서 O(n^2) 메모리 복잡도",
            }
        },
        {
            "paper_id": "2401.00002",
            "title": "BERT: Pre-training of Deep Bidirectional Transformers",
            "dimensions": {
                "method": "Masked Language Model + NSP",
                "dataset": "BooksCorpus, English Wikipedia",
                "metric_bleu": None,
                "metric_params": "110M / 340M",
                "year": 2018,
                "venue": "NAACL",
                "task": "Language Understanding",
                "novelty": "양방향 사전학습으로 문맥 표현 학습",
                "limitation": "사전학습 비용이 매우 높음",
            }
        },
    ],
    "dimensions_meta": {
        "method": {"label": "방법론", "type": "text"},
        "dataset": {"label": "데이터셋", "type": "text"},
        "metric_bleu": {"label": "BLEU", "type": "numeric"},
        "metric_params": {"label": "파라미터 수", "type": "text"},
        "year": {"label": "발표 연도", "type": "numeric"},
        "venue": {"label": "학회/저널", "type": "text"},
        "task": {"label": "연구 과제", "type": "text"},
        "novelty": {"label": "핵심 기여", "type": "text"},
        "limitation": {"label": "한계점", "type": "text"},
    },
}


@pytest.fixture
def mock_openai_client():
    """OpenAI 클라이언트를 mock하여 고정된 JSON 응답을 반환한다."""
    client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(
            content=json.dumps(MOCK_LLM_EXTRACTION_RESPONSE, ensure_ascii=False)
        ))
    ]
    mock_response.usage = MagicMock(
        prompt_tokens=1500, completion_tokens=800, total_tokens=2300
    )
    client.chat.completions.create.return_value = mock_response
    return client


@pytest.fixture
def sample_papers():
    """비교 분석에 사용할 샘플 논문 목록."""
    return [
        {
            "id": "2401.00001",
            "title": "Attention Is All You Need",
            "authors": [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}],
            "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...",
            "year": 2017,
            "venue": "NeurIPS",
        },
        {
            "id": "2401.00002",
            "title": "BERT: Pre-training of Deep Bidirectional Transformers",
            "authors": [{"name": "Jacob Devlin"}, {"name": "Ming-Wei Chang"}],
            "abstract": "We introduce a new language representation model called BERT...",
            "year": 2018,
            "venue": "NAACL",
        },
    ]


class TestExtractionPromptConstruction:
    """LLM 추출 프롬프트가 올바르게 구성되는지 검증."""

    def test_build_extraction_prompt_includes_all_papers(
        self, sample_papers
    ):
        """프롬프트에 모든 논문 제목과 초록이 포함되어야 한다."""
        # from routers.comparative import build_extraction_prompt
        # prompt = build_extraction_prompt(sample_papers)
        # assert "Attention Is All You Need" in prompt
        # assert "BERT" in prompt
        # assert len(sample_papers) == 2
        pass  # 구현 후 활성화

    def test_build_extraction_prompt_requests_json_format(
        self, sample_papers
    ):
        """프롬프트가 JSON 형식의 응답을 요구해야 한다."""
        # prompt = build_extraction_prompt(sample_papers)
        # assert "JSON" in prompt
        # assert "dimensions" in prompt
        pass

    def test_build_extraction_prompt_specifies_dimensions(
        self, sample_papers
    ):
        """프롬프트에 추출해야 할 차원(method, dataset, metric 등)이 명시되어야 한다."""
        # prompt = build_extraction_prompt(sample_papers)
        # required_dims = ["method", "dataset", "metric", "year", "venue", "task"]
        # for dim in required_dims:
        #     assert dim in prompt.lower()
        pass

    def test_prompt_handles_korean_papers(self):
        """한국어 논문 데이터가 프롬프트에 올바르게 포함되어야 한다."""
        # korean_papers = [
        #     {"id": "kr001", "title": "한국어 자연어처리를 위한 BERT 모델",
        #      "abstract": "본 연구에서는 한국어에 특화된 사전학습 모델을 제안한다..."}
        # ]
        # prompt = build_extraction_prompt(korean_papers)
        # assert "한국어" in prompt
        pass


class TestLLMResponseParsing:
    """LLM 응답 파싱 로직 테스트."""

    def test_parse_valid_json_response(self, mock_openai_client):
        """정상적인 JSON 응답을 올바르게 파싱해야 한다."""
        # result = extract_comparison_data(mock_openai_client, sample_papers)
        # assert len(result["papers"]) == 2
        # assert result["papers"][0]["title"] == "Attention Is All You Need"
        pass

    def test_parse_response_with_markdown_code_block(self):
        """LLM이 ```json ... ``` 형태로 감싼 응답도 처리해야 한다."""
        # raw = "```json\n{\"papers\": []}\n```"
        # result = parse_extraction_response(raw)
        # assert result["papers"] == []
        pass

    def test_parse_response_with_missing_dimensions(self):
        """일부 차원이 누락된 응답에서 None으로 채워야 한다."""
        # incomplete = {"papers": [{"paper_id": "001", "dimensions": {"method": "CNN"}}]}
        # result = normalize_extraction(incomplete, expected_dims=["method", "dataset"])
        # assert result["papers"][0]["dimensions"]["dataset"] is None
        pass

    def test_parse_malformed_json_raises_error(self):
        """잘못된 JSON 응답 시 ValueError를 발생시켜야 한다."""
        # with pytest.raises(ValueError, match="LLM 응답 파싱 실패"):
        #     parse_extraction_response("이것은 JSON이 아닙니다")
        pass

    def test_parse_response_with_extra_fields_ignored(self):
        """예상하지 않은 추가 필드는 무시하고 정상 처리해야 한다."""
        pass


class TestDimensionAlignment:
    """차원 정렬 및 정규화 로직 테스트."""

    def test_numeric_values_normalized(self):
        """숫자형 차원 값이 올바르게 정규화되어야 한다."""
        # values = [28.4, None, 41.0]
        # normalized = normalize_numeric_dimension(values)
        # assert normalized[1] is None  # None 유지
        # assert 0.0 <= normalized[0] <= 1.0
        pass

    def test_text_values_preserved(self):
        """텍스트형 차원 값은 원본 그대로 유지되어야 한다."""
        pass

    def test_dimension_type_inference(self):
        """값 목록으로부터 차원 타입(numeric/text)을 추론해야 한다."""
        # assert infer_dimension_type([28.4, 41.0, 35.2]) == "numeric"
        # assert infer_dimension_type(["CNN", "RNN", "Transformer"]) == "text"
        # assert infer_dimension_type([28.4, "N/A", 35.2]) == "mixed"
        pass

    def test_missing_values_handled(self):
        """None 또는 'N/A' 값이 포함된 경우 올바르게 처리해야 한다."""
        pass

    def test_align_dimensions_across_papers(self):
        """모든 논문에 대해 동일한 차원 집합이 보장되어야 한다."""
        # papers = [
        #     {"dimensions": {"method": "A", "year": 2020}},
        #     {"dimensions": {"method": "B", "dataset": "CIFAR-10"}},
        # ]
        # aligned = align_dimensions(papers)
        # assert set(aligned[0]["dimensions"].keys()) == {"method", "year", "dataset"}
        # assert aligned[1]["dimensions"]["year"] is None
        pass


class TestExportFormatters:
    """CSV, LaTeX, Markdown 내보내기 포맷터 테스트."""

    @pytest.fixture
    def comparison_table_data(self):
        return {
            "headers": ["논문", "방법론", "BLEU", "파라미터 수"],
            "rows": [
                ["Attention Is All You Need", "Transformer", 28.4, "65M"],
                ["BERT", "Masked LM", None, "340M"],
            ],
        }

    def test_export_csv_format(self, comparison_table_data):
        """CSV 내보내기가 올바른 형식을 출력해야 한다."""
        # csv_str = export_to_csv(comparison_table_data)
        # lines = csv_str.strip().split("\n")
        # assert lines[0] == "논문,방법론,BLEU,파라미터 수"
        # assert "Transformer" in lines[1]
        # assert "28.4" in lines[1]
        # assert ",," in lines[2] or ",N/A," in lines[2]  # None 처리
        pass

    def test_export_csv_escapes_commas(self):
        """CSV에서 쉼표가 포함된 값은 따옴표로 감싸야 한다."""
        # data = {"headers": ["title"], "rows": [["CNN, RNN, Transformer"]]}
        # csv_str = export_to_csv(data)
        # assert '"CNN, RNN, Transformer"' in csv_str
        pass

    def test_export_latex_format(self, comparison_table_data):
        """LaTeX 테이블 형식이 올바르게 생성되어야 한다."""
        # latex_str = export_to_latex(comparison_table_data)
        # assert "\\begin{tabular}" in latex_str
        # assert "\\end{tabular}" in latex_str
        # assert "\\hline" in latex_str
        # assert "&" in latex_str  # column separator
        pass

    def test_export_latex_escapes_special_chars(self):
        """LaTeX 특수문자(_, %, &)가 이스케이프되어야 한다."""
        # data = {"headers": ["method"], "rows": [["CNN_v2 & 50% accuracy"]]}
        # latex_str = export_to_latex(data)
        # assert "CNN\\_v2" in latex_str
        # assert "50\\%" in latex_str
        pass

    def test_export_markdown_format(self, comparison_table_data):
        """Markdown 테이블 형식이 올바르게 생성되어야 한다."""
        # md_str = export_to_markdown(comparison_table_data)
        # assert "| 논문 | 방법론 | BLEU | 파라미터 수 |" in md_str
        # assert "|---" in md_str  # separator line
        # assert "| Transformer |" in md_str or "Transformer" in md_str
        pass

    def test_export_none_values_displayed_as_dash(self, comparison_table_data):
        """None 값은 내보내기 시 '-' 또는 'N/A'로 표시되어야 한다."""
        pass


class TestComparativeAPIEndpoint:
    """비교 분석 API 엔드포인트 테스트."""

    @pytest.fixture
    def app_client(self):
        """FastAPI TestClient 생성."""
        # from httpx import AsyncClient, ASGITransport
        # from api_server import app
        # return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        pass

    @pytest.fixture
    def auth_headers(self):
        """인증 헤더 fixture."""
        return {"Authorization": "Bearer test_jwt_token"}

    async def test_post_comparative_analysis_success(
        self, app_client, auth_headers
    ):
        """정상적인 비교 분석 요청이 200 OK를 반환해야 한다."""
        # request_body = {
        #     "paper_ids": ["2401.00001", "2401.00002"],
        #     "dimensions": ["method", "dataset", "metric_bleu"]
        # }
        # response = await app_client.post(
        #     "/api/comparative-analysis",
        #     json=request_body,
        #     headers=auth_headers,
        # )
        # assert response.status_code == 200
        # data = response.json()
        # assert "papers" in data
        # assert "dimensions_meta" in data
        # assert len(data["papers"]) == 2
        pass

    async def test_post_comparative_analysis_invalid_paper_ids(
        self, app_client, auth_headers
    ):
        """존재하지 않는 paper_id로 요청 시 404 또는 적절한 에러를 반환해야 한다."""
        # request_body = {"paper_ids": ["nonexistent_001"]}
        # response = await app_client.post(
        #     "/api/comparative-analysis",
        #     json=request_body,
        #     headers=auth_headers,
        # )
        # assert response.status_code in (404, 400)
        pass

    async def test_post_comparative_analysis_empty_paper_ids(
        self, app_client, auth_headers
    ):
        """빈 paper_ids 목록 요청 시 422 Validation Error를 반환해야 한다."""
        # request_body = {"paper_ids": []}
        # response = await app_client.post(
        #     "/api/comparative-analysis",
        #     json=request_body,
        #     headers=auth_headers,
        # )
        # assert response.status_code == 422
        pass

    async def test_post_comparative_analysis_single_paper(
        self, app_client, auth_headers
    ):
        """논문 1편으로도 비교 테이블 생성이 가능해야 한다 (자기 자신과 비교)."""
        pass

    async def test_post_comparative_analysis_unauthorized(self, app_client):
        """인증 없이 요청 시 401을 반환해야 한다."""
        # response = await app_client.post(
        #     "/api/comparative-analysis",
        #     json={"paper_ids": ["2401.00001"]},
        # )
        # assert response.status_code == 401
        pass

    async def test_export_csv_endpoint(self, app_client, auth_headers):
        """CSV 내보내기 엔드포인트가 올바른 Content-Type을 반환해야 한다."""
        # response = await app_client.get(
        #     "/api/comparative-analysis/export/csv?session_id=test_session",
        #     headers=auth_headers,
        # )
        # assert response.status_code == 200
        # assert "text/csv" in response.headers["content-type"]
        pass

    async def test_export_latex_endpoint(self, app_client, auth_headers):
        """LaTeX 내보내기 엔드포인트가 올바른 형식을 반환해야 한다."""
        pass

    async def test_export_markdown_endpoint(self, app_client, auth_headers):
        """Markdown 내보내기 엔드포인트 테스트."""
        pass


class TestErrorHandling:
    """에러 케이스 테스트."""

    def test_llm_timeout_returns_504(self, mock_openai_client):
        """LLM 응답 타임아웃 시 504 Gateway Timeout을 반환해야 한다."""
        # from openai import APITimeoutError
        # mock_openai_client.chat.completions.create.side_effect = APITimeoutError(request=MagicMock())
        # with pytest.raises(HTTPException) as exc_info:
        #     await generate_comparison(mock_openai_client, sample_papers)
        # assert exc_info.value.status_code == 504
        pass

    def test_llm_rate_limit_returns_429(self, mock_openai_client):
        """LLM Rate Limit 시 429를 반환해야 한다."""
        # from openai import RateLimitError
        # mock_openai_client.chat.completions.create.side_effect = RateLimitError(
        #     message="Rate limit exceeded", response=MagicMock(), body=None
        # )
        pass

    def test_partial_extraction_returns_available_data(self):
        """일부 논문만 추출에 성공한 경우 성공한 데이터만 반환해야 한다."""
        # partial_response = {
        #     "papers": [
        #         {"paper_id": "001", "dimensions": {"method": "CNN"}, "status": "success"},
        #         {"paper_id": "002", "dimensions": {}, "status": "extraction_failed"},
        #     ]
        # }
        # result = handle_partial_extraction(partial_response)
        # assert len(result["papers"]) == 2
        # assert result["papers"][1]["status"] == "extraction_failed"
        # assert result["warnings"] is not None
        pass

    def test_llm_returns_non_json_error(self):
        """LLM이 JSON이 아닌 응답을 반환할 때 재시도 또는 에러를 반환해야 한다."""
        pass

    def test_concurrent_requests_handled(self):
        """동시 요청 시 Race condition이 발생하지 않아야 한다."""
        pass
```

---

## 3. 프론트엔드 단위 테스트

### 3.1 ComparativeTable 컴포넌트 렌더링

**파일**: `web-ui/src/test/ComparativeTable.test.tsx`

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
// import ComparativeTable from '../components/mypage/ComparativeTable';

// ── Mock 데이터 ──────────────────────────────────────────────────────

const mockComparisonData = {
  papers: [
    {
      paper_id: '2401.00001',
      title: 'Attention Is All You Need',
      dimensions: {
        method: 'Transformer (Self-Attention)',
        dataset: 'WMT 2014 EN-DE',
        metric_bleu: 28.4,
        year: 2017,
        venue: 'NeurIPS',
        task: 'Machine Translation',
        novelty: 'Self-attention 기반 seq2seq 아키텍처',
      },
    },
    {
      paper_id: '2401.00002',
      title: 'BERT',
      dimensions: {
        method: 'Masked Language Model',
        dataset: 'BooksCorpus, Wikipedia',
        metric_bleu: null,
        year: 2018,
        venue: 'NAACL',
        task: 'Language Understanding',
        novelty: '양방향 사전학습',
      },
    },
  ],
  dimensions_meta: {
    method: { label: '방법론', type: 'text' },
    dataset: { label: '데이터셋', type: 'text' },
    metric_bleu: { label: 'BLEU', type: 'numeric' },
    year: { label: '연도', type: 'numeric' },
    venue: { label: '학회', type: 'text' },
    task: { label: '과제', type: 'text' },
    novelty: { label: '핵심 기여', type: 'text' },
  },
};

const defaultProps = {
  data: mockComparisonData,
  loading: false,
  error: null as string | null,
  onExport: vi.fn(),
  onCellEdit: vi.fn(),
  onSort: vi.fn(),
  onFilter: vi.fn(),
};


describe('ComparativeTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('기본 렌더링', () => {
    it('테이블 헤더에 모든 논문 제목이 표시되어야 한다', () => {
      // render(<ComparativeTable {...defaultProps} />);
      // expect(screen.getByText('Attention Is All You Need')).toBeInTheDocument();
      // expect(screen.getByText('BERT')).toBeInTheDocument();
    });

    it('모든 차원(dimension) 행이 렌더링되어야 한다', () => {
      // render(<ComparativeTable {...defaultProps} />);
      // expect(screen.getByText('방법론')).toBeInTheDocument();
      // expect(screen.getByText('데이터셋')).toBeInTheDocument();
      // expect(screen.getByText('BLEU')).toBeInTheDocument();
      // expect(screen.getByText('연도')).toBeInTheDocument();
    });

    it('셀 값이 올바르게 표시되어야 한다', () => {
      // render(<ComparativeTable {...defaultProps} />);
      // expect(screen.getByText('Transformer (Self-Attention)')).toBeInTheDocument();
      // expect(screen.getByText('28.4')).toBeInTheDocument();
    });

    it('null 값은 "-" 또는 "N/A"로 표시되어야 한다', () => {
      // render(<ComparativeTable {...defaultProps} />);
      // BERT의 metric_bleu가 null이므로
      // const bleuRow = screen.getByText('BLEU').closest('tr');
      // expect(within(bleuRow!).getByText('-')).toBeInTheDocument();
    });

    it('빈 데이터일 때 안내 메시지를 표시해야 한다', () => {
      // const emptyData = { papers: [], dimensions_meta: {} };
      // render(<ComparativeTable {...defaultProps} data={emptyData} />);
      // expect(screen.getByText(/비교할 논문을 선택하세요/)).toBeInTheDocument();
    });
  });

  describe('로딩 및 에러 상태', () => {
    it('로딩 중일 때 스피너/스켈레톤을 표시해야 한다', () => {
      // render(<ComparativeTable {...defaultProps} loading={true} />);
      // expect(screen.getByText(/분석 중/)).toBeInTheDocument();
      // 또는 스켈레톤 요소 존재 확인
      // expect(document.querySelector('.skeleton')).toBeInTheDocument();
    });

    it('에러 발생 시 에러 메시지를 표시해야 한다', () => {
      // render(<ComparativeTable {...defaultProps} error="LLM 분석 시간 초과" />);
      // expect(screen.getByText('LLM 분석 시간 초과')).toBeInTheDocument();
      // expect(screen.getByRole('button', { name: /재시도/ })).toBeInTheDocument();
    });

    it('에러 상태에서 재시도 버튼이 동작해야 한다', async () => {
      // const onRetry = vi.fn();
      // render(<ComparativeTable {...defaultProps} error="timeout" onRetry={onRetry} />);
      // const user = userEvent.setup();
      // await user.click(screen.getByRole('button', { name: /재시도/ }));
      // expect(onRetry).toHaveBeenCalledOnce();
    });
  });

  describe('정렬 기능', () => {
    it('차원 이름 클릭 시 onSort가 호출되어야 한다', async () => {
      // render(<ComparativeTable {...defaultProps} />);
      // const user = userEvent.setup();
      // await user.click(screen.getByText('BLEU'));
      // expect(defaultProps.onSort).toHaveBeenCalledWith('metric_bleu', 'asc');
    });

    it('같은 차원을 다시 클릭하면 정렬 방향이 반전되어야 한다', async () => {
      // render(<ComparativeTable {...defaultProps} />);
      // const user = userEvent.setup();
      // await user.click(screen.getByText('BLEU'));
      // await user.click(screen.getByText('BLEU'));
      // expect(defaultProps.onSort).toHaveBeenLastCalledWith('metric_bleu', 'desc');
    });

    it('숫자형 차원은 숫자 기준으로 정렬되어야 한다', () => {
      // 정렬 로직 유틸 함수 단위 테스트
      // const papers = [...mockComparisonData.papers];
      // const sorted = sortByDimension(papers, 'year', 'asc');
      // expect(sorted[0].dimensions.year).toBe(2017);
      // expect(sorted[1].dimensions.year).toBe(2018);
    });

    it('텍스트형 차원은 알파벳/한글 기준으로 정렬되어야 한다', () => {
      // const sorted = sortByDimension(papers, 'method', 'asc');
      // 'Masked Language Model' < 'Transformer'
    });

    it('null 값은 정렬 시 항상 맨 뒤에 위치해야 한다', () => {
      // null인 BLEU를 가진 BERT가 항상 마지막
    });
  });

  describe('필터링 기능', () => {
    it('차원 필터 입력 시 onFilter가 호출되어야 한다', async () => {
      // render(<ComparativeTable {...defaultProps} />);
      // const user = userEvent.setup();
      // const filterInput = screen.getByPlaceholderText('차원 필터...');
      // await user.type(filterInput, 'BLEU');
      // expect(defaultProps.onFilter).toHaveBeenCalledWith('BLEU');
    });

    it('필터 적용 시 매칭되지 않는 차원 행이 숨겨져야 한다', () => {
      // 필터가 'BLEU'일 때 method, dataset 행은 숨김
    });
  });

  describe('내보내기 기능', () => {
    it('CSV 내보내기 버튼 클릭 시 onExport("csv")가 호출되어야 한다', async () => {
      // render(<ComparativeTable {...defaultProps} />);
      // const user = userEvent.setup();
      // await user.click(screen.getByRole('button', { name: /CSV/ }));
      // expect(defaultProps.onExport).toHaveBeenCalledWith('csv');
    });

    it('LaTeX 내보내기 버튼 클릭 시 onExport("latex")가 호출되어야 한다', async () => {
      // render(<ComparativeTable {...defaultProps} />);
      // const user = userEvent.setup();
      // await user.click(screen.getByRole('button', { name: /LaTeX/ }));
      // expect(defaultProps.onExport).toHaveBeenCalledWith('latex');
    });

    it('Markdown 내보내기 버튼 클릭 시 onExport("markdown")가 호출되어야 한다', async () => {
      // render(<ComparativeTable {...defaultProps} />);
      // const user = userEvent.setup();
      // await user.click(screen.getByRole('button', { name: /Markdown/ }));
      // expect(defaultProps.onExport).toHaveBeenCalledWith('markdown');
    });

    it('데이터가 없을 때 내보내기 버튼이 비활성화되어야 한다', () => {
      // const emptyData = { papers: [], dimensions_meta: {} };
      // render(<ComparativeTable {...defaultProps} data={emptyData} />);
      // expect(screen.getByRole('button', { name: /CSV/ })).toBeDisabled();
    });
  });

  describe('셀 편집', () => {
    it('셀 더블클릭 시 편집 모드에 진입해야 한다', async () => {
      // render(<ComparativeTable {...defaultProps} />);
      // const user = userEvent.setup();
      // const cell = screen.getByText('28.4');
      // await user.dblClick(cell);
      // expect(screen.getByRole('textbox')).toHaveValue('28.4');
    });

    it('편집 후 Enter 시 onCellEdit가 호출되어야 한다', async () => {
      // render(<ComparativeTable {...defaultProps} />);
      // const user = userEvent.setup();
      // await user.dblClick(screen.getByText('28.4'));
      // const input = screen.getByRole('textbox');
      // await user.clear(input);
      // await user.type(input, '29.0');
      // await user.keyboard('{Enter}');
      // expect(defaultProps.onCellEdit).toHaveBeenCalledWith(
      //   '2401.00001', 'metric_bleu', '29.0'
      // );
    });

    it('편집 중 Escape 시 편집이 취소되어야 한다', async () => {
      // render(<ComparativeTable {...defaultProps} />);
      // const user = userEvent.setup();
      // await user.dblClick(screen.getByText('28.4'));
      // await user.keyboard('{Escape}');
      // expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
      // expect(screen.getByText('28.4')).toBeInTheDocument();
    });

    it('편집 중 다른 셀 클릭 시 현재 편집이 저장되어야 한다', async () => {
      // blur event 시 자동 저장
    });
  });
});
```

### 3.2 정렬/필터 유틸 함수 테스트

**파일**: `web-ui/src/test/comparativeUtils.test.ts`

```typescript
import { describe, it, expect } from 'vitest';
// import { sortPapersByDimension, filterDimensions, formatCellValue } from '../utils/comparativeUtils';

describe('sortPapersByDimension', () => {
  const papers = [
    { paper_id: '001', title: 'A', dimensions: { year: 2020, method: 'CNN' } },
    { paper_id: '002', title: 'B', dimensions: { year: 2018, method: 'RNN' } },
    { paper_id: '003', title: 'C', dimensions: { year: null, method: 'Transformer' } },
  ];

  it('숫자형 차원을 오름차순 정렬한다', () => {
    // const result = sortPapersByDimension(papers, 'year', 'asc');
    // expect(result.map(p => p.paper_id)).toEqual(['002', '001', '003']);
  });

  it('숫자형 차원을 내림차순 정렬한다', () => {
    // const result = sortPapersByDimension(papers, 'year', 'desc');
    // expect(result.map(p => p.paper_id)).toEqual(['001', '002', '003']);
  });

  it('null 값은 항상 뒤로 보낸다', () => {
    // const result = sortPapersByDimension(papers, 'year', 'asc');
    // expect(result[result.length - 1].paper_id).toBe('003');
  });
});

describe('filterDimensions', () => {
  const allDimensions = ['method', 'dataset', 'metric_bleu', 'year', 'venue'];

  it('빈 필터는 모든 차원을 반환한다', () => {
    // expect(filterDimensions(allDimensions, '')).toEqual(allDimensions);
  });

  it('필터 텍스트에 매칭되는 차원만 반환한다', () => {
    // expect(filterDimensions(allDimensions, 'metric')).toEqual(['metric_bleu']);
  });

  it('대소문자 구분 없이 필터링한다', () => {
    // expect(filterDimensions(allDimensions, 'METHOD')).toEqual(['method']);
  });
});

describe('formatCellValue', () => {
  it('null은 "-"로 표시한다', () => {
    // expect(formatCellValue(null)).toBe('-');
  });

  it('숫자는 소수점 유지하여 표시한다', () => {
    // expect(formatCellValue(28.4)).toBe('28.4');
  });

  it('긴 텍스트는 100자로 truncate한다', () => {
    // const longText = 'A'.repeat(200);
    // const result = formatCellValue(longText);
    // expect(result.length).toBeLessThanOrEqual(103); // 100 + '...'
  });
});
```

---

## 4. 통합 테스트

### 4.1 E2E 시나리오: 논문 선택 -> 테이블 생성 -> 표시 -> 내보내기

**파일**: `web-ui/src/test/ComparativeAnalysisIntegration.test.tsx`

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
// import { setupServer } from 'msw/node';
// import { http, HttpResponse } from 'msw';

// ── MSW 서버 설정 (API Mock) ─────────────────────────────────────────

/*
const server = setupServer(
  // 비교 분석 생성 엔드포인트
  http.post('/api/comparative-analysis', async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json({
      papers: [
        {
          paper_id: body.paper_ids[0],
          title: 'Test Paper 1',
          dimensions: { method: 'CNN', year: 2020, metric_acc: 95.2 },
        },
        {
          paper_id: body.paper_ids[1],
          title: 'Test Paper 2',
          dimensions: { method: 'RNN', year: 2019, metric_acc: 91.8 },
        },
      ],
      dimensions_meta: {
        method: { label: '방법론', type: 'text' },
        year: { label: '연도', type: 'numeric' },
        metric_acc: { label: '정확도', type: 'numeric' },
      },
    });
  }),

  // CSV 내보내기 엔드포인트
  http.get('/api/comparative-analysis/export/csv', () => {
    return new HttpResponse(
      '논문,방법론,연도,정확도\nTest Paper 1,CNN,2020,95.2\nTest Paper 2,RNN,2019,91.8',
      { headers: { 'Content-Type': 'text/csv' } },
    );
  }),

  // 북마크 목록 (비교 분석에 사용할 논문 선택 소스)
  http.get('/api/bookmarks', () => {
    return HttpResponse.json({
      bookmarks: [
        {
          id: 'bm_001', title: 'Bookmark 1', session_id: 's1',
          query: 'CNN', num_papers: 3, created_at: '2026-01-01',
          tags: ['DL'], topic: 'ML',
        },
        {
          id: 'bm_002', title: 'Bookmark 2', session_id: 's2',
          query: 'RNN', num_papers: 2, created_at: '2026-01-02',
          tags: ['NLP'], topic: 'NLP',
        },
      ],
    });
  }),
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
*/

describe('비교 분석 통합 테스트', () => {
  it('논문 선택 -> 비교 분석 요청 -> 테이블 렌더링 전체 흐름', async () => {
    /*
    const user = userEvent.setup();

    // 1. MyPage 또는 비교 분석 페이지 렌더링
    render(<ComparativeAnalysisPage />);

    // 2. 북마크에서 논문 선택
    await waitFor(() => {
      expect(screen.getByText('Bookmark 1')).toBeInTheDocument();
    });

    await user.click(screen.getByText('Bookmark 1'));
    await user.click(screen.getByText('Bookmark 2'));

    // 3. '비교 분석 시작' 버튼 클릭
    await user.click(screen.getByRole('button', { name: /비교 분석/ }));

    // 4. 로딩 상태 확인
    expect(screen.getByText(/분석 중/)).toBeInTheDocument();

    // 5. 테이블 렌더링 확인
    await waitFor(() => {
      expect(screen.getByText('Test Paper 1')).toBeInTheDocument();
      expect(screen.getByText('Test Paper 2')).toBeInTheDocument();
      expect(screen.getByText('95.2')).toBeInTheDocument();
    });

    // 6. CSV 내보내기
    await user.click(screen.getByRole('button', { name: /CSV/ }));
    // 다운로드 트리거 확인 (URL.createObjectURL mock 필요)
    */
  });

  it('비교 분석 중 네트워크 에러 시 에러 UI 표시', async () => {
    /*
    server.use(
      http.post('/api/comparative-analysis', () => {
        return HttpResponse.error();
      }),
    );

    const user = userEvent.setup();
    render(<ComparativeAnalysisPage />);

    // 논문 선택 후 분석 시작
    await user.click(screen.getByRole('button', { name: /비교 분석/ }));

    await waitFor(() => {
      expect(screen.getByText(/에러가 발생했습니다/)).toBeInTheDocument();
    });
    */
  });

  it('LLM 타임아웃 시 재시도 가능', async () => {
    /*
    let callCount = 0;
    server.use(
      http.post('/api/comparative-analysis', () => {
        callCount++;
        if (callCount === 1) {
          return HttpResponse.json(
            { detail: 'LLM analysis timed out. Please retry.' },
            { status: 504 },
          );
        }
        return HttpResponse.json(mockComparisonData);
      }),
    );

    const user = userEvent.setup();
    render(<ComparativeAnalysisPage />);

    await user.click(screen.getByRole('button', { name: /비교 분석/ }));
    await waitFor(() => {
      expect(screen.getByText(/시간 초과/)).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /재시도/ }));
    await waitFor(() => {
      expect(screen.getByText('Attention Is All You Need')).toBeInTheDocument();
    });
    */
  });
});
```

### 4.2 북마크 시스템 연동 테스트

```typescript
describe('북마크-비교분석 연동', () => {
  it('체크박스로 선택된 북마크의 논문들이 비교 분석 대상으로 전달된다', async () => {
    /*
    const user = userEvent.setup();
    render(<MyPage />);

    // 북마크 체크박스 선택
    const checkboxes = screen.getAllByRole('checkbox');
    await user.click(checkboxes[0]);
    await user.click(checkboxes[1]);

    // 비교 분석 버튼 활성화 확인
    const compareBtn = screen.getByRole('button', { name: /비교 분석/ });
    expect(compareBtn).not.toBeDisabled();

    // 클릭 시 올바른 paper_ids가 API로 전송되는지 확인
    await user.click(compareBtn);
    // MSW handler에서 request body 검증
    */
  });

  it('비교 분석 결과를 새 북마크로 저장할 수 있다', async () => {
    /*
    // 비교 분석 결과가 표시된 후
    // '분석 결과 저장' 버튼 클릭 시 /api/bookmarks POST 호출
    */
  });
});
```

---

## 5. 엣지 케이스

### 5.1 백엔드 엣지 케이스

```python
class TestEdgeCases:
    """비교 분석의 다양한 엣지 케이스 테스트."""

    def test_paper_with_no_extractable_metrics(self):
        """추출 가능한 메트릭이 없는 논문 (예: 서베이 논문)."""
        # survey_paper = {
        #     "id": "survey_001",
        #     "title": "A Survey of Deep Learning",
        #     "abstract": "This paper provides a comprehensive survey...",
        # }
        # LLM 응답에서 대부분의 numeric 차원이 null
        # result = extract_comparison_data(client, [survey_paper])
        # assert all(v is None for k, v in result["papers"][0]["dimensions"].items()
        #            if result["dimensions_meta"][k]["type"] == "numeric")
        pass

    def test_large_table_20_papers_15_dimensions(self):
        """20편 이상의 논문, 15개 이상의 차원을 가진 대형 테이블."""
        # papers = [{"id": f"paper_{i}", "title": f"Paper {i}",
        #            "abstract": f"Abstract {i}"} for i in range(25)]
        #
        # LLM 호출 시 토큰 제한 확인:
        # - 입력 프롬프트 크기가 max_tokens 이내인지
        # - 출력 JSON 크기가 합리적인지
        # - 필요시 배치 분할 처리가 되는지
        #
        # result = extract_comparison_data(client, papers)
        # assert len(result["papers"]) == 25
        # assert len(result["dimensions_meta"]) >= 10
        pass

    def test_large_table_performance(self):
        """대형 테이블의 응답 시간이 30초 이내여야 한다."""
        # import time
        # start = time.time()
        # result = extract_comparison_data(client, large_papers)
        # elapsed = time.time() - start
        # assert elapsed < 30.0
        pass

    def test_mixed_language_korean_english(self):
        """한국어와 영어 논문이 혼합된 경우."""
        # papers = [
        #     {"id": "en_001", "title": "Attention Is All You Need",
        #      "abstract": "The dominant sequence..."},
        #     {"id": "kr_001", "title": "한국어 감성 분석을 위한 BERT 미세조정",
        #      "abstract": "본 연구에서는 KoBERT를 활용하여..."},
        # ]
        # result = extract_comparison_data(client, papers)
        # assert len(result["papers"]) == 2
        # 차원 레이블이 일관되게 한국어 또는 영어로 통일
        pass

    def test_duplicate_papers_deduplicated(self):
        """동일 논문이 중복 선택된 경우 중복 제거."""
        # papers = [same_paper, same_paper]
        # result = extract_comparison_data(client, papers)
        # assert len(result["papers"]) == 1
        # 또는 경고 메시지 포함
        pass

    def test_paper_with_very_long_abstract(self):
        """초록이 매우 긴 논문 (10,000자 이상) 처리."""
        # long_paper = {"id": "long_001", "title": "Long Paper",
        #               "abstract": "A" * 15000}
        # 프롬프트 구성 시 truncation이 올바르게 동작해야 함
        pass

    def test_network_failure_mid_generation(self):
        """LLM 응답 수신 중 네트워크 끊김."""
        # from openai import APIConnectionError
        # mock_client.chat.completions.create.side_effect = APIConnectionError(
        #     request=MagicMock()
        # )
        # 적절한 에러 메시지 반환 확인
        pass

    def test_empty_abstract_papers(self):
        """초록이 비어있는 논문."""
        # paper = {"id": "empty_abs", "title": "No Abstract Paper", "abstract": ""}
        # LLM에 전달 시 title과 기타 메타데이터만으로 추출 시도
        pass

    def test_special_characters_in_values(self):
        """특수문자가 포함된 값 처리 (수식, 유니코드 등)."""
        # "O(n²)" "≥ 95%" "α=0.01" 등
        pass
```

### 5.2 프론트엔드 엣지 케이스

```typescript
describe('프론트엔드 엣지 케이스', () => {
  it('20편 이상의 논문이 있을 때 가로 스크롤이 동작한다', () => {
    /*
    const manyPapers = Array.from({ length: 25 }, (_, i) => ({
      paper_id: `paper_${i}`,
      title: `Paper ${i}`,
      dimensions: { method: `Method ${i}`, year: 2020 + i },
    }));
    const data = { papers: manyPapers, dimensions_meta: { method: { label: '방법론', type: 'text' }, year: { label: '연도', type: 'numeric' } } };
    render(<ComparativeTable {...defaultProps} data={data} />);
    const tableContainer = document.querySelector('.comparative-table-container');
    expect(tableContainer).toHaveStyle({ overflowX: 'auto' });
    */
  });

  it('15개 이상의 차원이 있을 때 세로 공간이 충분하다', () => {
    // 많은 차원이 있어도 테이블이 정상 렌더링
  });

  it('차원 값이 매우 긴 텍스트일 때 셀이 깨지지 않는다', () => {
    /*
    const data = {
      papers: [{
        paper_id: '001',
        title: 'Paper',
        dimensions: { novelty: 'A'.repeat(500) },
      }],
      dimensions_meta: { novelty: { label: '기여', type: 'text' } },
    };
    render(<ComparativeTable {...defaultProps} data={data} />);
    // 텍스트가 truncate되거나 tooltip으로 표시
    */
  });

  it('모든 값이 null인 차원이 있을 때 해당 행이 회색으로 표시된다', () => {
    // 데이터가 없는 차원은 시각적으로 구분
  });

  it('브라우저 새로고침 후에도 비교 분석 결과가 유지된다', () => {
    // sessionStorage 또는 URL 파라미터 기반 상태 복원
  });
});
```

---

## 6. 품질 메트릭 및 LLM 출력 검증

### 6.1 추출 정확도 측정 방법론

```python
"""
LLM 추출 정확도를 정량적으로 측정하기 위한 평가 프레임워크.
"""

# ── 골든 데이터셋 (Ground Truth) ──────────────────────────────────────

GOLDEN_DATASET = [
    {
        "paper_id": "1706.03762",
        "title": "Attention Is All You Need",
        "expected_dimensions": {
            "method": "Transformer",
            "dataset": "WMT 2014 EN-DE",
            "metric_bleu_en_de": 28.4,
            "metric_bleu_en_fr": 41.0,
            "params": "65M",
            "year": 2017,
            "venue": "NeurIPS",
            "task": "Neural Machine Translation",
        },
    },
    {
        "paper_id": "1810.04805",
        "title": "BERT: Pre-training of Deep Bidirectional Transformers",
        "expected_dimensions": {
            "method": "Masked Language Modeling",
            "dataset": "GLUE, SQuAD",
            "metric_glue": 80.5,
            "params": "340M",
            "year": 2018,
            "venue": "NAACL",
            "task": "Language Understanding",
        },
    },
    {
        "paper_id": "2005.14165",
        "title": "Language Models are Few-Shot Learners (GPT-3)",
        "expected_dimensions": {
            "method": "Autoregressive Language Model",
            "dataset": "Common Crawl, WebText2, Books, Wikipedia",
            "metric_few_shot_acc": 76.2,
            "params": "175B",
            "year": 2020,
            "venue": "NeurIPS",
            "task": "Few-Shot Learning",
        },
    },
]


def compute_extraction_accuracy(extracted: dict, golden: dict) -> dict:
    """
    추출된 차원과 골든 데이터를 비교하여 정확도를 계산한다.

    반환값:
    - exact_match_rate: 정확히 일치하는 차원의 비율
    - semantic_match_rate: 의미적으로 일치하는 차원의 비율 (텍스트 유사도 기반)
    - numeric_accuracy: 숫자형 차원의 평균 절대 오차
    - coverage: 추출된 차원 수 / 기대 차원 수
    """
    total_dims = len(golden)
    exact_matches = 0
    semantic_matches = 0
    numeric_errors = []

    for dim_key, expected_value in golden.items():
        extracted_value = extracted.get(dim_key)

        if extracted_value is None:
            continue

        if isinstance(expected_value, (int, float)):
            if isinstance(extracted_value, (int, float)):
                error = abs(extracted_value - expected_value)
                numeric_errors.append(error)
                if error < 0.01:
                    exact_matches += 1
                    semantic_matches += 1
        else:
            # 텍스트 비교
            if str(extracted_value).strip().lower() == str(expected_value).strip().lower():
                exact_matches += 1
                semantic_matches += 1
            elif _semantic_similarity(str(extracted_value), str(expected_value)) > 0.8:
                semantic_matches += 1

    extracted_count = sum(1 for v in extracted.values() if v is not None)

    return {
        "exact_match_rate": exact_matches / total_dims if total_dims > 0 else 0,
        "semantic_match_rate": semantic_matches / total_dims if total_dims > 0 else 0,
        "numeric_mae": sum(numeric_errors) / len(numeric_errors) if numeric_errors else 0,
        "coverage": extracted_count / total_dims if total_dims > 0 else 0,
    }


def _semantic_similarity(a: str, b: str) -> float:
    """간단한 단어 겹침 기반 유사도 (Jaccard 유사도)."""
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


class TestExtractionAccuracy:
    """추출 정확도 테스트 (골든 데이터셋 기반)."""

    @pytest.mark.parametrize("golden_entry", GOLDEN_DATASET,
                             ids=[g["paper_id"] for g in GOLDEN_DATASET])
    def test_extraction_accuracy_per_paper(self, golden_entry, mock_openai_client):
        """각 골든 데이터 논문에 대해 추출 정확도가 70% 이상이어야 한다."""
        # extracted = extract_comparison_data(mock_openai_client, [golden_entry])
        # paper_result = extracted["papers"][0]["dimensions"]
        # accuracy = compute_extraction_accuracy(paper_result, golden_entry["expected_dimensions"])
        # assert accuracy["semantic_match_rate"] >= 0.7, (
        #     f"논문 {golden_entry['paper_id']}의 의미적 정확도: "
        #     f"{accuracy['semantic_match_rate']:.2%} (기준: 70%)"
        # )
        # assert accuracy["coverage"] >= 0.6, (
        #     f"논문 {golden_entry['paper_id']}의 커버리지: "
        #     f"{accuracy['coverage']:.2%} (기준: 60%)"
        # )
        pass

    def test_numeric_extraction_mae_threshold(self):
        """숫자형 메트릭의 MAE가 허용 범위 내여야 한다."""
        # 예: BLEU 점수의 오차가 0.5 이내
        pass

    def test_extraction_consistency_across_runs(self):
        """동일 입력에 대해 3회 추출 시 결과의 일관성이 80% 이상이어야 한다."""
        # results = [extract_comparison_data(client, papers) for _ in range(3)]
        # consistency = compute_consistency(results)
        # assert consistency >= 0.8
        pass
```

### 6.2 LLM 출력 품질 검증

```python
class TestLLMOutputQuality:
    """LLM 출력의 구조적/의미적 품질 검증."""

    def test_output_json_schema_valid(self):
        """LLM 출력이 기대하는 JSON 스키마를 준수해야 한다."""
        # from jsonschema import validate
        # schema = {
        #     "type": "object",
        #     "required": ["papers", "dimensions_meta"],
        #     "properties": {
        #         "papers": {
        #             "type": "array",
        #             "items": {
        #                 "type": "object",
        #                 "required": ["paper_id", "title", "dimensions"],
        #                 "properties": {
        #                     "paper_id": {"type": "string"},
        #                     "title": {"type": "string"},
        #                     "dimensions": {"type": "object"},
        #                 }
        #             }
        #         },
        #         "dimensions_meta": {
        #             "type": "object",
        #             "additionalProperties": {
        #                 "type": "object",
        #                 "properties": {
        #                     "label": {"type": "string"},
        #                     "type": {"enum": ["text", "numeric"]},
        #                 }
        #             }
        #         }
        #     }
        # }
        # validate(llm_output, schema)
        pass

    def test_dimension_labels_are_human_readable(self):
        """차원 레이블이 사람이 읽을 수 있는 한국어/영어여야 한다."""
        # for dim_key, meta in result["dimensions_meta"].items():
        #     assert len(meta["label"]) >= 2
        #     assert meta["label"] != dim_key  # key와 label이 다르면 사람 친화적
        pass

    def test_no_hallucinated_values(self):
        """LLM이 논문에 없는 값을 만들어내지 않아야 한다 (hallucination 검증)."""
        # 골든 데이터의 수치와 비교하여 터무니없는 값이 없는지 확인
        # 예: BLEU가 100 이상이거나, 연도가 미래인 경우
        pass

    def test_dimension_types_consistent(self):
        """같은 차원의 값 타입이 논문 간 일관되어야 한다."""
        # 'year' 차원의 모든 값이 숫자이거나, 'method' 차원의 모든 값이 텍스트
        pass
```

### 6.3 프롬프트 변경 회귀 테스트

```python
class TestPromptRegression:
    """프롬프트 변경 시 기존 품질이 유지되는지 검증하는 회귀 테스트."""

    REGRESSION_FIXTURES = [
        {
            "input_papers": [
                {"id": "reg_001", "title": "ResNet", "abstract": "Deep residual learning..."},
                {"id": "reg_002", "title": "VGG", "abstract": "Very deep convolutional..."},
            ],
            "expected_dimensions": ["method", "dataset", "year", "metric"],
            "expected_min_papers": 2,
        },
    ]

    @pytest.mark.parametrize("fixture", REGRESSION_FIXTURES)
    def test_prompt_change_does_not_reduce_coverage(self, fixture, mock_openai_client):
        """프롬프트 변경 후에도 추출되는 차원 수가 줄어들지 않아야 한다."""
        # result = extract_comparison_data(mock_openai_client, fixture["input_papers"])
        # extracted_dims = set(result["dimensions_meta"].keys())
        # for expected_dim in fixture["expected_dimensions"]:
        #     assert any(expected_dim in d for d in extracted_dims), (
        #         f"차원 '{expected_dim}'이 추출 결과에 없음 (프롬프트 회귀)"
        #     )
        pass

    @pytest.mark.parametrize("fixture", REGRESSION_FIXTURES)
    def test_prompt_change_does_not_reduce_paper_count(self, fixture, mock_openai_client):
        """프롬프트 변경 후에도 모든 논문이 결과에 포함되어야 한다."""
        # result = extract_comparison_data(mock_openai_client, fixture["input_papers"])
        # assert len(result["papers"]) >= fixture["expected_min_papers"]
        pass

    def test_prompt_snapshot_comparison(self):
        """프롬프트의 핵심 키워드가 유지되는지 스냅샷 비교."""
        # from routers.comparative import EXTRACTION_PROMPT_TEMPLATE
        # required_keywords = ["JSON", "dimensions", "method", "dataset", "metric"]
        # for keyword in required_keywords:
        #     assert keyword.lower() in EXTRACTION_PROMPT_TEMPLATE.lower(), (
        #         f"프롬프트에서 필수 키워드 '{keyword}'가 제거됨"
        #     )
        pass
```

---

## 7. 테스트 데이터 (Fixtures)

### 7.1 Mock 논문 데이터

**파일**: `tests/fixtures/mock_papers.json`

```json
{
  "standard_papers": [
    {
      "id": "2401.00001",
      "title": "Attention Is All You Need",
      "authors": [
        {"name": "Ashish Vaswani"},
        {"name": "Noam Shazeer"},
        {"name": "Niki Parmar"}
      ],
      "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.",
      "year": 2017,
      "venue": "NeurIPS",
      "categories": ["cs.CL", "cs.LG"],
      "citations": 120000,
      "url": "https://arxiv.org/abs/1706.03762"
    },
    {
      "id": "2401.00002",
      "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
      "authors": [
        {"name": "Jacob Devlin"},
        {"name": "Ming-Wei Chang"},
        {"name": "Kenton Lee"},
        {"name": "Kristina Toutanova"}
      ],
      "abstract": "We introduce a new language representation model called BERT, which stands for Bidirectional Encoder Representations from Transformers. Unlike recent language representation models, BERT is designed to pre-train deep bidirectional representations from unlabeled text by jointly conditioning on both left and right context in all layers.",
      "year": 2018,
      "venue": "NAACL",
      "categories": ["cs.CL"],
      "citations": 85000,
      "url": "https://arxiv.org/abs/1810.04805"
    },
    {
      "id": "2401.00003",
      "title": "Language Models are Few-Shot Learners",
      "authors": [
        {"name": "Tom B. Brown"},
        {"name": "Benjamin Mann"},
        {"name": "Nick Ryder"}
      ],
      "abstract": "Recent work has demonstrated substantial gains on many NLP tasks and benchmarks by pre-training on a large corpus of text followed by fine-tuning on a specific task. While typically task-agnostic in architecture, this method still requires task-specific fine-tuning datasets of thousands or tens of thousands of examples. By contrast, humans can generally perform a new language task from only a few examples or from simple instructions.",
      "year": 2020,
      "venue": "NeurIPS",
      "categories": ["cs.CL", "cs.LG"],
      "citations": 35000,
      "url": "https://arxiv.org/abs/2005.14165"
    }
  ],

  "korean_papers": [
    {
      "id": "kr_001",
      "title": "KoBERT: 한국어 자연어처리를 위한 사전학습 언어 모델",
      "authors": [{"name": "김지수"}, {"name": "박영진"}],
      "abstract": "본 연구에서는 한국어에 특화된 BERT 기반 사전학습 모델 KoBERT를 제안한다. SentencePiece 토크나이저를 활용하여 한국어의 교착어적 특성을 반영하였으며, 네이버 뉴스와 위키피디아 한국어판을 학습 데이터로 사용하였다.",
      "year": 2019,
      "venue": "한국정보과학회",
      "categories": ["cs.CL"],
      "citations": 500
    }
  ],

  "edge_case_papers": {
    "no_abstract": {
      "id": "edge_001",
      "title": "Paper Without Abstract",
      "authors": [{"name": "Author"}],
      "abstract": "",
      "year": 2023
    },
    "very_long_abstract": {
      "id": "edge_002",
      "title": "Paper With Extremely Long Abstract",
      "authors": [{"name": "Author"}],
      "abstract": "Lorem ipsum dolor sit amet... [15000자 이상의 텍스트]",
      "year": 2023
    },
    "special_characters": {
      "id": "edge_003",
      "title": "O(n²) Complexity: α-β Pruning for ≥95% Accuracy",
      "authors": [{"name": "Author & Co-Author"}],
      "abstract": "We achieve ≥95% accuracy with O(n²) time complexity using α=0.01, β=0.99...",
      "year": 2023
    },
    "no_metrics": {
      "id": "edge_004",
      "title": "A Comprehensive Survey of Deep Learning",
      "authors": [{"name": "Survey Author"}],
      "abstract": "This paper provides a comprehensive overview of recent advances in deep learning, covering architectures, training methods, and applications...",
      "year": 2024
    }
  }
}
```

### 7.2 기대 추출 결과

**파일**: `tests/fixtures/expected_extractions.json`

```json
{
  "standard_extraction": {
    "papers": [
      {
        "paper_id": "2401.00001",
        "title": "Attention Is All You Need",
        "dimensions": {
          "method": "Transformer (Self-Attention Mechanism)",
          "dataset": "WMT 2014 EN-DE, WMT 2014 EN-FR",
          "metric_bleu_ende": 28.4,
          "metric_bleu_enfr": 41.0,
          "params": "65M",
          "year": 2017,
          "venue": "NeurIPS",
          "task": "Neural Machine Translation",
          "novelty": "순수 attention 기반 encoder-decoder 아키텍처",
          "limitation": "O(n^2) 메모리 복잡도로 긴 시퀀스 처리 비효율적"
        }
      },
      {
        "paper_id": "2401.00002",
        "title": "BERT",
        "dimensions": {
          "method": "Masked Language Model + Next Sentence Prediction",
          "dataset": "BooksCorpus, English Wikipedia (3.3B words)",
          "metric_bleu_ende": null,
          "metric_bleu_enfr": null,
          "params": "110M (Base) / 340M (Large)",
          "year": 2018,
          "venue": "NAACL",
          "task": "Language Understanding (GLUE, SQuAD)",
          "novelty": "양방향 Transformer 사전학습",
          "limitation": "사전학습 비용이 높고 [MASK] 토큰이 fine-tuning 시 불일치"
        }
      }
    ],
    "dimensions_meta": {
      "method": {"label": "핵심 방법론", "type": "text"},
      "dataset": {"label": "학습/평가 데이터", "type": "text"},
      "metric_bleu_ende": {"label": "BLEU (EN-DE)", "type": "numeric"},
      "metric_bleu_enfr": {"label": "BLEU (EN-FR)", "type": "numeric"},
      "params": {"label": "모델 파라미터", "type": "text"},
      "year": {"label": "발표 연도", "type": "numeric"},
      "venue": {"label": "발표 학회", "type": "text"},
      "task": {"label": "연구 과제", "type": "text"},
      "novelty": {"label": "핵심 기여", "type": "text"},
      "limitation": {"label": "한계점", "type": "text"}
    }
  },

  "edge_case_no_metrics": {
    "papers": [
      {
        "paper_id": "edge_004",
        "title": "A Comprehensive Survey of Deep Learning",
        "dimensions": {
          "method": "Survey / Literature Review",
          "dataset": null,
          "metric_bleu": null,
          "params": null,
          "year": 2024,
          "venue": null,
          "task": "Survey",
          "novelty": "최신 딥러닝 발전 동향 종합 분석",
          "limitation": "실험적 검증 없음"
        }
      }
    ]
  }
}
```

### 7.3 프론트엔드 Mock 데이터

**파일**: `web-ui/src/test/fixtures/comparativeFixtures.ts`

```typescript
export const mockComparisonResponse = {
  papers: [
    {
      paper_id: '2401.00001',
      title: 'Attention Is All You Need',
      dimensions: {
        method: 'Transformer',
        dataset: 'WMT 2014',
        metric_bleu: 28.4,
        year: 2017,
        venue: 'NeurIPS',
        task: 'Machine Translation',
        novelty: 'Self-attention 기반 아키텍처',
        limitation: 'O(n^2) 메모리 복잡도',
      },
    },
    {
      paper_id: '2401.00002',
      title: 'BERT',
      dimensions: {
        method: 'Masked LM',
        dataset: 'Wikipedia + BooksCorpus',
        metric_bleu: null,
        year: 2018,
        venue: 'NAACL',
        task: 'Language Understanding',
        novelty: '양방향 사전학습',
        limitation: '높은 사전학습 비용',
      },
    },
  ],
  dimensions_meta: {
    method: { label: '방법론', type: 'text' as const },
    dataset: { label: '데이터셋', type: 'text' as const },
    metric_bleu: { label: 'BLEU', type: 'numeric' as const },
    year: { label: '연도', type: 'numeric' as const },
    venue: { label: '학회', type: 'text' as const },
    task: { label: '과제', type: 'text' as const },
    novelty: { label: '핵심 기여', type: 'text' as const },
    limitation: { label: '한계점', type: 'text' as const },
  },
};

export const mockEmptyComparison = {
  papers: [],
  dimensions_meta: {},
};

export const mockLargeComparison = {
  papers: Array.from({ length: 25 }, (_, i) => ({
    paper_id: `paper_${i}`,
    title: `Paper ${i}: A Study on Topic ${i}`,
    dimensions: Object.fromEntries(
      Array.from({ length: 15 }, (_, j) => [
        `dim_${j}`,
        j < 5 ? Math.random() * 100 : `Value ${i}-${j}`,
      ])
    ),
  })),
  dimensions_meta: Object.fromEntries(
    Array.from({ length: 15 }, (_, j) => [
      `dim_${j}`,
      { label: `Dimension ${j}`, type: j < 5 ? 'numeric' as const : 'text' as const },
    ])
  ),
};

export const mockExportCSV =
  '논문,방법론,BLEU,연도\nAttention Is All You Need,Transformer,28.4,2017\nBERT,Masked LM,-,2018\n';

export const mockExportMarkdown = `| 논문 | 방법론 | BLEU | 연도 |
|------|--------|------|------|
| Attention Is All You Need | Transformer | 28.4 | 2017 |
| BERT | Masked LM | - | 2018 |`;

export const mockExportLatex = `\\begin{tabular}{|l|l|r|r|}
\\hline
논문 & 방법론 & BLEU & 연도 \\\\
\\hline
Attention Is All You Need & Transformer & 28.4 & 2017 \\\\
BERT & Masked LM & - & 2018 \\\\
\\hline
\\end{tabular}`;
```

---

## 8. 실행 계획 및 CI 통합

### 8.1 테스트 실행 명령어

```bash
# 백엔드 테스트
cd /Users/gimjiseong/git/PaperReviewAgent
pytest tests/test_comparative_extraction.py -v --tb=short

# 프론트엔드 테스트
cd web-ui && npm run test -- --filter="ComparativeTable"
cd web-ui && npm run test -- --filter="comparativeUtils"

# 전체 테스트
pytest tests/ -v --cov=routers --cov-report=html
cd web-ui && npm run test
```

### 8.2 추가 설치 필요 패키지

```bash
# 백엔드
pip install pytest pytest-asyncio pytest-cov httpx jsonschema

# 프론트엔드 (통합 테스트용)
cd web-ui && npm install -D msw
```

### 8.3 테스트 우선순위

| 우선순위 | 테스트 영역 | 이유 |
|---------|-----------|------|
| P0 (필수) | LLM 응답 파싱 + JSON 유효성 | 전체 기능의 핵심. 파싱 실패 시 전체 기능 불가 |
| P0 (필수) | API 엔드포인트 기본 요청/응답 | 프론트-백엔드 통신의 기본 계약 |
| P0 (필수) | 에러 핸들링 (timeout, rate limit) | 사용자 경험과 안정성 직결 |
| P1 (중요) | 내보내기 포맷터 (CSV, LaTeX, MD) | 사용자의 핵심 사용 목적 |
| P1 (중요) | ComparativeTable 렌더링 | UI 정상 동작 확인 |
| P1 (중요) | 차원 정렬/정규화 | 데이터 정합성 |
| P2 (권장) | 셀 편집 기능 | 부가 기능 |
| P2 (권장) | 대형 테이블 성능 | 엣지 케이스 |
| P2 (권장) | 추출 정확도 골든 테스트 | 장기적 품질 유지 |
| P3 (향후) | E2E 통합 테스트 (Playwright) | 전체 흐름 자동화 |
| P3 (향후) | 프롬프트 회귀 테스트 | LLM 프롬프트 변경 추적 |

### 8.4 품질 기준 (Quality Gates)

| 메트릭 | 기준값 | 측정 방법 |
|--------|-------|----------|
| 코드 커버리지 (백엔드) | >= 80% | pytest-cov |
| 코드 커버리지 (프론트엔드) | >= 75% | vitest --coverage |
| LLM 추출 정확도 (semantic) | >= 70% | 골든 데이터셋 비교 |
| LLM 추출 커버리지 | >= 60% | 기대 차원 대비 추출 비율 |
| API 응답 시간 (mock LLM) | < 200ms | 엔드포인트 테스트 내 시간 측정 |
| API 응답 시간 (실 LLM) | < 30s | 수동 성능 테스트 |
| 프론트엔드 테스트 실행 시간 | < 10s | Vitest 실행 시간 |
| 에러 복구율 | 100% | 모든 에러 케이스에서 graceful 처리 확인 |

### 8.5 CI 파이프라인 통합 (향후)

```yaml
# .github/workflows/test-comparative.yml (참고용)
name: Comparative Analysis Tests
on:
  push:
    paths:
      - 'routers/comparative*.py'
      - 'web-ui/src/components/mypage/ComparativeTable*'
      - 'tests/test_comparative*'
      - 'web-ui/src/test/Comparative*'

jobs:
  backend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pytest tests/test_comparative_extraction.py -v --cov

  frontend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: cd web-ui && npm ci
      - run: cd web-ui && npm run test -- --filter="Comparative"
```

---

## 부록: 테스트 체크리스트

### 기능 출시 전 반드시 확인해야 할 항목

- [ ] LLM 추출 프롬프트가 JSON 형식 응답을 유도하는가?
- [ ] JSON 파싱 실패 시 graceful fallback이 있는가?
- [ ] 모든 내보내기 형식(CSV/LaTeX/MD)에서 특수문자가 이스케이프되는가?
- [ ] null 값이 UI와 내보내기에서 일관되게 처리되는가?
- [ ] 인증 없는 요청이 401로 거부되는가?
- [ ] LLM timeout 시 사용자에게 재시도 안내가 표시되는가?
- [ ] 20편 이상의 논문에서도 테이블이 정상 렌더링되는가?
- [ ] 한국어 논문이 포함된 경우 인코딩 문제가 없는가?
- [ ] 셀 편집 후 데이터 정합성이 유지되는가?
- [ ] 비교 분석 결과가 북마크 시스템과 올바르게 연동되는가?

---

*본 테스트 전략은 QA Validator Agent에 의해 작성되었습니다.*
*프로젝트 구조 분석 기반: api_server.py, routers/, web-ui/src/ 코드베이스 참조*
