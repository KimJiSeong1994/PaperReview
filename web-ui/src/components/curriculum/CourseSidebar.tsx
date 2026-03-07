import { useState } from 'react';
import type { CurriculumSummary } from './types';

interface CourseSidebarProps {
  courses: CurriculumSummary[];
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
  onSelectCourse: (id: string) => void;
  onSelectModule: (id: string) => void;
  onGenerate: (topic: string, difficulty: string, numModules: number) => Promise<any>;
  getModuleProgress: (moduleId: string) => { read: number; total: number };
}

export default function CourseSidebar({
  courses,
  loadingCourses,
  selectedCourseId,
  selectedModuleId,
  progressStats,
  courseDetail,
  generating,
  onSelectCourse,
  onSelectModule,
  onGenerate,
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

  return (
    <div className="curriculum-sidebar">
      <div className="curriculum-sidebar-header">Courses</div>

      <div className="curriculum-course-list">
        {loadingCourses ? (
          <div className="curriculum-loading">Loading courses...</div>
        ) : courses.length === 0 ? (
          <div className="curriculum-empty">No courses available</div>
        ) : (
          courses.map((course) => (
            <div
              key={course.id}
              className={`curriculum-course-card ${selectedCourseId === course.id ? 'active' : ''}`}
              onClick={() => onSelectCourse(course.id)}
            >
              <div className="curriculum-course-name">{course.name}</div>
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
              {selectedCourseId === course.id && progressStats.total > 0 && (
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
          ))
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
