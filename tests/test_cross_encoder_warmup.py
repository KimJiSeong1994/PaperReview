"""
Tests for cross-encoder warmup in api_server lifespan startup.

Verifies that _warm_cross_encoder() pre-loads the singleton model so the
first /api/search call is not slowed by a HuggingFace model download.
"""

from __future__ import annotations

import sys
import threading
from types import ModuleType
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def transformers_progress_bars():
    """Restore the process-global Transformers progress state after each test."""
    from transformers.utils import logging as transformers_logging

    initially_enabled = transformers_logging.is_progress_bar_enabled()
    try:
        yield transformers_logging
    finally:
        if initially_enabled:
            transformers_logging.enable_progress_bar()
        else:
            transformers_logging.disable_progress_bar()


def test_warm_cross_encoder_loads_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lifespan startup pre-loads cross-encoder to avoid cold-start timeout."""
    model = object()
    cross_encoder = MagicMock(return_value=model)
    module = ModuleType("sentence_transformers")
    module.CrossEncoder = cross_encoder  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    from api_server import _warm_cross_encoder
    from app.QueryAgent.relevance_filter import LocalRelevanceScorer

    monkeypatch.setattr(LocalRelevanceScorer, "_model", None)
    _warm_cross_encoder()

    # Check population before get_model() could conceal a warmup failure.
    assert LocalRelevanceScorer._model is model
    assert LocalRelevanceScorer.get_model() is model
    _warm_cross_encoder()
    assert LocalRelevanceScorer._model is model
    cross_encoder.assert_called_once()


def test_warm_cross_encoder_graceful_on_import_failure(monkeypatch) -> None:
    """Warmup failure logs a warning but does not raise — startup stays alive."""
    import api_server

    # Simulate an unexpected error inside the warmup helper
    def _failing_get_model():
        raise RuntimeError("simulated HF network failure")

    from app.QueryAgent import relevance_filter as rf_module

    monkeypatch.setattr(
        rf_module.LocalRelevanceScorer, "get_model", staticmethod(_failing_get_model)
    )

    # Must not raise — try/except inside _warm_cross_encoder absorbs the error
    api_server._warm_cross_encoder()


@pytest.mark.parametrize("initially_enabled", [True, False])
@pytest.mark.parametrize("get_model_raises", [False, True])
def test_warm_cross_encoder_restores_transformers_progress_bar_state(
    monkeypatch: pytest.MonkeyPatch,
    transformers_progress_bars,
    initially_enabled: bool,
    get_model_raises: bool,
) -> None:
    """Warmup restores both progress states after success and failure."""
    import api_server
    from app.QueryAgent import relevance_filter as rf_module

    if initially_enabled:
        transformers_progress_bars.enable_progress_bar()
    else:
        transformers_progress_bars.disable_progress_bar()

    observed_during_load: list[bool] = []

    def _fake_get_model():
        observed_during_load.append(
            transformers_progress_bars.is_progress_bar_enabled()
        )
        if get_model_raises:
            raise RuntimeError("simulated CrossEncoder load failure")
        return object()

    monkeypatch.setattr(
        rf_module.LocalRelevanceScorer,
        "get_model",
        staticmethod(_fake_get_model),
    )

    api_server._warm_cross_encoder()

    assert observed_during_load == [False]
    assert transformers_progress_bars.is_progress_bar_enabled() is initially_enabled


def test_warm_cross_encoder_fake_transformers_load_starts_no_thread(
    monkeypatch: pytest.MonkeyPatch,
    transformers_progress_bars,
) -> None:
    """A Transformers tqdm load during warmup cannot leave a monitor thread."""
    import api_server
    from app.QueryAgent import relevance_filter as rf_module
    from tqdm._monitor import TMonitor

    transformers_progress_bars.enable_progress_bar()
    threads_before = {thread for thread in threading.enumerate() if thread.is_alive()}
    observed_extra_threads: list[threading.Thread] = []

    def _fake_get_model():
        with transformers_progress_bars.tqdm(range(1)) as progress:
            list(progress)
        observed_extra_threads.extend(
            thread
            for thread in threading.enumerate()
            if thread.is_alive() and thread not in threads_before
        )
        return object()

    monkeypatch.setattr(
        rf_module.LocalRelevanceScorer,
        "get_model",
        staticmethod(_fake_get_model),
    )

    api_server._warm_cross_encoder()

    live_extra_threads = [
        thread
        for thread in threading.enumerate()
        if thread.is_alive() and thread not in threads_before
    ]
    assert observed_extra_threads == []
    assert live_extra_threads == []
    assert not any(isinstance(thread, TMonitor) for thread in live_extra_threads)
    assert transformers_progress_bars.is_progress_bar_enabled() is True
