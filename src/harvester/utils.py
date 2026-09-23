"""Small helpers shared across the package."""

from __future__ import annotations

from datetime import UTC, datetime

MB = 1024 * 1024


def as_utc(dt: datetime | str | None) -> datetime | None:
    """Kaggle's dates come without a time zone. Treat them as UTC so they compare correctly."""
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def mb(num_bytes: int | None) -> float:
    return round((num_bytes or 0) / MB, 2)


def tidy(text: str) -> str:
    """Remove blank lines and extra spaces."""
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def first_line(error: BaseException) -> str:
    """Error messages can be long; keep the first line."""
    text = str(error).strip()
    return text.splitlines()[0][:200] if text else type(error).__name__


def safe_dirname(ref: str) -> str:
    """Turn "owner/dataset-name" into a single folder name."""
    return ref.replace("/", "__")
