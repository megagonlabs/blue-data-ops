from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, cast

from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import Attributes, DataBundle, Properties
from blue_data_ops.plan.pipeline import DataPipeline, Node
from blue_data_ops.plan.types import NodeType, PlanRecord, Status


class RefinableOperator(Operator, ABC):
    """Operator with a plan-producing refinement body."""

    @abstractmethod
    def refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        """Build ordered serialized plans for a valid refinement call."""


def default_operator_refiner(
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
) -> list[PlanRecord]:
    """Return no alternatives for an operator without refinement logic."""
    del input_data, attributes, properties
    return []


def declarative_operator_refiner(
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
) -> list[PlanRecord]:
    """Expand ordered declarative node specifications into portable pipelines."""
    del attributes
    plans = cast(dict[str, Any], properties)["plans"]
    if plans is None:
        return []

    pipelines: list[PlanRecord] = []
    unbound = object()
    from_id: str | None | object = unbound
    for plan in cast(list[dict[str, Any]], plans):
        nodes = cast(dict[str, dict[str, Any]], plan["nodes"])
        mappings: dict[str | None, str | None] = {}
        pipeline = DataPipeline(properties=properties)
        plan_input_node = None
        plan_output_node = None

        for node_label, node_spec in nodes.items():
            node_type = node_spec["type"]
            node_id: str | None = None
            if node_type == str(NodeType.OPERATOR):
                operator_node = pipeline.define_operator(
                    cast(str, node_spec["name"]),
                    attributes=cast(dict[str, Any], node_spec.get("attributes", {})),
                    properties=cast(dict[str, Any], node_spec.get("properties", {})),
                )
                node_id = operator_node.get_id()
            elif node_type == str(NodeType.INPUT):
                input_value = node_spec.get("value")
                input_node = pipeline.define_input(
                    label=node_label,
                    value=input_value,
                    properties=cast(dict[str, Any], node_spec.get("properties", {})),
                )
                node_id = input_node.get_id()
                if input_value is None:
                    plan_input_node = input_node
                    plan_input_node.set_data("value", input_data)
                else:
                    input_node.set_data("status", str(Status.EXECUTED))
            elif node_type == str(NodeType.OUTPUT):
                output_node = pipeline.define_output(
                    label=node_label,
                    value=node_spec.get("value"),
                    properties=cast(dict[str, Any], node_spec.get("properties", {})),
                )
                node_id = output_node.get_id()
                plan_output_node = output_node
            mappings[node_label] = node_id
            mappings[node_id] = node_label

        if plan_input_node is None:
            plan_input_node = pipeline.define_input(value=input_data, properties={})
        if plan_output_node is None:
            plan_output_node = pipeline.define_output(properties={})

        for node_label, node_spec in nodes.items():
            node_id = mappings[node_label]
            for prev_label in cast(list[str], node_spec.get("prev", [])):
                to_id = node_id
                prev_id = mappings[prev_label]
                del prev_id
                if from_id is unbound:
                    raise UnboundLocalError(
                        "cannot access local variable 'from_id' where it is not associated "
                        "with a value"
                    )
                pipeline.connect_nodes(cast(str, from_id), cast(str, to_id))
            for next_label in cast(list[str], node_spec.get("next", [])):
                from_id = node_id
                to_id = mappings[next_label]
                pipeline.connect_nodes(cast(str, from_id), cast(str, to_id))

        for operator_id in pipeline.filter_nodes(filter_node_type=[str(NodeType.OPERATOR)]):
            operator_node = pipeline.get_node(operator_id)
            if len(pipeline.get_prev_nodes(operator_id)) == 0:
                pipeline.connect_nodes(plan_input_node, cast(Node, operator_node))
            if len(pipeline.get_next_nodes(operator_id)) == 0:
                pipeline.connect_nodes(cast(Node, operator_node), plan_output_node)

        pipeline.set_plan_input(plan_input_node)
        pipeline.set_plan_output(plan_output_node)
        pipelines.append(pipeline.to_dict())

    return pipelines


class DeclarativeOperator(RefinableOperator):
    """Operator whose properties hold ordered declarative subplans."""

    PROPERTIES: ClassVar[dict[str, list[Any]]] = {"plans": []}
    name = "declarative_operator"
    description = "Declaratively specifies the execution of the operator as a set of plans"
    attributes = {}
    default_attributes: ClassVar[dict[str, Any]] = {}

    def __init__(self, properties: Properties | None = None) -> None:
        property_data = cast(Properties, properties)
        if "name" in property_data:
            object.__setattr__(self, "name", property_data["name"])
        if "description" in property_data:
            object.__setattr__(self, "description", property_data["description"])
        self.properties = property_data
        self.properties["refine"] = True

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        del input_data, attributes, properties
        return [[]]

    def refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        return declarative_operator_refiner(input_data, attributes, properties)

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        return {
            "output": output,
            "input_data": input_data,
            "attributes": attributes,
            "explanation": "Declarative operator passed input data to plans specified",
        }


__all__ = [
    "DeclarativeOperator",
    "RefinableOperator",
    "declarative_operator_refiner",
    "default_operator_refiner",
]
