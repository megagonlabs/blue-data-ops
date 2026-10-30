"""Confirmation questions go to standard error, so ``--format json`` keeps stdout to one object.

Consent is unchanged: without ``--confirm`` or an interactive yes, nothing is replaced.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli

REQUEST: dict[str, Any] = {
    "goal": "average total of orders above 100",
    "discovery_queries": [
        {"text": "filter", "tags": ["capability-filter"]},
        {"text": "average", "tags": ["capability-average"]},
    ],
    "operator_attributes": {
        "select": {"operand_key": "total", "operand": ">", "operand_val": 100},
        "avg": {"avg_key": "total", "output_key": "average_total"},
    },
}
QUESTION = "Replace the stored pipeline 'nightly'"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def request_file(tmp_path: Path) -> str:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(REQUEST), encoding="utf-8")
    return str(path)


@pytest.fixture
def stored(runner: CliRunner, request_file: str, cli_home: Path, tmp_path: Path) -> Path:
    result = runner.invoke(cli, ["pipeline", "add", "nightly", "--request-file", request_file])
    assert result.exit_code == 0, result.output
    path = cli_home / "default" / "pipeline" / "nightly" / "pipeline.json"
    exported = tmp_path / "exported.json"
    exported.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def replacement(kind: str, request_file: str, tmp_path: Path) -> list[str]:
    if kind == "add":
        return ["pipeline", "add", "nightly", "--request-file", request_file]
    return ["pipeline", "import", "nightly", "--pipeline-file", str(tmp_path / "exported.json")]


@pytest.mark.parametrize("kind", ["add", "import"])
def test_json_replacement_without_a_terminal_is_one_usage_object(
    kind: str, runner: CliRunner, stored: Path, request_file: str, tmp_path: Path
) -> None:
    before = digest(stored)
    result = runner.invoke(cli, [*replacement(kind, request_file, tmp_path), "--format", "json"])
    assert result.exit_code == config.EXIT_USAGE
    document = json.loads(result.stdout)
    assert document["error"]["code"] == "USAGE"
    assert "--confirm" in document["error"]["message"]
    assert QUESTION not in result.stdout
    assert QUESTION in result.stderr
    assert digest(stored) == before


@pytest.mark.parametrize("kind", ["add", "import"])
def test_json_replacement_with_confirm_asks_nothing_and_replaces(
    kind: str, runner: CliRunner, stored: Path, request_file: str, tmp_path: Path
) -> None:
    result = runner.invoke(
        cli, [*replacement(kind, request_file, tmp_path), "--confirm", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    json.loads(result.stdout)
    assert QUESTION not in result.output


@pytest.mark.parametrize("kind", ["add", "import"])
def test_an_interactive_no_keeps_the_stored_pipeline(
    kind: str, runner: CliRunner, stored: Path, request_file: str, tmp_path: Path
) -> None:
    before = digest(stored)
    result = runner.invoke(cli, replacement(kind, request_file, tmp_path), input="n\n")
    assert result.exit_code == 0, result.output
    assert QUESTION in result.stderr
    assert QUESTION not in result.stdout
    assert digest(stored) == before


@pytest.mark.parametrize("kind", ["add", "import"])
def test_an_interactive_yes_replaces_after_the_question_on_stderr(
    kind: str, runner: CliRunner, stored: Path, request_file: str, tmp_path: Path
) -> None:
    before = stored.stat()
    result = runner.invoke(cli, replacement(kind, request_file, tmp_path), input="y\n")
    assert result.exit_code == 0, result.output
    assert QUESTION in result.stderr
    assert QUESTION not in result.stdout
    after = stored.stat()
    assert (after.st_ino, after.st_mtime_ns) != (before.st_ino, before.st_mtime_ns)
