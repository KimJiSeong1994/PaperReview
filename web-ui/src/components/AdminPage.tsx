import { useState, useEffect, useCallback, useRef, lazy, Suspense } from 'react';
import { useNavigate } from 'react-router-dom';
import './AdminPage.css';

const AdminVisitsReport = lazy(() => import('./AdminVisitsReport'));
const AdminMcpReport = lazy(() => import('./AdminMcpReport'));
const AdminDashboardReport = lazy(() => import('./AdminDashboardReport'));
const AdminMembersReport = lazy(() => import('./AdminMembersReport'));
import {
  getAdminDashboard,
  getAdminUsers,
  updateUserRole,
  deleteUser,
  getAdminPapers,
  getAdminPaperStats,
  deleteAdminPapers,
  getAdminBookmarks,
  deleteAdminBookmark,
  getAdminCurricula,
} from '../api/client';
import type { AdminDashboard, AdminUser, AdminPaper, AdminBookmark, AdminPaperUserStats, AdminCurriculaResponse } from '../api/client';

type Tab = 'dashboard' | 'visits' | 'mcp' | 'members';

const TAB_LABELS: Record<Tab, string> = {
  dashboard: 'Dashboard',
  visits: 'Visitors',
  mcp: 'MCP Usage',
  members: 'Members',
};

export default function AdminPage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');

  // Dashboard
  const [stats, setStats] = useState<AdminDashboard | null>(null);

  // Users
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);

  // Papers – tree view
  const [paperStats, setPaperStats] = useState<AdminPaperUserStats | null>(null);
  const [paperStatsLoading, setPaperStatsLoading] = useState(false);
  const [openPaperFolder, setOpenPaperFolder] = useState<string | null>(null);
  const [folderPapers, setFolderPapers] = useState<AdminPaper[]>([]);
  const [folderPage, setFolderPage] = useState(1);
  const [folderTotalPages, setFolderTotalPages] = useState(1);
  const [folderTotal, setFolderTotal] = useState(0);
  const [folderLoading, setFolderLoading] = useState(false);
  const [selectedPapers, setSelectedPapers] = useState<Set<number>>(new Set());

  // Bookmarks
  const [bookmarks, setBookmarks] = useState<AdminBookmark[]>([]);
  const [bookmarksLoading, setBookmarksLoading] = useState(false);

  // Curricula
  const [curriculaData, setCurriculaData] = useState<AdminCurriculaResponse | null>(null);
  const [curriculaLoading, setCurriculaLoading] = useState(false);

  // Confirm dialog
  const [confirm, setConfirm] = useState<{
    title: string;
    message: string;
    onConfirm: () => void | Promise<void>;
  } | null>(null);
  // Blocks a second click landing in the same tick as the first: the repeat
  // would fire another delete with indices the first one is about to shift.
  const confirmBusy = useRef(false);
  const confirmDialogRef = useRef<HTMLDivElement>(null);
  // 다이얼로그를 연 버튼. 닫을 때 포커스를 그 자리로 돌려놔야 키보드 사용자가
  // 목록 맨 위로 튕기지 않는다.
  const confirmTriggerRef = useRef<HTMLElement | null>(null);

  const askConfirm = useCallback((next: NonNullable<typeof confirm>) => {
    confirmTriggerRef.current = document.activeElement as HTMLElement | null;
    setConfirm(next);
  }, []);

  const closeConfirm = useCallback(() => {
    setConfirm(null);
    confirmTriggerRef.current?.focus();
  }, []);

  // Escape-to-close and initial focus into the dialog, the same shape as the
  // other dialogs here (RecommendationBell.tsx, BlogPage.tsx, SearchPage.tsx).
  useEffect(() => {
    if (!confirm) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeConfirm();
    };
    document.addEventListener('keydown', handleKeyDown);
    confirmDialogRef.current?.focus();
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [confirm, closeConfirm]);

  // Transient notice (success/error feedback for admin actions).
  const [notice, setNotice] = useState<{
    kind: 'success' | 'warn' | 'error';
    text: string;
  } | null>(null);

  // Auto-dismiss the notice after 5s so it never lingers indefinitely.
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 5000);
    return () => clearTimeout(t);
  }, [notice]);

  const currentUsername = localStorage.getItem('username') || '';

  // ── Data loaders ─────────────────────────────────────────────────

  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [dashboardError, setDashboardError] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    setDashboardLoading(true);
    setDashboardError(null);
    try {
      const data = await getAdminDashboard();
      setStats(data);
    } catch (err) {
      setDashboardError(err instanceof Error ? err.message : 'Failed to load dashboard');
    } finally {
      setDashboardLoading(false);
    }
  }, []);

  const loadUsers = useCallback(async () => {
    setUsersLoading(true);
    try {
      const data = await getAdminUsers();
      setUsers(data.users);
    } catch {
      /* ignore */
    } finally {
      setUsersLoading(false);
    }
  }, []);

  const loadPaperStats = useCallback(async () => {
    setPaperStatsLoading(true);
    try {
      const data = await getAdminPaperStats();
      setPaperStats(data);
    } catch {
      /* ignore */
    } finally {
      setPaperStatsLoading(false);
    }
  }, []);

  const loadFolderPapers = useCallback(async (username: string, page: number) => {
    setFolderLoading(true);
    try {
      const data = await getAdminPapers(page, 50, username);
      setFolderPapers(data.papers);
      setFolderPage(data.page);
      setFolderTotalPages(data.total_pages);
      setFolderTotal(data.total);
      setSelectedPapers(new Set());
    } catch {
      /* ignore */
    } finally {
      setFolderLoading(false);
    }
  }, []);

  const loadBookmarks = useCallback(async () => {
    setBookmarksLoading(true);
    try {
      const data = await getAdminBookmarks();
      setBookmarks(data.bookmarks);
    } catch {
      /* ignore */
    } finally {
      setBookmarksLoading(false);
    }
  }, []);

  const loadCurricula = useCallback(async () => {
    setCurriculaLoading(true);
    try {
      const data = await getAdminCurricula();
      setCurriculaData(data);
    } catch {
      /* ignore */
    } finally {
      setCurriculaLoading(false);
    }
  }, []);

  // ── Tab change → load data ───────────────────────────────────────

  useEffect(() => {
    if (activeTab === 'dashboard') loadDashboard();
    else if (activeTab === 'members') {
      // 통합 탭은 네 소스를 함께 그리므로 병렬로 받는다.
      loadUsers();
      loadBookmarks();
      loadCurricula();
      loadPaperStats();
    }
  }, [activeTab, loadDashboard, loadUsers, loadPaperStats, loadBookmarks, loadCurricula]);

  // ── Paper folder expand ──────────────────────────────────────────

  // Members 트리의 유저 폴더가 열리면 username, 닫히면 null이 온다.
  const handleToggleFolder = (username: string | null) => {
    if (username === null) {
      setOpenPaperFolder(null);
      setFolderPapers([]);
      setSelectedPapers(new Set());
    } else {
      setOpenPaperFolder(username);
      // Clear here, not inside loadFolderPapers: that clear lands after the
      // await, so switching straight from one member to another would leave
      // the previous member's row indices selected while the new list loads.
      setSelectedPapers(new Set());
      loadFolderPapers(username, 1);
    }
  };

  // ── User actions ─────────────────────────────────────────────────

  const handleToggleRole = async (username: string, currentRole: string) => {
    const newRole = currentRole === 'admin' ? 'user' : 'admin';
    try {
      await updateUserRole(username, newRole);
      setUsers((prev) =>
        prev.map((u) => (u.username === username ? { ...u, role: newRole } : u)),
      );
    } catch {
      /* ignore */
    }
  };

  const handleDeleteUser = (username: string) => {
    askConfirm({
      title: '계정 삭제',
      message:
        `"${username}" 계정을 완전히 삭제합니다. 북마크, 리뷰 이벤트, ` +
        `임베딩, 프로필, 큐레이션 소유권까지 모두 제거되며 되돌릴 수 없습니다.`,
      onConfirm: async () => {
        closeConfirm();
        try {
          const result = await deleteUser(username);
          // Refresh from backend rather than optimistically splicing so
          // partial failures don't produce a stale-but-"gone" row.
          // 통합 탭은 네 소스를 한 화면에 그리므로 북마크/커리큘럼/논문 집계도
          // 함께 다시 받아야 삭제된 유저의 잔여 기록이 남지 않는다.
          await Promise.all([loadUsers(), loadBookmarks(), loadCurricula(), loadPaperStats()]);
          loadDashboard();

          const partials: string[] = Array.isArray(result?.partial_failures)
            ? result.partial_failures
            : [];
          if (result?.success && partials.length === 0) {
            setNotice({ kind: 'success', text: `"${username}" 삭제 완료.` });
          } else {
            setNotice({
              kind: 'warn',
              text:
                `"${username}" 일부 단계 실패: ${partials.join(', ') || '알 수 없음'}. ` +
                `계정 자체는 제거됐지만 로그를 확인하세요.`,
            });
          }
        } catch (err: unknown) {
          // Surface backend HTTPException detail (403 last-admin,
          // 400 self-delete, 429 rate-limit, etc.) instead of silently
          // swallowing — that was the original "삭제해도 반영이 안 된다"
          // symptom: admin clicked delete, backend refused, UI showed
          // nothing.
          const detail =
            (err as { response?: { data?: { detail?: string } } })?.response
              ?.data?.detail ??
            (err instanceof Error ? err.message : '삭제에 실패했습니다');
          setNotice({ kind: 'error', text: `삭제 실패: ${detail}` });
        }
      },
    });
  };

  // ── Paper actions ────────────────────────────────────────────────

  const togglePaperSelect = (idx: number) => {
    setSelectedPapers((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const toggleAllPapers = () => {
    if (selectedPapers.size === folderPapers.length) {
      setSelectedPapers(new Set());
    } else {
      setSelectedPapers(new Set(folderPapers.map((p) => p.index)));
    }
  };

  const handleDeletePapers = () => {
    // Send each row's fingerprint alongside its index: the index is only a
    // position in the corpus, so the backend verifies the record is still the
    // one that was listed and refuses (409) rather than deleting a neighbour.
    const targets = folderPapers
      .filter((p) => selectedPapers.has(p.index))
      .map((p) => ({ index: p.index, fingerprint: p.fingerprint }));
    if (targets.length === 0) return;
    askConfirm({
      title: '논문 삭제',
      message: `선택한 논문 ${targets.length}편을 삭제합니다. 되돌릴 수 없습니다.`,
      onConfirm: async () => {
        closeConfirm();
        try {
          await deleteAdminPapers(targets);
          if (openPaperFolder) loadFolderPapers(openPaperFolder, folderPage);
          loadPaperStats();
          loadDashboard();
        } catch (err: unknown) {
          // A 409 means the list moved under the admin and nothing was
          // deleted — swallowing it would look like a successful delete.
          const status = (err as { response?: { status?: number } })?.response?.status;
          if (status === 409 && openPaperFolder) loadFolderPapers(openPaperFolder, folderPage);
          const detail =
            (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            (err instanceof Error ? err.message : '삭제에 실패했습니다');
          setNotice({
            kind: status === 409 ? 'warn' : 'error',
            text:
              status === 409
                ? '목록이 바뀌어 아무것도 삭제하지 않았습니다. 새로고침된 목록에서 다시 선택하세요.'
                : `삭제 실패: ${detail}`,
          });
        }
      },
    });
  };

  // ── Bookmark actions ─────────────────────────────────────────────

  const handleDeleteBookmark = (bookmarkId: string, title: string) => {
    askConfirm({
      title: '북마크 삭제',
      message: `북마크 "${title}"을(를) 삭제합니다. 되돌릴 수 없습니다.`,
      onConfirm: async () => {
        closeConfirm();
        try {
          await deleteAdminBookmark(bookmarkId);
          setBookmarks((prev) => prev.filter((b) => b.id !== bookmarkId));
          loadDashboard();
        } catch {
          /* ignore */
        }
      },
    });
  };

  // ── Render ───────────────────────────────────────────────────────

  return (
    <div className="admin">
      {/* Header */}
      <header className="admin-app-header">
        <nav className="admin-header-nav">
          <div className="admin-logo">
            <picture>
              <source srcSet="/Jiphyeonjeon_llama.webp" type="image/webp" />
              <img src="/Jiphyeonjeon_llama.png" alt="Jiphyeonjeon" className="admin-logo-icon" width={128} height={128} loading="eager" fetchPriority="high" />
            </picture>
            <span className="admin-brand-name">Admin</span>
          </div>
          <div className="admin-header-actions">
            <button className="admin-nav-btn" onClick={() => navigate('/')}>
              Home
            </button>
            <button className="admin-nav-btn" onClick={() => navigate('/mypage')}>
              My Page
            </button>
          </div>
        </nav>
      </header>

      {/* Content */}
      <div className="admin-content">
        {/* Tabs */}
        <div className="admin-tabs">
          {(Object.keys(TAB_LABELS) as Tab[]).map((tab) => (
            <button
              key={tab}
              className={`admin-tab ${activeTab === tab ? 'admin-tab--active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {TAB_LABELS[tab]}
            </button>
          ))}
        </div>

        {/* Visits Tab */}
        {activeTab === 'visits' && (
          <Suspense fallback={<div className="admin-loading">Loading visitors...</div>}>
            <AdminVisitsReport />
          </Suspense>
        )}

        {/* MCP usage is loaded independently from browser/GA4 analytics. */}
        {activeTab === 'mcp' && (
          <Suspense fallback={<div className="admin-loading">Loading MCP usage...</div>}>
            <AdminMcpReport />
          </Suspense>
        )}

        {/* Dashboard Tab */}
        {activeTab === 'dashboard' && dashboardLoading && (
          <div className="admin-loading">Loading dashboard...</div>
        )}
        {activeTab === 'dashboard' && dashboardError && (
          <div className="admin-loading" style={{ color: 'var(--danger-strong)' }}>
            Error: {dashboardError}
          </div>
        )}
        {activeTab === 'dashboard' && stats && (
          <Suspense fallback={<div className="admin-loading">Loading dashboard report...</div>}>
            <AdminDashboardReport stats={stats} />
          </Suspense>
        )}

        {/* Members Tab — 계정 · 북마크 · 커리큘럼 · 논문 통합 */}
        {activeTab === 'members' && (
          <Suspense fallback={<div className="admin-loading">회원 정보를 불러오는 중...</div>}>
            <AdminMembersReport
              users={users}
              bookmarks={bookmarks}
              curricula={curriculaData}
              loading={usersLoading || bookmarksLoading || curriculaLoading || paperStatsLoading}
              currentUsername={currentUsername}
              onToggleRole={handleToggleRole}
              onDeleteUser={handleDeleteUser}
              onDeleteBookmark={handleDeleteBookmark}
              paperStats={paperStats}
              folderPapers={folderPapers}
              folderPage={folderPage}
              folderTotalPages={folderTotalPages}
              folderTotal={folderTotal}
              folderLoading={folderLoading}
              selectedPapers={selectedPapers}
              onExpandMember={handleToggleFolder}
              onPaperPageChange={loadFolderPapers}
              onTogglePaperSelect={togglePaperSelect}
              onToggleAllPapers={toggleAllPapers}
              onDeletePapers={handleDeletePapers}
            />
          </Suspense>
        )}

      </div>

      {/* Transient notice (success / warn / error) */}
      {notice && (
        <div
          className={`admin-notice admin-notice--${notice.kind}`}
          role={notice.kind === 'error' ? 'alert' : 'status'}
          onClick={() => setNotice(null)}
        >
          {notice.text}
          <button
            className="admin-notice-close"
            onClick={(e) => {
              e.stopPropagation();
              setNotice(null);
            }}
            aria-label="알림 닫기"
          >
            ×
          </button>
        </div>
      )}

      {/* Confirm Dialog */}
      {confirm && (
        <div className="admin-confirm-overlay" onClick={closeConfirm}>
          <div
            ref={confirmDialogRef}
            className="admin-confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-confirm-title"
            tabIndex={-1}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="admin-confirm-title" id="admin-confirm-title">{confirm.title}</h3>
            <p className="admin-confirm-message">{confirm.message}</p>
            <div className="admin-confirm-actions">
              <button className="admin-confirm-cancel" onClick={closeConfirm}>
                취소
              </button>
              <button
                className="admin-confirm-delete"
                onClick={async () => {
                  if (confirmBusy.current) return;
                  confirmBusy.current = true;
                  try {
                    await confirm.onConfirm();
                  } finally {
                    confirmBusy.current = false;
                  }
                }}
              >
                삭제
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
