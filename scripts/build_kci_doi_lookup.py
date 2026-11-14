"""Build a compact DOI→KCI rowid sidecar without modifying the harvested DB.

Uses a consistent read snapshot, builds a private temporary file, then atomically
replaces the sidecar. Readers verify the DOI against the live source record.
Missing entries fall back to a bounded scan, so a stale sidecar cannot certify
absence. Rerun after harvesting to refresh newly added/changed DOI mappings.
"""

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.utils.paper_utils import normalize_doi


def build(source: Path, output: Path):
    if source.resolve() == output.resolve():
        raise ValueError("Lookup destination must differ from the source database")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=output.name + ".", dir=output.parent)
    os.close(fd)
    scanned = indexed = 0
    started = time.monotonic()
    try:
        with closing(sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)) as src, closing(sqlite3.connect(temporary)) as dst:
            src.execute("BEGIN")
            dst.execute("CREATE TABLE doi_lookup (rowid INTEGER PRIMARY KEY, doi TEXT NOT NULL)")
            dst.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
            cursor = src.execute("SELECT id, c7 FROM kci_content ORDER BY id")
            while batch := cursor.fetchmany(10000):
                records = [(rowid, normalize_doi(doi)) for rowid, doi in batch if doi]
                dst.executemany("INSERT INTO doi_lookup VALUES (?, ?)", records)
                scanned += len(batch)
                indexed += len(records)
                if scanned % 200000 == 0:
                    print(json.dumps({"scanned": scanned, "indexed": indexed}), flush=True)
            dst.execute("CREATE INDEX doi_lookup_doi ON doi_lookup(doi)")
            dst.executemany("INSERT INTO metadata VALUES (?,?)", [
                ("source", str(source.resolve())), ("scanned", str(scanned)),
                ("indexed", str(indexed)), ("built_at", str(time.time())),
            ])
            dst.commit()
        # Preserve the source corpus's read-access policy for service/container
        # users; mkstemp's owner-only default would make a mounted index unreadable.
        os.chmod(temporary, source.stat().st_mode & 0o666)
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"scanned": scanned, "indexed": indexed, "seconds": round(time.monotonic() - started, 3), "path": str(output)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/kci.db"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.db, args.output or Path(str(args.db) + ".doi.db"))), flush=True)
