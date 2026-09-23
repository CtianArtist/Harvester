"""Read robots.txt, the file where a site lists the pages bots shouldn't visit."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.robotparser import RobotFileParser

from harvester.utils import first_line

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext

log = logging.getLogger("harvester")


def parse_robots(status: int, content_type: str, body: str) -> RobotFileParser | None:
    """Turn a robots.txt response into rules. None means "no clear answer, stay out"."""
    rules = RobotFileParser()
    if status in (404, 410):
        rules.parse([])  # no robots.txt means nothing is off-limits
        return rules
    if status != 200:
        log.warning("  robots.txt answered with HTTP %s", status)
        return None
    if "text/plain" not in content_type.lower():
        # Kaggle answers /robots.txt with its home page (HTML, status 200)
        # rather than a robots file. Parsing that HTML would "work" only by
        # accident, so treat it for what it is: no robots.txt.
        log.info("  robots.txt is not a robots file (%s); treating it as no rules", content_type)
        rules.parse([])
        return rules
    rules.parse(body.splitlines())
    return rules


async def fetch_robots(
    context: BrowserContext, base_url: str, timeout_ms: int
) -> RobotFileParser | None:
    try:
        resp = await context.request.get(f"{base_url}/robots.txt", timeout=timeout_ms)
        status, body = resp.status, await resp.text()
        content_type = resp.headers.get("content-type", "")
    except Exception as e:
        log.warning("  Couldn't fetch robots.txt: %s", first_line(e))
        return None
    return parse_robots(status, content_type, body)
