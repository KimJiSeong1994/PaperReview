"""Personal soul endpoints (USER.md profile + memories).

  GET    /api/me/soul                  profile, memories and rendered markdown
  PUT    /api/me/soul                  replace the USER.md profile
  DELETE /api/me/soul/memories/{id}    forget one memory
  DELETE /api/me/soul                  forget everything
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.storage.soul_db import MAX_USER_MD, render_markdown
from .deps.auth import AuthenticatedPrincipal, get_authenticated_principal
from .deps.storage import _get_soul_db

router = APIRouter(prefix="/api/me/soul", tags=["soul"])


class UserMdRequest(BaseModel):
    user_md: str = Field(max_length=MAX_USER_MD)


@router.get("")
async def get_soul(principal: AuthenticatedPrincipal = Depends(get_authenticated_principal)):
    """Return the caller's profile, memories and the rendered USER.md/MEMORY.md text."""
    soul = _get_soul_db().get_soul(principal.username, principal.account_incarnation)
    return {
        "user_md": soul["user_md"],
        "memories": [{k: m[k] for k in ("id", "kind", "text", "created_at")} for m in soul["memories"]],
        "markdown": render_markdown(soul),
    }


@router.put("")
async def put_user_md(body: UserMdRequest, principal: AuthenticatedPrincipal = Depends(get_authenticated_principal)):
    """Replace the caller's USER.md profile."""
    return {"user_md": _get_soul_db().set_user_md(principal.username, principal.account_incarnation, body.user_md)}


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, principal: AuthenticatedPrincipal = Depends(get_authenticated_principal)):
    """Forget one of the caller's memories."""
    if not _get_soul_db().delete_memory(memory_id, principal.username, principal.account_incarnation):
        raise HTTPException(status_code=404, detail="메모리를 찾을 수 없습니다")
    return {"ok": True}


@router.delete("")
async def clear_soul(principal: AuthenticatedPrincipal = Depends(get_authenticated_principal)):
    """Forget the caller's profile and all memories."""
    return {"deleted": _get_soul_db().clear(principal.username, principal.account_incarnation)}
