from __future__ import annotations

import copy
import time
from collections.abc import Callable
from threading import Event
from typing import Any, cast

import pytest

import blue_data_ops.plan.refiner as refiner_module
from blue_data_ops.operators import (
    Attributes,
    DataBundle,
    ErrorCategory,
    ErrorCode,
    ErrorStage,
    OperatorRegistry,
    ProjectOperator,
    Properties,
    SelectOperator,
)
from blue_data_ops.operators.plan_discover_operator import PlanDiscoverOperator
from blue_data_ops.plan import (
    DataPipeline,
    DeclarativeOperator,
    NodeType,
    RefinableOperator,
    declarative_operator_refiner,
    normalized_declarative_operator_refiner,
)
from blue_data_ops.plan import pipeline as pipeline_module
from blue_data_ops.plan.types import PlanRecord

INPUT: DataBundle = [[]]
VALID_ATTRIBUTES = {
    "task": "starter",
    "data": "rows",
    "approximate": True,
    "search_query": "starter",
}


def _registry() -> OperatorRegistry:
    registry = OperatorRegistry()
    registry.register(ProjectOperator(), "1.0.0", tags=("starter",))
    registry.register(SelectOperator(), "1.0.0", tags=("starter",))
    return registry


def test_plan_discover_proves_refinable_operator_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = PlanDiscoverOperator(_registry())
    attributes = dict(VALID_ATTRIBUTES)
    issued = 0

    def next_id() -> str:
        nonlocal issued
        issued += 1
        return f"id-{issued}"

    monkeypatch.setattr(pipeline_module, "_new_id", next_id)
    raw_records = operator.refiner(INPUT, attributes)
    issued = 0
    plans, meta = operator.refine(INPUT, attributes)

    assert [plan.to_dict() for plan in plans] == raw_records
    assert len(plans) == 2
    assert meta.is_empty is False
    assert meta.errors == []
    assert attributes == VALID_ATTRIBUTES
    assert operator.apply(INPUT, attributes) == [[]]
    assert operator.validate(INPUT, attributes) is True


def test_refine_validation_failure_is_recoverable() -> None:
    plans, meta = PlanDiscoverOperator(_registry()).refine(INPUT, {})
    assert plans == []
    assert meta.is_empty is False
    assert meta.errors[0] == (
        ErrorCategory.RECOVERABLE,
        ErrorCode.INVALID_INPUT,
        "plan_discover@2.0.0",
        ErrorStage.VALIDATE,
        "input validation failed",
        False,
        "supply valid input attributes",
    )


class ProbeRefiner(RefinableOperator):
    name = "probe_refiner"
    attributes = {}

    def __init__(self, case: str = "zero") -> None:
        self.case = case
        self.refiner_calls = 0

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        del attributes, properties
        return input_data

    def refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        del input_data, attributes, properties
        self.refiner_calls += 1
        if self.case == "zero":
            return []
        if self.case == "raises":
            raise RuntimeError("private refiner payload")
        if self.case == "none":
            return cast(list[PlanRecord], None)
        if self.case == "container":
            return cast(list[PlanRecord], ("bad",))
        if self.case == "record":
            return [cast(PlanRecord, {"type": "bad"})]
        raise AssertionError(self.case)


@pytest.mark.parametrize(
    "case,code,stage",
    [
        ("raises", ErrorCode.REFINEMENT_FAILED, ErrorStage.REFINE),
        ("none", ErrorCode.REFINEMENT_FAILED, ErrorStage.REFINE),
        ("container", ErrorCode.REFINEMENT_RESULT_INVALID, ErrorStage.NORMALIZE),
        ("record", ErrorCode.REFINEMENT_RESULT_INVALID, ErrorStage.NORMALIZE),
    ],
)
def test_refine_failure_rows_are_total(case: str, code: ErrorCode, stage: ErrorStage) -> None:
    operator = ProbeRefiner(case)
    plans, meta = operator.refine(INPUT, {})
    assert plans == []
    assert meta.is_empty is False
    assert meta.errors[0].code is code
    assert meta.errors[0].stage is stage
    assert "private" not in meta.errors[0].message
    assert operator.refiner_calls == 1


@pytest.mark.parametrize(
    "value",
    ["0.001", -1, 0, True, float("nan"), float("inf"), 10**400],
    ids=["string", "negative", "zero", "bool", "nan", "inf", "huge-int"],
)
def test_refine_invalid_timeout_suppresses_refiner(value: object) -> None:
    operator = ProbeRefiner()
    plans, meta = operator.refine(INPUT, {}, {"execution.timeout_seconds": value})
    assert plans == []
    assert meta.errors[0].code is ErrorCode.INVALID_INPUT
    assert meta.errors[0].operator_id == "probe_refiner@2.0.0"
    assert meta.errors[0].stage is ErrorStage.VALIDATE
    assert operator.refiner_calls == 0


class SlowRefiner(ProbeRefiner):
    def __init__(self, finished: Event) -> None:
        super().__init__()
        self.finished = finished

    def refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        del input_data, attributes, properties
        self.refiner_calls += 1
        time.sleep(0.04)
        self.finished.set()
        return []


def test_refine_timeout_discards_late_result_without_retry() -> None:
    finished = Event()
    operator = SlowRefiner(finished)
    plans, meta = operator.refine(INPUT, {}, {"execution.timeout_seconds": 0.005})
    assert plans == []
    assert meta.errors[0].code is ErrorCode.OPERATOR_TIMEOUT
    assert meta.errors[0].stage is ErrorStage.REFINE
    assert operator.refiner_calls == 1
    assert finished.wait(timeout=0.2)


class ConstructorBomb:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("private executor payload")


def test_refine_executor_construction_failure_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(refiner_module, "ThreadPoolExecutor", ConstructorBomb)
    operator = ProbeRefiner()
    _, meta = operator.refine(INPUT, {}, {"execution.timeout_seconds": 1})
    assert meta.errors[0].code is ErrorCode.REFINEMENT_FAILED
    assert meta.errors[0].message == "refinement failed"
    assert operator.refiner_calls == 0


def _two_operator_properties() -> Properties:
    return {
        "plans": [
            {
                "nodes": {
                    "op-a": {"type": "OPERATOR", "name": "select@1.0.0"},
                    "op-b": {
                        "type": "OPERATOR",
                        "name": "project@1.0.0",
                        "prev": ["op-a"],
                    },
                }
            }
        ]
    }


def test_declarative_raw_bug_is_preserved_and_normalized_refine_repairs_it() -> None:
    properties = _two_operator_properties()
    operator = DeclarativeOperator({"plans": []})
    with pytest.raises(UnboundLocalError, match="from_id"):
        operator.refiner(INPUT, {}, copy.deepcopy(properties))

    plans, meta = operator.refine(INPUT, {}, copy.deepcopy(properties))
    assert len(plans) == 1
    assert meta.errors == []
    plan = plans[0]
    operator_nodes = plan.filter_nodes(filter_node_type=["OPERATOR"])
    assert len(operator_nodes) == 2
    first, second = operator_nodes
    assert [node.get_id() for node in plan.get_next_nodes(first)] == [second]
    assert [node.get_id() for node in plan.get_prev_nodes(second)] == [first]


def test_declarative_refine_selects_topology_by_pinned_version() -> None:
    properties = _two_operator_properties()
    source = DeclarativeOperator({"plans": []})
    registry = OperatorRegistry()
    registry.register(source, "1.0.0")
    registry.register(source, "2.0.0")

    v1_plans, v1_meta = cast(
        RefinableOperator, registry.resolve("declarative_operator@1.0.0")
    ).refine(
        INPUT,
        {},
        copy.deepcopy(properties),
    )
    v2_plans, v2_meta = cast(
        RefinableOperator, registry.resolve("declarative_operator@2.0.0")
    ).refine(
        INPUT,
        {},
        copy.deepcopy(properties),
    )

    assert v1_plans == []
    assert v1_meta.errors[0].code is ErrorCode.REFINEMENT_FAILED
    assert v1_meta.errors[0].operator_id == "declarative_operator@1.0.0"
    assert len(v2_plans) == 1
    assert v2_meta.errors == []


def _uuid_sequence() -> Callable[[], str]:
    current = 0

    def create_uuid() -> str:
        nonlocal current
        current += 1
        return f"plan_{current:04d}"

    return create_uuid


def _operator_ids(pipeline: DataPipeline) -> list[str]:
    return list(pipeline.filter_nodes([str(NodeType.OPERATOR)]))


def _without_edges(value: Any) -> Any:
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {
            key: _without_edges(item)
            for key, item in mapping.items()
            if key not in {"prev", "next"}
        }
    if isinstance(value, list):
        return [_without_edges(item) for item in cast(list[object], value)]
    return value


def test_declarative_normalization_changes_only_the_stale_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    properties: Properties = {
        "plans": [
            {
                "nodes": {
                    "op-a": {
                        "type": "OPERATOR",
                        "name": "select@2.0.0",
                        "next": ["op-b"],
                    },
                    "op-b": {"type": "OPERATOR", "name": "project@2.0.0"},
                    "op-c": {
                        "type": "OPERATOR",
                        "name": "join@2.0.0",
                        "prev": ["op-b"],
                    },
                }
            }
        ]
    }

    monkeypatch.setattr(pipeline_module, "_new_id", _uuid_sequence())
    raw_record = declarative_operator_refiner(INPUT, {}, properties)[0]
    monkeypatch.setattr(pipeline_module, "_new_id", _uuid_sequence())
    normalized_record = normalized_declarative_operator_refiner(INPUT, {}, properties)[0]

    raw = DataPipeline.from_dict(raw_record)
    normalized = DataPipeline.from_dict(normalized_record)
    raw_a, raw_b, raw_c = _operator_ids(raw)
    assert raw.get_node(raw_c).get_data("prev") == [raw_a]  # type: ignore[union-attr]
    assert raw_c not in raw.get_node(raw_b).get_data("next")  # type: ignore[union-attr]

    _, normalized_b, normalized_c = _operator_ids(normalized)
    assert normalized.get_node(normalized_c).get_data("prev") == [normalized_b]  # type: ignore[union-attr]
    assert normalized_c in normalized.get_node(normalized_b).get_data("next")  # type: ignore[union-attr]
    assert _without_edges(raw_record) == _without_edges(normalized_record)
    assert raw_record != normalized_record


def test_declarative_normalization_keeps_edge_state_plan_local() -> None:
    properties: Properties = {
        "plans": [
            {
                "nodes": {
                    "op-a": {
                        "type": "OPERATOR",
                        "name": "select@2.0.0",
                        "next": ["op-b"],
                    },
                    "op-b": {"type": "OPERATOR", "name": "project@2.0.0"},
                }
            },
            {
                "nodes": {
                    "op-x": {"type": "OPERATOR", "name": "select@2.0.0"},
                    "op-y": {
                        "type": "OPERATOR",
                        "name": "project@2.0.0",
                        "prev": ["op-x"],
                    },
                }
            },
        ]
    }

    with pytest.raises(Exception, match="Undefined from node"):
        declarative_operator_refiner(INPUT, {}, copy.deepcopy(properties))

    plans, meta = DeclarativeOperator({"plans": []}).refine(
        INPUT,
        {},
        copy.deepcopy(properties),
    )
    assert len(plans) == 2
    second_source, second_target = _operator_ids(plans[1])
    assert plans[1].get_node(second_target).get_data("prev") == [second_source]  # type: ignore[union-attr]
    assert plans[1].get_node(second_source).get_data("next") == [second_target]  # type: ignore[union-attr]
    assert [DataPipeline.from_dict(plan.to_dict()).to_dict() for plan in plans] == [
        plan.to_dict() for plan in plans
    ]
    assert meta.errors == []


def test_declarative_normalization_contains_malformed_plan() -> None:
    plans, meta = DeclarativeOperator({"plans": []}).refine(
        INPUT,
        {},
        cast(Properties, {"plans": [{"nodes": {"bad": {"type": "OPERATOR"}}}]}),
    )
    assert plans == []
    assert len(meta.errors) == 1
    assert meta.errors[0].code is ErrorCode.REFINEMENT_FAILED
    assert meta.errors[0].stage is ErrorStage.REFINE
