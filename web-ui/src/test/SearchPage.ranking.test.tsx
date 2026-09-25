import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SearchPage from '../components/SearchPage';
import { fetchBatchReferences, getGraphData, searchPapers, startDeepReview } from '../api/client';
import { trackSearchEvent } from '../analytics/events';
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
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, setShowLoginModal: vi.fn() }),
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

describe('SearchPage result ordering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  it('hides an unchanged executed query but displays source-specific differences', async () => {
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
    expect(screen.getByText('openalex: translated')).toBeInTheDocument();
    expect(screen.queryByText('arxiv: original')).not.toBeInTheDocument();
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

  it('shows executed queries and degraded/save status, never proposed analyzer text', async () => {
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
    expect(screen.getByText('openalex: actual translated query')).toBeInTheDocument();
    expect(screen.queryByText(/suggestion that never ran/)).not.toBeInTheDocument();
    expect(screen.getByText(/일부 검색만 완료/)).toHaveTextContent('dblp: 검색 응답이 제한되었습니다.');
    expect(screen.getByText(/저장 작업 용량이 부족/)).toBeInTheDocument();
    expect(screen.getByText(/google_scholar 출처가 제때/)).toBeInTheDocument();
  });

  it('discloses actual query and no-results save status for empty results', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: {}, total: 0,
      metadata: { executed_query: 'executed empty query', partial: true, save_status: 'no_results' },
    });
    render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('empty');
    expect(screen.getByText('executed empty query')).toBeInTheDocument();
    expect(screen.getByText(/저장할 검색 결과가 없어/)).toBeInTheDocument();
    expect(screen.queryByText(/다른 키워드로 시도/)).not.toBeInTheDocument();
  });

  it('discloses backend-shaped per-request fallbacks without exposing diagnostic text', async () => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: { arxiv: [paper('one', 'Partial paper', 0)] }, total: 1,
      stage_modes: {
        query_analysis_mode: 'original_query_fallback_error',
        ranking_mode: 'fallback_TimeoutError',
        source_search_mode: 'timeout_partial',
      },
      metadata: {
        executed_query: 'original', executed_queries: { arxiv: 'original' },
        partial: true, save_status: 'accepted',
        degraded: ['query_analysis_mode:original_query_fallback_error', 'ranking_mode:fallback_TimeoutError'],
      },
      degraded: ['internal diagnostic secret-token-123'],
    });
    render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('original');
    expect(screen.getByText(/질의 분석이 제한되어 원래 검색어/)).toBeInTheDocument();
    expect(screen.getByText(/결과 순위 계산이 제한되어 대체 순서/)).toBeInTheDocument();
    expect(screen.getByText(/일부 검색만 완료/)).toBeInTheDocument();
    expect(screen.getByText(/저장 완료를 보장하지 않습니다/)).toBeInTheDocument();
    expect(screen.queryByText(/secret-token-123|fallback_TimeoutError/)).not.toBeInTheDocument();
  });

  it.each([
    ['skipped_cache', '캐시 결과에 새 자동 저장 작업'],
    ['no_results', '저장할 검색 결과가 없어'],
    ['not_admitted_shutdown', '서버 종료 중이어서'],
    ['not_admitted_disconnect', '연결이 종료되어'],
  ] as const)('discloses backend save status %s', async (save_status, message) => {
    vi.mocked(searchPapers).mockResolvedValue({
      results: save_status === 'no_results' ? {} : { arxiv: [paper('one', 'Result', 0)] },
      total: save_status === 'no_results' ? 0 : 1,
      stage_modes: { query_analysis_mode: 'skipped_cache_hit', ranking_mode: 'skipped_cache_hit' },
      metadata: { executed_query: 'original', partial: false, save_status },
      cache_hit: save_status === 'skipped_cache',
    });
    render(<MemoryRouter><SearchPage /></MemoryRouter>);
    await submitSearch('original');
    expect(screen.getByText(new RegExp(message))).toBeInTheDocument();
    expect(screen.queryByText(/결과 순위 계산이 제한/)).not.toBeInTheDocument();
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
    await submitSearch('new');
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
