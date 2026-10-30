from __future__ import annotations

import json
import logging
import re
from types import MethodType
from typing import Any, ClassVar, cast

from blue_data_ops.data import resolve_registry
from blue_data_ops.data.errors import RegistryNotConfigured
from blue_data_ops.data.registry_seam import (
    _diagnose_source,  # pyright: ignore[reportPrivateUsage]
    diagnose_generation_target,
)
from blue_data_ops.llm import prepare_llm_operator_properties, resolve_llm_client
from blue_data_ops.llm.client import validate_llm_caller_controls
from blue_data_ops.llm.sql_execution import SQL_REGISTRY_SELECTORS, ReadOnlySQLExecutor, sql_error
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


class _MissingRegistryError(RegistryNotConfigured):
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

    # Raw blank questions and missing generation registries keep their empty return.
    # Schema comes from the selected registry or host capability; the compatibility
    # schema attribute does not replace it.

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
        "execute_query": False,
        "validate_query_prefixes": ["SELECT"],
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-6-luna",
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
            {
                "transformation": "sub",
                "from": r"(?is)\A```(?:json)?[ \t]*\r?\n(.*)\r?\n```\Z",
                "to": r"\1",
            },
        ],
        "output_strip": True,
        "output_cast": "json",
    }

    def __init__(
        self, *args: Any, read_only_executor: ReadOnlySQLExecutor | None = None, **kwargs: Any
    ) -> None:
        if read_only_executor is not None and type(read_only_executor) is not ReadOnlySQLExecutor:
            raise sql_error("sql_policy_invalid")
        self._read_only_executor = read_only_executor
        super().__init__(*args, **kwargs)

    def _preflight_execution(self, attributes: Attributes, properties: Properties | None) -> bool:
        """Check original caller policy and bound target before schema or client work."""
        validate_llm_caller_controls(
            properties, service_prefix=str(self.DEFAULT_PROPERTIES.get("service_prefix", "openai"))
        )
        caller = properties or {}
        execute = caller.get("execute_query", False)
        if type(execute) is not bool or "read_only_executor" in caller:
            raise sql_error("sql_policy_invalid")
        if "validate_query_prefixes" in caller:
            value = caller["validate_query_prefixes"]
            if type(value) is not list:
                raise sql_error("sql_policy_invalid")
            prefixes = cast(list[object], value)
            if (
                len(prefixes) != 1
                or type(prefixes[0]) is not str
                or not prefixes[0].isascii()
                or prefixes[0].upper() != "SELECT"
            ):
                raise sql_error("sql_policy_invalid")
        if execute:
            if SQL_REGISTRY_SELECTORS.intersection(caller):
                raise sql_error("sql_policy_invalid")
            if self._read_only_executor is None:
                raise sql_error("sql_execution_unavailable")
            self._read_only_executor.preflight(self._execution_target(attributes))
        return execute

    @staticmethod
    def _execution_target(attributes: Attributes) -> tuple[str, str, str]:
        target = tuple(attributes.get(key, "") for key in ("source", "database", "collection"))
        if any(type(part) is not str or not part for part in target):
            raise sql_error("sql_target_denied")
        return cast(tuple[str, str, str], target)

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        try:
            execute = self._execute
            if type(execute) is MethodType and execute.__func__ is _BUILTIN_EXECUTE:
                return self._execute_sql(input_data, attributes, properties).output_data
            return execute(input_data, attributes, properties).output_data
        except _MissingRegistryError:
            return [[]]

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        return self._execute_sql(input_data, attributes, properties, _diagnose_registry=True)

    def _execute_sql(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
        *,
        _diagnose_generation_target: bool = False,
        _diagnose_registry: bool = False,
    ) -> FunctionResult:
        execute_query = self._preflight_execution(attributes, properties)
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

        if execute_query:
            assert self._read_only_executor is not None
            schema = self._read_only_executor.get_schema(self._execution_target(attributes))
        else:
            registry = resolve_registry(properties)
            if not registry:
                raise _MissingRegistryError
            if _diagnose_registry or _diagnose_generation_target:
                _diagnose_source(registry, source)
            if _diagnose_generation_target:
                diagnose_generation_target(registry, source, database, collection)
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
        merged = prepare_llm_operator_properties(merged, self.DEFAULT_PROPERTIES, properties)
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
            except json.JSONDecodeError:
                raise sql_error("sql_query_rejected") from None
        elif isinstance(sql_result, dict):
            sql_data = cast("dict[str, Any]", sql_result)
        else:
            raise sql_error("sql_query_rejected")

        if not isinstance(sql_data, dict):
            raise sql_error("sql_query_rejected")
        generated_query = cast(dict[str, Any], sql_data).get("query")
        if not isinstance(generated_query, str) or not re.match(
            r"\A\s*[Ss][Ee][Ll][Ee][Cc][Tt]\b", generated_query
        ):
            raise sql_error("sql_query_rejected")

        if execute_query:
            assert self._read_only_executor is not None
            result = self._read_only_executor.execute(
                generated_query, self._execution_target(attributes)
            )
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


_BUILTIN_EXECUTE = NL2SQLOperator.__dict__["_execute"]
