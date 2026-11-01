import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import '../conversation/ConversationPage.css';
import { fetchSampleConversation } from '../../api/samples';
import type { SampleConversation, SampleSummary, SampleTurn } from '../../types';
import SearchResultsBlock from '../conversation/SearchResultsBlock';
import { linkCitations, normalizeEmphasis, searchBlockOf } from '../conversation/conversationBlocks';
import MascotFace from './MascotFace';

const MS_PER_CHAR = 18;
const TURN_PAUSE_MS = 1200;
const MAX_SAMPLE_MS = 60_000;

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

/** Where the lead paragraph ends: the first blank line, as the live page splits it. */
const leadEndOf = (content: string): number => {
  const match = /\n\s*\n/.exec(content);
  return match ? match.index : content.length;
};

interface ReplayPlayerProps {
  sample: SampleConversation;
  /** Show every turn at once, with no typing (prefers-reduced-motion). */
  reduced: boolean;
  /** Playing, on screen and the tab visible. */
  running: boolean;
  onFinished: () => void;
}

/**
 * Plays one sample: each user bubble, then the assistant's answer typed out
 * word by word, the inline results appearing once the lead is written. Mount
 * with a key per (sample, replay) so it starts from the top.
 */
function ReplayPlayer({ sample, reduced, running, onFinished }: ReplayPlayerProps) {
  const navigate = useNavigate();
  const [turnIndex, setTurnIndex] = useState(0);
  const [typed, setTyped] = useState(0);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const turns = sample.turns;

  // ~18ms a character, slowed down for no sample but sped up so none runs past a minute.
  const msPerChar = useMemo(() => {
    const total = turns.filter(turn => turn.role === 'assistant').reduce((sum, turn) => sum + turn.content.length, 0);
    return total > 0 ? Math.min(MS_PER_CHAR, MAX_SAMPLE_MS / total) : MS_PER_CHAR;
  }, [turns]);

  useEffect(() => {
    if (reduced || !running) return undefined;
    const turn = turns[turnIndex];
    let timer: ReturnType<typeof setTimeout>;
    if (!turn) {
      timer = setTimeout(onFinished, 0);
    } else if (turn.role === 'user' || typed >= turn.content.length) {
      // A finished turn rests for a beat before the next one starts.
      timer = setTimeout(() => {
        setTurnIndex(index => index + 1);
        setTyped(0);
      }, TURN_PAUSE_MS);
    } else {
      // Type up to the end of the next word.
      const word = /^\s*\S+/.exec(turn.content.slice(typed));
      const end = typed + (word ? word[0].length : turn.content.length - typed);
      timer = setTimeout(() => setTyped(end), Math.max(1, (end - typed) * msPerChar));
    }
    return () => clearTimeout(timer);
  }, [reduced, running, turns, turnIndex, typed, msPerChar, onFinished]);

  useEffect(() => {
    const box = scrollRef.current;
    if (box && !reduced) box.scrollTop = box.scrollHeight;
  }, [turnIndex, typed, reduced]);

  const openSample = () => navigate(`/samples/${sample.slug}`);
  const done = reduced || turnIndex >= turns.length;

  const renderAssistant = (turn: SampleTurn, shown: number) => {
    const text = turn.content.slice(0, shown);
    const search = searchBlockOf({ ...turn, id: '', status: 'done', created_at: '' });
    const leadEnd = leadEndOf(turn.content);
    const showBlock = Boolean(search) && shown >= leadEnd;
    return (
      <>
        <div className="conv-assistant-head">
          <MascotFace size={32} className="conv-avatar" />
          <span className="conv-assistant-name">집현전</span>
          <span className="conv-assistant-role">논문 연구 도우미</span>
        </div>
        {shown === 0 && (
          <p className="conv-status is-live">
            <span className="conv-status-dot" aria-hidden="true" />
            생각하는 중…
          </p>
        )}
        {search ? (
          <>
            <ReplayMarkdown text={text.slice(0, leadEnd)} />
            {showBlock && search.papers.length > 0 && (
              <SearchResultsBlock block={search} onSelect={openSample} onShowAll={openSample} />
            )}
            <ReplayMarkdown text={text.slice(leadEnd).trim()} />
          </>
        ) : (
          <ReplayMarkdown text={text} />
        )}
      </>
    );
  };

  return (
    <div className="home-replay-body" ref={scrollRef}>
      <ol className="conv-thread">
        {turns.map((turn, index) => {
          if (!done && index > turnIndex) return null;
          const current = !done && index === turnIndex;
          return turn.role === 'user' ? (
            <li key={turn.seq} className="conv-turn is-user">
              <p className="conv-bubble">{turn.content}</p>
            </li>
          ) : (
            <li key={turn.seq} className="conv-turn is-assistant">
              {renderAssistant(turn, current ? typed : turn.content.length)}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

interface SampleReplayProps {
  /** The sample to play. Mount with `key={sample.slug}` so another sample starts from the top. */
  sample: SampleSummary;
}

/**
 * The guest home's replay panel: one sample conversation typed out in place,
 * with 다시 보기 and a pause toggle. Pauses off screen and in a hidden tab;
 * with reduced motion it shows the sample whole. "전체 답변" opens the full
 * sample page with its graph and list.
 */
function SampleReplay({ sample: summary }: SampleReplayProps) {
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

  const restart = () => {
    setNonce(value => value + 1);
    setFinished(false);
    setPlaying(true);
  };
  const togglePlay = () => {
    if (finished) restart();
    else setPlaying(value => !value);
  };

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

      {sample ? (
        <ReplayPlayer
          key={nonce}
          sample={sample}
          reduced={reduced}
          running={running}
          onFinished={onFinished}
        />
      ) : (
        <div className="home-replay-body">
          <p className="home-empty">{failed ? '상담 예시를 불러오지 못했어요.' : '상담 예시를 불러오는 중…'}</p>
        </div>
      )}

      <div className="home-replay-foot">
        <span className="home-replay-status">
          <span role="status">{status}</span>
          {/* Moving content needs a way to stop it (WCAG 2.2.2). */}
          {!reduced && (
            <button type="button" onClick={togglePlay}>{playing && !finished ? '멈춤' : '재생'}</button>
          )}
        </span>
        <span>{summary.asof} 기준</span>
      </div>
    </section>
  );
}

export default SampleReplay;
