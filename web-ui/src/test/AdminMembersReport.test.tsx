import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import AdminMembersReport from '../components/AdminMembersReport';
import type { AdminUser, AdminBookmark, AdminCurriculaResponse } from '../api/client';

// ── Fixtures ─────────────────────────────────────────────────────────────────

const SELF: AdminUser = {
  username: 'alice', role: 'admin', created_at: '2025-01-01T00:00:00Z', bookmark_count: 0,
};
const OTHER: AdminUser = {
  username: 'bob', role: 'user', created_at: '2025-03-15T00:00:00Z', bookmark_count: 2,
};

// Three users in the union: alice (account only), bob (account + bookmarks + curriculum),
// orphan (bookmark only — simulates a deleted account with leftover records).
const BOOKMARKS: AdminBookmark[] = [
  {
    id: 'bm-1', title: 'ML Papers', username: 'bob',
    query: 'machine learning', topic: 'ML', num_papers: 2,
    papers: [
      { title: 'Paper One', authors: ['Author A'] },
      { title: 'Paper Two', authors: ['Author B', 'Author C'] },
    ],
    created_at: '2025-04-01T00:00:00Z',
  },
  {
    id: 'bm-empty', title: 'Empty Bookmark', username: 'bob',
    query: '', topic: 'Empty', num_papers: 0, papers: [],
    created_at: '2025-05-01T00:00:00Z',
  },
  {
    id: 'bm-orphan', title: 'Orphan Bookmark', username: 'orphan',
    query: '', topic: 'DL', num_papers: 0, papers: [],
    created_at: '2025-05-15T00:00:00Z',
  },
];

const CURRICULA: AdminCurriculaResponse = {
  total_user_curricula: 1,
  total_users_with_curricula: 1,
  users: [{
    username: 'bob',
    curricula: [{
      id: 'cur-1', name: 'Deep Learning Basics', difficulty: 'beginner',
      total_papers: 5, total_modules: 3, is_preset: false,
      forked_from: 'preset-dl', type: 'fork',
    }],
    total_curricula: 1, fork_count: 1, custom_count: 0,
    total_read_papers: 3, courses_with_progress: 1,
  }],
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderReport(overrides: Partial<Parameters<typeof AdminMembersReport>[0]> = {}) {
  return render(<AdminMembersReport
    users={[SELF, OTHER]}
    bookmarks={BOOKMARKS}
    curricula={CURRICULA}
    loading={false}
    currentUsername="alice"
    onToggleRole={() => {}}
    onDeleteUser={() => {}}
    onDeleteBookmark={() => {}}
    {...overrides}
  />);
}

// Find the .admin-tree-folder-row element that contains the given username folder.
function getFolderRow(username: string): HTMLElement {
  const el = screen.getAllByText(username)
    .find(n => n.classList.contains('admin-tree-folder-name'));
  if (!el) throw new Error(`No folder row found for "${username}"`);
  return el.closest('.admin-tree-folder-row') as HTMLElement;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('AdminMembersReport', () => {
  it('renders report heading, 3 insight cards with ko-KR numbers, and 6 stat tiles', () => {
    renderReport();

    expect(screen.getByRole('heading', { name: '회원 통합 관리' })).toBeInTheDocument();
    // 2 users (alice + bob), 1 admin; 3 bookmarks (bm-1 + bm-empty + bm-orphan), 2 papers;
    // 1 curriculum, 3 read
    expect(screen.getByText('2명 등록 · 1명 관리자')).toBeInTheDocument();
    expect(screen.getByText('3개 북마크 · 2편 논문')).toBeInTheDocument();
    expect(screen.getByText('1개 커리큘럼 · 3편 읽음')).toBeInTheDocument();

    for (const label of ['사용자', '관리자', '북마크', '저장 논문', '커리큘럼', '읽은 논문']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('shows top bookmarker and top learner in context strip', () => {
    renderReport();

    expect(screen.getByText('최다 북마크 보유자')).toBeInTheDocument();
    expect(screen.getByText('최다 커리큘럼 보유자')).toBeInTheDocument();
    // bob has 2 bookmarks (most) and the only curriculum
    const strip = document.querySelector('.dashboard-context-strip') as HTMLElement;
    // Both strong elements inside the strip should say 'bob'
    expect(within(strip).getAllByText('bob')).toHaveLength(2);
  });

  it('renders role badge and activity badges on user folder rows', () => {
    renderReport();

    const aliceRow = getFolderRow('alice');
    expect(within(aliceRow).getByText('admin')).toBeInTheDocument();

    const bobRow = getFolderRow('bob');
    expect(within(bobRow).getByText('user')).toBeInTheDocument();
    expect(within(bobRow).getByText('북마크 2')).toBeInTheDocument();
    expect(within(bobRow).getByText('커리큘럼 1')).toBeInTheDocument();
    expect(within(bobRow).getByText('읽음 3')).toBeInTheDocument();
  });

  it('disables Promote and Delete for current user (alice), enables them for bob', () => {
    renderReport();

    const aliceRow = getFolderRow('alice');
    // alice is admin, so the role-toggle button reads "Demote"
    expect(within(aliceRow).getByRole('button', { name: 'Demote' })).toBeDisabled();
    expect(within(aliceRow).getByRole('button', { name: 'Delete' })).toBeDisabled();

    const bobRow = getFolderRow('bob');
    expect(within(bobRow).getByRole('button', { name: 'Promote' })).not.toBeDisabled();
    expect(within(bobRow).getByRole('button', { name: 'Delete' })).not.toBeDisabled();
  });

  it('calls onToggleRole(username, role) when Promote is clicked on another user', () => {
    const onToggleRole = vi.fn();
    renderReport({ onToggleRole });

    fireEvent.click(within(getFolderRow('bob')).getByRole('button', { name: 'Promote' }));

    expect(onToggleRole).toHaveBeenCalledWith('bob', 'user');
  });

  it('calls onDeleteUser(username) when Delete is clicked on a user folder row', () => {
    const onDeleteUser = vi.fn();
    renderReport({ onDeleteUser });

    fireEvent.click(within(getFolderRow('bob')).getByRole('button', { name: 'Delete' }));

    expect(onDeleteUser).toHaveBeenCalledWith('bob');
  });

  it('does not open user folder when Delete button is clicked (stopPropagation guard)', () => {
    renderReport();

    fireEvent.click(within(getFolderRow('bob')).getByRole('button', { name: 'Delete' }));

    // The folder must stay closed — bob's bookmark titles must not appear in the DOM
    expect(screen.queryByText('ML Papers')).not.toBeInTheDocument();
  });

  it('renders no Promote or Delete buttons for orphan row (account is null)', () => {
    renderReport();

    const orphanRow = getFolderRow('orphan');
    expect(within(orphanRow).queryByRole('button', { name: 'Promote' })).not.toBeInTheDocument();
    expect(within(orphanRow).queryByRole('button', { name: 'Demote' })).not.toBeInTheDocument();
    expect(within(orphanRow).queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  });

  it('shows Account, Bookmarks, Curricula sections with metadata when bob is expanded', () => {
    renderReport();
    fireEvent.click(getFolderRow('bob'));

    expect(screen.getByText('Account')).toBeInTheDocument();
    expect(screen.getByText('Bookmarks')).toBeInTheDocument();
    expect(screen.getByText('Curricula')).toBeInTheDocument();

    // Curriculum entry: name, type badge, fork source, modules, papers, difficulty
    expect(screen.getByText('Deep Learning Basics')).toBeInTheDocument();
    expect(screen.getByText('fork')).toBeInTheDocument();
    expect(document.body).toHaveTextContent('from preset-dl');
    expect(document.body).toHaveTextContent('3 modules');
    expect(document.body).toHaveTextContent('5 papers');
    expect(document.body).toHaveTextContent('beginner');

    // Reading Progress summary
    expect(screen.getByText('Reading Progress')).toBeInTheDocument();
    expect(document.body).toHaveTextContent('3 papers read across 1 course');
  });

  it('shows "삭제된 계정의 잔여 기록" in Account section for orphan (no account)', () => {
    renderReport();
    fireEvent.click(getFolderRow('orphan'));

    expect(screen.getByText('삭제된 계정의 잔여 기록')).toBeInTheDocument();
  });

  it('shows paper titles when bookmark mini-toggle is clicked', () => {
    renderReport();
    fireEvent.click(getFolderRow('bob'));

    // ML Papers has 2 papers — mini expand button must exist
    const expandBtn = document.querySelector('.admin-tree-expand-mini') as HTMLElement;
    expect(expandBtn).toBeInTheDocument();
    fireEvent.click(expandBtn);

    expect(screen.getByText('Paper One')).toBeInTheDocument();
    expect(screen.getByText('Paper Two')).toBeInTheDocument();
  });

  it('renders no mini-toggle button for a zero-paper bookmark', () => {
    renderReport();
    fireEvent.click(getFolderRow('bob'));

    // Only ML Papers (2 papers) gets the expand button; Empty Bookmark (0 papers) does not
    expect(document.querySelectorAll('.admin-tree-expand-mini')).toHaveLength(1);
  });

  it('calls onDeleteBookmark(id, title) when bookmark Delete is clicked', () => {
    const onDeleteBookmark = vi.fn();
    renderReport({ onDeleteBookmark });
    fireEvent.click(getFolderRow('bob'));

    const mlSection = screen.getByText('ML Papers').closest('.admin-tree-file') as HTMLElement;
    fireEvent.click(within(mlSection).getByRole('button', { name: 'Delete' }));

    expect(onDeleteBookmark).toHaveBeenCalledWith('bm-1', 'ML Papers');
  });

  it('shows empty bookmark hint when the expanded user has no bookmarks (alice)', () => {
    renderReport();
    fireEvent.click(getFolderRow('alice'));

    expect(screen.getByText('저장한 북마크가 없습니다.')).toBeInTheDocument();
  });

  it('shows empty curricula hint when the expanded user has no curricula (alice)', () => {
    renderReport();
    fireEvent.click(getFolderRow('alice'));

    expect(screen.getByText('보유한 커리큘럼이 없습니다 (프리셋 진도만 있을 수 있음).')).toBeInTheDocument();
  });

  it('shows loading text when loading prop is true', () => {
    render(<AdminMembersReport
      users={[SELF]} bookmarks={[]} curricula={null} loading={true}
      currentUsername="alice"
      onToggleRole={() => {}} onDeleteUser={() => {}} onDeleteBookmark={() => {}}
    />);

    expect(screen.getByText('Loading members...')).toBeInTheDocument();
  });

  it('shows empty state when there are no members at all', () => {
    render(<AdminMembersReport
      users={[]} bookmarks={[]} curricula={null} loading={false}
      currentUsername="alice"
      onToggleRole={() => {}} onDeleteUser={() => {}} onDeleteBookmark={() => {}}
    />);

    expect(screen.getByText('회원 데이터가 없습니다.')).toBeInTheDocument();
  });
});
