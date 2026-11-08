import type { AdminConversationStats } from '../../api/client';

const dates = Array.from({ length: 90 }, (_, index) =>
  new Date(Date.UTC(2026, 7, 11 + index)).toISOString().slice(0, 10),
);

export const CONVERSATIONS: AdminConversationStats = {
  window: { days: 90, start: '2026-08-10T15:00:00Z', end: '2026-11-08T03:00:00Z', timezone: 'Asia/Seoul' },
  totals: { conversations: 7, user_turns: 126, assistant_turns: 109, active_users: 6, running: 2 },
  outcomes: { done: 100, failed: 2, interrupted: 3, cancelled: 2 },
  error_rate: 0.048,
  intents: [
    { intent: 'chat', turns: 90, failed: 1, interrupted: 0 },
    { intent: 'search', turns: 15, failed: 1, interrupted: 1 },
    { intent: 'review', turns: 2, failed: 0, interrupted: 0 },
  ],
  latency: [
    { intent: 'chat', samples: 88, p50_ms: 2100, p95_ms: 9100 },
    { intent: 'search', samples: 13, p50_ms: 4800, p95_ms: 15300 },
    { intent: 'review', samples: 2, p50_ms: 1200, p95_ms: null },
  ],
  reviews: {
    started: 2, by_mode: { fast: 1, full: 1 }, mode_missing: 0,
    outcomes: { completed: 1, failed: 0, running: 0, unknown: 1 },
    verification: { sessions_with_claims: 1, claims: 4, verified: 2, partially_verified: 1, unverified: 1, contradicted: 0, verified_ratio: 0.5 },
  },
  activation: { signups: 3, first_conversation_within_24h: 2 },
  daily: dates.map((date, index) => ({
    date,
    conversations: index < 87 ? 0 : index - 84,
    user_turns: index < 87 ? 0 : (index - 86) * 21,
    active_users: index < 87 ? 0 : index - 85,
    failed: index === 88 ? 5 : 0,
  })),
  metric_definitions: {},
};

export const EMPTY_CONVERSATIONS: AdminConversationStats = {
  ...CONVERSATIONS,
  totals: { conversations: 0, user_turns: 0, assistant_turns: 0, active_users: 0, running: 0 },
  outcomes: { done: 0, failed: 0, interrupted: 0, cancelled: 0 },
  error_rate: null,
  intents: [], latency: [],
  reviews: {
    started: 0, by_mode: { fast: 0, full: 0 }, mode_missing: 0,
    outcomes: { completed: 0, failed: 0, running: 0, unknown: 0 },
    verification: { sessions_with_claims: 0, claims: 0, verified: 0, partially_verified: 0, unverified: 0, contradicted: 0, verified_ratio: null },
  },
  activation: { signups: 0, first_conversation_within_24h: 0 },
  daily: CONVERSATIONS.daily.map(({ date }) => ({ date, conversations: 0, user_turns: 0, active_users: 0, failed: 0 })),
};
