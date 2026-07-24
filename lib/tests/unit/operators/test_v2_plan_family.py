from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any, cast
from unittest.mock import patch

import pytest

from blue_data_ops import (
    ErrorCategory,
    ErrorCode,
    ErrorStage,
    FunctionResult,
    ValidationResult,
)
from blue_data_ops.operators import (
    Attributes,
    CreateDatabaseOperator,
    CreateTableOperator,
    DataBundle,
    DataDiscoverOperator,
    InsertTableOperator,
    MultipartQueryOperator,
    NL2LLMOperator,
    NL2QueryRouterOperator,
    NL2SQLOperator,
    Operator,
    OperatorRegistry,
    PlanDiscoverOperator,
    ProjectOperator,
    Properties,
    QueryBreakdownOperator,
    SelectOperator,
    default_registry,
)
from blue_data_ops.operators import query_breakdown_operator as query_module
from blue_data_ops.plan import DeclarativeOperator, RefinableOperator
from blue_data_ops.plan import pipeline as pipeline_module
from tests.unit.operators._plan_operator_helpers import (
    assert_registry_resolves,
    cte,
    edges,
    operator_ids,
)

INPUT: DataBundle = [[]]
PLAN_ATTRIBUTES: Attributes = {
    "task": "starter",
    "data": "rows",
    "approximate": True,
}
ROUTER_ATTRIBUTES: Attributes = {
    "search_query": "find rows",
    "columns": [{"name": "value"}],
    "execute_query": False,
    "protocol": "sqlite",
}


class RecordingClient:
    def __init__(self, result: Any = None, error: BaseException | None = None) -> None:
        self.result: Any = [] if result is None else result
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def execute_api_call(
        self,
        input: Any,  # noqa: A002
        properties: Properties | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(
            {
                "input": input,
                "properties": properties,
                "additional_data": additional_data,
            }
        )
        if self.error is not None:
            raise self.error
        return self.result


def _inject_client(monkeypatch: pytest.MonkeyPatch, client: RecordingClient) -> None:
    def resolve(properties: Properties) -> RecordingClient:
        del properties
        return client

    monkeypatch.setattr(query_module, "resolve_llm_client", resolve)


def _source(name: str, protocol: str = "sqlite") -> dict[str, Any]:
    return {
        "name": name,
        "type": "source",
        "scope": f"/source/{name}",
        "properties": {"connection": {"protocol": protocol}, "owner": name},
    }


def _collection(name: str = "items") -> dict[str, Any]:
    return {
        "name": name,
        "type": "collection",
        "scope": "/source/s/database/d/collection/items",
    }


def _id_sequence() -> Callable[[], str]:
    current = 0

    def next_id() -> str:
        nonlocal current
        current += 1
        return f"v2-plan-{current:04d}"

    return next_id


def _selected(operator: RefinableOperator, version: str) -> RefinableOperator:
    registry = OperatorRegistry()
    registry.register(operator, "1.0.0")
    registry.register(operator, "2.0.0")
    return cast(RefinableOperator, registry.resolve(f"{operator.name}@{version}"))


def _child_registry() -> OperatorRegistry:
    registry = OperatorRegistry()
    children: list[Operator] = [
        CreateDatabaseOperator(),
        CreateTableOperator(),
        DataDiscoverOperator(),
        InsertTableOperator(),
        NL2LLMOperator(),
        NL2QueryRouterOperator(),
        NL2SQLOperator(),
        ProjectOperator(),
        SelectOperator(),
    ]
    for operator in children:
        tags = ("starter",) if operator.name in {"project", "select"} else ()
        registry.register(operator, "1.0.0", tags=tags)
        registry.register(operator, "2.0.0", tags=tags)
    return registry


def _assert_error(
    meta: Any,
    category: ErrorCategory,
    code: ErrorCode,
    stage: ErrorStage,
    operator_id: str,
) -> None:
    assert len(meta.errors) == 1
    error = meta.errors[0]
    assert error.category is category
    assert error.code is code
    assert error.stage is stage
    assert error.operator_id == operator_id
    assert error.retryable is False


@pytest.mark.parametrize(
    ("operator", "attributes"),
    [
        (PlanDiscoverOperator(OperatorRegistry()), PLAN_ATTRIBUTES),
        (QueryBreakdownOperator(), {"query": ""}),
        (MultipartQueryOperator(), {}),
        (NL2QueryRouterOperator(), {"search_query": "q"}),
    ],
)
def test_plan_c01_native_hooks_and_public_adapters_have_exact_types(
    operator: RefinableOperator,
    attributes: Attributes,
) -> None:
    assert "_execute" in type(operator).__dict__
    assert "_validate_input" in type(operator).__dict__
    assert "_refiner" in type(operator).__dict__
    assert (
        type(
            operator._execute(INPUT, attributes)  # pyright: ignore[reportPrivateUsage]
        )
        is FunctionResult
    )
    assert (
        type(
            operator._validate_input(  # pyright: ignore[reportPrivateUsage]
                INPUT,
                attributes,
            )
        )
        is ValidationResult
    )
    assert type(operator.apply(INPUT, attributes)) is list


def test_plan_c02_all_36_default_operators_now_own_native_hooks() -> None:
    registry = default_registry()
    cards = registry.list_cards()
    assert len(cards) == 36
    assert all(card.version == "1.0.0" for card in cards)
    for card in cards:
        operator = registry.resolve(card.operator_id)
        assert "_execute" in type(operator).__dict__
        assert "_validate_input" in type(operator).__dict__


def test_plan_c03_raw_validator_surfaces_stay_compatible() -> None:
    multipart = MultipartQueryOperator()
    router = NL2QueryRouterOperator()
    assert multipart.validate({}, {}) is True
    assert router.validate({"search_query": "q"}, {}) is True
    with pytest.raises(TypeError, match="unexpected keyword argument 'input_data'"):
        multipart.validate(input_data=INPUT, attributes={}, properties={})
    with pytest.raises(TypeError, match="unexpected keyword argument 'input_data'"):
        router.validate(
            input_data=INPUT,
            attributes={"search_query": "q"},
            properties={},
        )
    assert "validate" not in QueryBreakdownOperator.__dict__


@pytest.mark.parametrize(
    ("operator", "attributes"),
    [
        (PlanDiscoverOperator(OperatorRegistry()), PLAN_ATTRIBUTES),
        (QueryBreakdownOperator(), {"query": ""}),
        (MultipartQueryOperator(), {}),
        (NL2QueryRouterOperator(), {"search_query": "q"}),
    ],
)
def test_plan_c04_run_is_successful_empty_and_calls_native_body_once(
    operator: RefinableOperator,
    attributes: Attributes,
) -> None:
    with patch.object(
        operator,
        "_execute",
        wraps=operator._execute,  # pyright: ignore[reportPrivateUsage]
    ) as execute:
        output, output_attributes, meta = operator.run(INPUT, attributes)
    assert execute.call_count == 1
    assert output == [[]]
    assert output_attributes == {}
    assert meta.is_empty is True
    assert meta.errors == []


@pytest.mark.parametrize(
    "attributes",
    [
        {},
        {**PLAN_ATTRIBUTES, "task": ""},
        {**PLAN_ATTRIBUTES, "page": -1},
        {**PLAN_ATTRIBUTES, "page_size": 0},
        {**PLAN_ATTRIBUTES, "threshold": -0.1},
        {**PLAN_ATTRIBUTES, "threshold": 1.1},
    ],
)
def test_plan_pd01_canonical_task_validation_stops_registry(
    attributes: Attributes,
) -> None:
    registry = OperatorRegistry()
    with patch.object(registry, "find", wraps=registry.find) as find:
        for call in ("run", "refine"):
            result = getattr(PlanDiscoverOperator(registry), call)(INPUT, attributes)
            meta = result[-1]
            _assert_error(
                meta,
                ErrorCategory.RECOVERABLE,
                ErrorCode.INVALID_INPUT,
                ErrorStage.VALIDATE,
                "plan_discover@2.0.0",
            )
    assert find.call_count == 0


class HostileRange(int):
    def __lt__(self, other: object) -> bool:
        del other
        raise RuntimeError("private-range-payload")

    def __le__(self, other: object) -> bool:
        del other
        raise RuntimeError("private-range-payload")

    def __gt__(self, other: object) -> bool:
        del other
        raise RuntimeError("private-range-payload")


@pytest.mark.parametrize("field", ["page", "page_size", "threshold"])
def test_plan_pd02_hostile_range_values_are_contained(field: str) -> None:
    _, meta = PlanDiscoverOperator(OperatorRegistry()).refine(
        INPUT,
        {**PLAN_ATTRIBUTES, field: HostileRange(1)},
    )
    _assert_error(
        meta,
        ErrorCategory.FAILED,
        ErrorCode.VALIDATION_FAILED,
        ErrorStage.VALIDATE,
        "plan_discover@2.0.0",
    )


def test_plan_pd03_raw_uses_search_query_but_canonical_uses_task() -> None:
    operator = PlanDiscoverOperator(OperatorRegistry())
    assert operator.validate(INPUT, PLAN_ATTRIBUTES) is False
    assert operator.validate(INPUT, {**PLAN_ATTRIBUTES, "search_query": "legacy"}) is True
    _, run_attributes, run_meta = operator.run(INPUT, PLAN_ATTRIBUTES)
    plans, refine_meta = operator.refine(INPUT, PLAN_ATTRIBUTES)
    assert run_attributes == {}
    assert run_meta.errors == []
    assert plans == []
    assert refine_meta.is_empty is True


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
def test_plan_pd04_selected_discovery_filters_and_resolves_one_child_version(
    monkeypatch: pytest.MonkeyPatch,
    version: str,
) -> None:
    child_registry = _child_registry()
    operator = _selected(PlanDiscoverOperator(child_registry), version)
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    plans, meta = operator.refine(INPUT, PLAN_ATTRIBUTES)
    assert meta.errors == []
    assert len(plans) == 2
    records = [plan.to_dict() for plan in plans]
    assert {operator_ids(record)[0] for record in records} == {
        f"project@{version}",
        f"select@{version}",
    }
    for record in records:
        assert_registry_resolves(record, child_registry)


def test_plan_pd05_limit_applies_after_selected_candidate_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _selected(PlanDiscoverOperator(_child_registry()), "2.0.0")
    issued: list[str] = []

    def next_id() -> str:
        issued.append(str(len(issued)))
        return f"limited-{len(issued)}"

    monkeypatch.setattr(pipeline_module, "_new_id", next_id)
    plans, meta = operator.refine(INPUT, {**PLAN_ATTRIBUTES, "limit": 1})
    assert len(plans) == 1
    assert meta.errors == []
    assert len(issued) == 10


def test_plan_qb01_omitted_schema_is_valid_but_explicit_list_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RecordingClient([[cte("answer")]])
    _inject_client(monkeypatch, client)
    operator = QueryBreakdownOperator()
    output, _, run_meta = operator.run(INPUT, {"query": "q"})
    assert output == [[cte("answer")]]
    assert run_meta.errors == []
    assert client.calls[0]["additional_data"]["schema"] == ""

    for method in (operator.run, operator.refine):
        result = method(INPUT, {"query": "q", "schema": []})
        _assert_error(
            result[-1],
            ErrorCategory.RECOVERABLE,
            ErrorCode.INVALID_INPUT,
            ErrorStage.VALIDATE,
            "query_breakdown@2.0.0",
        )
    assert len(client.calls) == 1


@pytest.mark.parametrize("query", ["", "   "])
def test_plan_qb02_blank_query_is_successful_empty_without_provider(
    monkeypatch: pytest.MonkeyPatch,
    query: str,
) -> None:
    client = RecordingClient()
    _inject_client(monkeypatch, client)
    output, _, run_meta = QueryBreakdownOperator().run(INPUT, {"query": query})
    plans, refine_meta = QueryBreakdownOperator().refine(INPUT, {"query": query})
    assert output == [[]]
    assert run_meta.is_empty is True
    assert plans == []
    assert refine_meta.is_empty is True
    assert client.calls == []


def test_plan_qb03_provider_failure_is_stage_specific_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive = "opaque-provider-payload"
    client = RecordingClient(error=RuntimeError(sensitive))
    _inject_client(monkeypatch, client)
    operator = QueryBreakdownOperator()
    _, _, run_meta = operator.run(INPUT, {"query": "q"})
    _, refine_meta = operator.refine(INPUT, {"query": "q"})
    _assert_error(
        run_meta,
        ErrorCategory.FAILED,
        ErrorCode.EXECUTION_FAILED,
        ErrorStage.EXECUTE,
        "query_breakdown@2.0.0",
    )
    _assert_error(
        refine_meta,
        ErrorCategory.FAILED,
        ErrorCode.REFINEMENT_FAILED,
        ErrorStage.REFINE,
        "query_breakdown@2.0.0",
    )
    assert sensitive not in str(run_meta)
    assert sensitive not in str(refine_meta)


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
def test_plan_qb04_selected_refinement_emits_one_resolvable_version(
    monkeypatch: pytest.MonkeyPatch,
    version: str,
) -> None:
    child_registry = _child_registry()
    client = RecordingClient([[cte("base"), cte("child", dependency=["base"])]])
    _inject_client(monkeypatch, client)
    operator = _selected(QueryBreakdownOperator(), version)
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    plans, meta = operator.refine(INPUT, {"query": "q"})
    assert len(plans) == 1
    assert meta.errors == []
    record = plans[0].to_dict()
    assert {operator_id.rpartition("@")[2] for operator_id in operator_ids(record)} == {version}
    assert_registry_resolves(record, child_registry)


def test_plan_mq01_legacy_and_attribute_inputs_are_equivalent_and_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [[cte("base"), cte("child", dependency=["base"])]]
    original = copy.deepcopy(records)
    operator = MultipartQueryOperator()
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    legacy, legacy_meta = operator.refine(records, {"serialize": False})
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    explicit, explicit_meta = operator.refine(
        [[cte("ignored")]],
        {"plans": records, "serialize": False},
    )
    assert [plan.to_dict() for plan in legacy] == [plan.to_dict() for plan in explicit]
    assert legacy_meta.errors == explicit_meta.errors == []
    assert records == original


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownArgumentType]
    ("input_data", "attributes", "count"),
    [  # pyright: ignore[reportUnknownArgumentType]
        ([], {}, 0),
        ([[]], {}, 1),
        (INPUT, {"plans": []}, 0),
        (INPUT, {"plans": [[]]}, 1),
    ],
)
def test_plan_mq02_empty_forms_have_pinned_semantics(
    input_data: DataBundle,
    attributes: Attributes,
    count: int,
) -> None:
    plans, meta = MultipartQueryOperator().refine(input_data, attributes)
    assert len(plans) == count
    assert meta.is_empty is (count == 0)
    assert meta.errors == []


@pytest.mark.parametrize(
    "plans",
    [
        "bad",
        ["bad"],
        [["bad"]],
        [[{"description": "d"}]],
        [[{**cte("x"), "columns": [{"type": "str"}]}]],
        [[{**cte("x"), "dependency": [1]}]],
        [[{**cte("x"), "generality": "high"}]],
    ],
)
def test_plan_mq03_structural_errors_are_invalid_before_refinement(plans: object) -> None:
    result, meta = MultipartQueryOperator().refine(INPUT, {"plans": plans})
    assert result == []
    _assert_error(
        meta,
        ErrorCategory.RECOVERABLE,
        ErrorCode.INVALID_INPUT,
        ErrorStage.VALIDATE,
        "multipart_query@2.0.0",
    )


def test_plan_mq04_dependency_order_failure_is_contained_at_refine() -> None:
    plans, meta = MultipartQueryOperator().refine(
        INPUT,
        {"plans": [[cte("child", dependency=["missing"])]]},
    )
    assert plans == []
    _assert_error(
        meta,
        ErrorCategory.FAILED,
        ErrorCode.REFINEMENT_FAILED,
        ErrorStage.REFINE,
        "multipart_query@2.0.0",
    )


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
def test_plan_mq05_selected_refinement_emits_one_resolvable_version(
    monkeypatch: pytest.MonkeyPatch,
    version: str,
) -> None:
    child_registry = _child_registry()
    operator = _selected(MultipartQueryOperator(), version)
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    plans, meta = operator.refine([[cte("x")]], {})
    assert meta.errors == []
    record = plans[0].to_dict()
    assert {operator_id.rpartition("@")[2] for operator_id in operator_ids(record)} == {version}
    assert_registry_resolves(record, child_registry)


def test_plan_nq01_legacy_first_group_and_explicit_sources_are_equivalent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source("s")
    operator = NL2QueryRouterOperator()
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    legacy, legacy_meta = operator.refine(
        [[source], [_source("ignored", "openai")]], ROUTER_ATTRIBUTES
    )
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    explicit, explicit_meta = operator.refine(
        [[_source("ignored", "openai")]],
        {**ROUTER_ATTRIBUTES, "sources": [source]},
    )
    assert [plan.to_dict() for plan in legacy] == [plan.to_dict() for plan in explicit]
    assert legacy_meta.errors == explicit_meta.errors == []


@pytest.mark.parametrize(
    ("input_data", "attributes"),
    [
        ([], ROUTER_ATTRIBUTES),
        (INPUT, ROUTER_ATTRIBUTES),
        (INPUT, {**ROUTER_ATTRIBUTES, "sources": []}),
    ],
)
def test_plan_nq02_empty_sources_are_successful_empty(
    input_data: DataBundle,
    attributes: Attributes,
) -> None:
    plans, meta = NL2QueryRouterOperator().refine(input_data, attributes)
    assert plans == []
    assert meta.is_empty is True
    assert meta.errors == []


@pytest.mark.parametrize(
    "sources",
    [
        "bad",
        ["bad"],
        [{"name": "s", "type": "source", "scope": "/source/s"}],
        [{"name": "c", "type": "collection", "scope": "/source/s"}],
        [{"name": "x", "type": "mystery", "scope": "/"}],
    ],
)
def test_plan_nq03_malformed_or_unknown_sources_are_invalid(sources: object) -> None:
    plans, meta = NL2QueryRouterOperator().refine(
        INPUT,
        {**ROUTER_ATTRIBUTES, "sources": sources},
    )
    assert plans == []
    _assert_error(
        meta,
        ErrorCategory.RECOVERABLE,
        ErrorCode.INVALID_INPUT,
        ErrorStage.VALIDATE,
        "nl2query_router@2.0.0",
    )


@pytest.mark.parametrize(
    ("record", "protocol", "expected"),
    [
        (_source("s", "openai"), "", ["nl2llm"]),
        (_source("s", "sqlite"), "", ["data_discover", "nl2query_router"]),
        (_source("s", "unknown"), "", []),
        (_collection(), "sqlite", ["nl2sql"]),
        (_collection(), "unknown", []),
    ],
)
def test_plan_nq04_supported_and_unsupported_routes_stay_successful(
    record: dict[str, Any],
    protocol: str,
    expected: list[str],
) -> None:
    attributes = {**ROUTER_ATTRIBUTES, "protocol": protocol, "sources": [record]}
    plans, meta = NL2QueryRouterOperator().refine(INPUT, attributes)
    assert meta.errors == []
    if record["type"] == "source" and not expected:
        assert plans == []
        assert meta.is_empty is True
    else:
        assert len(plans) == 1
        assert [name.partition("@")[0] for name in operator_ids(plans[0].to_dict())] == expected


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
def test_plan_nq05_selected_refinement_emits_one_resolvable_version(
    monkeypatch: pytest.MonkeyPatch,
    version: str,
) -> None:
    child_registry = _child_registry()
    operator = _selected(NL2QueryRouterOperator(), version)
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    plans, meta = operator.refine(
        INPUT,
        {**ROUTER_ATTRIBUTES, "sources": [_source("s", "sqlite")]},
    )
    assert meta.errors == []
    record = plans[0].to_dict()
    assert {operator_id.rpartition("@")[2] for operator_id in operator_ids(record)} == {version}
    assert_registry_resolves(record, child_registry)


def test_plan_shared01_normalization_is_fresh_and_wrapper_delegates() -> None:
    source = MultipartQueryOperator()
    wrapper = _selected(source, "2.0.0")
    input_data = [[cte("x")]]
    attributes: Attributes = {"serialize": False}
    with patch.object(
        source,
        "_pre_validate_normalize",
        wraps=source._pre_validate_normalize,  # pyright: ignore[reportPrivateUsage]
    ) as normalize:
        plans, meta = wrapper.refine(input_data, attributes)
    assert normalize.call_count == 1
    assert len(plans) == 1
    assert meta.errors == []
    normalized_input, normalized_attributes, _ = normalize.call_args.args
    assert normalized_input is input_data
    assert normalized_attributes is attributes
    assert input_data == [[cte("x")]]
    assert attributes == {"serialize": False}


class CopyBomb(dict[str, Any]):
    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        del memo
        raise RuntimeError("private-copy-payload")


def test_plan_shared02_normalization_failure_is_defaults_failure() -> None:
    plans, meta = MultipartQueryOperator().refine(INPUT, cast(Attributes, CopyBomb()))
    assert plans == []
    _assert_error(
        meta,
        ErrorCategory.FAILED,
        ErrorCode.DEFAULTS_FAILED,
        ErrorStage.DEFAULTS,
        "multipart_query@2.0.0",
    )
    assert "private-copy-payload" not in str(meta)


def _declarative_properties(version: str) -> Properties:
    return {
        "plans": [
            {
                "nodes": {
                    "first": {"type": "OPERATOR", "name": f"select@{version}"},
                    "second": {
                        "type": "OPERATOR",
                        "name": f"project@{version}",
                        "prev": ["first"],
                    },
                }
            }
        ]
    }


def test_plan_shared03_d32_raw_and_v1_fail_while_direct_and_v2_repair_prev() -> None:
    source = DeclarativeOperator({"plans": []})
    with pytest.raises(UnboundLocalError, match="from_id"):
        source.refiner(INPUT, {}, _declarative_properties("1.0.0"))

    v1 = _selected(DeclarativeOperator({"plans": []}), "1.0.0")
    v1_plans, v1_meta = v1.refine(INPUT, {}, _declarative_properties("1.0.0"))
    assert v1_plans == []
    assert v1_meta.errors[0].code is ErrorCode.REFINEMENT_FAILED

    for operator, version in [
        (DeclarativeOperator({"plans": []}), "2.0.0"),
        (_selected(DeclarativeOperator({"plans": []}), "2.0.0"), "2.0.0"),
    ]:
        plans, meta = operator.refine(INPUT, {}, _declarative_properties(version))
        assert len(plans) == 1
        assert meta.errors == []
        first, second = list(plans[0].filter_nodes(["OPERATOR"]))
        assert (first, second) in edges(plans[0].to_dict())


def test_plan_shared04_direct_calls_keep_declared_v1_child_pins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    plans, meta = MultipartQueryOperator().refine([[cte("x")]], {})
    assert meta.errors == []
    assert {operator_id.rpartition("@")[2] for operator_id in operator_ids(plans[0].to_dict())} == {
        "1.0.0"
    }


def test_plan_shared05_selected_error_identity_is_exact() -> None:
    for operator, attributes in (
        (PlanDiscoverOperator(OperatorRegistry()), {}),
        (QueryBreakdownOperator(), {}),
        (MultipartQueryOperator(), {"plans": "bad"}),
        (NL2QueryRouterOperator(), {"sources": "bad"}),
    ):
        for version in ("1.0.0", "2.0.0"):
            selected = _selected(operator, version)
            plans, meta = selected.refine(INPUT, attributes)
            assert plans == []
            _assert_error(
                meta,
                ErrorCategory.RECOVERABLE,
                ErrorCode.INVALID_INPUT,
                ErrorStage.VALIDATE,
                f"{operator.name}@{version}",
            )
