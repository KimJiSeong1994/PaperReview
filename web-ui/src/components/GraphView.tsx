import { useMemo } from 'react';
import Plot from 'react-plotly.js';
import type { Data, Layout } from 'plotly.js';
import './GraphView.css';
import type { GraphData, Paper } from '../types';

interface GraphViewProps {
  graphData: GraphData;
  selectedPaper: Paper | null;
  papers: Paper[];
  onNodeClick: (paper: Paper) => void;
}

function GraphView({ graphData, selectedPaper, papers, onNodeClick }: GraphViewProps) {
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

    // Edge trace
    const edgeX: number[] = [];
    const edgeY: number[] = [];
    
    edges.forEach(edge => {
      const sourceNode = nodes.find(n => n.id === edge.source);
      const targetNode = nodes.find(n => n.id === edge.target);
      
      if (sourceNode && targetNode) {
        edgeX.push(sourceNode.x, targetNode.x, null);
        edgeY.push(sourceNode.y, targetNode.y, null);
      }
    });

    const edgeTrace: Data = {
      x: edgeX,
      y: edgeY,
      mode: 'lines',
      line: {
        width: 0.7,
        color: 'rgba(156, 163, 175, 0.25)',
      },
      hoverinfo: 'skip',
      showlegend: false,
      type: 'scatter',
    };

    // Node trace
    const nodeX = nodes.map(n => n.x);
    const nodeY = nodes.map(n => n.y);
    const nodeColors = nodes.map(n => {
      const year = Number(n.year) || minYear;
      const relative = (year - minYear) / yearRange;
      const r = Math.floor(40 + relative * 80);
      const g = Math.floor(120 + relative * 90);
      const b = 160;
      return `rgba(${r}, ${g}, ${b}, 0.9)`;
    });

    const nodeSizes = nodes.map(n => {
      const citations = n.citations || 1;
      const baseSize = 12;
      const size = baseSize + 6 * Math.log10(citations + 1);
      // Match by node id or doc_id
      const isSelected = selectedPaper && (n.id === selectedPaper.doc_id || (n as any).doc_id === selectedPaper.doc_id);
      return isSelected ? size * 1.35 : size;
    });

    const nodeText = nodes.map(n => {
      const authors = n.authors?.slice(0, 2).join(', ') || 'Unknown';
      const year = n.year || '';
      return `${authors}, ${year}`;
    });

    // Create a node map for lookup
    const nodeMap = new Map(nodes.map(n => [n.id, n]));

    const nodeTrace: Data = {
      x: nodeX,
      y: nodeY,
      mode: 'markers+text',
      type: 'scatter',
      marker: {
        size: nodeSizes,
        color: nodeColors,
        line: {
          width: nodes.map(n => {
            const isSelected = selectedPaper && (n.id === selectedPaper.doc_id || (n as any).doc_id === selectedPaper.doc_id);
            return isSelected ? 3 : 2;
          }),
          color: nodes.map(n => {
            const isSelected = selectedPaper && (n.id === selectedPaper.doc_id || (n as any).doc_id === selectedPaper.doc_id);
            return isSelected ? '#9333ea' : '#ffffff';
          }),
        },
      },
      text: nodeText,
      textposition: 'top center',
      textfont: {
        size: 10,
        color: '#9ca3af',
      },
      hovertext: nodes.map(n => n.title),
      hoverinfo: 'text',
      showlegend: false,
      customdata: nodes.map(n => {
        // Use doc_id if available, otherwise use id
        const nodeDocId = (n as any).doc_id || n.id;
        return nodeDocId;
      }),
    };

    const plotData: Data[] = [edgeTrace, nodeTrace];

    const plotLayout: Partial<Layout> = {
      showlegend: false,
      hovermode: 'closest',
      margin: { l: 0, r: 0, t: 10, b: 10 },
      xaxis: { visible: false, range: [-1.2, 1.2] },
      yaxis: { visible: false, range: [-1.2, 1.2] },
      plot_bgcolor: '#181818',
      paper_bgcolor: '#181818',
      font: { color: '#ececec', family: 'Roboto, sans-serif' },
      height: 620,
    };

    return { plotData, layout: plotLayout };
  }, [graphData, selectedPaper]);

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
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: '100%', height: '100%' }}
        onClick={handlePlotClick}
        useResizeHandler
      />
    </div>
  );
}

export default GraphView;

