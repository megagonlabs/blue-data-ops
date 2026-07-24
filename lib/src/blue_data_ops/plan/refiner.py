from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from copy import deepcopy
from typing import Any, ClassVar, cast

from blue_data_ops.operators.operator import (
    Operator,
    _call_with_operator_id,  # pyright: ignore[reportPrivateUsage]
    _error,  # pyright: ignore[reportPrivateUsage]
    _invalid_timeout_error,  # pyright: ignore[reportPrivateUsage]
    _InvalidTimeout,  # pyright: ignore[reportPrivateUsage]
    _meta,  # pyright: ignore[reportPrivateUsage]
    _shutdown_executor,  # pyright: ignore[reportPrivateUsage]
    _timeout_seconds,  # pyright: ignore[reportPrivateUsage]
    _validation_result,  # pyright: ignore[reportPrivateUsage]
    _VersionBindingMixin,  # pyright: ignore[reportPrivateUsage]
    apply_defaults,
    default_operator_refiner,
)
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    ErrorCategory,
    ErrorCode,
    ErrorStage,
    ExecMeta,
    Properties,
)
from blue_data_ops.plan.pipeline import DataPipeline, Node
from blue_data_ops.plan.types import EntityType, NodeType, PlanRecord, Status


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

    def _refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        """Adapt the raw v1 refiner to the normalized v2 boundary."""
        return self.refiner(input_data, attributes, properties)

    def _pre_validate_normalize(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None,
    ) -> tuple[DataBundle, Attributes]:
        """Copy canonical refinement inputs before defaults and validation."""
        del properties
        return deepcopy(input_data), deepcopy(attributes)

    def refine(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> tuple[list[DataPipeline], ExecMeta]:
        """Return normalized plan objects and execution metadata."""
        try:
            timeout = _timeout_seconds(properties)
        except _InvalidTimeout:
            return [], _meta(error=_invalid_timeout_error(self.operator_id))
        if timeout is None:
            return self._refine_once(input_data, attributes, properties)

        executor: ThreadPoolExecutor | None = None
        try:
            executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="blue-data-ops-refine",
            )
            future = executor.submit(self._refine_once, input_data, attributes, properties)
        except Exception:
            _shutdown_executor(executor)
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.REFINEMENT_FAILED,
                ErrorStage.REFINE,
                "refinement failed",
            )
            return [], _meta(error=error)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            try:
                future.cancel()
            except Exception:
                pass
            error = _error(
                self.operator_id,
                ErrorCategory.TIMEOUT,
                ErrorCode.OPERATOR_TIMEOUT,
                ErrorStage.REFINE,
                "operator timed out",
            )
            return [], _meta(error=error)
        except Exception:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.REFINEMENT_FAILED,
                ErrorStage.REFINE,
                "refinement failed",
            )
            return [], _meta(error=error)
        finally:
            _shutdown_executor(executor)

    def _refine_once(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None,
    ) -> tuple[list[DataPipeline], ExecMeta]:
        try:
            call_input, normalized_attributes = self._pre_validate_normalize(
                input_data,
                attributes,
                properties,
            )
        except Exception:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.DEFAULTS_FAILED,
                ErrorStage.DEFAULTS,
                "default materialization failed",
            )
            return [], _meta(error=error)

        try:
            schema = self._refresh_attribute_projection()  # pyright: ignore[reportPrivateUsage]
        except Exception:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.VALIDATION_FAILED,
                ErrorStage.VALIDATE,
                "validator failed",
            )
            return [], _meta(error=error)

        try:
            call_attributes = apply_defaults(normalized_attributes, schema)
        except Exception:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.DEFAULTS_FAILED,
                ErrorStage.DEFAULTS,
                "default materialization failed",
            )
            return [], _meta(error=error)

        try:
            validator: Callable[[DataBundle, Attributes, Properties | None], object] = (
                self._validate_input
            )
            validation_value = validator(call_input, call_attributes, properties)
        except Exception:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.VALIDATION_FAILED,
                ErrorStage.VALIDATE,
                "validator failed",
            )
            return [], _meta(error=error)

        try:
            validation = _validation_result(validation_value)
        except Exception:
            validation = None
        if validation is None:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.VALIDATION_RESULT_INVALID,
                ErrorStage.VALIDATE,
                "validator returned an invalid result",
            )
            return [], _meta(error=error)
        if not validation.ok:
            if not isinstance(validation.reason, str) or not validation.reason:
                error = _error(
                    self.operator_id,
                    ErrorCategory.FAILED,
                    ErrorCode.VALIDATION_RESULT_INVALID,
                    ErrorStage.VALIDATE,
                    "validator returned an invalid result",
                )
            else:
                error = _error(
                    self.operator_id,
                    ErrorCategory.RECOVERABLE,
                    ErrorCode.INVALID_INPUT,
                    ErrorStage.VALIDATE,
                    "input validation failed",
                    suggestion=validation.reason,
                )
            return [], _meta(error=error)

        try:
            refiner: Callable[[DataBundle, Attributes, Properties | None], object] = self._refiner
            records_value = cast(object, refiner(call_input, call_attributes, properties))
        except Exception:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.REFINEMENT_FAILED,
                ErrorStage.REFINE,
                "refinement failed",
            )
            return [], _meta(error=error)

        if records_value is None:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.REFINEMENT_FAILED,
                ErrorStage.REFINE,
                "refinement failed",
            )
            return [], _meta(error=error)

        try:
            records = _plan_records(records_value)
        except Exception:
            records = None
        if records is None:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.REFINEMENT_RESULT_INVALID,
                ErrorStage.NORMALIZE,
                "refiner returned an invalid result",
            )
            return [], _meta(error=error)
        try:
            plans = [DataPipeline.from_dict(record) for record in records]
        except Exception:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.REFINEMENT_RESULT_INVALID,
                ErrorStage.NORMALIZE,
                "refiner returned an invalid result",
            )
            return [], _meta(error=error)
        return plans, _meta(is_empty=not plans)


class _VersionBoundRefinableOperator(  # pyright: ignore[reportUnusedClass]
    _VersionBindingMixin,
    RefinableOperator,
):
    """A refinable registration bound to one ID without copying its implementation."""

    def refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        target = cast(RefinableOperator, self._target)
        return _call_with_operator_id(
            target,
            self.operator_id,
            target.refiner,
            input_data,
            attributes,
            properties,
        )

    def _refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        target = cast(RefinableOperator, self._target)
        return _call_with_operator_id(
            target,
            self.operator_id,
            target._refiner,  # pyright: ignore[reportPrivateUsage]
            input_data,
            attributes,
            properties,
        )

    def _pre_validate_normalize(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None,
    ) -> tuple[DataBundle, Attributes]:
        target = cast(RefinableOperator, self._target)
        return _call_with_operator_id(
            target,
            self.operator_id,
            target._pre_validate_normalize,  # pyright: ignore[reportPrivateUsage]
            input_data,
            attributes,
            properties,
        )


def _selected_refinement_version(  # pyright: ignore[reportUnusedFunction]
    operator: RefinableOperator,
) -> str | None:
    """Return a registry-selected version, excluding direct unbound calls."""
    if getattr(operator, "_registered_operator_id", None) is None:
        return None
    _, separator, version = operator.operator_id.rpartition("@")
    return version if separator else None


def _rewrite_plan_operator_version(  # pyright: ignore[reportUnusedFunction]
    records: list[PlanRecord],
    version: str | None,
) -> list[PlanRecord]:
    """Rewrite pinned operator entities only for a selected v2 refinement."""
    if version != "2.0.0":
        return records
    for record in records:
        entities = cast(dict[str, Any], record.get("entities", {}))
        operator_entities = cast(
            dict[str, PlanRecord],
            entities.get(str(EntityType.OPERATOR), {}),
        )
        for entity in operator_entities.values():
            operator_id = entity.get("operator_id")
            if isinstance(operator_id, str) and "@" in operator_id:
                name, _, _ = operator_id.rpartition("@")
                entity["operator_id"] = f"{name}@{version}"
    return records


def _plan_records(value: object) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    records: list[dict[str, Any]] = []
    for record in cast(list[object], value):
        if not isinstance(record, dict):
            return None
        records.append(cast(dict[str, Any], record))
    return records


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


def normalized_declarative_operator_refiner(
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
) -> list[PlanRecord]:
    """Build declarative plans with predecessor edges local to each plan."""
    del attributes
    plans = cast(dict[str, Any], properties)["plans"]
    if plans is None:
        return []

    pipelines: list[PlanRecord] = []
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
                prev_id = mappings[prev_label]
                pipeline.connect_nodes(cast(str, prev_id), cast(str, node_id))
            for next_label in cast(list[str], node_spec.get("next", [])):
                next_id = mappings[next_label]
                pipeline.connect_nodes(cast(str, node_id), cast(str, next_id))

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
        name = property_data["name"] if "name" in property_data else type(self).name
        description = (
            property_data["description"]
            if "description" in property_data
            else type(self).description
        )
        super().__init__(
            name=name,
            description=description,
            properties=property_data,
            refiner=self.refiner,
        )
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

    def _refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        if self.operator_id.endswith("@1.0.0"):
            return self.refiner(input_data, attributes, properties)
        return normalized_declarative_operator_refiner(input_data, attributes, properties)

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
    "normalized_declarative_operator_refiner",
]
