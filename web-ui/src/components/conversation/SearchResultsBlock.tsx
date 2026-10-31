import type { Paper, SearchResultsBlock as SearchResultsData } from '../../types';

interface SearchResultsBlockProps {
  block: SearchResultsData;
  onSelect: (paper: Paper) => void;
  onShowAll: () => void;
}

const PREVIEW_COUNT = 5;

/** Inline preview of a turn's search: top papers, then a hand-off to the artifact list. */
function SearchResultsBlock({ block, onSelect, onShowAll }: SearchResultsBlockProps) {
  const preview = block.papers.slice(0, PREVIEW_COUNT);
  return (
    <section className="conv-results" aria-label={`검색 결과 ${block.total}편`}>
      <ol className="conv-results-list">
        {preview.map((paper, index) => (
          <li key={String(paper.result_key ?? paper.doc_id)}>
            <button type="button" className="conv-result" onClick={() => onSelect(paper)}>
              <span className="conv-result-rank" aria-hidden="true">{index + 1}</span>
              <span className="conv-result-text">
                <span className="conv-result-title">{paper.title}</span>
                <span className="conv-result-meta">{[paper.year, paper.source].filter(Boolean).join(' · ')}</span>
              </span>
            </button>
          </li>
        ))}
      </ol>
      {block.total > 0 && (
        <button type="button" className="conv-results-more" onClick={onShowAll}>
          전체 {block.total}편 보기 →
        </button>
      )}
    </section>
  );
}

export default SearchResultsBlock;
