import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { copyToClipboard } from '../utils/clipboard';
import './LandingSections.css';

interface LandingSectionsProps {
  onExampleSearch: (query: string) => void;
}

/* Verifiable numbers live here so the page can never contradict itself.
   PUBLISHED_REVIEWS counts category=paper-review, published=true in
   data/blog/posts.json (43 as of 2026-07-29). */
const PUBLISHED_REVIEWS = 43;
const SOURCE_COUNT = 6;
const MCP_TOOL_COUNT = 11;
const SKILL_COUNT = 7;

const GIT_INSTALL = [
  'git clone https://github.com/KimJiSeong1994/jiphyeonjeon-agent.git',
  'cd jiphyeonjeon-agent',
  'bash scripts/setup.sh',
].join('\n');

const EXAMPLE_QUERIES = [
  'graph neural networks',
  'LLM agent 논문',
  'retrieval augmented generation',
  'diffusion model',
  '멀티모달 표현학습',
];

/* Workflow describes what the user experiences; the feature rows below
   describe what the system does. Keeping those separate avoids restating
   the same sentences twice on one page. */
const WORKFLOW_STEPS = [
  {
    label: '검색',
    title: '질문에서 시작합니다',
    body: `질문 하나를 입력하면 ${SOURCE_COUNT}개 소스의 결과가 중복 없이 한 목록으로 도착합니다.`,
  },
  {
    label: '딥리뷰',
    title: '여러 에이전트가 나눠 읽습니다',
    body: '읽을 논문을 골라두고 기다리면, 5편 기준 4~5분 뒤 리뷰 한 편이 완성됩니다.',
  },
  {
    label: '사실검증',
    title: '주장마다 출처를 되짚습니다',
    body: '리뷰의 문장마다 출처가 붙어 있어, 어디까지 믿고 쓸 수 있는지 눈으로 확인합니다.',
  },
  {
    label: '학습',
    title: '다음에 읽을 것을 정합니다',
    body: '리뷰가 끝난 자리에서 이어 읽을 논문과 순서를 그대로 받습니다.',
  },
];

interface ProseRow {
  heading: string;
  caption?: string;
  keyword?: string;
  body: string;
  links?: { to: string; label: string }[];
  accent?: boolean;
}

const FEATURE_ROWS: ProseRow[] = [
  {
    heading: '찾고, 펼쳐보기',
    caption: 'Research & Discovery',
    body: `한 번 검색하면 ${SOURCE_COUNT}개 소스가 동시에 응답합니다. arXiv와 Google Scholar, OpenAlex, DBLP, Connected Papers를 각각 열어볼 필요가 없습니다. 검색 깊이는 Basic·Smart·Deep 세 모드로 조절하고, 쓸 만한 논문이 걸리면 거기서부터 인용을 최대 3단계까지 펼쳐 커뮤니티와 토폴로지를 살핍니다. 모아둔 논문으로 지식그래프를 세우면 개별 문서 검색으로는 답하기 어려운 질문도 GraphRAG·LightRAG로 물어볼 수 있습니다.`,
    links: [
      { to: '/blog/search-agent-beyond-single-query-65bcbe5c30fd', label: '검색 에이전트 이야기' },
      { to: '/blog/paper-network-graph-hidden-connections-f954b2866fb4', label: '논문 네트워크 그래프' },
    ],
  },
  {
    heading: '깊게 읽고, 검증하기',
    caption: 'Analysis & Review',
    body: '혼자 읽으면 하루가 걸리는 일을 에이전트 여러 명이 나눠 맡습니다. 연구원 에이전트가 논문별로 병렬로 읽고 지도교수 에이전트가 종합하며, 그 결과에는 주장마다 원문 근거가 붙습니다. 직접 읽을 때도 핵심 문장 표시와 수식 풀이, 논문과의 문답이 함께 갑니다.',
    links: [
      { to: '/blog/auto-highlight-ai-scholarly-annotation-f6a5ccb4ce6b', label: '오토하이라이트 만들기' },
    ],
  },
  {
    heading: '만들고, 이어가기',
    caption: 'Creation & Learning',
    body: '리뷰를 읽고 덮어두지 않아도 됩니다. 실제 대학 강의 자료를 참고한 학습 순서를 받고, 그 안의 논문이 실존하는지 OpenAlex로 확인합니다. 딥리뷰 결과는 학회용 포스터와 다이어그램으로 변환해 HTML·PDF·PPTX로 내려받고, 아침마다 연구 페르소나가 고른 논문이 도착합니다.',
    links: [
      { to: '/blog/curriculum-generator-jiphyeonjeon-9fdf6c688749', label: '커리큘럼 생성기' },
      { to: '/blog/daily-recommendations-research-persona-dailyrec2026', label: '일일 추천 설계' },
    ],
  },
];

// TODO(fact-verification stats persist 후): 실측 검증 바 미니어처 삽입 — 검토 문서 참조
const WHY_ROWS: ProseRow[] = [
  {
    keyword: '근거 있는 리뷰',
    heading: '근거를 확인할 수 있습니다',
    body: 'AI 요약 도구는 결론을 줍니다. 집현전은 그 결론이 어느 논문 어느 문장에서 왔는지를 함께 줍니다. 리뷰의 주장마다 원문 근거가 연결되어 있으므로, 읽는 사람이 직접 확인하고 인용할 수 있습니다.',
    accent: true,
    links: [{ to: '/blog/category/paper-review', label: '리뷰에서 확인하기' }],
  },
  {
    keyword: '검색 그 이후',
    heading: '검색 이후가 있습니다',
    body: '검색 도구는 논문을 찾아주고 거기서 끝납니다. 읽고, 정리하고, 다음에 읽을 것을 고르는 일은 사용자의 몫이었습니다. 집현전에서는 검색한 논문을 고르면 리뷰, 사실검증, 학습 커리큘럼까지 같은 화면에서 이어집니다.',
    links: [{ to: '/', label: '직접 검색해보기' }],
  },
  {
    keyword: '공개된 결과물',
    heading: '결과물이 공개되어 있습니다',
    body: `이 파이프라인이 만든 리뷰 ${PUBLISHED_REVIEWS}편이 블로그에 공개되어 있습니다. 도구의 설명이 아니라 실제 산출물을 읽고 판단할 수 있습니다.`,
    links: [{ to: '/blog/category/paper-review', label: '리뷰 읽어보기' }],
  },
];

const SKILL_MAP = [
  {
    situation: '논문 하나를 깊게 읽고 싶다',
    skill: 'jh-review-paper',
    prompt: 'arXiv [2401.12345] 딥리뷰해줘',
  },
  {
    situation: '오늘 뭘 읽을지 모르겠다',
    skill: 'jh-daily-digest',
    prompt: '오늘 논문 브리핑 해줘',
  },
  {
    situation: '이 논문에서 더 파고들고 싶다',
    skill: 'jh-explore',
    prompt: '[논문 제목]에서 이어지는 논문 찾아줘',
  },
  {
    situation: '주제를 처음부터 배우고 싶다',
    skill: 'jh-build-curriculum',
    prompt: '[graph neural networks] 커리큘럼 짜줘',
  },
];

const MCP_TOOLS: [string, string][] = [
  ['search_papers', '여러 소스에서 논문을 한 번에 검색합니다'],
  ['get_paper', '논문 한 편의 상세 정보를 가져옵니다'],
  ['start_review', '선택한 논문들의 딥리뷰를 시작합니다'],
  ['get_review_status', '진행 중인 리뷰의 상태와 결과를 확인합니다'],
  ['list_bookmarks', '저장해 둔 북마크 목록을 불러옵니다'],
  ['add_bookmark', '논문이나 리뷰를 북마크에 저장합니다'],
  ['remove_bookmark', '북마크를 삭제합니다'],
  ['create_curriculum', '주제에 맞는 학습 커리큘럼을 만듭니다'],
  ['explore_related', '인용 관계를 따라 관련 논문을 넓힙니다'],
  ['generate_figure', '다이어그램과 플롯을 생성합니다'],
  ['create_blog_draft', '리뷰를 블로그 초안으로 옮깁니다 (관리자)'],
];

function CopySnippet({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const multiline = text.includes('\n');

  const handleCopy = () => {
    copyToClipboard(text)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
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
        onClick={handleCopy}
        aria-live="polite"
        aria-label={copied ? '클립보드에 복사했습니다' : `"${text}" 복사`}
      >
        {copied ? '복사됨' : '복사'}
      </button>
    </div>
  );
}

/* Editorial prose row: typography and whitespace carry the structure, so the
   heading level is chosen for document order and the size comes from CSS. */
function ProseRowBlock({ row, as }: { row: ProseRow; as: 'h2' | 'h3' }) {
  const Heading = as;
  return (
    <div
      className={`landing-row${row.keyword ? ' landing-row--keyed' : ''}${row.accent ? ' landing-row--accent' : ''}`}
    >
      {row.keyword && <span className="landing-row-keyword">{row.keyword}</span>}
      <div className="landing-row-head">
        <Heading className="landing-row-title">{row.heading}</Heading>
        {row.caption && <span className="landing-row-caption">{row.caption}</span>}
      </div>
      <p className="landing-row-body">{row.body}</p>
      {row.links && (
        <p className="landing-row-links">
          {row.links.map(link => (
            <Link key={link.to} className="landing-link" to={link.to}>
              → {link.label}
            </Link>
          ))}
        </p>
      )}
    </div>
  );
}

function LandingSections({ onExampleSearch }: LandingSectionsProps) {
  const navigate = useNavigate();

  return (
    <div className="landing">
      <ul className="landing-chips" aria-label="예시 검색어">
        {EXAMPLE_QUERIES.map(q => (
          <li key={q}>
            <button type="button" className="landing-chip" onClick={() => onExampleSearch(q)}>
              {q}
            </button>
          </li>
        ))}
      </ul>

      <div className="landing-features">
        <section className="landing-section">
          <header className="landing-section-header">
            <h2 className="landing-section-title">한 번의 질문에서 여기까지 갑니다</h2>
          </header>
          <ol className="landing-workflow">
            {WORKFLOW_STEPS.map((step, i) => (
              <li className="landing-step" key={step.label}>
                <div className="landing-step-marker">
                  <span className="landing-step-num">{i + 1}</span>
                  <span className="landing-step-label">{step.label}</span>
                </div>
                <div className="landing-step-text">
                  <h3 className="landing-step-title">{step.title}</h3>
                  <p className="landing-step-body">{step.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="landing-section">
          <header className="landing-section-header">
            <h2 className="landing-section-title">왜 집현전인가</h2>
          </header>
          <div className="landing-rows">
            {WHY_ROWS.map(row => (
              <ProseRowBlock key={row.heading} row={row} as="h3" />
            ))}
          </div>
        </section>

        <section className="landing-section">
          <header className="landing-section-header">
            <h2 className="landing-section-title">찾고, 읽고, 이어갑니다</h2>
          </header>
          <div className="landing-rows">
            {FEATURE_ROWS.map(row => (
              <ProseRowBlock key={row.heading} row={row} as="h3" />
            ))}
          </div>
        </section>

        <section className="landing-section" id="claude" tabIndex={-1}>
          <header className="landing-section-header">
            <h2 className="landing-section-title">Claude에 연결하기</h2>
            <span className="landing-section-caption">MCP &amp; Skills</span>
          </header>

          <p className="landing-mcp-intro">
            논문 초록을 Claude 창에 복사해 붙여넣고 있다면, 그때가 연결할 시점입니다.
          </p>

          <div className="landing-install">
            <p className="landing-install-label">
              터미널 명령이 아닙니다. Claude Code 채팅창에 그대로 입력하세요.
            </p>
            <CopySnippet text="집현전 agent 설치해줘" />
            <p className="landing-install-note">
              로그인 → MCP 등록 → 스킬 {SKILL_COUNT}개 설치까지 한 번에 끝납니다.{' '}
              <a
                className="landing-link"
                href="https://claude.com/claude-code"
                target="_blank"
                rel="noreferrer noopener"
              >
                Claude Code가 처음이라면
              </a>
            </p>

            <details className="landing-details">
              <summary className="landing-summary">직접 설치하기 (git clone)</summary>
              <CopySnippet text={GIT_INSTALL} />
              <p className="landing-install-note">pip / uvx 설치는 지원하지 않습니다.</p>
            </details>
          </div>

          <h3 className="landing-sub-title">어떤 스킬을 쓸지 고르기</h3>
          <ul className="landing-skill-map">
            {SKILL_MAP.map(item => (
              <li className="landing-skill" key={item.skill}>
                <div className="landing-skill-head">
                  <span className="landing-skill-situation">{item.situation}</span>
                  <code className="landing-skill-name">{item.skill}</code>
                </div>
                <CopySnippet text={item.prompt} />
              </li>
            ))}
          </ul>

          <details className="landing-details">
            <summary className="landing-summary">MCP 도구 전체 보기 ({MCP_TOOL_COUNT}개)</summary>
            <div className="landing-table-wrap">
              <table className="landing-tool-table">
                <thead className="landing-sr-only">
                  <tr>
                    <th scope="col">도구</th>
                    <th scope="col">설명</th>
                  </tr>
                </thead>
                <tbody>
                  {MCP_TOOLS.map(([name, desc]) => (
                    <tr key={name}>
                      <td className="landing-tool-name">{name}</td>
                      <td className="landing-tool-desc">{desc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>

          <p className="landing-mcp-outro">
            Claude Code에서 <code className="landing-code">/mcp</code> 를 열어 jiphyeonjeon이
            ✔ Connected면 성공입니다.
            <br />
            새 버전이 나오면 &ldquo;집현전 업데이트해줘&rdquo; 한마디면 됩니다.
          </p>

          <p className="landing-row-links">
            <Link className="landing-link" to="/blog/jiphyeonjeon-agent-mcp-tool-surface-a7c9e3d4b821">
              → MCP 도구 설계 이야기
            </Link>
            <a
              className="landing-link"
              href="https://github.com/KimJiSeong1994/jiphyeonjeon-agent"
              target="_blank"
              rel="noreferrer noopener"
            >
              → GitHub 저장소
            </a>
          </p>
        </section>

        <section className="landing-section landing-closing">
          <p className="landing-row-body landing-made">
            먼저 리뷰 {PUBLISHED_REVIEWS}편을 읽어보고 판단해도 됩니다. 바로 시작하려면 검색부터.
          </p>
          <button type="button" className="landing-cta" onClick={() => navigate('/')}>
            논문 검색하러 가기
          </button>
        </section>
      </div>
    </div>
  );
}

export default LandingSections;
