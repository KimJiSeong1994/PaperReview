import { Link } from 'react-router-dom';
import LandingSections from './LandingSections';
import MascotFace from './home/MascotFace';
import { INTRODUCE_SAMPLE_PATH } from '../seo/introduceFaq';
import './IntroducePage.css';

export type IntroduceLocale = 'en' | 'ko';


interface SampleSentence {
  text: string;
  /** Result numbers cited at the end of the sentence, shown as a plain superscript. */
  cites: string;
}

/*
 * The hero's sample excerpt is fixed text, not a replay: the home already plays samples,
 * and a static card cannot shift the layout or change between visits. The Korean text is
 * the sample's first exchange trimmed as the home does (components/home/sampleExchange.ts):
 * the lead, the top three results, and the conclusion paragraph. The English is a
 * translation of the same excerpt.
 */
const COPY = {
  en: {
    pill: 'AI for paper research · free after sign-in',
    title: 'Find the papers.',
    titleAccent: 'Read the evidence.',
    lead: 'Ask about a topic or a paper title. Jiphyeonjeon searches six scholarly sources, removes duplicates, and numbers each answer with the papers it came from. Important claims are checked against the source in a full review.',
    ask: 'Ask for free',
    sample: 'See a sample answer',
    note: 'Sample answers and public reviews are open without signing in.',
    sampleLabel: 'Sample answer from Jiphyeonjeon',
    sampleTitle: 'A conversation with Jiphyeonjeon',
    sampleMeta: 'Sample answer · as of 2026-11-02 · translated from Korean',
    question: 'When is GraphRAG better than standard RAG?',
    assistant: 'Jiphyeonjeon',
    role: 'paper research assistant',
    sampleLead: 'I’ll find the relevant papers and answer with the evidence.',
    resultsLabel: 'Top 3 search results',
    conclusion: [
      { text: 'GraphRAG helps most when a question has to connect several clues', cites: '3,8' },
      { text: 'Its strength is largest when structured knowledge or relationships inside documents matter and hallucinations must be kept down', cites: '3,7,8' },
      { text: 'For simple lookup questions the gap to standard RAG is small, and building the graph is the cost', cites: '2,4' },
    ] as SampleSentence[],
    fullAnswer: 'Full answer (in Korean) ↗',
  },
  ko: {
    pill: '논문 연구 AI · 로그인 후 무료',
    title: '논문을 찾은 뒤,',
    titleAccent: '근거까지 읽습니다.',
    lead: '궁금한 주제나 논문 제목을 물어보면 여섯 개 학술 출처에서 찾아 중복을 걷어내고, 답변마다 어느 논문에서 왔는지 번호로 달아 드립니다. 중요한 주장은 정밀 리뷰에서 원문과 다시 대조합니다.',
    ask: '무료로 물어보기',
    sample: '샘플 답변 보기',
    note: '샘플 답변과 공개 리뷰는 로그인 없이 볼 수 있어요.',
    sampleLabel: '집현전 샘플 답변',
    sampleTitle: '집현전과의 대화',
    sampleMeta: '2026-11-02 기준 · 상담 예시',
    question: 'GraphRAG가 기존 RAG보다 나은 경우는 언제야?',
    assistant: '집현전',
    role: '논문 연구 도우미',
    sampleLead: '관련 논문을 찾아 근거와 함께 답해 볼게요.',
    resultsLabel: '검색 결과 상위 3편',
    conclusion: [
      { text: 'GraphRAG는 질문이 여러 단서를 연결해야 할 때 더 유리합니다', cites: '3,8' },
      { text: '특히 구조화된 지식이나 문서 내부 관계가 중요하고, 환각을 줄여야 할 때 강점이 큽니다', cites: '3,7,8' },
      { text: '반면 단순 검색형 질문에서는 기존 RAG와 차이가 작고, 그래프 구축 비용이 문제입니다', cites: '2,4' },
    ] as SampleSentence[],
    fullAnswer: '전체 답변 ↗',
  },
} as const;

const SAMPLE_PAPERS = [
  { title: 'Is GraphRAG Needed? From Basic RAG to Graph-/Agentic Solutions with Context Optimization', meta: '2026 · OpenAlex' },
  { title: 'RAG vs. GraphRAG: A Systematic Evaluation and Key Insights', meta: '2026 · OpenAlex' },
  { title: 'Structured Knowledge for Multi-hop QA: A Comparative Study of GraphRAG and RAG', meta: '2025 · OpenAlex' },
];

interface IntroducePageProps {
  locale?: IntroduceLocale;
}

function IntroducePage({ locale = 'en' }: IntroducePageProps) {
  const copy = COPY[locale];

  return (
    <main className="main-content introduce-shell" lang={locale}>
      <div className="introduce-page">
        <header className="introduce-hero">
          <div className="introduce-hero-copy">
            <p className="introduce-pill">{copy.pill}</p>
            <h1 className="introduce-title">
              {copy.title}
              <span>{copy.titleAccent}</span>
            </h1>
            <div className="introduce-mascot">
              <MascotFace size={80} className="introduce-face" />
              <p className="introduce-lead">{copy.lead}</p>
            </div>
            <div className="intro-cta-group">
              <div className="introduce-cta">
                <Link className="intro-btn" to="/">{copy.ask}</Link>
                {/* An in-app link: a direct load of /samples needs the production nginx route. */}
                <Link className="intro-btn intro-btn--ghost" to={INTRODUCE_SAMPLE_PATH}>{copy.sample}</Link>
              </div>
              <p className="introduce-hero-note">{copy.note}</p>
            </div>
          </div>

          <section className="introduce-sample" aria-label={copy.sampleLabel}>
            <div className="introduce-sample-head">
              <h2 className="introduce-sample-title">{copy.sampleTitle}</h2>
              <p className="introduce-sample-meta">{copy.sampleMeta}</p>
            </div>
            <div className="introduce-sample-body">
              <p className="introduce-sample-question">{copy.question}</p>
              <div className="introduce-sample-answer">
                <p className="introduce-sample-who">
                  <MascotFace size={28} className="introduce-sample-face" />
                  <span className="introduce-sample-name">{copy.assistant}</span>
                  <span className="introduce-sample-role">{copy.role}</span>
                </p>
                <p>{copy.sampleLead}</p>
                <ol className="introduce-sample-results" aria-label={copy.resultsLabel}>
                  {SAMPLE_PAPERS.map((paper, index) => (
                    <li key={paper.title}>
                      <span className="introduce-sample-rank" aria-hidden="true">{index + 1}</span>
                      <span className="introduce-sample-paper">
                        <span className="introduce-sample-paper-title">{paper.title}</span>
                        <span className="introduce-sample-paper-meta">{paper.meta}</span>
                      </span>
                    </li>
                  ))}
                </ol>
                <p>
                  {copy.conclusion.map(sentence => (
                    <span key={sentence.cites}>
                      {sentence.text}<sup className="introduce-sample-cite">{sentence.cites}</sup>.{' '}
                    </span>
                  ))}
                </p>
              </div>
            </div>
            <div className="introduce-sample-foot">
              <Link className="introduce-sample-link" to={INTRODUCE_SAMPLE_PATH}>{copy.fullAnswer}</Link>
            </div>
          </section>
        </header>

        <LandingSections
          locale={locale}
          sample={{ question: copy.question, claim: copy.conclusion[0], papers: SAMPLE_PAPERS }}
        />
      </div>
    </main>
  );
}

export default IntroducePage;
