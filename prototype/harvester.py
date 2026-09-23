"""
The Karvester: a Kaggle dataset harvester for AI benchmarks.

Finds recent, niche STEM datasets on Kaggle that AI models are unlikely to have
seen during training, and saves them as "candidate" records that can later be
turned into test questions.

What it does, in order:
  1. Logs in to Kaggle with the official API.
  2. Searches each topic in SEARCH_TOPICS, newest datasets first.
  3. Quarantines anything dated before CUTOFF_DATE (older data is more likely
     to be in an AI model's training data).
  4. Downloads the files of the datasets it keeps, within size limits.
  5. Opens each kept dataset's discussion threads in a hidden browser
     (Playwright) and saves the text, plus sentences that mention edge cases.
  6. Writes everything to the harvest_output/ folder.

One-time setup (needs Python 3.11 or newer):
    pip install -r requirements.txt
    playwright install chromium

Run it:
    python harvester.py
    python harvester.py --cutoff 2026-03-01 --per-topic 3
    python harvester.py --no-download --no-scrape     # quick dates-only run
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import logging
import os
import re
import shutil
import sys
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib import robotparser

from playwright.async_api import Route, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

# =============================================================================
# SETTINGS: change these to suit you
# =============================================================================

# Your Kaggle API token. Create one at https://www.kaggle.com/settings/api
# ("Generate New Token") and paste it here. Safer: leave this placeholder alone
# and set the KAGGLE_API_TOKEN environment variable, or save the token in
# ~/.kaggle/access_token. An older ~/.kaggle/kaggle.json file also works.
# Never commit a real token to GitHub.
KAGGLE_API_TOKEN = "PASTE_YOUR_KAGGLE_API_TOKEN_HERE"

# Topics to search for.
SEARCH_TOPICS = ["linear algebra", "signal processing", "optimization", "reinforcement learning"]

# Anything dated before this is quarantined. Set it to at least the training
# cutoff of the newest AI model you plan to test, and move it forward as new
# models come out.
CUTOFF_DATE = "2026-06-01"

DATASETS_PER_TOPIC = 5        # search results to check per topic (max 20)
MAX_FILE_MB = 200             # skip any single file bigger than this (measured after unzipping)
MAX_DATASET_MB = 500          # skip datasets bigger than this, and stop downloading past it

THREADS_PER_DATASET = 3       # discussion threads to read per dataset
MAX_CHARS_PER_THREAD = 5000   # trim very long threads
PAGES_AT_ONCE = 2             # browser tabs loading at the same time (keep small to be polite)
SECONDS_BETWEEN_PAGES = 2.0   # pause before each page load, in each tab
PAGE_TIMEOUT_MS = 30_000      # give up on a page that takes longer than this to load
WAIT_FOR_CONTENT_MS = 15_000  # how long to wait for JavaScript to draw the content
SHOW_BROWSER = False          # True opens a visible browser window so you can watch it work

# Which part of a thread page to save. "main" is a guess at where Kaggle puts
# the content (the script falls back to the whole page if it isn't there).
# If you get lots of menu text, run `playwright codegen <a thread's URL>`,
# click the post, and copy the selector it shows you.
THREAD_TEXT_SELECTOR = "main"

OUTPUT_DIR = Path("harvest_output")
KAGGLE_WEB = "https://www.kaggle.com"

# =============================================================================

log = logging.getLogger("harvester")
MB = 1024 * 1024
THREAD_URL = re.compile(r"/discussion/\d+$")  # a thread's URL ends in /discussion/<number>

# A rough keyword filter for sentences that point out traps in the data.
EDGE_CASE_WORDS = re.compile(
    r"\b(edge cases?|corner cases?|careful|caveat|gotcha|bug|wrong|incorrect|missing|"
    r"NaNs?|outliers?|duplicates?|leak(age)?|mislabel(l)?ed|units?|overflow|unstable|"
    r"diverg\w*|doesn't work|does not work)\b",
    re.IGNORECASE,
)

LOGIN_HELP = (
    "\nCouldn't log in to Kaggle. Get an API token at https://www.kaggle.com/settings/api,\n"
    "then paste it into KAGGLE_API_TOKEN at the top of harvester.py\n"
    "(or set the KAGGLE_API_TOKEN environment variable).\n"
    "You can also run `kaggle auth login` once to log in through your browser."
)


@dataclass
class Candidate:
    """Everything we learned about one dataset. Saved as one line of JSON."""

    ref: str                          # "owner/dataset-name"
    title: str
    url: str
    found_by_search: str
    tags: list[str]
    listed_size_mb: float
    last_updated: str | None
    earliest_date_seen: str | None = None
    status: str = "pending"           # becomes "kept" or "quarantined"
    reason: str = ""
    files_downloaded: list[dict] = field(default_factory=list)
    files_skipped: list[dict] = field(default_factory=list)
    discussions: list[dict] = field(default_factory=list)
    edge_case_hints: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    possible_question: str = ""       # left blank on purpose: writing test questions is the next phase


# -----------------------------------------------------------------------------
# Step 1: log in
# -----------------------------------------------------------------------------

def connect_to_kaggle():
    """Log in with the official Kaggle API and return the API object."""
    if KAGGLE_API_TOKEN and not KAGGLE_API_TOKEN.startswith("PASTE_"):
        os.environ["KAGGLE_API_TOKEN"] = KAGGLE_API_TOKEN

    try:
        # The kaggle package prints a long help text (twice) when login fails,
        # so we hide its output and show our own shorter message instead.
        with contextlib.redirect_stdout(io.StringIO()):
            # Imported here rather than at the top: the kaggle package tries to
            # log in the moment it's imported, so the token has to be set first.
            from kaggle.api.kaggle_api_extended import KaggleApi

            api = KaggleApi()
            api.authenticate()  # looks for the env var, ~/.kaggle/access_token, or kaggle.json
    except SystemExit:          # the kaggle package quits when it can't find a valid login
        sys.exit(LOGIN_HELP)
    except Exception as e:      # e.g. no internet connection
        sys.exit(f"Couldn't reach Kaggle to log in: {first_line(e)}")
    return api


# -----------------------------------------------------------------------------
# Step 2: search
# -----------------------------------------------------------------------------

def search_kaggle(api, topics, per_topic):
    """Search each topic, newest first. Returns {ref: (topic, dataset)} with no duplicates."""
    found = {}
    for topic in topics:
        try:
            # "published" puts the newest datasets first. max_size makes Kaggle
            # leave out huge datasets before we ever try to download them.
            results = api.dataset_list(
                search=topic, sort_by="published", max_size=MAX_DATASET_MB * MB
            ) or []
        except Exception as e:
            log.warning("  Search for %r failed: %s", topic, first_line(e))
            continue
        new = 0
        for ds in results[:per_topic]:
            if ds is not None and ds.ref not in found:
                found[ds.ref] = (topic, ds)
                new += 1
        log.info("  %-24s %2d results, %d new", topic, len(results), new)
    return found


# -----------------------------------------------------------------------------
# Step 3: date check
# -----------------------------------------------------------------------------

def assess_dataset(api, topic, ds, cutoff, download):
    """Decide whether to keep a dataset, and download it if we do."""
    cand = Candidate(
        ref=ds.ref,
        title=ds.title or ds.ref,
        url=f"{KAGGLE_WEB}/datasets/{ds.ref}",
        found_by_search=topic,
        tags=[t.name for t in (ds.tags or []) if t is not None and t.name],
        listed_size_mb=mb(ds.total_bytes),
        last_updated=iso(ds.last_updated),
    )

    updated = as_utc(ds.last_updated)
    if updated is None:
        return quarantine(cand, "Kaggle gave no date, so its age can't be checked")
    if updated < cutoff:
        return quarantine(cand, f"last updated {updated:%Y-%m-%d}, before the cutoff")

    # "Updated recently" doesn't mean "new": an old dataset can get a fresh
    # upload. So we also look at when each file and version was created, and
    # judge the dataset by the OLDEST date we can find.
    try:
        files = list_files(api, ds.ref)
    except Exception as e:
        return quarantine(cand, f"couldn't list its files ({first_line(e)})")
    dates = [as_utc(f.creation_date) for f in files]
    dates += [as_utc(v.creation_date) for v in (ds.versions or []) if v is not None]
    earliest = min((d for d in dates if d), default=updated)
    cand.earliest_date_seen = iso(earliest)
    if earliest < cutoff:
        return quarantine(cand, f"updated recently, but parts of it date back to {earliest:%Y-%m-%d}")

    # Note: dates are a strong signal, not proof. Someone could upload years-old
    # data as a brand-new dataset, and no date check can catch that.
    cand.status, cand.reason = "kept", f"oldest date found is {earliest:%Y-%m-%d}"
    log_decision(cand)
    if download:
        download_files(api, cand, files)
    return cand


def list_files(api, ref):
    """Ask Kaggle for a dataset's files (name, size, creation date), page by page."""
    files, page_token = [], None
    for _ in range(20):  # safety cap: at most 20 pages of 200 files
        resp = api.dataset_list_files(ref, page_token=page_token, page_size=200)
        if resp is None:
            break
        if resp.error_message:
            raise RuntimeError(resp.error_message)
        files += [f for f in (resp.files or []) if f is not None]
        page_token = resp.next_page_token
        if not page_token:
            break
    return files


def quarantine(cand, reason):
    cand.status, cand.reason = "quarantined", reason
    log_decision(cand)
    return cand


def log_decision(cand):
    log.info("  %-11s %s: %s", cand.status.upper(), cand.ref, cand.reason)


# -----------------------------------------------------------------------------
# Step 4: download, with size checks before AND after
# -----------------------------------------------------------------------------

def download_files(api, cand, files):
    """Download a dataset's files one at a time, skipping anything over the limits."""
    dest = OUTPUT_DIR / "data" / cand.ref.replace("/", "__")
    incoming = dest / "_incoming"  # each file lands here first so it can be checked
    file_limit, total_limit = MAX_FILE_MB * MB, MAX_DATASET_MB * MB
    used = 0

    for f in files:
        name, listed = f.name, f.total_bytes or 0
        final = dest / name
        if not name or ".." in Path(name).parts:
            skip(cand, name, listed, "unsafe file name")
            continue

        # Check 1: the size Kaggle reports, before downloading anything.
        if listed > file_limit:
            skip(cand, name, listed, f"over the {MAX_FILE_MB} MB file limit")
            continue
        if used + listed > total_limit:
            skip(cand, name, listed, f"would take this dataset past {MAX_DATASET_MB} MB")
            continue
        if final.exists():  # already downloaded on an earlier run
            used += final.stat().st_size
            cand.files_downloaded.append({"file": final.as_posix(), "mb": mb(final.stat().st_size)})
            continue

        shutil.rmtree(incoming, ignore_errors=True)
        incoming.mkdir(parents=True)
        try:
            api.dataset_download_file(cand.ref, name, path=str(incoming), force=True, quiet=True)
        except Exception as e:
            skip(cand, name, listed, f"download failed: {first_line(e)}")
            continue

        # Check 2: the real size on disk, measured after unzipping.
        for got in [p for p in incoming.rglob("*") if p.is_file()]:
            saved, real = check_and_place(got, final, dest, file_limit, total_limit - used)
            if not saved:
                skip(cand, name, real, "too big once downloaded and unzipped")
                continue
            used += real
            for p in saved:
                cand.files_downloaded.append({"file": p.as_posix(), "mb": mb(p.stat().st_size)})

    shutil.rmtree(incoming, ignore_errors=True)
    log.info("      %d file(s) saved, %d skipped", len(cand.files_downloaded), len(cand.files_skipped))


def check_and_place(got, final, dest, file_limit, room_left):
    """Move a downloaded file into place if it fits the limits, unzipping zips.

    Kaggle sends large files as .zip archives. A small zip can unpack into
    something huge, so we read the unzipped sizes from the archive's index
    BEFORE extracting. This is what protects the next stage of the pipeline
    from running out of memory.
    Returns (list of saved paths, real size in bytes). The list is empty if it was too big.
    """
    if zipfile.is_zipfile(got):
        with zipfile.ZipFile(got) as z:
            members = [m for m in z.infolist() if not m.is_dir()]
            real = sum(m.file_size for m in members)  # size after unzipping
            if real > room_left or any(m.file_size > file_limit for m in members):
                return [], real
            return [Path(z.extract(m, dest)) for m in members], real

    real = got.stat().st_size
    if real > file_limit or real > room_left:
        return [], real
    final.parent.mkdir(parents=True, exist_ok=True)
    got.replace(final)
    return [final], real


def skip(cand, name, size, why):
    cand.files_skipped.append({"file": name, "mb": mb(size), "why": why})
    log.info("      skipped %s: %s", name, why)


# -----------------------------------------------------------------------------
# Step 5: read discussion threads with Playwright
# -----------------------------------------------------------------------------

async def collect_discussions(cands):
    """Read each kept dataset's discussion threads in a hidden browser."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not SHOW_BROWSER)
        context = await browser.new_context()
        await context.route("**/*", skip_images_and_fonts)

        rules = await read_robots_txt(context)
        if rules is None:
            for c in cands:
                c.notes.append("discussions skipped: couldn't get a clear answer from robots.txt")
        else:
            tabs = asyncio.Semaphore(PAGES_AT_ONCE)  # limits how many pages load at once
            await asyncio.gather(*(read_discussions(context, tabs, rules, c) for c in cands))
        await browser.close()

    visited = [c for c in cands if c.discussions or "no discussion threads found" in c.notes]
    if visited and not any(c.discussions for c in visited):
        log.warning(
            "  No threads found for any dataset. If that seems wrong, set SHOW_BROWSER = True\n"
            "  to watch what the browser sees. Kaggle may have changed its page layout."
        )


async def skip_images_and_fonts(route: Route):
    """We only want text, so don't download pictures, video or fonts. Pages load faster."""
    if route.request.resource_type in {"image", "media", "font"}:
        await route.abort()
    else:
        await route.continue_()


async def read_robots_txt(context):
    """Fetch robots.txt, the file where a site lists the pages bots shouldn't visit.

    Returns the rules, or None if we couldn't get a clear answer (then we stay out).
    """
    try:
        resp = await context.request.get(f"{KAGGLE_WEB}/robots.txt", timeout=PAGE_TIMEOUT_MS)
        status, body = resp.status, await resp.text()
    except Exception as e:
        log.warning("  Couldn't fetch robots.txt: %s", first_line(e))
        return None
    rules = robotparser.RobotFileParser()
    if status == 200:
        rules.parse(body.splitlines())
    elif status in (404, 410):
        rules.parse([])  # no robots.txt means nothing is off-limits
    else:
        log.warning("  robots.txt answered with HTTP %s", status)
        return None
    return rules


async def read_discussions(context, tabs, rules, cand):
    """Find a dataset's thread links, then read the first few threads."""
    list_url = f"{KAGGLE_WEB}/datasets/{cand.ref}/discussion"
    if not rules.can_fetch("*", list_url):
        cand.notes.append("discussions skipped: robots.txt asks bots not to visit them")
        log.info("  %s: skipped, robots.txt asks bots not to visit", cand.ref)
        return

    async with tabs:  # wait here until a tab is free
        page = await context.new_page()
        try:
            await asyncio.sleep(SECONDS_BETWEEN_PAGES)
            thread_urls = await find_thread_links(page, list_url, cand.ref)
            if not thread_urls:
                cand.notes.append("no discussion threads found")
            for url in thread_urls[:THREADS_PER_DATASET]:
                if rules.can_fetch("*", url):
                    await asyncio.sleep(SECONDS_BETWEEN_PAGES)
                    cand.discussions.append(await read_thread(page, url))
        except Exception as e:
            cand.notes.append(f"stopped reading discussions early: {first_line(e)}")
        finally:
            await page.close()

    cand.edge_case_hints = find_edge_case_hints(cand.discussions)
    log.info("  %s: read %d thread(s)", cand.ref, len(cand.discussions))


async def find_thread_links(page, list_url, ref):
    """Open a dataset's Discussion tab and collect the links to its threads."""
    await page.goto(list_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)

    # Kaggle draws its pages with JavaScript after they load, so the links
    # aren't there at first. Wait for the first one to show up.
    links = page.locator(f'a[href*="/datasets/{ref}/discussion/"]')
    try:
        await links.first.wait_for(state="attached", timeout=WAIT_FOR_CONTENT_MS)
    except PlaywrightTimeoutError:
        return []  # nothing showed up: this dataset has no threads
    await wait_for_text_to_settle(page, "body", max_ms=5_000)  # let the rest of the list appear

    urls = []
    for href in await links.evaluate_all("els => els.map(e => e.href)"):
        href = href.split("#")[0].split("?")[0].rstrip("/")
        if THREAD_URL.search(href) and href not in urls:
            urls.append(href)
    return urls


async def read_thread(page, url):
    """Open one thread and return its title and text."""
    await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    await wait_for_text_to_settle(page, THREAD_TEXT_SELECTOR)

    area = page.locator(THREAD_TEXT_SELECTOR)
    area = area.first if await area.count() else page.locator("body")
    text = tidy(await area.inner_text())
    title = (await page.title()).removesuffix(" | Kaggle").strip()
    return {"url": url, "title": title, "text": text[:MAX_CHARS_PER_THREAD]}


async def wait_for_text_to_settle(page, selector, max_ms=None, step_ms=500):
    """Wait until the text on the page stops changing, meaning JavaScript is done drawing it."""
    max_ms = max_ms or WAIT_FOR_CONTENT_MS
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


def find_edge_case_hints(threads, limit=8):
    """Pull out sentences that sound like warnings about the data (a rough keyword filter)."""
    hints = []
    for thread in threads:
        for sentence in re.split(r"(?<=[.!?])\s+|\n", thread["text"]):
            sentence = sentence.strip()
            if 20 <= len(sentence) <= 300 and EDGE_CASE_WORDS.search(sentence):
                if sentence not in hints:
                    hints.append(sentence)
    return hints[:limit]


# -----------------------------------------------------------------------------
# Step 6: save
# -----------------------------------------------------------------------------

def save_results(cands, topics, cutoff):
    """Write kept and quarantined datasets to separate JSON Lines files."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    kept = [c for c in cands if c.status == "kept"]
    held = [c for c in cands if c.status != "kept"]
    for filename, rows in (("candidates.jsonl", kept), ("quarantine.jsonl", held)):
        with open(OUTPUT_DIR / filename, "w", encoding="utf-8") as fh:
            for c in rows:
                fh.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")

    summary = {
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cutoff": f"{cutoff:%Y-%m-%d}",
        "topics": topics,
        "kept": len(kept),
        "quarantined": len(held),
    }
    (OUTPUT_DIR / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return kept, held


# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------

def as_utc(dt):
    """Kaggle's dates come without a time zone. Treat them as UTC so they compare correctly."""
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(dt):
    dt = as_utc(dt)
    return dt.isoformat() if dt else None


def mb(num_bytes):
    return round((num_bytes or 0) / MB, 2)


def tidy(text):
    """Remove blank lines and extra spaces."""
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def first_line(error):
    """Error messages can be long; keep the first line."""
    text = str(error).strip()
    return text.splitlines()[0][:200] if text else type(error).__name__


def parse_date(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} isn't a date like 2026-06-01")


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Collect recent, niche STEM datasets from Kaggle for AI benchmarks."
    )
    p.add_argument("--topics", nargs="+", default=SEARCH_TOPICS,
                   help='topics to search, e.g. --topics "signal processing" optimization')
    p.add_argument("--cutoff", type=parse_date, default=parse_date(CUTOFF_DATE),
                   help="quarantine anything dated before this (YYYY-MM-DD)")
    p.add_argument("--per-topic", type=int, default=DATASETS_PER_TOPIC,
                   help="search results to check per topic")
    p.add_argument("--no-download", action="store_true", help="check dates only, don't download files")
    p.add_argument("--no-scrape", action="store_true", help="don't read discussion threads")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    log.info("Step 1: logging in to Kaggle")
    api = connect_to_kaggle()

    log.info("Step 2: searching %d topic(s), newest first", len(args.topics))
    found = search_kaggle(api, args.topics, args.per_topic)

    if args.no_download:
        log.info("Step 3: checking dates (cutoff %s)", f"{args.cutoff:%Y-%m-%d}")
    else:
        log.info("Steps 3-4: checking dates (cutoff %s) and downloading what passes",
                 f"{args.cutoff:%Y-%m-%d}")
    cands = [
        assess_dataset(api, topic, ds, args.cutoff, download=not args.no_download)
        for topic, ds in found.values()
    ]

    kept = [c for c in cands if c.status == "kept"]
    if kept and not args.no_scrape:
        log.info("Step 5: reading discussion threads for %d dataset(s)", len(kept))
        try:
            asyncio.run(collect_discussions(kept))
        except Exception as e:  # don't lose the rest of the results if the browser fails
            log.error("  The browser failed: %s\n  If it isn't installed yet, run: "
                      "playwright install chromium", first_line(e))
            for c in kept:
                c.notes.append("discussions skipped: the browser failed to run")

    log.info("Step 6: saving results")
    kept, held = save_results(cands, args.topics, args.cutoff)
    log.info("\nDone: %d kept, %d quarantined. Results are in %s/", len(kept), len(held), OUTPUT_DIR)


if __name__ == "__main__":
    main()
