import { useState, useRef, useEffect, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import './MyPage.css';
import { useBookmarks } from '../hooks/useBookmarks';
import type { BookmarkDetail } from '../hooks/useBookmarks';
import { useHighlights } from '../hooks/useHighlights';
import { useExploration } from '../hooks/useExploration';
import { useChat } from '../hooks/useChat';
import { useCurriculum } from '../hooks/useCurriculum';
import { createShareLink, revokeShareLink } from '../api/client';
import type { ShareInfo } from '../api/client';
import type { Bookmark } from './mypage/types';
import BookmarkSidebar from './mypage/BookmarkSidebar';
import ReportViewer from './mypage/ReportViewer';
import ChatPanel from './mypage/ChatPanel';
import CourseSidebar from './curriculum/CourseSidebar';
import ModuleView from './curriculum/ModuleView';
import CurriculumDetailPanel from './curriculum/CurriculumDetailPanel';
import PaperViewerPanel from './mypage/PaperViewerPanel';
import './CurriculumPage.css';

interface MyPageProps {
  onBack: () => void;
}

type MyPageTab = 'bookmarks' | 'curriculum' | 'papers';

function MyPage({ onBack }: MyPageProps) {
  const reportScrollRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const [activeTab, setActiveTab] = useState<MyPageTab>('bookmarks');

  // Direct paper view from search results (via router state)
  const [directPaper, setDirectPaper] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    const state = location.state as { viewPaper?: Record<string, unknown> } | null;
    if (state?.viewPaper) {
      setDirectPaper(state.viewPaper);
      setActiveTab('papers');
      // Clear router state so refresh doesn't re-trigger
      window.history.replaceState({}, '');
    }
  }, [location.state]);

  // ── Share state ──
  const [shareInfo, setShareInfo] = useState<ShareInfo | null>(null);
  const [shareLoading, setShareLoading] = useState(false);

  // ── Hooks ──
  const bm = useBookmarks();
  const hl = useHighlights(bm.selectedBookmark, bm.bookmarkDetail, bm.setBookmarks, reportScrollRef);
  const exploration = useExploration(bm.selectedBookmark, bm.setBookmarks, bm.bookmarkDetail);

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
      bm.setBookmarkDetail((prev: BookmarkDetail | null) => prev ? { ...prev, share: info } : prev);
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
      bm.setBookmarkDetail((prev: BookmarkDetail | null) => {
        if (!prev) return prev;
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
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

  // Refresh bookmarks when switching to bookmarks or papers tab
  useEffect(() => {
    if (activeTab === 'bookmarks' || activeTab === 'papers') {
      bm.loadBookmarks();
    }
  }, [activeTab]);

  // ── Curriculum hook ──
  const cur = useCurriculum();

  return (
    <div className="mypage">
      {/* Header */}
      <div className="mypage-app-header">
        <div className="mypage-header-nav">
          <div className="mypage-logo" onClick={onBack} style={{ cursor: 'pointer' }}>
            <img src="/Jiphyeonjeon_llama.png" alt="Jiphyeonjeon" className="mypage-logo-icon"
              onError={(e) => { e.currentTarget.style.display = 'none'; }} />
            <span className="mypage-brand-name">Jiphyeonjeon</span>
          </div>
          <div className="mypage-header-actions">
            <button
              className={`mypage-nav-btn ${activeTab === 'papers' ? 'mypage-nav-btn-active' : ''}`}
              onClick={() => setActiveTab('papers')}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px' }}>
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
              </svg>
              Papers
            </button>
            <button
              className={`mypage-nav-btn ${activeTab === 'curriculum' ? 'mypage-nav-btn-active' : ''}`}
              onClick={() => setActiveTab('curriculum')}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px' }}>
                <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
                <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
              </svg>
              Curriculum
            </button>
            <button
              className={`mypage-nav-btn ${activeTab === 'bookmarks' ? 'mypage-nav-btn-active' : ''}`}
              onClick={() => setActiveTab('bookmarks')}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginRight: '6px' }}>
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
              </svg>
              My Page
            </button>
          </div>
        </div>
      </div>

      {/* Tab content */}
      {activeTab === 'papers' ? (
        <div className="mypage-content">
          {directPaper ? (
            <>
              <div className="paper-viewer-direct-sidebar">
                <div className="paper-viewer-list-header">
                  <span>Search Result</span>
                  <button
                    className="paper-viewer-direct-close"
                    onClick={() => setDirectPaper(null)}
                    title="Close and return to bookmarks"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  </button>
                </div>
                <div className="paper-viewer-direct-info">
                  <div className="paper-viewer-item-title">{directPaper.title}</div>
                  <div className="paper-viewer-item-meta">
                    {directPaper.authors?.slice(0, 2).join(', ')}{directPaper.authors?.length > 2 ? ' et al.' : ''}
                    {directPaper.year ? ` · ${directPaper.year}` : ''}
                  </div>
                </div>
              </div>
              <PaperViewerPanel
                bookmarkDetail={{ papers: [{
                  title: directPaper.title,
                  authors: directPaper.authors || [],
                  year: directPaper.year,
                  pdf_url: directPaper.pdf_url || undefined,
                  doi: directPaper.doi || undefined,
                  url: directPaper.url || undefined,
                  source: directPaper.source || undefined,
                }]}}
                loadingDetail={false}
                hasSelectedBookmark={true}
                autoSelectFirst={true}
              />
            </>
          ) : (
            <>
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
              <PaperViewerPanel
                bookmarkDetail={bm.bookmarkDetail}
                loadingDetail={bm.loadingDetail}
                hasSelectedBookmark={!!bm.selectedBookmark}
              />
            </>
          )}
        </div>
      ) : activeTab === 'bookmarks' ? (
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
      ) : (
        <div className="curriculum-content mypage-curriculum-content">
          <CourseSidebar
            presetCourses={cur.presetCourses}
            myCourses={cur.myCourses}
            loadingCourses={cur.loadingCourses}
            selectedCourseId={cur.selectedCourseId}
            selectedModuleId={cur.selectedModuleId}
            readPapers={cur.readPapers}
            progressStats={cur.progressStats}
            courseDetail={cur.courseDetail}
            generating={cur.generating}
            forking={cur.forking}
            generateProgress={cur.generateProgress}
            onSelectCourse={cur.handleSelectCourse}
            onSelectModule={cur.setSelectedModuleId}
            onGenerate={cur.handleGenerate}
            onFork={cur.handleFork}
            onDelete={cur.handleDelete}
            onShare={cur.handleShare}
            onRevokeShare={cur.handleRevokeShare}
            shareMessage={cur.shareMessage}
            getModuleProgress={cur.getModuleProgress}
          />

          {cur.loadingCourse ? (
            <div className="curriculum-main">
              <div className="curriculum-loading">Loading course...</div>
            </div>
          ) : (
            <ModuleView
              module={cur.selectedModule}
              readPapers={cur.readPapers}
              selectedPaperId={cur.selectedPaperId}
              onSelectPaper={cur.setSelectedPaperId}
              onToggleRead={cur.handleToggleRead}
              getModuleProgress={cur.getModuleProgress}
              onDeepReviewModule={cur.handleDeepReviewModule}
              reviewStatus={cur.reviewStatus}
              reviewingModuleId={cur.reviewingModuleId}
            />
          )}

          <CurriculumDetailPanel
            paper={cur.selectedPaper}
            courseDetail={cur.courseDetail}
            onSearchPaper={cur.handleSearchPaper}
            onViewPaper={(paper) => {
              setDirectPaper({ title: paper.title, authors: paper.authors, year: paper.year, doi: paper.doi, arxiv_id: paper.arxiv_id });
              setActiveTab('papers');
            }}
            onDeepReview={cur.handleDeepReviewPaper}
            reviewStatus={cur.reviewStatus}
            reviewProgress={cur.reviewProgress}
            reviewingPaperIds={cur.reviewingPaperIds}
            reviewingModuleId={cur.reviewingModuleId}
          />
        </div>
      )}
    </div>
  );
}

export default MyPage;
