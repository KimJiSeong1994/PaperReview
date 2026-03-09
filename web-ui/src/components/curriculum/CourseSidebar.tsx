import { useState, useEffect, useRef } from 'react';
import type { CurriculumSummary } from './types';
import type { CurriculumGenerateProgress } from '../../api/client';

interface CourseSidebarProps {
  presetCourses: CurriculumSummary[];
  myCourses: CurriculumSummary[];
  loadingCourses: boolean;
  selectedCourseId: string | null;
  selectedModuleId: string | null;
  readPapers: Set<string>;
  progressStats: { read: number; total: number; percent: number };
  courseDetail: {
    modules: {
      id: string;
      week: number;
      title: string;
      topics: { papers: { id: string }[] }[];
    }[];
  } | null;
  generating: boolean;
  forking: boolean;
  generateProgress: CurriculumGenerateProgress | null;
  onSelectCourse: (id: string) => void;
  onSelectModule: (id: string) => void;
  onGenerate: (topic: string, difficulty: string, numModules: number, options?: { learning_goals?: string; paper_preference?: string }) => Promise<any>;
  onFork: (courseId: string) => Promise<any>;
  onDelete: (courseId: string) => Promise<any>;
  getModuleProgress: (moduleId: string) => { read: number; total: number };
}

/* ── Icons ── */

function ChevronIcon() {
  return (
    <svg className="cur-tree-chevron" viewBox="0 0 16 16" fill="currentColor" width="10" height="10">
      <path d="M6 4l4 4-4 4z" />
    </svg>
  );
}

function FolderIcon({ open }: { open: boolean }) {
  return (
    <svg className="cur-tree-folder-icon" viewBox="0 0 24 24" width="14" height="14">
      {open ? (
        <>
          <path d="M5 19a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v1" fill="rgba(99,102,241,0.15)" stroke="#818cf8" strokeWidth="1.5" />
          <path d="M5 19h14a2 2 0 0 0 2-2l-3-7H4l-1 7a2 2 0 0 0 2 2z" fill="rgba(99,102,241,0.25)" stroke="#818cf8" strokeWidth="1.5" />
        </>
      ) : (
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" fill="rgba(156,163,175,0.1)" stroke="#6b7280" strokeWidth="1.5" />
      )}
    </svg>
  );
}

function CourseFileIcon() {
  return (
    <svg className="cur-tree-file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="13" height="13">
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
      <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
    </svg>
  );
}

function ModuleFileIcon() {
  return (
    <svg className="cur-tree-file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="13" height="13">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}

function ForkIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
      <circle cx="12" cy="18" r="3" />
      <circle cx="6" cy="6" r="3" />
      <circle cx="18" cy="6" r="3" />
      <path d="M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9" />
      <line x1="12" y1="12" x2="12" y2="15" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="11" height="11">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
    </svg>
  );
}

/* ── Main Component ── */

export default function CourseSidebar({
  presetCourses,
  myCourses,
  loadingCourses,
  selectedCourseId,
  selectedModuleId,
  progressStats,
  courseDetail,
  generating,
  forking,
  generateProgress,
  onSelectCourse,
  onSelectModule,
  onGenerate,
  onFork,
  onDelete,
  getModuleProgress,
}: CourseSidebarProps) {
  const [featuredOpen, setFeaturedOpen] = useState(true);
  const [myOpen, setMyOpen] = useState(true);
  const [showGenerateModal, setShowGenerateModal] = useState(false);
  const [genTopic, setGenTopic] = useState('');
  const [genDifficulty, setGenDifficulty] = useState('intermediate');
  const [genModules, setGenModules] = useState(5);
  const [genGoals, setGenGoals] = useState('');
  const [genPaperPref, setGenPaperPref] = useState('balanced');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const wasGenerating = useRef(false);

  // Auto-close modal on successful generation completion
  useEffect(() => {
    if (generating) {
      wasGenerating.current = true;
    } else if (wasGenerating.current && !generateProgress) {
      wasGenerating.current = false;
      setShowGenerateModal(false);
      setGenTopic('');
      setGenGoals('');
      setShowAdvanced(false);
    } else if (wasGenerating.current && generateProgress?.step === -1) {
      wasGenerating.current = false;
    }
  }, [generating, generateProgress]);

  const handleSubmitGenerate = () => {
    if (!genTopic.trim()) return;
    const options: { learning_goals?: string; paper_preference?: string } = {};
    if (genGoals.trim()) options.learning_goals = genGoals.trim();
    if (genPaperPref !== 'balanced') options.paper_preference = genPaperPref;
    onGenerate(genTopic.trim(), genDifficulty, genModules, options);
  };

  /* ── Course tree item ── */
  const renderCourseItem = (course: CurriculumSummary, showFork: boolean) => {
    const isSelected = selectedCourseId === course.id;
    return (
      <div key={course.id}>
        <div
          className={`cur-tree-file ${isSelected ? 'active' : ''}`}
          onClick={() => onSelectCourse(course.id)}
        >
          <span className="cur-tree-guide-line" />
          <CourseFileIcon />
          <div className="cur-tree-file-info">
            <div className="cur-tree-file-name">{course.name}</div>
            <div className="cur-tree-file-meta">
              <span className={`curriculum-badge ${course.difficulty}`}>
                {course.difficulty}
              </span>
              <span>{course.total_modules} modules</span>
              <span>{course.total_papers} papers</span>
            </div>
          </div>
          <div className="cur-tree-file-actions">
            {showFork && (
              <button
                className="cur-tree-action-btn cur-fork-btn"
                title="Fork to my curricula"
                onClick={(e) => { e.stopPropagation(); onFork(course.id); }}
                disabled={forking}
              >
                <ForkIcon />
              </button>
            )}
            {!course.is_preset && (
              <button
                className="cur-tree-action-btn cur-delete-btn"
                title="Delete"
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm('Delete this curriculum?')) onDelete(course.id);
                }}
              >
                <TrashIcon />
              </button>
            )}
          </div>
        </div>

        {/* Module sub-tree when course is selected */}
        {isSelected && courseDetail && courseDetail.modules.length > 0 && (
          <div className="cur-tree-children cur-module-tree">
            {courseDetail.modules.map((mod) => {
              const mp = getModuleProgress(mod.id);
              return (
                <div
                  key={mod.id}
                  className={`cur-tree-file cur-module-item ${selectedModuleId === mod.id ? 'active' : ''}`}
                  onClick={() => onSelectModule(mod.id)}
                >
                  <span className="cur-tree-guide-line" />
                  <ModuleFileIcon />
                  <div className="cur-tree-file-info">
                    <div className="cur-tree-file-name">
                      <span className="cur-module-week">W{mod.week}</span>
                      {mod.title}
                    </div>
                  </div>
                  <span className="cur-module-progress-badge">
                    {mp.read}/{mp.total}
                  </span>
                </div>
              );
            })}
            {/* Progress bar */}
            {progressStats.total > 0 && (
              <div className="cur-tree-progress-row">
                <div className="curriculum-progress-bar">
                  <div
                    className="curriculum-progress-fill"
                    style={{ width: `${progressStats.percent}%` }}
                  />
                </div>
                <span className="cur-tree-progress-text">
                  {progressStats.read}/{progressStats.total} ({progressStats.percent}%)
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  // Compute overall generate progress percent
  const overallPercent = generateProgress
    ? Math.round(((generateProgress.step - 1) / 4) * 100 + (generateProgress.progress / 4))
    : 0;

  return (
    <div className="curriculum-sidebar">
      {/* ── Featured Courses folder ── */}
      <div className={`cur-tree-folder ${featuredOpen ? 'open' : ''}`}>
        <div className={`cur-tree-folder-row ${featuredOpen ? 'open' : ''}`} onClick={() => setFeaturedOpen(!featuredOpen)}>
          <ChevronIcon />
          <FolderIcon open={featuredOpen} />
          <span className="cur-tree-folder-name">Featured Courses</span>
          <span className="cur-tree-folder-badge">{presetCourses.length}</span>
        </div>
        {featuredOpen && (
          <div className="cur-tree-children">
            {loadingCourses ? (
              <div className="curriculum-loading">Loading...</div>
            ) : presetCourses.length === 0 ? (
              <div className="cur-tree-empty">No featured courses</div>
            ) : (
              presetCourses.map((course) => renderCourseItem(course, true))
            )}
          </div>
        )}
      </div>

      {/* ── My Curricula folder ── */}
      <div className={`cur-tree-folder ${myOpen ? 'open' : ''}`}>
        <div className={`cur-tree-folder-row ${myOpen ? 'open' : ''}`} onClick={() => setMyOpen(!myOpen)}>
          <ChevronIcon />
          <FolderIcon open={myOpen} />
          <span className="cur-tree-folder-name">My Curricula</span>
          <span className="cur-tree-folder-badge">{myCourses.length}</span>
        </div>
        {myOpen && (
          <div className="cur-tree-children">
            {loadingCourses ? null : myCourses.length === 0 ? (
              <div className="cur-tree-empty">
                Fork a course or generate a custom one
              </div>
            ) : (
              myCourses.map((course) => renderCourseItem(course, false))
            )}
          </div>
        )}
      </div>

      {/* ── Generate button ── */}
      <div className="curriculum-generate-section">
        <button
          className="curriculum-generate-btn"
          onClick={() => setShowGenerateModal(true)}
          disabled={generating}
        >
          {generating ? 'Generating...' : '+ Custom Curriculum'}
        </button>
      </div>

      {/* ── Generate modal ── */}
      {showGenerateModal && (
        <div className="curriculum-generate-modal-overlay" onClick={() => !generating && setShowGenerateModal(false)}>
          <div className="curriculum-generate-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Generate Custom Curriculum</h3>

            {(generating || (generateProgress && generateProgress.step === -1)) && generateProgress ? (
              <div className="curriculum-generate-progress-section">
                {generateProgress.step === -1 ? (
                  <>
                    <div className="curriculum-generate-error-msg">
                      {generateProgress.message}
                    </div>
                    <div className="curriculum-generate-modal-actions" style={{ marginTop: 12 }}>
                      <button className="curriculum-generate-cancel-btn" onClick={() => setShowGenerateModal(false)}>
                        Close
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="curriculum-generate-step-label">
                      Step {generateProgress.step}/4: {
                        generateProgress.step_name === 'structure' ? 'Designing structure' :
                        generateProgress.step_name === 'search' ? 'Searching papers' :
                        generateProgress.step_name === 'assembly' ? 'Assembling curriculum' :
                        generateProgress.step_name === 'review' ? 'Quality review & refinement' :
                        'Preparing'
                      }
                    </div>
                    <div className="curriculum-progress-bar" style={{ marginTop: 8 }}>
                      <div
                        className="curriculum-progress-fill"
                        style={{ width: `${overallPercent}%`, transition: 'width 0.5s ease' }}
                      />
                    </div>
                    <div className="curriculum-generate-progress-msg">
                      {generateProgress.message}
                    </div>
                    {generateProgress.detail?.modules && (
                      <div className="curriculum-generate-progress-detail">
                        {generateProgress.detail.modules.map((m: string, i: number) => (
                          <div key={i} className="curriculum-generate-progress-module">{m}</div>
                        ))}
                      </div>
                    )}
                    {generateProgress.detail?.reference_courses && (
                      <div className="curriculum-generate-progress-refs">
                        <div className="curriculum-generate-progress-refs-label">Referenced courses:</div>
                        {generateProgress.detail.reference_courses.map((c: any, i: number) => (
                          <div key={i} className="curriculum-generate-progress-ref">
                            {c.university} {c.course_code}: {c.course_name}
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            ) : (
              <>
                <label>Topic</label>
                <input
                  type="text"
                  placeholder="e.g., Reinforcement Learning, Graph Neural Networks"
                  value={genTopic}
                  onChange={(e) => setGenTopic(e.target.value)}
                  autoFocus
                />
                <label>Difficulty</label>
                <select value={genDifficulty} onChange={(e) => setGenDifficulty(e.target.value)}>
                  <option value="beginner">Beginner</option>
                  <option value="intermediate">Intermediate</option>
                  <option value="advanced">Advanced</option>
                </select>
                <label>Number of Modules</label>
                <input
                  type="number"
                  min={2}
                  max={10}
                  value={genModules}
                  onChange={(e) => setGenModules(Number(e.target.value))}
                />

                <div
                  className="curriculum-generate-advanced-toggle"
                  onClick={() => setShowAdvanced(!showAdvanced)}
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12"
                    style={{ transform: showAdvanced ? 'rotate(90deg)' : 'rotate(0)', transition: 'transform 0.2s' }}>
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                  Advanced Options
                </div>
                {showAdvanced && (
                  <div className="curriculum-generate-advanced-body">
                    <label>Learning Goals (optional)</label>
                    <textarea
                      placeholder="e.g., Understand GNN architectures and implement them in PyTorch"
                      value={genGoals}
                      onChange={(e) => setGenGoals(e.target.value)}
                      rows={2}
                    />
                    <label>Paper Preference</label>
                    <select value={genPaperPref} onChange={(e) => setGenPaperPref(e.target.value)}>
                      <option value="balanced">Balanced (default)</option>
                      <option value="survey_heavy">Survey / Tutorial focused</option>
                      <option value="cutting_edge">Cutting-edge research (2022+)</option>
                    </select>
                  </div>
                )}

                <div className="curriculum-generate-modal-actions">
                  <button className="curriculum-generate-cancel-btn" onClick={() => setShowGenerateModal(false)}>
                    Cancel
                  </button>
                  <button
                    className="curriculum-generate-submit-btn"
                    onClick={handleSubmitGenerate}
                    disabled={!genTopic.trim() || generating}
                  >
                    Generate
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
