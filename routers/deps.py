"""
Shared dependencies and global state for all routers.

Centralises agent instances, config, and session storage so that
every router module can import from one place.
"""

import logging
import os
import secrets
import sys
import json
import threading
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import certifi
from filelock import FileLock

logger = logging.getLogger(__name__)

# SSL: certifi CA bundle (macOS certificate issue)
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

from dotenv import load_dotenv

# ── Project paths ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "src"))
sys.path.append(str(PROJECT_ROOT / "app" / "SearchAgent"))
sys.path.append(str(PROJECT_ROOT / "app" / "QueryAgent"))

# .env
env_path = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# ── OpenAI API Key ─────────────────────────────────────────────────────
api_key: Optional[str] = (
    os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY") or os.getenv("OPENAI_API")
)
if not api_key:
    logger.warning("No OpenAI API key found in environment")

# ── Agent instances ────────────────────────────────────────────────────
from search_agent import SearchAgent
from query_analyzer import QueryAnalyzer
from relevance_filter import RelevanceFilter

search_agent = SearchAgent(openai_api_key=api_key)

query_analyzer: Optional[QueryAnalyzer] = None
relevance_filter: Optional[RelevanceFilter] = None

if api_key:
    try:
        try:
            query_analyzer = QueryAnalyzer(api_key=api_key)
            logger.info("Query analyzer initialized")
        except Exception as e:
            logger.warning("Could not initialize query analyzer: %s", e)
            query_analyzer = None

        try:
            relevance_filter = RelevanceFilter(api_key=api_key)
            logger.info("Relevance filter initialized")
        except Exception as e:
            logger.warning("Could not initialize relevance filter: %s", e)
            relevance_filter = None
    except Exception as e:
        logger.warning("Could not initialize query analyzer/filter: %s", e)
else:
    logger.warning("No OpenAI API key - query analysis and relevance filtering disabled")

# ── Review session storage (shared between reviews & bookmarks) ────────
review_sessions: Dict[str, Dict[str, Any]] = {}
review_sessions_lock = threading.Lock()

# ── Bookmarks file & helpers ──────────────────────────────────────────
BOOKMARKS_FILE = Path("data/bookmarks.json")
_bookmarks_lock = FileLock(str(BOOKMARKS_FILE) + ".lock")


def load_bookmarks() -> dict:
    """Load bookmarks from JSON file (thread-safe)."""
    with _bookmarks_lock:
        if not BOOKMARKS_FILE.exists():
            return {"bookmarks": []}
        try:
            with open(BOOKMARKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            backup = BOOKMARKS_FILE.with_suffix(".json.corrupt")
            BOOKMARKS_FILE.rename(backup)
            logger.error("Corrupt bookmarks file backed up to %s: %s", backup, e)
            return {"bookmarks": []}


def save_bookmarks(data: dict):
    """Save bookmarks to JSON file (thread-safe, atomic write)."""
    with _bookmarks_lock:
        BOOKMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = BOOKMARKS_FILE.with_suffix(".json.tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_file.replace(BOOKMARKS_FILE)


@contextmanager
def modify_bookmarks():
    """Atomically read-modify-write bookmarks under a single lock.

    Only saves if the block completes without exception.
    Usage:
        with modify_bookmarks() as data:
            data["bookmarks"].append(new_bm)
            # auto-saved on exit
    """
    with _bookmarks_lock:
        if BOOKMARKS_FILE.exists():
            with open(BOOKMARKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {"bookmarks": []}
        try:
            yield data
        except Exception:
            raise
        else:
            BOOKMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = BOOKMARKS_FILE.with_suffix(".json.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp_file.replace(BOOKMARKS_FILE)


# ── Users file & helpers (shared by auth + admin) ────────────────────
USERS_FILE = Path(__file__).resolve().parent.parent / "data" / "users.json"
_users_lock = FileLock(str(USERS_FILE) + ".lock")


def load_users() -> dict:
    """Load users from JSON file (thread-safe)."""
    with _users_lock:
        if not USERS_FILE.exists():
            return {}
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            backup = USERS_FILE.with_suffix(".json.corrupt")
            USERS_FILE.rename(backup)
            logger.error("Corrupt users file backed up to %s: %s", backup, e)
            return {}


def save_users(users: dict) -> None:
    """Save users to JSON file (thread-safe, atomic write)."""
    with _users_lock:
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = USERS_FILE.with_suffix(".json.tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
        tmp_file.replace(USERS_FILE)


@contextmanager
def modify_users():
    """Atomically read-modify-write users under a single lock."""
    with _users_lock:
        if USERS_FILE.exists():
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                users = json.load(f)
        else:
            users = {}
        try:
            yield users
        except Exception:
            raise
        else:
            USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = USERS_FILE.with_suffix(".json.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(users, f, indent=2, ensure_ascii=False)
            tmp_file.replace(USERS_FILE)


# ── Papers file helpers ──────────────────────────────────────────────
PAPERS_FILE = Path("data/raw/papers.json")
_papers_lock = FileLock(str(PAPERS_FILE) + ".lock")


# ── Rate limiting ────────────────────────────────────────────────────
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# ── Optional API key auth ────────────────────────────────────────────
from fastapi import HTTPException
from starlette.requests import Request

API_AUTH_KEY = os.getenv("API_AUTH_KEY", "")


async def verify_api_key(request: Request):
    """Verify API key if API_AUTH_KEY is configured."""
    if not API_AUTH_KEY:
        return  # Auth disabled
    auth_header = request.headers.get("X-API-Key", "")
    if auth_header != API_AUTH_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ── LightRAG singleton ────────────────────────────────────────────────
_light_rag_agent = None


# ── OpenAI client singleton ──────────────────────────────────────────
_openai_client = None


def get_openai_client():
    """Return (and lazily create) the singleton OpenAI client."""
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(timeout=120.0)
        logger.info("OpenAI client initialized (timeout=120s)")
    return _openai_client


# ── JWT user extraction ─────────────────────────────────────────────
import jwt as _pyjwt

_JWT_SECRET = os.getenv("JWT_SECRET")
if not _JWT_SECRET:
    _JWT_SECRET = secrets.token_hex(32)
    logger.warning("JWT_SECRET not set! Using random secret — tokens will NOT persist across restarts.")
    logger.warning("Set JWT_SECRET env var for production.")
_JWT_ALGORITHM = "HS256"


def _decode_jwt(request: Request) -> dict:
    """Extract and decode JWT from Authorization header. Returns full payload."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[len("Bearer "):]
    try:
        payload = _pyjwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except _pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except _pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return payload


async def get_current_user(request: Request) -> str:
    """Extract and validate JWT from Authorization header. Returns username."""
    payload = _decode_jwt(request)
    return payload["sub"]


async def get_admin_user(request: Request) -> str:
    """Like get_current_user but requires admin role. Returns username."""
    payload = _decode_jwt(request)
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload["sub"]


async def get_optional_user(request: Request) -> Optional[str]:
    """Extract username from JWT if present, return None otherwise (no auth required)."""
    try:
        payload = _decode_jwt(request)
        return payload.get("sub")
    except HTTPException:
        return None


# ── Bookmark migration: add username to existing bookmarks ──────────
def _migrate_bookmarks_add_username():
    """One-time: assign existing bookmarks without username to the default admin."""
    default_user = os.getenv("APP_USERNAME", "Jipyheonjeon")
    with _bookmarks_lock:
        if not BOOKMARKS_FILE.exists():
            return
        with open(BOOKMARKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        needs_save = False
        for bm in data.get("bookmarks", []):
            if "username" not in bm:
                bm["username"] = default_user
                needs_save = True

        if needs_save:
            tmp_file = BOOKMARKS_FILE.with_suffix(".json.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp_file.replace(BOOKMARKS_FILE)
            logger.info("Assigned existing bookmarks to user '%s'", default_user)


_migrate_bookmarks_add_username()


# ── Paper migration: add searched_by to existing papers ──────────


def _migrate_papers_add_searched_by():
    """One-time: assign existing papers without searched_by to the default admin."""
    default_user = os.getenv("APP_USERNAME", "Jipyheonjeon")
    if not PAPERS_FILE.exists():
        return
    try:
        with _papers_lock:
            with open(PAPERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            needs_save = False
            for paper in data.get("papers", []):
                if "searched_by" not in paper:
                    paper["searched_by"] = default_user
                    needs_save = True

            if needs_save:
                tmp_file = PAPERS_FILE.with_suffix(".json.tmp")
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                tmp_file.replace(PAPERS_FILE)
                logger.info("Assigned existing papers to user '%s'", default_user)
    except Exception as e:
        logger.warning("Paper migration warning: %s", e)


_migrate_papers_add_searched_by()


# ── LightRAG singleton ────────────────────────────────────────────────
def get_light_rag_agent():
    """Return (and lazily create) the singleton LightRAG agent."""
    global _light_rag_agent
    if _light_rag_agent is None:
        from app.GraphRAG.rag_agent import GraphRAGAgent

        _light_rag_agent = GraphRAGAgent(
            papers_json_path="data/raw/papers.json",
            graph_path="data/graph/paper_graph.pkl",
            light_rag_dir="data/light_rag",
        )
    return _light_rag_agent
