"""Production incidents reproduced without external providers or credentials."""
import itertools
import sqlite3
from unittest.mock import MagicMock

import pytest

from app.SearchAgent.search_agent import SearchAgent, classify_search_route
from src.collector.paper import kci_searcher as kci
from src.collector.paper.deduplicator import PaperDeduplicator


KCI_URL = 'https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART003261978'


def test_same_title_cannot_attach_another_kci_papers_doi():
    papers = [
        dict(kci_id='ART002646829', id='ART002646829', source='KCI', title='권두언',
             authors=['김상래'], venue='신학과 학문', year='2020', doi=''),
        dict(kci_id='ART002644428', id='ART002644428', source='KCI', title='권두언',
             authors=['최정학'], venue='민주법학', year='2020', doi='10.15756/dls.2020.74..7'),
        dict(title='권두언', authors=['김창남'], year='2018', source='OpenAlex'),
    ]
    for rows in itertools.permutations(papers):
        result = PaperDeduplicator().deduplicate(list(rows))
        assert len(result) == 3
        assert next(p for p in result if p.get('kci_id') == 'ART002646829')['doi'] == ''


@pytest.mark.parametrize('query', [KCI_URL, 'ART003261978', 'kci:ART003261978'])
def test_kci_identity_route(query):
    assert classify_search_route(query) == dict(kind='kci', value='ART003261978')


def test_untrusted_url_is_not_a_kci_identity():
    assert classify_search_route(KCI_URL.replace('www.kci.go.kr', 'www.kci.go.kr.evil.test'))['kind'] == 'topic'
    assert classify_search_route('https://[invalid')['kind'] == 'topic'


def test_existing_index_kci_identity_and_legacy_url_title(tmp_path):
    path = tmp_path / 'kci.db'
    with sqlite3.connect(path) as conn:
        conn.executescript(kci._SCHEMA)
        for identifier, title in [(3261978, '그래프 신경망 연구'), (1477033, 'Unrelated medical study')]:
            conn.execute('INSERT INTO kci(rowid,title,title_en,abstract,abstract_en,authors,venue,year,doi,url,citations) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                         (identifier, title, KCI_URL, '', '', '김연구', '학술지', '2025', '', KCI_URL, 0))
    papers = kci.search_kci(KCI_URL, 10, path, route=dict(kind='kci', value='ART003261978'))
    assert [p['kci_id'] for p in papers] == ['ART003261978']
    assert papers[0]['title_en'] == ''
    assert kci.search_kci('ART009999999', 10, path, route=dict(kind='kci', value='ART009999999')) == []


def test_kci_identity_never_falls_through_to_other_providers():
    agent = SearchAgent.__new__(SearchAgent)
    agent.openalex_searcher = MagicMock()
    assert agent._search_single_source('openalex', KCI_URL, {}, {}, 10) == []
    agent.openalex_searcher.search.assert_not_called()


def test_chronological_kci_timeout_does_not_substitute_relevance_results(monkeypatch):
    agent = SearchAgent.__new__(SearchAgent)
    agent.openalex_searcher = MagicMock()
    agent.openalex_searcher.search_korean.return_value = [dict(title='Old climate paper', year='2008')]
    def timeout(*args, attempts, **kwargs):
        attempts.append(dict(provider='kci', status='timeout', reason='index_query_failed'))
        return []
    monkeypatch.setattr('app.SearchAgent.search_agent.search_kci', timeout)
    filters = dict(sort_by='submittedDate')
    assert agent._search_single_source('openalex_korean', '기후변화', filters, {}, 10) == []
    agent.openalex_searcher.search_korean.assert_not_called()
    assert filters['_attempts'][0]['status'] == 'timeout'


@pytest.mark.parametrize('query,expected', [
    ('2020년부터 2024년까지 그래프 신경망', {'year_start': 2020, 'year_end': 2024}),
    ('2026년 이전 그래프 신경망', {'year_end': 2025}),
    ('graph learning after 2024', {'year_start': 2025}),
    ('graph learning before 2026', {'year_end': 2025}),
    ('latest graph learning', {'sort_by': 'submittedDate'}),
])
def test_time_constraints_without_a_model(query, expected):
    from routers.search import SearchRequest, _resolve_search_constraints
    filters = {'sort_by': 'relevance'}
    _resolve_search_constraints(SearchRequest(query=query), filters)
    assert all(filters[k] == v for k, v in expected.items())


def test_inferred_category_and_ungrounded_year_are_not_hard_filters():
    from routers.search import SearchRequest, _resolve_search_constraints
    filters = {'sort_by': 'relevance'}
    _resolve_search_constraints(SearchRequest(query='그래프 신경망'), filters, {
        'confidence': .99, 'search_filters': {'category': 'graph machine learning', 'year_start': 2026},
    })
    assert filters == {'sort_by': 'relevance'}


def test_explicit_relevance_overrides_latest_intent():
    from routers.search import SearchRequest, _resolve_search_constraints
    filters = {'sort_by': 'relevance'}
    _resolve_search_constraints(SearchRequest(query='최신 그래프 신경망', sort_by='relevance'), filters)
    assert filters['sort_by'] == 'relevance'


def test_different_source_controls_cannot_share_cache():
    from routers.search import _compute_cache_key
    keys = {_compute_cache_key('GraphRAG', ['openalex_korean'], controls) for controls in (
        {}, {'include_related': True}, {'strict_sources': True},
    )}
    assert len(keys) == 3


def test_harvest_does_not_index_catalog_urls_as_titles():
    from tests.test_kci_searcher import _page
    page = _page('ART000000001', '실제 논문 제목').replace(
        b'Graph Neural Network Recommendation', KCI_URL.replace('&', '&amp;').encode())
    rows, _ = kci.parse_records(page)
    assert rows[0][1] == '실제 논문 제목'
    assert rows[0][2] == ''


def test_legacy_title_repair_is_auditable_idempotent_and_updates_fts(tmp_path):
    import json
    from scripts.repair_kci_title_urls import repair
    path = tmp_path / 'kci.db'
    with sqlite3.connect(path) as conn:
        conn.executescript(kci._SCHEMA)
        conn.executemany('INSERT INTO kci(rowid,title,title_en,doi) VALUES (?,?,?,?)', [
            (1, 'Actual title', KCI_URL, '10.1234/keep'),
            (2, 'HTTP transport protocol', None, ''),
        ])
    assert repair(path)['affected'] == 1
    assert repair(path)['changed'] == 0
    backup = tmp_path / 'before.jsonl'
    assert repair(path, backup=backup)['changed'] == 1
    assert json.loads(backup.read_text())['before'] == ['Actual title', KCI_URL]
    assert repair(path)['affected'] == 0
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT rowid FROM kci WHERE kci MATCH 'https'").fetchall() == []
        assert conn.execute('SELECT title,title_en,doi FROM kci WHERE rowid=1').fetchone() == ('Actual title', '', '10.1234/keep')
        assert conn.execute('SELECT title,title_en FROM kci WHERE rowid=2').fetchone() == ('HTTP transport protocol', None)
    with pytest.raises(FileExistsError):
        repair(path, backup=backup)
