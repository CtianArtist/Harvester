"""Command-line entry point: `harvester run`."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from pydantic import ValidationError

from harvester import pipeline
from harvester.config import load_settings
from harvester.sources.kaggle import KaggleAuthError, KaggleSource

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def main() -> None:
    """Collect recent, niche STEM datasets for contamination-resistant AI benchmarks."""


@app.command()
def run(
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="YAML settings file (see config/).")
    ] = None,
    topic: Annotated[
        list[str] | None, typer.Option("--topic", "-t", help="Topic to search. Repeat for more.")
    ] = None,
    cutoff: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Quarantine anything dated before this."),
    ] = None,
    per_topic: Annotated[
        int | None, typer.Option(help="Search results to check per topic (1-20).")
    ] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output folder.")] = None,
    download: Annotated[
        bool, typer.Option("--download/--no-download", help="Download kept datasets.")
    ] = True,
    scrape: Annotated[
        bool, typer.Option("--scrape/--no-scrape", help="Read discussion threads.")
    ] = True,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Search, filter, download and enrich datasets, then save the results."""
    overrides: dict[str, Any] = {
        "topics": topic,
        "cutoff": cutoff.date() if cutoff else None,
        "per_topic": per_topic,
        "output_dir": output,
    }
    try:
        settings = load_settings(config, {k: v for k, v in overrides.items() if v is not None})
    except (ValidationError, OSError, yaml.YAMLError) as e:
        typer.secho(f"Bad settings:\n{e}", err=True, fg="red")
        raise typer.Exit(2) from None

    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(message)s")

    try:
        source = KaggleSource.connect()
    except KaggleAuthError as e:
        typer.secho(str(e), err=True, fg="red")
        raise typer.Exit(1) from None

    result = pipeline.run(settings, source, download=download, scrape=scrape)
    typer.echo(
        f"\nDone: {len(result.kept)} kept, {len(result.quarantined)} quarantined. "
        f"Results are in {settings.output_dir}/"
    )
