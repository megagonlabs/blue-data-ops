"""Focused coverage for one-level normalized refinement planning."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from copy import deepcopy
from types import MethodType
from typing import Any, cast

import pytest

from blue_data_ops.operators.registry import OperatorRegistry, versioned_registry
from blue_data_ops.operators.types import ErrorCategory, ErrorRecord, ErrorStage, ExecMeta
from blue_data_ops.operators.types import ErrorCode as OperatorErrorCode
from blue_data_ops.plan import (
    DataPipeline,
    DataScope,
    DiscoveryQuery,
    DiscoverySnapshot,
    PipelinePlanner,
    PlanDraft,
    PlanningError,
    PlanningErrorCode,
    PlanningRequest,
    PlanningStage,
)

SOURCE = "multipart_query@2.0.0"
WRITE_CHILD = "create_database@2.0.0"


def planner(registry: OperatorRegistry | None = None) -> tuple[PipelinePlanner, OperatorRegistry]:
    shared = versioned_registry() if registry is None else registry
    return PipelinePlanner(shared, cast(Any, None)), shared


def request_for(
    allowed: tuple[str, ...] = (SOURCE, WRITE_CHILD),
    query: str = "multipart_query",
    **overrides: Any,
) -> PlanningRequest:
    fields: dict[str, Any] = {
        "goal": "materialize a refinement alternative",
        "discovery_queries": (DiscoveryQuery(query),),
        "allowed_operator_ids": allowed,
    }
    fields.update(overrides)
    return PlanningRequest(**fields)


def refine_empty(plan: PipelinePlanner, request: PlanningRequest | None = None) -> Any:
    return plan.plan_refinement(request or request_for(), SOURCE, [[]], {})


# --- 1. The terminal success path --------------------------------------------------- #
def test_a_terminal_alternative_becomes_a_compiled_preflighted_plan() -> None:
    plan, _ = planner()

    result = refine_empty(plan)

    assert [step.operator_id for step in result.selected.steps] == [WRITE_CHILD]
    assert [step.step_id for step in result.selected.steps] == ["step-001"]
    assert result.preflight.operator_ids == (WRITE_CHILD,)
    assert len(result.candidates) == 1


def test_the_compiled_pipeline_is_fresh_not_the_returned_one() -> None:
    plan, registry = planner()
    source = registry.resolve(SOURCE)
    returned, _ = cast(Any, source).refine([[]], {}, None)

    result = refine_empty(plan)

    assert all(result.pipeline is not alternative for alternative in returned)
    assert result.pipeline.get_id() != returned[0].get_id()


def test_discovery_is_extended_by_the_exact_child_id() -> None:
    plan, _ = planner()

    result = refine_empty(plan)

    ids = result.discovery.operator_ids
    # The source stays even though the compiled plan does not contain it: it records
    # how the candidates were produced.
    assert SOURCE in ids
    assert WRITE_CHILD in ids
    assert all(identifier.endswith("@2.0.0") for identifier in ids)


def test_mutating_a_returned_alternative_cannot_change_the_result() -> None:
    plan, _ = planner()

    result = refine_empty(plan)
    before = [dict(step.attributes) for step in result.selected.steps]
    record = result.pipeline.to_dict()
    cast(dict[str, Any], record)["label"] = "mutated-after-planning"

    assert [dict(step.attributes) for step in result.selected.steps] == before


def test_an_equal_replacement_scope_keeps_the_detached_anchor() -> None:
    plan, registry = planner()
    request = request_for(data_scope=DataScope("source", "database", "collection"))
    replacement = DataScope("source", "database", "collection")
    resolved = registry.resolve(SOURCE)
    original = cast(Any, resolved)._refine_once

    def replace_scope(*args: Any, **kwargs: Any) -> Any:
        object.__setattr__(request, "data_scope", replacement)
        return original(*args, **kwargs)

    object.__setattr__(resolved, "_refine_once", replace_scope)

    result = refine_empty(plan, request)

    assert result.request.data_scope == replacement
    assert result.request.data_scope is not replacement


def test_a_refiner_cannot_repoint_the_scope() -> None:
    plan, registry = planner()
    request = request_for(data_scope=DataScope("source", "database", "collection"))
    resolved = registry.resolve(SOURCE)
    original = cast(Any, resolved)._refine_once

    def repoint_scope(*args: Any, **kwargs: Any) -> Any:
        object.__setattr__(request, "data_scope", DataScope("source", "database", "other"))
        return original(*args, **kwargs)

    object.__setattr__(resolved, "_refine_once", repoint_scope)

    with pytest.raises(PlanningError, match="scope does not match") as caught:
        refine_empty(plan, request)

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_SCOPE_MISMATCH


class ScopeMutatingSelector:
    def __init__(self, request: PlanningRequest) -> None:
        self.request = request

    def select(self, candidates: Sequence[PlanDraft]) -> PlanDraft:
        object.__setattr__(self.request, "data_scope", DataScope("source", "database", "other"))
        return candidates[0]


def test_a_selector_cannot_repoint_the_scope() -> None:
    request = request_for(data_scope=DataScope("source", "database", "collection"))
    shared = versioned_registry()
    plan = PipelinePlanner(shared, cast(Any, None), cast(Any, ScopeMutatingSelector(request)))

    with pytest.raises(PlanningError, match="scope does not match") as caught:
        refine_empty(plan, request)

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_SCOPE_MISMATCH


def test_a_router_collection_compiles_its_matching_nl2sql_child() -> None:
    source_id = "nl2query_router@2.0.0"
    child_id = "nl2sql@2.0.0"
    plan, _ = planner()
    request = request_for(
        allowed=(source_id, child_id),
        query="nl2query_router",
        data_scope=DataScope("s", "d", "items"),
    )
    input_data = [
        [
            {
                "name": "items",
                "type": "collection",
                "scope": "/source/s/database/d/collection/items",
            }
        ]
    ]
    attributes = {
        "search_query": "find rows",
        "columns": [{"name": "value"}],
        "execute_query": False,
        "protocol": "sqlite",
    }

    result = plan.plan_refinement(request, source_id, input_data, attributes)

    assert [step.operator_id for step in result.selected.steps] == [child_id]
    assert result.preflight.operator_ids == (child_id,)


# --- 2. Source eligibility ---------------------------------------------------------- #
@pytest.mark.parametrize(
    "source_id",
    [
        "multipart_query@1.0.0",
        "multipart_query",
        "select@2.0.0",
        "not_registered@2.0.0",
        "",
        cast(str, None),
        cast(str, 7),
    ],
)
def test_an_ineligible_source_is_refused(source_id: str) -> None:
    plan, _ = planner()

    with pytest.raises(PlanningError, match="refinement source is not eligible") as caught:
        plan.plan_refinement(request_for(), source_id, [[]], {})

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID
    assert caught.value.record.category is ErrorCategory.RECOVERABLE
    assert caught.value.record.stage is PlanningStage.GENERATION


def test_a_discovered_allowed_nonrefiner_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    source_id = "select@2.0.0"
    plan, registry = planner()
    source_card = registry.get_card(source_id)
    assert source_card is not None
    object.__setattr__(source_card, "tags", (*source_card.tags, "produces-plan"))

    def forced_discovery(_request: PlanningRequest) -> DiscoverySnapshot:
        return DiscoverySnapshot((source_card,))

    monkeypatch.setattr(plan, "discover", forced_discovery)

    with pytest.raises(PlanningError, match="source is not eligible") as caught:
        plan.plan_refinement(request_for(allowed=(source_id,)), source_id, [[]], {})

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID


def test_a_discovered_source_outside_the_allowlist_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, registry = planner()
    source_card = registry.get_card(SOURCE)
    assert source_card is not None
    forced = DiscoverySnapshot((source_card,))

    def forced_discovery(_request: PlanningRequest) -> DiscoverySnapshot:
        return forced

    monkeypatch.setattr(plan, "discover", forced_discovery)

    with pytest.raises(PlanningError, match="source is not eligible") as caught:
        plan.plan_refinement(request_for(allowed=(WRITE_CHILD,)), SOURCE, [[]], {})

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID


def test_an_undiscovered_source_is_refused() -> None:
    plan, _ = planner()
    elsewhere = request_for(query="select")

    with pytest.raises(PlanningError, match="source is not eligible"):
        plan.plan_refinement(elsewhere, SOURCE, [[]], {})


def test_a_custom_refiner_with_a_matching_name_is_refused() -> None:
    # Name, id, tags, and class hierarchy are all reachable through public register();
    # package provenance is what separates a built-in from a lookalike.
    from blue_data_ops.operators.multipart_query_operator import MultipartQueryOperator

    custom = OperatorRegistry()
    custom.register(
        MultipartQueryOperator(),
        "2.0.0",
        ["produces-plan"],
        when_to_invoke="looks exactly like the built-in",
    )
    plan, _ = planner(custom)

    with pytest.raises(PlanningError, match="source is not eligible"):
        plan.plan_refinement(request_for(), SOURCE, [[]], {})


def test_a_builtin_refiner_without_the_produces_plan_tag_is_refused() -> None:
    plan, registry = planner()
    card = registry.get_card(SOURCE)
    assert card is not None
    object.__setattr__(card, "tags", tuple(tag for tag in card.tags if tag != "produces-plan"))

    with pytest.raises(PlanningError, match="source is not eligible"):
        refine_empty(plan)


def test_a_builtin_refiner_subclass_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from blue_data_ops.operators.multipart_query_operator import MultipartQueryOperator

    class MultipartQuerySubclass(MultipartQueryOperator):
        pass

    plan, registry = planner()
    replacement = MultipartQuerySubclass()
    replacement._bind_operator_id(SOURCE)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setitem(cast(Any, registry)._operators, SOURCE, replacement)

    with pytest.raises(PlanningError, match="source is not eligible"):
        refine_empty(plan)


def test_source_resolution_failure_is_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    plan, registry = planner()
    original = registry.resolve

    def fail_source(operator_id: str) -> Any:
        if operator_id == SOURCE:
            raise RuntimeError("registry detail that must not leak")
        return original(operator_id)

    monkeypatch.setattr(registry, "resolve", fail_source)

    with pytest.raises(PlanningError, match="source resolution failed") as caught:
        refine_empty(plan)

    assert caught.value.record.code is PlanningErrorCode.DISCOVERY_FAILED
    assert caught.value.record.stage is PlanningStage.DISCOVERY
    assert "must not leak" not in str(caught.value)


def _unbound_refine(*args: Any, **kwargs: Any) -> tuple[list[Any], Any]:
    del args, kwargs
    return [], None


def test_a_rebound_refine_hook_is_refused() -> None:
    # A provenance regression test, not a tamper-resistance claim: a caller with the
    # object can still reassign attributes, as it can anywhere in this runtime.
    plan, registry = planner()
    resolved = registry.resolve(SOURCE)
    object.__setattr__(resolved, "refine", _unbound_refine)

    with pytest.raises(PlanningError, match="source is not eligible"):
        refine_empty(plan)


@pytest.mark.parametrize("name", ["refine", "refiner", "_refiner"])
def test_a_different_bound_refinement_hook_is_refused(name: str) -> None:
    plan, registry = planner()
    resolved = registry.resolve(SOURCE)

    def replacement(self: object, *args: Any, **kwargs: Any) -> Any:
        del self, args, kwargs
        return [], Meta([], is_empty=True)

    object.__setattr__(resolved, name, MethodType(replacement, resolved))

    with pytest.raises(PlanningError, match="source is not eligible"):
        refine_empty(plan)


# --- 3. Write children need explicit admission -------------------------------------- #
def test_a_write_child_the_caller_did_not_name_is_rejected() -> None:
    plan, _ = planner()

    with pytest.raises(PlanningError, match="invalid plan result") as caught:
        refine_empty(plan, request_for(allowed=(SOURCE,)))

    # A child problem, reported as a child problem: the source was eligible.
    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID
    assert caught.value.record.category is ErrorCategory.FAILED


def test_naming_the_exact_write_id_admits_it_and_plans_nothing() -> None:
    plan, _ = planner()

    result = refine_empty(plan)

    # Admission is not execution: planning compiled and preflighted, and no operator
    # body ran.
    assert result.preflight.operator_ids == (WRITE_CHILD,)


def test_a_missing_child_card_is_an_invalid_refinement_result() -> None:
    missing_child = "not_registered@2.0.0"
    pipeline = DataPipeline()
    source = pipeline.define_input("input")
    step = pipeline.define_operator(missing_child, label="missing")
    sink = pipeline.define_output("output")
    pipeline.connect_nodes(source, step)
    pipeline.connect_nodes(step, sink)
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(sink)
    plan, registry = planner()
    script_refinement(registry, ([pipeline], Meta([])))

    with pytest.raises(PlanningError, match="invalid plan result") as caught:
        refine_empty(plan, request_for(allowed=(SOURCE, missing_child)))

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID
    assert caught.value.record.category is ErrorCategory.FAILED


# --- 4. One refinement call, no recursion ------------------------------------------- #
@pytest.mark.parametrize(
    ("source_id", "attributes"),
    [
        (
            "plan_discover@2.0.0",
            {"task": "starter", "data": "rows", "approximate": True, "search_query": "avg"},
        )
    ],
)
def test_a_refinable_child_fails_the_whole_batch(
    source_id: str, attributes: dict[str, Any]
) -> None:
    plan, _ = planner()
    allowed = (source_id, "plan_discover@2.0.0")

    with pytest.raises(PlanningError, match="invalid plan result") as caught:
        plan.plan_refinement(
            request_for(allowed=allowed, query="plan_discover"),
            source_id,
            [[{"x": 1}]],
            attributes,
        )

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID


def test_the_source_is_called_exactly_once() -> None:
    plan, registry = planner()
    resolved = registry.resolve(SOURCE)
    calls: list[int] = []
    original = cast(Any, resolved)._refine_once

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(*args, **kwargs)

    object.__setattr__(resolved, "_refine_once", counting)
    try:
        refine_empty(plan)
    finally:
        object.__delattr__(resolved, "_refine_once")

    assert calls == [1]


# --- 5. Malformed refinement results ------------------------------------------------ #
def script_refinement(registry: OperatorRegistry, outcome: Any) -> None:
    """Replace the inner refinement hook without changing source provenance."""

    resolved = registry.resolve(SOURCE)

    def scripted(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        return outcome

    object.__setattr__(resolved, "_refine_once", scripted)


def error_record(category: ErrorCategory) -> ErrorRecord:
    return ErrorRecord(
        category=category,
        code=OperatorErrorCode.INVALID_INPUT,
        operator_id=SOURCE,
        stage=ErrorStage.VALIDATE,
        message="operator detail that must not leak",
        retryable=False,
        suggestion="operator suggestion that must not leak",
    )


def Meta(errors: list[Any], is_empty: bool = False) -> ExecMeta:
    """A real ExecMeta. The adapter requires the exact type, not a lookalike."""

    return ExecMeta(is_empty=is_empty, errors=errors, logs=[], traces={})


class FakeMeta:
    """A duck-typed lookalike: right attribute names, wrong type."""

    def __init__(self, errors: list[Any], is_empty: bool = False) -> None:
        self.errors = errors
        self.is_empty = is_empty


@pytest.mark.parametrize(
    "outcome",
    [
        "not a tuple",
        ([],),
        ([], None, None),
        ("not a list", Meta([])),
        ([], object()),
        ([object()], Meta([])),
        ([], Meta([], is_empty=False)),
    ],
)
def test_a_malformed_refinement_result_is_rejected(outcome: Any) -> None:
    plan, registry = planner()
    script_refinement(registry, outcome)

    with pytest.raises(PlanningError) as caught:
        refine_empty(plan)

    assert caught.value.record.code in {
        PlanningErrorCode.GENERATION_RESULT_INVALID,
        PlanningErrorCode.GENERATION_FAILED,
    }


@pytest.mark.parametrize(
    "category", [ErrorCategory.RECOVERABLE, ErrorCategory.TIMEOUT, ErrorCategory.FAILED]
)
def test_an_operator_error_maps_by_category_without_leaking(category: ErrorCategory) -> None:
    plan, registry = planner()
    script_refinement(registry, ([], Meta([error_record(category)])))

    with pytest.raises(PlanningError, match="operator refinement failed") as caught:
        refine_empty(plan)

    record = caught.value.record
    assert record.code is PlanningErrorCode.GENERATION_FAILED
    assert record.category is category
    assert record.retryable is False
    assert "must not leak" not in str(caught.value)
    assert "must not leak" not in str(record)


def test_several_operator_errors_collapse_by_severity() -> None:
    # One PlanningError carries one record, so the batch reports the worst category.
    plan, registry = planner()
    records = [error_record(ErrorCategory.RECOVERABLE), error_record(ErrorCategory.FAILED)]
    script_refinement(registry, ([], Meta(records)))

    with pytest.raises(PlanningError) as caught:
        refine_empty(plan)

    assert caught.value.record.category is ErrorCategory.FAILED


def test_a_refiner_reporting_errors_and_plans_together_is_rejected() -> None:
    plan, registry = planner()
    real, _ = cast(Any, versioned_registry().resolve(SOURCE)).refine([[]], {}, None)
    script_refinement(registry, (real, Meta([error_record(ErrorCategory.FAILED)])))

    with pytest.raises(PlanningError, match="invalid plan result"):
        refine_empty(plan)


def test_an_exception_escaping_refine_is_contained() -> None:
    plan, registry = planner()
    resolved = registry.resolve(SOURCE)

    def explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("refiner internals that must not leak")

    object.__setattr__(resolved, "_refine_once", explode)

    with pytest.raises(PlanningError, match="operator refinement failed") as caught:
        refine_empty(plan)

    assert caught.value.record.category is ErrorCategory.FAILED
    assert "must not leak" not in str(caught.value)


def test_a_successful_empty_refinement_uses_the_existing_no_candidates_record() -> None:
    # Empty refinement is a success at the operator boundary; it becomes a planning
    # outcome only because the selector has nothing to choose.
    plan, registry = planner()
    script_refinement(registry, ([], Meta([], is_empty=True)))

    with pytest.raises(PlanningError) as caught:
        refine_empty(plan)

    assert caught.value.record.code is PlanningErrorCode.NO_CANDIDATES
    assert caught.value.record.stage is PlanningStage.SELECTION


# --- 6. Limits ---------------------------------------------------------------------- #
def test_too_many_alternatives_fail_the_batch_without_truncating() -> None:
    plan, registry = planner()
    real, _ = cast(Any, versioned_registry().resolve(SOURCE)).refine([[]], {}, None)
    script_refinement(registry, (real * 3, Meta([])))

    with pytest.raises(PlanningError, match="exceeded a planning limit") as caught:
        refine_empty(plan, request_for(max_candidates=2))

    assert caught.value.record.code is PlanningErrorCode.CANDIDATE_LIMIT_EXCEEDED
    assert caught.value.record.category is ErrorCategory.RECOVERABLE


def test_an_extended_snapshot_over_the_discovery_bound_fails() -> None:
    plan, _ = planner()

    with pytest.raises(PlanningError, match="exceeded a planning limit"):
        refine_empty(plan, request_for(max_discovery_cards=1))


# --- 7. Admission boundaries --------------------------------------------------------- #
def test_an_empty_allowlist_fails_before_refinement() -> None:
    """An empty allowed_operator_ids tuple does not mean unrestricted."""

    plan, _ = planner()
    unrestricted = PlanningRequest(
        goal="materialize a refinement alternative",
        discovery_queries=(DiscoveryQuery("multipart_query"),),
    )

    with pytest.raises(PlanningError, match="source is not eligible") as caught:
        plan.plan_refinement(unrestricted, SOURCE, [[]], {})

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID


def test_an_empty_allowlist_cannot_admit_a_write_child() -> None:
    plan, _ = planner()
    unrestricted = PlanningRequest(goal="g", discovery_queries=(DiscoveryQuery("multipart_query"),))

    with pytest.raises(PlanningError):
        plan.plan_refinement(unrestricted, SOURCE, [[]], {})


def test_a_duck_typed_metadata_lookalike_is_rejected() -> None:
    """The transient result requires exact ExecMeta and ErrorRecord types."""

    plan, registry = planner()
    real, _ = cast(Any, versioned_registry().resolve(SOURCE)).refine([[]], {}, None)
    script_refinement(registry, (real, FakeMeta(errors=[], is_empty=False)))

    with pytest.raises(PlanningError, match="invalid plan result") as caught:
        refine_empty(plan)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID


def test_a_duck_typed_error_record_is_rejected() -> None:
    class FakeRecord:
        category = ErrorCategory.FAILED

    plan, registry = planner()
    script_refinement(registry, ([], Meta([cast(Any, FakeRecord())])))

    with pytest.raises(PlanningError, match="invalid plan result"):
        refine_empty(plan)


Nodes = dict[str, dict[str, Any]]


def _kind(nodes: Nodes, wanted: str) -> str:
    return next(node_id for node_id, node in nodes.items() if node["type"] == wanted)


def _drop_input(nodes: Nodes) -> None:
    del nodes[_kind(nodes, "INPUT")]


def _drop_output(nodes: Nodes) -> None:
    del nodes[_kind(nodes, "OUTPUT")]


def _dangling_edge(nodes: Nodes) -> None:
    nodes[_kind(nodes, "INPUT")]["prev"] = ["missing"]


def _non_reciprocal(nodes: Nodes) -> None:
    nodes[_kind(nodes, "INPUT")]["next"] = []


def _bad_node_type(nodes: Nodes) -> None:
    nodes[_kind(nodes, "OPERATOR")]["type"] = "UNKNOWN"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_drop_input, id="no-input"),
        pytest.param(_drop_output, id="no-output"),
        pytest.param(_dangling_edge, id="dangling-edge"),
        pytest.param(_non_reciprocal, id="non-reciprocal"),
        pytest.param(_bad_node_type, id="bad-node-type"),
    ],
)
def test_an_unrepresentable_returned_graph_is_rejected(
    mutate: Callable[[Nodes], None],
) -> None:
    """Reject a returned graph that cannot be projected without loss."""

    plan, registry = planner()
    real, _ = cast(Any, versioned_registry().resolve(SOURCE)).refine([[]], {}, None)
    record = cast("dict[str, Any]", real[0].to_dict())
    mutate(cast("Nodes", record["nodes"]))
    broken = DataPipeline.from_dict(cast(Any, record))
    script_refinement(registry, ([broken], Meta([])))

    with pytest.raises(PlanningError, match="invalid plan result") as caught:
        refine_empty(plan)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID


# --- 8. Representable records -------------------------------------------------------- #

Record = dict[str, Any]


def _valid_record() -> Record:
    real, _ = cast(Any, versioned_registry().resolve(SOURCE)).refine([[]], {}, None)
    return cast(Record, real[0].to_dict())


def _node_of(record: Record, wanted: str) -> str:
    nodes = cast(Nodes, record["nodes"])
    return next(node_id for node_id, node in nodes.items() if node["type"] == wanted)


def _entity_of(record: Record) -> dict[str, Any]:
    section = cast("dict[str, Any]", cast("dict[str, Any]", record["entities"])["OPERATOR"])
    return cast("dict[str, Any]", next(iter(section.values())))


# Rule 1: top-level input is an exact string naming the unique INPUT node.
def _input_none(record: Record) -> None:
    record["input"] = None


def _input_missing_node(record: Record) -> None:
    record["input"] = "no_such_node"


def _input_not_a_string(record: Record) -> None:
    record["input"] = [_node_of(record, "INPUT")]


def _input_names_the_operator(record: Record) -> None:
    record["input"] = _node_of(record, "OPERATOR")


# Rule 2: top-level output is an exact string naming the unique OUTPUT node.
def _output_none(record: Record) -> None:
    record["output"] = None


def _output_missing_node(record: Record) -> None:
    record["output"] = "no_such_node"


def _output_names_the_input(record: Record) -> None:
    record["output"] = _node_of(record, "INPUT")


# Rule 3: entities contains only the OPERATOR section.
def _extra_entity_section(record: Record) -> None:
    cast("dict[str, Any]", record["entities"])["OTHER"] = {}


def _foreign_entity_section(record: Record) -> None:
    cast("dict[str, Any]", record["entities"])["DATA"] = {"d1": {"id": "d1"}}


# Rule 4: every operator node names exactly one existing operator entity.
def _operator_entity_missing(record: Record) -> None:
    cast("dict[str, Any]", record["entities"])["OPERATOR"] = {}


def _operator_entity_points_at_missing_node(record: Record) -> None:
    _entity_of(record)["nodes"] = ["no_such_node"]


def _operator_entity_claims_two_nodes(record: Record) -> None:
    _entity_of(record)["nodes"] = [_node_of(record, "OPERATOR"), _node_of(record, "INPUT")]


# Rule 5: every operator entity links back to exactly its operator node.
def _entity_links_to_the_input_node(record: Record) -> None:
    _entity_of(record)["nodes"] = [_node_of(record, "INPUT")]


def _second_entity_claims_the_same_node(record: Record) -> None:
    section = cast("dict[str, Any]", cast("dict[str, Any]", record["entities"])["OPERATOR"])
    duplicate = dict(_entity_of(record))
    duplicate["id"] = "duplicate_entity"
    section["duplicate_entity"] = duplicate


MALFORMED_RECORD_CASES = [
    pytest.param(_input_none, id="rule1-input-none"),
    pytest.param(_input_missing_node, id="rule1-input-missing"),
    pytest.param(_input_not_a_string, id="rule1-input-not-a-string"),
    pytest.param(_input_names_the_operator, id="rule1-input-wrong-node"),
    pytest.param(_output_none, id="rule2-output-none"),
    pytest.param(_output_missing_node, id="rule2-output-missing"),
    pytest.param(_output_names_the_input, id="rule2-output-wrong-node"),
    pytest.param(_extra_entity_section, id="rule3-extra-section"),
    pytest.param(_foreign_entity_section, id="rule3-foreign-section"),
    pytest.param(_operator_entity_missing, id="rule4-no-entity"),
    pytest.param(_operator_entity_points_at_missing_node, id="rule4-entity-dangling"),
    pytest.param(_operator_entity_claims_two_nodes, id="rule4-entity-two-nodes"),
    pytest.param(_entity_links_to_the_input_node, id="rule5-entity-wrong-node"),
    pytest.param(_second_entity_claims_the_same_node, id="rule5-duplicate-entity"),
]


@pytest.mark.parametrize("mutate", MALFORMED_RECORD_CASES)
def test_every_representability_rule_rejects_before_projection(
    mutate: Callable[[Record], None],
) -> None:
    plan, registry = planner()
    record = _valid_record()
    mutate(record)
    script_refinement(registry, ([DataPipeline.from_dict(cast(Any, record))], Meta([])))

    with pytest.raises(PlanningError, match="invalid plan result") as caught:
        refine_empty(plan)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID


@pytest.mark.parametrize("mutate", MALFORMED_RECORD_CASES)
def test_no_malformed_pipeline_ever_compiles_a_write_card(
    mutate: Callable[[Record], None],
) -> None:
    """The consequence that matters: every one of these previously produced a compiled
    plan containing create_database@2.0.0."""

    plan, registry = planner()
    record = _valid_record()
    mutate(record)
    script_refinement(registry, ([DataPipeline.from_dict(cast(Any, record))], Meta([])))

    with pytest.raises(PlanningError):
        refine_empty(plan)


def test_two_operator_roots_are_rejected() -> None:
    plan, registry = planner()
    record = _valid_record()
    nodes = cast(Nodes, record["nodes"])
    operator_node = _node_of(record, "OPERATOR")
    stray = dict(nodes[operator_node])
    stray["id"] = "stray_operator"
    stray["prev"] = [_node_of(record, "INPUT")]
    stray["next"] = [_node_of(record, "OUTPUT")]
    nodes["stray_operator"] = stray
    nodes[_node_of(record, "INPUT")]["next"].append("stray_operator")
    nodes[_node_of(record, "OUTPUT")]["prev"].append("stray_operator")

    script_refinement(registry, ([DataPipeline.from_dict(cast(Any, record))], Meta([])))

    with pytest.raises(PlanningError, match="invalid plan result"):
        refine_empty(plan)


# Rule 8: none of the above may cost the valid path.
def test_a_valid_built_in_alternative_still_succeeds() -> None:
    plan, _ = planner()

    result = refine_empty(plan)

    assert result.preflight.operator_ids == (WRITE_CHILD,)
    assert [step.operator_id for step in result.selected.steps] == [WRITE_CHILD]


def test_an_unmutated_record_round_trips_through_validation() -> None:
    # Guards the mutators themselves: the fixture must be valid before mutation, or
    # every case above would pass for the wrong reason.
    plan, registry = planner()
    script_refinement(registry, ([DataPipeline.from_dict(cast(Any, _valid_record()))], Meta([])))

    result = refine_empty(plan)

    assert result.preflight.operator_ids == (WRITE_CHILD,)


# --- 9. Node and entity links -------------------------------------------------------- #


def _entity_key(record: Record) -> str:
    section = cast("dict[str, Any]", cast("dict[str, Any]", record["entities"])["OPERATOR"])
    return next(iter(section))


def _entity_section(record: Record) -> dict[str, Any]:
    return cast("dict[str, Any]", cast("dict[str, Any]", record["entities"])["OPERATOR"])


def test_the_valid_record_links_node_and_entity_both_ways() -> None:
    """The shape the negative cases below break. Asserted so they cannot pass for the
    wrong reason."""

    record = _valid_record()
    key = _entity_key(record)
    entity = _entity_section(record)[key]
    node_id = _node_of(record, "OPERATOR")

    assert type(key) is str
    assert entity["id"] == key
    assert entity["type"] == "OPERATOR"
    assert entity["nodes"] == [node_id]
    assert cast(Nodes, record["nodes"])[node_id]["OPERATOR"] == key
    # Absent rather than None on a non-operator node, which is why the check reads it
    # with .get() instead of indexing.
    assert "OPERATOR" not in cast(Nodes, record["nodes"])[_node_of(record, "INPUT")]
    assert "OPERATOR" not in cast(Nodes, record["nodes"])[_node_of(record, "OUTPUT")]


def _backlink_missing(record: Record) -> None:
    cast(Nodes, record["nodes"])[_node_of(record, "OPERATOR")]["OPERATOR"] = None


def _backlink_absent_key(record: Record) -> None:
    del cast(Nodes, record["nodes"])[_node_of(record, "OPERATOR")]["OPERATOR"]


def _backlink_not_a_string(record: Record) -> None:
    cast(Nodes, record["nodes"])[_node_of(record, "OPERATOR")]["OPERATOR"] = [_entity_key(record)]


def _backlink_nonexistent(record: Record) -> None:
    cast(Nodes, record["nodes"])[_node_of(record, "OPERATOR")]["OPERATOR"] = "no_such_entity"


def _backlink_mismatched(record: Record) -> None:
    # A second entity that also claims the node, with the node pointing at it instead of
    # at the entity the first one records.
    section = _entity_section(record)
    other = dict(section[_entity_key(record)])
    other["id"] = "second_entity"
    section["second_entity"] = other
    cast(Nodes, record["nodes"])[_node_of(record, "OPERATOR")]["OPERATOR"] = "second_entity"


def _entity_id_disagrees_with_key(record: Record) -> None:
    section = _entity_section(record)
    section[_entity_key(record)]["id"] = "some_other_id"


def _entity_type_is_wrong(record: Record) -> None:
    section = _entity_section(record)
    section[_entity_key(record)]["type"] = "DATA"


def _input_claims_an_entity(record: Record) -> None:
    cast(Nodes, record["nodes"])[_node_of(record, "INPUT")]["OPERATOR"] = _entity_key(record)


def _output_claims_an_entity(record: Record) -> None:
    cast(Nodes, record["nodes"])[_node_of(record, "OUTPUT")]["OPERATOR"] = _entity_key(record)


BACKLINK_CASES = [
    pytest.param(_backlink_missing, id="backlink-none"),
    pytest.param(_backlink_absent_key, id="backlink-key-absent"),
    pytest.param(_backlink_not_a_string, id="backlink-not-a-string"),
    pytest.param(_backlink_nonexistent, id="backlink-nonexistent"),
    pytest.param(_backlink_mismatched, id="backlink-wrong-entity"),
    pytest.param(_entity_id_disagrees_with_key, id="entity-id-mismatch"),
    pytest.param(_entity_type_is_wrong, id="entity-wrong-type"),
    pytest.param(_input_claims_an_entity, id="input-claims-entity"),
    pytest.param(_output_claims_an_entity, id="output-claims-entity"),
]


@pytest.mark.parametrize("mutate", BACKLINK_CASES)
def test_a_broken_node_entity_link_is_rejected(mutate: Callable[[Record], None]) -> None:
    plan, registry = planner()
    record = _valid_record()
    mutate(record)
    script_refinement(registry, ([DataPipeline.from_dict(cast(Any, record))], Meta([])))

    with pytest.raises(PlanningError, match="invalid plan result") as caught:
        refine_empty(plan)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID


@pytest.mark.parametrize("mutate", BACKLINK_CASES)
def test_a_broken_link_never_compiles_a_write_card(
    mutate: Callable[[Record], None],
) -> None:
    plan, registry = planner()
    record = _valid_record()
    mutate(record)
    script_refinement(registry, ([DataPipeline.from_dict(cast(Any, record))], Meta([])))

    with pytest.raises(PlanningError):
        refine_empty(plan)


class _Opaque:
    """Raises on the operations a traversal would perform."""

    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        raise RuntimeError("discarded field was deep-copied")

    def __eq__(self, other: object) -> bool:
        raise RuntimeError("discarded field was compared")

    def __hash__(self) -> int:
        raise RuntimeError("discarded field was hashed")


def test_validation_still_does_not_traverse_discarded_fields() -> None:
    """The projection discards top-level map, attributes,
    properties, ids, provenance, input/output values, node values, statuses, and sync
    state; tightening the link checks must not start reading any of them."""

    plan, registry = planner()
    record = _valid_record()
    record["attributes"] = _Opaque()
    record["provenance"] = _Opaque()
    record["properties"] = _Opaque()
    for node in cast(Nodes, record["nodes"]).values():
        node["values"] = _Opaque()
        node["statuses"] = _Opaque()
        node["value"] = _Opaque()
    script_refinement(registry, ([DataPipeline.from_dict(cast(Any, record))], Meta([])))

    result = refine_empty(plan)

    assert result.preflight.operator_ids == (WRITE_CHILD,)


# --- 10. Hostile structural values -------------------------------------------------- #


class HookLog:
    """Records the operations a validator must never perform on untrusted data."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def reset(self) -> None:
        self.calls.clear()


class Spoof:
    """Answers every structural question the way an attacker would want it answered.

    `__eq__` agrees with whatever it is compared against, `__bool__` and `__len__` report
    empty, and `__hash__` impersonates a chosen string so the object can occupy that
    key's slot in a dictionary and intercept the lookup. Every hook records itself, so a
    test can assert the record was refused on type alone.
    """

    def __init__(self, log: HookLog, impersonates: str = "OPERATOR") -> None:
        self._log = log
        self._impersonates = impersonates

    def __eq__(self, other: object) -> bool:
        self._log.calls.append("__eq__")
        return True

    def __hash__(self) -> int:
        self._log.calls.append("__hash__")
        return hash(self._impersonates)

    def __bool__(self) -> bool:
        self._log.calls.append("__bool__")
        return False

    def __len__(self) -> int:
        self._log.calls.append("__len__")
        return 0

    def __iter__(self) -> Iterator[Any]:
        self._log.calls.append("__iter__")
        return iter(())

    def __str__(self) -> str:
        self._log.calls.append("__str__")
        return self._impersonates

    def __deepcopy__(self, memo: dict[int, Any]) -> Spoof:
        self._log.calls.append("__deepcopy__")
        return self


def test_the_hostile_sentinel_records_every_hook_it_claims_to() -> None:
    """Guards the matrix below. A sentinel that silently failed to record would make
    every zero-hook assertion pass for the wrong reason."""

    log = HookLog()
    spoof = Spoof(log, impersonates="OPERATOR")

    assert spoof == "anything"
    assert bool(spoof) is False
    assert len(spoof) == 0
    assert list(spoof) == []
    assert str(spoof) == "OPERATOR"
    assert hash(spoof) == hash("OPERATOR")
    assert deepcopy(spoof) is spoof

    assert sorted(set(log.calls)) == [
        "__bool__",
        "__deepcopy__",
        "__eq__",
        "__hash__",
        "__iter__",
        "__len__",
        "__str__",
    ]


# Structural values: the type has to be established before anything reads the value.
def _spoof_input(record: Record, log: HookLog) -> None:
    record["input"] = Spoof(log, _node_of(record, "INPUT"))


def _spoof_output(record: Record, log: HookLog) -> None:
    record["output"] = Spoof(log, _node_of(record, "OUTPUT"))


def _spoof_node_type(record: Record, log: HookLog) -> None:
    node = cast(Nodes, record["nodes"])[_node_of(record, "OPERATOR")]
    node["type"] = Spoof(log, "OPERATOR")


def _spoof_prev_entry(record: Record, log: HookLog) -> None:
    nodes = cast(Nodes, record["nodes"])
    nodes[_node_of(record, "OPERATOR")]["prev"] = [Spoof(log, _node_of(record, "INPUT"))]


def _spoof_next_entry(record: Record, log: HookLog) -> None:
    nodes = cast(Nodes, record["nodes"])
    nodes[_node_of(record, "OPERATOR")]["next"] = [Spoof(log, _node_of(record, "OUTPUT"))]


def _spoof_node_operator(record: Record, log: HookLog) -> None:
    nodes = cast(Nodes, record["nodes"])
    nodes[_node_of(record, "OPERATOR")]["OPERATOR"] = Spoof(log, _entity_key(record))


def _spoof_entity_id(record: Record, log: HookLog) -> None:
    _entity_of(record)["id"] = Spoof(log, _entity_key(record))


def _spoof_entity_type(record: Record, log: HookLog) -> None:
    _entity_of(record)["type"] = Spoof(log, "OPERATOR")


def _spoof_entity_nodes(record: Record, log: HookLog) -> None:
    _entity_of(record)["nodes"] = Spoof(log, _node_of(record, "OPERATOR"))


def _spoof_entity_nodes_entry(record: Record, log: HookLog) -> None:
    _entity_of(record)["nodes"] = [Spoof(log, _node_of(record, "OPERATOR"))]


def _spoof_entity_properties(record: Record, log: HookLog) -> None:
    _entity_of(record)["properties"] = Spoof(log, "properties")


# Structural keys: each of these takes over the slot of the string it impersonates, so
# an unguarded lookup consults the object and hands back whatever it is holding.
def _spoof_top_level_key(record: Record, log: HookLog) -> None:
    real = record.pop("nodes")
    record[cast(Any, Spoof(log, "nodes"))] = real


def _spoof_node_map_key(record: Record, log: HookLog) -> None:
    nodes = cast(Nodes, record["nodes"])
    operator = _node_of(record, "OPERATOR")
    node = nodes.pop(operator)
    nodes[cast(Any, Spoof(log, operator))] = node


def _spoof_node_record_key(record: Record, log: HookLog) -> None:
    node = cast(Nodes, record["nodes"])[_node_of(record, "OPERATOR")]
    kind = node.pop("type")
    node[cast(Any, Spoof(log, "type"))] = kind


def _spoof_entity_section_key(record: Record, log: HookLog) -> None:
    entities = cast("dict[str, Any]", record["entities"])
    section = entities.pop("OPERATOR")
    entities[cast(Any, Spoof(log, "OPERATOR"))] = section


def _spoof_entity_map_key(record: Record, log: HookLog) -> None:
    section = _entity_section(record)
    key = _entity_key(record)
    entity = section.pop(key)
    section[cast(Any, Spoof(log, key))] = entity


def _spoof_entity_record_key(record: Record, log: HookLog) -> None:
    entity = _entity_of(record)
    entity.pop("properties", None)
    entity[cast(Any, Spoof(log, "properties"))] = {}


HOSTILE_STRUCTURE_CASES = [
    pytest.param(_spoof_input, id="value-input"),
    pytest.param(_spoof_output, id="value-output"),
    pytest.param(_spoof_node_type, id="value-node-type"),
    pytest.param(_spoof_prev_entry, id="value-prev-entry"),
    pytest.param(_spoof_next_entry, id="value-next-entry"),
    pytest.param(_spoof_node_operator, id="value-node-operator"),
    pytest.param(_spoof_entity_id, id="value-entity-id"),
    pytest.param(_spoof_entity_type, id="value-entity-type"),
    pytest.param(_spoof_entity_nodes, id="value-entity-nodes"),
    pytest.param(_spoof_entity_nodes_entry, id="value-entity-nodes-entry"),
    pytest.param(_spoof_entity_properties, id="value-entity-properties"),
    pytest.param(_spoof_top_level_key, id="key-top-level"),
    pytest.param(_spoof_node_map_key, id="key-node-map"),
    pytest.param(_spoof_node_record_key, id="key-node-record"),
    pytest.param(_spoof_entity_section_key, id="key-entity-section"),
    pytest.param(_spoof_entity_map_key, id="key-entity-map"),
    pytest.param(_spoof_entity_record_key, id="key-entity-record"),
]


def _hostile_planner(
    place: Callable[[Record, HookLog], None],
) -> tuple[PipelinePlanner, HookLog]:
    plan, registry = planner()
    record = _valid_record()
    log = HookLog()
    place(record, log)
    script_refinement(registry, ([DataPipeline.from_dict(cast(Any, record))], Meta([])))
    # Inserting a spoofed key hashes it, and from_dict reads the record before the
    # planner ever sees it. Only what validation itself does should be measured.
    log.reset()
    return plan, log


@pytest.mark.parametrize("place", HOSTILE_STRUCTURE_CASES)
def test_a_hostile_structural_value_is_refused_unasked(
    place: Callable[[Record, HookLog], None],
) -> None:
    plan, log = _hostile_planner(place)

    with pytest.raises(PlanningError, match="invalid plan result") as caught:
        refine_empty(plan)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID
    assert log.calls == []


@pytest.mark.parametrize("place", HOSTILE_STRUCTURE_CASES)
def test_a_hostile_structural_value_never_compiles_a_write_card(
    place: Callable[[Record, HookLog], None],
) -> None:
    """The consequence that matters, stated separately from the error code: none of
    these may reach a compiled, preflighted `create_database@2.0.0`."""

    plan, _ = _hostile_planner(place)

    with pytest.raises(PlanningError):
        refine_empty(plan)


# --- Returned adjacency ------------------------------------------------------------- #
SECOND_CHILD = "create_table@2.0.0"


def _two_step_record() -> Record:
    pipeline = DataPipeline(label="two-step")
    source = pipeline.define_input("input")
    first = pipeline.define_operator(WRITE_CHILD, label="first")
    second = pipeline.define_operator(SECOND_CHILD, label="second")
    sink = pipeline.define_output("output")
    pipeline.connect_nodes(source, first)
    pipeline.connect_nodes(first, second)
    pipeline.connect_nodes(second, sink)
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(sink)
    return pipeline.to_dict()


def _script_record(record: Record) -> tuple[PipelinePlanner, PlanningRequest]:
    plan, registry = planner()
    script_refinement(registry, ([DataPipeline.from_dict(cast(Any, record))], Meta([])))
    request = request_for(allowed=(SOURCE, WRITE_CHILD, SECOND_CHILD))
    return plan, request


def _connect_record(record: Record, source: str, target: str) -> None:
    nodes = cast(Nodes, record["nodes"])
    nodes[source]["next"].append(target)
    nodes[target]["prev"].append(source)


def _direct_endpoint_bypass(record: Record) -> None:
    _connect_record(record, _node_of(record, "INPUT"), _node_of(record, "OUTPUT"))


def _input_to_nonroot(record: Record) -> None:
    nodes = cast(Nodes, record["nodes"])
    operators = [node_id for node_id, node in nodes.items() if node["type"] == "OPERATOR"]
    _connect_record(record, _node_of(record, "INPUT"), operators[1])


def _nonterminal_to_output(record: Record) -> None:
    nodes = cast(Nodes, record["nodes"])
    operators = [node_id for node_id, node in nodes.items() if node["type"] == "OPERATOR"]
    _connect_record(record, operators[0], _node_of(record, "OUTPUT"))


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_direct_endpoint_bypass, id="input-output-bypass"),
        pytest.param(_input_to_nonroot, id="input-nonroot"),
        pytest.param(_nonterminal_to_output, id="nonterminal-output"),
    ],
)
def test_an_endpoint_edge_the_draft_cannot_represent_is_rejected(
    mutate: Callable[[Record], None],
) -> None:
    record = _two_step_record()
    mutate(record)
    plan, request = _script_record(record)

    with pytest.raises(PlanningError, match="invalid plan result") as caught:
        plan.plan_refinement(request, SOURCE, [[]], {})

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID


def _duplicate_forward_edge(record: Record) -> None:
    nodes = cast(Nodes, record["nodes"])
    operators = [node_id for node_id, node in nodes.items() if node["type"] == "OPERATOR"]
    nodes[operators[0]]["next"].append(operators[1])


def _duplicate_reverse_edge(record: Record) -> None:
    nodes = cast(Nodes, record["nodes"])
    operators = [node_id for node_id, node in nodes.items() if node["type"] == "OPERATOR"]
    nodes[operators[1]]["prev"].append(operators[0])


def _duplicate_both_directions(record: Record) -> None:
    _duplicate_forward_edge(record)
    _duplicate_reverse_edge(record)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_duplicate_forward_edge, id="forward"),
        pytest.param(_duplicate_reverse_edge, id="reverse"),
        pytest.param(_duplicate_both_directions, id="both"),
    ],
)
def test_edge_multiplicity_must_match_one_for_one(mutate: Callable[[Record], None]) -> None:
    record = _two_step_record()
    mutate(record)
    plan, request = _script_record(record)

    with pytest.raises(PlanningError, match="invalid plan result") as caught:
        plan.plan_refinement(request, SOURCE, [[]], {})

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID


def test_the_edge_limit_counts_returned_adjacency_before_projection() -> None:
    record = _valid_record()
    _direct_endpoint_bypass(record)
    plan, registry = planner()
    script_refinement(registry, ([DataPipeline.from_dict(cast(Any, record))], Meta([])))

    with pytest.raises(PlanningError, match="exceeded a planning limit") as caught:
        refine_empty(plan, request_for(max_edges=2))

    assert caught.value.record.code is PlanningErrorCode.CANDIDATE_LIMIT_EXCEEDED
