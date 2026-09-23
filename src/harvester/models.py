"""Data shapes that move through the pipeline.

Sources turn their own API objects into `Listing` and `RemoteFile`, so the rest
of the pipeline never touches a Kaggle-specific type. Each dataset then becomes
one `Candidate`, which is what gets saved (one line of JSON per dataset).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from harvester.utils import as_utc, mb


class RemoteFile(BaseModel):
    """One file in a dataset, as the source describes it before download."""

    name: str
    total_bytes: int = 0
    creation_date: datetime | None = None

    @field_validator("creation_date")
    @classmethod
    def to_utc(cls, dt: datetime | None) -> datetime | None:
        return as_utc(dt)


class Listing(BaseModel):
    """What a source tells us about a dataset before we download anything."""

    ref: str  # "owner/dataset-name"
    title: str
    url: str
    subtitle: str = ""
    tags: list[str] = Field(default_factory=list)
    total_bytes: int = 0
    last_updated: datetime | None = None
    version_dates: list[datetime] = Field(default_factory=list)
    license: str | None = None

    @field_validator("last_updated")
    @classmethod
    def to_utc(cls, dt: datetime | None) -> datetime | None:
        return as_utc(dt)

    @field_validator("version_dates")
    @classmethod
    def all_to_utc(cls, dates: list[datetime]) -> list[datetime]:
        return [d for d in map(as_utc, dates) if d is not None]


class Details(BaseModel):
    """Text about a dataset that search results leave out, fetched only when needed."""

    description: str = ""
    keywords: list[str] = Field(default_factory=list)


class Status(StrEnum):
    KEPT = "kept"
    QUARANTINED = "quarantined"


class Verdict(BaseModel):
    """A keep/quarantine decision plus every reason behind it, so it can be audited later."""

    status: Status
    reasons: list[str]
    earliest_date: datetime | None = None
    matched_keywords: list[str] = Field(default_factory=list)

    @classmethod
    def quarantine(cls, *reasons: str) -> Verdict:
        return cls(status=Status.QUARANTINED, reasons=list(reasons))


class SavedFile(BaseModel):
    file: str
    mb: float


class SkippedFile(BaseModel):
    file: str
    mb: float
    why: str


class Thread(BaseModel):
    """A discussion thread. The source lists it; the browser fills in `text`."""

    url: str
    title: str
    posted_at: datetime | None = None
    author: str | None = None
    comment_count: int = 0
    votes: int = 0
    text: str = ""

    @field_validator("posted_at")
    @classmethod
    def to_utc(cls, dt: datetime | None) -> datetime | None:
        return as_utc(dt)


class ThreadIndex(BaseModel):
    """One page of a dataset's threads, plus how many there are in total."""

    total: int
    threads: list[Thread]


class Candidate(BaseModel):
    """Everything we learned about one dataset."""

    ref: str
    title: str
    url: str
    found_by_search: str
    tags: list[str]
    license: str | None
    listed_size_mb: float
    last_updated: datetime | None
    discussion_count: int | None = None  # None until the source has been asked
    earliest_date_seen: datetime | None = None
    status: Status | None = None
    reasons: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    files_downloaded: list[SavedFile] = Field(default_factory=list)
    files_skipped: list[SkippedFile] = Field(default_factory=list)
    discussions: list[Thread] = Field(default_factory=list)
    edge_case_hints: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    possible_question: str = ""  # left blank on purpose: writing test questions is the next phase

    @classmethod
    def from_listing(cls, listing: Listing, topic: str) -> Candidate:
        return cls(
            ref=listing.ref,
            title=listing.title,
            url=listing.url,
            found_by_search=topic,
            tags=listing.tags,
            license=listing.license,
            listed_size_mb=mb(listing.total_bytes),
            last_updated=listing.last_updated,
        )

    @property
    def kept(self) -> bool:
        return self.status == Status.KEPT

    def apply(self, verdict: Verdict) -> None:
        self.status = verdict.status
        self.reasons = verdict.reasons
        self.earliest_date_seen = verdict.earliest_date
        self.matched_keywords = verdict.matched_keywords
