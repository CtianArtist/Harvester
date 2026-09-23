# Architecture

## Goal

Produce candidate datasets for AI benchmarks that a model under test is
unlikely to have seen in training, with a record of why each dataset was kept
or rejected.

## Stages

| Stage | Module | Network? | Can reject? |
|---|---|---|---|
| Discover | `sources/<name>/source.py` → `search` | API | no |
| Prefilter | `contamination/verdict.py` → `prefilter` | no | date, license |
| List files | `sources/<name>/source.py` → `list_files` | API | on API error |
| Describe | `sources/<name>/source.py` → `details` (only if the headline isn't on topic) | API | no |
| Assess | `contamination/verdict.py` → `assess` | no | oldest date, relevance |
| Download | `download.py` + `guards/size.py` | API | per file, by size |
| List threads | `sources/<name>/source.py` → `list_threads` | API | no |
| Read threads | `enrichment/discussions.py` (only if any kept dataset has threads) | browser | no |
| Save | `storage/output.py` | no | no |

Stages are ordered by cost: the checks that need nothing but the search
result run first, so a rejected dataset costs one search result and zero
further requests.

## Principles

**Decisions are pure functions.** `prefilter` and `assess` take data and return
a `Verdict`; they never do I/O. The contamination rules can be tested
exhaustively without a network and explained line by line.

**Sources sit behind a protocol.** The pipeline only knows `DatasetSource`
(`search`, `list_files`, `download_file`, `details`, `list_threads`). Kaggle types are converted
to `Listing` and `RemoteFile` at the edge (`sources/kaggle/source.py`), so the
rest of the code never imports `kaggle`. Tests run the whole pipeline against a
`FakeSource`.

**Every rejection carries a reason.** Reasons are prefixed with the check that
produced them (`TEMPORAL:`, `LICENSE:`, `RELEVANCE:`, `SOURCE:`) and all of them are kept,
not just the first, so a quarantine file can be audited or re-filtered later.

**Fail per item, not per run.** A failed search, file listing, download or
browser session is recorded on the affected dataset and the run continues.

## Known limits

- Dates are evidence, not proof: an old dataset re-uploaded as new passes the
  temporal check. Near-duplicate detection is the planned answer.
- Reading thread text depends on Kaggle's page structure. The selector is a
  setting, not code, was last checked in September 2026, and a run warns when
  it stops matching. Finding threads does not: that uses the official API.
- Relevance trusts the dataset owner's title and tags. A dataset tagged with a
  topic it isn't really about still scores as strong evidence.
- Each run overwrites the JSONL output. A SQLite manifest (planned) will make
  runs incremental.
