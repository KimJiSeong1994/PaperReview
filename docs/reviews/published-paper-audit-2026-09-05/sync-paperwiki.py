"""Back up and synchronize the fixed, reviewed PaperWiki article set."""

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WIKI = Path("/Users/jiseong/Library/Mobile Documents/com~apple~CloudDocs/PaperWiki/PaperWiki/blog").resolve()
parser = argparse.ArgumentParser()
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()
manifest = json.loads((ROOT / "paperwiki-sync-map.json").read_text())
assert len(manifest) == 62
prepared = []
for entry in manifest:
    source = Path(entry["source"]).resolve()
    target = Path(entry["target"]).resolve()
    assert source.is_relative_to(ROOT / "articles")
    assert target.is_relative_to(WIKI)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == entry["source_sha256"], entry["slug"]
    text = source.read_text().replace(
        "](/api/blog/figures/", "](https://jiphyeonjeon.kr/api/blog/figures/"
    ).replace(
        "](/paper-viewer?", "](https://jiphyeonjeon.kr/paper-viewer?"
    )
    current = target.read_bytes() if target.exists() else None
    previous_body_only = text.encode()
    backup_file = ROOT / "paperwiki-backups" / (entry["slug"] + ".md")
    original = backup_file.read_bytes() if backup_file.exists() else current
    if original is not None and original.startswith(b"---\n"):
        original_text = original.decode()
        _, front, _ = original_text.split("---\n", 2)
        metadata = json.loads((source.parent / "review.json").read_text())
        for key, value in [("title", metadata["paper_metadata"]["title"]), ("excerpt", metadata.get("excerpt", ""))]:
            if re.search(r"^" + key + r":\s*[>|]", front, re.MULTILINE):
                continue
            front = re.sub(r"^" + key + r":[^\n]*", lambda _: key + ": " + json.dumps(value, ensure_ascii=False), front, flags=re.MULTILINE)
        front = re.sub(r"^review_provenance:", "review_provenance_before_corpus_audit:", front, flags=re.MULTILINE)
        front = front.rstrip() + "\nreview_provenance: " + json.dumps("원문 대조 및 독립 교차 검증. 상세 근거: " + str(source.parent / "evidence.md"), ensure_ascii=False) + "\n"
        text = "---\n" + front + "---\n\n" + text
    new = text.encode()
    if current != new:
        current_hash = hashlib.sha256(current).hexdigest() if current is not None else None
        assert current_hash == entry["target_sha256"] or current == previous_body_only, f"Concurrent PaperWiki edit: {entry['slug']}"
    prepared.append((entry, source, target, current, new))

if args.apply:
    backup_dir = ROOT / "paperwiki-backups"
    backup_dir.mkdir(exist_ok=True)
    for entry, source, target, current, new in prepared:
        if current == new:
            continue
        backup = backup_dir / (entry["slug"] + ".md")
        if current is not None and not backup.exists():
            backup.write_bytes(current)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=target.parent, prefix=".paper-review-", suffix=".tmp")
        with os.fdopen(fd, "wb") as stream:
            stream.write(new)
            stream.flush()
            os.fsync(stream.fileno())
        if target.exists():
            shutil.copymode(target, name)
        os.replace(name, target)
        assert target.read_bytes() == new
    receipt = {"articles": 62, "status": "synchronized", "backups": str(backup_dir)}
    (ROOT / "paperwiki-sync-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
else:
    receipt = {"articles": 62, "status": "dry-run passed", "new_notes": sum(current is None for _, _, _, current, _ in prepared)}
print(json.dumps(receipt))
