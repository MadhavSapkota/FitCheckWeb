from __future__ import annotations

import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


class TransientError(Exception):
    pass


def _retryable(e: BaseException) -> bool:
    return isinstance(e, (TransientError, requests.ConnectionError, requests.Timeout))


@retry(retry=retry_if_exception(_retryable), stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=30), reraise=True)
def post_json(url: str, payload, auth=None, timeout: int = 90) -> dict:
    r = requests.post(url, json=payload, auth=auth, timeout=timeout)
    if r.status_code in (429, 500, 502, 503, 504):
        raise TransientError(f"HTTP {r.status_code} from {url}")
    r.raise_for_status()
    return r.json()
