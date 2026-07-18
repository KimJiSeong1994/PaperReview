import { Component, lazy, Suspense } from 'react';
import type { ReactNode } from 'react';
import type { AdminDashboard } from '../api/client';

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

function InsightCard({ eyebrow, headline, body }: { eyebrow: string; headline: ReactNode; body: string }) {
  return (
    <article className="visits-insight-card">
      <p className="visits-insight-eyebrow">{eyebrow}</p>
      <h3 className="visits-insight-headline">{headline}</h3>
      <p className="visits-insight-body">{body}</p>
    </article>
  );
}

function Band({ label, title, description }: { label: string; title: string; description: string }) {
  return (
    <header className="visits-band" aria-label={label}>
      <span className="visits-band-eyebrow">{label}</span>
      <h2>{title}</h2>
      <p>{description}</p>
    </header>
  );
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
  const totalGraph = (stats.kg_nodes ?? 0) + (stats.kg_edges ?? 0);
  const latestPaper = stats.recent_papers?.[0];
  const latestDate = latestPaper?.collected_at
    ? new Date(latestPaper.collected_at).toLocaleDateString('ko-KR')
    : '기록 없음';

  return (
    <article className="admin-dashboard visits-report dashboard-report">
      <header className="visits-report-header dashboard-report-header">
        <div className="visits-report-heading">
          <span className="visits-report-kicker">ADMIN OVERVIEW</span>
          <h1>서비스 운영 리포트</h1>
          <p>사용자와 논문 데이터, 지식 그래프, 최근 수집 흐름을 하나의 운영 맥락으로 읽습니다.</p>
        </div>
        <div className="dashboard-live-status" aria-label="누적 운영 현황">
          <span aria-hidden="true" />
          누적 운영 현황
        </div>
      </header>

      <section className="visits-summary" aria-labelledby="dashboard-summary-title">
        <span className="visits-summary-kicker">핵심 요약</span>
        <h2 id="dashboard-summary-title">현재 운영 상태를 한 문장씩 읽어보세요</h2>
        <p className="visits-summary-copy">개별 수치보다 먼저 이용 규모, 저장 행동, 지식 연결의 전체 모습을 보여줍니다.</p>
        <div className="visits-insight-grid">
          <InsightCard
            eyebrow="이용과 콘텐츠"
            headline={<>{fmt(stats.total_users)}명 등록 · {fmt(stats.total_papers)}편 보유</>}
            body="등록 계정 수와 전역 논문 카탈로그의 누적 규모이며, 사용자별 열람량을 뜻하지 않습니다."
          />
          <InsightCard
            eyebrow="저장과 최근 작업"
            headline={<>{fmt(stats.total_bookmarks)}개 저장 · {fmt(recentReviewSessions)}개 리뷰 작업</>}
            body="리뷰 작업은 최근 24시간의 인메모리 작업 수로, 방문 세션이나 영구 작업 이력이 아닙니다."
          />
          <InsightCard
            eyebrow="지식 연결"
            headline={<>{fmt(stats.kg_nodes)}개 노드 · {fmt(stats.kg_edges)}개 연결</>}
            body={`지식 그래프 안에 총 ${fmt(totalGraph)}개의 탐색 단서가 구성돼 있습니다.`}
          />
        </div>
      </section>

      <div className="dashboard-context-strip" aria-label="리포트 기준">
        <div><span>집계 기준</span><strong>누적 자산 · 휘발성 작업 분리</strong></div>
        <div><span>주요 수집원</span><strong>{leadingSource?.source ?? '기록 없음'}</strong></div>
        <div><span>최근 수집</span><strong>{latestDate}</strong></div>
      </div>

      <Band
        label="운영 기반"
        title="콘텐츠와 지식 그래프"
        description="서비스가 현재 어느 정도의 사용자, 논문, 지식 연결을 품고 있는지 봅니다."
      />

      <section className="visits-section dashboard-section">
        <div className="dashboard-section-heading">
          <div>
            <span>01 · SCALE</span>
            <h3>운영 규모</h3>
          </div>
          <p>사용량과 데이터 자산의 누적 규모</p>
        </div>
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

      <Band
        label="수집 메타데이터"
        title="수집 기여와 분류"
        description="검색 인기도가 아니라, 저장된 논문에 남은 수집 쿼리와 연구 분야를 비교합니다."
      />
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

      <Band
        label="수집 흐름"
        title="최근 들어온 논문"
        description="가장 최근에 추가된 콘텐츠와 수집원을 시간 순서로 확인합니다."
      />
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
    </article>
  );
}
