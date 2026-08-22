"""src/carwatch/robots.py"""
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

_CACHE_TTL_SECONDS = 24 * 3600
_cache: dict[str, tuple[float, RobotFileParser, float | None]] = {}


def clear_robots_cache() -> None:
    _cache.clear()


async def is_allowed(url: str, user_agent: str, *, fetch_fn) -> tuple[bool, float | None]:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    robots_url = f"{origin}/robots.txt"

    cached = _cache.get(origin)
    if cached is not None and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        _, parser, crawl_delay = cached
        return parser.can_fetch(user_agent, url), crawl_delay

    parser = RobotFileParser()
    response = await fetch_fn(robots_url)
    if response is None or response.status_code >= 400:
        parser.parse([])
        crawl_delay = None
    else:
        parser.parse(response.text.splitlines())
        crawl_delay = parser.crawl_delay(user_agent)
        if crawl_delay is not None:
            crawl_delay = float(crawl_delay)

    _cache[origin] = (time.time(), parser, crawl_delay)
    return parser.can_fetch(user_agent, url), crawl_delay
