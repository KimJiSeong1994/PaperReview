"""Safe provider-access diagnostics; never publish URLs, bodies or credentials."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math

import requests


class ProviderAccessError(requests.HTTPError):
    def __init__(self, provider, reason, *, http_status=None, retry_after=None):
        self.provider = provider
        self.reason = reason
        self.http_status = http_status
        self.retry_after = retry_after
        super().__init__(f"{provider}: {reason}")


def retry_after_seconds(value, default=60.0):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            seconds = default
    return max(0.0, seconds) if math.isfinite(seconds) else default


def access_details(error):
    if isinstance(error, ProviderAccessError):
        details = {"reason": error.reason}
        if error.http_status is not None:
            details["http_status"] = error.http_status
        if error.retry_after is not None:
            details["retry_after_seconds"] = max(0, math.ceil(error.retry_after))
        return details
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if status not in (401, 403, 429):
        return {}
    delay = retry_after_seconds(response.headers.get("Retry-After"), 60 if status == 429 else 300)
    return {"reason": "rate_limited" if status == 429 else "access_denied",
            "http_status": status, "retry_after_seconds": math.ceil(delay)}
