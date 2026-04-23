"""
LightRAG endpoints:
  POST /api/light-rag/build
  POST /api/light-rag/query
  GET  /api/light-rag/status
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from starlette.requests import Request

from .deps import get_light_rag_agent, get_current_user, limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["lightrag"])


# ── Pydantic models ───────────────────────────────────────────────────

class LightRAGBuildRequest(BaseModel):
    max_concurrent: int = 4
    extraction_model: str = "gpt-4o-mini"


from enum import Enum as _Enum


class LightRAGMode(str, _Enum):
    naive = "naive"
    local = "local"
    global_ = "global"
    hybrid = "hybrid"
    mix = "mix"


class LightRAGQueryRequest(BaseModel):
    query: str
    mode: LightRAGMode = LightRAGMode.hybrid
    top_k: int = 10
    temperature: float = 0.7


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/light-rag/build")
@limiter.limit("10/minute")
async def light_rag_build(
    request: Request,
    payload: LightRAGBuildRequest,
    background_tasks: BackgroundTasks,
    username: str = Depends(get_current_user),
):
    """Build LightRAG knowledge graph (background task).

    F-34: IP rate-limited to 10/min — builds queue LLM extraction for the
    whole paper corpus; without a cap an authenticated user can tie up
    the worker and burn unbounded extraction_model credits.
    """

    def _build():
        try:
            agent = get_light_rag_agent()
            agent.build_knowledge_graph(
                max_concurrent=payload.max_concurrent,
                extraction_model=payload.extraction_model,
            )
            logger.info("Knowledge graph build complete")
        except Exception as e:
            logger.error("Build error: %s", e)

    background_tasks.add_task(_build)
    return {
        "status": "building",
        "message": "Knowledge graph build started in background",
        "config": {
            "max_concurrent": payload.max_concurrent,
            "extraction_model": payload.extraction_model,
        },
    }


@router.post("/light-rag/query")
@limiter.limit("10/minute")
async def light_rag_query(
    request: Request,
    payload: LightRAGQueryRequest,
    username: str = Depends(get_current_user),
):
    """Execute a LightRAG query.

    F-34: IP rate-limited to 10/min — each call runs an LLM query over
    the knowledge graph.
    """
    try:
        agent = get_light_rag_agent()
        result = agent.light_query(
            query=payload.query,
            mode=payload.mode.value,
            top_k=payload.top_k,
            temperature=payload.temperature,
        )
        return result
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Knowledge graph not found. Run /api/light-rag/build first.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LightRAG query failed: {str(e)}")


@router.get("/light-rag/status")
@limiter.limit("30/minute")
async def light_rag_status(
    request: Request,
    username: str = Depends(get_current_user),
):
    """Check LightRAG knowledge graph status.

    F-34: IP rate-limited to 30/min (read-only status probe).
    """
    try:
        agent = get_light_rag_agent()
        stats = agent.get_kg_stats()
        return {"status": "ready", "stats": stats}
    except Exception as e:
        return {"status": "not_built", "error": str(e)}
