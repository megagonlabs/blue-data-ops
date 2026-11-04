"""The two catalog views, the selection that picks one, and the view that is not offered.

`catalog` is this repository's `database`: the thing you select once so every later command
reads the same view. So the claims here are about the selection as much as about the views —
where it is written, which tiers outrank it, and what it does to the next command.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.catalog import TAG_AXES
from blue_data_ops_cli.commands import cli

ACTIVE_CARDS = 33
HISTORY_CARDS = 88


def payload(result_output: str) -> dict[str, Any]:
    return json.loads(result_output)


# ------------------------------------------------------------------- list --
def test_list_reports_both_views_and_their_sizes(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["catalog", "list", "--format", "json"])
    assert result.exit_code == 0, result.output
    catalogs = payload(result.stdout)["catalogs"]
    assert [entry["name"] for entry in catalogs] == list(config.CATALOGS)
    assert [entry["cards"] for entry in catalogs] == [ACTIVE_CARDS, HISTORY_CARDS]


def test_list_says_which_one_is_selected(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["catalog", "list", "--format", "json"])
    assert payload(result.stdout)["selected"] == "active"


def test_list_marks_the_selection_in_the_table(runner: CliRunner) -> None:
    assert runner.invoke(cli, ["catalog", "select", "history"]).exit_code == 0
    text = runner.invoke(cli, ["catalog", "list"]).stdout
    assert "history" in text
    assert "*" in text


# ---------------------------------------------------------------- inspect --
def test_inspect_defaults_to_the_selected_catalog(runner: CliRunner) -> None:
    assert runner.invoke(cli, ["catalog", "select", "history"]).exit_code == 0
    result = runner.invoke(cli, ["catalog", "inspect", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert payload(result.stdout)["catalog"]["name"] == "history"


def test_inspect_takes_the_view_as_a_bare_positional(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["catalog", "inspect", "history", "--format", "json"])
    assert result.exit_code == 0, result.output
    body = payload(result.stdout)["catalog"]
    assert body["name"] == "history"
    assert body["cards"] == HISTORY_CARDS
    assert payload(result.stdout)["selected"] == "active"


def test_inspect_groups_the_tags_by_the_librarys_own_axes(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["catalog", "inspect", "active", "--format", "json"])
    tags = payload(result.stdout)["catalog"]["tags"]
    assert list(tags) == list(TAG_AXES), "every axis is present and in the documented order"
    for axis, values in tags.items():
        assert values, axis
        assert all(value.startswith(f"{axis}-") for value in values), axis


def test_inspect_reports_the_version_spread(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["catalog", "inspect", "history", "--format", "json"])
    versions = payload(result.stdout)["catalog"]["versions"]
    assert sum(versions.values()) == HISTORY_CARDS
    assert versions == {"1.0.0": 33, "2.0.0": 33, "3.0.0": 21, "4.0.0": 1}


# ----------------------------------------------------------------- select --
def test_select_writes_the_profiles_own_selection_file(runner: CliRunner, cli_home: Path) -> None:
    assert runner.invoke(cli, ["catalog", "select", "history"]).exit_code == 0
    path = cli_home / "default" / ".selected.catalog"
    assert path.read_text(encoding="utf-8") == "history"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_selected_catalog_is_what_the_next_command_reads(runner: CliRunner) -> None:
    assert runner.invoke(cli, ["catalog", "select", "history"]).exit_code == 0
    result = runner.invoke(cli, ["operator", "list", "--format", "json"])
    assert payload(result.stdout)["count"] == HISTORY_CARDS


def test_the_selection_belongs_to_one_profile(runner: CliRunner, cli_home: Path) -> None:
    assert runner.invoke(cli, ["profile", "add", "staging"]).exit_code == 0
    selected = runner.invoke(cli, ["--profile", "staging", "catalog", "select", "history"])
    assert selected.exit_code == 0, selected.output
    assert not (cli_home / "default" / ".selected.catalog").exists()
    result = runner.invoke(cli, ["catalog", "inspect", "--format", "json"])
    assert payload(result.stdout)["catalog"]["name"] == "active"


def test_an_option_and_the_variable_both_outrank_the_selection(runner: CliRunner) -> None:
    assert runner.invoke(cli, ["catalog", "select", "history"]).exit_code == 0
    flagged = runner.invoke(cli, ["operator", "list", "--catalog", "active", "--format", "json"])
    assert payload(flagged.stdout)["count"] == ACTIVE_CARDS
    exported = runner.invoke(
        cli, ["operator", "list", "--format", "json"], env={"BLUE_DATA_OPS_CATALOG": "active"}
    )
    assert payload(exported.stdout)["count"] == ACTIVE_CARDS


# -------------------------------------------------------------- the third --
@pytest.mark.parametrize("command", [["catalog", "inspect", "raw"], ["catalog", "select", "raw"]])
def test_the_raw_view_is_refused_with_the_reason(command: list[str], runner: CliRunner) -> None:
    """`raw` is a name a reader of the library's own documentation will try."""
    result = runner.invoke(cli, command)
    assert result.exit_code == config.EXIT_USAGE
    assert "planning authority" in result.stderr


def test_a_name_that_is_not_a_catalog_is_a_usage_error(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["catalog", "inspect", "nonsense"])
    assert result.exit_code == config.EXIT_USAGE
    assert "ERROR: USAGE" in result.stderr
