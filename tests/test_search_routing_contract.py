"""Deterministic source-boundary contracts; no live provider calls."""
from unittest.mock import ANY, MagicMock
import pytest
import time
import threading

from app.SearchAgent.search_agent import SearchAgent, apply_search_filters, classify_search_route
from app.QueryAgent.query_analyzer import normalize_source_queries
from src.collector.paper.arxiv_searcher import ArxivSearcher


def test_bilingual_queries_are_typed_bounded_and_not_fabricated():
    result = normalize_source_queries('한국어 검색', {'default': 'Korean research', 'google_scholar': ['one', None, {}, 'one', 'two', 'three', 'four']})
    assert result['openalex'] == 'Korean research'
    assert result['openalex_korean'] == '한국어 검색'
    assert result['scholar_queries'] == ['one', 'two', 'three']
    assert normalize_source_queries('한국어 검색')['openalex'] == '한국어 검색'
    assert normalize_source_queries('query', {'google_scholar': 'single'})['scholar_queries'] == ['single']


def test_routes_do_not_treat_short_topics_as_titles():
    assert classify_search_route('graph learning')['kind'] == 'topic'
    assert classify_search_route('"Graph Learning"') == {'kind': 'title', 'value': 'Graph Learning'}
    assert classify_search_route('https://doi.org/10.1234/ABC')['value'] == '10.1234/abc'
    assert classify_search_route('https://arxiv.org/abs/2401.12345v2')['value'] == '2401.12345'


def test_hard_filters_unknowns_boundaries_and_update_sort():
    papers = [
        {'title': 'a', 'year': 2020, 'authors': ['Li Wei'], 'categories': ['cs.AI'], 'updated': '2024-01-01'},
        {'title': 'b', 'year': 2021, 'authors': ['Williams'], 'categories': ['cs.AI']},
        {'title': 'c', 'authors': ['Li']},
    ]
    kept, drops = apply_search_filters(papers, {'year_start': 2020, 'year_end': 2021, 'author': 'Li', 'category': 'cs.AI'})
    assert [p['title'] for p in kept] == ['a']
    assert drops == {'author': 1, 'unknown_year': 1}
    kept, _ = apply_search_filters([{'title': 'missing', 'year': 2099}, papers[0]], {'sort_by': 'lastUpdatedDate'})
    assert [p['title'] for p in kept] == ['a', 'missing']


def test_scholar_round_robin_before_cap_and_malformed_variants():
    agent = SearchAgent.__new__(SearchAgent)
    agent.search_history = []
    agent.google_scholar_searcher = MagicMock()
    agent.google_scholar_searcher.search.side_effect = lambda q, *args, **kwargs: [{'title': q + str(i)} for i in range(4)]
    result = agent._search_single_source('google_scholar', 'topic', {}, {'scholar_queries': ['first', 'first', None, 'second']}, 3)
    assert [p['title'] for p in result] == ['first0', 'second0', 'first1']
    assert agent.google_scholar_searcher.search.call_count == 2
    assert len(agent._search_single_source('google_scholar', 'topic', {}, {'scholar_queries': ['first', 'second']}, 1)) == 1


def test_exact_doi_rejects_wrong_paper_even_when_title_matches():
    agent = SearchAgent.__new__(SearchAgent)
    agent.openalex_searcher = MagicMock()
    agent.openalex_searcher.search.return_value = [{'title': 'same', 'doi': '10.1234/wrong'}, {'title': 'same', 'doi': 'https://doi.org/10.1234/right'}]
    papers = agent._search_single_source('openalex', 'rewritten', {'original_query': '10.1234/right'}, {}, 5)
    assert len(papers) == 1
    assert papers[0]['doi'].endswith('/right')
    agent.openalex_searcher.search.assert_called_once_with('10.1234/right', 5, deadline=ANY, stop_event=ANY, attempts=ANY)


def test_quoted_title_ignores_proposed_rewrite_and_uses_title_adapter():
    agent = SearchAgent.__new__(SearchAgent)
    agent.openalex_searcher = MagicMock()
    agent.openalex_searcher.search_by_title.return_value = [{'title': 'Original Title'}]
    result = agent._search_single_source('openalex', 'rewritten topic', {'original_query': '"Original Title"'}, {'openalex': 'unrelated'}, 3)
    assert result == [{'title': 'Original Title'}]
    agent.openalex_searcher.search_by_title.assert_called_once_with('Original Title', 3, deadline=ANY, stop_event=ANY, attempts=ANY)
    agent.openalex_searcher.search.assert_not_called()


def test_year_end_is_inclusive_and_active_category_rejects_unknown():
    papers = [{'title': 'boundary', 'published_date': '2024-12-31', 'categories': ['cs.LG']}, {'title': 'unknown', 'year': 2024}]
    result, drops = apply_search_filters(papers, {'year_start': 2024, 'year_end': 2024, 'category': 'cs.LG'})
    assert [p['title'] for p in result] == ['boundary']
    assert drops == {'unknown_category': 1}


def test_arxiv_attempts_are_distinct_and_deadline_stops_transport(monkeypatch):
    searcher = ArxivSearcher()
    monkeypatch.setattr(searcher, '_rate_limit', lambda *args: None)
    calls = []
    monkeypatch.setattr(searcher.client, 'results', lambda search: calls.append(search.query) or iter([]))
    assert searcher.search('graph learning', 10) == []
    assert len(calls) == 2
    assert len(set(calls)) == 2
    calls.clear()
    with pytest.raises(TimeoutError):
        searcher.search('graph learning', 10, deadline=time.monotonic() - 1)
    assert calls == []
    stop = threading.Event()
    stop.set()
    with pytest.raises(TimeoutError):
        searcher.search('graph learning', 10, stop_event=stop)
    assert calls == []


@pytest.mark.parametrize("query", ["graph learning", '"Exact Paper Title"', "10.1234/paper"])
@pytest.mark.parametrize("cutoff", ["stop", "deadline"])
def test_dblp_budget_reaches_transport_boundary(monkeypatch, query, cutoff):
    from types import SimpleNamespace
    from src.collector.paper import dblp_searcher

    agent = SearchAgent.__new__(SearchAgent)
    agent.dblp_searcher = dblp_searcher.DBLPSearcher()
    stop = threading.Event()
    deadline = time.monotonic() + 30
    transport = MagicMock(side_effect=AssertionError("expired DBLP must not send HTTP"))
    monkeypatch.setattr(agent.dblp_searcher.session, "get", transport)

    def rate_limit():
        if cutoff == "stop":
            stop.set()
        else:
            monkeypatch.setattr(dblp_searcher, "time", SimpleNamespace(monotonic=lambda: deadline))

    monkeypatch.setattr(agent.dblp_searcher, "_rate_limit", rate_limit)
    with pytest.raises(TimeoutError):
        agent._search_single_source(
            "dblp", query, {"_deadline": deadline, "_stop_event": stop},
            normalize_source_queries(query), 5,
        )
    transport.assert_not_called()
