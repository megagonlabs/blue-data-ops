"""Three levels of help, and nothing documented that the runtime does not have.

`--help` is the only documentation a user reaches from inside the CLI, so three things are
checked: that each level exists and says something, that every option with a default or a
closed set shows it, and that nothing appears there which the command would refuse. The last
one is checked by comparing the text against the registered parameters rather than by
reading it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

# Every command whose usage is not obvious from its name and its one argument.
WORKED_EXAMPLES = [
    ["profile", "add"],
    ["profile", "remove"],
    ["profile", "config"],
    ["metadata", "inspect"],
]


def commands() -> list[tuple[list[str], click.Command]]:
    found: list[tuple[list[str], click.Command]] = []
    for name, group in cli.commands.items():
        assert isinstance(group, click.Group)
        for action, command in group.commands.items():
            found.append(([name, action], command))
    return found


def choices_of(parameter: click.Parameter) -> tuple[str, ...]:
    values: Any = getattr(parameter.type, "choices", ())
    return tuple(str(value) for value in values)


def help_text(runner: CliRunner, path: list[str]) -> str:
    result = runner.invoke(cli, [*path, "--help"], terminal_width=200)
    assert result.exit_code == 0, result.output
    return result.stdout


# ------------------------------------------------------------ three levels --
def test_the_root_help_describes_the_cli_and_names_its_components(runner: CliRunner) -> None:
    text = help_text(runner, [])
    assert config.PROGRAM in text
    for component in cli.commands:
        assert component in text


@pytest.mark.parametrize("component", sorted(cli.commands))
def test_a_component_help_describes_it_and_lists_its_actions(
    component: str, runner: CliRunner
) -> None:
    group = cli.commands[component]
    assert isinstance(group, click.Group)
    text = help_text(runner, [component])
    for action in group.commands:
        assert action in text


@pytest.mark.parametrize("path", [path for path, _ in commands()], ids=lambda p: "-".join(p))
def test_an_action_help_documents_its_parameters_and_options(
    path: list[str], runner: CliRunner
) -> None:
    text = help_text(runner, path)
    registered = next(c for p, c in commands() if p == path)
    for parameter in registered.params:
        if isinstance(parameter, click.Argument):
            assert parameter.name is not None
            assert parameter.name.upper() in text, f"{path} {parameter.name}"
            continue
        for spelling in parameter.opts:
            if spelling.startswith("--"):
                assert spelling in text, f"{path} {spelling}"


# ------------------------------------------------------- defaults and sets --
@pytest.mark.parametrize("path", [path for path, _ in commands()], ids=lambda p: "-".join(p))
def test_a_closed_set_shows_its_values_in_help(path: list[str], runner: CliRunner) -> None:
    """Allowed values are discoverable from the help rather than from a runtime refusal."""
    text = " ".join(help_text(runner, path).split())
    registered = next(c for p, c in commands() if p == path)
    for parameter in registered.params:
        if isinstance(parameter.type, click.Choice):
            assert "|".join(choices_of(parameter)) in text, f"{path} {parameter.opts}"


def test_the_two_options_with_a_resolved_default_say_where_it_comes_from(
    runner: CliRunner,
) -> None:
    """A default that is itself a lookup is not a value to print, so it is named instead."""
    text = " ".join(help_text(runner, ["metadata", "inspect"]).split())
    assert "BLUE_DATA_CLI_FORMAT" in text
    assert "the profile's selection, else active" in text


def test_profile_config_help_shows_closed_values_and_bounds(runner: CliRunner) -> None:
    text = " ".join(help_text(runner, ["profile", "config"]).split())
    for choices in ("table|json|nl", "active|history", "rule|openai", "memory|file|redis"):
        assert choices in text
    assert "finite and positive" in text
    assert "300 seconds" in text
    assert "256–16384" in text


@pytest.mark.parametrize("path", WORKED_EXAMPLES, ids=lambda p: "-".join(p))
def test_a_worked_example_is_present_where_the_usage_is_not_obvious(
    path: list[str], runner: CliRunner
) -> None:
    text = help_text(runner, path)
    assert f"{config.PROGRAM} {' '.join(path)}" in text


# ----------------------------------------------- nothing undocumented, both ways --
@pytest.mark.parametrize("path", [path for path, _ in commands()], ids=lambda p: "-".join(p))
def test_help_documents_no_option_the_command_does_not_have(
    path: list[str], runner: CliRunner
) -> None:
    """The other direction: a `--flag` in the prose that the parser would refuse."""
    text = help_text(runner, path)
    registered = next(c for p, c in commands() if p == path)
    declared = {
        spelling
        for parameter in registered.params
        for spelling in parameter.opts + parameter.secondary_opts
    }
    declared |= {"--help", "-h", "--version", "--profile"}
    mentioned = set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", text))
    assert mentioned <= declared, f"{path} documents {sorted(mentioned - declared)}"


def test_the_root_help_documents_no_option_the_root_does_not_have(runner: CliRunner) -> None:
    text = help_text(runner, [])
    declared = {spelling for parameter in cli.params for spelling in parameter.opts}
    declared |= {"--help", "--version"}
    mentioned = set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", text))
    assert mentioned <= declared, f"root documents {sorted(mentioned - declared)}"


# ------------------------------------------------------------- the version --
def test_version_exists_and_matches_the_packaged_version(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0, result.output
    declared = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.M)
    assert declared is not None
    assert result.stdout.strip() == f"{config.PROGRAM} {declared.group(1)}"


def test_family_terminology_reads_the_same_here_as_elsewhere(runner: CliRunner) -> None:
    """`profile`, `metadata`, `--format` and `--confirm` mean what they mean in the family."""
    root = help_text(runner, [])
    assert "profile" in root
    assert "metadata" in root
    assert "--format" in help_text(runner, ["profile", "list"])
    assert "--confirm" in help_text(runner, ["profile", "remove"])
