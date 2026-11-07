import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AdminPage from '../components/AdminPage';
import {
  getAdminUsers,
  getAdminBookmarks,
  getAdminCurricula,
  getAdminPaperStats,
  getAdminPapers,
  deleteUser,
} from '../api/client';

// ── Module mocks ──────────────────────────────────────────────────────────────

// Stub lazy-loaded report components so Suspense resolves synchronously.
vi.mock('../components/AdminMembersReport', () => ({
  default: ({ onDeleteUser }: { onDeleteUser: (username: string) => void }) => (
    <div data-testid="members-report">
      <button onClick={() => onDeleteUser('bob')}>trigger-delete-bob</button>
    </div>
  ),
}));
vi.mock('../components/AdminOverviewTab', () => ({
  default: () => <div data-testid="dashboard-report" />,
}));
vi.mock('../components/AdminVisitsReport', () => ({
  default: () => <div data-testid="visits-report" />,
}));
vi.mock('../components/AdminSystemTab', () => ({
  default: () => <div data-testid="mcp-report" />,
}));

// Mock the entire api/client module, keeping non-admin exports intact.
vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    getAdminUsers: vi.fn(),
    getAdminBookmarks: vi.fn(),
    getAdminCurricula: vi.fn(),
    getAdminPaperStats: vi.fn(),
    getAdminPapers: vi.fn(),
    deleteUser: vi.fn(),
    updateUserRole: vi.fn(),
    deleteAdminBookmark: vi.fn(),
  };
});

// ── Fixtures ──────────────────────────────────────────────────────────────────

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

  vi.mocked(getAdminUsers).mockResolvedValue({ users: [] });
  vi.mocked(getAdminBookmarks).mockResolvedValue({ bookmarks: [] });
  vi.mocked(getAdminCurricula).mockResolvedValue({ total_user_curricula: 0, total_users_with_curricula: 0, users: [] });
  vi.mocked(getAdminPaperStats).mockResolvedValue({ total: 0, users: [] });
  vi.mocked(deleteUser).mockResolvedValue({ success: true, partial_failures: [] });

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
  it('shows the current admin tabs', async () => {
    renderPage();
    await screen.findByTestId('dashboard-report');

    expect(screen.getByRole('button', { name: '대시보드' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '성장' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '시스템' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '회원' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '대화' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '콘텐츠' })).toBeInTheDocument();

    expect(screen.queryByRole('button', { name: 'Users' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Bookmarks' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Curricula' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Papers' })).not.toBeInTheDocument();
  });

  it('loads accounts without requesting retired member data', async () => {
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: '회원' }));
    await screen.findByTestId('members-report');

    expect(getAdminUsers).toHaveBeenCalledTimes(1);
    expect(getAdminBookmarks).not.toHaveBeenCalled();
    expect(getAdminCurricula).not.toHaveBeenCalled();
    expect(getAdminPaperStats).not.toHaveBeenCalled();
    expect(getAdminPapers).not.toHaveBeenCalled();
  });

  it('opens the MCP usage report without loading member data', async () => {
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: '시스템' }));
    expect(await screen.findByTestId('mcp-report')).toBeInTheDocument();
    expect(getAdminUsers).not.toHaveBeenCalled();
    expect(getAdminBookmarks).not.toHaveBeenCalled();
    expect(getAdminCurricula).not.toHaveBeenCalled();
    expect(getAdminPaperStats).not.toHaveBeenCalled();
  });

  it('refreshes accounts after deletion without requesting retired data', async () => {
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: '회원' }));
    await screen.findByTestId('members-report');

    // Capture the account load before deletion.
    const userCallsBefore = vi.mocked(getAdminUsers).mock.calls.length;

    // Trigger the delete flow via the stub button in the mocked MembersReport
    fireEvent.click(screen.getByRole('button', { name: 'trigger-delete-bob' }));

    // The confirm dialog should appear
    expect(screen.getByText('계정 삭제')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '삭제' }));

    await waitFor(() => {
      expect(deleteUser).toHaveBeenCalledWith('bob');
      // Only the account list is needed by the current member view.
      expect(vi.mocked(getAdminUsers).mock.calls.length).toBeGreaterThan(userCallsBefore);
      expect(getAdminBookmarks).not.toHaveBeenCalled();
      expect(getAdminCurricula).not.toHaveBeenCalled();
      expect(getAdminPaperStats).not.toHaveBeenCalled();
    });
  });
});

describe('AdminPage — overview tab', () => {
  it('opens overview by default without fetching member records', async () => {
    renderPage();
    expect(await screen.findByTestId('dashboard-report')).toBeInTheDocument();
    expect(getAdminUsers).not.toHaveBeenCalled();
    expect(getAdminBookmarks).not.toHaveBeenCalled();
  });
});

describe('AdminPage — account deletion copy', () => {
  const BOB = {
    username: 'bob', role: 'user', created_at: '2025-03-15T00:00:00Z', bookmark_count: 0,
    conversation_count: 3, last_conversation_at: '2026-11-02T00:00:00+00:00',
    memory_count: 5, profile_updated_at: null,
  };

  it('names the conversations and memories the delete removes', async () => {
    vi.mocked(getAdminUsers).mockResolvedValue({ users: [BOB] });
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: '회원' }));
    await screen.findByTestId('members-report');
    await waitFor(() => expect(getAdminUsers).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: 'trigger-delete-bob' }));

    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent('대화 3개와 메모리 5개를 포함해 "bob" 계정을 완전히 삭제합니다.');
    expect(dialog).toHaveTextContent('대화·메모리·연구 프로필·방문 분석 이벤트, 북마크');
  });

  it('reports partial-failure stages in Korean, unknown keys verbatim', async () => {
    vi.mocked(deleteUser).mockResolvedValue({ success: false, partial_failures: ['conversations', 'souls', 'mystery_stage'] });
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: '회원' }));
    await screen.findByTestId('members-report');

    fireEvent.click(screen.getByRole('button', { name: 'trigger-delete-bob' }));
    fireEvent.click(screen.getByRole('button', { name: '삭제' }));

    expect(await screen.findByText(/일부 단계 실패: 대화, 메모리·연구 프로필, mystery_stage/)).toBeInTheDocument();
  });
});

describe('AdminPage — confirm dialog', () => {
  async function openDialog() {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: '회원' }));
    await screen.findByTestId('members-report');
    const trigger = screen.getByRole('button', { name: 'trigger-delete-bob' });
    trigger.focus();
    fireEvent.click(trigger);
    return trigger;
  }

  it('announces itself as a modal dialog labelled by its own title', async () => {
    await openDialog();

    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAccessibleName('계정 삭제');
  });

  it('moves focus into the dialog when it opens', async () => {
    await openDialog();

    expect(document.activeElement).toBe(screen.getByRole('dialog'));
  });

  it('closes on Escape and returns focus to the control that opened it', async () => {
    const trigger = await openDialog();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(deleteUser).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(trigger);
  });

  it('returns focus to the trigger after cancelling', async () => {
    const trigger = await openDialog();

    fireEvent.click(screen.getByRole('button', { name: '취소' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });
});
