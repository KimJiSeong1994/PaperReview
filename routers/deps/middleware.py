"""
Rate limiting and API key verification middleware.
"""

import os

from fastapi import HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

# ── Rate limiting ────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── Optional API key auth ────────────────────────────────────────────
API_AUTH_KEY = os.getenv("API_AUTH_KEY", "")


async def verify_api_key(request: Request):
    """Verify API key if API_AUTH_KEY is configured."""
    if not API_AUTH_KEY:
        return  # Auth disabled
    auth_header = request.headers.get("X-API-Key", "")
    if auth_header != API_AUTH_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
