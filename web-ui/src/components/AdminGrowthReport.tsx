import { fetchAdminGrowthStats, type AdminGrowthStats, type AdminWindowDays } from '../api/client';
import { COLORS, fmt, kstDay, pct, useBlock } from './adminShared';
import { AdminChart, AdminSection, AdminTable, BlockBody, KpiTile } from './AdminUi';

function GrowthMetrics({ stats, compact }: { stats: AdminGrowthStats; compact: boolean }) {
  const { totals, activation, retention, measurement } = stats;
  return (
    <>
      <p className="admin-note">
        {kstDay(stats.window.start)} — {kstDay(stats.window.end)} · KST · 현재 일반 계정의 실제 메시지 기준 · 관리자 제외
      </p>
      <div className="admin-kpis admin-kpis--6" role="group" aria-label="사용자 성장 핵심 지표">
        <KpiTile label="활성 사용자" value={fmt(totals.active_users)} hint="기간 내 메시지를 보낸 계정" />
        <KpiTile label="첫 이용 사용자" value={fmt(totals.new_users)} hint="보관 기록의 첫 메시지가 기간 내 발생" />
        <KpiTile label="기존 이용 사용자" value={fmt(totals.returning_users)} hint="기간 이전에도 메시지를 보낸 계정" />
        <KpiTile label="여러 날 재사용" value={fmt(totals.repeat_users)} hint="기간 내 서로 다른 2일 이상 이용" />
        <KpiTile label="신규 가입" value={fmt(activation.signups)} hint="선택 기간에 가입한 일반 계정" />
        <KpiTile label="24시간 첫 이용률" value={pct(activation.rate)} hint={`${fmt(activation.eligible)}명 중 ${fmt(activation.activated)}명 · 관찰 대기 ${fmt(activation.pending)}명`} />
      </div>
      <p className="admin-note">
        빈 대화 생성은 이용에 포함하지 않습니다. 방문 통계는 분석 동의 브라우저 표본이므로 계정 수와 나누어 전환율을 계산하지 않습니다.
      </p>
      {!compact && <>
        <AdminSection title="가입 → 실제 첫 이용" aside="가입 후 24시간 관찰이 끝난 계정만 비율에 포함">
          <p className="visits-funnel-inline" aria-label="가입에서 첫 메시지까지">
            가입 {fmt(activation.signups)}명 → 관찰 완료 {fmt(activation.eligible)}명 → 24시간 내 첫 메시지 {fmt(activation.activated)}명 ({pct(activation.rate)})
          </p>
          <p className="admin-note">관찰 대기 {fmt(activation.pending)}명 중 이미 첫 메시지를 보낸 계정 {fmt(activation.pending_activated)}명. 대기 계정은 성공·실패 비율에서 모두 제외합니다.</p>
        </AdminSection>
        <AdminSection title="첫 이용 후 재방문" aside="페이지 방문이 아닌 메시지를 보낸 재사용">
          <AdminTable label="첫 이용 코호트 재방문율" headings={['재사용 시점', '관찰 완료', '재사용', '재방문율', '관찰 대기']}>
            {retention.map((row) => <tr key={row.day}>
              <th scope="row">D{row.day}</th><td>{fmt(row.eligible)}</td><td>{fmt(row.returned)}</td>
              <td>{pct(row.rate)}</td><td>{fmt(row.pending)}</td>
            </tr>)}
          </AdminTable>
          <p className="admin-note">선택 기간에 처음 이용한 계정이 정확히 다음 날(D1)·7일 뒤(D7)에 다시 메시지를 보냈는지 봅니다. 해당 KST 날짜가 끝나야 관찰 완료이며, 분모가 없으면 —로 표시합니다.</p>
        </AdminSection>
        <AdminSection title="일별 실제 이용" aside="일별 순사용자 · 기간 순사용자는 일별 합과 다름">
          <AdminChart label="일별 첫 이용·기존 이용 사용자 추이" barmode="stack" data={[
            { type: 'bar', name: '첫 이용', x: stats.daily.map((row) => row.date), y: stats.daily.map((row) => row.new_users), marker: { color: COLORS.bar } },
            { type: 'bar', name: '기존 이용', x: stats.daily.map((row) => row.date), y: stats.daily.map((row) => row.returning_users), marker: { color: COLORS.barSoft } },
          ]} />
          <details className="visits-drill">
            <summary>일별 상세 {stats.daily.length}일</summary>
          <AdminTable label="일별 사용자 이용" headings={['KST 날짜', '활성 사용자', '첫 이용', '기존 이용', '메시지']}>
            {[...stats.daily].reverse().map((row) => <tr key={row.date}>
              <th scope="row">{row.date}</th><td>{fmt(row.active_users)}</td><td>{fmt(row.new_users)}</td>
              <td>{fmt(row.returning_users)}</td><td>{fmt(row.user_messages)}</td>
            </tr>)}
          </AdminTable>
          </details>
        </AdminSection>
      </>}
      <p className="admin-note">
        보관된 메시지 기준{measurement.first_activity_date ? ` · 첫 기록 ${measurement.first_activity_date}` : ' · 아직 이용 기록이 없습니다'}.
        삭제된 계정·대화 이력은 포함하지 않아 생애 최초 이용과 다를 수 있습니다.
        {measurement.unknown_signup_dates > 0 && ` 가입 시각을 확인할 수 없는 ${fmt(measurement.unknown_signup_dates)}개 계정은 가입·활성화 집계에서 제외했습니다.`}
      </p>
    </>
  );
}

export default function AdminGrowthReport({ days, compact = false }: { days: AdminWindowDays; compact?: boolean }) {
  const growth = useBlock(fetchAdminGrowthStats, days);
  return <section className="admin-growth-metrics" aria-label="사용자 이용·성장" aria-busy={growth.loading}>
    <BlockBody block={growth} label="사용자 성장 지표">{(stats) => <GrowthMetrics stats={stats} compact={compact} />}</BlockBody>
  </section>;
}
