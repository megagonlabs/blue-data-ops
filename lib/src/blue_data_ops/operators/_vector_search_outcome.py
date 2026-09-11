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
    ValidationResult,
)
from blue_data_ops.operators.vector_search_operator import VectorSearchOperator

_DEFAULT_MODEL = "all-MiniLM-L6-v2"
_SUPPORTED_MODELS = {_DEFAULT_MODEL, "paraphrase-MiniLM-L6-v2"}


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


class VectorSearchOutcomeOperator(_OutcomeOperator, VectorSearchOperator):
    """Rank candidate records by their similarity to a text or vector query."""

    name: ClassVar[str] = "vector_search"
    description: ClassVar[str] = (
        "Perform semantic search within each dataset using text or vector queries."
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "query": AttributeSpec(
            type="str | dict",
            description="Query text or query embedding object",
            required=True,
        ),
        "search_fields": AttributeSpec(
            type="list[str]",
            description="Keys containing searchable text",
        ),
        "model_ref": AttributeSpec(
            type="str",
            description="Reference to the embedding model",
            default=_DEFAULT_MODEL,
        ),
        "metric": AttributeSpec(
            type="str",
            description="Similarity metric: cosine | dot | l2",
            default="cosine",
        ),
        "add_meta_data": AttributeSpec(
            type="bool",
            description="Add search.metric and search.model",
            default=False,
        ),
        "on_missing_embedding": AttributeSpec(
            type="str",
            description=("How to handle missing candidate embeddings: embed_missing | raise"),
            default="embed_missing",
        ),
        "on_missing_fields": AttributeSpec(
            type="str",
            description="How to handle missing search fields: raise | use_empty",
            default="raise",
        ),
        "top_k": AttributeSpec(
            type="int",
            description="Maximum number of results per dataset",
            default=10,
        ),
        "min_score": AttributeSpec(
            type="float",
            description="Minimum score threshold",
        ),
        "normalize": AttributeSpec(
            type="bool",
            description="L2-normalize embeddings before scoring",
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

    def _resolve_search_controls(
        self,
        attributes: Attributes,
        properties: Properties | None,
    ) -> tuple[Any, Any, Any]:
        def selected(name: str) -> Any:
            if properties is not None and name in properties:
                return properties[name]
            if name in attributes:
                return attributes[name]
            return self.default_of(name)

        return selected("top_k"), selected("min_score"), selected("normalize")

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        query = attributes.get("query")
        search_fields = cast(list[str], attributes.get("search_fields", []))
        model_ref = attributes.get("model_ref")
        metric = cast(str, attributes.get("metric", "cosine"))
        add_meta_data = cast(bool, attributes.get("add_meta_data", False))
        on_missing_embedding = attributes.get("on_missing_embedding", "embed_missing")
        on_missing_fields = attributes.get("on_missing_fields", "raise")
        top_k, min_score, normalize = self._resolve_search_controls(attributes, properties)
        batch_size = cast(int, (properties or {}).get("batch_size", 32))

        if on_missing_embedding not in {"embed_missing", "raise"}:
            raise ValueError("on_missing_embedding must be one of: embed_missing, raise")
        if on_missing_fields not in {"raise", "use_empty"}:
            raise ValueError("on_missing_fields must be one of: raise, use_empty")
        if not input_data:
            return FunctionResult([], {})

        # Defer NumPy loading until after empty-input and policy checks.
        np = cast(Any, import_module("numpy"))

        default_model = model_ref if model_ref else _DEFAULT_MODEL

        def get_embedder(model_name: str) -> _Embedder:
            if model_name in _SUPPORTED_MODELS:
                return _embedder_constructor()(model_name)
            raise ValueError(f"Unsupported embedding model: {model_name}")

        def normalize_matrix(matrix: Any) -> Any:
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms = np.clip(norms, 1e-12, None)
            return matrix / norms

        def normalize_vector(vector: Any) -> Any:
            norm = np.linalg.norm(vector)
            if norm <= 1e-12:
                return vector
            return vector / norm

        def compute_scores(query_vector: Any, candidate_matrix: Any) -> Any:
            if metric == "cosine":
                if normalize:
                    return np.dot(candidate_matrix, query_vector)
                normalized_query = normalize_vector(query_vector)
                normalized_candidates = normalize_matrix(candidate_matrix)
                return np.dot(normalized_candidates, normalized_query)
            if metric == "dot":
                return np.dot(candidate_matrix, query_vector)
            if metric == "l2":
                return -np.linalg.norm(candidate_matrix - query_vector, axis=1)
            raise ValueError(f"Unsupported metric: {metric}")

        def extract_candidate_embedding(record: Record) -> Any | None:
            embedding = record.get("embedding")
            if embedding is None:
                return None
            if not isinstance(embedding, (list, tuple, np.ndarray)):
                raise ValueError("Candidate embedding must be a list, tuple, or numpy array.")
            array = np.asarray(embedding, dtype=float)
            if array.ndim != 1:
                raise ValueError("Candidate embedding must be 1-dimensional.")
            return array

        def build_text(record: Record, record_index: int) -> str:
            if search_fields:
                missing_fields = [field for field in search_fields if field not in record]
                if missing_fields and on_missing_fields == "raise":
                    raise ValueError(
                        f"Missing search fields {missing_fields} in candidate record "
                        f"{record_index}: {record}"
                    )
                values = [str(record.get(field, "")) for field in search_fields]
                if on_missing_fields == "raise" and all(value == "" for value in values):
                    raise ValueError(
                        "All configured search_fields are empty or missing in candidate "
                        f"record {record_index}: {record}"
                    )
            else:
                values = [str(record[key]) for key in sorted(record)]
            return "\n".join(values)

        def parse_query(query_value: Any) -> tuple[Any | None, Any | None, bool]:
            if isinstance(query_value, str):
                return None, None, False
            if isinstance(query_value, dict):
                query_record = cast(Record, query_value)
                embedding: Any = query_record.get("embedding")
                if embedding is not None:
                    query_vector = np.asarray(embedding, dtype=float)
                    if query_vector.ndim != 1:
                        raise ValueError("Query embedding must be 1-dimensional.")
                    query_model: Any = query_record.get("model")
                    return query_vector, query_model, True
            raise ValueError("query must be either a string or a dict containing 'embedding'.")

        query_vector, query_model, query_is_embedding = parse_query(query)
        effective_model = query_model if query_model else default_model
        embedder: _Embedder | None = None

        def ensure_embedder() -> _Embedder:
            nonlocal embedder
            if embedder is None:
                embedder = get_embedder(cast(str, effective_model))
            return embedder

        if not query_is_embedding:
            embedder = ensure_embedder()
            query_vector = np.asarray(
                embedder.encode(
                    [cast(str, query)],
                    batch_size=1,
                    normalize_embeddings=False,
                )[0],
                dtype=float,
            )

        if normalize:
            query_vector = normalize_vector(query_vector)

        output_data: DataBundle = []
        for dataset_index, data_value in enumerate(cast(list[object], input_data)):
            data = cast(Data, data_value)
            if not isinstance(data_value, list) or not all(
                isinstance(record, dict) for record in cast(list[object], data_value)
            ):
                raise ValueError("Each item in input_data must be a list of dictionaries.")
            if not data:
                output_data.append([])
                continue

            candidate_records: Data = []
            candidate_embeddings: list[Any] = []
            candidate_texts_to_embed: list[str] = []
            candidate_records_to_embed: Data = []
            dataset_model_values: set[Any] = set()

            for record_index, record in enumerate(data):
                embedding = extract_candidate_embedding(record)
                if embedding is not None:
                    candidate_records.append(record)
                    candidate_embeddings.append(embedding)
                    model_name = record.get("embed.model")
                    if model_name is None:
                        raise ValueError(
                            "Candidate embedding metadata is missing embed.model in "
                            f"dataset {dataset_index}, record {record_index}."
                        )
                    dataset_model_values.add(model_name)
                else:
                    if on_missing_embedding == "raise":
                        raise ValueError(
                            "Missing candidate embedding and on_missing_embedding='raise'."
                        )
                    candidate_records_to_embed.append(record)
                    candidate_texts_to_embed.append(build_text(record, record_index))

            if len(dataset_model_values) > 1:
                raise ValueError(
                    "Inconsistent candidate embed.model values in dataset "
                    f"{dataset_index}: {sorted(dataset_model_values)}"
                )
            if (
                query_is_embedding
                and query_model is None
                and model_ref is None
                and (dataset_model_values or candidate_records_to_embed)
            ):
                raise ValueError(
                    "Query embedding is missing model metadata; provide query.model or "
                    "model_ref to verify compatibility with candidate embeddings."
                )
            if dataset_model_values and effective_model not in dataset_model_values:
                raise ValueError(
                    f"Embedding space mismatch in dataset {dataset_index}: "
                    f"query/current model '{effective_model}' does not match candidate "
                    f"embed.model values {sorted(dataset_model_values)}."
                )

            if candidate_records_to_embed:
                embedder = ensure_embedder()
                embedded = np.asarray(
                    embedder.encode(
                        candidate_texts_to_embed,
                        batch_size=batch_size,
                        normalize_embeddings=False,
                    ),
                    dtype=float,
                )
                for index, record in enumerate(candidate_records_to_embed):
                    candidate_records.append(record)
                    candidate_embeddings.append(embedded[index])

            if not candidate_records:
                output_data.append([])
                continue

            candidate_matrix = np.vstack(candidate_embeddings)
            if normalize:
                candidate_matrix = normalize_matrix(candidate_matrix)
            scores = compute_scores(query_vector, candidate_matrix)

            scored_records: Data = []
            for index, record in enumerate(candidate_records):
                score = float(scores[index])
                if min_score is not None and score < min_score:
                    continue
                new_record = dict(record)
                new_record["search.score"] = score
                if add_meta_data:
                    new_record["search.metric"] = metric
                    if effective_model:
                        new_record["search.model"] = effective_model
                scored_records.append(new_record)

            scored_records.sort(
                key=lambda record: cast(float, record["search.score"]), reverse=True
            )
            if top_k is not None:
                scored_records = scored_records[: cast(int, top_k)]
            for rank, record in enumerate(scored_records, start=1):
                record["search.rank"] = rank
            output_data.append(scored_records)
        return FunctionResult(output_data, {})

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        reason = "supply a valid vector search query, attributes, and properties"
        inherited = super()._validate_input(input_data, attributes, properties)
        if not inherited.ok:
            return inherited

        top_k, min_score, normalize = self._resolve_search_controls(attributes, properties)
        property_top_k = properties is not None and "top_k" in properties
        property_normalize = properties is not None and "normalize" in properties
        if top_k is None:
            if not property_top_k:
                return ValidationResult(False, reason)
        elif not isinstance(top_k, int) or top_k < 1:
            return ValidationResult(False, reason)
        if min_score is not None and not isinstance(min_score, (int, float)):
            return ValidationResult(False, reason)
        if normalize is None:
            if not property_normalize:
                return ValidationResult(False, reason)
        elif not isinstance(normalize, bool):
            return ValidationResult(False, reason)
        return ValidationResult(True, None)


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when records in each group must be ranked by similarity to a text or vector query."
    ),
    tags=(
        "domain-vector",
        "flow-transform",
        "accepts-data",
        "produces-data",
        "capability-search",
        "requires-vector",
    ),
)
