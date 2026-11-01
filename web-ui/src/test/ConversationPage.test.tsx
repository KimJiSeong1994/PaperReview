import { StrictMode } from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ConversationPage from '../components/conversation/ConversationPage';
import { fetchConversation, streamTurn, type TurnStreamHandlers } from '../api/conversations';
import { getReviewReport, getReviewStatus } from '../api/client';
import type { Paper } from '../types';

const storage = new Map<string, string>();
const storageShim = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => { storage.set(key, String(value)); },
  removeItem: (key: string) => { storage.delete(key); },
  clear: () => storage.clear(),
  key: (index: number) => [...storage.keys()][index] ?? null,
  get length() { return storage.size; },
};
Object.defineProperty(globalThis, 'localStorage', { configurable: true, writable: true, value: storageShim });
Object.defineProperty(window, 'localStorage', { configurable: true, writable: true, value: storageShim });

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, setShowLoginModal: vi.fn(), logout: vi.fn() }),
}));
vi.mock('../api/conversations', () => ({
  fetchConversation: vi.fn(),
  streamTurn: vi.fn(),
  createConversation: vi.fn(),
  fetchMyConversations: vi.fn().mockResolvedValue([
    { id: 'conv-1', title: '그래프 RAG', updated_at: new Date().toISOString(), turn_count: 1, last_intent: null },
  ]),
}));
// ReviewBlock polls through api/client, the 리뷰 tab reads api/review: one set of fakes for both.
const reviewApi = vi.hoisted(() => ({
  getReviewStatus: vi.fn(),
  getReviewReport: vi.fn(),
  getVerificationDetail: vi.fn(),
  generatePoster: vi.fn(),
  generatePosterDirect: vi.fn(),
  downloadPosterPdf: vi.fn(),
}));
vi.mock('../api/client', () => reviewApi);
vi.mock('../api/review', async () => {
  const actual = await vi.importActual<typeof import('../api/review')>('../api/review');
  return { ...reviewApi, classifyPosterResponse: actual.classifyPosterResponse, classifyPosterError: actual.classifyPosterError };
});
vi.mock('../components/mypage/PaperViewerPanel', () => ({
  default: ({ bookmarkDetail, highlights }: { bookmarkDetail: { papers: { title: string; pdf_url?: string }[] }; highlights?: unknown[] }) => (
    <div data-testid="pdf-viewer">
      {bookmarkDetail.papers[0].title}|{bookmarkDetail.papers[0].pdf_url}|{highlights ? highlights.length : 'none'}
    </div>
  ),
}));
vi.mock('../api/me', () => ({ fetchMyReviewSessions: vi.fn().mockResolvedValue({ sessions: [], total: 0 }) }));
vi.mock('../api/curriculum', () => ({ fetchCurricula: vi.fn().mockResolvedValue({ curricula: [] }) }));
// Plotly does not render in jsdom; the panel's wiring is what this suite checks.
vi.mock('../components/GraphView', () => ({
  default: ({ selectedPaper }: { selectedPaper: Paper | null }) => (
    <div data-testid="graph">graph:{selectedPaper?.title ?? 'none'}</div>
  ),
}));

const papers: Paper[] = [
  { doc_id: 'd1', result_key: 'k1', title: 'GraphRAG Survey', authors: [], year: 2025, source: 'arxiv' },
  { doc_id: 'd2', result_key: 'k2', title: 'HippoRAG', authors: [], year: 2024, source: 'openalex' },
];

let live: TurnStreamHandlers | null = null;

function renderPage(state: unknown = { run: true }) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/c/conv-1', state }]}>
      <Routes>
        <Route path="/c/:id" element={<ConversationPage id="conv-1" />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ConversationPage', () => {
  beforeEach(() => {
    storage.clear();
    live = null;
    vi.mocked(streamTurn).mockReset().mockImplementation(async (_id, _message, handlers) => { live = handlers; });
    vi.mocked(fetchConversation).mockReset().mockResolvedValue({
      id: 'conv-1',
      title: '그래프 RAG',
      created_at: '2026-10-31T00:00:00Z',
      updated_at: '2026-10-31T00:00:00Z',
      turns: [{
        id: 'u1', seq: 1, role: 'user', content: '그래프 RAG', blocks: [], intent: null, status: 'done',
        created_at: '2026-10-31T00:00:00Z',
      }],
    });
  });

  it('runs the pending turn, streams status, results, graph and answer into the thread and artifact', async () => {
    renderPage();
    expect(await screen.findByRole('heading', { name: '그래프 RAG' })).toBeTruthy();
    expect(streamTurn).toHaveBeenCalledWith('conv-1', null, expect.any(Object), expect.any(AbortSignal));

    act(() => live!.onStatus({ status: '출처 6곳에서 검색하는 중…', stage: 'search' }));
    expect(screen.getByRole('status').textContent).toContain('출처 6곳에서 검색하는 중…');

    act(() => live!.onBlock({
      type: 'search_results', query: '그래프 RAG', total: 2, query_hash: 'h1', partial: false, degraded: [], papers,
    }));
    expect(screen.getByRole('region', { name: '검색 결과 2편' })).toBeTruthy();
    expect(screen.queryByRole('complementary', { name: '검색 결과 아티팩트' })).toBeNull();

    act(() => live!.onBlock({ type: 'graph', query_hash: 'h1', graph: { nodes: [], edges: [] } }));
    expect(screen.getByRole('complementary', { name: '검색 결과 아티팩트' })).toBeTruthy();
    expect(await screen.findByTestId('graph')).toBeTruthy();

    act(() => {
      live!.onDelta('두 편을 찾았어요. 특히 ');
      live!.onDelta('HippoRAG [2] 가 눈에 띕니다.');
      live!.onDone({ turn_id: 'a1', intent: 'search' });
    });
    expect(screen.getByText('출처 2곳 · 2편 · 그래프')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '참고 논문 2: HippoRAG 2024, HippoRAG' }));
    expect(screen.getByTestId('graph').textContent).toBe('graph:HippoRAG');

    fireEvent.click(screen.getByRole('button', { name: '아티팩트' }));
    expect(screen.queryByRole('complementary', { name: '검색 결과 아티팩트' })).toBeNull();
  });

  it('opens the full list from the inline block and sends a follow-up into the same conversation', async () => {
    renderPage();
    await screen.findByRole('heading', { name: '그래프 RAG' });
    act(() => {
      live!.onBlock({ type: 'search_results', query: 'q', total: 2, query_hash: 'h1', partial: false, degraded: [], papers });
      live!.onDone({ turn_id: 'a1', intent: 'search' });
    });

    fireEvent.click(screen.getByRole('button', { name: '전체 2편 보기 →' }));
    const artifact = screen.getByRole('complementary', { name: '검색 결과 아티팩트' });
    expect(within(artifact).getByRole('tab', { name: '목록 2' }).getAttribute('aria-selected')).toBe('true');

    const box = screen.getByRole('textbox', { name: '이어서 물어보세요' });
    fireEvent.change(box, { target: { value: '둘의 차이는?' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(streamTurn).toHaveBeenLastCalledWith('conv-1', '둘의 차이는?', expect.any(Object), expect.any(AbortSignal));
    expect(screen.getByText('둘의 차이는?')).toBeTruthy();
    expect((box as HTMLTextAreaElement).value).toBe('');
    expect(screen.getByRole('button', { name: '중단' })).toBeTruthy();
  });

  it('runs a follow-up exactly once, with no bare re-run after it', async () => {
    render(
      <StrictMode>
        <MemoryRouter initialEntries={[{ pathname: '/c/conv-1', state: { run: true } }]}>
          <Routes>
            <Route path="/c/:id" element={<ConversationPage id="conv-1" />} />
          </Routes>
        </MemoryRouter>
      </StrictMode>,
    );
    await screen.findByRole('heading', { name: '그래프 RAG' });
    act(() => {
      live!.onDelta('첫 답변');
      live!.onDone({ turn_id: 'a1', intent: 'search' });
    });

    const box = screen.getByRole('textbox', { name: '이어서 물어보세요' });
    fireEvent.change(box, { target: { value: '1번과 2번의 결론 차이는?' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    await act(async () => {
      live!.onDelta('차이는 이렇습니다.');
      live!.onDone({ turn_id: 'a2', intent: 'answer' });
    });

    const calls = vi.mocked(streamTurn).mock.calls.map(([, message]) => message);
    expect(calls).toEqual([null, '1번과 2번의 결론 차이는?']);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getAllByText('집현전')).toHaveLength(2);
  });

  it('does not re-run a saved conversation and shows a retry on a failed turn', async () => {
    renderPage(null);
    await screen.findByRole('heading', { name: '그래프 RAG' });
    expect(streamTurn).not.toHaveBeenCalled();

    const box = screen.getByRole('textbox', { name: '이어서 물어보세요' });
    fireEvent.change(box, { target: { value: '다시' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    act(() => live!.onError('검색에 실패했어요', true));
    expect(screen.getByRole('alert').textContent).toContain('검색에 실패했어요');

    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(streamTurn).toHaveBeenLastCalledWith('conv-1', null, expect.any(Object), expect.any(AbortSignal));
    // The retried answer replaces the failed one; the question is not repeated.
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getAllByText('다시')).toHaveLength(1);
  });

  it('offers a retry on an errored turn restored from the server', async () => {
    vi.mocked(fetchConversation).mockResolvedValueOnce({
      id: 'conv-1', title: '그래프 RAG', created_at: '', updated_at: '',
      turns: [
        { id: 'u1', seq: 1, role: 'user', content: '그래프 RAG', blocks: [], intent: null, status: 'done', created_at: '' },
        { id: 'a1', seq: 2, role: 'assistant', content: '', blocks: [], intent: null, status: 'error', created_at: '' },
      ],
    });
    renderPage(null);
    expect((await screen.findByRole('alert')).textContent).toContain('답변을 만들지 못했어요.');
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(streamTurn).toHaveBeenCalledWith('conv-1', null, expect.any(Object), expect.any(AbortSignal));
  });

  it('keeps the artifact usable when a finished search has no graph', async () => {
    renderPage();
    await screen.findByRole('heading', { name: '그래프 RAG' });
    act(() => {
      live!.onBlock({ type: 'search_results', query: 'q', total: 2, query_hash: 'h1', partial: false, degraded: [], papers });
      live!.onDone({ turn_id: 'a1', intent: 'search' });
    });
    expect(screen.queryByRole('complementary', { name: '검색 결과 아티팩트' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '아티팩트' }));
    expect(screen.getByText('이 검색은 관계 그래프를 만들지 못했어요.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '목록에서 보기 →' }));
    expect(screen.getByRole('tab', { name: '목록 2' }).getAttribute('aria-selected')).toBe('true');
  });

  it('re-sends a follow-up the server never stored, without repeating it in the thread', async () => {
    renderPage(null);
    await screen.findByRole('heading', { name: '그래프 RAG' });
    const box = screen.getByRole('textbox', { name: '이어서 물어보세요' });
    fireEvent.change(box, { target: { value: '결론 차이는?' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    act(() => live!.onError('요청이 너무 잦아요. 잠시 후 다시 시도해 주세요.', false));

    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(vi.mocked(streamTurn).mock.calls.map(([, message]) => message)).toEqual(['결론 차이는?', '결론 차이는?']);
    expect(screen.getAllByText('결론 차이는?')).toHaveLength(1);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('keeps the composer usable after 중단', async () => {
    renderPage();
    await screen.findByRole('heading', { name: '그래프 RAG' });
    act(() => live!.onDelta('부분 답변'));
    fireEvent.click(screen.getByRole('button', { name: '중단' }));
    expect(screen.getByText('중단됨')).toBeTruthy();
    const box = screen.getByRole('textbox', { name: '이어서 물어보세요' });
    fireEvent.change(box, { target: { value: '다른 질문' } });
    expect(screen.getByRole('button', { name: '보내기' })).not.toBeDisabled();
  });

  it('renders restored cancelled and failed turns without a stale retry', async () => {
    const turn = (seq: number, role: 'user' | 'assistant', content: string, status: 'done' | 'error') => ({
      id: `t${seq}`, seq, role, content, blocks: [], intent: null, status, created_at: '',
    });
    vi.mocked(fetchConversation).mockResolvedValueOnce({
      id: 'conv-1', title: '그래프 RAG', created_at: '', updated_at: '',
      turns: [
        turn(1, 'user', '첫 질문', 'done'),
        turn(2, 'assistant', '중단됨', 'error'),
        turn(3, 'user', '둘째 질문', 'done'),
        turn(4, 'assistant', '', 'error'),
        turn(5, 'user', '셋째 질문', 'done'),
        turn(6, 'assistant', '답했어요.', 'done'),
      ],
    });
    renderPage(null);
    expect(await screen.findByText('중단됨')).toBeTruthy();
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(screen.getByRole('alert').textContent).toContain('답변을 만들지 못했어요.');
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull();
  });

  it('keys results by turn, so the same query asked again cites and opens the newer results', async () => {
    renderPage();
    await screen.findByRole('heading', { name: '그래프 RAG' });
    act(() => {
      live!.onBlock({ type: 'search_results', query: 'q', total: 1, query_hash: 'same', partial: false, degraded: [], papers: [papers[0]] });
      live!.onBlock({ type: 'graph', query_hash: 'same', graph: { nodes: [], edges: [] } });
      live!.onDone({ turn_id: 'a1', intent: 'search' });
    });
    fireEvent.click(screen.getByRole('button', { name: '아티팩트' }));
    expect(screen.queryByRole('complementary', { name: '검색 결과 아티팩트' })).toBeNull();

    const box = screen.getByRole('textbox', { name: '이어서 물어보세요' });
    fireEvent.change(box, { target: { value: '같은 검색 다시' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    act(() => {
      live!.onBlock({ type: 'search_results', query: 'q', total: 1, query_hash: 'same', partial: false, degraded: [], papers: [papers[1]] });
      live!.onBlock({ type: 'graph', query_hash: 'same', graph: { nodes: [], edges: [] } });
      live!.onDelta('다시 찾은 결과 [1]');
      live!.onDone({ turn_id: 'a2', intent: 'search' });
    });
    expect(screen.getByRole('complementary', { name: '검색 결과 아티팩트' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '참고 논문 1: HippoRAG 2024, HippoRAG' }));
    expect((await screen.findByTestId('graph')).textContent).toBe('graph:HippoRAG');
  });

  it('puts the lead above the status line and results, and the summary below them', async () => {
    renderPage();
    await screen.findByRole('heading', { name: '그래프 RAG' });
    act(() => {
      live!.onDelta('GraphRAG 논문을 찾아볼게요.');
      live!.onStatus({ status: '출처 6곳에서 검색하는 중…', stage: 'search' });
      live!.onBlock({ type: 'search_results', query: 'q', total: 2, query_hash: 'h1', partial: false, degraded: [], papers });
    });
    const lead = screen.getByText('GraphRAG 논문을 찾아볼게요.');
    const status = screen.getByRole('status');
    const results = screen.getByRole('region', { name: '검색 결과 2편' });
    const follows = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(follows(lead, status)).toBe(true);
    expect(follows(status, results)).toBe(true);

    act(() => {
      live!.onDelta('\n\n두 편이 핵심이에요.');
      live!.onDone({ turn_id: 'a1', intent: 'search' });
    });
    expect(follows(results, screen.getByText('두 편이 핵심이에요.'))).toBe(true);
    expect(follows(screen.getByText('GraphRAG 논문을 찾아볼게요.'), results)).toBe(true);
  });

  it('splits a saved search turn at its first paragraph', async () => {
    vi.mocked(fetchConversation).mockResolvedValueOnce({
      id: 'conv-1', title: '그래프 RAG', created_at: '', updated_at: '',
      turns: [
        { id: 'u1', seq: 1, role: 'user', content: '그래프 RAG', blocks: [], intent: null, status: 'done', created_at: '' },
        {
          id: 'a1', seq: 2, role: 'assistant', content: '찾아볼게요.\n\n요약입니다.', intent: 'search', status: 'done', created_at: '',
          blocks: [{ type: 'search_results', query: 'q', total: 2, query_hash: 'h1', partial: false, degraded: [], papers }],
        },
      ],
    });
    renderPage(null);
    const results = await screen.findByRole('region', { name: '검색 결과 2편' });
    const follows = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(follows(screen.getByText('찾아볼게요.'), results)).toBe(true);
    expect(follows(results, screen.getByText('요약입니다.'))).toBe(true);
  });

  it('streams a chat turn with no status line, and applies the new title in place', async () => {
    renderPage();
    await screen.findByRole('heading', { name: '그래프 RAG' });
    // Waiting indicator from send until the first event.
    expect(screen.getByRole('status').textContent).toContain('생각하는 중…');
    act(() => live!.onDelta('안녕하세요! 어떤 주제가 궁금하세요?'));
    expect(screen.queryByRole('status')).toBeNull();

    act(() => live!.onDone({ turn_id: 'a1', intent: 'chat', title: '인사와 주제 고르기' }));
    expect(screen.getByRole('heading', { name: '인사와 주제 고르기' })).toBeTruthy();
    expect(screen.queryByText(/출처 \d+곳/)).toBeNull();
    const nav = screen.getByRole('navigation', { name: '내 기록' });
    expect(await within(nav).findByRole('link', { name: /인사와 주제 고르기/ })).toBeTruthy();
    // A later turn sends title null: the title stays.
    const box = screen.getByRole('textbox', { name: '이어서 물어보세요' });
    fireEvent.change(box, { target: { value: '고마워요' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    act(() => {
      live!.onDelta('천만에요.');
      live!.onDone({ turn_id: 'a2', intent: 'chat', latency_ms: 5, title: null });
    });
    expect(screen.getByRole('heading', { name: '인사와 주제 고르기' })).toBeTruthy();
    expect(screen.getByRole('textbox', { name: '이어서 물어보세요' }).getAttribute('placeholder'))
      .toBe('이어서 물어보세요 (예: 2번 핵심 내용 설명해줘, 2024년 이후만)');
  });

  it('ignores a block type it does not know', async () => {
    vi.mocked(fetchConversation).mockResolvedValueOnce({
      id: 'conv-1', title: '그래프 RAG', created_at: '', updated_at: '',
      turns: [
        { id: 'u1', seq: 1, role: 'user', content: '질문', blocks: [], intent: null, status: 'done', created_at: '' },
        {
          id: 'a1', seq: 2, role: 'assistant', content: '답했어요.', intent: 'answer', status: 'done', created_at: '',
          blocks: [{ type: 'future_widget', payload: 1 } as unknown as never],
        },
      ],
    });
    renderPage(null);
    expect(await screen.findByText('답했어요.')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  describe('deep review turns', () => {
    const reviewConversation = () => ({
      id: 'conv-1', title: '그래프 RAG', created_at: '', updated_at: '',
      turns: [
        { id: 'u1', seq: 1, role: 'user' as const, content: '2번 리뷰해줘', blocks: [], intent: null, status: 'done' as const, created_at: '' },
        {
          id: 'a1', seq: 2, role: 'assistant' as const, content: 'HippoRAG 심층 리뷰를 시작했어요.\n\n끝나면 알려드릴게요.',
          intent: 'review', status: 'done' as const, created_at: '',
          blocks: [{ type: 'review_started' as const, session_id: 'rev-1', paper_index: 2, paper_title: 'HippoRAG', paper_key: 'k2' }],
        },
      ],
    });
    const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

    beforeEach(() => {
      vi.useFakeTimers();
      vi.mocked(getReviewStatus).mockReset();
      vi.mocked(getReviewReport).mockReset();
      reviewApi.getVerificationDetail.mockReset().mockResolvedValue({ session_id: 'rev-1', claims: [], cross_references: [], consensus: [] });
      vi.mocked(fetchConversation).mockResolvedValueOnce(reviewConversation());
    });
    afterEach(() => vi.useRealTimers());

    it('resumes polling a running review when the conversation is reloaded', async () => {
      vi.mocked(getReviewStatus).mockResolvedValue({ session_id: 'rev-1', status: 'processing', progress: '검증 2/3', report_available: false });
      renderPage(null);
      await tick(0); // resolve the conversation fetch
      expect(screen.getByText('심층 리뷰 시작')).toBeTruthy();
      await tick(2000);
      await tick(2000);
      expect(getReviewStatus).toHaveBeenCalledTimes(2);
      expect(getReviewStatus).toHaveBeenCalledWith('rev-1');
      expect(screen.getByRole('region', { name: '심층 리뷰: HippoRAG' }).textContent).toContain('검증 2/3');
      expect(screen.queryByText(/출처 \d+곳/)).toBeNull();
    });

    it('opens the report in the 리뷰 tab', async () => {
      vi.mocked(getReviewStatus).mockResolvedValue({ session_id: 'rev-1', status: 'completed', report_available: true });
      vi.mocked(getReviewReport).mockResolvedValue({
        session_id: 'rev-1', report_markdown: '## 핵심 기여\n\n그래프 기반 기억.', num_papers: 1, created_at: '',
        verification_stats: {
          total_claims: 10, verifiable_claims: 8, verified: 6, partially_verified: 1, unverified: 1, contradicted: 0, verification_rate: 0.7,
        } as never,
      });
      renderPage(null);
      await tick(0); // resolve the conversation fetch
      await tick(2000);
      fireEvent.click(screen.getByRole('button', { name: '리포트 보기 →' }));

      const artifact = screen.getByRole('complementary', { name: '검색 결과 아티팩트' });
      expect(within(artifact).getByRole('tab', { name: '리뷰' }).getAttribute('aria-selected')).toBe('true');
      await tick(0); // the 리뷰 tab loads the session's report on open
      expect(within(artifact).getByRole('heading', { name: '핵심 기여' })).toBeTruthy();
      expect(within(artifact).getByText(/근거 확인 70%/)).toBeTruthy();
    });
  });

  describe('PDF tool blocks', () => {
    const paper = {
      paper_index: 2, paper_title: 'HippoRAG', paper_key: 'k2', pdf_url: 'https://arxiv.org/pdf/2405.14831',
      proxy_url: '/api/pdf/proxy?url=x', viewer_url: '/paper-viewer?title=HippoRAG', authors: ['B. Gutiérrez'], year: 2024,
    };

    it('opens the artifact on the PDF tab when a paper_pdf block arrives, and PdfBlock returns to it', async () => {
      renderPage();
      await screen.findByRole('heading', { name: '그래프 RAG' });
      act(() => {
        live!.onDelta('HippoRAG PDF를 열었어요.');
        live!.onBlock({ type: 'paper_pdf', ...paper });
        live!.onDone({ turn_id: 'a1', intent: 'pdf' });
      });
      const artifact = screen.getByRole('complementary', { name: '검색 결과 아티팩트' });
      expect(within(artifact).getByRole('tab', { name: 'PDF' }).getAttribute('aria-selected')).toBe('true');
      expect((await within(artifact).findByTestId('pdf-viewer')).textContent).toBe('HippoRAG|https://arxiv.org/pdf/2405.14831|none');
      expect(within(artifact).getByRole('link', { name: /새 창에서 열기/ }).getAttribute('href')).toBe('/paper-viewer?title=HippoRAG');
      expect(screen.getByText('PDF 열기')).toBeTruthy();

      fireEvent.click(within(artifact).getByRole('tab', { name: '그래프' }));
      fireEvent.click(screen.getByRole('button', { name: 'PDF 열기 →' }));
      expect(within(artifact).getByRole('tab', { name: 'PDF' }).getAttribute('aria-selected')).toBe('true');
    });

    it('lists highlights with Korean category chips; a click opens the PDF tab with them overlaid', async () => {
      renderPage();
      await screen.findByRole('heading', { name: '그래프 RAG' });
      act(() => {
        live!.onBlock({
          type: 'pdf_highlights', ...paper,
          highlights: [
            { id: 'h1', text: 'graph memory improves recall', color: '', memo: '', created_at: '', category: 'finding' },
            { id: 'h2', text: 'only English corpora', color: '', memo: '', created_at: '', category: 'limitation' },
            { id: 'h3', text: 'an odd one', color: '', memo: '', created_at: '', category: 'mystery' },
          ],
        });
        live!.onDone({ turn_id: 'a1', intent: 'pdf' });
      });
      const block = screen.getByRole('region', { name: '하이라이트: HippoRAG' });
      expect(within(block).getByText('핵심 발견')).toBeTruthy();
      expect(within(block).getByText('한계')).toBeTruthy();
      expect(within(block).getByText('하이라이트')).toBeTruthy();
      expect(screen.getByText('하이라이트 3개', { selector: 'p' })).toBeTruthy();

      fireEvent.click(screen.getByRole('button', { name: '아티팩트' }));
      expect(screen.queryByRole('complementary', { name: '검색 결과 아티팩트' })).toBeNull();
      fireEvent.click(within(block).getByRole('button', { name: /only English corpora/ }));
      const artifact = screen.getByRole('complementary', { name: '검색 결과 아티팩트' });
      expect(within(artifact).getByRole('tab', { name: 'PDF' }).getAttribute('aria-selected')).toBe('true');
      expect((await within(artifact).findByTestId('pdf-viewer')).textContent).toBe('HippoRAG|https://arxiv.org/pdf/2405.14831|3');
    });
  });

  describe('bookmark-grounded answers', () => {
    it('shows the 근거 북마크 strip above the answer, links [B1] to its chip, and summarises the turn', async () => {
      renderPage();
      await screen.findByRole('heading', { name: '그래프 RAG' });
      act(() => {
        live!.onBlock({
          type: 'bookmark_refs',
          bookmarks: [
            { id: 'bm_1', title: 'GraphRAG 서베이', query: 'graphrag', num_papers: 5, has_report: true, url: '/mypage?bookmark=bm_1' },
            { id: 'bm_2', title: '장기 기억', query: 'memory', num_papers: 3, has_report: false, url: '/mypage?bookmark=bm_2' },
          ],
        });
        live!.onDelta('두 북마크 모두 그래프 기반 검색을 다뤄요 [B1].');
        live!.onDone({ turn_id: 'a1', intent: 'answer_from_bookmarks' });
      });
      const strip = screen.getByRole('navigation', { name: '근거 북마크' });
      const first = within(strip).getByRole('link', { name: /GraphRAG 서베이/ });
      expect(first.getAttribute('href')).toBe('/mypage?bookmark=bm_1');
      expect(first.textContent).toContain('5편 · 리포트');
      expect(within(strip).getByRole('link', { name: /장기 기억/ }).textContent).not.toContain('리포트');
      const follows = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
      expect(follows(strip, screen.getByText(/두 북마크 모두/))).toBe(true);
      expect(screen.getByText('북마크 2개 근거')).toBeTruthy();

      fireEvent.click(screen.getByRole('button', { name: '근거 북마크 B1: GraphRAG 서베이' }));
      expect(document.activeElement).toBe(first);
      expect(screen.queryByRole('complementary', { name: '검색 결과 아티팩트' })).toBeNull();
    });

    it('tags a paper block that came from a bookmark', async () => {
      renderPage();
      await screen.findByRole('heading', { name: '그래프 RAG' });
      act(() => {
        live!.onBlock({
          type: 'paper_pdf', paper_index: 1, paper_title: 'HippoRAG', paper_key: 'k', pdf_url: null, proxy_url: null,
          viewer_url: '/paper-viewer?title=HippoRAG', authors: [], year: 2024, source: 'bookmark', bookmark_id: 'bm_1',
        });
        live!.onDone({ turn_id: 'a1', intent: 'pdf' });
      });
      expect(within(screen.getByRole('region', { name: 'PDF: HippoRAG' })).getByText('북마크')).toBeTruthy();
    });
  });

  it('opens a bookmark\'s review in the 리뷰 tab from 리뷰 보기 on its chip', async () => {
    reviewApi.getReviewReport.mockReset().mockResolvedValue({
      session_id: 'rev-bm', report_markdown: '## 북마크 리뷰 본문', num_papers: 3, created_at: '',
    });
    reviewApi.getVerificationDetail.mockReset().mockResolvedValue({ session_id: 'rev-bm', claims: [], cross_references: [], consensus: [] });
    renderPage();
    await screen.findByRole('heading', { name: '그래프 RAG' });
    act(() => {
      live!.onBlock({
        type: 'bookmark_refs',
        bookmarks: [
          { id: 'bm_1', title: 'GraphRAG 서베이', query: 'q', num_papers: 3, has_report: true, url: '/mypage?bookmark=bm_1', session_id: 'rev-bm' },
          { id: 'bm_2', title: '리뷰 없는 북마크', query: 'q', num_papers: 1, has_report: false, url: '/mypage?bookmark=bm_2', session_id: null },
        ],
      });
      live!.onDelta('답변 [B1]');
      live!.onDone({ turn_id: 'a1', intent: 'answer_from_bookmarks' });
    });
    expect(screen.getAllByRole('button', { name: /리뷰 보기/ })).toHaveLength(1);

    fireEvent.click(screen.getByRole('button', { name: 'GraphRAG 서베이 리뷰 보기' }));
    const artifact = screen.getByRole('complementary', { name: '검색 결과 아티팩트' });
    expect(within(artifact).getByRole('tab', { name: '리뷰' }).getAttribute('aria-selected')).toBe('true');
    expect(await within(artifact).findByRole('heading', { name: '북마크 리뷰 본문' })).toBeTruthy();
    expect(reviewApi.getReviewReport).toHaveBeenCalledWith('rev-bm');
  });

  it('opens the 리뷰 tab at once when MyPage hands over a review session', async () => {
    reviewApi.getReviewReport.mockReset().mockResolvedValue({
      session_id: 'rev-bm', report_markdown: '## 넘겨받은 리뷰', num_papers: 2, created_at: '',
    });
    reviewApi.getVerificationDetail.mockReset().mockResolvedValue({ session_id: 'rev-bm', claims: [], cross_references: [], consensus: [] });
    renderPage({ run: true, openReview: 'rev-bm', openReviewTitle: 'GraphRAG 서베이' });
    const artifact = await screen.findByRole('complementary', { name: '검색 결과 아티팩트' });
    expect(within(artifact).getByRole('tab', { name: '리뷰' }).getAttribute('aria-selected')).toBe('true');
    expect(within(artifact).getByText('GraphRAG 서베이')).toBeTruthy();
    expect(await within(artifact).findByRole('heading', { name: '넘겨받은 리뷰' })).toBeTruthy();
    expect(streamTurn).toHaveBeenCalledWith('conv-1', null, expect.any(Object), expect.any(AbortSignal));
  });

  it('reads a vanished handed-over session as 확인 불가', async () => {
    reviewApi.getReviewReport.mockReset().mockRejectedValue({ response: { status: 404 } });
    renderPage({ run: true, openReview: 'rev-gone', openReviewTitle: '오래된 북마크' });
    const artifact = await screen.findByRole('complementary', { name: '검색 결과 아티팩트' });
    expect((await within(artifact).findByText(/리뷰 세션을 더 이상 찾을 수 없어요/))).toBeTruthy();
  });

  describe('citations', () => {
    const eight: Paper[] = Array.from({ length: 8 }, (_, i) => ({
      doc_id: `d${i + 1}`, result_key: `k${i + 1}`, title: `Paper number ${i + 1} on graph memory`,
      authors: i === 2 ? ['Jiseong Han', 'Minji Lee', 'Sora Park', 'Doyun Kim'] : i === 6 ? ['이민지'] : [`Author${i + 1} Surname${i + 1}`],
      year: 2020 + i, source: 'arxiv', pdf_url: i === 2 ? 'https://arxiv.org/pdf/3' : undefined, url: i === 6 ? 'https://example.org/7' : undefined,
    }));

    const answer = async (text: string) => {
      renderPage();
      await screen.findByRole('heading', { name: '그래프 RAG' });
      act(() => {
        live!.onBlock({ type: 'search_results', query: 'q', total: 8, query_hash: 'h8', partial: false, degraded: [], papers: eight });
        live!.onDelta(text);
        live!.onDone({ turn_id: 'a1', intent: 'search' });
      });
    };

    it('marks citations with superscript numbers, resolves past the top 5, and lists cited papers by number', async () => {
      await answer('기억 그래프가 핵심이에요 [7]. 비교하면 [3][7][8] 순으로 정리됩니다.');

      // [7] lies beyond the inline top 5 and still resolves.
      const seven = screen.getAllByRole('button', { name: '참고 논문 7: 이민지 2026, Paper number 7 on graph memory' });
      expect(seven).toHaveLength(2);
      expect(seven[0].textContent).toBe('7');
      expect(seven[0].hasAttribute('title')).toBe(false);
      const group = screen.getByRole('button', { name: /^참고 논문 3: Han 2022/ }).closest('.conv-cite-group')!;
      expect(group.tagName).toBe('SUP');
      expect(group.textContent).toBe('3,7,8');

      const refs = screen.getByRole('region', { name: '참고 논문' });
      expect(within(refs).getByRole('heading').textContent).toContain('참고 논문');
      expect(within(refs).getByRole('heading').textContent).toContain('3');
      const items = within(refs).getAllByRole('listitem');
      expect(items.map(item => item.querySelector('.conv-ref-n')!.textContent)).toEqual(['3', '7', '8']);
      expect(items[0].textContent).toContain('Paper number 3 on graph memory');
      expect(items[0].querySelector('.conv-ref-meta')!.textContent).toContain('Jiseong Han, Minji Lee, Sora Park et al. · 2022 · arxiv');
      expect(refs.querySelector('.conv-ref-label')).toBeNull();
      expect(within(items[0]).getByRole('link').getAttribute('href')).toBe('https://arxiv.org/pdf/3');
      expect(within(items[1]).getByRole('link').getAttribute('href')).toBe('https://example.org/7');
      expect(within(items[2]).queryByRole('link')).toBeNull();
      expect(within(refs).queryByText(/Paper number 1 on/)).toBeNull();

      fireEvent.click(within(items[2]).getByRole('button', { name: 'Paper number 8 on graph memory' }));
      // No graph block in this turn: the artifact opens with the selected paper's detail.
      const artifact = screen.getByRole('complementary', { name: '검색 결과 아티팩트' });
      expect(within(artifact).getAllByText('Paper number 8 on graph memory').length).toBeGreaterThan(0);
    });

    it('shows no 참고 논문 list when the answer cites nothing', async () => {
      await answer('8편을 찾았어요.');
      expect(screen.queryByRole('region', { name: '참고 논문' })).toBeNull();
    });

    it('opens the popover on focus, describes the marker with it, and closes on Escape', async () => {
      await answer('핵심은 [3] 입니다.');
      const marker = screen.getByRole('button', { name: /^참고 논문 3:/ });
      act(() => { marker.focus(); });
      const tooltip = screen.getByRole('tooltip');
      expect(tooltip.textContent).toContain('Paper number 3 on graph memory');
      expect(tooltip.textContent).toContain('Jiseong Han, Minji Lee et al. · 2022 · arxiv');
      expect(tooltip.textContent).toContain('클릭하면 오른쪽 패널에서 열려요');
      expect(marker.getAttribute('aria-describedby')).toBe('conv-cite-peek');
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(screen.queryByRole('tooltip')).toBeNull();
      expect(document.activeElement).toBe(marker);
    });

    it('opens the popover 120ms after a mouse enters, closes it on leave, and never for touch', async () => {
      await answer('핵심은 [3] 입니다.');
      vi.useFakeTimers();
      try {
        const marker = screen.getByRole('button', { name: /^참고 논문 3:/ });
        fireEvent.pointerEnter(marker, { pointerType: 'mouse' });
        act(() => { vi.advanceTimersByTime(100); });
        expect(screen.queryByRole('tooltip')).toBeNull();
        act(() => { vi.advanceTimersByTime(20); });
        expect(screen.getByRole('tooltip')).toBeTruthy();
        fireEvent.pointerLeave(marker, { pointerType: 'mouse' });
        expect(screen.queryByRole('tooltip')).toBeNull();

        fireEvent.pointerEnter(marker, { pointerType: 'touch' });
        act(() => { vi.advanceTimersByTime(500); });
        expect(screen.queryByRole('tooltip')).toBeNull();
      } finally {
        vi.useRealTimers();
      }
    });

    it('renders a number with no result as plain text, without a list row', async () => {
      await answer('없는 번호 [9] 와 있는 번호 [2].');
      const group = screen.getAllByText('9').find(node => node.classList.contains('conv-cite'))!;
      expect(group.tagName).toBe('SPAN');
      expect(group.classList.contains('is-missing')).toBe(true);
      expect(screen.queryByRole('button', { name: /^참고 논문 9/ })).toBeNull();
      const rows = within(screen.getByRole('region', { name: '참고 논문' })).getAllByRole('listitem');
      expect(rows.map(row => row.querySelector('.conv-ref-n')!.textContent)).toEqual(['2']);
    });

    it('marks bookmark citations as B1 and focuses the strip chip', async () => {
      renderPage();
      await screen.findByRole('heading', { name: '그래프 RAG' });
      act(() => {
        live!.onBlock({
          type: 'bookmark_refs',
          bookmarks: [{ id: 'bm_1', title: '그래프 기반 장기 기억 연구 모음과 정리 노트', query: 'q', num_papers: 2, has_report: true, url: '/mypage?bookmark=bm_1' }],
        });
        live!.onDelta('북마크를 보면 [B1] 이렇습니다.');
        live!.onDone({ turn_id: 'a1', intent: 'answer_from_bookmarks' });
      });
      const marker = screen.getByRole('button', { name: '근거 북마크 B1: 그래프 기반 장기 기억 연구 모음과 정리 노트' });
      expect(marker.textContent).toBe('B1');
      act(() => { marker.focus(); });
      expect(screen.getByRole('tooltip').textContent).toContain('북마크 · 2편 · 리포트');
      fireEvent.click(marker);
      expect(document.activeElement?.id).toMatch(/^bookmark-ref-\d+-1$/);
    });
  });

  it('shows a load error with a way back', async () => {
    vi.mocked(fetchConversation).mockReset().mockRejectedValue({ response: { status: 404 } });
    renderPage(null);
    expect((await screen.findByRole('alert')).textContent).toContain('대화를 찾을 수 없어요');
    expect(screen.getByRole('button', { name: '홈으로' })).toBeTruthy();
  });
});
