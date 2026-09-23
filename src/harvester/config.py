"""Settings for a harvest run.

The defaults here are the source of truth. config/default.yaml mirrors them as
a template you can copy and edit; a test keeps the two in sync. Unknown keys
are rejected, so a typo in a YAML file fails loudly instead of being ignored.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from harvester.utils import MB


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DownloadLimits(_Strict):
    max_file_mb: PositiveInt = 200  # skip any single file bigger than this (after unzipping)
    # skip datasets bigger than this, and stop downloading past it
    max_dataset_mb: PositiveInt = 500

    @property
    def file_bytes(self) -> int:
        return self.max_file_mb * MB

    @property
    def dataset_bytes(self) -> int:
        return self.max_dataset_mb * MB


class ScrapeSettings(_Strict):
    threads_per_dataset: PositiveInt = 3
    max_chars_per_thread: PositiveInt = 5000
    # browser tabs loading at the same time (keep small to be polite)
    pages_at_once: PositiveInt = 2
    seconds_between_pages: float = Field(2.0, ge=0)  # pause before each page load, in each tab
    page_timeout_ms: PositiveInt = 30_000
    wait_for_content_ms: PositiveInt = 15_000  # how long to wait for JavaScript to draw content
    show_browser: bool = False  # True opens a visible window so you can watch it work
    # Which parts of a thread page to save: the post with its comments, and the
    # thread's title. Checked against kaggle.com in September 2026. If Kaggle
    # changes its layout and you get menu text (or nothing), run
    # `playwright codegen <a thread's URL>`, click the post, and copy the selector.
    thread_text_selector: str = '[data-testid="discussion-detail-render-tid"]'
    thread_title_selector: str = '[data-testid="discussions-topic-header"] h3'


class Settings(_Strict):
    topics: list[str] = Field(
        default_factory=lambda: [
            "linear algebra",
            "signal processing",
            "optimization",
            "reinforcement learning",
        ],
        min_length=1,
    )
    # Anything dated before this is quarantined. Set it to at least the training
    # cutoff of the newest model you plan to test, and move it forward over time.
    cutoff: date = date(2026, 6, 1)
    per_topic: int = Field(5, ge=1, le=20)  # search results to check per topic
    # License name parts that get a dataset quarantined, matched as whole words,
    # so "NC" catches "CC-BY-NC-SA-4.0". Add "UNKNOWN" to also reject unlicensed data.
    blocked_licenses: list[str] = Field(default_factory=lambda: ["NC", "ND"])
    output_dir: Path = Path("data")
    download: DownloadLimits = Field(default_factory=DownloadLimits)
    scrape: ScrapeSettings = Field(default_factory=ScrapeSettings)

    @property
    def cutoff_at(self) -> datetime:
        return datetime(self.cutoff.year, self.cutoff.month, self.cutoff.day, tzinfo=UTC)


def load_settings(path: Path | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    """Build settings from code defaults, then a YAML file (if given), then overrides."""
    data: dict[str, Any] = {}
    if path is not None:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.update(overrides or {})
    return Settings.model_validate(data)
