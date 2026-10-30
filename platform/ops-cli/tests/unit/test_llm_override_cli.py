"""An unknown ``llm.*`` setting from a properties file is the documented ``bad_override``."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from blue_data_ops.operators import OperatorRegistry, versioned_registry
from click.testing import CliRunner, Result

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli


def _run(runner: CliRunner, tmp_path: Path, *options: str) -> Result:
    data = tmp_path / "input.json"
    data.write_text("[[]]")
    return runner.invoke(
        cli,
        [
            "operator",
            "run",
            "nl2llm@3.0.0",
            "--input-file",
            str(data),
            "--attribute",
            "query=hello",
            *options,
            "--format",
            "json",
        ],
    )


def test_a_properties_file_typo_is_bad_override(
    install_catalog: Callable[[OperatorRegistry | Exception], object],
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    install_catalog(versioned_registry())
    properties = tmp_path / "properties.json"
    properties.write_text(json.dumps({"llm.max_token": 5}))
    result = _run(runner, tmp_path, "--properties-file", str(properties))
    assert result.exit_code == config.EXIT_EXECUTION
    document = json.loads(result.stdout)
    assert "LLM setting is not supported" in document["error"]["message"]
    assert document["error"]["detail"]["suggestion"] == (
        "Use a documented llm.* or provider generation setting."
    )
    assert "max_token" not in result.stdout


def test_a_reserved_control_from_a_properties_file_stays_reserved(
    install_catalog: Callable[[OperatorRegistry | Exception], object],
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    install_catalog(versioned_registry())
    properties = tmp_path / "properties.json"
    properties.write_text(json.dumps({"service_prefix": None}))
    result = _run(runner, tmp_path, "--properties-file", str(properties))
    assert result.exit_code == config.EXIT_EXECUTION
    assert "operator template and transport controls are reserved" in result.stdout


def test_the_argv_credential_guard_still_refuses_a_token_named_property(
    install_catalog: Callable[[OperatorRegistry | Exception], object],
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    install_catalog(versioned_registry())
    result = _run(runner, tmp_path, "--property", "llm.max_token=5")
    assert result.exit_code == config.EXIT_USAGE
