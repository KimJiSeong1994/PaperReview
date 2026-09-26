import { useEffect, useState } from 'react';
import './BlogPage.css';
import SEOHead from './SEOHead';
import { BLOG_SERIES } from '../seo/series';
import { SITE_URL, seriesGraph, detectLang, localeFor } from '../seo/structuredData';
import { fetchBlogPosts } from '../api/client';
import {
  GEO_COMPARISONS,
  type GeoComparisonAxis,
  type GeoComparisonHub,
} from '../seo/geoComparisons.generated';

interface SeriesPost {
  slug: string;
  title: string;
  excerpt: string;
  reading_time_min: number;
}

interface SeriesPageProps {
  seriesId: string;
}

type SeriesRequest = {
  seriesId: string;
  status: 'loading' | 'success' | 'error';
  posts: SeriesPost[];
};

const AXIS_LABELS: Record<GeoComparisonAxis, string> = {
  retrieval_or_representation_unit: '다루는 정보·표현 단위',
  graph_construction: '입력 그래프와 구성',
  evaluation_context: '평가 조건',
  traceability: '설명·근거 확인',
  cost: '비용',
  failure_conditions: '실패 조건',
};

function ComparisonCell({ cell }: { cell: GeoComparisonHub['entries'][number]['values'][GeoComparisonAxis] }) {
  const stateLabel = cell.state === 'unknown' ? '미확인: ' : cell.state === 'not_applicable' ? '해당 없음: ' : '';
  return (
    <>
      {stateLabel}{cell.state === 'known' ? cell.value : cell.reason}
      {cell.sources.length > 0 && (
        <span className="geo-comparison-sources">
          {cell.sources.map((source, index) => (
            <a key={source} href={source} rel="noopener noreferrer">
              출처 {index + 1}
            </a>
          ))}
        </span>
      )}
    </>
  );
}

function SeriesComparison({ comparison, posts, detailed = false }: { comparison: GeoComparisonHub; posts: SeriesPost[]; detailed?: boolean }) {
  const titles = new Map(posts.map((post) => [post.slug, post.title]));
  const entryLabel = (entry: GeoComparisonHub['entries'][number]) => titles.has(entry.slug)
    ? <a href={`/blog/${entry.slug}`} title={titles.get(entry.slug)}>{entry.label}</a>
    : entry.label;
  if (detailed) return (
    <section className="geo-evidence" aria-labelledby="series-evidence-title">
      <p className="blog-series-kicker">근거를 확인하며 읽기</p>
      <h2 id="series-evidence-title">상세 근거와 출처</h2>
      <p className="geo-comparison-question">{comparison.question}</p>
      <p className="geo-comparison-limits"><strong>해석 한계:</strong> {comparison.limits}</p>
      <p className="geo-comparison-source-note">{comparison.source_note}</p>
      {comparison.entries.map((entry, index) => (
          <article className="geo-evidence-method" key={entry.slug} aria-labelledby={`series-evidence-${index + 1}`}>
            <h3 id={`series-evidence-${index + 1}`}>{entryLabel(entry)}</h3>
            <dl>
              {comparison.axes.map((axis) => (
                <div key={axis}>
                  <dt>{AXIS_LABELS[axis]}</dt>
                  <dd data-state={entry.values[axis].state}><ComparisonCell cell={entry.values[axis]} /></dd>
                </div>
              ))}
            </dl>
            <a className="blog-series-text-link" href="#geo-comparison-title">선택 요약으로 돌아가기</a>
          </article>
        ))}
    </section>
  );
  return (
    <section className="geo-comparison" aria-labelledby="geo-comparison-title">
      <p className="blog-series-kicker">질문에 맞춰 고르기</p>
      <h2 id="geo-comparison-title">논문 선택 비교</h2>
      <p className="geo-comparison-caveat">성능 순위가 아닌 역할 비교입니다. 평가 조건과 한계는 상세 근거에서 확인하세요.</p>
      <div className="geo-decision-grid">
        {comparison.entries.map((entry, index) => (
          <article className="geo-decision" key={entry.slug}>
            <h3>{entryLabel(entry)}</h3>
            <dl>
              <div><dt>역할</dt><dd>{entry.summary.role}</dd></div>
              <div><dt>이럴 때</dt><dd>{entry.summary.fit}</dd></div>
              <div><dt>주의점</dt><dd>{entry.summary.caution}</dd></div>
            </dl>
            <a className="blog-series-text-link" href={`#series-evidence-${index + 1}`}>{entry.label} 상세 근거 <span aria-hidden="true">→</span></a>
          </article>
        ))}
      </div>
    </section>
  );
}

function SeriesPage({ seriesId }: SeriesPageProps) {
  return <SeriesPageContent key={seriesId} seriesId={seriesId} />;
}

function SeriesPageContent({ seriesId }: SeriesPageProps) {
  const series = BLOG_SERIES[seriesId];
  const comparison = GEO_COMPARISONS[seriesId as keyof typeof GEO_COMPARISONS];
  const [request, setRequest] = useState<SeriesRequest>({ seriesId, status: 'loading', posts: [] });
  const [attempt, setAttempt] = useState(0);
  const current: Pick<SeriesRequest, 'status' | 'posts'> = request.seriesId === seriesId ? request : { status: 'loading', posts: [] };
  const posts = current.posts;
  const first = posts[0];
  const readingList = (members: SeriesPost[]) => (
    <ol className="blog-series-list" start={posts.indexOf(members[0]) + 1}>
      {members.map((post) => (
        <li key={post.slug}>
          <a href={`/blog/${post.slug}`}>
            <span className="blog-series-pos" aria-hidden="true">{posts.indexOf(post) + 1}</span>
            <span className="blog-series-item-title">{post.title}</span>
          </a>
          <p className="blog-series-item-excerpt">{post.excerpt}</p>
        </li>
      ))}
    </ol>
  );

  useEffect(() => {
    if (!series) return;
    let cancelled = false;
    async function loadPosts() {
      const bySlug = new Map<string, SeriesPost>();
      const wanted = new Set(series.slugs);
      try {
        let page = 1;
        while (wanted.size > 0) {
          const response = await fetchBlogPosts(undefined, undefined, page, 100);
          if (cancelled) return;
          const data = response.data as { posts: SeriesPost[]; page: number; pages: number };
          if (!data || !Array.isArray(data.posts) || data.page !== page
            || !Number.isInteger(data.pages) || data.pages < page) {
            throw new Error('Invalid series pagination response');
          }
          for (const post of data.posts) {
            if (wanted.delete(post.slug)) bySlug.set(post.slug, post);
          }
          if (data.page >= data.pages) break;
          page = data.page + 1;
        }
        if (!cancelled) setRequest({ seriesId, status: 'success', posts: series.slugs.flatMap((slug) => bySlug.get(slug) ?? []) });
      } catch {
        if (!cancelled) setRequest({ seriesId, status: 'error', posts: [] });
      }
    }
    void loadPosts();
    return () => { cancelled = true; };
  }, [series, seriesId, attempt]);

  if (!series) {
    return (
      <div className="blog-container">
        <SEOHead title="Series not found | Jiphyeonjeon Blog" description="Series not found." canonical={`${SITE_URL}/blog`} robots="noindex,nofollow" />
        <div className="blog-content"><div className="blog-error">Series not found.</div></div>
      </div>
    );
  }

  return (
    <div className="blog-container blog-series-page">
      <SEOHead
        title={`${series.title} | Jiphyeonjeon Blog`}
        description={series.description}
        canonical={`${SITE_URL}/blog/series/${seriesId}`}
        robots={current.status === 'success' && posts.length === 0 ? 'noindex,nofollow' : undefined}
        locale={localeFor(detectLang(series.title + series.description))}
        jsonLd={seriesGraph(seriesId, posts)}
      />
      <div className="blog-content">
        <header className="blog-header">
          <nav aria-label="breadcrumb"><a href="/blog">집현전 블로그</a></nav>
          <h1 className="blog-title">{series.title}</h1>
          <p className="blog-subtitle">{series.description.split('. ')[0]}{series.description.includes('. ') ? '.' : ''}</p>
        </header>
        <section className="blog-series-start" aria-labelledby="series-start-title">
          <p className="blog-series-kicker">여기서 시작하세요</p>
          {first ? <>
            <h2 id="series-start-title"><a href={`/blog/${first.slug}`}>{first.title}</a></h2>
            <a className="blog-series-start-cta" href={`/blog/${first.slug}`}>첫 글 읽기 <span aria-hidden="true">→</span></a>
          </> : <>
            <h2 id="series-start-title">첫 글부터 차근차근</h2>
            {current.status === 'loading' && <p role="status">시리즈 글을 불러오는 중입니다.</p>}
            {current.status === 'error' && <div className="blog-series-error">
              <p role="alert">시리즈 글을 불러오지 못했습니다. 다시 시도해 주세요.</p>
              <button type="button" onClick={() => { setRequest({ seriesId, status: 'loading', posts: [] }); setAttempt((value) => value + 1); }}>다시 시도</button>
            </div>}
            {current.status === 'success' && <p role="status">아직 공개된 시리즈 글이 없습니다.</p>}
          </>}
        </section>
        {comparison && (
          <nav className="blog-series-path" aria-labelledby="series-guide-title">
            <h2 id="series-guide-title">한눈에 보는 학습 경로</h2>
            <ol>{comparison.reading_guide.map((step, index) => <li key={step.title}>
              <a href={`#series-stage-${index + 1}`}>{step.title}</a>
            </li>)}</ol>
          </nav>
        )}
        <nav className="blog-series-nav" aria-label="시리즈 바로가기">
          {comparison && <a href="#geo-comparison-title">논문 선택 비교</a>}
          <a href="#series-reading-title">추천 읽기 순서</a>
          {comparison && <a href="#series-evidence-title">상세 근거와 출처</a>}
        </nav>
        {comparison && <SeriesComparison comparison={comparison} posts={posts} />}
        <section className="blog-series-reading" aria-labelledby="series-reading-title">
          <p className="blog-series-kicker">개념을 연결하며 읽기</p>
          <h2 id="series-reading-title">추천 읽기 순서</h2>
          <p className="blog-series-reading-intro">{series.description}</p>
          {comparison ? comparison.reading_guide.map((step, index) => {
            const members = posts.filter((post) => step.slugs.includes(post.slug));
            return <section className="blog-series-stage" key={step.title} aria-labelledby={`series-stage-${index + 1}`}>
              <div className="blog-series-stage-heading"><h3 id={`series-stage-${index + 1}`}>{step.title}</h3></div>
              <p className="blog-series-stage-description">{step.description}</p>
              {members.length > 0 ? readingList(members) : current.status === 'success' && <p>이 단계에는 아직 공개된 글이 없습니다.</p>}
            </section>;
          }) : posts.length > 0 && readingList(posts)}
        </section>
        {comparison && <SeriesComparison comparison={comparison} posts={posts} detailed />}
      </div>
    </div>
  );
}

export default SeriesPage;
