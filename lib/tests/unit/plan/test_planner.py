from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from copy import deepcopy
from dataclasses import replace
from typing import Any, ClassVar, NoReturn, cast

import pytest

from blue_data_ops.operators import AttributeSpec, Operator, OperatorRegistry, versioned_registry
from blue_data_ops.operators.types import Attributes, DataBundle, ErrorCategory, Properties
from blue_data_ops.plan import (
    DataContextSnapshot,
    DataPipeline,
    DataScope,
    DiscoveryQuery,
    DiscoverySnapshot,
    NodeType,
    PipelineExecutor,
    PipelinePlanner,
    PlanDraft,
    PlanningError,
    PlanningErrorCode,
    PlanningErrorRecord,
    PlanningRequest,
    PlanningStage,
    PlanStep,
    RequireSinglePlan,
    RulePlanGenerator,
)
from blue_data_ops.plan.planner import PlanRule


def _order_request() -> PlanningRequest:
    return PlanningRequest(
        goal="Find the average total above 100",
        discovery_queries=(
            DiscoveryQuery(
                "filter",
                ("flow-transform", "accepts-data", "capability-filter"),
            ),
            DiscoveryQuery(
                "average",
                ("flow-aggregate", "accepts-data", "capability-average"),
            ),
        ),
        operator_attributes={
            "select": {
                "operand_key": "total",
                "operand": ">",
                "operand_val": 100,
            },
            "avg": {"avg_key": "total", "output_key": "average_total"},
        },
        allowed_operator_ids=("select@2.0.0", "avg@2.0.0"),
        input_label="orders",
        output_label="answer",
    )


def test_discovers_compiles_and_executes_select_then_average() -> None:
    planner = PipelinePlanner(versioned_registry(), RulePlanGenerator())

    result = planner.run(
        _order_request(),
        [
            [
                {"order_id": 1, "total": 80.0},
                {"order_id": 2, "total": 125.0},
                {"order_id": 3, "total": 210.0},
                {"order_id": 4, "total": 100.0},
            ]
        ],
    )

    assert result.planning.discovery.operator_ids == ("select@2.0.0", "avg@2.0.0")
    assert result.planning.preflight.operator_ids == ("select@2.0.0", "avg@2.0.0")
    assert result.execution.succeeded
    assert result.execution.output_data == [[{"average_total": 167.5}]]


def test_query_limit_counts_cards_after_version_and_allowlist_filtering() -> None:
    planner = PipelinePlanner(versioned_registry(), RulePlanGenerator())
    request = PlanningRequest(
        goal="Filter rows",
        discovery_queries=(DiscoveryQuery("filter", limit=1),),
        allowed_operator_ids=("select@2.0.0",),
    )

    assert planner.discover(request).operator_ids == ("select@2.0.0",)


class _CountingOperator(Operator):
    name: ClassVar[str] = "counting"
    description: ClassVar[str] = "Count body entries."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def __init__(self) -> None:
        self.calls = 0
        super().__init__()

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        del attributes, properties
        self.calls += 1
        return input_data


def _fixed_rule(draft: PlanDraft) -> PlanRule:
    def rule(
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None,
    ) -> PlanDraft:
        del request, discovery, data_context
        return draft

    return rule


def _order_draft() -> PlanDraft:
    return PlanDraft(
        (
            PlanStep(
                "select",
                "select@2.0.0",
                {
                    "operand_key": "total",
                    "operand": ">",
                    "operand_val": 100,
                },
            ),
            PlanStep(
                "average",
                "avg@2.0.0",
                {"avg_key": "total", "output_key": "average_total"},
                depends_on=("select",),
            ),
        )
    )


def test_preflight_resolves_the_plan_without_entering_operator_bodies() -> None:
    operator = _CountingOperator()
    registry = OperatorRegistry()
    registry.register(operator, "2.0.0")
    draft = PlanDraft((PlanStep("count", "counting@2.0.0"),))
    planner = PipelinePlanner(registry, RulePlanGenerator((_fixed_rule(draft),)))
    request = PlanningRequest(
        goal="Count the rows",
        discovery_queries=(DiscoveryQuery("counting"),),
    )

    planning = planner.plan(request)

    assert planning.preflight.operator_ids == ("counting@2.0.0",)
    assert operator.calls == 0
    before = deepcopy(planning.pipeline.to_dict())
    repeated = PipelineExecutor(registry).preflight(planning.pipeline)
    assert repeated.operator_ids == ("counting@2.0.0",)
    assert planning.pipeline.to_dict() == before
    assert operator.calls == 0
    execution = planner.execute(planning, [[{"x": 1}]])
    assert execution.succeeded
    assert operator.calls == 1


def test_generated_step_labels_cannot_collide_with_pipeline_nodes() -> None:
    cases = (
        ("orders", "answer", "orders_2", "answer_2"),
        ("orders", "orders", "orders_2", "orders_3"),
    )
    for first_label, second_label, first_materialized, second_materialized in cases:
        original = _order_draft()
        draft = PlanDraft(
            (
                replace(original.steps[0], label=first_label),
                replace(original.steps[1], label=second_label),
            )
        )
        planner = PipelinePlanner(versioned_registry(), RulePlanGenerator((_fixed_rule(draft),)))

        result = planner.plan(_order_request())

        for label, node_type in (
            ("orders", NodeType.INPUT),
            ("answer", NodeType.OUTPUT),
            (first_materialized, NodeType.OPERATOR),
            (second_materialized, NodeType.OPERATOR),
        ):
            node = result.pipeline.get_node_by_label(label)
            assert node is not None
            assert node.get_type() == str(node_type)
        assert result.preflight.operator_ids == ("select@2.0.0", "avg@2.0.0")


def test_request_endpoint_labels_must_differ_before_generation() -> None:
    planner = PipelinePlanner(versioned_registry(), RulePlanGenerator())
    request = replace(_order_request(), output_label="orders")

    with pytest.raises(PlanningError, match="input and output labels must differ"):
        planner.plan(request)


class _RaisingGenerator:
    def generate(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None,
    ) -> Sequence[PlanDraft]:
        del request, discovery, data_context
        raise RuntimeError("provider-payload-should-not-leak")


class _KnownFailureGenerator:
    def generate(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None,
    ) -> Sequence[PlanDraft]:
        del request, discovery, data_context
        raise PlanningError("known planning failure")


class _MalformedContainerGenerator:
    def generate(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None,
    ) -> Sequence[PlanDraft]:
        del request, discovery, data_context
        return cast(Sequence[PlanDraft], object())


class _MalformedCandidateGenerator:
    def generate(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None,
    ) -> Sequence[PlanDraft]:
        del request, discovery, data_context
        return cast(Sequence[PlanDraft], (object(),))


class _RaisingSequence(list[PlanDraft]):
    def __iter__(self) -> Iterator[PlanDraft]:
        raise RuntimeError("iterator-detail-should-not-leak")


class _RaisingIterationGenerator:
    def generate(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None,
    ) -> Sequence[PlanDraft]:
        del request, discovery, data_context
        return _RaisingSequence()


class _ManyCandidatesGenerator:
    def generate(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None,
    ) -> Sequence[PlanDraft]:
        del discovery, data_context
        draft = _order_draft()
        return (draft,) * (request.max_candidates + 1)


class _RaisingSelector:
    def select(self, candidates: Sequence[PlanDraft]) -> PlanDraft:
        del candidates
        raise LookupError("selector-detail-should-not-leak")


class _KnownFailureSelector:
    def __init__(self, error: PlanningError) -> None:
        self.error = error

    def select(self, candidates: Sequence[PlanDraft]) -> PlanDraft:
        del candidates
        raise self.error


class _MalformedSelector:
    def select(self, candidates: Sequence[PlanDraft]) -> PlanDraft:
        del candidates
        return cast(PlanDraft, object())


class _MutatingSelector:
    def __init__(self) -> None:
        self.received: Sequence[PlanDraft] | None = None

    def select(self, candidates: Sequence[PlanDraft]) -> PlanDraft:
        self.received = candidates
        selected = deepcopy(candidates[0])
        attributes = cast(dict[str, object], candidates[0].steps[0].attributes)
        attributes["runtime"] = object()
        return selected


class _ReturningMutatedSelector:
    def select(self, candidates: Sequence[PlanDraft]) -> PlanDraft:
        attributes = cast(dict[str, object], candidates[0].steps[0].attributes)
        attributes["runtime"] = object()
        return candidates[0]


@pytest.mark.parametrize(
    ("generator", "match", "code"),
    [
        (
            _RaisingGenerator(),
            "plan generation failed",
            PlanningErrorCode.GENERATION_FAILED,
        ),
        (
            _MalformedContainerGenerator(),
            "malformed candidates",
            PlanningErrorCode.GENERATION_RESULT_INVALID,
        ),
        (
            _MalformedCandidateGenerator(),
            "malformed candidate",
            PlanningErrorCode.GENERATION_RESULT_INVALID,
        ),
        (
            _RaisingIterationGenerator(),
            "candidate iteration failed",
            PlanningErrorCode.GENERATION_FAILED,
        ),
    ],
)
def test_generator_boundary_contains_unexpected_failures(
    generator: Any,
    match: str,
    code: PlanningErrorCode,
) -> None:
    planner = PipelinePlanner(versioned_registry(), generator)

    with pytest.raises(PlanningError, match=match) as caught:
        planner.plan(_order_request())

    assert "payload" not in str(caught.value)
    assert "iterator-detail" not in str(caught.value)
    assert caught.value.record.category is ErrorCategory.FAILED
    assert caught.value.record.code is code
    assert caught.value.record.stage is PlanningStage.GENERATION
    assert caught.value.record.message == str(caught.value)
    assert not caught.value.record.retryable


def test_generator_boundary_preserves_existing_planning_errors() -> None:
    planner = PipelinePlanner(versioned_registry(), _KnownFailureGenerator())

    with pytest.raises(PlanningError, match="known planning failure") as caught:
        planner.plan(_order_request())

    assert caught.value.record == (
        ErrorCategory.FAILED,
        PlanningErrorCode.GENERATION_FAILED,
        PlanningStage.GENERATION,
        "known planning failure",
        False,
        None,
    )


def test_planning_error_public_values_are_stable() -> None:
    assert tuple(stage.value for stage in PlanningStage) == (
        "VALIDATION",
        "DISCOVERY",
        "DATA_CONTEXT",
        "GENERATION",
        "SELECTION",
        "COMPILATION",
        "PREFLIGHT",
    )
    assert tuple(code.value for code in PlanningErrorCode) == (
        "INVALID_REQUEST",
        "DISCOVERY_FAILED",
        "DISCOVERY_RESULT_INVALID",
        "DATA_CONTEXT_REQUIRED",
        "DATA_CONTEXT_UNAVAILABLE",
        "DATA_CONTEXT_SCOPE_MISMATCH",
        "DATA_CONTEXT_RESULT_INVALID",
        "DATA_CONTEXT_LIMIT_EXCEEDED",
        "DATA_CONTEXT_FAILED",
        "DATA_CONTEXT_DISCLOSURE_REQUIRED",
        "GENERATION_FAILED",
        "GENERATION_RESULT_INVALID",
        "GENERATOR_DEPENDENCY_MISSING",
        "GENERATOR_REQUEST_REJECTED",
        "GENERATOR_TIMEOUT",
        "GENERATOR_RATE_LIMITED",
        "GENERATOR_UNAVAILABLE",
        "GENERATOR_REFUSED",
        "GENERATOR_RESPONSE_INVALID",
        "CANDIDATE_LIMIT_EXCEEDED",
        "NO_CANDIDATES",
        "AMBIGUOUS_CANDIDATES",
        "SELECTION_FAILED",
        "SELECTION_RESULT_INVALID",
        "PLAN_INVALID",
        "PLAN_LIMIT_EXCEEDED",
        "COMPILATION_FAILED",
        "PREFLIGHT_FAILED",
        "RESULT_COPY_FAILED",
    )
    assert PlanningErrorRecord._fields == (
        "category",
        "code",
        "stage",
        "message",
        "retryable",
        "suggestion",
    )


def test_selector_boundary_contains_unexpected_failures() -> None:
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(_order_draft()),)),
        cast(RequireSinglePlan, _RaisingSelector()),
    )

    with pytest.raises(PlanningError, match="plan selection failed") as caught:
        planner.plan(_order_request())

    assert "selector-detail" not in str(caught.value)
    assert caught.value.record.category is ErrorCategory.FAILED
    assert caught.value.record.code is PlanningErrorCode.SELECTION_FAILED
    assert caught.value.record.stage is PlanningStage.SELECTION


def test_selector_boundary_preserves_existing_planning_error_and_record() -> None:
    expected = PlanningError("known selection failure")
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(_order_draft()),)),
        cast(RequireSinglePlan, _KnownFailureSelector(expected)),
    )

    with pytest.raises(PlanningError) as caught:
        planner.plan(_order_request())

    assert caught.value is expected
    assert caught.value.record is expected.record


def test_selector_boundary_rejects_a_malformed_selection() -> None:
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(_order_draft()),)),
        cast(RequireSinglePlan, _MalformedSelector()),
    )

    with pytest.raises(PlanningError, match="malformed candidate") as caught:
        planner.plan(_order_request())

    assert caught.value.record.code is PlanningErrorCode.SELECTION_RESULT_INVALID
    assert caught.value.record.stage is PlanningStage.SELECTION


def test_selector_cannot_mutate_retained_candidates() -> None:
    selector = _MutatingSelector()
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(_order_draft()),)),
        cast(RequireSinglePlan, selector),
    )

    result = planner.plan(_order_request())

    assert result.candidates == (_order_draft(),)
    assert result.selected == _order_draft()
    assert result.candidates[0] is not result.selected
    assert result.candidates[0].steps[0].attributes is not result.selected.steps[0].attributes
    assert selector.received is not None
    assert selector.received[0] is not result.candidates[0]
    assert selector.received[0].steps[0].attributes is not result.candidates[0].steps[0].attributes


def test_selector_cannot_return_a_mutated_nonportable_candidate() -> None:
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(_order_draft()),)),
        cast(RequireSinglePlan, _ReturningMutatedSelector()),
    )

    with pytest.raises(PlanningError, match="non-portable data") as caught:
        planner.plan(_order_request())

    assert caught.value.record.category is ErrorCategory.FAILED
    assert caught.value.record.code is PlanningErrorCode.SELECTION_RESULT_INVALID
    assert caught.value.record.stage is PlanningStage.SELECTION


def test_compiler_boundary_contains_unexpected_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(_order_draft()),)),
    )

    def explode(*args: object) -> NoReturn:
        del args
        raise RuntimeError("compiler-detail-should-not-leak")

    monkeypatch.setattr(planner, "_compile", explode)

    with pytest.raises(PlanningError, match="plan compilation failed") as caught:
        planner.plan(_order_request())

    assert "compiler-detail" not in str(caught.value)
    assert caught.value.record.category is ErrorCategory.FAILED
    assert caught.value.record.code is PlanningErrorCode.COMPILATION_FAILED
    assert caught.value.record.stage is PlanningStage.COMPILATION
    assert caught.value.record.suggestion == "Check the plan compiler."


def test_operator_definition_failure_has_the_attribute_copy_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(_order_draft()),)),
    )

    def explode(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise RuntimeError("definition-payload-should-not-leak")

    monkeypatch.setattr(DataPipeline, "define_operator", explode)

    with pytest.raises(PlanningError, match="attributes could not be copied") as caught:
        planner.plan(_order_request())

    assert "definition-payload" not in str(caught.value)
    assert caught.value.record == (
        ErrorCategory.FAILED,
        PlanningErrorCode.COMPILATION_FAILED,
        PlanningStage.COMPILATION,
        "plan attributes could not be copied",
        False,
        "Use portable plan attributes.",
    )


def test_compiler_boundary_preserves_existing_planning_error_and_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(_order_draft()),)),
    )
    expected = PlanningError("known compiler failure")

    def fail(*args: object) -> NoReturn:
        del args
        raise expected

    monkeypatch.setattr(planner, "_compile", fail)

    with pytest.raises(PlanningError) as caught:
        planner.plan(_order_request())

    assert caught.value is expected
    assert caught.value.record is expected.record


def test_preflight_boundary_contains_unexpected_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(_order_draft()),)),
    )

    def explode(*args: object) -> NoReturn:
        del args
        raise RuntimeError("preflight-detail-should-not-leak")

    monkeypatch.setattr(PipelineExecutor, "preflight", explode)

    with pytest.raises(PlanningError, match="plan preflight failed") as caught:
        planner.plan(_order_request())

    assert "preflight-detail" not in str(caught.value)
    assert caught.value.record.category is ErrorCategory.FAILED
    assert caught.value.record.code is PlanningErrorCode.PREFLIGHT_FAILED
    assert caught.value.record.stage is PlanningStage.PREFLIGHT


def test_preflight_boundary_preserves_existing_planning_error_and_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(_order_draft()),)),
    )
    expected = PlanningError("known preflight failure")

    def fail(*args: object) -> NoReturn:
        del args
        raise expected

    monkeypatch.setattr(PipelineExecutor, "preflight", fail)

    with pytest.raises(PlanningError) as caught:
        planner.plan(_order_request())

    assert caught.value is expected
    assert caught.value.record is expected.record


@pytest.mark.parametrize(
    "draft",
    [
        PlanDraft(cast(tuple[PlanStep, ...], [])),
        PlanDraft(
            (
                PlanStep(
                    "select",
                    "select@2.0.0",
                    depends_on=cast(tuple[str, ...], ["missing"]),
                ),
            )
        ),
    ],
)
def test_rejects_malformed_draft_container_shapes(draft: PlanDraft) -> None:
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(draft),)),
    )

    with pytest.raises(PlanningError, match="malformed (steps|dependencies)"):
        planner.plan(_order_request())


class _RuntimeObject:
    def __repr__(self) -> str:
        return "credential-payload-should-not-leak"


@pytest.mark.parametrize("value", [_RuntimeObject(), float("nan"), float("inf"), float("-inf")])
def test_rejects_nonportable_request_attributes_without_leaking_values(value: object) -> None:
    attributes = deepcopy(dict(_order_request().operator_attributes))
    attributes["select"] = {**attributes["select"], "operand_val": value}
    request = replace(_order_request(), operator_attributes=attributes)

    with pytest.raises(PlanningError, match="non-portable data") as caught:
        PipelinePlanner(versioned_registry(), RulePlanGenerator()).plan(request)

    assert "credential-payload" not in str(caught.value)
    assert caught.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.INVALID_REQUEST,
        PlanningStage.VALIDATION,
        "planning request contains non-portable data",
        False,
        "Correct the planning request and try again.",
    )


def test_rejects_nonportable_generated_attributes_and_labels() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    drafts = (
        PlanDraft(
            (
                PlanStep(
                    "select",
                    "select@2.0.0",
                    cast(dict[str, Any], {"runtime": _RuntimeObject()}),
                ),
            )
        ),
        PlanDraft(
            (
                PlanStep(
                    "select",
                    "select@2.0.0",
                    cast(dict[str, Any], cyclic),
                ),
            )
        ),
        PlanDraft(
            (PlanStep("select", "select@2.0.0"),),
            label=cast(str, _RuntimeObject()),
        ),
    )
    for draft in drafts:
        planner = PipelinePlanner(
            versioned_registry(),
            RulePlanGenerator((_fixed_rule(draft),)),
        )
        with pytest.raises(PlanningError, match="(non-portable data|malformed label)"):
            planner.plan(_order_request())


class _IntSubclass(int):
    pass


class _ListSubclass(list[object]):
    pass


class _DictSubclass(dict[str, object]):
    pass


class _TupleSubclass(tuple[object, ...]):
    def __bool__(self) -> bool:
        raise RuntimeError("constructor-payload-should-not-leak")


class _ExplodingStr(str):
    def strip(self, chars: str | None = None) -> str:
        del chars
        raise RuntimeError("constructor-payload-should-not-leak")


@pytest.mark.parametrize(
    "value",
    [
        {1: "non-string key"},
        _IntSubclass(1),
        _ListSubclass(),
        _DictSubclass(),
    ],
)
def test_rejects_nonportable_json_lookalikes(value: object) -> None:
    attributes = deepcopy(dict(_order_request().operator_attributes))
    attributes["select"] = {**attributes["select"], "operand_val": value}
    request = replace(_order_request(), operator_attributes=attributes)

    with pytest.raises(PlanningError, match="non-portable data"):
        PipelinePlanner(versioned_registry(), RulePlanGenerator()).plan(request)


def test_rejects_plan_data_nested_beyond_the_depth_limit() -> None:
    nested: list[object] = []
    for _ in range(65):
        nested = [nested]
    attributes = deepcopy(dict(_order_request().operator_attributes))
    attributes["select"] = {**attributes["select"], "operand_val": nested}
    request = replace(_order_request(), operator_attributes=attributes)

    with pytest.raises(PlanningError, match="non-portable data"):
        PipelinePlanner(versioned_registry(), RulePlanGenerator()).plan(request)


@pytest.mark.parametrize(
    "operator_attributes",
    [
        {"select": {}, "avg": {}},
        {
            "select": {"operand_key": "total"},
            "avg": {"avg_key": "total"},
        },
    ],
)
def test_default_rule_requires_all_structural_attribute_keys(
    operator_attributes: dict[str, dict[str, object]],
) -> None:
    request = replace(_order_request(), operator_attributes=operator_attributes)

    with pytest.raises(PlanningError, match="attributes are incomplete"):
        PipelinePlanner(versioned_registry(), RulePlanGenerator()).plan(request)


def test_default_rule_leaves_attribute_value_semantics_to_execution() -> None:
    attributes = deepcopy(dict(_order_request().operator_attributes))
    attributes["select"] = {**attributes["select"], "operand": "not-an-operand"}
    request = replace(_order_request(), operator_attributes=attributes)
    planner = PipelinePlanner(versioned_registry(), RulePlanGenerator())

    planning = planner.plan(request)
    execution = planner.execute(planning, [[{"total": 125.0}]])

    assert not execution.succeeded
    assert execution.node_runs[0].exec_meta.errors


def test_requires_an_explicit_choice_when_rules_return_multiple_plans() -> None:
    draft = PlanDraft((PlanStep("select", "select@2.0.0"),))
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(draft), _fixed_rule(draft))),
    )
    request = PlanningRequest(
        goal="Filter rows",
        discovery_queries=(DiscoveryQuery("select"),),
    )

    with pytest.raises(PlanningError, match="produced 2 candidates") as caught:
        planner.plan(request)

    assert caught.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.AMBIGUOUS_CANDIDATES,
        PlanningStage.SELECTION,
        "planning produced 2 candidates",
        False,
        "Provide a selector that chooses one plan.",
    )


def test_rejects_an_unsupported_operator_version() -> None:
    draft = PlanDraft((PlanStep("select", "select@1.0.0"),))
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(draft),)),
    )
    request = PlanningRequest(
        goal="Filter rows",
        discovery_queries=(DiscoveryQuery("select"),),
    )

    with pytest.raises(PlanningError, match="requires supported pinned operator ids"):
        planner.plan(request)


def test_rejects_an_operator_outside_the_discovery_snapshot() -> None:
    draft = PlanDraft((PlanStep("average", "avg@2.0.0"),))
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(draft),)),
    )
    request = PlanningRequest(
        goal="Average rows",
        discovery_queries=(
            DiscoveryQuery(
                "filter",
                ("flow-transform", "accepts-data", "capability-filter"),
            ),
        ),
    )

    with pytest.raises(PlanningError, match="was not discovered"):
        planner.plan(request)


def test_a_retired_step_is_rejected_as_undiscovered() -> None:
    draft = PlanDraft(
        (
            PlanStep(
                "breakdown",
                "query_breakdown@2.0.0",
                {"query": "How many rows?"},
            ),
        )
    )
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(draft),)),
    )
    request = PlanningRequest(
        goal="Break down a question",
        discovery_queries=(DiscoveryQuery("query_breakdown"),),
    )

    with pytest.raises(PlanningError) as caught:
        planner.plan(request)

    assert caught.value.record.message == "operator 'query_breakdown@2.0.0' was not discovered"
    assert caught.value.record.category is ErrorCategory.RECOVERABLE
    assert caught.value.record.code is PlanningErrorCode.PLAN_INVALID
    assert caught.value.record.stage is PlanningStage.COMPILATION


def test_rejects_a_cyclic_draft() -> None:
    draft = PlanDraft(
        (
            PlanStep("select", "select@2.0.0", depends_on=("average",)),
            PlanStep("average", "avg@2.0.0", depends_on=("select",)),
        )
    )
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(draft),)),
    )

    with pytest.raises(PlanningError, match="contains a cycle"):
        planner.plan(_order_request())


def test_discovery_failure_has_a_non_leaking_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = versioned_registry()
    failure = RuntimeError("registry-payload-should-not-leak")

    def explode(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise failure

    monkeypatch.setattr(registry, "find", explode)

    with pytest.raises(PlanningError, match="operator discovery failed") as caught:
        PipelinePlanner(registry, RulePlanGenerator()).discover(_order_request())

    assert "registry-payload" not in str(caught.value)
    assert caught.value is not failure
    assert caught.value.record == (
        ErrorCategory.FAILED,
        PlanningErrorCode.DISCOVERY_FAILED,
        PlanningStage.DISCOVERY,
        "operator discovery failed",
        False,
        "Check the operator registry and discovery filters.",
    )


def test_discovery_preserves_an_existing_planning_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = versioned_registry()
    expected = PlanningError("known discovery failure")

    def explode(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise expected

    monkeypatch.setattr(registry, "find", explode)

    with pytest.raises(PlanningError) as caught:
        PipelinePlanner(registry, RulePlanGenerator()).discover(_order_request())

    assert caught.value is expected
    assert caught.value.record is expected.record


@pytest.mark.parametrize(
    "construct",
    [
        lambda: DiscoveryQuery(cast(str, _ExplodingStr("query"))),
        lambda: DiscoveryQuery("query", cast(tuple[str, ...], ["tag"])),
        lambda: DiscoveryQuery("query", cast(tuple[str, ...], _TupleSubclass(("tag",)))),
        lambda: DiscoveryQuery("query", limit=cast(int, True)),
        lambda: DataScope(cast(str, _ExplodingStr("scope")), "shop", "public"),
        lambda: DataScope("demo", "shop", "public", cast("tuple[str, ...]", ["orders"])),
        lambda: PlanningRequest(
            goal=cast(str, _ExplodingStr("goal")),
            discovery_queries=(DiscoveryQuery("query"),),
        ),
        lambda: PlanningRequest(
            goal="goal",
            discovery_queries=cast(
                tuple[DiscoveryQuery, ...],
                [DiscoveryQuery("query")],
            ),
        ),
        lambda: PlanningRequest(
            goal="goal",
            discovery_queries=cast(
                tuple[DiscoveryQuery, ...],
                _TupleSubclass((DiscoveryQuery("query"),)),
            ),
        ),
        lambda: PlanningRequest(
            goal="goal",
            discovery_queries=(DiscoveryQuery("query"),),
            max_steps=cast(int, _IntSubclass(1)),
        ),
    ],
)
def test_public_records_reject_hostile_runtime_types_before_using_them(
    construct: Callable[[], object],
) -> None:
    with pytest.raises(PlanningError) as caught:
        construct()

    assert "constructor-payload" not in str(caught.value)
    assert caught.value.record.category is ErrorCategory.RECOVERABLE
    assert caught.value.record.code is PlanningErrorCode.INVALID_REQUEST
    assert caught.value.record.stage is PlanningStage.VALIDATION
    assert not caught.value.record.retryable


def test_candidate_limit_and_empty_selection_have_stable_records() -> None:
    registry = versioned_registry()
    with pytest.raises(PlanningError, match="candidate limit") as limited:
        PipelinePlanner(registry, _ManyCandidatesGenerator()).plan(_order_request())

    assert limited.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.CANDIDATE_LIMIT_EXCEEDED,
        PlanningStage.GENERATION,
        "planning exceeded its candidate limit",
        False,
        "Return fewer candidates or raise max_candidates.",
    )

    request = replace(_order_request(), goal="List recent orders")
    with pytest.raises(PlanningError, match="no candidates") as empty:
        PipelinePlanner(registry, RulePlanGenerator()).plan(request)

    assert empty.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.NO_CANDIDATES,
        PlanningStage.SELECTION,
        "planning produced no candidates",
        False,
        "Adjust discovery or generation so at least one plan is produced.",
    )


def test_compilation_rejection_has_a_stable_record() -> None:
    draft = PlanDraft((PlanStep("select", "select@1.0.0"),))
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((_fixed_rule(draft),)),
    )

    with pytest.raises(
        PlanningError,
        match="requires supported pinned operator ids",
    ) as caught:
        planner.plan(
            PlanningRequest(
                goal="Filter rows",
                discovery_queries=(DiscoveryQuery("select"),),
            )
        )

    assert caught.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.PLAN_INVALID,
        PlanningStage.COMPILATION,
        "planner requires supported pinned operator ids",
        False,
        "Use discovered supported pinned operators in a valid bounded plan.",
    )


def test_result_copy_failure_has_a_non_leaking_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_deepcopy = deepcopy

    def fail_request_copy(value: object) -> object:
        if type(value) is PlanningRequest:
            raise RuntimeError("copy-payload-should-not-leak")
        return real_deepcopy(value)

    monkeypatch.setattr("blue_data_ops.plan.planner.deepcopy", fail_request_copy)

    with pytest.raises(PlanningError, match="could not be copied") as caught:
        PipelinePlanner(versioned_registry(), RulePlanGenerator()).plan(_order_request())

    assert "copy-payload" not in str(caught.value)
    assert caught.value.record == (
        ErrorCategory.FAILED,
        PlanningErrorCode.RESULT_COPY_FAILED,
        PlanningStage.COMPILATION,
        "planning request could not be copied",
        False,
        "Use a planning request containing portable data.",
    )


# --- Retired IDs: compatibility discovery versus ordinary planning ------------------ #
RETIRED_PLAN_IDS = (
    "plan_discover@2.0.0",
    "multipart_query@2.0.0",
    "nl2query_router@2.0.0",
    "query_breakdown@2.0.0",
)


def _admission_request() -> PlanningRequest:
    return PlanningRequest(
        goal="Average order total above 100",
        discovery_queries=(
            DiscoveryQuery("plan", limit=4),
            DiscoveryQuery("select", limit=2),
            DiscoveryQuery("avg", limit=1),
        ),
        allowed_operator_ids=(),
        max_discovery_cards=12,
    )


class _OfferedRecorder(RulePlanGenerator):
    """A rule generator that also keeps what plan() offered it."""

    def __init__(self, rules: Sequence[PlanRule] | None = None) -> None:
        super().__init__(rules)
        self.offered: list[tuple[str, ...]] = []

    def generate(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None = None,
    ) -> tuple[PlanDraft, ...]:
        self.offered.append(discovery.operator_ids)
        return super().generate(request, discovery, data_context)


def test_public_discover_offers_only_retained_v2_history() -> None:
    planner = PipelinePlanner(versioned_registry(), RulePlanGenerator())

    assert planner.discover(_admission_request()).operator_ids == (
        "data_discover@2.0.0",
        "semantic_project@2.0.0",
        "select@2.0.0",
        "avg@2.0.0",
    )


def test_ordinary_planning_offers_only_active_policy_cards() -> None:
    draft = replace(
        _order_draft(),
        steps=(
            _order_draft().steps[0],
            replace(_order_draft().steps[1], operator_id="avg@3.0.0"),
        ),
    )
    generator = _OfferedRecorder((_fixed_rule(draft),))
    planner = PipelinePlanner(versioned_registry(), generator)

    result = planner.plan(_admission_request())

    assert result.discovery.operator_ids == (
        "data_discover@2.0.0",
        "semantic_project@3.0.0",
        "select@2.0.0",
        "avg@3.0.0",
    )
    assert generator.offered == [result.discovery.operator_ids]


def test_compatibility_discovery_and_active_planning_have_distinct_version_policies() -> None:
    draft = replace(
        _order_draft(),
        steps=(
            _order_draft().steps[0],
            replace(_order_draft().steps[1], operator_id="avg@3.0.0"),
        ),
    )
    planner = PipelinePlanner(versioned_registry(), _OfferedRecorder((_fixed_rule(draft),)))
    request = _admission_request()

    compatible = planner.discover(request).operator_ids
    active = planner.plan(request).discovery.operator_ids

    assert all(operator_id.endswith("@2.0.0") for operator_id in compatible)
    assert active == (
        "data_discover@2.0.0",
        "semantic_project@3.0.0",
        "select@2.0.0",
        "avg@3.0.0",
    )


def test_ordinary_planning_and_compatibility_discovery_share_one_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`discover()` and `plan()` reach discovery through the same parameterized body."""

    registry = versioned_registry()

    def explode(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise RuntimeError("registry-payload-should-not-leak")

    monkeypatch.setattr(registry, "find", explode)
    planner = PipelinePlanner(registry, RulePlanGenerator())
    envelope = (
        ErrorCategory.FAILED,
        PlanningErrorCode.DISCOVERY_FAILED,
        PlanningStage.DISCOVERY,
        "operator discovery failed",
        False,
        "Check the operator registry and discovery filters.",
    )

    with pytest.raises(PlanningError) as public:
        planner.discover(_order_request())
    with pytest.raises(PlanningError) as active:
        planner.plan(_order_request())

    assert public.value.record == envelope
    assert active.value.record == envelope
    assert "registry-payload" not in str(active.value)


def test_a_request_restricted_to_retired_cards_is_invalid() -> None:
    planner = PipelinePlanner(versioned_registry(), RulePlanGenerator())
    request = PlanningRequest(
        goal="Break a question down",
        discovery_queries=(DiscoveryQuery("plan", limit=4),),
        allowed_operator_ids=RETIRED_PLAN_IDS,
    )

    assert planner.discover(request).operator_ids == ()

    with pytest.raises(PlanningError, match="supported pinned ids") as caught:
        planner.plan(request)

    assert caught.value.record.code is PlanningErrorCode.INVALID_REQUEST
    assert caught.value.record.stage is PlanningStage.VALIDATION
