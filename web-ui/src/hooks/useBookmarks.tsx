import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
  useSensor, useSensors, PointerSensor,
  type DragStartEvent, type DragEndEvent, type DragOverEvent,
} from '@dnd-kit/core';
import {
  getBookmarks, getBookmarkDetail, deleteBookmark, updateBookmarkTopic,
  bulkDeleteBookmarks, bulkMoveBookmarks, buildLightRAG, getLightRAGStatus,
} from '../api/client';
import type { HighlightItem } from '../api/client';
import type { Bookmark } from '../components/mypage/types';

export interface BookmarkSelectResult {
  detail: any;
  notes: string;
  highlights: HighlightItem[];
}

export function useBookmarks() {
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([]);
  const [selectedBookmark, setSelectedBookmark] = useState<Bookmark | null>(null);
  const [bookmarkDetail, setBookmarkDetail] = useState<any>(null);
  const [loadingBookmarks, setLoadingBookmarks] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // Bulk selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Search/filter
  const [searchQuery, setSearchQuery] = useState('');
  const [allNotesMode, setAllNotesMode] = useState(false);

  // Topic-scoped chat
  const [chatTopicFilter, setChatTopicFilter] = useState<string>('all');

  // Accordion + topic management
  const [topicAccordionOpen, setTopicAccordionOpen] = useState<Record<string, boolean>>({});
  const [newTopicInput, setNewTopicInput] = useState('');
  const [showNewTopicInput, setShowNewTopicInput] = useState(false);
  const [emptyTopics, setEmptyTopics] = useState<Set<string>>(new Set());

  // DnD
  const [activeDragId, setActiveDragId] = useState<string | null>(null);
  const [overTopicId, setOverTopicId] = useState<string | null>(null);
  const autoExpandTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // KG
  const [kgBuilding, setKgBuilding] = useState(false);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  );

  // ── Computed ──

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

  const topicGroups = useMemo(() => {
    const groups: Record<string, Bookmark[]> = {};
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

  const chatBookmarkIds = useMemo(() => {
    if (chatTopicFilter === 'all') return [];
    return bookmarks
      .filter(bm => (bm.topic || 'General') === chatTopicFilter)
      .map(bm => bm.id);
  }, [bookmarks, chatTopicFilter]);

  const activeDragBookmark = useMemo(() =>
    activeDragId ? bookmarks.find(bm => bm.id === activeDragId) || null : null
  , [activeDragId, bookmarks]);

  // ── Effects ──

  useEffect(() => { loadBookmarks(); }, []);

  useEffect(() => {
    setTopicAccordionOpen(prev => {
      const next = { ...prev };
      allTopics.forEach(topic => {
        if (!(topic in next)) next[topic] = true;
      });
      return next;
    });
  }, [allTopics]);

  // ── Handlers ──

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

  const handleSelectBookmark = useCallback(async (bookmark: Bookmark): Promise<BookmarkSelectResult | null> => {
    setSelectedBookmark(bookmark);
    setLoadingDetail(true);
    try {
      const detail = await getBookmarkDetail(bookmark.id);
      setBookmarkDetail(detail);
      return {
        detail,
        notes: detail.notes || '',
        highlights: detail.highlights || [],
      };
    } catch (error: any) {
      console.error('Failed to load bookmark detail:', error);
      return null;
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  const handleDeleteBookmark = useCallback(async (bookmarkId: string) => {
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
  }, [bookmarks, selectedBookmark]);

  const handleMoveBookmark = useCallback(async (bookmarkId: string, newTopic: string) => {
    try {
      await updateBookmarkTopic(bookmarkId, newTopic);
      setBookmarks(prev => prev.map(bm =>
        bm.id === bookmarkId ? { ...bm, topic: newTopic } : bm
      ));
      setEmptyTopics(prev => {
        const next = new Set(prev);
        next.delete(newTopic);
        return next;
      });
    } catch (error: any) {
      console.error('Failed to move bookmark:', error);
    }
  }, []);

  const handleAddTopic = useCallback(() => {
    const trimmed = newTopicInput.trim();
    if (!trimmed) return;
    setEmptyTopics(prev => new Set(prev).add(trimmed));
    setTopicAccordionOpen(prev => ({ ...prev, [trimmed]: true }));
    setNewTopicInput('');
    setShowNewTopicInput(false);
  }, [newTopicInput]);

  const toggleTopicAccordion = useCallback((topic: string) => {
    setTopicAccordionOpen(prev => ({ ...prev, [topic]: !prev[topic] }));
  }, []);

  // Bulk selection
  const handleToggleSelection = useCallback((bookmarkId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(bookmarkId)) next.delete(bookmarkId);
      else next.add(bookmarkId);
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    setSelectedIds(new Set(filteredBookmarks.map(bm => bm.id)));
  }, [filteredBookmarks]);

  const handleDeselectAll = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const handleBulkDelete = useCallback(async () => {
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
  }, [selectedIds, selectedBookmark]);

  const handleBulkMove = useCallback(async (topic: string) => {
    try {
      await bulkMoveBookmarks(Array.from(selectedIds), topic);
      setBookmarks(prev => prev.map(bm =>
        selectedIds.has(bm.id) ? { ...bm, topic } : bm
      ));
      setSelectedIds(new Set());
    } catch (error: any) {
      console.error('Failed to bulk move:', error);
    }
  }, [selectedIds]);

  // DnD handlers
  const handleDragStart = useCallback((event: DragStartEvent) => {
    setActiveDragId(event.active.id as string);
  }, []);

  const handleDragOver = useCallback((event: DragOverEvent) => {
    const overId = event.over?.id as string | undefined;
    let topicId: string | null = overId?.startsWith('topic:') ? overId : null;

    setOverTopicId(topicId);

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
  }, [handleMoveBookmark]);

  // KG
  const handleBuildKG = useCallback(async () => {
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
  }, [kgBuilding]);

  // Export
  const handleExportBibTeX = useCallback(() => {
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
  }, [bookmarkDetail]);

  const handleExportReport = useCallback(() => {
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
  }, [bookmarkDetail]);

  return {
    // State
    bookmarks, setBookmarks,
    selectedBookmark, bookmarkDetail,
    loadingBookmarks, loadingDetail,
    selectedIds,
    searchQuery, setSearchQuery,
    allNotesMode, setAllNotesMode,
    chatTopicFilter, setChatTopicFilter,
    topicAccordionOpen, toggleTopicAccordion,
    showNewTopicInput, setShowNewTopicInput,
    newTopicInput, setNewTopicInput,
    // Computed
    filteredBookmarks, topicGroups, allTopics, chatBookmarkIds,
    // DnD
    activeDragId, overTopicId, activeDragBookmark, sensors,
    handleDragStart, handleDragOver, handleDragEnd,
    // KG
    kgBuilding, handleBuildKG,
    // Handlers
    handleSelectBookmark, handleDeleteBookmark, handleMoveBookmark,
    handleAddTopic, handleToggleSelection,
    handleSelectAll, handleDeselectAll,
    handleBulkDelete, handleBulkMove,
    handleExportBibTeX, handleExportReport,
  };
}
