import { useState, useRef, useEffect, useCallback } from 'react';
import './MyPage.css';
import { useBookmarks } from '../hooks/useBookmarks';
import { useHighlights } from '../hooks/useHighlights';
import { useExploration } from '../hooks/useExploration';
import { useChat } from '../hooks/useChat';
import { createShareLink, revokeShareLink } from '../api/client';
import type { ShareInfo } from '../api/client';
import type { Bookmark } from './mypage/types';
import BookmarkSidebar from './mypage/BookmarkSidebar';
import ReportViewer from './mypage/ReportViewer';
import ChatPanel from './mypage/ChatPanel';

interface MyPageProps {
  onBack: () => void;
}

function MyPage({ onBack }: MyPageProps) {
  const reportScrollRef = useRef<HTMLDivElement>(null);

  // ── Share state ──
  const [shareInfo, setShareInfo] = useState<ShareInfo | null>(null);
  const [shareLoading, setShareLoading] = useState(false);

  // ── Hooks ──
  const bm = useBookmarks();
  const hl = useHighlights(bm.selectedBookmark, bm.bookmarkDetail, bm.setBookmarks, reportScrollRef);
  const exploration = useExploration(bm.selectedBookmark, bm.setBookmarks);

  // Wrap handleSelectBookmark to also init highlights
  const selectBookmarkAndInitHighlights = useCallback(async (bookmark: Bookmark) => {
    const result = await bm.handleSelectBookmark(bookmark);
    if (result) {
      hl.initFromDetail(result.notes, result.highlights);
    }
    return result;
  }, [bm.handleSelectBookmark, hl.initFromDetail]);

  const chat = useChat(bm.bookmarks, bm.chatBookmarkIds, selectBookmarkAndInitHighlights);

  // Direct bookmark selection (clears chat highlight terms)
  const handleSelectBookmarkDirect = useCallback(async (bookmark: Bookmark) => {
    chat.setHighlightTerms([]);
    await selectBookmarkAndInitHighlights(bookmark);
  }, [selectBookmarkAndInitHighlights, chat.setHighlightTerms]);

  // Auto-load citation tree when selecting a bookmark that has one
  useEffect(() => {
    if (bm.selectedBookmark?.has_citation_tree && !exploration.citationTreeData && !exploration.citationTreeLoading) {
      exploration.handleLoadCitationTree(bm.selectedBookmark.id);
    }
  }, [bm.selectedBookmark?.id]);

  // Sync share info when bookmark detail loads
  useEffect(() => {
    if (bm.bookmarkDetail?.share) {
      setShareInfo(bm.bookmarkDetail.share);
    } else {
      setShareInfo(null);
    }
  }, [bm.bookmarkDetail]);

  const handleCreateShare = useCallback(async () => {
    if (!bm.selectedBookmark || shareLoading) return;
    setShareLoading(true);
    try {
      const info = await createShareLink(bm.selectedBookmark.id);
      setShareInfo(info);
      bm.setBookmarkDetail((prev: any) => prev ? { ...prev, share: info } : prev);
      bm.setBookmarks((prev: Bookmark[]) => prev.map(b =>
        b.id === bm.selectedBookmark!.id ? { ...b, has_share: true } : b
      ));
    } catch (error) {
      console.error('Failed to create share link:', error);
    } finally {
      setShareLoading(false);
    }
  }, [bm.selectedBookmark, shareLoading, bm.setBookmarkDetail, bm.setBookmarks]);

  const handleRevokeShare = useCallback(async () => {
    if (!bm.selectedBookmark || shareLoading) return;
    setShareLoading(true);
    try {
      await revokeShareLink(bm.selectedBookmark.id);
      setShareInfo(null);
      bm.setBookmarkDetail((prev: any) => {
        if (!prev) return prev;
        const { share: _, ...rest } = prev;
        return rest;
      });
      bm.setBookmarks((prev: Bookmark[]) => prev.map(b =>
        b.id === bm.selectedBookmark!.id ? { ...b, has_share: false } : b
      ));
    } catch (error) {
      console.error('Failed to revoke share link:', error);
    } finally {
      setShareLoading(false);
    }
  }, [bm.selectedBookmark, shareLoading, bm.setBookmarkDetail, bm.setBookmarks]);

  // Scroll to first highlight after render
  useEffect(() => {
    if (chat.scrollToHighlight && chat.highlightTerms.length > 0 && bm.bookmarkDetail && !bm.loadingDetail) {
      const timer = setTimeout(() => {
        const firstHighlight = reportScrollRef.current?.querySelector('.mypage-highlight');
        if (firstHighlight) {
          firstHighlight.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        chat.setScrollToHighlight(false);
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [chat.scrollToHighlight, chat.highlightTerms, bm.bookmarkDetail, bm.loadingDetail]);

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
            <button className="mypage-nav-btn" onClick={bm.handleBuildKG} disabled={bm.kgBuilding}
              title="Build Knowledge Graph">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px' }}>
                <circle cx="12" cy="5" r="3" /><circle cx="5" cy="19" r="3" /><circle cx="19" cy="19" r="3" />
                <line x1="12" y1="8" x2="5" y2="16" /><line x1="12" y1="8" x2="19" y2="16" />
              </svg>
              {bm.kgBuilding ? 'Building...' : 'Build KG'}
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
        <BookmarkSidebar
          bookmarks={bm.bookmarks}
          filteredBookmarks={bm.filteredBookmarks}
          topicGroups={bm.topicGroups}
          allTopics={bm.allTopics}
          selectedBookmark={bm.selectedBookmark}
          selectedIds={bm.selectedIds}
          loadingBookmarks={bm.loadingBookmarks}
          searchQuery={bm.searchQuery}
          setSearchQuery={bm.setSearchQuery}
          allNotesMode={bm.allNotesMode}
          setAllNotesMode={bm.setAllNotesMode}
          topicAccordionOpen={bm.topicAccordionOpen}
          toggleTopicAccordion={bm.toggleTopicAccordion}
          showNewTopicInput={bm.showNewTopicInput}
          setShowNewTopicInput={bm.setShowNewTopicInput}
          newTopicInput={bm.newTopicInput}
          setNewTopicInput={bm.setNewTopicInput}
          overTopicId={bm.overTopicId}
          activeDragBookmark={bm.activeDragBookmark}
          sensors={bm.sensors}
          onDragStart={bm.handleDragStart}
          onDragOver={bm.handleDragOver}
          onDragEnd={bm.handleDragEnd}
          onSelect={handleSelectBookmarkDirect}
          onDelete={bm.handleDeleteBookmark}
          onToggleSelection={bm.handleToggleSelection}
          onSelectAll={bm.handleSelectAll}
          onDeselectAll={bm.handleDeselectAll}
          onBulkDelete={bm.handleBulkDelete}
          onBulkMove={bm.handleBulkMove}
          onAddTopic={bm.handleAddTopic}
        />

        <ReportViewer
          bookmarkDetail={bm.bookmarkDetail}
          loadingDetail={bm.loadingDetail}
          hasSelectedBookmark={!!bm.selectedBookmark}
          reportScrollRef={reportScrollRef}
          highlightTerms={chat.highlightTerms}
          setHighlightTerms={chat.setHighlightTerms}
          highlightChildren={chat.highlightChildren}
          userHighlights={hl.userHighlights}
          sortedHighlights={hl.sortedHighlights}
          applyUserHighlights={hl.applyUserHighlights}
          expandedHighlightId={hl.expandedHighlightId}
          setExpandedHighlightId={hl.setExpandedHighlightId}
          highlightPopover={hl.highlightPopover}
          popoverPos={hl.popoverPos}
          setHighlightPopover={() => {}}
          notesText={hl.notesText}
          setNotesText={hl.setNotesText}
          notesSaving={hl.notesSaving}
          notesCollapsed={hl.notesCollapsed}
          setNotesCollapsed={hl.setNotesCollapsed}
          saveStatus={hl.saveStatus}
          autoHighlighting={hl.autoHighlighting}
          onSaveNotes={hl.handleSaveNotes}
          onAutoHighlight={hl.handleAutoHighlight}
          onClearAllHighlights={hl.handleClearAllHighlights}
          onRemoveHighlight={hl.handleRemoveHighlight}
          papersCollapsed={hl.papersCollapsed}
          setPapersCollapsed={hl.setPapersCollapsed}
          onExportBibTeX={bm.handleExportBibTeX}
          onExportReport={bm.handleExportReport}
          selectionToolbar={hl.selectionToolbar}
          memoMode={hl.memoMode}
          memoInput={hl.memoInput}
          setMemoInput={hl.setMemoInput}
          onAddHighlight={hl.handleAddHighlight}
          onStartMemo={hl.handleStartMemo}
          onSaveMemo={hl.handleSaveMemo}
          onCancelMemo={hl.handleCancelMemo}
          citationTreeData={exploration.citationTreeData}
          citationTreeLoading={exploration.citationTreeLoading}
          citationTreeError={exploration.citationTreeError}
          citationTreeWarning={exploration.citationTreeWarning}
          onGenerateCitationTree={() => {
            if (bm.selectedBookmark) {
              exploration.handleGenerateCitationTree(bm.selectedBookmark.id);
            }
          }}
          onDeleteCitationTree={exploration.handleDeleteCitationTree}
          onRenameBookmark={(title: string) => {
            if (bm.selectedBookmark) {
              bm.handleRenameBookmark(bm.selectedBookmark.id, title);
            }
          }}
          shareInfo={shareInfo}
          shareLoading={shareLoading}
          onCreateShare={handleCreateShare}
          onRevokeShare={handleRevokeShare}
        />

        <ChatPanel
          messages={chat.messages}
          inputValue={chat.inputValue}
          setInputValue={chat.setInputValue}
          isStreaming={chat.isStreaming}
          streamingContent={chat.streamingContent}
          chatEndRef={chat.chatEndRef}
          chatTopicFilter={bm.chatTopicFilter}
          setChatTopicFilter={bm.setChatTopicFilter}
          allTopics={bm.allTopics}
          selectedCount={bm.selectedIds.size}
          onSendMessage={() => chat.handleSendMessage()}
          onKeyDown={chat.handleKeyDown}
          onClearChat={chat.clearChat}
          processCitationChildren={chat.processCitationChildren}
          handleCitationClick={chat.handleCitationClick}
        />
      </div>
    </div>
  );
}

export default MyPage;
