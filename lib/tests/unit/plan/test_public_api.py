from __future__ import annotations

import inspect

import blue_data_ops.plan as plan_surface
from blue_data_ops.operators import Operator
from blue_data_ops.plan import (
    DataContextProvider,
    DataContextSnapshot,
    DataPipeline,
    DataScope,
    EntityType,
    NodeType,
    PipelinePlanner,
    PlanGenerator,
    RefinableOperator,
    RegistryDataContextProvider,
    Status,
)


def test_plan_constants_match_the_public_wire_values() -> None:
    assert [
        str(Status.INITED),
        str(Status.REFINING),
        str(Status.REFINED),
        str(Status.EXECUTING),
        str(Status.EXECUTED),
        str(Status.PLANNED),
        str(Status.FAILED),
    ] == [
        "INITED",
        "REFINING",
        "REFINED",
        "EXECUTING",
        "EXECUTED",
        "PLANNED",
        "FAILED",
    ]
    assert [str(NodeType.INPUT), str(NodeType.OUTPUT), str(NodeType.OPERATOR)] == [
        "INPUT",
        "OUTPUT",
        "OPERATOR",
    ]
    assert [str(EntityType.OPERATOR), str(EntityType.DATA_PIPELINE)] == [
        "OPERATOR",
        "DATA_PIPELINE",
    ]


def test_plan_surface_exports_the_data_context_contracts() -> None:
    for name in (
        "DataContextProvider",
        "DataContextSnapshot",
        "DataScope",
        "RegistryDataContextProvider",
    ):
        assert name in plan_surface.__all__
        assert getattr(plan_surface, name) is not None


def test_generators_rules_and_planner_share_one_call_shape() -> None:
    assert list(inspect.signature(PlanGenerator.generate).parameters) == [
        "self",
        "request",
        "discovery",
        "data_context",
    ]
    assert list(inspect.signature(DataContextProvider.collect).parameters) == ["self", "scope"]
    assert list(inspect.signature(PipelinePlanner.__init__).parameters) == [
        "self",
        "registry",
        "generator",
        "selector",
        "data_context_provider",
    ]
    assert list(inspect.signature(DataScope).parameters) == [
        "source",
        "database",
        "collection",
        "entities",
    ]
    assert list(inspect.signature(DataContextSnapshot).parameters) == [
        "scope",
        "resolved_entities",
        "payload",
    ]
    limits = inspect.signature(RegistryDataContextProvider.__init__).parameters
    assert [name for name in limits if name not in {"self", "registry"}] == [
        "max_entities",
        "max_attributes_per_entity",
        "max_total_attributes",
        "max_description_chars",
        "max_serialized_bytes",
    ]
    assert [limits[name].default for name in list(limits)[2:]] == [32, 64, 512, 512, 131_072]


def test_plan_surface_exposes_the_v1_refiner_contract() -> None:
    assert issubclass(RefinableOperator, Operator)
    assert list(inspect.signature(DataPipeline).parameters) == [
        "id",
        "label",
        "type",
        "properties",
        "attributes",
        "path",
        "plan_provenance",
        "plan_input",
        "plan_output",
        "sync_backend",
        "auto_sync",
        "sync",
    ]
