"""로컬 cross-encoder 관련성 스코어러.

이 모듈에는 LLM 기반 ``RelevanceFilter`` 도 있었다. 랭킹 뒤에서 상위 후보를
cross-encoder 점수만으로 재정렬하면서 임계값 미달 논문을 뒤에 도로 붙여
아무것도 거르지 않았고, 랭커가 이미 매긴 점수를 한 번 더 추론했다. 그 단계를
파이프라인에서 걷어낸 뒤로 프로덕션 호출자가 없어 삭제했다. 지금 남은 것은
``HybridRanker`` 가 RRF 신호로 쓰는 스코어러뿐이다.

파일명은 그대로 둔다 — 임포트 경로를 바꾸면 이 삭제와 무관한 차이가 섞인다.
"""
import logging
import os
import threading
from typing import Any, Dict, List

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()


class LocalRelevanceScorer:
    """로컬 cross-encoder 모델 기반 관련성 스코어러.

    sentence-transformers의 CrossEncoder를 사용하여
    LLM API 호출 없이 빠르게 관련성을 평가한다.
    """

    _instance = None
    _model = None
    # 로드는 20~97초가 걸릴 수 있어(아래 참조) 동시 요청이 각자 로드하지 않도록 직렬화한다.
    _model_lock = threading.Lock()

    def __init__(self) -> None:
        pass

    @classmethod
    def get_model(cls):
        """Lazy initialization of cross-encoder model (singleton).

        가중치가 이미 로컬에 있어도 기본 로드는 Hugging Face Hub에 메타데이터를
        확인하러 나가며, 그 왕복이 측정상 로드 시간의 98%를 차지한다
        (네트워크 허용 20~97초 vs ``local_files_only`` 0.4초). 랭킹 단계 예산이
        25초라 이 지연만으로 타임아웃돼 무랭킹 결과가 반환됐다.

        그래서 로컬 캐시를 먼저 시도하고, 캐시가 없을 때만 네트워크로 내려받는다.
        내려받은 뒤에는 다음 로드부터 빠른 경로를 탄다.
        """
        if cls._model is not None:
            return cls._model

        with cls._model_lock:
            # 락을 기다리는 동안 다른 스레드가 이미 로드했을 수 있다.
            if cls._model is not None:
                return cls._model

            try:
                from sentence_transformers import CrossEncoder  # type: ignore
            except ImportError:
                logger.warning(
                    "[LocalScorer] sentence-transformers not installed, local scoring unavailable"
                )
                return None

            # local_files_only=True 우선. 캐시 미스면 False로 한 번만 재시도한다.
            for local_only in (True, False):
                try:
                    cls._model = CrossEncoder(
                        "cross-encoder/ms-marco-MiniLM-L-6-v2",  # 22MB, fast
                        max_length=512,
                        local_files_only=local_only,
                    )
                    logger.info(
                        "[LocalScorer] Cross-encoder model loaded successfully (local_files_only=%s)",
                        local_only,
                    )
                    return cls._model
                except Exception as e:
                    if local_only:
                        logger.info(
                            "[LocalScorer] Cross-encoder not in local cache, downloading once: %s",
                            e,
                        )
                        continue
                    logger.warning("[LocalScorer] Failed to load cross-encoder: %s", e)
                    return None

        return cls._model

    @classmethod
    def is_available(cls) -> bool:
        """Check if local scoring is available."""
        try:
            from sentence_transformers import CrossEncoder  # noqa: F401  # type: ignore
            return True
        except ImportError:
            return False

    @classmethod
    def score_papers(cls, query: str, papers: List[Dict[str, Any]]) -> List[float]:
        """Score papers using local cross-encoder.

        Args:
            query: Search query
            papers: List of paper dicts with 'title' and optional 'abstract'

        Returns:
            List of relevance scores (0.0-1.0)
        """
        model = cls.get_model()
        if model is None:
            return []

        pairs = []
        for paper in papers:
            title = paper.get("title", "")
            abstract = (paper.get("abstract", "") or "")[:500]
            doc_text = f"{title}. {abstract}" if abstract else title
            pairs.append((query, doc_text))

        if not pairs:
            return []

        try:
            import numpy as np
            # batch_size=32: CPU 추론 시 기본값(1)보다 3-5배 빠름
            raw_scores = model.predict(pairs, batch_size=32, show_progress_bar=False)
            # Sigmoid normalization to 0-1 range
            scores = 1 / (1 + np.exp(-raw_scores))
            return scores.tolist()
        except Exception as e:
            logger.warning("[LocalScorer] Scoring failed: %s", e)
            return []


# Pre-load cross-encoder model at import time if env var set
if os.getenv("PRELOAD_CROSS_ENCODER", "").lower() in ("1", "true", "yes"):
    LocalRelevanceScorer.get_model()
