"""Pull sentences that warn about traps in the data out of discussion threads.

This is a rough keyword filter. It finds candidates for a human (or a later
model pass) to read; it doesn't understand the text.
"""

from __future__ import annotations

import re

from harvester.models import Thread

EDGE_CASE_WORDS = re.compile(
    r"\b(edge cases?|corner cases?|careful|caveat|gotcha|bug|wrong|incorrect|missing|"
    r"NaNs?|outliers?|duplicates?|leak(age)?|mislabel(l)?ed|units?|overflow|unstable|"
    r"diverg\w*|doesn't work|does not work)\b",
    re.IGNORECASE,
)
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n")


def find_edge_case_hints(threads: list[Thread], limit: int = 8) -> list[str]:
    hints: list[str] = []
    for thread in threads:
        for sentence in SENTENCE_BREAK.split(thread.text):
            sentence = sentence.strip()
            if (
                20 <= len(sentence) <= 300
                and EDGE_CASE_WORDS.search(sentence)
                and sentence not in hints
            ):
                hints.append(sentence)
    return hints[:limit]
