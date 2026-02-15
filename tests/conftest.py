"""Shared test fixtures for the Paper Review Agent backend."""

import os
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set test environment variables before importing app
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key-for-testing")


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
