"""Every format on every command that returns a result, and the channel split under each.

The renderer is one implementation, so these check the claim the renderer makes rather than
each command's own printing: a result goes to standard output in the format that was asked
for, and nothing else goes there at all.
"""

from __future__ import annotations

import io
import json

import pytest
from click.testing import CliRunner
from rich.console import Console

from blue_data_ops_cli import formats
from blue_data_ops_cli.commands import cli
from blue_data_ops_cli.formats import FORMATS

RESULT_COMMANDS: list[list[str]] = [
    ["profile", "list"],
    ["profile", "inspect"],
    ["metadata", "inspect"],
]


def render_to_string(result: formats.Result, fmt: str, capsys: pytest.CaptureFixture[str]) -> str:
    """Whatever the renderer wrote, from either of the two writers it uses.

    A table goes through a Rich console the caller can hand in; `json` and `nl` go through
    `click.echo`, which writes to the process stream.
    """
    buffer = io.StringIO()
    console = Console(file=buffer, markup=False, highlight=False, width=120)
    capsys.readouterr()
    formats.render(result, fmt, out=console)
    return buffer.getvalue() + capsys.readouterr().out


# ------------------------------------------------------------- the formats --
def test_the_advertised_formats_are_the_guide_s_three() -> None:
    assert FORMATS == ("table", "json", "nl")


@pytest.mark.parametrize("command", RESULT_COMMANDS, ids=lambda c: "-".join(c[:2]))
def test_json_is_one_object_and_nothing_else(command: list[str], runner: CliRunner) -> None:
    result = runner.invoke(cli, [*command, "--format", "json"])
    assert result.exit_code == 0, result.output
    published = json.loads(result.stdout)
    assert isinstance(published, dict)
    assert result.stdout.strip().startswith("{")
    assert result.stdout.strip().endswith("}")


@pytest.mark.parametrize("command", RESULT_COMMANDS, ids=lambda c: "-".join(c[:2]))
def test_json_carries_a_payload_key_named_for_the_resource(
    command: list[str], runner: CliRunner
) -> None:
    expected = {
        "profile list": "profiles",
        "profile inspect": "parameters",
        "metadata inspect": "metadata",
    }[" ".join(command)]
    published = json.loads(runner.invoke(cli, [*command, "--format", "json"]).stdout)
    assert expected in published


@pytest.mark.parametrize("command", RESULT_COMMANDS, ids=lambda c: "-".join(c[:2]))
def test_a_table_has_named_headers(command: list[str], runner: CliRunner) -> None:
    result = runner.invoke(cli, [*command, "--format", "table"])
    assert result.exit_code == 0, result.output
    headers = {
        "profile list": ("Profile", "Selected", "Configured"),
        "profile inspect": ("Parameter", "Value", "Source"),
        "metadata inspect": ("key", "value"),
    }[" ".join(command)]
    for header in headers:
        assert header in result.stdout


@pytest.mark.parametrize("command", RESULT_COMMANDS, ids=lambda c: "-".join(c[:2]))
def test_nl_is_a_sentence_rather_than_a_dump(command: list[str], runner: CliRunner) -> None:
    result = runner.invoke(cli, [*command, "--format", "nl"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip().endswith(".")
    assert "┏" not in result.stdout


@pytest.mark.parametrize("command", RESULT_COMMANDS, ids=lambda c: "-".join(c[:2]))
@pytest.mark.parametrize("fmt", FORMATS)
def test_nothing_but_the_result_reaches_stdout(
    command: list[str], fmt: str, runner: CliRunner
) -> None:
    """A JSON consumer reads standard output; every note, warning and spinner is elsewhere."""
    result = runner.invoke(cli, [*command, "--format", fmt])
    assert result.exit_code == 0, result.output
    if fmt == "json":
        json.loads(result.stdout)
    assert "warning:" not in result.stdout


def test_a_spinner_is_suppressed_outright_under_json(
    runner: CliRunner, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both the terminal check and the format check, because leaving it to the first one is
    how a JSON pipe acquires a spinner on a machine whose stderr happens to be a terminal."""
    from blue_data_ops_cli import config

    with config.Reporter("json").status("Running…"):
        pass
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------- the renderer --
def test_a_control_character_never_reaches_a_cell(capsys: pytest.CaptureFixture[str]) -> None:
    """Operator output is untrusted, and an escape sequence in it walks the cursor."""
    result = formats.tabular(
        ("Name",), [{"Name": "ev\x1b[2J\x1b[31mil"}], {"rows": ["ev\x1b[2J\x1b[31mil"]}
    )
    for fmt in FORMATS:
        assert "\x1b" not in render_to_string(result, fmt, capsys), fmt


def test_a_control_character_in_a_json_value_is_stripped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = formats.tabular(("Name",), [], {"name": "ev\x1b[2Jil"})
    assert "\\u001b" not in render_to_string(result, "json", capsys)


def test_a_column_name_holding_a_control_character_still_reads_its_records(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Stripping the name where the columns were chosen turned the lookup into a miss."""
    result = formats.tabular(("Na\x1bme",), [{"Na\x1bme": "Ada"}], {})
    assert "Ada" in render_to_string(result, "table", capsys)


def test_an_empty_table_says_what_to_run_instead_of_drawing_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = formats.tabular(("Name",), [], {}, empty="(nothing yet — run `blue-ops profile add`)")
    assert "nothing yet" in render_to_string(result, "table", capsys)


def test_nl_falls_back_to_a_paragraph_when_a_command_supplies_no_sentence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No command can answer `--format nl` with nothing."""
    result = formats.tabular(("Name",), [{"Name": "Ada"}], {})
    assert "Name Ada" in render_to_string(result, "nl", capsys)
