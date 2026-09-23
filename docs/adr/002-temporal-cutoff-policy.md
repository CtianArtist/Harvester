# 002: Temporal cutoff policy

**Status:** accepted

## Context

Data created before a model's training cutoff may be in its training data. A
fixed cutoff ("late 2024") goes stale as new models ship. And a dataset's
last-updated date is easy to refresh: uploading one new file to an old dataset
makes it look new.

## Decision

- The cutoff is a setting (`cutoff`), not a constant. It should be at least the
  training cutoff of the newest model being evaluated.
- A dataset is judged by the **oldest** date found across its last-updated
  date, every file's creation date, and every version's creation date.
- A dataset with no date at all is quarantined, since its age can't be checked.
- The cheap check (last-updated date from the search result) runs before the
  file listing, so obviously old datasets cost no extra API calls.

## Consequences

- Re-uploads of old data under an existing dataset are caught.
- Old data uploaded as a brand-new dataset is **not** caught by dates alone.
  That needs content-based checks (near-duplicate detection), tracked on the
  roadmap.
