from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from blue_data_ops.operators import default_registry, versioned_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli

MARKER = "SYNTHETIC_PRIVATE_SEMANTIC_ROW"
CASES: dict[str, tuple[dict[str, Any], Any]] = {
    "filter": ({"filter_conditions": {"x": "keep"}}, None),
    "extract": ({"entities": [{"name": "k"}]}, []),
    "project": ({"projection_instructions": "keep"}, []),
    "transform": ({"output_desc": {"out": {"description": "target"}}}, {}),
    "join": ({"left_fields": [], "right_fields": [], "estimate_cost": False}, {}),
}


@pytest.mark.parametrize("family", list(CASES))
@pytest.mark.parametrize("version", ["default", "1.0.0", "2.0.0"])
async def test_repaired_family_error_agrees_library_pipeline_cli_mcp(
    family: str,
    version: str,
    tmp_path: Path,
    monkeypatch: Any,
    caplog: Any,
) -> None:
    attrs, bad = CASES[family]
    name = f"semantic_{family}"
    identity = f"{name}@{'1.0.0' if version == 'default' else version}"
    module = importlib.import_module(f"blue_data_ops.operators.{name}_operator")

    class Client:
        def execute_api_call(self, *args: Any, **kwargs: Any) -> Any:
            return bad

    def resolve(properties: Any) -> Any:
        return Client()

    monkeypatch.setattr(module, "resolve_llm_client", resolve)
    registry = default_registry() if version == "default" else versioned_registry()
    op = registry.resolve(identity)
    data = [[{"x": MARKER}]]
    if family == "join":
        data.append([{"y": MARKER}])
    expected = op.run(data, attrs)[2].errors[0]._asdict()
    assert expected["message"] == "model reply did not match the operator's output format"
    assert expected["operator_id"] == identity
    plan = DataPipeline(id="semantic-failure")
    entry = plan.define_input("input")
    step = plan.define_operator(identity, label="step", attributes=attrs)
    out = plan.define_output("output")
    plan.set_plan_input(entry)
    plan.set_plan_output(out)
    plan.connect_nodes(entry, step)
    plan.connect_nodes(step, out)
    portable = json.loads(json.dumps(plan.to_dict()))
    result = PipelineExecutor(registry).execute(plan, data)
    assert result.node_runs[0].exec_meta.errors[0]._asdict() == expected

    def catalog(*args: Any, **kwargs: Any) -> Any:
        return registry

    monkeypatch.setattr(config, "build_catalog", catalog)
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps(data))
    attr_file = tmp_path / "attrs.json"
    attr_file.write_text(json.dumps(attrs))
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(portable))
    runner = CliRunner()
    imported = runner.invoke(
        cli,
        [
            "pipeline",
            "import",
            "probe",
            "--confirm",
            "--pipeline-file",
            str(plan_file),
            "--format",
            "json",
        ],
    )
    assert imported.exit_code == 0, imported.output
    for component, selected in [("operator", identity), ("pipeline", "probe")]:
        args = [component, "run", selected, "--input-file", str(input_file), "--format", "json"]
        if component == "operator":
            args += ["--attributes-file", str(attr_file)]
        value = runner.invoke(cli, args)
        assert value.exit_code == 8, value.output
        detail = json.loads(value.stdout)["error"]["detail"]
        for key in ("category", "operator_id", "stage", "retryable", "suggestion"):
            assert detail[key] == expected[key]
        assert detail["library_code"] == expected["code"]
        assert MARKER not in value.stdout + value.stderr
    assert MARKER not in caplog.text
    if version != "2.0.0":
        return
    memory = importlib.import_module("mcp.shared.memory")
    server_module = importlib.import_module("blue_data_ops_mcp.server")
    server = server_module.create_server(registry=registry, operator_ids=(identity,))
    async with memory.create_connected_server_and_client_session(server) as session:
        wire = await session.call_tool(f"ops_{name}", {"input_data": data, "attributes": attrs})
    assert wire.isError is False
    assert wire.structuredContent["exec_meta"]["errors"][0] == expected
    assert MARKER not in wire.model_dump_json() + caplog.text


@pytest.mark.parametrize("version", ["default", "1.0.0", "2.0.0"])
@pytest.mark.parametrize(
    "family,positive,negative,return_idx",
    [
        ("filter", p, n, idx)
        for p, n in [("true", "false"), ("yes", "no"), ("1", "0"), ("include", "exclude")]
        for idx in [False, True]
    ]
    + [
        ("join", p, n, False)
        for p, n in [("true", "false"), ("yes", "no"), ("1", "0"), ("match", "no")]
    ],
)
@pytest.mark.parametrize("malformed", [False, True])
async def test_legacy_filter_aliases_agree_library_pipeline_cli_mcp(
    version: str,
    family: str,
    positive: str,
    negative: str,
    return_idx: bool,
    malformed: bool,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    module = importlib.import_module(f"blue_data_ops.operators.semantic_{family}_operator")
    clients: list[Client] = []

    class Client:
        def __init__(self) -> None:
            values = [
                f" {positive.upper()} ",
                "maybe" if malformed else f" {negative.upper()} ",
                positive,
                negative,
            ]
            self.replies = iter(
                values
                if family == "filter"
                else [{f"pair_{i}": v for i, v in enumerate(values, 1)}]
            )
            self.calls = 0

        def execute_api_call(self, *args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            return next(self.replies)

    def resolve(properties: Any) -> Any:
        client = Client()
        clients.append(client)
        return client

    monkeypatch.setattr(module, "resolve_llm_client", resolve)
    registry = default_registry() if version == "default" else versioned_registry()
    identity = f"semantic_{family}@{'1.0.0' if version == 'default' else version}"
    attrs = {"filter_conditions": {"x": "keep"}, "return_idx": return_idx}
    data = [[{"x": label} for label in "ABCD"]]
    if family == "join":
        attrs = {**CASES["join"][0], "keep_keys": "both"}
        data.append([{"z": "right"}])
    expected = [[{"indices": [0, 2]}]] if return_idx else [[data[0][0], data[0][2]]]
    if family == "join":
        expected = [[{"x": "A", "z": "right"}, {"x": "C", "z": "right"}]]
    library = registry.resolve(identity).run(data, attrs)
    if malformed:
        assert library[0] == [[]] and len(library[2].errors) == 1
    else:
        assert library[0] == expected and not library[2].errors
    plan = DataPipeline(id="filter-aliases")
    entry = plan.define_input("input")
    step = plan.define_operator(identity, label="step", attributes=attrs)
    out = plan.define_output("output")
    plan.set_plan_input(entry)
    plan.set_plan_output(out)
    plan.connect_nodes(entry, step)
    plan.connect_nodes(step, out)
    portable = json.loads(json.dumps(plan.to_dict()))
    result = PipelineExecutor(registry).execute(plan, data)
    if malformed:
        assert result.node_runs[0].exec_meta.errors == library[2].errors
        assert result.output_data == [[]]
    else:
        assert result.output_data == expected and not result.node_runs[0].exec_meta.errors

    def build_catalog(*args: Any, **kwargs: Any) -> Any:
        return registry

    monkeypatch.setattr(config, "build_catalog", build_catalog)
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps(data))
    attr_file = tmp_path / "attrs.json"
    attr_file.write_text(json.dumps(attrs))
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(portable))
    runner = CliRunner()
    imported = runner.invoke(
        cli,
        [
            "pipeline",
            "import",
            "aliases",
            "--confirm",
            "--pipeline-file",
            str(plan_file),
            "--format",
            "json",
        ],
    )
    assert imported.exit_code == 0, imported.output
    for component, selected in [("operator", identity), ("pipeline", "aliases")]:
        args = [component, "run", selected, "--input-file", str(input_file), "--format", "json"]
        if component == "operator":
            args += ["--attributes-file", str(attr_file)]
        value = runner.invoke(cli, args)
        assert value.exit_code == (8 if malformed else 0), value.output
        payload = json.loads(value.stdout)
        if malformed:
            assert payload["error"]["detail"]["library_code"] == "EXECUTION_FAILED"
        else:
            assert payload["result"]["output_data"] == expected
    if version == "2.0.0":
        memory = importlib.import_module("mcp.shared.memory")
        server_module = importlib.import_module("blue_data_ops_mcp.server")
        server = server_module.create_server(registry=registry, operator_ids=(identity,))
        async with memory.create_connected_server_and_client_session(server) as session:
            wire = await session.call_tool(
                f"ops_semantic_{family}", {"input_data": data, "attributes": attrs}
            )
        assert wire.isError is False
        assert wire.structuredContent["output_data"] == ([[]] if malformed else expected)
        assert wire.structuredContent["exec_meta"]["errors"] == [
            e._asdict() for e in library[2].errors
        ]
    assert all(
        client.calls == (1 if family == "join" else (2 if malformed else 4)) for client in clients
    )
