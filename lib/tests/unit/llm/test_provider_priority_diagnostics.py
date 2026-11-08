from __future__ import annotations

import importlib
import subprocess
import sys
from typing import Any

import pytest

from blue_data_ops.llm import LLMClient
from blue_data_ops.llm.errors import LLMError
from blue_data_ops.operators.operator import _execution_error  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    "name,message",
    [
        ("ContextWindowExceededError", "model request exceeds the context window"),
        ("ContentPolicyViolationError", "model provider refused the request content"),
    ],
)
def test_specific_provider_class_precedes_bad_request_body(name: str, message: str) -> None:
    if __name__ != "__main__":
        from tests.optional_integrations import require_optional

        require_optional("litellm")
        result = subprocess.run(
            [sys.executable, "-B", __file__, name, message],
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
    cls: Any = vars(exceptions)[name]
    error = cls(message="SYNTHETIC_PRIVATE_PROVIDER_BODY", model="gpt-4o", llm_provider="openai")
    error.body = {"error": {"code": "unsupported_parameter"}}
    calls: list[bool] = []

    def completion(*args: Any, **kwargs: Any) -> Any:
        calls.append(True)
        raise error

    setattr(module, "completion", completion)
    client = LLMClient(
        "openai",
        {
            "openai.model": "gpt-4o",
            "input_field": "messages",
            "input_template": "ordinary",
            "input_json": '[{"role":"user"}]',
            "input_context": "$[0]",
            "input_context_field": "content",
            "output_path": "$.choices[0].message.content",
        },
    )
    with pytest.raises(LLMError) as captured:
        client.execute_api_call({})
    # Preserve the original structured unsupported-parameter transport retry decision.
    assert len(calls) == 1 and captured.value.retryable is False
    record = _execution_error("probe@2.0.0", captured.value)
    assert record.message == message and record.retryable is False
    assert "SYNTHETIC_PRIVATE" not in str(record)


if __name__ == "__main__":
    test_specific_provider_class_precedes_bad_request_body(sys.argv[1], sys.argv[2])
