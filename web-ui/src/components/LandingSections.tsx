import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { copyToClipboard } from '../utils/clipboard';
import './LandingSections.css';

interface LandingSectionsProps {
  onExampleSearch: (query: string) => void;
}

const SOURCE_COUNT = 6;
const RESEARCH_SKILL_COUNT = 6;

const GIT_INSTALL = [
  'git clone https://github.com/KimJiSeong1994/jiphyeonjeon-agent.git',
  'cd jiphyeonjeon-agent',
  'bash scripts/setup.sh',
].join('\n');

const EXAMPLE_QUERIES = [
  'graph neural networks',
  'LLM agent 논문',
  'retrieval augmented generation',
  '멀티모달 표현학습',
];

const DIFFERENCES = [
  {
    keyword: '검색 다음 단계',
    heading: '찾은 논문을 바로 다음 작업에 씁니다',
    body: '여러 소스에서 찾은 논문을 다시 옮겨 적을 필요가 없습니다. 고른 논문으로 딥리뷰를 만들고, 북마크에 남기거나 인용 그래프와 커리큘럼으로 넓힐 수 있습니다.',
    link: { to: '/', label: '논문 검색부터 시작하기' },
  },
  {
    keyword: '비교와 검증',
    heading: '논문 한 편보다, 논문 사이의 차이를 읽습니다',
    body: '각 논문은 따로 분석하고, 마지막에 공통점과 충돌, 방법론의 차이를 함께 정리합니다. 중요한 주장은 원문 구절과 다시 맞춰봅니다.',
    link: { to: '/blog/category/paper-review', label: '공개 리뷰에서 검토 방식 보기' },
  },
  {
    keyword: '공개 리뷰',
    heading: '가입하기 전에 결과부터 읽어보세요',
    body: '공개 리뷰에서 논문의 방법과 실험 결과뿐 아니라 한계와 적용 비용을 어떻게 다루는지도 확인할 수 있습니다.',
    link: { to: '/blog/category/paper-review', label: '공개 리뷰 읽기' },
  },
];

const WORKFLOW_STEPS = [
  {
    number: '01',
    label: 'Discover',
    title: '질문에 맞는 논문을 넓게 찾습니다',
    body: `질문에서 소스별 검색어를 만들고, 최대 ${SOURCE_COUNT}개 소스에서 찾은 결과의 중복을 걷어내 한 목록으로 정리합니다.`,
  },
  {
    number: '02',
    label: 'Review',
    title: '여러 논문을 나란히 읽습니다',
    body: '논문별로 분석한 뒤 공통점과 충돌, 방법론의 차이를 하나의 리뷰로 묶습니다.',
  },
  {
    number: '03',
    label: 'Verify',
    title: '중요한 주장을 원문에서 확인합니다',
    body: '주장을 뒷받침하는 구절을 원문에서 찾고, 직접 인용과 의역, 추론, 미확인을 구분해 표시합니다.',
  },
  {
    number: '04',
    label: 'Continue',
    title: '다음에 읽을 논문을 정합니다',
    body: '인용 관계를 따라 관련 연구를 찾거나, 확인한 논문으로 커리큘럼과 후속 읽기 목록을 만듭니다.',
  },
];

const CAPABILITIES = [
  {
    label: 'Research & Discovery',
    heading: '질문으로 찾고, 인용 관계로 넓힙니다',
    body: '질문에 맞춘 검색어로 여러 소스를 함께 살핍니다. 한 논문을 고르면 인용 관계를 최대 3단계까지 따라가며 관련 연구를 찾을 수 있습니다.',
    links: [
      { to: '/blog/search-agent-beyond-single-query-65bcbe5c30fd', label: '검색 에이전트 설계' },
      { to: '/blog/paper-network-graph-hidden-connections-f954b2866fb4', label: '논문 네트워크 그래프' },
    ],
  },
  {
    label: 'Analysis & Review',
    heading: '여러 편을 비교하고, 원문을 확인합니다',
    body: '논문별 분석을 하나의 딥리뷰로 묶습니다. 핵심 문장과 수식 설명을 살피고, 리뷰의 중요한 주장은 원문 구절과 대조할 수 있습니다.',
    links: [
      { to: '/blog/auto-highlight-ai-scholarly-annotation-f6a5ccb4ce6b', label: '오토하이라이트 설계' },
    ],
  },
  {
    label: 'Creation & Learning',
    heading: '읽은 내용을 남기고, 다음 읽기를 준비합니다',
    body: '로그인 후 리뷰와 메모를 북마크에 저장하고, 확인한 논문으로 커리큘럼과 후속 읽기 목록을 만듭니다. 방법론 다이어그램과 HTML 포스터도 만들 수 있습니다.',
    links: [
      { to: '/blog/curriculum-generator-jiphyeonjeon-9fdf6c688749', label: '커리큘럼 생성기' },
      { to: '/blog/daily-recommendations-research-persona-dailyrec2026', label: '일일 추천 설계' },
    ],
  },
];

const PUBLIC_OUTPUTS = [
  {
    type: 'Paper review',
    title: 'CausalRAG2: Hierarchical Causal Knowledge Graph Design for RAG',
    description: '방법과 실험 결과뿐 아니라 인과라는 표현을 어디까지 해석할 수 있는지 한계까지 검토합니다.',
    to: '/blog/causalrag2-hugrag-hierarchical-causal-gating',
  },
  {
    type: 'Paper review',
    title: 'HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models',
    description: '지식 그래프와 Personalized PageRank의 역할, 성능 주장, 비용 구조를 함께 읽습니다.',
    to: '/blog/hipporag-neurobiologically-inspired-long-term-memory',
  },
  {
    type: 'Engineering note',
    title: '집현전 검색 에이전트: 단일 쿼리의 한계를 넘어서',
    description: '병렬 검색에서 멀티턴 보완 검색까지, 실제 제품이 어떤 판단을 하는지 설명합니다.',
    to: '/blog/search-agent-beyond-single-query-65bcbe5c30fd',
  },
];

const EVIDENCE_EXAMPLE = {
  paper: 'CausalRAG2 · arXiv:2602.05143v2',
  claim: '논문이 말하는 “인과 게이트”는 검증된 방향성 인과 간선이 아니라, 검색 경로를 여는 무방향 이진 연결입니다.',
  sourceCheck: '원문 방법과 알고리즘을 대조하면 게이트에는 방향과 효과 크기가 없고, LLM이 인과 또는 논리적 의존성을 판정합니다.',
  verdict: '원문이 뒷받침하는 범위로 해석을 제한했습니다.',
  to: '/blog/causalrag2-hugrag-hierarchical-causal-gating',
};

const SKILL_MAP = [
  {
    situation: '논문 하나를 깊게 읽고 싶다',
    skill: 'jh-review-paper',
    prompt: 'arXiv ID 또는 논문 제목으로 딥리뷰해줘',
  },
  {
    situation: '오늘 무엇을 읽을지 정하고 싶다',
    skill: 'jh-daily-digest',
    prompt: '오늘 주제 기준으로 논문 브리핑 해줘',
  },
  {
    situation: '한 논문에서 관련 연구를 넓히고 싶다',
    skill: 'jh-explore',
    prompt: '선택한 논문에서 이어지는 관련 연구를 찾아줘',
  },
  {
    situation: '주제를 처음부터 순서대로 배우고 싶다',
    skill: 'jh-build-curriculum',
    prompt: '주제 기반 학습 커리큘럼을 짜줘',
  },
];

const MCP_TOOLS: [string, string][] = [
  ['search_papers', '현재 구성된 소스에서 논문을 검색합니다'],
  ['get_paper', '논문 한 편의 상세 정보를 가져옵니다'],
  ['start_review', '선택한 논문들의 딥리뷰를 시작합니다'],
  ['get_review_status', '진행 중인 리뷰의 상태를 확인합니다'],
  ['list_bookmarks', '저장한 북마크 목록을 불러옵니다'],
  ['add_bookmark', '논문을 북마크에 저장합니다'],
  ['remove_bookmark', '북마크를 삭제합니다'],
  ['create_curriculum', '주제에 맞는 학습 커리큘럼을 만듭니다'],
  ['explore_related', '인용 관계를 따라 관련 논문을 넓힙니다'],
  ['generate_figure', '방법론 텍스트를 SVG 다이어그램으로 바꿉니다'],
  ['create_blog_draft', '리뷰를 블로그 초안으로 옮깁니다 (관리자)'],
];

const MCP_TOOL_COUNT = MCP_TOOLS.length;

function CopySnippet({ text }: { text: string }) {
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
        onClick={handleCopy}
        aria-live="polite"
        aria-label={copied ? '클립보드에 복사했습니다' : `“${text}” 복사`}
      >
        {copied ? '복사됨' : '복사'}
      </button>
    </div>
  );
}

function SectionHeading({ kicker, title, body }: { kicker: string; title: string; body?: string }) {
  return (
    <header className="landing-section-header">
      <p className="landing-section-kicker">{kicker}</p>
      <h2 className="landing-section-title">{title}</h2>
      {body && <p className="landing-section-lead">{body}</p>}
    </header>
  );
}

function LandingSections({ onExampleSearch }: LandingSectionsProps) {
  const navigate = useNavigate();

  return (
    <div className="landing">
      <section className="landing-section" id="difference">
        <SectionHeading
          kicker="Why Jiphyeonjeon"
          title="검색부터 다음 읽기까지, 한곳에서"
          body="논문을 찾고 비교한 뒤 원문을 확인하고, 다음에 읽을 자료를 정하는 과정을 한곳에 모았습니다."
        />
        <div className="landing-differences">
          {DIFFERENCES.map((item, index) => (
            <article className="landing-difference" key={item.keyword}>
              <span className="landing-difference-number">0{index + 1}</span>
              <div>
                <p className="landing-row-keyword">{item.keyword}</p>
                <h3 className="landing-row-title">{item.heading}</h3>
                <p className="landing-row-body">{item.body}</p>
                <Link className="landing-link" to={item.link.to}>→ {item.link.label}</Link>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="landing-section" id="workflow">
        <SectionHeading
          kicker="Research flow"
          title="질문 하나를 네 단계로 풀어갑니다"
          body="앞 단계에서 고른 논문과 질문을 다음 단계에서 그대로 사용합니다. 도구가 바뀔 때마다 같은 맥락을 다시 설명할 필요가 없습니다."
        />
        <ol className="landing-workflow">
          {WORKFLOW_STEPS.map(step => (
            <li className="landing-step" key={step.number}>
              <div className="landing-step-marker">
                <span className="landing-step-num">{step.number}</span>
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

      <section className="landing-section" id="outputs">
        <SectionHeading
          kicker="Evidence in practice"
          title="주장과 원문이 어떻게 연결되는지 먼저 보세요"
          body="집현전은 요약문만 보여주지 않습니다. 리뷰의 중요한 해석이 원문이 말하는 범위를 벗어나지 않는지 다시 확인합니다."
        />

        <article className="landing-evidence-example" aria-labelledby="evidence-example-title">
          <div className="landing-evidence-head">
            <p className="landing-evidence-kicker">실제 공개 리뷰의 검토 예시</p>
            <p className="landing-evidence-paper">{EVIDENCE_EXAMPLE.paper}</p>
          </div>
          <div className="landing-evidence-grid">
            <div className="landing-evidence-cell">
              <p className="landing-evidence-label">리뷰 주장</p>
              <h3 id="evidence-example-title">{EVIDENCE_EXAMPLE.claim}</h3>
            </div>
            <div className="landing-evidence-cell">
              <p className="landing-evidence-label">원문 확인</p>
              <p>{EVIDENCE_EXAMPLE.sourceCheck}</p>
            </div>
          </div>
          <div className="landing-evidence-verdict">
            <span>판정</span>
            <p>{EVIDENCE_EXAMPLE.verdict}</p>
          </div>
          <Link className="landing-link" to={EVIDENCE_EXAMPLE.to}>→ 검토 과정이 담긴 리뷰 읽기</Link>
        </article>

        <h3 className="landing-sub-title landing-output-sub-title">공개 결과물</h3>
        <div className="landing-output-list">
          {PUBLIC_OUTPUTS.map(item => (
            <Link className="landing-output" to={item.to} key={item.to}>
              <span className="landing-output-type">{item.type}</span>
              <span className="landing-output-title">{item.title}</span>
              <span className="landing-output-description">{item.description}</span>
              <span className="landing-output-arrow" aria-hidden="true">↗</span>
            </Link>
          ))}
        </div>
        <Link className="landing-link landing-output-more" to="/blog/category/paper-review">
          공개 리뷰 전체 보기 →
        </Link>
      </section>

      <section className="landing-section" id="capabilities">
        <SectionHeading
          kicker="Capabilities"
          title="찾고, 읽고, 남기는 데 필요한 것들"
          body="논문을 찾는 일부터 비교와 원문 확인, 기록과 후속 읽기까지 한곳에서 할 수 있습니다."
        />
        <div className="landing-capability-grid">
          {CAPABILITIES.map(item => (
            <article className="landing-capability" key={item.label}>
              <p className="landing-capability-label">{item.label}</p>
              <h3>{item.heading}</h3>
              <p>{item.body}</p>
              <div className="landing-row-links">
                {item.links.map(link => (
                  <Link key={link.to} className="landing-link" to={link.to}>→ {link.label}</Link>
                ))}
              </div>
            </article>
          ))}
        </div>

        <div className="landing-try">
          <div>
            <p className="landing-try-label">검색으로 바로 확인하기</p>
            <p className="landing-try-copy">예시 질문을 선택하면 메인 검색 페이지로 이동해 바로 탐색합니다.</p>
          </div>
          <ul className="landing-chips" aria-label="예시 검색어">
            {EXAMPLE_QUERIES.map(query => (
              <li key={query}>
                <button type="button" className="landing-chip" onClick={() => onExampleSearch(query)}>
                  {query}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="landing-section landing-claude" id="claude" tabIndex={-1}>
        <SectionHeading
          kicker="Optional Claude extension"
          title="웹에서 하던 연구를 Claude로 확장합니다"
          body={`집현전 Agent는 웹 서비스와 별도로 설치하는 오픈소스 확장입니다. ${MCP_TOOL_COUNT}개 MCP 도구와 ${RESEARCH_SKILL_COUNT}개 연구 스킬을 통해 Claude 대화 안에서 집현전의 검색, 리뷰, 북마크와 커리큘럼 기능을 호출합니다.`}
        />

        <div className="landing-install">
          <div className="landing-install-copy">
            <p className="landing-install-label">Claude에서도 사용하려면 별도 Agent를 설치하세요.</p>
            <p className="landing-install-note">집현전 로그인, MCP 등록, 연구 스킬 설치 순서를 안내합니다.</p>
          </div>
          <CopySnippet text="집현전 agent 설치해줘" />

          <details className="landing-details">
            <summary className="landing-summary">터미널에서 직접 설치하기</summary>
            <CopySnippet text={GIT_INSTALL} />
          </details>
        </div>

        <h3 className="landing-sub-title">대표 연구 스킬</h3>
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

        <details className="landing-details landing-tool-details">
          <summary className="landing-summary">MCP 도구 전체 보기 ({MCP_TOOL_COUNT}개)</summary>
          <div className="landing-table-wrap">
            <table className="landing-tool-table">
              <thead className="landing-sr-only">
                <tr><th scope="col">도구</th><th scope="col">설명</th></tr>
              </thead>
              <tbody>
                {MCP_TOOLS.map(([name, description]) => (
                  <tr key={name}>
                    <td className="landing-tool-name">{name}</td>
                    <td className="landing-tool-desc">{description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>

        <p className="landing-mcp-outro">
          설치 후 Claude Code의 <code className="landing-code">/mcp</code> 화면에서
          jiphyeonjeon이 Connected로 표시되는지 확인하세요.
        </p>
        <p className="landing-row-links">
          <a className="landing-link" href="https://github.com/KimJiSeong1994/jiphyeonjeon-agent" target="_blank" rel="noreferrer noopener">
            → Agent GitHub 저장소
          </a>
          <Link className="landing-link" to="/blog/jiphyeonjeon-agent-mcp-tool-surface-a7c9e3d4b821">
            → MCP 도구 설계 이야기
          </Link>
        </p>
      </section>

      <section className="landing-section landing-closing">
        <p className="landing-section-kicker">Start from evidence</p>
        <h2>궁금한 주제부터 검색해보세요</h2>
        <p>검색은 바로 시작할 수 있습니다. 집현전이 논문을 읽고 근거를 표시하는 방식이 궁금하다면 공개 리뷰를 먼저 살펴보세요.</p>
        <div className="landing-closing-actions">
          <button type="button" className="landing-cta" onClick={() => navigate('/')}>논문 검색하기</button>
          <Link className="landing-cta landing-cta--ghost" to="/blog/category/paper-review">공개 리뷰 읽기</Link>
          <a className="landing-link landing-closing-link" href="#claude">Claude 확장 보기 ↑</a>
        </div>
      </section>
    </div>
  );
}

export default LandingSections;
