from datetime import UTC, datetime

from harvester.contamination.verdict import assess, prefilter
from harvester.guards.license import license_reason
from harvester.models import Details, RemoteFile, Status
from tests.conftest import NEW, OLD, make_listing


def test_new_dataset_with_new_files_is_kept(settings):
    listing = make_listing()
    files = [RemoteFile(name="a.csv", creation_date=NEW)]
    verdict = assess(listing, files, settings, topic="signals")
    assert verdict.status is Status.KEPT
    assert verdict.earliest_date == NEW
    assert verdict.reasons == ["oldest date found is 2026-07-15"]


def test_dataset_updated_before_cutoff_is_quarantined(settings):
    verdict = assess(make_listing(last_updated=OLD), [], settings, topic="signals")
    assert verdict.status is Status.QUARANTINED
    assert verdict.reasons == ["TEMPORAL: last updated 2023-03-10, before the 2026-06-01 cutoff"]


def test_dataset_without_any_date_is_quarantined(settings):
    verdict = assess(make_listing(last_updated=None), [], settings, topic="signals")
    assert verdict.status is Status.QUARANTINED
    assert "can't be checked" in verdict.reasons[0]


def test_recent_update_to_old_data_is_quarantined(settings):
    """The re-upload case: last_updated is new, but a file is years old."""
    files = [
        RemoteFile(name="new.csv", creation_date=NEW),
        RemoteFile(name="old.csv", creation_date=OLD),
    ]
    verdict = assess(make_listing(), files, settings, topic="signals")
    assert verdict.status is Status.QUARANTINED
    assert verdict.earliest_date == OLD
    assert "date back to 2023-03-10" in verdict.reasons[0]


def test_old_version_dates_count_too(settings):
    verdict = assess(make_listing(version_dates=[OLD]), [], settings, topic="signals")
    assert verdict.status is Status.QUARANTINED


def test_naive_dates_from_the_api_compare_as_utc(settings):
    naive_new = datetime(2026, 7, 1)  # the Kaggle API returns dates without a time zone
    verdict = assess(make_listing(last_updated=naive_new), [], settings, topic="signals")
    assert verdict.status is Status.KEPT
    assert verdict.earliest_date == datetime(2026, 7, 1, tzinfo=UTC)


def test_every_reason_is_recorded_not_just_the_first(settings):
    listing = make_listing(last_updated=OLD, license="CC-BY-NC-SA-4.0")
    reasons = prefilter(listing, settings)
    assert [r.split(":")[0] for r in reasons] == ["TEMPORAL", "LICENSE"]


def test_temporal_reason_is_not_repeated_by_history_check(settings):
    files = [RemoteFile(name="a.csv", creation_date=OLD)]
    verdict = assess(make_listing(last_updated=OLD), files, settings, topic="signals")
    assert len(verdict.reasons) == 1


def test_license_matches_whole_words():
    blocked = ["NC", "ND"]
    assert license_reason("CC-BY-NC-SA-4.0", blocked)
    assert license_reason("CC BY-ND 4.0", blocked)
    assert license_reason("CC0-1.0", blocked) is None
    assert license_reason("CC-BY-4.0", blocked) is None


def test_missing_license_counts_as_unknown():
    assert license_reason(None, ["NC"]) is None
    assert license_reason(None, ["UNKNOWN"]) == "LICENSE: unknown (UNKNOWN not allowed)"


def test_off_topic_dataset_is_quarantined(settings):
    listing = make_listing("bob/school-map", title="Bengaluru School Map")
    verdict = assess(listing, [], settings, topic="linear algebra")
    assert verdict.status is Status.QUARANTINED
    assert verdict.reasons == [
        "RELEVANCE: 'linear algebra' scored 0 of 3 needed (no keywords found)"
    ]


def test_description_can_prove_relevance(settings):
    listing = make_listing("rahman/math", title="math_problem_solutions")
    details = Details(description="Linear algebra drills: eigenvalues of 3x3 matrices, by hand.")
    verdict = assess(listing, [], settings, topic="linear algebra", details=details)
    assert verdict.status is Status.KEPT
    assert verdict.matched_keywords == ["linear algebra", "matrices", "eigenvalue"]


def test_min_relevance_score_zero_turns_relevance_off(settings):
    settings = settings.model_copy(update={"min_relevance_score": 0})
    listing = make_listing("bob/school-map", title="Bengaluru School Map")
    assert assess(listing, [], settings, topic="linear algebra").status is Status.KEPT
