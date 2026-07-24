"""Blue-compatible JSON merge and JSONPath behavior.

``merge_json`` delegates to jsonmerge==1.9.2; the scalar-base/object-head edge
raises rather than replacing the scalar. ``json_query`` and ``json_query_set``
exercise Blue's JSONPath behavior. Operator metadata uses the same merge function.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from blue_data_ops.operators import _metadata as metadata_module
from blue_data_ops.utils.json_utils import json_query, json_query_set, merge_json

MERGE_CASES: list[tuple[Any, Any, Any]] = [
    ({"a": {"x": 1}}, {"a": {"y": 2}, "b": 3}, {"a": {"x": 1, "y": 2}, "b": 3}),
    ({"a": 1}, {"a": 2}, {"a": 2}),
    ({"a": [1, 2]}, {"a": [3]}, {"a": [3]}),  # arrays replace
    ({}, {"k": {"n": {"deep": True}}}, {"k": {"n": {"deep": True}}}),
    ({"k": {"n": 1}}, {"k": "scalar"}, {"k": "scalar"}),  # object base, scalar head -> replace
    (None, {"a": 1}, {"a": 1}),
    ({"a": 1}, None, None),  # jsonmerge: a None head merges to None
]


@pytest.mark.parametrize(("base", "head", "expected"), MERGE_CASES)
def test_merge_json_matches_jsonmerge(base: Any, head: Any, expected: Any) -> None:
    assert merge_json(base, head) == expected


def test_merge_json_raises_on_scalar_base_object_head() -> None:
    # jsonmerge raises when an object head is applied to a scalar base.
    import jsonmerge.exceptions  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]

    base_instance_error = cast(
        type[Exception],
        jsonmerge.exceptions.BaseInstanceError,  # pyright: ignore[reportUnknownMemberType]
    )
    with pytest.raises(base_instance_error):
        merge_json({"k": "scalar"}, {"k": {"n": 1}})


def test_merge_json_does_not_mutate_base() -> None:
    base = {"a": {"x": 1}}
    merge_json(base, {"a": {"y": 2}})
    assert base == {"a": {"x": 1}}


# --- json_query --------------------------------------------------------------------
def test_json_query_single_and_list_and_default() -> None:
    obj = {"a": {"b": [1, 2, 3]}}
    assert json_query(obj, "$.a.b[0]") == 1
    assert json_query(obj, "$.a.b[*]", single=False) == [1, 2, 3]
    assert json_query(obj, "$.missing") is None
    assert json_query(obj, "$.missing", default="fallback") == "fallback"


# --- json_query_set ----------------------------------------------------------------
def test_json_query_set_root_and_nested() -> None:
    obj: dict[str, Any] = {"user": {"name": "x"}}
    json_query_set(obj, "age", 30, context="$.user")
    assert obj["user"]["age"] == 30
    json_query_set(obj, "top", True)
    assert obj["top"] is True


def test_json_query_set_non_dict_context_raises() -> None:
    obj = {"items": [1, 2]}
    with pytest.raises(Exception, match="context must be a dict"):
        json_query_set(obj, "k", 1, context="$.items[0]")


# --- shared implementation ----------------------------------------------------------
def test_metadata_merge_shares_the_json_merge_implementation() -> None:
    assert metadata_module.merge_metadata is merge_json
