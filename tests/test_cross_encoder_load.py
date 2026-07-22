"""Cross-encoder 모델 로드 경로 회귀 테스트.

배경: 가중치가 로컬에 있어도 기본 로드는 Hugging Face Hub로 메타데이터를
확인하러 나가고, 그 왕복이 측정상 로드 시간의 98%를 차지했다 (네트워크 허용
20~97초 vs local_files_only 0.4초). 랭킹 단계 예산이 25초라 이 지연만으로
타임아웃돼 무랭킹 결과가 반환됐다.

검증:
- 로컬 캐시를 먼저 시도한다 (local_files_only=True)
- 캐시 미스면 네트워크로 한 번만 재시도한다 (self-healing)
- 둘 다 실패하면 None을 반환해 상위가 graceful degradation 한다
- 동시 호출이 모델을 중복 로드하지 않는다 (락)

sentence-transformers 실물은 쓰지 않고 전부 모킹한다.
"""

from __future__ import annotations

import sys
import threading
from types import ModuleType
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from app.QueryAgent.relevance_filter import LocalRelevanceScorer


@pytest.fixture(autouse=True)
def _reset_singleton():
    """싱글턴은 클래스 속성이라 테스트 간 누수를 막는다."""
    LocalRelevanceScorer._model = None
    yield
    LocalRelevanceScorer._model = None


def _install_fake_sentence_transformers(monkeypatch, cross_encoder) -> None:
    """`from sentence_transformers import CrossEncoder`가 가짜를 집도록 한다."""
    module = ModuleType("sentence_transformers")
    module.CrossEncoder = cross_encoder  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)


def test_prefers_local_cache_first(monkeypatch) -> None:
    """정상 경로는 local_files_only=True 한 번으로 끝나야 한다."""
    calls: List[Dict[str, Any]] = []

    def fake_cross_encoder(model_name, **kwargs):
        calls.append(kwargs)
        return MagicMock(name="model")

    _install_fake_sentence_transformers(monkeypatch, fake_cross_encoder)

    model = LocalRelevanceScorer.get_model()

    assert model is not None
    assert len(calls) == 1, "로컬 캐시 히트인데 네트워크 재시도가 일어났다"
    assert calls[0]["local_files_only"] is True
    assert calls[0]["max_length"] == 512


def test_falls_back_to_network_when_cache_misses(monkeypatch) -> None:
    """캐시가 없으면 네트워크로 한 번 재시도해 자가 치유해야 한다.

    이 폴백이 없으면 가중치가 없는 새 머신에서 cross-encoder가 조용히
    비활성화되고 랭킹 품질이 떨어진다.
    """
    calls: List[Dict[str, Any]] = []

    def fake_cross_encoder(model_name, **kwargs):
        calls.append(kwargs)
        if kwargs.get("local_files_only"):
            raise OSError("not found in local cache")
        return MagicMock(name="downloaded-model")

    _install_fake_sentence_transformers(monkeypatch, fake_cross_encoder)

    model = LocalRelevanceScorer.get_model()

    assert model is not None
    assert [c["local_files_only"] for c in calls] == [True, False]


def test_returns_none_when_both_attempts_fail(monkeypatch) -> None:
    """네트워크까지 실패하면 예외를 던지지 말고 None으로 degrade 한다."""

    def fake_cross_encoder(model_name, **kwargs):
        raise OSError("offline and no cache")

    _install_fake_sentence_transformers(monkeypatch, fake_cross_encoder)

    assert LocalRelevanceScorer.get_model() is None


def test_missing_sentence_transformers_returns_none(monkeypatch) -> None:
    """라이브러리 미설치는 기존과 동일하게 None."""
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    assert LocalRelevanceScorer.get_model() is None


def test_concurrent_calls_load_model_once(monkeypatch) -> None:
    """동시 요청이 각자 로드하면 20~97초 네트워크 호출이 N개 뜬다.

    락이 없으면 이 테스트가 load_count > 1로 실패한다.
    """
    load_count = 0
    entered = threading.Event()

    def fake_cross_encoder(model_name, **kwargs):
        nonlocal load_count
        load_count += 1
        # 첫 로드가 느린 상황을 재현해 다른 스레드가 확실히 겹치게 한다.
        entered.set()
        threading.Event().wait(0.05)
        return MagicMock(name="model")

    _install_fake_sentence_transformers(monkeypatch, fake_cross_encoder)

    results: List[Any] = []

    def worker() -> None:
        results.append(LocalRelevanceScorer.get_model())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert load_count == 1, f"모델이 {load_count}번 로드됐다 (락 미동작)"
    assert all(r is not None for r in results)
    assert len({id(r) for r in results}) == 1, "스레드마다 다른 인스턴스를 받았다"
