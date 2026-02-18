import { useState, useEffect, useRef, useMemo, cloneElement, isValidElement } from 'react';
import type React from 'react';
import { updateBookmarkNotes, autoHighlightBookmark } from '../api/client';
import type { HighlightItem } from '../api/client';
import type { Bookmark } from '../components/mypage/types';
import { getTone } from '../components/mypage/types';

export function useHighlights(
  selectedBookmark: Bookmark | null,
  bookmarkDetail: any,
  setBookmarks: React.Dispatch<React.SetStateAction<Bookmark[]>>,
  reportScrollRef: React.RefObject<HTMLDivElement | null>,
) {
  const [notesText, setNotesText] = useState('');
  const [notesSaving, setNotesSaving] = useState(false);
  const [notesCollapsed, setNotesCollapsed] = useState(true);
  const [papersCollapsed, setPapersCollapsed] = useState(true);
  const [userHighlights, setUserHighlights] = useState<HighlightItem[]>([]);
  const [selectionToolbar, setSelectionToolbar] = useState<{ x: number; y: number; text: string } | null>(null);
  const [memoMode, setMemoMode] = useState(false);
  const [memoInput, setMemoInput] = useState('');
  const memoModeRef = useRef(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'error'>('idle');
  const [autoHighlighting, setAutoHighlighting] = useState(false);
  const [expandedHighlightId, setExpandedHighlightId] = useState<string | null>(null);
  const [highlightPopover, setHighlightPopover] = useState<{ hl: HighlightItem } | null>(null);
  const [popoverPos, setPopoverPos] = useState<{ x: number; y: number } | null>(null);

  const saveStatusTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedNotesRef = useRef('');

  const sortedHighlights = useMemo(() =>
    [...userHighlights].sort((a, b) => (b.significance ?? 3) - (a.significance ?? 3)),
    [userHighlights],
  );

  // ── Effects ──

  // Popover positioning
  useEffect(() => {
    if (!highlightPopover) { setPopoverPos(null); return; }
    const hlId = highlightPopover.hl.id;
    const update = () => {
      const anchor = reportScrollRef.current?.querySelector(`[data-hl-id="${hlId}"]`);
      if (!anchor) { setPopoverPos(null); return; }
      const rect = anchor.getBoundingClientRect();
      const scrollEl = reportScrollRef.current;
      if (scrollEl) {
        const container = scrollEl.getBoundingClientRect();
        if (rect.bottom < container.top || rect.top > container.bottom) {
          setHighlightPopover(null);
          return;
        }
      }
      setPopoverPos({ x: rect.left + rect.width / 2, y: rect.bottom + 6 });
    };
    const raf = requestAnimationFrame(update);
    const scrollEl = reportScrollRef.current;
    scrollEl?.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      scrollEl?.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
    };
  }, [highlightPopover, reportScrollRef]);

  // Keep memoModeRef in sync
  useEffect(() => { memoModeRef.current = memoMode; }, [memoMode]);

  // Cleanup timer on unmount
  useEffect(() => () => {
    if (saveStatusTimerRef.current) clearTimeout(saveStatusTimerRef.current);
  }, []);

  // Selection toolbar: show on text select in report area
  useEffect(() => {
    const reportEl = reportScrollRef.current;
    if (!reportEl || !bookmarkDetail) return;
    const handleMouseUp = () => {
      if (memoModeRef.current) return;
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
      if (!target.closest('.mypage-hl-popover') && !target.closest('.mypage-user-highlight')) {
        setHighlightPopover(null);
      }
    };
    reportEl.addEventListener('mouseup', handleMouseUp);
    document.addEventListener('mousedown', handleMouseDown);
    return () => {
      reportEl.removeEventListener('mouseup', handleMouseUp);
      document.removeEventListener('mousedown', handleMouseDown);
    };
  }, [bookmarkDetail, reportScrollRef]);

  // ── Helpers ──

  const showSaveStatus = (status: 'saved' | 'error') => {
    if (saveStatusTimerRef.current) clearTimeout(saveStatusTimerRef.current);
    setSaveStatus(status);
    saveStatusTimerRef.current = setTimeout(() => setSaveStatus('idle'), 2000);
  };

  /** Initialize state when a bookmark is loaded. Called by the parent orchestrator. */
  const initFromDetail = (notes: string, highlights: HighlightItem[]) => {
    setNotesText(notes);
    lastSavedNotesRef.current = notes;
    setUserHighlights(highlights);
    setNotesCollapsed(!notes.trim() && !highlights.length);
    setSelectionToolbar(null);
  };

  // ── Handlers ──

  const handleSaveNotes = async () => {
    if (!selectedBookmark) return;
    if (notesText === lastSavedNotesRef.current) return;
    setNotesSaving(true);
    try {
      await updateBookmarkNotes(selectedBookmark.id, notesText);
      lastSavedNotesRef.current = notesText;
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
    if (userHighlights.some(hl => hl.text === text)) {
      setSelectionToolbar(null);
      window.getSelection()?.removeAllRanges();
      return;
    }

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
      const result = await autoHighlightBookmark(selectedBookmark.id) as any;
      const addedCount = result.added_count ?? 0;
      setUserHighlights(result.highlights);
      if (addedCount > 0) {
        setNotesCollapsed(false);
        setBookmarks(prev => prev.map(bm =>
          bm.id === selectedBookmark.id ? { ...bm, has_notes: true } : bm
        ));
      }
      if (addedCount === 0) {
        setSaveStatus('idle');
        alert('추출 가능한 새로운 하이라이트가 없습니다.');
      } else {
        showSaveStatus('saved');
      }
    } catch (error) {
      console.error('Auto highlight failed:', error);
      showSaveStatus('error');
    } finally {
      setAutoHighlighting(false);
    }
  };

  const handleClearAllHighlights = async () => {
    if (!selectedBookmark || userHighlights.length === 0) return;
    if (!confirm(`${userHighlights.length}개의 하이라이트를 모두 삭제하시겠습니까?`)) return;
    const backup = userHighlights;
    setUserHighlights([]);
    try {
      await updateBookmarkNotes(selectedBookmark.id, undefined, []);
      setBookmarks(prev => prev.map(bm =>
        bm.id === selectedBookmark.id
          ? { ...bm, has_notes: !!notesText.trim() }
          : bm
      ));
      showSaveStatus('saved');
    } catch (error) {
      console.error('Failed to clear highlights:', error);
      setUserHighlights(backup);
      showSaveStatus('error');
    }
  };

  // Apply user highlights to rendered content (wraps text in <mark>)
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
            const hlRef = hl;
            nextResult.push(
              <mark key={`hl-${hl.id}-${idx}`}
                className={`mypage-user-highlight${hl.memo ? ' has-memo' : ''}`}
                style={hl.color && hl.color !== '#a5b4fc' ? { background: `${hl.color}33`, borderBottomColor: `${hl.color}aa` } : undefined}
                title={hl.memo || undefined}
                data-hl-id={hl.id}
                onMouseDown={(e: React.MouseEvent) => {
                  if (e.button !== 0) return;
                  e.preventDefault();
                  e.stopPropagation();
                  setHighlightPopover(prev => prev?.hl.id === hlRef.id ? null : { hl: hlRef });
                }}
              >{hl.text}</mark>
            );
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

  return {
    // State
    notesText, setNotesText,
    notesSaving, notesCollapsed, setNotesCollapsed,
    papersCollapsed, setPapersCollapsed,
    userHighlights,
    selectionToolbar,
    memoMode, memoInput, setMemoInput,
    saveStatus, autoHighlighting,
    expandedHighlightId, setExpandedHighlightId,
    highlightPopover, popoverPos,
    // Computed
    sortedHighlights,
    // Init
    initFromDetail,
    // Handlers
    handleSaveNotes, handleAddHighlight, handleRemoveHighlight,
    handleStartMemo, handleSaveMemo, handleCancelMemo,
    handleAutoHighlight, handleClearAllHighlights,
    // Utilities
    applyUserHighlights,
    getTone,
  };
}
