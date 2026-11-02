"""Public, read-only sample conversations for the logged-out home.

  GET /api/samples/conversations          list of samples
  GET /api/samples/conversations/{slug}   one sample with its turns

Samples are sanitised JSON files written by scripts/export_sample_conversation.py
into data/samples/conversations/ (committed to git). A file is re-read when its
mtime changes, so an edited sample shows up without a restart.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, HTTPException, Request

from .deps.middleware import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/samples", tags=["samples"])

SAMPLES_DIR = Path(os.getenv("SAMPLES_DIR", Path(__file__).resolve().parents[1] / "data" / "samples" / "conversations"))
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_cache: Dict[Path, Tuple[float, Dict[str, Any]]] = {}


def _load(path: Path) -> Dict[str, Any]:
    """Parsed sample file, cached until its mtime changes."""
    mtime = path.stat().st_mtime
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    sample = json.loads(path.read_text(encoding="utf-8"))
    _cache[path] = (mtime, sample)
    return sample


def _samples() -> List[Dict[str, Any]]:
    out = []
    for path in sorted(Path(SAMPLES_DIR).glob("*.json")):
        try:
            out.append(_load(path))
        except (OSError, ValueError):
            logger.warning("unreadable sample conversation: %s", path.name)
    return out


@router.get("/conversations")
@limiter.limit("60/minute")
async def list_samples(request: Request) -> List[Dict[str, Any]]:
    """Every sample: ``[{id, slug, title, question, asof, turn_count}]``."""
    return [
        {"id": s["id"], "slug": s["slug"], "title": s["title"], "question": s["question"], "asof": s["asof"],
         "turn_count": len(s["turns"])}
        for s in _samples()
    ]


@router.get("/conversations/{slug}")
@limiter.limit("60/minute")
async def get_sample(request: Request, slug: str) -> Dict[str, Any]:
    """One sample: ``{id, slug, title, question, asof, turns:[{seq, role, content, blocks, intent}]}``."""
    path = Path(SAMPLES_DIR) / f"{slug}.json"
    if not _SLUG.fullmatch(slug) or not path.is_file():
        raise HTTPException(status_code=404, detail="샘플 대화를 찾을 수 없습니다")
    s = _load(path)
    return {
        "id": s["id"], "slug": s["slug"], "title": s["title"], "question": s["question"], "asof": s["asof"],
        "turns": [{k: t.get(k) for k in ("seq", "role", "content", "blocks", "intent")} for t in s["turns"]],
    }
