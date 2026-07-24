from __future__ import annotations

import json
import logging
from typing import Any, ClassVar, cast

from blue_data_ops.data import RegistrySeam, resolve_registry
from blue_data_ops.llm import resolve_llm_client
from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators._query_results import format_execution_result
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


class _MissingRegistryError(RuntimeError):
    pass


_PROMPT = """
You are an assistant that maps natural language questions into probabilistic query components for a Bayesian Network.

A Bayesian Network consists of:

- **Nodes** (random variables) - each node represents a variable in the domain

- **States** (possible values each node can take) - the discrete values each variable can assume

- **Directed edges** indicating conditional dependencies between variables

This network encodes a joint probability distribution P(X₁, X₂, ..., Xₙ).  

Each edge A → B means that the conditional probability P(B | A) is directly represented in the network.

--- 

${schema_section}

---

Given the following question, extract:

1. The **target node** being queried (i.e., the variable we want the probability for)

2. The **target state** or value of that variable (must be one of the valid states for that node)

3. Any **observed context** or evidence described in the question (as a dictionary mapping node names to their observed states)

---

Question: ${question}

---

Respond ONLY with a JSON object in the exact format below. Use the original node names and state values exactly as defined above:

{
  "target_node": "node_name",
  "target_state": "state_value",
  "context": {
    "node1": "state1",
    "node2": "state2"
  }
}

Important:
- Use exact node names and state values as shown in the schema information above
- The target_state must be a valid state for the target_node
- All context node states must be valid states for their respective nodes
- If no context is provided in the question, use an empty dictionary {} for context
"""

_CORRECTION_PROMPT = """
You previously generated a Bayesian Network query, but it has validation errors. Please correct the query based on the errors and the BN structure.

**Original Question:**
${question}

**Original Query:**
${original_query}

**Validation Errors:**
${validation_errors}

${schema_section}

---

Please correct the query to fix all validation errors. Respond ONLY with a JSON object in the exact format:

{
  "target_node": "node_name",
  "target_state": "state_value",
  "context": {
    "node1": "state1",
    "node2": "state2"
  }
}

Important:
- Use exact node names and state values from the schema information above
- Ensure all nodes exist in the BN
- Ensure all states are valid for their respective nodes
"""


def _extract_nodes_info(graph_structure: dict[str, Any]) -> str:
    """Extract nodes and their states from graph_structure."""
    nodes = graph_structure.get("nodes", {})

    nodes_list: list[str] = []
    for node_name, node_info in nodes.items():
        if isinstance(node_info, dict):
            states = cast("dict[str, Any]", node_info).get("states", [])
            states_str = ", ".join(states) if states else "N/A"
            nodes_list.append(f"- {node_name}: [{states_str}]")

    return "\n".join(nodes_list) if nodes_list else "No nodes found"


def _extract_edges_info(graph_structure: dict[str, Any]) -> str:
    """Extract edges (parent -> child) from graph_structure."""
    edges = graph_structure.get("edges", {})

    edges_list: list[str] = []
    for parent, children in edges.items():
        if isinstance(children, list):
            for child in cast("list[Any]", children):
                edges_list.append(f"- {parent} → {child}")
        elif isinstance(children, dict):
            for child in cast("dict[str, Any]", children).keys():
                edges_list.append(f"- {parent} → {child}")

    return "\n".join(edges_list) if edges_list else "No edges found"


def _extract_node_descriptions(graph_structure: dict[str, Any]) -> str:
    """Extract collection and node descriptions (with state descriptions)."""
    descriptions: list[str] = []

    collection_desc = graph_structure.get("description", "")
    if collection_desc:
        descriptions.append(f"Collection: {collection_desc}")

    nodes = graph_structure.get("nodes", {})

    node_descriptions: list[str] = []
    for node_name, node_info in nodes.items():
        if isinstance(node_info, dict):
            info = cast("dict[str, Any]", node_info)
            node_desc = info.get("description", "")
            states_desc = info.get("states_description", {})

            if node_desc:
                desc_line = f"- {node_name}: {node_desc}"
                if states_desc:
                    state_lines: list[str] = []
                    for state, state_desc in states_desc.items():
                        if state_desc:  # Only add non-empty state descriptions
                            state_lines.append(f"  - {state}: {state_desc}")
                    if state_lines:
                        desc_line += "\n" + "\n".join(state_lines)
                node_descriptions.append(desc_line)

    if node_descriptions:
        descriptions.append("Node descriptions:")
        descriptions.extend(node_descriptions)

    return "\n".join(descriptions) if descriptions else "No descriptions available"


def _validate_bn_query(bn_query_data: dict[str, Any], graph_structure: dict[str, Any]) -> list[str]:
    """Validate a BN query against graph_structure; return error messages (empty if valid)."""
    errors: list[str] = []
    nodes = graph_structure.get("nodes", {})

    target_node = bn_query_data.get("target_node")
    if not target_node:
        errors.append("Missing target_node")
    elif target_node not in nodes:
        errors.append(f"Target node '{target_node}' not found in BN.")
    else:
        target_state = bn_query_data.get("target_state")
        if not target_state:
            errors.append("Missing target_state")
        else:
            node_info = nodes[target_node]
            node_states = node_info.get("states", [])
            if target_state not in node_states:
                errors.append(
                    f"Target state '{target_state}' not valid for node '{target_node}'. "
                    f"Valid states: {node_states}"
                )

    context = bn_query_data.get("context", {})
    if context:
        for ctx_node, ctx_state in context.items():
            if ctx_node not in nodes:
                errors.append(f"Context node '{ctx_node}' not found in BN.")
            else:
                node_info = nodes[ctx_node]
                node_states = node_info.get("states", [])
                if ctx_state not in node_states:
                    errors.append(
                        f"Context state '{ctx_state}' not valid for node '{ctx_node}'. "
                        f"Valid states: {node_states}"
                    )

    return errors


def _resolve_schema_section(
    provided_schema: Any,
    registry: RegistrySeam,
    source: str,
    database: str,
    collection: str,
) -> tuple[str, dict[str, Any] | None]:
    """Build the prompt's schema section; return (schema_info, graph_structure or None).

    A non-None graph_structure means the schema is structured (has nodes and edges)
    and generated queries are validated against it. Mirrors the upstream unified
    schema/graph_structure handling exactly, including the metadata-key fallback for
    registries that report graph_structure at the schema's top level.
    """
    schema_dict: Any = None
    graph_structure: Any = None
    metadata: Any = None
    is_structured = False
    schema_info: str | None = None

    if not provided_schema:
        # Fetch from the registry; the "bn" protocol argument requests metadata with
        # graph_structure where the registry supports it.
        schema_dict = registry.get_data_source_schema(
            source, database, collection, "bn", format="dict"
        )
        empty: dict[str, Any] = {}
        # Metadata may sit under schema['metadata'], or the schema itself may carry
        # the metadata fields at the top level (registry version difference).
        if schema_dict and "metadata" in schema_dict:
            metadata = schema_dict.get("metadata", empty)
            graph_structure = metadata.get("graph_structure", empty) if metadata else empty
        else:
            metadata = schema_dict if schema_dict else empty
            graph_structure = (
                cast("dict[str, Any]", metadata).get("graph_structure", empty)
                if isinstance(metadata, dict)
                else empty
            )
        is_structured = bool(
            graph_structure and "nodes" in graph_structure and "edges" in graph_structure
        )
    else:
        if isinstance(provided_schema, str):
            try:
                parsed_schema = json.loads(provided_schema)
            except json.JSONDecodeError:
                schema_info = provided_schema
                is_structured = False
            else:
                if (
                    isinstance(parsed_schema, dict)
                    and "nodes" in parsed_schema
                    and "edges" in parsed_schema
                ):
                    graph_structure = cast("dict[str, Any]", parsed_schema)
                    is_structured = True
                else:
                    schema_info = (
                        json.dumps(parsed_schema, indent=2)
                        if isinstance(parsed_schema, dict)
                        else provided_schema
                    )
                    is_structured = False
        else:
            if (
                isinstance(provided_schema, dict)
                and "nodes" in provided_schema
                and "edges" in provided_schema
            ):
                graph_structure = cast("dict[str, Any]", provided_schema)
                is_structured = True
            else:
                schema_info = json.dumps(provided_schema, indent=2)
                is_structured = False

    if is_structured:
        schema_info = f"""**Nodes and their states:**

{_extract_nodes_info(graph_structure)}

**Edges** (parent → child relationships):

{_extract_edges_info(graph_structure)}

**Node descriptions:**

{_extract_node_descriptions(graph_structure)}"""
    else:
        if not schema_info:
            schema_info = json.dumps(schema_dict, indent=2) if schema_dict else ""
        schema_info = f"""**Bayesian Network Schema:**

{schema_info}"""

    return schema_info, cast("dict[str, Any]", graph_structure) if is_structured else None


class NL2BNOperator(Operator):
    """Translate a natural language question into a Bayesian Network query and run it."""

    # Faithful to Blue source's nl2bn operator: a blank question returns [[]] with no
    # provider call; source/database/collection/protocol_variant are required; a
    # missing registry returns [[]]. Failures of the INITIAL LLM CALL become
    # validation errors routed into the correction loop — upstream catches its
    # platform error type there, and its error-wrapping layer converts every
    # exception leaving the client into that type,
    # so the adapter-equivalent catch scope is Exception AROUND THE CALL ONLY: the
    # operator's own response parse is outside it, where (as upstream) only
    # JSONDecodeError converts and any other parse failure propagates. Failures of
    # a CORRECTION call propagate (upstream leaves that call uncaught). Exhausted
    # corrections raise ValueError.

    name: ClassVar[str] = "nl2bn"
    description: ClassVar[str] = (
        "Translates natural language questions into Bayesian Network queries using LLM models"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "question": AttributeSpec(
            type="str",
            description="Natural language question to translate to BN query",
            required=True,
        ),
        "source": AttributeSpec(
            type="str", description="BN data source name", required=True, default=""
        ),
        "database": AttributeSpec(
            type="str", description="Database name", required=True, default=""
        ),
        "collection": AttributeSpec(
            type="str", description="Collection/model name", required=True, default=""
        ),
        "protocol_variant": AttributeSpec(
            type="str",
            description="Protocol variant (e.g., 'pgmpy')",
            required=True,
            default="pgmpy",
        ),
        "context": AttributeSpec(
            type="str", description="Optional context for domain knowledge", default=""
        ),
        "schema": AttributeSpec(
            type="str",
            description=(
                "JSON string of BN schema (optional - will be fetched automatically "
                "if not provided)"
            ),
            default="",
        ),
        "explanation": AttributeSpec(
            type="bool",
            description="Return natural language explanation for the answer",
            default=True,
        ),
        "structured_explanation": AttributeSpec(
            type="bool",
            description="Return structured explanation (only effective when explanation is True)",
            default=False,
        ),
        "max_corrections": AttributeSpec(
            type="int",
            description="Maximum number of correction attempts for query validation",
            default=2,
        ),
        "max_num_paths": AttributeSpec(
            type="int",
            description="Maximum number of reasoning paths to include in explanation (default: 50)",
            default=50,
        ),
    }

    DEFAULT_PROPERTIES: ClassVar[dict[str, Any]] = {
        # Declared upstream but never read by this operator's function; kept for
        # property-surface parity.
        "execute_query": True,
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-4o",
        "openai.stream": False,
        "openai.max_tokens": 4096,
        "openai.temperature": 0,
        "input_json": '[{"role": "user"}]',
        "input_context": "$[0]",
        "input_context_field": "content",
        "input_field": "messages",
        "input_template": _PROMPT,
        "output_path": "$.choices[0].message.content",
        "service_prefix": "openai",
        "output_transformations": [
            {"transformation": "replace", "from": "```", "to": ""},
            {"transformation": "replace", "from": "json", "to": ""},
        ],
        "output_strip": True,
        "output_cast": "json",
    }

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        try:
            return self._execute(input_data, attributes, properties).output_data
        except _MissingRegistryError:
            return [[]]

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        question = cast(str, attributes.get("question", ""))
        source = cast(str, attributes.get("source", ""))
        database = cast(str, attributes.get("database", "default"))
        collection = cast(str, attributes.get("collection", ""))
        protocol_variant = cast(str, attributes.get("protocol_variant", "pgmpy"))
        context = attributes.get("context", "")
        provided_schema = attributes.get("schema", "")
        explanation = attributes.get("explanation", True)
        structured_explanation = attributes.get("structured_explanation", False)
        max_corrections = cast(int, attributes.get("max_corrections", 2))
        max_num_paths = attributes.get("max_num_paths", 50)

        if not question or not question.strip():
            return FunctionResult([[]], {})

        if not source or not database or not collection or not protocol_variant:
            raise ValueError("Source, database, collection, and protocol_variant are required")

        if protocol_variant not in ["pgmpy"]:
            raise ValueError(
                f"Unsupported protocol_variant: {protocol_variant}. Supported variants: ['pgmpy']"
            )

        registry = resolve_registry(properties)
        if not registry:
            raise _MissingRegistryError

        schema_info, graph_structure = _resolve_schema_section(
            provided_schema, registry, source, database, collection
        )
        is_structured = graph_structure is not None

        # Caller properties override the operator defaults (Blue source merges the same
        # values through its instance properties; same observable, different shell).
        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
        client = resolve_llm_client(merged)

        additional_data = {
            "question": question,
            "context": context,
            "schema_section": schema_info,
        }

        bn_query_data: dict[str, Any] = {}
        validation_errors: list[str] = []

        try:
            bn_query_result = client.execute_api_call(
                {}, properties=merged, additional_data=additional_data
            )
        except Exception as e:
            # The Exception-wide scope is the upstream equivalent for failures leaving
            # the CLIENT CALL ONLY (see the class note); the local parse below sits
            # outside it so that, as upstream, only JSONDecodeError converts there and
            # any other local parse failure propagates.
            validation_errors.append(f"Service error: {str(e)}")
            bn_query_data = {}
        else:
            if isinstance(bn_query_result, str):
                try:
                    bn_query_data = json.loads(bn_query_result)
                except json.JSONDecodeError as e:
                    validation_errors.append(f"Invalid JSON response from LLM: {str(e)}")
                    bn_query_data = {}
            elif isinstance(bn_query_result, dict):
                bn_query_data = cast("dict[str, Any]", bn_query_result)
            else:
                validation_errors.append(
                    f"Invalid response type from LLM: {type(bn_query_result).__name__}"
                )
                bn_query_data = {}

        if not validation_errors:
            if "target_node" not in bn_query_data:
                validation_errors.append("No target_node found in LLM response")
            if "target_state" not in bn_query_data:
                validation_errors.append("No target_state found in LLM response")
            if "context" not in bn_query_data:
                bn_query_data["context"] = {}

        if is_structured and not validation_errors:
            assert graph_structure is not None
            validation_errors.extend(_validate_bn_query(bn_query_data, graph_structure))
        correction_attempts = 0

        while validation_errors and correction_attempts < max_corrections:
            logger.info(
                f"Query validation found errors (attempt {correction_attempts + 1}): "
                f"{validation_errors}"
            )

            correction_data = {
                "question": question,
                "original_query": json.dumps(bn_query_data, indent=2),
                "validation_errors": json.dumps(validation_errors, indent=2),
                "schema_section": schema_info,
            }

            # Upstream deep-copies the properties before swapping the prompt; the only
            # write is the top-level input_template, so a copy-with-override is the
            # same observable without deep-copying live adapter objects (e.g. an
            # injected client).
            correction_properties = {**merged, "input_template": _CORRECTION_PROMPT}

            correction_result = client.execute_api_call(
                {}, properties=correction_properties, additional_data=correction_data
            )

            if isinstance(correction_result, str):
                try:
                    bn_query_data = json.loads(correction_result)
                    validation_errors = []
                except json.JSONDecodeError as e:
                    validation_errors = [f"Invalid JSON in corrected query: {str(e)}"]
                    break
            elif isinstance(correction_result, dict):
                bn_query_data = cast("dict[str, Any]", correction_result)
                validation_errors = []
            else:
                validation_errors = [
                    f"Invalid correction response type: {type(correction_result).__name__}"
                ]
                break

            if not validation_errors:
                if "target_node" not in bn_query_data:
                    validation_errors.append("No target_node found in corrected query")
                if "target_state" not in bn_query_data:
                    validation_errors.append("No target_state found in corrected query")
                if "context" not in bn_query_data:
                    bn_query_data["context"] = {}

            if is_structured and not validation_errors:
                assert graph_structure is not None
                validation_errors.extend(_validate_bn_query(bn_query_data, graph_structure))
            correction_attempts += 1

        if validation_errors:
            error_message = (
                f"Query validation failed after {max_corrections} correction attempts. "
                f"Errors: {', '.join(validation_errors)}"
            )
            logger.error(error_message)
            raise ValueError(error_message)

        query_json = json.dumps(bn_query_data)
        logger.info("Generated BN Query: " + query_json)

        optional_properties: dict[str, Any] = {}
        if explanation:
            optional_properties["explanation"] = True
            optional_properties["structured_explanation"] = structured_explanation
            optional_properties["max_num_paths"] = max_num_paths

        result = registry.execute_query(
            query_json, source, database, collection, optional_properties=optional_properties
        )
        logger.debug("Result: ")
        logger.debug(result)

        formatted_result = format_execution_result(result)

        prob = None
        explanation_text = None
        if formatted_result and len(formatted_result) > 0 and len(formatted_result[0]) > 0:
            first_result = formatted_result[0][0]
            prob = first_result.get("probability", first_result.get("prob"))
            if explanation:
                explanation_text = first_result.get("explanation", "")

        output: dict[str, Any] = {"prob": prob, "query": bn_query_data}

        if explanation and explanation_text:
            output["explanation"] = explanation_text

        return FunctionResult([[output]], {})

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        valid = super().validate(input_data, attributes, properties)
        return ValidationResult(
            valid,
            None if valid else "supply valid Bayesian-network query attributes",
        )

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        return {
            "output": output,
            "attributes": attributes,
        }


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when a natural-language question must be translated into a Bayesian-network query."
    ),
    tags=(
        "domain-query-compound",
        "flow-head",
        "accepts-none",
        "produces-data",
        "capability-bayesian-query",
        "capability-query-execution",
        "capability-query-generation",
        "requires-data-registry",
        "requires-llm",
        "requires-query-backend",
    ),
)
