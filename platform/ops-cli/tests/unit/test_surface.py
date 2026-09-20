"""The shape of the CLI itself: the tree, the version, the formats, the precedence chain.

These are the claims the compliance checklist makes about every command at once, so they are
checked against every command at once rather than one at a time in the command's own file.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli
from blue_data_ops_cli.formats import FORMATS

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

TREE = {
    "profile": ["add", "remove", "list", "config", "inspect", "select"],
    "catalog": ["list", "inspect", "select"],
    "operator": ["list", "search", "inspect", "run", "resource"],
    "pipeline": ["add", "import", "export", "list", "inspect", "remove", "run"],
    "metadata": ["inspect"],
}

# Every command that returns a result, and therefore carries `--format`.
RESULT_COMMANDS: list[list[str]] = [
    ["profile", "list"],
    ["profile", "inspect"],
    ["catalog", "list"],
    ["catalog", "inspect"],
    ["operator", "list"],
    ["operator", "search", "average"],
    ["operator", "inspect", "select@2.0.0"],
    ["operator", "resource", "list"],
    ["operator", "resource", "inspect", "select@2.0.0"],
    ["pipeline", "list"],
    ["metadata", "inspect"],
]

# Every command that reads the operator catalog, and therefore carries `--catalog`.
CATALOG_COMMANDS: list[list[str]] = [
    ["operator", "list"],
    ["operator", "search"],
    ["operator", "inspect"],
    ["operator", "run"],
    ["operator", "resource", "list"],
    ["operator", "resource", "inspect"],
    ["operator", "resource", "export"],
    ["pipeline", "add"],
    ["pipeline", "import"],
    ["pipeline", "inspect"],
    ["pipeline", "run"],
    ["metadata", "inspect"],
]


def leaves(group: click.Group) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for name, command in group.commands.items():
        assert isinstance(command, click.Group), f"{name} is not a component group"
        found[name] = sorted(command.commands)
    return found


def choices_of(parameter: click.Parameter) -> tuple[str, ...]:
    """The values a closed-set option accepts.

    Read through `getattr` because Click made `Choice` generic after the floor this package
    declares, so the attribute's element type is not knowable from the declared dependency.
    """
    values: Any = getattr(parameter.type, "choices", ())
    return tuple(str(value) for value in values)


def option_named(command: click.Command, spelling: str) -> click.Parameter:
    for parameter in command.params:
        if spelling in parameter.opts:
            return parameter
    raise AssertionError(f"{command.name} has no {spelling}")


def every_command() -> list[tuple[str, click.Command]]:
    found: list[tuple[str, click.Command]] = []
    for name, group in cli.commands.items():
        assert isinstance(group, click.Group)
        for action, command in group.commands.items():
            found.append((f"{name} {action}", command))
    return found


# ----------------------------------------------------------------- the tree --
def test_the_tree_is_the_declared_components_and_actions() -> None:
    assert leaves(cli) == {name: sorted(actions) for name, actions in TREE.items()}


@pytest.mark.parametrize("component", sorted(TREE))
def test_the_root_help_names_every_component(component: str, runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0, result.output
    assert component in result.stdout


@pytest.mark.parametrize(
    ("component", "action"),
    [(component, action) for component, actions in TREE.items() for action in actions],
)
def test_every_command_has_help_of_its_own(component: str, action: str, runner: CliRunner) -> None:
    result = runner.invoke(cli, [component, action, "--help"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip()


def test_the_root_help_states_the_precedence_chain(runner: CliRunner) -> None:
    text = runner.invoke(cli, ["--help"]).stdout
    for tier in ("command option", "environment", "profile", "default"):
        assert tier in text


def test_help_is_reachable_by_both_spellings(runner: CliRunner) -> None:
    assert runner.invoke(cli, ["-h"]).exit_code == 0
    assert runner.invoke(cli, ["--help"]).exit_code == 0


def test_every_multi_word_option_is_lowercase_and_hyphenated() -> None:
    for label, command in every_command():
        for parameter in command.params:
            for spelling in parameter.opts:
                if not spelling.startswith("--"):
                    continue
                assert spelling == spelling.lower(), f"{label} {spelling}"
                assert "_" not in spelling, f"{label} {spelling}"


def test_every_boolean_option_is_a_bare_flag_defaulting_to_false() -> None:
    """No `--x/--no-x` pair anywhere: no boolean in this CLI needs a third, unset state."""
    for label, command in every_command():
        for parameter in command.params:
            if not isinstance(parameter, click.Option) or not parameter.is_flag:
                continue
            assert parameter.default is False, f"{label} {parameter.opts}"
            assert not parameter.secondary_opts, f"{label} {parameter.opts}"


def test_every_resource_is_a_bare_positional() -> None:
    """The guide's `<name>` convention: the resource is the argument, never an option."""
    for label, command in every_command():
        for parameter in command.params:
            if isinstance(parameter, click.Argument):
                assert parameter.name is not None
                assert parameter.name.islower(), f"{label} {parameter.name}"


# -------------------------------------------------------------- the version --
def test_version_prints_the_program_name_and_the_packaged_version(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0, result.output
    declared = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.M)
    assert declared is not None
    assert result.stdout.strip() == f"blue-ops {declared.group(1)}"


# -------------------------------------------------------------- the formats --
@pytest.mark.parametrize("command", RESULT_COMMANDS, ids=lambda c: "-".join(c[:2]))
@pytest.mark.parametrize("fmt", FORMATS)
def test_every_command_honours_every_format(
    command: list[str], fmt: str, runner: CliRunner
) -> None:
    result = runner.invoke(cli, [*command, "--format", fmt])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip(), f"{command} produced nothing in {fmt}"
    if fmt == "json":
        json.loads(result.stdout)


@pytest.mark.parametrize("command", RESULT_COMMANDS, ids=lambda c: "-".join(c[:2]))
def test_an_unknown_format_is_refused_before_anything_runs(
    command: list[str], runner: CliRunner
) -> None:
    result = runner.invoke(cli, [*command, "--format", "yaml"])
    assert result.exit_code == config.EXIT_USAGE
    assert "ERROR: USAGE" in result.stderr


def test_csv_is_not_a_format_this_cli_offers(runner: CliRunner) -> None:
    """A record bundle is groups of records, and CSV has no representation for the boundary."""
    assert "csv" not in FORMATS
    result = runner.invoke(cli, ["profile", "list", "--format", "csv"])
    assert result.exit_code == config.EXIT_USAGE


@pytest.mark.parametrize("command", RESULT_COMMANDS, ids=lambda c: "-".join(c[:2]))
def test_the_default_format_comes_from_the_profile(command: list[str], runner: CliRunner) -> None:
    assert runner.invoke(cli, ["profile", "config", "BLUE_DATA_CLI_FORMAT", "json"]).exit_code == 0
    result = runner.invoke(cli, command)
    assert result.exit_code == 0, result.output
    json.loads(result.stdout)


def test_a_configured_format_the_cli_does_not_have_is_a_profile_error(runner: CliRunner) -> None:
    assert runner.invoke(cli, ["profile", "config", "BLUE_DATA_CLI_FORMAT", "yaml"]).exit_code == 0
    result = runner.invoke(cli, ["metadata", "inspect"])
    assert result.exit_code == config.EXIT_PROFILE
    assert "ERROR: PROFILE" in result.stderr
    assert "BLUE_DATA_CLI_FORMAT" in result.stderr


def test_format_is_one_option_declared_once_and_identical_everywhere() -> None:
    """A reused option with a different type or default on one command is the drift this
    single declaration exists to prevent."""
    seen = {
        label: option_named(command, "--format")
        for label, command in every_command()
        if any("--format" in parameter.opts for parameter in command.params)
    }
    assert {label.split()[0] for label in seen} == set(TREE)
    for label, parameter in seen.items():
        assert isinstance(parameter, click.Option)
        assert parameter.default is None, label
        assert isinstance(parameter.type, click.Choice)
        assert choices_of(parameter) == FORMATS, label


def test_catalog_is_one_option_declared_once_and_identical_everywhere() -> None:
    for label, command in every_command():
        if not any("--catalog" in parameter.opts for parameter in command.params):
            continue
        parameter = option_named(command, "--catalog")
        assert isinstance(parameter, click.Option)
        assert parameter.default is None, label
        assert isinstance(parameter.type, click.Choice)
        assert choices_of(parameter) == config.CATALOGS, label


# ----------------------------------------------------------- the four tiers --
def test_a_command_option_wins_over_everything(runner: CliRunner) -> None:
    runner.invoke(cli, ["profile", "config", "BLUE_DATA_OPS_CATALOG", "active"])
    result = runner.invoke(
        cli,
        ["metadata", "inspect", "--catalog", "history", "--format", "json"],
        env={"BLUE_DATA_OPS_CATALOG": "active"},
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["metadata"]["catalog"] == "history"


def test_the_environment_wins_over_the_profile(runner: CliRunner) -> None:
    runner.invoke(cli, ["profile", "config", "BLUE_DATA_OPS_CATALOG", "active"])
    result = runner.invoke(
        cli,
        ["metadata", "inspect", "--format", "json"],
        env={"BLUE_DATA_OPS_CATALOG": "history"},
    )
    assert json.loads(result.stdout)["metadata"]["catalog"] == "history"


def test_the_profile_wins_over_the_default(runner: CliRunner) -> None:
    runner.invoke(cli, ["profile", "config", "BLUE_DATA_OPS_CATALOG", "history"])
    result = runner.invoke(cli, ["metadata", "inspect", "--format", "json"])
    assert json.loads(result.stdout)["metadata"]["catalog"] == "history"


def test_the_built_in_default_is_the_last_tier(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["metadata", "inspect", "--format", "json"])
    assert json.loads(result.stdout)["metadata"]["catalog"] == "active"


def test_the_stored_selection_sits_between_the_profile_parameter_and_the_default(
    runner: CliRunner, cli_home: Path
) -> None:
    """`.selected.catalog` is the family's selection file, and it is not reachable from the
    environment, so it sits under the parameter that is."""
    from blue_data_ops_cli.configstore import ProfileStore

    runner.invoke(cli, ["profile", "list"])
    ProfileStore(cli_home).write_selection("default", "catalog", "history")
    result = runner.invoke(cli, ["metadata", "inspect", "--format", "json"])
    assert json.loads(result.stdout)["metadata"]["catalog"] == "history"

    overridden = runner.invoke(
        cli, ["metadata", "inspect", "--format", "json"], env={"BLUE_DATA_OPS_CATALOG": "active"}
    )
    assert json.loads(overridden.stdout)["metadata"]["catalog"] == "active"


def test_the_raw_view_is_refused_with_the_reason_rather_than_an_unknown_value(
    runner: CliRunner,
) -> None:
    """`raw` is a name a reader of the library's own documentation will try."""
    result = runner.invoke(cli, ["metadata", "inspect", "--catalog", "raw"])
    assert result.exit_code == config.EXIT_USAGE
    assert "planning authority" in result.stderr

    configured = runner.invoke(cli, ["metadata", "inspect"], env={"BLUE_DATA_OPS_CATALOG": "raw"})
    assert configured.exit_code == config.EXIT_CONFIG
    assert "planning authority" in configured.stderr


def test_a_configured_catalog_that_is_not_a_catalog_names_the_parameter(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["metadata", "inspect"], env={"BLUE_DATA_OPS_CATALOG": "nonsense"})
    assert result.exit_code == config.EXIT_CONFIG
    assert "BLUE_DATA_OPS_CATALOG" in result.stderr


def test_the_root_profile_option_reads_blue_data_profile(runner: CliRunner) -> None:
    runner.invoke(cli, ["profile", "add", "staging"])
    result = runner.invoke(
        cli, ["profile", "inspect", "--format", "json"], env={"BLUE_DATA_PROFILE": "staging"}
    )
    assert json.loads(result.stdout)["profile"] == "staging"


def test_the_root_profile_option_beats_the_variable(runner: CliRunner) -> None:
    runner.invoke(cli, ["profile", "add", "staging"])
    result = runner.invoke(
        cli,
        ["--profile", "default", "profile", "inspect", "--format", "json"],
        env={"BLUE_DATA_PROFILE": "staging"},
    )
    assert json.loads(result.stdout)["profile"] == "default"


def test_a_named_profile_that_does_not_exist_is_refused(runner: CliRunner) -> None:
    """A misspelled name would run with none of the settings the profile holds."""
    result = runner.invoke(cli, ["--profile", "ghost", "metadata", "inspect"])
    assert result.exit_code == config.EXIT_PROFILE
    assert "no such profile: 'ghost'" in result.stderr
    assert "profile add ghost" in result.stderr


def test_the_same_refusal_reaches_the_variable(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["metadata", "inspect"], env={"BLUE_DATA_PROFILE": "ghost"})
    assert result.exit_code == config.EXIT_PROFILE


# ------------------------------------------------------ stdout stays clean --
def test_a_run_leaves_the_environment_as_it_found_it(runner: CliRunner) -> None:
    """The profile is exported for the duration of the run, not for the life of the process."""
    runner.invoke(cli, ["profile", "config", "BLUE_DATA_OPS_PLANNER", "rule"])
    before = dict(os.environ)
    assert runner.invoke(cli, ["metadata", "inspect"]).exit_code == 0
    assert dict(os.environ) == before


def test_progress_is_suppressed_under_a_machine_format() -> None:
    assert config.Reporter("json").machine_readable
    assert not config.Reporter("table").machine_readable
    assert not config.Reporter("nl").machine_readable


def test_a_suppressed_spinner_is_a_no_op_context() -> None:
    with config.Reporter("json").status("Running…"):
        pass


def test_log_lines_are_truncated_to_the_limit() -> None:
    reporter = config.Reporter("table", log=True, log_limit=20)
    assert len(config.truncate("why " * 200, reporter.log_limit)) == 20


def test_a_log_limit_of_zero_is_a_limit_of_zero() -> None:
    """Not `unset`. The same value read two ways depending on the tier is the bug."""
    assert config.truncate("anything", 0) == "..."


# ------------------------------------------------------- nothing blocks --
@pytest.mark.parametrize("command", RESULT_COMMANDS, ids=lambda c: "-".join(c[:2]))
def test_every_command_runs_with_an_empty_profile(command: list[str], runner: CliRunner) -> None:
    """No parameter gates a command. A missing credential surfaces only at the provider."""
    result = runner.invoke(cli, command)
    assert result.exit_code == 0, result.output


def test_every_resource_beside_the_modules_is_declared_package_data() -> None:
    """A file loaded with `Path(__file__).with_name(...)` has to be declared to ship.

    `profile_spec.json` is read on every invocation, and setuptools ships a non-Python file
    only when `package-data` names it. Without the declaration the source tree and an
    editable install both work and a wheel install raises `FileNotFoundError` on the first
    command, so no test that imports from source can see the gap.
    """
    package = Path(config.__file__).parent
    manifest = (package.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    pattern = (
        r"^\[tool\.setuptools\.package-data\]\s*\n" + package.name + r"\s*=\s*\[(?P<names>[^\]]*)\]"
    )
    block = re.search(pattern, manifest, re.MULTILINE)
    declared: set[str] = set(re.findall(r'"([^"]+)"', block["names"])) if block else set()
    present = {p.name for p in package.iterdir() if p.is_file() and p.suffix != ".py"}
    assert present <= declared, f"undeclared package data: {sorted(present - declared)}"
