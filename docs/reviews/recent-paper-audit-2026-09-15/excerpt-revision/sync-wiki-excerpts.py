"""Back up and apply only the excerpt and update timestamp to ten Wiki articles."""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parent
wiki = Path('/Users/jiseong/Library/Mobile Documents/com~apple~CloudDocs/PaperWiki/PaperWiki/blog').resolve()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
entries = json.loads((root / 'wiki-manifest.json').read_text())
assert len(entries) == len({e['slug'] for e in entries}) == 10
prepared = []
for entry in entries:
    target = Path(entry['target']).resolve()
    source = root / 'wiki-prepared' / (entry['slug'] + '.md')
    assert target.is_relative_to(wiki)
    old, new = target.read_bytes(), source.read_bytes()
    assert hashlib.sha256(old).hexdigest() == entry['before_sha256'] or old == new, entry['slug']
    assert hashlib.sha256(new).hexdigest() == entry['after_sha256']
    assert old.decode().split('---\n', 2)[2] == new.decode().split('---\n', 2)[2], entry['slug']
    prepared.append((entry, target, old, new))
if args.apply:
    backup = root / 'wiki-backups'
    backup.mkdir(exist_ok=True)
    for entry, target, old, new in prepared:
        assert target.read_bytes() == old, entry['slug']
        if old == new:
            continue
        saved = backup / (entry['slug'] + '.md')
        if not saved.exists():
            saved.write_bytes(old)
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix='.excerpt-', suffix='.tmp')
        with os.fdopen(fd, 'wb') as out:
            out.write(new)
            out.flush()
            os.fsync(out.fileno())
        shutil.copymode(target, temporary)
        os.replace(temporary, target)
        assert target.read_bytes() == new
    (root / 'wiki-receipt.json').write_text(json.dumps({'status': 'synchronized', 'articles': 10,
        'body_unchanged': True, 'entries': entries}, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'mode': 'apply' if args.apply else 'dry-run', 'articles': 10, 'body_unchanged': True}))
