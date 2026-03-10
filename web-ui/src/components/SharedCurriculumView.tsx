import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getSharedCurriculum } from '../api/client';
import type { SharedCurriculumData } from '../api/client';
import './CurriculumPage.css';

type SharedError = 'not_found' | 'expired' | 'unknown' | null;

export default function SharedCurriculumView() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<SharedCurriculumData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<SharedError>(null);
  const [expandedModuleId, setExpandedModuleId] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    setError(null);
    getSharedCurriculum(token)
      .then((result) => {
        setData(result);
        // Auto-expand first module
        if (result.course?.modules?.length > 0) {
          setExpandedModuleId(result.course.modules[0].id);
        }
      })
      .catch((err) => {
        const status = err?.response?.status;
        if (status === 410) setError('expired');
        else if (status === 404) setError('not_found');
        else setError('unknown');
      })
      .finally(() => setLoading(false));
  }, [token]);

  const totalPapers = useMemo(() => {
    if (!data?.course?.modules) return 0;
    let count = 0;
    for (const mod of data.course.modules) {
      for (const topic of mod.topics) {
        count += topic.papers.length;
      }
    }
    return count;
  }, [data]);

  if (loading) {
    return (
      <div className="shared-view">
        <div className="shared-view-loading">Loading shared curriculum...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="shared-view">
        <div className="shared-view-error">
          {error === 'expired' && (
            <>
              <h2>Link Expired</h2>
              <p>This share link has expired and is no longer available.</p>
            </>
          )}
          {error === 'not_found' && (
            <>
              <h2>Not Found</h2>
              <p>This share link is invalid or has been revoked.</p>
            </>
          )}
          {error === 'unknown' && (
            <>
              <h2>Error</h2>
              <p>Something went wrong loading this shared curriculum.</p>
            </>
          )}
        </div>
      </div>
    );
  }

  if (!data) return null;

  const { summary, course } = data;
  const isAuthenticated = !!localStorage.getItem('access_token');

  return (
    <div className="shared-curriculum-view">
      {/* Header */}
      <div className="shared-view-header">
        <div className="shared-view-brand">
          <img
            src="/Jiphyeonjeon_llama.png"
            alt="Jiphyeonjeon"
            className="shared-view-logo"
            onError={(e) => { e.currentTarget.style.display = 'none'; }}
          />
          <span className="shared-view-brand-name">Jiphyeonjeon</span>
          <span className="shared-view-badge">Shared Curriculum</span>
        </div>
      </div>

      <div className="shared-curriculum-content">
        {/* Course info */}
        <div className="shared-curriculum-info">
          <h1 className="shared-curriculum-title">{summary.name}</h1>
          <div className="shared-curriculum-meta">
            <span className={`curriculum-badge ${summary.difficulty}`}>{summary.difficulty}</span>
            <span>{summary.total_modules} modules</span>
            <span>{totalPapers} papers</span>
            {summary.university && <span>{summary.university}</span>}
            {summary.instructor && <span>by {summary.instructor}</span>}
          </div>
          {summary.description && (
            <p className="shared-curriculum-description">{summary.description}</p>
          )}
          {summary.prerequisites && summary.prerequisites.length > 0 && (
            <div className="shared-curriculum-prereqs">
              <strong>Prerequisites:</strong> {summary.prerequisites.join(', ')}
            </div>
          )}

          {isAuthenticated && (
            <button
              className="shared-curriculum-fork-btn"
              onClick={() => navigate('/curriculum')}
            >
              Open Curriculum Page
            </button>
          )}
        </div>

        {/* Modules */}
        <div className="shared-curriculum-modules">
          {course.modules.map((mod) => {
            const isExpanded = expandedModuleId === mod.id;
            const paperCount = mod.topics.reduce((sum, t) => sum + t.papers.length, 0);
            return (
              <div key={mod.id} className="shared-curriculum-module">
                <div
                  className={`shared-curriculum-module-header ${isExpanded ? 'expanded' : ''}`}
                  onClick={() => setExpandedModuleId(isExpanded ? null : mod.id)}
                >
                  <svg viewBox="0 0 16 16" fill="currentColor" width="10" height="10"
                    style={{ transform: isExpanded ? 'rotate(90deg)' : 'rotate(0)', transition: 'transform 0.15s', marginRight: 8, flexShrink: 0 }}>
                    <path d="M6 4l4 4-4 4z" />
                  </svg>
                  <span className="shared-curriculum-module-week">W{mod.week}</span>
                  <span className="shared-curriculum-module-title">{mod.title}</span>
                  <span className="shared-curriculum-module-count">{paperCount} papers</span>
                </div>

                {isExpanded && (
                  <div className="shared-curriculum-module-body">
                    {mod.description && (
                      <p className="shared-curriculum-module-desc">{mod.description}</p>
                    )}
                    {mod.topics.map((topic) => (
                      <div key={topic.id} className="shared-curriculum-topic">
                        <h4 className="shared-curriculum-topic-title">{topic.title}</h4>
                        <div className="shared-curriculum-papers">
                          {topic.papers.map((paper) => (
                            <div key={paper.id} className="shared-curriculum-paper">
                              <div className="shared-curriculum-paper-title">
                                {paper.title}
                                <span className={`curriculum-badge ${paper.category}`}>{paper.category}</span>
                              </div>
                              <div className="shared-curriculum-paper-meta">
                                {paper.authors?.slice(0, 3).join(', ')}{paper.authors?.length > 3 ? ' et al.' : ''}
                                {paper.year ? ` (${paper.year})` : ''}
                                {paper.venue ? ` — ${paper.venue}` : ''}
                              </div>
                              {paper.context && (
                                <div className="shared-curriculum-paper-context">{paper.context}</div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Reference courses */}
        {course.reference_courses && course.reference_courses.length > 0 && (
          <div className="shared-curriculum-refs">
            <h3>Reference Courses</h3>
            {course.reference_courses.map((ref, i) => (
              <div key={i} className="shared-curriculum-ref">
                <strong>{ref.university}</strong> {ref.course_code}: {ref.course_name}
                {ref.url && (
                  <a href={ref.url} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 8, fontSize: '0.8em' }}>
                    Link
                  </a>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
