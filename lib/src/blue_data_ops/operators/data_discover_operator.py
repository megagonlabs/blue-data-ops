from __future__ import annotations

import logging
from typing import Any, ClassVar, cast

from blue_data_ops.data import RegistrySeam, resolve_registry
from blue_data_ops.data.errors import RegistryFailure, RegistryReason
from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class _DataDiscoverFailure(RegistryFailure):
    pass


def _construct_scope(
    scope: str | None,
    source: str | None,
    database: str | None,
    collection: str | None,
    concept_type: str,
    auto_construct: bool = True,
) -> str | None:
    """Construct search scope from attributes based on data registry hierarchy."""
    if scope is None:
        # Component fields refine an explicit scope. Without one, search is unscoped.
        return None

    if not auto_construct:
        return scope.rstrip("/") if scope else "/"

    if scope and scope != "/":
        base_scope = scope.rstrip("/")
    else:
        base_scope = "/"
        if source:
            base_scope = f"/source/{source}"
            if database:
                base_scope = f"/source/{source}/database/{database}"
                if collection:
                    base_scope = f"/source/{source}/database/{database}/collection/{collection}"

    scope_parts = base_scope.split("/")
    scope_components: dict[str, str | None] = {
        "source": None,
        "database": None,
        "collection": None,
        "entity": None,
        "relation": None,
        "attribute": None,
    }

    for i, part in enumerate(scope_parts):
        if part in scope_components and i + 1 < len(scope_parts):
            scope_components[part] = scope_parts[i + 1]

    if source:
        scope_components["source"] = source
    if database:
        scope_components["database"] = database
    if collection:
        scope_components["collection"] = collection

    if concept_type == "source":
        return "/"
    elif concept_type == "database":
        if scope_components["source"]:
            return f"/source/{scope_components['source']}"
        return "/"
    elif concept_type == "collection":
        if scope_components["source"] and scope_components["database"]:
            return f"/source/{scope_components['source']}/database/{scope_components['database']}"
        elif scope_components["source"]:
            return f"/source/{scope_components['source']}"
        return "/"
    elif concept_type in ["entity", "relation"]:
        if (
            scope_components["source"]
            and scope_components["database"]
            and scope_components["collection"]
        ):
            return (
                f"/source/{scope_components['source']}/database/{scope_components['database']}"
                f"/collection/{scope_components['collection']}"
            )
        elif scope_components["source"] and scope_components["database"]:
            return f"/source/{scope_components['source']}/database/{scope_components['database']}"
        elif scope_components["source"]:
            return f"/source/{scope_components['source']}"
        return "/"
    elif concept_type == "attribute":
        if (
            scope_components["source"]
            and scope_components["database"]
            and scope_components["collection"]
            and scope_components["entity"]
        ):
            return (
                f"/source/{scope_components['source']}/database/{scope_components['database']}"
                f"/collection/{scope_components['collection']}/entity/{scope_components['entity']}"
            )
        elif (
            scope_components["source"]
            and scope_components["database"]
            and scope_components["collection"]
            and scope_components["relation"]
        ):
            return (
                f"/source/{scope_components['source']}/database/{scope_components['database']}"
                f"/collection/{scope_components['collection']}/relation/{scope_components['relation']}"
            )
        elif (
            scope_components["source"]
            and scope_components["database"]
            and scope_components["collection"]
        ):
            return (
                f"/source/{scope_components['source']}/database/{scope_components['database']}"
                f"/collection/{scope_components['collection']}"
            )
        elif scope_components["source"] and scope_components["database"]:
            return f"/source/{scope_components['source']}/database/{scope_components['database']}"
        elif scope_components["source"]:
            return f"/source/{scope_components['source']}"
        return "/"
    else:
        return base_scope


_PUBLIC_SOURCE_KINDS = frozenset(
    {"file", "graph", "json", "network", "redis", "sql", "stream", "vector"}
)


def _transform_result(
    result: dict[str, Any],
    concept_type: str,
    registry: RegistrySeam,
) -> dict[str, Any]:
    """Return a catalog match without the stored record's free-form fields."""
    transformed_result: dict[str, Any] = {
        "type": concept_type,
        "name": result["name"],
        "id": result["id"],
        "scope": result["scope"],
    }
    if "score" in result:
        transformed_result["score"] = float(result["score"])

    if concept_type == "source":
        record = registry.get_record(result["name"], concept_type, result["scope"])
        record_fields = cast(dict[str, object], record) if isinstance(record, dict) else {}
        properties = record_fields.get("properties")
        kind = (
            cast(dict[str, object], properties).get("kind")
            if isinstance(properties, dict)
            else None
        )
        if type(kind) is str and kind in _PUBLIC_SOURCE_KINDS:
            transformed_result["properties"] = {"kind": kind}

    return transformed_result


class DataDiscoverOperator(Operator):
    """Discover registry records through hierarchical or regular search."""

    name: ClassVar[str] = "data_discover"
    description: ClassVar[str] = "Discovers data sources using the data registry"
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "search_query": AttributeSpec(
            type="str",
            description="Text to search for in source names and descriptions",
            required=True,
            default="",
        ),
        "approximate": AttributeSpec(
            type="bool",
            description="Whether to use approximate (vector) search",
            required=True,
            default=True,
        ),
        "hybrid": AttributeSpec(
            type="bool", description="Whether to use hybrid search (text + vector)", default=False
        ),
        "limit": AttributeSpec(
            type="int", description="Max number of results to return (-1, unlimited)", default=-1
        ),
        "page": AttributeSpec(type="int", description="Page number for pagination", default=0),
        "page_size": AttributeSpec(
            type="int",
            description="Number of results per page (default: 10, max: 100)",
            default=10,
        ),
        "include_metadata": AttributeSpec(
            type="bool",
            description="Must be false; discovery does not return stored metadata",
            default=False,
        ),
        "threshold": AttributeSpec(
            type="float",
            description=(
                "Similarity threshold for filtering results (0.0-1.0, lower = more "
                "similar, only applies to approximate/hybrid search)"
            ),
            default=0.5,
        ),
        "progressive_pagination": AttributeSpec(
            type="bool",
            description=(
                "Whether to use progressive pagination for approximate/hybrid search "
                "(searches all pages until threshold exceeded)"
            ),
            default=False,
        ),
        "concept_type": AttributeSpec(
            type="str",
            description=(
                "Record type to search for (e.g., 'source', 'database', 'collection', "
                "'entity', 'attribute', 'relation')"
            ),
            default="source",
        ),
        "use_hierarchical_search": AttributeSpec(
            type="bool",
            description="Whether to use hierarchical search or regular search",
            default=True,
        ),
        "scope": AttributeSpec(
            type="str",
            description=(
                "Base search scope. When omitted, source, database, and collection do not "
                "construct one"
            ),
            default=None,
            materialize_default=False,
        ),
        "source": AttributeSpec(
            type="str",
            description=(
                "Source component. Refines an explicit scope only; it does not construct one "
                "when scope is omitted"
            ),
            default=None,
            materialize_default=False,
        ),
        "database": AttributeSpec(
            type="str",
            description=(
                "Database component; requires source. Refines an explicit scope only; it does not "
                "construct one when scope is omitted"
            ),
            default=None,
            materialize_default=False,
        ),
        "collection": AttributeSpec(
            type="str",
            description=(
                "Collection component; requires source and database. Refines an explicit scope "
                "only; it does not construct one when scope is omitted"
            ),
            default=None,
            materialize_default=False,
        ),
        "auto_construct_scope": AttributeSpec(
            type="bool",
            description=(
                "Rebuild an explicit scope from source, database, and collection when true; "
                "use that scope unchanged when false. Has no effect when scope is omitted"
            ),
            default=True,
        ),
        "filter_names": AttributeSpec(
            type="list",
            description="Filter out results with matching names in the filter list",
            default=[],
        ),
    }

    DEFAULT_PROPERTIES: ClassVar[dict[str, Any]] = {}

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        try:
            return self._execute(input_data, attributes, properties).output_data
        except _DataDiscoverFailure:
            return [[]]

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        search_query = cast(str, attributes.get("search_query", ""))
        approximate = attributes.get("approximate", True)
        hybrid = attributes.get("hybrid", False)
        limit = cast(int, attributes.get("limit", -1))
        page = cast(int, attributes.get("page", 0))
        page_size = cast(int, attributes.get("page_size", 10))
        include_metadata = cast(bool, attributes.get("include_metadata", False))
        if include_metadata:
            raise ValueError("include_metadata must be false for catalog discovery")
        threshold = cast(float, attributes.get("threshold", 0.5))
        progressive_pagination = attributes.get("progressive_pagination", False)
        concept_type = cast(str, attributes.get("concept_type", "source"))
        use_hierarchical_search = attributes.get("use_hierarchical_search", True)
        scope = cast("str | None", attributes.get("scope", None))
        source = cast("str | None", attributes.get("source", None))
        database = cast("str | None", attributes.get("database", None))
        collection = cast("str | None", attributes.get("collection", None))
        auto_construct_scope = cast(bool, attributes.get("auto_construct_scope", True))
        filter_names = cast("list[str]", attributes.get("filter_names", []))

        search_scope = _construct_scope(
            scope, source, database, collection, concept_type, auto_construct_scope
        )

        registry = resolve_registry(properties)
        if not registry:
            logger.error("Data discovery registry unavailable")
            raise _DataDiscoverFailure(RegistryReason.NOT_CONFIGURED)

        results: list[dict[str, Any]] = []

        try:
            use_simple_pagination = (not approximate and not hybrid) or not progressive_pagination

            if use_simple_pagination:
                if use_hierarchical_search:
                    search_results = registry.search_records_hierarchical(
                        search_query,
                        type=concept_type,
                        scope=search_scope,
                        page=page,
                        page_size=page_size,
                    )
                else:
                    search_results = registry.search_records(
                        search_query,
                        type=concept_type,
                        scope=search_scope,
                        approximate=cast(bool, approximate),
                        hybrid=cast(bool, hybrid),
                        page=page,
                        page_size=page_size,
                    )

                for result in search_results:
                    if result["name"] in filter_names:
                        continue

                    transformed_result = _transform_result(result, concept_type, registry)

                    if (approximate or hybrid) and "score" in result:
                        score = float(result["score"])
                        if score <= threshold:
                            results.append(transformed_result)
                    else:
                        results.append(transformed_result)
            else:
                current_page = page

                while True:
                    if use_hierarchical_search:
                        search_results = registry.search_records_hierarchical(
                            search_query,
                            type=concept_type,
                            scope=search_scope,
                            page=current_page,
                            page_size=page_size,
                        )
                    else:
                        search_results = registry.search_records(
                            search_query,
                            type=concept_type,
                            scope=search_scope,
                            approximate=cast(bool, approximate),
                            hybrid=cast(bool, hybrid),
                            page=current_page,
                            page_size=page_size,
                        )

                    if len(search_results) == 0:
                        break

                    for result in search_results:
                        if result["name"] in filter_names:
                            continue

                        score = float(result["score"])
                        if score <= threshold:
                            transformed_result = _transform_result(result, concept_type, registry)
                            results.append(transformed_result)
                        else:
                            break

                    if len(search_results) > 0:
                        last_score = float(search_results[-1]["score"])
                        if last_score > threshold:
                            break

                    current_page += 1

        except Exception as error:
            # Keep the raw apply() failure shape for existing callers.
            logger.error("Data discovery registry search failed")
            raise _DataDiscoverFailure(error) from None

        if limit >= 0:
            return FunctionResult([results[:limit]], {})
        else:
            return FunctionResult([results], {})

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        result = self._validate_input(input_data, attributes, properties)
        return type(result) is ValidationResult and result.ok is True

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        suggestion = "supply a valid search query, pagination, threshold, scope, and concept type"
        try:
            if not super().validate(input_data, attributes, properties):
                return ValidationResult(False, suggestion)
        except Exception:
            return ValidationResult(False, suggestion)

        search_query = cast(str, attributes.get("search_query", ""))
        page = cast(int, attributes.get("page", 0))
        page_size = cast(int, attributes.get("page_size", 10))
        threshold = cast(float, attributes.get("threshold", 0.5))
        source = attributes.get("source", None)
        database = attributes.get("database", None)
        collection = attributes.get("collection", None)

        if not search_query or not search_query.strip():
            return ValidationResult(False, suggestion)
        if page < 0 or page_size <= 0:
            return ValidationResult(False, suggestion)
        if threshold < 0 or threshold > 1:
            return ValidationResult(False, suggestion)

        if database and not source:
            return ValidationResult(False, suggestion)
        if collection and (not source or not database):
            return ValidationResult(False, suggestion)

        concept_type = attributes.get("concept_type", "source")
        valid_concept_types = [
            "source",
            "database",
            "collection",
            "entity",
            "relation",
            "attribute",
        ]
        if concept_type not in valid_concept_types:
            return ValidationResult(False, suggestion)

        if attributes.get("include_metadata", False):
            return ValidationResult(
                False, "include_metadata must be false; discovery returns catalog identifiers only"
            )

        return ValidationResult(True, None)

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        concept_type = attributes.get("concept_type", "source")
        use_hierarchical = attributes.get("use_hierarchical_search", True)
        search_method = "hierarchical" if use_hierarchical else "regular"

        scope = cast("str | None", attributes.get("scope", None))
        source = cast("str | None", attributes.get("source", None))
        database = cast("str | None", attributes.get("database", None))
        collection = cast("str | None", attributes.get("collection", None))
        auto_construct_scope = cast(bool, attributes.get("auto_construct_scope", True))
        search_scope = _construct_scope(
            scope, source, database, collection, cast(str, concept_type), auto_construct_scope
        )

        scope_info = f" within scope '{search_scope}'" if search_scope != "/" else ""

        return {
            "output": output,
            "input_data": input_data,
            "attributes": attributes,
            "explanation": (
                f"Data discover operator searched for {concept_type} entities using "
                f"{search_method} search with query '{attributes.get('search_query', '')}'"
                f"{scope_info} and returned "
                f"{len(output[0]) if output and len(output) > 0 else 0} results."
            ),
        }


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when data sources, databases, collections, or entities must be found through "
        "registry search."
    ),
    tags=(
        "domain-plan",
        "flow-head",
        "accepts-none",
        "produces-metadata",
        "capability-discovery",
        "capability-metadata-search",
        "requires-data-registry",
    ),
)
