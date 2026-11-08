import { useState, type ReactNode } from 'react';
import { fetchAdminConversationStats, type AdminConversationStats, type AdminWindowDays } from '../api/client';
import { COLORS, INTENT_LABELS, fmt, kstDay, pct, ratio, seconds, useBlock } from './adminShared';
import { AdminChart, AdminSection, AdminTable, AdminTabHeader, BlockBody, KpiTile } from './AdminUi';
import './AdminConversationsTab.css';

function intentRows(stats: AdminConversationStats) {
  const latency = new Map(stats.latency.map((row) => [row.intent, row]));
  const keys = [...stats.intents.map((row) => row.intent), ...stats.latency.map((row) => row.intent)];
  return [...new Set(keys)].map((intent) => {
    const counts = stats.intents.find((row) => row.intent === intent);
    const lat = latency.get(intent);
    return {
      intent,
      label: INTENT_LABELS[intent] ?? intent,
      turns: counts?.turns ?? 0,
      failed: counts?.failed ?? 0,
      interrupted: counts?.interrupted ?? 0,
      issues: (counts?.failed ?? 0) + (counts?.interrupted ?? 0),
      p50: lat?.p50_ms ?? null,
      p95: lat?.p95_ms ?? null,
      samples: lat?.samples ?? 0,
    };
  });
}

function Details({ title, aside, children }: { title: string; aside?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return <details className="conversation-details" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary><span>{title}</span>{aside && <small>{aside}</small>}</summary>
    {open && <div className="conversation-details-body">{children}</div>}
  </details>;
}

function Trend({ stats }: { stats: AdminConversationStats }) {
  const [metric, setMetric] = useState<'messages' | 'issues'>('messages');
  const today = kstDay(stats.window.end);
  const messages = metric === 'messages';
  const label = messages ? '사용자 메시지' : '실패·중단';
  return <AdminSection title="이용과 응답 추이" aside="KST 일자별 건수">
    <div className="conversation-trend-tools">
      <div className="conversation-metric-switch" role="group" aria-label="추이 지표">
        <button type="button" aria-pressed={messages} onClick={() => setMetric('messages')}>메시지</button>
        <button type="button" aria-pressed={!messages} onClick={() => setMetric('issues')}>실패·중단</button>
      </div>
      <span className="conversation-partial">{today?.slice(5)} 집계 중</span>
    </div>
    <AdminChart
      label={messages ? '일별 메시지 추이' : '일별 실패·중단 추이'}
      height={200}
      showlegend={false}
      maxCount={Math.max(0, ...stats.daily.map((day) => messages ? day.user_turns : day.failed))}
      data={[{
        type: 'bar', name: label,
        x: stats.daily.map((day) => day.date),
        y: stats.daily.map((day) => messages ? day.user_turns : day.failed),
        marker: { color: stats.daily.map((day) => day.date === today
          ? (messages ? '#b3adf8' : '#efb2bc')
          : (messages ? COLORS.bar : COLORS.fail)) },
        text: stats.daily.map((day) => day.date === today ? ' · 집계 중' : ''),
        hovertemplate: `%{x}%{text}<br>${label} %{y:,}건<extra></extra>`,
      }]}
    />
    <p className="conversation-caption">오늘은 집계 중입니다. 실패·중단은 발생 건수이며, 메시지 수 대비 비율이 아닙니다.</p>
  </AdminSection>;
}

function Attention({ stats, rows }: { stats: AdminConversationStats; rows: ReturnType<typeof intentRows> }) {
  const problems = rows.filter((row) => row.issues > 0)
    .sort((a, b) => b.issues - a.issues || b.turns - a.turns || a.intent.localeCompare(b.intent));
  const unclassified = Math.max(0, stats.outcomes.failed + stats.outcomes.interrupted - rows.reduce((sum, row) => sum + row.issues, 0));
  // Review latency is time to start a background job, so it cannot be ranked as answer latency.
  const longest = rows.filter((row) => row.intent !== 'review' && row.samples >= 5 && row.p95 !== null)
    .sort((a, b) => b.p95! - a.p95! || a.intent.localeCompare(b.intent))[0];
  return <AdminSection title="확인할 응답 유형" aside="실패·중단 건수순">
    {problems.length > 0 ? <ul className="conversation-attention-list">
      {problems.slice(0, 3).map((row) => <li key={row.intent}>
        <div><strong>{row.label}</strong><span>응답 {fmt(row.turns)}건 중</span></div>
        <b>{fmt(row.issues)}건</b>
      </li>)}
    </ul> : <p className="conversation-status">
      {unclassified > 0 ? '문제 응답의 유형이 기록되지 않았습니다.'
        : stats.outcomes.done > 0 ? '기록된 실패·중단이 없습니다.' : '아직 완료된 응답이 없습니다.'}
    </p>}
    {unclassified > 0 && <p className="conversation-caption">유형 미분류 {fmt(unclassified)}건은 위 목록에서 제외했습니다.</p>}
    {problems.length > 3 && <p className="conversation-caption">상위 3개 유형 · 전체는 아래 상세에서 확인할 수 있습니다.</p>}
    <div className="conversation-latency">
      <span>응답 시간 참고 · 가장 긴 p95</span>
      {longest ? <>
        <p><strong>{longest.label}</strong><b>{seconds(longest.p95)}</b></p>
        <small>완료 응답 {fmt(longest.samples)}건 측정 · 중앙값 {seconds(longest.p50)}</small>
      </> : <p className="conversation-status">완료 응답이 5건 이상 측정된 유형이 없습니다.</p>}
      <small>리뷰 시작 시간은 제외합니다. 장애 판정 기준은 아닙니다.</small>
    </div>
  </AdminSection>;
}

function ReviewDetails({ reviews }: { reviews: AdminConversationStats['reviews'] }) {
  const v = reviews.verification;
  return <Details title="리뷰 상세" aside={`대화에서 시작 ${fmt(reviews.started)}건`}>
    {reviews.started === 0 ? <p className="conversation-caption">선택 기간에 대화에서 시작한 리뷰가 없습니다.</p> : <>
      <dl className="admin-facts">
        <div><dt>시작</dt><dd>{fmt(reviews.started)}건</dd></div>
        <div><dt>빠른 · 정밀</dt><dd>{fmt(reviews.by_mode.fast)} · {fmt(reviews.by_mode.full)} (정밀 {pct(ratio(reviews.by_mode.full, reviews.started))})</dd></div>
        <div><dt>리뷰 결과</dt><dd>완료 {fmt(reviews.outcomes.completed)} · 실패 {fmt(reviews.outcomes.failed)} · 진행 {fmt(reviews.outcomes.running)} · 알 수 없음 {fmt(reviews.outcomes.unknown)}</dd></div>
        <div><dt>주장 검증</dt><dd>{v.sessions_with_claims === 0
          ? '정밀 리뷰 검증 기록이 아직 없습니다'
          : `주장 ${fmt(v.claims)} · 확인 ${fmt(v.verified)} · 부분 ${fmt(v.partially_verified)} · 미확인 ${fmt(v.unverified)} · 불일치 ${fmt(v.contradicted)} · 확인율 ${pct(v.verified_ratio)}`}</dd></div>
      </dl>
      <p className="conversation-caption">실패 기록은 영구 보관되지 않아 서버 재시작 뒤 실패와 기록 유실을 구분할 수 없는 리뷰는 ‘알 수 없음’으로 표시합니다.</p>
      {reviews.mode_missing > 0 && <p className="conversation-caption">모드 기록이 없는 이전 리뷰 {fmt(reviews.mode_missing)}건은 빠른 리뷰로 집계합니다.</p>}
    </>}
  </Details>;
}

function Body({ stats }: { stats: AdminConversationStats }) {
  const rows = intentRows(stats);
  const issues = stats.outcomes.failed + stats.outcomes.interrupted;
  const today = kstDay(stats.window.end);
  const hasActivity = stats.totals.user_turns > 0 || stats.totals.assistant_turns > 0
    || stats.totals.running > 0 || stats.reviews.started > 0;

  if (!hasActivity) return <div className="conversation-empty" role="status">
    <h2>선택 기간에 대화 이용 기록이 없습니다.</h2>
    <p>조회 기간을 넓혀 이전 기록을 확인할 수 있습니다.</p>
    {stats.totals.conversations > 0 && <p>새로 생성된 대화 {fmt(stats.totals.conversations)}개에는 아직 메시지가 없습니다.</p>}
  </div>;

  return <>
    <div className="admin-kpis admin-kpis--4" role="group" aria-label="대화 운영 요약">
      <KpiTile label="사용자 메시지" value={fmt(stats.totals.user_turns)} hint="선택 기간에 보낸 메시지" />
      <KpiTile label="활성 계정" value={fmt(stats.totals.active_users)} hint="메시지를 보낸 계정 · 중복 제외" />
      <KpiTile label="실패·중단" value={fmt(issues)} hint={`문제 응답률 ${pct(stats.error_rate)}`} />
      <KpiTile label="진행 중 응답" value={fmt(stats.totals.running)} hint="선택 기간에 시작 · 기록 상태 기준" />
    </div>
    <div className="conversation-context">
      <span>관리자 포함 · 보관된 대화 기록 기준</span>
      <span>응답 완료 {fmt(stats.outcomes.done)} · 실패 {fmt(stats.outcomes.failed)} · 중단 {fmt(stats.outcomes.interrupted)} · 취소 {fmt(stats.outcomes.cancelled)}</span>
    </div>

    <div className="conversation-overview">
      <Trend stats={stats} />
      <Attention stats={stats} rows={rows} />
    </div>

    <div className="conversation-detail-list">
      <Details title="일별 상세" aside={`${stats.daily.length}일 · 정확한 수치 확인`}>
        <p className="conversation-caption">이용한 대화는 그날 메시지를 보낸 대화입니다. 같은 대화·계정이 여러 날에 포함되므로 일별 합계는 중복을 제외한 기간 전체 수와 다릅니다.</p>
        <AdminTable label="일별 대화 이용" headings={['날짜', '이용한 대화', '사용자 메시지', '활성 계정', '실패·중단']}>
          {[...stats.daily].reverse().map((day) => <tr key={day.date}>
            <th scope="row">{day.date}{day.date === today && <span className="conversation-day-note">집계 중</span>}</th>
            <td>{fmt(day.conversations)}</td><td>{fmt(day.user_turns)}</td><td>{fmt(day.active_users)}</td>
            <td className={day.failed > 0 ? 'admin-bad' : undefined}>{fmt(day.failed)}</td>
          </tr>)}
        </AdminTable>
        <p className="conversation-caption">보관 기록이 없는 날짜는 0으로 표시합니다. 수집 시작 전이나 기록 삭제로 비어 있는 날짜와 실제 이용이 없었던 날짜는 구분할 수 없습니다.</p>
      </Details>

      <Details title="유형별 응답 상세" aside={`${rows.length}개 유형 · 응답 시간과 표본`}>
        {rows.length > 0 ? <>
          <AdminTable label="유형별 응답 표" headings={['유형', '응답', '실패', '중단', '중앙값', 'p95', '측정 표본']}>
            {[...rows].sort((a, b) => b.issues - a.issues || b.turns - a.turns || a.intent.localeCompare(b.intent)).map((row) => <tr key={row.intent}>
              <th scope="row">{row.label}</th><td>{fmt(row.turns)}</td><td>{fmt(row.failed)}</td><td>{fmt(row.interrupted)}</td>
              <td>{seconds(row.p50)}</td><td>{row.samples < 5 ? '—' : seconds(row.p95)}</td><td>{fmt(row.samples)}건</td>
            </tr>)}
          </AdminTable>
          <p className="conversation-caption">응답 시간은 완료된 응답만 측정합니다. 중앙값은 절반의 응답이 끝난 시간, p95는 95%가 끝난 시간입니다. 표본 5건 미만이면 p95는 —입니다. 리뷰는 완료까지가 아닌 시작까지 걸린 시간입니다.</p>
          <p className="conversation-caption">유형이 기록된 응답만 포함합니다. 유형이 없는 중단·취소가 있어 전체 응답 수와 합계가 다를 수 있습니다.</p>
        </> : <p className="conversation-caption">유형이 기록된 응답이 없습니다.</p>}
      </Details>
      <ReviewDetails reviews={stats.reviews} />
      <Details title="집계 기준" aside="모집단·비율·상태 정의">
        <ul className="conversation-method">
          <li>활성 계정은 선택 기간에 메시지를 보낸 계정이며 관리자를 포함합니다. 성장 탭은 현재 일반 계정만 집계하므로 수치가 다를 수 있습니다.</li>
          <li>문제 응답률 = (실패 + 중단) ÷ (완료 + 실패 + 중단). 취소와 진행 중은 분모에서 제외하고, 분모가 없으면 —로 표시합니다.</li>
          <li>중단은 서버 재시작 때 처리 중이던 응답, 취소는 새 사용자 메시지로 대체된 응답입니다. 진행 중은 저장된 상태이며 실시간 처리 여부를 보장하지 않습니다.</li>
          <li>선택 기간의 새 대화는 {fmt(stats.totals.conversations)}개입니다. 생성일 기준이므로 일별 표의 ‘이용한 대화’와 다릅니다.</li>
        </ul>
      </Details>
    </div>
  </>;
}

export default function AdminConversationsTab({ days, onDays }: { days: AdminWindowDays; onDays: (days: AdminWindowDays) => void }) {
  const conversations = useBlock(fetchAdminConversationStats, days);
  const win = conversations.data?.window;
  return <article className="admin-dashboard visits-report admin-tabview admin-conversations" aria-labelledby="admin-conversations-title" aria-busy={conversations.loading}>
    <AdminTabHeader id="admin-conversations-title" title="대화"
      range={win ? `${kstDay(win.start)} — ${kstDay(win.end)} · KST` : null}
      days={days} onDays={onDays} />
    <BlockBody block={conversations} label="대화 통계">{(stats) => <Body key={days} stats={stats} />}</BlockBody>
  </article>;
}
