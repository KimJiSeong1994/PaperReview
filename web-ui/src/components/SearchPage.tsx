import { useState, useEffect, useCallback, useMemo, useRef, Suspense, lazy } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import PaperList from './PaperList';
import DetailPanel from './DetailPanel';
import SearchBar from './SearchBar';
import {
  searchPapers,
  trackSearchClick,
  getGraphData,
  startDeepReview,
  saveBookmark,
  fetchBatchReferences,
  classifyPosterError,
  classifyPosterResponse,
  downloadPosterPdf,
  generatePoster,
  generatePosterDirect,
} from '../api/client';
import type { Paper, GraphData } from '../types';
import { useDeepReview } from '../hooks/useDeepReview';
import { useAuth } from '../contexts/AuthContext';
import { generateApaCitation } from '../utils/citation';
import { copyToClipboard } from '../utils/clipboard';
import { openPaperViewer, viewerHrefForPaper } from '../utils/blogPaperReference';
import {
  trackBookmarkSave,
  trackDeepReviewComplete,
  trackDeepReviewFail,
  trackDeepReviewStart,
  trackPaperSelect,
  trackPosterGenerateComplete,
  trackPosterGenerateFail,
  trackPosterGenerateStart,
  trackReportDownload,
  trackSearchEvent,
} from '../analytics/events';

const GraphViewComponent = lazy(() => import('./GraphView'));

// PDF 실패는 다시 눌러 볼 값어치가 있는지로 갈린다. 서버에 Chromium 이 없으면
// 재시도는 같은 503 을 되돌려 줄 뿐이므로, 그 경우엔 이미 손에 쥔 HTML 로 안내한다.
const posterPdfErrorMessage = (
  error: ReturnType<typeof classifyPosterError>,
): string => {
  if (error.errorCode === 'poster_pdf_unavailable') {
    return 'PDF 내보내기를 지원하지 않는 서버입니다. 다시 시도해도 결과는 같으니 Download 로 HTML 을 받으세요.';
  }
  const reason = error.error || '알 수 없는 오류';
  return error.retryable === false
    ? `PDF 생성 실패: ${reason} — 다시 시도해도 같은 결과입니다.`
    : `PDF 생성 실패: ${reason} — 잠시 후 다시 시도해 주세요.`;
};

// Four shapes of question this corpus answers, not four topics. A visitor
// arriving at an empty box has no way to know whether it wants a keyword, a
// title, or a comparison — these are vocabulary, not decoration. Each string
// was run through QueryAnalyzer.analyze_query before being chosen:
//   그래프 신경망               topic_exploration  conf 0.98
//   LLM 에이전트 논문            topic_exploration  conf 0.93
//   GraphRAG와 기존 RAG 비교     comparison         conf 0.97
//   Attention Is All You Need 논문  paper_search   conf 0.99
// They are NOT chosen for speed. classify_difficulty only returns "easy" for
// <= 3 keywords, and the analyzer expands every natural query to 5-6, so
// `hyde_enabled = difficulty !== "easy"` is true for all of them. No chip
// choice can avoid the slow path; that is a QueryAnalyzer property.
const HOME_CHIPS = [
  '그래프 신경망',
  'LLM 에이전트 논문',
  'GraphRAG와 기존 RAG 비교',
  'Attention Is All You Need 논문',
];

function SearchPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, setShowLoginModal } = useAuth();

  const [papers, setPapers] = useState<Paper[]>([]);
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  // Set from each search response; sent back with a click so the event can be
  // joined to the search that produced the result.
  const [queryHash, setQueryHash] = useState<string>('');
  // Random per search, sent with the impression and echoed back on each click
  // so the anonymous analytics channel can join the two. Encodes nothing about
  // the query itself — see SearchImpression in analytics/events.
  const [searchId, setSearchId] = useState<string>('');
  const [rankingVariant, setRankingVariant] = useState<string>('');
  const [highlightedPapers, setHighlightedPapers] = useState<Set<string>>(new Set());
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [enrichmentLoading, setEnrichmentLoading] = useState(false);
  const [query, setQuery] = useState('');
  // Survives a failed search so the empty state can hand the query back
  // instead of dropping it (a chip click has no other copy of it).
  const [attemptedQuery, setAttemptedQuery] = useState('');
  // What the backend actually searched, and which sources failed to answer.
  // Both ship in every response and neither was read: the UI reported "no
  // results" for a query it never showed, whether the sources came back empty
  // or simply timed out.
  const [improvedQuery, setImprovedQuery] = useState('');
  const [timedOutSources, setTimedOutSources] = useState<string[]>([]);
  const [searchNotices, setSearchNotices] = useState<string[]>([]);

  // Deep Review states
  const [selectedPapersForReview, setSelectedPapersForReview] = useState<Set<string>>(new Set());
  const {
    reviewSessionId, reviewStatus, reviewProgress, reviewReport,
    verificationStats, startReview: startReviewHook, resetReview,
  } = useDeepReview();
  const [showReport, setShowReport] = useState(false);
  const [showToolsMenu, setShowToolsMenu] = useState(false);
  const [showResultsPanel, setShowResultsPanel] = useState(true);
  const [showDetailsPanel, setShowDetailsPanel] = useState(true);

  // Bookmark states
  const [bookmarkSaved, setBookmarkSaved] = useState(false);

  // Poster states
  const [posterLoading, setPosterLoading] = useState(false);
  const [posterHtml, setPosterHtml] = useState<string | null>(null);
  // Kept apart from posterHtml: closing must only hide the modal. The
  // response HTML is the only copy of a run that costs up to 240s of LLM
  // time, and a stray click on the overlay used to throw it away.
  const [posterOpen, setPosterOpen] = useState(false);
  const [posterWarning, setPosterWarning] = useState<string | null>(null);
  const [posterPdfLoading, setPosterPdfLoading] = useState(false);
  const [posterPdfError, setPosterPdfError] = useState<string | null>(null);
  // Declared above the de-auth reset because that block has to abort it.
  const posterPdfAbortRef = useRef<AbortController | null>(null);
  // logout() clears tokens and navigates to '/', but a SearchPage already
  // mounted there is never unmounted, so everything a session produced would be
  // inherited by whoever logs in next on this device. Reset during render
  // (React's documented pattern) rather than in an effect, so nothing stale is
  // ever painted for the new user.
  //
  // All three de-auth paths funnel through setIsAuthenticated(false) — the
  // logout button, the auth:logout event an interceptor fires on an expired
  // token, and a failed token check at startup — so this one block covers them.
  // Trade-off: an expired token therefore also discards the report, and logging
  // back in as the same user does not bring it back. That is deliberate; a
  // server-derived report should not outlive the session it came from.
  const [prevAuthenticated, setPrevAuthenticated] = useState(isAuthenticated);
  if (prevAuthenticated !== isAuthenticated) {
    setPrevAuthenticated(isAuthenticated);
    setPosterHtml(null);
    setPosterOpen(false);
    // A PDF request already in flight would otherwise land as a download on
    // the next user's device, which is exactly what this block exists to stop.
    posterPdfAbortRef.current?.abort();
    setPosterPdfLoading(false);
    setPosterPdfError(null);
    resetReview();
    setShowReport(false);
    setSelectedPapersForReview(new Set());
    setBookmarkSaved(false);
  }

  // Query guidance (non-academic query feedback)
  const [guidanceMessage, setGuidanceMessage] = useState<string | null>(null);
  const [guidanceSticky, setGuidanceSticky] = useState(false);

  const communityByPaper = useMemo(() => Object.fromEntries(
    (graphData?.nodes || []).map(node => [
      String(node.id),
      {
        communityId: node.community_id ?? 0,
        label: node.community_label || `주제 ${Number(node.community_id ?? 0) + 1}`,
      },
    ]),
  ), [graphData]);

  // AbortController ref for cancelling in-flight search requests
  const searchAbortRef = useRef<AbortController | null>(null);
  const searchRequestIdRef = useRef(0);
  const trackedCompletedReviewRef = useRef(false);
  const toolsButtonRef = useRef<HTMLButtonElement>(null);
  const posterModalRef = useRef<HTMLDivElement>(null);
  // The control that opened the poster, so closing hands focus back to it.
  // The tools-menu item unmounts with its menu, so that path points at Tools.
  const posterTriggerRef = useRef<HTMLElement | null>(null);

  // Auto-dismiss guidance message. Hard failures opt out — the window is a
  // nudge for the non-academic hint, but it silently ate the search error and
  // left the empty state looking like a blank result. 8s rather than 3s: the
  // non-academic hint is a 40-character instruction carrying two worked
  // examples, and 3s is under the time it takes to read it once.
  useEffect(() => {
    if (!guidanceMessage || guidanceSticky) return;
    const timer = setTimeout(() => setGuidanceMessage(null), 8000);
    return () => clearTimeout(timer);
  }, [guidanceMessage]);

  const newImpressionId = () => (
    globalThis.crypto?.randomUUID?.() ?? `s_${Math.random().toString(36).slice(2)}`
  );

  const hashString = (str: string) => {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return Math.abs(hash).toString();
  };

  const isStaleSearch = (requestId: number, abortController: AbortController) => (
    searchRequestIdRef.current !== requestId ||
    searchAbortRef.current !== abortController ||
    abortController.signal.aborted
  );

  const enrichSearchResults = async (
    requestId: number,
    abortController: AbortController,
    basePapers: Paper[],
  ) => {
    if (isStaleSearch(requestId, abortController)) return;
    setEnrichmentLoading(true);

    let latestGraphRequest = 0;
    const applyGraphData = async (papersToGraph: Paper[]) => {
      const graphRequest = ++latestGraphRequest;
      try {
        const graph = await getGraphData(JSON.stringify(papersToGraph));
        if (!isStaleSearch(requestId, abortController) && graphRequest === latestGraphRequest) {
          setGraphData(graph);
        }
      } catch (error) {
        if (!isStaleSearch(requestId, abortController)) {
          console.warn('Graph enrichment failed:', error);
        }
      }
    };

    const enrichReferences = async () => {
      // Reference enrichment is authenticated. Anonymous search must remain a
      // public graph flow instead of turning a background 401 into a login modal.
      if (!isAuthenticated) return;

      const topPapers = basePapers.slice(0, 5).map(p => ({
        title: p.title,
        doi: p.doi,
        arxiv_id: p.arxiv_id,
      }));

      try {
        const { references } = await fetchBatchReferences(topPapers);
        if (isStaleSearch(requestId, abortController) || references.length === 0) return;

        const existingKeys = new Set(basePapers.map(p => p.result_key ?? p.doc_id));
        const refPapers: Paper[] = [];
        for (const ref of references) {
          if (!ref.title?.trim()) continue;
          const resultKey = ref.paper_id
            ? `reference:${ref.source}:${ref.paper_id}`
            : `reference:${JSON.stringify([ref.title, ref.authors, ref.year, ref.url, ref.source])}`;
          if (existingKeys.has(resultKey)) continue;
          existingKeys.add(resultKey);
          refPapers.push({
            doc_id: hashString(ref.title),
            result_key: resultKey,
            title: ref.title,
            authors: ref.authors || [],
            year: ref.year,
            abstract: ref.abstract || '',
            url: ref.url || '',
            citations: ref.citations || 0,
            source: 'reference',
            parent_paper_title: ref.parent_paper_title,
          });
        }

        if (refPapers.length === 0 || isStaleSearch(requestId, abortController)) return;

        const merged = [...basePapers, ...refPapers];
        setPapers(merged);
        await applyGraphData(merged);
      } catch (error) {
        if (!isStaleSearch(requestId, abortController)) {
          console.warn('Reference enrichment failed:', error);
        }
      }
    };

    try {
      await Promise.allSettled([
        applyGraphData(basePapers),
        enrichReferences(),
      ]);
    } finally {
      if (!isStaleSearch(requestId, abortController)) {
        setEnrichmentLoading(false);
      }
    }
  };

  const handleSearch = async (searchQuery: string, source: 'home' | 'fixed_bar' | 'url_prefill' = papers.length > 0 || query ? 'fixed_bar' : 'home') => {
    if (!searchQuery.trim()) return;

    setAttemptedQuery(searchQuery);
    const impressionId = newImpressionId();
    setSearchId(impressionId);
    searchRequestIdRef.current += 1;
    const requestId = searchRequestIdRef.current;

    if (searchAbortRef.current) {
      searchAbortRef.current.abort();
    }
    const abortController = new AbortController();
    searchAbortRef.current = abortController;

    setGuidanceMessage(null);
    setGuidanceSticky(false);
    setEnrichmentLoading(false);
    setImprovedQuery('');
    setTimedOutSources([]);
    setSearchNotices([]);

    // Delay loading indicator so non-academic responses (~0.5s) don't flash it
    const loadingTimer = setTimeout(() => {
      if (!isStaleSearch(requestId, abortController)) {
        setLoading(true);
        setQuery(searchQuery);
      }
    }, 500);

    try {
      const results = await searchPapers({
        query: searchQuery,
        max_results: 50,
        sources: ['arxiv', 'connected_papers', 'google_scholar', 'openalex', 'dblp', 'openalex_korean'],
        sort_by: 'relevance',
        use_llm_search: false,
      }, abortController.signal);

      if (isStaleSearch(requestId, abortController)) return;

      setQueryHash(results.query_hash || '');

      // Analyzer suggestions do not establish which queries actually ran.
      const executed = Object.entries(results.metadata?.executed_queries ?? {})
        .filter(([, queries]) => (Array.isArray(queries) ? queries : [queries])
          .some(value => value.trim() !== searchQuery.trim()))
        .map(([provider, queries]) => `${provider}: ${Array.isArray(queries) ? queries.join(' / ') : queries}`);
      const executedQuery = results.metadata?.executed_query?.trim() || '';
      setImprovedQuery(executed.join(' · ') || (executedQuery !== searchQuery.trim() ? executedQuery : ''));
      // Only fixed user-facing messages: backend markers may include exception
      // names or diagnostics and are not safe presentation text.
      const notices: string[] = [];
      const degradation = [...(results.degraded ?? []), ...(results.metadata?.degraded ?? [])];
      if (degradation.length) notices.push('일부 검색 기능이 제한되었습니다.');
      if (results.metadata?.partial) notices.push('일부 검색만 완료되었습니다.');
      const stageModes = results.stage_modes ?? results.metadata?.stage_modes ?? {};
      const isDegraded = (mode: unknown) => typeof mode === 'string'
        && /fallback|error|timeout|capacity|circuit|reject|unavailable|disabled_no_api_key/i.test(mode);
      if (isDegraded(stageModes.query_analysis_mode) || isDegraded(stageModes.analyze)
        || degradation.some(marker => /^(query_analysis_mode|analyze):/.test(marker))) {
        notices.push('질의 분석이 제한되어 원래 검색어로 대체 검색했습니다.');
      }
      if (isDegraded(stageModes.ranking_mode) || isDegraded(stageModes.rank)
        || degradation.some(marker => /^(ranking_mode|rank):/.test(marker))) {
        notices.push('결과 순위 계산이 제한되어 대체 순서를 표시합니다.');
      }
      const sourceModes = stageModes.source_modes as Record<string, string> | undefined;
      for (const [provider, mode] of Object.entries(sourceModes ?? {})) {
        if (isDegraded(mode)) {
          const sourceName = ['arxiv', 'connected_papers', 'google_scholar', 'openalex', 'dblp', 'openalex_korean'].includes(provider)
            ? provider : '일부 출처';
          notices.push(`${sourceName}: 검색 응답이 제한되었습니다.`);
        }
      }
      const saveMessages = {
        accepted: '저장 요청이 접수되었습니다. 비동기 최선 노력 작업이며 저장 완료를 보장하지 않습니다.',
        not_admitted_capacity: '저장 작업 용량이 부족하여 자동 저장 요청이 접수되지 않았습니다.',
        not_requested: '자동 저장을 요청하지 않았습니다.',
        skipped_cache: '캐시 결과에 새 자동 저장 작업을 요청하지 않았습니다.',
        no_results: '저장할 검색 결과가 없어 자동 저장하지 않았습니다.',
        not_admitted_shutdown: '서버 종료 중이어서 자동 저장 요청이 접수되지 않았습니다.',
        not_admitted_disconnect: '연결이 종료되어 자동 저장 요청이 접수되지 않았습니다.',
      };
      const saveStatus = results.metadata?.save_status;
      if (saveStatus) notices.push(saveMessages[saveStatus]);
      setSearchNotices([...new Set(notices)]);

      // A source that timed out is not a source that found nothing. Without
      // this the zero-result copy blames the user's keywords for a backend
      // that never answered.
      setTimedOutSources(
        Object.entries(results.source_timeouts ?? {})
          .filter(([, timedOut]) => timedOut)
          .map(([name]) => name),
      );
      const variant = String(
        (results.stage_modes as Record<string, unknown> | undefined)?.ranking_variant ?? '',
      );
      setRankingVariant(variant);

      // Check if query was classified as non-academic
      const qa = results.query_analysis;
      if (qa && qa.is_academic === false) {
        clearTimeout(loadingTimer);
        setGuidanceMessage(
          '학술 논문 및 연구 관련 주제를 입력해주세요. 예: "transformer attention mechanism", "강화학습 정책 최적화"'
        );
        setPapers([]);
        setGraphData(null);
        setSelectedPaper(null);
        setHighlightedPapers(new Set());
        setSelectedPapersForReview(new Set());
        setQuery('');
        setLoading(false);
        trackSearchEvent(searchQuery, 'non_academic', 0, source, { searchId: impressionId });
        return;
      }

      // Academic query confirmed — ensure loading is shown until primary search results render
      clearTimeout(loadingTimer);
      setLoading(true);
      setQuery(searchQuery);

      const allPapers: Paper[] = [];

      Object.entries(results.results).forEach(([source, sourcePapers]) => {
        sourcePapers.forEach((paper: any) => {
          const title = paper.title || 'Untitled';
          const doc_id = hashString(title);

          allPapers.push({
            doc_id,
            title,
            authors: paper.authors || [],
            year: paper.year || paper.published,
            journal: paper.journal || paper.publication || '',
            abstract: paper.abstract || '',
            url: paper.url || paper.paper_url,
            pdf_url: paper.pdf_url,
            doi: paper.doi,
            citations: paper.citations || 0,
            source: source,
            ...paper,
          });
        });
      });

      // The API returns papers grouped by source, so the loop above yields
      // every arXiv hit, then every Scholar hit, and so on — which discards
      // the cross-source ranking the backend computed. `_rank` carries that
      // order; papers without one (partial/timed-out responses) keep their
      // arrival order at the end.
      allPapers.sort(
        (a, b) => (a._rank ?? Number.MAX_SAFE_INTEGER) - (b._rank ?? Number.MAX_SAFE_INTEGER)
      );

      setPapers(allPapers);
      setGraphData(null);
      trackSearchEvent(searchQuery, allPapers.length > 0 ? 'success' : 'empty', allPapers.length, source,
        { searchId: impressionId, rankingVariant: variant });

      if (allPapers.length > 0) {
        setSelectedPaper(allPapers[0]);
        setHighlightedPapers(new Set());
        setSelectedPapersForReview(new Set());
        void enrichSearchResults(requestId, abortController, allPapers);
      } else {
        setSelectedPaper(null);
        setHighlightedPapers(new Set());
        setSelectedPapersForReview(new Set());
      }
    } catch (error: any) {
      clearTimeout(loadingTimer);

      if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return;
      if (isStaleSearch(requestId, abortController)) return;

      console.error('Search error:', error);

      let errorMessage = '알 수 없는 오류가 발생했습니다.';

      if (error.code === 'ECONNREFUSED' || error.message?.includes('Network Error') || error.message?.includes('Failed to fetch')) {
        errorMessage = '백엔드 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.';
      } else if (error.response?.status === 503) {
        errorMessage = '검색 서비스가 현재 요청을 처리할 수 없습니다(503). 잠시 후 다시 시도해주세요.';
      } else if (typeof error.response?.data?.detail === 'string') {
        errorMessage = error.response.data.detail;
      } else if (error.message) {
        errorMessage = error.message;
      }

      setGuidanceSticky(true);
      setGuidanceMessage(`검색 중 오류가 발생했습니다: ${errorMessage}`);

      setPapers([]);
      setGraphData(null);
      setSelectedPaper(null);
      setHighlightedPapers(new Set());
      setSelectedPapersForReview(new Set());
      trackSearchEvent(searchQuery, 'error', 0, source, { searchId: impressionId });
    } finally {
      clearTimeout(loadingTimer);
      if (!isStaleSearch(requestId, abortController)) {
        setLoading(false);
      }
    }
  };

  // Auto-search from URL query param (e.g. /?q=paper+title)
  useEffect(() => {
    if (location.pathname !== '/') return;
    const params = new URLSearchParams(location.search);
    const q = params.get('q');
    if (q && q.trim() && q !== query) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      handleSearch(q.trim(), 'url_prefill');
      navigate('/', { replace: true });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search, location.pathname]);

  const handleSaveBookmark = async () => {
    if (!reviewSessionId || !reviewReport) return;
    if (!isAuthenticated) {
      setShowLoginModal(true);
      return;
    }
    try {
      const selectedPaperIds = Array.from(selectedPapersForReview);
      const selectedPapersData = papers.filter(paper =>
        selectedPaperIds.includes(paper.result_key ?? paper.doc_id)
      );
      const title = query
        ? `${query} - ${new Date().toLocaleDateString()}`
        : `Deep Research - ${new Date().toLocaleDateString()}`;
      await saveBookmark({
        session_id: reviewSessionId,
        title,
        query,
        papers: selectedPapersData.map(p => ({
          title: p.title,
          authors: p.authors,
          year: p.year,
          pdf_url: p.pdf_url || undefined,
          doi: p.doi || undefined,
          arxiv_id: p.arxiv_id || undefined,
          url: p.url || undefined,
          source: p.source || undefined,
        })),
        report_markdown: reviewReport,
      });
      trackBookmarkSave();
      setBookmarkSaved(true);
      setTimeout(() => setBookmarkSaved(false), 3000);
    } catch (error: any) {
      if (error.response?.status === 401) {
        setShowLoginModal(true);
        return;
      }
      console.error('Bookmark save error:', error);
      setGuidanceMessage(`북마크 저장 실패: ${error.message || error}`);
    }
  };

  /** 1-based position of *paper* in the ranked list on screen (0 when absent). */
  const rankOf = (paper: Paper) => papers.indexOf(paper) + 1;

  const handlePaperSelect = (paper: Paper) => {
    trackPaperSelect('list', { searchId, rankingVariant, rank: rankOf(paper) });
    trackSearchClick(queryHash, paper.doc_id || '', rankOf(paper));
    setSelectedPaper(paper);
    setHighlightedPapers(new Set());
  };

  const handleNodeClickWithHighlight = (paper: Paper) => {
    trackPaperSelect('graph', { searchId, rankingVariant, rank: rankOf(paper) });
    trackSearchClick(queryHash, paper.doc_id || '', rankOf(paper));
    setSelectedPaper(paper);

    if (graphData && graphData.edges) {
      const paperId = paper.result_key ?? paper.doc_id;
      const connectedPapers: Array<{ docId: string; weight: number }> = [];

      graphData.edges.forEach(edge => {
        if (edge.source === paperId || String(edge.source) === String(paperId)) {
          connectedPapers.push({ docId: edge.target, weight: edge.weight || 0 });
        } else if (edge.target === paperId || String(edge.target) === String(paperId)) {
          connectedPapers.push({ docId: edge.source, weight: edge.weight || 0 });
        }
      });

      connectedPapers.sort((a, b) => b.weight - a.weight);
      const topSimilar = connectedPapers.slice(0, 5).map(p => String(p.docId));
      setHighlightedPapers(new Set(topSimilar));
    }
  };

  const handlePaperToggleForReview = (paperId: string) => {
    setSelectedPapersForReview(prev => {
      const newSet = new Set(prev);
      if (newSet.has(paperId)) {
        newSet.delete(paperId);
      } else {
        newSet.add(paperId);
      }
      return newSet;
    });
  };

  const handleDownloadPosterPdf = async () => {
    if (!posterHtml || posterPdfLoading) return;
    const abortController = new AbortController();
    posterPdfAbortRef.current = abortController;
    setPosterPdfLoading(true);
    setPosterPdfError(null);
    try {
      const { blob, filename } = await downloadPosterPdf(posterHtml, abortController.signal);
      // De-auth aborts this controller. A response that was already on the wire
      // when that happened still resolves here, so re-check before delivering:
      // the closed-over isAuthenticated is the value from the old session.
      if (abortController.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      // An abort is this component cancelling itself, not a failure to report.
      if (abortController.signal.aborted) return;
      setPosterPdfError(posterPdfErrorMessage(classifyPosterError(err)));
    } finally {
      setPosterPdfLoading(false);
    }
  };

  const handleGeneratePoster = async () => {
    if (posterHtml) {
      setPosterOpen(true);
      return;
    }
    if (reviewSessionId && reviewStatus === 'completed' && reviewReport) {
      setPosterLoading(true);
      setPosterWarning(null);
      try {
        let useDirectFallback = false;
        trackPosterGenerateStart();
        try {
          const result = await generatePoster(reviewSessionId);
          const poster = classifyPosterResponse(result);
          if (poster.canPreview) {
            if (poster.isCompleteAnalytics) {
              trackPosterGenerateComplete(poster.status);
            } else {
              trackPosterGenerateFail(poster.status);
            }
            setPosterWarning(poster.status === 'degraded'
              ? poster.warning || '포스터가 일부 제한된 상태로 생성되었습니다. 내용을 확인한 뒤 사용하세요.'
              : null);
            setPosterHtml(poster.posterHtml);
            setPosterOpen(true);
            return;
          }
          if (poster.canUseDirectFallback) {
            useDirectFallback = true;
          } else {
            trackPosterGenerateFail(poster.status);
            setGuidanceMessage(`포스터 생성 실패: ${poster.error || '알 수 없는 오류'}`);
            return;
          }
        } catch (err: unknown) {
          const posterError = classifyPosterError(err);
          if (!posterError.canUseDirectFallback) {
            trackPosterGenerateFail(posterError.status);
            console.warn('Session-based poster failed without direct fallback:', posterError.status);
            setGuidanceMessage(`포스터 생성 실패: ${posterError.error || '알 수 없는 오류'}`);
            return;
          }
          useDirectFallback = true;
        }

        if (useDirectFallback) {
          console.warn('Session-based poster unavailable, trying direct fallback');
        }

        const result = await generatePosterDirect(reviewReport, selectedPapersForReview.size);
        const poster = classifyPosterResponse(result);
        if (poster.canPreview) {
          if (poster.isCompleteAnalytics) {
            trackPosterGenerateComplete(poster.status);
          } else {
            trackPosterGenerateFail(poster.status);
          }
          setPosterWarning(poster.status === 'degraded'
            ? poster.warning || '포스터가 일부 제한된 상태로 생성되었습니다. 내용을 확인한 뒤 사용하세요.'
            : null);
          setPosterHtml(poster.posterHtml);
          setPosterOpen(true);
        } else {
          trackPosterGenerateFail(poster.status);
          setGuidanceMessage(`포스터 생성 실패: ${poster.error || '알 수 없는 오류'}`);
        }
      } catch (err: unknown) {
        const posterError = classifyPosterError(err);
        trackPosterGenerateFail(posterError.status);
        console.error('Poster generation failed:', err);
        setGuidanceMessage(`포스터 생성 중 오류: ${posterError.error || '알 수 없는 오류'}`);
      } finally {
        setPosterLoading(false);
      }
      return;
    }

    if (selectedPapersForReview.size === 0) {
      setGuidanceMessage('포스터를 생성하려면 논문을 선택한 후 Deep Research를 먼저 실행해주세요.');
      return;
    }

    if (reviewStatus === 'processing') {
      setGuidanceMessage('Deep Research가 진행 중입니다. 완료 후 다시 시도해주세요.');
      return;
    }

    const confirmed = confirm(
      `선택된 ${selectedPapersForReview.size}편의 논문으로 Deep Research를 실행한 후 포스터를 생성합니다.\n계속하시겠습니까?`
    );
    if (confirmed) {
      await handleStartDeepReview();
    }
  };

  const handleDownloadPDFs = async () => {
    if (selectedPapersForReview.size === 0) {
      setGuidanceMessage('다운로드할 논문을 선택해주세요.');
      return;
    }

    const selectedPaperIds = Array.from(selectedPapersForReview);
    const selectedPapersData = papers.filter(paper =>
      selectedPaperIds.includes(paper.result_key ?? paper.doc_id)
    );

    const papersWithPDF = selectedPapersData.filter(paper => paper.pdf_url);

    if (papersWithPDF.length === 0) {
      setGuidanceMessage('선택된 논문 중 다운로드 가능한 PDF가 없습니다.');
      return;
    }

    let downloadedCount = 0;
    for (const paper of papersWithPDF) {
      try {
        const link = document.createElement('a');
        link.href = paper.pdf_url || '';
        link.target = '_blank';
        link.download = `${paper.title.substring(0, 50).replace(/[^a-zA-Z0-9]/g, '_')}.pdf`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        downloadedCount++;
        if (downloadedCount < papersWithPDF.length) {
          await new Promise(resolve => setTimeout(resolve, 500));
        }
      } catch (error) {
        console.error(`Failed to download PDF for paper: ${paper.title}`, error);
      }
    }

    setGuidanceMessage(`${downloadedCount}개의 PDF 다운로드를 시작했습니다.`);
  };

  const handleStartDeepReview = async () => {
    if (selectedPapersForReview.size === 0) return;

    try {
      setShowReport(true);
      setPosterHtml(null);
      setPosterOpen(false);
      trackDeepReviewStart(selectedPapersForReview.size);

      const selectedPaperIds = Array.from(selectedPapersForReview);
      const selectedPapersData = papers.filter(paper =>
        selectedPaperIds.includes(paper.result_key ?? paper.doc_id)
      );

      const response = await startDeepReview({
        paper_ids: selectedPapersData.map(paper => paper.doc_id),
        papers: selectedPapersData,
        num_researchers: Math.min(selectedPapersForReview.size, 5),
      });

      startReviewHook(response.session_id);
    } catch (error: any) {
      console.error('Deep review error:', error);
      setGuidanceMessage(`Failed to start deep research: ${error.message || error}`);
      setShowReport(false);
    }
  };

  useEffect(() => {
    // Fire exactly one terminal outcome per review run: complete or fail.
    // The ref resets while the review is processing/idle so the next run tracks.
    if (reviewStatus !== 'completed' && reviewStatus !== 'failed') {
      trackedCompletedReviewRef.current = false;
      return;
    }
    if (!trackedCompletedReviewRef.current) {
      if (reviewStatus === 'completed') {
        trackDeepReviewComplete(selectedPapersForReview.size);
      } else {
        trackDeepReviewFail(selectedPapersForReview.size);
      }
      trackedCompletedReviewRef.current = true;
    }
  }, [reviewStatus, selectedPapersForReview.size]);

  // Close tools menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (!target.closest('.tools-dropdown-container')) {
        setShowToolsMenu(false);
      }
    };

    if (showToolsMenu) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showToolsMenu]);

  const closePoster = useCallback(() => {
    setPosterOpen(false);
    setPosterPdfError(null);
    posterTriggerRef.current?.focus();
  }, []);

  // Escape-to-close and initial focus into the dialog, the same shape as the
  // other dialogs here (RecommendationBell.tsx, BlogPage.tsx).
  useEffect(() => {
    if (!posterOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closePoster();
    };
    document.addEventListener('keydown', handleKeyDown);
    posterModalRef.current?.focus();
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [posterOpen, closePoster]);

  return (
    <main id="main" className="main-content">
      {!loading && papers.length === 0 && !query && (
        <div className="centered-search">
          <div className="brand-section">
            {/* Matches the pre-hydration <h1> in web-ui/index.html. React
                replaces #root on mount, so a bare "Jiphyeonjeon" here meant
                JS-rendering crawlers saw a different (and Hangul-free) H1 than
                non-JS ones — and Korean brand queries are "집현전". */}
            <h1 className="brand-title">
              Jiphyeonjeon <span className="brand-title-ko">(집현전)</span>
            </h1>
            <p className="brand-tagline">논문을 찾은 뒤, 근거까지 읽습니다.</p>
          </div>
          <SearchBar
            key={attemptedQuery}
            initialQuery={attemptedQuery}
            onSearch={handleSearch}
            loading={loading}
            guidanceMessage={guidanceMessage}
            guidanceSticky={guidanceSticky}
            onQueryChange={() => setGuidanceMessage(null)}
          />
          <ul className="home-chips" aria-label="예시 검색어">
            {HOME_CHIPS.map((chip) => (
              <li key={chip}>
                {/* Already on "/", so search directly. IntroducePage routes the
                    same chips through ?q= only because it sits on another route. */}
                <button type="button" className="home-chip" onClick={() => handleSearch(chip, 'home')}>
                  {chip}
                </button>
              </li>
            ))}
          </ul>
          <p className="home-note">검색은 로그인 없이 바로 시작할 수 있습니다.</p>
          <Link to="/ko/introduce/" className="home-more">
            집현전 사용법 자세히 보기
          </Link>
        </div>
      )}

      {loading && (
        <div className="loading-screen">
          {/* A search can run for up to 100s (_SEARCH_TIMEOUT). Until now every
              branch that renders a search box was gated on `!loading`, so for
              that whole time there was no field on the page: a typo could not
              be corrected and the run could not be abandoned.

              `loading={false}` is deliberate, not a slip. SearchBar disables
              its input and its button on that prop, so passing the real value
              would render a box the user still cannot use — the trap this is
              meant to remove. Submitting here calls handleSearch, which aborts
              the in-flight request on its way in (searchAbortRef). */}
          <div className="search-bar-fixed">
            <SearchBar
              key={attemptedQuery}
              initialQuery={attemptedQuery}
              onSearch={handleSearch}
              loading={false}
              guidanceMessage={guidanceMessage}
              guidanceSticky={guidanceSticky}
              onQueryChange={() => setGuidanceMessage(null)}
            />
          </div>
          <section
            className="search-loading-scene"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            <div
              className="search-loading-illustration"
              aria-hidden="true"
            />
            <div className="search-loading-shade" aria-hidden="true" />
            <div className="search-loading-copy">
              <div className="search-loading-kicker">
                <span className="search-loading-signal" aria-hidden="true" />
                집현전 서고 탐색 중
              </div>
              <h2>질문과 맞닿은 논문을 찾고 있습니다</h2>
              <p>여러 연구의 제목과 핵심 내용을 살피며 읽을 만한 자료를 고르고 있어요.</p>
              <div className="search-loading-books" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
            </div>
          </section>
        </div>
      )}

      {!loading && papers.length > 0 && (
        <div className="results-view">
          <div className="search-bar-fixed">
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', width: '100%', position: 'relative' }}>
              <div style={{ flex: 1 }}>
                <SearchBar
                  key={attemptedQuery}
                  initialQuery={attemptedQuery}
                  onSearch={handleSearch}
                  loading={loading}
                  guidanceMessage={guidanceMessage}
                  guidanceSticky={guidanceSticky}
                  onQueryChange={() => setGuidanceMessage(null)}
                />
              </div>
              <div className="tools-dropdown-container">
                <button
                  ref={toolsButtonRef}
                  className="tools-button"
                  onClick={() => setShowToolsMenu(!showToolsMenu)}
                >
                  <svg
                    className="tools-icon"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <circle cx="12" cy="6" r="1" fill="currentColor"></circle>
                    <circle cx="12" cy="12" r="1" fill="currentColor"></circle>
                    <circle cx="12" cy="18" r="1" fill="currentColor"></circle>
                    <circle cx="6" cy="12" r="1" fill="currentColor"></circle>
                    <circle cx="18" cy="12" r="1" fill="currentColor"></circle>
                  </svg>
                  <span className="tools-text">Tools</span>
                </button>
                {showToolsMenu && (
                  <div className="tools-dropdown-menu">
                    <button
                      className="tools-menu-item"
                      onClick={() => {
                        setShowToolsMenu(false);
                        handleStartDeepReview();
                      }}
                      disabled={selectedPapersForReview.size === 0 || reviewStatus === 'processing'}
                    >
                      <svg
                        className="menu-item-icon"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <circle cx="11" cy="11" r="8"></circle>
                        <path d="m21 21-4.35-4.35"></path>
                      </svg>
                      <span className="menu-item-text">
                        {reviewStatus === 'processing'
                          ? 'Analyzing...'
                          : selectedPapersForReview.size > 0
                            ? `Deep Research (${selectedPapersForReview.size})`
                            : 'Deep Research'}
                      </span>
                    </button>

                    <div style={{ height: '1px', background: 'rgba(255,255,255,0.1)', margin: '8px 0' }} />

                    <button
                      className="tools-menu-item"
                      disabled={posterLoading}
                      onClick={() => {
                        posterTriggerRef.current = toolsButtonRef.current;
                        setShowToolsMenu(false);
                        handleGeneratePoster();
                      }}
                      title="Generate Conference Poster"
                    >
                      <svg
                        className="menu-item-icon"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                        <line x1="3" y1="9" x2="21" y2="9"></line>
                        <line x1="9" y1="21" x2="9" y2="9"></line>
                      </svg>
                      <span className="menu-item-text">
                        {posterLoading ? 'Generating...' : posterHtml ? 'View Poster' : 'Generate Poster'}
                      </span>
                    </button>

                    <div style={{ height: '1px', background: 'rgba(255,255,255,0.1)', margin: '8px 0' }} />

                    <button
                      className="tools-menu-item"
                      onClick={() => {
                        setShowToolsMenu(false);
                        handleDownloadPDFs();
                      }}
                      disabled={selectedPapersForReview.size === 0}
                    >
                      <svg
                        className="menu-item-icon"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="7 10 12 15 17 10"></polyline>
                        <line x1="12" y1="15" x2="12" y2="3"></line>
                      </svg>
                      <span className="menu-item-text">
                        {selectedPapersForReview.size > 0
                          ? `Download PDFs (${selectedPapersForReview.size})`
                          : 'Download PDFs'}
                      </span>
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Only provider execution metadata establishes actual queries. */}
          {improvedQuery && (
            <p className="results-rewritten-query">
              실제 검색어: <span>{improvedQuery}</span>
            </p>
          )}

          {timedOutSources.length > 0 && (
            <p className="results-degraded" role="status">
              {timedOutSources.join(', ')} 출처가 제때 응답하지 않아 일부 결과가 빠졌을 수 있습니다.
            </p>
          )}

          {searchNotices.length > 0 && (
            <p className="results-degraded" role="status">{searchNotices.join(' · ')}</p>
          )}

          <div className="results-workspace-toolbar" aria-label="검색 결과 보기 설정">
            <div className="results-context">
              <strong>{papers.length}편의 논문 관계</strong>
              <span>{enrichmentLoading ? '관계를 확장하는 중' : '그래프 준비 완료'}</span>
            </div>
            <div className="results-panel-actions">
              <button
                type="button"
                className={showResultsPanel ? 'active' : ''}
                aria-pressed={showResultsPanel}
                onClick={() => setShowResultsPanel(value => !value)}
              >
                관련 논문
              </button>
              <button
                type="button"
                className={showDetailsPanel ? 'active' : ''}
                aria-pressed={showDetailsPanel}
                onClick={() => setShowDetailsPanel(value => !value)}
              >
                논문 정보
              </button>
            </div>
          </div>

          <div className={`main-container ${showResultsPanel ? '' : 'results-panel-collapsed'} ${showDetailsPanel ? '' : 'details-panel-collapsed'}`}>
            <div className={`left-panel ${showResultsPanel ? '' : 'is-collapsed'}`}>
              <div className="pane-title">
                연구 탐색
                {selectedPapersForReview.size > 0 && (
                  <span style={{ marginLeft: '8px', fontSize: '0.9em', color: 'var(--text-faint)' }}>
                    ({selectedPapersForReview.size} 선택됨)
                  </span>
                )}
              </div>
              <PaperList
                papers={papers}
                selectedPaper={selectedPaper}
                onSelect={handlePaperSelect}
                highlightedPapers={highlightedPapers}
                communityByPaper={communityByPaper}
                selectedForReview={selectedPapersForReview}
                onToggleForReview={handlePaperToggleForReview}
              />
            </div>

            <div className="center-panel">
              <div className="pane-title graph-pane-title">
                <span>논문 관계 그래프</span>
                <span className="graph-pane-caption">노드를 선택하면 가까운 연구가 함께 강조됩니다</span>
              </div>
              {graphData ? (
                <Suspense fallback={<div className="app-loading">Loading graph...</div>}>
                  <GraphViewComponent
                    key={queryHash || query}
                    graphData={graphData}
                    selectedPaper={selectedPaper}
                    highlightedPapers={highlightedPapers}
                    papers={papers}
                    onNodeClick={handleNodeClickWithHighlight}
                  />
                </Suspense>
              ) : enrichmentLoading ? (
                <div className="app-loading">Loading graph...</div>
              ) : null}
            </div>

            {!showReport && (
              <div className={`right-panel ${showDetailsPanel ? '' : 'is-collapsed'}`}>
                <div className="pane-title">논문 정보</div>
                {selectedPaper ? (
                  <DetailPanel
                    paper={selectedPaper}
                    // The standalone viewer route is public (the blog links readers to it),
                    // so opening a PDF no longer needs an account the way MyPage did.
                    onViewPaper={(paper) => openPaperViewer(viewerHrefForPaper(paper, 'search'))}
                  />
                ) : (
                  <div className="no-selection">논문을 선택하세요</div>
                )}
              </div>
            )}

            {showReport && (
              <div className={`right-panel ${showDetailsPanel ? '' : 'is-collapsed'}`}>
                <div className="pane-title">
                  Deep Research Report
                  <div className="report-title-actions">
                    {reviewStatus === 'completed' && reviewReport && (
                      <>
                        <button
                          className="cite-report-button"
                          onClick={() => {
                            const selectedPaperIds = Array.from(selectedPapersForReview);
                            const selectedPapersData = papers.filter(paper =>
                              selectedPaperIds.includes(paper.result_key ?? paper.doc_id)
                            );
                            const apaCitations = selectedPapersData
                              .map(paper => generateApaCitation(paper))
                              .join('\n\n');

                            copyToClipboard(apaCitations).then(() => {
                              const btn = document.querySelector('.cite-report-button') as HTMLButtonElement;
                              if (btn) {
                                btn.classList.add('copied');
                                setTimeout(() => btn.classList.remove('copied'), 1500);
                              }
                            });
                          }}
                          title="Copy APA Citations"
                        >
                          <svg
                            className="cite-icon"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                          >
                            <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5C7 4 7 7 7 7"></path>
                            <path d="M6 15H4.5a2.5 2.5 0 0 0 0 5C7 20 7 17 7 17"></path>
                            <path d="M18 9h1.5a2.5 2.5 0 0 0 0-5C17 4 17 7 17 7"></path>
                            <path d="M18 15h1.5a2.5 2.5 0 0 1 0 5C17 20 17 17 17 17"></path>
                            <line x1="7" y1="7" x2="7" y2="17"></line>
                            <line x1="17" y1="7" x2="17" y2="17"></line>
                          </svg>
                        </button>
                        <button
                          className="download-report-button"
                          onClick={() => {
                            const blob = new Blob([reviewReport], { type: 'text/markdown' });
                            const url = URL.createObjectURL(blob);
                            const a = document.createElement('a');
                            a.href = url;
                            a.download = `deep_research_${new Date().toISOString().split('T')[0]}.md`;
                            document.body.appendChild(a);
                            a.click();
                            document.body.removeChild(a);
                            URL.revokeObjectURL(url);
                            trackReportDownload();
                          }}
                          title="Download as Markdown"
                        >
                          <svg
                            className="download-icon"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                          >
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                            <polyline points="7 10 12 15 17 10"></polyline>
                            <line x1="12" y1="15" x2="12" y2="3"></line>
                          </svg>
                        </button>
                        <button
                          className={`bookmark-save-button ${bookmarkSaved ? 'saved' : ''}`}
                          onClick={handleSaveBookmark}
                          title={bookmarkSaved ? 'Bookmarked!' : 'Save as Bookmark'}
                        >
                          <svg
                            className="bookmark-icon"
                            viewBox="0 0 24 24"
                            fill={bookmarkSaved ? 'currentColor' : 'none'}
                            stroke="currentColor"
                            strokeWidth="2"
                          >
                            <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path>
                          </svg>
                        </button>
                      </>
                    )}
                    <button
                      className="close-report-button"
                      onClick={() => {
                        setShowReport(false);
                        resetReview();
                        setBookmarkSaved(false);
                      }}
                      title="Close report"
                    >
                      ✕
                    </button>
                  </div>
                </div>
                <div className="report-content">
                  {reviewStatus === 'processing' && (
                    <div className="review-processing">
                      <div className="loading-spinner"></div>
                      <p>{reviewProgress}</p>
                      <p className="review-hint">Researchers are analyzing papers in parallel...</p>
                    </div>
                  )}
                  {reviewStatus === 'completed' && reviewReport && (
                    <div className="review-report-markdown">
                      {verificationStats && verificationStats.total_claims > 0 && (
                        <div className={`verification-banner ${
                          verificationStats.verification_rate >= 0.7 ? 'verification-banner--high' :
                          verificationStats.verification_rate >= 0.4 ? 'verification-banner--medium' : 'verification-banner--low'
                        }`}>
                          <span className="verification-label">Fact Verification</span>
                          <div className="verification-bar" role="status" aria-label={`${(verificationStats.verification_rate * 100).toFixed(0)}% verified`}>
                            {verificationStats.verified > 0 && (
                              <div
                                className="verification-bar__segment verification-bar__segment--verified"
                                style={{ width: `${(verificationStats.verified / verificationStats.total_claims) * 100}%` }}
                                title={`${verificationStats.verified} verified`}
                              />
                            )}
                            {verificationStats.partially_verified > 0 && (
                              <div
                                className="verification-bar__segment verification-bar__segment--partial"
                                style={{ width: `${(verificationStats.partially_verified / verificationStats.total_claims) * 100}%` }}
                                title={`${verificationStats.partially_verified} partial`}
                              />
                            )}
                            {verificationStats.unverified > 0 && (
                              <div
                                className="verification-bar__segment verification-bar__segment--unverified"
                                style={{ width: `${(verificationStats.unverified / verificationStats.total_claims) * 100}%` }}
                                title={`${verificationStats.unverified} unverified`}
                              />
                            )}
                            {verificationStats.contradicted > 0 && (
                              <div
                                className="verification-bar__segment verification-bar__segment--contradicted"
                                style={{ width: `${(verificationStats.contradicted / verificationStats.total_claims) * 100}%` }}
                                title={`${verificationStats.contradicted} contradicted`}
                              />
                            )}
                          </div>
                          <span className="verification-rate">
                            {(verificationStats.verification_rate * 100).toFixed(0)}% verified
                          </span>
                          <span className="verification-detail">
                            {verificationStats.verified} verified, {verificationStats.partially_verified} partial, {verificationStats.unverified} unverified
                            {verificationStats.contradicted > 0 && `, ${verificationStats.contradicted} contradicted`}
                            &nbsp;&middot;&nbsp;{verificationStats.total_claims} claims ({verificationStats.verifiable_claims} verifiable)
                          </span>
                        </div>
                      )}
                      <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>
                        {reviewReport}
                      </pre>
                      <div style={{
                        marginTop: '16px',
                        padding: '12px 16px',
                        background: 'rgba(99, 102, 241, 0.1)',
                        border: '1px solid rgba(99, 102, 241, 0.3)',
                        borderRadius: '8px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}>
                        <span style={{ color: 'var(--indigo)', fontSize: '13px' }}>
                          Deep Research 완료 — 결과를 학회 포스터로 변환할 수 있습니다
                        </span>
                        <button
                          onClick={(e) => {
                            posterTriggerRef.current = e.currentTarget;
                            handleGeneratePoster();
                          }}
                          disabled={posterLoading}
                          style={{
                            padding: '6px 16px',
                            background: '#6366f1',
                            color: 'white',
                            border: 'none',
                            borderRadius: '6px',
                            cursor: posterLoading ? 'wait' : 'pointer',
                            fontSize: '13px',
                            fontWeight: 500,
                            opacity: posterLoading ? 0.7 : 1,
                          }}
                        >
                          {posterLoading ? 'Generating...' : posterHtml ? 'View Poster' : 'Generate Poster'}
                        </button>
                      </div>
                    </div>
                  )}
                  {reviewStatus === 'failed' && (
                    <div className="review-error">
                      <p>Analysis Failed</p>
                      <p>{reviewProgress}</p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {!loading && papers.length === 0 && query && (
        <div className="centered-search">
          <div className="search-bar-fixed">
            <SearchBar
              key={attemptedQuery}
              initialQuery={attemptedQuery}
              onSearch={handleSearch}
              loading={loading}
              guidanceMessage={guidanceMessage}
              guidanceSticky={guidanceSticky}
              onQueryChange={() => setGuidanceMessage(null)}
            />
          </div>
          {/* A sticky guidance message is a hard failure (a 4xx/5xx, or a
              non-academic rejection), and SearchBar is already rendering it.
              The 500ms loading timer sets `query` before the request settles,
              so this branch matches on errors too — without this guard the
              page tells the user their keywords were wrong when the server
              was the thing that failed. SearchBar keeps rendering either way;
              gating the whole branch would blank the page instead. */}
          {!guidanceSticky && (
            /* role="status" because the loading branch's own live region
               unmounts the moment loading ends, so a screen-reader user who
               searched and got nothing was told nothing at all while focus
               dropped to <body>. */
            <div className="empty-state" role="status" aria-live="polite">
              {improvedQuery && <p>실제 검색어: <span>{improvedQuery}</span></p>}
              {searchNotices.length > 0 && <p>{searchNotices.join(' · ')}</p>}
              {timedOutSources.length > 0 ? (
                <>
                  <p>
                    {timedOutSources.length}개 출처가 제때 응답하지 않아 결과를 가져오지 못했습니다.
                  </p>
                  <p className="empty-state-detail">
                    응답하지 않은 출처: {timedOutSources.join(', ')} · 잠시 후 다시 시도해보세요.
                  </p>
                </>
              ) : (
                <p>{searchNotices.length > 0
                  ? '반환된 검색 결과가 없습니다. 위 검색 상태를 확인해주세요.'
                  : '검색 결과가 없습니다. 다른 키워드로 시도해보세요.'}</p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Poster Viewer Modal */}
      {posterOpen && posterHtml && (
        <div className="poster-modal-overlay" onClick={closePoster}>
          <div
            ref={posterModalRef}
            className="poster-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="poster-modal-title"
            tabIndex={-1}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="poster-modal-header">
              <span className="poster-modal-title" id="poster-modal-title">Conference Poster</span>
              <div className="poster-modal-actions">
                <button
                  className="poster-modal-btn"
                  onClick={() => {
                    const blob = new Blob([posterHtml], { type: 'text/html' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'poster.html';
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                  title="Download HTML"
                >
                  Download
                </button>
                <button
                  className="poster-modal-btn"
                  onClick={handleDownloadPosterPdf}
                  disabled={posterPdfLoading}
                  style={{
                    cursor: posterPdfLoading ? 'wait' : 'pointer',
                    opacity: posterPdfLoading ? 0.7 : 1,
                  }}
                  title="Download A3 PDF"
                >
                  {posterPdfLoading ? 'Generating PDF...' : 'Download PDF'}
                </button>
                <button className="poster-modal-close" aria-label="Close poster" onClick={closePoster}>
                  ✕
                </button>
              </div>
            </div>
            {posterWarning && (
              <div
                role="alert"
                style={{
                  margin: '12px 16px 0',
                  padding: '10px 12px',
                  border: '1px solid rgba(234, 179, 8, 0.45)',
                  borderRadius: '6px',
                  background: 'rgba(234, 179, 8, 0.12)',
                  color: '#92400e',
                  fontSize: '13px',
                }}
              >
                {posterWarning}
              </div>
            )}
            {posterPdfError && (
              <div
                role="alert"
                style={{
                  margin: '12px 16px 0',
                  padding: '10px 12px',
                  border: '1px solid rgba(234, 67, 53, 0.45)',
                  borderRadius: '6px',
                  background: 'rgba(234, 67, 53, 0.12)',
                  color: '#991b1b',
                  fontSize: '13px',
                }}
              >
                {posterPdfError}
              </div>
            )}
            <iframe
              className="poster-modal-iframe"
              srcDoc={posterHtml}
              sandbox=""
              title="Poster Preview"
            />
          </div>
        </div>
      )}
    </main>
  );
}

export default SearchPage;
