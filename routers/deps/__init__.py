"""
Shared dependencies and global state for all routers.

Centralises agent instances, config, and session storage so that
every router module can import from one place.

This package re-exports all public names so that existing imports
of the form ``from .deps import X`` continue to work unchanged.
"""

# ── Config (base — no deps imports) ──────────────────────────────────
from .config import (
    PROJECT_ROOT,
    api_key,
    env_path,
    DEFAULT_RESEARCH_MODEL,
    DEFAULT_TOOL_MODEL,
    DEFAULT_EVAL_MODEL,
)

# ── Storage (depends on config) ──────────────────────────────────────
from .storage import (
    BOOKMARKS_FILE,
    PAPERS_FILE,
    USERS_FILE,
    _bookmarks_lock,
    _papers_lock,
    _users_lock,
    load_bookmarks,
    load_users,
    modify_bookmarks,
    modify_users,
    review_sessions,
    review_sessions_lock,
    save_bookmarks,
    save_users,
)

# ── Auth (depends on config) ─────────────────────────────────────────
from .auth import (
    _JWT_ALGORITHM,
    _JWT_SECRET,
    _decode_jwt,
    get_admin_user,
    get_current_user,
    get_optional_user,
)

# ── Middleware (standalone) ──────────────────────────────────────────
from .middleware import API_AUTH_KEY, limiter, verify_api_key

# ── Agents (depends on config) ──────────────────────────────────────
from .agents import query_analyzer, relevance_filter, search_agent

# ── OpenAI / LightRAG singletons (standalone) ───────────────────────
from .openai_client import get_light_rag_agent, get_openai_client

# ── Run migrations on import (same behaviour as original deps.py) ────
from .migrations import _migrate_bookmarks_add_username, _migrate_papers_add_searched_by, _fix_username_typo

_migrate_bookmarks_add_username()
_migrate_papers_add_searched_by()
_fix_username_typo()
