import { lazy, Suspense } from 'react';
import {
  fetchAdminDiagnostics,
  fetchAdminLlmUsage,
  type AdminDiagnostics,
  type AdminLlmUsage,
  type AdminWindowDays,
} from '../api/client';
import { COLORS, STAGE_LABELS, fmt, kstDay, unavailableCopy, useBlock } from './adminShared';
import { AdminChart, AdminSection, AdminTable, AdminTabHeader, BlockBody, KpiTile } from './AdminUi';

const AdminMcpReport = lazy(() => import('./AdminMcpReport'));

// The diagnostics endpoint takes no window.
const fetchDiagnostics = (_days: AdminWindowDays, signal: AbortSignal) => fetchAdminDiagnostics(signal);

const kib = (bytes: number) => (bytes < 1024 ? `${fmt(bytes)} B` : `${fmt(Math.round(bytes / 1024))} KB`);
const countCopy = (n: number) => (n === -1 ? '파일 없음' : n === -2 ? '읽기 실패' : fmt(n));

function LlmUsage({ usage }: { usage: AdminLlmUsage }) {
  const unrecorded = usage.coverage?.unrecorded_stages ?? [];
  const path = typeof usage.metric_definitions?.ledger_path === 'string' ? usage.metric_definitions.ledger_path : null;
  return (
    <>
      {!usage.available && <p className="admin-inline-error" role="status">{unavailableCopy(usage)}</p>}
      {unrecorded.length > 0 && (
        <p className="admin-warn" role="note">일부 단계 미집계: {unrecorded.map((s) => STAGE_LABELS[s] ?? s).join(', ')}</p>
      )}
      {usage.available && (
        <>
          <div className="admin-kpis admin-kpis--4" role="group" aria-label="LLM 토큰 지표">
            <KpiTile label="호출" value={fmt(usage.totals.calls)} />
            <KpiTile label="입력 토큰" value={fmt(usage.totals.prompt_tokens)} hint={`캐시 ${fmt(usage.totals.cached_tokens)}`} />
            <KpiTile label="출력 토큰" value={fmt(usage.totals.completion_tokens)} />
            <KpiTile label="합계" value={fmt(usage.totals.prompt_tokens + usage.totals.completion_tokens)} hint="통화 환산 없음" />
          </div>
          <div className="admin-split">
            {usage.by_stage.length > 0 ? (
              <AdminTable label="단계별 토큰 표" headings={['단계', '모델', '호출', '입력', '출력']}>
                {usage.by_stage.map((row) => (
                  <tr key={`${row.stage}|${row.model}`}>
                    <th scope="row">{row.stage}</th>
                    <td>{row.model}</td>
                    <td>{fmt(row.calls)}</td>
                    <td>{fmt(row.prompt_tokens)}</td>
                    <td>{fmt(row.completion_tokens)}</td>
                  </tr>
                ))}
              </AdminTable>
            ) : <div className="admin-empty">아직 기록이 없습니다.</div>}
            {usage.daily.length > 0 ? (
              <AdminChart
                label="일별 입력·출력 토큰 누적 막대"
                height={200}
                barmode="stack"
                data={[
                  { type: 'bar', name: '입력', x: usage.daily.map((d) => d.date), y: usage.daily.map((d) => d.prompt_tokens), marker: { color: COLORS.bar } },
                  { type: 'bar', name: '출력', x: usage.daily.map((d) => d.date), y: usage.daily.map((d) => d.completion_tokens), marker: { color: COLORS.barSoft } },
                ]}
              />
            ) : <div className="admin-empty">아직 기록이 없습니다.</div>}
          </div>
        </>
      )}
      <p className="admin-note">
        {path ? <>원장 <code>{path}</code> · </> : null}
        {usage.ledger.first_at ? `기록 ${kstDay(usage.ledger.first_at)} — ${kstDay(usage.ledger.last_at)}` : '기록 없음'}
        {usage.ledger.malformed_lines > 0 && ` · 읽지 못한 줄 ${fmt(usage.ledger.malformed_lines)}개 제외`}
        {' · 사용자·대화별 귀속 없음'}
      </p>
    </>
  );
}

function Diagnostics({ data }: { data: AdminDiagnostics }) {
  const files = Object.entries(data.files ?? {});
  const counts = Object.entries(data.counts ?? {});
  return (
    <div className="admin-split">
      <AdminTable label="데이터 파일 표" headings={['파일', '상태', '크기']}>
        {files.map(([name, info]) => (
          <tr key={name}>
            <th scope="row"><code>{name}</code></th>
            <td className={info.exists ? undefined : 'admin-muted'}>{info.exists ? '있음' : '없음'}</td>
            <td>{info.exists ? kib(info.size) : '—'}</td>
          </tr>
        ))}
      </AdminTable>
      <AdminTable label="테이블 행 수 표" headings={['테이블', '행 수']}>
        {counts.map(([name, n]) => (
          <tr key={name}>
            <th scope="row">{name}</th>
            <td className={n < 0 ? 'admin-bad' : undefined}>{countCopy(n)}</td>
          </tr>
        ))}
      </AdminTable>
    </div>
  );
}

/** 시스템: what it costs and whether the plumbing works — LLM ledger, MCP, data files. */
export default function AdminSystemTab({ days, onDays }: { days: AdminWindowDays; onDays: (days: AdminWindowDays) => void }) {
  const llm = useBlock(fetchAdminLlmUsage, days);
  const diagnostics = useBlock(fetchDiagnostics, days);
  return (
    <div className="admin-tabstack">
      <article className="admin-dashboard visits-report admin-tabview" aria-labelledby="admin-system-title">
        <AdminTabHeader id="admin-system-title" title="시스템" days={days} onDays={onDays} />
        <AdminSection title="LLM 사용량" aside="토큰 단위">
          <BlockBody block={llm} label="LLM 사용량">{(usage) => <LlmUsage usage={usage} />}</BlockBody>
        </AdminSection>
        <AdminSection title="진단" aside="데이터 파일·행 수">
          <BlockBody block={diagnostics} label="진단">{(data) => <Diagnostics data={data} />}</BlockBody>
        </AdminSection>
      </article>
      <Suspense fallback={<div className="admin-loading">MCP 사용 로딩 중...</div>}>
        <AdminMcpReport days={days} />
      </Suspense>
    </div>
  );
}
