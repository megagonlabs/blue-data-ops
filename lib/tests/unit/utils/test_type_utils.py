"""Blue-compatible type parsing, model construction, and validation.

Malformed ``union[]`` returns ``False`` rather than raising ``IndexError``, system
faults are wrapped as ``RuntimeError``, and typing-object identity is preserved.
"""
# ruff: noqa: UP006, UP007, UP045 - typing.* literals are the Blue return-identity fixture.

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union  # noqa: UP035

import pytest
from pydantic import ValidationError

from blue_data_ops.operators import operator as operator_module
from blue_data_ops.utils import type_utils
from blue_data_ops.utils.type_utils import (
    create_pydantic_model,
    string_to_python_type,
    validate_parameter_type,
)

# --- string_to_python_type: exact Blue return-object identity ----------------------
STRING_TO_TYPE_CASES: list[tuple[str, Any]] = [
    ("", Any),
    ("str", str),
    ("int", int),
    ("float", float),
    ("bool", bool),
    ("dict", dict),
    ("list", list),
    ("none", type(None)),
    ("any", Any),
    ("unknown_type", Any),
    # List/Dict/Optional/Union keep Blue's typing.* objects.
    ("List[str]", List[str]),  # noqa: UP006
    ("list[int]", List[int]),  # noqa: UP006
    ("Dict[str, int]", Dict[str, int]),  # noqa: UP006
    ("dict[str, Any]", Dict[str, Any]),  # noqa: UP006
    ("dict[str]", Dict[str, Any]),  # noqa: UP006
    ("Optional[int]", Optional[int]),  # noqa: UP007
    ("optional[str]", Optional[str]),  # noqa: UP007
    ("Union[int, str]", Union[int, str]),  # noqa: UP007
    ("Union[int, None]", Optional[int]),  # noqa: UP007
    ("int | str", Union[int, str]),  # noqa: UP007
    ("str | none", Optional[str]),  # noqa: UP007
    ("list[dict[str, int]]", List[Dict[str, int]]),  # noqa: UP006
    # tuple/set/frozenset/deque keep builtin generics (Blue does too).
    ("Tuple[int]", tuple[int]),
    ("Set[str]", set[str]),
    ("FrozenSet[int]", frozenset[int]),
]


@pytest.mark.parametrize(("type_str", "expected"), STRING_TO_TYPE_CASES)
def test_string_to_python_type_matches_blue(type_str: str, expected: Any) -> None:
    assert string_to_python_type(type_str) == expected


def test_typing_object_matches_standard_typing_factory() -> None:
    # A mutation to builtin generics (list[str]) instead of typing.List[str] would
    # break Blue callers that compare the returned object; pin the typing.* spelling.
    assert string_to_python_type("List[str]") == List[str]  # noqa: UP006
    assert repr(string_to_python_type("List[str]")).startswith("typing.List")
    # Optional's representation follows the standard factory on each interpreter.
    observed = string_to_python_type("Optional[int]")
    expected = Optional[int]
    assert observed is expected
    assert type(observed) is type(expected)
    assert repr(observed) == repr(expected)


# --- validate_parameter_type: lax coercion, malformed, and system faults -----------
VALIDATE_CASES: list[tuple[Any, Any, bool]] = [
    (7, "int", True),
    ("7", "int", True),
    (7.5, "int", False),
    ("x", "int", False),
    (True, "int", True),
    ("7.5", "float", True),
    (b"b", "str", True),
    ("true", "bool", True),
    (("a", "b"), "list[str]", True),
    ([1, "x"], "list[int]", False),
    ({"a": "1"}, "dict[str, int]", True),
    ({"a": "x"}, "dict[str, int]", False),
    (None, "none", True),
    (None, "Optional[int]", True),
    (5, "Optional[int]", True),
    ("s", "Union[int, str]", True),
    ("anything", "unknown_type", True),
    (1, "", True),  # empty type accepts anything
    (1, None, True),  # None type accepts anything
]


@pytest.mark.parametrize(("value", "expected_type", "expected"), VALIDATE_CASES)
def test_validate_parameter_type_matches_blue(
    value: Any, expected_type: Any, expected: bool
) -> None:
    assert validate_parameter_type(value, expected_type) is expected


def test_malformed_union_returns_false_not_indexerror() -> None:
    # Blue returns False for a malformed union spec instead of raising.
    assert validate_parameter_type("x", "union[]") is False


@pytest.mark.parametrize("bad", ["list[", "dict[str", "optional[", "union[]"])
def test_malformed_type_specs_never_raise(bad: str) -> None:
    # Malformed specs degrade to a bool, never propagate a parse exception. Some
    # (list[, dict[str, union[]) fail validation -> False; others (optional[)
    # collapse to Any -> True. The contract is "returns a bool", not a fixed value.
    assert isinstance(validate_parameter_type("x", bad), bool)


def test_system_fault_wraps_as_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # A system fault is logged and re-raised as RuntimeError rather than propagated raw.
    class _MarkerError(ArithmeticError):
        pass

    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise _MarkerError("c2a-system-fault")

    monkeypatch.setattr(type_utils, "create_model", _raise)
    with pytest.raises(RuntimeError, match="Parameter type validation system error"):
        validate_parameter_type(1, "int")


# --- create_pydantic_model ---------------------------------------------------------
def test_create_pydantic_model_required_optional_and_coercion() -> None:
    model = create_pydantic_model(
        {
            "a": {"type": "int", "required": True},
            "b": {"type": "str"},
            "c": {"type": "list[int]", "required": False},
        }
    )
    assert model.__name__ == "ParameterModel"
    assert model(a=1).model_dump() == {"a": 1, "b": None, "c": None}
    assert model(a="3").model_dump()["a"] == 3  # lax coercion
    with pytest.raises(ValidationError):
        model(b="x")  # missing required 'a'
    with pytest.raises(ValidationError):
        model(a=1, c=["x"])  # bad list member


# --- shared implementation ----------------------------------------------------------
def test_operator_delegates_to_utils_implementation() -> None:
    assert (
        operator_module.validate_parameter_type  # pyright: ignore[reportPrivateImportUsage]
        is validate_parameter_type
    )
    assert operator_module._string_to_python_type is string_to_python_type  # pyright: ignore[reportPrivateUsage]
    assert operator_module._check_type is validate_parameter_type  # pyright: ignore[reportPrivateUsage]
