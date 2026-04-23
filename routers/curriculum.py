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

import asyncio
import copy
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from filelock import FileLock
from pydantic import BaseModel, Field
from starlette.requests import Request

from .deps import get_current_user, get_openai_client, get_optional_user, limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["curriculum"])

CURRICULA_DIR = Path("data/curricula")
PROGRESS_FILE = Path("data/curriculum_progress.json")
USER_INDEX_FILE = CURRICULA_DIR / "user_index.json"
_progress_lock = FileLock(str(PROGRESS_FILE) + ".lock")
_index_lock = FileLock(str(USER_INDEX_FILE) + ".lock")

# Preset course IDs — these are the built-in featured courses
PRESET_COURSE_IDS = {"cs224w", "cs224n", "cs231n", "cs229", "stats315a", "stats361", "xai", "rl", "genai"}

# Course ID validation pattern
_COURSE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


# ── Helpers ───────────────────────────────────────────────────────────

def _validate_course_id(course_id: str) -> str:
    """Validate course_id to prevent path traversal attacks."""
    if not _COURSE_ID_RE.match(course_id) or len(course_id) > 128:
        raise HTTPException(status_code=400, detail="Invalid course ID format")
    resolved = (CURRICULA_DIR / f"{course_id}.json").resolve()
    if not str(resolved).startswith(str(CURRICULA_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid course ID")
    return course_id


def _load_preset_index() -> list:
    """Load git-tracked preset curricula index."""
    index_path = CURRICULA_DIR / "index.json"
    if not index_path.exists():
        return []
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("curricula", [])
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error("Corrupted index.json, returning empty list")
        return []


def _load_user_index() -> list:
    """Load user-generated curricula index (survives deploys)."""
    if not USER_INDEX_FILE.exists():
        return []
    try:
        with open(USER_INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("curricula", [])
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error("Corrupted user_index.json, returning empty list")
        return []


def _save_user_index(entries: list) -> None:
    """Save user-generated curricula index (atomic write). Caller must hold _index_lock."""
    USER_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = USER_INDEX_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"curricula": entries}, f, ensure_ascii=False, indent=2)
    tmp.replace(USER_INDEX_FILE)


def _load_index() -> dict:
    """Load merged index (presets + user). Caller must hold _index_lock if writing."""
    presets = _load_preset_index()
    users = _load_user_index()
    return {"curricula": presets + users}


def _load_course(course_id: str) -> Optional[dict]:
    """Load a single course JSON file."""
    course_path = CURRICULA_DIR / f"{course_id}.json"
    if not course_path.exists():
        return None
    try:
        with open(course_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error("Corrupted course file: %s", course_id)
        return None


def _save_course(course_id: str, data: dict) -> None:
    """Save a course JSON file (atomic write)."""
    CURRICULA_DIR.mkdir(parents=True, exist_ok=True)
    course_path = CURRICULA_DIR / f"{course_id}.json"
    tmp = course_path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(course_path)


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


def _update_progress_atomic(updater) -> dict:
    """Atomically read-modify-write progress data. Returns updated progress."""
    with _progress_lock:
        if not PROGRESS_FILE.exists():
            progress = {}
        else:
            try:
                with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                    progress = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                progress = {}
        result = updater(progress)
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PROGRESS_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
        tmp.replace(PROGRESS_FILE)
        return result


def _count_papers(course: dict) -> int:
    """Count total papers in a course."""
    count = 0
    for module in course.get("modules", []):
        for topic in module.get("topics", []):
            count += len(topic.get("papers", []))
    return count


# ── Pydantic models ──────────────────────────────────────────────────

class ProgressUpdateRequest(BaseModel):
    paper_id: str = Field(..., min_length=1, max_length=200)
    read: bool


class CurriculumGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=200)
    difficulty: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    num_modules: int = Field(5, ge=2, le=15)


class CurriculumGenerateStreamRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=200)
    difficulty: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    num_modules: int = Field(5, ge=2, le=15)
    learning_goals: Optional[str] = Field(None, max_length=500)
    paper_preference: Optional[Literal["cutting_edge", "survey_heavy", "balanced"]] = None


class CurriculumShareRequest(BaseModel):
    expires_in_days: Optional[int] = 30


class CurriculumShareResponse(BaseModel):
    token: str
    share_url: str
    created_at: str
    expires_at: str


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/curricula")
async def list_curricula(
    owner: Optional[str] = None,
    current_user: Optional[str] = Depends(get_optional_user),
):
    """List available curricula — presets + current user's own.

    인증된 유저: 프리셋 + 자신의 커리큘럼만 반환.
    비인증: 프리셋만 반환.
    owner 파라미터: 명시적 필터 (관리자용).
    """
    index = _load_index()
    enriched = []
    for c in index.get("curricula", []):
        entry = {**c}
        entry.setdefault("is_preset", c["id"] in PRESET_COURSE_IDS)
        entry.setdefault("owner", None)
        entry.setdefault("forked_from", None)
        entry["has_share"] = bool(entry.get("share"))
        entry.pop("share", None)  # Don't expose share token in list
        enriched.append(entry)

    # 필터링: owner 파라미터 > 현재 유저 > 프리셋만
    if owner:
        enriched = [c for c in enriched if c.get("owner") == owner or c.get("is_preset")]
    elif current_user:
        enriched = [c for c in enriched if c.get("is_preset") or c.get("owner") == current_user]
    else:
        enriched = [c for c in enriched if c.get("is_preset")]

    return {"curricula": enriched}


@router.get("/curricula/generate")
async def generate_placeholder():
    """Prevent GET /curricula/generate from matching /{id}."""
    raise HTTPException(status_code=405, detail="Use POST to generate a curriculum")


@router.get("/curricula/{course_id}")
async def get_curriculum(course_id: str):
    """Get full course detail with modules, topics, and papers."""
    _validate_course_id(course_id)
    course = _load_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")
    return course


@router.get("/curricula/{course_id}/progress")
async def get_progress(course_id: str, username: str = Depends(get_current_user)):
    """Get user's reading progress for a course."""
    _validate_course_id(course_id)
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
    _validate_course_id(course_id)
    course = _load_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    def updater(progress):
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
        return user_course

    user_course = _update_progress_atomic(updater)

    total_papers = _count_papers(course)
    return {
        "success": True,
        "read_papers": user_course["read_papers"],
        "total_papers": total_papers,
        "progress_percent": round(len(user_course["read_papers"]) / total_papers * 100, 1) if total_papers > 0 else 0,
    }


@router.post("/curricula/generate")
@limiter.limit("10/minute")
async def generate_curriculum(
    request: Request,
    payload: CurriculumGenerateRequest,
    username: str = Depends(get_current_user),
):
    """Generate a custom curriculum using LLM.

    F-34: IP rate-limited to 10/min — the LLM prompt is multi-KB and a
    single authenticated user could otherwise burn unbounded credits.
    """
    client = get_openai_client()

    # Sanitize topic for prompt
    safe_topic = payload.topic.strip()[:200]

    prompt = f"""You are an expert academic curriculum designer. Create a structured learning curriculum for the topic: "{safe_topic}"

Requirements:
- Difficulty level: {payload.difficulty}
- Number of modules: {payload.num_modules}
- Each module should have 1-3 topics
- Each topic should reference 2-4 real, existing academic papers
- Include paper titles, authors, year, venue, and arxiv_id if available
- Provide a Korean context sentence explaining why each paper is important

Return ONLY valid JSON matching this exact schema (no markdown, no explanation):
{{
  "id": "custom_<short_id>",
  "name": "Custom: {safe_topic}",
  "university": "Custom Curriculum",
  "instructor": "AI Generated",
  "difficulty": "{payload.difficulty}",
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
            model="gpt-5.4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_completion_tokens=4096,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        curriculum = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON")
    except Exception as e:
        logger.error("LLM curriculum generation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail="Curriculum generation failed. Please try again.")

    # Validate basic structure
    if "modules" not in curriculum or not isinstance(curriculum["modules"], list):
        raise HTTPException(status_code=502, detail="LLM returned curriculum without valid modules")

    # ── OpenAlex verification: replace LLM-hallucinated papers with real data ──
    from src.collector.paper.openalex_searcher import OpenAlexSearcher
    searcher = OpenAlexSearcher()
    try:
        for module in curriculum["modules"]:
            for topic in module.get("topics", []):
                verified = []
                for paper in topic.get("papers", []):
                    results = searcher.search_by_title(paper.get("title", ""), 1)
                    if results:
                        real = results[0]
                        paper["title"] = real["title"]
                        paper["authors"] = real["authors"][:10]
                        paper["year"] = int(real["year"]) if real.get("year") else paper.get("year")
                        paper["doi"] = real.get("doi") or paper.get("doi")
                        paper["venue"] = real.get("venue") or paper.get("venue")
                        paper["verified"] = True
                        verified.append(paper)
                    else:
                        # Verification failed: search for fallback paper by topic keyword
                        fallback = searcher.search(topic.get("title", ""), 2)
                        if fallback:
                            fb = fallback[0]
                            verified.append({
                                **paper,
                                "title": fb["title"],
                                "authors": fb["authors"][:10],
                                "year": int(fb["year"]) if fb.get("year") else None,
                                "doi": fb.get("doi"),
                                "venue": fb.get("venue", ""),
                                "verified": True,
                            })
                        else:
                            paper["verified"] = False
                            verified.append(paper)
                topic["papers"] = verified
    except Exception as e:
        logger.warning("OpenAlex verification partially failed: %s", e)
    finally:
        searcher.close()

    # Generate unique ID (UUID to avoid collisions)
    course_id = f"custom_{uuid.uuid4().hex[:12]}"
    curriculum["id"] = course_id

    # Assign unique paper IDs
    paper_counter = 1
    for module in curriculum.get("modules", []):
        for topic in module.get("topics", []):
            for paper in topic.get("papers", []):
                paper["id"] = f"paper-{course_id}-{paper_counter:03d}"
                paper_counter += 1

    # Save course file (atomic)
    _save_course(course_id, curriculum)

    # Register in user index (locked, survives deploys)
    with _index_lock:
        user_entries = _load_user_index()
        total_papers = _count_papers(curriculum)
        total_modules = len(curriculum.get("modules", []))

        user_entries = [c for c in user_entries if c["id"] != course_id]
        user_entries.append({
            "id": course_id,
            "name": curriculum.get("name", f"Custom: {payload.topic}"),
            "university": "Custom Curriculum",
            "instructor": "AI Generated",
            "difficulty": payload.difficulty,
            "prerequisites": curriculum.get("prerequisites", []),
            "description": curriculum.get("description", ""),
            "url": "",
            "total_papers": total_papers,
            "total_modules": total_modules,
            "is_preset": False,
            "owner": username,
        })
        _save_user_index(user_entries)

    return {
        "success": True,
        "course_id": course_id,
        "curriculum": curriculum,
    }


@router.post("/curricula/generate-stream")
@limiter.limit("10/minute")
async def generate_curriculum_stream(
    request: Request,
    payload: CurriculumGenerateStreamRequest,
    username: str = Depends(get_current_user),
):
    """Generate curriculum with 3-step pipeline and SSE progress streaming.

    Guarantees a terminal SSE event (`done` or `error`) under every exit path
    — including LLM hangs behind nginx's 180s ``proxy_read_timeout`` and
    unexpected exceptions inside the pipeline. Also emits periodic keepalive
    comments so an idle LLM call cannot be silently torn down by the proxy.

    F-34: IP rate-limited to 10/min.  Each call holds an SSE stream open
    through a 3-step LLM pipeline; without this cap a burst of tabs can
    exhaust OpenAI quota AND saturate the worker pool at the same time.
    """
    from .curriculum_pipeline import CurriculumPipeline

    # Keepalive interval: well under nginx's 180s proxy_read_timeout so the
    # connection stays alive during long LLM calls. SSE comment lines
    # (starting with ":") are ignored by EventSource/SSE consumers but
    # refresh the proxy idle timer.
    KEEPALIVE_INTERVAL_SEC = 15.0

    async def event_stream():
        terminal_sent = False

        def envelope(event_payload: dict) -> str:
            return f"data: {json.dumps(event_payload, ensure_ascii=False)}\n\n"

        try:
            client = get_openai_client()
        except Exception as e:
            logger.exception("Failed to initialize OpenAI client")
            yield envelope({"error": f"OpenAI client initialization failed: {e}"})
            return

        pipeline = CurriculumPipeline(client)

        # Producer/consumer pattern: the pipeline runs as a background task
        # and pushes events into an asyncio.Queue. The outer loop reads from
        # the queue with a timeout so it can emit keepalive comments when
        # the pipeline is busy inside a long LLM call.
        queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        async def _producer():
            try:
                async for event in pipeline.generate(
                    topic=payload.topic,
                    difficulty=payload.difficulty,
                    num_modules=payload.num_modules,
                    learning_goals=payload.learning_goals,
                    paper_preference=payload.paper_preference,
                ):
                    await queue.put(("event", event))
            except asyncio.CancelledError:
                # Client disconnected — stop producing; don't enqueue
                # terminal error (consumer is also cancelled).
                raise
            except Exception as e:
                logger.exception("Pipeline producer crashed")
                await queue.put(("error", str(e)))
            finally:
                await queue.put(("done", _SENTINEL))

        producer_task = asyncio.create_task(_producer())

        try:
            while True:
                try:
                    kind, item = await asyncio.wait_for(
                        queue.get(), timeout=KEEPALIVE_INTERVAL_SEC,
                    )
                except asyncio.TimeoutError:
                    # Keepalive: SSE comment line, ignored by clients but
                    # refreshes nginx proxy_read_timeout.
                    yield ": keepalive\n\n"
                    continue

                if kind == "done":
                    break

                if kind == "error":
                    yield envelope({"error": f"Pipeline error: {item}"})
                    terminal_sent = True
                    break

                event = item
                if event.get("done") and event.get("curriculum"):
                    curriculum = event["curriculum"]

                    # Validate basic structure
                    if (
                        "modules" not in curriculum
                        or not isinstance(curriculum["modules"], list)
                    ):
                        yield envelope({"error": "LLM returned invalid curriculum structure"})
                        terminal_sent = True
                        break

                    # Persist curriculum + index — wrapped to ensure terminal
                    # event even if disk/index operations fail.
                    try:
                        course_id = f"custom_{uuid.uuid4().hex[:12]}"
                        curriculum["id"] = course_id

                        paper_counter = 1
                        for module in curriculum.get("modules", []):
                            for topic in module.get("topics", []):
                                for paper in topic.get("papers", []):
                                    paper["id"] = f"paper-{course_id}-{paper_counter:03d}"
                                    paper_counter += 1

                        _save_course(course_id, curriculum)

                        with _index_lock:
                            user_entries = _load_user_index()
                            total_papers = _count_papers(curriculum)
                            total_modules = len(curriculum.get("modules", []))

                            user_entries = [c for c in user_entries if c["id"] != course_id]
                            user_entries.append({
                                "id": course_id,
                                "name": curriculum.get("name", f"Custom: {payload.topic}"),
                                "university": curriculum.get("university", "Multi-University Reference"),
                                "instructor": curriculum.get("instructor", "AI Curated"),
                                "difficulty": payload.difficulty,
                                "prerequisites": curriculum.get("prerequisites", []),
                                "description": curriculum.get("description", ""),
                                "url": "",
                                "total_papers": total_papers,
                                "total_modules": total_modules,
                                "is_preset": False,
                                "owner": username,
                            })
                            _save_user_index(user_entries)
                    except Exception as e:
                        logger.exception("Failed to persist generated curriculum")
                        yield envelope({"error": f"Failed to save curriculum: {e}"})
                        terminal_sent = True
                        break

                    yield envelope({"done": True, "course_id": course_id})
                    terminal_sent = True
                    # Continue draining so producer finishes cleanly
                elif event.get("done"):
                    # Pipeline signalled done but with empty/falsy curriculum.
                    # This is a bug upstream; surface it as an error so FE
                    # doesn't hang on a silent close.
                    yield envelope({"error": "Pipeline completed without a curriculum"})
                    terminal_sent = True
                    break
                else:
                    yield envelope(event)
                    # An inner-step error from pipeline also terminates the
                    # stream (e.g. Step 1/2/3 yield {"error": ..., "step": N}
                    # then return). Treat as terminal so FE's onError fires.
                    if event.get("error"):
                        terminal_sent = True
        except asyncio.CancelledError:
            logger.info("Curriculum stream cancelled (client disconnected)")
            raise
        except Exception as e:
            logger.exception("Curriculum stream handler crashed")
            if not terminal_sent:
                try:
                    yield envelope({"error": f"Stream handler error: {e}"})
                    terminal_sent = True
                except Exception:
                    pass
        finally:
            if not producer_task.done():
                producer_task.cancel()
                try:
                    await producer_task
                except (asyncio.CancelledError, Exception):
                    pass
            # Last-ditch guarantee: if the loop exited without a terminal
            # event (e.g. producer finished with no yields), emit one so the
            # FE never sees reader.read() → TypeError with completed=False.
            if not terminal_sent:
                try:
                    yield envelope({"error": "Stream ended without a terminal event"})
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/curricula/{course_id}/fork")
@limiter.limit("10/minute")
async def fork_curriculum(
    request: Request,
    course_id: str,
    username: str = Depends(get_current_user),
):
    """Fork a curriculum into the user's own collection.

    F-34: IP rate-limited to 10/min — deep-copying a curriculum and
    persisting a new user index entry is cheap per call, but loop-abuse
    would pile up user-indexed JSON rows.
    """
    _validate_course_id(course_id)
    source = _load_course(course_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    # Generate unique forked ID (UUID)
    forked_id = f"fork_{uuid.uuid4().hex[:12]}"

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

    # Save course file (atomic)
    _save_course(forked_id, forked)

    # Register in user index (locked, survives deploys)
    with _index_lock:
        user_entries = _load_user_index()
        total_papers = _count_papers(forked)
        total_modules = len(forked.get("modules", []))

        user_entries.append({
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
        _save_user_index(user_entries)

    return {
        "success": True,
        "course_id": forked_id,
        "forked_from": course_id,
    }


@router.delete("/curricula/{course_id}")
@limiter.limit("10/minute")
async def delete_curriculum(
    request: Request,
    course_id: str,
    username: str = Depends(get_current_user),
):
    """Delete a user's own curriculum (cannot delete presets).

    F-34: IP rate-limited to 10/min — each call rewrites the user index
    and deletes a JSON file; visitor-level cap avoids disk-churn abuse.
    """
    _validate_course_id(course_id)

    if course_id in PRESET_COURSE_IDS:
        raise HTTPException(status_code=403, detail="Cannot delete preset courses")

    with _index_lock:
        user_entries = _load_user_index()
        entry = next((c for c in user_entries if c["id"] == course_id), None)
        if not entry:
            raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

        # Strict ownership check: only owner can delete
        if entry.get("owner") != username:
            raise HTTPException(status_code=403, detail="Cannot delete another user's curriculum")

        # Check is_preset field as additional safeguard
        if entry.get("is_preset"):
            raise HTTPException(status_code=403, detail="Cannot delete preset courses")

        # Remove from user index only
        user_entries = [c for c in user_entries if c["id"] != course_id]
        _save_user_index(user_entries)

    # Remove course file
    course_path = CURRICULA_DIR / f"{course_id}.json"
    if course_path.exists():
        course_path.unlink()

    # Clean up orphaned progress data
    def cleanup_progress(progress):
        for user_data in progress.values():
            user_data.pop(course_id, None)
        return None

    _update_progress_atomic(cleanup_progress)

    return {"success": True, "deleted": course_id}


# ── Share endpoints ───────────────────────────────────────────────────


@router.post("/curricula/{course_id}/share")
@limiter.limit("10/minute")
async def create_curriculum_share(
    request: Request,
    course_id: str,
    payload: CurriculumShareRequest = CurriculumShareRequest(),
    username: str = Depends(get_current_user),
):
    """Generate a public share token for a curriculum.

    F-34: IP rate-limited to 10/min.
    """
    import secrets
    from datetime import timedelta

    _validate_course_id(course_id)

    token = f"sc_{secrets.token_urlsafe(16)}"
    now = datetime.now()
    expires_days = payload.expires_in_days or 30
    expires_at = now + timedelta(days=expires_days)

    try:
        with _index_lock:
            user_entries = _load_user_index()
            entry = next((c for c in user_entries if c["id"] == course_id), None)
            if not entry:
                raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")
            if entry.get("owner") != username:
                raise HTTPException(status_code=403, detail="Only the owner can share this curriculum")

            entry["share"] = {
                "token": token,
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
            }
            _save_user_index(user_entries)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create share link: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to save share data: {e}")

    return CurriculumShareResponse(
        token=token,
        share_url=f"/share/curriculum/{token}",
        created_at=now.isoformat(),
        expires_at=expires_at.isoformat(),
    )


@router.delete("/curricula/{course_id}/share")
async def revoke_curriculum_share(
    course_id: str,
    username: str = Depends(get_current_user),
):
    """Revoke the public share link for a curriculum."""
    _validate_course_id(course_id)

    with _index_lock:
        user_entries = _load_user_index()
        entry = next((c for c in user_entries if c["id"] == course_id), None)
        if not entry:
            raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")
        if entry.get("owner") != username:
            raise HTTPException(status_code=403, detail="Access denied")
        if "share" not in entry:
            raise HTTPException(status_code=404, detail="No share link exists")
        del entry["share"]
        _save_user_index(user_entries)

    return {"success": True, "message": "Share link revoked"}


@router.get("/shared/curriculum/{share_token}")
async def get_shared_curriculum(share_token: str):
    """Public endpoint: retrieve a shared curriculum by token (no auth required)."""
    user_entries = _load_user_index()
    entry = None
    for e in user_entries:
        share = e.get("share")
        if share and share.get("token") == share_token:
            entry = e
            break

    if not entry:
        raise HTTPException(status_code=404, detail="Shared curriculum not found")

    # Check expiration
    share = entry["share"]
    expires_at = share.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) < datetime.now():
                raise HTTPException(status_code=410, detail="Share link has expired")
        except ValueError:
            pass

    # Load full course data
    course = _load_course(entry["id"])
    if not course:
        raise HTTPException(status_code=404, detail="Course data not found")

    # Build safe summary (strip owner and share token)
    safe_entry = {k: v for k, v in entry.items() if k not in ("owner", "share")}
    return {"summary": safe_entry, "course": course}
