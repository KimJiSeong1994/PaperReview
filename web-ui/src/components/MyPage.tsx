import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './MyPage.css';
import {
  getBookmarks, getBookmarkDetail, deleteBookmark, updateBookmarkTopic,
  bulkDeleteBookmarks, bulkMoveBookmarks,
  chatWithBookmarks, buildLightRAG, getLightRAGStatus,
} from '../api/client';
import type { ChatMessage, ChatSource } from '../api/client';

const CHAT_STORAGE_KEY = 'mypage_chat_history';

interface Bookmark {
  id: string;
  title: string;
  session_id: string;
  query: string;
  num_papers: number;
  created_at: string;
  tags: string[];
  topic: string;
}

interface MyPageProps {
  onBack: () => void;
}

function MyPage({ onBack }: MyPageProps) {
  // Bookmark state
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([]);
  const [selectedBookmark, setSelectedBookmark] = useState<Bookmark | null>(null);
  const [bookmarkDetail, setBookmarkDetail] = useState<any>(null);
  const [loadingBookmarks, setLoadingBookmarks] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // M-6: Bulk selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // QW-4: Search/filter
  const [searchQuery, setSearchQuery] = useState('');

  // QW-3: Topic-scoped chat
  const [chatTopicFilter, setChatTopicFilter] = useState<string>('all');

  // Chat state — QW-5: restore from sessionStorage
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    try {
      const saved = sessionStorage.getItem(CHAT_STORAGE_KEY);
      return saved ? JSON.parse(saved) : [];
    } catch { return []; }
  });
  const [inputValue, setInputValue] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [pendingSources, setPendingSources] = useState<ChatSource[] | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // QW-5: persist chat history
  useEffect(() => {
    try { sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages)); } catch { /* ignore */ }
  }, [messages]);

  // Accordion state — for topic groups only
  const [topicAccordionOpen, setTopicAccordionOpen] = useState<Record<string, boolean>>({});

  // Topic management
  const [newTopicInput, setNewTopicInput] = useState('');
  const [moveTopicInput, setMoveTopicInput] = useState('');
  const [showNewTopicInput, setShowNewTopicInput] = useState(false);
  const [movingBookmarkId, setMovingBookmarkId] = useState<string | null>(null);

  const toggleTopicAccordion = (topic: string) => {
    setTopicAccordionOpen(prev => ({ ...prev, [topic]: !prev[topic] }));
  };

  // QW-4: Filter bookmarks by search query
  const filteredBookmarks = useMemo(() => {
    if (!searchQuery.trim()) return bookmarks;
    const q = searchQuery.toLowerCase();
    return bookmarks.filter(bm =>
      bm.title.toLowerCase().includes(q) ||
      bm.query.toLowerCase().includes(q) ||
      bm.tags.some(t => t.toLowerCase().includes(q)) ||
      bm.topic.toLowerCase().includes(q)
    );
  }, [bookmarks, searchQuery]);

  // Group filtered bookmarks by topic
  const topicGroups = useMemo(() => {
    const groups: Record<string, Bookmark[]> = {};
    filteredBookmarks.forEach(bm => {
      const topic = bm.topic || 'General';
      if (!groups[topic]) groups[topic] = [];
      groups[topic].push(bm);
    });
    const sortedKeys = Object.keys(groups).sort((a, b) => {
      if (a === 'General') return -1;
      if (b === 'General') return 1;
      return a.localeCompare(b);
    });
    const sorted: Record<string, Bookmark[]> = {};
    sortedKeys.forEach(k => { sorted[k] = groups[k]; });
    return sorted;
  }, [filteredBookmarks]);

  const allTopics = useMemo(() => {
    const topics = new Set<string>();
    bookmarks.forEach(bm => topics.add(bm.topic || 'General'));
    return Array.from(topics).sort((a, b) => {
      if (a === 'General') return -1;
      if (b === 'General') return 1;
      return a.localeCompare(b);
    });
  }, [bookmarks]);

  // Initialize accordion open state for new topics
  useEffect(() => {
    setTopicAccordionOpen(prev => {
      const next = { ...prev };
      allTopics.forEach(topic => {
        if (!(topic in next)) {
          next[topic] = true;
        }
      });
      return next;
    });
  }, [allTopics]);

  // QW-3: Get bookmark IDs for selected chat topic
  const chatBookmarkIds = useMemo(() => {
    if (chatTopicFilter === 'all') return [];
    return bookmarks
      .filter(bm => (bm.topic || 'General') === chatTopicFilter)
      .map(bm => bm.id);
  }, [bookmarks, chatTopicFilter]);

  // LightRAG state (for header Build KG button)
  const [kgBuilding, setKgBuilding] = useState(false);

  // Load bookmarks on mount
  useEffect(() => {
    loadBookmarks();
  }, []);

  // Auto-scroll chat to bottom
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  const loadBookmarks = async () => {
    try {
      setLoadingBookmarks(true);
      const data = await getBookmarks();
      setBookmarks(data.bookmarks || []);
    } catch (error: any) {
      console.error('Failed to load bookmarks:', error);
    } finally {
      setLoadingBookmarks(false);
    }
  };

  const handleSelectBookmark = async (bookmark: Bookmark) => {
    setSelectedBookmark(bookmark);
    setLoadingDetail(true);
    try {
      const detail = await getBookmarkDetail(bookmark.id);
      setBookmarkDetail(detail);
    } catch (error: any) {
      console.error('Failed to load bookmark detail:', error);
    } finally {
      setLoadingDetail(false);
    }
  };

  const handleDeleteBookmark = async (bookmarkId: string) => {
    const bm = bookmarks.find(b => b.id === bookmarkId);
    if (!confirm(`"${bm?.title || 'this bookmark'}" 을(를) 삭제하시겠습니까?`)) return;
    try {
      await deleteBookmark(bookmarkId);
      setBookmarks(prev => prev.filter(b => b.id !== bookmarkId));
      if (selectedBookmark?.id === bookmarkId) {
        setSelectedBookmark(null);
        setBookmarkDetail(null);
      }
      setSelectedIds(prev => { const next = new Set(prev); next.delete(bookmarkId); return next; });
    } catch (error: any) {
      console.error('Failed to delete bookmark:', error);
    }
  };

  const handleMoveBookmark = async (bookmarkId: string, newTopic: string) => {
    try {
      await updateBookmarkTopic(bookmarkId, newTopic);
      setBookmarks(prev => prev.map(bm =>
        bm.id === bookmarkId ? { ...bm, topic: newTopic } : bm
      ));
      setMovingBookmarkId(null);
      setMoveTopicInput('');
    } catch (error: any) {
      console.error('Failed to move bookmark:', error);
    }
  };

  const handleAddTopic = () => {
    const trimmed = newTopicInput.trim();
    if (!trimmed) return;
    setTopicAccordionOpen(prev => ({ ...prev, [trimmed]: true }));
    if (movingBookmarkId) {
      handleMoveBookmark(movingBookmarkId, trimmed);
    }
    setNewTopicInput('');
    setShowNewTopicInput(false);
  };

  const handleAddMoveTopicInline = () => {
    const trimmed = moveTopicInput.trim();
    if (!trimmed || !movingBookmarkId) return;
    handleMoveBookmark(movingBookmarkId, trimmed);
  };

  // M-6: Bulk selection handlers
  const handleToggleSelection = (bookmarkId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(bookmarkId)) next.delete(bookmarkId);
      else next.add(bookmarkId);
      return next;
    });
  };

  const handleSelectAll = () => {
    setSelectedIds(new Set(filteredBookmarks.map(bm => bm.id)));
  };

  const handleDeselectAll = () => {
    setSelectedIds(new Set());
  };

  const handleBulkDelete = async () => {
    const count = selectedIds.size;
    if (!confirm(`선택한 ${count}개의 북마크를 삭제하시겠습니까?`)) return;
    try {
      await bulkDeleteBookmarks(Array.from(selectedIds));
      setBookmarks(prev => prev.filter(bm => !selectedIds.has(bm.id)));
      if (selectedBookmark && selectedIds.has(selectedBookmark.id)) {
        setSelectedBookmark(null);
        setBookmarkDetail(null);
      }
      setSelectedIds(new Set());
    } catch (error: any) {
      console.error('Failed to bulk delete:', error);
    }
  };

  const handleBulkMove = async (topic: string) => {
    try {
      await bulkMoveBookmarks(Array.from(selectedIds), topic);
      setBookmarks(prev => prev.map(bm =>
        selectedIds.has(bm.id) ? { ...bm, topic } : bm
      ));
      setSelectedIds(new Set());
    } catch (error: any) {
      console.error('Failed to bulk move:', error);
    }
  };

  // U-4: Use ref to capture sources in streaming closure
  const pendingSourcesRef = useRef<ChatSource[] | null>(null);

  const handleSendMessage = useCallback(async (overrideContent?: string) => {
    const trimmed = (overrideContent || inputValue).trim();
    if (!trimmed || isStreaming) return;

    const userMessage: ChatMessage = { role: 'user', content: trimmed };
    const updatedMessages = [...messages, userMessage];
    setMessages(updatedMessages);
    setInputValue('');
    setIsStreaming(true);
    setStreamingContent('');
    setPendingSources(null);
    pendingSourcesRef.current = null;

    let accumulated = '';

    await chatWithBookmarks(
      updatedMessages,
      chatBookmarkIds,
      (chunk) => {
        accumulated += chunk;
        setStreamingContent(accumulated);
      },
      (sources) => {
        pendingSourcesRef.current = sources;
        setPendingSources(sources);
      },
      () => {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: accumulated,
          sources: pendingSourcesRef.current || undefined,
        }]);
        setStreamingContent('');
        setPendingSources(null);
        pendingSourcesRef.current = null;
        setIsStreaming(false);
      },
      (error) => {
        setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${error}` }]);
        setStreamingContent('');
        setPendingSources(null);
        pendingSourcesRef.current = null;
        setIsStreaming(false);
      },
    );
  }, [inputValue, isStreaming, messages, chatBookmarkIds]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // QW-8: Export BibTeX
  const handleExportBibTeX = () => {
    if (!bookmarkDetail?.papers) return;
    const bibtex = bookmarkDetail.papers.map((p: any, i: number) => {
      const key = (p.title || 'paper').replace(/[^a-zA-Z0-9]/g, '').slice(0, 20) + (p.year || i);
      const authors = (p.authors || []).join(' and ');
      return `@article{${key},\n  title={${p.title || 'Untitled'}},\n  author={${authors || 'Unknown'}},\n  year={${p.year || 'n.d.'}}\n}`;
    }).join('\n\n');
    const blob = new Blob([bibtex], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(bookmarkDetail.title || 'bookmarks').replace(/[^a-zA-Z0-9]/g, '_')}.bib`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // QW-8: Export report markdown
  const handleExportReport = () => {
    if (!bookmarkDetail?.report_markdown) return;
    const blob = new Blob([bookmarkDetail.report_markdown], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(bookmarkDetail.title || 'report').replace(/[^a-zA-Z0-9]/g, '_')}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // LightRAG handlers
  const handleBuildKG = async () => {
    if (kgBuilding) return;
    setKgBuilding(true);
    try {
      await buildLightRAG(4, 'gpt-4o-mini');
      alert('Knowledge Graph build started in background.');
      const pollId = setInterval(async () => {
        try {
          const status = await getLightRAGStatus();
          if (status.status === 'ready' && status.stats && status.stats.kg_nodes > 0) {
            setKgBuilding(false);
            clearInterval(pollId);
          }
        } catch { /* still building */ }
      }, 10000);
      setTimeout(() => { clearInterval(pollId); setKgBuilding(false); }, 600000);
    } catch (error: any) {
      alert(`KG build failed: ${error.message || error}`);
      setKgBuilding(false);
    }
  };

  // U-4: Render citation badges inline
  const renderCitationText = (text: string, sources?: ChatSource[]) => {
    if (!sources || sources.length === 0) return <>{text}</>;
    const parts: (string | JSX.Element)[] = [];
    let lastIndex = 0;
    const regex = /\[(\d+)\]/g;
    let match;
    let key = 0;
    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIndex) parts.push(text.substring(lastIndex, match.index));
      const refNum = parseInt(match[1]);
      const source = sources.find(s => s.ref === refNum);
      if (source) {
        parts.push(
          <span
            key={`c-${key++}`}
            className="mypage-citation-badge"
            onClick={(e) => {
              e.stopPropagation();
              const bm = bookmarks.find(b => b.id === source.id);
              if (bm) handleSelectBookmark(bm);
            }}
            title={source.title}
          >[{refNum}]</span>
        );
      } else {
        parts.push(match[0]);
      }
      lastIndex = match.index + match[0].length;
    }
    if (lastIndex < text.length) parts.push(text.substring(lastIndex));
    return <>{parts}</>;
  };

  return (
    <div className="mypage">
      {/* Header */}
      <div className="mypage-app-header">
        <div className="mypage-header-nav">
          <div className="mypage-logo" onClick={onBack} style={{ cursor: 'pointer' }}>
            <img src="/Jipyheonjeon_llama.png" alt="Jipyheonjeon" className="mypage-logo-icon"
              onError={(e) => { e.currentTarget.style.display = 'none'; }} />
            <span className="mypage-brand-name">Jipyheonjeon</span>
          </div>
          <div className="mypage-header-actions">
            <button className="mypage-nav-btn" onClick={handleBuildKG} disabled={kgBuilding}
              title="Build Knowledge Graph">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px' }}>
                <circle cx="12" cy="5" r="3" /><circle cx="5" cy="19" r="3" /><circle cx="19" cy="19" r="3" />
                <line x1="12" y1="8" x2="5" y2="16" /><line x1="12" y1="8" x2="19" y2="16" />
              </svg>
              {kgBuilding ? 'Building...' : 'Build KG'}
            </button>
            <button className="mypage-nav-btn mypage-nav-btn-active">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px' }}>
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
              </svg>
              My Page
            </button>
          </div>
        </div>
      </div>

      {/* 3-panel layout */}
      <div className="mypage-content">
        {/* ===== Panel 1: Bookmarks ===== */}
        <div className="mypage-bookmarks-panel">
          {/* Search bar */}
          <div className="mypage-search-bar">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14" className="mypage-search-icon">
              <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input type="text" className="mypage-search-input" placeholder="Search bookmarks..."
              value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} />
            {searchQuery && (
              <button className="mypage-search-clear" onClick={() => setSearchQuery('')}>✕</button>
            )}
          </div>

          {/* M-6: Bulk action bar */}
          {selectedIds.size > 0 && (
            <div className="mypage-bulk-bar">
              <div className="mypage-bulk-info">
                <span className="mypage-bulk-count">{selectedIds.size} selected</span>
                <button className="mypage-bulk-text-btn" onClick={handleSelectAll}>All</button>
                <button className="mypage-bulk-text-btn" onClick={handleDeselectAll}>None</button>
              </div>
              <div className="mypage-bulk-actions">
                <select className="mypage-bulk-move-select" defaultValue=""
                  onChange={(e) => { if (e.target.value) { handleBulkMove(e.target.value); e.target.value = ''; } }}>
                  <option value="" disabled>Move to...</option>
                  {allTopics.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
                <button className="mypage-bulk-delete-btn" onClick={handleBulkDelete}>Delete</button>
              </div>
            </div>
          )}

          {/* Bookmark list */}
          <div className="mypage-bookmarks-scroll">
            {loadingBookmarks ? (
              <div className="mypage-loading">Loading...</div>
            ) : bookmarks.length === 0 ? (
              <div className="mypage-empty">No bookmarks saved yet</div>
            ) : filteredBookmarks.length === 0 ? (
              <div className="mypage-empty">No bookmarks match "{searchQuery}"</div>
            ) : (
              Object.entries(topicGroups).map(([topic, topicBookmarks]) => (
                <div key={topic} className="mypage-accordion">
                  <div
                    className={`mypage-accordion-header ${topicAccordionOpen[topic] ? 'open' : ''}`}
                    onClick={() => toggleTopicAccordion(topic)}
                  >
                    <svg className="mypage-accordion-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                      <polyline points="9 18 15 12 9 6" />
                    </svg>
                    <span className="mypage-accordion-topic-name">{topic}</span>
                    <span className="mypage-accordion-count">{topicBookmarks.length}</span>
                  </div>
                  {topicAccordionOpen[topic] && (
                    <div className="mypage-accordion-body">
                      <div className="mypage-bookmarks-list">
                        {topicBookmarks.map((bm) => (
                          <div
                            key={bm.id}
                            className={`mypage-bookmark-item ${selectedBookmark?.id === bm.id ? 'active' : ''} ${selectedIds.has(bm.id) ? 'checked' : ''}`}
                            onClick={() => handleSelectBookmark(bm)}
                          >
                            {/* M-6: Checkbox */}
                            <input
                              type="checkbox"
                              className="mypage-bookmark-checkbox"
                              checked={selectedIds.has(bm.id)}
                              onClick={(e) => handleToggleSelection(bm.id, e as any)}
                              onChange={() => {}}
                            />
                            <div className="mypage-bookmark-info">
                              <div className="mypage-bookmark-title">{bm.title}</div>
                              <div className="mypage-bookmark-meta">
                                <span>{new Date(bm.created_at).toLocaleDateString()}</span>
                                <span>{bm.num_papers} papers</span>
                              </div>
                              {bm.tags && bm.tags.length > 0 && (
                                <div className="mypage-bookmark-tags">
                                  {bm.tags.map((tag, ti) => (
                                    <span key={ti} className="mypage-tag-chip" onClick={(e) => { e.stopPropagation(); setSearchQuery(tag); }}>{tag}</span>
                                  ))}
                                </div>
                              )}
                            </div>
                            <div className="mypage-bookmark-actions">
                              <button className="mypage-bookmark-move"
                                onClick={(e) => { e.stopPropagation(); setMovingBookmarkId(movingBookmarkId === bm.id ? null : bm.id); setMoveTopicInput(''); }}
                                title="Move to topic">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                                </svg>
                              </button>
                              <button className="mypage-bookmark-delete"
                                onClick={(e) => { e.stopPropagation(); handleDeleteBookmark(bm.id); }}
                                title="Delete">✕</button>
                            </div>
                            {movingBookmarkId === bm.id && (
                              <div className="mypage-move-dropdown" onClick={(e) => e.stopPropagation()}>
                                <div className="mypage-move-dropdown-title">Move to:</div>
                                {allTopics.filter(t => t !== topic).map(t => (
                                  <button key={t} className="mypage-move-dropdown-item" onClick={() => handleMoveBookmark(bm.id, t)}>{t}</button>
                                ))}
                                <div className="mypage-move-dropdown-divider" />
                                <div className="mypage-move-new-topic">
                                  <input type="text" placeholder="New topic..." value={moveTopicInput}
                                    onChange={(e) => setMoveTopicInput(e.target.value)}
                                    onKeyDown={(e) => { if (e.key === 'Enter') handleAddMoveTopicInline(); }}
                                    className="mypage-move-new-input" />
                                  <button className="mypage-move-new-btn" onClick={handleAddMoveTopicInline} disabled={!moveTopicInput.trim()}>+</button>
                                </div>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}

            {!loadingBookmarks && bookmarks.length > 0 && (
              <div className="mypage-add-topic-section">
                {showNewTopicInput ? (
                  <div className="mypage-add-topic-form">
                    <input type="text" placeholder="Topic name..." value={newTopicInput}
                      onChange={(e) => setNewTopicInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleAddTopic();
                        if (e.key === 'Escape') { setShowNewTopicInput(false); setNewTopicInput(''); }
                      }}
                      className="mypage-add-topic-input" autoFocus />
                    <button className="mypage-add-topic-confirm" onClick={handleAddTopic} disabled={!newTopicInput.trim()}>Add</button>
                    <button className="mypage-add-topic-cancel" onClick={() => { setShowNewTopicInput(false); setNewTopicInput(''); }}>✕</button>
                  </div>
                ) : (
                  <button className="mypage-add-topic-btn" onClick={() => setShowNewTopicInput(true)}>+ New Topic</button>
                )}
              </div>
            )}
          </div>
        </div>

        {/* ===== Panel 2: Report / Detail ===== */}
        <div className="mypage-report-panel">
          {!selectedBookmark ? (
            <div className="mypage-report-empty">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="40" height="40" style={{ color: '#4b5563', marginBottom: '12px' }}>
                <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2z" />
              </svg>
              <p className="mypage-report-empty-title">Select a bookmark</p>
              <p className="mypage-report-empty-subtitle">Click a bookmark on the left to view its report and papers</p>
            </div>
          ) : loadingDetail ? (
            <div className="mypage-loading" style={{ padding: '40px' }}>Loading detail...</div>
          ) : bookmarkDetail ? (
            <div className="mypage-report-scroll">
              {/* Header with title & export */}
              <div className="mypage-report-header">
                <h2 className="mypage-report-title">{bookmarkDetail.title}</h2>
                <div className="mypage-detail-export-btns">
                  <button className="mypage-export-btn" onClick={handleExportBibTeX} title="Export BibTeX">BibTeX</button>
                  {bookmarkDetail.report_markdown && (
                    <button className="mypage-export-btn" onClick={handleExportReport} title="Download Report">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                      .md
                    </button>
                  )}
                </div>
              </div>

              {/* Papers list */}
              {bookmarkDetail.papers && bookmarkDetail.papers.length > 0 && (
                <div className="mypage-report-section">
                  <h3 className="mypage-report-section-title">Papers ({bookmarkDetail.papers.length})</h3>
                  <div className="mypage-detail-papers">
                    {bookmarkDetail.papers.map((p: any, i: number) => (
                      <div key={i} className="mypage-detail-paper">
                        <span className="mypage-detail-paper-title">{p.title}</span>
                        <span className="mypage-detail-paper-meta">
                          {p.authors?.slice(0, 2).join(', ')}{p.authors?.length > 2 ? ' et al.' : ''} {p.year && `(${p.year})`}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Report markdown */}
              {bookmarkDetail.report_markdown && (
                <div className="mypage-report-section">
                  <h3 className="mypage-report-section-title">Report</h3>
                  <div className="mypage-report-content">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {bookmarkDetail.report_markdown}
                    </ReactMarkdown>
                  </div>
                </div>
              )}

            </div>
          ) : null}
        </div>

        {/* ===== Panel 3: Chat ===== */}
        <div className="mypage-chat-panel">
          {/* Chat header with topic filter */}
          <div className="mypage-panel-header mypage-chat-header">
            <span>Chat with your papers</span>
            <div className="mypage-chat-header-actions">
              <select className="mypage-chat-topic-select" value={chatTopicFilter}
                onChange={(e) => setChatTopicFilter(e.target.value)}>
                <option value="all">All topics</option>
                {allTopics.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
              {messages.length > 0 && (
                <button className="mypage-chat-clear-btn"
                  onClick={() => { setMessages([]); sessionStorage.removeItem(CHAT_STORAGE_KEY); }}
                  title="Clear chat">✕</button>
              )}
            </div>
          </div>

          <div className="mypage-chat-messages">
            {messages.length === 0 && !isStreaming && (
              <div className="mypage-chat-welcome">
                <p className="mypage-chat-welcome-title">Ask about your bookmarked papers</p>
                <p className="mypage-chat-welcome-subtitle">
                  {chatTopicFilter === 'all'
                    ? 'The assistant has access to all your bookmarked research reports.'
                    : `Chatting with papers in "${chatTopicFilter}" topic.`}
                </p>
              </div>
            )}

            {messages.map((msg, i) => (
              <div key={i} className={`mypage-chat-message mypage-chat-${msg.role}`}>
                <div className="mypage-chat-bubble">
                  {msg.role === 'assistant' ? (
                    <div className="mypage-chat-markdown">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          p: ({ children }) => {
                            // U-4: Replace [N] with citation badges in paragraph text
                            const processNode = (node: any): any => {
                              if (typeof node === 'string') {
                                return renderCitationText(node, msg.sources);
                              }
                              return node;
                            };
                            const processed = Array.isArray(children)
                              ? children.map(processNode)
                              : processNode(children);
                            return <p>{processed}</p>;
                          },
                          li: ({ children }) => {
                            const processNode = (node: any): any => {
                              if (typeof node === 'string') {
                                return renderCitationText(node, msg.sources);
                              }
                              return node;
                            };
                            const processed = Array.isArray(children)
                              ? children.map(processNode)
                              : processNode(children);
                            return <li>{processed}</li>;
                          },
                        }}
                      >
                        {msg.content}
                      </ReactMarkdown>
                      {/* U-4: Sources section */}
                      {msg.sources && msg.sources.length > 0 && (
                        <details className="mypage-sources-section">
                          <summary className="mypage-sources-header">Sources ({msg.sources.length})</summary>
                          <div className="mypage-sources-list">
                            {msg.sources.map(source => (
                              <div key={source.ref} className="mypage-source-item"
                                onClick={() => {
                                  const bm = bookmarks.find(b => b.id === source.id);
                                  if (bm) handleSelectBookmark(bm);
                                }}>
                                <span className="mypage-source-ref">[{source.ref}]</span>
                                <span className="mypage-source-title">{source.title}</span>
                                <span className="mypage-source-meta">{source.num_papers} papers</span>
                              </div>
                            ))}
                          </div>
                        </details>
                      )}
                    </div>
                  ) : (
                    <pre className="mypage-chat-text">{msg.content}</pre>
                  )}
                </div>
              </div>
            ))}

            {isStreaming && streamingContent && (
              <div className="mypage-chat-message mypage-chat-assistant">
                <div className="mypage-chat-bubble">
                  <div className="mypage-chat-markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingContent}</ReactMarkdown>
                  </div>
                  <span className="mypage-streaming-cursor"></span>
                </div>
              </div>
            )}

            {isStreaming && !streamingContent && (
              <div className="mypage-chat-message mypage-chat-assistant">
                <div className="mypage-chat-bubble">
                  <div className="mypage-chat-typing">
                    <span></span><span></span><span></span>
                  </div>
                </div>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>

          <div className="mypage-chat-input-area">
            <textarea className="mypage-chat-input" value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={chatTopicFilter === 'all' ? 'Ask about your bookmarked papers...' : `Ask about "${chatTopicFilter}" papers...`}
              rows={1} disabled={isStreaming} />
            <button className="mypage-chat-send" onClick={() => handleSendMessage()}
              disabled={isStreaming || !inputValue.trim()}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default MyPage;
