import io
import urllib.error

import pytest

from poster2json import http_retry
from poster2json.http_retry import RequestFailed, get_json


@pytest.fixture
def fake_net(monkeypatch):
    """urlopen answers from a queue (exception to raise, or JSON bytes); sleeps are recorded."""
    queue, calls, sleeps = [], [], []

    def fake_urlopen(target, timeout=None):
        calls.append(target)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return io.BytesIO(item)

    monkeypatch.setattr(http_retry.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_retry.time, "sleep", sleeps.append)
    http_retry.start_poster()
    return queue, calls, sleeps


def _http_error(code):
    return urllib.error.HTTPError("https://example.org", code, "err", {}, None)


def test_retries_with_growing_waits_but_not_bad_requests(fake_net):
    queue, calls, sleeps = fake_net
    queue += [_http_error(503), TimeoutError("slow"), b'{"ok": true}']
    assert get_json("https://example.org", 10) == {"ok": True}
    assert sleeps == [1.0, 2.0]

    queue.append(_http_error(400))
    with pytest.raises(RequestFailed) as exc:
        get_json("https://example.org", 10)
    assert exc.value.bad_request
    assert len(calls) == 4  # the 400 was sent once


def test_retry_budget_is_shared_per_poster(fake_net, monkeypatch):
    queue, calls, sleeps = fake_net
    monkeypatch.setattr(http_retry, "POSTER_RETRY_BUDGET", 1.5)
    http_retry.start_poster()
    queue += [_http_error(503)] * 2
    with pytest.raises(RequestFailed):
        get_json("https://example.org", 10)
    assert sleeps == [1.0]  # the 2s wait would go over the budget

    http_retry.start_poster()  # next poster: full budget again
    queue += [_http_error(503), b"{}"]
    assert get_json("https://example.org", 10) == {}
