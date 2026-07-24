from __future__ import annotations

from collections.abc import Callable, Sequence
from importlib import import_module
from typing import Any, ClassVar, Protocol, cast

from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators.operator import Operator
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


class VectorEmbedOperator(Operator):
    """Convert record text into vector embeddings."""

    name: ClassVar[str] = "vector_embed"
    description: ClassVar[str] = "Convert text data into vector embeddings using a specified model."
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "model_ref": AttributeSpec(
            type="str",
            description="Reference to the embedding model",
            default=_DEFAULT_MODEL,
        ),
        "text_field": AttributeSpec(
            type="list[str]",
            description="Keys containing the raw text",
            default=[],
        ),
        "delimiter": AttributeSpec(
            type="str",
            description="Delimiter for concatenating text fields",
            default="\n",
        ),
        "append": AttributeSpec(
            type="bool",
            description="Append embeddings to dataset or return only embeddings",
            default=False,
        ),
        "add_meta_data": AttributeSpec(
            type="bool",
            description="Add embed.model and embed.dim to output",
            default=False,
        ),
        "on_missing_fields": AttributeSpec(
            type="str",
            description="How to handle missing text fields: raise | use_empty",
            default="raise",
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
        properties = properties or {}
        model_ref = attributes.get("model_ref")
        text_fields = cast(list[str], attributes.get("text_field", []))
        delimiter = cast(str, attributes.get("delimiter", "\n"))
        append = cast(bool, attributes.get("append", False))
        add_meta_data = cast(bool, attributes.get("add_meta_data", False))
        batch_size = cast(int, properties.get("batch_size", 32))
        normalize = cast(bool, properties.get("normalize", False))
        on_missing_fields = attributes.get("on_missing_fields", "raise")

        if on_missing_fields not in {"raise", "use_empty"}:
            raise ValueError("on_missing_fields must be one of: raise, use_empty")
        if not input_data or not input_data[0]:
            return FunctionResult([[]], {})

        constructor = _embedder_constructor()
        if model_ref:
            try:
                embedder = constructor(cast(str, model_ref))
            except Exception as exc:
                raise ValueError(f"Failed to load embedding model '{model_ref}': {exc}") from exc
        else:
            embedder = constructor(_DEFAULT_MODEL)

        output_data: DataBundle = []
        for data_value in cast(list[object], input_data):
            data = cast(Data, data_value)
            if not isinstance(data_value, list) or not all(
                isinstance(record, dict) for record in cast(list[object], data_value)
            ):
                raise ValueError("Each item in input_data must be a list of dictionaries.")

            texts: list[str] = []
            records_to_embed: Data = []
            for record in data:
                if text_fields:
                    missing_fields = [field for field in text_fields if field not in record]
                    if missing_fields and on_missing_fields == "raise":
                        raise ValueError(
                            f"Missing text fields {missing_fields} in record: {record}"
                        )
                    values = [str(record.get(field, "")) for field in text_fields]
                    if on_missing_fields == "raise" and all(value == "" for value in values):
                        raise ValueError(
                            "All configured text_field values are empty or missing "
                            f"in record: {record}"
                        )
                    text = delimiter.join(values)
                else:
                    values = [str(record[key]) for key in sorted(record)]
                    text = delimiter.join(values)
                texts.append(text)
                records_to_embed.append(record)

            if not records_to_embed:
                output_data.append([])
                continue

            embeddings_result: Any = embedder.encode(
                texts,
                batch_size=batch_size,
                normalize_embeddings=normalize,
            )
            if len(embeddings_result) == 0:
                raise ValueError("Embedding model returned no embeddings.")
            first_embedding: Any = embeddings_result[0]
            try:
                dimension = len(first_embedding)
            except TypeError as exc:
                raise ValueError(
                    "Embedding model returned embeddings with unknown dimension."
                ) from exc

            if hasattr(embeddings_result, "tolist"):
                embeddings = cast(list[list[Any]], embeddings_result.tolist())
            else:
                embeddings = [list(embedding) for embedding in embeddings_result]

            output_records: Data = []
            for index, record in enumerate(records_to_embed):
                new_record: Record = dict(record) if append else {}
                if "id" not in new_record:
                    new_record["id"] = record.get("id", f"index_{index}")
                new_record["embedding"] = embeddings[index]
                if add_meta_data:
                    new_record["embed.model"] = model_ref if model_ref else _DEFAULT_MODEL
                    new_record["embed.dim"] = dimension
                    new_record["embed.fields"] = str(text_fields) if text_fields else "all_fields"
                output_records.append(new_record)
            output_data.append(output_records)
        return FunctionResult(output_data, {})

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
        reason = "supply valid vector embedding attributes and properties"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, reason)

        text_fields = attributes.get("text_field")
        if text_fields is not None and not isinstance(text_fields, list):
            return ValidationResult(False, reason)
        if text_fields and not all(
            isinstance(field, str) for field in cast(list[object], text_fields)
        ):
            return ValidationResult(False, reason)
        on_missing_fields = attributes.get("on_missing_fields")
        if on_missing_fields is not None and on_missing_fields not in {
            "raise",
            "use_empty",
        }:
            return ValidationResult(False, reason)
        if properties is not None:
            batch_size = properties.get("batch_size")
            if batch_size is not None and (not isinstance(batch_size, int) or batch_size < 1):
                return ValidationResult(False, reason)
            normalize = properties.get("normalize")
            if normalize is not None and not isinstance(normalize, bool):
                return ValidationResult(False, reason)
        return ValidationResult(True, None)


DISCOVERY = DiscoverySpec(
    when_to_invoke="Use when text fields must be encoded as vectors for later similarity work.",
    tags=(
        "domain-vector",
        "flow-transform",
        "accepts-data",
        "produces-data",
        "capability-embedding",
        "requires-vector",
    ),
)
