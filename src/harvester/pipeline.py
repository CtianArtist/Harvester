"""Run the stages in order: discover, decide, download, enrich, save.

Cheap checks run first. A dataset is only downloaded, and its discussions only
read, once every check that can reject it has passed.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from harvester.config import Settings
from harvester.contamination.verdict import assess, prefilter, relevance
from harvester.download import download_dataset
from harvester.models import Candidate, Listing, Verdict
from harvester.sources.base import DatasetSource
from harvester.storage.output import raw_dir, save_results
from harvester.utils import first_line

log = logging.getLogger("harvester")
MAX_THREADS_LISTED = 50  # one page of the source's thread list is plenty to pick from


@dataclass
class RunResult:
    kept: list[Candidate]
    quarantined: list[Candidate]


def run(
    settings: Settings, source: DatasetSource, *, download: bool = True, scrape: bool = True
) -> RunResult:
    log.info("Searching %d topic(s) on %s, newest first", len(settings.topics), source.name)
    found = discover(source, settings)

    log.info("Checking %d dataset(s) against the %s cutoff", len(found), settings.cutoff)
    cands = [
        evaluate(source, topic, listing, settings, download=download)
        for topic, listing in found.values()
    ]

    kept = [c for c in cands if c.kept]
    if kept:
        log.info("Listing discussion threads for %d dataset(s)", len(kept))
        list_discussions(source, kept, settings.scrape.threads_per_dataset)
        with_threads = [c for c in kept if c.discussions]
        if with_threads and scrape:
            log.info("Reading %d dataset(s)' threads in the browser", len(with_threads))
            read_discussions(with_threads, settings)

    save_results(cands, settings)
    return RunResult(kept=kept, quarantined=[c for c in cands if not c.kept])


def discover(source: DatasetSource, settings: Settings) -> dict[str, tuple[str, Listing]]:
    """Search each topic. Returns {ref: (topic, listing)} with no duplicates."""
    found: dict[str, tuple[str, Listing]] = {}
    for topic in settings.topics:
        try:
            results = source.search(topic, settings.per_topic, settings.download.dataset_bytes)
        except Exception as e:
            log.warning("  Search for %r failed: %s", topic, first_line(e))
            continue
        new = 0
        for listing in results:
            if listing.ref not in found:
                found[listing.ref] = (topic, listing)
                new += 1
        log.info("  %-24s %2d results, %d new", topic, len(results), new)
    return found


def evaluate(
    source: DatasetSource, topic: str, listing: Listing, settings: Settings, *, download: bool
) -> Candidate:
    """Decide whether to keep one dataset, and download it if we do."""
    cand = Candidate.from_listing(listing, topic)

    early = prefilter(listing, settings)
    if early:
        cand.apply(Verdict.quarantine(*early))
        _log_decision(cand)
        return cand

    try:
        files = source.list_files(listing.ref)
    except Exception as e:
        cand.apply(Verdict.quarantine(f"SOURCE: couldn't list its files ({first_line(e)})"))
        _log_decision(cand)
        return cand

    # Only fetch the description when the title and tags alone don't show the
    # dataset is on topic: it costs one more API call.
    details = None
    if relevance(listing, topic, settings).score < settings.min_relevance_score:
        try:
            details = source.details(listing.ref)
        except Exception as e:
            cand.notes.append(f"couldn't fetch its description: {first_line(e)}")

    cand.apply(assess(listing, files, settings, topic=topic, details=details))
    _log_decision(cand)
    if cand.kept and download:
        download_dataset(
            source, cand, files, raw_dir(settings.output_dir, cand.ref), settings.download
        )
    return cand


def list_discussions(source: DatasetSource, cands: list[Candidate], per_dataset: int) -> None:
    """Ask the source which threads each dataset has, and pick the busiest few to read."""
    for c in cands:
        try:
            index = source.list_threads(c.ref, MAX_THREADS_LISTED)
        except Exception as e:
            c.notes.append(f"couldn't list discussion threads: {first_line(e)}")
            continue
        c.discussion_count = index.total
        # Busiest first: long threads are where edge cases get argued out.
        busiest = sorted(index.threads, key=lambda t: (t.comment_count, t.votes), reverse=True)
        c.discussions = busiest[:per_dataset]


def read_discussions(cands: list[Candidate], settings: Settings) -> None:
    """Fill in the text of each picked thread. The browser only starts if there's work."""
    # Imported here so runs with --no-scrape never load Playwright.
    from harvester.enrichment.discussions import collect_discussions

    try:
        asyncio.run(collect_discussions(cands, settings.scrape))
    except Exception as e:  # don't lose the rest of the results if the browser fails
        log.error(
            "  The browser failed: %s\n  If it isn't installed yet, run: "
            "playwright install chromium",
            first_line(e),
        )
        for c in cands:
            c.notes.append("thread text not read: the browser failed to run")


def _log_decision(cand: Candidate) -> None:
    status = cand.status.upper() if cand.status else "?"
    log.info("  %-11s %s: %s", status, cand.ref, "; ".join(cand.reasons))
