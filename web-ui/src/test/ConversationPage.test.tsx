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
vi.mock('../api/client', () => ({ getReviewStatus: vi.fn(), getReviewReport: vi.fn() }));
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

    fireEvent.click(screen.getByRole('button', { name: '2' }));
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
    fireEvent.click(screen.getByRole('button', { name: '1' }));
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
      .toBe('이어서 물어보거나 조건을 바꿔 보세요 (예: 2024년 이후만)');
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
      expect(within(artifact).getByRole('heading', { name: '핵심 기여' })).toBeTruthy();
      expect(within(artifact).getByText(/근거 확인 70%/)).toBeTruthy();
    });
  });

  it('shows a load error with a way back', async () => {
    vi.mocked(fetchConversation).mockReset().mockRejectedValue({ response: { status: 404 } });
    renderPage(null);
    expect((await screen.findByRole('alert')).textContent).toContain('대화를 찾을 수 없어요');
    expect(screen.getByRole('button', { name: '홈으로' })).toBeTruthy();
  });
});
