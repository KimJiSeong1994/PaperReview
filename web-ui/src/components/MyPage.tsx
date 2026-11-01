import { useState, useRef, useEffect, useCallback } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import './MyPage.css';
import { useBookmarks } from '../hooks/useBookmarks';
import { useHighlights } from '../hooks/useHighlights';
import { useExploration } from '../hooks/useExploration';
import { createShareLink, revokeShareLink } from '../api/client';
import { createConversation } from '../api/conversations';
import type { ShareInfo } from '../api/client';
import type { Bookmark } from './mypage/types';
import BookmarkSidebar from './mypage/BookmarkSidebar';
import ReportViewer from './mypage/ReportViewer';
import AgentKeyButton from './AgentKeyButton';
import SoulPanel from './mypage/SoulPanel';

interface MyPageProps {
  onBack: () => void;
}

type MyPageTab = 'bookmarks' | 'memory';

// The default tab comes first, so the first tab on screen is the one the page
// opens on. "Papers" and "bookmarks" share a selection; the labels say what the
// right-hand pane shows rather than pretending to be different places.
const MYPAGE_TABS: { id: MyPageTab; label: string; icon: ReactNode }[] = [
  {
    id: 'bookmarks', label: '북마크',
    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" aria-hidden="true"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" /></svg>,
  },
  {
    // What the assistant remembers about this user; it has its own panel, no bookmark sidebar.
    id: 'memory', label: '기억',
    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" aria-hidden="true"><path d="M12 3a6 6 0 0 0-6 6c0 2.2 1.2 3.6 2.4 4.8.8.8 1.6 1.6 1.6 2.7V18h4v-1.5c0-1.1.8-1.9 1.6-2.7C16.8 12.6 18 11.2 18 9a6 6 0 0 0-6-6z" /><line x1="10" y1="21" x2="14" y2="21" /></svg>,
  },
];

const CURRICULUM_ICON = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" aria-hidden="true"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" /><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" /></svg>;

/**
 * `bookmarks` is the default, so it is the absence of the parameter rather than
 * a value — anything unrecognised lands there too.
 */
export function tabFromParams(raw: string | null): MyPageTab {
  return raw === 'memory' ? raw : 'bookmarks';
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
  const navigate = useNavigate();
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


  // ── "대화에서 열기" ──
  // The error belongs to the bookmark it was raised on, so selecting another one hides it.
  const [conversationAttempt, setConversationAttempt] = useState<{ bookmarkId: string; error: string | null } | null>(null);

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

  // Direct bookmark selection
  const handleSelectBookmarkDirect = useCallback(async (bookmark: Bookmark) => {
    setSearchParams((prev) => paramsWithBookmark(prev, bookmark.id), { replace: true });
    await selectBookmarkAndInitHighlights(bookmark);
  }, [selectBookmarkAndInitHighlights, setSearchParams]);

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

  const handleOpenInConversation = async () => {
    const bookmarkId = bm.selectedBookmark?.id;
    const title = bm.bookmarkDetail?.title ?? bm.selectedBookmark?.title;
    if (!bookmarkId || !title || conversationAttempt?.error === null) return;
    setConversationAttempt({ bookmarkId, error: null });
    try {
      const created = await createConversation(`북마크 "${title}"의 리포트를 바탕으로 이야기해 줘`);
      // The bookmark's review opens in the conversation's 리뷰 tab straight away.
      navigate(`/c/${created.id}`, {
        state: { run: true, openReview: bm.selectedBookmark?.session_id || null, openReviewTitle: title },
      });
    } catch {
      setConversationAttempt({ bookmarkId, error: '대화를 시작하지 못했어요. 잠시 후 다시 시도해 주세요.' });
    }
  };
  const attemptForSelected = conversationAttempt && conversationAttempt.bookmarkId === bm.selectedBookmark?.id
    ? conversationAttempt
    : null;

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

  // Old links still say ?tab=curriculum, which has its own route now; that
  // render only redirects, so it must not fetch on the way out.
  const redirectingToCurriculum = searchParams.get('tab') === 'curriculum';

  // Refresh bookmarks when switching to bookmarks or papers tab
  useEffect(() => {
    if (!redirectingToCurriculum) bm.loadBookmarks();
  }, [activeTab, redirectingToCurriculum]);

  // One element, rendered once at the top of the shared container. Written
  // twice it was 33 props of copy-paste that had to be kept in step by hand.
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
    onStartCurriculum={() => navigate('/curriculum')}
    />
  );

  if (redirectingToCurriculum) return <Navigate to="/curriculum" replace />;

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
            <Link className="mypage-nav-btn mypage-nav-link" to="/curriculum">
              {CURRICULUM_ICON}
              커리큘럼
            </Link>
          </div>
        </div>
      </div>

      {/* Tab content */}
        <div
          className={`mypage-content${activeTab === 'memory' ? ' mypage-content--memory' : ''}`}
          role="tabpanel"
          id={`mypage-panel-${activeTab}`}
          aria-labelledby={`mypage-tab-${activeTab}`}
        >
          {activeTab !== 'memory' && bookmarkSidebar}
          {activeTab === 'memory' && <SoulPanel />}
          {/* A display:contents wrapper: the report stays a grid child, and stays mounted while 기억 is open. */}
          <div className="mypage-tab-body" hidden={activeTab !== 'bookmarks'}>
          <ReportViewer
            bookmarkDetail={bm.bookmarkDetail}
            loadingDetail={bm.loadingDetail}
            hasSelectedBookmark={!!bm.selectedBookmark}
            reportScrollRef={reportScrollRef}
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
            onOpenInConversation={handleOpenInConversation}
            openingConversation={attemptForSelected?.error === null}
            conversationError={attemptForSelected?.error ?? null}
          />

          </div>
        </div>
    </div>
  );
}

export default MyPage;
