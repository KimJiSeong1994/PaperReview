import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import AdminActivityReport, { fmtDuration } from '../components/AdminActivityReport';
import { fetchAdminActivity, type AdminActivityReport as ActivityData } from '../api/client';

vi.mock('../PlotlyChart', () => ({ default: () => <div data-testid="plot" /> }));
vi.mock('../api/client', () => ({ fetchAdminActivity: vi.fn() }));

const mocked = vi.mocked(fetchAdminActivity);

const SAMPLE: ActivityData = {
  window_days: 28,
  generated_at: '2026-07-22T03:15:00Z',
  growth: {
    signups_series: [{ date: '2026-07-20', count: 4 }, { date: '2026-07-21', count: 7 }],
    total_users: 128,
    new_users_in_window: 11,
  },
  active_users: {
    dau: 12, wau: 40, mau: 96, stickiness: 0.125,
    active_series: [{ date: '2026-07-20', active: 10 }, { date: '2026-07-21', active: 12 }],
    basis: '로그인 이벤트 기준 · 비로그인 사용자는 과소집계됩니다.',
  },
  search: {
    query_series: [{ date: '2026-07-20', count: 30 }],
    total_queries: 210,
    top_queries: [{ query: 'graph rag', count: 42 }],
    click_through_rate: 0.34,
  },
  bookmarks: {
    add_series: [{ date: '2026-07-20', count: 5 }],
    remove_series: [{ date: '2026-07-20', count: 1 }],
    net_in_window: 4,
    top_topics: [{ topic: 'RAG', count: 9 }],
  },
  reviews: {
    create_series: [{ date: '2026-07-20', count: 3 }],
    started: 20, completed: 17, failed: 3, success_rate: 0.85,
    duration_p50_s: 45, duration_p90_s: 150, duration_p99_s: 320,
    fast_mode_share: 0.6,
    researcher_hist: { '3': 12, '5': 4 },
    failure_reasons: [{ reason: 'timeout', count: 2 }],
    cost_estimate_usd: 12.5,
    basis: '토큰 사용량 × 단가 추정.',
  },
  recent_activity_by_user: [{ username: 'alice', last_active: '2026-07-21', events_in_window: 55 }],
  metric_definitions: { dau: '하루 동안 활동한 순사용자 수.' },
  notes: ['비로그인 활동은 집계에서 제외됩니다.'],
};

const empty = (): ActivityData => ({
  ...SAMPLE,
  growth: { signups_series: [], total_users: 0, new_users_in_window: 0 },
  active_users: { dau: 0, wau: 0, mau: 0, stickiness: 0, active_series: [], basis: '' },
  search: { query_series: [], total_queries: 0, top_queries: [], click_through_rate: 0 },
  bookmarks: { add_series: [], remove_series: [], net_in_window: 0, top_topics: [] },
  reviews: {
    ...SAMPLE.reviews,
    create_series: [], researcher_hist: {}, failure_reasons: [],
    duration_p50_s: null, duration_p90_s: null, duration_p99_s: null,
  },
  recent_activity_by_user: [],
  metric_definitions: {},
  notes: [],
});

// Component reads only `.data` off the axios-style response.
const resp = (data: ActivityData) => ({ data }) as Awaited<ReturnType<typeof fetchAdminActivity>>;

describe('fmtDuration', () => {
  it('renders seconds under a minute and minutes at/above 60s', () => {
    expect(fmtDuration(45)).toBe('45초');
    expect(fmtDuration(60)).toBe('1.0분');
    expect(fmtDuration(150)).toBe('2.5분');
    expect(fmtDuration(0)).toBe('—');
  });
});

describe('AdminActivityReport', () => {
  beforeEach(() => mocked.mockReset());

  it('renders every activity section with data', async () => {
    mocked.mockResolvedValue(resp(SAMPLE));
    render(<AdminActivityReport />);

    expect(await screen.findByRole('heading', { name: '활동 분석 리포트' })).toBeInTheDocument();
    expect(screen.getByText('성장')).toBeInTheDocument();
    expect(screen.getByText('고착도')).toBeInTheDocument();
    expect(screen.getByText('13%')).toBeInTheDocument(); // stickiness 0.125 → 13%
    expect(screen.getByText('딥리뷰 파이프라인')).toBeInTheDocument();
    expect(screen.getByText('$12.50')).toBeInTheDocument();
    expect(screen.getByText('graph rag')).toBeInTheDocument();
    expect(screen.getByText('alice')).toBeInTheDocument();
  });

  it('shows empty-state placeholders without crashing', async () => {
    mocked.mockResolvedValue(resp(empty()));
    render(<AdminActivityReport />);

    expect(await screen.findByText('이 기간에 집계된 가입 데이터가 없습니다.')).toBeInTheDocument();
    expect(screen.getByText('이 기간에 활동한 사용자가 없습니다.')).toBeInTheDocument();
    expect(screen.getByText('집계된 검색어가 없습니다.')).toBeInTheDocument();
    // null durations (live prod when no session completed) render as "—", never crash.
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3);
  });
});
