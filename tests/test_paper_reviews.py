"""Integration tests for per-paper review endpoints.

Covers:
  POST   /api/bookmarks/{bookmark_id}/papers/{paper_index}/review
  GET    /api/bookmarks/{bookmark_id}/papers/{paper_index}/review
  DELETE /api/bookmarks/{bookmark_id}/papers/{paper_index}/review
  POST   /api/math-explain
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from filelock import FileLock

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BOOKMARK_ID = "bm-review-test-001"
_USERNAME = "test-admin"

_PAPER = {
    "title": "Attention Is All You Need",
    "authors": ["Vaswani et al."],
    "year": "2017",
    "abstract": "We propose a new architecture called the Transformer.",
}

_REVIEW_MOCK = {
    "summary": "Test summary",
    "strengths": ["Good methodology"],
    "weaknesses": ["Limited scope"],
    "methodology_assessment": {
        "rigor": 4,
        "novelty": 3,
        "reproducibility": 3,
        "commentary": "Solid",
    },
    "key_contributions": ["Novel approach"],
    "questions_for_authors": ["How does it scale?"],
    "overall_score": 7,
    "confidence": 4,
    "detailed_review_markdown": (
        "## Summary\n"
        "Test review content that is long enough to pass validation checks "
        "for highlights generation minimum length requirement and then some more text."
    ),
    "created_at": "2024-01-01T00:00:00Z",
    "model": "gpt-4.1",
    "input_type": "abstract",
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_bookmarks_with_paper(tmp_path):
    """Initialise a temp bookmarks file containing one bookmark with one paper."""
    bf = tmp_path / "bookmarks.json"
    initial_data = {
        "bookmarks": [
            {
                "id": _BOOKMARK_ID,
                "username": _USERNAME,
                "title": "Test Bookmark",
                "papers": [_PAPER.copy()],
            }
        ]
    }
    bf.write_text(json.dumps(initial_data))

    with patch("routers.deps.storage.BOOKMARKS_FILE", bf):
        with patch(
            "routers.deps.storage._bookmarks_lock",
            FileLock(str(bf) + ".lock"),
        ):
            yield bf


@pytest.fixture
def mock_generate_review():
    """Patch generate_paper_review at the router import boundary."""
    with patch(
        "routers.paper_reviews.generate_paper_review",
        return_value=_REVIEW_MOCK,
    ) as m:
        yield m


@pytest.fixture
def mock_generate_highlights():
    """Patch generate_highlights to return an empty list (no-op for non-highlight tests)."""
    with patch(
        "routers.paper_reviews.generate_highlights",
        return_value=[],
    ) as m:
        yield m


@pytest.fixture
def mock_openai_client():
    """Patch get_openai_client used by math-explain."""
    with patch(
        "routers.paper_reviews.get_openai_client",
        return_value=MagicMock(),
    ) as m:
        yield m


# ---------------------------------------------------------------------------
# GET review — no LLM needed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_review_not_found(client, auth_headers):
    """Returns 404 when paper exists but has no review stored."""
    resp = await client.get(
        f"/api/bookmarks/{_BOOKMARK_ID}/papers/0/review",
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert "review" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_review_bookmark_not_found(client, auth_headers):
    """Returns 404 when the bookmark id does not exist."""
    resp = await client.get(
        "/api/bookmarks/nonexistent-bm/papers/0/review",
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert "bookmark" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# DELETE review — no LLM needed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_review_not_found_is_idempotent(client, auth_headers):
    """DELETE on a paper with no review still returns 200 (idempotent)."""
    resp = await client.delete(
        f"/api/bookmarks/{_BOOKMARK_ID}/papers/0/review",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# POST review — LLM mocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_review_success(
    client, auth_headers, mock_generate_review, mock_generate_highlights, mock_openai_client
):
    """POST review returns the mocked review and success flag."""
    resp = await client.post(
        f"/api/bookmarks/{_BOOKMARK_ID}/papers/0/review",
        json={"review_mode": "fast"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["review"]["summary"] == _REVIEW_MOCK["summary"]
    assert body["review"]["overall_score"] == _REVIEW_MOCK["overall_score"]
    # generate_paper_review was called exactly once
    mock_generate_review.assert_called_once()


@pytest.mark.asyncio
async def test_create_review_no_content(client, auth_headers, tmp_path):
    """Returns 400 when the paper has no title, abstract, or full_text."""
    # Write a bookmark whose paper has no reviewable content
    bf = tmp_path / "empty_paper_bookmarks.json"
    bf.write_text(
        json.dumps(
            {
                "bookmarks": [
                    {
                        "id": _BOOKMARK_ID,
                        "username": _USERNAME,
                        "title": "Test Bookmark",
                        "papers": [{}],  # completely empty paper
                    }
                ]
            }
        )
    )
    with patch("routers.deps.storage.BOOKMARKS_FILE", bf):
        with patch(
            "routers.deps.storage._bookmarks_lock",
            FileLock(str(bf) + ".lock"),
        ):
            resp = await client.post(
                f"/api/bookmarks/{_BOOKMARK_ID}/papers/0/review",
                json={"review_mode": "fast"},
                headers=auth_headers,
            )
    assert resp.status_code == 400
    assert "content" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_review_paper_index_out_of_range(
    client, auth_headers, mock_generate_review, mock_openai_client
):
    """Returns 400 when paper_index is beyond the papers list length."""
    resp = await client.post(
        f"/api/bookmarks/{_BOOKMARK_ID}/papers/99/review",
        json={"review_mode": "fast"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "out of range" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_review_no_auth(client):
    """Returns 401 when no Authorization header is provided."""
    resp = await client.post(
        f"/api/bookmarks/{_BOOKMARK_ID}/papers/0/review",
        json={"review_mode": "fast"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST math-explain — OpenAI client mocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_math_explain_success(client, auth_headers, mock_openai_client):
    """Returns structured explanation when OpenAI client returns valid JSON."""
    expected_response = {
        "explanation": "This formula computes the softmax of the input.",
        "variables": [{"symbol": "x", "meaning": "input logits"}],
        "formula_type": "probability",
    }

    # Build a mock response chain: client.chat.completions.create(...)
    mock_message = MagicMock()
    mock_message.content = json.dumps(expected_response)
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    mock_client_instance = mock_openai_client.return_value
    mock_client_instance.chat.completions.create.return_value = mock_completion

    # Bypass file-based LLM cache so the mock client is actually called
    with patch("routers.paper_reviews.get_cached", return_value=None):
        with patch("routers.paper_reviews.set_cache"):
            resp = await client.post(
                "/api/math-explain",
                json={
                    "formula_text": r"\text{softmax}(x_i) = \frac{e^{x_i}}{\sum_j e^{x_j}}",
                    "context": "Equation 1 in the attention mechanism section.",
                    "paper_title": "Attention Is All You Need",
                },
                headers=auth_headers,
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["explanation"] == expected_response["explanation"]
    assert body["formula_type"] == expected_response["formula_type"]
    assert isinstance(body["variables"], list)


@pytest.mark.asyncio
async def test_math_explain_empty_formula(client, auth_headers):
    """Returns 400 when formula_text is an empty string."""
    resp = await client.post(
        "/api/math-explain",
        json={"formula_text": "   ", "context": "some context"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "formula_text" in resp.json()["detail"].lower()
