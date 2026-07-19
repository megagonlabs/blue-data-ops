from __future__ import annotations

import inspect

from blue_data_ops.operators import Operator
from blue_data_ops.plan import (
    DataPipeline,
    EntityType,
    NodeType,
    RefinableOperator,
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
