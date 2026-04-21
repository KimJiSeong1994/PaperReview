"""
Tests for cross-encoder warmup in api_server lifespan startup.

Verifies that _warm_cross_encoder() pre-loads the singleton model so the
first /api/search call is not slowed by a HuggingFace model download.
"""
import time


def test_warm_cross_encoder_loads_model() -> None:
    """Lifespan startup pre-loads cross-encoder to avoid cold-start timeout."""
    from api_server import _warm_cross_encoder

    # Should not raise even if model is already loaded
    _warm_cross_encoder()

    # After warmup the singleton must be populated
    from app.QueryAgent.relevance_filter import LocalRelevanceScorer

    # Accessing get_model() after warmup must be fast (cached, no HF download)
    start = time.perf_counter()
    model = LocalRelevanceScorer.get_model()
    elapsed = time.perf_counter() - start

    assert model is not None, "LocalRelevanceScorer.get_model() returned None after warmup"
    assert elapsed < 1.0, (
        f"Cross-encoder still loading after warmup ({elapsed:.2f}s); "
        "expected <1s for cached singleton access"
    )


def test_warm_cross_encoder_graceful_on_import_failure(monkeypatch) -> None:
    """Warmup failure logs a warning but does not raise — startup stays alive."""
    import api_server

    # Simulate an unexpected error inside the warmup helper
    def _failing_get_model():
        raise RuntimeError("simulated HF network failure")

    from app.QueryAgent import relevance_filter as rf_module
    monkeypatch.setattr(rf_module.LocalRelevanceScorer, "get_model", staticmethod(_failing_get_model))

    # Must not raise — try/except inside _warm_cross_encoder absorbs the error
    api_server._warm_cross_encoder()
