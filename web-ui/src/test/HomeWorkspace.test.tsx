import { act, fireEvent, render, screen, within, waitFor } from '@testing-library/react';
import { afterEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import HomeWorkspace from '../components/home/HomeWorkspace';
import { fetchRecommendationNotifications } from '../api/recommendations';
import { fetchMyConversations } from '../api/conversations';
import { fetchMyReviewSessions } from '../api/me';
import { relativeLabel } from '../components/home/homeTime';
import { userInitials } from '../components/home/userInitials';
import { clipToSentence, sampleExchange } from '../components/home/sampleExchange';

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
  userRole: 'user',
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
vi.mock('../api/conversations', () => ({
  fetchMyConversations: vi.fn().mockResolvedValue([]),
}));
const samplesApi = vi.hoisted(() => ({
  fetchSampleConversations: vi.fn(),
  fetchSampleConversation: vi.fn(),
}));
vi.mock('../api/samples', () => samplesApi);
const events = vi.hoisted(() => ({ trackSampleView: vi.fn(), trackSampleCtaClick: vi.fn() }));
vi.mock('../analytics/events', () => events);
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
    samplesApi.fetchSampleConversations.mockReset().mockResolvedValue([]);
    samplesApi.fetchSampleConversation.mockReset();
    vi.mocked(fetchMyReviewSessions).mockClear();
    authState.isAuthenticated = true;
    authState.userRole = 'user';
    localStorage.clear();
    localStorage.setItem('username', 'jiseong');
    localStorage.setItem('jh.recentSearches:jiseong', JSON.stringify([
      { query: 'graph retrieval augmented generation', at: new Date().toISOString() },
    ]));
  });

  it('shows the member workspace: history, continue rows, picks, and account', async () => {
    const onSearch = renderHome();

    expect(await screen.findByText('GRAG 딥리뷰')).toBeTruthy();
    expect(screen.getByText('진행 중')).toBeTruthy();
    // The sidebar reuses the home's review list instead of requesting it again.
    expect(fetchMyReviewSessions).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('link', { name: /GraphRAG 입문/ })).toBeTruthy();
    expect(screen.getByText('jiseong')).toBeTruthy();

    expect(screen.getByRole('heading', { name: '이어서 하기' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /결과 다시 보기/ }));
    expect(onSearch).toHaveBeenCalledWith('graph retrieval augmented generation');

    expect(await screen.findByText('Dynamic Graph RAG with Event-Centric Reasoning')).toBeTruthy();
    expect(screen.getByText('북마크한 GRAG와 제목 유사도가 높아요')).toBeTruthy();
    expect(screen.getByRole('button', { name: '다시 불러오기' })).toBeTruthy();
    expect(screen.getByText(/오늘 추천 7편/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /최근 장기 대화 기억 논문을 찾아서 핵심 내용 설명해줘/ }));
    expect((screen.getByRole('textbox', { name: '논문 검색' }) as HTMLTextAreaElement).value)
      .toBe('최근 장기 대화 기억 논문을 찾아서 핵심 내용 설명해줘');
    expect(onSearch).toHaveBeenCalledTimes(1);
  });

  it('clears the composer on 새 대화 and toggles the drawer accessibly', async () => {
    renderHome();
    const box = screen.getByRole('textbox', { name: '논문 검색' }) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: 'draft' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '새 대화' }));
    });
    // 새 대화 remounts the composer, so query the fresh box.
    expect((screen.getByRole('textbox', { name: '논문 검색' }) as HTMLTextAreaElement).value).toBe('');

    // Vitest loads the CSS, which hides the drawer button at desktop width; include hidden elements.
    const menu = screen.getByLabelText('기록 열기');
    expect(menu.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(menu);
    expect(menu.getAttribute('aria-expanded')).toBe('true');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(menu.getAttribute('aria-expanded')).toBe('false');
  });

  it('gives guests a sidebar-free home: mascot intro, composer, public reviews, no account blocks', async () => {
    authState.isAuthenticated = false;
    renderHome();

    expect(screen.queryByRole('navigation', { name: '내 기록' })).toBeNull();
    expect(screen.queryByRole('complementary', { name: '오늘의 추천' })).toBeNull();
    expect(screen.queryByRole('heading', { name: '이어서 하기' })).toBeNull();
    expect(screen.getByText('궁금한 주제나 논문 제목을 편하게 물어보세요.')).toBeTruthy();
    expect(screen.getByText('집현전이 여러 소스에서 찾아 근거까지 읽어 드려요.')).toBeTruthy();
    expect(document.querySelector('.home-guest-mascot picture.mascot-face img')!.getAttribute('width')).toBe('80');
    // Public reviews are not on the guest home; the left column ends with the samples.
    await screen.findByText('집현전이 여러 소스에서 찾아 근거까지 읽어 드려요.');
    expect(screen.queryByRole('heading', { name: '공개 리뷰 읽어보기' })).toBeNull();
    expect(screen.queryByText('KronLSTM 페어 리뷰')).toBeNull();
  });

  it('keeps the workspace up when the recommendation response has no items', async () => {
    vi.mocked(fetchRecommendationNotifications).mockResolvedValueOnce(
      {} as Awaited<ReturnType<typeof fetchRecommendationNotifications>>,
    );
    renderHome();

    expect(await screen.findByText('GRAG 딥리뷰')).toBeTruthy();
    expect(screen.getByRole('textbox', { name: '논문 검색' })).toBeTruthy();
    expect(screen.queryByText('Dynamic Graph RAG with Event-Centric Reasoning')).toBeNull();
  });

  it('lists saved conversations in the sidebar instead of device searches', async () => {
    vi.mocked(fetchMyConversations).mockResolvedValueOnce([
      { id: 'conv-9', title: 'LightRAG 비교', updated_at: new Date().toISOString(), turn_count: 2, last_intent: 'search' },
    ]);
    renderHome();
    const nav = screen.getByRole('navigation', { name: '내 기록' });
    const link = await within(nav).findByRole('link', { name: /LightRAG 비교/ });
    expect(link.getAttribute('href')).toBe('/c/conv-9');
    expect(within(nav).queryByText('graph retrieval augmented generation')).toBeNull();
  });

  it('shows the hero face close-up next to the eyebrow', () => {
    renderHome();
    const eyebrow = document.querySelector('.home-eyebrow')!;
    const img = eyebrow.parentElement!.querySelector('picture.mascot-face img')!;
    expect(img.getAttribute('src')).toBe('/jiphyeonjeon-face.png');
    expect(img.getAttribute('srcset')).toBe('/jiphyeonjeon-face.png 1x, /jiphyeonjeon-face@2x.png 2x');
    expect(img.getAttribute('width')).toBe('28');
    expect(img.getAttribute('alt')).toBe('');
  });

  it('scrolls the history between a fixed 새 대화 button and a pinned account footer', async () => {
    renderHome();
    const nav = screen.getByRole('navigation', { name: '내 기록' });
    await within(nav).findByText('GRAG 딥리뷰');
    const children = [...nav.children];
    const scroll = nav.querySelector('.home-sidebar-scroll')!;
    const account = nav.querySelector('.home-account')!;
    // Order (and so focus order): 새 대화, the scrolling history, then the account.
    expect(children.map(child => child.className)).toEqual(['home-btn home-btn-outline', 'home-sidebar-scroll', 'home-account']);
    expect(scroll.contains(within(nav).getByText('GRAG 딥리뷰'))).toBe(true);
    expect(scroll.contains(account)).toBe(false);
    expect(getComputedStyle(scroll).overflowY).toBe('auto');
  });

  it('shows a user card with initials, name and role, then 설정 and 로그아웃', () => {
    renderHome();
    const account = document.querySelector('.home-account') as HTMLElement;
    expect(account.querySelector('.home-account-avatar')!.textContent).toBe('JI');
    expect(within(account).getByText('jiseong')).toBeTruthy();
    expect(within(account).getByText('연구자')).toBeTruthy();
    expect(within(account).getByRole('link', { name: '설정' }).getAttribute('href')).toBe('/mypage');
    fireEvent.click(within(account).getByRole('button', { name: '로그아웃' }));
    expect(authState.logout).toHaveBeenCalled();
  });

  it('labels an admin account 관리자', () => {
    authState.userRole = 'admin';
    renderHome();
    expect(within(document.querySelector('.home-account') as HTMLElement).getByText('관리자')).toBeTruthy();
  });

  it('derives avatar initials', () => {
    expect(userInitials('jiseong')).toBe('JI');
    expect(userInitials('home_demo')).toBe('HO');
    expect(userInitials('한지성')).toBe('한');
    expect(userInitials('_x')).toBe('X');
    expect(userInitials('')).toBe('?');
  });

  describe('guest home with samples', () => {
    const summaries = [
      { id: 's1', slug: 'graphrag-vs-rag', title: 'GraphRAG vs RAG', question: 'GraphRAG가 RAG보다 나은 경우는?', asof: '2026-10-25', turn_count: 2 },
      { id: 's2', slug: 'graphrag-core-explained', title: 'GraphRAG 핵심', question: 'GraphRAG 핵심을 설명해줘', asof: '2026-10-25', turn_count: 2 },
      { id: 's3', slug: 'long-term-agent-memory', title: '장기 기억', question: '장기 대화 기억 논문 보여줘', asof: '2026-10-25', turn_count: 2 },
    ];
    const lead = '그래프가 도움이 되는 경우를 정리했어요.';
    const detail = {
      id: 's1', slug: 'graphrag-vs-rag', title: 'GraphRAG vs RAG', asof: '2026-10-25',
      turns: [
        { seq: 1, role: 'user', content: 'GraphRAG가 RAG보다 나은 경우는?', blocks: [], intent: null },
        {
          seq: 2, role: 'assistant', intent: 'search',
          content: `${lead}\n\n전역 질문에서는 GraphRAG가 유리합니다 [1].\n\n세 번째 문단은 패널에 나오지 않아요.`,
          blocks: [{
            type: 'search_results', query: 'q', total: 4, query_hash: 'h', partial: false, degraded: [],
            papers: ['From Local to Global', 'LightRAG', 'HippoRAG', 'Fourth paper'].map((title, index) => ({
              doc_id: `d${index + 1}`, title, authors: ['Darren Edge'], year: 2024, source: 'arxiv',
            })),
          }],
        },
        // The sample goes on; the panel plays only the first exchange.
        ...Array.from({ length: 12 }, (_, index) => ({
          seq: index + 3, role: index % 2 === 0 ? 'user' : 'assistant', intent: null, blocks: [],
          content: index % 2 === 0 ? `후속 질문 ${index}` : `후속 답변 ${index}`,
        })),
      ],
    };
    const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
    // Each typed word schedules the next from an effect, so playback needs a commit per step.
    const play = async (ms: number) => {
      for (let elapsed = 0; elapsed < ms; elapsed += 40) await tick(40);
    };

    beforeEach(() => {
      authState.isAuthenticated = false;
      samplesApi.fetchSampleConversations.mockResolvedValue(summaries);
      samplesApi.fetchSampleConversation.mockResolvedValue(detail);
    });
    afterEach(() => {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    });

    it('shows the pill, the guest composer with a sample placeholder, and three sample cards as buttons', async () => {
      renderHome();
      expect(screen.getByText('논문 연구 AI, 로그인 후 무료')).toBeTruthy();
      // Korean breaks only at spaces on the whole guest home (no lone "줘" on a line).
      expect(getComputedStyle(document.querySelector('.home-guest')!).wordBreak).toBe('keep-all');
      expect(screen.getByRole('button', { name: '무료로 물어보기' })).toBeTruthy();
      const note = screen.getByText('내 질문은 로그인 후 무료로 검색·대화해요.');
      // The note sits under the composer card, not inside it.
      expect(note.closest('form')).toBeNull();
      expect(screen.queryByRole('heading', { name: '집현전에 이런 걸 맡겨 보세요' })).toBeNull();

      const section = (await screen.findByRole('heading', { name: '샘플 질문으로 먼저 써보세요' })).closest('section')!;
      expect(within(section).getByText('로그인 없이 답변 보기')).toBeTruthy();
      const cards = within(section).getAllByRole('button');
      expect(cards).toHaveLength(3);
      expect(cards.map(card => card.getAttribute('aria-pressed'))).toEqual(['true', 'false', 'false']);
      expect(cards[0].textContent).toContain('GraphRAG가 RAG보다 나은 경우는?');
      expect(cards[0].textContent).toContain('GraphRAG vs RAG');
      expect(within(section).queryByRole('link')).toBeNull();
      expect((screen.getByRole('textbox', { name: '논문 검색' }) as HTMLTextAreaElement).placeholder)
        .toBe('예) GraphRAG가 RAG보다 나은 경우는?');
    });

    it('plays the clicked card\'s sample in the panel, with 전체 답변 pointing at its page', async () => {
      samplesApi.fetchSampleConversation.mockImplementation(async (slug: string) => ({
        ...detail,
        slug,
        turns: [{ ...detail.turns[0], content: `질문: ${slug}` }, detail.turns[1]],
      }));
      renderHome();
      const panel = (await screen.findByRole('heading', { name: '집현전과의 대화' })).closest('section')!;
      expect(await within(panel).findByText('질문: graphrag-vs-rag')).toBeTruthy();
      expect(within(panel).getByRole('link', { name: '전체 답변 ↗' }).getAttribute('href')).toBe('/samples/graphrag-vs-rag');

      const cards = within(screen.getByRole('heading', { name: '샘플 질문으로 먼저 써보세요' }).closest('section')!).getAllByRole('button');
      fireEvent.click(cards[1]);
      expect(cards[1].getAttribute('aria-pressed')).toBe('true');
      expect(cards[0].getAttribute('aria-pressed')).toBe('false');
      const next = (await screen.findByRole('heading', { name: '집현전과의 대화' })).closest('section')!;
      expect(await within(next).findByText('질문: graphrag-core-explained')).toBeTruthy();
      expect(within(next).getByRole('link', { name: '전체 답변 ↗' }).getAttribute('href')).toBe('/samples/graphrag-core-explained');
      expect(within(next).queryByRole('button', { name: /다른 샘플 보기/ })).toBeNull();
    });

    it('plays one exchange in a fixed panel: question, lead, three results, conclusion, then the CTA', async () => {
      vi.useFakeTimers();
      const onSearch = renderHome();
      await tick(0);
      await tick(0);
      const replay = screen.getByRole('heading', { name: '집현전과의 대화' }).closest('section')!;
      // The card stretches to the left column's height (ending with the last sample card);
      // the body has no fixed height of its own and only fills the card.
      const body = replay.querySelector('.home-replay-body') as HTMLElement;
      expect(getComputedStyle(body).height).not.toBe('520px');
      expect(getComputedStyle(replay.parentElement!).alignSelf).toBe('stretch');
      expect(getComputedStyle(replay.parentElement!).position).not.toBe('sticky');
      expect(within(replay).getByText('2026-10-25 기준 · 상담 예시')).toBeTruthy();
      expect(within(replay).getByRole('status').textContent).toBe('상담 예시 · 재생 중');
      expect(within(replay).getByText('GraphRAG가 RAG보다 나은 경우는?')).toBeTruthy();
      expect(within(replay).getByText('생각하는 중…')).toBeTruthy();
      expect(replay.textContent).not.toContain('그래프가');

      await tick(1200);
      await play(120);
      // Part of the lead is typed, the results not yet.
      expect(replay.textContent).toContain('그래프가');
      expect(replay.textContent).not.toContain(lead);
      expect(within(replay).queryByRole('list', { name: /검색 결과/ })).toBeNull();

      await play(800);
      expect(replay.textContent).toContain(lead);
      const results = within(replay).getByRole('list', { name: '검색 결과 상위 3편' });
      expect(within(results).getAllByRole('listitem').map(item => item.querySelector('.home-replay-paper-title')!.textContent))
        .toEqual(['From Local to Global', 'LightRAG', 'HippoRAG']);
      expect(within(results).getAllByRole('listitem')[0].textContent).toContain('2024 · arxiv');

      // 멈춤 holds the text where it is.
      fireEvent.click(within(replay).getByRole('button', { name: '멈춤' }));
      expect(within(replay).getByRole('status').textContent).toBe('상담 예시 · 멈춤');
      const frozen = replay.textContent;
      await play(1000);
      expect(replay.textContent).toBe(frozen);
      fireEvent.click(within(replay).getByRole('button', { name: '재생' }));
      await play(1500);
      expect(replay.textContent).toContain('전역 질문에서는 GraphRAG가 유리합니다');
      expect(within(replay).getByRole('status').textContent).toBe('상담 예시 · 재생 완료');
      // Finished: no 멈춤/재생 toggle in the footer; 다시 보기 replays.
      expect(within(replay).queryByRole('button', { name: /^(멈춤|재생)$/ })).toBeNull();

      // One exchange only: no later turns, no third paragraph.
      expect(replay.querySelectorAll('.conv-turn.is-user')).toHaveLength(1);
      expect(replay.textContent).not.toContain('후속 질문');
      expect(replay.textContent).not.toContain('세 번째 문단');
      expect(replay.textContent).not.toContain('Fourth paper');
      expect(within(replay).queryByText(/전체 \d+편 보기/)).toBeNull();

      // The CTA comes last and asks this sample's question through the home's sign-in gate.
      expect(within(replay).getByText('내 질문으로 이어서 물어보세요')).toBeTruthy();
      fireEvent.click(within(replay).getByRole('button', { name: '로그인하고 이어서 물어보기 →' }));
      expect(onSearch).toHaveBeenCalledWith('GraphRAG가 RAG보다 나은 경우는?');

      // 다시 보기 starts the same exchange again.
      fireEvent.click(within(replay).getByRole('button', { name: '↻ 다시 보기' }));
      await tick(0);
      expect(within(replay).getByRole('status').textContent).toBe('상담 예시 · 재생 중');
      expect(replay.textContent).not.toContain(lead);
      expect(within(replay).queryByRole('button', { name: '로그인하고 이어서 물어보기 →' })).toBeNull();
    });

    it('records a sample view per replay shown and the CTA click with its slug', async () => {
      events.trackSampleView.mockClear();
      events.trackSampleCtaClick.mockClear();
      vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce'), media: query }));
      const onSearch = vi.fn();
      renderHome(onSearch);

      // The auto-shown first sample is home_default; only a click on another card is home_card.
      const cards = within((await screen.findByRole('heading', { name: '샘플 질문으로 먼저 써보세요' })).closest('section')!).getAllByRole('button');
      await waitFor(() => expect(events.trackSampleView.mock.calls).toEqual([['home_default', 'graphrag-vs-rag']]));
      fireEvent.click(cards[0]);
      expect(events.trackSampleView).toHaveBeenCalledTimes(1);
      fireEvent.click(cards[1]);
      expect(events.trackSampleView.mock.calls).toEqual([
        ['home_default', 'graphrag-vs-rag'],
        ['home_card', 'graphrag-core-explained'],
      ]);

      const replay = (await screen.findByRole('heading', { name: '집현전과의 대화' })).closest('section')!;
      fireEvent.click(await within(replay).findByRole('button', { name: '로그인하고 이어서 물어보기 →' }));
      expect(events.trackSampleCtaClick).toHaveBeenCalledWith('home_card', 'graphrag-core-explained');
      expect(onSearch).toHaveBeenCalledWith('GraphRAG가 RAG보다 나은 경우는?');
    });

    it('shows the whole exchange at once, without playback controls, under reduced motion', async () => {
      vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce'), media: query }));
      renderHome();
      const replay = (await screen.findByRole('heading', { name: '집현전과의 대화' })).closest('section')!;
      expect(await within(replay).findByText(/전역 질문에서는 GraphRAG가 유리합니다/)).toBeTruthy();
      expect(within(within(replay).getByRole('list', { name: '검색 결과 상위 3편' })).getAllByRole('listitem')).toHaveLength(3);
      expect(within(replay).getByRole('button', { name: '로그인하고 이어서 물어보기 →' })).toBeTruthy();
      expect(within(replay).queryByText('생각하는 중…')).toBeNull();
      expect(within(replay).queryByRole('button', { name: '멈춤' })).toBeNull();
      expect(within(replay).queryByRole('button', { name: '↻ 다시 보기' })).toBeNull();
      expect(within(replay).getByRole('status').textContent).toBe('상담 예시');
    });
  });

  it('trims a sample to one exchange, cutting a long conclusion at a sentence end', () => {
    const long = `${'가'.repeat(150)}. ${'나'.repeat(150)}. 끝.`;
    expect(clipToSentence(long)).toBe(`${'가'.repeat(150)}.…`);
    expect(clipToSentence('짧은 결론입니다.')).toBe('짧은 결론입니다.');
    expect(clipToSentence('마침표 없는 '.repeat(40)).endsWith('…')).toBe(true);
    expect(clipToSentence('마침표 없는 '.repeat(40)).length).toBeLessThanOrEqual(241);

    const exchange = sampleExchange({
      id: 's', slug: 's', title: 't', asof: '',
      turns: [
        { seq: 1, role: 'user', content: '질문', blocks: [], intent: null },
        { seq: 2, role: 'assistant', content: `리드.\n\n${long}\n\n셋째.`, blocks: [], intent: null },
        { seq: 3, role: 'user', content: '다음 질문', blocks: [], intent: null },
      ],
    })!;
    expect(exchange).toEqual({ question: '질문', lead: '리드.', papers: [], conclusion: `${'가'.repeat(150)}.…` });
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
