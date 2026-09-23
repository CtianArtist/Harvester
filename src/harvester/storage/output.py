"""Where results land on disk.

<output_dir>/
  raw/<owner>__<dataset>/   downloaded files
  accepted.jsonl            one kept Candidate per line
  quarantine.jsonl          one quarantined Candidate per line, with reasons
  run_summary.json          what this run did
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from harvester.config import Settings
from harvester.models import Candidate
from harvester.utils import safe_dirname


def raw_dir(output_dir: Path, ref: str) -> Path:
    return output_dir / "raw" / safe_dirname(ref)


def save_results(cands: list[Candidate], settings: Settings) -> None:
    out = settings.output_dir
    out.mkdir(parents=True, exist_ok=True)
    kept = [c for c in cands if c.kept]
    held = [c for c in cands if not c.kept]
    for filename, rows in (("accepted.jsonl", kept), ("quarantine.jsonl", held)):
        with open(out / filename, "w", encoding="utf-8") as fh:
            for c in rows:
                fh.write(c.model_dump_json() + "\n")

    summary = {
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "cutoff": settings.cutoff.isoformat(),
        "topics": settings.topics,
        "kept": len(kept),
        "quarantined": len(held),
    }
    (out / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
