"""Exercise installed LiteLLM exception types in an isolated offline process."""

from __future__ import annotations

import asyncio
import importlib
import subprocess
import sys
from typing import Any, cast

import pytest


@pytest.mark.parametrize("mode", ["sync", "async", "observed"])
def test_installed_litellm_temperature_refusals(mode: str) -> None:
    if __name__ != "__main__":
        from tests.optional_integrations import require_optional

        require_optional("litellm")
        process = subprocess.run(
            [sys.executable, "-B", __file__, mode], capture_output=True, text=True, timeout=25
        )
        assert process.returncode == 0, process.stdout + process.stderr
        return
    module: Any = importlib.import_module("litellm")

    from blue_data_ops.llm import LLMClient, prepare_llm_operator_properties
    from blue_data_ops.llm.client import (
        _InvocationCostObservation,  # pyright: ignore[reportPrivateUsage]
    )

    assert "site-packages/litellm/" in module.__file__
    for message in (
        "gpt-6.1-sol doesn't support temperature=0 while reasoning is active. "
        "Only temperature=1 is supported",
        "O-series models don't support temperature=0. Only temperature=1 is supported.",
        "model does not support parameters: ['temperature']",
        None,
    ):
        calls: list[dict[str, Any]] = []

        def completion(**kwargs: Any) -> dict[str, Any]:
            calls.append(dict(kwargs))
            if len(calls) == 1:
                if message is None:
                    raise module.BadRequestError(
                        message="private detail",
                        model="gpt-6.1-sol",
                        llm_provider="openai",
                        body={"error": {"code": "unsupported_value", "param": "temperature"}},
                    )
                raise module.UnsupportedParamsError(
                    message=message, model="gpt-6.1-sol", llm_provider="openai"
                )
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            }

        async def acompletion(**kwargs: Any) -> dict[str, Any]:
            return completion(**kwargs)

        setattr(module, "completion", completion)
        setattr(module, "acompletion", acompletion)

        def price(**kwargs: Any) -> float:
            return 0.125

        setattr(module, "completion_cost", price)
        defaults = {
            "service_prefix": "openai",
            "openai.temperature": 0,
            "openai.model": "gpt-4o",
            "input_field": "messages",
            "input_template": "Reply OK",
            "input_json": '[{"role":"user"}]',
            "input_context": "$[0]",
            "input_context_field": "content",
            "output_path": "$.choices[0].message.content",
        }
        caller = {"llm.model": "gpt-6.1-sol", "llm.reasoning_effort": "low"}
        props = prepare_llm_operator_properties({**defaults, **caller}, defaults, caller)
        client = LLMClient("test", props)
        observation = _InvocationCostObservation()
        if mode == "async":
            result = asyncio.run(client.aexecute_api_call({}, props))
        elif mode == "observed":
            result = cast(Any, client)._execute_api_call_observed({}, props, None, observation)
        else:
            result = client.execute_api_call({}, props)
        assert result == "ok" and len(calls) == 2
        assert calls[0]["temperature"] == 0 and "temperature" not in calls[1]
        if mode == "observed":
            assert observation.provider_attempts == 2
            assert observation.complete_cost() == (0.125 if message else None)
    print("installed LiteLLM: four refusal forms passed", mode)


if __name__ == "__main__":
    test_installed_litellm_temperature_refusals(sys.argv[1])
