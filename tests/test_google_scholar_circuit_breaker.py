"""Circuit-breaker state reporting for the Google Scholar searcher."""
import time

from src.collector.paper.google_scholar_searcher import GoogleScholarSearcher


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
