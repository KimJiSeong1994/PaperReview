import { api } from './base';
import type { HighlightItem } from './base';

// Per-Paper Review API
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