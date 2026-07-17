from __future__ import annotations

import logging
import traceback
from typing import Any, ClassVar, cast

from blue_data_ops.data import RegistrySeam, resolve_registry
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import Attributes, AttributeSpec, DataBundle, Properties

logger = logging.getLogger(__name__)


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
        # Upstream returns None outright here — source/database/collection do NOT
        # produce a scope unless an explicit scope string is provided (its own TODO
        # notes the ambiguity). Kept as-is.
        return None

    # If auto_construct is False, return the scope as-is
    if not auto_construct:
        return scope.rstrip("/") if scope else "/"

    # If explicit scope is provided and not default, use it as base
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

    # Parse the base scope to extract components
    scope_parts = base_scope.split("/")
    scope_components: dict[str, str | None] = {
        "source": None,
        "database": None,
        "collection": None,
        "entity": None,
        "relation": None,
        "attribute": None,
    }

    # Extract components from scope path
    for i, part in enumerate(scope_parts):
        if part in scope_components and i + 1 < len(scope_parts):
            scope_components[part] = scope_parts[i + 1]

    if source:
        scope_components["source"] = source
    if database:
        scope_components["database"] = database
    if collection:
        scope_components["collection"] = collection

    # Construct the appropriate scope based on concept_type
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
        # Fallback to base scope for unknown concept types
        return base_scope


def _transform_result(
    result: dict[str, Any],
    concept_type: str,
    registry: RegistrySeam,
    include_metadata: bool,
) -> dict[str, Any]:
    """Transform a search result into the expected format."""
    transformed_result: dict[str, Any] = {
        "type": concept_type,
        "name": result["name"],
        "id": result["id"],
        "scope": result["scope"],
    }
    if "score" in result:
        transformed_result["score"] = float(result["score"])

    full_record = registry.get_record(result["name"], concept_type, result["scope"])
    if full_record:
        transformed_result["description"] = full_record.get("description", "")
        transformed_result["properties"] = full_record.get("properties", {})
        if include_metadata:
            transformed_result["metadata"] = full_record.get("metadata", {})
    else:
        transformed_result["description"] = ""
        transformed_result["properties"] = {}

    return transformed_result


class DataDiscoverOperator(Operator):
    """Discover registry records through hierarchical or regular search."""

    # Faithful to blue-dev's data_discover operator: any search failure is logged
    # and swallowed to [[]] (by upstream design); scope=None (the default) is passed
    # through as None regardless of source/database/collection; the threshold keeps
    # score <= threshold (lower = better); progressive pagination walks pages until
    # a score exceeds the threshold. The explainer reports "within scope 'None'"
    # for the default scope — upstream-identical.

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
            description=(
                "Whether to include metadata in results (description and properties "
                "always included)"
            ),
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
            type="str", description="Search scope to limit results", default=None
        ),
        "source": AttributeSpec(
            type="str", description="Source name to limit search scope", default=None
        ),
        "database": AttributeSpec(
            type="str",
            description="Database name to limit search scope (requires source)",
            default=None,
        ),
        "collection": AttributeSpec(
            type="str",
            description="Collection name to limit search scope (requires source and database)",
            default=None,
        ),
        "auto_construct_scope": AttributeSpec(
            type="bool",
            description=(
                "Whether to auto-construct scope from individual attributes or use scope as-is"
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
        # Extract attributes
        search_query = cast(str, attributes.get("search_query", ""))
        approximate = attributes.get("approximate", True)
        hybrid = attributes.get("hybrid", False)
        limit = cast(int, attributes.get("limit", -1))
        page = cast(int, attributes.get("page", 0))
        page_size = cast(int, attributes.get("page_size", 10))
        include_metadata = cast(bool, attributes.get("include_metadata", False))
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
            logger.error("Error: Data registry not found")
            return [[]]

        results: list[dict[str, Any]] = []

        try:
            # Determine if we should use simple pagination
            use_simple_pagination = (not approximate and not hybrid) or not progressive_pagination

            if use_simple_pagination:
                # Simple pagination - single call
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
                    # filter names
                    if result["name"] in filter_names:
                        continue

                    transformed_result = _transform_result(
                        result, concept_type, registry, include_metadata
                    )

                    # Apply threshold filtering for approximate/hybrid search even in
                    # simple pagination mode
                    if (approximate or hybrid) and "score" in result:
                        score = float(result["score"])
                        if score <= threshold:
                            results.append(transformed_result)
                    else:
                        results.append(transformed_result)
            else:
                # Progressive pagination - loop until threshold exceeded
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
                        # filter names
                        if result["name"] in filter_names:
                            continue

                        # Check threshold for approximate/hybrid search
                        score = float(result["score"])
                        if score <= threshold:
                            transformed_result = _transform_result(
                                result, concept_type, registry, include_metadata
                            )
                            results.append(transformed_result)
                        else:
                            # Score exceeds threshold, stop searching
                            break

                    # Check if last result exceeded threshold to break outer loop
                    if len(search_results) > 0:
                        last_score = float(search_results[-1]["score"])
                        if last_score > threshold:
                            break

                    # Move to next page
                    current_page += 1

        except Exception:
            # Upstream design: any search failure is logged and swallowed to [[]].
            logger.error(traceback.format_exc())
            return [[]]

        # limit results
        if limit >= 0:
            return [results[:limit]]
        else:
            return [results]

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        # Upstream wraps its base-validator call defensively; kept, though the base
        # gate is total.
        try:
            if not super().validate(input_data, attributes, properties):
                return False
        except Exception:
            return False

        search_query = cast(str, attributes.get("search_query", ""))
        page = cast(int, attributes.get("page", 0))
        page_size = cast(int, attributes.get("page_size", 10))
        threshold = cast(float, attributes.get("threshold", 0.5))
        source = attributes.get("source", None)
        database = attributes.get("database", None)
        collection = attributes.get("collection", None)

        if not search_query or not search_query.strip():
            return False
        if page < 0 or page_size <= 0:
            return False
        if threshold < 0 or threshold > 1:
            return False

        if database and not source:
            return False
        if collection and (not source or not database):
            return False

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
            return False

        return True

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        concept_type = attributes.get("concept_type", "source")
        use_hierarchical = attributes.get("use_hierarchical_search", True)
        search_method = "hierarchical" if use_hierarchical else "regular"

        # Get scope information
        scope = cast("str | None", attributes.get("scope", None))
        source = cast("str | None", attributes.get("source", None))
        database = cast("str | None", attributes.get("database", None))
        collection = cast("str | None", attributes.get("collection", None))
        auto_construct_scope = cast(bool, attributes.get("auto_construct_scope", True))
        search_scope = _construct_scope(
            scope, source, database, collection, cast(str, concept_type), auto_construct_scope
        )

        # Upstream compares against "/" only, so the default None scope renders as
        # "within scope 'None'" — kept.
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
