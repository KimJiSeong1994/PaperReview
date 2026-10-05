import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Data, Layout } from '../PlotlyChart';
import type { GraphData, Paper } from '../types';
import GraphView from './GraphView';

type PlotlyClickHandler = (event: { points?: Array<{ customdata?: unknown }> }) => void;

type CapturedTrace = {
  mode?: string;
  customdata?: unknown[];
  text?: unknown;
  hovertext?: unknown;
  x?: unknown[];
  y?: unknown[];
};

const plotlyMock = vi.hoisted(() => {
  const listeners = new Map<string, PlotlyClickHandler>();
  return {
    listeners,
    graphDiv: {
      on: vi.fn((eventName: string, handler: PlotlyClickHandler) => {
        listeners.set(eventName, handler);
      }),
      removeListener: vi.fn((eventName: string, handler: PlotlyClickHandler) => {
        if (listeners.get(eventName) === handler) listeners.delete(eventName);
      }),
    },
  };
});

vi.mock('../PlotlyChart', () => ({
  default: ({
    data,
    layout,
    onInitialized,
  }: {
    data: Data[];
    layout: Partial<Layout>;
    onInitialized?: (figure: unknown, graphDiv: unknown) => void;
  }) => (
    <button
      type="button"
      data-testid="graph-plot"
      data-plot-data={JSON.stringify(data)}
      data-plot-layout={JSON.stringify(layout)}
      onClick={() => onInitialized?.({}, plotlyMock.graphDiv)}
    />
  ),
}));

const papers: Paper[] = [
  { doc_id: 'origin', title: 'Origin paper', authors: ['A'], year: 2020 },
  { doc_id: 'selected', title: 'Selected paper', authors: ['B'], year: 2021 },
  { doc_id: 'hop-two', title: 'Hop two paper', authors: ['C'], year: 2022 },
];

const graphData: GraphData = {
  nodes: [
    { id: 'origin', x: -0.4, y: 0, title: 'Origin paper', community_id: 0, citations: 10, year: 2020 },
    { id: 'selected', x: 0, y: 0, title: 'Selected paper', community_id: 0, citations: 4, year: 2021 },
    { id: 'hop-two', x: 0.4, y: 0, title: 'Hop two paper', community_id: 1, citations: 8, year: 2022 },
  ],
  edges: [
    { source: 'origin', target: 'selected', weight: 0.9, shared_terms: ['graph'] },
    { source: 'selected', target: 'hop-two', weight: 0.8, shared_terms: ['retrieval'] },
  ],
  meta: {
    edge_method: 'title_keyword_jaccard',
    edge_label: '제목·키워드 유사도',
    directed: false,
    communities: [
      { community_id: 0, label: 'Graph', nodes: ['origin', 'selected'], size: 2 },
      { community_id: 1, label: 'Retrieval', nodes: ['hop-two'], size: 1 },
    ],
  },
};

let compactViewport = false;

function renderGraph(
  data: GraphData = graphData,
  selected: Paper | null = papers[0],
  highlighted = new Set<string>(),
  graphPapers: Paper[] = papers,
) {
  return render(
    <GraphView
      graphData={data}
      selectedPaper={selected}
      highlightedPapers={highlighted}
      papers={graphPapers}
      onNodeClick={vi.fn()}
    />,
  );
}

function plotData(): CapturedTrace[] {
  const raw = screen.getByTestId('graph-plot').getAttribute('data-plot-data');
  return JSON.parse(raw ?? '[]') as CapturedTrace[];
}

function plottedNodeIds(): string[] {
  return plotData().flatMap(trace => (
    trace.mode === 'markers' && Array.isArray(trace.customdata)
      ? trace.customdata.map(String)
      : []
  ));
}

function plottedLabels(): string[] {
  return plotData().flatMap(trace => (
    trace.mode === 'text' && Array.isArray(trace.text)
      ? trace.text.map(String)
      : []
  ));
}

function focusedEdgeHoverText(): string[] {
  return plotData().flatMap(trace => (
    Array.isArray(trace.hovertext) ? trace.hovertext.map(String) : []
  ));
}

describe('GraphView analysis layers', () => {
  beforeEach(() => {
    compactViewport = false;
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: compactViewport && query === '(max-width: 520px)',
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(() => true),
    }) as unknown as MediaQueryList);
    plotlyMock.listeners.clear();
    plotlyMock.graphDiv.on.mockClear();
    plotlyMock.graphDiv.removeListener.mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('starts with settings collapsed and sparse edges enabled', async () => {
    const user = userEvent.setup();
    renderGraph();

    const settings = screen.getByRole('button', { name: '보기 설정' });
    expect(settings).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('button', { name: '전체 연결선 표시' })).toHaveAttribute('aria-pressed', 'false');

    await user.click(settings);
    expect(screen.getByRole('checkbox', { name: '전체 연결선 표시' })).not.toBeChecked();
  });

  it('keeps 3-hop and 기준논문 paths independently active and reports full counts', async () => {
    const user = userEvent.setup();
    renderGraph(graphData, papers[1]);

    const hopButton = screen.getByRole('button', { name: '3-hop' });
    const pathButton = screen.getByRole('button', { name: '기준논문 경로' });

    await user.click(hopButton);
    await user.click(pathButton);

    expect(hopButton).toHaveAttribute('aria-pressed', 'true');
    expect(pathButton).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('기본 지형 + 3-hop + 기준논문 경로')).toBeInTheDocument();
    expect(screen.getAllByText(/기준논문까지 1단계/)).toHaveLength(2);
    expect(screen.getByText('기준논문(검색1위)')).toBeInTheDocument();
    expect(screen.getByText('표시 3/3편')).toBeInTheDocument();
    expect(screen.getByText('관계 2/2개')).toBeInTheDocument();
    expect(screen.getByTestId('graph-plot')).toBeInTheDocument();
  });

  it('disables selection-dependent layers when no paper is selected', () => {
    renderGraph(graphData, null);

    expect(screen.getByRole('button', { name: '3-hop' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '기준논문 경로' })).toBeDisabled();
  });

  it('binds the Plotly click event after initialization and resolves the clicked paper', async () => {
    const user = userEvent.setup();
    const onNodeClick = vi.fn();
    render(
      <GraphView
        graphData={graphData}
        selectedPaper={papers[0]}
        highlightedPapers={new Set()}
        papers={papers}
        onNodeClick={onNodeClick}
      />,
    );

    await user.click(screen.getByTestId('graph-plot'));

    const clickHandler = plotlyMock.listeners.get('plotly_click');
    expect(clickHandler).toBeTypeOf('function');
    act(() => clickHandler?.({ points: [{ customdata: 'hop-two' }] }));

    expect(onNodeClick).toHaveBeenCalledWith(papers[2]);
  });

  it('counts only edges whose endpoints survive the citation filter', () => {
    const citationGraph: GraphData = {
      ...graphData,
      nodes: graphData.nodes.map(node => ({
        ...node,
        citations: node.id === 'selected' ? 1 : 10,
      })),
    };
    const { container } = renderGraph(citationGraph, papers[1]);
    expect(screen.getByText('관계 2/2개')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '보기 설정' }));
    const citationInput = container.querySelector('input.control-input[type="number"]');
    expect(citationInput).not.toBeNull();
    fireEvent.change(citationInput!, { target: { value: '2' } });

    expect(screen.getByText('표시 2/3편')).toBeInTheDocument();
    expect(screen.getByText('관계 0/2개')).toBeInTheDocument();
  });

  it('keeps the selected edge to a ranked neighbor in sparse mode and describes its method accurately', () => {
    const nodes = Array.from({ length: 22 }, (_, index) => ({
      id: `node-${index}`,
      x: index,
      y: index % 3,
      title: `Node ${index}`,
      citations: 10,
    }));
    const edges: GraphData['edges'] = [];
    for (let source = 0; source < nodes.length; source += 1) {
      for (let target = source + 1; target < nodes.length; target += 1) {
        const isSelectedToNeighbor = source === 1 && target === 2;
        edges.push({
          source: nodes[source].id,
          target: nodes[target].id,
          weight: isSelectedToNeighbor ? 0.01 : 0.9,
          shared_terms: isSelectedToNeighbor ? ['rare-term'] : [],
        });
      }
    }
    const denseGraph: GraphData = {
      nodes,
      edges,
      meta: {
        edge_method: 'title_keyword_jaccard',
        edge_label: '제목·키워드 유사도',
        directed: false,
      },
    };
    const densePapers = nodes.map(node => ({
      doc_id: node.id,
      title: node.title,
      authors: [],
    }));
    renderGraph(denseGraph, densePapers[1], new Set(['node-2']), densePapers);

    expect(screen.getByRole('button', { name: '전체 연결선 표시' })).toHaveAttribute('aria-pressed', 'false');
    expect(plottedNodeIds()).toContain('node-2');
    expect(focusedEdgeHoverText()).toContain('제목·키워드 유사도 1%<br>공통 단서 · rare-term');
    const relationCount = screen.getByText(/관계 \d+\/\d+개/).textContent ?? '';
    expect(relationCount).toMatch(new RegExp(`\\d+/${edges.length}개`));
    expect(Number(relationCount.match(/관계 (\d+)/)?.[1])).toBeLessThan(edges.length);
  });

  it('escapes relationship metadata before inserting it into Plotly hover markup', () => {
    renderGraph({
      ...graphData,
      meta: {
        edge_method: 'title_keyword_jaccard',
        directed: false,
        edge_label: '<b>제목 & 키워드</b>',
      },
    }, papers[1], new Set(['origin']));

    expect(focusedEdgeHoverText()).toContain(
      '&lt;b&gt;제목 &amp; 키워드&lt;/b&gt; 90%<br>공통 단서 · graph',
    );
  });

  it('pins low-degree highlighted nodes beyond the 20-node ranked cap', async () => {
    const user = userEvent.setup();
    const nodes = Array.from({ length: 25 }, (_, index) => ({
      id: `pin-${index}`,
      x: index,
      y: 0,
      title: `Pin node ${index}`,
      citations: 0,
    }));
    const edges: GraphData['edges'] = [];
    for (let source = 0; source < 22; source += 1) {
      for (let target = source + 1; target < 22; target += 1) {
        edges.push({ source: nodes[source].id, target: nodes[target].id, weight: 0.9 });
      }
    }
    const pinGraph: GraphData = { nodes, edges };
    const pinPapers = nodes.map(node => ({ doc_id: node.id, title: node.title, authors: [] }));
    renderGraph(pinGraph, pinPapers[1], new Set(['pin-24']), pinPapers);

    await user.click(screen.getByRole('button', { name: '보기 설정' }));
    await user.selectOptions(screen.getByLabelText('표시 논문 수'), '20');

    const shownIds = plottedNodeIds();
    expect(shownIds).toHaveLength(20);
    expect(shownIds).toEqual(expect.arrayContaining(['pin-0', 'pin-1', 'pin-24']));
  });

  it('keeps every node on a 25-node path when the selected node cap is 20', async () => {
    const user = userEvent.setup();
    const pathIds = Array.from({ length: 25 }, (_, index) => `path-${index}`);
    const nodes = Array.from({ length: 62 }, (_, index) => ({
      id: `path-${index}`,
      x: index,
      y: 0,
      title: `Path paper ${index}`,
      citations: 1,
    }));
    const edges = pathIds.slice(0, -1).map((id, index) => ({
      source: id,
      target: pathIds[index + 1],
      weight: 0.9,
    }));
    const pathGraph: GraphData = { nodes, edges };
    const pathPapers = nodes.map(node => ({ doc_id: node.id, title: node.title, authors: [] }));
    renderGraph(pathGraph, pathPapers[24], new Set(), pathPapers);

    await user.click(screen.getByRole('button', { name: '보기 설정' }));
    await user.selectOptions(screen.getByLabelText('표시 논문 수'), '20');
    await user.click(screen.getByRole('button', { name: '기준논문 경로' }));

    const shownIds = plottedNodeIds();
    expect(new Set(shownIds)).toEqual(new Set(pathIds));
    expect(shownIds).toHaveLength(25);
    expect(screen.getByText('표시 25/62편')).toBeInTheDocument();
    expect(screen.getByText('관계 24/24개')).toBeInTheDocument();
  });

  it('limits compact Plotly labels to origin, selection, and the first three ranked highlights', async () => {
    compactViewport = true;
    const relatedPapers = Array.from({ length: 6 }, (_, index) => ({
      doc_id: `related-${index + 1}`,
      title: `Related paper ${index + 1}`,
      authors: [],
    }));
    const labelPapers = [papers[0], papers[1], ...relatedPapers];
    const labelGraph: GraphData = {
      nodes: labelPapers.map((paper, index) => ({
        id: paper.doc_id,
        title: paper.title,
        x: index,
        y: 0,
        citations: index + 1,
      })),
      edges: relatedPapers.map((paper, index) => ({
        source: 'selected',
        target: paper.doc_id,
        weight: 1 - index * 0.1,
      })),
      meta: graphData.meta,
    };
    const user = userEvent.setup();
    renderGraph(labelGraph, papers[1], new Set(relatedPapers.map(paper => paper.doc_id)), labelPapers);

    expect(plottedLabels()).toHaveLength(5);
    expect(plottedLabels()).toEqual([
      'Origin paper', 'Related paper 1', 'Related paper 2', 'Related paper 3', 'Selected paper',
    ]);
    const labelButton = screen.getByRole('button', {
      name: '핵심 레이블(기준·선택·관련 최대 3편) 숨기기',
    });
    expect(labelButton).toHaveAttribute('title', '핵심 레이블(기준·선택·관련 최대 3편) 숨기기');

    await user.click(screen.getByRole('button', { name: '보기 설정' }));
    expect(screen.getByText('핵심 레이블(기준·선택·관련 최대 3편)')).toBeInTheDocument();
    await user.click(labelButton);
    expect(plottedLabels()).toHaveLength(0);
    expect(screen.getByRole('button', {
      name: '핵심 레이블(기준·선택·관련 최대 3편) 표시',
    })).toHaveAttribute('aria-pressed', 'false');
  });

  it('uses at most four compact labels when the origin is also selected', () => {
    compactViewport = true;
    const labelGraph: GraphData = {
      nodes: [
        ...graphData.nodes,
        { id: 'related-a', x: 1, y: 1, title: 'Related A' },
        { id: 'related-b', x: 2, y: 1, title: 'Related B' },
        { id: 'related-c', x: 3, y: 1, title: 'Related C' },
        { id: 'related-d', x: 4, y: 1, title: 'Related D' },
      ],
      edges: [
        ...graphData.edges,
        { source: 'origin', target: 'related-a', weight: 0.9 },
        { source: 'origin', target: 'related-b', weight: 0.8 },
        { source: 'origin', target: 'related-c', weight: 0.7 },
        { source: 'origin', target: 'related-d', weight: 0.6 },
      ],
    };
    const related = ['related-a', 'related-b', 'related-c', 'related-d'];
    renderGraph(labelGraph, papers[0], new Set(related));

    expect(plottedLabels()).toHaveLength(4);
    expect(plottedLabels()).toContain('Origin paper');
  });
});
