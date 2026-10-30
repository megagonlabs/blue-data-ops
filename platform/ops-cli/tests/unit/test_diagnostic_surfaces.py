from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from blue_data_ops.data.errors import RegistryFailure, RegistryReason
from blue_data_ops.llm.client import _provider_error  # pyright: ignore[reportPrivateUsage]
from blue_data_ops.llm.templating import extract_output
from blue_data_ops.operators import Operator, OperatorRegistry
from blue_data_ops.operators.types import Attributes, DataBundle, Properties
from blue_data_ops.plan import DataPipeline, PipelineExecutor
from click.testing import CliRunner

from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli

MARKER = "SYNTHETIC_PRIVATE_SQL_REPLY_ROW_TARGET_PATH"


class Failure(Operator):
    name = "diagnostic_surface"
    description = "Local canonical-body diagnostic fixture."
    attributes = {}

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def apply(
        self, input_data: DataBundle, attributes: Attributes, properties: Properties | None = None
    ) -> DataBundle:
        raise self.error


def pipeline(identity: str) -> DataPipeline:
    plan = DataPipeline(id="diagnostic-surface")
    entry = plan.define_input("input")
    step = plan.define_operator(identity, label="step", attributes={})
    out = plan.define_output("output")
    plan.set_plan_input(entry)
    plan.set_plan_output(out)
    plan.connect_nodes(entry, step)
    plan.connect_nodes(step, out)
    return plan


def owned_error(kind: str, tmp_path: Path) -> tuple[Exception, str]:
    private = f"{MARKER} {tmp_path}"
    if kind == "reply":
        try:
            extract_output({"value": private}, {"output_path": "$.value", "output_cast": "json"})
        except json.JSONDecodeError as error:
            return error, "model reply did not match the operator's output format"
        raise AssertionError("invalid reply was accepted")
    if kind == "driver":
        return sqlite3.IntegrityError(private), "database constraint rejected the operation"
    if kind == "provider":
        module = importlib.import_module("litellm")
        assert module.__file__ and "site-packages/litellm/" in module.__file__
        error = module.RateLimitError(private, "gpt-4o", "openai")
        import httpx
        import openai

        response = httpx.Response(429, request=httpx.Request("POST", "https://unit.invalid"))
        error.__cause__ = openai.RateLimitError(private, response=response, body=None)
        return _provider_error(
            error, module.UnsupportedParamsError, module.BadRequestError
        ), "model provider rate limit reached"
    if kind == "target":
        reason = RegistryReason("DATABASE_ABSENT")
        return RegistryFailure(reason), "database is not available in the declared source"
    if kind == "custom":
        module = importlib.import_module("blue_data_ops")
        cls: Any = vars(module).get("OperatorExecutionError")
        assert isinstance(cls, type), "intentional custom diagnostic is absent"
        return cls("fixed public message", suggestion="fixed public action"), "fixed public message"
    return RuntimeError(private), "operator execution failed"


@pytest.mark.parametrize("kind", ["reply", "driver", "provider", "target", "custom", "generic"])
@pytest.mark.parametrize("with_log", [False, True])
async def test_owned_diagnostics_agree_through_run_pipeline_cli_and_mcp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    kind: str,
    with_log: bool,
) -> None:
    error, expected_message = owned_error(kind, tmp_path)
    operator = Failure(error)
    registry = OperatorRegistry()
    registry.register(operator, "2.0.0")
    expected = operator.run([[{"private": MARKER}]], {})[2].errors[0]._asdict()
    assert expected["message"] == expected_message
    run = PipelineExecutor(registry).execute(
        pipeline(operator.operator_id), [[{"private": MARKER}]]
    )
    assert run.node_runs[0].exec_meta.errors[0]._asdict() == expected

    def catalog(*args: Any, **kwargs: Any) -> OperatorRegistry:
        return registry

    monkeypatch.setattr(config, "build_catalog", catalog)
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps([[{"private": MARKER}]]))
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(pipeline(operator.operator_id).to_dict()))
    runner = CliRunner()
    imported = runner.invoke(
        cli,
        ["pipeline", "import", "diagnostic", "--pipeline-file", str(plan_file), "--format", "json"],
    )
    assert imported.exit_code == 0, imported.output
    for component, identity in [("operator", operator.operator_id), ("pipeline", "diagnostic")]:
        args = [component, "run", identity, "--input-file", str(input_file), "--format", "json"]
        if with_log:
            args.append("--log")
        result = runner.invoke(cli, args)
        assert result.exit_code == 8, result.output
        document = json.loads(result.stdout)
        assert expected_message in document["error"]["message"]
        detail = document["error"]["detail"]
        for key in ("category", "operator_id", "stage", "retryable", "suggestion"):
            assert detail[key] == expected[key]
        assert detail["library_code"] == expected["code"]
        assert MARKER not in result.stdout + result.stderr
        assert str(tmp_path) not in result.stdout + result.stderr
    memory: Any = importlib.import_module("mcp.shared.memory")
    server_module: Any = importlib.import_module("blue_data_ops_mcp.server")
    server = server_module.create_server(registry=registry, operator_ids=(operator.operator_id,))
    async with memory.create_connected_server_and_client_session(server) as client:
        wire = await client.call_tool(
            "ops_diagnostic_surface", {"input_data": [[{"private": MARKER}]]}
        )
    assert wire.isError is False
    assert wire.structuredContent["exec_meta"]["errors"][0] == expected
    assert MARKER not in wire.model_dump_json() + caplog.text
    assert str(tmp_path) not in wire.model_dump_json() + caplog.text
