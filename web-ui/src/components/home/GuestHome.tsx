import { useState, type ReactNode } from 'react';
import type { SampleSummary } from '../../types';
import MascotFace from './MascotFace';
import SampleReplay from './SampleReplay';

interface GuestHomeProps {
  /** The guest composer, built by the home so it shares the login gate and draft state. */
  composer: ReactNode;
  samples: SampleSummary[];
  /** The home's ask (sign-in gate, then a new conversation); the replay's CTA uses it. */
  onAsk: (question: string) => void;
}

/**
 * The signed-out home: the question and sample cards on the left, a sample
 * conversation replaying on the right. No sidebar, nothing that needs an account.
 */
function GuestHome({ composer, samples, onAsk }: GuestHomeProps) {
  const [activeSlug, setActiveSlug] = useState<string | null>(null);
  const active = samples.find(sample => sample.slug === activeSlug) ?? samples[0] ?? null;

  return (
    <div className="home-shell home-shell--guest">
      <div className="home-guest">
        <section className="home-guest-intro" aria-labelledby="home-title">
          <p className="home-pill">논문 연구 AI, 로그인 후 무료</p>
          <h1 id="home-title" className="home-title">오늘은 <span className="home-title-accent">어떤 논문</span>부터 볼까요?</h1>
          <div className="home-guest-mascot">
            <MascotFace size={80} className="home-guest-face" />
            <p>
              <span>궁금한 주제나 논문 제목을 편하게 물어보세요.</span>
              <span>집현전이 여러 소스에서 찾아 근거까지 읽어 드려요.</span>
            </p>
          </div>

          <div className="home-guest-ask">
            {composer}
            <p className="home-composer-note">내 질문은 로그인 후 무료로 검색·대화해요.</p>
          </div>

          {samples.length > 0 && (
            <section className="home-samples" aria-labelledby="home-samples">
              <div className="home-samples-head">
                <h2 id="home-samples">샘플 질문으로 먼저 써보세요</h2>
                <span>로그인 없이 답변 보기</span>
              </div>
              <ul className="home-sample-cards">
                {samples.map(sample => {
                  const isActive = sample.slug === active?.slug;
                  return (
                    <li key={sample.slug}>
                      <button
                        type="button"
                        className={`home-sample-card${isActive ? ' is-active' : ''}`}
                        aria-pressed={isActive}
                        onClick={() => setActiveSlug(sample.slug)}
                      >
                        <span className="home-sample-card-text">
                          <span className="home-sample-card-title">{sample.question}</span>
                          <span className="home-sample-card-meta">{sample.title}</span>
                        </span>
                        <span className="home-sample-card-icon" aria-hidden="true">↗</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
        </section>

        {active && (
          <div className="home-guest-replay">
            <SampleReplay key={active.slug} sample={active} onContinue={onAsk} />
          </div>
        )}

        <p className="home-disclaimer home-guest-disclaimer">AI 리뷰도 틀릴 수 있어요. 중요한 주장은 원문 근거를 한 번 더 확인해 주세요.</p>
      </div>
    </div>
  );
}

export default GuestHome;
