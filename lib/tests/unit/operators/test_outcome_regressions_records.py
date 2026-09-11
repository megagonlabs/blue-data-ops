from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from blue_data_ops import ErrorCode, ErrorStage
from blue_data_ops.operators.registry import versioned_registry


def _assert_successful_empty(result: tuple[Any, Any, Any]) -> None:
    output_data, output_attributes, meta = result
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is True
    assert meta.errors == []


def _assert_invalid(result: tuple[Any, Any, Any]) -> None:
    output_data, output_attributes, meta = result
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    assert meta.errors[0].code is ErrorCode.INVALID_INPUT
    assert meta.errors[0].stage is ErrorStage.VALIDATE


def test_insert_populates_an_empty_base_that_the_prior_version_left_empty() -> None:
    input_data: list[list[dict[str, Any]]] = [[]]
    attributes = {"insert_idx": 0, "insert_records": [{"id": 17}]}
    old_operator = versioned_registry().resolve("insert@2.0.0")
    new_operator = versioned_registry().resolve("insert@3.0.0")

    _assert_successful_empty(old_operator.run(deepcopy(input_data), attributes))
    output_data, output_attributes, meta = new_operator.run(deepcopy(input_data), attributes)
    assert output_data == [[{"id": 17}]]
    assert output_attributes == {}
    assert meta.errors == []
    assert meta.is_empty is False


def test_intersect_treats_an_empty_middle_group_as_an_operand() -> None:
    operator = versioned_registry().resolve("intersect@3.0.0")
    _assert_successful_empty(
        operator.run(
            [[{"id": 1}], [], [{"id": 1}]],
            {},
        )
    )


@pytest.mark.parametrize(
    ("operator_id", "input_key", "output_key"),
    [
        ("min@3.0.0", "amount", "low"),
        ("max@3.0.0", "amount", "high"),
    ],
)
def test_extrema_distinguish_no_numeric_value_from_real_zero(
    operator_id: str, input_key: str, output_key: str
) -> None:
    operator = versioned_registry().resolve(operator_id)
    attributes = {
        f"{operator_id.split('@', 1)[0]}_key": input_key,
        "output_key": output_key,
    }

    _assert_successful_empty(operator.run([[{"id": "missing"}, {input_key: None}]], attributes))
    output_data, output_attributes, meta = operator.run(
        [[{input_key: 3}, {input_key: 0}]], attributes
    )
    assert output_data == [[{output_key: 0 if operator_id.startswith("min") else 3}]]
    assert output_attributes == {}
    assert meta.errors == []
    assert meta.is_empty is False


def test_project_rejects_an_empty_key_request_before_empty_data() -> None:
    operator = versioned_registry().resolve("project@3.0.0")
    _assert_invalid(operator.run([[]], {"kept_keys": []}))
