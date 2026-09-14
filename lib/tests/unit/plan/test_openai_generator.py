"""Focused verification for the direct OpenAI plan generator.

Every test here runs against `RecordingClient`, a double exposing only the two calls the
adapter makes. It never imports the real SDK, reads a credential, or opens a socket; the
separate transport test proves the same request shape against the official client.

The suite is organized around the two boundaries the module defends: what may reach the
provider, and what the provider's answer may become.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from blue_data_ops.operators.registry import (
    OperatorCard,
    OperatorRegistry,
    default_registry,
    versioned_registry,
)
from blue_data_ops.operators.select_operator import SelectOperator
from blue_data_ops.operators.types import ErrorCategory
from blue_data_ops.plan import (
    DiscoveryQuery,
    OpenAIPlanGenerator,
    PlanningError,
    PlanningErrorCode,
    PlanningRequest,
    PlanningStage,
)
from blue_data_ops.plan.openai_generator import (
    PLANNER_INSTRUCTIONS,
    PLANNING_INPUT_FORMAT,
    response_format,
)
from blue_data_ops.plan.planner import DiscoverySnapshot

MODEL = "gpt-5-2026-01-01"
ALLOWED = ("nl2sql@2.0.0", "select@2.0.0", "avg@2.0.0")

NO_ATTRIBUTES: dict[str, Any] = {}
SELECT_ATTRIBUTES: dict[str, Any] = {
    "operand_key": "total",
    "operand": ">",
    "operand_val": 100,
}
AVG_ATTRIBUTES = {"avg_key": "total", "output_key": "average_total"}
NL2SQL_ATTRIBUTES = {
    "source": "demo_sqlite",
    "protocol": "sqlite",
    "database": "shop",
    "collection": "public",
    "question": "Average order total above 100",
}


# --- Doubles ------------------------------------------------------------------------ #
class RecordingClient:
    """The narrow surface the adapter touches, plus an append-only call log."""

    def __init__(self, response: Any = None, error: BaseException | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def with_options(self, **kwargs: Any) -> RecordingClient:
        self.calls.append(("with_options", kwargs))
        return self

    @property
    def responses(self) -> RecordingClient:
        return self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(("create", kwargs))
        if self.error is not None:
            raise self.error
        return self.response

    @property
    def create_calls(self) -> list[dict[str, Any]]:
        return [payload for name, payload in self.calls if name == "create"]


def completed(payload: Any, *, status: str = "completed") -> Any:
    text = payload if type(payload) is str else json.dumps(payload)
    part = SimpleNamespace(type="output_text", text=text)
    return SimpleNamespace(status=status, output=[SimpleNamespace(content=[part])])


def refusal() -> Any:
    part = SimpleNamespace(type="refusal", refusal="cannot help with that")
    return SimpleNamespace(status="completed", output=[SimpleNamespace(content=[part])])


def step(
    step_id: str,
    operator_id: str,
    attributes: dict[str, Any],
    depends_on: list[str] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "operator_id": operator_id,
        "attributes_json": json.dumps(attributes),
        "depends_on": depends_on or [],
        "label": label,
    }


def candidates(*steps: dict[str, Any], label: str | None = "orders-plan") -> dict[str, Any]:
    return {"candidates": [{"label": label, "steps": list(steps)}]}


ORDERS_PAYLOAD = candidates(
    step("query", "nl2sql@2.0.0", NL2SQL_ATTRIBUTES),
    step("filter", "select@2.0.0", SELECT_ATTRIBUTES, ["query"]),
    step("average", "avg@2.0.0", AVG_ATTRIBUTES, ["filter"]),
)

# The same graph without nl2sql, for the cases that deliberately run with no snapshot.
# An nl2sql candidate now requires a disclosed data context, so a scopeless fixture
# cannot use the orders graph.
SCOPELESS_PAYLOAD = candidates(
    step("filter", "select@2.0.0", SELECT_ATTRIBUTES),
    step("average", "avg@2.0.0", AVG_ATTRIBUTES, ["filter"]),
)


# --- Fixtures ----------------------------------------------------------------------- #
def orders_request(**overrides: Any) -> PlanningRequest:
    fields: dict[str, Any] = {
        "goal": "Average order total above 100",
        "discovery_queries": (DiscoveryQuery("nl2sql"),),
        "operator_attributes": {
            "nl2sql": dict(NL2SQL_ATTRIBUTES),
            "select": dict(SELECT_ATTRIBUTES),
            "avg": dict(AVG_ATTRIBUTES),
        },
    }
    fields.update(overrides)
    return PlanningRequest(**fields)


def discovery_of(registry: OperatorRegistry, ids: tuple[str, ...] = ALLOWED) -> DiscoverySnapshot:
    cards: list[Any] = []
    for operator_id in ids:
        card = registry.get_card(operator_id)
        assert card is not None
        cards.append(card)
    return DiscoverySnapshot(tuple(cards))


NO_CLIENT = cast(Any, object())
"""Sentinel: `build(client=NO_CLIENT)` constructs with no client, forcing the lazy import."""


def build(
    registry: OperatorRegistry | None = None,
    client: Any = None,
    **overrides: Any,
) -> tuple[OpenAIPlanGenerator, OperatorRegistry, RecordingClient]:
    shared = versioned_registry() if registry is None else registry
    if client is NO_CLIENT:
        double = cast(Any, None)
    else:
        double = RecordingClient(completed(ORDERS_PAYLOAD)) if client is None else client
    options: dict[str, Any] = {
        "allowed_operator_ids": ALLOWED,
        "client": double,
        "send_data_context": True,
    }
    options.update(overrides)
    generator = OpenAIPlanGenerator(MODEL, registry=shared, **options)
    return generator, shared, double


_DEFAULT_SNAPSHOT = cast(Any, object())


def generate(
    generator: OpenAIPlanGenerator,
    registry: OperatorRegistry,
    *,
    request: PlanningRequest | None = None,
    ids: tuple[str, ...] = ALLOWED,
    data_context: Any = _DEFAULT_SNAPSHOT,
) -> Any:
    supplied = FakeSnapshot() if data_context is _DEFAULT_SNAPSHOT else data_context
    return generator.generate(
        request or orders_request(), discovery_of(registry, ids), cast(Any, supplied)
    )


class FakeSnapshot:
    """Stands in for a data-context snapshot; the generator only serializes it."""

    def __init__(self, document: dict[str, Any] | None = None) -> None:
        self.document = document or {"format": "blue-data-ops/data-context@1", "protocol": "sqlite"}

    def to_dict(self) -> dict[str, Any]:
        return dict(self.document)


# --- 1. The happy path and the exact outbound request ------------------------------- #
def test_one_call_returns_the_three_step_orders_graph() -> None:
    generator, registry, client = build()

    drafts = generate(generator, registry)

    assert len(drafts) == 1
    assert [item.operator_id for item in drafts[0].steps] == list(ALLOWED)
    assert [item.step_id for item in drafts[0].steps] == ["query", "filter", "average"]
    assert drafts[0].steps[2].depends_on == ("filter",)
    assert drafts[0].label == "orders-plan"
    assert len(client.create_calls) == 1


def test_the_request_disables_retries_and_propagates_the_timeout() -> None:
    generator, registry, client = build(timeout_seconds=12.5)

    generate(generator, registry)

    assert client.calls[0] == ("with_options", {"max_retries": 0, "timeout": 12.5})


def test_the_request_is_nonstreaming_unstored_and_foreground() -> None:
    generator, registry, client = build(max_output_tokens=2048)

    generate(generator, registry)

    sent = client.create_calls[0]
    assert sent["model"] == MODEL
    assert sent["background"] is False
    assert sent["store"] is False
    assert sent["stream"] is False
    assert sent["max_output_tokens"] == 2048
    assert sent["instructions"] == PLANNER_INSTRUCTIONS
    assert sent["text"] == {"format": response_format()}


def test_the_request_carries_no_tools_or_continuation_state() -> None:
    generator, registry, client = build()

    generate(generator, registry)

    forbidden = {"tools", "tool_choice", "previous_response_id", "conversation", "prompt", "files"}
    assert forbidden.isdisjoint(client.create_calls[0])


def test_the_user_content_is_the_canonical_planning_document() -> None:
    generator, registry, client = build()

    generate(generator, registry)

    content = client.create_calls[0]["input"]
    assert [entry["role"] for entry in content] == ["user"]
    document = json.loads(content[0]["content"])
    assert document["format"] == PLANNING_INPUT_FORMAT
    assert document["goal"] == "Average order total above 100"
    assert [entry["operator_id"] for entry in document["operators"]] == list(ALLOWED)
    assert document["limits"]["max_candidates"] == 1
    assert document["data_context"] == FakeSnapshot().to_dict()
    # Canonical encoding: sorted keys, no incidental whitespace.
    assert content[0]["content"] == json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


# --- 2. The four registry catalogs -------------------------------------------------- #
def test_the_package_factory_catalog_is_accepted() -> None:
    generator, registry, client = build()

    generate(generator, registry)

    assert len(client.create_calls) == 1


def test_raw_default_override_cannot_erase_write_policy_before_a_call() -> None:
    registry = default_registry(create_database="2.0.0")
    operator_id = "create_database@2.0.0"
    card = registry.get_card(operator_id)
    assert card is not None
    assert card.tags == ()
    client = RecordingClient(completed(candidates(step("write", operator_id, {}))))
    generator = OpenAIPlanGenerator(
        MODEL,
        registry=registry,
        allowed_operator_ids=(operator_id,),
        client=client,
    )
    request = PlanningRequest(
        goal="Create a database",
        discovery_queries=(DiscoveryQuery("create_database"),),
        allowed_operator_ids=(operator_id,),
    )

    with pytest.raises(PlanningError, match="requires supported built-in") as caught:
        generator.generate(request, DiscoverySnapshot((card,)), None)

    assert caught.value.record.code is PlanningErrorCode.DISCOVERY_RESULT_INVALID
    assert client.calls == []


def test_a_permissive_custom_registry_is_rejected_before_any_call() -> None:
    custom = OperatorRegistry()
    custom.register(SelectOperator(), "2.0.0")
    generator, _, client = build(registry=custom)

    with pytest.raises(PlanningError, match="requires supported built-in") as caught:
        generator.generate(orders_request(), discovery_of(custom, ("select@2.0.0",)), None)

    assert caught.value.record.code is PlanningErrorCode.DISCOVERY_RESULT_INVALID
    assert caught.value.record.stage is PlanningStage.DISCOVERY
    assert client.calls == []


def test_a_custom_card_added_to_a_factory_registry_is_rejected() -> None:
    # Pinned at 2.0.0 under a fresh name so it clears the allowlist's version check and
    # actually reaches the provenance test: public register() leaves it unmarked.
    registry = versioned_registry()
    custom_card = registry.register(SelectOperator(name="custom_select"), "2.0.0")
    generator, _, client = build(
        registry=registry, allowed_operator_ids=("custom_select@2.0.0",) + ALLOWED
    )

    with pytest.raises(PlanningError, match="requires supported built-in"):
        generator.generate(orders_request(), DiscoverySnapshot((custom_card,)), None)

    assert client.calls == []


def test_a_card_from_a_second_factory_instance_is_rejected() -> None:
    # The generator reads live declarations out of its own registry, so an
    # equal-looking card from another versioned_registry() is not interchangeable.
    generator, _, client = build()
    other = versioned_registry()

    with pytest.raises(PlanningError, match="requires supported built-in"):
        generator.generate(orders_request(), discovery_of(other), None)

    assert client.calls == []


def test_an_empty_discovery_intersection_reports_no_authorized_operators() -> None:
    generator, registry, client = build()
    unrelated = discovery_of(registry, ("union@2.0.0",))

    with pytest.raises(PlanningError, match="no authorized operators were discovered") as caught:
        generator.generate(orders_request(), unrelated, None)

    assert caught.value.record.code is PlanningErrorCode.DISCOVERY_RESULT_INVALID
    assert caught.value.record.retryable is False
    assert client.calls == []


# --- 3. Write cards are never offered and never accepted ---------------------------- #
@pytest.mark.parametrize(
    "write_id", ["create_database@2.0.0", "create_table@2.0.0", "insert_table@2.0.0"]
)
def test_a_built_in_write_card_is_never_offered_to_the_model(write_id: str) -> None:
    registry = versioned_registry()
    generator, _, client = build(registry=registry, allowed_operator_ids=ALLOWED + (write_id,))

    generator.generate(
        orders_request(),
        discovery_of(registry, ALLOWED + (write_id,)),
        cast(Any, FakeSnapshot()),
    )

    document = json.loads(client.create_calls[0]["input"][0]["content"])
    assert write_id not in [entry["operator_id"] for entry in document["operators"]]


@pytest.mark.parametrize(
    "write_id", ["create_database@2.0.0", "create_table@2.0.0", "insert_table@2.0.0"]
)
def test_a_model_selected_write_card_is_rejected_at_decode(write_id: str) -> None:
    registry = versioned_registry()
    payload = candidates(step("write", write_id, {}))
    generator, _, _ = build(
        registry=registry,
        client=RecordingClient(completed(payload)),
        allowed_operator_ids=ALLOWED + (write_id,),
    )

    with pytest.raises(PlanningError, match="unauthorized operator") as caught:
        generator.generate(orders_request(), discovery_of(registry, ALLOWED + (write_id,)), None)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID


def test_an_allowlist_of_only_write_cards_never_reaches_a_provider() -> None:
    registry = versioned_registry()
    writes = ("create_table@2.0.0",)
    generator, _, client = build(registry=registry, allowed_operator_ids=writes)

    with pytest.raises(PlanningError, match="no authorized operators were discovered"):
        generator.generate(orders_request(), discovery_of(registry, writes), None)

    assert client.calls == []


# --- 3b. Deprecated cards are never offered and never accepted ---------------------- #
DEPRECATED_ID = "plan_discover@2.0.0"


def test_a_retired_id_is_rejected_before_provider_work() -> None:
    registry = versioned_registry()
    client = RecordingClient(completed(candidates(step("average", "avg@2.0.0", AVG_ATTRIBUTES))))
    generator, _, _ = build(
        registry=registry,
        client=client,
        allowed_operator_ids=(DEPRECATED_ID,),
    )

    assert registry.get_card(DEPRECATED_ID) is None
    with pytest.raises(PlanningError, match="no authorized operators") as caught:
        generator.generate(orders_request(), DiscoverySnapshot(()), None)

    assert caught.value.record.code is PlanningErrorCode.DISCOVERY_RESULT_INVALID
    assert client.calls == []


@pytest.mark.parametrize("forged_flag", [True, False])
def test_a_forged_card_fails_provenance_rather_than_the_lifecycle_skip(forged_flag: bool) -> None:
    """Ordering: the flag read has to be the registry's own value, not the caller's.

    A caller can hand the generator any object shaped like a card. The lifecycle skip sits
    after `is_builtin_card`, so neither flag value changes the outcome: a forged card is a
    wiring error, reported. Moved ahead of the provenance test, the `True` case would be
    dropped in silence and this would report the empty-catalog error instead.
    """

    registry = versioned_registry()
    forged = OperatorCard(
        DEPRECATED_ID,
        "plan_discover",
        "2.0.0",
        "Discover operators for a plan.",
        deprecated=forged_flag,
    )
    generator, _, client = build(
        registry=registry, allowed_operator_ids=(DEPRECATED_ID, "avg@2.0.0")
    )

    with pytest.raises(PlanningError, match="requires supported built-in") as caught:
        generator.generate(orders_request(), DiscoverySnapshot((forged,)), None)

    assert caught.value.record.code is PlanningErrorCode.DISCOVERY_RESULT_INVALID
    assert client.calls == []


# --- 4. Disclosure ordering --------------------------------------------------------- #
def test_a_snapshot_without_disclosure_fails_before_any_provider_work() -> None:
    generator, registry, client = build(send_data_context=False)

    with pytest.raises(PlanningError, match="data context disclosure is not enabled") as caught:
        generate(generator, registry, data_context=FakeSnapshot())

    record = caught.value.record
    assert record.code is PlanningErrorCode.DATA_CONTEXT_DISCLOSURE_REQUIRED
    assert record.stage is PlanningStage.GENERATION
    assert record.category is ErrorCategory.RECOVERABLE
    assert record.retryable is False
    assert record.suggestion == "Set send_data_context=True to send the planning snapshot."
    assert client.calls == []


def test_disclosure_is_checked_before_the_registry_boundary() -> None:
    # Ordering matters: an unauthorized snapshot must not even be evaluated against a
    # catalog, so this fails on disclosure rather than on the custom registry.
    custom = OperatorRegistry()
    custom.register(SelectOperator(), "2.0.0")
    generator, _, client = build(registry=custom, send_data_context=False)

    with pytest.raises(PlanningError, match="disclosure is not enabled"):
        generator.generate(
            orders_request(),
            discovery_of(custom, ("select@2.0.0",)),
            cast(Any, FakeSnapshot()),
        )

    assert client.calls == []


def test_an_enabled_snapshot_is_sent_exactly_once() -> None:
    generator, registry, client = build(send_data_context=True)
    snapshot = FakeSnapshot({"format": "blue-data-ops/data-context@1", "protocol": "sql/sqlite"})

    generate(generator, registry, data_context=snapshot)

    document = json.loads(client.create_calls[0]["input"][0]["content"])
    assert document["data_context"] == snapshot.to_dict()


def test_no_snapshot_means_no_data_context_field() -> None:
    generator, registry, client = build(client=RecordingClient(completed(SCOPELESS_PAYLOAD)))

    generate(generator, registry, data_context=None)

    assert "data_context" not in json.loads(client.create_calls[0]["input"][0]["content"])


# --- 5. Caller attributes are immutable constraints --------------------------------- #
def test_an_omitted_caller_attribute_survives_the_model_response() -> None:
    payload = candidates(step("filter", "select@2.0.0", {"operand_key": "total"}))
    generator, registry, _ = build(client=RecordingClient(completed(payload)))

    drafts = generate(generator, registry)

    assert dict(drafts[0].steps[0].attributes) == SELECT_ATTRIBUTES


def test_a_declared_model_only_attribute_is_accepted() -> None:
    payload = candidates(
        step("filter", "select@2.0.0", {**SELECT_ATTRIBUTES, "approximate_match": True})
    )
    generator, registry, _ = build(client=RecordingClient(completed(payload)))

    drafts = generate(generator, registry)

    assert drafts[0].steps[0].attributes["approximate_match"] is True


def test_an_undeclared_model_attribute_is_rejected() -> None:
    payload = candidates(step("filter", "select@2.0.0", {**SELECT_ATTRIBUTES, "not_declared": "x"}))
    generator, registry, _ = build(client=RecordingClient(completed(payload)))

    with pytest.raises(PlanningError, match="undeclared operator attribute") as caught:
        generate(generator, registry)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID


@pytest.mark.parametrize("conflict", [{"operand_val": 999}, {"operand_val": "100"}])
def test_a_conflicting_overlapping_attribute_fails(conflict: dict[str, Any]) -> None:
    payload = candidates(step("filter", "select@2.0.0", {**SELECT_ATTRIBUTES, **conflict}))
    generator, registry, _ = build(client=RecordingClient(completed(payload)))

    with pytest.raises(
        PlanningError, match="conflicted with a caller-supplied attribute"
    ) as caught:
        generate(generator, registry)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID


def test_an_agreeing_overlapping_attribute_is_accepted() -> None:
    payload = candidates(step("filter", "select@2.0.0", dict(SELECT_ATTRIBUTES)))
    generator, registry, _ = build(client=RecordingClient(completed(payload)))

    drafts = generate(generator, registry)

    assert dict(drafts[0].steps[0].attributes) == SELECT_ATTRIBUTES


def test_an_undeclared_attribute_is_rejected_even_when_the_caller_supplied_it() -> None:
    """Declaration is checked before overlap, so agreement cannot smuggle a key through.

    With the overlap test first this case took the `continue` and skipped the declaration
    check, admitting a model-authored key outside the operator's schema whenever the
    caller happened to name the same key.
    """

    request = orders_request(
        operator_attributes={
            "nl2sql": dict(NL2SQL_ATTRIBUTES),
            "select": {**SELECT_ATTRIBUTES, "not_declared": "same"},
            "avg": dict(AVG_ATTRIBUTES),
        }
    )
    payload = candidates(
        step("filter", "select@2.0.0", {**SELECT_ATTRIBUTES, "not_declared": "same"})
    )
    generator, registry, _ = build(client=RecordingClient(completed(payload)))

    with pytest.raises(PlanningError, match="undeclared operator attribute") as caught:
        generate(generator, registry, request=request)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID


def test_a_planning_error_from_an_injected_client_does_not_reach_the_record() -> None:
    """An injected client is a public seam, so its PlanningError is foreign text.

    Passing it through published the provider's own message as both `str(error)` and
    `record.message`, carrying its forged classification with it.
    """

    class RaisingClient:
        def with_options(self, **_: Any) -> Any:
            return self

        @property
        def responses(self) -> Any:
            class _Responses:
                def create(self, **_: Any) -> Any:
                    raise PlanningError("PROVIDER-DETAIL-MUST-NOT-LEAK")

            return _Responses()

    generator, registry, _ = build(client=RaisingClient())

    with pytest.raises(PlanningError) as caught:
        generate(generator, registry)

    assert "PROVIDER-DETAIL-MUST-NOT-LEAK" not in str(caught.value)
    assert "PROVIDER-DETAIL-MUST-NOT-LEAK" not in caught.value.record.message
    assert caught.value.record.code is PlanningErrorCode.GENERATION_FAILED
    assert caught.value.record.stage is PlanningStage.GENERATION


def test_decoded_containers_are_fresh() -> None:
    generator, registry, _ = build()
    request = orders_request()

    drafts = generate(generator, registry, request=request)

    decoded = drafts[0].steps[1].attributes
    assert decoded is not request.operator_attributes["select"]
    assert dict(decoded) == SELECT_ATTRIBUTES


# --- 6. Response validation against the packaged resource --------------------------- #
def test_the_packaged_resource_is_the_strict_provider_format() -> None:
    document = response_format()

    assert document["type"] == "json_schema"
    assert document["strict"] is True
    # The outbound schema carries no string-length keyword.
    assert "maxLength" not in json.dumps(document)
    assert document["schema"]["properties"]["candidates"]["maxItems"] == 1


def test_response_format_returns_a_fresh_document_each_call() -> None:
    first = response_format()
    first["schema"]["properties"].clear()

    assert response_format()["schema"]["properties"]["candidates"]["maxItems"] == 1


# Each entry breaks one rule the packaged schema states: candidate count, a missing
# required field, an unknown field, a mistyped label, an incomplete step, a missing root.
OFF_SCHEMA_PAYLOADS: list[dict[str, Any]] = [
    {"candidates": []},
    {"candidates": [{"label": None}]},
    {"candidates": [{"label": None, "steps": [], "extra": 1}]},
    {"candidates": [{"label": 7, "steps": [step("a", "select@2.0.0", NO_ATTRIBUTES)]}]},
    {"candidates": [{"label": None, "steps": [{"step_id": "a"}]}]},
    {"steps": []},
]


@pytest.mark.parametrize("payload", OFF_SCHEMA_PAYLOADS)
def test_a_response_outside_the_schema_is_invalid(payload: dict[str, Any]) -> None:
    generator, registry, _ = build(client=RecordingClient(completed(payload)))

    with pytest.raises(PlanningError, match="returned an invalid response") as caught:
        generate(generator, registry)

    assert caught.value.record.code is PlanningErrorCode.GENERATOR_RESPONSE_INVALID
    assert caught.value.record.category is ErrorCategory.FAILED


def test_more_candidates_than_the_schema_permits_are_rejected() -> None:
    one = {"label": None, "steps": [step("filter", "select@2.0.0", SELECT_ATTRIBUTES)]}
    generator, registry, _ = build(client=RecordingClient(completed({"candidates": [one, one]})))

    with pytest.raises(PlanningError, match="returned an invalid response"):
        generate(generator, registry)


@pytest.mark.parametrize("raw", ["not json", "[]", '{"candidates": [] ', "null"])
def test_unparseable_output_is_invalid(raw: str) -> None:
    generator, registry, _ = build(client=RecordingClient(completed(raw)))

    with pytest.raises(PlanningError, match="returned an invalid response"):
        generate(generator, registry)


def test_a_duplicate_outer_key_is_rejected() -> None:
    raw = '{"candidates": [], "candidates": []}'
    generator, registry, _ = build(client=RecordingClient(completed(raw)))

    with pytest.raises(PlanningError, match="returned an invalid response"):
        generate(generator, registry)


def test_a_duplicate_inner_attribute_key_is_rejected() -> None:
    payload = candidates(
        {
            "step_id": "filter",
            "operator_id": "select@2.0.0",
            "attributes_json": '{"operand_key": "a", "operand_key": "b"}',
            "depends_on": [],
            "label": None,
        }
    )
    generator, registry, _ = build(client=RecordingClient(completed(payload)))

    with pytest.raises(PlanningError, match="returned an invalid response"):
        generate(generator, registry)


@pytest.mark.parametrize("status", ["incomplete", "in_progress", "failed"])
def test_a_non_completed_response_is_invalid(status: str) -> None:
    client = RecordingClient(completed(ORDERS_PAYLOAD, status=status))
    generator, registry, _ = build(client=client)

    with pytest.raises(PlanningError, match="returned an invalid response"):
        generate(generator, registry)


def test_more_than_one_output_text_item_is_invalid() -> None:
    part = SimpleNamespace(type="output_text", text=json.dumps(ORDERS_PAYLOAD))
    doubled = SimpleNamespace(status="completed", output=[SimpleNamespace(content=[part, part])])
    generator, registry, _ = build(client=RecordingClient(doubled))

    with pytest.raises(PlanningError, match="returned an invalid response"):
        generate(generator, registry)


def test_a_structured_refusal_maps_to_the_refused_record() -> None:
    generator, registry, _ = build(client=RecordingClient(refusal()))

    with pytest.raises(PlanningError, match="refused the request") as caught:
        generate(generator, registry)

    record = caught.value.record
    assert record.code is PlanningErrorCode.GENERATOR_REFUSED
    assert "cannot help" not in str(caught.value)
    assert record.suggestion == "Revise the planning goal or use a rule generator."


# --- 7. Decoder byte limits --------------------------------------------------------- #
def test_an_oversized_raw_response_is_rejected_before_parsing() -> None:
    padded = candidates(
        step("filter", "select@2.0.0", {**SELECT_ATTRIBUTES, "operand_key": "t" * 200_000})
    )
    generator, registry, _ = build(client=RecordingClient(completed(padded)))

    with pytest.raises(PlanningError, match="returned an invalid response"):
        generate(generator, registry)


def test_an_oversized_attributes_json_is_rejected() -> None:
    payload = candidates(
        {
            "step_id": "filter",
            "operator_id": "select@2.0.0",
            "attributes_json": json.dumps({"operand_key": "t" * 40_000}),
            "depends_on": [],
            "label": None,
        }
    )
    generator, registry, _ = build(client=RecordingClient(completed(payload)))

    with pytest.raises(PlanningError, match="returned an invalid response"):
        generate(generator, registry)


@pytest.mark.parametrize("field", ["step_id", "operator_id"])
def test_an_oversized_identifier_is_rejected(field: str) -> None:
    entry = step("filter", "select@2.0.0", SELECT_ATTRIBUTES)
    entry[field] = "x" * 129
    generator, registry, _ = build(client=RecordingClient(completed(candidates(entry))))

    with pytest.raises(PlanningError, match="returned an invalid response"):
        generate(generator, registry)


def test_an_oversized_dependency_identifier_is_rejected() -> None:
    entry = step("filter", "select@2.0.0", SELECT_ATTRIBUTES, ["y" * 129])
    generator, registry, _ = build(client=RecordingClient(completed(candidates(entry))))

    with pytest.raises(PlanningError, match="returned an invalid response"):
        generate(generator, registry)


@pytest.mark.parametrize("where", ["candidate", "step"])
def test_an_oversized_label_is_rejected(where: str) -> None:
    long_label = "L" * 257
    if where == "candidate":
        payload = candidates(step("filter", "select@2.0.0", SELECT_ATTRIBUTES), label=long_label)
    else:
        payload = candidates(step("filter", "select@2.0.0", SELECT_ATTRIBUTES, label=long_label))
    generator, registry, _ = build(client=RecordingClient(completed(payload)))

    with pytest.raises(PlanningError, match="returned an invalid response"):
        generate(generator, registry)


def test_a_multibyte_identifier_is_measured_in_utf8_bytes() -> None:
    # 128 code points but 384 UTF-8 bytes: the bound is a byte bound.
    entry = step("f", "select@2.0.0", SELECT_ATTRIBUTES)
    entry["step_id"] = "中" * 128
    generator, registry, _ = build(client=RecordingClient(completed(candidates(entry))))

    with pytest.raises(PlanningError, match="returned an invalid response"):
        generate(generator, registry)


def test_an_oversized_planning_request_never_reaches_the_provider() -> None:
    generator, registry, client = build()
    request = orders_request(goal="g" * 200_000)

    with pytest.raises(PlanningError, match="exceeds the plan generator request limit"):
        generate(generator, registry, request=request)

    assert client.calls == []


# --- 8. Provider error mapping ------------------------------------------------------ #
class SDKError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


# Stands in for any provider-side detail that must not reach a planning record.
# Named and shaped so it is not itself credential-like: the repository scanner
# rejects both a key-shaped value and a secret-shaped identifier, and it is right
# to, even in a fixture.
PROVIDER_TEXT = "PROVIDER-DETAIL-MUST-NOT-LEAK"


@pytest.mark.parametrize(
    ("status", "code", "category", "retryable"),
    [
        (500, PlanningErrorCode.GENERATOR_UNAVAILABLE, ErrorCategory.FAILED, True),
        (503, PlanningErrorCode.GENERATOR_UNAVAILABLE, ErrorCategory.FAILED, True),
        (408, PlanningErrorCode.GENERATOR_UNAVAILABLE, ErrorCategory.FAILED, True),
        (409, PlanningErrorCode.GENERATOR_UNAVAILABLE, ErrorCategory.FAILED, True),
        (400, PlanningErrorCode.GENERATOR_REQUEST_REJECTED, ErrorCategory.RECOVERABLE, False),
        (401, PlanningErrorCode.GENERATOR_REQUEST_REJECTED, ErrorCategory.RECOVERABLE, False),
        (403, PlanningErrorCode.GENERATOR_REQUEST_REJECTED, ErrorCategory.RECOVERABLE, False),
        (404, PlanningErrorCode.GENERATOR_REQUEST_REJECTED, ErrorCategory.RECOVERABLE, False),
        (422, PlanningErrorCode.GENERATOR_REQUEST_REJECTED, ErrorCategory.RECOVERABLE, False),
    ],
)
def test_http_status_maps_without_leaking_text(
    status: int, code: PlanningErrorCode, category: ErrorCategory, retryable: bool
) -> None:
    client = RecordingClient(error=SDKError(PROVIDER_TEXT, status_code=status))
    generator, registry, _ = build(client=client)

    with pytest.raises(PlanningError) as caught:
        generate(generator, registry)

    record = caught.value.record
    assert record.code is code
    assert record.category is category
    assert record.retryable is retryable
    assert record.stage is PlanningStage.GENERATION
    assert PROVIDER_TEXT not in str(caught.value)
    assert PROVIDER_TEXT not in str(record)


def test_an_unexpected_client_failure_is_a_generic_generation_failure() -> None:
    client = RecordingClient(error=RuntimeError(PROVIDER_TEXT))
    generator, registry, _ = build(client=client)

    with pytest.raises(PlanningError, match="plan generation failed") as caught:
        generate(generator, registry)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_FAILED
    assert PROVIDER_TEXT not in str(caught.value)


def test_the_generator_never_retries_a_failed_call() -> None:
    client = RecordingClient(error=SDKError(PROVIDER_TEXT, status_code=500))
    generator, registry, _ = build(client=client)

    with pytest.raises(PlanningError):
        generate(generator, registry)

    assert len(client.create_calls) == 1


def test_a_missing_optional_sdk_is_reported_without_a_client(monkeypatch: Any) -> None:
    import builtins

    real_import = builtins.__import__

    def refuse(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "openai":
            # A real absent-module failure carries `name`, which is what separates
            # "the extra is not installed" from any other import-time problem.
            raise ModuleNotFoundError("No module named 'openai'", name="openai")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    generator, registry, _ = build(client=NO_CLIENT)

    with pytest.raises(PlanningError, match="OpenAI plan generator is unavailable") as caught:
        generate(generator, registry)

    record = caught.value.record
    assert record.code is PlanningErrorCode.GENERATOR_DEPENDENCY_MISSING
    assert record.suggestion == "Install blue-data-ops[openai]."


# --- 9. Constructor validation ------------------------------------------------------ #
@pytest.mark.parametrize(
    "overrides",
    [
        {"allowed_operator_ids": ()},
        {"allowed_operator_ids": "select@2.0.0"},
        {"allowed_operator_ids": ("select@1.0.0",)},
        {"allowed_operator_ids": ("select@2.0.0", "select@2.0.0")},
        {"max_candidates": 2},
        {"max_candidates": True},
        {"timeout_seconds": 0},
        {"timeout_seconds": 301},
        {"timeout_seconds": True},
        {"max_output_tokens": 255},
        {"max_output_tokens": 16_385},
        {"send_data_context": 1},
    ],
)
def test_the_constructor_rejects_out_of_contract_configuration(overrides: dict[str, Any]) -> None:
    options: dict[str, Any] = {"allowed_operator_ids": ALLOWED, "client": RecordingClient()}
    options.update(overrides)

    with pytest.raises(PlanningError) as caught:
        OpenAIPlanGenerator(MODEL, registry=versioned_registry(), **options)

    assert caught.value.record.code is PlanningErrorCode.INVALID_REQUEST


@pytest.mark.parametrize("model", ["", "   ", cast(str, None), cast(str, 7)])
def test_the_constructor_requires_an_explicit_model(model: str) -> None:
    with pytest.raises(PlanningError, match="model must be a nonempty string"):
        OpenAIPlanGenerator(
            model,
            registry=versioned_registry(),
            allowed_operator_ids=ALLOWED,
            client=RecordingClient(),
        )


def test_the_constructor_requires_a_registry() -> None:
    with pytest.raises(PlanningError, match="requires an operator registry"):
        OpenAIPlanGenerator(
            MODEL,
            registry=cast(Any, object()),
            allowed_operator_ids=ALLOWED,
            client=RecordingClient(),
        )


# --- 10. The optional dependency stays optional ------------------------------------- #
def test_importing_the_package_does_not_import_the_sdk() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import blue_data_ops.plan; print('openai' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "False"


# --- 11. The official SDK, credential-free, through a local transport --------------- #
# Skipped one test at a time where the optional extra is absent, never module-wide: the
# 87 double-based tests above must still run without the SDK, because one of the things
# they prove is that it stays optional. This section is the only place the real client's
# serialization is checked, and it runs in the scratch gate environment.
httpx: Any = None
openai: Any = None
_sdk_present = False
try:  # pragma: no cover - environment dependent
    import httpx  # type: ignore[no-redef]
    import openai  # type: ignore[no-redef]

    _sdk_present = True
except ImportError:  # pragma: no cover - environment dependent
    pass

requires_sdk = pytest.mark.skipif(
    not _sdk_present, reason="optional blue-data-ops[openai] extra is not installed"
)


def official_client(handler: Any) -> Any:
    """A real OpenAI client whose transport never leaves the process."""

    # Short on purpose: the SDK only needs a non-empty value, and anything longer
    # trips the repository secret scanner's api_key pattern. No credential is read.
    return openai.OpenAI(
        api_key="unused",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@requires_sdk
def test_the_official_client_serializes_the_agreed_request() -> None:
    seen: list[Any] = []

    def handler(request: Any) -> Any:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "resp_1",
                "object": "response",
                "created_at": 0,
                "model": MODEL,
                "status": "completed",
                "output": [
                    {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(ORDERS_PAYLOAD),
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
        )

    generator, registry, _ = build(client=official_client(handler))

    drafts = generate(generator, registry)

    assert len(seen) == 1, "exactly one provider request"
    body = json.loads(seen[0].content)
    assert body["model"] == MODEL
    assert body["store"] is False
    assert body["stream"] is False
    assert body["background"] is False
    assert body["instructions"] == PLANNER_INSTRUCTIONS
    assert body["text"] == {"format": response_format()}
    assert "tools" not in body and "previous_response_id" not in body
    assert [item.operator_id for item in drafts[0].steps] == list(ALLOWED)


@requires_sdk
def test_the_official_client_does_not_retry_a_server_error() -> None:
    attempts: list[int] = []

    def handler(request: Any) -> Any:
        attempts.append(1)
        return httpx.Response(500, json={"error": {"message": PROVIDER_TEXT}})

    generator, registry, _ = build(client=official_client(handler))

    with pytest.raises(PlanningError) as caught:
        generate(generator, registry)

    assert attempts == [1], "SDK retries are disabled for this call"
    assert caught.value.record.code is PlanningErrorCode.GENERATOR_UNAVAILABLE
    assert caught.value.record.retryable is True
    assert PROVIDER_TEXT not in str(caught.value)


@requires_sdk
@pytest.mark.parametrize(
    ("status", "code"),
    [
        (429, PlanningErrorCode.GENERATOR_RATE_LIMITED),
        (400, PlanningErrorCode.GENERATOR_REQUEST_REJECTED),
        (401, PlanningErrorCode.GENERATOR_REQUEST_REJECTED),
        (503, PlanningErrorCode.GENERATOR_UNAVAILABLE),
    ],
)
def test_official_sdk_exception_classes_map_as_documented(
    status: int, code: PlanningErrorCode
) -> None:
    def handler(request: Any) -> Any:
        return httpx.Response(status, json={"error": {"message": PROVIDER_TEXT}})

    generator, registry, _ = build(client=official_client(handler))

    with pytest.raises(PlanningError) as caught:
        generate(generator, registry)

    assert caught.value.record.code is code
    assert PROVIDER_TEXT not in str(caught.value)


@requires_sdk
def test_a_structured_refusal_from_the_official_client_is_mapped() -> None:
    def handler(request: Any) -> Any:
        return httpx.Response(
            200,
            json={
                "id": "resp_2",
                "object": "response",
                "created_at": 0,
                "model": MODEL,
                "status": "completed",
                "output": [
                    {
                        "id": "msg_2",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "refusal", "refusal": PROVIDER_TEXT}],
                    }
                ],
            },
        )

    generator, registry, _ = build(client=official_client(handler))

    with pytest.raises(PlanningError, match="refused the request") as caught:
        generate(generator, registry)

    assert caught.value.record.code is PlanningErrorCode.GENERATOR_REFUSED
    assert PROVIDER_TEXT not in str(caught.value)


# --- 12. Boundaries asserted from the design text ----------------------------------- #
# Each of these is written from the design text rather than from the implementation, so
# it asserts what the contract requires instead of confirming what the code happens to do.


def test_a_fine_tuned_model_is_rejected() -> None:
    """The fine-tuned exclusion holds while the schema uses minItems and maxItems."""

    with pytest.raises(PlanningError, match="does not support fine-tuned models") as caught:
        OpenAIPlanGenerator(
            "ft:gpt-4o:acme:planner:1",
            registry=versioned_registry(),
            allowed_operator_ids=ALLOWED,
            client=RecordingClient(),
        )

    assert caught.value.record.code is PlanningErrorCode.INVALID_REQUEST


def test_an_nl2sql_candidate_without_a_snapshot_is_rejected() -> None:
    """An nl2sql candidate requires a data-context snapshot and send_data_context=True."""

    generator, registry, client = build(send_data_context=False)

    with pytest.raises(PlanningError, match="nl2sql without a disclosed data context") as caught:
        generate(generator, registry, data_context=None)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_RESULT_INVALID
    assert caught.value.record.category is ErrorCategory.RECOVERABLE
    # The provider was still called: this is an admission rule on the response, not a
    # pre-provider gate, and saying otherwise would overstate the boundary.
    assert len(client.create_calls) == 1


def test_a_non_nl2sql_candidate_still_plans_without_a_snapshot() -> None:
    generator, registry, _ = build(client=RecordingClient(completed(SCOPELESS_PAYLOAD)))

    drafts = generate(generator, registry, data_context=None)

    assert [item.operator_id for item in drafts[0].steps] == ["select@2.0.0", "avg@2.0.0"]


def test_a_malformed_declaration_fails_before_any_provider_traffic() -> None:
    """A malformed declaration fails before optional import, client construction, or
    provider traffic."""

    registry = versioned_registry()
    resolved = registry.resolve("select@2.0.0")
    object.__setattr__(resolved, "attributes", ["not", "a", "declaration"])
    generator, _, client = build(registry=registry)

    with pytest.raises(PlanningError, match="requires supported built-in") as caught:
        generator.generate(orders_request(), discovery_of(registry), cast(Any, FakeSnapshot()))

    assert caught.value.record.code is PlanningErrorCode.DISCOVERY_RESULT_INVALID
    assert client.calls == [], "no provider request may precede this failure"


def test_an_unrelated_import_failure_is_not_a_missing_dependency(monkeypatch: Any) -> None:
    """The dependency code is reserved for an absent optional import; an unrelated
    import-time defect uses the generic generation failure."""

    import builtins

    real_import = builtins.__import__

    def broken(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "openai":
            raise RuntimeError("unrelated import-time defect")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken)
    generator, registry, _ = build(client=NO_CLIENT)

    with pytest.raises(PlanningError, match="plan generation failed") as caught:
        generate(generator, registry)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_FAILED
    assert "unrelated import-time defect" not in str(caught.value)


# --- 13. The dependency code means the package is absent, nothing else -------------- #
# Each import failure below is a separate case. Narrowing `except Exception` to
# `except ImportError` and covering only the RuntimeError would leave a plain
# ImportError still reported as a missing SDK, so both are asserted here.


def _with_failing_import(monkeypatch: Any, error: BaseException) -> None:
    import builtins

    real_import = builtins.__import__

    def failing(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "openai":
            raise error
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing)


def test_an_absent_top_level_openai_is_a_missing_dependency(monkeypatch: Any) -> None:
    _with_failing_import(
        monkeypatch, ModuleNotFoundError("No module named 'openai'", name="openai")
    )
    generator, registry, _ = build(client=NO_CLIENT)

    with pytest.raises(PlanningError, match="OpenAI plan generator is unavailable") as caught:
        generate(generator, registry)

    assert caught.value.record.code is PlanningErrorCode.GENERATOR_DEPENDENCY_MISSING
    assert caught.value.record.suggestion == "Install blue-data-ops[openai]."


def test_a_plain_import_error_is_a_generic_generation_failure(monkeypatch: Any) -> None:
    _with_failing_import(monkeypatch, ImportError("cannot import name Foo from openai._compat"))
    generator, registry, _ = build(client=NO_CLIENT)

    with pytest.raises(PlanningError, match="plan generation failed") as caught:
        generate(generator, registry)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_FAILED
    assert "openai._compat" not in str(caught.value)


def test_a_missing_transitive_dependency_is_a_generic_failure(monkeypatch: Any) -> None:
    # The SDK is installed but one of its own dependencies is not. Reporting that as
    # "install blue-data-ops[openai]" would send the caller to fix the wrong thing.
    _with_failing_import(monkeypatch, ModuleNotFoundError("No module named 'httpx'", name="httpx"))
    generator, registry, _ = build(client=NO_CLIENT)

    with pytest.raises(PlanningError, match="plan generation failed") as caught:
        generate(generator, registry)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_FAILED


def test_an_unrelated_runtime_import_failure_is_a_generic_failure(monkeypatch: Any) -> None:
    _with_failing_import(monkeypatch, RuntimeError("unrelated import-time defect"))
    generator, registry, _ = build(client=NO_CLIENT)

    with pytest.raises(PlanningError, match="plan generation failed") as caught:
        generate(generator, registry)

    assert caught.value.record.code is PlanningErrorCode.GENERATION_FAILED
    assert "unrelated import-time defect" not in str(caught.value)


def test_an_injected_client_never_triggers_the_optional_import(monkeypatch: Any) -> None:
    attempted: list[str] = []
    import builtins

    real_import = builtins.__import__

    def recording(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "openai":
            attempted.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", recording)
    generator, registry, _ = build()

    generate(generator, registry)

    assert attempted == [], "a supplied client must not reach the optional import at all"
