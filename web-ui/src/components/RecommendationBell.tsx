import { useEffect, useId, useRef, useState, type Dispatch, type RefObject, type SetStateAction } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { openPaperViewer, viewerHrefForPaper } from '../utils/blogPaperReference';
import {
  fetchRecommendationNotifications, mutateRecommendation, recordRecommendationExposure,
  type RecommendationAction, type RecommendationNotification,
  type RecommendationNotificationResponse,
} from '../api/recommendations';
import './RecommendationBell.css';

const labels: Record<RecommendationAction, string> = {
  hide: '숨기기', already_seen: '이미 읽은 논문', topic_less: '이 주제 덜 보기', interested: '관심 있어요', seen: '읽음 표시',
};
const stateLabels: Record<RecommendationNotificationResponse['state'], string> = {
  ready: '추천 준비 완료', empty: '표시할 추천 논문이 없습니다.', degraded: '일부 소스를 사용할 수 없습니다.',
  stale: '이전 추천입니다. 최신 추천을 기다리고 있습니다.', expired: '추천 유효기간이 지났습니다.',
  unavailable: '아직 추천을 사용할 수 없습니다.',
};
const sourceLabels: Record<string, string> = { local_public: '공개 논문', owner_local: '내 자료', openclaw: 'OpenClaw' };
const sourceStatusLabels: Record<string, string> = {
  ready: '사용 가능', empty: '후보 없음', disabled: '사용 안 함', degraded: '일부 수집',
  error: '수집 실패', missing: '수집 대기', invalid: '검증 실패', stale: '갱신 필요',
};
const scoringLabels: Record<string, string> = {
  v1: '관심사 기반', v2: '활동·관심사 기반', v1_fallback: '기본 관심사 기반', metadata: '논문 정보 기반',
};
function day() { return new Date().toLocaleDateString('en-CA'); }
function paperDescription(abstract?: string | null) {
  const text = abstract?.replace(/\s+/g, ' ').trim();
  if (!text) return '이 논문은 초록이 제공되지 않아 설명을 표시할 수 없습니다.';
  const characters = Array.from(text);
  return characters.length > 280 ? `${characters.slice(0, 280).join('').trimEnd()}…` : text;
}
function date(value?: string | null) {
  if (!value) return '없음';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('ko-KR');
}
interface UndoReceipt { owner: string; run: string; key: string; title: string; action: RecommendationAction; id: string }

function PaperActionControls({ item, pending, canMutate, onView, onSearch, onAction }: {
  item: RecommendationNotification;
  pending: boolean;
  canMutate: boolean;
  onView: () => void;
  onSearch: () => void;
  onAction: (action: RecommendationAction) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const controlsId = useId();
  return <>
    <div className="recommendation-card-toolbar" aria-label={`${item.title} 작업`}>
      <button type="button" className="recommendation-action-primary" disabled={pending} onClick={onView}>PDF 보기</button>
      <button type="button" aria-expanded={expanded} aria-controls={controlsId} onClick={() => setExpanded(value => !value)}>더보기</button>
    </div>
    {expanded && <div id={controlsId} className="recommendation-secondary-actions" role="group" aria-label={`${item.title} 추가 작업`}>
      <button type="button" onClick={onSearch}>관련 검색</button>
      {(['interested', 'seen', 'already_seen', 'topic_less', 'hide'] as const).map(action => (
        <button type="button" key={action} disabled={pending || !canMutate || (action === 'seen' && item.seen)} onClick={() => onAction(action)}>{labels[action]}</button>
      ))}
      <p className="recommendation-meta">변경 후 실행 취소할 수 있습니다.</p>
      <p className="recommendation-meta" aria-label="논문 수집 경로">출처: {item.candidate_sources.map(source => sourceLabels[source] ?? source).join(', ')}</p>
    </div>}
  </>;
}

export default function RecommendationBell() {
  const { isAuthenticated } = useAuth();
  const [identity, setIdentity] = useState(() => ({ token: localStorage.getItem('access_token'), generation: 0 }));
  const [open, setOpen] = useState(false);
  const observedToken = useRef(identity.token);
  const sessionRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const sync = () => {
      const token = localStorage.getItem('access_token');
      if (token === observedToken.current) return;
      sessionRef.current?.abort();
      observedToken.current = token;
      setIdentity(current => ({ token, generation: current.generation + 1 }));
    };
    const logout = () => {
      sessionRef.current?.abort();
      observedToken.current = null;
      setIdentity(current => ({ token: null, generation: current.generation + 1 }));
    };
    const timer = window.setInterval(sync, 1000);
    window.addEventListener('storage', sync);
    window.addEventListener('focus', sync);
    window.addEventListener('auth:logout', logout);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('storage', sync);
      window.removeEventListener('focus', sync);
      window.removeEventListener('auth:logout', logout);
    };
  }, []);

  return <RecommendationSession
    key={`${identity.generation}:${isAuthenticated}:${identity.token ?? ''}`}
    owner={identity.token}
    isAuthenticated={isAuthenticated}
    open={open}
    setOpen={setOpen}
    sessionRef={sessionRef}
  />;
}

function RecommendationSession({ owner, isAuthenticated, open, setOpen, sessionRef }: {
  owner: string | null;
  isAuthenticated: boolean;
  open: boolean;
  setOpen: Dispatch<SetStateAction<boolean>>;
  sessionRef: RefObject<AbortController | null>;
}) {
  const navigate = useNavigate();
  const [snapshot, setSnapshot] = useState<{ owner: string; receivedAt: number; data: RecommendationNotificationResponse } | null>(null);
  const data = snapshot?.owner === owner ? snapshot.data : null;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [receipts, setReceipts] = useState<UndoReceipt[]>([]);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const refresh = useRef<() => Promise<void>>(async () => {});
  const requestVersion = useRef(0);
  const mutating = useRef(false);
  const exposed = useRef(new Set<string>());
  const authenticated = isAuthenticated && !!owner && owner === localStorage.getItem('access_token');

  useEffect(() => {
    if (!snapshot) return;
    const timer = window.setTimeout(() => setSnapshot(current => current === snapshot ? null : current), Math.max(0, 60000 - (Date.now() - snapshot.receivedAt)));
    return () => window.clearTimeout(timer);
  }, [snapshot]);

  useEffect(() => {
    const invalidateExpired = () => {
      const now = Date.now();
      setSnapshot(current => current && now - current.receivedAt >= 60000 ? null : current);
    };
    window.addEventListener('focus', invalidateExpired);
    return () => window.removeEventListener('focus', invalidateExpired);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    sessionRef.current = controller;
    return () => controller.abort();
  }, [sessionRef]);

  useEffect(() => {
    if (!open || !authenticated) return;
    const controller = sessionRef.current!;
    let active = true;
    let lastDay = day();
    const valid = () => active && !controller.signal.aborted && owner === localStorage.getItem('access_token');
    const load = async () => {
      if (!valid()) return;
      const now = Date.now();
      setSnapshot(current => current && now - current.receivedAt >= 60000 ? null : current);
      const version = ++requestVersion.current;
      setLoading(true);
      try {
        const result = await fetchRecommendationNotifications(5, controller.signal);
        if (valid() && version === requestVersion.current) { setSnapshot({ owner: owner!, receivedAt: Date.now(), data: result }); setError(null); }
      } catch {
        if (valid() && version === requestVersion.current) {
          setSnapshot(null);
          setError('추천을 불러오지 못했습니다. 다시 시도해 주세요.');
        }
      } finally {
        if (valid() && version === requestVersion.current) setLoading(false);
      }
    };
    refresh.current = load;
    void load();
    const focus = () => { if (!mutating.current) void load(); };
    const timer = window.setInterval(() => {
      const today = day();
      if (today !== lastDay) { lastDay = today; exposed.current.clear(); }
      if (!mutating.current) void load();
    }, 30000);
    window.addEventListener('focus', focus);
    const stop = () => { active = false; window.clearInterval(timer); window.removeEventListener('focus', focus); };
    controller.signal.addEventListener('abort', stop, { once: true });
    return () => {
      stop();
      controller.signal.removeEventListener('abort', stop);
    };
  }, [open, authenticated, owner, sessionRef]);

  useEffect(() => {
    if (!open) return;
    panelRef.current?.focus();
    const outside = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); buttonRef.current?.focus(); }
    };
    document.addEventListener('mousedown', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('mousedown', outside); document.removeEventListener('keydown', escape); };
  }, [open, setOpen]);

  useEffect(() => {
    if (!open || !authenticated || !data?.run_id || !panelRef.current || typeof IntersectionObserver === 'undefined') return;
    const controller = sessionRef.current!;
    const run = data.run_id;
    const timers = new Map<Element, number>();
    const fractions = new Map<Element, number>();
    const cancel = (element: Element) => { window.clearTimeout(timers.get(element)); timers.delete(element); };
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        fractions.set(entry.target, entry.intersectionRatio);
        if (!entry.isIntersecting || entry.intersectionRatio < 0.5 || document.visibilityState !== 'visible') {
          cancel(entry.target); continue;
        }
        if (timers.has(entry.target)) continue;
        const key = entry.target.getAttribute('data-canonical-key')!;
        const exposureDay = day();
        const dedup = `${run}/${key}/${exposureDay}`;
        if (exposed.current.has(dedup)) continue;
        timers.set(entry.target, window.setTimeout(() => {
          timers.delete(entry.target);
          if (controller.signal.aborted || owner !== localStorage.getItem('access_token') || document.visibilityState !== 'visible' || day() !== exposureDay) return;
          exposed.current.add(dedup);
          void recordRecommendationExposure({ run_id: run, canonical_key: key, visible_fraction: fractions.get(entry.target)!, visible_ms: 1000 }, controller.signal)
            .catch(() => { if (!controller.signal.aborted) exposed.current.delete(dedup); });
        }, 1000));
      }
    }, { threshold: [0, 0.5, 1] });
    const elements = panelRef.current.querySelectorAll('[data-canonical-key]');
    elements.forEach(element => observer.observe(element));
    const visibility = () => {
      timers.forEach((_, element) => cancel(element));
      observer.disconnect();
      if (document.visibilityState === 'visible') elements.forEach(element => observer.observe(element));
    };
    document.addEventListener('visibilitychange', visibility);
    const stop = () => {
      observer.disconnect(); timers.forEach((_, element) => cancel(element));
      document.removeEventListener('visibilitychange', visibility);
    };
    controller.signal.addEventListener('abort', stop, { once: true });
    return () => {
      stop();
      controller.signal.removeEventListener('abort', stop);
    };
  }, [open, authenticated, data, owner, sessionRef]);

  const act = async (item: { canonical_key: string; title: string }, action: RecommendationAction | 'undo', receipt?: UndoReceipt) => {
    const run = receipt?.run ?? data?.run_id;
    const controller = sessionRef.current;
    if (!run || !authenticated || !controller || controller.signal.aborted || mutating.current) return;
    mutating.current = true; setPending(true); setLoading(false); setError(null);
    requestVersion.current++;
    const valid = () => !controller.signal.aborted && owner === localStorage.getItem('access_token');
    try {
      const result = await mutateRecommendation({ run_id: run, canonical_key: item.canonical_key, action, request_id: crypto.randomUUID(), ...(receipt ? { undo_action: receipt.action } : {}) }, controller.signal);
      if (!valid()) return;
      if (!result.tracked) throw new Error('Unacknowledged mutation');
      if (action === 'hide' || action === 'already_seen') {
        setSnapshot(current => {
          if (!current || current.owner !== owner || current.data.run_id !== run) return current;
          const removed = current.data.items.find(value => value.canonical_key === item.canonical_key);
          if (!removed) return current;
          return {
            ...current,
            data: {
              ...current.data,
              items: current.data.items.filter(value => value.canonical_key !== item.canonical_key),
              total_count: Math.max(0, current.data.total_count - 1),
              unread_count: Math.max(0, current.data.unread_count - (removed.seen ? 0 : 1)),
            },
          };
        });
      }
      if (action === 'undo') setReceipts(current => current.filter(value => value.id !== receipt?.id));
      else setReceipts(current => [...current, { owner: owner!, run, key: item.canonical_key, title: item.title, action, id: result.request_id }]);
      await refresh.current();
      if (action === 'hide') panelRef.current?.focus();
    } catch {
      if (valid()) setError('변경을 저장하지 못했습니다. 다시 시도해 주세요.');
    } finally {
      if (valid()) { mutating.current = false; setPending(false); }
    }
  };
  const view = (item: RecommendationNotification) => {
    if (!authenticated) return;
    const href = viewerHrefForPaper(item, 'recommendation');
    openPaperViewer(`${href}&result_key=${encodeURIComponent(item.canonical_key)}`);
    void act(item, 'seen');
  };
  const receiptItems = receipts.filter(receipt => receipt.owner === owner).map(receipt => (
    <div key={receipt.id}>
      <span title={receipt.title}>{labels[receipt.action]} · {receipt.title}</span>
      <button type="button" disabled={pending} onClick={() => void act({ canonical_key: receipt.key, title: receipt.title }, 'undo', receipt)}>실행 취소</button>
    </div>
  ));

  return (
    <div className="recommendation-bell" ref={rootRef}>
      <button className={`recommendation-bell-btn ${open ? 'recommendation-bell-btn-active' : ''}`} type="button" aria-haspopup="dialog" aria-expanded={open} aria-label="추천 논문 열기" onClick={() => {
        const now = Date.now();
        setSnapshot(current => current && now - current.receivedAt >= 60000 ? null : current);
        setOpen(value => !value);
      }} ref={buttonRef}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg>
        {authenticated && (data?.unread_count ?? 0) > 0 && <span className="recommendation-bell-dot" aria-hidden="true" />}
      </button>
      {open && <section className="recommendation-panel" role="dialog" aria-label="추천 논문" tabIndex={-1} ref={panelRef}>
        <div className="recommendation-panel-header"><div><p className="recommendation-eyebrow">오늘의 추천</p><h2>추천 논문 Top 5</h2></div><button type="button" onClick={() => { setOpen(false); buttonRef.current?.focus(); }}>닫기</button></div>
        {!authenticated ? <p className="recommendation-empty">로그인 후 추천을 확인해 주세요.</p> : <>
          {data && <>
            <p className="recommendation-meta">추천 생성: {date(data.latest_run_at)}</p>
            <div className="recommendation-summary" aria-label="추천 요약"><span>읽지 않음 {data.unread_count}편</span><span>전체 {data.total_count}편</span><span>상위 {Math.min(data.items.length, 5)}편 표시</span></div>
            <p className="recommendation-status" role="status">{data.freshness === 'missing' && !data.run_id && data.state === 'empty' ? '아직 추천이 생성되지 않았습니다.' : data.state === 'degraded' && data.items.length > 0 ? '수집 범위가 제한되어 검증된 논문만 표시합니다.' : stateLabels[data.state]}{data.freshness === 'stale' && data.state !== 'stale' ? ' 이전 추천입니다.' : ''}{data.freshness === 'expired' && data.state !== 'expired' ? ' 추천 유효기간이 지났습니다.' : ''}</p>
            <details className="recommendation-details">
              <summary>추천 기준 및 수집 상태</summary>
              {data.scoring_mode === 'metadata' && <p className="recommendation-meta">개인화 정보가 부족해 논문 메타데이터를 기준으로 추천합니다.</p>}
              {data.scoring_mode === 'v1_fallback' && <p className="recommendation-meta">대체 추천 방식으로 표시합니다.</p>}
              {data.scoring_mode && <p className="recommendation-meta">추천 방식: {scoringLabels[data.scoring_mode]}</p>}
              <div className="recommendation-signals" aria-label="소스 상태">{Object.entries(data.source_statuses).map(([source, status]) => <span key={source}>{sourceLabels[source] ?? source}: {sourceStatusLabels[status] ?? status}</span>)}</div>
              {data.degraded_reasons.length > 0 && <p className="recommendation-meta">진단 코드: {data.degraded_reasons.join(' · ')}</p>}
            </details>
          </>}
          {loading && <p role="status">추천을 불러오는 중...</p>}
          {error && <div className="recommendation-error" role="alert">{error}<button type="button" disabled={pending} onClick={() => void refresh.current()}>다시 시도</button></div>}
          <div className="recommendation-receipts" aria-label="최근 변경" aria-live="polite">{receiptItems.slice(-1)}</div>
          {receiptItems.length > 1 && <details className="recommendation-details"><summary>이전 변경 {receiptItems.length - 1}건</summary><div className="recommendation-receipts" aria-label="이전 변경">{receiptItems.slice(0, -1)}</div></details>}
          <div className="recommendation-list">{data?.items.slice(0, 5).map(item => <article className="recommendation-item" key={item.canonical_key} data-canonical-key={item.canonical_key}>
            <div className="recommendation-item-topline"><strong>#{item.final_rank}</strong><span>{item.seen ? '읽음' : '읽지 않음'}</span></div>
            <h3><button className="recommendation-title" type="button" disabled={pending} onClick={() => view(item)}>{item.title}</button></h3>
            <p className="recommendation-meta">{[item.authors.slice(0, 2).join(', '), item.publication_date || item.year, item.venue].filter(Boolean).join(' · ')}</p>
            <p className="recommendation-description">{paperDescription(item.abstract)}</p>
            <PaperActionControls item={item} pending={pending} canMutate={!!data?.run_id}
              onView={() => view(item)}
              onSearch={() => { setOpen(false); navigate(`/?q=${encodeURIComponent(item.title)}`); }}
              onAction={action => void act(item, action)}
            />
          </article>)}</div>
        </>}
      </section>}
    </div>
  );
}
