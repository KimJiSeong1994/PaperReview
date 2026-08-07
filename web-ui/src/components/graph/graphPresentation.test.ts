import { describe, expect, it } from 'vitest';
import type { GraphData } from '../../types';
import {
  neighborhoodSubgraph,
  pathEdgeKeys,
  rankedSubgraph,
  separateCommunityLayout,
  strongestPathToOrigin,
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

  it('softly separates communities without replacing the organic layout with a grid', () => {
    const communityGraph: GraphData = {
      nodes: [
        { id: 'a1', x: -0.4, y: 0, title: 'A1', community_id: 0 },
        { id: 'a2', x: -0.2, y: 0, title: 'A2', community_id: 0 },
        { id: 'b1', x: 0.2, y: 0, title: 'B1', community_id: 1 },
        { id: 'b2', x: 0.4, y: 0, title: 'B2', community_id: 1 },
      ],
      edges: [],
    };

    const separated = separateCommunityLayout(communityGraph);
    const positions = Object.fromEntries(separated.nodes.map(node => [node.id, node.x]));
    const originalCenterGap = 0.6;
    const separatedCenterGap = ((positions.b1 + positions.b2) / 2) - ((positions.a1 + positions.a2) / 2);

    expect(separatedCenterGap).toBeCloseTo(originalCenterGap * 0.96);
    expect(positions.a2 - positions.a1).toBeCloseTo(0.2 * 0.88);
    expect(positions.a1).toBeLessThan(positions.a2);
    expect(positions.b1).toBeLessThan(positions.b2);
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
});
