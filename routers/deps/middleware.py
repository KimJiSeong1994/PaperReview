"""
Rate limiting and API key verification middleware.
"""

import os

from fastapi import HTTPException
from slowapi import Limiter
from starlette.requests import Request


_TRUSTED_PROXIES = set(
    p.strip() for p in os.getenv("TRUSTED_PROXIES", "127.0.0.1").split(",") if p.strip()
)


def _get_real_ip(request: Request) -> str:
    """Extract real client IP from X-Forwarded-For header.

    Only trusts X-Forwarded-For when the direct client is a known reverse proxy.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    if client_ip in _TRUSTED_PROXIES:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return client_ip


# ── Rate limiting ────────────────────────────────────────────────────
limiter = Limiter(key_func=_get_real_ip)

# ── Optional API key auth ────────────────────────────────────────────
API_AUTH_KEY = os.getenv("API_AUTH_KEY", "")


async def verify_api_key(request: Request):
    """Verify API key if API_AUTH_KEY is configured."""
    if not API_AUTH_KEY:
        return  # Auth disabled
    auth_header = request.headers.get("X-API-Key", "")
    if auth_header != API_AUTH_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
