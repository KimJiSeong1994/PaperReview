"""
FastAPI backend server for Paper Review Agent.
Provides REST API for React frontend.

All endpoint logic lives in the routers/ package.
This file handles app creation, middleware, and router registration.
"""

import logging
import os
import time
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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


from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    _ensure_faiss_index()
    yield


app = FastAPI(
    title="Paper Review Agent API",
    description="AI-based academic paper search, review, and analysis system",
    version="1.1.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware - configurable via environment
_DEFAULT_ORIGINS = "https://jiphyeonjeon.kr,http://localhost:5173,http://localhost:5174"
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


# ── Request logging middleware ────────────────────────────────────────

# Per-request timeout (seconds) — configurable via REQUEST_TIMEOUT env var
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "120"))


_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log request duration, warn on slow requests, and inject security headers."""
    start = time.perf_counter()
    response = await call_next(request)
    for hdr, val in _SECURITY_HEADERS.items():
        response.headers[hdr] = val
    duration_ms = (time.perf_counter() - start) * 1000
    duration_s = duration_ms / 1000
    if duration_s > REQUEST_TIMEOUT:
        logger.warning(
            "Slow request (%ds limit exceeded): %s %s → %s (%.1fms)",
            REQUEST_TIMEOUT,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
    else:
        logger.debug(
            "%s %s → %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
    return response


# ── Root & health endpoints ──────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "Paper Review Agent API", "version": "1.1.0"}


@app.get("/debug/db-status")
async def debug_db_status():
    """Temporary: check DB file states without auth. Remove after debugging."""
    import sqlite3 as _sql
    data_dir = Path("data")

    def _count(db: str, table: str) -> int:
        p = data_dir / db
        if not p.exists():
            return -1
        try:
            c = _sql.connect(str(p))
            n = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
            c.close()
            return n
        except Exception:
            return -2

    def _distinct(db: str, table: str, col: str) -> list:
        p = data_dir / db
        if not p.exists():
            return []
        try:
            c = _sql.connect(str(p))
            rows = c.execute(f"SELECT DISTINCT {col} FROM {table}").fetchall()  # noqa: S608
            c.close()
            return [r[0] for r in rows]
        except Exception:
            return []

    return {
        "bookmarks_count": _count("bookmarks.db", "bookmarks"),
        "users_count": _count("users.db", "users"),
        "papers_count": _count("papers.db", "papers"),
        "bookmark_usernames": _distinct("bookmarks.db", "bookmarks", "username"),
        "registered_usernames": _distinct("users.db", "users", "username"),
        "files_exist": {
            "bookmarks.db": (data_dir / "bookmarks.db").exists(),
            "users.db": (data_dir / "users.db").exists(),
            "bookmarks.json": (data_dir / "bookmarks.json").exists(),
            "bookmarks.json.migrated": (data_dir / "bookmarks.json.migrated").exists(),
            "users.json": (data_dir / "users.json").exists(),
        },
    }


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
