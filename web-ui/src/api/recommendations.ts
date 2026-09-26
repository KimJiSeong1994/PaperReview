import { api } from './base';

export interface RecommendationNotification {
  canonical_key: string;
  final_rank: number;
  display_position: number;
  seen: boolean;
  title: string;
  abstract?: string | null;
  authors: string[];
  year?: number | string | null;
  publication_date?: string | null;
  url?: string | null;
  pdf_url?: string | null;
  doi?: string | null;
  arxiv_id?: string | null;
  openalex_id?: string | null;
  semantic_scholar_id?: string | null;
  pmid?: string | null;
  venue?: string | null;
  score: number;
  reason: string;
  candidate_sources: string[];
  score_breakdown: Record<string, number>;
}

export interface RecommendationNotificationResponse {
  items: RecommendationNotification[];
  unread_count: number;
  total_count: number;
  latest_run_at: string | null;
  run_id: string | null;
  scoring_mode: 'v1' | 'v2' | 'v1_fallback' | 'metadata' | null;
  state: 'ready' | 'empty' | 'degraded' | 'stale' | 'expired' | 'unavailable';
  freshness: 'fresh' | 'stale' | 'expired' | 'missing';
  source_statuses: Record<string, string>;
  degraded_reasons: string[];
}

export type RecommendationAction = 'hide' | 'already_seen' | 'topic_less' | 'interested' | 'seen';
export interface RecommendationMutation {
  run_id: string;
  canonical_key: string;
  action: RecommendationAction | 'undo';
  request_id: string;
  undo_action?: RecommendationAction;
}
export interface RecommendationReceipt {
  tracked: true;
  request_id: string;
  canonical_key: string;
  action: RecommendationAction | 'undo';
  undo_action: RecommendationAction | null;
  applied_at: string;
}

export async function fetchRecommendationNotifications(limit = 5, signal?: AbortSignal): Promise<RecommendationNotificationResponse> {
  const response = await api.get<RecommendationNotificationResponse>('/api/recommendations/notifications', {
    params: { limit }, signal,
  });
  return response.data;
}

export async function mutateRecommendation(body: RecommendationMutation, signal?: AbortSignal): Promise<RecommendationReceipt> {
  const endpoint = body.action === 'seen' ? 'read-state' : 'feedback';
  const response = await api.post<RecommendationReceipt>(`/api/recommendations/${endpoint}`, body, { signal });
  return response.data;
}

export async function recordRecommendationExposure(body: {
  run_id: string; canonical_key: string; visible_fraction: number; visible_ms: number;
}, signal?: AbortSignal): Promise<{ tracked: true; recorded: boolean }> {
  const response = await api.post<{ tracked: true; recorded: boolean }>('/api/recommendations/exposure', body, { signal });
  return response.data;
}
