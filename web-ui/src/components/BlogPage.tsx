import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import './BlogPage.css';
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
  thumbnail_url?: string;
  reading_time_min: number;
  created_at: string;
  updated_at: string;
}

interface BlogPageProps {
  isAdmin: boolean;
}

type BlogView = 'list' | 'detail' | 'editor';

// ── Simple Markdown Renderer ─────────────────────────────────────────

function renderMarkdown(markdown: string): string {
  const lines = markdown.split('\n');
  const html: string[] = [];
  let inList = false;
  let inOrderedList = false;
  let inCodeBlock = false;
  let inBlockquote = false;
  let inHtmlBlock = 0; // nested HTML/SVG depth counter

  const closeOpenBlocks = () => {
    if (inList) {
      html.push('</ul>');
      inList = false;
    }
    if (inOrderedList) {
      html.push('</ol>');
      inOrderedList = false;
    }
    if (inBlockquote) {
      html.push('</blockquote>');
      inBlockquote = false;
    }
  };

  const processInline = (text: string): string => {
    return text
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+)\*/g, '<em>$1</em>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Fenced code block toggle
    if (line.startsWith('```')) {
      if (inCodeBlock) {
        html.push('</code></pre>');
        inCodeBlock = false;
      } else {
        closeOpenBlocks();
        const lang = line.slice(3).trim();
        html.push(`<pre><code${lang ? ` class="language-${lang}"` : ''}>`);
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      html.push(
        line
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;'),
      );
      continue;
    }

    // Headings
    if (/^#{1}\s/.test(line)) {
      closeOpenBlocks();
      html.push(`<h2>${processInline(line.replace(/^#\s+/, ''))}</h2>`);
      continue;
    }
    if (/^#{2}\s/.test(line)) {
      closeOpenBlocks();
      html.push(`<h2>${processInline(line.replace(/^##\s+/, ''))}</h2>`);
      continue;
    }
    if (/^#{3}\s/.test(line)) {
      closeOpenBlocks();
      html.push(`<h3>${processInline(line.replace(/^###\s+/, ''))}</h3>`);
      continue;
    }

    // Blockquote
    if (line.startsWith('> ')) {
      if (!inBlockquote) {
        closeOpenBlocks();
        html.push('<blockquote>');
        inBlockquote = true;
      }
      html.push(`<p>${processInline(line.replace(/^>\s*/, ''))}</p>`);
      continue;
    } else if (inBlockquote && line.trim() === '') {
      html.push('</blockquote>');
      inBlockquote = false;
      continue;
    }

    // Unordered list
    if (/^[-*]\s/.test(line)) {
      if (inOrderedList) { html.push('</ol>'); inOrderedList = false; }
      if (!inList) { closeOpenBlocks(); html.push('<ul>'); inList = true; }
      html.push(`<li>${processInline(line.replace(/^[-*]\s+/, ''))}</li>`);
      continue;
    }

    // Ordered list
    if (/^\d+\.\s/.test(line)) {
      if (inList) { html.push('</ul>'); inList = false; }
      if (!inOrderedList) { closeOpenBlocks(); html.push('<ol>'); inOrderedList = true; }
      html.push(`<li>${processInline(line.replace(/^\d+\.\s+/, ''))}</li>`);
      continue;
    }

    // Horizontal rule
    if (/^---+$/.test(line.trim())) {
      closeOpenBlocks();
      html.push('<hr />');
      continue;
    }

    // HTML/SVG block passthrough — track open/close tags to pass entire blocks
    if (inHtmlBlock > 0) {
      html.push(line);
      const opens = (line.match(/<(?:svg|div|figure)[\s>]/g) || []).length;
      const closes = (line.match(/<\/(?:svg|div|figure)>/g) || []).length;
      inHtmlBlock += opens - closes;
      if (inHtmlBlock < 0) inHtmlBlock = 0;
      continue;
    }

    // Detect start of HTML/SVG block
    if (/^\s*<(?:svg|div|figure)[\s>]/.test(line)) {
      closeOpenBlocks();
      html.push(line);
      const opens = (line.match(/<(?:svg|div|figure)[\s>]/g) || []).length;
      const closes = (line.match(/<\/(?:svg|div|figure)>/g) || []).length;
      inHtmlBlock = opens - closes;
      if (inHtmlBlock < 0) inHtmlBlock = 0;
      continue;
    }

    // Empty line: close open blocks, add paragraph break
    if (line.trim() === '') {
      closeOpenBlocks();
      html.push('');
      continue;
    }

    // Normal paragraph line
    closeOpenBlocks();
    html.push(`<p>${processInline(line)}</p>`);
  }

  closeOpenBlocks();
  if (inCodeBlock) {
    html.push('</code></pre>');
  }

  return html.join('\n');
}

// ── Helpers ───────────────────────────────────────────────────────────

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
  thumbnail_url: string;
}

const EMPTY_FORM: EditorForm = {
  title: '',
  excerpt: '',
  content: '',
  author: '',
  tags: '',
  thumbnail_url: '',
};

// ── Main Component ────────────────────────────────────────────────────

function BlogPage({ isAdmin }: BlogPageProps) {
  const navigate = useNavigate();

  const [view, setView] = useState<BlogView>('list');
  const [posts, setPosts] = useState<BlogPost[]>([]);
  const [selectedPost, setSelectedPost] = useState<BlogPost | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Editor state (admin only)
  const [editingPost, setEditingPost] = useState<BlogPost | null>(null);
  const [form, setForm] = useState<EditorForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // ── Data fetching ──────────────────────────────────────────────────

  const loadPosts = useCallback(async (tag?: string) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchBlogPosts(tag ?? undefined);
      setPosts((response.data?.posts ?? response.data) as BlogPost[]);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to load posts.');
      // Fall back to empty list so UI is usable
      setPosts([]);
    } finally {
      setLoading(false);
    }
  }, []);


  useEffect(() => {
    loadPosts();
  }, [loadPosts]);

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
    window.scrollTo({ top: 0, behavior: 'smooth' });
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
    } catch (err: any) {
      alert(err?.response?.data?.detail ?? '삭제 중 오류가 발생했습니다.');
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
    } catch (err: any) {
      setSaveError(err?.response?.data?.detail ?? '저장 중 오류가 발생했습니다.');
    } finally {
      setSaving(false);
    }
  };

  // ── Header shared by all views ─────────────────────────────────────

  const renderHeader = () => (
    <div className="blog-app-header">
      <div className="blog-header-nav">
        <div className="blog-logo" onClick={() => navigate('/')}>
          <img
            src="/Jiphyeonjeon_llama.png"
            alt="Jiphyeonjeon"
            className="blog-logo-icon"
            onError={(e) => { e.currentTarget.style.display = 'none'; }}
          />
          <span className="blog-brand-name">Jiphyeonjeon</span>
        </div>
        <div className="blog-header-actions">
          <button className="blog-nav-btn blog-nav-btn-active">Blog</button>
          <button className="blog-nav-btn" onClick={() => navigate('/')}>Search</button>
          <button className="blog-nav-btn" onClick={() => navigate('/mypage')}>My Page</button>
        </div>
      </div>
    </div>
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
        <div className="blog-grid">
          {posts.map((post, idx) => (
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

                {/* Row 1: Date · Reading time */}
                <div className="blog-card-meta">
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
    </>
  );

  // ── Detail view ────────────────────────────────────────────────────

  const renderDetail = () => {
    if (!selectedPost) return null;

    return (
      <div className="blog-detail">
        <button className="blog-detail-back" onClick={() => { setView('list'); setSelectedPost(null); }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
            <line x1="19" y1="12" x2="5" y2="12" />
            <polyline points="12 19 5 12 12 5" />
          </svg>
          Back to Blog
        </button>

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

        <div
          className="blog-detail-content"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(selectedPost.content) }}
        />

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

  return (
    <div className="blog-container">
      {renderHeader()}
      <div className="blog-content">
        {view === 'list' && renderList()}
        {view === 'detail' && renderDetail()}
        {view === 'editor' && isAdmin && renderEditor()}
      </div>
    </div>
  );
}

export default BlogPage;
