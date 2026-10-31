#!/usr/bin/env python3
"""Sync blog content from the jiphyeonjeon-content checkout the server reads.

Pulls the content repo (fast-forward only), rebuilds ``posts.json`` from
``posts/*.md`` with the content repo's own build script, and verifies the
result. The app reads ``BLOG_CONTENT_DIR`` (routers/blog.py), so point that at
the same checkout.

    python scripts/sync_blog_content.py --content-dir ~/jiphyeonjeon-content
    python scripts/sync_blog_content.py --check   # verify only, no pull/build
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def verify(content_dir: Path) -> tuple[int, int]:
    """Return (post count, figure count); raise if the checkout is unusable."""
    posts_file = content_dir / "posts.json"
    index = json.loads(posts_file.read_text(encoding="utf-8"))
    posts = index["posts"] if isinstance(index, dict) else index
    if not isinstance(posts, list) or not posts:
        raise ValueError(f"{posts_file}: no posts")
    figures = content_dir / "figures"
    if not figures.is_dir():
        raise FileNotFoundError(f"{figures}: figures directory missing")
    return len(posts), sum(1 for f in figures.iterdir() if f.is_file())


def sync(content_dir: Path, *, pull: bool) -> tuple[int, int]:
    builder = content_dir / "scripts" / "build_posts_index.py"
    if not builder.exists():
        raise FileNotFoundError(f"{builder}: not a jiphyeonjeon-content checkout")
    if pull and (content_dir / ".git").exists():
        _run(["git", "pull", "--ff-only", "--quiet"], cwd=content_dir)
    _run([sys.executable, str(builder), "--out", str(content_dir / "posts.json")], cwd=content_dir)
    return verify(content_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--content-dir",
        type=Path,
        default=Path(os.environ.get("BLOG_CONTENT_DIR", Path.home() / "jiphyeonjeon-content")),
    )
    parser.add_argument("--no-pull", action="store_true", help="rebuild from the current checkout only")
    parser.add_argument("--check", action="store_true", help="verify posts.json and figures without pulling or building")
    args = parser.parse_args()
    content_dir = args.content_dir.expanduser().resolve()
    try:
        posts, figures = verify(content_dir) if args.check else sync(content_dir, pull=not args.no_pull)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"content sync failed: {exc}", file=sys.stderr)
        return 1
    print(f"content ok: {posts} posts, {figures} figures at {content_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
