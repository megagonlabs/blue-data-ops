"""`metadata inspect` reports what is installed, and reports it from the installation.

The failure this prevents is a version literal that drifts: a number written into the source
and then not changed, so the command reports one thing and `pip` reports another. Every
version here is read from `importlib.metadata`, and the comparison is against that rather
than against a copy of it.
"""

from __future__ import annotations

import json
import platform
import re
from importlib import metadata as distributions
from pathlib import Path
from typing import Any, cast

import pytest
from click.testing import CliRunner

from blue_data_ops_cli import __version__, config, metadata
from blue_data_ops_cli.commands import cli

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def reported(runner: CliRunner) -> dict[str, Any]:
    result = runner.invoke(cli, ["metadata", "inspect", "--format", "json"])
    assert result.exit_code == 0, result.output
    published: Any = json.loads(result.stdout)["metadata"]
    assert isinstance(published, dict)
    return cast("dict[str, Any]", published)


def declared_version() -> str:
    found = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.M)
    assert found is not None
    return found.group(1)


def test_the_package_literal_and_the_manifest_agree() -> None:
    """The build reads the manifest; a source checkout with no distribution reads the literal."""
    assert __version__ == declared_version()


def test_the_reported_cli_version_is_the_one_version_prints(runner: CliRunner) -> None:
    published = reported(runner)
    assert published[config.DISTRIBUTION] == config.cli_version()
    printed = runner.invoke(cli, ["--version"]).stdout.strip()
    assert printed == f"{config.PROGRAM} {published[config.DISTRIBUTION]}"


@pytest.mark.parametrize(
    "distribution",
    [metadata.CORE_DISTRIBUTION, metadata.MCP_DISTRIBUTION, metadata.DATA_DISTRIBUTION],
)
def test_every_reported_distribution_is_read_from_the_installation(
    distribution: str, runner: CliRunner
) -> None:
    try:
        installed: str | None = distributions.version(distribution)
    except distributions.PackageNotFoundError:
        installed = None
    assert reported(runner)[distribution] == installed


def test_a_distribution_that_is_not_installed_is_reported_as_absent_rather_than_guessed(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(name: str) -> str:
        raise distributions.PackageNotFoundError(name)

    monkeypatch.setattr(metadata.distributions, "version", missing)
    published = reported(runner)
    assert published[metadata.MCP_DISTRIBUTION] is None
    result = runner.invoke(cli, ["metadata", "inspect"])
    assert metadata.NOT_INSTALLED in result.stdout


def test_the_reported_interpreter_is_the_running_one(runner: CliRunner) -> None:
    assert reported(runner)["python"] == platform.python_version()


def test_the_reported_extras_are_the_ones_this_package_asks_for(runner: CliRunner) -> None:
    """A reported extra nothing installs would be a claim about a package that never arrives.

    Three of the four are requested from the core in the dependency line; `openai` is this
    package's own optional group, because only the provider-backed planner needs it.
    """
    manifest = PYPROJECT.read_text()
    requested = re.search(r'"blue-data-ops\[([^\]]+)\]', manifest)
    assert requested is not None
    from_core = {name.strip() for name in requested.group(1).split(",")}
    section = manifest.split("[project.optional-dependencies]")[1].split("\n[")[0]
    own = set(re.findall(r"^(\w+) = \[", section, re.M))

    published = cast("dict[str, bool]", reported(runner)["extras"])
    assert set(published) == set(metadata.EXTRA_MODULES)
    assert set(published) == from_core | (own - {"dev"})


def test_an_extra_is_reported_present_only_when_every_module_it_brings_is(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def without_sklearn(name: str) -> bool:
        return name != "sklearn"

    monkeypatch.setattr(metadata, "module_present", without_sklearn)
    published = cast("dict[str, bool]", reported(runner)["extras"])
    assert published["ml"] is False
    assert published["openai"] is True


def test_the_reported_card_count_is_the_selected_catalog_s(runner: CliRunner) -> None:
    active = reported(runner)
    assert active["catalog"] == "active"
    assert active["cards"] == len(config.build_catalog("active").list_cards())

    result = runner.invoke(cli, ["metadata", "inspect", "--catalog", "history", "--format", "json"])
    history = json.loads(result.stdout)["metadata"]
    assert history["catalog"] == "history"
    assert history["cards"] == len(config.build_catalog("history").list_cards())
    assert history["cards"] > active["cards"]


def test_the_table_and_the_object_report_the_same_facts(runner: CliRunner) -> None:
    published = reported(runner)
    printed = runner.invoke(cli, ["metadata", "inspect"]).stdout
    assert str(published["cards"]) in printed
    assert str(published["catalog"]) in printed
    assert str(published["python"]) in printed
