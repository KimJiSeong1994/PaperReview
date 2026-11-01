import { api } from './base';
import type { SampleConversation, SampleSummary } from '../types';

/** Read-only sample conversations; public, so the guest home and /samples work signed out. */
export const fetchSampleConversations = async (signal?: AbortSignal): Promise<SampleSummary[]> => {
  const response = await api.get<SampleSummary[]>('/api/samples/conversations', { signal });
  return Array.isArray(response.data) ? response.data : [];
};

export const fetchSampleConversation = async (slug: string, signal?: AbortSignal): Promise<SampleConversation> => {
  const response = await api.get<SampleConversation>(`/api/samples/conversations/${encodeURIComponent(slug)}`, { signal });
  return response.data;
};
