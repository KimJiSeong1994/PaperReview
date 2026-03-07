"""Comprehensive tests for authentication endpoints (register, login, verify)."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from filelock import FileLock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_username(prefix: str = "testuser") -> str:
    """Generate a unique username for test isolation."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_users_file(tmp_path):
    """Isolate user storage to a temp file for every test."""
    uf = tmp_path / "users.json"
    uf.write_text(json.dumps({}))
    with patch("routers.deps.USERS_FILE", uf), \
         patch("routers.deps.storage.USERS_FILE", uf), \
         patch("routers.deps._users_lock", FileLock(str(uf) + ".lock")), \
         patch("routers.deps.storage._users_lock", FileLock(str(uf) + ".lock")):
        yield uf


@pytest.fixture(autouse=True)
def disable_rate_limiter(app):
    """Disable slowapi rate limiting during tests to avoid flaky failures."""
    app.state.limiter.enabled = False
    yield
    app.state.limiter.enabled = True


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------

class TestRegister:
    """POST /api/auth/register"""

    async def test_register_success(self, client):
        """Register a new user and verify 200 response with expected body."""
        username = _unique_username()
        resp = await client.post(
            "/api/auth/register",
            json={"username": username, "password": "securepass"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Account created successfully"
        assert data["username"] == username

    async def test_register_duplicate(self, client):
        """Registering the same username twice returns 409."""
        username = _unique_username()
        resp1 = await client.post(
            "/api/auth/register",
            json={"username": username, "password": "pass1234"},
        )
        assert resp1.status_code == 200

        resp2 = await client.post(
            "/api/auth/register",
            json={"username": username, "password": "pass5678"},
        )
        assert resp2.status_code == 409
        assert "already exists" in resp2.json()["detail"].lower()

    async def test_register_short_username(self, client):
        """Username shorter than 3 characters returns 422."""
        resp = await client.post(
            "/api/auth/register",
            json={"username": "ab", "password": "validpass"},
        )
        assert resp.status_code == 422

    async def test_register_short_password(self, client):
        """Password shorter than 4 characters returns 422."""
        resp = await client.post(
            "/api/auth/register",
            json={"username": _unique_username(), "password": "abc"},
        )
        assert resp.status_code == 422

    async def test_register_invalid_username_chars(self, client):
        """Username with special characters (not alphanumeric/_) returns 422."""
        for bad_name in ["user@name", "user name", "user!!", "user.dot", "user-dash"]:
            resp = await client.post(
                "/api/auth/register",
                json={"username": bad_name, "password": "validpass"},
            )
            assert resp.status_code == 422, f"Expected 422 for username '{bad_name}'"


# ---------------------------------------------------------------------------
# Login tests
# ---------------------------------------------------------------------------

class TestLogin:
    """POST /api/auth/login"""

    async def test_login_success(self, client):
        """Register then login; verify token, username, and role are returned."""
        username = _unique_username()
        password = "goodpassword"

        # Register
        resp = await client.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )
        assert resp.status_code == 200

        # Login
        resp = await client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["username"] == username
        assert data["role"] == "user"  # newly registered users are regular users

    async def test_login_wrong_password(self, client):
        """Login with wrong password returns 401."""
        username = _unique_username()
        await client.post(
            "/api/auth/register",
            json={"username": username, "password": "correct"},
        )

        resp = await client.post(
            "/api/auth/login",
            json={"username": username, "password": "wrong"},
        )
        assert resp.status_code == 401
        assert "invalid credentials" in resp.json()["detail"].lower()

    async def test_login_nonexistent_user(self, client):
        """Login with an unknown username returns 401."""
        resp = await client.post(
            "/api/auth/login",
            json={"username": "nobody_here_12345", "password": "whatever"},
        )
        assert resp.status_code == 401
        assert "invalid credentials" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Token verification tests
# ---------------------------------------------------------------------------

class TestVerifyToken:
    """GET /api/auth/verify?token=xxx"""

    async def test_verify_valid_token(self, client):
        """A freshly obtained token is valid."""
        username = _unique_username()
        password = "verifyme"
        await client.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )
        login_resp = await client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        token = login_resp.json()["access_token"]

        resp = await client.get("/api/auth/verify", params={"token": token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["username"] == username
        assert data["role"] == "user"

    async def test_verify_expired_token(self, client):
        """An expired JWT returns 401."""
        from tests.conftest import _TEST_JWT_SECRET
        secret = _TEST_JWT_SECRET
        payload = {
            "sub": "expired_user",
            "role": "user",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        expired_token = jwt.encode(payload, secret, algorithm="HS256")

        resp = await client.get("/api/auth/verify", params={"token": expired_token})
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    async def test_verify_invalid_token(self, client):
        """A garbage string as token returns 401."""
        resp = await client.get(
            "/api/auth/verify", params={"token": "this.is.not.a.jwt"}
        )
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Role-based access tests
# ---------------------------------------------------------------------------

class TestRoleBasedAccess:
    """Verify admin vs regular user access on /api/admin endpoints."""

    async def _register_and_login(self, client, username: str, password: str) -> str:
        """Helper: register a user, log in, and return the access token."""
        await client.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )
        resp = await client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        return resp.json()["access_token"]

    async def test_admin_access(self, client):
        """An admin token can access /api/admin/dashboard."""
        # conftest._make_test_token creates an admin token signed with
        # the same JWT_SECRET the test app uses.
        from tests.conftest import _make_test_token

        admin_token = _make_test_token(username="admin_tester", role="admin")
        headers = {"Authorization": f"Bearer {admin_token}"}

        resp = await client.get("/api/admin/dashboard", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_users" in data
        assert "total_papers" in data

    async def test_user_cannot_access_admin(self, client):
        """A regular user token gets 403 on admin-only endpoints."""
        username = _unique_username("regularuser")
        token = await self._register_and_login(client, username, "userpass1")
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.get("/api/admin/dashboard", headers=headers)
        assert resp.status_code == 403
        assert "admin" in resp.json()["detail"].lower()
