"""Apply prepared PaperWiki merges without losing metadata or unique citations."""
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
entries = json.loads((root / 'paperwiki-sync-map.json').read_text())
assert len(entries) == 10
prepared = []
for e in entries:
    target = Path(e['target']).resolve()
    source = Path(e['prepared']).resolve()
    assert target.is_relative_to(wiki) and source.is_relative_to(root / 'paperwiki-prepared')
    old, new = target.read_bytes(), source.read_bytes()
    assert hashlib.sha256(new).hexdigest() == e['prepared_sha256']
    assert hashlib.sha256(old).hexdigest() == e['original_sha256'] or old == new, e['slug']
    assert b'<<<<<<<' not in new and b'>>>>>>>' not in new
    prepared.append((e, target, old, new))
receipt = {'status': 'synchronized' if args.apply else 'dry-run', 'articles': 10, 'records': []}
if args.apply:
    backup = root / 'paperwiki-backups'
    backup.mkdir(exist_ok=True)
    for e, target, old, new in prepared:
        if old != new:
            assert target.read_bytes() == old, e['slug']
            saved = backup / (e['slug'] + '.md')
            if not saved.exists():
                saved.write_bytes(old)
            fd, tmp = tempfile.mkstemp(prefix='.review-sync-', suffix='.tmp', dir=target.parent)
            with os.fdopen(fd, 'wb') as out:
                out.write(new)
                out.flush()
                os.fsync(out.fileno())
            shutil.copymode(target, tmp)
            os.replace(tmp, target)
        assert target.read_bytes() == new
        receipt['records'].append({'slug': e['slug'], 'path': str(target), 'sha256': e['prepared_sha256']})
    (root / 'paperwiki-sync-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: v for k, v in receipt.items() if k != 'records'}))
