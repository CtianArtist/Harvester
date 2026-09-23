from typer.testing import CliRunner

from harvester import cli
from harvester.models import RemoteFile
from harvester.sources.kaggle import KaggleAuthError
from tests.conftest import NEW, FakeSource, make_listing

runner = CliRunner()


def test_run_uses_cli_overrides(tmp_path, monkeypatch):
    source = FakeSource(
        listings={"optimization": [make_listing("a/b")]},
        files={"a/b": [RemoteFile(name="f.csv", total_bytes=1, creation_date=NEW)]},
    )
    monkeypatch.setattr(cli.KaggleSource, "connect", classmethod(lambda cls: source))
    out = tmp_path / "out"

    result = runner.invoke(
        cli.app,
        [
            "run",
            "-t",
            "optimization",
            "--cutoff",
            "2026-01-01",
            "-o",
            str(out),
            "--no-download",
            "--no-scrape",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Done: 1 kept, 0 quarantined" in result.output
    assert (out / "accepted.jsonl").exists()


def test_bad_settings_exit_with_code_2(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("per_topic: 99\n")
    result = runner.invoke(cli.app, ["run", "--config", str(bad)])
    assert result.exit_code == 2
    assert "per_topic" in result.output


def test_login_failure_exits_with_code_1(tmp_path, monkeypatch):
    def fail(cls):
        raise KaggleAuthError("no token")

    monkeypatch.setattr(cli.KaggleSource, "connect", classmethod(fail))
    result = runner.invoke(cli.app, ["run", "-o", str(tmp_path)])
    assert result.exit_code == 1
    assert "no token" in result.output
