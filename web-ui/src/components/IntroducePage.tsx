import { Link, useNavigate } from 'react-router-dom';
import LandingSections from './LandingSections';
import './IntroducePage.css';

const INTRO_NAV = [
  { href: '#difference', label: 'Why it is different' },
  { href: '#workflow', label: 'Research flow' },
  { href: '#outputs', label: 'Evidence & public reviews' },
  { href: '#capabilities', label: 'Capabilities' },
  { href: '#faq', label: 'FAQ' },
  { href: '#claude', label: 'Claude extension' },
];

function IntroducePage() {
  const navigate = useNavigate();

  const goToSearch = (searchQuery: string) => {
    navigate(`/?q=${encodeURIComponent(searchQuery)}`);
  };

  return (
    <main className="main-content introduce-shell">
      <div className="introduce-page">
        <header className="introduce-hero">
          <div className="introduce-hero-copy">
            <p className="introduce-eyebrow">An AI research workspace for researchers, graduate students, and research engineers</p>
            <h1 className="introduce-title">
              Find the papers.
              <span>Read the evidence.</span>
            </h1>
            <p className="introduce-lead">
              Search across arXiv, Google Scholar, OpenAlex, and more. Read selected papers
              side by side with AI, map the disagreements, and check important claims against
              the source before deciding what to read next.
            </p>
            <div className="introduce-cta">
              <Link className="introduce-btn" to="/">
                Search papers
              </Link>
              <Link className="introduce-btn introduce-btn--ghost" to="/blog/category/paper-review">
                Read public reviews
              </Link>
            </div>
            <p className="introduce-hero-note">
              Search without signing in. Sign in only when you want to save work to your research space.
            </p>
          </div>

          <div className="introduce-hero-art" aria-hidden="true">
            <div className="introduce-art-sequence">
              <span>Discover</span>
              <i>→</i>
              <span>Review</span>
              <i>→</i>
              <span>Verify</span>
              <i>→</i>
              <span>Continue</span>
            </div>
          </div>
        </header>

        <dl className="introduce-proof" aria-label="Jiphyeonjeon access and coverage">
          <div className="introduce-proof-item">
            <dt>Up to 6</dt>
            <dd>configured search routes</dd>
          </div>
          <div className="introduce-proof-item">
            <dt>No sign-in</dt>
            <dd>required to start searching</dd>
          </div>
          <div className="introduce-proof-item">
            <dt>Source-checked</dt>
            <dd>evidence status for each claim</dd>
          </div>
        </dl>
        <p className="introduce-proof-note">
          Jiphyeonjeon currently connects arXiv, Google Scholar, OpenAlex, DBLP,
          Connected Papers, and Korean academic search. Coverage varies by source and query.
        </p>

        <nav className="introduce-index" aria-label="About page sections">
          <span className="introduce-index-label">Explore</span>
          <div className="introduce-index-links">
            {INTRO_NAV.map(item => (
              <a key={item.href} href={item.href}>{item.label}</a>
            ))}
          </div>
        </nav>

        <LandingSections onExampleSearch={goToSearch} />
      </div>
    </main>
  );
}

export default IntroducePage;
