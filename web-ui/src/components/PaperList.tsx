import { useEffect, useRef } from 'react';
import './PaperList.css';
import type { Paper } from '../types';

interface PaperListProps {
  papers: Paper[];
  selectedPaper: Paper | null;
  onSelect: (paper: Paper) => void;
}

function PaperList({ papers, selectedPaper, onSelect }: PaperListProps) {
  const selectedRef = useRef<HTMLDivElement>(null);
  
  // Scroll to selected paper when it changes
  useEffect(() => {
    if (selectedPaper && selectedRef.current) {
      selectedRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    }
  }, [selectedPaper]);
  
  const formatAuthors = (authors: string[]): string => {
    if (!authors || authors.length === 0) return 'Unknown authors';
    if (authors.length <= 2) return authors.join(', ');
    return `${authors.slice(0, 2).join(', ')} + ${authors.length - 2} authors`;
  };

  const formatSummary = (paper: Paper): string => {
    const parts: string[] = [];
    if (paper.authors && paper.authors.length > 0) {
      parts.push(formatAuthors(paper.authors));
    }
    if (paper.journal) {
      parts.push(paper.journal);
    }
    if (paper.year) {
      parts.push(String(paper.year));
    }
    return parts.join(' · ');
  };

  return (
    <div className="paper-list">
      {papers.length > 0 && (
        <div
          key={papers[0].doc_id}
          ref={selectedPaper?.doc_id === papers[0].doc_id ? selectedRef : null}
          className={`paper-card ${papers[0].doc_id === selectedPaper?.doc_id ? 'selected' : ''} origin`}
          onClick={() => onSelect(papers[0])}
        >
          <div className="origin-badge">Origin Paper</div>
          <div className="paper-title">{papers[0].title}</div>
          <div className="paper-meta">{formatSummary(papers[0])}</div>
        </div>
      )}
      
      {papers.slice(1).map((paper) => (
        <div
          key={paper.doc_id}
          ref={selectedPaper?.doc_id === paper.doc_id ? selectedRef : null}
          className={`paper-card ${paper.doc_id === selectedPaper?.doc_id ? 'selected' : ''}`}
          onClick={() => onSelect(paper)}
        >
          <div className="paper-title">{paper.title}</div>
          <div className="paper-meta">{formatSummary(paper)}</div>
        </div>
      ))}
    </div>
  );
}

export default PaperList;

