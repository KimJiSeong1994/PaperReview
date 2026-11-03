import { useState } from 'react';
import { Link } from 'react-router-dom';
import { copyToClipboard } from '../utils/clipboard';
import { INTRODUCE_FAQ } from '../seo/introduceFaq';
import './LandingSections.css';

type Locale = 'en' | 'ko';

interface LandingSectionsProps {
  locale?: Locale;
}

const GIT_INSTALL = [
  'git clone https://github.com/KimJiSeong1994/jiphyeonjeon-agent.git',
  'cd jiphyeonjeon-agent',
  'bash scripts/setup.sh',
].join('\n');

const WORKFLOW = {
  en: {
    kicker: 'How it works',
    title: 'What happens in one conversation',
    steps: [
      ['Ask', 'In your own words. Write dates and conditions as part of the sentence.'],
      ['Find', 'Six scholarly sources are searched and deduplicated; the results open as a graph and a list in the side panel.'],
      ['Read', 'Tap a number in the answer to reach its paper. Open the PDF and get its key sentences highlighted.'],
      ['Go deeper', 'A fast review takes minutes; a full review also checks claims against the source.'],
    ],
    next: 'Bookmarks, curricula, and daily recommendations decide what to read next.',
  },
  ko: {
    kicker: '어떻게 동작하나요',
    title: '대화 한 번에 일어나는 일',
    steps: [
      ['묻기', '평소 말투 그대로. 기간·조건도 문장으로 적으면 됩니다.'],
      ['찾기', '여섯 개 학술 출처에서 찾아 중복을 걷어내고, 결과는 오른쪽 패널의 그래프와 목록으로 봅니다.'],
      ['읽기', '답변의 번호를 누르면 근거 논문으로. PDF를 열고 핵심 문장을 자동 하이라이트합니다.'],
      ['깊이', '빠른 리뷰는 몇 분, 정밀 리뷰는 주장을 원문과 대조하는 검증까지 합니다.'],
    ],
    next: '북마크·커리큘럼·일일 추천으로 다음 읽기를 정합니다.',
  },
} as const;

const OUTPUTS = {
  en: {
    kicker: 'Evidence in practice',
    title: 'See how a claim connects to its source',
    exampleKicker: 'Evidence check from a full review',
    claimLabel: 'Review claim',
    claim: 'The paper’s “causal gate” is not a validated directed causal edge. It is an undirected binary connection that opens a retrieval path.',
    sourceLabel: 'Source check',
    source: 'The method and algorithm assign neither direction nor effect size to the gate; an LLM judges causal or logical dependence.',
    verdictLabel: 'Verdict',
    verdict: 'We limit the interpretation to what the source supports.',
    readReview: 'Read the full evidence review',
    allReviews: 'Browse all public reviews',
  },
  ko: {
    kicker: '실제 근거 확인',
    title: '주장과 원문이 어떻게 연결되는지 먼저 보세요',
    exampleKicker: '정밀 리뷰의 검토 예시',
    claimLabel: '리뷰 주장',
    claim: '논문이 말하는 “인과 게이트”는 검증된 방향성 인과 간선이 아니라, 검색 경로를 여는 무방향 이진 연결입니다.',
    sourceLabel: '원문 확인',
    source: '원문 방법과 알고리즘을 대조하면 게이트에는 방향과 효과 크기가 없고, LLM이 인과 또는 논리적 의존성을 판정합니다.',
    verdictLabel: '판정',
    verdict: '원문이 뒷받침하는 범위로 해석을 제한했습니다.',
    readReview: '검토 과정이 담긴 리뷰 읽기',
    allReviews: '공개 리뷰 전체 보기',
  },
} as const;

const SKILLS = [
  { skill: 'jh-review-paper', en: ['Read one paper in depth', 'Deep-review this paper by arXiv ID or title'], ko: ['논문 하나를 깊게 읽고 싶다', 'arXiv ID 또는 논문 제목으로 딥리뷰해줘'] },
  { skill: 'jh-daily-digest', en: ['Decide what to read today', 'Brief me on today’s papers for this topic'], ko: ['오늘 무엇을 읽을지 정하고 싶다', '오늘 주제 기준으로 논문 브리핑 해줘'] },
  { skill: 'jh-explore', en: ['Expand from one paper', 'Find related work that follows from this paper'], ko: ['한 논문에서 관련 연구를 넓히고 싶다', '선택한 논문에서 이어지는 관련 연구를 찾아줘'] },
  { skill: 'jh-build-curriculum', en: ['Learn a topic in order', 'Build a study curriculum for this topic'], ko: ['주제를 처음부터 순서대로 배우고 싶다', '주제 기반 학습 커리큘럼을 짜줘'] },
];

const CLAUDE = {
  en: {
    kicker: 'Optional Claude extension',
    title: 'Bring your Jiphyeonjeon workflow into Claude',
    body: 'Jiphyeonjeon Agent is an optional open-source extension installed separately from the web app.',
    install: 'Ask Claude to install it:',
    installPrompt: 'Install the Jiphyeonjeon agent',
    more: 'Research skills and terminal install',
    terminal: 'Install from the terminal',
    skills: 'Research skills',
    outroBefore: 'After installation, open ',
    outroAfter: ' in Claude Code and confirm that jiphyeonjeon appears as Connected.',
    repo: 'Agent GitHub repository (all MCP tools)',
  },
  ko: {
    kicker: '선택형 Claude 확장',
    title: '웹에서 하던 연구를 Claude로 확장합니다',
    body: '집현전 Agent는 웹 서비스와 별도로 설치하는 오픈소스 확장입니다.',
    install: 'Claude에게 이렇게 요청하면 설치합니다.',
    installPrompt: '집현전 agent 설치해줘',
    more: '연구 스킬과 터미널 설치',
    terminal: '터미널에서 직접 설치하기',
    skills: '연구 스킬',
    outroBefore: '설치 후 Claude Code의 ',
    outroAfter: ' 화면에서 jiphyeonjeon이 Connected로 표시되는지 확인하세요.',
    repo: 'Agent GitHub 저장소 (MCP 도구 전체)',
  },
} as const;

function CopySnippet({ text, locale }: { text: string; locale: Locale }) {
  const [copied, setCopied] = useState(false);
  const multiline = text.includes('\n');

  const handleCopy = () => {
    copyToClipboard(text)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => setCopied(false));
  };

  return (
    <div className={`landing-snippet${multiline ? ' landing-snippet--block' : ''}`}>
      {multiline ? (
        <pre className="landing-snippet-text">{text}</pre>
      ) : (
        <code className="landing-snippet-text">{text}</code>
      )}
      <button
        type="button"
        className="landing-copy-btn"
        data-copied={copied}
        onClick={handleCopy}
        aria-live="polite"
        aria-label={copied
          ? (locale === 'ko' ? '클립보드에 복사했습니다' : 'Copied to clipboard')
          : (locale === 'ko' ? `“${text}” 복사` : `Copy “${text}”`)}
      >
        {copied ? (locale === 'ko' ? '복사됨' : 'Copied') : (locale === 'ko' ? '복사' : 'Copy')}
      </button>
    </div>
  );
}

function SectionHeading({ kicker, title, body }: { kicker: string; title: string; body?: string }) {
  return (
    <header className="landing-section-header">
      <p className="intro-eyebrow">{kicker}</p>
      <h2 className="landing-section-title">{title}</h2>
      {body && <p className="landing-section-lead">{body}</p>}
    </header>
  );
}

function LandingSections({ locale = 'en' }: LandingSectionsProps) {
  const workflow = WORKFLOW[locale];
  const outputs = OUTPUTS[locale];
  const claude = CLAUDE[locale];

  return (
    <div className="landing">
      <section className="intro-section" id="workflow">
        <SectionHeading kicker={workflow.kicker} title={workflow.title} />
        <ol className="intro-steps">
          {workflow.steps.map(([label, body], index) => (
            <li className="intro-step" key={label}>
              <div className="intro-step-head">
                <span className="intro-step-num">0{index + 1}</span>
                <h3 className="intro-step-title">{label}</h3>
              </div>
              <p className="intro-step-body">{body}</p>
            </li>
          ))}
        </ol>
        <p className="intro-eyebrow landing-workflow-next">{workflow.next}</p>
      </section>

      <section className="intro-section" id="outputs">
        <SectionHeading kicker={outputs.kicker} title={outputs.title} />

        <article className="intro-evidence" aria-labelledby="evidence-example-title">
          <div className="landing-evidence-head">
            <p className="intro-chip intro-chip--accent">{outputs.exampleKicker}</p>
            <p className="landing-evidence-paper">CausalRAG2 · arXiv:2602.05143v2</p>
          </div>
          <div className="landing-evidence-grid">
            <div className="landing-evidence-cell">
              <p className="landing-evidence-label">{outputs.claimLabel}</p>
              <h3 id="evidence-example-title">{outputs.claim}</h3>
            </div>
            <div className="landing-evidence-cell">
              <p className="landing-evidence-label">{outputs.sourceLabel}</p>
              <p>{outputs.source}</p>
            </div>
          </div>
          <div className="intro-verdict">
            <span className="intro-chip intro-chip--accent">{outputs.verdictLabel}</span>
            <p>{outputs.verdict}</p>
            <Link className="landing-link intro-verdict-link" to="/blog/causalrag2-hugrag-hierarchical-causal-gating">{outputs.readReview} →</Link>
          </div>
        </article>

        <Link className="landing-link landing-output-more" to="/blog/category/paper-review">
          {outputs.allReviews} →
        </Link>
      </section>

      <section className="intro-section" id="faq">
        <SectionHeading
          kicker={locale === 'ko' ? '자주 묻는 질문' : 'Frequently asked questions'}
          title={locale === 'ko' ? 'AI 논문 검색과 리뷰, 자주 묻는 질문' : 'Questions about AI paper search and review'}
        />
        {/* Collapsed on the page; the static copy and the FAQPage JSON-LD keep every answer. */}
        <div className="intro-faq-list">
          {INTRODUCE_FAQ[locale].map(item => (
            <details className="intro-faq-item" key={item.question}>
              <summary><h3>{item.question}</h3></summary>
              <p>{item.answer}</p>
            </details>
          ))}
        </div>
      </section>

      <section className="intro-section intro-claude" id="claude" tabIndex={-1}>
        <SectionHeading kicker={claude.kicker} title={claude.title} body={claude.body} />

        <div className="landing-install">
          <p className="landing-install-label">{claude.install}</p>
          <CopySnippet locale={locale} text={claude.installPrompt} />

          <details className="landing-details">
            <summary className="landing-summary">{claude.more}</summary>
            <p className="landing-install-note">{claude.terminal}</p>
            <CopySnippet locale={locale} text={GIT_INSTALL} />
            <h3 className="landing-sub-title">{claude.skills}</h3>
            <ul className="landing-skill-map">
              {SKILLS.map(item => (
                <li className="landing-skill" key={item.skill}>
                  <div className="landing-skill-head">
                    <span className="landing-skill-situation">{item[locale][0]}</span>
                    <code className="landing-skill-name">{item.skill}</code>
                  </div>
                  <CopySnippet locale={locale} text={item[locale][1]} />
                </li>
              ))}
            </ul>
            <p className="landing-mcp-outro">
              {claude.outroBefore}
              <code className="landing-code">/mcp</code>
              {claude.outroAfter}
            </p>
            <a className="landing-link" href="https://github.com/KimJiSeong1994/jiphyeonjeon-agent" target="_blank" rel="noreferrer noopener">
              {claude.repo} →
            </a>
          </details>
        </div>
      </section>

    </div>
  );
}

export default LandingSections;
