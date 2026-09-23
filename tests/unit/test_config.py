from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from harvester.config import Settings, load_settings

REPO = Path(__file__).resolve().parents[2]


def test_default_yaml_matches_code_defaults():
    """config/default.yaml is documentation; it must not drift from the real defaults."""
    assert load_settings(REPO / "config" / "default.yaml") == Settings()


def test_overrides_win_over_the_file(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("per_topic: 3\ncutoff: 2025-01-01\n")
    s = load_settings(f, {"per_topic": 7})
    assert s.per_topic == 7
    assert s.cutoff == date(2025, 1, 1)
    assert s.cutoff_at == datetime(2025, 1, 1, tzinfo=UTC)


def test_typos_are_rejected(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("download:\n  max_fiel_mb: 10\n")
    with pytest.raises(ValidationError, match="max_fiel_mb"):
        load_settings(f)


@pytest.mark.parametrize("bad", [{"per_topic": 0}, {"per_topic": 21}, {"topics": []}])
def test_out_of_range_values_are_rejected(bad):
    with pytest.raises(ValidationError):
        load_settings(overrides=bad)


def test_empty_yaml_file_means_all_defaults(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("")
    assert load_settings(f) == Settings()
