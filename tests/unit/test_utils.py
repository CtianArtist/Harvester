from datetime import UTC, datetime, timedelta, timezone

import pytest

from harvester.utils import as_utc, first_line, mb, safe_dirname, tidy


def test_as_utc_treats_naive_dates_as_utc():
    assert as_utc(datetime(2026, 1, 1)) == datetime(2026, 1, 1, tzinfo=UTC)


def test_as_utc_parses_z_suffix_strings():
    assert as_utc("2026-01-01T12:00:00Z") == datetime(2026, 1, 1, 12, tzinfo=UTC)


def test_as_utc_keeps_existing_timezones():
    plus_two = timezone(timedelta(hours=2))
    assert as_utc(datetime(2026, 1, 1, tzinfo=plus_two)).tzinfo is plus_two


def test_as_utc_passes_none_through():
    assert as_utc(None) is None


@pytest.mark.parametrize(("num_bytes", "expected"), [(None, 0), (0, 0), (1024 * 1024 * 3, 3.0)])
def test_mb(num_bytes, expected):
    assert mb(num_bytes) == expected


def test_tidy_collapses_whitespace_and_blank_lines():
    assert tidy("  a   b \n\n   \n c ") == "a b\nc"


def test_first_line_trims_long_errors_and_falls_back_to_type_name():
    assert first_line(RuntimeError("one\ntwo")) == "one"
    assert first_line(ValueError()) == "ValueError"


def test_safe_dirname():
    assert safe_dirname("alice/data") == "alice__data"
