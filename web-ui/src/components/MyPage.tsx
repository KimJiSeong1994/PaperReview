import { useState, useEffect, useRef, useMemo, useCallback, cloneElement, isValidElement } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  DndContext, DragOverlay, pointerWithin,
  PointerSensor, useSensor, useSensors, useDraggable, useDroppable,
  type DragStartEvent, type DragEndEvent, type DragOverEvent,
} from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import './MyPage.css';
import {
  getBookmarks, getBookmarkDetail, deleteBookmark, updateBookmarkTopic,
  bulkDeleteBookmarks, bulkMoveBookmarks, updateBookmarkNotes, autoHighlightBookmark,
  chatWithBookmarks, buildLightRAG, getLightRAGStatus,
} from '../api/client';
import type { ChatMessage, ChatSource, HighlightItem } from '../api/client';

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
  has_notes?: boolean;
}

/* ===== Draggable Bookmark Item ===== */
interface DraggableBookmarkItemProps {
  bookmark: Bookmark;
  isActive: boolean;
  isChecked: boolean;
  onSelect: (bm: Bookmark) => void;
  onToggleSelection: (id: string, e: React.MouseEvent) => void;
  onDelete: (id: string) => void;
  currentTopic: string;
  setSearchQuery: (q: string) => void;
}

function DraggableBookmarkItem({
  bookmark: bm, isActive, isChecked,
  onSelect, onToggleSelection, onDelete, currentTopic, setSearchQuery,
}: DraggableBookmarkItemProps) {
  const {
    attributes, listeners, setNodeRef, transform, isDragging,
  } = useDraggable({ id: bm.id, data: { topic: currentTopic, bookmark: bm } });

  const style = transform ? {
    transform: CSS.Translate.toString(transform),
  } : undefined;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`mypage-tree-file ${isActive ? 'active' : ''} ${isChecked ? 'checked' : ''} ${isDragging ? 'dragging' : ''}`}
      onClick={() => !isDragging && onSelect(bm)}
    >
      {/* Tree guide line */}
      <span className="mypage-tree-guide-line" />
      {/* Drag handle */}
      <button
        className="mypage-drag-handle"
        {...attributes}
        {...listeners}
        onClick={(e) => e.stopPropagation()}
        tabIndex={-1}
      >
        <svg viewBox="0 0 16 16" width="10" height="10" fill="currentColor">
          <circle cx="5" cy="3" r="1.5"/><circle cx="11" cy="3" r="1.5"/>
          <circle cx="5" cy="8" r="1.5"/><circle cx="11" cy="8" r="1.5"/>
          <circle cx="5" cy="13" r="1.5"/><circle cx="11" cy="13" r="1.5"/>
        </svg>
      </button>
      {/* Checkbox */}
      <input
        type="checkbox"
        className="mypage-bookmark-checkbox"
        checked={isChecked}
        onClick={(e) => onToggleSelection(bm.id, e as any)}
        onChange={() => {}}
      />
      {/* File icon */}
      <svg className="mypage-tree-file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="13" height="13">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
      </svg>
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
        {bm.has_notes && (
          <svg className="mypage-note-indicator" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
          </svg>
        )}
        <button className="mypage-bookmark-delete"
          onClick={(e) => { e.stopPropagation(); onDelete(bm.id); }}
          title="Delete">✕</button>
      </div>
    </div>
  );
}

/* ===== Droppable Topic Group (Directory Tree) ===== */
interface DroppableTopicGroupProps {
  topic: string;
  isOpen: boolean;
  onToggle: () => void;
  bookmarkCount: number;
  isOver: boolean;
  isLast: boolean;
  children: React.ReactNode;
}

function DroppableTopicGroup({ topic, isOpen, onToggle, bookmarkCount, isOver, isLast, children }: DroppableTopicGroupProps) {
  const { setNodeRef } = useDroppable({ id: `topic:${topic}`, data: { topic } });

  return (
    <div ref={setNodeRef} className={`mypage-tree-folder ${isOver ? 'drag-over' : ''} ${isLast ? 'last' : ''}`}>
      <div className={`mypage-tree-folder-row ${isOpen ? 'open' : ''}`} onClick={onToggle}>
        {/* Tree chevron */}
        <svg className="mypage-tree-chevron" viewBox="0 0 16 16" fill="currentColor" width="10" height="10">
          <path d="M6 4l4 4-4 4z" />
        </svg>
        {/* Folder icon */}
        <svg className="mypage-tree-folder-icon" viewBox="0 0 24 24" width="14" height="14">
          {isOpen ? (
            <>
              <path d="M5 19a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v1" fill="rgba(99,102,241,0.15)" stroke="#818cf8" strokeWidth="1.5"/>
              <path d="M5 19h14a2 2 0 0 0 2-2l-3-7H4l-1 7a2 2 0 0 0 2 2z" fill="rgba(99,102,241,0.25)" stroke="#818cf8" strokeWidth="1.5"/>
            </>
          ) : (
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" fill="rgba(156,163,175,0.1)" stroke="#6b7280" strokeWidth="1.5"/>
          )}
        </svg>
        <span className="mypage-tree-folder-name">{topic}</span>
        <span className="mypage-tree-folder-badge">{bookmarkCount}</span>
      </div>
      {isOpen && (
        <div className="mypage-tree-children">
          {bookmarkCount === 0 ? (
            <div className="mypage-tree-empty-hint">
              <span className="mypage-tree-guide-line" />
              Drag bookmarks here
            </div>
          ) : children}
        </div>
      )}
    </div>
  );
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
  const [_pendingSources, setPendingSources] = useState<ChatSource[] | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const reportScrollRef = useRef<HTMLDivElement>(null);

  // Highlight state — search terms to highlight in report panel
  const [highlightTerms, setHighlightTerms] = useState<string[]>([]);

  // Notes & user highlights
  const [notesText, setNotesText] = useState('');
  const [notesSaving, setNotesSaving] = useState(false);
  const [notesCollapsed, setNotesCollapsed] = useState(true);
  const [userHighlights, setUserHighlights] = useState<HighlightItem[]>([]);
  const [selectionToolbar, setSelectionToolbar] = useState<{ x: number; y: number; text: string } | null>(null);
  const [allNotesMode, setAllNotesMode] = useState(false);
  const [memoMode, setMemoMode] = useState(false);
  const [memoInput, setMemoInput] = useState('');
  const memoModeRef = useRef(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'error'>('idle');
  const [autoHighlighting, setAutoHighlighting] = useState(false);

  // QW-5: persist chat history
  useEffect(() => {
    try { sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages)); } catch { /* ignore */ }
  }, [messages]);

  // Accordion state — for topic groups only
  const [topicAccordionOpen, setTopicAccordionOpen] = useState<Record<string, boolean>>({});

  // Topic management
  const [newTopicInput, setNewTopicInput] = useState('');
  const [showNewTopicInput, setShowNewTopicInput] = useState(false);
  const [emptyTopics, setEmptyTopics] = useState<Set<string>>(new Set());

  const toggleTopicAccordion = (topic: string) => {
    setTopicAccordionOpen(prev => ({ ...prev, [topic]: !prev[topic] }));
  };

  // QW-4: Filter bookmarks by search query + notes filter
  const filteredBookmarks = useMemo(() => {
    let filtered = bookmarks;
    if (allNotesMode) {
      filtered = filtered.filter(bm => bm.has_notes);
    }
    if (!searchQuery.trim()) return filtered;
    const q = searchQuery.toLowerCase();
    return filtered.filter(bm =>
      bm.title.toLowerCase().includes(q) ||
      bm.query.toLowerCase().includes(q) ||
      bm.tags.some(t => t.toLowerCase().includes(q)) ||
      bm.topic.toLowerCase().includes(q)
    );
  }, [bookmarks, searchQuery, allNotesMode]);

  // Group filtered bookmarks by topic (including empty user-created topics)
  const topicGroups = useMemo(() => {
    const groups: Record<string, Bookmark[]> = {};
    // Include empty topics first
    emptyTopics.forEach(topic => { groups[topic] = []; });
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
  }, [filteredBookmarks, emptyTopics]);

  const allTopics = useMemo(() => {
    const topics = new Set<string>();
    bookmarks.forEach(bm => topics.add(bm.topic || 'General'));
    emptyTopics.forEach(t => topics.add(t));
    return Array.from(topics).sort((a, b) => {
      if (a === 'General') return -1;
      if (b === 'General') return 1;
      return a.localeCompare(b);
    });
  }, [bookmarks, emptyTopics]);

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

  // DnD state
  const [activeDragId, setActiveDragId] = useState<string | null>(null);
  const [overTopicId, setOverTopicId] = useState<string | null>(null);
  const autoExpandTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  );

  const activeDragBookmark = useMemo(() =>
    activeDragId ? bookmarks.find(bm => bm.id === activeDragId) || null : null
  , [activeDragId, bookmarks]);

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setActiveDragId(event.active.id as string);
  }, []);

  const handleDragOver = useCallback((event: DragOverEvent) => {
    const overId = event.over?.id as string | undefined;
    let topicId: string | null = null;

    if (overId?.startsWith('topic:')) {
      topicId = overId;
    } else {
      topicId = null;
    }

    setOverTopicId(topicId);

    // Auto-expand collapsed topics after hovering 500ms
    if (topicId) {
      const topicName = topicId.replace('topic:', '');
      if (!topicAccordionOpen[topicName]) {
        if (autoExpandTimerRef.current) clearTimeout(autoExpandTimerRef.current);
        autoExpandTimerRef.current = setTimeout(() => {
          setTopicAccordionOpen(prev => ({ ...prev, [topicName]: true }));
        }, 500);
      }
    } else {
      if (autoExpandTimerRef.current) {
        clearTimeout(autoExpandTimerRef.current);
        autoExpandTimerRef.current = null;
      }
    }
  }, [topicAccordionOpen]);

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event;
    setActiveDragId(null);
    setOverTopicId(null);
    if (autoExpandTimerRef.current) {
      clearTimeout(autoExpandTimerRef.current);
      autoExpandTimerRef.current = null;
    }

    if (!over) return;

    const draggedId = active.id as string;
    const sourceTopic = (active.data.current as any)?.topic as string | undefined;
    if (!sourceTopic) return;

    const overId = over.id as string;
    let targetTopic: string | null = null;

    if (overId.startsWith('topic:')) {
      targetTopic = overId.replace('topic:', '');
    }

    if (targetTopic && targetTopic !== sourceTopic) {
      handleMoveBookmark(draggedId, targetTopic);
    }
  }, []);

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
    setSelectionToolbar(null);
    try {
      const detail = await getBookmarkDetail(bookmark.id);
      setBookmarkDetail(detail);
      setNotesText(detail.notes || '');
      setUserHighlights(detail.highlights || []);
      setNotesCollapsed(!(detail.notes || '').trim() && !(detail.highlights || []).length);
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
      // Remove from emptyTopics if a bookmark was moved into it
      setEmptyTopics(prev => {
        const next = new Set(prev);
        next.delete(newTopic);
        return next;
      });
    } catch (error: any) {
      console.error('Failed to move bookmark:', error);
    }
  };

  const handleAddTopic = () => {
    const trimmed = newTopicInput.trim();
    if (!trimmed) return;
    setEmptyTopics(prev => new Set(prev).add(trimmed));
    setTopicAccordionOpen(prev => ({ ...prev, [trimmed]: true }));
    setNewTopicInput('');
    setShowNewTopicInput(false);
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

  // ── Notes & Highlights handlers ──
  const showSaveStatus = (status: 'saved' | 'error') => {
    setSaveStatus(status);
    setTimeout(() => setSaveStatus('idle'), 2000);
  };

  const handleSaveNotes = async () => {
    if (!selectedBookmark) return;
    setNotesSaving(true);
    try {
      await updateBookmarkNotes(selectedBookmark.id, notesText, userHighlights);
      setBookmarks(prev => prev.map(bm =>
        bm.id === selectedBookmark.id
          ? { ...bm, has_notes: !!notesText.trim() || userHighlights.length > 0 }
          : bm
      ));
      showSaveStatus('saved');
    } catch (error) {
      console.error('Failed to save notes:', error);
      showSaveStatus('error');
    } finally {
      setNotesSaving(false);
    }
  };

  const handleAddHighlight = async () => {
    if (!selectionToolbar || !selectedBookmark) return;
    const text = selectionToolbar.text;
    if (!text || text.length < 3) return;

    const newHighlight: HighlightItem = {
      id: `hl_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`,
      text,
      color: '#a5b4fc',
      memo: '',
      created_at: new Date().toISOString(),
    };
    const updated = [...userHighlights, newHighlight];
    setUserHighlights(updated);
    setSelectionToolbar(null);
    window.getSelection()?.removeAllRanges();
    setNotesCollapsed(false);

    try {
      await updateBookmarkNotes(selectedBookmark.id, undefined, updated);
      setBookmarks(prev => prev.map(bm =>
        bm.id === selectedBookmark.id ? { ...bm, has_notes: true } : bm
      ));
      showSaveStatus('saved');
    } catch (error) {
      console.error('Failed to save highlight:', error);
      showSaveStatus('error');
    }
  };

  const handleRemoveHighlight = async (hlId: string) => {
    if (!selectedBookmark) return;
    const updated = userHighlights.filter(hl => hl.id !== hlId);
    setUserHighlights(updated);
    try {
      await updateBookmarkNotes(selectedBookmark.id, undefined, updated);
      setBookmarks(prev => prev.map(bm =>
        bm.id === selectedBookmark.id
          ? { ...bm, has_notes: !!notesText.trim() || updated.length > 0 }
          : bm
      ));
      showSaveStatus('saved');
    } catch (error) {
      console.error('Failed to remove highlight:', error);
      showSaveStatus('error');
    }
  };

  // Keep memoModeRef in sync for use inside event listener closures
  useEffect(() => { memoModeRef.current = memoMode; }, [memoMode]);

  const handleStartMemo = () => {
    if (!selectionToolbar || !selectedBookmark) return;
    setMemoMode(true);
    setMemoInput('');
    window.getSelection()?.removeAllRanges();
  };

  const handleSaveMemo = async () => {
    if (!selectedBookmark || !selectionToolbar) return;
    const newHighlight: HighlightItem = {
      id: `hl_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`,
      text: selectionToolbar.text,
      color: '#a5b4fc',
      memo: memoInput.trim(),
      created_at: new Date().toISOString(),
    };
    const updated = [...userHighlights, newHighlight];
    setUserHighlights(updated);
    setSelectionToolbar(null);
    setMemoMode(false);
    setMemoInput('');
    setNotesCollapsed(false);

    try {
      await updateBookmarkNotes(selectedBookmark.id, undefined, updated);
      setBookmarks(prev => prev.map(bm =>
        bm.id === selectedBookmark.id ? { ...bm, has_notes: true } : bm
      ));
      showSaveStatus('saved');
    } catch (error) {
      console.error('Failed to save memo:', error);
      showSaveStatus('error');
    }
  };

  const handleCancelMemo = () => {
    setMemoMode(false);
    setMemoInput('');
    setSelectionToolbar(null);
  };

  const handleAutoHighlight = async () => {
    if (!selectedBookmark || autoHighlighting) return;
    setAutoHighlighting(true);
    try {
      const result = await autoHighlightBookmark(selectedBookmark.id);
      setUserHighlights(result.highlights);
      setNotesCollapsed(false);
      setBookmarks(prev => prev.map(bm =>
        bm.id === selectedBookmark.id ? { ...bm, has_notes: true } : bm
      ));
      showSaveStatus('saved');
    } catch (error) {
      console.error('Auto highlight failed:', error);
      showSaveStatus('error');
    } finally {
      setAutoHighlighting(false);
    }
  };

  // Selection toolbar: show on text select in report area
  useEffect(() => {
    const reportEl = reportScrollRef.current;
    if (!reportEl || !bookmarkDetail) return;
    const handleMouseUp = () => {
      if (memoModeRef.current) return; // Don't interfere when typing memo
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed && sel.toString().trim().length >= 3) {
        const rect = sel.getRangeAt(0).getBoundingClientRect();
        setSelectionToolbar({ x: rect.left + rect.width / 2, y: rect.top - 8, text: sel.toString().trim() });
      } else {
        setSelectionToolbar(null);
      }
    };
    const handleMouseDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest('.mypage-selection-toolbar')) {
        setSelectionToolbar(null);
        if (memoModeRef.current) {
          setMemoMode(false);
          setMemoInput('');
        }
      }
    };
    reportEl.addEventListener('mouseup', handleMouseUp);
    document.addEventListener('mousedown', handleMouseDown);
    return () => {
      reportEl.removeEventListener('mouseup', handleMouseUp);
      document.removeEventListener('mousedown', handleMouseDown);
    };
  }, [bookmarkDetail]);

  // Highlight matching: wrap matching text fragments in <mark>
  const applyUserHighlights = (children: React.ReactNode): React.ReactNode => {
    if (userHighlights.length === 0) return children;
    const processNode = (node: React.ReactNode, key: number): React.ReactNode => {
      if (typeof node === 'string') {
        let result: React.ReactNode[] = [node];
        for (const hl of userHighlights) {
          const nextResult: React.ReactNode[] = [];
          for (const part of result) {
            if (typeof part !== 'string') { nextResult.push(part); continue; }
            const idx = part.indexOf(hl.text);
            if (idx === -1) { nextResult.push(part); continue; }
            if (idx > 0) nextResult.push(part.slice(0, idx));
            nextResult.push(<mark key={`hl-${hl.id}-${idx}`} className={`mypage-user-highlight${hl.memo ? ' has-memo' : ''}`} style={hl.color && hl.color !== '#a5b4fc' ? { background: `${hl.color}33`, borderBottomColor: `${hl.color}aa` } : undefined} title={hl.memo || undefined}>{hl.text}</mark>);
            if (idx + hl.text.length < part.length) nextResult.push(part.slice(idx + hl.text.length));
          }
          result = nextResult;
        }
        return result.length === 1 ? result[0] : <>{result}</>;
      }
      if (isValidElement(node) && (node.props as any).children) {
        return cloneElement(node, { key } as any, applyUserHighlights((node.props as any).children));
      }
      return node;
    };
    if (Array.isArray(children)) return children.map((child, i) => processNode(child, i));
    return processNode(children, 0);
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

  // Extract key terms from chat text around a citation for highlighting in report
  const extractHighlightTerms = (chatContent: string, refNum: number): string[] => {
    // Find the sentence containing [N]
    const citationPattern = `[${refNum}]`;
    const idx = chatContent.indexOf(citationPattern);
    if (idx === -1) return [];

    // Get surrounding text (expand to sentence boundaries)
    const before = chatContent.substring(Math.max(0, idx - 400), idx);
    const after = chatContent.substring(idx + citationPattern.length, Math.min(chatContent.length, idx + citationPattern.length + 300));

    // Find sentence boundaries (handle -1 from lastIndexOf)
    const dotSpace = before.lastIndexOf('. ');
    const dotNewline = before.lastIndexOf('.\n');
    const doubleNewline = before.lastIndexOf('\n\n');
    const sentStart = Math.max(
      dotSpace >= 0 ? dotSpace + 2 : 0,
      dotNewline >= 0 ? dotNewline + 2 : 0,
      doubleNewline >= 0 ? doubleNewline + 2 : 0,
      0
    );
    const sentEndOffset = after.search(/[.!?]\s|[.!?]$|\n\n|。|！|？/);
    const sentEnd = sentEndOffset >= 0 ? sentEndOffset + 1 : after.length;

    const sentence = (before.substring(sentStart) + after.substring(0, sentEnd))
      .replace(/\[\d+\]/g, '') // Remove citation markers
      .replace(/[*_#>`~]/g, '') // Remove markdown formatting
      .trim();

    if (!sentence || sentence.length < 3) return [];

    // English stop words
    const stopWords = new Set([
      'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had', 'her',
      'was', 'one', 'our', 'out', 'has', 'have', 'been', 'from', 'with', 'they',
      'this', 'that', 'these', 'those', 'which', 'their', 'also', 'more', 'some',
      'than', 'into', 'each', 'such', 'does', 'most', 'both', 'when', 'what',
      'about', 'between', 'through', 'using', 'based', 'other', 'where', 'while',
      'there', 'being', 'would', 'could', 'should', 'above', 'below',
    ]);

    // Korean stop words (common particles/suffixes)
    const koStopWords = new Set([
      '있습니다', '합니다', '됩니다', '입니다', '습니다', '것입니다',
      '하는', '되는', '있는', '없는', '같은', '대한', '통해', '위해',
      '에서', '으로', '에게', '까지', '부터', '처럼', '만큼',
      '그리고', '하지만', '그러나', '따라서', '또한', '즉',
    ]);

    const terms: string[] = [];
    const seen = new Set<string>();

    // Split by whitespace and process each token
    const tokens = sentence.split(/\s+/);
    for (const raw of tokens) {
      if (terms.length >= 10) break;

      // Trim punctuation but preserve Unicode letters (Korean, etc.)
      const w = raw.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, '');
      if (!w) continue;

      const lower = w.toLowerCase();

      // Check if it's a Korean word (contains Hangul)
      const isKorean = /[\u3131-\uD79D]/.test(w);

      if (isKorean) {
        // Korean: min 2 chars, skip stop words
        if (w.length >= 2 && !koStopWords.has(w) && !seen.has(w)) {
          seen.add(w);
          terms.push(w);
        }
      } else {
        // English/Latin: min 4 chars, skip stop words
        if (w.length >= 4 && !stopWords.has(lower) && !seen.has(lower)) {
          seen.add(lower);
          terms.push(w);
        }
      }
    }

    return terms;
  };

  // Scroll to first highlight after render when both highlightTerms and bookmarkDetail are ready
  const [scrollToHighlight, setScrollToHighlight] = useState(false);
  useEffect(() => {
    if (scrollToHighlight && highlightTerms.length > 0 && bookmarkDetail && !loadingDetail) {
      // Wait for DOM to update with highlighted marks
      const timer = setTimeout(() => {
        const firstHighlight = reportScrollRef.current?.querySelector('.mypage-highlight');
        if (firstHighlight) {
          firstHighlight.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        setScrollToHighlight(false);
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [scrollToHighlight, highlightTerms, bookmarkDetail, loadingDetail]);

  // Handle citation click — load bookmark + highlight evidence
  const handleCitationClick = async (source: ChatSource, chatContent: string, refNum: number) => {
    const bm = bookmarks.find(b => b.id === source.id);
    if (!bm) return;

    // Extract terms from chat context around the citation
    let terms = extractHighlightTerms(chatContent, refNum);

    // Fallback: if no terms found, use significant words from the source title
    if (terms.length === 0 && source.title) {
      const titleWords = source.title.split(/\s+/)
        .map(w => w.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, ''))
        .filter(w => w.length >= 3);
      terms = titleWords.slice(0, 6);
    }

    setHighlightTerms(terms);
    if (terms.length > 0) {
      setScrollToHighlight(true);
    }

    // Skip re-fetching if same bookmark is already loaded
    if (selectedBookmark?.id === bm.id && bookmarkDetail) {
      return;
    }

    // Load bookmark detail
    await handleSelectBookmark(bm);
  };

  // Clear highlights when selecting a bookmark normally (not via citation)
  const handleSelectBookmarkDirect = async (bookmark: Bookmark) => {
    setHighlightTerms([]);
    await handleSelectBookmark(bookmark);
  };

  // Highlight matching text in report content
  const highlightText = (text: string): React.ReactNode => {
    if (!highlightTerms.length) return text;

    // Build regex from terms (escape special chars), case-insensitive
    const escaped = highlightTerms.map(t =>
      t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    );
    const pattern = new RegExp(`(${escaped.join('|')})`, 'gi');

    const parts = text.split(pattern);
    if (parts.length === 1) return text;

    // When split() uses a capture group, odd-indexed elements are matches
    let hlKey = 0;
    return parts.map((part, i) => {
      if (i % 2 === 1) {
        return <mark key={`hl-${hlKey++}`} className="mypage-highlight">{part}</mark>;
      }
      return part;
    });
  };

  // Recursively process React children to apply highlight to all text nodes
  const highlightChildren = (children: React.ReactNode): React.ReactNode => {
    if (!highlightTerms.length) return children;

    const processNode = (node: any, idx: number): any => {
      if (typeof node === 'string') return highlightText(node);
      if (isValidElement(node)) {
        const processed = highlightChildren((node.props as any).children);
        return cloneElement(node, { key: node.key || `hc-${idx}` }, processed);
      }
      return node;
    };

    if (Array.isArray(children)) {
      return children.map((child, i) => processNode(child, i));
    }
    return processNode(children, 0);
  };

  // U-4: Render citation badges inline
  const renderCitationText = (text: string, sources?: ChatSource[], msgContent?: string) => {
    if (!sources || sources.length === 0) return <>{text}</>;
    const fullContent = msgContent || '';
    const parts: (string | React.ReactElement)[] = [];
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
              handleCitationClick(source, fullContent, refNum);
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

  // Recursively process children to find citation text in all nodes (including nested elements)
  const processCitationChildren = (children: React.ReactNode, sources?: ChatSource[], msgContent?: string): React.ReactNode => {
    const processNode = (node: any, idx: number): any => {
      if (typeof node === 'string') {
        return renderCitationText(node, sources, msgContent);
      }
      if (isValidElement(node) && (node.props as any).children) {
        const processed = processCitationChildren((node.props as any).children, sources, msgContent);
        return cloneElement(node, { key: node.key || `cn-${idx}` }, processed);
      }
      return node;
    };
    if (Array.isArray(children)) {
      return children.map((child, i) => processNode(child, i));
    }
    return processNode(children, 0);
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
            <button
              className={`mypage-notes-view-btn ${allNotesMode ? 'active' : ''}`}
              onClick={() => setAllNotesMode(!allNotesMode)}
              title={allNotesMode ? 'Show all bookmarks' : 'Show only bookmarks with notes'}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
              </svg>
            </button>
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

          {/* Bookmark list with DnD */}
          <div className="mypage-bookmarks-scroll">
            {loadingBookmarks ? (
              <div className="mypage-loading">Loading...</div>
            ) : bookmarks.length === 0 ? (
              <div className="mypage-empty">No bookmarks saved yet</div>
            ) : filteredBookmarks.length === 0 ? (
              <div className="mypage-empty">No bookmarks match "{searchQuery}"</div>
            ) : (
              <DndContext
                sensors={sensors}
                collisionDetection={pointerWithin}
                onDragStart={handleDragStart}
                onDragOver={handleDragOver}
                onDragEnd={handleDragEnd}
              >
                {Object.entries(topicGroups).map(([topic, topicBookmarks], idx, arr) => (
                  <DroppableTopicGroup
                    key={topic}
                    topic={topic}
                    isOpen={!!topicAccordionOpen[topic]}
                    onToggle={() => toggleTopicAccordion(topic)}
                    bookmarkCount={topicBookmarks.length}
                    isOver={overTopicId === `topic:${topic}`}
                    isLast={idx === arr.length - 1}
                  >
                    {topicBookmarks.map((bm) => (
                      <DraggableBookmarkItem
                        key={bm.id}
                        bookmark={bm}
                        isActive={selectedBookmark?.id === bm.id}
                        isChecked={selectedIds.has(bm.id)}
                        onSelect={handleSelectBookmarkDirect}
                        onToggleSelection={handleToggleSelection}
                        onDelete={handleDeleteBookmark}
                        currentTopic={topic}
                        setSearchQuery={setSearchQuery}
                      />
                    ))}
                  </DroppableTopicGroup>
                ))}

                {/* Drag overlay */}
                <DragOverlay dropAnimation={null}>
                  {activeDragBookmark ? (
                    <div className="mypage-drag-overlay">
                      <div className="mypage-bookmark-title">{activeDragBookmark.title}</div>
                      <div className="mypage-bookmark-meta">
                        <span>{new Date(activeDragBookmark.created_at).toLocaleDateString()}</span>
                        <span>{activeDragBookmark.num_papers} papers</span>
                      </div>
                    </div>
                  ) : null}
                </DragOverlay>
              </DndContext>
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
            <div className="mypage-report-scroll" ref={reportScrollRef}>
              {/* Highlight indicator */}
              {highlightTerms.length > 0 && (
                <div className="mypage-highlight-bar">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                  <span>Evidence highlighted</span>
                  <button className="mypage-highlight-clear" onClick={() => setHighlightTerms([])}>Clear</button>
                </div>
              )}
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

              {/* Report markdown with highlight support */}
              {bookmarkDetail.report_markdown && (
                <div className="mypage-report-section">
                  <h3 className="mypage-report-section-title">Report</h3>
                  <div className="mypage-report-content">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={(highlightTerms.length > 0 || userHighlights.length > 0) ? {
                        p: ({ children }) => {
                          let c: React.ReactNode = children;
                          if (userHighlights.length > 0) c = applyUserHighlights(c);
                          if (highlightTerms.length > 0) c = highlightChildren(c);
                          return <p>{c}</p>;
                        },
                        li: ({ children }) => {
                          let c: React.ReactNode = children;
                          if (userHighlights.length > 0) c = applyUserHighlights(c);
                          if (highlightTerms.length > 0) c = highlightChildren(c);
                          return <li>{c}</li>;
                        },
                        td: ({ children }) => {
                          let c: React.ReactNode = children;
                          if (userHighlights.length > 0) c = applyUserHighlights(c);
                          if (highlightTerms.length > 0) c = highlightChildren(c);
                          return <td>{c}</td>;
                        },
                      } : undefined}
                    >
                      {bookmarkDetail.report_markdown}
                    </ReactMarkdown>
                  </div>
                </div>
              )}

              {/* ── Notes & Highlights ── */}
              <div className={`mypage-notes-section ${notesCollapsed ? 'collapsed' : ''}`}>
                <div className="mypage-notes-header" onClick={() => setNotesCollapsed(!notesCollapsed)}>
                  <svg className="mypage-notes-chevron" viewBox="0 0 16 16" fill="currentColor" width="10" height="10">
                    <path d="M6 4l4 4-4 4z" />
                  </svg>
                  <span>Notes & Highlights</span>
                  {notesSaving && <span className="mypage-notes-saving">Saving...</span>}
                  {saveStatus === 'saved' && <span className="mypage-notes-saved">Saved</span>}
                  {saveStatus === 'error' && <span className="mypage-notes-error">Save failed</span>}
                  {userHighlights.length > 0 && (
                    <span className="mypage-notes-badge">{userHighlights.length}</span>
                  )}
                  <button
                    className="mypage-auto-highlight-btn"
                    onClick={(e) => { e.stopPropagation(); handleAutoHighlight(); }}
                    disabled={autoHighlighting || !bookmarkDetail?.report_markdown}
                    title="LLM 기반 자동 하이라이트"
                  >
                    {autoHighlighting ? (
                      <>
                        <svg className="mypage-auto-highlight-spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                          <path d="M12 2v4m0 12v4m-7.07-2.93l2.83-2.83m8.48-8.48l2.83-2.83M2 12h4m12 0h4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83" />
                        </svg>
                        Analyzing...
                      </>
                    ) : (
                      <>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                          <path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                        </svg>
                        Auto
                      </>
                    )}
                  </button>
                </div>
                {!notesCollapsed && (
                  <div className="mypage-notes-body">
                    <textarea
                      className="mypage-notes-textarea"
                      value={notesText}
                      onChange={(e) => setNotesText(e.target.value)}
                      onBlur={handleSaveNotes}
                      placeholder="Write your notes here (Markdown supported)..."
                      rows={4}
                    />
                    {userHighlights.length > 0 && (
                      <div className="mypage-highlights-list">
                        <div className="mypage-highlights-title">Highlights ({userHighlights.length})</div>
                        {userHighlights.map(hl => (
                          <div key={hl.id} className="mypage-highlight-item">
                            <div className="mypage-highlight-item-content">
                              <mark className="mypage-highlight-item-text" style={hl.color && hl.color !== '#a5b4fc' ? { background: `${hl.color}44`, borderLeftColor: hl.color } : undefined}>{hl.text.length > 100 ? hl.text.slice(0, 100) + '...' : hl.text}</mark>
                              {hl.memo && <div className="mypage-highlight-item-memo">{hl.memo}</div>}
                            </div>
                            <button className="mypage-highlight-remove" onClick={() => handleRemoveHighlight(hl.id)} title="Remove">✕</button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>

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
                            return <p>{processCitationChildren(children, msg.sources, msg.content)}</p>;
                          },
                          li: ({ children }) => {
                            return <li>{processCitationChildren(children, msg.sources, msg.content)}</li>;
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
                                onClick={() => handleCitationClick(source, msg.content, source.ref)}>
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

      {/* Floating selection toolbar for highlighting / memo */}
      {selectionToolbar && (
        <div
          className={`mypage-selection-toolbar ${memoMode ? 'memo-mode' : ''}`}
          style={{ left: selectionToolbar.x, top: selectionToolbar.y }}
        >
          {memoMode ? (
            <div className="mypage-memo-form">
              <div className="mypage-memo-preview">
                {selectionToolbar.text.length > 60 ? selectionToolbar.text.slice(0, 60) + '...' : selectionToolbar.text}
              </div>
              <input
                className="mypage-memo-input"
                value={memoInput}
                onChange={(e) => setMemoInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSaveMemo();
                  if (e.key === 'Escape') handleCancelMemo();
                }}
                placeholder="Write a memo..."
                autoFocus
              />
              <div className="mypage-memo-actions">
                <button className="mypage-memo-save-btn" onClick={handleSaveMemo}>Save</button>
                <button className="mypage-memo-cancel-btn" onClick={handleCancelMemo}>Cancel</button>
              </div>
            </div>
          ) : (
            <>
              <button className="mypage-selection-toolbar-btn" onClick={handleAddHighlight}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                  <path d="M12 20h9" /><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                </svg>
                Highlight
              </button>
              <div className="mypage-selection-toolbar-divider" />
              <button className="mypage-selection-toolbar-btn" onClick={handleStartMemo}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
                Memo
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default MyPage;
