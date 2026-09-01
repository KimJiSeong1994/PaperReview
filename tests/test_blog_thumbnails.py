"""List thumbnails (``PostSummary.thumbnail_url``) and width-constrained figures."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api_server import app
import routers.blog as blog


_SHARED = {
    "author": "test-admin",
    "updated_at": None,
    "published": True,
    "reading_time_min": 1,
    "tags": [],
    "category": "paper-review",
    "excerpt": "요약.",
}

POSTS = [
    {
        **_SHARED,
        "id": "own",
        "title": "자체 썸네일",
        "slug": "own-thumb",
        "thumbnail_url": "/api/blog/figures/cover.png",
        "created_at": "2026-01-03T00:00:00+09:00",
        # An inline figure that must lose to the post's own thumbnail.
        "content": "본문\n\n![그림](/api/blog/figures/inline-a.png)\n",
    },
    {
        **_SHARED,
        "id": "placeholder",
        "title": "플레이스홀더",
        "slug": "placeholder-thumb",
        "thumbnail_url": "/og-default.jpg",
        "created_at": "2026-01-02T00:00:00+09:00",
        "content": "앞\n\n![첫 그림](/api/blog/figures/inline-b.png)\n\n![둘째](/api/blog/figures/inline-c.png)\n",
    },
    {
        **_SHARED,
        "id": "bare",
        "title": "그림 없음",
        "slug": "bare-post",
        "thumbnail_url": None,
        "created_at": "2026-01-01T00:00:00+09:00",
        "content": "그림이 하나도 없는 본문.",
    },
]


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(blog, "_load_posts", lambda: [dict(p) for p in POSTS])
    return TestClient(app)


def _by_slug(client: TestClient) -> dict[str, dict]:
    body = client.get("/api/blog/posts", params={"limit": 100}).json()
    return {p["slug"]: p for p in body["posts"]}


def test_own_thumbnail_wins_over_inline_figure(client: TestClient) -> None:
    assert _by_slug(client)["own-thumb"]["thumbnail_url"] == "/api/blog/figures/cover.png"


def test_placeholder_falls_back_to_first_inline_figure(client: TestClient) -> None:
    """The placeholder must never reach the list — 37 posts share it."""
    post = _by_slug(client)["placeholder-thumb"]
    assert post["thumbnail_url"] == "/api/blog/figures/inline-b.png"


def test_no_thumbnail_and_no_figure_is_none(client: TestClient) -> None:
    assert _by_slug(client)["bare-post"]["thumbnail_url"] is None


def test_list_still_omits_content(client: TestClient) -> None:
    assert all("content" not in p for p in _by_slug(client).values())


# ── Figure serving ────────────────────────────────────────────────────


@pytest.fixture
def figures(monkeypatch, tmp_path: Path) -> Path:
    """Point BLOG_DIR at a temp dir holding one 900px-wide PNG."""
    from PIL import Image

    fig_dir = tmp_path / "figures"
    fig_dir.mkdir()
    Image.new("RGB", (900, 500), "navy").save(fig_dir / "big.png")
    monkeypatch.setattr(blog, "BLOG_DIR", tmp_path)
    return fig_dir


def test_no_width_serves_original_bytes(figures: Path) -> None:
    client = TestClient(app)
    response = client.get("/api/blog/figures/big.png")

    assert response.status_code == 200
    assert response.content == (figures / "big.png").read_bytes()
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert not (figures / ".cache").exists()


@pytest.mark.parametrize("width", sorted(blog._FIGURE_WIDTHS))
def test_allowed_widths_shrink_the_image(figures: Path, width: int) -> None:
    import io

    from PIL import Image

    response = TestClient(app).get("/api/blog/figures/big.png", params={"w": width})

    assert response.status_code == 200
    assert Image.open(io.BytesIO(response.content)).width == width
    assert len(response.content) < (figures / "big.png").stat().st_size


@pytest.mark.parametrize("width", [1, 227, 1000, -228, 0])
def test_disallowed_width_is_rejected(figures: Path, width: int) -> None:
    assert TestClient(app).get("/api/blog/figures/big.png", params={"w": width}).status_code == 400


def test_resize_is_cached_on_disk(figures: Path) -> None:
    client = TestClient(app)
    first = client.get("/api/blog/figures/big.png", params={"w": 228})

    cached = figures / ".cache" / "228" / "big.png"
    assert cached.is_file()
    assert not list(cached.parent.glob("*.tmp"))

    # Second call must serve the cached file, not re-encode: proven by
    # rewriting the cache entry and seeing the new bytes come back.
    from PIL import Image

    Image.new("RGB", (228, 127), "red").save(cached)
    second = client.get("/api/blog/figures/big.png", params={"w": 228})
    assert second.content == cached.read_bytes()
    assert second.content != first.content


def test_never_upscales(figures: Path) -> None:
    from PIL import Image

    Image.new("RGB", (100, 60), "green").save(figures / "small.png")
    response = TestClient(app).get("/api/blog/figures/small.png", params={"w": 640})

    assert response.content == (figures / "small.png").read_bytes()
    assert not (figures / ".cache").exists()


def test_corrupt_image_falls_back_to_original(figures: Path) -> None:
    (figures / "broken.png").write_bytes(b"not an image at all")
    response = TestClient(app).get("/api/blog/figures/broken.png", params={"w": 228})

    assert response.status_code == 200
    assert response.content == b"not an image at all"


def test_cache_directory_is_not_servable(figures: Path) -> None:
    (figures / ".cache" / "228").mkdir(parents=True)
    assert TestClient(app).get("/api/blog/figures/.cache").status_code == 404


@pytest.mark.parametrize(
    "name", ["../posts.json", "..%2Fposts.json", "sub/big.png", "..\\posts.json"]
)
def test_traversal_attempts_are_refused(figures: Path, name: str) -> None:
    (figures.parent / "posts.json").write_text("secret")
    response = TestClient(app).get(f"/api/blog/figures/{name}")

    assert response.status_code in (400, 404)
    assert b"secret" not in response.content


def test_failed_resize_leaves_no_temp_file(figures: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A save that dies mid-write must not leave its .tmp behind.

    The write is atomic (tmp + os.replace) so a reader never sees a partial
    file, but without cleanup every retry on a figure that cannot be encoded
    would drop another temp file into the cache directory forever.
    """
    from PIL import Image

    def explode(self: Image.Image, fp: object, format: object = None, **kw: object) -> None:
        Path(str(fp)).write_bytes(b"partial")  # the half-written file
        raise OSError("encoder ran out of space")

    monkeypatch.setattr(Image.Image, "save", explode)
    response = TestClient(app).get("/api/blog/figures/big.png", params={"w": 228})

    assert response.status_code == 200  # still served, from the original
    leftovers = list((figures / ".cache").rglob("*.tmp"))
    assert leftovers == [], f"temp files left behind: {leftovers}"
