import { useState } from 'react';
import './DetailPanel.css';
import type { Paper } from '../types';
import { generateApaCitation } from '../utils/citation';
import { copyToClipboard } from '../utils/clipboard';

interface DetailPanelProps {
  paper: Paper;
  onViewPaper?: (paper: Paper) => void;
}

function DetailPanel({ paper, onViewPaper }: DetailPanelProps) {
  const [copied, setCopied] = useState(false);

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
      openalex: 'OpenAlex',
      dblp: 'DBLP',
      openalex_korean: 'Korean Journals',
    };
    return sourceMap[paper.source || ''] || paper.source || 'Unknown';
  };

  const handleCopyCitation = () => {
    const citation = generateApaCitation(paper);
    copyToClipboard(citation).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {
      console.error('Failed to copy citation');
    });
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
        {onViewPaper ? (
          <button
            className="detail-button view-paper-button"
            onClick={() => onViewPaper(paper)}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: '4px', verticalAlign: '-1px' }}>
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
            View Paper
          </button>
        ) : (paper.pdf_url || paper.url || paper.doi) && (
          <a
            href={paper.pdf_url || paper.url || `https://doi.org/${paper.doi}`}
            target="_blank"
            rel="noopener noreferrer"
            className="detail-button view-paper-button"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: '4px', verticalAlign: '-1px' }}>
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
            View Paper
          </a>
        )}
        <button
          className={`detail-button cite-button ${copied ? 'copied' : ''}`}
          onClick={handleCopyCitation}
        >
          {copied ? 'Copied!' : 'Cite'}
        </button>
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

