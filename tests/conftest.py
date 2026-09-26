"""Shared test fixtures for the Paper Review Agent backend."""

import os
import ipaddress
import socket
import sys
import tempfile
import threading
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

# Collection-time imports must not restore workspaces or initialize account
# lifecycles against the developer's application data.
_TEST_DATA_ROOT = tempfile.TemporaryDirectory(prefix="paperreview-tests-")
os.environ["DATA_DIR"] = _TEST_DATA_ROOT.name
os.environ["EVENTS_DB_PATH"] = str(Path(_TEST_DATA_ROOT.name) / "events.db")
os.environ["PROFILE_DB_PATH"] = str(Path(_TEST_DATA_ROOT.name) / "profile.db")
os.environ["FEATURE_FLAGS_DB_PATH"] = str(
    Path(_TEST_DATA_ROOT.name) / "feature_flags.db"
)
os.environ["RECOMMENDATIONS_ARTIFACTS_DIR"] = str(
    Path(_TEST_DATA_ROOT.name) / "recommendations"
)

_TEST_JWT_SECRET = os.environ["JWT_SECRET"]

# The optional Scholar client otherwise reads a repository-local pickle during
# construction, before API fixtures can isolate their stores.
from src.collector.paper import google_scholar_searcher as _scholar_module
from src.collector.paper import similarity_calculator as _similarity_module

_similarity_module._DEFAULT_CACHE_DB = Path(_TEST_DATA_ROOT.name) / "embedding-cache.db"

_original_cookie_loader = _scholar_module.GoogleScholarSearcher._load_cookies
_repository_cookie_path = Path(_scholar_module.__file__).with_name(
    ".google_scholar_cookies.pkl"
)


def _load_isolated_scholar_cookies(searcher):
    if searcher.cookies_file == _repository_cookie_path:
        searcher.cookies_file = Path(os.environ["DATA_DIR"]) / "scholar-cookies.pkl"
    return _original_cookie_loader(searcher)


_scholar_module.GoogleScholarSearcher._load_cookies = _load_isolated_scholar_cookies


@pytest.fixture(autouse=True)
def isolate_private_app_storage(tmp_path, monkeypatch, request):
    """Keep real authorization checks, but give every API test its own store."""
    data_dir = tmp_path / "app-data"
    monkeypatch.setattr(
        _similarity_module, "_DEFAULT_CACHE_DB", data_dir / "embedding-cache.db"
    )
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("EVENTS_DB_PATH", str(data_dir / "events.db"))
    monkeypatch.setenv("PROFILE_DB_PATH", str(data_dir / "profile.db"))
    monkeypatch.setenv("FEATURE_FLAGS_DB_PATH", str(data_dir / "feature_flags.db"))
    monkeypatch.setenv(
        "RECOMMENDATIONS_ARTIFACTS_DIR", str(data_dir / "recommendations")
    )
    if "routers.deps.storage" not in sys.modules and {
        "app",
        "client",
        "auth_headers",
    }.intersection(request.fixturenames):
        import api_server  # noqa: F401
    storage = sys.modules.get("routers.deps.storage")
    if storage is not None:
        for name, path in {
            "DATA_DIR": data_dir,
            "USERS_FILE": data_dir / "users.json",
            "BOOKMARKS_FILE": data_dir / "bookmarks.json",
            "PAPERS_FILE": data_dir / "raw" / "papers.json",
            "WORKSPACE_DIR": data_dir / "workspace",
        }.items():
            monkeypatch.setattr(storage, name, path)
    papers = sys.modules.get("routers.papers")
    if papers is not None:
        from src.storage.paper_db import PaperDB

        monkeypatch.setattr(papers, "_paper_db", PaperDB(data_dir / "papers.db"))


@pytest.fixture(autouse=True)
def isolate_mcp_analytics_storage(tmp_path, monkeypatch):
    """No test may persist measurements or deletion tombstones in app data."""
    monkeypatch.setenv("MCP_ANALYTICS_DB_PATH", str(tmp_path / "mcp_analytics.db"))


@pytest.fixture(autouse=True)
def isolate_optional_model_warmup(monkeypatch, request, isolate_private_app_storage):
    """API test lifespans must not launch model loads across test boundaries.

    Return the real wrapper so startup tests can opt into its thread behavior
    with a controlled model loader. Direct model-loading tests remain real.
    """
    api_server = sys.modules.get("api_server")
    if api_server is None:
        # Standalone source-contract tests must keep their import boundary:
        # only API fixtures may require the application to load here.
        if not {"app", "client"}.intersection(request.fixturenames):
            return None
        import api_server

    background_warmup = api_server._warm_cross_encoder_background
    monkeypatch.setattr(api_server, "_warm_cross_encoder_background", lambda: None)
    return background_warmup


@pytest.fixture(autouse=True)
def isolate_search_shutdown_signal(monkeypatch, isolate_optional_model_warmup):
    """A TestClient shutdown must not shut down another test's ASGI app.

    Keep operation owners and their real worker accounting intact. Only the
    application-lifetime signal is fresh; shutdown remains effective for every
    request and worker within the test that triggers it.
    """
    search = sys.modules.get("routers.search")
    if search is not None:
        monkeypatch.setattr(search, "_router_shutdown", threading.Event())


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


if os.environ.get("PAPERREVIEW_OFFLINE_TESTS") == "1":
    # Guard collection as well as test bodies. This mode permits only local
    # fixture servers/IPC; it never turns provider failures into fake results.
    _socket_connect = socket.socket.connect
    _socket_connect_ex = socket.socket.connect_ex
    _socket_getaddrinfo = socket.getaddrinfo

    def _local_host(host):
        if host is None or host in ("localhost", b"localhost"):
            return True
        try:
            return ipaddress.ip_address(
                host.decode() if isinstance(host, bytes) else host
            ).is_loopback
        except (ValueError, TypeError):
            return False

    def _offline_connect(sock, address):
        if sock.family != getattr(socket, "AF_UNIX", None) and not _local_host(
            address[0]
        ):
            raise AssertionError("External network disabled for isolated verification")
        return _socket_connect(sock, address)

    def _offline_connect_ex(sock, address):
        if sock.family != getattr(socket, "AF_UNIX", None) and not _local_host(
            address[0]
        ):
            raise AssertionError("External network disabled for isolated verification")
        return _socket_connect_ex(sock, address)

    def _offline_getaddrinfo(host, *args, **kwargs):
        if not _local_host(host):
            raise AssertionError("External DNS disabled for isolated verification")
        return _socket_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = _offline_connect
    socket.socket.connect_ex = _offline_connect_ex
    socket.getaddrinfo = _offline_getaddrinfo


def _make_test_token(username: str = "test-admin", role: str = "admin") -> str:
    """Sign the actual temporary account incarnation, never bypass authority."""
    from datetime import datetime, timedelta, timezone
    from routers.deps.storage import _get_user_db

    user = _get_user_db().get(username)
    if user is None:
        raise ValueError("Create the temporary account before issuing its test token")
    payload = {
        "sub": username,
        "account_incarnation": user["account_incarnation"],
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
        db.create_account(
            "test-admin",
            {"password_hash": "test-hash", "role": "admin", "created_at": ""},
        )
    else:
        # Ensure role is admin even if a prior test downgraded the record.
        record = db.get("test-admin") or {}
        if record.get("role") != "admin":
            record["role"] = "admin"
            db.upsert(
                "test-admin", record, expected_incarnation=record["account_incarnation"]
            )

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
