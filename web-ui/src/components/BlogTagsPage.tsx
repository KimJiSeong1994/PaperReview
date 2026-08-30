import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import './BlogPage.css';
import './BlogTagsPage.css';
import SEOHead from './SEOHead';
import ThemeToggle from './ThemeToggle';
import { SITE_URL } from '../seo/structuredData';
import { fetchBlogTags } from '../api/client';

interface TagCount {
  tag: string;
  count: number;
}

const PAGE_SIZE = 60;
const TAGS_TITLE = 'Tags | Jiphyeonjeon Blog';
const TAGS_DESCRIPTION = '집현전 블로그의 모든 태그를 한곳에서 모아봅니다. 관심 있는 주제를 골라 관련 글을 찾아보세요.';

function BlogTagsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  // A junk or out-of-range ?page= still requests that page: the API answers with
  // an empty list, which renders the empty state rather than crashing.
  const page = Math.max(1, Number(searchParams.get('page')) || 1);

  const [tags, setTags] = useState<TagCount[]>([]);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // `cancelled` drops a stale response that lands after a newer page request.
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchBlogTags(page, PAGE_SIZE, 'name')
      .then((response) => {
        if (cancelled) return;
        setTags((response.data?.tags ?? []) as TagCount[]);
        setPages(response.data?.pages ?? 1);
      })
      .catch(() => {
        if (cancelled) return;
        setTags([]);
        setError('태그를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [page]);

  const goToPage = (next: number) => {
    setSearchParams(next <= 1 ? {} : { page: String(next) });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  // Page 2+ canonicalises to itself, not to page 1: each page lists a different
  // slice of tags, so collapsing them would drop pages 2..n from the index.
  const canonical = page > 1 ? `${SITE_URL}/blog/tags?page=${page}` : `${SITE_URL}/blog/tags`;

  return (
    <div className="blog-container">
      <SEOHead title={TAGS_TITLE} description={TAGS_DESCRIPTION} canonical={canonical} />

      {/* Minimal copy of BlogPage's header: that one is a closure over the blog's
          view/search state, so reusing it would mean refactoring BlogPage. */}
      <div className="blog-app-header">
        <div className="blog-header-nav">
          <div className="blog-logo" onClick={() => navigate('/')}>
            <picture>
              <source srcSet="/Jiphyeonjeon_llama.webp" type="image/webp" />
              <img
                src="/Jiphyeonjeon_llama.png"
                alt="Jiphyeonjeon"
                className="blog-logo-icon"
                width={128}
                height={128}
                onError={(e) => { e.currentTarget.style.display = 'none'; }}
              />
            </picture>
            <span className="blog-brand-name">Jiphyeonjeon</span>
          </div>
          <div className="blog-header-actions">
            <button className="blog-nav-btn blog-nav-btn-active" onClick={() => navigate('/blog')}>Blog</button>
            <button className="blog-nav-btn" onClick={() => navigate('/')}>Search</button>
            <button className="blog-nav-btn" onClick={() => navigate('/mypage')}>My Page</button>
            <ThemeToggle />
          </div>
        </div>
      </div>

      <div className="blog-content">
        <header className="blog-tags-header">
          <h1 className="blog-tags-title">Tags</h1>
          <p className="blog-tags-subtitle">집현전의 모든 글을 태그로 찾아볼 수 있습니다.</p>
        </header>

        {error && <div className="blog-error">{error}</div>}

        {loading ? (
          <div className="blog-tags-skeleton" aria-hidden="true">
            {Array.from({ length: 24 }, (_, i) => (
              <span key={i} className="blog-skeleton-line blog-tags-skeleton-chip" />
            ))}
          </div>
        ) : tags.length === 0 ? (
          !error && (
            <div className="blog-empty">
              <div className="blog-empty-title">태그가 없습니다</div>
              <div className="blog-empty-subtitle">글이 등록되면 이곳에 태그가 모입니다.</div>
            </div>
          )
        ) : (
          <nav className="blog-tags-nav" aria-label="태그 목록">
            <ul className="blog-tags-list">
              {tags.map((t) => (
                <li key={t.tag}>
                  <Link className="blog-tag-chip" to={`/blog?tag=${encodeURIComponent(t.tag)}`}>
                    {t.tag}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        )}

        {!loading && pages > 1 && (
          <nav className="blog-tags-pager" aria-label="페이지">
            <button
              type="button"
              className="blog-tags-page-btn"
              disabled={page <= 1}
              onClick={() => goToPage(page - 1)}
            >
              이전
            </button>
            {/* ponytail: every page number is rendered (4 pages today); add a
                windowed range if the tag index ever grows past ~10 pages. */}
            {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
              <button
                key={n}
                type="button"
                className={`blog-tags-page-btn${n === page ? ' active' : ''}`}
                aria-current={n === page ? 'page' : undefined}
                onClick={() => goToPage(n)}
              >
                {n}
              </button>
            ))}
            <button
              type="button"
              className="blog-tags-page-btn"
              disabled={page >= pages}
              onClick={() => goToPage(page + 1)}
            >
              다음
            </button>
          </nav>
        )}
      </div>
    </div>
  );
}

export default BlogTagsPage;
