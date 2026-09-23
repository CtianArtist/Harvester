"""Temporal contamination checks.

Anything created before a model's training cutoff may be in its training data,
so we quarantine it. "Updated recently" doesn't mean "new", though: an old
dataset can get a fresh upload. So a dataset is judged by the OLDEST date we
can find on it (its files and versions), not by its last-updated date.

Dates are a strong signal, not proof. Someone could upload years-old data as a
brand-new dataset, and no date check can catch that; that is what the
near-duplicate check (planned) is for.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime


def listing_reason(last_updated: datetime | None, cutoff: datetime) -> str | None:
    """The check we can make from a search result alone, before any more API calls."""
    if last_updated is None:
        return "TEMPORAL: the source gave no date, so its age can't be checked"
    if last_updated < cutoff:
        return (
            f"TEMPORAL: last updated {last_updated:%Y-%m-%d}, before the {cutoff:%Y-%m-%d} cutoff"
        )
    return None


def earliest_date(
    last_updated: datetime | None, other_dates: Iterable[datetime | None]
) -> datetime | None:
    dates = [d for d in (last_updated, *other_dates) if d is not None]
    return min(dates, default=None)


def history_reason(earliest: datetime | None, cutoff: datetime) -> str | None:
    """The check that needs file and version dates."""
    if earliest is not None and earliest < cutoff:
        return f"TEMPORAL: updated recently, but parts of it date back to {earliest:%Y-%m-%d}"
    return None
