"""Focused planner admission checks for the 3.0 catalog."""

from __future__ import annotations

from typing import ClassVar

import pytest

from blue_data_ops.operators import (
    Attributes,
    DataBundle,
    Operator,
    OperatorRegistry,
    Properties,
    active_registry,
)
from blue_data_ops.plan import (
    DiscoveryQuery,
    PipelinePlanner,
    PlanningError,
    PlanningRequest,
    RulePlanGenerator,
)


class CallerV2Operator(Operator):
    name: ClassVar[str] = "caller_v2"

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        return input_data


def _average_request(allowed: tuple[str, ...] = ()) -> PlanningRequest:
    return PlanningRequest(
        goal="Average values greater than zero",
        discovery_queries=(
            DiscoveryQuery("filter", ("capability-filter",)),
            DiscoveryQuery("average", ("capability-average",)),
        ),
        operator_attributes={
            "select": {"operand_key": "value", "operand": ">", "operand_val": 0},
            "avg": {"avg_key": "value", "output_key": "mean"},
        },
        allowed_operator_ids=allowed,
    )


def test_package_default_admits_the_active_v3_average() -> None:
    planner = PipelinePlanner(active_registry(), RulePlanGenerator())
    result = planner.plan(_average_request())

    assert "select@2.0.0" in result.discovery.operator_ids
    assert "avg@3.0.0" in result.discovery.operator_ids
    assert tuple(step.operator_id for step in result.selected.steps) == (
        "select@2.0.0",
        "avg@3.0.0",
    )
    assert result.preflight.operator_ids == ("select@2.0.0", "avg@3.0.0")


def test_caller_registered_v2_remains_admissible() -> None:
    registry = OperatorRegistry()
    registry.register(CallerV2Operator(), "2.0.0", tags=("capability-custom",))
    request = PlanningRequest(
        goal="Run the caller operator",
        discovery_queries=(DiscoveryQuery("caller_v2"),),
        allowed_operator_ids=("caller_v2@2.0.0",),
    )

    discovery = PipelinePlanner(registry, RulePlanGenerator()).discover(request)
    assert discovery.operator_ids == ("caller_v2@2.0.0",)


def test_caller_registered_v3_is_rejected_before_generation() -> None:
    registry = OperatorRegistry()
    registry.register(CallerV2Operator(), "3.0.0")
    planner = PipelinePlanner(registry, RulePlanGenerator())
    request = PlanningRequest(
        goal="Run the caller operator",
        discovery_queries=(DiscoveryQuery("caller_v2"),),
        allowed_operator_ids=("caller_v2@3.0.0",),
    )

    with pytest.raises(PlanningError, match="supported pinned"):
        planner.plan(request)
