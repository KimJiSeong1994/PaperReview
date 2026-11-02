/**
 * The introduce page's FAQ, in one place: the page renders it, the runtime
 * FAQPage JSON-LD repeats it, and `scripts/create-static-routes.mjs` keeps a
 * byte-identical static copy (structuredData.test checks the static copy).
 */

/**
 * The sample the introduce hero excerpt is cut from (data/samples/conversations/graphrag-vs-rag.json).
 * Linked in-app only: a direct load of /samples needs the production nginx route.
 */
export const INTRODUCE_SAMPLE_PATH = '/samples/graphrag-vs-rag';

export interface IntroduceFaqItem {
  question: string;
  answer: string;
}

export const INTRODUCE_FAQ: Record<'en' | 'ko', IntroduceFaqItem[]> = {
  en: [
    {
      question: 'What kind of AI paper search tool is Jiphyeonjeon?',
      answer: 'It is a research assistant you ask about papers. It searches arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers, and OpenAlex’s Korean-language filter, removes duplicates, and numbers each answer with the papers it came from. The results open as a relation graph and a list.',
    },
    {
      question: 'What can I use without signing in?',
      answer: 'Sample answers and public paper reviews are open without an account. Sign in, free of charge, to ask your own questions and keep your conversations.',
    },
    {
      question: 'How are claims in an AI paper review verified?',
      answer: 'In a full review. A full review finds the source passage behind each important claim and labels it as a direct quote, paraphrase, inference, or unverified. The fast review that conversations start by default summarizes within minutes but does not verify claims.',
    },
    {
      question: 'Which sources does it search?',
      answer: 'arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers, and OpenAlex filtered to Korean-language papers. Coverage differs by source, so results can vary with the question and the time of the search.',
    },
    {
      question: 'Who is Jiphyeonjeon for?',
      answer: 'Researchers and graduate students entering a new field, research engineers comparing methods, and readers who need to test a paper’s claims against its evidence.',
    },
  ],
  ko: [
    {
      question: '집현전은 어떤 AI 논문 검색 도구인가요?',
      answer: '논문에 대해 물어보면 답하는 연구 도우미입니다. arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers와 OpenAlex 한국어 논문 필터에서 찾아 중복을 걷어내고, 답변마다 근거 논문을 번호로 달아 드립니다. 결과는 관계 그래프와 목록으로 볼 수 있습니다.',
    },
    {
      question: '로그인 없이 무엇을 사용할 수 있나요?',
      answer: '샘플 답변과 공개 논문 리뷰는 로그인 없이 볼 수 있습니다. 직접 질문하고 대화를 저장하려면 로그인하세요. 로그인 후 무료로 이용합니다.',
    },
    {
      question: 'AI 논문 리뷰의 주장은 어떻게 검증하나요?',
      answer: '정밀 리뷰에서 검증합니다. 정밀 리뷰는 중요한 주장마다 원문 구절을 찾아 직접 인용·의역·추론·미확인으로 구분합니다. 대화에서 기본으로 실행하는 빠른 리뷰는 몇 분 안에 요약하지만 주장 검증 단계는 없습니다.',
    },
    {
      question: '어떤 출처에서 논문을 찾나요?',
      answer: 'arXiv, Google Scholar, OpenAlex, DBLP, Connected Papers와 OpenAlex의 한국어 논문 필터를 함께 찾습니다. 출처마다 응답 범위가 달라 질문과 검색 시점에 따라 결과가 달라질 수 있습니다.',
    },
    {
      question: '누구에게 적합한 연구 도구인가요?',
      answer: '새 주제의 핵심 논문을 찾는 연구자와 대학원생, 여러 방법론을 비교하는 리서치 엔지니어, 논문의 주장을 실제 근거와 대조해야 하는 독자에게 맞습니다.',
    },
  ],
};
