import { useState, useRef, useEffect, useCallback, lazy, Suspense } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { openPaperViewer, viewerHrefForPaper } from '../utils/blogPaperReference';
import './MyPage.css';
import { useBookmarks } from '../hooks/useBookmarks';
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
import LazyLoadErrorBoundary from './LazyLoadErrorBoundary';
import AgentKeyButton from './AgentKeyButton';
import RecommendationBell from './RecommendationBell';
import './CurriculumPage.css';

const PaperViewerPanel = lazy(() => import('./mypage/PaperViewerPanel'));

interface MyPageProps {
  onBack: () => void;
}

type MyPageTab = 'bookmarks' | 'curriculum' | 'papers';

// The default tab comes first, so the first tab on screen is the one the page
// opens on. "Papers" and "bookmarks" share a selection; the labels say what the
// right-hand pane shows rather than pretending to be different places.
const MYPAGE_TABS: { id: MyPageTab; label: string; icon: ReactNode }[] = [
  {
    id: 'bookmarks', label: '북마크',
    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" aria-hidden="true"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" /></svg>,
  },
  {
    id: 'papers', label: '논문 PDF',
    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /></svg>,
  },
  {
    id: 'curriculum', label: '커리큘럼',
    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" aria-hidden="true"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" /><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" /></svg>,
  },
];

/**
 * `bookmarks` is the default, so it is the absence of the parameter rather than
 * a value — anything unrecognised lands there too.
 */
export function tabFromParams(raw: string | null): MyPageTab {
  return raw === 'papers' || raw === 'curriculum' ? raw : 'bookmarks';
}

/** Carries the rest of the query string through; only touches its own key. */
export function paramsWithTab(prev: URLSearchParams, tab: MyPageTab): URLSearchParams {
  const next = new URLSearchParams(prev);
  if (tab === 'bookmarks') next.delete('tab');
  else next.set('tab', tab);
  return next;
}

/** Same, for the open bookmark. */
export function paramsWithBookmark(prev: URLSearchParams, id: string): URLSearchParams {
  const next = new URLSearchParams(prev);
  next.set('bookmark', id);
  return next;
}

function MyPage({ onBack }: MyPageProps) {
  const reportScrollRef = useRef<HTMLDivElement>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  // Read once, on mount: the URL seeds the tab, and after that the tab writes
  // to the URL. Reading it on every render instead would fight the writes.
  const [activeTab, setActiveTab] = useState<MyPageTab>(() => tabFromParams(searchParams.get('tab')));

  /** Switch tabs and record it, so a reload or a shared link lands in the same place. */
  const changeTab = useCallback((tab: MyPageTab) => {
    setActiveTab(tab);
    setSearchParams((prev) => paramsWithTab(prev, tab), { replace: true });
  }, [setSearchParams]);

  // Roving tabindex: arrows move between tabs and open them, Home/End jump.
  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const order = MYPAGE_TABS.map((tab) => tab.id);
    const index = order.indexOf(activeTab);
    const next = event.key === 'ArrowRight' ? order[(index + 1) % order.length]
      : event.key === 'ArrowLeft' ? order[(index - 1 + order.length) % order.length]
        : event.key === 'Home' ? order[0]
          : event.key === 'End' ? order[order.length - 1]
            : null;
    if (!next) return;
    event.preventDefault();
    changeTab(next);
    document.getElementById(`mypage-tab-${next}`)?.focus();
  };


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
    setSearchParams((prev) => paramsWithBookmark(prev, bookmark.id), { replace: true });
    await selectBookmarkAndInitHighlights(bookmark);
  }, [selectBookmarkAndInitHighlights, chat.setHighlightTerms, setSearchParams]);

  /**
   * Reopen whatever the URL names, once the list it has to be found in has
   * arrived. Guarded so it runs a single time: this reads the params and must
   * never react to its own writes, which is how a sync effect turns into a loop.
   */
  const restoredFromUrl = useRef(false);
  useEffect(() => {
    if (restoredFromUrl.current) return;
    const wanted = searchParams.get('bookmark');
    if (!wanted || bm.bookmarks.length === 0) return;
    restoredFromUrl.current = true;
    const found = bm.bookmarks.find((b: Bookmark) => b.id === wanted);
    if (found) selectBookmarkAndInitHighlights(found);
  }, [bm.bookmarks, searchParams, selectBookmarkAndInitHighlights]);

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

  // Refresh bookmarks when switching to bookmarks or papers tab
  useEffect(() => {
    if (activeTab === 'bookmarks' || activeTab === 'papers') {
      bm.loadBookmarks();
    }
  }, [activeTab]);

  // ── Curriculum hook ──
  const cur = useCurriculum();

  // One element, rendered by whichever tab is active — they are mutually
  // exclusive, so this only ever mounts once. Written twice it was 33 props
  // of copy-paste that had to be kept in step by hand.
  const bookmarkSidebar = (
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
    onStartSearch={onBack}
    onStartCurriculum={() => changeTab('curriculum')}
    />
  );

  return (
    <div className="mypage">
      {/* Header */}
      <div className="mypage-app-header">
        <div className="mypage-header-nav">
          <div className="mypage-logo" onClick={onBack} style={{ cursor: 'pointer' }}>
            <picture>
              <source srcSet="/Jiphyeonjeon_llama.webp" type="image/webp" />
              <img src="/Jiphyeonjeon_llama.png" alt="Jiphyeonjeon" className="mypage-logo-icon"
                width={128} height={128} loading="eager" fetchPriority="high"
                onError={(e) => { e.currentTarget.style.display = 'none'; }} />
            </picture>
            <span className="mypage-brand-name">Jiphyeonjeon</span>
          </div>
          <div className="mypage-header-actions">
            <RecommendationBell />
            <AgentKeyButton />
            <div className="mypage-tabs" role="tablist" aria-label="마이페이지">
              {MYPAGE_TABS.map(({ id, label, icon }) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  id={`mypage-tab-${id}`}
                  aria-selected={activeTab === id}
                  aria-controls={activeTab === id ? `mypage-panel-${id}` : undefined}
                  tabIndex={activeTab === id ? 0 : -1}
                  className={`mypage-nav-btn ${activeTab === id ? 'mypage-nav-btn-active' : ''}`}
                  onClick={() => changeTab(id)}
                  onKeyDown={onTabKeyDown}
                >
                  {icon}
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Tab content */}
      {activeTab === 'papers' ? (
        <div className="mypage-content mypage-content--viewer" role="tabpanel" id="mypage-panel-papers" aria-labelledby="mypage-tab-papers">
          <>
              {bookmarkSidebar}
              <LazyLoadErrorBoundary>
                <Suspense fallback={<div className="paper-viewer-lazy-loading" role="status" aria-live="polite">뷰어 불러오는 중...</div>}>
                  <PaperViewerPanel
                    bookmarkDetail={bm.bookmarkDetail}
                    loadingDetail={bm.loadingDetail}
                    hasSelectedBookmark={!!bm.selectedBookmark}
                  />
                </Suspense>
              </LazyLoadErrorBoundary>
          </>
        </div>
      ) : activeTab === 'bookmarks' ? (
        <div className="mypage-content" role="tabpanel" id="mypage-panel-bookmarks" aria-labelledby="mypage-tab-bookmarks">
          {bookmarkSidebar}

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
            setHighlightPopover={hl.setHighlightPopover}
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
        <div className="curriculum-content mypage-curriculum-content" role="tabpanel" id="mypage-panel-curriculum" aria-labelledby="mypage-tab-curriculum">
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
            onViewPaper={(paper) => openPaperViewer(viewerHrefForPaper(paper, 'curriculum'))}
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
