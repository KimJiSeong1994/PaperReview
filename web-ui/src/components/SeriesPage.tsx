import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './BlogPage.css';
import SEOHead from './SEOHead';
import { BLOG_SERIES } from '../seo/series';
import { SITE_URL, seriesGraph, detectLang, localeFor } from '../seo/structuredData';
import { fetchBlogPosts } from '../api/client';

interface SeriesPost {
  slug: string;
  title: string;
  excerpt: string;
  reading_time_min: number;
}

interface SeriesPageProps {
  seriesId: string;
}

function SeriesPage({ seriesId }: SeriesPageProps) {
  const navigate = useNavigate();
  const series = BLOG_SERIES[seriesId];
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
