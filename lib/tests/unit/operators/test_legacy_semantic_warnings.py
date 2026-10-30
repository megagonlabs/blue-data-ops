"""Retained semantic versions reject malformed replies and preserve registry selection."""

from __future__ import annotations

from typing import Any, cast

import pytest

from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import active_registry, default_registry, versioned_registry
from blue_data_ops.operators.semantic_extract_operator import SemanticExtractOperator
from blue_data_ops.operators.semantic_filter_operator import SemanticFilterOperator
from blue_data_ops.operators.semantic_join_operator import SemanticJoinOperator
from blue_data_ops.operators.semantic_project_operator import SemanticProjectOperator
from blue_data_ops.operators.semantic_transform_operator import SemanticTransformOperator

CLASSES = {
    "semantic_filter": SemanticFilterOperator,
    "semantic_extract": SemanticExtractOperator,
    "semantic_project": SemanticProjectOperator,
    "semantic_transform": SemanticTransformOperator,
    "semantic_join": SemanticJoinOperator,
}

# Input, attributes, the scripted malformed replies, and what the retained versions return.
CASES: dict[str, tuple[Any, dict[str, Any], list[Any], Any]] = {
    "semantic_filter": (
        [[{"id": 1, "score": 9}, {"id": 2, "score": 8}]],
        {"filter_conditions": {"score": "is high"}},
        ["I'm sorry, I can't help with that.", ""],
        [[]],
    ),
    "semantic_extract": (
        [[{"bio": "Ada uses Python"}]],
        {"entities": [{"name": "skill"}]},
        [[]],
        [[{"skill": []}]],
    ),
    "semantic_project": (
        [[{"first": "Ada"}]],
        {"projection_instructions": "keep first"},
        [[]],
        [[]],
    ),
    "semantic_transform": (
        [[{"raw": "A"}]],
        {"output_desc": {"label": {"description": "normalized label"}}},
        ["not json", "not json"],
        [[{}]],
    ),
    "semantic_join": (
        [[{"left": "Ada"}], [{"right": "ADA"}]],
        {"estimate_cost": False, "left_fields": [], "right_fields": []},
        ["not json"],
        [[]],
    ),
}


class Scripted(LLMClient):
    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ):
        self.calls += 1
        if not self.replies:
            raise AssertionError("scripted client exhausted")
        return self.replies.pop(0)


class Failing(LLMClient):
    def __init__(self) -> None:
        pass

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ):
        raise RuntimeError("synthetic provider failure")


def _implementation(operator: Any) -> Any:
    while hasattr(operator, "_target"):
        operator = operator._target
    return operator


@pytest.mark.parametrize("name", sorted(CLASSES))
def test_each_retained_class_documents_strict_errors(name: str) -> None:
    doc = " ".join((CLASSES[name].__doc__ or "").split())
    assert "@1.0.0" in doc and "@2.0.0" in doc
    assert "exec_meta.errors" in doc and "apply()" in doc and "run()" in doc
    if name == "semantic_join":
        assert "complete pair objects" in doc
        assert "true/yes/1/match/join" in doc
        assert "false/no/0/exclude" in doc
    else:
        assert "strict" in doc


@pytest.mark.parametrize("name", sorted(CLASSES))
def test_the_strict_versions_do_not_inherit_the_warning(name: str) -> None:
    strict = cast(type[Any], type(_implementation(versioned_registry().resolve(f"{name}@3.0.0"))))
    assert issubclass(strict, CLASSES[name])
    assert "permissive" not in (strict.__doc__ or "")


def test_the_warned_surface_is_the_default_one_and_the_strict_one_is_active() -> None:
    def selected(registry: Any) -> list[str]:
        return sorted(
            card.operator_id
            for card in registry.list_cards()
            if card.operator_id.split("@")[0] in CLASSES
        )

    assert selected(default_registry()) == sorted(f"{name}@1.0.0" for name in CLASSES)
    assert selected(active_registry()) == sorted(f"{name}@3.0.0" for name in CLASSES)


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
@pytest.mark.parametrize("name", sorted(CASES))
def test_retained_versions_report_a_malformed_reply(name: str, version: str) -> None:
    data, attributes, replies, _ = CASES[name]
    client = Scripted(replies)
    output, _, meta = (
        versioned_registry()
        .resolve(f"{name}@{version}")
        .run(data, attributes, {"llm_client": client})
    )
    assert output == [[]]
    assert [error.code.name for error in meta.errors] == ["EXECUTION_FAILED"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_strict_version_reports_the_same_reply(name: str) -> None:
    data, attributes, replies, _ = CASES[name]
    output, _, meta = (
        versioned_registry()
        .resolve(f"{name}@3.0.0")
        .run(data, attributes, {"llm_client": Scripted(replies)})
    )
    assert output == [[]]
    assert [error.code.name for error in meta.errors] == ["EXECUTION_FAILED"]


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
@pytest.mark.parametrize("name", sorted(CASES))
def test_a_provider_exception_is_still_a_failure_on_retained_versions(
    name: str, version: str
) -> None:
    data, attributes, _, _ = CASES[name]
    operator = versioned_registry().resolve(f"{name}@{version}")
    with pytest.raises(RuntimeError, match="synthetic provider failure"):
        operator.apply(data, attributes, {"llm_client": Failing()})
    output, _, meta = operator.run(data, attributes, {"llm_client": Failing()})
    assert output == [[]]
    assert [error.code.name for error in meta.errors] == ["EXECUTION_FAILED"]
    assert "synthetic provider failure" not in str(meta.errors)
