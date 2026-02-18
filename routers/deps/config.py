"""
Environment configuration, SSL setup, project paths, and API key.

This is the base module — it must not import from any other deps submodule.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import certifi
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# SSL: certifi CA bundle (macOS certificate issue)
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

# ── Project paths ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
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
    logger.warning("No OpenAI API key found in environment")
