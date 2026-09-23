"""Read Kaggle discussion threads in a headless browser (Playwright).

The official API doesn't expose discussions, and Kaggle draws its pages with
JavaScript, so a plain HTTP request only gets an empty shell. A real browser
runs that JavaScript for us. We stay polite: few tabs at once, a pause before
every page load, no images or fonts, and robots.txt is respected.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.robotparser import RobotFileParser

from playwright.async_api import BrowserContext, Page, Route, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from harvester.config import ScrapeSettings
from harvester.enrichment.hints import find_edge_case_hints
from harvester.enrichment.robots import fetch_robots
from harvester.models import Candidate, Thread
from harvester.sources.kaggle.source import KAGGLE_WEB
from harvester.utils import first_line, tidy

log = logging.getLogger("harvester")
THREAD_URL = re.compile(r"/discussion/\d+$")  # a thread's URL ends in /discussion/<number>
NO_THREADS = "no discussion threads found"
ICON_LABEL = re.compile(
    r"^(arrow_drop_(up|down)|more_vert|more_horiz|expand_(more|less)|keyboard_arrow_(up|down)"
    r"|push_pin|reply)\d*$"
)


async def collect_discussions(cands: list[Candidate], cfg: ScrapeSettings) -> None:
    """Read each dataset's discussion threads, filling in `discussions` and `edge_case_hints`."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not cfg.show_browser)
        try:
            context = await browser.new_context()
            await context.route("**/*", skip_images_and_fonts)

            rules = await fetch_robots(context, KAGGLE_WEB, cfg.page_timeout_ms)
            if rules is None:
                for c in cands:
                    c.notes.append(
                        "discussions skipped: couldn't get a clear answer from robots.txt"
                    )
            else:
                tabs = asyncio.Semaphore(cfg.pages_at_once)  # limits how many pages load at once
                await asyncio.gather(
                    *(read_discussions(context, tabs, rules, c, cfg) for c in cands)
                )
        finally:
            await browser.close()

    visited = [c for c in cands if c.discussions or NO_THREADS in c.notes]
    if visited and not any(c.discussions for c in visited):
        log.warning(
            "  No threads found for any dataset. If that seems wrong, set scrape.show_browser\n"
            "  to true to watch what the browser sees. Kaggle may have changed its page layout."
        )


async def skip_images_and_fonts(route: Route) -> None:
    """We only want text, so don't download pictures, video or fonts. Pages load faster."""
    if route.request.resource_type in {"image", "media", "font"}:
        await route.abort()
    else:
        await route.continue_()


async def read_discussions(
    context: BrowserContext,
    tabs: asyncio.Semaphore,
    rules: RobotFileParser,
    cand: Candidate,
    cfg: ScrapeSettings,
) -> None:
    """Find a dataset's thread links, then read the first few threads."""
    list_url = f"{cand.url}/discussion"
    if not rules.can_fetch("*", list_url):
        cand.notes.append("discussions skipped: robots.txt asks bots not to visit them")
        log.info("  %s: skipped, robots.txt asks bots not to visit", cand.ref)
        return

    async with tabs:  # wait here until a tab is free
        page = await context.new_page()
        try:
            await asyncio.sleep(cfg.seconds_between_pages)
            thread_urls = await find_thread_links(page, list_url, cand.ref, cfg)
            if not thread_urls:
                cand.notes.append(NO_THREADS)
            for url in thread_urls[: cfg.threads_per_dataset]:
                if rules.can_fetch("*", url):
                    await asyncio.sleep(cfg.seconds_between_pages)
                    cand.discussions.append(await read_thread(page, url, cfg))
        except Exception as e:
            cand.notes.append(f"stopped reading discussions early: {first_line(e)}")
        finally:
            await page.close()

    cand.edge_case_hints = find_edge_case_hints(cand.discussions)
    log.info("  %s: read %d thread(s)", cand.ref, len(cand.discussions))


async def find_thread_links(page: Page, list_url: str, ref: str, cfg: ScrapeSettings) -> list[str]:
    """Open a dataset's Discussion tab and collect the links to its threads."""
    await page.goto(list_url, wait_until="domcontentloaded", timeout=cfg.page_timeout_ms)

    # Kaggle draws its pages with JavaScript after they load, so the links
    # aren't there at first. Wait for the first one to show up.
    links = page.locator(f'a[href*="/datasets/{ref}/discussion/"]')
    try:
        await links.first.wait_for(state="attached", timeout=cfg.wait_for_content_ms)
    except PlaywrightTimeoutError:
        return []  # nothing showed up: this dataset has no threads
    await wait_for_text_to_settle(page, "body", max_ms=5_000)  # let the rest of the list appear

    return normalize_thread_urls(await links.evaluate_all("els => els.map(e => e.href)"))


def normalize_thread_urls(hrefs: list[str]) -> list[str]:
    """Strip anchors and query strings, keep only real thread links, drop duplicates."""
    urls: list[str] = []
    for href in hrefs:
        href = href.split("#")[0].split("?")[0].rstrip("/")
        if THREAD_URL.search(href) and href not in urls:
            urls.append(href)
    return urls


async def read_thread(page: Page, url: str, cfg: ScrapeSettings) -> Thread:
    """Open one thread and return its title and text."""
    await page.goto(url, wait_until="domcontentloaded", timeout=cfg.page_timeout_ms)
    await wait_for_text_to_settle(page, cfg.thread_text_selector, max_ms=cfg.wait_for_content_ms)

    area = page.locator(cfg.thread_text_selector)
    area = area.first if await area.count() else page.locator("body")
    text = strip_icon_labels(tidy(await area.inner_text()))

    heading = page.locator(cfg.thread_title_selector)
    if await heading.count():
        title = (await heading.first.inner_text()).strip()
    else:
        title = (await page.title()).removesuffix(" | Kaggle").strip()
    return Thread(url=url, title=title, text=text[: cfg.max_chars_per_thread])


def strip_icon_labels(text: str) -> str:
    """Drop lines that are only icon names, like "more_vert" or "arrow_drop_up50".

    Kaggle draws icons with a font that turns words into pictures, so to a text
    reader each icon shows up as its name (plus a vote count next to it).
    """
    return "\n".join(line for line in text.splitlines() if not ICON_LABEL.match(line))


async def wait_for_text_to_settle(
    page: Page, selector: str, max_ms: int, step_ms: int = 500
) -> None:
    """Wait until the text on the page stops changing, meaning JavaScript is done drawing it."""
    last_length, calm_checks = -1, 0
    for _ in range(max_ms // step_ms):
        length = await page.evaluate(
            "sel => (document.querySelector(sel) || document.body).innerText.length", selector
        )
        calm_checks = calm_checks + 1 if (length == last_length and length > 0) else 0
        if calm_checks >= 3:  # unchanged for about 1.5 seconds
            return
        last_length = length
        await page.wait_for_timeout(step_ms)
