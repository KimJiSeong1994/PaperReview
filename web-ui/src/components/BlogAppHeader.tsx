import { useNavigate } from 'react-router-dom';
import ThemeToggle from './ThemeToggle';

/** Shared minimal blog header for surfaces that are not BlogPage itself
 * (BlogPage keeps its own header, which closes over search/view state).
 * Blog is always the active tab here: every current caller lives under /blog. */
function BlogAppHeader() {
  const navigate = useNavigate();

  return (
    <div className="blog-app-header">
      <div className="blog-header-nav">
        <a
          className="blog-logo"
          href="/"
          style={{ textDecoration: 'none', color: 'inherit' }}
          onClick={(e) => { e.preventDefault(); navigate('/'); }}
        >
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
        </a>
        <div className="blog-header-actions">
          <a
            className="blog-nav-btn blog-nav-btn-active"
            href="/blog"
            aria-current="page"
            onClick={(e) => { e.preventDefault(); navigate('/blog'); }}
          >
            Blog
          </a>
          <a className="blog-nav-btn" href="/" onClick={(e) => { e.preventDefault(); navigate('/'); }}>
            Search
          </a>
          <a className="blog-nav-btn" href="/mypage" onClick={(e) => { e.preventDefault(); navigate('/mypage'); }}>
            My Page
          </a>
          <ThemeToggle />
        </div>
      </div>
    </div>
  );
}

export default BlogAppHeader;
