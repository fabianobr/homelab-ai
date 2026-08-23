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


@pytest.mark.parametrize(
    "exc,expected",
    [
        (httpx.ConnectError("x"), True),
        (httpx.ReadTimeout("x"), True),
        (httpx.ReadError("x"), True),
        (httpx.WriteError("x"), True),
        (httpx.RemoteProtocolError("x"), True),
        (httpx.TooManyRedirects("x"), True),
        (httpx.DecodingError("x"), True),
        (ValueError("not a transport failure"), False),
    ],
)
def test_is_retryable_covers_the_whole_httpx_request_error_family(exc, expected):
    """IMPORTANT 8: the retry loop used to know only about TimeoutException
    and ConnectError."""
    assert fetcher._is_retryable(0, exc) is expected


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
async def test_short_feed_body_is_not_flagged_as_blocked():
    """A legitimately small RSS feed (few recent items) is not an anti-bot
    challenge page. Flagging it fed the breaker (24h pause -> probation ->
    permanently blocked) and blacklisted valid feeds for being short.
    """
    _allow_robots(respx)
    tiny_feed = (
        "<?xml version='1.0'?><rss version='2.0'><channel>"
        "<item><title>One item</title><link>https://example.com/a</link></item>"
        "</channel></rss>"
    )
    assert len(tiny_feed) < 500
    respx.get("https://example.com/feed.xml").mock(
        return_value=httpx.Response(200, text=tiny_feed)
    )

    result = await fetcher.fetch("https://example.com/feed.xml", kind="feed")

    assert result.status == 200
    assert result.blocked is False
    assert result.body == tiny_feed


@respx.mock
async def test_short_feed_body_with_challenge_marker_is_still_blocked():
    """The marker-phrase check still applies to feeds — only the length-based
    short-circuit is page-only."""
    _allow_robots(respx)
    respx.get("https://example.com/feed.xml").mock(
        return_value=httpx.Response(200, text="Just a moment... checking your browser")
    )

    result = await fetcher.fetch("https://example.com/feed.xml", kind="feed")

    assert result.blocked is True
    assert result.body is None


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


@respx.mock
async def test_crawl_delay_from_robots_overrides_domain_min_interval():
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nCrawl-delay: 2\nAllow: /\n")
    )
    respx.get("https://example.com/page").mock(
        return_value=httpx.Response(200, text="fine content that is long enough " + "x" * 500)
    )

    result = await fetcher.fetch("https://example.com/page")

    assert result.status == 200
    assert fetcher._limiter._domain_min_interval["example.com"] == 2.0


@respx.mock
async def test_connect_error_is_retried_then_records_breaker_failure(db_pool):
    _allow_robots(respx)
    async with db_pool.connection() as conn:
        row = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/page', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await row.fetchone())[0]

    route = respx.get("https://example.com/page").mock(side_effect=httpx.ConnectError("boom"))

    result = await fetcher.fetch("https://example.com/page", source_id=source_id, timeout=5.0)

    assert result.status == 0
    assert result.body is None
    assert "boom" in result.reason
    assert route.call_count == 3

    async with db_pool.connection() as conn:
        row = await conn.execute(
            "SELECT consecutive_failures FROM sources WHERE id = %s", (source_id,)
        )
        assert (await row.fetchone())[0] == 1


@respx.mock
async def test_unreachable_robots_txt_fails_open_instead_of_propagating():
    """CRITICAL 2: robots.is_allowed() called fetch_fn with no exception
    handling, so a DNS failure / refused connection on robots.txt escaped
    fetch() entirely and aborted the whole weekly run.
    """
    respx.get("https://example.com/robots.txt").mock(
        side_effect=httpx.ConnectError("Name or service not known")
    )
    respx.get("https://example.com/feed.xml").mock(
        return_value=httpx.Response(200, text="<rss>fine content " + "x" * 500 + "</rss>")
    )

    result = await fetcher.fetch("https://example.com/feed.xml", kind="feed")

    assert isinstance(result, fetcher.FetchResult)
    assert result.status == 200
    assert result.blocked is False


@respx.mock
async def test_unreachable_robots_txt_on_timeout_also_fails_open():
    respx.get("https://example.com/robots.txt").mock(
        side_effect=httpx.ConnectTimeout("timed out")
    )
    respx.get("https://example.com/page").mock(
        return_value=httpx.Response(200, text="fine content " + "x" * 500)
    )

    result = await fetcher.fetch("https://example.com/page")

    assert result.status == 200


@respx.mock
async def test_read_error_is_retried_and_returns_graceful_result():
    """IMPORTANT 8: only TimeoutException/ConnectError used to be caught, so
    ReadError/WriteError/RemoteProtocolError/TooManyRedirects/DecodingError all
    escaped the single HTTP egress point uncaught."""
    _allow_robots(respx)
    route = respx.get("https://example.com/page").mock(side_effect=httpx.ReadError("reset"))

    result = await fetcher.fetch("https://example.com/page", timeout=5.0)

    assert result.status == 0
    assert result.body is None
    assert "reset" in result.reason
    assert route.call_count == 3


@respx.mock
@pytest.mark.parametrize(
    "exc",
    [
        httpx.RemoteProtocolError("bad chunk"),
        httpx.WriteError("broken pipe"),
        httpx.TooManyRedirects("loop"),
        httpx.DecodingError("bad gzip"),
    ],
    ids=["remote_protocol", "write", "too_many_redirects", "decoding"],
)
async def test_other_httpx_failures_do_not_propagate(exc):
    _allow_robots(respx)
    respx.get("https://example.com/page").mock(side_effect=exc)

    result = await fetcher.fetch("https://example.com/page", timeout=5.0)

    assert result.status == 0
    assert result.reason is not None


@respx.mock
async def test_blocked_source_short_circuits_without_any_request(db_pool):
    """IMPORTANT 4: breaker state was written but never read back here, so a
    terminally blocked source kept being fetched by probe/discovery_seed."""
    _allow_robots(respx)
    async with db_pool.connection() as conn:
        row = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed.xml', 'rss', 1, 'blocked') "
            "RETURNING id"
        )
        source_id = (await row.fetchone())[0]

    route = respx.get("https://example.com/feed.xml")

    result = await fetcher.fetch(
        "https://example.com/feed.xml", kind="feed", source_id=source_id
    )

    assert result.status == 0
    assert result.reason == "breaker"
    assert route.call_count == 0


@respx.mock
async def test_source_with_active_blocked_until_short_circuits(db_pool):
    _allow_robots(respx)
    async with db_pool.connection() as conn:
        row = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status, blocked_until) "
            "VALUES ('example.com', 'https://example.com/feed.xml', 'rss', 1, 'active', "
            "now() + interval '24 hours') RETURNING id"
        )
        source_id = (await row.fetchone())[0]

    route = respx.get("https://example.com/feed.xml")

    result = await fetcher.fetch(
        "https://example.com/feed.xml", kind="feed", source_id=source_id
    )

    assert result.reason == "breaker"
    assert route.call_count == 0


@respx.mock
async def test_source_with_expired_blocked_until_proceeds_normally(db_pool):
    _allow_robots(respx)
    async with db_pool.connection() as conn:
        row = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status, blocked_until) "
            "VALUES ('example.com', 'https://example.com/feed.xml', 'rss', 1, 'active', "
            "now() - interval '1 hour') RETURNING id"
        )
        source_id = (await row.fetchone())[0]

    route = respx.get("https://example.com/feed.xml").mock(
        return_value=httpx.Response(200, text="<rss>fine " + "x" * 500 + "</rss>")
    )

    result = await fetcher.fetch(
        "https://example.com/feed.xml", kind="feed", source_id=source_id
    )

    assert result.status == 200
    assert route.call_count == 1


@respx.mock
async def test_fetch_emits_fetch_result_event(capsys):
    """IMPORTANT 7 / SPEC.md §18: fetcher emitted no structlog events at all."""
    _allow_robots(respx)
    respx.get("https://example.com/page").mock(
        return_value=httpx.Response(200, text="fine content " + "x" * 500)
    )

    await fetcher.fetch("https://example.com/page")

    out = capsys.readouterr().out
    assert "fetch.result" in out
    for field in ("domain", "status", "ms", "not_modified", "blocked"):
        assert field in out


@respx.mock
async def test_successful_fetch_with_source_id_records_breaker_success_and_persists_headers(db_pool):
    _allow_robots(respx)
    async with db_pool.connection() as conn:
        row = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status, consecutive_failures) "
            "VALUES ('example.com', 'https://example.com/feed.xml', 'rss', 1, 'active', 2) "
            "RETURNING id"
        )
        source_id = (await row.fetchone())[0]

    respx.get("https://example.com/feed.xml").mock(
        return_value=httpx.Response(
            200,
            text="<rss>ok content long enough to not look blocked " + "x" * 500 + "</rss>",
            headers={"ETag": '"fresh-etag"'},
        )
    )

    result = await fetcher.fetch(
        "https://example.com/feed.xml", kind="feed", source_id=source_id
    )

    assert result.status == 200
    assert result.blocked is False

    async with db_pool.connection() as conn:
        row = await conn.execute(
            "SELECT consecutive_failures, etag FROM sources WHERE id = %s", (source_id,)
        )
        consecutive_failures, etag = await row.fetchone()
        assert consecutive_failures == 0
        assert etag == '"fresh-etag"'
