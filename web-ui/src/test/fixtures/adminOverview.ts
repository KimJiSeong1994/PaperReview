import type { AdminOverview } from '../../api/client';
export const OVERVIEW: AdminOverview = {
  window: { days: 7, start: '2026-11-01T15:00:00Z', end: '2026-11-08T03:00:00Z' },
  totals: { visitors: 1248, page_views: 3862, returning_visitors: 316 },
  comparison: { start: '2026-10-25T15:00:00Z', end: '2026-11-01T03:00:00Z', available: true,
    totals: { visitors: 1040, page_views: 3511, returning_visitors: 329 } },
  daily: [182, 146, 203, 178, 241, 218, 129].map((visitors, i) => ({ date: `2026-11-0${i + 2}`, visitors })),
  top_pages: [
    { path: '/blog/graphrag', title: 'GraphRAG: 검색을 넘어 지식의 관계를 읽다', views: 428 },
    { path: '/blog/agent-memory', title: 'AI 에이전트는 무엇을 기억해야 할까?', views: 312 },
    { path: '/', views: 286 },
    { path: '/blog/attention', title: 'Attention을 이해하는 가장 직관적인 방법', views: 194 },
    { path: '/blog', views: 168 },
  ],
  acquisition: { state: 'connected', synced_at: '2026-11-08T01:00:00Z', channels: [
    { source: 'google', medium: 'organic', sessions: 524 },
    { source: '(direct)', medium: '(none)', sessions: 281 },
    { source: 'naver', medium: 'organic', sessions: 164 },
    { source: 'youtube.com', medium: 'referral', sessions: 92 },
    { source: 'chatgpt.com', medium: 'referral', sessions: 67 },
  ] },
  measurement: { first_at: '2026-09-01T00:00:00Z', last_at: '2026-11-08T02:58:00Z', population: 'consented_browser_events' },
};
