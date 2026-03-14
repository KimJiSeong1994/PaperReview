"""
Semantic Scholar API 공유 클라이언트.

세션 관리, 인증, 레이트 리밋, 지수 백오프 재시도 로직을 통합.
exploration_service, reference_collector, connected_papers_searcher
에서 각각 독립 구현되던 것을 단일 클라이언트로 통합.
"""

import logging
import os
import time
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MIN_REQUEST_INTERVAL = 0.3


class SemanticScholarClient:
    """Semantic Scholar Graph API 공유 HTTP 클라이언트."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    def __init__(self) -> None:
        self._last_request_time: float = 0.0

        headers: Dict[str, str] = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Accept": "application/json",
        }

        s2_key = os.getenv("S2_API_KEY")
        if s2_key:
            headers["x-api-key"] = s2_key

        self.session = requests.Session()
        self.session.headers.update(headers)

    def _enforce_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.monotonic()

    def request_with_retry(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 20,
        max_retries: int = 3,
    ) -> requests.Response:
        """HTTP GET with exponential backoff for transient errors."""
        last_exc: Optional[Exception] = None

        for attempt in range(max_retries):
            self._enforce_rate_limit()
            try:
                resp = self.session.get(url, params=params, timeout=timeout)

                if resp.status_code in _RETRYABLE_STATUS:
                    wait = min(2 ** attempt * 2, 10)
                    logger.warning(
                        "Semantic Scholar %d for %s, retry in %ds (%d/%d)",
                        resp.status_code, url, wait, attempt + 1, max_retries,
                    )
                    time.sleep(wait)
                    last_exc = requests.exceptions.HTTPError(
                        f"status {resp.status_code}", response=resp
                    )
                    continue

                resp.raise_for_status()
                return resp

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                wait = min(2 ** attempt * 2, 10)
                logger.warning(
                    "Semantic Scholar network error for %s, retry in %ds (%d/%d): %s",
                    url, wait, attempt + 1, max_retries, e,
                )
                time.sleep(wait)
                last_exc = e
                continue

            except Exception as e:
                last_exc = e
                break

        raise last_exc or Exception(
            f"Max retries ({max_retries}) exceeded for Semantic Scholar API: {url}"
        )

    def close(self) -> None:
        self.session.close()

    def __del__(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    def __enter__(self) -> "SemanticScholarClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


_default_client: Optional[SemanticScholarClient] = None


def get_client() -> SemanticScholarClient:
    """프로세스 전역 공유 SemanticScholarClient 인스턴스 반환."""
    global _default_client
    if _default_client is None:
        _default_client = SemanticScholarClient()
    return _default_client
