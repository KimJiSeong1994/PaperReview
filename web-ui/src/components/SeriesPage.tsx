import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import './BlogPage.css';
import SEOHead from './SEOHead';
import BlogAppHeader from './BlogAppHeader';
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
  thumbnail_url?: string | null;
  category?: string;
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

/** Ask the figure endpoint for a resized copy; leave any other URL alone
 * (mirrors BlogPage.tsx's figureSrc so both surfaces request the same asset). */
function figureSrc(url: string, width: number): string {
  if (!url.includes('/api/blog/figures/')) return url;
  return `${url}${url.includes('?') ? '&' : '?'}w=${width}`;
}

/** The opening sentence of a description/excerpt: the claim without its hedge.
 *  A half-clamped caveat reads as a broken claim, so lists show sentence one. */
function firstSentence(text: string): string {
  const trimmed = text.trim();
  const cut = trimmed.indexOf('. ');
  return cut === -1 ? trimmed : trimmed.slice(0, cut + 1);
}

function totalMinutes(posts: SeriesPost[]): number | null {
  if (posts.length === 0) return null;
  let total = 0;
  for (const post of posts) {
    if (!Number.isFinite(post.reading_time_min)) return null;
    total += post.reading_time_min;
  }
  return total;
}

function ComparisonCell({ cell }: { cell: GeoComparisonHub['entries'][number]['values'][GeoComparisonAxis] }) {
  const stateLabel = cell.state === 'unknown' ? '미확인' : cell.state === 'not_applicable' ? '해당 없음' : '';
  return (
    <>
      {stateLabel && <span className="geo-state">{stateLabel}</span>}
      {cell.state === 'known' ? cell.value : cell.reason}
    </>
  );
}

/** True when every axis of the entry shares one identical, non-empty source list. */
function sharedSources(entry: GeoComparisonHub['entries'][number], axes: GeoComparisonAxis[]): string[] | null {
  const first = entry.values[axes[0]].sources;
  if (first.length === 0) return null;
  const same = axes.every((axis) => {
    const sources = entry.values[axis].sources;
    return sources.length === first.length && sources.every((source, index) => source === first[index]);
  });
  return same ? first : null;
}

function SourceLinks({ sources }: { sources: string[] }) {
  return (
    <span className="geo-comparison-sources">
      {sources.map((source, index) => (
        <a key={source} href={source} rel="noopener noreferrer">출처 {index + 1}</a>
      ))}
    </span>
  );
}

function SeriesComparison({ comparison, posts, detailed = false }: { comparison: GeoComparisonHub; posts: SeriesPost[]; detailed?: boolean }) {
  const titles = new Map(posts.map((post) => [post.slug, post.title]));
  const entryLabel = (entry: GeoComparisonHub['entries'][number]) => titles.has(entry.slug)
    ? <a href={`/blog/${entry.slug}`} title={titles.get(entry.slug)}>{entry.label}</a>
    : entry.label;
  if (detailed) return (
    <section className="geo-evidence" aria-labelledby="series-evidence-title">
      <h2 id="series-evidence-title">상세 근거와 출처</h2>
      <p className="geo-comparison-limits"><strong>해석 한계:</strong> {comparison.limits}</p>
      <p className="geo-comparison-source-note">{comparison.source_note}</p>
      {comparison.entries.map((entry, index) => {
        const hoisted = sharedSources(entry, comparison.axes);
        return (
          <article className="geo-evidence-method" key={entry.slug} aria-labelledby={`series-evidence-${index + 1}`}>
            <h3 id={`series-evidence-${index + 1}`}>{entryLabel(entry)}</h3>
            {hoisted && (
              <div className="geo-evidence-method-sources">
                <span className="geo-evidence-method-sources-label">전 항목 출처</span>
                <SourceLinks sources={hoisted} />
              </div>
            )}
            <dl>
              {comparison.axes.map((axis) => (
                <div key={axis}>
                  <dt>{AXIS_LABELS[axis]}</dt>
                  <dd data-state={entry.values[axis].state}>
                    <ComparisonCell cell={entry.values[axis]} />
                    {!hoisted && entry.values[axis].sources.length > 0 && <SourceLinks sources={entry.values[axis].sources} />}
                  </dd>
                </div>
              ))}
            </dl>
            <a className="blog-series-text-link" href="#geo-comparison-title">논문 선택 비교로 돌아가기 <span aria-hidden="true">↑</span></a>
          </article>
        );
      })}
    </section>
  );
  return (
    <section className="geo-comparison" aria-labelledby="geo-comparison-title">
      <h2 id="geo-comparison-title">논문 선택 비교</h2>
      <p className="geo-comparison-question">{comparison.question}</p>
      <p className="geo-comparison-caveat">성능 순위가 아닌 역할 비교입니다. 평가 조건과 한계는 상세 근거에서 확인하세요.</p>
      <div className="geo-decision-grid" data-count={comparison.entries.length}>
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
  const { hash } = useLocation();
  const series = BLOG_SERIES[seriesId];
  const comparison = GEO_COMPARISONS[seriesId as keyof typeof GEO_COMPARISONS];
  const [request, setRequest] = useState<SeriesRequest>({ seriesId, status: 'loading', posts: [] });
  const [attempt, setAttempt] = useState(0);
  const current: Pick<SeriesRequest, 'status' | 'posts'> = request.seriesId === seriesId ? request : { status: 'loading', posts: [] };
  const posts = current.posts;
  const first = posts[0];
  const catMeta = first ? (first.category === 'paper-review' ? 'paper-review' : 'engineering') : undefined;
  const total = totalMinutes(posts);
  const readingList = (members: SeriesPost[]) => (
    <ol className="blog-series-list" start={posts.indexOf(members[0]) + 1}>
      {members.map((post) => (
        <li key={post.slug}>
          <span className="blog-series-pos" aria-hidden="true">{posts.indexOf(post) + 1}</span>
          <a className="blog-row" href={`/blog/${post.slug}`} aria-label={post.title}>
            <div className="blog-row-text">
              <h4 className="blog-row-title">{post.title}</h4>
              <p className="blog-row-excerpt">{firstSentence(post.excerpt)}</p>
              {Number.isFinite(post.reading_time_min) && (
                <span className="blog-series-time">{post.reading_time_min}분</span>
              )}
            </div>
            {post.thumbnail_url && (
              <div className="blog-row-thumb">
                <img
                  src={figureSrc(post.thumbnail_url, 456)}
                  alt=""
                  width={228}
                  height={128}
                  loading="lazy"
                  decoding="async"
                  onError={(e) => { e.currentTarget.parentElement!.style.display = 'none'; }}
                />
              </div>
            )}
          </a>
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

  // React Router does not act on a URL fragment, so anchors like
  // #geo-comparison-title land at the top until the target exists.
  useEffect(() => {
    let id = hash.slice(1);
    try { id = decodeURIComponent(id); } catch { /* Preserve a malformed fragment verbatim. */ }
    if (id) document.getElementById(id)?.scrollIntoView?.({ block: 'start' });
  }, [hash, current.status]);

  if (!series) {
    return (
      <div className="blog-container">
        <SEOHead title="Series not found | Jiphyeonjeon Blog" description="Series not found." canonical={`${SITE_URL}/blog`} robots="noindex,nofollow" />
        <BlogAppHeader />
        <main id="main" className="blog-content"><div className="blog-error">Series not found.</div></main>
      </div>
    );
  }

  const navTargets = [
    ['#series-reading-title', '추천 읽기 순서'] as const,
    comparison && ['#geo-comparison-title', '논문 선택 비교'] as const,
    comparison && ['#series-evidence-title', '상세 근거와 출처'] as const,
  ].filter(Boolean) as Array<readonly [string, string]>;

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
      <BlogAppHeader />
      <main id="main" className="blog-content">
        <header className="blog-header">
          <nav aria-label="breadcrumb"><a href="/blog">← 블로그로</a></nav>
          <h1 className="blog-title">{series.title}</h1>
          <p className="blog-subtitle">{firstSentence(series.description)}</p>
          {posts.length > 0 && (
            <p className="blog-series-meta">
              {catMeta && <span className="blog-row-cat" data-cat={catMeta}>{catMeta === 'engineering' ? 'Engineering' : 'Paper Review'}</span>}
              <span>{posts.length}편{total !== null ? ` · 약 ${total}분` : ''}</span>
            </p>
          )}
        </header>
        <section className="blog-series-start" aria-labelledby="series-start-title">
          <div className="blog-series-start-text">
            <p className="blog-series-kicker">
              여기서 시작하세요
              {first && Number.isFinite(first.reading_time_min) && (
                <span className="blog-series-start-time"> · {first.reading_time_min}분</span>
              )}
            </p>
            {first ? <>
              <h2 id="series-start-title"><a href={`/blog/${first.slug}`}>{first.title}</a></h2>
              <p className="blog-series-start-excerpt">{firstSentence(first.excerpt)}</p>
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
          </div>
          {first?.thumbnail_url && (
            <div className="blog-series-start-media">
              <img src={figureSrc(first.thumbnail_url, 456)} alt="" decoding="async" onError={(e) => { e.currentTarget.parentElement!.style.display = 'none'; }} />
            </div>
          )}
        </section>
        {comparison && (
          <nav className="blog-series-path" aria-labelledby="series-guide-title">
            <h2 id="series-guide-title">한눈에 보는 학습 경로</h2>
            <ol data-count={comparison.reading_guide.length}>{comparison.reading_guide.map((step, index) => {
              const members = step.slugs.filter((slug) => posts.some((post) => post.slug === slug));
              const minutes = totalMinutes(posts.filter((post) => members.includes(post.slug)));
              return <li key={step.title}>
                <a href={`#series-stage-${index + 1}`}>
                  <span className="blog-series-path-title">{step.title}</span>
                  {members.length > 0 && (
                    <span className="blog-series-path-meta">{members.length}편{minutes !== null ? ` · ${minutes}분` : ''}</span>
                  )}
                </a>
              </li>;
            })}</ol>
          </nav>
        )}
        {navTargets.length >= 2 && (
          <nav className="blog-series-nav" aria-label="시리즈 바로가기">
            {navTargets.map(([href, label]) => <a key={href} href={href}>{label}</a>)}
          </nav>
        )}
        <section className="blog-series-reading" aria-labelledby="series-reading-title">
          <h2 id="series-reading-title">추천 읽기 순서</h2>
          {!comparison && (
            <p className="blog-series-reading-intro">
              {series.description.includes('. ') ? series.description.split('. ').slice(1).join('. ') : ''}
            </p>
          )}
          {comparison ? comparison.reading_guide.map((step, index) => {
            const members = posts.filter((post) => step.slugs.includes(post.slug));
            const minutes = totalMinutes(members);
            return <section className="blog-series-stage" key={step.title} aria-labelledby={`series-stage-${index + 1}`}>
              <div className="blog-series-stage-heading">
                <h3 id={`series-stage-${index + 1}`}>{step.title}</h3>
                {members.length > 0 && <span className="blog-series-stage-meta">{members.length}편{minutes !== null ? ` · ${minutes}분` : ''}</span>}
              </div>
              <p className="blog-series-stage-description">{step.description}</p>
              {members.length > 0 ? readingList(members) : current.status === 'success' && <p>이 단계에는 아직 공개된 글이 없습니다.</p>}
            </section>;
          }) : posts.length > 0 && readingList(posts)}
        </section>
        {comparison && <SeriesComparison comparison={comparison} posts={posts} />}
        {comparison && <SeriesComparison comparison={comparison} posts={posts} detailed />}
      </main>
    </div>
  );
}

export default SeriesPage;
