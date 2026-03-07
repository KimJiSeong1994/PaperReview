import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchCurricula,
  fetchCurriculumDetail,
  fetchCurriculumProgress,
  updateCurriculumProgress,
  generateCurriculum,
} from '../api/client';
import type {
  CurriculumSummary,
  CurriculumCourse,
  CurriculumPaper,
} from '../components/curriculum/types';

const LS_PREFIX = 'curriculum_progress_';

export function useCurriculum() {
  const navigate = useNavigate();

  // Course list
  const [courses, setCourses] = useState<CurriculumSummary[]>([]);
  const [loadingCourses, setLoadingCourses] = useState(true);

  // Selected course detail
  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(null);
  const [courseDetail, setCourseDetail] = useState<CurriculumCourse | null>(null);
  const [loadingCourse, setLoadingCourse] = useState(false);

  // Navigation within course
  const [selectedModuleId, setSelectedModuleId] = useState<string | null>(null);
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null);

  // Progress
  const [readPapers, setReadPapers] = useState<Set<string>>(new Set());

  // Generate
  const [generating, setGenerating] = useState(false);

  const isAuthenticated = !!localStorage.getItem('access_token');

  // Load course list on mount
  useEffect(() => {
    setLoadingCourses(true);
    fetchCurricula()
      .then((data) => setCourses(data.curricula || []))
      .catch((err) => console.error('Failed to load curricula:', err))
      .finally(() => setLoadingCourses(false));
  }, []);

  // Load course detail when selected
  const handleSelectCourse = useCallback(async (courseId: string) => {
    if (courseId === selectedCourseId && courseDetail) return;

    setSelectedCourseId(courseId);
    setSelectedPaperId(null);
    setLoadingCourse(true);

    try {
      const detail = await fetchCurriculumDetail(courseId);
      setCourseDetail(detail);

      // Auto-select first module
      if (detail.modules?.length > 0) {
        setSelectedModuleId(detail.modules[0].id);
      }

      // Load progress
      if (isAuthenticated) {
        try {
          const prog = await fetchCurriculumProgress(courseId);
          setReadPapers(new Set(prog.read_papers || []));
        } catch {
          // Fall back to localStorage
          const stored = localStorage.getItem(LS_PREFIX + courseId);
          if (stored) {
            try {
              setReadPapers(new Set(JSON.parse(stored)));
            } catch {
              setReadPapers(new Set());
            }
          } else {
            setReadPapers(new Set());
          }
        }
      } else {
        // Not authenticated — use localStorage
        const stored = localStorage.getItem(LS_PREFIX + courseId);
        if (stored) {
          try {
            setReadPapers(new Set(JSON.parse(stored)));
          } catch {
            setReadPapers(new Set());
          }
        } else {
          setReadPapers(new Set());
        }
      }
    } catch (err) {
      console.error('Failed to load course:', err);
      setCourseDetail(null);
    } finally {
      setLoadingCourse(false);
    }
  }, [selectedCourseId, courseDetail, isAuthenticated]);

  // Toggle paper read (optimistic update)
  const handleToggleRead = useCallback((paperId: string) => {
    const newRead = !readPapers.has(paperId);

    // Optimistic update
    setReadPapers((prev) => {
      const next = new Set(prev);
      if (newRead) {
        next.add(paperId);
      } else {
        next.delete(paperId);
      }

      // Save to localStorage
      if (selectedCourseId) {
        localStorage.setItem(LS_PREFIX + selectedCourseId, JSON.stringify([...next]));
      }

      return next;
    });

    // Sync to server if authenticated
    if (isAuthenticated && selectedCourseId) {
      updateCurriculumProgress(selectedCourseId, paperId, newRead).catch((err) => {
        console.error('Failed to sync progress:', err);
        // Rollback on error
        setReadPapers((prev) => {
          const rollback = new Set(prev);
          if (newRead) {
            rollback.delete(paperId);
          } else {
            rollback.add(paperId);
          }
          return rollback;
        });
      });
    }
  }, [readPapers, selectedCourseId, isAuthenticated]);

  // Search a paper in the main search page
  const handleSearchPaper = useCallback((paper: CurriculumPaper) => {
    navigate(`/?q=${encodeURIComponent(paper.title)}`);
  }, [navigate]);

  // Selected module data
  const selectedModule = useMemo(() => {
    if (!courseDetail || !selectedModuleId) return null;
    return courseDetail.modules.find((m) => m.id === selectedModuleId) || null;
  }, [courseDetail, selectedModuleId]);

  // Selected paper data
  const selectedPaper = useMemo((): CurriculumPaper | null => {
    if (!courseDetail || !selectedPaperId) return null;
    for (const mod of courseDetail.modules) {
      for (const topic of mod.topics) {
        for (const paper of topic.papers) {
          if (paper.id === selectedPaperId) return paper;
        }
      }
    }
    return null;
  }, [courseDetail, selectedPaperId]);

  // Compute progress stats for current course
  const progressStats = useMemo(() => {
    if (!courseDetail) return { read: 0, total: 0, percent: 0 };
    let total = 0;
    for (const mod of courseDetail.modules) {
      for (const topic of mod.topics) {
        total += topic.papers.length;
      }
    }
    const read = [...readPapers].filter((id) => {
      // Only count papers that exist in this course
      for (const mod of courseDetail.modules) {
        for (const topic of mod.topics) {
          if (topic.papers.some((p) => p.id === id)) return true;
        }
      }
      return false;
    }).length;
    return { read, total, percent: total > 0 ? Math.round((read / total) * 100) : 0 };
  }, [courseDetail, readPapers]);

  // Module progress
  const getModuleProgress = useCallback((moduleId: string) => {
    if (!courseDetail) return { read: 0, total: 0 };
    const mod = courseDetail.modules.find((m) => m.id === moduleId);
    if (!mod) return { read: 0, total: 0 };
    let total = 0;
    let read = 0;
    for (const topic of mod.topics) {
      for (const paper of topic.papers) {
        total++;
        if (readPapers.has(paper.id)) read++;
      }
    }
    return { read, total };
  }, [courseDetail, readPapers]);

  // Generate custom curriculum
  const handleGenerate = useCallback(async (topic: string, difficulty: string, numModules: number) => {
    setGenerating(true);
    try {
      const result = await generateCurriculum(topic, difficulty, numModules);
      // Refresh course list
      const data = await fetchCurricula();
      setCourses(data.curricula || []);
      // Auto-select the new course
      if (result.course_id) {
        await handleSelectCourse(result.course_id);
      }
      return result;
    } catch (err) {
      console.error('Failed to generate curriculum:', err);
      throw err;
    } finally {
      setGenerating(false);
    }
  }, [handleSelectCourse]);

  return {
    courses,
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
    handleSelectCourse,
    setSelectedModuleId,
    setSelectedPaperId,
    handleToggleRead,
    handleSearchPaper,
    handleGenerate,
    getModuleProgress,
  };
}
