"""
LightRAG endpoints:
  POST /api/light-rag/build
  POST /api/light-rag/query
  GET  /api/light-rag/status
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from .deps import get_light_rag_agent, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["lightrag"])


# ── Pydantic models ───────────────────────────────────────────────────

class LightRAGBuildRequest(BaseModel):
    max_concurrent: int = 4
    extraction_model: str = "gpt-4o-mini"


class LightRAGQueryRequest(BaseModel):
    query: str
    mode: str = "hybrid"  # naive, local, global, hybrid, mix
    top_k: int = 10
    temperature: float = 0.7


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/light-rag/build")
async def light_rag_build(request: LightRAGBuildRequest, background_tasks: BackgroundTasks, username: str = Depends(get_current_user)):
    """Build LightRAG knowledge graph (background task)."""

    def _build():
        try:
            agent = get_light_rag_agent()
            agent.build_knowledge_graph(
                max_concurrent=request.max_concurrent,
                extraction_model=request.extraction_model,
            )
            logger.info("Knowledge graph build complete")
        except Exception as e:
            logger.error("Build error: %s", e)

    background_tasks.add_task(_build)
    return {
        "status": "building",
        "message": "Knowledge graph build started in background",
        "config": {
            "max_concurrent": request.max_concurrent,
            "extraction_model": request.extraction_model,
        },
    }


@router.post("/light-rag/query")
async def light_rag_query(request: LightRAGQueryRequest, username: str = Depends(get_current_user)):
    """Execute a LightRAG query."""
    try:
        agent = get_light_rag_agent()
        result = agent.light_query(
            query=request.query,
            mode=request.mode,
            top_k=request.top_k,
            temperature=request.temperature,
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
async def light_rag_status(username: str = Depends(get_current_user)):
    """Check LightRAG knowledge graph status."""
    try:
        agent = get_light_rag_agent()
        stats = agent.get_kg_stats()
        return {"status": "ready", "stats": stats}
    except Exception as e:
        return {"status": "not_built", "error": str(e)}
