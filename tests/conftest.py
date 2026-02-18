"""Shared test fixtures for the Paper Review Agent backend."""

import os
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
    """Return Authorization headers with a valid admin JWT."""
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
