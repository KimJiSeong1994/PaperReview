import { Link, useNavigate } from 'react-router-dom';
import LandingSections from './LandingSections';
import './IntroducePage.css';

const INTRO_NAV = [
  { href: '#difference', label: '무엇이 다른가' },
  { href: '#workflow', label: '연구 흐름' },
  { href: '#outputs', label: '근거와 공개 리뷰' },
  { href: '#capabilities', label: '주요 기능' },
  { href: '#faq', label: '자주 묻는 질문' },
  { href: '#claude', label: 'Claude 확장' },
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
            <p className="introduce-eyebrow">연구자·대학원생·리서치 엔지니어를 위한 AI 연구 워크스페이스</p>
            <h1 className="introduce-title">
              논문을 찾은 뒤,
              <span>근거까지 읽습니다.</span>
            </h1>
            <p className="introduce-lead">
              arXiv·Google Scholar·OpenAlex 등 여러 출처에서 질문에 맞는 논문을 찾고,
              여러 편을 AI로 함께 읽어 쟁점을 정리합니다.
              중요한 주장은 원문에서 다시 확인하고, 다음에 읽을 논문까지 남깁니다.
            </p>
            <div className="introduce-cta">
              <Link className="introduce-btn" to="/">
                논문 검색해보기
              </Link>
              <Link className="introduce-btn introduce-btn--ghost" to="/blog/category/paper-review">
                공개 리뷰 읽기
              </Link>
            </div>
            <p className="introduce-hero-note">
              검색은 로그인 없이 바로 시작할 수 있습니다. 저장과 개인 연구 공간은 로그인 후 이용합니다.
            </p>
          </div>

          <div className="introduce-hero-art" aria-hidden="true">
            <div className="introduce-art-sequence">
              <span>찾기</span>
              <i>→</i>
              <span>읽기</span>
              <i>→</i>
              <span>검증</span>
              <i>→</i>
              <span>다음 읽기</span>
            </div>
          </div>
        </header>

        <dl className="introduce-proof" aria-label="집현전 이용 범위">
          <div className="introduce-proof-item">
            <dt>최대 6개</dt>
            <dd>현재 구성된 검색 경로</dd>
          </div>
          <div className="introduce-proof-item">
            <dt>로그인 없이</dt>
            <dd>바로 시작하는 논문 검색</dd>
          </div>
          <div className="introduce-proof-item">
            <dt>원문 대조</dt>
            <dd>주장별 근거와 검증 상태 표시</dd>
          </div>
        </dl>
        <p className="introduce-proof-note">
          arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers와 국내 논문 검색을 구성했습니다.
          소스별 응답 범위는 검색 시점에 따라 달라질 수 있습니다.
        </p>

        <nav className="introduce-index" aria-label="소개 페이지 바로가기">
          <span className="introduce-index-label">살펴보기</span>
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
