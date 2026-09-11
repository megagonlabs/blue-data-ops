from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from blue_data_ops import ErrorCode, ErrorStage
from blue_data_ops.data import RegistrySeam
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators.registry import versioned_registry


class ScriptedClient(LLMClient):
    def __init__(self, responses: list[Any]) -> None:
        self.responses = deepcopy(responses)
        self.calls: list[Any] = []

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append((input, properties, additional_data))
        if not self.responses:
            raise AssertionError("provider response queue exhausted")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class ScriptedRegistry(RegistrySeam):
    def __init__(self, *, schema: Any = None, execute_result: Any = None) -> None:
        self.schema: Any = {} if schema is None else deepcopy(schema)
        self.execute_result = deepcopy(execute_result)
        self.calls: list[tuple[str, Any]] = []

    def get_data_source_schema(
        self,
        source: str,
        database: str,
        collection: str,
        protocol: str | None = None,
        format: str = "dict",
    ) -> Any:
        self.calls.append(("schema", (source, database, collection, protocol, format)))
        return deepcopy(self.schema)

    def execute_query(
        self,
        query: Any,
        source: str,
        database: str | None = None,
        collection: str | None = None,
        optional_properties: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(("query", (query, source, database, collection, optional_properties)))
        return deepcopy(self.execute_result)


def _assert_successful_empty(result: tuple[Any, Any, Any]) -> None:
    output_data, output_attributes, meta = result
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is True
    assert meta.errors == []


def _assert_error(result: tuple[Any, Any, Any], code: ErrorCode, stage: ErrorStage) -> None:
    output_data, output_attributes, meta = result
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    assert meta.errors[0].code is code
    assert meta.errors[0].stage is stage


def _properties(client: LLMClient, registry: RegistrySeam | None = None) -> dict[str, Any]:
    properties: dict[str, Any] = {"llm_client": client}
    if registry is not None:
        properties["data_registry"] = registry
    return properties


def test_semantic_extract_processes_a_later_group() -> None:
    operator = versioned_registry().resolve("semantic_extract@3.0.0")
    client = ScriptedClient([{"skill": ["Python"]}])
    output_data, output_attributes, meta = operator.run(
        [[], [{"id": 1, "bio": "Ada uses Python"}]],
        {"entities": [{"name": "skill", "extract_on_fields": ["bio"]}]},
        _properties(client),
    )

    assert output_data == [[], [{"skill": ["Python"]}]]
    assert output_attributes == {}
    assert meta.errors == []
    assert meta.is_empty is False
    assert len(client.calls) == 1


def test_semantic_filter_preserves_empty_groups_and_rejects_boolean_aliases() -> None:
    operator = versioned_registry().resolve("semantic_filter@3.0.0")
    client = ScriptedClient(["false", "true"])
    output_data, output_attributes, meta = operator.run(
        [[], [{"id": 1, "score": 2}, {"id": 2, "score": 9}]],
        {"filter_conditions": {"score": "is high"}, "return_idx": True},
        _properties(client),
    )
    assert output_data == [[{"indices": []}], [{"indices": [1]}]]
    assert output_attributes == {}
    assert meta.errors == []
    assert meta.is_empty is False

    alias_client = ScriptedClient(["yes"])
    _assert_error(
        operator.run(
            [[{"id": 2, "score": 9}]],
            {"filter_conditions": {"score": "is high"}},
            _properties(alias_client),
        ),
        ErrorCode.EXECUTION_FAILED,
        ErrorStage.EXECUTE,
    )


def test_semantic_project_processes_a_later_group() -> None:
    operator = versioned_registry().resolve("semantic_project@3.0.0")
    client = ScriptedClient([{"first": "name"}])
    output_data, output_attributes, meta = operator.run(
        [[], [{"first": "Ada", "age": 37}]],
        {"projection_instructions": "keep first as name"},
        _properties(client),
    )
    assert output_data == [[], [{"name": "Ada"}]]
    assert output_attributes == {}
    assert meta.errors == []
    assert meta.is_empty is False
    assert len(client.calls) == 1


def test_semantic_transform_processes_a_later_group() -> None:
    operator = versioned_registry().resolve("semantic_transform@3.0.0")
    client = ScriptedClient(
        [
            {
                "full_name": {
                    "source_fields": ["name"],
                    "transformation_type": "field_mapping_without_value_change",
                }
            }
        ]
    )
    output_data, output_attributes, meta = operator.run(
        [[], [{"name": "Ada"}]],
        {"output_desc": {"full_name": {"description": "copied name", "required": True}}},
        _properties(client),
    )
    assert output_data == [[], [{"full_name": "Ada"}]]
    assert output_attributes == {}
    assert meta.errors == []
    assert meta.is_empty is False
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    ("operator_id", "input_data", "attributes", "response"),
    [
        (
            "semantic_extract@3.0.0",
            [[{"bio": "Ada uses Python"}]],
            {"entities": [{"name": "skill"}]},
            [],
        ),
        (
            "semantic_project@3.0.0",
            [[{"first": "Ada"}]],
            {"projection_instructions": "keep first"},
            [],
        ),
        (
            "semantic_transform@3.0.0",
            [[{"raw": "A"}]],
            {"output_desc": {"label": {"description": "normalized label"}}},
            [],
        ),
    ],
)
def test_malformed_semantic_responses_fail_the_whole_call(
    operator_id: str,
    input_data: list[list[dict[str, Any]]],
    attributes: dict[str, Any],
    response: Any,
) -> None:
    client = ScriptedClient([response])
    _assert_error(
        versioned_registry()
        .resolve(operator_id)
        .run(
            input_data,
            attributes,
            _properties(client),
        ),
        ErrorCode.EXECUTION_FAILED,
        ErrorStage.EXECUTE,
    )
    assert len(client.calls) == 1


def test_semantic_join_distinguishes_no_pairs_from_a_malformed_response() -> None:
    operator = versioned_registry().resolve("semantic_join@3.0.0")
    attributes: dict[str, Any] = {
        "estimate_cost": False,
        "left_fields": [],
        "right_fields": [],
    }
    empty_client = ScriptedClient([])
    _assert_successful_empty(
        operator.run(
            [[{"left": "Ada"}], []],
            attributes,
            _properties(empty_client),
        )
    )
    assert empty_client.calls == []

    malformed_client = ScriptedClient(["not json"])
    _assert_error(
        operator.run(
            [[{"left": "Ada"}], [{"right": "ADA"}]],
            attributes,
            _properties(malformed_client),
        ),
        ErrorCode.EXECUTION_FAILED,
        ErrorStage.EXECUTE,
    )
    assert len(malformed_client.calls) == 1


def test_nl2llm_distinguishes_empty_records_from_invalid_or_malformed_results() -> None:
    operator = versioned_registry().resolve("nl2llm@3.0.0")
    blank_client = ScriptedClient([])
    _assert_error(
        operator.run([], {"query": "  "}, _properties(blank_client)),
        ErrorCode.INVALID_INPUT,
        ErrorStage.VALIDATE,
    )
    assert blank_client.calls == []

    empty_client = ScriptedClient([[]])
    _assert_successful_empty(
        operator.run([], {"query": "Return matching records"}, _properties(empty_client))
    )
    malformed_client = ScriptedClient([{"answer": "Ada"}])
    _assert_error(
        operator.run([], {"query": "Return a record"}, _properties(malformed_client)),
        ErrorCode.EXECUTION_RESULT_INVALID,
        ErrorStage.NORMALIZE,
    )


SQL_ATTRIBUTES = {
    "collection": "public",
    "database": "analytics",
    "protocol": "postgres",
    "question": "List roles",
    "source": "warehouse",
}


def test_nl2sql_validates_routing_and_distinguishes_backend_result_shapes() -> None:
    operator = versioned_registry().resolve("nl2sql@3.0.0")
    invalid_client = ScriptedClient([])
    invalid_registry = ScriptedRegistry()
    _assert_error(
        operator.run(
            [],
            {**SQL_ATTRIBUTES, "source": " "},
            _properties(invalid_client, invalid_registry),
        ),
        ErrorCode.INVALID_INPUT,
        ErrorStage.VALIDATE,
    )
    assert invalid_client.calls == []
    assert invalid_registry.calls == []

    empty_client = ScriptedClient([{"query": "SELECT role FROM jobs WHERE 1 = 0"}])
    empty_registry = ScriptedRegistry(schema={"jobs": {"role": "text"}}, execute_result=[])
    _assert_successful_empty(
        operator.run(
            [],
            SQL_ATTRIBUTES,
            {
                **_properties(empty_client, empty_registry),
                "execute_query": True,
            },
        )
    )

    malformed_client = ScriptedClient([{"query": "SELECT role FROM jobs"}])
    malformed_registry = ScriptedRegistry(
        schema={"jobs": {"role": "text"}}, execute_result=[["not-a-record"]]
    )
    _assert_error(
        operator.run(
            [],
            SQL_ATTRIBUTES,
            {
                **_properties(malformed_client, malformed_registry),
                "execute_query": True,
            },
        ),
        ErrorCode.EXECUTION_RESULT_INVALID,
        ErrorStage.NORMALIZE,
    )


BN_ATTRIBUTES = {
    "collection": "risk_model",
    "database": "default",
    "explanation": False,
    "protocol_variant": "pgmpy",
    "question": "What is the risk?",
    "schema": "BN schema",
    "source": "bayes",
}
BN_QUERY: dict[str, Any] = {"context": {}, "target_node": "risk", "target_state": "high"}


def test_nl2bn_distinguishes_no_rows_missing_probability_and_real_zero() -> None:
    operator = versioned_registry().resolve("nl2bn@3.0.0")

    empty_client = ScriptedClient([BN_QUERY])
    empty_registry = ScriptedRegistry(execute_result=[])
    _assert_successful_empty(
        operator.run([], BN_ATTRIBUTES, _properties(empty_client, empty_registry))
    )

    missing_client = ScriptedClient([BN_QUERY])
    missing_registry = ScriptedRegistry(execute_result=[{}])
    _assert_error(
        operator.run([], BN_ATTRIBUTES, _properties(missing_client, missing_registry)),
        ErrorCode.EXECUTION_FAILED,
        ErrorStage.EXECUTE,
    )

    zero_client = ScriptedClient([BN_QUERY])
    zero_registry = ScriptedRegistry(execute_result=[{"probability": 0}])
    output_data, output_attributes, meta = operator.run(
        [], BN_ATTRIBUTES, _properties(zero_client, zero_registry)
    )
    assert output_data == [[{"prob": 0, "query": BN_QUERY}]]
    assert output_attributes == {}
    assert meta.errors == []
    assert meta.is_empty is False
