"""Publish the already merged, paper-only IPCCF record without changing other posts."""

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

SLUG = "intent-propagation-contrastive-collaborative-filtering"
record = json.loads(Path("/tmp/ipccf-paper-explainer-post.json").read_text())
expected = json.loads(Path("/tmp/ipccf-before-explainer.json").read_text())
assert record["slug"] == expected["slug"] == SLUG
assert record["content"].count("![") == 3
assert "검토 기준" not in record["content"]
assert "공개 코드" not in record["content"]
posts_file = Path("/home/ubuntu/PaperReviewAgent/data/blog/posts.json")

with FileLock(str(posts_file) + ".lock", timeout=30):
    document = json.loads(posts_file.read_text())
    matches = [p for p in document["posts"] if p.get("slug") == SLUG]
    assert len(matches) == 1
    post = matches[0]
    assert post["content"] in (expected["content"], record["content"]), "Unexpected concurrent article edit"
    for field in ["id", "slug", "created_at", "author", "tags", "category", "thumbnail_url", "published"]:
        assert post[field] == record[field]
    other_posts = [p.copy() for p in document["posts"] if p is not post]
    post.update({field: record[field] for field in ["title", "excerpt", "content", "reading_time_min", "updated_at"]})
    assert other_posts == [p for p in document["posts"] if p is not post]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = posts_file.parent / "backups" / f"posts-before-ipccf-paper-explainer-{stamp}.json"
    backup.parent.mkdir(exist_ok=True)
    shutil.copy2(posts_file, backup)
    fd, name = tempfile.mkstemp(dir=posts_file.parent, prefix="posts-ipccf-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    shutil.copymode(posts_file, name)
    os.replace(name, posts_file)
    assert json.loads(posts_file.read_text()) == document
    print(json.dumps({"slug": SLUG, "content_sha256": hashlib.sha256(post["content"].encode()).hexdigest(),
                      "other_posts_unchanged": True, "figures": 3, "backup": str(backup)}, ensure_ascii=False))
