import { fetchAdminConversationStats, type AdminConversationStats, type AdminWindowDays } from '../api/client';
import { INTENT_LABELS, fmt, kstDay, pct, ratio, seconds, useBlock } from './adminShared';
import { AdminSection, AdminTable, AdminTabHeader, BlockBody } from './AdminUi';

const OUTCOMES = [
  { key: 'done', label: '완료', className: 'admin-seg--done' },
  { key: 'failed', label: '실패', className: 'admin-seg--fail' },
  { key: 'interrupted', label: '중단', className: 'admin-seg--interrupt' },
  { key: 'cancelled', label: '취소', className: 'admin-seg--cancel' },
] as const;

/** Intents and latency share the intent key; one row per intent, intent order kept. */
function intentRows(stats: AdminConversationStats) {
  const latency = new Map(stats.latency.map((row) => [row.intent, row]));
  const keys = [...stats.intents.map((row) => row.intent), ...stats.latency.map((row) => row.intent)];
  return [...new Set(keys)].map((intent) => {
    const counts = stats.intents.find((row) => row.intent === intent);
    const lat = latency.get(intent);
    return {
      intent,
      turns: counts?.turns ?? 0,
      failed: counts?.failed ?? 0,
      interrupted: counts?.interrupted ?? 0,
      p50: lat?.p50_ms ?? null,
      p95: lat?.p95_ms ?? null,
      samples: lat?.samples ?? 0,
    };
  });
}

function OutcomeBar({ outcomes }: { outcomes: AdminConversationStats['outcomes'] }) {
  const total = OUTCOMES.reduce((sum, o) => sum + outcomes[o.key], 0);
  return (
    <>
      <div className="admin-stackbar" role="img" aria-label={OUTCOMES.map((o) => `${o.label} ${outcomes[o.key]}`).join(', ')}>
        {total > 0 && OUTCOMES.map((o) => outcomes[o.key] > 0 && (
          <span key={o.key} className={o.className} style={{ width: `${(outcomes[o.key] / total) * 100}%` }} />
        ))}
      </div>
      <ul className="admin-legend">
        {OUTCOMES.map((o) => (
          <li key={o.key}><i className={o.className} aria-hidden="true" />{o.label} <strong>{fmt(outcomes[o.key])}</strong></li>
        ))}
      </ul>
    </>
  );
}

function Body({ stats }: { stats: AdminConversationStats }) {
  const { reviews } = stats;
  const v = reviews.verification;
  const rows = intentRows(stats);
  return (
    <>
      <AdminSection
        title="답변 결과"
        aside={`실패율 ${pct(stats.error_rate)} · 취소는 실패에서 뺌`}
      >
        <OutcomeBar outcomes={stats.outcomes} />
      </AdminSection>

      <AdminSection title="의도별" aside="지연은 완료된 답변만 · 리뷰는 시작까지 · 표본 5개 미만이면 p95 —">
        {rows.length > 0 ? (
          <AdminTable label="의도별 표" headings={['의도', '턴', '실패', '중단', 'p50', 'p95']}>
            {rows.map((row) => (
              <tr key={row.intent}>
                <th scope="row">{INTENT_LABELS[row.intent] ?? row.intent}</th>
                <td>{fmt(row.turns)}</td>
                <td className={row.failed > 0 ? 'admin-bad' : undefined}>{fmt(row.failed)}</td>
                <td className={row.interrupted > 0 ? 'admin-bad' : undefined}>{fmt(row.interrupted)}</td>
                <td title={`표본 ${row.samples}`}>{seconds(row.p50)}</td>
                <td title={`표본 ${row.samples}`}>{seconds(row.p95)}</td>
              </tr>
            ))}
          </AdminTable>
        ) : <div className="admin-empty">아직 기록이 없습니다.</div>}
      </AdminSection>

      <AdminSection title="리뷰" aside="대화에서 시작된 리뷰만">
        <dl className="admin-facts">
          <div><dt>시작</dt><dd>{fmt(reviews.started)}</dd></div>
          <div><dt>빠른 · 정밀</dt><dd>{fmt(reviews.by_mode.fast)} · {fmt(reviews.by_mode.full)} ({pct(ratio(reviews.by_mode.full, reviews.started))})</dd></div>
          <div title="실패는 기록되지 않아, 재시작 뒤에는 실패와 유실을 구분할 수 없어 '알 수 없음'으로 셉니다."><dt>결과</dt><dd>완료 {fmt(reviews.outcomes.completed)} · 실패 {fmt(reviews.outcomes.failed)} · 진행 {fmt(reviews.outcomes.running)} · 알 수 없음 {fmt(reviews.outcomes.unknown)}</dd></div>
          <div>
            <dt>주장 검증</dt>
            <dd>
              {v.sessions_with_claims === 0
                ? '정밀 리뷰 검증 기록이 아직 없습니다'
                : `주장 ${fmt(v.claims)} · 확인 ${fmt(v.verified)} · 부분 ${fmt(v.partially_verified)} · 미확인 ${fmt(v.unverified)} · 불일치 ${fmt(v.contradicted)} · 확인율 ${pct(v.verified_ratio)}`}
            </dd>
          </div>
        </dl>
        {reviews.mode_missing > 0 && (
          <p className="admin-note">모드 기록이 없는 옛 리뷰 {fmt(reviews.mode_missing)}건은 빠른 리뷰로 셉니다.</p>
        )}
      </AdminSection>

      <AdminSection title="일별" aside="KST 일자">
        <AdminTable label="일별 표" headings={['날짜', '대화', '메시지', '활성', '실패']}>
          {[...stats.daily].reverse().map((d) => (
            <tr key={d.date}>
              <th scope="row">{d.date}</th>
              <td>{fmt(d.conversations)}</td>
              <td>{fmt(d.user_turns)}</td>
              <td>{fmt(d.active_users)}</td>
              <td className={d.failed > 0 ? 'admin-bad' : undefined}>{fmt(d.failed)}</td>
            </tr>
          ))}
        </AdminTable>
      </AdminSection>
    </>
  );
}

/** 대화: how the assistant answered — outcomes, per-intent quality, reviews, day by day. */
export default function AdminConversationsTab({ days, onDays }: { days: AdminWindowDays; onDays: (days: AdminWindowDays) => void }) {
  const conversations = useBlock(fetchAdminConversationStats, days);
  const win = conversations.data?.window;
  return (
    <article className="admin-dashboard visits-report admin-tabview" aria-labelledby="admin-conversations-title" aria-busy={conversations.loading}>
      <AdminTabHeader
        id="admin-conversations-title"
        title="대화"
        range={win ? `${kstDay(win.start)} — ${kstDay(win.end)} · KST` : null}
        days={days}
        onDays={onDays}
      />
      <BlockBody block={conversations} label="대화 통계">{(stats) => <Body stats={stats} />}</BlockBody>
    </article>
  );
}
