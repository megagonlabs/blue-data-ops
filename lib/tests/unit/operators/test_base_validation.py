"""Contract tests for lax scalar and composite attribute-type validation."""

from __future__ import annotations

from typing import Any

import pytest

from blue_data_ops.operators.operator import (
    _check_type,  # pyright: ignore[reportPrivateUsage] — white-box test of the base
)

# (type_string, value, expected)
TYPE_CASES: list[tuple[str, Any, bool]] = [
    # scalars (abbreviated — the full bool matrix lives in test_aggregates)
    ("str", "x", True),
    ("str", b"x", True),
    ("str", 123, False),
    ("bool", "yes", True),
    ("bool", "maybe", False),
    ("float", "1.5", True),
    ("float", "x", False),
    ("int", 1.0, True),
    ("int", 1.5, False),
    ("int", "3", True),
    # composite spellings
    ("list[int]", [1, 2], True),
    ("list[int]", ["3"], True),  # lax: numeric strings coerce inside containers too
    ("list[int]", ["x"], False),
    ("list[int]", 123, False),
    ("list[str]", ["a", "b"], True),
    ("list[list[str]]", [["a"], ["b"]], True),  # join's schema
    ("list[list[str]]", ["a"], False),
    ("list[dict]", [{"a": 1}], True),  # insert's schema
    ("list[dict]", ["x"], False),
    ("dict[str, int]", {"a": 1}, True),
    ("dict[str, int]", {"a": "x"}, False),
    ("dict[str, int]", [], False),
    ("dict", {"a": 1}, True),
    ("tuple[str]", ("a",), True),
    ("set[int]", {1, 2}, True),
    # unions / optionals (insert/delete use Union[int, list[int]])
    ("Optional[int]", None, True),
    ("Optional[int]", 5, True),
    ("Optional[int]", "x", False),
    ("int | none", None, True),
    ("int | none", 1, True),
    ("int | none", "x", False),
    ("Union[int, list[int]]", 5, True),
    ("Union[int, list[int]]", [1, 2], True),
    ("Union[int, list[int]]", "x", False),
    # Unknown spellings fall back to Any and therefore always validate.
    ("foobar", object(), True),
    ("SomeCustomThing", 123, True),
    ("Any", None, True),
    ("", object(), True),
    # Bare frozenset/deque are unknown and fall back to Any; bracketed forms parse.
    ("frozenset", "not-a-container", True),
    ("frozenset", 123, True),
    ("deque", "not-a-container", True),
    ("deque", 123, True),
    ("frozenset[int]", frozenset({1, 2}), True),
    ("frozenset[int]", ["x"], False),
    ("deque[int]", [1, 2], True),  # lax: deque coerces from a list
    ("deque[int]", "x", False),
]


@pytest.mark.parametrize(
    "type_string,value,expected",
    TYPE_CASES,
    ids=[f"{t or 'empty'}~{i}" for i, (t, _v, _e) in enumerate(TYPE_CASES)],
)
def test_check_type_matches_contract(type_string: str, value: Any, expected: bool) -> None:
    assert _check_type(value, type_string) is expected
