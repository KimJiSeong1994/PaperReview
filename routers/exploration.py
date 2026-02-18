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

from .deps import get_current_user, limiter, load_bookmarks, modify_bookmarks
from .exploration_service import generate_citation_tree

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

    # Save to bookmark
    with modify_bookmarks() as store:
        bm = _find_bookmark(store, bookmark_id, username)
        bm["citation_tree"] = tree_data

    return {"success": True, "citation_tree": tree_data}


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
