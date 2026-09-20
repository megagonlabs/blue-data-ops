"""Every command the package README shows, run in the order the README shows it.

A README is documentation that rots quietly: the command keeps being printed long after the
option it uses was renamed. So the file itself is the fixture here. Every `blue-ops` line in
a shell block is extracted and run against a throwaway CLI home, in order, because the
examples build on each other — a profile is added before it is removed, a pipeline is
planned before it is run.

Nothing reaches a provider or a network. Every command here reads the local operator
library, and the two files the examples name are written from the README's own JSON blocks
rather than from a copy kept in this test.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli

README = Path(__file__).resolve().parents[2] / "README.md"

_FENCE = re.compile(r"^```(\w*)\s*$")
_NAMED_FILE = re.compile(r"^`([\w./-]+\.json)`:\s*$")

ANSWERS = "\n" * 40
"""Blank answers for every prompt an example reaches.

A blank keeps a parameter's current value and declines a confirmation, so a run with nothing
to read from still ends at exit 0 rather than blocking.
"""


def blocks() -> list[tuple[str, str, str]]:
    """Every fenced block as (language, preceding non-blank line, body)."""
    found: list[tuple[str, str, str]] = []
    language: str | None = None
    previous = ""
    body: list[str] = []
    for line in README.read_text(encoding="utf-8").splitlines():
        fence = _FENCE.match(line)
        if fence and language is None:
            language = fence.group(1)
            body = []
            continue
        if fence and language is not None:
            found.append((language, previous, "\n".join(body)))
            language = None
            continue
        if language is not None:
            body.append(line)
        elif line.strip():
            previous = line.strip()
    return found


def documented_files() -> dict[str, str]:
    """The files the examples name, taken from the README's own JSON blocks."""
    return {
        _NAMED_FILE.match(previous).group(1): body  # pyright: ignore[reportOptionalMemberAccess]
        for language, previous, body in blocks()
        if language == "json" and _NAMED_FILE.match(previous)
    }


def documented_commands() -> list[list[str]]:
    """Every `blue-ops` line in a shell block, in README order, as argument lists."""
    commands: list[list[str]] = []
    for language, _, body in blocks():
        if language != "bash":
            continue
        # A trailing backslash continues one command across lines.
        for statement in body.replace("\\\n", " ").splitlines():
            text = statement.strip()
            if text.startswith("blue-ops "):
                commands.append(shlex.split(text)[1:])
    return commands


def every_command() -> set[str]:
    found: set[str] = set()
    for name, group in cli.commands.items():
        assert isinstance(group, click.Group)
        for action, command in group.commands.items():
            if isinstance(command, click.Group):
                found.update(f"{name} {action} {leaf}" for leaf in command.commands)
                continue
            found.add(f"{name} {action}")
    return found


def test_the_readme_shows_every_command_this_cli_has() -> None:
    """The other direction: a command nobody documented is a command nobody finds."""
    shown = {
        " ".join(argument for argument in command if not argument.startswith("-"))
        for command in documented_commands()
    }
    missing = [
        path
        for path in sorted(every_command())
        if not any(entry.startswith(path) for entry in shown)
    ]
    assert not missing, f"the README shows no example of: {missing}"


def test_the_readme_documents_no_command_this_cli_does_not_have(runner: CliRunner) -> None:
    for command in documented_commands():
        if command in (["--help"], ["--version"]):
            continue
        assert command[0] in cli.commands, command


def test_every_command_in_the_readme_runs(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In order, against a throwaway home, because the examples build on each other."""
    commands = documented_commands()
    assert len(commands) > 30, "the README lost its examples"
    monkeypatch.chdir(tmp_path)
    for name, body in documented_files().items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    for command in commands:
        result = runner.invoke(cli, command, input=ANSWERS)
        assert result.exit_code == config.EXIT_OK, (
            f"`blue-ops {' '.join(command)}` exits {result.exit_code}\n"
            f"{result.stderr}\n{result.stdout}"
        )
