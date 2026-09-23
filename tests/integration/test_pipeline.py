"""The whole pipeline end to end, against a fake source (no network, no browser)."""

import json

from harvester import pipeline
from harvester.config import load_settings
from harvester.models import RemoteFile
from harvester.utils import MB
from tests.conftest import NEW, OLD, FakeSource, make_listing


def build_source():
    fresh = make_listing("alice/fresh", discussion_count=0)
    stale = make_listing("bob/stale", last_updated=OLD)
    reupload = make_listing("carol/reupload")
    noncommercial = make_listing("dan/nc", license="CC-BY-NC-4.0")
    return FakeSource(
        listings={"signals": [fresh, stale, reupload, noncommercial]},
        files={
            "alice/fresh": [
                RemoteFile(name="small.csv", total_bytes=10, creation_date=NEW),
                RemoteFile(name="huge.csv", total_bytes=300 * MB, creation_date=NEW),
            ],
            "carol/reupload": [RemoteFile(name="x.csv", total_bytes=10, creation_date=OLD)],
        },
        contents={("alice/fresh", "small.csv"): b"a,b\n1,2\n"},
    )


def test_full_run(settings):
    source = build_source()
    result = pipeline.run(settings, source, download=True, scrape=True)

    assert [c.ref for c in result.kept] == ["alice/fresh"]
    reasons = {c.ref: c.reasons[0] for c in result.quarantined}
    assert reasons["bob/stale"].startswith("TEMPORAL: last updated")
    assert reasons["carol/reupload"].startswith("TEMPORAL: updated recently")
    assert reasons["dan/nc"].startswith("LICENSE:")

    # Rejected by the listing alone, so their files were never even listed.
    assert "bob/stale" not in source.listed
    assert "dan/nc" not in source.listed

    # Only the small file was downloaded; the huge one was skipped before download.
    assert source.downloads == [("alice/fresh", "small.csv")]
    fresh = result.kept[0]
    assert [s.file for s in fresh.files_skipped] == ["huge.csv"]
    saved = settings.output_dir / "raw" / "alice__fresh" / "small.csv"
    assert saved.read_bytes() == b"a,b\n1,2\n"
    assert not (saved.parent / "_incoming").exists()

    # The source said there are no discussions, so the browser never started.
    assert fresh.notes == ["no discussion threads (per the source), so none were read"]

    out = settings.output_dir
    accepted = [json.loads(line) for line in (out / "accepted.jsonl").read_text().splitlines()]
    held = (out / "quarantine.jsonl").read_text().splitlines()
    summary = json.loads((out / "run_summary.json").read_text())
    assert [a["ref"] for a in accepted] == ["alice/fresh"]
    assert accepted[0]["earliest_date_seen"].startswith("2026-07-15")
    assert len(held) == 3
    assert summary["kept"] == 1
    assert summary["quarantined"] == 3


def test_second_run_reuses_files_already_downloaded(settings):
    pipeline.run(settings, build_source(), scrape=False)
    source = build_source()
    result = pipeline.run(settings, source, scrape=False)
    assert source.downloads == []
    assert [s.file.rsplit("/", 1)[-1] for s in result.kept[0].files_downloaded] == ["small.csv"]


def test_no_download_mode_still_decides(settings):
    source = build_source()
    result = pipeline.run(settings, source, download=False, scrape=False)
    assert len(result.kept) == 1
    assert source.downloads == []


def test_failed_search_and_failed_file_listing_do_not_stop_the_run(tmp_path):
    settings = load_settings(overrides={"output_dir": tmp_path, "topics": ["broken", "signals"]})
    source = FakeSource(listings={"signals": [make_listing("eve/missing-files")]})
    result = pipeline.run(settings, source, scrape=False)
    assert result.kept == []
    assert result.quarantined[0].reasons[0].startswith("SOURCE: couldn't list its files")


def test_same_dataset_found_by_two_topics_is_checked_once(tmp_path):
    settings = load_settings(overrides={"output_dir": tmp_path, "topics": ["a", "b"]})
    shared = make_listing("x/shared")
    source = FakeSource(
        listings={"a": [shared], "b": [shared]},
        files={"x/shared": [RemoteFile(name="f.csv", total_bytes=1, creation_date=NEW)]},
        contents={("x/shared", "f.csv"): b"1"},
    )
    result = pipeline.run(settings, source, scrape=False)
    assert len(result.kept) == 1
    assert result.kept[0].found_by_search == "a"
