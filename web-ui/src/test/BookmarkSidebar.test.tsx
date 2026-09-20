import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ComponentProps } from 'react';
import BookmarkSidebar from '../components/mypage/BookmarkSidebar';
import type { Bookmark } from '../components/mypage/types';

const bookmark = (over: Partial<Bookmark>): Bookmark => ({
  id: 'bm_1', title: 'Graph RAG', session_id: 's1', query: 'graph rag', num_papers: 3,
  created_at: '2026-09-01T00:00:00Z', tags: [], topic: 'RAG', ...over,
});

const base: ComponentProps<typeof BookmarkSidebar> = {
  bookmarks: [], filteredBookmarks: [], topicGroups: {}, allTopics: [],
  selectedBookmark: null, selectedIds: new Set(), loadingBookmarks: false,
  searchQuery: '', setSearchQuery: vi.fn(), allNotesMode: false, setAllNotesMode: vi.fn(),
  topicAccordionOpen: {}, toggleTopicAccordion: vi.fn(),
  showNewTopicInput: false, setShowNewTopicInput: vi.fn(), newTopicInput: '', setNewTopicInput: vi.fn(),
  overTopicId: null, activeDragBookmark: null, sensors: [],
  onDragStart: vi.fn(), onDragOver: vi.fn(), onDragEnd: vi.fn(),
  onSelect: vi.fn(), onDelete: vi.fn(), onToggleSelection: vi.fn(),
  onSelectAll: vi.fn(), onDeselectAll: vi.fn(), onBulkDelete: vi.fn(), onBulkMove: vi.fn(),
  onAddTopic: vi.fn(), onStartSearch: vi.fn(), onStartCurriculum: vi.fn(),
};

beforeEach(() => vi.clearAllMocks());

describe('BookmarkSidebar', () => {
  it('offers the two ways to a first bookmark instead of a dead end', () => {
    render(<BookmarkSidebar {...base} />);
    expect(screen.getByText('아직 북마크가 없습니다')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '논문 검색하기' }));
    fireEvent.click(screen.getByRole('button', { name: '커리큘럼에서 시작' }));
    expect(base.onStartSearch).toHaveBeenCalledTimes(1);
    expect(base.onStartCurriculum).toHaveBeenCalledTimes(1);
  });

  it('names the notes-only filter when it empties the list, and offers the way back', () => {
    const one = bookmark({});
    render(<BookmarkSidebar {...base} bookmarks={[one]} filteredBookmarks={[]} allNotesMode />);
    expect(screen.getByText('메모 있는 북마크만 표시 중')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '메모 있는 북마크만 보기' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('메모가 있는 북마크가 없습니다')).toBeInTheDocument();
    expect(screen.queryByText(/No results/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '전체 보기' }));
    expect(base.setAllNotesMode).toHaveBeenCalledWith(false);
  });

  it('says which search came up empty', () => {
    render(<BookmarkSidebar {...base} bookmarks={[bookmark({})]} filteredBookmarks={[]} searchQuery="quantum" />);
    expect(screen.getByText('"quantum"에 맞는 북마크가 없습니다')).toBeInTheDocument();
  });

  it('draws the share and citation-tree flags the server already sends', () => {
    const flagged = bookmark({ has_notes: true, has_citation_tree: true, has_share: true });
    const plain = bookmark({ id: 'bm_2', title: 'Plain' });
    render(<BookmarkSidebar {...base} bookmarks={[flagged, plain]} filteredBookmarks={[flagged, plain]}
      topicGroups={{ RAG: [flagged, plain] }} allTopics={['RAG']} topicAccordionOpen={{ RAG: true }} />);
    expect(screen.getByRole('img', { name: '메모 있음' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '관련 논문 분석 있음' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '공유 링크 활성' })).toBeInTheDocument();
    expect(screen.getAllByRole('img')).toHaveLength(3);
  });

  it('tells the user an empty topic is not saved', () => {
    render(<BookmarkSidebar {...base} bookmarks={[bookmark({})]} filteredBookmarks={[bookmark({})]}
      topicGroups={{ Empty: [] }} allTopics={['Empty']} topicAccordionOpen={{ Empty: true }} />);
    expect(screen.getByText(/비어 있는 주제는 저장되지 않습니다/)).toBeInTheDocument();
  });
});
