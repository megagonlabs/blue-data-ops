from __future__ import annotations

import inspect
import warnings
from typing import Any, ClassVar

import pytest

from blue_data_ops import BlueDataOpsDeprecationWarning
from blue_data_ops.operators import (
    AttributeSpec,
    Operator,
    OperatorRegistry,
    versioned_registry,
)


class CallerOperator(Operator):
    name: ClassVar[str] = "caller_retired_name"
    description: ClassVar[str] = "Caller-owned lifecycle probe."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del attributes, properties
        return input_data


def test_public_category_is_retained_for_historical_warning_filters() -> None:
    assert issubclass(BlueDataOpsDeprecationWarning, DeprecationWarning)


def test_operator_constructor_and_metadata_have_no_refinement_seam() -> None:
    assert "refiner" not in inspect.signature(Operator).parameters
    operator = CallerOperator()
    assert not hasattr(operator, "refiner")
    assert "refine" not in operator.properties
    with pytest.raises(TypeError):
        CallerOperator(refiner=lambda *_args: [])  # type: ignore[call-arg]


def test_direct_execution_of_a_caller_deprecated_card_is_not_blanket_banned() -> None:
    registry = OperatorRegistry()
    registry.register(CallerOperator(), "2.0.0", deprecated=True)
    card = registry.get_card("caller_retired_name@2.0.0")
    assert card is not None and card.deprecated is True

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        output, attributes, meta = registry.resolve(card.operator_id).run([[{"x": 1}]], {})

    assert output == [[{"x": 1}]]
    assert attributes == {}
    assert meta.errors == []
    assert not any(item.category is BlueDataOpsDeprecationWarning for item in caught)


def test_versioned_registry_emits_no_deprecation_warning() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        history = versioned_registry()

    assert len(history.list_cards()) == 88
    assert not any(item.category is BlueDataOpsDeprecationWarning for item in caught)
