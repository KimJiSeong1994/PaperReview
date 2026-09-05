import { beforeEach, describe, expect, it, vi } from 'vitest';
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

function renderHome() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <SearchPage />
    </MemoryRouter>,
  );
}

describe('homepage landing content', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.scrollTo = vi.fn();
    vi.mocked(searchPapers).mockResolvedValue({ results: {}, total: 0 } as never);
  });

  it('offers four example queries under the search box', () => {
    renderHome();
    expect(screen.getAllByRole('button', { name: /./ }).length).toBeGreaterThan(0);
    expect(document.querySelectorAll('.home-chip')).toHaveLength(4);
    expect(screen.getByRole('list', { name: '예시 검색어' })).toBeTruthy();
  });

  // The chips exist to start a search, so the wiring is the whole point: a chip
  // that renders but does not search is worse than no chip. IntroducePage routes
  // the same strings through ?q= because it sits on another route; here we are
  // already on "/", so the call must go straight to handleSearch.
  it('runs the query when a chip is clicked', async () => {
    renderHome();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '그래프 신경망' }));
    });
    // searchPapers takes (payload, abortSignal), so assert on the payload
    // rather than the whole argument list.
    expect(searchPapers).toHaveBeenCalledTimes(1);
    expect(vi.mocked(searchPapers).mock.calls[0][0]).toMatchObject({
      query: '그래프 신경망',
    });
  });

  it('shows one comparison query, not four topic keywords', () => {
    renderHome();
    // Verified against QueryAnalyzer.analyze_query: this one classifies as
    // intent=comparison (conf 0.97) where the bare topic nouns classify as
    // topic_exploration. It is here to show the corpus answers comparisons,
    // not because it is faster — nothing reachable through this analyzer is.
    expect(screen.getByRole('button', { name: 'GraphRAG와 기존 RAG 비교' })).toBeTruthy();
  });

  it('keeps the brand h1 byte-identical to the pre-hydration copy', () => {
    renderHome();
    // web-ui/index.html ships this exact H1 before React mounts. If they drift,
    // JS-rendering and non-JS crawlers see different headings for the same URL.
    expect(document.querySelector('h1.brand-title')?.textContent?.trim()).toBe(
      'Jiphyeonjeon (집현전)',
    );
  });

  it('says search needs no login, and offers a way to read more', () => {
    renderHome();
    expect(screen.getByText('검색은 로그인 없이 바로 시작할 수 있습니다.')).toBeTruthy();
    expect(
      screen.getByRole('link', { name: '집현전 사용법 자세히 보기' }).getAttribute('href'),
    ).toBe('/ko/introduce/');
  });
});
