from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data_ops.data import RegistrySeam
from blue_data_ops.operators import OperatorRegistry, active_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor
from blue_data_ops_mcp.server import create_server
from click.testing import CliRunner
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli


def attrs(name: str) -> dict[str, Any]:
    return {
        "source": "local",
        "database": "db",
        "collection": "public",
        "question": "query",
        "protocol": "sqlite",
        "protocol_variant": "pgmpy",
        **({"schema": "supplied schema"} if name == "nl2bn" else {}),
    }


@pytest.mark.parametrize("name", ["nl2sql", "nl2bn"])
async def test_missing_source_is_contained_before_client_on_all_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
):
    import blue_data_ops.operators._nl2bn_outcome as bn_outcome
    import blue_data_ops.operators.nl2bn_operator as bn
    import blue_data_ops.operators.nl2sql_operator as sql

    calls: list[bool] = []

    def deny(*args: Any, **kwargs: Any):
        calls.append(True)
        pytest.fail("missing source reached client resolution")

    for module in (sql, bn, bn_outcome):
        monkeypatch.setattr(module, "resolve_llm_client", deny)
    registry = DataRegistry(rebuild=False)
    seam = RegistrySeam(registry)
    catalog = active_registry()
    operator = catalog.resolve(name + ("@4.0.0" if name == "nl2sql" else "@3.0.0"))
    target = attrs(name)
    properties = {"data_registry": seam}
    error = operator.run([[]], target, properties)[2].errors[0]._asdict()
    assert error["message"] == "data source is not registered"
    assert error["retryable"] is False
    assert error["code"] == "EXECUTION_FAILED" and error["stage"] == "EXECUTE"

    plan = DataPipeline(id="missing-source")
    entry = plan.define_input("input")
    step = plan.define_operator(operator.operator_id, label="step", attributes=target)
    output = plan.define_output("output")
    plan.set_plan_input(entry)
    plan.set_plan_output(output)
    plan.connect_nodes(entry, step)
    plan.connect_nodes(step, output)
    execution = PipelineExecutor(catalog).execute(plan, [[]], properties=properties)
    assert execution.node_runs[0].exec_meta.errors[0]._asdict() == error

    cast(Callable[[object, str, Callable[..., OperatorRegistry]], None], monkeypatch.setattr)(
        config, "build_catalog", lambda *args, **kwargs: catalog
    )
    monkeypatch.setattr(config, "build_registry_seam", lambda: seam)
    input_path = tmp_path / "input.json"
    input_path.write_text("[[]]")
    attributes_path = tmp_path / "attributes.json"
    attributes_path.write_text(json.dumps(target))
    result = CliRunner().invoke(
        cli,
        [
            "operator",
            "run",
            operator.operator_id,
            "--input-file",
            str(input_path),
            "--attributes-file",
            str(attributes_path),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 8, result.output
    wire = json.loads(result.stdout)
    assert wire["error"]["detail"]["retryable"] is False
    assert error["message"] in wire["error"]["message"]

    server = create_server(
        registry=catalog, data_registry=seam, operator_ids=(operator.operator_id,)
    )
    async with create_connected_server_and_client_session(cast(Any, server)._mcp_server) as client:
        result = await client.call_tool("ops_" + name, {"input_data": [[]], "attributes": target})
    assert result.isError is False
    assert cast(dict[str, Any], result.structuredContent)["exec_meta"]["errors"][0] == error
    assert calls == []
