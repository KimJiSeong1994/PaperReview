import { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import { useNavigate } from 'react-router-dom';
import './AdminPage.css';
import { FolderIcon, ChevronIcon, FileIcon } from './AdminTreeIcons';

const AdminVisitsReport = lazy(() => import('./AdminVisitsReport'));
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

type Tab = 'dashboard' | 'visits' | 'members' | 'papers';

const TAB_LABELS: Record<Tab, string> = {
  dashboard: 'Dashboard',
  visits: 'Visitors',
  members: 'Members',
  papers: 'Papers',
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
    onConfirm: () => void;
  } | null>(null);

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
    else if (activeTab === 'papers') loadPaperStats();
    else if (activeTab === 'members') {
      // 통합 탭은 세 소스를 함께 그리므로 병렬로 받는다.
      loadUsers();
      loadBookmarks();
      loadCurricula();
    }
  }, [activeTab, loadDashboard, loadUsers, loadPaperStats, loadBookmarks, loadCurricula]);

  // ── Paper folder expand ──────────────────────────────────────────

  const handleToggleFolder = (username: string) => {
    if (openPaperFolder === username) {
      setOpenPaperFolder(null);
      setFolderPapers([]);
      setSelectedPapers(new Set());
    } else {
      setOpenPaperFolder(username);
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
    setConfirm({
      title: 'Delete User',
      message:
        `"${username}" 계정을 완전히 삭제합니다. 북마크, 리뷰 이벤트, ` +
        `임베딩, 프로필, 큐레이션 소유권까지 모두 제거되며 되돌릴 수 없습니다.`,
      onConfirm: async () => {
        setConfirm(null);
        try {
          const result = await deleteUser(username);
          // Refresh from backend rather than optimistically splicing so
          // partial failures don't produce a stale-but-"gone" row.
          // 통합 탭은 세 소스를 한 화면에 그리므로 북마크/커리큘럼도 함께
          // 다시 받아야 삭제된 유저의 잔여 기록이 남지 않는다.
          await Promise.all([loadUsers(), loadBookmarks(), loadCurricula()]);
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
    if (selectedPapers.size === 0) return;
    setConfirm({
      title: 'Delete Papers',
      message: `Are you sure you want to delete ${selectedPapers.size} paper(s)?`,
      onConfirm: async () => {
        setConfirm(null);
        try {
          await deleteAdminPapers(Array.from(selectedPapers));
          if (openPaperFolder) loadFolderPapers(openPaperFolder, folderPage);
          loadPaperStats();
          loadDashboard();
        } catch {
          /* ignore */
        }
      },
    });
  };

  // ── Bookmark actions ─────────────────────────────────────────────

  const handleDeleteBookmark = (bookmarkId: string, title: string) => {
    setConfirm({
      title: 'Delete Bookmark',
      message: `Are you sure you want to delete "${title}"?`,
      onConfirm: async () => {
        setConfirm(null);
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

        {/* Members Tab — 계정 · 북마크 · 커리큘럼 통합 */}
        {activeTab === 'members' && (
          <Suspense fallback={<div className="admin-loading">Loading members...</div>}>
            <AdminMembersReport
              users={users}
              bookmarks={bookmarks}
              curricula={curriculaData}
              loading={usersLoading || bookmarksLoading || curriculaLoading}
              currentUsername={currentUsername}
              onToggleRole={handleToggleRole}
              onDeleteUser={handleDeleteUser}
              onDeleteBookmark={handleDeleteBookmark}
            />
          </Suspense>
        )}

        {/* Papers Tab — Tree View */}
        {activeTab === 'papers' && (
          <div className="admin-tree-wrapper">
            {/* Tree header */}
            <div className="admin-tree-header">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#6b7280" strokeWidth="1.5">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
              </svg>
              <span className="admin-tree-header-title">Papers</span>
              <span className="admin-tree-header-count">{paperStats?.total ?? 0} total</span>
            </div>

            {paperStatsLoading ? (
              <div className="admin-loading">Loading...</div>
            ) : paperStats && paperStats.users.length > 0 ? (
              <div className="admin-tree">
                {paperStats.users.map((userStat, idx) => {
                  const isOpen = openPaperFolder === userStat.username;
                  const isLast = idx === paperStats.users.length - 1;
                  return (
                    <div key={userStat.username} className={`admin-tree-folder ${isLast ? 'last' : ''}`}>
                      {/* Folder row */}
                      <div
                        className={`admin-tree-folder-row ${isOpen ? 'open' : ''}`}
                        onClick={() => handleToggleFolder(userStat.username)}
                      >
                        <ChevronIcon />
                        <FolderIcon open={isOpen} />
                        <span className="admin-tree-folder-name">{userStat.username}</span>
                        <span className="admin-tree-folder-count">{userStat.paper_count}</span>
                      </div>

                      {/* Expanded children */}
                      {isOpen && (
                        <div className="admin-tree-children">
                          {/* Bulk bar */}
                          {selectedPapers.size > 0 && (
                            <div className="admin-bulk-bar" style={{ margin: '0 0 8px 0', borderRadius: 8 }}>
                              <span className="admin-bulk-count">{selectedPapers.size} selected</span>
                              <button className="admin-bulk-delete-btn" onClick={handleDeletePapers}>
                                Delete Selected
                              </button>
                            </div>
                          )}

                          {folderLoading ? (
                            <div className="admin-tree-empty-hint">Loading papers...</div>
                          ) : folderPapers.length === 0 ? (
                            <div className="admin-tree-empty-hint">No papers</div>
                          ) : (
                            <>
                              {/* Select all */}
                              <div className="admin-tree-select-all">
                                <input
                                  type="checkbox"
                                  className="admin-checkbox"
                                  checked={folderPapers.length > 0 && selectedPapers.size === folderPapers.length}
                                  onChange={toggleAllPapers}
                                />
                                <span className="admin-tree-select-all-label">Select all on this page</span>
                              </div>

                              {/* Paper items */}
                              {folderPapers.map((p) => (
                                <div key={p.index} className="admin-tree-file">
                                  <div className="admin-tree-guide-line" />
                                  <input
                                    type="checkbox"
                                    className="admin-checkbox"
                                    checked={selectedPapers.has(p.index)}
                                    onChange={() => togglePaperSelect(p.index)}
                                  />
                                  <FileIcon />
                                  <div className="admin-tree-file-info">
                                    <span className="admin-tree-file-title">{p.title}</span>
                                    <span className="admin-tree-file-meta">
                                      {p.authors.join(', ')}{p.source && <> &middot; {p.source}</>}{p.published_date && <> &middot; {p.published_date}</>}
                                    </span>
                                  </div>
                                </div>
                              ))}

                              {/* Pagination */}
                              {folderTotalPages > 1 && (
                                <div className="admin-pagination" style={{ padding: '10px 0' }}>
                                  <button
                                    className="admin-page-btn"
                                    disabled={folderPage <= 1}
                                    onClick={() => openPaperFolder && loadFolderPapers(openPaperFolder, folderPage - 1)}
                                  >
                                    Prev
                                  </button>
                                  <span className="admin-page-info">
                                    {folderPage} / {folderTotalPages} ({folderTotal})
                                  </span>
                                  <button
                                    className="admin-page-btn"
                                    disabled={folderPage >= folderTotalPages}
                                    onClick={() => openPaperFolder && loadFolderPapers(openPaperFolder, folderPage + 1)}
                                  >
                                    Next
                                  </button>
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="admin-loading">No papers found</div>
            )}
          </div>
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
            aria-label="Close notice"
          >
            ×
          </button>
        </div>
      )}

      {/* Confirm Dialog */}
      {confirm && (
        <div className="admin-confirm-overlay" onClick={() => setConfirm(null)}>
          <div className="admin-confirm-dialog" onClick={(e) => e.stopPropagation()}>
            <h3 className="admin-confirm-title">{confirm.title}</h3>
            <p className="admin-confirm-message">{confirm.message}</p>
            <div className="admin-confirm-actions">
              <button className="admin-confirm-cancel" onClick={() => setConfirm(null)}>
                Cancel
              </button>
              <button className="admin-confirm-delete" onClick={confirm.onConfirm}>
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
