"""Atomically publish only the 62 already-reviewed and merged post records."""

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

parser = argparse.ArgumentParser()
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()
records = json.loads(Path("/tmp/paper-audit-published-records.json").read_text())
baseline = json.loads(Path("/tmp/paper-audit-production-before.json").read_text())["posts"]
old_by_slug = {p["slug"]: p for p in baseline}
slugs = {p["slug"] for p in records}
assert len(records) == len(slugs) == 62
assert "ic2-interventional-dynamical-causality-under-latent-confounders" not in slugs
assert "intent-propagation-contrastive-collaborative-filtering" not in slugs
mutable = ["title", "excerpt", "content", "reading_time_min", "updated_at"]
preserved = ["id", "slug", "author", "tags", "category", "thumbnail_url", "created_at", "published"]
path = Path("/home/ubuntu/PaperReviewAgent/data/blog/posts.json")

with FileLock(str(path) + ".lock", timeout=30):
    document = json.loads(path.read_text())
    existing = {p["slug"]: p for p in document["posts"]}
    untouched = [p.copy() for p in document["posts"] if p["slug"] not in slugs]
    for record in records:
        post = existing[record["slug"]]
        old = old_by_slug[record["slug"]]
        current_fields = {key: post.get(key) for key in mutable}
        assert current_fields in (
            {key: old.get(key) for key in mutable},
            {key: record.get(key) for key in mutable},
        ), f"Concurrent post edit: {record['slug']}"
        assert all(post.get(key) == record.get(key) for key in preserved), record["slug"]
        assert record["published"] and record["category"] == "paper-review"
        assert "## References" in record["content"]
    for record in records:
        existing[record["slug"]].update({key: record[key] for key in mutable})
    assert untouched == [p for p in document["posts"] if p["slug"] not in slugs]
    receipt = {"mode": "apply" if args.apply else "dry-run", "articles": 62,
               "total_posts": len(document["posts"]), "other_posts_unchanged": True,
               "hashes": {p["slug"]: hashlib.sha256(p["content"].encode()).hexdigest() for p in records}}
    if args.apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = path.parent / "backups" / f"posts-before-paper-audit-{stamp}.json"
        backup.parent.mkdir(exist_ok=True)
        shutil.copy2(path, backup)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="posts-paper-audit-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copymode(path, temporary)
        assert json.loads(Path(temporary).read_text()) == document
        os.replace(temporary, path)
        assert json.loads(path.read_text()) == document
        receipt["backup"] = str(backup)
        Path("/tmp/paper-audit-publication-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({key: value for key, value in receipt.items() if key != "hashes"}))
