"""License guard.

A benchmark built on data we can't redistribute is useless, so licenses are
checked up front, alongside dates, before anything is downloaded.
"""

from __future__ import annotations

import re


def license_reason(license_name: str | None, blocked: list[str]) -> str | None:
    """Quarantine if any blocked word appears in the license name.

    Matching is by whole word, so "NC" catches "CC-BY-NC-SA-4.0" but not "CC0".
    A missing license counts as "unknown".
    """
    name = license_name or "unknown"
    words = set(re.split(r"[^A-Z0-9]+", name.upper()))
    hits = [b for b in blocked if b.upper() in words]
    if hits:
        return f"LICENSE: {name} ({', '.join(hits)} not allowed)"
    return None
