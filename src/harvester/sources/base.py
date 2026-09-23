"""The interface every data source implements.

The pipeline only talks to this protocol, never to Kaggle directly. That keeps
Kaggle as one plugin (others, like the Hugging Face Hub, can be added later)
and lets tests swap in a fake source that never touches the network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from harvester.models import Details, Listing, RemoteFile, ThreadIndex


class DatasetSource(Protocol):
    name: str

    def search(self, topic: str, limit: int, max_bytes: int) -> list[Listing]:
        """Return up to `limit` datasets for `topic`, newest first, none bigger than `max_bytes`."""
        ...

    def list_files(self, ref: str) -> list[RemoteFile]:
        """Return every file in a dataset, with sizes and creation dates."""
        ...

    def download_file(self, ref: str, name: str, dest_dir: Path) -> None:
        """Download one file into `dest_dir`. It may arrive zipped."""
        ...

    def details(self, ref: str) -> Details:
        """Return the description and keywords that search results leave out."""
        ...

    def list_threads(self, ref: str, limit: int) -> ThreadIndex:
        """Return up to `limit` discussion threads (without their text) and the total count."""
        ...
