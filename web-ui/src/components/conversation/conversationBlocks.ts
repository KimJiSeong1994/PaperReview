import type {
  BookmarkRefsBlock,
  ConversationTurn,
  GraphBlock,
  PaperPdfBlock,
  PdfHighlightsBlock,
  ReviewStartedBlock,
  SearchResultsBlock,
} from '../../types';

export const CITE_PREFIX = '#cite-';
export const BOOKMARK_CITE_PREFIX = '#bm-';

export const searchBlockOf = (turn: ConversationTurn): SearchResultsBlock | null => (
  turn.blocks.find((block): block is SearchResultsBlock => block.type === 'search_results') ?? null
);

export const graphBlockOf = (turn: ConversationTurn): GraphBlock | null => (
  turn.blocks.find((block): block is GraphBlock => block.type === 'graph') ?? null
);

export const reviewBlockOf = (turn: ConversationTurn): ReviewStartedBlock | null => (
  turn.blocks.find((block): block is ReviewStartedBlock => block.type === 'review_started') ?? null
);

export const bookmarkRefsOf = (turn: ConversationTurn): BookmarkRefsBlock | null => (
  turn.blocks.find((block): block is BookmarkRefsBlock => block.type === 'bookmark_refs') ?? null
);

/** The paper a turn opened (paper_pdf) or highlighted (pdf_highlights); highlights win. */
export const pdfBlockOf = (turn: ConversationTurn): PaperPdfBlock | PdfHighlightsBlock | null => (
  turn.blocks.find((block): block is PdfHighlightsBlock => block.type === 'pdf_highlights')
  ?? turn.blocks.find((block): block is PaperPdfBlock => block.type === 'paper_pdf')
  ?? null
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
    // `**핵심 기여 [1][2]**는`: a citation before the closer leaves `]` there, which
    // CommonMark will not close on before a letter. Move citations outside the bold.
    .replace(/\*\*(?=[^\s*])([^*\n]*?[^\s*\]])((?:[ \t]*\[B?\d{1,2}\])+)\*\*/g, '**$1**$2')
    // `**…(…)**를`: punctuation before the closer, a letter after it. Move the
    // punctuation outside. Runs after the quote rule, which it would split.
    // The lookahead keeps a match from starting at a closing `**`.
    .replace(/\*\*(?=[^\s*])([^*\n]*?[^\s*])([)\]」』"”'’.,!?:;…]+)\*\*/g, '**$1**$2')
);

// A run of citations such as `[3][7]`, `[3], [7]` or `[3] [7]`; never a real link `[3](…)`.
const PAPER_RUN = /\[\d{1,2}\](?:[ \t]*,?[ \t]*\[\d{1,2}\])*(?!\()/g;
const BOOKMARK_RUN = /\[B\d{1,2}\](?:[ \t]*,?[ \t]*\[B\d{1,2}\])*(?!\()/g;
const numbersIn = (run: string): number[] => [...run.matchAll(/\d{1,2}/g)].map(match => Number(match[0]));

/**
 * Turns each run of `[n]` citations into one `#cite-3,7` link and each run of
 * `[Bn]` into `#bm-1,2`; the renderer draws them as author–year chips.
 */
export const linkCitations = (markdown: string): string => (
  markdown
    .replace(PAPER_RUN, run => `[${numbersIn(run).join(',')}](${CITE_PREFIX}${numbersIn(run).join(',')})`)
    .replace(BOOKMARK_RUN, run => `[B${numbersIn(run).join(',')}](${BOOKMARK_CITE_PREFIX}${numbersIn(run).join(',')})`)
);

/** The numbers a `#cite-3,7` / `#bm-1,2` link points at. */
export const citedNumbers = (href: string, prefix: string): number[] => (
  href.slice(prefix.length).split(',').map(Number).filter(n => Number.isInteger(n) && n > 0)
);

/** Paper numbers an answer cites, in order of first citation. */
export function citationOrder(markdown: string): number[] {
  const seen = new Set<number>();
  for (const run of markdown.match(PAPER_RUN) ?? []) numbersIn(run).forEach(n => seen.add(n));
  return [...seen];
}

const HANGUL = /[가-힣]/;
// Some sources put a year or a dash in the author field; without a letter it is not a name.
const HAS_LETTER = /\p{L}/u;
// Others put the venue or affiliation first ("Association for Computational Linguistics 2026").
const NOT_A_PERSON = /\d{4}|\b(?:association|conference|proceedings|workshop|symposium|journal|university|institute|press)\b/i;

/** Whether an author entry reads as a person: it has a letter, no year, and no venue word. */
const isPersonName = (author: string): boolean => HAS_LETTER.test(author) && !NOT_A_PERSON.test(author);

/** First author's surname: the last word of a Western name, the whole of a Korean one. */
function firstAuthorName(author: string | undefined): string | null {
  const name = author?.trim();
  if (!name || !isPersonName(name)) return null;
  if (HANGUL.test(name)) return name;
  // "Han, Jiseong" lists the surname first.
  const surname = name.includes(',')
    ? name.split(',')[0].trim()
    : name.split(/\s+/).at(-1)?.replace(/[.,;]+$/, '');
  return surname && HAS_LETTER.test(surname) ? surname : null;
}

const yearOf = (year: unknown): string | null => {
  const match = /\d{4}/.exec(String(year ?? ''));
  return match ? match[0] : null;
};

const clip = (text: string, max: number): string => (text.length > max ? `${text.slice(0, max).trimEnd()}…` : text);

/** A citation's reader-facing label: "Han 2026", "한지성 2025", or the title's start without authors. */
export function citationLabel(paper: { title: string; authors?: string[]; year?: unknown }): string {
  const who = firstAuthorName(paper.authors?.find(author => isPersonName(author.trim()))) ?? clip(paper.title.trim(), 20);
  const year = yearOf(paper.year);
  return year ? `${who} ${year}` : who;
}

/** "Han, Lee, Park et al." for the reference list. */
export function authorList(authors: string[] | undefined, max = 3): string {
  const list = (authors ?? []).map(author => author.trim()).filter(isPersonName);
  if (list.length === 0) return '';
  return list.length > max ? `${list.slice(0, max).join(', ')} et al.` : list.join(', ');
}

export const paperYear = yearOf;

/** Collapsed status line of a finished turn: "출처 4곳 · 42편 · 그래프", "심층 리뷰 시작", "PDF 열기", "하이라이트 N개". */
export function turnSummary(turn: ConversationTurn): string | null {
  const bookmarks = bookmarkRefsOf(turn);
  if (bookmarks) return `북마크 ${bookmarks.bookmarks.length}개 근거`;
  if (reviewBlockOf(turn)) return '심층 리뷰 시작';
  const pdf = pdfBlockOf(turn);
  if (pdf) return pdf.type === 'pdf_highlights' ? `하이라이트 ${pdf.highlights.length}개` : 'PDF 열기';
  const search = searchBlockOf(turn);
  if (!search) return null;
  const sources = new Set(search.papers.map(paper => paper.source).filter(Boolean)).size;
  return [
    sources > 0 && `출처 ${sources}곳`,
    `${search.total}편`,
    graphBlockOf(turn) && '그래프',
  ].filter(Boolean).join(' · ');
}

/**
 * Deep-review progress in the reader's words. The review service reports in
 * English ("AI is analysing the papers...", "Fetching paper abstracts..."), and
 * raw strings can carry exception text, so anything unrecognised becomes "진행 중…".
 */
export function reviewProgressLabel(progress: string | null | undefined): string {
  const text = (progress ?? '').trim();
  if (!text || /^starting/i.test(text)) return '심층 리뷰를 시작하는 중…';
  if (/[가-힣]/.test(text)) return text;
  if (/retry/i.test(text)) return '논문을 다시 분석하는 중…';
  if (/fetch|abstract/i.test(text)) return '논문 정보를 모으는 중…';
  if (/verif/i.test(text)) return '주장을 검증하는 중…';
  if (/report|generat/i.test(text)) return '리포트를 쓰는 중…';
  if (/analy[sz]/i.test(text)) return '논문을 분석하는 중…';
  return '진행 중…';
}

// routers/highlight_service.py PDF_CATEGORY_CONFIG, in Korean, with its colour family.
const HIGHLIGHT_CATEGORY: Record<string, { label: string; tone: 'finding' | 'method' | 'limit' | 'assume' }> = {
  finding: { label: '핵심 발견', tone: 'finding' },
  evidence: { label: '근거·데이터', tone: 'finding' },
  contribution: { label: '기여', tone: 'finding' },
  claim: { label: '저자 주장', tone: 'finding' },
  methodology: { label: '방법론', tone: 'method' },
  insight: { label: '인사이트', tone: 'method' },
  reproducibility: { label: '재현성', tone: 'method' },
  experimental_setup: { label: '실험 설정', tone: 'method' },
  limitation: { label: '한계', tone: 'limit' },
  gap: { label: '연구 공백', tone: 'limit' },
  assumption: { label: '숨은 가정', tone: 'assume' },
};

/** Chip label and colour family of a highlight category; unknown ones read "하이라이트". */
export function highlightCategory(category: string | undefined): { label: string; tone: string } {
  return HIGHLIGHT_CATEGORY[category ?? ''] ?? { label: '하이라이트', tone: 'other' };
}

const VERIFICATION_LABEL: Record<string, string> = {
  verified: '확인',
  partially_verified: '부분',
  unverified: '미확인',
  contradicted: '반박',
};

/** A claim's verification status in Korean; null when the service did not report one. */
export function verificationStatusLabel(status: string | undefined): string | null {
  return status ? VERIFICATION_LABEL[status] ?? null : null;
}

/** The passage a claim was checked against: its own evidence, or the first linked one. */
export function claimEvidence(claim: { evidence?: string; evidences?: { text?: string }[] }): string | null {
  return claim.evidence?.trim() || claim.evidences?.find(item => item.text?.trim())?.text?.trim() || null;
}

/**
 * Whether the artifact may open by itself (a sample loading, a search's
 * results arriving). Only where it is a third column (≥1101px, as
 * `.conv-shell.has-artifact`); below that it is a full-width sheet that would
 * cover the thread, so it waits for the reader to tap 아티팩트.
 */
export const canAutoOpenArtifact = (): boolean => {
  try {
    return window.matchMedia?.('(min-width: 1101px)').matches === true;
  } catch {
    return false;
  }
};
