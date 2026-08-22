"""tests/test_robots.py"""
import time
from unittest.mock import AsyncMock

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
