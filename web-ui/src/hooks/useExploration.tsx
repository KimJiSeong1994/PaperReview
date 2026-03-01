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
  bookmarkDetail: any,
) {
  const [citationTreeData, setCitationTreeData] = useState<CitationTreeData | null>(null);
  const [citationTreeLoading, setCitationTreeLoading] = useState(false);
  const [citationTreeError, setCitationTreeError] = useState<string | null>(null);
  const [citationTreeWarning, setCitationTreeWarning] = useState<string | null>(null);

  // Track which bookmark the current data belongs to
  const dataBookmarkIdRef = useRef<string | null>(null);

  // Extract citation tree from bookmark detail when it loads.
  // This eliminates the separate GET request and provides instant data on bookmark select.
  useEffect(() => {
    const newId = selectedBookmark?.id || null;
    const prevId = dataBookmarkIdRef.current;

    // Bookmark changed — reset state
    if (prevId && prevId !== newId) {
      setCitationTreeData(null);
      setCitationTreeError(null);
      setCitationTreeWarning(null);
    }
    dataBookmarkIdRef.current = newId;

    // Extract citation_tree from bookmarkDetail if available
    if (bookmarkDetail && newId && bookmarkDetail.id === newId) {
      const tree = bookmarkDetail.citation_tree as CitationTreeData | undefined;
      if (tree && tree.nodes) {
        setCitationTreeData(tree);
        // Reconstruct warning from skipped_papers
        const skipped = tree.skipped_papers || [];
        if (skipped.length > 0) {
          if (!tree.nodes.length) {
            const titles = skipped.slice(0, 3).join(', ') + (skipped.length > 3 ? ` 외 ${skipped.length - 3}편` : '');
            setCitationTreeWarning(`Semantic Scholar에서 논문을 찾을 수 없습니다: ${titles}`);
          } else {
            setCitationTreeWarning(`${skipped.length}편의 논문을 찾지 못해 제외되었습니다.`);
          }
        } else {
          setCitationTreeWarning(null);
        }
      } else if (!citationTreeLoading) {
        // Detail loaded but no tree — ensure clean state
        setCitationTreeData(null);
        setCitationTreeWarning(null);
      }
    }
  }, [selectedBookmark?.id, bookmarkDetail]);

  const handleGenerateCitationTree = useCallback(async (bookmarkId: string) => {
    if (citationTreeLoading) return;
    setCitationTreeLoading(true);
    setCitationTreeError(null);
    setCitationTreeWarning(null);
    dataBookmarkIdRef.current = bookmarkId;
    try {
      const result = await generateCitationTree(bookmarkId);
      setCitationTreeData(result.citation_tree);
      setCitationTreeWarning(result.warning || null);
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

  // Keep handleLoadCitationTree for manual reload if needed
  const handleLoadCitationTree = useCallback(async (bookmarkId: string) => {
    setCitationTreeLoading(true);
    setCitationTreeError(null);
    setCitationTreeWarning(null);
    dataBookmarkIdRef.current = bookmarkId;
    try {
      const data = await getCitationTree(bookmarkId);
      setCitationTreeData(data);
      const skipped = data?.skipped_papers || [];
      if (skipped.length > 0) {
        if (!data?.nodes?.length) {
          const titles = skipped.slice(0, 3).join(', ') + (skipped.length > 3 ? ` 외 ${skipped.length - 3}편` : '');
          setCitationTreeWarning(`Semantic Scholar에서 논문을 찾을 수 없습니다: ${titles}`);
        } else {
          setCitationTreeWarning(`${skipped.length}편의 논문을 찾지 못해 제외되었습니다.`);
        }
      }
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
      setCitationTreeWarning(null);
      setBookmarks(prev => prev.map(bm =>
        bm.id === id ? { ...bm, has_citation_tree: false } : bm
      ));
    } catch (error) {
      console.error('Failed to delete citation tree:', error);
    }
  }, [selectedBookmark, setBookmarks]);

  return {
    citationTreeData, citationTreeLoading, citationTreeError, citationTreeWarning,
    handleGenerateCitationTree, handleLoadCitationTree, handleDeleteCitationTree,
  };
}
