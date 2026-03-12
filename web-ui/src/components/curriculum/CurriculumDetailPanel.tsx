import type { CurriculumPaper, CurriculumCourse } from './types';

interface CurriculumDetailPanelProps {
  paper: CurriculumPaper | null;
  courseDetail: CurriculumCourse | null;
  onSearchPaper: (paper: CurriculumPaper) => void;
  onDeepReview?: (paper: CurriculumPaper) => void;
  reviewStatus?: 'idle' | 'processing' | 'completed' | 'failed';
  reviewProgress?: string;
  reviewingPaperIds?: Set<string>;
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
      <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

function ArxivIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  );
}

function DoiIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </svg>
  );
}

function DeepReviewIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
      <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

export default function CurriculumDetailPanel({
  paper,
  courseDetail,
  onSearchPaper,
  onDeepReview,
  reviewStatus = 'idle',
  reviewProgress = '',
  reviewingPaperIds = new Set(),
}: CurriculumDetailPanelProps) {
  // No paper selected — show course overview
  if (!paper) {
    if (!courseDetail) {
      return (
        <div className="curriculum-detail">
          <div className="curriculum-detail-placeholder">
            Select a course from the sidebar to get started
          </div>
        </div>
      );
    }

    return (
      <div className="curriculum-detail">
        <div className="curriculum-detail-overview">
          <h3>{courseDetail.name}</h3>
          <p>{courseDetail.description}</p>
          <div className="curriculum-course-meta" style={{ marginBottom: 12 }}>
            <span>{courseDetail.instructor}</span>
            <span className={`curriculum-badge ${courseDetail.difficulty}`}>
              {courseDetail.difficulty}
            </span>
          </div>
          {courseDetail.url && (
            <a
              href={courseDetail.url}
              target="_blank"
              rel="noopener noreferrer"
              className="curriculum-detail-action-btn"
              style={{ marginBottom: 16 }}
            >
              Visit Course Website
            </a>
          )}
          {courseDetail.prerequisites.length > 0 && (
            <div className="curriculum-detail-prereqs">
              <h4>Prerequisites</h4>
              <ul>
                {courseDetail.prerequisites.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    );
  }

  const isReviewingThis = reviewingPaperIds.has(paper.id);
  const isAnyReviewing = reviewStatus === 'processing';

  // Paper selected — show detail
  return (
    <div className="curriculum-detail">
      <div className="curriculum-detail-title">{paper.title}</div>
      <div className="curriculum-detail-authors">
        {paper.authors.join(', ')}
      </div>
      <div className="curriculum-detail-venue">
        {paper.venue} · {paper.year}
        {paper.arxiv_id && ` · arXiv: ${paper.arxiv_id}`}
      </div>

      <span className={`curriculum-category-badge ${paper.category}`} style={{ marginBottom: 16, display: 'inline-block' }}>
        {paper.category}
      </span>

      <div className="curriculum-detail-context-box">
        <div className="curriculum-detail-context-label">Why This Paper Matters</div>
        <div className="curriculum-detail-context-text">{paper.context}</div>
      </div>

      <div className="curriculum-detail-actions">
        <button
          className="curriculum-detail-action-btn primary"
          onClick={() => onSearchPaper(paper)}
        >
          <SearchIcon />
          Search in Jiphyeonjeon
        </button>
        {paper.arxiv_id && (
          <a
            href={`https://arxiv.org/abs/${paper.arxiv_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="curriculum-detail-action-btn"
          >
            <ArxivIcon />
            Open on arXiv
          </a>
        )}
        {paper.doi && (
          <a
            href={`https://doi.org/${paper.doi}`}
            target="_blank"
            rel="noopener noreferrer"
            className="curriculum-detail-action-btn"
          >
            <DoiIcon />
            Open via DOI
          </a>
        )}
        {onDeepReview && (
          <button
            className={`curriculum-detail-action-btn deep-review ${
              isReviewingThis && reviewStatus === 'completed' ? 'success' : ''
            }`}
            onClick={() => onDeepReview(paper)}
            disabled={isAnyReviewing}
          >
            {isReviewingThis && reviewStatus === 'processing' ? (
              <>
                <div className="curriculum-btn-spinner" />
                Analyzing...
              </>
            ) : isReviewingThis && reviewStatus === 'completed' ? (
              <>
                <CheckIcon />
                Saved to Bookmarks!
              </>
            ) : isReviewingThis && reviewStatus === 'failed' ? (
              'Failed'
            ) : (
              <>
                <DeepReviewIcon />
                Deep Research &amp; Bookmark
              </>
            )}
          </button>
        )}
      </div>

      {isReviewingThis && reviewStatus === 'processing' && reviewProgress && (
        <div className="curriculum-review-progress">
          <div className="curriculum-review-progress-spinner" />
          <span>{reviewProgress}</span>
        </div>
      )}
    </div>
  );
}
