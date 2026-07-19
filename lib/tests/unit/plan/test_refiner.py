from __future__ import annotations

import pytest

from blue_data_ops.operators.types import Properties
from blue_data_ops.plan import (
    DataPipeline,
    DeclarativeOperator,
    NodeType,
    Status,
    declarative_operator_refiner,
    default_operator_refiner,
)


def test_default_refiner_always_returns_no_alternatives() -> None:
    assert default_operator_refiner([], {}, None) == []
    assert default_operator_refiner([[]], {"ignored": True}, {"ignored": True}) == []


def test_declarative_empty_and_isolated_operator_complete_missing_endpoints() -> None:
    empty = declarative_operator_refiner([], {}, {"plans": [{"nodes": {}}]})[0]
    empty_pipeline = DataPipeline.from_dict(empty)
    assert len(empty_pipeline.filter_nodes([str(NodeType.INPUT)])) == 1
    assert len(empty_pipeline.filter_nodes([str(NodeType.OUTPUT)])) == 1
    assert empty_pipeline.to_jsonform_diagram_json()["edges"] == []

    isolated = declarative_operator_refiner(
        [[]],
        {},
        {
            "plans": [
                {
                    "nodes": {
                        "op": {"type": "OPERATOR", "name": "select@1.0.0"},
                    }
                }
            ]
        },
    )[0]
    pipeline = DataPipeline.from_dict(isolated)
    operator = next(iter(pipeline.filter_nodes([str(NodeType.OPERATOR)]).values()))
    assert len(pipeline.get_prev_nodes(operator)) == 1
    assert len(pipeline.get_next_nodes(operator)) == 1
    assert pipeline.get_plan_input() is not None
    assert pipeline.get_plan_output() is not None


def test_declarative_prev_preserves_unbound_and_stale_wrong_edge_paths() -> None:
    unbound = {
        "plans": [
            {
                "nodes": {
                    "op-a": {"type": "OPERATOR", "name": "select@1.0.0"},
                    "op-b": {
                        "type": "OPERATOR",
                        "name": "project@1.0.0",
                        "prev": ["op-a"],
                    },
                }
            }
        ]
    }
    with pytest.raises(UnboundLocalError, match="from_id"):
        declarative_operator_refiner([[]], {}, unbound)

    stale = {
        "plans": [
            {
                "nodes": {
                    "op-a": {
                        "type": "OPERATOR",
                        "name": "select@1.0.0",
                        "next": ["op-b"],
                    },
                    "op-b": {"type": "OPERATOR", "name": "project@1.0.0"},
                    "op-c": {
                        "type": "OPERATOR",
                        "name": "join@1.0.0",
                        "prev": ["op-b"],
                    },
                }
            }
        ]
    }
    pipeline = DataPipeline.from_dict(declarative_operator_refiner([[]], {}, stale)[0])
    operator_ids = list(pipeline.filter_nodes([str(NodeType.OPERATOR)]))
    op_a, op_b, op_c = operator_ids
    assert pipeline.get_node(op_c).get_data("prev") == [op_a]  # type: ignore[union-attr]
    assert op_c not in pipeline.get_node(op_b).get_data("next")  # type: ignore[union-attr]


def test_declarative_endpoint_selection_values_unknown_types_and_alternative_order() -> None:
    properties: Properties = {
        "plans": [
            {
                "nodes": {
                    "valued": {"type": "INPUT", "value": 4},
                    "first-open": {"type": "INPUT"},
                    "last-open": {"type": "INPUT"},
                    "first-output": {"type": "OUTPUT"},
                    "last-output": {"type": "OUTPUT", "value": 8},
                    "ignored": {"type": "UNKNOWN"},
                }
            },
            {"nodes": {}},
        ]
    }

    records = declarative_operator_refiner([[{"x": 1}]], {}, properties)
    pipelines = [DataPipeline.from_dict(record) for record in records]

    assert len(pipelines) == 2
    first = pipelines[0]
    assert first.get_node("valued").get_data("status") == str(Status.EXECUTED)  # type: ignore[union-attr]
    assert first.get_plan_input().get_label() == "last-open"  # type: ignore[union-attr]
    assert first.get_plan_output().get_label() == "last-output"  # type: ignore[union-attr]
    assert first.get_node("ignored") is None


def test_declarative_operator_interface_and_raw_failure_propagation() -> None:
    with pytest.raises(TypeError, match="NoneType"):
        DeclarativeOperator()

    properties: Properties = {
        "name": "custom",
        "description": "custom description",
        "plans": [],
    }
    operator = DeclarativeOperator(properties)
    assert operator.name == "custom"
    assert operator.description == "custom description"
    assert operator.properties["refine"] is True
    assert operator.apply([], {}) == [[]]
    assert operator.explain([], [], {})["explanation"] == (
        "Declarative operator passed input data to plans specified"
    )

    failing_properties: Properties = {
        "plans": [
            {
                "nodes": {
                    "op-a": {"type": "OPERATOR", "name": "select@1.0.0"},
                    "op-b": {
                        "type": "OPERATOR",
                        "name": "project@1.0.0",
                        "prev": ["op-a"],
                    },
                }
            }
        ]
    }
    with pytest.raises(UnboundLocalError, match="from_id"):
        operator.refiner([[]], {}, failing_properties)
