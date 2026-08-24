from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import fields
from typing import Any, Literal, cast

import pytest

from blue_data_ops.operators import OperatorCard, versioned_registry
from blue_data_ops.operators.types import ErrorCategory
from blue_data_ops.plan import (
    SELECT_THEN_AVERAGE_TEMPLATE,
    DataContextSnapshot,
    DataScope,
    DiscoveryQuery,
    DiscoverySnapshot,
    PipelinePlanner,
    PlanDraft,
    PlanningError,
    PlanningErrorCode,
    PlanningRequest,
    PlanningResult,
    PlanningStage,
    PlanStep,
    RulePlanGenerator,
    RuleTemplateStep,
    project_then_aggregate_template,
)


def _select_average_request() -> PlanningRequest:
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
    )


def _project_sum_request() -> PlanningRequest:
    return PlanningRequest(
        goal="Keep the order total and calculate its sum",
        discovery_queries=(
            DiscoveryQuery(
                "projection",
                ("flow-transform", "accepts-data", "capability-projection"),
            ),
            DiscoveryQuery(
                "sum",
                ("flow-aggregate", "accepts-data", "capability-sum"),
            ),
        ),
        operator_attributes={
            "project": {
                "kept_keys": ["total"],
                "key_mapping": {"total": "amount"},
            },
            "sum": {"sum_key": "amount", "output_key": "total_amount"},
        },
        allowed_operator_ids=("project@2.0.0", "sum@2.0.0"),
    )


def _snapshot(*operator_names: str) -> DiscoverySnapshot:
    registry = versioned_registry()
    cards = tuple(
        card for name in operator_names if (card := registry.get_card(f"{name}@2.0.0")) is not None
    )
    return DiscoverySnapshot(cards)


def test_default_generator_still_uses_select_then_average_template() -> None:
    request = _select_average_request()
    discovery = _snapshot("select", "avg")

    assert RulePlanGenerator().generate(request, discovery, None) == (
        SELECT_THEN_AVERAGE_TEMPLATE.generate(request, discovery, None),
    )


def test_select_then_average_template_executes_existing_rule() -> None:
    result = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((SELECT_THEN_AVERAGE_TEMPLATE,)),
    ).run(
        _select_average_request(),
        [
            [
                {"order_id": 1, "total": 80.0},
                {"order_id": 2, "total": 125.0},
                {"order_id": 3, "total": 210.0},
                {"order_id": 4, "total": 100.0},
            ]
        ],
    )

    assert result.planning.selected.label == "select-then-average"
    assert result.planning.preflight.operator_ids == ("select@2.0.0", "avg@2.0.0")
    assert result.execution.output_data == [[{"average_total": 167.5}]]


def test_project_then_sum_uses_explicit_projection_and_aggregate_fields() -> None:
    result = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((project_then_aggregate_template("sum"),)),
    ).run(
        _project_sum_request(),
        [
            [
                {"order_id": 1, "total": 80.0},
                {"order_id": 2, "total": 125.0},
            ]
        ],
    )

    assert result.planning.preflight.operator_ids == ("project@2.0.0", "sum@2.0.0")
    assert result.execution.output_data == [[{"total_amount": 205.0}]]


@pytest.mark.parametrize(
    ("aggregate", "required_key", "capability"),
    [
        ("avg", "avg_key", "capability-average"),
        ("sum", "sum_key", "capability-sum"),
        ("min", "min_key", "capability-extrema"),
        ("max", "max_key", "capability-extrema"),
    ],
)
def test_project_aggregate_templates_pin_current_names_tags_and_attributes(
    aggregate: Literal["avg", "sum", "min", "max"],
    required_key: str,
    capability: str,
) -> None:
    template = project_then_aggregate_template(aggregate)
    assert template.steps[0] == RuleTemplateStep(
        step_id="project",
        operator_name="project",
        required_attributes=("kept_keys",),
        expected_tags=(
            "domain-relational",
            "flow-transform",
            "accepts-data",
            "produces-data",
            "capability-projection",
        ),
    )
    assert template.steps[1].operator_name == aggregate
    assert template.steps[1].required_attributes == (required_key, "output_key")
    assert capability in template.steps[1].expected_tags
    request = PlanningRequest(
        goal=f"Project records, then apply {aggregate}",
        discovery_queries=(DiscoveryQuery("projection"),),
        operator_attributes={
            "project": {"kept_keys": ["value"]},
            aggregate: {required_key: "value", "output_key": "result"},
        },
    )
    draft = template.generate(request, _snapshot("project", aggregate), None)
    assert tuple(step.operator_id for step in draft.steps) == (
        "project@2.0.0",
        f"{aggregate}@2.0.0",
    )


def test_project_aggregate_template_rejects_unknown_operator_name() -> None:
    with pytest.raises(PlanningError, match="unsupported aggregate operator") as caught:
        project_then_aggregate_template(cast(Any, "median"))
    assert caught.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.GENERATION_FAILED,
        PlanningStage.GENERATION,
        "unsupported aggregate operator; expected avg, sum, min, or max",
        False,
        "Correct the rule template configuration.",
    )


class _AggregateName(str):
    pass


class _HashBomb:
    def __init__(self) -> None:
        self.calls = 0

    def __hash__(self) -> int:
        self.calls += 1
        raise RuntimeError("payload-should-not-leak")


@pytest.mark.parametrize("value", [_AggregateName("avg"), _HashBomb()])
def test_project_aggregate_template_contains_hostile_names(value: object) -> None:
    with pytest.raises(PlanningError) as caught:
        project_then_aggregate_template(cast(Any, value))

    assert caught.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.GENERATION_FAILED,
        PlanningStage.GENERATION,
        "unsupported aggregate operator; expected avg, sum, min, or max",
        False,
        "Correct the rule template configuration.",
    )
    if type(value) is _HashBomb:
        assert value.calls == 0


def test_template_requires_all_field_and_output_names() -> None:
    request = _project_sum_request()
    cast(dict[str, Any], request.operator_attributes["sum"]).pop("output_key")

    with pytest.raises(PlanningError) as caught:
        project_then_aggregate_template("sum").generate(request, _snapshot("project", "sum"), None)

    assert caught.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.INVALID_REQUEST,
        PlanningStage.VALIDATION,
        "project and sum attributes are incomplete for the project-then-sum template",
        False,
        "Correct the planning request and try again.",
    )


def test_default_rule_keeps_the_missing_attribute_record() -> None:
    request = _select_average_request()
    cast(dict[str, Any], request.operator_attributes["avg"]).pop("output_key")

    with pytest.raises(PlanningError) as caught:
        RulePlanGenerator().generate(request, _snapshot("select", "avg"), None)

    assert caught.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.INVALID_REQUEST,
        PlanningStage.VALIDATION,
        "select and avg attributes are incomplete for the average rule",
        False,
        "Correct the planning request and try again.",
    )


@pytest.mark.parametrize(
    ("discovery", "missing_name"),
    [
        (DiscoverySnapshot(()), "select"),
        (_snapshot("select"), "avg"),
    ],
)
def test_default_rule_checks_discovery_before_missing_attributes(
    discovery: DiscoverySnapshot,
    missing_name: str,
) -> None:
    request = _select_average_request()
    cast(dict[str, Mapping[str, Any]], request.operator_attributes).clear()

    with pytest.raises(PlanningError) as caught:
        RulePlanGenerator().generate(request, discovery, None)

    assert caught.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.DISCOVERY_RESULT_INVALID,
        PlanningStage.DISCOVERY,
        f"expected one discovered {missing_name!r} operator, got []",
        False,
        "Narrow discovery until exactly one required operator remains.",
    )


def test_template_rejects_a_card_with_different_tags() -> None:
    request = _project_sum_request()
    project, total = _snapshot("project", "sum").cards
    changed = OperatorCard(
        operator_id=project.operator_id,
        name=project.name,
        version=project.version,
        description=project.description,
        tags=project.tags[:-1],
        when_to_invoke=project.when_to_invoke,
    )

    with pytest.raises(PlanningError) as caught:
        project_then_aggregate_template("sum").generate(
            request,
            DiscoverySnapshot((changed, total)),
            None,
        )

    assert caught.value.record.code is PlanningErrorCode.DISCOVERY_RESULT_INVALID
    assert caught.value.record.stage is PlanningStage.DISCOVERY
    assert str(caught.value) == "discovered 'project' metadata does not match the rule template"


def test_template_rejects_a_non_v2_card() -> None:
    request = _project_sum_request()
    project, total = _snapshot("project", "sum").cards
    changed = OperatorCard(
        operator_id="project@1.0.0",
        name=project.name,
        version="1.0.0",
        description=project.description,
        tags=project.tags,
        when_to_invoke=project.when_to_invoke,
    )

    with pytest.raises(PlanningError, match="metadata does not match"):
        project_then_aggregate_template("sum").generate(
            request,
            DiscoverySnapshot((changed, total)),
            None,
        )


def test_template_draft_does_not_alias_request_attributes() -> None:
    request = _project_sum_request()
    original = deepcopy(request.operator_attributes)
    draft = project_then_aggregate_template("sum").generate(
        request, _snapshot("project", "sum"), None
    )

    request.operator_attributes["project"]["kept_keys"].append("currency")
    assert draft.steps[0].attributes == original["project"]

    draft.steps[0].attributes["kept_keys"].append("status")
    assert request.operator_attributes["project"] == {
        "kept_keys": ["total", "currency"],
        "key_mapping": {"total": "amount"},
    }


def test_template_works_as_a_rule_without_changing_custom_rule_support() -> None:
    custom_draft = PlanDraft((PlanStep("project", "project@2.0.0", {"kept_keys": ["total"]}),))

    def custom_rule(
        request: PlanningRequest,
        discovery: DiscoverySnapshot,
        data_context: DataContextSnapshot | None,
    ) -> PlanDraft:
        del request, discovery, data_context
        return custom_draft

    generator = RulePlanGenerator((project_then_aggregate_template("sum"), custom_rule))
    generated = generator.generate(
        _project_sum_request(),
        _snapshot("project", "sum"),
        None,
    )

    assert generated[0].label == "project-then-sum"
    assert generated[1] is custom_draft


def test_existing_request_and_draft_record_shapes_are_unchanged() -> None:
    assert tuple(field.name for field in fields(PlanningRequest)) == (
        "goal",
        "discovery_queries",
        "operator_attributes",
        "data_scope",
        "allowed_operator_ids",
        "input_label",
        "output_label",
        "max_discovery_cards",
        "max_candidates",
        "max_steps",
        "max_nodes",
        "max_edges",
    )
    assert tuple(field.name for field in fields(PlanDraft)) == ("steps", "label")
    assert tuple(field.name for field in fields(PlanningResult)) == (
        "request",
        "discovery",
        "candidates",
        "selected",
        "pipeline",
        "preflight",
        "data_context",
    )
    assert tuple(field.name for field in fields(DataScope)) == (
        "source",
        "database",
        "collection",
        "entities",
    )
