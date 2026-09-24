"""Apply the reviewed IPCCF content only, preserving all other production posts."""

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("payload", type=Path)
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()
payload = json.loads(args.payload.read_text())
slug = "intent-propagation-contrastive-collaborative-filtering"
assert payload["slug"] == slug
assert set(payload["updates"]) == {"title", "excerpt", "content"}
assert 0 < len(payload["updates"]["title"]) <= 300
assert len(payload["updates"]["excerpt"]) <= 500
assert "## References" in payload["updates"]["content"]
assert "오프셋" in payload["updates"]["content"]
posts_file = Path("/home/ubuntu/PaperReviewAgent/data/blog/posts.json")

with FileLock(str(posts_file) + ".lock", timeout=30):
    document = json.loads(posts_file.read_text())
    matches = [p for p in document["posts"] if p.get("slug") == slug]
    assert len(matches) == 1, "Expected exactly one existing IPCCF post"
    post = matches[0]
    assert post["id"] == payload["id"]
    assert post["published"] is True
    assert post["category"] == "paper-review"
    assert digest(post["content"]) == payload["expected_content_sha256"], "Post changed since preparation"
    assert post.get("updated_at") == payload["expected_updated_at"], "Post metadata changed since preparation"
    before = post.copy()
    other_before = [p.copy() for p in document["posts"] if p is not post]
    post.update(payload["updates"])
    cjk = re.compile(r"[가-힣぀-ヿ一-鿿]")
    word_count = len(cjk.sub(" ", post["content"]).split())
    cjk_count = len(cjk.findall(post["content"]))
    post["reading_time_min"] = max(1, math.ceil((word_count + cjk_count / 2.5) / 200))
    post["updated_at"] = datetime.now(timezone.utc).isoformat()
    preserved = {"id", "slug", "author", "tags", "category", "thumbnail_url", "created_at", "published"}
    assert all(post.get(k) == before.get(k) for k in preserved)
    assert other_before == [p for p in document["posts"] if p is not post]
    result = {
        "mode": "apply" if args.apply else "dry-run",
        "slug": slug,
        "post_count": len(document["posts"]),
        "other_posts_unchanged": True,
        "changed_fields": sorted(k for k in post if post[k] != before.get(k)),
        "content_sha256": digest(post["content"]),
        "reading_time_min": post["reading_time_min"],
        "updated_at": post["updated_at"],
    }
    if args.apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_dir = posts_file.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / f"posts-before-ipccf-revision-{stamp}.json"
        shutil.copy2(posts_file, backup)
        fd, temporary = tempfile.mkstemp(prefix="posts-ipccf-", suffix=".json.tmp", dir=posts_file.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            shutil.copymode(posts_file, temporary)
            assert json.loads(Path(temporary).read_text()) == document
            os.replace(temporary, posts_file)
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()
        saved = json.loads(posts_file.read_text())
        assert saved == document
        result["backup"] = str(backup)
    print(json.dumps(result, ensure_ascii=False))
