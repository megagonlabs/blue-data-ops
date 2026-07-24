from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any, ClassVar, cast

import pytest

from blue_data_ops.operators import (
    AttributeSpec,
    Operator,
    OperatorRegistry,
    ValidationResult,
    versioned_registry,
)
from blue_data_ops.operators.types import Attributes, DataBundle, Properties
from blue_data_ops.plan import (
    DataPipeline,
    Status,
)
from blue_data_ops.plan.executor import PipelineError, PipelineExecutor


def _order_plan() -> DataPipeline:
    pipeline = DataPipeline(id="orders", properties={"plan": "base"})
    source = pipeline.define_input("orders")
    selected = pipeline.define_operator(
        "select@2.0.0",
        label="orders-above-100",
        attributes={"operand_key": "total", "operand": ">", "operand_val": 100},
        properties={"node": "select"},
    )
    average = pipeline.define_operator(
        "avg@2.0.0",
        label="average-total",
        attributes={"avg_key": "total", "output_key": "average_total"},
    )
    result = pipeline.define_output("answer")
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(result)
    pipeline.connect_nodes(source, selected)
    pipeline.connect_nodes(selected, average)
    pipeline.connect_nodes(average, result)
    return pipeline


def test_executes_round_tripped_linear_plan_with_pinned_ids() -> None:
    source_data = [
        [
            {"order_id": 1, "total": 80.0},
            {"order_id": 2, "total": 125.0},
            {"order_id": 3, "total": 210.0},
            {"order_id": 4, "total": 100.0},
        ]
    ]
    original = copy.deepcopy(source_data)
    pipeline = DataPipeline.from_dict(copy.deepcopy(_order_plan().to_dict()))

    run = PipelineExecutor(versioned_registry()).execute(
        pipeline,
        source_data,
        {"call": "value"},
    )

    assert run.succeeded
    assert run.failed_node_id is None
    assert run.output_data == [[{"average_total": 167.5}]]
    assert [item.operator_id for item in run.node_runs] == [
        "select@2.0.0",
        "avg@2.0.0",
    ]
    assert all(item.status == Status.EXECUTED for item in run.node_runs)
    assert source_data == original
    assert pipeline.get_node_status("orders") == Status.EXECUTED
    assert pipeline.get_node_status("answer") == Status.EXECUTED


class _EchoOperator(Operator):
    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "Return every input group."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        del attributes, properties
        return input_data


class _FailOperator(Operator):
    name: ClassVar[str] = "fail"
    description: ClassVar[str] = "Return a validation failure."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        raise AssertionError("validation must suppress the body")

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        del input_data, attributes, properties
        return ValidationResult(False, "the fixture rejects this call")


class _FirstOperator(_EchoOperator):
    name: ClassVar[str] = "first"


class _SecondOperator(_EchoOperator):
    name: ClassVar[str] = "second"


class _SinkOperator(_EchoOperator):
    name: ClassVar[str] = "sink"


class _DownstreamOperator(_EchoOperator):
    name: ClassVar[str] = "downstream"


class _EmptyOperator(_EchoOperator):
    name: ClassVar[str] = "empty"

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        del input_data, attributes, properties
        return [[]]


class _MutatingOperator(_EchoOperator):
    name: ClassVar[str] = "mutating"

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        del attributes, properties
        input_data[0][0]["changed"] = True
        return input_data


class _CountingOperator(_EchoOperator):
    name: ClassVar[str] = "counting"

    def __init__(self) -> None:
        self.calls = 0
        super().__init__()

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        self.calls += 1
        return super().apply(input_data, attributes, properties)


class _RecordPropertiesOperator(Operator):
    name: ClassVar[str] = "record_properties"
    description: ClassVar[str] = "Record active properties."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def __init__(self) -> None:
        self.seen: dict[str, Any] | None = None
        super().__init__()

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        del attributes
        self.seen = dict(properties or {})
        return input_data


def _local_registry(*operators: Operator) -> OperatorRegistry:
    registry = OperatorRegistry()
    for operator in operators:
        registry.register(operator, "2.0.0")
    return registry


def test_branch_fan_in_uses_predecessor_order_once() -> None:
    first = _FirstOperator()
    second = _SecondOperator()
    sink = _SinkOperator()
    registry = _local_registry(first, second, sink)
    pipeline = DataPipeline()
    source = pipeline.define_input("source")
    left = pipeline.define_operator("first@2.0.0")
    right = pipeline.define_operator("second@2.0.0")
    joined = pipeline.define_operator("sink@2.0.0")
    output = pipeline.define_output("output")
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(output)
    pipeline.connect_nodes(source, left)
    pipeline.connect_nodes(source, right)
    pipeline.connect_nodes(left, joined)
    pipeline.connect_nodes(right, joined)
    pipeline.connect_nodes(joined, output)

    run = PipelineExecutor(registry).execute(pipeline, [[{"side": "input"}]])

    assert run.output_data == [[{"side": "input"}], [{"side": "input"}]]
    assert [item.operator_id for item in run.node_runs] == [
        "first@2.0.0",
        "second@2.0.0",
        "sink@2.0.0",
    ]


def test_failure_stops_downstream_and_remains_structured() -> None:
    failing = _FailOperator()
    downstream = _DownstreamOperator()
    registry = _local_registry(failing, downstream)
    pipeline = DataPipeline()
    source = pipeline.define_input()
    failed = pipeline.define_operator("fail@2.0.0")
    skipped = pipeline.define_operator("downstream@2.0.0")
    output = pipeline.define_output()
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(output)
    pipeline.connect_nodes(source, failed)
    pipeline.connect_nodes(failed, skipped)
    pipeline.connect_nodes(skipped, output)

    run = PipelineExecutor(registry).execute(pipeline, [[{"x": 1}]])

    assert not run.succeeded
    assert run.failed_node_id == failed.get_id()
    assert run.output_data == [[]]
    assert len(run.node_runs) == 1
    assert run.node_runs[0].exec_meta.errors[0].operator_id == "fail@2.0.0"
    assert pipeline.get_node_status(failed) == Status.FAILED
    assert pipeline.get_node_status(skipped) == Status.FAILED
    assert pipeline.get_node_status(output) == Status.FAILED


def test_failure_marks_planned_downstream_nodes_failed() -> None:
    registry = _local_registry(_FailOperator(), _DownstreamOperator())
    pipeline = DataPipeline()
    source = pipeline.define_input()
    failed = pipeline.define_operator("fail@2.0.0")
    skipped = pipeline.define_operator("downstream@2.0.0")
    output = pipeline.define_output()
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(output)
    pipeline.connect_nodes(source, failed)
    pipeline.connect_nodes(failed, skipped)
    pipeline.connect_nodes(skipped, output)
    pipeline.set_node_status(skipped, Status.PLANNED)
    pipeline.set_node_status(output, Status.INITED)

    PipelineExecutor(registry).execute(pipeline, [[{"x": 1}]])

    assert pipeline.get_node_status(skipped) == Status.FAILED
    assert pipeline.get_node_status(output) == Status.FAILED


def test_successful_empty_reaches_the_next_node() -> None:
    registry = _local_registry(_EmptyOperator(), _DownstreamOperator())
    pipeline = DataPipeline()
    source = pipeline.define_input()
    empty = pipeline.define_operator("empty@2.0.0")
    downstream = pipeline.define_operator("downstream@2.0.0")
    output = pipeline.define_output()
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(output)
    pipeline.connect_nodes(source, empty)
    pipeline.connect_nodes(empty, downstream)
    pipeline.connect_nodes(downstream, output)

    run = PipelineExecutor(registry).execute(pipeline, [[{"x": 1}]])

    assert run.succeeded
    assert run.output_data == [[]]
    assert [item.exec_meta.is_empty for item in run.node_runs] == [True, True]
    assert all(item.status == Status.EXECUTED for item in run.node_runs)


def test_operator_mutation_does_not_reach_caller_input() -> None:
    registry = _local_registry(_MutatingOperator())
    pipeline = DataPipeline()
    source = pipeline.define_input()
    action = pipeline.define_operator("mutating@2.0.0")
    output = pipeline.define_output()
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(output)
    pipeline.connect_nodes(source, action)
    pipeline.connect_nodes(action, output)
    caller_input = [[{"x": 1}]]

    run = PipelineExecutor(registry).execute(pipeline, caller_input)

    assert caller_input == [[{"x": 1}]]
    assert run.output_data == [[{"x": 1, "changed": True}]]


def test_property_precedence_is_plan_then_call_then_node() -> None:
    operator = _RecordPropertiesOperator()
    registry = _local_registry(operator)
    pipeline = DataPipeline(properties={"shared": "plan", "plan": 1})
    source = pipeline.define_input()
    action = pipeline.define_operator(
        "record_properties@2.0.0",
        properties={"shared": "node", "node": 3},
    )
    output = pipeline.define_output()
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(output)
    pipeline.connect_nodes(source, action)
    pipeline.connect_nodes(action, output)

    PipelineExecutor(registry).execute(
        pipeline,
        [[{"x": 1}]],
        {"shared": "call", "call": 2},
    )

    assert operator.seen == {
        "shared": "node",
        "plan": 1,
        "call": 2,
        "node": 3,
    }


def _missing_output(plan: DataPipeline) -> None:
    plan.set_plan_output_id("missing")


def _dangling_successor(plan: DataPipeline) -> None:
    node = plan.get_node("orders")
    assert node is not None
    next_nodes = node.get_data("next")
    assert isinstance(next_nodes, list)
    cast(list[Any], next_nodes).append("missing")


def _malformed_edge(plan: DataPipeline) -> None:
    node = plan.get_node("orders")
    assert node is not None
    next_nodes = node.get_data("next")
    assert isinstance(next_nodes, list)
    cast(list[Any], next_nodes).append({"not": "an id"})


def _cycle(plan: DataPipeline) -> None:
    plan.connect_nodes("answer", "orders")


def _replayed_input(plan: DataPipeline) -> None:
    node = plan.get_node("orders")
    assert node is not None
    node.set_data("status", Status.EXECUTED)


def _replayed_operator(plan: DataPipeline) -> None:
    node = plan.get_node("orders-above-100")
    assert node is not None
    node.set_data("status", Status.EXECUTED)


def _replayed_output(plan: DataPipeline) -> None:
    node = plan.get_node("answer")
    assert node is not None
    node.set_data("status", Status.FAILED)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (_missing_output, "input and output"),
        (_dangling_successor, "dangling successor"),
        (_malformed_edge, "malformed edges"),
        (_cycle, "cycle"),
        (_replayed_input, "already started"),
        (_replayed_operator, "already started"),
        (_replayed_output, "already started"),
    ],
)
def test_preflight_rejects_invalid_or_replayed_plans(
    mutate: Callable[[DataPipeline], None],
    match: str,
) -> None:
    pipeline = _order_plan()
    mutate(pipeline)

    with pytest.raises(PipelineError, match=match):
        PipelineExecutor(versioned_registry()).execute(pipeline, [[{"total": 200}]])


def test_preflight_rejects_refinable_operator_nodes() -> None:
    pipeline = DataPipeline()
    source = pipeline.define_input()
    action = pipeline.define_operator(
        "query_breakdown@2.0.0",
        attributes={"query": "question"},
    )
    output = pipeline.define_output()
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(output)
    pipeline.connect_nodes(source, action)
    pipeline.connect_nodes(action, output)

    with pytest.raises(PipelineError, match="materialized non-refinable"):
        PipelineExecutor(versioned_registry()).execute(pipeline, [[]])


def test_preflight_resolves_every_id_before_any_body_runs() -> None:
    counting = _CountingOperator()
    registry = _local_registry(counting)
    pipeline = DataPipeline()
    source = pipeline.define_input()
    first = pipeline.define_operator("counting@2.0.0")
    unresolved = pipeline.define_operator("counting@2.0.0")
    entity = pipeline.get_node_entity(unresolved, type="OPERATOR")
    assert entity is not None
    entity.set_data("operator_id", "missing@2.0.0")
    output = pipeline.define_output()
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(output)
    pipeline.connect_nodes(source, first)
    pipeline.connect_nodes(first, unresolved)
    pipeline.connect_nodes(unresolved, output)

    with pytest.raises(PipelineError, match="cannot resolve"):
        PipelineExecutor(registry).execute(pipeline, [[{"x": 1}]])

    assert counting.calls == 0
