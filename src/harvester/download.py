"""Download a kept dataset's files one at a time, within size limits."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from harvester.config import DownloadLimits
from harvester.guards.size import check_and_place
from harvester.models import Candidate, RemoteFile, SavedFile, SkippedFile
from harvester.sources.base import DatasetSource
from harvester.utils import first_line, mb

log = logging.getLogger("harvester")


def download_dataset(
    source: DatasetSource,
    cand: Candidate,
    files: list[RemoteFile],
    dest: Path,
    limits: DownloadLimits,
) -> None:
    incoming = dest / "_incoming"  # each file lands here first so it can be checked
    used = 0

    for f in files:
        name, listed = f.name, f.total_bytes
        final = dest / name
        if not name or ".." in Path(name).parts or Path(name).is_absolute():
            _skip(cand, name, listed, "unsafe file name")
            continue

        # Check 1: the size the source reports, before downloading anything.
        if listed > limits.file_bytes:
            _skip(cand, name, listed, f"over the {limits.max_file_mb} MB file limit")
            continue
        if used + listed > limits.dataset_bytes:
            _skip(cand, name, listed, f"would take this dataset past {limits.max_dataset_mb} MB")
            continue
        if final.exists():  # already downloaded on an earlier run
            used += final.stat().st_size
            _saved(cand, final)
            continue

        shutil.rmtree(incoming, ignore_errors=True)
        incoming.mkdir(parents=True)
        try:
            source.download_file(cand.ref, name, incoming)
        except Exception as e:
            _skip(cand, name, listed, f"download failed: {first_line(e)}")
            continue

        # Check 2: the real size on disk, measured after unzipping.
        for got in [p for p in incoming.rglob("*") if p.is_file()]:
            saved, real = check_and_place(
                got, final, dest, limits.file_bytes, limits.dataset_bytes - used
            )
            if not saved:
                _skip(cand, name, real, "too big once downloaded and unzipped")
                continue
            used += real
            for p in saved:
                _saved(cand, p)

    shutil.rmtree(incoming, ignore_errors=True)
    log.info(
        "      %d file(s) saved, %d skipped", len(cand.files_downloaded), len(cand.files_skipped)
    )


def _saved(cand: Candidate, path: Path) -> None:
    cand.files_downloaded.append(SavedFile(file=path.as_posix(), mb=mb(path.stat().st_size)))


def _skip(cand: Candidate, name: str, size: int, why: str) -> None:
    cand.files_skipped.append(SkippedFile(file=name, mb=mb(size), why=why))
    log.info("      skipped %s: %s", name, why)
