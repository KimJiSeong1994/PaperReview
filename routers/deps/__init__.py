"""
Shared dependencies and global state for all routers.

Centralises agent instances, config, and session storage so that
every router module can import from one place.

This package re-exports all public names so that existing imports
of the form ``from .deps import X`` continue to work unchanged.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

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


# ── Event-driven foundation bootstrap (US-008) ────────────────────────
#
# Runs at module import so that the event bus singleton and the
# backing SQLite DBs are ready before any router handler receives a
# request. Failures are logged but never propagated — if the event
# pipeline cannot be initialised, the server should still boot and
# serve traffic (graceful degradation: no events captured).
def _bootstrap_event_infrastructure() -> None:
    """Ensure events/profile DBs exist and init the event bus singleton.

    Reads ``EVENTS_DB_PATH`` and ``PROFILE_DB_PATH`` from the environment
    (defaults: ``data/events.db`` and ``data/profile.db``). Runs the
    idempotent schema migrations and initialises the module-level
    :class:`~src.events.event_bus.EventBus` so that ``get_event_bus()``
    resolves anywhere after the import.
    """
    try:
        from src.events.event_bus import init_event_bus
        from src.events.migrations import ensure_events_db, ensure_profile_db

        events_db_path = Path(os.getenv("EVENTS_DB_PATH", "data/events.db"))
        profile_db_path = Path(os.getenv("PROFILE_DB_PATH", "data/profile.db"))

        ensure_events_db(events_db_path)
        ensure_profile_db(profile_db_path)
        init_event_bus(events_db_path)

        logger.info(
            "event infrastructure ready: events_db=%s profile_db=%s",
            events_db_path,
            profile_db_path,
        )
    except Exception:
        # Do NOT crash the server — the rest of the API can still serve
        # traffic with events simply going uncaptured.
        logger.exception(
            "event infrastructure bootstrap failed; continuing without event capture"
        )


_bootstrap_event_infrastructure()
