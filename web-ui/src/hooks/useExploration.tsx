import { useState, useCallback, useEffect, useRef } from 'react';
import {
  generateCitationTree,
  getCitationTree,
  deleteCitationTree,
} from '../api/client';
import type { Bookmark, CitationTreeData } from '../components/mypage/types';

export function useExploration(
  selectedBookmark: Bookmark | null,
  setBookmarks: React.Dispatch<React.SetStateAction<Bookmark[]>>,
) {
  const [citationTreeData, setCitationTreeData] = useState<CitationTreeData | null>(null);
  const [citationTreeLoading, setCitationTreeLoading] = useState(false);
  const [citationTreeError, setCitationTreeError] = useState<string | null>(null);

  // Track which bookmark the current data belongs to
  const dataBookmarkIdRef = useRef<string | null>(null);

  // Reset when bookmark changes
  useEffect(() => {
    const newId = selectedBookmark?.id || null;
    if (dataBookmarkIdRef.current && dataBookmarkIdRef.current !== newId) {
      setCitationTreeData(null);
      setCitationTreeError(null);
      dataBookmarkIdRef.current = newId;
    } else if (!dataBookmarkIdRef.current) {
      dataBookmarkIdRef.current = newId;
    }
  }, [selectedBookmark?.id]);

  const handleGenerateCitationTree = useCallback(async (bookmarkId: string) => {
    if (citationTreeLoading) return;
    setCitationTreeLoading(true);
    setCitationTreeError(null);
    dataBookmarkIdRef.current = bookmarkId;
    try {
      const result = await generateCitationTree(bookmarkId);
      setCitationTreeData(result.citation_tree);
      setBookmarks(prev => prev.map(bm =>
        bm.id === bookmarkId ? { ...bm, has_citation_tree: true } : bm
      ));
    } catch (error: any) {
      const msg = error?.response?.data?.detail || 'Failed to generate citation tree';
      setCitationTreeError(msg);
    } finally {
      setCitationTreeLoading(false);
    }
  }, [citationTreeLoading, setBookmarks]);

  const handleLoadCitationTree = useCallback(async (bookmarkId: string) => {
    setCitationTreeLoading(true);
    setCitationTreeError(null);
    dataBookmarkIdRef.current = bookmarkId;
    try {
      const data = await getCitationTree(bookmarkId);
      setCitationTreeData(data);
    } catch (error: any) {
      const msg = error?.response?.data?.detail || 'Failed to load citation tree';
      setCitationTreeError(msg);
    } finally {
      setCitationTreeLoading(false);
    }
  }, []);

  const handleDeleteCitationTree = useCallback(async () => {
    const id = selectedBookmark?.id || dataBookmarkIdRef.current;
    if (!id) return;
    try {
      await deleteCitationTree(id);
      setCitationTreeData(null);
      setBookmarks(prev => prev.map(bm =>
        bm.id === id ? { ...bm, has_citation_tree: false } : bm
      ));
    } catch (error) {
      console.error('Failed to delete citation tree:', error);
    }
  }, [selectedBookmark, setBookmarks]);

  return {
    citationTreeData, citationTreeLoading, citationTreeError,
    handleGenerateCitationTree, handleLoadCitationTree, handleDeleteCitationTree,
  };
}
