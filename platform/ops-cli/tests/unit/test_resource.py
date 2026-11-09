"""The resource package beside an operator: what is there, and getting it out.

`operator resource` is a subcomponent, so the first claim here is a shape claim — it is
reachable that way and no other. The rest is the loader's own vocabulary
reaching the terminal intact: a level that no package declares is refused in help rather
than at runtime, and an operator with no package gets the library's own stable code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli


def body(output: str) -> dict[str, Any]:
    return json.loads(output)


# ------------------------------------------------------------ the subcomponent --
def test_resource_is_reachable_only_under_operator(runner: CliRunner) -> None:
    assert runner.invoke(cli, ["operator", "resource", "list"]).exit_code == 0
    assert runner.invoke(cli, ["resource", "list"]).exit_code == config.EXIT_USAGE


def test_resource_is_a_group_under_operator_and_holds_three_actions() -> None:
    operator = cli.commands["operator"]
    assert isinstance(operator, click.Group)
    resource = operator.commands["resource"]
    assert isinstance(resource, click.Group)
    assert sorted(resource.commands) == ["export", "inspect", "list"]


# --------------------------------------------------------------------- list --
def test_list_reports_the_operators_that_ship_a_package(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["operator", "resource", "list", "--format", "json"])
    assert result.exit_code == 0, result.output
    found = body(result.stdout)
    assert found["count"] > 0
    assert "select@2.0.0" in found["operators"]


# ------------------------------------------------------------------ inspect --
def test_inspect_reports_the_kinds_and_levels_a_package_declares(runner: CliRunner) -> None:
    result = runner.invoke(
        cli, ["operator", "resource", "inspect", "select@2.0.0", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    resource = body(result.stdout)["resource"]
    assert resource["operator_id"] == "select@2.0.0"
    assert "guide" in resource["declared_kinds"]
    assert resource["declared_levels"] == [2, 3]


def test_inspect_takes_a_bare_name_and_says_what_it_resolved_to(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["operator", "resource", "inspect", "select"])
    assert result.exit_code == 0, result.output
    assert "select resolved to select@2.0.0" in result.stderr


# ------------------------------------------------------------------- export --
def test_export_writes_the_guide_to_standard_output(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["operator", "resource", "export", "select@2.0.0"])
    assert result.exit_code == 0, result.output
    assert result.stdout.lstrip().startswith("#")
    assert "select@2.0.0" in result.stdout


def test_level_three_adds_the_worked_examples(runner: CliRunner) -> None:
    two = runner.invoke(cli, ["operator", "resource", "export", "select@2.0.0"]).stdout
    three = runner.invoke(
        cli, ["operator", "resource", "export", "select@2.0.0", "--level", "3"]
    ).stdout
    assert three.startswith(two.rstrip("\n"))
    assert len(three) > len(two)


def test_export_writes_a_file_when_it_is_asked_to(runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "select.md"
    result = runner.invoke(
        cli, ["operator", "resource", "export", "select@2.0.0", "--output-file", str(target)]
    )
    assert result.exit_code == 0, result.output
    assert target.read_text(encoding="utf-8").lstrip().startswith("#")


def test_an_overwrite_refuses_rather_than_blocking_with_nothing_to_ask(
    runner: CliRunner, tmp_path: Path
) -> None:
    target = tmp_path / "select.md"
    target.write_text("keep me", encoding="utf-8")
    result = runner.invoke(
        cli, ["operator", "resource", "export", "select@2.0.0", "--output-file", str(target)]
    )
    assert result.exit_code == config.EXIT_USAGE
    assert "--confirm" in result.stderr
    assert target.read_text(encoding="utf-8") == "keep me"


def test_confirm_skips_the_question(runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "select.md"
    target.write_text("replace me", encoding="utf-8")
    result = runner.invoke(
        cli,
        [
            "operator",
            "resource",
            "export",
            "select@2.0.0",
            "--output-file",
            str(target),
            "--confirm",
        ],
    )
    assert result.exit_code == 0, result.output
    assert target.read_text(encoding="utf-8") != "replace me"


def test_declining_the_overwrite_changes_nothing_and_is_not_a_failure(
    runner: CliRunner, tmp_path: Path
) -> None:
    target = tmp_path / "select.md"
    target.write_text("keep me", encoding="utf-8")
    result = runner.invoke(
        cli,
        ["operator", "resource", "export", "select@2.0.0", "--output-file", str(target)],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    assert target.read_text(encoding="utf-8") == "keep me"


def test_a_level_no_package_declares_is_refused_from_the_closed_set(runner: CliRunner) -> None:
    """The library raises NOT_AVAILABLE for level 4; the choice says so in help instead."""
    result = runner.invoke(cli, ["operator", "resource", "export", "select@2.0.0", "--level", "4"])
    assert result.exit_code == config.EXIT_USAGE


def test_export_has_no_format_option() -> None:
    """An export emits the artifact; re-encoding Markdown as a table would not be one."""
    operator = cli.commands["operator"]
    assert isinstance(operator, click.Group)
    resource = operator.commands["resource"]
    assert isinstance(resource, click.Group)
    export = resource.commands["export"]
    assert not any("--format" in parameter.opts for parameter in export.params)


@pytest.mark.parametrize("action", ["inspect", "export"])
def test_an_operator_with_no_package_is_the_librarys_own_failure(
    action: str, runner: CliRunner
) -> None:
    result = runner.invoke(
        cli, ["operator", "resource", action, "avg@1.0.0", "--catalog", "history"]
    )
    assert result.exit_code == config.EXIT_RESOURCE
    assert "OperatorSkillLoadError" in result.stderr
