import './SiteFooter.css';

// Maintainer profile links shown site-wide for service credibility.
// Keep in sync with the SSR footer (routers/seo.py::_site_footer_html)
// and the Organization sameAs entries in seo/structuredData.ts.
export const GITHUB_PROFILE_URL = 'https://github.com/KimJiSeong1994';
export const LINKEDIN_PROFILE_URL = 'https://www.linkedin.com/in/jiseong-kim-868218193/';

function SiteFooter() {
  return (
    <footer className="site-footer">
      <span className="site-footer-brand">© Jiphyeonjeon (집현전)</span>
      <nav className="site-footer-links" aria-label="Maintainer profiles">
        <a href={GITHUB_PROFILE_URL} target="_blank" rel="me noopener noreferrer">
          GitHub
        </a>
        <span className="site-footer-sep" aria-hidden="true">·</span>
        <a href={LINKEDIN_PROFILE_URL} target="_blank" rel="me noopener noreferrer">
          LinkedIn
        </a>
      </nav>
    </footer>
  );
}

export default SiteFooter;
