"""
Per-paper review endpoints:
  POST   /api/bookmarks/{bookmark_id}/papers/{paper_index}/review
  GET    /api/bookmarks/{bookmark_id}/papers/{paper_index}/review
  DELETE /api/bookmarks/{bookmark_id}/papers/{paper_index}/review
  POST   /api/bookmarks/{bookmark_id}/papers/{paper_index}/auto-highlight
  POST   /api/pdf-highlights  (standalone, no bookmark required)
  POST   /api/math-explain    (explain a formula from a PDF)
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .deps import load_bookmarks, modify_bookmarks, get_current_user, get_openai_client
from .llm_cache import get_cached, set_cache
from .highlight_service import (
    CATEGORY_CONFIG,
    PDF_CATEGORY_CONFIG,
    generate_highlights,
    generate_pdf_highlights as generate_pdf_highlights_llm,
    _find_verbatim_or_fuzzy,
)
from .paper_review_service import generate_paper_review

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["paper-reviews"])


class PaperReviewRequest(BaseModel):
    full_text: Optional[str] = None
    abstract: Optional[str] = None
    review_mode: str = "fast"


class PdfHighlightRequest(BaseModel):
    """Request body for standalone PDF text highlight extraction."""

    text: str
    title: str = ""


def _get_bookmark_paper(bookmark_id: str, paper_index: int, username: str):
    """Load bookmark and validate paper index. Returns (bookmark, paper) or raises HTTPException."""
    data = load_bookmarks()
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id:
            if bm.get("username") != username:
                raise HTTPException(status_code=403, detail="Access denied")
            papers = bm.get("papers", [])
            if paper_index < 0 or paper_index >= len(papers):
                raise HTTPException(status_code=400, detail=f"Paper index {paper_index} out of range (0-{len(papers)-1})")
            return bm, papers[paper_index]
    raise HTTPException(status_code=404, detail="Bookmark not found")


@router.post("/bookmarks/{bookmark_id}/papers/{paper_index}/review")
def create_paper_review(
    bookmark_id: str,
    paper_index: int,
    request: PaperReviewRequest,
    username: str = Depends(get_current_user),
):
    """Generate a structured review for a single paper within a bookmark."""
    from openai import APITimeoutError, RateLimitError, APIError

    # Phase 1: Read and validate
    bookmark, paper = _get_bookmark_paper(bookmark_id, paper_index, username)

    # Build paper input for LLM
    paper_input = {
        "title": paper.get("title", ""),
        "authors": paper.get("authors", []),
        "year": paper.get("year", ""),
    }
    if request.full_text:
        paper_input["full_text"] = request.full_text
    elif request.abstract:
        paper_input["abstract"] = request.abstract
    elif paper.get("abstract"):
        paper_input["abstract"] = paper["abstract"]

    if not paper_input.get("full_text") and not paper_input.get("abstract") and not paper_input.get("title"):
        raise HTTPException(status_code=400, detail="No reviewable content: provide full_text, abstract, or at least a title")

    # Phase 2: LLM call (no lock held)
    client = get_openai_client()
    try:
        review = generate_paper_review(paper_input, client)
    except APITimeoutError:
        raise HTTPException(status_code=504, detail="Review generation timed out. Please retry.")
    except RateLimitError:
        raise HTTPException(status_code=429, detail="Rate limited. Please wait and retry.")
    except APIError as e:
        raise HTTPException(status_code=502, detail=f"LLM service error: {e.message}")
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Phase 2b: Auto-highlight on the review markdown
    highlights = []
    review_md = review.get("detailed_review_markdown", "")
    if review_md and len(review_md) > 50:
        try:
            llm_highlights = generate_highlights(
                review_md,
                paper_input.get("title", ""),
                paper_input.get("title", ""),
                client,
            )
            # Process highlights (same logic as bookmarks.py auto_highlight_bookmark)
            valid_categories = set(CATEGORY_CONFIG.keys())
            for item in llm_highlights:
                text = item.get("text", "").strip()
                category = item.get("category", "finding")
                if category not in valid_categories:
                    category = "finding"
                reviewer_comment = item.get("reviewer_comment", "").strip()
                if not reviewer_comment:
                    reviewer_comment = item.get("reason", "").strip()
                implication = item.get("implication", "").strip()
                strength_or_weakness = item.get("strength_or_weakness", "").strip().lower()
                if strength_or_weakness not in ("strength", "weakness"):
                    strength_or_weakness = ""
                question_for_authors = item.get("question_for_authors", "").strip()
                try:
                    confidence_level = max(1, min(5, int(float(item.get("confidence_level", 3)))))
                except (ValueError, TypeError):
                    confidence_level = 3
                try:
                    significance = max(1, min(5, int(float(item.get("significance", 3)))))
                except (ValueError, TypeError):
                    significance = 3
                section = item.get("section", "")

                if not text or len(text) < 5:
                    continue
                matched_text = _find_verbatim_or_fuzzy(text, review_md)
                if not matched_text:
                    continue

                cfg = CATEGORY_CONFIG[category]
                memo = f"{cfg['label']} {reviewer_comment}" if reviewer_comment else cfg["label"]

                highlights.append({
                    "id": f"rhl_{uuid.uuid4().hex[:12]}",
                    "text": matched_text,
                    "color": cfg["color"],
                    "memo": memo,
                    "category": category,
                    "significance": significance,
                    "section": section,
                    "implication": implication,
                    "strength_or_weakness": strength_or_weakness,
                    "question_for_authors": question_for_authors,
                    "confidence_level": confidence_level,
                    "created_at": datetime.now().isoformat(),
                })
        except Exception as e:
            logger.warning("Auto-highlight during review creation failed: %s", e)
            # Non-fatal: review still saved without highlights

    # Phase 3: Atomic write
    with modify_bookmarks() as data:
        for bm in data["bookmarks"]:
            if bm["id"] == bookmark_id and bm.get("username") == username:
                papers = bm.get("papers", [])
                if paper_index < len(papers):
                    papers[paper_index]["review"] = review
                    papers[paper_index]["review_highlights"] = highlights
                break

    return {
        "success": True,
        "review": review,
        "highlights": highlights,
        "highlight_count": len(highlights),
    }


@router.get("/bookmarks/{bookmark_id}/papers/{paper_index}/review")
async def get_paper_review(
    bookmark_id: str,
    paper_index: int,
    username: str = Depends(get_current_user),
):
    """Retrieve cached review for a paper."""
    _, paper = _get_bookmark_paper(bookmark_id, paper_index, username)
    review = paper.get("review")
    if not review:
        raise HTTPException(status_code=404, detail="No review found for this paper")
    return {
        "review": review,
        "highlights": paper.get("review_highlights", []),
    }


@router.delete("/bookmarks/{bookmark_id}/papers/{paper_index}/review")
async def delete_paper_review(
    bookmark_id: str,
    paper_index: int,
    username: str = Depends(get_current_user),
):
    """Remove a per-paper review."""
    # Validate first
    _get_bookmark_paper(bookmark_id, paper_index, username)

    with modify_bookmarks() as data:
        for bm in data["bookmarks"]:
            if bm["id"] == bookmark_id and bm.get("username") == username:
                papers = bm.get("papers", [])
                if paper_index < len(papers):
                    papers[paper_index].pop("review", None)
                    papers[paper_index].pop("review_highlights", None)
                break

    return {"success": True}


@router.post("/bookmarks/{bookmark_id}/papers/{paper_index}/auto-highlight")
def auto_highlight_paper_review(
    bookmark_id: str,
    paper_index: int,
    username: str = Depends(get_current_user),
):
    """Re-run auto-highlight on an existing per-paper review."""
    from openai import APITimeoutError, RateLimitError, APIError

    # Phase 1: Read and validate
    _, paper = _get_bookmark_paper(bookmark_id, paper_index, username)
    review = paper.get("review")
    if not review:
        raise HTTPException(status_code=400, detail="No review exists for this paper. Create a review first.")

    review_md = review.get("detailed_review_markdown", "")
    if not review_md.strip():
        raise HTTPException(status_code=400, detail="Review has no detailed markdown content")

    title = paper.get("title", "")

    # Phase 2: LLM call
    client = get_openai_client()
    try:
        llm_highlights = generate_highlights(review_md, title, title, client)
    except APITimeoutError:
        raise HTTPException(status_code=504, detail="LLM analysis timed out. Please retry.")
    except RateLimitError:
        raise HTTPException(status_code=429, detail="Rate limited. Please wait and retry.")
    except APIError as e:
        raise HTTPException(status_code=502, detail=f"LLM service error: {e.message}")
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Phase 3: Process and save highlights
    existing_highlights: list = []
    added_count = 0
    enriched_count = 0

    with modify_bookmarks() as data:
        for bm in data["bookmarks"]:
            if bm["id"] == bookmark_id and bm.get("username") == username:
                papers = bm.get("papers", [])
                if paper_index >= len(papers):
                    break
                target_paper = papers[paper_index]
                target_review_md = target_paper.get("review", {}).get("detailed_review_markdown", "")

                existing_highlights = list(target_paper.get("review_highlights", []))
                existing_by_text = {h["text"]: i for i, h in enumerate(existing_highlights)}
                added_count = 0
                enriched_count = 0
                valid_categories = set(CATEGORY_CONFIG.keys())

                for item in llm_highlights:
                    text = item.get("text", "").strip()
                    category = item.get("category", "finding")
                    if category not in valid_categories:
                        category = "finding"
                    reviewer_comment = item.get("reviewer_comment", "").strip()
                    if not reviewer_comment:
                        reviewer_comment = item.get("reason", "").strip()
                    implication = item.get("implication", "").strip()
                    strength_or_weakness = item.get("strength_or_weakness", "").strip().lower()
                    if strength_or_weakness not in ("strength", "weakness"):
                        strength_or_weakness = ""
                    question_for_authors = item.get("question_for_authors", "").strip()
                    try:
                        confidence_level = max(1, min(5, int(float(item.get("confidence_level", 3)))))
                    except (ValueError, TypeError):
                        confidence_level = 3
                    try:
                        significance = max(1, min(5, int(float(item.get("significance", 3)))))
                    except (ValueError, TypeError):
                        significance = 3
                    section = item.get("section", "")

                    if not text or len(text) < 5:
                        continue
                    matched_text = _find_verbatim_or_fuzzy(text, target_review_md)
                    if not matched_text:
                        continue

                    cfg = CATEGORY_CONFIG[category]
                    memo = f"{cfg['label']} {reviewer_comment}" if reviewer_comment else cfg["label"]

                    # Enrich existing or add new
                    existing_idx = existing_by_text.get(text) if text in existing_by_text else existing_by_text.get(matched_text)
                    if existing_idx is not None:
                        existing_hl = existing_highlights[existing_idx]
                        enriched = False
                        if implication and not existing_hl.get("implication"):
                            existing_hl["implication"] = implication
                            enriched = True
                        if section and not existing_hl.get("section"):
                            existing_hl["section"] = section
                            enriched = True
                        if significance and not existing_hl.get("significance"):
                            existing_hl["significance"] = significance
                            enriched = True
                        if not existing_hl.get("category"):
                            existing_hl["category"] = category
                            existing_hl["color"] = cfg["color"]
                            enriched = True
                        if reviewer_comment and (not existing_hl.get("memo") or existing_hl["memo"] == existing_hl.get("category", "")):
                            existing_hl["memo"] = memo
                            enriched = True
                        if strength_or_weakness and not existing_hl.get("strength_or_weakness"):
                            existing_hl["strength_or_weakness"] = strength_or_weakness
                            enriched = True
                        if question_for_authors and not existing_hl.get("question_for_authors"):
                            existing_hl["question_for_authors"] = question_for_authors
                            enriched = True
                        if confidence_level and not existing_hl.get("confidence_level"):
                            existing_hl["confidence_level"] = confidence_level
                            enriched = True
                        if enriched:
                            enriched_count += 1
                        continue

                    existing_highlights.append({
                        "id": f"rhl_{uuid.uuid4().hex[:12]}",
                        "text": matched_text,
                        "color": cfg["color"],
                        "memo": memo,
                        "category": category,
                        "significance": significance,
                        "section": section,
                        "implication": implication,
                        "strength_or_weakness": strength_or_weakness,
                        "question_for_authors": question_for_authors,
                        "confidence_level": confidence_level,
                        "created_at": datetime.now().isoformat(),
                    })
                    existing_by_text[matched_text] = len(existing_highlights) - 1
                    added_count += 1

                target_paper["review_highlights"] = existing_highlights
                break

    return {
        "success": True,
        "highlights": existing_highlights,
        "added_count": added_count,
        "enriched_count": enriched_count,
    }


@router.post("/pdf-highlights")
def pdf_highlights_endpoint(
    request: PdfHighlightRequest,
    username: str = Depends(get_current_user),
):
    """Extract highlights from raw PDF text for overlay display.

    This endpoint is independent of bookmarks — it takes arbitrary text
    (typically extracted from a PDF via pdfjs) and returns highlight
    spans with category, color, and reviewer commentary.

    Uses the PDF-specific prompt and preprocessing pipeline for better
    accuracy on academic paper text.
    """
    from openai import APIError, APITimeoutError, RateLimitError

    text = request.text.strip()
    if not text or len(text) < 50:
        raise HTTPException(
            status_code=400,
            detail="PDF text is too short to generate meaningful highlights.",
        )

    title = request.title.strip()

    client = get_openai_client()
    try:
        llm_highlights = generate_pdf_highlights_llm(text, title, client)
    except APITimeoutError:
        raise HTTPException(
            status_code=504,
            detail="LLM analysis timed out. Please retry.",
        )
    except RateLimitError:
        raise HTTPException(
            status_code=429,
            detail="Rate limited. Please wait and retry.",
        )
    except APIError as e:
        raise HTTPException(
            status_code=502,
            detail=f"LLM service error: {e.message}",
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))

    highlights: list[dict] = []
    valid_categories = set(PDF_CATEGORY_CONFIG.keys())

    for item in llm_highlights:
        raw_text = item.get("text", "").strip()
        category = item.get("category", "finding")
        if category not in valid_categories:
            category = "finding"

        reviewer_comment = item.get("reviewer_comment", "").strip()
        if not reviewer_comment:
            reviewer_comment = item.get("reason", "").strip()

        implication = item.get("implication", "").strip()
        strength_or_weakness = item.get("strength_or_weakness", "").strip().lower()
        if strength_or_weakness not in ("strength", "weakness"):
            strength_or_weakness = ""
        question_for_authors = item.get("question_for_authors", "").strip()

        try:
            confidence_level = max(
                1, min(5, int(float(item.get("confidence_level", 3))))
            )
        except (ValueError, TypeError):
            confidence_level = 3
        try:
            significance = max(
                1, min(5, int(float(item.get("significance", 3))))
            )
        except (ValueError, TypeError):
            significance = 3

        section = item.get("section", "")

        if not raw_text or len(raw_text) < 5:
            continue

        # For PDF overlay we try to match against the full text
        matched_text = _find_verbatim_or_fuzzy(raw_text, text)
        if not matched_text:
            # Keep original text even if not matched verbatim — the
            # frontend will attempt its own fuzzy matching.
            matched_text = raw_text

        cfg = PDF_CATEGORY_CONFIG[category]
        memo = (
            f"{cfg['label']} {reviewer_comment}"
            if reviewer_comment
            else cfg["label"]
        )

        highlights.append({
            "id": f"phl_{uuid.uuid4().hex[:12]}",
            "text": matched_text,
            "color": cfg["color"],
            "memo": memo,
            "category": category,
            "significance": significance,
            "section": section,
            "implication": implication,
            "strength_or_weakness": strength_or_weakness,
            "question_for_authors": question_for_authors,
            "confidence_level": confidence_level,
            "created_at": datetime.now().isoformat(),
        })

    return {"highlights": highlights}


# ── Math formula explanation ────────────────────────────────────────


class MathExplainRequest(BaseModel):
    """Request body for explaining a math formula extracted from a PDF."""

    formula_text: str
    context: str = ""
    paper_title: str = ""


_MATH_EXPLAIN_SYSTEM = """You are a math tutor explaining formulas from academic papers.
Given a formula and its surrounding context, provide:
1. A clear explanation of what the formula computes
2. The meaning of each variable/symbol
3. The type of formula (loss function, probability, optimization, definition, theorem, other)

Respond in JSON format:
{
  "explanation": "1-3 sentences explaining the formula in plain language",
  "variables": [{"symbol": "x", "meaning": "input features"}, ...],
  "formula_type": "loss function | probability | optimization | definition | theorem | other"
}

Keep explanations concise. Match the language of the paper context."""

_MATH_MODEL = "gpt-4.1"
_MATH_TEMPERATURE = 0.2


@router.post("/math-explain")
def explain_math_formula(
    request: MathExplainRequest,
    username: str = Depends(get_current_user),
) -> dict:
    """Explain a math formula extracted from a PDF paper.

    Sends the formula text and surrounding context to an LLM and returns
    a structured explanation with variable definitions and formula type.
    Uses file-based LLM cache to avoid repeated calls for the same formula.
    """
    from openai import APIError, APITimeoutError, RateLimitError

    formula_text = request.formula_text.strip()
    if not formula_text:
        raise HTTPException(status_code=400, detail="formula_text is required")

    context = request.context.strip()
    paper_title = request.paper_title.strip()

    # Build user prompt
    parts: list[str] = []
    if paper_title:
        parts.append(f"Paper: {paper_title}")
    parts.append(f"Formula: {formula_text}")
    if context:
        parts.append(f"Context: {context}")
    user_prompt = "\n".join(parts)

    # Check LLM cache
    cached = get_cached(_MATH_EXPLAIN_SYSTEM, user_prompt, _MATH_MODEL, _MATH_TEMPERATURE)
    if cached is not None:
        try:
            return json.loads(cached)
        except (json.JSONDecodeError, TypeError):
            pass  # stale/corrupt cache entry — regenerate

    client = get_openai_client()
    try:
        response = client.chat.completions.create(
            model=_MATH_MODEL,
            messages=[
                {"role": "system", "content": _MATH_EXPLAIN_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=_MATH_TEMPERATURE,
            timeout=30,
            response_format={"type": "json_object"},
        )
    except APITimeoutError:
        raise HTTPException(status_code=504, detail="Formula explanation timed out. Please retry.")
    except RateLimitError:
        raise HTTPException(status_code=429, detail="Rate limited. Please wait and retry.")
    except APIError as e:
        raise HTTPException(status_code=502, detail=f"LLM service error: {e.message}")

    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise HTTPException(status_code=502, detail="LLM returned an empty response")

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Math explain: failed to parse LLM JSON: %s", content[:200])
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON")

    # Normalise shape — ensure expected keys exist
    explanation = result.get("explanation", "")
    variables: list[dict[str, str]] = []
    for v in result.get("variables", []):
        if isinstance(v, dict) and v.get("symbol"):
            variables.append({"symbol": v["symbol"], "meaning": v.get("meaning", "")})
    formula_type = result.get("formula_type", "other")

    normalised: dict = {
        "explanation": explanation,
        "variables": variables,
        "formula_type": formula_type,
    }

    # Persist to cache
    set_cache(_MATH_EXPLAIN_SYSTEM, user_prompt, _MATH_MODEL, _MATH_TEMPERATURE, json.dumps(normalised, ensure_ascii=False))

    return normalised
