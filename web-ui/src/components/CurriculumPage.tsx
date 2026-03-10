import { useNavigate } from 'react-router-dom';
import { useCurriculum } from '../hooks/useCurriculum';
import CourseSidebar from './curriculum/CourseSidebar';
import ModuleView from './curriculum/ModuleView';
import CurriculumDetailPanel from './curriculum/CurriculumDetailPanel';
import './CurriculumPage.css';

export default function CurriculumPage() {
  const navigate = useNavigate();
  const {
    presetCourses,
    myCourses,
    loadingCourses,
    courseDetail,
    loadingCourse,
    selectedCourseId,
    selectedModuleId,
    selectedPaperId,
    selectedModule,
    selectedPaper,
    readPapers,
    progressStats,
    generating,
    forking,
    generateProgress,
    bookmarkLoading,
    bookmarkSuccess,
    handleSelectCourse,
    setSelectedModuleId,
    setSelectedPaperId,
    handleToggleRead,
    handleSearchPaper,
    handleGenerate,
    handleFork,
    handleDelete,
    handleShare,
    handleRevokeShare,
    handleBookmarkPaper,
    getModuleProgress,
  } = useCurriculum();

  return (
    <div className="curriculum-page">
      <div className="curriculum-header">
        <div className="curriculum-header-left">
          <button className="curriculum-back-btn" onClick={() => navigate('/')}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14" style={{ marginRight: 4, verticalAlign: 'middle' }}>
              <polyline points="15 18 9 12 15 6" />
            </svg>
            Back
          </button>
          <span className="curriculum-header-title">Learning Curriculum</span>
        </div>
      </div>

      <div className="curriculum-content">
        <CourseSidebar
          presetCourses={presetCourses}
          myCourses={myCourses}
          loadingCourses={loadingCourses}
          selectedCourseId={selectedCourseId}
          selectedModuleId={selectedModuleId}
          readPapers={readPapers}
          progressStats={progressStats}
          courseDetail={courseDetail}
          generating={generating}
          forking={forking}
          generateProgress={generateProgress}
          onSelectCourse={handleSelectCourse}
          onSelectModule={setSelectedModuleId}
          onGenerate={handleGenerate}
          onFork={handleFork}
          onDelete={handleDelete}
          onShare={handleShare}
          onRevokeShare={handleRevokeShare}
          getModuleProgress={getModuleProgress}
        />

        {loadingCourse ? (
          <div className="curriculum-main">
            <div className="curriculum-loading">Loading course...</div>
          </div>
        ) : (
          <ModuleView
            module={selectedModule}
            readPapers={readPapers}
            selectedPaperId={selectedPaperId}
            onSelectPaper={setSelectedPaperId}
            onToggleRead={handleToggleRead}
            getModuleProgress={getModuleProgress}
          />
        )}

        <CurriculumDetailPanel
          paper={selectedPaper}
          courseDetail={courseDetail}
          onSearchPaper={handleSearchPaper}
          onBookmarkPaper={handleBookmarkPaper}
          bookmarkLoading={bookmarkLoading}
          bookmarkSuccess={bookmarkSuccess}
        />
      </div>
    </div>
  );
}
