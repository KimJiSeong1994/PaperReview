import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import type { AxiosResponse } from 'axios';
import {
  fetchAdminConversationStats,
  fetchAdminLlmUsage,
  fetchAdminSoulStats,
  type AdminConversationStats,
  type AdminLlmUsage,
  type AdminSoulStats,
  type AdminWindowDays,
} from '../api/client';
import LazyLoadErrorBoundary from './LazyLoadErrorBoundary';
import type { Data } from '../PlotlyChart';

const Plot = lazy(() => import('../PlotlyChart'));

const WINDOWS: AdminWindowDays[] = [7, 28, 90];
const nf = new Intl.NumberFormat('ko-KR');
const fmt = (value: number) => nf.format(value ?? 0);
// null is "no denominator", never 0%.
const pct = (value: number | null) => (value === null ? '—' : `${(value * 100).toFixed(1)}%`);
const ratio = (part: number, whole: number) => (whole > 0 ? part / whole : null);
const seconds = (ms: number | null) => (ms === null ? '—' : `${(ms / 1000).toFixed(1)}초`);
const kstDay = (iso: string | null) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(t) ? new Date(t + 9 * 3_600_000).toISOString().slice(0, 10) : null;
};

const INTENT_LABELS: Record<string, string> = {
  chat: '대화',
  clarify: '되묻기',
  search: '검색',
  answer: '결과 답변',
  review: '리뷰 시작',
  open_pdf: 'PDF 열기',
  highlight_pdf: '하이라이트',
  answer_from_bookmarks: '북마크 답변',
};
const MEMORY_KIND_LABELS: Record<string, string> = {
  preference: '선호',
  topic: '주제',
  paper: '논문',
  fact: '사실',
  research: '연구',
  interest: '관심사',
};
const STAGE_LABELS: Record<string, string> = { claim_verification: '주장 검증' };
const LEDGER_REASON_LABELS: Record<string, string> = { 'ledger not found': '사용량 원장 파일이 없습니다' };

// Plotly ignores CSS var() colors, so charts take hex literals (same palette as the legacy dashboard).
const COLORS = { bar: '#4f46e5', barSoft: '#a7a1f7', fail: '#e05266', axis: '#858291', grid: '#ecebf0', font: '#706d7d' };
const CHART_LAYOUT = {
  paper_bgcolor: 'transparent', plot_bgcolor: 'transparent', height: 240,
  margin: { t: 12, b: 36, l: 48, r: 12 },
  font: { color: COLORS.font, size: 11, family: 'Pretendard, sans-serif' },
  xaxis: { gridcolor: 'transparent', color: COLORS.axis, fixedrange: true },
  yaxis: { gridcolor: COLORS.grid, color: COLORS.axis, zeroline: false, fixedrange: true, rangemode: 'tozero' as const },
  legend: { orientation: 'h' as const, y: -0.2 },
};

interface Block<T> { data: T | null; loading: boolean; error: string | null; retry: () => void }

/** One endpoint, loaded on its own so a failing source never blanks the others. */
function useBlock<T>(fetcher: (days: AdminWindowDays, signal: AbortSignal) => Promise<AxiosResponse<T>>, days: AdminWindowDays): Block<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => {
      if (controller.signal.aborted) return;
      setLoading(true);
      setError(null);
      fetcher(days, controller.signal)
        .then(({ data: next }) => { if (!controller.signal.aborted) setData(next); })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          const detail = err as { response?: { data?: { detail?: string } }; message?: string };
          setError(detail.response?.data?.detail ?? detail.message ?? '알 수 없는 오류');
        })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    });
    return () => controller.abort();
  }, [fetcher, days, nonce]);

  const retry = useCallback(() => setNonce((n) => n + 1), []);
  return { data, loading, error, retry };
}

/** Loading / error / content for one block; a refetch keeps the old data on screen. */
function BlockState<T>({ block, label, children }: { block: Block<T>; label: string; children: (data: T) => ReactNode }) {
  if (block.error && !block.loading) {
    return (
      <div className="assistant-block-error" role="alert">
        <span>{label}을(를) 불러오지 못했습니다 · {block.error}</span>
        <button type="button" className="admin-action-btn" onClick={block.retry}>다시 시도</button>
      </div>
    );
  }
  if (!block.data) return <div className="admin-loading">{label} 불러오는 중...</div>;
  return <div aria-busy={block.loading}>{children(block.data)}</div>;
}

function StatTile({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <article className="admin-stat-card">
      <p className="admin-stat-label">{label}</p>
      <p className="admin-stat-value">{value}</p>
      {hint && <p className="visits-stat-hint">{hint}</p>}
    </article>
  );
}

function SectionHeading({ kicker, title, note }: { kicker: string; title: string; note?: string }) {
  return (
    <div className="dashboard-section-heading">
      <div><span>{kicker}</span><h3>{title}</h3></div>
      {note && <p>{note}</p>}
    </div>
  );
}

/** CSS bars (theme tokens apply, no chart dependency), same look as the legacy RankList. */
function BarList({ title, rows, emptyLabel }: {
  title: string; emptyLabel: string; rows: { key: string; label: string; count: number; badge?: ReactNode }[];
}) {
  const max = Math.max(0, ...rows.map((row) => row.count));
  return (
    <section className="dashboard-rank-card">
      <h3>{title}</h3>
      {rows.length > 0 && max > 0 ? (
        <ol className="dashboard-rank-list">
          {rows.map((row) => (
            <li key={row.key} className="dashboard-rank-item assistant-bar-item">
              <div className="dashboard-rank-detail">
                <div className="dashboard-rank-copy">
                  <span>{row.label}{row.badge}</span>
                  <strong>{fmt(row.count)}</strong>
                </div>
                <span className="dashboard-rank-track" aria-hidden="true">
                  <span style={{ width: `${(row.count / max) * 100}%` }} />
                </span>
              </div>
            </li>
          ))}
        </ol>
      ) : <div className="admin-empty">{emptyLabel}</div>}
    </section>
  );
}

function Chart({ data, label }: { data: Data[]; label: string }) {
  return (
    <LazyLoadErrorBoundary fallback={<div className="admin-empty">차트를 표시할 수 없습니다.</div>}>
      <Suspense fallback={<div className="admin-loading">차트 로딩 중...</div>}>
        <div role="img" aria-label={label}>
          <Plot data={data} layout={CHART_LAYOUT} config={{ displayModeBar: false, responsive: true }} style={{ width: '100%' }} />
        </div>
      </Suspense>
    </LazyLoadErrorBoundary>
  );
}

function ConversationBlock({ stats }: { stats: AdminConversationStats }) {
  const { totals, outcomes, reviews, activation } = stats;
  const end = Date.parse(stats.window.end);
  const yesterday = Number.isFinite(end) ? kstDay(new Date(end - 86_400_000).toISOString()) : null;
  const yesterdayRow = stats.daily.find((row) => row.date === yesterday);
  const verification = reviews.verification;

  return (
    <>
      <p className="assistant-yesterday" role="status">
        {yesterdayRow
          ? <>어제({yesterdayRow.date}) 대화 {fmt(yesterdayRow.conversations)} · 메시지 {fmt(yesterdayRow.user_turns)} · 실패 {fmt(yesterdayRow.failed)}</>
          : '어제 기록이 없습니다.'}
      </p>

      <div className="admin-stats-grid dashboard-stat-grid" role="group" aria-label="대화 핵심 지표">
        <StatTile label="대화 수" value={fmt(totals.conversations)} hint="창 안에 생성된 대화" />
        <StatTile label="활성 사용자" value={fmt(totals.active_users)} hint="메시지를 보낸 계정" />
        <StatTile label="사용자 메시지" value={fmt(totals.user_turns)} hint={`답변 ${fmt(totals.assistant_turns)} · 진행 중 ${fmt(totals.running)}`} />
        <StatTile
          label="실패율"
          value={pct(stats.error_rate)}
          hint={`실패 ${fmt(outcomes.failed)} · 중단 ${fmt(outcomes.interrupted)} · 취소 ${fmt(outcomes.cancelled)}건은 별도`}
        />
        <StatTile
          label="정밀 리뷰 비율"
          value={pct(ratio(reviews.by_mode.full, reviews.started))}
          hint={`리뷰 시작 ${fmt(reviews.started)}건 중 정밀 ${fmt(reviews.by_mode.full)}`}
        />
      </div>

      <p className="assistant-activation">
        창 안 가입 {fmt(activation.signups)}명 중 24시간 안에 첫 대화 {fmt(activation.first_conversation_within_24h)}명
        {' '}({pct(ratio(activation.first_conversation_within_24h, activation.signups))})
      </p>

      <div className="dashboard-rank-grid">
        <BarList
          title="의도 분포 · 답변 턴"
          emptyLabel="아직 기록이 없습니다."
          rows={stats.intents.map((row) => ({
            key: row.intent,
            label: INTENT_LABELS[row.intent] ?? row.intent,
            count: row.turns,
            badge: row.failed + row.interrupted > 0
              ? <span className="assistant-fail-badge">실패 {fmt(row.failed + row.interrupted)}</span>
              : null,
          }))}
        />
        <section className="dashboard-rank-card">
          <h3>의도별 지연</h3>
          {stats.latency.length > 0 ? (
            <div className="assistant-table-scroll" tabIndex={0} role="region" aria-label="의도별 지연 표">
              <table className="assistant-table">
                <thead><tr><th scope="col">의도</th><th scope="col">표본</th><th scope="col">p50</th><th scope="col">p95</th></tr></thead>
                <tbody>
                  {stats.latency.map((row) => (
                    <tr key={row.intent}>
                      <th scope="row">{INTENT_LABELS[row.intent] ?? row.intent}</th>
                      <td>{fmt(row.samples)}</td>
                      <td>{seconds(row.p50_ms)}</td>
                      <td>{seconds(row.p95_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <div className="admin-empty">아직 기록이 없습니다.</div>}
          <p className="assistant-footnote">완료된 답변만 집계합니다. 리뷰는 리뷰 전체가 아니라 시작까지의 시간이고, 표본 5개 미만이면 p95는 —.</p>
        </section>
      </div>

      <div className="dashboard-rank-grid">
        <BarList
          title={`리뷰 모드 · 시작 ${fmt(reviews.started)}건`}
          emptyLabel="대화에서 시작된 리뷰가 아직 없습니다."
          rows={[
            { key: 'fast', label: '빠른 리뷰', count: reviews.by_mode.fast },
            { key: 'full', label: '정밀 리뷰', count: reviews.by_mode.full },
          ]}
        />
        <section className="dashboard-rank-card">
          <h3>리뷰 결과와 주장 검증</h3>
          <p className="assistant-line">
            완료 {fmt(reviews.outcomes.completed)} · 실패 {fmt(reviews.outcomes.failed)} · 진행 {fmt(reviews.outcomes.running)} · 알 수 없음 {fmt(reviews.outcomes.unknown)}
          </p>
          {reviews.mode_missing > 0 && (
            <p className="assistant-footnote">모드 기록이 없는 옛 리뷰 {fmt(reviews.mode_missing)}건은 빠른 리뷰로 셉니다.</p>
          )}
          {verification.sessions_with_claims === 0 ? (
            <div className="admin-empty">정밀 리뷰 검증 기록이 아직 없습니다</div>
          ) : (
            <p className="assistant-verify">
              주장 {fmt(verification.claims)}개 중 확인 {fmt(verification.verified)}({pct(verification.verified_ratio)})
              {' · '}부분 {fmt(verification.partially_verified)} · 미확인 {fmt(verification.unverified)} · 불일치 {fmt(verification.contradicted)}
            </p>
          )}
          <p className="assistant-footnote">재시작 뒤에는 실패와 유실을 구분할 수 없어 '알 수 없음'으로 셉니다.</p>
        </section>
      </div>

      <section className="dashboard-chart-card">
        <div className="dashboard-card-heading">
          <div><span>DAILY</span><h3>일별 대화와 실패</h3></div>
          <p>KST 일자 기준</p>
        </div>
        {stats.daily.length > 0 ? (
          <Chart
            label="일별 대화 수 막대와 실패 수 선"
            data={[
              { type: 'bar', name: '대화', x: stats.daily.map((d) => d.date), y: stats.daily.map((d) => d.conversations), marker: { color: COLORS.bar } },
              { type: 'scatter', mode: 'lines+markers', name: '실패', x: stats.daily.map((d) => d.date), y: stats.daily.map((d) => d.failed), line: { color: COLORS.fail, width: 2 }, marker: { color: COLORS.fail, symbol: 'x' } },
            ]}
          />
        ) : <div className="admin-empty">아직 기록이 없습니다.</div>}
      </section>
    </>
  );
}

function SoulBlock({ stats }: { stats: AdminSoulStats }) {
  const { accounts, memories, profiles } = stats;
  const fill = (n: number) => `${fmt(n)} / ${fmt(profiles.total)} (${pct(ratio(n, profiles.total))})`;
  return (
    <>
      <div className="admin-stats-grid dashboard-stat-grid" role="group" aria-label="메모리·프로필 지표">
        <StatTile label="메모리 보유 계정" value={fmt(accounts.with_memories)} hint={`USER.md 작성 ${fmt(accounts.with_user_md)}`} />
        <StatTile label="창 안 신규 메모리" value={fmt(memories.new_in_window)} hint={`전체 ${fmt(memories.total)}개`} />
        <StatTile label="연구 프로필" value={fmt(profiles.total)} hint={`24시간 초과 ${fmt(profiles.stale_over_24h)}`} />
      </div>
      <div className="dashboard-rank-grid">
        <BarList
          title="종류별 메모리"
          emptyLabel="아직 기록이 없습니다."
          rows={memories.by_kind.map((row) => ({
            key: row.kind,
            label: `${MEMORY_KIND_LABELS[row.kind] ?? row.kind} · ${fmt(row.accounts)}계정`,
            count: row.count,
          }))}
        />
        <section className="dashboard-rank-card">
          <h3>프로필 채움률</h3>
          {profiles.total > 0 ? (
            <ul className="assistant-fill">
              <li><span>역할</span><strong>{fill(profiles.with_role)}</strong></li>
              <li><span>분야</span><strong>{fill(profiles.with_domain)}</strong></li>
              <li><span>키워드</span><strong>{fill(profiles.with_keywords)}</strong></li>
            </ul>
          ) : <div className="admin-empty">아직 기록이 없습니다.</div>}
          <p className="assistant-footnote">관심사 평균 반복 {memories.interest_avg_hits === null ? '—' : memories.interest_avg_hits.toFixed(1)}회 · 건수만 집계하며 메모리·프로필 내용은 받지 않습니다.</p>
        </section>
      </div>
    </>
  );
}

function LlmBlock({ usage }: { usage: AdminLlmUsage }) {
  const unrecorded = usage.coverage?.unrecorded_stages ?? [];
  return (
    <>
      {unrecorded.length > 0 && (
        <p className="assistant-warn" role="note">일부 단계 미집계: {unrecorded.map((s) => STAGE_LABELS[s] ?? s).join(', ')}</p>
      )}
      {!usage.available ? (
        <div className="admin-empty">
          {usage.reason ? LEDGER_REASON_LABELS[usage.reason] ?? `사용량 원장을 읽을 수 없습니다 (${usage.reason})` : '사용량 원장이 없습니다'}
        </div>
      ) : (
        <>
          <div className="admin-stats-grid dashboard-stat-grid" role="group" aria-label="LLM 토큰 지표">
            <StatTile label="호출" value={fmt(usage.totals.calls)} />
            <StatTile label="입력 토큰" value={fmt(usage.totals.prompt_tokens)} hint={`캐시 ${fmt(usage.totals.cached_tokens)}`} />
            <StatTile label="출력 토큰" value={fmt(usage.totals.completion_tokens)} />
          </div>
          <div className="dashboard-rank-grid">
            <section className="dashboard-rank-card">
              <h3>단계 × 모델</h3>
              {usage.by_stage.length > 0 ? (
                <div className="assistant-table-scroll" tabIndex={0} role="region" aria-label="단계별 토큰 표">
                  <table className="assistant-table">
                    <thead><tr><th scope="col">단계</th><th scope="col">모델</th><th scope="col">호출</th><th scope="col">입력</th><th scope="col">출력</th></tr></thead>
                    <tbody>
                      {usage.by_stage.map((row) => (
                        <tr key={`${row.stage}|${row.model}`}>
                          <th scope="row">{row.stage}</th>
                          <td>{row.model}</td>
                          <td>{fmt(row.calls)}</td>
                          <td>{fmt(row.prompt_tokens)}</td>
                          <td>{fmt(row.completion_tokens)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <div className="admin-empty">아직 기록이 없습니다.</div>}
              {usage.ledger.malformed_lines > 0 && (
                <p className="assistant-footnote">읽지 못한 원장 줄 {fmt(usage.ledger.malformed_lines)}개는 제외했습니다.</p>
              )}
            </section>
            <section className="dashboard-chart-card">
              <div className="dashboard-card-heading">
                <div><span>DAILY</span><h3>일별 토큰</h3></div>
                <p>통화 환산 없음</p>
              </div>
              {usage.daily.length > 0 ? (
                <Chart
                  label="일별 입력·출력 토큰 누적 막대"
                  data={[
                    { type: 'bar', name: '입력', x: usage.daily.map((d) => d.date), y: usage.daily.map((d) => d.prompt_tokens), marker: { color: COLORS.bar } },
                    { type: 'bar', name: '출력', x: usage.daily.map((d) => d.date), y: usage.daily.map((d) => d.completion_tokens), marker: { color: COLORS.barSoft } },
                  ]}
                />
              ) : <div className="admin-empty">아직 기록이 없습니다.</div>}
            </section>
          </div>
        </>
      )}
    </>
  );
}

/**
 * The conversational product at a glance: conversations, failures, review
 * modes, memory build-up and token use. Each source loads and fails on its own.
 */
export default function AdminAssistantReport() {
  const [days, setDays] = useState<AdminWindowDays>(7);
  const conversations = useBlock(fetchAdminConversationStats, days);
  const souls = useBlock(fetchAdminSoulStats, days);
  const llm = useBlock(fetchAdminLlmUsage, days);
  const win = conversations.data?.window;

  return (
    <article className="admin-dashboard visits-report dashboard-report assistant-report" aria-labelledby="assistant-report-title">
      <header className="visits-report-header dashboard-report-header">
        <div className="visits-report-heading">
          <span className="visits-report-kicker">CONVERSATIONS</span>
          <h1 id="assistant-report-title">대화 운영 리포트</h1>
          <p>{win ? `${kstDay(win.start)} — ${kstDay(win.end)} · ${win.timezone}` : '대화형 홈의 대화·리뷰·메모리·토큰 집계'}</p>
        </div>
        <div className="assistant-window" role="group" aria-label="조회 기간">
          {WINDOWS.map((w) => (
            <button type="button" key={w} aria-pressed={days === w} onClick={() => setDays(w)}>{w}일</button>
          ))}
        </div>
      </header>

      <section className="visits-section dashboard-section">
        <SectionHeading kicker="01 · CONVERSATIONS" title="대화와 실패" note="취소(새 메시지로 끊음)는 실패에서 뺍니다" />
        <BlockState block={conversations} label="대화 통계">{(data) => <ConversationBlock stats={data} />}</BlockState>
      </section>

      <section className="visits-section dashboard-section">
        <SectionHeading kicker="02 · MEMORY" title="메모리와 연구 프로필" note="건수만, 내용 없음" />
        <BlockState block={souls} label="메모리 통계">{(data) => <SoulBlock stats={data} />}</BlockState>
      </section>

      <section className="visits-section dashboard-section">
        <SectionHeading kicker="03 · TOKENS" title="LLM 토큰" note="사용자·대화별 귀속 없음" />
        <BlockState block={llm} label="LLM 사용량">{(data) => <LlmBlock usage={data} />}</BlockState>
      </section>
    </article>
  );
}
