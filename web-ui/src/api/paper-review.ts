import { api } from './base';
import type { HighlightItem } from './base';

// Per-Paper Review API
export interface PaperReviewStrength {
  point: string;
  evidence: string;
  significance: 'high' | 'medium' | 'low';
}

export interface PaperReviewWeakness {
  point: string;
  evidence: string;
  severity: 'major' | 'minor';
}

export interface MethodologyAssessment {
  rigor: number;
  novelty: number;
  reproducibility: number;
  commentary: string;
}

export interface PaperReview {
  summary: string;
  strengths: PaperReviewStrength[];
  weaknesses: PaperReviewWeakness[];
  methodology_assessment: MethodologyAssessment;
  key_contributions: string[];
  questions_for_authors: string[];
  overall_score: number;
  confidence: number;
  detailed_review_markdown: string;
  created_at: string;
  model: string;
  input_type: 'full_text' | 'abstract' | 'metadata';
}

export interface PaperReviewResponse {
  success: boolean;
  review: PaperReview;
  highlights: HighlightItem[];
  highlight_count: number;
}

export const startPaperReview = async (
  bookmarkId: string,
  paperIndex: number,
  fullText?: string,
  abstract?: string,
): Promise<PaperReviewResponse> => {
  const body: Record<string, unknown> = { review_mode: 'fast' };
  if (fullText) body.full_text = fullText;
  if (abstract) body.abstract = abstract;
  const response = await api.post<PaperReviewResponse>(
    `/api/bookmarks/${bookmarkId}/papers/${paperIndex}/review`,
    body,
    { timeout: 180_000 },
  );
  return response.data;
};

export const getPaperReview = async (
  bookmarkId: string,
  paperIndex: number,
): Promise<{ review: PaperReview; highlights: HighlightItem[] }> => {
  const response = await api.get(`/api/bookmarks/${bookmarkId}/papers/${paperIndex}/review`);
  return response.data;
};

export const deletePaperReview = async (
  bookmarkId: string,
  paperIndex: number,
): Promise<{ success: boolean }> => {
  const response = await api.delete(`/api/bookmarks/${bookmarkId}/papers/${paperIndex}/review`);
  return response.data;
};

export const autoHighlightPaperReview = async (
  bookmarkId: string,
  paperIndex: number,
): Promise<{ highlights: HighlightItem[]; added_count: number; enriched_count: number }> => {
  const response = await api.post(
    `/api/bookmarks/${bookmarkId}/papers/${paperIndex}/auto-highlight`,
    {},
    { timeout: 180_000 },
  );
  return response.data;
};

// PDF Overlay Highlights (standalone — no bookmark required)
export const generatePdfHighlights = async (
  text: string,
  title: string,
): Promise<{ highlights: HighlightItem[] }> => {
  const response = await api.post<{ highlights: HighlightItem[] }>(
    '/api/pdf-highlights',
    { text, title },
    { timeout: 300_000 },
  );
  return response.data;
};

// Math Formula Explanation API
export interface MathExplanation {
  explanation: string;
  variables: { symbol: string; meaning: string }[];
  formula_type: string;
}

export const explainMathFormula = async (
  formulaText: string,
  context: string,
  paperTitle: string,
): Promise<MathExplanation> => {
  const response = await api.post<MathExplanation>(
    '/api/math-explain',
    { formula_text: formulaText, context, paper_title: paperTitle },
    { timeout: 60_000 },
  );
  return response.data;
};
