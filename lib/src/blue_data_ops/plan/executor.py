from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.registry import OperatorRegistry
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    ErrorCategory,
    ErrorCode,
    ErrorRecord,
    ErrorStage,
    ExecMeta,
    Properties,
)
from blue_data_ops.plan.pipeline import DataPipeline, Entity, Node
from blue_data_ops.plan.refiner import RefinableOperator
from blue_data_ops.plan.types import EntityType, NodeType, Status


class PipelineError(ValueError):
    """The pipeline cannot be executed safely."""


@dataclass(frozen=True)
class NodeRun:
    node_id: str
    operator_id: str
    status: Status
    output_data: DataBundle
    output_attributes: Attributes
    exec_meta: ExecMeta


@dataclass(frozen=True)
class PipelineRun:
    output_data: DataBundle
    node_runs: tuple[NodeRun, ...]
    failed_node_id: str | None

    @property
    def succeeded(self) -> bool:
        return self.failed_node_id is None


@dataclass(frozen=True)
class PipelinePreflight:
    node_order: tuple[str, ...]
    operator_ids: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedNode:
    node_id: str
    operator_id: str
    operator: Operator
    attributes: Attributes
    properties: Properties


class PipelineExecutor:
    """Execute a materialized local pipeline with exact registry resolution."""

    def __init__(self, registry: OperatorRegistry) -> None:
        self._registry = registry

    def preflight(
        self,
        pipeline: DataPipeline,
        properties: Properties | None = None,
    ) -> PipelinePreflight:
        """Validate and resolve a materialized pipeline without running operators."""
        order, prepared = self._prepare(pipeline, properties)
        return PipelinePreflight(
            node_order=order,
            operator_ids=tuple(
                prepared[node_id].operator_id for node_id in order if node_id in prepared
            ),
        )

    def execute(
        self,
        pipeline: DataPipeline,
        input_data: DataBundle,
        properties: Properties | None = None,
    ) -> PipelineRun:
        order, prepared = self._prepare(pipeline, properties)
        if not _is_data_bundle(input_data):
            raise PipelineError("input_data must be a list of record groups")
        try:
            active_input = deepcopy(input_data)
        except Exception:
            raise PipelineError("input_data could not be copied") from None

        input_node = cast(Node, pipeline.get_plan_input())
        output_node = cast(Node, pipeline.get_plan_output())
        pipeline.set_node_value(input_node, active_input)
        pipeline.set_node_status(input_node, Status.EXECUTED)

        node_runs: list[NodeRun] = []
        for node_id in order:
            node = cast(Node, pipeline.get_node(node_id))
            if node.get_type() in {str(NodeType.INPUT), str(NodeType.OUTPUT)}:
                continue
            item = prepared[node_id]
            call_input = _aggregate_predecessors(pipeline, node)
            pipeline.set_node_status(node, Status.EXECUTING)
            output_data: DataBundle
            output_attributes: Attributes
            exec_meta: ExecMeta
            try:
                output_data, output_attributes, exec_meta = item.operator.run(
                    call_input,
                    item.attributes,
                    item.properties,
                )
            except Exception:
                output_data = [[]]
                output_attributes = {}
                exec_meta = _execution_failed(item.operator_id)

            failed = bool(exec_meta.errors)
            status = Status.FAILED if failed else Status.EXECUTED
            pipeline.set_node_value(node, output_data)
            pipeline.set_node_status(node, status)
            node_runs.append(
                NodeRun(
                    node_id=node_id,
                    operator_id=item.operator_id,
                    status=status,
                    output_data=output_data,
                    output_attributes=output_attributes,
                    exec_meta=exec_meta,
                )
            )
            if failed:
                _mark_unfinished_failed(pipeline, order)
                return PipelineRun(
                    output_data=[[]],
                    node_runs=tuple(node_runs),
                    failed_node_id=node_id,
                )

        final_output = _aggregate_predecessors(pipeline, output_node)
        pipeline.set_node_value(output_node, final_output)
        pipeline.set_node_status(output_node, Status.EXECUTED)
        return PipelineRun(
            output_data=final_output,
            node_runs=tuple(node_runs),
            failed_node_id=None,
        )

    def _prepare(
        self,
        pipeline: DataPipeline,
        properties: Properties | None,
    ) -> tuple[tuple[str, ...], dict[str, _PreparedNode]]:
        raw_nodes: object = pipeline.get_data("nodes")
        if not isinstance(raw_nodes, dict) or not raw_nodes:
            raise PipelineError("pipeline has no nodes")
        nodes = cast(dict[str, object], raw_nodes)

        input_id = pipeline.get_plan_input_id()
        output_id = pipeline.get_plan_output_id()
        if input_id not in nodes or output_id not in nodes:
            raise PipelineError("pipeline must declare existing input and output nodes")

        input_nodes = [
            node_id
            for node_id, record in nodes.items()
            if _node_record(node_id, record).get("type") == str(NodeType.INPUT)
        ]
        output_nodes = [
            node_id
            for node_id, record in nodes.items()
            if _node_record(node_id, record).get("type") == str(NodeType.OUTPUT)
        ]
        if input_nodes != [input_id] or output_nodes != [output_id]:
            raise PipelineError("pipeline must have one declared input and one declared output")

        _validate_nodes_and_edges(nodes)
        order = _topological_order(nodes)
        _validate_reachability(nodes, input_id, output_id)

        call_properties: Properties = {} if properties is None else properties
        raw_plan_properties: object = pipeline.get_data("properties")
        if not isinstance(raw_plan_properties, dict):
            raise PipelineError("pipeline properties must be a dictionary")
        plan_properties = cast(Properties, raw_plan_properties)

        prepared: dict[str, _PreparedNode] = {}
        for node_id in order:
            record = _node_record(node_id, nodes[node_id])
            status = record.get("status")
            if status in {
                str(Status.EXECUTING),
                str(Status.EXECUTED),
                str(Status.FAILED),
                Status.EXECUTING,
                Status.EXECUTED,
                Status.FAILED,
            }:
                raise PipelineError(f"node {node_id!r} has already started")
            if record["type"] != str(NodeType.OPERATOR):
                continue
            node = cast(Node, pipeline.get_node(node_id))
            entity = pipeline.get_node_entity(node, type=str(EntityType.OPERATOR))
            prepared[node_id] = self._prepare_operator(
                node_id,
                entity,
                plan_properties,
                call_properties,
            )
        return order, prepared

    def _prepare_operator(
        self,
        node_id: str,
        entity: Entity | None,
        plan_properties: Properties,
        call_properties: Properties,
    ) -> _PreparedNode:
        if entity is None:
            raise PipelineError(f"operator node {node_id!r} has no operator entity")
        operator_id = entity.get_data("operator_id")
        attributes = entity.get_data("attributes")
        entity_properties = entity.get_data("properties")
        if not isinstance(operator_id, str):
            raise PipelineError(f"operator node {node_id!r} has no pinned operator id")
        if not isinstance(attributes, dict) or not isinstance(entity_properties, dict):
            raise PipelineError(f"operator node {node_id!r} has malformed call data")
        try:
            operator = self._registry.resolve(operator_id)
        except Exception:
            raise PipelineError(
                f"operator node {node_id!r} cannot resolve {operator_id!r}"
            ) from None
        if isinstance(operator, RefinableOperator):
            raise PipelineError(
                f"operator node {node_id!r} requires a materialized non-refinable operator"
            )
        try:
            call_attributes = deepcopy(cast(Attributes, attributes))
        except Exception:
            raise PipelineError(
                f"operator node {node_id!r} attributes could not be copied"
            ) from None
        active_properties: Properties = dict(plan_properties)
        active_properties.update(call_properties)
        active_properties.update(cast(Properties, entity_properties))
        return _PreparedNode(
            node_id=node_id,
            operator_id=operator_id,
            operator=operator,
            attributes=call_attributes,
            properties=active_properties,
        )


def _is_data_bundle(value: object) -> bool:
    if not isinstance(value, list):
        return False
    return all(
        isinstance(group, list)
        and all(isinstance(record, dict) for record in cast(list[object], group))
        for group in cast(list[object], value)
    )


def _node_record(node_id: str, value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PipelineError(f"node {node_id!r} has a malformed record")
    record = cast(dict[str, Any], value)
    if record.get("id") != node_id:
        raise PipelineError(f"node {node_id!r} has a malformed record")
    return record


def _validate_nodes_and_edges(nodes: dict[str, object]) -> None:
    supported = {str(NodeType.INPUT), str(NodeType.OUTPUT), str(NodeType.OPERATOR)}
    for node_id, raw_record in nodes.items():
        record = _node_record(node_id, raw_record)
        if record.get("type") not in supported:
            raise PipelineError(f"node {node_id!r} has an unsupported type")
        raw_previous: object = record.get("prev")
        raw_following: object = record.get("next")
        if not isinstance(raw_previous, list) or not isinstance(raw_following, list):
            raise PipelineError(f"node {node_id!r} has malformed edges")
        previous = cast(list[object], raw_previous)
        following = cast(list[object], raw_following)
        if any(not isinstance(other_id, str) for other_id in previous + following):
            raise PipelineError(f"node {node_id!r} has malformed edges")
        previous_ids = cast(list[str], previous)
        following_ids = cast(list[str], following)
        if len(previous_ids) != len(set(previous_ids)) or len(following_ids) != len(
            set(following_ids)
        ):
            raise PipelineError(f"node {node_id!r} has duplicate edges")
        for other_id in previous_ids:
            if other_id not in nodes:
                raise PipelineError(f"node {node_id!r} has a dangling predecessor")
            other_record = _node_record(other_id, nodes[other_id])
            if node_id not in other_record.get("next", []):
                raise PipelineError(f"node {node_id!r} has a non-reciprocal predecessor")
        for other_id in following_ids:
            if other_id not in nodes:
                raise PipelineError(f"node {node_id!r} has a dangling successor")
            other_record = _node_record(other_id, nodes[other_id])
            if node_id not in other_record.get("prev", []):
                raise PipelineError(f"node {node_id!r} has a non-reciprocal successor")


def _topological_order(nodes: dict[str, object]) -> tuple[str, ...]:
    indegree = {
        node_id: len(cast(list[object], _node_record(node_id, record)["prev"]))
        for node_id, record in nodes.items()
    }
    ready = [node_id for node_id in nodes if indegree[node_id] == 0]
    order: list[str] = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        record = _node_record(node_id, nodes[node_id])
        for next_id in cast(list[str], record["next"]):
            indegree[next_id] -= 1
            if indegree[next_id] == 0:
                ready.append(next_id)
    if len(order) != len(nodes):
        raise PipelineError("pipeline contains a cycle")
    return tuple(order)


def _validate_reachability(
    nodes: dict[str, object],
    input_id: str,
    output_id: str,
) -> None:
    forward = _walk(nodes, input_id, "next")
    backward = _walk(nodes, output_id, "prev")
    if forward != set(nodes) or backward != set(nodes):
        raise PipelineError("every node must lie on a path from input to output")


def _walk(
    nodes: dict[str, object],
    start: str,
    edge: str,
) -> set[str]:
    seen: set[str] = set()
    pending = [start]
    while pending:
        node_id = pending.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        record = _node_record(node_id, nodes[node_id])
        pending.extend(cast(list[str], record[edge]))
    return seen


def _aggregate_predecessors(pipeline: DataPipeline, node: Node) -> DataBundle:
    result: DataBundle = []
    for previous in pipeline.get_prev_nodes(node):
        value = pipeline.get_node_value(previous)
        if not _is_data_bundle(value):
            raise PipelineError(f"node {previous.get_id()!r} produced malformed data")
        result.extend(cast(DataBundle, value))
    return result


def _mark_unfinished_failed(pipeline: DataPipeline, order: tuple[str, ...]) -> None:
    for node_id in order:
        node = cast(Node, pipeline.get_node(node_id))
        if pipeline.get_node_status(node) not in {
            Status.EXECUTED,
            Status.FAILED,
        }:
            pipeline.set_node_status(node, Status.FAILED)


def _execution_failed(operator_id: str) -> ExecMeta:
    return ExecMeta(
        is_empty=False,
        errors=[
            ErrorRecord(
                category=ErrorCategory.FAILED,
                code=ErrorCode.EXECUTION_FAILED,
                operator_id=operator_id,
                stage=ErrorStage.EXECUTE,
                message="operator execution failed",
                retryable=False,
                suggestion=None,
            )
        ],
        logs=[],
        traces={},
    )
