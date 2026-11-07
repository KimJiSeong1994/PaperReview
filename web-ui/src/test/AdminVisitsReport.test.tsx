import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import AdminVisitsReport from '../components/AdminVisitsReport';
import { fetchAdminVisitsReport, fetchSampleConversations, resolveEstimatedAnswerFetches } from '../api/client';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  // Public sample list, joined by slug for titles; empty unless a test sets it.
  return { ...actual, fetchAdminGrowthStats: vi.fn(() => new Promise(() => {})), fetchAdminVisitsReport: vi.fn(), fetchSampleConversations: vi.fn(() => Promise.resolve([])) };
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
  product_events: { search: 3, paper_select: 4, deep_review_start: 2, deep_review_complete: 1, deep_review_fail: 1, bookmark_save: 5, report_download: 1, poster_generate_start: 1, poster_generate_complete: 1, poster_generate_fail: 1, login: 2, conversation_start: 6 },
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
  samples: [] as { slug: string; page_views: number; card_views: number; cta_clicks: number }[],
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
  it('uses canonical nullish precedence and distinguishes missing from observed zero', () => {
    expect(resolveEstimatedAnswerFetches({ estimated_answer_fetches: 0, citation_clicks: 5 })).toEqual({
      value: 0,
      mismatch: true,
    });
    expect(resolveEstimatedAnswerFetches({ citation_clicks: 5 })).toEqual({ value: 5, mismatch: false });
    expect(resolveEstimatedAnswerFetches({ estimated_answer_fetches: 0 })).toEqual({ value: 0, mismatch: false });
    expect(resolveEstimatedAnswerFetches({})).toEqual({ value: undefined, mismatch: false });
    expect(resolveEstimatedAnswerFetches({ available: false, estimated_answer_fetches: 7, citation_clicks: 7 })).toEqual({
      value: undefined,
      mismatch: false,
    });
  });

  it('keeps the canonical value on mismatch and reports a development diagnostic', async () => {
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    vi.mocked(fetchAdminVisitsReport).mockResolvedValue({
      data: { ...REPORT, ai: { ...REPORT.ai, estimated_answer_fetches: 0, citation_clicks: 5 } },
    } as unknown as Awaited<ReturnType<typeof fetchAdminVisitsReport>>);
    render(<AdminVisitsReport days={28} onDays={vi.fn()} />);
    await screen.findByRole('heading', { name: '방문·유입' });
    expect(screen.getAllByText('0').length).toBeGreaterThan(0);
    expect(warning).toHaveBeenCalledWith(
      expect.stringContaining('estimated_answer_fetches'),
      { canonical: 0, legacy: 5 },
    );
    warning.mockRestore();
  });

  it('renders an absent fetch metric as unavailable rather than observed zero', async () => {
    const withoutLegacy = { ...REPORT.ai, citation_clicks: undefined };
    vi.mocked(fetchAdminVisitsReport).mockResolvedValue({
      data: { ...REPORT, ai: withoutLegacy },
    } as unknown as Awaited<ReturnType<typeof fetchAdminVisitsReport>>);
    render(<AdminVisitsReport days={28} onDays={vi.fn()} />);
    await screen.findByRole('heading', { name: '방문·유입' });
    expect(screen.getAllByText('확인 불가').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/답변 fetch 확인 불가/)).toBeInTheDocument();
  });

  it('keeps a missing referral unknown while preserving an observed zero', async () => {
    vi.mocked(fetchAdminVisitsReport).mockResolvedValueOnce({
      data: {
        ...REPORT,
        ai: { ...REPORT.ai, ai_referral_hits: undefined },
      },
    } as unknown as Awaited<ReturnType<typeof fetchAdminVisitsReport>>);
    const missing = render(<AdminVisitsReport days={28} onDays={vi.fn()} />);
    await screen.findByRole('heading', { name: '방문·유입' });
    expect(screen.getByText(/실제 유입 확인 불가/)).toBeInTheDocument();
    expect(screen.getByText('AI 클릭 유입').closest('.admin-stat-card')).toHaveTextContent('확인 불가');
    missing.unmount();

    vi.mocked(fetchAdminVisitsReport).mockResolvedValueOnce({
      data: {
        ...REPORT,
        ai: { ...REPORT.ai, ai_referral_hits: 0 },
      },
    } as unknown as Awaited<ReturnType<typeof fetchAdminVisitsReport>>);
    render(<AdminVisitsReport days={28} onDays={vi.fn()} />);
    await screen.findByRole('heading', { name: '방문·유입' });
    expect(screen.getByText(/실제 유입 0번/)).toBeInTheDocument();
    expect(screen.getByText('AI 클릭 유입').closest('.admin-stat-card')).toHaveTextContent('0');
  });

  it('prefers canonical fetch paths and preserves the nginx unavailable state', async () => {
    vi.mocked(fetchAdminVisitsReport).mockResolvedValueOnce({
      data: {
        ...REPORT,
        ai: {
          ...REPORT.ai,
          estimated_answer_fetch_paths: [{ path: '/blog/canonical-path', hits: 3 }],
          citation_paths: [{ path: '/blog/legacy-path', hits: 9 }],
        },
      },
    } as unknown as Awaited<ReturnType<typeof fetchAdminVisitsReport>>);
    const first = render(<AdminVisitsReport days={28} onDays={vi.fn()} />);
    expect(await screen.findByText('/blog/canonical-path')).toBeInTheDocument();
    expect(screen.queryByText('/blog/legacy-path')).not.toBeInTheDocument();
    first.unmount();

    vi.mocked(fetchAdminVisitsReport).mockResolvedValueOnce({
      data: {
        ...REPORT,
        ai: {
          available: false,
          reason: 'PermissionError',
          estimated_answer_fetches: 7,
          citation_clicks: 7,
          ai_referral_hits: 2,
        },
      },
    } as unknown as Awaited<ReturnType<typeof fetchAdminVisitsReport>>);
    render(<AdminVisitsReport days={28} onDays={vi.fn()} />);
    expect(await screen.findByText(/nginx 로그를 읽을 수 없어/)).toHaveTextContent('PermissionError');
    expect(screen.getByText(/답변 fetch 확인 불가 · 실제 유입 확인 불가/)).toBeInTheDocument();
    expect(screen.queryByText(/답변 fetch 7번/)).not.toBeInTheDocument();
  });

  it('renders traffic tiles, tables, and the AI section', async () => {
    vi.mocked(fetchAdminVisitsReport).mockResolvedValue({
      data: REPORT,
    } as unknown as Awaited<ReturnType<typeof fetchAdminVisitsReport>>);

    render(<AdminVisitsReport days={28} onDays={vi.fn()} />);

    await waitFor(() => expect(fetchAdminVisitsReport).toHaveBeenCalledWith(28, expect.any(AbortSignal)));
    expect(await screen.findByRole('heading', { name: '방문·유입' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '이번 기간을 한 문장씩 읽어보세요' })).toBeInTheDocument();
    expect(screen.getByText('12명이 30번 방문')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '도달과 이용' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'AI와 외부 유입' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '샘플에서 대화로' })).toBeInTheDocument();
    expect(await screen.findByText('방문 추이')).toBeInTheDocument();
    // Band dividers group the report.
    expect(screen.getByText('사람 방문')).toBeInTheDocument();
    expect(screen.getByText('AI · 유입')).toBeInTheDocument();
    // At-a-glance hero repeats headline numbers, so several appear twice.
    expect(screen.getAllByText('12').length).toBeGreaterThanOrEqual(1); // visitors
    expect(screen.getAllByText('60%').length).toBeGreaterThanOrEqual(1); // engaged rate
    expect(screen.getByTitle(/퍼스트파티 이벤트 표본/)).toBeInTheDocument(); // data-source line
    expect(screen.getByText(/동의 표본/)).toBeInTheDocument();
    expect(screen.getAllByText(/30분 비활동 기준 세션이 아닙니다/).length).toBeGreaterThan(0);
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
    expect(screen.queryByText('구 검색 페이지 (/?q=)')).not.toBeInTheDocument();
    expect(screen.queryByText('검색 → 딥리뷰 완료')).not.toBeInTheDocument();
    expect(screen.queryByText(/딥리뷰 결과/)).not.toBeInTheDocument();
    for (const label of ['검색', '논문 선택', '딥리뷰 시작', '딥리뷰 완료', '딥리뷰 실패', '북마크', '리포트 다운로드', '포스터 시작', '포스터 완료', '포스터 실패']) {
      expect(screen.queryByText(label, { exact: true })).not.toBeInTheDocument();
    }
    expect(screen.getByText('로그인')).toBeInTheDocument();
  }, 20_000);

  it('shows the sample funnel and a per-sample table joined to public titles, zero rows included', async () => {
    vi.mocked(fetchSampleConversations).mockResolvedValue([
      { id: 's1', slug: 'graphrag-vs-rag', title: 'GraphRAG 비교', question: 'q', asof: '2026-10-25', turn_count: 2 },
      { id: 's2', slug: 'memory-papers', title: '장기 기억 논문', question: 'q', asof: '2026-10-25', turn_count: 2 },
    ]);
    vi.mocked(fetchAdminVisitsReport).mockResolvedValue({
      data: {
        ...REPORT,
        funnels: [
          ...REPORT.funnels,
          {
            id: 'sample_to_conversation',
            label: '샘플 → CTA → 첫 대화',
            steps: [
              { event: 'sample_view', count: 20, rate: 1, drop_off: 0 },
              { event: 'sample_cta_click', count: 5, rate: 0.25, drop_off: 15 },
              { event: 'conversation_start', count: 2, rate: 0.1, drop_off: 3 },
            ],
            overall_conversion: 0.1,
          },
        ],
        samples: [{ slug: 'graphrag-vs-rag', page_views: 40, card_views: 25, cta_clicks: 6 }],
      },
    } as unknown as Awaited<ReturnType<typeof fetchAdminVisitsReport>>);

    render(<AdminVisitsReport days={28} onDays={vi.fn()} />);

    expect(await screen.findByText('샘플 → 대화')).toBeInTheDocument();
    expect(screen.getByText('동의 사용자만(하한값) · 퍼널은 홈 기본 노출 포함, 표는 카드 클릭+페이지만')).toBeInTheDocument();
    // The funnel is one inline line: count per step, rate from step 2 on.
    const funnel = screen.getByLabelText('샘플 → CTA → 첫 대화');
    expect(funnel).toHaveTextContent('샘플 노출 (홈 기본 포함) 20→이어서 묻기 클릭 525%→대화 생성 210%');
    // Funnel step 1 includes the home default; the table counts card clicks and page opens only.
    expect(screen.getByText('샘플 노출 (홈 기본 포함)')).toBeInTheDocument();
    expect(screen.getByText('샘플 조회 · 카드 클릭+페이지')).toBeInTheDocument();
    expect(screen.getByText('이어서 묻기 클릭')).toBeInTheDocument();
    expect(screen.getAllByText('대화 생성').length).toBeGreaterThan(0);
    expect(screen.queryByText('구 검색 페이지 (/?q=)')).not.toBeInTheDocument();

    const seen = (await screen.findByText('GraphRAG 비교')).closest('tr') as HTMLElement;
    // CTA rate = cta / sample_view (6 / 25); page views are the same visits seen by the router, not added.
    expect(within(seen).getAllByRole('cell').map((c) => c.textContent)).toEqual(['GraphRAG 비교', '40', '25', '6', '24%']);
    const unseen = screen.getByText('장기 기억 논문').closest('tr') as HTMLElement;
    expect(within(unseen).getAllByRole('cell').map((c) => c.textContent)).toEqual(['장기 기억 논문', '0', '0', '0', '—']);
  });

  it('surfaces the API error state', async () => {
    vi.mocked(fetchAdminVisitsReport).mockRejectedValue(new Error('boom'));
    render(<AdminVisitsReport days={28} onDays={vi.fn()} />);
    expect(await screen.findByText(/boom/)).toBeInTheDocument();
  });
});
