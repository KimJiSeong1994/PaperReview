"""Audit URL-valued KCI titles; --apply repairs FTS entries with a before-image journal.

The default is read-only. Repair preserves identifiers, abstracts and all other
metadata. The journal must be a new file and is flushed before each DB update.
Run with the same collection lock used by the daily harvest job.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.collector.paper.kci_searcher import _clean_title


def repair(db: Path, *, backup: Path | None = None):
    mode = 'rw' if backup is not None else 'ro'
    journal = backup.open('x', encoding='utf-8') if backup is not None else None
    report = {'affected': 0, 'changed': 0, 'concurrent_changes': 0, 'samples': []}
    try:
        with closing(sqlite3.connect(f'file:{db.resolve()}?mode={mode}', uri=True, timeout=5)) as conn:
            last = 0
            while rows := conn.execute(
                'SELECT rowid,title,title_en FROM kci WHERE kci MATCH ? AND rowid > ? ORDER BY rowid LIMIT 500',
                ('{title title_en} : (http OR https)', last),
            ).fetchall():
                for rowid, title, title_en in rows:
                    last = rowid
                    cleaned = [_clean_title(title), _clean_title(title_en)]
                    # Only remove whole URL values, never edit legitimate titles.
                    after = [new if old and not new else old for old, new in zip((title, title_en), cleaned)]
                    if after == [title, title_en]:
                        continue
                    report['affected'] += 1
                    record = {'rowid': rowid, 'before': [title, title_en], 'after': after}
                    if len(report['samples']) < 5:
                        report['samples'].append(record)
                    if journal is not None:
                        journal.write(json.dumps(record, ensure_ascii=False) + '\n')
                        journal.flush()
                        os.fsync(journal.fileno())
                        with conn:
                            changed = conn.execute(
                                'UPDATE kci SET title=?,title_en=? WHERE rowid=? AND title IS ? AND title_en IS ?',
                                (*after, rowid, title, title_en),
                            ).rowcount
                        report['changed' if changed else 'concurrent_changes'] += 1
        return report
    finally:
        if journal is not None:
            journal.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=Path('data/kci.db'))
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    if args.apply != (args.backup is not None):
        parser.error('--apply and a new --backup path must be supplied together')
    print(json.dumps(repair(args.db, backup=args.backup), ensure_ascii=False, indent=2))
