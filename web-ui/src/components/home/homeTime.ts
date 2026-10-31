/** Relative-time helpers for the home sidebar and continue rows. */
const DAY_MS = 86_400_000;
export const HISTORY_GROUPS = ['오늘', '이번 주', '이전'] as const;
export type HistoryGroup = typeof HISTORY_GROUPS[number];


export function groupOf(at: string, now: Date): HistoryGroup {
  const time = new Date(at).getTime();
  if (Number.isNaN(time)) return '이전';
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (time >= startOfToday) return '오늘';
  if (now.getTime() - time < 7 * DAY_MS) return '이번 주';
  return '이전';
}

export function relativeLabel(at: string, now: Date = new Date()): string {
  const time = new Date(at).getTime();
  if (Number.isNaN(time)) return '';
  const elapsed = now.getTime() - time;
  if (elapsed < 60_000) return '방금';
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)}분 전`;
  if (groupOf(at, now) === '오늘') return `${Math.floor(elapsed / 3_600_000)}시간 전`;
  if (elapsed < 2 * DAY_MS) return '어제';
  if (elapsed < 7 * DAY_MS) return `${Math.floor(elapsed / DAY_MS)}일 전`;
  return new Date(time).toLocaleDateString('ko-KR', { month: 'numeric', day: 'numeric' });
}
