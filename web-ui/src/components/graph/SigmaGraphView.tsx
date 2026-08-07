import { useEffect, useState, useCallback, useMemo } from 'react';
import { SigmaContainer, useRegisterEvents, useSetSettings, useSigma } from '@react-sigma/core';
import { drawDiscNodeHover, type NodeHoverDrawingFunction } from 'sigma/rendering';
import '@react-sigma/core/lib/react-sigma.min.css';
import './SigmaGraphView.css';
import type { SigmaGraphViewProps } from './types';
import { useGraphData } from './useGraphData';
import type { Paper } from '../../types';
import { useThemeObserver, type Theme } from '../../theme';
import { graphEdgeKey, type GraphMode } from './graphPresentation';

/**
 * Sigma's default hover renderer always paints a WHITE box (hardcoded #FFF) and
 * then draws the label in settings.labelColor. In dark mode labelColor is white,
 * so the hover label was white-on-white (invisible). Force a dark-ink hover label
 * — the hover box is white in both themes, so dark ink reads in both.
 * Hoisted to module scope so its reference is stable: SigmaContainer rebuilds the
 * Sigma instance whenever a settings value changes by identity, and an inline
 * function would differ every render.
 */
const drawHoverInk: NodeHoverDrawingFunction = (context, data, settings) =>
  drawDiscNodeHover(context, data, {
    ...settings,
    labelColor: { color: 'rgba(17, 24, 39, 0.9)' },
  });

/**
 * Per-theme colors. The `dark` branch reproduces the previous hardcoded
 * literals exactly (dark must stay pixel-identical). Light uses dark-ink /
 * slate values so nodes, edges, and labels read on a white ground.
 * Selected/highlight purple is theme-independent (kept in the reducers).
 */
const THEME_COLORS = {
  dark: {
    label: 'rgba(255, 255, 255, 0.9)',
    defaultNode: 'rgba(60, 150, 150, 0.95)',
    defaultEdge: 'rgba(156, 163, 175, 0.3)',
    nodeDimmed: 'rgba(60, 150, 150, 0.3)',
    edgeDefault: (weight: number, opacity: number) =>
      `rgba(156, 163, 175, ${(Math.min(0.6, 0.3 + weight * 0.3) * opacity).toFixed(2)})`,
    edgeDimmed: (weight: number, opacity: number) =>
      `rgba(156, 163, 175, ${(Math.min(0.35, 0.15 + weight * 0.2) * opacity).toFixed(2)})`,
  },
  light: {
    label: 'rgba(17, 24, 39, 0.9)',
    defaultNode: '#0d9488',
    defaultEdge: 'rgba(17, 24, 39, 0.45)',
    nodeDimmed: 'rgba(71, 85, 105, 0.35)',
    edgeDefault: (weight: number, opacity: number) =>
      `rgba(17, 24, 39, ${(Math.min(0.75, 0.45 + weight * 0.3) * opacity).toFixed(2)})`,
    edgeDimmed: (weight: number, opacity: number) =>
      `rgba(71, 85, 105, ${(Math.min(0.35, 0.15 + weight * 0.2) * opacity).toFixed(2)})`,
  },
} as const;

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
  theme,
  graphMode,
  pathEdgeKeys,
}: {
  selectedPaper: Paper | null;
  highlightedPapers: Set<string>;
  papers: Paper[];
  onNodeClick: (paper: Paper) => void;
  showLabels: boolean;
  edgeOpacity: number;
  theme: Theme;
  graphMode: GraphMode;
  pathEdgeKeys: Set<string>;
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
        res.color = THEME_COLORS[theme].nodeDimmed;
        res.zIndex = 0;
      }

      return res;
    },
    [selectedNodeId, highlightedPapers, hoveredNode, hasActiveSelection, highlightedNeighbors, theme],
  );

  const edgeReducer = useCallback(
    (edge: string, data: Record<string, unknown>) => {
      const res = { ...data } as Record<string, unknown>;
      const graph = sigma.getGraph();
      const source = graph.source(edge);
      const target = graph.target(edge);

      const isConnectedToSelection = graphMode === 'path'
        ? pathEdgeKeys.has(graphEdgeKey(source, target))
        : (
          (selectedNodeId && (source === selectedNodeId || target === selectedNodeId)) ||
          highlightedPapers.has(source) ||
          highlightedPapers.has(target) ||
          (hoveredNode && (source === hoveredNode || target === hoveredNode))
        );

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
        res.color = THEME_COLORS[theme].edgeDimmed(weight, edgeOpacity);
        res.size = 0.7;
        res.zIndex = 0;
      } else {
        // Default: apply edge opacity
        const weight = (data.weight as number) || 0.1;
        res.color = THEME_COLORS[theme].edgeDefault(weight, edgeOpacity);
        res.size = 0.7;
      }

      return res;
    },
    [sigma, selectedNodeId, highlightedPapers, hoveredNode, hasActiveSelection, edgeOpacity, theme, graphMode, pathEdgeKeys],
  );

  // Apply settings including reducers and label visibility
  useEffect(() => {
    setSettings({
      nodeReducer,
      edgeReducer,
      renderLabels: showLabels,
      // Ink label in light; also fixes the both-theme hover label — Sigma's
      // default hover box is white, so a white label was invisible on hover.
      labelColor: { color: THEME_COLORS[theme].label },
      labelSize: 9,
      labelFont: 'Roboto, sans-serif',
      labelRenderedSizeThreshold: 6,
      zIndex: true,
    });
  }, [setSettings, nodeReducer, edgeReducer, showLabels, theme]);

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
  graphMode,
  pathEdgeKeys,
}: SigmaGraphViewProps) {
  const theme = useThemeObserver();
  const { graph } = useGraphData(graphData, minCitations, yearFilter, theme);
  const colors = THEME_COLORS[theme];

  if (!graphData || graphData.nodes.length === 0) {
    return null;
  }

  return (
    <div className="sigma-graph-container">
      <SigmaContainer
        graph={graph}
        style={{ width: '100%', height: '100%', background: 'var(--bg-elev)' }}
        settings={{
          renderLabels: showLabels,
          labelColor: { color: colors.label },
          labelSize: 9,
          labelFont: 'Roboto, sans-serif',
          labelRenderedSizeThreshold: 6,
          defaultEdgeColor: colors.defaultEdge,
          defaultNodeColor: colors.defaultNode,
          defaultDrawNodeHover: drawHoverInk,
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
          theme={theme}
          graphMode={graphMode}
          pathEdgeKeys={pathEdgeKeys}
        />
      </SigmaContainer>
    </div>
  );
}

export default SigmaGraphView;
