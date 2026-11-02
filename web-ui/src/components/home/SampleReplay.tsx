import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import '../conversation/ConversationPage.css';
import { fetchSampleConversation } from '../../api/samples';
import type { SampleConversation, SampleSummary } from '../../types';
import { linkCitations, normalizeEmphasis } from '../conversation/conversationBlocks';
import MascotFace from './MascotFace';
import { sampleExchange, type SampleExchange } from './sampleExchange';

const MS_PER_CHAR = 18;
// "생각하는 중…" before the answer starts.
const THINK_MS = 1200;
// The whole exchange types out within this; long answers type faster.
const EXCHANGE_MS = 15_000;

const prefersReducedMotion = (): boolean => {
  try {
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  } catch {
    return false;
  }
};

/** Citations in a replay are read-only: the numbers show, the artifact lives on /samples. */
function ReplayLink({ href, children }: { href?: string; children?: ReactNode }) {
  if (href?.startsWith('#cite-') || href?.startsWith('#bm-')) {
    return <sup className="conv-cite-group">{children}</sup>;
  }
  return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
}
const MARKDOWN_COMPONENTS = { a: ReplayLink };
const MARKDOWN_PLUGINS = [remarkGfm];

function ReplayMarkdown({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="conv-markdown">
      <ReactMarkdown remarkPlugins={MARKDOWN_PLUGINS} components={MARKDOWN_COMPONENTS}>
        {linkCitations(normalizeEmphasis(text))}
      </ReactMarkdown>
    </div>
  );
}

interface ReplayPlayerProps {
  exchange: SampleExchange;
  /** Show the whole exchange at once, with no typing (prefers-reduced-motion). */
  reduced: boolean;
  /** Playing, on screen and the tab visible. */
  running: boolean;
  onFinished: () => void;
  /** "로그인하고 이어서 물어보기": ask this sample's question for real. */
  onContinue: (question: string) => void;
}

/**
 * Plays one exchange: the question, a beat of "생각하는 중…", the lead typed
 * word by word, the top results, the conclusion, then the sign-in CTA. Mount
 * with a key per (sample, replay) so it starts from the top.
 */
function ReplayPlayer({ exchange, reduced, running, onFinished, onContinue }: ReplayPlayerProps) {
  // Typed as one string, lead and conclusion joined by a line break so a word never spans both.
  const text = `${exchange.lead}\n${exchange.conclusion}`;
  const leadEnd = exchange.lead.length;
  const msPerChar = Math.min(MS_PER_CHAR, (EXCHANGE_MS - THINK_MS) / Math.max(1, text.length));
  const [thinking, setThinking] = useState(!reduced);
  const [typed, setTyped] = useState(reduced ? text.length : 0);

  useEffect(() => {
    if (reduced || !running) return undefined;
    let timer: ReturnType<typeof setTimeout>;
    if (thinking) {
      timer = setTimeout(() => setThinking(false), THINK_MS);
    } else if (typed >= text.length) {
      timer = setTimeout(onFinished, 0);
    } else {
      // Type up to the end of the next word.
      const word = /^\s*\S+/.exec(text.slice(typed));
      const end = typed + (word ? word[0].length : text.length - typed);
      timer = setTimeout(() => setTyped(end), Math.max(1, (end - typed) * msPerChar));
    }
    return () => clearTimeout(timer);
  }, [reduced, running, thinking, typed, text, msPerChar, onFinished]);

  const done = typed >= text.length;
  return (
    <div className="home-replay-body">
      <ol className="conv-thread">
        <li className="conv-turn is-user">
          <p className="conv-bubble">{exchange.question}</p>
        </li>
        <li className="conv-turn is-assistant">
          <div className="conv-assistant-head">
            <MascotFace size={32} className="conv-avatar" />
            <span className="conv-assistant-name">집현전</span>
            <span className="conv-assistant-role">논문 연구 도우미</span>
          </div>
          {thinking && (
            <p className="conv-status is-live">
              <span className="conv-status-dot" aria-hidden="true" />
              생각하는 중…
            </p>
          )}
          <ReplayMarkdown text={text.slice(0, Math.min(typed, leadEnd))} />
          {typed >= leadEnd && exchange.papers.length > 0 && (
            <ol className="home-replay-results" aria-label={`검색 결과 상위 ${exchange.papers.length}편`}>
              {exchange.papers.map((paper, index) => (
                <li key={String(paper.result_key ?? paper.doc_id)}>
                  <span className="home-replay-rank" aria-hidden="true">{index + 1}</span>
                  <span className="home-replay-paper">
                    <span className="home-replay-paper-title">{paper.title}</span>
                    <span className="home-replay-paper-meta">{[paper.year, paper.source].filter(Boolean).join(' · ')}</span>
                  </span>
                </li>
              ))}
            </ol>
          )}
          <ReplayMarkdown text={typed > leadEnd ? text.slice(leadEnd + 1, typed) : ''} />
          {done && (
            <div className="home-replay-cta">
              <span>내 질문으로 이어서 물어보세요</span>
              <button type="button" className="home-btn" onClick={() => onContinue(exchange.question)}>
                로그인하고 이어서 물어보기 →
              </button>
            </div>
          )}
        </li>
      </ol>
    </div>
  );
}

interface SampleReplayProps {
  /** The sample to play. Mount with `key={sample.slug}` so another sample starts from the top. */
  sample: SampleSummary;
  /** Asks the sample's question as a real conversation, through the home's sign-in gate. */
  onContinue: (question: string) => void;
}

/**
 * The guest home's replay panel: a sample's first exchange typed out in a
 * fixed-height card, with 다시 보기 and a pause toggle. Pauses off screen and in a hidden tab;
 * with reduced motion it shows the sample whole. "전체 답변" opens the full
 * sample page with its graph and list.
 */
function SampleReplay({ sample: summary, onContinue }: SampleReplayProps) {
  const [nonce, setNonce] = useState(0);
  const [sample, setSample] = useState<SampleConversation | null>(null);
  const [failed, setFailed] = useState(false);
  const [playing, setPlaying] = useState(true);
  const [finished, setFinished] = useState(false);
  const [onScreen, setOnScreen] = useState(true);
  const [tabVisible, setTabVisible] = useState(() => document.visibilityState !== 'hidden');
  const [reduced] = useState(prefersReducedMotion);
  const rootRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchSampleConversation(summary.slug, controller.signal)
      .then(data => { if (!controller.signal.aborted) setSample(data); })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, [summary.slug]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof IntersectionObserver === 'undefined') return undefined;
    const observer = new IntersectionObserver(entries => setOnScreen(entries.some(entry => entry.isIntersecting)));
    observer.observe(root);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const onVisibility = () => setTabVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);

  const onFinished = useCallback(() => setFinished(true), []);
  const exchange = useMemo(() => (sample ? sampleExchange(sample) : null), [sample]);

  const restart = () => {
    setNonce(value => value + 1);
    setFinished(false);
    setPlaying(true);
  };
  const togglePlay = () => setPlaying(value => !value);

  const running = playing && !finished && onScreen && tabVisible;
  const status = reduced
    ? '상담 예시'
    : finished
      ? '상담 예시 · 재생 완료'
      : playing ? '상담 예시 · 재생 중' : '상담 예시 · 멈춤';

  return (
    <section className="home-replay" aria-labelledby="home-replay-title" ref={rootRef}>
      <div className="home-replay-head">
        <div>
          <h2 id="home-replay-title" className="home-replay-title">집현전과의 대화</h2>
          <p className="home-replay-sub">{summary.asof} 기준 · 상담 예시</p>
        </div>
        <div className="home-replay-actions">
          <Link className="home-replay-open" to={`/samples/${summary.slug}`}>전체 답변 ↗</Link>
          {!reduced && <button type="button" onClick={restart}>↻ 다시 보기</button>}
        </div>
      </div>

      {exchange ? (
        <ReplayPlayer
          key={nonce}
          exchange={exchange}
          reduced={reduced}
          running={running}
          onFinished={onFinished}
          onContinue={onContinue}
        />
      ) : (
        <div className="home-replay-body">
          <p className="home-empty">{failed || sample ? '상담 예시를 불러오지 못했어요.' : '상담 예시를 불러오는 중…'}</p>
        </div>
      )}

      <div className="home-replay-foot">
        <span className="home-replay-status">
          <span role="status">{status}</span>
          {/* Moving content needs a way to stop it (WCAG 2.2.2). */}
          {/* Once finished, ↻ 다시 보기 is the way to play again. */}
          {!reduced && !finished && (
            <button type="button" onClick={togglePlay}>{playing ? '멈춤' : '재생'}</button>
          )}
        </span>
        <span>{summary.asof} 기준</span>
      </div>
    </section>
  );
}

export default SampleReplay;
