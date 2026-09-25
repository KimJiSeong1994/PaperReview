"""DBLP cannot turn provider failure or an expired budget into healthy emptiness."""
import threading
import time
from unittest.mock import MagicMock

import pytest
import requests

from src.collector.paper.dblp_searcher import DBLPSearcher


@pytest.fixture
def searcher(monkeypatch):
    instance = DBLPSearcher()
    instance.session = MagicMock()
    monkeypatch.setattr(instance, '_rate_limit', lambda: None)
    return instance


@pytest.mark.parametrize('failure', [requests.Timeout('expired'), requests.HTTPError('503'), ValueError('invalid JSON')])
def test_transport_failure_propagates(searcher, failure):
    searcher.session.get.side_effect = failure
    with pytest.raises(type(failure)):
        searcher.search('graph retrieval')


def test_real_empty_is_empty_and_transport_obeys_remaining_budget(searcher):
    searcher.session.get.return_value.json.return_value = {'result': {'hits': {'hit': []}}}
    assert searcher.search('graph retrieval', deadline=time.monotonic() + 0.5) == []
    assert 0 < searcher.session.get.call_args.kwargs['timeout'] <= 0.5


def test_stop_during_rate_limit_prevents_transport(searcher, monkeypatch):
    stop = threading.Event()
    monkeypatch.setattr(searcher, '_rate_limit', stop.set)
    with pytest.raises(TimeoutError, match='rate limiting'):
        searcher.search_by_title('Exact title', deadline=time.monotonic() + 2, stop_event=stop)
    searcher.session.get.assert_not_called()


def test_expired_budget_admits_no_transport(searcher):
    with pytest.raises(TimeoutError, match='budget expired'):
        searcher.search('graph retrieval', deadline=time.monotonic() - 1)
    searcher.session.get.assert_not_called()
