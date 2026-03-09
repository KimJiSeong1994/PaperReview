import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchCurricula,
  fetchCurriculumDetail,
  fetchCurriculumProgress,
  updateCurriculumProgress,
  forkCurriculum,
  deleteCurriculum,
  generateCurriculumStream,
} from '../api/client';
import type { CurriculumGenerateProgress } from '../api/client';
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

  // Generate / Fork
  const [generating, setGenerating] = useState(false);
  const [forking, setForking] = useState(false);
  const [generateProgress, setGenerateProgress] = useState<CurriculumGenerateProgress | null>(null);

  // Refs for stable access in callbacks
  const readPapersRef = useRef(readPapers);
  readPapersRef.current = readPapers;
  const selectedCourseIdRef = useRef(selectedCourseId);
  selectedCourseIdRef.current = selectedCourseId;
  const generateAbortRef = useRef<AbortController | null>(null);

  // Auth state is checked at call sites via localStorage directly
  // to avoid stale closure issues

  // Load course list on mount
  useEffect(() => {
    let ignore = false;
    setLoadingCourses(true);
    fetchCurricula()
      .then((data) => { if (!ignore) setCourses(data.curricula || []); })
      .catch((err) => console.error('Failed to load curricula:', err))
      .finally(() => { if (!ignore) setLoadingCourses(false); });
    return () => { ignore = true; };
  }, []);

  // Abort SSE stream on unmount
  useEffect(() => {
    return () => {
      generateAbortRef.current?.abort();
    };
  }, []);

  // Load course detail when selected
  const handleSelectCourse = useCallback(async (courseId: string) => {
    if (courseId === selectedCourseIdRef.current && courseDetail) return;

    setSelectedCourseId(courseId);
    setSelectedPaperId(null);
    setLoadingCourse(true);

    try {
      const detail = await fetchCurriculumDetail(courseId);

      // Guard against stale response
      if (courseId !== selectedCourseIdRef.current) return;

      setCourseDetail(detail);

      // Auto-select first module
      if (detail.modules?.length > 0) {
        setSelectedModuleId(detail.modules[0].id);
      }

      // Load progress
      const authenticated = !!localStorage.getItem('access_token');
      if (authenticated) {
        try {
          const prog = await fetchCurriculumProgress(courseId);
          if (courseId === selectedCourseIdRef.current) {
            setReadPapers(new Set(prog.read_papers || []));
          }
        } catch {
          // Fall back to localStorage
          const stored = localStorage.getItem(LS_PREFIX + courseId);
          if (stored && courseId === selectedCourseIdRef.current) {
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
  }, [courseDetail]);

  // Toggle paper read (optimistic update)
  const handleToggleRead = useCallback((paperId: string) => {
    setReadPapers((prev) => {
      const wasRead = prev.has(paperId);
      const next = new Set(prev);
      if (wasRead) {
        next.delete(paperId);
      } else {
        next.add(paperId);
      }

      // Save to localStorage
      const courseId = selectedCourseIdRef.current;
      if (courseId) {
        localStorage.setItem(LS_PREFIX + courseId, JSON.stringify([...next]));
      }

      // Sync to server if authenticated
      const authenticated = !!localStorage.getItem('access_token');
      if (authenticated && courseId) {
        updateCurriculumProgress(courseId, paperId, !wasRead).catch((err) => {
          console.error('Failed to sync progress:', err);
          // Rollback on error
          setReadPapers((rollbackPrev) => {
            const rollback = new Set(rollbackPrev);
            if (wasRead) {
              rollback.add(paperId);
            } else {
              rollback.delete(paperId);
            }
            return rollback;
          });
        });
      }

      return next;
    });
  }, []);

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

  // Pre-build a Set of all paper IDs in the course for O(1) lookups
  const coursePaperIds = useMemo(() => {
    if (!courseDetail) return new Set<string>();
    const ids = new Set<string>();
    for (const mod of courseDetail.modules) {
      for (const topic of mod.topics) {
        for (const paper of topic.papers) {
          ids.add(paper.id);
        }
      }
    }
    return ids;
  }, [courseDetail]);

  // Compute progress stats for current course — O(readPapers) with Set lookup
  const progressStats = useMemo(() => {
    if (!courseDetail) return { read: 0, total: 0, percent: 0 };
    const total = coursePaperIds.size;
    let read = 0;
    for (const id of readPapers) {
      if (coursePaperIds.has(id)) read++;
    }
    return { read, total, percent: total > 0 ? Math.round((read / total) * 100) : 0 };
  }, [courseDetail, readPapers, coursePaperIds]);

  // Module progress — memoized as a map
  const moduleProgressMap = useMemo(() => {
    const map: Record<string, { read: number; total: number }> = {};
    if (!courseDetail) return map;
    for (const mod of courseDetail.modules) {
      let total = 0;
      let read = 0;
      for (const topic of mod.topics) {
        for (const paper of topic.papers) {
          total++;
          if (readPapers.has(paper.id)) read++;
        }
      }
      map[mod.id] = { read, total };
    }
    return map;
  }, [courseDetail, readPapers]);

  const getModuleProgress = useCallback((moduleId: string) => {
    return moduleProgressMap[moduleId] || { read: 0, total: 0 };
  }, [moduleProgressMap]);

  // Derived lists: preset (featured) vs user's own
  const presetCourses = useMemo(() => courses.filter((c) => c.is_preset), [courses]);
  const myCourses = useMemo(() => courses.filter((c) => !c.is_preset), [courses]);

  // Fork a preset curriculum
  const handleFork = useCallback(async (courseId: string) => {
    setForking(true);
    try {
      const result = await forkCurriculum(courseId);
      // Refresh course list
      const data = await fetchCurricula();
      setCourses(data.curricula || []);
      // Auto-select the forked course
      if (result.course_id) {
        await handleSelectCourse(result.course_id);
      }
      return result;
    } catch (err) {
      console.error('Failed to fork curriculum:', err);
      throw err;
    } finally {
      setForking(false);
    }
  }, [handleSelectCourse]);

  // Delete a user's own curriculum
  const handleDelete = useCallback(async (courseId: string) => {
    try {
      await deleteCurriculum(courseId);
      // Refresh course list
      const data = await fetchCurricula();
      setCourses(data.curricula || []);
      // Clear selection if deleted course was selected
      if (selectedCourseIdRef.current === courseId) {
        setSelectedCourseId(null);
        setCourseDetail(null);
        setSelectedModuleId(null);
        setSelectedPaperId(null);
      }
    } catch (err) {
      console.error('Failed to delete curriculum:', err);
      throw err;
    }
  }, []);

  // Generate custom curriculum (3-step pipeline with SSE streaming)
  const handleGenerate = useCallback(async (
    topic: string, difficulty: string, numModules: number,
    options?: { learning_goals?: string; paper_preference?: string },
  ) => {
    // Abort any previous generation
    generateAbortRef.current?.abort();
    const abortController = new AbortController();
    generateAbortRef.current = abortController;

    setGenerating(true);
    setGenerateProgress({ step: 0, step_name: 'init', progress: 0, message: 'Starting...' });
    try {
      await generateCurriculumStream(
        { topic, difficulty, num_modules: numModules, ...options },
        (progress) => {
          if (!abortController.signal.aborted) setGenerateProgress(progress);
        },
        async (result) => {
          if (abortController.signal.aborted) return;
          try {
            setGenerateProgress({ step: 5, step_name: 'done', progress: 100, message: 'Curriculum created successfully!' });
            const data = await fetchCurricula();
            setCourses(data.curricula || []);
            if (result.course_id) {
              await handleSelectCourse(result.course_id);
            }
          } finally {
            setGenerateProgress(null);
            setGenerating(false);
          }
        },
        (error) => {
          if (abortController.signal.aborted) return;
          console.error('Curriculum generation failed:', error);
          setGenerateProgress({ step: -1, step_name: 'error', progress: 0, message: `Generation failed: ${error}` });
          setGenerating(false);
        },
        abortController.signal,
      );
    } catch (err) {
      if (abortController.signal.aborted) return;
      console.error('Failed to generate curriculum:', err);
      setGenerateProgress({ step: -1, step_name: 'error', progress: 0, message: `Connection failed: ${err}` });
      setGenerating(false);
    }
  }, [handleSelectCourse]);

  return {
    courses,
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
    handleSelectCourse,
    setSelectedModuleId,
    setSelectedPaperId,
    handleToggleRead,
    handleSearchPaper,
    handleGenerate,
    handleFork,
    handleDelete,
    getModuleProgress,
  };
}
