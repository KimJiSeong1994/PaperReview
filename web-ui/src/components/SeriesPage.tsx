import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import './BlogPage.css';
import SEOHead from './SEOHead';
import BlogAppHeader from './BlogAppHeader';
import { BLOG_SERIES } from '../seo/series';
import { SITE_URL, seriesGraph, detectLang, localeFor } from '../seo/structuredData';
import { fetchBlogPosts } from '../api/client';

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

function SeriesPage({ seriesId }: SeriesPageProps) {
  return <SeriesPageContent key={seriesId} seriesId={seriesId} />;
}

function SeriesPageContent({ seriesId }: SeriesPageProps) {
  const { hash } = useLocation();
  const series = BLOG_SERIES[seriesId];
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

  // React Router does not scroll to fragments when navigating within the SPA.
  useEffect(() => {
    let id = hash.slice(1);
    try { id = decodeURIComponent(id); } catch { /* Preserve a malformed fragment verbatim. */ }
    if (id) {
      const target = document.getElementById(id);
      target?.scrollIntoView?.({ block: 'start' });
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
      </main>
    </div>
  );
}

export default SeriesPage;
