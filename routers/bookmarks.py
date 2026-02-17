"""
Bookmark CRUD endpoints (per-user isolated):
  POST   /api/bookmarks
  GET    /api/bookmarks
  GET    /api/bookmarks/{bookmark_id}
  DELETE /api/bookmarks/{bookmark_id}
  PATCH  /api/bookmarks/{bookmark_id}/topic
  PATCH  /api/bookmarks/{bookmark_id}/notes
  POST   /api/bookmarks/{bookmark_id}/auto-highlight
  POST   /api/bookmarks/bulk-delete
  POST   /api/bookmarks/bulk-move
"""

import json
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .deps import load_bookmarks, save_bookmarks, review_sessions, review_sessions_lock, get_current_user

router = APIRouter(prefix="/api", tags=["bookmarks"])


# ── Pydantic models ───────────────────────────────────────────────────

class BookmarkCreateRequest(BaseModel):
    session_id: str
    title: str
    query: str = ""
    papers: List[dict] = []
    report_markdown: str
    tags: List[str] = []
    topic: str = "General"


class BookmarkTopicUpdateRequest(BaseModel):
    topic: str


class BookmarkResponse(BaseModel):
    id: str
    title: str
    session_id: str
    query: str
    num_papers: int
    created_at: str
    tags: List[str]
    topic: str = "General"


class BulkDeleteBookmarksRequest(BaseModel):
    bookmark_ids: List[str]


class BulkMoveBookmarksRequest(BaseModel):
    bookmark_ids: List[str]
    topic: str


class BookmarkNotesUpdateRequest(BaseModel):
    notes: Optional[str] = None
    highlights: Optional[List[dict]] = None


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/bookmarks")
async def create_bookmark(request: BookmarkCreateRequest, username: str = Depends(get_current_user)):
    """Save a deep research result as a bookmark."""
    bookmark_id = f"bm_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    workspace_path = ""
    with review_sessions_lock:
        if request.session_id in review_sessions:
            workspace_path = review_sessions[request.session_id].get("workspace_path", "")

    bookmark = {
        "id": bookmark_id,
        "username": username,
        "title": request.title,
        "session_id": request.session_id,
        "workspace_path": workspace_path,
        "query": request.query,
        "papers": request.papers,
        "num_papers": len(request.papers),
        "report_markdown": request.report_markdown,
        "created_at": datetime.now().isoformat(),
        "tags": request.tags,
        "topic": request.topic,
    }

    data = load_bookmarks()
    data["bookmarks"].append(bookmark)
    save_bookmarks(data)

    return BookmarkResponse(
        id=bookmark_id,
        title=request.title,
        session_id=request.session_id,
        query=request.query,
        num_papers=len(request.papers),
        created_at=bookmark["created_at"],
        tags=request.tags,
        topic=request.topic,
    )


@router.get("/bookmarks")
async def list_bookmarks(username: str = Depends(get_current_user)):
    """List bookmarks for the current user (summary only)."""
    data = load_bookmarks()
    return {
        "bookmarks": [
            {
                "id": bm["id"],
                "title": bm["title"],
                "session_id": bm["session_id"],
                "query": bm.get("query", ""),
                "num_papers": bm.get("num_papers", 0),
                "created_at": bm["created_at"],
                "tags": bm.get("tags", []),
                "topic": bm.get("topic", "General"),
                "has_notes": bool(bm.get("notes", "").strip()) or bool(bm.get("highlights", [])),
            }
            for bm in data["bookmarks"]
            if bm.get("username") == username
        ]
    }


@router.get("/bookmarks/{bookmark_id}")
async def get_bookmark(bookmark_id: str, username: str = Depends(get_current_user)):
    """Get full bookmark detail including report."""
    data = load_bookmarks()
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id:
            if bm.get("username") != username:
                raise HTTPException(status_code=403, detail="Access denied")
            return bm
    raise HTTPException(status_code=404, detail="Bookmark not found")


@router.delete("/bookmarks/{bookmark_id}")
async def delete_bookmark(bookmark_id: str, username: str = Depends(get_current_user)):
    """Delete a bookmark owned by the current user."""
    data = load_bookmarks()
    original_len = len(data["bookmarks"])
    data["bookmarks"] = [
        bm for bm in data["bookmarks"]
        if not (bm["id"] == bookmark_id and bm.get("username") == username)
    ]

    if len(data["bookmarks"]) == original_len:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    save_bookmarks(data)
    return {"success": True, "message": "Bookmark deleted"}


@router.patch("/bookmarks/{bookmark_id}/topic")
async def update_bookmark_topic(
    bookmark_id: str, request: BookmarkTopicUpdateRequest,
    username: str = Depends(get_current_user),
):
    """Update a bookmark's topic."""
    data = load_bookmarks()
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id:
            if bm.get("username") != username:
                raise HTTPException(status_code=403, detail="Access denied")
            bm["topic"] = request.topic
            save_bookmarks(data)
            return {"success": True, "topic": request.topic}
    raise HTTPException(status_code=404, detail="Bookmark not found")


@router.patch("/bookmarks/{bookmark_id}/notes")
async def update_bookmark_notes(
    bookmark_id: str, request: BookmarkNotesUpdateRequest,
    username: str = Depends(get_current_user),
):
    """Update a bookmark's personal notes and/or highlights."""
    data = load_bookmarks()
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id:
            if bm.get("username") != username:
                raise HTTPException(status_code=403, detail="Access denied")
            if request.notes is not None:
                bm["notes"] = request.notes
            if request.highlights is not None:
                bm["highlights"] = request.highlights
            save_bookmarks(data)
            return {
                "success": True,
                "notes": bm.get("notes", ""),
                "highlights": bm.get("highlights", []),
            }
    raise HTTPException(status_code=404, detail="Bookmark not found")


CATEGORY_CONFIG = {
    "finding": {"label": "[핵심 발견]", "color": "#6ee7b7"},      # emerald
    "methodology": {"label": "[방법론]", "color": "#93c5fd"},      # blue
    "insight": {"label": "[인사이트]", "color": "#c4b5fd"},        # violet
    "limitation": {"label": "[연구 한계]", "color": "#fca5a5"},    # rose
}

AUTO_HIGHLIGHT_SYSTEM_PROMPT = """\
당신은 Nature, Science 등 최상위 저널의 리뷰어이자 학술 논문 분석 전문가입니다.
주어진 연구 리포트에서 가장 핵심적이고 학술적 가치가 높은 구절을 정확히 추출하는 것이 임무입니다.

## 추출 원칙
1. **원문 정확 복사**: text 필드에는 리포트 본문에서 해당 구절을 한 글자도 바꾸지 않고 그대로 복사해야 합니다.
   - 공백, 구두점, 특수문자까지 모두 원문 그대로여야 합니다.
   - 마크다운 기호(#, *, -, |)는 제외하고 순수 텍스트만 복사하세요.
2. **구절 길이**: 한 문장 또는 의미 있는 반 문장(20~120자) 단위로 추출하세요. 너무 짧거나(10자 미만) 너무 길면(200자 초과) 안 됩니다.
3. **깊이 우선**: 표면적이거나 일반적인 서술이 아니라, 구체적 수치·방법·비교·한계·새로운 해석이 담긴 문장을 선택하세요.

## 카테고리 가이드
- **finding**: 실증적 연구 결과, 정량적 수치, 핵심 결론. 주로 '개별 논문 분석', '교차 분석', '결론' 섹션에 존재.
  예: 특정 수치 결과, 비교 실험 결과, 핵심 발견 요약
- **methodology**: 핵심 알고리즘, 기술적 혁신, 연구 설계. 주로 '개별 논문 분석'의 방법론 서술에 존재.
  예: 모델 아키텍처 설명, 데이터 처리 방식, 새로운 접근법
- **insight**: 논문 간 교차 해석, 메타 수준의 시사점, 독창적 통찰. 주로 '핵심 통찰', '연구 동향', '교차 분석' 섹션에 존재.
  예: 연구 트렌드 해석, 방법론 간 시너지, 학문적 의미
- **limitation**: 연구의 한계, 숨겨진 가정, 향후 과제. 주로 '한계', '미래 전망', '비판적 분석' 부분에 존재.
  예: 데이터 제약, 일반화 한계, 미해결 문제

## 출력 형식
반드시 아래 JSON 형식으로만 응답하세요:
{"highlights": [{"text": "리포트 원문 그대로", "category": "finding|methodology|insight|limitation", "reason": "선정 이유 (한국어, 1문장)"}]}

## 선정 기준
- 총 8~15개 하이라이트를 추출하세요.
- 카테고리별 최소 1개, finding과 insight는 각 3개 이상 권장.
- 리포트 전체에 걸쳐 고르게 분포시키세요 (서론~결론까지).
- 중복되는 내용의 구절은 제외하세요.\
"""


def _strip_markdown(text: str) -> str:
    """Strip common markdown formatting characters for comparison."""
    import re
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)  # bold/italic
    text = re.sub(r'`([^`]+)`', r'\1', text)  # inline code
    return text.strip()


def _find_verbatim_or_fuzzy(text: str, report: str) -> str | None:
    """Return the original report substring matching `text`, or None."""
    # 1. Exact verbatim match
    if text in report:
        return text

    # 2. Whitespace-normalized match within individual lines
    normalized = " ".join(text.split())
    for line in report.split("\n"):
        norm_line = " ".join(line.split())
        idx = norm_line.find(normalized)
        if idx == -1:
            continue
        # Map normalized offset back to original line
        orig_start = 0
        ni = 0
        for ci, ch in enumerate(line):
            if ni == idx:
                orig_start = ci
                break
            if ch.strip() or (ci > 0 and line[ci - 1].strip()):
                ni += 1
        # Extract original substring of the same semantic length
        orig_end = orig_start
        ni = 0
        for ci in range(orig_start, len(line)):
            if ni >= len(normalized):
                break
            ch = line[ci]
            if ch.strip() or (ci > orig_start and line[ci - 1].strip()):
                ni += 1
            orig_end = ci + 1
        candidate = line[orig_start:orig_end].strip()
        if candidate and candidate in report:
            return candidate

    # 3. Markdown-stripped match: try stripping bold/italic/code from LLM output
    stripped = _strip_markdown(text)
    if stripped != text and stripped in report:
        return stripped

    return None


@router.post("/bookmarks/{bookmark_id}/auto-highlight")
def auto_highlight_bookmark(bookmark_id: str, username: str = Depends(get_current_user)):
    """Use LLM to automatically extract key highlights from the bookmark report."""
    from openai import OpenAI

    # Phase 1: Read bookmark and report (before LLM call)
    data = load_bookmarks()
    bookmark = None
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id:
            if bm.get("username") != username:
                raise HTTPException(status_code=403, detail="Access denied")
            bookmark = bm
            break
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    report = bookmark.get("report_markdown", "")
    if not report.strip():
        raise HTTPException(status_code=400, detail="No report content to analyze")

    # Section-aware truncation: keep structure intact up to limit
    max_chars = 24000
    if len(report) > max_chars:
        cutoff = report.rfind("\n## ", 0, max_chars)
        if cutoff > max_chars * 0.6:
            report_text = report[:cutoff]
        else:
            cutoff = report.rfind("\n\n", 0, max_chars)
            report_text = report[:cutoff] if cutoff > 0 else report[:max_chars]
    else:
        report_text = report

    query = bookmark.get("query", "")
    title = bookmark.get("title", "")
    topic_context = f"[연구 주제: {title or query}]\n\n" if (query or title) else ""

    # Phase 2: LLM call (potentially long-running, no lock held)
    client = OpenAI()
    response = client.chat.completions.create(
        model="gpt-4.1",
        temperature=0.2,
        timeout=60,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": AUTO_HIGHLIGHT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{topic_context}"
                    f"다음 연구 리포트에서 핵심 하이라이트를 추출해 주세요.\n\n"
                    f"---\n{report_text}\n---"
                ),
            },
        ],
    )

    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON")

    llm_highlights = parsed.get("highlights", [])

    # Phase 3: Re-load bookmarks (atomic read-modify-write to avoid TOCTOU)
    data = load_bookmarks()
    bookmark = None
    for bm in data["bookmarks"]:
        if bm["id"] == bookmark_id and bm.get("username") == username:
            bookmark = bm
            break
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    existing_texts = {h["text"] for h in bookmark.get("highlights", [])}
    new_highlights = list(bookmark.get("highlights", []))
    added_count = 0
    valid_categories = set(CATEGORY_CONFIG.keys())

    for item in llm_highlights:
        text = item.get("text", "").strip()
        category = item.get("category", "finding")
        if category not in valid_categories:
            category = "finding"
        reason = item.get("reason", "")
        if not text or len(text) < 5 or text in existing_texts:
            continue

        # Verbatim match with fuzzy fallback
        matched_text = _find_verbatim_or_fuzzy(text, report)
        if not matched_text:
            continue

        # Use matched_text (may differ from LLM output due to fuzzy recovery)
        if matched_text in existing_texts:
            continue

        cfg = CATEGORY_CONFIG[category]
        memo = f"{cfg['label']} {reason}" if reason else cfg["label"]
        new_highlights.append({
            "id": f"hl_{uuid.uuid4().hex[:12]}",
            "text": matched_text,
            "color": cfg["color"],
            "memo": memo,
            "created_at": datetime.now().isoformat(),
        })
        existing_texts.add(matched_text)
        added_count += 1

    bookmark["highlights"] = new_highlights
    save_bookmarks(data)

    return {
        "success": True,
        "highlights": new_highlights,
        "added_count": added_count,
    }


@router.post("/bookmarks/bulk-delete")
async def bulk_delete_bookmarks(request: BulkDeleteBookmarksRequest, username: str = Depends(get_current_user)):
    """Delete multiple bookmarks owned by the current user."""
    data = load_bookmarks()
    ids_set = set(request.bookmark_ids)
    original = len(data["bookmarks"])
    data["bookmarks"] = [
        bm for bm in data["bookmarks"]
        if not (bm["id"] in ids_set and bm.get("username") == username)
    ]
    deleted = original - len(data["bookmarks"])
    if deleted == 0:
        raise HTTPException(status_code=404, detail="No bookmarks found to delete")
    save_bookmarks(data)
    return {"success": True, "deleted_count": deleted}


@router.post("/bookmarks/bulk-move")
async def bulk_move_bookmarks(request: BulkMoveBookmarksRequest, username: str = Depends(get_current_user)):
    """Move multiple bookmarks to a new topic (current user only)."""
    data = load_bookmarks()
    ids_set = set(request.bookmark_ids)
    updated = 0
    for bm in data["bookmarks"]:
        if bm["id"] in ids_set and bm.get("username") == username:
            bm["topic"] = request.topic
            updated += 1
    if updated == 0:
        raise HTTPException(status_code=404, detail="No bookmarks found to update")
    save_bookmarks(data)
    return {"success": True, "updated_count": updated, "topic": request.topic}
