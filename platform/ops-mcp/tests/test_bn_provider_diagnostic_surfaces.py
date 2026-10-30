from __future__ import annotations

import asyncio
import importlib
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from blue_data_ops.data import RegistrySeam
from blue_data_ops.operators import active_registry, default_registry, versioned_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor
from blue_data_ops_cli import config
from blue_data_ops_cli.commands import cli
from click.testing import CliRunner
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_mcp.server import create_server

PROVIDER = "SYNTHETIC_PRIVATE_BN_PROVIDER_DETAIL"
SOURCE = "SYNTHETIC_PRIVATE_BN_SOURCE_DETAIL"
INPUT = "SYNTHETIC_PRIVATE_BN_INPUT_DETAIL"
CASES = {
    "auth-zero": ("model provider rejected its credentials", 0, 3),
    "settings-zero": ("model rejected a requested generation setting", 0, 0),
    "auth-default": ("model provider rejected its credentials", 2, 6),
    "settings-default": ("model rejected a requested generation setting", 2, 0),
    "recovered-malformed": ("model reply did not match the operator's output format", 2, 5),
    "malformed-control": ("model reply did not match the operator's output format", 2, 3),
    "later-auth": ("model provider rejected its credentials", 2, 4),
}


@pytest.mark.parametrize("selector", ["1.0.0", "2.0.0", "3.0.0", "default", "active"])
@pytest.mark.parametrize("case", list(CASES))
def test_real_provider_bn_diagnostics_across_four_surfaces(
    selector: str,
    case: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    asyncio.run(check_surfaces(selector, case, tmp_path, caplog))


async def check_surfaces(
    selector: str, case: str, directory: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    lite = importlib.import_module("litellm")
    assert lite.__file__ and "site-packages/litellm/" in lite.__file__
    if selector == "default":
        catalog, identity = default_registry(), "nl2bn@1.0.0"
    elif selector == "active":
        catalog, identity = active_registry(), "nl2bn@3.0.0"
    else:
        catalog, identity = versioned_registry(), "nl2bn@" + selector
    operator = catalog.resolve(identity)
    expected_class = "NL2BNOutcomeOperator" if identity.endswith("3.0.0") else "NL2BNOperator"
    assert type(operator).__name__ == expected_class
    data_registry = importlib.import_module("blue_data.registry.data_registry").DataRegistry
    memory_source = importlib.import_module(
        "blue_data.source.json.memory_json_source"
    ).MemoryJSONSource
    registry = data_registry(store=memory_source(), rebuild=False)
    registry.register_source(memory_source(SOURCE))
    seam = RegistrySeam(registry)
    message, budget, expected_calls = CASES[case]
    attrs = {
        "source": SOURCE,
        "database": "db",
        "collection": "public",
        "question": "synthetic",
        "protocol_variant": "pgmpy",
        "schema": "synthetic schema",
        "max_corrections": budget,
    }
    settings: dict[str, Any] = {"llm.model": "gpt-5-mini", "llm.reasoning_effort": "low"}
    if case.startswith("settings"):
        settings["llm.temperature"] = 0
    properties = {"data_registry": seam, **settings}
    calls: list[dict[str, Any]] = []
    caplog.clear()

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if case.startswith("settings"):
            raise AssertionError("rejected setting reached provider")
        if (
            case in {"auth-zero", "auth-default"}
            or (case == "recovered-malformed" and len(calls) <= 3)
            or (case == "later-auth" and len(calls) > 1)
        ):
            raise lite.AuthenticationError(
                message=PROVIDER, model="gpt-5-mini", llm_provider="openai"
            )
        return {"choices": [{"message": {"content": '{"wrong":true}'}}], "usage": {}}

    def assert_calls() -> None:
        assert len(calls) == expected_calls
        for call in calls:
            for marker in (PROVIDER, SOURCE, INPUT):
                assert marker not in json.dumps(call)
        calls.clear()

    with patch.object(lite, "completion", completion):
        result = operator.run([[{"private": INPUT}]], attrs, properties)
        expected = result[2].errors[0]._asdict()
        assert expected == {
            "category": "FAILED",
            "code": "EXECUTION_FAILED",
            "stage": "EXECUTE",
            "operator_id": identity,
            "message": message,
            "suggestion": (
                "Check the provider credential in the deployment environment."
                if "credentials" in message
                else (
                    "For temperature, set llm.temperature=null; otherwise remove the unsupported "
                    "setting or choose a compatible model."
                )
                if "generation setting" in message
                else (
                    "Simplify the request or choose a model that follows "
                    "the required output format."
                )
            ),
            "retryable": False,
        }
        assert_calls()
        plan = DataPipeline(id="bn-diagnostics")
        entry = plan.define_input("input")
        step = plan.define_operator(identity, label="step", attributes=attrs)
        output = plan.define_output("output")
        plan.set_plan_input(entry)
        plan.set_plan_output(output)
        plan.connect_nodes(entry, step)
        plan.connect_nodes(step, output)
        execution = PipelineExecutor(catalog).execute(
            plan, [[{"private": INPUT}]], properties=properties
        )
        assert execution.node_runs[0].exec_meta.errors[0]._asdict() == expected
        assert_calls()
        (directory / "input.json").write_text(json.dumps([[{"private": INPUT}]]))
        (directory / "attrs.json").write_text(json.dumps(attrs))
        args = [
            "operator",
            "run",
            identity,
            "--input-file",
            str(directory / "input.json"),
            "--attributes-file",
            str(directory / "attrs.json"),
            "--format",
            "json",
        ]
        for key, value in settings.items():
            args.extend(["--property", key + "=" + json.dumps(value)])
        with (
            patch.object(
                config,
                "build_catalog",
                return_value=versioned_registry() if selector == "default" else catalog,
            ),
            patch.object(config, "build_registry_seam", return_value=seam),
        ):
            cli_result = CliRunner().invoke(cli, args)
        assert cli_result.exit_code == 8
        cli_text = cli_result.stdout
        json_start = cli_text.rfind("\n{") + 1
        cli_wire = json.loads(cli_text[json_start:])
        assert message in cli_wire["error"]["message"]
        assert_calls()
        if identity.endswith("1.0.0"):
            with pytest.raises(ValueError, match="supports exact v2/v3 selections only"):
                create_server(registry=catalog, data_registry=seam, operator_ids=(identity,))
            wire = {"v1_selection": "rejected by existing MCP contract"}
        else:
            server = create_server(registry=catalog, data_registry=seam, operator_ids=(identity,))
            transport = create_connected_server_and_client_session(getattr(server, "_mcp_server"))
            async with transport as client:
                mcp_result = await client.call_tool(
                    "ops_nl2bn",
                    {
                        "input_data": [[{"private": INPUT}]],
                        "attributes": attrs,
                        "properties": settings,
                    },
                )
            wire = mcp_result.structuredContent
            assert wire is not None and wire["exec_meta"]["errors"][0] == expected
            assert_calls()
    for marker in (PROVIDER, SOURCE, INPUT):
        assert marker not in json.dumps([expected, cli_wire, wire])
        assert marker not in cli_result.stdout + cli_result.stderr
        assert marker not in caplog.text
