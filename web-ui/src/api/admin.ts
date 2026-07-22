import { api } from './base';

export interface AdminDashboard {
  total_users: number;
  total_papers: number;
  total_bookmarks: number;
  recent_review_sessions: number;
  /** @deprecated Volatile deep-review jobs, not traffic sessions. */
  total_sessions?: number;
  kg_nodes: number;
  kg_edges: number;
  papers_by_source: { source: string; count: number }[];
  papers_by_year: { year: string; count: number }[];
  collection_queries: { query: string; count: number }[];
  /** @deprecated Stored-paper contribution counts, not search frequency. */
  top_queries?: { query: string; count: number }[];
  top_categories: { category: string; count: number }[];
  recent_papers: { title: string; source: string; collected_at: string }[];
  metric_definitions: {
    recent_review_sessions: {
      population: 'volatile_deep_review_jobs';
      ttl_hours: number;
      durable: false;
    };
    collection_queries: {
      population: 'stored_papers_with_search_query';
      unit: 'papers';
      is_search_frequency: false;
    };
    paper_catalog: {
      source: 'raw_papers_json';
      relationship_to_users: 'none';
    };
  };
}

export interface VisitsDaily {
  date: string;
  visitors: number;
  sessions: number;
  page_views: number;
}

export interface AdminVisitsReport {
  window: { days: number; start: string; end: string; timezone: string };
  measurement: {
    population: 'consented_browser_events';
    session_definition: 'browser_tab_lifetime';
    first_event_at: string | null;
    last_event_at: string | null;
    history_days: number;
    observed_days: number;
    event_count: number;
  };
  traffic: {
    totals: {
      visitors: number;
      sessions: number;
      page_views: number;
      signed_in_users: number;
      returning_visitors: number;
      new_visitors: number;
      avg_daily_visitors: number;
      engaged_sessions: number;
      engaged_rate: number;
      bounce_rate: number;
      pages_per_session: number;
    };
    daily: VisitsDaily[];
  };
  timing: {
    hour_of_day: number[];
    day_of_week: number[];
    peak_hour: number | null;
    peak_day_of_week: number | null;
  };
  top_pages: { path: string; page_views: number; visitors: number }[];
  landing: { path: string; sessions: number; engaged_rate: number }[];
  acquisition: {
    utm_sources: {
      utm_source: string;
      utm_medium: string | null;
      page_views: number;
      sessions: number;
    }[];
  };
  product_events: Record<string, number>;
  funnels: {
    id: string;
    label: string;
    steps: { event: string; count: number; rate: number; drop_off: number }[];
    overall_conversion: number;
  }[];
  deep_review_outcome: {
    started: number;
    completed: number;
    failed: number;
    abandoned: number;
  };
  ga4: {
    available: boolean;
    state: 'connected' | 'pending' | 'failed' | 'never_run';
    last_run: { sync_finished_at: string; status: string; error: string | null } | null;
    channels: { source: string; medium: string; users: number; sessions: number }[];
  };
  ai: {
    available: boolean;
    reason?: string;
    bots?: { bot: string; hits: number; ok: number; errors: number }[];
    citation_clicks?: number;
    citation_paths?: { path: string; hits: number }[];
    ai_referral_hits?: number;
    ai_referral_sources?: { source: string; hits: number }[];
    crawled_pages?: { path: string; hits: number }[];
    channels?: { channel: string; hits: number }[];
  };
}

export const fetchAdminVisitsReport = (days: number) =>
  api.get<AdminVisitsReport>('/api/admin/analytics/visits', { params: { days } });

// ── Activity analytics (성장·활성·검색·북마크·딥리뷰) ──────────────────
// Frozen contract: GET /api/admin/analytics/activity?days={7|28|90}.
// Series may be empty and numerics may be 0; render defensively.

export interface ActivityCountPoint {
  date: string;
  count: number;
}

export interface AdminActivityGrowth {
  signups_series: ActivityCountPoint[];
  total_users: number;
  new_users_in_window: number;
}

export interface AdminActivityActiveUsers {
  dau: number;
  wau: number;
  mau: number;
  /** dau/mau ratio (0..1). */
  stickiness: number;
  active_series: { date: string; active: number }[];
  basis: string;
}

export interface AdminActivitySearch {
  query_series: ActivityCountPoint[];
  total_queries: number;
  top_queries: { query: string; count: number }[];
  /** 0..1 */
  click_through_rate: number;
}

export interface AdminActivityBookmarks {
  add_series: ActivityCountPoint[];
  remove_series: ActivityCountPoint[];
  net_in_window: number;
  top_topics: { topic: string; count: number }[];
}

export interface AdminActivityReviews {
  create_series: ActivityCountPoint[];
  started: number;
  completed: number;
  failed: number;
  /** 0..1 */
  success_rate: number;
  /** null when no in-window session has completed (percentile undefined). */
  duration_p50_s: number | null;
  duration_p90_s: number | null;
  duration_p99_s: number | null;
  /** 0..1 */
  fast_mode_share: number;
  /** Map of researcher-count (string key) → session count. */
  researcher_hist: Record<string, number>;
  failure_reasons: { reason: string; count: number }[];
  cost_estimate_usd: number;
  basis: string;
}

export interface AdminActivityRecentUser {
  username: string;
  last_active: string;
  events_in_window: number;
}

export interface AdminActivityReport {
  window_days: number;
  generated_at: string;
  growth: AdminActivityGrowth;
  active_users: AdminActivityActiveUsers;
  search: AdminActivitySearch;
  bookmarks: AdminActivityBookmarks;
  reviews: AdminActivityReviews;
  recent_activity_by_user: AdminActivityRecentUser[];
  metric_definitions: Record<string, string>;
  notes: string[];
}

export const fetchAdminActivity = (days: number) =>
  api.get<AdminActivityReport>('/api/admin/analytics/activity', { params: { days } });

export interface AdminUser {
  username: string;
  role: string;
  created_at: string;
  bookmark_count: number;
}

export interface AdminPaper {
  index: number;
  title: string;
  authors: string[];
  source: string;
  published_date: string;
  search_query: string;
  searched_by: string;
}

export interface AdminPapersResponse {
  papers: AdminPaper[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  usernames: string[];
}

export interface AdminBookmarkPaper {
  title: string;
  authors: string[];
}

export interface AdminBookmark {
  id: string;
  title: string;
  username: string;
  query: string;
  topic: string;
  num_papers: number;
  papers: AdminBookmarkPaper[];
  created_at: string;
}

export interface AdminPaperUserStats {
  total: number;
  users: { username: string; paper_count: number }[];
}

export interface AdminCurriculumItem {
  id: string;
  name: string;
  difficulty: string;
  total_papers: number;
  total_modules: number;
  is_preset: boolean;
  forked_from: string | null;
  type: 'fork' | 'custom';
}

export interface AdminCurriculumUser {
  username: string;
  curricula: AdminCurriculumItem[];
  total_curricula: number;
  fork_count: number;
  custom_count: number;
  total_read_papers: number;
  courses_with_progress: number;
}

export interface AdminCurriculaResponse {
  total_user_curricula: number;
  total_users_with_curricula: number;
  users: AdminCurriculumUser[];
}

export const getAdminDashboard = async (): Promise<AdminDashboard> => {
  const response = await api.get<AdminDashboard>('/api/admin/dashboard');
  return response.data;
};

export const getAdminUsers = async (): Promise<{ users: AdminUser[] }> => {
  const response = await api.get<{ users: AdminUser[] }>('/api/admin/users');
  return response.data;
};

export const updateUserRole = async (username: string, role: string) => {
  const response = await api.patch(`/api/admin/users/${username}/role`, { role });
  return response.data;
};

export const deleteUser = async (username: string) => {
  const response = await api.delete(`/api/admin/users/${username}`);
  return response.data;
};

export const getAdminPaperStats = async (): Promise<AdminPaperUserStats> => {
  const response = await api.get<AdminPaperUserStats>('/api/admin/papers/stats');
  return response.data;
};

export const getAdminPapers = async (page: number = 1, pageSize: number = 50, username?: string): Promise<AdminPapersResponse> => {
  const response = await api.get<AdminPapersResponse>('/api/admin/papers', {
    params: { page, page_size: pageSize, ...(username ? { username } : {}) },
  });
  return response.data;
};

export const deleteAdminPapers = async (indices: number[]) => {
  const response = await api.delete('/api/admin/papers', { data: { indices } });
  return response.data;
};

export const getAdminBookmarks = async (username?: string): Promise<{ bookmarks: AdminBookmark[] }> => {
  const response = await api.get<{ bookmarks: AdminBookmark[] }>('/api/admin/bookmarks', {
    params: username ? { username } : {},
  });
  return response.data;
};

export const deleteAdminBookmark = async (bookmarkId: string) => {
  const response = await api.delete(`/api/admin/bookmarks/${bookmarkId}`);
  return response.data;
};

export const getAdminCurricula = async (): Promise<AdminCurriculaResponse> => {
  const response = await api.get<AdminCurriculaResponse>('/api/admin/curricula');
  return response.data;
};
