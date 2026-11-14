"""DOI sidecar construction, live validation and stale-index recovery."""

import sqlite3

import pytest

from scripts.build_kci_doi_lookup import build
from src.collector.paper import kci_searcher as kci


@pytest.fixture
def corpus(tmp_path):
    path = tmp_path / "kci.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(kci._SCHEMA)
        conn.execute("INSERT INTO kci(rowid,title,authors,doi,year) VALUES (1,'그래프 논문','홍길동','https://doi.org/10.1234/ABC','2025')")
    return path


def lookup(path, value):
    return kci.search_kci(value, 5, path, route={"kind": "doi", "value": value})


def test_build_preserves_source_and_normalizes_doi(corpus):
    before = corpus.read_bytes()
    summary = build(corpus, corpus.with_name(corpus.name + ".doi.db"))
    assert summary["scanned"] == summary["indexed"] == 1
    assert corpus.read_bytes() == before
    assert corpus.with_name(corpus.name + ".doi.db").stat().st_mode & 0o777 == corpus.stat().st_mode & 0o666
    assert kci._lookup_doi(corpus, "10.1234/abc") == [1]
    assert lookup(corpus, "10.1234/abc")[0]["kci_id"] == "ART000000001"


def test_stale_mapping_is_verified_and_new_location_recovered(corpus):
    build(corpus, corpus.with_name(corpus.name + ".doi.db"))
    with sqlite3.connect(corpus) as conn:
        conn.execute("UPDATE kci SET doi='10.1234/changed' WHERE rowid=1")
        conn.execute("INSERT INTO kci(rowid,title,authors,doi,year) VALUES (2,'다른 논문','김철수','10.1234/abc','2026')")
    assert lookup(corpus, "10.1234/abc")[0]["kci_id"] == "ART000000002"
    assert lookup(corpus, "10.1234/changed")[0]["kci_id"] == "ART000000001"


def test_invalid_sidecar_falls_back_and_source_overwrite_is_rejected(corpus):
    with pytest.raises(ValueError):
        build(corpus, corpus)
    corpus.with_name(corpus.name + ".doi.db").write_bytes(b"broken")
    assert lookup(corpus, "10.1234/abc")[0]["kci_id"] == "ART000000001"
