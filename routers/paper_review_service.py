"""
Per-paper review generation service.

Generates structured single-paper reviews via a single LLM call.

The prompt layout is optimised for OpenAI automatic prompt caching:
  1. ``messages[0]`` (``system``) is a static, immutable string ≥1024 tokens.
  2. ``messages[1]`` (``user``) starts with a fixed ``PAPER_REVIEW_USER_PREFIX``
     (also cacheable) followed by the variable paper metadata / body.

See ``routers/llm_cache.py`` for the split-key local cache that mirrors the
same prefix/suffix structure.
"""

import json
import logging
from datetime import datetime

from .llm_cache import get_cached, set_cache

logger = logging.getLogger(__name__)

# ── Stable system prompt (≥1024 tokens, immutable) ─────────────────────
#
# All instruction-oriented content lives here. Do NOT interpolate any
# runtime values (paper title, language, author, etc.) into this string —
# doing so breaks OpenAI's automatic prompt cache.

PAPER_REVIEW_SYSTEM_PROMPT = """\
You are a senior reviewer at a top-tier venue (Nature/Science/ICML/NeurIPS/ACL/CVPR).
You have served on program committees for the past fifteen years and have reviewed
papers spanning machine learning, natural language processing, computer vision,
computational biology, and systems research. Your job is to analyse the single
paper supplied in the user message and produce a structured review in JSON format.

Your review must be thorough, specific, and evidence-based. Avoid generic or
boilerplate statements. Every claim you make must be grounded in concrete content
from the paper (methods, numbers, datasets, results, or text quotations).

## Output Schema (strict JSON)
Respond with a single JSON object matching the following shape. Keys must be
present exactly as named; extra keys will be ignored but should not be added.

{
  "summary": "2-3 sentence overview of the paper's contribution",
  "strengths": [
    {"point": "specific strength", "evidence": "supporting detail from the paper", "significance": "high|medium|low"}
  ],
  "weaknesses": [
    {"point": "specific weakness", "evidence": "supporting detail", "severity": "major|minor"}
  ],
  "methodology_assessment": {
    "rigor": <1-5>,
    "novelty": <1-5>,
    "reproducibility": <1-5>,
    "commentary": "2-3 sentences on methodology"
  },
  "key_contributions": ["contribution 1", "contribution 2"],
  "questions_for_authors": ["question 1", "question 2"],
  "overall_score": <1-10>,
  "confidence": <1-5>,
  "detailed_review_markdown": "Full markdown review text (800+ chars). Use ## headings for sections."
}

## Scoring Guide
- overall_score: 1-3 reject, 4-5 borderline, 6-7 accept, 8-10 strong accept.
  Use the full range — do not cluster every paper in the 5-7 band.
- confidence: 1=guess, 2=educated guess, 3=fairly confident, 4=confident, 5=certain.
  Confidence reflects your familiarity with the exact sub-area, not the paper's quality.
- rigor: 1=very poor, 2=poor, 3=adequate, 4=good, 5=excellent. Rigor judges the
  internal validity of the experimental design: baselines, ablations, statistics,
  confounders, and fair comparison.
- novelty: 1=trivial extension of prior work, 2=incremental combination,
  3=meaningful new angle, 4=substantive new contribution, 5=paradigm-shifting.
- reproducibility: 1=not reproducible from the paper, 2=partial code/data,
  3=adequate for an expert reader, 4=good (code + data + configs), 5=fully packaged.

## Extraction and Evidence Rules
- Extract at least 3 strengths and 2 weaknesses. If you cannot find that many,
  state explicitly why a slot was filled with a weaker item.
- Each strength/weakness MUST cite concrete evidence from the paper: a number,
  a method name, a dataset, a section heading, or a direct paraphrase of the
  author's own words. Avoid paraphrases that could apply to any paper in the area.
- The significance/severity axis is distinct from the point itself — a valid
  strength can be "minor" in impact, and a well-argued weakness can be "major"
  even if the paper only mentions it in passing.
- Do not fabricate author names, citation numbers, benchmarks, or quantitative
  results that are not present in the provided paper content. If the paper
  content was truncated, acknowledge the gap rather than inventing details.

## Methodology Commentary
The ``commentary`` field in ``methodology_assessment`` should cover, in 2-3
sentences, the single biggest methodological strength and the single biggest
methodological concern. It must not repeat the summary and it must not list
the three numeric scores — those are already in the adjacent fields.

## Questions for Authors
Generate 2-4 questions that a reviewer would realistically raise in a rebuttal
thread. Each question must be specific enough that the authors could answer
it by running an additional experiment, quoting a prior result, or clarifying
an assumption. Avoid open-ended prompts ("have you considered X?") — prefer
operational questions ("under what conditions does X degrade to baseline?").

## detailed_review_markdown Requirements
- Minimum 800 characters of body text (not counting headings).
- Use ## headings for at least these sections: Summary, Strengths, Weaknesses,
  Questions, Overall Assessment. Additional sections (e.g. Related Work
  Comparison, Reproducibility Notes) are encouraged when the paper warrants them.
- The markdown should stand alone as a review document — a reader who does not
  see the JSON summary should still be able to follow your evaluation.
- Cite specific sections, tables, or figures using the numbering the paper uses
  itself (e.g. "Section 4.2", "Table 3"). Do not invent numbering.

## Language Policy
Write the review in the same language as the paper content. If the paper is
primarily in Korean, produce the summary, strengths, weaknesses, and
``detailed_review_markdown`` in Korean. If the paper is in English, respond
in English. Mixed-language papers should be reviewed in the language of the
abstract.

## Style and Boilerplate Ban
The following phrases are forbidden anywhere in the output. Each one signals
a lazy review and will be rejected during quality assurance:
- "this is an interesting approach"
- "further research is needed"
- "the paper presents novel work"
- "results look promising"
- "additional validation would strengthen the paper"

Replace every such phrase with a concrete statement that names the object
("the proposed contrastive objective"), the comparison ("versus the
cross-entropy baseline in Table 2"), and the consequence ("which would
clarify whether the 3.2% gain generalises beyond ImageNet-1k"). If you
cannot state the object, comparison, and consequence, the observation is
not specific enough to include.

## Output Discipline
Return ONLY the JSON object described above. Do not prepend a preamble, do
not wrap the JSON in Markdown fences, and do not append commentary after
the closing brace. The response must parse with ``json.loads`` on the
first attempt.
"""

# ── Fixed user-message prefix (cacheable along with the system prompt) ──
#
# This prefix is appended to every user message BEFORE the variable paper
# body. Keep it byte-stable.

PAPER_REVIEW_USER_PREFIX = """\
You will now receive a single academic paper. Produce the JSON review
described in the system instructions.

Follow these runtime reminders:
- Apply the scoring rubric strictly. Do not inflate ``overall_score`` just
  because the paper is well-written.
- Fill every JSON field. If the paper truly lacks the information required
  for a field, use an empty list or a brief string explaining the gap
  rather than omitting the key.
- Keep ``summary`` at 2-3 sentences and avoid repeating it verbatim inside
  ``detailed_review_markdown``.
- Remember the language policy from the system prompt: match the paper's
  primary language.

=== PAPER CONTENT ===
"""


def _build_variable_user_body(paper: dict) -> tuple[str, str]:
    """Return ``(variable_body, input_type)`` for the given paper.

    The body contains the per-call variable text (title, authors, abstract /
    full text). It does not include the fixed ``PAPER_REVIEW_USER_PREFIX``.
    """
    parts: list[str] = []
    parts.append(f"# Paper: {paper.get('title', 'Unknown')}")
    if paper.get("authors"):
        authors = paper["authors"]
        if isinstance(authors, list):
            parts.append(f"**Authors**: {', '.join(authors)}")
        else:
            parts.append(f"**Authors**: {authors}")
    if paper.get("year"):
        parts.append(f"**Year**: {paper['year']}")

    input_type = "metadata"
    if paper.get("full_text"):
        text = paper["full_text"]
        # Truncate to ~30K chars to fit context
        if len(text) > 30000:
            text = text[:30000] + "\n\n[... truncated ...]"
        parts.append(f"\n## Full Text\n{text}")
        input_type = "full_text"
    elif paper.get("abstract"):
        parts.append(f"\n## Abstract\n{paper['abstract']}")
        input_type = "abstract"

    return "\n".join(parts), input_type


def generate_paper_review(
    paper: dict,
    client,
    model: str = "gpt-4.1",
) -> dict:
    """Generate a structured per-paper review using a single LLM call.

    The call is structured so that the prefix
    ``system + PAPER_REVIEW_USER_PREFIX`` is byte-identical across
    invocations, which lets OpenAI's automatic prompt cache reuse it (and
    lets :mod:`routers.llm_cache` key on the variable tail only).

    Args:
        paper: Paper dict with title, authors, year, abstract, full_text (optional).
        client: OpenAI-compatible client instance.
        model: LLM model name.

    Returns:
        Structured review dict matching the output schema.

    Raises:
        openai.APITimeoutError, openai.RateLimitError, openai.APIError, ValueError
    """
    variable_body, input_type = _build_variable_user_body(paper)
    user_prompt = f"{PAPER_REVIEW_USER_PREFIX}{variable_body}"
    temperature = 0.3

    # Check cache (split-key: (system + fixed prefix) vs. variable body)
    cached = get_cached(
        PAPER_REVIEW_SYSTEM_PROMPT,
        user_prompt,
        model,
        temperature,
        fixed_prefix=PAPER_REVIEW_USER_PREFIX,
    )
    if cached is not None:
        logger.info("Using cached LLM response for paper review")
        raw = cached
    else:
        # Scale timeout by input length
        timeout = 120 if input_type == "full_text" else 90
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            timeout=timeout,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": PAPER_REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        logger.info("Paper review token usage: %s", response.usage)
        raw = response.choices[0].message.content or "{}"
        set_cache(
            PAPER_REVIEW_SYSTEM_PROMPT,
            user_prompt,
            model,
            temperature,
            raw,
            fixed_prefix=PAPER_REVIEW_USER_PREFIX,
        )

    try:
        review = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("LLM returned invalid JSON for paper review")

    # Add metadata
    review["created_at"] = datetime.now().isoformat()
    review["model"] = model
    review["input_type"] = input_type

    return review
