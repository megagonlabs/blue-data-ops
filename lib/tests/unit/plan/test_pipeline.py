from __future__ import annotations

from typing import Any, cast

import pytest

from blue_data_ops.plan import DataPipeline, EntityType, NodeType, Status
from blue_data_ops.plan import pipeline as pipeline_module


@pytest.fixture(autouse=True)
def clear_shared_operator_attributes() -> None:
    cast(dict[str, Any], getattr(pipeline_module, "_SHARED_OPERATOR_ATTRIBUTES")).clear()


def test_empty_pipeline_has_the_canonical_layered_wire_shape() -> None:
    pipeline = DataPipeline(id="empty")

    assert pipeline.to_dict() == {
        "id": "empty",
        "label": None,
        "type": "DATA_PIPELINE",
        "nodes": {},
        "map": {},
        "entities": {},
        "properties": {},
        "provenance": "$",
        "input": None,
        "output": None,
        "attributes": {},
    }
    assert pipeline.to_dict() is pipeline.get_data()


def test_base_plan_classes_keep_blue_default_type_strings() -> None:
    assert pipeline_module.Entity().get_type() == "Entity"
    assert pipeline_module.DAG().get_type() == "DAG"
    assert pipeline_module.Plan().get_type() == "PLAN"


def test_definitions_build_nodes_and_a_separate_pinned_operator_entity() -> None:
    pipeline = DataPipeline(id="pipe", plan_provenance="root")
    attributes = {"field": "score"}

    input_node = pipeline.define_input("input", value=3, provenance="source")
    operator_node = pipeline.define_operator(
        "select@1.2.3",
        label="selection",
        attributes=attributes,
        properties={"description": "choose rows"},
    )
    output_node = pipeline.define_output("output")

    assert input_node.get_data("values") == {"source": 3}
    assert input_node.get_data("statuses") == {}
    assert input_node.get_data("provenance") == "root.pipe"
    assert operator_node.get_data("status") is None
    assert output_node.get_data("value") is None
    entity = pipeline.get_node_entity(operator_node, type=str(EntityType.OPERATOR))
    assert entity is not None
    assert entity.get_data("operator_id") == "select@1.2.3"
    assert entity.get_data("attributes") is attributes
    assert "name" not in entity.to_dict()
    assert operator_node.get_data(str(EntityType.OPERATOR)) == entity.get_id()


@pytest.mark.parametrize("operator_id", ["select", "/server/a/operator/select", "select@1.2"])
def test_operator_references_must_be_pinned_and_portable(operator_id: str) -> None:
    with pytest.raises(ValueError, match="pinned"):
        DataPipeline().create_operator(operator_id)


def test_missing_operator_name_keeps_the_reference_exception() -> None:
    with pytest.raises(Exception, match="^Name is not specified$"):
        DataPipeline().define_operator(None)  # type: ignore[arg-type]


def test_from_dict_mutates_defaults_and_adopts_the_callers_record() -> None:
    record: dict[str, Any] = {"id": "p", "type": "DATA_PIPELINE"}

    pipeline = DataPipeline.from_dict(record)

    assert record == {
        "id": "p",
        "type": "DATA_PIPELINE",
        "label": None,
        "properties": {},
        "nodes": {},
        "map": {},
        "entities": {},
    }
    assert pipeline.to_dict() is record
    assert pipeline.get_data("provenance") is None
    with pytest.raises(Exception, match="^Failed validation$"):
        DataPipeline.from_dict({"id": "missing-type"})


def test_endpoints_resolve_objects_ids_and_labels_but_keep_unknown_literals() -> None:
    pipeline = DataPipeline(id="p")
    input_node = pipeline.define_input("input")
    output_node = pipeline.define_output("output")

    pipeline.set_plan_input(input_node)
    pipeline.set_plan_output("output")
    assert pipeline.get_plan_input_id() == input_node.get_id()
    assert pipeline.get_plan_input() is not None
    assert pipeline.get_plan_output_id() == output_node.get_id()

    pipeline.set_plan_input_id("unresolved")
    assert pipeline.get_plan_input_id() == "unresolved"
    assert pipeline.get_plan_input() is None


def test_edges_traversal_filtering_counts_and_leaf_rules() -> None:
    pipeline = DataPipeline(id="p")
    first = pipeline.define_input("first")
    middle = pipeline.define_operator("select@1.0.0", label="middle")
    last = pipeline.define_output("last")
    isolated = pipeline.define_output("isolated")

    pipeline.connect_nodes(first, middle)
    pipeline.connect_nodes(first, middle)
    pipeline.connect_nodes(middle, last)
    assert pipeline.is_node_leaf(last)
    first.get_data("prev").append("missing")
    last.get_data("next").append("missing")

    assert middle.get_data("prev") == [first.get_id()]
    assert first.get_data("next") == [middle.get_id()]
    assert [node.get_id() for node in pipeline.get_prev_nodes(middle)] == [first.get_id()]
    assert [node.get_id() for node in pipeline.get_next_nodes(middle)] == [last.get_id()]
    assert list(pipeline.filter_nodes([str(NodeType.OPERATOR)])) == [middle.get_id()]
    assert pipeline.filter_nodes([], False, False).keys() == pipeline.get_nodes().keys()
    assert pipeline.count_nodes(filter_hasPrev=True) == 3
    assert not pipeline.is_node_leaf(last)
    assert not pipeline.is_node_leaf(isolated)

    with pytest.raises(Exception, match="^Undefined from node$"):
        pipeline.connect_nodes("missing", first)
    with pytest.raises(Exception, match="^Undefined to node$"):
        pipeline.connect_nodes(first, "missing")


def test_label_collision_enforcement_is_asymmetric_across_layers() -> None:
    node_first = DataPipeline()
    node_first.create_node(label="same")
    with pytest.raises(Exception, match="failed varification"):
        node_first.create_node(label="same")
    with pytest.raises(Exception, match="failed varification"):
        node_first.create_entity(label="same", type="CUSTOM")

    entity_first = DataPipeline()
    entity = entity_first.create_entity(label="same", type="CUSTOM")
    node = entity_first.create_node(label="same")
    assert entity_first.get_data("map")["same"] == node.get_id()
    assert entity_first.get_entity(entity.get_id()) is not None


def test_values_statuses_properties_and_attributes_are_live() -> None:
    pipeline = DataPipeline(properties={"owner": "team"}, attributes={"mode": "fast"})
    node = pipeline.define_input()

    pipeline.set_node_value(node, 11, provenance="")
    pipeline.set_node_value(node, 12, provenance="p1")
    pipeline.set_node_status(node, Status.EXECUTED, provenance="")
    pipeline.set_node_status(node, Status.EXECUTING, provenance="p1")

    assert pipeline.get_node_value(node) == 12
    assert pipeline.get_node_values(node) == {"p1": 12}
    assert pipeline.get_node_value(node, "missing") is None
    assert pipeline.get_node_status(node) == Status.EXECUTING
    assert pipeline.get_node_statuses(node) == {"p1": Status.EXECUTING}
    assert pipeline.get_node_status(node, "missing") is None
    pipeline.get_properties()["live"] = True
    pipeline.get_attributes()["live"] = True
    assert pipeline.get_property("live") is True
    assert pipeline.get_attribute("live") is True
    with pytest.raises(AttributeError):
        pipeline.get_node_value("missing")
    with pytest.raises(Exception, match="non-existing node cannot be get"):
        pipeline.get_node_entity("missing")


def test_entity_links_can_duplicate_and_omitted_operator_attributes_are_shared() -> None:
    pipeline = DataPipeline()
    first = pipeline.define_operator("select@1.0.0")
    second = pipeline.define_operator("project@1.0.0")
    first_entity = pipeline.get_node_entity(first, type=str(EntityType.OPERATOR))
    second_entity = pipeline.get_node_entity(second, type=str(EntityType.OPERATOR))
    assert first_entity is not None and second_entity is not None

    pipeline.set_node_entity(first, first_entity)
    assert first_entity.get_data("nodes") == [first.get_id(), first.get_id()]
    first_entity.get_data("attributes")["shared"] = True
    assert second_entity.get_data("attributes") == {"shared": True}

    pipeline.set_node_entity(second, None, field="optional")
    assert second.get_data("optional") is None


def test_append_data_keeps_list_and_uniqueness_behavior() -> None:
    node = DataPipeline().define_input()
    node.append_data("next", "n", unique=True)
    node.append_data("next", "n", unique=True)
    assert node.get_data("next") == ["n"]
    with pytest.raises(Exception, match="^Data is not a list$"):
        node.append_data("value", "x")


def test_merge_imports_live_layers_and_nested_endpoints_without_connecting_graphs() -> None:
    host = DataPipeline(id="host")
    host_output = host.define_output("host-output")
    host.set_plan_output(host_output)
    guest = DataPipeline(id="guest", label="guest-plan", plan_provenance="source")
    guest_input = guest.define_input("guest-input")
    guest_operator = guest.define_operator("select@1.0.0", label="guest-op")
    guest_output = guest.define_output("guest-output")
    guest.connect_nodes(guest_input, guest_operator)
    guest.connect_nodes(guest_operator, guest_output)
    guest.set_plan_input(guest_input)
    guest.set_plan_output(guest_output)

    host.merge(guest)

    assert host.get_plan_output_id() == host_output.get_id()
    assert host.get_plan_input_id("guest") == guest_input.get_id()
    assert host.get_plan_output_id("guest") == guest_output.get_id()
    assert host.get_plan_input("guest") is not None
    assert host.get_node(guest_input.get_id()).get_data("provenance") == "source.guest"  # type: ignore[union-attr]
    pipeline_entity = host.get_entity("guest", type=str(EntityType.DATA_PIPELINE))
    assert pipeline_entity is not None
    assert set(pipeline_entity.get_data("nodes")) == set(guest.get_nodes())
    assert host.get_prev_nodes(host_output) == []


def test_diagram_projects_retained_refinement_statuses() -> None:
    pipeline = DataPipeline(id="status-history")
    refining = pipeline.define_input("refining")
    refined = pipeline.define_output("refined")
    explicit = pipeline.define_output("explicit", properties={"progress": 0.9})
    pipeline.set_node_status(refining, Status.REFINING)
    pipeline.set_node_status(refined, Status.REFINED)
    pipeline.set_node_status(explicit, Status.REFINING)
    diagram = {
        item["data"]["name"]: item["data"] for item in pipeline.to_jsonform_diagram_json()["nodes"]
    }
    assert diagram["refining"]["status"] == Status.REFINING
    assert diagram["refined"]["status"] == Status.REFINED
    assert diagram["refining"]["progress"] == 0.5
    assert diagram["refined"]["progress"] == 0.25
    assert diagram["explicit"]["progress"] == 0.9


def test_diagram_adapter_deduplicates_edges_and_infers_progress() -> None:
    pipeline = DataPipeline()
    first = pipeline.define_input("first")
    second = pipeline.define_output("second", properties={"progress": 0.8})
    pipeline.set_node_status(first, Status.EXECUTING)
    pipeline.connect_nodes(first, second)

    diagram = pipeline.to_jsonform_diagram_json()

    by_name = {item["data"]["name"]: item["data"] for item in diagram["nodes"]}
    assert by_name["first"]["progress"] == 0.5
    assert by_name["second"]["progress"] == 0.8
    assert len(diagram["edges"]) == 1
    assert diagram["edges"][0]["source"] == first.get_id()
    assert diagram["edges"][0]["target"] == second.get_id()


def test_sync_truth_table_and_attribute_forwarding_quirk() -> None:
    calls: list[tuple[str, str, Any]] = []

    def backend(path: str, key: str, value: Any) -> None:
        calls.append((path, key, value))

    manual = DataPipeline(id="manual", sync_backend=backend, sync=False)
    manual.set_data("a", 1)
    manual.set_data("b", 2, sync=False)
    manual.set_data("c", 3, sync=True)
    assert [key for _, key, _ in calls] == ["c"]

    calls.clear()
    automatic = DataPipeline(
        id="automatic",
        sync_backend=backend,
        auto_sync=True,
        sync=False,
    )
    automatic.set_data("a", 1)
    automatic.set_data("b", 2, sync=True)
    automatic.set_data("c", 3, sync=False)
    assert [key for _, key, _ in calls] == ["a", "b"]

    calls.clear()
    manual.set_attribute("ignored", True, sync=True)
    assert calls == []
    DataPipeline(sync=True)
