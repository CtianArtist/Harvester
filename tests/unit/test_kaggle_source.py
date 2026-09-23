"""The Kaggle adapter, tested against stand-ins shaped like kagglesdk objects."""

from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest

from harvester.sources.kaggle.source import KaggleSource, to_listing


def api_dataset(**kw):
    fields = {
        "ref": "alice/data",
        "title": "Data",
        "tags": [NS(name="signal processing"), None, NS(name="")],
        "total_bytes": 2048,
        "last_updated": datetime(2026, 7, 1),  # naive, like the real API
        "versions": [NS(creation_date=datetime(2026, 6, 20)), None],
        "license_name": "CC0-1.0",
        "topic_count": 4,
    }
    fields.update(kw)
    return NS(**fields)


def test_to_listing_converts_and_cleans_fields():
    listing = to_listing(api_dataset())
    assert listing.url == "https://www.kaggle.com/datasets/alice/data"
    assert listing.tags == ["signal processing"]
    assert listing.last_updated == datetime(2026, 7, 1, tzinfo=UTC)
    assert listing.version_dates == [datetime(2026, 6, 20, tzinfo=UTC)]
    assert listing.license == "CC0-1.0"
    assert listing.discussion_count is None  # the API's topic_count is always 0


def test_to_listing_handles_missing_fields():
    listing = to_listing(api_dataset(title=None, tags=None, versions=None, license_name=""))
    assert listing.title == "alice/data"
    assert listing.tags == []
    assert listing.version_dates == []
    assert listing.license is None


class FakeApi:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def dataset_list(self, **kw):
        self.calls.append(kw)
        return [api_dataset(ref=f"a/{i}") for i in range(10)] + [None]

    def dataset_list_files(self, ref, page_token=None, page_size=20):
        return self.pages[page_token]


def page(names, next_token=None, error=None):
    files = [NS(name=n, total_bytes=1, creation_date=None) for n in names]
    return NS(files=files, next_page_token=next_token, error_message=error)


def test_search_asks_for_newest_first_and_respects_limit():
    api = FakeApi({})
    results = KaggleSource(api).search("optimization", limit=3, max_bytes=500)
    assert [r.ref for r in results] == ["a/0", "a/1", "a/2"]
    assert api.calls == [{"search": "optimization", "sort_by": "published", "max_size": "500"}]


def test_list_files_follows_pages():
    api = FakeApi({None: page(["a", "b"], "t2"), "t2": page(["c"])})
    assert [f.name for f in KaggleSource(api).list_files("x/y")] == ["a", "b", "c"]


def test_list_files_raises_on_api_error():
    api = FakeApi({None: page([], error="Dataset not found")})
    with pytest.raises(RuntimeError, match="Dataset not found"):
        KaggleSource(api).list_files("x/y")
