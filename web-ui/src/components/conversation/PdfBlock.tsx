import type { PaperPdfBlock } from '../../types';

interface PdfBlockProps {
  block: PaperPdfBlock;
  onOpen: () => void;
}

/** A paper the assistant opened; the PDF itself reads in the artifact's PDF tab. */
function PdfBlock({ block, onOpen }: PdfBlockProps) {
  const meta = [block.authors.slice(0, 3).join(', ') + (block.authors.length > 3 ? ' et al.' : ''), block.year]
    .filter(Boolean)
    .join(' · ');
  return (
    <section className="conv-review" aria-label={`PDF: ${block.paper_title}`}>
      <p className="conv-review-title">{block.paper_title}</p>
      <div className="conv-review-row">
        {meta && <span className="conv-review-progress">{meta}</span>}
        <button type="button" className="conv-results-more" onClick={onOpen}>PDF 열기 →</button>
      </div>
    </section>
  );
}

export default PdfBlock;
