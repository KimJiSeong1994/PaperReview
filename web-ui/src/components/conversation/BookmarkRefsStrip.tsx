import { Link } from 'react-router-dom';
import type { BookmarkRefsBlock } from '../../types';

interface BookmarkRefsStripProps {
  block: BookmarkRefsBlock;
  /** Prefix for chip ids; `[Bn]` in the answer focuses `${idPrefix}-n`. */
  idPrefix: string;
}

/** "근거 북마크": the bookmarks an answer drew on, each a link to it in MyPage. */
function BookmarkRefsStrip({ block, idPrefix }: BookmarkRefsStripProps) {
  if (block.bookmarks.length === 0) return null;
  return (
    <nav className="conv-bookmarks" aria-label="근거 북마크">
      <span className="conv-bookmarks-label">근거 북마크</span>
      <ul className="conv-bookmarks-list">
        {block.bookmarks.map((bookmark, index) => (
          <li key={bookmark.id}>
            <Link id={`${idPrefix}-${index + 1}`} className="conv-bookmark-chip" to={bookmark.url}>
              <span className="conv-bookmark-n" aria-hidden="true">B{index + 1}</span>
              <span className="conv-bookmark-title">{bookmark.title}</span>
              <span className="conv-bookmark-meta">
                {bookmark.num_papers}편{bookmark.has_report ? ' · 리포트' : ''}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export default BookmarkRefsStrip;
