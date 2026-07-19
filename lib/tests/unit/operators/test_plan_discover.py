from __future__ import annotations

import copy
from typing import Any

import pytest

from blue_data_ops.operators import OperatorRegistry, ProjectOperator, SelectOperator
from blue_data_ops.operators.plan_discover_operator import PlanDiscoverOperator
from blue_data_ops.plan import DataPipeline
from blue_data_ops.plan import pipeline as pipeline_module
from tests.unit.operators._plan_operator_helpers import (
    assert_registry_resolves,
    assert_roundtrip,
    operator_records,
)

INPUT: list[list[dict[str, Any]]] = [[]]
BASE = {"task": "starter", "data": "rows", "approximate": True}


def _registry() -> OperatorRegistry:
    registry = OperatorRegistry()
    registry.register(ProjectOperator(), "1.0.0", tags=("starter",))
    registry.register(SelectOperator(), "1.0.0", tags=("starter",))
    return registry


def test_compute_interface_and_explainer() -> None:
    op = PlanDiscoverOperator(_registry())
    assert op.apply(INPUT, dict(BASE)) == [[]]
    assert op.name == "plan_discover"
    assert op.description == (
        "Discovers plans using the operator registry to search for top-level operators "
        "as plan starters"
    )
    assert op.PROPERTIES == {"refine": True}
    assert set(op.attributes) == {
        "task",
        "data",
        "approximate",
        "hybrid",
        "limit",
        "page",
        "page_size",
        "include_metadata",
        "threshold",
        "progressive_pagination",
    }
    assert op.explain([[{"x": 1}]], INPUT, {"search_query": "q"}) == {
        "output": [[{"x": 1}]],
        "input_data": INPUT,
        "attributes": {"search_query": "q"},
        "explanation": (
            "plan discover operator searched for top-level operators with query 'q' "
            "and returned 1 results."
        ),
    }


@pytest.mark.parametrize(
    "attributes, expected",
    [
        (BASE, False),
        ({**BASE, "search_query": "q"}, True),
        ({**BASE, "task": "", "data": "", "search_query": "q"}, True),
        ({**BASE, "search_query": ""}, False),
        ({**BASE, "search_query": "q", "page": -1}, False),
        ({**BASE, "search_query": "q", "page_size": 0}, False),
        ({**BASE, "search_query": "q", "page_size": 200}, True),
        ({**BASE, "search_query": "q", "threshold": -0.1}, False),
        ({**BASE, "search_query": "q", "threshold": 1.1}, False),
        ({"data": "d", "approximate": True, "search_query": "q"}, False),
        ({"task": "t", "approximate": True, "search_query": "q"}, False),
        ({**BASE, "data": 123, "search_query": "q"}, False),
        ({**BASE, "search_query": "q", "database": "d"}, True),
        ({**BASE, "search_query": "q", "concept_type": "bogus"}, True),
    ],
)
def test_validator_matrix(attributes: dict[str, Any], expected: bool) -> None:
    assert PlanDiscoverOperator(_registry()).validate(INPUT, attributes) is expected


def test_validator_preserves_raw_range_type_error() -> None:
    with pytest.raises(TypeError):
        PlanDiscoverOperator(_registry()).validate(
            INPUT,
            {**BASE, "search_query": "q", "page": "1"},
        )


def test_refiner_emits_ordered_pinned_starter_plans() -> None:
    registry = _registry()
    attributes = dict(BASE)
    plans = PlanDiscoverOperator(registry).refiner(INPUT, attributes, {"caller": True})

    assert attributes == BASE
    assert len(plans) == 2
    assert [operator_records(plan)[0][0] for plan in plans] == [
        "project@1.0.0",
        "select@1.0.0",
    ]
    for plan in plans:
        pipeline = DataPipeline.from_dict(copy.deepcopy(plan))
        [(_, operator_attributes, node)] = operator_records(plan)
        assert operator_attributes == {}
        assert node["status"] == "INITED"
        assert pipeline.get_properties() == {}
        assert pipeline.get_plan_input() is not None
        assert pipeline.get_plan_output() is not None
        assert "/server/" not in repr(plan)
        assert_registry_resolves(plan, registry)
        assert_roundtrip(plan)


def test_empty_discovery_and_missing_inputs() -> None:
    empty_registry = OperatorRegistry()
    op = PlanDiscoverOperator(empty_registry)
    assert op.refiner(INPUT, dict(BASE)) == []
    with pytest.raises(KeyError, match="task"):
        op.refiner(INPUT, {"data": "rows"})
    with pytest.raises(KeyError, match="data"):
        op.refiner(INPUT, {"task": "starter"})


@pytest.mark.parametrize("limit, expected", [(-1, 2), (0, 0), (1, 1), (4, 2)])
def test_limit_slices_after_constructing_every_candidate(
    monkeypatch: pytest.MonkeyPatch,
    limit: int,
    expected: int,
) -> None:
    issued: list[str] = []

    def next_id() -> str:
        value = f"p{len(issued) + 1}"
        issued.append(value)
        return value

    monkeypatch.setattr(pipeline_module, "_new_id", next_id)
    plans = PlanDiscoverOperator(_registry()).refiner(INPUT, {**BASE, "limit": limit})
    assert len(plans) == expected
    assert len(issued) == 10
