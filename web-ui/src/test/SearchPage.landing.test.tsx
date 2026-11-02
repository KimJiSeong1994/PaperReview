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
const samplesApi = vi.hoisted(() => ({
  fetchSampleConversations: vi.fn(),
  fetchSampleConversation: vi.fn(),
}));
vi.mock('../api/samples', () => samplesApi);
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
    samplesApi.fetchSampleConversations.mockResolvedValue([]);
  });

  it('asks one question over a composer and offers verb-first task rows', () => {
    // The task rows are the signed-in home's; guests get sample conversations instead.
    authState.isAuthenticated = true;
    renderHome();
    expect(screen.getByRole('textbox', { name: '논문 검색' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '집현전에 이런 걸 맡겨 보세요' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /GraphRAG가 기존 RAG보다 나은 경우는 언제야\?/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /최근 장기 대화 기억 논문을 찾아서 핵심 내용 설명해줘/ })).toBeTruthy();
    expect(screen.getByRole('link', { name: /주제 입문 커리큘럼 짜기/ }).getAttribute('href')).toBe('/curriculum');
    expect(screen.getByRole('textbox', { name: '논문 검색' }).getAttribute('placeholder'))
      .toBe('궁금한 주제나 질문을 편하게 적어 주세요');
  });

  // A starter row puts its question in the composer for editing; sending it
  // starts a conversation and opens it with the run flag.
  it('prefills the composer from a starter row, then starts a conversation on send', async () => {
    authState.isAuthenticated = true;
    renderHome();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /GraphRAG가 기존 RAG보다 나은 경우는 언제야\?/ }));
    });
    expect(createConversation).not.toHaveBeenCalled();
    const box = screen.getByRole('textbox', { name: '논문 검색' }) as HTMLTextAreaElement;
    expect(box.value).toBe('GraphRAG가 기존 RAG보다 나은 경우는 언제야?');
    expect(document.activeElement).toBe(box);

    await act(async () => {
      fireEvent.change(box, { target: { value: 'GraphRAG가 기존 RAG보다 나은 경우는 언제야? 2024년 이후만' } });
      fireEvent.keyDown(box, { key: 'Enter' });
    });
    expect(createConversation).toHaveBeenCalledWith('GraphRAG가 기존 RAG보다 나은 경우는 언제야? 2024년 이후만');
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

  // The replay's CTA goes through the same gate as the composer: login first, then the
  // sample's question becomes a real conversation. The guest home unmounts on sign-in,
  // so the pending question has to live here, in SearchPage.
  it('turns the replay CTA into a conversation after a guest signs in', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce'), media: query }));
    samplesApi.fetchSampleConversations.mockResolvedValue([
      { id: 's1', slug: 'graphrag-vs-rag', title: 'GraphRAG vs RAG', question: 'GraphRAG가 기존 RAG보다 나은 경우는 언제야?', asof: '2026-11-02', turn_count: 2 },
    ]);
    samplesApi.fetchSampleConversation.mockResolvedValue({
      id: 's1', slug: 'graphrag-vs-rag', title: 'GraphRAG vs RAG', asof: '2026-11-02',
      turns: [
        { seq: 1, role: 'user', content: 'GraphRAG가 기존 RAG보다 나은 경우는 언제야?', blocks: [], intent: null },
        { seq: 2, role: 'assistant', content: '정리했어요.\n\n전역 질문에 유리합니다.', blocks: [], intent: 'search' },
      ],
    });
    try {
      const { rerender } = renderHome();
      const cta = await screen.findByRole('button', { name: '로그인하고 이어서 물어보기 →' });
      await act(async () => { fireEvent.click(cta); });
      expect(authState.setShowLoginModal).toHaveBeenCalledWith(true);
      expect(createConversation).not.toHaveBeenCalled();

      authState.isAuthenticated = true;
      await act(async () => { rerender(routes()); });
      expect(createConversation).toHaveBeenCalledWith('GraphRAG가 기존 RAG보다 나은 경우는 언제야?');
      expect(screen.getByText('conversation conv-1 run=true')).toBeTruthy();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('says search needs sign-in, without the public-review rows on the guest home', () => {
    renderHome();
    expect(screen.getByText('내 질문은 로그인 후 무료로 검색·대화해요.')).toBeTruthy();
    expect(screen.queryByRole('heading', { name: '공개 리뷰 읽어보기' })).toBeNull();
    expect(screen.queryByRole('link', { name: /집현전 사용법 자세히 보기/ })).toBeNull();
  });
});
