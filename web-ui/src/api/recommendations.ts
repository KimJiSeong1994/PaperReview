import { api } from './base';

export interface RecommendationNotification {
  id: string;
  title: string;
  reason: string;
  variant: string;
  run_at: string;
  score?: number | null;
  rank?: number | null;
  year?: number | string | null;
  authors: string[];
  venue?: string | null;
  source?: string | null;
  url?: string | null;
  pdf_url?: string | null;
  doi?: string | null;
  arxiv_id?: string | null;
}

export interface RecommendationNotificationResponse {
  items: RecommendationNotification[];
  unread_count: number;
  latest_run_at?: string | null;
  scoring_mode?: string | null;
  score_stats: Record<string, Record<string, number>>;
}

export async function fetchRecommendationNotifications(limit = 10): Promise<RecommendationNotificationResponse> {
  const response = await api.get<RecommendationNotificationResponse>('/api/recommendations/notifications', {
    params: { limit },
  });
  return response.data;
}
