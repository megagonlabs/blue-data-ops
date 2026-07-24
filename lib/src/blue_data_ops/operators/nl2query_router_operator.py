from __future__ import annotations

from typing import Any, ClassVar, cast

from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
)
from blue_data_ops.plan import DataPipeline, PlanRecord, RefinableOperator
from blue_data_ops.plan.refiner import (
    _rewrite_plan_operator_version,  # pyright: ignore[reportPrivateUsage]
    _selected_refinement_version,  # pyright: ignore[reportPrivateUsage]
)

_DATA_DISCOVER = "data_discover@1.0.0"
_NL2LLM = "nl2llm@1.0.0"
_NL2QUERY_ROUTER = "nl2query_router@1.0.0"
_NL2SQL = "nl2sql@1.0.0"


def nl2query_router_operator_function(
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
) -> DataBundle:
    """Return the empty compute result for this refinement-only operator."""
    del input_data, attributes, properties
    return [[]]


def parse_scope(scope: str) -> dict[str, str]:
    """Parse alternating scope keys and values using the source ordering."""
    parts = scope.split("/")[1:]
    parsed: dict[str, str] = {}
    keys = parts[::2]
    if len(keys) <= 1:
        return parsed
    values = parts[1:][::2]
    for index, key in enumerate(keys):
        parsed[key] = values[index]
    return parsed


def nl2query_router_operator_refiner(
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
) -> list[PlanRecord]:
    """Route first-group source records to pinned query operators."""
    pipelines: list[PlanRecord] = []
    if len(input_data) == 0:
        return pipelines

    elements = input_data[0]
    query = attributes.get("search_query")
    columns = attributes.get("columns")
    execute_query = attributes.get("execute_query", True)
    protocol = attributes.get("protocol", "")

    for element in elements:
        name = element["name"]
        element_type = element["type"]
        scope = element["scope"]
        parsed = parse_scope(scope)

        pipeline = DataPipeline(properties=properties)
        input_node = pipeline.define_input(value=None)
        output_node = pipeline.define_output(properties={})
        pipeline.set_plan_input(input_node)
        pipeline.set_plan_output(output_node)

        if element_type == "source":
            source_name = element["name"]
            if "properties" not in element:
                continue
            properties = cast(Properties, element["properties"])
            if "connection" not in properties:
                continue
            connection = cast(dict[str, Any], properties["connection"])
            if "protocol" not in connection:
                continue
            protocol = connection["protocol"]

            if protocol == "openai":
                nl2llm_node = pipeline.define_operator(
                    _NL2LLM,
                    attributes={"source": source_name, "query": query, "attrs": columns},
                    properties={},
                )
                pipeline.connect_nodes(input_node, nl2llm_node)
                pipeline.connect_nodes(nl2llm_node, output_node)
            elif protocol in {"postgres", "mysql", "sqlite"}:
                data_discovery_node = pipeline.define_operator(
                    _DATA_DISCOVER,
                    attributes={
                        "source": source_name,
                        "scope": "/source/" + source_name,
                        "search_query": query,
                        "approximate": True,
                        "concept_type": "collection",
                        "limit": 1,
                        "use_hierarchical_search": True,
                    },
                    properties={},
                )
                nl2query_router_node = pipeline.define_operator(
                    _NL2QUERY_ROUTER,
                    attributes={
                        "search_query": query,
                        "protocol": protocol,
                        "execute_query": True,
                        "columns": columns,
                    },
                    properties={},
                )
                pipeline.connect_nodes(input_node, data_discovery_node)
                pipeline.connect_nodes(data_discovery_node, nl2query_router_node)
                pipeline.connect_nodes(nl2query_router_node, output_node)
            else:
                continue
        elif element_type == "collection":
            source = parsed["source"]
            database = parsed["database"]
            collection = name

            if protocol == "openai":
                nl2llm_node = pipeline.define_operator(
                    _NL2LLM,
                    attributes={"query": query, "attrs": columns},
                    properties={},
                )
                pipeline.connect_nodes(input_node, nl2llm_node)
                pipeline.connect_nodes(nl2llm_node, output_node)
            elif protocol in {"postgres", "mysql", "sqlite"}:
                attr_names = [column["name"] for column in cast(list[dict[str, Any]], columns)]
                nl2sql_node = pipeline.define_operator(
                    _NL2SQL,
                    attributes={
                        "question": query,
                        "protocol": protocol,
                        "source": source,
                        "database": database,
                        "collection": collection,
                        "attr_names": attr_names,
                        "execute_query": execute_query,
                    },
                    properties={},
                )
                pipeline.connect_nodes(input_node, nl2sql_node)
                pipeline.connect_nodes(nl2sql_node, output_node)

        pipelines.append(pipeline.to_dict())

    return pipelines


def nl2query_router_operator_validator(
    attributes: Attributes,
    properties: Properties | None = None,
) -> bool:
    """Validate the raw two-argument attribute contract."""
    del properties
    return NL2QueryRouterOperator()._validate_attributes(  # pyright: ignore[reportPrivateUsage]
        attributes
    )


def nl2query_router_operator_explainer(
    output: DataBundle,
    input_data: DataBundle,
    attributes: Attributes,
) -> dict[str, Any]:
    """Explain the selected query route."""
    return {
        "output": output,
        "input_data": input_data,
        "attributes": attributes,
        "explanation": "routes the execution of query to...",
    }


def _valid_columns(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(column, dict)
        and isinstance(cast(dict[str, Any], column).get("name"), str)
        and (
            "type" not in cast(dict[str, Any], column)
            or isinstance(cast(dict[str, Any], column)["type"], str)
        )
        for column in cast(list[object], value)
    )


def _valid_sources(value: object) -> bool:
    if not isinstance(value, list):
        return False
    for record_value in cast(list[object], value):
        if not isinstance(record_value, dict):
            return False
        record = cast(dict[str, Any], record_value)
        if not all(isinstance(record.get(name), str) for name in ("name", "type", "scope")):
            return False
        record_type = record["type"]
        if record_type == "source":
            source_properties = record.get("properties")
            if not isinstance(source_properties, dict):
                return False
            connection = cast(dict[str, Any], source_properties).get("connection")
            if not isinstance(connection, dict) or not isinstance(
                cast(dict[str, Any], connection).get("protocol"), str
            ):
                return False
        elif record_type == "collection":
            try:
                parsed = parse_scope(cast(str, record["scope"]))
            except (AttributeError, IndexError, TypeError, ValueError):
                return False
            if not parsed.get("source") or not parsed.get("database"):
                return False
        else:
            return False
    return True


class NL2QueryRouterOperator(RefinableOperator):
    """Route natural-language queries according to source metadata."""

    name: ClassVar[str] = "nl2query_router"
    description: ClassVar[str] = "Routees the execution of query, based on source"
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "search_query": AttributeSpec(
            type="str",
            description="Natural language query to process",
            required=True,
        ),
        "columns": AttributeSpec(
            type="list[dict]",
            description="List of attribute specifications (dicts with name and optional type)",
            default=[],
        ),
        "execute_query": AttributeSpec(
            type="bool",
            description="Whether to execute query or just translate nl to query",
            default=True,
        ),
        "protocol": AttributeSpec(
            type="str",
            description="Protocol of the source",
            default="",
        ),
    }
    PROPERTIES: ClassVar[dict[str, Any]] = {"refine": True}

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        return self._execute(input_data, attributes, properties).output_data

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        return FunctionResult(
            nl2query_router_operator_function(input_data, attributes, properties),
            {},
        )

    def refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        return nl2query_router_operator_refiner(input_data, attributes, properties)

    def _pre_validate_normalize(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None,
    ) -> tuple[DataBundle, Attributes]:
        normalized_input, normalized_attributes = super()._pre_validate_normalize(
            input_data,
            attributes,
            properties,
        )
        if "sources" not in normalized_attributes:
            normalized_attributes["sources"] = normalized_input[0] if normalized_input else []
        return [[]], normalized_attributes

    def _refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        del input_data
        records = nl2query_router_operator_refiner(
            [cast(list[dict[str, Any]], attributes["sources"])],
            attributes,
            properties,
        )
        return _rewrite_plan_operator_version(
            records,
            _selected_refinement_version(self),
        )

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        reason = "supply valid query-routing attributes"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, reason)
        if "columns" in attributes and not _valid_columns(attributes["columns"]):
            return ValidationResult(False, reason)
        if "sources" in attributes and not _valid_sources(attributes["sources"]):
            return ValidationResult(False, reason)
        return ValidationResult(True, None)

    def validate(self, *args: Any, **kwargs: Any) -> bool:
        """Keep the source's direct validator and canonical call mismatch."""
        if "input_data" in kwargs or len(args) == 3:
            raise TypeError(
                "default_attributes_validator() got an unexpected keyword argument 'input_data'"
            )
        if args:
            attributes = args[0]
            properties = args[1] if len(args) > 1 else kwargs.get("properties")
        else:
            attributes = kwargs["attributes"]
            properties = kwargs.get("properties")
        return nl2query_router_operator_validator(attributes, properties)

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        return nl2query_router_operator_explainer(output, input_data, attributes)


__all__ = [
    "NL2QueryRouterOperator",
    "nl2query_router_operator_explainer",
    "nl2query_router_operator_function",
    "nl2query_router_operator_refiner",
    "nl2query_router_operator_validator",
    "parse_scope",
]


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when discovered source metadata must be refined into a source-specific query plan."
    ),
    tags=(
        "domain-plan",
        "flow-plan",
        "accepts-metadata",
        "produces-plan",
        "capability-query-routing",
    ),
)
