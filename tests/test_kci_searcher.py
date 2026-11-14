"""KCI OAI-PMH 수집 → 로컬 색인 → 검색 왕복 검증 (네트워크 없음)."""

import pytest

from src.collector.paper import kci_searcher


def _page(article_id: str, title: str, token: str = "") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListRecords>
<record><header><identifier>oai:kci.go.kr:ARTI/1</identifier></header><metadata>
<oai_kci xmlns="http://www.kci.go.kr/kciportal/OAI/">
  <journalInfo><journal-name>정보과학회논문지</journal-name><pub-year>2025</pub-year></journalInfo>
  <articleInfo article-id="{article_id}">
    <title-group><article-title lang="original">{title}</article-title>
      <article-title lang="english">Graph Neural Network Recommendation</article-title></title-group>
    <author-name><author><name>홍길동</name></author><author><name>김철수</name></author></author-name>
    <abstract-group><abstract lang="original">추천 시스템을 다룬다.</abstract></abstract-group>
    <doi>http://dx.doi.org/10.1234/kci.{article_id}</doi>
    <citation-count>3</citation-count><url>https://www.kci.go.kr/{article_id}</url>
  </articleInfo>
</oai_kci></metadata></record>
{f"<resumptionToken>{token}</resumptionToken>" if token else ""}
</ListRecords></OAI-PMH>""".encode()


def test_harvest_follows_tokens_and_search_finds_korean(tmp_path, monkeypatch):
    db = tmp_path / "kci.db"
    calls = []
    pages = iter([
        _page("ART000000001", "그래프 신경망 기반 추천", token="t1"),
        _page("ART000000002", "기후변화와 농업"),
    ])

    def fake_fetch(params):
        calls.append(params)
        return next(pages)

    monkeypatch.setattr(kci_searcher, "_fetch", fake_fetch)
    monkeypatch.setattr(kci_searcher.time, "sleep", lambda _: None)

    assert kci_searcher.harvest(db, "2026-11-01", "2026-11-02") == 2
    # 토큰 요청에도 metadataPrefix 가 있어야 KCI 가 oai_kci 로 응답한다.
    assert calls[1]["resumptionToken"] == "t1" and calls[1]["metadataPrefix"] == "oai_kci"

    # 조사("신경망을")를 떼고 찾는다.
    (paper,) = kci_searcher.search_kci("그래프 신경망을", 5, db)
    assert paper["title"] == "그래프 신경망 기반 추천"
    assert paper["authors"] == ["홍길동", "김철수"]
    assert paper["doi"] == "10.1234/kci.ART000000001"
    assert (paper["source"], paper["year"], paper["venue"], paper["citations"]) == ("KCI", "2025", "정보과학회논문지", 3)
    # 모든 단어가 일치하는 문서가 없으면 일부 일치로 넓힌다.
    assert len(kci_searcher.search_kci("기후변화 추천", 5, db)) == 2

    # 같은 논문을 다시 받으면 덮어쓴다(중복 없음).
    monkeypatch.setattr(kci_searcher, "_fetch", lambda params: _page("ART000000002", "기후변화와 어업"))
    kci_searcher.harvest(db, "2026-11-02", "2026-11-02")
    assert [p["title"] for p in kci_searcher.search_kci("기후변화", 5, db)] == ["기후변화와 어업"]


def test_default_run_resumes_from_saved_token_and_backfill_leaves_state_alone(tmp_path, monkeypatch):
    db = tmp_path / "kci.db"
    monkeypatch.setattr(kci_searcher.time, "sleep", lambda _: None)
    calls = []

    def crash_on_second_page(params):
        calls.append(params)
        if "resumptionToken" in params:
            raise RuntimeError("중단")
        return _page("ART000000001", "첫 논문", token="t1")

    monkeypatch.setattr(kci_searcher, "_fetch", crash_on_second_page)
    with pytest.raises(RuntimeError):
        kci_searcher.harvest(db, until="2013-03-25")

    # 구간 재수집(start 지정)은 저장된 토큰을 쓰지도, 지우지도 않는다.
    monkeypatch.setattr(kci_searcher, "_fetch", lambda params: _page("ART000000003", "재수집"))
    kci_searcher.harvest(db, "2020-01-01", "2020-01-02")

    calls.clear()
    monkeypatch.setattr(kci_searcher, "_fetch", lambda params: calls.append(params) or _page("ART000000002", "둘째 논문"))
    kci_searcher.harvest(db, until="2013-03-25")
    assert calls[0]["resumptionToken"] == "t1"


def test_record_the_server_cannot_serve_is_skipped_not_fatal(monkeypatch):
    """KCI 는 특정 레코드가 낀 페이지에 항상 500 을 낸다 → 한 건씩 받아 그 건만 건너뛴다."""
    import requests

    def fake_fetch(params):
        _, _, size, cursor = params["resumptionToken"].split(":")
        if size == "3" or cursor == "11":  # 큰 페이지와 문제 레코드(11번)는 500
            raise requests.HTTPError(response=type("R", (), {"status_code": 500})())
        return _page(f"ART{int(cursor):09d}", f"논문 {cursor}", token=f"a:b:1:{int(cursor) + 1}")

    monkeypatch.setattr(kci_searcher, "_fetch", fake_fetch)
    rows, token = kci_searcher._fetch_page({"resumptionToken": "a:b:3:10"})
    assert [row[0] for row in rows] == [10, 12]
    assert token == "a:b:3:13"  # 다음 페이지는 원래 크기로 복귀

    # 차단(4xx)이나 연결 장애는 레코드 문제가 아니므로 건너뛰지 않고 멈춘다.
    def blocked(params):
        raise requests.HTTPError(response=type("R", (), {"status_code": 400})())

    def offline(params):
        raise requests.Timeout("연결 없음")

    for failing in (blocked, offline):
        monkeypatch.setattr(kci_searcher, "_fetch", failing)
        with pytest.raises(requests.RequestException):
            kci_searcher._fetch_page({"resumptionToken": "a:b:3:10"})


def test_parallel_harvest_resumes_unfinished_chunks_only(tmp_path, monkeypatch):
    from datetime import date, timedelta

    db = tmp_path / "kci.db"
    today = date.today()
    monkeypatch.setattr(kci_searcher.time, "sleep", lambda _: None)
    monkeypatch.setattr(kci_searcher, "_EARLIEST", (today - timedelta(days=100)).isoformat())  # 작업 2개
    second_chunk_start = (today - timedelta(days=40)).isoformat()
    calls = []

    def fake_fetch(params, fail=True):
        calls.append(params["from"])
        if fail and params["from"] >= second_chunk_start:
            raise RuntimeError("중단")
        return _page(f"ART{len(calls):09d}", f"논문 {params['from']}")

    monkeypatch.setattr(kci_searcher, "_fetch", fake_fetch)
    with pytest.raises(RuntimeError):
        kci_searcher.harvest_parallel(2, db)
    finished = [day for day in calls if day < second_chunk_start]

    calls.clear()
    monkeypatch.setattr(kci_searcher, "_fetch", lambda params: fake_fetch(params, fail=False))
    kci_searcher.harvest_parallel(2, db)
    assert calls and not set(calls) & set(finished)  # 끝난 작업의 구간은 다시 받지 않는다

    calls.clear()
    kci_searcher.harvest_parallel(2, db)
    assert calls == [today.isoformat()]  # 이후 실행은 오늘분만


def test_broken_or_missing_index_returns_empty(tmp_path):
    assert kci_searcher.search_kci("그래프 신경망", 5, tmp_path / "missing.db") == []
    (tmp_path / "empty.db").touch()
    assert kci_searcher.search_kci("그래프 신경망", 5, tmp_path / "empty.db") == []


def test_filler_words_do_not_decide_the_match(tmp_path, monkeypatch):
    db = tmp_path / "kci.db"
    monkeypatch.setattr(kci_searcher.time, "sleep", lambda _: None)
    monkeypatch.setattr(kci_searcher, "_fetch", lambda params: _page("ART000000001", "노동 시장에 관한 연구"))
    kci_searcher.harvest(db, "2026-11-01", "2026-11-01")
    assert kci_searcher.search_kci("기후변화에 관한 연구 찾아줘", 5, db) == []


def test_oai_error_is_not_silently_skipped():
    with pytest.raises(ValueError):
        kci_searcher.parse_records(
            b'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><error code="badResumptionToken">x</error></OAI-PMH>'
        )
    assert kci_searcher.parse_records(
        b'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><error code="noRecordsMatch">x</error></OAI-PMH>'
    ) == ([], None)
