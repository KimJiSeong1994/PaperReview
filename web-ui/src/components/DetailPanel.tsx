import './DetailPanel.css';
import type { Paper } from '../types';

interface DetailPanelProps {
  paper: Paper;
}

function DetailPanel({ paper }: DetailPanelProps) {
  const formatAuthors = (authors: string[]): string => {
    if (!authors || authors.length === 0) return 'Unknown authors';
    if (authors.length <= 3) return authors.join(', ');
    return `${authors.slice(0, 3).join(', ')} + ${authors.length - 3} authors`;
  };

  const getSourceDisplay = (): string => {
    const sourceMap: Record<string, string> = {
      arxiv: 'arXiv',
      connected_papers: 'Connected Papers',
      google_scholar: 'Google Scholar',
    };
    return sourceMap[paper.source || ''] || paper.source || 'Unknown';
  };

  return (
    <div className="detail-panel">
      <h2 className="detail-title">{paper.title}</h2>
      
      <div className="detail-meta">
        {formatAuthors(paper.authors || [])}
        {paper.year && ` · ${paper.year}`}
        {paper.journal && ` · ${paper.journal}`}
        {` · ${getSourceDisplay()}`}
      </div>

      <div className="detail-actions">
        {paper.url && (
          <a href={paper.url} target="_blank" rel="noopener noreferrer" className="detail-button">
            원문 열기
          </a>
        )}
        {paper.pdf_url && (
          <a href={paper.pdf_url} target="_blank" rel="noopener noreferrer" className="detail-button">
            PDF
          </a>
        )}
        {paper.doi && (
          <a
            href={`https://doi.org/${paper.doi}`}
            target="_blank"
            rel="noopener noreferrer"
            className="detail-button"
          >
            DOI
          </a>
        )}
      </div>

      <div className="detail-divider" />

      <div className="detail-metric">
        <span className="metric-label">Citations</span>
        <span className="metric-value">{paper.citations || 0}</span>
      </div>

      <div className="detail-abstract">
        <h3>Abstract</h3>
        <p>{paper.abstract || '초록 정보가 없습니다.'}</p>
      </div>
    </div>
  );
}

export default DetailPanel;

