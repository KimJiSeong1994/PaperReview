import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import MyPage from '../components/MyPage';
import { createConversation } from '../api/conversations';

// MyPage is wiring; every panel and hook is replaced so the test sees only the
// wiring: which tab renders, what the URL says, what the report is handed.
const bm = {
  bookmarks: [], filteredBookmarks: [], topicGroups: {}, allTopics: [],
  selectedBookmark: null, bookmarkDetail: null, loadingBookmarks: false, loadingDetail: false,
  selectedIds: new Set<string>(), searchQuery: '', allNotesMode: false, topicAccordionOpen: {},
  loadBookmarks: vi.fn(), setBookmarks: vi.fn(), setBookmarkDetail: vi.fn(), handleSelectBookmark: vi.fn(),
};
const hl = { initFromDetail: vi.fn(), setHighlightPopover: vi.fn(), userHighlights: [], sortedHighlights: [] };
const reportSpy = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useBookmarks', () => ({ useBookmarks: () => bm }));
vi.mock('../hooks/useHighlights', () => ({ useHighlights: () => hl }));
vi.mock('../hooks/useExploration', () => ({ useExploration: () => ({}) }));
vi.mock('../components/mypage/BookmarkSidebar', () => ({ default: () => <div data-testid="sidebar" /> }));
vi.mock('../components/mypage/ReportViewer', () => ({
  default: (props: Record<string, unknown>) => { reportSpy(props); return <div data-testid="report" />; },
}));
vi.mock('../components/AgentKeyButton', () => ({ default: () => null }));
vi.mock('../api/conversations', () => ({ createConversation: vi.fn() }));

function Probe() {
  const location = useLocation();
  return <output data-testid="probe">{location.pathname}{location.search}|{location.state === null ? 'null' : 'state'}</output>;
}

function StateProbe() {
  const location = useLocation();
  return <output data-testid="state-probe">{JSON.stringify({ pathname: location.pathname, state: location.state })}</output>;
}

const renderAt = (entry: string | { pathname: string; state: unknown }) => render(
  <MemoryRouter initialEntries={[entry]}>
    <MyPage onBack={() => {}} />
    <Probe />
  </MemoryRouter>,
);

beforeEach(() => { vi.clearAllMocks(); });

describe('MyPage 대화에서 열기', () => {
  it('starts a conversation about the selected bookmark and opens it with the run flag and its review', async () => {
    Object.assign(bm, {
      selectedBookmark: { id: 'bm_1', title: 'GraphRAG 서베이', session_id: 'rev-bm' },
      bookmarkDetail: { id: 'bm_1', title: 'GraphRAG 서베이', papers: [] },
    });
    vi.mocked(createConversation).mockResolvedValue({ id: 'conv-9', title: 't', turn_id: 'u' });
    try {
      render(
        <MemoryRouter initialEntries={['/mypage']}>
          <Routes>
            <Route path="/mypage" element={<MyPage onBack={() => {}} />} />
            <Route path="/c/:id" element={<StateProbe />} />
          </Routes>
        </MemoryRouter>,
      );
      await screen.findByTestId('report');
      const props = reportSpy.mock.calls.at(-1)![0] as { onOpenInConversation: () => Promise<void> };
      await act(async () => { await props.onOpenInConversation(); });
      expect(createConversation).toHaveBeenCalledWith('북마크 "GraphRAG 서베이"의 리포트를 바탕으로 이야기해 줘');
      const handed = JSON.parse(screen.getByTestId('state-probe').textContent!);
      expect(handed).toEqual({ pathname: '/c/conv-9', state: { run: true, openReview: 'rev-bm', openReviewTitle: 'GraphRAG 서베이' } });
    } finally {
      Object.assign(bm, { selectedBookmark: null, bookmarkDetail: null });
    }
  });

  it('hands the report an inline error when the conversation cannot be created', async () => {
    Object.assign(bm, {
      selectedBookmark: { id: 'bm_1', title: 'GraphRAG 서베이' },
      bookmarkDetail: { id: 'bm_1', title: 'GraphRAG 서베이', papers: [] },
    });
    vi.mocked(createConversation).mockRejectedValue(new Error('503'));
    try {
      renderAt('/mypage');
      await screen.findByTestId('report');
      const props = reportSpy.mock.calls.at(-1)![0] as { onOpenInConversation: () => Promise<void> };
      await act(async () => { await props.onOpenInConversation(); });
      expect(reportSpy.mock.calls.at(-1)![0]).toMatchObject({
        conversationError: '대화를 시작하지 못했어요. 잠시 후 다시 시도해 주세요.',
        openingConversation: false,
      });
    } finally {
      Object.assign(bm, { selectedBookmark: null, bookmarkDetail: null });
    }
  });
});

describe('MyPage view wiring', () => {
  it('sends the old ?tab=curriculum link on to the curriculum route without fetching first', async () => {
    // Rendered through routes, as in the app: the redirect swaps the page out,
    // so MyPage must not have asked for bookmarks on its way to the exit.
    render(
      <MemoryRouter initialEntries={['/mypage?tab=curriculum']}>
        <Routes>
          <Route path="/mypage" element={<MyPage onBack={() => {}} />} />
          <Route path="/curriculum" element={<div data-testid="curriculum-route" />} />
        </Routes>
        <Probe />
      </MemoryRouter>,
    );
    await screen.findByTestId('curriculum-route');
    expect(screen.getByTestId('probe')).toHaveTextContent('/curriculum|null');
    expect(bm.loadBookmarks).not.toHaveBeenCalled();
  });

  it('shows the bookmark view without a tablist, keeping the 커리큘럼 link', async () => {
    renderAt('/mypage');
    await screen.findByTestId('report');
    expect(screen.queryByRole('tablist')).toBeNull();
    expect(screen.queryByRole('tab')).toBeNull();
    expect(screen.queryByText('기억')).toBeNull();
    expect(screen.getByRole('link', { name: '커리큘럼' })).toHaveAttribute('href', '/curriculum');
    const view = screen.getByRole('region', { name: '북마크' });
    expect(view).toContainElement(screen.getByTestId('sidebar'));
    expect(view).toContainElement(screen.getByTestId('report'));
    expect(bm.loadBookmarks).toHaveBeenCalledTimes(1);
  });

  it.each(['/mypage?tab=memory', '/mypage?tab=papers'])('opens the bookmark view for an old %s link', async (entry) => {
    renderAt(entry);
    expect(await screen.findByTestId('report')).toBeVisible();
    expect(screen.getByTestId('sidebar')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '집현전이 기억하는 것' })).toBeNull();
  });

  it('hands the report the real popover setter instead of a no-op', async () => {
    renderAt('/mypage');
    await screen.findByTestId('report');
    expect(reportSpy.mock.lastCall![0].setHighlightPopover).toBe(hl.setHighlightPopover);
  });
});
