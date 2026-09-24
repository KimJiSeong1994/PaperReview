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


@pytest.mark.asyncio
async def test_health_attests_loaded_revision_without_rereading_git(monkeypatch):
    import os
    import api_server

    revision = "a" * 40
    monkeypatch.setattr(api_server, "_DEPLOYMENT_REVISION", revision)

    def forbidden(*args, **kwargs):
        raise AssertionError("health must not report the mutable checkout revision")

    monkeypatch.setattr(api_server.subprocess, "run", forbidden)
    result = await api_server.health_check()
    assert result["deployment_revision"] == revision
    assert result["process_id"] == os.getpid()


def test_unknown_revision_is_explicit_when_git_is_unavailable(monkeypatch):
    import api_server

    def unavailable(*args, **kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(api_server.subprocess, "run", unavailable)
    assert api_server._deployment_revision() == "unknown"
