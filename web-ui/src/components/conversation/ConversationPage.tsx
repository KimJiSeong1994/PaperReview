import {
  createContext,
  Fragment,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FocusEvent as ReactFocusEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import '../home/HomeWorkspace.css';
import './ConversationPage.css';
import HomeComposer from '../home/HomeComposer';
import HomeSidebar from '../home/HomeSidebar';
import MascotFace from '../home/MascotFace';
import { rememberRecentSearch } from '../home/recentSearches';
import { createConversation } from '../../api/conversations';
import { useConversation, type ViewTurn } from '../../hooks/useConversation';
import type { Paper } from '../../types';
import ArtifactPanel, { type ArtifactTab } from './ArtifactPanel';
import BookmarkRefsStrip from './BookmarkRefsStrip';
import CitedPapers from './CitedPapers';
import HighlightsBlock from './HighlightsBlock';
import PdfBlock from './PdfBlock';
import ReviewBlock, { type CompletedReview } from './ReviewBlock';
import SearchResultsBlock from './SearchResultsBlock';
import {
  BOOKMARK_CITE_PREFIX,
  bookmarkRefsOf,
  CITE_PREFIX,
  citationLabel,
  citationOrder,
  authorList,
  paperYear,
  citedNumbers,
  citationSources,
  degradedLabels,
  linkCitations,
  normalizeEmphasis,
  pdfBlockOf,
  resultsOf,
  reviewBlockOf,
  searchBlockOf,
  splitLead,
  turnSummary,
} from './conversationBlocks';

// The server's content for a turn a newer message cancelled.
const CANCELLED_CONTENT = '중단됨';
const keyOf = (paper: Paper): string => String(paper.result_key ?? paper.doc_id);

/** A run of citations as quiet superscript numbers: "유리합니다³˒⁷˒⁸". */
const citationGroup = (markers: ReactNode[]) => (
  <sup className="conv-cite-group">
    {markers.map((marker, index) => <Fragment key={index}>{index > 0 && ','}{marker}</Fragment>)}
  </sup>
);

/**
 * ReactMarkdown remounts a subtree whenever a `components` entry changes
 * identity, which would drop a marker's focus and hover each time the popover
 * opens. So the link component is stable and reads its turn's renderer from context.
 */
const CitationRenderer = createContext<(href: string | undefined, children: ReactNode) => ReactNode>(
  (href, children) => <a href={href}>{children}</a>,
);

function CitationAnchor({ href, children }: { href?: string; children?: ReactNode }) {
  return <>{useContext(CitationRenderer)(href, children)}</>;
}

const MARKDOWN_PLUGINS = [remarkGfm];
const MARKDOWN_COMPONENTS = { a: CitationAnchor };

/** What the citation popover shows for one marker. */
interface PeekContent {
  title: string;
  meta: string;
  hint: boolean;
}

const PEEK_ID = 'conv-cite-peek';
const PEEK_DELAY_MS = 120;
const PEEK_GAP = 6;
const PEEK_MAX_WIDTH = 320;
// Flip above when this much room is not left below; an estimate, the popover is at most ~3 lines.
const PEEK_ROOM_BELOW = 96;

interface ConversationPageProps {
  id: string;
}

/** One saved conversation: thread with a follow-up composer, results in the artifact panel. */
function ConversationPage({ id }: ConversationPageProps) {
  const navigate = useNavigate();
  const location = useLocation();
  // One-shot navigation state: run the pending turn, and (from MyPage's 대화에서 열기)
  // open that bookmark's review in the 리뷰 tab right away.
  const [navState] = useState(() => (location.state ?? {}) as { run?: boolean; openReview?: string | null; openReviewTitle?: string });
  const runOnLoad = Boolean(navState.run);
  const { conversation, turns, loadError, streaming, liveStatus, send, stop, retry, reload } = useConversation(id, runOnLoad);

  // Which turn's results the artifact shows (null = the latest), the selected paper in it,
  // and the reader's open/closed and tab choices for the newest artifact turn (a graph or a
  // PDF): a newer one re-opens the panel on its own tab. Keyed by turn seq, not query_hash:
  // the same query asked twice is two results.
  const [activeSeq, setActiveSeq] = useState<number | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [artifactPref, setArtifactPref] = useState<{ artifactSeq: number; open: boolean } | null>(
    () => (navState.openReview ? { artifactSeq: -1, open: true } : null),
  );
  const [tabPref, setTabPref] = useState<{ artifactSeq: number; tab: ArtifactTab } | null>(
    () => (navState.openReview ? { artifactSeq: -1, tab: 'review' } : null),
  );
  const [pdfSeq, setPdfSeq] = useState<number | null>(null);
  // Reviews that finished while this page was open (or settled on their first
  // poll after a reload), newest last; the 리뷰 tab shows the chosen one, else the latest.
  const [reviews, setReviews] = useState<CompletedReview[]>([]);
  const [reviewTarget, setReviewTarget] = useState<{ sessionId: string; title: string } | null>(
    () => (navState.openReview ? { sessionId: navState.openReview, title: navState.openReviewTitle || '북마크 리뷰' } : null),
  );
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // One citation popover for the page (hover after a short delay, or keyboard focus).
  const [peek, setPeek] = useState<({ id: string; rect: DOMRect } & PeekContent) | null>(null);
  const peekTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
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
  const pdfs = useMemo(() => turns.flatMap(turn => {
    const block = pdfBlockOf(turn);
    return block ? [{ seq: turn.seq, block }] : [];
  }), [turns]);
  const activePdf = pdfs.find(entry => entry.seq === pdfSeq) ?? pdfs.at(-1) ?? null;
  const latestGraphSeq = results.filter(entry => entry.graph).at(-1)?.seq ?? -1;
  const latestPdfSeq = pdfs.at(-1)?.seq ?? -1;
  const latestArtifactSeq = Math.max(latestGraphSeq, latestPdfSeq);
  const artifactOpen = artifactPref && artifactPref.artifactSeq === latestArtifactSeq
    ? artifactPref.open
    : latestArtifactSeq >= 0;
  const autoTab: ArtifactTab = latestArtifactSeq >= 0 && latestArtifactSeq === latestPdfSeq ? 'pdf' : 'graph';
  const tab = tabPref && tabPref.artifactSeq === latestArtifactSeq ? tabPref.tab : autoTab;
  const setTab = (next: ArtifactTab) => setTabPref({ artifactSeq: latestArtifactSeq, tab: next });
  const liveSeq = turns.find(turn => turn.id === 'live')?.seq;
  const graphPending = Boolean(streaming && active && active.seq === liveSeq);
  const selectedPaper = activeSearch?.papers.find(paper => keyOf(paper) === selectedKey) ?? null;

  const setArtifactOpen = (open: boolean) => setArtifactPref({ artifactSeq: latestArtifactSeq, open });

  const openPdf = (seq: number) => {
    setPdfSeq(seq);
    setTab('pdf');
    setArtifactOpen(true);
  };
  const latestReview = reviews.at(-1);
  const activeReview = reviewTarget ?? (latestReview ? { sessionId: latestReview.sessionId, title: latestReview.title } : null);

  const addReview = (review: CompletedReview) => setReviews(prev => [
    ...prev.filter(item => item.sessionId !== review.sessionId),
    review,
  ]);

  const openReport = (sessionId: string, title: string) => {
    setReviewTarget({ sessionId, title });
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

  const closePeek = () => {
    if (peekTimerRef.current) clearTimeout(peekTimerRef.current);
    peekTimerRef.current = null;
    setPeek(null);
  };

  /** Hover (mouse only, after 120ms) and focus (at once) open the popover; touch never does. */
  const peekProps = (id: string, content: PeekContent) => ({
    'aria-describedby': peek?.id === id ? PEEK_ID : undefined,
    onPointerEnter: (event: ReactPointerEvent<HTMLElement>) => {
      if (event.pointerType !== 'mouse') return;
      const target = event.currentTarget;
      if (peekTimerRef.current) clearTimeout(peekTimerRef.current);
      peekTimerRef.current = setTimeout(() => {
        peekTimerRef.current = null;
        setPeek({ id, rect: target.getBoundingClientRect(), ...content });
      }, PEEK_DELAY_MS);
    },
    onPointerLeave: closePeek,
    onFocus: (event: ReactFocusEvent<HTMLElement>) => setPeek({ id, rect: event.currentTarget.getBoundingClientRect(), ...content }),
    onBlur: closePeek,
  });

  const renderCitation = (turn: ViewTurn, href: string | undefined, children: ReactNode) => {
    if (href?.startsWith(BOOKMARK_CITE_PREFIX)) {
      const bookmarks = bookmarkRefsOf(turn)?.bookmarks ?? [];
      const markers = citedNumbers(href, BOOKMARK_CITE_PREFIX).map(n => {
        const bookmark = bookmarks[n - 1];
        if (!bookmark) return <span key={n} className="conv-cite is-missing">B{n}</span>;
        // Bookmark citations stay in the thread: they point at the turn's own chip.
        const focusChip = () => {
          const chip = document.getElementById(`bookmark-ref-${turn.seq}-${n}`);
          chip?.scrollIntoView?.({ block: 'nearest' });
          chip?.focus();
        };
        return (
          <button
            key={n}
            type="button"
            className="conv-cite"
            aria-label={`근거 북마크 B${n}: ${bookmark.title}`}
            onClick={focusChip}
            {...peekProps(`${turn.seq}-B${n}`, {
              title: bookmark.title,
              meta: `북마크 · ${bookmark.num_papers}편${bookmark.has_report ? ' · 리포트' : ''}`,
              hint: false,
            })}
          >
            B{n}
          </button>
        );
      });
      return citationGroup(markers);
    }
    if (!href?.startsWith(CITE_PREFIX)) {
      return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
    }
    const source = citations.get(turn.id);
    const markers = citedNumbers(href, CITE_PREFIX).map(n => {
      const paper = source?.search.papers[n - 1];
      if (!source || !paper) return <span key={n} className="conv-cite is-missing">{n}</span>;
      return (
        <button
          key={n}
          type="button"
          className="conv-cite"
          aria-label={`참고 논문 ${n}: ${citationLabel(paper)}, ${paper.title}`}
          onClick={() => showInArtifact(source.seq, paper)}
          {...peekProps(`${turn.seq}-${n}`, {
            title: paper.title,
            meta: [authorList(paper.authors, 2), paperYear(paper.year), paper.source].filter(Boolean).join(' · '),
            hint: true,
          })}
        >
          {n}
        </button>
      );
    });
    return citationGroup(markers);
  };

  // While the popover is open, Escape and scrolling the thread close it.
  useEffect(() => {
    if (!peek) return undefined;
    const box = scrollRef.current;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setPeek(null); };
    const onScroll = () => setPeek(null);
    document.addEventListener('keydown', onKeyDown);
    box?.addEventListener('scroll', onScroll, { capture: true });
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      box?.removeEventListener('scroll', onScroll, { capture: true });
    };
  }, [peek]);

  useEffect(() => () => { if (peekTimerRef.current) clearTimeout(peekTimerRef.current); }, []);

  const lastTurn = turns.at(-1);

  const renderAssistant = (turn: ViewTurn) => {
    const live = turn.id === 'live';
    const search = searchBlockOf(turn);
    const review = reviewBlockOf(turn);
    const pdf = pdfBlockOf(turn);
    const bookmarkRefs = bookmarkRefsOf(turn);
    const summary = turnSummary(turn);
    const isLast = turn === lastTurn;
    const serverCancelled = turn.status === 'error' && turn.content.trim() === CANCELLED_CONTENT;
    // Search turns: lead paragraph, status, results, then the summary. Chat and
    // clarify turns stream text only and show no status line.
    const { lead, rest } = splitLead(serverCancelled ? '' : turn.content, Boolean(search || review || pdf) || Boolean(turn.statusSeen), turn.leadLength);
    const showLiveStatus = live && turn.status === 'running'
      && (Boolean(turn.statusSeen) || (!turn.content && turn.blocks.length === 0));
    const markdown = (text: string) => text && (
      <CitationRenderer.Provider value={(href, children) => renderCitation(turn, href, children)}>
        <div className="conv-markdown">
          <ReactMarkdown remarkPlugins={MARKDOWN_PLUGINS} components={MARKDOWN_COMPONENTS}>
            {linkCitations(normalizeEmphasis(text))}
          </ReactMarkdown>
        </div>
      </CitationRenderer.Provider>
    );
    return (
      <li key={turn.id} className="conv-turn is-assistant">
        <div className="conv-assistant-head">
          {/* Shown from the first moment, including while the turn is still "생각하는 중…". */}
          <MascotFace size={32} className="conv-avatar" />
          <span className="conv-assistant-name">집현전</span>
          <span className="conv-assistant-role">논문 연구 도우미</span>
        </div>
        {bookmarkRefs && (
          <BookmarkRefsStrip block={bookmarkRefs} idPrefix={`bookmark-ref-${turn.seq}`} onOpenReview={openReport} />
        )}

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
        ) : summary && (review || pdf || bookmarkRefs) && !(live && turn.status === 'running') ? (
          <p className="conv-status">{summary}</p>
        ) : null}

        {search && search.papers.length > 0 && (
          <SearchResultsBlock
            block={search}
            onSelect={paper => showInArtifact(turn.seq, paper)}
            onShowAll={() => showInArtifact(turn.seq, null, 'list')}
          />
        )}

        {review && <ReviewBlock block={review} onCompleted={addReview} onOpenReport={sessionId => openReport(sessionId, review.paper_title)} />}
        {pdf?.type === 'paper_pdf' && <PdfBlock block={pdf} onOpen={() => openPdf(turn.seq)} />}
        {pdf?.type === 'pdf_highlights' && <HighlightsBlock block={pdf} onOpen={() => openPdf(turn.seq)} />}

        {markdown(rest)}

        {(() => {
          const source = citations.get(turn.id);
          if (!source || serverCancelled) return null;
          const entries = citationOrder(turn.content)
            .flatMap(n => {
              const paper = source.search.papers[n - 1];
              return paper ? [{ n, paper }] : [];
            })
            .sort((left, right) => left.n - right.n);
          return <CitedPapers entries={entries} turnSeq={turn.seq} onSelect={paper => showInArtifact(source.seq, paper)} />;
        })()}

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

      {peek && (
        <div
          id={PEEK_ID}
          role="tooltip"
          className="conv-cite-peek"
          // Fixed to the viewport: the thread scrolls (overflow-y: auto) and would clip an absolute popover.
          style={{
            left: Math.max(16, Math.min(peek.rect.left, window.innerWidth - 16 - PEEK_MAX_WIDTH)),
            ...(peek.rect.bottom + PEEK_GAP + PEEK_ROOM_BELOW > window.innerHeight
              ? { bottom: window.innerHeight - peek.rect.top + PEEK_GAP }
              : { top: peek.rect.bottom + PEEK_GAP }),
          }}
        >
          <div className="conv-cite-peek-title">{peek.title}</div>
          {peek.meta && <div className="conv-cite-peek-meta">{peek.meta}</div>}
          {peek.hint && <div className="conv-cite-peek-hint">클릭하면 오른쪽 패널에서 열려요</div>}
        </div>
      )}

      {artifactOpen && (
        <ArtifactPanel
          search={activeSearch}
          graph={active?.graph?.graph ?? null}
          graphPending={graphPending}
          review={activeReview}
          pdf={activePdf?.block ?? null}
          pdfKey={activePdf ? `${activePdf.seq}:${activePdf.block.type}` : ''}
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
