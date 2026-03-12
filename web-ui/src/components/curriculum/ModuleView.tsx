import type { CurriculumModule, CurriculumPaper } from './types';

interface ModuleViewProps {
  module: CurriculumModule | null;
  readPapers: Set<string>;
  selectedPaperId: string | null;
  onSelectPaper: (id: string) => void;
  onToggleRead: (id: string) => void;
  getModuleProgress: (moduleId: string) => { read: number; total: number };
  onDeepReviewModule?: (moduleId: string) => void;
  reviewStatus?: 'idle' | 'processing' | 'completed' | 'failed';
  reviewingModuleId?: string | null;
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function PaperCard({
  paper,
  isRead,
  isSelected,
  onSelect,
  onToggleRead,
}: {
  paper: CurriculumPaper;
  isRead: boolean;
  isSelected: boolean;
  onSelect: () => void;
  onToggleRead: () => void;
}) {
  return (
    <div
      className={`curriculum-paper-card ${isSelected ? 'selected' : ''} ${isRead ? 'read' : ''}`}
      onClick={onSelect}
    >
      <div
        className={`curriculum-paper-checkbox ${isRead ? 'checked' : ''}`}
        onClick={(e) => {
          e.stopPropagation();
          onToggleRead();
        }}
      >
        {isRead && <CheckIcon />}
      </div>
      <div className="curriculum-paper-info">
        <div className="curriculum-paper-title">{paper.title}</div>
        <div className="curriculum-paper-meta">
          {paper.authors.slice(0, 3).join(', ')}
          {paper.authors.length > 3 && ' et al.'}
          {' · '}
          {paper.year} · {paper.venue}
        </div>
        <div className="curriculum-paper-context">{paper.context}</div>
      </div>
      <span className={`curriculum-category-badge ${paper.category}`}>
        {paper.category}
      </span>
    </div>
  );
}

export default function ModuleView({
  module,
  readPapers,
  selectedPaperId,
  onSelectPaper,
  onToggleRead,
  getModuleProgress,
  onDeepReviewModule,
  reviewStatus = 'idle',
  reviewingModuleId = null,
}: ModuleViewProps) {
  if (!module) {
    return (
      <div className="curriculum-main">
        <div className="curriculum-empty">Select a course and module to view papers</div>
      </div>
    );
  }

  const mp = getModuleProgress(module.id);
  const percent = mp.total > 0 ? Math.round((mp.read / mp.total) * 100) : 0;

  return (
    <div className="curriculum-main">
      <div className="curriculum-module-header">
        <div className="curriculum-module-header-title">
          Week {module.week}: {module.title}
        </div>
        <div className="curriculum-module-header-desc">{module.description}</div>
        <div className="curriculum-module-header-progress">
          <div className="curriculum-progress-bar">
            <div
              className="curriculum-progress-fill"
              style={{ width: `${percent}%` }}
            />
          </div>
          <span className="curriculum-progress-text">
            {mp.read} / {mp.total} ({percent}%)
          </span>
        </div>
        {onDeepReviewModule && (
          <div className="curriculum-module-header-actions">
            <button
              className={`curriculum-detail-action-btn deep-review module-review ${
                reviewingModuleId === module.id && reviewStatus === 'completed' ? 'success' : ''
              }`}
              onClick={() => onDeepReviewModule(module.id)}
              disabled={reviewStatus === 'processing'}
            >
              {reviewingModuleId === module.id && reviewStatus === 'processing'
                ? 'Analyzing...'
                : reviewingModuleId === module.id && reviewStatus === 'completed'
                  ? 'Saved to Bookmarks!'
                  : reviewingModuleId === module.id && reviewStatus === 'failed'
                    ? 'Failed'
                    : `Analyze All Papers (${mp.total})`}
            </button>
          </div>
        )}
      </div>

      <div className="curriculum-papers-scroll">
        {module.topics.map((topic) => (
          <div key={topic.id} className="curriculum-topic-section">
            <div className="curriculum-topic-title">{topic.title}</div>
            {topic.papers.map((paper) => (
              <PaperCard
                key={paper.id}
                paper={paper}
                isRead={readPapers.has(paper.id)}
                isSelected={selectedPaperId === paper.id}
                onSelect={() => onSelectPaper(paper.id)}
                onToggleRead={() => onToggleRead(paper.id)}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
