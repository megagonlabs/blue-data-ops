from __future__ import annotations

from collections.abc import Callable, Sequence
from importlib import import_module
from typing import Any, ClassVar, Protocol, cast

from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    Data,
    DataBundle,
    FunctionResult,
    Properties,
    Record,
)
from blue_data_ops.operators.vector_similarity_operator import VectorSimilarityOperator

_DEFAULT_MODEL = "all-MiniLM-L6-v2"


class _Embedder(Protocol):
    def encode(
        self,
        sentences: Sequence[str],
        batch_size: int = 32,
        normalize_embeddings: bool = False,
    ) -> Any: ...


def _embedder_constructor() -> Callable[[str], _Embedder]:
    # The vector extra is optional; resolve it only when an embedding path is reached.
    module = import_module("sentence_transformers")
    return cast(Callable[[str], _Embedder], getattr(module, "SentenceTransformer"))


class VectorSimilarityOutcomeOperator(_OutcomeOperator, VectorSimilarityOperator):
    """Compare two record lists using existing or generated embeddings."""

    name: ClassVar[str] = "vector_similarity"
    description: ClassVar[str] = "Compute similarity between two lists of records using embeddings."
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "model_ref": AttributeSpec(
            type="str",
            description="Reference to the embedding model",
            default=_DEFAULT_MODEL,
        ),
        "fields": AttributeSpec(
            type="list[str]",
            description="Fields to use when text embedding is needed",
        ),
        "metric": AttributeSpec(
            type="str",
            description="Similarity metric",
            default="cosine",
        ),
        "comparison_mode": AttributeSpec(
            type="str",
            description="Comparison mode: cartesian or pairwise",
            default="cartesian",
        ),
        "on_missing_embedding": AttributeSpec(
            type="str",
            description="How to handle missing embeddings",
            default="raise",
        ),
        "on_missing_fields": AttributeSpec(
            type="str",
            description="How to handle missing fields: raise | use_empty",
            default="raise",
        ),
        "add_meta_data": AttributeSpec(
            type="bool",
            description="Add similarity metadata",
            default=False,
        ),
        "threshold": AttributeSpec(
            type="float",
            description="Threshold for passed flag",
        ),
        "normalize": AttributeSpec(
            type="bool",
            description="Normalize embeddings",
            default=False,
        ),
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
        model_ref = attributes.get("model_ref")
        # Omitted fields are valid when both inputs already contain embeddings.
        fields_value: object = attributes.get("fields")
        metric = attributes.get("metric", "cosine")
        add_meta_data = cast(bool, attributes.get("add_meta_data", False))
        threshold = attributes.get("threshold")
        normalize = cast(bool, attributes.get("normalize", False))
        comparison_mode = attributes.get("comparison_mode", "cartesian")
        on_missing_embedding = attributes.get("on_missing_embedding", "raise")
        on_missing_fields = attributes.get("on_missing_fields", "raise")

        if len(input_data) != 2:
            raise ValueError("vector_similarity requires exactly two input lists.")
        list1 = input_data[0]
        list2 = input_data[1]
        if comparison_mode not in {"cartesian", "pairwise"}:
            raise ValueError("comparison_mode must be one of: cartesian, pairwise")
        if on_missing_embedding not in {"raise", "embed_missing"}:
            raise ValueError("on_missing_embedding must be one of: raise, embed_missing")
        if on_missing_fields not in {"raise", "use_empty"}:
            raise ValueError("on_missing_fields must be one of: raise, use_empty")
        if metric not in {"cosine", "dot", "l2"}:
            raise ValueError(f"Unsupported metric: {metric}")
        if comparison_mode == "pairwise" and len(list1) != len(list2):
            raise ValueError(
                "pairwise comparison requires both input lists to have the same length."
            )
        if fields_value is not None and (
            not isinstance(fields_value, list)
            or len(cast(list[object], fields_value)) != 2
            or not all(isinstance(field, str) for field in cast(list[object], fields_value))
        ):
            raise ValueError("fields must be a list of exactly two field names when provided.")
        fields = cast(list[str] | None, fields_value)

        if (comparison_mode == "cartesian" and (not list1 or not list2)) or (
            comparison_mode == "pairwise" and not list1 and not list2
        ):
            return FunctionResult([[]], {})

        # Defer NumPy loading until after structural and policy checks.
        np = cast(Any, import_module("numpy"))

        field1 = fields[0] if fields else None
        field2 = fields[1] if fields else None
        embedder_name = cast(str, model_ref if model_ref else _DEFAULT_MODEL)
        embedder: _Embedder | None = None

        def ensure_embedder() -> _Embedder:
            nonlocal embedder
            if embedder is None:
                embedder = _embedder_constructor()(embedder_name)
            return embedder

        def extract_embedding(record: Record, index: int, side: str) -> Any | None:
            embedding = record.get("embedding")
            if embedding is None:
                return None
            if not isinstance(embedding, (list, tuple, np.ndarray)):
                raise ValueError(f"{side} record {index} has non-sequence embedding")
            array = np.asarray(embedding, dtype=float)
            if array.ndim != 1:
                raise ValueError(f"{side} record {index} embedding must be 1-dimensional")
            return array

        def normalize_matrix(matrix: Any) -> Any:
            return matrix / np.clip(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12, None)

        def build_text(record: Record, field_name: str | None, index: int, side: str) -> str:
            if field_name is None:
                raise ValueError("fields are required when text embedding is needed.")
            if field_name not in record:
                if on_missing_fields == "raise":
                    raise ValueError(
                        f"Missing field '{field_name}' in {side} record {index}: {record}"
                    )
                return ""
            value = str(record.get(field_name, ""))
            if on_missing_fields == "raise" and value == "":
                raise ValueError(
                    f"Field '{field_name}' is empty in {side} record {index}: {record}"
                )
            return value

        def prepare_embeddings(
            records: Data, field_name: str | None, side: str
        ) -> tuple[Any, bool]:
            embedding_list: list[Any | None] = [
                extract_embedding(record, index, side) for index, record in enumerate(records)
            ]
            has_missing = any(embedding is None for embedding in embedding_list)
            if has_missing and on_missing_embedding == "raise":
                raise ValueError(
                    f"Missing embedding in {side} records and on_missing_embedding='raise'."
                )
            if not has_missing:
                dimensions = {
                    embedding.shape[0] for embedding in embedding_list if embedding is not None
                }
                if len(dimensions) != 1:
                    raise ValueError(f"Inconsistent embedding dimensions within {side} list")
                matrix = np.vstack(embedding_list)
                return (normalize_matrix(matrix) if normalize else matrix), True

            texts_to_embed: list[str] = []
            missing_indexes: list[int] = []
            for index, record in enumerate(records):
                if embedding_list[index] is None:
                    texts_to_embed.append(build_text(record, field_name, index, side))
                    missing_indexes.append(index)

            computed = np.asarray(
                ensure_embedder().encode(texts_to_embed, normalize_embeddings=normalize),
                dtype=float,
            )
            for computed_index, index in enumerate(missing_indexes):
                embedding_list[index] = computed[computed_index]

            dimensions = {
                embedding.shape[0] for embedding in embedding_list if embedding is not None
            }
            if len(dimensions) != 1:
                raise ValueError(
                    f"Embedding dimension mismatch within {side} list after filling "
                    "missing embeddings"
                )
            matrix = np.vstack(embedding_list)
            return (normalize_matrix(matrix) if normalize else matrix), False

        embeddings1, used_existing_left = prepare_embeddings(list1, field1, "left")
        embeddings2, used_existing_right = prepare_embeddings(list2, field2, "right")
        use_existing = used_existing_left and used_existing_right
        if embeddings1.shape[1] != embeddings2.shape[1]:
            raise ValueError(
                "Embedding dimension mismatch between lists: "
                f"{embeddings1.shape[1]} vs {embeddings2.shape[1]}"
            )

        pair_indexes = (
            [(index, index) for index in range(len(list1))]
            if comparison_mode == "pairwise"
            else [
                (left_index, right_index)
                for left_index in range(len(list1))
                for right_index in range(len(list2))
            ]
        )
        results: Data = []
        for left_index, right_index in pair_indexes:
            if metric == "cosine":
                if normalize:
                    score = float(np.dot(embeddings1[left_index], embeddings2[right_index]))
                else:
                    left_norm = np.linalg.norm(embeddings1[left_index])
                    right_norm = np.linalg.norm(embeddings2[right_index])
                    if left_norm == 0.0 or right_norm == 0.0:
                        score = 0.0
                    else:
                        score = float(
                            np.dot(embeddings1[left_index], embeddings2[right_index])
                            / (left_norm * right_norm)
                        )
            elif metric == "dot":
                score = float(np.dot(embeddings1[left_index], embeddings2[right_index]))
            else:
                score = -float(np.linalg.norm(embeddings1[left_index] - embeddings2[right_index]))

            left_id = list1[left_index].get("id", f"left_{left_index}")
            right_id = list2[right_index].get("id", f"right_{right_index}")
            result: Record = {
                "id": f"{left_id}_{right_id}",
                "left_id": left_id,
                "right_id": right_id,
                "similarity.score": score,
            }
            if add_meta_data:
                result["similarity.metric"] = metric
                result["similarity.comparison_mode"] = comparison_mode
                if not use_existing:
                    result["similarity.model"] = model_ref if model_ref else _DEFAULT_MODEL
            if threshold is not None:
                result["similarity.passed"] = score >= threshold
                result["similarity.threshold"] = threshold
            results.append(result)
        return FunctionResult([results], {})


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when records from two groups must be compared by embedding-based similarity in "
        "pairwise or cartesian mode."
    ),
    tags=(
        "domain-vector",
        "flow-combine",
        "accepts-data",
        "produces-data",
        "capability-similarity",
        "requires-vector",
    ),
)
