import { StrictMode } from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ConversationPage from '../components/conversation/ConversationPage';
import { fetchConversation, streamTurn, type TurnStreamHandlers } from '../api/conversations';
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

  it('shows a load error with a way back', async () => {
    vi.mocked(fetchConversation).mockReset().mockRejectedValue({ response: { status: 404 } });
    renderPage(null);
    expect((await screen.findByRole('alert')).textContent).toContain('대화를 찾을 수 없어요');
    expect(screen.getByRole('button', { name: '홈으로' })).toBeTruthy();
  });
});
