import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
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
            <a key={source} href={source} target="_blank" rel="noopener noreferrer">
              출처 {index + 1}
            </a>
          ))}
        </span>
      )}
    </>
  );
}

function SeriesComparison({ comparison, posts }: { comparison: GeoComparisonHub; posts: SeriesPost[] }) {
  const titles = new Map(posts.map((post) => [post.slug, post.title]));
  const entryLabel = (entry: GeoComparisonHub['entries'][number]) => titles.has(entry.slug)
    ? <a href={`/blog/${entry.slug}`} title={titles.get(entry.slug)}>{entry.label}</a>
    : entry.label;
  return (
    <section className="geo-comparison" aria-labelledby="geo-comparison-title">
      <h2 id="geo-comparison-title">논문 선택 비교</h2>
      <p className="geo-comparison-question">{comparison.question}</p>
      <p className="geo-comparison-limits"><strong>해석 한계:</strong> {comparison.limits}</p>
      <p className="geo-comparison-source-note">{comparison.source_note}</p>
      <div className="geo-comparison-desktop">
        <p id="geo-comparison-scroll-hint">같은 기준을 가로로 비교하세요. 표가 잘리면 좌우로 스크롤할 수 있습니다.</p>
        <div className="geo-comparison-scroll" role="region" aria-label="논문 선택 비교표" aria-describedby="geo-comparison-scroll-hint" tabIndex={0}>
          <table>
            <caption>여섯 기준으로 비교한 논문 선택표</caption>
            <thead>
              <tr>
                <th scope="col">비교 기준</th>
                {comparison.entries.map((entry) => <th scope="col" key={entry.slug}>{entryLabel(entry)}</th>)}
              </tr>
            </thead>
            <tbody>
              {comparison.axes.map((axis) => (
                <tr key={axis}>
                  <th scope="row">{AXIS_LABELS[axis]}</th>
                  {comparison.entries.map((entry) => (
                    <td key={entry.slug} data-state={entry.values[axis].state}>
                      <ComparisonCell cell={entry.values[axis]} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="geo-comparison-cards">
        {comparison.entries.map((entry) => (
          <article className="geo-comparison-card" key={entry.slug}>
            <h3>{entryLabel(entry)}</h3>
            <dl>
              {comparison.axes.map((axis) => (
                <div key={axis}>
                  <dt>{AXIS_LABELS[axis]}</dt>
                  <dd data-state={entry.values[axis].state}><ComparisonCell cell={entry.values[axis]} /></dd>
                </div>
              ))}
            </dl>
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
  const navigate = useNavigate();
  const series = BLOG_SERIES[seriesId];
  const comparison = GEO_COMPARISONS[seriesId as keyof typeof GEO_COMPARISONS];
  const [request, setRequest] = useState<SeriesRequest>({ seriesId, status: 'loading', posts: [] });
  const [attempt, setAttempt] = useState(0);
  const current = request.seriesId === seriesId ? request : { status: 'loading', posts: [] };
  const posts = current.posts;

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
        locale={localeFor(detectLang(series.title + series.description))}
        jsonLd={seriesGraph(seriesId, posts)}
      />
      <div className="blog-content">
        <header className="blog-header">
          <nav aria-label="breadcrumb"><a href="/blog" onClick={(e) => { e.preventDefault(); navigate('/blog'); }}>Blog</a></nav>
          <h1 className="blog-title">{series.title}</h1>
          <p className="blog-subtitle">{series.description}</p>
        </header>
        <nav className="blog-series-nav" aria-label="시리즈 바로가기">
          {comparison && <a href="#series-guide-title">읽기 안내</a>}
          <a href="#series-reading-title">추천 읽기 순서</a>
          {comparison && <a href="#geo-comparison-title">논문 선택 비교</a>}
        </nav>
        {comparison && (
          <section className="blog-series-guide" aria-labelledby="series-guide-title">
            <h2 id="series-guide-title">읽기 안내</h2>
            <ol>{comparison.reading_guide.map((step) => <li key={step.title}><h3>{step.title}</h3><p>{step.description}</p></li>)}</ol>
          </section>
        )}
        <section className="blog-series-reading" aria-labelledby="series-reading-title">
          <h2 id="series-reading-title">추천 읽기 순서</h2>
          {current.status === 'loading' && <p role="status">시리즈 글을 불러오는 중입니다.</p>}
          {current.status === 'error' && (
            <div className="blog-series-error">
              <p role="alert">시리즈 글을 불러오지 못했습니다. 다시 시도해 주세요.</p>
              <button type="button" onClick={() => { setRequest({ seriesId, status: 'loading', posts: [] }); setAttempt((value) => value + 1); }}>다시 시도</button>
            </div>
          )}
          {current.status === 'success' && (posts.length === 0
            ? <p role="status">아직 공개된 시리즈 글이 없습니다.</p>
            : <ol className="blog-series-list">
              {posts.map((post, i) => (
                <li key={post.slug}>
                  <a href={`/blog/${post.slug}`} onClick={(e) => { e.preventDefault(); navigate(`/blog/${post.slug}`); }}>
                    <span className="blog-series-pos" aria-hidden="true">{i + 1}</span>
                    <span className="blog-series-item-title">{post.title}</span>
                  </a>
                  <p className="blog-series-item-excerpt">{post.excerpt}</p>
                </li>
              ))}
            </ol>)}
        </section>
        {comparison && <SeriesComparison comparison={comparison} posts={posts} />}
      </div>
    </div>
  );
}

export default SeriesPage;
