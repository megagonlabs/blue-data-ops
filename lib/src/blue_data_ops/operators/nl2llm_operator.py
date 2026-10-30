from __future__ import annotations

from typing import Any, ClassVar, cast

from blue_data_ops.llm import prepare_llm_operator_properties, resolve_llm_client
from blue_data_ops.llm.client import validate_llm_caller_controls
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

_PROMPT = """
You are an intelligent system that converts a natural language query into a structured JSON output.

### General Requirements:
- Always output a **valid JSON array** of objects.
- Each element must be a well-formed JSON object with key–value pairs.
- Do **not** include explanations, comments, or additional text outside of the JSON.
- Strive to return non-empty output. If the query is vague, use best judgement to produce a meaningful result.

### Attributes:
- If output attributes are specified, every object must include them.
- If types are specified, ensure values match those types exactly (e.g., string, int, float, boolean, date, list, dict, etc.).
- If types are **not** specified, infer them reasonably from the query and context.
- If no attributes are provided, return the most relevant structured JSON representation of the query.

### Context:
- Use the provided context if it exists and is non-empty.

### Output Formatting:
- Return only the JSON array.
- No prose, explanations, or formatting (such as Markdown fences).
- Ensure strict JSON compliance (no trailing commas, keys quoted, etc.).

---

Query: ${query}

Attributes:
${attrs}

Context:
${context}

Output:
"""


class NL2LLMOperator(Operator):
    """Convert a natural language query into structured JSON through an LLM."""

    # A blank query returns [] without a provider call, and LLM errors propagate. The
    # output pipeline removes Markdown fences and every literal lowercase "json"
    # substring before JSON conversion. Transport-only service_url is ignored.

    name: ClassVar[str] = "nl2llm"
    description: ClassVar[str] = (
        "Processes natural language query using LLM models and returns structured data"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "query": AttributeSpec(
            type="str", description="Natural language query to process", required=True
        ),
        "context": AttributeSpec(
            type="str", description="Optional context to provide domain knowledge", default=""
        ),
        "attrs": AttributeSpec(
            type="list[dict]",
            description="List of attribute specifications (dicts with name and optional type)",
            default=[],
        ),
    }

    DEFAULT_PROPERTIES: ClassVar[dict[str, Any]] = {
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-6-luna",
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
            {
                "transformation": "sub",
                "from": r"(?is)\A```(?:json)?[ \t]*\r?\n(.*)\r?\n```\Z",
                "to": r"\1",
            },
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
        return self._execute(input_data, attributes, properties).output_data

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        validate_llm_caller_controls(
            properties, service_prefix=str(self.DEFAULT_PROPERTIES.get("service_prefix", "openai"))
        )
        query = cast(str, attributes.get("query", ""))
        context = attributes.get("context", "")
        attrs = cast("list[dict[str, Any]]", attributes.get("attrs", []))

        if not query or not query.strip():
            return FunctionResult([], {})

        attrs_formatted = ""
        if attrs:
            attrs_formatted = "Required output attributes:\n"
            for attr in attrs:
                if "type" in attr:
                    attrs_formatted += f"- {attr['name']}: {attr['type']}\n"
                else:
                    attrs_formatted += f"- {attr['name']}: (type will be inferred)\n"

        # Caller properties take precedence over operator defaults.
        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
        merged = prepare_llm_operator_properties(merged, self.DEFAULT_PROPERTIES, properties)
        client = resolve_llm_client(merged)
        additional_data = {"query": query, "context": context, "attrs": attrs_formatted}

        return FunctionResult(
            [client.execute_api_call({}, properties=merged, additional_data=additional_data)],
            {},
        )

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
        reason = "supply valid natural-language query attributes"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, reason)

        if "attrs" in attributes and attributes["attrs"]:
            for attr in cast("list[Any]", attributes["attrs"]):
                if not isinstance(attr, dict) or "name" not in attr:
                    return ValidationResult(False, reason)
        return ValidationResult(True, None)

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
        "Use when a natural-language request should be sent to the configured reasoning "
        "provider and returned as structured data."
    ),
    tags=(
        "domain-query-compound",
        "flow-head",
        "accepts-none",
        "produces-data",
        "capability-generation",
        "requires-llm",
    ),
)
