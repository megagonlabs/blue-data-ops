"""Executable migrations for callers that do not need automatic refinement."""

from __future__ import annotations

import importlib
from typing import Any, ClassVar

import pytest

from blue_data_ops import ErrorCode, ErrorStage
from blue_data_ops.operators import Attributes, DataBundle, Operator, Properties, versioned_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor, Status
from blue_data_ops.plan.executor import PipelineError

INPUT: DataBundle = [
    [
        {"order_id": 1, "total": 80.0},
        {"order_id": 2, "total": 125.0},
        {"order_id": 3, "total": 210.0},
    ]
]

REMOVED_MODULES = (
    "blue_data_ops.operators._multipart_plan",
    "blue_data_ops.plan.refiner",
)


class CallerLeaf(Operator):
    name: ClassVar[str] = "caller_leaf"
    description: ClassVar[str] = "Copy rows and mark them as observed."
    attributes: ClassVar[dict[str, Any]] = {}

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        del attributes, properties
        return [[dict(row, observed=True) for row in group] for group in input_data]


@pytest.mark.parametrize("module", REMOVED_MODULES)
def test_removed_support_modules_do_not_import(module: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_historical_status_and_error_constants_remain_parseable() -> None:
    assert Status("REFINING") == Status.REFINING
    assert Status("REFINED") == Status.REFINED
    assert ErrorCode("REFINEMENT_FAILED") is ErrorCode.REFINEMENT_FAILED
    assert ErrorStage("REFINE") is ErrorStage.REFINE


def test_stored_retired_id_parses_before_exact_resolution_fails() -> None:
    pipeline = DataPipeline(id="stored")
    source = pipeline.define_input("input")
    retired = pipeline.define_operator("plan_discover@2.0.0")
    output = pipeline.define_output("output")
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(output)
    pipeline.connect_nodes(source, retired)
    pipeline.connect_nodes(retired, output)
    record = pipeline.to_dict()

    restored = DataPipeline.from_dict(record)
    assert restored.to_dict() == record
    with pytest.raises(PipelineError, match="cannot resolve 'plan_discover@2.0.0'"):
        PipelineExecutor(versioned_registry()).preflight(restored)


def test_plain_operator_run_replaces_an_executable_declarative_leaf() -> None:
    leaf = CallerLeaf(properties={"case_tag": "leaf"})

    output, output_attributes, meta = leaf.run(INPUT, {})

    assert leaf.name == "caller_leaf"
    assert leaf.description == "Copy rows and mark them as observed."
    assert output == [
        [
            {"order_id": 1, "total": 80.0, "observed": True},
            {"order_id": 2, "total": 125.0, "observed": True},
            {"order_id": 3, "total": 210.0, "observed": True},
        ]
    ]
    assert output_attributes == {}
    assert meta.errors == []
    assert meta.is_empty is False


def test_fixed_pipeline_replaces_a_declarative_expansion() -> None:
    pipeline = DataPipeline(properties={"case_tag": "fixed-graph"})
    input_node = pipeline.define_input(label="input")
    select = pipeline.define_operator(
        "select@2.0.0",
        label="select",
        attributes={"operand_key": "total", "operand": ">", "operand_val": 100},
        properties={"node_tag": "filter"},
    )
    average = pipeline.define_operator(
        "avg@2.0.0",
        label="average",
        attributes={"avg_key": "total", "output_key": "average_total"},
        properties={"node_tag": "aggregate"},
    )
    output_node = pipeline.define_output(label="output")
    pipeline.connect_nodes(input_node, select)
    pipeline.connect_nodes(select, average)
    pipeline.connect_nodes(average, output_node)
    pipeline.set_plan_input(input_node)
    pipeline.set_plan_output(output_node)

    run = PipelineExecutor(versioned_registry()).execute(pipeline, INPUT)

    assert run.failed_node_id is None
    assert run.output_data == [[{"average_total": 167.5}]]
    assert [item.operator_id for item in run.node_runs] == ["select@2.0.0", "avg@2.0.0"]
    assert [item.output_data for item in run.node_runs] == [
        [[{"order_id": 2, "total": 125.0}, {"order_id": 3, "total": 210.0}]],
        [[{"average_total": 167.5}]],
    ]
    assert pipeline.get_properties() == {"case_tag": "fixed-graph"}
    assert pipeline.get_plan_provenance() == "$"
    assert pipeline.get_plan_input_id() == input_node.get_id()
    assert pipeline.get_plan_output_id() == output_node.get_id()
    assert [node.get_id() for node in pipeline.get_next_nodes(input_node)] == [select.get_id()]
    assert [node.get_id() for node in pipeline.get_next_nodes(select)] == [average.get_id()]
    assert [node.get_id() for node in pipeline.get_next_nodes(average)] == [output_node.get_id()]
    assert all(
        pipeline.get_node_status(node) == Status.EXECUTED
        for node in (input_node, select, average, output_node)
    )
    select_entity = pipeline.get_node_entity(select, type="OPERATOR")
    average_entity = pipeline.get_node_entity(average, type="OPERATOR")
    assert select_entity is not None and average_entity is not None
    assert select_entity.get_data("operator_id") == "select@2.0.0"
    assert select_entity.get_properties() == {"node_tag": "filter"}
    assert average_entity.get_data("operator_id") == "avg@2.0.0"
    assert average_entity.get_properties() == {"node_tag": "aggregate"}
