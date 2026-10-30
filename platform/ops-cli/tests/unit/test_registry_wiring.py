"""The seam onto `blue-data`, which is the one import boundary this CLI cannot type-check.

`blue_data.config` is a module of an already-required dependency with no leading underscore
on any of the five symbols, but `blue-data` declares no `__all__` and ships no `py.typed`.
A rename there breaks the registry wiring silently, so the imports are asserted rather than
assumed. Nothing here builds a registry that touches redis or a file: the default backend is
in-memory and the construction path is exercised once, offline.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, cast

import pytest
from blue_data_ops import RegistrySeam
from blue_data_ops.operators import active_registry
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli

FIVE_SYMBOLS = (
    "build_enricher",
    "build_hybrid_config",
    "build_store",
    "get_vector_dim",
    "load_sources",
)


@pytest.mark.parametrize("symbol", FIVE_SYMBOLS)
def test_the_five_blue_data_config_imports_resolve(symbol: str) -> None:
    import blue_data.config as blue_data_config  # pyright: ignore[reportMissingTypeStubs]

    assert callable(getattr(blue_data_config, symbol)), symbol


def test_the_data_registry_class_is_where_the_seam_expects_it() -> None:
    from blue_data.registry.data_registry import (  # pyright: ignore[reportMissingTypeStubs]
        DataRegistry,
    )

    # Read off the class rather than off `__init__`: `blue-data` ships no `py.typed`, which
    # is the whole reason this file asserts the shape instead of letting the checker do it.
    signature = inspect.signature(cast("type[Any]", DataRegistry))
    for keyword in ("store", "metadata_enricher", "hybrid_config", "vector_dim"):
        assert keyword in signature.parameters, keyword


def test_the_seam_is_built_from_the_same_four_arguments_blue_data_s_own_cli_uses() -> None:
    """Same helpers, same keywords, so the same variables produce the same registry."""
    from blue_data_ops.data.config import build_environment_registry

    source = inspect.getsource(build_environment_registry)
    for keyword in ("store=", "metadata_enricher=", "hybrid_config=", "vector_dim="):
        assert keyword in source, keyword


def test_building_the_seam_produces_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default backend is in-memory, so this constructs and discards a real registry."""
    monkeypatch.setenv("BLUE_DATA_REGISTRY_STORE", "memory")
    monkeypatch.delenv("BLUE_DATA_SOURCES_CONFIG", raising=False)
    assert isinstance(config.build_registry_seam(), RegistrySeam)


# ------------------------------------------------------------- tag-driven --
def test_the_tag_is_the_library_s_own_and_some_card_carries_it() -> None:
    """Construction is lazy and tag-driven, so the tag has to be the one the cards use."""
    assert config.DATA_REGISTRY_TAG == "requires-data-registry"
    cards = active_registry().list_cards()
    tagged = [card for card in cards if config.requires_data_registry(card)]
    assert tagged, "no active card carries the data-registry tag"


def test_an_untagged_card_does_not_ask_for_a_registry() -> None:
    card = next(
        card for card in active_registry().list_cards() if not config.requires_data_registry(card)
    )
    assert not config.requires_data_registry(card)


def test_nothing_builds_a_registry_until_a_tagged_card_asks_for_one(
    install_registry_seam: Any, runner: CliRunner
) -> None:
    """The seam reaches a backend, so a command that needs no registry must not build one."""

    class Tripwire(Exception):
        pass

    install_registry_seam(Tripwire("a registry was built by a command that needs none"))
    result = runner.invoke(cli, ["metadata", "inspect"])
    assert result.exit_code == 0, result.output
    assert runner.invoke(cli, ["profile", "list"]).exit_code == 0


# ------------------------------------------------------------ the backend --
def test_the_memory_backend_is_reported_as_the_ephemeral_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """For a CLI it means anything created dies with the command, which is worth saying."""
    monkeypatch.delenv("BLUE_DATA_REGISTRY_STORE", raising=False)
    assert config.registry_backend() == "memory"
    assert config.registry_is_ephemeral()

    monkeypatch.setenv("BLUE_DATA_REGISTRY_STORE", "file")
    assert config.registry_backend() == "file"
    assert not config.registry_is_ephemeral()


def test_the_backend_is_read_from_the_variable_blue_data_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BLUE_DATA_REGISTRY_STORE", "REDIS")
    assert config.registry_backend() == "redis"


def test_cli_missing_sources_path_is_a_fixed_configuration_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runner: CliRunner
) -> None:
    import json

    path = tmp_path / "input.json"
    path.write_text("[[]]")
    missing = tmp_path / "missing-sources.json"
    monkeypatch.setenv("BLUE_DATA_SOURCES_CONFIG", str(missing))
    result = runner.invoke(
        cli,
        [
            "operator",
            "run",
            "data_discover@2.0.0",
            "--input-file",
            str(path),
            "--attribute",
            "search_query=items",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == config.EXIT_CONFIG
    document = json.loads(result.stdout)
    assert document["error"]["code"] == "CONFIG"
    assert "data registry configuration failed" in document["error"]["message"]
    assert str(missing) not in result.output


def test_cli_unconfigured_memory_default_still_warns_and_runs(
    tmp_path: Path, runner: CliRunner
) -> None:
    path = tmp_path / "input.json"
    path.write_text("[[]]")
    result = runner.invoke(
        cli,
        [
            "operator",
            "run",
            "data_discover@2.0.0",
            "--input-file",
            str(path),
            "--attribute",
            "search_query=items",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "memory" in result.stderr.lower()
