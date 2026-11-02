import { api } from './base';

export interface ReviewSessionSummary {
  session_id: string;
  status: string;
  progress: string | null;
  num_papers: number;
  created_at: string;
  title: string | null;
}

export interface ReviewSessionListResponse {
  sessions: ReviewSessionSummary[];
  total: number;
}

/** The caller's own deep-review sessions, newest first. */
export const fetchMyReviewSessions = async (
  limit = 5,
  signal?: AbortSignal,
): Promise<ReviewSessionListResponse> => {
  const response = await api.get<ReviewSessionListResponse>('/api/me/review-sessions', {
    params: { limit },
    signal,
  });
  return response.data;
};
