"""
Citation Tree Explorer endpoints:
  POST   /api/bookmarks/{bookmark_id}/citation-tree
  GET    /api/bookmarks/{bookmark_id}/citation-tree
  DELETE /api/bookmarks/{bookmark_id}/citation-tree
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

from .deps import get_current_user, get_optional_user, limiter, load_bookmarks, modify_bookmarks
from .exploration_service import generate_citation_tree
from src.collector.paper.semantic_scholar_client import SemanticScholarClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["exploration"])


# ── Request models ────────────────────────────────────────────────────

class CitationTreeRequest(BaseModel):
    depth: int = Field(default=1, ge=1, le=3)
    max_per_direction: int = Field(default=10, ge=1, le=30)


# ── Helpers ───────────────────────────────────────────────────────────

def _find_bookmark(data: dict, bookmark_id: str, username: str):
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id:
            if bm.get("username") != username:
                raise HTTPException(status_code=403, detail="Access denied")
            return bm
    raise HTTPException(status_code=404, detail="Bookmark not found")


# ── Citation Tree endpoints ───────────────────────────────────────────

@router.post("/bookmarks/{bookmark_id}/citation-tree")
@limiter.limit("5/minute")
def create_citation_tree(
    request: Request,
    bookmark_id: str,
    body: CitationTreeRequest = CitationTreeRequest(),
    username: str = Depends(get_current_user),
):
    """Generate a citation tree for a bookmark's papers."""
    data = load_bookmarks()
    bookmark = _find_bookmark(data, bookmark_id, username)

    papers = bookmark.get("papers", [])
    if not papers:
        raise HTTPException(status_code=400, detail="Bookmark has no papers")

    logger.info("Generating citation tree for bookmark %s (%d papers)", bookmark_id, len(papers))

    try:
        tree_data = generate_citation_tree(
            papers=papers,
            depth=body.depth,
            max_per_direction=body.max_per_direction,
        )
    except Exception as e:
        logger.exception("Citation tree generation failed for %s", bookmark_id)
        raise HTTPException(status_code=502, detail=f"Citation tree generation failed: {e}")

    # Build warning message based on skipped papers
    skipped = tree_data.get("skipped_papers", [])
    warning = None
    if skipped:
        if not tree_data.get("nodes"):
            titles = ", ".join(skipped[:3])
            if len(skipped) > 3:
                titles += f" and {len(skipped) - 3} more"
            warning = f"Could not find on Semantic Scholar: {titles}"
        else:
            warning = f"{len(skipped)} paper(s) could not be found and were excluded."

    # Save to bookmark
    with modify_bookmarks() as store:
        bm = _find_bookmark(store, bookmark_id, username)
        bm["citation_tree"] = tree_data

    result = {"success": True, "citation_tree": tree_data}
    if warning:
        result["warning"] = warning
    return result


@router.get("/bookmarks/{bookmark_id}/citation-tree")
async def get_citation_tree(bookmark_id: str, username: str = Depends(get_current_user)):
    """Retrieve the stored citation tree for a bookmark."""
    data = load_bookmarks()
    bookmark = _find_bookmark(data, bookmark_id, username)

    tree = bookmark.get("citation_tree")
    if not tree:
        raise HTTPException(status_code=404, detail="Citation tree not generated yet")
    return tree


@router.delete("/bookmarks/{bookmark_id}/citation-tree")
async def delete_citation_tree(bookmark_id: str, username: str = Depends(get_current_user)):
    """Delete the stored citation tree for a bookmark."""
    with modify_bookmarks() as data:
        bm = _find_bookmark(data, bookmark_id, username)
        if "citation_tree" not in bm:
            raise HTTPException(status_code=404, detail="No citation tree to delete")
        del bm["citation_tree"]
    return {"success": True}


# ── Semantic Scholar Reader URL ──────────────────────────────────────

@router.get("/s2/reader-url")
async def get_s2_reader_url(
    title: str = "",
    doi: str = "",
    arxiv_id: str = "",
    _username: str = Depends(get_optional_user),
):
    """Resolve a paper to its Semantic Scholar Reader URL.

    Returns the reader URL (https://www.semanticscholar.org/reader/{paperId})
    if the paper is found on Semantic Scholar.
    """
    if not title and not doi and not arxiv_id:
        raise HTTPException(status_code=400, detail="At least one of title, doi, or arxiv_id is required")

    paper = {"title": title, "doi": doi, "arxiv_id": arxiv_id}

    from .exploration_service import _resolve_paper

    s2_client = SemanticScholarClient()
    try:
        resolved = _resolve_paper(paper, s2_client)
        if not resolved:
            return {"reader_url": None, "paper_id": None, "pdf_url": None}

        paper_id = resolved["paperId"]
        reader_url = f"https://www.semanticscholar.org/reader/{paper_id}"

        # Fetch openAccessPdf and externalIds to provide PDF URL
        pdf_url = None
        try:
            base_url = "https://api.semanticscholar.org/graph/v1"
            resp = s2_client.request_with_retry(
                f"{base_url}/paper/{paper_id}",
                params={"fields": "openAccessPdf,externalIds"},
                timeout=15,
            )
            data = resp.json()
            oa_pdf = data.get("openAccessPdf") or {}
            pdf_url = oa_pdf.get("url") or None
            if not pdf_url:
                ext_ids = data.get("externalIds") or {}
                s2_arxiv = ext_ids.get("ArXiv")
                if s2_arxiv:
                    pdf_url = f"https://arxiv.org/pdf/{s2_arxiv.split('v')[0]}.pdf"
        except Exception as e:
            logger.debug("S2 PDF lookup failed for %s: %s", paper_id, e)

        return {"reader_url": reader_url, "paper_id": paper_id, "pdf_url": pdf_url}
    finally:
        s2_client.close()
