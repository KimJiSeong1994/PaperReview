"""Every text in one comparison must be embedded by one model.

The calculator used to pick a model per text by detecting its language: Korean
text went to ``text-embedding-3-large`` (3072 dim), English to
``text-embedding-3-small`` (1536 dim). Embeddings are only useful when compared,
and vectors from different models cannot be compared at all — so a Korean query
against English papers produced no semantic signal whatsoever, in a product
whose primary language is Korean.

These tests pin the invariant that replaced it: one model per calculator.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.collector.paper.similarity_calculator import SimilarityCalculator

KOREAN_QUERY = "대규모 언어 모델 파인튜닝 최신 연구"
ENGLISH_DOC = "Parameter-efficient fine-tuning of large language models"


# Real OpenAI dimensions, so a stub that dispatches per language produces the
# same mismatch production did instead of quietly returning uniform vectors.
_MODEL_DIMS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072}


def _dimension_faithful_create(**kwargs):
    """Stand in for the embeddings API, returning that model's real width."""
    dim = _MODEL_DIMS[kwargs["model"]]
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.1] * dim) for _ in kwargs["input"]]
    )


@pytest.fixture
def calculator(tmp_path):
    """A calculator with an isolated cache DB and a stubbed OpenAI client."""
    with patch.object(SimilarityCalculator, "_init_sqlite_cache", lambda self: None):
        calc = SimilarityCalculator.__new__(SimilarityCalculator)
        calc.api_key = "test"
        calc.client = MagicMock()
        calc.model = "text-embedding-3-small"
        calc._l1_cache = __import__("collections").OrderedDict()
        calc._cache_lock = __import__("threading").Lock()
        calc._db_lock = __import__("threading").Lock()
        calc._db_conn = None
        calc._cache_db_path = tmp_path / "embeddings.db"
        calc.embedding_cache = calc._l1_cache
    # No SQLite in these tests: L2 is a no-op so assertions are about model choice.
    calc._l2_get_with_model = lambda text_hash, model: None
    calc._l2_set_batch_with_model = lambda items, model: None
    calc.client.embeddings.create.side_effect = _dimension_faithful_create
    return calc


def test_mixed_language_batch_uses_a_single_model(calculator):
    """A Korean query batched with English documents must not split models.

    This is the exact call shape ``_compute_semantic_scores`` makes:
    ``[query, title_0, abstract_0, ...]``.
    """
    calculator.get_embeddings_batch([KOREAN_QUERY, ENGLISH_DOC, "another english title"])

    models_used = {
        call.kwargs["model"] for call in calculator.client.embeddings.create.call_args_list
    }
    assert models_used == {"text-embedding-3-small"}, (
        f"batch split across models {models_used} — vectors from different models "
        "cannot be compared, which is how the Korean semantic signal was lost"
    )


def test_mixed_language_batch_returns_one_dimension(calculator):
    """The returned vectors must be mutually comparable."""
    vectors = calculator.get_embeddings_batch([KOREAN_QUERY, ENGLISH_DOC])

    dims = {np.asarray(v).shape for v in vectors if v is not None}
    assert len(dims) == 1, f"mixed embedding dimensions in one batch: {dims}"


def test_korean_single_text_uses_the_instance_model(calculator):
    """The single-text path must agree with the batch path."""
    calculator._get_embedding(KOREAN_QUERY)

    assert calculator.client.embeddings.create.call_args.kwargs["model"] == (
        "text-embedding-3-small"
    )


def test_model_follows_the_instance_not_the_text(calculator):
    """Switching the calculator's model switches every text with it.

    Moving to a stronger embedding model stays possible — it is a corpus-wide
    decision (change the default, rebuild the index), not a per-text one.
    """
    calculator.model = "text-embedding-3-large"

    calculator.get_embeddings_batch([KOREAN_QUERY, ENGLISH_DOC])

    models_used = {
        call.kwargs["model"] for call in calculator.client.embeddings.create.call_args_list
    }
    assert models_used == {"text-embedding-3-large"}


def test_korean_query_scores_against_english_papers(calculator):
    """End to end through the real calculator: a Korean query keeps its signal.

    Before the fix this path returned all-zero scores and logged
    ``HyDE dim mismatch: hyde=(3072,) paper=(1536,)``, dropping the dense signal
    for every Korean search while looking like a legitimate zero.
    """
    from src.graph_rag.hybrid_ranker import HybridRanker

    papers = [
        {"title": ENGLISH_DOC, "abstract": "LoRA and adapters", "paper_id": "p0"},
        {"title": "Unrelated protein folding paper", "abstract": "alphafold", "paper_id": "p1"},
    ]
    scores = HybridRanker(similarity_calculator=calculator)._compute_semantic_scores(
        KOREAN_QUERY, papers
    )

    assert len(scores) == len(papers)
    assert any(score > 0.0 for score in scores), (
        "every semantic score was zero for a Korean query — the dense signal is "
        "being dropped again"
    )
