import { describe, expect, it } from 'vitest';
import type { GraphData } from '../../types';
import {
  convexHull,
  describeEdgeMethod,
  estimateTextWidthPx,
  hullPath,
  neighborhoodSubgraph,
  pathEdgeKeys,
  placeLabels,
  rankedNeighbors,
  rankedSubgraph,
  separateCommunityLayout,
  shortLabel,
  strongestPathToOrigin,
  uniqueLabels,
} from './graphPresentation';

const graph: GraphData = {
  nodes: [
    { id: 'origin', x: 0, y: 0, title: 'Origin', citations: 3 },
    { id: 'middle', x: 1, y: 0, title: 'Middle', citations: 2 },
    { id: 'selected', x: 2, y: 0, title: 'Selected', citations: 1 },
    { id: 'popular', x: 0, y: 1, title: 'Popular', citations: 100 },
  ],
  edges: [
    { source: 'selected', target: 'origin', weight: 0.5 },
    { source: 'selected', target: 'middle', weight: 0.8 },
    { source: 'middle', target: 'origin', weight: 0.8 },
    { source: 'popular', target: 'origin', weight: 0.2 },
  ],
};

describe('graph presentation helpers', () => {
  it('returns no ranked neighbors when graph data or the selected id is missing', () => {
    expect(rankedNeighbors(null, 'selected')).toEqual([]);
    expect(rankedNeighbors(undefined, 'selected')).toEqual([]);
    expect(rankedNeighbors(graph, null)).toEqual([]);
    expect(rankedNeighbors(graph, undefined)).toEqual([]);
  });

  it('ranks undirected neighbors by strongest edge, breaking ties by id', () => {
    const neighborGraph: GraphData = {
      nodes: [],
      edges: [
        { source: 'selected', target: 'z', weight: 0.9, shared_terms: ['older'] },
        { source: 'a', target: 'selected', weight: 0.9, shared_terms: ['alpha'] },
        { source: 'selected', target: 'b', weight: 0.9, shared_terms: ['beta'] },
        { source: 'selected', target: 'z', weight: 0.95, shared_terms: ['strongest'] },
        { source: 'selected', target: 'z', weight: 0.8, shared_terms: ['weaker'] },
        { source: 'selected', target: 'c', weight: 0.7 },
        { source: 'selected', target: 'selected', weight: 1, shared_terms: ['loop'] },
        { source: 'outside', target: 'unconnected', weight: 1 },
      ],
    };

    expect(rankedNeighbors(neighborGraph, 'selected', 3)).toEqual([
      { id: 'z', weight: 0.95, sharedTerms: ['strongest'] },
      { id: 'a', weight: 0.9, sharedTerms: ['alpha'] },
      { id: 'b', weight: 0.9, sharedTerms: ['beta'] },
    ]);
    expect(rankedNeighbors(neighborGraph, 'selected', 0)).toEqual([]);
    expect(rankedNeighbors(neighborGraph, 'selected', -1)).toEqual([]);
  });

  it('normalizes numeric edge ids to strings and applies the default neighbor limit', () => {
    const numericGraph = {
      nodes: [],
      edges: [
        { source: 1, target: 2, weight: 0.9 },
        { source: 3, target: 1, weight: 0.8 },
        { source: 1, target: 4, weight: 0.7 },
        { source: 5, target: 1, weight: 0.6 },
        { source: 1, target: 6, weight: 0.5 },
        { source: 7, target: 1, weight: 0.4 },
      ],
    } as unknown as GraphData;

    expect(rankedNeighbors(numericGraph, '1')).toEqual([
      { id: '2', weight: 0.9, sharedTerms: [] },
      { id: '3', weight: 0.8, sharedTerms: [] },
      { id: '4', weight: 0.7, sharedTerms: [] },
      { id: '5', weight: 0.6, sharedTerms: [] },
      { id: '6', weight: 0.5, sharedTerms: [] },
    ]);
  });

  it('skips invalid edge weights but keeps real zero weights and the strongest valid duplicate', () => {
    const graphWithInvalidWeights = {
      nodes: [],
      edges: [
        { source: 'selected', target: 'missing-weight' },
        { source: 'selected', target: 'null-weight', weight: null },
        { source: 'selected', target: 'nan-weight', weight: Number.NaN },
        { source: 'selected', target: 'infinite-weight', weight: Number.POSITIVE_INFINITY },
        { source: 'selected', target: 'negative-infinite-weight', weight: Number.NEGATIVE_INFINITY },
        { source: 'selected', target: 'zero-weight', weight: 0, shared_terms: ['zero is evidence'] },
        { source: 'selected', target: 'duplicate', weight: Number.NaN, shared_terms: ['invalid'] },
        { source: 'selected', target: 'duplicate', weight: 0.4, shared_terms: ['valid'] },
        { source: 'selected', target: 'duplicate', weight: null, shared_terms: ['also invalid'] },
      ],
    } as unknown as GraphData;

    expect(rankedNeighbors(graphWithInvalidWeights, 'selected')).toEqual([
      { id: 'duplicate', weight: 0.4, sharedTerms: ['valid'] },
      { id: 'zero-weight', weight: 0, sharedTerms: ['zero is evidence'] },
    ]);
  });

  it('softly expands past the node limit to retain every pinned path node', () => {
    const nodes = Array.from({ length: 32 }, (_, index) => ({
      id: `pin-${index}`,
      x: index,
      y: 0,
      title: `Pin ${index}`,
    }));
    const pinnedPath = nodes.slice(0, 25).map(node => node.id);
    const ranked = rankedSubgraph({ nodes, edges: [] }, 20, pinnedPath);

    expect(ranked.nodes).toHaveLength(25);
    expect(ranked.nodes.map(node => node.id)).toEqual(pinnedPath);
  });

  it('describes each edge method accurately without claiming abstract inputs', () => {
    const semantic = describeEdgeMethod({
      edge_method: 'semantic_cosine', edge_label: 'Title semantics', directed: false,
    });
    const semanticFallback = describeEdgeMethod({
      edge_method: 'semantic_cosine', edge_label: '', directed: false,
    });
    const keyword = describeEdgeMethod({
      edge_method: 'title_keyword_jaccard', edge_label: 'Title and keyword overlap', directed: false,
    });
    const unavailable = describeEdgeMethod({
      edge_method: 'unavailable', edge_label: 'Ignored label', directed: false,
    });
    const missing = describeEdgeMethod();

    expect(semantic).toEqual({
      label: 'Title semantics',
      explanation: '제목 임베딩 코사인 유사도 · 인용·인과 관계 아님',
    });
    expect(semantic.explanation).toContain('제목');
    expect(semanticFallback.label).toBe('제목 의미 유사도');
    expect(keyword).toEqual({
      label: 'Title and keyword overlap',
      explanation: '제목·키워드 겹침(Jaccard) · 인용·인과 관계 아님',
    });
    expect(unavailable).toEqual({ label: '논문 간 유사도', explanation: '관계 계산 정보 없음' });
    expect(missing).toEqual({ label: '논문 간 유사도', explanation: '관계 계산 정보 없음' });
    expect(JSON.stringify([semantic, semanticFallback, keyword, unavailable, missing])).not.toContain('초록');
  });

  it('chooses the strongest product-of-similarities path to the origin', () => {
    expect(strongestPathToOrigin(graph, 'selected', 'origin')).toEqual([
      'selected',
      'middle',
      'origin',
    ]);
    expect(pathEdgeKeys(['selected', 'middle', 'origin'])).toEqual(new Set([
      'middle--selected',
      'middle--origin',
    ]));
  });

  it('keeps task-critical pinned nodes inside a ranked view', () => {
    const ranked = rankedSubgraph(graph, 20, ['origin', 'selected']);
    expect(ranked.nodes.map(node => node.id)).toContain('origin');
    expect(ranked.nodes.map(node => node.id)).toContain('selected');
  });

  it('packs communities without overlapping hulls while keeping each community\'s own layout', () => {
    const communityGraph: GraphData = {
      nodes: [
        { id: 'a1', x: -0.4, y: 0, title: 'A1', community_id: 0 },
        { id: 'a2', x: -0.2, y: 0.1, title: 'A2', community_id: 0 },
        { id: 'a3', x: -0.3, y: -0.1, title: 'A3', community_id: 0 },
        { id: 'b1', x: 0.2, y: 0, title: 'B1', community_id: 1 },
        { id: 'b2', x: 0.4, y: 0, title: 'B2', community_id: 1 },
        { id: 'c1', x: 0.3, y: 0.05, title: 'C1', community_id: 2 },
        { id: 'c2', x: 0.35, y: 0.05, title: 'C2', community_id: 2 },
      ],
      edges: [],
    };

    const packed = separateCommunityLayout(communityGraph);
    const byId = Object.fromEntries(packed.nodes.map(node => [node.id, node]));
    const circles = [0, 1, 2].map(communityId => {
      const members = packed.nodes.filter(node => node.community_id === communityId);
      const cx = members.reduce((sum, node) => sum + node.x, 0) / members.length;
      const cy = members.reduce((sum, node) => sum + node.y, 0) / members.length;
      const r = Math.max(...members.map(node => Math.hypot(node.x - cx, node.y - cy)));
      return { cx, cy, r };
    });

    circles.forEach((left, index) => circles.slice(index + 1).forEach(right => {
      expect(Math.hypot(left.cx - right.cx, left.cy - right.cy)).toBeGreaterThan(left.r + right.r);
    }));
    expect(byId.a1.x).toBeLessThan(byId.a2.x);
    expect(byId.a3.y).toBeLessThan(byId.a2.y);
    packed.nodes.forEach(node => {
      expect(Math.abs(node.x)).toBeLessThanOrEqual(1);
      expect(Math.abs(node.y)).toBeLessThanOrEqual(1);
    });
    expect(separateCommunityLayout({ ...communityGraph, nodes: communityGraph.nodes.slice(0, 3) }).nodes)
      .toEqual(communityGraph.nodes.slice(0, 3));

    const withLoner = separateCommunityLayout({
      ...communityGraph,
      nodes: [...communityGraph.nodes, { id: 'u', x: 0.1, y: 0.1, title: 'Loner', community_id: null }],
    });
    const loner = withLoner.nodes.find(node => node.id === 'u')!;
    withLoner.nodes
      .filter(node => typeof node.community_id === 'number')
      .forEach(node => {
        const circle = circles[node.community_id as number];
        expect(Math.hypot(loner.x - circle.cx, loner.y - circle.cy)).toBeGreaterThan(circle.r);
      });
  });

  it('expands a selected neighborhood through three similarity hops', () => {
    const threeHopGraph: GraphData = {
      nodes: [
        { id: 'selected', x: 0, y: 0, title: 'Selected' },
        { id: 'hop-1', x: 1, y: 0, title: 'Hop 1' },
        { id: 'hop-2', x: 2, y: 0, title: 'Hop 2' },
        { id: 'hop-3', x: 3, y: 0, title: 'Hop 3' },
        { id: 'hop-4', x: 4, y: 0, title: 'Hop 4' },
      ],
      edges: [
        { source: 'selected', target: 'hop-1', weight: 0.9 },
        { source: 'hop-1', target: 'hop-2', weight: 0.8 },
        { source: 'hop-2', target: 'hop-3', weight: 0.7 },
        { source: 'hop-3', target: 'hop-4', weight: 0.6 },
      ],
    };

    const neighborhood = neighborhoodSubgraph(threeHopGraph, 'selected', 20);
    expect(neighborhood.nodes.map(node => node.id)).toEqual(['selected', 'hop-1', 'hop-2', 'hop-3', 'hop-4']);
    expect(neighborhood.nodes.map(node => node.hop_distance)).toEqual([0, 1, 2, 3, undefined]);
    expect(neighborhood.edges).toHaveLength(4);
  });

  it('uses strongest-neighbor expansion instead of collapsing a dense graph into one hop', () => {
    const nodeIds = ['selected', 'a', 'b', 'c', 'd', 'x', 'y'];
    const denseGraph: GraphData = {
      nodes: nodeIds.map((id, index) => ({ id, x: index, y: 0, title: id })),
      edges: [
        { source: 'selected', target: 'a', weight: 0.99 },
        { source: 'selected', target: 'b', weight: 0.98 },
        { source: 'selected', target: 'c', weight: 0.97 },
        { source: 'selected', target: 'd', weight: 0.96 },
        { source: 'selected', target: 'x', weight: 0.3 },
        { source: 'selected', target: 'y', weight: 0.2 },
        { source: 'a', target: 'x', weight: 0.95 },
        { source: 'b', target: 'y', weight: 0.94 },
      ],
    };

    const neighborhood = neighborhoodSubgraph(denseGraph, 'selected', 20);
    const hops = Object.fromEntries(neighborhood.nodes.map(node => [node.id, node.hop_distance]));
    expect(hops.selected).toBe(0);
    expect(hops.a).toBe(1);
    expect(hops.x).toBe(2);
    expect(hops.y).toBe(2);
  });

  it('shortens titles to distinctive names and keeps them unique', () => {
    const common = ['graph', 'retrieval-augmented', 'generation'];
    expect(shortLabel('GRAG: Graph Retrieval-Augmented Generation', common)).toBe('GRAG');
    expect(shortLabel('Graph Retrieval-Augmented Generation: A Survey', common)).toBe('Graph Survey…');
    expect(shortLabel('Origin paper', common)).toBe('Origin paper');
    expect(shortLabel('   ')).toBe('Untitled');
    expect(shortLabel('The Of And')).toBe('The Of And');

    const labels = uniqueLabels([
      { id: 'a', title: 'Federated Graph Retrieval-Augmented Generation', year: 2025 },
      { id: 'b', title: 'Federated Graph Retrieval-Augmented Generation', year: 2026 },
      { id: 'c', title: 'Federated Graph Retrieval-Augmented Generation', year: 2026 },
    ], common);
    expect(new Set(labels.values()).size).toBe(3);
    expect(labels.get('a')).toBe('Federated Graph… (2025)');
    expect(labels.get('c')).toBe('Federated Graph… (2026) 2');
  });

  it('places labels without overlap and drops the lowest-priority collider', () => {
    const candidates = [
      { id: 'a', x: 0, y: 0, text: 'Alpha paper', priority: 10, fontPx: 10, anchorPx: 6 },
      { id: 'b', x: 0, y: 0, text: 'Beta paper', priority: 5, fontPx: 10, anchorPx: 6 },
      { id: 'c', x: 0.5, y: 0, text: 'Gamma', priority: 1, fontPx: 10, anchorPx: 6 },
      { id: 'd', x: 0.2, y: 0, text: 'Delta paper', priority: 0, fontPx: 10, anchorPx: 6 },
    ];
    const placed = placeLabels(candidates, 100, 100);

    expect(placed.map(label => label.id)).toEqual(['a', 'b', 'c']);
    expect(placed[0].y).toBeGreaterThan(0);
    expect(placed[1].y).toBeLessThan(0);

    const boxes = placed.map(label => {
      const half = estimateTextWidthPx(label.text, 10) / 2;
      return { x0: label.x * 100 - half, x1: label.x * 100 + half, y0: label.y * 100 - 6.5, y1: label.y * 100 + 6.5 };
    });
    boxes.forEach((left, i) => boxes.slice(i + 1).forEach(right => {
      const overlap = left.x0 < right.x1 && right.x0 < left.x1 && left.y0 < right.y1 && right.y0 < left.y1;
      expect(overlap).toBe(false);
    }));
    expect(placeLabels(candidates, 0, 100)).toEqual([]);
  });

  it('builds a padded convex hull path around a community', () => {
    const points = [
      { x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }, { x: 0.5, y: 0.5 },
    ];
    expect(convexHull(points)).toHaveLength(4);
    expect(convexHull(points)).not.toContainEqual({ x: 0.5, y: 0.5 });
    expect(hullPath(points, 0.1)).toMatch(/^M -0\.07\d+,-0\.07\d+ L .* Z$/);
    expect(hullPath(points.slice(0, 2), 0.1)).toBe('');
  });
});
