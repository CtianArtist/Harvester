"""Size guard: the check that protects later stages from running out of memory.

Sizes are checked twice. Before downloading, against what the source reports.
After downloading, against the real size on disk, measured after unzipping.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import NamedTuple


class Placement(NamedTuple):
    saved: list[Path]  # empty if the file was too big and nothing was kept
    real_bytes: int


def check_and_place(
    got: Path, final: Path, dest: Path, file_limit: int, room_left: int
) -> Placement:
    """Move a downloaded file into place if it fits the limits, unzipping zips.

    Kaggle sends large files as .zip archives. A small zip can unpack into
    something huge (a "zip bomb"), so we read the unzipped sizes from the
    archive's index BEFORE extracting anything.
    """
    if zipfile.is_zipfile(got):
        with zipfile.ZipFile(got) as z:
            members = [m for m in z.infolist() if not m.is_dir()]
            real = sum(m.file_size for m in members)  # size after unzipping
            if real > room_left or any(m.file_size > file_limit for m in members):
                return Placement([], real)
            # ZipFile.extract strips ".." and absolute paths, so members can't
            # escape `dest` (tests/unit/test_size_guard.py checks this).
            return Placement([Path(z.extract(m, dest)) for m in members], real)

    real = got.stat().st_size
    if real > file_limit or real > room_left:
        return Placement([], real)
    final.parent.mkdir(parents=True, exist_ok=True)
    got.replace(final)
    return Placement([final], real)
