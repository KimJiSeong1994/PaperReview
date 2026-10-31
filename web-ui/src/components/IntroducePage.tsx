import { Fragment } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import LandingSections from './LandingSections';
import './IntroducePage.css';

export type IntroduceLocale = 'en' | 'ko';

const COPY = {
  en: {
    nav: [
      ['#difference', 'Why it is different'],
      ['#workflow', 'Research flow'],
      ['#outputs', 'Evidence & public reviews'],
      ['#capabilities', 'Capabilities'],
      ['#faq', 'FAQ'],
      ['#claude', 'Claude extension'],
    ],
    eyebrow: 'An AI research workspace for researchers, graduate students, and research engineers',
    title: 'Find the papers.',
    titleAccent: 'Read the evidence.',
    lead: 'Search across arXiv, Google Scholar, OpenAlex, and more. Read selected papers side by side with AI, map the disagreements, and check important claims against the source before deciding what to read next.',
    search: 'Search papers',
    reviews: 'Read public reviews',
    note: 'Search without signing in. Sign in only when you want to save work to your research space.',
    sequence: ['Discover', 'Review', 'Verify', 'Continue'],
    proofLabel: 'Jiphyeonjeon access and coverage',
    proof: [
      ['Up to 6', 'configured search routes'],
      ['No sign-in', 'required to start searching'],
      ['Source-checked', 'evidence status for each claim'],
    ],
    proofNote: 'Jiphyeonjeon currently connects arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers, and Korean academic search. Coverage varies by source and query.',
    sectionLabel: 'About page sections',
    explore: 'Explore',
  },
  ko: {
    nav: [
      ['#difference', '무엇이 다른가'],
      ['#workflow', '연구 흐름'],
      ['#outputs', '근거와 공개 리뷰'],
      ['#capabilities', '주요 기능'],
      ['#faq', '자주 묻는 질문'],
      ['#claude', 'Claude 확장'],
    ],
    eyebrow: '연구자·대학원생·리서치 엔지니어를 위한 AI 연구 워크스페이스',
    title: '논문을 찾은 뒤,',
    titleAccent: '근거까지 읽습니다.',
    lead: 'arXiv·Google Scholar·OpenAlex 등 여러 출처에서 질문에 맞는 논문을 찾고, 여러 편을 AI로 함께 읽어 쟁점을 정리합니다. 중요한 주장은 원문에서 다시 확인하고, 다음에 읽을 논문까지 남깁니다.',
    search: '논문 검색해보기',
    reviews: '공개 리뷰 읽기',
    note: '검색은 로그인 없이 바로 시작할 수 있습니다. 저장과 개인 연구 공간은 로그인 후 이용합니다.',
    sequence: ['찾기', '읽기', '검증', '다음 읽기'],
    proofLabel: '집현전 이용 범위',
    proof: [
      ['최대 6개', '현재 구성된 검색 경로'],
      ['로그인 없이', '바로 시작하는 논문 검색'],
      ['원문 대조', '주장별 근거와 검증 상태 표시'],
    ],
    proofNote: 'arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers와 국내 논문 검색을 구성했습니다. 소스별 응답 범위는 검색 시점에 따라 달라질 수 있습니다.',
    sectionLabel: '소개 페이지 바로가기',
    explore: '살펴보기',
  },
} as const;

function IntroducePage({ locale = 'en' }: { locale?: IntroduceLocale }) {
  const navigate = useNavigate();
  const copy = COPY[locale];

  const goToSearch = (searchQuery: string) => {
    navigate(`/?q=${encodeURIComponent(searchQuery)}`);
  };

  return (
    <main className="main-content introduce-shell" lang={locale}>
      <div className="introduce-page">
        <header className="introduce-hero">
          <div className="introduce-hero-copy">
            <p className="introduce-eyebrow">{copy.eyebrow}</p>
            <h1 className="introduce-title">
              {copy.title}
              <span>{copy.titleAccent}</span>
            </h1>
            <p className="introduce-lead">{copy.lead}</p>
            <div className="introduce-cta">
              <Link className="introduce-btn" to="/">{copy.search}</Link>
              <Link className="introduce-btn introduce-btn--ghost" to="/blog/category/paper-review">
                {copy.reviews}
              </Link>
            </div>
            <p className="introduce-hero-note">{copy.note}</p>
          </div>

          <div className="introduce-hero-art" aria-hidden="true">
            <div className="introduce-art-sequence">
              {copy.sequence.map((step, index) => (
                <Fragment key={step}>
                  {index > 0 && <i>→</i>}
                  <span>{step}</span>
                </Fragment>
              ))}
            </div>
          </div>
        </header>

        <dl className="introduce-proof" aria-label={copy.proofLabel}>
          {copy.proof.map(([term, description]) => (
            <div className="introduce-proof-item" key={term}>
              <dt>{term}</dt>
              <dd>{description}</dd>
            </div>
          ))}
        </dl>
        <p className="introduce-proof-note">{copy.proofNote}</p>

        <nav className="introduce-index" aria-label={copy.sectionLabel}>
          <span className="introduce-index-label">{copy.explore}</span>
          <div className="introduce-index-links">
            {copy.nav.map(([href, label]) => (
              <a key={href} href={href}>{label}</a>
            ))}
          </div>
        </nav>

        <LandingSections locale={locale} onExampleSearch={goToSearch} />
      </div>
    </main>
  );
}

export default IntroducePage;
