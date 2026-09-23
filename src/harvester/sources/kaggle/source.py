"""Kaggle as a `DatasetSource`, using only the official API."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path
from typing import Any

from harvester.models import Details, Listing, RemoteFile, Thread, ThreadIndex
from harvester.sources.kaggle import auth

KAGGLE_WEB = "https://www.kaggle.com"
MAX_FILE_PAGES = 20  # safety cap: at most 20 pages of 200 files


class KaggleSource:
    name = "kaggle"

    def __init__(self, api: Any) -> None:
        self.api = api

    @classmethod
    def connect(cls) -> KaggleSource:
        return cls(auth.connect())

    def search(self, topic: str, limit: int, max_bytes: int) -> list[Listing]:
        # "published" puts the newest datasets first. max_size makes Kaggle
        # leave out huge datasets before we ever try to download them.
        results = (
            self.api.dataset_list(search=topic, sort_by="published", max_size=str(max_bytes)) or []
        )
        return [to_listing(ds) for ds in results[:limit] if ds is not None]

    def list_files(self, ref: str) -> list[RemoteFile]:
        files: list[RemoteFile] = []
        page_token = None
        for _ in range(MAX_FILE_PAGES):
            resp = self.api.dataset_list_files(ref, page_token=page_token, page_size=200)
            if resp is None:
                break
            if resp.error_message:
                raise RuntimeError(resp.error_message)
            files += [to_remote_file(f) for f in (resp.files or []) if f is not None]
            page_token = resp.next_page_token
            if not page_token:
                break
        return files

    def download_file(self, ref: str, name: str, dest_dir: Path) -> None:
        # quiet=True still prints "Dataset URL: ..." for every file, so hide it.
        with contextlib.redirect_stdout(io.StringIO()):
            self.api.dataset_download_file(ref, name, path=str(dest_dir), force=True, quiet=True)

    def details(self, ref: str) -> Details:
        # The API only offers the description as a metadata file written to disk.
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            path = self.api.dataset_metadata(ref, path=tmp)
            info = json.loads(Path(path).read_text(encoding="utf-8")).get("info", {})
        return Details(
            description=info.get("description") or "",
            keywords=[k for k in info.get("keywords") or [] if k],
        )

    def list_threads(self, ref: str, limit: int) -> ThreadIndex:
        resp = self.api.dataset_list_topics(ref, page_size=limit)
        if resp is None:
            return ThreadIndex(total=0, threads=[])
        threads = [to_thread(t) for t in (resp.topics or []) if t is not None and t.url]
        return ThreadIndex(total=resp.total_count or len(threads), threads=threads)


def to_listing(ds: Any) -> Listing:
    """Convert a kagglesdk `ApiDataset` into our own type."""
    return Listing(
        ref=ds.ref,
        title=ds.title or ds.ref,
        url=f"{KAGGLE_WEB}/datasets/{ds.ref}",
        subtitle=ds.subtitle or "",
        tags=[t.name for t in (ds.tags or []) if t is not None and t.name],
        total_bytes=ds.total_bytes or 0,
        last_updated=ds.last_updated,
        version_dates=[
            v.creation_date for v in (ds.versions or []) if v is not None and v.creation_date
        ],
        license=ds.license_name or None,
        # Not ds.topic_count: the search API always reports 0 there (checked in
        # September 2026 against uciml/iris, which has 33 threads). The real
        # count comes from list_threads.
    )


def to_remote_file(f: Any) -> RemoteFile:
    """Convert a kagglesdk `ApiDatasetFile` into our own type."""
    return RemoteFile(
        name=f.name or "", total_bytes=f.total_bytes or 0, creation_date=f.creation_date
    )


def to_thread(t: Any) -> Thread:
    """Convert a kagglesdk `ApiDiscussionTopic` (it has no post text) into our own type."""
    return Thread(
        url=f"{KAGGLE_WEB}{t.url}" if t.url.startswith("/") else t.url,
        title=t.title or "",
        posted_at=t.post_date,
        author=t.author_name or None,
        comment_count=t.comment_count or 0,
        votes=t.votes or 0,
    )
