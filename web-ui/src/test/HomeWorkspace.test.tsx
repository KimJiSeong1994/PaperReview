import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import HomeWorkspace from '../components/home/HomeWorkspace';
import { relativeLabel } from '../components/home/homeTime';

// jsdom's default localStorage is broken in this setup (see AdminPage.members.test);
// use the same in-memory shim the analytics tests rely on.
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

const authState = vi.hoisted(() => ({
  isAuthenticated: true,
  setShowLoginModal: vi.fn(),
  logout: vi.fn(),
}));

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => authState }));
vi.mock('../api/recommendations', () => ({
  fetchRecommendationNotifications: vi.fn().mockResolvedValue({
    items: [{
      canonical_key: 'rec-1', final_rank: 1, display_position: 1, seen: false,
      title: 'Dynamic Graph RAG with Event-Centric Reasoning', abstract: null, authors: [],
      year: 2026, publication_date: null, venue: 'arXiv', url: 'https://arxiv.org/abs/1', pdf_url: null,
      doi: null, arxiv_id: null, openalex_id: null, semantic_scholar_id: null, pmid: null,
      score: 0.9, reason: '북마크한 GRAG와 제목 유사도가 높아요', candidate_sources: ['arxiv'], score_breakdown: {},
    }],
    unread_count: 1, total_count: 7, latest_run_at: new Date().toISOString(), run_id: 'run-1',
    scoring_mode: null, state: 'ready', freshness: 'fresh', source_statuses: {},
    degraded_reasons: ['Semantic Scholar 응답이 늦어 2편은 제외됐어요.'],
  }),
}));
vi.mock('../api/bookmarks', () => ({
  getBookmarks: vi.fn().mockResolvedValue({ bookmarks: [{ id: 'b1', title: 'GRAG', session_id: 's', query: 'q', num_papers: 2, created_at: '', tags: [], topic: 'graphrag' }] }),
}));
vi.mock('../api/curriculum', () => ({
  fetchCurricula: vi.fn().mockResolvedValue({ curricula: [{ id: 'c1', name: 'GraphRAG 입문', university: '', instructor: '', difficulty: 'beginner', prerequisites: [], description: '', url: '', total_papers: 12, total_modules: 6 }] }),
}));
vi.mock('../api/me', () => ({
  fetchMyReviewSessions: vi.fn().mockResolvedValue({
    sessions: [{ session_id: 'review_1', status: 'processing', progress: '검증 2/3', num_papers: 2, created_at: new Date().toISOString(), title: 'GRAG' }],
    total: 1,
  }),
}));
vi.mock('../api/blog', () => ({
  fetchBlogPosts: vi.fn().mockResolvedValue({ data: { posts: [{ slug: 'kronlstm', title: 'KronLSTM 페어 리뷰' }] } }),
}));

function renderHome(onSearch = vi.fn()) {
  render(
    <MemoryRouter>
      <HomeWorkspace
        attemptedQuery=""
        onSearch={onSearch}
        guidanceMessage={null}
        guidanceSticky={false}
        onQueryChange={vi.fn()}
      />
    </MemoryRouter>,
  );
  return onSearch;
}

describe('HomeWorkspace', () => {
  beforeEach(() => {
    authState.isAuthenticated = true;
    localStorage.clear();
    localStorage.setItem('username', 'jiseong');
    localStorage.setItem('jh.recentSearches', JSON.stringify([
      { query: 'graph retrieval augmented generation', at: new Date().toISOString() },
    ]));
  });

  it('shows the member workspace: history, continue rows, picks, and account', async () => {
    const onSearch = renderHome();

    expect(await screen.findByText('GRAG 딥리뷰')).toBeTruthy();
    expect(screen.getByText('진행 중')).toBeTruthy();
    expect(screen.getByRole('link', { name: /GraphRAG 입문/ })).toBeTruthy();
    expect(screen.getByText('jiseong')).toBeTruthy();

    expect(screen.getByRole('heading', { name: '이어서 하기' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /결과 다시 보기/ }));
    expect(onSearch).toHaveBeenCalledWith('graph retrieval augmented generation');

    expect(await screen.findByText('Dynamic Graph RAG with Event-Centric Reasoning')).toBeTruthy();
    expect(screen.getByText('북마크한 GRAG와 제목 유사도가 높아요')).toBeTruthy();
    expect(screen.getByRole('button', { name: '다시 불러오기' })).toBeTruthy();
    expect(screen.getByText(/전체 7편/)).toBeTruthy();
    expect(screen.getByText('북마크 1편 중에서 골라 딥리뷰 만들기')).toBeTruthy();
  });

  it('clears the composer on 새 검색 and toggles the drawer accessibly', async () => {
    renderHome();
    const box = screen.getByRole('textbox', { name: '검색어' }) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: 'draft' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '새 검색' }));
    });
    // 새 검색 remounts the composer, so query the fresh box.
    expect((screen.getByRole('textbox', { name: '검색어' }) as HTMLTextAreaElement).value).toBe('');

    // Vitest loads the CSS, which hides the drawer button at desktop width; include hidden elements.
    const menu = screen.getByLabelText('기록 열기');
    expect(menu.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(menu);
    expect(menu.getAttribute('aria-expanded')).toBe('true');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(menu.getAttribute('aria-expanded')).toBe('false');
  });

  it('shows the guest shell with sign-in guidance and public reviews', async () => {
    authState.isAuthenticated = false;
    renderHome();

    expect(screen.getByText('논문을 찾은 뒤, 근거까지 읽습니다.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '로그인' }));
    expect(authState.setShowLoginModal).toHaveBeenCalledWith(true);
    expect(screen.queryByRole('heading', { name: '이어서 하기' })).toBeNull();
    expect(await screen.findAllByText('KronLSTM 페어 리뷰')).toHaveLength(2);
    expect(screen.getByText(/로그인하고 논문을 3편만 북마크하면/)).toBeTruthy();
  });

  it('labels time relative to now', () => {
    const now = new Date('2026-10-31T12:00:00Z');
    expect(relativeLabel('2026-10-31T11:59:40Z', now)).toBe('방금');
    expect(relativeLabel('2026-10-31T11:30:00Z', now)).toBe('30분 전');
    expect(relativeLabel('2026-10-30T12:00:00Z', now)).toBe('어제');
    expect(relativeLabel('2026-10-27T12:00:00Z', now)).toBe('4일 전');
    expect(relativeLabel('not a date', now)).toBe('');
  });
});
