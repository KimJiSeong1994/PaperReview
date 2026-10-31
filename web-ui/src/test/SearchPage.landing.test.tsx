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

vi.mock('../api/recommendations', () => ({
  fetchRecommendationNotifications: vi.fn().mockResolvedValue({
    items: [], unread_count: 0, total_count: 0, latest_run_at: null, run_id: null,
    scoring_mode: null, state: 'idle', freshness: 'fresh', source_statuses: {}, degraded_reasons: [],
  }),
}));
vi.mock('../api/bookmarks', () => ({ getBookmarks: vi.fn().mockResolvedValue([]) }));
vi.mock('../api/curriculum', () => ({ fetchCurricula: vi.fn().mockResolvedValue({ curricula: [] }) }));
vi.mock('../api/me', () => ({ fetchMyReviewSessions: vi.fn().mockResolvedValue({ sessions: [], total: 0 }) }));
vi.mock('../api/blog', () => ({ fetchBlogPosts: vi.fn().mockResolvedValue({ data: { posts: [] } }) }));

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

  it('asks one question over a composer and offers verb-first task rows', () => {
    renderHome();
    expect(screen.getByRole('textbox', { name: '검색어' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '집현전에 이런 걸 맡겨 보세요' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /비교 리뷰/ })).toBeTruthy();
    expect(screen.getByRole('link', { name: /커리큘럼 짜기/ })).toBeTruthy();
  });

  // A task row exists to start work, so the wiring is the whole point: the
  // comparison row must call handleSearch directly because we are already on "/".
  it('runs the comparison query when its task row is clicked', async () => {
    renderHome();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /GraphRAG와 기존 RAG, 무엇이 달라졌는지 비교 리뷰/ }));
    });
    expect(searchPapers).toHaveBeenCalledTimes(1);
    expect(vi.mocked(searchPapers).mock.calls[0][0]).toMatchObject({
      query: 'GraphRAG와 기존 RAG 비교',
    });
  });

  it('submits the composer with Enter and keeps Shift+Enter for a new line', async () => {
    renderHome();
    const box = screen.getByRole('textbox', { name: '검색어' });
    await act(async () => {
      fireEvent.change(box, { target: { value: '그래프 신경망' } });
      fireEvent.keyDown(box, { key: 'Enter', shiftKey: true });
    });
    expect(searchPapers).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.keyDown(box, { key: 'Enter' });
    });
    expect(vi.mocked(searchPapers).mock.calls[0][0]).toMatchObject({ query: '그래프 신경망' });
  });

  it('keeps the h1 byte-identical to the pre-hydration copy', () => {
    renderHome();
    // web-ui/index.html ships this exact H1 before React mounts. If they drift,
    // JS-rendering and non-JS crawlers see different headings for the same URL.
    expect(document.querySelector('h1.home-title')?.textContent?.trim()).toBe(
      '오늘은 어떤 논문부터 볼까요?',
    );
  });

  it('says search needs no login, and offers a way to read more', () => {
    renderHome();
    expect(screen.getByText('검색은 로그인 없이 바로 시작할 수 있습니다.')).toBeTruthy();
    expect(
      screen.getByRole('link', { name: /집현전 사용법 자세히 보기/ }).getAttribute('href'),
    ).toBe('/ko/introduce/');
  });
});
