"""scripts/sync_blog_content.py: orchestration against a stub content checkout."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_blog_content.py"


def _stub_checkout(tmp_path: Path, posts: int = 2) -> Path:
    content = tmp_path / "content"
    (content / "scripts").mkdir(parents=True)
    (content / "figures").mkdir()
    (content / "figures" / "a.png").write_bytes(b"png")
    builder = content / "scripts" / "build_posts_index.py"
    builder.write_text(
        "import json, sys\n"
        "out = sys.argv[sys.argv.index('--out') + 1]\n"
        f"json.dump({{'posts': [{{'slug': f's{{i}}'}} for i in range({posts})]}}, open(out, 'w'))\n",
        encoding="utf-8",
    )
    return content


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_sync_builds_and_verifies_without_a_git_checkout(tmp_path: Path) -> None:
    content = _stub_checkout(tmp_path)
    result = _run("--content-dir", str(content))
    assert result.returncode == 0, result.stderr
    assert "content ok: 2 posts, 1 figures" in result.stdout
    assert json.loads((content / "posts.json").read_text())["posts"][0]["slug"] == "s0"


def test_check_mode_only_verifies(tmp_path: Path) -> None:
    content = _stub_checkout(tmp_path)
    assert _run("--content-dir", str(content), "--check").returncode == 1  # no posts.json yet
    assert _run("--content-dir", str(content), "--no-pull").returncode == 0
    assert _run("--content-dir", str(content), "--check").returncode == 0


def test_rejects_a_directory_that_is_not_a_content_checkout(tmp_path: Path) -> None:
    result = _run("--content-dir", str(tmp_path))
    assert result.returncode == 1
    assert "not a jiphyeonjeon-content checkout" in result.stderr


def test_empty_index_fails_verification(tmp_path: Path) -> None:
    content = _stub_checkout(tmp_path, posts=0)
    result = _run("--content-dir", str(content))
    assert result.returncode == 1
    assert "no posts" in result.stderr


def test_blog_router_reads_content_dir_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BLOG_CONTENT_DIR", str(tmp_path / "content"))
    import routers.blog as blog

    reloaded = importlib.reload(blog)
    try:
        assert reloaded.BLOG_DIR == Path(os.environ["BLOG_CONTENT_DIR"])
        assert reloaded.POSTS_FILE == reloaded.BLOG_DIR / "posts.json"
    finally:
        monkeypatch.delenv("BLOG_CONTENT_DIR")
        importlib.reload(blog)
