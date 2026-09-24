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

const AXIS_LABELS: Record<GeoComparisonAxis, string> = {
  retrieval_or_representation_unit: '검색·표현 단위',
  graph_construction: '그래프 구성',
  evaluation_context: '평가 조건',
  traceability: '근거 추적',
  cost: '비용',
  failure_conditions: '실패 조건',
};

function SeriesComparison({
  comparison,
  posts,
}: {
  comparison: GeoComparisonHub;
  posts: SeriesPost[];
}) {
  const titles = new Map(posts.map((post) => [post.slug, post.title]));
  return (
    <section className="geo-comparison" aria-labelledby="geo-comparison-title">
      <h2 id="geo-comparison-title">논문 선택 비교</h2>
      <p className="geo-comparison-question">{comparison.question}</p>
      <div className="geo-comparison-scroll" tabIndex={0}>
        <table>
          <caption>여섯 기준으로 비교한 논문 선택표</caption>
          <thead>
            <tr>
              <th scope="col">비교 기준</th>
              {comparison.entries.map((entry) => (
                <th scope="col" key={entry.slug}>
                  <a href={`/blog/${entry.slug}`}>{titles.get(entry.slug) ?? entry.slug}</a>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {comparison.axes.map((axis) => (
              <tr key={axis}>
                <th scope="row">{AXIS_LABELS[axis]}</th>
                {comparison.entries.map((entry) => {
                  const cell = entry.values[axis];
                  let stateLabel = '';
                  if (cell.state === 'unknown') {
                    stateLabel = '미확인: ';
                  } else if (cell.state === 'not_applicable') {
                    stateLabel = '해당 없음: ';
                  }
                  return (
                    <td key={entry.slug} data-state={cell.state}>
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
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="geo-comparison-limits"><strong>해석 한계:</strong> {comparison.limits}</p>
      <p className="geo-comparison-source-note">{comparison.source_note}</p>
    </section>
  );
}

function SeriesPage({ seriesId }: SeriesPageProps) {
  const navigate = useNavigate();
  const series = BLOG_SERIES[seriesId];
  const comparison = GEO_COMPARISONS[seriesId as keyof typeof GEO_COMPARISONS];
  const [posts, setPosts] = useState<SeriesPost[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!series) return;
    let cancelled = false;
    fetchBlogPosts(undefined, undefined, 1, 100)
      .then((response) => {
        if (cancelled) return;
        const all = (response.data as { posts: SeriesPost[] }).posts ?? [];
        const bySlug = new Map(all.map((p) => [p.slug, p]));
        setPosts(series.slugs.flatMap((slug) => bySlug.get(slug) ?? []));
      })
      .catch(() => {
        /* keep the static series shell; links still work via SSR pages */
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [series]);

  if (!series) {
    return (
      <div className="blog-container">
        <SEOHead
          title="Series not found | Jiphyeonjeon Blog"
          description="Series not found."
          canonical={`${SITE_URL}/blog`}
          robots="noindex,nofollow"
        />
        <div className="blog-content">
          <div className="blog-error">Series not found.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="blog-container">
      <SEOHead
        title={`${series.title} | Jiphyeonjeon Blog`}
        description={series.description}
        canonical={`${SITE_URL}/blog/series/${seriesId}`}
        locale={localeFor(detectLang(series.title + series.description))}
        jsonLd={seriesGraph(seriesId, posts)}
      />
      <div className="blog-content">
        <header className="blog-header">
          <nav aria-label="breadcrumb">
            <a
              href="/blog"
              onClick={(e) => {
                e.preventDefault();
                navigate('/blog');
              }}
            >
              Blog
            </a>
          </nav>
          <h1 className="blog-title">{series.title}</h1>
          <p className="blog-subtitle">{series.description}</p>
        </header>
        {comparison && <SeriesComparison comparison={comparison} posts={posts} />}
        {loading ? (
          <div className="blog-empty-title">Loading series...</div>
        ) : (
          <ol className="blog-series-list">
            {posts.map((post, i) => (
              <li key={post.slug}>
                <a
                  href={`/blog/${post.slug}`}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(`/blog/${post.slug}`);
                  }}
                >
                  <span className="blog-series-pos">{i + 1}</span>
                  <span className="blog-series-item-title">{post.title}</span>
                </a>
                <p className="blog-series-item-excerpt">{post.excerpt}</p>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

export default SeriesPage;
