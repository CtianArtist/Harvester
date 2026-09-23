"""Run the stages in order: discover, decide, download, enrich, save.

Cheap checks run first. A dataset is only downloaded, and its discussions only
read, once every check that can reject it has passed.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from harvester.config import ScrapeSettings, Settings
from harvester.contamination.verdict import assess, prefilter
from harvester.download import download_dataset
from harvester.models import Candidate, Listing, Verdict
from harvester.sources.base import DatasetSource
from harvester.storage.output import raw_dir, save_results
from harvester.utils import first_line

log = logging.getLogger("harvester")


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
    if kept and scrape:
        log.info("Reading discussion threads for %d dataset(s)", len(kept))
        enrich(kept, settings.scrape)

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

    cand.apply(assess(listing, files, settings))
    _log_decision(cand)
    if cand.kept and download:
        download_dataset(
            source, cand, files, raw_dir(settings.output_dir, cand.ref), settings.download
        )
    return cand


def enrich(cands: list[Candidate], cfg: ScrapeSettings) -> None:
    """Read discussions for datasets that have any. The browser is only started if needed."""
    to_read = []
    for c in cands:
        if c.discussion_count == 0:
            c.notes.append("no discussion threads (per the source), so none were read")
        else:
            to_read.append(c)
    if not to_read:
        return

    # Imported here so runs with --no-scrape never load Playwright.
    from harvester.enrichment.discussions import collect_discussions

    try:
        asyncio.run(collect_discussions(to_read, cfg))
    except Exception as e:  # don't lose the rest of the results if the browser fails
        log.error(
            "  The browser failed: %s\n  If it isn't installed yet, run: "
            "playwright install chromium",
            first_line(e),
        )
        for c in to_read:
            c.notes.append("discussions skipped: the browser failed to run")


def _log_decision(cand: Candidate) -> None:
    status = cand.status.upper() if cand.status else "?"
    log.info("  %-11s %s: %s", status, cand.ref, "; ".join(cand.reasons))
