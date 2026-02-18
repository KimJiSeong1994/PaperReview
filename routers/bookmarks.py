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
import logging
import re
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from .deps import load_bookmarks, save_bookmarks, modify_bookmarks, review_sessions, review_sessions_lock, get_current_user, get_openai_client

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

    with modify_bookmarks() as data:
        data["bookmarks"].append(bookmark)

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
    with modify_bookmarks() as data:
        original_len = len(data["bookmarks"])
        data["bookmarks"] = [
            bm for bm in data["bookmarks"]
            if not (bm["id"] == bookmark_id and bm.get("username") == username)
        ]
        if len(data["bookmarks"]) == original_len:
            raise HTTPException(status_code=404, detail="Bookmark not found")
    return {"success": True, "message": "Bookmark deleted"}


@router.patch("/bookmarks/{bookmark_id}/topic")
async def update_bookmark_topic(
    bookmark_id: str, request: BookmarkTopicUpdateRequest,
    username: str = Depends(get_current_user),
):
    """Update a bookmark's topic."""
    with modify_bookmarks() as data:
        for bm in data["bookmarks"]:
            if bm["id"] == bookmark_id:
                if bm.get("username") != username:
                    raise HTTPException(status_code=403, detail="Access denied")
                bm["topic"] = request.topic
                return {"success": True, "topic": request.topic}
        raise HTTPException(status_code=404, detail="Bookmark not found")


@router.patch("/bookmarks/{bookmark_id}/notes")
async def update_bookmark_notes(
    bookmark_id: str, request: BookmarkNotesUpdateRequest,
    username: str = Depends(get_current_user),
):
    """Update a bookmark's personal notes and/or highlights."""
    with modify_bookmarks() as data:
        for bm in data["bookmarks"]:
            if bm["id"] == bookmark_id:
                if bm.get("username") != username:
                    raise HTTPException(status_code=403, detail="Access denied")
                if request.notes is not None:
                    bm["notes"] = request.notes
                if request.highlights is not None:
                    bm["highlights"] = request.highlights
                return {
                    "success": True,
                    "notes": bm.get("notes", ""),
                    "highlights": bm.get("highlights", []),
                }
        raise HTTPException(status_code=404, detail="Bookmark not found")


CATEGORY_CONFIG = {
    # Green 톤 — 실증적 발견
    "finding":         {"label": "[핵심 발견]", "color": "#6ee7b7"},
    "evidence":        {"label": "[근거/수치]", "color": "#6ee7b7"},
    "contribution":    {"label": "[핵심 기여]", "color": "#6ee7b7"},
    # Blue 톤 — 분석적/구조적
    "methodology":     {"label": "[방법론]",    "color": "#93c5fd"},
    "insight":         {"label": "[인사이트]",  "color": "#93c5fd"},
    "reproducibility": {"label": "[재현성]",    "color": "#93c5fd"},
    # Rose 톤 — 비판적 평가
    "limitation":      {"label": "[연구 한계]", "color": "#fca5a5"},
    "gap":             {"label": "[연구 공백]", "color": "#fca5a5"},
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

## 카테고리 가이드 (8개 카테고리, 3가지 색상 톤)

### Green 톤 (실증적/긍정적 발견)
- **finding**: 실증적 연구 결과, 정량적 수치, 핵심 결론.
  예: 특정 수치 결과, 비교 실험 결과, 핵심 발견 요약
- **evidence**: 주장을 뒷받침하는 구체적 데이터, 통계, 실험 수치.
  예: p-value, 성능 지표, 정확도 비교, 표본 크기
- **contribution**: 학술적·실용적 핵심 기여, 새로운 프레임워크·도구 제시.
  예: 새로운 분석 도구 제안, 기존 방법 대비 차별점

### Blue 톤 (분석적/구조적)
- **methodology**: 핵심 알고리즘, 기술적 혁신, 연구 설계.
  예: 모델 아키텍처 설명, 데이터 처리 방식, 새로운 접근법
- **insight**: 논문 간 교차 해석, 메타 수준의 시사점, 독창적 통찰.
  예: 연구 트렌드 해석, 방법론 간 시너지, 학문적 의미
- **reproducibility**: 재현 가능성, 데이터/코드 공개 여부, 실험 조건의 투명성.
  예: 데이터셋 공개 수준, 파라미터 설정 기준, 재현성 우려

### Rose 톤 (비판적 평가)
- **limitation**: 연구의 명시적 한계, 숨겨진 가정, 향후 과제.
  예: 데이터 제약, 일반화 한계, 미해결 문제
- **gap**: 연구 공백, 후속 연구 필요성, 미탐색 영역.
  예: 다루지 못한 변수, 누락된 비교군, 확장 필요성

## 중요도 (significance) 점수
각 하이라이트에 1~5점의 중요도를 부여하세요:
- 5: 논문 전체의 핵심 결론 또는 가장 중요한 발견
- 4: 주요 방법론적 혁신 또는 핵심 실험 결과
- 3: 의미 있는 기여이나 보조적 수준
- 2: 참고할 만한 세부 사항
- 1: 맥락적 배경 정보

## 섹션 인식
리포트는 [SECTION: 제목] 마커로 섹션이 구분되어 있습니다.
각 하이라이트가 추출된 섹션의 제목을 section 필드에 기록하세요.
마커가 없는 경우 가장 가까운 문맥의 섹션 제목을 추정하여 기록합니다.

## Reviewer Commentary (P2)
각 하이라이트에 전문 리뷰어 수준의 비평을 제공하세요.

### reviewer_comment — 톤별 리뷰 관점
2~3문장의 비판적 코멘트를 작성하되, 카테고리 톤에 따라 다른 관점(lens)을 적용하세요:

**Green 톤** (finding/evidence/contribution):
→ 결과의 내적 타당도(internal validity), 효과 크기(effect size)의 실질적 의미, 외적 타당도 한계를 분석하세요.
  예: "42개 도시 대상 비교 분석에서 클러스터링 패턴의 일관성은 내적 타당도가 높다. 그러나 표본이 중국 도시에 편중되어 있어 글로벌 일반화에는 한계가 있다."

**Blue 톤** (methodology/insight/reproducibility):
→ 방법론적 엄밀성, 기존 접근법 대비 차별적 장점, 재현 가능성 우려를 분석하세요.
  예: "GAN 기반 데이터 증강은 소규모 데이터셋 문제를 창의적으로 해결하지만, 생성 데이터의 분포가 원본과 괴리될 경우 모델 편향을 오히려 증폭시킬 수 있다."

**Rose 톤** (limitation/gap):
→ 한계의 근본 원인, 해소를 위한 구체적 접근법, 후속 연구에서 우선적으로 다뤄야 할 사항을 분석하세요.
  예: "단일 시점 분석은 도시 발전의 시계열 역학을 포착하지 못한다. 5~10년 종단 데이터 확보 시 정책 효과의 인과관계 추론이 가능해질 것이다."

### implication — 3차원 영향 분석
1~2문장으로 다음 3가지 차원 중 가장 적합한 것을 선택하여 기술하세요:
- **이론적 함의**: 기존 이론/모델에 대한 지지 또는 도전
- **실용적 함의**: 산업·정책·응용 관점에서의 의미
- **후속 연구 방향**: 이 발견이 열어주는 새로운 연구 질문
  예: "도시 형태와 에너지 효율 간 비선형 관계의 발견은 기존 선형 모델 가정에 도전하며, 복잡계 시뮬레이션 기반 후속 연구를 촉발할 것이다."

### 금지 사항
다음과 같은 보일러플레이트 코멘트는 절대 금지합니다:
- "이 결과는 의미 있다" / "중요한 기여이다" → 무엇이, 왜 의미 있는지 구체적으로 기술
- "향후 연구가 필요하다" → 어떤 방향의, 어떤 문제에 대한 연구인지 기술
- "흥미로운 접근이다" → 기존 방법 대비 어떤 점에서 차별적인지 기술

### 근거 기반 원칙
reviewer_comment와 implication에는 리포트에 직접 언급되지 않은 수치, 저자명, 논문 제목을 포함하지 마세요.
리포트 본문에 근거가 있는 분석만 기술하세요.

## 출력 형식
반드시 아래 JSON 형식으로만 응답하세요:
{"highlights": [{"text": "리포트 원문 그대로", "category": "finding|evidence|contribution|methodology|insight|reproducibility|limitation|gap", "reviewer_comment": "비판적 코멘트 2~3문장", "implication": "연구 분야 영향 1~2문장", "significance": 1, "section": "섹션 제목"}]}

## 선정 기준
- 총 10~18개 하이라이트를 추출하세요.
- Green 톤(finding, evidence, contribution)에서 최소 3개.
- Blue 톤(methodology, insight, reproducibility)에서 최소 3개.
- Rose 톤(limitation, gap)에서 최소 2개.
- significance 4~5는 전체의 30~40%를 권장합니다.
- 리포트 전체에 걸쳐 고르게 분포시키세요 (서론~결론까지).
- 중복되는 내용의 구절은 제외하세요.\
"""


def _parse_report_sections(report: str) -> str:
    """Parse report markdown and reformat with [SECTION: ...] markers for LLM."""
    heading_pattern = re.compile(r'^(#{2,3})\s+(.+)$', re.MULTILINE)
    matches = list(heading_pattern.finditer(report))

    if not matches:
        return report

    parts: list[str] = []
    # Content before first heading
    if matches[0].start() > 0:
        preamble = report[:matches[0].start()].strip()
        if preamble:
            parts.append(preamble)

    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(report)
        content = report[start:end].strip()
        if content:
            parts.append(f"\n[SECTION: {heading}]\n{content}")

    return "\n".join(parts)


def _strip_markdown(text: str) -> str:
    """Strip common markdown formatting characters for comparison."""
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

    # Section-aware formatting for LLM
    formatted_report = _parse_report_sections(report_text)

    # Phase 2: LLM call (potentially long-running, no lock held)
    from openai import APITimeoutError, RateLimitError, APIError

    client = get_openai_client()
    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            temperature=0.2,
            timeout=120,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": AUTO_HIGHLIGHT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"{topic_context}"
                        f"다음 연구 리포트에서 핵심 하이라이트를 추출해 주세요.\n\n"
                        f"---\n{formatted_report}\n---"
                    ),
                },
            ],
        )
    except APITimeoutError:
        raise HTTPException(status_code=504, detail="LLM analysis timed out. Please retry.")
    except RateLimitError:
        raise HTTPException(status_code=429, detail="Rate limited. Please wait and retry.")
    except APIError as e:
        raise HTTPException(status_code=502, detail=f"LLM service error: {e.message}")

    logger.info("Auto-highlight token usage: %s", response.usage)

    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON")

    llm_highlights = parsed.get("highlights", [])

    # Phase 3: Atomic read-modify-write under single lock
    with modify_bookmarks() as data:
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
            reviewer_comment = item.get("reviewer_comment", "").strip()
            implication = item.get("implication", "").strip()
            # Backward compat: fall back to legacy "reason" if reviewer_comment absent
            if not reviewer_comment:
                reviewer_comment = item.get("reason", "").strip()
            try:
                significance = max(1, min(5, int(float(item.get("significance", 3)))))
            except (ValueError, TypeError):
                significance = 3
            section = item.get("section", "")
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
            memo = f"{cfg['label']} {reviewer_comment}" if reviewer_comment else cfg["label"]
            new_highlights.append({
                "id": f"hl_{uuid.uuid4().hex[:12]}",
                "text": matched_text,
                "color": cfg["color"],
                "memo": memo,
                "category": category,
                "significance": significance,
                "section": section,
                "implication": implication,
                "created_at": datetime.now().isoformat(),
            })
            existing_texts.add(matched_text)
            added_count += 1

        bookmark["highlights"] = new_highlights

    return {
        "success": True,
        "highlights": new_highlights,
        "added_count": added_count,
    }


@router.post("/bookmarks/bulk-delete")
async def bulk_delete_bookmarks(request: BulkDeleteBookmarksRequest, username: str = Depends(get_current_user)):
    """Delete multiple bookmarks owned by the current user."""
    with modify_bookmarks() as data:
        ids_set = set(request.bookmark_ids)
        original = len(data["bookmarks"])
        data["bookmarks"] = [
            bm for bm in data["bookmarks"]
            if not (bm["id"] in ids_set and bm.get("username") == username)
        ]
        deleted = original - len(data["bookmarks"])
        if deleted == 0:
            raise HTTPException(status_code=404, detail="No bookmarks found to delete")
    return {"success": True, "deleted_count": deleted}


@router.post("/bookmarks/bulk-move")
async def bulk_move_bookmarks(request: BulkMoveBookmarksRequest, username: str = Depends(get_current_user)):
    """Move multiple bookmarks to a new topic (current user only)."""
    with modify_bookmarks() as data:
        ids_set = set(request.bookmark_ids)
        updated = 0
        for bm in data["bookmarks"]:
            if bm["id"] in ids_set and bm.get("username") == username:
                bm["topic"] = request.topic
                updated += 1
        if updated == 0:
            raise HTTPException(status_code=404, detail="No bookmarks found to update")
    return {"success": True, "updated_count": updated, "topic": request.topic}
