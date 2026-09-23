# Harvester

Collects **recent, niche STEM datasets** for building AI coding benchmarks that
models can't have memorized.

## Why

Benchmarks mined from public repositories leak. SWE-bench-style tasks come from
public pull requests, so both the problem and its fix are likely in a model's
pretraining data, and agents have been caught reading the reference patch
straight out of `git log`. A benchmark only measures reasoning if its data is
newer than the model under test and hasn't been seen before.

Harvester finds candidate data under that constraint and keeps an auditable
record of every decision it makes.

## What it does

```
discover ──► prefilter ──► list files ──► assess ──► download ──► enrich ──► save
 (search,     (date and      (sizes and     (oldest     (size-      (discussion  (accepted /
  newest       license,       creation       date wins)  bounded,    threads,     quarantine
  first)       no extra       dates)                     zip-bomb    edge-case    + reasons)
               API calls)                                 safe)       hints)
```

- **Temporal filtering.** Anything dated before the cutoff is quarantined. A
  dataset is judged by the *oldest* date found on any of its files or versions,
  so an old dataset with a fresh upload doesn't slip through.
- **License guard.** Non-commercial or no-derivatives licenses are quarantined
  up front (configurable), because benchmark data has to be redistributable.
- **Bounded downloads.** File and dataset size caps are checked against the
  listed size before downloading, then against the real size after. Zip
  archives are measured from their index *before* extraction.
- **Discussion enrichment.** Kaggle's API doesn't expose discussions and its
  pages are drawn with JavaScript, so a headless browser (Playwright) reads
  them, slowly and a few tabs at a time. Sentences that warn about traps in the
  data are pulled out as edge-case hints.
- **Every quarantine has a reason**, such as
  `TEMPORAL: updated recently, but parts of it date back to 2023-03-10` or
  `LICENSE: CC-BY-NC-4.0 (NC not allowed)`.

Dates are a strong signal, not proof: someone can upload years-old data as a
brand-new dataset. Near-duplicate detection against known corpora is on the
roadmap for that reason.

## Quick start

Needs Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium          # only needed for discussion scraping
```

Create an API token at <https://www.kaggle.com/settings/api>, then either set
`KAGGLE_API_TOKEN` or save it to `~/.kaggle/access_token` (an older
`~/.kaggle/kaggle.json` also works).

```bash
harvester run --no-download --no-scrape          # dates and licenses only: fast
harvester run -t "signal processing" -t optimization --cutoff 2026-03-01
harvester run --config my-settings.yaml
```

All settings, with comments, are in [config/default.yaml](config/default.yaml).

## Output

```
data/
  raw/<owner>__<dataset>/   downloaded files
  accepted.jsonl            one kept dataset per line
  quarantine.jsonl          one quarantined dataset per line, with reasons
  run_summary.json
```

## Project layout

```
src/harvester/
  cli.py                  `harvester run`
  config.py               typed settings (pydantic), loaded from YAML
  models.py               Listing, RemoteFile, Verdict, Candidate
  pipeline.py             runs the stages in order
  download.py             size-bounded downloads
  sources/
    base.py               the DatasetSource protocol every source implements
    kaggle/               the official Kaggle API, behind that protocol
  contamination/
    temporal.py           date checks
    verdict.py            combines every check into keep / quarantine
  guards/
    size.py               pre/post-download size checks, zip-bomb safe
    license.py
  enrichment/
    discussions.py        Playwright discussion reader
    robots.py             robots.txt handling
    hints.py              edge-case sentence extraction
  storage/output.py       on-disk layout
tests/                    unit + end-to-end, all offline
prototype/                the original single-file script, kept for reference
docs/                     architecture and design decisions
```

The pipeline only talks to the `DatasetSource` protocol, so Kaggle is one
plugin, and the tests run the whole pipeline against a fake source with no
network access.

## Development

```bash
pytest                 # all offline
ruff check . && ruff format --check .
mypy
```

## Roadmap

- [ ] Run manifest (SQLite) so runs are resumable and incremental
- [ ] Near-duplicate detection (MinHash) against older public corpora
- [ ] Recorded Kaggle discussion pages as test fixtures
- [ ] Second source (Hugging Face Hub) to prove the source interface
- [ ] Cutoff presets per model (`--cutoff-model ...`)
