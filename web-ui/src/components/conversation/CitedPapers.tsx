import type { Paper } from '../../types';
import { authorList, paperYear } from './conversationBlocks';

interface CitedPapersProps {
  /** Cited papers by their result number, ascending. */
  entries: { n: number; paper: Paper }[];
  /** Owning turn, for the row ids `cite-ref-{turnSeq}-{n}`. */
  turnSeq: number;
  onSelect: (paper: Paper) => void;
}

/** "참고 논문": only what the answer cited, numbered as in its text and in the results. */
function CitedPapers({ entries, turnSeq, onSelect }: CitedPapersProps) {
  if (entries.length === 0) return null;
  return (
    <section className="conv-refs" aria-label="참고 논문">
      <h4 className="conv-refs-title">
        참고 논문 <span className="conv-refs-count">{entries.length}</span>
      </h4>
      <ol className="conv-refs-list">
        {entries.map(({ n, paper }) => {
          const link = paper.pdf_url || paper.url;
          const meta = [authorList(paper.authors), paperYear(paper.year), paper.source].filter(Boolean).join(' · ');
          return (
            <li key={n} className="conv-ref" id={`cite-ref-${turnSeq}-${n}`}>
              <span className="conv-ref-n">{n}</span>
              <div className="conv-ref-body">
                <button type="button" className="conv-ref-title" onClick={() => onSelect(paper)}>{paper.title}</button>
                {meta && <div className="conv-ref-meta">{meta}</div>}
              </div>
              {link ? (
                <a className="conv-ref-link" href={link} target="_blank" rel="noopener noreferrer" aria-label={`${paper.title} 원문 열기`}>
                  ↗
                </a>
              ) : <span />}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export default CitedPapers;
