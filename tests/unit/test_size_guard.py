import zipfile
from pathlib import Path

from harvester.guards.size import check_and_place

KB = 1024


def write_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def test_plain_file_within_limits_is_moved_into_place(tmp_path):
    got = tmp_path / "in" / "a.csv"
    got.parent.mkdir()
    got.write_bytes(b"x" * 10)
    final = tmp_path / "dest" / "a.csv"

    saved, real = check_and_place(got, final, tmp_path / "dest", file_limit=100, room_left=100)

    assert saved == [final]
    assert real == 10
    assert final.read_bytes() == b"x" * 10
    assert not got.exists()


def test_plain_file_over_the_file_limit_is_refused(tmp_path):
    got = tmp_path / "a.csv"
    got.write_bytes(b"x" * 200)
    saved, real = check_and_place(got, tmp_path / "d" / "a.csv", tmp_path / "d", 100, 1000)
    assert saved == []
    assert real == 200


def test_plain_file_over_the_room_left_is_refused(tmp_path):
    got = tmp_path / "a.csv"
    got.write_bytes(b"x" * 50)
    saved, _ = check_and_place(got, tmp_path / "d" / "a.csv", tmp_path / "d", 100, 40)
    assert saved == []


def test_zip_bomb_is_refused_before_extracting(tmp_path):
    """A zip that is tiny on disk but huge once unpacked must never be extracted."""
    bomb = write_zip(tmp_path / "bomb.zip", {"big.csv": b"\0" * (512 * KB)})
    assert bomb.stat().st_size < 10 * KB  # compresses to almost nothing
    dest = tmp_path / "dest"

    saved, real = check_and_place(
        bomb, dest / "big.csv", dest, file_limit=100 * KB, room_left=10**9
    )

    assert saved == []
    assert real == 512 * KB
    assert not dest.exists()  # nothing was written


def test_zip_within_limits_is_extracted(tmp_path):
    z = write_zip(tmp_path / "data.zip", {"a.csv": b"1,2\n", "sub/b.csv": b"3,4\n"})
    dest = tmp_path / "dest"
    saved, real = check_and_place(z, dest / "data.zip", dest, file_limit=KB, room_left=KB)
    assert sorted(p.relative_to(dest).as_posix() for p in saved) == ["a.csv", "sub/b.csv"]
    assert real == 8


def test_zip_total_over_room_left_is_refused(tmp_path):
    z = write_zip(tmp_path / "data.zip", {"a.csv": b"x" * 600, "b.csv": b"x" * 600})
    saved, _ = check_and_place(z, tmp_path / "d" / "x", tmp_path / "d", file_limit=KB, room_left=KB)
    assert saved == []


def test_zip_members_cannot_escape_the_destination(tmp_path):
    z = write_zip(tmp_path / "evil.zip", {"../../escaped.txt": b"gotcha"})
    dest = tmp_path / "a" / "b" / "dest"
    saved, _ = check_and_place(z, dest / "x", dest, file_limit=KB, room_left=KB)
    assert len(saved) == 1
    assert saved[0].resolve().is_relative_to(dest.resolve())
    assert not (tmp_path / "a" / "escaped.txt").exists()
