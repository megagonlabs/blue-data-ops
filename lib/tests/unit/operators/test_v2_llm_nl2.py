from __future__ import annotations

import json
import time
from collections.abc import Sequence
from copy import deepcopy
from typing import Any
from unittest.mock import patch

import pytest

from blue_data_ops import (
    ErrorCategory,
    ErrorCode,
    ErrorStage,
    ExecMeta,
    FunctionResult,
    ValidationResult,
)
from blue_data_ops.data import RegistrySeam
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import (
    Attributes,
    DataBundle,
    NL2BNOperator,
    NL2LLMOperator,
    NL2SQLOperator,
    Operator,
    OperatorRegistry,
    Properties,
    default_registry,
)
from tests.doubles.data import RegistrySeamDouble

INPUT: DataBundle = [[]]
GRAPH: dict[str, Any] = {
    "nodes": {
        "rain": {"states": ["yes", "no"]},
        "wet": {"states": ["yes", "no"]},
    },
    "edges": {"rain": ["wet"]},
}
BN_ATTRIBUTES: Attributes = {
    "question": "What is the probability of wet given rain?",
    "source": "bn",
    "database": "default",
    "collection": "weather",
    "protocol_variant": "pgmpy",
}
BN_RESPONSE: dict[str, Any] = {
    "target_node": "wet",
    "target_state": "yes",
    "context": {"rain": "yes"},
}
SQL_ATTRIBUTES: Attributes = {
    "source": "pg",
    "question": "Which role is most common?",
    "protocol": "postgres",
    "database": "analytics",
    "collection": "public",
}
SQL_RESPONSE: dict[str, Any] = {
    "question": "Which role is most common?",
    "query": "SELECT role FROM jobs",
}


class ScriptedClient(LLMClient):
    def __init__(self, responses: Sequence[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[Any, dict[str, Any] | None, dict[str, Any] | None]] = []

    def execute_api_call(
        self,
        input: Any,  # noqa: A002
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


class RecordingSeam(RegistrySeamDouble, RegistrySeam):
    pass


def _seam() -> RecordingSeam:
    seam = RecordingSeam()
    seam.schema_result = {"graph_structure": GRAPH}
    seam.query_result = [{"probability": 0.75, "role": "manager"}]
    return seam


def _properties(
    client: LLMClient,
    seam: RegistrySeam | None = None,
    **extra: Any,
) -> Properties:
    result: Properties = {"llm_client": client, **extra}
    if seam is not None:
        result["data_registry"] = seam
    return result


def _assert_error(
    meta: ExecMeta,
    category: ErrorCategory,
    code: ErrorCode,
    stage: ErrorStage,
    operator_id: str,
    sensitive_text: str | None = None,
) -> None:
    assert len(meta.errors) == 1
    error = meta.errors[0]
    assert error.category is category
    assert error.code is code
    assert error.stage is stage
    assert error.operator_id == operator_id
    assert error.retryable is False
    if sensitive_text is not None:
        assert sensitive_text not in str(error)


@pytest.mark.parametrize(
    ("operator", "attributes", "properties"),
    [
        (
            NL2LLMOperator(),
            {"query": "list roles"},
            _properties(ScriptedClient([[{"x": 1}], [{"x": 1}]])),
        ),
        (
            NL2BNOperator(),
            BN_ATTRIBUTES,
            _properties(ScriptedClient([BN_RESPONSE, BN_RESPONSE]), _seam()),
        ),
        (
            NL2SQLOperator(),
            SQL_ATTRIBUTES,
            _properties(ScriptedClient([SQL_RESPONSE, SQL_RESPONSE]), _seam()),
        ),
    ],
)
def test_l3_c01_native_hooks_and_public_adapters_keep_exact_types(
    operator: Operator,
    attributes: Attributes,
    properties: Properties,
) -> None:
    assert "_execute" in type(operator).__dict__
    assert "_validate_input" in type(operator).__dict__
    native = operator._execute(INPUT, attributes, properties)  # pyright: ignore[reportPrivateUsage]
    validation = operator._validate_input(  # pyright: ignore[reportPrivateUsage]
        INPUT, attributes, properties
    )
    assert type(native) is FunctionResult
    assert type(validation) is ValidationResult
    assert type(operator.validate(INPUT, attributes, properties)) is bool
    assert type(operator.apply(INPUT, attributes, properties)) is list


def test_l3_c02_caller_defaults_and_results_are_isolated() -> None:
    operator = NL2LLMOperator()
    attributes: Attributes = {"query": "list roles"}
    original = deepcopy(attributes)
    client = ScriptedClient([[{"role": "engineer"}], [{"role": "engineer"}]])
    with patch.object(
        operator,
        "_execute",
        wraps=operator._execute,  # pyright: ignore[reportPrivateUsage]
    ) as execute:
        first = operator.run(INPUT, attributes, _properties(client))
        second = operator.run(INPUT, attributes, _properties(client))

    assert execute.call_count == 2
    assert attributes == original
    first_call_attributes = execute.call_args_list[0].args[1]
    second_call_attributes = execute.call_args_list[1].args[1]
    assert (
        first_call_attributes
        == second_call_attributes
        == {
            "query": "list roles",
            "context": "",
            "attrs": [],
        }
    )
    assert first_call_attributes is not attributes
    assert first_call_attributes is not second_call_attributes
    assert first[1] == second[1] == {}
    assert first[1] is not second[1]
    assert first[2].errors is not second[2].errors
    assert first[2].logs is not second[2].logs
    assert first[2].traces is not second[2].traces


@pytest.mark.parametrize("operator", [NL2LLMOperator(), NL2BNOperator(), NL2SQLOperator()])
def test_l3_c03_selected_registry_version_owns_error_identity(operator: Operator) -> None:
    registry = OperatorRegistry()
    registry.register(operator, "1.0.0")
    registry.register(operator, "2.0.0")
    for version in ("1.0.0", "2.0.0"):
        operator_id = f"{operator.name}@{version}"
        _, _, meta = registry.resolve(operator_id).run(INPUT, {})
        _assert_error(
            meta,
            ErrorCategory.RECOVERABLE,
            ErrorCode.INVALID_INPUT,
            ErrorStage.VALIDATE,
            operator_id,
        )


@pytest.mark.parametrize(
    ("operator", "attributes"),
    [
        (NL2LLMOperator(), {"query": "q", "attrs": ["bad"]}),
        (NL2BNOperator(), {**BN_ATTRIBUTES, "question": 7}),
        (NL2SQLOperator(), {**SQL_ATTRIBUTES, "question": 7}),
    ],
)
def test_l3_c04_invalid_structured_input_suppresses_dependencies(
    operator: Operator,
    attributes: Attributes,
) -> None:
    seam = _seam()
    client = ScriptedClient([])
    _, _, meta = operator.run(INPUT, attributes, _properties(client, seam))
    _assert_error(
        meta,
        ErrorCategory.RECOVERABLE,
        ErrorCode.INVALID_INPUT,
        ErrorStage.VALIDATE,
        f"{operator.name}@2.0.0",
    )
    assert meta.errors[0].suggestion
    assert client.calls == []
    assert seam.calls == []


@pytest.mark.parametrize("operator", [NL2LLMOperator(), NL2BNOperator(), NL2SQLOperator()])
def test_l3_c05_body_exception_is_contained_without_payload(operator: Operator) -> None:
    sensitive_text = "opaque-provider-detail"
    with patch.object(operator, "_execute", side_effect=RuntimeError(sensitive_text)) as execute:
        _, _, meta = operator.run(INPUT, {})
    assert execute.call_count == 0
    if operator.name == "nl2llm":
        valid: Attributes = {"query": "q"}
    elif operator.name == "nl2bn":
        valid = BN_ATTRIBUTES
    else:
        valid = SQL_ATTRIBUTES
    with patch.object(operator, "_execute", side_effect=RuntimeError(sensitive_text)) as execute:
        _, _, meta = operator.run(INPUT, valid)
    assert execute.call_count == 1
    _assert_error(
        meta,
        ErrorCategory.FAILED,
        ErrorCode.EXECUTION_FAILED,
        ErrorStage.EXECUTE,
        f"{operator.name}@2.0.0",
        sensitive_text,
    )


@pytest.mark.parametrize(
    ("operator", "attributes"),
    [
        (NL2LLMOperator(), {"query": "q"}),
        (NL2BNOperator(), BN_ATTRIBUTES),
        (NL2SQLOperator(), SQL_ATTRIBUTES),
    ],
)
def test_l3_c06_timeout_calls_body_once_and_discards_late_result(
    operator: Operator,
    attributes: Attributes,
) -> None:
    def slow_body(*args: Any, **kwargs: Any) -> FunctionResult:
        del args, kwargs
        time.sleep(0.03)
        return FunctionResult([[{"late": True}]], {})

    with patch.object(operator, "_execute", side_effect=slow_body) as execute:
        output, output_attributes, meta = operator.run(
            INPUT,
            attributes,
            {"execution.timeout_seconds": 0.001},
        )
    assert execute.call_count == 1
    assert output == [[]]
    assert output_attributes == {}
    _assert_error(
        meta,
        ErrorCategory.TIMEOUT,
        ErrorCode.OPERATOR_TIMEOUT,
        ErrorStage.EXECUTE,
        f"{operator.name}@2.0.0",
    )


@pytest.mark.parametrize(
    ("operator", "attributes"),
    [
        (NL2LLMOperator(), {"query": "q"}),
        (NL2BNOperator(), BN_ATTRIBUTES),
        (NL2SQLOperator(), SQL_ATTRIBUTES),
    ],
)
def test_l3_c07_malformed_native_result_is_rejected(
    operator: Operator,
    attributes: Attributes,
) -> None:
    with patch.object(operator, "_execute", return_value=object()) as execute:
        _, _, meta = operator.run(INPUT, attributes)
    assert execute.call_count == 1
    _assert_error(
        meta,
        ErrorCategory.FAILED,
        ErrorCode.EXECUTION_RESULT_INVALID,
        ErrorStage.NORMALIZE,
        f"{operator.name}@2.0.0",
    )


def test_l3_n01_valid_result_matches_raw_and_pins_exact_prompt_data() -> None:
    operator = NL2LLMOperator()
    attributes: Attributes = {
        "query": "rank languages",
        "context": "jobs",
        "attrs": [{"name": "language", "type": "str"}, {"name": "rank"}],
    }
    expected: DataBundle = [[{"language": "Python", "rank": 1}]]
    client = ScriptedClient([expected[0], expected[0]])
    properties = _properties(client)
    native = operator._execute(INPUT, attributes, properties)  # pyright: ignore[reportPrivateUsage]
    raw = operator.apply(INPUT, attributes, properties)
    assert native == FunctionResult(expected, {})
    assert raw == expected
    assert client.calls[0][2] == {
        "query": "rank languages",
        "context": "jobs",
        "attrs": "Required output attributes:\n- language: str\n- rank: (type will be inferred)\n",
    }
    assert client.calls[0][1] is not None
    assert (
        client.calls[0][1]["input_template"] is NL2LLMOperator.DEFAULT_PROPERTIES["input_template"]
    )


@pytest.mark.parametrize("query", ["", "   "])
def test_l3_n02_blank_query_is_successful_empty_without_provider(query: str) -> None:
    operator = NL2LLMOperator()
    client = ScriptedClient([])
    assert operator.apply(INPUT, {"query": query}, _properties(client)) == []
    output, _, meta = operator.run(INPUT, {"query": query}, _properties(client))
    assert output == [[]]
    assert meta.is_empty is True
    assert meta.errors == []
    assert client.calls == []


def test_l3_n03_missing_query_is_invalid_without_provider() -> None:
    client = ScriptedClient([])
    _, _, meta = NL2LLMOperator().run(INPUT, {}, _properties(client))
    assert meta.errors[0].code is ErrorCode.INVALID_INPUT
    assert client.calls == []


def test_l3_n04_invalid_attribute_descriptor_is_invalid_without_provider() -> None:
    client = ScriptedClient([])
    _, _, meta = NL2LLMOperator().run(
        INPUT,
        {"query": "q", "attrs": [{"type": "str"}]},
        _properties(client),
    )
    assert meta.errors[0].code is ErrorCode.INVALID_INPUT
    assert client.calls == []


def test_l3_n05_cleanup_contract_remains_in_provider_properties() -> None:
    client = ScriptedClient([[{"ish": 1}]])
    result = NL2LLMOperator().run(INPUT, {"query": "q"}, _properties(client))
    assert result[0] == [[{"ish": 1}]]
    assert client.calls[0][1] is not None
    assert client.calls[0][1]["output_transformations"] == [
        {"transformation": "replace", "from": "```", "to": ""},
        {"transformation": "replace", "from": "json", "to": ""},
    ]
    assert client.calls[0][1]["output_cast"] == "json"


def test_l3_n06_provider_empty_list_is_successful_empty() -> None:
    output, _, meta = NL2LLMOperator().run(
        INPUT,
        {"query": "q"},
        _properties(ScriptedClient([[]])),
    )
    assert output == [[]]
    assert meta.is_empty is True
    assert meta.errors == []


def test_l3_n07_malformed_bundle_shape_is_raw_but_not_canonical() -> None:
    operator = NL2LLMOperator()
    client = ScriptedClient([{"bad": True}, {"bad": True}])
    properties = _properties(client)
    assert operator.apply(INPUT, {"query": "q"}, properties) == [{"bad": True}]
    _, _, meta = operator.run(INPUT, {"query": "q"}, properties)
    assert meta.errors[0].code is ErrorCode.EXECUTION_RESULT_INVALID
    assert meta.errors[0].stage is ErrorStage.NORMALIZE


def test_l3_n08_provider_failure_propagates_raw_and_is_contained_canonically() -> None:
    operator = NL2LLMOperator()
    sensitive_text = "opaque-nl2llm-provider-detail"
    with pytest.raises(RuntimeError, match=sensitive_text):
        operator.apply(
            INPUT,
            {"query": "q"},
            _properties(ScriptedClient([RuntimeError(sensitive_text)])),
        )
    _, _, meta = operator.run(
        INPUT,
        {"query": "q"},
        _properties(ScriptedClient([RuntimeError(sensitive_text)])),
    )
    _assert_error(
        meta,
        ErrorCategory.FAILED,
        ErrorCode.EXECUTION_FAILED,
        ErrorStage.EXECUTE,
        "nl2llm@2.0.0",
        sensitive_text,
    )


@pytest.mark.parametrize("question", ["", "  "])
def test_l3_b01_blank_question_is_successful_empty_without_calls(question: str) -> None:
    seam = _seam()
    client = ScriptedClient([])
    attributes = {**BN_ATTRIBUTES, "question": question}
    assert NL2BNOperator().apply(INPUT, attributes, _properties(client, seam)) == [[]]
    output, _, meta = NL2BNOperator().run(INPUT, attributes, _properties(client, seam))
    assert output == [[]]
    assert meta.is_empty is True
    assert client.calls == []
    assert seam.calls == []


def test_l3_b02_missing_or_invalid_required_attribute_stops_calls() -> None:
    seam = _seam()
    client = ScriptedClient([])
    for attributes in ({"question": "q"}, {**BN_ATTRIBUTES, "question": 4}):
        _, _, meta = NL2BNOperator().run(INPUT, attributes, _properties(client, seam))
        assert meta.errors[0].code is ErrorCode.INVALID_INPUT
    assert client.calls == []
    assert seam.calls == []


def test_l3_b03_blank_required_value_reaches_body_failure() -> None:
    _, _, meta = NL2BNOperator().run(INPUT, {**BN_ATTRIBUTES, "source": ""})
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert meta.errors[0].stage is ErrorStage.EXECUTE


def test_l3_b04_unsupported_protocol_is_execution_failure_without_calls() -> None:
    seam = _seam()
    client = ScriptedClient([])
    _, _, meta = NL2BNOperator().run(
        INPUT,
        {**BN_ATTRIBUTES, "protocol_variant": "bayes"},
        _properties(client, seam),
    )
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert client.calls == []
    assert seam.calls == []


def test_l3_b05_missing_registry_is_raw_empty_but_canonical_failure() -> None:
    operator = NL2BNOperator()
    client = ScriptedClient([])
    assert operator.apply(INPUT, BN_ATTRIBUTES, _properties(client)) == [[]]
    _, _, meta = operator.run(INPUT, BN_ATTRIBUTES, _properties(client))
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert meta.errors[0].stage is ErrorStage.EXECUTE
    assert client.calls == []


def test_l3_b06_provided_schema_skips_lookup_and_executes_query() -> None:
    seam = _seam()
    client = ScriptedClient([BN_RESPONSE])
    output, _, meta = NL2BNOperator().run(
        INPUT,
        {**BN_ATTRIBUTES, "schema": json.dumps(GRAPH)},
        _properties(client, seam),
    )
    assert output[0][0]["prob"] == 0.75
    assert meta.errors == []
    assert seam.calls_to("get_data_source_schema") == []
    assert len(seam.calls_to("execute_query")) == 1
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "schema",
    [
        {"graph_structure": GRAPH},
        {"metadata": {"graph_structure": GRAPH}},
        {"entities": [], "relations": []},
        {},
    ],
    ids=["top-level-graph", "metadata-graph", "unstructured", "empty"],
)
def test_l3_b07_registry_schema_variants_keep_call_order(schema: dict[str, Any]) -> None:
    seam = _seam()
    seam.schema_result = schema
    client = ScriptedClient([BN_RESPONSE])
    NL2BNOperator().run(INPUT, BN_ATTRIBUTES, _properties(client, seam))
    assert [name for name, _ in seam.calls] == ["get_data_source_schema", "execute_query"]
    assert len(client.calls) == 1


def test_l3_b08_valid_query_returns_probability_query_and_explanation() -> None:
    seam = _seam()
    seam.query_result = [{"probability": 0.75, "explanation": "rain causes wetness"}]
    client = ScriptedClient([BN_RESPONSE])
    output, output_attributes, meta = NL2BNOperator().run(
        INPUT, BN_ATTRIBUTES, _properties(client, seam)
    )
    assert output == [
        [
            {
                "prob": 0.75,
                "query": BN_RESPONSE,
                "explanation": "rain causes wetness",
            }
        ]
    ]
    assert output_attributes == {}
    assert meta.errors == []


def test_l3_b09_initial_provider_failure_recovers_on_correction() -> None:
    seam = _seam()
    client = ScriptedClient([RuntimeError("initial"), BN_RESPONSE])
    output, _, meta = NL2BNOperator().run(INPUT, BN_ATTRIBUTES, _properties(client, seam))
    assert output[0][0]["prob"] == 0.75
    assert meta.errors == []
    assert len(client.calls) == 2
    assert client.calls[1][1] is not None
    assert "previously generated" in client.calls[1][1]["input_template"]


def test_l3_b10_invalid_initial_response_recovers_on_correction() -> None:
    seam = _seam()
    client = ScriptedClient([{"target_state": "yes"}, BN_RESPONSE])
    output, _, meta = NL2BNOperator().run(INPUT, BN_ATTRIBUTES, _properties(client, seam))
    assert output[0][0]["query"] == BN_RESPONSE
    assert meta.errors == []
    assert len(client.calls) == 2


def test_l3_b11_local_non_json_decode_error_propagates_raw_and_is_contained() -> None:
    operator = NL2BNOperator()
    seam = _seam()
    client = ScriptedClient(["deep", "deep"])
    original_loads = json.loads

    def fail_locally(value: str) -> Any:
        if value == "deep":
            raise RecursionError("parser-payload")
        return original_loads(value)

    with patch(
        "blue_data_ops.operators.nl2bn_operator.json.loads",
        side_effect=fail_locally,
    ):
        with pytest.raises(RecursionError, match="parser-payload"):
            operator.apply(
                INPUT,
                BN_ATTRIBUTES,
                _properties(client, seam, output_cast="str"),
            )
        _, _, meta = operator.run(
            INPUT,
            BN_ATTRIBUTES,
            _properties(client, seam, output_cast="str"),
        )
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert "parser-payload" not in str(meta.errors[0])


def test_l3_b12_correction_failure_and_exhaustion_keep_exact_calls() -> None:
    operator = NL2BNOperator()
    seam = _seam()
    failing = ScriptedClient([{"target_state": "yes"}, RuntimeError("correction")])
    with pytest.raises(RuntimeError, match="correction"):
        operator.apply(INPUT, BN_ATTRIBUTES, _properties(failing, seam))
    assert len(failing.calls) == 2

    exhausted = ScriptedClient([{"target_state": "yes"}, {"target_state": "yes"}])
    with pytest.raises(ValueError, match="failed after 1 correction attempts"):
        operator.apply(
            INPUT,
            {**BN_ATTRIBUTES, "max_corrections": 1},
            _properties(exhausted, seam),
        )
    assert len(exhausted.calls) == 2


def test_l3_b13_empty_registry_result_is_successful_null_probability() -> None:
    seam = _seam()
    seam.query_result = []
    output, _, meta = NL2BNOperator().run(
        INPUT,
        BN_ATTRIBUTES,
        _properties(ScriptedClient([BN_RESPONSE]), seam),
    )
    assert output == [[{"prob": None, "query": BN_RESPONSE}]]
    assert meta.errors == []


def test_l3_b14_formatter_fallthrough_is_successful_null_probability() -> None:
    seam = _seam()
    seam.query_result = [["not-a-record"]]
    output, _, meta = NL2BNOperator().run(
        INPUT,
        BN_ATTRIBUTES,
        _properties(ScriptedClient([BN_RESPONSE]), seam),
    )
    assert output == [[{"prob": None, "query": BN_RESPONSE}]]
    assert meta.errors == []


def test_l3_b15_registry_exception_propagates_raw_and_is_contained() -> None:
    class FailingSeam(RecordingSeam):
        def get_data_source_schema(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            raise RuntimeError("opaque-schema-detail")

    operator = NL2BNOperator()
    seam = FailingSeam()
    with pytest.raises(RuntimeError, match="opaque-schema-detail"):
        operator.apply(INPUT, BN_ATTRIBUTES, _properties(ScriptedClient([]), seam))
    _, _, meta = operator.run(INPUT, BN_ATTRIBUTES, _properties(ScriptedClient([]), seam))
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert "opaque-schema-detail" not in str(meta.errors[0])


@pytest.mark.parametrize("question", ["", "  "])
def test_l3_s01_blank_question_is_successful_empty_without_calls(question: str) -> None:
    seam = _seam()
    client = ScriptedClient([])
    attributes = {**SQL_ATTRIBUTES, "question": question}
    assert NL2SQLOperator().apply(INPUT, attributes, _properties(client, seam)) == [[]]
    output, _, meta = NL2SQLOperator().run(INPUT, attributes, _properties(client, seam))
    assert output == [[]]
    assert meta.is_empty is True
    assert client.calls == []
    assert seam.calls == []


def test_l3_s02_missing_or_invalid_required_attribute_stops_calls() -> None:
    seam = _seam()
    client = ScriptedClient([])
    for attributes in ({"question": "q"}, {**SQL_ATTRIBUTES, "question": 4}):
        _, _, meta = NL2SQLOperator().run(INPUT, attributes, _properties(client, seam))
        assert meta.errors[0].code is ErrorCode.INVALID_INPUT
    assert client.calls == []
    assert seam.calls == []


def test_l3_s03_absent_source_is_invalid_but_explicit_empty_reaches_body() -> None:
    absent = dict(SQL_ATTRIBUTES)
    del absent["source"]
    seam = _seam()
    client = ScriptedClient([SQL_RESPONSE])
    _, _, absent_meta = NL2SQLOperator().run(INPUT, absent, _properties(client, seam))
    assert absent_meta.errors[0].code is ErrorCode.INVALID_INPUT
    assert seam.calls == []
    output, _, explicit_meta = NL2SQLOperator().run(
        INPUT,
        {**SQL_ATTRIBUTES, "source": ""},
        _properties(client, seam),
    )
    assert output == [[{"probability": 0.75, "role": "manager"}]]
    assert explicit_meta.errors == []
    assert seam.calls_to("get_data_source_schema")[0]["source"] == ""


def test_l3_s04_missing_registry_is_raw_empty_but_canonical_failure() -> None:
    operator = NL2SQLOperator()
    client = ScriptedClient([])
    assert operator.apply(INPUT, SQL_ATTRIBUTES, _properties(client)) == [[]]
    _, _, meta = operator.run(INPUT, SQL_ATTRIBUTES, _properties(client))
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert client.calls == []


def test_l3_s05_execute_path_matches_raw_with_exact_calls() -> None:
    operator = NL2SQLOperator()
    seam = _seam()
    client = ScriptedClient([SQL_RESPONSE, SQL_RESPONSE])
    properties = _properties(client, seam)
    native = operator._execute(  # pyright: ignore[reportPrivateUsage]
        INPUT, SQL_ATTRIBUTES, properties
    )
    raw = operator.apply(INPUT, SQL_ATTRIBUTES, properties)
    expected: DataBundle = [[{"probability": 0.75, "role": "manager"}]]
    assert native == FunctionResult(expected, {})
    assert raw == expected
    assert len(seam.calls_to("get_data_source_schema")) == 2
    assert len(seam.calls_to("execute_query")) == 2
    assert len(client.calls) == 2
    assert client.calls[0][2] is not None
    assert client.calls[0][2]["question"] == SQL_ATTRIBUTES["question"]


def test_l3_s06_sql_only_path_skips_registry_execution() -> None:
    seam = _seam()
    client = ScriptedClient([SQL_RESPONSE])
    output, _, meta = NL2SQLOperator().run(
        INPUT,
        SQL_ATTRIBUTES,
        _properties(client, seam, execute_query=False),
    )
    assert output == [[{"sql": SQL_RESPONSE["query"]}]]
    assert meta.errors == []
    assert len(seam.calls_to("get_data_source_schema")) == 1
    assert seam.calls_to("execute_query") == []


def test_l3_s07_supplied_schema_is_ignored_and_registry_schema_is_used() -> None:
    seam = _seam()
    client = ScriptedClient([SQL_RESPONSE])
    NL2SQLOperator().run(
        INPUT,
        {**SQL_ATTRIBUTES, "schema": '{"ignored": true}'},
        _properties(client, seam, execute_query=False),
    )
    assert len(seam.calls_to("get_data_source_schema")) == 1
    assert client.calls[0][2] is not None
    assert "ignored" not in client.calls[0][2]["schema"]


@pytest.mark.parametrize(
    "response",
    [
        RuntimeError("opaque-provider-detail"),
        "not-json",
        {"question": "missing query"},
        {"query": "DELETE FROM jobs"},
    ],
    ids=["provider", "parser", "missing-query", "prefix"],
)
def test_l3_s08_provider_and_parser_failures_are_contained(response: Any) -> None:
    seam = _seam()
    _, _, meta = NL2SQLOperator().run(
        INPUT,
        SQL_ATTRIBUTES,
        _properties(ScriptedClient([response]), seam),
    )
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert meta.errors[0].stage is ErrorStage.EXECUTE
    assert "opaque-provider-detail" not in str(meta.errors[0])
    assert seam.calls_to("execute_query") == []


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownArgumentType]
    ("query_result", "expected", "is_empty"),
    [  # pyright: ignore[reportUnknownArgumentType]
        ({"n": 1}, [[{"n": 1}]], False),
        ([], [[]], True),
        (None, [[]], True),
        ([{"n": 1}], [[{"n": 1}]], False),
        ([[{"n": 1}]], [[{"n": 1}]], False),
    ],
    ids=["dict", "empty", "none", "list", "nested"],
)
def test_l3_s09_formatter_success_shapes(
    query_result: Any,
    expected: DataBundle,
    is_empty: bool,
) -> None:
    seam = _seam()
    seam.query_result = query_result
    output, _, meta = NL2SQLOperator().run(
        INPUT,
        SQL_ATTRIBUTES,
        _properties(ScriptedClient([SQL_RESPONSE]), seam),
    )
    assert output == expected
    assert meta.is_empty is is_empty
    assert meta.errors == []


def test_l3_s10_formatter_none_is_raw_none_but_canonical_invalid_result() -> None:
    operator = NL2SQLOperator()
    seam = _seam()
    seam.query_result = [["not-a-record"]]
    assert (
        operator.apply(
            INPUT,
            SQL_ATTRIBUTES,
            _properties(ScriptedClient([SQL_RESPONSE]), seam),
        )
        is None
    )
    _, _, meta = operator.run(
        INPUT,
        SQL_ATTRIBUTES,
        _properties(ScriptedClient([SQL_RESPONSE]), seam),
    )
    assert meta.errors[0].code is ErrorCode.EXECUTION_RESULT_INVALID
    assert meta.errors[0].stage is ErrorStage.NORMALIZE


@pytest.mark.parametrize("field", ["protocol", "database", "collection"])
def test_l3_s11_blank_required_value_is_execution_failure(field: str) -> None:
    _, _, meta = NL2SQLOperator().run(INPUT, {**SQL_ATTRIBUTES, field: ""})
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert meta.errors[0].stage is ErrorStage.EXECUTE


def test_l3_s12_protocol_check_occurs_after_schema_lookup() -> None:
    seam = _seam()
    client = ScriptedClient([])
    _, _, meta = NL2SQLOperator().run(
        INPUT,
        {**SQL_ATTRIBUTES, "protocol": "oracle"},
        _properties(client, seam),
    )
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert len(seam.calls_to("get_data_source_schema")) == 1
    assert seam.calls_to("execute_query") == []
    assert client.calls == []


def test_l3_s13_registry_exception_propagates_raw_and_is_contained() -> None:
    class FailingSeam(RecordingSeam):
        def execute_query(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            raise RuntimeError("opaque-query-detail")

    operator = NL2SQLOperator()
    seam = FailingSeam()
    with pytest.raises(RuntimeError, match="opaque-query-detail"):
        operator.apply(
            INPUT,
            SQL_ATTRIBUTES,
            _properties(ScriptedClient([SQL_RESPONSE]), seam),
        )
    _, _, meta = operator.run(
        INPUT,
        SQL_ATTRIBUTES,
        _properties(ScriptedClient([SQL_RESPONSE]), seam),
    )
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert "opaque-query-detail" not in str(meta.errors[0])


def test_l3_registry_default_remains_exactly_36_v1_cards() -> None:
    cards = default_registry().list_cards()
    assert len(cards) == 36
    assert len({card.operator_id for card in cards}) == 36
    assert all(card.version == "1.0.0" for card in cards)
    assert {card.operator_id for card in cards}.issuperset(
        {"nl2llm@1.0.0", "nl2bn@1.0.0", "nl2sql@1.0.0"}
    )
