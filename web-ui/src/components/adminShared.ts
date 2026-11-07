import { useCallback, useEffect, useState } from 'react';
import type { AdminLlmUsage, AdminWindowDays } from '../api/client';

export const WINDOWS: AdminWindowDays[] = [7, 28, 90];
const WINDOW_KEY = 'admin.window';

const nf = new Intl.NumberFormat('ko-KR');
export const fmt = (value: number) => nf.format(value ?? 0);
// null is "no denominator", never 0%.
export const pct = (value: number | null) => (value === null ? '—' : `${(value * 100).toFixed(1)}%`);
export const ratio = (part: number, whole: number) => (whole > 0 ? part / whole : null);
export const seconds = (ms: number | null) => (ms === null ? '—' : `${(ms / 1000).toFixed(1)}초`);
export const kstDay = (iso: string | null) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(t) ? new Date(t + 9 * 3_600_000).toISOString().slice(0, 10) : null;
};

export const INTENT_LABELS: Record<string, string> = {
  chat: '대화',
  clarify: '되묻기',
  search: '검색',
  answer: '결과 답변',
  review: '리뷰 시작',
  open_pdf: 'PDF 열기',
  highlight_pdf: '하이라이트',
  answer_from_bookmarks: '북마크 답변',
};
export const MEMORY_KIND_LABELS: Record<string, string> = {
  preference: '선호',
  topic: '주제',
  paper: '논문',
  fact: '사실',
  research: '연구',
  interest: '관심사',
};
export const STAGE_LABELS: Record<string, string> = { claim_verification: '주장 검증' };
const LEDGER_REASON_LABELS: Record<string, string> = { 'ledger not found': '사용량 원장 파일이 없습니다' };

export const unavailableCopy = (usage: AdminLlmUsage) => (
  usage.reason ? LEDGER_REASON_LABELS[usage.reason] ?? `사용량 원장을 읽을 수 없습니다 (${usage.reason})` : '사용량 원장이 없습니다'
);

// Plotly ignores CSS var() colors, so charts take hex literals.
export const COLORS = { bar: '#4f46e5', barSoft: '#a7a1f7', fail: '#e05266', axis: '#858291', grid: '#ecebf0', font: '#706d7d' };

/** The admin's shared 7/28/90 window, remembered across tabs and visits. */
export function useAdminWindow(): [AdminWindowDays, (days: AdminWindowDays) => void] {
  const [days, setDaysState] = useState<AdminWindowDays>(() => {
    try {
      const stored = Number(localStorage.getItem(WINDOW_KEY));
      return (WINDOWS as number[]).includes(stored) ? (stored as AdminWindowDays) : 7;
    } catch {
      return 7;
    }
  });
  const setDays = useCallback((next: AdminWindowDays) => {
    setDaysState(next);
    try {
      localStorage.setItem(WINDOW_KEY, String(next));
    } catch {
      /* private mode: the window just resets next visit */
    }
  }, []);
  return [days, setDays];
}

export interface Block<T> { data: T | null; loading: boolean; error: string | null; status: number | null; retry: () => void }

/** One endpoint, loaded on its own so a failing source never blanks the others. */
export function useBlock<T>(
  fetcher: (days: AdminWindowDays, signal: AbortSignal) => Promise<{ data: T }>,
  days: AdminWindowDays,
): Block<T> {
  const [nonce, setNonce] = useState(0);
  const [snapshot, setSnapshot] = useState<{
    days: AdminWindowDays; fetcher: typeof fetcher; nonce: number;
    data: T | null; error: string | null; status: number | null;
  } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => {
      if (controller.signal.aborted) return;
      fetcher(days, controller.signal)
        .then(({ data }) => {
          if (!controller.signal.aborted) setSnapshot({ days, fetcher, nonce, data, error: null, status: null });
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          const detail = err as { response?: { status?: number; data?: { detail?: string } }; message?: string };
          setSnapshot({ days, fetcher, nonce, data: null,
            status: detail.response?.status ?? null,
            error: detail.response?.data?.detail ?? detail.message ?? '알 수 없는 오류' });
        });
    });
    return () => controller.abort();
  }, [fetcher, days, nonce]);

  const retry = useCallback(() => setNonce((n) => n + 1), []);
  const current = snapshot?.days === days && snapshot.fetcher === fetcher && snapshot.nonce === nonce;
  return current
    ? { data: snapshot.data, loading: false, error: snapshot.error, status: snapshot.status, retry }
    : { data: null, loading: true, error: null, status: null, retry };
}
