import type { Paper } from '../types';

function formatAuthorsApa(authors: string[]): string {
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
}

export function generateApaCitation(paper: Paper): string {
  const getYear = () => {
    if (paper.year) return String(paper.year);
    if (paper.published_date) {
      const match = String(paper.published_date).match(/(\d{4})/);
      return match ? match[1] : 'n.d.';
    }
    return 'n.d.';
  };

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

  const getVenueInfo = () => {
    if (paper.journal_ref) return paper.journal_ref;
    if (paper.journal) return paper.journal;
    if (paper.comment) {
      const match = paper.comment.match(/(?:accepted at|published in|presented at)\s+(.+?)(?:;|$)/i);
      if (match) return match[1].trim();
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

  const isConferencePaper = venue && /proceedings|conference|workshop|symposium/i.test(venue);
  const isArxiv = paper.source === 'arXiv' || paper.arxiv_id;

  let citation = '';

  if (isConferencePaper) {
    const yearPart = month ? `${year}, ${month}` : year;
    const pagesPart = pages ? ` (pp. ${pages})` : '';
    citation = `${authors} (${yearPart}). ${title}. In ${venue}${pagesPart}.`;
  } else if (isArxiv) {
    const arxivId = paper.arxiv_id || paper.url?.match(/abs\/(.+)/)?.[1] || '';
    citation = `${authors} (${year}). ${title}. arXiv preprint arXiv:${arxivId}.`;
  } else if (venue) {
    let venuePart = venue;
    if (volume) {
      venuePart += `, ${volume}`;
      if (issue) venuePart += `(${issue})`;
    }
    if (pages) venuePart += `, ${pages}`;
    citation = `${authors} (${year}). ${title}. ${venuePart}.`;
  } else {
    citation = `${authors} (${year}). ${title}.`;
  }

  if (paper.doi) {
    citation += ` https://doi.org/${paper.doi}`;
  } else if (paper.url && !isArxiv) {
    citation += ` ${paper.url}`;
  } else if (isArxiv && paper.url) {
    citation += ` ${paper.url}`;
  }

  return citation;
}
