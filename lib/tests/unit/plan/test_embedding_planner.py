from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, cast

import pytest

from blue_data_ops.operators import (
    EmbeddingDiscoveryError,
    OperatorEmbeddingIndex,
    versioned_registry,
)
from blue_data_ops.plan import (
    DiscoveryQuery,
    PipelinePlanner,
    PlanningError,
    PlanningErrorCode,
    PlanningRequest,
    PlanningStage,
    RulePlanGenerator,
)


class _UniformEmbedder:
    space_id = "uniform-test-space-v1"

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, texts: tuple[str, ...]) -> Sequence[Sequence[float]]:
        self.calls.append(texts)
        return tuple((1.0, 1.0) for _ in texts)


class _FailingQueryEmbedder(_UniformEmbedder):
    def __call__(self, texts: tuple[str, ...]) -> Sequence[Sequence[float]]:
        self.calls.append(texts)
        if len(texts) == 1:
            raise RuntimeError("private-query-detail")
        return tuple((1.0, 1.0) for _ in texts)


class _IndexSubclass(OperatorEmbeddingIndex):
    pass


def _indexed_planner(
    request_registry: Any = None,
) -> tuple[PipelinePlanner, _UniformEmbedder]:
    registry = versioned_registry() if request_registry is None else request_registry
    embedder = _UniformEmbedder()
    index = OperatorEmbeddingIndex.build(registry, embedder)
    planner = PipelinePlanner(
        registry,
        RulePlanGenerator(),
        embedding_index=index,
    )
    return planner, embedder


def _discovery_request(
    *queries: DiscoveryQuery,
    allowed: tuple[str, ...] = ("avg@2.0.0", "select@2.0.0"),
    maximum: int = 40,
) -> PlanningRequest:
    return PlanningRequest(
        goal="Find operators",
        discovery_queries=queries or (DiscoveryQuery("rank"),),
        allowed_operator_ids=allowed,
        max_discovery_cards=maximum,
    )


def test_planner_accepts_only_an_exact_index_for_its_registry() -> None:
    registry = versioned_registry()
    embedder = _UniformEmbedder()
    index = OperatorEmbeddingIndex.build(registry, embedder)
    PipelinePlanner(registry, RulePlanGenerator(), embedding_index=index)

    with pytest.raises(EmbeddingDiscoveryError) as wrong_type:
        PipelinePlanner(
            registry,
            RulePlanGenerator(),
            embedding_index=cast(Any, object()),
        )
    assert wrong_type.value.reason == "BACKEND_MISMATCH"

    other_registry = versioned_registry()
    with pytest.raises(EmbeddingDiscoveryError) as wrong_registry:
        PipelinePlanner(other_registry, RulePlanGenerator(), embedding_index=index)
    assert wrong_registry.value.reason == "BACKEND_MISMATCH"

    subclass_index = _IndexSubclass.build(registry, _UniformEmbedder())
    with pytest.raises(EmbeddingDiscoveryError) as subclass:
        PipelinePlanner(registry, RulePlanGenerator(), embedding_index=subclass_index)
    assert subclass.value.reason == "BACKEND_MISMATCH"

    assert len(embedder.calls) == 1


def test_planner_without_an_index_keeps_lexical_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = versioned_registry()
    original_find = registry.find
    calls: list[tuple[str, tuple[str, ...]]] = []

    def recording_find(query: str, tags: Sequence[str] | None = None) -> Any:
        calls.append((query, tuple(tags or ())))
        return original_find(query, tags)

    monkeypatch.setattr(registry, "find", recording_find)
    result = PipelinePlanner(registry, RulePlanGenerator()).discover(
        _discovery_request(
            DiscoveryQuery("average", ("flow-aggregate",)),
            allowed=("avg@2.0.0",),
        )
    )

    assert result.operator_ids == ("avg@2.0.0",)
    assert calls == [("average", ("flow-aggregate",))]


def test_embedding_discovery_keeps_version_and_allowlist_admission() -> None:
    planner, _ = _indexed_planner()

    result = planner.discover(_discovery_request(DiscoveryQuery("rank")))

    assert result.operator_ids == ("avg@2.0.0", "select@2.0.0")


def test_embedding_discovery_keeps_exact_and_tag_filtering() -> None:
    planner, _ = _indexed_planner()

    result = planner.discover(
        _discovery_request(
            DiscoveryQuery(
                "rank",
                ("flow-aggregate", "capability-average"),
            )
        )
    )

    assert result.operator_ids == ("avg@2.0.0",)


def test_embedding_discovery_keeps_the_per_query_limit() -> None:
    planner, _ = _indexed_planner()

    result = planner.discover(_discovery_request(DiscoveryQuery("rank", limit=1)))

    assert result.operator_ids == ("avg@2.0.0",)


def test_embedding_discovery_removes_duplicates_before_filling_the_next_query() -> None:
    planner, _ = _indexed_planner()

    result = planner.discover(
        _discovery_request(
            DiscoveryQuery("first", limit=1),
            DiscoveryQuery("second", limit=1),
        )
    )

    assert result.operator_ids == ("avg@2.0.0", "select@2.0.0")


def test_embedding_discovery_keeps_the_request_wide_limit() -> None:
    planner, _ = _indexed_planner()

    result = planner.discover(
        _discovery_request(
            DiscoveryQuery("first", limit=1),
            DiscoveryQuery("second", limit=1),
            maximum=1,
        )
    )

    assert result.operator_ids == ("avg@2.0.0",)


def test_planner_contains_an_embedding_query_failure() -> None:
    registry = versioned_registry()
    embedder = _FailingQueryEmbedder()
    index = OperatorEmbeddingIndex.build(registry, embedder)
    planner = PipelinePlanner(registry, RulePlanGenerator(), embedding_index=index)

    with pytest.raises(PlanningError) as caught:
        planner.discover(_discovery_request(DiscoveryQuery("rank")))

    assert caught.value.record.code is PlanningErrorCode.DISCOVERY_FAILED
    assert caught.value.record.stage is PlanningStage.DISCOVERY
    assert caught.value.record.message == "operator discovery failed"
    assert "private-query-detail" not in str(caught.value)


class _ContentEmbedder:
    space_id = "content-keywords-v1"

    _FILTER_WORDS = frozenset({"filter", "keep", "select", "where"})
    _AVERAGE_WORDS = frozenset({"average", "avg", "mean"})

    def __call__(self, texts: tuple[str, ...]) -> Sequence[Sequence[float]]:
        vectors: list[tuple[float, float, float]] = []
        for text in texts:
            words = set(re.findall(r"[a-z0-9_]+", text.lower()))
            vectors.append(
                (
                    float(len(words & self._FILTER_WORDS)),
                    float(len(words & self._AVERAGE_WORDS)),
                    1.0,
                )
            )
        return vectors


def _content_plan(
    first_query: str,
    second_query: str,
) -> tuple[PipelinePlanner, PlanningRequest]:
    registry = versioned_registry()
    planner = PipelinePlanner(
        registry,
        RulePlanGenerator(),
        embedding_index=OperatorEmbeddingIndex.build(registry, _ContentEmbedder()),
    )
    request = PlanningRequest(
        goal="Find the average total above 100",
        discovery_queries=(
            DiscoveryQuery(first_query, limit=1),
            DiscoveryQuery(second_query, limit=1),
        ),
        operator_attributes={
            "select": {"operand_key": "total", "operand": ">", "operand_val": 100},
            "avg": {"avg_key": "total", "output_key": "average_total"},
        },
        allowed_operator_ids=("select@2.0.0", "avg@2.0.0", "argmax@2.0.0"),
        input_label="orders",
        output_label="answer",
    )
    return planner, request


def _run_content_plan(first_query: str, second_query: str) -> Any:
    planner, request = _content_plan(first_query, second_query)
    return planner.run(
        request,
        [
            [
                {"order_id": 1, "total": 80.0},
                {"order_id": 2, "total": 125.0},
                {"order_id": 3, "total": 210.0},
                {"order_id": 4, "total": 100.0},
            ]
        ],
    )


def test_embedding_discovery_drives_a_rule_plan_through_execution() -> None:
    result = _run_content_plan("keep expensive orders", "mean order total")

    assert result.planning.discovery.operator_ids == ("select@2.0.0", "avg@2.0.0")
    assert result.planning.preflight.operator_ids == ("select@2.0.0", "avg@2.0.0")
    assert result.execution.succeeded
    assert result.execution.output_data == [[{"average_total": 167.5}]]


@pytest.mark.parametrize(
    ("first_query", "second_query", "discovered"),
    [
        ("mean order total", "mean order total", ("avg@2.0.0", "argmax@2.0.0")),
        ("unrelated tokens", "mean order total", ("argmax@2.0.0", "avg@2.0.0")),
        ("keep expensive orders", "keep expensive orders", ("select@2.0.0", "argmax@2.0.0")),
        ("keep expensive orders", "unrelated tokens", ("select@2.0.0", "argmax@2.0.0")),
    ],
)
def test_rule_plan_requires_both_embedding_query_axes(
    first_query: str,
    second_query: str,
    discovered: tuple[str, str],
) -> None:
    planner, request = _content_plan(first_query, second_query)
    assert planner.discover(request).operator_ids == discovered

    with pytest.raises(PlanningError) as caught:
        planner.plan(request)

    assert caught.value.record.code is PlanningErrorCode.DISCOVERY_RESULT_INVALID
    assert caught.value.record.stage is PlanningStage.DISCOVERY
