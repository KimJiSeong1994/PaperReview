/* eslint-disable @typescript-eslint/no-explicit-any */
import axios from 'axios';
import { api, API_BASE_URL } from './base';
import type { HighlightItem } from './base';

export interface ShareInfo {
  token: string;
  share_url: string;
  created_at: string;
  expires_at: string;
}

export interface SharedBookmarkData {
  id: string;
  title: string;
  query: string;
  papers: any[];
  num_papers: number;
  report_markdown: string;
  created_at: string;
  tags: string[];
  topic: string;
  notes?: string;
  highlights?: HighlightItem[];
}

export const createShareLink = async (bookmarkId: string, expiresInDays?: number): Promise<ShareInfo> => {
  const body: Record<string, unknown> = {};
  if (expiresInDays !== undefined) body.expires_in_days = expiresInDays;
  const response = await api.post<ShareInfo>(`/api/bookmarks/${bookmarkId}/share`, body);
  return response.data;
};

export const revokeShareLink = async (bookmarkId: string) => {
  const response = await api.delete(`/api/bookmarks/${bookmarkId}/share`);
  return response.data;
};

export const getSharedBookmark = async (token: string): Promise<SharedBookmarkData> => {
  // Use raw axios to bypass auth interceptor — this is a public endpoint
  const response = await axios.get<SharedBookmarkData>(`${API_BASE_URL}/api/shared/${token}`);
  return response.data;
};
