import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import AdminVisitsReport from '../components/AdminVisitsReport';
import { fetchAdminVisitsReport } from '../api/client';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return { ...actual, fetchAdminVisitsReport: vi.fn() };
});

vi.mock('../PlotlyChart', () => ({
  default: () => <div data-testid="plot" />,
}));

const REPORT = {
  window: { days: 28, start: '2026-06-17', end: '2026-07-14', timezone: 'Asia/Seoul' },
  measurement: {
    population: 'consented_browser_events' as const,
    session_definition: 'browser_tab_lifetime' as const,
    first_event_at: '2026-06-17T00:00:00Z',
    last_event_at: '2026-07-14T02:00:00Z',
    history_days: 28,
    observed_days: 2,
    event_count: 95,
  },
  traffic: {
    totals: {
      visitors: 12,
      sessions: 30,
      page_views: 88,
      signed_in_users: 2,
      returning_visitors: 4,
      new_visitors: 8,
      avg_daily_visitors: 0.4,
      engaged_sessions: 18,
      engaged_rate: 0.6,
      bounce_rate: 0.4,
      pages_per_session: 2.9,
    },
    daily: [
      { date: '2026-07-13', visitors: 3, sessions: 5, page_views: 20 },
      { date: '2026-07-14', visitors: 4, sessions: 6, page_views: 22 },
    ],
  },
  timing: { hour_of_day: Array(24).fill(0), day_of_week: Array(7).fill(0), peak_hour: null, peak_day_of_week: null },
  top_pages: [{ path: '/blog', page_views: 40, visitors: 9 }],
  landing: [{ path: '/blog', sessions: 10, engaged_rate: 0.2 }],
  acquisition: { utm_sources: [] },
  product_events: { search: 3 },
  funnels: [
    {
      id: 'search_to_review',
      label: '검색 → 딥리뷰 완료',
      steps: [
        { event: 'search', count: 40, rate: 1.0, drop_off: 0 },
        { event: 'deep_review_start', count: 15, rate: 0.375, drop_off: 25 },
        { event: 'deep_review_complete', count: 10, rate: 0.25, drop_off: 5 },
      ],
      overall_conversion: 0.25,
    },
  ],
  deep_review_outcome: { started: 5, completed: 2, failed: 1, abandoned: 2 },
  ga4: {
    available: false,
    state: 'pending' as const,
    last_run: {
      sync_finished_at: '2026-07-13T19:52:30Z',
      status: 'failed',
      error: 'NotFound: 404 Not found: Dataset x',
    },
    channels: [],
  },
  ai: {
    available: true,
    bots: [
      {
        bot: 'GPTBot',
        hits: 7,
        ok: 6,
        errors: 1,
        verification_available: true,
        verified_hits: 5,
        unverified_hits: 2,
        content_ok: 4,
        content_errors: 0,
        discovery_errors: 1,
        suspected_scan_hits: 2,
        suspected_scan_errors: 1,
        redirects: 1,
      },
      {
        bot: 'ClaudeBot',
        hits: 3,
        ok: 2,
        errors: 1,
        verification_available: false,
        verified_hits: 0,
        unverified_hits: 3,
        content_ok: 0,
        content_errors: 0,
        discovery_errors: 0,
        suspected_scan_hits: 1,
        suspected_scan_errors: 1,
        redirects: 0,
      },
    ],
    verified_indexing_hits: 4,
    verified_content_errors: 0,
    discovery_errors: 1,
    suspected_scan_hits: 3,
    suspected_scan_errors: 2,
    unverified_hits: 5,
    citation_clicks: 2,
    citation_paths: [{ path: '/blog/post-a', hits: 2 }],
    ai_referral_hits: 1,
    ai_referral_sources: [{ source: 'chatgpt.com', hits: 1 }],
    crawled_pages: [{ path: '/blog/deepwalk', hits: 7 }],
    channels: [{ channel: 'Google', hits: 34 }],
    log_window: {
      requested_days: 28,
      observed_days: 15,
      first_at: '2026-06-30T00:00:00Z',
      last_at: '2026-07-14T02:00:00Z',
    },
    verification_failures: ['Amazonbot'],
  },
};

describe('AdminVisitsReport', () => {
  it('renders traffic tiles, tables, and the AI section', async () => {
    vi.mocked(fetchAdminVisitsReport).mockResolvedValue({
      data: REPORT,
    } as unknown as Awaited<ReturnType<typeof fetchAdminVisitsReport>>);

    render(<AdminVisitsReport />);

    await waitFor(() => expect(fetchAdminVisitsReport).toHaveBeenCalledWith(28));
    expect(await screen.findByRole('heading', { name: '방문 분석 리포트' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '이번 기간을 한 문장씩 읽어보세요' })).toBeInTheDocument();
    expect(screen.getByText('12명이 30번 방문')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '도달과 이용' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'AI와 외부 유입' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '제품 행동과 전환' })).toBeInTheDocument();
    expect(await screen.findByText('방문 추이')).toBeInTheDocument();
    // Band dividers group the report.
    expect(screen.getByText('사람 방문')).toBeInTheDocument();
    expect(screen.getByText('AI · 유입')).toBeInTheDocument();
    // At-a-glance hero repeats headline numbers, so several appear twice.
    expect(screen.getAllByText('12').length).toBeGreaterThanOrEqual(1); // visitors
    expect(screen.getAllByText('60%').length).toBeGreaterThanOrEqual(1); // engaged rate
    expect(screen.getByText(/퍼스트파티 이벤트 표본/)).toBeInTheDocument(); // data-source line
    expect(screen.getByText(/동의 표본/)).toBeInTheDocument();
    expect(screen.getByText(/30분 비활동 기준 세션이 아닙니다/)).toBeInTheDocument();
    expect(screen.getByText('독자층')).toBeInTheDocument();
    expect(screen.getByText('8')).toBeInTheDocument(); // new visitors tile
    expect(screen.getByText('GPTBot')).toBeInTheDocument();
    expect(screen.getByText('검증된 색인 크롤')).toBeInTheDocument();
    expect(screen.getAllByText('AI 답변 fetch (추정)').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('스캔 의심 요청')).toBeInTheDocument();
    expect(screen.getByText('크롤러 신뢰도')).toBeInTheDocument();
    expect(screen.getByText('미지원')).toBeInTheDocument();
    expect(screen.getByText(/nginx 로그 15일분/)).toBeInTheDocument();
    expect(screen.getByText(/공식 IP 확인 불가: Amazonbot/)).toBeInTheDocument();
    expect(screen.getByText(/실제 색인 오류 0건/)).toBeInTheDocument();
    expect(screen.getByText('검색·소셜 유입')).toBeInTheDocument();
    expect(screen.getByText('Google')).toBeInTheDocument();
    expect(screen.getByText('즉시 이탈 많음')).toBeInTheDocument();
    expect(screen.getByText('GA4 채널')).toBeInTheDocument();
    expect(screen.getByText(/연동을 기다리고 있습니다/)).toBeInTheDocument();
    expect(screen.getAllByText('검색').length).toBeGreaterThanOrEqual(1); // product event + funnel step label
    // Conversion funnel section renders with its steps + overall conversion.
    expect(screen.getByText('전환 퍼널')).toBeInTheDocument();
    expect(screen.getByText('검색 → 딥리뷰 완료')).toBeInTheDocument();
    expect(screen.getByText('전환 25%')).toBeInTheDocument();
    expect(screen.getByText('↓5')).toBeInTheDocument(); // drop-off annotation
    // Deep-review outcome breakdown (완료/실패/이탈).
    expect(screen.getByText('딥리뷰 결과')).toBeInTheDocument();
    expect(screen.getByText(/딥리뷰 결과 — 시작 5건/)).toBeInTheDocument();
    expect(screen.getByText('완료율 40%')).toBeInTheDocument();
    expect(screen.getByText(/실패 1/)).toBeInTheDocument();
    expect(screen.getByText(/이탈 2/)).toBeInTheDocument();
  }, 20_000);

  it('surfaces the API error state', async () => {
    vi.mocked(fetchAdminVisitsReport).mockRejectedValue(new Error('boom'));
    render(<AdminVisitsReport />);
    expect(await screen.findByText(/boom/)).toBeInTheDocument();
  });
});
