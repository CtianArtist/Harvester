"""Read the text of Kaggle discussion threads in a headless browser (Playwright).

The official API lists a dataset's threads (titles, links, dates, comment
counts) but not what they say, and Kaggle draws its pages with JavaScript, so a
plain HTTP request only gets an empty shell. A real browser runs that
JavaScript for us. We stay polite: few tabs at once, a pause before every page
load, no images or fonts, and robots.txt is respected.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.robotparser import RobotFileParser

from playwright.async_api import BrowserContext, Page, Route, async_playwright

from harvester.config import ScrapeSettings
from harvester.enrichment.hints import find_edge_case_hints
from harvester.enrichment.robots import fetch_robots
from harvester.models import Candidate, Thread
from harvester.sources.kaggle.source import KAGGLE_WEB
from harvester.utils import first_line, tidy

log = logging.getLogger("harvester")
SELECTOR_MISSED = "thread text selector not found; saved the whole page instead"
ICON_LABEL = re.compile(
    r"^(arrow_drop_(up|down)|more_vert|more_horiz|expand_(more|less)|keyboard_arrow_(up|down)"
    r"|push_pin|reply)\d*$"
)


async def collect_discussions(cands: list[Candidate], cfg: ScrapeSettings) -> None:
    """Fill in the text of every thread in each candidate's `discussions`, then find hints."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not cfg.show_browser)
        try:
            context = await browser.new_context()
            await context.route("**/*", skip_images_and_fonts)

            rules = await fetch_robots(context, KAGGLE_WEB, cfg.page_timeout_ms)
            if rules is None:
                for c in cands:
                    c.notes.append("thread text not read: no clear answer from robots.txt")
            else:
                tabs = asyncio.Semaphore(cfg.pages_at_once)  # limits how many pages load at once
                await asyncio.gather(*(read_threads(context, tabs, rules, c, cfg) for c in cands))
        finally:
            await browser.close()

    if any(SELECTOR_MISSED in c.notes for c in cands):
        log.warning(
            "  Some threads didn't have the expected layout, so the whole page was saved.\n"
            "  Kaggle may have changed its pages: see scrape.thread_text_selector."
        )


async def skip_images_and_fonts(route: Route) -> None:
    """We only want text, so don't download pictures, video or fonts. Pages load faster."""
    if route.request.resource_type in {"image", "media", "font"}:
        await route.abort()
    else:
        await route.continue_()


async def read_threads(
    context: BrowserContext,
    tabs: asyncio.Semaphore,
    rules: RobotFileParser,
    cand: Candidate,
    cfg: ScrapeSettings,
) -> None:
    async with tabs:  # wait here until a tab is free
        page = await context.new_page()
        try:
            for thread in cand.discussions:
                if not rules.can_fetch("*", thread.url):
                    cand.notes.append(f"skipped {thread.url}: robots.txt asks bots not to visit")
                    continue
                await asyncio.sleep(cfg.seconds_between_pages)
                if not await read_thread(page, thread, cfg) and SELECTOR_MISSED not in cand.notes:
                    cand.notes.append(SELECTOR_MISSED)
        except Exception as e:
            cand.notes.append(f"stopped reading threads early: {first_line(e)}")
        finally:
            await page.close()

    cand.edge_case_hints = find_edge_case_hints(cand.discussions)
    read = sum(1 for t in cand.discussions if t.text)
    log.info("  %s: read %d of %d thread(s)", cand.ref, read, cand.discussion_count or 0)


async def read_thread(page: Page, thread: Thread, cfg: ScrapeSettings) -> bool:
    """Open one thread and fill in its text. Returns False if the layout wasn't as expected."""
    await page.goto(thread.url, wait_until="domcontentloaded", timeout=cfg.page_timeout_ms)
    await wait_for_text_to_settle(page, cfg.thread_text_selector, max_ms=cfg.wait_for_content_ms)

    area = page.locator(cfg.thread_text_selector)
    found = await area.count() > 0
    area = area.first if found else page.locator("body")
    thread.text = strip_icon_labels(tidy(await area.inner_text()))[: cfg.max_chars_per_thread]
    return found


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
