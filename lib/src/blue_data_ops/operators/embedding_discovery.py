from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Literal, Protocol, TypeGuard

from blue_data_ops.operators._discovery import DiscoveryError, normalize_filter_tag
from blue_data_ops.operators.registry import OperatorCard, OperatorRegistry
from blue_data_ops.operators.types import OperatorError

_EmbeddingDiscoveryReason = Literal[
    "BUILD_FAILED",
    "QUERY_FAILED",
    "INVALID_RESULT",
    "STALE_INDEX",
    "BACKEND_MISMATCH",
    "MODE_UNAVAILABLE",
    "INVALID_MODE",
]

_ERROR_MESSAGES: dict[_EmbeddingDiscoveryReason, str] = {
    "BUILD_FAILED": "embedding index build failed",
    "QUERY_FAILED": "embedding query failed",
    "INVALID_RESULT": "embedder returned an invalid result",
    "STALE_INDEX": "embedding index is stale; rebuild it",
    "BACKEND_MISMATCH": "embedding index does not match the registry",
    "MODE_UNAVAILABLE": "the requested discovery mode is unavailable",
    "INVALID_MODE": "the requested discovery modes conflict",
}


class OperatorEmbedder(Protocol):
    """A caller-supplied batch embedder with an exact embedding-space identity."""

    @property
    def space_id(self) -> str: ...

    def __call__(self, texts: tuple[str, ...]) -> Sequence[Sequence[float]]: ...


class EmbeddingDiscoveryError(DiscoveryError, OperatorError):
    """Embedding discovery failed with a stable public reason."""

    reason: _EmbeddingDiscoveryReason

    def __init__(self, reason: _EmbeddingDiscoveryReason) -> None:
        self.reason = reason
        super().__init__(_ERROR_MESSAGES[reason])


@dataclass(frozen=True, init=False)
class OperatorEmbeddingIndex:
    """An in-memory embedding snapshot bound to one operator registry."""

    _registry: OperatorRegistry
    _embedder: OperatorEmbedder
    _space_id: str
    _cards: tuple[OperatorCard, ...]
    _documents: tuple[str, ...]
    _document_hashes: tuple[str, ...]
    _vectors: tuple[tuple[float, ...], ...]
    _dimension: int | None
    _fingerprint: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("use OperatorEmbeddingIndex.build()")

    @classmethod
    def build(
        cls,
        registry: OperatorRegistry,
        embedder: OperatorEmbedder,
    ) -> OperatorEmbeddingIndex:
        """Embed one validated snapshot of all cards in registry."""
        space_id = _read_build_space_id(embedder)
        cards, documents = _read_initial_snapshot(registry)
        document_hashes = tuple(_document_hash(document) for document in documents)
        fingerprint = _snapshot_fingerprint(space_id, cards, document_hashes)

        if cards:
            try:
                raw_vectors = embedder(documents)
            except Exception:
                raise EmbeddingDiscoveryError("BUILD_FAILED") from None
            vectors, dimension = _validated_vectors(raw_vectors, len(cards))
        else:
            vectors = ()
            dimension = None

        return cls._from_validated(
            registry,
            embedder,
            space_id,
            cards,
            documents,
            document_hashes,
            vectors,
            dimension,
            fingerprint,
        )

    @classmethod
    def _from_validated(
        cls,
        registry: OperatorRegistry,
        embedder: OperatorEmbedder,
        space_id: str,
        cards: tuple[OperatorCard, ...],
        documents: tuple[str, ...],
        document_hashes: tuple[str, ...],
        vectors: tuple[tuple[float, ...], ...],
        dimension: int | None,
        fingerprint: str,
    ) -> OperatorEmbeddingIndex:
        index = object.__new__(cls)
        object.__setattr__(index, "_registry", registry)
        object.__setattr__(index, "_embedder", embedder)
        object.__setattr__(index, "_space_id", space_id)
        object.__setattr__(index, "_cards", cards)
        object.__setattr__(index, "_documents", documents)
        object.__setattr__(index, "_document_hashes", document_hashes)
        object.__setattr__(index, "_vectors", vectors)
        object.__setattr__(index, "_dimension", dimension)
        object.__setattr__(index, "_fingerprint", fingerprint)
        return index

    @property
    def registry(self) -> OperatorRegistry:
        """Return the exact registry captured at build time."""
        return self._registry

    def find(
        self,
        query: str,
        tags: Sequence[str] | None = None,
    ) -> list[OperatorCard]:
        """Rank snapshot cards after applying exact AND-tag filters."""
        self._check_continuity()

        filter_tags: set[str] | None = None
        if tags is not None:
            filter_tags = {normalize_filter_tag(token) for token in tags}

        candidates = [
            (card, vector)
            for card, vector in zip(self._cards, self._vectors, strict=True)
            if not filter_tags or filter_tags.issubset(set(card.tags))
        ]

        needle = query.strip()
        if not needle:
            if not filter_tags:
                return []
            return sorted(
                (card for card, _ in candidates),
                key=lambda card: (card.name, _descending_version(card.version)),
            )
        if not candidates:
            return []

        try:
            raw_query = self._embedder((query,))
        except Exception:
            raise EmbeddingDiscoveryError("QUERY_FAILED") from None
        query_vectors, _ = _validated_vectors(
            raw_query,
            1,
            expected_dimension=self._dimension,
        )
        query_vector = query_vectors[0]

        ranked = [
            (
                math.fsum(left * right for left, right in zip(query_vector, vector, strict=True)),
                card,
            )
            for card, vector in candidates
        ]
        ranked.sort(
            key=lambda item: (
                -item[0],
                item[1].name,
                _descending_version(item[1].version),
            )
        )
        return [card for _, card in ranked]

    def _check_continuity(self) -> None:
        try:
            current_space_id = self._embedder.space_id
        except Exception:
            raise EmbeddingDiscoveryError("STALE_INDEX") from None
        if not _valid_space_id(current_space_id) or current_space_id != self._space_id:
            raise EmbeddingDiscoveryError("STALE_INDEX")

        try:
            current_cards = tuple(self._registry.list_cards())
            if len(current_cards) != len(self._cards):
                raise ValueError

            current_documents: list[str] = []
            for current, captured in zip(current_cards, self._cards, strict=True):
                if current is not captured:
                    raise ValueError
                if self._registry.get_card(captured.operator_id) is not captured:
                    raise ValueError
                current_documents.append(_card_document(current))

            documents = tuple(current_documents)
            if documents != self._documents:
                raise ValueError
            hashes = tuple(_document_hash(document) for document in documents)
            if hashes != self._document_hashes:
                raise ValueError
            if _snapshot_fingerprint(current_space_id, current_cards, hashes) != self._fingerprint:
                raise ValueError
        except Exception:
            raise EmbeddingDiscoveryError("STALE_INDEX") from None


def _read_build_space_id(embedder: OperatorEmbedder) -> str:
    try:
        space_id = embedder.space_id
    except Exception:
        raise EmbeddingDiscoveryError("BUILD_FAILED") from None
    if not _valid_space_id(space_id):
        raise EmbeddingDiscoveryError("BUILD_FAILED")
    return space_id


def _valid_space_id(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _read_initial_snapshot(
    registry: OperatorRegistry,
) -> tuple[tuple[OperatorCard, ...], tuple[str, ...]]:
    if not isinstance(registry, OperatorRegistry):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise EmbeddingDiscoveryError("BACKEND_MISMATCH")

    try:
        cards = tuple(registry.list_cards())
        operator_ids: set[str] = set()
        documents: list[str] = []
        for card in cards:
            if not isinstance(card, OperatorCard):  # pyright: ignore[reportUnnecessaryIsInstance]
                raise ValueError
            if card.operator_id in operator_ids:
                raise ValueError
            operator_ids.add(card.operator_id)
            if registry.get_card(card.operator_id) is not card:
                raise ValueError
            documents.append(_card_document(card))
        return cards, tuple(documents)
    except EmbeddingDiscoveryError:
        raise
    except Exception:
        raise EmbeddingDiscoveryError("BACKEND_MISMATCH") from None


def _card_document(card: OperatorCard) -> str:
    def encode(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    return (
        f"name: {encode(card.name)}\n"
        f"when_to_invoke: {encode(card.when_to_invoke)}\n"
        f"description: {encode(card.description)}\n"
        f"tags: {encode(list(card.tags))}\n"
    )


def _document_hash(document: str) -> str:
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


def _snapshot_fingerprint(
    space_id: str,
    cards: tuple[OperatorCard, ...],
    document_hashes: tuple[str, ...],
) -> str:
    payload = {
        "space_id": space_id,
        "cards": [
            [card.operator_id, document_hash]
            for card, document_hash in zip(cards, document_hashes, strict=True)
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validated_vectors(
    raw_vectors: object,
    expected_count: int,
    *,
    expected_dimension: int | None = None,
) -> tuple[tuple[tuple[float, ...], ...], int]:
    if not _is_sequence(raw_vectors):
        raise EmbeddingDiscoveryError("INVALID_RESULT")

    try:
        if len(raw_vectors) != expected_count:
            raise EmbeddingDiscoveryError("INVALID_RESULT")

        vectors: list[tuple[float, ...]] = []
        dimension = expected_dimension
        for raw_vector in raw_vectors:
            if not _is_sequence(raw_vector) or not raw_vector:
                raise EmbeddingDiscoveryError("INVALID_RESULT")

            values: list[float] = []
            for item in raw_vector:
                if isinstance(item, bool) or not isinstance(item, Real):
                    raise EmbeddingDiscoveryError("INVALID_RESULT")
                number = float(item)
                if not math.isfinite(number):
                    raise EmbeddingDiscoveryError("INVALID_RESULT")
                values.append(number)

            if dimension is None:
                dimension = len(values)
            if len(values) != dimension:
                raise EmbeddingDiscoveryError("INVALID_RESULT")

            norm = math.hypot(*values)
            if not math.isfinite(norm) or norm == 0.0:
                raise EmbeddingDiscoveryError("INVALID_RESULT")
            vectors.append(tuple(value / norm for value in values))
    except EmbeddingDiscoveryError:
        raise
    except Exception:
        raise EmbeddingDiscoveryError("INVALID_RESULT") from None

    if dimension is None:
        raise EmbeddingDiscoveryError("INVALID_RESULT")
    return tuple(vectors), dimension


def _is_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _descending_version(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.split(".")
    return -int(major), -int(minor), -int(patch)
