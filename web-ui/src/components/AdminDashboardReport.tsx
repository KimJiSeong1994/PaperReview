import { Component, lazy, Suspense } from 'react';
import type { ReactNode } from 'react';
import type { AdminDashboard } from '../api/client';
import AdminDetailsRow from './AdminDetailsRow';

const Plot = lazy(() => import('../PlotlyChart'));

const nf = new Intl.NumberFormat('ko-KR');
const fmt = (value: number) => nf.format(value ?? 0);

class DashboardChartBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return <div className="admin-empty">차트를 표시할 수 없습니다.</div>;
    }
    return this.props.children;
  }
}

function StatTile({ label, value, hint }: { label: string; value: ReactNode; hint: string }) {
  return (
    <article className="admin-stat-card">
      <p className="admin-stat-label">{label}</p>
      <p className="admin-stat-value">{value}</p>
      <p className="visits-stat-hint">{hint}</p>
    </article>
  );
}

function RankList({
  title,
  emptyLabel,
  rows,
}: {
  title: string;
  emptyLabel: string;
  rows: { label: string; count: number }[];
}) {
  const maxCount = Math.max(...rows.map((row) => row.count), 0);
  return (
    <section className="dashboard-rank-card">
      <h3>{title}</h3>
      {rows.length > 0 ? (
        <ol className="dashboard-rank-list">
          {rows.map((row, index) => (
            <li key={`${row.label}-${index}`} className="dashboard-rank-item">
              <span className="dashboard-rank-index">{String(index + 1).padStart(2, '0')}</span>
              <div className="dashboard-rank-detail">
                <div className="dashboard-rank-copy">
                  <span>{row.label}</span>
                  <strong>{fmt(row.count)}</strong>
                </div>
                <span className="dashboard-rank-track" aria-hidden="true">
                  <span style={{ width: `${maxCount ? (row.count / maxCount) * 100 : 0}%` }} />
                </span>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <div className="admin-empty">{emptyLabel}</div>
      )}
    </section>
  );
}

export default function AdminDashboardReport({ stats }: { stats: AdminDashboard }) {
  const recentReviewSessions = stats.recent_review_sessions ?? stats.total_sessions ?? 0;
  const collectionQueries = stats.collection_queries ?? stats.top_queries ?? [];
  const leadingSource = stats.papers_by_source?.reduce<(typeof stats.papers_by_source)[number] | null>(
    (leader, current) => (!leader || current.count > leader.count ? current : leader),
    null,
  );
  const latestPaper = stats.recent_papers?.[0];
  const latestDate = latestPaper?.collected_at
    ? new Date(latestPaper.collected_at).toLocaleDateString('ko-KR')
    : '기록 없음';

  return (
    <>
      <AdminDetailsRow
        id="legacy-content"
        title="콘텐츠·지식 그래프 (레거시)"
        summary={`회원 ${fmt(stats.total_users)} · 논문 ${fmt(stats.total_papers)} · 북마크 ${fmt(stats.total_bookmarks)}`}
      >
      <div className="dashboard-context-strip" aria-label="리포트 기준">
        <div><span>집계 기준</span><strong>누적 자산 · 휘발성 작업 분리</strong></div>
        <div><span>주요 수집원</span><strong>{leadingSource?.source ?? '기록 없음'}</strong></div>
        <div><span>최근 수집</span><strong>{latestDate}</strong></div>
      </div>

      <section className="dashboard-section">
        <div className="admin-stats-grid dashboard-stat-grid">
          <StatTile label="사용자" value={fmt(stats.total_users)} hint="등록 계정" />
          <StatTile label="논문" value={fmt(stats.total_papers)} hint="수집 콘텐츠" />
          <StatTile label="북마크" value={fmt(stats.total_bookmarks)} hint="저장 행동" />
          <StatTile label="최근 리뷰 작업" value={fmt(recentReviewSessions)} hint="24시간 인메모리" />
          <StatTile label="KG 노드" value={fmt(stats.kg_nodes)} hint="지식 개체" />
          <StatTile label="KG 연결" value={fmt(stats.kg_edges)} hint="개체 관계" />
        </div>

        <div className="dashboard-chart-grid">
          <section className="dashboard-chart-card">
            <div className="dashboard-card-heading">
              <div><span>SOURCE MIX</span><h3>수집원 구성</h3></div>
              <p>논문이 들어온 경로</p>
            </div>
            {(stats.papers_by_source?.length ?? 0) > 0 ? (
              <DashboardChartBoundary>
                <Suspense fallback={<div className="admin-loading">차트 로딩 중...</div>}>
                  <Plot
                    data={[{
                      type: 'pie',
                      hole: 0.62,
                      labels: stats.papers_by_source.map((item) => item.source),
                      values: stats.papers_by_source.map((item) => item.count),
                      marker: { colors: ['#4f46e5', '#766cf3', '#a7a1f7', '#d8d5fb', '#eceafe'] },
                      textinfo: 'label+percent',
                      textfont: { color: '#4d4958', size: 11, family: 'Pretendard, sans-serif' },
                      hoverinfo: 'label+value+percent',
                    }]}
                    layout={{
                      paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
                      margin: { t: 8, b: 8, l: 8, r: 8 }, showlegend: false, height: 270,
                      font: { color: '#706d7d', family: 'Pretendard, sans-serif' },
                    }}
                    config={{ displayModeBar: false, responsive: true }}
                    style={{ width: '100%' }}
                  />
                </Suspense>
              </DashboardChartBoundary>
            ) : <div className="admin-empty">수집원 데이터가 없습니다.</div>}
          </section>

          <section className="dashboard-chart-card">
            <div className="dashboard-card-heading">
              <div><span>YEARLY ARCHIVE</span><h3>연도별 논문</h3></div>
              <p>출판 연도 기준 분포</p>
            </div>
            {(stats.papers_by_year?.length ?? 0) > 0 ? (
              <DashboardChartBoundary>
                <Suspense fallback={<div className="admin-loading">차트 로딩 중...</div>}>
                  <Plot
                    data={[{
                      type: 'bar',
                      x: stats.papers_by_year.map((item) => item.year),
                      y: stats.papers_by_year.map((item) => item.count),
                      marker: { color: '#7167ec', line: { width: 0 } },
                      hoverinfo: 'x+y',
                    }]}
                    layout={{
                      paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
                      margin: { t: 12, b: 36, l: 44, r: 12 }, height: 270,
                      font: { color: '#706d7d', size: 11, family: 'Pretendard, sans-serif' },
                      xaxis: { gridcolor: 'transparent', color: '#858291', fixedrange: true },
                      yaxis: { gridcolor: '#ecebf0', color: '#858291', zeroline: false, fixedrange: true },
                      bargap: 0.38,
                    }}
                    config={{ displayModeBar: false, responsive: true }}
                    style={{ width: '100%' }}
                  />
                </Suspense>
              </DashboardChartBoundary>
            ) : <div className="admin-empty">연도별 데이터가 없습니다.</div>}
          </section>
        </div>
      </section>
      </AdminDetailsRow>

      <AdminDetailsRow
        id="legacy-collection"
        title="수집 기여·분류"
        summary={`쿼리 ${fmt(collectionQueries.length)} · 분야 ${fmt(stats.top_categories?.length ?? 0)} · 검색 인기도가 아니라 저장된 논문의 수집 쿼리`}
      >
      <div className="dashboard-rank-grid">
        <RankList
          title="논문 수집 기여 쿼리 · 논문 수"
          emptyLabel="수집 쿼리 데이터가 없습니다."
          rows={collectionQueries.map((item) => ({ label: item.query, count: item.count }))}
        />
        <RankList
          title="상위 연구 분야"
          emptyLabel="분류 데이터가 없습니다."
          rows={(stats.top_categories ?? []).map((item) => ({ label: item.category, count: item.count }))}
        />
      </div>
      </AdminDetailsRow>

      <AdminDetailsRow
        id="legacy-recent"
        title="최근 들어온 논문"
        summary={`${fmt(stats.recent_papers.length)}편 · 최근 수집 ${latestDate}`}
      >
      <section className="dashboard-recent-card">
        {stats.recent_papers.length > 0 ? (
          <ol className="dashboard-recent-list">
            {stats.recent_papers.map((paper, index) => (
              <li key={`${paper.title}-${index}`}>
                <span className="dashboard-recent-index">{String(index + 1).padStart(2, '0')}</span>
                <div>
                  <strong>{paper.title}</strong>
                  <span>{paper.source}</span>
                </div>
                <time dateTime={paper.collected_at}>
                  {paper.collected_at ? new Date(paper.collected_at).toLocaleDateString('ko-KR') : '-'}
                </time>
              </li>
            ))}
          </ol>
        ) : <div className="admin-empty">최근 수집된 논문이 없습니다.</div>}
      </section>
      </AdminDetailsRow>
    </>
  );
}
