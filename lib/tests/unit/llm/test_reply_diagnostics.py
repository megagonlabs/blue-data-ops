from __future__ import annotations

import json
import traceback
from typing import Any

import pytest

from blue_data_ops.llm.errors import LLMError
from blue_data_ops.llm.templating import extract_output

MARKER = "SYNTHETIC_PRIVATE_MODEL_RESPONSE"


@pytest.mark.parametrize(
    "kind,value,family",
    [
        ("json", MARKER, json.JSONDecodeError),
        ("json", None, TypeError),
        ("int", MARKER, ValueError),
        ("float", MARKER, ValueError),
    ],
)
@pytest.mark.parametrize("ambient", [False, True])
def test_parser_preserves_family_and_removes_chain(
    kind: str,
    value: Any,
    family: type[Exception],
    ambient: bool,
) -> None:
    def parse() -> None:
        with pytest.raises(family) as captured:
            extract_output({"value": value}, {"output_path": "$.value", "output_cast": kind})
        error = captured.value
        assert not isinstance(error, LLMError)
        assert error.__context__ is None and error.__cause__ is None
        assert MARKER not in str(error.args)
        assert MARKER not in "".join(traceback.format_exception(error))
        if isinstance(error, json.JSONDecodeError):
            assert error.doc == ""

    if ambient:
        try:
            raise RuntimeError(MARKER)
        except RuntimeError:
            parse()
    else:
        parse()


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("json", "[]", []),
        ("json", "null", None),
        ("int", "3", 3),
        ("float", "3.5", 3.5),
        ("bool", "false", "false"),
        ("str", 1, "1"),
    ],
)
def test_cast_controls(kind: str, value: Any, expected: Any) -> None:
    assert (
        extract_output({"value": value}, {"output_path": "$.value", "output_cast": kind})
        == expected
    )


@pytest.mark.parametrize("mode", ["sync", "async", "observed", "cache"])
async def test_client_extraction_boundary_all_paths(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    from blue_data_ops.llm import LLMClient
    from blue_data_ops.llm.client import (
        _InvocationCostObservation,  # pyright: ignore[reportPrivateUsage]
    )

    props: dict[str, Any] = {
        "openai.model": "gpt-4o",
        "input_field": "messages",
        "input_template": "ordinary",
        "input_json": '[{"role":"user"}]',
        "input_context": "$[0]",
        "input_context_field": "content",
        "output_path": "$.choices[0].message.content",
        "output_cast": "json",
    }
    client = LLMClient("openai", props)
    payload = {"choices": [{"message": {"content": MARKER}, "finish_reason": "stop"}]}
    calls: list[str] = []

    def sync(*args: Any, **kwargs: Any) -> Any:
        calls.append("sync")
        return payload, 0.0

    async def asynchronous(*args: Any, **kwargs: Any) -> Any:
        calls.append("async")
        return payload, 0.0

    def cache(*args: Any, **kwargs: Any) -> Any:
        return {"key": payload}, "key"

    monkeypatch.setattr(client, "_call_provider", sync)
    monkeypatch.setattr(client, "_call_provider_observed", sync)
    monkeypatch.setattr(client, "_acall_provider", asynchronous)
    if mode == "cache":
        monkeypatch.setattr(client, "_cache_lookup", cache)
    with pytest.raises(json.JSONDecodeError) as captured:
        if mode == "async":
            await client.aexecute_api_call({})
        elif mode == "observed":
            observation = _InvocationCostObservation()
            client._execute_api_call_observed({}, None, None, observation)  # pyright: ignore[reportPrivateUsage]
            assert observation.complete_cost() is None
        else:
            client.execute_api_call({})
    assert len(calls) == (0 if mode == "cache" else 1)
    assert captured.value.doc == ""
    assert captured.value.__context__ is None and captured.value.__cause__ is None
