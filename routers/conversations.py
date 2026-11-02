"""Conversational home endpoints.

  POST /api/conversations                  create (stores the first user turn)
  POST /api/conversations/{id}/turns       run the next assistant turn (SSE)
  GET  /api/me/conversations               caller's recent conversations
  GET  /api/conversations/{id}             conversation with turns
  POST /api/conversations/{id}/archive     hide from the list
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.assistant import turn_runner
from .deps.auth import AuthenticatedPrincipal, get_authenticated_principal
from .deps.middleware import limiter
from .deps.storage import _get_conversation_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["conversations"])

KEEPALIVE_INTERVAL_SEC = 15.0
_TURN_FIELDS = ("id", "seq", "role", "content", "blocks", "intent", "status", "created_at")

# conversation_id → running turn task. Holds a strong reference so a turn keeps
# running after its client disconnects, and lets a new message cancel it.
_running_turns: Dict[str, asyncio.Task] = {}


class CreateConversationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class TurnRequest(BaseModel):
    message: Optional[str] = Field(default=None, min_length=1, max_length=2000)


def _owned(conversation_id: str, principal: AuthenticatedPrincipal) -> Dict[str, Any]:
    """Return the caller's conversation or raise 404 (missing and foreign look alike)."""
    conv = _get_conversation_db().get_conversation(
        conversation_id, principal.username, principal.account_incarnation
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다")
    return conv


@router.post("/conversations", status_code=201)
async def create_conversation(
    body: CreateConversationRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    """Create a conversation titled after the first message and store that user turn."""
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="메시지가 비어 있습니다")
    db = _get_conversation_db()
    conv = db.create_conversation(principal.username, principal.account_incarnation, message[:60].strip())
    turn = db.append_turn(conv["id"], "user", message)
    return {"id": conv["id"], "title": conv["title"], "turn_id": turn["id"]}


@router.post("/conversations/{conversation_id}/turns")
@limiter.limit("20/minute")
async def run_turn(
    request: Request,
    conversation_id: str,
    body: TurnRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    """Optionally add a user message, then stream the assistant turn answering it.

    400 when the last user turn already has a (done or running) answer; a
    turn that ended in ``error`` may be re-run by posting without a message.
    A new message while a turn is running cancels it (stored as error "중단됨").
    """
    db = _get_conversation_db()
    turns = _owned(conversation_id, principal)["turns"]
    # ponytail: check-then-append is race-free only because no await runs in
    # between on the single server process; move into one SQL transaction if
    # the server ever runs multiple workers.
    if body.message is not None and body.message.strip():
        last = turns[-1] if turns else None
        if last and last["role"] == "assistant" and last["status"] == "running":
            # A new message supersedes the running answer (the client's stop
            # button only closes its connection).
            running = _running_turns.pop(conversation_id, None)
            if running is not None:
                running.cancel()
            db.finish_turn(last["id"], "중단됨", [], None, "error", None, None)
            last["status"] = "error"
        turns.append(db.append_turn(conversation_id, "user", body.message.strip()))
    last_user = next((i for i in range(len(turns) - 1, -1, -1) if turns[i]["role"] == "user"), None)
    if last_user is None:
        raise HTTPException(status_code=400, detail="답변할 메시지가 없습니다")
    if any(t["status"] in ("done", "running") for t in turns[last_user + 1:]):
        raise HTTPException(status_code=400, detail="이미 답변했거나 답변 중인 메시지입니다")
    history = [t for t in turns[: last_user + 1] if t["status"] != "error"]
    turn_id = db.append_turn(conversation_id, "assistant", "", status="running")["id"]

    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(
        turn_runner.run_turn(db, conversation_id, turn_id, principal, history, queue.put_nowait)
    )
    _running_turns[conversation_id] = task
    task.add_done_callback(
        lambda t: _running_turns.pop(conversation_id, None) if _running_turns.get(conversation_id) is t else None
    )

    async def event_stream():
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL_SEC)
            except asyncio.TimeoutError:
                if task.done() and queue.empty():
                    # run_turn always emits a terminal event; this only guards a crash.
                    yield f"data: {json.dumps({'error': '응답이 중단되었습니다.'}, ensure_ascii=False)}\n\n"
                    return
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if "done" in event or "error" in event:
                return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/me/conversations")
async def list_my_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    """List the caller's non-archived conversations, newest first."""
    return _get_conversation_db().list_conversations(
        principal.username, principal.account_incarnation, limit
    )


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    """Return one conversation with its ordered turns."""
    conv = _owned(conversation_id, principal)
    return {
        "id": conv["id"],
        "title": conv["title"],
        "created_at": conv["created_at"],
        "updated_at": conv["updated_at"],
        "turns": [{k: t[k] for k in _TURN_FIELDS} for t in conv["turns"]],
    }


@router.post("/conversations/{conversation_id}/archive")
async def archive_conversation(
    conversation_id: str,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
):
    """Archive the caller's conversation."""
    if not _get_conversation_db().archive(conversation_id, principal.username, principal.account_incarnation):
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다")
    return {"ok": True}
