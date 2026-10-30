from __future__ import annotations

import asyncio
import importlib
import subprocess
import sys
from typing import Any

import pytest

from blue_data_ops.llm import LLMClient
from blue_data_ops.llm.client import (
    _InvocationCostObservation,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.llm.errors import LLMError
from blue_data_ops.operators.operator import _execution_error  # pyright: ignore[reportPrivateUsage]

MARKER = "SYNTHETIC_PRIVATE_PROVIDER_RESPONSE"


def _attach_retry_evidence(error: Any, name: str) -> None:
    import httpx
    import openai

    if name == "APIConnectionError":
        error.__cause__ = httpx.ConnectError(MARKER)
    elif name == "Timeout":
        error.__cause__ = httpx.ReadTimeout(MARKER)
    elif name in {"RateLimitError", "ServiceUnavailableError", "InternalServerError"}:
        status = 429 if name == "RateLimitError" else 503
        response = httpx.Response(status, request=httpx.Request("POST", "https://unit.invalid"))
        cls = openai.RateLimitError if status == 429 else openai.InternalServerError
        error.__cause__ = cls(MARKER, response=response, body=None)


@pytest.mark.parametrize("mode", ["sync", "async", "observed"])
def test_genuine_provider_transport_attempts_and_diagnostics(mode: str) -> None:
    if __name__ != "__main__":
        result = subprocess.run(
            [sys.executable, "-B", __file__, mode],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    module = importlib.import_module("litellm")
    exceptions = importlib.import_module("litellm.exceptions")
    assert exceptions.__file__ and "site-packages/litellm/exceptions.py" in exceptions.__file__
    cases = [
        ("ContextWindowExceededError", "model request exceeds the context window", False),
        ("ContentPolicyViolationError", "model provider refused the request content", False),
        ("RateLimitError", "model provider rate limit reached", True),
        ("Timeout", "model provider timed out", True),
        ("APIConnectionError", "model provider connection failed", True),
        ("ServiceUnavailableError", "model provider is temporarily unavailable", True),
        ("InternalServerError", "model provider is temporarily unavailable", True),
        ("AuthenticationError", "model provider rejected its credentials", False),
        ("NotFoundError", "model provider could not find the requested model", False),
        ("BadRequestError", "model provider request failed", False),
        ("UnsupportedParamsError", "model rejected a requested generation setting", False),
    ]
    for name, message, retryable in cases:
        cls: Any = vars(exceptions)[name]
        error = cls(message=MARKER, model="gpt-4o", llm_provider="openai")
        _attach_retry_evidence(error, name)
        calls: list[bool] = []

        def completion(*args: Any, **kwargs: Any) -> Any:
            calls.append(True)
            raise error

        async def acompletion(*args: Any, **kwargs: Any) -> Any:
            return completion(*args, **kwargs)

        setattr(module, "completion", completion)
        setattr(module, "acompletion", acompletion)
        props: dict[str, Any] = {
            "openai.model": "gpt-4o",
            "input_field": "messages",
            "input_template": "ordinary",
            "input_json": '[{"role":"user"}]',
            "input_context": "$[0]",
            "input_context_field": "content",
            "output_path": "$.choices[0].message.content",
        }
        client = LLMClient("openai", props)
        observation = _InvocationCostObservation()
        with pytest.raises(LLMError) as captured:
            if mode == "sync":
                client.execute_api_call({})
            elif mode == "async":
                asyncio.run(client.aexecute_api_call({}))
            else:
                client._execute_api_call_observed({}, None, None, observation)  # pyright: ignore[reportPrivateUsage]
        record = _execution_error("probe@2.0.0", captured.value)
        assert record.message == message and record.retryable is retryable
        assert MARKER not in str(record)
        assert len(calls) == (1 if name == "UnsupportedParamsError" else 3)
        assert observation.complete_cost() is None
        assert client.ledger.records == []


if __name__ == "__main__":
    test_genuine_provider_transport_attempts_and_diagnostics(sys.argv[1])
