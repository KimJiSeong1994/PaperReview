"""KCI 논문 사이 인용 관계: Crossref 참고문헌 목록 → 로컬 KCI 색인 연결.

DOI 가 있는 KCI 논문마다 Crossref 에서 참고문헌 목록을 받아, 각 참고문헌을
(1) DOI 가 있으면 KCI DOI 색인으로, (2) 없으면 원문 문장 속 제목을 KCI 제목 색인과
정확히 맞춰(발행연도도 일치) KCI 논문에 연결한다. 결과는 `KCI_DB_PATH` 옆의
`.cites.db` 에 쌓인다(배포된 읽기 전용 색인은 건드리지 않는다).

    python -m src.collector.paper.kci_citation_graph --titles   # 제목 색인 만들기(1회)
    python -m src.collector.paper.kci_citation_graph --limit 1000   # 이어서 1000편 수집
    python -m src.collector.paper.kci_citation_graph --report   # 매칭률
"""

import argparse
import logging
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import requests

from src.collector.paper.kci_searcher import _default_db_path, _norm
from src.utils.paper_utils import normalize_doi

logger = logging.getLogger(__name__)

CROSSREF_URL = "https://api.crossref.org/works/"
_MIN_KEY = 8  # 정규화한 제목이 이보다 짧으면("서론", "권두언") 오탐이 많아 쓰지 않는다
_GENERIC = 3  # 같은 제목이 이만큼 이상이면 흔한 제목으로 보고 쓰지 않는다
# Crossref 공개 풀: 초당 5건, 동시 1건 (응답 헤더 x-rate-limit-*, x-concurrency-limit)
_MIN_INTERVAL = 0.2
_BATCH = 100  # 요청 하나에 묶는 DOI 수

_SCHEMA = """
CREATE TABLE IF NOT EXISTS title_key (key TEXT NOT NULL, year TEXT, rowid_ INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS title_key_key ON title_key(key);
CREATE TABLE IF NOT EXISTS kci_cites (citing INTEGER, cited INTEGER, how TEXT,
                                      PRIMARY KEY (citing, cited)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS kci_cites_cited ON kci_cites(cited);
CREATE TABLE IF NOT EXISTS refs_done (rowid INTEGER PRIMARY KEY, status INTEGER, refs INTEGER,
                                      ref_dois INTEGER, ref_texts INTEGER, by_doi INTEGER, by_title INTEGER);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
"""


def graph_path(db_path: Optional[Path] = None) -> Path:
    return Path(str(db_path or _default_db_path()) + ".cites.db")


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(graph_path(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def build_title_keys(db_path: Optional[Path] = None) -> int:
    """KCI 색인의 국문·영문 제목을 정규화해 (제목, 연도) → 논문으로 찾는 표를 만든다."""
    db_path = db_path or _default_db_path()
    count = 0
    with closing(_connect(db_path)) as dst, closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as src:
        with dst:
            dst.execute("DELETE FROM title_key")
            dst.execute("DROP INDEX IF EXISTS title_key_key")
            for rowid, title, title_en, year in src.execute("SELECT rowid, title, title_en, year FROM kci"):
                keys = {k for k in (_norm(title), _norm(title_en)) if len(k) >= _MIN_KEY}
                dst.executemany("INSERT INTO title_key VALUES (?, ?, ?)", [(k, year, rowid) for k in keys])
                count += 1
            dst.execute("CREATE INDEX title_key_key ON title_key(key)")
            dst.execute("INSERT OR REPLACE INTO state VALUES ('titles_built', ?)", (str(count),))
    return count


def _candidate_keys(text: str) -> Set[str]:
    """참고문헌 원문에서 제목일 수 있는 구간을 모두 뽑는다(구분자 사이 1~4조각)."""
    pieces = [p for p in re.split(r"[.,;:]\s|[\"“”‘’「」『』《》〈〉<>]|\(\d{4}[a-z]?\)", text) if p.strip()]
    keys = set()
    for i in range(len(pieces)):
        for j in range(i + 1, min(i + 5, len(pieces) + 1)):
            key = _norm(" ".join(pieces[i:j]))
            if _MIN_KEY <= len(key) <= 400:
                keys.add(key)
    return keys


def match_reference(conn: sqlite3.Connection, doi_conn: Optional[sqlite3.Connection],
                    ref: Dict) -> Tuple[Optional[int], str]:
    """Crossref 참고문헌 하나 → (KCI 논문 rowid 또는 None, 'doi'|'title'|'')."""
    doi = normalize_doi(ref.get("DOI") or "")
    if doi and doi_conn is not None:
        row = doi_conn.execute("SELECT rowid FROM doi_lookup WHERE doi = ? LIMIT 2", (doi,)).fetchall()
        if len(row) == 1:
            return row[0][0], "doi"
    text = " ".join(str(ref.get(f) or "") for f in ("unstructured", "article-title", "volume-title", "year"))
    keys = _candidate_keys(text) | {k for k in [_norm(ref.get("article-title") or "")] if len(k) >= _MIN_KEY}
    if not keys:
        return None, ""
    marks = ",".join("?" * len(keys))
    hits: Dict[str, List[Tuple[str, int]]] = {}
    for key, year, rowid in conn.execute(f"SELECT key, year, rowid_ FROM title_key WHERE key IN ({marks})", list(keys)):
        hits.setdefault(key, []).append((year, rowid))
    found = {
        rowid
        for key, rows in hits.items() if len(rows) < _GENERIC
        for year, rowid in rows if year and year in text
    }
    return (found.pop(), "title") if len(found) == 1 else (None, "")


def _get(session: requests.Session, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """Crossref GET. 400·404 면 None, 일시 오류(429·5xx·연결)는 기다렸다 다시."""
    for attempt in range(1, 8):
        try:
            response = session.get(url, params=params, timeout=120)
        except requests.RequestException as error:
            logger.warning("Crossref 요청 실패(%s), 재시도 %d", error, attempt)
            time.sleep(5 * attempt)
            continue
        if response.status_code in (400, 404):  # 400: 잘못된 DOI(예: "/" 없음)
            return None
        if response.status_code in (429, 500, 502, 503, 504):
            time.sleep(5 * attempt)
            continue
        response.raise_for_status()
        return response.json()["message"]
    raise RuntimeError(f"Crossref 응답 없음: {url}")


def _fetch_batch(session: requests.Session, dois: List[str]) -> Dict[str, List[Dict]]:
    """DOI 여러 개의 참고문헌을 요청 하나로 받는다(같은 필터를 여러 번 주면 Crossref 가 OR 로 묶는다).

    Crossref 에 없는 DOI 는 결과에서 빠진다. 필터를 깨는 DOI(쉼표, "/" 없음)는 한 건씩 받고,
    묶음 요청이 거부되면(400) 묶음 전체를 한 건씩 받는다.
    """
    found: Dict[str, List[Dict]] = {}
    plain = [d for d in dois if "," not in d and re.fullmatch(r"10\.\d+/\S+", d)]
    message = _get(session, CROSSREF_URL.rstrip("/"), {
        "filter": ",".join("doi:" + d for d in plain), "rows": len(plain), "select": "DOI,reference"}) if plain else None
    for item in (message or {}).get("items", []):
        found[normalize_doi(item.get("DOI") or "")] = item.get("reference") or []
    single = [d for d in dois if d not in plain] + (plain if plain and message is None else [])
    for doi in single:
        if (one := _get(session, CROSSREF_URL + doi)) is not None:
            found[doi] = one.get("reference") or []
    return found


def harvest(limit: Optional[int] = None, db_path: Optional[Path] = None) -> int:
    """DOI 가 있는 KCI 논문의 참고문헌을 rowid 순서대로 100편씩 받는다(중단 후 이어받기)."""
    db_path = db_path or _default_db_path()
    doi_db = Path(str(db_path) + ".doi.db")
    session = requests.Session()
    session.headers["User-Agent"] = "kci-citation-graph/0.1"
    done = 0
    with closing(_connect(db_path)) as conn, closing(sqlite3.connect(f"file:{doi_db}?mode=ro", uri=True)) as doi_conn:
        if not conn.execute("SELECT 1 FROM state WHERE key='titles_built'").fetchone():
            raise SystemExit("제목 색인이 없음: --titles 를 먼저 실행")
        last = conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM refs_done").fetchone()[0]
        todo = doi_conn.execute("SELECT rowid, doi FROM doi_lookup WHERE rowid > ? ORDER BY rowid LIMIT ?",
                                (last, limit or -1)).fetchall()
        for i in range(0, len(todo), _BATCH):
            started = time.monotonic()
            batch = todo[i:i + _BATCH]
            found = _fetch_batch(session, [doi for _, doi in batch])
            cites, done_rows = [], []
            for rowid, doi in batch:
                refs = found.get(doi)
                edges, by = {}, {"doi": 0, "title": 0}
                for ref in refs or []:
                    cited, how = match_reference(conn, doi_conn, ref)
                    if cited and cited != rowid and cited not in edges:
                        edges[cited] = how
                        by[how] += 1
                cites += [(rowid, cited, how) for cited, how in edges.items()]
                done_rows.append((rowid, 404 if refs is None else 200, len(refs or []),
                                  sum(1 for r in refs or [] if r.get("DOI")),
                                  sum(1 for r in refs or [] if not r.get("DOI")), by["doi"], by["title"]))
            with conn:
                conn.executemany("INSERT OR IGNORE INTO kci_cites VALUES (?, ?, ?)", cites)
                conn.executemany("INSERT OR REPLACE INTO refs_done VALUES (?, ?, ?, ?, ?, ?, ?)", done_rows)
            done += len(batch)
            if done % 10_000 < _BATCH:
                logger.info("Crossref 참고문헌: %d/%d편", done, len(todo))
            time.sleep(max(0.0, _MIN_INTERVAL - (time.monotonic() - started)))
    return done


def report(db_path: Optional[Path] = None) -> Dict[str, float]:
    """수집한 범위의 매칭률."""
    with closing(_connect(db_path)) as conn:
        papers, found, with_refs, refs, ref_dois, ref_texts, by_doi, by_title, linked_papers = conn.execute(
            "SELECT COUNT(*), SUM(status = 200), SUM(refs > 0), SUM(refs), SUM(ref_dois), SUM(ref_texts),"
            " SUM(by_doi), SUM(by_title), SUM(by_doi + by_title > 0) FROM refs_done").fetchone()
    ratio = lambda a, b: round(100.0 * (a or 0) / b, 1) if b else 0.0  # noqa: E731
    return {
        "papers": papers, "crossref_found_pct": ratio(found, papers), "with_refs_pct": ratio(with_refs, papers),
        "refs": refs or 0, "ref_with_doi_pct": ratio(ref_dois, refs),
        "linked_refs": (by_doi or 0) + (by_title or 0), "linked_refs_pct": ratio((by_doi or 0) + (by_title or 0), refs),
        "linked_by_doi": by_doi or 0, "linked_by_title": by_title or 0,
        "papers_citing_kci_pct": ratio(linked_papers, papers),
        "papers_citing_kci_among_with_refs_pct": ratio(linked_papers, with_refs),
    }


def edges_for(rowid: int, db_path: Optional[Path] = None) -> Tuple[List[int], List[int]]:
    """(이 논문이 인용한 KCI 논문, 이 논문을 인용한 KCI 논문). 그래프가 없으면 빈 목록."""
    path = graph_path(db_path)
    if not path.is_file():
        return [], []
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            out = [r[0] for r in conn.execute("SELECT cited FROM kci_cites WHERE citing = ?", (rowid,))]
            inc = [r[0] for r in conn.execute("SELECT citing FROM kci_cites WHERE cited = ?", (rowid,))]
            return out, inc
    except sqlite3.Error as error:
        logger.warning("KCI 인용 그래프 조회 실패: %s", error)
        return [], []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KCI 인용 관계 수집(Crossref)")
    parser.add_argument("--titles", action="store_true", help="제목 색인 만들기")
    parser.add_argument("--limit", type=int, help="이번에 처리할 논문 수(생략 시 끝까지)")
    parser.add_argument("--report", action="store_true", help="매칭률 출력")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if args.titles:
        logger.info("제목 색인: %d편", build_title_keys())
    if args.report:
        print(report())
    elif not args.titles or args.limit:
        logger.info("완료: %d편", harvest(args.limit))
