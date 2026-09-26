"""Circuit-breaker state reporting for the Google Scholar searcher."""
import time
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from src.collector.paper.google_scholar_searcher import GoogleScholarSearcher, ScholarBudgetExhausted


@pytest.mark.parametrize("cancellation", ["deadline", "stop", "rate_limit"])
@pytest.mark.parametrize("with_receipts", [True, False])
def test_local_cancellations_do_not_change_breaker(monkeypatch, cancellation, with_receipts):
    searcher = GoogleScholarSearcher()
    stop = threading.Event()
    deadline = time.monotonic() - 1 if cancellation == "deadline" else time.monotonic() + 60
    if cancellation == "stop":
        stop.set()
    monkeypatch.setattr(searcher, "_rate_limit", stop.set if cancellation == "rate_limit" else lambda: None)
    transport = MagicMock()
    monkeypatch.setattr(searcher.session, "get", transport)
    # Local cancellation must neither increment nor reset prior upstream failures.
    searcher._record_failure()
    for _ in range(searcher._circuit_breaker_threshold + 1):
        if cancellation == "rate_limit":
            stop.clear()
        attempts = [] if with_receipts else None
        if with_receipts:
            assert searcher.search("topic", deadline=deadline, stop_event=stop, attempts=attempts) == []
            assert attempts == [{"query": "topic", "status": "timeout"}]
        else:
            with pytest.raises(ScholarBudgetExhausted):
                searcher.search("topic", deadline=deadline, stop_event=stop)
        assert searcher._consecutive_failures == 1
        assert searcher.is_circuit_open() is False
    transport.assert_not_called()


@pytest.mark.parametrize("failure,status", [
    (requests.Timeout("upstream timed out"), "timeout"),
    (requests.HTTPError("503 upstream unavailable"), "error"),
])
@pytest.mark.parametrize("with_receipts", [True, False])
def test_upstream_failures_open_breaker(monkeypatch, failure, status, with_receipts):
    searcher = GoogleScholarSearcher()
    monkeypatch.setattr(searcher, "_rate_limit", lambda: None)
    transport = MagicMock()
    if isinstance(failure, requests.HTTPError):
        transport.return_value.raise_for_status.side_effect = failure
    else:
        transport.side_effect = failure
    monkeypatch.setattr(searcher.session, "get", transport)
    for _ in range(searcher._circuit_breaker_threshold):
        if with_receipts:
            attempts = []
            assert searcher.search("topic", attempts=attempts) == []
            assert attempts == [{"query": "topic", "status": status}]
        else:
            with pytest.raises(type(failure)):
                searcher.search("topic")
    assert searcher.is_circuit_open() is True
    attempts = []
    assert searcher.search("topic", attempts=attempts) == []
    assert attempts == [{"query": "topic", "status": "circuit_open"}]
    assert transport.call_count == searcher._circuit_breaker_threshold


def test_successful_empty_request_resets_consecutive_failures(monkeypatch):
    searcher = GoogleScholarSearcher()
    searcher._record_failure()
    monkeypatch.setattr(searcher, "_request_with_backoff", lambda *args, **kwargs: SimpleNamespace(text="no results"))
    monkeypatch.setattr(searcher, "_is_captcha_response", lambda response: False)
    monkeypatch.setattr(searcher, "_parse_search_results", lambda text, limit: [])
    assert searcher.search("no matches") == []
    assert searcher._consecutive_failures == 0
    searcher._record_failure()
    assert searcher._consecutive_failures == 1
    assert searcher.is_circuit_open() is False


def test_is_circuit_open_reports_state_without_resetting_it():
    """Unlike _is_available, the observer must not clear the failure counter."""
    searcher = GoogleScholarSearcher()

    assert searcher.is_circuit_open() is False

    for _ in range(searcher._circuit_breaker_threshold):
        searcher._record_failure()

    assert searcher.is_circuit_open() is True
    # Observing twice must not reset the breaker.
    assert searcher.is_circuit_open() is True
    assert searcher._consecutive_failures >= searcher._circuit_breaker_threshold

    # Once the cooldown lapses the breaker reads closed again.
    searcher._disabled_until = time.time() - 1
    assert searcher.is_circuit_open() is False
