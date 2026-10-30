"""Focused verification for the bounded planning data context.

The suite is organized by the properties the context contract requires, including that
entity and attribute records are read directly. Registry reads go through
`RegistryDouble`, which answers only the three allowed operations; the closing test
repeats the orders collection against a real blue-data SQLite registry.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from blue_data_ops.operators import versioned_registry
from blue_data_ops.operators.types import ErrorCategory
from blue_data_ops.plan import (
    DataContextSnapshot,
    DataPipeline,
    DataScope,
    DiscoveryQuery,
    PipelinePlanner,
    PlanDraft,
    PlanningError,
    PlanningErrorCode,
    PlanningRequest,
    PlanningStage,
    PlanStep,
    RegistryDataContextProvider,
    RulePlanGenerator,
)
from blue_data_ops.plan.context import DATA_CONTEXT_FORMAT
from tests.unit.plan._data_context_helpers import (
    ALLOWED_REGISTRY_METHODS,
    ORDERS_COLLECTION,
    ORDERS_DATABASE,
    ORDERS_DESCRIPTION,
    ORDERS_SOURCE,
    RegistryDouble,
    as_document,
    attribute_record,
    entity_record,
    load_fixture,
    opaque_double,
    opaque_scope,
    orders_double,
    orders_scope,
    provider,
)


def _collect_orders(**limits: int) -> DataContextSnapshot:
    return provider(orders_double(), **limits).collect(orders_scope())


def _canonical(document: dict[str, Any]) -> bytes:
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


# --- 1. Canonical fixtures ---------------------------------------------------------- #
def test_orders_fixture_is_the_collected_projection() -> None:
    assert as_document(_collect_orders()) == load_fixture("data_context_orders.json")


def test_opaque_fixture_is_the_collected_whole_collection_projection() -> None:
    collected = provider(opaque_double()).collect(opaque_scope())

    assert as_document(collected) == load_fixture("data_context_opaque.json")


@pytest.mark.parametrize("name", ["data_context_orders.json", "data_context_opaque.json"])
def test_fixtures_are_finite_canonical_json_within_their_declared_bounds(name: str) -> None:
    document = load_fixture(name)
    serialized = _canonical(document)

    assert document["format"] == DATA_CONTEXT_FORMAT
    assert len(serialized) <= document["limits"]["max_serialized_bytes"]
    assert json.loads(serialized.decode("utf-8")) == document
    # allow_nan=False above already rejects a non-finite float; no fixture carries one.
    assert document["provenance"]["raw_rows"] == 0
    assert document["limits"]["max_raw_rows"] == 0


# --- 2. Determinism ----------------------------------------------------------------- #
def test_collection_is_deterministic_across_registry_insertion_order() -> None:
    forward = provider(opaque_double()).collect(opaque_scope())
    reversed_order = provider(opaque_double(reverse=True)).collect(opaque_scope())

    assert as_document(forward) == as_document(reversed_order)
    assert forward.resolved_entities == reversed_order.resolved_entities == ("t_017", "t_042")


# --- 3. Allowed registry reads ------------------------------------------------------ #
def test_provider_reads_only_the_three_allowed_registry_methods() -> None:
    double = orders_double()

    provider(double).collect(orders_scope())

    assert set(double.called_methods) <= set(ALLOWED_REGISTRY_METHODS)
    assert double.called_methods == (
        "get_source_properties",
        "list_collection_entities",
        "list_entity_attributes",
    )


def test_reaching_any_other_registry_method_is_a_failure() -> None:
    # The negative control for the test above: the double itself refuses.
    with pytest.raises(AssertionError, match="disallowed registry method"):
        _ = orders_double().build_schema_for_nl


# --- 4. Descriptions, and everything the projection drops --------------------------- #
def test_only_declared_fields_survive_the_projection() -> None:
    document = as_document(_collect_orders())
    entity = document["schema"]["entities"][0]

    assert set(entity) == {"name", "description", "attributes"}
    assert entity["description"] == ORDERS_DESCRIPTION
    assert all(set(attribute) == {"name", "type"} for attribute in entity["attributes"])


@pytest.mark.parametrize(
    "leaked",
    [
        "created_by",
        "icon",
        "contents",
        "row_count",
        "sample_values",
        "sample-value-must-not-leak",
        "database_directory",
        "must-not-leak",
        "registry-operator@example.invalid",
        "relations",
    ],
)
def test_no_registry_metadata_connection_detail_or_row_reaches_the_snapshot(leaked: str) -> None:
    serialized = _canonical(as_document(_collect_orders())).decode("utf-8")

    assert leaked not in serialized


def test_an_empty_description_is_omitted_rather_than_serialized() -> None:
    double = orders_double()
    double.entities = [entity_record("orders", orders_scope(), "")]

    entity = as_document(provider(double).collect(orders_scope()))["schema"]["entities"][0]

    assert "description" not in entity


@pytest.mark.parametrize("description", [None, 7, {"text": "x"}, ["x"], True])
def test_a_non_string_description_is_omitted(description: Any) -> None:
    double = orders_double()
    double.entities = [entity_record("orders", orders_scope(), description=None)]
    cast("dict[str, Any]", double.entities[0])["description"] = description

    entity = as_document(provider(double).collect(orders_scope()))["schema"]["entities"][0]

    assert "description" not in entity


@pytest.mark.parametrize(
    ("record_override", "reason"),
    [
        ({"properties": {"info": {}}}, "absent type"),
        ({"properties": {"info": {"type": ""}}}, "empty type"),
        ({"properties": {"info": {"type": "   "}}}, "blank type"),
        ({"properties": {"info": {"type": 7}}}, "non-string type"),
        ({"properties": {"info": {"type": None}}}, "null type"),
        ({"properties": {"info": "TEXT"}}, "non-mapping info"),
        ({"properties": {}}, "absent info"),
        ({"properties": "TEXT"}, "non-mapping properties"),
        ({}, "absent properties"),
    ],
)
def test_an_unknown_declared_type_becomes_null_without_substitution(
    record_override: dict[str, Any],
    reason: str,
) -> None:
    # build_schema_for_nl() would answer "TEXT" or str(info) here. The context answers null.
    del reason
    double = orders_double()
    record = attribute_record("total", "REAL")
    record.pop("properties", None)
    record.update(record_override)
    double.attributes = {"orders": [record]}

    entity = as_document(provider(double).collect(orders_scope()))["schema"]["entities"][0]

    assert entity["attributes"] == [{"name": "total", "type": None}]


def test_a_known_string_type_is_copied_verbatim() -> None:
    document = as_document(_collect_orders())

    assert document["schema"]["entities"][0]["attributes"] == [
        {"name": "currency", "type": "TEXT"},
        {"name": "customer_id", "type": "INTEGER"},
        {"name": "order_id", "type": "INTEGER"},
        {"name": "total", "type": "REAL"},
    ]


# --- 5. Relations are not projected ------------------------------------------------- #
def test_the_payload_has_no_relation_shape_at_all() -> None:
    document = as_document(_collect_orders())

    assert set(document) == {
        "format",
        "scope",
        "resolved_entities",
        "protocol",
        "schema",
        "provenance",
        "limits",
    }
    assert set(document["schema"]) == {"entities"}
    assert "max_relations" not in document["limits"]


def test_provenance_names_the_direct_read_path() -> None:
    assert as_document(_collect_orders())["provenance"] == {
        "provider": "blue-data-registry",
        "source_properties_method": "get_source_properties",
        "entity_method": "list_collection_entities",
        "attribute_method": "list_entity_attributes",
        "raw_rows": 0,
    }


# --- 6. Every bound fails closed ---------------------------------------------------- #
def test_a_missing_projected_entity_fails_rather_than_returning_partial_context() -> None:
    with pytest.raises(PlanningError, match="not registered in the collection") as caught:
        provider(orders_double()).collect(orders_scope(("customers", "orders")))

    assert caught.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.DATA_CONTEXT_UNAVAILABLE,
        PlanningStage.DATA_CONTEXT,
        "requested entity is not registered in the collection",
        False,
        "Check the data scope against the registered collection.",
    )


def test_a_whole_collection_larger_than_the_entity_limit_fails() -> None:
    with pytest.raises(PlanningError, match="entity limit") as caught:
        provider(opaque_double(), max_entities=1).collect(opaque_scope())

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_LIMIT_EXCEEDED
    assert caught.value.record.stage is PlanningStage.DATA_CONTEXT
    assert caught.value.record.category is ErrorCategory.RECOVERABLE


def test_an_explicit_projection_larger_than_the_entity_limit_fails() -> None:
    with pytest.raises(PlanningError, match="entity limit"):
        provider(opaque_double(), max_entities=1).collect(opaque_scope(("t_017", "t_042")))


@pytest.mark.parametrize(
    ("limits", "match"),
    [
        ({"max_attributes_per_entity": 3}, "per-entity attribute limit"),
        ({"max_total_attributes": 3}, "total attribute limit"),
        ({"max_description_chars": 8}, "description limit"),
        ({"max_serialized_bytes": 64}, "serialized byte limit"),
    ],
)
def test_each_numeric_bound_fails_closed(limits: dict[str, int], match: str) -> None:
    with pytest.raises(PlanningError, match=match) as caught:
        _collect_orders(**limits)

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_LIMIT_EXCEEDED


@pytest.mark.parametrize("field", ["name", "type"])
def test_an_oversized_attribute_name_or_type_fails(field: str) -> None:
    double = orders_double()
    oversized = "x" * 129
    double.attributes = {
        "orders": [
            attribute_record(
                oversized if field == "name" else "total",
                oversized if field == "type" else "REAL",
            )
        ]
    }

    with pytest.raises(PlanningError, match=f"{field} limit") as caught:
        provider(double).collect(orders_scope())

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_LIMIT_EXCEEDED


def test_an_oversized_protocol_fails() -> None:
    double = orders_double()
    double.source_properties = {"connection": {"protocol": "p" * 129}}

    with pytest.raises(PlanningError, match="protocol limit"):
        provider(double).collect(orders_scope())


@pytest.mark.parametrize(
    "limits",
    [
        {"max_entities": 0},
        {"max_attributes_per_entity": -1},
        {"max_total_attributes": cast(int, True)},
        {"max_description_chars": cast(int, 1.0)},
        {"max_serialized_bytes": cast(int, "512")},
    ],
)
def test_the_provider_rejects_a_malformed_bound(limits: dict[str, int]) -> None:
    with pytest.raises(PlanningError, match="positive integers") as caught:
        provider(orders_double(), **limits)

    assert caught.value.record.code is PlanningErrorCode.INVALID_REQUEST


def test_an_unknown_protocol_is_null_rather_than_invented() -> None:
    double = orders_double()
    double.source_properties = {"connection": {}}

    assert as_document(provider(double).collect(orders_scope()))["protocol"] is None


# --- 7. Malformed input and hostile failures do not leak ---------------------------- #
class _HostileRegistry(RegistryDouble):
    def list_collection_entities(self, source: str, database: str, collection: str) -> Any:
        raise RuntimeError("registry-payload-should-not-leak")


def test_a_registry_exception_becomes_a_stable_record_without_its_text() -> None:
    with pytest.raises(PlanningError, match="data context collection failed") as caught:
        provider(_HostileRegistry()).collect(orders_scope())

    assert "registry-payload" not in str(caught.value)
    assert caught.value.record == (
        ErrorCategory.FAILED,
        PlanningErrorCode.DATA_CONTEXT_FAILED,
        PlanningStage.DATA_CONTEXT,
        "data context collection failed",
        False,
        "Check the data registry and the context provider.",
    )


@pytest.mark.parametrize(
    ("entities", "match"),
    [
        ("not-a-list", "malformed entity listing"),
        (["not-a-record"], "malformed entity record"),
        ([{"type": "entity"}], "malformed entity record"),
        ([{"name": "  "}], "malformed entity record"),
        ([{"name": 7}], "malformed entity record"),
    ],
)
def test_a_malformed_entity_listing_is_rejected(entities: Any, match: str) -> None:
    double = orders_double()
    double.entities = entities

    with pytest.raises(PlanningError, match=match) as caught:
        provider(double).collect(orders_scope(()))

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_RESULT_INVALID


def test_duplicate_registry_records_are_rejected() -> None:
    double = orders_double()
    scope = orders_scope()
    double.entities = [
        entity_record("orders", scope, "one"),
        entity_record("orders", scope, "two"),
    ]

    with pytest.raises(PlanningError, match="duplicate entity records"):
        provider(double).collect(scope)


def test_duplicate_attribute_records_are_rejected() -> None:
    double = orders_double()
    double.attributes = {"orders": [attribute_record("total", "REAL")] * 2}

    with pytest.raises(PlanningError, match="duplicate attribute records"):
        provider(double).collect(orders_scope())


@pytest.mark.parametrize(
    "attributes",
    ["not-a-list", ["not-a-record"], [{"name": ""}], [{"nope": "total"}]],
)
def test_a_malformed_attribute_listing_is_rejected(attributes: Any) -> None:
    double = orders_double()
    double.attributes = {"orders": attributes}

    with pytest.raises(PlanningError, match="malformed attribute") as caught:
        provider(double).collect(orders_scope())

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_RESULT_INVALID


# --- 8. Scope validation ------------------------------------------------------------ #
class _ExplodingStr(str):
    def strip(self, chars: str | None = None) -> str:
        del chars
        raise RuntimeError("scope-payload-should-not-leak")


@pytest.mark.parametrize(
    "construct",
    [
        lambda: DataScope("", "d", "c"),
        lambda: DataScope("s", "  ", "c"),
        lambda: DataScope("s", "d", cast(str, 7)),
        lambda: DataScope("s", "d", "c", cast("tuple[str, ...]", ["a"])),
        lambda: DataScope("s", "d", "c", ("a", "a")),
        lambda: DataScope("s", "d", "c", (" ",)),
        lambda: DataScope("s", "d", "c", cast("tuple[str, ...]", (7,))),
        lambda: DataScope(cast(str, _ExplodingStr("s")), "d", "c"),
    ],
)
def test_the_scope_rejects_malformed_and_hostile_input(construct: Any) -> None:
    with pytest.raises(PlanningError) as caught:
        construct()

    assert "scope-payload" not in str(caught.value)
    assert caught.value.record.code is PlanningErrorCode.INVALID_REQUEST
    assert caught.value.record.stage is PlanningStage.VALIDATION


def test_the_scope_canonicalizes_a_nonempty_projection() -> None:
    assert DataScope("s", "d", "c", ("orders", "customers")).entities == ("customers", "orders")
    assert DataScope("s", "d", "c").entities == ()


# --- Requested versus resolved entities --------------------------------------------- #
def test_an_empty_request_keeps_scope_entities_empty_and_resolves_the_collection() -> None:
    collected = provider(opaque_double()).collect(opaque_scope())
    document = as_document(collected)

    assert collected.scope.entities == ()
    assert document["scope"]["entities"] == []
    assert collected.resolved_entities == ("t_017", "t_042")
    assert document["resolved_entities"] == ["t_017", "t_042"]
    assert [entity["name"] for entity in document["schema"]["entities"]] == ["t_017", "t_042"]


def test_an_explicit_projection_equals_resolved_entities_and_the_schema_names() -> None:
    collected = provider(opaque_double()).collect(opaque_scope(("t_042",)))
    document = as_document(collected)

    assert collected.scope.entities == ("t_042",)
    assert collected.resolved_entities == ("t_042",)
    assert [entity["name"] for entity in document["schema"]["entities"]] == ["t_042"]


def test_the_opaque_fixture_carries_the_distinction_names_alone_cannot() -> None:
    # Entity and attribute identifiers are opaque; only the bounded description says
    # which table holds orders. This is what descriptions are in the projection for.
    entities = load_fixture("data_context_opaque.json")["schema"]["entities"]
    orders_like = [entity for entity in entities if "purchase orders" in entity["description"]]

    assert [entity["name"] for entity in orders_like] == ["t_017"]
    assert all("order" not in entity["name"] for entity in entities)


# --- Serialization contract --------------------------------------------------------- #
def test_to_dict_returns_fresh_nested_containers_every_call() -> None:
    collected = _collect_orders()
    first = as_document(collected)
    second = as_document(collected)

    assert first == second
    assert first is not second
    assert first["scope"] is not second["scope"]
    assert first["schema"] is not second["schema"]
    assert first["schema"]["entities"] is not second["schema"]["entities"]
    assert (
        first["schema"]["entities"][0]["attributes"]
        is not (second["schema"]["entities"][0]["attributes"])
    )

    first["schema"]["entities"].clear()
    first["scope"]["entities"].append("injected")
    assert as_document(collected) == second


def test_to_dict_builds_scope_from_the_snapshot_scope() -> None:
    collected = _collect_orders()

    assert as_document(collected)["scope"] == {
        "source": ORDERS_SOURCE,
        "database": ORDERS_DATABASE,
        "collection": ORDERS_COLLECTION,
        "entities": ["orders"],
    }
    assert "scope" not in collected.payload
    assert "resolved_entities" not in collected.payload
    assert "format" not in collected.payload


def test_the_stored_payload_is_frozen() -> None:
    payload = _collect_orders().payload

    with pytest.raises(TypeError):
        cast("dict[str, Any]", payload)["protocol"] = "postgres"
    with pytest.raises(TypeError):
        cast("dict[str, Any]", payload["schema"])["entities"] = []


def test_the_snapshot_rejects_a_payload_carrying_scope_or_format() -> None:
    collected = _collect_orders()
    payload = {key: value for key, value in as_document(collected).items() if key != "format"}

    with pytest.raises(PlanningError, match="payload is malformed"):
        DataContextSnapshot(
            scope=collected.scope,
            resolved_entities=collected.resolved_entities,
            payload=payload,
        )


def test_the_snapshot_rejects_a_declared_raw_row_budget() -> None:
    collected = _collect_orders()
    document = as_document(collected)
    payload = {key: document[key] for key in ("protocol", "schema", "provenance", "limits")}
    cast("dict[str, Any]", payload["limits"])["max_raw_rows"] = 1

    with pytest.raises(PlanningError, match="raw-row budget"):
        DataContextSnapshot(
            scope=collected.scope,
            resolved_entities=collected.resolved_entities,
            payload=payload,
        )


# --- Planner integration ------------------------------------------------------------ #
NL2SQL_QUESTION = "Average order total above 100"


def _orders_request(
    scope: DataScope | None = None,
    *,
    nl2sql_attributes: dict[str, Any] | None = None,
) -> PlanningRequest:
    address = {
        "source": ORDERS_SOURCE,
        "protocol": "sqlite",
        "database": ORDERS_DATABASE,
        "collection": ORDERS_COLLECTION,
        "question": NL2SQL_QUESTION,
    }
    address.update(nl2sql_attributes or {})
    return PlanningRequest(
        goal="Find the average total above 100",
        data_scope=orders_scope() if scope is None else scope,
        discovery_queries=(
            DiscoveryQuery("nl2sql"),
            DiscoveryQuery("select"),
            DiscoveryQuery("avg"),
        ),
        operator_attributes={
            "nl2sql": address,
            "select": {"operand_key": "total", "operand": ">", "operand_val": 100},
            "avg": {"avg_key": "total", "output_key": "average_total"},
        },
        allowed_operator_ids=("nl2sql@2.0.0", "select@2.0.0", "avg@2.0.0"),
        input_label="orders",
        output_label="answer",
    )


def _orders_draft(request: PlanningRequest) -> PlanDraft:
    return PlanDraft(
        (
            PlanStep("query", "nl2sql@2.0.0", dict(request.operator_attributes["nl2sql"])),
            PlanStep(
                "filter",
                "select@2.0.0",
                dict(request.operator_attributes["select"]),
                depends_on=("query",),
            ),
            PlanStep(
                "average",
                "avg@2.0.0",
                dict(request.operator_attributes["avg"]),
                depends_on=("filter",),
            ),
        ),
        label="orders-context-plan",
    )


class _ContextRule:
    """A deterministic rule that plans only fields the snapshot actually reports."""

    def __init__(self) -> None:
        self.seen: list[DataContextSnapshot | None] = []

    def __call__(
        self,
        request: PlanningRequest,
        discovery: Any,
        data_context: DataContextSnapshot | None,
    ) -> PlanDraft | None:
        del discovery
        self.seen.append(data_context)
        if data_context is None:
            return None
        entity = cast("dict[str, Any]", as_document(data_context)["schema"]["entities"][0])
        available = {attribute["name"] for attribute in entity["attributes"]}
        if entity["name"] != "orders" or not {"total", "currency"}.issubset(available):
            return None
        return _orders_draft(request)


class _FixedGenerator:
    """Stands in for a provider-backed generator: same inputs, same returned draft."""

    def __init__(self) -> None:
        self.seen: list[DataContextSnapshot | None] = []

    def generate(
        self,
        request: PlanningRequest,
        discovery: Any,
        data_context: DataContextSnapshot | None,
    ) -> Sequence[PlanDraft]:
        del discovery
        self.seen.append(data_context)
        return (_orders_draft(request),)


def _orders_planner(
    generator: Any,
    double: RegistryDouble | None = None,
) -> tuple[PipelinePlanner, RegistryDataContextProvider]:
    context_provider = provider(orders_double() if double is None else double)
    return (
        PipelinePlanner(versioned_registry(), generator, None, context_provider),
        context_provider,
    )


def test_the_generator_and_result_snapshots_are_equal_but_not_the_same_object() -> None:
    """The snapshot boundary: equal canonical content, separate objects."""

    generator = _FixedGenerator()
    planner, _ = _orders_planner(generator)

    planning = planner.plan(_orders_request())

    assert len(generator.seen) == 1
    handed_out = generator.seen[0]
    retained = planning.data_context
    assert handed_out is not None and retained is not None
    assert type(handed_out) is DataContextSnapshot
    assert type(retained) is DataContextSnapshot

    assert handed_out is not retained
    assert handed_out.scope is not retained.scope
    assert handed_out.payload is not retained.payload
    assert as_document(handed_out) == as_document(retained)
    assert _canonical(as_document(handed_out)) == _canonical(as_document(retained))

    # Package-built, so the documented serializer is the one a caller gets back.
    assert type(retained).to_dict is DataContextSnapshot.to_dict
    assert "to_dict" not in vars(retained)


def test_a_request_without_a_scope_never_calls_the_provider() -> None:
    double = orders_double()
    rule = _ContextRule()
    planner = PipelinePlanner(
        versioned_registry(),
        RulePlanGenerator((rule,)),
        None,
        provider(double),
    )

    with pytest.raises(PlanningError, match="no candidates"):
        planner.plan(
            PlanningRequest(
                goal="Find the average total above 100",
                discovery_queries=(DiscoveryQuery("select"),),
                allowed_operator_ids=("select@2.0.0",),
            )
        )

    assert double.calls == []
    assert rule.seen == [None]


def test_a_scope_without_a_provider_fails_before_generation() -> None:
    generator = _FixedGenerator()
    planner = PipelinePlanner(versioned_registry(), generator)

    with pytest.raises(PlanningError, match="requires a data context provider") as caught:
        planner.plan(_orders_request())

    assert generator.seen == []
    assert caught.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.DATA_CONTEXT_REQUIRED,
        PlanningStage.DATA_CONTEXT,
        "planning a data scope requires a data context provider",
        False,
        "Pass a data_context_provider or plan without a DataScope.",
    )


def _topology(pipeline: DataPipeline) -> list[tuple[Any, ...]]:
    """Compare graphs by label, type, edges, and operator binding, not by node UUID."""

    document = pipeline.to_dict()
    nodes = cast("dict[str, dict[str, Any]]", document["nodes"])
    label_of = {node_id: node["label"] for node_id, node in nodes.items()}
    operators = cast("dict[str, dict[str, Any]]", document["entities"].get("OPERATOR", {}))
    return sorted(
        (
            node["label"],
            node["type"],
            tuple(sorted(label_of[previous] for previous in node["prev"])),
            operators.get(node.get("OPERATOR", ""), {}).get("operator_id"),
            operators.get(node.get("OPERATOR", ""), {}).get("attributes"),
        )
        for node in nodes.values()
    )


def test_rule_and_fixed_generator_doubles_produce_the_same_orders_graph() -> None:
    rule_planner, _ = _orders_planner(RulePlanGenerator((_ContextRule(),)))
    fixed_planner, _ = _orders_planner(_FixedGenerator())
    request = _orders_request()

    from_rule = rule_planner.plan(request)
    from_fixed = fixed_planner.plan(request)

    assert _topology(from_rule.pipeline) == _topology(from_fixed.pipeline)
    assert from_rule.selected == from_fixed.selected
    assert from_rule.preflight.operator_ids == ("nl2sql@2.0.0", "select@2.0.0", "avg@2.0.0")
    assert from_fixed.preflight.operator_ids == from_rule.preflight.operator_ids
    assert [entry[0] for entry in _topology(from_rule.pipeline)] == [
        "answer",
        "average",
        "filter",
        "orders",
        "query",
    ]


def test_the_legacy_rule_still_plans_and_executes_without_a_data_context() -> None:
    # Rule behavior under the shared signature: no scope, no provider, same result.
    planner = PipelinePlanner(versioned_registry(), RulePlanGenerator())

    result = planner.run(
        PlanningRequest(
            goal="Find the average total above 100",
            discovery_queries=(
                DiscoveryQuery("filter", ("flow-transform", "accepts-data", "capability-filter")),
                DiscoveryQuery("average", ("flow-aggregate", "accepts-data", "capability-average")),
            ),
            operator_attributes={
                "select": {"operand_key": "total", "operand": ">", "operand_val": 100},
                "avg": {"avg_key": "total", "output_key": "average_total"},
            },
            allowed_operator_ids=("select@2.0.0", "avg@2.0.0"),
        ),
        [[{"total": 80.0}, {"total": 125.0}, {"total": 210.0}]],
    )

    assert result.planning.data_context is None
    assert result.execution.output_data == [[{"average_total": 167.5}]]


# --- The planner accepts only an exact, matching snapshot --------------------------- #
class _SnapshotSubclass(DataContextSnapshot):
    pass


class _SnapshotLookalike:
    def __init__(self, snapshot: DataContextSnapshot) -> None:
        self.scope = snapshot.scope
        self.resolved_entities = snapshot.resolved_entities
        self.payload = snapshot.payload

    def to_dict(self) -> dict[str, Any]:
        return {"format": DATA_CONTEXT_FORMAT}


def _payload(snapshot: DataContextSnapshot) -> dict[str, Any]:
    document = as_document(snapshot)
    return {key: document[key] for key in ("protocol", "schema", "provenance", "limits")}


class _ScriptedProvider:
    def __init__(self, snapshot: Any) -> None:
        self.snapshot = snapshot

    def collect(self, scope: DataScope) -> DataContextSnapshot:
        del scope
        return cast(DataContextSnapshot, self.snapshot)


def _planner_with(snapshot: Any) -> PipelinePlanner:
    return PipelinePlanner(
        versioned_registry(),
        _FixedGenerator(),
        None,
        cast(Any, _ScriptedProvider(snapshot)),
    )


def test_the_planner_rejects_a_snapshot_subclass_or_lookalike() -> None:
    collected = _collect_orders()
    subclass = _SnapshotSubclass(
        scope=collected.scope,
        resolved_entities=collected.resolved_entities,
        payload=_payload(collected),
    )

    for impostor in (subclass, _SnapshotLookalike(collected)):
        with pytest.raises(PlanningError, match="malformed snapshot") as caught:
            _planner_with(impostor).plan(_orders_request())
        assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_RESULT_INVALID
        assert caught.value.record.stage is PlanningStage.DATA_CONTEXT


def test_the_planner_rejects_a_snapshot_collected_for_a_different_scope() -> None:
    other = provider(opaque_double()).collect(opaque_scope())

    with pytest.raises(PlanningError, match="scope does not match") as caught:
        _planner_with(other).plan(_orders_request())

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_SCOPE_MISMATCH
    assert caught.value.record.stage is PlanningStage.DATA_CONTEXT


def test_a_partial_projection_cannot_exist_in_a_snapshot() -> None:
    # The planner needs no separate partial-projection branch: the type refuses to hold
    # one, so a narrower resolution can only arrive as a differently scoped snapshot.
    collected = _collect_orders()

    with pytest.raises(PlanningError, match="must resolve the requested entity projection"):
        DataContextSnapshot(
            scope=orders_scope(("customers", "orders")),
            resolved_entities=("orders",),
            payload=_payload(collected),
        )


def test_the_planner_rejects_a_snapshot_that_resolves_fewer_entities_than_requested() -> None:
    request = _orders_request(orders_scope(("customers", "orders")))
    narrower = provider(orders_double()).collect(orders_scope(("orders",)))

    with pytest.raises(PlanningError, match="scope does not match") as caught:
        _planner_with(narrower).plan(request)

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_SCOPE_MISMATCH


class _RaisingProvider:
    def collect(self, scope: DataScope) -> DataContextSnapshot:
        del scope
        raise RuntimeError("provider-payload-should-not-leak")


def test_an_unexpected_provider_failure_does_not_leak_its_text() -> None:
    planner = PipelinePlanner(
        versioned_registry(),
        _FixedGenerator(),
        None,
        cast(Any, _RaisingProvider()),
    )

    with pytest.raises(PlanningError, match="data context collection failed") as caught:
        planner.plan(_orders_request())

    assert "provider-payload" not in str(caught.value)
    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_FAILED
    assert caught.value.record.category is ErrorCategory.FAILED


def test_a_provider_failure_never_falls_back_to_empty_context() -> None:
    planner = PipelinePlanner(
        versioned_registry(),
        _FixedGenerator(),
        None,
        cast(Any, _RaisingProvider()),
    )

    with pytest.raises(PlanningError):
        planner.plan(_orders_request())


# --- Address consistency, which is not table authorization -------------------------- #
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", "other_source"),
        ("database", "other_database"),
        ("collection", "other_collection"),
    ],
)
def test_an_nl2sql_step_cannot_name_another_address(field: str, value: str) -> None:
    planner, _ = _orders_planner(_FixedGenerator())
    request = _orders_request(nl2sql_attributes={field: value})

    with pytest.raises(PlanningError, match="must address the request data scope") as caught:
        planner.plan(request)

    assert caught.value.record == (
        ErrorCategory.RECOVERABLE,
        PlanningErrorCode.PLAN_INVALID,
        PlanningStage.COMPILATION,
        "step 'query' must address the request data scope",
        False,
        "Use discovered supported pinned operators in a valid bounded plan.",
    )


@pytest.mark.parametrize("field", ["source", "database", "collection"])
def test_an_nl2sql_step_cannot_omit_or_mistype_its_address(field: str) -> None:
    planner, _ = _orders_planner(_FixedGenerator())
    request = _orders_request(nl2sql_attributes={field: cast(str, None)})

    with pytest.raises(PlanningError, match="must address the request data scope"):
        planner.plan(request)


def test_a_scopeless_request_cannot_compile_an_nl2sql_step() -> None:
    planner = PipelinePlanner(versioned_registry(), _FixedGenerator())
    request = PlanningRequest(
        goal="Find the average total above 100",
        discovery_queries=(
            DiscoveryQuery("nl2sql"),
            DiscoveryQuery("select"),
            DiscoveryQuery("avg"),
        ),
        operator_attributes=dict(_orders_request().operator_attributes),
        allowed_operator_ids=("nl2sql@2.0.0", "select@2.0.0", "avg@2.0.0"),
    )

    with pytest.raises(PlanningError, match="requires a request data scope") as caught:
        planner.plan(request)

    assert caught.value.record.stage is PlanningStage.COMPILATION


def test_the_entity_projection_does_not_authorize_or_restrict_sql_tables() -> None:
    # The address check compares the step's source/database/collection to the scope and
    # nothing else. A question naming a table outside DataScope.entities still compiles:
    # the context makes no table-authorization claim, and nl2sql has no table-allowlist input.
    planner, _ = _orders_planner(_FixedGenerator())
    request = _orders_request(
        nl2sql_attributes={"question": "Average total from the customers table"}
    )

    planning = planner.plan(request)

    assert planning.data_context is not None
    assert planning.data_context.scope.entities == ("orders",)
    assert planning.preflight.operator_ids == ("nl2sql@2.0.0", "select@2.0.0", "avg@2.0.0")


# --- New error vocabulary ----------------------------------------------------------- #
def test_the_data_context_stage_and_codes_are_stable() -> None:
    assert tuple(stage.value for stage in PlanningStage) == (
        "VALIDATION",
        "DISCOVERY",
        "DATA_CONTEXT",
        "GENERATION",
        "SELECTION",
        "COMPILATION",
        "PREFLIGHT",
    )
    assert [code.value for code in PlanningErrorCode if code.value.startswith("DATA_CONTEXT")] == [
        "DATA_CONTEXT_REQUIRED",
        "DATA_CONTEXT_UNAVAILABLE",
        "DATA_CONTEXT_SCOPE_MISMATCH",
        "DATA_CONTEXT_RESULT_INVALID",
        "DATA_CONTEXT_LIMIT_EXCEEDED",
        "DATA_CONTEXT_FAILED",
        # The disclosure gate is grouped here because it guards the data-context
        # boundary, though only a provider-backed generator raises it.
        "DATA_CONTEXT_DISCLOSURE_REQUIRED",
    ]


# --- The real SQLite seam, with no query executed ----------------------------------- #
def test_the_local_sqlite_seam_collects_the_orders_snapshot_without_executing_a_query(
    tmp_path: Path,
) -> None:
    pytest.importorskip("blue_data")
    from blue_data.registry.data_registry import (  # pyright: ignore[reportMissingTypeStubs]
        DataRegistry,
    )
    from blue_data.source.sql.sqlite.sqlite_sql_source import (  # pyright: ignore[reportMissingTypeStubs]
        SQLiteDBSource,
    )

    from blue_data_ops.data import RegistrySeam

    executed: list[Any] = []
    seam = RegistrySeam(DataRegistry(name="context_probe", rebuild=True))
    seam.register_source(
        SQLiteDBSource(
            ORDERS_SOURCE,
            properties={"connection": {"database_directory": str(tmp_path)}},
        )
    )
    seam.create_source_database(ORDERS_SOURCE, ORDERS_DATABASE, overwrite=True)
    seam.create_source_database_collection_entity(
        ORDERS_SOURCE,
        ORDERS_DATABASE,
        ORDERS_COLLECTION,
        "orders",
        creation_properties={
            "cols_definition": [
                {"name": "order_id", "type": "INTEGER"},
                {"name": "customer_id", "type": "INTEGER"},
                {"name": "total", "type": "REAL"},
                {"name": "currency", "type": "TEXT"},
            ],
            "primary_key": ["order_id"],
        },
        overwrite=True,
    )
    seam.set_source_database_collection_entity_description(
        ORDERS_SOURCE,
        ORDERS_DATABASE,
        ORDERS_COLLECTION,
        "orders",
        ORDERS_DESCRIPTION,
        rebuild=True,
    )

    def refuse_query(*args: Any, **kwargs: Any) -> None:
        executed.append((args, kwargs))
        raise AssertionError("data context collection must not execute a query")

    setattr(seam, "execute_query", refuse_query)

    collected = RegistryDataContextProvider(seam).collect(orders_scope())
    document = as_document(collected)

    assert executed == []
    # blue-data has used both "sql/sqlite" and "sqlite". Preserve the value
    # declared by the source rather than normalizing it to the fixture value.
    fixture = load_fixture("data_context_orders.json")
    declared = seam.get_source_properties(ORDERS_SOURCE)["connection"]["protocol"]
    assert document["protocol"] == declared
    assert document | {"protocol": fixture["protocol"]} == fixture
    assert str(tmp_path) not in _canonical(document).decode("utf-8")
    assert "database_directory" not in _canonical(document).decode("utf-8")


# --- Mutation after construction ---------------------------------------------------- #
class _HostileEq:
    def __eq__(self, other: object) -> bool:
        raise RuntimeError("eq-payload-should-not-leak")

    def __ne__(self, other: object) -> bool:
        raise RuntimeError("eq-payload-should-not-leak")

    def __hash__(self) -> int:
        return 0


class _HostileGetDict(dict[str, Any]):
    def get(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("get-payload-should-not-leak")


class _HostileBoolTuple(tuple[str, ...]):
    def __bool__(self) -> bool:
        raise RuntimeError("bool-payload-should-not-leak")


class _HostileStr(str):
    def strip(self, chars: str | None = None) -> str:
        del chars
        raise RuntimeError("strip-payload-should-not-leak")


def _mutated(field: str, value: Any) -> DataContextSnapshot:
    snapshot = _collect_orders()
    object.__setattr__(snapshot, field, value)
    return snapshot


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scope", _HostileEq()),
        ("scope", DataScope("other_source", "shop", "public", ("orders",))),
        ("payload", _HostileGetDict({"schema": {}})),
        ("payload", {"protocol": "sqlite"}),
        ("resolved_entities", ("orders", "smuggled")),
        ("resolved_entities", ["orders"]),
    ],
)
def test_the_planner_rejects_every_post_construction_mutation(field: str, value: Any) -> None:
    snapshot = _mutated(field, value)

    with pytest.raises(PlanningError) as caught:
        _planner_with(snapshot).plan(_orders_request())

    assert "payload-should-not-leak" not in str(caught.value)
    assert caught.value.record.stage is PlanningStage.DATA_CONTEXT
    assert caught.value.record.code in {
        PlanningErrorCode.DATA_CONTEXT_RESULT_INVALID,
        PlanningErrorCode.DATA_CONTEXT_SCOPE_MISMATCH,
    }


class _MutatingGenerator:
    """Rewrites every field of its own snapshot copy, which the contract permits."""

    def __init__(self) -> None:
        self.seen: DataContextSnapshot | None = None

    def generate(
        self,
        request: PlanningRequest,
        discovery: Any,
        data_context: DataContextSnapshot | None,
    ) -> Sequence[PlanDraft]:
        del discovery
        assert data_context is not None
        self.seen = data_context
        object.__setattr__(
            data_context, "payload", {**_payload(data_context), "protocol": "forged-protocol"}
        )
        object.__setattr__(
            data_context, "scope", DataScope("other_source", "other_db", "other_collection")
        )
        object.__setattr__(data_context, "resolved_entities", ("smuggled",))
        object.__setattr__(data_context, "to_dict", lambda: {"forged": True})
        return (_orders_draft(request),)


def test_generator_mutation_of_its_copy_reaches_neither_compilation_nor_the_result() -> None:
    generator = _MutatingGenerator()
    planner, _ = _orders_planner(generator)

    planning = planner.plan(_orders_request())

    # The mutation happened, and it stayed on the generator's copy. Read the field
    # directly: the generator shadowed to_dict on that copy too.
    assert generator.seen is not None
    assert generator.seen.payload["protocol"] == "forged-protocol"
    assert generator.seen.scope.collection == "other_collection"

    retained = planning.data_context
    assert retained is not None
    assert retained is not generator.seen
    assert as_document(retained) == as_document(_collect_orders())
    assert retained.scope == orders_scope()
    assert retained.resolved_entities == ("orders",)

    # The request's nl2sql step addresses the real orders collection. Had compilation
    # read the generator's copy, that address would no longer have matched the scope and
    # the plan would have been rejected; it compiled, so the anchor is what was read.
    assert planning.preflight.operator_ids == ("nl2sql@2.0.0", "select@2.0.0", "avg@2.0.0")


@pytest.mark.parametrize(
    "scope_field",
    ["source", "database", "collection", "entities"],
)
def test_the_adapter_rejects_a_scope_mutated_after_construction(scope_field: str) -> None:
    scope = orders_scope()
    replacement: Any = (
        _HostileBoolTuple(("orders",)) if scope_field == "entities" else _HostileStr("demo_sqlite")
    )
    object.__setattr__(scope, scope_field, replacement)

    with pytest.raises(PlanningError) as caught:
        provider(orders_double()).collect(scope)

    assert "payload-should-not-leak" not in str(caught.value)
    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_RESULT_INVALID


# --- Foreign error text never crosses the boundary ---------------------------------- #
class _PlanningErrorRegistry(RegistryDouble):
    def list_collection_entities(self, source: str, database: str, collection: str) -> Any:
        raise PlanningError("REGISTRY_SECRET_8675309")


class _PlanningErrorProvider:
    def collect(self, scope: DataScope) -> DataContextSnapshot:
        del scope
        raise PlanningError("PROVIDER_SECRET_8675309")


def test_a_registry_planning_error_does_not_pass_its_text_through() -> None:
    with pytest.raises(PlanningError, match="data context collection failed") as caught:
        provider(_PlanningErrorRegistry()).collect(orders_scope())

    assert "REGISTRY_SECRET" not in str(caught.value)
    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_FAILED
    assert caught.value.record.stage is PlanningStage.DATA_CONTEXT


def test_a_foreign_provider_planning_error_does_not_pass_its_text_through() -> None:
    planner = PipelinePlanner(
        versioned_registry(), _FixedGenerator(), None, cast(Any, _PlanningErrorProvider())
    )

    with pytest.raises(PlanningError, match="data context collection failed") as caught:
        planner.plan(_orders_request())

    assert "PROVIDER_SECRET" not in str(caught.value)
    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_FAILED
    assert caught.value.record.stage is PlanningStage.DATA_CONTEXT


# --- The wire bound is fixed, not declared ------------------------------------------ #
def test_a_payload_cannot_raise_the_name_and_type_limit_by_declaring_it() -> None:
    # A whole-collection scope, so the oversized name reaches the payload validators
    # rather than being caught earlier as a scope identifier.
    collected = _collect_orders()
    payload = _payload(collected)
    oversized = "x" * 129
    payload["limits"] = {
        **cast("dict[str, Any]", payload["limits"]),
        "max_name_or_type_codepoints": 129,
    }
    payload["schema"] = {"entities": [{"name": oversized, "attributes": []}]}

    with pytest.raises(PlanningError, match="redeclare the name and type limit") as caught:
        DataContextSnapshot(scope=orders_scope(()), resolved_entities=(oversized,), payload=payload)

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_RESULT_INVALID


def test_an_oversized_name_still_fails_when_the_declared_limit_is_correct() -> None:
    collected = _collect_orders()
    payload = _payload(collected)
    oversized = "x" * 129
    payload["schema"] = {"entities": [{"name": oversized, "attributes": []}]}

    with pytest.raises(PlanningError, match="exceeds its name limit") as caught:
        DataContextSnapshot(scope=orders_scope(()), resolved_entities=(oversized,), payload=payload)

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_LIMIT_EXCEEDED


@pytest.mark.parametrize("field", ["source", "database", "collection"])
def test_an_oversized_scope_identifier_fails_the_snapshot(field: str) -> None:
    collected = _collect_orders()
    scope = DataScope(
        **{
            **{
                "source": ORDERS_SOURCE,
                "database": ORDERS_DATABASE,
                "collection": ORDERS_COLLECTION,
            },
            field: "x" * 129,
        },
        entities=("orders",),
    )

    with pytest.raises(PlanningError, match="exceeds its name limit") as caught:
        DataContextSnapshot(scope=scope, resolved_entities=("orders",), payload=_payload(collected))

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_LIMIT_EXCEEDED


# --- No undeclared provenance restriction ------------------------------------------- #
def test_provenance_accepts_finite_json_beyond_the_package_adapter_shape() -> None:
    collected = _collect_orders()
    payload = _payload(collected)
    payload["provenance"] = {
        "provider": "third-party-provider",
        "raw_rows": 0,
        **{f"fact_{index}": f"value-{index}" for index in range(20)},
        "nested": {"depth": [1, 2.5, True, None]},
    }

    rebuilt = DataContextSnapshot(
        scope=collected.scope, resolved_entities=collected.resolved_entities, payload=payload
    )

    assert as_document(rebuilt)["provenance"]["nested"] == {"depth": [1, 2.5, True, None]}


@pytest.mark.parametrize(
    "provenance",
    [
        {"provider": "p", "raw_rows": 1},
        {"provider": "p"},
        {"raw_rows": 0},
        {"provider": "", "raw_rows": 0},
        {"provider": "p", "raw_rows": 0, "bad": float("inf")},
        {"provider": "p", "raw_rows": 0, "bad": object()},
    ],
)
def test_provenance_still_enforces_its_declared_constraints(provenance: Any) -> None:
    collected = _collect_orders()
    payload = _payload(collected)
    payload["provenance"] = provenance

    with pytest.raises(PlanningError, match="provenance"):
        DataContextSnapshot(
            scope=collected.scope, resolved_entities=collected.resolved_entities, payload=payload
        )


# --- A blank description is omitted, not fatal -------------------------------------- #
def test_a_blank_description_is_omitted_rather_than_failing_collection() -> None:
    double = orders_double()
    double.entities = [entity_record("orders", orders_scope(), "   ")]

    entity = as_document(provider(double).collect(orders_scope()))["schema"]["entities"][0]

    assert "description" not in entity


def test_the_snapshot_accepts_any_bounded_string_description() -> None:
    collected = _collect_orders()
    payload = _payload(collected)
    entities = cast("list[dict[str, Any]]", cast("dict[str, Any]", payload["schema"])["entities"])
    entities[0]["description"] = "   "

    rebuilt = DataContextSnapshot(
        scope=collected.scope, resolved_entities=collected.resolved_entities, payload=payload
    )

    assert as_document(rebuilt)["schema"]["entities"][0]["description"] == "   "


# --- Persisted registry records --------------------------------------------------- #
def _orders_registry(tmp_path: Path) -> Any:
    """Build a real registry holding the owner orders collection."""

    from blue_data.registry.data_registry import (  # pyright: ignore[reportMissingTypeStubs]
        DataRegistry,
    )
    from blue_data.source.sql.sqlite.sqlite_sql_source import (  # pyright: ignore[reportMissingTypeStubs]
        SQLiteDBSource,
    )

    from blue_data_ops.data import RegistrySeam

    registry = DataRegistry(name="context_store", rebuild=True)
    seam = RegistrySeam(registry)
    seam.register_source(
        SQLiteDBSource(
            ORDERS_SOURCE, properties={"connection": {"database_directory": str(tmp_path)}}
        )
    )
    seam.create_source_database(ORDERS_SOURCE, ORDERS_DATABASE, overwrite=True)
    seam.create_source_database_collection_entity(
        ORDERS_SOURCE,
        ORDERS_DATABASE,
        ORDERS_COLLECTION,
        "orders",
        creation_properties={
            "cols_definition": [
                {"name": "order_id", "type": "INTEGER"},
                {"name": "customer_id", "type": "INTEGER"},
                {"name": "total", "type": "REAL"},
                {"name": "currency", "type": "TEXT"},
            ],
            "primary_key": ["order_id"],
        },
        overwrite=True,
    )
    seam.set_source_database_collection_entity_description(
        ORDERS_SOURCE,
        ORDERS_DATABASE,
        ORDERS_COLLECTION,
        "orders",
        ORDERS_DESCRIPTION,
        rebuild=True,
    )
    return registry, seam


def _reopened(registry: Any) -> Any:
    """A second registry over the same store: persisted records, no live source object."""

    from blue_data.registry.data_registry import (  # pyright: ignore[reportMissingTypeStubs]
        DataRegistry,
    )

    from blue_data_ops.data import RegistrySeam

    reopened = DataRegistry(name="context_store", store=getattr(registry, "store"), rebuild=False)
    assert reopened.sources == {}
    return RegistrySeam(reopened)


def test_context_collects_from_newly_created_registry_records(tmp_path: Path) -> None:
    pytest.importorskip("blue_data")
    _, seam = _orders_registry(tmp_path)

    collected = RegistryDataContextProvider(seam).collect(orders_scope())

    fixture = load_fixture("data_context_orders.json")
    declared = seam.get_source_properties(ORDERS_SOURCE)["connection"]["protocol"]
    assert as_document(collected)["protocol"] == declared
    assert as_document(collected) | {"protocol": fixture["protocol"]} == fixture


def test_context_collects_from_previously_persisted_records_without_connect_source(
    tmp_path: Path,
) -> None:
    # Rehydrating a source needs stored `_class` metadata. Collection reads the
    # registered records directly, so reopening the registry preserves the snapshot.
    pytest.importorskip("blue_data")
    registry, seam = _orders_registry(tmp_path)
    reopened = _reopened(registry)

    fresh = as_document(RegistryDataContextProvider(seam).collect(orders_scope()))
    persisted = as_document(RegistryDataContextProvider(reopened).collect(orders_scope()))

    assert persisted == fresh
    assert getattr(reopened, "_registry").sources == {}  # never connected a source


def test_context_collection_does_not_need_class_provenance(tmp_path: Path) -> None:
    # The strongest form of the same statement: strip the `_class` field that
    # connect_source() now requires. Connecting fails; collecting still succeeds.
    pytest.importorskip("blue_data")
    registry, _ = _orders_registry(tmp_path)
    reopened = _reopened(registry)
    properties = reopened.get_source_properties(ORDERS_SOURCE)
    properties.pop("_class", None)

    from importlib import import_module

    from blue_data_ops.data.errors import RegistryFailure

    with pytest.raises(ValueError, match="_class"):
        reopened.connect_source(ORDERS_SOURCE)
    seam_module = cast(Any, import_module("blue_data_ops.data.registry_seam"))
    with pytest.raises(RegistryFailure, match="data source is unavailable"):
        seam_module._diagnose_source(reopened, ORDERS_SOURCE)

    collected = RegistryDataContextProvider(reopened).collect(orders_scope())

    assert collected.resolved_entities == ("orders",)
    assert as_document(collected)["schema"]["entities"][0]["name"] == "orders"


def test_persisted_collection_still_executes_no_query(tmp_path: Path) -> None:
    pytest.importorskip("blue_data")
    registry, _ = _orders_registry(tmp_path)
    reopened = _reopened(registry)
    executed: list[Any] = []

    def refuse_query(*args: Any, **kwargs: Any) -> None:
        executed.append((args, kwargs))
        raise AssertionError("data context collection must not execute a query")

    setattr(reopened, "execute_query", refuse_query)

    RegistryDataContextProvider(reopened).collect(orders_scope())

    assert executed == []


# --- The retained payload is frozen all the way down -------------------------------- #
def test_the_retained_snapshot_payload_cannot_be_mutated_after_planning() -> None:
    planner, _ = _orders_planner(_FixedGenerator())

    planning = planner.plan(_orders_request())

    assert planning.data_context is not None
    schema = planning.data_context.payload["schema"]
    with pytest.raises(TypeError):
        cast("dict[str, Any]", schema)["entities"] = []
    entities = cast("dict[str, Any]", schema)["entities"]
    assert isinstance(entities, tuple)  # frozen all the way down, not just at the top


# --- The request scope survives a hostile provider ---------------------------------- #
class _ScopeMutatingProvider:
    """Narrows the projection of whatever scope object it is handed, then collects."""

    def __init__(self) -> None:
        self.received: DataScope | None = None
        self.inner = provider(orders_double())

    def collect(self, scope: DataScope) -> DataContextSnapshot:
        self.received = scope
        object.__setattr__(scope, "entities", ("orders",))
        return self.inner.collect(scope)


def test_a_provider_cannot_narrow_the_projection_by_mutating_the_scope_it_receives() -> None:
    request = _orders_request(orders_scope(("customers", "orders")))
    hostile = _ScopeMutatingProvider()
    generator = _FixedGenerator()
    planner = PipelinePlanner(versioned_registry(), generator, None, cast(Any, hostile))

    with pytest.raises(PlanningError, match="scope does not match") as caught:
        planner.plan(request)

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_SCOPE_MISMATCH
    # Caught before the generator ever saw a narrowed snapshot.
    assert generator.seen == []
    # And the request's own scope was never handed out, so it is untouched.
    assert request.data_scope is not None
    assert request.data_scope.entities == ("customers", "orders")
    assert hostile.received is not request.data_scope


class _ScopeMutatingGenerator:
    def generate(
        self,
        request: PlanningRequest,
        discovery: Any,
        data_context: DataContextSnapshot | None,
    ) -> Sequence[PlanDraft]:
        del discovery, data_context
        assert request.data_scope is not None
        object.__setattr__(request.data_scope, "collection", "other_collection")
        return (_orders_draft(request),)


def test_a_generator_cannot_repoint_the_request_scope_before_compilation() -> None:
    planner, _ = _orders_planner(_ScopeMutatingGenerator())

    with pytest.raises(PlanningError, match="scope does not match") as caught:
        planner.plan(_orders_request())

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_SCOPE_MISMATCH


# --- Trust follows the code path, not the object's type ----------------------------- #
def test_an_instance_level_collect_shadow_is_never_invoked() -> None:
    adapter = provider(orders_double())
    shadow_calls: list[DataScope] = []

    def shadowed_collect(scope: DataScope) -> DataContextSnapshot:
        shadow_calls.append(scope)
        raise PlanningError("EXACT_INSTANCE_SECRET")

    object.__setattr__(adapter, "collect", shadowed_collect)
    assert type(adapter) is RegistryDataContextProvider  # the exact-type premise holds
    planner = PipelinePlanner(versioned_registry(), _FixedGenerator(), None, adapter)

    planning = planner.plan(_orders_request())

    assert shadow_calls == []
    assert planning.data_context is not None
    assert as_document(planning.data_context)["schema"]["entities"][0]["name"] == "orders"


def _adapter_limits_of(adapter: RegistryDataContextProvider) -> dict[str, int]:
    """Read the adapter's private limits for a corruption fixture, in one typed place."""

    return cast("dict[str, int]", getattr(adapter, "_limits"))


def test_a_corrupted_limits_attribute_is_contained_generically() -> None:
    """`_limits` is the one mutable input the trusted path still reads.

    It is pinned to package-owned exact integers on entry, so a replacement can neither
    raise its own record out of the trusted branch nor run a comparison of its own.
    """

    class _HostileLimits(dict[str, int]):
        def items(self) -> Any:
            raise PlanningError("CALLER_SUPPLIED_TEXT")

    corruptions: list[Any] = [
        _HostileLimits({"max_entities": 32}),
        "not-a-dict",
        {"max_entities": 32},  # exact dict, incomplete key set
        {**_adapter_limits_of(provider(orders_double())), "max_raw_rows": 8},
        {**_adapter_limits_of(provider(orders_double())), "max_name_or_type_codepoints": 129},
        {**_adapter_limits_of(provider(orders_double())), "max_entities": True},
    ]
    for corrupted in corruptions:
        adapter = provider(orders_double())
        object.__setattr__(adapter, "_limits", corrupted)
        planner = PipelinePlanner(versioned_registry(), _FixedGenerator(), None, adapter)

        with pytest.raises(PlanningError) as caught:
            planner.plan(_orders_request())

        assert "CALLER_SUPPLIED_TEXT" not in str(caught.value)
        assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_FAILED
        assert caught.value.record.stage is PlanningStage.DATA_CONTEXT
        assert caught.value.record.suggestion == "Check the data registry and the context provider."


# --- No unrecorded depth limit ------------------------------------------------------ #
@pytest.mark.parametrize("depth", [1, 63, 64, 65, 200])
def test_finite_acyclic_provenance_is_accepted_at_any_depth(depth: int) -> None:
    collected = _collect_orders()
    payload = _payload(collected)
    nested: Any = "leaf"
    for _ in range(depth):
        nested = [nested]
    payload["provenance"] = {"provider": "third-party", "raw_rows": 0, "nested": nested}

    rebuilt = DataContextSnapshot(
        scope=collected.scope, resolved_entities=collected.resolved_entities, payload=payload
    )

    assert as_document(rebuilt)["provenance"]["nested"] == nested


def test_a_self_referential_provenance_terminates_with_a_fixed_record() -> None:
    collected = _collect_orders()
    payload = _payload(collected)
    cyclic: dict[str, Any] = {"provider": "third-party", "raw_rows": 0}
    cyclic["self"] = cyclic
    payload["provenance"] = cyclic

    with pytest.raises(PlanningError, match="provenance is malformed") as caught:
        DataContextSnapshot(
            scope=collected.scope, resolved_entities=collected.resolved_entities, payload=payload
        )

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_RESULT_INVALID


def test_a_shadowed_scope_to_dict_cannot_change_the_serialized_scope() -> None:
    snapshot = _collect_orders()
    object.__setattr__(snapshot.scope, "to_dict", lambda: {"source": "forged"})

    document = cast("dict[str, Any]", DataContextSnapshot.to_dict(snapshot))

    assert document["scope"]["source"] == ORDERS_SOURCE


# --- The selector cannot repoint compilation ---------------------------------------- #
class _ScopeMutatingSelector:
    def __init__(self, request: PlanningRequest) -> None:
        self.request = request

    def select(self, candidates: Sequence[PlanDraft]) -> PlanDraft:
        assert self.request.data_scope is not None
        object.__setattr__(self.request.data_scope, "collection", "other_collection")
        return candidates[0]


def test_a_selector_cannot_repoint_the_scope_before_the_address_check() -> None:
    request = _orders_request(nl2sql_attributes={"collection": "other_collection"})
    selector = _ScopeMutatingSelector(request)
    planner = PipelinePlanner(
        versioned_registry(),
        _FixedGenerator(),
        cast(Any, selector),
        provider(orders_double()),
    )

    with pytest.raises(PlanningError, match="scope does not match") as caught:
        planner.plan(request)

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_SCOPE_MISMATCH


# --- The interpreter ceiling is contained ------------------------------------------- #
def test_provenance_at_the_recursion_ceiling_yields_a_structured_record() -> None:
    import sys

    collected = _collect_orders()
    payload = _payload(collected)
    nested: Any = "leaf"
    for _ in range(sys.getrecursionlimit() + 50):
        nested = [nested]
    payload["provenance"] = {"provider": "third-party", "raw_rows": 0, "nested": nested}

    with pytest.raises(PlanningError, match="could not be serialized") as caught:
        DataContextSnapshot(
            scope=collected.scope, resolved_entities=collected.resolved_entities, payload=payload
        )

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_RESULT_INVALID
    assert caught.value.record.stage is PlanningStage.DATA_CONTEXT


# --- The package adapter's own outcomes stay distinct ------------------------------- #
@pytest.mark.parametrize(
    ("adapter", "match", "code", "category"),
    [
        (
            lambda: provider(orders_double(), max_description_chars=8),
            "exceeds its description limit",
            PlanningErrorCode.DATA_CONTEXT_LIMIT_EXCEEDED,
            ErrorCategory.RECOVERABLE,
        ),
        (
            lambda: provider(RegistryDouble(entities=[], attributes={})),
            "requested entity is not registered",
            PlanningErrorCode.DATA_CONTEXT_UNAVAILABLE,
            ErrorCategory.RECOVERABLE,
        ),
        (
            lambda: provider(RegistryDouble(entities=cast(Any, "not-a-list"))),
            "malformed entity listing",
            PlanningErrorCode.DATA_CONTEXT_RESULT_INVALID,
            ErrorCategory.FAILED,
        ),
    ],
)
def test_the_package_adapter_surfaces_its_distinct_structured_outcomes(
    adapter: Any, match: str, code: PlanningErrorCode, category: ErrorCategory
) -> None:
    # The outcomes have to stay distinct: a limit violation is recoverable by narrowing
    # the scope, an unregistered entity is a scope error, a malformed listing is a failure.
    # Genericizing the trusted adapter would collapse all three.
    planner = PipelinePlanner(versioned_registry(), _FixedGenerator(), None, adapter())

    with pytest.raises(PlanningError, match=match) as caught:
        planner.plan(_orders_request())

    assert caught.value.record.code is code
    assert caught.value.record.category is category
    assert caught.value.record.stage is PlanningStage.DATA_CONTEXT


# --- The anchor precedes the first caller callback ---------------------------------- #
class _ScopeMutatingRegistry:
    """A caller registry that repoints the request scope from find(), during discovery."""

    def __init__(self, request: PlanningRequest) -> None:
        self._inner = versioned_registry()
        self.request = request

    def find(self, text: str, tags: Any = ()) -> Any:
        assert self.request.data_scope is not None
        object.__setattr__(self.request.data_scope, "collection", "other_collection")
        return self._inner.find(text, tags=tags)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def test_discovery_cannot_repoint_the_scope_before_the_anchor_exists() -> None:
    request = _orders_request(nl2sql_attributes={"collection": "other_collection"})
    planner = PipelinePlanner(
        cast(Any, _ScopeMutatingRegistry(request)),
        _FixedGenerator(),
        None,
        provider(orders_double()),
    )

    with pytest.raises(PlanningError, match="scope does not match") as caught:
        planner.plan(request)

    assert caught.value.record.code is PlanningErrorCode.DATA_CONTEXT_SCOPE_MISMATCH


# --- Nothing the provider owns survives into the retained snapshot ------------------ #
def test_the_retained_snapshot_keeps_no_provider_container_or_shadow() -> None:
    """The rebuild, from the provider's side: containers and shadows both dropped.

    A same-content proxy over a mapping the provider keeps is indistinguishable by
    content, and a shadowed `to_dict` would decide what the snapshot claims to hold.
    Rebuilding into package-owned instances is what answers both at once.
    """

    from types import MappingProxyType

    calls: list[int] = []

    def raising() -> dict[str, Any]:
        calls.append(1)
        raise PlanningError("PUBLIC_SHADOW_TEXT")

    snapshot = _collect_orders()
    backing: dict[str, Any] = dict(_payload(snapshot))
    object.__setattr__(snapshot, "payload", MappingProxyType(backing))
    object.__setattr__(snapshot, "to_dict", raising)
    object.__setattr__(snapshot.scope, "to_dict", lambda: {"source": "forged"})
    planner = PipelinePlanner(
        versioned_registry(), _FixedGenerator(), None, cast(Any, _ScriptedProvider(snapshot))
    )

    planning = planner.plan(_orders_request())

    retained = planning.data_context
    assert retained is not None
    assert calls == []  # never dispatched through the instance attribute

    # The public call, not the class call: neither shadow travelled onto the rebuild.
    document = cast("dict[str, Any]", retained.to_dict())
    assert document["schema"]["entities"][0]["name"] == "orders"
    assert document["scope"]["source"] == ORDERS_SOURCE
    assert "PUBLIC_SHADOW_TEXT" not in json.dumps(document)
    assert vars(retained).keys() == {"scope", "resolved_entities", "payload"}
    assert vars(retained.scope).keys() == {"source", "database", "collection", "entities"}

    # And the provider's own container is not the one the result holds.
    assert retained.payload is not backing
    backing["protocol"] = "post-plan-change"
    assert as_document(retained)["protocol"] == "sql/sqlite"
