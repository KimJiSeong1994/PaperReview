import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import RecommendationBell from '../components/RecommendationBell';
import type { RecommendationNotification, RecommendationNotificationResponse } from '../api/recommendations';

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), mutate: vi.fn(), exposure: vi.fn(), viewer: vi.fn(), authenticated: true }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: mocks.authenticated }) }));
vi.mock('../api/recommendations', () => ({ fetchRecommendationNotifications: mocks.fetch, mutateRecommendation: mocks.mutate, recordRecommendationExposure: mocks.exposure }));
vi.mock('../utils/blogPaperReference', () => ({ viewerHrefForPaper: () => '/paper-viewer?source=recommendation', openPaperViewer: mocks.viewer }));

class Observer {
  static instances: Observer[] = [];
  elements = new Set<Element>();
  callback: IntersectionObserverCallback;
  constructor(callback: IntersectionObserverCallback) { this.callback = callback; Observer.instances.push(this); }
  observe = (element: Element) => { this.elements.add(element); };
  unobserve = (element: Element) => { this.elements.delete(element); };
  disconnect = () => { this.elements.clear(); };
  emit(ratio: number) {
    this.callback([...this.elements].map(target => ({ target, intersectionRatio: ratio, isIntersecting: ratio > 0 }) as IntersectionObserverEntry), this as unknown as IntersectionObserver);
  }
}
const paper = (key: string, rank: number, score = 1): RecommendationNotification => ({ canonical_key: key, final_rank: rank, display_position: rank, title: `Paper ${key}`, authors: ['Author'], seen: false, score, reason: '추천 이유', candidate_sources: ['local'], score_breakdown: {} });
const response = (items = [paper('a', 1, 1), paper('b', 3, 99)]): RecommendationNotificationResponse => ({ items, unread_count: 7, total_count: 12, latest_run_at: '2026-09-25T01:00:00Z', run_id: 'run-1', scoring_mode: 'v1', state: 'ready', freshness: 'fresh', source_statuses: { local: 'ready' }, degraded_reasons: [] });
const flush = async () => { await act(async () => { await Promise.resolve(); }); };
const tick = async (ms: number) => { await act(async () => { vi.advanceTimersByTime(ms); }); };
async function open() {
  const rendered = render(<MemoryRouter><RecommendationBell /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: '추천 논문 열기' }));
  await flush();
  return rendered;
}
const card = (key: string) => within(document.querySelector(`[data-canonical-key="${key}"]`)! as HTMLElement);
const observer = () => Observer.instances[Observer.instances.length - 1];

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-09-25T12:00:00Z'));
  vi.clearAllMocks(); Observer.instances = []; mocks.authenticated = true;
  const store: Record<string, string> = {};
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { Object.keys(store).forEach(key => delete store[key]); },
  });
  localStorage.setItem('access_token', 'owner-a');
  vi.stubGlobal('IntersectionObserver', Observer);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  mocks.fetch.mockResolvedValue(response());
  mocks.mutate.mockImplementation(async body => ({ tracked: true, ...body, undo_action: body.undo_action ?? null, applied_at: '2026-09-25T12:00:00Z' }));
  mocks.exposure.mockResolvedValue({ tracked: true, recorded: true });
});
afterEach(() => { cleanup(); localStorage.clear(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('RecommendationBell durable recommendation contract', () => {
  it('keeps server order and rank gaps despite scores, with separate unread/total and dates', async () => {
    mocks.fetch.mockResolvedValue(response([paper('a', 1, 1), { ...paper('b', 3, 99), publication_date: '2020-01-01' }]));
    await open();
    expect(screen.getAllByRole('article').map(element => element.getAttribute('data-canonical-key'))).toEqual(['a', 'b']);
    expect(screen.getByText('#3')).toBeInTheDocument();
    expect(screen.getByText('읽지 않음 7편')).toBeInTheDocument();
    expect(screen.getByText('전체 12편')).toBeInTheDocument();
    expect(screen.getByText(/추천 생성:/)).toBeInTheDocument();
    expect(screen.getByText(/논문 발표:/)).toBeInTheDocument();
    expect(mocks.exposure).not.toHaveBeenCalled();
  });

  it('refills from the server after hide and keeps an actionable undo receipt for the hidden key', async () => {
    await open();
    mocks.fetch.mockResolvedValue(response([paper('b', 3), paper('c', 6)]));
    fireEvent.click(card('a').getByRole('button', { name: '숨기기' })); await flush();
    expect(document.querySelector('[data-canonical-key="a"]')).toBeNull();
    expect(screen.getByText('#6')).toBeInTheDocument();
    expect(mocks.mutate.mock.calls[0][0]).toMatchObject({ run_id: 'run-1', canonical_key: 'a', action: 'hide' });
    mocks.fetch.mockResolvedValue(response());
    fireEvent.click(screen.getByRole('button', { name: '실행 취소' })); await flush();
    expect(mocks.mutate.mock.calls[1][0]).toMatchObject({ canonical_key: 'a', action: 'undo', undo_action: 'hide' });
    expect(card('a').getByText('#1')).toBeInTheDocument();
  });

  it('does not acknowledge failed writes or replace the current list', async () => {
    await open(); mocks.mutate.mockRejectedValue(new Error('offline'));
    fireEvent.click(card('a').getByRole('button', { name: '숨기기' })); await flush();
    expect(screen.getByRole('alert')).toHaveTextContent('변경을 저장하지 못했습니다');
    expect(card('a').getByText('읽지 않음')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '실행 취소' })).not.toBeInTheDocument();
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
  });

  it('clears previously valid cards when a current-owner refresh returns 503', async () => {
    await open();
    expect(screen.getAllByRole('article')).toHaveLength(2);
    mocks.fetch.mockRejectedValueOnce({ response: { status: 503 } });
    fireEvent(window, new Event('focus')); await flush();
    expect(screen.queryAllByRole('article')).toHaveLength(0);
    expect(screen.queryByText('추천 준비 완료')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('추천을 불러오지 못했습니다');
  });

  it.each([
    ['hide', '숨기기'], ['already_seen', '이미 읽은 논문'],
  ] as const)('removes acknowledged %s before reserve fetch and retains undo if fetch returns 503', async (action, label) => {
    await open();
    let rejectRefresh!: (reason: unknown) => void;
    mocks.fetch.mockReturnValueOnce(new Promise((_, reject) => { rejectRefresh = reject; }));
    fireEvent.click(card('a').getByRole('button', { name: label })); await flush();
    expect(mocks.mutate.mock.calls[0][0]).toMatchObject({ canonical_key: 'a', action });
    expect(document.querySelector('[data-canonical-key="a"]')).toBeNull();
    expect(card('b').getByText('#3')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '실행 취소' })).toBeInTheDocument();
    await act(async () => { rejectRefresh({ response: { status: 503 } }); });
    expect(screen.queryAllByRole('article')).toHaveLength(0);
    expect(screen.getByRole('alert')).toHaveTextContent('추천을 불러오지 못했습니다');
    expect(screen.getByRole('button', { name: '실행 취소' })).toBeEnabled();
    mocks.fetch.mockResolvedValue(response());
    fireEvent.click(screen.getByRole('button', { name: '실행 취소' })); await flush();
    expect(mocks.mutate.mock.calls[1][0]).toMatchObject({ run_id: 'run-1', canonical_key: 'a', action: 'undo', undo_action: action });
    expect(card('a').getByText('#1')).toBeInTheDocument();
  });

  it('marks read only after durable ack/refetch and hands canonical metadata to the viewer', async () => {
    let acknowledge!: (value: unknown) => void;
    await open(); mocks.mutate.mockReturnValue(new Promise(resolve => { acknowledge = resolve; }));
    fireEvent.click(card('a').getByRole('button', { name: 'PDF 보기' }));
    expect(mocks.viewer).toHaveBeenCalledWith('/paper-viewer?source=recommendation&result_key=a');
    expect(card('a').getByText('읽지 않음')).toBeInTheDocument();
    mocks.fetch.mockResolvedValue(response([{ ...paper('a', 1), seen: true }]));
    await act(async () => { acknowledge({ tracked: true, request_id: 'ack' }); });
    expect(mocks.mutate.mock.calls[0][0].action).toBe('seen');
    expect(card('a').getByText('읽음')).toBeInTheDocument();
  });

  it.each(['already_seen', 'topic_less', 'interested'] as const)('persists %s independently of read state', async action => {
    const labels = { already_seen: '이미 읽은 논문', topic_less: '이 주제 덜 보기', interested: '관심 있어요' };
    await open(); fireEvent.click(card('a').getByRole('button', { name: labels[action] })); await flush();
    expect(mocks.mutate.mock.calls[0][0]).toMatchObject({ action, canonical_key: 'a' });
    expect(mocks.mutate.mock.calls[0][0].request_id).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it.each([
    ['empty', '표시할 추천 논문이 없습니다.'], ['unavailable', '아직 추천을 사용할 수 없습니다.'],
    ['stale', '이전 추천입니다. 최신 추천을 기다리고 있습니다.'], ['expired', '추천 유효기간이 지났습니다.'],
    ['degraded', '일부 소스를 사용할 수 없습니다.'],
  ] as const)('reports %s without pretending success', async (state, message) => {
    mocks.fetch.mockResolvedValue({ ...response([]), state, degraded_reasons: state === 'degraded' ? ['source timeout'] : [] });
    await open(); expect(screen.getByText(message)).toBeInTheDocument();
  });

  it('refetches on reopen, focus, and date change and stops refresh on close', async () => {
    await open();
    fireEvent(window, new Event('focus')); await flush(); expect(mocks.fetch).toHaveBeenCalledTimes(2);
    vi.setSystemTime(new Date('2026-09-26T12:00:00Z')); await tick(30000); expect(mocks.fetch).toHaveBeenCalledTimes(3);
    fireEvent.click(screen.getByRole('button', { name: '닫기' })); await tick(60000); expect(mocks.fetch).toHaveBeenCalledTimes(3);
    fireEvent.click(screen.getByRole('button', { name: '추천 논문 열기' })); await flush(); expect(mocks.fetch).toHaveBeenCalledTimes(4);
  });

  it('requires continuous half visibility for a second and deduplicates without altering seen', async () => {
    await open(); observer().emit(0.49); await tick(1000); expect(mocks.exposure).not.toHaveBeenCalled();
    observer().emit(0.5); await tick(999); expect(mocks.exposure).not.toHaveBeenCalled();
    observer().emit(0.1); await tick(1); expect(mocks.exposure).not.toHaveBeenCalled();
    observer().emit(0.5); await tick(1000); expect(mocks.exposure).toHaveBeenCalledTimes(2);
    expect(mocks.exposure.mock.calls[0][0]).toMatchObject({ visible_fraction: 0.5, visible_ms: 1000, run_id: 'run-1' });
    expect(card('a').getByText('읽지 않음')).toBeInTheDocument();
    observer().emit(0.5); await tick(1000); expect(mocks.exposure).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole('button', { name: '닫기' }));
    fireEvent.click(screen.getByRole('button', { name: '추천 논문 열기' })); await flush();
    observer().emit(1); await tick(1000); expect(mocks.exposure).toHaveBeenCalledTimes(2);
  });

  it('cancels exposure on document hidden, close, and unmount', async () => {
    const view = await open(); observer().emit(1); await tick(500);
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    fireEvent(document, new Event('visibilitychange')); await tick(1000); expect(mocks.exposure).not.toHaveBeenCalled();
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    fireEvent(document, new Event('visibilitychange')); observer().emit(1); await tick(500);
    fireEvent.click(screen.getByRole('button', { name: '닫기' })); await tick(1000); expect(mocks.exposure).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '추천 논문 열기' })); await flush(); observer().emit(1);
    view.unmount(); await tick(1000); expect(mocks.exposure).not.toHaveBeenCalled();
  });

  it('discards a late owner A response after token replacement even with the same username', async () => {
    let resolveA!: (value: RecommendationNotificationResponse) => void;
    mocks.fetch.mockReturnValueOnce(new Promise(resolve => { resolveA = resolve; }));
    localStorage.setItem('username', 'same-user'); await open();
    const signalA = mocks.fetch.mock.calls[0][1] as AbortSignal;
    mocks.fetch.mockResolvedValue(response([paper('owner-b', 1)]));
    localStorage.setItem('access_token', 'recreated-owner-b');
    fireEvent(window, new Event('storage')); await flush();
    expect(signalA.aborted).toBe(true);
    await act(async () => { resolveA(response([paper('private-a', 1)])); });
    expect(screen.queryByText('Paper private-a')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Paper owner-b' })).toBeInTheDocument();
  });

  it('focuses the dialog and returns keyboard focus on Escape', async () => {
    await open(); expect(screen.getByRole('dialog')).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '추천 논문 열기' })).toHaveFocus();
  });

  it.each(['focus', 'reopen'] as const)('invalidates an expired snapshot on %s when timers were throttled', async trigger => {
    await open();
    if (trigger === 'reopen') fireEvent.click(screen.getByRole('button', { name: '닫기' }));
    // Advance wall-clock time without running the expiry or refresh timers.
    vi.setSystemTime(new Date('2026-09-25T12:01:01Z'));
    let resolveRefresh!: (value: RecommendationNotificationResponse) => void;
    mocks.fetch.mockReturnValueOnce(new Promise(resolve => { resolveRefresh = resolve; }));
    if (trigger === 'focus') fireEvent(window, new Event('focus'));
    else fireEvent.click(screen.getByRole('button', { name: '추천 논문 열기' }));
    await flush();
    expect(screen.queryAllByRole('article')).toHaveLength(0);
    await act(async () => { resolveRefresh(response([paper('fresh', 1)])); });
    expect(screen.getByRole('button', { name: 'Paper fresh' })).toBeInTheDocument();
  });

  it('remounts session state on auth lifecycle changes even when the token string is unchanged', async () => {
    const view = await open();
    fireEvent.click(card('a').getByRole('button', { name: '관심 있어요' })); await flush();
    expect(screen.getByRole('button', { name: '실행 취소' })).toBeInTheDocument();
    const oldSignal = mocks.fetch.mock.calls[0][1] as AbortSignal;
    mocks.authenticated = false;
    view.rerender(<MemoryRouter><RecommendationBell /></MemoryRouter>);
    expect(oldSignal.aborted).toBe(true);
    expect(screen.queryAllByRole('article')).toHaveLength(0);
    mocks.authenticated = true;
    mocks.fetch.mockResolvedValue(response([paper('new-session', 1)]));
    view.rerender(<MemoryRouter><RecommendationBell /></MemoryRouter>); await flush();
    expect(screen.queryByRole('button', { name: '실행 취소' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Paper new-session' })).toBeInTheDocument();
  });

  it('aborts synchronously in the storage event before React commits the replacement session', async () => {
    await open();
    const oldSignal = mocks.fetch.mock.calls[0][1] as AbortSignal;
    observer().emit(1);
    localStorage.setItem('access_token', 'owner-b');
    act(() => {
      window.dispatchEvent(new Event('storage'));
      expect(oldSignal.aborted).toBe(true);
      expect(observer().elements.size).toBe(0);
    });
    await flush();
    expect(mocks.exposure).not.toHaveBeenCalled();
  });

  it('reports initial fetch failure and retries without inventing an empty success', async () => {
    mocks.fetch.mockRejectedValueOnce(new Error('unavailable'));
    await open();
    expect(screen.getByRole('alert')).toHaveTextContent('추천을 불러오지 못했습니다');
    expect(screen.queryByText('추천 준비 완료')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' })); await flush();
    expect(screen.getByRole('button', { name: 'Paper a' })).toBeInTheDocument();
  });

  it('labels metadata-only cold start without claiming personalized scoring', async () => {
    mocks.fetch.mockResolvedValue({ ...response(), scoring_mode: 'metadata' });
    await open();
    expect(screen.getByText('개인화 정보가 부족해 논문 메타데이터를 기준으로 추천합니다.')).toBeInTheDocument();
  });

  it('allows exposure again on a new day without converting exposure to read', async () => {
    await open(); observer().emit(0.5); await tick(1000);
    vi.setSystemTime(new Date('2026-09-26T12:00:00Z'));
    fireEvent(window, new Event('focus')); await flush();
    observer().emit(0.5); await tick(1000);
    expect(mocks.exposure).toHaveBeenCalledTimes(4);
    expect(mocks.mutate).not.toHaveBeenCalled();
    expect(card('a').getByText('읽지 않음')).toBeInTheDocument();
  });

  it('discards late mutation receipts and cancels exposure when authentication changes', async () => {
    let acknowledge!: (value: unknown) => void;
    await open();
    mocks.mutate.mockReturnValueOnce(new Promise(resolve => { acknowledge = resolve; }));
    fireEvent.click(card('a').getByRole('button', { name: '숨기기' }));
    observer().emit(1); await tick(500);
    localStorage.setItem('access_token', 'owner-b');
    mocks.fetch.mockResolvedValue(response([paper('b-only', 1)]));
    fireEvent(window, new Event('storage')); await flush();
    await act(async () => { acknowledge({ tracked: true, request_id: 'late-a' }); });
    await tick(1000);
    expect(screen.queryByRole('button', { name: '실행 취소' })).not.toBeInTheDocument();
    expect(mocks.exposure).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Paper b-only' })).toBeInTheDocument();
  });
});
