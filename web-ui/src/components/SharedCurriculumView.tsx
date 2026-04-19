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
      <div className="shared-cur">
        <div className="shared-cur-loading">
          <div className="shared-cur-loading-spinner" />
          Loading curriculum...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="shared-cur">
        <div className="shared-cur-error-page">
          <div className="shared-cur-error-icon">
            {error === 'expired' ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="48" height="48">
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 6 12 12 16 14" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="48" height="48">
                <circle cx="12" cy="12" r="10" />
                <line x1="15" y1="9" x2="9" y2="15" />
                <line x1="9" y1="9" x2="15" y2="15" />
              </svg>
            )}
          </div>
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
              <h2>Something went wrong</h2>
              <p>Failed to load this shared curriculum. Please try again later.</p>
            </>
          )}
          <button className="shared-cur-home-btn" onClick={() => navigate('/')}>
            Go to Home
          </button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const { summary, course } = data;
  const isAuthenticated = !!localStorage.getItem('access_token');

  return (
    <div className="shared-cur">
      {/* ── Header ── */}
      <header className="shared-cur-header">
        <div className="shared-cur-header-inner">
          <div className="shared-cur-brand" onClick={() => navigate('/')} style={{ cursor: 'pointer' }}>
            <picture>
              <source srcSet="/Jiphyeonjeon_llama.webp" type="image/webp" />
              <img
                src="/Jiphyeonjeon_llama.png"
                alt="Jiphyeonjeon"
                className="shared-cur-logo"
                width={128}
                height={128}
                loading="eager"
                fetchPriority="high"
                onError={(e) => { e.currentTarget.style.display = 'none'; }}
              />
            </picture>
            <span className="shared-cur-brand-name">Jiphyeonjeon</span>
          </div>
          <span className="shared-cur-badge">Shared Curriculum</span>
        </div>
      </header>

      {/* ── Hero section ── */}
      <div className="shared-cur-hero">
        <div className="shared-cur-hero-inner">
          <div className="shared-cur-hero-top">
            <span className={`curriculum-badge ${summary.difficulty}`}>{summary.difficulty}</span>
            {summary.university && <span className="shared-cur-hero-uni">{summary.university}</span>}
          </div>
          <h1 className="shared-cur-title">{summary.name}</h1>
          {summary.description && (
            <p className="shared-cur-desc">{summary.description}</p>
          )}
          <div className="shared-cur-stats">
            <div className="shared-cur-stat">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
                <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
              </svg>
              <span>{summary.total_modules} modules</span>
            </div>
            <div className="shared-cur-stat">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
              <span>{totalPapers} papers</span>
            </div>
            {summary.instructor && (
              <div className="shared-cur-stat">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                  <circle cx="12" cy="7" r="4" />
                </svg>
                <span>{summary.instructor}</span>
              </div>
            )}
          </div>
          {summary.prerequisites && summary.prerequisites.length > 0 && (
            <div className="shared-cur-prereqs">
              <span className="shared-cur-prereqs-label">Prerequisites</span>
              <div className="shared-cur-prereqs-list">
                {summary.prerequisites.map((p, i) => (
                  <span key={i} className="shared-cur-prereq-chip">{p}</span>
                ))}
              </div>
            </div>
          )}
          {isAuthenticated && (
            <button className="shared-cur-cta" onClick={() => navigate('/mypage', { state: { activeTab: 'curriculum' } })}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
                <polyline points="10 17 15 12 10 7" />
                <line x1="15" y1="12" x2="3" y2="12" />
              </svg>
              Open in Curriculum
            </button>
          )}
        </div>
      </div>

      {/* ── Modules ── */}
      <div className="shared-cur-body">
        <div className="shared-cur-body-inner">
          <h2 className="shared-cur-section-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
              <rect x="3" y="3" width="7" height="7" />
              <rect x="14" y="3" width="7" height="7" />
              <rect x="14" y="14" width="7" height="7" />
              <rect x="3" y="14" width="7" height="7" />
            </svg>
            Modules
          </h2>

          <div className="shared-cur-modules">
            {course.modules.map((mod, idx) => {
              const isExpanded = expandedModuleId === mod.id;
              const paperCount = mod.topics.reduce((sum, t) => sum + t.papers.length, 0);
              return (
                <div key={mod.id} className={`shared-cur-module ${isExpanded ? 'expanded' : ''}`}>
                  <div
                    className="shared-cur-module-header"
                    onClick={() => setExpandedModuleId(isExpanded ? null : mod.id)}
                  >
                    <div className="shared-cur-module-left">
                      <span className="shared-cur-module-num">{idx + 1}</span>
                      <div className="shared-cur-module-info">
                        <div className="shared-cur-module-name">{mod.title}</div>
                        <div className="shared-cur-module-sub">
                          Week {mod.week} &middot; {paperCount} paper{paperCount !== 1 ? 's' : ''} &middot; {mod.topics.length} topic{mod.topics.length !== 1 ? 's' : ''}
                        </div>
                      </div>
                    </div>
                    <svg
                      className={`shared-cur-module-chevron ${isExpanded ? 'open' : ''}`}
                      viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"
                    >
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </div>

                  {isExpanded && (
                    <div className="shared-cur-module-body">
                      {mod.description && (
                        <p className="shared-cur-module-desc">{mod.description}</p>
                      )}
                      {mod.topics.map((topic) => (
                        <div key={topic.id} className="shared-cur-topic">
                          <div className="shared-cur-topic-header">
                            <span className="shared-cur-topic-dot" />
                            <h4 className="shared-cur-topic-name">{topic.title}</h4>
                            <span className="shared-cur-topic-count">{topic.papers.length}</span>
                          </div>
                          <div className="shared-cur-papers">
                            {topic.papers.map((paper) => (
                              <div key={paper.id} className="shared-cur-paper">
                                <div className="shared-cur-paper-row">
                                  <span className={`shared-cur-cat-dot cat-${paper.category}`} title={paper.category} />
                                  <span className="shared-cur-paper-title">{paper.title}</span>
                                </div>
                                <div className="shared-cur-paper-meta">
                                  {paper.authors?.slice(0, 3).join(', ')}{paper.authors?.length > 3 ? ' et al.' : ''}
                                  {paper.year ? ` (${paper.year})` : ''}
                                  {paper.venue && <span className="shared-cur-paper-venue">{paper.venue}</span>}
                                </div>
                                {paper.context && (
                                  <div className="shared-cur-paper-context">{paper.context}</div>
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
            <div className="shared-cur-refs">
              <h3 className="shared-cur-section-title" style={{ fontSize: '0.85rem', marginTop: 32 }}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                </svg>
                Reference Courses
              </h3>
              <div className="shared-cur-refs-list">
                {course.reference_courses.map((ref, i) => (
                  <div key={i} className="shared-cur-ref-item">
                    <span className="shared-cur-ref-uni">{ref.university}</span>
                    <span className="shared-cur-ref-name">{ref.course_code}: {ref.course_name}</span>
                    {ref.url && (
                      <a href={ref.url} target="_blank" rel="noopener noreferrer" className="shared-cur-ref-link">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                          <polyline points="15 3 21 3 21 9" />
                          <line x1="10" y1="14" x2="21" y2="3" />
                        </svg>
                      </a>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Footer ── */}
      <footer className="shared-cur-footer">
        <span>Shared via Jiphyeonjeon</span>
      </footer>
    </div>
  );
}
