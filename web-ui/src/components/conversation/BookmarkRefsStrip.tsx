import { Link } from 'react-router-dom';
import type { BookmarkRefsBlock } from '../../types';

interface BookmarkRefsStripProps {
  block: BookmarkRefsBlock;
  /** Prefix for chip ids; `[Bn]` in the answer focuses `${idPrefix}-n`. */
  idPrefix: string;
  /** Opens the artifact's 리뷰 tab for a bookmark's review session. */
  onOpenReview: (sessionId: string, title: string) => void;
}

/** "근거 북마크": the bookmarks an answer drew on, each a link to it in MyPage. */
function BookmarkRefsStrip({ block, idPrefix, onOpenReview }: BookmarkRefsStripProps) {
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
            {bookmark.session_id && (
              <button
                type="button"
                className="conv-bookmark-review"
                aria-label={`${bookmark.title} 리뷰 보기`}
                onClick={() => onOpenReview(bookmark.session_id!, bookmark.title)}
              >
                리뷰 보기
              </button>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}

export default BookmarkRefsStrip;
