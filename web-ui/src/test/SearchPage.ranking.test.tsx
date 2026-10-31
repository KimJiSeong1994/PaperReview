import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SearchPage from '../components/SearchPage';
import { fetchBatchReferences, getGraphData, searchPapers, startDeepReview } from '../api/client';
import { api } from '../api/base';
import {
  fetchBatchReferences as fetchBatchReferencesRequest,
  getGraphData as getGraphDataRequest,
} from '../api/search';
import { trackPaperSelect, trackSearchEvent } from '../analytics/events';
import { useDeepReview } from '../hooks/useDeepReview';
import type { PaperReference } from '../api/search';
import GraphView from '../components/GraphView';
import PaperList from '../components/PaperList';
import SigmaGraphView from '../components/graph/SigmaGraphView';
import type { ReactNode } from 'react';

const sigmaMock = vi.hoisted(() => ({
  registerEvents: vi.fn(),
  setSettings: vi.fn(),
  sigma: {
    getGraph: () => ({
      hasNode: () => true,
      forEachNeighbor: () => {},
      getNodeAttributes: () => ({ label: 'Same title' }),
    }),
  },
}));

vi.mock('@react-sigma/core', () => ({
  SigmaContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  useRegisterEvents: () => sigmaMock.registerEvents,
  useSetSettings: () => sigmaMock.setSettings,
  useSigma: () => sigmaMock.sigma,
}));
vi.mock('sigma/rendering', () => ({ drawDiscNodeHover: vi.fn() }));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('../PlotlyChart', () => ({
  default: ({ data, onInitialized }: {
    data: Array<{ customdata?: string[] }>;
    onInitialized: (figure: unknown, node: unknown) => void;
  }) => (
    <div>
      {[...new Set([...data.flatMap(trace => trace.customdata ?? []), 'missing-node'])].map(key => (
        <button key={key} onClick={() => onInitialized({}, {
          on: (_event: string, handler: (event: unknown) => void) => handler({ points: [{ customdata: key }] }),
          removeListener: vi.fn(),
        })}>graph-click:{key}</button>
      ))}
    </div>
  ),
}));

vi.mock('../api/client', async () => {
  const reviewApi = await vi.importActual<typeof import('../api/review')>('../api/review');
  return {
    classifyPosterError: reviewApi.classifyPosterError,
    classifyPosterResponse: reviewApi.classifyPosterResponse,
    fetchBatchReferences: vi.fn(),
    generatePoster: vi.fn(),
    generatePosterDirect: vi.fn(),
    getGraphData: vi.fn(),
    saveBookmark: vi.fn(),
    searchPapers: vi.fn(),
    startDeepReview: vi.fn(),
    trackSearchClick: vi.fn(),
  };
});

vi.mock('../hooks/useDeepReview', () => ({ useDeepReview: vi.fn() }));
const authState = vi.hoisted(() => ({
  isAuthenticated: true,
  setShowLoginModal: vi.fn(),
}));
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => authState,
}));
vi.mock('../analytics/events', () => ({
  trackBookmarkSave: vi.fn(),
  trackDeepReviewComplete: vi.fn(),
  trackDeepReviewFail: vi.fn(),
  trackDeepReviewStart: vi.fn(),
  trackPaperSelect: vi.fn(),
  trackPosterGenerateComplete: vi.fn(),
  trackPosterGenerateFail: vi.fn(),
  trackPosterGenerateStart: vi.fn(),
  trackReportDownload: vi.fn(),
  trackSearchEvent: vi.fn(),
}));

function paper(docId: string, title: string, rank?: number) {
  return { doc_id: docId, title, authors: ['A. Researcher'], year: 2026, abstract: 'a', _rank: rank };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function submitSearch(query: string) {
  await act(async () => {
    fireEvent.change(screen.getByPlaceholderText('논문 검색'), { target: { value: query } });
    fireEvent.click(screen.getByRole('button', { name: '논문 검색' }));
  });
}

function renderedTitles(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('.paper-title')).map(
    (node) => node.textContent ?? '',
  );
}

function relatedBadges(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('.paper-card')).map(
    card => card.querySelector('.related-rank-badge')?.textContent ?? '',
  );
}

describe('search API cancellation signals', () => {
  it('passes the provided signal through to graph and reference requests', async () => {
    const signal = new AbortController().signal;
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { nodes: [], edges: [] } } as never);
    try {
      await getGraphDataRequest('[]', signal);
      await fetchBatchReferencesRequest([], signal);

      expect(post).toHaveBeenNthCalledWith(
        1,
        '/api/graph-data',
        { papers_json: '[]' },
        { signal },
      );
      expect(post).toHaveBeenNthCalledWith(
        2,
        '/api/batch-references',
        { papers: [], max_references: 5 },
        { signal },
      );
    } finally {
      post.mockRestore();
    }
  });
});

describe('SearchPage result ordering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.isAuthenticated = true;
    HTMLElement.prototype.scrollIntoView = vi.fn();
    vi.mocked(useDeepReview).mockReturnValue({
      reviewSessionId: null,
      reviewStatus: 'idle',
      reviewProgress: '',
      reviewReport: '',
      verificationStats: null,
      startReview: vi.fn(),
      resetReview: vi.fn(),
    } as never);
    vi.mocked(getGraphData).mockResolvedValue({ nodes: [], edges: [] });
    vi.mocked(fetchBatchReferences).mockResolvedValue({ references: [] });
  });

  it('renders the backend ranking order, not the per-source bucket order', async () => {
    // The API groups papers by source. Walking the buckets yields
    // [arxiv-1, arxiv-2, openalex-1]; the ranker put the openalex paper first.
    vi.mocked(searchPapers).mockResolvedValue({
      results: {
        arxiv: [paper('a1', 'Arxiv Second', 1), paper('a2', 'Arxiv Third', 2)],
        openalex: [paper('o1', 'OpenAlex First', 0)],
      },
      total: 3,
    } as never);

    const { container } = render(
      <MemoryRouter initialEntries={['/']}>
        <SearchPage />
      </MemoryRouter>,
    );
    await submitSearch('attention');

    await waitFor(() => expect(renderedTitles(container)).toHaveLength(3));
    expect(renderedTitles(container)).toEqual([
      'OpenAlex First',
      'Arxiv Second',
      'Arxiv Third',
    ]);
  });

  it('renders the first list before graph and reference enrichment complete', async () => {
    const graph = deferred<{ nodes: []; edges: [] }>();
    const references = deferred<{ references: [] }>();
    vi.mocked(searchPapers).mockResolvedValue({
      results: { arxiv: [paper('first', 'First list result', 0)] },
      total: 1,
    } as never);
    vi.mocked(getGraphData).mockReturnValue(graph.promise);
    vi.mocked(fetchBatchReferences).mockReturnValue(references.promise);

    const { container } = render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('first list');

    expect(renderedTitles(container)).toEqual(['First list result']);
    expect(screen.getByPlaceholderText('논문 검색')).not.toBeDisabled();
    expect(getGraphData).toHaveBeenCalledTimes(1);
    expect(fetchBatchReferences).toHaveBeenCalledTimes(1);

    await act(async () => {
      graph.resolve({ nodes: [], edges: [] });
      references.resolve({ references: [] });
    });
  });

  it('marks and schedules list timing after the published list commits', async () => {
    const graph = deferred<{ nodes: []; edges: [] }>();
    const references = deferred<{ references: [] }>();
    const commitSnapshots: string[] = [];
    const frameSnapshots: string[] = [];
    const mark = vi.spyOn(globalThis.performance, 'mark').mockImplementation((name: string) => {
      if (name.endsWith('.list-commit')) {
        commitSnapshots.push(renderedTitles(document.body).join('|'));
      }
      return undefined as unknown as PerformanceMark;
    });
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => {
      frameSnapshots.push(renderedTitles(document.body).join('|'));
      return 1;
    }));
    vi.stubGlobal('cancelAnimationFrame', vi.fn());
    vi.mocked(searchPapers).mockResolvedValue({
      results: { arxiv: [paper('committed', 'Committed list result', 0)] },
      total: 1,
    } as never);
    vi.mocked(getGraphData).mockReturnValue(graph.promise);
    vi.mocked(fetchBatchReferences).mockReturnValue(references.promise);

    const view = render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('post commit timing');

    expect(commitSnapshots).toEqual(['Committed list result']);
    expect(frameSnapshots).toEqual(['Committed list result']);
    view.unmount();
    mark.mockRestore();
    vi.unstubAllGlobals();
  });

  it('publishes empty and error lists through the post-commit timing path', async () => {
    const commitNames: string[] = [];
    const frameNames: string[] = [];
    const mark = vi.spyOn(globalThis.performance, 'mark').mockImplementation((name: string) => {
      if (name.endsWith('.list-commit')) commitNames.push(name);
      return undefined as unknown as PerformanceMark;
    });
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => {
      frameNames.push('frame');
      return 1;
    }));
    vi.stubGlobal('cancelAnimationFrame', vi.fn());
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(searchPapers)
      .mockResolvedValueOnce({ results: {}, total: 0 })
      .mockRejectedValueOnce(new Error('empty-path error'));

    const view = render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('empty result');
    await submitSearch('error result');

    expect(commitNames).toHaveLength(2);
    expect(frameNames).toHaveLength(2);
    view.unmount();
    error.mockRestore();
    mark.mockRestore();
    vi.unstubAllGlobals();
  });

  it('keeps executed queries hidden while rendering returned results', async () => {
    vi.mocked(searchPapers)
      .mockResolvedValueOnce({
        results: { arxiv: [paper('one', 'Result', 0)] }, total: 1,
        metadata: { executed_query: 'original' },
      })
      .mockResolvedValueOnce({
        results: { arxiv: [paper('one', 'Result', 0)] }, total: 1,
        metadata: { executed_query: 'original', executed_queries: { arxiv: ['original'], openalex: ['translated'] } },
      });
    render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('original');
    expect(screen.queryByText(/실제 검색어:/)).not.toBeInTheDocument();
    await submitSearch('original');
    expect(screen.getAllByText('Result').length).toBeGreaterThan(0);
    expect(screen.queryByText('OpenAlex: translated')).not.toBeInTheDocument();
    expect(screen.queryByText('arXiv: original')).not.toBeInTheDocument();
  });

  it('preserves retrieved papers when a low-confidence classification is non-authoritative', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: { openalex: [paper('fallback', 'Retrieved despite uncertain classification', 0)] },
      total: 1,
      query_analysis: {
        is_academic: false,
        analysis_status: 'low_confidence_original_query',
        intent: 'paper_search',
        keywords: [],
        improved_query: 'original',
        search_filters: {},
        confidence: 0.2,
        original_query: 'original',
      },
    });
    render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('original');
    expect(screen.getAllByText('Retrieved despite uncertain classification')[0]).toBeVisible();
    expect(screen.queryByText(/질의 분석이 제한되어 원래 검색어/)).not.toBeInTheDocument();
    expect(screen.queryByText(/학술 논문 및 연구 관련 주제를 입력/)).not.toBeInTheDocument();
    expect(trackSearchEvent).not.toHaveBeenCalledWith(
      expect.anything(), 'non_academic', expect.anything(), expect.anything(), expect.anything(),
    );
  });

  it('uses result keys for list communities and related highlights despite storage collisions', () => {
    const papers = [
      { ...paper('legacy', 'Same title', 0), result_key: 'doi:one' },
      { ...paper('legacy', 'Same title', 1), result_key: 'doi:two' },
      { ...paper('legacy', 'Same title', 2), result_key: 'doi:three' },
    ];
    const { container } = render(<PaperList
      papers={papers} selectedPaper={papers[0]} onSelect={vi.fn()}
      highlightedPapers={new Set(['doi:two'])}
      communityByPaper={{
        'doi:one': { communityId: 0, label: 'First community' },
        'doi:two': { communityId: 1, label: 'Second community' },
      }}
    />);
    expect(screen.getByText('First community')).toBeInTheDocument();
    expect(screen.getByText('Second community')).toBeInTheDocument();
    const cards = container.querySelectorAll('.paper-card');
    expect(cards[1]).toHaveClass('graph-related');
    expect(cards[2]).not.toHaveClass('graph-related');
    expect(screen.getAllByText('유사 1')).toHaveLength(1);
  });

  it('derives initial, list, and node highlights from one result-key-ranked neighborhood', async () => {
    const origin = { ...paper('legacy', 'Origin', 0), result_key: 'doi:origin' };
    const alpha = { ...paper('legacy', 'Alpha', 1), result_key: 'doi:alpha' };
    const beta = { ...paper('legacy', 'Beta', 2), result_key: 'doi:beta' };
    const zeta = { ...paper('legacy', 'Zeta', 3), result_key: 'doi:zeta' };
    const results = [origin, alpha, beta, zeta];
    vi.mocked(searchPapers).mockResolvedValue({
      results: { arxiv: results }, total: results.length,
    } as never);
    vi.mocked(getGraphData).mockResolvedValue({
      nodes: results.map((result, index) => ({
        id: result.result_key,
        title: result.title,
        x: index,
        y: 0,
      })),
      edges: [
        { source: 'doi:origin', target: 'doi:zeta', weight: 0.99 },
        { source: 'doi:origin', target: 'doi:beta', weight: 0.9 },
        { source: 'doi:origin', target: 'doi:alpha', weight: 0.9 },
        { source: 'doi:alpha', target: 'doi:beta', weight: 0.7 },
      ],
    });

    const { container } = render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('graph neighbors');
    await waitFor(() => expect(relatedBadges(container)).toEqual([
      '', '유사 2', '유사 3', '유사 1',
    ]));

    fireEvent.click(container.querySelectorAll('.paper-card')[1]);
    await waitFor(() => expect(relatedBadges(container)).toEqual([
      '', '', '유사 2', '',
    ]));
    // The origin keeps its dedicated badge; relation cards still include it first.
    const relatedTitles = () => Array.from(
      container.querySelectorAll('.detail-related-title'),
      element => element.textContent,
    );
    expect(relatedTitles()).toEqual(['Origin', 'Beta']);
    const listSelectionBadges = relatedBadges(container);
    fireEvent.click(screen.getByRole('button', { name: 'graph-click:doi:alpha' }));
    await waitFor(() => expect(relatedBadges(container)).toEqual(listSelectionBadges));
    expect(relatedTitles()).toEqual(['Origin', 'Beta']);

    expect(trackPaperSelect).toHaveBeenCalledWith('list', expect.objectContaining({ rank: 2 }));
    expect(trackPaperSelect).toHaveBeenCalledWith('graph', expect.objectContaining({ rank: 2 }));
  });

  it('keeps independently identified same-title references independently selectable', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: { arxiv: [{ ...paper('legacy', 'Same title', 0), result_key: 'doi:origin' }] }, total: 1,
    });
    vi.mocked(fetchBatchReferences).mockResolvedValue({ references: ['one', 'two'].map(paper_id => ({
      paper_id, title: 'Same title', authors: [], year: '2025', citations: 0,
      abstract: '', url: '', source: 'openalex',
    })) });
    vi.mocked(getGraphData).mockReturnValue(new Promise(() => {}));
    render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('references');
    await waitFor(() => expect(screen.getAllByRole('checkbox')).toHaveLength(3));
    const boxes = screen.getAllByRole('checkbox');
    fireEvent.click(boxes[2]);
    expect(boxes[0]).not.toBeChecked();
    expect(boxes[1]).not.toBeChecked();
    expect(boxes[2]).toBeChecked();
  });

  it('Sigma selects and clicks exact result keys without same-title fallback', () => {
    const first = { ...paper('legacy', 'Same title'), result_key: 'doi:one' };
    const second = { ...paper('legacy', 'Same title'), result_key: 'doi:two' };
    const onNodeClick = vi.fn();
    render(<SigmaGraphView
      graphData={{
        nodes: [
          { id: first.result_key, title: first.title, x: 0, y: 0 },
          { id: second.result_key, title: second.title, x: 1, y: 1 },
        ], edges: [],
      }}
      papers={[first, second]} selectedPaper={second}
      highlightedPapers={new Set()} onNodeClick={onNodeClick}
      showLabels={true} edgeOpacity={0.5} minCitations={0} yearFilter={null}
      graphMode="landscape" pathEdgeKeys={new Set()}
    />);
    const handlers = sigmaMock.registerEvents.mock.calls.at(-1)![0];
    handlers.clickNode({ node: second.result_key });
    expect(onNodeClick).toHaveBeenCalledExactlyOnceWith(second);
    handlers.clickNode({ node: 'unknown' });
    handlers.clickNode({ node: 'legacy' });
    expect(onNodeClick).toHaveBeenCalledTimes(1);
    const settings = sigmaMock.setSettings.mock.calls.at(-1)![0];
    expect(settings.nodeReducer(second.result_key, { size: 10 }).zIndex).toBe(3);
    expect(settings.nodeReducer(first.result_key, { size: 10 }).zIndex).not.toBe(3);
  });

  it('keeps papers without a rank, sorted after the ranked ones', async () => {
    // Partial/timed-out responses and papers beyond the ranking cap arrive
    // without _rank. They must still render rather than disappear.
    vi.mocked(searchPapers).mockResolvedValue({
      results: {
        arxiv: [paper('a1', 'Unranked Tail'), paper('a2', 'Ranked Head', 0)],
      },
      total: 2,
    } as never);

    const { container } = render(
      <MemoryRouter initialEntries={['/']}>
        <SearchPage />
      </MemoryRouter>,
    );
    await submitSearch('attention');

    await waitFor(() => expect(renderedTitles(container)).toHaveLength(2));
    expect(renderedTitles(container)).toEqual(['Ranked Head', 'Unranked Tail']);
  });

  it('selects and hands off only one same-title paper despite colliding storage IDs', async () => {
    const first = { ...paper('legacy', 'Same title', 0), result_key: 'doi:10.1000/one', doi: '10.1000/one', pdf_url: 'https://example.org/one.pdf' };
    const second = { ...paper('legacy', 'Same title', 1), result_key: 'doi:10.1000/two', doi: '10.1000/two', pdf_url: 'https://example.org/two.pdf' };
    let resolveReferences!: (value: { references: PaperReference[] }) => void;
    vi.mocked(fetchBatchReferences).mockReturnValue(new Promise(resolve => { resolveReferences = resolve; }));
    vi.mocked(getGraphData).mockReturnValue(new Promise(() => {}));
    vi.mocked(searchPapers).mockResolvedValue({ results: { arxiv: [first, second] }, total: 2 });
    vi.mocked(startDeepReview).mockResolvedValue({ session_id: 'selected-only' } as never);
    const { container } = render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('same title');
    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[1]);
    fireEvent.click(container.querySelectorAll('.paper-card')[1]);
    await act(async () => {
      resolveReferences({ references: [{
        title: 'Additional reference', authors: [], year: '2025', citations: 0,
        abstract: '', url: '', source: 'reference', paper_id: 'reference-id',
      }] });
    });
    expect(renderedTitles(container)).toHaveLength(3);
    expect(checkboxes[0]).not.toBeChecked();
    expect(checkboxes[1]).toBeChecked();
    expect(container.querySelectorAll('.paper-card.selected')).toHaveLength(1);
    expect(container.querySelectorAll('.paper-card')[1]).toHaveAttribute('aria-current', 'true');

    const downloads: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      downloads.push(this.href);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Tools' }));
    fireEvent.click(screen.getByRole('button', { name: 'Download PDFs (1)' }));
    expect(downloads).toEqual(['https://example.org/two.pdf']);
    click.mockRestore();
    fireEvent.click(screen.getByRole('button', { name: 'Tools' }));
    fireEvent.click(screen.getByRole('button', { name: 'Deep Research (1)' }));
    await waitFor(() => expect(startDeepReview).toHaveBeenCalledWith({
      paper_ids: ['legacy'],
      papers: [expect.objectContaining(second)],
      num_researchers: 1,
    }));
    expect(trackSearchEvent).toHaveBeenCalledTimes(1);
    expect(vi.mocked(searchPapers).mock.calls[0][0]).toEqual({
      query: 'same title', max_results: 50, sort_by: 'relevance', use_llm_search: false,
      sources: ['arxiv', 'connected_papers', 'google_scholar', 'openalex', 'dblp', 'openalex_korean'],
    });
  });

  it('hides executed queries and diagnostic, save, and provider status while preserving results', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: { arxiv: [paper('one', 'Result', 0)] }, total: 1,
      query_analysis: { improved_query: 'suggestion that never ran' },
      metadata: {
        executed_query: 'actual query',
        executed_queries: { openalex: ['actual translated query'] },
        partial: true, save_status: 'not_admitted_capacity',
      },
      stage_modes: { source_modes: { dblp: 'error' } },
      source_timeouts: { google_scholar: true }, degraded: ['ranking_timeout'],
    } as never);
    render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('한국어 질문');
    expect(screen.getAllByText('Result').length).toBeGreaterThan(0);
    expect(screen.queryByText('OpenAlex: actual translated query')).not.toBeInTheDocument();
    expect(screen.queryByText(/suggestion that never ran/)).not.toBeInTheDocument();
    expect(screen.queryByText(/일부 검색만 완료/)).not.toBeInTheDocument();
    expect(screen.queryByText(/DBLP: 검색 응답이 제한되었습니다/)).not.toBeInTheDocument();
    expect(screen.queryByText(/일부 검색 기능이 제한/)).not.toBeInTheDocument();
    expect(screen.queryByText(/저장 작업 용량이 부족/)).not.toBeInTheDocument();
    expect(screen.queryByText(/출처가 제때 응답하지 않아|응답하지 않은 출처/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Google Scholar/)).not.toBeInTheDocument();
  });

  it('keeps executed query, partial-result, and save metadata out of the empty state', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: {}, total: 0,
      metadata: { executed_query: 'executed empty query', partial: true, save_status: 'no_results' },
    });
    render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('empty');
    expect(screen.getByText('검색 결과가 없습니다. 잠시 후 다시 시도하거나 검색어를 바꿔보세요.')).toBeInTheDocument();
    expect(screen.queryByText('executed empty query')).not.toBeInTheDocument();
    expect(screen.queryByText(/실제 검색어:|일부 검색만 완료|저장할 검색 결과가 없어/)).not.toBeInTheDocument();
  });

  it('keeps fallback and diagnostic metadata out of returned results', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: { arxiv: [paper('one', 'Partial paper', 0)] }, total: 1,
      stage_modes: {
        query_analysis_mode: 'original_query_fallback_error',
        ranking_mode: 'fallback_TimeoutError',
        source_search_mode: 'timeout_partial',
      },
      metadata: {
        executed_query: 'backend fallback query', executed_queries: { arxiv: 'provider fallback query' },
        partial: true, save_status: 'accepted',
        degraded: ['query_analysis_mode:original_query_fallback_error', 'ranking_mode:fallback_TimeoutError'],
      },
      degraded: ['internal diagnostic secret-token-123'],
    });
    render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('original');
    expect(screen.getAllByText('Partial paper').length).toBeGreaterThan(0);
    expect(screen.queryByText(/질의 분석이 제한되어 원래 검색어/)).not.toBeInTheDocument();
    expect(screen.queryByText(/결과 순위 계산이 제한되어 대체 순서/)).not.toBeInTheDocument();
    expect(screen.queryByText(/일부 검색만 완료/)).not.toBeInTheDocument();
    expect(screen.queryByText(/일부 검색 기능이 제한/)).not.toBeInTheDocument();
    expect(screen.queryByText('backend fallback query')).not.toBeInTheDocument();
    expect(screen.queryByText('provider fallback query')).not.toBeInTheDocument();
    expect(screen.queryByText(/저장 요청이 접수되었습니다/)).not.toBeInTheDocument();
    expect(screen.queryByText(/secret-token-123|fallback_TimeoutError/)).not.toBeInTheDocument();
  });

  it.each([
    ['accepted', '저장 완료를 보장하지 않습니다'],
    ['not_requested', '자동 저장을 요청하지 않았습니다'],
    ['skipped_cache', '캐시 결과에 새 자동 저장 작업'],
    ['no_results', '저장할 검색 결과가 없어'],
    ['not_admitted_capacity', '저장 작업 용량이 부족'],
    ['not_admitted_shutdown', '서버 종료 중이어서'],
    ['not_admitted_disconnect', '연결이 종료되어'],
  ] as const)('keeps backend save status %s out of the UI', async (save_status, message) => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: save_status === 'no_results' ? {} : { arxiv: [paper('one', 'Result', 0)] },
      total: save_status === 'no_results' ? 0 : 1,
      stage_modes: save_status === 'skipped_cache'
        ? { query_analysis_mode: 'skipped_cache_hit', ranking_mode: 'skipped_cache_hit' }
        : { query_analysis_mode: 'llm', ranking_mode: 'llm' },
      metadata: { executed_query: 'original', partial: false, save_status },
      cache_hit: save_status === 'skipped_cache',
    });
    const { container } = render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('original');
    expect(screen.queryByText(new RegExp(message))).not.toBeInTheDocument();
    expect(screen.queryByText(/결과 순위 계산이 제한/)).not.toBeInTheDocument();
    expect(container.querySelector('.results-save-information')).toBeNull();
    if (save_status === 'no_results') {
      expect(screen.getByText('검색 결과가 없습니다. 잠시 후 다시 시도하거나 검색어를 바꿔보세요.')).toBeInTheDocument();
    } else {
      expect(screen.getAllByText('Result').length).toBeGreaterThan(0);
    }
  });

  it('never renders provider timeout or diagnostic status', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: { arxiv: [paper('one', 'Result', 0)] }, total: 1,
      stage_modes: { source_modes: {
        connected_papers: 'error_HTTP429_secret-token',
        'unknown-secret-provider': 'error_secret-token',
        dblp: 'timeout_internal-reset',
      } },
      source_timeouts: { dblp: true, 'unknown-timeout-token': true },
      metadata: {
        executed_queries: { 'unknown-query-provider-token': 'translated query' },
        partial: true, save_status: 'accepted',
      },
    });
    const { container } = render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('original');
    expect(screen.queryByText(/출처가 제때 응답하지 않아|응답하지 않은 출처|검색 응답이 제한/)).not.toBeInTheDocument();
    expect(screen.queryByText('일부 출처: translated query')).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(/secret-token|unknown-.*token|unknown-secret-provider|internal-reset|HTTP429/);
  });

  it('reports capacity errors without blaming an empty result on the query', async () => {
    vi.mocked(searchPapers).mockRejectedValue({ response: { status: 503, data: { detail: { reason: 'capacity' } } } });
    render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('capacity');
    expect(screen.getByText(/현재 요청을 처리할 수 없습니다\(503\)/)).toBeInTheDocument();
    expect(screen.queryByText(/다른 키워드로 시도/)).not.toBeInTheDocument();
  });

  it('ignores old reference enrichment after a newer search and selection', async () => {
    let resolveOld!: (value: { references: PaperReference[] }) => void;
    vi.mocked(fetchBatchReferences).mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
    vi.mocked(getGraphData).mockReturnValue(new Promise(() => {}));
    vi.mocked(searchPapers)
      .mockResolvedValueOnce({ results: { arxiv: [paper('old', 'Old result', 0)] }, total: 1 })
      .mockResolvedValueOnce({ results: { arxiv: [paper('new', 'New result', 0)] }, total: 1 });
    const { container } = render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('old');
    const oldReferenceSignal = vi.mocked(fetchBatchReferences).mock.calls[0][1] as AbortSignal;
    await submitSearch('new');
    expect(oldReferenceSignal.aborted).toBe(true);
    fireEvent.click(screen.getByRole('checkbox'));
    await act(async () => {
      resolveOld({ references: [{
        title: 'Stale reference', authors: [], year: '2025', citations: 0,
        abstract: '', url: '', source: 'reference', paper_id: 'stale-id',
      }] });
    });
    expect(renderedTitles(container)).toEqual(['New result']);
    expect(screen.getByRole('checkbox')).toBeChecked();
    expect(trackSearchEvent).toHaveBeenCalledTimes(2);
  });

  it('uses a parent signal for references and a replaceable child signal for graphs', async () => {
    const seedGraph = deferred<{ nodes: []; edges: [] }>();
    const references = deferred<{ references: PaperReference[] }>();
    const mergedGraph = deferred<{ nodes: []; edges: [] }>();
    vi.mocked(searchPapers)
      .mockResolvedValueOnce({ results: { arxiv: [paper('old', 'Old result', 0)] }, total: 1 })
      .mockResolvedValueOnce({ results: { arxiv: [paper('new', 'New result', 0)] }, total: 1 });
    vi.mocked(getGraphData)
      .mockReturnValueOnce(seedGraph.promise)
      .mockReturnValueOnce(mergedGraph.promise)
      .mockResolvedValue({ nodes: [], edges: [] });
    vi.mocked(fetchBatchReferences)
      .mockReturnValueOnce(references.promise)
      .mockResolvedValue({ references: [] });

    const { container, unmount } = render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('old');

    const parentSignal = vi.mocked(searchPapers).mock.calls[0][1] as AbortSignal;
    const referenceSignal = vi.mocked(fetchBatchReferences).mock.calls[0][1] as AbortSignal;
    const seedGraphSignal = vi.mocked(getGraphData).mock.calls[0][1] as AbortSignal;
    expect(referenceSignal).toBe(parentSignal);
    expect(seedGraphSignal).toBeInstanceOf(AbortSignal);
    expect(seedGraphSignal).not.toBe(parentSignal);
    expect(parentSignal.aborted).toBe(false);

    await act(async () => {
      references.resolve({
        references: [{
          title: 'Merged reference',
          authors: [],
          year: '2025',
          citations: 0,
          abstract: '',
          url: '',
          source: 'reference',
          paper_id: 'merged-reference',
        }],
      });
    });
    await waitFor(() => expect(getGraphData).toHaveBeenCalledTimes(2));
    const mergedGraphSignal = vi.mocked(getGraphData).mock.calls[1][1] as AbortSignal;
    expect(seedGraphSignal.aborted).toBe(true);
    expect(mergedGraphSignal.aborted).toBe(false);

    await submitSearch('new');
    expect(parentSignal.aborted).toBe(true);
    expect(referenceSignal.aborted).toBe(true);
    expect(mergedGraphSignal.aborted).toBe(true);

    await act(async () => {
      seedGraph.resolve({ nodes: [], edges: [] });
      mergedGraph.resolve({ nodes: [], edges: [] });
    });
    expect(renderedTitles(container)).toEqual(['New result']);
    unmount();
  });

  it('aborts enrichment on authentication lifetime changes and unmount', async () => {
    const graph = deferred<{ nodes: []; edges: [] }>();
    const references = deferred<{ references: [] }>();
    vi.mocked(searchPapers).mockResolvedValue({
      results: { arxiv: [paper('auth', 'Auth result', 0)] }, total: 1,
    } as never);
    vi.mocked(getGraphData).mockReturnValue(graph.promise);
    vi.mocked(fetchBatchReferences).mockReturnValue(references.promise);

    const view = render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('auth transition');
    const parentSignal = vi.mocked(searchPapers).mock.calls[0][1] as AbortSignal;
    const graphSignal = vi.mocked(getGraphData).mock.calls[0][1] as AbortSignal;
    const referenceSignal = vi.mocked(fetchBatchReferences).mock.calls[0][1] as AbortSignal;
    expect(screen.getByText('관계를 확장하는 중')).toBeInTheDocument();

    authState.isAuthenticated = false;
    await act(async () => {
      view.rerender(<MemoryRouter><SearchPage /></MemoryRouter>);
    });
    expect(parentSignal.aborted).toBe(true);
    expect(graphSignal.aborted).toBe(true);
    expect(referenceSignal.aborted).toBe(true);
    expect(screen.queryByText('그래프 준비 완료')).not.toBeInTheDocument();
    expect(screen.queryByText('관계를 확장하는 중')).not.toBeInTheDocument();

    const graphCallCount = vi.mocked(getGraphData).mock.calls.length;
    authState.isAuthenticated = true;
    await act(async () => {
      view.rerender(<MemoryRouter><SearchPage /></MemoryRouter>);
    });
    expect(getGraphData).toHaveBeenCalledTimes(graphCallCount);

    view.unmount();
    await act(async () => {
      graph.resolve({ nodes: [], edges: [] });
      references.resolve({ references: [] });
    });
  });

  it('clears the primary loading state when auth changes mid-search', async () => {
    const search = deferred<{ results: Record<string, never>; total: number }>();
    vi.mocked(searchPapers).mockReturnValue(search.promise as never);

    const view = render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await act(async () => {
      fireEvent.change(screen.getByPlaceholderText('논문 검색'), { target: { value: 'mid-search logout' } });
      fireEvent.click(screen.getByRole('button', { name: '논문 검색' }));
    });
    await waitFor(() => expect(screen.getByText('집현전 서고 탐색 중')).toBeInTheDocument());

    authState.isAuthenticated = false;
    await act(async () => {
      view.rerender(<MemoryRouter><SearchPage /></MemoryRouter>);
    });
    expect(screen.queryByText('집현전 서고 탐색 중')).not.toBeInTheDocument();
    const searchButton = screen.getByRole('button', { name: '논문 검색' });
    expect(searchButton).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText('논문 검색'), {
      target: { value: 'fresh auth query' },
    });
    expect(screen.getByRole('button', { name: '논문 검색' })).not.toBeDisabled();

    view.unmount();
    await act(async () => {
      search.resolve({ results: {}, total: 0 });
    });
  });

  it('clears authenticated search state across logout and login on the same page', async () => {
    const graph = deferred<{ nodes: []; edges: [] }>();
    const references = deferred<{ references: [] }>();
    vi.mocked(searchPapers).mockResolvedValue({
      query_hash: 'alpha-hash',
      stage_modes: { ranking_variant: 'alpha-variant' },
      results: { arxiv: [paper('alpha', 'Authenticated alpha', 0)] },
      total: 1,
    } as never);
    vi.mocked(getGraphData).mockReturnValue(graph.promise);
    vi.mocked(fetchBatchReferences).mockReturnValue(references.promise);
    const view = render(<MemoryRouter><SearchPage /></MemoryRouter>);
    const { container } = view;
    await submitSearch('alpha');
    expect(renderedTitles(container)).toEqual(['Authenticated alpha']);
    expect(screen.getByDisplayValue('alpha')).toBeInTheDocument();

    authState.isAuthenticated = false;
    await act(async () => {
      view.rerender(<MemoryRouter><SearchPage /></MemoryRouter>);
    });
    expect(renderedTitles(container)).toEqual([]);
    expect(screen.getByPlaceholderText('논문 검색')).toHaveValue('');
    expect(screen.queryByText('관계를 확장하는 중')).not.toBeInTheDocument();

    authState.isAuthenticated = true;
    await act(async () => {
      view.rerender(<MemoryRouter><SearchPage /></MemoryRouter>);
    });
    expect(renderedTitles(container)).toEqual([]);
    expect(screen.getByPlaceholderText('논문 검색')).toHaveValue('');

    await act(async () => {
      graph.resolve({ nodes: [], edges: [] });
      references.resolve({ references: [] });
    });
    expect(renderedTitles(container)).toEqual([]);
    view.unmount();
  });

  it('keeps the primary list when graph and reference enrichment fail', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.mocked(searchPapers).mockResolvedValue({
      results: { arxiv: [paper('failed', 'Primary result survives', 0)] }, total: 1,
    } as never);
    vi.mocked(getGraphData).mockRejectedValue(new Error('graph failed'));
    vi.mocked(fetchBatchReferences).mockRejectedValue(new Error('references failed'));

    const { container } = render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('failed enrichment');

    await waitFor(() => expect(screen.getByText('그래프 준비 완료')).toBeInTheDocument());
    expect(renderedTitles(container)).toEqual(['Primary result survives']);
    expect(warn).toHaveBeenCalledTimes(2);
    warn.mockRestore();
  });

  it('aborts the active search and enrichment lifetimes on unmount', async () => {
    const graph = deferred<{ nodes: []; edges: [] }>();
    const references = deferred<{ references: [] }>();
    vi.mocked(searchPapers).mockResolvedValue({
      results: { arxiv: [paper('unmount', 'Unmount result', 0)] }, total: 1,
    } as never);
    vi.mocked(getGraphData).mockReturnValue(graph.promise);
    vi.mocked(fetchBatchReferences).mockReturnValue(references.promise);

    const view = render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('unmount');
    const parentSignal = vi.mocked(searchPapers).mock.calls[0][1] as AbortSignal;
    const graphSignal = vi.mocked(getGraphData).mock.calls[0][1] as AbortSignal;
    const referenceSignal = vi.mocked(fetchBatchReferences).mock.calls[0][1] as AbortSignal;

    view.unmount();
    expect(parentSignal.aborted).toBe(true);
    expect(graphSignal.aborted).toBe(true);
    expect(referenceSignal.aborted).toBe(true);

    await act(async () => {
      graph.resolve({ nodes: [], edges: [] });
      references.resolve({ references: [] });
    });
  });

  it('graph clicks resolve exact result identity, not colliding title or storage ID', () => {
    const first = { ...paper('legacy', 'Same title', 0), result_key: 'doi:10.1000/one', doi: '10.1000/one' };
    const second = { ...paper('legacy', 'Same title', 1), result_key: 'doi:10.1000/two', doi: '10.1000/two' };
    const onNodeClick = vi.fn();
    render(<GraphView
      graphData={{
        nodes: [
          { id: first.result_key, title: first.title, x: -1, y: 0 },
          { id: second.result_key, title: second.title, x: 1, y: 0 },
          { id: 'missing-node', title: first.title, x: 0, y: 1 },
        ],
        edges: [{ source: first.result_key, target: second.result_key, weight: 1 }],
      }}
      papers={[first, second]}
      selectedPaper={first}
      highlightedPapers={new Set()}
      onNodeClick={onNodeClick}
    />);
    fireEvent.click(screen.getByRole('button', { name: `graph-click:${second.result_key}` }));
    expect(onNodeClick).toHaveBeenCalledExactlyOnceWith(second);
    fireEvent.click(screen.getByRole('button', { name: 'graph-click:missing-node' }));
    expect(onNodeClick).toHaveBeenCalledTimes(1);
    expect(first.doc_id).toBe('legacy');
    expect(second.doc_id).toBe('legacy');
  });
});
