from __future__ import annotations

import copy
import importlib
import json
import logging
from functools import lru_cache
from typing import Any
from unittest.mock import patch

import pytest

from blue_data_ops import ErrorCategory, ErrorCode, ErrorStage, FunctionResult
from blue_data_ops.data import RegistrySeam
from blue_data_ops.llm import LLMClient, LLMError
from blue_data_ops.llm.errors import is_reply_failure
from blue_data_ops.operators import (
    NL2BNOperator,
    active_registry,
    default_registry,
    versioned_registry,
)
from tests.doubles.data import RegistrySeamDouble

SELECTORS = ["1.0.0", "2.0.0", "3.0.0", "default", "active"]
REPLY_MESSAGE = "model reply did not match the operator's output format"
PRIVATE = "SYNTHETIC_PRIVATE_BN_BACKEND"
ATTRS = {
    "source": "bn",
    "database": "db",
    "collection": "public",
    "question": "synthetic",
    "protocol_variant": "pgmpy",
    "schema": "synthetic schema",
}
VALID: dict[str, Any] = {"target_node": "wet", "target_state": "yes", "context": {}}


class ScriptedClient(LLMClient):
    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(dict(additional_data or {}))
        assert self.replies, "unexpected additional provider call"
        value = self.replies.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class RecordingSeam(RegistrySeamDouble, RegistrySeam):
    pass


@lru_cache
def selected(selector: str) -> Any:
    if selector == "default":
        operator = default_registry().resolve("nl2bn@1.0.0")
    elif selector == "active":
        operator = active_registry().resolve("nl2bn@3.0.0")
    else:
        operator = versioned_registry().resolve("nl2bn@" + selector)
    if selector in {"1.0.0", "2.0.0", "default"}:
        assert type(operator) is NL2BNOperator
        assert operator.operator_id == "nl2bn@" + ("1.0.0" if selector == "default" else selector)
    else:
        assert type(operator).__module__ == "blue_data_ops.operators._nl2bn_outcome"
        assert type(operator).__name__ == "NL2BNOutcomeOperator"
        assert operator.operator_id == "nl2bn@3.0.0"
    return operator


def setup(replies: list[Any]) -> tuple[ScriptedClient, RecordingSeam, dict[str, Any]]:
    client = ScriptedClient(replies)
    seam = RecordingSeam()
    seam.query_result = [{"probability": 0.75}]
    return client, seam, {"llm_client": client, "data_registry": seam}


def assert_public(meta: Any, identity: str, message: str) -> None:
    assert len(meta.errors) == 1
    error = meta.errors[0]
    assert error.category is ErrorCategory.FAILED
    assert error.code is ErrorCode.EXECUTION_FAILED
    assert error.stage is ErrorStage.EXECUTE
    assert error.operator_id == identity
    assert error.message == message
    assert error.retryable is False
    assert error.suggestion
    assert PRIVATE not in json.dumps(error._asdict())


@pytest.mark.parametrize("selector", SELECTORS)
def test_resolved_bn_classes_and_selections(selector: str) -> None:
    selected(selector)


@pytest.mark.parametrize("selector", SELECTORS)
@pytest.mark.parametrize("surface", ["apply", "invoke", "run"])
@pytest.mark.parametrize(
    "code,message",
    [
        ("provider_credentials", "model provider rejected its credentials"),
        ("unsupported_parameter", "model rejected a requested generation setting"),
        ("unrecognized_bn_code", "LLM request failed"),
    ],
)
def test_zero_budget_preserves_original_typed_error(
    selector: str, surface: str, code: str, message: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    original = LLMError(PRIVATE, code=code, provider_error=PRIVATE, retryable=False)
    client, seam, properties = setup([original])
    operator = selected(selector)
    attrs = {**ATTRS, "max_corrections": 0}
    if surface == "run":
        _, _, meta = operator.run([[]], attrs, properties)
        assert_public(meta, operator.operator_id, message)
    else:
        with pytest.raises(LLMError) as captured:
            getattr(operator, surface)([[]], attrs, properties)
        assert captured.value is original
        assert captured.value.code == code and captured.value.retryable is False
        assert captured.value.provider_error == PRIVATE
        assert captured.value.__cause__ is None
    assert len(client.calls) == 1
    assert seam.calls_to("execute_query") == []
    assert PRIVATE not in caplog.text


@pytest.mark.parametrize("selector", SELECTORS)
@pytest.mark.parametrize("surface", ["apply", "invoke", "run"])
@pytest.mark.parametrize(
    "malformed,correction_calls",
    [
        ("{", 1),
        ("42", 1),
        ('["target_node", "target_state"]', 1),
        (17, 1),
        (["target_node", "target_state"], 1),
        ({"target_node": "wet"}, 2),
        ({"target_state": "yes"}, 2),
    ],
)
def test_successful_malformed_correction_clears_service_provenance(
    selector: str,
    surface: str,
    malformed: Any,
    correction_calls: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    original = LLMError(PRIVATE, code="provider_credentials", provider_error=PRIVATE)
    client, seam, properties = setup([original, malformed, malformed])
    operator = selected(selector)
    if surface == "run":
        _, _, meta = operator.run([[]], ATTRS, properties)
        assert_public(meta, operator.operator_id, REPLY_MESSAGE)
    else:
        with pytest.raises(ValueError, match=REPLY_MESSAGE) as captured:
            getattr(operator, surface)([[]], ATTRS, properties)
        assert is_reply_failure(captured.value)
        assert captured.value.__context__ is None
        assert captured.value.__cause__ is None
    assert len(client.calls) == correction_calls + 1
    assert seam.calls_to("execute_query") == []
    for call in client.calls[1:]:
        assert set(call) == {"question", "original_query", "validation_errors", "schema_section"}
        assert PRIVATE not in json.dumps(call)
    assert "Service error:" in client.calls[1]["validation_errors"]
    assert PRIVATE not in caplog.text


@pytest.mark.parametrize("selector", SELECTORS)
@pytest.mark.parametrize("surface", ["apply", "invoke", "run"])
@pytest.mark.parametrize("malformed", ["42", "[]", "{", 3, [], {}, {"target_state": "yes"}])
def test_initial_malformed_reply_uses_format_correction(
    selector: str, surface: str, malformed: Any
) -> None:
    client, _, properties = setup([malformed, dict(VALID)])
    operator = selected(selector)
    value = getattr(operator, surface)([[]], ATTRS, properties)
    output = value[0] if surface == "run" else value
    assert output == [[{"prob": 0.75, "query": VALID}]]
    assert len(client.calls) == 2
    if surface == "run":
        assert value[2].errors == []


@pytest.mark.parametrize("selector", SELECTORS)
@pytest.mark.parametrize("surface", ["apply", "invoke", "run"])
@pytest.mark.parametrize("scenario", ["unknown", "default-auth", "default-setting", "later-error"])
def test_unknown_and_later_correction_failures_keep_call_order(
    selector: str, surface: str, scenario: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    if scenario == "unknown":
        original: Exception = RuntimeError(PRIVATE)
        replies = [original]
        budget = 0
        message = "operator execution failed"
        count = 1
    else:
        code = "unsupported_parameter" if scenario == "default-setting" else "provider_credentials"
        original = LLMError(PRIVATE, code=code, retryable=False)
        replies = (
            [{"target_state": "yes"}, original]
            if scenario == "later-error"
            else [original, original]
        )
        budget = 2
        message = (
            "model rejected a requested generation setting"
            if scenario == "default-setting"
            else "model provider rejected its credentials"
        )
        count = 2
    client, seam, properties = setup(replies)
    operator = selected(selector)
    attrs = {**ATTRS, "max_corrections": budget}
    if surface == "run":
        _, _, meta = operator.run([[]], attrs, properties)
        assert_public(meta, operator.operator_id, message)
    else:
        with pytest.raises(Exception) as captured:
            getattr(operator, surface)([[]], attrs, properties)
        if scenario == "unknown":
            assert type(captured.value) is ValueError
            assert not is_reply_failure(captured.value)
            assert PRIVATE not in str(captured.value)
        else:
            assert captured.value is original
    assert len(client.calls) == count
    assert seam.calls_to("execute_query") == []
    assert PRIVATE not in caplog.text
    assert PRIVATE not in json.dumps(client.calls)


@pytest.mark.parametrize("selector", SELECTORS)
def test_empty_question_and_custom_dispatch_identity(selector: str) -> None:
    operator = copy.copy(selected(selector))
    client, _, properties = setup([])
    assert operator.apply([[]], {**ATTRS, "question": " "}, properties) == [[]]
    assert client.calls == []
    output = [[{"custom": True}]]
    attributes = {"original": True}
    props = {"custom": object()}
    calls: list[Any] = []

    def execute(*args: Any) -> FunctionResult:
        calls.append(args)
        return FunctionResult(output, {})

    operator._execute = execute
    assert operator.apply([[]], attributes, props) is output
    assert calls == [([[]], attributes, props)]


@pytest.mark.parametrize("selector", SELECTORS)
@pytest.mark.parametrize("surface", ["apply", "invoke", "run"])
def test_typed_initial_error_then_valid_correction(
    selector: str, surface: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    original = LLMError(PRIVATE, code="provider_credentials", provider_error=PRIVATE)
    query = dict(VALID)
    client, _, properties = setup([original, query])
    value = getattr(selected(selector), surface)([[]], ATTRS, properties)
    output = value[0] if surface == "run" else value
    assert output == [[{"prob": 0.75, "query": VALID}]]
    assert output[0][0]["query"] is query
    if surface == "run":
        assert value[2].errors == []
    assert len(client.calls) == 2
    assert json.loads(client.calls[1]["validation_errors"]) == [
        "Service error: model request failed"
    ]
    assert PRIVATE not in json.dumps(client.calls) + caplog.text


@pytest.mark.parametrize("selector", SELECTORS)
@pytest.mark.parametrize("surface", ["apply", "invoke", "run"])
@pytest.mark.parametrize("recovered", [False, True])
def test_default_client_json_cast_preserves_safe_format_hint(
    selector: str, surface: str, recovered: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    operator = selected(selector)
    assert operator.DEFAULT_PROPERTIES["output_cast"] == "json"
    lite = importlib.import_module("litellm")
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        content = json.dumps(VALID) if recovered and len(calls) == 2 else "{" + PRIVATE
        return {"choices": [{"message": {"content": content}}], "usage": {}}

    seam = RecordingSeam()
    seam.query_result = [{"probability": 0.75}]
    properties = {
        "llm_client": LLMClient("openai"),
        "data_registry": seam,
        "llm.model": "gpt-5-mini",
        "llm.reasoning_effort": "low",
    }
    with patch.object(lite, "completion", completion):
        if recovered:
            value = getattr(operator, surface)([[]], ATTRS, properties)
            output = value[0] if surface == "run" else value
            assert output == [[{"prob": 0.75, "query": VALID}]]
            if surface == "run":
                assert value[2].errors == []
        elif surface == "run":
            _, _, meta = operator.run([[]], ATTRS, properties)
            assert_public(meta, operator.operator_id, REPLY_MESSAGE)
        else:
            with pytest.raises(ValueError, match=REPLY_MESSAGE) as captured:
                getattr(operator, surface)([[]], ATTRS, properties)
            assert is_reply_failure(captured.value)
            assert captured.value.__cause__ is None
            assert PRIVATE not in str(captured.value)
    assert len(calls) == 2
    assert "Service error: " + REPLY_MESSAGE in json.dumps(calls[1]["messages"])
    assert PRIVATE not in json.dumps(calls) + caplog.text
    if not recovered:
        assert seam.calls_to("execute_query") == []
