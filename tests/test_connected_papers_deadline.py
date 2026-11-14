"""Connected Papers transport admission honors the caller's search budget."""
import threading
import time
from unittest.mock import MagicMock

import pytest

from src.collector.paper import connected_papers_searcher as connected_module
from src.collector.paper.connected_papers_searcher import ConnectedPapersSearcher


def _searcher() -> ConnectedPapersSearcher:
    searcher = ConnectedPapersSearcher()
    searcher.session = MagicMock()
    response = searcher.session.get.return_value
    response.json.return_value = {"data": []}
    return searcher


def test_search_clamps_transport_timeout_to_remaining_budget(monkeypatch):
    searcher = _searcher()
    monkeypatch.setattr(connected_module.time, "monotonic", lambda: 100.0)

    assert searcher.search("topic", deadline=100.25) == []

    request = searcher.session.get.call_args
    assert 0 < request.kwargs["timeout"] <= 0.25


def test_expired_budget_admits_no_transport(monkeypatch):
    searcher = _searcher()
    monkeypatch.setattr(connected_module.time, "monotonic", lambda: 100.0)

    with pytest.raises(TimeoutError, match="budget expired"):
        searcher.search("topic", deadline=99.0)

    searcher.session.get.assert_not_called()


def test_stop_event_admits_no_transport():
    searcher = _searcher()
    stop = threading.Event()
    stop.set()

    with pytest.raises(TimeoutError, match="cancelled"):
        searcher.search("topic", stop_event=stop)

    searcher.session.get.assert_not_called()


def test_search_rechecks_stop_after_transport_returns():
    searcher = _searcher()
    stop = threading.Event()
    response = searcher.session.get.return_value

    def get_and_cancel(*args, **kwargs):
        stop.set()
        return response

    searcher.session.get.side_effect = get_and_cancel

    with pytest.raises(TimeoutError, match="Connected Papers search cancelled"):
        searcher.search("topic", stop_event=stop)


def test_search_rechecks_deadline_after_json_parsing(monkeypatch):
    searcher = _searcher()
    now = [100.0]
    monkeypatch.setattr(connected_module.time, "monotonic", lambda: now[0])
    response = searcher.session.get.return_value

    def parse_and_expire():
        now[0] = 101.0
        return {
            "data": [
                {
                    "title": "stale",
                    "authors": [],
                    "paperId": "stale-id",
                }
            ]
        }

    response.json.side_effect = parse_and_expire

    with pytest.raises(TimeoutError, match="Connected Papers search budget expired"):
        searcher.search("topic", deadline=100.5)


def test_topic_and_doi_routes_pass_budget_to_connected_searcher():
    from app.SearchAgent.search_agent import SearchAgent

    agent = SearchAgent.__new__(SearchAgent)
    agent.search_history = []
    agent.connected_papers_searcher = MagicMock()
    agent.connected_papers_searcher.search.return_value = []
    stop = threading.Event()
    deadline = time.monotonic() + 1

    filters = {
        "_deadline": deadline,
        "_stop_event": stop,
        "_attempts": [],
        "original_query": "topic",
    }
    agent._search_single_source(
        "connected_papers",
        "topic",
        filters,
        {"default": "translated topic"},
        5,
    )
    agent.connected_papers_searcher.search.assert_called_once_with(
        "translated topic", 5, deadline=deadline, stop_event=stop
    )

    agent.connected_papers_searcher.search.reset_mock()
    doi_filters = {
        "_deadline": deadline,
        "_stop_event": stop,
        "_attempts": [],
        "original_query": "10.1234/example",
    }
    agent._search_single_source(
        "connected_papers",
        "10.1234/example",
        doi_filters,
        {"default": "10.1234/example"},
        5,
    )
    agent.connected_papers_searcher.search.assert_called_once_with(
        "10.1234/example", 5, deadline=deadline, stop_event=stop
    )
