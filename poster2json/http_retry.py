"""Retrying GET for the ORCID, ROR and funder lookups.

Timeouts, connection errors, 408, 429 and 5xx are retried with growing waits
(1s, 2s). Other errors, such as a 400, fail at once: the same request would
fail again. All lookups for one poster share POSTER_RETRY_BUDGET seconds of
retrying; call start_poster() at the start of each poster.
"""

import http.client
import json
import time
import urllib.error
import urllib.request

ATTEMPTS = 3
POSTER_RETRY_BUDGET = 30.0
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

_budget = POSTER_RETRY_BUDGET


class RequestFailed(Exception):
    """The request failed, so the answer is unknown (not "no match").

    ``bad_request`` is True when the request itself was rejected (a 4xx), which
    says nothing about whether the service is up.
    """

    def __init__(self, err: Exception, bad_request: bool = False):
        super().__init__(err)
        self.bad_request = bad_request


def start_poster() -> None:
    global _budget
    _budget = POSTER_RETRY_BUDGET


def get_json(target, timeout: float) -> dict:
    """GET *target* (a URL or Request) and parse the JSON body."""
    global _budget
    for attempt in range(ATTEMPTS):
        started = time.monotonic()
        try:
            with urllib.request.urlopen(target, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code not in RETRYABLE_STATUS:
                raise RequestFailed(e, bad_request=400 <= e.code < 500) from e
            err = e
        except (OSError, http.client.HTTPException, ValueError) as e:
            err = e  # timeouts, dropped connections, truncated bodies
        finally:
            if attempt:
                _budget -= time.monotonic() - started
        wait = 2.0 ** attempt
        if attempt == ATTEMPTS - 1 or wait > _budget:
            raise RequestFailed(err) from err
        _budget -= wait
        time.sleep(wait)
    raise AssertionError("unreachable")
