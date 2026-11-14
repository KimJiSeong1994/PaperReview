"""KCI(한국학술지인용색인) 한글 논문: OAI-PMH 수집 + 로컬 FTS5 검색.

OAI-PMH 는 검색 기능이 없는 수집 전용 프로토콜이라, 레코드를 SQLite FTS5
색인(`KCI_DB_PATH`, 기본 `data/kci.db`)에 내려받아 두고 검색은 그 색인에서 한다.

수집 (중단 후 다시 실행하면 이어서 진행)::

    python -m src.collector.paper.kci_searcher              # 마지막 지점부터 오늘까지(이어받기)
    python -m src.collector.paper.kci_searcher --workers 8  # 남은 기간을 나눠 동시에 수집(이어받기)
    python -m src.collector.paper.kci_searcher --from 2026-01-01   # 구간 재수집(진행 상태와 무관)
"""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor
import os
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

OAI_URL = "https://open.kci.go.kr/oai/request"


def _default_db_path() -> Path:
    return Path(os.getenv("KCI_DB_PATH", "data/kci.db"))


def index_available() -> bool:
    return _default_db_path().is_file()


def _lookup_doi(db_path, doi):
    path = Path(str(db_path) + ".doi.db")
    if not path.is_file():
        return []
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            source = conn.execute("SELECT value FROM metadata WHERE key='source'").fetchone()
            if not source or source[0] != str(db_path.resolve()):
                return []
            return [r[0] for r in conn.execute("SELECT rowid FROM doi_lookup WHERE doi=? LIMIT 100", (doi,))]
    except sqlite3.Error:
        return []


_EARLIEST = "2013-03-21"  # Identify 응답의 earliestDatestamp
_WINDOW_DAYS = 30
_CHUNK_DAYS = 60  # 병렬 수집 시 작업 하나가 맡는 기간

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS kci USING fts5(
    title, title_en, abstract, abstract_en, authors, venue,
    year UNINDEXED, doi UNINDEXED, url UNINDEXED, citations UNINDEXED,
    tokenize='unicode61'
);
CREATE TABLE IF NOT EXISTS kci_state (key TEXT PRIMARY KEY, value TEXT);
"""
# bm25 가중치: title, title_en, abstract, abstract_en, authors, venue
_RANK = "bm25(kci, 10.0, 5.0, 1.0, 1.0, 2.0, 2.0)"
_PARTICLES = "은는이가을를의에로와과도"
# ponytail: 흔한 단어는 bm25 가 일치 행 전체를 채점해 느려진다(100만 건에서 1초대).
# 고정 목록으로 거르는 수준 → 부족하면 fts5vocab 문서빈도로 동적 제외.
_STOPWORDS = frozenset(
    "연구 분석 논문 관한 대한 관련 영향 효과 방법 방안 기반 이용 활용 통한 위한 중심 고찰 최신 최근 찾아줘 알려줘 정리".split()
)
_MAX_TERMS = 8


def _text(node: Optional[ET.Element], path: str) -> str:
    found = node.find(path) if node is not None else None
    return (found.text or "").strip() if found is not None else ""


def parse_records(xml_bytes: bytes) -> tuple[List[tuple], Optional[str]]:
    """ListRecords(oai_kci) 응답을 (kci 테이블 행 목록, 다음 resumptionToken) 으로 변환."""
    root = ET.fromstring(xml_bytes)
    error = root.find("{*}error")
    if error is not None and error.get("code") != "noRecordsMatch":
        raise ValueError(f"KCI OAI-PMH 오류: {error.get('code')} {error.text}")
    rows = []
    for item in root.iterfind(".//{*}oai_kci"):
        info = item.find("{*}articleInfo")
        match = re.fullmatch(r"ART0*(\d+)", info.get("article-id", "") if info is not None else "")
        if not match:
            continue
        journal = item.find("{*}journalInfo")
        names = [(n.text or "").strip() for n in info.iterfind("{*}author-name/{*}author/{*}name")]
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", _text(info, "{*}doi"))
        rows.append((
            int(match.group(1)),
            _text(info, "{*}title-group/{*}article-title[@lang='original']"),
            _text(info, "{*}title-group/{*}article-title[@lang='english']"),
            _text(info, "{*}abstract-group/{*}abstract[@lang='original']"),
            _text(info, "{*}abstract-group/{*}abstract[@lang='english']"),
            ", ".join(n for n in names if n),
            _text(journal, "{*}journal-name"),
            _text(journal, "{*}pub-year"),
            doi,
            _text(info, "{*}url"),
            int(cited) if (cited := _text(info, "{*}citation-count")).isdigit() else 0,
        ))
    if not rows and root.find(".//{*}record/{*}metadata") is not None:
        raise ValueError("KCI 응답에 레코드가 있으나 oai_kci 형식으로 읽지 못함")
    token = next((t.text.strip() for t in root.iterfind(".//{*}resumptionToken") if t.text and t.text.strip()), None)
    return rows, token


def _is_server_error(error: requests.RequestException) -> bool:
    return isinstance(error, requests.HTTPError) and getattr(error.response, "status_code", 0) >= 500


def _fetch(params: Dict[str, str]) -> bytes:
    """요청 하나를 받는다. 연결 문제는 재시도하고, 5xx 는 바로 올린다(같은 페이지는 계속 500)."""
    for attempt in range(1, 5):
        try:
            response = requests.get(OAI_URL, params=params, timeout=120)
            response.raise_for_status()
            return response.content
        except requests.RequestException as error:
            if attempt == 4 or _is_server_error(error):
                raise
            logger.warning("KCI 요청 실패(%s), 재시도 %d/3", error, attempt)
            time.sleep(10 * attempt)
    raise AssertionError("unreachable")


def _fetch_page(params: Dict[str, str]) -> tuple[List[tuple], Optional[str]]:
    """한 페이지를 받는다. 서버가 500 을 내는 레코드는 한 건씩 받아 그 건만 건너뛴다.

    KCI 는 특정 레코드(예: ARTI/501105)가 낀 페이지에 항상 500 을 낸다(실측).
    토큰은 `from:until:페이지크기:시작번호` 형식이라 크기를 1 로 줄여 문제 레코드를 가려낸다.
    차단(4xx)이나 연결 장애는 레코드 문제가 아니므로 건너뛰지 않고 그대로 올린다.
    """
    try:
        return parse_records(_fetch(params))
    except requests.RequestException as error:
        head, _, cursor = params.get("resumptionToken", "").rpartition(":")
        head, _, size = head.rpartition(":")
        if not (_is_server_error(error) and size.isdigit() and cursor.isdigit() and int(size) > 1):
            raise
    rows: List[tuple] = []
    token: Optional[str] = f"{head}:1:{cursor}"
    for _ in range(int(size)):
        try:
            page, next_token = parse_records(_fetch({**params, "resumptionToken": token}))
        except requests.RequestException as error:
            if not _is_server_error(error):
                raise
            bad = int(token.rpartition(":")[2])
            logger.warning("KCI 가 500 을 내는 레코드 건너뜀: ARTI/%d", bad)
            page, next_token = [], f"{head}:1:{bad + 1}"
        rows += page
        token = next_token
        if not token:
            return rows, None
    return rows, f"{head}:{size}:{token.rpartition(':')[2]}"


def harvest(
    db_path: Optional[Path] = None, start: Optional[str] = None, until: Optional[str] = None, chunk: bool = False
) -> int:
    """KCI 논문 레코드를 날짜 구간별로 내려받아 색인한다. 저장한 레코드 수를 반환.

    `start` 없이 실행하면 페이지마다 진행 상태(다음 시작일, resumptionToken)를
    커밋하고, 중단 후 다시 실행하면 그 지점부터 이어받는다. `start` 를 주면 그
    구간만 다시 받고 진행 상태는 건드리지 않는다. 같은 논문은 article-id 로 덮어쓴다.
    `chunk=True` 는 병렬 수집용: (start, until) 구간별로 진행 상태를 따로 두고 이어받는다.
    """
    prefix = f"{start}~{until}:" if chunk else ""
    stateful = chunk or start is None
    db_path = db_path or _default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    end = date.fromisoformat(until) if until else date.today()
    saved = 0
    with closing(sqlite3.connect(db_path, timeout=60)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")  # 수집 중에도 검색이 막히지 않게
        conn.executescript(_SCHEMA)
        state = {
            key[len(prefix):]: value
            for key, value in conn.execute("SELECT key, value FROM kci_state")
            if stateful and key.startswith(prefix)
        }
        token = state.get("token")
        day = date.fromisoformat(state.get("next_from") or start or _EARLIEST)
        resumable = stateful and day <= end
        while day <= end:
            # metadataPrefix 는 토큰 요청에도 넣는다(빼면 KCI 가 oai_dc 로 응답).
            params = {"verb": "ListRecords", "set": "ARTI", "metadataPrefix": "oai_kci"}
            if token:
                # 토큰은 발급 당시 구간에 묶여 있으므로 저장해 둔 구간 끝을 쓴다.
                window_end = date.fromisoformat(state["window_end"])
                params["resumptionToken"] = token
            else:
                window_end = min(day + timedelta(days=_WINDOW_DAYS - 1), end)
                params.update({"from": day.isoformat(), "until": window_end.isoformat()})
            rows, token = _fetch_page(params)
            if not token:
                day = window_end + timedelta(days=1)
            state = {"next_from": day.isoformat(), "window_end": window_end.isoformat(), "token": token}
            with conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO kci(rowid, title, title_en, abstract, abstract_en, authors,"
                    " venue, year, doi, url, citations) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
                if resumable:
                    conn.executemany(
                        "INSERT OR REPLACE INTO kci_state VALUES (?, ?)",
                        [(prefix + key, value) for key, value in state.items()],
                    )
            saved += len(rows)
            logger.info("KCI 수집: 누적 %d건 (구간 ~%s, token=%s)", saved, window_end, token)
            time.sleep(0.5)
        # 마지막 날은 다음 실행에서 다시 받는다(그날 뒤늦게 갱신된 레코드 대비, 덮어쓰기라 안전).
        if resumable and not chunk:
            with conn:
                conn.execute("INSERT OR REPLACE INTO kci_state VALUES ('next_from', ?)", (end.isoformat(),))
    return saved


def harvest_parallel(workers: int, db_path: Optional[Path] = None) -> int:
    """마지막 수집 지점부터 오늘까지를 기간별 작업으로 나눠 `workers` 개씩 동시에 받는다.

    작업마다 진행 상태를 따로 저장하므로, 중단 후 같은 명령으로 다시 실행하면
    끝난 작업은 건너뛰고 나머지를 이어받는다. 모두 끝나면 기본 실행의 수집 지점을 오늘로 옮긴다.
    """
    db_path = db_path or _default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path, timeout=60)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        first = conn.execute("SELECT value FROM kci_state WHERE key = 'next_from'").fetchone()
        day, end = date.fromisoformat(first[0] if first else _EARLIEST), date.today()
        chunks = []
        while day <= end:
            chunk_end = min(day + timedelta(days=_CHUNK_DAYS - 1), end)
            chunks.append((day.isoformat(), chunk_end.isoformat()))
            day = chunk_end + timedelta(days=1)
        with ThreadPoolExecutor(workers) as pool:
            saved = sum(pool.map(lambda span: harvest(db_path, *span, chunk=True), chunks))
        with conn:
            conn.executemany(
                "INSERT OR REPLACE INTO kci_state VALUES (?, ?)", [("next_from", end.isoformat()), ("token", None)]
            )
    return saved


def _query(db_path: Path, terms: List[str], max_results: int, *, filters=None,
           route=None, deadline=None, stop_event=None, receipt=None, use_lookup=True) -> List[tuple]:
    filters = filters or {}
    rows: List[tuple] = []
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
        cutoff = min(deadline if deadline is not None else float("inf"), time.monotonic() + 3)
        conn.set_progress_handler(lambda: int(time.monotonic() >= cutoff or
                                  (stop_event is not None and stop_event.is_set())), 1000)
        from src.utils.paper_utils import normalize_doi, normalize_title
        conn.create_function("norm_doi", 1, normalize_doi, deterministic=True)
        conn.create_function("norm_title", 1, normalize_title, deterministic=True)
        where, params = [], []
        if filters.get("year_start") is not None or filters.get("year_end") is not None:
            where.append("substr(year,1,4) GLOB '[0-9][0-9][0-9][0-9]'")
        for key, op in (("year_start", ">="), ("year_end", "<=")):
            if filters.get(key) is not None:
                where.append(f"CAST(year AS INTEGER) {op} ?")
                params.append(filters[key])
        if filters.get("author"):
            wanted = normalize_title(filters["author"]).split()
            def author_matches(value):
                for author in (value or "").split(", "):
                    tokens = normalize_title(author).split()
                    if any(tokens[i:i + len(wanted)] == wanted for i in range(len(tokens))):
                        return 1
                return 0
            conn.create_function("author_matches", 1, author_matches)
            where.append("author_matches(authors)")
        kind = (route or {}).get("kind", "topic")
        exact = kind in ("doi", "title")
        ids = []
        if exact:
            if kind == "doi":
                where.append("norm_doi(doi) = ?")
                params.append(normalize_doi(route["value"]))
                ids = _lookup_doi(db_path, normalize_doi(route["value"])) if use_lookup else []
                if ids:
                    # Verify the live record too: stale mappings cannot return
                    # another paper if a harvested record changes its DOI.
                    where.append("rowid IN (" + ",".join("?" for _ in ids) + ")")
                    params.extend(ids)
            else:
                if terms:
                    where.append("kci MATCH ?")
                    params.append(" AND ".join(f'"{t}"*' for t in terms))
                where.append("(norm_title(title) = ? OR norm_title(title_en) = ?)")
                params.extend([normalize_title(route["value"])] * 2)
        order = "CAST(year AS INTEGER) DESC, rowid" if filters.get("sort_by") == "submittedDate" else ("rowid" if exact else _RANK + ", rowid")
        seen = set()
        for tier, joiner in enumerate((" AND ", " OR ") if not exact else ("",)):
            clauses, values = list(where), list(params)
            if not exact:
                clauses.insert(0, "kci MATCH ?")
                values.insert(0, joiner.join(f'"{t}"*' for t in terms))
            if seen:
                clauses.append("rowid NOT IN (" + ",".join("?" for _ in seen) + ")")
                values.extend(sorted(seen))
            try:
                page = conn.execute(
                    "SELECT rowid, title, title_en, abstract, abstract_en, authors, venue, year, doi, url, citations"
                    f" FROM kci WHERE {' AND '.join(clauses)} ORDER BY {order} LIMIT ?",
                    [*values, max_results - len(rows)],
                ).fetchall()
            except sqlite3.OperationalError as error:
                if rows and "interrupted" in str(error):
                    if receipt is not None:
                        receipt.update(status="partial_timeout", reason="relaxed_query_deadline")
                    return rows
                raise
            rows.extend((*row, tier) for row in page)
            seen.update(row[0] for row in page)
            if len(rows) >= max_results or len(terms) == 1 or exact:
                break
    if ids and not rows:
        return _query(db_path, terms, max_results, filters=filters, route=route,
                      deadline=cutoff, stop_event=stop_event, receipt=receipt, use_lookup=False)
    return rows


def search_kci(query: str, max_results: int = 10, db_path: Optional[Path] = None, *,
               filters=None, route=None, deadline=None, stop_event=None, attempts=None,
               retrieval_mode=None) -> List[Dict[str, Any]]:
    """로컬 KCI 색인에서 논문을 찾는다. 색인이 없으면 빈 목록."""
    db_path = db_path or _default_db_path()
    receipt = {"provider": "kci", "query": query, "status": "searched_empty"}
    if attempts is not None:
        attempts.append(receipt)
    if (deadline is not None and time.monotonic() >= deadline) or (stop_event is not None and stop_event.is_set()):
        receipt.update(status="timeout", reason="budget_expired")
        return []
    if not db_path.exists():
        receipt.update(status="error", reason="index_missing")
        return []
    # ponytail: 형태소 분석 없이 조사 한 글자만 떼고 접두 일치로 찾는다.
    # 합성어 내부("심층신경망" ← "신경망")는 못 찾음 → 필요해지면 형태소 분석기/임베딩 색인.
    terms = [
        t[:-1] if len(t) >= 3 and t[-1] in _PARTICLES else t
        for t in re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    ]
    terms = list(dict.fromkeys(t for t in terms if len(t) >= 2))
    terms = ([t for t in terms if t not in _STOPWORDS] or terms)[:_MAX_TERMS]
    if not terms and (route or {}).get("kind") not in ("doi", "title"):
        return []
    from src.graph_rag.spectral_retriever import configured_mode, retrieve, MAX_CANDIDATES
    mode = retrieval_mode or configured_mode()
    if mode not in ("baseline", "spectral", "ppr"):
        raise ValueError("Unknown KCI retrieval mode")
    if not 1 <= max_results <= 100:
        raise ValueError("max_results must be between 1 and 100")
    # Exact routes and explicit chronological sorting retain their contracts.
    use_graph = mode != "baseline" and (route or {}).get("kind", "topic") == "topic" and (filters or {}).get("sort_by", "relevance") == "relevance"
    limit = min(MAX_CANDIDATES, max_results * 4) if use_graph else max_results
    try:
        rows = _query(db_path, terms, limit, filters=filters, route=route,
                      deadline=deadline, stop_event=stop_event, receipt=receipt)
    except sqlite3.Error as error:
        # 색인 문제(잠금, 손상, 테이블 없음)가 한글 검색 전체를 막지 않게 한다.
        logger.warning("KCI 색인 검색 실패: %s", error)
        receipt.update(status="timeout" if "interrupted" in str(error) else "error", reason="index_query_failed")
        return []
    papers = [
        {
            "kci_id": f"ART{rowid:09d}",
            "id": f"ART{rowid:09d}",
            "title": title or title_en,
            "title_en": title_en,
            "authors": [a for a in authors.split(", ") if a],
            "abstract": abstract or abstract_en,
            "abstract_en": abstract_en,
            "url": url,
            "pdf_url": "",
            "source": "KCI",
            "year": year,
            "citations": citations,
            "doi": doi,
            "venue": venue,
            "_kci_match_tier": tier,
        }
        for rowid, title, title_en, abstract, abstract_en, authors, venue, year, doi, url, citations, tier in rows
    ]
    if use_graph:
        selected = retrieve(query, papers, max_results, mode=mode, deadline=deadline, stop_event=stop_event)
        papers = selected.papers
        receipt["retrieval"] = selected.metadata
    if receipt["status"] != "partial_timeout":
        receipt["status"] = "searched" if papers else "searched_empty"
    return papers


def index_cache_signature() -> str:
    """Include WAL commits as well as DB replacement in search-cache identity."""
    from src.graph_rag.spectral_retriever import VERSION, configured_mode
    path = _default_db_path().resolve()
    parts = [VERSION, configured_mode(), str(path)]
    for file in (path, Path(str(path) + "-wal"), Path(str(path) + ".doi.db")):
        try:
            stat = file.stat()
            parts.extend([str(stat.st_ino), str(stat.st_size), str(stat.st_mtime_ns)])
        except OSError:
            parts.append("missing")
    return "|".join(parts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KCI OAI-PMH 수집")
    parser.add_argument("--from", dest="start", help="YYYY-MM-DD (생략 시 마지막 수집 지점)")
    parser.add_argument("--until", help="YYYY-MM-DD (생략 시 오늘)")
    parser.add_argument("--workers", type=int, default=1, help="동시 수집 작업 수 (--from/--until 과 함께 쓰지 않음)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if args.workers > 1:
        logger.info("완료: %d건", harvest_parallel(args.workers))
    else:
        logger.info("완료: %d건", harvest(start=args.start, until=args.until))
