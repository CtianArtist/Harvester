"""Relevance guard: is this dataset actually about the topic it was found by?

Kaggle's search matches loosely. It returns any dataset whose description
mentions the search words, so a map of schools that lists "linear algebra"
among the subjects taught comes back for "linear algebra". A mention in the
description therefore proves little on its own.

So evidence is weighted by where it appears:
  - a keyword in the title, subtitle or tags is strong: STRONG_POINTS each
  - a keyword only in the description is weak: 1 point each
A dataset passes with `min_relevance_score` points (3 by default: one strong
mention, or three different keywords in the description).

Keywords match as whole words or phrases; a trailing "s" or "es" is allowed, so
"signal" matches "signals".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from harvester.models import Details, Listing

STRONG_POINTS = 3
_SEPARATORS = re.compile(r"[_\-/]+")  # "Linear_algebra", "Q-learning" -> spaces


@dataclass
class Relevance:
    strong: list[str] = field(default_factory=list)  # found in title, subtitle or tags
    weak: list[str] = field(default_factory=list)  # found only in the description

    @property
    def score(self) -> int:
        return STRONG_POINTS * len(self.strong) + len(self.weak)

    @property
    def keywords(self) -> list[str]:
        return self.strong + self.weak


def normalize(text: str) -> str:
    return _SEPARATORS.sub(" ", text.lower())


def score_relevance(keywords: list[str], listing: Listing, details: Details | None) -> Relevance:
    headline = normalize("\n".join([listing.title, listing.subtitle, *listing.tags]))
    if details is not None:
        headline += "\n" + normalize("\n".join(details.keywords))  # Kaggle's keywords are tags
    body = normalize(details.description) if details is not None else ""

    strong = find_keywords(keywords, headline)
    weak = [kw for kw in find_keywords(keywords, body) if kw not in strong]
    return Relevance(strong=strong, weak=weak)


def find_keywords(keywords: list[str], text: str) -> list[str]:
    """Return the keywords that appear in `text` (already normalized), in keyword order."""
    return [kw for kw in keywords if _pattern(kw).search(text)]


def relevance_reason(topic: str, rel: Relevance, min_score: int) -> str | None:
    if rel.score >= min_score:
        return None
    if rel.keywords:
        where = f"only {', '.join(rel.weak)} in the description" if rel.weak else ""
        found = where or ", ".join(rel.strong)
    else:
        found = "no keywords found"
    return f"RELEVANCE: {topic!r} scored {rel.score} of {min_score} needed ({found})"


def _pattern(keyword: str) -> re.Pattern[str]:
    words = normalize(keyword).split()
    return re.compile(r"\b" + r"\s+".join(map(re.escape, words)) + r"(?:s|es)?\b")
