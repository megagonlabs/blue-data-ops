"""Model defaults on all registered LLM operator versions."""

from __future__ import annotations

from typing import Any, cast

import pytest

from blue_data_ops.llm import prepare_llm_operator_properties
from blue_data_ops.operators.registry import default_registry, versioned_registry


@pytest.mark.parametrize(
    "name",
    [
        "nl2bn",
        "nl2llm",
        "nl2sql",
        "semantic_extract",
        "semantic_filter",
        "semantic_join",
        "semantic_project",
        "semantic_transform",
    ],
)
def test_default_model_is_luna_at_each_version(name: str) -> None:
    registry = versioned_registry()
    for version in ("1.0.0", "2.0.0", "3.0.0"):
        operator = registry.resolve(f"{name}@{version}")
        defaults = cast(dict[str, Any], getattr(operator, "DEFAULT_PROPERTIES"))
        assert defaults["openai.model"] == "gpt-6-luna"
        assert "openai.reasoning_effort" not in defaults

        prepared = prepare_llm_operator_properties(dict(defaults), defaults, None)
        assert "openai.temperature" not in prepared

    raw = default_registry().resolve(f"{name}@1.0.0")
    raw_defaults = cast(dict[str, Any], getattr(raw, "DEFAULT_PROPERTIES"))
    assert raw_defaults["openai.model"] == "gpt-6-luna"
