import type { ConversationTurn, GraphBlock, ReviewStartedBlock, SearchResultsBlock } from '../../types';

export const CITE_PREFIX = '#cite-';

export const searchBlockOf = (turn: ConversationTurn): SearchResultsBlock | null => (
  turn.blocks.find((block): block is SearchResultsBlock => block.type === 'search_results') ?? null
);

export const graphBlockOf = (turn: ConversationTurn): GraphBlock | null => (
  turn.blocks.find((block): block is GraphBlock => block.type === 'graph') ?? null
);

export const reviewBlockOf = (turn: ConversationTurn): ReviewStartedBlock | null => (
  turn.blocks.find((block): block is ReviewStartedBlock => block.type === 'review_started') ?? null
);

/** A turn's search and its graph, keyed by the turn's seq so a repeated query stays distinct. */
export interface TurnResults {
  seq: number;
  search: SearchResultsBlock;
  graph: GraphBlock | null;
}

export const resultsOf = (turns: ConversationTurn[]): TurnResults[] => turns.flatMap(turn => {
  const search = searchBlockOf(turn);
  return search ? [{ seq: turn.seq, search, graph: graphBlockOf(turn) }] : [];
});

/**
 * The results each turn's `[n]` citations point into: its own search, or the
 * latest one before it (an answer turn cites the results it was asked about).
 */
export function citationSources(turns: ConversationTurn[]): Map<string, TurnResults> {
  const sources = new Map<string, TurnResults>();
  let latest: TurnResults | null = null;
  turns.forEach(turn => {
    const search = searchBlockOf(turn);
    if (search) latest = { seq: turn.seq, search, graph: graphBlockOf(turn) };
    if (turn.role === 'assistant' && latest) sources.set(turn.id, latest);
  });
  return sources;
}

/**
 * Search degradation markers in the reader's words. `source_incomplete` means
 * a source did not answer; ranker and stage fallbacks (`ranker_unavailable`,
 * `stage:mode`) collapse into one line; anything else is not shown.
 */
export function degradedLabels(markers: string[]): string[] {
  const labels = new Set<string>();
  markers.forEach(marker => {
    if (marker === 'source_incomplete') labels.add('일부 출처가 응답하지 않았어요.');
    else if (marker === 'ranker_unavailable' || marker.includes(':')) labels.add('순위 계산은 대체 방식으로 했어요.');
  });
  return [...labels];
}

/**
 * A search turn opens with a one-paragraph lead, then the results, then the
 * summary. Live turns know where the lead ended; saved ones split at the
 * first blank line. Turns without results have no lead.
 */
export function splitLead(content: string, hasResults: boolean, leadLength?: number): { lead: string; rest: string } {
  if (!hasResults) return { lead: '', rest: content };
  if (leadLength !== undefined) return { lead: content.slice(0, leadLength).trim(), rest: content.slice(leadLength).trim() };
  const match = /\n\s*\n/.exec(content);
  return match
    ? { lead: content.slice(0, match.index).trim(), rest: content.slice(match.index + match[0].length).trim() }
    : { lead: content.trim(), rest: '' };
}

/**
 * CommonMark will not close `**"제목"**가` (a quote before the delimiter, a Hangul
 * letter after it), so the asterisks print. Unwrap quoted and triple emphasis
 * to plain bold, and move trailing punctuation out of bold, before parsing.
 */
export const normalizeEmphasis = (markdown: string): string => (
  markdown
    .replace(/\*{2,3}"([^"\n]+)"\*{2,3}/g, '**$1**')
    .replace(/\*{3}([^*\n]+)\*{3}/g, '**$1**')
    // `**…(…)**를`: punctuation before the closer, a letter after it. Move the
    // punctuation outside. Runs after the quote rule, which it would split.
    // The lookahead keeps a match from starting at a closing `**`.
    .replace(/\*\*(?=[^\s*])([^*\n]*?[^\s*])([)\]」』"”'’.,!?:;…]+)\*\*/g, '**$1**$2')
);

/** Turns `[3]` into a `#cite-3` link the renderer swaps for a button; leaves real links alone. */
export const linkCitations = (markdown: string): string => (
  markdown.replace(/\[(\d{1,2})\](?!\()/g, `[$1](${CITE_PREFIX}$1)`)
);

/** Collapsed status line of a finished turn: "출처 4곳 · 42편 · 그래프", or "심층 리뷰 시작". */
export function turnSummary(turn: ConversationTurn): string | null {
  if (reviewBlockOf(turn)) return '심층 리뷰 시작';
  const search = searchBlockOf(turn);
  if (!search) return null;
  const sources = new Set(search.papers.map(paper => paper.source).filter(Boolean)).size;
  return [
    sources > 0 && `출처 ${sources}곳`,
    `${search.total}편`,
    graphBlockOf(turn) && '그래프',
  ].filter(Boolean).join(' · ');
}
