"""Every command the package README shows, run in the order the README shows it.

A README is documentation that rots quietly: the command keeps being printed long after the
option it uses was renamed. So the file itself is the fixture here. Every `blue-ops` line in
a shell block is extracted and run against a throwaway CLI home, in order, because the
examples build on each other — a profile is added before it is removed, a pipeline is
planned before it is run.

Nothing reaches a provider or a network. Every command here reads the local operator
library, and the printed JSON paths are read from the checkout.
Inline examples must match those files.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any, cast

import click
import litellm
import pytest
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli

README = Path(__file__).resolve().parents[2] / "README.md"

_FENCE = re.compile(r"^```(\w*)\s*$")
_NAMED_FILE = re.compile(r"^\[?`([\w./-]+\.json)`(?:\]\([^)]*\))?:\s*$")

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
    files: dict[str, str] = {}
    for language, previous, body in blocks():
        match = _NAMED_FILE.match(previous)
        if language == "json" and match:
            name = match.group(1)
            content = (README.parents[2] / name).read_text(encoding="utf-8")
            assert json.loads(content) == json.loads(body), name
            files[name] = content
    assert set(files) >= {
        "examples/cli/workspaces.json",
        "examples/cli/llm-pipeline.json",
        "examples/cli/llm-input.json",
    }
    return files


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

    class OfflineResponse:
        def __init__(self, content: str) -> None:
            self.content = content

        def model_dump(self) -> dict[str, Any]:
            return {
                "choices": [{"message": {"role": "assistant", "content": self.content}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            }

    def offline_completion(**kwargs: Any) -> OfflineResponse:
        raw_messages: Any = kwargs.get("messages")
        messages = (
            cast("list[dict[str, Any]]", raw_messages) if isinstance(raw_messages, list) else []
        )
        prompt = str(messages[0].get("content", "")) if messages else ""
        if "only a boolean value" in prompt:
            return OfflineResponse("true")
        return OfflineResponse('[{"category": "sample"}]')

    def offline_cost(**kwargs: Any) -> float:
        del kwargs
        return 0.0

    monkeypatch.setattr(litellm, "completion", offline_completion)
    monkeypatch.setattr(litellm, "completion_cost", offline_cost)
    commands = documented_commands()
    assert len(commands) > 30, "the README lost its examples"
    monkeypatch.chdir(tmp_path)
    for name, body in documented_files().items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    for command in commands:
        result = runner.invoke(cli, command, input=ANSWERS)
        assert result.exit_code == config.EXIT_OK, (
            f"`blue-ops {' '.join(command)}` exits {result.exit_code}\n"
            f"{result.stderr}\n{result.stdout}"
        )


def test_documented_llm_pipeline_preserves_layers_and_clears_effort(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    class OfflineResponse:
        def model_dump(self) -> dict[str, Any]:
            return {
                "choices": [{"message": {"role": "assistant", "content": "[]"}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            }

    def offline_completion(**kwargs: Any) -> OfflineResponse:
        calls.append(kwargs)
        return OfflineResponse()

    def offline_cost(**kwargs: Any) -> float:
        del kwargs
        return 0.0

    monkeypatch.setattr(litellm, "completion", offline_completion)
    monkeypatch.setattr(litellm, "completion_cost", offline_cost)
    monkeypatch.chdir(tmp_path)
    files = documented_files()
    for name in ("llm-pipeline.json", "llm-input.json"):
        path = tmp_path / "examples/cli" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(files[f"examples/cli/{name}"], encoding="utf-8")

    record = cast("dict[str, Any]", json.loads(files["examples/cli/llm-pipeline.json"]))
    assert record["properties"] == {
        "llm.model": "gpt-5-mini",
        "llm.reasoning_effort": "medium",
    }
    operator = next(iter(cast("dict[str, Any]", record["entities"])["OPERATOR"].values()))
    assert operator["properties"] == {
        "llm.model": "gpt-4o-mini",
        "llm.reasoning_effort": None,
    }

    imported = runner.invoke(
        cli,
        ["pipeline", "import", "llm-example", "--pipeline-file", "examples/cli/llm-pipeline.json"],
    )
    assert imported.exit_code == config.EXIT_OK, imported.output
    exported = runner.invoke(cli, ["pipeline", "export", "llm-example"])
    assert exported.exit_code == config.EXIT_OK, exported.output
    assert json.loads(exported.stdout) == record
    result = runner.invoke(
        cli,
        [
            "pipeline",
            "run",
            "llm-example",
            "--input-file",
            "examples/cli/llm-input.json",
            "--model",
            "gpt-4o",
            "--reasoning-effort",
            "high",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == config.EXIT_OK, result.output
    assert len(calls) == 1
    assert calls[0]["model"] == "gpt-4o-mini"
    assert "reasoning_effort" not in calls[0]
    payload = json.loads(result.stdout)
    assert payload["settings"]["scope"] == "invocation_defaults"


def test_shipped_workspaces_semantic_filter_returns_selected_record(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    class OfflineResponse:
        def model_dump(self) -> dict[str, Any]:
            return {
                "choices": [{"message": {"role": "assistant", "content": "true"}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            }

    def complete(**kwargs: Any) -> OfflineResponse:
        calls.append(kwargs)
        return OfflineResponse()

    def cost(**kwargs: Any) -> float:
        return 0.0

    monkeypatch.setattr(litellm, "completion", complete)
    monkeypatch.setattr(litellm, "completion_cost", cost)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "examples/cli/workspaces.json"
    path.parent.mkdir(parents=True)
    path.write_text(documented_files()["examples/cli/workspaces.json"])
    result = runner.invoke(
        cli,
        [
            "operator",
            "run",
            "semantic_filter@3.0.0",
            "--input-file",
            str(path),
            "--attribute",
            'filter_conditions={"summary":"suited to focused work"}',
            "--model",
            "gpt-4o-mini",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == config.EXIT_OK, result.output
    assert json.loads(result.stdout)["result"]["output_data"] == json.loads(path.read_text())
    assert calls and all(call["model"] == "gpt-4o-mini" for call in calls)
