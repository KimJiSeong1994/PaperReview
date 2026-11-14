"""Provider access failures stay truthful while permitted paths recover."""
import json
import threading
import time
from unittest.mock import MagicMock

import pytest
import requests

from src.collector.paper.connected_papers_searcher import ConnectedPapersSearcher
from src.collector.paper.dblp_searcher import DBLPSearcher
from src.collector.paper.google_scholar_searcher import GoogleScholarSearcher
from src.collector.paper.provider_access import ProviderAccessError, access_details, retry_after_seconds
from src.collector.paper.rate_limiter import RateLimiter
from src.collector.paper.semantic_scholar_client import SemanticScholarClient


def response(status, body, content_type='application/json', headers=None):
    value = requests.Response()
    value.status_code = status
    value._content = body.encode()
    value._content_consumed = True
    value.url = 'https://provider.example/resource'
    value.headers.update({'Content-Type': content_type, **(headers or {})})
    return value


def sparql_response():
    def binding(author, ordinal):
        return {key: {'value': value} for key, value in {
            'paper': 'https://dblp.org/rec/conf/example/Paper26',
            'title': 'Graph Neural Networks.', 'year': '2026',
            'doi': 'https://doi.org/10.1234/ABC', 'venue': 'Test Conference',
            'authorName': author, 'ordinal': str(ordinal),
        }.items()}
    value = MagicMock(status_code=200)
    value.iter_content.return_value = [json.dumps({'results': {'bindings': [binding('Alice', 1), binding('Bob', 2), binding('Alice', 1)]}}).encode()]
    return value


@pytest.fixture
def dblp(monkeypatch):
    monkeypatch.setenv('DBLP_SEARCH_BACKEND', 'auto')
    value = DBLPSearcher()
    value.session.close()
    value.session = MagicMock()
    value.session.get.return_value = response(202, '<html>Making sure you are not a bot</html>', 'text/html')
    value.session.post.return_value = sparql_response()
    monkeypatch.setattr(value, '_rate_limit', lambda: None)
    return value


def test_dblp_html_uses_documented_sparql_without_challenge_execution(dblp):
    papers = dblp.search('graph neural networks', 3)
    assert len(papers) == 1
    assert papers[0]['source'] == 'DBLP'
    assert papers[0]['doi'] == '10.1234/abc'
    assert papers[0]['authors'] == ['Alice', 'Bob']
    assert papers[0]['venue'] == 'Test Conference'
    assert dblp.session.post.call_args.args[0] == 'https://sparql.dblp.org/sparql'
    dblp.session.post.return_value.close.assert_called_once()
    dblp.search('graph neural networks', 3)
    assert dblp.session.get.call_count == 1  # do not probe the challenged site repeatedly


def test_sparql_config_skips_rest_and_has_safe_literal_queries(dblp):
    dblp.backend = 'sparql'
    dblp.search_by_title('Paper " } SERVICE <https://bad.example> { ?s ?p ?o } #', 2)
    query = dblp.session.post.call_args.kwargs['data'].decode()
    assert '\\"' in query
    assert 'LIMIT 2' in query
    dblp.session.get.assert_not_called()


def test_sparql_valid_empty_and_malformed_response_differ(dblp):
    dblp.backend = 'sparql'
    dblp.session.post.return_value.iter_content.return_value = [b'{"results":{"bindings":[]}}']
    assert dblp.search('graph') == []
    dblp.session.post.return_value.iter_content.return_value = [b'{"error":"unavailable"}']
    with pytest.raises(ProviderAccessError, match='invalid_response'):
        dblp.search('graph')


def test_sparql_author_search_queries_authorship_instead_of_title(dblp):
    dblp.backend = 'sparql'
    assert dblp.search_by_author('Alice')
    query = dblp.session.post.call_args.kwargs['data'].decode()
    assert 'dblp:authoredBy ?person' in query
    assert 'STR(?personName)' in query
    dblp.session.get.assert_not_called()


def test_sparql_deadline_body_limit_and_cancellation(dblp):
    dblp.backend = 'sparql'
    with pytest.raises(TimeoutError):
        dblp.search('graph', deadline=time.monotonic()-1)
    dblp.session.post.assert_not_called()
    dblp.session.post.return_value.iter_content.return_value = [b'x' * (2*1024*1024 + 1)]
    with pytest.raises(ProviderAccessError, match='response_size_limit'):
        dblp.search('graph')
    stop = threading.Event()
    def blocks(*args):
        stop.set()
        yield b'{}'
    dblp.session.post.return_value.iter_content.side_effect = blocks
    with pytest.raises(TimeoutError):
        dblp.search('graph', stop_event=stop)


def test_s2_retry_after_prevents_repeated_transport_and_recovers(monkeypatch):
    monkeypatch.setattr(SemanticScholarClient, '_rate_limiter', RateLimiter(0))
    value = ConnectedPapersSearcher()
    value.session.close()
    value.session = MagicMock()
    value.session.get.return_value = response(429, '{}', headers={'Retry-After': '120'})
    for _ in range(2):
        with pytest.raises(ProviderAccessError) as exc:
            value.search('graph')
        assert access_details(exc.value)['reason'] == 'rate_limited'
        assert access_details(exc.value)['http_status'] == 429
    assert value.session.get.call_count == 1
    value._cooldown_until = 0
    value.session.get.return_value = response(200, '{"data":[]}')
    assert value.search('graph') == []
    assert value.session.get.call_count == 2


def test_scholar_denial_opens_circuit_after_one_request(monkeypatch):
    value = GoogleScholarSearcher()
    monkeypatch.setattr(value, '_rate_limit', lambda: None)
    transport = MagicMock(return_value=response(403, 'denied', 'text/html'))
    monkeypatch.setattr(value.session, 'get', transport)
    for _ in range(2):
        attempts = []
        assert value.search('graph', attempts=attempts) == []
        assert attempts[0]['reason'] == 'access_denied'
        assert attempts[0]['http_status'] == 403
    assert attempts[0]['status'] == 'circuit_open'
    assert transport.call_count == 1
    assert value.is_circuit_open()


def test_scholar_waiting_request_rechecks_denial_before_transport(monkeypatch):
    value = GoogleScholarSearcher()
    def deny_while_waiting():
        value._access_issue = {'reason': 'access_denied', 'http_status': 403}
        value._consecutive_failures = value._circuit_breaker_threshold
        value._disabled_until = time.time() + 300
    monkeypatch.setattr(value, '_rate_limit', deny_while_waiting)
    value.session.get = MagicMock()
    attempts = []
    assert value.search('graph', attempts=attempts) == []
    value.session.get.assert_not_called()
    assert attempts[0]['reason'] == 'access_denied'


def test_rate_limit_queue_respects_deadline_and_stop():
    limiter = RateLimiter(10)
    limiter.wait()
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        limiter.wait(deadline=start + 0.02)
    assert time.monotonic() - start < 0.5
    stop = threading.Event()
    stop.set()
    with pytest.raises(TimeoutError):
        limiter.wait(stop_event=stop)


def test_retry_after_parsing_and_no_sensitive_details():
    assert retry_after_seconds('90') == 90
    assert retry_after_seconds('nan') == 60
    assert retry_after_seconds('invalid') == 60
    error = requests.HTTPError('secret token and URL', response=response(429, 'secret body'))
    details = access_details(error)
    assert details == {'reason': 'rate_limited', 'http_status': 429, 'retry_after_seconds': 60}


@pytest.mark.asyncio
async def test_http_search_preserves_access_reasons_and_dblp_results_in_cache(dblp, monkeypatch, tmp_path, client, auth_headers):
    from app.SearchAgent.search_agent import SearchAgent
    from src.collector.paper.deduplicator import PaperDeduplicator
    from src.graph_rag.hybrid_ranker import HybridRanker
    from routers import search as router

    monkeypatch.setattr(SemanticScholarClient, '_rate_limiter', RateLimiter(0))
    agent = SearchAgent.__new__(SearchAgent)
    agent.search_history = []
    agent.deduplicator = PaperDeduplicator()
    agent.similarity_calculator = None
    agent.dblp_searcher = dblp
    dblp.backend = 'sparql'
    s2 = agent.connected_papers_searcher = ConnectedPapersSearcher()
    s2.session.close()
    s2.session = MagicMock()
    s2.session.get.return_value = response(429, 'private body', headers={'Retry-After': '120'})
    scholar = agent.google_scholar_searcher = GoogleScholarSearcher()
    monkeypatch.setattr(scholar, '_rate_limit', lambda: None)
    scholar.session.get = MagicMock(return_value=response(403, 'private body', 'text/html'))
    analyzer = MagicMock()
    analyzer.analyze_and_prepare.return_value = {'is_academic': True, 'intent': 'paper_search', 'confidence': 0.5}
    monkeypatch.setattr(router, 'search_agent', agent)
    monkeypatch.setattr(router, 'query_analyzer', analyzer)
    monkeypatch.setattr(router, '_hybrid_ranker', HybridRanker())
    monkeypatch.setattr(router, '_RANKER_DEGRADATION_REASONS', [])
    monkeypatch.setattr(router, '_router_shutdown', threading.Event())
    monkeypatch.setattr(router, '_router_operation_owner', SearchAgent.__new__(SearchAgent))
    monkeypatch.setattr(router, '_persist_last_search', MagicMock())
    monkeypatch.setattr(router, 'get_openai_client', lambda: None)
    monkeypatch.setattr(router, '_search_cache', {})
    monkeypatch.setattr(router, 'SEARCH_CACHE_DIR', tmp_path/'cache')
    router.SEARCH_CACHE_DIR.mkdir()
    write = MagicMock(wraps=router._set_cache)
    monkeypatch.setattr(router, '_set_cache', write)
    body = {'query': 'graph neural networks', 'sources': ['dblp', 'google_scholar', 'connected_papers'],
            'max_results': 3, 'fast_mode': True, 'save_papers': False}
    first = await client.post('/api/search', json=body, headers=auth_headers)
    assert first.status_code == 200
    data = first.json()
    assert data['total'] == 1
    assert data['results']['dblp'][0]['source'] == 'DBLP'
    assert data['metadata']['partial'] is True
    errors = data['metadata']['source_errors']
    assert errors['connected_papers']['http_status'] == 429
    assert errors['google_scholar']['http_status'] == 403
    assert 'private body' not in first.text
    assert write.call_args.kwargs['ttl_seconds'] == 120
    second = await client.post('/api/search', json=body, headers=auth_headers)
    assert second.json()['cache_hit'] is True
    assert second.json()['metadata']['source_errors'] == errors
    assert s2.session.get.call_count == scholar.session.get.call_count == dblp.session.post.call_count == 1


def test_provider_configuration_changes_cache_namespace(monkeypatch):
    from routers.search import _compute_cache_key
    monkeypatch.delenv('S2_API_KEY', raising=False)
    monkeypatch.setenv('DBLP_SEARCH_BACKEND', 'auto')
    original = _compute_cache_key('graph', ['connected_papers', 'dblp'], {})
    monkeypatch.setenv('S2_API_KEY', 'test-only-never-a-real-key')
    keyed = _compute_cache_key('graph', ['connected_papers', 'dblp'], {})
    assert keyed != original
    monkeypatch.setenv('DBLP_SEARCH_BACKEND', 'sparql')
    assert _compute_cache_key('graph', ['connected_papers', 'dblp'], {}) != keyed
