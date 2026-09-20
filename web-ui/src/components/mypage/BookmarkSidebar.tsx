import {
  DndContext, DragOverlay, pointerWithin,
  useDraggable, useDroppable,
  type DragStartEvent, type DragEndEvent, type DragOverEvent,
  type SensorDescriptor, type SensorOptions,
} from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import type { Bookmark } from './types';

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

/**
 * The bookmark title often ends with the same date the meta row shows, because
 * of how the record was named. Drop that suffix — and only that exact one, so a
 * title that never carried a date is left alone.
 */
function titleWithoutDate(bm: { title: string; created_at: string }): string {
  const suffix = ` - ${new Date(bm.created_at).toLocaleDateString()}`;
  return bm.title.endsWith(suffix) ? bm.title.slice(0, -suffix.length) : bm.title;
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
      <span className="mypage-tree-guide-line" />
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
      <input
        type="checkbox"
        className="mypage-bookmark-checkbox"
        checked={isChecked}
        onClick={(e) => onToggleSelection(bm.id, e as any)}
        onChange={() => {}}
      />
      <svg className="mypage-tree-file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="13" height="13">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
      </svg>
      <div className="mypage-bookmark-info">
        <div className="mypage-bookmark-title" title={bm.title}>{titleWithoutDate(bm)}</div>
        <div className="mypage-bookmark-meta">
          <span>{new Date(bm.created_at).toLocaleDateString()}</span>
          <span>논문 {bm.num_papers}편</span>
          {/* Flags sit here rather than in the top-right action slot, which the
              title only leaves 30px for. */}
          {(bm.has_notes || bm.has_citation_tree || bm.has_share) && (
          <span className="mypage-bookmark-flags">
          {bm.has_notes && (
            <svg className="mypage-note-indicator" role="img" aria-label="메모 있음" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
              <title>메모 있음</title>
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
            </svg>
          )}
          {bm.has_citation_tree && (
            <svg className="mypage-note-indicator" role="img" aria-label="관련 논문 분석 있음" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
              <title>관련 논문 분석 있음</title>
              <path d="M12 3v6m0 0l-4 4m4-4l4 4m-8 0v4m8-4v4" /><circle cx="4" cy="21" r="2" /><circle cx="12" cy="21" r="2" /><circle cx="20" cy="21" r="2" />
            </svg>
          )}
          {bm.has_share && (
            <svg className="mypage-note-indicator" role="img" aria-label="공유 링크 활성" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
              <title>공유 링크 활성</title>
              <circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" />
              <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" /><line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
            </svg>
          )}
          </span>
          )}
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
        <button className="mypage-bookmark-delete"
          onClick={(e) => { e.stopPropagation(); onDelete(bm.id); }}
          title="북마크 삭제">✕</button>
      </div>
    </div>
  );
}

/* ===== Droppable Topic Group ===== */

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
        <svg className="mypage-tree-chevron" viewBox="0 0 16 16" fill="currentColor" width="10" height="10">
          <path d="M6 4l4 4-4 4z" />
        </svg>
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
              북마크를 끌어다 놓으세요 · 비어 있는 주제는 저장되지 않습니다
            </div>
          ) : children}
        </div>
      )}
    </div>
  );
}

/* ===== BookmarkSidebar ===== */

export interface BookmarkSidebarProps {
  bookmarks: Bookmark[];
  filteredBookmarks: Bookmark[];
  topicGroups: Record<string, Bookmark[]>;
  allTopics: string[];
  selectedBookmark: Bookmark | null;
  selectedIds: Set<string>;
  loadingBookmarks: boolean;
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  allNotesMode: boolean;
  setAllNotesMode: (v: boolean) => void;
  topicAccordionOpen: Record<string, boolean>;
  toggleTopicAccordion: (topic: string) => void;
  showNewTopicInput: boolean;
  setShowNewTopicInput: (v: boolean) => void;
  newTopicInput: string;
  setNewTopicInput: (v: string) => void;
  overTopicId: string | null;
  activeDragBookmark: Bookmark | null;
  sensors: SensorDescriptor<SensorOptions>[];
  onDragStart: (e: DragStartEvent) => void;
  onDragOver: (e: DragOverEvent) => void;
  onDragEnd: (e: DragEndEvent) => void;
  onSelect: (bm: Bookmark) => void;
  onDelete: (id: string) => void;
  onToggleSelection: (id: string, e: React.MouseEvent) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  onBulkDelete: () => void;
  onBulkMove: (topic: string) => void;
  onAddTopic: () => void;
  onStartSearch: () => void;
  onStartCurriculum: () => void;
}

export default function BookmarkSidebar({
  bookmarks, filteredBookmarks, topicGroups, allTopics,
  selectedBookmark, selectedIds, loadingBookmarks,
  searchQuery, setSearchQuery, allNotesMode, setAllNotesMode,
  topicAccordionOpen, toggleTopicAccordion,
  showNewTopicInput, setShowNewTopicInput, newTopicInput, setNewTopicInput,
  overTopicId, activeDragBookmark, sensors,
  onDragStart, onDragOver, onDragEnd,
  onSelect, onDelete, onToggleSelection,
  onSelectAll, onDeselectAll, onBulkDelete, onBulkMove,
  onAddTopic, onStartSearch, onStartCurriculum,
}: BookmarkSidebarProps) {
  return (
    <div className="mypage-bookmarks-panel" role="region" aria-label="Bookmarks sidebar">
      {/* Search bar */}
      <div className="mypage-search-bar">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14" className="mypage-search-icon">
          <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input type="text" className="mypage-search-input" placeholder="북마크 검색..."
          value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} aria-label="북마크 검색" />
        {searchQuery && (
          <button className="mypage-search-clear" onClick={() => setSearchQuery('')} aria-label="Clear search">✕</button>
        )}
        <button
          type="button"
          className={`mypage-notes-view-btn ${allNotesMode ? 'active' : ''}`}
          onClick={() => setAllNotesMode(!allNotesMode)}
          aria-pressed={allNotesMode}
          aria-label="메모 있는 북마크만 보기"
          title={allNotesMode ? '전체 북마크 보기' : '메모 있는 북마크만 보기'}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
          </svg>
        </button>
      </div>

      {allNotesMode && (
        <div className="mypage-filter-chip">
          <span>메모 있는 북마크만 표시 중</span>
          <button type="button" onClick={() => setAllNotesMode(false)}>해제</button>
        </div>
      )}

      {/* Bulk action bar */}
      {selectedIds.size > 0 && (
        <div className="mypage-bulk-bar">
          <div className="mypage-bulk-info">
            <span className="mypage-bulk-count">{selectedIds.size} selected</span>
            <button className="mypage-bulk-text-btn" onClick={onSelectAll}>All</button>
            <button className="mypage-bulk-text-btn" onClick={onDeselectAll}>None</button>
          </div>
          <div className="mypage-bulk-actions">
            <select className="mypage-bulk-move-select" defaultValue=""
              onChange={(e) => { if (e.target.value) { onBulkMove(e.target.value); e.target.value = ''; } }}>
              <option value="" disabled>Move to...</option>
              {allTopics.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <button className="mypage-bulk-delete-btn" onClick={onBulkDelete} aria-label="Delete selected bookmarks">Delete</button>
          </div>
        </div>
      )}

      {/* Bookmark list with DnD */}
      <div className="mypage-bookmarks-scroll">
        {loadingBookmarks ? (
          <div className="mypage-loading">불러오는 중...</div>
        ) : bookmarks.length === 0 ? (
          <div className="mypage-empty mypage-empty--start">
            <p>아직 북마크가 없습니다</p>
            <p className="mypage-empty-hint">논문을 검색해 딥리뷰를 저장하거나, 커리큘럼의 논문에서 시작할 수 있습니다.</p>
            <div className="mypage-empty-actions">
              <button type="button" className="mypage-empty-btn" onClick={onStartSearch}>논문 검색하기</button>
              <button type="button" className="mypage-empty-btn" onClick={onStartCurriculum}>커리큘럼에서 시작</button>
            </div>
          </div>
        ) : filteredBookmarks.length === 0 ? (
          allNotesMode && !searchQuery.trim() ? (
            <div className="mypage-empty mypage-empty--start">
              <p>메모가 있는 북마크가 없습니다</p>
              <div className="mypage-empty-actions">
                <button type="button" className="mypage-empty-btn" onClick={() => setAllNotesMode(false)}>전체 보기</button>
              </div>
            </div>
          ) : (
            <div className="mypage-empty">"{searchQuery}"에 맞는 북마크가 없습니다</div>
          )
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={pointerWithin}
            onDragStart={onDragStart}
            onDragOver={onDragOver}
            onDragEnd={onDragEnd}
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
                    onSelect={onSelect}
                    onToggleSelection={onToggleSelection}
                    onDelete={onDelete}
                    currentTopic={topic}
                    setSearchQuery={setSearchQuery}
                  />
                ))}
              </DroppableTopicGroup>
            ))}

            <DragOverlay dropAnimation={null}>
              {activeDragBookmark ? (
                <div className="mypage-drag-overlay">
                  <div className="mypage-bookmark-title">{activeDragBookmark.title}</div>
                  <div className="mypage-bookmark-meta">
                    <span>{new Date(activeDragBookmark.created_at).toLocaleDateString()}</span>
                    <span>논문 {activeDragBookmark.num_papers}편</span>
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
                    if (e.key === 'Enter') onAddTopic();
                    if (e.key === 'Escape') { setShowNewTopicInput(false); setNewTopicInput(''); }
                  }}
                  className="mypage-add-topic-input" autoFocus />
                <button className="mypage-add-topic-confirm" onClick={onAddTopic} disabled={!newTopicInput.trim()}>Add</button>
                <button className="mypage-add-topic-cancel" onClick={() => { setShowNewTopicInput(false); setNewTopicInput(''); }}>✕</button>
              </div>
            ) : (
              <button className="mypage-add-topic-btn" onClick={() => setShowNewTopicInput(true)}>New Topic</button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
