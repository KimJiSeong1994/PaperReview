import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { createRef, type ComponentProps, type ReactNode } from 'react';
import ReportViewer from '../components/mypage/ReportViewer';

const detail = {
  id: 'bm_1', title: 'Graph RAG survey', query: 'graph rag 2026',
  papers: [], report_markdown: '# Report\n\nBody', notes: '', highlights: [],
};
const share = { token: 'tok123', share_url: '/share/tok123', created_at: '2026-09-01T00:00:00Z', expires_at: '2099-01-01T00:00:00Z' };

const base: ComponentProps<typeof ReportViewer> = {
  bookmarkDetail: detail, loadingDetail: false, hasSelectedBookmark: true,
  reportScrollRef: createRef<HTMLDivElement>(),
  highlightTerms: [], setHighlightTerms: vi.fn(), highlightChildren: (children: ReactNode) => children,
  userHighlights: [], sortedHighlights: [], applyUserHighlights: (children: ReactNode) => children,
  expandedHighlightId: null, setExpandedHighlightId: vi.fn(),
  highlightPopover: null, popoverPos: null, setHighlightPopover: vi.fn(),
  notesText: '', setNotesText: vi.fn(), notesSaving: false, notesCollapsed: true, setNotesCollapsed: vi.fn(),
  saveStatus: 'idle', autoHighlighting: false,
  onSaveNotes: vi.fn(), onAutoHighlight: vi.fn(), onClearAllHighlights: vi.fn(), onRemoveHighlight: vi.fn(),
  papersCollapsed: true, setPapersCollapsed: vi.fn(), onExportReport: vi.fn(),
  selectionToolbar: null, memoMode: false, memoInput: '', setMemoInput: vi.fn(),
  onAddHighlight: vi.fn(), onStartMemo: vi.fn(), onSaveMemo: vi.fn(), onCancelMemo: vi.fn(),
  citationTreeData: null, citationTreeLoading: false, citationTreeError: null, citationTreeWarning: null,
  onGenerateCitationTree: vi.fn(), onDeleteCitationTree: vi.fn(), onRenameBookmark: vi.fn(),
  shareInfo: null, shareLoading: false, onCreateShare: vi.fn(), onRevokeShare: vi.fn(),
} as unknown as ComponentProps<typeof ReportViewer>;

const setClipboard = (writeText: unknown) => {
  Object.defineProperty(navigator, 'clipboard', { value: writeText === undefined ? undefined : { writeText }, configurable: true });
  // The helper only trusts the async API on secure origins; jsdom is not one by default.
  Object.defineProperty(window, 'isSecureContext', { value: writeText !== undefined, configurable: true });
};

beforeEach(() => vi.clearAllMocks());
afterEach(() => setClipboard(undefined));

describe('ReportViewer without a chat panel or PDF tab', () => {
  it('points the empty state at conversations for questions about bookmarks', () => {
    render(<ReportViewer {...base} hasSelectedBookmark={false} />);
    expect(screen.getByText(/북마크에 대해 묻고 싶으면 ‘대화에서 열기’를 누르거나 홈에서 ‘내 북마크에서 …’라고 물어보세요/)).toBeTruthy();
  });

  it('opens each listed paper in the standalone viewer, in a new tab', () => {
    const papers = [{ title: 'HippoRAG', authors: ['B. Gutiérrez', 'Y. Shu'], year: 2024, pdf_url: 'https://arxiv.org/pdf/2405.14831' }];
    render(<ReportViewer {...base} bookmarkDetail={{ ...detail, papers }} papersCollapsed={false} />);
    const link = screen.getByRole('link', { name: /PDF 보기/ });
    const href = new URL(link.getAttribute('href')!, 'https://x');
    expect(href.pathname).toBe('/paper-viewer');
    expect(href.searchParams.get('title')).toBe('HippoRAG');
    expect(href.searchParams.get('pdf_url')).toBe('https://arxiv.org/pdf/2405.14831');
    expect(href.searchParams.get('authors')).toBe('B. Gutiérrez;Y. Shu');
    expect(href.searchParams.get('year')).toBe('2024');
    expect(href.searchParams.get('source')).toBe('bookmark');
    expect(link.getAttribute('target')).toBe('_blank');
  });
});

describe('ReportViewer header', () => {
  it('offers 대화에서 열기 beside the export actions and shows its error inline', () => {
    const onOpenInConversation = vi.fn();
    const { rerender } = render(<ReportViewer {...base} onOpenInConversation={onOpenInConversation} />);
    fireEvent.click(screen.getByRole('button', { name: /대화에서 열기/ }));
    expect(onOpenInConversation).toHaveBeenCalledTimes(1);
    rerender(<ReportViewer {...base} onOpenInConversation={onOpenInConversation} openingConversation />);
    expect(screen.getByRole('button', { name: /여는 중/ })).toBeDisabled();
    rerender(<ReportViewer {...base} onOpenInConversation={onOpenInConversation} conversationError="대화를 시작하지 못했어요." />);
    expect(screen.getByRole('alert').textContent).toBe('대화를 시작하지 못했어요.');
  });

  it('calls the highlight pass what it is, and shows the question the report answered', () => {
    render(<ReportViewer {...base} />);
    expect(screen.queryByText('Auto Review')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /자동 하이라이트/ }));
    expect(base.onAutoHighlight).toHaveBeenCalledTimes(1);
    expect(screen.getByText('검색어 · graph rag 2026')).toBeInTheDocument();
  });

  it('opens the title editor from a visible button, not only a double-click', () => {
    render(<ReportViewer {...base} />);
    fireEvent.click(screen.getByRole('button', { name: '제목 수정' }));
    expect(screen.getByDisplayValue('Graph RAG survey')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '제목 수정' })).not.toBeInTheDocument();
  });

  it('returns focus to the rename button after a keyboard exit, and saves on Enter', () => {
    render(<ReportViewer {...base} />);
    fireEvent.click(screen.getByRole('button', { name: '제목 수정' }));
    fireEvent.keyDown(screen.getByDisplayValue('Graph RAG survey'), { key: 'Escape' });
    expect(screen.getByRole('button', { name: '제목 수정' })).toHaveFocus();
    expect(base.onRenameBookmark).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '제목 수정' }));
    const input = screen.getByDisplayValue('Graph RAG survey');
    fireEvent.change(input, { target: { value: 'Renamed' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(base.onRenameBookmark).toHaveBeenCalledWith('Renamed');
    expect(screen.getByRole('button', { name: '제목 수정' })).toHaveFocus();
  });

  it('folds the paper list from the keyboard and names its regions in Korean', () => {
    const withPapers = { ...detail, papers: [{ title: 'Paper A', authors: ['A'], year: 2024 }] };
    render(<ReportViewer {...base} bookmarkDetail={withPapers} />);
    expect(screen.getByRole('region', { name: '리서치 리포트' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '메모와 하이라이트' })).toBeInTheDocument();
    const header = screen.getByRole('button', { name: /논문 \(1\)|Papers \(1\)/ });
    expect(header).toHaveAttribute('aria-expanded', 'false');
    fireEvent.keyDown(header, { key: 'Enter' });
    expect(base.setPapersCollapsed).toHaveBeenCalledWith(false);
  });

  it('labels the citation keyword bar honestly', () => {
    render(<ReportViewer {...base} highlightTerms={['retrieval']} />);
    expect(screen.getByText('인용 키워드 표시 중')).toBeInTheDocument();
    expect(screen.queryByText('Evidence highlighted')).not.toBeInTheDocument();
  });

  it('does not claim a copy that did not happen', async () => {
    setClipboard(undefined);
    render(<ReportViewer {...base} shareInfo={share} />);
    fireEvent.click(screen.getByRole('button', { name: '복사' }));
    expect(await screen.findByRole('button', { name: '복사 실패' })).toBeInTheDocument();
  });

  it('reports a rejected clipboard write, and a successful one', async () => {
    const writeText = vi.fn().mockRejectedValueOnce(new Error('denied')).mockResolvedValueOnce(undefined);
    setClipboard(writeText);
    // The label resets on a two-second timer; fake the clock before it is set
    // so the reset can be stepped instead of waited out.
    vi.useFakeTimers();
    try {
      render(<ReportViewer {...base} shareInfo={share} />);
      fireEvent.click(screen.getByRole('button', { name: '복사' }));
      await act(async () => {});
      expect(screen.getByRole('button', { name: '복사 실패' })).toBeInTheDocument();

      act(() => { vi.advanceTimersByTime(2000); });
      expect(screen.getByRole('button', { name: '복사' })).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: '복사' }));
      await act(async () => {});
      expect(screen.getByRole('button', { name: '복사됨!' })).toBeInTheDocument();
      expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/share/tok123`);
    } finally {
      vi.useRealTimers();
    }
  });
});
