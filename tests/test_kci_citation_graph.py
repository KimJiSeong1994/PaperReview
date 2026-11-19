"""Crossref 참고문헌 → KCI 논문 연결 (네트워크 없음)."""

import sqlite3

from src.collector.paper import kci_citation_graph as graph
from src.collector.paper import kci_searcher
from tests.test_kci_searcher import _page


def _index(tmp_path, monkeypatch):
    db = tmp_path / "kci.db"
    monkeypatch.setattr(kci_searcher.time, "sleep", lambda _: None)
    pages = iter([
        _page("ART000000001", "그래프 신경망을 활용한 온라인 의견 사기 탐지", token="a"),  # pub-year 2025, 영문 제목 고정
        _page("ART000000002", "인용하는 논문", token="b"),
        _page("ART000000003", "서론"),
    ])
    monkeypatch.setattr(kci_searcher, "_fetch", lambda params: next(pages))
    kci_searcher.harvest(db, "2026-11-01", "2026-11-01")
    with sqlite3.connect(str(db) + ".doi.db") as conn:
        conn.execute("CREATE TABLE doi_lookup (rowid INTEGER PRIMARY KEY, doi TEXT NOT NULL)")
        conn.executemany("INSERT INTO doi_lookup VALUES (?, ?)", [(1, "10.1234/kci.art000000001"), (2, "10.1234/kci.art000000002")])
    graph.build_title_keys(db)
    return db


def test_reference_is_linked_by_doi_or_exact_title_and_year(tmp_path, monkeypatch):
    db = _index(tmp_path, monkeypatch)
    with sqlite3.connect(graph.graph_path(db)) as conn, sqlite3.connect(str(db) + ".doi.db") as doi_conn:
        def match(ref):
            return graph.match_reference(conn, doi_conn, ref)

        assert match({"DOI": "10.1234/KCI.ART000000001"}) == (1, "doi")
        # 국문 APA: 띄어쓰기가 달라도 제목 전체 + 연도가 맞으면 연결
        assert match({"unstructured": "현우창. (2025). 그래프 신경망을활용한 온라인 의견 사기 탐지. 정보과학회논문지, 50(11)."}) == (1, "title")
        # 영문 IEEE 따옴표 제목도 후보로 뽑지만, 색인의 세 논문이 같은 영문 제목이라 흔한 제목으로 보고 버린다
        assert "graphneuralnetworkrecommendation" in graph._candidate_keys('J. Kim, "Graph Neural Network Recommendation," KIISE, 2025.')
        assert match({"unstructured": 'J. Kim, "Graph Neural Network Recommendation," KIISE, 2025.'}) == (None, "")
        assert match({"unstructured": "현우창. (2019). 그래프 신경망을활용한 온라인 의견 사기 탐지. 정보과학회논문지."}) == (None, "")  # 연도 다름
        assert match({"unstructured": "홍길동. (2025). 서론. 학회지."}) == (None, "")  # 짧은 제목은 쓰지 않는다


def test_harvest_records_edges_and_lookups_use_them(tmp_path, monkeypatch):
    db = _index(tmp_path, monkeypatch)
    monkeypatch.setattr(graph, "_MIN_INTERVAL", 0)
    calls = []

    def fake_get(session, url, params=None):
        calls.append(params)
        # Crossref 는 없는 DOI(…001)를 결과에서 뺀다. 응답 DOI 는 대문자일 수 있다.
        return {"items": [{"DOI": "10.1234/KCI.ART000000002", "reference": [
            {"DOI": "10.1234/kci.art000000001"}, {"DOI": "10.9999/elsewhere"},
            {"unstructured": "Kim. (2025). 그래프 신경망을 활용한 온라인 의견 사기 탐지."}]}]}

    monkeypatch.setattr(graph, "_get", fake_get)
    assert graph.harvest(db_path=db) == 2
    assert len(calls) == 1 and calls[0]["filter"] == "doi:10.1234/kci.art000000001,doi:10.1234/kci.art000000002"
    assert graph.harvest(db_path=db) == 0  # 이어받기: 끝난 논문은 다시 받지 않는다

    assert graph.edges_for(2, db) == ([1], [])
    assert graph.edges_for(1, db) == ([], [2])
    stats = graph.report(db)
    assert (stats["papers"], stats["refs"], stats["linked_refs"], stats["linked_by_doi"]) == (2, 3, 1, 1)

    monkeypatch.setenv("KCI_DB_PATH", str(db))
    monkeypatch.delenv("KCI_API_KEY", raising=False)
    (cited,) = kci_searcher.kci_references({"kci_id": "ART000000002"}, db_path=db)
    (citing,) = kci_searcher.kci_citing({"kci_id": "ART000000001", "title": "그래프 신경망을 활용한 온라인 의견 사기 탐지"}, db_path=db)
    assert (cited["kci_id"], citing["kci_id"]) == ("ART000000001", "ART000000002")


def test_malformed_doi_does_not_break_the_batch(monkeypatch):
    """KCI 에 "/" 없는 DOI 가 있다(실제: 10.1007-012-0015-5). 묶음에 넣으면 Crossref 가 묶음 전체를 400 으로 거부한다."""
    calls = []

    def fake_get(session, url, params=None):
        calls.append(params["filter"] if params else url)
        if params and "-012-" in params["filter"]:
            return None  # 400
        return {"items": [{"DOI": "10.1/a", "reference": [{"DOI": "10.1/x"}]}]} if params else {"reference": []}

    monkeypatch.setattr(graph, "_get", fake_get)
    found = graph._fetch_batch(None, ["10.1/a", "10.1007-012-0015-5"])
    assert found == {"10.1/a": [{"DOI": "10.1/x"}], "10.1007-012-0015-5": []}
    assert calls[0] == "doi:10.1/a"  # 잘못된 DOI 는 묶음에서 빠진다
