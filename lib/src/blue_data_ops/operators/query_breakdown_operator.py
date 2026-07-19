# ruff: noqa: E501
# The prompt is a byte-exact provider protocol fixture and intentionally retains long lines.

from __future__ import annotations

from typing import Any, ClassVar, cast

from blue_data_ops.llm import resolve_llm_client
from blue_data_ops.operators._multipart_plan import build_multipart_pipelines
from blue_data_ops.operators.types import Attributes, AttributeSpec, DataBundle, Properties
from blue_data_ops.plan import PlanRecord, RefinableOperator

_PROMPT = """
Your task is to process a natural language query, and break it down to its subqueries.\x20\x20
Your strategy is to translate the natural language query into SQL, defining each subquery as common table expressions (CTE):
* Each subquery should be sufficiently self-contained and independent in terms of specific data to retrieve.\x20
* Break down into as many subsqueries as necessary but don't do excessively.\x20
* Only last subquery should join all the subqueries to answer the natural language query. Return the results in JSON format.

Return the results in JSON format.
The response should be a valid JSON array containing the following information for each CTE:
- 'description': natural language description of the CTE, representing the subquery
- 'sql': sql statement corresponding to the CTE
- 'table':  name of the CTE table, use short generic table names\x20
- 'columns': a list of columns of the table, each with a name and type (suitable for sql)
- 'dependency': a list of dependent tables names, as defined in respective CTEs
- 'generality': score of 0 to 10, where a score of 10 indicating whether the subquery can be completed answered through public general knowledge sources and a score of 0 indicating subquery can only be answered through private data sources

Here are additional requirements:
- Create a total of ${num_alternatives} alternatives.
- The output should be a JSON array, each containing an alternative set of CTEs.\x20
- Each alternative set of CTE should be in a JSON array with each CTE as a JSON object in the array.
- As such the overall output should be a JSON array of JSON arrays each representing an alternative set. The second level of JSONArray contains JSON objects.
- Output should not be 3 levels of JSON Arrays.\x20
- Avoid using IN within a CTE. Instead breakdown further and create another CTE and have another CTE finally that uses JOIN to put the subqueries together.\x20
- Dependency field should only contain table names defined in other CTEs.
- Use columns with ids sparingly. When joining especially different tables use columns that have values instead of ids.
- There might be optional context provided. Use it to assist the query if provided.
- There might be specificed schema, whenever possible try to match it.
- Each object should contain the requested information in a structured format
- Please try to return non-empty output. If the query is not clear, please use your best judgement to return a non-empty output.
- The response should be well-formatted and easy to parse.
- Output the JSON directly. Do not generate explanation or other additional output.

Below is an example:\x20
Query:\x20
what jobs are available for data scientists in bay area?\x20

Output:\x20
[[{"description":"Retrieve all jobs for data scientist roles","sql":"SELECT job_title, company_name, location FROM jobs WHERE LOWER(job_title) LIKE '%data scientist%'","table":"ds_roles","columns":[{"name":"job_title","type":"VARCHAR"},{"name":"company_name","type":"VARCHAR"},{"name":"location","type":"VARCHAR"}],"dependency":[],"generality":3},{"description":"Retrieve locations that are considered part of the Bay Area","sql":"SELECT city FROM locations WHERE city IN ('San Francisco', 'San Jose', 'Oakland', 'Palo Alto', 'Mountain View', 'Sunnyvale', 'Berkeley')","table":"bay_locs","columns":[{"name":"city","type":"VARCHAR"}],"dependency":[],"generality":8},{"description":"Join data scientist job listings with Bay Area locations to find available data scientist jobs in the Bay Area","sql":"SELECT d.job_title, d.company_name, d.location FROM ds_roles d JOIN bay_locs b ON LOWER(d.location) = LOWER(b.city)","table":"ds_jobs_bayarea","columns":[{"name":"job_title","type":"VARCHAR"},{"name":"company_name","type":"VARCHAR"},{"name":"location","type":"VARCHAR"}],"dependency":["ds_roles","bay_locs"],"generality":2}]]

Below is Your task:

Query:
${query}

Schema:
${schema}

Context:
${context}

Output:
"""


def _call_provider(attributes: Attributes, properties: Properties | None) -> Any:
    query = attributes.get("query", "")
    context = attributes.get("context", "")
    num_alternatives = attributes.get("num_alternatives", 1)
    schema = attributes.get("schema", "")

    if not query or not cast(str, query).strip():
        return []

    merged = {**QueryBreakdownOperator.DEFAULT_PROPERTIES, **(properties or {})}
    client = resolve_llm_client(merged)
    additional_data = {
        "query": query,
        "context": context,
        "num_alternatives": num_alternatives,
        "schema": schema,
    }
    return client.execute_api_call({}, properties=merged, additional_data=additional_data)


def query_breakdown_operator_function(
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
) -> DataBundle:
    """Generate multipart-query descriptions through the configured LLM client."""
    del input_data
    return cast(DataBundle, _call_provider(attributes, properties))


def query_breakdown_operator_refiner(
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
) -> list[PlanRecord]:
    """Generate multipart-query descriptions and turn them into pipelines."""
    del input_data
    plans = _call_provider(attributes, properties)
    return build_multipart_pipelines(
        plans,
        attributes.get("serialize", True),
        properties,
    )


def query_breakdown_operator_explainer(
    output: DataBundle,
    input_data: DataBundle,
    attributes: Attributes,
) -> dict[str, Any]:
    """Return the source operator's minimal explanation record."""
    del input_data
    return {"output": output, "attributes": attributes}


class QueryBreakdownOperator(RefinableOperator):
    """Break a natural-language query into multipart execution plans."""

    name: ClassVar[str] = "query_breakdown"
    description: ClassVar[str] = (
        "Processes natural language query and break it down to subqueries using common "
        "table expressions"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "query": AttributeSpec(
            type="str",
            description="Natural language query to process",
            required=True,
        ),
        "context": AttributeSpec(
            type="str",
            description="Optional context to provide domain knowledge",
            default="",
        ),
        "schema": AttributeSpec(
            type="str",
            description="Optional schema to match",
            default=[],
        ),
        "num_alternatives": AttributeSpec(
            type="int",
            description="Optional number of alternatives to generate",
            default=1,
        ),
    }
    PROPERTIES: ClassVar[dict[str, Any]] = {"refine": True}
    DEFAULT_PROPERTIES: ClassVar[dict[str, Any]] = {
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
        return query_breakdown_operator_function(input_data, attributes, properties)

    def refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        return query_breakdown_operator_refiner(input_data, attributes, properties)

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        return query_breakdown_operator_explainer(output, input_data, attributes)


__all__ = [
    "QueryBreakdownOperator",
    "query_breakdown_operator_explainer",
    "query_breakdown_operator_function",
    "query_breakdown_operator_refiner",
]
