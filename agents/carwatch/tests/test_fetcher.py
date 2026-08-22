"""tests/test_fetcher.py"""
import httpx
import pytest
import respx

from carwatch import fetcher
from carwatch.robots import clear_robots_cache


@pytest.fixture(autouse=True)
def _reset():
    clear_robots_cache()
    yield
    clear_robots_cache()


@pytest.fixture(autouse=True)
async def _close_client_after():
    yield
    await fetcher.close_client()


def _allow_robots(mock_router, host="example.com"):
    mock_router.get(f"https://{host}/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )


@respx.mock
async def test_fresh_fetch_returns_body_and_caches_headers():
    _allow_robots(respx)
    respx.get("https://example.com/feed.xml").mock(
        return_value=httpx.Response(
            200,
            text="<rss>ok content long enough to not look blocked " + "x" * 500 + "</rss>",
            headers={"ETag": '"abc123"', "Last-Modified": "Wed, 01 Jan 2026 00:00:00 GMT"},
        )
    )

    result = await fetcher.fetch("https://example.com/feed.xml", kind="feed")

    assert result.status == 200
    assert result.not_modified is False
    assert result.blocked is False
    assert result.etag == '"abc123"'
    assert "ok content" in result.body


@respx.mock
async def test_conditional_get_returns_not_modified_on_304(db_pool):
    _allow_robots(respx)
    async with db_pool.connection() as conn:
        row = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status, etag, last_modified) "
            "VALUES ('example.com', 'https://example.com/feed.xml', 'rss', 1, 'active', "
            "'\"abc123\"', 'Wed, 01 Jan 2026 00:00:00 GMT') RETURNING id"
        )
        source_id = (await row.fetchone())[0]

    route = respx.get("https://example.com/feed.xml").mock(return_value=httpx.Response(304))

    result = await fetcher.fetch(
        "https://example.com/feed.xml", kind="feed", source_id=source_id
    )

    assert result.status == 304
    assert result.not_modified is True
    assert result.body is None
    sent_headers = route.calls.last.request.headers
    assert sent_headers["If-None-Match"] == '"abc123"'


@respx.mock
async def test_short_body_is_flagged_as_blocked():
    _allow_robots(respx)
    respx.get("https://example.com/page").mock(return_value=httpx.Response(200, text="short"))

    result = await fetcher.fetch("https://example.com/page")

    assert result.status == 200
    assert result.blocked is True


@respx.mock
async def test_challenge_phrase_is_flagged_as_blocked():
    _allow_robots(respx)
    body = "Just a moment..." + "x" * 600
    respx.get("https://example.com/page").mock(return_value=httpx.Response(200, text=body))

    result = await fetcher.fetch("https://example.com/page")

    assert result.blocked is True


@respx.mock
async def test_403_is_never_retried():
    _allow_robots(respx)
    route = respx.get("https://example.com/page").mock(return_value=httpx.Response(403))

    result = await fetcher.fetch("https://example.com/page")

    assert result.status == 403
    assert route.call_count == 1


@respx.mock
async def test_503_is_retried_up_to_3_times_then_gives_up():
    _allow_robots(respx)
    route = respx.get("https://example.com/page").mock(return_value=httpx.Response(503))

    result = await fetcher.fetch("https://example.com/page", timeout=5.0)

    assert result.status == 503
    assert route.call_count == 3


@respx.mock
async def test_429_honors_retry_after_header():
    _allow_robots(respx)
    route = respx.get("https://example.com/page")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, text="fine content that is long enough " + "x" * 500),
    ]

    result = await fetcher.fetch("https://example.com/page")

    assert result.status == 200
    assert route.call_count == 2


@respx.mock
async def test_non_numeric_retry_after_falls_back_to_backoff_without_crashing():
    _allow_robots(respx)
    route = respx.get("https://example.com/page")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        httpx.Response(200, text="fine content that is long enough " + "x" * 500),
    ]

    result = await fetcher.fetch("https://example.com/page")

    assert result.status == 200
    assert route.call_count == 2


@respx.mock
async def test_robots_disallow_short_circuits_without_fetching():
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
    )
    route = respx.get("https://example.com/private/page")

    result = await fetcher.fetch("https://example.com/private/page")

    assert result.status == 0
    assert result.reason == "robots"
    assert route.call_count == 0
