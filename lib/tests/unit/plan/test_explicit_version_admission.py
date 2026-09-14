from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from types import MethodType, SimpleNamespace
from typing import Any, cast

import pytest

from blue_data_ops.operators import (
    OperatorCard,
    OperatorRegistry,
    default_registry,
    versioned_registry,
)
from blue_data_ops.operators.select_operator import SelectOperator
from blue_data_ops.operators.types import ErrorCategory
from blue_data_ops.plan import (
    DataContextSnapshot,
    DataScope,
    DiscoveryQuery,
    DiscoverySnapshot,
    OpenAIPlanGenerator,
    PipelinePlanner,
    PlanDraft,
    PlanningError,
    PlanningErrorCode,
    PlanningRequest,
    PlanningStage,
    PlanStep,
    RulePlanGenerator,
    RulePlanTemplate,
    RuleTemplateStep,
)
from blue_data_ops.plan.context import planning_error

V3_IDS = ("join@3.0.0", "avg@3.0.0")
JOIN_TAGS = (
    "domain-relational",
    "flow-combine",
    "accepts-data",
    "produces-data",
    "capability-join",
)
AVG_TAGS = (
    "domain-arithmetic",
    "flow-aggregate",
    "accepts-data",
    "produces-data",
    "capability-average",
    "capability-reduction",
)
JOIN_ATTRIBUTES = {
    "join_on": [["account_id"], ["customer_ref"]],
    "join_suffix": ["_account", "_invoice"],
    "join_type": "inner",
    "keep_keys": "left",
}
AVG_ATTRIBUTES = {"avg_key": "amount", "output_key": "mean_amount"}


def _template() -> RulePlanTemplate:
    return RulePlanTemplate(
        label="join-then-average",
        steps=(
            RuleTemplateStep("join", "join", ("join_on",), JOIN_TAGS),
            RuleTemplateStep("average", "avg", ("avg_key", "output_key"), AVG_TAGS),
        ),
    )


def _request(
    *,
    allowed: tuple[str, ...] = V3_IDS,
    queries: tuple[DiscoveryQuery, ...] | None = None,
) -> PlanningRequest:
    return PlanningRequest(
        goal="Join accounts to invoices and average the amount",
        discovery_queries=queries
        or (
            DiscoveryQuery("join", tags=("capability-join",)),
            DiscoveryQuery("average", tags=("capability-average",)),
        ),
        operator_attributes={
            "join": dict(JOIN_ATTRIBUTES),
            "avg": dict(AVG_ATTRIBUTES),
        },
        allowed_operator_ids=allowed,
    )


def _cards(registry: OperatorRegistry, *operator_ids: str) -> DiscoverySnapshot:
    cards: list[OperatorCard] = []
    for operator_id in operator_ids:
        card = registry.get_card(operator_id)
        assert card is not None
        cards.append(card)
    return DiscoverySnapshot(tuple(cards))


class _FixedGenerator:
    def __init__(self, draft: PlanDraft) -> None:
        self.draft = draft
        self.calls = 0

    def generate(
        self,
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None,
    ) -> Sequence[PlanDraft]:
        del request, discovery, data_context
        self.calls += 1
        return (self.draft,)


class _RecordingClient:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document
        self.options: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []

    def with_options(self, **kwargs: Any) -> _RecordingClient:
        self.options.append(kwargs)
        return self

    @property
    def responses(self) -> _RecordingClient:
        return self

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        part = SimpleNamespace(type="output_text", text=json.dumps(self.document))
        return SimpleNamespace(status="completed", output=[SimpleNamespace(content=[part])])


class _RecordingContextProvider:
    def __init__(self) -> None:
        self.calls: list[DataScope] = []

    def collect(self, scope: DataScope) -> DataContextSnapshot:
        self.calls.append(scope)
        raise AssertionError("the changed scope reached the context provider")


def _response(*operator_ids: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    for index, operator_id in enumerate(operator_ids):
        steps.append(
            {
                "step_id": f"step-{index}",
                "operator_id": operator_id,
                "attributes_json": "{}",
                "depends_on": [] if index == 0 else [f"step-{index - 1}"],
                "label": None,
            }
        )
    return {"candidates": [{"label": "planned", "steps": steps}]}


def test_explicit_v3_rule_plan_preserves_exact_ids_and_executes() -> None:
    registry = versioned_registry()
    planner = PipelinePlanner(registry, RulePlanGenerator((_template(),)))

    result = planner.run(
        _request(),
        [
            [{"account_id": "a1"}, {"account_id": "a2"}],
            [
                {"customer_ref": "a1", "amount": 120.0},
                {"customer_ref": "a2", "amount": 80.0},
            ],
        ],
    )

    assert result.planning.discovery.operator_ids == V3_IDS
    assert tuple(step.operator_id for step in result.planning.selected.steps) == V3_IDS
    assert result.planning.preflight.operator_ids == V3_IDS
    assert result.execution.output_data == [[{"mean_amount": 100.0}]]


def test_explicit_v3_request_can_mix_one_exact_version_per_template_name() -> None:
    registry = versioned_registry()
    planner = PipelinePlanner(registry, RulePlanGenerator((_template(),)))

    result = planner.plan(_request(allowed=("join@3.0.0", "avg@2.0.0")))

    assert tuple(step.operator_id for step in result.selected.steps) == (
        "join@3.0.0",
        "avg@2.0.0",
    )
    assert result.preflight.operator_ids == ("join@3.0.0", "avg@2.0.0")


@pytest.mark.parametrize(
    "replacement",
    [None, DataScope("other-source", "other-db", "other-collection")],
    ids=("removed", "repointed"),
)
def test_explicit_v3_registry_validation_cannot_change_the_scope_before_discovery(
    monkeypatch: pytest.MonkeyPatch,
    replacement: DataScope | None,
) -> None:
    registry = versioned_registry()
    request = replace(
        _request(allowed=("avg@3.0.0",)),
        data_scope=DataScope("source", "db", "collection"),
    )
    generator = _FixedGenerator(PlanDraft((PlanStep("average", "avg@3.0.0", AVG_ATTRIBUTES),)))
    context_provider = _RecordingContextProvider()
    original_get_card = registry.get_card
    original_find = registry.find
    find_calls = 0

    def mutating_get_card(self: OperatorRegistry, operator_id: str) -> OperatorCard | None:
        card = original_get_card(operator_id)
        object.__setattr__(request, "data_scope", replacement)
        return card

    def recording_find(
        self: OperatorRegistry, query: str, tags: Sequence[str] | None = None
    ) -> list[OperatorCard]:
        nonlocal find_calls
        find_calls += 1
        return original_find(query, tags)

    monkeypatch.setattr(registry, "get_card", MethodType(mutating_get_card, registry))
    monkeypatch.setattr(registry, "find", MethodType(recording_find, registry))

    with pytest.raises(PlanningError, match="scope does not match") as caught:
        PipelinePlanner(
            registry,
            generator,
            data_context_provider=context_provider,
        ).plan(request)

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_SCOPE_MISMATCH
    assert caught.value.record.stage is PlanningStage.DATA_CONTEXT
    assert find_calls == 0
    assert context_provider.calls == []
    assert generator.calls == 0


def test_empty_allowlist_uses_active_defaults_and_compatibility_discover_remains_v2() -> None:
    registry = versioned_registry()
    planner = PipelinePlanner(registry, RulePlanGenerator((_template(),)))
    request = _request(allowed=())

    result = planner.plan(request)

    assert tuple(step.operator_id for step in result.selected.steps) == (
        "join@3.0.0",
        "avg@3.0.0",
    )
    assert result.preflight.operator_ids == ("join@3.0.0", "avg@3.0.0")
    assert PipelinePlanner(registry, cast(Any, None)).discover(_request()).operator_ids == ()


@pytest.mark.parametrize(
    "operator_id",
    ["avg@1.0.0", "avg@4.0.0", "avg", "avg@3.0.0@3.0.0"],
)
def test_v3_opt_in_rejects_versions_outside_current_builtin_v2_v3(
    operator_id: str,
) -> None:
    generator = _FixedGenerator(PlanDraft((PlanStep("join", "join@3.0.0"),)))
    planner = PipelinePlanner(versioned_registry(), generator)

    with pytest.raises(PlanningError) as caught:
        planner.plan(_request(allowed=("join@3.0.0", operator_id)))

    assert caught.value.record.code is PlanningErrorCode.INVALID_REQUEST
    assert caught.value.record.stage is PlanningStage.VALIDATION
    assert generator.calls == 0


def test_ordinary_plan_rejects_a_custom_v3_registration() -> None:
    registry = versioned_registry()
    custom = registry.register(SelectOperator(name="custom_select"), "3.0.0")
    generator = _FixedGenerator(PlanDraft((PlanStep("custom", custom.operator_id),)))
    planner = PipelinePlanner(registry, generator)

    with pytest.raises(PlanningError) as caught:
        planner.plan(
            PlanningRequest(
                goal="Use the custom operator",
                discovery_queries=(DiscoveryQuery("custom_select"),),
                allowed_operator_ids=(custom.operator_id,),
            )
        )

    assert caught.value.record.code is PlanningErrorCode.INVALID_REQUEST
    assert generator.calls == 0


def test_caller_rule_can_plan_with_a_caller_registered_v2_operator() -> None:
    registry = OperatorRegistry()
    card = registry.register(SelectOperator(name="custom_select"), "2.0.0")
    draft = PlanDraft(
        (
            PlanStep(
                "filter",
                card.operator_id,
                {"operand_key": "amount", "operand": ">", "operand_val": 10},
            ),
        )
    )
    request = PlanningRequest(
        goal="Filter rows with a caller operator",
        discovery_queries=(DiscoveryQuery("custom_select"),),
        allowed_operator_ids=(card.operator_id,),
    )

    result = PipelinePlanner(registry, _FixedGenerator(draft)).plan(request)

    assert result.preflight.operator_ids == ("custom_select@2.0.0",)


def test_raw_default_override_is_not_builtin_planning_authority() -> None:
    registry = default_registry(argmax="3.0.0")
    generator = _FixedGenerator(PlanDraft((PlanStep("largest", "argmax@3.0.0"),)))
    card = registry.get_card("argmax@3.0.0")
    assert card is not None
    assert card.tags == ()
    assert registry.resolve(card.operator_id).operator_id == card.operator_id

    with pytest.raises(PlanningError) as caught:
        PipelinePlanner(registry, generator).plan(
            PlanningRequest(
                goal="Find the row with the largest value",
                discovery_queries=(DiscoveryQuery("argmax"),),
                allowed_operator_ids=(card.operator_id,),
            )
        )

    assert caught.value.record.code is PlanningErrorCode.INVALID_REQUEST
    assert generator.calls == 0


@pytest.mark.parametrize("swap_window", ["generator", "selector"])
def test_admission_rejects_same_id_operator_swaps(swap_window: str) -> None:
    registry = versioned_registry()
    operator_id = "select@2.0.0"
    original = registry.resolve(operator_id)
    replacement = SelectOperator()
    cast(Any, replacement)._bind_operator_id(operator_id)
    draft = PlanDraft(
        (
            PlanStep(
                "filter",
                operator_id,
                {"operand_key": "amount", "operand": ">", "operand_val": 10},
            ),
        )
    )

    def swap() -> None:
        cast(Any, registry)._operators[operator_id] = replacement

    class SwappingGenerator(_FixedGenerator):
        def generate(
            self,
            request: PlanningRequest,
            discovery: DiscoverySnapshot,
            data_context: DataContextSnapshot | None,
        ) -> Sequence[PlanDraft]:
            if swap_window == "generator":
                swap()
            return super().generate(request, discovery, data_context)

    class SwappingSelector:
        def select(self, candidates: Sequence[PlanDraft]) -> PlanDraft:
            if swap_window == "selector":
                swap()
            return candidates[0]

    request = PlanningRequest(
        goal="Filter rows",
        discovery_queries=(DiscoveryQuery("select"),),
        allowed_operator_ids=(operator_id,),
    )
    planner = PipelinePlanner(
        registry,
        SwappingGenerator(draft),
        selector=cast(Any, SwappingSelector()),
    )

    with pytest.raises(PlanningError, match="was not admitted") as caught:
        planner.plan(request)

    assert replacement is not original
    assert caught.value.record.code is PlanningErrorCode.PLAN_INVALID


def test_allowlist_does_not_add_an_operator_discovery_did_not_return() -> None:
    draft = PlanDraft((PlanStep("average", "avg@3.0.0", AVG_ATTRIBUTES),))
    planner = PipelinePlanner(versioned_registry(), _FixedGenerator(draft))
    request = _request(
        allowed=("avg@3.0.0",),
        queries=(DiscoveryQuery("join", tags=("capability-join",)),),
    )

    with pytest.raises(PlanningError, match="was not discovered") as caught:
        planner.plan(request)

    assert caught.value.record.code is PlanningErrorCode.PLAN_INVALID
    assert caught.value.record.stage is PlanningStage.COMPILATION


def test_discovery_rejects_a_same_id_card_from_another_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = versioned_registry()
    other = versioned_registry()
    substituted = other.get_card("join@3.0.0")
    assert substituted is not None

    original_find = registry.find

    def substituted_find(
        self: OperatorRegistry, query: str, tags: Sequence[str] | None = None
    ) -> list[OperatorCard]:
        if query == "join":
            return [substituted]
        return original_find(query, tags)

    monkeypatch.setattr(registry, "find", MethodType(substituted_find, registry))
    planner = PipelinePlanner(registry, RulePlanGenerator((_template(),)))

    with pytest.raises(PlanningError, match="operator 'join@3.0.0' was not admitted") as caught:
        planner.plan(_request())

    assert caught.value.record.code is PlanningErrorCode.PLAN_INVALID


def test_rule_template_rejects_a_forged_allowed_card_without_planner_discovery() -> None:
    registry = versioned_registry()
    genuine_join = registry.get_card("join@3.0.0")
    assert genuine_join is not None
    forged_join = OperatorCard(
        operator_id="join@3.0.0",
        name="join",
        version="2.0.0",
        description=genuine_join.description,
        tags=genuine_join.tags,
        when_to_invoke=genuine_join.when_to_invoke,
    )

    with pytest.raises(PlanningError, match="metadata does not match") as caught:
        _template().generate(
            _request(),
            DiscoverySnapshot((forged_join, *_cards(registry, "avg@3.0.0").cards)),
            None,
        )

    assert caught.value.record.code is PlanningErrorCode.DISCOVERY_RESULT_INVALID


def test_rule_template_rejects_multiple_allowed_versions_of_one_name() -> None:
    registry = versioned_registry()
    request = _request(allowed=("join@3.0.0", "avg@2.0.0", "avg@3.0.0"))
    discovery = _cards(registry, "join@3.0.0", "avg@2.0.0", "avg@3.0.0")

    with pytest.raises(PlanningError) as caught:
        _template().generate(request, discovery, None)

    assert caught.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.INVALID_REQUEST,
        PlanningStage.VALIDATION,
        "rule template requires one allowed version of 'avg'",
        False,
        "Correct the planning request and try again.",
    )


def test_default_rule_rejects_multiple_versions_with_the_same_validation_record() -> None:
    request = PlanningRequest(
        goal="Average values greater than 5",
        discovery_queries=(DiscoveryQuery("select"), DiscoveryQuery("avg")),
        operator_attributes={
            "select": {"operand_key": "x", "operand": ">", "operand_val": 5},
            "avg": {"avg_key": "x", "output_key": "mean"},
        },
        allowed_operator_ids=("select@2.0.0", "avg@2.0.0", "avg@3.0.0"),
    )

    with pytest.raises(PlanningError) as caught:
        PipelinePlanner(versioned_registry(), RulePlanGenerator()).plan(request)

    assert caught.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.INVALID_REQUEST,
        PlanningStage.VALIDATION,
        "rule template requires one allowed version of 'avg'",
        False,
        "Correct the planning request and try again.",
    )


def test_direct_rule_template_accepts_copied_matching_metadata() -> None:
    registry = versioned_registry()
    copied = tuple(replace(card) for card in _cards(registry, *V3_IDS).cards)

    draft = _template().generate(_request(), DiscoverySnapshot(copied), None)

    assert tuple(step.operator_id for step in draft.steps) == V3_IDS


def test_explicit_request_rejects_a_retired_operator_id() -> None:
    registry = versioned_registry()
    retired_id = "query_breakdown@2.0.0"
    generator = _FixedGenerator(PlanDraft((PlanStep("average", "avg@3.0.0", AVG_ATTRIBUTES),)))
    request = PlanningRequest(
        goal="Inspect a retired card",
        discovery_queries=(DiscoveryQuery("query_breakdown"),),
        allowed_operator_ids=(retired_id, "avg@3.0.0"),
    )

    with pytest.raises(PlanningError) as caught:
        PipelinePlanner(registry, generator).plan(request)

    assert caught.value.record.code is PlanningErrorCode.INVALID_REQUEST
    assert caught.value.record.stage is PlanningStage.VALIDATION
    assert generator.calls == 0


def test_explicit_compile_rechecks_registry_identity() -> None:
    registry = versioned_registry()
    other = versioned_registry()
    planner = PipelinePlanner(registry, cast(Any, None))
    request = _request(allowed=("avg@3.0.0",))
    draft = PlanDraft((PlanStep("average", "avg@3.0.0", AVG_ATTRIBUTES),))

    with pytest.raises(PlanningError, match="was not admitted") as caught:
        cast(Any, planner)._compile(
            request,
            draft,
            _cards(other, "avg@3.0.0"),
        )

    assert caught.value.record.code is PlanningErrorCode.PLAN_INVALID


def test_scripted_openai_v3_plan_discloses_only_discovered_metadata_and_compiles() -> None:
    registry = versioned_registry()
    client = _RecordingClient(_response("avg@3.0.0"))
    request = PlanningRequest(
        goal="Average the invoice amount",
        discovery_queries=(DiscoveryQuery("average", tags=("capability-average",)),),
        operator_attributes={"avg": dict(AVG_ATTRIBUTES)},
        allowed_operator_ids=("avg@3.0.0",),
    )
    generator = OpenAIPlanGenerator(
        "offline-scripted-test",
        registry=registry,
        allowed_operator_ids=("avg@3.0.0",),
        client=client,
    )

    result = PipelinePlanner(registry, generator).run(
        request, [[{"amount": 10.0}, {"amount": 20.0}]]
    )

    assert result.planning.preflight.operator_ids == ("avg@3.0.0",)
    assert result.execution.output_data == [[{"mean_amount": 15.0}]]
    payload = json.loads(client.requests[0]["input"][0]["content"])
    assert [card["operator_id"] for card in payload["operators"]] == ["avg@3.0.0"]
    assert "data_context" not in payload
    assert {"skills", "operator_skills", "guides"}.isdisjoint(payload)
    assert {"tools", "tool_choice", "files"}.isdisjoint(client.requests[0])


def test_openai_decoder_rejects_an_unallowed_version_after_one_scripted_call() -> None:
    registry = versioned_registry()
    client = _RecordingClient(_response("avg@2.0.0"))
    generator = OpenAIPlanGenerator(
        "offline-scripted-test",
        registry=registry,
        allowed_operator_ids=("avg@3.0.0",),
        client=client,
    )

    with pytest.raises(PlanningError, match="unauthorized operator") as caught:
        generator.generate(
            _request(allowed=("avg@3.0.0",)),
            _cards(registry, "avg@3.0.0"),
            None,
        )

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID
    assert len(client.requests) == 1


def test_openai_v3_catalog_rejects_a_card_from_another_registry_before_call() -> None:
    registry = versioned_registry()
    other = versioned_registry()
    client = _RecordingClient(_response("avg@3.0.0"))
    generator = OpenAIPlanGenerator(
        "offline-scripted-test",
        registry=registry,
        allowed_operator_ids=("avg@3.0.0",),
        client=client,
    )

    with pytest.raises(PlanningError, match="requires supported built-in") as caught:
        generator.generate(_request(allowed=("avg@3.0.0",)), _cards(other, "avg@3.0.0"), None)

    assert caught.value.record.code is PlanningErrorCode.DISCOVERY_RESULT_INVALID
    assert client.requests == []


@pytest.mark.parametrize(
    ("substitution_call", "expected_provider_calls"),
    [(1, 0), (2, 0), (3, 1)],
    ids=("catalog-resolution", "catalog-declaration", "decoded-declaration"),
)
def test_direct_openai_rejects_a_later_nonexact_resolution(
    monkeypatch: pytest.MonkeyPatch,
    substitution_call: int,
    expected_provider_calls: int,
) -> None:
    registry = versioned_registry()
    discovery = _cards(registry, "avg@3.0.0")
    substituted = registry.resolve("sum@2.0.0")
    original_resolve = registry.resolve
    client = _RecordingClient(_response("avg@3.0.0"))
    resolve_calls = 0

    def substituting_resolve(self: OperatorRegistry, operator_id: str) -> Any:
        nonlocal resolve_calls
        if operator_id == "avg@3.0.0":
            resolve_calls += 1
            if resolve_calls == substitution_call:
                return substituted
        return original_resolve(operator_id)

    monkeypatch.setattr(registry, "resolve", MethodType(substituting_resolve, registry))
    generator = OpenAIPlanGenerator(
        "offline-scripted-test",
        registry=registry,
        allowed_operator_ids=("avg@3.0.0",),
        client=client,
    )

    with pytest.raises(PlanningError, match="requires supported built-in") as caught:
        generator.generate(_request(allowed=("avg@3.0.0",)), discovery, None)

    assert caught.value.record.code is PlanningErrorCode.DISCOVERY_RESULT_INVALID
    assert caught.value.record.stage is PlanningStage.DISCOVERY
    assert resolve_calls == substitution_call
    assert len(client.requests) == expected_provider_calls


def _foreign_boundary_error(marker: str) -> PlanningError:
    return planning_error(
        PlanningStage.GENERATION,
        PlanningErrorCode.GENERATION_FAILED,
        f"FOREIGN_BOUNDARY_SYNTHETIC_{marker}_MESSAGE",
        category=ErrorCategory.FAILED,
        suggestion=f"FOREIGN_BOUNDARY_SYNTHETIC_{marker}_SUGGESTION",
    )


def _assert_sanitized_registry_error(
    error: PlanningError,
    foreign: PlanningError | None = None,
) -> None:
    if foreign is not None:
        assert error is not foreign
    assert error.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.DISCOVERY_RESULT_INVALID,
        PlanningStage.DISCOVERY,
        "OpenAI plan generator requires supported built-in 2.0.0 or 3.0.0 operator cards",
        False,
        "Pass one shared, unmodified active_registry() or versioned_registry() instance "
        "to the generator and planner, or use a different plan generator.",
    )
    assert "FOREIGN_BOUNDARY_SYNTHETIC" not in str(error)


def _boundary_generator(
    registry: OperatorRegistry,
) -> tuple[OpenAIPlanGenerator, _RecordingClient]:
    client = _RecordingClient(_response("avg@3.0.0"))
    generator = OpenAIPlanGenerator(
        "offline-scripted-test",
        registry=registry,
        allowed_operator_ids=("avg@3.0.0",),
        client=client,
    )
    return generator, client


@pytest.mark.parametrize("lookup", [1, 2, 3])
def test_openai_contains_a_resolution_without_identity(
    monkeypatch: pytest.MonkeyPatch,
    lookup: int,
) -> None:
    registry = versioned_registry()
    discovery = _cards(registry, "avg@3.0.0")
    original_resolve = registry.resolve
    resolve_calls = 0

    def resolving_without_identity(self: OperatorRegistry, operator_id: str) -> Any:
        nonlocal resolve_calls
        resolve_calls += 1
        return None if resolve_calls == lookup else original_resolve(operator_id)

    monkeypatch.setattr(
        registry,
        "resolve",
        MethodType(resolving_without_identity, registry),
    )
    generator, client = _boundary_generator(registry)

    with pytest.raises(PlanningError) as caught:
        generator.generate(_request(allowed=("avg@3.0.0",)), discovery, None)

    _assert_sanitized_registry_error(caught.value)
    assert resolve_calls == lookup
    assert len(client.requests) == (1 if lookup == 3 else 0)


@pytest.mark.parametrize("lookup", [2, 3])
def test_openai_contains_a_foreign_declaration_error(
    monkeypatch: pytest.MonkeyPatch,
    lookup: int,
) -> None:
    registry = versioned_registry()
    discovery = _cards(registry, "avg@3.0.0")
    original_resolve = registry.resolve
    foreign = _foreign_boundary_error("DECLARATION")
    resolve_calls = 0

    class ForeignDeclaration:
        operator_id = "avg@3.0.0"

        @property
        def attributes(self) -> Any:
            raise foreign

    def resolving_foreign_declaration(self: OperatorRegistry, operator_id: str) -> Any:
        nonlocal resolve_calls
        resolve_calls += 1
        if resolve_calls == lookup:
            return ForeignDeclaration()
        return original_resolve(operator_id)

    monkeypatch.setattr(
        registry,
        "resolve",
        MethodType(resolving_foreign_declaration, registry),
    )
    generator, client = _boundary_generator(registry)

    with pytest.raises(PlanningError) as caught:
        generator.generate(_request(allowed=("avg@3.0.0",)), discovery, None)

    _assert_sanitized_registry_error(caught.value, foreign)
    assert resolve_calls == lookup
    assert len(client.requests) == (1 if lookup == 3 else 0)


@pytest.mark.parametrize("lookup", [1, 2, 3])
def test_openai_contains_a_foreign_identity_error(
    monkeypatch: pytest.MonkeyPatch,
    lookup: int,
) -> None:
    registry = versioned_registry()
    discovery = _cards(registry, "avg@3.0.0")
    original_resolve = registry.resolve
    foreign = _foreign_boundary_error("IDENTITY")
    resolve_calls = 0

    class ForeignIdentity:
        @property
        def operator_id(self) -> Any:
            raise foreign

    def resolving_foreign_identity(self: OperatorRegistry, operator_id: str) -> Any:
        nonlocal resolve_calls
        resolve_calls += 1
        if resolve_calls == lookup:
            return ForeignIdentity()
        return original_resolve(operator_id)

    monkeypatch.setattr(
        registry,
        "resolve",
        MethodType(resolving_foreign_identity, registry),
    )
    generator, client = _boundary_generator(registry)

    with pytest.raises(PlanningError) as caught:
        generator.generate(_request(allowed=("avg@3.0.0",)), discovery, None)

    _assert_sanitized_registry_error(caught.value, foreign)
    assert resolve_calls == lookup
    assert len(client.requests) == (1 if lookup == 3 else 0)


def test_openai_contains_a_foreign_identity_comparison_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = versioned_registry()
    discovery = _cards(registry, "avg@3.0.0")
    foreign = _foreign_boundary_error("COMPARISON")

    class ForeignComparison:
        def __eq__(self, other: object) -> bool:
            del other
            raise foreign

    class ForeignIdentity:
        operator_id = ForeignComparison()

    def resolving_comparison(self: OperatorRegistry, operator_id: str) -> Any:
        del self, operator_id
        return ForeignIdentity()

    monkeypatch.setattr(
        registry,
        "resolve",
        MethodType(resolving_comparison, registry),
    )
    generator, client = _boundary_generator(registry)

    with pytest.raises(PlanningError) as caught:
        generator.generate(_request(allowed=("avg@3.0.0",)), discovery, None)

    _assert_sanitized_registry_error(caught.value, foreign)
    assert client.requests == []


def test_openai_v3_side_effect_card_is_neither_disclosed_nor_authorized() -> None:
    registry = versioned_registry()
    client = _RecordingClient(_response("avg@3.0.0"))
    allowed = ("avg@3.0.0", "insert_table@3.0.0")
    generator = OpenAIPlanGenerator(
        "offline-scripted-test",
        registry=registry,
        allowed_operator_ids=allowed,
        client=client,
    )

    generator.generate(_request(allowed=allowed), _cards(registry, *allowed), None)

    payload = json.loads(client.requests[0]["input"][0]["content"])
    assert [card["operator_id"] for card in payload["operators"]] == ["avg@3.0.0"]


@pytest.mark.parametrize("operator_id", ["avg@1.0.0", "avg@4.0.0", "avg"])
def test_openai_constructor_rejects_noncurrent_versions_without_a_call(
    operator_id: str,
) -> None:
    client = _RecordingClient(_response("avg@3.0.0"))

    with pytest.raises(PlanningError) as caught:
        OpenAIPlanGenerator(
            "offline-scripted-test",
            registry=versioned_registry(),
            allowed_operator_ids=(operator_id,),
            client=client,
        )

    assert caught.value.record.code is PlanningErrorCode.INVALID_REQUEST
    assert caught.value.record.stage is PlanningStage.VALIDATION
    assert client.requests == []
