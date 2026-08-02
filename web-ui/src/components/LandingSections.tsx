import { useState } from 'react';
import { Link } from 'react-router-dom';
import { copyToClipboard } from '../utils/clipboard';
import './LandingSections.css';

interface LandingSectionsProps {
  onExampleSearch: (query: string) => void;
  locale?: 'en' | 'ko';
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
  'LLM agents',
  'retrieval augmented generation',
  'multimodal representation learning',
];

const DIFFERENCES = [
  {
    keyword: 'Beyond search',
    heading: 'Put every paper to work immediately',
    body: 'No exporting or re-entering results. Turn selected papers into a deep review, save them to bookmarks, or expand them into a citation graph and study curriculum.',
    link: { to: '/', label: 'Start with paper search' },
  },
  {
    keyword: 'Compare & verify',
    heading: 'Read the differences between papers',
    body: 'Analyze each paper on its own, then bring the shared findings, conflicts, and methodological differences into one review. Important claims are checked against source passages.',
    link: { to: '/blog/category/paper-review', label: 'See the method in public reviews' },
  },
  {
    keyword: 'Public reviews',
    heading: 'Read the output before you sign up',
    body: 'Public reviews show how Jiphyeonjeon handles a paper’s methods and results alongside its limitations and practical cost.',
    link: { to: '/blog/category/paper-review', label: 'Read public reviews' },
  },
];

const WORKFLOW_STEPS = [
  {
    number: '01',
    label: 'Discover',
    title: 'Search broadly for papers that fit the question',
    body: `Turn one question into source-specific queries, search up to ${SOURCE_COUNT} sources, remove duplicates, and bring the results into one list.`,
  },
  {
    number: '02',
    label: 'Review',
    title: 'Read several papers side by side',
    body: 'Analyze each paper, then combine the shared findings, conflicts, and methodological differences into one review.',
  },
  {
    number: '03',
    label: 'Verify',
    title: 'Check important claims against the source',
    body: 'Locate the supporting passage and label each claim as a direct quote, paraphrase, inference, or unverified.',
  },
  {
    number: '04',
    label: 'Continue',
    title: 'Choose what to read next',
    body: 'Follow citation relationships to related work, or turn verified papers into a curriculum and follow-up reading list.',
  },
];

const CAPABILITIES = [
  {
    label: 'Research & Discovery',
    heading: 'Search by question, expand by citation',
    body: 'Search several sources with queries tailored to your question. Select a paper, then follow citation relationships up to three levels to find related work.',
    links: [
      { to: '/blog/search-agent-beyond-single-query-65bcbe5c30fd', label: 'Search agent design' },
      { to: '/blog/paper-network-graph-hidden-connections-f954b2866fb4', label: 'Paper network graph' },
    ],
  },
  {
    label: 'Analysis & Review',
    heading: 'Compare papers and inspect the source',
    body: 'Combine paper-level analyses into one deep review. Inspect key passages and equation explanations, then compare important review claims with the source text.',
    links: [
      { to: '/blog/auto-highlight-ai-scholarly-annotation-f6a5ccb4ce6b', label: 'Auto-highlight design' },
    ],
  },
  {
    label: 'Creation & Learning',
    heading: 'Keep what you learn and prepare the next read',
    body: 'Sign in to save reviews and notes to bookmarks, build curricula and follow-up reading lists, or turn a methodology into a diagram and HTML poster.',
    links: [
      { to: '/blog/curriculum-generator-jiphyeonjeon-9fdf6c688749', label: 'Curriculum builder' },
      { to: '/blog/daily-recommendations-research-persona-dailyrec2026', label: 'Daily recommendation design' },
    ],
  },
];

const PUBLIC_OUTPUTS = [
  {
    type: 'Paper review',
    title: 'CausalRAG2: Hierarchical Causal Knowledge Graph Design for RAG',
    description: 'Reviews the method and results while testing how far the paper’s causal language can reasonably be interpreted.',
    to: '/blog/causalrag2-hugrag-hierarchical-causal-gating',
  },
  {
    type: 'Paper review',
    title: 'HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models',
    description: 'Examines the roles of the knowledge graph and Personalized PageRank alongside performance claims and cost.',
    to: '/blog/hipporag-neurobiologically-inspired-long-term-memory',
  },
  {
    type: 'Engineering note',
    title: 'Jiphyeonjeon Search Agent: Beyond a Single Query',
    description: 'Explains the product decisions behind parallel retrieval and multi-turn follow-up search.',
    to: '/blog/search-agent-beyond-single-query-65bcbe5c30fd',
  },
];

const EVIDENCE_EXAMPLE = {
  paper: 'CausalRAG2 · arXiv:2602.05143v2',
  claim: 'The paper’s “causal gate” is not a validated directed causal edge. It is an undirected binary connection that opens a retrieval path.',
  sourceCheck: 'The method and algorithm assign neither direction nor effect size to the gate; an LLM judges causal or logical dependence.',
  verdict: 'We limit the interpretation to what the source supports.',
  to: '/blog/causalrag2-hugrag-hierarchical-causal-gating',
};

const FAQ_ITEMS = [
  {
    question: 'What kind of AI paper search tool is Jiphyeonjeon?',
    answer: 'Jiphyeonjeon connects arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers, and Korean academic search. It carries one question from discovery through comparison, deep review, source checking, and follow-up reading.',
  },
  {
    question: 'How are claims in an AI paper review verified?',
    answer: 'For each important review claim, Jiphyeonjeon locates a supporting source passage. It distinguishes direct quotes, paraphrases, inferences, and unverified claims so the AI summary stays within what the paper actually says.',
  },
  {
    question: 'What can I use without signing in?',
    answer: 'You can search papers and read public reviews without an account. Sign in when you want to save reviews, notes, and bookmarks to a personal research space.',
  },
  {
    question: 'Who is Jiphyeonjeon for?',
    answer: 'It is designed for researchers and graduate students entering a new field, research engineers comparing methods, and readers who need to test a paper’s claims against its evidence.',
  },
];

const SKILL_MAP = [
  {
    situation: 'Read one paper in depth',
    skill: 'jh-review-paper',
    prompt: 'Deep-review this paper by arXiv ID or title',
  },
  {
    situation: 'Decide what to read today',
    skill: 'jh-daily-digest',
    prompt: 'Brief me on today’s papers for this topic',
  },
  {
    situation: 'Expand from one paper',
    skill: 'jh-explore',
    prompt: 'Find related work that follows from this paper',
  },
  {
    situation: 'Learn a topic in order',
    skill: 'jh-build-curriculum',
    prompt: 'Build a study curriculum for this topic',
  },
];

const MCP_TOOLS: [string, string][] = [
  ['search_papers', 'Search papers across the configured sources'],
  ['get_paper', 'Retrieve the details of one paper'],
  ['start_review', 'Start a deep review of selected papers'],
  ['get_review_status', 'Check the status of a review in progress'],
  ['list_bookmarks', 'List saved bookmarks'],
  ['add_bookmark', 'Save a paper to bookmarks'],
  ['remove_bookmark', 'Remove a bookmark'],
  ['create_curriculum', 'Build a study curriculum for a topic'],
  ['explore_related', 'Follow citations to related papers'],
  ['generate_figure', 'Turn methodology text into an SVG diagram'],
  ['create_blog_draft', 'Turn a review into a blog draft (admin)'],
];

const KO_TRANSLATIONS: Record<string, string> = {
  'graph neural networks': '그래프 신경망',
  'LLM agents': 'LLM 에이전트 논문',
  'retrieval augmented generation': '검색 증강 생성',
  'multimodal representation learning': '멀티모달 표현학습',
  'Beyond search': '검색 다음 단계',
  'Put every paper to work immediately': '찾은 논문을 바로 다음 작업에 씁니다',
  'No exporting or re-entering results. Turn selected papers into a deep review, save them to bookmarks, or expand them into a citation graph and study curriculum.': '여러 소스에서 찾은 논문을 다시 옮겨 적을 필요가 없습니다. 고른 논문으로 딥리뷰를 만들고, 북마크에 남기거나 인용 그래프와 커리큘럼으로 넓힐 수 있습니다.',
  'Start with paper search': '논문 검색부터 시작하기',
  'Compare & verify': '비교와 검증',
  'Read the differences between papers': '논문 한 편보다, 논문 사이의 차이를 읽습니다',
  'Analyze each paper on its own, then bring the shared findings, conflicts, and methodological differences into one review. Important claims are checked against source passages.': '각 논문은 따로 분석하고, 마지막에 공통점과 충돌, 방법론의 차이를 함께 정리합니다. 중요한 주장은 원문 구절과 다시 맞춰봅니다.',
  'See the method in public reviews': '공개 리뷰에서 검토 방식 보기',
  'Public reviews': '공개 리뷰',
  'Read the output before you sign up': '가입하기 전에 결과부터 읽어보세요',
  'Public reviews show how Jiphyeonjeon handles a paper’s methods and results alongside its limitations and practical cost.': '공개 리뷰에서 논문의 방법과 실험 결과뿐 아니라 한계와 적용 비용을 어떻게 다루는지도 확인할 수 있습니다.',
  'Read public reviews': '공개 리뷰 읽기',
  'Discover': '탐색',
  'Search broadly for papers that fit the question': '질문에 맞는 논문을 넓게 찾습니다',
  'Turn one question into source-specific queries, search up to 6 sources, remove duplicates, and bring the results into one list.': '질문에서 소스별 검색어를 만들고, 최대 6개 소스에서 찾은 결과의 중복을 걷어내 한 목록으로 정리합니다.',
  'Review': '리뷰',
  'Read several papers side by side': '여러 논문을 나란히 읽습니다',
  'Analyze each paper, then combine the shared findings, conflicts, and methodological differences into one review.': '논문별로 분석한 뒤 공통점과 충돌, 방법론의 차이를 하나의 리뷰로 묶습니다.',
  'Verify': '검증',
  'Check important claims against the source': '중요한 주장을 원문에서 확인합니다',
  'Locate the supporting passage and label each claim as a direct quote, paraphrase, inference, or unverified.': '주장을 뒷받침하는 구절을 원문에서 찾고, 직접 인용과 의역, 추론, 미확인을 구분해 표시합니다.',
  'Continue': '다음 읽기',
  'Choose what to read next': '다음에 읽을 논문을 정합니다',
  'Follow citation relationships to related work, or turn verified papers into a curriculum and follow-up reading list.': '인용 관계를 따라 관련 연구를 찾거나, 확인한 논문으로 커리큘럼과 후속 읽기 목록을 만듭니다.',
  'Research & Discovery': '탐색과 발견',
  'Search by question, expand by citation': '질문으로 찾고, 인용 관계로 넓힙니다',
  'Search several sources with queries tailored to your question. Select a paper, then follow citation relationships up to three levels to find related work.': '질문에 맞춘 검색어로 여러 소스를 함께 살핍니다. 한 논문을 고르면 인용 관계를 최대 3단계까지 따라가며 관련 연구를 찾을 수 있습니다.',
  'Search agent design': '검색 에이전트 설계',
  'Paper network graph': '논문 네트워크 그래프',
  'Analysis & Review': '분석과 리뷰',
  'Compare papers and inspect the source': '여러 편을 비교하고, 원문을 확인합니다',
  'Combine paper-level analyses into one deep review. Inspect key passages and equation explanations, then compare important review claims with the source text.': '논문별 분석을 하나의 딥리뷰로 묶습니다. 핵심 문장과 수식 설명을 살피고, 리뷰의 중요한 주장은 원문 구절과 대조할 수 있습니다.',
  'Auto-highlight design': '오토하이라이트 설계',
  'Creation & Learning': '기록과 학습',
  'Keep what you learn and prepare the next read': '읽은 내용을 남기고, 다음 읽기를 준비합니다',
  'Sign in to save reviews and notes to bookmarks, build curricula and follow-up reading lists, or turn a methodology into a diagram and HTML poster.': '로그인 후 리뷰와 메모를 북마크에 저장하고, 확인한 논문으로 커리큘럼과 후속 읽기 목록을 만듭니다. 방법론 다이어그램과 HTML 포스터도 만들 수 있습니다.',
  'Curriculum builder': '커리큘럼 생성기',
  'Daily recommendation design': '일일 추천 설계',
  'Paper review': '논문 리뷰',
  'Reviews the method and results while testing how far the paper’s causal language can reasonably be interpreted.': '방법과 실험 결과뿐 아니라 인과라는 표현을 어디까지 해석할 수 있는지 한계까지 검토합니다.',
  'Examines the roles of the knowledge graph and Personalized PageRank alongside performance claims and cost.': '지식 그래프와 Personalized PageRank의 역할, 성능 주장, 비용 구조를 함께 읽습니다.',
  'Engineering note': '엔지니어링 노트',
  'Jiphyeonjeon Search Agent: Beyond a Single Query': '집현전 검색 에이전트: 단일 쿼리의 한계를 넘어서',
  'Explains the product decisions behind parallel retrieval and multi-turn follow-up search.': '병렬 검색에서 멀티턴 보완 검색까지, 실제 제품이 어떤 판단을 하는지 설명합니다.',
  'The paper’s “causal gate” is not a validated directed causal edge. It is an undirected binary connection that opens a retrieval path.': '논문이 말하는 “인과 게이트”는 검증된 방향성 인과 간선이 아니라, 검색 경로를 여는 무방향 이진 연결입니다.',
  'The method and algorithm assign neither direction nor effect size to the gate; an LLM judges causal or logical dependence.': '원문 방법과 알고리즘을 대조하면 게이트에는 방향과 효과 크기가 없고, LLM이 인과 또는 논리적 의존성을 판정합니다.',
  'We limit the interpretation to what the source supports.': '원문이 뒷받침하는 범위로 해석을 제한했습니다.',
  'What kind of AI paper search tool is Jiphyeonjeon?': '집현전은 어떤 AI 논문 검색 도구인가요?',
  'Jiphyeonjeon connects arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers, and Korean academic search. It carries one question from discovery through comparison, deep review, source checking, and follow-up reading.': '집현전은 arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers와 국내 논문 검색을 한곳에서 연결합니다. 질문에 맞는 논문을 찾은 뒤 비교, 딥리뷰, 원문 근거 확인과 다음 읽기까지 이어갑니다.',
  'How are claims in an AI paper review verified?': 'AI 논문 리뷰의 주장은 어떻게 검증하나요?',
  'For each important review claim, Jiphyeonjeon locates a supporting source passage. It distinguishes direct quotes, paraphrases, inferences, and unverified claims so the AI summary stays within what the paper actually says.': '리뷰의 중요한 주장마다 이를 뒷받침하는 원문 구절을 찾습니다. 직접 인용, 의역, 추론, 미확인을 구분해 AI 요약이 논문이 말하는 범위를 벗어나지 않는지 확인합니다.',
  'What can I use without signing in?': '로그인 없이 무엇을 사용할 수 있나요?',
  'You can search papers and read public reviews without an account. Sign in when you want to save reviews, notes, and bookmarks to a personal research space.': '논문 검색과 공개된 논문 리뷰 읽기는 로그인 없이 시작할 수 있습니다. 리뷰, 메모와 북마크를 개인 연구 공간에 저장하는 기능은 로그인 후 이용합니다.',
  'Who is Jiphyeonjeon for?': '누구에게 적합한 연구 도구인가요?',
  'It is designed for researchers and graduate students entering a new field, research engineers comparing methods, and readers who need to test a paper’s claims against its evidence.': '새 주제의 핵심 논문을 찾는 연구자와 대학원생, 여러 방법론을 비교하는 리서치 엔지니어, 논문의 주장과 실제 근거를 빠르게 대조해야 하는 독자에게 적합합니다.',
  'Read one paper in depth': '논문 하나를 깊게 읽고 싶다',
  'Deep-review this paper by arXiv ID or title': 'arXiv ID 또는 논문 제목으로 딥리뷰해줘',
  'Decide what to read today': '오늘 무엇을 읽을지 정하고 싶다',
  'Brief me on today’s papers for this topic': '오늘 주제 기준으로 논문 브리핑 해줘',
  'Expand from one paper': '한 논문에서 관련 연구를 넓히고 싶다',
  'Find related work that follows from this paper': '선택한 논문에서 이어지는 관련 연구를 찾아줘',
  'Learn a topic in order': '주제를 처음부터 순서대로 배우고 싶다',
  'Build a study curriculum for this topic': '주제 기반 학습 커리큘럼을 짜줘',
  'Search papers across the configured sources': '현재 구성된 소스에서 논문을 검색합니다',
  'Retrieve the details of one paper': '논문 한 편의 상세 정보를 가져옵니다',
  'Start a deep review of selected papers': '선택한 논문들의 딥리뷰를 시작합니다',
  'Check the status of a review in progress': '진행 중인 리뷰의 상태를 확인합니다',
  'List saved bookmarks': '저장한 북마크 목록을 불러옵니다',
  'Save a paper to bookmarks': '논문을 북마크에 저장합니다',
  'Remove a bookmark': '북마크를 삭제합니다',
  'Build a study curriculum for a topic': '주제에 맞는 학습 커리큘럼을 만듭니다',
  'Follow citations to related papers': '인용 관계를 따라 관련 논문을 넓힙니다',
  'Turn methodology text into an SVG diagram': '방법론 텍스트를 SVG 다이어그램으로 바꿉니다',
  'Turn a review into a blog draft (admin)': '리뷰를 블로그 초안으로 옮깁니다 (관리자)',
};

const MCP_TOOL_COUNT = MCP_TOOLS.length;

function CopySnippet({ text, locale }: { text: string; locale: 'en' | 'ko' }) {
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
      <p className="landing-section-kicker">{kicker}</p>
      <h2 className="landing-section-title">{title}</h2>
      {body && <p className="landing-section-lead">{body}</p>}
    </header>
  );
}

function LandingSections({ onExampleSearch, locale = 'en' }: LandingSectionsProps) {
  const t = (text: string) => locale === 'ko' ? (KO_TRANSLATIONS[text] ?? text) : text;

  return (
    <div className="landing">
      <section className="landing-section" id="difference">
        <SectionHeading
          kicker={locale === 'ko' ? '집현전이 다른 점' : 'Why Jiphyeonjeon'}
          title={locale === 'ko' ? '검색부터 다음 읽기까지, 한곳에서' : 'From first search to next read, in one place'}
          body={locale === 'ko' ? '논문을 찾고 비교한 뒤 원문을 확인하고, 다음에 읽을 자료를 정하는 과정을 한곳에 모았습니다.' : 'Find papers, compare them, inspect the source, and decide what deserves your attention next without rebuilding context in another tool.'}
        />
        <div className="landing-differences">
          {DIFFERENCES.map((item, index) => (
            <article className="landing-difference" key={item.keyword}>
              <span className="landing-difference-number">0{index + 1}</span>
              <div>
                <p className="landing-row-keyword">{t(item.keyword)}</p>
                <h3 className="landing-row-title">{t(item.heading)}</h3>
                <p className="landing-row-body">{t(item.body)}</p>
                <Link className="landing-link" to={item.link.to}>→ {t(item.link.label)}</Link>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="landing-section" id="workflow">
        <SectionHeading
          kicker={locale === 'ko' ? '연구 흐름' : 'Research flow'}
          title={locale === 'ko' ? '질문 하나를 네 단계로 풀어갑니다' : 'Take one question through four research stages'}
          body={locale === 'ko' ? '앞 단계에서 고른 논문과 질문을 다음 단계에서 그대로 사용합니다. 도구가 바뀔 때마다 같은 맥락을 다시 설명할 필요가 없습니다.' : 'Each stage carries the question and selected papers forward, so you do not have to explain the same context every time the task changes.'}
        />
        <ol className="landing-workflow">
          {WORKFLOW_STEPS.map(step => (
            <li className="landing-step" key={step.number}>
              <div className="landing-step-marker">
                <span className="landing-step-num">{step.number}</span>
                <span className="landing-step-label">{t(step.label)}</span>
              </div>
              <div className="landing-step-text">
                <h3 className="landing-step-title">{t(step.title)}</h3>
                <p className="landing-step-body">{t(step.body)}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="landing-section" id="outputs">
        <SectionHeading
          kicker={locale === 'ko' ? '실제 근거 확인' : 'Evidence in practice'}
          title={locale === 'ko' ? '주장과 원문이 어떻게 연결되는지 먼저 보세요' : 'See how a claim connects to its source'}
          body={locale === 'ko' ? '집현전은 요약문만 보여주지 않습니다. 리뷰의 중요한 해석이 원문이 말하는 범위를 벗어나지 않는지 다시 확인합니다.' : 'Jiphyeonjeon does more than produce a summary. It checks whether the review’s important interpretations stay within what the paper actually supports.'}
        />

        <article className="landing-evidence-example" aria-labelledby="evidence-example-title">
          <div className="landing-evidence-head">
            <p className="landing-evidence-kicker">{locale === 'ko' ? '실제 공개 리뷰의 검토 예시' : 'Evidence check from a public review'}</p>
            <p className="landing-evidence-paper">{EVIDENCE_EXAMPLE.paper}</p>
          </div>
          <div className="landing-evidence-grid">
            <div className="landing-evidence-cell">
              <p className="landing-evidence-label">{locale === 'ko' ? '리뷰 주장' : 'Review claim'}</p>
              <h3 id="evidence-example-title">{t(EVIDENCE_EXAMPLE.claim)}</h3>
            </div>
            <div className="landing-evidence-cell">
              <p className="landing-evidence-label">{locale === 'ko' ? '원문 확인' : 'Source check'}</p>
              <p>{t(EVIDENCE_EXAMPLE.sourceCheck)}</p>
            </div>
          </div>
          <div className="landing-evidence-verdict">
            <span>{locale === 'ko' ? '판정' : 'Verdict'}</span>
            <p>{t(EVIDENCE_EXAMPLE.verdict)}</p>
          </div>
          <Link className="landing-link" to={EVIDENCE_EXAMPLE.to}>→ {locale === 'ko' ? '검토 과정이 담긴 리뷰 읽기' : 'Read the full evidence review'}</Link>
        </article>

        <h3 className="landing-sub-title landing-output-sub-title">{locale === 'ko' ? '공개 결과물' : 'Public work'}</h3>
        <div className="landing-output-list">
          {PUBLIC_OUTPUTS.map(item => (
            <Link className="landing-output" to={item.to} key={item.to}>
              <span className="landing-output-type">{t(item.type)}</span>
              <span className="landing-output-title">{t(item.title)}</span>
              <span className="landing-output-description">{t(item.description)}</span>
              <span className="landing-output-arrow" aria-hidden="true">↗</span>
            </Link>
          ))}
        </div>
        <Link className="landing-link landing-output-more" to="/blog/category/paper-review">
          {locale === 'ko' ? '공개 리뷰 전체 보기' : 'Browse all public reviews'} →
        </Link>
      </section>

      <section className="landing-section" id="capabilities">
        <SectionHeading
          kicker={locale === 'ko' ? '주요 기능' : 'Capabilities'}
          title={locale === 'ko' ? '찾고, 읽고, 남기는 데 필요한 것들' : 'Everything you need to find, read, and retain'}
          body={locale === 'ko' ? '논문을 찾는 일부터 비교와 원문 확인, 기록과 후속 읽기까지 한곳에서 할 수 있습니다.' : 'Move from discovery to comparison, source checking, notes, and follow-up reading in one research workspace.'}
        />
        <div className="landing-capability-grid">
          {CAPABILITIES.map(item => (
            <article className="landing-capability" key={item.label}>
              <p className="landing-capability-label">{t(item.label)}</p>
              <h3>{t(item.heading)}</h3>
              <p>{t(item.body)}</p>
              <div className="landing-row-links">
                {item.links.map(link => (
                  <Link key={link.to} className="landing-link" to={link.to}>→ {t(link.label)}</Link>
                ))}
              </div>
            </article>
          ))}
        </div>

        <div className="landing-try">
          <div>
            <p className="landing-try-label">{locale === 'ko' ? '검색으로 바로 확인하기' : 'Try it in search'}</p>
            <p className="landing-try-copy">{locale === 'ko' ? '예시 질문을 선택하면 메인 검색 페이지로 이동해 바로 탐색합니다.' : 'Choose an example query to open the main search page and start exploring.'}</p>
          </div>
          <ul className="landing-chips" aria-label={locale === 'ko' ? '예시 검색어' : 'Example search queries'}>
            {EXAMPLE_QUERIES.map(query => (
              <li key={query}>
                <button type="button" className="landing-chip" onClick={() => onExampleSearch(t(query))}>
                  {t(query)}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="landing-section" id="faq">
        <SectionHeading
          kicker={locale === 'ko' ? '자주 묻는 질문' : 'Frequently asked questions'}
          title={locale === 'ko' ? 'AI 논문 검색과 리뷰, 자주 묻는 질문' : 'Questions about AI paper search and review'}
          body={locale === 'ko' ? '집현전이 찾는 자료의 범위와 AI 리뷰의 검증 방식, 로그인 전후 이용 범위를 먼저 확인하세요.' : 'Understand what Jiphyeonjeon searches, how it verifies an AI review, and what is available before and after sign-in.'}
        />
        <dl className="landing-faq-list">
          {FAQ_ITEMS.map(item => (
            <div className="landing-faq-item" key={item.question}>
              <dt>{t(item.question)}</dt>
              <dd>{t(item.answer)}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="landing-section landing-claude" id="claude" tabIndex={-1}>
        <SectionHeading
          kicker={locale === 'ko' ? '선택형 Claude 확장' : 'Optional Claude extension'}
          title={locale === 'ko' ? '웹에서 하던 연구를 Claude로 확장합니다' : 'Bring your Jiphyeonjeon workflow into Claude'}
          body={locale === 'ko'
            ? `집현전 Agent는 웹 서비스와 별도로 설치하는 오픈소스 확장입니다. ${MCP_TOOL_COUNT}개 MCP 도구와 ${RESEARCH_SKILL_COUNT}개 연구 스킬을 통해 Claude 대화 안에서 집현전의 검색, 리뷰, 북마크와 커리큘럼 기능을 호출합니다.`
            : `Jiphyeonjeon Agent is an optional open-source extension installed separately from the web app. Its ${MCP_TOOL_COUNT} MCP tools and ${RESEARCH_SKILL_COUNT} research skills bring search, review, bookmarks, and curricula into a Claude conversation.`}
        />

        <div className="landing-install">
          <div className="landing-install-copy">
            <p className="landing-install-label">{locale === 'ko' ? 'Claude에서도 사용하려면 별도 Agent를 설치하세요.' : 'Install the separate Agent to use Jiphyeonjeon in Claude.'}</p>
            <p className="landing-install-note">{locale === 'ko' ? '집현전 로그인, MCP 등록, 연구 스킬 설치 순서를 안내합니다.' : 'The setup covers Jiphyeonjeon sign-in, MCP registration, and research skills.'}</p>
          </div>
          <CopySnippet locale={locale} text={locale === 'ko' ? '집현전 agent 설치해줘' : 'Install the Jiphyeonjeon agent'} />

          <details className="landing-details">
            <summary className="landing-summary">{locale === 'ko' ? '터미널에서 직접 설치하기' : 'Install from the terminal'}</summary>
            <CopySnippet locale={locale} text={GIT_INSTALL} />
          </details>
        </div>

        <h3 className="landing-sub-title">{locale === 'ko' ? '대표 연구 스킬' : 'Core research skills'}</h3>
        <ul className="landing-skill-map">
          {SKILL_MAP.map(item => (
            <li className="landing-skill" key={item.skill}>
              <div className="landing-skill-head">
                <span className="landing-skill-situation">{t(item.situation)}</span>
                <code className="landing-skill-name">{item.skill}</code>
              </div>
              <CopySnippet locale={locale} text={t(item.prompt)} />
            </li>
          ))}
        </ul>

        <details className="landing-details landing-tool-details">
          <summary className="landing-summary">{locale === 'ko' ? `MCP 도구 전체 보기 (${MCP_TOOL_COUNT}개)` : `View all MCP tools (${MCP_TOOL_COUNT})`}</summary>
          <div className="landing-table-wrap">
            <table className="landing-tool-table">
              <thead className="landing-sr-only">
                <tr><th scope="col">{locale === 'ko' ? '도구' : 'Tool'}</th><th scope="col">{locale === 'ko' ? '설명' : 'Description'}</th></tr>
              </thead>
              <tbody>
                {MCP_TOOLS.map(([name, description]) => (
                  <tr key={name}>
                    <td className="landing-tool-name">{name}</td>
                    <td className="landing-tool-desc">{t(description)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>

        <p className="landing-mcp-outro">
          {locale === 'ko' ? '설치 후 Claude Code의 ' : 'After installation, open '}
          <code className="landing-code">/mcp</code>
          {locale === 'ko' ? ' 화면에서 jiphyeonjeon이 Connected로 표시되는지 확인하세요.' : ' in Claude Code and confirm that jiphyeonjeon appears as Connected.'}
        </p>
        <p className="landing-row-links">
          <a className="landing-link" href="https://github.com/KimJiSeong1994/jiphyeonjeon-agent" target="_blank" rel="noreferrer noopener">
            → {locale === 'ko' ? 'Agent GitHub 저장소' : 'Agent GitHub repository'}
          </a>
          <Link className="landing-link" to="/blog/jiphyeonjeon-agent-mcp-tool-surface-a7c9e3d4b821">
            → {locale === 'ko' ? 'MCP 도구 설계 이야기' : 'How the MCP tool surface was designed'}
          </Link>
        </p>
      </section>

      <section className="landing-section landing-closing">
        <p className="landing-section-kicker">{locale === 'ko' ? '근거에서 시작하기' : 'Start from evidence'}</p>
        <h2>{locale === 'ko' ? '궁금한 주제부터 검색해보세요' : 'Start with the question you care about'}</h2>
        <p>{locale === 'ko' ? '검색은 바로 시작할 수 있습니다. 집현전이 논문을 읽고 근거를 표시하는 방식이 궁금하다면 공개 리뷰를 먼저 살펴보세요.' : 'Search immediately, or read a public review first to see how Jiphyeonjeon handles papers and marks the evidence behind its claims.'}</p>
        <div className="landing-closing-actions">
          <Link className="landing-cta" to="/">{locale === 'ko' ? '논문 검색하기' : 'Search papers'}</Link>
          <Link className="landing-cta landing-cta--ghost" to="/blog/category/paper-review">{locale === 'ko' ? '공개 리뷰 읽기' : 'Read public reviews'}</Link>
          <a className="landing-link landing-closing-link" href="#claude">{locale === 'ko' ? 'Claude 확장 보기' : 'View Claude extension'} ↑</a>
        </div>
      </section>
    </div>
  );
}

export default LandingSections;
