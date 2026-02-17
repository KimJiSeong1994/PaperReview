import { useState, useEffect, useCallback, useMemo, lazy, Suspense } from 'react';
import { useNavigate } from 'react-router-dom';
import './AdminPage.css';

const Plot = lazy(() => import('react-plotly.js'));
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
} from '../api/client';
import type { AdminDashboard, AdminUser, AdminPaper, AdminBookmark, AdminPaperUserStats } from '../api/client';

type Tab = 'dashboard' | 'users' | 'papers' | 'bookmarks';

/* ── Folder icon SVGs (matching MyPage style) ─────────────────────── */

function FolderIcon({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" className="admin-tree-folder-icon">
      {open ? (
        <>
          <path d="M5 19a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v1" fill="rgba(99,102,241,0.15)" stroke="#818cf8" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M5 19h14a2 2 0 0 0 2-2l-3-7H4l-1 7a2 2 0 0 0 2 2z" fill="rgba(99,102,241,0.25)" stroke="#818cf8" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </>
      ) : (
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" fill="rgba(156,163,175,0.1)" stroke="#6b7280" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      )}
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" className="admin-tree-chevron">
      <path d="M6 4l4 4-4 4" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" className="admin-tree-file-icon">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" fill="rgba(156,163,175,0.08)" stroke="#6b7280" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="14 2 14 8 20 8" stroke="#6b7280" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function BookmarkIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" className="admin-tree-file-icon">
      <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" fill="rgba(251,191,36,0.1)" stroke="#fbbf24" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function AdminPage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');

  // Dashboard
  const [stats, setStats] = useState<AdminDashboard | null>(null);

  // Users
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [expandedUser, setExpandedUser] = useState<string | null>(null);
  const [userBookmarks, setUserBookmarks] = useState<AdminBookmark[]>([]);
  const [userBookmarksLoading, setUserBookmarksLoading] = useState(false);

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

  // Bookmarks – tree view
  const [bookmarks, setBookmarks] = useState<AdminBookmark[]>([]);
  const [bookmarksLoading, setBookmarksLoading] = useState(false);
  const [openBookmarkFolder, setOpenBookmarkFolder] = useState<string | null>(null);
  const [expandedBookmark, setExpandedBookmark] = useState<string | null>(null);

  // Confirm dialog
  const [confirm, setConfirm] = useState<{
    title: string;
    message: string;
    onConfirm: () => void;
  } | null>(null);

  const currentUsername = localStorage.getItem('username') || '';

  // ── Data loaders ─────────────────────────────────────────────────

  const loadDashboard = useCallback(async () => {
    try {
      const data = await getAdminDashboard();
      setStats(data);
    } catch {
      /* ignore */
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

  // ── Tab change → load data ───────────────────────────────────────

  useEffect(() => {
    if (activeTab === 'dashboard') loadDashboard();
    else if (activeTab === 'users') loadUsers();
    else if (activeTab === 'papers') loadPaperStats();
    else if (activeTab === 'bookmarks') loadBookmarks();
  }, [activeTab, loadDashboard, loadUsers, loadPaperStats, loadBookmarks]);

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

  // ── User expand → load bookmarks ────────────────────────────────

  const handleExpandUser = async (username: string) => {
    if (expandedUser === username) {
      setExpandedUser(null);
      return;
    }
    setExpandedUser(username);
    setUserBookmarksLoading(true);
    try {
      const data = await getAdminBookmarks(username);
      setUserBookmarks(data.bookmarks);
    } catch {
      setUserBookmarks([]);
    } finally {
      setUserBookmarksLoading(false);
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
      message: `Are you sure you want to delete "${username}"? All their bookmarks will also be deleted.`,
      onConfirm: async () => {
        setConfirm(null);
        try {
          await deleteUser(username);
          setUsers((prev) => prev.filter((u) => u.username !== username));
          if (expandedUser === username) setExpandedUser(null);
          loadDashboard();
        } catch {
          /* ignore */
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

  // Group bookmarks by username for tree view
  const bookmarkGroups = useMemo(() => {
    const groups: Record<string, AdminBookmark[]> = {};
    for (const bm of bookmarks) {
      const user = bm.username || '(unknown)';
      if (!groups[user]) groups[user] = [];
      groups[user].push(bm);
    }
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  }, [bookmarks]);

  // ── Render ───────────────────────────────────────────────────────

  return (
    <div className="admin">
      {/* Header */}
      <header className="admin-app-header">
        <nav className="admin-header-nav">
          <div className="admin-logo">
            <img src="/Jipyheonjeon_llama.png" alt="Jipyheonjeon" className="admin-logo-icon" />
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
          {(['dashboard', 'users', 'papers', 'bookmarks'] as Tab[]).map((tab) => (
            <button
              key={tab}
              className={`admin-tab ${activeTab === tab ? 'admin-tab--active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>

        {/* Dashboard Tab */}
        {activeTab === 'dashboard' && stats && (
          <div className="admin-dashboard">
            {/* Row 1: 6 stat cards */}
            <div className="admin-stats-grid">
              <div className="admin-stat-card">
                <p className="admin-stat-label">Users</p>
                <p className="admin-stat-value">{stats.total_users}</p>
              </div>
              <div className="admin-stat-card">
                <p className="admin-stat-label">Papers</p>
                <p className="admin-stat-value">{stats.total_papers}</p>
              </div>
              <div className="admin-stat-card">
                <p className="admin-stat-label">Bookmarks</p>
                <p className="admin-stat-value">{stats.total_bookmarks}</p>
              </div>
              <div className="admin-stat-card">
                <p className="admin-stat-label">Sessions</p>
                <p className="admin-stat-value">{stats.total_sessions}</p>
              </div>
              <div className="admin-stat-card">
                <p className="admin-stat-label">KG Nodes</p>
                <p className="admin-stat-value">{stats.kg_nodes.toLocaleString()}</p>
              </div>
              <div className="admin-stat-card">
                <p className="admin-stat-label">KG Edges</p>
                <p className="admin-stat-value">{stats.kg_edges.toLocaleString()}</p>
              </div>
            </div>

            {/* Row 2: Charts */}
            <div className="admin-charts-row">
              {/* Donut: Papers by Source */}
              <div className="admin-chart-card">
                <h4 className="admin-chart-title">Papers by Source</h4>
                {stats.papers_by_source.length > 0 && (
                  <Suspense fallback={<div className="admin-loading">Loading chart...</div>}>
                    <Plot
                      data={[{
                        type: 'pie',
                        hole: 0.55,
                        labels: stats.papers_by_source.map(s => s.source),
                        values: stats.papers_by_source.map(s => s.count),
                        marker: { colors: ['#6366f1', '#818cf8', '#a5b4fc', '#c7d2fe', '#e0e7ff'] },
                        textinfo: 'label+percent',
                        textfont: { color: '#d1d5db', size: 12, family: 'inherit' },
                        hoverinfo: 'label+value+percent',
                      }]}
                      layout={{
                        paper_bgcolor: 'transparent',
                        plot_bgcolor: 'transparent',
                        margin: { t: 10, b: 10, l: 10, r: 10 },
                        showlegend: false,
                        height: 260,
                        font: { color: '#9ca3af' },
                      }}
                      config={{ displayModeBar: false, responsive: true }}
                      style={{ width: '100%' }}
                    />
                  </Suspense>
                )}
              </div>

              {/* Bar: Papers by Year */}
              <div className="admin-chart-card">
                <h4 className="admin-chart-title">Papers by Year</h4>
                {stats.papers_by_year.length > 0 && (
                  <Suspense fallback={<div className="admin-loading">Loading chart...</div>}>
                    <Plot
                      data={[{
                        type: 'bar',
                        x: stats.papers_by_year.map(y => y.year),
                        y: stats.papers_by_year.map(y => y.count),
                        marker: {
                          color: stats.papers_by_year.map((_, i, arr) =>
                            `rgba(99, 102, 241, ${0.4 + 0.6 * (i / Math.max(arr.length - 1, 1))})`
                          ),
                          line: { width: 0 },
                        },
                        hoverinfo: 'x+y',
                      }]}
                      layout={{
                        paper_bgcolor: 'transparent',
                        plot_bgcolor: 'transparent',
                        margin: { t: 10, b: 40, l: 40, r: 10 },
                        height: 260,
                        font: { color: '#9ca3af', size: 11 },
                        xaxis: {
                          gridcolor: 'rgba(255,255,255,0.04)',
                          tickangle: -45,
                          color: '#6b7280',
                        },
                        yaxis: {
                          gridcolor: 'rgba(255,255,255,0.06)',
                          color: '#6b7280',
                        },
                        bargap: 0.3,
                      }}
                      config={{ displayModeBar: false, responsive: true }}
                      style={{ width: '100%' }}
                    />
                  </Suspense>
                )}
              </div>
            </div>

            {/* Row 3: Ranking Lists */}
            <div className="admin-charts-row">
              {/* Top Search Queries */}
              <div className="admin-list-card">
                <h4 className="admin-chart-title">Top Search Queries</h4>
                {stats.top_queries.length > 0 ? (
                  <div className="admin-rank-list">
                    {stats.top_queries.map((q, i) => {
                      const maxCount = stats.top_queries[0].count;
                      return (
                        <div key={i} className="admin-rank-item">
                          <span className="admin-rank-num">{i + 1}</span>
                          <div className="admin-rank-bar-wrap">
                            <div
                              className="admin-rank-bar"
                              style={{ width: `${(q.count / maxCount) * 100}%` }}
                            />
                            <span className="admin-rank-label">{q.query}</span>
                          </div>
                          <span className="admin-rank-value">{q.count}</span>
                        </div>
                      );
                    })}
                  </div>
                ) : <div className="admin-empty">No data</div>}
              </div>

              {/* Top Categories */}
              <div className="admin-list-card">
                <h4 className="admin-chart-title">Top Categories</h4>
                {stats.top_categories.length > 0 ? (
                  <div className="admin-rank-list">
                    {stats.top_categories.map((c, i) => {
                      const maxCount = stats.top_categories[0].count;
                      return (
                        <div key={i} className="admin-rank-item">
                          <span className="admin-rank-num">{i + 1}</span>
                          <div className="admin-rank-bar-wrap">
                            <div
                              className="admin-rank-bar admin-rank-bar--cat"
                              style={{ width: `${(c.count / maxCount) * 100}%` }}
                            />
                            <span className="admin-rank-label">{c.category}</span>
                          </div>
                          <span className="admin-rank-value">{c.count}</span>
                        </div>
                      );
                    })}
                  </div>
                ) : <div className="admin-empty">No data</div>}
              </div>
            </div>

            {/* Row 4: Recent Papers */}
            <div className="admin-recent-card">
              <h4 className="admin-chart-title">Recent Papers</h4>
              {stats.recent_papers.length > 0 ? (
                <div className="admin-recent-list">
                  {stats.recent_papers.map((p, i) => (
                    <div key={i} className="admin-recent-row">
                      <span className="admin-recent-source">{p.source}</span>
                      <span className="admin-recent-title">{p.title}</span>
                      <span className="admin-recent-date">
                        {p.collected_at ? new Date(p.collected_at).toLocaleDateString() : '-'}
                      </span>
                    </div>
                  ))}
                </div>
              ) : <div className="admin-empty">No recent papers</div>}
            </div>
          </div>
        )}

        {/* Users Tab */}
        {activeTab === 'users' && (
          <div className="admin-table-container">
            {usersLoading ? (
              <div className="admin-loading">Loading users...</div>
            ) : (
              <table className="admin-table">
                <thead>
                  <tr>
                    <th style={{ width: 30 }}></th>
                    <th>Username</th>
                    <th>Role</th>
                    <th>Created</th>
                    <th>Bookmarks</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <>
                      <tr key={u.username} className={expandedUser === u.username ? 'admin-row-expanded' : ''}>
                        <td>
                          <button
                            className={`admin-expand-btn ${expandedUser === u.username ? 'admin-expand-btn--open' : ''}`}
                            onClick={() => handleExpandUser(u.username)}
                            title="View bookmarks & papers"
                          >
                            <svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor">
                              <path d="M6 4l4 4-4 4" />
                            </svg>
                          </button>
                        </td>
                        <td>
                          <span
                            className="admin-username-link"
                            onClick={() => handleExpandUser(u.username)}
                          >
                            {u.username}
                          </span>
                        </td>
                        <td>
                          <span className={`admin-role-badge admin-role-badge--${u.role}`}>
                            {u.role}
                          </span>
                        </td>
                        <td>{u.created_at ? new Date(u.created_at).toLocaleDateString() : '-'}</td>
                        <td>{u.bookmark_count}</td>
                        <td>
                          <button
                            className="admin-action-btn"
                            onClick={(e) => { e.stopPropagation(); handleToggleRole(u.username, u.role); }}
                            disabled={u.username === currentUsername}
                          >
                            {u.role === 'admin' ? 'Demote' : 'Promote'}
                          </button>
                          <button
                            className="admin-action-btn admin-action-btn--danger"
                            onClick={(e) => { e.stopPropagation(); handleDeleteUser(u.username); }}
                            disabled={u.username === currentUsername}
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                      {expandedUser === u.username && (
                        <tr key={`${u.username}-detail`} className="admin-detail-row">
                          <td colSpan={6}>
                            <div className="admin-user-detail">
                              <h4 className="admin-detail-title">
                                {u.username}'s Bookmarks & Papers
                              </h4>
                              {userBookmarksLoading ? (
                                <div className="admin-detail-loading">Loading...</div>
                              ) : userBookmarks.length === 0 ? (
                                <div className="admin-detail-empty">No bookmarks</div>
                              ) : (
                                <div className="admin-detail-bookmarks">
                                  {userBookmarks.map((bm) => (
                                    <div key={bm.id} className="admin-detail-bookmark">
                                      <div className="admin-detail-bookmark-header">
                                        <div className="admin-detail-bookmark-info">
                                          <span className="admin-detail-bookmark-title">{bm.title}</span>
                                          <span className="admin-detail-bookmark-meta">
                                            {bm.topic} &middot; {bm.num_papers} papers
                                            {bm.query && <> &middot; Query: "{bm.query}"</>}
                                          </span>
                                        </div>
                                        <span className="admin-detail-bookmark-date">
                                          {bm.created_at ? new Date(bm.created_at).toLocaleDateString() : ''}
                                        </span>
                                      </div>
                                      {bm.papers.length > 0 && (
                                        <div className="admin-detail-papers">
                                          {bm.papers.map((p, idx) => (
                                            <div key={idx} className="admin-detail-paper-item">
                                              <span className="admin-detail-paper-idx">{idx + 1}.</span>
                                              <span className="admin-detail-paper-title">{p.title}</span>
                                              {p.authors.length > 0 && (
                                                <span className="admin-detail-paper-authors">
                                                  — {p.authors.slice(0, 3).join(', ')}{p.authors.length > 3 ? ' et al.' : ''}
                                                </span>
                                              )}
                                            </div>
                                          ))}
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                  {users.length === 0 && (
                    <tr>
                      <td colSpan={6} className="admin-empty">No users found</td>
                    </tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
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

        {/* Bookmarks Tab — Tree View */}
        {activeTab === 'bookmarks' && (
          <div className="admin-tree-wrapper">
            {/* Tree header */}
            <div className="admin-tree-header">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#6b7280" strokeWidth="1.5">
                <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
              </svg>
              <span className="admin-tree-header-title">Bookmarks</span>
              <span className="admin-tree-header-count">{bookmarks.length} total</span>
            </div>

            {bookmarksLoading ? (
              <div className="admin-loading">Loading...</div>
            ) : bookmarkGroups.length > 0 ? (
              <div className="admin-tree">
                {bookmarkGroups.map(([username, userBookmarksList], idx) => {
                  const isOpen = openBookmarkFolder === username;
                  const isLast = idx === bookmarkGroups.length - 1;
                  return (
                    <div key={username} className={`admin-tree-folder ${isLast ? 'last' : ''}`}>
                      {/* User folder row */}
                      <div
                        className={`admin-tree-folder-row ${isOpen ? 'open' : ''}`}
                        onClick={() => {
                          setOpenBookmarkFolder(isOpen ? null : username);
                          setExpandedBookmark(null);
                        }}
                      >
                        <ChevronIcon />
                        <FolderIcon open={isOpen} />
                        <span className="admin-tree-folder-name">{username}</span>
                        <span className="admin-tree-folder-count">{userBookmarksList.length}</span>
                      </div>

                      {/* Expanded bookmarks */}
                      {isOpen && (
                        <div className="admin-tree-children">
                          {userBookmarksList.length === 0 ? (
                            <div className="admin-tree-empty-hint">No bookmarks</div>
                          ) : (
                            userBookmarksList.map((bm) => {
                              const bmExpanded = expandedBookmark === bm.id;
                              return (
                                <div key={bm.id} className="admin-tree-bookmark-node">
                                  {/* Bookmark item */}
                                  <div className={`admin-tree-file ${bmExpanded ? 'admin-tree-file--open' : ''}`}>
                                    <div className="admin-tree-guide-line" />
                                    {bm.papers.length > 0 ? (
                                      <button
                                        className={`admin-tree-expand-mini ${bmExpanded ? 'open' : ''}`}
                                        onClick={(e) => { e.stopPropagation(); setExpandedBookmark(bmExpanded ? null : bm.id); }}
                                      >
                                        <ChevronIcon />
                                      </button>
                                    ) : (
                                      <span style={{ width: 16, flexShrink: 0 }} />
                                    )}
                                    <BookmarkIcon />
                                    <div className="admin-tree-file-info" style={{ flex: 1 }}>
                                      <span className="admin-tree-file-title">{bm.title}</span>
                                      <span className="admin-tree-file-meta">
                                        {bm.topic}{bm.num_papers > 0 && <> &middot; {bm.num_papers} papers</>}
                                        {bm.query && <> &middot; "{bm.query}"</>}
                                        {bm.created_at && <> &middot; {new Date(bm.created_at).toLocaleDateString()}</>}
                                      </span>
                                    </div>
                                    <button
                                      className="admin-action-btn admin-action-btn--danger"
                                      style={{ flexShrink: 0, marginLeft: 8 }}
                                      onClick={(e) => { e.stopPropagation(); handleDeleteBookmark(bm.id, bm.title); }}
                                    >
                                      Delete
                                    </button>
                                  </div>

                                  {/* Expanded papers sub-tree */}
                                  {bmExpanded && bm.papers.length > 0 && (
                                    <div className="admin-tree-sub-children">
                                      {bm.papers.map((p, pIdx) => (
                                        <div key={pIdx} className="admin-tree-file admin-tree-sub-file">
                                          <div className="admin-tree-guide-line" />
                                          <FileIcon />
                                          <div className="admin-tree-file-info">
                                            <span className="admin-tree-file-title">{p.title}</span>
                                            {p.authors.length > 0 && (
                                              <span className="admin-tree-file-meta">
                                                {p.authors.slice(0, 3).join(', ')}{p.authors.length > 3 ? ' et al.' : ''}
                                              </span>
                                            )}
                                          </div>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              );
                            })
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="admin-loading">No bookmarks found</div>
            )}
          </div>
        )}
      </div>

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
