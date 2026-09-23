from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from harvester.config import Settings, load_settings
from harvester.models import Details, Listing, RemoteFile, Thread, ThreadIndex

CUTOFF = datetime(2026, 6, 1, tzinfo=UTC)
NEW = datetime(2026, 7, 15, tzinfo=UTC)
OLD = datetime(2023, 3, 10, tzinfo=UTC)


def make_listing(ref: str = "alice/fresh-signals", **kw: object) -> Listing:
    fields: dict[str, object] = {
        "ref": ref,
        "title": ref.split("/")[-1],
        "url": f"https://www.kaggle.com/datasets/{ref}",
        "last_updated": NEW,
        "license": "CC0-1.0",
        "total_bytes": 1000,
    }
    fields.update(kw)
    return Listing.model_validate(fields)


class FakeSource:
    """A DatasetSource that serves canned data and never touches the network."""

    name = "fake"

    def __init__(
        self,
        listings: dict[str, list[Listing]],
        files: dict[str, list[RemoteFile]] | None = None,
        contents: dict[tuple[str, str], bytes] | None = None,
        details: dict[str, Details] | None = None,
        threads: dict[str, list[Thread]] | None = None,
    ) -> None:
        self.listings = listings
        self.files = files or {}
        self.contents = contents or {}
        self.details_by_ref = details or {}
        self.threads = threads or {}
        self.downloads: list[tuple[str, str]] = []
        self.listed: list[str] = []
        self.described: list[str] = []

    def search(self, topic: str, limit: int, max_bytes: int) -> list[Listing]:
        if topic == "broken":
            raise RuntimeError("search exploded")
        return self.listings.get(topic, [])[:limit]

    def list_files(self, ref: str) -> list[RemoteFile]:
        self.listed.append(ref)
        if ref not in self.files:
            raise RuntimeError("404 not found")
        return self.files[ref]

    def download_file(self, ref: str, name: str, dest_dir: Path) -> None:
        self.downloads.append((ref, name))
        (dest_dir / name).write_bytes(self.contents[(ref, name)])

    def details(self, ref: str) -> Details:
        self.described.append(ref)
        if ref == "boom/details":
            raise RuntimeError("metadata exploded")
        return self.details_by_ref.get(ref, Details())

    def list_threads(self, ref: str, limit: int) -> ThreadIndex:
        threads = self.threads.get(ref, [])
        return ThreadIndex(total=len(threads), threads=threads[:limit])


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(
        overrides={"output_dir": tmp_path / "out", "topics": ["signals"], "per_topic": 10}
    )
