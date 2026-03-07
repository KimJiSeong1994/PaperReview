"""
Chat endpoint:
  POST /api/chat
"""

import json
import logging
from typing import List

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.requests import Request

from .deps import limiter, load_bookmarks, get_light_rag_agent, get_current_user, get_openai_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


# ── Pydantic models ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    messages: List[dict]  # [{"role": "user"|"assistant", "content": "..."}]
    bookmark_ids: List[str] = []  # empty = use all bookmarks


# ── Endpoint ───────────────────────────────────────────────────────────

@router.post("/chat")
@limiter.limit("20/minute")
async def chat_with_bookmarks(request: Request, chat_request: ChatRequest, username: str = Depends(get_current_user)):
    """Chat about bookmarked papers using their report content as context. Returns SSE stream."""

    # Load bookmark context — filtered to current user only
    data = load_bookmarks()
    bookmarks = [bm for bm in data.get("bookmarks", []) if bm.get("username") == username]

    if chat_request.bookmark_ids:
        bookmark_id_set = set(chat_request.bookmark_ids)
        bookmarks = [bm for bm in bookmarks if bm["id"] in bookmark_id_set]

    # Build context from bookmark reports with numbered references
    sources_metadata = []
    if not bookmarks:
        context_text = "(No bookmarked papers available.)"
    else:
        context_parts = []
        max_chars = 4000
        for idx, bm in enumerate(bookmarks[:10], start=1):
            report = bm.get("report_markdown", "")[:max_chars]
            papers_summary = ", ".join(p.get("title", "Untitled") for p in bm.get("papers", [])[:5])
            context_parts.append(
                f"[{idx}] Bookmark: {bm.get('title', 'Untitled')}\n"
                f"Query: {bm.get('query', 'N/A')}\n"
                f"Papers: {papers_summary}\n"
                f"Report:\n{report}\n"
            )
            sources_metadata.append(
                {
                    "ref": idx,
                    "id": bm["id"],
                    "title": bm.get("title", "Untitled"),
                    "num_papers": bm.get("num_papers", 0),
                }
            )
        context_text = "\n---\n".join(context_parts)

    # Inject high-significance highlights as key findings context
    highlights_context = ""
    if bookmarks:
        key_findings = []
        for bm in bookmarks[:10]:
            for hl in bm.get("highlights", []):
                sig = hl.get("significance", 3)
                if sig >= 4:
                    key_findings.append({
                        "text": hl.get("text", ""),
                        "category": hl.get("category", ""),
                        "section": hl.get("section", ""),
                        "significance": sig,
                        "bookmark": bm.get("title", ""),
                    })
        key_findings.sort(key=lambda x: x["significance"], reverse=True)
        if key_findings:
            hl_parts = []
            for kf in key_findings[:5]:
                hl_parts.append(f"- [{kf['category']}] {kf['text']}")
            highlights_context = "\n".join(hl_parts)

    # LightRAG: automatically query knowledge graph for additional context
    lightrag_context = ""
    user_query = ""
    for m in reversed(chat_request.messages):
        if m.get("role") == "user":
            user_query = m.get("content", "")
            break

    if user_query:
        try:
            agent = get_light_rag_agent()
            stats = agent.get_kg_stats()
            if stats and stats.get("kg_nodes", 0) > 0:
                kg_result = agent.light_query(
                    query=user_query, mode="hybrid", top_k=10, temperature=0.5
                )
                kg_answer = kg_result.get("answer", "")
                kg_entities = kg_result.get("retrieval", {}).get("entities", [])
                kg_relationships = kg_result.get("retrieval", {}).get("relationships", [])

                kg_parts = []
                if kg_entities:
                    entity_strs = [
                        f"- {e.get('name', '')} ({e.get('type', '')}): {e.get('description', '')}"
                        for e in kg_entities[:8]
                    ]
                    kg_parts.append("Key Entities:\n" + "\n".join(entity_strs))
                if kg_relationships:
                    rel_strs = [
                        f"- {r.get('source', '')} -> {r.get('target', '')}: {r.get('description', '')}"
                        for r in kg_relationships[:8]
                    ]
                    kg_parts.append("Relationships:\n" + "\n".join(rel_strs))
                if kg_answer:
                    kg_parts.append(f"Knowledge Graph Analysis:\n{kg_answer[:3000]}")

                if kg_parts:
                    lightrag_context = "\n\n".join(kg_parts)
        except Exception as e:
            logger.warning("LightRAG query skipped: %s", e)

    # Build system message with both bookmark and KG context
    system_parts = [
        "You are a research assistant helping users understand their bookmarked academic papers. "
        "You have access to the following bookmarked research reports and paper information. "
        "Each bookmark is numbered [1], [2], etc. When referencing information from the bookmarks, "
        "cite them using numbered references like [1], [2], etc. "
        "Answer questions based on this context. If the user asks about something not covered "
        "in the bookmarks, say so clearly. Respond in the same language the user uses.",
        f"\n\n=== BOOKMARKED PAPERS CONTEXT ===\n{context_text}\n=== END CONTEXT ===",
    ]

    if highlights_context:
        system_parts.append(
            f"\n\n=== KEY FINDINGS (user-highlighted) ===\n"
            f"The following are the most important findings highlighted by the user from their papers. "
            f"Prioritize these when answering related questions.\n\n"
            f"{highlights_context}\n=== END KEY FINDINGS ==="
        )

    if lightrag_context:
        system_parts.append(
            f"\n\n=== KNOWLEDGE GRAPH CONTEXT ===\n"
            f"The following additional information was retrieved from the knowledge graph built from your papers. "
            f"Use this to provide deeper, more connected insights.\n\n"
            f"{lightrag_context}\n=== END KNOWLEDGE GRAPH CONTEXT ==="
        )

    system_message = {"role": "system", "content": "".join(system_parts)}

    openai_messages = [system_message] + [
        {"role": m["role"], "content": m["content"]} for m in chat_request.messages
    ]

    client = get_openai_client()

    def generate():
        try:
            stream = client.chat.completions.create(
                model="gpt-5.2",
                messages=openai_messages,
                temperature=0.7,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield f"data: {json.dumps({'content': delta.content})}\n\n"
            if sources_metadata:
                yield f"data: {json.dumps({'sources': sources_metadata})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
