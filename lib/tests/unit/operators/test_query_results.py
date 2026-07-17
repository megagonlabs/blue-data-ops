"""The shared registry-result formatter: upstream duplicates this helper in each
query-executing operator; the port shares one copy with behavior preserved exactly,
including the case-4 None fallthrough."""

from __future__ import annotations

from typing import Any

import pytest

from blue_data_ops.operators._query_results import format_execution_result

_FORMAT_CASES: list[tuple[Any, Any]] = [
    (None, [[]]),
    ([], [[]]),
    (0, [[]]),  # falsy non-list rides the `not result` arm of case 1
    ({"a": 1}, [[{"a": 1}]]),
    ([{"a": 1}, {"b": 2}], [[{"a": 1}, {"b": 2}]]),
    ([[{"a": 1}], [{"b": 2}]], [[{"a": 1}], [{"b": 2}]]),
    ([[], [{"a": 1}]], [[], [{"a": 1}]]),  # empty inner lists are allowed
]


@pytest.mark.parametrize(
    "result,expected",
    _FORMAT_CASES,
    ids=["none", "empty", "falsy", "dict", "list-of-dicts", "list-of-lists", "with-empty-inner"],
)
def test_format_cases(result: Any, expected: Any) -> None:
    assert format_execution_result(result) == expected


def test_inner_non_dict_falls_through_to_none() -> None:
    # The pinned upstream quirk: a list of lists holding a non-dict item breaks out
    # of the case chain WITHOUT reaching the raise — the result is None.
    assert format_execution_result([["not-a-dict"]]) is None


@pytest.mark.parametrize(
    "result",
    ["rows", 5, [{"a": 1}, ["mixed"]], [1, 2]],
    ids=["str", "int", "mixed-list", "list-of-scalars"],
)
def test_unformattable_raises(result: Any) -> None:
    with pytest.raises(ValueError, match="Invalid result format from data registry execution"):
        format_execution_result(result)
