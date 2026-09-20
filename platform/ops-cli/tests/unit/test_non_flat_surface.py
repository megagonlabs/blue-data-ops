"""Nothing is reachable except as `<component> {<subcomponent>} <action>`.

The guide gives one command shape and the checklist asks that every command follow it. That
is a claim about the tree rather than about any one command, and the way it breaks is a
convenience action added at the root — `blue-ops list`, `blue-ops run` — which reads fine on
its own and leaves the CLI with two grammars.
"""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli

STANDARD_VERBS = frozenset(
    {"add", "remove", "list", "config", "select", "query", "inspect", "search", "import", "export"}
)
"""The guide's verb list. Anything outside it is a documented deviation, not an accident."""

NON_STANDARD_VERBS = frozenset({"run"})
"""Verbs this CLI introduces, each argued in the README and in the design.

`run` means "apply a transformation to supplied records and return the result". No standard
verb covers that, and `query` means "retrieve from a store" everywhere else in the family.
"""

SYNONYMS = frozenset({"create", "delete", "show", "set", "register", "sync", "get", "update"})
"""Spellings of verbs that are already in the list. None of them may appear."""


def component_groups() -> dict[str, click.Group]:
    groups: dict[str, click.Group] = {}
    for name, command in cli.commands.items():
        assert isinstance(command, click.Group), f"{name} is a bare action at the root"
        groups[name] = command
    return groups


def actions() -> list[tuple[str, str]]:
    """Every leaf in the tree, as (path, action)."""
    found: list[tuple[str, str]] = []
    for name, group in component_groups().items():
        for action, command in group.commands.items():
            if isinstance(command, click.Group):
                # A subcomponent: its own children are the actions, and they are leaves.
                for leaf, subcommand in command.commands.items():
                    assert not isinstance(subcommand, click.Group), f"{name} {action} {leaf}"
                    found.append((f"{name} {action}", leaf))
                continue
            found.append((name, action))
    return found


def test_every_top_level_entry_is_a_component_group() -> None:
    assert component_groups()


def test_the_tree_is_never_more_than_component_subcomponent_action() -> None:
    """Three levels below the program name, and no fourth."""
    for path, _ in actions():
        assert len(path.split()) <= 2, path


@pytest.mark.parametrize("action", sorted({action for _, action in actions()}))
def test_every_action_is_a_standard_verb_or_a_declared_deviation(action: str) -> None:
    assert action in STANDARD_VERBS | NON_STANDARD_VERBS, action


@pytest.mark.parametrize("synonym", sorted(SYNONYMS))
def test_no_synonym_of_a_standard_verb_is_reachable(synonym: str, runner: CliRunner) -> None:
    assert synonym not in {action for _, action in actions()}
    assert synonym not in component_groups()
    result = runner.invoke(cli, [synonym])
    assert result.exit_code == config.EXIT_USAGE


@pytest.mark.parametrize("verb", sorted(STANDARD_VERBS | NON_STANDARD_VERBS))
def test_no_action_is_reachable_without_its_component(verb: str, runner: CliRunner) -> None:
    result = runner.invoke(cli, [verb])
    assert result.exit_code == config.EXIT_USAGE
    assert "ERROR: USAGE" in result.stderr


def test_a_component_with_no_action_is_a_usage_error_naming_its_actions(
    runner: CliRunner,
) -> None:
    for component in component_groups():
        result = runner.invoke(cli, [component])
        assert result.exit_code == config.EXIT_USAGE
        assert "ERROR: USAGE" in result.stderr
