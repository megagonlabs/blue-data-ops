from __future__ import annotations

import importlib
import json
from typing import Any, cast

import pytest

from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import Operator, active_registry, versioned_registry
from blue_data_ops.operators.types import Attributes, DataBundle, Properties

MARKER = "SYNTHETIC_PRIVATE_REPLY_TARGET_SQL"
REPLY_MESSAGE = "model reply did not match the operator's output format"


class Reply(LLMClient):
    def __init__(self, value: Any) -> None:
        self.value = value
        self.calls = 0

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls += 1
        return self.value


class RaisingOperator(Operator):
    name = "diagnostic_probe"
    description = "Local deterministic diagnostic fixture."
    attributes = {}

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        raise self.error


def record(result: Any) -> dict[str, Any]:
    assert result[0] == [[]]
    assert result[1] == {}
    error = result[2].errors[0]._asdict()
    assert MARKER not in json.dumps(error)
    return error


@pytest.mark.parametrize("reply", [None, "maybe", {}, 1])
def test_filter_owned_reply(reply: Any) -> None:
    op = active_registry().resolve("semantic_filter@3.0.0")
    client = Reply(reply)
    error = record(
        op.run(
            [[{"value": MARKER}]], {"filter_conditions": {"value": "keep"}}, {"llm_client": client}
        )
    )
    assert error["message"] == REPLY_MESSAGE
    assert error["stage"] == "EXECUTE"
    assert error["code"] == "EXECUTION_FAILED"
    assert error["retryable"] is False
    assert error["suggestion"]
    assert client.calls == 1


@pytest.mark.parametrize(
    "reply,kept", [(True, True), (False, False), ("true", True), ("false", False), (" TRUE ", True)]
)
def test_filter_valid_controls(reply: Any, kept: bool) -> None:
    result = (
        active_registry()
        .resolve("semantic_filter@3.0.0")
        .run(
            [[{"value": "ordinary"}]],
            {"filter_conditions": {"value": "keep"}},
            {"llm_client": Reply(reply)},
        )
    )
    assert not result[2].errors
    assert result[2].is_empty is (not kept)


@pytest.mark.parametrize("reply", [{"a": 1}, None, 1, [1], "prose"])
def test_nl2llm_shape_stays_normalize(reply: Any) -> None:
    error = record(
        active_registry()
        .resolve("nl2llm@3.0.0")
        .run([[]], {"query": "rows"}, {"llm_client": Reply(reply)})
    )
    assert error["code"] == "EXECUTION_RESULT_INVALID"
    assert error["stage"] == "NORMALIZE"
    assert error["message"] == "model reply is not an array of records"
    assert error["suggestion"] == "Request a JSON array of objects in the model reply."


@pytest.mark.parametrize("reply", [[], [{"a": 1}]])
def test_nl2llm_record_controls(reply: Any) -> None:
    result = (
        active_registry()
        .resolve("nl2llm@3.0.0")
        .run([[]], {"query": "rows"}, {"llm_client": Reply(reply)})
    )
    assert not result[2].errors
    assert result[2].is_empty is (not reply)


@pytest.mark.parametrize(
    "identity,attrs,reply",
    [
        ("semantic_extract@3.0.0", {"entities": [{"name": "thing", "description": "thing"}]}, {}),
        (
            "semantic_extract@3.0.0",
            {
                "entities": [{"name": "thing", "description": "thing"}],
                "extract_with_single_prompt": False,
            },
            [1],
        ),
        ("semantic_project@3.0.0", {"projection_instructions": "rename"}, {"absent": "value"}),
        ("semantic_project@3.0.0", {"projection_instructions": "rename"}, None),
        (
            "semantic_transform@3.0.0",
            {"output_desc": {"target": {"type": "str", "required": True, "description": "target"}}},
            {},
        ),
    ],
)
def test_existing_strict_semantic_rejections(
    identity: str,
    attrs: Attributes,
    reply: Any,
) -> None:
    error = record(
        active_registry()
        .resolve(identity)
        .run([[{"value": MARKER}]], attrs, {"llm_client": Reply(reply)})
    )
    assert error["message"] == REPLY_MESSAGE
    assert error["stage"] == "EXECUTE"


@pytest.mark.parametrize("reply", ["maybe", 1, {}, []])
def test_legacy_filter_coercion_control(reply: Any) -> None:
    result = (
        versioned_registry()
        .resolve("semantic_filter@2.0.0")
        .run(
            [[{"value": "ordinary"}]],
            {"filter_conditions": {"value": "keep"}},
            {"llm_client": Reply(reply)},
        )
    )
    assert record(result)["message"] == REPLY_MESSAGE


@pytest.mark.parametrize(
    "error",
    [
        ValueError(MARKER),
        RuntimeError(MARKER),
        FileNotFoundError(MARKER),
        json.JSONDecodeError(MARKER, MARKER, 0),
    ],
)
def test_unowned_exceptions_generic(error: Exception) -> None:
    value = record(RaisingOperator(error).run([[]], {}))
    assert value["message"] == "operator execution failed"
    assert value["retryable"] is False


def execution_error_type() -> Any:
    # Resolve at test execution so an absent new export gives an intended assertion red.
    root = importlib.import_module("blue_data_ops")
    operators = importlib.import_module("blue_data_ops.operators")
    types = importlib.import_module("blue_data_ops.operators.types")
    cls = vars(types).get("OperatorExecutionError")
    assert isinstance(cls, type), "new intentional custom diagnostic export is absent"
    assert vars(root).get("OperatorExecutionError") is cls
    assert vars(operators).get("OperatorExecutionError") is cls
    return cls


def test_public_custom_error_and_hostile_subclass() -> None:
    cls = execution_error_type()

    class Hostile(cls):
        def __getattribute__(self, name: str) -> Any:
            if name not in {"__class__", "__traceback__", "__cause__", "__context__"}:
                raise AssertionError("dynamic accessor used")
            return object.__getattribute__(self, name)

        @property
        def _OperatorExecutionError__carrier(self) -> Any:
            raise AssertionError("shadow property used")

    for error in (
        cls("fixed public message", suggestion="fixed public action", retryable=True),
        Hostile("fixed public message", suggestion="fixed public action", retryable=True),
    ):
        value = record(RaisingOperator(error).run([[]], {}))
        assert value["message"] == "fixed public message"
        assert value["suggestion"] == "fixed public action"
        assert value["retryable"] is True
        assert value["code"] == "EXECUTION_FAILED" and value["stage"] == "EXECUTE"


@pytest.mark.parametrize(
    "field,value",
    [
        ("message", ""),
        ("message", " "),
        ("message", "a" * 513),
        ("message", "line\nbreak"),
        ("message", "tab\tvalue"),
        ("message", 1),
        ("suggestion", ""),
        ("suggestion", "a" * 513),
        ("retryable", 1),
        ("retryable", "true"),
    ],
)
def test_custom_constructor_rejects_malformed(field: str, value: Any) -> None:
    cls = execution_error_type()
    kwargs = {"message": "fixed public message", field: value}
    with pytest.raises((ValueError, TypeError)) as captured:
        cls(**kwargs)
    assert MARKER not in str(captured.value)


def test_custom_uninitialized_and_foreign_generic() -> None:
    cls = execution_error_type()

    class Uninitialized(cls):
        def __init__(self) -> None:
            Exception.__init__(self, MARKER)

    foreign = type("OperatorExecutionError", (Exception,), {"__module__": cls.__module__})
    for error in (Uninitialized(), foreign(MARKER)):
        assert (
            record(RaisingOperator(error).run([[]], {}))["message"] == "operator execution failed"
        )


def test_custom_default_and_primitive_subclasses() -> None:
    cls = execution_error_type()
    default = record(RaisingOperator(cls("fixed public message")).run([[]], {}))
    assert default["suggestion"] is None and default["retryable"] is False

    class Text(str):
        pass

    for kwargs in ({"message": Text("fixed")}, {"message": "fixed", "suggestion": Text("action")}):
        with pytest.raises((ValueError, TypeError)):
            cls(**kwargs)


@pytest.mark.parametrize(
    "carrier",
    [
        None,
        (),
        ("", None, False),
        ("fixed", None, 1),
        ("fixed\nprivate", None, False),
        ["fixed", None, False],
    ],
)
def test_mutated_base_carrier_falls_back(carrier: Any) -> None:
    from types import MemberDescriptorType

    cls = execution_error_type()
    error = cls("fixed public message")
    slots = [
        value
        for value in cast(dict[str, Any], vars(cls)).values()
        if isinstance(value, MemberDescriptorType)
    ]
    assert len(slots) == 1
    slots[0].__set__(error, carrier)
    assert record(RaisingOperator(error).run([[]], {}))["message"] == "operator execution failed"
