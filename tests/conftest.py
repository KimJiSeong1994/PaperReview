"""Shared test fixtures for the Paper Review Agent backend."""

import os
import socket
import sys
from pathlib import Path

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set test environment variables before importing app
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key-for-testing")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-testing-only")
os.environ.setdefault("APP_PASSWORD", "test-admin-password")
os.environ.setdefault("APP_USERNAME", "test-admin")

_TEST_JWT_SECRET = os.environ["JWT_SECRET"]


@pytest.fixture(autouse=True)
def isolate_mcp_analytics_storage(tmp_path, monkeypatch):
    """No test may persist measurements or deletion tombstones in app data."""
    monkeypatch.setenv("MCP_ANALYTICS_DB_PATH", str(tmp_path / "mcp_analytics.db"))


# Bound every socket operation so a slow/unreachable external API (OpenAlex,
# arXiv, Semantic Scholar, Scholar, DBLP, GitHub, …) can never hang the suite —
# this is what stalled CI for ~40 min. Unlike hard-blocking, a short default
# timeout preserves the real code path (the paper searchers make their call and
# gracefully degrade on a slow one), so real-pipeline tests keep passing; it
# just caps a multi-minute stall at a few seconds. In-process ASGI (httpx
# ASGITransport) and SQLite use no sockets and are unaffected. Opt out with
# ALLOW_TEST_NETWORK=1 for a deliberate integration run.
if os.environ.get("ALLOW_TEST_NETWORK") != "1":
    socket.setdefaulttimeout(float(os.environ.get("TEST_SOCKET_TIMEOUT", "8")))


def _make_test_token(username: str = "test-admin", role: str = "admin") -> str:
    """Create a JWT token for testing."""
    from datetime import datetime, timedelta, timezone
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture
def auth_headers() -> dict:
    """Return Authorization headers with a valid admin JWT.

    ``get_current_user`` and ``get_admin_user`` now verify that the JWT
    subject still exists in the user DB (so a deleted account cannot
    keep using its old token).  We register the test-admin user here
    so every test receiving ``auth_headers`` passes that check.
    """
    from routers.deps.storage import _get_user_db

    db = _get_user_db()
    if db.get("test-admin") is None:
        db.upsert(
            "test-admin",
            {"password_hash": "test-hash", "role": "admin", "created_at": ""},
        )
    else:
        # Ensure role is admin even if a prior test downgraded the record.
        record = db.get("test-admin") or {}
        if record.get("role") != "admin":
            record["role"] = "admin"
            db.upsert("test-admin", record)

    token = _make_test_token()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app():
    """Create a fresh FastAPI app for testing."""
    from api_server import app as _app
    return _app


@pytest.fixture
async def client(app):
    """Async HTTP client for testing API endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
