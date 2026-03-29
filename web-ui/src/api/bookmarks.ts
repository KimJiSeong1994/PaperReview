/* eslint-disable @typescript-eslint/no-explicit-any */
import { api } from './base';
import type { HighlightItem } from './base';

export const saveBookmark = async (request: {
  session_id: string;
  title: string;
  query: string;
  papers: any[];
  report_markdown: string;
  tags?: string[];
  topic?: string;
}) => {
  const response = await api.post('/api/bookmarks', request);
  return response.data;
};

export const saveBookmarkFromPaper = async (request: {
  title: string;
  authors: string[];
  year?: number;
  venue?: string;
  doi?: string | null;
  arxiv_id?: string | null;
  context?: string;
  source_curriculum?: string;
  topic?: string;
  tags?: string[];
}) => {
  const response = await api.post('/api/bookmarks/from-paper', request);
  return response.data;
};

export const getBookmarks = async () => {
  const response = await api.get('/api/bookmarks');
  return response.data;
};

export const getBookmarkDetail = async (bookmarkId: string) => {
  const response = await api.get(`/api/bookmarks/${bookmarkId}`);
  return response.data;
};

export const deleteBookmark = async (bookmarkId: string) => {
  const response = await api.delete(`/api/bookmarks/${bookmarkId}`);
  return response.data;
};

export const updateBookmarkTitle = async (bookmarkId: string, title: string) => {
  const response = await api.patch(`/api/bookmarks/${bookmarkId}/title`, { title });
  return response.data;
};

export const updateBookmarkTopic = async (bookmarkId: string, topic: string) => {
  const response = await api.patch(`/api/bookmarks/${bookmarkId}/topic`, { topic });
  return response.data;
};

export const updateBookmarkNotes = async (
  bookmarkId: string,
  notes?: string,
  highlights?: HighlightItem[],
) => {
  const body: Record<string, unknown> = {};
  if (notes !== undefined) body.notes = notes;
  if (highlights !== undefined) body.highlights = highlights;
  const response = await api.patch(`/api/bookmarks/${bookmarkId}/notes`, body);
  return response.data;
};

// Auto Highlight (LLM-based)
export const autoHighlightBookmark = async (bookmarkId: string): Promise<{ highlights: HighlightItem[] }> => {
  const response = await api.post<{ highlights: HighlightItem[] }>(`/api/bookmarks/${bookmarkId}/auto-highlight`);
  return response.data;
};

// Bulk bookmark operations
export const bulkDeleteBookmarks = async (bookmarkIds: string[]) => {
  const response = await api.post('/api/bookmarks/bulk-delete', { bookmark_ids: bookmarkIds });
  return response.data;
};

export const bulkMoveBookmarks = async (bookmarkIds: string[], topic: string) => {
  const response = await api.post('/api/bookmarks/bulk-move', { bookmark_ids: bookmarkIds, topic });
  return response.data;
};