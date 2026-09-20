import { useCallback, useEffect, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useCurriculum } from '../hooks/useCurriculum';
import CourseSidebar from './curriculum/CourseSidebar';
import ModuleView from './curriculum/ModuleView';
import CurriculumDetailPanel from './curriculum/CurriculumDetailPanel';
import { openPaperViewer, viewerHrefForPaper } from '../utils/blogPaperReference';
import { paramsWithSelection } from './curriculum/params';
import './CurriculumPage.css';

export default function CurriculumPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const cur = useCurriculum();
  const {
    courseDetail, selectedCourseId, selectedModuleId, selectedPaperId,
    handleSelectCourse, setSelectedModuleId, setSelectedPaperId,
  } = cur;

  // The URL seeds the selection once, on mount; after that the selection writes
  // to the URL. Latched like MyPage's restoredFromUrl: this effect must never
  // react to its own writes.
  const seededCourse = useRef(false);
  useEffect(() => {
    if (seededCourse.current) return;
    seededCourse.current = true;
    const course = searchParams.get('course');
    if (course) handleSelectCourse(course);
  }, [searchParams, handleSelectCourse]);

  // Module and paper can only be applied once the course detail is here — and
  // handleSelectCourse auto-selects the first module when it lands, so the URL's
  // choice has to be applied after that, once.
  const seededDetail = useRef<string | null>(null);
  useEffect(() => {
    if (!courseDetail || seededDetail.current === courseDetail.id) return;
    seededDetail.current = courseDetail.id;
    if (courseDetail.id !== searchParams.get('course')) return;
    const module = searchParams.get('module');
    const paper = searchParams.get('paper');
    if (module) setSelectedModuleId(module);
    if (paper) setSelectedPaperId(paper);
  }, [courseDetail, searchParams, setSelectedModuleId, setSelectedPaperId]);

  const writeSelection = useCallback((selection: { course: string | null; module: string | null; paper: string | null }) => {
    setSearchParams((prev) => paramsWithSelection(prev, selection), { replace: true });
  }, [setSearchParams]);

  const onSelectCourse = useCallback((courseId: string) => {
    // The course row is also the handle for its module sub-tree, so it is
    // clicked while already open; the hook no-ops then and so must the URL,
    // or a reload lands on the first module with nothing selected.
    if (courseId === selectedCourseId && courseDetail) return;
    handleSelectCourse(courseId);
    writeSelection({ course: courseId, module: null, paper: null });
  }, [handleSelectCourse, writeSelection, selectedCourseId, courseDetail]);

  const onSelectModule = useCallback((moduleId: string) => {
    setSelectedModuleId(moduleId);
    // The hook keeps the paper across a module change; the URL does not, and a
    // paper from another module has no business staying open under this one.
    setSelectedPaperId(null);
    writeSelection({ course: selectedCourseId, module: moduleId, paper: null });
  }, [setSelectedModuleId, setSelectedPaperId, writeSelection, selectedCourseId]);

  const onSelectPaper = useCallback((paperId: string) => {
    setSelectedPaperId(paperId);
    writeSelection({ course: selectedCourseId, module: selectedModuleId, paper: paperId });
  }, [setSelectedPaperId, writeSelection, selectedCourseId, selectedModuleId]);

  return (
    <div className="curriculum-page">
      <div className="curriculum-header">
        <div className="curriculum-header-left">
          <Link className="curriculum-back-btn" to="/mypage">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14" style={{ marginRight: 4, verticalAlign: 'middle' }} aria-hidden="true">
              <polyline points="15 18 9 12 15 6" />
            </svg>
            마이페이지
          </Link>
          <h1 className="curriculum-header-title">학습 커리큘럼</h1>
        </div>
      </div>

      <div className="curriculum-content">
        <CourseSidebar
          presetCourses={cur.presetCourses}
          myCourses={cur.myCourses}
          loadingCourses={cur.loadingCourses}
          selectedCourseId={selectedCourseId}
          selectedModuleId={selectedModuleId}
          readPapers={cur.readPapers}
          progressStats={cur.progressStats}
          courseDetail={courseDetail}
          generating={cur.generating}
          forking={cur.forking}
          generateProgress={cur.generateProgress}
          onSelectCourse={onSelectCourse}
          onSelectModule={onSelectModule}
          onGenerate={cur.handleGenerate}
          onFork={cur.handleFork}
          onDelete={cur.handleDelete}
          onShare={cur.handleShare}
          onRevokeShare={cur.handleRevokeShare}
          shareMessage={cur.shareMessage}
          getModuleProgress={cur.getModuleProgress}
        />

        {cur.loadingCourse ? (
          <div className="curriculum-main">
            <div className="curriculum-loading">코스 불러오는 중...</div>
          </div>
        ) : (
          <ModuleView
            module={cur.selectedModule}
            readPapers={cur.readPapers}
            selectedPaperId={selectedPaperId}
            onSelectPaper={onSelectPaper}
            onToggleRead={cur.handleToggleRead}
            getModuleProgress={cur.getModuleProgress}
            onDeepReviewModule={cur.handleDeepReviewModule}
            reviewStatus={cur.reviewStatus}
            reviewingModuleId={cur.reviewingModuleId}
          />
        )}

        <CurriculumDetailPanel
          paper={cur.selectedPaper}
          courseDetail={courseDetail}
          onSearchPaper={cur.handleSearchPaper}
          onViewPaper={(paper) => openPaperViewer(viewerHrefForPaper(paper, 'curriculum'))}
          onDeepReview={cur.handleDeepReviewPaper}
          reviewStatus={cur.reviewStatus}
          reviewProgress={cur.reviewProgress}
          reviewingPaperIds={cur.reviewingPaperIds}
          reviewingModuleId={cur.reviewingModuleId}
        />
      </div>
    </div>
  );
}
