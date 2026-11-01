import type { PdfHighlightsBlock } from '../../types';
import { highlightCategory } from './conversationBlocks';

interface HighlightsBlockProps {
  block: PdfHighlightsBlock;
  /** Opens the PDF tab. The overlay renders lazily per page, so it does not scroll to the passage. */
  onOpen: () => void;
}

/** Highlights the assistant found in a paper: category chip and passage, each opening the PDF. */
function HighlightsBlock({ block, onOpen }: HighlightsBlockProps) {
  return (
    <section className="conv-highlights" aria-label={`하이라이트: ${block.paper_title}`}>
      <p className="conv-review-title">{block.paper_title}</p>
      {block.highlights.length === 0 ? (
        <p className="conv-note">표시할 문장을 찾지 못했어요.</p>
      ) : (
        <ul className="conv-results-list">
          {block.highlights.map(highlight => {
            const category = highlightCategory(highlight.category);
            return (
              <li key={highlight.id}>
                <button type="button" className="conv-result conv-highlight" onClick={onOpen}>
                  <span className={`conv-hl-chip is-${category.tone}`}>{category.label}</span>
                  <span className="conv-result-text conv-highlight-text">{highlight.text}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <button type="button" className="conv-results-more" onClick={onOpen}>PDF에서 보기 →</button>
    </section>
  );
}

export default HighlightsBlock;
