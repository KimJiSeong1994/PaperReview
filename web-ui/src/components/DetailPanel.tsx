import { useState } from 'react';
import './DetailPanel.css';
import type { Paper } from '../types';

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

  // APA 형식으로 인용 생성
  const generateApaCitation = (): string => {
    const formatAuthorsApa = (authors: string[]) => {
      if (!authors || authors.length === 0) return 'Unknown Author';

      const formatted = authors.slice(0, 20).map((author) => {
        const parts = author.trim().split(' ');
        if (parts.length === 1) return parts[0];
        const lastName = parts[parts.length - 1];
        const initials = parts.slice(0, -1).map(p => p[0]?.toUpperCase() + '.').join(' ');
        return `${lastName}, ${initials}`;
      });

      if (authors.length > 20) {
        return formatted.slice(0, 19).join(', ') + ', ... ' + formatted[formatted.length - 1];
      } else if (formatted.length === 1) {
        return formatted[0];
      } else if (formatted.length === 2) {
        return formatted.join(', & ');
      } else {
        return formatted.slice(0, -1).join(', ') + ', & ' + formatted[formatted.length - 1];
      }
    };

    // 연도 추출 (year 또는 published_date에서)
    const getYear = () => {
      if (paper.year) return String(paper.year);
      if (paper.published_date) {
        const match = String(paper.published_date).match(/(\d{4})/);
        return match ? match[1] : 'n.d.';
      }
      return 'n.d.';
    };

    // 월 추출 (published_date에서)
    const getMonth = () => {
      if (paper.month) return paper.month;
      if (paper.published_date) {
        const date = new Date(paper.published_date);
        if (!isNaN(date.getTime())) {
          return date.toLocaleString('en-US', { month: 'long' });
        }
      }
      return '';
    };

    // 학회/저널 정보 추출
    const getVenueInfo = () => {
      // journal_ref가 있으면 사용
      if (paper.journal_ref) return paper.journal_ref;
      // journal이 있으면 사용
      if (paper.journal) return paper.journal;
      // comment에서 학회 정보 추출 (예: "Accepted at ECIR 2021")
      if (paper.comment) {
        const match = paper.comment.match(/(?:accepted at|published in|presented at)\s+(.+?)(?:;|$)/i);
        if (match) return match[1].trim();
        // 학회명이 포함된 경우
        if (/conference|proceedings|workshop|symposium|journal/i.test(paper.comment)) {
          return paper.comment;
        }
      }
      return '';
    };

    const authors = formatAuthorsApa(paper.authors || []);
    const year = getYear();
    const month = getMonth();
    const title = paper.title || 'Untitled';
    const venue = getVenueInfo();
    const pages = paper.pages || '';
    const volume = paper.volume || '';
    const issue = paper.issue || '';

    // 학회 논문인지 확인
    const isConferencePaper = venue && /proceedings|conference|workshop|symposium/i.test(venue);
    // arXiv 프리프린트인지 확인
    const isArxiv = paper.source === 'arXiv' || paper.arxiv_id;

    let citation = '';

    if (isConferencePaper) {
      // 학회 논문 형식: 저자 (년도, 월). 제목. In 학회명 (pp. 페이지).
      const yearPart = month ? `${year}, ${month}` : year;
      const pagesPart = pages ? ` (pp. ${pages})` : '';
      citation = `${authors} (${yearPart}). ${title}. In ${venue}${pagesPart}.`;
    } else if (isArxiv) {
      // arXiv 형식: 저자 (년도). 제목. arXiv preprint arXiv:ID.
      const arxivId = paper.arxiv_id || paper.url?.match(/abs\/(.+)/)?.[1] || '';
      citation = `${authors} (${year}). ${title}. arXiv preprint arXiv:${arxivId}.`;
    } else if (venue) {
      // 저널 논문 형식: 저자 (년도). 제목. 저널명, 권(호), 페이지.
      let venuePart = venue;
      if (volume) {
        venuePart += `, ${volume}`;
        if (issue) venuePart += `(${issue})`;
      }
      if (pages) venuePart += `, ${pages}`;
      citation = `${authors} (${year}). ${title}. ${venuePart}.`;
    } else {
      // 기본 형식
      citation = `${authors} (${year}). ${title}.`;
    }

    // DOI 또는 URL 추가
    if (paper.doi) {
      citation += ` https://doi.org/${paper.doi}`;
    } else if (paper.url && !isArxiv) {
      citation += ` ${paper.url}`;
    } else if (isArxiv && paper.url) {
      citation += ` ${paper.url}`;
    }

    return citation;
  };

  const handleCopyCitation = () => {
    const citation = generateApaCitation();

    // Clipboard API fallback for HTTP environments
    const copyToClipboard = (text: string) => {
      if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
      } else {
        // Fallback for HTTP
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        textArea.style.top = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        return new Promise<void>((resolve, reject) => {
          document.execCommand('copy') ? resolve() : reject();
          textArea.remove();
        });
      }
    };

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
        {onViewPaper && (
          <button
            className="detail-button view-paper-button"
            onClick={() => onViewPaper(paper)}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: '4px', verticalAlign: '-1px' }}>
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
            원문보기
          </button>
        )}
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
        <button
          className={`detail-button cite-button ${copied ? 'copied' : ''}`}
          onClick={handleCopyCitation}
        >
          {copied ? 'Copied!' : '인용하기'}
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

