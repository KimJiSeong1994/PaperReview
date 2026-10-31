import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SearchPage from '../components/SearchPage';
import { searchPapers } from '../api/client';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const authState = vi.hoisted(() => ({
  isAuthenticated: false,
  setShowLoginModal: vi.fn(),
}));

vi.mock('../api/client', async () => {
  const reviewApi = await vi.importActual<typeof import('../api/review')>('../api/review');
  return {
    classifyPosterError: reviewApi.classifyPosterError,
    classifyPosterResponse: reviewApi.classifyPosterResponse,
    fetchBatchReferences: vi.fn(),
    generatePoster: vi.fn(),
    generatePosterDirect: vi.fn(),
    getGraphData: vi.fn(),
    saveBookmark: vi.fn(),
    searchPapers: vi.fn(),
    startDeepReview: vi.fn(),
    trackSearchClick: vi.fn(),
  };
});

vi.mock('../hooks/useDeepReview', () => ({
  useDeepReview: () => ({
    reviewStatus: 'idle',
    reviewProgress: '',
    reviewReport: null,
    reviewSessionId: null,
    startReview: vi.fn(),
    resetReview: vi.fn(),
  }),
}));

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => authState }));

vi.mock('../analytics/events', () => ({
  trackBookmarkSave: vi.fn(),
  trackDeepReviewComplete: vi.fn(),
  trackDeepReviewFail: vi.fn(),
  trackDeepReviewStart: vi.fn(),
  trackPaperSelect: vi.fn(),
  trackPosterGenerateComplete: vi.fn(),
  trackPosterGenerateFail: vi.fn(),
  trackPosterGenerateStart: vi.fn(),
  trackReportDownload: vi.fn(),
  trackSearchEvent: vi.fn(),
}));

function renderSearchPage() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <SearchPage />
    </MemoryRouter>,
  );
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function submit(query: string) {
  await act(async () => {
    fireEvent.change(screen.getByPlaceholderText('논문 검색'), {
      target: { value: query },
    });
    fireEvent.click(screen.getByRole('button', { name: '논문 검색' }));
  });
}

describe('SearchPage failure recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.scrollTo = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // A request that fails *slowly* is the case that matters: handleSearch arms a
  // 500ms timer that sets `query` so the loading screen can appear, and only
  // then does the request settle. That leaves papers empty AND query set, which
  // is exactly the condition the zero-result branch matches on — so before the
  // guard, a 504 rendered "try different keywords" underneath its own error.
  async function failSlowly(query: string, reason: unknown) {
    const deferred = createDeferred<never>();
    vi.mocked(searchPapers).mockReturnValue(deferred.promise as never);

    renderSearchPage();
    await submit(query);
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    await act(async () => {
      deferred.reject(reason);
      await deferred.promise.catch(() => {});
    });
  }

  it('does not blame the query when the server is what failed', async () => {
    await failSlowly('transformer attention', new Error('Request failed with status code 504'));

    expect(screen.getByText(/검색 중 오류가 발생했습니다/)).toBeTruthy();
    expect(screen.queryByText(/검색 결과가 없습니다/)).toBeNull();
  });

  it('hands the submitted query back after a failure', async () => {
    await failSlowly('transformer attention', new Error('boom'));

    expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('transformer attention');
  });

  it('leaves the non-academic hint up long enough to read', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: {},
      total: 0,
      query_analysis: { is_academic: false },
    } as never);

    renderSearchPage();
    await submit('점심 메뉴 추천');

    expect(screen.getByText(/학술 논문 및 연구 관련 주제를 입력해주세요/)).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(7000);
    });
    expect(screen.getByText(/학술 논문 및 연구 관련 주제를 입력해주세요/)).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.queryByText(/학술 논문 및 연구 관련 주제를 입력해주세요/)).toBeNull();
  });
});
