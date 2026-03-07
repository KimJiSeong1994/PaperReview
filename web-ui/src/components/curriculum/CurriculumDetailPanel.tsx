import type { CurriculumPaper, CurriculumCourse } from './types';

interface CurriculumDetailPanelProps {
  paper: CurriculumPaper | null;
  courseDetail: CurriculumCourse | null;
  onSearchPaper: (paper: CurriculumPaper) => void;
}

export default function CurriculumDetailPanel({
  paper,
  courseDetail,
  onSearchPaper,
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
          Search in Jiphyeonjeon
        </button>
        {paper.arxiv_id && (
          <a
            href={`https://arxiv.org/abs/${paper.arxiv_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="curriculum-detail-action-btn"
          >
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
            Open via DOI
          </a>
        )}
      </div>
    </div>
  );
}
