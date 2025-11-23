import { useMemo } from 'react';
import Plot from 'react-plotly.js';
import type { Data, Layout } from 'plotly.js';
import './GraphView.css';
import type { GraphData, Paper } from '../types';

interface GraphViewProps {
  graphData: GraphData;
  selectedPaper: Paper | null;
  highlightedPapers: Set<string>;
  papers: Paper[];
  onNodeClick: (paper: Paper) => void;
}

function GraphView({ graphData, selectedPaper, highlightedPapers, papers, onNodeClick }: GraphViewProps) {
  const { plotData, layout } = useMemo(() => {
    if (!graphData || graphData.nodes.length === 0) {
      return { plotData: [], layout: {} };
    }

    const nodes = graphData.nodes;
    const edges = graphData.edges;

    // Calculate year range for coloring
    const years = nodes.map(n => n.year).filter(Boolean) as number[];
    const minYear = years.length > 0 ? Math.min(...years) : 2010;
    const maxYear = years.length > 0 ? Math.max(...years) : 2024;
    const yearRange = maxYear - minYear || 1;

    // Edge trace - highlight edges connected to selected/highlighted papers
    const edgeX: number[] = [];
    const edgeY: number[] = [];
    const edgeXHighlighted: number[] = [];
    const edgeYHighlighted: number[] = [];
    const selectedPaperIdForEdges = selectedPaper?.doc_id ? String(selectedPaper.doc_id) : null;
    
    edges.forEach(edge => {
      const sourceNode = nodes.find(n => n.id === edge.source || String(n.id) === String(edge.source));
      const targetNode = nodes.find(n => n.id === edge.target || String(n.id) === String(edge.target));
      
      if (sourceNode && targetNode) {
        const sourceId = String(edge.source);
        const targetId = String(edge.target);
        const isHighlighted = 
          (selectedPaperIdForEdges && (sourceId === selectedPaperIdForEdges || targetId === selectedPaperIdForEdges)) ||
          highlightedPapers.has(sourceId) || highlightedPapers.has(targetId);
        
        if (isHighlighted) {
          edgeXHighlighted.push(sourceNode.x, targetNode.x, NaN);
          edgeYHighlighted.push(sourceNode.y, targetNode.y, NaN);
        } else {
          edgeX.push(sourceNode.x, targetNode.x, NaN);
          edgeY.push(sourceNode.y, targetNode.y, NaN);
        }
      }
    });

    // Calculate opacity for non-highlighted edges based on whether there are selected/highlighted nodes
    const hasHighlightedNodes = selectedPaper || highlightedPapers.size > 0;
    
    // Normal edges - light gray color
    const edgeTrace: Data = {
      x: edgeX,
      y: edgeY,
      mode: 'lines',
      line: {
        width: 0.7,
        color: hasHighlightedNodes ? 'rgba(156, 163, 175, 0.4)' : 'rgba(156, 163, 175, 0.6)',
      },
      hoverinfo: 'skip',
      showlegend: false,
      type: 'scatter',
    };

    // Highlighted edges trace - light purple, thicker
    const highlightedEdgeTrace: Data | null = edgeXHighlighted.length > 0 ? {
      x: edgeXHighlighted,
      y: edgeYHighlighted,
      mode: 'lines',
      line: {
        width: 2.5,
        color: 'rgba(168, 85, 247, 0.8)', // Light purple for highlighted edges
      },
      hoverinfo: 'skip',
      showlegend: false,
      type: 'scatter',
    } : null;

    // Separate nodes into three groups for z-ordering
    const selectedPaperId = selectedPaper ? String(selectedPaper.doc_id) : null;
    const normalNodes: typeof nodes = [];
    const highlightedNodes: typeof nodes = [];
    const selectedNodes: typeof nodes = [];
    
    nodes.forEach(n => {
      const nodeId = String((n as any).doc_id || n.id);
      if (selectedPaperId === nodeId) {
        selectedNodes.push(n);
      } else if (highlightedPapers.has(nodeId)) {
        highlightedNodes.push(n);
      } else {
        normalNodes.push(n);
      }
    });

    // Helper function to truncate title to a brief version
    const truncateTitle = (title: string, maxWords: number = 5): string => {
      if (!title) return 'Untitled';
      const words = title.split(' ');
      if (words.length <= maxWords) return title;
      return words.slice(0, maxWords).join(' ') + '...';
    };

    // Helper function to create node trace
    const createNodeTrace = (nodeList: typeof nodes, isHighlighted: boolean, isSelected: boolean): Data | null => {
      if (nodeList.length === 0) return null;
      
      const nodeX = nodeList.map(n => n.x);
      const nodeY = nodeList.map(n => n.y);
      
      // Calculate opacity for normal nodes based on whether there are selected/highlighted nodes
      const hasHighlightedNodes = selectedPaper || highlightedPapers.size > 0;
      
      // Calculate colors for all nodes - exactly matching web_app.py
      const nodeColors = nodeList.map(n => {
        try {
          // Get year and calculate color - exactly like web_app.py line 298-301
          const nodeYear = n.year ? Number(n.year) : null;
          const year = (nodeYear && !isNaN(nodeYear)) ? nodeYear : minYear;
          
          // Calculate relative position in year range - exactly like web_app.py
          const relative = yearRange > 0 ? (year - minYear) / yearRange : 0;
          const baseGreen = Math.floor(150 + relative * 70); // Green: 150~220 based on year
          
          if (isSelected) {
            // Selected node - purple color matching highlighted edges
            return 'rgba(168, 85, 247, 0.95)'; // Purple color like edges
          } else {
            // All other nodes: use original green/blue color with 0.95 opacity (exactly like web_app.py line 301)
            // Ensure baseGreen is clamped to valid range
            const clampedGreen = Math.max(150, Math.min(220, baseGreen));
            // Return color as a proper rgba string
            return `rgba(60, ${clampedGreen}, 150, 0.95)`;
          }
        } catch (error) {
          // Fallback color if calculation fails
          console.error('Error calculating node color:', error, n);
          return 'rgba(60, 150, 150, 0.95)';
        }
      });
      
      // Debug: Log first few colors to verify they're being calculated correctly
      if (nodeColors.length > 0) {
        console.log('Sample node colors:', nodeColors.slice(0, 3));
      }

      const nodeSizes = nodeList.map(n => {
        const citations = n.citations || 1;
        const baseSize = 12;
        const size = baseSize + 6 * Math.log10(citations + 1);
        if (isSelected) {
          return size * 1.5;
        } else if (isHighlighted) {
          return size * 1.35; // Similar size to selected
        }
        return size;
      });

      // Ensure nodeColors is a valid array with proper color strings
      const validColors = nodeColors.length > 0 && nodeColors.every(c => typeof c === 'string' && c.startsWith('rgba'))
        ? nodeColors 
        : nodeList.map(() => 'rgba(60, 150, 150, 0.95)'); // Fallback if colors are invalid

      return {
        x: nodeX,
        y: nodeY,
        mode: 'markers', // Remove text from markers, use separate text trace
        type: 'scatter',
        marker: {
          size: nodeSizes,
          color: validColors, // Use validated colors array (opacity already in rgba values)
          line: {
            width: isSelected ? 3.5 : (isHighlighted ? 3 : 2),
            color: isSelected 
              ? 'rgba(221, 214, 254, 1)' // Light purple border for selected node to match purple node color
              : (isHighlighted 
                ? '#ffffff' // White border for highlighted
                : (hasHighlightedNodes 
                  ? 'rgba(255, 255, 255, 0.6)' // Slightly transparent white border for normal nodes when highlighted
                  : '#ffffff')),
          },
        },
        hovertext: nodeList.map(n => n.title || ''),
        hoverinfo: 'text',
        showlegend: false,
        customdata: nodeList.map(n => {
          const nodeDocId = (n as any).doc_id || n.id;
          return nodeDocId;
        }),
      };
    };

    // Create node traces in order (normal -> highlighted -> selected)
    // Last trace will be drawn on top
    const normalNodeTrace = createNodeTrace(normalNodes, false, false);
    const highlightedNodeTrace = createNodeTrace(highlightedNodes, true, false);
    const selectedNodeTrace = createNodeTrace(selectedNodes, false, true);

    // Helper function to create text-only trace positioned above nodes
    const createTextTrace = (nodeList: typeof nodes, isHighlighted: boolean, isSelected: boolean): Data | null => {
      if (nodeList.length === 0) return null;
      
      const hasHighlightedNodes = selectedPaper || highlightedPapers.size > 0;
      const textOffset = 0.08; // Offset to move text higher above nodes
      
      const nodeX = nodeList.map(n => n.x);
      const nodeY = nodeList.map(n => n.y + textOffset); // Move text higher
      const nodeText = nodeList.map(n => {
        return truncateTitle(n.title || 'Untitled', 5);
      });

      return {
        x: nodeX,
        y: nodeY,
        mode: 'text',
        type: 'scatter',
        text: nodeText,
        textposition: 'middle center',
        textfont: {
          size: 9,
          color: hasHighlightedNodes && !isSelected && !isHighlighted 
            ? 'rgba(255, 255, 255, 0.6)' // More visible text for non-highlighted nodes
            : 'rgba(255, 255, 255, 0.9)', // White text for better visibility on dark background
        },
        hoverinfo: 'skip',
        showlegend: false,
      };
    };

    // Create text traces
    const normalTextTrace = createTextTrace(normalNodes, false, false);
    const highlightedTextTrace = createTextTrace(highlightedNodes, true, false);
    const selectedTextTrace = createTextTrace(selectedNodes, false, true);

    // Build plot data with proper z-ordering:
    // 1. Normal edges (bottom)
    // 2. Highlighted edges (middle)
    // 3. Normal nodes (middle)
    // 4. Highlighted nodes (upper)
    // 5. Selected node (top)
    // 6. Text traces (on top of nodes)
    const plotData: Data[] = [
      edgeTrace,
      ...(highlightedEdgeTrace ? [highlightedEdgeTrace] : []),
      ...(normalNodeTrace ? [normalNodeTrace] : []),
      ...(highlightedNodeTrace ? [highlightedNodeTrace] : []),
      ...(selectedNodeTrace ? [selectedNodeTrace] : []),
      ...(normalTextTrace ? [normalTextTrace] : []),
      ...(highlightedTextTrace ? [highlightedTextTrace] : []),
      ...(selectedTextTrace ? [selectedTextTrace] : []),
    ].filter(Boolean) as Data[];

    const plotLayout: Partial<Layout> = {
      showlegend: false,
      hovermode: 'closest',
      margin: { l: 0, r: 0, t: 10, b: 10 },
      xaxis: { 
        visible: false, 
        range: [-1.2, 1.2],
        fixedrange: false, // Allow zoom/pan
      },
      yaxis: { 
        visible: false, 
        range: [-1.2, 1.2],
        fixedrange: false, // Allow zoom/pan
      },
      plot_bgcolor: '#181818',
      paper_bgcolor: '#181818',
      font: { color: '#ececec', family: 'Roboto, sans-serif' },
      height: 620,
      dragmode: 'pan', // Enable pan mode for dragging
    };

    return { plotData, layout: plotLayout };
  }, [graphData, selectedPaper, highlightedPapers]);

  const handlePlotClick = (data: any) => {
    if (data.points && data.points.length > 0) {
      const point = data.points[0];
      if (point.customdata) {
        const nodeDocId = point.customdata;
        // Find the corresponding paper from papers array by doc_id
        const paper = papers.find(p => {
          const pId = String(p.doc_id);
          const nId = String(nodeDocId);
          return pId === nId || pId === nodeDocId || p.doc_id === nodeDocId;
        });
        if (paper) {
          onNodeClick(paper);
        } else {
          // Fallback: try to find by title from graph node
          const node = graphData.nodes.find(n => {
            const nId = (n as any).doc_id || n.id;
            return String(nId) === String(nodeDocId) || n.id === nodeDocId;
          });
          if (node) {
            const paperByTitle = papers.find(p => p.title === node.title);
            if (paperByTitle) {
              onNodeClick(paperByTitle);
            }
          }
        }
      }
    }
  };

  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className="graph-empty">
        <p>그래프 데이터가 없습니다.</p>
      </div>
    );
  }

  return (
    <div className="graph-view">
      <Plot
        data={plotData}
        layout={layout}
        config={{ 
          displayModeBar: true,
          modeBarButtonsToRemove: ['select2d', 'lasso2d'],
          displaylogo: false,
          responsive: true,
          scrollZoom: true,
          doubleClick: 'reset',
          toImageButtonOptions: {
            format: 'png',
            filename: 'graph',
            height: 620,
            width: 1200,
            scale: 1
          }
        }}
        style={{ width: '100%', height: '100%' }}
        onClick={handlePlotClick}
        useResizeHandler
      />
    </div>
  );
}

export default GraphView;

