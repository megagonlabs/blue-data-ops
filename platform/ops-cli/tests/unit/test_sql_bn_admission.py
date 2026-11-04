from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.json.memory_json_source import MemoryJSONSource  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource  # pyright: ignore[reportMissingTypeStubs]
from blue_data_ops.llm import LLMClient
from blue_data_ops.llm.sql_execution import ReadOnlySQLExecutor
from blue_data_ops.operators import (
    NL2BNOperator,
    NL2SQLOperator,
    OperatorRegistry,
    versioned_registry,
)
from click.testing import CliRunner, Result

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli


class _ResolverPatch(Protocol):
    def setattr(
        self, target: object, name: str, value: Callable[[dict[str, Any]], LLMClient]
    ) -> None: ...


SQL_ATTRIBUTES = {
    "question": "list rows",
    "source": "approved",
    "database": "db",
    "collection": "public",
    "protocol": "sqlite",
}


def invoke(
    runner: CliRunner,
    tmp_path: Path,
    operator_id: str,
    properties: dict[str, Any],
    attributes: dict[str, Any] | None = None,
) -> Result:
    path = tmp_path / "input.json"
    path.write_text("[[]]")
    arguments = ["operator", "run", operator_id, "--input-file", str(path), "--format", "json"]
    for key, value in (attributes or SQL_ATTRIBUTES).items():
        arguments.extend(("--attribute", key + "=" + json.dumps(value)))
    for key, value in properties.items():
        arguments.extend(("--property", key + "=" + json.dumps(value)))
    return runner.invoke(cli, arguments)


@pytest.mark.parametrize("version", ["2.0.0", "3.0.0"])
@pytest.mark.parametrize(
    "properties,message",
    [
        ({"execute_query": True}, "read-only SQL execution is not configured"),
        ({"execute_query": "true"}, "invalid SQL execution policy"),
        (
            {"input_template": "synthetic caller detail"},
            "operator template and transport controls are reserved",
        ),
        *[
            ({"execute_query": True, key: None}, "invalid SQL execution policy")
            for key in ("data_registry", "platform.name", "data_registry.name")
        ],
    ],
)
def test_stock_sql_denial_precedes_cli_registry_build(
    monkeypatch: pytest.MonkeyPatch,
    install_catalog: Callable[[OperatorRegistry | Exception], object],
    runner: CliRunner,
    tmp_path: Path,
    version: str,
    properties: dict[str, Any],
    message: str,
) -> None:
    install_catalog(versioned_registry())
    builds: list[int] = []

    def forbidden() -> None:
        builds.append(1)
        raise AssertionError("early denial must precede registry construction")

    monkeypatch.setattr(config, "build_registry_seam", forbidden)
    result = invoke(runner, tmp_path, "nl2sql@" + version, properties)
    assert result.exit_code == config.EXIT_EXECUTION
    document = json.loads(result.stdout)
    assert message in document["error"]["message"]
    assert message in result.stderr
    assert "synthetic caller detail" not in result.output
    assert builds == []


@pytest.mark.parametrize("version", ["2.0.0", "3.0.0"])
@pytest.mark.parametrize("prefix", ["openai", "host_service"])
def test_bn_original_transport_controls_precede_cli_registry_build(
    monkeypatch: pytest.MonkeyPatch,
    install_catalog: Callable[[OperatorRegistry | Exception], object],
    runner: CliRunner,
    tmp_path: Path,
    version: str,
    prefix: str,
) -> None:
    registry = versioned_registry()
    selected = registry.resolve("nl2bn@" + version)
    implementation = cast(NL2BNOperator, getattr(selected, "_target", selected))
    monkeypatch.setattr(
        implementation,
        "DEFAULT_PROPERTIES",
        {
            **implementation.DEFAULT_PROPERTIES,
            "service_prefix": prefix,
        },
    )
    install_catalog(registry)
    builds: list[int] = []

    def forbidden() -> None:
        builds.append(1)
        raise AssertionError("early denial must precede registry construction")

    monkeypatch.setattr(config, "build_registry_seam", forbidden)
    result = invoke(
        runner,
        tmp_path,
        "nl2bn@" + version,
        {
            prefix + ".service_url": "synthetic caller detail",
        },
    )
    assert result.exit_code == config.EXIT_EXECUTION
    message = "operator template and transport controls are reserved"
    assert message in json.loads(result.stdout)["error"]["message"]
    assert message in result.stderr
    assert builds == []


@pytest.mark.parametrize("alias", [False, True])
@pytest.mark.parametrize("version", ["2.0.0", "4.0.0"])
def test_host_bound_cli_select_builds_no_ordinary_registry(
    monkeypatch: pytest.MonkeyPatch,
    install_catalog: Callable[[OperatorRegistry | Exception], object],
    runner: CliRunner,
    tmp_path: Path,
    alias: bool,
    version: str,
) -> None:
    import blue_data_ops.operators.nl2sql_operator as module

    class Client(LLMClient):
        def __init__(self) -> None:
            pass

        def execute_api_call(
            self,
            input: Any,
            properties: dict[str, Any] | None = None,
            additional_data: dict[str, Any] | None = None,
        ) -> dict[str, str]:
            return {"query": "SELECT id FROM records"}

    with sqlite3.connect(tmp_path / "db.db") as connection:
        connection.execute("CREATE TABLE records (id INTEGER)")
        connection.execute("INSERT INTO records VALUES (1)")
    data_registry = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    data_registry.register_source(
        SQLiteDBSource(
            "approved",
            properties={"connection": {"database_directory": str(tmp_path)}},
        )
    )
    operator = NL2SQLOperator(
        read_only_executor=ReadOnlySQLExecutor(
            data_registry,
            frozenset({("approved", "db", "public")}),
        )
    )
    registry = OperatorRegistry()
    if alias:
        registry.register(operator, "1.0.0")
    registry.register(operator, version, tags=("requires-data-registry",))
    install_catalog(registry)
    cast(_ResolverPatch, monkeypatch).setattr(
        module, "resolve_llm_client", lambda properties: Client()
    )
    builds: list[int] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        builds.append(1)
        raise AssertionError("bound execution must use its host registry")

    monkeypatch.setattr(config, "build_registry_seam", forbidden)
    monkeypatch.setattr(module, "resolve_registry", forbidden)
    result = invoke(runner, tmp_path, "nl2sql@" + version, {"execute_query": True})
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["result"]["output_data"] == [[{"id": 1}]]
    assert builds == []


@pytest.mark.parametrize("preflight", [None, "raises", "nonboolean"])
def test_cli_missing_raising_nonboolean_preflight_denies_before_build(
    monkeypatch: pytest.MonkeyPatch,
    install_catalog: Callable[[OperatorRegistry | Exception], object],
    runner: CliRunner,
    tmp_path: Path,
    preflight: object,
) -> None:
    registry = versioned_registry()
    selected = registry.resolve("nl2sql@2.0.0")
    implementation = getattr(selected, "_target", selected)
    selected_preflight = preflight
    if preflight == "raises":

        def raising_preflight(*args: object) -> object:
            raise RuntimeError("synthetic backend detail")

        selected_preflight = raising_preflight
    elif preflight == "nonboolean":

        def nonboolean_preflight(*args: object) -> object:
            return 1

        selected_preflight = nonboolean_preflight

    monkeypatch.setattr(implementation, "_preflight_execution", selected_preflight)
    install_catalog(registry)
    builds: list[int] = []

    def forbidden() -> None:
        builds.append(1)
        raise AssertionError("early denial must precede registry construction")

    monkeypatch.setattr(config, "build_registry_seam", forbidden)
    result = invoke(runner, tmp_path, "nl2sql@2.0.0", {"execute_query": True})
    assert result.exit_code == config.EXIT_EXECUTION
    assert (
        "read-only SQL execution is not configured" in json.loads(result.stdout)["error"]["message"]
    )
    assert "synthetic backend detail" not in result.output
    assert builds == []
