import { Link, useLocation } from 'react-router-dom';
import './SiteFooter.css';

// Maintainer profile links shown site-wide for service credibility.
// Keep in sync with the SSR footer (routers/seo.py::_SITE_FOOTER_HTML)
// and the Organization sameAs entries in seo/structuredData.ts.
export const GITHUB_PROFILE_URL = 'https://github.com/KimJiSeong1994';
export const LINKEDIN_PROFILE_URL = 'https://www.linkedin.com/in/jiseong-kim-868218193/';

export const SITE_FOOTER_BRAND = '© Jiphyeonjeon (집현전)';

// The whole footer, mirrored byte-for-byte by _SITE_FOOTER_HTML in
// routers/seo.py so crawlers on SSR pages see the same links. The Korean
// /ko/introduce/ href is what SSR ships (it only serves Korean pages);
// English routes swap it below. tests/test_site_footer_sync.py enforces this.
export const SITE_FOOTER_COLUMNS: {
  heading: string;
  links: { href: string; label: string }[];
}[] = [
  {
    heading: '집현전',
    links: [
      { href: '/', label: '논문 검색' },
      { href: '/ko/introduce/', label: '서비스 소개' },
    ],
  },
  {
    heading: '블로그',
    links: [
      { href: '/blog', label: '전체 아티클' },
      { href: '/blog#series-index', label: '아티클 시리즈' },
      { href: '/blog/tags', label: '태그 전체 보기' },
    ],
  },
  {
    heading: '만든 사람',
    links: [
      { href: GITHUB_PROFILE_URL, label: 'GitHub' },
      { href: LINKEDIN_PROFILE_URL, label: 'LinkedIn' },
    ],
  },
];

function SiteFooter() {
  const location = useLocation();
  // Mirrors App.tsx's isKoreanIntroduce so 서비스 소개 keeps the reader on the
  // locale they are already reading; /introduce/ and /ko/introduce/ are
  // separately indexed pages with their own canonicals.
  const isKoreanIntroduce = location.pathname.startsWith('/ko/introduce');

  return (
    <footer className="site-footer">
      <div className="site-footer-columns">
        {SITE_FOOTER_COLUMNS.map((column) => (
          <nav className="site-footer-column" key={column.heading} aria-label={column.heading}>
            <p className="site-footer-heading">{column.heading}</p>
            <ul className="site-footer-list">
              {column.links.map((link) => (
                <li key={link.href}>
                  {link.href.startsWith('http') ? (
                    <a href={link.href} target="_blank" rel="me noopener noreferrer">
                      {link.label}
                    </a>
                  ) : (
                    <Link
                      to={
                        link.href === '/ko/introduce/' && !isKoreanIntroduce
                          ? '/introduce/'
                          : link.href
                      }
                    >
                      {link.label}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
      <span className="site-footer-brand">{SITE_FOOTER_BRAND}</span>
    </footer>
  );
}

export default SiteFooter;
