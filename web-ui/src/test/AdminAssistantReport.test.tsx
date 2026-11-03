import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import AdminAssistantReport from '../components/AdminAssistantReport';
import {
  fetchAdminConversationStats,
  fetchAdminLlmUsage,
  fetchAdminSoulStats,
  type AdminConversationStats,
  type AdminLlmUsage,
  type AdminSoulStats,
} from '../api/client';

vi.mock('../PlotlyChart', () => ({ default: () => <div data-testid="plot" /> }));
vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    fetchAdminConversationStats: vi.fn(),
    fetchAdminSoulStats: vi.fn(),
    fetchAdminLlmUsage: vi.fn(),
  };
});

const WINDOW = { days: 7 as const, start: '2026-10-27T15:00:00+00:00', end: '2026-11-03T12:00:00+00:00', timezone: 'Asia/Seoul' };

// Shapes copied from spec C-1..C-3. 2026-11-03T12:00Z is 21:00 KST, so "yesterday" is 2026-11-02.
const CONVERSATIONS: AdminConversationStats = {
  window: WINDOW,
  totals: { conversations: 28, user_turns: 82, assistant_turns: 81, active_users: 6, running: 1 },
  outcomes: { done: 76, failed: 3, cancelled: 2, interrupted: 1 },
  error_rate: 0.05,
  latency: [
    { intent: 'search', samples: 22, p50_ms: 14000, p95_ms: 31000 },
    { intent: 'review', samples: 3, p50_ms: 900, p95_ms: null },
  ],
  intents: [
    { intent: 'search', turns: 22, failed: 2, interrupted: 1 },
    { intent: 'chat', turns: 40, failed: 0, interrupted: 0 },
  ],
  reviews: {
    started: 7,
    by_mode: { fast: 5, full: 2 },
    mode_missing: 4,
    outcomes: { completed: 6, failed: 0, running: 0, unknown: 1 },
    verification: {
      sessions_with_claims: 2, claims: 30,
      verified: 25, partially_verified: 5, unverified: 0, contradicted: 0,
      verified_ratio: 0.833,
    },
  },
  activation: { signups: 3, first_conversation_within_24h: 2 },
  daily: [
    { date: '2026-11-01', conversations: 4, user_turns: 10, active_users: 2, failed: 0 },
    { date: '2026-11-02', conversations: 8, user_turns: 33, active_users: 3, failed: 1 },
    { date: '2026-11-03', conversations: 2, user_turns: 5, active_users: 1, failed: 0 },
  ],
  metric_definitions: {},
};

const SOULS: AdminSoulStats = {
  window: WINDOW,
  accounts: { with_soul: 4, with_memories: 4, with_user_md: 1 },
  memories: {
    total: 38, new_in_window: 12, interest_avg_hits: 1.5,
    by_kind: [
      { kind: 'preference', count: 12, accounts: 3 },
      { kind: 'topic', count: 0, accounts: 0 },
      { kind: 'paper', count: 8, accounts: 2 },
      { kind: 'fact', count: 0, accounts: 0 },
      { kind: 'research', count: 6, accounts: 2 },
      { kind: 'interest', count: 12, accounts: 4 },
    ],
  },
  profiles: { total: 3, stale_over_24h: 1, with_role: 2, with_domain: 2, with_keywords: 3 },
  metric_definitions: {},
};

const LLM: AdminLlmUsage = {
  available: true,
  window: WINDOW,
  ledger: { first_at: '2026-10-31T00:00:00+00:00', last_at: '2026-11-02T00:00:00+00:00', malformed_lines: 0 },
  totals: { calls: 148, prompt_tokens: 180000, completion_tokens: 23000, cached_tokens: 0 },
  by_stage: [{ stage: 'fast_review', model: 'gpt-x', calls: 10, prompt_tokens: 60000, completion_tokens: 5400 }],
  daily: [{ date: '2026-11-02', prompt_tokens: 90000, completion_tokens: 11000 }],
  coverage: { unrecorded_stages: [] },
  metric_definitions: {},
};

const ok = <T,>(data: T) => Promise.resolve({ data } as never);

beforeEach(() => {
  vi.mocked(fetchAdminConversationStats).mockImplementation(() => ok(CONVERSATIONS));
  vi.mocked(fetchAdminSoulStats).mockImplementation(() => ok(SOULS));
  vi.mocked(fetchAdminLlmUsage).mockImplementation(() => ok(LLM));
});

// jsdom's localStorage is broken in this setup (see AdminPage.members.test); rows persist through this shim.
let store: Record<string, string> = {};
beforeEach(() => {
  store = {};
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = String(value); },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  });
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

const tile = (label: string) => screen.getByText(label, { selector: '.assistant-kpi-label' }).closest('.assistant-kpi') as HTMLElement;
const row = (title: string) => screen.getByText(title, { selector: '.admin-details-title' }).closest('details') as HTMLDetailsElement;
const summary = (title: string) => row(title).querySelector('.admin-details-summary')?.textContent;
const openRow = (title: string) => fireEvent.click(row(title).querySelector('summary')!);
const loaded = () => screen.findByText('어제 8 · 실패 1');

describe('AdminAssistantReport', () => {
  it('puts eight KPI tiles in one strip, with yesterday and activation as hints', async () => {
    render(<AdminAssistantReport />);
    await loaded();

    expect(screen.getByRole('heading', { level: 1, name: '대시보드' })).toBeInTheDocument();
    expect(screen.getByText('2026-10-28 — 2026-11-03 · KST')).toBeInTheDocument();
    const strip = screen.getByRole('group', { name: '핵심 지표' });
    expect(strip.querySelectorAll('.assistant-kpi')).toHaveLength(8);

    const value = (label: string) => tile(label).querySelector('.assistant-kpi-value')?.textContent;
    const hint = (label: string) => tile(label).querySelector('.assistant-kpi-hint')?.textContent;
    expect(value('대화')).toBe('28');
    expect(tile('대화')).toHaveAttribute('title', expect.stringContaining('어제(2026-11-02) 대화 8 · 메시지 33 · 실패 1'));
    expect([value('활성 사용자'), hint('활성 사용자')]).toEqual(['6', '가입 3 · 24h 대화 2']);
    expect(value('사용자 메시지')).toBe('82');
    expect([value('실패율'), hint('실패율')]).toEqual(['5.0%', '실패 3 · 중단 1 · 취소 2']);
    expect(value('정밀 리뷰 비율')).toBe('28.6%'); // 2 / 7
    expect([value('검증된 주장 비율'), hint('검증된 주장 비율')]).toEqual(['83.3%', '주장 30 중 25']);
    expect([value('메모리 보유 계정'), hint('메모리 보유 계정')]).toEqual(['4', '메모리 38 · 신규 12']);
    expect([value('LLM 토큰'), hint('LLM 토큰')]).toEqual(['203,000', '호출 148']);
  });

  it('shows the daily chart beside intent bars and per-intent latency', async () => {
    render(<AdminAssistantReport />);
    await loaded();

    expect(await screen.findAllByTestId('plot')).toHaveLength(1);
    expect(screen.getByText('실패 3').parentElement).toHaveTextContent('검색실패 3');
    const latency = screen.getByRole('region', { name: '의도별 지연 표' });
    const searchRow = within(latency).getByRole('rowheader', { name: '검색' }).closest('tr') as HTMLElement;
    expect(within(searchRow).getAllByRole('cell').map((c) => c.textContent)).toEqual(['22', '14.0초', '31.0초']);
  });

  it('caps the intent and latency lists at six rows', async () => {
    const intents = ['chat', 'clarify', 'search', 'answer', 'review', 'open_pdf', 'highlight_pdf', 'answer_from_bookmarks'];
    vi.mocked(fetchAdminConversationStats).mockImplementation(() => ok({
      ...CONVERSATIONS,
      intents: intents.map((intent) => ({ intent, turns: 3, failed: 0, interrupted: 0 })),
      latency: intents.map((intent) => ({ intent, samples: 6, p50_ms: 1000, p95_ms: 2000 })),
    }));
    render(<AdminAssistantReport />);
    await loaded();
    expect(document.querySelectorAll('.assistant-mini-bars li')).toHaveLength(6);
    expect(within(screen.getByRole('region', { name: '의도별 지연 표' })).getAllByRole('row')).toHaveLength(7);
  });

  it('collapses every detail row by default, with the numbers in its summary', async () => {
    render(<AdminAssistantReport />);
    await loaded();
    await screen.findByText(/^계정 4/);

    for (const title of ['리뷰 모드·검증', '메모리·연구 프로필', 'LLM 사용량']) expect(row(title).open).toBe(false);
    expect(summary('리뷰 모드·검증')).toBe('시작 7 · 빠른 5 · 정밀 2 · 검증 83%');
    expect(summary('메모리·연구 프로필')).toBe('계정 4 · 메모리 38 · 프로필 3 (24h 지남 1)');
    expect(summary('LLM 사용량')).toBe('호출 148 · 토큰 203,000');
    // Closed rows mount nothing: no verification card until opened.
    expect(screen.queryByText(/주장 30개 중 확인/)).toBeNull();
  });

  it('opens a row to show its detail and remembers it', async () => {
    const { unmount } = render(<AdminAssistantReport />);
    await loaded();

    openRow('리뷰 모드·검증');
    expect(await screen.findByText(/주장 30개 중 확인 25\(83\.3%\)/)).toBeInTheDocument();
    expect(screen.getByText('모드 기록이 없는 옛 리뷰 4건은 빠른 리뷰로 셉니다.')).toBeInTheDocument();
    expect(store['admin.dashboard.open.reviews']).toBe('1');
    unmount();

    render(<AdminAssistantReport />);
    await loaded();
    expect(row('리뷰 모드·검증').open).toBe(true);
    expect(row('LLM 사용량').open).toBe(false);
  });

  it('renders the legacy slot at the end of the row list', async () => {
    render(<AdminAssistantReport legacy={<div data-testid="legacy-rows" />} />);
    await loaded();
    const list = document.querySelector('.admin-details-list')!;
    expect(list.lastElementChild).toBe(screen.getByTestId('legacy-rows'));
  });

  it('shows — for null error rate and null p95, not 0', async () => {
    vi.mocked(fetchAdminConversationStats).mockImplementation(() => ok({ ...CONVERSATIONS, error_rate: null }));
    render(<AdminAssistantReport />);
    await loaded();

    expect(tile('실패율').querySelector('.assistant-kpi-value')?.textContent).toBe('—');
    const reviewRow = within(screen.getByRole('region', { name: '의도별 지연 표' }))
      .getByRole('rowheader', { name: '리뷰 시작' }).closest('tr') as HTMLElement;
    expect(within(reviewRow).getAllByRole('cell').map((cell) => cell.textContent)).toEqual(['3', '0.9초', '—']);
  });

  it('keeps other blocks when one endpoint fails and retries only that one inline', async () => {
    vi.mocked(fetchAdminSoulStats).mockImplementationOnce(() => Promise.reject(new Error('boom')));
    render(<AdminAssistantReport />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('메모리 통계을(를) 불러오지 못했습니다 · boom');
    await loaded();
    expect(tile('메모리 보유 계정').querySelector('.assistant-kpi-value')?.textContent).toBe('—');
    expect(summary('메모리·연구 프로필')).toBe('불러오지 못했습니다');
    expect(tile('LLM 토큰').querySelector('.assistant-kpi-value')?.textContent).toBe('203,000');

    fireEvent.click(within(alert).getByRole('button', { name: '다시 시도' }));
    await waitFor(() => expect(tile('메모리 보유 계정').querySelector('.assistant-kpi-value')?.textContent).toBe('4'));
    expect(fetchAdminSoulStats).toHaveBeenCalledTimes(2);
    expect(fetchAdminConversationStats).toHaveBeenCalledTimes(1);
    expect(fetchAdminLlmUsage).toHaveBeenCalledTimes(1);
  });

  it('shows the empty verification message inside the review row', async () => {
    vi.mocked(fetchAdminConversationStats).mockImplementation(() => ok({
      ...CONVERSATIONS,
      reviews: { ...CONVERSATIONS.reviews, verification: { ...CONVERSATIONS.reviews.verification, sessions_with_claims: 0, claims: 0, verified_ratio: null } },
    }));
    render(<AdminAssistantReport />);
    await loaded();
    expect(tile('검증된 주장 비율').querySelector('.assistant-kpi-hint')?.textContent).toBe('검증 기록 없음');
    expect(summary('리뷰 모드·검증')).toBe('시작 7 · 빠른 5 · 정밀 2 · 검증 —');
    openRow('리뷰 모드·검증');
    expect(await screen.findByText('정밀 리뷰 검증 기록이 아직 없습니다')).toBeInTheDocument();
  });

  it('shows unavailable ledger state in the summary and the unrecorded-stage warning inside', async () => {
    vi.mocked(fetchAdminLlmUsage).mockImplementation(() => ok({
      ...LLM, available: false, reason: 'ledger not found', by_stage: [], daily: [],
      coverage: { unrecorded_stages: ['claim_verification'] },
    }));
    render(<AdminAssistantReport />);
    await loaded();

    expect(summary('LLM 사용량')).toBe('사용량 원장 파일이 없습니다');
    expect(tile('LLM 토큰').querySelector('.assistant-kpi-hint')?.textContent).toBe('원장 없음');
    openRow('LLM 사용량');
    expect(await screen.findByText('일부 단계 미집계: 주장 검증')).toBeInTheDocument();
  });

  it('falls back to the raw reason for an unmapped ledger state', async () => {
    vi.mocked(fetchAdminLlmUsage).mockImplementation(() => ok({ ...LLM, available: false, reason: 'permission denied', by_stage: [], daily: [] }));
    render(<AdminAssistantReport />);
    await loaded();
    expect(summary('LLM 사용량')).toBe('사용량 원장을 읽을 수 없습니다 (permission denied)');
  });

  it('renders zeros as an empty structure without NaN', async () => {
    vi.mocked(fetchAdminConversationStats).mockImplementation(() => ok({
      ...CONVERSATIONS,
      totals: { conversations: 0, user_turns: 0, assistant_turns: 0, active_users: 0, running: 0 },
      outcomes: { done: 0, failed: 0, cancelled: 0, interrupted: 0 },
      error_rate: null, latency: [], intents: [],
      reviews: {
        started: 0, by_mode: { fast: 0, full: 0 }, mode_missing: 0,
        outcomes: { completed: 0, failed: 0, running: 0, unknown: 0 },
        verification: { sessions_with_claims: 0, claims: 0, verified: 0, partially_verified: 0, unverified: 0, contradicted: 0, verified_ratio: null },
      },
      activation: { signups: 0, first_conversation_within_24h: 0 },
      daily: CONVERSATIONS.daily.map((d) => ({ ...d, conversations: 0, user_turns: 0, active_users: 0, failed: 0 })),
    }));
    render(<AdminAssistantReport />);

    await screen.findByText('어제 0 · 실패 0');
    openRow('리뷰 모드·검증');
    expect(await screen.findByText('대화에서 시작된 리뷰가 아직 없습니다.')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/NaN|Infinity|undefined/);
    expect(tile('정밀 리뷰 비율').querySelector('.assistant-kpi-value')?.textContent).toBe('—');
  });

  it('refetches all three endpoints when the window toggle changes', async () => {
    render(<AdminAssistantReport />);
    await loaded();
    expect(screen.getByRole('button', { name: '7일' })).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByRole('button', { name: '28일' }));

    await waitFor(() => {
      expect(fetchAdminConversationStats).toHaveBeenLastCalledWith(28, expect.any(AbortSignal));
      expect(fetchAdminSoulStats).toHaveBeenLastCalledWith(28, expect.any(AbortSignal));
      expect(fetchAdminLlmUsage).toHaveBeenLastCalledWith(28, expect.any(AbortSignal));
    });
    expect(screen.getByRole('button', { name: '28일' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('never renders conversation or memory text, rows open included', async () => {
    // Fields the contract forbids; if a backend ever leaked them, the UI must still not show them.
    vi.mocked(fetchAdminConversationStats).mockImplementation(() => ok({ ...CONVERSATIONS, title: 'SECRET-title', content: 'SECRET-turn' }));
    vi.mocked(fetchAdminSoulStats).mockImplementation(() => ok({ ...SOULS, text: 'SECRET-memory', user_md: 'SECRET-usermd' }));
    render(<AdminAssistantReport />);
    await loaded();
    await screen.findByText(/^계정 4/);
    for (const title of ['리뷰 모드·검증', '메모리·연구 프로필', 'LLM 사용량']) openRow(title);
    await screen.findByText('종류별 메모리');
    expect(document.body.textContent).not.toContain('SECRET');
  });
});
