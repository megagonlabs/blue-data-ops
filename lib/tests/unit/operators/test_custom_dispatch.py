from __future__ import annotations

from typing import Any, cast

import pytest

from blue_data_ops.operators import versioned_registry
from blue_data_ops.operators.types import FunctionResult, ValidationResult

IDENTITIES = [
    f"{name}@{version}.0.0"
    for name, versions in [
        ("nl2sql", (1, 2, 3)),
        ("nl2bn", (1, 2, 3)),
        ("insert_table", (1, 2, 3)),
        ("create_table", (1, 2)),
        ("create_database", (1, 2)),
    ]
    for version in versions
]
DATA = [[{"hook": True}]]


def valid(*args: Any, **kwargs: Any) -> ValidationResult:
    return ValidationResult(True, None)


@pytest.mark.parametrize("identity", IDENTITIES)
@pytest.mark.parametrize("kind", ["subclass", "instance_callable", "parent_patch"])
def test_custom_execute_receives_original_arguments(
    identity: str, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = type(versioned_registry().resolve(identity))
    calls: list[Any] = []
    attributes: dict[str, Any] = {}
    properties = {"custom": object()}

    def execute(self: Any, *args: Any) -> FunctionResult:
        calls.append(args)
        return FunctionResult(DATA, {})

    class Callable:
        @property
        def __func__(self) -> Any:
            pytest.fail("custom callable introspected")

        def __call__(self, *args: Any) -> FunctionResult:
            calls.append(args)
            return FunctionResult(DATA, {})

    child = type("Custom", (parent,), {"attributes": {}, "_validate_input": valid})
    if kind == "subclass":
        cast(Any, child)._execute = execute
    elif kind == "parent_patch":
        owner = next(cls for cls in parent.__mro__ if "_execute" in cls.__dict__)
        monkeypatch.setattr(owner, "_execute", execute)
    operator = child()
    if kind == "instance_callable":
        cast(Any, operator)._execute = Callable()
    assert operator.apply(DATA, attributes, properties) is DATA
    assert len(calls) == 1
    assert calls[0][0] is DATA
    assert calls[0][1] is attributes
    assert calls[0][2] is properties
    result = operator.run(DATA, attributes, properties)
    assert not result[2].errors
    assert result[0] is DATA
    assert len(calls) == 2
    assert len(calls[1]) == 3


@pytest.mark.parametrize("identity", IDENTITIES)
def test_inherited_execute_preserves_custom_helper_and_properties(identity: str) -> None:
    parent = type(versioned_registry().resolve(identity))
    name = identity.split("@")[0]
    helper = {
        "nl2sql": "_execute_sql",
        "nl2bn": "_execute_bn",
        "insert_table": "_execute_insert",
        "create_table": "_execute_create",
        "create_database": "_execute_create",
    }[name]
    calls: list[Any] = []
    prompt = {"input_template": "custom prompt"}

    def body(self: Any, *args: Any, **kwargs: Any) -> FunctionResult:
        calls.append((self.DEFAULT_PROPERTIES, args, kwargs))
        return FunctionResult(DATA, {})

    child = type(
        "CustomHelper",
        (parent,),
        {helper: body, "DEFAULT_PROPERTIES": prompt, "attributes": {}, "_validate_input": valid},
    )
    operator = child()
    assert operator.apply(DATA, {}, None) is DATA
    assert calls[0][0] is prompt
    assert calls[0][2] == {}
    result = operator.run(DATA, {}, None)
    assert not result[2].errors
    assert calls[1][0] is prompt
    expected = (
        {"_diagnose_generation_target": True}
        if identity == "nl2sql@3.0.0"
        else {"_diagnose_registry": True}
    )
    assert calls[1][2] == expected
