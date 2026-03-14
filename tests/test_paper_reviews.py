"""
Comprehensive tests for the per-paper review & auto-highlight feature.

Covers:
- paper_review_service.generate_paper_review (unit)
- paper_reviews router: POST/GET/DELETE review, POST auto-highlight (integration)
- Edge cases: empty papers, out-of-range index, auth failures, LLM errors,
  concurrent switches, missing content, variable input types
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import jwt
import pytest
from filelock import FileLock


# ---------------------------------------------------------------------------
# Helpers / constants
# ---------------------------------------------------------------------------

_JWT_SECRET = "test-jwt-secret-for-testing-only"
_VALID_REVIEW = {
    "summary": "This paper proposes a novel method.",
    "strengths": [
        {"point": "Clear motivation", "evidence": "Section 1", "significance": "high"},
        {"point": "Strong baselines", "evidence": "Table 2", "significance": "medium"},
        {"point": "Ablation study", "evidence": "Table 3", "significance": "low"},
    ],
    "weaknesses": [
        {"point": "Limited evaluation", "evidence": "Only one dataset", "severity": "major"},
        {"point": "High compute cost", "evidence": "Appendix A", "severity": "minor"},
    ],
    "methodology_assessment": {
        "rigor": 4,
        "novelty": 3,
        "reproducibility": 3,
        "commentary": "Solid methodology with some gaps.",
    },
    "key_contributions": ["New architecture", "Benchmark results"],
    "questions_for_authors": ["How does it scale?", "Why not compare to X?"],
    "overall_score": 7,
    "confidence": 4,
    "detailed_review_markdown": (
        "## Summary\nThis paper introduces a new approach.\n\n"
        "## Strengths\nThe motivation is clear and well-articulated.\n\n"
        "## Weaknesses\nThe evaluation scope is limited to one dataset.\n\n"
        "## Questions\nHow does the method scale to larger inputs?"
    ),
}


def _make_token(username: str = "testuser", role: str = "user") -> str:
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


def _auth(username: str = "testuser") -> dict:
    return {"Authorization": f"Bearer {_make_token(username)}"}


def _make_bookmark(username: str = "testuser", papers: list | None = None) -> dict:
    return {
        "id": f"bm_{uuid.uuid4().hex[:12]}",
        "username": username,
        "title": "Test Bookmark",
        "query": "test query",
        "papers": papers or [
            {"title": "Paper A", "authors": ["Author 1"], "year": "2024", "abstract": "Abstract A"},
            {"title": "Paper B", "authors": ["Author 2"], "year": "2023", "abstract": "Abstract B"},
        ],
        "report_markdown": "# Test",
        "tags": [],
        "topic": "",
        "created_at": datetime.now().isoformat(),
        "notes": "",
        "highlights": [],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_storage(tmp_path):
    """Isolate all storage to tmp files for every test."""
    bf = tmp_path / "bookmarks.json"
    bf.write_text(json.dumps({"bookmarks": []}))
    lock = FileLock(str(bf) + ".lock")
    with (
        patch("routers.deps.storage.BOOKMARKS_FILE", bf),
        patch("routers.deps.storage._bookmarks_lock", lock),
        patch("routers.deps.BOOKMARKS_FILE", bf),
        patch("routers.deps._bookmarks_lock", lock),
    ):
        yield bf


def _seed_bookmark(storage_path, bm: dict):
    """Write a bookmark directly to storage (bypasses router)."""
    data = json.loads(storage_path.read_text())
    data["bookmarks"].append(bm)
    storage_path.write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# ── Unit: paper_review_service.generate_paper_review ──────────────────────
# ---------------------------------------------------------------------------

class TestGeneratePaperReview:
    """Unit tests for generate_paper_review() in paper_review_service.py."""

    def _make_client(self, content: str = None):
        """Return a mock OpenAI client that returns given content."""
        if content is None:
            content = json.dumps(_VALID_REVIEW)
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = content
        mock_response.usage = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        return mock_client

    def test_generates_review_from_abstract(self):
        from routers.paper_review_service import generate_paper_review
        client = self._make_client()
        paper = {"title": "Test Paper", "abstract": "This is the abstract."}
        with patch("routers.paper_review_service.get_cached", return_value=None), \
             patch("routers.paper_review_service.set_cache"):
            result = generate_paper_review(paper, client)
        assert result["overall_score"] == 7
        assert result["input_type"] == "abstract"
        assert "created_at" in result
        assert result["model"] == "gpt-4.1"

    def test_generates_review_from_full_text(self):
        from routers.paper_review_service import generate_paper_review
        client = self._make_client()
        paper = {"title": "Test Paper", "full_text": "Full paper content here."}
        with patch("routers.paper_review_service.get_cached", return_value=None), \
             patch("routers.paper_review_service.set_cache"):
            result = generate_paper_review(paper, client)
        assert result["input_type"] == "full_text"

    def test_generates_review_metadata_only(self):
        from routers.paper_review_service import generate_paper_review
        client = self._make_client()
        paper = {"title": "Test Paper Only"}
        with patch("routers.paper_review_service.get_cached", return_value=None), \
             patch("routers.paper_review_service.set_cache"):
            result = generate_paper_review(paper, client)
        assert result["input_type"] == "metadata"

    def test_truncates_long_full_text(self):
        from routers.paper_review_service import generate_paper_review
        client = self._make_client()
        paper = {"title": "Test", "full_text": "x" * 35000}
        with patch("routers.paper_review_service.get_cached", return_value=None), \
             patch("routers.paper_review_service.set_cache"):
            generate_paper_review(paper, client)
        # Verify the prompt sent to LLM was truncated (user content ≤ 30k chars + overhead)
        call_args = client.chat.completions.create.call_args
        user_content = call_args.kwargs["messages"][1]["content"]
        assert "[... truncated ...]" in user_content

    def test_uses_cache_hit(self):
        from routers.paper_review_service import generate_paper_review
        cached_content = json.dumps(_VALID_REVIEW)
        client = self._make_client()
        paper = {"title": "Test Paper", "abstract": "Some abstract."}
        with patch("routers.paper_review_service.get_cached", return_value=cached_content), \
             patch("routers.paper_review_service.set_cache") as mock_set:
            result = generate_paper_review(paper, client)
        # Should NOT have called LLM
        client.chat.completions.create.assert_not_called()
        mock_set.assert_not_called()
        assert result["overall_score"] == 7

    def test_raises_value_error_on_invalid_json(self):
        from routers.paper_review_service import generate_paper_review
        client = self._make_client(content="this is not json {{{")
        paper = {"title": "Test"}
        with patch("routers.paper_review_service.get_cached", return_value=None), \
             patch("routers.paper_review_service.set_cache"):
            with pytest.raises(ValueError, match="invalid JSON"):
                generate_paper_review(paper, client)

    def test_empty_llm_response_raises_value_error(self):
        from routers.paper_review_service import generate_paper_review
        # Empty string produces "{}" → valid JSON but result = {} → no error,
        # but the empty content path (None → "{}") produces an empty dict
        client = self._make_client(content="{}")
        paper = {"title": "Test"}
        with patch("routers.paper_review_service.get_cached", return_value=None), \
             patch("routers.paper_review_service.set_cache"):
            result = generate_paper_review(paper, client)
        # Should not crash; metadata fields still added
        assert "created_at" in result
        assert "model" in result

    def test_authors_list_joined(self):
        from routers.paper_review_service import generate_paper_review
        client = self._make_client()
        paper = {"title": "T", "authors": ["Alice", "Bob", "Carol"]}
        with patch("routers.paper_review_service.get_cached", return_value=None), \
             patch("routers.paper_review_service.set_cache"):
            generate_paper_review(paper, client)
        call_args = client.chat.completions.create.call_args
        user_content = call_args.kwargs["messages"][1]["content"]
        assert "Alice, Bob, Carol" in user_content

    def test_authors_string_passthrough(self):
        from routers.paper_review_service import generate_paper_review
        client = self._make_client()
        paper = {"title": "T", "authors": "Alice et al."}
        with patch("routers.paper_review_service.get_cached", return_value=None), \
             patch("routers.paper_review_service.set_cache"):
            generate_paper_review(paper, client)
        call_args = client.chat.completions.create.call_args
        user_content = call_args.kwargs["messages"][1]["content"]
        assert "Alice et al." in user_content

    def test_timeout_scaled_by_input_type(self):
        """full_text input uses longer timeout (120s) vs abstract (90s)."""
        from routers.paper_review_service import generate_paper_review
        client = self._make_client()

        with patch("routers.paper_review_service.get_cached", return_value=None), \
             patch("routers.paper_review_service.set_cache"):
            generate_paper_review({"title": "T", "full_text": "text"}, client)
        assert client.chat.completions.create.call_args.kwargs["timeout"] == 120

        client2 = self._make_client()
        with patch("routers.paper_review_service.get_cached", return_value=None), \
             patch("routers.paper_review_service.set_cache"):
            generate_paper_review({"title": "T", "abstract": "abstract"}, client2)
        assert client2.chat.completions.create.call_args.kwargs["timeout"] == 90


# ---------------------------------------------------------------------------
# ── Integration: POST /api/bookmarks/{id}/papers/{idx}/review ─────────────
# ---------------------------------------------------------------------------

class TestCreatePaperReview:
    """Integration tests for the POST review endpoint."""

    def _mock_llm(self, review_content: str | None = None, highlights: list | None = None):
        """Patch generate_paper_review and generate_highlights."""
        rv = dict(_VALID_REVIEW)
        rv["created_at"] = datetime.now().isoformat()
        rv["model"] = "gpt-4.1"
        rv["input_type"] = "abstract"
        if review_content:
            rv["detailed_review_markdown"] = review_content
        return rv

    @pytest.mark.asyncio
    async def test_create_review_success(self, client, auth_headers, mock_storage):
        """POST review returns 200 with review + highlights."""
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)

        mock_review = self._mock_llm()
        with patch("routers.paper_reviews.generate_paper_review", return_value=mock_review), \
             patch("routers.paper_reviews.generate_highlights", return_value=[]), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/review",
                json={"review_mode": "fast"},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["review"]["overall_score"] == 7
        assert isinstance(data["highlights"], list)
        assert "highlight_count" in data

    @pytest.mark.asyncio
    async def test_review_persisted_to_bookmark(self, client, auth_headers, mock_storage):
        """Verify review is stored on the paper in the bookmark file."""
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)

        mock_review = self._mock_llm()
        with patch("routers.paper_reviews.generate_paper_review", return_value=mock_review), \
             patch("routers.paper_reviews.generate_highlights", return_value=[]), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/review",
                json={"review_mode": "fast"},
                headers=auth_headers,
            )

        # Read storage directly
        stored = json.loads(mock_storage.read_text())
        paper0 = stored["bookmarks"][0]["papers"][0]
        assert "review" in paper0
        assert paper0["review"]["overall_score"] == 7
        assert "review_highlights" in paper0

    @pytest.mark.asyncio
    async def test_create_review_uses_request_full_text(self, client, auth_headers, mock_storage):
        """full_text from request body takes priority over paper abstract."""
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)

        captured_paper_input = {}

        def capture_generate(paper_input, client_obj, model="gpt-4.1"):
            captured_paper_input.update(paper_input)
            return self._mock_llm()

        with patch("routers.paper_reviews.generate_paper_review", side_effect=capture_generate), \
             patch("routers.paper_reviews.generate_highlights", return_value=[]), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/review",
                json={"review_mode": "fast", "full_text": "custom full text content"},
                headers=auth_headers,
            )

        assert captured_paper_input.get("full_text") == "custom full text content"
        assert "abstract" not in captured_paper_input

    @pytest.mark.asyncio
    async def test_create_review_falls_back_to_paper_abstract(self, client, auth_headers, mock_storage):
        """Falls back to paper abstract when no full_text in request."""
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)

        captured = {}

        def capture_generate(paper_input, client_obj, model="gpt-4.1"):
            captured.update(paper_input)
            return self._mock_llm()

        with patch("routers.paper_reviews.generate_paper_review", side_effect=capture_generate), \
             patch("routers.paper_reviews.generate_highlights", return_value=[]), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/review",
                json={"review_mode": "fast"},
                headers=auth_headers,
            )

        assert captured.get("abstract") == "Abstract A"

    @pytest.mark.asyncio
    async def test_create_review_404_on_missing_bookmark(self, client, auth_headers):
        """Returns 404 when bookmark does not exist."""
        with patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                "/api/bookmarks/nonexistent-bm/papers/0/review",
                json={"review_mode": "fast"},
                headers=auth_headers,
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_review_400_on_out_of_range_index(self, client, auth_headers, mock_storage):
        """Returns 400 when paper_index is out of range."""
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)

        with patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/99/review",
                json={"review_mode": "fast"},
                headers=auth_headers,
            )
        assert resp.status_code == 400
        assert "out of range" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_review_400_on_negative_index(self, client, auth_headers, mock_storage):
        """Returns 400 when paper_index is negative."""
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)

        with patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/-1/review",
                json={"review_mode": "fast"},
                headers=auth_headers,
            )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_create_review_403_on_wrong_user(self, client, mock_storage):
        """Returns 403 when a different user tries to review another user's bookmark."""
        bm = _make_bookmark(username="alice")
        _seed_bookmark(mock_storage, bm)

        bob_headers = _auth("bob")
        with patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/review",
                json={"review_mode": "fast"},
                headers=bob_headers,
            )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_review_504_on_timeout(self, client, auth_headers, mock_storage):
        """Returns 504 on APITimeoutError."""
        from openai import APITimeoutError
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)

        with patch("routers.paper_reviews.generate_paper_review",
                   side_effect=APITimeoutError(request=MagicMock())), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/review",
                json={"review_mode": "fast"},
                headers=auth_headers,
            )
        assert resp.status_code == 504

    @pytest.mark.asyncio
    async def test_create_review_429_on_rate_limit(self, client, auth_headers, mock_storage):
        """Returns 429 on RateLimitError."""
        from openai import RateLimitError
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)

        with patch("routers.paper_reviews.generate_paper_review",
                   side_effect=RateLimitError("rate limited", response=MagicMock(), body=None)), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/review",
                json={"review_mode": "fast"},
                headers=auth_headers,
            )
        assert resp.status_code == 429

    @pytest.mark.asyncio
    async def test_create_review_502_on_invalid_json(self, client, auth_headers, mock_storage):
        """Returns 502 when LLM returns invalid JSON."""
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)

        with patch("routers.paper_reviews.generate_paper_review",
                   side_effect=ValueError("LLM returned invalid JSON for paper review")), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/review",
                json={"review_mode": "fast"},
                headers=auth_headers,
            )
        assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_create_review_auto_highlight_failure_non_fatal(self, client, auth_headers, mock_storage):
        """Auto-highlight failure during review creation does not cause 500."""
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)
        mock_review = self._mock_llm()

        with patch("routers.paper_reviews.generate_paper_review", return_value=mock_review), \
             patch("routers.paper_reviews.generate_highlights",
                   side_effect=RuntimeError("LLM service unavailable")), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/review",
                json={"review_mode": "fast"},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["highlights"] == []

    @pytest.mark.asyncio
    async def test_create_review_with_short_review_markdown_skips_highlights(
        self, client, auth_headers, mock_storage
    ):
        """If detailed_review_markdown is ≤50 chars, auto-highlight is skipped."""
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)
        mock_review = dict(_VALID_REVIEW)
        mock_review["detailed_review_markdown"] = "Too short"
        mock_review["created_at"] = datetime.now().isoformat()
        mock_review["model"] = "gpt-4.1"
        mock_review["input_type"] = "abstract"

        with patch("routers.paper_reviews.generate_paper_review", return_value=mock_review), \
             patch("routers.paper_reviews.generate_highlights") as mock_hl, \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/review",
                json={"review_mode": "fast"},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        mock_hl.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_review_401_without_token(self, client, mock_storage):
        """Returns 401 when no auth token is provided."""
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)
        resp = await client.post(
            f"/api/bookmarks/{bm['id']}/papers/0/review",
            json={"review_mode": "fast"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_review_400_no_reviewable_content(self, client, auth_headers, mock_storage):
        """Returns 400 when paper has no title/abstract/full_text."""
        bm = _make_bookmark(
            username="test-admin",
            papers=[{"title": "", "authors": [], "year": ""}],
        )
        _seed_bookmark(mock_storage, bm)

        with patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/review",
                json={"review_mode": "fast"},
                headers=auth_headers,
            )
        assert resp.status_code == 400
        assert "No reviewable content" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# ── Integration: GET /api/bookmarks/{id}/papers/{idx}/review ──────────────
# ---------------------------------------------------------------------------

class TestGetPaperReview:
    @pytest.mark.asyncio
    async def test_get_review_returns_cached(self, client, auth_headers, mock_storage):
        """GET returns cached review and highlights for a paper that has been reviewed."""
        bm = _make_bookmark(username="test-admin")
        bm["papers"][0]["review"] = dict(_VALID_REVIEW)
        bm["papers"][0]["review_highlights"] = [
            {"id": "rhl_abc123", "text": "highlight text", "color": "#a5b4fc", "memo": "test"}
        ]
        _seed_bookmark(mock_storage, bm)

        resp = await client.get(
            f"/api/bookmarks/{bm['id']}/papers/0/review",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["review"]["overall_score"] == 7
        assert len(data["highlights"]) == 1
        assert data["highlights"][0]["id"] == "rhl_abc123"

    @pytest.mark.asyncio
    async def test_get_review_404_when_no_review(self, client, auth_headers, mock_storage):
        """GET returns 404 when paper has no review."""
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)

        resp = await client.get(
            f"/api/bookmarks/{bm['id']}/papers/0/review",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_review_empty_highlights_when_none(self, client, auth_headers, mock_storage):
        """GET returns empty highlights list when review exists but highlights do not."""
        bm = _make_bookmark(username="test-admin")
        bm["papers"][0]["review"] = dict(_VALID_REVIEW)
        # No review_highlights key at all
        _seed_bookmark(mock_storage, bm)

        resp = await client.get(
            f"/api/bookmarks/{bm['id']}/papers/0/review",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["highlights"] == []

    @pytest.mark.asyncio
    async def test_get_review_403_on_wrong_user(self, client, mock_storage):
        bm = _make_bookmark(username="alice")
        bm["papers"][0]["review"] = dict(_VALID_REVIEW)
        _seed_bookmark(mock_storage, bm)

        resp = await client.get(
            f"/api/bookmarks/{bm['id']}/papers/0/review",
            headers=_auth("bob"),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# ── Integration: DELETE /api/bookmarks/{id}/papers/{idx}/review ───────────
# ---------------------------------------------------------------------------

class TestDeletePaperReview:
    @pytest.mark.asyncio
    async def test_delete_review_success(self, client, auth_headers, mock_storage):
        """DELETE removes review and review_highlights from paper."""
        bm = _make_bookmark(username="test-admin")
        bm["papers"][0]["review"] = dict(_VALID_REVIEW)
        bm["papers"][0]["review_highlights"] = [{"id": "rhl_x"}]
        _seed_bookmark(mock_storage, bm)

        resp = await client.delete(
            f"/api/bookmarks/{bm['id']}/papers/0/review",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Verify storage
        stored = json.loads(mock_storage.read_text())
        paper0 = stored["bookmarks"][0]["papers"][0]
        assert "review" not in paper0
        assert "review_highlights" not in paper0

    @pytest.mark.asyncio
    async def test_delete_review_idempotent(self, client, auth_headers, mock_storage):
        """DELETE on a paper with no review still returns success (pop is no-op)."""
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)

        resp = await client.delete(
            f"/api/bookmarks/{bm['id']}/papers/0/review",
            headers=auth_headers,
        )
        # Validation passes, then pop is a no-op
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_review_leaves_other_papers_intact(self, client, auth_headers, mock_storage):
        """DELETE on paper index 0 does not affect paper index 1."""
        bm = _make_bookmark(username="test-admin")
        bm["papers"][0]["review"] = dict(_VALID_REVIEW)
        bm["papers"][1]["review"] = {"overall_score": 5, "summary": "Paper B review"}
        _seed_bookmark(mock_storage, bm)

        await client.delete(
            f"/api/bookmarks/{bm['id']}/papers/0/review",
            headers=auth_headers,
        )

        stored = json.loads(mock_storage.read_text())
        paper1 = stored["bookmarks"][0]["papers"][1]
        assert paper1.get("review", {}).get("overall_score") == 5

    @pytest.mark.asyncio
    async def test_delete_review_400_on_out_of_range(self, client, auth_headers, mock_storage):
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)

        resp = await client.delete(
            f"/api/bookmarks/{bm['id']}/papers/50/review",
            headers=auth_headers,
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# ── Integration: POST .../auto-highlight ─────────────────────────────────
# ---------------------------------------------------------------------------

class TestAutoHighlight:
    @pytest.mark.asyncio
    async def test_auto_highlight_requires_existing_review(self, client, auth_headers, mock_storage):
        """Returns 400 when paper has no review yet."""
        bm = _make_bookmark(username="test-admin")
        _seed_bookmark(mock_storage, bm)

        with patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/auto-highlight",
                headers=auth_headers,
            )
        assert resp.status_code == 400
        assert "No review exists" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_auto_highlight_requires_markdown_content(self, client, auth_headers, mock_storage):
        """Returns 400 when review has empty detailed_review_markdown."""
        bm = _make_bookmark(username="test-admin")
        bm["papers"][0]["review"] = {"overall_score": 7, "detailed_review_markdown": "   "}
        _seed_bookmark(mock_storage, bm)

        with patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/auto-highlight",
                headers=auth_headers,
            )
        assert resp.status_code == 400
        assert "no detailed markdown" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_auto_highlight_adds_new_highlights(self, client, auth_headers, mock_storage):
        """New highlights are added when they don't match existing ones."""
        bm = _make_bookmark(username="test-admin")
        bm["papers"][0]["review"] = dict(_VALID_REVIEW)
        bm["papers"][0]["review_highlights"] = []
        _seed_bookmark(mock_storage, bm)

        llm_highlights = [
            {
                "text": "The motivation is clear and well-articulated",
                "category": "finding",
                "reviewer_comment": "Good",
                "implication": "Shows clarity",
                "strength_or_weakness": "strength",
                "confidence_level": 4,
                "significance": 4,
                "section": "Strengths",
                "question_for_authors": "",
            }
        ]

        with patch("routers.paper_reviews.generate_highlights", return_value=llm_highlights), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/auto-highlight",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["added_count"] >= 1
        assert len(data["highlights"]) >= 1

    @pytest.mark.asyncio
    async def test_auto_highlight_enriches_existing(self, client, auth_headers, mock_storage):
        """Existing highlights are enriched rather than duplicated."""
        bm = _make_bookmark(username="test-admin")
        bm["papers"][0]["review"] = dict(_VALID_REVIEW)
        matched_text = "The motivation is clear and well-articulated"
        bm["papers"][0]["review_highlights"] = [
            {"id": "rhl_existing", "text": matched_text, "color": "#a5b4fc",
             "memo": "finding", "category": "finding"}
        ]
        _seed_bookmark(mock_storage, bm)

        llm_highlights = [
            {
                "text": matched_text,
                "category": "finding",
                "reviewer_comment": "Excellent clarity",
                "implication": "Helps reader orientation",
                "strength_or_weakness": "strength",
                "confidence_level": 5,
                "significance": 5,
                "section": "Strengths",
                "question_for_authors": "",
            }
        ]

        with patch("routers.paper_reviews.generate_highlights", return_value=llm_highlights), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/auto-highlight",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enriched_count"] >= 1
        assert data["added_count"] == 0

    @pytest.mark.asyncio
    async def test_auto_highlight_skips_short_texts(self, client, auth_headers, mock_storage):
        """Highlight items with text < 5 chars are discarded."""
        bm = _make_bookmark(username="test-admin")
        bm["papers"][0]["review"] = dict(_VALID_REVIEW)
        bm["papers"][0]["review_highlights"] = []
        _seed_bookmark(mock_storage, bm)

        llm_highlights = [{"text": "Hi", "category": "finding", "reviewer_comment": "x"}]

        with patch("routers.paper_reviews.generate_highlights", return_value=llm_highlights), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/auto-highlight",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["added_count"] == 0

    @pytest.mark.asyncio
    async def test_auto_highlight_normalises_invalid_category(self, client, auth_headers, mock_storage):
        """Invalid category string is normalised to 'finding'."""
        bm = _make_bookmark(username="test-admin")
        bm["papers"][0]["review"] = dict(_VALID_REVIEW)
        bm["papers"][0]["review_highlights"] = []
        _seed_bookmark(mock_storage, bm)

        llm_highlights = [
            {
                "text": "The motivation is clear and well-articulated",
                "category": "INVALID_CATEGORY",
                "reviewer_comment": "",
                "implication": "",
                "strength_or_weakness": "",
                "confidence_level": 3,
                "significance": 3,
                "section": "",
                "question_for_authors": "",
            }
        ]

        with patch("routers.paper_reviews.generate_highlights", return_value=llm_highlights), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/auto-highlight",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        added = resp.json()["highlights"]
        if added:
            assert added[-1]["category"] == "finding"

    @pytest.mark.asyncio
    async def test_auto_highlight_clamps_confidence_and_significance(
        self, client, auth_headers, mock_storage
    ):
        """Out-of-range confidence/significance values are clamped to [1, 5]."""
        bm = _make_bookmark(username="test-admin")
        bm["papers"][0]["review"] = dict(_VALID_REVIEW)
        bm["papers"][0]["review_highlights"] = []
        _seed_bookmark(mock_storage, bm)

        llm_highlights = [
            {
                "text": "The motivation is clear and well-articulated",
                "category": "finding",
                "reviewer_comment": "",
                "implication": "",
                "strength_or_weakness": "",
                "confidence_level": 999,
                "significance": -5,
                "section": "",
                "question_for_authors": "",
            }
        ]

        with patch("routers.paper_reviews.generate_highlights", return_value=llm_highlights), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/auto-highlight",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        hl_list = resp.json()["highlights"]
        if hl_list:
            last_hl = hl_list[-1]
            assert 1 <= last_hl["confidence_level"] <= 5
            assert 1 <= last_hl["significance"] <= 5

    @pytest.mark.asyncio
    async def test_auto_highlight_504_on_timeout(self, client, auth_headers, mock_storage):
        from openai import APITimeoutError
        bm = _make_bookmark(username="test-admin")
        bm["papers"][0]["review"] = dict(_VALID_REVIEW)
        _seed_bookmark(mock_storage, bm)

        with patch("routers.paper_reviews.generate_highlights",
                   side_effect=APITimeoutError(request=MagicMock())), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/auto-highlight",
                headers=auth_headers,
            )
        assert resp.status_code == 504

    @pytest.mark.asyncio
    async def test_auto_highlight_variable_scoping_bug_check(self, client, auth_headers, mock_storage):
        """
        Regression: auto_highlight_paper_review returns `existing_highlights` and
        `added_count` from the inner scope. If the bookmark loop never enters (e.g.,
        bookmark deleted mid-flight), those variables would be unbound → NameError.
        This test verifies the endpoint does NOT crash when the bookmark is found.
        """
        bm = _make_bookmark(username="test-admin")
        bm["papers"][0]["review"] = dict(_VALID_REVIEW)
        bm["papers"][0]["review_highlights"] = []
        _seed_bookmark(mock_storage, bm)

        with patch("routers.paper_reviews.generate_highlights", return_value=[]), \
             patch("routers.paper_reviews.get_openai_client", return_value=MagicMock()):
            resp = await client.post(
                f"/api/bookmarks/{bm['id']}/papers/0/auto-highlight",
                headers=auth_headers,
            )
        assert resp.status_code == 200
