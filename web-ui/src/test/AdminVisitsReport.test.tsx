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
    bots: [{ bot: 'GPTBot', hits: 5, ok: 5, errors: 0 }],
    citation_clicks: 2,
    citation_paths: [{ path: '/blog/post-a', hits: 2 }],
    ai_referral_hits: 1,
    ai_referral_sources: [{ source: 'chatgpt.com', hits: 1 }],
    crawled_pages: [{ path: '/blog/deepwalk', hits: 7 }],
    channels: [{ channel: 'Google', hits: 34 }],
  },
};

describe('AdminVisitsReport', () => {
  it('renders traffic tiles, tables, AI section, and the GA4 pending banner', async () => {
    vi.mocked(fetchAdminVisitsReport).mockResolvedValue({
      data: REPORT,
    } as unknown as Awaited<ReturnType<typeof fetchAdminVisitsReport>>);

    render(<AdminVisitsReport />);

    await waitFor(() => expect(fetchAdminVisitsReport).toHaveBeenCalledWith(28));
    expect(await screen.findByText('방문 추이')).toBeInTheDocument();
    expect(screen.getByText('데이터 출처')).toBeInTheDocument(); // provenance header
    expect(screen.getByText('12')).toBeInTheDocument(); // visitors tile
    expect(screen.getByText('60%')).toBeInTheDocument(); // engaged rate
    expect(screen.getByText('독자층')).toBeInTheDocument(); // new audience section
    expect(screen.getByText('8')).toBeInTheDocument(); // new visitors tile
    expect(screen.getByText(/GA4 연동 대기 중/)).toBeInTheDocument();
    expect(screen.getByText('GPTBot')).toBeInTheDocument();
    expect(screen.getByText('AI 인용 fetch')).toBeInTheDocument(); // relabeled
    expect(screen.getByText('검색·소셜 유입')).toBeInTheDocument(); // new channel section
    expect(screen.getByText('Google')).toBeInTheDocument(); // channel row
    expect(screen.getByText('즉시 이탈 많음')).toBeInTheDocument();
    expect(screen.getByText('검색')).toBeInTheDocument(); // product event label
  });

  it('surfaces the API error state', async () => {
    vi.mocked(fetchAdminVisitsReport).mockRejectedValue(new Error('boom'));
    render(<AdminVisitsReport />);
    expect(await screen.findByText(/boom/)).toBeInTheDocument();
  });
});
