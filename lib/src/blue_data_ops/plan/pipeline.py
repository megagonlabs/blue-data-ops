from __future__ import annotations

import re
import uuid
from typing import Any, TypeVar, cast

from blue_data_ops.plan.types import EntityType, NodeType, PlanRecord, Status, SyncBackend

_BaseT = TypeVar("_BaseT", bound="Base")
_PINNED_OPERATOR_ID = re.compile(r"^[^@/]+@(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHARED_OPERATOR_ATTRIBUTES: dict[str, Any] = {}


def _new_id() -> str:
    return str(hex(uuid.uuid4().fields[0]))[2:]


def _nested_value(data: PlanRecord, key: str) -> Any:
    value: Any = data
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = cast(dict[str, Any], value)[part]
    return value


def _require_pinned_operator_id(operator_id: str) -> None:
    if not _PINNED_OPERATOR_ID.fullmatch(operator_id):
        raise ValueError(
            f"operator reference must be a pinned name@<MAJOR.MINOR.PATCH>: {operator_id!r}"
        )


class Base:
    """Live-record base shared by graph nodes, entities, and plans."""

    def __init__(
        self,
        id: str | None = None,
        label: str | None = None,
        type: str | None = None,
        properties: dict[str, Any] | None = None,
        path: str | None = None,
        sync_backend: SyncBackend | None = None,
        auto_sync: bool = False,
        sync: bool | None = None,
    ) -> None:
        self.id = id if id is not None else _new_id()
        self.path = path if path is not None else "$"
        self.auto_sync = auto_sync
        self.sync_backend = sync_backend
        self._data: PlanRecord = {}
        self.synchronize(sync=sync)
        self.set_data("id", self.id, sync=sync)
        self.set_data("label", label, sync=sync)
        self.set_data("type", type, sync=sync)
        self._initialize(properties=properties, sync=sync)

    def _init_data(self, sync: bool | None = None) -> None:
        del sync

    def _initialize(
        self,
        properties: dict[str, Any] | None = None,
        sync: bool | None = None,
    ) -> None:
        self._init_data(sync=sync)
        self.set_data("properties", {}, sync=sync)
        if properties is not None:
            for key, value in properties.items():
                self.set_property(key, value, sync=sync)

    def set_data(self, key: str, value: Any, sync: bool | None = None) -> None:
        self._data[key] = value
        self.synchronize(key=key, value=value, sync=sync)

    def get_data(self, key: str | None = None) -> Any:
        if key is None:
            return self._data
        return self._data.get(key)

    def append_data(
        self,
        key: str,
        value: Any,
        unique: bool = False,
        sync: bool | None = None,
    ) -> None:
        raw_values = self.get_data(key)
        if not isinstance(raw_values, list):
            raise Exception("Data is not a list")
        values = cast(list[Any], raw_values)
        if unique and value in values:
            return
        values.append(value)
        self.synchronize(key=key, single=False, sync=sync)

    def get_id(self) -> str:
        return cast(str, self.get_data("id"))

    def get_label(self) -> str | None:
        return cast(str | None, self.get_data("label"))

    def get_type(self) -> str:
        return cast(str, self.get_data("type"))

    def set_property(self, key: str, value: Any, sync: bool | None = None) -> None:
        self.get_properties()[key] = value
        self.synchronize(key="properties." + key, value=value, sync=sync)

    def get_property(self, key: str) -> Any:
        return self.get_properties().get(key)

    def get_properties(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.get_data("properties"))

    def to_dict(self) -> PlanRecord:
        return self._data

    @classmethod
    def _validate_record(cls, data: PlanRecord) -> PlanRecord | None:
        if "id" not in data or "type" not in data:
            return None
        data.setdefault("label", None)
        data.setdefault("properties", {})
        return data

    @classmethod
    def from_dict(
        cls: type[_BaseT],
        data: PlanRecord,
        path: str | None = None,
        sync_backend: SyncBackend | None = None,
        auto_sync: bool = False,
        sync: bool | None = None,
    ) -> _BaseT:
        validated = cls._validate_record(data)
        if validated is None:
            raise Exception("Failed validation")
        instance = cls(
            id=cast(str, validated["id"]),
            path=path,
            sync_backend=sync_backend,
            auto_sync=False,
            sync=False,
        )
        instance._data = validated
        instance.id = cast(str, validated["id"])
        instance.auto_sync = auto_sync
        instance.synchronize(sync=sync)
        return instance

    def synchronize(
        self,
        key: str | None = None,
        value: Any = None,
        single: bool = True,
        sync: bool | None = None,
    ) -> None:
        del single
        if sync is None and not self.auto_sync:
            return
        if sync is False:
            return
        if self.sync_backend is None:
            return
        if key is None:
            value = self._data
            self.synchronizer(self.path, self.id, value)
            return
        if value is None:
            value = _nested_value(self._data, key)
        self.synchronizer(self.path + "." + self.id, key, value)

    def synchronizer(self, path: str, key: str, value: Any) -> None:
        if self.sync_backend is not None:
            self.sync_backend(path, key, value)


class Node(Base):
    """A node in a portable data pipeline."""

    def _init_data(self, sync: bool | None = None) -> None:
        super()._init_data(sync=sync)
        self.set_data("prev", [], sync=sync)
        self.set_data("next", [], sync=sync)

    def _add_next(self, target_id: str, sync: bool | None = None) -> None:
        self.append_data("next", target_id, unique=True)
        self.synchronize(key="next", single=False, sync=sync)

    def _add_prev(self, source_id: str, sync: bool | None = None) -> None:
        self.append_data("prev", source_id, unique=True)
        self.synchronize(key="prev", single=False, sync=sync)

    def connect_to(self, target: Node, sync: bool | None = None) -> None:
        self._add_next(target.get_id(), sync=sync)
        target._add_prev(self.get_id(), sync=sync)

    @classmethod
    def _validate_record(cls, data: PlanRecord) -> PlanRecord | None:
        validated = super()._validate_record(data)
        if validated is None:
            return None
        validated.setdefault("prev", [])
        validated.setdefault("next", [])
        return validated


class Entity(Base):
    """Metadata entity linked to one or more pipeline nodes."""

    def __init__(
        self,
        id: str | None = None,
        label: str | None = None,
        type: str | None = "Entity",
        properties: dict[str, Any] | None = None,
        path: str | None = None,
        sync_backend: SyncBackend | None = None,
        auto_sync: bool = False,
        sync: bool | None = None,
    ) -> None:
        super().__init__(
            id=id,
            label=label,
            type=type,
            properties=properties,
            path=path,
            sync_backend=sync_backend,
            auto_sync=auto_sync,
            sync=sync,
        )


class DAG(Base):
    """Directed graph stored as live node records and reciprocal edge lists."""

    def __init__(
        self,
        id: str | None = None,
        label: str | None = None,
        type: str | None = "DAG",
        properties: dict[str, Any] | None = None,
        path: str | None = None,
        sync_backend: SyncBackend | None = None,
        auto_sync: bool = False,
        sync: bool | None = None,
    ) -> None:
        super().__init__(
            id=id,
            label=label,
            type=type,
            properties=properties,
            path=path,
            sync_backend=sync_backend,
            auto_sync=auto_sync,
            sync=sync,
        )

    def _init_data(self, sync: bool | None = None) -> None:
        super()._init_data(sync=sync)
        self.set_data("nodes", {}, sync=sync)
        self.set_data("map", {}, sync=sync)

    def _verify_node(
        self,
        label: str | None = None,
        type: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        del type, properties
        return not (label and self.get_node_by_label(label))

    def create_node(
        self,
        id: str | None = None,
        label: str | None = None,
        type: str | None = None,
        properties: dict[str, Any] | None = None,
        sync: bool | None = None,
    ) -> Node:
        if not self._verify_node(label=label, type=type, properties=properties):
            raise Exception("Cannot create node due to failed varification")
        node = Node(
            id=id,
            label=label,
            type=type,
            properties=properties,
            path=self.path + "." + self.get_id() + ".nodes",
            sync_backend=self.sync_backend,
            auto_sync=self.auto_sync,
            sync=sync,
        )
        self.get_nodes()[node.get_id()] = node.get_data()
        if label:
            self.map(cast(str, node.get_label()), node.get_id(), sync=sync)
        return node

    def connect_nodes(
        self,
        f: str | Node,
        t: str | Node,
        sync: bool | None = None,
    ) -> None:
        from_node = f if isinstance(f, Node) else self.get_node(f)
        if from_node is None:
            raise Exception("Undefined from node")
        to_node = t if isinstance(t, Node) else self.get_node(t)
        if to_node is None:
            raise Exception("Undefined to node")
        from_node.connect_to(to_node, sync=sync)

    def get_nodes(self) -> dict[str, PlanRecord]:
        return cast(dict[str, PlanRecord], self.get_data("nodes"))

    def get_node(self, n: str | Node | None, cls: type[Node] | None = None) -> Node | None:
        node_cls = cls if cls is not None else Node
        if isinstance(n, node_cls):
            return n
        node = self.get_node_by_id(cast(str, n), cls=node_cls)
        if node is None:
            node = self.get_node_by_label(cast(str, n), cls=node_cls)
        return node

    def get_node_by_id(self, node_id: str, cls: type[Node] | None = None) -> Node | None:
        nodes = self.get_nodes()
        if node_id not in nodes:
            return None
        node_cls = cls if cls is not None else Node
        return node_cls.from_dict(
            nodes[node_id],
            path=self.path + "." + self.get_id() + ".nodes",
            sync_backend=self.sync_backend,
            auto_sync=self.auto_sync,
            sync=False,
        )

    def get_node_by_label(self, node_label: str, cls: type[Node] | None = None) -> Node | None:
        del cls
        labels = cast(dict[str, str], self.get_data("map"))
        if node_label in labels:
            return self.get_node_by_id(labels[node_label])
        return None

    def get_prev_nodes(self, n: str | Node) -> list[Node]:
        node = self.get_node(n)
        if node is None:
            return []
        result: list[Node] = []
        for node_id in cast(list[str], node.get_data("prev")):
            previous = self.get_node_by_id(node_id)
            if previous is not None:
                result.append(previous)
        return result

    def get_next_nodes(self, n: str | Node) -> list[Node]:
        node = self.get_node(n)
        if node is None:
            return []
        result: list[Node] = []
        for node_id in cast(list[str], node.get_data("next")):
            following = self.get_node_by_id(node_id)
            if following is not None:
                result.append(following)
        return result

    def filter_nodes(
        self,
        filter_node_type: list[str] | None = None,
        filter_hasPrev: bool | None = None,
        filter_hasNext: bool | None = None,
    ) -> dict[str, Node]:
        filtered: dict[str, Node] = {}
        for node_id in self.get_nodes():
            node = cast(Node, self.get_node(node_id))
            if filter_node_type and node.get_type() not in filter_node_type:
                continue
            if filter_hasPrev and len(cast(list[str], node.get_data("prev"))) == 0:
                continue
            if filter_hasNext and len(cast(list[str], node.get_data("next"))) == 0:
                continue
            filtered[node_id] = node
        return filtered

    def count_nodes(
        self,
        filter_node_type: list[str] | None = None,
        filter_hasPrev: bool | None = None,
        filter_hasNext: bool | None = None,
    ) -> int:
        return len(self.filter_nodes(filter_node_type, filter_hasPrev, filter_hasNext))

    def is_node_leaf(self, n: str | Node) -> bool:
        node = cast(Node, self.get_node(n))
        return bool(node.get_data("prev")) and not bool(node.get_data("next"))

    def map(self, f: str, t: str, sync: bool | None = None) -> None:
        labels = cast(dict[str, str], self.get_data("map"))
        labels[f] = t
        self.synchronize(key="map." + f, value=t, sync=sync)

    def is_mapped(self, i: str) -> bool:
        return i in cast(dict[str, str], self.get_data("map"))

    @classmethod
    def _validate_record(cls, data: PlanRecord) -> PlanRecord | None:
        validated = super()._validate_record(data)
        if validated is None:
            return None
        validated.setdefault("nodes", {})
        validated.setdefault("map", {})
        return validated


class EntityDAG(DAG):
    """Graph with typed metadata entities and node back-references."""

    def _init_data(self, sync: bool | None = None) -> None:
        super()._init_data(sync=sync)
        self.set_data("entities", {}, sync=sync)

    def verify_entity(
        self,
        label: str | None = None,
        type: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        del type, properties
        return not (label and self.is_mapped(label))

    def create_entity(
        self,
        id: str | None = None,
        label: str | None = None,
        type: str | None = None,
        properties: dict[str, Any] | None = None,
        sync: bool | None = None,
    ) -> Entity:
        if not self.verify_entity(label=label, type=type, properties=properties):
            raise Exception("Cannot create entity due to failed varification")
        if not self.has_entity_type(type):
            self.add_entity_type(type, sync=sync)
        entity = Entity(
            id=id,
            label=label,
            type=type,
            properties=properties,
            path=self.path + "." + self.get_id() + ".entities." + str(type),
            sync_backend=self.sync_backend,
            auto_sync=self.auto_sync,
            sync=sync,
        )
        self.get_entities(type=type)[entity.get_id()] = entity.get_data()
        entity.set_data("nodes", [])
        if label:
            self.map(cast(str, entity.get_label()), entity.get_id(), sync=sync)
        return entity

    def has_entity_type(self, type: str | None) -> bool:
        return type in cast(dict[str | None, dict[str, PlanRecord]], self.get_data("entities"))

    def add_entity_type(self, type: str | None, sync: bool | None = None) -> None:
        entities = cast(dict[str | None, dict[str, PlanRecord]], self.get_data("entities"))
        if type in entities:
            return
        entities[type] = {}
        self.synchronize(key="entities." + str(type), value=entities[type], sync=sync)

    def get_entities(self, type: str | None = None) -> dict[str, Any]:
        entities = cast(dict[str, Any], self.get_data("entities"))
        if type and type in entities:
            return cast(dict[str, Any], entities[type])
        return entities

    def get_entity(
        self,
        e: str | Entity | DataPipeline | None,
        type: str | None = None,
        cls: type[Entity] | None = None,
    ) -> Entity | None:
        entity_cls = cls if cls is not None else Entity
        if isinstance(e, entity_cls):
            return e
        entity = self.get_entity_by_id(cast(str, e), type=type, cls=entity_cls)
        if entity is None:
            entity = self.get_entity_by_label(cast(str, e), type=type, cls=entity_cls)
        return entity

    def get_entity_by_id(
        self,
        entity_id: str,
        type: str | None = None,
        cls: type[Entity] | None = None,
    ) -> Entity | None:
        entities = self.get_entities(type=type)
        entity_data: PlanRecord | None = None
        found_type = type
        if type:
            if entity_id in entities:
                entity_data = cast(PlanRecord, entities[entity_id])
        else:
            for entity_type, typed_entities in entities.items():
                if entity_id in typed_entities:
                    entity_data = cast(PlanRecord, typed_entities[entity_id])
                    found_type = entity_type
        if entity_data is None:
            return None
        entity_cls = cls if cls is not None else Entity
        return entity_cls.from_dict(
            entity_data,
            path=self.path + "." + self.get_id() + ".entities." + str(found_type),
            sync_backend=self.sync_backend,
            auto_sync=self.auto_sync,
            sync=False,
        )

    def get_entity_by_label(
        self,
        entity_label: str,
        type: str | None = None,
        cls: type[Entity] | None = None,
    ) -> Entity | None:
        labels = cast(dict[str, str], self.get_data("map"))
        if entity_label in labels:
            return self.get_entity_by_id(labels[entity_label], type=type, cls=cls)
        return None

    def get_nodes_by_entity(
        self,
        e: str | Entity,
        type: str | None = None,
        cls: type[Entity] | None = None,
        node_type: str | list[str] | None = None,
    ) -> list[Node]:
        entity = self.get_entity(e, type=type, cls=cls)
        if entity is None:
            return []
        result: list[Node] = []
        for node_id in cast(list[str], entity.get_data("nodes")):
            node = cast(Node, self.get_node(node_id))
            if node_type:
                if isinstance(node_type, list) and node.get_type() in node_type:
                    result.append(node)
                elif not isinstance(node_type, list) and node.get_type() == node_type:
                    result.append(node)
            else:
                result.append(node)
        return result

    def set_node_entity(
        self,
        n: str | Node,
        e: str | Entity | None,
        field: str | None = None,
        sync: bool | None = None,
    ) -> None:
        node = self.get_node(n)
        if node is None:
            raise Exception("Entity for non-existing node cannot be set")
        if e is None:
            node.set_data(field if field is not None else "Entity", None, sync=sync)
            return
        entity = self.get_entity(e)
        link_field = field if field is not None else cast(Entity, entity).get_type()
        if entity is None:
            return
        entity.append_data("nodes", node.get_id(), sync=sync)
        node.set_data(link_field, entity.get_id(), sync=sync)

    def get_node_entity(
        self,
        n: str | Node,
        type: str | None = None,
        cls: type[Entity] | None = None,
        field: str | None = None,
    ) -> Entity | None:
        node = self.get_node(n)
        if node is None:
            raise Exception("Entity for non-existing node cannot be get")
        link_field = field if field is not None else type
        if link_field is None:
            link_field = "Entity"
        return self.get_entity(cast(str | None, node.get_data(link_field)), type=type, cls=cls)

    @classmethod
    def _validate_record(cls, data: PlanRecord) -> PlanRecord | None:
        validated = super()._validate_record(data)
        if validated is None:
            return None
        validated.setdefault("entities", {})
        return validated


class Plan(EntityDAG):
    """Serializable portable plan with graph composition."""

    def __init__(
        self,
        id: str | None = None,
        label: str | None = None,
        type: str | None = "PLAN",
        properties: dict[str, Any] | None = None,
        path: str | None = None,
        sync_backend: SyncBackend | None = None,
        auto_sync: bool = False,
        sync: bool | None = None,
    ) -> None:
        super().__init__(
            id=id,
            label=label,
            type=type,
            properties=properties,
            path=path,
            sync_backend=sync_backend,
            auto_sync=auto_sync,
            sync=sync,
        )

    def merge(self, merge_plan: DataPipeline, sync: bool | None = None) -> None:
        nodes = self.get_nodes()
        entities = self.get_entities()
        merge_plan_id = merge_plan.get_id()
        merge_plan_data = merge_plan.get_data()
        self.create_entity(
            id=merge_plan_id,
            label=merge_plan.get_label(),
            type=merge_plan.get_type(),
            properties=merge_plan.get_properties(),
            sync=sync,
        )
        merge_entity = cast(Entity, self.get_entity(merge_plan_id))
        for key, value in cast(PlanRecord, merge_plan_data).items():
            if key not in {"entities", "map", "properties", "id", "label", "type", "nodes"}:
                merge_entity.set_data(key, value)
        for node_id, node_data in merge_plan.get_nodes().items():
            nodes[node_id] = node_data
            self.synchronize(key="nodes." + node_id, value=node_data, sync=sync)
            self.set_node_entity(node_id, merge_plan_id, sync=sync)
            node_label = cast(str | None, node_data["label"])
            if node_label:
                self.map(node_label, node_id, sync=sync)
        for entity_type, typed_entities in merge_plan.get_entities().items():
            if entity_type not in entities:
                self.add_entity_type(entity_type, sync=sync)
            host_entities = cast(dict[str, PlanRecord], entities[entity_type])
            for entity_id, entity_data in cast(dict[str, PlanRecord], typed_entities).items():
                host_entities[entity_id] = entity_data
                entity_label = cast(str | None, entity_data["label"])
                if entity_label:
                    self.map(entity_label, entity_id, sync=sync)


class DataPipeline(Plan):
    """Portable layered node/entity data pipeline."""

    def __init__(
        self,
        id: str | None = None,
        label: str | None = None,
        type: str = "DATA_PIPELINE",
        properties: dict[str, Any] | None = None,
        attributes: dict[str, Any] | None = None,
        path: str | None = None,
        plan_provenance: str | None = None,
        plan_input: str | Node | None = None,
        plan_output: str | Node | None = None,
        sync_backend: SyncBackend | None = None,
        auto_sync: bool = False,
        sync: bool | None = None,
    ) -> None:
        super().__init__(
            id=id,
            label=label,
            type=type,
            properties=properties,
            path=path,
            sync_backend=sync_backend,
            auto_sync=auto_sync,
            sync=sync,
        )
        self.set_plan_provenance(plan_provenance if plan_provenance is not None else "$", sync=sync)
        self.set_plan_input(plan_input, sync=sync)
        self.set_plan_output(plan_output, sync=sync)
        self.set_data("attributes", {}, sync=sync)
        if attributes is not None:
            for key, value in attributes.items():
                self.set_attribute(key, value, sync=sync)

    def set_attribute(self, key: str, value: Any, sync: bool | None = None) -> None:
        del sync
        self.get_attributes()[key] = value
        self.synchronize(key="attributes." + key, value=value)

    def get_attribute(self, key: str) -> Any:
        return self.get_attributes().get(key)

    def get_attributes(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.get_data("attributes"))

    def set_plan_provenance(
        self,
        plan_provenance: str,
        sync: bool | None = None,
    ) -> None:
        self.set_data("provenance", plan_provenance, sync=sync)

    def get_plan_provenance(self) -> str:
        return cast(str, self.get_data("provenance"))

    def set_plan_input_id(self, input_id: str | Node | None, sync: bool | None = None) -> None:
        self.set_plan_input(input_id, sync=sync)

    def set_plan_input(self, i: str | Node | None, sync: bool | None = None) -> None:
        input_id: str | Node | None = i
        input_node = self.get_node(i)
        if input_node is not None:
            input_id = input_node.get_id()
        self.set_data("input", input_id, sync=sync)

    def get_plan_input_id(self, pipeline: str | DataPipeline | None = None) -> str | None:
        if pipeline is None:
            return cast(str | None, self.get_data("input"))
        pipeline_entity = cast(Entity, self.get_entity(pipeline))
        return cast(str | None, pipeline_entity.get_data("input"))

    def get_plan_input(self, pipeline: str | DataPipeline | None = None) -> Node | None:
        return self.get_node(self.get_plan_input_id(pipeline=pipeline))

    def set_plan_output_id(self, output_id: str | Node | None, sync: bool | None = None) -> None:
        self.set_plan_output(output_id, sync=sync)

    def set_plan_output(self, o: str | Node | None, sync: bool | None = None) -> None:
        output_id: str | Node | None = o
        output_node = self.get_node(o)
        if output_node is not None:
            output_id = output_node.get_id()
        self.set_data("output", output_id, sync=sync)

    def get_plan_output_id(self, pipeline: str | DataPipeline | None = None) -> str | None:
        if pipeline is None:
            return cast(str | None, self.get_data("output"))
        pipeline_entity = cast(Entity, self.get_entity(pipeline))
        return cast(str | None, pipeline_entity.get_data("output"))

    def get_plan_output(self, pipeline: str | DataPipeline | None = None) -> Node | None:
        return self.get_node(self.get_plan_output_id(pipeline=pipeline))

    def set_node_value(
        self,
        n: str | Node,
        value: Any = None,
        provenance: str | None = None,
        sync: bool | None = None,
    ) -> None:
        node = cast(Node, self.get_node(n))
        node.set_data("value", value, sync=sync)
        if provenance:
            values = cast(dict[str, Any], node.get_data("values"))
            values[provenance] = value
            node.synchronize(key="values." + provenance, value=value, sync=sync)

    def get_node_value(self, n: str | Node, provenance: str | None = None) -> Any:
        node = cast(Node, self.get_node(n))
        if provenance:
            return cast(dict[str, Any], node.get_data("values")).get(provenance)
        return node.get_data("value")

    def get_node_values(self, n: str | Node) -> dict[str, Any]:
        node = cast(Node, self.get_node(n))
        return cast(dict[str, Any], node.get_data("values"))

    def set_node_status(
        self,
        n: str | Node,
        status: Status | str | None = None,
        provenance: str | None = None,
        sync: bool | None = None,
    ) -> None:
        node = cast(Node, self.get_node(n))
        node.set_data("status", status, sync=sync)
        if provenance:
            statuses = cast(dict[str, Status | str | None], node.get_data("statuses"))
            statuses[provenance] = status
            node.synchronize(key="statuses." + provenance, value=status, sync=sync)

    def get_node_status(
        self,
        n: str | Node,
        provenance: str | None = None,
    ) -> Status | str | None:
        node = cast(Node, self.get_node(n))
        if provenance:
            return cast(dict[str, Status | str | None], node.get_data("statuses")).get(provenance)
        return cast(Status | str | None, node.get_data("status"))

    def get_node_statuses(self, n: str | Node) -> dict[str, Status | str | None]:
        node = cast(Node, self.get_node(n))
        return cast(dict[str, Status | str | None], node.get_data("statuses"))

    def set_node_provenance(self, n: str | Node) -> None:
        node = cast(Node, self.get_node(n))
        node.set_data("provenance", self.get_plan_provenance() + "." + self.get_id())

    def define_input(
        self,
        label: str | None = None,
        value: Any = None,
        provenance: str | None = None,
        properties: dict[str, Any] | None = None,
        sync: bool | None = None,
    ) -> Node:
        node = self.create_node(
            label=label,
            type=str(NodeType.INPUT),
            properties=properties,
            sync=sync,
        )
        node.set_data("values", {}, sync=sync)
        node.set_data("statuses", {}, sync=sync)
        self.set_node_value(node, value=value, provenance=provenance, sync=sync)
        self.set_node_provenance(node)
        return node

    def define_output(
        self,
        label: str | None = None,
        value: Any = None,
        provenance: str | None = None,
        properties: dict[str, Any] | None = None,
        sync: bool | None = None,
    ) -> Node:
        node = self.create_node(
            label=label,
            type=str(NodeType.OUTPUT),
            properties=properties,
            sync=sync,
        )
        node.set_data("values", {}, sync=sync)
        node.set_data("statuses", {}, sync=sync)
        self.set_node_value(node, value=value, provenance=provenance, sync=sync)
        self.set_node_provenance(node)
        return node

    def define_operator(
        self,
        name: str,
        label: str | None = None,
        attributes: dict[str, Any] | None = None,
        properties: dict[str, Any] | None = None,
        sync: bool | None = None,
    ) -> Node:
        if cast(str | None, name) is None:
            raise Exception("Name is not specified")
        _require_pinned_operator_id(name)
        node = self.create_node(
            label=label,
            type=str(NodeType.OPERATOR),
            properties=properties,
            sync=sync,
        )
        node.set_data("values", {}, sync=sync)
        node.set_data("statuses", {}, sync=sync)
        operator = self.create_operator(
            name,
            attributes=attributes,
            properties=properties,
            sync=sync,
        )
        self.set_node_entity(node, operator, sync=sync)
        self.set_node_provenance(node)
        return node

    def create_operator(
        self,
        name: str,
        label: str | None = None,
        attributes: dict[str, Any] | None = None,
        properties: dict[str, Any] | None = None,
        sync: bool | None = None,
    ) -> Entity:
        _require_pinned_operator_id(name)
        operator = self.create_entity(
            label=label,
            type=str(EntityType.OPERATOR),
            properties=properties,
            sync=sync,
        )
        operator.set_data("operator_id", name)
        operator.set_data(
            "attributes",
            _SHARED_OPERATOR_ATTRIBUTES if attributes is None else attributes,
        )
        return operator

    def merge(self, merge_plan: DataPipeline, sync: bool | None = None) -> None:
        merge_plan_id = merge_plan.get_id()
        merge_plan_nodes = merge_plan.get_nodes()
        super().merge(merge_plan, sync=sync)
        merge_plan_provenance = merge_plan.get_plan_provenance()
        for node_id in merge_plan_nodes:
            node = cast(Node, self.get_node(node_id))
            node.set_data("provenance", merge_plan_provenance + "." + merge_plan_id, sync=sync)

    def to_jsonform_diagram_json(self) -> dict[str, Any]:
        diagram_nodes: list[dict[str, Any]] = []
        diagram_edges: list[dict[str, Any]] = []
        for node_id in self.get_nodes():
            node = self.get_node(node_id)
            if node is None:
                continue
            status = node.get_data("status") or str(Status.INITED)
            progress = node.get_property("progress")
            if progress is None:
                if status == str(Status.EXECUTED):
                    progress = 1
                elif status in {str(Status.EXECUTING), str(Status.REFINING)}:
                    progress = 0.5
                elif status in {str(Status.PLANNED), str(Status.REFINED)}:
                    progress = 0.25
                else:
                    progress = 0
            description = node.get_property("description")
            if not description:
                if node.get_type() == str(NodeType.OPERATOR):
                    description = "Operator"
                    entity = self.get_node_entity(node_id, type=str(EntityType.OPERATOR))
                    if entity is not None:
                        description = f"Operator: {entity.get_data('operator_id')}"
                else:
                    description = f"Type: {node.get_type() or None}"
            diagram_nodes.append(
                {
                    "id": f"node-{node_id}",
                    "type": "status",
                    "data": {
                        "name": node.get_label() or node_id,
                        "description": description,
                        "status": status,
                        "progress": progress,
                    },
                }
            )
        seen_edges: set[tuple[str, str]] = set()
        for source_id in self.get_nodes():
            source = self.get_node(source_id)
            if source is None:
                continue
            for target_id in cast(list[str], source.get_data("next") or []):
                edge = (str(source_id), str(target_id))
                if edge in seen_edges:
                    continue
                seen_edges.add(edge)
                diagram_edges.append(
                    {
                        "id": f"edge-{_new_id()}",
                        "source": str(source_id),
                        "target": str(target_id),
                        "type": "smoothstep",
                        "animated": True,
                        "style": {"strokeWidth": 2},
                    }
                )
        return {"nodes": diagram_nodes, "edges": diagram_edges}


__all__ = ["DataPipeline", "Entity", "Node", "Plan"]
