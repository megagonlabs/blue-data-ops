from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import litellm
import pytest


def json_provider(contents: str | Sequence[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Install an OpenAI-shaped deterministic provider over the local litellm stub."""
    queue = [contents] if isinstance(contents, str) else list(contents)

    def fake(**kwargs: Any) -> Any:
        litellm.calls.append(kwargs)
        if not queue:
            raise AssertionError("semantic test provider response queue exhausted")
        content = queue.pop(0)

        class _R:
            def model_dump(self) -> dict[str, Any]:
                return {
                    "choices": [{"message": {"role": "assistant", "content": content}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }

        return _R()

    monkeypatch.setattr(litellm, "completion", fake)


def reset_litellm() -> None:
    litellm.calls.clear()
    litellm.fail_next.clear()
