from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, cast

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class EncodeCall:
    """One deterministic stub-model invocation."""

    model_name: str
    sentences: tuple[str, ...]
    batch_size: int
    normalize_embeddings: bool
    show_progress_bar: bool = False


class SentenceTransformer:
    """Deterministic four-dimensional stand-in for sentence-transformers."""

    model_names: ClassVar[list[str]] = []
    encode_calls: ClassVar[list[EncodeCall]] = []

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.model_names.append(model_name)

    @classmethod
    def reset(cls) -> None:
        """Clear construction and encode call history."""
        cls.model_names.clear()
        cls.encode_calls.clear()

    def encode(
        self,
        sentences: Sequence[str],
        batch_size: int = 32,
        normalize_embeddings: bool = False,
        show_progress_bar: bool = False,
    ) -> NDArray[np.float64]:
        """Return deterministic vectors while recording the model-call contract."""
        items = tuple(sentences)
        self.encode_calls.append(
            EncodeCall(
                model_name=self.model_name,
                sentences=items,
                batch_size=batch_size,
                normalize_embeddings=normalize_embeddings,
                show_progress_bar=show_progress_bar,
            )
        )
        embeddings = np.asarray([_embedding(text) for text in items], dtype=float)
        if normalize_embeddings and len(embeddings) > 0:
            np_api = cast(Any, np)
            norms: Any = np_api.linalg.norm(embeddings, axis=1, keepdims=True)
            embeddings = cast(NDArray[np.float64], embeddings / np_api.clip(norms, 1e-12, None))
        return embeddings


def _embedding(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    return [digest[index] / 255.0 for index in range(4)]
