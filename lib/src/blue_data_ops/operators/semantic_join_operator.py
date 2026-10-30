from __future__ import annotations

import hashlib
import json
import logging
import warnings
from collections.abc import Callable
from importlib import import_module
from typing import Any, ClassVar, cast

from blue_data_ops.llm import LLMClient, prepare_llm_operator_properties, resolve_llm_client
from blue_data_ops.llm.client import validate_llm_caller_controls
from blue_data_ops.llm.errors import raise_reply_failure
from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    DataBundle,
    FunctionResult,
    Properties,
    Record,
    ValidationResult,
)

_LOGGER = logging.getLogger(__name__)

COST_PER_1K_TOKENS_USD = 0.04
CHARS_PER_TOKEN = 4
_sentence_transformer: Any | None = None

_JOIN_PROMPT = """## Task
You are given two data records and a natural language join predicate. Your job is to determine if these two records should be joined together based on the predicate.

## Left Record
${left_record}

## Right Record
${right_record}

## Join Predicate
${join_predicate}

## Context
${context}

## Demonstrations
${demonstrations}

## Output Requirements
- Return **only a boolean value**: true or false
- Return **true** if the two records should be joined based on the join predicate
- Return **false** if the two records should NOT be joined
- Be precise in your evaluation based on the natural language predicate
- Consider the semantic meaning of the predicate, not just exact text matching
- The predicate describes the relationship or condition that should exist between the records

## Additional Notes
- Use your understanding of natural language to interpret the join predicate
- Consider semantic similarity, not just exact matches
- Return only the boolean result, no explanations or additional text

---

### Output
"""

_BATCH_JOIN_PROMPT = """## Task
You are given multiple pairs of data records and a natural language join predicate. Your job is to determine which pairs should be joined together based on the predicate.

## Record Pairs
${pairs}

## Join Predicate
${join_predicate}

## Context
${context}

## Demonstrations
${demonstrations}

## Output Requirements
- Return a **JSON object** with keys "pair_1", "pair_2", ..., "pair_N" (where N is the number of pairs)
- Each value should be a boolean: true if the pair should be joined, false otherwise
- Example format: {"pair_1": true, "pair_2": false, "pair_3": true}
- Be precise in your evaluation based on the natural language predicate
- Consider the semantic meaning of the predicate, not just exact text matching
- The predicate describes the relationship or condition that should exist between records in each pair

## Additional Notes
- Use your understanding of natural language to interpret the join predicate
- Consider semantic similarity, not just exact matches
- Return only the JSON object, no explanations or additional text
- Ensure all pairs are evaluated (pair_1 through pair_${num_pairs})

---

### Output JSON Object
"""


def _numpy() -> Any:
    # NumPy belongs to the existing ml/vector extras. Resolve it only if an
    # embedding/threshold helper is reached, so ordinary LLM joins remain llm-only.
    return import_module("numpy")


def _estimate_join_cost(
    left_data: list[Record],
    right_data: list[Record],
    join_predicate: str,
    left_fields: list[str],
    right_fields: list[str],
    batch_size: int,
    context: str = "",
    demonstrations: str = "",
) -> dict[str, Any]:
    n_left = len(left_data)
    n_right = len(right_data)
    total_pairs = n_left * n_right
    max_llm_calls = (total_pairs + batch_size - 1) // batch_size
    sample_left = left_data[0] if left_data else {}
    sample_right = right_data[0] if right_data else {}
    if left_fields:
        sample_left = {key: value for key, value in sample_left.items() if key in left_fields}
    if right_fields:
        sample_right = {key: value for key, value in sample_right.items() if key in right_fields}
    prompt_overhead = 500
    predicate_tokens = len(join_predicate) // CHARS_PER_TOKEN
    context_tokens = len(context) // CHARS_PER_TOKEN
    demonstrations_tokens = len(demonstrations) // CHARS_PER_TOKEN
    tokens_per_pair = (
        len(json.dumps(sample_left)) + len(json.dumps(sample_right))
    ) // CHARS_PER_TOKEN
    tokens_per_batch = (
        prompt_overhead
        + predicate_tokens
        + context_tokens
        + demonstrations_tokens
        + (tokens_per_pair * batch_size)
    )
    max_total_tokens = max_llm_calls * tokens_per_batch
    max_cost_usd = (max_total_tokens / 1000) * COST_PER_1K_TOKENS_USD
    return {
        "n_left": n_left,
        "n_right": n_right,
        "total_pairs": total_pairs,
        "max_llm_calls": max_llm_calls,
        "tokens_per_batch": tokens_per_batch,
        "max_total_tokens": max_total_tokens,
        "max_cost_usd": max_cost_usd,
        "batch_size": batch_size,
    }


def _get_embedding_model(properties: dict[str, Any]) -> Any:
    global _sentence_transformer
    if _sentence_transformer is None:
        try:
            module = import_module("sentence_transformers")
        except ImportError:
            raise ImportError(
                "sentence-transformers package is required for embedding-based filtering. "
                "Install it with: pip install sentence-transformers"
            ) from None
        constructor = getattr(module, "SentenceTransformer")
        model_name = properties.get("embeddings_model", "paraphrase-MiniLM-L6-v2")
        _sentence_transformer = constructor(model_name)
    return _sentence_transformer


def _record_to_text(record: Record, fields: list[str]) -> str:
    if not fields:
        fields = list(record.keys())
    text_parts = [
        f"{field}: {record[field]}"
        for field in fields
        if field in record and record[field] is not None
    ]
    return " | ".join(text_parts)


def _generate_embeddings(records: list[Record], fields: list[str], model: Any) -> Any:
    np = _numpy()
    if not records:
        return np.array([])
    texts = [_record_to_text(record, fields) for record in records]
    embeddings = model.encode(texts, show_progress_bar=False, batch_size=32)
    return np.array(embeddings)


def _compute_cosine_similarity_matrix(left_embeddings: Any, right_embeddings: Any) -> Any:
    np = _numpy()
    if left_embeddings.size == 0 or right_embeddings.size == 0:
        return np.array([])
    left_norm = np.linalg.norm(left_embeddings, axis=1, keepdims=True)
    right_norm = np.linalg.norm(right_embeddings, axis=1, keepdims=True)
    left_norm = np.where(left_norm == 0, 1, left_norm)
    right_norm = np.where(right_norm == 0, 1, right_norm)
    return np.dot(left_embeddings / left_norm, (right_embeddings / right_norm).T)


def _filter_pairs_by_similarity(  # pyright: ignore[reportUnusedFunction]
    similarity_matrix: Any, threshold: float
) -> list[tuple[int, int]]:
    if similarity_matrix.size == 0:
        return []
    cosine_threshold = (threshold * 2.0) - 1.0
    candidate_pairs: list[tuple[int, int]] = []
    n_left, n_right = similarity_matrix.shape
    for left_index in range(n_left):
        for right_index in range(n_right):
            if similarity_matrix[left_index, right_index] >= cosine_threshold:
                candidate_pairs.append((left_index, right_index))
    return candidate_pairs


def _get_cache_key(
    left_record: Record,
    right_record: Record,
    join_predicate: str,
    left_fields: list[str],
    right_fields: list[str],
) -> str:
    left_filtered = {
        key: value for key, value in left_record.items() if not left_fields or key in left_fields
    }
    right_filtered = {
        key: value for key, value in right_record.items() if not right_fields or key in right_fields
    }
    key_data = {
        "left": json.dumps(left_filtered, sort_keys=True),
        "right": json.dumps(right_filtered, sort_keys=True),
        "predicate": join_predicate,
    }
    return hashlib.md5(json.dumps(key_data, sort_keys=True).encode()).hexdigest()


class _JoinResponseFormatError(ValueError):
    pass


def _request_join_predicate_batch(
    pairs: list[tuple[Record, Record, int, int]],
    join_predicate: str,
    left_fields: list[str],
    right_fields: list[str],
    context: str,
    demonstrations: str,
    client: LLMClient,
    properties: dict[str, Any],
) -> Any:
    pairs_data: list[dict[str, Any]] = []
    for left_record, right_record, left_index, right_index in pairs:
        left_filtered = {
            key: value
            for key, value in left_record.items()
            if not left_fields or key in left_fields
        }
        right_filtered = {
            key: value
            for key, value in right_record.items()
            if not right_fields or key in right_fields
        }
        pairs_data.append(
            {
                "left_idx": left_index,
                "right_idx": right_index,
                "left_record": left_filtered,
                "right_record": right_filtered,
            }
        )
    pairs_text = [
        f"Pair {index}:\n  Left Record (index {pair['left_idx']}): {json.dumps(pair['left_record'])}\n  Right Record (index {pair['right_idx']}): {json.dumps(pair['right_record'])}"
        for index, pair in enumerate(pairs_data, 1)
    ]
    batch_properties = properties.copy()
    batch_properties["input_template"] = _BATCH_JOIN_PROMPT
    # Blue's output_cast="bool" is a no-op, but the batch path still deletes the
    # key from its copy because it expects structured results. The caller dict keeps it.
    if "output_cast" in batch_properties:
        del batch_properties["output_cast"]
    return client.execute_api_call(
        {},
        properties=batch_properties,
        additional_data={
            "pairs": "\n\n".join(pairs_text),
            "join_predicate": join_predicate,
            "context": context,
            "demonstrations": demonstrations,
            "num_pairs": len(pairs),
        },
    )


def _evaluate_join_predicate_batch(
    pairs: list[tuple[Record, Record, int, int]],
    join_predicate: str,
    left_fields: list[str],
    right_fields: list[str],
    context: str,
    demonstrations: str,
    client: LLMClient,
    properties: dict[str, Any],
) -> dict[tuple[int, int], bool]:
    try:
        return _evaluate_join_predicate_batch_strict(
            pairs,
            join_predicate,
            left_fields,
            right_fields,
            context,
            demonstrations,
            client,
            properties,
            legacy_aliases=True,
        )
    except _JoinResponseFormatError:
        pass
    raise_reply_failure()


def _evaluate_join_predicate_batch_strict(  # pyright: ignore[reportUnusedFunction]
    pairs: list[tuple[Record, Record, int, int]],
    join_predicate: str,
    left_fields: list[str],
    right_fields: list[str],
    context: str,
    demonstrations: str,
    client: LLMClient,
    properties: dict[str, Any],
    *,
    legacy_aliases: bool = False,
) -> dict[tuple[int, int], bool]:
    if not pairs:
        return {}
    result = _request_join_predicate_batch(
        pairs,
        join_predicate,
        left_fields,
        right_fields,
        context,
        demonstrations,
        client,
        properties,
    )
    if isinstance(result, str):
        clean_result = result.strip()
        if clean_result.startswith("```json"):
            clean_result = clean_result[7:]
        if clean_result.startswith("```"):
            clean_result = clean_result[3:]
        if clean_result.endswith("```"):
            clean_result = clean_result[:-3]
        try:
            result = json.loads(clean_result.strip())
        except (json.JSONDecodeError, ValueError) as error:
            raise _JoinResponseFormatError("join response is not valid JSON") from error
    if not isinstance(result, dict):
        raise _JoinResponseFormatError("join response must be an object")
    response = cast(dict[Any, Any], result)
    expected_keys = {f"pair_{index}" for index in range(1, len(pairs) + 1)}
    if set(response) != expected_keys:
        raise _JoinResponseFormatError("join response has invalid pair results")
    decisions: dict[str, bool] = {}
    for key, value in response.items():
        if type(value) is bool:
            decisions[key] = value
        elif legacy_aliases and isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "1", "match", "join"}:
                decisions[key] = True
            elif normalized in {"false", "no", "0", "exclude"}:
                decisions[key] = False
            else:
                raise _JoinResponseFormatError("join response has invalid pair results")
        else:
            raise _JoinResponseFormatError("join response has invalid pair results")
    return {
        (left_index, right_index): decisions[f"pair_{index}"]
        for index, (_, _, left_index, right_index) in enumerate(pairs, 1)
    }


_JoinBatchEvaluator = Callable[
    [
        list[tuple[Record, Record, int, int]],
        str,
        list[str],
        list[str],
        str,
        str,
        LLMClient,
        dict[str, Any],
    ],
    dict[tuple[int, int], bool],
]


def _merge_records(
    left_record: Record,
    right_record: Record,
    field_conflicts: set[str],
    left_suffix: str,
    right_suffix: str,
    keep_keys: str,
    right_fields: list[str] | None = None,
) -> Record:
    merged: Record = {}
    for field, value in left_record.items():
        merged[f"{field}{left_suffix}" if field in field_conflicts else field] = value
    for field, value in right_record.items():
        if keep_keys == "left" and right_fields and field in right_fields:
            continue
        if field in field_conflicts:
            merged[f"{field}{right_suffix}"] = value
        elif field not in merged:
            merged[field] = value
        else:
            merged[f"{field}{right_suffix}"] = value
    return merged


def _semantic_inner_join_from_matches(
    left_data: list[Record],
    right_data: list[Record],
    match_results: dict[tuple[int, int], bool],
    field_conflicts: set[str],
    left_suffix: str,
    right_suffix: str,
    keep_keys: str,
    right_fields: list[str] | None = None,
) -> list[Record]:
    return [
        _merge_records(
            left_data[left_index],
            right_data[right_index],
            field_conflicts,
            left_suffix,
            right_suffix,
            keep_keys,
            right_fields,
        )
        for (left_index, right_index), should_join in match_results.items()
        if should_join
    ]


def _semantic_left_join_from_matches(
    left_data: list[Record],
    right_data: list[Record],
    match_results: dict[tuple[int, int], bool],
    field_conflicts: set[str],
    left_suffix: str,
    right_suffix: str,
    keep_keys: str,
    right_fields: list[str] | None = None,
) -> list[Record]:
    result: list[Record] = []
    matched_left_indices: set[int] = set()
    for (left_index, right_index), should_join in match_results.items():
        if should_join:
            matched_left_indices.add(left_index)
            result.append(
                _merge_records(
                    left_data[left_index],
                    right_data[right_index],
                    field_conflicts,
                    left_suffix,
                    right_suffix,
                    keep_keys,
                    right_fields,
                )
            )
    for left_index in range(len(left_data)):
        if left_index not in matched_left_indices:
            result.append(
                _merge_records(
                    left_data[left_index],
                    {},
                    field_conflicts,
                    left_suffix,
                    right_suffix,
                    keep_keys,
                    right_fields,
                )
            )
    return result


def _semantic_right_join_from_matches(
    left_data: list[Record],
    right_data: list[Record],
    match_results: dict[tuple[int, int], bool],
    field_conflicts: set[str],
    left_suffix: str,
    right_suffix: str,
    keep_keys: str,
    right_fields: list[str] | None = None,
) -> list[Record]:
    result: list[Record] = []
    matched_right_indices: set[int] = set()
    for (left_index, right_index), should_join in match_results.items():
        if should_join:
            matched_right_indices.add(right_index)
            result.append(
                _merge_records(
                    left_data[left_index],
                    right_data[right_index],
                    field_conflicts,
                    left_suffix,
                    right_suffix,
                    keep_keys,
                    right_fields,
                )
            )
    for right_index in range(len(right_data)):
        if right_index not in matched_right_indices:
            result.append(
                _merge_records(
                    {},
                    right_data[right_index],
                    field_conflicts,
                    left_suffix,
                    right_suffix,
                    keep_keys,
                    right_fields,
                )
            )
    return result


def _semantic_outer_join_from_matches(
    left_data: list[Record],
    right_data: list[Record],
    match_results: dict[tuple[int, int], bool],
    field_conflicts: set[str],
    left_suffix: str,
    right_suffix: str,
    keep_keys: str,
    right_fields: list[str] | None = None,
) -> list[Record]:
    result: list[Record] = []
    matched_left_indices: set[int] = set()
    matched_right_indices: set[int] = set()
    for (left_index, right_index), should_join in match_results.items():
        if should_join:
            matched_left_indices.add(left_index)
            matched_right_indices.add(right_index)
            result.append(
                _merge_records(
                    left_data[left_index],
                    right_data[right_index],
                    field_conflicts,
                    left_suffix,
                    right_suffix,
                    keep_keys,
                    right_fields,
                )
            )
    for left_index in range(len(left_data)):
        if left_index not in matched_left_indices:
            result.append(
                _merge_records(
                    left_data[left_index],
                    {},
                    field_conflicts,
                    left_suffix,
                    right_suffix,
                    keep_keys,
                    right_fields,
                )
            )
    for right_index in range(len(right_data)):
        if right_index not in matched_right_indices:
            result.append(
                _merge_records(
                    {},
                    right_data[right_index],
                    field_conflicts,
                    left_suffix,
                    right_suffix,
                    keep_keys,
                    right_fields,
                )
            )
    return result


def _importance_sampling(
    scores: list[float],
    sampling_percentage: float = 0.1,
    random_seed: int = 42,
    max_sample_range: int = 5000,
) -> tuple[list[int], Any]:
    del max_sample_range
    np = _numpy()
    if not scores:
        return [], np.array([])
    np.random.seed(random_seed)
    scores_array = np.array(scores)
    weights = np.sqrt(np.maximum(scores_array, 0))
    sum_weights = np.sum(weights)
    if sum_weights > 0:
        weights = 0.5 * weights / sum_weights + 0.5 * (1 / len(scores))
    else:
        weights = np.ones(len(scores)) / len(scores)
    weights = weights / np.sum(weights)
    sample_size = max(5, int(sampling_percentage * len(scores)))
    indices = np.arange(len(scores))
    sample_indices = np.random.choice(indices, size=sample_size, replace=False, p=weights)
    correction_factors = (1 / len(scores)) / weights[sample_indices]
    return list(sample_indices), correction_factors


def _params_UB(mean: float, std_dev: float, sample_size: int, delta: float) -> float:
    if sample_size == 0:
        return 1.0
    np = _numpy()
    return float(mean + (std_dev / (sample_size**0.5)) * ((2 * np.log(1 / delta)) ** 0.5))


def _params_LB(mean: float, std_dev: float, sample_size: int, delta: float) -> float:
    if sample_size == 0:
        return 0.0
    np = _numpy()
    return float(mean - (std_dev / (sample_size**0.5)) * ((2 * np.log(1 / delta)) ** 0.5))


def _calculate_recall(
    pos_threshold: float,
    neg_threshold: float,
    sorted_pairs: list[tuple[float, bool, float]],
) -> float:
    total_correct = sum(pair[1] * pair[2] for pair in sorted_pairs)
    if total_correct <= 0:
        return 1.0
    found_correct = sum(pair[1] * pair[2] for pair in sorted_pairs if pair[0] >= pos_threshold)
    found_correct += sum(
        pair[1] * pair[2]
        for pair in sorted_pairs
        if pair[0] < pos_threshold and pair[0] > neg_threshold
    )
    return found_correct / total_correct


def _calculate_precision(  # pyright: ignore[reportUnusedFunction]
    pos_threshold: float,
    neg_threshold: float,
    sorted_pairs: list[tuple[float, bool, float]],
) -> float:
    del neg_threshold
    accepted = [pair for pair in sorted_pairs if pair[0] >= pos_threshold]
    if not accepted:
        return 1.0
    predicted_positives = sum(pair[2] for pair in accepted)
    true_positives = sum(pair[1] * pair[2] for pair in accepted)
    if predicted_positives == 0:
        return 1.0
    return true_positives / predicted_positives


def _calculate_tau_neg(
    sorted_pairs: list[tuple[float, bool, float]],
    tau_pos: float,
    recall_target: float,
) -> float:
    best_tau_neg = 0.0
    candidates = sorted({pair[0] for pair in sorted_pairs})
    for tau_neg in reversed(candidates):
        if tau_neg >= tau_pos:
            continue
        if _calculate_recall(tau_pos, tau_neg, sorted_pairs) >= recall_target:
            best_tau_neg = tau_neg
            break
    return best_tau_neg


def _learn_thresholds(
    scores: list[float],
    labels: list[bool],
    correction_factors: Any,
    recall_target: float = 0.95,
    precision_target: float = 0.99,
    failure_probability: float = 0.05,
) -> tuple[float, float, int]:
    np = _numpy()
    sorted_pairs = sorted(
        zip(scores, labels, correction_factors), key=lambda item: item[0], reverse=True
    )
    sample_size = len(sorted_pairs)
    best_tau_pos = 1.0
    best_tau_neg = _calculate_tau_neg(sorted_pairs, best_tau_pos, recall_target)
    z1 = [int(pair[1]) * pair[2] for pair in sorted_pairs if pair[0] >= best_tau_neg]
    z2 = [int(pair[1]) * pair[2] for pair in sorted_pairs if pair[0] < best_tau_neg]
    mean_z1 = float(np.mean(z1)) if z1 else 0.0
    std_z1 = float(np.std(z1)) if z1 else 0.0
    mean_z2 = float(np.mean(z2)) if z2 else 0.0
    std_z2 = float(np.std(z2)) if z2 else 0.0
    ub_z1 = _params_UB(mean_z1, std_z1, sample_size, failure_probability / 2)
    lb_z2 = _params_LB(mean_z2, std_z2, sample_size, failure_probability / 2)
    corrected_recall = 1.0 if ub_z1 + lb_z2 == 0 else ub_z1 / (ub_z1 + lb_z2)
    corrected_recall = min(1.0, corrected_recall)
    best_tau_neg = _calculate_tau_neg(sorted_pairs, best_tau_pos, corrected_recall)
    candidate_thresholds = [1.0]
    for threshold in sorted({pair[0] for pair in sorted_pairs}, reverse=True):
        if threshold <= best_tau_neg:
            break
        samples = [int(pair[1]) for pair in sorted_pairs if pair[0] >= threshold]
        if not samples:
            continue
        precision_lb = _params_LB(
            np.mean(samples),
            np.std(samples),
            len(samples),
            failure_probability / len(sorted_pairs),
        )
        if precision_lb >= precision_target:
            candidate_thresholds.append(threshold)
    best_tau_pos = min(candidate_thresholds)
    if best_tau_pos < best_tau_neg:
        best_tau_pos = best_tau_neg
        best_tau_pos = 1.0
    return best_tau_pos, best_tau_neg, len(sorted_pairs)


def _perform_semantic_join_optimized(
    left_data: list[Record],
    right_data: list[Record],
    join_predicate: str,
    join_type: str,
    left_fields: list[str],
    right_fields: list[str],
    left_suffix: str,
    right_suffix: str,
    keep_keys: str,
    context: str,
    demonstrations: str,
    client: LLMClient,
    properties: dict[str, Any],
    batch_size: int,
    cache: dict[str, bool] | None,
    use_embedding_filter: bool,
    embedding_threshold: float,
    response_evaluator: _JoinBatchEvaluator = _evaluate_join_predicate_batch,
    propagate_optimization_errors: bool = False,
) -> list[Record]:
    del use_embedding_filter
    if not join_predicate or not join_predicate.strip():
        join_predicate = (
            "Determine if the two records are semantically equivalent based on the provided fields."
        )
    if not left_fields:
        left_fields = list(left_data[0].keys()) if left_data else []
    if not right_fields:
        right_fields = list(right_data[0].keys()) if right_data else []

    candidate_pairs: list[tuple[int, int]] = []
    auto_matches: list[tuple[int, int]] = []
    use_embedding = properties.get("use_embedding_filter", False)
    optimize = properties.get("optimize_thresholds", False)
    if optimize:
        use_embedding = True
    evaluating_sample = False
    if use_embedding:
        try:
            embedding_model = _get_embedding_model(properties)
            left_embeddings = _generate_embeddings(left_data, left_fields, embedding_model)
            right_embeddings = _generate_embeddings(right_data, right_fields, embedding_model)
            similarity_matrix = _compute_cosine_similarity_matrix(left_embeddings, right_embeddings)
            t_pos = 1.0
            t_neg = embedding_threshold
            if optimize:
                try:
                    all_scores: list[float] = []
                    flat_index_map: list[tuple[int, int]] = []
                    rows, columns = similarity_matrix.shape
                    for row in range(rows):
                        for column in range(columns):
                            all_scores.append(float(similarity_matrix[row][column]))
                            flat_index_map.append((row, column))
                    sample_indices, correction_factors = _importance_sampling(
                        all_scores, properties.get("sampling_percentage", 0.1)
                    )
                    sample_pairs = [
                        (
                            left_data[flat_index_map[index][0]],
                            right_data[flat_index_map[index][1]],
                            flat_index_map[index][0],
                            flat_index_map[index][1],
                        )
                        for index in sample_indices
                    ]
                    evaluating_sample = True
                    sample_results = response_evaluator(
                        sample_pairs,
                        join_predicate,
                        left_fields,
                        right_fields,
                        context,
                        demonstrations,
                        client,
                        properties,
                    )
                    evaluating_sample = False
                    labels: list[bool] = []
                    sample_scores: list[float] = []
                    for index in sample_indices:
                        left_index, right_index = flat_index_map[index]
                        sample_scores.append(all_scores[index])
                        labels.append(sample_results.get((left_index, right_index), False))
                    t_pos, t_neg, _ = _learn_thresholds(
                        sample_scores,
                        labels,
                        correction_factors,
                        properties.get("recall_target", 0.95),
                        properties.get("precision_target", 0.99),
                        properties.get("failure_probability", 0.05),
                    )
                except Exception:
                    if propagate_optimization_errors or evaluating_sample:
                        raise
                    warnings.warn(
                        "Cascade optimization failed; using the static threshold.",
                        UserWarning,
                    )
                    t_neg = embedding_threshold
                    t_pos = 1.0
            rows, columns = similarity_matrix.shape
            for row in range(rows):
                for column in range(columns):
                    score = similarity_matrix[row][column]
                    if score >= t_pos:
                        auto_matches.append((row, column))
                    elif score > t_neg:
                        candidate_pairs.append((row, column))
        except Exception:
            if propagate_optimization_errors or evaluating_sample:
                raise
            warnings.warn(
                "Embedding optimization failed; falling back to all pairs.",
                UserWarning,
            )
            auto_matches.clear()
            candidate_pairs = [
                (left_index, right_index)
                for left_index in range(len(left_data))
                for right_index in range(len(right_data))
            ]

    if not candidate_pairs and not (optimize and auto_matches):
        if not use_embedding:
            candidate_pairs = [
                (left_index, right_index)
                for left_index in range(len(left_data))
                for right_index in range(len(right_data))
            ]

    left_all_fields = {field for record in left_data for field in record}
    right_all_fields = {field for record in right_data for field in record}
    field_conflicts = left_all_fields.intersection(right_all_fields)
    if keep_keys != "both" and right_fields:
        field_conflicts.difference_update(right_fields)

    match_results: dict[tuple[int, int], bool] = {}
    if auto_matches:
        for left_index, right_index in auto_matches:
            match_results[(left_index, right_index)] = True

    batches: list[list[tuple[Record, Record, int, int]]] = []
    current_batch: list[tuple[Record, Record, int, int]] = []
    for left_index, right_index in candidate_pairs:
        if (left_index, right_index) in match_results:
            continue
        current_batch.append(
            (left_data[left_index], right_data[right_index], left_index, right_index)
        )
        if len(current_batch) >= batch_size:
            batches.append(current_batch)
            current_batch = []
    if current_batch:
        batches.append(current_batch)

    for batch in batches:
        uncached_pairs: list[tuple[Record, Record, int, int]] = []
        for left_record, right_record, left_index, right_index in batch:
            if cache is not None:
                cache_key = _get_cache_key(
                    left_record,
                    right_record,
                    join_predicate,
                    left_fields,
                    right_fields,
                )
                if cache_key in cache:
                    match_results[(left_index, right_index)] = cache[cache_key]
                else:
                    uncached_pairs.append((left_record, right_record, left_index, right_index))
            else:
                uncached_pairs.append((left_record, right_record, left_index, right_index))
        if uncached_pairs:
            batch_results = response_evaluator(
                uncached_pairs,
                join_predicate,
                left_fields,
                right_fields,
                context,
                demonstrations,
                client,
                properties,
            )
            for (left_index, right_index), result in batch_results.items():
                match_results[(left_index, right_index)] = result
                if cache is not None:
                    cache_key = _get_cache_key(
                        left_data[left_index],
                        right_data[right_index],
                        join_predicate,
                        left_fields,
                        right_fields,
                    )
                    cache[cache_key] = result

    join_functions = {
        "inner": _semantic_inner_join_from_matches,
        "left": _semantic_left_join_from_matches,
        "right": _semantic_right_join_from_matches,
        "outer": _semantic_outer_join_from_matches,
    }
    function = join_functions.get(join_type)
    if function is None:
        return []
    return function(
        left_data,
        right_data,
        match_results,
        field_conflicts,
        left_suffix,
        right_suffix,
        keep_keys,
        right_fields,
    )


class SemanticJoinOperator(Operator):
    """Join two datasets under a natural-language predicate.

    Retained ``@1.0.0`` and ``@2.0.0`` require complete pair objects with booleans
    or trimmed, case-insensitive strings: true/yes/1/match/join and false/no/0/exclude.
    Malformed replies raise through ``apply()`` and ``invoke()``; ``run()``
    contains failures in ``exec_meta.errors``. Valid negative and empty replies remain valid.
    Embedding failures evaluate all Cartesian pairs: ceil(N*M/batch) calls.
    A failure after optimization sampling can add the sample call to that fallback.
    The estimate_cost/max_llm_calls check guards an estimate, not runtime call counts.
    """

    name: ClassVar[str] = "semantic_join"
    description: ClassVar[str] = (
        "Joins two datasets based on natural language join predicate using LLM models"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "left_fields": AttributeSpec(
            type="list[str]",
            description="Fields from left dataset to consider",
            required=True,
        ),
        "right_fields": AttributeSpec(
            type="list[str]",
            description="Fields from right dataset to consider",
            required=True,
        ),
        "join_predicate": AttributeSpec(
            type="str",
            description="Natural language description of when records should be joined",
            default="",
        ),
        "join_type": AttributeSpec(
            type="str",
            description="Type of join: 'inner', 'left', 'right', 'outer'",
            default="inner",
        ),
        "left_suffix": AttributeSpec(
            type="str",
            description="Suffix for field name conflicts from left dataset",
            default="_left",
        ),
        "right_suffix": AttributeSpec(
            type="str",
            description="Suffix for field name conflicts from right dataset",
            default="_right",
        ),
        "keep_keys": AttributeSpec(
            type="str",
            description="'left' to keep left keys only, 'both' to keep both",
            default="left",
        ),
        "context": AttributeSpec(
            type="str",
            description=("Optional context to provide domain knowledge or additional instructions"),
            default="",
        ),
        "demonstrations": AttributeSpec(
            type="str",
            description="Optional demonstrations to help in-context learning",
            default="",
        ),
        "batch_size": AttributeSpec(
            type="int",
            description="Number of record pairs to evaluate per LLM call (batch processing)",
            default=10,
        ),
        "use_cache": AttributeSpec(
            type="bool",
            description="Enable result caching to avoid re-evaluating similar pairs",
            default=True,
        ),
        "use_embedding_filter": AttributeSpec(
            type="bool",
            description=(
                "Use embedding pre-filtering to reduce candidate pairs (requires "
                "sentence-transformers package)"
            ),
            default=False,
        ),
        "embedding_threshold": AttributeSpec(
            type="float",
            description=(
                "Similarity threshold for embedding pre-filtering (0.0-1.0, maps to "
                "cosine similarity [-1,1])"
            ),
            default=0.7,
        ),
        "max_llm_calls": AttributeSpec(
            type="int",
            description=(
                "Maximum allowed LLM calls (None = no limit). Prevents accidental "
                "expensive operations."
            ),
            default=1000,
        ),
        "estimate_cost": AttributeSpec(
            type="bool",
            description="Log a cost estimate at INFO level before execution",
            default=True,
        ),
        "optimize_thresholds": AttributeSpec(
            type="bool",
            description="Enable dynamic threshold learning (Cascade Optimization)",
            default=False,
        ),
        "recall_target": AttributeSpec(
            type="float",
            description="Target recall for optimization (0.0-1.0)",
            default=0.8,
        ),
        "precision_target": AttributeSpec(
            type="float",
            description="Target precision for auto-acceptance (0.0-1.0)",
            default=0.8,
        ),
        "sampling_percentage": AttributeSpec(
            type="float",
            description="Fraction of data to sample for learning (0.0-1.0)",
            default=0.1,
        ),
        "failure_probability": AttributeSpec(
            type="float",
            description="Statistical failure probability (delta) for threshold learning",
            default=0.2,
        ),
    }
    JOIN_PROMPT: ClassVar[str] = _JOIN_PROMPT
    BATCH_JOIN_PROMPT: ClassVar[str] = _BATCH_JOIN_PROMPT
    DEFAULT_PROPERTIES: ClassVar[dict[str, Any]] = {
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-6-luna",
        "openai.stream": False,
        "openai.max_tokens": 1024,
        "openai.temperature": 0,
        "input_json": '[{"role": "user"}]',
        "input_context": "$[0]",
        "input_context_field": "content",
        "input_field": "messages",
        "input_template": _JOIN_PROMPT,
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
        "output_cast": "bool",
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
        if not input_data or len(input_data) < 2:
            return FunctionResult([], {})

        left_data = input_data[0]
        right_data = input_data[1]
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
            _LOGGER.info(
                "Semantic join estimate: %s pairs; LLM calls: up to %s; cost: ~$%.2f",
                f"{cost_estimate['total_pairs']:,}",
                f"{cost_estimate['max_llm_calls']:,}",
                cost_estimate["max_cost_usd"],
            )
        if not join_suffix:
            join_suffix = (
                ["_left", "_right"]
                if len(input_data) == 2
                else [f"_ds{index}" for index in range(len(input_data))]
            )
        if len(join_suffix) != len(input_data):
            return FunctionResult([], {})

        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
        merged = prepare_llm_operator_properties(merged, self.DEFAULT_PROPERTIES, properties)
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
        client = resolve_llm_client(merged)
        cache: dict[str, bool] | None = {} if use_cache else None
        result = _perform_semantic_join_optimized(
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
            client,
            merged,
            batch_size,
            cache,
            use_embedding_filter,
            embedding_threshold,
        )
        return FunctionResult([result], {})

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
        reason = "supply valid semantic join attributes"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, reason)
        join_predicate = attributes.get("join_predicate", "")
        join_type = attributes.get("join_type", "inner")
        left_fields = attributes.get("left_fields", [])
        right_fields = attributes.get("right_fields", [])
        keep_keys = attributes.get("keep_keys", "left")
        if join_predicate and not isinstance(join_predicate, str):
            return ValidationResult(False, reason)
        if join_type not in ["inner", "left", "right", "outer"]:
            return ValidationResult(False, reason)
        if left_fields is None or not isinstance(left_fields, list):
            return ValidationResult(False, reason)
        if right_fields is None or not isinstance(right_fields, list):
            return ValidationResult(False, reason)
        if attributes.get("left_suffix") and not isinstance(attributes.get("left_suffix"), str):
            return ValidationResult(False, reason)
        if attributes.get("right_suffix") and not isinstance(attributes.get("right_suffix"), str):
            return ValidationResult(False, reason)
        valid = keep_keys in ["left", "both"]
        return ValidationResult(valid, None if valid else reason)


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when two datasets must be joined by a natural-language relationship rather than "
        "exact keys."
    ),
    tags=(
        "domain-semantic",
        "flow-combine",
        "accepts-data",
        "produces-data",
        "capability-embedding-filter",
        "capability-join",
        "requires-llm",
    ),
)
