import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import './AdminPage.css';
import {
  getAdminDashboard,
  getAdminUsers,
  updateUserRole,
  deleteUser,
  getAdminPapers,
  deleteAdminPapers,
  getAdminBookmarks,
  deleteAdminBookmark,
} from '../api/client';
import type { AdminDashboard, AdminUser, AdminPaper, AdminBookmark } from '../api/client';

type Tab = 'dashboard' | 'users' | 'papers' | 'bookmarks';

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

  // Papers
  const [papers, setPapers] = useState<AdminPaper[]>([]);
  const [papersPage, setPapersPage] = useState(1);
  const [papersTotalPages, setPapersTotalPages] = useState(1);
  const [papersTotal, setPapersTotal] = useState(0);
  const [papersLoading, setPapersLoading] = useState(false);
  const [selectedPapers, setSelectedPapers] = useState<Set<number>>(new Set());

  // Bookmarks
  const [bookmarks, setBookmarks] = useState<AdminBookmark[]>([]);
  const [bookmarksLoading, setBookmarksLoading] = useState(false);
  const [bookmarkUserFilter, setBookmarkUserFilter] = useState<string>('');
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

  const loadPapers = useCallback(async (page: number) => {
    setPapersLoading(true);
    try {
      const data = await getAdminPapers(page, 50);
      setPapers(data.papers);
      setPapersPage(data.page);
      setPapersTotalPages(data.total_pages);
      setPapersTotal(data.total);
      setSelectedPapers(new Set());
    } catch {
      /* ignore */
    } finally {
      setPapersLoading(false);
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
    else if (activeTab === 'papers') loadPapers(1);
    else if (activeTab === 'bookmarks') loadBookmarks();
  }, [activeTab, loadDashboard, loadUsers, loadPapers, loadBookmarks]);

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
    if (selectedPapers.size === papers.length) {
      setSelectedPapers(new Set());
    } else {
      setSelectedPapers(new Set(papers.map((p) => p.index)));
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
          loadPapers(papersPage);
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

  // Filtered bookmarks by selected user
  const filteredBookmarks = useMemo(() => {
    if (!bookmarkUserFilter) return bookmarks;
    return bookmarks.filter((b) => b.username === bookmarkUserFilter);
  }, [bookmarks, bookmarkUserFilter]);

  // Unique usernames for filter dropdown
  const bookmarkUsernames = useMemo(() => {
    const set = new Set(bookmarks.map((b) => b.username));
    return Array.from(set).sort();
  }, [bookmarks]);

  // ── Render ───────────────────────────────────────────────────────

  return (
    <div className="admin">
      {/* Header */}
      <header className="admin-app-header">
        <nav className="admin-header-nav">
          <div className="admin-logo">
            <img src="/icon.png" alt="" className="admin-logo-icon" />
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
        {activeTab === 'dashboard' && (
          <div className="admin-stats-grid">
            <div className="admin-stat-card">
              <p className="admin-stat-label">Users</p>
              <p className="admin-stat-value">{stats?.total_users ?? '-'}</p>
            </div>
            <div className="admin-stat-card">
              <p className="admin-stat-label">Papers</p>
              <p className="admin-stat-value">{stats?.total_papers ?? '-'}</p>
            </div>
            <div className="admin-stat-card">
              <p className="admin-stat-label">Bookmarks</p>
              <p className="admin-stat-value">{stats?.total_bookmarks ?? '-'}</p>
            </div>
            <div className="admin-stat-card">
              <p className="admin-stat-label">Active Sessions</p>
              <p className="admin-stat-value">{stats?.total_sessions ?? '-'}</p>
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

        {/* Papers Tab */}
        {activeTab === 'papers' && (
          <div className="admin-table-container">
            {selectedPapers.size > 0 && (
              <div className="admin-bulk-bar">
                <span className="admin-bulk-count">{selectedPapers.size} selected</span>
                <button className="admin-bulk-delete-btn" onClick={handleDeletePapers}>
                  Delete Selected
                </button>
              </div>
            )}
            {papersLoading ? (
              <div className="admin-loading">Loading papers...</div>
            ) : (
              <>
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th style={{ width: 36 }}>
                        <input
                          type="checkbox"
                          className="admin-checkbox"
                          checked={papers.length > 0 && selectedPapers.size === papers.length}
                          onChange={toggleAllPapers}
                        />
                      </th>
                      <th>Title</th>
                      <th>Authors</th>
                      <th>Source</th>
                      <th>Date</th>
                      <th>Search Query</th>
                    </tr>
                  </thead>
                  <tbody>
                    {papers.map((p) => (
                      <tr key={p.index}>
                        <td>
                          <input
                            type="checkbox"
                            className="admin-checkbox"
                            checked={selectedPapers.has(p.index)}
                            onChange={() => togglePaperSelect(p.index)}
                          />
                        </td>
                        <td style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {p.title}
                        </td>
                        <td style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {p.authors.join(', ')}
                        </td>
                        <td>{p.source}</td>
                        <td>{p.published_date || '-'}</td>
                        <td style={{ maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {p.search_query || '-'}
                        </td>
                      </tr>
                    ))}
                    {papers.length === 0 && (
                      <tr>
                        <td colSpan={6} className="admin-empty">No papers found</td>
                      </tr>
                    )}
                  </tbody>
                </table>
                {papersTotalPages > 1 && (
                  <div className="admin-pagination">
                    <button
                      className="admin-page-btn"
                      disabled={papersPage <= 1}
                      onClick={() => loadPapers(papersPage - 1)}
                    >
                      Prev
                    </button>
                    <span className="admin-page-info">
                      Page {papersPage} of {papersTotalPages} ({papersTotal} total)
                    </span>
                    <button
                      className="admin-page-btn"
                      disabled={papersPage >= papersTotalPages}
                      onClick={() => loadPapers(papersPage + 1)}
                    >
                      Next
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Bookmarks Tab */}
        {activeTab === 'bookmarks' && (
          <div className="admin-table-container">
            {/* User filter */}
            <div className="admin-filter-bar">
              <label className="admin-filter-label">Filter by user:</label>
              <select
                className="admin-filter-select"
                value={bookmarkUserFilter}
                onChange={(e) => setBookmarkUserFilter(e.target.value)}
              >
                <option value="">All Users</option>
                {bookmarkUsernames.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
              {bookmarkUserFilter && (
                <span className="admin-filter-count">
                  {filteredBookmarks.length} bookmark(s)
                </span>
              )}
            </div>
            {bookmarksLoading ? (
              <div className="admin-loading">Loading bookmarks...</div>
            ) : (
              <table className="admin-table">
                <thead>
                  <tr>
                    <th style={{ width: 30 }}></th>
                    <th>Title</th>
                    <th>User</th>
                    <th>Query</th>
                    <th>Topic</th>
                    <th>Papers</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredBookmarks.map((b) => (
                    <>
                      <tr key={b.id}>
                        <td>
                          <button
                            className={`admin-expand-btn ${expandedBookmark === b.id ? 'admin-expand-btn--open' : ''}`}
                            onClick={() => setExpandedBookmark(expandedBookmark === b.id ? null : b.id)}
                          >
                            <svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor">
                              <path d="M6 4l4 4-4 4" />
                            </svg>
                          </button>
                        </td>
                        <td style={{ maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {b.title}
                        </td>
                        <td>
                          <span
                            className="admin-username-link"
                            onClick={() => { setBookmarkUserFilter(b.username); }}
                          >
                            {b.username}
                          </span>
                        </td>
                        <td style={{ maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {b.query || '-'}
                        </td>
                        <td>{b.topic}</td>
                        <td>{b.num_papers}</td>
                        <td>{b.created_at ? new Date(b.created_at).toLocaleDateString() : '-'}</td>
                        <td>
                          <button
                            className="admin-action-btn admin-action-btn--danger"
                            onClick={() => handleDeleteBookmark(b.id, b.title)}
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                      {expandedBookmark === b.id && b.papers.length > 0 && (
                        <tr key={`${b.id}-papers`} className="admin-detail-row">
                          <td colSpan={8}>
                            <div className="admin-detail-papers">
                              {b.papers.map((p, idx) => (
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
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                  {filteredBookmarks.length === 0 && (
                    <tr>
                      <td colSpan={8} className="admin-empty">No bookmarks found</td>
                    </tr>
                  )}
                </tbody>
              </table>
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
