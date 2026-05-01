import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SearchPage from '../components/SearchPage';

const { searchStreamMock } = vi.hoisted(() => ({
  searchStreamMock: vi.fn(),
}));

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    setShowLoginModal: vi.fn(),
  }),
}));

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    searchStream: searchStreamMock,
    searchPapers: vi.fn(),
    getGraphData: vi.fn().mockResolvedValue({ nodes: [], edges: [] }),
    fetchBatchReferences: vi.fn().mockResolvedValue({ references: [] }),
    startDeepReview: vi.fn(),
    saveBookmark: vi.fn(),
    generatePoster: vi.fn(),
    generatePosterDirect: vi.fn(),
  };
});

vi.mock('../components/PaperList', () => ({
  default: () => <div data-testid="paper-list" />,
}));

vi.mock('../components/DetailPanel', () => ({
  default: () => <div data-testid="detail-panel" />,
}));

vi.mock('../components/GraphView', () => ({
  default: () => <div data-testid="graph-view" />,
}));

describe('SearchPage search SSE progress', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    searchStreamMock.mockReset();
    searchStreamMock.mockImplementation(async (_request, callbacks) => {
      setTimeout(() => {
        callbacks.onProgress?.({
          stage: 'query_analysis',
          status: 'running',
          message: '질문 의도와 검색 키워드를 분석 중입니다.',
          detail: {},
        });
      }, 10);
      setTimeout(() => {
        callbacks.onProgress?.({
          stage: 'source_search',
          status: 'running',
          message: '관련 논문을 여러 데이터베이스에서 수집 중입니다.',
          detail: {},
        });
      }, 20);
      setTimeout(() => {
        callbacks.onComplete?.({
          results: { arxiv: [] },
          total: 0,
          query_analysis: {
            intent: 'paper_search',
            keywords: ['transformer'],
            improved_query: 'transformer',
            search_filters: {},
            confidence: 0.9,
            original_query: 'transformer',
          },
        });
      }, 1000);
    });
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it('renders SSE stage text and progress when search is running', async () => {
    render(
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText('Search papers...'), { target: { value: 'transformer' } });
    fireEvent.click(screen.getByTitle('Search'));

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(screen.getAllByText('쿼리 분석')[0]).toBeInTheDocument();
    expect(screen.getByText('질문 의도와 검색 키워드를 분석 중입니다.')).toBeInTheDocument();
    expect(screen.getByText('12%')).toBeInTheDocument();

    expect(searchStreamMock).toHaveBeenCalledTimes(1);
  });

  it('clears the loading state once the stream completes', async () => {
    render(
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText('Search papers...'), { target: { value: 'transformer' } });
    fireEvent.click(screen.getByTitle('Search'));

    await act(async () => {
      vi.advanceTimersByTime(1200);
    });

    expect(screen.queryByText('결과를 분석하고 있습니다...')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Search progress stages')).not.toBeInTheDocument();
  });
});
