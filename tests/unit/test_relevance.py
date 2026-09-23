import pytest

from harvester.guards.relevance import (
    Relevance,
    find_keywords,
    normalize,
    relevance_reason,
    score_relevance,
)
from harvester.models import Details
from tests.conftest import make_listing


@pytest.mark.parametrize(
    ("keyword", "text", "hit"),
    [
        ("linear algebra", "Linear_algebra", True),  # underscores, as in real Kaggle titles
        ("signal", "raw EEG signals", True),  # plurals
        ("matrix", "sparse matrices", False),  # irregular plurals need their own keyword
        ("q learning", "Deep Q-Learning agent", True),  # hyphens
        ("tsp", "tspan measurements", False),  # whole words only
        ("svd", "we use SVD here", True),  # case
        ("sampling rate", "sampling\nrate of 1 kHz", True),  # phrases across line breaks
    ],
)
def test_find_keywords(keyword, text, hit):
    assert (find_keywords([keyword], normalize(text)) == [keyword]) is hit


KEYWORDS = ["signal processing", "fft", "radar", "wavelet"]


def test_headline_mentions_are_strong_and_description_mentions_weak():
    listing = make_listing(title="Radar sweeps", tags=["physics"])
    details = Details(description="We apply an FFT and a wavelet transform to each radar sweep.")
    rel = score_relevance(KEYWORDS, listing, details)
    assert rel.strong == ["radar"]
    assert rel.weak == ["fft", "wavelet"]  # radar isn't double-counted
    assert rel.score == 3 + 2


def test_kaggle_keywords_from_the_metadata_count_as_strong():
    rel = score_relevance(
        KEYWORDS, make_listing(title="x"), Details(keywords=["signal processing"])
    )
    assert rel.strong == ["signal processing"]


def test_a_passing_mention_in_the_description_is_not_enough():
    """The real case: a map of schools that lists linear algebra among subjects taught."""
    listing = make_listing(title="Bengaluru School-College-NGO Mapping")
    details = Details(description="Focus areas: mathematics for AI, linear algebra, matrices.")
    rel = score_relevance(["linear algebra", "matrices", "eigenvalue"], listing, details)
    assert rel.score == 2
    assert relevance_reason("linear algebra", rel, min_score=3) == (
        "RELEVANCE: 'linear algebra' scored 2 of 3 needed "
        "(only linear algebra, matrices in the description)"
    )


def test_reason_when_nothing_matches():
    assert relevance_reason("optimization", Relevance(), 3) == (
        "RELEVANCE: 'optimization' scored 0 of 3 needed (no keywords found)"
    )
