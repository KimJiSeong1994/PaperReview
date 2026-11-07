import type { AdminGrowthStats } from '../../api/client';

export const GROWTH: AdminGrowthStats = {
  window: { days: 28, start: '2026-10-10T15:00:00Z', end: '2026-11-07T03:00:00Z', timezone: 'Asia/Seoul' },
  totals: { active_users: 42, new_users: 12, returning_users: 30, repeat_users: 18, user_messages: 120 },
  activation: { signups: 10, eligible: 8, activated: 4, pending: 2, pending_activated: 1, rate: 0.5 },
  retention: [
    { day: 1, eligible: 10, returned: 3, pending: 2, rate: 0.3 },
    { day: 7, eligible: 0, returned: 0, pending: 12, rate: null },
  ],
  daily: [
    { date: '2026-11-06', active_users: 8, new_users: 3, returning_users: 5, user_messages: 23 },
    { date: '2026-11-07', active_users: 4, new_users: 1, returning_users: 3, user_messages: 15 },
  ],
  measurement: { population: 'current_non_admin_accounts', activity: 'persisted_user_message', history: 'retained_messages_only', first_activity_date: '2026-10-01', unknown_signup_dates: 2 },
  metric_definitions: {},
};
