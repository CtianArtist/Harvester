"""The whole pipeline end to end, against a fake source (no network, no browser)."""

import json

from harvester import pipeline
from harvester.config import load_settings
from harvester.models import Details, RemoteFile, Thread
from harvester.utils import MB
from tests.conftest import NEW, OLD, FakeSource, make_listing


def thread(n: int, comments: int) -> Thread:
    return Thread(
        url=f"https://www.kaggle.com/d/discussion/{n}", title=f"t{n}", comment_count=comments
    )


def build_source():
    fresh = make_listing("alice/fresh-signals")
    stale = make_listing("bob/stale-signals", last_updated=OLD)
    reupload = make_listing("carol/reupload-signals")
    noncommercial = make_listing("dan/nc-signals", license="CC-BY-NC-4.0")
    off_topic = make_listing("erin/school-map", title="School map")
    described = make_listing("fay/sensor-dump", title="sensor dump")
    return FakeSource(
        listings={"signals": [fresh, stale, reupload, noncommercial, off_topic, described]},
        files={
            "alice/fresh-signals": [
                RemoteFile(name="small.csv", total_bytes=10, creation_date=NEW),
                RemoteFile(name="huge.csv", total_bytes=300 * MB, creation_date=NEW),
            ],
            "carol/reupload-signals": [RemoteFile(name="x.csv", total_bytes=10, creation_date=OLD)],
            "erin/school-map": [],
            "fay/sensor-dump": [],
        },
        contents={("alice/fresh-signals", "small.csv"): b"a,b\n1,2\n"},
        details={
            "fay/sensor-dump": Details(description="Raw accelerometer data", keywords=["signals"])
        },
        threads={"alice/fresh-signals": [thread(1, 0), thread(2, 9), thread(3, 4), thread(4, 1)]},
    )


def test_full_run(settings):
    source = build_source()
    result = pipeline.run(settings, source, download=True, scrape=False)

    assert [c.ref for c in result.kept] == ["alice/fresh-signals", "fay/sensor-dump"]
    reasons = {c.ref: c.reasons[0] for c in result.quarantined}
    assert reasons["bob/stale-signals"].startswith("TEMPORAL: last updated")
    assert reasons["carol/reupload-signals"].startswith("TEMPORAL: updated recently")
    assert reasons["dan/nc-signals"].startswith("LICENSE:")
    assert reasons["erin/school-map"].startswith("RELEVANCE:")

    # Rejected by the listing alone, so their files were never even listed.
    assert "bob/stale-signals" not in source.listed
    assert "dan/nc-signals" not in source.listed
    # The description was only fetched where the title didn't already match.
    assert source.described == ["erin/school-map", "fay/sensor-dump"]

    # Only the small file was downloaded; the huge one was skipped before download.
    assert ("alice/fresh-signals", "small.csv") in source.downloads
    fresh = result.kept[0]
    assert [s.file for s in fresh.files_skipped] == ["huge.csv"]
    saved = settings.output_dir / "raw" / "alice__fresh-signals" / "small.csv"
    assert saved.read_bytes() == b"a,b\n1,2\n"
    assert not (saved.parent / "_incoming").exists()

    # Threads come from the source's list: real count, busiest three picked.
    assert fresh.discussion_count == 4
    assert [t.title for t in fresh.discussions] == ["t2", "t3", "t4"]
    assert result.kept[1].discussion_count == 0

    out = settings.output_dir
    accepted = [json.loads(line) for line in (out / "accepted.jsonl").read_text().splitlines()]
    held = (out / "quarantine.jsonl").read_text().splitlines()
    summary = json.loads((out / "run_summary.json").read_text())
    assert [a["ref"] for a in accepted] == ["alice/fresh-signals", "fay/sensor-dump"]
    assert accepted[0]["earliest_date_seen"].startswith("2026-07-15")
    assert accepted[1]["matched_keywords"] == ["signals"]
    assert len(held) == 4
    assert summary["kept"] == 2
    assert summary["quarantined"] == 4


def test_browser_is_not_started_when_no_kept_dataset_has_threads(settings, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("the browser should not start")

    monkeypatch.setattr(pipeline, "read_discussions", fail)
    source = build_source()
    source.threads = {}
    pipeline.run(settings, source, download=False, scrape=True)


def test_second_run_reuses_files_already_downloaded(settings):
    pipeline.run(settings, build_source(), scrape=False)
    source = build_source()
    result = pipeline.run(settings, source, scrape=False)
    assert source.downloads == []
    assert [s.file.rsplit("/", 1)[-1] for s in result.kept[0].files_downloaded] == ["small.csv"]


def test_no_download_mode_still_decides(settings):
    source = build_source()
    result = pipeline.run(settings, source, download=False, scrape=False)
    assert len(result.kept) == 2
    assert source.downloads == []


def test_failures_are_recorded_and_do_not_stop_the_run(tmp_path):
    settings = load_settings(overrides={"output_dir": tmp_path, "topics": ["broken", "signals"]})
    source = FakeSource(
        listings={"signals": [make_listing("eve/missing-files"), make_listing("boom/details")]},
        files={"boom/details": []},
    )
    result = pipeline.run(settings, source, scrape=False)
    assert result.kept == []
    missing, boom = result.quarantined
    assert missing.reasons[0].startswith("SOURCE: couldn't list its files")
    assert boom.notes == ["couldn't fetch its description: metadata exploded"]
    assert boom.reasons[0].startswith("RELEVANCE:")


def test_same_dataset_found_by_two_topics_is_checked_once(tmp_path):
    settings = load_settings(
        overrides={"output_dir": tmp_path, "topics": ["a", "b"], "min_relevance_score": 0}
    )
    shared = make_listing("x/shared")
    source = FakeSource(
        listings={"a": [shared], "b": [shared]},
        files={"x/shared": [RemoteFile(name="f.csv", total_bytes=1, creation_date=NEW)]},
        contents={("x/shared", "f.csv"): b"1"},
    )
    result = pipeline.run(settings, source, scrape=False)
    assert len(result.kept) == 1
    assert result.kept[0].found_by_search == "a"
