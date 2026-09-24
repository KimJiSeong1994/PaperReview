"""Publish only the ten reviewed existing records, with a backup and conflict check."""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('payload', type=Path)
parser.add_argument('--posts-file', type=Path, required=True)
parser.add_argument('--receipt', type=Path, required=True)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
records = json.loads(args.payload.read_text())['records']
slugs = {r['after']['slug'] for r in records}
assert len(slugs) == len(records) == 10
mutable = {'content', 'excerpt', 'updated_at', 'reading_time_min'}
path = args.posts_file.resolve()
with FileLock(str(path) + '.lock', timeout=30):
    raw = path.read_bytes()
    document = json.loads(raw)
    current = {p['slug']: p for p in document['posts']}
    assert len(current) == len(document['posts'])
    unchanged = [p.copy() for p in document['posts'] if p['slug'] not in slugs]
    for entry in records:
        before, after = entry['before'], entry['after']
        slug = after['slug']
        post = current[slug]
        assert post == before or post == after, f'Concurrent edit: {slug}'
        for key in set(before) | set(after):
            if key not in mutable:
                assert before.get(key) == after.get(key), (slug, key)
        assert after['published'] and after['category'] == 'paper-review'
        assert '## References' in after['content'] and len(after['excerpt']) <= 500
    for entry in records:
        current[entry['after']['slug']].update({k: entry['after'][k] for k in mutable})
    assert unchanged == [p for p in document['posts'] if p['slug'] not in slugs]
    receipt = {'mode': 'apply' if args.apply else 'dry-run', 'articles': 10,
               'total_posts': len(document['posts']), 'other_posts_unchanged': len(unchanged),
               'hashes': {p['slug']: hashlib.sha256(p['content'].encode()).hexdigest()
                          for p in document['posts'] if p['slug'] in slugs}}
    if args.apply:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = path.parent / 'backups' / f'posts-before-recent-review-{stamp}.json'
        backup.parent.mkdir(exist_ok=True)
        shutil.copy2(path, backup)
        fd, tmp = tempfile.mkstemp(prefix='.recent-review-', suffix='.tmp', dir=path.parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(document, out, ensure_ascii=False, indent=2)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        shutil.copymode(path, tmp)
        assert path.read_bytes() == raw, 'Store modified outside lock'
        os.replace(tmp, path)
        assert json.loads(path.read_text()) == document
        receipt.update(backup=str(backup), applied_at=datetime.now(timezone.utc).isoformat())
    args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: v for k, v in receipt.items() if k != 'hashes'}))
