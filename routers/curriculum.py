"""
Curriculum endpoints:
  GET    /api/curricula                  — List all courses
  GET    /api/curricula/{id}             — Course detail (modules/topics/papers)
  GET    /api/curricula/{id}/progress    — User reading progress
  PATCH  /api/curricula/{id}/progress    — Toggle paper read status
  POST   /api/curricula/generate         — Generate custom curriculum via LLM
  POST   /api/curricula/{id}/fork        — Fork a preset curriculum to user's own
  DELETE /api/curricula/{id}             — Delete user's own curriculum
"""

import copy
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from filelock import FileLock
from pydantic import BaseModel

from .deps import get_current_user, get_openai_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["curriculum"])

CURRICULA_DIR = Path("data/curricula")
PROGRESS_FILE = Path("data/curriculum_progress.json")
_progress_lock = FileLock(str(PROGRESS_FILE) + ".lock")

# Preset course IDs — these are the built-in featured courses
PRESET_COURSE_IDS = {"cs224w", "cs224n", "cs231n", "cs229"}


# ── Helpers ───────────────────────────────────────────────────────────

def _load_index() -> dict:
    """Load curricula index."""
    index_path = CURRICULA_DIR / "index.json"
    if not index_path.exists():
        return {"curricula": []}
    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_index(data: dict) -> None:
    """Save curricula index (atomic write)."""
    index_path = CURRICULA_DIR / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = index_path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(index_path)


def _load_course(course_id: str) -> Optional[dict]:
    """Load a single course JSON file."""
    course_path = CURRICULA_DIR / f"{course_id}.json"
    if not course_path.exists():
        return None
    with open(course_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_progress() -> dict:
    """Load progress data (thread-safe)."""
    with _progress_lock:
        if not PROGRESS_FILE.exists():
            return {}
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}


def _save_progress(data: dict) -> None:
    """Save progress data (thread-safe, atomic write)."""
    with _progress_lock:
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PROGRESS_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(PROGRESS_FILE)


def _count_papers(course: dict) -> int:
    """Count total papers in a course."""
    count = 0
    for module in course.get("modules", []):
        for topic in module.get("topics", []):
            count += len(topic.get("papers", []))
    return count


# ── Pydantic models ──────────────────────────────────────────────────

class ProgressUpdateRequest(BaseModel):
    paper_id: str
    read: bool


class CurriculumGenerateRequest(BaseModel):
    topic: str
    difficulty: str = "intermediate"
    num_modules: int = 5


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/curricula")
async def list_curricula(owner: Optional[str] = None):
    """List all available curricula with preset/owner metadata."""
    index = _load_index()
    enriched = []
    for c in index.get("curricula", []):
        entry = {**c}
        entry.setdefault("is_preset", c["id"] in PRESET_COURSE_IDS)
        entry.setdefault("owner", None)
        entry.setdefault("forked_from", None)
        enriched.append(entry)
    if owner:
        enriched = [c for c in enriched if c.get("owner") == owner or c.get("is_preset")]
    return {"curricula": enriched}


@router.get("/curricula/generate")
async def generate_placeholder():
    """Prevent GET /curricula/generate from matching /{id}."""
    raise HTTPException(status_code=405, detail="Use POST to generate a curriculum")


@router.get("/curricula/{course_id}")
async def get_curriculum(course_id: str):
    """Get full course detail with modules, topics, and papers."""
    course = _load_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")
    return course


@router.get("/curricula/{course_id}/progress")
async def get_progress(course_id: str, username: str = Depends(get_current_user)):
    """Get user's reading progress for a course."""
    # Verify course exists
    course = _load_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    progress = _load_progress()
    user_progress = progress.get(username, {}).get(course_id, {})

    read_papers = user_progress.get("read_papers", [])
    total_papers = _count_papers(course)

    return {
        "course_id": course_id,
        "read_papers": read_papers,
        "total_papers": total_papers,
        "progress_percent": round(len(read_papers) / total_papers * 100, 1) if total_papers > 0 else 0,
        "updated_at": user_progress.get("updated_at"),
    }


@router.patch("/curricula/{course_id}/progress")
async def update_progress(
    course_id: str,
    request: ProgressUpdateRequest,
    username: str = Depends(get_current_user),
):
    """Toggle a paper's read status for the current user."""
    # Verify course exists
    course = _load_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    progress = _load_progress()

    if username not in progress:
        progress[username] = {}
    if course_id not in progress[username]:
        progress[username][course_id] = {"read_papers": [], "updated_at": None}

    user_course = progress[username][course_id]
    read_set = set(user_course["read_papers"])

    if request.read:
        read_set.add(request.paper_id)
    else:
        read_set.discard(request.paper_id)

    user_course["read_papers"] = sorted(read_set)
    user_course["updated_at"] = datetime.now().isoformat()

    _save_progress(progress)

    total_papers = _count_papers(course)
    return {
        "success": True,
        "read_papers": user_course["read_papers"],
        "total_papers": total_papers,
        "progress_percent": round(len(user_course["read_papers"]) / total_papers * 100, 1) if total_papers > 0 else 0,
    }


@router.post("/curricula/generate")
async def generate_curriculum(
    request: CurriculumGenerateRequest,
    username: str = Depends(get_current_user),
):
    """Generate a custom curriculum using LLM."""
    client = get_openai_client()

    prompt = f"""You are an expert academic curriculum designer. Create a structured learning curriculum for the topic: "{request.topic}"

Requirements:
- Difficulty level: {request.difficulty}
- Number of modules: {request.num_modules}
- Each module should have 1-3 topics
- Each topic should reference 2-4 real, existing academic papers
- Include paper titles, authors, year, venue, and arxiv_id if available
- Provide a Korean context sentence explaining why each paper is important

Return ONLY valid JSON matching this exact schema (no markdown, no explanation):
{{
  "id": "custom_<short_id>",
  "name": "Custom: {request.topic}",
  "university": "Custom Curriculum",
  "instructor": "AI Generated",
  "difficulty": "{request.difficulty}",
  "prerequisites": ["list of prerequisites"],
  "description": "Course description",
  "url": "",
  "modules": [
    {{
      "id": "mod-01",
      "week": 1,
      "title": "Module Title",
      "description": "Module description",
      "topics": [
        {{
          "id": "topic-01-01",
          "title": "Topic Title",
          "papers": [
            {{
              "id": "paper-custom-001",
              "title": "Actual Paper Title",
              "authors": ["Author1", "Author2"],
              "year": 2020,
              "venue": "Conference/Journal",
              "arxiv_id": "2001.12345",
              "doi": null,
              "category": "required",
              "context": "이 논문이 왜 중요한지 한국어로 설명"
            }}
          ]
        }}
      ]
    }}
  ]
}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        curriculum = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON")
    except Exception as e:
        logger.error("LLM curriculum generation failed: %s", e)
        raise HTTPException(status_code=502, detail=f"LLM generation failed: {str(e)}")

    # Generate stable ID based on topic
    topic_hash = hashlib.md5(request.topic.encode()).hexdigest()[:8]
    course_id = f"custom_{topic_hash}"
    curriculum["id"] = course_id

    # Assign unique paper IDs
    paper_counter = 1
    for module in curriculum.get("modules", []):
        for topic in module.get("topics", []):
            for paper in topic.get("papers", []):
                paper["id"] = f"paper-{course_id}-{paper_counter:03d}"
                paper_counter += 1

    # Save course file
    CURRICULA_DIR.mkdir(parents=True, exist_ok=True)
    course_path = CURRICULA_DIR / f"{course_id}.json"
    with open(course_path, "w", encoding="utf-8") as f:
        json.dump(curriculum, f, ensure_ascii=False, indent=2)

    # Register in index
    index = _load_index()
    total_papers = _count_papers(curriculum)
    total_modules = len(curriculum.get("modules", []))

    # Remove existing entry with same ID if any
    index["curricula"] = [c for c in index["curricula"] if c["id"] != course_id]
    index["curricula"].append({
        "id": course_id,
        "name": curriculum.get("name", f"Custom: {request.topic}"),
        "university": "Custom Curriculum",
        "instructor": "AI Generated",
        "difficulty": request.difficulty,
        "prerequisites": curriculum.get("prerequisites", []),
        "description": curriculum.get("description", ""),
        "url": "",
        "total_papers": total_papers,
        "total_modules": total_modules,
    })
    _save_index(index)

    return {
        "success": True,
        "course_id": course_id,
        "curriculum": curriculum,
    }


@router.post("/curricula/{course_id}/fork")
async def fork_curriculum(
    course_id: str,
    username: str = Depends(get_current_user),
):
    """Fork a curriculum into the user's own collection."""
    source = _load_course(course_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    # Generate unique forked ID
    fork_hash = hashlib.md5(f"{username}:{course_id}:{datetime.now().isoformat()}".encode()).hexdigest()[:8]
    forked_id = f"fork_{fork_hash}"

    # Deep copy and update metadata
    forked = copy.deepcopy(source)
    forked["id"] = forked_id
    forked["name"] = f"{source.get('name', course_id)}"
    forked["forked_from"] = course_id
    forked["owner"] = username

    # Re-assign paper IDs to avoid collision
    paper_counter = 1
    for module in forked.get("modules", []):
        for topic in module.get("topics", []):
            for paper in topic.get("papers", []):
                paper["id"] = f"paper-{forked_id}-{paper_counter:03d}"
                paper_counter += 1

    # Save course file
    CURRICULA_DIR.mkdir(parents=True, exist_ok=True)
    course_path = CURRICULA_DIR / f"{forked_id}.json"
    with open(course_path, "w", encoding="utf-8") as f:
        json.dump(forked, f, ensure_ascii=False, indent=2)

    # Register in index
    index = _load_index()
    total_papers = _count_papers(forked)
    total_modules = len(forked.get("modules", []))

    index["curricula"].append({
        "id": forked_id,
        "name": forked["name"],
        "university": source.get("university", ""),
        "instructor": source.get("instructor", ""),
        "difficulty": source.get("difficulty", "intermediate"),
        "prerequisites": source.get("prerequisites", []),
        "description": source.get("description", ""),
        "url": source.get("url", ""),
        "total_papers": total_papers,
        "total_modules": total_modules,
        "is_preset": False,
        "owner": username,
        "forked_from": course_id,
    })
    _save_index(index)

    return {
        "success": True,
        "course_id": forked_id,
        "forked_from": course_id,
    }


@router.delete("/curricula/{course_id}")
async def delete_curriculum(
    course_id: str,
    username: str = Depends(get_current_user),
):
    """Delete a user's own curriculum (cannot delete presets)."""
    if course_id in PRESET_COURSE_IDS:
        raise HTTPException(status_code=403, detail="Cannot delete preset courses")

    index = _load_index()
    entry = next((c for c in index["curricula"] if c["id"] == course_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    if entry.get("owner") and entry["owner"] != username:
        raise HTTPException(status_code=403, detail="Cannot delete another user's curriculum")

    # Remove from index
    index["curricula"] = [c for c in index["curricula"] if c["id"] != course_id]
    _save_index(index)

    # Remove course file
    course_path = CURRICULA_DIR / f"{course_id}.json"
    if course_path.exists():
        course_path.unlink()

    return {"success": True, "deleted": course_id}
