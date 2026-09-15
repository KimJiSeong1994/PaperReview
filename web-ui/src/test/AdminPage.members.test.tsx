import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AdminPage from '../components/AdminPage';
import {
  getAdminUsers,
  getAdminBookmarks,
  getAdminCurricula,
  getAdminDashboard,
  getAdminPaperStats,
  getAdminPapers,
  deleteAdminPapers,
  deleteUser,
} from '../api/client';
import type { AdminDashboard, AdminPaper } from '../api/client';

// ── Module mocks ──────────────────────────────────────────────────────────────

// Stub lazy-loaded report components so Suspense resolves synchronously.
vi.mock('../components/AdminMembersReport', () => ({
  // Expose trigger buttons so tests can fire the member/paper flows without
  // rendering the full member tree.
  default: ({
    onDeleteUser,
    onExpandMember,
    onTogglePaperSelect,
    onDeletePapers,
    folderPapers,
    folderLoading,
    selectedPapers,
  }: {
    onDeleteUser: (u: string) => void;
    onExpandMember: (u: string | null) => void;
    onTogglePaperSelect: (index: number) => void;
    onDeletePapers: () => void;
    folderPapers: AdminPaper[];
    folderLoading: boolean;
    selectedPapers: Set<number>;
  }) => (
    <div data-testid="members-report">
      <button onClick={() => onDeleteUser('bob')}>trigger-delete-bob</button>
      <button onClick={() => onExpandMember('alice')}>expand-alice</button>
      <button onClick={() => onExpandMember('bob')}>expand-bob</button>
      <span data-testid="selected-count">{selectedPapers.size}</span>
      <span data-testid="folder-loading">{String(folderLoading)}</span>
      {folderPapers.map((p) => (
        <button key={p.index} onClick={() => onTogglePaperSelect(p.index)}>
          select-{p.title}
        </button>
      ))}
      <button onClick={onDeletePapers}>delete-selected</button>
    </div>
  ),
}));
vi.mock('../components/AdminDashboardReport', () => ({
  default: () => <div data-testid="dashboard-report" />,
}));
vi.mock('../components/AdminVisitsReport', () => ({
  default: () => <div data-testid="visits-report" />,
}));
vi.mock('../components/AdminMcpReport', () => ({
  default: () => <div data-testid="mcp-report" />,
}));

// Mock the entire api/client module, keeping non-admin exports intact.
vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    getAdminDashboard: vi.fn(),
    getAdminUsers: vi.fn(),
    getAdminBookmarks: vi.fn(),
    getAdminCurricula: vi.fn(),
    getAdminPaperStats: vi.fn(),
    getAdminPapers: vi.fn(),
    deleteAdminPapers: vi.fn(),
    deleteUser: vi.fn(),
    updateUserRole: vi.fn(),
    deleteAdminBookmark: vi.fn(),
  };
});

// ── Fixtures ──────────────────────────────────────────────────────────────────

const MINIMAL_DASHBOARD: AdminDashboard = {
  total_users: 0, total_papers: 0, total_bookmarks: 0,
  recent_review_sessions: 0, kg_nodes: 0, kg_edges: 0,
  papers_by_source: [], papers_by_year: [],
  collection_queries: [], top_categories: [], recent_papers: [],
  metric_definitions: {
    recent_review_sessions: { population: 'volatile_deep_review_jobs', ttl_hours: 24, durable: false },
    collection_queries: { population: 'stored_papers_with_search_query', unit: 'papers', is_search_frequency: false },
    paper_catalog: { source: 'raw_papers_json', relationship_to_users: 'none' },
  },
};

// Papers as the backend lists them: `index` is the row's position in the
// unfiltered corpus (so a member folder's rows are not 0,1,2…) and
// `fingerprint` is the identity token the delete call has to echo back.
const papersPage = (papers: AdminPaper[]) => ({
  papers,
  total: papers.length,
  page: 1,
  page_size: 50,
  total_pages: 1,
  usernames: ['alice', 'bob'],
});

const paper = (index: number, title: string, searched_by: string): AdminPaper => ({
  index,
  fingerprint: `fp-${title}`,
  title,
  authors: [],
  source: 'arxiv',
  published_date: '',
  search_query: '',
  searched_by,
});

// ── Lifecycle ─────────────────────────────────────────────────────────────────

beforeEach(() => {
  // jsdom in this project receives --localstorage-file without a valid path,
  // which produces a broken localStorage object.  Stub with a plain in-memory
  // implementation so AdminPage's `localStorage.getItem('username')` works.
  const store: Record<string, string> = { username: 'alice' };
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, val: string) => { store[key] = val; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { Object.keys(store).forEach((k) => delete store[k]); },
  });

  vi.mocked(getAdminDashboard).mockResolvedValue(MINIMAL_DASHBOARD);
  vi.mocked(getAdminUsers).mockResolvedValue({ users: [] });
  vi.mocked(getAdminBookmarks).mockResolvedValue({ bookmarks: [] });
  vi.mocked(getAdminCurricula).mockResolvedValue({ total_user_curricula: 0, total_users_with_curricula: 0, users: [] });
  vi.mocked(getAdminPaperStats).mockResolvedValue({ total: 0, users: [] });
  vi.mocked(deleteUser).mockResolvedValue({ success: true, partial_failures: [] });
  vi.mocked(getAdminPapers).mockResolvedValue(papersPage([]));
  vi.mocked(deleteAdminPapers).mockResolvedValue({ success: true, deleted_count: 1 });
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderPage() {
  return render(
    <MemoryRouter>
      <AdminPage />
    </MemoryRouter>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('AdminPage — Members tab wiring', () => {
  it('shows the dashboard, visitor, MCP usage, and consolidated member tabs', () => {
    renderPage();

    expect(screen.getByRole('button', { name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Visitors' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'MCP Usage' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Members' })).toBeInTheDocument();

    expect(screen.queryByRole('button', { name: 'Users' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Bookmarks' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Curricula' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Papers' })).not.toBeInTheDocument();
  });

  it('calls getAdminUsers, getAdminBookmarks, getAdminCurricula, and getAdminPaperStats in parallel when Members tab is clicked', async () => {
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Members' }));
    await screen.findByTestId('members-report');

    expect(getAdminUsers).toHaveBeenCalledTimes(1);
    expect(getAdminBookmarks).toHaveBeenCalledTimes(1);
    expect(getAdminCurricula).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(getAdminPaperStats).toHaveBeenCalledTimes(1));
  });

  it('opens the MCP usage report without loading member data', async () => {
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'MCP Usage' }));
    expect(await screen.findByTestId('mcp-report')).toBeInTheDocument();
    expect(getAdminUsers).not.toHaveBeenCalled();
    expect(getAdminBookmarks).not.toHaveBeenCalled();
    expect(getAdminCurricula).not.toHaveBeenCalled();
    expect(getAdminPaperStats).not.toHaveBeenCalled();
  });

  it('re-fetches users, bookmarks, curricula, AND paper stats after user deletion (regression: stale orphan row bug)', async () => {
    // Background: deleteUser cascade removes the user's bookmarks on the backend.
    // If the frontend only re-fetches getAdminUsers, the deleted user's bookmarks
    // remain in local state and that user reappears as a "bookmark-only orphan row"
    // with a Delete button — which is confusing and wrong.
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Members' }));
    await screen.findByTestId('members-report');

    // Capture baseline call counts after initial Members load (1 each)
    const userCallsBefore = vi.mocked(getAdminUsers).mock.calls.length;
    const bmCallsBefore = vi.mocked(getAdminBookmarks).mock.calls.length;
    const curCallsBefore = vi.mocked(getAdminCurricula).mock.calls.length;
    const paperCallsBefore = vi.mocked(getAdminPaperStats).mock.calls.length;

    // Trigger the delete flow via the stub button in the mocked MembersReport
    fireEvent.click(screen.getByRole('button', { name: 'trigger-delete-bob' }));

    // The confirm dialog should appear
    expect(screen.getByText('Delete User')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => {
      expect(deleteUser).toHaveBeenCalledWith('bob');
      // All four sources must be re-fetched — not just users
      expect(vi.mocked(getAdminUsers).mock.calls.length).toBeGreaterThan(userCallsBefore);
      expect(vi.mocked(getAdminBookmarks).mock.calls.length).toBeGreaterThan(bmCallsBefore);
      expect(vi.mocked(getAdminCurricula).mock.calls.length).toBeGreaterThan(curCallsBefore);
      expect(vi.mocked(getAdminPaperStats).mock.calls.length).toBeGreaterThan(paperCallsBefore);
    });
  });
});

describe('AdminPage — paper deletion safety', () => {
  async function openFolder(member: 'alice' | 'bob', rows: AdminPaper[]) {
    vi.mocked(getAdminPapers).mockResolvedValue(papersPage(rows));
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Members' }));
    await screen.findByTestId('members-report');
    fireEvent.click(screen.getByRole('button', { name: `expand-${member}` }));
    await screen.findByRole('button', { name: `select-${rows[0].title}` });
  }

  it('deletes by index AND fingerprint, so a stale row cannot remove a neighbour', async () => {
    // bob's papers sit at global positions 1 and 4 — the listing does not
    // renumber them, and the delete call must carry them through untouched.
    const rows = [paper(1, 'BOB-0', 'bob'), paper(4, 'BOB-2', 'bob')];
    await openFolder('bob', rows);

    fireEvent.click(screen.getByRole('button', { name: 'select-BOB-0' }));
    fireEvent.click(screen.getByRole('button', { name: 'delete-selected' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() =>
      expect(deleteAdminPapers).toHaveBeenCalledWith([{ index: 1, fingerprint: 'fp-BOB-0' }]),
    );
  });

  it('surfaces a 409 instead of silently reporting success, and reloads the folder', async () => {
    const rows = [paper(1, 'BOB-0', 'bob')];
    await openFolder('bob', rows);
    vi.mocked(deleteAdminPapers).mockRejectedValue({
      response: { status: 409, data: { detail: 'Paper list changed since it was loaded' } },
    });
    const loadsBefore = vi.mocked(getAdminPapers).mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: 'select-BOB-0' }));
    fireEvent.click(screen.getByRole('button', { name: 'delete-selected' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(await screen.findByText(/아무것도 삭제하지 않았습니다/)).toBeInTheDocument();
    expect(vi.mocked(getAdminPapers).mock.calls.length).toBeGreaterThan(loadsBefore);
  });

  it('drops the previous selection immediately when switching straight to another member', async () => {
    const aliceRows = [paper(0, 'ALICE-0', 'alice')];
    await openFolder('alice', aliceRows);
    fireEvent.click(screen.getByRole('button', { name: 'select-ALICE-0' }));
    expect(screen.getByTestId('selected-count')).toHaveTextContent('1');

    // Switching members must not leave the old row indices selected while the
    // new folder loads — that selection would delete by someone else's index.
    let resolveLoad: (v: ReturnType<typeof papersPage>) => void = () => {};
    vi.mocked(getAdminPapers).mockReturnValue(
      new Promise((resolve) => {
        resolveLoad = resolve;
      }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'expand-alice' }));

    expect(screen.getByTestId('selected-count')).toHaveTextContent('0');
    // The real AdminMembersReport renders its bulk bar only inside the loaded
    // branch, so folderLoading here means no "Delete Selected" over B's folder.
    expect(screen.getByTestId('folder-loading')).toHaveTextContent('true');
    resolveLoad(papersPage([]));
    await waitFor(() => expect(screen.getByTestId('selected-count')).toHaveTextContent('0'));
  });
});
