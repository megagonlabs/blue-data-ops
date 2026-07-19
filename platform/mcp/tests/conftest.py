from __future__ import annotations

import hashlib
import sys
import types
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np


@dataclass(frozen=True)
class EncodeCall:
    model_name: str
    sentences: tuple[str, ...]
    batch_size: int
    normalize_embeddings: bool
    show_progress_bar: bool = False


class SentenceTransformer:
    model_names: ClassVar[list[str]] = []
    encode_calls: ClassVar[list[EncodeCall]] = []

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.model_names.append(model_name)

    @classmethod
    def reset(cls) -> None:
        cls.model_names.clear()
        cls.encode_calls.clear()

    def encode(
        self,
        sentences: Sequence[str],
        batch_size: int = 32,
        normalize_embeddings: bool = False,
        show_progress_bar: bool = False,
    ) -> Any:
        items = tuple(sentences)
        self.encode_calls.append(
            EncodeCall(
                self.model_name,
                items,
                batch_size,
                normalize_embeddings,
                show_progress_bar,
            )
        )
        return np.asarray([_embedding(text) for text in items], dtype=float)


def _embedding(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    return [digest[index] / 255.0 for index in range(4)]


sentence_transformers_stub = types.ModuleType("sentence_transformers")
setattr(sentence_transformers_stub, "SentenceTransformer", SentenceTransformer)
sys.modules["sentence_transformers"] = sentence_transformers_stub
