import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import '../home/HomeWorkspace.css';
import './ConversationPage.css';
import HomeComposer from '../home/HomeComposer';
import HomeSidebar from '../home/HomeSidebar';
import { rememberRecentSearch } from '../home/recentSearches';
import { createConversation } from '../../api/conversations';
import { useConversation, type ViewTurn } from '../../hooks/useConversation';
import type { Paper } from '../../types';
import ArtifactPanel, { type ArtifactTab } from './ArtifactPanel';
import ReviewBlock, { type CompletedReview } from './ReviewBlock';
import SearchResultsBlock from './SearchResultsBlock';
import {
  CITE_PREFIX,
  citationSources,
  degradedLabels,
  linkCitations,
  normalizeEmphasis,
  resultsOf,
  reviewBlockOf,
  searchBlockOf,
  splitLead,
  turnSummary,
} from './conversationBlocks';

const AVATAR_SRC = '/Jiphyeonjeon_llama.webp';
// The server's content for a turn a newer message cancelled.
const CANCELLED_CONTENT = '중단됨';
const keyOf = (paper: Paper): string => String(paper.result_key ?? paper.doc_id);

interface ConversationPageProps {
  id: string;
}

/** One saved conversation: thread with a follow-up composer, results in the artifact panel. */
function ConversationPage({ id }: ConversationPageProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [runOnLoad] = useState(() => Boolean((location.state as { run?: boolean } | null)?.run));
  const { conversation, turns, loadError, streaming, liveStatus, send, stop, retry, reload } = useConversation(id, runOnLoad);

  // Which turn's results the artifact shows (null = the latest), the selected paper in it,
  // and the reader's open/closed choice for the newest graph (a newer graph re-opens).
  // Keyed by turn seq, not query_hash: the same query asked twice is two results.
  const [activeSeq, setActiveSeq] = useState<number | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [artifactPref, setArtifactPref] = useState<{ graphSeq: number; open: boolean } | null>(null);
  const [tab, setTab] = useState<ArtifactTab>('graph');
  // Reviews that finished while this page was open (or settled on their first
  // poll after a reload), newest last; the 리뷰 tab shows the chosen or latest one.
  const [reviews, setReviews] = useState<CompletedReview[]>([]);
  const [reviewSession, setReviewSession] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickRef = useRef(true);

  // The run flag is one-shot: a reload of this entry must not re-run the turn.
  useEffect(() => {
    if (runOnLoad) navigate(location.pathname, { replace: true, state: null });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const results = useMemo(() => resultsOf(turns), [turns]);
  const citations = useMemo(() => citationSources(turns), [turns]);
  const active = results.find(entry => entry.seq === activeSeq) ?? results.at(-1) ?? null;
  const activeSearch = active?.search ?? null;
  const latestGraphSeq = results.filter(entry => entry.graph).at(-1)?.seq ?? -1;
  const artifactOpen = artifactPref && artifactPref.graphSeq === latestGraphSeq
    ? artifactPref.open
    : latestGraphSeq >= 0;
  const liveSeq = turns.find(turn => turn.id === 'live')?.seq;
  const graphPending = Boolean(streaming && active && active.seq === liveSeq);
  const selectedPaper = activeSearch?.papers.find(paper => keyOf(paper) === selectedKey) ?? null;

  const setArtifactOpen = (open: boolean) => setArtifactPref({ graphSeq: latestGraphSeq, open });
  const activeReview = reviews.find(review => review.sessionId === reviewSession) ?? reviews.at(-1) ?? null;

  const addReview = (review: CompletedReview) => setReviews(prev => [
    ...prev.filter(item => item.sessionId !== review.sessionId),
    review,
  ]);

  const openReport = (sessionId: string) => {
    setReviewSession(sessionId);
    setTab('review');
    setArtifactOpen(true);
  };

  const showInArtifact = (seq: number, paper: Paper | null, nextTab?: ArtifactTab) => {
    setActiveSeq(seq);
    setSelectedKey(paper ? keyOf(paper) : null);
    if (nextTab) setTab(nextTab);
    setArtifactOpen(true);
  };

  useEffect(() => {
    const box = scrollRef.current;
    if (box && stickRef.current) box.scrollTop = box.scrollHeight;
  }, [turns, liveStatus]);

  const ask = (query: string) => {
    rememberRecentSearch(query);
    createConversation(query)
      .then(created => navigate(`/c/${created.id}`, { state: { run: true } }))
      .catch(() => navigate(`/?q=${encodeURIComponent(query)}`));
  };

  const renderCitation = (turn: ViewTurn, href: string | undefined, children: ReactNode) => {
    const source = citations.get(turn.id);
    if (!href?.startsWith(CITE_PREFIX)) {
      return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
    }
    const n = Number(href.slice(CITE_PREFIX.length));
    const paper = source?.search.papers[n - 1];
    if (!source || !paper) return <span>[{n}]</span>;
    return (
      <button type="button" className="conv-cite" title={paper.title} onClick={() => showInArtifact(source.seq, paper)}>
        {n}
      </button>
    );
  };

  const lastTurn = turns.at(-1);

  const renderAssistant = (turn: ViewTurn) => {
    const live = turn.id === 'live';
    const search = searchBlockOf(turn);
    const review = reviewBlockOf(turn);
    const summary = turnSummary(turn);
    const isLast = turn === lastTurn;
    const serverCancelled = turn.status === 'error' && turn.content.trim() === CANCELLED_CONTENT;
    // Search turns: lead paragraph, status, results, then the summary. Chat and
    // clarify turns stream text only and show no status line.
    const { lead, rest } = splitLead(serverCancelled ? '' : turn.content, Boolean(search || review) || Boolean(turn.statusSeen), turn.leadLength);
    const showLiveStatus = live && turn.status === 'running'
      && (Boolean(turn.statusSeen) || (!turn.content && turn.blocks.length === 0));
    const markdown = (text: string) => text && (
      <div className="conv-markdown">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{ a: ({ href, children }) => renderCitation(turn, href, children) }}
        >
          {linkCitations(normalizeEmphasis(text))}
        </ReactMarkdown>
      </div>
    );
    return (
      <li key={turn.id} className="conv-turn is-assistant">
        <div className="conv-assistant-head">
          <img className="conv-avatar" src={AVATAR_SRC} alt="" width="28" height="28" />
          <span className="conv-assistant-name">집현전</span>
        </div>
        {markdown(lead)}

        {showLiveStatus ? (
          <p className="conv-status is-live" role="status">
            <span className="conv-status-dot" aria-hidden="true" />
            {/* The router can stay silent for seconds before its first event. */}
            {liveStatus ?? '생각하는 중…'}
          </p>
        ) : summary && search && !(live && turn.status === 'running') ? (
          <details className="conv-status">
            <summary>{summary}</summary>
            <ul className="conv-status-detail">
              <li>검색어 · {search.executed_query || search.query}</li>
              {search.partial && <li>일부 출처가 늦어 결과가 덜 모였을 수 있어요.</li>}
              {degradedLabels(search.degraded ?? []).map(label => <li key={label}>{label}</li>)}
            </ul>
          </details>
        ) : summary && review && !(live && turn.status === 'running') ? (
          <p className="conv-status">{summary}</p>
        ) : null}

        {search && search.papers.length > 0 && (
          <SearchResultsBlock
            block={search}
            onSelect={paper => showInArtifact(turn.seq, paper)}
            onShowAll={() => showInArtifact(turn.seq, null, 'list')}
          />
        )}

        {review && <ReviewBlock block={review} onCompleted={addReview} onOpenReport={openReport} />}

        {markdown(rest)}

        {(turn.stopped || serverCancelled) && <p className="conv-note">중단됨</p>}
        {!live && turn.status === 'running' && (
          <p className="conv-note">
            답변을 마무리하는 중이에요.
            <button type="button" className="conv-link-btn" onClick={reload}>새로고침</button>
          </p>
        )}
        {turn.status === 'error' && !serverCancelled && (
          <div className="conv-error" role="alert">
            <span>{turn.error ?? '답변을 만들지 못했어요.'}</span>
            {isLast && !streaming && <button type="button" onClick={retry}>다시 시도</button>}
          </div>
        )}
      </li>
    );
  };

  return (
    <div className={`home-shell conv-shell${artifactOpen ? ' has-artifact' : ''}`}>
      <HomeSidebar onNew={() => navigate('/')} onAsk={ask} activeConversationId={id} activeConversationTitle={conversation?.title} />

      <main id="main" className="conv-main">
        <header className="conv-topbar">
          <h1 className="conv-title">{conversation?.title ?? (loadError ? '대화' : '불러오는 중…')}</h1>
          <button
            type="button"
            className={`conv-toggle${artifactOpen ? ' is-on' : ''}`}
            aria-pressed={artifactOpen}
            aria-controls={artifactOpen ? 'conv-artifact' : undefined}
            onClick={() => setArtifactOpen(!artifactOpen)}
          >
            <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16">
              <path d="M2.5 3h11v10h-11zM9.5 3v10" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
            </svg>
            아티팩트
          </button>
        </header>

        <div
          className="conv-scroll"
          ref={scrollRef}
          onScroll={event => {
            const box = event.currentTarget;
            stickRef.current = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
          }}
        >
          {loadError ? (
            <div className="conv-error conv-load-error" role="alert">
              <span>{loadError}</span>
              <button type="button" onClick={reload}>다시 불러오기</button>
              <button type="button" onClick={() => navigate('/')}>홈으로</button>
            </div>
          ) : !conversation ? (
            <div className="conv-skeleton" aria-busy="true" aria-label="대화를 불러오는 중">
              <span className="conv-skeleton-bubble" />
              <span className="conv-skeleton-line" />
              <span className="conv-skeleton-line is-short" />
            </div>
          ) : (
            <ol className="conv-thread">
              {turns.map(turn => (turn.role === 'user' ? (
                <li key={turn.id} className="conv-turn is-user">
                  <p className="conv-bubble">{turn.content}</p>
                </li>
              ) : renderAssistant(turn)))}
            </ol>
          )}
        </div>

        <div className="conv-composer">
          <HomeComposer
            variant="reply"
            initialQuery=""
            onSearch={message => { stickRef.current = true; send(message); }}
            guidanceMessage={null}
            guidanceSticky={false}
            onQueryChange={() => {}}
            busy={streaming || !conversation}
            onStop={streaming ? stop : undefined}
          />
          <p className="conv-disclaimer">AI 답변도 틀릴 수 있어요. 중요한 주장은 원문 근거를 한 번 더 확인해 주세요.</p>
        </div>
      </main>

      {artifactOpen && (
        <ArtifactPanel
          search={activeSearch}
          graph={active?.graph?.graph ?? null}
          graphPending={graphPending}
          review={activeReview}
          tab={tab}
          onTab={setTab}
          selectedPaper={selectedPaper}
          onSelect={paper => setSelectedKey(paper ? keyOf(paper) : null)}
          onClose={() => setArtifactOpen(false)}
        />
      )}
    </div>
  );
}

export default ConversationPage;
