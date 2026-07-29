import { useNavigate } from 'react-router-dom';
import LandingSections from './LandingSections';
import './IntroducePage.css';

function IntroducePage() {
  const navigate = useNavigate();

  // The search itself lives on the root route, which picks the query up from ?q=.
  const goToSearch = (searchQuery: string) => {
    navigate(`/?q=${encodeURIComponent(searchQuery)}`);
  };

  return (
    <div className="main-content">
      <div className="introduce-page">
        <header className="introduce-hero">
          <h1 className="introduce-title">논문을 찾는 데서 끝나지 않습니다</h1>
          <p className="introduce-lead">
            검색하고, 여러 에이전트가 읽고, 근거를 검증하고, 학습 경로까지 이어갑니다.
          </p>
          <div className="introduce-cta">
            <button type="button" className="introduce-btn" onClick={() => navigate('/')}>
              논문 검색하기
            </button>
            <a className="introduce-btn introduce-btn--ghost" href="#claude">
              Claude에 연결하기
            </a>
          </div>
        </header>
        <LandingSections onExampleSearch={goToSearch} />
      </div>
    </div>
  );
}

export default IntroducePage;
