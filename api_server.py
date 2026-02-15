"""
FastAPI backend server for Paper Review Agent.
Provides REST API for React frontend.

All endpoint logic lives in the routers/ package.
This file handles app creation, middleware, and router registration.
"""

import os
from pathlib import Path

from fastapi import FastAPI
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
    chat_router,
    lightrag_router,
    admin_router,
)
from routers.deps import api_key, limiter

# ── App setup ──────────────────────────────────────────────────────────
app = FastAPI(
    title="Paper Review Agent API",
    description="AI-based academic paper search, review, and analysis system",
    version="1.1.0",
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware - configurable via environment
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Root & health endpoints ──────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "Paper Review Agent API", "version": "1.1.0"}


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    checks = {
        "api": "ok",
        "openai_key": "configured" if api_key else "missing",
        "data_dir": "ok" if Path("data").exists() else "missing",
    }
    status = "healthy" if all(v in ("ok", "configured") for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}


# ── Register routers ──────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(search_router)
app.include_router(papers_router)
app.include_router(reviews_router)
app.include_router(bookmarks_router)
app.include_router(chat_router)
app.include_router(lightrag_router)
app.include_router(admin_router)


# ── Entrypoint ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
