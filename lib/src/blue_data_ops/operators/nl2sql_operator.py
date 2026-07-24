from __future__ import annotations

import json
import logging
from typing import Any, ClassVar, cast

from blue_data_ops.data import resolve_registry
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
Your task is to translate a natural language question into a SQL query based on the provided database schema.

## Here are the requirements:
- The output should be a JSON object with the following fields:
  - "question": the original natural language question
  - "query": the SQL query that is translated from the natural language question
- The SQL query should be compatible with the provided schema.
- The SQL query should be compatible with the syntax of the corresponding database's protocol.
- For enum fields, do not use LOWER(), ILIKE, or other string functions. Compare enum fields using exact equality.
- Always do case-${sensitivity} matching for string comparison.
- The query should start with any of the following prefixes: ${force_query_prefixes}
- When interpreting the "question" use additional context provided, if available.
- Output the JSON directly. Do not generate explanation or other additional output.
${additional_requirements}

## Database Protocol: 
```
${protocol}
```

##Database Schema:
```
${schema}
```

## Context: ${context}

## Question: ${question}

${attr_names_section}

---
## Output (JSON only):
"""


class NL2SQLOperator(Operator):
    """Translate a natural language question into a SQL query and optionally run it."""

    # Faithful to Blue source's nl2sql operator: a blank question returns [[]] with no
    # provider call; protocol/database/collection are required while `source` is NOT
    # part of that check (upstream quirk, kept); a missing registry returns [[]];
    # the schema is ALWAYS fetched from the registry — the declared `schema`
    # attribute is accepted but never used (upstream reads it and immediately
    # overwrites it); LLM errors PROPAGATE. Upstream's module also carries
    # direct-connection schema helpers explicitly marked not for production — those
    # (and their database-driver imports) are dropped; schema access goes through
    # the registry.

    name: ClassVar[str] = "nl2sql"
    description: ClassVar[str] = (
        "Translates natural language questions into SQL queries using LLM models"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "source": AttributeSpec(
            type="str", description="Data source name", required=True, default=""
        ),
        "question": AttributeSpec(
            type="str",
            description="Natural language question to translate to SQL",
            required=True,
        ),
        "protocol": AttributeSpec(
            type="str",
            description="Database protocol (postgres, mysql, sqlite)",
            required=True,
            default="postgres",
        ),
        "database": AttributeSpec(
            type="str", description="Database name", required=True, default=""
        ),
        "collection": AttributeSpec(
            type="str", description="Collection/schema name", required=True, default=""
        ),
        "case_insensitive": AttributeSpec(
            type="bool", description="Case insensitive string matching", default=True
        ),
        "additional_requirements": AttributeSpec(
            type="str", description="Additional requirements for SQL generation", default=""
        ),
        "context": AttributeSpec(
            type="str", description="Optional context for domain knowledge", default=""
        ),
        "schema": AttributeSpec(
            type="str",
            description=(
                "JSON string of database schema (optional - will be fetched automatically "
                "if not provided)"
            ),
            default="",
        ),
        "attr_names": AttributeSpec(
            type="list[str]",
            description="Optional list of target field names for the output objects",
            default=[],
        ),
    }

    DEFAULT_PROPERTIES: ClassVar[dict[str, Any]] = {
        "execute_query": True,
        "validate_query_prefixes": ["SELECT"],
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-4o",
        "openai.stream": False,
        "openai.max_tokens": 512,
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
        protocol = cast(str, attributes.get("protocol", "postgres"))
        database = cast(str, attributes.get("database", ""))
        collection = cast(str, attributes.get("collection", ""))
        # Read even though undeclared in the attribute schema — upstream does the
        # same (it reaches the prompt as a template value, not through validation).
        force_query_prefixes = attributes.get("force_query_prefixes", "SELECT")
        case_insensitive = attributes.get("case_insensitive", True)
        additional_requirements = attributes.get("additional_requirements", "")
        context = attributes.get("context", "")
        attr_names = cast("list[str]", attributes.get("attr_names", []))

        if not question or not question.strip():
            return FunctionResult([[]], {})

        if not protocol or not database or not collection:
            raise ValueError("Protocol, database, and collection are required")

        registry = resolve_registry(properties)
        if not registry:
            raise _MissingRegistryError

        # get schema from data registry (unconditionally — the schema attribute is
        # accepted but not consulted, matching upstream)
        schema = registry.get_data_source_schema(source, database, collection)
        logger.debug("SCHEMA:")
        logger.debug(schema)
        if isinstance(schema, dict):
            schema_str = json.dumps(schema, indent=2)
        else:
            schema_str = str(schema)

        # Caller properties override the operator defaults (Blue source merges the same
        # values through its instance properties; same observable, different shell).
        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
        execute_query = merged.get("execute_query", True)
        validate_query_prefixes = cast(
            "list[str]", merged.get("validate_query_prefixes", ["SELECT"])
        )
        if protocol not in ["postgres", "mysql", "sqlite"]:
            raise ValueError(
                f"Unsupported protocol: {protocol}. "
                f"Supported protocols are: postgres, mysql, sqlite"
            )

        client = resolve_llm_client(merged)

        attr_names_section = ""
        if attr_names and len(attr_names) > 0:
            attr_names_list = ", ".join(attr_names)
            attr_names_section = (
                "## Target Field Names (SELECT AS):\n"
                "Please use the following field names as column aliases if it's not same "
                "with the column names. Use 'AS' keyword if needed to alias columns:\n"
                f"{attr_names_list}\n"
            )

        additional_data = {
            "question": question,
            "schema": schema_str,
            "protocol": protocol,
            "sensitivity": "insensitive" if case_insensitive else "sensitive",
            "force_query_prefixes": force_query_prefixes,
            "additional_requirements": additional_requirements,
            "context": context,
            "attr_names_section": attr_names_section,
        }
        sql_result = client.execute_api_call({}, properties=merged, additional_data=additional_data)

        if isinstance(sql_result, str):
            try:
                sql_data = json.loads(sql_result)
            except json.JSONDecodeError as e:
                # implicit exception context only, as upstream raises it
                raise ValueError(f"Invalid JSON response from LLM: {str(e)}")
        elif isinstance(sql_result, dict):
            sql_data = cast("dict[str, Any]", sql_result)
        else:
            raise ValueError("Invalid response from LLM: " + str(sql_result))

        generated_query = cast(str, sql_data.get("query", ""))
        if not generated_query:
            raise ValueError("No query found in LLM response")

        if not any(
            generated_query.upper().startswith(prefix.upper()) for prefix in validate_query_prefixes
        ):
            raise ValueError(f"Invalid query prefix: {generated_query}")

        if execute_query and generated_query:
            logger.info("Generated Query: " + generated_query)
            result = registry.execute_query(generated_query, source, database, collection)
            logger.debug("Result: ")
            logger.debug(result)
            # The formatter's case-4 fallthrough can yield None at runtime (an upstream
            # quirk, kept and pinned); the cast keeps the declared operator contract.
            return FunctionResult(cast(DataBundle, format_execution_result(result)), {})
        return FunctionResult([[{"sql": generated_query}]], {})

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        valid = super().validate(input_data, attributes, properties)
        return ValidationResult(
            valid,
            None if valid else "supply valid natural-language SQL attributes",
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
        "Use when a natural-language question must be translated into SQL, with optional execution."
    ),
    tags=(
        "domain-query-compound",
        "flow-head",
        "accepts-none",
        "produces-data",
        "produces-query",
        "capability-query-execution",
        "capability-query-generation",
        "capability-sql",
        "requires-data-registry",
        "requires-llm",
        "requires-query-backend",
    ),
)
