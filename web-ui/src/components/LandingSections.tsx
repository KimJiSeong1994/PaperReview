import { useState } from 'react';
import { Link } from 'react-router-dom';
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
        aria-label={copied ? 'Copied to clipboard' : `Copy “${text}”`}
      >
        {copied ? 'Copied' : 'Copy'}
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
  return (
    <div className="landing">
      <section className="landing-section" id="difference">
        <SectionHeading
          kicker="Why Jiphyeonjeon"
          title="From first search to next read, in one place"
          body="Find papers, compare them, inspect the source, and decide what deserves your attention next without rebuilding context in another tool."
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
          title="Take one question through four research stages"
          body="Each stage carries the question and selected papers forward, so you do not have to explain the same context every time the task changes."
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
          title="See how a claim connects to its source"
          body="Jiphyeonjeon does more than produce a summary. It checks whether the review’s important interpretations stay within what the paper actually supports."
        />

        <article className="landing-evidence-example" aria-labelledby="evidence-example-title">
          <div className="landing-evidence-head">
            <p className="landing-evidence-kicker">Evidence check from a public review</p>
            <p className="landing-evidence-paper">{EVIDENCE_EXAMPLE.paper}</p>
          </div>
          <div className="landing-evidence-grid">
            <div className="landing-evidence-cell">
              <p className="landing-evidence-label">Review claim</p>
              <h3 id="evidence-example-title">{EVIDENCE_EXAMPLE.claim}</h3>
            </div>
            <div className="landing-evidence-cell">
              <p className="landing-evidence-label">Source check</p>
              <p>{EVIDENCE_EXAMPLE.sourceCheck}</p>
            </div>
          </div>
          <div className="landing-evidence-verdict">
            <span>Verdict</span>
            <p>{EVIDENCE_EXAMPLE.verdict}</p>
          </div>
          <Link className="landing-link" to={EVIDENCE_EXAMPLE.to}>→ Read the full evidence review</Link>
        </article>

        <h3 className="landing-sub-title landing-output-sub-title">Public work</h3>
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
          Browse all public reviews →
        </Link>
      </section>

      <section className="landing-section" id="capabilities">
        <SectionHeading
          kicker="Capabilities"
          title="Everything you need to find, read, and retain"
          body="Move from discovery to comparison, source checking, notes, and follow-up reading in one research workspace."
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
            <p className="landing-try-label">Try it in search</p>
            <p className="landing-try-copy">Choose an example query to open the main search page and start exploring.</p>
          </div>
          <ul className="landing-chips" aria-label="Example search queries">
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

      <section className="landing-section" id="faq">
        <SectionHeading
          kicker="Frequently asked questions"
          title="Questions about AI paper search and review"
          body="Understand what Jiphyeonjeon searches, how it verifies an AI review, and what is available before and after sign-in."
        />
        <dl className="landing-faq-list">
          {FAQ_ITEMS.map(item => (
            <div className="landing-faq-item" key={item.question}>
              <dt>{item.question}</dt>
              <dd>{item.answer}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="landing-section landing-claude" id="claude" tabIndex={-1}>
        <SectionHeading
          kicker="Optional Claude extension"
          title="Bring your Jiphyeonjeon workflow into Claude"
          body={`Jiphyeonjeon Agent is an optional open-source extension installed separately from the web app. Its ${MCP_TOOL_COUNT} MCP tools and ${RESEARCH_SKILL_COUNT} research skills bring search, review, bookmarks, and curricula into a Claude conversation.`}
        />

        <div className="landing-install">
          <div className="landing-install-copy">
            <p className="landing-install-label">Install the separate Agent to use Jiphyeonjeon in Claude.</p>
            <p className="landing-install-note">The setup covers Jiphyeonjeon sign-in, MCP registration, and research skills.</p>
          </div>
          <CopySnippet text="Install the Jiphyeonjeon agent" />

          <details className="landing-details">
            <summary className="landing-summary">Install from the terminal</summary>
            <CopySnippet text={GIT_INSTALL} />
          </details>
        </div>

        <h3 className="landing-sub-title">Core research skills</h3>
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
          <summary className="landing-summary">View all MCP tools ({MCP_TOOL_COUNT})</summary>
          <div className="landing-table-wrap">
            <table className="landing-tool-table">
              <thead className="landing-sr-only">
                <tr><th scope="col">Tool</th><th scope="col">Description</th></tr>
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
          After installation, open <code className="landing-code">/mcp</code> in Claude Code
          and confirm that jiphyeonjeon appears as Connected.
        </p>
        <p className="landing-row-links">
          <a className="landing-link" href="https://github.com/KimJiSeong1994/jiphyeonjeon-agent" target="_blank" rel="noreferrer noopener">
            → Agent GitHub repository
          </a>
          <Link className="landing-link" to="/blog/jiphyeonjeon-agent-mcp-tool-surface-a7c9e3d4b821">
            → How the MCP tool surface was designed
          </Link>
        </p>
      </section>

      <section className="landing-section landing-closing">
        <p className="landing-section-kicker">Start from evidence</p>
        <h2>Start with the question you care about</h2>
        <p>Search immediately, or read a public review first to see how Jiphyeonjeon handles papers and marks the evidence behind its claims.</p>
        <div className="landing-closing-actions">
          <Link className="landing-cta" to="/">Search papers</Link>
          <Link className="landing-cta landing-cta--ghost" to="/blog/category/paper-review">Read public reviews</Link>
          <a className="landing-link landing-closing-link" href="#claude">View Claude extension ↑</a>
        </div>
      </section>
    </div>
  );
}

export default LandingSections;
