import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeRaw from 'rehype-raw';
import rehypeKatex from 'rehype-katex';
import './BlogPage.css';
import SEOHead from './SEOHead';
import ThemeToggle from './ThemeToggle';
import {
  SITE_URL,
  blogCanonical,
  blogPostingGraph,
  blogIndexGraph,
  detectLang,
  localeFor,
  OG_DEFAULT_IMAGE,
} from '../seo/structuredData';
import {
  fetchBlogPosts,
  fetchBlogPost,
  createBlogPost,
  updateBlogPost,
  deleteBlogPost,
} from '../api/client';

// ── Types ─────────────────────────────────────────────────────────────

interface BlogPost {
  id: string;
  slug: string;
  title: string;
  excerpt: string;
  content: string;
  author: string;
  tags: string[];
  category?: string;
  thumbnail_url?: string;
  reading_time_min: number;
  created_at: string;
  updated_at: string;
}

interface BlogPageProps {
  isAdmin: boolean;
  slug?: string;
  /** Set by the /blog/category/:category route to open the list pre-filtered. */
  initialCategory?: 'paper-review' | 'engineering';
}

type BlogView = 'list' | 'detail' | 'editor';

// ── Categories ────────────────────────────────────────────────────────

type CategoryKey = 'paper-review' | 'engineering';
type CategoryFilter = CategoryKey;
const DEFAULT_CATEGORY: CategoryKey = 'engineering';

const CATEGORY_META: Record<CategoryKey, { label: string; badge: string }> = {
  'paper-review': { label: 'Paper Reviews', badge: 'Paper Review' },
  engineering: { label: 'Engineering', badge: 'Engineering' },
};

const SEGMENTS: { key: CategoryFilter; label: string }[] = [
  { key: 'engineering', label: 'Engineering' },
  { key: 'paper-review', label: 'Paper Reviews' },
];

/** Coerce any stored/legacy value to a known category (defaults to engineering). */
function normalizeCategory(category?: string): CategoryKey {
  return category === 'paper-review' ? 'paper-review' : 'engineering';
}

// Drop a leading top-level "# " heading so the rendered body doesn't duplicate
// the post title <h1>. Mirrors routers/seo.py::_strip_leading_h1.
const LEADING_H1_RE = /^\s*#[ \t]+[^\n]*\n+/;
function stripLeadingH1(content: string): string {
  return content.replace(LEADING_H1_RE, '');
}

// Blog paper reviews have historically used LaTeX delimiters from source
// notes (\(...\) and \[...\]). remark-math/KaTeX expects dollar
// delimiters, while Markdown parsers treat the backslashes as escapes and can
// render broken text like `(\tilde A)` instead of math. Normalize before
// handing content to ReactMarkdown so both new and legacy posts render math.
function repairCorruptedLatexEscapes(content: string): string {
  // Repair JSON escape damage where LaTeX `\tilde` was stored as tab + `ilde`.
  return content.replace(/\u0009ilde/g, '\\tilde');
}

function normalizeDisplayMathFences(content: string): string {
  // remark-math parses display math most reliably when $$ fences are on their own lines.
  return content.replace(/\$\$([\s\S]*?)\$\$/g, (_match, expr: string) => `$$\n${expr.trim()}\n$$`);
}

function normalizeLatexDelimiters(content: string): string {
  return content
    .replace(/\\\[([\s\S]*?)\\\]/g, (_match, expr: string) => `$$${expr.trim()}$$`)
    .replace(/\\\(([^\n]*?)\\\)/g, (_match, expr: string) => `$${expr.trim()}$`);
}


function normalizeBlogMarkdown(content: string): string {
  return normalizeDisplayMathFences(normalizeLatexDelimiters(stripLeadingH1(repairCorruptedLatexEscapes(content))));
}

function categoryHref(key: CategoryFilter): string {
  return key === DEFAULT_CATEGORY ? '/blog' : `/blog/category/${key}`;
}

function CategoryBadge({ category }: { category?: string }) {
  const key = normalizeCategory(category);
  return (
    <span className={`blog-cat-badge blog-cat-${key}`}>
      {key === 'paper-review' ? (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="11" height="11" aria-hidden="true">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="11" height="11" aria-hidden="true">
          <polyline points="16 18 22 12 16 6" />
          <polyline points="8 6 2 12 8 18" />
        </svg>
      )}
      {CATEGORY_META[key].badge}
    </span>
  );
}

/** Leading icon for a sidebar category item (color set via CSS per data-cat). */
function sidebarIcon(key: CategoryFilter) {
  if (key === 'paper-review') {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="15" height="15" aria-hidden="true">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
      </svg>
    );
  }
  if (key === 'engineering') {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="15" height="15" aria-hidden="true">
        <polyline points="16 18 22 12 16 6" />
        <polyline points="8 6 2 12 8 18" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="15" height="15" aria-hidden="true">
      <line x1="8" y1="6" x2="21" y2="6" />
      <line x1="8" y1="12" x2="21" y2="12" />
      <line x1="8" y1="18" x2="21" y2="18" />
      <line x1="3" y1="6" x2="3.01" y2="6" />
      <line x1="3" y1="12" x2="3.01" y2="12" />
      <line x1="3" y1="18" x2="3.01" y2="18" />
    </svg>
  );
}

// renderMarkdown replaced by ReactMarkdown component (XSS-safe)

// ── Helpers ───────────────────────────────────────────────────────────

const BLOG_TITLE = 'Jiphyeonjeon Blog - Paper Research Notes';
const BLOG_DESCRIPTION = 'Research writeups, experiments, and product notes from Jiphyeonjeon.';

function formatDate(isoString: string): string {
  try {
    return new Date(isoString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  } catch {
    return isoString;
  }
}

function buildSlug(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .slice(0, 80);
}

function estimateReadingTime(content: string): number {
  const words = content.trim().split(/\s+/).length;
  return Math.max(1, Math.round(words / 200));
}

function getErrorMessage(err: unknown, fallback: string): string {
  const maybe = err as { response?: { data?: { detail?: string } }; message?: string };
  return maybe.response?.data?.detail ?? maybe.message ?? fallback;
}

// ── Loading Skeleton ──────────────────────────────────────────────────

function BlogSkeletonCard() {
  return (
    <div className="blog-skeleton-card">
      <div className="blog-skeleton-separator" />
      <div className="blog-skeleton-body">
        <div className="blog-skeleton-line short" />
        <div className="blog-skeleton-line title" />
        <div className="blog-skeleton-line full" />
        <div className="blog-skeleton-line excerpt" />
        <div className="blog-skeleton-line short" />
      </div>
    </div>
  );
}

// ── Empty editor form state ───────────────────────────────────────────

interface EditorForm {
  title: string;
  excerpt: string;
  content: string;
  author: string;
  tags: string;
  category: CategoryKey;
  thumbnail_url: string;
}

const EMPTY_FORM: EditorForm = {
  title: '',
  excerpt: '',
  content: '',
  author: '',
  tags: '',
  category: 'engineering',
  thumbnail_url: '',
};

// ── Main Component ────────────────────────────────────────────────────

function BlogPage({ isAdmin, slug, initialCategory }: BlogPageProps) {
  const navigate = useNavigate();

  const [view, setView] = useState<BlogView>('list');
  const [posts, setPosts] = useState<BlogPost[]>([]);
  const [activeCategory, setActiveCategory] = useState<CategoryFilter>(initialCategory ?? DEFAULT_CATEGORY);
  const [selectedPost, setSelectedPost] = useState<BlogPost | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Editor state (admin only)
  const [editingPost, setEditingPost] = useState<BlogPost | null>(null);
  const [form, setForm] = useState<EditorForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // ── Data fetching ──────────────────────────────────────────────────

  const loadPosts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Fetch the full set (both categories) so the segmented control can
      // show accurate counts and switch tabs client-side without refetching.
      const response = await fetchBlogPosts(undefined, undefined, 1, 100);
      setPosts((response.data?.posts ?? response.data) as BlogPost[]);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load posts.'));
      // Fall back to empty list so UI is usable
      setPosts([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // ── Category filtering (client-side) ───────────────────────────────

  const categoryCounts = useMemo(() => {
    const counts: Record<CategoryFilter, number> = {
      'paper-review': 0,
      engineering: 0,
    };
    for (const p of posts) counts[normalizeCategory(p.category)] += 1;
    return counts;
  }, [posts]);

  const visiblePosts = useMemo(
    () => posts.filter((p) => normalizeCategory(p.category) === activeCategory),
    [posts, activeCategory],
  );

  // Keep the active filter in sync with the /blog/category/:category route.
  // Adjust-during-render (React's recommended pattern) rather than an effect,
  // so navigating between category hubs without a remount still re-filters.
  const [lastInitialCategory, setLastInitialCategory] = useState(initialCategory);
  if (initialCategory !== lastInitialCategory) {
    setLastInitialCategory(initialCategory);
    setActiveCategory(initialCategory ?? DEFAULT_CATEGORY);
  }

  useEffect(() => {
    if (slug) return;
    queueMicrotask(() => {
      void loadPosts();
    });
  }, [loadPosts, slug]);

  useEffect(() => {
    if (!slug) return;

    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      setLoading(true);
      setError(null);
      setSelectedPost(null);
      setView('detail');

      fetchBlogPost(slug)
        .then((response) => {
          if (cancelled) return;
          setSelectedPost(response.data as BlogPost);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setError(getErrorMessage(err, 'Failed to load post.'));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    });

    return () => {
      cancelled = true;
    };
  }, [slug]);

  // ── Detail view ────────────────────────────────────────────────────

  const openPost = async (post: BlogPost) => {
    setError(null);
    try {
      const response = await fetchBlogPost(post.slug);
      const full = response.data as BlogPost;
      setSelectedPost(full);
    } catch {
      // Use the list item if detail fetch fails
      setSelectedPost(post);
    }
    setView('detail');
    if (!slug) {
      navigate(`/blog/${post.slug}`);
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const closeDetail = () => {
    setView('list');
    setSelectedPost(null);
    if (slug) {
      navigate('/blog');
    }
  };

  // ── Admin actions ──────────────────────────────────────────────────

  const openNewEditor = () => {
    setEditingPost(null);
    setForm(EMPTY_FORM);
    setSaveError(null);
    setView('editor');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const openEditEditor = (post: BlogPost, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingPost(post);
    setForm({
      title: post.title,
      excerpt: post.excerpt,
      content: post.content,
      author: post.author,
      tags: post.tags.join(', '),
      category: normalizeCategory(post.category),
      thumbnail_url: post.thumbnail_url ?? '',
    });
    setSaveError(null);
    setView('editor');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleDelete = async (post: BlogPost, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(`"${post.title}" 포스트를 삭제하시겠습니까?`)) return;
    try {
      await deleteBlogPost(post.id);
      setPosts((prev) => prev.filter((p) => p.id !== post.id));
      if (selectedPost?.id === post.id) {
        setSelectedPost(null);
        setView('list');
      }
    } catch (err: unknown) {
      alert(getErrorMessage(err, '삭제 중 오류가 발생했습니다.'));
    }
  };

  const handleSave = async () => {
    if (!form.title.trim()) { setSaveError('제목을 입력해주세요.'); return; }
    if (!form.content.trim()) { setSaveError('본문을 입력해주세요.'); return; }

    setSaving(true);
    setSaveError(null);

    const payload = {
      title: form.title.trim(),
      slug: buildSlug(form.title),
      excerpt: form.excerpt.trim() || form.content.trim().slice(0, 160),
      content: form.content.trim(),
      author: form.author.trim() || '집현전 팀',
      tags: form.tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
      category: form.category,
      thumbnail_url: form.thumbnail_url.trim() || undefined,
      reading_time_min: estimateReadingTime(form.content),
    };

    try {
      if (editingPost) {
        const response = await updateBlogPost(editingPost.id, payload);
        const updated = response.data as BlogPost;
        setPosts((prev) => prev.map((p) => (p.id === editingPost.id ? updated : p)));
        setSelectedPost(updated);
        setView('detail');
      } else {
        const response = await createBlogPost(payload);
        const created = response.data as BlogPost;
        setPosts((prev) => [created, ...prev]);
        setSelectedPost(created);
        setView('detail');
      }
      // Refresh tags in the background
    } catch (err: unknown) {
      setSaveError(getErrorMessage(err, '저장 중 오류가 발생했습니다.'));
    } finally {
      setSaving(false);
    }
  };

  // ── Header shared by all views ─────────────────────────────────────

  const renderHeader = () => (
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
              loading="eager"
              fetchPriority="high"
              onError={(e) => { e.currentTarget.style.display = 'none'; }}
            />
          </picture>
          <span className="blog-brand-name">Jiphyeonjeon</span>
        </div>
        <div className="blog-header-actions">
          <button className="blog-nav-btn blog-nav-btn-active">Blog</button>
          <button className="blog-nav-btn" onClick={() => navigate('/')}>Search</button>
          <button className="blog-nav-btn" onClick={() => navigate('/mypage')}>My Page</button>
          <ThemeToggle />
        </div>
      </div>
    </div>
  );

  // ── Category sidebar (list view) ────────────────────────────────────

  const renderSidebar = () => (
    <aside className="blog-sidebar">
      <nav
        className="blog-side-nav"
        role="tablist"
        aria-orientation="vertical"
        aria-label="Filter posts by category"
      >
        <div className="blog-side-label">Categories</div>
        {SEGMENTS.map((seg) => (
          <a
            key={seg.key}
            href={categoryHref(seg.key)}
            role="tab"
            data-cat={seg.key}
            aria-selected={activeCategory === seg.key}
            className={`blog-side-item ${activeCategory === seg.key ? 'active' : ''}`}
            onClick={(e) => {
              e.preventDefault();
              setActiveCategory(seg.key);
              navigate(categoryHref(seg.key));
            }}
          >
            <span className="blog-side-icon">{sidebarIcon(seg.key)}</span>
            <span className="blog-side-text">{seg.label}</span>
            <span className="blog-side-count">{categoryCounts[seg.key]}</span>
          </a>
        ))}
      </nav>
    </aside>
  );

  // ── List view ──────────────────────────────────────────────────────

  const renderList = () => (
    <>
      <header className="blog-header">
        <div className="blog-title-row">
          <h1 className="blog-page-title">Blog</h1>
          {isAdmin && (
            <div className="blog-admin-bar">
              <button className="blog-new-post-btn" onClick={openNewEditor}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                  <line x1="12" y1="5" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
                New Post
              </button>
            </div>
          )}
        </div>
        <p className="blog-page-subtitle">Research writeups, experiments, and product notes.</p>
      </header>

      {error && <div className="blog-error">{error}</div>}

      {loading ? (
        <div className="blog-skeleton-grid">
          {[0, 1, 2, 3].map((i) => <BlogSkeletonCard key={i} />)}
        </div>
      ) : posts.length === 0 ? (
        <div className="blog-empty">
          <div className="blog-empty-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="48" height="48" style={{ opacity: 0.3 }}>
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10 9 9 9 8 9" />
            </svg>
          </div>
          <div className="blog-empty-title">
            게시물이 없습니다
          </div>
          <div className="blog-empty-subtitle">
            {isAdmin ? '첫 번째 블로그 포스트를 작성해보세요.' : '곧 새로운 글이 올라올 예정입니다.'}
          </div>
        </div>
      ) : (
        <div className="blog-layout">
          {renderSidebar()}
          <div className="blog-main">
            {visiblePosts.length === 0 ? (
              <div className="blog-empty">
                <div className="blog-empty-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="48" height="48" style={{ opacity: 0.3 }}>
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                </div>
                <div className="blog-empty-title">
                  {activeCategory === 'paper-review' ? '논문 리뷰 글이 아직 없습니다' : '개발 노트가 아직 없습니다'}
                </div>
                <div className="blog-empty-subtitle">
                  {activeCategory === 'paper-review'
                    ? '딥리뷰를 블로그 초안으로 정리하면 이곳에 모입니다.'
                    : '집현전 개발·제품 이야기가 곧 올라올 예정입니다.'}
                </div>
              </div>
            ) : (
              <div className="blog-grid">
                {visiblePosts.map((post, idx) => (
            <a
              key={post.id}
              className="blog-card"
              onClick={(e) => { e.preventDefault(); openPost(post); }}
              href={`/blog/${post.slug}`}
              role="article"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && openPost(post)}
              aria-label={post.title}
            >
              {/* Separator — shown on all cards except the first */}
              {idx > 0 && <div className="blog-card-separator" aria-hidden="true" />}

              <div className="blog-card-inner">

                {/* Row 1: Category · Date · Reading time */}
                <div className="blog-card-meta">
                  <CategoryBadge category={post.category} />
                  <time className="blog-card-date">{formatDate(post.created_at)}</time>
                  <span className="blog-card-dot" aria-hidden="true">·</span>
                  <span className="blog-card-readtime">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12" aria-hidden="true">
                      <circle cx="12" cy="12" r="10" />
                      <polyline points="12 6 12 12 16 14" />
                    </svg>
                    {post.reading_time_min} min read
                  </span>
                </div>

                {/* Row 2: Title + arrow icon */}
                <div className="blog-card-title-row">
                  <h2 className="blog-card-title">{post.title}</h2>
                  <svg
                    className="blog-card-arrow"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    width="20"
                    height="20"
                    aria-hidden="true"
                  >
                    <line x1="7" y1="17" x2="17" y2="7" />
                    <polyline points="7 7 17 7 17 17" />
                  </svg>
                </div>

                {/* Row 3: Excerpt */}
                <p className="blog-card-excerpt">{post.excerpt}</p>

                {/* Row 4: Author · Tags */}
                <div className="blog-card-footer">
                  <span className="blog-card-author-label">
                    <span className="blog-card-author-name">{post.author}</span>
                  </span>
                  {post.tags.length > 0 && (
                    <>
                      <span className="blog-card-dot" aria-hidden="true">·</span>
                      {post.tags.slice(0, 5).map((tag) => (
                        <span key={tag} className="blog-tag">{tag}</span>
                      ))}
                    </>
                  )}
                </div>

                {isAdmin && (
                  <div
                    className="blog-card-admin-actions"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      className="blog-card-edit-btn"
                      onClick={(e) => openEditEditor(post, e)}
                      aria-label="Edit post"
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                      </svg>
                      Edit
                    </button>
                    <button
                      className="blog-card-delete-btn"
                      onClick={(e) => handleDelete(post, e)}
                      aria-label="Delete post"
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                        <polyline points="3 6 5 6 21 6" />
                        <path d="M19 6l-1 14H6L5 6" />
                        <path d="M10 11v6M14 11v6" />
                        <path d="M9 6V4h6v2" />
                      </svg>
                      Delete
                    </button>
                  </div>
                )}

              </div>
            </a>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );

  // ── Detail view ────────────────────────────────────────────────────

  const renderDetail = () => {
    if (!selectedPost) {
      return (
        <div className="blog-detail">
          <button className="blog-detail-back" onClick={closeDetail}>
            Back to Blog
          </button>
          {loading ? (
            <div className="blog-empty-title">Loading post...</div>
          ) : (
            <div className="blog-error">{error ?? 'Post not found.'}</div>
          )}
        </div>
      );
    }

    return (
      <div className="blog-detail">
        <button className="blog-detail-back" onClick={closeDetail}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
            <line x1="19" y1="12" x2="5" y2="12" />
            <polyline points="12 19 5 12 12 5" />
          </svg>
          Back to Blog
        </button>

        <div className="blog-detail-category">
          <CategoryBadge category={selectedPost.category} />
        </div>

        {selectedPost.tags.length > 0 && (
          <div className="blog-detail-tags">
            {selectedPost.tags.map((tag) => (
              <span key={tag} className="blog-tag">{tag}</span>
            ))}
          </div>
        )}

        <h1 className="blog-detail-title">{selectedPost.title}</h1>

        <div className="blog-detail-meta">
          <span className="blog-detail-author">{selectedPost.author}</span>
          <span className="blog-card-dot" aria-hidden="true" />
          <span>{formatDate(selectedPost.created_at)}</span>
          <span className="blog-card-dot" aria-hidden="true" />
          <span>{selectedPost.reading_time_min} min read</span>
        </div>

        <div className="blog-detail-content">
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[rehypeRaw, rehypeKatex]}
          >
            {normalizeBlogMarkdown(selectedPost.content)}
          </ReactMarkdown>
        </div>

        {isAdmin && (
          <div className="blog-detail-admin-bar">
            <button
              className="blog-card-edit-btn"
              onClick={(e) => openEditEditor(selectedPost, e)}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
              Edit Post
            </button>
            <button
              className="blog-card-delete-btn"
              onClick={(e) => handleDelete(selectedPost, e)}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13">
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6l-1 14H6L5 6" />
                <path d="M10 11v6M14 11v6" />
                <path d="M9 6V4h6v2" />
              </svg>
              Delete Post
            </button>
          </div>
        )}
      </div>
    );
  };

  // ── Editor view (admin) ────────────────────────────────────────────

  const renderEditor = () => (
    <div className="blog-editor">
      <div className="blog-editor-header">
        <span className="blog-editor-title-text">
          {editingPost ? 'Edit Post' : 'New Post'}
        </span>
        <div className="blog-editor-actions">
          <button
            className="blog-editor-cancel-btn"
            onClick={() => {
              if (editingPost && selectedPost) {
                setView('detail');
              } else {
                setView('list');
              }
            }}
          >
            Cancel
          </button>
          <button
            className="blog-editor-save-btn"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? (
              <>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14" style={{ animation: 'spin 1s linear infinite' }}>
                  <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                </svg>
                Saving...
              </>
            ) : (
              <>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                  <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                  <polyline points="17 21 17 13 7 13 7 21" />
                  <polyline points="7 3 7 8 15 8" />
                </svg>
                Save Post
              </>
            )}
          </button>
        </div>
      </div>

      {saveError && <div className="blog-error">{saveError}</div>}

      <div className="blog-editor-form">
        <div className="blog-editor-field">
          <label className="blog-editor-label" htmlFor="blog-field-title">Title</label>
          <input
            id="blog-field-title"
            className="blog-editor-input"
            type="text"
            placeholder="Post title..."
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
          />
        </div>

        <div className="blog-editor-field">
          <label className="blog-editor-label">Category</label>
          <div className="blog-editor-segments" role="radiogroup" aria-label="Post category">
            {(Object.keys(CATEGORY_META) as CategoryKey[]).map((key) => (
              <button
                key={key}
                type="button"
                role="radio"
                data-cat={key}
                aria-checked={form.category === key}
                className={`blog-editor-segment ${form.category === key ? 'active' : ''}`}
                onClick={() => setForm((f) => ({ ...f, category: key }))}
              >
                {CATEGORY_META[key].badge}
              </button>
            ))}
          </div>
          <span className="blog-editor-hint">
            'Paper Review'는 논문 리뷰 섹션, 'Engineering'은 개발·제품 노트 섹션으로 묶입니다.
          </span>
        </div>

        <div className="blog-editor-field">
          <label className="blog-editor-label" htmlFor="blog-field-excerpt">Excerpt</label>
          <input
            id="blog-field-excerpt"
            className="blog-editor-input"
            type="text"
            placeholder="Short description shown in the card list..."
            value={form.excerpt}
            onChange={(e) => setForm((f) => ({ ...f, excerpt: e.target.value }))}
          />
        </div>

        <div className="blog-editor-field">
          <label className="blog-editor-label" htmlFor="blog-field-author">Author</label>
          <input
            id="blog-field-author"
            className="blog-editor-input"
            type="text"
            placeholder="Author name (default: 집현전 팀)"
            value={form.author}
            onChange={(e) => setForm((f) => ({ ...f, author: e.target.value }))}
          />
        </div>

        <div className="blog-editor-field">
          <label className="blog-editor-label" htmlFor="blog-field-tags">Tags</label>
          <input
            id="blog-field-tags"
            className="blog-editor-input"
            type="text"
            placeholder="Comma-separated tags: AI, Research, NLP"
            value={form.tags}
            onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))}
          />
        </div>

        <div className="blog-editor-field">
          <label className="blog-editor-label" htmlFor="blog-field-thumb">Thumbnail URL</label>
          <input
            id="blog-field-thumb"
            className="blog-editor-input"
            type="text"
            placeholder="https://... (leave blank for gradient placeholder)"
            value={form.thumbnail_url}
            onChange={(e) => setForm((f) => ({ ...f, thumbnail_url: e.target.value }))}
          />
        </div>

        <div className="blog-editor-field">
          <label className="blog-editor-label" htmlFor="blog-field-content">Content (Markdown)</label>
          <textarea
            id="blog-field-content"
            className="blog-editor-textarea"
            placeholder={`# Section Title\n\nWrite your post content in Markdown...\n\n## Sub-section\n\nParagraph text here.`}
            value={form.content}
            onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
          />
          <span className="blog-editor-hint">
            Supports: # headings, **bold**, *italic*, `code`, - lists, 1. ordered lists, {'>'} blockquote, ``` code blocks
          </span>
        </div>
      </div>
    </div>
  );

  // ── Render ─────────────────────────────────────────────────────────

  const seoPost = view === 'detail' ? selectedPost : null;
  const categoryView = view === 'list';
  const categoryLabel = categoryView ? CATEGORY_META[activeCategory].label : '';
  const seoTitle = seoPost
    ? `${seoPost.title} | Jiphyeonjeon Blog`
    : categoryView
      ? `${categoryLabel} | Jiphyeonjeon Blog`
      : BLOG_TITLE;
  const seoDescription = seoPost?.excerpt || BLOG_DESCRIPTION;
  const hasSlugError = Boolean(slug && view === 'detail' && !loading && !seoPost);
  const seoCanonical = seoPost
    ? blogCanonical(seoPost.slug)
    : initialCategory
      ? `${SITE_URL}/blog/category/${activeCategory}`
      : blogCanonical(hasSlugError ? undefined : slug);
  const seoLocale = seoPost
    ? localeFor(detectLang(`${seoPost.title} ${seoPost.content || seoPost.excerpt || ''}`))
    : undefined;

  return (
    <div className="blog-container">
      <SEOHead
        title={seoTitle}
        description={seoDescription}
        canonical={seoCanonical}
        robots={hasSlugError ? 'noindex,nofollow' : undefined}
        type={seoPost ? 'article' : 'website'}
        image={seoPost ? seoPost.thumbnail_url || OG_DEFAULT_IMAGE : undefined}
        publishedTime={seoPost ? seoPost.created_at : undefined}
        modifiedTime={seoPost ? seoPost.updated_at || seoPost.created_at : undefined}
        locale={seoLocale}
        jsonLd={seoPost ? blogPostingGraph(seoPost) : blogIndexGraph(posts)}
      />
      {renderHeader()}
      <div className={`blog-content${view === 'list' ? ' blog-content--list' : ''}`}>
        {view === 'list' && renderList()}
        {view === 'detail' && renderDetail()}
        {view === 'editor' && isAdmin && renderEditor()}
      </div>
    </div>
  );
}

export default BlogPage;
