"""tests/test_robots.py"""
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from carwatch.robots import clear_robots_cache, is_allowed


class FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_robots_cache()
    yield
    clear_robots_cache()


async def test_allowed_when_no_disallow_matches():
    fetch_fn = AsyncMock(return_value=FakeResponse(200, "User-agent: *\nDisallow: /admin\n"))
    allowed, delay = await is_allowed(
        "https://example.com/news/article", "CarWatchBot/1.0", fetch_fn=fetch_fn
    )
    assert allowed is True
    assert delay is None


async def test_disallowed_path_is_blocked():
    fetch_fn = AsyncMock(return_value=FakeResponse(200, "User-agent: *\nDisallow: /admin\n"))
    allowed, _ = await is_allowed(
        "https://example.com/admin/secret", "CarWatchBot/1.0", fetch_fn=fetch_fn
    )
    assert allowed is False


async def test_crawl_delay_is_parsed():
    fetch_fn = AsyncMock(
        return_value=FakeResponse(200, "User-agent: *\nCrawl-delay: 10\n")
    )
    _, delay = await is_allowed(
        "https://example.com/news", "CarWatchBot/1.0", fetch_fn=fetch_fn
    )
    assert delay == 10.0


async def test_missing_robots_txt_allows_everything():
    fetch_fn = AsyncMock(return_value=FakeResponse(404, ""))
    allowed, _ = await is_allowed(
        "https://example.com/news", "CarWatchBot/1.0", fetch_fn=fetch_fn
    )
    assert allowed is True


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("Name or service not known"),
        httpx.ConnectTimeout("timed out"),
        httpx.ReadError("connection reset"),
        httpx.TooManyRedirects("redirect loop"),
        RuntimeError("some other transport's failure"),
    ],
    ids=["dns", "timeout", "read", "redirects", "non_httpx"],
)
async def test_unreachable_robots_txt_fails_open(exc):
    """CRITICAL 2: an httpx exception from fetch_fn used to propagate all the
    way out of fetcher.fetch() and abort the caller's whole batch."""
    fetch_fn = AsyncMock(side_effect=exc)
    allowed, delay = await is_allowed(
        "https://example.com/news", "CarWatchBot/1.0", fetch_fn=fetch_fn
    )
    assert allowed is True
    assert delay is None


async def test_failed_robots_fetch_is_cached_so_it_is_not_retried_every_url():
    fetch_fn = AsyncMock(side_effect=httpx.ConnectError("down"))
    await is_allowed("https://example.com/a", "CarWatchBot/1.0", fetch_fn=fetch_fn)
    await is_allowed("https://example.com/b", "CarWatchBot/1.0", fetch_fn=fetch_fn)
    assert fetch_fn.call_count == 1


async def test_robots_txt_is_cached_for_24h():
    fetch_fn = AsyncMock(return_value=FakeResponse(200, "User-agent: *\nDisallow: /admin\n"))
    await is_allowed("https://example.com/news", "CarWatchBot/1.0", fetch_fn=fetch_fn)
    await is_allowed("https://example.com/other", "CarWatchBot/1.0", fetch_fn=fetch_fn)
    assert fetch_fn.call_count == 1


async def test_robots_txt_cache_expires_after_ttl(monkeypatch):
    fetch_fn = AsyncMock(return_value=FakeResponse(200, "User-agent: *\nDisallow: /admin\n"))
    real_time = time.time
    fake_now = {"t": real_time()}
    monkeypatch.setattr("carwatch.robots.time.time", lambda: fake_now["t"])

    await is_allowed("https://example.com/news", "CarWatchBot/1.0", fetch_fn=fetch_fn)
    fake_now["t"] += 24 * 3600 + 1
    await is_allowed("https://example.com/news", "CarWatchBot/1.0", fetch_fn=fetch_fn)

    assert fetch_fn.call_count == 2
