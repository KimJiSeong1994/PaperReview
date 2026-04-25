import { api } from './base';

export interface RecommendationVariantEvidence {
  variant: string;
  reason: string;
  score?: number | null;
  display_score?: string | null;
  confidence_label: string;
  rank?: number | null;
}

export interface RecommendationNotification {
  id: string;
  paper_id?: string | null;
  title: string;
  reason: string;
  variant: string;
  run_at: string;
  score?: number | null;
  display_score?: string | null;
  confidence_label: string;
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

export interface RecommendationPaperNotification {
  id: string;
  paper_id: string;
  title: string;
  top_reason: string;
  run_at: string;
  score?: number | null;
  display_score?: string | null;
  confidence_label: string;
  rank?: number | null;
  year?: number | string | null;
  authors: string[];
  venue?: string | null;
  source?: string | null;
  url?: string | null;
  pdf_url?: string | null;
  doi?: string | null;
  arxiv_id?: string | null;
  variants: RecommendationVariantEvidence[];
}

export interface RecommendationNotificationResponse {
  items: RecommendationNotification[];
  grouped_items: RecommendationPaperNotification[];
  unread_count: number;
  raw_count: number;
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
