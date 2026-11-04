"""Inherited temperature recovery through the public invocation surfaces."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import litellm
import pytest
from blue_data_ops.operators import active_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor
from blue_data_ops_cli.commands import cli
from click.testing import CliRunner
from litellm.exceptions import BadRequestError, UnsupportedParamsError
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_mcp.server import create_server


@pytest.mark.parametrize("surface", ["operator", "pipeline", "cli", "mcp"])
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("rejection_kind", ["local", "provider"])
def test_temperature_fallback_on_public_surfaces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    surface: str,
    explicit: bool,
    rejection_kind: str,
) -> None:
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        if "temperature" in kwargs:
            if rejection_kind == "provider":
                raise BadRequestError(
                    message="synthetic provider rejection",
                    model="gpt-6.1-sol",
                    llm_provider="openai",
                    body={"error": {"code": "unsupported_value", "param": "temperature"}},
                )
            raise UnsupportedParamsError(
                message="model doesn't support temperature=0",
                model="gpt-6.1-sol",
                llm_provider="openai",
            )
        return {
            "choices": [{"message": {"content": '[{"product":"example"}]'}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }

    monkeypatch.setattr(litellm, "completion", completion)

    def price(**kwargs: Any) -> float:
        return 0.125

    monkeypatch.setattr(litellm, "completion_cost", price)
    props: dict[str, Any] = {"llm.model": "gpt-6.1-sol", "llm.reasoning_effort": "low"}
    if explicit:
        props["llm.temperature"] = 0
    if surface == "operator":
        out, _, meta = (
            active_registry()
            .resolve("nl2llm@3.0.0")
            .run([[]], {"query": "Return one product"}, props)
        )
        success = not meta.errors
        if success:
            assert out == [[{"product": "example"}]]
    elif surface == "pipeline":
        plan = DataPipeline(properties=props)
        src = plan.define_input("rows")
        node = plan.define_operator("nl2llm@3.0.0", attributes={"query": "Return one product"})
        dst = plan.define_output("result")
        plan.set_plan_input(src)
        plan.set_plan_output(dst)
        plan.connect_nodes(src, node)
        plan.connect_nodes(node, dst)
        run = PipelineExecutor(active_registry()).execute(
            DataPipeline.from_dict(plan.to_dict()), [[]]
        )
        success = run.succeeded
    elif surface == "cli":
        data = tmp_path / "input.json"
        data.write_text("[[]]")
        options = [
            "operator",
            "run",
            "nl2llm@3.0.0",
            "--input-file",
            str(data),
            "--attribute",
            "query=Return one product",
            "--model",
            "gpt-6.1-sol",
            "--reasoning-effort",
            "low",
            "--format",
            "json",
        ]
        if explicit:
            options += ["--property", "llm.temperature=0"]
        result = CliRunner().invoke(cli, options)
        success = result.exit_code == 0
        if explicit:
            assert "llm.temperature=null" in result.stdout
    else:

        async def request() -> bool:
            server = create_server(operator_ids=("nl2llm@3.0.0",))
            async with create_connected_server_and_client_session(
                cast(Any, server)._mcp_server
            ) as client:
                result = await client.call_tool(
                    "ops_nl2llm",
                    {
                        "input_data": [[]],
                        "attributes": {"query": "Return one product"},
                        "properties": props,
                    },
                )
            return not cast(dict[str, Any], result.structuredContent)["exec_meta"]["errors"]

        success = asyncio.run(request())
    assert success is not explicit
    assert len(calls) == (1 if explicit else 2)
