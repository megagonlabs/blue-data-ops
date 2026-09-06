"""Discovery compatibility: PlanDiscover v1/v2 views, the OperatorDiscover facade, the Blue
``DeclarativeOperator`` import path, and the explicit legacy-id upgrader.

None of the compatibility surfaces enters a built-in registry or the primary card catalog:
``OperatorDiscoverOperator`` and ``DeclarativeOperator`` have no card, and ``question_answer`` has
no core recipe. ``resolve()`` and ``DataPipeline.from_dict()`` never upgrade a stored reference.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import pytest

from blue_data_ops.operators import (
    DeclarativeOperator,
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
from blue_data_ops.operators import operator as operator_module
from blue_data_ops.operators.registry import (
    _builtin_operator_classes,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.plan import DataPipeline, RefinableOperator
from blue_data_ops.plan import pipeline as pipeline_module
from tests.unit.operators._plan_operator_helpers import operator_ids


def _id_sequence() -> Any:
    current = 0

    def next_id() -> str:
        nonlocal current
        current += 1
        return f"catalog_{current:04d}"

    return next_id


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


# --------------------------------------------------------------------------------------------------
# PlanDiscover v1/v2 views
# --------------------------------------------------------------------------------------------------
def test_v1_plan_discover_emits_v1_children_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    operator = cast(RefinableOperator, versioned_registry().resolve("plan_discover@1.0.0"))
    plans, meta = operator.refine([[]], {"task": "select", "data": "rows", "approximate": True})
    assert meta.errors == [] and plans
    for plan in plans:
        assert {i.rpartition("@")[2] for i in operator_ids(plan.to_dict())} == {"1.0.0"}


def test_v2_plan_discover_emits_v2_children_and_filters_by_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    operator = cast(RefinableOperator, versioned_registry().resolve("plan_discover@2.0.0"))
    plans, meta = operator.refine(
        [[]],
        {
            "task": "records",
            "data": "rows",
            "approximate": True,
            "tags": ["flow-transform", "domain-relational"],
        },
    )
    assert meta.errors == [] and plans
    matched = {i.partition("@")[0] for plan in plans for i in operator_ids(plan.to_dict())}
    assert matched <= {"delete", "insert", "project", "select"}
    for plan in plans:
        assert {i.rpartition("@")[2] for i in operator_ids(plan.to_dict())} == {"2.0.0"}


def test_v2_plan_discover_limit_applies_after_the_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    operator = cast(RefinableOperator, versioned_registry().resolve("plan_discover@2.0.0"))
    plans, meta = operator.refine(
        [[]], {"task": "records", "data": "rows", "approximate": True, "limit": 1}
    )
    assert meta.errors == []
    assert len(plans) == 1


def test_v2_plan_discover_never_falls_back_from_an_injected_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from blue_data_ops.operators import OperatorRegistry
    from blue_data_ops.operators.plan_discover_operator import PlanDiscoverOperator

    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    empty = OperatorRegistry()  # injected, empty: no fallback to default_registry
    operator = PlanDiscoverOperator(empty)
    plans, meta = operator.refine([[]], {"task": "select", "data": "rows", "approximate": True})
    assert meta.errors == []
    assert plans == []  # empty injected registry yields no starter plans, never a v1 fallback


# --------------------------------------------------------------------------------------------------
# DeclarativeOperator compatibility import path (no card)
# --------------------------------------------------------------------------------------------------
def test_declarative_operator_has_the_blue_compatible_import_path() -> None:
    from blue_data_ops.operators.operator import DeclarativeOperator as FromOperatorModule

    assert FromOperatorModule is DeclarativeOperator
    assert operator_module.DeclarativeOperator is DeclarativeOperator
    assert issubclass(DeclarativeOperator, RefinableOperator)


def test_declarative_operator_has_no_registry_card() -> None:
    assert DeclarativeOperator not in _builtin_operator_classes()
    assert "declarative" not in {c.name for c in versioned_registry().list_cards()}


def test_operator_module_getattr_rejects_unknown_names() -> None:
    with pytest.raises(AttributeError):
        _ = operator_module.NotARealSymbol  # type: ignore[attr-defined]


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
        registry.resolve("select")  # bare name is never silently upgraded
    # a serialized v1 plan keeps its exact pinned ids through DataPipeline.from_dict round-trip
    operator = cast(RefinableOperator, registry.resolve("plan_discover@1.0.0"))
    plans, _ = operator.refine([[]], {"task": "select", "data": "rows", "approximate": True})
    if plans:
        record = plans[0].to_dict()
        assert DataPipeline.from_dict(record).to_dict() == record
        assert all(i.endswith("@1.0.0") for i in operator_ids(record))


def test_v2_plan_discover_rejects_malformed_tags_before_the_registry() -> None:
    from blue_data_ops.operators import ErrorCategory, ErrorCode, ErrorStage, OperatorRegistry
    from blue_data_ops.operators.plan_discover_operator import PlanDiscoverOperator

    class _SpyRegistry(OperatorRegistry):
        def __init__(self) -> None:
            super().__init__()
            self.find_calls = 0

        def find(self, query: str, tags: Any = None) -> Any:
            self.find_calls += 1
            return super().find(query, tags)

    spy = _SpyRegistry()  # the discovery source
    host = OperatorRegistry()
    operator = PlanDiscoverOperator(spy)
    host.register(operator, "2.0.0")  # bind as plan_discover@2.0.0 so the v2 path is selected
    bound = cast(RefinableOperator, host.resolve("plan_discover@2.0.0"))

    for bad in (["BAD TAG"], ["flow-\thead"], [123], "flow-plan"):
        _, meta = bound.refine(
            [[]], {"task": "find", "data": "rows", "approximate": True, "tags": bad}
        )
        error = meta.errors[0]
        assert error.category is ErrorCategory.RECOVERABLE
        assert error.code is ErrorCode.INVALID_INPUT
        assert error.stage is ErrorStage.VALIDATE
    assert spy.find_calls == 0  # malformed tags are rejected before any registry access


def test_upgrade_rejects_an_ambiguous_name_alias_collision() -> None:
    registry = versioned_registry()  # "select" is a registered bare name
    with pytest.raises(UpgradeError):
        upgrade_legacy_operator_id(
            "select", registry, target_version="2.0.0", aliases={"select": "join@2.0.0"}
        )
