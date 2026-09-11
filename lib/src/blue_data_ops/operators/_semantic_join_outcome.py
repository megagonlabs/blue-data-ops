from __future__ import annotations

from typing import Any, cast

from blue_data_ops.llm import resolve_llm_client
from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.semantic_join_operator import (
    SemanticJoinOperator,
    _estimate_join_cost,  # pyright: ignore[reportPrivateUsage]
    _evaluate_join_predicate_batch_strict,  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue, reportUnknownVariableType]
    _perform_semantic_join_optimized,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
)


class SemanticJoinOutcomeOperator(_OutcomeOperator, SemanticJoinOperator):
    """Require two groups and reject malformed batch or optimization responses."""

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        join_predicate = cast(str, attributes.get("join_predicate", ""))
        join_type = cast(str, attributes.get("join_type", "inner"))
        left_fields = cast(list[str], attributes.get("left_fields", []))
        right_fields = cast(list[str], attributes.get("right_fields", []))
        join_suffix = cast(list[str], attributes.get("join_suffix", []))
        keep_keys = cast(str, attributes.get("keep_keys", "left"))
        context = cast(str, attributes.get("context", ""))
        demonstrations = cast(str, attributes.get("demonstrations", ""))
        batch_size = cast(int, attributes.get("batch_size", 10))
        use_cache = cast(bool, attributes.get("use_cache", True))
        use_embedding_filter = cast(bool, attributes.get("use_embedding_filter", False))
        embedding_threshold = cast(float, attributes.get("embedding_threshold", 0.7))

        left_data, right_data = input_data
        estimate_cost = cast(bool, attributes.get("estimate_cost", True))
        if estimate_cost and left_data and right_data:
            cost_estimate = _estimate_join_cost(
                left_data,
                right_data,
                join_predicate,
                left_fields,
                right_fields,
                batch_size,
                context,
                demonstrations,
            )
            max_calls = attributes.get("max_llm_calls")
            if max_calls is not None and cost_estimate["max_llm_calls"] > max_calls:
                raise ValueError(
                    f"Semantic join aborted: {cost_estimate['max_llm_calls']:,} LLM "
                    f"calls exceeds limit of {max_calls:,}. Dataset: "
                    f"{cost_estimate['n_left']:,} × {cost_estimate['n_right']:,} = "
                    f"{cost_estimate['total_pairs']:,} pairs. Estimated cost: "
                    f"~${cost_estimate['max_cost_usd']:.2f}"
                )

        if not join_suffix:
            join_suffix = ["_left", "_right"]
        if len(join_suffix) != 2:
            return FunctionResult([], {})

        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
        merged.update(
            {
                "use_embedding_filter": use_embedding_filter,
                "embedding_threshold": embedding_threshold,
                "optimize_thresholds": attributes.get("optimize_thresholds", False),
                "recall_target": attributes.get("recall_target", 0.8),
                "precision_target": attributes.get("precision_target", 0.8),
                "sampling_percentage": attributes.get("sampling_percentage", 0.1),
                "failure_probability": attributes.get("failure_probability", 0.2),
                "batch_size": batch_size,
            }
        )
        result = cast(
            list[dict[str, Any]],
            cast(Any, _perform_semantic_join_optimized)(
                left_data,
                right_data,
                join_predicate,
                join_type,
                left_fields,
                right_fields,
                cast(str, attributes.get("left_suffix", "_left")),
                cast(str, attributes.get("right_suffix", "_right")),
                keep_keys,
                context,
                demonstrations,
                resolve_llm_client(merged),
                merged,
                batch_size,
                {} if use_cache else None,
                use_embedding_filter,
                embedding_threshold,
                _evaluate_join_predicate_batch_strict,
                True,
            ),
        )
        return FunctionResult([result], {})

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        validation = super()._validate_input(input_data, attributes, properties)
        if not validation.ok:
            return validation
        if len(input_data) != 2:
            return ValidationResult(False, "semantic join requires exactly two input groups")
        raw_join_suffix: object = attributes.get("join_suffix", [])
        if raw_join_suffix is not None:
            if not isinstance(raw_join_suffix, list):
                return ValidationResult(
                    False,
                    "join_suffix must be omitted, None, [], or a two-element list of strings",
                )
            join_suffix = cast(list[object], raw_join_suffix)
            if join_suffix and (
                len(join_suffix) != 2 or not all(isinstance(suffix, str) for suffix in join_suffix)
            ):
                return ValidationResult(
                    False,
                    "join_suffix must be omitted, None, [], or a two-element list of strings",
                )
        batch_size = attributes.get("batch_size", 10)
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            return ValidationResult(False, "batch_size must be a positive integer")
        return validation
