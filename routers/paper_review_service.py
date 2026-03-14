"""
Per-paper review generation service.

Generates structured single-paper reviews via a single LLM call.
"""

import json
import logging
from datetime import datetime

from .llm_cache import get_cached, set_cache

logger = logging.getLogger(__name__)

PAPER_REVIEW_SYSTEM_PROMPT = """\
You are a senior reviewer at a top-tier venue (Nature/Science/ICML/NeurIPS/ACL).
Analyze the given paper and produce a structured review in JSON format.

Your review must be thorough, specific, and evidence-based. Avoid generic or boilerplate statements.

## Output Schema (strict JSON)
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
- overall_score: 1-3 reject, 4-5 borderline, 6-7 accept, 8-10 strong accept
- confidence: 1=guess, 2=educated guess, 3=fairly confident, 4=confident, 5=certain
- rigor/novelty/reproducibility: 1=very poor, 2=poor, 3=adequate, 4=good, 5=excellent

## Guidelines
- Extract at least 3 strengths and 2 weaknesses
- Be specific — reference concrete methods, results, or claims
- detailed_review_markdown should be a standalone review document with sections like Summary, Strengths, Weaknesses, Questions, Overall Assessment
- Write the review in the same language as the paper content (Korean if Korean, English if English)
"""


def generate_paper_review(
    paper: dict,
    client,
    model: str = "gpt-4.1",
) -> dict:
    """Generate a structured per-paper review using a single LLM call.

    Args:
        paper: Paper dict with title, authors, year, abstract, full_text (optional).
        client: OpenAI-compatible client instance.
        model: LLM model name.

    Returns:
        Structured review dict matching the output schema.

    Raises:
        openai.APITimeoutError, openai.RateLimitError, openai.APIError, ValueError
    """
    # Build user prompt from available paper content
    parts = []
    parts.append(f"# Paper: {paper.get('title', 'Unknown')}")
    if paper.get("authors"):
        authors = paper["authors"]
        if isinstance(authors, list):
            parts.append(f"**Authors**: {', '.join(authors)}")
        else:
            parts.append(f"**Authors**: {authors}")
    if paper.get("year"):
        parts.append(f"**Year**: {paper['year']}")

    # Determine input type
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

    user_prompt = "\n".join(parts)
    temperature = 0.3

    # Check cache
    cached = get_cached(PAPER_REVIEW_SYSTEM_PROMPT, user_prompt, model, temperature)
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
        set_cache(PAPER_REVIEW_SYSTEM_PROMPT, user_prompt, model, temperature, raw)

    try:
        review = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("LLM returned invalid JSON for paper review")

    # Add metadata
    review["created_at"] = datetime.now().isoformat()
    review["model"] = model
    review["input_type"] = input_type

    return review
