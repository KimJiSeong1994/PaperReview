"""
Shared dependencies and global state for all routers.

Centralises agent instances, config, and session storage so that
every router module can import from one place.
"""

import os
import sys
import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import certifi
from filelock import FileLock

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
    print("[WARNING] No OpenAI API key found in environment")

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
            print("[INFO] Query analyzer initialized")
        except Exception as e:
            print(f"[WARNING] Could not initialize query analyzer: {e}")
            query_analyzer = None

        try:
            relevance_filter = RelevanceFilter(api_key=api_key)
            print("[INFO] Relevance filter initialized")
        except Exception as e:
            print(f"[WARNING] Could not initialize relevance filter: {e}")
            relevance_filter = None
    except Exception as e:
        print(f"[WARNING] Could not initialize query analyzer/filter: {e}")
else:
    print("[WARNING] No OpenAI API key - query analysis and relevance filtering disabled")

# ── Review session storage (shared between reviews & bookmarks) ────────
review_sessions: Dict[str, Dict[str, Any]] = {}
review_sessions_lock = threading.Lock()

# ── Bookmarks file & helpers ──────────────────────────────────────────
BOOKMARKS_FILE = Path("data/bookmarks.json")
_bookmarks_lock = FileLock(str(BOOKMARKS_FILE) + ".lock")


def load_bookmarks() -> dict:
    """Load bookmarks from JSON file (thread-safe)."""
    with _bookmarks_lock:
        if BOOKMARKS_FILE.exists():
            with open(BOOKMARKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"bookmarks": []}


def save_bookmarks(data: dict):
    """Save bookmarks to JSON file (thread-safe, atomic write)."""
    with _bookmarks_lock:
        BOOKMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = BOOKMARKS_FILE.with_suffix(".json.tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_file.replace(BOOKMARKS_FILE)


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
