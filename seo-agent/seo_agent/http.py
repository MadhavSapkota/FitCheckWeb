from __future__ import annotations

import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


class TransientError(Exception):
    pass


def _retryable(e: BaseException) -> bool:
    return isinstance(e, (TransientError, requests.ConnectionError, requests.Timeout))


# Errors that never succeed on retry: bad credentials, missing permission, invalid request, spending cap.
PERMANENT_NAMES = {"AuthenticationError", "PermissionDeniedError", "BadRequestError", "NotFoundError",
                   "Unauthenticated", "PermissionDenied", "Forbidden", "InvalidArgument", "BudgetExceeded",
                   "RefreshError", "NoProvider"}
TRANSIENT_NAMES = {"RateLimitError", "InternalServerError", "APIConnectionError", "APITimeoutError", "OverloadedError",
                   "ServiceUnavailable", "ResourceExhausted", "DeadlineExceeded", "InternalServerError", "TooManyRequests",
                   "GatewayTimeout", "BadGateway", "ConnectionError", "Timeout", "TransientError", "TimeoutError"}
TRANSIENT_MARKERS = ("RESOURCE_EXHAUSTED", "RATE_EXCEEDED", "INTERNAL_ERROR", "TRANSIENT_ERROR", "DEADLINE_EXCEEDED",
                     "UNAVAILABLE", "HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "overloaded")


def is_transient(e: BaseException) -> bool:
    """True for rate limits, timeouts, and 5xx errors. Auth/permission/400 errors are permanent (never retried)."""
    names = {c.__name__ for c in type(e).__mro__}
    if names & PERMANENT_NAMES:
        return False
    status = getattr(e, "status_code", None) or getattr(getattr(e, "resp", None), "status", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    if names & TRANSIENT_NAMES or isinstance(e, (requests.ConnectionError, requests.Timeout)):
        return True
    msg = str(e)
    return any(m in msg for m in TRANSIENT_MARKERS)


def with_backoff(attempts: int = 3, min_wait: float = 2, max_wait: float = 30):
    """Bounded exponential backoff for transient errors only."""
    return retry(retry=retry_if_exception(is_transient), stop=stop_after_attempt(attempts),
                 wait=wait_exponential(min=min_wait, max=max_wait), reraise=True)


@retry(retry=retry_if_exception(_retryable), stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=30), reraise=True)
def post_json(url: str, payload, auth=None, timeout: int = 90) -> dict:
    r = requests.post(url, json=payload, auth=auth, timeout=timeout)
    if r.status_code in (429, 500, 502, 503, 504):
        raise TransientError(f"HTTP {r.status_code} from {url}")
    r.raise_for_status()
    return r.json()
