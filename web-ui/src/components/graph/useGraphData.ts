import { useMemo } from 'react';
import Graph from 'graphology';
import type { GraphData } from '../../types';
import type { GraphStats } from './types';

/**
 * Converts API GraphData (nodes/edges arrays) to a graphology Graph instance.
 * Applies minCitations and yearFilter, computes node color from year
 * (green-to-blue gradient matching Plotly), computes node size from citations (log scale).
 */
export function useGraphData(
  graphData: GraphData | null,
  minCitations: number,
  yearFilter: [number, number] | null,
): { graph: Graph; stats: GraphStats } {
  return useMemo(() => {
    const graph = new Graph();
    const emptyStats: GraphStats = { nodes: 0, edges: 0, avgCitations: 0, yearRange: [0, 0] };

    if (!graphData || graphData.nodes.length === 0) {
      return { graph, stats: emptyStats };
    }

    // Filter nodes
    let nodes = graphData.nodes;

    if (minCitations > 0) {
      nodes = nodes.filter(n => (n.citations || 0) >= minCitations);
    }

    if (yearFilter) {
      nodes = nodes.filter(n => {
        const year = typeof n.year === 'number' ? n.year : parseInt(String(n.year), 10);
        return !isNaN(year) && year >= yearFilter[0] && year <= yearFilter[1];
      });
    }

    if (nodes.length === 0) {
      return { graph, stats: emptyStats };
    }

    // Calculate year range for coloring — matches Plotly logic exactly
    const years = nodes
      .map(n => {
        const year = n.year;
        if (typeof year === 'number') return year;
        if (typeof year === 'string') {
          const parsed = parseInt(year, 10);
          return isNaN(parsed) ? null : parsed;
        }
        return null;
      })
      .filter((y): y is number => y !== null && !isNaN(y));

    const minYear = years.length > 0 ? Math.min(...years) : 2010;
    const maxYear = years.length > 0 ? Math.max(...years) : 2024;
    const yearRange = maxYear - minYear || 1;

    // Build node set for fast edge lookup
    const nodeIdSet = new Set<string>();

    nodes.forEach(n => {
      const nodeId = String((n as Record<string, unknown>).doc_id || n.id);
      if (nodeIdSet.has(nodeId)) return; // skip duplicate
      nodeIdSet.add(nodeId);

      // Color: year-based green gradient — rgba(60, 150~220, 150, 0.95)
      const nodeYear = n.year ? Number(n.year) : null;
      const year = nodeYear && !isNaN(nodeYear) ? nodeYear : minYear;
      const relative = yearRange > 0 ? (year - minYear) / yearRange : 0;
      const baseGreen = Math.floor(150 + relative * 70);
      const clampedGreen = Math.max(150, Math.min(220, baseGreen));
      const color = `rgba(60, ${clampedGreen}, 150, 0.95)`;

      // Size: log scale matching Plotly — baseSize 12 + 6 * log10(citations + 1)
      const citations = n.citations || 1;
      const size = 12 + 6 * Math.log10(citations + 1);

      graph.addNode(nodeId, {
        x: n.x,
        y: n.y,
        size,
        color,
        label: n.title || 'Untitled',
        // Store original data for lookup
        nodeYear: year,
        citations: n.citations || 0,
        docId: nodeId,
      });
    });

    // Add edges with deduplication
    const edgeSet = new Set<string>();
    let addedEdges = 0;

    graphData.edges.forEach(edge => {
      const source = String(edge.source);
      const target = String(edge.target);

      if (!nodeIdSet.has(source) || !nodeIdSet.has(target)) return;
      if (source === target) return;

      // Deduplicate undirected edges
      const edgeKey = source < target ? `${source}--${target}` : `${target}--${source}`;
      if (edgeSet.has(edgeKey)) return;
      edgeSet.add(edgeKey);

      graph.addEdge(source, target, {
        weight: edge.weight || 0.1,
        color: 'rgba(156, 163, 175, 0.3)',
        size: 0.7,
      });
      addedEdges++;
    });

    // Calculate statistics
    const citationValues = nodes.map(n => n.citations || 0);
    const avgCitations =
      citationValues.length > 0
        ? Math.round(citationValues.reduce((a, b) => a + b, 0) / citationValues.length)
        : 0;

    const stats: GraphStats = {
      nodes: graph.order,
      edges: addedEdges,
      avgCitations,
      yearRange: [minYear, maxYear],
    };

    return { graph, stats };
  }, [graphData, minCitations, yearFilter]);
}
