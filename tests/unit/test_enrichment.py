from harvester.enrichment.discussions import normalize_thread_urls, strip_icon_labels
from harvester.enrichment.hints import find_edge_case_hints
from harvester.enrichment.robots import parse_robots
from harvester.models import Thread

BASE = "https://www.kaggle.com/datasets/alice/data/discussion"


def thread(text: str) -> Thread:
    return Thread(url="u", title="t", text=text)


def test_hints_pick_out_warning_sentences():
    t = thread(
        "Thanks for sharing this. Be careful: column 3 is in millivolts, not volts. "
        "Great work overall!\nThere are NaNs in the last 200 rows of the file."
    )
    assert find_edge_case_hints([t]) == [
        "Be careful: column 3 is in millivolts, not volts.",
        "There are NaNs in the last 200 rows of the file.",
    ]


def test_hints_skip_short_and_duplicate_sentences_and_respect_the_limit():
    t = thread("Bug. " + "This row is wrong and should be fixed. " * 3)
    assert find_edge_case_hints([t, t]) == ["This row is wrong and should be fixed."]
    many = thread("\n".join(f"Row {i} has a missing value here." for i in range(20)))
    assert len(find_edge_case_hints([many], limit=5)) == 5


def test_thread_urls_are_cleaned_and_deduplicated():
    hrefs = [
        f"{BASE}/123?sort=new",
        f"{BASE}/123#comment-9",
        f"{BASE}/456/",
        f"{BASE}?sort=hotness",  # the list page itself, not a thread
        "https://www.kaggle.com/datasets/alice/data",
    ]
    assert normalize_thread_urls(hrefs) == [f"{BASE}/123", f"{BASE}/456"]


def test_robots_404_means_no_rules():
    rules = parse_robots(404, "", "")
    assert rules is not None
    assert rules.can_fetch("*", BASE)


def test_robots_html_page_is_treated_as_no_rules():
    """What kaggle.com actually does: /robots.txt returns its home page."""
    rules = parse_robots(200, "text/html; charset=utf-8", "<html>Disallow: /</html>")
    assert rules is not None
    assert rules.can_fetch("*", BASE)


def test_robots_real_file_is_obeyed():
    body = "User-agent: *\nDisallow: /datasets/\n"
    rules = parse_robots(200, "text/plain", body)
    assert rules is not None
    assert not rules.can_fetch("*", BASE)
    assert rules.can_fetch("*", "https://www.kaggle.com/competitions")


def test_robots_server_error_means_stay_out():
    assert parse_robots(503, "text/plain", "") is None


def test_icon_labels_are_removed_but_real_text_is_kept():
    text = "Alice · Posted 2 years ago\narrow_drop_up50\nmore_vert\nUse max_iter=500 here.\nreply"
    assert strip_icon_labels(text) == "Alice · Posted 2 years ago\nUse max_iter=500 here."
