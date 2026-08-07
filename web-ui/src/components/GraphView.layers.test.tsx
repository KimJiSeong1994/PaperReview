import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GraphData, Paper } from '../types';
import GraphView from './GraphView';

const plotlyMock = vi.hoisted(() => {
  const listeners = new Map<string, (event: { points?: Array<{ customdata?: unknown }> }) => void>();
  return {
    listeners,
    graphDiv: {
      on: vi.fn((eventName: string, handler: (event: { points?: Array<{ customdata?: unknown }> }) => void) => {
        listeners.set(eventName, handler);
      }),
      removeListener: vi.fn((eventName: string, handler: (event: { points?: Array<{ customdata?: unknown }> }) => void) => {
        if (listeners.get(eventName) === handler) listeners.delete(eventName);
      }),
    },
  };
});

vi.mock('../PlotlyChart', () => ({
  default: ({ onInitialized }: { onInitialized?: (figure: unknown, graphDiv: unknown) => void }) => (
    <button
      type="button"
      data-testid="graph-plot"
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
    { id: 'origin', x: -0.4, y: 0, title: 'Origin paper', community_id: 0 },
    { id: 'selected', x: 0, y: 0, title: 'Selected paper', community_id: 0 },
    { id: 'hop-two', x: 0.4, y: 0, title: 'Hop two paper', community_id: 1 },
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

describe('GraphView analysis layers', () => {
  beforeEach(() => {
    plotlyMock.listeners.clear();
    plotlyMock.graphDiv.on.mockClear();
    plotlyMock.graphDiv.removeListener.mockClear();
  });

  it('shows view settings and the full edge set by default', () => {
    render(
      <GraphView
        graphData={graphData}
        selectedPaper={papers[0]}
        highlightedPapers={new Set()}
        papers={papers}
        onNodeClick={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: '보기 설정' })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', { name: '보기 설정 닫기' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: '전체 연결선 표시' })).toBeChecked();
    expect(screen.getByRole('button', { name: '구조 연결선만 표시' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('keeps 3-hop and origin path independently active on one canvas', async () => {
    const user = userEvent.setup();
    render(
      <GraphView
        graphData={graphData}
        selectedPaper={papers[1]}
        highlightedPapers={new Set()}
        papers={papers}
        onNodeClick={vi.fn()}
      />,
    );

    const hopButton = screen.getByRole('button', { name: '3-hop' });
    const pathButton = screen.getByRole('button', { name: '원문 경로' });

    await user.click(hopButton);
    await user.click(pathButton);

    expect(hopButton).toHaveAttribute('aria-pressed', 'true');
    expect(pathButton).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('기본 지형 + 3-hop + 원문 경로')).toBeInTheDocument();
    expect(screen.getByText(/1-hop 2편/)).toBeInTheDocument();
    expect(screen.getAllByText(/원 논문까지 1단계/)).toHaveLength(2);
    expect(screen.getByTestId('graph-plot')).toBeInTheDocument();
  });

  it('disables selection-dependent layers when no paper is selected', () => {
    render(
      <GraphView
        graphData={graphData}
        selectedPaper={null}
        highlightedPapers={new Set()}
        papers={papers}
        onNodeClick={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: '3-hop' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '원문 경로' })).toBeDisabled();
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
});
