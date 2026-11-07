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
  /** Per-slug sample activity; slugs are only those seen in events. */
  samples: { slug: string; page_views: number; card_views: number; cta_clicks: number }[];
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
    bots?: {
      bot: string;
      hits: number;
      ok: number;
      errors: number;
      verification_available: boolean;
      verified_hits: number;
      unverified_hits: number;
      content_ok: number;
      content_errors: number;
      discovery_errors: number;
      suspected_scan_hits: number;
      suspected_scan_errors: number;
      redirects: number;
    }[];
    verified_indexing_hits?: number;
    verified_content_errors?: number;
    discovery_errors?: number;
    suspected_scan_hits?: number;
    suspected_scan_errors?: number;
    unverified_hits?: number;
    estimated_answer_fetches?: number;
    estimated_answer_fetch_paths?: { path: string; hits: number }[];
    /** @deprecated Use estimated_answer_fetches. */
    citation_clicks?: number;
    /** @deprecated Use estimated_answer_fetch_paths. */
    citation_paths?: { path: string; hits: number }[];
    ai_referral_hits?: number;
    ai_referral_sources?: { source: string; hits: number }[];
    crawled_pages?: { path: string; hits: number }[];
    channels?: { channel: string; hits: number }[];
    log_window?: {
      requested_days: number;
      observed_days: number;
      first_at: string | null;
      last_at: string | null;
    };
    verification_failures?: string[];
  };
}

export function resolveEstimatedAnswerFetches(
  ai: Pick<AdminVisitsReport['ai'], 'estimated_answer_fetches' | 'citation_clicks'>
    & Partial<Pick<AdminVisitsReport['ai'], 'available'>>,
): { value: number | undefined; mismatch: boolean } {
  if (ai.available === false) return { value: undefined, mismatch: false };
  const canonical = ai.estimated_answer_fetches;
  const legacy = ai.citation_clicks;
  return {
    value: canonical ?? legacy,
    mismatch: canonical != null && legacy != null && canonical !== legacy,
  };
}

export const fetchAdminVisitsReport = (days: number, signal?: AbortSignal) =>
  api.get<AdminVisitsReport>('/api/admin/analytics/visits', { params: { days }, signal });

export type AdminWindowDays = 7 | 28 | 90;
export type AdminMcpWindowDays = AdminWindowDays;
export type AssistantIntent = 'chat' | 'clarify' | 'search' | 'answer' | 'review' | 'open_pdf' | 'highlight_pdf' | 'answer_from_bookmarks';
export interface AdminOverview {
  window: { days: number; start: string; end: string };
  totals: { visitors: number; page_views: number; returning_visitors: number };
  comparison: { start: string; end: string; available: boolean; totals: AdminOverview['totals'] };
  daily: { date: string; visitors: number | null }[];
  top_pages: { path: string; title?: string | null; views: number }[];
  acquisition: { state: 'connected' | 'failed' | 'not_connected'; synced_at: string | null; channels: { source: string; medium: string; sessions: number }[] };
  measurement: { first_at: string | null; last_at: string | null; population: 'consented_browser_events' };
}
export const fetchAdminOverview = (days: AdminWindowDays, signal?: AbortSignal) =>
  api.get<AdminOverview>('/api/admin/analytics/overview', { params: { days }, signal });

type AdminWindow = { days: AdminWindowDays; start: string; end: string; timezone: string };

export interface AdminGrowthStats {
  window: AdminWindow;
  totals: { active_users: number; new_users: number; returning_users: number; repeat_users: number; user_messages: number };
  activation: { signups: number; eligible: number; activated: number; pending: number; pending_activated: number; rate: number | null };
  retention: { day: number; eligible: number; returned: number; pending: number; rate: number | null }[];
  daily: { date: string; active_users: number; new_users: number; returning_users: number; user_messages: number }[];
  measurement: { population: string; activity: string; history: string; first_activity_date: string | null; unknown_signup_dates: number };
  metric_definitions: Record<string, string>;
}

export const fetchAdminGrowthStats = (days: AdminWindowDays, signal?: AbortSignal) =>
  api.get<AdminGrowthStats>('/api/admin/growth/stats', { params: { days }, signal });

// Aggregates only: the backend never returns conversation titles, turn text,
// memory text, USER.md or profile values on these endpoints.
export interface AdminConversationStats {
  window: AdminWindow;
  totals: { conversations: number; user_turns: number; assistant_turns: number; active_users: number; running: number };
  outcomes: { done: number; failed: number; cancelled: number; interrupted: number };
  error_rate: number | null;
  latency: { intent: AssistantIntent | string; samples: number; p50_ms: number | null; p95_ms: number | null }[];
  intents: { intent: AssistantIntent | string; turns: number; failed: number; interrupted: number }[];
  reviews: {
    started: number;
    by_mode: { fast: number; full: number };
    mode_missing: number;
    outcomes: { completed: number; failed: number; running: number; unknown: number };
    verification: {
      sessions_with_claims: number; claims: number;
      verified: number; partially_verified: number; unverified: number; contradicted: number;
      verified_ratio: number | null;
    };
  };
  activation: { signups: number; first_conversation_within_24h: number };
  daily: { date: string; conversations: number; user_turns: number; active_users: number; failed: number }[];
  metric_definitions: Record<string, unknown>;
}

export type MemoryKind = 'preference' | 'topic' | 'paper' | 'fact' | 'research' | 'interest';

export interface AdminSoulStats {
  window: AdminWindow;
  accounts: { with_soul: number; with_memories: number; with_user_md: number };
  memories: {
    total: number; new_in_window: number; interest_avg_hits: number | null;
    by_kind: { kind: MemoryKind; count: number; accounts: number }[];
  };
  profiles: { total: number; stale_over_24h: number; with_role: number; with_domain: number; with_keywords: number };
  metric_definitions: Record<string, unknown>;
}

export interface AdminLlmUsage {
  available: boolean;
  reason?: string;
  window: AdminWindow;
  ledger: { first_at: string | null; last_at: string | null; malformed_lines: number };
  totals: { calls: number; prompt_tokens: number; completion_tokens: number; cached_tokens: number };
  by_stage: { stage: string; model: string; calls: number; prompt_tokens: number; completion_tokens: number }[];
  daily: { date: string; prompt_tokens: number; completion_tokens: number }[];
  coverage: { unrecorded_stages: string[] };
  metric_definitions: Record<string, unknown>;
}

export const fetchAdminConversationStats = (days: AdminWindowDays, signal?: AbortSignal) =>
  api.get<AdminConversationStats>('/api/admin/conversations/stats', { params: { days }, signal });
export const fetchAdminSoulStats = (days: AdminWindowDays, signal?: AbortSignal) =>
  api.get<AdminSoulStats>('/api/admin/souls/stats', { params: { days }, signal });
export const fetchAdminLlmUsage = (days: AdminWindowDays, signal?: AbortSignal) =>
  api.get<AdminLlmUsage>('/api/admin/llm-usage', { params: { days }, signal });

export interface AdminMcpReport {
  available: boolean;
  reason: string | null;
  window: { start: string; end: string; days: AdminMcpWindowDays; timezone: string };
  measurement: {
    started_at: string | null;
    last_event_at: string | null;
    source_trust: string;
    tool_telemetry_available: boolean;
    claimed_adapter_requests: number;
    requests_with_invocation_id: number;
    legacy_or_unattributed_requests: number;
    invocation_coverage: number | null;
    limitations: string[];
  };
  totals: {
    requests: number;
    active_accounts: number;
    tool_calls: number;
    tool_successes: number;
    tool_failures: number;
    tool_unknown: number;
    jobs_started: number;
    jobs_completed: number;
    jobs_failed: number;
    jobs_pending: number;
    // 종료 대기 중 가장 오래된 작업의 시작 시각 — 건수만으로는 멈춘 작업을 못 가린다.
    jobs_pending_oldest_started_at: string | null;
    request_error_rate: number | null;
    request_p95_ms: number | null;
    tool_p95_ms: number | null;
    job_p95_ms: number | null;
    repeat_accounts: number;
    // p95의 실제 표본 수 — duration이 기록된 이벤트만 세므로 요청·호출·작업 건수와 다르다.
    request_duration_samples: number;
    tool_duration_samples: number;
    job_duration_samples: number;
  };
  daily: {
    date: string;
    requests: number;
    active_accounts: number;
    tool_calls: number;
    jobs_started: number;
    jobs_completed: number;
    jobs_failed: number;
  }[];
  tools: { name: string; calls: number; succeeded: number; failed: number; unknown: number; p95_ms: number | null }[];
  routes: { name: string; requests: number; errors: number; p95_ms: number | null }[];
  // 클라이언트와 어댑터 버전은 한 번만 나눈다 — 조인 키가 같은 행 안에 있어야
  // "어떤 클라이언트의 어떤 어댑터가 깨졌나"에 답할 수 있다.
  client_versions: {
    client: string; client_version: string; adapter_version: string;
    requests: number; errors: number; tool_calls: number; tool_failures: number;
  }[];
  jobs: { name: string; started: number; completed: number; failed: number; pending: number; unknown: number }[];
  errors: { kind: string; code: string; count: number }[];
}

export const fetchAdminMcpReport = (
  days: AdminMcpWindowDays,
  includeInternal: boolean,
  signal?: AbortSignal,
) => api.get<AdminMcpReport>('/api/admin/analytics/mcp', {
  params: { days, include_internal: includeInternal },
  signal,
});

export interface AdminUser {
  username: string;
  role: string;
  created_at: string;
  bookmark_count: number;
  conversation_count: number;
  last_conversation_at: string | null;
  memory_count: number;
  profile_updated_at: string | null;
}

export interface AdminPaper {
  index: number;
  /** Opaque identity token; echo it back to delete this exact record. */
  fingerprint: string;
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

// The index alone is a position, not an identity — the backend re-checks the
// fingerprint and refuses the whole request (409) if the list has moved.
export const deleteAdminPapers = async (papers: { index: number; fingerprint: string }[]) => {
  const response = await api.delete('/api/admin/papers', { data: { papers } });
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

/** Data-file states for the 시스템 tab; the endpoint's username lists are deliberately not typed or shown. */
export interface AdminDiagnostics {
  files: Record<string, { exists: boolean; size: number }>;
  /** -1 = file missing, -2 = table unreadable. */
  counts: Record<string, number>;
}

export const fetchAdminDiagnostics = (signal?: AbortSignal) =>
  api.get<AdminDiagnostics>('/api/admin/diagnostics', { signal });
