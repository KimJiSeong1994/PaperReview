"""
FastAPI backend server for Paper Review Agent.
Provides REST API for React frontend.

All endpoint logic lives in the routers/ package.
This file handles app creation, middleware, and router registration.
"""

import logging
import os
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from middleware import TimingSecurityHeadersMiddleware

# ── Logging setup ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Importing routers triggers deps.py which sets up SSL, env, agents, etc.
from routers import (
    auth_router,
    search_router,
    papers_router,
    reviews_router,
    bookmarks_router,
    paper_reviews_router,
    chat_router,
    lightrag_router,
    admin_router,
    exploration_router,
    share_router,
    curriculum_router,
    pdf_proxy_router,
    autofigure_router,
    blog_router,
    topology_router,
    me_router,
)
from routers.deps import api_key, limiter

# ── App setup ──────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)


def _ensure_faiss_index():
    """Rebuild FAISS index from JSON if the index file is missing."""
    index_path = Path("data/embeddings/paper_embeddings.index")
    json_path = Path("data/embeddings/embeddings.json")

    if index_path.exists():
        logger.info("FAISS index already exists: %s", index_path)
        return

    if not json_path.exists():
        logger.warning("No embeddings JSON found at %s — skipping FAISS rebuild", json_path)
        return

    try:
        from src.graph.embedding_generator import EmbeddingGenerator
        ok = EmbeddingGenerator.rebuild_faiss_from_json(
            json_path=str(json_path),
            output_dir=str(json_path.parent),
        )
        if ok:
            logger.info("FAISS index rebuilt successfully from %s", json_path)
        else:
            logger.warning("FAISS index rebuild returned False")
    except Exception as exc:
        logger.warning("Failed to rebuild FAISS index: %s", exc)


def _warm_cross_encoder() -> None:
    """Pre-load cross-encoder model to avoid HF download on first /api/search.

    Without this, the first search call takes ~49s (30s cross-encoder download
    inside relevance_filter's 30s budget → TimeoutError → fallback to unfiltered).
    After warmup, first search is ~15-20s (dominated by external API latency).

    LocalRelevanceScorer stores the model as a class-level singleton via
    ``get_model()``; calling it here populates ``LocalRelevanceScorer._model``
    so subsequent calls in the request handler find the model already loaded.
    """
    try:
        from app.QueryAgent.relevance_filter import LocalRelevanceScorer
        # get_model() triggers lazy singleton init (downloads model on first call)
        model = LocalRelevanceScorer.get_model()
        if model is not None:
            logger.info("Cross-encoder model warmed up successfully")
        else:
            logger.warning(
                "Cross-encoder warmup: get_model() returned None "
                "(sentence-transformers may not be installed)"
            )
    except Exception as exc:
        logger.warning(
            "Failed to warm cross-encoder: %s — first search may be slow (~30s)",
            exc,
        )


from contextlib import asynccontextmanager
import asyncio


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle.

    On shutdown, the event bus is drained (US-007) with a bounded
    timeout so any batched-but-not-yet-persisted events are flushed to
    SQLite before the ASGI server exits. This guarantees zero event
    loss on SIGTERM for the gunicorn/uvicorn graceful shutdown path.
    """
    _ensure_faiss_index()

    # Pre-warm cross-encoder model to avoid HF download on first /api/search.
    # Run in executor so a slow first-time download doesn't block the event loop.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _warm_cross_encoder)

    # Register the running event loop with the event bus so sync
    # endpoints running in the threadpool can emit events via
    # ``run_coroutine_threadsafe`` (see ``src/events/emit.py`` path (b)).
    # ``register_main_loop`` also starts the background batch flusher
    # that replaces per-event INSERTs with ``executemany`` batches.
    try:
        from src.events.event_bus import get_event_bus
        get_event_bus().register_main_loop(asyncio.get_running_loop())
    except RuntimeError:
        logger.warning(
            "event bus not initialized at lifespan startup; "
            "sync-path event emits will fall back to persist_only",
        )
    except Exception:
        logger.exception("failed to register main loop with event bus")

    yield

    # Shutdown: drain batched events before process exit (US-007).
    try:
        from src.events.event_bus import get_event_bus
        await get_event_bus().wait_for_drain(timeout=5.0)
    except RuntimeError:
        # Bus was never initialized — nothing to drain.
        pass
    except Exception:
        logger.exception("event bus drain failed at shutdown")


app = FastAPI(
    title="Paper Review Agent API",
    description="AI-based academic paper search, review, and analysis system",
    version="1.1.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware - configurable via environment.
# Production default only allows the public domain; local dev servers must
# be explicitly opted in via CORS_ORIGINS (e.g. in .env:
#   CORS_ORIGINS=https://jiphyeonjeon.kr,http://localhost:5173
# ).
_DEFAULT_ORIGINS = "https://jiphyeonjeon.kr,https://www.jiphyeonjeon.kr"
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", _DEFAULT_ORIGINS).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)





# ── Global exception handler ──────────────────────────────────────────


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception on %s %s:\n%s",
        request.method,
        request.url.path,
        traceback.format_exc(),
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ── Request logging / security headers middleware ────────────────────
# Implemented in middleware.py as pure ASGI (NOT BaseHTTPMiddleware) so SSE
# streams are not buffered through anyio memory streams. Added AFTER CORS so
# CORSMiddleware remains the outermost wrapper (Starlette middleware is LIFO).
app.add_middleware(TimingSecurityHeadersMiddleware)


# ── Root & health endpoints ──────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "Paper Review Agent API", "version": "1.1.0"}


# ── MCP capability negotiation ────────────────────────────────────────
from pydantic import BaseModel


class VersionResponse(BaseModel):
    """Server version + capability map consumed by the Jiphyeonjeon MCP server.

    The MCP server calls GET /api/version at startup and registers only the
    tools whose capability appears in ``capabilities``. Older 집현전 servers
    that pre-date this endpoint return 404 and the MCP server falls back to
    its baseline tool set.
    """

    version: str
    capabilities: list[str]
    mcp_min_client: str = "0.1.0"


_API_VERSION = "1.1.0"
_API_CAPABILITIES: list[str] = [
    "search",
    "papers",
    "deep_review",
    "bookmarks",
    "curriculum",
    "explore",
    "autofigure",
    "blog",
]


@app.get("/api/version", response_model=VersionResponse)
async def get_api_version() -> VersionResponse:
    """Return server version + capability flags for MCP/agent clients."""
    return VersionResponse(version=_API_VERSION, capabilities=_API_CAPABILITIES)


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    checks = {
        "api": "ok",
        "openai_key": "configured" if api_key else "missing",
        "data_dir": "ok" if Path("data").exists() else "missing",
        "jwt_secret": "configured" if os.getenv("JWT_SECRET") else "random-fallback",
    }
    # "random-fallback" is acceptable in dev but should trigger warnings in prod monitoring
    _acceptable = ("ok", "configured", "random-fallback")
    status = "healthy" if all(v in _acceptable for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}


# ── Register routers ──────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(search_router)
app.include_router(papers_router)
app.include_router(reviews_router)
app.include_router(bookmarks_router)
app.include_router(paper_reviews_router)
app.include_router(chat_router)
app.include_router(lightrag_router)
app.include_router(admin_router)
app.include_router(exploration_router)
app.include_router(share_router)
app.include_router(curriculum_router)
app.include_router(pdf_proxy_router)
app.include_router(autofigure_router)
app.include_router(blog_router)
app.include_router(topology_router)
app.include_router(me_router)


# ── Entrypoint ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        timeout_keep_alive=120,
        timeout_graceful_shutdown=30,
    )
