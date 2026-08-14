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

from app.DeepAgent.poster.result_contract import (
    CODE_RATE_LIMITED,
    new_generation_id,
)

# Importing routers triggers deps.py which sets up SSL, env, agents, etc.
from routers import (
    auth_router,
    analytics_router,
    search_router,
    papers_router,
    reviews_router,
    bookmarks_router,
    paper_reviews_router,
    chat_router,
    lightrag_router,
    admin_router,
    admin_analytics_router,
    exploration_router,
    share_router,
    curriculum_router,
    pdf_proxy_router,
    autofigure_router,
    blog_router,
    topology_router,
    me_router,
    recommendations_router,
    seo_router,
)
from routers.deps import api_key, limiter
from routers.indexnow import (
    INDEXNOW_ENABLED,
    published_urls as indexnow_published_urls,
    router as indexnow_router,
    submit_async as indexnow_submit_async,
)
from routers.search import (
    start_search_background_workers,
    stop_search_background_workers,
)

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
        from transformers.utils.logging import (
            disable_progress_bar,
            enable_progress_bar,
            is_progress_bar_enabled,
        )

        # get_model() triggers lazy singleton init (downloads model on first call)
        progress_bars_were_enabled = is_progress_bar_enabled()
        try:
            disable_progress_bar()
            model = LocalRelevanceScorer.get_model()
        finally:
            if progress_bars_were_enabled:
                enable_progress_bar()
            else:
                disable_progress_bar()

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

    try:
        # Notify IndexNow (Bing/Yandex/…) of public URLs on startup/deploy so
        # git-based blog edits get picked up without an API call.
        if INDEXNOW_ENABLED:
            indexnow_submit_async(indexnow_published_urls())

        start_search_background_workers()
        yield
    finally:
        try:
            if not stop_search_background_workers():
                logger.warning("search background workers did not stop before timeout")
        except Exception:
            logger.exception("search background worker shutdown failed")

        # Shutdown: drain batched events before process exit (US-007).
        try:
            from src.events.event_bus import get_event_bus

            await get_event_bus().wait_for_drain(timeout=5.0)
        except RuntimeError:
            # Bus was never initialized — nothing to drain.
            pass
        except Exception:
            logger.exception("event bus drain failed at shutdown")

        # Shutdown: close the module-level httpx.AsyncClient singleton so the
        # TCP connection pool and keepalive sockets are released before the
        # ASGI server exits (F-35).  Without this, SIGTERM on a rolling deploy
        # leaks file descriptors until the interpreter is reaped.
        try:
            from routers.pdf_proxy import close_http_client

            await close_http_client()
        except Exception:
            logger.exception("http client close failed at shutdown")


app = FastAPI(
    title="Paper Review Agent API",
    description="AI-based academic paper search, review, and analysis system",
    version="1.1.0",
    lifespan=lifespan,
)


def _is_poster_rate_limited_path(path: str) -> bool:
    return (
        path.startswith("/api/deep-review/visualize/")
        or path == "/api/deep-review/visualize-direct"
        or path == "/api/autofigure/generate-poster-figures"
    )


async def poster_aware_rate_limit_handler(
    request: Request,
    exc: RateLimitExceeded,
):
    path = request.url.path
    if not _is_poster_rate_limited_path(path):
        return _rate_limit_exceeded_handler(request, exc)

    return JSONResponse(
        status_code=429,
        content={
            "detail": {
                "poster_status": "failed",
                "status": "failed",
                "success": False,
                "error_code": CODE_RATE_LIMITED,
                "retryable": True,
                "generation_id": new_generation_id(),
            }
        },
    )


# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, poster_aware_rate_limit_handler)

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
    "recommendations",
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
app.include_router(analytics_router)
app.include_router(search_router)
app.include_router(papers_router)
app.include_router(reviews_router)
app.include_router(bookmarks_router)
app.include_router(paper_reviews_router)
app.include_router(chat_router)
app.include_router(lightrag_router)
app.include_router(admin_router)
app.include_router(admin_analytics_router)
app.include_router(exploration_router)
app.include_router(share_router)
app.include_router(curriculum_router)
app.include_router(pdf_proxy_router)
app.include_router(autofigure_router)
app.include_router(blog_router)
app.include_router(indexnow_router)
app.include_router(topology_router)
app.include_router(me_router)
app.include_router(recommendations_router)
app.include_router(seo_router)


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
