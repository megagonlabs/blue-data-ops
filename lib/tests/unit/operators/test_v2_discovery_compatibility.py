"""Retained discovery facade and explicit legacy-ID upgrade compatibility."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import pytest

from blue_data_ops.operators import (
    DiscoveryError,
    EmbeddingDiscoveryError,
    OperatorDiscoverOperator,
    OperatorEmbeddingIndex,
    OperatorError,
    UpgradeError,
    default_registry,
    upgrade_legacy_operator_id,
    versioned_registry,
)
from blue_data_ops.operators.registry import (
    _builtin_operator_classes,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.plan import DataPipeline


# --------------------------------------------------------------------------------------------------
# OperatorDiscoverOperator facade
# --------------------------------------------------------------------------------------------------
def test_facade_is_outside_the_built_in_catalog_and_mcp_inventory() -> None:
    assert OperatorDiscoverOperator not in _builtin_operator_classes()
    registry = versioned_registry()
    assert registry.get_card("operator_discover@2.0.0") is None
    assert registry.get_card("operator_discover@1.0.0") is None
    assert default_registry().get_card("operator_discover@1.0.0") is None
    assert "operator_discover" not in {c.name for c in registry.list_cards()}


def test_facade_portable_mode_is_deterministic_local_discovery() -> None:
    facade = OperatorDiscoverOperator(versioned_registry())
    rows = facade.apply([[]], {"search_query": "", "tags": ["domain-set"]})[0]
    assert sorted({r["name"] for r in rows}) == ["intersect", "union"]
    assert all(
        set(("operator_id", "name", "version", "description", "tags", "when_to_invoke")) <= set(row)
        for row in rows
    )
    limited = facade.apply([[]], {"search_query": "join", "limit": 2})[0]
    assert len(limited) == 2


class _ControlledEmbedder:
    space_id = "facade-control-v1"

    def __init__(self, *, reverse: bool = False, fail_query: bool = False) -> None:
        self.reverse = reverse
        self.fail_query = fail_query
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, texts: tuple[str, ...]) -> Sequence[Sequence[float]]:
        self.calls.append(texts)
        if len(texts) == 1:
            if self.fail_query:
                raise RuntimeError("private-callback-detail")
            return ((1.0, 0.0, 0.25),)

        vectors: list[tuple[float, float, float]] = []
        for text in texts:
            if 'name: "select"' in text:
                vector = (1.0, 0.0, 0.25)
            elif 'name: "avg"' in text:
                vector = (0.0, 1.0, 0.25)
            else:
                vector = (0.0, 0.0, 1.0)
            if self.reverse and vector[:2] != (0.0, 0.0):
                vector = (vector[1], vector[0], vector[2])
            vectors.append(vector)
        return vectors


def _approximate_first_name(*, reverse: bool) -> tuple[str, _ControlledEmbedder]:
    registry = versioned_registry()
    embedder = _ControlledEmbedder(reverse=reverse)
    index = OperatorEmbeddingIndex.build(registry, embedder)
    rows = OperatorDiscoverOperator(registry).apply(
        [[]],
        {"search_query": "rank by the supplied vector", "approximate": True, "limit": 1},
        {"discovery_backend": index},
    )[0]
    return cast(str, rows[0]["name"]), embedder


def test_facade_approximate_mode_uses_the_index_order() -> None:
    first, first_embedder = _approximate_first_name(reverse=False)
    reversed_first, reversed_embedder = _approximate_first_name(reverse=True)

    assert first == "select"
    assert reversed_first == "avg"
    assert len(first_embedder.calls) == len(reversed_embedder.calls) == 2
    assert len(first_embedder.calls[0]) == len(versioned_registry().list_cards())
    assert first_embedder.calls[1] == ("rank by the supplied vector",)


@pytest.mark.parametrize("backend_kind", ["missing", "wrong", "different_registry"])
def test_facade_rejects_an_unbound_embedding_index(backend_kind: str) -> None:
    registry = versioned_registry()
    properties: dict[str, Any] = {}
    if backend_kind == "wrong":
        properties["discovery_backend"] = object()
    elif backend_kind == "different_registry":
        properties["discovery_backend"] = OperatorEmbeddingIndex.build(
            versioned_registry(), _ControlledEmbedder()
        )

    facade = OperatorDiscoverOperator(registry)
    with pytest.raises(EmbeddingDiscoveryError) as caught:
        facade.apply(
            [[]],
            {"search_query": "select", "approximate": True},
            properties,
        )

    assert caught.value.reason == "BACKEND_MISMATCH"
    assert isinstance(caught.value, OperatorError)
    assert isinstance(caught.value, DiscoveryError)


@pytest.mark.parametrize(
    ("attributes", "reason"),
    [
        ({"search_query": "x", "hybrid": True}, "MODE_UNAVAILABLE"),
        (
            {"search_query": "x", "approximate": True, "hybrid": True},
            "INVALID_MODE",
        ),
    ],
)
def test_facade_rejects_unavailable_or_conflicting_modes(
    attributes: dict[str, Any], reason: str
) -> None:
    with pytest.raises(OperatorError) as caught:
        OperatorDiscoverOperator(versioned_registry()).apply([[]], attributes)

    assert isinstance(caught.value, EmbeddingDiscoveryError)
    assert caught.value.reason == reason


def test_facade_does_not_fall_back_when_the_index_query_fails() -> None:
    registry = versioned_registry()
    embedder = _ControlledEmbedder(fail_query=True)
    index = OperatorEmbeddingIndex.build(registry, embedder)

    with pytest.raises(EmbeddingDiscoveryError) as caught:
        OperatorDiscoverOperator(registry).apply(
            [[]],
            {"search_query": "select", "approximate": True},
            {"discovery_backend": index},
        )

    assert caught.value.reason == "QUERY_FAILED"
    assert "private-callback-detail" not in str(caught.value)


def test_facade_run_contains_embedding_errors() -> None:
    output, output_attributes, meta = OperatorDiscoverOperator(versioned_registry()).run(
        [[]],
        {"search_query": "select", "approximate": True},
    )

    assert output == [[]]
    assert output_attributes == {}
    assert len(meta.errors) == 1
    assert meta.errors[0].message == "operator execution failed"


def test_question_answer_has_no_core_recipe() -> None:
    names = {c.name for c in versioned_registry().list_cards()}
    assert "question_answer" not in names
    assert not any(cls.__name__ == "QuestionAnswerOperator" for cls in _builtin_operator_classes())


# --------------------------------------------------------------------------------------------------
# upgrade_legacy_operator_id — every edge
# --------------------------------------------------------------------------------------------------
def test_upgrade_accepts_a_pinned_id_unchanged() -> None:
    registry = versioned_registry()
    assert (
        upgrade_legacy_operator_id("select@1.0.0", registry, target_version="2.0.0")
        == "select@1.0.0"
    )


def test_upgrade_converts_bare_name_and_deployment_path() -> None:
    registry = versioned_registry()
    assert upgrade_legacy_operator_id("select", registry, target_version="2.0.0") == "select@2.0.0"
    assert (
        upgrade_legacy_operator_id("/server/s/operator/join", registry, target_version="1.0.0")
        == "join@1.0.0"
    )
    assert (
        upgrade_legacy_operator_id("/server/s/tool/avg", registry, target_version="2.0.0")
        == "avg@2.0.0"
    )


def test_upgrade_resolves_explicit_aliases_to_registered_pinned_ids() -> None:
    registry = versioned_registry()
    assert (
        upgrade_legacy_operator_id(
            "qa", registry, target_version="2.0.0", aliases={"qa": "nl2llm@2.0.0"}
        )
        == "nl2llm@2.0.0"
    )


@pytest.mark.parametrize(
    "reference,aliases",
    [
        ("ghost", None),  # unregistered bare name
        ("ghost@1.0.0", None),  # unregistered pinned id
        ("/server/s/operator/ghost", None),  # unregistered deployment path
        ("qa", {"qa": "nl2llm"}),  # alias value not pinned
        ("qa", {"qa": "ghost@2.0.0"}),  # alias target not registered
        ("a@b@c", None),  # malformed
    ],
)
def test_upgrade_rejects_bad_references(reference: str, aliases: dict[str, str] | None) -> None:
    with pytest.raises(UpgradeError):
        upgrade_legacy_operator_id(
            reference, versioned_registry(), target_version="2.0.0", aliases=aliases
        )


def test_upgrade_rejects_a_malformed_target_version() -> None:
    with pytest.raises(UpgradeError):
        upgrade_legacy_operator_id("select", versioned_registry(), target_version="2.0")


def test_resolve_and_from_dict_never_upgrade_implicitly() -> None:
    from blue_data_ops.operators import ResolveError

    registry = versioned_registry()
    with pytest.raises(ResolveError):
        registry.resolve("select")

    pipeline = DataPipeline(label="historical exact-id record")
    source_node = pipeline.define_input("input")
    selected = pipeline.define_operator(
        "select@1.0.0",
        attributes={"operand_key": "value", "operand": "eq", "operand_val": 1},
    )
    output_node = pipeline.define_output("output")
    pipeline.connect_nodes(source_node, selected)
    pipeline.connect_nodes(selected, output_node)
    pipeline.set_plan_input(source_node)
    pipeline.set_plan_output(output_node)
    record = pipeline.to_dict()

    assert DataPipeline.from_dict(record).to_dict() == record
    assert registry.resolve("select@1.0.0").operator_id == "select@1.0.0"


def test_upgrade_rejects_an_ambiguous_name_alias_collision() -> None:
    registry = versioned_registry()  # "select" is a registered bare name
    with pytest.raises(UpgradeError):
        upgrade_legacy_operator_id(
            "select", registry, target_version="2.0.0", aliases={"select": "join@2.0.0"}
        )
