import type { Paper, SampleConversation, SearchResultsBlock } from '../../types';

export interface SampleExchange {
  question: string;
  /** The answer's first paragraph. */
  lead: string;
  /** The inline results, top three only. */
  papers: Paper[];
  /** The first paragraph after the results, cut to fit the panel. */
  conclusion: string;
}

const CONCLUSION_MAX = 240;

/** Cut at the last sentence end before `max` characters, or hard at `max`, and mark the cut. */
export function clipToSentence(text: string, max = CONCLUSION_MAX): string {
  if (text.length <= max) return text;
  const head = text.slice(0, max);
  const ends = [...head.matchAll(/[.!?。](?=\s|$)/g)];
  const cut = ends.length > 0 ? ends[ends.length - 1].index! + 1 : max;
  return `${head.slice(0, cut).trimEnd()}…`;
}

/**
 * The one exchange the guest home replays: the sample's first question and the
 * first answer to it, trimmed to a lead, three results and a conclusion.
 */
export function sampleExchange(sample: SampleConversation): SampleExchange | null {
  const askedAt = sample.turns.findIndex(turn => turn.role === 'user');
  const answer = sample.turns.slice(askedAt + 1).find(turn => turn.role === 'assistant');
  if (askedAt < 0 || !answer) return null;
  const paragraphs = answer.content.split(/\n\s*\n/).map(part => part.trim()).filter(Boolean);
  const search = answer.blocks.find((block): block is SearchResultsBlock => block.type === 'search_results');
  return {
    question: sample.turns[askedAt].content,
    lead: paragraphs[0] ?? '',
    papers: search?.papers.slice(0, 3) ?? [],
    conclusion: clipToSentence(paragraphs[1] ?? ''),
  };
}
