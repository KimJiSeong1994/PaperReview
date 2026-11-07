import { Link } from 'react-router-dom';
import { fetchAdminOverview, type AdminOverview, type AdminWindowDays } from '../api/client';
import { fmt, kstDay, useBlock } from './adminShared';
import { AdminChart, AdminTabHeader, BlockBody } from './AdminUi';
import './AdminOverviewTab.css';

const METRICS = [
  { key: 'visitors', label: '방문자', unit: '명', hint: '중복을 제외한 브라우저 수' },
  { key: 'page_views', label: '페이지 조회', unit: '회', hint: '전체 페이지가 열린 횟수' },
  { key: 'returning_visitors', label: '재방문자', unit: '명', hint: '이전 방문 기록이 있는 브라우저' },
] as const;
const PAGE_NAMES: Record<string, string> = { '/': '집현전 홈', '/blog': '블로그 목록', '/introduce': '서비스 소개', '/ko/introduce': '서비스 소개', '/c/:id': '대화 화면' };
const SOURCE_NAMES: Record<string, string> = { '(direct)': '직접 방문', google: 'Google', naver: '네이버', bing: 'Bing', 'youtube.com': 'YouTube', 'chatgpt.com': 'ChatGPT' };
const MEDIUM_NAMES: Record<string, string> = { organic: '검색', referral: '링크', social: '소셜', email: '이메일', cpc: '광고' };
const timestamp = (iso: string) => new Date(iso).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });

function Change({ current, previous, available }: { current: number; previous: number; available: boolean }) {
  if (!available) return <span className="overview-change overview-change--muted">비교 데이터 부족</span>;
  if (previous === 0) return <span className="overview-change overview-change--muted">{current === 0 ? '변화 없음' : '이전 0 · 증감률 없음'}</span>;
  const change = (current - previous) / previous * 100;
  return <span className={`overview-change ${change > 0 ? 'overview-change--up' : change < 0 ? 'overview-change--down' : 'overview-change--muted'}`}>
    {change === 0 ? '변화 없음' : `${change > 0 ? '↑' : '↓'} ${Math.abs(change).toFixed(1)}%`}
  </span>;
}

function TrafficOverview({ report }: { report: AdminOverview }) {
  const { totals, comparison, acquisition, measurement } = report;
  return <>
    <div className="overview-meta">
      <span>{kstDay(report.window.start)} — {kstDay(report.window.end)} <span className="overview-muted">· KST</span></span>
      <span className="overview-muted">{measurement.last_at ? `마지막 방문 기록 ${timestamp(measurement.last_at)}` : '아직 수집된 방문 기록이 없습니다'}</span>
    </div>
    <div className="overview-metrics" role="group" aria-label="방문 핵심 지표">
      {METRICS.map(({ key, label, unit, hint }) => <article key={key} className="overview-metric" title={hint}>
        <p className="overview-metric-label">{label}</p>
        <div className="overview-metric-number"><strong>{fmt(totals[key])}</strong><span>{unit}</span></div>
        <div className="overview-metric-change">
          <Change current={totals[key]} previous={comparison.totals[key]} available={comparison.available} />
          {comparison.available && <span>이전 {report.window.days}일 대비</span>}
        </div>
      </article>)}
    </div>
    <section className="overview-panel overview-trend" aria-labelledby="overview-trend-title">
      <div className="overview-panel-head"><h2 id="overview-trend-title">방문 추이</h2><span>일별 방문자 · 명</span></div>
      {measurement.first_at ? <AdminChart label="일별 방문자 추이" height={190} showlegend={false} data={[{
        type: 'scatter', mode: 'lines+markers', name: '방문자',
        x: report.daily.map((row) => row.date), y: report.daily.map((row) => row.visitors),
        line: { color: '#4f46e5', width: 2.5 }, marker: { size: 5, color: '#4f46e5' },
        fill: 'tozeroy', fillcolor: 'rgba(79,70,229,0.06)', hovertemplate: '%{x}<br>%{y:,}명<extra></extra>',
      }]} /> : <p className="overview-empty">방문 기록이 쌓이면 추이가 표시됩니다.</p>}
    </section>
    <div className="overview-ranks">
      <section className="overview-panel" aria-labelledby="overview-pages-title">
        <div className="overview-panel-head"><h2 id="overview-pages-title">많이 본 페이지</h2><span>상위 5개 · 조회 수</span></div>
        {report.top_pages.length ? <ol className="overview-ranking">
          {report.top_pages.map((page, i) => {
            const title = page.title || PAGE_NAMES[page.path] || page.path;
            const canLink = /^\/(?!\/)/.test(page.path) && !page.path.includes(':');
            return <li key={page.path}>
              <span className="overview-rank-number">{i + 1}</span>
              {canLink ? <Link className="overview-rank-title" title={title} to={page.path}>{title}</Link> : <span className="overview-rank-title">{title}</span>}
              <strong>{fmt(page.views)}<small>회</small></strong>
            </li>;
          })}
        </ol> : <p className="overview-empty">집계된 페이지 조회가 없습니다.</p>}
      </section>
      <section className="overview-panel" aria-labelledby="overview-sources-title">
        <div className="overview-panel-head"><h2 id="overview-sources-title">유입 경로</h2><span>GA4 · 세션 수</span></div>
        {acquisition.state === 'failed' && <p className="overview-source-warning">최근 동기화 실패 · 마지막 집계 기준</p>}
        {acquisition.channels.length ? <ol className="overview-ranking">
          {acquisition.channels.map((channel, i) => <li key={`${channel.source}/${channel.medium}`}>
            <span className="overview-rank-number">{i + 1}</span>
            <span className="overview-rank-title">{SOURCE_NAMES[channel.source] || channel.source}<small>{MEDIUM_NAMES[channel.medium] || (channel.medium === '(none)' ? '' : channel.medium)}</small></span>
            <strong>{fmt(channel.sessions)}</strong>
          </li>)}
        </ol> : <p className="overview-empty">{acquisition.state === 'connected' ? '이 기간에 집계된 유입 경로가 없습니다.' : acquisition.state === 'failed' ? '유입 경로 데이터를 불러올 수 없습니다.' : '유입 경로 데이터가 아직 연결되지 않았습니다.'}</p>}
        {acquisition.synced_at && <p className="overview-source-time">동기화 {timestamp(acquisition.synced_at)}</p>}
      </section>
    </div>
    <footer className="overview-footer">
      <details><summary>측정 기준 · 분석에 동의한 브라우저 표본</summary>
        <p>방문자는 브라우저 식별자로 중복을 제거합니다. 재방문자는 선택 기간 이전에 방문 기록이 있는 브라우저입니다. 로그인 계정 수와 다르며, 브라우저 변경·쿠키 삭제와 보관 이력의 영향을 받습니다.</p>
        <p>증감은 이전 {report.window.days}일의 같은 경과 시간까지 비교합니다. 비교 구간 시작 이전의 수집 기록이 없으면 증감률을 숨깁니다. 기록이 있다고 모든 시간대의 수집이 보장되지는 않습니다.</p>
        <p>유입 경로는 별도 GA4 동기화 데이터이며 위 방문자 수와 합산하지 않습니다. 날짜는 KST입니다.</p>
      </details>
      <Link to="/admin?tab=growth">방문 상세 보기 →</Link>
    </footer>
  </>;
}

export default function AdminOverviewTab({ days, onDays }: { days: AdminWindowDays; onDays: (days: AdminWindowDays) => void }) {
  const overview = useBlock(fetchAdminOverview, days);
  return <article className="visits-report admin-tabview admin-overview" aria-labelledby="admin-overview-title">
    <AdminTabHeader id="admin-overview-title" title="대시보드" days={days} onDays={onDays} />
    <BlockBody block={overview} label="대시보드">{(report) => <TrafficOverview report={report} />}</BlockBody>
  </article>;
}
