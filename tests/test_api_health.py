"""Tests for root and health endpoints."""

import pytest


@pytest.mark.asyncio
async def test_root(client):
    """GET / returns API info."""
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "Paper Review Agent API"
    assert "version" in data


@pytest.mark.asyncio
async def test_health(client):
    """GET /health returns status."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("healthy", "degraded")
    assert "checks" in data
    assert "api" in data["checks"]
