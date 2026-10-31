import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation, useParams } from 'react-router-dom';
import SearchPage from '../components/SearchPage';
import { createConversation, searchPapers } from '../api/client';

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
    createConversation: vi.fn(),
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
vi.mock('../api/conversations', () => ({ fetchMyConversations: vi.fn().mockResolvedValue([]) }));
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

function ConversationProbe() {
  const { id } = useParams();
  const location = useLocation();
  return <p>{`conversation ${id} run=${String((location.state as { run?: boolean } | null)?.run)}`}</p>;
}

function routes() {
  return (
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<SearchPage />} />
        <Route path="/c/:id" element={<ConversationProbe />} />
      </Routes>
    </MemoryRouter>
  );
}

function renderHome() {
  return render(routes());
}

describe('homepage landing content', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.isAuthenticated = false;
    window.scrollTo = vi.fn();
    vi.mocked(searchPapers).mockResolvedValue({ results: {}, total: 0 } as never);
    vi.mocked(createConversation).mockResolvedValue({ id: 'conv-1', title: 't', turn_id: 'turn-1' });
  });

  it('asks one question over a composer and offers verb-first task rows', () => {
    renderHome();
    expect(screen.getByRole('textbox', { name: '논문 검색' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '집현전에 이런 걸 맡겨 보세요' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /비교 리뷰/ })).toBeTruthy();
    expect(screen.getByRole('link', { name: /커리큘럼 짜기/ })).toBeTruthy();
  });

  // A task row exists to start work, so the wiring is the whole point: the
  // comparison row starts a conversation and opens it with the run flag.
  it('starts a conversation from the comparison task row', async () => {
    authState.isAuthenticated = true;
    renderHome();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /GraphRAG와 기존 RAG, 무엇이 달라졌는지 비교 리뷰/ }));
    });
    expect(createConversation).toHaveBeenCalledWith('GraphRAG와 기존 RAG 비교');
    expect(searchPapers).not.toHaveBeenCalled();
    expect(screen.getByText('conversation conv-1 run=true')).toBeTruthy();
  });

  it('falls back to the direct results search when the conversation cannot be created', async () => {
    authState.isAuthenticated = true;
    vi.mocked(createConversation).mockRejectedValueOnce(new Error('503'));
    renderHome();
    const box = screen.getByRole('textbox', { name: '논문 검색' });
    await act(async () => {
      fireEvent.change(box, { target: { value: '그래프 신경망' } });
      fireEvent.keyDown(box, { key: 'Enter' });
    });
    expect(vi.mocked(searchPapers).mock.calls[0][0]).toMatchObject({ query: '그래프 신경망' });
  });

  it('submits the composer with Enter and keeps Shift+Enter for a new line', async () => {
    authState.isAuthenticated = true;
    renderHome();
    const box = screen.getByRole('textbox', { name: '논문 검색' });
    await act(async () => {
      fireEvent.change(box, { target: { value: '그래프 신경망' } });
      fireEvent.keyDown(box, { key: 'Enter', shiftKey: true });
    });
    expect(createConversation).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.keyDown(box, { key: 'Enter' });
    });
    expect(createConversation).toHaveBeenCalledWith('그래프 신경망');
  });

  it('keeps the h1 byte-identical to the pre-hydration copy', () => {
    renderHome();
    // web-ui/index.html ships this exact H1 before React mounts. If they drift,
    // JS-rendering and non-JS crawlers see different headings for the same URL.
    expect(document.querySelector('h1.home-title')?.textContent?.trim()).toBe(
      '오늘은 어떤 논문부터 볼까요?',
    );
  });

  // Search is a signed-in feature: a guest submission opens the login dialog,
  // sends nothing, and keeps the query so it can run right after sign-in.
  it('asks guests to sign in instead of searching, then starts the conversation', async () => {
    const { rerender } = renderHome();
    const box = screen.getByRole('textbox', { name: '논문 검색' });
    await act(async () => {
      fireEvent.change(box, { target: { value: '그래프 신경망' } });
      fireEvent.keyDown(box, { key: 'Enter' });
    });
    expect(authState.setShowLoginModal).toHaveBeenCalledWith(true);
    expect(createConversation).not.toHaveBeenCalled();
    expect(searchPapers).not.toHaveBeenCalled();

    authState.isAuthenticated = true;
    await act(async () => {
      rerender(routes());
    });
    expect(createConversation).toHaveBeenCalledWith('그래프 신경망');
    expect(screen.getByText('conversation conv-1 run=true')).toBeTruthy();
  });

  it('says search needs sign-in, and offers a way to read more', () => {
    renderHome();
    expect(screen.getByText('검색은 로그인 후 이용할 수 있어요. 공개 리뷰는 바로 읽을 수 있습니다.')).toBeTruthy();
    expect(
      screen.getByRole('link', { name: /집현전 사용법 자세히 보기/ }).getAttribute('href'),
    ).toBe('/ko/introduce/');
  });
});
