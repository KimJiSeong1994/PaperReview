import { useState } from 'react';
import type { CurriculumSummary } from './types';

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
  onSelectCourse: (id: string) => void;
  onSelectModule: (id: string) => void;
  onGenerate: (topic: string, difficulty: string, numModules: number) => Promise<any>;
  onFork: (courseId: string) => Promise<any>;
  onDelete: (courseId: string) => Promise<any>;
  getModuleProgress: (moduleId: string) => { read: number; total: number };
}

function ForkIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
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
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
    </svg>
  );
}

function ForkedBadge({ forkedFrom, presetCourses }: { forkedFrom: string; presetCourses: CurriculumSummary[] }) {
  const source = presetCourses.find((c) => c.id === forkedFrom);
  const label = source ? source.name.split(':')[0] : forkedFrom;
  return (
    <span className="curriculum-forked-badge">
      <ForkIcon /> {label}
    </span>
  );
}

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
  onSelectCourse,
  onSelectModule,
  onGenerate,
  onFork,
  onDelete,
  getModuleProgress,
}: CourseSidebarProps) {
  const [showGenerateModal, setShowGenerateModal] = useState(false);
  const [genTopic, setGenTopic] = useState('');
  const [genDifficulty, setGenDifficulty] = useState('intermediate');
  const [genModules, setGenModules] = useState(5);

  const handleSubmitGenerate = async () => {
    if (!genTopic.trim()) return;
    try {
      await onGenerate(genTopic.trim(), genDifficulty, genModules);
      setShowGenerateModal(false);
      setGenTopic('');
    } catch {
      // Error handled in hook
    }
  };

  const renderCourseCard = (course: CurriculumSummary, showFork: boolean) => {
    const isSelected = selectedCourseId === course.id;
    return (
      <div
        key={course.id}
        className={`curriculum-course-card ${isSelected ? 'active' : ''}`}
        onClick={() => onSelectCourse(course.id)}
      >
        <div className="curriculum-course-card-header">
          <div className="curriculum-course-name">{course.name}</div>
          <div className="curriculum-course-card-actions">
            {showFork && (
              <button
                className="curriculum-fork-btn"
                title="내 커리큘럼으로 복사"
                onClick={(e) => {
                  e.stopPropagation();
                  onFork(course.id);
                }}
                disabled={forking}
              >
                <ForkIcon />
                <span>Fork</span>
              </button>
            )}
            {!course.is_preset && (
              <button
                className="curriculum-delete-btn"
                title="삭제"
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm('이 커리큘럼을 삭제하시겠습니까?')) {
                    onDelete(course.id);
                  }
                }}
              >
                <TrashIcon />
              </button>
            )}
          </div>
        </div>
        <div className="curriculum-course-meta">
          <span>{course.university}</span>
          <span className={`curriculum-badge ${course.difficulty}`}>
            {course.difficulty}
          </span>
        </div>
        <div className="curriculum-course-meta">
          <span>{course.total_modules} modules</span>
          <span>{course.total_papers} papers</span>
        </div>
        {course.forked_from && (
          <ForkedBadge forkedFrom={course.forked_from} presetCourses={presetCourses} />
        )}
        {isSelected && progressStats.total > 0 && (
          <>
            <div className="curriculum-progress-bar">
              <div
                className="curriculum-progress-fill"
                style={{ width: `${progressStats.percent}%` }}
              />
            </div>
            <div className="curriculum-progress-text">
              {progressStats.read} / {progressStats.total} papers read ({progressStats.percent}%)
            </div>
          </>
        )}
      </div>
    );
  };

  return (
    <div className="curriculum-sidebar">
      {/* Featured Courses (presets) */}
      <div className="curriculum-sidebar-header">
        Featured Courses
      </div>

      <div className="curriculum-course-list">
        {loadingCourses ? (
          <div className="curriculum-loading">Loading courses...</div>
        ) : presetCourses.length === 0 ? (
          <div className="curriculum-empty-small">No featured courses</div>
        ) : (
          presetCourses.map((course) => renderCourseCard(course, true))
        )}
      </div>

      {/* My Curricula (forked + custom) */}
      <div className="curriculum-sidebar-header curriculum-my-section">
        My Curricula
        {myCourses.length > 0 && (
          <span className="curriculum-my-count">{myCourses.length}</span>
        )}
      </div>

      <div className="curriculum-course-list curriculum-my-list">
        {loadingCourses ? null : myCourses.length === 0 ? (
          <div className="curriculum-empty-small">
            Fork a featured course or generate a custom one to get started
          </div>
        ) : (
          myCourses.map((course) => renderCourseCard(course, false))
        )}
      </div>

      {/* Module tree for selected course */}
      {courseDetail && courseDetail.modules.length > 0 && (
        <div className="curriculum-module-tree">
          <div className="curriculum-module-tree-header">Modules</div>
          {courseDetail.modules.map((mod) => {
            const mp = getModuleProgress(mod.id);
            return (
              <div
                key={mod.id}
                className={`curriculum-module-item ${selectedModuleId === mod.id ? 'active' : ''}`}
                onClick={() => onSelectModule(mod.id)}
              >
                <span className="curriculum-module-week">Week {mod.week}</span>
                <span className="curriculum-module-title">{mod.title}</span>
                <span className="curriculum-module-progress-mini">
                  {mp.read}/{mp.total}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Generate custom curriculum */}
      <div className="curriculum-generate-section">
        <button
          className="curriculum-generate-btn"
          onClick={() => setShowGenerateModal(true)}
          disabled={generating}
        >
          {generating ? 'Generating...' : '+ Custom Curriculum'}
        </button>
      </div>

      {/* Generate modal */}
      {showGenerateModal && (
        <div className="curriculum-generate-modal-overlay" onClick={() => setShowGenerateModal(false)}>
          <div className="curriculum-generate-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Generate Custom Curriculum</h3>
            <label>Topic</label>
            <input
              type="text"
              placeholder="e.g., Reinforcement Learning"
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
            <div className="curriculum-generate-modal-actions">
              <button
                className="curriculum-generate-cancel-btn"
                onClick={() => setShowGenerateModal(false)}
              >
                Cancel
              </button>
              <button
                className="curriculum-generate-submit-btn"
                onClick={handleSubmitGenerate}
                disabled={!genTopic.trim() || generating}
              >
                {generating ? 'Generating...' : 'Generate'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
