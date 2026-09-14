from __future__ import annotations

from unittest.mock import patch

import pytest

from blue_data_ops import ErrorCategory, ErrorCode, ErrorStage, FunctionResult, ValidationResult
from blue_data_ops.operators import (
    Attributes,
    DataBundle,
    Operator,
    OperatorRegistry,
    VectorEmbedOperator,
    VectorSearchOperator,
    VectorSimilarityOperator,
    default_registry,
)
from tests.stubs.sentence_transformers import SentenceTransformer

EMBED_INPUT: DataBundle = [[{"id": "a", "title": "alpha"}]]
SEARCH_INPUT: DataBundle = [
    [
        {
            "id": "a",
            "embedding": [1.0, 0.0],
            "embed.model": "model-2d",
        }
    ]
]
SEARCH_ATTRIBUTES: Attributes = {"query": {"embedding": [1.0, 0.0], "model": "model-2d"}}
SIMILARITY_INPUT: DataBundle = [
    [{"id": "left", "embedding": [1.0, 0.0]}],
    [{"id": "right", "embedding": [1.0, 0.0]}],
]


@pytest.fixture(autouse=True)
def reset_model_stub() -> None:
    SentenceTransformer.reset()


VALID_CASES: list[tuple[Operator, DataBundle, Attributes]] = [
    (VectorEmbedOperator(), EMBED_INPUT, {"text_field": ["title"]}),
    (VectorSearchOperator(), SEARCH_INPUT, SEARCH_ATTRIBUTES),
    (VectorSimilarityOperator(), SIMILARITY_INPUT, {}),
]

INVALID_CASES: list[tuple[Operator, DataBundle, Attributes]] = [
    (VectorEmbedOperator(), EMBED_INPUT, {"text_field": ("title",)}),
    (VectorSearchOperator(), SEARCH_INPUT, {}),
    (VectorSimilarityOperator(), [[]], {}),
]


@pytest.mark.parametrize(("operator", "input_data", "attributes"), VALID_CASES)
def test_vector_operator_owns_native_hooks_and_matches_public_apply(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
) -> None:
    operator_type = type(operator)

    assert "_execute" in operator_type.__dict__
    assert "_validate_input" in operator_type.__dict__
    result = getattr(operator, "_execute")(input_data, attributes)

    assert type(result) is FunctionResult
    assert result.output_attributes == {}
    assert result.output_data == operator.apply(input_data, attributes)


@pytest.mark.parametrize(("operator", "input_data", "attributes"), VALID_CASES)
def test_run_executes_native_vector_body_once_and_returns_fresh_attributes(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
) -> None:
    raw_output = operator.apply(input_data, attributes)
    before = dict(attributes)

    with patch.object(operator, "_execute", wraps=getattr(operator, "_execute")) as execute:
        output_data, output_attributes, meta = operator.run(input_data, attributes)
    second_output_attributes = operator.run(input_data, attributes)[1]

    assert execute.call_count == 1
    assert output_data == raw_output
    assert output_attributes == {}
    assert output_attributes is not second_output_attributes
    assert meta.errors == []
    assert meta.is_empty is False
    assert attributes == before


@pytest.mark.parametrize(("operator", "input_data", "attributes"), INVALID_CASES)
def test_invalid_vector_input_is_recoverable_and_suppresses_execution(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
) -> None:
    validation = getattr(operator, "_validate_input")(input_data, attributes)
    assert type(validation) is ValidationResult
    assert validation.ok is False
    assert validation.reason
    assert operator.validate(input_data, attributes) is False

    with patch.object(
        operator,
        "_execute",
        side_effect=AssertionError("execution must be suppressed"),
    ) as execute:
        output_data, output_attributes, meta = operator.run(input_data, attributes)

    assert execute.call_count == 0
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    error = meta.errors[0]
    assert error.category is ErrorCategory.RECOVERABLE
    assert error.code is ErrorCode.INVALID_INPUT
    assert error.stage is ErrorStage.VALIDATE
    assert error.operator_id == f"{operator.name}@2.0.0"
    assert error.suggestion == validation.reason


def test_vector_embed_missing_field_stays_raw_and_is_contained_by_run() -> None:
    operator = VectorEmbedOperator()
    attributes: Attributes = {"text_field": ["title"]}
    input_data: DataBundle = [[{"id": "missing"}]]

    assert operator.validate(input_data, attributes) is True
    with pytest.raises(ValueError, match=r"Missing text fields \['title'\]"):
        operator.apply(input_data, attributes)

    output_data, output_attributes, meta = operator.run(input_data, attributes)
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert meta.errors[0].stage is ErrorStage.EXECUTE


def test_vector_search_malformed_dict_query_stays_raw_and_is_contained_by_run() -> None:
    operator = VectorSearchOperator()
    attributes: Attributes = {"query": {"model": "model-2d"}}

    assert operator.validate(SEARCH_INPUT, attributes) is True
    with pytest.raises(ValueError, match="dict containing 'embedding'"):
        operator.apply(SEARCH_INPUT, attributes)

    output_data, output_attributes, meta = operator.run(SEARCH_INPUT, attributes)
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert meta.errors[0].stage is ErrorStage.EXECUTE


def test_vector_optional_dependency_failure_stays_raw_and_is_contained_by_run() -> None:
    operator = VectorEmbedOperator()
    attributes: Attributes = {"text_field": ["title"]}

    with patch(
        "blue_data_ops.operators.vector_embed_operator.import_module",
        side_effect=ImportError("optional dependency detail must stay private"),
    ):
        with pytest.raises(ImportError, match="optional dependency detail"):
            operator.apply(EMBED_INPUT, attributes)

        output_data, output_attributes, meta = operator.run(EMBED_INPUT, attributes)

    assert output_data == [[]]
    assert output_attributes == {}
    assert len(meta.errors) == 1
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert meta.errors[0].stage is ErrorStage.EXECUTE
    assert "optional dependency detail" not in meta.errors[0].message


def test_vector_similarity_structured_validation_uses_input_groups() -> None:
    operator = VectorSimilarityOperator()
    validate_input = getattr(operator, "_validate_input")

    assert validate_input(SIMILARITY_INPUT, {}) == ValidationResult(True, None)
    invalid = validate_input([SIMILARITY_INPUT[0]], {})
    assert invalid.ok is False
    assert invalid.reason


@pytest.mark.parametrize(("operator", "input_data", "attributes"), INVALID_CASES)
def test_selected_versions_keep_exact_vector_error_identity(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
) -> None:
    registry = OperatorRegistry()
    registry.register(operator, "1.0.0")
    registry.register(operator, "2.0.0")

    for version in ("1.0.0", "2.0.0"):
        operator_id = f"{operator.name}@{version}"
        resolved = registry.resolve(operator_id)
        output_data, output_attributes, meta = resolved.run(input_data, attributes)

        assert resolved.operator_id == operator_id
        assert output_data == [[]]
        assert output_attributes == {}
        assert len(meta.errors) == 1
        assert meta.errors[0].operator_id == operator_id
        assert meta.errors[0].code is ErrorCode.INVALID_INPUT


def test_v1_default_registry_is_the_32_card_compatibility_catalog() -> None:
    cards = default_registry().list_cards()

    assert len(cards) == 32
    assert all(card.version == "1.0.0" for card in cards)
