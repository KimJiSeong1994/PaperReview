import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SampleConversationPage from '../components/conversation/SampleConversationPage';
import { createConversation } from '../api/conversations';
import type { Paper } from '../types';

const authState = vi.hoisted(() => ({
  isAuthenticated: false,
  showLoginModal: false,
  setShowLoginModal: vi.fn(),
  logout: vi.fn(),
  userRole: 'user',
}));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => authState }));
vi.mock('../api/samples', () => ({
  fetchSampleConversations: vi.fn().mockResolvedValue([
    { id: 's1', slug: 'graphrag-vs-rag', title: 'GraphRAG vs RAG', question: 'GraphRAG가 RAG보다 나은 경우는?', asof: '2026-10-25', turn_count: 2 },
    { id: 's2', slug: 'long-term-agent-memory', title: '장기 기억', question: '장기 대화 기억 논문 보여줘', asof: '2026-10-25', turn_count: 2 },
  ]),
  fetchSampleConversation: vi.fn(),
}));
vi.mock('../api/conversations', () => ({
  createConversation: vi.fn(),
  fetchMyConversations: vi.fn().mockResolvedValue([]),
}));
vi.mock('../analytics/events', () => ({
  trackSampleView: vi.fn(),
  trackSampleCtaClick: vi.fn(),
  trackConversationStart: vi.fn(),
}));
vi.mock('../api/me', () => ({ fetchMyReviewSessions: vi.fn().mockResolvedValue({ sessions: [], total: 0 }) }));
vi.mock('../api/curriculum', () => ({ fetchCurricula: vi.fn().mockResolvedValue({ curricula: [] }) }));
vi.mock('../components/GraphView', () => ({
  default: ({ papers }: { papers: Paper[] }) => <div data-testid="graph">graph:{papers.length}</div>,
}));

import { fetchSampleConversation } from '../api/samples';
import { trackConversationStart, trackSampleCtaClick, trackSampleView } from '../analytics/events';

const papers: Paper[] = [
  { doc_id: 'd1', result_key: 'k1', title: 'From Local to Global', authors: ['Darren Edge'], year: 2024, source: 'arxiv' },
  { doc_id: 'd2', result_key: 'k2', title: 'LightRAG', authors: ['Zirui Guo'], year: 2024, source: 'arxiv' },
];

// The artifact opens by itself only where it is a third column (≥1101px).
const setViewport = (wide: boolean) => vi.stubGlobal('matchMedia', (query: string) => ({
  matches: wide && query === '(min-width: 1101px)', media: query,
}));

function ConversationProbe() {
  const { id } = useParams();
  return <p>conversation {id}</p>;
}

function routes() {
  return (
    <MemoryRouter initialEntries={['/samples/graphrag-vs-rag']}>
      <Routes>
        <Route path="/samples/:slug" element={<SampleConversationPage slug="graphrag-vs-rag" />} />
        <Route path="/c/:id" element={<ConversationProbe />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('SampleConversationPage', () => {
  afterEach(() => vi.unstubAllGlobals());

  beforeEach(() => {
    setViewport(true);
    authState.isAuthenticated = false;
    authState.setShowLoginModal.mockClear();
    vi.mocked(createConversation).mockReset().mockResolvedValue({ id: 'conv-7', title: 't', turn_id: 'u' });
    vi.mocked(fetchSampleConversation).mockResolvedValue({
      id: 's1', slug: 'graphrag-vs-rag', title: 'GraphRAG vs RAG', asof: '2026-10-25',
      turns: [
        { seq: 1, role: 'user', content: 'GraphRAG가 RAG보다 나은 경우는?', blocks: [], intent: null },
        {
          seq: 2, role: 'assistant', intent: 'search',
          content: '두 편을 찾았어요.\n\n전역 질문에는 GraphRAG가 유리합니다 [1].',
          blocks: [
            { type: 'search_results', query: 'q', total: 2, query_hash: 'h', partial: false, degraded: [], papers },
            { type: 'graph', query_hash: 'h', graph: { nodes: [], edges: [] } },
          ],
        },
      ],
    });
  });

  it('renders the sample read-only: title, turns, the artifact with the graph, and a sign-in CTA instead of a composer', async () => {
    render(routes());
    expect(await screen.findByRole('heading', { name: 'GraphRAG vs RAG · 상담 예시 · 2026-10-25 기준' })).toBeTruthy();
    expect(screen.getByText('GraphRAG가 RAG보다 나은 경우는?', { selector: '.conv-bubble' })).toBeTruthy();
    expect(screen.getByText(/전역 질문에는 GraphRAG가 유리합니다/)).toBeTruthy();
    expect(screen.getByRole('region', { name: '검색 결과 2편' })).toBeTruthy();
    expect(within(screen.getByRole('region', { name: '참고 논문' })).getByText('From Local to Global')).toBeTruthy();

    const artifact = screen.getByRole('complementary', { name: '검색 결과 아티팩트' });
    expect(await within(artifact).findByTestId('graph')).toBeTruthy();

    expect(screen.queryByRole('textbox', { name: '이어서 물어보세요' })).toBeNull();
    // A guest's sidebar here ends with the sign-in card.
    const signin = document.querySelector('.home-signin') as HTMLElement;
    expect(within(signin).getByText('로그인하면 대화가 저장돼요')).toBeTruthy();
    expect(screen.getByRole('button', { name: '로그인하고 이어서 물어보기' })).toBeTruthy();
    const others = await screen.findByRole('navigation', { name: '다른 샘플 보기' });
    expect(within(others).getByRole('link', { name: '장기 대화 기억 논문 보여줘' }).getAttribute('href')).toBe('/samples/long-term-agent-memory');
  });

  it('asks a guest to sign in, then starts a conversation with the sample\'s question', async () => {
    const view = render(routes());
    await screen.findByRole('heading', { name: /상담 예시/ });
    await screen.findByRole('navigation', { name: '다른 샘플 보기' });
    fireEvent.click(screen.getByRole('button', { name: '로그인하고 이어서 물어보기' }));
    expect(authState.setShowLoginModal).toHaveBeenCalledWith(true);
    expect(createConversation).not.toHaveBeenCalled();

    authState.isAuthenticated = true;
    await act(async () => { view.rerender(routes()); });
    expect(createConversation).toHaveBeenCalledWith('GraphRAG가 RAG보다 나은 경우는?');
    expect(await screen.findByText('conversation conv-7')).toBeTruthy();
  });

  it('records the sample funnel: page view, CTA click, then conversation start only once it exists', async () => {
    vi.mocked(trackSampleView).mockClear();
    vi.mocked(trackSampleCtaClick).mockClear();
    vi.mocked(trackConversationStart).mockClear();
    const view = render(routes());
    await screen.findByRole('heading', { name: /상담 예시/ });
    expect(trackSampleView).toHaveBeenCalledWith('sample_page', 'graphrag-vs-rag');

    fireEvent.click(screen.getByRole('button', { name: '로그인하고 이어서 물어보기' }));
    expect(trackSampleCtaClick).toHaveBeenCalledWith('sample_page', 'graphrag-vs-rag');
    expect(trackConversationStart).not.toHaveBeenCalled();

    authState.isAuthenticated = true;
    await act(async () => { view.rerender(routes()); });
    await screen.findByText('conversation conv-7');
    expect(trackConversationStart).toHaveBeenCalledTimes(1);
    expect(trackConversationStart).toHaveBeenCalledWith('sample_cta');
  });

  it('does not record a conversation start when creating it fails', async () => {
    vi.mocked(trackConversationStart).mockClear();
    vi.mocked(createConversation).mockRejectedValue(new Error('down'));
    authState.isAuthenticated = true;
    render(routes());
    await screen.findByRole('heading', { name: /상담 예시/ });
    fireEvent.click(screen.getByRole('button', { name: '로그인하고 이어서 물어보기' }));
    expect(await screen.findByText('대화를 시작하지 못했어요. 잠시 후 다시 시도해 주세요.')).toBeTruthy();
    expect(trackConversationStart).not.toHaveBeenCalled();
  });

  it('opens on the conversation, not the graph sheet, on a narrow screen', async () => {
    setViewport(false);
    render(routes());
    expect(await screen.findByText(/전역 질문에는 GraphRAG가 유리합니다/)).toBeTruthy();
    expect(screen.queryByRole('complementary', { name: '검색 결과 아티팩트' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '아티팩트' }));
    expect(screen.getByRole('complementary', { name: '검색 결과 아티팩트' })).toBeTruthy();
  });

  it('says so when the sample does not exist', async () => {
    vi.mocked(fetchSampleConversation).mockRejectedValueOnce({ response: { status: 404 } });
    render(routes());
    expect((await screen.findByRole('alert')).textContent).toContain('이 상담 예시를 찾을 수 없어요.');
  });
});
