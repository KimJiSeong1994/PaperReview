import { useEffect, useState, useCallback, useMemo } from 'react';
import { SigmaContainer, useRegisterEvents, useSetSettings, useSigma } from '@react-sigma/core';
import '@react-sigma/core/lib/react-sigma.min.css';
import './SigmaGraphView.css';
import type { SigmaGraphViewProps } from './types';
import { useGraphData } from './useGraphData';
import type { Paper } from '../../types';

/**
 * Inner component that registers Sigma events for click handling
 * and applies node/edge reducers for selection/highlight.
 */
function GraphEvents({
  selectedPaper,
  highlightedPapers,
  papers,
  onNodeClick,
  showLabels,
  edgeOpacity,
}: {
  selectedPaper: Paper | null;
  highlightedPapers: Set<string>;
  papers: Paper[];
  onNodeClick: (paper: Paper) => void;
  showLabels: boolean;
  edgeOpacity: number;
}) {
  const sigma = useSigma();
  const registerEvents = useRegisterEvents();
  const setSettings = useSetSettings();
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  // Build a fast lookup map for papers
  const papersMap = useMemo(() => {
    const map = new Map<string, Paper>();
    papers.forEach(paper => {
      const docId = String(paper.doc_id);
      map.set(docId, paper);
      if (paper.title) {
        map.set(paper.title, paper);
      }
    });
    return map;
  }, [papers]);

  // Register click events
  useEffect(() => {
    registerEvents({
      clickNode: (event) => {
        const nodeId = event.node;
        const paper = papersMap.get(nodeId);
        if (paper) {
          onNodeClick(paper);
          return;
        }
        // Fallback: try to find via node label (title)
        const graph = sigma.getGraph();
        if (graph.hasNode(nodeId)) {
          const attrs = graph.getNodeAttributes(nodeId);
          const paperByTitle = papersMap.get(attrs.label as string);
          if (paperByTitle) {
            onNodeClick(paperByTitle);
          }
        }
      },
      enterNode: (event) => {
        setHoveredNode(event.node);
        document.body.style.cursor = 'pointer';
      },
      leaveNode: () => {
        setHoveredNode(null);
        document.body.style.cursor = 'default';
      },
    });
  }, [registerEvents, sigma, papersMap, onNodeClick]);

  // Determine selected node ID
  const selectedNodeId = selectedPaper ? String(selectedPaper.doc_id) : null;

  // Compute set of neighbors for highlighting
  const highlightedNeighbors = useMemo(() => {
    const neighbors = new Set<string>();
    const graph = sigma.getGraph();
    if (selectedNodeId && graph.hasNode(selectedNodeId)) {
      graph.forEachNeighbor(selectedNodeId, (neighbor) => neighbors.add(neighbor));
    }
    if (hoveredNode && graph.hasNode(hoveredNode)) {
      graph.forEachNeighbor(hoveredNode, (neighbor) => neighbors.add(neighbor));
    }
    highlightedPapers.forEach(id => {
      if (graph.hasNode(id)) {
        neighbors.add(id);
        graph.forEachNeighbor(id, (neighbor) => neighbors.add(neighbor));
      }
    });
    return neighbors;
  }, [sigma, selectedNodeId, hoveredNode, highlightedPapers]);

  // Apply node/edge reducers via settings
  const hasActiveSelection = selectedNodeId !== null || highlightedPapers.size > 0 || hoveredNode !== null;

  const nodeReducer = useCallback(
    (node: string, data: Record<string, unknown>) => {
      const res = { ...data } as Record<string, unknown>;

      if (node === selectedNodeId) {
        // Selected node: purple, larger
        res.color = 'rgba(168, 85, 247, 0.95)';
        res.size = (data.size as number) * 1.5;
        res.highlighted = true;
        res.zIndex = 3;
      } else if (highlightedPapers.has(node)) {
        // Highlighted papers: slightly larger
        res.size = (data.size as number) * 1.35;
        res.highlighted = true;
        res.zIndex = 2;
      } else if (node === hoveredNode) {
        // Hovered node: slightly larger
        res.size = (data.size as number) * 1.35;
        res.highlighted = true;
        res.zIndex = 2;
      } else if (hasActiveSelection && !highlightedNeighbors.has(node)) {
        // Dim unrelated nodes
        res.color = 'rgba(60, 150, 150, 0.3)';
        res.zIndex = 0;
      }

      return res;
    },
    [selectedNodeId, highlightedPapers, hoveredNode, hasActiveSelection, highlightedNeighbors],
  );

  const edgeReducer = useCallback(
    (edge: string, data: Record<string, unknown>) => {
      const res = { ...data } as Record<string, unknown>;
      const graph = sigma.getGraph();
      const source = graph.source(edge);
      const target = graph.target(edge);

      const isConnectedToSelection =
        (selectedNodeId && (source === selectedNodeId || target === selectedNodeId)) ||
        highlightedPapers.has(source) ||
        highlightedPapers.has(target) ||
        (hoveredNode && (source === hoveredNode || target === hoveredNode));

      if (isConnectedToSelection) {
        // Highlight connected edges: purple, thicker
        const weight = (data.weight as number) || 0.1;
        const normalizedOpacity = Math.min(0.7, 0.3 + weight * 0.4) * edgeOpacity;
        res.color = `rgba(168, 85, 247, ${normalizedOpacity.toFixed(2)})`;
        res.size = 2.5;
        res.zIndex = 1;
      } else if (hasActiveSelection) {
        // Dim unrelated edges
        const weight = (data.weight as number) || 0.1;
        const normalizedOpacity = Math.min(0.35, 0.15 + weight * 0.2) * edgeOpacity;
        res.color = `rgba(156, 163, 175, ${normalizedOpacity.toFixed(2)})`;
        res.size = 0.7;
        res.zIndex = 0;
      } else {
        // Default: apply edge opacity
        const weight = (data.weight as number) || 0.1;
        const normalizedOpacity = Math.min(0.6, 0.3 + weight * 0.3) * edgeOpacity;
        res.color = `rgba(156, 163, 175, ${normalizedOpacity.toFixed(2)})`;
        res.size = 0.7;
      }

      return res;
    },
    [sigma, selectedNodeId, highlightedPapers, hoveredNode, hasActiveSelection, edgeOpacity],
  );

  // Apply settings including reducers and label visibility
  useEffect(() => {
    setSettings({
      nodeReducer,
      edgeReducer,
      renderLabels: showLabels,
      labelColor: { color: 'rgba(255, 255, 255, 0.9)' },
      labelSize: 9,
      labelFont: 'Roboto, sans-serif',
      labelRenderedSizeThreshold: 6,
      zIndex: true,
    });
  }, [setSettings, nodeReducer, edgeReducer, showLabels]);

  return null;
}

/**
 * SigmaGraphView — WebGL graph renderer using Sigma.js v3.
 * Drop-in replacement for Plotly rendering, activated via VITE_USE_SIGMA flag.
 */
function SigmaGraphView({
  graphData,
  selectedPaper,
  highlightedPapers,
  papers,
  onNodeClick,
  showLabels,
  edgeOpacity,
  minCitations,
  yearFilter,
}: SigmaGraphViewProps) {
  const { graph } = useGraphData(graphData, minCitations, yearFilter);

  if (!graphData || graphData.nodes.length === 0) {
    return null;
  }

  return (
    <div className="sigma-graph-container">
      <SigmaContainer
        graph={graph}
        style={{ width: '100%', height: '620px', background: '#181818' }}
        settings={{
          renderLabels: showLabels,
          labelColor: { color: 'rgba(255, 255, 255, 0.9)' },
          labelSize: 9,
          labelFont: 'Roboto, sans-serif',
          labelRenderedSizeThreshold: 6,
          defaultEdgeColor: 'rgba(156, 163, 175, 0.3)',
          defaultNodeColor: 'rgba(60, 150, 150, 0.95)',
          zIndex: true,
          enableEdgeEvents: false,
          minEdgeThickness: 0.5,
          antiAliasingFeather: 1,
        }}
      >
        <GraphEvents
          selectedPaper={selectedPaper}
          highlightedPapers={highlightedPapers}
          papers={papers}
          onNodeClick={onNodeClick}
          showLabels={showLabels}
          edgeOpacity={edgeOpacity}
        />
      </SigmaContainer>
    </div>
  );
}

export default SigmaGraphView;
