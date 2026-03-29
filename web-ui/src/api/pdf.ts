import { api } from './base';

export async function resolvePdfUrl(title: string, doi?: string, arxivId?: string): Promise<{pdf_url: string | null; source: string | null}> {
  const params: Record<string, string> = { title };
  if (doi) params.doi = doi;
  if (arxivId) params.arxiv_id = arxivId;
  const { data } = await api.get('/api/pdf/resolve', { params });
  return data;
}

export async function batchResolvePdfUrls(
  papers: { title: string; doi?: string; arxiv_id?: string }[],
): Promise<{ results: { pdf_url: string | null; source: string | null }[] }> {
  const { data } = await api.post('/api/pdf/resolve-batch', { papers });
  return data;
}

// Semantic Scholar Reader
export async function getS2ReaderUrl(
  title: string,
  doi?: string,
  arxivId?: string,
): Promise<{ reader_url: string | null; paper_id: string | null; pdf_url: string | null }> {
  const params: Record<string, string> = { title };
  if (doi) params.doi = doi;
  if (arxivId) params.arxiv_id = arxivId;
  const { data } = await api.get('/api/s2/reader-url', { params });
  return data;
}
