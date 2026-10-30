"""An unknown ``llm.*`` setting is ``bad_override``; reserved controls stay ``reserved_field``.

The early caller-control check runs before any registry, client, cache or provider work.
Its diagnostic is fixed text owned by the package, so a caller-chosen key never comes back
in the error.
"""

from __future__ import annotations

from typing import Any

import pytest

from blue_data_ops.llm import LLMClient
from blue_data_ops.llm.client import (
    RESERVED_OPERATOR_LLM_CONTROLS,
    validate_llm_caller_controls,
)
from blue_data_ops.llm.errors import LLMError
from blue_data_ops.operators import versioned_registry

UNKNOWN = [
    "llm.max_token",
    "llm.api_key",
    "llm.mock_response",
    "llm.MODEL",
    "llm.",
    "llm.<caller-chosen-name>",
]
EXPECTED_MESSAGE = (
    "unsupported llm.* override; accepted: llm.cache, llm.cache_dir, llm.max_parallel, "
    "llm.max_tokens, llm.model, llm.rate_limit, llm.reasoning_effort, llm.stream, "
    "llm.temperature"
)


class Counting(LLMClient):
    def __init__(self) -> None:
        self.calls = 0

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ):
        self.calls += 1
        return "unused"


@pytest.mark.parametrize("key", UNKNOWN)
@pytest.mark.parametrize("value", [5, None, "x"])
def test_unknown_llm_setting_is_bad_override_without_echo(key: str, value: Any) -> None:
    with pytest.raises(LLMError) as raised:
        validate_llm_caller_controls({key: value})
    assert raised.value.code == "bad_override"
    assert raised.value.retryable is False
    # One fixed message for every unknown key, so nothing the caller chose is echoed.
    assert str(raised.value) == EXPECTED_MESSAGE


def test_the_accepted_llm_settings_pass() -> None:
    validate_llm_caller_controls(
        {
            "llm.model": "m",
            "llm.stream": False,
            "llm.max_tokens": 5,
            "llm.temperature": 0,
            "llm.reasoning_effort": None,
            "llm.cache": False,
            "llm.cache_dir": "x",
            "llm.max_parallel": 1,
            "llm.rate_limit": 1,
        }
    )


@pytest.mark.parametrize("key", sorted(RESERVED_OPERATOR_LLM_CONTROLS))
@pytest.mark.parametrize("value", [None, "x"])
def test_named_template_and_transport_controls_stay_reserved(key: str, value: Any) -> None:
    with pytest.raises(LLMError) as raised:
        validate_llm_caller_controls({key: value})
    assert raised.value.code == "reserved_field"


@pytest.mark.parametrize("key", ["openai.x", "openai.api_key", "openai.mock_response"])
def test_unknown_provider_prefixed_settings_stay_reserved(key: str) -> None:
    with pytest.raises(LLMError) as raised:
        validate_llm_caller_controls({key: None})
    assert raised.value.code == "reserved_field"


@pytest.mark.parametrize(
    ("operator_id", "attributes"),
    [
        ("nl2llm@3.0.0", {"query": "hello"}),
        ("nl2llm@2.0.0", {"query": "hello"}),
        ("semantic_filter@1.0.0", {"filter_conditions": {"id": "is one"}}),
    ],
)
def test_operator_run_projects_bad_override_before_any_client_call(
    operator_id: str, attributes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no client or registry may be resolved")

    operator = versioned_registry().resolve(operator_id)
    for module_name, module in list(sys.modules.items()):
        if module_name.startswith("blue_data_ops."):
            for name in ("resolve_llm_client", "resolve_registry"):
                if hasattr(module, name):
                    monkeypatch.setattr(module, name, forbidden)
    client = Counting()
    output, _, meta = operator.run(
        [[{"id": 1}]], attributes, {"llm_client": client, "llm.max_token": 5}
    )
    assert output == [[]]
    [error] = meta.errors
    assert error.code.name == "EXECUTION_FAILED"
    assert error.message == "LLM setting is not supported"
    assert error.suggestion == "Use a documented llm.* or provider generation setting."
    assert error.retryable is False
    assert client.calls == 0
    assert "max_token" not in str(meta.errors)
