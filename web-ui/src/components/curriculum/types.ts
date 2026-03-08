export interface CurriculumSummary {
  id: string;
  name: string;
  university: string;
  instructor: string;
  difficulty: 'beginner' | 'intermediate' | 'advanced';
  prerequisites: string[];
  description: string;
  url: string;
  total_papers: number;
  total_modules: number;
  is_preset?: boolean;
  owner?: string | null;
  forked_from?: string | null;
}

export interface CurriculumPaper {
  id: string;
  title: string;
  authors: string[];
  year: number;
  venue: string;
  arxiv_id?: string | null;
  doi?: string | null;
  category: 'required' | 'optional' | 'supplementary';
  context: string;
}

export interface CurriculumTopic {
  id: string;
  title: string;
  papers: CurriculumPaper[];
}

export interface CurriculumModule {
  id: string;
  week: number;
  title: string;
  description: string;
  topics: CurriculumTopic[];
}

export interface CurriculumCourse extends CurriculumSummary {
  modules: CurriculumModule[];
}

export interface CurriculumProgress {
  course_id: string;
  read_papers: string[];
  total_papers: number;
  progress_percent: number;
  updated_at: string | null;
}
