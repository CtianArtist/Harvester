"""Combine every check into one keep/quarantine decision.

These functions only decide; they never download or call an API. That keeps
the contamination rules easy to test and easy to explain.
"""

from __future__ import annotations

from harvester.config import Settings
from harvester.contamination import temporal
from harvester.guards.license import license_reason
from harvester.guards.relevance import Relevance, relevance_reason, score_relevance
from harvester.models import Details, Listing, RemoteFile, Status, Verdict


def prefilter(listing: Listing, settings: Settings) -> list[str]:
    """Reasons to quarantine that we can find from the search result alone.

    Running these first saves an API call for every dataset they reject.
    Relevance isn't here: a title that doesn't mention the topic proves
    nothing until we've read the description.
    """
    reasons = [
        temporal.listing_reason(listing.last_updated, settings.cutoff_at),
        license_reason(listing.license, settings.blocked_licenses),
    ]
    return [r for r in reasons if r]


def relevance(
    listing: Listing, topic: str, settings: Settings, details: Details | None = None
) -> Relevance:
    return score_relevance(settings.keywords_for(topic), listing, details)


def assess(
    listing: Listing,
    files: list[RemoteFile],
    settings: Settings,
    *,
    topic: str,
    details: Details | None = None,
) -> Verdict:
    """The full decision, using the dataset's file list and description as well."""
    reasons = prefilter(listing, settings)
    other_dates = [f.creation_date for f in files] + list(listing.version_dates)
    earliest = temporal.earliest_date(listing.last_updated, other_dates)

    # If the last-updated date already failed, the history check would only repeat it.
    if temporal.listing_reason(listing.last_updated, settings.cutoff_at) is None:
        history = temporal.history_reason(earliest, settings.cutoff_at)
        if history:
            reasons.append(history)

    rel = relevance(listing, topic, settings, details)
    off_topic = relevance_reason(topic, rel, settings.min_relevance_score)
    if off_topic:
        reasons.append(off_topic)

    if reasons or earliest is None:
        return Verdict(
            status=Status.QUARANTINED,
            reasons=reasons,
            earliest_date=earliest,
            matched_keywords=rel.keywords,
        )
    return Verdict(
        status=Status.KEPT,
        reasons=[f"oldest date found is {earliest:%Y-%m-%d}"],
        earliest_date=earliest,
        matched_keywords=rel.keywords,
    )
