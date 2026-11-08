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
  created_at?: string | null;
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

function firstSentence(text: string): string {
  const end = text.search(/[.!?](?=\s|$)/);
  return end === -1 ? text : text.slice(0, end + 1);
}

function publishedDate(createdAt?: string | null): { isoDate: string; label: string } | null {
  if (!createdAt) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$/.exec(createdAt);
  if (!match) return null;

  const [, yearText, monthText, dayText, hourText, minuteText, secondText, zone] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (month < 1 || month > 12 || day < 1 || day > daysInMonth[month - 1]) return null;
  if (hourText !== undefined) {
    if (Number(hourText) > 23 || Number(minuteText) > 59 || Number(secondText ?? 0) > 59) return null;
    if (zone && zone !== 'Z') {
      const [offsetHour, offsetMinute] = zone.slice(1).split(':').map(Number);
      if (offsetHour > 23 || offsetMinute > 59) return null;
    }
  }

  const isoDate = `${yearText}-${monthText}-${dayText}`;
  return { isoDate, label: `${yearText}.${monthText}.${dayText}` };
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
  const total = totalMinutes(posts);

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

  // React Router does not act on a URL fragment. Open the resources disclosure
  // before scrolling so guide, comparison and evidence targets can be reached.
  useEffect(() => {
    let id = hash.slice(1);
    try { id = decodeURIComponent(id); } catch { /* Preserve a malformed fragment verbatim. */ }
    if (id) {
      const target = document.getElementById(id);
      if (!target) return;
      const resources = target.closest<HTMLDetailsElement>('.blog-series-resources');
      if (resources) resources.open = true;
      target.scrollIntoView?.({ block: 'start' });
    }
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
          <p className="blog-series-kicker">SERIES</p>
          <h1 className="blog-title">{series.title}</h1>
          <p className="blog-subtitle">{firstSentence(series.description)}</p>
          {posts.length > 0 && (
            <p className="blog-series-meta">
              <span>{posts.length}편{total !== null ? ` · 약 ${total}분` : ''}</span>
            </p>
          )}
        </header>
        <aside className="blog-series-service" aria-label="집현전 서비스">
          <span className="blog-series-service-label">SERVICE</span>
          <p>논문 검색과 근거 확인을 집현전에서 이어 가세요.</p>
          <a href="/">집현전에서 논문 찾기 <span aria-hidden="true">→</span></a>
        </aside>
        <section className="blog-series-reading" aria-labelledby="series-reading-title">
          <h2 id="series-reading-title">추천 읽기 순서</h2>
          {current.status === 'loading' && <p role="status">시리즈 글을 불러오는 중입니다.</p>}
          {current.status === 'error' && <div className="blog-series-error">
            <p role="alert">시리즈 글을 불러오지 못했습니다. 다시 시도해 주세요.</p>
            <button type="button" onClick={() => { setRequest({ seriesId, status: 'loading', posts: [] }); setAttempt((value) => value + 1); }}>다시 시도</button>
          </div>}
          {current.status === 'success' && posts.length === 0 && <p role="status">아직 공개된 시리즈 글이 없습니다.</p>}
          {posts.length > 0 && (
            <ol className="blog-series-list">
              {posts.map((post, index) => {
                const category = post.category === 'paper-review' || post.category === 'engineering'
                  ? post.category
                  : null;
                const categoryLabel = category === 'paper-review' ? 'Paper Review' : category === 'engineering' ? 'Engineering' : null;
                const date = publishedDate(post.created_at);
                return (
                  <li key={post.slug}>
                    <span className="blog-series-pos" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
                    <a className="blog-row" href={`/blog/${post.slug}`} aria-label={post.title}>
                      <div className="blog-row-text">
                        <div className="blog-series-row-meta">
                          {categoryLabel && <span className="blog-row-cat" data-cat={category}>{categoryLabel}</span>}
                          {date && <time dateTime={date.isoDate}>{date.label}</time>}
                          {Number.isFinite(post.reading_time_min) && (
                            <span className="blog-series-time">{post.reading_time_min}분</span>
                          )}
                        </div>
                        <h3 className="blog-row-title">{post.title}</h3>
                        <p className="blog-row-excerpt">{post.excerpt}</p>
                      </div>
                      {post.thumbnail_url && (
                        <div className="blog-row-thumb">
                          <img
                            src={figureSrc(post.thumbnail_url, 456)}
                            alt=""
                            width={228}
                            height={128}
                            loading={index === 0 ? 'eager' : 'lazy'}
                            decoding="async"
                            onError={(e) => { e.currentTarget.parentElement!.style.display = 'none'; }}
                          />
                        </div>
                      )}
                    </a>
                  </li>
                );
              })}
            </ol>
          )}
        </section>
        <details className="blog-series-resources">
          <summary>{comparison ? '시리즈 소개 · 학습 경로와 논문 비교 · 근거 보기' : '시리즈 소개 더 보기'}</summary>
          <div className="blog-series-resources-content">
            {comparison && (
              <nav className="blog-series-resource-nav" aria-label="자료 바로가기">
                <a href="#series-guide-title">학습 경로</a>
                <a href="#geo-comparison-title">논문 선택 비교</a>
                <a href="#series-evidence-title">상세 근거와 출처</a>
              </nav>
            )}
            <section className="blog-series-about" aria-labelledby="series-about-title">
              <h2 id="series-about-title">시리즈 소개</h2>
              <p>{series.description}</p>
            </section>
            {comparison && <>
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
              {comparison.reading_guide.map((step, index) => {
                const members = posts.filter((post) => step.slugs.includes(post.slug));
                const minutes = totalMinutes(members);
                return <section className="blog-series-stage" key={step.title} aria-labelledby={`series-stage-${index + 1}`}>
                  <div className="blog-series-stage-heading">
                    <h3 id={`series-stage-${index + 1}`}>{step.title}</h3>
                    {members.length > 0 && <span className="blog-series-stage-meta">{members.length}편{minutes !== null ? ` · ${minutes}분` : ''}</span>}
                  </div>
                  <p className="blog-series-stage-description">{step.description}</p>
                  {members.length === 0 && current.status === 'success' && <p>이 단계에는 아직 공개된 글이 없습니다.</p>}
                </section>;
              })}
              <SeriesComparison comparison={comparison} posts={posts} />
              <SeriesComparison comparison={comparison} posts={posts} detailed />
            </>}
          </div>
        </details>
      </main>
    </div>
  );
}

export default SeriesPage;
